"""Readiness (RFC 0034): is the day all in? For each class of source — mail, message, meeting,
location, photo, calendar — whether the day has lines of it, from which sources, and which usual
sources have not delivered.

A source is usual for a class when, over the `WINDOW_DAYS` local days ending on the day, it has a
line of the class's kinds on at least `USUAL_SHARE` of the window's days that have any line (the
rule `days` applies per source, applied per class) and `policy/import.json` has not disabled it. The
block is computed from the record and the policy alone: one aggregate on the index, the day's lines
and the policy file read, nothing written (not even the default policy) and no connection opened.
It is advice before signing, never a gate."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import timedelta
from typing import Any

from . import policy
from .chain import Line
from .export import parse_day
from .store import Logbook

#: the classes in the order they are shown, each the kinds it covers
CLASSES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("mail", ("mail",)),
    ("message", ("message",)),
    ("meeting", ("transcript",)),
    ("location", ("location",)),
    ("photo", ("photo",)),
    ("calendar", ("event",)),
)
KINDS: tuple[str, ...] = tuple(kind for _name, kinds in CLASSES for kind in kinds)
WINDOW_DAYS = 28  # the window a source's habit is read over, the day included
USUAL_SHARE = 0.8  # a source with the class on this share of the window's logged days is usual
DOT = " · "


def read(
    lb: Logbook, day: str, lines: Iterable[Line] | None = None, tiers: Sequence[int] | None = None
) -> dict[str, Any]:
    """The readiness block of `day`. `lines` are the day's lines when the caller has read them
    already, else they are read through the index; with `tiers`, only those tiers count (a gated
    reader's days). `ValueError` for a day that is not one; `policy.PolicyError` when the import
    policy is not what it should be."""
    d = parse_day(day)
    since = (d - timedelta(days=WINDOW_DAYS - 1)).isoformat()
    disabled = policy.read_disabled(lb.root)
    with lb.index() as idx:
        found = idx.day(day) if lines is None else list(lines)
        if tiers is not None:
            found = [line for line in found if line.get("tier") in tiers]
        logged, per_class_source = idx.kind_source_days(since, day, KINDS, tiers)
    return of_lines(day, since, found, logged, per_class_source, disabled)


def of_lines(
    day: str,
    since: str,
    lines: Iterable[Line],
    logged: int,
    days_of: dict[tuple[str, str], int],
    disabled: dict[str, str],
) -> dict[str, Any]:
    """The block from what `read` gathered: the day's lines, how many days of the window have any
    line, per (kind, source) on how many of them it has one, and the disabled sources."""
    on_day: dict[str, dict[str, int]] = {}  # kind -> source -> lines on the day
    for line in lines:
        kind, source = str(line.get("kind")), str(line.get("source"))
        if kind in KINDS:
            by_source = on_day.setdefault(kind, {})
            by_source[source] = by_source.get(source, 0) + 1
    classes = []
    for name, kinds in CLASSES:
        sources: dict[str, int] = {}
        for kind in kinds:
            for source, n in on_day.get(kind, {}).items():
                sources[source] = sources.get(source, 0) + n
        usual = sorted(
            {
                source
                for (kind, source), n in days_of.items()
                if kind in kinds and source not in disabled and logged and n >= logged * USUAL_SHARE
            }
        )
        classes.append(
            {
                "name": name,
                "kinds": list(kinds),
                "present": bool(sources),
                "lines": sum(sources.values()),
                "sources": sorted(sources),
                "usual": usual,
                "missing": [source for source in usual if source not in sources],
            }
        )
    missing = [c["name"] for c in classes if c["missing"]]
    return {
        "window": {"since": since, "until": day, "logged_days": logged},
        "classes": classes,
        "missing": missing,
        "ready": not missing,
    }


def text(block: dict[str, Any]) -> str:
    """One row: `mail none · message present · location present, missing dawarich · …`."""
    parts = []
    for c in block["classes"]:
        state = "present" if c["present"] else "none"
        if c["missing"]:
            missing = f"missing {', '.join(c['missing'])}"
            state = f"{state}, {missing}" if c["present"] else missing
        parts.append(f"{c['name']} {state}")
    return DOT.join(parts)
