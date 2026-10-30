"""The People door (RFC 0047 §4.3, `logbook/contrib/door_people.py`): everyone by closeness, each person
a thread. On the demo record (the Oslo persona, Ines Nordmann, and her circle: Ola, Kari and Eva
Nordmann, Per Hansen and the rest), on the four synthetic years of the Library's pages, on an empty
record and on a small record of two tiers; nobody here exists, addresses at example.org, numbers in
07700 900xxx. Every address the door answers, the empty states, the tier gate, no number beside a
person's name, no script and no reference away, the rings and the order, phone width first, an
exported page and a built one."""

from __future__ import annotations

import html
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

import page_text
import phone_width
import pytest
from library_record import library_record

from logbook.contrib import demo, door_people, doors, library_build, serve
from logbook.core import drafts, figures, people
from logbook.core.store import Logbook

JULY = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)  # the day after the demo's month
OCTOBER = datetime(2025, 10, 1, 12, 0, tzinfo=UTC)  # in the four years' last
TZ = "Europe/Oslo"
REFERENCE = re.compile(
    r"""(?:href|src|action|formaction|poster|data|srcset|cite)\s*=\s*["']([^"']*)["']""", re.I
)
TITLES = re.compile(r"""(?:title|aria-label|alt)\s*=\s*"([^"]*)\"""")


@pytest.fixture(scope="module")
def demo_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("door-people") / "Demo"
    demo.generate(root, days=30, seed=1)
    return root


