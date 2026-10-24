"""Today, the front door (RFC 0047 §4.1, `logbook/contrib/door_today.py`), and the shell every door
shares (§6, `logbook/contrib/library_shell.py`): the header on every page, `/shelves`, the tokens and the
fonts the Library serves itself.

On the demo month (`logbook demo`, read on its last morning), on an empty record, and on a small Oslo
record written here (`_record`): nights at home, promises in notes, a calendar entry with Kari Nordmann
tomorrow, a signed reflection a year back. Nobody here exists: the Oslo persona, addresses at
example.org."""

from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

import page_text
import pytest
from library_header import header_of, without_shell
from persona import HOME, KARI, KARI_ID, attendee, dwell, event, note, photo, resolution, utc

from logbook.contrib import day_rhythm, demo, door_today, library_shell, serve
from logbook.core import people, stars
from logbook.core.store import Logbook

LOOPBACK = "127.0.0.1"
JUNE_MORNING = datetime(2026, 6, 30, 5, 12, tzinfo=UTC)  # 07:12 in Oslo, the demo month's last day
TODAY = "2026-10-24"  # a Saturday
MORNING = datetime(2026, 10, 24, 5, 12, tzinfo=UTC)  # 07:12 in Oslo (summer time ends tomorrow)
A_YEAR_AGO = "2025-10-24"
TWO_YEARS_AGO = "2024-10-24"
REFLECTION = "We sailed to Drøbak and back before the wind turned. Kari steered the whole way home."
PLACES = {"Home": {"lat": HOME[0], "lon": HOME[1], "radius_m": 120, "kind": "home"}}
REFERENCE = re.compile(r"""(?:href|src|action)\s*=\s*["']([^"']*)["']|url\(\s*["']?([^"')]*)""", re.I)
FRONT = Path(__file__).parent / "fixtures" / "front_page_before_the_doors.html"
PROMISES = [  # said in the fortnight before Today, the oldest first: nine, so two are counted
    ("2026-10-12", "I'll send the harbour master the berth form."),
    ("2026-10-13", "I'll call the sailmaker about the jib."),
    ("2026-10-14", "I'll book the crane for the haul-out."),
    ("2026-10-16", "I'll bring the charts back to the club."),
    ("2026-10-17", "I'll write to the insurer about the dent."),
    ("2026-10-19", "I'll order the new fenders."),
    ("2026-10-20", "I'll check the bilge pump."),
    ("2026-10-22", "I'll pay the mooring fee."),
    ("2026-10-24", "I'll clean the cockpit drains by tomorrow."),
]


# -- the records ----------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def demo_lb(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    return demo.generate(tmp_path_factory.mktemp("today-demo") / "Demo", days=30, seed=1)


def _site(lb: Logbook, now: datetime = MORNING, **kwargs: object) -> serve.Site:
    return serve.Site(lb, now=lambda: now, **kwargs)  # type: ignore[arg-type]


def _get(site: serve.Site, target: str = "/") -> str:
    path, _, query = target.partition("?")
    response = site.respond(path, query)
    assert response.status == 200, (target, response.status, response.body[:300])
    return response.body.decode("utf-8")


def _home(day: str) -> list[dict[str, object]]:
    return dwell(day, "00:00", "24:00", HOME, every_min=30)


