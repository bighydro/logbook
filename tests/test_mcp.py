"""`logbook mcp`: the record as an MCP server over stdio, every tool behind the crossing ceiling of
`policy/crossing.json` for the `mcp` destination (ADR 0016). Driven here through the SDK's in-process
client over the synthetic Oslo persona; no socket opens. Every address is at example.org."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from persona import KARI, TZ, attendee, event, note, persona_record, utc

from logbook import cli
from logbook.contrib import mcp_server
from logbook.core import policy
from logbook.core.store import Logbook

pytest.importorskip("mcp")  # the `mcp` extra; the client below is imported where it is used

NOTE_DAY = "2026-06-13"  # the Saturday aboard: "Anchored in the bay with Ola Nordmann. Grilled."
SECRET = "I'll send the mooring photos by Friday"  # a tier-2 note, below the ceiling only at 2
HEALTH_DAY = "2026-06-10"


def _policy(lb: Logbook, max_tier: int | None) -> None:
    """The record's ceiling for the mcp destination; None leaves the destination unnamed."""
    path = lb.root / "policy" / "crossing.json"
    data = {"hermes": {"max_tier": 2}}
    if max_tier is not None:
        data["mcp"] = {"max_tier": max_tier}
    path.write_text(json.dumps(data), encoding="utf-8")


def _record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """The persona's fortnight plus one tier-2 note that reads as a promise, and one tier-3 line."""
    lb = persona_record(tmp_path, monkeypatch)
    lb.append_many(
        [
            note(utc(NOTE_DAY, "20:00"), f"Talked to Ola. {SECRET}."),
            {
                "at": utc(HEALTH_DAY, "22:00"),
                "source": "apple-health",
                "kind": "health",
                "tier": 3,
                "payload": {
                    "schema": "health-sample/v1",
                    "raw_id": "resting_hr:x",
                    "type": "resting_hr",
                    "value": 52,
                    "unit": "count/min",
                    "device": "watch",
                },
            },
        ]
    )
    return lb


def _call(lb: Logbook, name: str, arguments: dict[str, Any] | None = None, **options: Any) -> Any:
    """One tool call through the in-process client: the parsed JSON, or the error text."""
    from mcp.client.client import Client

    server = mcp_server.build_server(lb.root, **options)

    async def run() -> Any:
        async with Client(server) as client:
            result = await client.call_tool(name, arguments or {})
            text = result.content[0].text  # type: ignore[union-attr]
            if result.is_error:
                return {"error": text}
            return json.loads(text)

    return asyncio.run(run())


def _list(lb: Logbook) -> list[Any]:
    from mcp.client.client import Client

    server = mcp_server.build_server(lb.root)

    async def run() -> list[Any]:
        async with Client(server) as client:
            return list((await client.list_tools()).tools)

    return asyncio.run(run())


# -- the tool list ----------------------------------------------------------------------------------


def test_the_tools_are_listed_with_their_schemas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    lb = _record(tmp_path, monkeypatch)
    tools = {t.name: t for t in _list(lb)}
    assert set(tools) == {
        "day", "days", "trips", "places", "people", "person", "promises", "gaps", "search",
        "add_note", "promise_done",
    }  # fmt: skip
    assert set(tools["days"].input_schema["properties"]) == {"from", "to"}
    assert tools["search"].input_schema["required"] == ["text"]
    assert tools["add_note"].input_schema["required"] == ["text"]
    assert tools["promise_done"].input_schema["required"] == ["id"]


def test_inspect_prints_the_tool_list_and_a_sample_call(capsys: pytest.CaptureFixture[str]):
    cli.main(["serve", "mcp", "--inspect"])  # no record, no server: the table alone
    out = capsys.readouterr().out
    for name in mcp_server.TOOLS:
        assert f"\n{name}(" in out or out.startswith(f"{name}(")
    start = out.index('{\n  "jsonrpc"')
    request = json.loads(out[start : out.index("\n}", start) + 2])
    assert request["method"] == "tools/call"
    assert request["params"]["name"] in mcp_server.TOOLS


# -- the gate (ADR 0016) ----------------------------------------------------------------------------


