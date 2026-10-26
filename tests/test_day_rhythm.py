"""The Day page for v1 (`logbook.contrib.day_rhythm`): one page with four shapes that follow the hour —
morning, live, evening, signed — computed on every request and never stored; `?shape=` shows another
shape of the same day for reading only. The parts are read from readers already in the record: what
the day was for (the chapter and the goals it touched), yesterday, the ribbon of the planned and the
lived, today's plan and what is due, the loose ends both ways, who showed up, one person, looking
back 1, 2, 3, 5 and 10 years, the parts that hold nothing named once, and the pencil. On the Oslo
persona's fortnight, Kari and Ola Nordmann and Per Hansen, who do not exist; every address is at
example.org, every number in 07700 900xxx; no test opens a connection."""

from __future__ import annotations

import html
import json
import re
import shutil
import threading
from collections.abc import Iterable
from datetime import UTC, date, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import phone_width
import pytest
from dream_fortnight import (
    DECISION,
    ENV,
    GOAL_SAIL,
    MODEL,
    OLA_PROMISE,
    PROMISE_ZURICH,
    W25,
    fake,
    fortnight,
    message,
    run_cli,
)
from ideas_record import notion
from library_header import without_shell
from persona import CAFE, HOME, KARI, KARI_ID, OLA, ZURICH, attendee, dwell, event, flight, note, photo, utc

from logbook import cli
from logbook.contrib import day_rhythm, demo, notify, people_drift, serve
from logbook.core import day as day_reader
from logbook.core import drafts, people
from logbook.core.store import Logbook

TZ = ZoneInfo("Europe/Oslo")
RSQUO = "\u2019"
DASH = "\u2013"
TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY = (f"2026-06-{d}" for d in (16, 17, 18, 19, 20, 21))
MONDAY = "2026-06-15"  # to Zürich: XY 561 out at 07:05
BEFORE = "2026-06-07"  # the Sunday before the fortnight: no location line, so nothing lived beside an entry
PER_ID = "019cadd3-6bc0-7dcd-9133-000000000003"
PER = {"email": "per.hansen@example.org", "phone": "+447700900123"}
CHAPTER_NAME, CHAPTER_RULES = "Summer on the water", "Sail before screens"
REVIEW_NOTE = "Booked the berth."
BACK = {1: "2025-06-17", 2: "2024-06-17", 10: "2016-06-17"}  # the years back the record has
THEN_WORDS = "Sailed to Drøbak with Kari. The wind turned at four."
PLANNED_ALONE = "Call the marina"  # planned on a day no device tracked: nothing lived beside it
ALL_DAY = "Midsummer week"


def _resolution(ref: tuple[str, str], entity: str, label: str, birthday: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "resolution/v1",
        "ref": {"kind": ref[0], "value": ref[1]},
        "entity": {"type": "person", "id": entity, "registry": "logbook"},
        "label": label,
        "method": "owner",
    }
    if birthday:
        payload["extra"] = {"birthday": birthday}
    return {
        "at": "2026-06-01T08:00:00Z",
        "source": "manual",
        "kind": "resolution",
        "tier": 2,
        "payload": payload,
    }


def _reflection(at: str, text: str) -> dict[str, Any]:
    line = note(at, text)
    line["payload"]["labels"] = ["reflection"]
    return line


def _back_day(day: str) -> list[dict[str, Any]]:
    """A day years ago: a night at home, lunch with Kari at the cafe, a favourite photo, a reflection."""
    return [
        *dwell(day, "00:00", "11:00", HOME, every_min=10),
        *dwell(day, "11:30", "14:00", CAFE, every_min=10),
        *dwell(day, "14:30", "24:00", HOME, every_min=10),
        event(utc(day, "12:00"), utc(day, "13:00"), "Lunch", [attendee(KARI["email"])]),
        photo(utc(day, "12:30"), CAFE, favorite=True),
        _reflection(utc(day, "22:00"), THEN_WORDS),
    ]


