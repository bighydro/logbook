"""The signed day (RFC 0034, `signed-day/v1`): the owner's reading of a day's page, recorded as one
tier-1 line.

Agents draft; the owner signs; only signed days cross. `sign` appends the line through
`Logbook.append` and rewrites nothing: the day signed, the owner as subject, the ids of the lines
the owner confirmed as the day's facts, the digest of the page as shown, an optional one-line note,
and, when the day was signed before, the id of the signature this one supersedes. The readers ask
`standing` which days are signed: the latest `signed-day` line per day whose subject is the owner
and that is not retracted. The crossing (`crossing.select`) crosses the lines of signed days by
default; `show` and `day` say in their header whether a day is signed.

The page digest is over hashes, not text: the page of a day is every line SPEC §3.2.1 lists on it
(every kind but `retraction` and `signed-day`, a retracted line included, in the day's order, by
instant then `seq`), and the digest is the SHA-256 of `canonical_json({"day", "tz", "lines": [the
hashes]})`, so any implementation recomputes it from the record alone and the owner's words are
never held to a wording. Nothing here is a setting; nothing but `sign` writes."""

from __future__ import annotations

import hashlib
from collections.abc import Collection, Iterable, Sequence
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .chain import Line, canonical_json
from .export import parse_day
from .index import Index
from .store import RETRACTION, Logbook, now_utc, retractions, utc

KIND = "signed-day"
SCHEMA = "signed-day/v1"
SOURCE = "manual"  # the owner signed it: not a tool, not an adapter
TIER = 1  # the line names a day, ids, a digest and a count, never what a line said


class SignError(ValueError):
    """A signature the record refuses; the message says what and nothing is written."""


# -- the page --------------------------------------------------------------------------------------------


def page(idx: Index, day: str, lines: Iterable[Line] | None = None) -> list[Line]:
    """The page of `day` as `show` lists it (SPEC §3.2.1): every line of the local day but the
    retractions (a mark on another line's day) and the signatures (about the page, never on it), a
    retracted line included, by the instant of `at` then `seq`. `lines` are the day's lines when the
    caller has read them already, else they are read through the index."""
    found = idx.day(day) if lines is None else lines
    kept = [line for line in found if line.get("kind") not in (RETRACTION, KIND)]
    kept.sort(key=lambda line: (_instant(str(line["at"])), int(line["seq"])))
    return kept


def page_digest(day: str, tz: str, lines: Sequence[Line]) -> str:
    """The digest of the page as shown (RFC 0034): SHA-256 of the canonical JSON of the day, the
    record's zone and the hashes of the page's lines in the page's order."""
    text = canonical_json({"day": day, "tz": tz, "lines": [str(line["hash"]) for line in lines]})
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# -- the standing signatures ------------------------------------------------------------------------------


def signatures(lines: Iterable[Line], retracted: Collection[str], owner: str | None) -> dict[str, Line]:
    """The standing signature per day: of the `signed-day` lines, the latest by `seq` naming the
    day whose subject is `owner` (any subject when `owner` is None) and that is not retracted."""
    found: dict[str, Line] = {}
    for line in sorted(lines, key=lambda line: int(line["seq"])):
        payload = line.get("payload") or {}
        if line.get("kind") != KIND or payload.get("schema") != SCHEMA:
            continue
        if str(line["id"]) in retracted:
            continue
        if owner is not None and payload.get("subject") != owner:
            continue
        day = payload.get("day")
        if isinstance(day, str):
            found[day] = line
    return found


def standing(idx: Index, owner: str | None = None) -> dict[str, Line]:
    """The standing signature per day, read through the index."""
    return signatures(idx.by_kind(KIND), retractions(idx.retractions()), owner)


def gate(idx: Index, owner: str | None = None) -> tuple[set[str], dict[str, str]]:
    """For the crossing: the days with a standing signature, and, for every `signed-day` line
    standing or not, the day it signs by the line's id (a signature crosses with its day)."""
    lines = idx.by_kind(KIND)
    signed = set(signatures(lines, retractions(idx.retractions()), owner))
    signs = {str(line["id"]): str((line.get("payload") or {}).get("day")) for line in lines}
    return signed, signs


def signature_of(idx: Index, day: str, owner: str | None = None) -> Line | None:
    return standing(idx, owner).get(day)


# -- signing ---------------------------------------------------------------------------------------------


