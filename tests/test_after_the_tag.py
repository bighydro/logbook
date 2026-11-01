"""After the tag (v1.0.0): the desk's reviews of the last week of October. No number, date or clock time
touches a person's name with only separators between, anywhere a person reads it (text, titles,
aria-labels, alt, hover text), words between are fine (the owner): the digest's tomorrow says the title,
then its time after a word; an all-day entry says `all day`, never `from 00:00 to 00:00+1`, in `logbook
day`, on the Day page, Today, the week page and the digest, whichever calendar flagged it and when one
of two calendars did not; the ribbon's words and the task-done message keep a word between a clock or
a date and a name. And a page that reads no notes looks exactly as if the day had no reflection. On the
dream's synthetic fortnight: Ines, Kari and Ola Nordmann of Oslo and Per Hansen, who do not exist."""

from __future__ import annotations

import html
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from dream_fortnight import fortnight, run_cli
from persona import KARI, OLA, attendee, event, note, utc
from test_no_count_beside_a_name import beside

from logbook.contrib import day_rhythm, demo, serve, taskdone, week_page
from logbook.core import figures
from logbook.core.store import Logbook

TZ = ZoneInfo("Europe/Oslo")
LOOPBACK = "127.0.0.1"
DAY, TOMORROW, WEEK = "2026-06-10", "2026-06-11", "2026-W24"  # a Wednesday, and its Thursday
PARTY = "Ola Nordmann's birthday"  # a timed entry with no end whose title opens with a name
DINNER = "Dinner with Kari Nordmann"  # one whose title ends with a name
BIRTHDAY = "Birthday Ola Nordmann"  # all-day on one calendar, midnight to midnight on another
NAME_DAY = "Kari Nordmann's name day"  # midnight to midnight on a calendar that flags no all-day
HANSEN = "Birthday Per Hansen"  # all-day, tomorrow
WHOLE = ("00:00+1", "from 00:00 to 00:00", "00:00\u201300:00")  # how a whole day read before


def _whole_day(day: str, next_day: str, title: str, **extra: Any) -> dict[str, Any]:
    return event(utc(day, "00:00"), utc(next_day, "00:00"), title, **extra)


@pytest.fixture(scope="module")
def pristine(tmp_path_factory: pytest.TempPathFactory) -> Path:
    with pytest.MonkeyPatch.context() as mp:
        root = tmp_path_factory.mktemp("after-the-tag") / "lb"
        mp.setenv("LOGBOOK_HOME", str(root))
        lb = fortnight(root)
        lb.append_many(
            [
                _whole_day(DAY, TOMORROW, BIRTHDAY, all_day=True),
                {**_whole_day(DAY, TOMORROW, BIRTHDAY), "source": "notion"},  # the same, timed
                {**_whole_day(DAY, TOMORROW, NAME_DAY), "source": "notion"},
                _whole_day(TOMORROW, "2026-06-12", HANSEN, all_day=True),
                {k: v for k, v in event(utc(TOMORROW, "19:30"), "", PARTY).items() if k != "end"},
                event(utc(TOMORROW, "19:30"), utc(TOMORROW, "21:00"), DINNER, [attendee(KARI["email"])]),
                {k: v for k, v in event(utc(DAY, "17:00"), "", PARTY + " cake").items() if k != "end"},
            ]
        )
        return lb.root