@pytest.fixture(scope="module")
def pristine(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The fortnight; Per Hansen with a birthday; an entry nothing lived beside and an all-day one; a
    chapter and a review of the sailing goal on Wednesday; three days years back."""
    with pytest.MonkeyPatch.context() as mp:
        root = tmp_path_factory.mktemp("day-rhythm") / "lb"
        mp.setenv("LOGBOOK_HOME", str(root))
        lb = fortnight(root)
        goal = next(
            line for line in lb.lines() if line["kind"] == "goal" and line["payload"]["text"] == GOAL_SAIL
        )
        extra = [
            _resolution(("email", PER["email"]), PER_ID, "Per Hansen", birthday="1986-06-23"),
            event(utc(BEFORE, "10:00"), utc(BEFORE, "10:30"), PLANNED_ALONE),
            event(utc(FRIDAY, "00:00"), utc(SATURDAY, "00:00"), ALL_DAY, all_day=True),
            {
                "at": utc("2026-06-01", "09:00"),
                "source": "manual",
                "kind": "chapter",
                "tier": 2,
                "payload": {
                    "schema": "chapter/v1",
                    "name": CHAPTER_NAME,
                    "from": "2026-06-01",
                    "rules": CHAPTER_RULES,
                },
            },
            {
                "at": utc(WEDNESDAY, "21:30"),
                "source": "manual",
                "kind": "review",
                "tier": 2,
                "payload": {
                    "schema": "review/v1",
                    "goal": str(goal["id"]),
                    "disposition": "advancing",
                    "period": "week",
                    "note": REVIEW_NOTE,
                },
            },
        ]
        for day in BACK.values():
            extra += _back_day(day)
        lb.append_many(extra)
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


def _site(lb: Logbook, day: str = "2026-06-22", clock: str = "12:00", **kw: Any) -> serve.Site:
    return serve.Site(lb, now=lambda: _at(day, clock), **kw)


def _page(site: serve.Site, day: str, query: str = "") -> str:
    response = site.respond(f"/day/{day}", query)
    assert response.status == 200, response.body[:300]
    return response.body.decode("utf-8")


def _parts(page: str) -> list[str]:
    return re.findall(r'<section class="part ([a-z-]+)"', page)


def _part(page: str, name: str) -> str:
    start = page.index(f'<section class="part {name}"')
    return page[start : page.index("</section><!--part-->", start)]


def _eyebrow(page: str) -> str:
    found = re.search(r'<p class="eyebrow">(.*?)</p>', page)
    assert found is not None
    return found.group(1)


def _sign(day: str, at: str) -> None:
    assert not cli.main(["day", "sign", day, "--at", at])


# -- the shape -------------------------------------------------------------------------------------------


def _shape(
    day: str, now: str, *, signed: bool = False, stay: str | None = None, evening: int | None = None
) -> str:
    """The rule alone: `day` seen at local `now` on 20 June, the first stay of note after the night
    beginning at local `stay` when given."""
    local = datetime.fromisoformat(f"2026-06-20T{now}:00").replace(tzinfo=TZ)
    first = None if stay is None else datetime.fromisoformat(f"2026-06-20T{stay}:00").replace(tzinfo=TZ)
    return day_rhythm.shape_of(
        date.fromisoformat(day), local, signed=signed, first_stay=first, evening=evening
    )


def test_the_shape_follows_the_hour_at_its_edges() -> None:
    assert _shape(SATURDAY, "10:59") == "morning"
    assert _shape(SATURDAY, "11:00") == "live"
    assert _shape(SATURDAY, "08:30", stay="08:10") == "live", "the first stay of note after the night"
    assert _shape(SATURDAY, "08:00", stay="08:10") == "morning"
    assert _shape(SATURDAY, "19:59", evening=20) == "live"
    assert _shape(SATURDAY, "20:00", evening=20) == "evening"
    assert _shape(SATURDAY, "23:30") == "live", "no evening hour set: the day stays live until it is past"
    assert _shape(FRIDAY, "09:00") == "evening", "a past day not signed"
    assert _shape(FRIDAY, "09:00", signed=True) == "signed"
    assert _shape(SATURDAY, "09:00", signed=True) == "signed"


def test_the_page_takes_its_shape_from_the_clock_and_the_evening_hour(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(notify.EVENING_ENV, "20")
    assert _eyebrow(_page(_site(lb, SATURDAY, "10:59"), SATURDAY)) == "Saturday · morning · 10:59"
    assert _eyebrow(_page(_site(lb, SATURDAY, "11:00"), SATURDAY)) == "Saturday · live · 11:00"
    assert _eyebrow(_page(_site(lb, SATURDAY, "19:59"), SATURDAY)) == "Saturday · live · 19:59"
    assert _eyebrow(_page(_site(lb, SATURDAY, "20:00"), SATURDAY)) == "Saturday · evening · 20:00"
    assert _eyebrow(_page(_site(lb, SATURDAY, "08:30"), FRIDAY)) == "Friday · evening"
    assert _eyebrow(_page(_site(lb, FRIDAY, "07:50"), FRIDAY)).startswith("Friday · morning")
    assert _eyebrow(_page(_site(lb, FRIDAY, "08:30"), FRIDAY)).startswith("Friday · live"), "at the office"
    _sign(FRIDAY, "2026-06-19T21:52:00+02:00")
    assert _eyebrow(_page(_site(lb, SATURDAY, "09:00"), FRIDAY)) == "Friday · signed 21:52"


def test_the_clock_is_in_the_tag_of_today_and_not_of_a_past_day(lb: Logbook) -> None:
    clock = ["10:59"]
    site = serve.Site(lb, now=lambda: _at(SATURDAY, clock[0]))

    def tag(path: str) -> str | None:
        return site.etag(path, "", site.current())

    today, past = tag(f"/day/{SATURDAY}"), tag(f"/day/{FRIDAY}")
    clock[0] = "11:00"
    assert tag(f"/day/{SATURDAY}") != today, "the shape and the now line move with the clock"
    assert tag(f"/day/{FRIDAY}") == past, "a past day's shape is the head's"


def test_each_shape_draws_its_parts_in_its_order(lb: Logbook) -> None:
    site = _site(lb, SATURDAY, "09:00")
    morning = _parts(_page(site, SATURDAY))
    assert morning == [
        "header",
        "for",
        "yesterday",
        "today",
        "one-person",
        "record",
        "nothing-from",
        "add",
        "foot",
    ]
    live = _parts(_page(_site(lb, SATURDAY, "15:00"), SATURDAY))
    assert live == ["header", "for", "so-far", "add", "record", "nothing-from", "quiet", "foot"]
    assert _parts(_page(_site(lb, TUESDAY, "21:30"), TUESDAY))[:5] == [
        "header",
        "for",
        "so-far",
        "photos",
        "add",
    ]
    evening = _parts(_page(site, WEDNESDAY))
    assert evening == [
        "header",
        "for",
        "tiers",
        "the-day",
        "record",
        "photos",
        "nothing-from",
        "close",
        "foot",
    ]
    _sign(TUESDAY, "2026-06-16T23:00:00+02:00")
    signed = _parts(_page(site, TUESDAY))
    assert signed == ["header", "photos", "the-day", "record", "nothing-from", "close", "foot"]


def test_a_shape_asked_for_is_shown_for_reading_and_an_unknown_one_falls_back(lb: Logbook) -> None:
    site = _site(lb, SATURDAY, "09:00")
    computed = _page(site, SATURDAY)
    for shape in day_rhythm.SHAPES:
        page = _page(site, SATURDAY, f"shape={shape}")
        assert _eyebrow(page).split(" · ")[1].startswith(shape)
        assert "shown for reading" in page or shape == "morning"
    unknown = _page(site, SATURDAY, "shape=noon")
    assert _eyebrow(unknown) == _eyebrow(computed) == "Saturday · morning · 09:00"
    assert _parts(unknown) == _parts(computed) and "shown for reading" not in unknown
    forms = re.findall(r'<form [^>]*action="([^"]+)"', without_shell(_page(site, SATURDAY, "shape=evening")))
    assert forms and all(
        f in ("/with", "/star", f"/day/{SATURDAY}/reflect", f"/day/{SATURDAY}/sign") for f in forms
    )


# -- the parts --------------------------------------------------------------------------------------------


def test_for_names_the_chapter_and_its_rule_and_the_goals_the_day_touched(lb: Logbook) -> None:
    site = _site(lb, SATURDAY, "09:00")
    said = _part(_page(site, WEDNESDAY), "for")
    assert CHAPTER_NAME in said and f"“{CHAPTER_RULES}”" in said
    assert GOAL_SAIL in said and 'href="/goals/' in said, "the goal its review on the day touched, linked"
    assert "Read one book a month" not in said, "a goal the day did not touch"
    elsewhere = _part(_page(site, THURSDAY), "for")
    assert CHAPTER_NAME in elsewhere and GOAL_SAIL not in elsewhere


def test_for_says_plainly_when_no_goal_or_chapter_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "bare"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    lb = Logbook.init(root, "Europe/Oslo")
    lb.append_many(dwell(FRIDAY, "08:00", "18:00", HOME, every_min=30))
    said = _part(_page(_site(lb, SATURDAY, "09:00"), FRIDAY), "for")
    assert day_rhythm.NO_FOR in said and 'href="/goals"' in said


def test_the_ribbon_draws_the_planned_beside_the_lived(lb: Logbook) -> None:
    site = _site(lb, SATURDAY, "09:00")
    monday = _part(_page(site, MONDAY), "the-day")
    ribbon = _ribbon(monday)
    assert ">00</text>" in ribbon and ">24</text>" in ribbon and ">12</text>" in ribbon, (
        "midnight to midnight"
    )
    assert "PLANNED" in ribbon and "LIVED" in ribbon
    assert 'class="move"' in ribbon and 'class="stay"' in ribbon
    assert "Lived: " in _label(ribbon) and "stay" in _label(ribbon)
    legend = re.search(r'<p class="legend">(.*?)</p>', monday)
    assert legend is not None
    assert (
        re.sub(r"<[^>]+>", "", legend.group(1))
        == "stay · move · aboard · call · dashed: planned, nothing beside it"
    )
    alone = _ribbon(_part(_page(site, BEFORE), "the-day"))
    assert re.search(r'<rect class="plan hollow"[^>]*>\s*<title>[^<]* — ' + PLANNED_ALONE, alone), (
        "nothing lived beside it"
    )
    assert PLANNED_ALONE in _label(alone) and "no location lines for the day" in alone
    tuesday = _ribbon(_part(_page(site, TUESDAY), "the-day"))
    assert re.search(r'<rect class="plan filled"[^>]*>\s*<title>[^<]* — Dinner', tuesday), (
        "a dinner at the hotel"
    )
    friday = _ribbon(_part(_page(site, FRIDAY), "the-day"))
    assert ALL_DAY not in friday, "an all-day entry is not drawn"
    thursday = _ribbon(_part(_page(site, THURSDAY), "the-day"))
    assert "nothing planned in the calendar" in thursday and "nothing planned" not in tuesday
    assert "nothing planned in the calendar" in _label(thursday)


def _ribbon(part: str) -> str:
    svg = re.search(r'<svg class="ribbon".*?</svg>', part, re.S)
    assert svg is not None, part
    return svg.group(0)


def _label(ribbon: str) -> str:
    found = re.search(r'aria-label="([^"]*)"', ribbon)
    assert found is not None
    return found.group(1)


def test_the_ribbon_draws_now_on_today_only(lb: Logbook) -> None:
    site = _site(lb, SATURDAY, "15:00")
    assert 'class="now"' in _page(site, SATURDAY)
    assert 'class="now"' not in _page(site, FRIDAY)


def test_the_ribbon_says_why_a_day_has_no_stay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "quiet"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    lb = Logbook.init(root, "Europe/Oslo")
    lb.append(**note(utc(FRIDAY, "12:00"), "A day indoors."))
    ribbon = _part(_page(_site(lb, SATURDAY, "09:00"), FRIDAY), "the-day")
    assert "no location lines for the day" in ribbon


def test_morning_lists_today_s_plan_then_what_is_due(lb: Logbook) -> None:
    today = _part(_page(_site(lb, THURSDAY, "07:00"), THURSDAY), "today")
    assert '<svg class="ribbon"' in today
    rows = re.findall(r'<li class="(plan|due)">', today)
    assert "due" in rows, today
    assert "you were promised on Wednesday" in today and "Ola Nordmann" in today
    assert "the photos of the berth" in today


def test_loose_ends_reads_both_ways_and_holds_no_form(lb: Logbook) -> None:
    page = _page(_site(lb, SATURDAY, "09:00"), WEDNESDAY, "open=1")
    loose = _fold(page, "Loose ends")
    assert "1 promise made" in loose and "1 owed to you" in loose and "1 decision" in loose
    assert "the berth contract" in loose and "the photos of the berth" in loose
    assert DECISION in loose and "pencil" in loose
    assert "<form" not in loose and "<button" not in loose
    thursday = _fold(_page(_site(lb, SATURDAY, "09:00"), THURSDAY, "open=1"), "Loose ends")
    assert "due" in thursday and "the photos of the berth" in thursday, "due on the day it was owed"


def _fold(page: str, title: str) -> str:
    start = page.index(f"<summary><h2>{title}</h2>")
    start = page.rindex("<details", 0, start)
    return page[start : page.index("</details><!--fold-->", start)]


def test_people_in_order_of_time_together(lb: Logbook) -> None:
    page = _page(_site(lb, SATURDAY, "09:00"), TUESDAY, "open=1")
    assert "Ola Nordmann" in _fold(page, "People")


# -- the guard: never a number beside a person's name (RFC 0043 principle 5; the timeline's, #361) ----------

BESIDE = "[\\s(:×x#·,]*"  # what may stand between a name and a number and still be beside it
BREAK = "\u00b6"  # a block's end (a paragraph, a row, a cell, a summary): not a space, never crossed
BLOCK = re.compile(
    r"</?(?:p|li|ol|ul|dl|dt|dd|div|section|main|header|footer|nav|h[1-6]|table|tr|td|th|details|summary"
    r"|blockquote|form|svg|br|title)\b[^>]*>",  # an SVG <title> is a tooltip: a text of its own
    re.I,
)


# the attributes that carry words a reader is shown or read aloud: each is seen as a block of its own
WORDS = re.compile(
    r"""\s(?:title|aria-label|aria-description|aria-roledescription|alt|placeholder|label|summary|content"""
    r"""|value)\s*=\s*(?:"([^"]*)"|'([^']*)')""",
    re.I,
)


