"""Today gives a time its own column, apart from the names (the desk's independent look, round 164).

Today, the morning's plan under the Day's ribbon (where `/today` lands), lists the day's all-day entries,
its timed plan, what is due and the task tool's tasks of the day. A row's time is a `<time>` element in
a cell of its own, a `<dt>` (`all day`, `14:00`, `task`, `due`), and the title and the people are the
row's text, its `<dd>`: a column of its own on a wide screen, a line of its own above the row on a phone,
as the Day's timeline shows a time first. So a title that opens with a name (`Ola Nordmann's birthday
cake`) or ends with one (`Dinner with Kari Nordmann`) never shares a row of text with a clock, and main's
guard (`figures.adjacent`, every separator, a date in words, the first name too) finds nothing on Today
through any gate. Today at `/` (the Library's front door) shows no clock in any row: its open rows say
`since` after the person and the words, as the desk set them (#417).

On the dream's synthetic fortnight (Ines, Kari and Ola Nordmann of Oslo, Per Hansen) and the demo record;
nobody here exists, every address at example.org."""

from __future__ import annotations

import html
import json
import re
import shutil
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import phone_width
import pytest
from beside_a_name import page_rows
from dream_fortnight import fortnight
from ideas_record import notion
from persona import KARI, OLA, attendee, event, utc
from test_day_rhythm import _seen
from test_day_rhythm import beside as day_guard

from logbook.contrib import day_rhythm, demo, promises, serve
from logbook.core import figures, people
from logbook.core.store import Logbook

TZ = ZoneInfo("Europe/Oslo")
DAY = "2026-06-10"  # a Wednesday of the fortnight
CAKE = "Ola Nordmann's birthday cake"  # a timed entry whose title opens with a name
DINNER = "Dinner with Kari Nordmann"  # one whose title ends with a name
BIRTHDAY = "Birthday Ola Nordmann"  # all-day
CALL = "Call Per Hansen"  # a task of the day with a time, its title ending with a name
SECRET = "Lunch with Per Hemmelig"  # an entry at tier 3: the person only a tier-3 page may name
TASKS_DB = "00000100-0000-4000-8000-000000000100"
GATES: tuple[tuple[int, ...] | None, ...] = ((1,), (1, 2), (1, 2, 3), None)
CLOCK = re.compile(r"\b\d{1,2}:\d{2}\b")
CELL = re.compile(r"<dt\b[^>]*>(.*?)</dt>\s*<dd\b[^>]*>(.*?)</dd>", re.S)
TIME = re.compile(r'<time class="t" datetime="([^"]+)">([^<]*)</time>')


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
    with pytest.MonkeyPatch.context() as mp:
        root = tmp_path_factory.mktemp("today-time-apart") / "lb"
        mp.setenv("LOGBOOK_HOME", str(root))
        lb = fortnight(root)
        secret = event(utc(DAY, "12:00"), utc(DAY, "13:00"), SECRET)
        secret["tier"] = 3
        lb.append_many(
            [
                event(utc(DAY, "00:00"), utc("2026-06-11", "00:00"), BIRTHDAY, all_day=True),
                event(utc(DAY, "17:00"), utc(DAY, "18:00"), CAKE, [attendee(OLA["email"])]),
                event(utc(DAY, "19:30"), utc(DAY, "21:00"), DINNER, [attendee(KARI["email"])]),
                secret,
                _task(CALL, f"{DAY}T16:00:00.000+02:00"),
            ]
        )
        (lb.root / "policy" / "notion.json").write_text(
            json.dumps({"plan": {"tasks": TASKS_DB}}), encoding="utf-8"
        )
        return lb.root


