"""Today, the Library's front door (RFC 0047 §4.1), and the frame every door shares (`doors`): the
header (the wordmark, the four doors, Ask and the gear), one stylesheet of the owner's tokens, and the
three typefaces served by the Library itself.

Today, from the top: the date and where the night was, the weather when the record holds it; what is
open (the promises both ways, the plan's tasks, the replies owed: seven at most, the oldest first, each
a link to its moment); one memory (this day a year ago, else the same date in the nearest earlier year
that holds a signed reflection, a starred photo or a trip, else none); then Reflect and sign, the Day's
own forms. On the Oslo persona's fortnight, Kari and Ola Nordmann, who do not exist; every address at
example.org, every number in 07700 900xxx; no test opens a connection."""

from __future__ import annotations

import html
import json
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import phone_width
import pytest
from dream_fortnight import NOTE_HOME, OLA_PROMISE, PROMISE_ZURICH, fortnight, message
from ideas_record import notion
from persona import CAFE, HOME, KARI, OLA, ZURICH, attendee, dwell, event, note, persona_record, photo, utc
from test_day_rhythm import _seen, beside

from logbook import cli
from logbook.contrib import day_rhythm, demo, door_gear, door_today, doors, library_build, serve
from logbook.core import index as index_module
from logbook.core import people
from logbook.core.store import Logbook

TZ = ZoneInfo("Europe/Oslo")
TODAY = "2026-06-19"  # a Friday, the morning after Zürich
YEAR_AGO, TWO_YEARS = "2025-06-19", "2024-06-19"
THEN_WORDS = "Sailed to Drøbak with Kari. The wind turned at four."
TASKS_DB = "00000100-0000-4000-8000-000000000100"
TASK = "Varnish the tiller"
UNANSWERED = "Har du tid til en tur på lørdag?"  # Ola's last word, on Wednesday: a reply owed


def _reflection(at: str, text: str) -> dict[str, Any]:
    line = note(at, text)
    line["payload"]["labels"] = ["reflection"]
    return line


def _home_day(day: str) -> list[dict[str, Any]]:
    """A day at home and nothing else: a day the record holds, and nothing worth showing on it."""
    return dwell(day, "00:00", "24:00", HOME, every_min=20)


def _worth_day(day: str) -> list[dict[str, Any]]:
    """A day years ago worth showing: lunch with Kari at the cafe, a favourite photo, a reflection."""
    return [
        *dwell(day, "00:00", "11:00", HOME, every_min=20),
        *dwell(day, "11:30", "14:00", CAFE, every_min=10),
        *dwell(day, "14:30", "24:00", HOME, every_min=20),
        event(utc(day, "12:00"), utc(day, "13:00"), "Lunch", [attendee(KARI["email"])]),
        photo(utc(day, "12:30"), CAFE, favorite=True),
        _reflection(utc(day, "22:00"), THEN_WORDS),
    ]


def _task(title: str, due: str) -> dict[str, Any]:
    return notion(
        "2026-06-01T07:00:00Z",
        "00000801-0000-4000-8000-000000000801",
        title,
        action="created",
        parent={"type": "database", "id": TASKS_DB},
        path=["Plan", "Tasks"],
        properties={"Due": {"start": due, "end": None}, "Status": "To do"},
    )


