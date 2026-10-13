"""The Day with RFC 0036's owner lines (its section *What a Day page shows*): the chapter a day is in,
in the header after the weekday and the signed state; a row per goal review on the day the verdict
is about, with the goal's current text and `written <when>` when it was written later; and the goal
and chapter lines listed on the day of their `at`. `day`, `show` and the `serve` page alike, each
through the tier gate it reads under. Ines Nordmann of Oslo and her goals are synthetic."""

from __future__ import annotations

import contextlib
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.contrib import serve
from logbook.core import chapter, goals, signing, store
from logbook.core import day as day_reader
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
FIRST_GOAL = "019cadd3-6bc0-7dcd-9133-000000000301"
SECOND_GOAL = "019cadd3-6bc0-7dcd-9133-000000000302"
FIRST_TEXT = "Sail the boat to Lofoten and back in one summer."
SECOND_TEXT = "Sail to Lofoten and back between June and August, at anchor more nights than not."
NOTE = "Engine gone in Bodø on the 9th. Towed home. Next summer."
SUMMER, ASHORE = "The Lofoten summer", "Ashore, fixing things"
DASH = chapter.EN_DASH


def pin(monkeypatch: pytest.MonkeyPatch, stamp: str) -> None:
    instant = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    monkeypatch.setattr(goals, "now", lambda: instant)