def sign(
    lb: Logbook,
    day: str,
    confirm: Sequence[str] | None = None,
    note: str | None = None,
    at: str | None = None,
    recorded_at: str | None = None,
) -> Line:
    """Sign `day`: one `signed-day/v1` line appended, nothing else touched. `confirm` names the
    lines confirmed, each a `seq` or an id of a line on the page (a line not on the page, or a
    retracted one, is refused and nothing is written); None confirms every line of the page not
    retracted. `note` is one line. `at` is when the owner signed (now by default). When the day has
    a standing signature the new line supersedes it. `SignError` says why a signature is refused."""
    day = parse_day(day).isoformat()
    if note is not None:
        note = note.strip()
        if "\n" in note or "\r" in note:
            raise SignError("a note is one line; put the rest in a note/v1 line on the day")
        if not note:
            note = None
    meta = lb.meta
    owner, tz = str(meta["owner_id"]), str(meta["timezone"])
    with lb.index() as idx:
        lines = page(idx, day)
        retracted = retractions(idx.retractions())
        earlier = standing(idx, owner).get(day)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "day": day,
        "subject": owner,
        "confirmed": _confirmed(day, lines, retracted, confirm),
        "page": {"sha256": page_digest(day, tz, lines), "lines": len(lines)},
    }
    if note is not None:
        payload["note"] = note
    if earlier is not None:
        payload["supersedes"] = str(earlier["id"])
    return lb.append(
        at=utc(at) if at else now_utc(),
        source=SOURCE,
        kind=KIND,
        tier=TIER,
        payload=payload,
        recorded_at=recorded_at,
    )


def _confirmed(
    day: str, lines: Sequence[Line], retracted: Collection[str], confirm: Sequence[str] | None
) -> list[str]:
    """The ids confirmed, in the page's order: every line not retracted, or the ones `confirm`
    names by `seq` or id."""
    if confirm is None:
        return [str(line["id"]) for line in lines if str(line["id"]) not in retracted]
    by_seq = {int(line["seq"]): line for line in lines}
    by_id = {str(line["id"]): line for line in lines}
    chosen: set[str] = set()
    for entry in confirm:
        text = entry.strip()
        if not text:
            continue
        line = by_seq.get(int(text)) if text.isdigit() else by_id.get(text)
        if line is None:
            raise SignError(f"{text!r} is not a line on the page of {day}; `logbook show {day}` lists them")
        if str(line["id"]) in retracted:
            raise SignError(f"#{line['seq']} is retracted; a retracted line is not a fact of the day")
        chosen.add(str(line["id"]))
    if not chosen:
        raise SignError("--confirm names no line; leave it out to confirm every line on the page")
    return [str(line["id"]) for line in lines if str(line["id"]) in chosen]


# -- what the readers show --------------------------------------------------------------------------------


def signed_json(
    signature: Line | None, tz: str, lines: Sequence[Line] | None, day: str | None = None
) -> dict[str, Any] | None:
    """The Day's `signed` block (RFC 0034 rule 6): None for an unsigned day; else when, which line,
    how many lines were confirmed and on the page, the page digest, whether the page today still
    digests to it (`None` when `lines` are not the whole page: a gated reader), the note and what
    it supersedes."""
    if signature is None:
        return None
    payload = signature.get("payload") or {}
    found = payload.get("page")
    page_info: dict[str, Any] = found if isinstance(found, dict) else {}
    digest = page_info.get("sha256")
    confirmed = payload.get("confirmed")
    at = str(signature["at"])
    matches: bool | None = None
    if lines is not None and isinstance(digest, str):
        matches = page_digest(day or str(payload.get("day")), tz, lines) == digest
    return {
        "at": at,
        "at_local": _instant(at).astimezone(ZoneInfo(tz)).isoformat(timespec="seconds"),
        "line": str(signature["id"]),
        "seq": int(signature["seq"]),
        "confirmed": len(confirmed) if isinstance(confirmed, list) else None,
        "lines": page_info.get("lines"),
        "page_sha256": digest,
        "page_matches": matches,
        "note": payload.get("note"),
        "supersedes": payload.get("supersedes"),
    }


def state_text(signed: dict[str, Any] | None) -> str:
    """`unsigned`, or `signed 2026-03-02 09:00` (local, to the minute), with `, the page has changed
    since` when the page no longer digests to what was signed: the header of `show` and `day`."""
    if signed is None:
        return "unsigned"
    when = str(signed["at_local"])[:16].replace("T", " ")
    text = f"signed {when}"
    return f"{text}, the page has changed since" if signed.get("page_matches") is False else text


def row_text(payload: dict[str, Any]) -> str:
    """A signature's row in `show`: `signed 2026-03-01: 4 lines confirmed of 4 · <note>`."""
    confirmed = payload.get("confirmed")
    found = payload.get("page")
    page_info: dict[str, Any] = found if isinstance(found, dict) else {}
    n = len(confirmed) if isinstance(confirmed, list) else 0
    on_page = page_info.get("lines", "?")
    text = f"signed {payload.get('day')}: {n} line{'s' if n != 1 else ''} confirmed of {on_page}"
    note = payload.get("note")
    return f"{text} · {note}" if isinstance(note, str) and note else text


def _instant(stamp: str) -> datetime:
    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