@pytest.fixture(scope="module")
def pristine(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The fortnight; a year ago a day at home, two years ago a day worth showing; a task due today in
    the task tool; and Ola's question on Wednesday, unanswered."""
    with pytest.MonkeyPatch.context() as mp:
        root = tmp_path_factory.mktemp("door-today") / "lb"
        mp.setenv("LOGBOOK_HOME", str(root))
        lb = fortnight(root)
        lb.append_many(
            [
                *_home_day(YEAR_AGO),
                *_worth_day(TWO_YEARS),
                _task(TASK, TODAY),
                message(utc("2026-06-17", "18:00"), UNANSWERED, {**OLA, "name": "Ola"}),
            ]
        )
        (lb.root / "policy" / "notion.json").write_text(
            json.dumps({"plan": {"tasks": TASKS_DB}}), encoding="utf-8"
        )
        cli.main(["derive", "keepers"])
        return lb.root


@pytest.fixture
def lb(pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    shutil.copytree(pristine, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook(root)


def _at(day: str, clock: str) -> datetime:
    return datetime.fromisoformat(f"{day}T{clock}:00").replace(tzinfo=TZ).astimezone(UTC)


def _site(lb: Logbook, day: str = TODAY, clock: str = "07:00", **kw: Any) -> serve.Site:
    return serve.Site(lb, now=lambda: _at(day, clock), **kw)


def _today(site: serve.Site) -> str:
    response = site.respond("/", "")
    assert response.status == 200, response.body[:300]
    return response.body.decode("utf-8")


def _section(page: str, name: str) -> str:
    start = page.index(f'<section class="{name}"')
    return page[start : page.index("</section>", start)]


def _text(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment))


def _main(page: str) -> str:
    return page[page.index('<main class="door">') : page.index("</main>")]


# -- the frame ---------------------------------------------------------------------------------------------


def test_the_front_door_is_today_in_the_doors_frame(lb: Logbook) -> None:
    page = _today(_site(lb))
    head = page[page.index('<header class="doors">') : page.index("</header>")]
    assert '<a class="wordmark" href="/">Logbook</a>' in head
    doors_ = re.findall(r'<nav class="doors"[^>]*>(.*?)</nav>', head)[0]
    assert re.findall(r'<a href="([^"]+)"', doors_) == ["/", "/life", "/people", "/places"]
    assert re.findall(r">([A-Za-z]+)</a>", doors_) == ["Today", "Life", "People", "Places"]
    assert '<a href="/" aria-current="page">Today</a>' in doors_
    ask = re.search(r'<form class="ask" method="get" action="/ask" role="search">.*?</form>', head)
    assert ask is not None and 'name="q"' in ask.group(0) and "<label" in ask.group(0)
    gear = re.search(r'<a class="gear" href="/gear"[^>]*aria-label="The gear"', head)
    assert gear is not None and "<svg" in head, "one icon, drawn inline"
    assert head.index("<nav") < head.index('<form class="ask"') < head.index('class="gear"'), "RFC 0047 §6"
    assert "<title>Today · Logbook</title>" in page
    assert page.count("<nav") == 1 and '<a href="/today">today</a>' not in page, "the doors' header alone"


def test_the_stylesheet_holds_the_owner_s_tokens_once_on_root(lb: Logbook) -> None:
    page = _today(_site(lb))
    style = re.search(r"<style>(.*?)</style>", page, re.S)
    assert style is not None
    css = style.group(1)
    root = re.search(r":root\{([^}]*)\}", css)
    assert root is not None
    for name, value in (
        ("--paper", "#F4F1EA"),
        ("--surface", "#FBFAF6"),
        ("--line", "#E3DED3"),
        ("--line-soft", "#ECE7DD"),
        ("--tint", "#EDE8DE"),
        ("--ink", "#16181D"),
        ("--pencil", "#62666D"),
        ("--pencil-rule", "#8C8F95"),
        ("--signal", "#C8401A"),
        ("--signal-deep", "#A93413"),
        ("--card-dark", "#16181D"),
        ("--card-dark-text", "#F4F1EA"),
        ("--card-dark-muted", "#C9C4B8"),
    ):
        assert f"{name}:{value};" in root.group(1) + ";", name
    for family, fallback in (
        ("--serif", "Instrument Serif"),
        ("--sans", "Inter"),
        ("--mono", "JetBrains Mono"),
    ):
        found = re.search(rf"{family}:([^;}}]*)", root.group(1))
        assert found is not None and fallback in found.group(1), family
        assert found.group(1).rstrip().endswith(("serif", "sans-serif", "monospace")), "a fallback last"
    assert css.count(":root{") == 2, "the tokens, and the same tokens for a dark page: defined here only"
    faces = re.findall(r"@font-face\{([^}]*)\}", css)
    assert {re.search(r'font-family:"([^"]+)"', f).group(1) for f in faces} == {  # type: ignore[union-attr]
        "Instrument Serif",
        "Inter",
        "JetBrains Mono",
    }
    urls = re.findall(r"url\(([^)]*)\)", css)
    assert urls and all(u in {f"/font/{name}" for name in doors.FACES} for u in urls), urls
    csp = _site(lb).respond("/").headers["Content-Security-Policy"]
    assert csp.startswith("default-src 'none'") and "font-src 'self'" in csp and "script-src" not in csp


def test_the_typefaces_are_served_by_the_library_with_their_licences(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    site = _site(lb)
    assert site.respond("/font/OFL-inter.txt").status == 404, "the folder's other files are not served"

    def opened(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("a font opened the index")

    monkeypatch.setattr(index_module.Index, "open", opened)
    for name, (family, _style, _weight) in doors.FACES.items():
        response = site.respond(f"/font/{name}")
        assert response.status == 200 and response.content_type == "font/woff2", name
        assert response.body[:4] == b"wOF2" and response.etag is not None, name
        assert site.respond(f"/font/{name}", "", if_none_match=response.etag).status == 304
        licence = (doors.FONT_DIR / doors.LICENCES[family]).read_text(encoding="utf-8")
        assert "SIL Open Font License, Version 1.1" in licence and family.replace(" ", "") in licence.replace(
            " ", ""
        ), family
    assert site.respond("/font/comic-sans.woff2").status == 404
    assert sorted(p.name for p in doors.FONT_DIR.iterdir() if p.suffix == ".woff2") == sorted(doors.FACES)


def test_today_fits_a_phone_with_the_doors_at_the_foot(lb: Logbook) -> None:
    page = _today(_site(lb))
    assert phone_width.problems(page) == []
    css = re.search(r"<style>(.*?)</style>", page, re.S).group(1)  # type: ignore[union-attr]
    breakpoints = phone_width.phone_breakpoints(css)
    assert breakpoints
    phone = css[css.index("@media (max-width:40rem)") :]
    assert re.search(r"nav\.doors\{[^}]*position:fixed;[^}]*bottom:0", phone), (
        "the doors are a bar at the foot"
    )
    ask = re.search(r"form\.ask\{([^}]*)\}", phone)
    assert ask is not None and "position:fixed" not in ask.group(1), "Ask stays at the top, in the header"


# -- Today, from the top ---------------------------------------------------------------------------------


def test_the_date_and_where_the_night_was(lb: Logbook) -> None:
    page = _today(_site(lb))
    date_ = _section(page, "date")
    assert '<a href="/day/2026-06-19">' in date_ and "Friday 19 June" in _text(date_)
    assert "Last night at Home" in _text(date_), "the night after Thursday, at home after Zürich"
    assert page.index('<section class="date"') < page.index('<section class="open"')


def test_what_is_open_both_ways_the_plan_and_the_replies_owed_oldest_first(lb: Logbook) -> None:
    site = _site(lb)
    page = _today(site)
    open_ = _section(page, "open")
    said = _text(open_)
    for words in (NOTE_HOME, PROMISE_ZURICH, OLA_PROMISE, TASK):
        assert words in said, words
    owed = day_rhythm.replies_owed(lb, TODAY, people.directory(lb), None)
    assert owed and all(o["name"] in said for o in owed), owed
    rows = re.findall(r"<li class=\"([a-z ]+)\"", open_)
    assert 0 < len(rows) <= 7
    assert said.index(NOTE_HOME) < said.index(PROMISE_ZURICH), "the oldest first"
    for row in re.findall(r"<li class=.*?</li>", open_, re.S):
        assert re.search(r'href="/(day|line)/', row), row  # each opens its moment
    assert 'class="what pencil"' in open_, "a promise the rules read is pencil until the owner says"
    names = sorted({p.name for p in people.directory(lb).known.values()})
    assert beside(_seen(page), names) == [], "no number beside a name"


def test_an_open_row_says_who_first_and_since_when_after_words(lb: Logbook) -> None:
    """The desk's case: when `since` carries the year it is said after the person and the words, never
    just before a name: *Ola Nordmann promised you · since Wed 23 December 2026*. What's open reads the
    fortnight, so the case is a promise of the fortnight across the new year (a year-old one is on the
    Promises shelf, never on Today)."""
    lb.append_many([message(utc("2026-12-23", "18:00"), OLA_PROMISE, {**OLA, "name": "Ola"})])
    lb = Logbook(lb.root)
    page = _today(_site(lb, "2027-01-02"))
    rows = re.findall(r'<li class="(promise|owed)">.*?<span class="sub">(.*?)</span></div></li>', page, re.S)
    subs = [_text(sub) for _, sub in rows]
    assert subs and all(s.endswith(" 2026") and s.count(" · since ") == 1 for s in subs), subs
    assert "Ola Nordmann promised you · since Wed 23 December 2026" in subs, subs
    names = sorted({p.name for p in people.directory(lb).known.values()})
    assert beside(_seen(page), names) == []


@pytest.fixture(scope="module")
def demo_record(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    with pytest.MonkeyPatch.context() as mp:
        root = tmp_path_factory.mktemp("door-today-demo") / "Demo"
        mp.setenv("LOGBOOK_HOME", str(root))
        return demo.generate(root)


def test_no_number_beside_a_name_on_any_morning_of_the_demo_record(
    demo_record: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The strong guard over every row of Today on the demo record, its titles and aria-labels too
    (`_seen`): each morning of the demo month, and each a year on, when every date carries its year."""
    monkeypatch.setenv("LOGBOOK_HOME", str(demo_record.root))
    names = sorted({p.name for p in people.directory(demo_record).known.values()})
    month = [demo.START + timedelta(days=n) for n in range(30)]
    days = [d.isoformat() for d in month] + [d.replace(year=d.year + 1).isoformat() for d in month]
    rows = 0
    for day in days:
        page = _today(_site(demo_record, day))
        rows += len(re.findall(r"<li class=", _section(page, "open")))
        assert beside(_seen(page), names) == [], day
    assert rows > len(days), "the demo's promises and replies owed are on the page"


def test_since_is_a_weekday_within_the_week_and_a_date_before_it() -> None:
    assert door_today.since(TODAY, TODAY) == "today"
    assert door_today.since("2026-06-18", TODAY) == "since yesterday"
    assert door_today.since("2026-06-15", TODAY) == "since Monday"
    assert door_today.since("2026-06-08", TODAY) == "since Mon 8 June"
    assert door_today.since("2025-06-08", TODAY) == "since Sun 8 June 2025"


def test_a_door_s_footer_is_not_read_only_beside_its_forms(lb: Logbook) -> None:
    footer = re.search(r'<footer class="door">(.*?)</footer>', _today(_site(lb)), re.S)
    assert footer is not None and "read-only" not in footer.group(1)
    assert footer.group(1).startswith("Nothing here leaves this machine")
    assert "read-only" in _site(lb).respond("/days").body.decode("utf-8"), "the old pages as they were"


def test_what_is_open_is_seven_at_most_and_the_rest_one_link(lb: Logbook) -> None:
    lb.append_many(
        [
            note(utc(f"2026-06-{d:02d}", "20:00"), f"I'll send Kari Nordmann chart number {d} by Friday.")
            for d in range(8, 18)
        ]
    )
    open_ = _section(_today(_site(lb)), "open")
    rows = re.findall(r'<li class="(?!more)[a-z ]+"', open_)
    assert len(rows) == 7, rows
    more = re.search(r'<li class="more">.*?</li>', open_, re.S)
    assert more is not None and 'href="/promises"' in more.group(0)
    said = _text(open_)
    assert "chart number 8 " in said and said.index("chart number 8 ") < said.index("chart number 9 ")


def test_the_memory_is_exactly_a_year_back_first_whatever_it_holds(lb: Logbook) -> None:
    """The owner's answer (RFC 0047 §14.2, 25 October 2026): exactly a year back first. A year ago was a
    day at home and nothing else, and it is the memory, before the day two years back worth showing."""
    memory = _section(_today(_site(lb)), "memory")
    assert "A year ago today" in _text(memory) and "Two years ago" not in _text(memory)
    assert len(re.findall(r'href="/day/', memory)) == 1 and f'href="/day/{YEAR_AGO}"' in memory


def test_without_a_year_back_the_same_date_in_the_nearest_year_worth_showing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No day a year back: the same date in the nearest earlier year with a signed reflection, a starred
    photo or a trip. Two years back was a day at home, so three years back is the memory."""
    lb = persona_record(tmp_path, monkeypatch)
    lb.append_many([*_home_day("2024-06-21"), *_worth_day("2023-06-21")])
    cli.main(["derive", "keepers"])  # the favourite photo starred
    memory = _section(_today(serve.Site(lb, now=lambda: _at("2026-06-21", "07:00"))), "memory")
    assert "Three years ago today" in _text(memory)
    assert len(re.findall(r'href="/day/', memory)) == 1 and 'href="/day/2023-06-21"' in memory
    assert "Sailed to Drøbak with Kari." in _text(memory) and "The wind turned" not in _text(memory)
    assert "Kari Nordmann" in _text(memory)


def test_a_night_away_a_year_ago_is_the_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    lb.append_many(dwell("2025-06-21", "00:00", "24:00", ZURICH, every_min=10))  # a trip: the night in Zürich
    memory = _section(_today(serve.Site(lb, now=lambda: _at("2026-06-21", "07:00"))), "memory")
    assert "A year ago today" in _text(memory) and 'href="/day/2025-06-21"' in memory
    assert "away" in _text(memory) and "Zurich" in _text(memory)


def test_no_day_back_worth_showing_is_no_card(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """None: no card (RFC 0047 §14.2, the owner's answer): no year back at all, or only earlier years
    with nothing worth showing, and Today has no memory, not even a sentence."""
    lb = persona_record(tmp_path, monkeypatch)
    site = serve.Site(lb, now=lambda: _at("2026-06-21", "07:00"))
    assert 'class="memory"' not in _today(site), "no day back at all"
    lb.append_many(_home_day("2024-06-21"))
    page = _today(serve.Site(lb, now=lambda: _at("2026-06-21", "07:00")))
    assert 'class="memory"' not in page and "years ago" not in page, "two years back, a day at home"
    assert '<section class="close">' in page


def test_reflect_and_sign_at_the_foot_the_day_s_own_forms(lb: Logbook) -> None:
    page = _today(_site(lb))
    main = _main(page)
    close = main[main.index('<section class="close">') :]
    assert f'<form class="reflect" method="post" action="/day/{TODAY}/reflect">' in close
    assert "<textarea" in close and close.count("<section") == 1, "the last part"


def test_an_empty_record_is_kind_sentences_and_no_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "empty"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    lb = Logbook.init(root, "Europe/Oslo")
    page = _today(serve.Site(lb, now=lambda: _at(TODAY, "07:00")))
    said = _text(_section(page, "open")).strip()
    assert said and "no rows" not in said and said.endswith("."), said
    assert 'class="memory"' not in page, "no day back: no card"


# -- served, kept, built and exported --------------------------------------------------------------------


def test_today_keeps_its_tag_through_the_day_and_moves_with_it(lb: Logbook) -> None:
    clock = [_at(TODAY, "07:00")]
    site = serve.Site(lb, now=lambda: clock[0])
    morning = site.respond("/")
    clock[0] = _at(TODAY, "12:00")
    noon = site.respond("/")
    assert morning.etag is not None and morning.etag == noon.etag and morning.body == noon.body
    assert site.respond("/", "", if_none_match=morning.etag).status == 304
    clock[0] = _at("2026-06-20", "07:00")
    tomorrow = site.respond("/")
    assert tomorrow.etag != morning.etag and "Saturday 20 June" in tomorrow.body.decode("utf-8")


def test_live_what_reads_beyond_the_day_is_read_beside_the_page_and_said_until_it_is_here(
    lb: Logbook,
) -> None:
    site = _site(
        lb, read_later=True
    )  # `logbook serve`: never a reading of the record while the browser waits
    first = site.respond("/")
    said = _text(_section(first.body.decode("utf-8"), "open"))
    assert "Still reading the replies owed and the plan" in said, said
    assert NOTE_HOME in said, (
        "the fortnight's promises: one day's span, read on the request as the Day reads it"
    )
    assert len(re.findall(r"\. ", said.strip())) == 0, "one sentence"
    site.settle()
    second = site.respond("/", "", if_none_match=first.etag)
    assert second.status == 200 and second.etag != first.etag, "the tag names what has arrived"
    said = _text(_section(second.body.decode("utf-8"), "open"))
    assert NOTE_HOME in said and TASK in said and "Still reading" not in said


def test_the_shelves_listed_move_to_their_own_address_and_the_old_pages_wear_the_look(lb: Logbook) -> None:
    site = _site(lb)
    shelves = site.respond("/shelves")
    assert shelves.status == 200 and shelves.etag is not None
    text = shelves.body.decode("utf-8")
    assert "The last fortnight" in text and '<a class="gear" href="/gear"' in text
    days = site.respond("/days").body.decode("utf-8")
    # Life is its own door now (`door_life`): the Days page carries the header, Life a link to its door
    assert '<header class="doors">' in days and '<a href="/life">Life</a>' in days
    life = site.respond("/life").body.decode("utf-8")
    assert '<a href="/life" aria-current="page">Life</a>' in life
    assert doors.library_style() in days, "every other page in the doors' look, under the header"
    assert f'href="/day/{TODAY}"' in _today(site), "the Day /today names, one tap from Today"
    assert doors.GEAR == "/gear", "the gear's icon opens the gear (`door_gear`)"
    assert 'href="/shelves"' in site.respond("/gear").body.decode("utf-8"), "and the gear the shelves"


def test_the_record_button_is_today_s_script_when_the_server_hears(lb: Logbook) -> None:
    site = _site(lb, voice=serve.Voice(lambda path: None))  # type: ignore[arg-type, return-value]
    response = site.respond("/")
    text = response.body.decode("utf-8")
    assert text.count("<script>") == 1 and f"script-src '{serve.DAY_SCRIPT_HASH}'" in response.csp


def test_a_built_today_is_served_only_on_its_own_day(lb: Logbook) -> None:
    clock = [_at(TODAY, "07:00")]
    site = serve.Site(lb, now=lambda: clock[0])
    library = library_build.Library(lb, now=lambda: clock[0])
    library.put("/", site.respond("/"), str(lb.meta["head"]))
    served = serve.Site(lb, now=lambda: clock[0], library=library)
    built = served.respond("/").body
    assert built == library_build.stamped(site.respond("/").body, "07:00"), "the build's, on its day"
    clock[0] = _at("2026-06-20", "07:00")
    assert "Saturday 20 June" in served.respond("/").body.decode("utf-8"), "yesterday's build is not today"


def test_a_static_today_has_no_form_no_ask_and_no_font(lb: Logbook) -> None:
    site = _site(lb, href=lambda path: {"/": "index.html", "/days": "days.html"}.get(path))
    text = door_today.page_today(site)
    assert "<form" not in text and "@font-face" not in text and "url(" not in text
    assert 'href="index.html"' in text and "<span>People</span>" in text, "a door with no file is its name"
    assert "gear" not in _main(text) and 'class="gear"' not in text


# -- the doors' header on every page, the one policy, the fortnight (the follow-up to #404) ----------------

OLD_PROMISE = "I'll repaint the dinghy's name by Friday."  # said 18 days before Today: past the fortnight


def _crawl(site: serve.Site, seeds: list[str], most: int = 60) -> list[tuple[str, serve.Response]]:
    seen: list[tuple[str, serve.Response]] = []
    queue, done = list(seeds), set()
    while queue and len(seen) < most:
        target = queue.pop(0)
        if target in done:
            continue
        done.add(target)
        path, _, query = target.partition("?")
        response = site.respond(path, query)
        seen.append((target, response))
        if response.content_type.startswith("text/html"):
            for found in re.findall(r'href="(/[^"#]*)', response.body.decode("utf-8")):
                link = html.unescape(found)
                if not link.startswith(("/photo/", "/font/")):
                    queue.append(link)
    return seen


def test_every_page_carries_the_doors_header_and_marks_its_door(lb: Logbook) -> None:
    site = _site(lb)
    pages = [(t, r) for t, r in _crawl(site, ["/", "/shelves", "/days", "/people", "/places", "/world"])]
    html_pages = [(t, r.body.decode("utf-8")) for t, r in pages if r.content_type.startswith("text/html")]
    assert len(html_pages) >= 40
    for target, page in html_pages:
        assert page.count('<header class="doors">') == 1 and page.count("<nav") == 1, target
        assert '<a href="/today">today</a>' not in page, (target, "the old navigation is gone")
        door = doors.door_of(target.partition("?")[0])
        marked = re.findall(r'<a href="([^"]+)" aria-current="page">', page)
        assert marked == [t for n, t in doors.DOORS if n == door], (target, marked)
        root = ":root{color-scheme:light dark;--paper"
        # a door's own page (Today, Life) and the gear's own pages: the doors' frame
        own = target.partition("?")[0] in ("/", "/life", *door_gear.FRAMED)
        if own or '<main class="door">' in page:  # and any page in it (Places): the doors' one stylesheet
            assert doors.style() in page and doors.PAGES not in page, target
            assert page.count(root) == 1, (target, "the tokens defined once, on :root")
        elif door == doors.PEOPLE:  # the People door and each thread: the doors' frame, its tokens on :root
            assert doors.style() in page and root in page and doors.PAGES not in page, target
        else:  # a page that is not a door's: the doors' sheet and the pages' rules after it
            sheet = doors.header_style() if target.startswith("/world") else doors.library_style()
            assert page.count(sheet) == 1, target
            assert page.count(root) == 1, (target, "the tokens on :root, once: the doors'")
    assert doors.door_of("/people/019cadd3") == doors.PEOPLE and doors.door_of("/day/2026-06-19") is None
    shelves = site.respond("/shelves").body.decode("utf-8")
    assert (
        '<a class="gear" href="/gear"' in shelves and 'aria-label="The gear" aria-current="page"' in shelves
    ), "the shelves listed, a link from the gear, are the gear's"
    gear = site.respond("/gear").body.decode("utf-8")
    assert (
        'aria-label="The gear" aria-current="page"' in gear
        and "aria-current" not in gear[gear.index('<nav class="doors"') : gear.index("</nav>")]
    )
    days = site.respond("/days").body.decode("utf-8")
    assert 'aria-label="The gear" aria-current' not in days, "the gear is marked on its own page alone"


# what makes an element clip its descendants, or hold a `position:fixed` one to itself instead of the screen
TRAPS = ("clip-path", "overflow", "contain", "transform", "filter", "perspective", "will-change")


def test_the_header_never_clips_the_phone_s_door_bar() -> None:
    """On a phone the doors are a bar fixed at the foot of the screen, inside the header; a rule on the
    header that clips it (a `clip-path` drawing the band) or holds it to the header hides the bar."""
    sheets = (doors.header_style(), doors.header_style(fonts=False), doors.style(), doors.library_style())
    for sheet in sheets:
        for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", sheet):
            if "header.doors" in [s.strip() for s in selectors.split(",")]:
                properties = [d.split(":")[0].strip() for d in body.split(";") if ":" in d]
                assert not [p for p in properties if p.startswith(TRAPS)], (selectors, body)
        phone = sheet[sheet.index("@media (max-width:40rem)") :]
        assert re.search(r"nav\.doors\{position:fixed;[^}]*bottom:0", phone), "the bar at the foot"


def test_doors_page_is_as_404_made_it(lb: Logbook) -> None:
    """The frame the Life, People and Places sessions render through: `doors.page` and its stylesheet."""
    page = _today(_site(lb))
    assert doors.style() in page and page.count("<header") == 1
    assert (
        doors.FRAME.startswith(doors.ROOT)
        and doors.HEADER in doors.FRAME
        and doors.PHONE_HEADER in doors.FRAME
    )
    assert doors.header_style().startswith(doors.style()[: doors.style().index(":root")]), "the same faces"


def test_one_policy_with_fonts_from_the_server_and_the_font_address_kept(lb: Logbook) -> None:
    before = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'"
    fonts = before.replace("form-action", "font-src 'self'; form-action")
    assert f"{fonts}; frame-ancestors 'none'" == serve.CSP, "the two changes: the fonts, and no frame"
    for policy in (serve.CSP, serve.DAY_CSP, serve.DAY_IMAGES, serve.PLACES_CSP, serve.WORLD_CSP, doors.CSP):
        assert policy.count("font-src 'self'") == 1, policy
    site = _site(lb)
    for name in doors.FACES:
        found = site.respond(f"/font/{name}")
        assert found.status == 200 and found.content_type == doors.FONT_TYPE, name
    assert site.respond("/days").csp == serve.CSP
    assert site.respond("/font/nothing.woff2").status == 404


def test_what_is_open_reads_the_fortnight_and_never_a_promise_years_old(lb: Logbook) -> None:
    lb.append_many([note(utc("2026-06-01", "09:00"), OLD_PROMISE)])
    lb = Logbook(lb.root)
    site = _site(lb)
    said = _text(_section(_today(site), "open"))
    assert html.unescape(OLD_PROMISE) not in said, "past the fortnight: on the shelf, not on Today"
    assert NOTE_HOME in said, "said in the fortnight: on Today"
    shelf = site.respond("/promises").body.decode("utf-8")
    assert html.escape(OLD_PROMISE, quote=False) in shelf or OLD_PROMISE in html.unescape(shelf)
    near = day_rhythm.promises_near(lb, TODAY, None)
    assert {p.match.quote for p in door_today.open_promises(near)} <= {p.match.quote for p in near}
