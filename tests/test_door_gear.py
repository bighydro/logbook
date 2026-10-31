"""The gear (RFC 0047 §4.6, §5): the machinery behind one icon, at `/gear`, in the machine's own words.

One page of cards, one per part, each with one line of state, and the parts' own pages: the sources
(what each sent and when it last spoke, a quiet one marked, the command that brings it back), the
crossings (what left, when, to where, under which policy entry), the agents, the Manifest and the
assets (the old pages' contents exactly, every old address kept), and the build (when each page was
last built, how long it took, the command that builds it again). On the Oslo persona's fortnight and
the demo record: Kari and Ola Nordmann, who do not exist; every address at example.org; no test opens a
connection."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import beside_a_name
import phone_width
import pytest
import test_no_count_beside_a_name as strong
from persona import note, persona_record, utc
from test_day_rhythm import _seen, beside

from logbook import cli
from logbook.contrib import demo, door_gear, doors, library_build, orgs, serve
from logbook.core import figures, people
from logbook.core.store import Logbook

NOW = datetime(2026, 6, 22, 8, 0, tzinfo=UTC)  # the Monday after the fortnight, 10:00 in Oslo
QUIET = "gtasks"  # a live source that last spoke on 9 June: quiet for a week and more
HIDDEN = "hemmelig"  # a source whose every line is tier 2: never on a page that reads tier 1
FRAMED = ("/gear", "/gear/sources", "/gear/crossings", "/gear/build")  # the gear's own pages
OLD = {  # the gear's page → the old page whose contents it is, exactly
    "/gear/agents": "/agents",
    "/gear/manifest": "/manifest",
    "/gear/manifest/people": "/manifest/people",
    "/gear/assets": "/assets",
}
CRUMB = re.compile(r'<p class="mute gear-crumb">.*?</p>\n')
MARKED = ' aria-current="page"><svg'  # the gear's icon, marked as the page it opens
MEMBER = "kari"  # a member of the owner's circle a day was shared with: a person, never named on the gear
STATES = (  # every page of the gear, and every state its address can ask for
    *FRAMED,
    *OLD,
    "/gear/sources?quiet=1",
    "/gear/crossings?to=site",
    "/gear/crossings?to=circle",
    "/gear/crossings?to=nowhere",
    "/gear/crossings?page=2",
)
REFERENCE = re.compile(r"""(?:href|src|action)\s*=\s*["']([^"']*)["']""", re.I)


def _crossing(at: str, destination: str, tiers: list[int], by_tier: dict[str, int], by_kind: dict[str, int]):
    return {
        "at": at,
        "source": "logbook",
        "kind": "crossing",
        "tier": 1,
        "payload": {
            "schema": "crossing/v1",
            "destination": destination,
            "bundle_id": f"b-{destination}-{at}",
            "window": {"from": "2026-06-08T00:00:00Z", "to": "2026-06-22T00:00:00Z"},
            "tiers": tiers,
            "counts": {
                "logged": sum(by_tier.values()),
                "crossed": sum(by_tier.values()),
                "held_back": 0,
                "by_tier": by_tier,
                "by_kind": by_kind,
            },
            "policy": {"file": "policy/crossing.json", "max_tier": max(tiers)},
            "logbook_head": "0" * 64,
            "package_sha256": "1" * 64,
        },
    }


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """The fortnight; a task tool's line on 9 June and nothing since; a tier-2 source of its own; a site
    crossing on Saturday morning and a vault crossing of tiers 1 and 2 on Sunday."""
    lb = persona_record(tmp_path, monkeypatch)
    quiet = note(utc("2026-06-09", "09:00"), "Varnish the tiller")
    quiet.update(source=QUIET, tier=1)
    hidden = note(utc("2026-06-20", "21:00"), "A word for nobody")
    hidden.update(source=HIDDEN)
    lb.append_many(
        [
            quiet,
            hidden,
            _crossing(utc("2026-06-20", "06:10"), "site", [1], {"1": 120}, {"location": 100, "event": 20}),
            _crossing(utc("2026-06-21", "06:10"), "vault", [1, 2], {"1": 50, "2": 7}, {"note": 57}),
        ]
    )
    return lb


def _site(lb: Logbook, **kw: Any) -> serve.Site:
    return serve.Site(lb, now=lambda: NOW, **kw)


def _get(site: serve.Site, target: str) -> str:
    path, _, query = target.partition("?")
    response = site.respond(path, query)
    assert response.status == 200, (target, response.body[:300])
    return response.body.decode("utf-8")


def _main(page: str) -> str:
    return page[page.index("<main") : page.index("</main>")]


def _text(fragment: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment)))


def _rows(page: str) -> list[str]:
    return re.findall(r'<li class="row[^"]*".*?</li>', page, flags=re.S)


# -- the gear: one icon, one page of cards -------------------------------------------------------------------


def test_the_header_s_gear_opens_the_gear(lb: Logbook) -> None:
    assert doors.GEAR == "/gear"
    today = _get(_site(lb), "/")
    assert re.search(r'<a class="gear" href="/gear"', today), "the icon at the end of the header"


def test_the_gear_is_one_card_per_part_each_with_one_line_of_state(lb: Logbook) -> None:
    page = _get(_site(lb), "/gear")
    main = _main(page)
    assert '<main class="door">' in page and 'class="door-gear"' in main, "in the doors' frame"
    cards = re.findall(r'<a class="card" href="([^"]+)">(.*?)</a>', main, flags=re.S)
    assert [href for href, _ in cards] == [
        "/gear/sources",
        "/gear/crossings",
        "/gear/agents",
        "/gear/manifest",
        "/gear/assets",
        "/gear/build",
    ]
    for _href, card in cards:
        assert len(re.findall(r'<span class="state[^"]*"', card)) == 1, card
    state = dict((href, _text(card)) for href, card in cards)
    assert "quiet for a week" in state["/gear/sources"]
    assert "last crossing: vault, yesterday 06:10" in state["/gear/crossings"]
    assert "1 asset" in state["/gear/assets"]
    assert "live" in state["/gear/build"]
    assert '<a href="/shelves">Every shelf, as before</a>' in main
    assert re.search(r"<h1[^>]*>The gear</h1>", main), "the title, before any number"


def test_every_address_of_the_gear_answers_and_every_old_one_is_as_it_was(lb: Logbook) -> None:
    site = _site(lb)
    for target in (*FRAMED, *OLD, "/gear/crossings?to=site", "/gear/sources?quiet=1"):
        _get(site, target)
    for gear, old in OLD.items():
        mine, theirs = _get(site, gear), _get(site, old)
        assert len(CRUMB.findall(mine)) == 1, gear  # one line back to the gear, at the top of the page
        assert _main(CRUMB.sub("", mine)) == _main(theirs), f"{gear}'s contents are {old}'s, exactly"
        assert MARKED in mine and MARKED not in theirs, "the header marks the gear on the gear's pages"
        assert CRUMB.sub("", mine).replace(MARKED, "><svg") == theirs, f"{gear} is {old}, and nothing else"
    for old in ("/gaps", "/agents", "/manifest", "/manifest/people", "/assets", "/shelves"):
        assert "gear-crumb" not in _get(site, old), old
    assert site.respond("/gear/nothing").status == 404


def test_an_org_s_page_is_the_old_one_in_the_gear(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import orgs_record

    lb = orgs_record.settled_record(tmp_path, monkeypatch)
    site = serve.Site(lb, now=lambda: datetime(2026, 10, 12, 20, 0, tzinfo=UTC))
    org = sorted(orgs.read(lb, orgs.gate(None, False)).orgs)[0]
    for query in ("", "money=1"):
        mine = _get(site, f"/gear/org/{org}?{query}")
        assert CRUMB.sub("", mine).replace(MARKED, "><svg") == _get(site, f"/org/{org}?{query}")
    assert site.respond("/gear/org/no-such-org").status == 404


# -- the sources --------------------------------------------------------------------------------------------


def test_one_row_per_source_its_last_day_a_quiet_one_marked_and_the_command_that_brings_it_back(
    lb: Logbook,
) -> None:
    page = _get(_site(lb), "/gear/sources")
    rows = {re.search(r'data-source="([^"]+)"', r).group(1): r for r in _rows(page)}  # type: ignore[union-attr]
    assert {"dawarich", "ios-calendar", "manual", QUIET, HIDDEN} <= set(rows)
    quiet = rows[QUIET]
    assert "quiet" in quiet.split('"')[1], "marked on the row itself"
    assert '<a href="/day/2026-06-09">' in quiet, "its last line's day, a link to that Day"
    assert "<code>logbook sync gtasks</code>" in quiet
    assert "quiet" not in rows["dawarich"].split('"')[1]
    assert "<code>logbook sync dawarich</code>" in rows["dawarich"]
    only = _get(_site(lb), "/gear/sources?quiet=1")
    shown = [re.search(r'data-source="([^"]+)"', r).group(1) for r in _rows(only)]  # type: ignore[union-attr]
    assert QUIET in shown and "dawarich" not in shown
    assert '<a href="/gaps">' in _main(page), "the old table, a link away"


def test_a_source_the_import_policy_turns_off_says_so(lb: Logbook) -> None:
    (lb.root / "policy" / "import.json").write_text(
        '{"disabled": [{"source": "gtasks", "reason": "not mine any more"}]}', encoding="utf-8"
    )
    page = _get(_site(lb), "/gear/sources")
    quiet = next(r for r in _rows(page) if f'data-source="{QUIET}"' in r)
    assert "turned off in policy/import.json" in _text(quiet) and "logbook sync" not in quiet


# -- the crossings ------------------------------------------------------------------------------------------


def test_the_crossings_newest_first_each_with_its_destination_tiers_kinds_and_lines(lb: Logbook) -> None:
    page = _get(_site(lb), "/gear/crossings")
    rows = _rows(page)
    assert len(rows) == 2
    vault, site_ = (_text(r) for r in rows)
    assert vault.index("vault") < vault.index("tiers 1, 2")
    assert "57 lines" in vault and "note" in vault
    assert "policy/crossing.json" in vault and "ceiling 2" in vault
    assert "120 lines" in site_ and "event, location" in site_
    with lb.index() as idx:
        ids = [str(line["id"]) for line in idx.by_kind("crossing")]
    assert f'href="/line/{ids[1]}"' in rows[0] and f'href="/line/{ids[0]}"' in rows[1], "the line itself"
    only = _rows(_get(_site(lb), "/gear/crossings?to=site"))
    assert len(only) == 1 and "120 lines" in _text(only[0])


# -- the build ----------------------------------------------------------------------------------------------


def test_a_record_never_built_says_the_library_renders_live_and_how_to_try_the_build(lb: Logbook) -> None:
    said = _text(_main(_get(_site(lb), "/gear/build")))
    assert "renders every page live" in said
    assert "logbook serve --built" in said


def test_a_built_record_says_when_how_long_and_the_command_that_builds_it_again(lb: Logbook) -> None:
    site = _site(lb)
    library_build.build(lb, _site(lb))
    page = _get(site, "/gear/build")
    said = _text(_main(page))
    assert "logbook serve --build" in said
    built = library_build.Library(lb).built()
    assert f"{built['pages']:,} pages" in said and " s" in said
    assert "/gear" in said, "the gear's own pages are built too"
    assert "/gear/build" not in library_build.Library(lb).pages(), "the build's own page is always live"
    assert "last built" in _text(_get(site, "/gear"))


def test_the_gear_s_pages_are_built_and_the_build_page_is_live() -> None:
    for target in ("/gear/sources", "/gear/crossings", *OLD):
        assert target in library_build.DOORS, target
    assert library_build.live("/gear/build", "2026-06-22") and library_build.live("/gear", "2026-06-22")


# -- the record's rules -----------------------------------------------------------------------------------


def test_a_page_that_reads_tier_1_shows_no_tier_2_line_name_or_count(lb: Logbook) -> None:
    site = _site(lb, tiers=(1,))
    for target in FRAMED:
        page = _get(site, target)
        assert HIDDEN not in page, target
    crossings = _rows(_get(site, "/gear/crossings"))
    vault = _text(crossings[0])
    assert "50 lines" in vault and "57" not in vault and " 7 " not in vault, vault
    assert "note" not in vault, "a kind is said only when the page reads every tier that crossed"
    every = _text(_get(_site(lb), "/gear/sources"))
    assert HIDDEN in every, "the owner's page reads every tier"


@pytest.fixture(scope="module")
def demo_record(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    with pytest.MonkeyPatch.context() as mp:
        root = tmp_path_factory.mktemp("door-gear-demo") / "demo"
        mp.setenv("LOGBOOK_HOME", str(root))
        lb = demo.generate(root)
        cli.main(["export", "site", str(root.parent / "site")])
        return lb


def test_no_number_beside_a_name_and_no_script_and_nothing_fetched_on_the_demo_record(
    demo_record: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOGBOOK_HOME", str(demo_record.root))
    names = sorted({p.name for p in people.directory(demo_record).known.values()})
    site = serve.Site(demo_record, now=lambda: datetime(2026, 7, 1, 8, 0, tzinfo=UTC))
    for target in (*FRAMED, *OLD):
        path, _, query = target.partition("?")
        response = site.respond(path, query)
        assert response.status == 200, target
        page = response.body.decode("utf-8")
        assert beside(_seen(page), names) == [], target
        assert "<script" not in page.lower(), target
        csp = response.headers["Content-Security-Policy"]
        assert csp.startswith("default-src 'none'") and "script-src" not in csp, target
        for found in REFERENCE.findall(page):
            assert found.startswith("/") and not found.startswith("//"), (target, found)
    crossings = _get(site, "/gear/crossings")
    assert len(_rows(crossings)) == 1 and "site" in _text(_rows(crossings)[0]), "the export's own line"


def test_the_gear_fits_a_phone(lb: Logbook) -> None:
    site = _site(lb)
    for target in FRAMED:
        page = _get(site, target)
        assert phone_width.problems(page) == [], target
        assert phone_width.phone_breakpoints(phone_width.parse(page)[1]), target


def test_an_empty_record_is_kind_sentences_and_no_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "empty"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    lb = Logbook.init(root, "Europe/Oslo")
    site = serve.Site(lb, now=lambda: NOW)
    for target in (*FRAMED, *OLD):
        page = _get(site, target)
        assert "no rows" not in page.lower(), target
    for target in ("/gear/sources", "/gear/crossings"):
        empty = re.search(r'<p class="empty">(.*?)</p>', _get(site, target), flags=re.S)
        assert empty is not None, target
        said = _text(empty.group(1)).strip()
        assert said.endswith(".") and said.count(". ") == 0, (target, said)  # one sentence
    for _href, card in re.findall(r'<a class="card" href="([^"]+)">(.*?)</a>', _get(site, "/gear"), re.S):
        assert _text(card).strip().endswith("."), card


def test_the_gear_is_not_in_an_exported_site(demo_record: Logbook) -> None:
    site = demo_record.root.parent / "site"
    for page in site.rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        assert "gear" not in Path(page.name).stem, page
        assert "/gear" not in text and 'class="gear"' not in text, page


def test_the_gear_writes_nothing(lb: Logbook) -> None:
    head = lb.meta["head"]
    site = _site(lb)
    for target in (*FRAMED, *OLD):
        _get(site, target)
    assert Logbook(lb.root).meta["head"] == head
    assert door_gear.GEAR == doors.GEAR


def test_a_day_in_words_and_a_day_after_today_is_its_date() -> None:
    assert door_gear._day("2026-06-21", "2026-06-22") == "yesterday"
    assert door_gear._day("2026-06-09", "2026-06-22") == "Tue 9 June"
    assert door_gear._day("2026-10-26", "2026-06-22") == "26 October 2026"


# -- the rules v1.0 holds every page to ------------------------------------------------------------------


def _member_crossing(lb: Logbook) -> None:
    """A day shared with a member of the circle on Sunday evening, tiers 1 and 2: `share day`'s line."""
    lb.append_many([_crossing(utc("2026-06-21", "20:00"), MEMBER, [1, 2], {"1": 3, "2": 4}, {"message": 7})])