@pytest.fixture
def lb(pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    shutil.copytree(pristine, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook(root)


@pytest.fixture(scope="module")
def demo_record(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    with pytest.MonkeyPatch.context() as mp:
        root = tmp_path_factory.mktemp("today-time-apart-demo") / "Demo"
        mp.setenv("LOGBOOK_HOME", str(root))
        return demo.generate(root, days=30, seed=1)


def _at(day: str, clock: str) -> datetime:
    return datetime.fromisoformat(f"{day}T{clock}:00").replace(tzinfo=TZ).astimezone(UTC)


def _page(lb: Logbook, path: str, day: str, clock: str = "07:00", query: str = "", **kw: Any) -> str:
    response = serve.Site(Logbook(lb.root), now=lambda: _at(day, clock), **kw).respond(path, query)
    assert response.status == 200, response.body[:300]
    return response.body.decode("utf-8")


def _today(page: str) -> str:
    """Today on the Day page: the morning's plan, from the ribbon to the end of its part."""
    start = page.index('<section class="part today"')
    return page[start : page.index("</section><!--part-->", start)]


def _names(lb: Logbook) -> list[str]:
    """Every person the record names, and each one's first name too (the main guard reads both)."""
    full = {p.name for p in people.directory(lb).known.values() if p.name}
    full |= {"Ines Nordmann", "Kari Nordmann", "Ola Nordmann", "Per Hansen", "Per Hemmelig"}
    return sorted(full | {n.split()[0] for n in full})


def _guard(fragment: str, names: Iterable[str]) -> list[str]:
    """Main's guards over `fragment`: the rows a reader sees (a list item one row, its cells run
    together) read by `figures.adjacent`, and the Day page's guard over its text (`_seen`)."""
    names = list(names)
    found = [row for row in page_rows(fragment) if any(figures.adjacent(row, n) for n in names)]
    return found + day_guard(_seen(fragment), names)


def _cells(fragment: str) -> list[tuple[str, str]]:
    """(the time's cell, the row's text) of every row of Today's lists."""
    return CELL.findall(fragment)


def _assert_apart(today: str, names: Sequence[str]) -> int:
    """Every clock on Today stands in a `<time>` alone in its own cell, no name in that cell; returns how
    many timed rows there are."""
    timed = 0
    for cell, text in _cells(today):
        assert not any(re.search(rf"\b{re.escape(n)}\b", html.unescape(cell)) for n in names), cell
        assert not CLOCK.search(re.sub(r"<[^>]+>", " ", text)), ("a clock in the row's text", text)
        found = TIME.fullmatch(cell.strip())
        if CLOCK.search(cell):
            assert found is not None, ("a clock outside its <time>", cell)
            timed += 1
    for text in re.findall(r"<dd\b[^>]*>(.*?)</dd>", today, re.S):  # a row's text, a pair's or alone
        assert not CLOCK.search(re.sub(r"<[^>]+>", " ", text)), ("a clock in a row's text", text)
    rows = re.findall(r"<li\b[^>]*>(.*?)</li>", today, re.S)
    for row in rows:  # a clock in a list item would share a row with its words
        assert not CLOCK.search(re.sub(r"<[^>]+>", " ", re.sub(r"<svg\b.*?</svg>", "", row, flags=re.S))), row
    return timed


# -- the plan, all day, due and the tasks: the time in a cell of its own ------------------------------------


def test_today_s_rows_give_the_time_its_own_cell_and_the_names_the_row_s_text(lb: Logbook) -> None:
    today = _today(_page(lb, f"/day/{DAY}", DAY))
    by_title = {
        title: cell
        for cell, text in _cells(today)
        for title in (CAKE, DINNER, BIRTHDAY, CALL)
        if html.unescape(re.sub(r"<[^>]+>", "", text)).startswith(title)
    }
    assert set(by_title) == {CAKE, DINNER, BIRTHDAY, CALL}, _cells(today)
    assert TIME.fullmatch(by_title[CAKE].strip()).groups() == (f"{DAY}T17:00+02:00", "17:00")  # type: ignore[union-attr]
    assert TIME.fullmatch(by_title[DINNER].strip()).groups() == (f"{DAY}T19:30+02:00", "19:30")  # type: ignore[union-attr]
    assert TIME.fullmatch(by_title[BIRTHDAY].strip()).groups() == (DAY, "all day")  # type: ignore[union-attr]
    assert TIME.fullmatch(by_title[CALL].strip()).groups() == (f"{DAY}T16:00+02:00", "16:00")  # type: ignore[union-attr]
    assert _assert_apart(today, _names(lb)) >= 3
    assert _guard(today, _names(lb)) == [], "main's guard finds nothing on Today"


def test_today_s_time_is_a_column_on_a_wide_screen_and_a_line_above_on_a_phone(lb: Logbook) -> None:
    page = _page(lb, f"/day/{DAY}", DAY)
    assert phone_width.problems(page) == []
    css = re.search(r"<style>(.*?)</style>", page, re.S).group(1)  # type: ignore[union-attr]
    at = css.rindex("@media (max-width:40rem)")  # the Day's own breakpoint, after the frame's
    wide = css[:at]
    grid = re.search(r"dl\.rows\{([^}]*)\}", wide)
    assert grid is not None and "display:grid" in grid.group(1), "a grid: the time a column of its own"
    assert re.search(r"grid-template-columns:\s*\S+\s+minmax\(0,\s*1fr\)", grid.group(1)), grid.group(1)
    phone = css[at:]
    stacked = re.search(r"dl\.rows\{([^}]*)\}", phone)
    assert stacked is not None and "display:block" in stacked.group(1), "on a phone, the time its own line"
    assert re.search(r"dl\.rows dt\{[^}]*display:block", phone), "above the row's text"


def test_main_s_guard_finds_nothing_on_today_through_any_gate(lb: Logbook) -> None:
    names = _names(lb)
    for gate in GATES:
        page = _page(lb, f"/day/{DAY}", DAY, tiers=gate)
        today = _today(page)
        assert _guard(today, names) == [], gate
        _assert_apart(today, names)
        assert ("Per Hemmelig" in today) == (gate is None or 3 in gate), ("the tier-3 entry", gate)
        front = _page(lb, "/", DAY, tiers=gate)
        main = front[front.index('<main class="door">') : front.index("</main>")]
        assert _guard(main, names) == [], ("the front door", gate)
        _assert_apart(main, names)


def test_the_demo_record_s_mornings_put_every_time_apart_from_every_name(demo_record: Logbook) -> None:
    names = _names(demo_record)
    timed = 0
    for n in range(30):
        day = (demo.START + timedelta(days=n)).isoformat()
        for gate in ((1,), (1, 2), (1, 2, 3)):
            # the morning's shape of each day, as the page shows it for reading (`?shape=`): some demo
            # days are under way before dawn
            today = _today(_page(demo_record, f"/day/{day}", day, query="shape=morning", tiers=gate))
            assert _guard(today, names) == [], (day, gate)
            timed += _assert_apart(today, names)
    assert timed > 30, "the demo's plan is on its mornings"
    for gate in ((1,), (1, 2), (1, 2, 3)):
        page = _page(demo_record, "/", (demo.START + timedelta(days=29)).isoformat(), tiers=gate)
        main = page[page.index('<main class="door">') : page.index("</main>")]
        assert _guard(main, names) == [], gate
        _assert_apart(main, names)


def test_today_html_puts_a_time_first_in_a_cell_of_its_own() -> None:
    """The reader itself: no record, a plan entry whose title opens with a name and a task's row."""
    start = datetime(2026, 6, 10, 15, 0, tzinfo=UTC)
    entry = day_rhythm.Planned(CAKE, start, start + timedelta(hours=1), True, None, "l-1")
    body = day_rhythm.today_html([entry], [], DAY, TZ, lambda c: "", [BIRTHDAY])
    assert body.startswith('<dl class="rows">'), body
    assert f'<dt class="plan"><time class="t" datetime="{DAY}">all day</time></dt>' in body
    assert (
        f'<dt class="plan"><time class="t" datetime="{DAY}T17:00+02:00">17:00</time></dt><dd class="plan">'
        in body
    )
    assert _guard(body, ["Ola Nordmann", "Ola"]) == []


def _due(day: str, direction: str | None, role: str | None) -> promises.Proposal:
    """A promise with Ola Nordmann said on `day` and due on `DAY`: a fortnight back is said as a date."""
    match = promises.Match("I'll send the photos of the berth.", "I'll", "future", "en")
    return promises.Proposal(
        "p-1", day, f"{day}T10:00:00Z", "l-1", 1, "message", "whatsapp", None, None, direction, match, DAY,
        role=role, counterpart="Ola Nordmann",
    )  # fmt: skip


def test_a_promise_due_today_says_when_it_was_said_with_a_word_before_the_name() -> None:
    """The review's finding: a promise said more than a week before it is due says its day as a date,
    and the sub-line read `you were promised on 2026-05-20 · Ola Nordmann`, a date beside a name in
    the row's text. The person follows a word (`by`, `to`), as the open rows on `/` say it."""
    names = ["Ola Nordmann", "Ola"]
    for said, direction, role in (
        ("by", promises.OWED_TO_OWNER, None),
        ("by", promises.OWED_TO_OWNER, promises.ASKED),
        ("to", promises.OWED_BY_OWNER, None),
    ):
        for day in ("2026-05-20", "2026-06-08", DAY):
            body = day_rhythm.today_html([], [_due(day, direction, role)], DAY, TZ, lambda c: str(c["name"]))
            assert _guard(body, names) == [], (day, direction, role, body)
            assert f", {said} Ola Nordmann" in html.unescape(body), body


def test_today_s_last_row_draws_no_rule_under_it(lb: Logbook) -> None:
    """As `ul.rows li:last-child` drew none: the last pair of cells, on a wide screen and a phone."""
    page = _page(lb, f"/day/{DAY}", DAY)
    css = re.search(r"<style>(.*?)</style>", page, re.S).group(1)  # type: ignore[union-attr]
    assert re.search(r"dl\.rows dd:last-child\{border-bottom:0\}", css), "the last row draws no rule"
    assert not re.search(r"dl\.rows dt\{[^}]*border", css), "the rule is the row's text's, never the time's"
    for listed in re.findall(r'<dl class="rows">(.*?)</dl>', _today(page), re.S):
        assert listed.rstrip().endswith("</dd>"), "a list ends with a row's text, the one the rule leaves"
