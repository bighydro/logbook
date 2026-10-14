"""What the owner decided — `logbook status KIND ENTITY DISPOSITION [--reason "…"] [--at DATE]` and
`logbook status list KIND` (RFC 0037 §9; decisions 5, 6, 9, 10 and 11).

**The writer.** One `status/v1` line, `source` `manual`, tier 2, for an org, an idea, a place or an
asset, with one of its kind's dispositions; a person has no status, and a goal is reviewed by RFC
0036's `review/v1`. The entity is named as `review` and the pages name one (a ref, an id, a label
or an alias, a word of a label: `entities.lookup`). The line supersedes the standing status of the
entity, so the current status is the last line standing; any status may follow any. A status equal
to the standing one is refused on the same local day, and on a later day unless it comes with a new
reason (the owner reaffirmed, and said why). `--reason` writes one `note/v1` beside it, tier 2,
label `status`, the reason as its text, the status line's id under `extra`, so the owner's words
are on the day and in `search`. A place let go and an asset sold or let go close their registry
entry: `until`, the line's local day, is written into the entry of `places.json` or `assets.json`,
every other key kept; the entry is never deleted (ADR 0018, rule 4). Everything is read and written
under one hold of the writer lock, and the head is read again before the first line: a head that
moved is `HeadMoved`, and nothing is written.

`--at DATE` is the local day the owner disposed: today is now, a day before is its last minute,
a day ahead is refused. No money is ever on the line; the ledger holds it.

**The list.** `status list KIND` is every canonical entity of the kind with its current status, the
day it took effect, who proposed it and why, the registry's `until`, whether it is stale (a reader's
rule: `policy/entities.json` `stale_days`, a `hold` over three years and an `exploring` over two) and
the dispositions the dream may not propose for it (decision 6: a status with a reason that answered
a proposal of another disposition mutes that disposition for `mute_days`, 365). Nothing is written."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from ..core import assets, day_start, notes, places, stays
from ..core.chain import Line
from ..core.export import parse_day
from ..core.store import HeadMoved, Logbook
from . import entities
from .entities import DISPOSITIONS, PLACE

KIND = entities.STATUS
NOTE_LABEL = "status"
HEAD_MOVED = (
    "the record's head moved from seq {was} to seq {now} while the status was read, so the line"
    " would rest on a record it did not read; nothing was written"
)
NONE = "—"


class StatusError(ValueError):
    """A status the record refuses; the message says why and nothing is written."""


@dataclass(frozen=True)
class Written:
    entity: entities.Entity
    status: Line
    note: Line | None
    until: str | None  # the day the registry entry was closed with, when it was

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.entity.kind,
            "entity": self.entity.id,
            "label": self.entity.label,
            "status": self.status["payload"]["status"],
            "line": str(self.status["id"]),
            "note": None if self.note is None else str(self.note["id"]),
            "until": self.until,
        }


def check_kind(kind: str) -> None:
    """Refuse a kind that takes no status: a person, a goal, anything not org, idea, place, asset."""
    if kind in entities.NO_STATUS:
        raise StatusError(entities.NO_STATUS[kind])
    if kind not in DISPOSITIONS:
        raise StatusError(f"a status is for an {', '.join(DISPOSITIONS)}; not for {kind!r}")


def _read(
    lb: Logbook,
) -> tuple[dict[tuple[str, str], entities.Entity], dict[tuple[str, str], list[entities.Status]]]:
    with lb.index() as idx:
        marks = idx.retractions()
        lines = [*marks, *idx.resolutions(), *idx.by_kind(entities.ENTITY)]
        found = entities.statuses([*marks, *idx.by_kind(KIND)])
    return entities.known(lines, lb.root), found


def moment(lb: Logbook, day: str | None, today: str | None = None) -> str:
    """When the owner disposed, in UTC: now, or for `--at DATE` the day's moment (`notes.moment`:
    now when it is today, its last minute when it is past); a day ahead of today is refused."""
    days = day_start.of(lb.meta)
    now_day = today if today is not None else notes.today_in(days)
    if day is None:
        return notes.moment(now_day, str(lb.meta["timezone"]), None, now_day, days)
    try:
        wanted = parse_day(day.strip()).isoformat()
    except ValueError as e:
        raise StatusError(f"--at {day!r} is not a day, YYYY-MM-DD") from e
    if wanted > now_day:
        raise StatusError(f"--at {wanted} is after today ({now_day}); a status is what you decided, not will")
    return notes.moment(wanted, str(lb.meta["timezone"]), None, now_day, days)


def write(
    lb: Logbook,
    kind: str,
    name: str,
    disposition: str,
    reason: str | None = None,
    at: str | None = None,
    proposal: Mapping[str, Any] | None = None,
    today: str | None = None,
) -> Written:
    """One `status/v1` line for the entity of `kind` that `name` names, with its note when there is
    a `reason`, and the registry entry closed when the disposition closes one; under one hold of the
    writer lock, the head read again before the first line. `proposal` is what the dream proposed,
    when the owner answers one (`proposed_by` `dream`). `StatusError` or `entities.EntityError` says
    why a status is refused; `HeadMoved` when another writer moved the record."""
    check_kind(kind)
    if disposition not in DISPOSITIONS[kind]:
        raise StatusError(
            f"{disposition!r} is not an {kind}'s status; one of {', '.join(DISPOSITIONS[kind])}"
        )
    reason = " ".join(reason.split()) if reason is not None else None
    if reason == "":
        raise StatusError("--reason is empty; say why, or leave it out")
    if disposition in entities.REASON_REQUIRED and reason is None:
        raise StatusError(f'a status of {disposition} must say why: --reason "…"')
    with lb.writer():
        meta = lb.meta
        stamp = moment(lb, at, today)
        local = day_start.of(meta)
        day = local.day(_instant(stamp)).isoformat()
        known, found = _read(lb)
        entity = entities.lookup(known, kind, name)
        history = found.get((kind, entity.id), [])
        current = history[-1] if history else None
        if current is not None and current.status == disposition:
            since = current.day(_local(local))
            if since == day:
                raise StatusError(f"{entity.label} is {disposition} since {day} already; one status a day")
            if reason is None or reason == current.reason:
                raise StatusError(
                    f"{entity.label} is {disposition} since {since} already;"
                    ' to reaffirm it, say why: --reason "…"'
                )
        payload = entities.status_payload(
            kind,
            entity.id,
            entity.label,
            disposition,
            reason,
            proposed_by="dream" if proposal is not None else entities.METHOD,
            proposal=proposal,
            supersedes=None if current is None else current.line,
            head=str(meta["head"]),
        )
        problems = entities.validate_status(payload) + entities.tier_problems(
            entities.STATUS_SCHEMA, entities.TIER, {}
        )
        if problems:
            raise StatusError(problems[0])
        now = lb.meta
        if now["head"] != meta["head"]:
            raise HeadMoved(HEAD_MOVED.format(was=meta["seq"], now=now["seq"]))
        line = lb.append(at=stamp, source=entities.SOURCE, kind=KIND, tier=entities.TIER, payload=payload)
        note = None
        if reason is not None:
            note = lb.append(
                at=stamp,
                source=entities.SOURCE,
                kind=notes.KIND,
                tier=notes.TIER,
                payload={
                    "schema": notes.SCHEMA,
                    "text": reason,
                    "labels": [NOTE_LABEL],
                    "extra": {
                        "status": str(line["id"]),
                        "entity": entities.entity_ref(kind, entity.id),
                        "label": entity.label,
                        "disposition": disposition,
                    },
                },
            )
        until = None
        if disposition in entities.CLOSING.get(kind, ()) and entity.registry:
            close(lb.root, kind, entity.id, day)
            until = day
    return Written(entity, line, note, until)


def close(root: Path, kind: str, entity_id: str, day: str) -> Path:
    """Close a registry entry with `until`: the place of `places.json` named `entity_id`, or the
    asset of `assets.json` with that id; every other key of the file and the entry kept, the entry
    never deleted. Written to a temporary file and renamed into place."""
    path = places.path_of(root) if kind == PLACE else assets.assets_path(root)
    document = json.loads(path.read_text(encoding="utf-8"))
    if kind == PLACE:
        entry = document.get(entity_id) if isinstance(document, dict) else None
    else:
        entries = document.get("assets") if isinstance(document, dict) else None
        entry = next(
            (e for e in entries or [] if isinstance(e, dict) and e.get("id") == entity_id),
            None,
        )
    if not isinstance(entry, dict):
        raise StatusError(f"{path} has no entry {entity_id!r} to close")
    entry["until"] = day
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes((json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    os.replace(temporary, path)
    return path


# -- the list ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Row:
    entity: entities.Entity
    current: entities.Status | None
    since: str | None
    stale: bool
    muted: tuple[tuple[str, str], ...]  # (disposition, the last day it is muted)
    until: str | None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.entity.id,
            "label": self.entity.label,
            "key": self.entity.key,
            "status": None if self.current is None else self.current.status,
            "since": self.since,
            "reason": None if self.current is None else self.current.reason,
            "proposed_by": None if self.current is None else self.current.proposed_by,
            "line": None if self.current is None else self.current.line,
            "stale": self.stale,
            "muted": [{"status": s, "until": d} for s, d in self.muted],
            "until": self.until,
        }


@dataclass(frozen=True)
class Listing:
    kind: str
    rows: list[Row]
    on: str

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "on": self.on, "entities": [r.to_json() for r in self.rows]}


def listing(lb: Logbook, kind: str, today: str | None = None) -> Listing:
    """Every canonical entity of `kind` with its current status and the readers' rules over it,
    the most recent status first, then those with none by label. Writes nothing."""
    check_kind(kind)
    settings = entities.read_settings(lb.root)
    days = day_start.of(lb.meta)
    on = date.fromisoformat(today if today is not None else notes.today_in(days))
    local = _local(days)
    known, found = _read(lb)
    rows = []
    for (k, entity_id), entity in sorted(known.items()):
        if k != kind:
            continue
        history = found.get((kind, entity_id), [])
        current = history[-1] if history else None
        muted = []
        for disposition in DISPOSITIONS[kind]:
            hold = entities.muted(history, disposition, on, local, settings.mute_days)
            if hold is not None:
                start = date.fromisoformat(hold.day(local))
                muted.append(
                    (disposition, date.fromordinal(start.toordinal() + settings.mute_days - 1).isoformat())
                )
        closing = current is not None and current.status in entities.CLOSING.get(kind, ())
        until = (
            current.day(local) if current is not None and closing else None
        )  # the line's, never the file's
        rows.append(
            Row(
                entity,
                current,
                None if current is None else current.day(local),
                current is not None and entities.stale(current, on, local, settings.stale_days),
                tuple(muted),
                until,
            )
        )
    rows.sort(
        key=lambda r: (
            r.current is None,
            "" if r.since is None else _reverse(r.since),
            r.entity.label.casefold(),
        )
    )
    return Listing(kind, rows, on.isoformat())


def rows(found: Listing) -> Iterator[str]:
    single = found.kind
    yield f"status · {len(found.rows)} {single}{'' if len(found.rows) == 1 else 's'} · {found.on}"
    if not found.rows:
        yield f"no {single} yet: `review {single}` names them"
        return
    width = max(len(r.entity.label) for r in found.rows)
    for r in found.rows:
        if r.current is None:
            yield f"  {r.entity.label:<{width}}  {NONE}"
            continue
        who = r.current.proposed_by or "owner"
        if r.current.proposal is not None and who == "dream":
            who = f"dream proposed {r.current.proposal}"
        parts = [f"{r.current.status} since {r.since} ({who})"]
        if r.until is not None:
            parts.append(f"until {r.until}")
        if r.stale:
            parts.append("stale")
        if r.muted:
            parts.append("not proposed: " + ", ".join(f"{s} to {d}" for s, d in r.muted))
        yield f"  {r.entity.label:<{width}}  {' · '.join(parts)}"
        if r.current.reason:
            yield f"  {'':<{width}}  reason: {r.current.reason}"


def written_rows(w: Written) -> Iterator[str]:
    status = w.status["payload"]["status"]
    yield f"{w.entity.label}: {status} (#{w.status['seq']})"
    if w.note is not None:
        yield f"  the reason as a note (#{w.note['seq']})"
    if w.until is not None:
        registry = places.PLACES_FILE if w.entity.kind == PLACE else assets.ASSETS_FILE
        yield f"  closed in {registry} with until {w.until}"


def _instant(stamp: str) -> Any:
    found = stays.instant(stamp)
    assert found is not None
    return found


def _local(days: day_start.DayStart) -> Any:
    return lambda at: days.day(_instant(str(at))).isoformat()


def _reverse(day: str) -> str:
    """A key that sorts later days first."""
    return "".join(chr(0x7F - ord(c)) for c in day)
