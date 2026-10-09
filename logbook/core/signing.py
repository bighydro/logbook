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
never held to a wording. Nothing here is a setting; nothing but `sign` writes.

Amendment 1, dispositions: beside confirming a line, the owner may say what became of the
commitment on it. The payload's optional `dispositions` maps a confirmed line's id to one of four
words: `kept`, `missed`, `dropped` (let go on purpose) or `carried` (still open, taken to a later
day). A line given a disposition is confirmed by that; an id not in `confirmed`, or a fifth word, is
invalid, and a reader keeps the valid entries and never fails on the rest (`dispositions_of`). The
field is optional, so a signature without it is what it was and its hash does not move; the page
digest does not change. `day` prints a symbol next to each disposed line, `promises` closes a kept
or dropped promise and flags a missed one, and the crossing carries the field as it carries the
line.

Amendment 2, an empty confirmation and the owner's clock: `confirm=[]` (`--confirm none`) signs
the day with nothing confirmed, an empty `confirmed` over the page digest as shown, so that a day
whose every proposed fact the owner unticked is still signed; it goes alone, with no disposition.
And `at` is the moment the owner clicked, which on a phone is hours before the command runs:
given as an RFC 3339 moment with an offset or Z, checked by `moment` (not beyond five minutes in
the future, for clock skew; not before the day signed starts in the record's zone) and stored in
UTC as every `at` is. Without `at` the signing moment is now, as before."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from datetime import UTC, datetime, time, timedelta
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo

from .chain import Line, canonical_json
from .export import parse_day
from .index import Index
from .store import RETRACTION, Logbook, now_utc, retractions, utc

KIND = "signed-day"
SCHEMA = "signed-day/v1"
SOURCE = "manual"  # the owner signed it: not a tool, not an adapter
TIER = 1  # the line names a day, ids, a digest and a count, never what a line said
KEPT, MISSED, DROPPED, CARRIED = "kept", "missed", "dropped", "carried"
DISPOSITIONS = (KEPT, MISSED, DROPPED, CARRIED)  # amendment 1: what became of the commitment on a line
CLOSING = (KEPT, MISSED, DROPPED)  # the dispositions that close a promise; `carried` leaves it open
SYMBOLS = {KEPT: "\u2713", MISSED: "\u2717", DROPPED: "\u2013", CARRIED: "\u2192"}  # tick, cross, dash, arrow
DISPOSITION_WORDS = "kept, missed, dropped or carried"
SHA256_HEX = 64
NOTHING = "none"  # `--confirm none`: nothing on the page is a fact of the day (amendment 2)
SKEW = timedelta(minutes=5)  # how far ahead of this clock the owner's clock may be (amendment 2)
AT_EXAMPLE = "2026-06-09T19:30:00+02:00"
_MOMENT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})\Z")


class SignError(ValueError):
    """A signature the record refuses; the message says what and nothing is written."""


class Disposition(NamedTuple):
    """What the standing signature of a day says became of the commitment on one of its lines: the
    word, the day signed, and the id of the signature line that says so."""

    value: str
    day: str
    line: str


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


def disposed_lines(idx: Index, owner: str | None = None) -> dict[str, Disposition]:
    """By line id, the disposition the standing signature of the line's day gives it (amendment 1),
    over the whole record: what `promises` asks to close a kept or dropped promise, flag a missed one
    and leave a carried one open. A superseded or retracted signature's dispositions say nothing."""
    found: dict[str, Disposition] = {}
    for day, line in standing(idx, owner).items():
        for id_, value in dispositions_of(line.get("payload") or {}).items():
            found[id_] = Disposition(value, day, str(line["id"]))
    return found


# -- signing ---------------------------------------------------------------------------------------------


def sign(
    lb: Logbook,
    day: str,
    confirm: Sequence[str] | None = None,
    note: str | None = None,
    at: str | None = None,
    recorded_at: str | None = None,
    dispositions: Mapping[str, Sequence[str]] | None = None,
) -> Line:
    """Sign `day`: one `signed-day/v1` line appended, nothing else touched. `confirm` names the
    lines confirmed, each a `seq` or an id of a line on the page (a line not on the page, or a
    retracted one, is refused and nothing is written); None confirms every line of the page not
    retracted; an empty sequence confirms nothing (amendment 2, `--confirm none`), and then no
    disposition may be given. `dispositions` maps each of `kept`, `missed`, `dropped`, `carried` to
    the entries (seqs or ids, as `confirm` takes them) of the lines that became so (amendment 1):
    every such line is confirmed, whatever `confirm` says, and a line given two dispositions is
    refused. `note` is one line. `at` is when the owner signed, an RFC 3339 moment with an offset
    or Z, stored in UTC (amendment 2: not beyond five minutes ahead of this clock, not before the
    day starts in the record's zone); now by default. When the day has a standing signature the new
    line supersedes it. `SignError` says why a signature is refused."""
    day = parse_day(day).isoformat()
    if note is not None:
        note = note.strip()
        if "\n" in note or "\r" in note:
            raise SignError("a note is one line; put the rest in a note/v1 line on the day")
        if not note:
            note = None
    meta = lb.meta
    owner, tz = str(meta["owner_id"]), str(meta["timezone"])
    signed_at = moment(at, day, tz) if at is not None else now_utc()
    with lb.index() as idx:
        lines = page(idx, day)
        retracted = retractions(idx.retractions())
        earlier = standing(idx, owner).get(day)
    disposed = _dispositions(day, lines, retracted, dispositions)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "day": day,
        "subject": owner,
        "confirmed": _confirmed(day, lines, retracted, confirm, disposed),
        "page": {"sha256": page_digest(day, tz, lines), "lines": len(lines)},
    }
    if disposed:
        payload["dispositions"] = disposed
    if note is not None:
        payload["note"] = note
    if earlier is not None:
        payload["supersedes"] = str(earlier["id"])
    return lb.append(
        at=signed_at,
        source=SOURCE,
        kind=KIND,
        tier=TIER,
        payload=payload,
        recorded_at=recorded_at,
    )


