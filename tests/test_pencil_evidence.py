"""No pencil without evidence: wherever a model's draft lands outside the Day's own Draft block (the
letter, the week's one proposal under Today and on the week page, the intention it prefills, the verdict
a week's draft proposes for a goal, the decisions of a call on the morning's loose ends, the chapter's
sentence on Life, what was drafted about a person), a model's sentence is shown only with its pencil
mark and the ids of the lines it cites, and only when every one of them is a line the page's gate reads.
A sentence with no evidence, or with evidence the gate does not read, is not shown at all.

On the synthetic fortnight of `tests/letter_record.py` (Ines Nordmann of Oslo, Kari and Ola Nordmann, who
do not exist) and on hand-made drafts; line ids here are invented."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from dream_fortnight import MODEL, run_cli
from letter_record import FROM, STORY, TO, record
from persona import utc

from logbook.contrib import day_rhythm, door_life, door_people, letter, serve, week_page
from logbook.core import drafts
from logbook.core.store import Logbook

ZONE = ZoneInfo("Europe/Oslo")
CITED = "019cadd3-6bc0-7dcd-9133-00000000c17e"  # an invented line id a sentence cites
SHORT = drafts.short_id(CITED)
WORDS = "Send Kari Nordmann the harbour map."  # a model's sentence


def _link(text: str, path: str) -> str:
    return f'<a href="{path}">{text}</a>'


# -- the helpers every surface reads --------------------------------------------------------------------


def test_a_sentence_is_shown_only_with_the_ids_it_cites() -> None:
    assert drafts.pencil_ids({"text": WORDS, "evidence": [CITED]}) == [CITED]
    assert drafts.pencil_ids({"text": WORDS, "supported": True, "evidence": [CITED]}) == [CITED]
    assert drafts.pencil_ids({"text": WORDS, "unsupported": True}) is None
    assert drafts.pencil_ids({"text": WORDS, "supported": False, "evidence": [CITED]}) is None
    assert drafts.pencil_ids({"text": WORDS, "supported": True, "evidence": []}) is None
    assert drafts.pencil_ids({"text": WORDS, "evidence": []}) is None
    assert drafts.pencil_ids({"text": " ", "evidence": [CITED]}) is None
    assert drafts.pencil_ids({"text": WORDS, "evidence": [CITED, 7]}) is None, "an id is a string"
    assert drafts.pencil_ids({"text": WORDS, "supported": True, "evidence": CITED}) == [CITED], "one, bare"


def test_evidence_is_readable_only_when_every_line_is_through_the_gate() -> None:
    lines: dict[str, Any] = {"a": {"id": "a", "tier": 1}, "b": {"id": "b", "tier": 3}}
    assert drafts.readable(lines, ["a"], [1, 2], frozenset())
    assert not drafts.readable(lines, ["a", "b"], [1, 2], frozenset()), "a tier-3 line on a tier-2 page"
    assert drafts.readable(lines, ["a", "b"], None, frozenset()), "a page that reads every tier"
    assert not drafts.readable(lines, ["a", "c"], None, frozenset()), "a line the record does not hold"
    assert not drafts.readable(lines, ["a"], None, frozenset({"a"})), "a retracted line"
    assert not drafts.readable(lines, [], None, frozenset()), "no evidence is none to read"


# -- the letter -----------------------------------------------------------------------------------------


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    return record(tmp_path, monkeypatch)


def _letter(lb: Logbook, out: Path) -> tuple[str, str]:
    code, _, err = run_cli("export", "letter", FROM, TO, "--out", str(out))
    assert code == 0, err
    return (out / letter.HTML_FILE).read_text("utf-8"), (out / letter.MARKDOWN_FILE).read_text("utf-8")


def _story_evidence(lb: Logbook, day: str) -> str:
    """The id the day's story cites (`letter_record`): the day's standing draft's first segment's."""
    found = [
        line
        for line in lb.lines()
        if line["kind"] == drafts.KIND and line["payload"].get("unit") == drafts.UNIT_DAY
        and line["payload"].get("subject") == day
    ]  # fmt: skip
    return str(found[-1]["payload"]["segments"][0]["evidence"][0])


def test_every_story_sentence_in_a_letter_names_the_lines_it_rests_on(lb: Logbook, tmp_path: Path) -> None:
    html, md = _letter(lb, tmp_path / "out")
    day = "2026-06-16"
    short = drafts.short_id(_story_evidence(lb, day))
    sentence = re.search(rf"<p>{re.escape(f'{STORY} {day}.')}(.*?)</p>", html, re.S)
    assert sentence is not None
    assert f"{drafts.EVIDENCE} [" in sentence.group(1) and short in sentence.group(1)
    line = next(text for text in md.splitlines() if f"{STORY} {day}." in text)
    assert f"{drafts.EVIDENCE} [" in line and short in line, line
    for pencil in re.findall(r'<div class="pencil">(.*?)</div>', html, re.S):
        assert MODEL in pencil and "pencil" in pencil
        for p in re.findall(r"<p>(.*?)</p>", pencil, re.S):
            assert f"{drafts.EVIDENCE} [" in p, p


def test_a_story_sentence_that_rests_on_a_line_above_the_letter_s_tier_is_not_in_it(
    lb: Logbook, tmp_path: Path
) -> None:
    """A later draft of a signed day: one sentence on a line the letter reads, one on the tier-3
    workout. The first goes in with its evidence; the second, its words and its evidence, never."""
    day = "2026-06-16"
    lines = list(lb.lines())
    workout = next(
        line for line in lines if line["kind"] == "health" and line["payload"].get("type") == "workout"
    )
    assert int(workout["tier"]) == 3
    plain = _story_evidence(lb, day)
    payload: dict[str, Any] = {
        "schema": drafts.SCHEMA, "unit": drafts.UNIT_DAY, "subject": day, "read_head": "0" * 64,
        "read_count": 1, "language": "en",
        "segments": [{"text": "The lake was still.", "evidence": [plain]},
                     {"text": "Rowing at dawn, hard.", "evidence": [str(workout["id"])]}],
        "extra": {"prompt": "test/1", "parts": ["day", "day"], "policy_version": "0" * 64},
    }  # fmt: skip
    assert drafts.validate(payload) == []
    lb.append(at=utc(day, "21:45"), source=f"model:{MODEL}", kind=drafts.KIND, tier=2, payload=payload)
    html, md = _letter(lb, tmp_path / "out")
    assert "The lake was still." in html and "The lake was still." in md, "the premise: the draft is read"
    assert "Rowing at dawn" not in html and "Rowing at dawn" not in md
    assert drafts.short_id(str(workout["id"])) not in html and drafts.short_id(str(workout["id"])) not in md


# -- Today: the week's one proposal, and the decisions of a call ------------------------------------------


def test_the_week_s_proposal_under_today_carries_its_lines_or_is_not_shown() -> None:
    found = {"text": WORDS, "supported": True, "evidence": [CITED], "model": MODEL, "line": "d" * 8}
    shown = day_rhythm.proposal_html(found, _link)
    assert WORDS in shown and MODEL in shown and f"{drafts.EVIDENCE} [" in shown and SHORT in shown
    assert f'href="/line/{CITED}"' in shown
    assert day_rhythm.proposal_html({**found, "supported": False}, _link) == ""


@pytest.mark.parametrize(
    "segment",
    [
        {"part": "next_week", "text": WORDS, "supported": False, "evidence": [], "why": None},
        {"part": "next_week", "text": WORDS, "supported": True, "evidence": []},
    ],
)
def test_a_week_s_proposal_that_cites_no_line_is_none_under_today(
    segment: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The proposal Today reads (`week_proposal`): none when its sentence is unsupported or cites no
    line, so nothing of it reaches the page; the one that cites its lines carries them."""
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    week = {"line": "d" * 64, "model": f"model:{MODEL}", "segments": [segment]}
    monkeypatch.setattr(drafts, "by_unit", lambda *a, **k: {"2026-W24": [{"id": "x"}]})
    monkeypatch.setattr(drafts, "for_unit", lambda *a, **k: (week, None))
    assert day_rhythm.week_proposal(lb, "2026-06-16", None) is None
    week["segments"] = [{**segment, "supported": True, "evidence": [CITED]}]
    found = day_rhythm.week_proposal(lb, "2026-06-16", None)
    assert found is not None and found["evidence"] == [CITED]


