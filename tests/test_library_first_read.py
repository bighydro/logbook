"""What the Library and the readers say to someone who has never seen the record: the demo month
(the Oslo persona, June 2026) read in October, as the stranger of #334 read it. Each test is one
of #334's findings: the front page links every shelf the navigation does; an empty Day names the
record's first and last day; `/gaps` and `/assets` say when the record's last line was; the Day's
company row agrees with the proposals under it; a trip's route names its places; the shelves'
headers say what their tier means; the Manifest's counts agree with what it says under them.
Nobody here exists: the Oslo persona, addresses at example.org, numbers in 07700 900xxx."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

import page_text
import pytest

from logbook import cli
from logbook.contrib import demo, entities, entity_review, gaps, serve
from logbook.core import day as day_reader
from logbook.core.store import Logbook

OCTOBER = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)  # the stranger's reading, long after 30 June
JULY = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)  # the morning after the record's last day
FIRST, LAST = "2026-06-01", "2026-06-30"  # the demo month's days of track


@pytest.fixture(scope="module")
def record(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    return demo.generate(tmp_path_factory.mktemp("first-read") / "Demo", days=30, seed=1)


def _site(lb: Logbook, now: datetime = OCTOBER) -> serve.Site:
    return serve.Site(lb, now=lambda: now)


def _page(site: serve.Site, path: str, query: str = "") -> str:
    response = site.respond(path, query)
    assert response.status == 200, (path, response.status, response.body[:300])
    return response.body.decode("utf-8")


def _main(page: str) -> str:
    return page[page.index("<main>") : page.index("</main>")]


def _said(page: str) -> str:
    return " ".join(page_text.seen(_main(page)).split())


# -- 1. the front page links every shelf of the navigation ---------------------------------------------

# the navigation before the doors' header (RFC 0047 §6): every page it reached is one tap from the gear
NAV_BEFORE = (
    "/", "/today", "/days", "/search", "/timeline", "/journeys", "/people", "/manifest", "/ideas",
    "/promises", "/goals", "/agents", "/places", "/assets", "/gaps", "/world",
)  # fmt: skip


def test_the_front_page_links_every_page_the_navigation_does(record: Logbook) -> None:
    site = _site(record)
    assert '<a class="gear" href="/gear"' in _page(site, "/days"), "the gear, on every page"
    assert '<a href="/shelves">' in _page(site, "/gear"), "and the gear the shelves listed"
    page = _page(site, "/shelves")  # the shelves listed: the front page before Today
    main = _main(page)
    linked = {href.split("?")[0] for href in re.findall(r'href="([^"]+)"', main)}
    for href in NAV_BEFORE:
        if href in ("/", "/today"):  # the front page itself, and the Day it names as the last day
            continue
        assert href in linked, href
    for word in ("Promises", "Goals", "Agents", "The world"):
        assert word in _said(page), word


def test_an_exported_front_page_still_keeps_the_owner_shelves_home(record: Logbook) -> None:
    site = serve.Site(record, now=lambda: OCTOBER, href=lambda path: path)
    said = _said(site.page_index())
    for shelf in ("Promises", "Goals", "Agents", "The Manifest", "Ideas"):
        assert shelf not in said, shelf


# -- 2. a Day the record holds nothing for ---------------------------------------------------------------


def test_today_on_a_day_the_record_holds_nothing_for_names_its_first_and_last_day(record: Logbook) -> None:
    site = _site(record)
    moved = site.respond("/today")
    assert moved.status == 302 and moved.location == "/day/2026-10-19"
    page = _page(site, "/day/2026-10-19")
    said = _said(page)
    assert f"The record holds nothing for 2026-10-19: its days run from {FIRST} to {LAST}." in said
    assert f'href="/day/{FIRST}"' in _main(page) and f'href="/day/{LAST}"' in _main(page)


def test_a_day_with_lines_does_not_say_the_record_holds_nothing(record: Logbook) -> None:
    assert "holds nothing for" not in _said(_page(_site(record), "/day/2026-06-08"))


def test_a_day_a_tier_gate_empties_does_not_say_the_record_holds_nothing(record: Logbook) -> None:
    """Through a gate that reads no tier the Day lists nothing; the record still holds the day."""
    gated = serve.Site(record, now=lambda: OCTOBER, tiers=[])
    page = _page(gated, "/day/2026-06-03")
    assert "Sources none" in _said(page), "the gate leaves every line out"
    assert "holds nothing for" not in _said(page)
    assert "holds nothing for 2026-10-19" in _said(_page(gated, "/day/2026-10-19"))


# -- 3. /gaps and /assets on a record whose last line is long ago ---------------------------------------


def test_gaps_says_when_the_record_last_spoke_and_still_counts_silence_to_today(
    record: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gaps, "now", lambda: OCTOBER)
    report = gaps.report(record)
    said = _said(_page(_site(record), "/gaps"))
    assert f"The record's last line is from {LAST}" in said, said[:600]
    assert "every silence and every missing day here runs to today, 2026-10-19" in said
    for source in report["sources"]:  # the numbers are the report's, as they were
        assert f"{len(source['missing_days']):,}" in said, source["source"]
    assert all(s["silence"]["to"] is None for s in report["sources"] if s["lines"])  # counted to today


def test_gaps_on_the_morning_after_says_nothing_of_it(
    record: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gaps, "now", lambda: JULY)
    assert "The record's last line is from" not in _said(_page(_site(record, JULY), "/gaps"))


def test_assets_says_when_the_record_last_spoke(record: Logbook) -> None:
    said = _said(_page(_site(record), "/assets"))
    assert f"The record's last day is {LAST}" in said, said[:600]
    assert "each fix's age here runs to now" in said
    assert "110 days 15 h ago" in said  # the age itself, as it was: the last fix to 19 October noon
    assert "The record's last day is" not in _said(_page(_site(record, JULY), "/assets"))


# -- 4. the Day's company row ---------------------------------------------------------------------------


def _proposed_only_days(lb: Logbook) -> list[str]:
    """The days whose company nobody confirmed while a row under them proposes someone."""
    found = []
    for n in range(1, 31):
        day = f"2026-06-{n:02d}"
        data = day_reader.read(lb, day)
        proposed = any((e.get("with") or {}).get("proposed") for e in data["timeline"])
        if proposed and not day_reader.company_of_day(data):
            found.append(day)
    return found


def test_the_with_row_says_none_confirmed_when_a_row_proposes_someone(record: Logbook) -> None:
    days = _proposed_only_days(record)
    assert "2026-06-17" in days, days  # Anders Vik, proposed from a photo aboard Nordlys
    site = _site(record)
    for day in days:
        page = _page(site, f"/day/{day}")
        row = page[page.index('<dt id="with">') :]
        row = row[: row.index("</dd>")]
        said = _said(f"<main>{row}</main>")
        assert "nobody confirmed; proposed below" in said, (day, said)
        assert "nobody the record saw" not in said, day
        assert "with proposed" in _said(page), day  # the row it points to


def test_a_day_without_proposals_still_says_nobody_the_record_saw(record: Logbook) -> None:
    site = _site(record)
    for n in range(1, 31):
        day = f"2026-06-{n:02d}"
        data = day_reader.read(record, day)
        proposed = any((e.get("with") or {}).get("proposed") for e in data["timeline"])
        if data["sources"] and not day_reader.company_of_day(data) and not proposed:
            page = _page(site, f"/day/{day}")
            assert "nobody the record saw" in page and "nobody confirmed" not in page, day
            return
    pytest.fail("the demo month has no day with lines and nobody in it")


# -- 5. a trip's route, and `show year`'s asset -----------------------------------------------------------


@pytest.fixture
def home(record: Logbook, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    monkeypatch.setenv("LOGBOOK_HOME", str(record.root))
    return record


def test_a_trips_route_names_the_city_not_the_coordinates(
    home: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["show", "trips"])
    out = capsys.readouterr().out
    assert "route Zurich ·" in out and "route Copenhagen ·" in out, out
    assert not re.search(r"route [^·]*\d+\.\d{4},\d+\.\d{4}", out), out
    assert "route aboard Nordlys" in out and "route Cabin" in out


def test_show_year_names_the_asset_as_registered(home: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(["show", "year", "2026"])
    out = capsys.readouterr().out
    assert "aboard Nordlys" in out and "aboard nordlys" not in out, out
    assert "6 nights aboard Nordlys · route aboard Nordlys" in out
    assert "route Zurich ·" in out and not re.search(r"route [^·]*\d+\.\d{4},\d+\.\d{4}", out), out


def test_the_journeys_and_a_journey_name_the_city(record: Logbook) -> None:
    site = _site(record)
    said = _said(_page(site, "/journeys", "year=2026"))
    assert "home 2026-06-11 · Zurich ·" in said and "home 2026-06-27 · Copenhagen ·" in said, said[:800]
    assert "47.3769,8.5417" not in said and "55.6850,12.5500" not in said
    journey = _said(_page(site, "/journeys/2026-06-08/2026-06-10"))
    assert "Zurich" in journey


def test_the_json_keeps_the_label_the_spec_gives(home: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    """`trips --json` and the rollups are compared between implementations (SPEC §6.1): their labels
    stay §3.2.6's, coordinates and all; only the text a reader prints names the place."""
    cli.main(["show", "trips", "--json"])
    routes = [t["route"] for t in json.loads(capsys.readouterr().out)["trips"]]
    assert ["47.3769,8.5417 (Zurich)"] in routes and ["55.6850,12.5500 (Copenhagen)"] in routes, routes
    cli.main(["rollup", "places", "--json"])
    labels = [u["label"] for y in json.loads(capsys.readouterr().out)["years"] for u in y["unnamed"]]
    assert "59.0500,10.0300 aboard nordlys (Sandefjord)" in labels, labels