def test_a_tier_2_note_is_withheld_at_the_default_ceiling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    lb = _record(tmp_path, monkeypatch)
    _policy(lb, None)  # a record whose policy does not name mcp: the default ceiling is 1
    out = _call(lb, "day", {"date": NOTE_DAY})
    assert out["gate"] == {"destination": "mcp", "max_tier": 1, "withheld": out["gate"]["withheld"]}
    assert out["gate"]["withheld"] > 0
    assert SECRET not in json.dumps(out)
    assert "Ola" not in json.dumps(out)  # the resolution lines are tier 2 too: nobody is named
    assert out["data"]["day"] == NOTE_DAY

    _policy(lb, 2)
    out = _call(lb, "day", {"date": NOTE_DAY})
    assert out["gate"]["max_tier"] == 2
    assert SECRET in json.dumps(out)


def test_search_finds_the_note_only_above_the_ceiling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    lb = _record(tmp_path, monkeypatch)
    _policy(lb, 1)
    out = _call(lb, "search", {"text": "mooring photos"})
    assert out["data"]["hits"] == []
    assert out["gate"]["withheld"] >= 1
    _policy(lb, 2)
    out = _call(
        lb, "search", {"text": "MOORING photos", "kinds": ["note"], "since": NOTE_DAY, "until": NOTE_DAY}
    )
    [hit] = out["data"]["hits"]
    assert hit["kind"] == "note" and hit["tier"] == 2 and SECRET in hit["payload"]["text"]
    assert "hash" not in hit and "prev" not in hit
    out = _call(lb, "search", {"text": "mooring", "kinds": ["event"]})
    assert out["data"]["hits"] == []


def test_a_retracted_line_stays_hidden_whatever_the_ceiling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    lb = _record(tmp_path, monkeypatch)
    _policy(lb, 1)
    line = lb.append(
        at=utc(NOTE_DAY, "21:00"),
        source="manual",
        kind="note",
        tier=1,
        payload={"schema": "note/v1", "text": "wrong boat"},
    )
    assert _call(lb, "search", {"text": "wrong boat"})["data"]["hits"][0]["id"] == line["id"]
    lb.retract(int(line["seq"]), "a slip")  # the retraction is tier 2, above the ceiling, and still applies
    out = _call(lb, "search", {"text": "wrong boat"})
    assert out["data"]["hits"] == []
    assert _call(lb, "search", {"text": "a slip"})["data"]["hits"] == []  # a retraction is never a hit


def test_tier_3_crosses_only_when_the_policy_and_the_flag_both_say_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    lb = _record(tmp_path, monkeypatch)
    _policy(lb, 3)
    out = _call(lb, "search", {"text": "resting_hr"})
    assert out["gate"]["max_tier"] == 2 and out["data"]["hits"] == [] and out["gate"]["withheld"] == 1
    out = _call(lb, "search", {"text": "resting_hr"}, allow_tier_3=True)
    assert out["gate"]["max_tier"] == 3 and len(out["data"]["hits"]) == 1 and out["gate"]["withheld"] == 0


def test_a_broken_policy_is_one_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    lb = _record(tmp_path, monkeypatch)
    (lb.root / "policy" / "crossing.json").write_text('{"mcp": {"max_tier": 9}}', encoding="utf-8")
    out = _call(lb, "places")
    assert "crossing.json" in out["error"] and "mcp" in out["error"]


def test_init_names_the_mcp_destination_at_tier_1(tmp_path: Path):
    lb = Logbook.init(tmp_path / "fresh", TZ)
    assert policy.read(lb.root)["mcp"] == {"max_tier": 1}
    assert policy.mcp_ceiling(lb.root) == 1


# -- the read tools ---------------------------------------------------------------------------------


def test_the_readers_answer_from_the_record_and_write_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    lb = _record(tmp_path, monkeypatch)
    _policy(lb, 2)
    before = lb.meta_path.read_bytes()

    days = _call(lb, "days", {"from": "2026-06-08", "to": "2026-06-10"})["data"]
    assert [d["day"] for d in days] == ["2026-06-08", "2026-06-09", "2026-06-10"]
    trips = _call(lb, "trips", {"year": "2026"})["data"]
    assert trips["trips"] and trips["trips"][0]["route"]
    assert _call(lb, "trips", {"year": "1999"})["data"]["trips"] == []
    found = _call(lb, "places")["data"]
    assert {p["name"] for p in found} >= {"Home", "Office"}
    people = _call(lb, "people")["data"]
    names = {p["name"] for year in people["years"] for p in year["people"]}
    assert "Kari Nordmann" in names
    person = _call(lb, "person", {"name": "Kari"})["data"]
    assert person["name"] == "Kari Nordmann" and person["refs"][0]["value"] == KARI["email"]
    assert "nobody" in _call(lb, "person", {"name": "Nobody Atall"})["error"]
    promises = _call(lb, "promises", {"open": True})["data"]
    assert any(SECRET in p["quote"] for p in promises["proposals"])
    gaps = _call(lb, "gaps", {"since": "2026-06-08"})["data"]
    assert {s["source"] for s in gaps["sources"]} >= {"dawarich", "manual"}
    assert "not a date" in _call(lb, "day", {"date": "yesterday"})["error"]

    assert lb.meta_path.read_bytes() == before  # nothing appended, not even a crossing line


