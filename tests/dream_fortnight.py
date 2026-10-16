"""A synthetic fortnight for the dream of a journey and of a week: Monday 8 to Sunday 21 June 2026, two
ISO weeks (2026-W24, 2026-W25), the Oslo persona at home and at the office, and one journey, three
nights in Zürich from Monday 15 June (XY 561 out, XY 562 home on Thursday 18). Kari and Ola Nordmann,
resolved from their addresses; a lunch with Kari, messages with her, a call with Ola; in Zürich a
dinner with Ola, two photos (one a favourite), a note of what was agreed, a promise, and a call whose
synthesis records a decision; two goals the owner wrote in May; and the health lines of every night and one
workout, tier 3. Nobody here exists: example.org addresses, the persona's reserved numbers, carrier
XY, which is no airline.

`fortnight(root, until=None)` writes it into a fresh record, the lines before `until` only when it is
given, so a test can hold the record where it stood on a morning of the journey and append the rest
after (`rest`)."""

from __future__ import annotations

import contextlib
import io
import json
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from persona import (
    CAFE,
    HOME,
    KARI,
    KARI_ID,
    OFFICE,
    OLA,
    OLA_ID,
    OSL,
    PLACES,
    TZ,
    UTC,
    ZRH,
    ZURICH,
    attendee,
    dwell,
    event,
    flight,
    note,
    photo,
    resolution,
    transcript,
    travel,
    utc,
)

from logbook import cli
from logbook.contrib import model_client
from logbook.core import policy
from logbook.core.store import Logbook

DAYS = [f"2026-06-{d:02d}" for d in range(8, 22)]  # Monday 8 June to Sunday 21 June
W24, W25 = "2026-W24", "2026-W25"
JOURNEY = "trip:2026-06-15:2026-06-17"
OUT, BACK = "2026-06-15", "2026-06-18"
NOTE_ZURICH = "Agreed with Ola Nordmann over dinner to keep the berth in Vollen next summer."
NOTE_HOME = "I'll send Kari Nordmann the harbour map by Friday."
PROMISE_ZURICH = "I'll send Ola Nordmann the berth contract by Monday."
OLA_PROMISE = "I'll send you the photos of the berth tomorrow."  # Ola's, to the owner
MESSAGE_TEXT = "Har du kartene over havna?"
GOAL_SAIL = "Sail to Lofoten and back this summer."
GOAL_READ = "Read one book a month."
DECISION = "The berth in Vollen is kept for next summer."
DREAM_ENTRY = {"max_tier": 2, "until": "2026-12-31"}
MODEL = "qwen2.5-7b-instruct"
ENV = {model_client.ENDPOINT_ENV: "http://127.0.0.1:8080/v1", model_client.MODEL_ENV: MODEL}
NAME = "Zürich in June"


def _office_day(day: str) -> list[dict[str, Any]]:
    return (
        dwell(day, "07:30", "08:00", HOME, every_min=5)
        + travel(day, "08:00", "08:10", HOME, OFFICE, steps=3)
        + dwell(day, "08:10", "17:50", OFFICE, every_min=5)
        + travel(day, "17:50", "18:00", OFFICE, HOME, steps=3)
        + dwell(day, "18:00", "18:30", HOME, every_min=5)
    )


def _home_night(day: str, next_day: str) -> list[dict[str, Any]]:
    return dwell(day, "18:30", "24:00", HOME, every_min=5) + dwell(
        next_day, "00:00", "07:30", HOME, every_min=5
    )


def _weekend_day(day: str) -> list[dict[str, Any]]:
    """A day at home with two hours at the cafe, to the evening."""
    return (
        dwell(day, "07:30", "11:00", HOME, every_min=5)
        + travel(day, "11:00", "11:10", HOME, CAFE, steps=3)
        + dwell(day, "11:10", "13:10", CAFE, every_min=5)
        + travel(day, "13:10", "13:20", CAFE, HOME, steps=3)
        + dwell(day, "13:20", "18:30", HOME, every_min=5)
    )


