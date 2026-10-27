"""`logbook dream week [DAY|YYYY-Www]` and the week's turn in `dream --catch-up` (RFC 0036, unit `week`):
a model reads one ISO week, once its Sunday is over, its seven days' drafts and its lines together, and
writes one draft line: the time by place, person and thread, the energy, the people who moved and the
promises open both ways, a review proposed for each goal, one proposal for next week and a personal
part. Every figure is the code's, computed from the lines; a sentence that writes another is marked.
On the synthetic fortnight of `dream_fortnight.py`; the endpoint is the in-process fake (`fake`) and no
test opens a connection. Nobody here exists."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from dream_fortnight import (
    DREAM_ENTRY,
    ENV,
    GOAL_READ,
    GOAL_SAIL,
    MESSAGE_TEXT,
    MODEL,
    NOTE_HOME,
    NOTE_ZURICH,
    OLA_PROMISE,
    PROMISE_ZURICH,
    W24,
    W25,
    fake,
    fortnight,
    run_cli,
    set_dream_entry,
    week_answer,
)
from persona import KARI, KARI_ID, resolution

from logbook.contrib import dream, dream_week
from logbook.core import drafts, policy
from logbook.core.store import Logbook

MONDAY_AFTER = (
    "2026-06-22"  # the close of Sunday 21 June: both weeks have ended, all their days in the window
)


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = fortnight(tmp_path / "lb")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(policy, "today", lambda: date(2026, 6, 20))
    _today(monkeypatch, MONDAY_AFTER)
    return lb


def _today(monkeypatch: pytest.MonkeyPatch, day: str) -> None:
    monkeypatch.setattr(dream, "today", lambda: date.fromisoformat(day))


def _weeks(lb: Logbook) -> list[dict[str, Any]]:
    return [
        line
        for line in Logbook(lb.root).lines()
        if line["kind"] == drafts.KIND and line["payload"]["unit"] == drafts.UNIT_WEEK
    ]


def _week(lb: Logbook, week: str) -> dict[str, Any]:
    (line,) = [line for line in _weeks(lb) if line["payload"]["subject"] == week]
    return line


# -- a week only from its seven days -------------------------------------------------------------------------


def test_a_week_is_dreamed_only_from_its_seven_days_once_its_sunday_is_over(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    seen = fake(monkeypatch)
    _today(monkeypatch, "2026-06-21")  # Sunday: the week is not over
    code, _out, err = run_cli("dream", "week", W25)
    assert code == 2 and "which is not over" in err and _weeks(lb) == []
    code, _out, err = run_cli("dream", "week", "2026-06-17")  # a day of it names it as well
    assert code == 2 and "2026-W25 runs to Sunday 2026-06-21" in err
    code, _out, err = run_cli("dream", "week")  # the last week over is the one of 8 June
    assert code == 2 and "2026-W24 reads its seven days' drafts" in err and "dream day 2026-06-08" in err
    assert seen["weeks"] == [], "a week whose days are not dreamed is not sent"

    _today(monkeypatch, MONDAY_AFTER)  # the close of Sunday 21 June
    code, out, err = run_cli("dream", "--catch-up")
    assert f"{W24}  dreamed" in out and f"{W25}  dreamed" in out, out + err
    rows = out.splitlines()
    assert rows.index(next(r for r in rows if r.startswith(W24))) > rows.index(
        next(r for r in rows if r.startswith("2026-06-21"))
    ), "after the days, whose drafts it reads"
    assert len(_weeks(lb)) == 2 and len(seen["weeks"]) == 2
    w25 = seen["weeks"][1]
    assert [d["day"] for d in w25["days"]] == [f"2026-06-{d}" for d in range(15, 22)]
    assert all(d["draft"] for d in w25["days"]), "the seven days' drafts, each read"

    code, out, err = run_cli("dream", "--catch-up")  # a second run: nothing changed
    assert f"{W24}  unchanged" in out and f"{W25}  unchanged" in out, out + err
    assert len(_weeks(lb)) == 2 and len(seen["weeks"]) == 2, "nothing sent, nothing written"
    _today(monkeypatch, "2026-06-23")
    out = run_cli("dream", "--catch-up")[1]
    assert W24 not in out and f"{W25}  unchanged" in out, "its Monday left the window: not looked at"


def test_the_week_records_its_entry_and_is_dreamed_again_under_another(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    fake(monkeypatch)
    run_cli("dream", "--catch-up")
    before = _week(lb, W24)
    assert before["payload"]["extra"]["policy_version"] == policy.version(policy.dream_entry(lb.root))
    assert before["payload"]["extra"]["prompt"] == dream_week.PROMPT_NAME
    set_dream_entry(lb.root, {**DREAM_ENTRY, "until": "2026-11-30"})  # the same ceiling, another version
    _code, out, err = run_cli("dream", "--catch-up")
    assert f"{W24}  dreamed" in out and "dreamed under another dream entry" in out, out + err
    after = [line for line in _weeks(lb) if line["payload"]["subject"] == W24]
    assert after[-1]["payload"]["supersedes"] == before["id"]
    assert after[-1]["payload"]["extra"]["policy_version"] == policy.version(policy.dream_entry(lb.root))


def test_a_goal_written_or_reviewed_after_the_sunday_is_not_the_week_s(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """The week reads its goals as its Sunday left them: a goal written later is not one of them, a
    review written later does not close one, and neither changes what the week read."""
    seen = fake(monkeypatch)
    run_cli("dream", "--catch-up")
    goal = next(
        x for x in Logbook(lb.root).lines() if x["kind"] == "goal" and x["payload"]["text"] == GOAL_READ
    )
    lb.append(
        "2026-06-22T05:30:00Z",
        "manual",
        "goal",
        2,
        {"schema": "goal/v1", "text": "Swim every week.", "horizon": "quarter", "from": "2026-06-01"},
    )
    lb.append(
        "2026-06-22T05:31:00Z",
        "manual",
        "review",
        2,
        {"schema": "review/v1", "goal": goal["id"], "disposition": "let go", "period": "week"},
    )
    sent = len(seen["weeks"])
    _code, out, err = run_cli("dream", "--catch-up")
    assert f"{W24}  unchanged" in out and f"{W25}  unchanged" in out, out + err
    assert len(seen["weeks"]) == sent
    found = dream_week.material(lb, W25, "2026-06-15", "2026-06-21", policy.dream_entry(lb.root))
    assert {g["text"] for g in found.made.data["goals"]} == {GOAL_SAIL, GOAL_READ}


def test_a_day_of_the_week_dreamed_again_dreams_the_week_again(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    fake(monkeypatch)
    assert run_cli("dream", "--catch-up")[0] == 0
    before = _week(lb, W25)
    assert run_cli("dream", "day", "2026-06-19")[0] == 0  # a new draft of Friday: the week read another
    _code, out, err = run_cli("dream", "--catch-up")
    assert f"{W25}  dreamed" in out and "the week's lines are not the ones last dreamed" in out, out + err
    after = [line for line in _weeks(lb) if line["payload"]["subject"] == W25]
    assert len(after) == 2 and after[1]["payload"]["supersedes"] == before["id"]


# -- the numbers and the one proposal ------------------------------------------------------------------------


def test_the_week_draft_carries_the_numbers_it_was_given_and_one_proposal(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    seen = fake(monkeypatch)
    assert run_cli("dream", "--catch-up")[0] in (0, 1)
    m = seen["weeks"][1]
    line = _week(lb, W25)
    payload = line["payload"]
    numbers = payload["extra"]["numbers"]
    place = m["time"]["places"][0]
    assert numbers["places"][0]["hours"] == place["hours"] and numbers["places"][0]["place"] == place["place"]
    every = {str(x["id"]): x for x in Logbook(lb.root).lines()}
    assert numbers["places"][0]["lines"] and all(i in every for i in numbers["places"][0]["lines"])
    texts = [s["text"] for s in payload["segments"]]
    assert f"{place['hours']} hours at {place['place']}." in texts, "the number as it was given"
    assert payload["segments"][texts.index(f"{place['hours']} hours at {place['place']}.")].get("evidence")
    assert payload["extra"]["parts"].count("next_week") == 1, "never more than one proposal"
    assert payload["extra"]["dropped"] == {dream_week.MORE_THAN_ONE: 1}
    (review,) = payload["extra"]["goals"]
    goal = next(x for x in every.values() if x["kind"] == "goal" and x["payload"]["text"] == review["text"])
    assert review["goal"] == goal["id"] and review["disposition"] == "advancing"
    assert payload["extra"]["parts"][review["segment"]] == "goals"
    assert {g["text"] for g in m["goals"]} == {GOAL_SAIL, GOAL_READ}
    assert m["energy"] == dream_week.NO_DATA and numbers["energy"] is None, "health is tier 3: no data"
    zurich = next(p for p in m["time"]["places"] if "Zurich" in p["place"])
    assert zurich["days"] == 4 and zurich["hours"] > 70
    ola = next(p for p in m["time"]["people"] if p["name"] == "Ola Nordmann")
    assert ola["calendar"] == 1 and ola["messages"] == 2 and ola["transcripts"] == 1
    assert ola["days_together"] >= 1 and "hours_together" not in ola, "days at a stay, never its hours"
    kari = next(x for x in m["people"]["movers"] if x["name"] == "Kari Nordmann")
    assert (kari["this_week"], kari["week_before"]) == (0, 4) and kari["ref"] == []
    owed = {p["quote"]: p for p in m["people"]["promises"]["you_owe"]}
    assert list(owed) == [PROMISE_ZURICH, NOTE_HOME], "open both ways on the Sunday, the latest first"
    assert owed[PROMISE_ZURICH]["ref"] and "ref" not in owed[NOTE_HOME], "the week before's is not cited"
    text = next(p for p in seen["prompts"] if "one week of a personal record" in p)
    assert "Never moralise" in text and "never more than one" in text
    line24 = _week(lb, W24)
    assert line24["payload"]["extra"]["numbers"]["energy"] is None
    owed24 = seen["weeks"][0]["people"]["promises"]["you_owe"]
    assert owed24[0].get("ref"), "made in the week of 8 June: cited there"


def test_a_figure_the_week_did_not_give_is_marked_and_a_goal_without_evidence_is_dropped(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    def made_up(material: dict[str, Any]) -> dict[str, Any]:
        found = week_answer(material)
        place = material["time"]["places"][0]
        found["time"].append({"text": "About 50 hours of work.", "evidence": place["ref"][:1]})  # an estimate
        found["goals"] = [
            {
                "goal": material["goals"][0]["goal"],
                "disposition": "advancing",
                "text": "Sailing.",
                "evidence": [],
            },
            {"goal": "G9", "disposition": "done", "text": "Done.", "evidence": place["ref"][:1]},
            {
                "goal": material["goals"][1]["goal"],
                "disposition": "finished",
                "text": "Read.",
                "evidence": place["ref"][:1],
            },
            {
                "goal": material["goals"][1]["goal"],
                "disposition": "stalled",
                "text": "No book.",
                "evidence": place["ref"][:1],
            },
            {
                "goal": material["goals"][1]["goal"],
                "disposition": "let-go",
                "text": "Again.",
                "evidence": place["ref"][:1],
            },
        ]
        return found

    fake(monkeypatch, week=made_up)
    run_cli("dream", "--catch-up")
    payload = _week(lb, W25)["payload"]
    assert {"text": "About 50 hours of work.", "unsupported": True} in payload["segments"]
    assert payload["extra"]["marked"] == {dream.UNBACKED: 1}
    assert payload["extra"]["dropped"] == {
        dream_week.MORE_THAN_ONE: 1,
        dream_week.NOT_OF_THE_WEEK: 1,
        dream_week.NOT_A_GOAL: 1,
        dream_week.NOT_A_DISPOSITION: 1,
        dream_week.GOAL_TWICE: 1,
    }
    (review,) = payload["extra"]["goals"]
    assert review["text"] == GOAL_READ and review["disposition"] == "stalled"


def test_energy_is_the_code_s_sleep_and_training_when_the_entry_lets_health_cross(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    set_dream_entry(lb.root, {"max_tier": 3, "until": "2026-12-31"})
    seen = fake(monkeypatch)
    assert run_cli("dream", "--catch-up")[0] in (0, 1)
    w24 = seen["weeks"][0]
    sleep, training = w24["energy"]["sleep"], w24["energy"]["training"]
    assert sleep["nights"] == 7, "the nights that ended on its days, as the Day counts them"
    assert sleep["hours"] == 7.6, "7 h 34 min each: Monday's whole, its first stage on the Sunday before"
    assert training == {**training, "sessions": 1, "minutes": 45}
    payload = _week(lb, W24)["payload"]
    assert payload["extra"]["numbers"]["energy"]["sleep"]["nights"] == 7
    assert "7 nights, 7.6 hours asleep a night." in [s["text"] for s in payload["segments"]]
    assert _week(lb, W24)["tier"] == 3, "it read tier-3 lines"
    every = {str(x["id"]): x for x in Logbook(lb.root).lines()}
    sunday_before = [i for i, x in every.items() if x["payload"].get("raw_id") == "sleep:2026-06-07:0"]
    cited = {e for s in payload["segments"] for e in s.get("evidence", [])}
    assert sunday_before and not cited & set(sunday_before), "read for Monday's night, never cited"


# -- the policy ----------------------------------------------------------------------------------------------


def test_under_max_tier_1_no_tier_2_line_or_day_draft_reaches_the_week(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    fake(monkeypatch)
    assert run_cli("dream", "--catch-up")[0] in (0, 1)  # the days and weeks dreamed under max_tier 2
    set_dream_entry(lb.root, {"max_tier": 1, "until": "2026-12-31"})
    # Kari's name at tier 1, so the week under max_tier 1 may name her: it reads the people overlay at its
    # entry's tiers, and the fortnight names her only at tier 2 (R2, tests/test_dream_names_at_tier.py)
    lb.append_many([{**resolution(("email", KARI["email"]), KARI_ID, "Kari Nordmann"), "tier": 1}])
    seen = fake(monkeypatch)
    code, _out, err = run_cli("dream", "week", W25)
    assert code == 2 and "has none the 'dream' entry allows" in err, "the days' tier-2 drafts are withheld"
    assert seen["weeks"] == []

    code, out, err = run_cli("dream", "--catch-up")  # the days dreamed again under the entry, then the weeks
    assert f"{W25}  dreamed" in out and "dreamed at tier 2, above max_tier 1 now" in out, out + err
    sent = json.dumps(seen["weeks"], ensure_ascii=False)
    for text in (NOTE_ZURICH, NOTE_HOME, MESSAGE_TEXT, GOAL_SAIL, GOAL_READ):
        assert text not in sent
    m = seen["weeks"][-1]
    assert m["goals"] == [] and m["people"]["promises"] == {"you_owe": [], "they_owe": []}
    kari = next(x for x in m["people"]["movers"] if x["name"] == "Kari Nordmann")
    assert kari["week_before"] == 1, (
        "the lunch (tier 1) the week before; her messages (tier 2) are not counted"
    )
    assert all(p["messages"] == 0 and p["transcripts"] == 0 for p in m["time"]["people"])
    every = {str(x["id"]): x for x in Logbook(lb.root).lines()}
    line = [x for x in _weeks(lb) if x["payload"]["subject"] == W25][-1]
    assert line["tier"] == 1
    cited = [e for s in line["payload"]["segments"] for e in s.get("evidence", [])]
    noted = [
        i
        for kind in ("places", "people", "threads")
        for p in line["payload"]["extra"]["numbers"][kind]
        for i in p["lines"]
    ]
    assert cited and all(every[i]["tier"] <= 1 for i in [*cited, *noted]), (
        "no line above the ceiling is named"
    )


def test_no_dream_entry_refuses_the_week_before_anything_is_read(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    set_dream_entry(lb.root, None)
    seen = fake(monkeypatch)
    code, _out, err = run_cli("dream", "week", W24)
    assert code == 2 and "'dream'" in err and seen["calls"] == [] and _weeks(lb) == []


# -- the reader: the Day of its Sunday -----------------------------------------------------------------------


def test_the_day_of_a_sunday_carries_its_week_s_draft_and_withholds_it_by_the_entry(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    undreamed = json.loads(run_cli("day", "2026-06-21", "--json")[1])
    assert "week" not in undreamed and "week_draft" not in undreamed, "a Sunday whose week has no draft"
    fake(monkeypatch)
    run_cli("dream", "--catch-up")
    line = _week(lb, W25)
    data = json.loads(run_cli("day", "2026-06-21", "--json")[1])
    assert data["week"] == W25 and data["week_draft"]["line"] == line["id"]
    assert (
        data["week_draft"]["segments"][0]["part"] == "time" and data["week_draft"]["segments"][0]["supported"]
    )
    assert data["week_draft"]["numbers"]["places"] and data["week_draft"]["proposed"]["goals"]
    assert "week_draft_withheld" not in data
    saturday = json.loads(run_cli("day", "2026-06-20", "--json")[1])
    assert "week_draft" not in saturday and "week" not in saturday, "only on a Sunday"
    out = run_cli("day", "2026-06-21")[1]
    assert f"week {W25}" in out and "next week" in out and "hours" in out
    quiet = json.loads(run_cli("day", "2026-06-21", "--json", "--no-dream")[1])
    assert "week_draft" not in quiet and "week" not in quiet

    set_dream_entry(lb.root, {"max_tier": 1})  # lowered since: the draft is above it
    data = json.loads(run_cli("day", "2026-06-21", "--json")[1])
    assert "week_draft" not in data and data["week_draft_withheld"]["line"] == line["id"]
    assert "dream week" in data["week_draft_withheld"]["why"]
    out = run_cli("day", "2026-06-21")[1]
    assert drafts.SUPERSEDED_BY_POLICY in out and "Send Kari Nordmann" not in out
    assert DREAM_ENTRY["max_tier"] == 2


# -- the number rule and the evidence rule, at their edges --------------------------------------------------


def test_figures_glued_to_units_in_words_or_from_a_day_s_draft_are_marked(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """A figure is digits glued to a unit or not, and a number in words; a number a day's draft wrote
    is a model's and lends nothing; dates, clocks and the week's year are not numbers."""
    fake(monkeypatch)
    run_cli("dream", "--catch-up")
    read = dream_week.material(lb, W25, "2026-06-15", "2026-06-21", policy.dream_entry(lb.root))
    made = read.made
    place = made.data["time"]["places"][0]
    stay = [made.refs[r] for r in place["ref"][:1]]
    told = next(t for d in made.data["days"] for t in d["draft"] or [])
    segments: list[dict[str, Any]] = [
        {"text": f"{place['hours']} hours at {place['place']}.", "evidence": stay},
        {"text": "About 45min a day there.", "evidence": stay},
        {"text": "Some 7.5h on Monday.", "evidence": stay},
        {"text": "Eleven visits to the cafe.", "evidence": stay},
        {"text": f"On 2026-06-16 at 19:30, in 2026, {place['days']} days at the hotel.", "evidence": stay},
        {
            "text": "9 calls that day, as the day's draft said.",
            "evidence": [made.refs[r] for r in told["ref"]],
        },
    ]
    assert dream.hold_numbers(segments, made.data, made) == 4
    assert [s["text"] for s in segments if s.get("unsupported")] == [
        "About 45min a day there.",
        "Some 7.5h on Monday.",
        "Eleven visits to the cafe.",
        "9 calls that day, as the day's draft said.",
    ]


def test_a_sentence_citing_a_line_outside_the_week_or_a_reference_never_given_is_unsupported(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """RFC 0036 rule 6, strictly: one reference the material did not give (a made-up one, the goal's
    own line, the call's synthesis, a line of the week before) marks the sentence, whatever else it
    cites; and an answer of the wrong shapes is refused or dropped, never a crash."""
    every = list(Logbook(lb.root).lines())
    goal = next(x for x in every if x["kind"] == "goal")
    synthesis = next(x for x in every if x["kind"] == "draft")
    before = next(x for x in every if x["kind"] == "message" and x["at"].startswith("2026-06-09"))

    def answer(material: dict[str, Any]) -> dict[str, Any]:
        found = week_answer(material)
        ref = material["time"]["places"][0]["ref"][:1]
        found["time"] = [
            {"text": "The hotel.", "evidence": ref},
            {"text": "The office.", "evidence": ref},
            {"text": "The cafe.", "evidence": ref},
            {"text": "A made-up one.", "evidence": [*ref, "L999"]},
            {"text": "The goal itself.", "evidence": [*ref, goal["id"]]},
            {"text": "The call's synthesis.", "evidence": [synthesis["id"]]},
            {"text": "The week before.", "evidence": [before["id"]]},
            {"text": "A string of evidence.", "evidence": ref[0]},
            7,
            None,
            ["a", "list"],
        ]
        found["goals"] = [{"goal": ["G1"], "disposition": {}, "text": 3}, "G1", None]
        found["energy"] = "none"
        found["next_week"] = found["next_week"][:1] * 9
        return found

    fake(monkeypatch)
    run_cli("dream", "--catch-up")  # the days' drafts, which the week reads
    written = len(_weeks(lb))
    fake(monkeypatch, week=answer)
    code, out, err = run_cli("dream", "week", W24)
    assert code == 1 and "segments rest on no line of the week" in err, out + err
    assert len(_weeks(lb)) == written, "five of the time's sentences marked: refused, nothing written"


def test_a_journey_s_sentence_with_one_reference_it_was_not_given_is_unsupported(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    from dream_fortnight import JOURNEY, journey_answer

    def answer(material: dict[str, Any]) -> dict[str, Any]:
        found = journey_answer(material)
        found["days"] = [
            {"text": "Tuesday was the dinner.", "evidence": [*material["people"][0]["ref"], "L999"]}
        ]
        return found

    fake(monkeypatch, journey=answer)
    run_cli("dream", "--catch-up")
    (line,) = [
        x for x in Logbook(lb.root).lines() if x["kind"] == drafts.KIND and x["payload"]["unit"] == "journey"
    ]
    assert line["payload"]["subject"][0] == JOURNEY
    assert {"text": "Tuesday was the dinner.", "unsupported": True} in line["payload"]["segments"]


# -- as the Sunday stood -----------------------------------------------------------------------------------


def test_a_promise_kept_after_the_sunday_leaves_the_week_as_it_was(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """What a later week does never changes this one: a promise marked done after the Sunday was open
    on it, so the week reads it as it did and is unchanged."""
    from logbook.contrib import promises as promise_reader

    seen = fake(monkeypatch)
    run_cli("dream", "--catch-up")
    (kept,) = [p for p in promise_reader.extract(lb).proposals if p.match.quote == NOTE_HOME]
    code, _out, err = run_cli("promises", "done", kept.id)  # now, long after the week
    assert code == 0, err
    sent = len(seen["weeks"])
    _code, out, err = run_cli("dream", "--catch-up")
    assert f"{W24}  unchanged" in out and f"{W25}  unchanged" in out, out + err
    assert len(seen["weeks"]) == sent


def test_a_mover_s_promises_are_counted_as_the_sunday_stood(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """Ola's promise to the owner, made in Zürich, is owed to the owner on the Sunday: one, in his
    row and among the promises, and still one after it is kept, later."""
    from logbook.contrib import promises as promise_reader

    fake(monkeypatch)
    run_cli("dream", "--catch-up")
    found = policy.dream_entry(lb.root)
    ola = next(
        m
        for m in dream_week.material(lb, W25, "2026-06-15", "2026-06-21", found).made.data["people"]["movers"]
        if m["name"] == "Ola Nordmann"
    )
    assert (ola["they_owe"], ola["you_owe"]) == (1, 0)
    (theirs,) = [p for p in promise_reader.extract(lb).proposals if p.match.quote == OLA_PROMISE]
    assert run_cli("promises", "done", theirs.id)[0] == 0
    read = dream_week.material(lb, W25, "2026-06-15", "2026-06-21", found)
    ola = next(m for m in read.made.data["people"]["movers"] if m["name"] == "Ola Nordmann")
    assert ola["they_owe"] == 1, "open on the Sunday, kept after it"
    assert [p["quote"] for p in read.made.data["people"]["promises"]["they_owe"]] == [OLA_PROMISE]
    out = run_cli("dream", "--catch-up")[1]
    assert f"{W25}  unchanged" in out


def test_read_count_is_the_week_s_own_lines_and_the_rest_is_counted_beside(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    seen = fake(monkeypatch)
    run_cli("dream", "--catch-up")
    found = policy.dream_entry(lb.root)
    read = dream_week.material(lb, W25, "2026-06-15", "2026-06-21", found)
    payload = _week(lb, W25)["payload"]
    assert payload["read_count"] == len(read.made.ids) == read.made.read_count
    assert payload["extra"]["read_beside"] == read.beside > 0, "the days' drafts, the goals, the promises"
    code, out, err = run_cli("dream", "week", W25, "--dry-run")
    assert code == 0 and "dry run, nothing written" in out and len(_weeks(lb)) == 2, out + err
    assert len(seen["weeks"]) == 3


def test_a_thread_s_own_figures_are_the_record_s_words_not_an_estimate(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    fake(monkeypatch)
    run_cli("dream", "--catch-up")
    read = dream_week.material(lb, W25, "2026-06-15", "2026-06-21", policy.dream_entry(lb.root))
    made = read.made
    sprint = next(t for t in made.data["time"]["threads"] if t["thread"] == "Sprint 42 review")
    segments: list[dict[str, Any]] = [
        {
            "text": "Sprint 42 review was one of the threads.",
            "evidence": [made.refs[r] for r in sprint["ref"]],
        },
        {"text": "Sprint 43 review was another.", "evidence": [made.refs[r] for r in sprint["ref"]]},
    ]
    assert dream.hold_numbers(segments, made.data, made) == 1
    assert segments[0].get("evidence") and segments[1].get("unsupported")


def test_the_same_model_at_the_same_head_under_the_same_entry_writes_no_week(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    seen = fake(monkeypatch)
    run_cli("dream", "--catch-up")
    found = policy.dream_entry(lb.root)
    read = dream_week.material(lb, W24, "2026-06-08", "2026-06-14", found)
    payload = {
        "schema": drafts.SCHEMA,
        "unit": drafts.UNIT_WEEK,
        "subject": W24,
        "read_head": read.made.read_head,
        "read_count": read.made.read_count,
        "language": "en",
        "segments": [{"text": "A week.", "unsupported": True}],
        "extra": {"policy_version": policy.version(found)},
    }
    last = max(str(line["at"]) for line in _weeks(lb) if line["payload"]["subject"] == W24)
    lb.append(last, f"model:{MODEL}", drafts.KIND, 2, payload)  # the standing one: same `at`, later seq
    sent = len(seen["weeks"])
    with pytest.raises(dream.DreamError, match="nothing new to dream"):
        dream_week.run(lb, W24, ENV, today=date(2026, 6, 22), read=read)
    assert len(seen["weeks"]) == sent


@pytest.mark.parametrize(
    ("today", "days", "weeks"),
    [
        ("2026-06-22", 14, ["2026-W24", "2026-W25"]),  # Monday: the close of Sunday 21 June
        ("2026-06-23", 14, ["2026-W25"]),  # Tuesday: 8 June has left the window
        ("2026-06-21", 14, ["2026-W24"]),  # Sunday: its own week is not over
        ("2026-06-22", 7, ["2026-W25"]),
        ("2026-06-22", 6, []),  # fewer than seven days hold no week
        ("2027-01-04", 7, ["2026-W53"]),  # 2026 has 53 ISO weeks: 28 December to 3 January
        ("2026-01-05", 7, ["2026-W01"]),  # ISO week 1 of 2026 began on 29 December 2025
    ],
)
def test_the_weeks_a_catch_up_looks_at_are_those_whose_seven_days_it_looks_at(
    today: str, days: int, weeks: list[str]
) -> None:
    found = dream_week.weeks_to_catch_up(date.fromisoformat(today), days)
    assert [w for w, _monday, _sunday in found] == weeks


def test_which_week_a_day_a_week_or_none_names() -> None:
    tuesday = date(2026, 6, 23)
    assert dream_week.which(None, tuesday)[0] == W25, "the last week whose Sunday is over"
    assert dream_week.which("2026-06-10", tuesday) == (W24, "2026-06-08", "2026-06-14")
    assert dream_week.which("2026-W53", date(2027, 1, 4)) == ("2026-W53", "2026-12-28", "2027-01-03")
    assert dream_week.which("yesterday", date(2026, 6, 22))[0] == W25, "Monday: yesterday was Sunday"
    with pytest.raises(dream_week.NotOver):
        dream_week.which("yesterday", tuesday)
    with pytest.raises(ValueError):
        dream_week.which("2026-W54", tuesday)