def _record(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    year_ago: str = "signed",
    promises: list[tuple[str, str]] = PROMISES,
) -> Logbook:
    """Nights at home before Today, the promises of `promises` in notes, Kari Nordmann named and at
    tomorrow's dinner, and a year back as `year_ago` says: `signed` (a reflection, signed), `quiet` (a
    line, nothing worth showing, and a starred photo two years back), `none` (nothing back at all)."""
    lb = Logbook.init(root / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    (lb.root / "places.json").write_text(json.dumps(PLACES), encoding="utf-8")
    drafts: list[dict[str, object]] = [resolution(("email", KARI["email"]), KARI_ID, "Kari Nordmann")]
    for day in ("2026-10-23", TODAY):
        drafts += _home(day)
    drafts += [note(utc(day, "09:00"), text) for day, text in promises]
    drafts.append(
        event(utc("2026-10-25", "19:00"), utc("2026-10-25", "21:00"), "Dinner", [attendee(KARI["email"])])
    )
    if year_ago == "signed":
        drafts += _home(A_YEAR_AGO)
    elif year_ago == "quiet":
        drafts.append(note(utc(A_YEAR_AGO, "08:00"), "The dentist moved to Thursday."))
        drafts.append(photo(utc(TWO_YEARS_AGO, "12:00")))
    lb.append_many(drafts)
    lb = Logbook(lb.root)
    if year_ago == "signed":
        site = _site(lb)
        _act(site, A_YEAR_AGO, "reflect", act="reflect", text=REFLECTION)
        _act(site, A_YEAR_AGO, "sign", act="sign", **_sign_fields(site, A_YEAR_AGO))
    elif year_ago == "quiet":
        with lb.index() as idx:
            (shot,) = [line for line in idx.day(TWO_YEARS_AGO) if line["kind"] == "photo"]
        stars.star(lb, str(shot["id"]))
    return Logbook(lb.root)


def _act(site: serve.Site, day: str, to: str, client: str = LOOPBACK, **form: str) -> serve.Response:
    response = site.write(f"/day/{day}/{to}", form, client, None)
    assert response.status == 303, (to, response.status, response.body[:300])
    return response


def _sign_fields(site: serve.Site, day: str) -> dict[str, str]:
    page = _get(site, f"/day/{day}")
    found = re.search(r'<form class="sign"[^>]*>.*?</form>', page, re.S)
    assert found is not None
    fields = re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', found.group(0))
    return {name: html.unescape(value) for name, value in fields}


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    return _record(tmp_path, monkeypatch)


def _section(page: str, name: str) -> str:
    found = re.search(rf'<section class="{name}[^"]*"[^>]*>.*?</section>', page, re.S)
    return found.group(0) if found else ""


def _rows(page: str, name: str) -> list[str]:
    return re.findall(r'<span class="what">(.*?)</span>', _section(page, name), re.S)


# -- Today on the demo month and on an empty record -------------------------------------------------------


def test_today_on_the_demo_month(demo_lb: Logbook) -> None:
    site = _site(demo_lb, JUNE_MORNING)
    response = site.respond("/")
    page = response.body.decode("utf-8")
    assert response.status == 200 and response.etag is not None
    assert response.csp == serve.DAY_IMAGES and "script-src" not in response.csp, "the photo, no script"
    assert "<h1>Tuesday, 30 June</h1>" in page and '<p class="mono-label">HOME · 07:12</p>' in page
    assert "Not signed yet." in page
    owe = _section(page, "owe")
    assert "<h2>What you owe</h2>" in owe and re.search(r"\d+ open · read from your record", owe)
    assert "A reply to Marta Keller" in owe, "the replies owed, as the Day's morning reads them"
    owed = _section(page, "owed")
    assert "<h2>Owed to you</h2>" in owed and "Liv Berg promised, in a mail yesterday" in owed
    assert "Sigrid Moen promised" in owed and "FRI" not in owed.upper().split("“")[0]
    assert "Per Hansen" in _section(page, "words"), "who was I with"
    for said in ("This week, signed", "Coming up", door_today.LEGEND, door_today.HERE):
        assert html.escape(said) in page, said
    assert '<a href="/" aria-current="page">Today</a>' in header_of(page)
    assert site.respond("/", "", response.etag).status == 304


def test_today_on_an_empty_record_says_what_fills_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lb = Logbook.init(tmp_path / "empty", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    page = _get(_site(lb))
    seen = " ".join(page_text.seen(page).split())
    assert "Saturday, 24 October" in seen and "The record has no lines yet." in seen
    for gone in (
        'class="owe"',
        'class="owed"',
        'class="year-ago"',
        'class="photo"',
        'class="words',
        "Sign it",
    ):
        assert gone not in page, gone
    assert "No day signed yet this week." in seen and door_today.LEGEND in seen
    assert library_shell.WORDMARK in header_of(page)


# -- What you owe and Owed to you -------------------------------------------------------------------------


def test_what_you_owe_shows_seven_the_oldest_first_and_counts_the_rest(lb: Logbook) -> None:
    page = _get(_site(lb))
    owe = _section(page, "owe")
    rows = _rows(page, "owe")
    assert len(rows) == door_today.MOST == 7
    quotes = [html.unescape(r).strip("“”") for r in rows]
    assert quotes == [text for _day, text in PROMISES[:7]], "the oldest first"
    assert "9 open · read from your record" in owe
    assert '<a href="/promises">and 2 more</a>' in owe, "the rest, counted, to the full list"
    first = re.search(r'<a class="row" href="([^"]+)"', owe)
    assert first is not None and first.group(1).startswith("/day/2026-10-12#l-"), (
        "its moment: its day, its line"
    )
    assert 'class="prov pencil" title="Proposed by the promises reader' in owe, "a rule's proposal is pencil"


def test_a_row_carries_its_due_day_as_words(lb: Logbook) -> None:
    assert door_today.due_words(TODAY, TODAY) == "Today"
    assert door_today.due_words("2026-10-25", TODAY) == "Tomorrow"
    assert door_today.due_words("2026-10-30", TODAY) == "Fri 30 Oct"
    assert door_today.due_words("2027-01-04", TODAY) == "Mon 4 Jan 2027"
    few = _get(_site(_record(lb.root.parent / "few", pytest.MonkeyPatch(), promises=PROMISES[-1:])))
    assert '<span class="due">Tomorrow</span>' in _section(few, "owe")


def test_owed_to_you_says_one_kind_sentence_when_nothing_is(lb: Logbook) -> None:
    owed = _section(_get(_site(lb)), "owed")
    assert "<h2>Owed to you</h2>" in owed and door_today.OWED_EMPTY in owed and "<ol" not in owed


def test_nothing_owed_says_what_will_fill_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    owe = _section(_get(_site(_record(tmp_path, monkeypatch, promises=[]))), "owe")
    assert html.escape(door_today.OWE_EMPTY, quote=False) in owe and "open ·" not in owe


# -- a year ago today --------------------------------------------------------------------------------------


def test_a_year_ago_is_its_signed_reflections_first_sentence(lb: Logbook) -> None:
    card = _section(_get(_site(lb)), "year-ago")
    assert '<p class="mono-label">A year ago today</p>' in card
    assert '<p class="said">We sailed to Drøbak and back before the wind turned.</p>' in card
    assert '<p class="where">Friday 24 October 2025 · Home</p>' in card
    assert f'<a class="pill" href="/day/{A_YEAR_AGO}">Open that day</a>' in card


def test_a_quiet_year_gives_way_to_the_nearest_earlier_year_that_holds_something(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    card = _section(_get(_site(_record(tmp_path, monkeypatch, year_ago="quiet"))), "year-ago")
    assert '<p class="mono-label">2 years ago today</p>' in card, "a year back holds a note and no more"
    assert "A photo you starred." in card and f'href="/day/{TWO_YEARS_AGO}"' in card
    assert "Thursday 24 October 2024" in card


def test_no_year_back_is_no_card(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    page = _get(_site(_record(tmp_path, monkeypatch, year_ago="none")))
    assert 'class="year-ago"' not in page and "years ago" not in page.lower()


def test_the_same_date_a_year_back_of_the_twenty_ninth_of_february() -> None:
    assert door_today.same_date("2028-02-29", 1) == "2027-02-28"
    assert door_today.same_date("2028-02-29", 4) == "2024-02-29"


# -- your day, in your words -------------------------------------------------------------------------------


def test_the_questions_are_answered_from_the_record(lb: Logbook) -> None:
    site = _site(lb)
    words = _section(_get(site), "words")
    assert "<dt>What did I promise?</dt><dd>1, further down the list</dd>" in words, "said today, the ninth"
    assert "<dt>Who was I with?</dt><dd>Nobody the record saw yet.</dd>" in words
    assert "<dt>How did my ideas move?</dt><dd>No idea moved yet today.</dd>" in words
    response = site.write("/with", {"day": TODAY, "names": "Kari Nordmann"}, LOOPBACK, None)
    assert response.status in (303, 200), response.body[:300]
    _act(site, TODAY, "reflect", act="reflect", text="A slow morning. The tea went cold.")
    words = _section(_get(site), "words")
    assert '<p class="mono-label">Ink · written' in words and '<p class="ink">A slow morning.' in words
    assert ">Kari Nordmann</a></dd>" in words, "who was I with: names only"
    assert ">Add to the reflection</button>" in words and ">Sign</button>" in words


def test_a_promise_made_today_is_counted_above_when_it_is_shown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    words = _section(_get(_site(_record(tmp_path, monkeypatch, promises=PROMISES[-2:]))), "words")
    assert "<dt>What did I promise?</dt><dd>1, above</dd>" in words


def test_the_acts_are_the_day_pages_forms_posting_to_its_routes(lb: Logbook) -> None:
    site = _site(lb)
    _act(site, TODAY, "reflect", act="reflect", text="Rain all day.")
    today, day = _get(site), _get(site, f"/day/{TODAY}")

    def fields(page: str, cls: str) -> tuple[str, list[str]]:
        found = re.search(
            rf'<form class="{cls}" method="post" action="([^"]+)"[^>]*>(.*?)</form>', page, re.S
        )
        assert found is not None, cls
        return found.group(1), sorted(re.findall(r'name="([^"]+)"', found.group(2)))

    for cls in ("reflect", "sign"):
        assert fields(today, cls) == fields(day, cls), cls
    assert fields(today, "sign")[0] == f"/day/{TODAY}/sign"
    hidden = _sign_fields(site, TODAY)
    found = re.search(r'<form class="sign".*?</form>', today, re.S)
    assert found is not None
    for name, value in hidden.items():
        assert f'name="{name}" value="{html.escape(value)}"' in found.group(0), name


@pytest.mark.parametrize("to", ["reflect", "sign"])
def test_the_write_gate_refuses_the_acts_from_anywhere_but_this_machine(lb: Logbook, to: str) -> None:
    site = _site(lb)
    before = (lb.meta["seq"], lb.meta["head"])
    form = {"act": to, "text": "Written from elsewhere."} if to == "reflect" else {"act": to}
    refused = site.write(f"/day/{TODAY}/{to}", form, "192.0.2.7", None)
    assert refused.status == 403 and b"nothing was written" in refused.body
    proxied = site.write(f"/day/{TODAY}/{to}", form, LOOPBACK, "https://phone.example.org", None)
    assert proxied.status == 403
    elsewhere = site.write(f"/day/{TODAY}/{to}", form, LOOPBACK, "http://evil.example.org")
    assert elsewhere.status == 403
    lb = Logbook(lb.root)
    assert (lb.meta["seq"], lb.meta["head"]) == before, "nothing written"


# -- the aside ---------------------------------------------------------------------------------------------


def test_the_week_and_what_is_coming(lb: Logbook) -> None:
    page = _get(_site(lb))
    week = re.search(r'<ol class="week">(.*?)</ol>', page, re.S)
    assert week is not None and week.group(1).count("<li>") == 7
    assert 'aria-label="Saturday 24 October: not signed"' in week.group(1)
    assert 'href="/day/2026-10-19"' in week.group(1) and 'href="/day/2026-10-25"' not in week.group(1)
    assert "No day signed yet this week." in page
    ahead = re.search(r'<ul class="ahead">.*?</ul>', page, re.S)
    assert ahead is not None and "Sun 25 Oct" in ahead.group(0) and ">Dinner</span>" in ahead.group(0)
    assert "with Kari Nordmann" in page_text.seen(ahead.group(0))


def test_a_signed_day_fills_its_circle(lb: Logbook) -> None:
    site = _site(lb)
    _act(site, TODAY, "reflect", act="reflect", text="Rain all day.")
    _act(site, TODAY, "sign", act="sign", **_sign_fields(site, TODAY))
    page = _get(site)
    assert 'aria-label="Saturday 24 October: signed"' in page and "One day signed this week." in page
    assert re.search(r'<p class="state signed"><svg[^>]*>.*?</svg><span>Signed at \d\d:\d\d</span></p>', page)


# -- the record's rules ------------------------------------------------------------------------------------


class _Said(HTMLParser):
    """The page's text, and every title and aria-label, each a run of its own."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.runs: list[str] = []
        self.text: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.skip += tag in ("style", "script")
        self.runs += [v for k, v in attrs if k in ("title", "aria-label", "placeholder", "alt") and v]

    def handle_endtag(self, tag: str) -> None:
        self.skip -= tag in ("style", "script")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.text.append(data)


def _beside_a_name(page: str, names: list[str]) -> list[str]:
    said = _Said()
    said.feed(page)
    runs = [" ".join(" ".join(said.text).split()), *said.runs]
    found = []
    for name in names:
        n = re.escape(name)
        guard = re.compile(rf"(\d[\s(:×x#·,]*{n})|({n}\??[\s(:×x#·,]*\d)")
        found += [f"{name}: {m.group(0)!r}" for run in runs for m in guard.finditer(run)]
    return found


def _names(lb: Logbook) -> list[str]:
    known = [p.name for p in people.directory(lb).known.values() if p.name]
    return sorted({*known, *(n.split()[0] for n in known)}, key=len, reverse=True)


def test_no_number_stands_beside_a_name(demo_lb: Logbook, lb: Logbook) -> None:
    for record, now in ((demo_lb, JUNE_MORNING), (lb, MORNING)):
        page = _get(_site(record, now))
        assert _beside_a_name(page, _names(record)) == []
    assert _beside_a_name("<p>Kari Nordmann 3</p>", ["Kari Nordmann"]) != [], "the guard finds one"
    assert _beside_a_name('<a title="2 · Kari">x</a>', ["Kari"]) != [], "in a title too"


def test_a_page_at_tier_one_shows_no_line_name_or_count_above_it(lb: Logbook) -> None:
    every = _get(_site(lb))
    one = _get(_site(lb, tiers=(1,)))
    assert "harbour master" in every and "9 open" in every
    for above in (*(text for _d, text in PROMISES), "Kari", "Drøbak", "9 open", "open ·"):
        assert html.escape(above, quote=False) not in one, above
    assert "Dinner" in one, "the calendar entry is tier 1; who it is with rests on a tier-2 name"
    words = _section(one, "words")
    assert "Nothing yet today." in words


# -- the header, on every page -----------------------------------------------------------------------------


def _crawl(site: serve.Site, seeds: list[str], most: int = 80) -> Iterator[tuple[str, serve.Response]]:
    seen: set[str] = set()
    queue = list(seeds)
    while queue and len(seen) < most:
        target = queue.pop(0)
        if target in seen:
            continue
        seen.add(target)
        path, _, query = target.partition("?")
        response = site.respond(path, query)
        yield target, response
        if not response.content_type.startswith("text/html"):
            continue
        for found in re.findall(r'href="(/[^"#]*)', response.body.decode("utf-8")):
            link = html.unescape(found)
            if not link.startswith(("/photo/", "/fonts/")) and link not in seen:
                queue.append(link)


def test_every_page_carries_the_header_and_marks_its_door(demo_lb: Logbook) -> None:
    site = _site(demo_lb, JUNE_MORNING)
    seen = 0
    for target, response in _crawl(site, ["/", "/shelves", "/days", "/people", "/places", "/world"]):
        page = response.body.decode("utf-8")
        header = header_of(page)
        assert without_shell(page), target
        door = library_shell.current(target.partition("?")[0])
        marked = re.findall(r'<a href="([^"]+)"[^>]*aria-current="page"', header)
        expected = {library_shell.GEAR: ["/shelves"], None: []}.get(
            door, [t for n, t in library_shell.DOORS if n == door]
        )
        assert marked == expected, (target, marked)
        seen += 1
    assert seen >= 40
    for door, target in library_shell.DOORS:
        header = header_of(_get(site, target))
        assert f'<a href="{target}" aria-current="page">{door}</a>' in header, door
    gear = header_of(_get(site, "/days"))
    assert f'aria-label="{html.escape(library_shell.GEAR_LABEL)}"' in gear and "<svg viewBox" in gear
    assert '<form class="ask" role="search" method="get" action="/search">' in gear
    assert f'placeholder="{library_shell.ASK_PLACEHOLDER}"' in gear and 'name="q"' in gear


def test_the_doors_are_one_table() -> None:
    assert library_shell.DOORS == (
        ("Today", "/"),
        ("Life", "/days"),
        ("People", "/people"),
        ("Places", "/places"),
    )
    assert library_shell.current("/people/019cadd3-6bc0-7dcd-9133-000000000001") == "People"
    assert library_shell.current("/peoplex") is None and library_shell.current("/day/2026-06-30") is None


def test_shelves_is_the_front_page_as_it_was(demo_lb: Logbook) -> None:
    page = _get(serve.Site(demo_lb, now=lambda: datetime(2026, 7, 1, 10, 0, tzinfo=UTC)), "/shelves")
    main = page[page.index("<main>") : page.index("</main>") + len("</main>")] + "\n"
    assert main == FRONT.read_text(encoding="utf-8"), "every shelf, byte for byte as the front page had it"
    assert '<a href="/shelves" class="gear" aria-label' in page and 'aria-current="page"' in header_of(page)


def test_a_static_page_has_the_header_and_no_form(demo_lb: Logbook) -> None:
    static = serve.Site(demo_lb, now=lambda: JUNE_MORNING, href=lambda path: path)
    page = static.page_index()
    assert "<form" not in page and '<header class="shell">' in page
    assert without_shell(page, ask=False)


# -- the fonts, the tokens and the policy ------------------------------------------------------------------


def test_the_fonts_are_served_from_the_package_with_their_type_and_a_long_cache(demo_lb: Logbook) -> None:
    site = _site(demo_lb, JUNE_MORNING)
    for _family, _weight, _style, name in library_shell.FONTS:
        response = site.respond(f"/fonts/{name}")
        data = (library_shell.FONT_DIR / name).read_bytes()
        assert response.status == 200 and response.body == data and data[:4] == b"wOF2", name
        assert response.headers["Content-Type"] == "font/woff2"
        assert response.headers["Cache-Control"] == "public, max-age=31536000, immutable"
        assert response.etag == f'"font-{hashlib.sha256(data).hexdigest()[:32]}"'
        assert site.respond(f"/fonts/{name}", "", response.etag).status == 304
    for nowhere in (
        "/fonts/",
        "/fonts/serve.py",
        "/fonts/../serve.py",
        "/fonts/x.woff2",
        "/fonts/inter-OFL.txt",
    ):
        assert site.respond(nowhere).status == 404, nowhere


def test_each_family_keeps_its_licence_beside_its_files_inside_the_package() -> None:
    folder = library_shell.FONT_DIR
    assert folder.parent == Path(serve.__file__).parent and folder.parts[-3:] == (
        "logbook",
        "contrib",
        "fonts",
    )
    files = {name for *_rest, name in library_shell.FONTS}
    assert {p.name for p in folder.iterdir()} == files | set(library_shell.LICENCES)
    for licence in library_shell.LICENCES:
        assert "SIL Open Font License, Version 1.1" in (folder / licence).read_text(encoding="utf-8")
    root = Path(serve.__file__).parents[2]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert '[tool.hatch.build.targets.wheel]\npackages = ["logbook"]' in pyproject, (
        "everything under logbook/"
    )
    if (root / ".git").exists():  # a checkout: nothing ignores them, so the wheel built from it carries them
        ignored = subprocess.run(
            ["git", "check-ignore", *(str(folder / f) for f in sorted(files))],
            cwd=root,
            capture_output=True,
            encoding="utf-8",
        )
        assert ignored.returncode == 1 and ignored.stdout == "", ignored.stdout


def test_the_policy_adds_fonts_from_the_server_alone_and_nothing_else() -> None:
    before = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'"
    assert before.replace("form-action", "font-src 'self'; form-action") == serve.CSP
    for policy in (serve.DAY_CSP, serve.DAY_IMAGES, serve.PLACES_CSP, serve.WORLD_CSP):
        assert policy.count("font-src 'self'") == 1


def test_no_page_reaches_past_the_server(demo_lb: Logbook) -> None:
    site = _site(demo_lb, JUNE_MORNING)
    for target, response in _crawl(site, ["/", "/shelves", "/day/2026-06-30", "/people", "/world"], most=60):
        if not response.content_type.startswith("text/html"):
            continue
        page = response.body.decode("utf-8")
        for link, url in REFERENCE.findall(page):
            found = html.unescape(link or url)
            if found.startswith("https://www.notion.so/"):  # a task's own page, followed only on a click
                continue
            assert found.startswith(("/", "#")) and not found.startswith("//"), (target, found)
        faces = re.findall(r"url\(([^)]*)\)", page)
        assert all(f.startswith(library_shell.FONT_PATH) for f in faces), (target, faces)
        assert "fonts.googleapis" not in page and "@import" not in page, target


def _luminance(hex_: str) -> float:
    rgb = [int(hex_[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a: str, b: str) -> float:
    la, lb_ = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb_ + 0.05)


@pytest.mark.parametrize("tokens", [library_shell.LIGHT, library_shell.DARK], ids=["light", "dark"])
def test_every_text_on_its_ground_is_four_and_a_half_to_one(tokens: str) -> None:
    t = dict(pair.split(":") for pair in tokens.split(";"))
    for text in ("--ink", "--pencil"):
        for ground in ("--paper", "--surface", "--tint"):
            assert _contrast(t[text], t[ground]) >= 4.5, (
                text,
                ground,
                round(_contrast(t[text], t[ground]), 2),
            )
    for text in ("--card-dark-text", "--card-dark-muted"):
        assert _contrast(t[text], t["--card-dark"]) >= 4.5, text
    assert _contrast(t["--paper"], t["--ink"]) >= 4.5, "the primary pill: paper on ink"
    assert _contrast(t["--signal"], t["--surface"]) >= 4.5 or tokens is library_shell.DARK


# -- speed -------------------------------------------------------------------------------------------------


def test_today_reads_once_a_head_and_is_kept(demo_lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    site = _site(demo_lb, JUNE_MORNING)
    first = site.respond("/")
    calls: list[str] = []
    monkeypatch.setattr(day_rhythm, "promises_near", lambda *a, **k: calls.append("read") or [])
    again = site.respond("/")
    assert again.body == first.body and calls == [], "the same head, the same minute: the page as kept"


@pytest.mark.stress
def test_today_renders_live_in_under_a_tenth_of_a_second_on_the_demo_month(demo_lb: Logbook) -> None:
    serve.Site(demo_lb, now=lambda: JUNE_MORNING).respond("/days")  # the index, built
    took = []
    for _ in range(5):
        site = _site(demo_lb, JUNE_MORNING)
        started = time.perf_counter()
        assert site.respond("/").status == 200
        took.append(time.perf_counter() - started)
    assert sorted(took)[2] < 0.1, took
