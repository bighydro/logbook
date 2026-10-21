"""`logbook dream month [YYYY-MM]` and the month's turn in `dream --catch-up` (RFC 0036, unit `month`, the
amendment of 2026-10-21): a model reads one calendar month, once it is over, told from the days the owner
signed (their drafts' supported sentences and the owner's own words on them, never a raw line's text),
with where it went computed by the code (places, nights by class, people in order, never a count beside a
name), the goals with what the month shows for each, one proposal for next month and one question.

On the synthetic fortnight of `dream_fortnight.py` (8 to 21 June 2026); the endpoint is an in-process fake
(`fake_arcs`) and no test opens a connection. Nobody here exists."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from dream_fortnight import (
    DREAM_ENTRY,
    ENV,
    MESSAGE_TEXT,
    NOTE_HOME,
    day_answer,
    fortnight,
    journey_answer,
    run_cli,
    set_dream_entry,
    week_answer,
)

from logbook.contrib import dream, dream_month, model_client
from logbook.core import drafts, policy, signing
from logbook.core.store import Logbook

JUNE = "2026-06"
REFLECTION = "Reflect: the harbour office called back about the berth."
SIGN_NOTE = "A good day at the berth."
GOAL_OLA = "Keep the berth in Vollen, as agreed with Ola Nordmann."
SIGNED = ("2026-06-09", "2026-06-16", "2026-06-20")  # three of the fortnight's days, signed


def month_answer(material: dict[str, Any]) -> dict[str, Any]:
    """A plausible answer from a month's material, every figure as the material gives it, two proposals
    for next month and two questions (one of each is kept)."""
    first = re.findall(r'"(L\d+)"', json.dumps(material["days"]))[:1]
    where = material["where"]
    place = where["places"][0]
    found: dict[str, Any] = {
        "month": [
            {"text": "A month at home and at the office, with Zürich in the middle.", "evidence": first}
        ],
        "where": [{"text": f"{place['hours']} hours at {place['place']}.", "evidence": place["ref"][:1]}],
        "goals": [],
        "next_month": [
            {"text": "Send Kari Nordmann the harbour map.", "evidence": first},
            {"text": "Plan the summer.", "evidence": first},
        ],
        "question": [
            {"text": "Is the berth still what you want?", "evidence": first},
            {"text": "And the office?", "evidence": first},
        ],
    }
    if where["people"]:
        person = where["people"][0]
        found["where"].append({"text": f"Mostly with {person['name']}.", "evidence": person["ref"][:1]})
    touched = [g for g in material["goals"] if g["touched"]["ref"]]
    if touched:
        found["goals"] = [{"text": "The berth came up.", "evidence": touched[0]["touched"]["ref"][:1]}]
    return found


def chapter_answer(material: dict[str, Any]) -> dict[str, Any]:
    """A plausible answer from a chapter's material: its arc from the first drafted sentence, its rules,
    what it held, and what it closed when it closed anything."""
    ref = material["chapter"]["ref"]
    drafted = re.findall(r'"(L\d+)"', json.dumps([material["months"], material["weeks"]]))[:1]
    held = material["held"]
    found: dict[str, Any] = {
        "arc": [{"text": "The weeks at home, then Zürich, then home again.", "evidence": drafted}],
        "rule": [],
        "held": [{"text": f"{held['days']} days, {held['signed']} of them signed.", "evidence": ref}],
        "closed": [],
    }
    if material["chapter"]["rules"]:
        found["rule"] = [{"text": "Fixing things came first.", "evidence": ref}]
    closed = material["closed"]["goals"]
    if closed:
        found["closed"] = [
            {"text": f"The goal to read was {closed[0]['disposition']}.", "evidence": closed[0]["ref"]}
        ]
    return found


def fake_arcs(
    monkeypatch: pytest.MonkeyPatch,
    month: Callable[[dict[str, Any]], Any] | None = None,
    chapter: Callable[[dict[str, Any]], Any] | None = None,
    week: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """`model_client.send` replaced by an in-process fake that answers a month (`month`, default
    `month_answer`), a chapter (`chapter`, default `chapter_answer`), a week (`week`, default the
    fortnight's `week_answer`), a journey and a day as the fortnight's fake does. What each was sent
    is kept: `seen["months"]`, `seen["chapters"]` (the materials), `seen["prompts"]` (their system
    texts), `seen["calls"]` (every request)."""
    seen: dict[str, Any] = {"calls": [], "months": [], "chapters": [], "prompts": []}

    def send(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        seen["calls"].append(body)
        material = json.loads(body["messages"][1]["content"])
        if "chapter" in material:
            seen["chapters"].append(material)
            seen["prompts"].append(body["messages"][0]["content"])
            made = (chapter or chapter_answer)(material)
        elif "month" in material and "where" in material:
            seen["months"].append(material)
            seen["prompts"].append(body["messages"][0]["content"])
            made = (month or month_answer)(material)
        elif "week" in material:
            made = (week or week_answer)(material)
        elif "journey" in material:
            made = journey_answer(material)
        else:
            made = day_answer(material)
        return {"choices": [{"message": {"content": made if isinstance(made, str) else json.dumps(made)}}]}

    monkeypatch.setattr(model_client, "send", send)
    monkeypatch.setattr(model_client, "RETRY_PAUSE_S", 0.0)
    return seen


def today_is(monkeypatch: pytest.MonkeyPatch, day: str) -> None:
    monkeypatch.setattr(dream, "today", lambda: date.fromisoformat(day))


def dreamed_days(monkeypatch: pytest.MonkeyPatch, lb: Logbook) -> None:
    """Every day of the fortnight dreamed (the close of Monday 22 June), then three of them signed,
    one with a reflection and one with a note."""
    today_is(monkeypatch, "2026-06-22")
    code, out, err = run_cli("dream", "--catch-up")
    assert code == 0, out + err
    lb.append(
        "2026-06-16T19:30:00Z",
        "reflect",
        "note",
        2,
        {"schema": "note/v1", "text": REFLECTION, "labels": ["reflection"]},
    )
    for day in SIGNED:
        signing.sign(lb, day, note=SIGN_NOTE if day == "2026-06-20" else None)


def months(lb: Logbook) -> list[dict[str, Any]]:
    return [
        line
        for line in Logbook(lb.root).lines()
        if line["kind"] == drafts.KIND and line["payload"]["unit"] == drafts.UNIT_MONTH
    ]


def june(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """The fortnight with a third goal, one Ola Nordmann's name touches, the endpoint set and the policy's
    clock on 1 July: each test of a month or a chapter starts here."""
    lb = fortnight(tmp_path / "lb")
    lb.append(
        "2026-06-01T08:00:00Z",
        "manual",
        "goal",
        2,
        {"schema": "goal/v1", "text": GOAL_OLA, "horizon": "year", "from": "2026-06-01"},
    )
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(policy, "today", lambda: date(2026, 7, 1))
    return lb


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    return june(tmp_path, monkeypatch)


# -- a month once it is over, from its signed days ----------------------------------------------------------


def test_a_month_is_dreamed_once_over_from_its_signed_days_and_never_a_raw_line(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    seen = fake_arcs(monkeypatch)
    dreamed_days(monkeypatch, lb)
    today_is(monkeypatch, "2026-06-30")
    code, _out, err = run_cli("dream", "month", JUNE)
    assert code == 2 and "2026-06 runs to 2026-06-30, which is not over" in err and seen["months"] == []

    today_is(monkeypatch, "2026-07-01")
    code, out, err = run_cli("dream", "month")  # the last month over
    assert code == 0, out + err
    assert "2026-06: dreamed as #" in out and "signed    3 of 30 days" in out
    (material,) = seen["months"]
    assert [d["day"] for d in material["days"]] == list(SIGNED), "the signed days, and no other"
    assert all(d["drafted"] for d in material["days"]), "each told by its draft's supported sentences"
    wrote = {w["kind"]: w["text"] for d in material["days"] for w in d["wrote"]}
    assert wrote == {"reflection": REFLECTION, "signed": SIGN_NOTE}, "the owner's own words on them"
    sent = json.dumps(seen["calls"][-1])
    assert MESSAGE_TEXT not in sent and NOTE_HOME not in sent, "never a raw line's text"
    assert material["month"]["days"] == 30 and material["month"]["signed"] == 3

    (line,) = months(lb)
    payload = line["payload"]
    assert payload["subject"] == JUNE and payload["extra"]["prompt"] == dream_month.PROMPT_NAME
    assert payload["extra"]["policy_version"] == policy.version(policy.dream_entry(lb.root))
    assert drafts.validate(payload) == []
    for segment in payload["segments"]:
        assert "unsupported" in segment or set(segment["evidence"]) <= _month_ids(lb), "evidence of the month"
    assert payload["extra"]["parts"][0] == "month"


def _month_ids(lb: Logbook) -> set[str]:
    with lb.index() as idx:
        found = {str(x["id"]) for d in range(1, 31) for x in idx.day(f"2026-06-{d:02d}")}
        found |= {str(x["id"]) for x in idx.by_kind(signing.KIND)}
    return found


def test_a_month_with_no_signed_day_is_not_sent(lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network):
    seen = fake_arcs(monkeypatch)
    today_is(monkeypatch, "2026-07-01")
    code, _out, err = run_cli("dream", "month", JUNE)
    assert code == 2 and "no signed day" in err and seen["months"] == []
    code, out, err = run_cli("dream", "--catch-up")
    assert f"{JUNE}  empty     no signed day" in out, out + err
    assert seen["months"] == [] and months(lb) == []


# -- where it went: computed, and never a count beside a name ----------------------------------------------


def test_where_it_went_is_computed_and_the_people_are_names_in_order_never_counts(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    seen = fake_arcs(monkeypatch)
    dreamed_days(monkeypatch, lb)
    today_is(monkeypatch, "2026-07-01")
    assert run_cli("dream", "month", JUNE)[0] == 0
    (material,) = seen["months"]
    people = material["where"]["people"]
    assert {p["name"] for p in people} == {"Kari Nordmann", "Ola Nordmann"}
    assert all(set(p) == {"name", "ref"} for p in people), "a name and its references, no count"
    nights = {n["class"]: n["nights"] for n in material["where"]["nights"]}
    assert nights["home"] > 0 and nights["away"] == 3, "the three nights in Zürich away, the rest at home"
    numbers = months(lb)[0]["payload"]["extra"]["numbers"]
    assert all(set(p) == {"name", "id", "lines"} for p in numbers["people"]), "kept without a count too"
    assert numbers["places"][0]["hours"] == material["where"]["places"][0]["hours"]


def test_a_figure_beside_a_name_is_marked_and_a_second_proposal_and_question_dropped(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    def counted(material: dict[str, Any]) -> dict[str, Any]:
        found = month_answer(material)
        place = material["where"]["places"][0]
        person = material["where"]["people"][0]
        found["where"].append(
            {  # a figure the place's item gives, written beside a person: still marked
                "text": f"{place['days']} days with {person['name']}.",
                "evidence": [*person["ref"][:1], *place["ref"][:1]],
            }
        )
        return found

    fake_arcs(monkeypatch, month=counted)
    dreamed_days(monkeypatch, lb)
    today_is(monkeypatch, "2026-07-01")
    code, out, err = run_cli("dream", "month", JUNE)
    assert code == 0, out + err
    payload = months(lb)[0]["payload"]
    marked = [s for s in payload["segments"] if s.get("unsupported")]
    assert len(marked) == 1 and "days with" in marked[0]["text"]
    assert payload["extra"]["marked"] == {dream_month.BESIDE_A_NAME: 1}
    assert payload["extra"]["dropped"] == {dream_month.MORE_THAN_ONE: 1, dream_month.MORE_QUESTIONS: 1}
    assert (
        payload["extra"]["parts"].count("next_month") == 1
        and payload["extra"]["parts"].count("question") == 1
    )


def test_a_day_draft_s_sentence_with_a_figure_beside_a_name_is_never_passed_on(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    seen = fake_arcs(monkeypatch)
    dreamed_days(monkeypatch, lb)
    day = next(
        x
        for x in Logbook(lb.root).lines()
        if x["kind"] == drafts.KIND
        and x["payload"]["unit"] == "day"
        and x["payload"]["subject"] == "2026-06-09"
    )
    evidence = day["payload"]["segments"][0]["evidence"]
    payload = {
        **day["payload"],
        "segments": [
            {"text": "Kari Nordmann: 2 messages about the harbour maps.", "evidence": evidence},
            {"text": "An evening at home.", "evidence": evidence},
        ],
        "extra": {**day["payload"]["extra"], "parts": ["people", "day"]},
        "supersedes": day["id"],
    }
    lb.append("2026-06-22T05:10:00Z", day["source"], drafts.KIND, day["tier"], payload)
    today_is(monkeypatch, "2026-07-01")
    assert run_cli("dream", "month", JUNE)[0] == 0
    told = {d["day"]: [t["drafted"] for t in d["drafted"]] for d in seen["months"][0]["days"]}
    assert told["2026-06-09"] == ["An evening at home."], "the count beside Kari Nordmann stays out"


# -- the goals: what the month shows, computed --------------------------------------------------------------


def test_each_goal_carries_what_the_month_shows_its_reviews_and_the_days_it_was_touched(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    seen = fake_arcs(monkeypatch)
    dreamed_days(monkeypatch, lb)
    sail = next(
        x for x in Logbook(lb.root).lines() if x["kind"] == "goal" and "Lofoten" in x["payload"]["text"]
    )
    lb.append(
        "2026-06-19T10:00:00Z",
        "manual",
        "review",
        2,
        {"schema": "review/v1", "goal": str(sail["id"]), "disposition": "stalled", "period": "month"},
    )
    today_is(monkeypatch, "2026-07-01")
    assert run_cli("dream", "month", JUNE)[0] == 0
    (material,) = seen["months"]
    by_text = {g["text"]: g for g in material["goals"]}
    touched = by_text[GOAL_OLA]["touched"]["days"]
    assert {"2026-06-11", "2026-06-16"} <= set(touched), (
        "the call and the dinner with Ola Nordmann touched it"
    )
    assert all(isinstance(d, str) for d in touched), "dates, never a count beside a goal that names a person"
    assert [r["disposition"] for r in by_text[sail["payload"]["text"]]["reviews"]] == ["stalled"]
    assert by_text[sail["payload"]["text"]]["touched"]["days"] == []
    kept = {g["text"]: g for g in months(lb)[0]["payload"]["extra"]["numbers"]["goals"]}
    assert kept[GOAL_OLA]["touched"] == touched and kept[GOAL_OLA]["lines"]
    assert kept[sail["payload"]["text"]]["reviews"][0]["disposition"] == "stalled"
    assert any(part == "goals" for part in months(lb)[0]["payload"]["extra"]["parts"])


# -- once, and again only when it changed --------------------------------------------------------------------


def test_the_first_close_of_july_dreams_june_once_and_again_only_when_it_changed(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    seen = fake_arcs(monkeypatch)
    dreamed_days(monkeypatch, lb)
    today_is(monkeypatch, "2026-07-01")
    code, out, err = run_cli("dream", "--catch-up")
    assert code == 0 and f"{JUNE}  dreamed" in out and "its last day is over, no draft yet" in out, out + err
    rows = out.splitlines()
    assert rows.index(next(r for r in rows if r.startswith(JUNE + " "))) > rows.index(
        next(r for r in rows if r.startswith("2026-06-30"))
    ), "after the days"
    assert len(seen["months"]) == 1

    _code, out, _err = run_cli("dream", "--catch-up")
    assert f"{JUNE}  unchanged" in out and len(seen["months"]) == 1, "nothing sent, nothing written"

    signing.sign(lb, "2026-06-12")  # a fourth day signed: what the month reads changed
    today_is(monkeypatch, "2026-07-02")
    _code, out, _err = run_cli("dream", "--catch-up")
    assert f"{JUNE}  dreamed" in out and len(months(lb)) == 2
    assert months(lb)[1]["payload"]["supersedes"] == months(lb)[0]["id"]

    today_is(monkeypatch, "2026-07-15")
    out = run_cli("dream", "--catch-up")[1]
    assert not any(r.startswith(JUNE + "  ") for r in out.splitlines()), "its last day left the window"


@pytest.mark.parametrize(
    ("today", "days", "expected"),
    [
        ("2026-07-01", 14, ["2026-06"]),
        ("2026-07-14", 14, ["2026-06"]),
        ("2026-07-15", 14, []),
        ("2026-06-30", 14, []),
        ("2026-08-02", 40, ["2026-06", "2026-07"]),
    ],
)
def test_months_to_catch_up_are_those_whose_last_day_is_in_the_window(
    today: str, days: int, expected: list[str]
):
    assert [m for m, _f, _l in dream_month.months_to_catch_up(date.fromisoformat(today), days)] == expected


def test_the_month_records_its_entry_and_is_dreamed_again_under_another(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    fake_arcs(monkeypatch)
    dreamed_days(monkeypatch, lb)
    today_is(monkeypatch, "2026-07-01")
    run_cli("dream", "--catch-up")
    set_dream_entry(lb.root, {**DREAM_ENTRY, "until": "2026-11-30"})  # the same ceiling, another version
    _code, out, err = run_cli("dream", "--catch-up")
    assert f"{JUNE}  dreamed" in out and "dreamed under another dream entry" in out, out + err


# -- the policy gates --------------------------------------------------------------------------------------


@pytest.mark.parametrize("entry", [None, {"max_tier": 2, "until": "2026-06-30"}])
def test_no_dream_entry_or_an_expired_one_refuses_before_anything_is_sent(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network, entry: dict[str, Any] | None
):
    seen = fake_arcs(monkeypatch)
    dreamed_days(monkeypatch, lb)
    calls = len(seen["calls"])
    set_dream_entry(lb.root, entry)
    today_is(monkeypatch, "2026-07-01")
    code, _out, err = run_cli("dream", "month", JUNE)
    assert code == 2 and "dream" in err
    assert len(seen["calls"]) == calls and months(lb) == []


def test_under_max_tier_1_the_month_reads_no_tier_2_line(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    seen = fake_arcs(monkeypatch)
    dreamed_days(monkeypatch, lb)
    set_dream_entry(lb.root, {"max_tier": 1, "until": "2026-12-31"})
    today_is(monkeypatch, "2026-07-01")
    code, out, err = run_cli("dream", "month", JUNE, "--dry-run")
    assert code == 0 and "tier 1" in out, out + err
    (material,) = seen["months"]
    assert REFLECTION not in json.dumps(material), "a reflection is a tier-2 note"
    told = {d["day"]: d["drafted"] for d in material["days"]}
    assert told["2026-06-16"] == [], "a day's tier-2 draft is not read under a ceiling of 1"


# -- the reader and the line ---------------------------------------------------------------------------------


def test_dream_month_json_prints_the_standing_draft_as_a_reader_shows_it(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    fake_arcs(monkeypatch)
    dreamed_days(monkeypatch, lb)
    today_is(monkeypatch, "2026-07-01")
    code, out, err = run_cli("dream", "month", JUNE, "--json")
    assert code == 0, err
    found = json.loads(out)
    assert found["unit"] == "month" and found["subject"] == JUNE and found["draft_withheld"] is None
    draft = found["draft"]
    assert draft["segments"][0]["part"] == "month" and all(
        s["supported"] or s.get("why") is None for s in draft["segments"]
    )
    assert "numbers" in draft and draft["malformed"] == []
    set_dream_entry(lb.root, {"max_tier": 1, "until": "2026-12-31"})  # lowered: the reader withholds it
    draft, withheld = dream_month.for_month(lb, JUNE)
    assert draft is None and withheld is not None and "dream month" in withheld["why"]


def test_json_goes_with_month_or_chapter_only(lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network):
    code, _out, err = run_cli("dream", "week", "--json")
    assert code == 2 and "--json goes with" in err


def test_a_month_subject_is_a_month():
    payload = {
        "schema": drafts.SCHEMA,
        "unit": "month",
        "subject": "2026-13",
        "read_head": "0" * 64,
        "read_count": 1,
        "language": "en",
        "segments": [{"text": "A month.", "unsupported": True}],
    }
    assert any("not a month" in p for p in drafts.validate(payload))
    assert drafts.validate({**payload, "subject": JUNE}) == []