def test_a_route_element_is_named_by_what_names_it_and_neighbours_stay_apart() -> None:
    from logbook.core import trips

    assert trips.route_name("47.3769,8.5417 (Zurich)") == "Zurich"
    assert trips.route_name("53.5998,10.0130 near Cabin, 1.1 km") == "near Cabin, 1.1 km"
    assert trips.route_name("59.8500,10.6000") == "59.8500,10.6000", "nothing names it: the coordinates"
    for label in ("Cabin", "ZRH, Zurich", "aboard Nordlys", "Hotel (old town)"):
        assert trips.route_name(label) == label
    route = [
        "59.4300,10.4800 (Sandefjord)",
        "59.0500,10.0300 (Sandefjord)",
        "Marina",
        "47.3769,8.5417 (Zurich)",
    ]
    assert trips.route_names(route) == [*route[:3], "Zurich"], "two neighbours off one town keep their labels"
    apart = ["47.3769,8.5417 (Zurich)", "Marina", "47.3800,8.5400 (Zurich)"]
    assert trips.route_names(apart) == ["Zurich", "Marina", "Zurich"], "not neighbours: each by its city"


def test_a_journeys_stays_off_one_town_keep_their_coordinates(record: Logbook) -> None:
    said = _said(_page(_site(record), "/journeys/2026-06-15/2026-06-20"))
    assert "59.4300,10.4800 (Sandefjord)" in said and "59.0500,10.0300 (Sandefjord)" in said, said[:1500]