def _call(*segments: dict[str, Any]) -> dict[str, Any]:
    return {"transcript": CITED, "model": f"model:{MODEL}", "segments": list(segments)}


def test_a_call_s_decision_on_the_loose_ends_names_its_line_or_is_not_shown() -> None:
    made = {"part": "decisions", "text": "Keep the berth in Vollen.", "supported": True, "where": "12:30"}
    guessed = {"part": "decisions", "text": "Sell the boat.", "supported": False, "why": None}
    data = {"syntheses": [_call(made, guessed)]}
    assert day_rhythm.decisions(data) == [(data["syntheses"][0], made)], "an unsupported decision is none"
    summary, body = day_rhythm.loose_ends([], data, "2026-06-16", ZONE, lambda c: "", link=_link)
    assert "1 decision" in summary
    assert "Keep the berth in Vollen." in body and "Sell the boat." not in body
    assert f"{drafts.EVIDENCE} [" in body and SHORT in body
    assert day_rhythm.loose_ends([], {"syntheses": [_call(guessed)]}, "2026-06-16", ZONE, lambda c: "") == (
        "",
        "",
    )


# -- the week page: its proposal, the intention it prefills, a goal's proposed verdict -------------------


@pytest.fixture
def site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> serve.Site:
    found = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(found.root))
    return serve.Site(found)


