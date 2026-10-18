"""The relationship reader, slice 1 (EXPERIMENTAL, `logbook/contrib/relationship/`): `people ask` asks a
real model, the cloud endpoint the dream uses (`model_client`, LOGBOOK_DREAM_*), under the reader's
own dated entry, `relationship` in `policy/crossing.json`. The endpoint is an in-process fake
(`model_client.send` replaced) under the `no_network` guard, so nothing here opens a connection; what
the fake was sent is what would have left the machine. The record is slice 0's synthetic June
(`tests/test_relationship_reader.py`): Ines Nordmann of Oslo and Ola Nordmann, who do not exist.

What is held: nothing above the entry's `max_tier` and nothing of a day the owner has not signed is in
the request; without the entry, without its `until` or after it, nothing is sent and one sentence says
so; the key never appears in what is said; every claim of the answer cites lines of the set or is
listed as unsupported; and asking writes nothing."""

from __future__ import annotations

import json
import urllib.error
from collections.abc import Callable
from datetime import date
from email.message import Message
from pathlib import Path
from typing import Any

import pytest
from circle import message
from persona import note, resolution, utc
from test_relationship_reader import (
    CREW,
    DIRECT,
    HIS,
    KARI,
    OLA,
    WINDOW,
    _entry,
    _files,
    _ingest,
    _record,
    _store,
)

from logbook import cli
from logbook.contrib import model_client
from logbook.contrib.relationship import ask, model, reader
from logbook.core import policy
from logbook.core.store import Logbook, uuid7

ENDPOINT = "https://api.example.org/v1"
MODEL = "xy-chat-1"  # no model of any provider: the fake answers whatever it is called
KEY = "-".join(("xy", "synthetic", "bearer", "0000", "a1b2c3d4"))  # no real token, and never said


def _env(monkeypatch: pytest.MonkeyPatch, key: str | None = KEY) -> None:
    monkeypatch.setenv(model_client.ENDPOINT_ENV, ENDPOINT)
    monkeypatch.setenv(model_client.MODEL_ENV, MODEL)
    if key is not None:
        monkeypatch.setenv(model_client.KEY_ENV, key)


def _cites_first(material: dict[str, Any]) -> dict[str, Any]:
    """An answer that cites the first line it was given, invents a reference and admits one guess."""
    first = material["lines"][0]["ref"]
    return {
        "answer": [
            {"text": "You planned the boat for Saturday.", "evidence": [first]},
            {"text": "Ola raced in a regatta.", "evidence": ["L99"]},
            {"text": "The trip seems to matter to you both.", "unsupported": True},
        ]
    }


