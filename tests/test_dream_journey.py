"""`logbook dream journey ID` and the journey's turn in `dream --catch-up` (RFC 0036, unit `journey`): a
model reads one journey whole, once it has closed, and writes one draft line about it, every sentence
with its lines or marked, every figure one the code computed from the lines it cites. On the synthetic
fortnight of `dream_fortnight.py`, three nights in Zürich; the endpoint is the in-process fake of
`test_dream.py` (`model_client.send` replaced) and no test opens a connection. Nobody here exists."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from dream_fortnight import (
    DECISION,
    DREAM_ENTRY,
    ENV,
    JOURNEY,
    MESSAGE_TEXT,
    MODEL,
    NAME,
    NOTE_HOME,
    NOTE_ZURICH,
    OLA_PROMISE,
    PROMISE_ZURICH,
    fake,
    fortnight,
    journey_answer,
    rest,
    run_cli,
    set_dream_entry,
)

from logbook.contrib import dream, dream_journey
from logbook.core import drafts, policy
from logbook.core.store import Logbook

THURSDAY_06 = "2026-06-18T04:00:00Z"  # 06:00 in Oslo on the day the journey comes home


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """The fortnight as it stood at 06:00 on Thursday 18 June: the last night in Zürich just over."""
    lb = fortnight(tmp_path / "lb", until=THURSDAY_06)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(policy, "today", lambda: date(2026, 6, 20))
    _today(monkeypatch, "2026-06-18")
    return lb


def _today(monkeypatch: pytest.MonkeyPatch, day: str) -> None:
    monkeypatch.setattr(dream, "today", lambda: date.fromisoformat(day))


def _journey_drafts(lb: Logbook) -> list[dict[str, Any]]:
    return [
        line
        for line in Logbook(lb.root).lines()
        if line["kind"] == drafts.KIND and line["payload"]["unit"] == drafts.UNIT_JOURNEY
    ]


def _closed(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    """The rest of the fortnight synced, and the morning after the journey came home."""
    rest(lb, THURSDAY_06)
    _today(monkeypatch, "2026-06-19")


# -- once, after it closes -------------------------------------------------------------------------------


def test_a_journey_dreams_once_and_only_after_it_closes(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    seen = fake(monkeypatch)
    code, out, err = run_cli("dream", "--catch-up")
    assert code in (0, 1), err
    assert JOURNEY not in out and seen["journeys"] == [], "the last night was still in Zürich: not closed"
    code, _out, err = run_cli("dream", "journey", "2026-06-16")
    assert code == 2 and "has not closed" in err and _journey_drafts(lb) == [], err
    code, _out, err = run_cli("dream", "journey", JOURNEY)  # still away, the record reads it to its last day
    assert code == 2 and _journey_drafts(lb) == [] and seen["journeys"] == [], err

    _closed(lb, monkeypatch)  # Friday 06:00: Thursday's night was at home
    code, out, err = run_cli("dream", "--catch-up")
    assert f"{JOURNEY}  dreamed" in out, out + err
    (line,) = _journey_drafts(lb)
    assert len(seen["journeys"]) == 1
    payload = line["payload"]
    assert payload["subject"][0] == JOURNEY and len(payload["subject"]) > 1, "its id, then its lines' ids"
    assert all(i in {str(x["id"]) for x in Logbook(lb.root).lines()} for i in payload["subject"][1:])
    assert payload["extra"]["policy_version"] == policy.version(policy.dream_entry(lb.root))
    assert payload["extra"]["prompt"] == dream_journey.PROMPT_NAME
    assert payload["extra"]["name"] == NAME and payload["extra"]["dropped"] == {"more than one name": 1}
    assert line["tier"] == 2 and line["source"] == f"model:{MODEL}"

    _today(monkeypatch, "2026-06-20")  # the next morning: nothing of the journey changed
    code, out, err = run_cli("dream", "--catch-up")
    assert f"{JOURNEY}  unchanged" in out, out + err
    assert len(_journey_drafts(lb)) == 1 and len(seen["journeys"]) == 1, "nothing sent, nothing written"
    code, out, _err = run_cli("dream", "--catch-up")
    assert f"{JOURNEY}  unchanged" in out and len(_journey_drafts(lb)) == 1, "a second run is unchanged"


def test_dream_journey_by_any_day_of_it_and_again_supersedes_as_a_day_s_dream_does(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    _closed(lb, monkeypatch)
    seen = fake(monkeypatch)
    code, out, err = run_cli("dream", "journey", "2026-06-16", "--dry-run")
    assert code == 0 and "dry run, nothing written" in out and _journey_drafts(lb) == [], err
    code, out, err = run_cli("dream", "journey", "2026-06-16")
    assert code == 0 and f"{JOURNEY}: dreamed as #" in out, err
    assert "name" in out and NAME in out and "proposed" in out
    code, out, err = run_cli("dream", "journey", JOURNEY)  # asked again: the head moved with the first draft
    first, second = _journey_drafts(lb)
    assert code == 0 and "supersedes" in out and second["payload"]["supersedes"] == first["id"], err
    assert len(seen["journeys"]) == 3 and no_network == []


def test_the_same_model_at_the_same_head_under_the_same_entry_writes_nothing(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """RFC 0036 rule 1, the day's `refuse_same`: a journey dreamed at this head under this entry by
    this model already, as when a write failed half-way, is not sent again."""
    _closed(lb, monkeypatch)
    seen = fake(monkeypatch)
    found = policy.dream_entry(lb.root)
    rd, trip = dream_journey.locate(lb, JOURNEY, found)
    read = dream_journey.material(lb, rd, trip, found)
    payload = {
        "schema": drafts.SCHEMA,
        "unit": drafts.UNIT_JOURNEY,
        "subject": [JOURNEY],
        "read_head": read.made.read_head,
        "read_count": read.made.read_count,
        "language": "en",
        "segments": [{"text": "Zürich.", "unsupported": True}],
        "extra": {"policy_version": policy.version(found)},
    }
    lb.append("2026-06-19T05:00:00Z", f"model:{MODEL}", drafts.KIND, 2, payload)
    with pytest.raises(dream.DreamError, match="nothing new to dream"):
        dream_journey.run(lb, JOURNEY, ENV, today=date(2026, 6, 19), located=(rd, trip), read=read)
    assert seen["journeys"] == [] and len(_journey_drafts(lb)) == 1


def test_what_the_journey_reads_its_days_its_calls_decisions_its_photos(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    _closed(lb, monkeypatch)
    seen = fake(monkeypatch)
    code, _out, err = run_cli("dream", "journey", JOURNEY)
    assert code == 0, err
    (m,) = seen["journeys"]
    assert m["journey"]["nights"] == 3 and m["journey"]["return_day"] == "2026-06-18"
    assert [d["day"] for d in m["days"]] == ["2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18"]
    assert [f["flight"] for f in m["flights"]] == ["XY 561 OSL to ZRH", "XY 562 ZRH to OSL"]
    assert [p["name"] for p in m["people"]] == ["Ola Nordmann"]
    assert m["decisions"][0]["drafted"] == DECISION, "the call's decision, as its synthesis has it"
    assert any(n["text"] == NOTE_ZURICH for n in m["notes"])
    assert {p["quote"] for p in m["promises"]} == {PROMISE_ZURICH, OLA_PROMISE}
    assert all(p["ref"] for p in m["promises"]), "each a line of the journey"
    assert NOTE_HOME not in json.dumps(m), "a note of another day is not the journey's"
    assert all("texts" not in c for c in m["messages"]) and m["messages"][0]["count"] == 2, "Ola, counted"
    assert m["photos"]["count"] == 2 and m["photos"]["candidates"][0].get("favorite") is True
    hours = m["places"][0]["hours"]
    assert isinstance(hours, float) and hours > 70, "the hours at the hotel, computed from its stay"
    assert "Write in English" in seen["prompts"][0] and "Numbers are given, never made" in seen["prompts"][0]
    (line,) = _journey_drafts(lb)
    favourite = [x for x in Logbook(lb.root).lines() if x["kind"] == "photo" and x["payload"].get("extra")]
    assert line["payload"]["extra"]["star"] == [str(favourite[0]["id"])]
    assert line["payload"]["read_count"] > 0
    parts = line["payload"]["extra"]["parts"]
    assert parts[0] == "journey" and "name" in parts and parts.count("name") == 1


# -- the evidence rule and the number rule ---------------------------------------------------------------


def test_a_figure_the_cited_lines_do_not_give_is_marked_unsupported(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    def made_up(material: dict[str, Any]) -> dict[str, Any]:
        found = journey_answer(material)
        ref = material["journey"]["ref"][:1]
        found["journey"][0] = {
            "text": "5 nights in Zürich.",
            "evidence": ref,
        }  # it was three: no item it cites gives 5
        found["places"] = [
            {"text": "About 70 hours at the hotel.", "evidence": material["places"][0]["ref"][:1]}
        ]
        return found

    _closed(lb, monkeypatch)
    fake(monkeypatch, made_up)
    code, _out, err = run_cli("dream", "journey", JOURNEY)
    assert code == 1 and "3 of 8 segments rest on no line" in err, "marked, they count against the share"
    assert _journey_drafts(lb) == []

    def fewer(material: dict[str, Any]) -> dict[str, Any]:
        found = made_up(material)
        del found["journey"][1]  # the rain, unsupported from the start
        return found

    fake(monkeypatch, fewer)
    code, _out, err = run_cli("dream", "journey", JOURNEY)
    assert code == 0, err
    (line,) = _journey_drafts(lb)
    segments = line["payload"]["segments"]
    assert {"text": "5 nights in Zürich.", "unsupported": True} in segments
    assert {"text": "About 70 hours at the hotel.", "unsupported": True} in segments
    assert line["payload"]["extra"]["marked"] == {dream.UNBACKED: 2}
    assert sum(1 for s in segments if s.get("unsupported")) == 2


def test_an_answer_mostly_unsupported_is_refused_and_nothing_written(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    def guesses(material: dict[str, Any]) -> dict[str, Any]:
        return {
            "journey": [
                {"text": "A sunny trip.", "unsupported": True},
                {"text": "12 museums.", "evidence": material["journey"]["ref"][:1]},
                {"text": "Three nights.", "evidence": material["journey"]["ref"][:1]},
            ],
            "name": [{"text": "Summer", "evidence": ["L999"]}],
        }

    _closed(lb, monkeypatch)
    fake(monkeypatch, guesses)
    code, _out, err = run_cli("dream", "journey", JOURNEY)
    assert code == 1 and "rest on no line of the journey" in err and _journey_drafts(lb) == []


# -- the policy ---------------------------------------------------------------------------------------------


def test_under_max_tier_1_no_note_message_or_call_of_the_journey_reaches_the_model(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    _closed(lb, monkeypatch)
    set_dream_entry(lb.root, {"max_tier": 1, "until": "2026-12-31"})
    seen = fake(
        monkeypatch, lambda m: {"journey": [{"text": "Zürich.", "evidence": m["journey"]["ref"][:1]}]}
    )
    code, _out, err = run_cli("dream", "journey", JOURNEY)
    assert code == 0, err
    sent = json.dumps(seen["calls"][-1], ensure_ascii=False)
    assert NOTE_ZURICH not in sent and DECISION not in sent and MESSAGE_TEXT not in sent
    (m,) = seen["journeys"]
    assert m["messages"] == [] and m["notes"] == [] and m["decisions"] == [] and m["max_tier"] == 1
    assert m["promises"] == [] and PROMISE_ZURICH not in sent, "a promise read from a tier-2 note"
    (line,) = _journey_drafts(lb)
    assert line["tier"] == 1, "the highest tier it read, not the ceiling"
    every = {str(x["id"]): x for x in Logbook(lb.root).lines()}
    named = [
        *line["payload"]["subject"][1:],
        *(e for s in line["payload"]["segments"] for e in s.get("evidence", [])),
    ]
    assert named and all(every[i]["tier"] <= 1 for i in named), "no line above the ceiling is named"

    set_dream_entry(lb.root, DREAM_ENTRY)  # raised again: another version of the entry
    code, out, err = run_cli("dream", "--catch-up")
    assert f"{JOURNEY}  dreamed" in out and "dreamed under another dream entry" in out, out + err
    first, second = _journey_drafts(lb)
    assert second["payload"]["supersedes"] == first["id"] and second["tier"] == 2


def test_no_dream_entry_refuses_before_anything_is_read(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    _closed(lb, monkeypatch)
    set_dream_entry(lb.root, None)
    seen = fake(monkeypatch)
    code, _out, err = run_cli("dream", "journey", JOURNEY)
    assert code == 2 and "'dream'" in err and seen["calls"] == [] and _journey_drafts(lb) == []


# -- the readers ---------------------------------------------------------------------------------------------


def test_trips_and_trip_carry_the_journey_s_draft_and_withhold_it_by_the_entry(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    _closed(lb, monkeypatch)
    fake(monkeypatch)
    assert run_cli("dream", "journey", JOURNEY)[0] == 0
    (line,) = _journey_drafts(lb)
    code, out, err = run_cli("show", "trips", "--json")
    assert code == 0, err
    (trip,) = json.loads(out)["trips"]
    assert trip["id"] == JOURNEY and trip["draft"]["line"] == line["id"] and "draft_withheld" not in trip
    assert trip["draft"]["segments"][0]["part"] == "journey" and trip["draft"]["segments"][0]["supported"]
    code, out, _err = run_cli("show", "trips")
    assert "draft" in out and NAME in out and "~ journey" in out, "the unsupported sentence set apart"
    code, out, _err = run_cli("show", "trip", JOURNEY, "--json")
    assert json.loads(out)["draft"]["line"] == line["id"]
    code, out, _err = run_cli("show", "trip", JOURNEY)
    assert NAME in out
    edge = json.loads(run_cli("show", "trips", "--since", "2026-06-08", "--until", "2026-06-17", "--json")[1])
    (cut,) = edge["trips"]  # a window that ends on its last night: the flight home is the day after it
    assert cut["id"] == JOURNEY
    assert cut["draft"]["line"] == line["id"] and all(
        s["supported"] for s in cut["draft"]["segments"] if s["evidence"]
    ), [s for s in cut["draft"]["segments"] if not s["supported"]]

    set_dream_entry(lb.root, {"max_tier": 1})  # lowered since: the draft is above it
    (trip,) = json.loads(run_cli("show", "trips", "--json")[1])["trips"]
    assert "draft" not in trip and trip["draft_withheld"]["line"] == line["id"]
    assert "dream journey" in trip["draft_withheld"]["why"]
    out = run_cli("show", "trips")[1]
    assert drafts.SUPERSEDED_BY_POLICY in out and NAME not in out
    data = json.loads(run_cli("show", "trip", JOURNEY, "--json")[1])
    assert "draft" not in data and data["draft_withheld"]["tier"] == 2


def test_a_journey_begun_before_the_days_looked_at_is_read_whole(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """`--days 3` on the morning after it came home looks at 16 to 18 June; the journey began on the
    15th, so it is read whole and dreamed under its own id, never as a part of it."""
    _closed(lb, monkeypatch)
    seen = fake(monkeypatch)
    _code, out, err = run_cli("dream", "--catch-up", "--days", "3")
    assert f"{JOURNEY}  dreamed" in out, out + err
    assert [m["journey"]["first_day"] for m in seen["journeys"]] == ["2026-06-15"]
    (line,) = _journey_drafts(lb)
    assert line["payload"]["subject"][0] == JOURNEY