def moment(at: str, day: str, tz: str, now: datetime | None = None) -> str:
    """`at` as the owner's clock gave it, checked and returned in UTC (amendment 2): an RFC 3339
    moment with a numeric offset or Z (anything else is refused with the example), not beyond
    `SKEW` ahead of `now` (this clock; a phone's clock runs a few minutes fast, a signature from
    the future is not one), and not before `day` starts in the record's zone `tz` (a day is signed
    on it or after it, never before it was lived). A Z stamp is kept as given; an offset is
    converted, as every `at` of the record is."""
    text = at.strip()
    parsed: datetime | None = None
    if _MOMENT.match(text):
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
    if parsed is None:
        raise SignError(f"--at {text!r} is not an RFC 3339 moment with an offset or Z, e.g. {AT_EXAMPLE}")
    clock = now if now is not None else datetime.now(UTC)
    if parsed > clock + SKEW:
        raise SignError(f"--at {text} is in the future; a signature is when you signed, not later")
    start = datetime.combine(parse_day(day), time(), tzinfo=ZoneInfo(tz))
    if parsed < start:
        raise SignError(f"--at {text} is before {day} starts in {tz}; a day is signed on it or after it")
    return utc(text)


def _confirmed(
    day: str,
    lines: Sequence[Line],
    retracted: Collection[str],
    confirm: Sequence[str] | None,
    also: Collection[str] = (),
) -> list[str]:
    """The ids confirmed, in the page's order: every line not retracted, or the ones `confirm`
    names by `seq` or id, and `also` (the lines given a disposition) either way; nothing at all
    for an empty `confirm` (amendment 2), which then takes no disposition."""
    if confirm is None:
        return [str(line["id"]) for line in lines if str(line["id"]) not in retracted]
    if len(confirm) == 0:
        if also:
            raise SignError(
                f"--confirm {NOTHING} goes alone: a line given a disposition is confirmed, and none is"
            )
        return []
    chosen: set[str] = set(also)
    for entry in confirm:
        line = _on_page(day, lines, retracted, entry)
        if line is not None:
            chosen.add(str(line["id"]))
    if not chosen:
        raise SignError("--confirm names no line; leave it out to confirm every line on the page")
    return [str(line["id"]) for line in lines if str(line["id"]) in chosen]


def _dispositions(
    day: str, lines: Sequence[Line], retracted: Collection[str], given: Mapping[str, Sequence[str]] | None
) -> dict[str, str]:
    """Line id → disposition, in the page's order, from the entries given per word; refused when a
    word is not one of the four, an entry is not a line on the page, a line is given twice (by seq
    or by id, in one flag or two), or a flag names no line at all."""
    if not given:
        return {}
    chosen: dict[str, str] = {}
    for value, entries in given.items():
        if value not in DISPOSITIONS:
            raise SignError(f"{value!r} is not a disposition; a line is {DISPOSITION_WORDS}")
        named = 0
        for entry in entries:
            line = _on_page(day, lines, retracted, entry)
            if line is None:
                continue
            named += 1
            id_ = str(line["id"])
            if id_ in chosen:
                raise SignError(
                    f"#{line['seq']} is given twice ({chosen[id_]} and {value}); a line has one disposition"
                )
            chosen[id_] = value
        if not named:
            raise SignError(f"--{value} names no line; leave it out when no line was {value}")
    return {str(line["id"]): chosen[str(line["id"])] for line in lines if str(line["id"]) in chosen}


def _on_page(day: str, lines: Sequence[Line], retracted: Collection[str], entry: str) -> Line | None:
    """The line of the page `entry` names, by `seq` or id; None for a blank entry. An entry that
    names no line on the page, or a retracted line, is refused naming it."""
    text = entry.strip()
    if not text:
        return None
    if text.isdigit():
        line = next((line for line in lines if int(line["seq"]) == int(text)), None)
    else:
        line = next((line for line in lines if str(line["id"]) == text), None)
    if line is None:
        raise SignError(f"{text!r} is not a line on the page of {day}; `logbook show {day}` lists them")
    if str(line["id"]) in retracted:
        raise SignError(f"#{line['seq']} is retracted; a retracted line is not a fact of the day")
    return line