def _week(segment: dict[str, Any]) -> dict[str, Any]:
    return {"line": "d" * 64, "model": f"model:{MODEL}", "segments": [{"part": "next_week", **segment}]}


def test_the_week_page_s_proposal_carries_its_lines_or_is_not_shown(site: serve.Site) -> None:
    shown = week_page.proposal_html(site, _week({"text": WORDS, "supported": True, "evidence": [CITED]}), [])
    assert WORDS in shown and "Pencil" in shown and SHORT in shown
    for segment in (
        {"text": WORDS, "supported": False, "evidence": [], "why": None},
        {"text": WORDS, "supported": True, "evidence": []},
    ):
        assert week_page.proposal_html(site, _week(segment), []) == "", segment


def test_the_intention_is_prefilled_only_with_a_proposal_s_lines_beside_it(site: serve.Site) -> None:
    words, beside = week_page.prefill(
        site, _week({"text": WORDS, "supported": True, "evidence": [CITED]}), []
    )
    assert words == WORDS and SHORT in beside and f"/line/{CITED}" in beside
    assert week_page.prefill(site, _week({"text": WORDS, "supported": True, "evidence": []}), []) == ("", "")
    assert week_page.prefill(site, _week({"text": WORDS, "supported": False, "evidence": []}), []) == ("", "")


def test_a_goal_s_proposed_verdict_carries_its_lines_or_says_only_the_verdict(site: serve.Site) -> None:
    segment = {"part": "goals", "text": "Two sails this week.", "supported": True, "evidence": [CITED]}
    shown = week_page.verdict_html(site, {"disposition": "advancing", "segment": 0}, [segment], [])
    assert "advancing" in shown and "Two sails this week." in shown and SHORT in shown
    bare = week_page.verdict_html(
        site, {"disposition": "advancing", "segment": 0}, [{**segment, "evidence": []}], []
    )
    assert "Two sails this week." not in bare and SHORT not in bare


# -- Life's chapter, and a person's page ----------------------------------------------------------------


def test_the_chapter_s_sentence_on_life_carries_its_lines(site: serve.Site) -> None:
    shown = door_life.chapter_pencil(site, (WORDS, MODEL, (CITED,)))
    assert WORDS in shown and MODEL in shown and SHORT in shown and f"/line/{CITED}" in shown
    assert door_life.chapter_pencil(site, (WORDS, MODEL, ())) == ""
    assert door_life.chapter_pencil(site, None) == ""


def test_what_a_model_drafted_about_a_person_is_shown_only_with_its_lines(site: serve.Site) -> None:
    drafted = door_people.Drafted(
        f"model:{MODEL}",
        "",
        [(WORDS, [CITED], False), ("Kari is a sailor.", [], False), ("held", [], True)],
    )
    shown = door_people._drafted_html(site, drafted)
    assert WORDS in shown and SHORT in shown
    assert "Kari is a sailor." not in shown, "a sentence with no lines"
    assert json.dumps(shown)  # the page is text


# -- the blind review: the gate on the week's evidence, the folded journey draft, the letter's count -----


def _week_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Logbook, str, str]:
    """A record with a tier-2 note and a tier-3 workout on the Wednesday of 2026-W24."""
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    note = lb.append(at="2026-06-10T10:00:00Z", source="manual", kind="note", tier=2,
                     payload={"schema": "note/v1", "text": "Harbour."})  # fmt: skip
    workout = lb.append(at="2026-06-10T06:00:00Z", source="manual", kind="health", tier=3,
                        payload={"schema": "health/v1", "type": "workout"})  # fmt: skip
    return lb, str(note["id"]), str(workout["id"])