@pytest.fixture
def lb(demo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "Demo"
    shutil.copytree(demo_root, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook(root)


@pytest.fixture(scope="module")
def years_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("door-people-years") / "lb"
    library_record(root)
    return root


@pytest.fixture
def years(years_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    shutil.copytree(years_root, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook(root)


def _site(lb: Logbook, now: datetime = JULY, **kwargs: object) -> serve.Site:
    return serve.Site(lb, now=lambda: now, **kwargs)  # type: ignore[arg-type]


def _get(site: serve.Site, target: str) -> str:
    path, _, query = target.partition("?")
    response = site.respond(path, query)
    assert response.status == 200, (target, response.status, response.body[:400])
    return response.body.decode("utf-8")


def _ids(lb: Logbook) -> dict[str, str]:
    return {p.name: p.entity for p in people.directory(lb).known.values()}


def _door(text: str) -> str:
    """The door's own part of a page: from its block to the review queue (which is as it was)."""
    start = text.index('<div class="door-people')
    end = text.find('<section class="review">', start)
    return text[start : end if end >= 0 else None]


def _pages(lb: Logbook) -> list[str]:
    ids = _ids(lb)
    ola = ids["Ola Nordmann"]
    return [
        "/people",
        "/people?year=2026",
        f"/people?sel={ola}",
        f"/people?year=2026&sel={ola}",
        f"/people/{ola}",
        f"/people/{ola}?said=1",
        f"/people/{ola}?at=2026-06-13",
        *(f"/people/{entity}" for entity in ids.values()),
    ]


# -- the door renders, and every address works ---------------------------------------------------------------


def test_the_door_on_the_demo_record_the_head_the_orbit_the_thread_then_the_queue(lb: Logbook) -> None:
    text = _get(_site(lb), "/people")
    door = _door(text)
    assert "<h1>People</h1>" in door
    assert "12 people in your record. The closest sit nearest." in page_text.seen(door)
    legend = door[door.index('<ul class="legend"') :]
    legend = legend[: legend.index("</ul>")]
    assert [page_text.seen(li).strip() for li in legend.split("<li>")[1:]] == [
        "Home",
        "Family",
        "Friends",
        "Everyone else",
    ]
    orbit = door[door.index('<section class="orbit"') : door.index("</svg>")]
    assert '<circle class="you"' in orbit and ">You</text>" in orbit
    assert 'class="ring everyone"' in orbit and 'class="ring home"' in orbit
    ids = _ids(lb)
    assert orbit.count('href="/people?sel=') == len(ids), "every person of the circle is drawn: twelve"
    # the card: the closest when nobody is asked for, with the link to the whole thread
    card = door[door.index('<section class="card thread"') :]
    assert '<h2 class="name" id="thread-name">Per Hansen</h2>' in card, "the most days together this year"
    assert f'href="/people/{ids["Per Hansen"]}"' in card and "The whole thread" in card
    assert 'aria-current="true"' in orbit.split(f'sel={ids["Per Hansen"]}"')[1].split("</a>")[0]
    # then the review queue, at the foot, exactly as it was
    assert text.index('<h2 id="review">') > text.index('<section class="card thread"')
    assert text.index('<h2 id="review">') > text.index("</svg>")


def test_the_rings_are_a_rule_s_reading_in_pencil_and_the_order_is_closeness(lb: Logbook) -> None:
    site = _site(lb)
    found = door_people.circle(site, None)
    assert found is not None
    order = [n.person.name for n in found.near]
    rings = {n.person.name: n.ring for n in found.near}
    # days together this year first: Per's ten at the office, Liv's nine, then Ola's three
    assert order[:3] == ["Per Hansen", "Liv Berg", "Ola Nordmann"]
    assert order.index("Eva Nordmann") < order.index("Kari Nordmann"), "calls and messages next: Eva's calls"
    # Family: the owner's family name, read from the owner's address (ines.nordmann@example.org)
    assert {n for n, r in rings.items() if r == door_people.FAMILY} == {
        "Ola Nordmann",
        "Kari Nordmann",
        "Eva Nordmann",
    }
    # Friends: a call, a message or a night under one roof this year
    assert rings["Anders Vik"] == rings["Sigrid Moen"] == door_people.FRIENDS
    assert rings["Per Hansen"] == rings["Nils Haug"] == door_people.EVERYONE
    assert not any(r == door_people.HOME for r in rings.values()), "nobody spent a month of nights at home"
    assert door_people.EMPTY_RING["home"] in _door(_get(site, "/people")), "an empty ring says what fills it"
    card = _door(_get(site, f"/people?sel={_ids(lb)['Ola Nordmann']}"))
    kicker = (
        card[card.index('<section class="card thread"') :].split('<p class="kicker">')[1].split("</p>")[0]
    )
    assert kicker == f'<span class="pencil" title="{html.escape(door_people.RULE)}">Family</span>'


def test_the_people_you_live_with_come_first_on_the_innermost_ring(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The owner's answer of 25 October 2026 to RFC 0047 §14 Q1: the order is closeness, but the people
    the owner lives with always sit in the innermost ring and come first. Here the Marina is home and
    one night under one roof there is enough, so Ola and Anders live with the owner: they lead the
    order, Ola first (more days together), and Ola's is the thread the door opens."""
    found = json.loads((lb.root / "places.json").read_text(encoding="utf-8"))
    found["Marina"]["kind"] = "home"
    (lb.root / "places.json").write_text(json.dumps(found), encoding="utf-8")
    monkeypatch.setattr(door_people, "HOME_NIGHTS", 1)
    site = _site(lb)
    circle = door_people.circle(site, None)
    assert circle is not None
    order = [(n.person.name, n.ring) for n in circle.near]
    assert order[:2] == [("Ola Nordmann", "home"), ("Anders Vik", "home")], order[:3]
    assert order[2][0] == "Per Hansen", "then closeness: the most days together this year"
    door = _door(_get(site, "/people"))
    assert '<h2 class="name" id="thread-name">Ola Nordmann</h2>' in door
    assert door_people.EMPTY_RING["home"] not in door


def test_a_person_spending_the_nights_at_home_is_home_and_the_rule_reads_the_window() -> None:
    nights = {
        (f"2026-0{1 + n // 28}-{1 + n % 28:02d}", "s"): people.SharedDay(
            f"2026-0{1 + n // 28}-{1 + n % 28:02d}",
            "s",
            "Home",
            night=f"2026-0{1 + n // 28}-{1 + n % 28:02d}",
        )
        for n in range(door_people.HOME_NIGHTS)
    }
    p = people.Person("e1", "Kari Hansen", (), None, 1, {}, nights)
    assert door_people.ring_of(p, "2026-01-01", "2026-12-31", {"Home"}, {"nordmann"}, None)[0] == "home"
    assert door_people.ring_of(p, "2027-01-01", "2027-12-31", {"Home"}, {"nordmann"}, None)[0] == "everyone"
    assert door_people.ring_of(p, "2026-01-01", "2026-12-31", set(), {"hansen"}, None)[0] == "family"
    assert door_people.ring_of(p, "2026-01-01", "2026-12-31", set(), set(), None)[0] == "friends"


def test_the_card_and_the_whole_thread_of_one_person(lb: Logbook) -> None:
    site = _site(lb)
    ola = _ids(lb)["Ola Nordmann"]
    card = _door(_get(site, f"/people?sel={ola}"))
    card = card[card.index('<section class="card thread"') :]
    assert '<h2 class="name" id="thread-name">Ola Nordmann</h2>' in card
    assert card.count('<p class="moment">') == door_people.CARD + 1, "five moments and the beginning"
    assert "The beginning" in card and "The first day the record holds with you both." in card
    assert f'<a href="/people/{ola}">Earlier moments, on the whole thread</a>' in card
    assert 'href="/life?at=2026-06-01"' in card and "Your years together" in card, "Life at the first day"
    assert _site(lb).respond("/life", "at=2026-06-01").status == 200, "and Life answers it"
    assert f'href="/places?person={ola}"' in card and "Places you\u2019ve shared" in card
    whole = _door(_get(site, f"/people/{ola}"))
    assert '<h1 id="thread-name">Ola Nordmann</h1>' in whole
    strip = whole[whole.index('<ul class="strip">') : whole.index("</ul>", whole.index('<ul class="strip">'))]
    assert len(re.findall(r'class="mark"', strip)) == 3, "a mark for each day together, no count"
    assert 'href="/day/2026-06-13"' in strip
    assert "A night together at" in whole and "Messages back and forth." in whole
    assert "Cabin" in whole and "Marina" in whole, "the places shared"
    # what was said: only when asked, then the words of the last few, each with its day
    assert "Picking up bread" not in whole and f'href="/people/{ola}?said=1#said"' in whole
    said = _door(_get(site, f"/people/{ola}?said=1"))
    words = said[said.index('<ul class="said">') : said.index("</ul>", said.index('<ul class="said">'))]
    assert words.count("<li>") == door_people.SAID
    assert "Ola wrote" in words and "You wrote" in words, "both sides, not the owner's words alone"
    assert f'href="/people/{ola}#said"' in said, "and folded away again"
    # the promises are a rule's reading: pencil, the rule on hover, never the owner's ink
    chips = card[card.index('<ul class="chips"') : card.index("</ul>", card.index('<ul class="chips"'))]
    assert chips.count('<span class="pencil" title="rule: promises') == chips.count("<li")
    assert "You owe them" in chips and "Ola" not in page_text.seen(chips), "a chip names nobody"
    # how the record knows them: a word before each address; the strip says what a mark is
    assert "<dt>Email</dt><dd>ola.nordmann@example.org</dd>" in whole and "immich:" not in whole
    assert "One mark for each day you were together" in whole
    marked = _door(_get(site, f"/people/{ola}?at=2026-06-13"))
    assert 'id="at-2026-06-13"' in marked


def test_every_address_the_door_answers(lb: Logbook) -> None:
    site = _site(lb)
    for target in _pages(lb):
        _get(site, target)
    by_name = _get(site, "/people/Ola%20Nordmann")  # a name, as `/people/NAME` always took
    assert '<h1 id="thread-name">Ola Nordmann</h1>' in by_name
    assert "Kari Nordmann" in _site(lb).page_person("Kari Nordmann"), "the Site's own method, by name"
    assert site.respond("/people", "sel=nobody-at-all").status == 404
    assert site.respond("/people/nobody-at-all").status == 404
    assert site.respond("/people", "year=20x").status == 400
    assert site.respond("/people", "page=0").status == 400
    assert site.respond("/people/review").status == 405, "the queue's acts are a POST, as they were"


def test_an_empty_record_says_what_fills_the_door(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    site = _site(lb)
    door = _door(_get(site, "/people"))
    assert door_people.EMPTY in page_text.seen(door) and "<svg" not in door
    assert site.respond("/people/someone").status == 404


def test_a_thread_with_no_first_day_says_how_it_begins(lb: Logbook) -> None:
    nils = _ids(lb)["Nils Haug"]  # one mail, never a day together, a call or a message
    whole = _door(_get(_site(lb), f"/people/{nils}"))
    assert door_people.MET in whole and html.escape('logbook with YYYY-MM-DD "Nils Haug"') in whole
    assert 'title="rule: the beginning"' in whole, "in pencil, the rule named"


# -- the record's rules ------------------------------------------------------------------------------------


def _two_tiers(root: Path) -> Logbook:
    """Kari Nordmann, named at tier 1, in the calendar at tier 1 and in messages at tier 2 (one of them
    in 2025, a year only a tier-2 line gives); Per Hansen, named at tier 2 only."""
    lb = Logbook.init(root, TZ)
    kari, per = "a6f3c2d1-0000-4000-8000-0000000000a1", "a6f3c2d1-0000-4000-8000-0000000000a2"
    for ref, entity, label, tier in (
        (("email", "kari.nordmann@example.org"), kari, "Kari Nordmann", 1),
        (("phone", "+447700900002"), kari, "Kari Nordmann", 1),
        (("email", "per.hansen@example.org"), per, "Per Hansen", 2),
    ):
        lb.append(
            at="2026-06-01T08:00:00Z",
            source="manual",
            kind="resolution",
            tier=tier,
            payload={
                "schema": "resolution/v1",
                "ref": {"kind": ref[0], "value": ref[1]},
                "entity": {"type": "person", "id": entity, "registry": "logbook"},
                "label": label,
                "method": "owner",
            },
        )
    lb.append(
        at="2026-06-10T09:00:00Z",
        end="2026-06-10T10:00:00Z",
        source="ios-calendar",
        kind="event",
        tier=1,
        payload={
            "schema": "event/v1",
            "raw_id": "e-1",
            "title": "Harbour walk",
            "all_day": False,
            "attendees": [
                {"ref": {"kind": "email", "value": "kari.nordmann@example.org"}, "response": "accepted"},
                {"ref": {"kind": "email", "value": "per.hansen@example.org"}, "response": "accepted"},
            ],
        },
    )
    lb.append(
        at="2026-06-12T18:00:00Z",
        source="whatsapp",
        kind="message",
        tier=2,
        payload={
            "schema": "message/v1",
            "raw_id": "m-1",
            "chat": {"id": "447700900002@s.whatsapp.net", "name": "Kari", "type": "direct"},
            "sender": {"kind": "phone", "value": "+447700900002", "name": "Kari"},
            "from_me": False,
            "text": "The lighthouse key is under the blue stone",
        },
    )
    lb.append(
        at="2025-03-02T18:00:00Z",
        source="whatsapp",
        kind="message",
        tier=2,
        payload={
            "schema": "message/v1",
            "raw_id": "m-0",
            "chat": {"id": "447700900002@s.whatsapp.net", "name": "Kari", "type": "direct"},
            "sender": {"kind": "phone", "value": "+447700900002", "name": "Kari"},
            "from_me": False,
            "text": "The ferry leaves early tomorrow",
        },
    )
    return lb


def test_a_page_at_tier_one_shows_no_tier_two_line_name_or_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = _two_tiers(tmp_path / "lb")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    kari = "a6f3c2d1-0000-4000-8000-0000000000a1"
    every = _get(_site(lb), "/people")
    assert "Per Hansen" in every and "Kari Nordmann" in every and "2 people in your record" in every
    said = _get(_site(lb), f"/people/{kari}?said=1")
    assert "lighthouse key" in said, "the server reads every tier"
    gated = _site(lb, tiers=(1,))
    for target in ("/people", f"/people?sel={kari}", f"/people/{kari}", f"/people/{kari}?said=1"):
        text = _get(gated, target)
        assert "Per Hansen" not in text, target
        assert "lighthouse" not in text and "Messages back and forth" not in text, target
        assert "2 people" not in text, target
    door = _get(gated, "/people")
    assert "1 person in your record" in door and "Kari Nordmann" in door
    assert "year=2025" in every and "2025" not in page_text.seen(_door(door)), "a year only tier 2 gives"
    assert "ferry" not in door and "MAR 2025" not in door
    assert 'id="review"' in every and 'id="review"' not in door, "the queue reads every tier: not here"
    assert gated.respond("/people/a6f3c2d1-0000-4000-8000-0000000000a2").status == 404, "Per is tier 2"


def _beside(text: str, names: list[str]) -> list[str]:
    """Every place a number stands beside a person's name, by main's strong guard
    (`tests/test_no_count_beside_a_name.py`, #423, #430): a digit, then nothing but separators
    (`figures.SEPARATORS`, nothing at all among them), then a name, or the other way round, no boundary
    asked of the name; a date or a clock time is a figure too (`figures.CALENDAR`). Read over the page's
    text as a reader sees it, one run from top to bottom (a block's break is a separator, so a figure
    at the end of one block beside a name at the start of the next is beside it), an SVG tooltip's
    among it, and over every `title`, `aria-label` and `alt`, each on its own."""
    alt = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    sep = figures.SEPARATORS
    guard = re.compile(rf"(\d{sep}(?:{alt}))|((?:{alt})\??{sep}\d)")
    shown = [page_text.seen(text), *(html.unescape(t) for t in TITLES.findall(text))]
    short = re.compile(rf"…[0-9a-f-]{{{drafts.ID_SHORT}}}(?![0-9a-f])")  # a line's id, shortened: main's too
    return [
        m.group(0) for said in shown for m in guard.finditer(figures.CALENDAR.sub("0", short.sub(" ", said)))
    ]


def _names(lb: Logbook) -> list[str]:
    known = people.directory(lb).known.values()
    return sorted({p.name for p in known} | {p.name.split()[0] for p in known})


def test_no_number_beside_a_person_s_name_on_any_page_of_the_door(
    lb: Logbook, years: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every page and state of the door: the orbit with nobody asked for and with each person asked
    for, a year, the whole threads, what was said, a day marked, a gated page and an exported one."""
    site = _site(lb)
    names = _names(lb)
    ids = _ids(lb)
    targets = [
        *_pages(lb),
        *(f"/people?sel={e}" for e in ids.values()),
        *(f"/people/{e}?said=1" for e in ids.values()),
    ]
    for target in targets:
        assert _beside(_get(site, target), names) == [], target
    for gated in (_site(lb, tiers=(1, 2)), _site(lb, tiers=(1, 2), href=lambda path: None)):
        for target in ("/people", f"/people/{ids['Ola Nordmann']}"):
            assert _beside(_get(gated, target), names) == [], target
    four = _site(years, OCTOBER)
    names = _names(years)
    targets = [
        "/people",
        "/people?year=2022",
        "/people?year=2024",
        "/people?page=1",
        *(f"/people/{e}" for e in _ids(years).values()),
        *(f"/people?sel={e}" for e in _ids(years).values()),
    ]
    for target in targets:
        assert _beside(_get(four, target), names) == [], target
    two = _two_tiers(tmp_path / "two")
    monkeypatch.setenv("LOGBOOK_HOME", str(two.root))
    for target in ("/people", "/people/a6f3c2d1-0000-4000-8000-0000000000a1?said=1"):
        for tiers in (None, (1,)):
            assert _beside(_get(_site(two, tiers=tiers), target), _names(two)) == [], (target, tiers)


def test_no_script_no_reference_away_and_the_record_s_policy(lb: Logbook) -> None:
    site = _site(lb)
    for target in _pages(lb):
        path, _, query = target.partition("?")
        response = site.respond(path, query)
        text = response.body.decode("utf-8")
        assert response.csp == doors.CSP and "script-src" not in response.csp, target
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"], target
        assert '<header class="doors">' in text and 'aria-current="page">People</a>' in text, target
        assert "<script" not in text.lower(), target
        assert "http://" not in text and "https://" not in text, target
        for found in REFERENCE.findall(text):
            ref = html.unescape(found)
            assert ref.startswith("/") and not ref.startswith("//"), (target, ref)
        assert response.etag is not None, target
        assert "@import" not in text, "no stylesheet fetched"
        assert all(u.startswith("/font/") for u in re.findall(r"url\(([^)]*)\)", text)), (
            "the doors' own faces"
        )


def test_serving_the_door_writes_nothing(lb: Logbook) -> None:
    site = _site(lb)
    head = lb.meta["head"]
    files = {p.relative_to(lb.root).as_posix(): p.read_bytes() for p in lb.root.rglob("*") if p.is_file()}
    for target in _pages(lb):
        _get(site, target)
    after = {p.relative_to(lb.root).as_posix(): p.read_bytes() for p in lb.root.rglob("*") if p.is_file()}
    assert Logbook(lb.root).meta["head"] == head and after == files


# -- the year, the list, a phone, a file -------------------------------------------------------------------


def test_a_year_and_the_list_of_everyone_else_on_the_four_years(years: Logbook) -> None:
    site = _site(years, OCTOBER)
    text = _get(site, "/people?year=2022")
    found = door_people.circle(site, "2022")
    assert found is not None
    assert [n.person.name for n in found.near][:2] == ["Elin Moe", "Astrid Bakke"], "the most days in 2022"
    assert '<h2 class="name" id="thread-name">Elin Moe</h2>' in text
    assert "<b>2022</b>" in text and 'href="/people"' in text, "the years, and the last year"
    assert 'name="year" value="2022"' in text, "the queue's forms carry the year back, as they did"


def test_the_door_fits_a_phone(lb: Logbook) -> None:
    site = _site(lb)
    for target in _pages(lb)[:7]:
        text = _get(site, target)
        assert phone_width.problems(text) == [], target
    css = door_people.STYLE
    for selector in (".door-people .pill{", ".door-people .years a,", ".door-people ul.names a{"):
        rule = css[css.index(selector) :]
        assert re.search(r"min-height:4[46]px", rule[: rule.index("}")]), selector


def test_an_exported_page_has_no_form_and_links_only_what_it_has(lb: Logbook) -> None:
    site = _site(lb, href=lambda path: None, tiers=(1, 2))
    text = _get(site, "/people")
    assert "<form" not in text and "<a " not in _door(text) and 'id="review"' not in text
    assert "Ola" in text


def test_the_door_is_built_and_served_as_built(lb: Logbook) -> None:
    library = library_build.Library(lb, now=lambda: JULY)
    site = _site(lb)
    ola = _ids(lb)["Ola Nordmann"]
    result = library_build.build(lb, site, library, only=["/people", f"/people/{ola}"])
    assert result.failed == {}
    served = _site(lb, library=library)
    for target in ("/people", f"/people/{ola}"):
        _page, body = library.page(target) or pytest.fail(target)
        assert body == library_build.stamped(site.respond(*target.partition("?")[::2]).body, "12:00")
        response = served.respond(target)
        assert response.status == 200 and b"built 12:00" in response.body
