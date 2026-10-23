"""`logbook dream chapter [ID]` and the chapter's turn in `dream --catch-up` (RFC 0036, unit `chapter`, the
amendment of 2026-10-21): a model reads one chapter the owner named, open or closed, from the month drafts it
spans or the week drafts where no month draft exists, never the raw lines, and writes its arc, its rules,
what it held and what it closed. The catch-up dreams a chapter on the first close after it closes, after the
month, and again only when what it reads changed.

On the synthetic fortnight of `dream_fortnight.py` (8 to 21 June 2026), the chapter "Ashore, fixing things"
named over it; the endpoint is the in-process fake of `test_dream_month` and no test opens a connection.
Nobody here exists."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from dream_fortnight import (
    DREAM_ENTRY,
    GOAL_READ,
    MESSAGE_TEXT,
    NOTE_HOME,
    run_cli,
    set_dream_entry,
    week_answer,
)
from test_dream_month import chapter_answer, dreamed_days, fake_arcs, june, today_is

from logbook.contrib import dream, dream_chapter, dream_month
from logbook.core import chapter, drafts, goals
from logbook.core.store import Logbook

NAME = "Ashore, fixing things"
RULES = "What counts: the engine rebuilt, the mooring sorted, one weekend a month on the water anyway."


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    return june(tmp_path, monkeypatch)


def at(monkeypatch: pytest.MonkeyPatch, stamp: str) -> None:
    """The clock the chapter writers read (`goals.now`), pinned."""
    instant = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(UTC)
    monkeypatch.setattr(goals, "now", lambda: instant)


def opened(
    monkeypatch: pytest.MonkeyPatch, lb: Logbook, first: str = "2026-06-08", to: str | None = None
) -> str:
    at(monkeypatch, "2026-06-08T05:00:00Z")
    made = chapter.open_chapter(lb, NAME, first, to, RULES)
    assert made.line is not None
    return str(made.line["id"])


def chapters(lb: Logbook) -> list[dict[str, Any]]:
    return [
        line
        for line in Logbook(lb.root).lines()
        if line["kind"] == drafts.KIND and line["payload"]["unit"] == drafts.UNIT_CHAPTER
    ]


def _ids_of_days(lb: Logbook, first: int, last: int) -> set[str]:
    with lb.index() as idx:
        return {str(x["id"]) for d in range(first, last + 1) for x in idx.day(f"2026-06-{d:02d}")}


# -- an open chapter, from the week drafts -----------------------------------------------------------------


def test_an_open_chapter_is_drafted_from_its_week_drafts_where_no_month_draft_exists(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    seen = fake_arcs(monkeypatch)
    first_line = opened(monkeypatch, lb)
    dreamed_days(monkeypatch, lb)  # the days and both weeks, at the close of Monday 22 June
    today_is(monkeypatch, "2026-06-23")
    code, out, err = run_cli("dream", "chapter")  # the chapter yesterday was in
    assert code == 0, out + err
    assert f"{NAME} (2026-06-08 {chapter.EN_DASH} 2026-06-22): dreamed as #" in out
    assert "held      15 days · 3 signed · 0 months and 2 weeks drafted" in out
    (material,) = seen["chapters"]
    assert material["months"] == [] and [w["week"] for w in material["weeks"]] == ["2026-W24", "2026-W25"]
    assert material["chapter"]["rules"] == {"text": RULES} and material["chapter"]["state"] == "open"
    sent = json.dumps(seen["calls"][-1])
    assert MESSAGE_TEXT not in sent and NOTE_HOME not in sent, "never a raw line's text"
    (line,) = chapters(lb)
    payload = line["payload"]
    assert payload["subject"] == [first_line] and drafts.validate(payload) == []
    assert payload["extra"]["prompt"] == dream_chapter.PROMPT_NAME
    allowed = _ids_of_days(lb, 8, 22)
    for segment in payload["segments"]:
        assert "unsupported" in segment or set(segment["evidence"]) <= allowed, "evidence on the stretch"
    assert payload["extra"]["parts"][:2] == ["arc", "rule"]


def test_a_week_draft_s_sentence_off_the_stretch_is_not_given(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """A chapter that begins on Wednesday 17 June is given only the sentences of the weeks' drafts whose
    every line is on the 17th or after."""

    def later(material: dict[str, Any]) -> dict[str, Any]:
        found = week_answer(material)
        thursday = next((d for d in material["days"] if d["day"] == "2026-06-18"), None)
        refs = [r for t in (thursday or {}).get("draft") or [] for r in t["ref"]][:1]
        if refs:
            found["personal"] = [{"text": "Home again on Thursday.", "evidence": refs}]
        return found

    seen = fake_arcs(monkeypatch, week=later)
    opened(monkeypatch, lb, first="2026-06-17")
    dreamed_days(monkeypatch, lb)
    today_is(monkeypatch, "2026-06-23")
    code, out, err = run_cli("dream", "chapter", NAME)
    assert code == 0, out + err
    with lb.index() as idx:
        allowed = {str(x["id"]) for d in range(17, 23) for x in idx.day(f"2026-06-{d:02d}")}
    (material,) = seen["chapters"]
    assert [w["week"] for w in material["weeks"]] == ["2026-W25"], "the week of 8 June is off the stretch"
    line = chapters(lb)[0]
    allowed |= set(line["payload"]["subject"])  # the chapter's line: its rules are cited by it
    for segment in line["payload"]["segments"]:
        assert "unsupported" in segment or set(segment["evidence"]) <= allowed
    given = {r for w in material["weeks"] for t in w["drafted"] for r in t["ref"]}
    assert given, "the week of 15 June gives what rests on the 17th and after"


# -- a closed chapter, from the month draft, by the catch-up ------------------------------------------------


def test_a_closed_chapter_is_dreamed_by_the_first_close_after_it_closes_after_the_month(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    seen = fake_arcs(monkeypatch)
    first_line = opened(monkeypatch, lb)
    dreamed_days(monkeypatch, lb)
    read_goal = next(
        x for x in Logbook(lb.root).lines() if x["kind"] == "goal" and x["payload"]["text"] == GOAL_READ
    )
    lb.append(
        "2026-06-19T10:00:00Z",
        "manual",
        "review",
        2,
        {"schema": "review/v1", "goal": str(read_goal["id"]), "disposition": "let go", "period": "month"},
    )
    at(monkeypatch, "2026-06-21T18:00:00Z")  # closed on its last day, an evening with lines of its own
    closing = chapter.close(lb, "2026-06-21")
    today_is(monkeypatch, "2026-07-01")
    code, out, err = run_cli("dream", "--catch-up")
    assert code == 0, out + err
    rows = out.splitlines()
    month_row = next(i for i, r in enumerate(rows) if r.startswith("2026-06  "))
    chapter_row = next(i for i, r in enumerate(rows) if r.startswith(f"chapter {NAME}  "))
    assert "dreamed" in rows[month_row] and "dreamed" in rows[chapter_row] and month_row < chapter_row
    material = seen["chapters"][-1]
    assert [m["month"] for m in material["months"]] == ["2026-06"] and material["weeks"] == []
    assert material["chapter"]["state"] == "closed" and material["closed"]["chapter"]["to"] == "2026-06-21"
    assert [(g["text"], g["disposition"]) for g in material["closed"]["goals"]] == [(GOAL_READ, "let go")]
    (line,) = chapters(lb)
    assert line["payload"]["subject"] == [str(closing["id"]), first_line], "the standing line first"
    assert line["payload"]["extra"]["numbers"]["closed"][0]["disposition"] == "let go"

    code, out, _err = run_cli("dream", "--catch-up")
    assert f"chapter {NAME}  unchanged" in out and len(seen["chapters"]) == 1, "nothing sent, nothing written"


def test_closing_a_chapter_dreamed_while_open_dreams_it_again_superseding_the_open_draft(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    fake_arcs(monkeypatch)
    opened(monkeypatch, lb)
    dreamed_days(monkeypatch, lb)
    today_is(monkeypatch, "2026-06-23")
    assert run_cli("dream", "chapter")[0] == 0
    (open_draft,) = chapters(lb)
    at(monkeypatch, "2026-06-23T18:00:00Z")
    chapter.close(lb, "2026-06-21")
    today_is(monkeypatch, "2026-06-24")
    _code, out, err = run_cli("dream", "--catch-up")
    assert f"chapter {NAME}  dreamed" in out, out + err
    assert chapters(lb)[-1]["payload"]["supersedes"] == open_draft["id"]
    found = dream_chapter.which(Logbook(lb.root), NAME, date(2026, 6, 24))
    assert dream_chapter.standing_of(lb, found.chain)["id"] == chapters(lb)[-1]["id"]


def test_a_chapter_no_draft_speaks_of_is_refused_and_empty_in_the_catch_up(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    seen = fake_arcs(monkeypatch)
    at(monkeypatch, "2026-06-30T18:00:00Z")
    chapter.open_chapter(lb, "May at home", "2026-05-01", "2026-05-31")
    today_is(monkeypatch, "2026-07-01")
    code, _out, err = run_cli("dream", "chapter", "May at home")
    assert code == 2 and "no month or week draft says anything of" in err
    _code, out, _err = run_cli("dream", "--catch-up")
    assert "chapter May at home  empty" in out and seen["chapters"] == []


# -- the rules ----------------------------------------------------------------------------------------------


def test_a_figure_beside_a_name_is_marked_in_a_chapter_too(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    def counted(material: dict[str, Any]) -> dict[str, Any]:
        found = chapter_answer(material)
        found["held"].append(
            {
                "text": f"{material['held']['days']} days with Kari Nordmann.",
                "evidence": material["chapter"]["ref"],
            }
        )
        return found

    fake_arcs(monkeypatch, chapter=counted)
    opened(monkeypatch, lb)
    dreamed_days(monkeypatch, lb)
    today_is(monkeypatch, "2026-06-23")
    code, out, err = run_cli("dream", "chapter")
    assert code == 0, out + err
    payload = chapters(lb)[0]["payload"]
    assert payload["extra"]["marked"] == {dream_month.BESIDE_A_NAME: 1}
    assert [s["text"] for s in payload["segments"] if s.get("unsupported")] == [dream.HELD]
    assert "days with Kari Nordmann" not in json.dumps(payload)


def test_a_chapter_above_the_ceiling_is_refused_before_anything_is_sent(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    seen = fake_arcs(monkeypatch)
    opened(monkeypatch, lb)
    dreamed_days(monkeypatch, lb)
    calls = len(seen["calls"])
    set_dream_entry(lb.root, {"max_tier": 1, "until": "2026-12-31"})
    today_is(monkeypatch, "2026-06-23")
    code, _out, err = run_cli("dream", "chapter")
    assert code == 2 and "above max_tier 1" in err and len(seen["calls"]) == calls
    set_dream_entry(lb.root, None)
    code, _out, err = run_cli("dream", "chapter")
    assert code == 2 and "dream" in err and len(seen["calls"]) == calls and chapters(lb) == []


def test_a_chapter_is_named_by_its_id_its_seq_or_its_name(lb: Logbook, monkeypatch: pytest.MonkeyPatch):
    first_line = opened(monkeypatch, lb)
    seq = next(x["seq"] for x in Logbook(lb.root).lines() if x["id"] == first_line)
    today = date(2026, 6, 23)
    for text in (first_line, str(seq), f"#{seq}", NAME.upper(), None):
        assert dream_chapter.which(lb, text, today).chain == (first_line,)
    with pytest.raises(ValueError, match="no chapter is"):
        dream_chapter.which(lb, "The Lofoten summer", today)
    with pytest.raises(dream_chapter.NotBegun):
        dream_chapter.which(lb, NAME, date(2026, 6, 8))


def test_dream_chapter_json_prints_the_draft_found_by_any_of_its_lines(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    fake_arcs(monkeypatch)
    opened(monkeypatch, lb)
    dreamed_days(monkeypatch, lb)
    today_is(monkeypatch, "2026-06-23")
    code, out, err = run_cli("dream", "chapter", NAME, "--json")
    assert code == 0, err
    found = json.loads(out)
    assert found["unit"] == "chapter" and found["draft_withheld"] is None
    assert found["draft"]["segments"][0]["part"] == "arc" and found["draft"]["malformed"] == []
    assert all(s["supported"] for s in found["draft"]["segments"]), "the evidence is on the stretch"
    set_dream_entry(lb.root, {**DREAM_ENTRY, "max_tier": 1})
    draft, withheld = dream_chapter.for_chapter(lb, dream_chapter.which(lb, NAME, date(2026, 6, 23)))
    assert draft is None and withheld is not None and "dream chapter" in withheld["why"]


# -- what the review found ----------------------------------------------------------------------------------


def test_a_closed_chapter_above_the_ceiling_is_held_back_by_the_catch_up_never_refused(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    fake_arcs(monkeypatch)
    opened(monkeypatch, lb)
    at(monkeypatch, "2026-06-21T18:00:00Z")
    chapter.close(lb, "2026-06-21")
    set_dream_entry(lb.root, {"max_tier": 1, "until": "2026-12-31"})
    today_is(monkeypatch, "2026-06-22")
    _code, out, err = run_cli("dream", "--catch-up")
    row = next(r for r in out.splitlines() if r.startswith(f"chapter {NAME}  "))
    assert "empty" in row and "held back" in row and "above max_tier 1" in row, out + err
    assert chapters(lb) == []


def test_a_chapter_closed_ahead_is_told_as_closed_and_read_up_to_yesterday(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    seen = fake_arcs(monkeypatch)
    opened(monkeypatch, lb)
    dreamed_days(monkeypatch, lb)
    at(monkeypatch, "2026-06-22T18:00:00Z")
    chapter.close(lb, "2026-07-15")
    today_is(monkeypatch, "2026-06-23")
    code, out, err = run_cli("dream", "chapter")
    assert code == 0, out + err
    material = seen["chapters"][-1]
    assert material["chapter"]["state"] == "closed" and material["chapter"]["read_to"] == "2026-06-22"
    assert material["closed"]["chapter"]["to"] == "2026-07-15"
    assert "closing on 2026-07-15, read up to yesterday" in seen["prompts"][-1]


def test_a_chapter_closed_before_the_window_is_dreamed_again_from_its_month_draft(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """A chapter of the first week of the fortnight is dreamed from its week draft by the close of 22 June;
    the first close of July dreams June, and the chapter again from June's draft, though its last day has
    left the window by then."""
    seen = fake_arcs(monkeypatch)
    opened(monkeypatch, lb, to="2026-06-14")
    dreamed_days(monkeypatch, lb)  # the close of 22 June: the days, the weeks, and the chapter
    assert [w["week"] for w in seen["chapters"][0]["weeks"]] == ["2026-W24"]
    today_is(monkeypatch, "2026-07-01")
    _code, out, err = run_cli("dream", "--catch-up")
    assert f"chapter {NAME}  dreamed" in out, out + err
    assert [m["month"] for m in seen["chapters"][-1]["months"]] == ["2026-06"]
    assert chapters(lb)[-1]["payload"]["supersedes"] == chapters(lb)[0]["id"]
