"""The Places door (RFC 0047 §4.4), at `/places`: where a life has happened and where it goes next.

The head; the globe, drawn here as inline SVG on a dark card (a disc, a faint graticule, the coastlines
when the offline map file is set, the places as dots, the trips as arcs, home near the centre), with a
time scrubber under it that is links and a GET form; Next, the trips and visits ahead from the calendar
and the plan; Your places, home first; then the register of `places.json` and the review queue of
`setup places review`, as they were. `/places/ID` is one place: what it is, its days, who was there,
the trips through it. Every page reads through the Library's gate, never puts a number beside a
person's name, and carries no script of its own and nothing fetched. On the Oslo persona's fortnight
(`persona.py`), who does not exist, and records made here; nothing here is anyone's real life."""

from __future__ import annotations

import html
import json
import re
import shutil
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import oslo_map
import phone_width
import pytest
from ideas_record import notion
from persona import OLA, attendee, event, persona_record, utc

from logbook.contrib import door_places, serve
from logbook.contrib.map import KEY as MAP_KEY
from logbook.core.store import Logbook

AFTER = datetime(2026, 6, 22, 10, 0, tzinfo=UTC)  # the fortnight lived
BEFORE = datetime(2026, 6, 12, 10, 0, tzinfo=UTC)  # the Friday before the flight to Zürich
NAMES = ("Ola Nordmann", "Kari Nordmann", "Ola", "Kari")
HREF = re.compile(r"""href\s*=\s*["']([^"']*)["']""", re.I)
REFERENCE = re.compile(
    r"""(?:href|src|action|formaction|poster|data|srcset|cite)\s*=\s*["']([^"']*)["']""", re.I
)