def _seen(page: str) -> str:
    """A page as text: its style and script dropped, every block's end a break, the words of every
    attribute that carries them (`WORDS`) a block of their own, every other tag gone."""
    page = re.sub(r"<(style|script)\b.*?</\1>", "", page, flags=re.S | re.I)

    def tag(found: re.Match[str]) -> str:
        said = [a or b for a, b in WORDS.findall(found.group(0))]
        return "".join(f"{BREAK}{words}{BREAK}" for words in said if words) + (
            BREAK if BLOCK.fullmatch(found.group(0)) else ""
        )

    return html.unescape(re.sub(r"<[^>]+>", tag, page))


def beside(text: str, names: Iterable[str]) -> list[str]:
    """Every place in `text` where a digit stands beside one of `names`: `(\\d[\\s(:×x#·,]*NAME)`
    or `(NAME\\??[\\s(:×x#·,]*\\d)`, never across a block's end."""
    found = []
    for name in names:
        n = re.escape(name)
        found += [m.group(0) for m in re.finditer(rf"(\d{BESIDE}{n})|({n}\??{BESIDE}\d)", text)]
    return found


def test_the_guard_finds_a_number_beside_a_name_and_nothing_else() -> None:
    names = ["Per Hansen"]
    for said in (
        "Per Hansen · 5",
        "Per Hansen (3)",
        "Per Hansen: 2",
        "Per Hansen ×4",
        "Per Hansen, 12",
        "3 · Per Hansen",
    ):
        assert beside(said, names), said
    assert beside(f"Per Hansen{RSQUO}s birthday is on Tuesday.", names) == []
    assert beside(_seen("<li>12:00</li><li>Per Hansen</li>"), names) == [], "a block's end is not crossed"
    assert beside(_seen("<li>12:00 Per Hansen</li>"), names), "within a block it is"
    # the twenty-seventh sitting's finding: a ribbon block's words, in its `<title>` and its `aria-label`
    assert beside(_seen('<svg aria-label="Planned: Dinner with Per Hansen 19:30."></svg>'), names)
    assert beside(_seen("<rect><title>Dinner with Per Hansen 19:30</title></rect>"), names)
    assert beside(_seen('<a title="Per Hansen (3)" href="/x">x</a>'), names), (
        "any attribute that carries words"
    )
    assert beside(_seen('<img alt="Per Hansen, 12">'), names)
    assert beside(_seen('<svg aria-label="19:30 — Dinner with Per Hansen."></svg>'), names) == []
    # the review's: an entry titled by a name alone; `·` is a mark a number stands beside a name across
    assert beside(_seen("<rect><title>19:30" + DASH + "21:30 · Per Hansen</title></rect>"), names)
    assert beside(_seen("<li><span>16:30</span><span>Per Hansen</span></li>"), names), "a span is no block"
    assert beside(_seen("<rect><title>19:30" + DASH + "21:30 — Per Hansen</title></rect>"), names) == []
    assert beside(_seen('<li><div class="t">16:30</div><span>Per Hansen</span></li>'), names) == []
    assert beside(_seen("<title>Per Hansen</title><title>08:30</title>"), names) == [], "two tooltips"
    assert beside(_seen('<p title="12:00">Per Hansen</p>'), names) == [], "an attribute is its own block"


def test_no_page_puts_a_number_beside_a_name_in_any_shape(lb: Logbook) -> None:
    names = sorted({p.name for p in people.directory(lb).known.values()})
    assert "Per Hansen" in names and "Kari Nordmann" in names
    site = _site(lb, SATURDAY, "09:00")
    for day in (TUESDAY, WEDNESDAY, SATURDAY, BACK[1], BACK[10]):
        for shape in day_rhythm.SHAPES:
            for query in (f"shape={shape}", f"shape={shape}&open=1"):
                found = beside(_seen(_page(site, day, query)), names)
                assert found == [], (day, query, found)


def test_birthdays_this_week_in_people_and_one_person(lb: Logbook) -> None:
    morning = _page(_site(lb, SATURDAY, "09:00"), SATURDAY, "open=1")
    card = _text(_part(morning, "one-person"))
    assert card.strip().endswith(f"Per Hansen{RSQUO}s birthday is on Tuesday."), card
    assert "Per Hansen" in _fold(morning, "People")
    far = _page(_site(lb, "2026-06-10", "09:00"), "2026-06-10")
    assert "one-person" not in _parts(far), "nothing in the coming week: no card"


