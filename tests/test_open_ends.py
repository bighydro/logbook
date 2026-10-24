"""A span with one end unknown never breaks a page or a reader (#344: `/today` and a Day crashed on a
flight with no end, `_instant(None)`). The demo month (the Oslo persona, who does not exist) reshaped
by the fuzz suite's `open-ends` (`tests/test_fuzz_readers.py`): every line with an `end` written
without it, every flight without its arrival and every other one without its departure, a passage
left open, and the owner's track silent from the first flight's departure to the end of that day.
Every page the Library serves is walked from `/` and `/today`, at every tier and through a gate of
tier 1; every reader that reads a day, a window or the whole record reads it. The slow tier puts the
same reshaping into its random mixes."""

from __future__ import annotations

import html
import re
from collections import deque
from datetime import UTC, datetime

import pytest
from test_fuzz_readers import (
    WHOLE_RECORD_READERS,
    assert_reads_cleanly,
    at_home,
    local_date,
    make_record,
    windowed_readers,
)

from logbook.contrib import demo, serve
from logbook.core.store import Logbook

LABEL = "demo --days 30 --seed 1, open ends"
HREF = re.compile(r"""href\s*=\s*["']([^"']*)["']""", re.I)
ANSWERS = {
    200,
    302,
    400,
    404,
}  # a page, a redirect, a request refused, a detail the record lacks: never a 500
ROUTE = re.compile(r"/(?:day|journeys|people|org|idea|promises|goals|line|photo)/")


@pytest.fixture(scope="module")
def lb(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    return make_record(tmp_path_factory.mktemp("open-ends") / "Demo", 30, 1, frozenset({"open-ends"}))


def _flight_days(lb: Logbook) -> list[str]:
    return sorted({local_date(str(line["at"]), demo.TZ) for line in lb.lines() if line["kind"] == "flight"})


def _kind(target: str) -> str:
    """A page's kind, for the walk to read one of each: its route (one detail page of a sort), and the
    names in its query."""
    path, _, query = target.partition("?")
    found = ROUTE.match(path)
    route = found.group(0) if found else path
    return route + "?" + "&".join(sorted({p.partition("=")[0] for p in query.split("&") if p}))


def _walk(site: serve.Site, seeds: list[str]) -> dict[str, int]:
    """Every page reachable from `seeds`, one of each kind, by its status; a page that raises fails
    the test with the page named."""
    queue, seen = deque(seeds), set(seeds)
    kinds = {_kind(seed) for seed in seeds}
    found: dict[str, int] = {}
    while queue:
        target = queue.popleft()
        path, _, query = target.partition("?")
        try:
            response = site.respond(path, query)
        except Exception as e:  # the test's own message: which page, which exception
            raise AssertionError(f"{LABEL}: {target} raised {type(e).__name__}: {e}") from e
        found[target] = response.status
        text = response.body.decode("utf-8", "replace")
        links = [response.location] if response.location else [html.unescape(h) for h in HREF.findall(text)]
        for link in links:
            link = link.partition("#")[0]
            if not link.startswith("/") or link.startswith("//") or link in seen:
                continue
            if _kind(link) in kinds:
                continue
            kinds.add(_kind(link))
            seen.add(link)
            queue.append(link)
    return found


def test_the_record_holds_the_open_ends(lb: Logbook) -> None:
    flights = [line for line in lb.lines() if line["kind"] == "flight"]
    assert len(flights) >= 2
    assert all(f["end"] is None and "actual_arrival" not in f["payload"] for f in flights)
    assert any("actual_departure" not in f["payload"] for f in flights)
    assert all(line["end"] is None for line in lb.lines())


@pytest.mark.parametrize("tiers", [None, (1,)], ids=["every tier", "tier 1"])
def test_every_page_serves_a_record_of_open_ends(lb: Logbook, tiers: tuple[int, ...] | None) -> None:
    flown = _flight_days(lb)
    now = datetime.fromisoformat(f"{flown[0]}T10:00:00+00:00").astimezone(UTC)
    site = serve.Site(lb, tiers=tiers, now=lambda: now)
    today = site.respond("/today")
    assert today.status == 302 and today.location == f"/day/{flown[0]}"
    seeds = ["/", *(f"/day/{day}" for day in flown), *(f"/day/{day}?open=1" for day in flown)]
    found = _walk(site, seeds)
    bad = {target: status for target, status in found.items() if status not in ANSWERS}
    assert not bad, f"{LABEL}: {bad}"
    assert all(found[f"/day/{day}"] == 200 for day in flown)
    served = {_kind(t).partition("?")[0] for t, status in found.items() if status == 200}
    for route in ("/days", "/trips", "/journeys", "/places", "/people", "/world", "/gaps"):
        assert route in served, route


def test_every_reader_reads_a_record_of_open_ends(lb: Logbook) -> None:
    flown = _flight_days(lb)
    with at_home(lb):
        for args in WHOLE_RECORD_READERS:
            assert_reads_cleanly(LABEL, args)
        for day in flown:
            for args in windowed_readers(
                day, day, day, "Ola Nordmann", "places", "week", "memory", "owner", 3
            ):
                assert_reads_cleanly(LABEL, args)
        assert_reads_cleanly(LABEL, ["export", "vault", str(lb.root.parent / "vault")])