def message(at: str, text: str, who: dict[str, str], from_me: bool = False) -> dict[str, Any]:
    return {
        "at": at,
        "source": "imessage",
        "kind": "message",
        "tier": 2,
        "payload": {
            "schema": "message/v1",
            "chat": {"type": "direct", "id": f"chat-{who['phone']}", "name": who.get("name", "")},
            "sender": {"kind": "phone", "value": who["phone"]},
            "from_me": from_me,
            "text": text,
            "raw_id": f"msg:{at}:{who['phone']}",
        },
    }


def goal(text: str, horizon: str) -> dict[str, Any]:
    return {
        "at": "2026-05-02T08:00:00Z",
        "source": "manual",
        "kind": "goal",
        "tier": 2,
        "payload": {"schema": "goal/v1", "text": text, "horizon": horizon, "from": "2026-05-01"},
    }


def sleep(day: str, next_day: str) -> list[dict[str, Any]]:
    """One night's asleep stages, tier 3, as a phone writes them, split at midnight and at a waking:
    23:00 to 23:59 on `day`, 00:00 to 03:00 and 03:10 to 06:45 the next morning: 7 h 34 min asleep."""
    out = []
    for n, (first, start, last, end) in enumerate(
        (
            (day, "23:00", day, "23:59"),
            (next_day, "00:00", next_day, "03:00"),
            (next_day, "03:10", next_day, "06:45"),
        )
    ):
        begun = datetime.fromisoformat(f"{first}T{start}:00").replace(tzinfo=ZoneInfo(TZ))
        ended = datetime.fromisoformat(f"{last}T{end}:00").replace(tzinfo=ZoneInfo(TZ))
        out.append(
            {
                "at": begun.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end": ended.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source": "apple-health",
                "kind": "health",
                "tier": 3,
                "payload": {
                    "schema": "health-sample/v1",
                    "type": "sleep",
                    "stage": "asleep",
                    "value": (ended - begun).total_seconds(),
                    "unit": "s",
                    "device": "Phone",
                    "raw_id": f"sleep:{day}:{n}",
                },
            }
        )
    return out


def workout(day: str, start: str, minutes: int) -> dict[str, Any]:
    at = utc(day, start)
    ended = datetime.fromisoformat(at.replace("Z", "+00:00")) + timedelta(minutes=minutes)
    return {
        "at": at,
        "end": ended.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "apple-health",
        "kind": "health",
        "tier": 3,
        "payload": {
            "schema": "health-sample/v1",
            "type": "workout",
            "value": minutes * 60,
            "unit": "s",
            "raw_id": f"workout:{day}",
        },
    }


