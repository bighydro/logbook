"""What the owner decided — `logbook status KIND ENTITY DISPOSITION [--reason "…"] [--at DATE]` and
`logbook status list KIND` (RFC 0037 §9; decisions 5, 6, 9, 10 and 11).

**The writer.** One `status/v1` line, `source` `manual`, for an org, an idea, a place or an asset,
with one of its kind's dispositions, at the kind's tier (`entities.status_tier`, RFC 0037 §8): 3 for
an org, whose dispositions describe a position in money, so the line may cite tier-3 evidence; 2 for
an idea, a place or an asset, which never cites a tier-3 line. A person has no status, and a goal is
reviewed by RFC 0036's `review/v1`. The entity is named as `review` and the pages name one (a ref,
an id, a label or an alias, a word of a label: `entities.lookup`). The line supersedes the standing
status of the entity, so the current status is the last line standing; any status may follow any. A
status equal to the standing one is refused on the same local day, and on a later day unless it
comes with a new reason (the owner reaffirmed, and said why). `--reason` puts the owner's words in
the status line's own `reason`, and for an idea, a place or an asset first writes one `note/v1`, tier
2 as RFC 0010 makes every note (MUST), label `status`, the reason as its text, the entity under
`extra.entity` and never the disposition, and then the status line, whose `note` names it (RFC 0037
§10.5), so the owner's words are on the day and in `search`; a pair written before the writer kept
that order (the status line first, the note naming it under `extra.status`) is read the same. An
org's reason stays on its tier-3 line and is never a note: a reason about a company can name money,
and a note at 2 would carry it wherever tier 2 crosses. No note is ever written above tier 2 (SPEC §4: a MUST
tier is the profile's). A place let go and an asset sold or let go close their registry entry:
`until`, the line's local day, is written into the entry of `places.json` or `assets.json`, every
other key kept; the entry is never deleted (ADR 0018, rule 4). Everything is read and written under
one hold of the writer lock, and the head is read again before the first line: a head that moved is
`HeadMoved`, and nothing is written.

`--at DATE` is the local day the owner disposed: today is now, a day before is its last minute,
a day ahead is refused. No money is ever on the line; the ledger holds it.

**The portfolio** (RFC 0037 §10.2, amended 15 October 2026). `--portfolio TEXT` names which portfolio
holds an org (`Fund I`), free text, its words collapsed, in the status line's `portfolio` field;
`--portfolio ""` writes the field empty, which clears it; a status without it leaves the portfolio
as it stood (`entities.portfolios` reads the latest line that carries the field). Only an org's
status takes one: a portfolio given for an idea, a place or an asset is refused in one sentence
before anything is read or written. It rides on the org's tier-3 line, never on an `entity/v1` line,
which is tier 2. A status equal to the standing one that moves the portfolio (to another one, case
and spaces aside, or to none) says something new and is written, on its day too; one that moves
nothing is refused as above, and "one status a day" reads the standing line's own day. A line that
repeats the standing status only to move the portfolio, with no new reason, is no reaffirmation:
it carries `since`, the day the standing status took effect, so the status's day and its stale
flag do not move; one with a new reason reaffirms, and restarts both.

**The list.** `status list KIND` is every canonical entity of the kind with its current status, the
day it took effect, who proposed it and why, the registry's `until`, whether it is stale (a reader's
rule: `policy/entities.json` `stale_days`, a `hold` over three years and an `exploring` over two) and
the dispositions the dream may not propose for it (decision 6: a status with a reason that answered
a proposal of another disposition mutes that disposition for `mute_days`, 365). Nothing is written."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from ..core import assets, day_start, notes, places, stays
from ..core.chain import Line
from ..core.export import parse_day
from ..core.store import HeadMoved, Logbook
from . import entities
from .entities import DISPOSITIONS, PLACE

KIND = entities.STATUS
NOTE_LABEL = entities.STATUS_NOTE_LABEL
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

    @property
    def portfolio(self) -> str | None:
        """The `portfolio` the line carries: None when none, the empty string when it clears one."""
        return entities.portfolio_field(self.status["payload"])

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.entity.kind,
            "entity": self.entity.id,
            "label": self.entity.label,
            "status": self.status["payload"]["status"],
            "line": str(self.status["id"]),
            "note": None if self.note is None else str(self.note["id"]),
            "until": self.until,
            "portfolio": self.portfolio,
        }


def check_kind(kind: str) -> None:
    """Refuse a kind that takes no status: a person, a goal, anything not org, idea, place, asset."""
    if kind in entities.NO_STATUS:
        raise StatusError(entities.NO_STATUS[kind])
    if kind not in DISPOSITIONS:
        raise StatusError(f"a status is for an {', '.join(DISPOSITIONS)}; not for {kind!r}")


def check_portfolio(kind: str, portfolio: str | None) -> str | None:
    """The portfolio as it would be written, its words collapsed (empty: it clears one), or None for
    none given; refused, one sentence, when the kind is not an org (RFC 0037 §10.2, amended 15
    October 2026: it rides on an org's tier-3 status line and on no other kind's)."""
    if portfolio is None:
        return None
    if kind != entities.ORG:
        article = "an" if kind[:1] in ("a", "e", "i", "o", "u") else "a"
        raise StatusError(
            f"a portfolio is an org's, on its tier-3 status line; {article} {kind}'s status takes none"
        )
    return " ".join(portfolio.split())


def _read(
    lb: Logbook,
) -> tuple[
    dict[tuple[str, str], entities.Entity], dict[tuple[str, str], list[entities.Status]], dict[str, str]
]:
    """The canonical entities, the standing status lines of each, every status joined to its reason
    note (`entities.statuses`), and each org's portfolio, read from every status line not retracted
    (`entities.portfolios`: a line a later one supersedes still counts). A line names its note
    (`note`, RFC 0037 §10.5); an idea's, a
    place's or an asset's standing line with a reason and no `note`, written before the note came
    first, is named by its note instead, so only then are notes read: the `manual` notes labelled
    `status` of the days of those lines, where the writer put each note, at its line's `at`."""
    with lb.index() as idx:
        marks = idx.retractions()
        lines = [*marks, *idx.resolutions(), *idx.by_kind(entities.ENTITY)]
        said = idx.by_kind(KIND)
        older = [line for line in entities.standing([*marks, *said], KIND) if _older(line["payload"])]
        reasons = []
        if older:
            local = day_start.of(lb.meta)
            days = sorted(local.day(_instant(str(line["at"]))) for line in older)
            # a day either side: the index's day of a line was derived under the day start of its time
            first, last = (
                (days[0] - timedelta(days=1)).isoformat(),
                (days[-1] + timedelta(days=1)).isoformat(),
            )
            reasons = [
                n
                for n in idx.of_kind(notes.KIND, first, last, source=entities.SOURCE)
                if notes.labelled(n, NOTE_LABEL)
            ]
        found = entities.statuses([*marks, *said, *reasons])
        held = entities.portfolios([*marks, *said])
    return entities.known(lines, lb.root), found, held