def run(*args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            cli.main(list(args))
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
    return code, out.getvalue(), err.getvalue()


def day_json(day: str) -> dict[str, Any]:
    code, out, err = run("day", day, "--json", "--no-anniversaries")
    assert code == 0, err
    found: dict[str, Any] = json.loads(out)
    return found


def day_text(day: str) -> list[str]:
    code, out, err = run("day", day, "--no-anniversaries")
    assert code == 0, err
    return out.splitlines()


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """The year of the sailing goal: written in January, reworded in March, let go in August (said in
    October); the summer on the boat and the time ashore after it, named in September."""
    lb = Logbook.init(tmp_path / "Logbook", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    queue = [FIRST_GOAL, SECOND_GOAL]
    real = store.uuid7
    monkeypatch.setattr(store, "uuid7", lambda: queue.pop(0) if queue else real())
    pin(monkeypatch, "2026-01-04T10:15:00Z")
    goals.add(lb, FIRST_TEXT, "year", "2026-01-01")
    pin(monkeypatch, "2026-03-15T08:40:00Z")
    goals.add(lb, SECOND_TEXT, "year", "2026-01-01", "2026-12-31", FIRST_GOAL)
    pin(monkeypatch, "2026-09-06T17:20:00Z")
    chapter.open_chapter(lb, SUMMER, "2026-06-20", "2026-08-09", "Every night at anchor counts.")
    pin(monkeypatch, "2026-09-06T17:25:00Z")
    chapter.open_chapter(lb, ASHORE, "2026-08-10", None, "The engine rebuilt.")
    pin(monkeypatch, "2026-10-11T18:30:00Z")
    goals.review(lb, SECOND_GOAL, "let-go", "month", NOTE, "2026-08-31T20:00:00Z")
    return lb


# -- the chapter, in the header ------------------------------------------------------------------------------


def test_the_header_names_the_chapter_after_the_weekday_and_the_signed_state(lb: Logbook):
    lb.append(
        "2026-07-04T18:00:00Z", "manual", "note", 2, {"schema": "note/v1", "text": "Anchored off Træna."}
    )
    signing.sign(lb, "2026-07-04", at="2026-07-05T08:15:00+02:00")
    assert (
        day_text("2026-07-04")[0]
        == "2026-07-04  Saturday · signed 2026-07-05 08:15 · chapter The Lofoten summer"
    )
    found = day_json("2026-07-04")["chapter"]
    summer = next(line for line in lb.lines() if line["payload"].get("name") == SUMMER)
    assert found == {"name": SUMMER, "line": summer["id"], "from": "2026-06-20", "to": "2026-08-09"}
    code, out, _err = run("show", "2026-07-04")
    assert (
        code == 0
        and out.splitlines()[0] == "2026-07-04  signed 2026-07-05 08:15 · chapter The Lofoten summer"
    )


def test_each_day_of_a_chapter_is_in_it_and_the_days_around_it_are_not(lb: Logbook):
    assert day_json("2026-06-20")["chapter"]["name"] == SUMMER
    assert day_json("2026-08-09")["chapter"]["name"] == SUMMER
    assert day_json("2026-08-10")["chapter"] == {
        "name": ASHORE,
        "line": day_json("2026-08-10")["chapter"]["line"],
        "from": "2026-08-10",
        "to": None,
    }
    assert day_json("2026-12-24")["chapter"]["name"] == ASHORE  # open: every day on
    outside = day_json("2026-06-19")
    assert "chapter" not in outside  # a day in no chapter: the Day's object as it was (SPEC §3.2.7)
    assert "chapter" not in day_text("2026-06-19")[0]


def test_a_closed_chapter_ends_on_its_last_day(lb: Logbook, monkeypatch: pytest.MonkeyPatch):
    pin(monkeypatch, "2026-10-01T09:00:00Z")
    chapter.close(lb, "2026-09-30")
    assert day_json("2026-09-30")["chapter"]["to"] == "2026-09-30"
    assert "chapter" not in day_json("2026-10-01")


def test_two_standing_chapters_on_one_day_show_the_later_and_say_so(lb: Logbook):
    """Rule 4: a writer refuses the overlap, so this is two writers' record; a reader shows the later
    by `from`, then `seq`, and marks the clash."""
    lb.append("2026-09-07T08:00:00Z", "manual", "chapter", 2, {"schema": "chapter/v1", "name": "The yard",
              "from": "2026-09-01", "rules": ""})  # fmt: skip
    head = day_text("2026-09-02")[0]
    assert head.endswith(f"· chapter The yard, clashes with {ASHORE}")
    found = day_json("2026-09-02")["chapter"]
    assert found["name"] == "The yard" and [c["name"] for c in found["clash"]] == [ASHORE]


# -- the reviews, on the day they are about ------------------------------------------------------------------


def test_a_review_is_on_the_day_it_is_about_with_the_goal_s_current_text(lb: Logbook):
    found = day_json("2026-08-31")
    review = next(line for line in lb.lines() if line["kind"] == "review")
    assert found["reviews"] == [
        {
            "line": review["id"],
            "goal": SECOND_GOAL,
            "goal_text": SECOND_TEXT,
            "disposition": "let go",
            "period": "month",
            "note": NOTE,
            "recorded_at": "2026-10-11T18:30:00Z",
        }
    ]
    rows = day_text("2026-08-31")
    assert f"  reviews       let go · month · {SECOND_TEXT} · {NOTE} · written 2026-10-11 20:30" in rows
    assert "reviews" not in day_json("2026-10-11")  # not on the day it was written


def test_a_review_of_the_earlier_line_shows_the_reworded_goal(lb: Logbook, monkeypatch: pytest.MonkeyPatch):
    pin(monkeypatch, "2026-06-30T19:00:00Z")
    goals.review(lb, FIRST_GOAL, "advancing", "month")
    (row,) = day_json("2026-06-30")["reviews"]
    assert (row["goal"], row["goal_text"], row["disposition"]) == (FIRST_GOAL, SECOND_TEXT, "advancing")
    assert f"  reviews       advancing · month · {SECOND_TEXT}" in day_text("2026-06-30")  # written that day


def test_the_later_of_two_reviews_for_one_period_stands_and_a_retracted_one_is_not_shown(lb: Logbook):
    """The writer dedupes on (goal, period, day); two writers may still leave two. The later stands;
    retract it and the earlier is the day's again. Another period is another verdict, shown too."""
    later = lb.append("2026-08-31T21:00:00Z", "manual", "review", 2, {"schema": "review/v1",
                      "goal": FIRST_GOAL, "disposition": "stalled", "period": "month"})  # fmt: skip
    assert [r["disposition"] for r in day_json("2026-08-31")["reviews"]] == ["stalled"]
    lb.retract(later["seq"], "said twice")
    assert [r["disposition"] for r in day_json("2026-08-31")["reviews"]] == ["let go"]
    lb.append("2026-08-31T21:30:00Z", "manual", "review", 2, {"schema": "review/v1", "goal": SECOND_GOAL,
              "disposition": "stalled", "period": "year"})  # fmt: skip
    assert [r["disposition"] for r in day_json("2026-08-31")["reviews"]] == ["let go", "stalled"]


def test_a_review_follows_the_record_s_day_start(lb: Logbook, monkeypatch: pytest.MonkeyPatch):
    lb.set_meta(day_start="06:00")
    pin(monkeypatch, "2026-10-12T07:00:00Z")
    goals.review(lb, SECOND_GOAL, "superseded", "day", None, "2026-09-01T05:30:00+02:00")
    assert [r["disposition"] for r in day_json("2026-08-31")["reviews"]] == ["let go", "superseded"]
    assert "reviews" not in day_json("2026-09-01")


def test_show_lists_a_review_with_the_goal_s_text(lb: Logbook):
    code, out, err = run("show", "2026-08-31")
    assert code == 0, err
    assert f"review     manual         let go · month · {SECOND_TEXT}" in out


# -- goals and chapters, as lines ----------------------------------------------------------------------------


def test_a_goal_line_is_on_the_day_it_was_written_marked_when_superseded(lb: Logbook):
    first = day_json("2026-01-04")["goals"]
    assert first == [
        {
            "line": FIRST_GOAL,
            "text": FIRST_TEXT,
            "horizon": "year",
            "from": "2026-01-01",
            "until": None,
            "superseded": SECOND_GOAL,
        }
    ]
    assert f"  goal          {FIRST_TEXT}  (year, from 2026-01-01) · superseded" in day_text("2026-01-04")
    rows = day_text("2026-03-15")
    assert f"  goal          {SECOND_TEXT}  (year, from 2026-01-01, until 2026-12-31)" in rows
    code, out, _err = run("show", "2026-01-04")
    assert code == 0 and f"{FIRST_TEXT}  (year, from 2026-01-01) · superseded by #2" in out
    assert "goals" not in day_json("2026-01-05")


def test_a_chapter_line_is_on_the_day_it_was_named(lb: Logbook):
    found = day_json("2026-09-06")
    assert [(c["name"], c["from"], c["to"], c["superseded"]) for c in found["chapters"]] == [
        (SUMMER, "2026-06-20", "2026-08-09", None),
        (ASHORE, "2026-08-10", None, None),
    ]
    rows = day_text("2026-09-06")
    assert rows[0].endswith(f"· chapter {ASHORE}")
    assert f"  chapter       {SUMMER}  2026-06-20 {DASH} 2026-08-09" in rows
    assert f"  chapter       {ASHORE}  2026-08-10 {DASH}" in rows
    code, out, _err = run("show", "2026-09-06")
    assert code == 0 and f"{SUMMER}  2026-06-20 {DASH} 2026-08-09" in out


# -- the gate -----------------------------------------------------------------------------------------------


def test_under_a_ceiling_of_1_the_day_shows_no_chapter_review_or_goal(lb: Logbook):
    """Every one of these lines is tier 2: where a line may travel, not who wrote it."""
    for day in ("2026-07-04", "2026-08-31", "2026-01-04", "2026-09-06"):
        found = day_reader.read(lb, day, tiers=(1,))
        assert not {"chapter", "reviews", "goals", "chapters"} & set(found), day
    assert day_reader.read(lb, "2026-08-31", tiers=(1, 2))["reviews"]


def test_the_serve_page_shows_the_chapter_and_the_reviews(lb: Logbook):
    page = serve.Site(lb).page_day("2026-08-31")
    assert f"chapter {ASHORE}" in page
    assert "<h2>Reviews</h2>" in page and "written 2026-10-11 20:30" in page and SECOND_TEXT in page
    summer = serve.Site(lb).page_day("2026-01-04")
    assert "<h2>Goals and chapters</h2>" in summer and "superseded" in summer
    gated = serve.Site(lb, tiers=(1,)).page_day("2026-08-31")
    assert ASHORE not in gated and "Reviews" not in gated and NOTE not in gated