def drafts_of_fortnight() -> list[dict[str, Any]]:
    """Every line of the fortnight but the call's synthesis (`synthesis_of`), people first."""
    kari = {**KARI, "name": "Kari"}
    ola = {**OLA, "name": "Ola"}
    found: list[dict[str, Any]] = [
        resolution(("email", KARI["email"]), KARI_ID, "Kari Nordmann"),
        resolution(("phone", KARI["phone"]), KARI_ID, "Kari Nordmann"),
        resolution(("email", OLA["email"]), OLA_ID, "Ola Nordmann"),
        resolution(("phone", OLA["phone"]), OLA_ID, "Ola Nordmann"),
        goal(GOAL_SAIL, "year"),
        goal(GOAL_READ, "life"),
    ]
    # week one: the office, home nights, lunch with Kari on Wednesday, a call with Ola on Thursday
    for day, next_day in pairwise(DAYS[:5]):
        found += _office_day(day) + _home_night(day, next_day)
    found += _office_day(DAYS[4]) + _home_night(DAYS[4], DAYS[5])
    found += _weekend_day(DAYS[5]) + _home_night(DAYS[5], DAYS[6])
    found += _weekend_day(DAYS[6]) + dwell(
        DAYS[6], "18:30", "24:00", HOME, every_min=5
    )  # Monday leaves at 05:00
    found.append(
        event(utc("2026-06-10", "12:00"), utc("2026-06-10", "13:00"), "Lunch", [attendee(KARI["email"])])
    )
    found.append(message(utc("2026-06-09", "19:00"), MESSAGE_TEXT, kari, from_me=True))
    found.append(message(utc("2026-06-09", "19:10"), "Ja, jeg tar dem med på lørdag.", kari))
    found.append(message(utc("2026-06-11", "08:30"), "Takk for i går!", kari))
    found.append(transcript(utc("2026-06-11", "14:00"), utc("2026-06-11", "14:30"), "Boat plans", [ola]))
    found.append(note(utc("2026-06-12", "20:00"), NOTE_HOME))
    found.append(workout("2026-06-10", "06:30", 45))
    # week two: Monday to Zürich, three nights, Thursday home; the office Friday, a weekend at home
    mon, tue, wed, thu = DAYS[7], DAYS[8], DAYS[9], DAYS[10]
    found += (
        dwell(mon, "00:00", "05:00", HOME, every_min=5)
        + travel(mon, "05:00", "05:40", HOME, OSL, steps=4)
        + dwell(mon, "05:40", "07:00", OSL, every_min=5)
        + dwell(mon, "09:20", "10:00", ZRH, every_min=5)
        + travel(mon, "10:00", "10:30", ZRH, ZURICH, steps=3)
        + dwell(mon, "10:30", "24:00", ZURICH, every_min=5)
        + dwell(tue, "00:00", "24:00", ZURICH, every_min=5)
        + dwell(wed, "00:00", "24:00", ZURICH, every_min=5)
        + dwell(thu, "00:00", "15:00", ZURICH, every_min=5)
        + travel(thu, "15:00", "15:30", ZURICH, ZRH, steps=3)
        + dwell(thu, "15:30", "17:00", ZRH, every_min=5)
        + dwell(thu, "19:20", "20:00", OSL, every_min=5)
        + travel(thu, "20:00", "20:40", OSL, HOME, steps=4)
        + dwell(thu, "20:40", "24:00", HOME, every_min=5)
        + dwell(DAYS[11], "00:00", "07:30", HOME, every_min=5)
    )
    found.append(flight(mon, "561", "OSL", "ZRH", utc(mon, "07:05"), utc(mon, "09:15")))
    found.append(flight(thu, "562", "ZRH", "OSL", utc(thu, "17:10"), utc(thu, "19:15")))
    found.append(event(utc(tue, "19:00"), utc(tue, "21:00"), "Dinner", [attendee(OLA["email"])]))
    found.append(photo(utc(tue, "20:00"), ZURICH, favorite=True))
    found.append(photo(utc(wed, "11:00"), ZURICH))
    found.append(note(utc(tue, "22:30"), NOTE_ZURICH))
    found.append(note(utc(wed, "21:00"), PROMISE_ZURICH))
    found.append(message(utc(wed, "09:00"), "God tur hjem i morgen!", ola))
    found.append(message(utc(wed, "09:05"), OLA_PROMISE, ola))
    found.append(event(utc("2026-06-19", "09:00"), utc("2026-06-19", "10:00"), "Sprint 42 review"))
    found.append(transcript(utc(wed, "10:00"), utc(wed, "10:40"), "Berth contract", [ola]))
    found += _office_day(DAYS[11]) + _home_night(DAYS[11], DAYS[12])
    found += _weekend_day(DAYS[12]) + _home_night(DAYS[12], DAYS[13])
    found += dwell(DAYS[13], "07:30", "24:00", HOME, every_min=5)
    for day, next_day in pairwise(["2026-06-07", *DAYS]):
        found += sleep(day, next_day)
    return found