def _older(payload: Mapping[str, Any]) -> bool:
    """Whether a status line was written before the note came first: a reason a note carries, and
    no `note` naming it."""
    kind = entities.kind_of(payload.get("entity"))
    return kind is not None and reason_note(kind) and "reason" in payload and "note" not in payload


def _cited(lb: Logbook, evidence: Sequence[str]) -> dict[str, int]:
    """The tier of each line `evidence` names that the record has (line id → tier)."""
    if not evidence:
        return {}
    with lb.index() as idx:
        return {line_id: int(line.get("tier", 0)) for line_id, line in idx.by_ids(evidence).items()}


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
    evidence: Sequence[str] = (),
    portfolio: str | None = None,
) -> Written:
    """One `status/v1` line for the entity of `kind` that `name` names, at the kind's tier
    (`entities.status_tier`), the `reason` on it; with the reason also as a tier-2 note when the
    line is no higher than a note (`reason_note`: an idea, a place or an asset, never an org),
    written first and named by the line's `note` (RFC 0037 §10.5), and the registry entry closed
    when the disposition closes one; under one hold of the writer lock, everything checked and the
    head read again before the first line, so a refused status writes nothing. `proposal` is what
    the dream proposed, when the owner answers one (`proposed_by` `dream`), and `evidence` the ids of
    the lines it rested on: a status about an idea, a place or an asset that cites a tier-3 line is
    refused (`entities.tier_problems`); one about an org may. `StatusError` or
    `entities.EntityError` says why a status is refused; `HeadMoved` when another writer moved the
    record. `portfolio`, an org's only (`check_portfolio`), is written in the line's `portfolio`
    field, empty to clear it; a status equal to the standing one is written when it moves it."""
    check_kind(kind)
    portfolio = check_portfolio(kind, portfolio)
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
        known, found, held = _read(lb)
        cited = _cited(lb, evidence)
        entity = entities.lookup(known, kind, name)
        history = found.get((kind, entity.id), [])
        current = history[-1] if history else None
        standing_in = held.get(entity.id)
        moves = portfolio is not None and entities.fold(portfolio) != entities.fold(standing_in or "")
        same = current is not None and current.status == disposition
        if current is not None and same and not moves:
            since = current.day(_local(local))
            already = f"{entity.label} is {disposition} since {since}"
            if portfolio is not None:  # given, and moving nothing: the portfolio that stands, respelled
                already += f" in {standing_in}" if standing_in else " in no portfolio"
            if _local(local)(current.at) == day:  # the line's own day (RFC 0037 §9)
                raise StatusError(f"{already} already; one status a day")
            if reason is None or reason == current.reason:
                raise StatusError(f'{already} already; to reaffirm it, say why: --reason "…"')
        # a line that repeats the standing status only to move the portfolio says when the status
        # took effect, as the standing line does: it is no reaffirmation (RFC 0037 §9, 15 October)
        carried = current is not None and same and (reason is None or reason == current.reason)
        fields: dict[str, Any] = {
            "proposed_by": "dream" if proposal is not None else entities.METHOD,
            "proposal": proposal,
            "evidence": evidence,
            "supersedes": None if current is None else current.line,
            "head": str(meta["head"]),
            "portfolio": portfolio,
            "since": current.day(_local(local)) if carried and current is not None else None,
        }
        payload = entities.status_payload(kind, entity.id, entity.label, disposition, reason, **fields)
        tier = entities.status_tier(kind)
        problems = entities.validate_status(payload) + entities.tier_problems(
            entities.STATUS_SCHEMA, tier, cited, kind
        )
        if problems:
            raise StatusError(problems[0])
        now = lb.meta
        if now["head"] != meta["head"]:
            raise HeadMoved(HEAD_MOVED.format(was=meta["seq"], now=now["seq"]))
        note = None
        if reason is not None and reason_note(kind):  # first the note, then the line naming it (§10.5)
            note = lb.append(
                at=stamp,
                source=entities.SOURCE,
                kind=notes.KIND,
                tier=notes.TIER,
                payload={
                    "schema": notes.SCHEMA,
                    "text": reason,
                    "labels": [NOTE_LABEL],
                    "extra": {"entity": entities.entity_ref(kind, entity.id)},
                },
            )
            payload = entities.status_payload(
                kind, entity.id, entity.label, disposition, reason, note=str(note["id"]), **fields
            )
        line = lb.append(at=stamp, source=entities.SOURCE, kind=KIND, tier=tier, payload=payload)
        until = None
        if disposition in entities.CLOSING.get(kind, ()) and entity.registry:
            close(lb.root, kind, entity.id, day)
            until = day
    return Written(entity, line, note, until)


def reason_note(kind: str) -> bool:
    """Whether a status reason about an entity of `kind` is also written as a `note/v1`: only when
    the status line's tier is no higher than a note's, which RFC 0010 fixes at 2 (MUST), so the note
    shows nothing the line keeps higher. An org's status is tier 3, so its reason stays on the line."""
    return entities.reason_note(kind)


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
    portfolio: str | None = None  # an org's, from the latest status line that carries one

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
            "note": None if self.current is None else self.current.note,
            "stale": self.stale,
            "muted": [{"status": s, "until": d} for s, d in self.muted],
            "until": self.until,
            "portfolio": self.portfolio,
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
    known, found, held = _read(lb)
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
                held.get(entity_id) if kind == entities.ORG else None,
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
        if r.portfolio is not None:
            parts.append(f"portfolio {r.portfolio}")
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
    elif w.status["payload"].get("reason") is not None:
        yield f"  the reason on the line, tier {w.status['tier']}, no note: {w.status['payload']['reason']}"
    if w.portfolio is not None:
        said = f"portfolio {w.portfolio}" if w.portfolio else "no portfolio from now on"
        yield f"  {said}, on the line, tier {w.status['tier']}"
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