def test_looking_back_reads_the_years_the_record_has(lb: Logbook) -> None:
    page = _page(_site(lb, SATURDAY, "09:00"), WEDNESDAY, "open=1")
    back = _fold(page, "Looking back")
    years = re.findall(r'<li class="back"[^>]*><a href="/day/(\d{4}-\d{2}-\d{2})"', back)
    assert years == [BACK[1], BACK[2], BACK[10]]
    assert "1 year ago" in back and "2 years ago" in back and "10 years ago" in back
    assert "“Sailed to Drøbak with Kari.”" in back and "The wind turned" not in back
    assert "Kari Nordmann" in back and "1 starred photo" in back
    assert "3 years ago" not in back and "5 years ago" not in back


def test_an_empty_part_is_named_once_and_never_drawn_as_an_empty_fold(lb: Logbook) -> None:
    page = _page(_site(lb, SATURDAY, "09:00"), THURSDAY)
    said = re.findall(r'<p class="nothing">Nothing from: (.*?)</p>', page)
    assert len(said) == 1, said
    named = said[0].split(" · ")
    assert "the circle" in named and "looking back" in named
    for title in ("Looking back", "From"):
        assert f"<summary><h2>{title}" not in page


def test_the_pencil_is_the_draft_restyled(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: list[str]
) -> None:
    """The dream's draft, as main shows it, on ruled paper: its segments and their evidence marks; the
    evening's page has it above the record, the signed day's folded at its foot with what was kept."""
    lb.append_many([photo(utc(WEDNESDAY, f"{h}:00"), ZURICH) for h in range(12, 18)])  # the June pick
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    fake(monkeypatch)
    assert run_cli("dream", "day", WEDNESDAY)[0] == 0
    site = _site(lb, SATURDAY, "09:00")
    evening = _page(site, WEDNESDAY)
    pencil = _part(evening, "pencil")
    assert '<div class="paper"><p class="eyebrow">Pencil <span class="sc">' in pencil and MODEL in pencil
    assert "<h2>Draft</h2>" in pencil and "A day." in pencil and '<span class="id"' in pencil
    assert _parts(evening).index("pencil") < _parts(evening).index("record")
    assert "quiet" not in _parts(_page(site, WEDNESDAY, "shape=live"))
    _sign(WEDNESDAY, "2026-06-17T23:00:00+02:00")
    signed = _page(site, WEDNESDAY)
    assert _parts(signed).index("pencil") > _parts(signed).index("record")
    assert "<summary><h2>Pencil</h2>" in _part(signed, "pencil")
    assert no_network == []


def test_the_footer_says_what_is_computed_and_what_is_pencil(lb: Logbook) -> None:
    for day, clock, asked in (
        (SATURDAY, "09:00", SATURDAY),
        (SATURDAY, "15:00", SATURDAY),
        (SATURDAY, "09:00", FRIDAY),
    ):
        page = _page(_site(lb, day, clock), asked)
        assert day_rhythm.FOOTER in _part(page, "foot")
        assert serve.NO_MODEL in page.split("<footer>")[1]


def test_yesterday_says_signed_and_what_arrived_after(lb: Logbook) -> None:
    _sign(FRIDAY, "2026-06-19T22:00:00+02:00")
    lb.append(**photo(utc(FRIDAY, "21:00"), HOME))
    card = _part(_page(_site(lb, SATURDAY, "09:00"), SATURDAY), "yesterday")
    assert "Friday is signed" in card
    assert "1 photo arrived after you signed" in card and f'href="/day/{FRIDAY}#close"' in card
    assert "Thursday is still open" in card and f'href="/day/{THURSDAY}"' in card
    open_card = _part(_page(_site(lb, THURSDAY, "09:00"), THURSDAY), "yesterday")
    assert "Wednesday is open" in open_card