@pytest.fixture(scope="module")
def pristine(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("door-places")
    with pytest.MonkeyPatch.context() as mp:
        return persona_record(folder, mp).root


@pytest.fixture
def lb(pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    shutil.copytree(pristine, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook(root)


def _site(lb: Logbook, now: datetime = AFTER, **kw: object) -> serve.Site:
    return serve.Site(Logbook(lb.root), now=lambda: now, **kw)  # type: ignore[arg-type]


def _get(site: serve.Site, path: str, query: str = "") -> str:
    response = site.respond(path, query)
    assert response.status == 200, (path, query, response.body[:300])
    return response.body.decode("utf-8")


def _door(text: str) -> str:
    """The door's own part of `/places`: everything above the register and the review queue."""
    start = text.index('<div class="door-places">')
    return text[start : text.index("<!-- /door-places -->")]


def _meta(lb: Logbook, **values: object) -> None:
    path = lb.root / "logbook.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(values)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# -- the guard: never a number beside a person's name (RFC 0047's rules; the Day's guard, #377) -------------

BESIDE = "[\\s(:×x#·,]*"
BREAK = "¶"
BLOCK = re.compile(
    r"</?(?:p|li|ol|ul|dl|dt|dd|div|section|main|header|footer|nav|h[1-6]|table|tr|td|th|details|summary"
    r"|blockquote|form|svg|br|title|text|g)\b[^>]*>",
    re.I,
)
WORDS = re.compile(
    r"""\s(?:title|aria-label|aria-description|alt|placeholder|label|summary|content|value)\s*=\s*"""
    r"""(?:"([^"]*)"|'([^']*)')""",
    re.I,
)


def _seen(page: str) -> str:
    page = re.sub(r"<(style|script)\b.*?</\1>", "", page, flags=re.S | re.I)

    def tag(found: re.Match[str]) -> str:
        said = [a or b for a, b in WORDS.findall(found.group(0))]
        return "".join(f"{BREAK}{w}{BREAK}" for w in said if w) + (
            BREAK if BLOCK.fullmatch(found.group(0)) else ""
        )

    return html.unescape(re.sub(r"<[^>]+>", tag, page))


def beside(text: str, names: Iterable[str]) -> list[str]:
    found = []
    for name in names:
        n = re.escape(name)
        found += [m.group(0) for m in re.finditer(rf"(\d{BESIDE}{n})|({n}\??{BESIDE}\d)", text)]
    return found


def test_the_guard_finds_a_number_beside_a_name() -> None:
    assert beside(_seen("<li>Ola Nordmann · 5</li>"), NAMES)
    assert beside(_seen('<a title="Ola Nordmann (3)" href="/x">x</a>'), NAMES)
    assert beside(_seen("<li>15\u201316 June with Ola Nordmann</li>"), NAMES) == []
    assert beside(_seen("<li>16 June</li><li>Ola Nordmann</li>"), NAMES) == []


# -- the door ------------------------------------------------------------------------------------------


def test_the_door_is_the_head_the_globe_next_and_your_places_then_the_register_and_the_queue(
    lb: Logbook,
) -> None:
    text = _get(_site(lb), "/places")
    door = _door(text)
    assert "<h1>Places</h1>" in door
    assert "Where your life has happened, and where it goes next." in door
    assert door.index("<svg") < door.index(">Next<") < door.index(">Your places<")
    assert door.index(">Your places<") < len(door) <= text.index("Name this place"), "the queue at the foot"
    assert "<td>Home</td>" in text[text.index("<!-- /door-places -->") : text.index("Name this place")]
    assert text.count("<script>") == 1 and serve.PLACES_SCRIPT in text, "the queue's keys, as before"
    assert "<script" not in door, "the door itself carries no script"


def test_the_globe_is_inline_svg_on_a_dark_card_turned_to_home(lb: Logbook) -> None:
    text = _get(_site(lb), "/places")
    door = _door(text)
    svg = re.search(r"<svg[^>]*>.*?</svg>", door, re.S)
    assert svg is not None
    globe = svg.group(0)
    assert 'role="img"' in globe and 'aria-label="' in globe
    assert 'class="disc"' in globe and 'class="graticule"' in globe
    assert 'class="coast"' not in globe, "no map file set: the graticule alone"
    home = re.search(r'<g class="place home"[^>]*>\s*(?:<circle[^>]*>\s*)*', globe)
    assert home is not None, "home is a light dot with its glow"
    x, y = (float(v) for v in re.search(r'cx="([\d.]+)" cy="([\d.]+)"', home.group(0)).groups())  # type: ignore[union-attr]
    w = float(re.search(r'viewBox="0 0 ([\d.]+) ', globe).group(1))  # type: ignore[union-attr]
    assert abs(x - w / 2) < w * 0.2 and abs(y - w / 2) < w * 0.2, "home near the centre"
    assert re.search(r'class="arc past"', globe), "the Zürich trip, lived: a muted arc"
    assert ".globe-card{background:#0E141B" in text, "the dark card, in the page's one stylesheet"


def test_the_coastlines_come_from_the_map_file_when_it_is_set(lb: Logbook, tmp_path: Path) -> None:
    land = [(4.0, 57.5), (4.0, 71.0), (31.0, 71.0), (31.0, 57.5)]  # a box over the north, invented
    shape = oslo_map.Shape("earth", oslo_map.POLYGON, [land], {"kind": "earth"}, min_zoom=0)
    tile = oslo_map.encode_tile(0, 0, 0, [shape])
    path = oslo_map.write_pmtiles(tmp_path / "world.pmtiles", {(0, 0, 0): tile})
    _meta(lb, **{MAP_KEY: str(path)})
    globe = re.search(r"<svg.*?</svg>", _door(_get(_site(lb), "/places")), re.S).group(0)  # type: ignore[union-attr]
    assert 'class="coast"' in globe and 'class="graticule"' in globe
    _meta(lb, **{MAP_KEY: str(tmp_path / "gone.pmtiles")})
    assert 'class="coast"' not in _door(_get(_site(lb), "/places")), "a file not there: the graticule alone"


def test_the_scrubber_runs_over_the_life_setting_else_the_record_to_next_year(lb: Logbook) -> None:
    door = _door(_get(_site(lb), "/places"))
    form = re.search(r'<form class="scrub" method="get" action="/places">.*?</form>', door, re.S)
    assert form is not None and 'type="range"' in form.group(0) and ">Go</button>" in form.group(0)
    assert 'min="2026"' in form.group(0) and 'max="2027"' in form.group(0), "the record's first year to next"
    assert "Your life, from 2026" in door and "June 2026 · choose a year to travel in time" in door
    _meta(lb, life={"from": "1986-07-01", "to": "2035-12-31"})
    door = _door(_get(_site(lb), "/places"))
    assert 'min="1986"' in door and 'max="2035"' in door
    years = re.findall(r'href="/places\?at=(\d{4})"', door)
    assert years[0] == "1986" and {"1990", "2000", "2025", "2035"} <= set(years)
    assert all(int(y) % 5 == 0 for y in years[1:-1]), "a link every five years"
    assert "Your life, from 1986" in door


def test_a_year_turns_the_globe_to_it(lb: Logbook) -> None:
    site = _site(lb)
    now = _door(_get(site, "/places", "at=2026"))
    assert 'value="2026"' in now and re.search(r'class="arc past"', now)
    assert "2026 · choose a year to travel in time" in now
    before = _door(_get(site, "/places", "at=2010"))
    assert not re.search(r'class="arc', before), "no trip that year"
    assert 'class="place home faint"' in before, "the places of other years faint"
    assert site.respond("/places", "at=59.9200,10.7400").status in (200, 302), "a stay's spot, as before"
    assert site.respond("/places", "at=nowhere").status == 400


def test_next_holds_the_trips_ahead_from_the_calendar(lb: Logbook) -> None:
    door = _door(_get(_site(lb, BEFORE), "/places"))
    ahead = door[door.index(">Next<") : door.index(">Your places<")]
    assert "Zürich" in ahead and "Ola Nordmann" in ahead, "the flight out, and who the dinner there is with"
    assert 'href="/life?trip=2026-06-15/2026-06-16"' in ahead
    assert re.search(r'class="arc next"[^>]*stroke-dasharray', door), "a warm dashed arc"
    assert "Zürich · 15 June" in door, "the arc's label"
    lived = _door(_get(_site(lb), "/places"))
    after = lived[lived.index(">Next<") : lived.index(">Your places<")]
    assert "Zürich" not in after and "Nothing ahead yet" in after, "a kind empty state"


def test_next_holds_the_trips_of_the_plan(lb: Logbook) -> None:
    trips = "00000303-0000-4000-8000-000000000303"
    row = "00000304-0000-4000-8000-000000000304"
    line = notion(
        "2026-06-01T10:00:00Z",
        row,
        "Lofoten",
        "created",
        parent={"type": "database", "id": trips},
        path=["Plan", "Trips"],
        properties={"When": {"start": "2026-07-03", "end": "2026-07-08"}},
    )
    Logbook(lb.root).append_many([line])
    (lb.root / "policy").mkdir(exist_ok=True)
    (lb.root / "policy" / "notion.json").write_text(json.dumps({"plan": {"trips": trips}}), encoding="utf-8")
    door = _door(_get(_site(lb), "/places"))
    ahead = door[door.index(">Next<") : door.index(">Your places<")]
    assert "Lofoten" in ahead and 'href="/life?trip=2026-07-03/2026-07-08"' in ahead


def test_your_places_are_home_first_with_the_owner_s_words_or_a_pencil_placeholder(lb: Logbook) -> None:
    door = _door(_get(_site(lb), "/places"))
    mine = door[door.index(">Your places<") :]
    rows = re.findall(r'<a class="place-name" href="/places/([a-z0-9-]+)">', mine)
    assert rows[0] == "home" and set(rows) == {"home", "office", "marina"}
    assert ">Home</span>" in mine, "home says what it is"
    assert ">boat</span>" in mine, "the Marina's tag: the owner's own word"
    placeholder = re.search(
        r'<a class="pencil[^"]*" href="/places/office#what" title="([^"]+)">([^<]+)</a>', mine
    )
    assert placeholder is not None and placeholder.group(2) == "[what it holds for you]"
    assert not re.search(r">\s*\d+\s*(?:days?|nights?)", mine), "the order is the only signal"


def test_a_place_s_page_is_its_days_its_people_and_its_trips(lb: Logbook) -> None:
    site = _site(lb)
    office = _get(site, "/places/office")
    assert "<h1>Office</h1>" in office
    assert 'id="what"' in office and "[what it holds for you]" in office
    days = re.findall(r'href="/day/(2026-06-\d\d)"', office)
    assert "2026-06-11" in days, "a day there, a link to its Day"
    assert 'href="/people/019cadd3-6bc0-7dcd-9133-000000000002">Ola Nordmann</a>' in office
    assert not re.search(r"\b\d+ days?\b", _seen(office)), "no count of days printed"
    marina = _get(site, "/places/marina")
    assert ">boat<" in marina
    home = _get(site, "/places/home")
    assert "<h1>Home</h1>" in home and "Nobody yet." in home, "Kari's lunch was 1 km away: not at home"
    assert site.respond("/places/nowhere").status == 404


def test_a_page_at_tier_1_shows_no_tier_2_name(lb: Logbook) -> None:
    """Ola is at the office only by a tier-2 transcript: a page read at tier 1 does not name him there,
    nor anywhere a tier-2 line alone puts him."""
    gated = _site(lb, tiers=(1,))
    office = gated.respond("/places/office").body.decode("utf-8")
    assert "Ola Nordmann" not in office
    door = _door(gated.respond("/places").body.decode("utf-8"))
    assert "Ola Nordmann" not in door
    assert "Ola Nordmann" in _get(_site(lb), "/places/office"), "the server reads every tier"


@pytest.mark.parametrize("now", [AFTER, BEFORE], ids=["after", "before"])
@pytest.mark.parametrize("tiers", [None, (1,)], ids=["every-tier", "tier-1"])
def test_no_number_stands_beside_a_name(lb: Logbook, now: datetime, tiers: tuple[int, ...] | None) -> None:
    site = _site(lb, now, tiers=tiers)
    targets = ["/places", "/places?at=2026", "/places/home", "/places/office", "/places/marina"]
    for target in targets:
        path, _, query = target.partition("?")
        text = site.respond(path, query).body.decode("utf-8")
        assert beside(_seen(text), NAMES) == [], target


def test_every_address_in_the_door_answers(lb: Logbook) -> None:
    """Every link the door and its place pages make is a page of this server, or a moment on Life
    (`/life?trip=FIRST/LAST`, the door built beside this one); nothing is linked twice the same wrong way."""
    site = _site(lb, BEFORE)
    seen: set[str] = set()
    queue = ["/places", "/places?at=2026", "/places?at=1990"]
    while queue:
        target = queue.pop(0)
        if target in seen:
            continue
        seen.add(target)
        path, _, query = target.partition("?")
        response = site.respond(path, query)
        assert response.status == 200, target
        text = response.body.decode("utf-8")
        for link in HREF.findall(text):
            link = html.unescape(link).partition("#")[0]
            parts = urlsplit(link)
            if parts.path == "/life":
                assert re.fullmatch(r"trip=\d{4}-\d\d-\d\d/\d{4}-\d\d-\d\d", parts.query), link
            elif parts.path.startswith("/places") and link not in seen:
                queue.append(link)
            elif parts.path.startswith(("/day/", "/people/")):
                assert site.respond(parts.path, parts.query).status == 200, link
    assert {"/places/home", "/places/office", "/places/marina"} <= seen


def test_no_script_and_nothing_outside_the_server(lb: Logbook) -> None:
    site = _site(lb, BEFORE)
    for target in ("/places", "/places/home", "/places/office"):
        response = site.respond(target)
        text = response.body.decode("utf-8")
        for found in REFERENCE.findall(text):
            got = html.unescape(found)
            assert got.startswith("/") and not got.startswith("//") and ":" not in got.split("?")[0], got
        assert "url(" not in text and "@import" not in text and "<link" not in text
        if target != "/places":
            assert "<script" not in text and "script-src" not in response.headers["Content-Security-Policy"]


def test_the_door_fits_a_phone(lb: Logbook) -> None:
    site = _site(lb, BEFORE)
    for target in ("/places", "/places/home", "/places/office"):
        text = _get(site, target)
        assert phone_width.problems(text) == [], target
        assert phone_width.phone_breakpoints(phone_width.parse(text)[1]), target


def test_an_empty_record_says_what_fills_each_part(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lb = Logbook.init(tmp_path / "empty", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    text = _get(_site(lb), "/places")
    door = _door(text)
    assert "<h1>Places</h1>" in door and 'class="disc"' in door
    assert "Nothing ahead yet" in door
    assert "No places yet" in door
    assert "name one below" in text, "the register's invitation, as before"
    assert _site(lb).respond("/places/home").status == 404


def test_the_globe_labels_at_most_eight_places(lb: Logbook) -> None:
    spread = {
        f"Place {n}": {"lat": 40.0 + 2 * (n % 5), "lon": -10.0 + 6 * n, "radius_m": 150} for n in range(12)
    }
    spread["Home"] = {"lat": 59.9139, "lon": 10.7522, "radius_m": 120, "kind": "home"}
    (lb.root / "places.json").write_text(json.dumps(spread), encoding="utf-8")
    globe = re.search(r"<svg.*?</svg>", _door(_get(_site(lb), "/places")), re.S).group(0)  # type: ignore[union-attr]
    assert len(re.findall(r'<text class="label', globe)) <= door_places.LABELS_MOST == 8


def test_a_static_site_carries_the_door_without_its_forms(lb: Logbook) -> None:
    built = serve.Site(Logbook(lb.root), tiers=(1,), href=lambda path: None)
    text = built.page_places()
    door = _door(text)
    assert "<form" not in door and 'class="disc"' in door
    assert "<a " not in door, "no page to link to: plain text"


def test_a_calendar_entry_ahead_at_a_named_place_away_from_home_is_a_visit(lb: Logbook) -> None:
    (lb.root / "places.json").write_text(
        json.dumps(
            {
                "Home": {"lat": 59.9139, "lon": 10.7522, "radius_m": 120, "kind": "home"},
                "the cabin": {"lat": 60.6, "lon": 9.1, "radius_m": 200, "tags": ["the cabin"]},
            }
        ),
        encoding="utf-8",
    )
    weekend = event(
        utc("2026-07-04", "10:00"), utc("2026-07-05", "16:00"), "Cabin weekend", [attendee(OLA["email"])],
        location="the cabin",
    )  # fmt: skip
    Logbook(lb.root).append_many([weekend])
    door = _door(_get(_site(lb), "/places"))
    ahead = door[door.index(">Next<") : door.index(">Your places<")]
    assert "the cabin" in ahead and "Ola Nordmann" in ahead
    assert 'href="/life?trip=2026-07-04/2026-07-05"' in ahead