def synthesis_of(transcript_id: str, version: str) -> dict[str, Any]:
    """A model's synthesis of the Zürich call, as `transcript synthesize` writes it: one decision."""
    return {
        "at": utc("2026-06-18", "06:05"),
        "source": "model:qwen2.5-7b-instruct",
        "kind": "draft",
        "tier": 2,
        "payload": {
            "schema": "draft/v1",
            "unit": "event",
            "subject": [transcript_id],
            "read_head": "c" * 64,
            "read_count": 1,
            "language": "en",
            "segments": [{"text": DECISION, "evidence": [transcript_id]}],
            "extra": {
                "prompt": "transcript-synthesis/1",
                "utterances": 4,
                "segments": [{"part": "decisions", "utterances": [{"n": 3}]}],
                "policy_version": version,
            },
        },
    }


def set_dream_entry(root: Path, entry: dict[str, Any] | None) -> None:
    """The crossing policy's `dream` entry as `entry`, or none, beside a hermes and an mcp entry."""
    data: dict[str, Any] = {"hermes": {"max_tier": 2}, "mcp": {"max_tier": 1}}
    if entry is not None:
        data[policy.DREAM_DESTINATION] = entry
    path = policy.policy_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def fortnight(root: Path, until: str | None = None) -> Logbook:
    """The fortnight in a fresh record at `root`, the persona's places named, the `dream` entry
    `DREAM_ENTRY`; only the lines before `until` (an RFC 3339 UTC stamp) when it is given."""
    lb = Logbook.init(root, TZ)
    (lb.root / "places.json").write_text(json.dumps(PLACES, indent=2), encoding="utf-8")
    set_dream_entry(lb.root, DREAM_ENTRY)
    lines = drafts_of_fortnight()
    lb.append_many([line for line in lines if until is None or line["at"] < until])
    if until is None or utc("2026-06-18", "06:05") < until:
        _with_synthesis(lb)
    return lb


def rest(lb: Logbook, until: str) -> None:
    """Append the lines of the fortnight from `until` on, as the next syncs would."""
    lb.append_many([line for line in drafts_of_fortnight() if line["at"] >= until])
    _with_synthesis(lb)


def _with_synthesis(lb: Logbook) -> None:
    """The Zürich call's synthesis, once."""
    lines = list(lb.lines())
    if any(line["kind"] == "draft" and line["payload"]["unit"] == "event" for line in lines):
        return
    (call,) = [
        line
        for line in lines
        if line["kind"] == "transcript" and line["payload"]["title"] == "Berth contract"
    ]
    lb.append_many([synthesis_of(str(call["id"]), policy.version(policy.dream_entry(lb.root)))])


# -- the fake endpoint and the command line -------------------------------------------------------------


def day_answer(material: dict[str, Any]) -> dict[str, Any]:
    """A day's answer: one sentence on the first reference the material gives."""
    refs = re.findall(r'"(L\d+)"', json.dumps(material))
    return {"day": [{"text": "A day.", "evidence": refs[:1]}], "threads": [], "questions": [], "people": []}


def journey_answer(material: dict[str, Any]) -> dict[str, Any]:
    """A plausible answer from the journey's material, every figure as the material gives it; the
    people and the decisions when the ceiling let them through, one sentence on the journey else."""
    j = material["journey"]
    place = material["places"][0]
    photo = material["photos"]["candidates"][0]
    flights = [r for f in material["flights"] for r in f["ref"]]
    if not material["people"] or not material["decisions"]:
        return {"journey": [{"text": f"{j['nights']} nights away.", "evidence": j["ref"][:1]}]}
    return {
        "journey": [
            {
                "text": f"{j['nights']} nights in Zürich, out on XY 561 and home on XY 562.",
                "evidence": j["ref"][:1] + flights,
            },
            {"text": "It rained the whole time.", "unsupported": True},
        ],
        "days": [
            {"text": "Tuesday was the dinner with Ola Nordmann.", "evidence": material["people"][0]["ref"]}
        ],
        "places": [
            {"text": f"{place['hours']} hours at the hotel in the city.", "evidence": place["ref"][:1]}
        ],
        "people": [{"text": "Ola Nordmann was at the dinner.", "evidence": material["people"][0]["ref"]}],
        "decisions": [{"text": DECISION, "evidence": material["decisions"][0]["ref"]}],
        "promises": [],
        "photos": [{"text": "The photo from the dinner.", "evidence": photo["ref"]}],
        "name": [
            {"text": NAME, "evidence": j["ref"][:1]},
            {"text": "Three nights away", "evidence": j["ref"][:1]},
        ],
    }