def test_a_crossing_to_a_member_of_the_circle_never_names_them(lb: Logbook) -> None:
    _member_crossing(lb)
    site = _site(lb)
    for target in ("/gear", "/gear/crossings", "/gear/crossings?to=circle"):
        said = _text(_main(_get(site, target)))
        assert not re.search(rf"\b{MEMBER}\b", said, re.I), (target, said)
    rows = _rows(_get(site, "/gear/crossings?to=circle"))
    assert len(rows) == 1, rows
    row = _text(rows[0])
    assert "a member of your circle" in row and "the entry for that member" in row, row
    assert "7 lines" in row and "message" in row, "the owner's page counts what crossed"
    assert ">Your circle</a>" in _get(site, "/gear/crossings"), "one pill for the circle, no name on it"
    assert "last crossing: a member of your circle, yesterday 20:00." in _text(_get(site, "/gear"))
    assert "Nothing has crossed there" in _get(site, "/gear/crossings?to=kari"), (
        "a name asked is not a filter"
    )


def test_the_destinations_named_are_the_names_the_policy_reserves() -> None:
    """The gear names a destination only when the policy keeps it for its own reader (#438), the one
    list `export crossing` and `share day` refuse a person's name against."""
    from logbook.core import policy

    assert frozenset(policy.RESERVED) == door_gear.OWN
    for name in policy.RESERVED:
        with pytest.raises(policy.PolicyError):
            policy.check_destination(name)