# -- validation ------------------------------------------------------------------------------------------


def validate(payload: Mapping[str, Any]) -> list[str]:
    """The problems of a `signed-day/v1` payload (RFC 0034 and its amendment 1), each one plain
    sentence; empty when the payload is valid. `dispositions`, when present, is an object whose keys
    are ids in `confirmed` and whose values are one of the four words."""
    problems: list[str] = []
    if payload.get("schema") != SCHEMA:
        problems.append(f"schema is {payload.get('schema')!r}, not {SCHEMA!r}")
    day = payload.get("day")
    try:
        if not isinstance(day, str):
            raise ValueError(day)
        parse_day(day)
    except ValueError:
        problems.append(f"day {day!r} is not a local day, YYYY-MM-DD")
    if not isinstance(payload.get("subject"), str) or not payload["subject"]:
        problems.append("subject must name who signed, the record's owner_id")
    confirmed = payload.get("confirmed")
    if not isinstance(confirmed, list) or not all(isinstance(id_, str) for id_ in confirmed):
        problems.append("confirmed must be a list of line ids")
        confirmed = []
    elif len(set(confirmed)) != len(confirmed):
        problems.append("confirmed names a line twice")
    page_info = payload.get("page")
    if not isinstance(page_info, dict):
        problems.append("page must be an object {sha256, lines}")
    else:
        digest = page_info.get("sha256")
        if not isinstance(digest, str) or len(digest) != SHA256_HEX or set(digest) - set("0123456789abcdef"):
            problems.append("page.sha256 must be the page digest, 64 lowercase hex characters")
        count = page_info.get("lines")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            problems.append("page.lines must be how many lines were on the page")
        elif count < len(confirmed):
            problems.append("page.lines is smaller than the number of lines confirmed")
    note = payload.get("note")
    if note is not None and (not isinstance(note, str) or "\n" in note or "\r" in note):
        problems.append("note must be one line of text")
    if "supersedes" in payload and not isinstance(payload["supersedes"], str):
        problems.append("supersedes must be the id of the earlier signature")
    if "dispositions" in payload:
        found = payload["dispositions"]
        if not isinstance(found, dict):
            problems.append("dispositions must be an object mapping a confirmed line's id to its disposition")
        else:
            for id_, value in found.items():
                if id_ not in confirmed:
                    problems.append(f"dispositions names {id_}, which is not in confirmed")
                if value not in DISPOSITIONS:
                    problems.append(f"the disposition of {id_} is {value!r}; a line is {DISPOSITION_WORDS}")
    return problems


def dispositions_of(payload: Mapping[str, Any]) -> dict[str, str]:
    """The dispositions a signature gives, id → word, the valid entries only: an id that is not in
    `confirmed`, a word that is not one of the four, or a field that is not an object are left out
    and never fail a reader (SPEC §5). Empty when the field is absent."""
    found = payload.get("dispositions")
    confirmed = payload.get("confirmed")
    if not isinstance(found, dict) or not isinstance(confirmed, list):
        return {}
    return {
        str(id_): str(value)
        for id_, value in found.items()
        if id_ in confirmed and isinstance(value, str) and value in DISPOSITIONS
    }


def counts_text(dispositions: Mapping[str, str]) -> str:
    """`kept 2, missed 1`: how many lines got each word, in the four words' order; empty for none."""
    counts = {value: sum(1 for v in dispositions.values() if v == value) for value in DISPOSITIONS}
    return ", ".join(f"{value} {n}" for value, n in counts.items() if n)


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
        "dispositions": dispositions_of(payload),
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
    """A signature's row in `show`: `signed 2026-03-01: 4 lines confirmed of 4 · kept 1, missed 1 ·
    <note>`, the counts only when the signature gives dispositions."""
    confirmed = payload.get("confirmed")
    found = payload.get("page")
    page_info: dict[str, Any] = found if isinstance(found, dict) else {}
    n = len(confirmed) if isinstance(confirmed, list) else 0
    on_page = page_info.get("lines", "?")
    text = f"signed {payload.get('day')}: {n} line{'s' if n != 1 else ''} confirmed of {on_page}"
    counts = counts_text(dispositions_of(payload))
    if counts:
        text = f"{text} · {counts}"
    note = payload.get("note")
    return f"{text} · {note}" if isinstance(note, str) and note else text


def mark(dispositions: Mapping[str, str] | None, *line_ids: str | None) -> str:
    """For a reader's row: the symbol of the disposition the first of `line_ids` has (a tick for
    kept, a cross for missed, a dash for dropped, an arrow for carried), with a space after it, or
    nothing: a row on an unsigned day, or a line given none, prints as it did."""
    if not dispositions:
        return ""
    for id_ in line_ids:
        if id_ is not None and id_ in dispositions:
            return f"{SYMBOLS[dispositions[id_]]} "
    return ""


def _instant(stamp: str) -> datetime:
    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
