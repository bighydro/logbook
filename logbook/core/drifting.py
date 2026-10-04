"""`logbook rollup people --drifting [--until DAY] [--window N] [--min-contacts N]`: the people whose
contact frequency fell most between the recent window — `N` days ending on `--until`, the record's
last day by default — and the same number of days before it. A reader (ADR 0013): two readings of
the people reader (`people.read`), one per window, compared and never written; every number
carries the ids of its lines under `--json`; the same record gives the same table. It says what
the record holds and suggests nothing.

A **contact** is a `message/v1` either way in a direct chat (`messages`), a `call/v1` whose
counterparty they are, answered or not (`calls`), an `event/v1` they attend and did not decline
(`calendar`), or a stay of the owner's the with module confirms them at (`together`, one per day
and stay) — the people reader's own channels, mail and a tagged face left out: a newsletter is a
mail too, and a face is a proposal. A person is listed when their earlier window has at least
`--min-contacts` contacts and their recent window fewer than the earlier one; the fall is read as
the share of the earlier count lost, the larger share first, then the larger count, then the name.
Per person: the two counts by channel, the channels that went **quiet** (heard in the earlier
window, silent in the recent), the **last real contact** (a message, an answered call or a day
together, the people reader's rule) with the days from it to the window's last day, and the
**last shared place**, the latest day the record confirms them at one of the owner's stays.

What it cannot see: a person you now meet in person every day looks drifting when nothing is logged
about it — no calendar entry, no transcript, no note that says `with`, no message — and a record
that began inside the earlier window undercounts it, which the rollup says. See docs/rollups.md."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import date, timedelta
from typing import Any

from . import people
from .export import day_range
from .flights import Airports
from .store import Logbook

KIND = "drifting"
CHANNELS = ("messages", "calls", "calendar")  # the people reader's channels that are a contact
TOGETHER = "together"  # the confirmed stays together, one per day and stay
COUNTED = (*CHANNELS, TOGETHER)
DEFAULT_WINDOW = 365
DEFAULT_MIN_CONTACTS = 3
EN_DASH = "\u2013"
EM_DASH = "\u2014"


def empty() -> dict[str, Any]:
    """The rollup of a record with no lines."""
    return {"kind": KIND, "window": {"recent": None, "earlier": None}, "min_contacts": None, "people": []}


def windows(until: str, window: int) -> tuple[tuple[str, str], tuple[str, str]]:
    """The earlier and the recent window, each `window` local days, the recent ending on `until`
    and the earlier ending the day before the recent begins."""
    if window < 1:
        raise ValueError("--window is a number of days, at least 1")
    end = date.fromisoformat(until)
    recent_first = end - timedelta(days=window - 1)
    earlier_last = recent_first - timedelta(days=1)
    earlier_first = earlier_last - timedelta(days=window - 1)
    return (earlier_first.isoformat(), earlier_last.isoformat()), (recent_first.isoformat(), until)


def read(
    lb: Logbook,
    until: str,
    window: int = DEFAULT_WINDOW,
    min_contacts: int = DEFAULT_MIN_CONTACTS,
    airports: Airports | None = None,
    record_first: str | None = None,
) -> dict[str, Any]:
    """The rollup: the two windows read through `people.read` and compared (`compare`). Raises
    `ValueError` for a window under a day or a negative floor, and what the people reader raises
    (`stays.SettingsError`, `policy.PolicyError`); writes nothing. `record_first`, the record's
    first day when known, adds a `warning` when the record began inside one of the windows."""
    if min_contacts < 0:
        raise ValueError("--min-contacts is a count, at least 0")
    earlier, recent = windows(until, window)
    airports = airports or Airports.load()
    before = people.read(lb, *earlier, airports)
    after = people.read(lb, *recent, airports)
    out: dict[str, Any] = {
        "kind": KIND,
        "window": {"recent": _window(*recent), "earlier": _window(*earlier)},
        "min_contacts": min_contacts,
    }
    if record_first is not None and record_first > earlier[0]:
        which = "earlier" if record_first <= earlier[1] else "recent" if record_first <= recent[1] else None
        if which is not None:
            out["warning"] = f"the record begins {record_first}, inside the {which} window"
        else:
            out["warning"] = f"the record begins {record_first}, after the window"
    out["people"] = compare(before, after, min_contacts)
    return out


def _window(first: str, last: str) -> dict[str, Any]:
    return {"since": first, "until": last, "days": day_range(first, last)}


def compare(
    earlier: people.Report, recent: people.Report, min_contacts: int = DEFAULT_MIN_CONTACTS
) -> list[dict[str, Any]]:
    """The people of `earlier` with at least `min_contacts` contacts whose count in `recent` is
    lower, the larger share lost first. Days since the last real contact are counted to the recent
    window's last day. Pure: two reports in, rows out."""
    rows: list[dict[str, Any]] = []
    for entity, was in earlier.known.items():
        now = recent.known.get(entity)
        before, after = _side(was), _side(now)
        if before["contacts"] < min_contacts or after["contacts"] >= before["contacts"]:
            continue
        fall = before["contacts"] - after["contacts"]
        real = _latest_real(was, now)
        rows.append(
            {
                "id": entity,
                "name": was.name,
                "earlier": before,
                "recent": after,
                "fall": fall,
                "fell_by": round(fall / before["contacts"], 3),
                "quiet": [c for c in COUNTED if before[c]["count"] and not after[c]["count"]],
                "last_real_contact": real,
                "days_since_real_contact": None
                if real is None
                else (date.fromisoformat(recent.last) - date.fromisoformat(real["day"])).days,
                "last_place": _last_place(was, now),
            }
        )
    rows.sort(key=lambda r: (-r["fell_by"], -r["fall"], r["name"].casefold()))
    return rows