def test_the_week_s_lines_are_read_through_the_page_s_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A week draft is checked against the week's lines the page reads: a tier-3 line is not one of a
    tier-2 page's, so a sentence that cites it is unsupported there, and neither it nor the id shows."""
    lb, note, workout = _week_record(tmp_path, monkeypatch)
    seen: list[set[str]] = []

    def for_unit(found: Any, on: Any, *args: Any, **kwargs: Any) -> tuple[None, None]:
        seen.append(set(on))
        return None, None

    monkeypatch.setattr(drafts, "by_unit", lambda *a, **k: {"2026-W24": [{"id": "x"}]})
    monkeypatch.setattr(drafts, "for_unit", for_unit)
    day_rhythm.week_proposal(lb, "2026-06-16", [1, 2])
    week_page.week_draft(serve.Site(lb, tiers=[1, 2]), "2026-W24")
    assert len(seen) == 2
    for on in seen:
        assert note in on and workout not in on, on
    seen.clear()
    day_rhythm.week_proposal(lb, "2026-06-16", None)
    assert workout in seen[0], "a page that reads every tier reads it"


def test_a_goal_s_proposed_verdict_without_its_lines_is_not_shown(site: serve.Site) -> None:
    segment = {"part": "goals", "text": "Two sails this week.", "supported": True, "evidence": []}
    assert week_page.verdict_html(site, {"disposition": "abandoned", "segment": 0}, [segment], []) == ""
    assert week_page.verdict_html(site, {"disposition": "abandoned"}, [], []) == ""
    shown = week_page.verdict_html(
        site, {"disposition": "advancing", "segment": 0}, [{**segment, "evidence": [CITED]}], []
    )
    assert "Pencil" in shown and SHORT in shown


def test_a_folded_draft_shows_no_sentence_without_its_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    """A journey's or a trip's draft, folded under its head on its page: its supported sentences with
    their ids, never an unsupported one (the Day's own Draft block alone does, RFC 0036 rule 6)."""
    monkeypatch.setattr(drafts, "head_text", lambda draft: "draft of journey")
    draft = {
        "segments": [
            {"text": "Three nights by the lake.", "evidence": [CITED], "supported": True, "why": None},
            {"text": "It rained every day.", "evidence": [], "supported": False, "why": None},
        ],
        "proposals": [],
        "earlier": [],
    }
    folded = serve._draft_folded(draft)
    assert "Three nights by the lake." in folded and SHORT in folded
    assert "It rained every day." not in folded and "unsupported" not in folded


def test_a_letter_counts_nothing_that_rests_above_its_tier(lb: Logbook, tmp_path: Path) -> None:
    """A sentence on the tier-3 workout that the dream would also hold (a figure beside a name) is
    neither shown nor counted: no `segments_unsupported` grows for it."""
    day = "2026-06-16"
    _letter(lb, tmp_path / "before")
    before = json.loads((tmp_path / "before" / letter.MANIFEST_FILE).read_text("utf-8"))["held_back"]
    workout = next(
        line for line in lb.lines() if line["kind"] == "health" and line["payload"].get("type") == "workout"
    )
    plain = _story_evidence(lb, day)
    payload: dict[str, Any] = {
        "schema": drafts.SCHEMA, "unit": drafts.UNIT_DAY, "subject": day, "read_head": "0" * 64,
        "read_count": 1, "language": "en",
        "segments": [{"text": f"{STORY} {day}.", "evidence": [plain]},
                     {"text": "Kari Nordmann 3 times on the rower.", "evidence": [str(workout["id"])]},
                     {"text": "Unsure.", "evidence": [str(workout["id"])], "unsupported": True}],
        "extra": {"prompt": "test/1", "parts": ["day", "day", "day"], "policy_version": "0" * 64},
    }  # fmt: skip
    payload["segments"][2].pop("evidence")
    lb.append(at=utc(day, "21:45"), source=f"model:{MODEL}", kind=drafts.KIND, tier=2, payload=payload)
    html, md = _letter(lb, tmp_path / "after")
    assert "rower" not in html and "rower" not in md
    after = json.loads((tmp_path / "after" / letter.MANIFEST_FILE).read_text("utf-8"))["held_back"]
    assert after.get("segments_unsupported", 0) - before.get("segments_unsupported", 0) <= 1, (before, after)