# -- 6. the shelves' tier ---------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/manifest", "/ideas", "/goals", "/agents", "/promises"])
def test_a_shelf_header_says_what_its_tier_means(record: Logbook, path: str) -> None:
    page = _page(_site(record), path)
    head = re.search(r"<h1>.*?</h1>", page, re.S)
    assert head is not None
    assert "tier -" not in head.group(0)
    said = _said(f"<main>{head.group(0)}</main>")
    assert said.endswith("no lines") or re.search(r"read at tier \d$", said), said
    assert re.search(r'<small title="[^"]*highest tier[^"]*">', head.group(0)), head.group(0)
    assert "tier 3" not in serve.TIER_TITLE  # a gated page never says the tier it does not read


# -- 7. the Manifest's counts and what it says under them ------------------------------------------------


def test_the_manifest_says_why_what_was_seen_is_not_to_review(record: Logbook) -> None:
    report = entity_review.read(record, entities.ORG)
    assert not report.proposals and report.unplaced  # the demo: seen, never proposed
    said = _said(_page(_site(record), "/manifest"))
    n = len(report.unplaced)
    assert f"0 proposals · {n} seen, not placed · 0 placed" in said
    assert "every org the sources saw is placed or answered" not in said
    assert f"the {n} seen, not placed, match no org you named" in said, said