def week_answer(material: dict[str, Any]) -> dict[str, Any]:
    """A plausible answer from a week's material, every figure as the material gives it, two
    proposals for next week (one is kept) and a review proposed for the first goal."""
    time = material["time"]
    place, person = time["places"][0], time["people"][0]
    first = re.findall(r'"(L\d+)"', json.dumps(material["days"]))[:1]
    found: dict[str, Any] = {
        "time": [
            {"text": f"{place['hours']} hours at {place['place']}.", "evidence": place["ref"][:1]},
            {"text": f"{person['contacts']} contacts with {person['name']}.", "evidence": person["ref"][:1]},
        ],
        "energy": [],
        "people": [],
        "goals": [],
        "next_week": [
            {"text": "Send Kari Nordmann the harbour map.", "evidence": first},
            {"text": "Plan the summer.", "evidence": first},
        ],
        "personal": [],
    }
    energy = material["energy"]
    if isinstance(energy, dict) and energy.get("sleep"):
        sleep = energy["sleep"]
        found["energy"] = [
            {
                "text": f"{sleep['nights']} nights, {sleep['hours']} hours asleep a night.",
                "evidence": sleep["ref"][:1],
            }
        ]
    movers = [m for m in material["people"]["movers"] if m["ref"]]
    if movers:
        m = movers[0]
        found["people"] = [
            {
                "text": f"{m['name']}: {m['this_week']} contacts, {m['week_before']} the week before.",
                "evidence": m["ref"][:1],
            }
        ]
    if material["goals"]:
        found["goals"] = [
            {
                "goal": material["goals"][0]["goal"],
                "disposition": "advancing",
                "text": "The boat came up.",
                "evidence": first,
            }
        ]
    return found


def fake(
    monkeypatch: pytest.MonkeyPatch,
    journey: Callable[[dict[str, Any]], Any] | None = None,
    week: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """`model_client.send` replaced by an in-process fake: a journey's material gets `journey` (default
    `journey_answer`), a week's `week` (default `week_answer`), a day's `day_answer`. What each was
    sent is kept: `seen["journeys"]`, `seen["weeks"]` (the materials), `seen["prompts"]` (the system
    texts of both), `seen["calls"]` (every request)."""
    seen: dict[str, Any] = {"calls": [], "journeys": [], "weeks": [], "prompts": []}

    def send(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        seen["calls"].append(body)
        material = json.loads(body["messages"][1]["content"])
        if "journey" in material:
            seen["journeys"].append(material)
            seen["prompts"].append(body["messages"][0]["content"])
            made = (journey or journey_answer)(material)
        elif "week" in material:
            seen["weeks"].append(material)
            seen["prompts"].append(body["messages"][0]["content"])
            made = (week or week_answer)(material)
        else:
            made = day_answer(material)
        return {"choices": [{"message": {"content": made if isinstance(made, str) else json.dumps(made)}}]}

    monkeypatch.setattr(model_client, "send", send)
    monkeypatch.setattr(model_client, "RETRY_PAUSE_S", 0.0)
    return seen


def run_cli(*args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            cli.main(list(args))
        except SystemExit as e:
            code = int(e.code or 0)
    return code, out.getvalue(), err.getvalue()
