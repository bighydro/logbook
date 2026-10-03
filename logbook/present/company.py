"""`present` and `company`: everyone the sources put at a stay, and the same merged per person."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..chain import Line
from ..places import Place
from ..resolve import Identity, Ref
from ..stays import Segment
from .calendar import from_calendar
from .circle import from_circle
from .model import CONFIRMED, PROPOSED, Companion, Presence
from .notes import from_notes
from .owner import Owner
from .photos import from_photos
from .transcript import from_transcript

FROM = (from_circle, from_calendar, from_transcript, from_notes, from_photos)


def present(
    stay: Segment,
    lines: Sequence[Line],
    identities: Mapping[Ref, Identity],
    places: Sequence[Place] = (),
    owner: Owner | None = None,
) -> list[Presence]:
    """Everyone the evidence puts at the stay, one entry per piece of evidence, sources in the
    order of `SOURCES`, lines in the order given. `places` (places.json) geocodes a calendar
    entry's location; `owner` is left out, never their own company."""
    found: list[Presence] = []
    for source in FROM:
        found.extend(
            p for p in source(stay, lines, identities, places) if owner is None or not owner.holds(p)
        )
    return found


def company(
    stay: Segment,
    lines: Sequence[Line],
    identities: Mapping[Ref, Identity],
    places: Sequence[Place] = (),
    owner: Owner | None = None,
) -> list[Companion]:
    """`present` merged per person (by entity id, else by name): confirmed before proposed, then
    by confidence, then by first evidence."""
    merged: dict[tuple[str | None, str], list[Presence]] = {}
    for p in present(stay, lines, identities, places, owner):
        merged.setdefault((p.person, "" if p.person else p.name.casefold()), []).append(p)
    companions = []
    for group in merged.values():
        best = min(group, key=lambda p: (p.status != CONFIRMED, -p.confidence))
        companions.append(
            Companion(
                best.person,
                best.name,
                best.status,
                best.confidence,
                tuple(dict.fromkeys(p.source for p in group)),
                tuple(p.reason for p in group),
                tuple(dict.fromkeys(p.line for p in group)),
            )
        )
    order = {CONFIRMED: 0, PROPOSED: 1}
    companions.sort(key=lambda c: (order[c.status], -c.confidence))
    return companions