def test_people_and_promises_are_empty_at_the_default_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    lb = _record(tmp_path, monkeypatch)
    _policy(lb, 1)
    years = _call(lb, "people")["data"]["years"]
    assert years and all(
        year["people"] == [] for year in years
    )  # nobody resolved: no resolution line crossed
    # A display name a tier-1 calendar entry carries is that line's own content and crosses with it
    # (ADR 0016 rule 5: the request bounds what crosses, the overlay stays home), listed as unresolved.
    assert {p["name"] for year in years for p in year["unresolved"]} == {"Kari Nordmann"}
    assert _call(lb, "promises")["data"]["proposals"] == []
    assert "nobody" in _call(lb, "person", {"name": "Kari"})["error"]


# -- the write tools: Logbook.append and nothing else -----------------------------------------------


def test_add_note_appends_one_note_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    lb = _record(tmp_path, monkeypatch)
    _policy(lb, 1)
    seq = int(lb.meta["seq"])
    out = _call(
        lb, "add_note", {"text": "Called the yard about the crane.", "at": "2026-06-20T10:00:00+02:00"}
    )
    written = out["data"]
    assert written["seq"] == seq + 1 and written["at"] == "2026-06-20T08:00:00Z"
    assert written["kind"] == "note" and written["tier"] == 2 and written["readable"] is False
    line = lb.line_by_seq(seq + 1)
    assert line is not None and line["source"] == "manual"
    assert line["payload"] == {"schema": "note/v1", "text": "Called the yard about the crane."}
    assert lb.verify()[2] == []
    assert "zone" in _call(lb, "add_note", {"text": "x", "at": "2026-06-20T10:00:00"})["error"]
    assert "empty" in _call(lb, "add_note", {"text": "   "})["error"]
    assert int(lb.meta["seq"]) == seq + 1  # the refused calls wrote nothing


def test_promise_done_appends_the_task_line_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    lb = _record(tmp_path, monkeypatch)
    _policy(lb, 2)
    [proposal] = [p for p in _call(lb, "promises")["data"]["proposals"] if SECRET in p["quote"]]
    seq = int(lb.meta["seq"])
    out = _call(lb, "promise_done", {"id": proposal["id"]})["data"]
    assert out["seq"] == seq + 1 and out["kind"] == "task" and out["promise"] == proposal["id"]
    line = lb.line_by_seq(seq + 1)
    assert (
        line is not None
        and line["payload"]["status"] == "done"
        and line["payload"]["extra"]["promise"] == proposal["id"]
    )
    again = _call(lb, "promise_done", {"id": proposal["id"]})["data"]
    assert again["already_done"] is True and int(lb.meta["seq"]) == seq + 1
    assert all(
        p["status"] == "done" for p in _call(lb, "promises")["data"]["proposals"] if p["id"] == proposal["id"]
    )
    assert _call(lb, "promises", {"open": True})["data"]["proposals"] == [
        p for p in _call(lb, "promises")["data"]["proposals"] if p["id"] != proposal["id"]
    ]
    assert "no proposal" in _call(lb, "promise_done", {"id": "0000000000000000"})["error"]


def test_a_day_with_a_dinner_names_the_guest_only_at_tier_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    lb = _record(tmp_path, monkeypatch)
    lb.append_many(
        [event(utc("2026-06-17", "18:00"), utc("2026-06-17", "20:00"), "Supper", [attendee(KARI["email"])])]
    )
    _policy(lb, 1)
    text = json.dumps(_call(lb, "day", {"date": "2026-06-17"}))
    assert "Supper" in text and "Kari Nordmann" not in text
    _policy(lb, 2)
    text = json.dumps(_call(lb, "day", {"date": "2026-06-17"}))
    assert "Supper" in text and "Kari Nordmann" in text