def test_a_tier_1_page_says_no_tier_a_crossing_carried_above_it(lb: Logbook) -> None:
    _member_crossing(lb)
    rows = [_text(r) for r in _rows(_get(_site(lb, tiers=(1,)), "/gear/crossings"))]
    member, vault, site_ = rows
    for row in (member, vault):
        assert "tier 1" in row and "tiers 1, 2" not in row and "ceiling 2" not in row, row
    assert "3 lines" in member and "7" not in member and "message" not in member, member
    assert "ceiling 1" in site_, "a ceiling within the page's tiers is said"


def test_a_built_record_s_slowest_pages_are_named_by_section_and_a_gated_page_says_the_doors_alone(
    lb: Logbook,
) -> None:
    library_build.build(lb, _site(lb))
    full = _main(_get(_site(lb), "/gear/build"))
    assert "slowest of the rest" in full, "the persona's build has pages beyond the doors"
    for detail in (r"/people/[0-9a-f]", r"/journeys/\d", r"/day/\d", r"\?from=\d"):
        assert not re.search(detail, full), (detail, "no person's id, no day, beside the seconds")
    gated = _main(_get(_site(lb, tiers=(1,)), "/gear/build"))
    assert "slowest of the rest" not in gated and "pages they lead to" not in gated
    assert "/gear/sources" in gated, "the doors and shelves, each with when it was built"