def _fake(
    monkeypatch: pytest.MonkeyPatch, answer: Callable[[dict[str, Any]], Any] = _cites_first
) -> dict[str, Any]:
    """`model_client.send` replaced: `calls` holds each request body as it would have been sent,
    `headers` the last headers; `answer` makes the completion from the material."""
    seen: dict[str, Any] = {"calls": []}

    def send(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        seen["url"], seen["headers"] = url, dict(headers)
        seen["calls"].append(json.loads(json.dumps(body)))
        made = answer(json.loads(body["messages"][1]["content"]))
        return {"choices": [{"message": {"content": made if isinstance(made, str) else json.dumps(made)}}]}

    monkeypatch.setattr(model_client, "send", send)
    monkeypatch.setattr(model_client, "RETRY_PAUSE_S", 0.0)
    return seen


def _sent(seen: dict[str, Any]) -> dict[str, Any]:
    """The material of the last request, as the model read it."""
    data: dict[str, Any] = json.loads(seen["calls"][-1]["messages"][1]["content"])
    return data


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    code = 0
    try:
        cli.main(["people", *args])
    except SystemExit as e:
        code = int(e.code or 0)
    out, err = capsys.readouterr()
    return code, out, err


def _ask(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    return _run(capsys, "ask", "Ola Nordmann", "What did we plan for the boat?", *args)


def _tiers(lb: Logbook) -> dict[str, int]:
    return {str(line["id"]): int(line["tier"]) for line in lb.lines()}


@pytest.fixture
def june(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_network: list[str]
) -> tuple[Logbook, dict[str, str]]:
    lb, ids = _record(tmp_path, monkeypatch)
    _env(monkeypatch)
    return lb, ids


# -- what crosses ------------------------------------------------------------------------------------------


def test_the_request_carries_his_lines_as_references_and_nothing_above_the_tier(
    june: tuple[Logbook, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    no_network: list[str],
) -> None:
    lb, ids = june
    _ingest(lb)
    # the store is disposable and may be edited: plant his tier-3 line in it, and give a line of the
    # set the tier-3 words; neither crosses
    planted = {"id": "f" * 16, "speakers": [OLA["id"]], "role": "counterpart", "kind": "message"}
    planted |= {"at": utc("2026-06-15", "21:00"), "source": "whatsapp", "tier": 3}
    planted["text"] = "The test results came back fine."
    rows = _store(lb).joinpath("messages.jsonl").read_text(encoding="utf-8").splitlines()
    edited = [json.loads(row) for row in rows]
    edited[0]["text"] = "The test results came back fine."
    lines = json.loads(_store(lb).joinpath("lines.json").read_text(encoding="utf-8"))
    lines[planted["id"]] = ids["private"]
    _store(lb).joinpath("messages.jsonl").write_bytes(
        "".join(json.dumps(m) + "\n" for m in [*edited, planted]).encode("utf-8")
    )
    _store(lb).joinpath("lines.json").write_bytes(json.dumps(lines).encode("utf-8"))
    seen = _fake(monkeypatch)
    code, out, err = _ask(capsys, "--json")
    assert code == 0, err
    assert no_network == [], "the fake endpoint is the only way out, and it is in-process"
    [call] = seen["calls"]
    body = json.dumps(call)
    assert "test results" not in body, "no word of a tier-3 line, from the store or the record"
    material = _sent(seen)
    tiers = _tiers(lb)
    data = json.loads(out)
    served = {c["id"] for s in data["answer"] for c in s["evidence"] if c["line"] is not None}
    assert served <= {ids[n] for n in HIS}
    assert all(line["ref"].startswith("L") for line in material["lines"]), "references, never ids"
    assert not any(i in body for i in tiers), "no line id of the record crosses, only references"
    assert len(material["lines"]) == len(HIS) and data["withheld"] == 1
    assert set(material) == {"person", "window", "question", "lines"}, "nothing else of the record"
    assert material["person"] == OLA["name"] and material["window"] == {"from": WINDOW[0], "to": WINDOW[1]}
    assert call["model"] == MODEL and seen["url"] == ENDPOINT + "/chat/completions"
    # the references resolve back to his lines, every one at or under the ceiling in the record
    _entry(lb, 1, "2026-12-31")
    _ingest(lb)
    seen = _fake(monkeypatch)
    code, out, err = _ask(capsys, "--json")
    assert code == 0, err
    texts = {line["text"] for line in _sent(seen)["lines"]}
    assert texts == {"incoming call, answered, 25 min", "Sail planning"}, "tier 1 lets the call and the event"
    data = json.loads(out)
    assert data["max_tier"] == 1
    cited = [c["id"] for s in data["answer"] for c in s["evidence"] if c["line"] is not None]
    assert cited and all(tiers[i] <= 1 for i in cited)


def test_every_claim_cites_his_lines_or_is_listed_as_unsupported(
    june: tuple[Logbook, dict[str, str]], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb, ids = june
    _ingest(lb)

    def answer(material: dict[str, Any]) -> dict[str, Any]:
        by_text = {line["text"]: line["ref"] for line in material["lines"]}
        return {
            "answer": [
                {"text": "Ola said yes to Saturday.", "evidence": [by_text["Yes! Saturday."]]},
                {"text": "Ola had dinner at the marina.", "evidence": [ids["note"]]},  # a real line, not his
                {"text": "Ola raced in a regatta.", "evidence": ["L99"]},
                {"text": "Ola likes the fjord.", "evidence": []},
                {"text": "The trip seems to matter to you both.", "unsupported": True},
            ]
        }

    _fake(monkeypatch, answer)
    code, out, err = _ask(capsys, "--json")
    assert code == 0, err
    data = json.loads(out)
    assert [s["supported"] for s in data["answer"]] == [True, False, False, False, False]
    assert data["answer"][0]["evidence"][0]["id"] == ids["his"], "a reference turns back into his line"
    assert data["segments"][0] == {"text": "Ola said yes to Saturday.", "evidence": [ids["his"]]}
    assert all(s == {"text": s["text"], "unsupported": True} for s in data["segments"][1:]), "draft/v1"
    assert data["unsupported"] == 4 and data["model"] == MODEL
    assert data["answer"][4]["why"] == "the model says it rests on no line"
    code, out, err = _ask(capsys)
    rows = out.splitlines()
    heading = next(i for i, row in enumerate(rows) if row.startswith("unsupported:"))
    assert "  Ola said yes to Saturday." in rows[:heading] and ids["his"] in "\n".join(rows[:heading])
    claims = [row for row in rows[heading:] if row.startswith("  ~ ")]
    assert len(claims) == 4, "each claim that rests on no line of his is under `unsupported`"
    assert f"model:{MODEL}" in rows[0]


def test_a_line_on_a_day_the_owner_has_not_signed_crosses_only_when_the_entry_says_so(
    june: tuple[Logbook, dict[str, str]], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb, _ids = june
    july = message(utc("2026-06-30", "12:00"), DIRECT, "The mooring is booked for July.", OLA)
    july["id"] = uuid7()
    lb.append_many([july])  # on the 30th, the one day of June the owner has not signed
    found, _where = reader.ingest(lb, "Ola Nordmann", *WINDOW)
    assert str(july["id"]) not in {i.line for i in found.items} and found.unsigned == 1
    seen = _fake(monkeypatch)
    assert _ask(capsys)[0] == 0
    assert "mooring" not in json.dumps(seen["calls"]), "an unsigned day does not cross"
    path = policy.policy_path(lb.root)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["relationship"]["include_unsigned"] = True
    path.write_text(json.dumps(data), encoding="utf-8")
    code, _out, err = _ask(capsys)
    assert code == 2 and "changed" in err, "the store was read under the gate; the entry lifted it since"
    found, _where = reader.ingest(lb, "Ola Nordmann", *WINDOW)
    assert str(july["id"]) in {i.line for i in found.items} and found.unsigned == 0
    assert _ask(capsys)[0] == 0
    assert "mooring" in json.dumps(seen["calls"][-1]), "the entry says unsigned days may cross"


def test_a_name_whose_only_line_is_above_the_ceiling_never_crosses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], no_network: list[str]
) -> None:
    lb, _ids = _record(tmp_path, monkeypatch)
    _env(monkeypatch)
    secret = resolution(("phone", "+447700900077"), "019cadd3-6bc0-7dcd-9133-000000000077", "Kari Hemmelig")
    secret["tier"] = 3
    hers = {"name": "Kari Hemmelig", "phone": "+447700900077"}
    said = message(utc("2026-06-18", "10:00"), ("447700900077@s.whatsapp.net", "direct", "K"), "Hei", hers)
    lb.append_many([secret, said])
    seen = _fake(monkeypatch)
    code, _out, err = _run(capsys, "ingest", "Kari Hemmelig", "--window", *WINDOW)
    assert code == 2 and "above max_tier 2" in err
    assert not _store(lb).parent.joinpath("019cadd3-6bc0-7dcd-9133-000000000077").exists()
    code, _out, err = _run(capsys, "ask", "Kari Hemmelig", "Who is she?")
    assert code == 2 and "above max_tier 2" in err and seen["calls"] == [], "her name is above the ceiling"


# -- what does not cross -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entry", "said"),
    [
        (None, "names no 'relationship' entry"),
        ({"max_tier": 2}, "has no until"),
        ({"max_tier": 2, "until": "2026-06-30"}, "expired on 2026-06-30"),
    ],
    ids=["no entry", "no until", "expired"],
)
def test_without_the_entry_or_after_its_day_nothing_is_sent(
    entry: dict[str, Any] | None,
    said: str,
    june: tuple[Logbook, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    no_network: list[str],
) -> None:
    lb, _ids = june
    _ingest(lb)
    seen = _fake(monkeypatch)
    path = policy.policy_path(lb.root)
    path.write_text(json.dumps({} if entry is None else {"relationship": entry}), encoding="utf-8")
    before = _files(lb.root)
    code, out, err = _ask(capsys)
    assert code == 2 and said in err and out == ""
    assert len(err.strip().splitlines()) == 1, "one sentence"
    assert seen["calls"] == [] and no_network == [], "nothing was sent"
    assert _files(lb.root) == before


def test_the_dream_entry_is_not_the_relationship_entry(
    june: tuple[Logbook, dict[str, str]], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb, _ids = june
    _ingest(lb)
    seen = _fake(monkeypatch)
    path = policy.policy_path(lb.root)
    path.write_text(json.dumps({"dream": {"max_tier": 3, "until": "2026-12-31"}}), encoding="utf-8")
    code, _out, err = _ask(capsys)
    assert code == 2 and "names no 'relationship' entry" in err and seen["calls"] == []


def test_the_entry_names_the_one_model(
    june: tuple[Logbook, dict[str, str]], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb, _ids = june
    path = policy.policy_path(lb.root)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["relationship"]["model"] = "xy-chat-2"
    path.write_text(json.dumps(data), encoding="utf-8")
    _ingest(lb)
    seen = _fake(monkeypatch)
    code, _out, err = _ask(capsys)
    assert code == 2 and "names the model 'xy-chat-2'" in err and seen["calls"] == []
    monkeypatch.delenv(model_client.MODEL_ENV)
    assert _ask(capsys)[0] == 0 and seen["calls"][-1]["model"] == "xy-chat-2"


def test_the_key_never_appears_in_an_error(
    june: tuple[Logbook, dict[str, str]], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb, _ids = june
    _ingest(lb)

    def echoes(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        return {"error": {"message": f"Incorrect API key provided: {KEY}; or ...{KEY[-8:]}"}}

    def refuses(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        raise urllib.error.HTTPError(
            url, 401, f"Unauthorized for {headers['Authorization']}", Message(), None
        )

    def down(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        raise urllib.error.URLError(f"no route for key {KEY}")

    monkeypatch.setattr(model_client, "RETRY_PAUSE_S", 0.0)
    for send in (echoes, refuses, down):
        monkeypatch.setattr(model_client, "send", send)
        code, out, err = _ask(capsys)
        assert code == 1, f"{send.__name__}: the answer failed: {err}"
        assert KEY not in err + out and KEY[-8:] not in err + out, send.__name__
        assert "<key>" in err or "HTTP 401" in err
    seen = _fake(monkeypatch)
    code, out, err = _ask(capsys, "--show-prompt")
    assert code == 0 and KEY not in out + err, "the prompt shown is the messages, never a header"
    assert seen["headers"]["Authorization"] == f"Bearer {KEY}", "the key goes in the header, and only there"
    assert "Rules, each of them strict" in out
    code, _out, err = _run(capsys, "ingest", "Ola Nordmann", "--window", *WINDOW, "--show-prompt")
    assert code == 2 and "goes with `people ask`" in err


def test_an_answer_that_is_not_segments_fails_and_shows_nothing(
    june: tuple[Logbook, dict[str, str]], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb, _ids = june
    _ingest(lb)
    head, before = lb.meta["head"], _files(lb.root)
    for made in ("I think Saturday.", {"answer": "Saturday"}, {"answer": []}):
        _fake(monkeypatch, lambda _m, made=made: made)
        code, out, err = _ask(capsys)
        assert code == 1 and out == "" and "nothing is shown" in err, made
    _fake(monkeypatch, lambda m: [{"text": "Saturday.", "evidence": [m["lines"][0]["ref"]]}])
    assert _ask(capsys)[0] == 0, "a bare list of segments is taken"
    assert lb.meta["head"] == head and _files(lb.root) == before, "asking writes nothing"


def test_the_policy_is_read_today(
    june: tuple[Logbook, dict[str, str]], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb, _ids = june
    _ingest(lb)
    seen = _fake(monkeypatch)
    assert _ask(capsys)[0] == 0 and len(seen["calls"]) == 1
    monkeypatch.setattr(policy, "today", lambda: date(2027, 1, 1))
    code, _out, err = _ask(capsys)
    assert code == 2 and "expired on 2026-12-31" in err and len(seen["calls"]) == 1


def test_scrub_replaces_the_key_and_its_tail() -> None:
    assert model.scrub(f"bad key {KEY} and ...{KEY[-8:]}", KEY) == "bad key <key> and ...<key>"
    assert model.scrub("nothing to hide", None) == "nothing to hide"
    assert ask.MODEL is None, "the default is the endpoint"


def test_a_name_given_above_the_ceiling_never_crosses_and_the_one_under_it_still_asks(
    june: tuple[Logbook, dict[str, str]], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A tier-3 resolution line that names Ola, or Kari on his recorded call, otherwise: the name under
    the ceiling is the one he is asked by and the one that is sent; the tier-3 one never crosses."""
    lb, _ids = june
    hidden = []
    for person in (OLA, KARI):
        line = resolution(("email", person["email"]), person["id"], f"{person['name'].split()[0]} Hemmelig")
        line["tier"] = 3
        line["at"] = "2026-06-02T08:00:00Z"
        hidden.append(line)
    lb.append_many(hidden)
    _ingest(lb)
    seen = _fake(monkeypatch)
    code, _out, err = _ask(capsys)
    assert code == 0, err
    body = json.dumps(seen["calls"])
    assert "Hemmelig" not in body and KARI["name"] in body and _sent(seen)["person"] == OLA["name"]


def test_a_ceiling_above_two_is_refused_while_the_model_is_a_cloud_one(
    june: tuple[Logbook, dict[str, str]], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The owner's decision: nothing above tier 2 goes to the cloud model, whatever the entry says."""
    lb, _ids = june
    _ingest(lb)
    _entry(lb, 3, "2026-12-31")
    seen = _fake(monkeypatch)
    for args in (
        ("ask", "Ola Nordmann", "What did we plan?"),
        ("ingest", "Ola Nordmann", "--window", *WINDOW),
    ):
        code, _out, err = _run(capsys, *args)
        assert code == 2 and "max_tier 3" in err and "at most 2" in err, args
    assert seen["calls"] == []


def test_the_promises_of_his_lines_cross_and_no_other(
    june: tuple[Logbook, dict[str, str]], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A promise is read in the words of a line of his set and goes with that line; one in a group, a
    note or a line above the ceiling is never read."""
    lb, _ids = june
    day = "2026-06-21"
    mine = message(utc(day, "09:00"), DIRECT, "I will bring the charts on Saturday.")
    secret = message(utc(day, "10:00"), DIRECT, "I will send the test results tomorrow.", OLA)
    secret["tier"] = 3
    group = message(utc(day, "11:00"), CREW, "I will bake a cake for Ola tomorrow.", KARI)
    noted = note(utc(day, "22:00"), "I will call Ola about the regatta tomorrow.")
    lines = [mine, secret, group, noted]
    for line in lines:
        line["id"] = uuid7()
    lb.append_many(lines)
    _ingest(lb)
    seen = _fake(monkeypatch)
    assert _ask(capsys)[0] == 0
    sent = _sent(seen)["lines"]
    promised = [line for line in sent if line.get("promises")]
    assert [line["text"] for line in promised] == ["I will bring the charts on Saturday."]
    [said] = promised[0]["promises"]
    assert said["owed"] == "by_owner" and "charts" in said["quote"]
    body = json.dumps(seen["calls"])
    assert "test results" not in body and "cake" not in body and "regatta tomorrow" not in body
    assert _ask(capsys, "--json", "--show-prompt")[0] == 2, "the prompt would spoil the JSON"