def test_the_live_shape_waits_for_the_evening_question(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(notify.EVENING_ENV, "21")
    quiet = _part(_page(_site(lb, SATURDAY, "15:00"), SATURDAY), "quiet")
    assert "No pencil yet. Your question comes at 21:00." in quiet and "#close" in quiet


# -- the rules of the Library -------------------------------------------------------------------------------


def test_nothing_above_the_gate_on_any_shape(lb: Logbook) -> None:
    gated = _site(lb, SATURDAY, "09:00", tiers=[1])
    for shape in day_rhythm.SHAPES:
        for day in (WEDNESDAY, SATURDAY):
            page = re.sub(r"<datalist.*?</datalist>", "", _page(gated, day, f"shape={shape}&open=1"))
            for words in (
                PROMISE_ZURICH,
                OLA_PROMISE,
                DECISION,
                CHAPTER_NAME,
                GOAL_SAIL,
                THEN_WORDS,
                REVIEW_NOTE,
            ):
                assert words not in page, (shape, day, words)
            assert "Per Hansen" not in page, "a birthday rests on a tier-2 resolution"
    two = _site(lb, SATURDAY, "09:00", tiers=[1, 2])
    evening = _page(two, WEDNESDAY, "open=1")
    assert "asleep" not in evening and "<summary><h2>Health" not in evening, "tier 3 stays out"


def test_the_page_loads_nothing_and_opens_nothing(lb: Logbook, no_network: list[str]) -> None:
    site = _site(lb, SATURDAY, "15:00")
    for day in (SATURDAY, WEDNESDAY):
        response = site.respond(f"/day/{day}", "open=1")
        page = response.body.decode("utf-8")
        assert response.csp in (serve.DAY_CSP, serve.DAY_IMAGES)
        own = without_shell(page)  # the header's faces are the server's own (`/font/`), and nothing else
        assert "url(" not in own and "@import" not in page and "<link" not in page
        assert page.count("<script") <= 1 and ("<script" not in page or serve.DAY_SCRIPT in page)
        assert phone_width.problems(page) == []
    assert no_network == []


def test_the_look_is_the_owner_s(lb: Logbook) -> None:
    page = _page(_site(lb, SATURDAY, "09:00"), WEDNESDAY)
    for token in (
        "--paper:#f4efe3",
        "--graphite:#47433c",
        "--stay:#2e7d4f",
        "--card:#1b1c1f",
        "--ink:#f3f0e9",
    ):
        assert token in page
    assert '"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif' in page


# -- the review's cases ----------------------------------------------------------------------------------


def test_yesterday_names_no_open_day_above_the_gate(lb: Logbook) -> None:
    secret = note(utc("2026-06-02", "09:00"), "A line above the gate.")
    secret["tier"] = 3
    lb.append(**secret)
    gated = _page(_site(lb, "2026-06-04", "09:00", tiers=[1, 2]), "2026-06-04")
    assert "2026-06-02" not in _part(gated, "yesterday")
    assert "/day/2026-06-02" in _part(_page(_site(lb, "2026-06-04", "09:00"), "2026-06-04"), "yesterday")


def test_for_on_a_day_no_goal_touched_says_so_and_not_that_none_is_set(lb: Logbook) -> None:
    said = _part(_page(_site(lb, SATURDAY, "09:00"), "2026-05-20"), "for")
    assert day_rhythm.NO_FOR not in said and day_rhythm.NO_FOR_DAY in said


def test_the_ribbon_s_hours_are_the_wall_clock_s_on_a_day_of_25_hours(lb: Logbook) -> None:
    """25 October 2026: Oslo's clocks go back at 03:00, so the day lasts 25 hours."""
    ribbon = _ribbon(_part(_page(_site(lb, "2026-10-26", "09:00"), "2026-10-25"), "the-day"))
    labels = dict(re.findall(r'<text x="([\d.]+)" y="78"[^>]*>(\d\d)</text>', ribbon)[::1])
    at = {label: float(x) for x, label in labels.items()}
    assert sorted(at) == ["00", "03", "06", "09", "12", "15", "18", "21", "24"]
    assert at["03"] == round(4 / 25 * 360, 1) and at["24"] == 360.0, "03:00 comes four hours in"


def test_people_go_by_time_together_and_each_once(lb: Logbook) -> None:
    lb.append(
        **event(utc(TUESDAY, "13:00"), utc(TUESDAY, "17:00"), "Harbour office", [attendee(KARI["email"])])
    )
    people = _fold(_page(_site(lb, SATURDAY, "09:00"), TUESDAY, "open=1"), "People")
    names = re.findall(r'class="person"[^>]*>([^<]+)<', people.split('class="birthdays"')[0])
    assert names == ["Kari Nordmann", "Ola Nordmann"], "four hours with Kari, two with Ola"


def test_looking_back_reads_only_the_years_the_record_has(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    read: list[tuple[str, str]] = []
    real = day_rhythm.reading.read

    def counted(lb_: Logbook, first: str, last: str, *a: Any, **kw: Any) -> Any:
        read.append((first, last))
        return real(lb_, first, last, *a, **kw)

    monkeypatch.setattr(day_rhythm.reading, "read", counted)
    found = day_rhythm.looking_back(lb, WEDNESDAY, serve.Airports.load(), None)
    assert [b["years"] for b in found] == [1, 2, 10]
    assert [last for _first, last in read] == [BACK[1], BACK[2], BACK[10]], (
        "a year with no line reads nothing"
    )


def _endless(day: str, number: str) -> dict[str, Any]:
    """A flight line with its departure and no arrival: the tracker lost it before it landed. It
    leaves at 10:00, before the move to the cafe at 11:00 ends."""
    line = flight(day, number, "OSL", "BGO", utc(day, "10:00"), utc(day, "11:00"))
    del line["end"], line["payload"]["actual_arrival"]
    return line


def _today_and_back(lb: Logbook) -> None:
    """/today on Wednesday goes to its Day page; the page and its looking back read every year."""
    site = _site(lb, WEDNESDAY, "09:00")
    today = site.respond("/today", "")
    assert today.status == 302 and today.headers["Location"] == f"/day/{WEDNESDAY}"
    _page(site, WEDNESDAY)
    back = _fold(_page(site, WEDNESDAY, "open=1"), "Looking back")
    years = re.findall(r'<li class="back"[^>]*><a href="/day/(\d{4}-\d{2}-\d{2})"', back)
    assert years == [BACK[1], BACK[2], BACK[10]]
    for then in BACK.values():
        _page(site, then)


def test_a_flight_with_no_end_years_back_ends_at_its_start(lb: Logbook) -> None:
    lb.append(**_endless(BACK[1], "565"))
    _today_and_back(lb)
    data = day_reader.read(lb, BACK[1], serve.Airports.load())
    (row,) = [entry for entry in data["timeline"] if entry["kind"] == day_reader.FLIGHT]
    assert row["end"] is None and row["end_local"] is None
    assert all(not entry.get("flights") for entry in data["timeline"]), "no move is covered by an instant"


def test_a_flight_whose_start_cannot_be_read_years_back_is_skipped(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb.append(**_endless(BACK[1], "565"))
    lb.append(**flight(BACK[2], "567", "OSL", "BGO", utc(BACK[2], "10:00"), utc(BACK[2], "11:00")))
    real = day_reader.flight_lines.standing

    def unread(lines: Iterable[Any]) -> dict[Any, Any]:
        return {
            k: {**line, "at": None} if line["payload"]["date"] == BACK[2] else line
            for k, line in real(lines).items()
        }

    monkeypatch.setattr(day_reader.flight_lines, "standing", unread)
    _today_and_back(lb)
    data = day_reader.read(lb, BACK[2], serve.Airports.load())
    assert data["flights"] == [], "a flight with no start is not placed"


def test_the_flights_over_a_move_skip_one_with_no_start_and_end_one_with_none_at_its_start() -> None:
    start, end = datetime(2025, 6, 17, 9, 0, tzinfo=UTC), datetime(2025, 6, 17, 10, 0, tzinfo=UTC)
    route = {"from": "OSL", "to": "BGO"}
    flights = [
        {"id": "unread", "start": None, "end": "2025-06-17T09:30:00Z", **route},
        {"id": "endless", "start": "2025-06-17T09:15:00Z", "end": None, **route},
        {"id": "later", "start": "2025-06-17T10:30:00Z", "end": None, **route},
        {"id": "whole", "start": "2025-06-17T09:20:00Z", "end": "2025-06-17T09:50:00Z", **route},
    ]
    assert day_reader._covering(flights, start, end) == ["endless", "whole"]
    assert day_reader._flown(start, end, flights) == ["OSL", "BGO"], "the one with both ends"
    assert day_reader._flown(start, end, flights[:3]) == [], "an instant flies no move"


def test_the_morning_folds_its_photos_into_the_record_and_adds_after_it(lb: Logbook) -> None:
    page = _page(_site(lb, TUESDAY, "09:00"), TUESDAY)
    assert _parts(page) == [
        "header",
        "for",
        "yesterday",
        "today",
        "record",
        "nothing-from",
        "add",
        "foot",
    ]
    assert "<summary><h2>Photos</h2>" in _part(page, "record")


def test_a_static_day_reads_no_promise_and_no_year_back(lb: Logbook) -> None:
    static = serve.Site(lb, now=lambda: _at(SATURDAY, "09:00"), href=lambda path: f"site{path}.html")
    page = static.page_day(WEDNESDAY, expanded=True)
    assert "Made on the day" not in page and "<summary><h2>Looking back" not in page
    said = re.search(r'<p class="nothing">Nothing from: (.*?)</p>', page)
    assert said is None or ("loose ends" not in said.group(1) and "looking back" not in said.group(1))
    assert "<form" not in page and "<script" not in page and _eyebrow(page) == "Wednesday · evening"


def test_a_birthday_a_week_on_is_a_week_today(lb: Logbook) -> None:
    people = _fold(_page(_site(lb, SATURDAY, "09:00"), TUESDAY, "open=1"), "People")
    assert f"Per Hansen{RSQUO}s birthday is a week today." in _text(people)


def test_a_birthday_is_said_with_no_age_and_no_digit_beside_the_name(lb: Logbook) -> None:
    """RFC 0043 principle 5: a person's name is never beside a count, an age or a score. The One
    person card and the Birthdays row say only the birthday; neither carries a digit at all."""
    for day, clock in ((SATURDAY, "09:00"), ("2026-06-23", "09:00"), (TUESDAY, "09:00")):
        page = _page(_site(lb, day, clock), day, "open=1")
        card = _part(page, "one-person") if "one-person" in _parts(page) else ""
        row = re.search(r'<li class="birthdays">.*?</li>', page, re.S)
        assert row is not None, day
        for said in (card, row.group(0)):
            assert beside(_seen(said), ["Per Hansen"]) == [], said
            assert not re.search(r"\d", _text(said)), _text(said)
            assert "turns" not in said
    today = _text(
        re.search(
            r'<li class="birthdays">.*?</li>',
            _page(_site(lb, "2026-06-23", "09:00"), "2026-06-23", "open=1"),
            re.S,
        ).group(0)
    )  # type: ignore[union-attr]
    assert f"Per Hansen{RSQUO}s birthday is today." in today


def _text(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


# -- a static site leaves a model's drafts out unless asked (#364) -------------------------------------------

WEEK_TEXT = "Plan the summer."  # the week's draft says it (`week_answer`)


def _drafted(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    """Wednesday with a day draft, its week (2026-W25) with a week draft, and the Berth contract call's
    synthesis with its decision; a site may carry tier 2 (the drafts' and the synthesis' tier)."""
    lb.append_many([photo(utc(WEDNESDAY, f"{h}:00"), ZURICH) for h in range(12, 18)])  # the June pick
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    fake(monkeypatch)
    assert run_cli("dream", "day", WEDNESDAY)[0] == 0
    with lb.index() as idx:
        evidence = next(str(line["id"]) for line in idx.day(WEDNESDAY) if line["kind"] == "location")
    payload: dict[str, Any] = {
        "schema": drafts.SCHEMA,
        "unit": drafts.UNIT_WEEK,
        "subject": W25,
        "read_head": "0" * 64,
        "read_count": 1,
        "language": "en",
        "segments": [{"text": WEEK_TEXT, "evidence": [evidence]}],
        "extra": {"prompt": "test/1", "parts": ["next_week"], "policy_version": "0" * 64, "entry": "dream"},
    }
    assert drafts.validate(payload) == []
    lb.append(utc(SUNDAY, "22:00"), f"{drafts.SOURCE_PREFIX}{MODEL}", drafts.KIND, 2, payload)
    policy = lb.root / "policy" / "crossing.json"
    data = json.loads(policy.read_text(encoding="utf-8"))
    data["site"] = {"max_tier": 2}
    policy.write_text(json.dumps(data), encoding="utf-8")


def _export(lb: Logbook, folder: Path, *flags: str) -> dict[str, str]:
    """The site's Day pages (the Year's picks), Wednesday among them as June's."""
    cli.main(["export", "site", str(folder), "--tier", "1,2", *flags])
    pages = {p.stem: p.read_text(encoding="utf-8") for p in sorted((folder / "days").glob("*.html"))}
    assert WEDNESDAY in pages, sorted(pages)
    return pages


def test_a_site_without_drafts_carries_no_pencil_in_the_evening_or_signed(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_network: list[str]
) -> None:
    _drafted(lb, monkeypatch)
    live = _page(_site(lb, SATURDAY, "09:00"), WEDNESDAY)
    assert "A day." in live and DECISION in live and "Pencil" in live, "the Library itself keeps the pencil"
    for shape, when in (("evening", None), ("signed", "2026-06-17T23:00:00+02:00")):
        if when is not None:
            _sign(WEDNESDAY, when)
        pages = _export(lb, tmp_path / f"site-{shape}")
        assert _eyebrow(pages[WEDNESDAY]).split(" · ")[1].startswith(shape)
        for day, page in pages.items():
            text = _text(page[page.index("<main>") :])  # what the page says, its stylesheet aside
            for words in (
                MODEL,
                "model:",
                "A day.",
                WEEK_TEXT,
                "Pencil",
                "proposals confirmed",
                "the model",
                DECISION,
                "No pencil yet",
                "has a draft",
                "decision",
            ):
                assert words not in text, (shape, day, words)
            assert "<h2>Draft</h2>" not in page and 'class="paper"' not in page, (shape, day)
        drafted = _export(lb, tmp_path / f"site-{shape}-with", "--with-drafts")[WEDNESDAY]
        assert "<h2>Draft</h2>" in drafted and MODEL in drafted and "A day." in drafted
        assert "Pencil" in drafted and ("<summary><h2>Pencil</h2>" in drafted) == (shape == "signed")
    assert no_network == []


def test_the_ribbon_says_the_time_before_the_entry_so_no_name_has_a_number_beside_it(lb: Logbook) -> None:
    """The twenty-seventh sitting's finding: `Dinner with Per Hansen 19:30` in a block's `<title>` and
    the ribbon's `aria-label` put a clock time beside a name, where the guard did not read. (The
    timeline's own row of an entry, `Dinner with Per Hansen 19:30 to 21:30`, is main's and the
    timeline's: not this test's.)"""
    lb.append(**event(utc(SATURDAY, "19:30"), utc(SATURDAY, "21:30"), "Dinner with Per Hansen"))
    names = sorted({p.name for p in people.directory(lb).known.values()})
    for shape in day_rhythm.SHAPES:
        ribbon = _ribbon(_page(_site(lb, SATURDAY, "09:00"), SATURDAY, f"shape={shape}"))
        assert beside(_seen(ribbon), names) == [], shape
        assert "<title>19:30" + DASH + "21:30 — Dinner with Per Hansen</title>" in ribbon, ribbon
        assert "19:30 — Dinner with Per Hansen" in _label(ribbon)


# -- the morning's computed parts (RFC 0043 slice A, the rest) ----------------------------------------------

MORNING_DAY = "2026-06-09"  # a Tuesday: its ordinal is even, so the one drifted person is this morning's
TASKS_DB, SPRINTS_DB, TRIPS_DB = (f"{n:08x}-0000-4000-8000-{n:012x}" for n in (0x100, 0x101, 0x102))
SPRINT_24, WEDDING = "00000202-0000-4000-8000-000000000202", "00000301-0000-4000-8000-000000000301"
TASK_TITLES = ["Book the ferry", "Buy rope", "Check the life jackets", "Clean the cabin",
               "Varnish the tiller", "Order charts"]  # fmt: skip
TIMES = {"Varnish the tiller": "16:00", "Order charts": "18:00"}  # the rest are dated the day, no time
TRIP = f"Per{RSQUO}s wedding in Bergen"
BERTH = "Keep the berth in Vollen."
PROPOSAL = "Book the harbour crane before the weekend."
SINCE = "Vi sees snart?"  # Ola's last word, on a Thursday in May: a reply owed


def _task_line(n: int, title: str, due: str) -> dict[str, Any]:
    page = f"{0x800 + n:08x}-0000-4000-8000-{0x800 + n:012x}"
    return notion(
        "2026-06-01T07:00:00Z",
        page,
        title,
        action="created",
        parent={"type": "database", "id": TASKS_DB},
        path=["Plan", "Tasks"],
        properties={"Due": {"start": due, "end": None}, "Status": "To do"},
        relations={"Sprint": [SPRINT_24]},
    )


def _morning(lb: Logbook) -> None:
    """Everything the morning of `MORNING_DAY` reads: six tasks dated the day (two with a time, the
    later one beyond the five shown) in Sprint 24 and a trip five weeks on, from the task tool; a
    dinner with Kari and Ola; Per Hansen, twenty days together in July 2024 and nothing since; Ola's
    message of 28 May unanswered; a decision a year ago to revisit on the day; and the week before's
    draft with its one proposal."""
    tasks = [
        _task_line(n, t, f"{MORNING_DAY}T{TIMES[t]}:00.000+02:00" if t in TIMES else MORNING_DAY)
        for n, t in enumerate(TASK_TITLES)
    ]
    plan = [
        notion("2026-06-01T06:00:00Z", SPRINT_24, "Sprint 24", action="created",
               parent={"type": "database", "id": SPRINTS_DB}, path=["Plan", "Sprints"],
               properties={"Dates": {"start": "2026-06-01", "end": "2026-06-14"}}),
        notion("2026-06-01T06:05:00Z", WEDDING, TRIP, action="created",
               parent={"type": "database", "id": TRIPS_DB}, path=["Plan", "Trips"],
               properties={"When": {"start": "2026-07-14", "end": "2026-07-16"}}),
        *tasks,
    ]  # fmt: skip
    together = []
    for d in range(1, 21):  # twenty days with Per Hansen in July 2024, at the cafe
        day = f"2024-07-{d:02d}"
        together += [
            *dwell(day, "00:00", "11:00", HOME, every_min=30),
            *dwell(day, "11:30", "14:00", CAFE, every_min=10),
            *dwell(day, "14:30", "24:00", HOME, every_min=30),
        ]
        together.append(
            event(utc(day, "11:45"), utc(day, "13:45"), "Sailing lunch", [attendee(PER["email"])])
        )
    decided = note(utc("2025-06-09", "21:00"), BERTH)
    decided["payload"]["labels"] = ["decision"]
    decided["payload"]["extra"] = {"revisit": MORNING_DAY}
    lb.append_many(
        [
            *plan,
            *together,
            event(
                utc(MORNING_DAY, "18:00"),
                utc(MORNING_DAY, "20:00"),
                "Dinner",
                [attendee(KARI["email"]), attendee(OLA["email"]), attendee("noreply@example.org")],
            ),
            message(utc("2026-05-28", "10:00"), SINCE, {**OLA, "name": "Ola"}),
            decided,
        ]
    )
    with lb.index() as idx:
        evidence = next(str(line["id"]) for line in idx.day(BEFORE) if line["kind"] == "event")
    lb.append(
        utc(BEFORE, "22:00"),
        f"{drafts.SOURCE_PREFIX}{MODEL}",
        drafts.KIND,
        2,
        {
            "schema": drafts.SCHEMA,
            "unit": drafts.UNIT_WEEK,
            "subject": "2026-W23",
            "read_head": "0" * 64,
            "read_count": 1,
            "language": "en",
            "segments": [{"text": PROPOSAL, "evidence": [evidence]}],
            "extra": {
                "prompt": "test/1",
                "parts": ["next_week"],
                "policy_version": "0" * 64,
                "entry": "dream",
            },
        },
    )
    (lb.root / "policy" / "notion.json").write_text(
        json.dumps({"plan": {"tasks": TASKS_DB, "sprints": SPRINTS_DB, "trips": TRIPS_DB}}), encoding="utf-8"
    )


def _names(lb: Logbook) -> list[str]:
    return sorted({p.name for p in people.directory(lb).known.values()})


def test_the_morning_holds_all_six(lb: Logbook) -> None:
    _morning(lb)
    site = _site(lb, MORNING_DAY, "07:00")
    page = _page(site, MORNING_DAY)
    assert _eyebrow(page) == "Tuesday · morning · 07:00"
    today = _part(page, "today")
    tasks = _fold(today, day_rhythm.TASKS)
    assert [t for t in TASK_TITLES if t in tasks] == TASK_TITLES[:5], "five at most"
    assert "and 1 more in Sprint 24 — " in tasks and "open in Notion" in tasks
    assert '<a href="/line/' in tasks and 'href="https://www.notion.so/' in tasks, "its line, its page"
    assert f"{TRIP} — in five weeks" in html.unescape(_text(tasks))
    assert '<line class="task"' in _ribbon(today) and "16:00 — Varnish the tiller" in _ribbon(today)
    seeing = _text(_fold(today, day_rhythm.SEEING))
    assert "Kari Nordmann, Ola Nordmann" in seeing and "noreply" not in seeing
    proposal = re.search(r'<p class="proposal">.*?</p>', today, re.S)
    assert proposal is not None and PROPOSAL in proposal.group(0) and MODEL in proposal.group(0)
    card = _text(_part(page, "one-person")).strip().split("\n")[-1]
    assert card == (
        "Per Hansen: you saw each other often the year before last; the last real contact was a day"
        " together in the summer that year."
    ), card
    assert not re.search(r"\d", card), card
    opened = _page(site, MORNING_DAY, "open=1")
    loose = _fold(opened, "Loose ends")
    assert "1 reply owed" in loose and "1 to revisit" in loose
    assert "Ola Nordmann wrote on a Thursday in May" in _text(loose)
    said = f"A year ago you decided: “{BERTH}” How did it turn out?"
    assert said in html.unescape(_text(loose))
    back = _fold(opened, "Looking back")
    assert said in html.unescape(_text(back)) and "1 decision to revisit" in back
    for shown in (page, opened):
        assert beside(_seen(shown), _names(lb)) == []
    assert "<form" not in loose and "<button" not in loose, "the verbs are slice C's"


def test_the_morning_s_new_parts_name_no_digit_beside_a_name_in_any_shape(lb: Logbook) -> None:
    _morning(lb)
    site = _site(lb, MORNING_DAY, "07:00")
    for shape in day_rhythm.SHAPES:
        for query in (f"shape={shape}", f"shape={shape}&open=1"):
            assert beside(_seen(_page(site, MORNING_DAY, query)), _names(lb)) == [], query


def test_an_empty_morning_names_each_part_once(lb: Logbook) -> None:
    page = _page(_site(lb, MORNING_DAY, "07:00"), MORNING_DAY)
    said = re.findall(r'<p class="nothing">Nothing from: (.*?)</p>', page)
    assert len(said) == 1
    named = html.unescape(said[0]).split(" · ")
    for part in (
        day_rhythm.TASKS.lower(),
        day_rhythm.PROPOSAL,
        "one person",
        "replies owed",
        "decisions to revisit",
    ):
        assert part in named, (part, named)
    assert day_rhythm.SEEING.lower() in named, "nothing timed with anyone on the day"


def test_a_birthday_comes_first_and_the_reconnect_waits(lb: Logbook) -> None:
    _morning(lb)
    lb.append(**_resolution(("email", "kari.2@example.org"), KARI_ID, "Kari Nordmann", birthday="1990-06-12"))
    card = _text(_part(_page(_site(lb, MORNING_DAY, "07:00"), MORNING_DAY), "one-person"))
    assert card.strip().endswith(f"\nKari Nordmann{RSQUO}s birthday is on Friday."), card
    assert "Per Hansen" not in card, "the birthday's morning has no reconnect"


def test_the_reconnect_is_never_the_same_person_two_mornings_running() -> None:
    def drifted(name: str, tier: int = 2) -> day_rhythm.Drifted:
        return day_rhythm.Drifted(name, f"id-{name}", tier, "2022", None)

    first = date(2026, 6, 1)
    for found in ([drifted("a")], [drifted("a"), drifted("b")], [drifted(n) for n in "abc"]):
        picks = [
            day_rhythm.reconnect(found, date.fromordinal(first.toordinal() + k).isoformat(), None)
            for k in range(30)
        ]
        assert any(picks)
        for a, b in pairwise(picks):
            assert a is None or a != b, (len(found), picks)
    assert day_rhythm.reconnect([drifted("a", tier=3)], "2026-06-02", [1, 2]) is None, "through the gate"


def test_the_reconnect_is_said_in_words() -> None:
    for year, then, words in (
        ("2025", "2025-12-01", "last year; the last real contact was a call in the winter that year."),
        (
            "2022",
            "2023-04-02",
            "a few years ago; the last real contact was a call in the spring, a few years ago.",
        ),
        (
            "2016",
            "2017-08-02",
            "many years ago; the last real contact was a call in the summer, many years ago.",
        ),
    ):
        d = day_rhythm.Drifted("Per Hansen", "p", 2, year, people_drift.Contact(then, people_drift.CALL, "x"))
        said = day_rhythm.reconnect_said(d, "2026-06-09", lambda c: str(c["name"]))
        assert said == f"Per Hansen: you saw each other often {words}", said
        assert not re.search(r"\d", said)


def test_a_countdown_and_the_days_ago_are_words() -> None:
    assert [day_rhythm.in_words(n) for n in (0, 1, 3, 7, 10, 35, 60, 200, 400)] == [
        "today", "tomorrow", "in three days", "in a week", "in a week", "in five weeks", "in two months",
        "in seven months", "in over a year",
    ]  # fmt: skip
    name = lambda c: str(c["name"])  # noqa: E731
    for then, words in (
        ("2026-06-01", "on Monday last week"),
        ("2026-05-28", "on a Thursday in May"),
        ("2026-06-01", "on Monday last week"),
    ):
        assert day_rhythm.wrote_said({"name": "Kari Nordmann", "day": then}, "2026-06-09", name) == (
            f"Kari Nordmann wrote {words}"
        )
    assert day_rhythm.wrote_said({"name": "Kari Nordmann", "day": "2026-06-10"}, "2026-06-25", name) == (
        "Kari Nordmann wrote on a Wednesday earlier this month"
    )
    assert day_rhythm._ago("2025-06-09", "2026-06-09") == "A year ago"
    assert day_rhythm._ago("2023-06-10", "2026-06-09") == "Two years ago"
    assert day_rhythm._ago("2026-03-09", "2026-06-09") == "Three months ago"


def test_a_tier_1_morning_names_nobody_a_tier_2_line_names(lb: Logbook) -> None:
    _morning(lb)
    page = _page(_site(lb, MORNING_DAY, "07:00", tiers=[1]), MORNING_DAY, "open=1")
    ours = _part(page, "today") + "".join(
        _fold(page, title) for title in ("Loose ends", "Looking back") if f"<summary><h2>{title}" in page
    )  # parts 2 to 4 and the revisits: the header's with row is main's (see the pull request)
    for name in ("Kari Nordmann", "Ola Nordmann", "Per Hansen"):
        assert name not in ours, name
    assert SINCE not in page and BERTH not in page and PROPOSAL not in page
    assert TASK_TITLES[0] in _part(page, "today"), "the plan is tier 1: it shows"
    assert "one-person" not in _parts(page)


def test_a_site_carries_no_morning_and_no_proposal_without_drafts(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_network: list[str]
) -> None:
    _morning(lb)
    policy = lb.root / "policy" / "crossing.json"
    data = json.loads(policy.read_text(encoding="utf-8"))
    data["site"] = {"max_tier": 2}
    policy.write_text(json.dumps(data), encoding="utf-8")
    cli.main(["export", "site", str(tmp_path / "site"), "--tier", "1,2"])
    for page in (tmp_path / "site").rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        assert PROPOSAL not in text and 'class="proposal"' not in text, page
        assert BERTH not in text and SINCE not in text, page
    quiet = _site(lb, MORNING_DAY, "07:00", with_drafts=False)
    assert PROPOSAL not in _page(quiet, MORNING_DAY), "the served page without drafts, as #364's guard"
    assert no_network == []


def test_the_morning_reads_nothing_over_the_network_on_the_demo_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_network: list[str]
) -> None:
    root = tmp_path / "Demo"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    lb = demo.generate(root, days=5, seed=1)
    last = max(str(line["at"])[:10] for line in lb.lines() if line["kind"] == "location")
    site = _site(lb, last, "07:00")
    for query in ("", "shape=morning", "shape=morning&open=1"):
        page = _page(site, last, query)
        assert _eyebrow(page).split(" · ")[1] == "morning"
        assert beside(_seen(page), _names(lb)) == []
    assert no_network == []


def test_the_plan_s_error_is_one_sentence_on_the_page(lb: Logbook) -> None:
    _morning(lb)
    (lb.root / "policy" / "notion.json").write_text(json.dumps({"plan": {"tasks": 3}}), encoding="utf-8")
    today = _part(_page(_site(lb, MORNING_DAY, "07:00"), MORNING_DAY), "today")
    assert "plan.tasks must be a Notion database id" in today


def test_an_entry_or_a_task_titled_by_a_name_alone_has_no_time_beside_it(lb: Logbook) -> None:
    """The review's case: an entry and a task whose title is a person's name, each with a time."""
    _morning(lb)
    lb.append(**event(utc(MORNING_DAY, "19:30"), utc(MORNING_DAY, "21:30"), "Per Hansen"))
    lb.append(**_task_line(20, "Per Hansen", f"{MORNING_DAY}T08:30:00.000+02:00"))
    page = _page(_site(lb, MORNING_DAY, "07:00"), MORNING_DAY)
    today = _part(page, "today")
    assert "Per Hansen" in _ribbon(today) and "Per Hansen" in _fold(today, day_rhythm.TASKS)
    assert beside(_seen(today), _names(lb)) == []


def test_logbook_serve_reads_the_reconnect_off_the_request(lb: Logbook) -> None:
    """`read_later`, as `logbook serve` builds its Site: the morning answers without the drift, the
    reading runs on a thread under the lock a sync's rebuild takes, and once it has arrived the Day's
    tag moves and the card is there; a sync after it does not read it again."""
    _morning(lb)
    site = serve.Site(lb, now=lambda: _at(MORNING_DAY, "07:00"), read_later=True)
    read: list[str] = []
    real = day_rhythm.drifted

    def counted(*a: Any, **kw: Any) -> Any:
        read.append("drift")
        return real(*a, **kw)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(day_rhythm, "drifted", counted)
        try:
            before = site.etag(f"/day/{MORNING_DAY}", "", site.current())
            site.respond(f"/day/{MORNING_DAY}", "")
        finally:
            site.settle()  # no thread outlives the test: it would read the next test's environment
        after = site.etag(f"/day/{MORNING_DAY}", "", site.current())
        assert after != before, "the reading has arrived: the page is read again"
        card = _text(_part(_page(site, MORNING_DAY), "one-person"))
        assert "Per Hansen: you saw each other often" in card
        lb.append(**note(utc(MORNING_DAY, "06:30"), "A line a sync brings."))
        assert "Per Hansen" in _part(_page(site, MORNING_DAY), "one-person")
        site.settle()
    assert read == ["drift"], "read once for the day, whatever the syncs"


def test_a_reading_beside_the_page_that_fails_is_no_plan_and_the_morning_still_answers(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under `read_later`, a reading that fails with anything but the mapping's own error holds `()`:
    the morning reads it as no plan, says the error once on stderr's hook, and answers 200."""
    _morning(lb)
    heard: list[BaseException | None] = []
    monkeypatch.setattr(threading, "excepthook", lambda args: heard.append(args.exc_value))

    def broken(*_a: Any, **_kw: Any) -> Any:
        raise RuntimeError("the plan's reading broke")

    monkeypatch.setattr(day_rhythm, "plan_of", broken)
    site = serve.Site(lb, now=lambda: _at(MORNING_DAY, "07:00"), read_later=True)
    try:
        first = site.respond(f"/day/{MORNING_DAY}", "")
    finally:
        site.settle()
    assert first.status == 200
    assert [type(e) for e in heard] == [RuntimeError], "the error is said, not swallowed"
    for query in ("", "open=1"):
        again = site.respond(f"/day/{MORNING_DAY}", query)
        assert again.status == 200, again.body[:300]
        today = _part(again.body.decode("utf-8"), "today")
        assert day_rhythm.TASKS not in today and '<line class="task"' not in today
    site.settle()


def test_a_person_shows_only_through_a_gate_that_reads_every_tier_up_to_theirs(lb: Logbook) -> None:
    """Through a gate of tiers (1, 3), a person whose evidence reaches tier 3 is not shown: what put
    them there may rest on a tier-2 line the gate does not read. The reconnect and the replies owed."""
    tier_three = day_rhythm.Drifted("Per Hansen", PER_ID, 3, "2024", None)
    days = [date.fromordinal(date(2026, 6, 1).toordinal() + k).isoformat() for k in range(4)]
    assert any(day_rhythm.reconnect([tier_three], d, (1, 2, 3)) for d in days)
    assert not any(day_rhythm.reconnect([tier_three], d, (1, 3)) for d in days)
    assert day_rhythm.reads_up_to(2, (1, 2)) and not day_rhythm.reads_up_to(2, (2,))
    resolution = _resolution(("phone", "+447700900123"), PER_ID, "Per Hansen")
    resolution["tier"] = 3
    said = message(utc("2026-05-28", "10:00"), "Ses vi?", {**PER, "name": "Per"})
    said["tier"] = 3
    lb.append_many([resolution, said])
    directory = people.directory(lb)
    assert directory.known[PER_ID].tier == 3
    assert [o["name"] for o in day_rhythm.replies_owed(lb, MORNING_DAY, directory, (1, 2, 3))] == [
        "Per Hansen"
    ]
    assert day_rhythm.replies_owed(lb, MORNING_DAY, directory, (1, 3)) == []