def _side(p: people.Person | None) -> dict[str, Any]:
    """One window's contacts of one person: per channel the count and its lines, the confirmed
    stays together with their evidence, the total and every line behind it."""
    out: dict[str, Any] = {"contacts": 0}
    for channel in CHANNELS:
        found = p.channels.get(channel) if p is not None else None
        ids = list(dict.fromkeys(found.ids)) if found is not None else []
        out[channel] = {"count": len(ids), "lines": ids}
    shared = list(p.shared.values()) if p is not None else []
    out[TOGETHER] = {
        "count": len(shared),
        "lines": list(dict.fromkeys(id_ for s in shared for id_ in s.lines)),
    }
    out["contacts"] = sum(out[c]["count"] for c in COUNTED)
    out["lines"] = list(dict.fromkeys(id_ for c in COUNTED for id_ in out[c]["lines"]))
    return out


def _latest_real(*found: people.Person | None) -> dict[str, Any] | None:
    """The latest real contact among the windows' readings of one person."""
    reals = [p.real for p in found if p is not None and p.real is not None]
    if not reals:
        return None
    day, via, line = max(reals, key=lambda r: (r[0], -people.REAL_ORDER[r[1]]))
    return {"day": day, "via": via, "line": line}


def _last_place(*found: people.Person | None) -> dict[str, Any] | None:
    """The latest day the record confirms the person at one of the owner's stays, and where."""
    shared = [s for p in found if p is not None for s in p.shared.values()]
    if not shared:
        return None
    last = max(shared, key=lambda s: (s.day, s.stay))
    return {"where": last.where, "day": last.day, "lines": list(last.lines)}


# -- text ----------------------------------------------------------------------------------------------------


def rows(data: dict[str, Any]) -> Iterator[str]:
    """The rollup as a plain table: one row per person, the larger share lost first."""
    window = data["window"]
    head = "people · drifting"
    if window["recent"] is None:
        yield head
        yield "  nothing in the window"
        return
    recent, earlier = window["recent"], window["earlier"]
    yield (
        f"{head} · recent {recent['since']} {EN_DASH} {recent['until']}"
        f" · earlier {earlier['since']} {EN_DASH} {earlier['until']}"
        f" · at least {data['min_contacts']} contacts earlier"
    )
    if data.get("warning"):
        yield f"  ({data['warning']})"
    if not data["people"]:
        yield "        nobody fell below their earlier frequency"
        return
    quiet_width = max(8, *(len(_quiet(p["quiet"])) for p in data["people"]))
    yield (
        f"        {'person':<24} {'earlier':>7} {'recent':>6} {'fall':>6}  {'last real contact':<18} "
        f"{'quiet':<{quiet_width}}  last shared place"
    )
    for p in data["people"]:
        yield (
            f"        {p['name']:<24} {p['earlier']['contacts']:>7} {p['recent']['contacts']:>6}"
            f" {_fall(p['fell_by']):>6}  {_ago(p['days_since_real_contact']):<18} "
            f"{_quiet(p['quiet']):<{quiet_width}}  {_place(p['last_place'])}"
        )


def _fall(fell_by: float) -> str:
    return f"-{round(fell_by * 100)}%"


def _ago(days: int | None) -> str:
    if days is None:
        return "never"
    if days == 0:
        return "today"
    return f"{days} day ago" if days == 1 else f"{days} days ago"


def _quiet(channels: Sequence[str]) -> str:
    return ", ".join(channels) if channels else EM_DASH


def _place(place: dict[str, Any] | None) -> str:
    return EM_DASH if place is None else str(place["where"])