@pytest.fixture
def lb(pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    shutil.copytree(pristine, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook(root)


def _at(day: str, clock: str) -> datetime:
    return datetime.fromisoformat(f"{day}T{clock}:00").replace(tzinfo=TZ).astimezone(UTC)


def _page(lb: Logbook, path: str, day: str = DAY, clock: str = "21:30", **kw: Any) -> str:
    response = serve.Site(Logbook(lb.root), now=lambda: _at(day, clock), **kw).respond(path, "")
    assert response.status == 200, response.body[:300]
    return html.unescape(response.body.decode("utf-8"))


def _ribbon_said(page: str) -> list[str]:
    return re.findall(r'<svg class="ribbon"[^>]*aria-label="([^"]*)"', page)


# -- 1. the digest's tomorrow: the title, then its time after a word -----------------------------------------


def test_the_digest_s_tomorrow_says_the_title_then_its_time_after_a_word(lb: Logbook) -> None:
    code, out, err = run_cli("digest", DAY)
    assert code == 0, err
    rows = [row for row in out.splitlines() if row.lstrip().startswith("tomorrow")]
    assert any(f"{PARTY}, from 19:30" in row for row in rows), rows
    assert any(f"{DINNER}, from 19:30 to 21:00" in row for row in rows), rows
    assert not any(re.search(r"tomorrow\s+\d", row.lstrip()) for row in rows), "no clock opens a row"
    assert beside(out) == [], beside(out)


# -- 2. an all-day entry says all day ---------------------------------------------------------------------


def test_an_all_day_entry_says_all_day_in_logbook_day(lb: Logbook) -> None:
    code, out, err = run_cli("day", DAY)
    assert code == 0, err
    assert not any(whole in out for whole in WHOLE), out
    (row,) = [row for row in out.splitlines() if row.lstrip().startswith("all day")]
    assert BIRTHDAY in row and NAME_DAY in row and "from 2 sources" in row, row
    assert f"{BIRTHDAY}, from" not in out and f"{NAME_DAY}, from" not in out, out


def test_an_all_day_entry_says_all_day_on_the_day_page_today_and_the_week(lb: Logbook) -> None:
    """Each says it as it says an all-day entry already: the Day's `all day` row, Today's `all day` in
    its plan's time column, and the week a line `all day:` under the day's ribbon, which draws none."""
    day = _page(lb, f"/day/{DAY}")
    today = _page(lb, f"/day/{DAY}", clock="07:00")  # Today: the morning's plan under the ribbon
    week = _page(lb, f"/week/{WEEK}", clock="12:00")
    said = {
        "day": re.findall(r"<dt>all day</dt><dd>(.*?)</dd>", day, re.S),
        "today": re.findall(r'<li class="plan"><div class="t">all day</div><span>(.*?)</li>', today, re.S),
        "week": re.findall(r'<p class="allday">all day: (.*?)</p>', week, re.S),
    }
    for name, page in (("day", day), ("today", today), ("week", week)):
        for title in (BIRTHDAY, NAME_DAY):
            assert f"{title}, from" not in page, (name, title)
            assert any(title in found for found in said[name]), (name, title, said[name])
        assert "00:00+1" not in page, name
        assert not any(BIRTHDAY in s for s in _ribbon_said(page)), (
            "the ribbon draws and says no all-day entry"
        )
    assert '<div class="t">00:00</div>' not in today


def test_an_all_day_entry_says_all_day_in_the_digest(lb: Logbook) -> None:
    code, out, err = run_cli("digest", "2026-06-09")
    assert code == 0, err
    rows = [row for row in out.splitlines() if row.lstrip().startswith("tomorrow")]
    assert any(f"{BIRTHDAY}, all day" in row for row in rows), rows
    assert any(f"{NAME_DAY}, all day" in row for row in rows), rows
    assert not any(whole in out for whole in WHOLE), rows
    code, out, err = run_cli("digest", DAY)
    assert code == 0 and f"{HANSEN}, all day" in out, out + err


# -- 3. the ribbon's words and the task-done message ---------------------------------------------------


DEMO_NAMES = [p.name for p in (demo.OWNER, *demo.PEOPLE)]
DEMO_NAMES += [n.split()[0] for n in DEMO_NAMES if len(n.split()[0]) >= 3]  # as `figures.beside_a_name`


def test_the_ribbon_s_words_set_no_clock_beside_a_name() -> None:
    """The ribbon's sentence ended its plan with a clock and opened what was lived with `Lived:`,
    whose first letters are the demo's Liv: `from 12:00. Lived` is a clock beside a name, as the
    guard reads one (no boundary is asked of the name, the desk, 29 October)."""
    said = day_rhythm._ribbon_said(["Lunch, from 12:00"], {"stay": 2, "move": 1}, 1, "00:00", "00:00", "")
    assert [n for n in DEMO_NAMES if figures.adjacent(said, n)] == [], said
    nothing = day_rhythm._ribbon_said([], {}, 0, "04:00", "04:00", "no stay")
    assert [n for n in DEMO_NAMES if figures.adjacent(nothing, n)] == [], nothing


def _task(at: str, key: str, title: str, **fields: Any) -> dict[str, Any]:
    payload = {
        "schema": "task/v1",
        "raw_id": f"{key}@{at}",
        "title": title,
        "status": "open",
        "modified_at": at,
    }
    return {"at": at, "source": "google-takeout", "kind": "task", "tier": 2, "payload": {**payload, **fields}}


def test_the_task_done_message_and_the_task_rows_keep_a_word_between_a_date_and_a_name(
    lb: Logbook,
) -> None:
    """`tasks done` printed `done: “Call Ola Nordmann”  (2026-06-09, task/v1 line …)`: a date after a
    title that ends with a name. Its rows, and the proposals', put a date or an id after a title too."""
    lb.append_many(
        [
            _task(utc("2026-06-09", "08:00"), "b2xh", "Call Ola Nordmann", due="2026-06-12"),
            _task(utc("2026-06-09", "08:10"), "a2FyaQ", "Kari Nordmann", list="Home"),
            event(utc("2026-06-12", "10:00"), utc("2026-06-12", "10:30"), "Call Ola Nordmann",
                  [attendee(OLA["email"])]),
        ]
    )  # fmt: skip
    for args in (("promises", "tasks"), ("promises", "tasks", "--propose-done")):
        code, out, err = run_cli(*args)
        assert code == 0 and "Call Ola Nordmann" in out, out + err
        assert beside(out) == [], (args, beside(out))
    code, out, err = run_cli("promises", "tasks", "done", taskdone.task_id("b2xh"))
    assert code == 0 and "done" in out and "Call Ola Nordmann" in out, out + err
    assert beside(out) == [], beside(out)
    code, out, err = run_cli("promises", "tasks", "done", taskdone.task_id("b2xh"))
    assert code == 0 and "already done" in out and beside(out) == [], out + err


# -- 6. a page that reads no notes cannot tell whether the day has a reflection ------------------------


HEAD = re.compile(r"<code>[0-9a-f]{12}…</code>")  # the record's head: it moves with any line


def _twins(lb: Logbook, tmp_path: Path, tier: int) -> tuple[Path, Path]:
    """Two records alike but for one note on the day at `tier`: a reflection in one, a plain note in
    the other, so both hold as many lines."""
    plain, reflected = tmp_path / "plain", tmp_path / "reflected"
    shutil.copytree(lb.root, plain)
    shutil.copytree(lb.root, reflected)
    words = "A good day with Ola Nordmann. I will send Kari the map."
    line = {**note(utc(DAY, "21:00"), words), "tier": tier}
    Logbook(plain).append_many([line])
    line["payload"] = {**line["payload"], "labels": ["reflection"]}
    Logbook(reflected).append_many([line])
    return plain, reflected


@pytest.mark.parametrize(("gate", "tier"), [((1,), 2), ((1,), 3), ((1, 2), 3)])
def test_a_page_below_the_reflection_looks_exactly_as_if_there_were_none(
    lb: Logbook, tmp_path: Path, gate: tuple[int, ...], tier: int
) -> None:
    plain, reflected = _twins(lb, tmp_path, tier)
    for clock in ("07:00", "21:30"):
        for path in (f"/day/{DAY}", "/"):
            pages = [
                HEAD.sub("<code>…</code>", _page(Logbook(root), path, clock=clock, tiers=gate))
                for root in (plain, reflected)
            ]
            assert pages[0] == pages[1], (clock, path, [p for p in _diff(*pages)])


def _diff(a: str, b: str) -> list[tuple[str, str]]:
    return [(x, y) for x, y in zip(a.splitlines(), b.splitlines(), strict=False) if x != y][:4]


def test_a_tier_one_page_still_signs_with_the_reflection_it_cannot_show(lb: Logbook, tmp_path: Path) -> None:
    """The Sign form of a page that reads no notes carries what it read up to, never the reflection's
    id or a digest of it; Sign signs with the reflection standing then, and a reflection written
    since is a 409, nothing written."""
    _plain, reflected = _twins(lb, tmp_path, 2)
    stale = shutil.copytree(reflected, tmp_path / "stale")

    def site(root: Path) -> serve.Site:
        return serve.Site(Logbook(root), now=lambda: _at(DAY, "21:30"), tiers=(1,))

    page = site(reflected).respond(f"/day/{DAY}", "").body.decode("utf-8")
    form = re.search(r'<form class="sign".*?</form>', page, re.S)
    assert form is not None
    fields = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', form.group(0)))
    newer = {**note(utc(DAY, "21:10"), "Another reflection."), "payload": {"schema": "note/v1",
             "text": "Another reflection.", "labels": ["reflection"]}}  # fmt: skip
    Logbook(stale).append_many([newer])
    seq = Logbook(stale).meta["seq"]
    refused = site(stale).write(f"/day/{DAY}/sign", {**fields, "act": "sign"}, LOOPBACK, None, None)
    assert refused.status == 409 and Logbook(stale).meta["seq"] == seq, refused.body[:300]
    signed = site(reflected).write(f"/day/{DAY}/sign", {**fields, "act": "sign"}, LOOPBACK, None, None)
    assert signed.status == 303, signed.body[:300]


# -- 5. the week page's guard is the main one ---------------------------------------------------------------


def test_the_week_page_holds_a_sentence_to_the_main_guard() -> None:
    """`week_page.beside` had its own separators, fewer than `figures.SEPARATORS`, and read no date in
    words as a figure: it is the main guard (`figures.adjacent`), the full name and the first."""
    names = ["Ola Nordmann", "Kari Nordmann"]
    for said in (
        "Ola Nordmann; 8 June",
        "Ola Nordmann / 14:00",
        "Ola Nordmann → 14:00",
        "[Ola Nordmann] 8 June",
        "8 June · Ola Nordmann",
        "Dinner with Ola Nordmann «2».",
        "Ola Nordmann…2",
        "Most of all with Kari Nordmann.  […6742a9f5]",
        "Ola: 4 times",  # the first name, as `figures.beside_a_name` reads one
        "3xKari came",
    ):
        assert week_page.beside(said, names), said
        assert any(figures.adjacent(said, n) for n in (*names, "Ola", "Kari")), said
    for said in ("Ola Nordmann promised you · since 8 June", "With Ola at 14:00.", "Olav 2"):
        assert not week_page.beside(said, names), said


def test_a_reflection_above_the_gate_leaves_the_one_below_it_standing(lb: Logbook, tmp_path: Path) -> None:
    """The review: under a 1,2 gate, a tier-3 reflection after a tier-2 one hid both, `Reflect first`
    and no Sign, where the day without it shows the tier-2 one: the page reads the one it can see."""
    earlier = {**note(utc(DAY, "20:00"), "An earlier word on the day."), "tier": 2}
    earlier["payload"] = {**earlier["payload"], "labels": ["reflection"]}
    lb.append_many([earlier])
    plain, reflected = _twins(lb, tmp_path, 3)
    pages = [
        HEAD.sub("<code>…</code>", _page(Logbook(root), f"/day/{DAY}", tiers=(1, 2)))
        for root in (plain, reflected)
    ]
    assert pages[0] == pages[1], _diff(*pages)
    assert "An earlier word on the day." in pages[1] and '<form class="sign"' in pages[1]


def test_the_week_s_all_day_line_puts_a_word_between_its_titles(lb: Logbook) -> None:
    """The review: `Birthday Ola Nordmann · 17 May dinner` sets a figure beside a name across a dot."""
    lb.append_many(
        [_whole_day(DAY, TOMORROW, t, all_day=True) for t in ("Away with Per Hansen", "17 May dinner")]
    )
    week = _page(lb, f"/week/{WEEK}", clock="12:00")
    lines = re.findall(r'<p class="allday">(.*?)</p>', week, re.S)
    assert lines and beside(lines) == [], lines
    code, out, _err = run_cli("day", DAY)  # and the Day's own `all day` row, in text and on its page
    (row,) = [row for row in out.splitlines() if row.lstrip().startswith("all day")]
    assert code == 0 and "17 May dinner" in row and beside(row) == [], row
    rows = re.findall(r"<dt>all day</dt><dd>(.*?)</dd>", _page(lb, f"/day/{DAY}"), re.S)
    assert rows and beside(rows) == [], rows
