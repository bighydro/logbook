"""Calendar entries several sources carry: `fold`.

Two calendars that hold the same entry — a flight in the phone's calendar and in a subscribed
.ics, in two languages — are N `event/v1` lines for one event. `fold` keeps the first line of
each such set and names the sources it stands for, so `logbook show` and `logbook day` print one
row, `×N sources`, instead of N. Two lines are one event when they come from different sources,
start and end at the same instants, and either name the same flight (`flights.designator` on the
title: `Flight to Zürich (XY 561)`, `Flug XY561 nach Zürich`) or carry the same title, case,
accents and whitespace aside (`Standup` and `standup`, `Zürich` and `Zurich`). The fold happens
only across sources: one calendar holding an entry twice is two entries, though a repeat from one
calendar folds into a set another calendar already makes. Nothing here reads a file."""

from __future__ import annotations

import unicodedata
from collections.abc import Container, Sequence
from datetime import datetime
from typing import NamedTuple

from .chain import Line
from .flights import Airlines, designator
from .stays import instant


class Folded(NamedTuple):
    """What one kept event line stands for: the sources, the ids of every line, its own first."""

    sources: list[str]
    lines: list[str]


def fold(
    lines: Sequence[Line], airlines: Airlines, retracted: Container[str] = ()
) -> tuple[list[Line], dict[str, Folded]]:
    """The lines in their order with every event line that repeats an earlier one from another
    source dropped (every other kind kept in place), and, for each event kept in the place of
    two or more sources' lines, keyed by its id, the sources it stands for in evidence order and
    the ids of every line it stands for, its own first. A retracted line (`retracted`, ids) is
    never folded and folds nothing."""
    clusters: dict[tuple[datetime | None, datetime | None], list[list[Line]]] = {}
    for line in lines:
        if line.get("kind") != "event" or str(line["id"]) in retracted:
            continue
        key = (instant(line.get("at")), instant(line.get("end")))
        for cluster in clusters.setdefault(key, []):
            if _same_event(cluster[0], line, airlines):
                cluster.append(line)
                break
        else:
            clusters[key].append([line])
    dropped: set[str] = set()
    folded: dict[str, Folded] = {}
    for cluster in (c for group in clusters.values() for c in group):
        seen = list(dict.fromkeys(str(line["source"]) for line in cluster))
        if len(seen) < 2:
            continue
        folded[str(cluster[0]["id"])] = Folded(seen, [str(line["id"]) for line in cluster])
        dropped.update(str(line["id"]) for line in cluster[1:])
    return [line for line in lines if str(line["id"]) not in dropped], folded


def _same_event(a: Line, b: Line, airlines: Airlines) -> bool:
    title_a, title_b = (str((line.get("payload") or {}).get("title") or "") for line in (a, b))
    if _normal(title_a) == _normal(title_b):
        return True
    flight = designator(title_a, airlines)
    return flight is not None and flight == designator(title_b, airlines)


def _normal(title: str) -> str:
    """The title with accents stripped (NFKD, the combining marks dropped), case folded and
    whitespace collapsed, so `Zürich` and `Zurich`, `Café  Olsen` and `cafe olsen` compare equal."""
    bare = "".join(c for c in unicodedata.normalize("NFKD", title) if not unicodedata.combining(c))
    return " ".join(bare.split()).casefold()