def _strong(page: str, names: list[str]) -> list[tuple[str, str]]:
    """main's strong guard over a page as a reader sees it, a row at a time (`beside_a_name.page_rows`), and
    over its words of every attribute, titles and aria-labels among them (`_seen`): a digit, a date or a
    clock with nothing but separators between it and a name, full or first (`figures.adjacent`); then
    `test_no_count_beside_a_name`'s own guard over the persona's names."""
    every = {n for n in names} | {n.split()[0] for n in names if len(n.split()[0]) >= 3}
    found = [
        (name, text)
        for text in [*beside_a_name.page_rows(page), *_seen(page).splitlines()]
        for name in sorted(every)
        if figures.adjacent(text, name)
    ]
    return found + [("persona", row) for row in strong.beside(page)]


def _every_state(site: serve.Site) -> list[tuple[str, serve.Response]]:
    out = []
    for target in STATES:
        path, _, query = target.partition("?")
        out.append((target, site.respond(path, query)))
    return out


def test_no_number_date_or_clock_touches_a_name_on_any_page_or_state_of_the_gear(
    lb: Logbook, demo_record: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The strong guard (main's, widened by #423 and #430) over every page and every state of the gear:
    on the persona's fortnight with every kind of crossing, built and not, at every tier and at tier 1; on
    the demo record; and on an empty record. Order is the only signal of closeness."""
    _member_crossing(lb)
    names = sorted({*strong.NAMES, *(p.name for p in (demo.OWNER, *demo.PEOPLE))})
    sites = [_site(lb), _site(lb, tiers=(1,))]
    seen = 0
    for built in (False, True):
        if built:
            library_build.build(lb, _site(lb))
        for site in sites:
            for target, response in _every_state(site):
                assert response.status == 200, target
                assert _strong(response.body.decode("utf-8"), names) == [], (target, built)
                seen += 1
    monkeypatch.setenv("LOGBOOK_HOME", str(demo_record.root))
    demo_site = serve.Site(demo_record, now=lambda: datetime(2026, 7, 1, 8, 0, tzinfo=UTC))
    empty = Logbook.init(tmp_path / "empty", "Europe/Oslo")
    for site in (demo_site, serve.Site(empty, now=lambda: NOW)):
        for target, response in _every_state(site):
            assert response.status == 200, target
            assert _strong(response.body.decode("utf-8"), names) == [], target
            seen += 1
    assert seen == len(STATES) * 6


def test_every_response_of_the_gear_carries_the_doors_policy_and_no_frame(lb: Logbook) -> None:
    """Every answer under `/gear`, a page, a state, a page that is not there and a page number that is not
    one: `default-src 'none'`, no script, `frame-ancestors 'none'` (#421)."""
    site = _site(lb)
    answers = [*_every_state(site), ("/gear/nothing", site.respond("/gear/nothing"))]
    answers.append(("/gear/crossings?page=0", site.respond("/gear/crossings", "page=0")))
    assert {r.status for _t, r in answers} >= {200, 400, 404}
    for target, response in answers:
        csp = response.headers["Content-Security-Policy"]
        assert csp.startswith("default-src 'none'") and "script-src" not in csp, target
        assert "frame-ancestors 'none'" in csp, target
        assert "<script" not in response.body.decode("utf-8").lower(), target


def test_a_source_no_command_brings_back_says_why(lb: Logbook) -> None:
    page = _get(_site(lb), "/gear/sources")
    rows = {re.search(r'data-source="([^"]+)"', r).group(1): _text(r) for r in _rows(page)}  # type: ignore[union-attr]
    assert "written on this machine" in rows["manual"] and "logbook sync" not in rows["manual"]
    assert "no adapter here reads it" in rows[HIDDEN]
    assert "since Mon\xa08\xa0June" in rows["dawarich"], "a date never breaks across a line"
