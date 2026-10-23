"""Star (RFC 0041): the owner's mark on a line worth keeping — `logbook star`, `logbook unstar`, and
the star on a row of the Day page, which calls the same functions.

A star is a `star/v1` line at the starred line's `at` and at its tier, `source` `manual`, naming the
line and its kind, with the owner's `note` when one was given: it is on its line's day for every
reader of a day, and it crosses where its line crosses and nowhere else (a tier is where a line may
travel, never who wrote it). A photo is starred with `keeper/v1` instead (RFC 0024 and its amendment
of 2026-10-14): a keeper of lane `memory`, `source` `manual`, at the photo's tier, the Day's hero and
the press's pick, so a photo with a `memory` keeper standing, the library's favourite included, is
starred already. A line has one star standing; starring it again with another note supersedes it,
with the same note or none writes nothing. A model's draft (`draft/v1`, RFC 0036: the dream's draft
of a day, a call's synthesis) takes no star: it is a proposal, not the owner's to keep as a memory,
and what it says is confirmed by signing the day or by starring the lines it rests on; a reader
drops a star on one, and shows a star only beside a line it shows (`shown`), so no star makes a
draft the policy withholds, or a line above the reader's gate, visible. Unstarring is a retraction
(RFC 0003) of the standing star, or of each standing `memory` keeper of a photo, at the mark's tier,
so the unstar travels where the star did.

`star` and `unstar` read and append under one hold of the writer lock (`Logbook.writer`) and read the
head again before appending: when another writer moved it in between, `HeadMoved` and nothing
written, as `day sign` does. `standing` is the reader: the stars standing, keyed by the line they
mark; `listed` the stars of a window for the Days page. Nothing here opens a socket."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from . import day_start, drafts, keepers, reading, stays
from .chain import Line
from .store import RETRACTION, HeadMoved, Logbook, now_utc, retractions

KIND = "star"
SCHEMA = "star/v1"
SOURCE = "manual"  # the owner's act, from the command line or through the page
PHOTO = "photo"  # a photo's star is a keeper (RFC 0024)
MARKS = (KIND, keepers.KIND, RETRACTION)  # the kinds a star never names
UNKEPT = (drafts.KIND,)  # a model's draft (RFC 0036): a proposal, never the owner's to keep
REASON = "unstarred"  # the retraction's reason: the act, in the record's words
TITLE_CHARS = 72  # a note's first line, as the Day names it
SYMBOL = "★"
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)  # where a stamp no reader parses sorts


class StarError(ValueError):
    """A star or an unstar the record refuses; the message says why and nothing is written."""


class NotStarred(StarError):
    """An unstar of a line with no star standing: unstarred already, or never starred."""


@dataclass(frozen=True)
class Star:
    """One star standing: the line it marks, the star or keeper line, the marked line's kind, the
    owner's note, and the mark's tier."""

    line: str
    star: str
    kind: str
    note: str | None
    tier: int

    def to_json(self) -> dict[str, Any]:
        return {"line": self.line, "star": self.star, "kind": self.kind, "note": self.note}


# -- the reader -------------------------------------------------------------------------------------------


def target_of(line: Line) -> str | None:
    """The id of the line a mark stars: a star's `line`, a `memory` keeper's photo; None for any
    other line (an `art` keeper is the Art album's mark, not a star)."""
    payload = line.get("payload") or {}
    if line.get("kind") == KIND and payload.get("schema") == SCHEMA:
        found = payload.get("line")
        return found if isinstance(found, str) and found else None
    if line.get("kind") == keepers.KIND and payload.get("lane") == keepers.MEMORY:
        return keepers.photo_id_of(line)
    return None


def keepable(line: Line) -> bool:
    """Whether a star may name `line`: neither a mark itself (a star, a keeper, a retraction) nor a
    model's draft."""
    return line.get("kind") not in (*MARKS, *UNKEPT)


def shown(found: Mapping[str, Star], lines: Mapping[str, Line]) -> dict[str, Star]:
    """The stars of `found` a reader shows: those on a line among `lines`, the lines it read through
    its own gate, that a star may name (`keepable`). A star on a line the reader does not show, or
    on a model's draft, is not shown either."""
    return {target: s for target, s in found.items() if target in lines and keepable(lines[target])}


def beside(line: Line, crossing: Collection[str]) -> bool:
    """Whether `line` may cross in a package whose lines are `crossing` (rule 5): a star, and a
    photo's `memory` keeper, only beside the line it marks; a star whose payload cannot be read here
    (sealed, and no identity to open it) never; every other line, an `art` keeper included, as it is."""
    target = target_of(line)
    if line.get("kind") == KIND:
        return target is not None and target in crossing
    return target is None or target in crossing


def standing(lines: Iterable[Line], retracted: Collection[str] = ()) -> dict[str, Star]:
    """The stars standing among `lines` (star, keeper and retraction lines, in any order), keyed by
    the id of the line each marks: a mark not retracted and not named in a later mark's
    `supersedes` (SPEC §3.2, *standing*), the latest per line; none on a line that is retracted.
    `retracted` adds the ids a caller already knows are retracted to those `lines` retract."""
    ordered = sorted(lines, key=lambda line: int(line["seq"]))
    retracted = {*retracted, *retractions(line for line in ordered if line.get("kind") == RETRACTION)}
    superseded = {
        str(by)
        for line in ordered
        if line.get("kind") in (KIND, keepers.KIND)
        and isinstance(by := (line.get("payload") or {}).get("supersedes"), str)
    }
    found: dict[str, Star] = {}
    for line in ordered:
        target = target_of(line)
        id_ = str(line["id"])
        if target is None or id_ in retracted or id_ in superseded or target in retracted:
            continue
        payload = line.get("payload") or {}
        note = payload.get("note")
        kind = str(payload.get("kind") or "") if line.get("kind") == KIND else PHOTO
        found[target] = Star(target, id_, kind, note if isinstance(note, str) else None, int(line["tier"]))
    return found


def listed(lb: Logbook, first: str, last: str, tiers: Sequence[int] | None = None) -> list[dict[str, Any]]:
    """The stars standing on the lines of `[first, last]` (local days), through the gate `tiers`,
    in the order of the lines they mark: `{day, at, kind, title, line, star, note}` each."""
    days = day_start.of(lb.meta)
    with lb.index() as idx:
        marks = reading.crossing(
            [*idx.by_kind(KIND, first, last), *idx.by_kind(keepers.KIND, first, last)], tiers
        )
        found = standing([*marks, *idx.retractions()])
        lines = idx.by_ids(found)
    out = []
    for target, star in found.items():
        line = lines.get(target)
        if line is None or not keepable(line):
            continue  # a star on a line the reader does not show, or on a model's draft, is not listed
        if tiers is not None and int(line.get("tier") or 0) not in tiers:
            continue
        out.append(
            {
                "day": days.day_of(str(line["at"])),
                "at": str(line["at"]),
                "kind": str(line.get("kind")),
                "title": title(line),
                "line": target,
                "star": star.star,
                "note": star.note,
            }
        )
    out.sort(key=lambda s: (stays.instant(s["at"]) or EPOCH, s["line"]))
    return out


def title(line: Line) -> str:
    """What a starred line is called where it is listed: a photo's file name, an entry's or a
    recording's title, a note's first line, a mail's subject, a flight's route, else its kind."""
    payload = line.get("payload") or {}
    kind = line.get("kind")
    if kind == PHOTO:
        return str(payload.get("file_name") or payload.get("asset_id") or "a photo")
    if kind == "note":
        text = str(payload.get("text") or payload.get("title") or "").strip()
        first = text.splitlines()[0] if text else "(empty)"
        return first if len(first) <= TITLE_CHARS else first[: TITLE_CHARS - 1] + "…"
    if kind == "mail":
        return str(payload.get("subject") or "(no subject)")
    if kind == "flight":
        route = f"{_code(payload.get('from'))} → {_code(payload.get('to'))}"
        number = f"{payload.get('carrier') or ''} {payload.get('number') or ''}".strip()
        return f"{number}  {route}" if number else route
    for key in ("title", "name", "text"):
        if isinstance(payload.get(key), str) and payload[key].strip():
            return str(payload[key]).strip().splitlines()[0]
    return str(kind)


def _code(place: object) -> str:
    if isinstance(place, dict):
        return str(place.get("iata") or place.get("icao") or "?")
    return str(place or "?")


def mark(starred: Collection[str], *line_ids: str | None) -> str:
    """For a reader's row: the star and a space when any of `line_ids` is starred, else nothing."""
    return f"{SYMBOL} " if any(id_ is not None and id_ in starred for id_ in line_ids) else ""


def text(line: Line) -> str:
    """A star line as `show` prints it: `★ event 0199… · the table by the window`."""
    payload = line.get("payload") or {}
    note = payload.get("note")
    head = f"{SYMBOL} {payload.get('kind') or '?'} {str(payload.get('line') or '?')[:8]}…"
    return f"{head} · {note}" if isinstance(note, str) and note else head


# -- the writers ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Read:
    """What a star or an unstar reads under the lock: the line named, its marks, the retractions."""

    line: Line
    marks: list[Line]
    retracted: frozenset[str]
    superseded_by: int | None


def _read(lb: Logbook, ref: str) -> _Read:
    """The line `ref` names (an id, or `#N` or `N` for seq N), the star and keeper lines of its day,
    and the record's retractions. `StarError` when the record has no such line."""
    text_ = ref.strip()
    with lb.index() as idx:
        digits = text_.removeprefix("#")
        line = idx.by_seq(int(digits)) if digits.isdigit() else idx.by_id(text_)
        if line is None:
            raise StarError(f"no line {text_!r} in the record; a star names a line by its id or #seq")
        day = day_start.of(lb.meta).day_of(str(line["at"]))
        marks = [*idx.by_kind(KIND, day, day), *idx.by_kind(keepers.KIND, day, day)]
        retracted = frozenset(retractions(idx.retractions()))
        superseded = idx.superseded(str(line.get("kind")))
    return _Read(line, marks, retracted, superseded.get(str(line["id"])))


def _check_head(lb: Logbook, meta: dict[str, Any], what: str) -> None:
    now = lb.meta
    if now["head"] != meta["head"]:
        raise HeadMoved(
            f"the record's head moved from seq {meta['seq']} to seq {now['seq']} while {what} was read;"
            " nothing was written"
        )


def note_of(note: str | None) -> str | None:
    """The note as a star keeps it: one line, its spaces trimmed; None for none or a blank."""
    if note is None:
        return None
    if "\n" in note or "\r" in note:
        raise StarError("a star's note is one line; put the rest in a note on the day (`logbook add`)")
    return " ".join(note.split()) or None


def checked(lb: Logbook, ref: str) -> tuple[Line, Star | None]:
    """The line `ref` names, if it takes a star, and its star standing (None when it has none); read
    without writing, so a caller that writes more than the star (Keep and sign, RFC 0043 §5) checks it
    before its first line. `StarError` for a line that takes no star, as `star` refuses it."""
    found = _read(lb, ref)
    line, id_ = found.line, str(found.line["id"])
    kind = str(line.get("kind"))
    if kind in MARKS:
        raise StarError(f"#{line['seq']} is a {kind}, a mark itself; star the line it names")
    if kind in UNKEPT:
        raise StarError(
            f"#{line['seq']} is a model's draft ({drafts.SCHEMA}), a proposal and not yours to keep:"
            " star the lines it rests on, or sign the day to confirm what it says"
        )
    if id_ in found.retracted:
        raise StarError(f"#{line['seq']} is retracted; a star names a line that stands")
    if found.superseded_by is not None:
        raise StarError(f"#{line['seq']} is superseded by #{found.superseded_by}; star that one")
    return line, standing(found.marks, found.retracted).get(id_)


def star(lb: Logbook, ref: str, note: str | None = None) -> tuple[Line, Line | None]:
    """Star the line `ref` names: (the line, the star or keeper line written), the second None when
    the line is starred already with this note or none. `StarError` for a line that takes no star."""
    note = note_of(note)
    with lb.writer():
        meta = lb.meta
        line, current = checked(lb, ref)
        kind = str(line.get("kind"))
        if current is not None and (note is None or note == current.note):
            return line, None
        draft = _keeper(line, note) if kind == PHOTO else _star(line, note)
        if current is not None:
            draft["payload"]["supersedes"] = current.star
        _check_head(lb, meta, f"#{line['seq']}")
        return line, lb.append(**draft)


def _star(line: Line, note: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"schema": SCHEMA, "line": str(line["id"]), "kind": str(line.get("kind"))}
    if note is not None:
        payload["note"] = note
    return {
        "at": str(line["at"]),
        "source": SOURCE,
        "kind": KIND,
        "tier": int(line["tier"]),
        "payload": payload,
    }


def _keeper(photo: Line, note: str | None) -> dict[str, Any]:
    """The photo's star: RFC 0024's draft, made by the owner (`manual`), at the photo's tier."""
    draft = keepers.draft(photo, keepers.MEMORY)
    draft["source"] = SOURCE
    draft["tier"] = int(photo["tier"])
    draft["payload"]["source"] = SOURCE
    if note is not None:
        draft["payload"]["note"] = note
    return draft


def unstar(lb: Logbook, ref: str) -> tuple[Line, list[Line]]:
    """Take back the star on the line `ref` names, or on the line the star or `memory` keeper `ref`
    is marks: (the starred line, the retractions written), one per mark standing on that line, each
    at its mark's tier, whichever of its marks `ref` named (a superseded star names the line its
    successor stands on). `NotStarred` when nothing on it stands; `StarError` for an `art` keeper,
    the Art album's mark and no star."""
    with lb.writer():
        meta = lb.meta
        found = _read(lb, ref)
        line, id_ = found.line, str(found.line["id"])
        kind = str(line.get("kind"))
        if kind in (KIND, keepers.KIND):
            target = target_of(line)
            if target is None:  # an `art` keeper: the Art album's mark, which no star made
                lane = (line.get("payload") or {}).get("lane")
                raise StarError(f"#{line['seq']} is a keeper of lane {lane}, not a star; nothing written")
        else:
            target = id_
        marks = _standing_marks(found.marks, found.retracted, target)  # rule 4: the marks that stand
        if not marks:
            named = f"#{line['seq']}" if target == id_ else f"the line #{line['seq']} marks"
            raise NotStarred(f"{named} is not starred; nothing written")
        _check_head(lb, meta, f"#{line['seq']}")
        written = [
            lb.append(
                at=now_utc(),
                source=SOURCE,
                kind=RETRACTION,
                tier=int(mark["tier"]),
                payload={
                    "schema": "retraction/v1",
                    "supersedes": str(mark["id"]),
                    "seq": int(mark["seq"]),
                    "reason": REASON,
                },
            )
            for mark in marks
        ]
    starred = line
    if target is not None and target != id_:
        with lb.index() as idx:
            starred = idx.by_id(target) or line
    return starred, written


def _standing_marks(marks: Iterable[Line], retracted: Collection[str], target: str) -> list[Line]:
    """Every mark on `target` that stands, in chain order: a photo may carry the library's memory
    keeper and the owner's both, and an unstar takes back each."""
    ordered = sorted(marks, key=lambda m: int(m["seq"]))
    superseded = {
        str(by) for m in ordered if isinstance(by := (m.get("payload") or {}).get("supersedes"), str)
    }
    return [
        m
        for m in ordered
        if target_of(m) == target and str(m["id"]) not in retracted and str(m["id"]) not in superseded
    ]
