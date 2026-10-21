"""`logbook dream person NAME` (RFC 0036 amendment 1, unit `person`): a model reads one person's
authorized input set through the `relationship` entry's gate and writes one `draft/v1` line about
them, as `dream day` writes one about a day: `policy_version`, the evidence ids of the set or the
mark unsupported, `supersedes`, the dedupe of rule 1 with the window in its key. Refused without the
entry, and nothing is sent. The endpoint is an in-process fake under the `no_network` guard; the record
is slice 0's synthetic June of Ines and Ola Nordmann of Oslo, who do not exist."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from test_relationship_model import KEY, MODEL, _env, _fake
from test_relationship_reader import HIS, OLA, WINDOW, _entry, _files, _ingest, _record

from logbook import cli
from logbook.contrib import dream_person, model_client
from logbook.contrib.relationship import reader
from logbook.core import drafts, policy
from logbook.core.chain import Line
from logbook.core.store import Logbook


def _person(material: dict[str, Any]) -> dict[str, Any]:
    """Seven segments, two of them resting on no line given: under the 30 % the dream allows."""
    by_text = {line["text"]: line["ref"] for line in material["lines"]}
    return {
        "person": [
            {
                "text": "June with Ola was the boat.",
                "evidence": [by_text["Yes! Saturday."], by_text["Sail planning"]],
            },
            {"text": "He thanked you for the weekend.", "evidence": [by_text["Thanks for a great weekend."]]},
            {"text": "He brought the charts.", "evidence": ["L99"]},  # not given: unsupported
        ],
        "threads": [{"text": "A recorded crew call followed.", "evidence": [by_text[_crew(material)]]}],
        "promises": [{"text": "You asked him to bring the charts.", "evidence": [by_text[_mine(material)]]}],
        "questions": [
            {"text": "Did the charts arrive?", "evidence": [by_text["Charts for Saturday"]]},
            {"text": "Will you sail again in July?", "unsupported": True},
        ],
    }


def _mine(material: dict[str, Any]) -> str:
    return next(line["text"] for line in material["lines"] if line["text"].startswith("Boat on Saturday"))


def _crew(material: dict[str, Any]) -> str:
    return next(line["text"] for line in material["lines"] if line["kind"] == "transcript")


def _dream(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    code = 0
    try:
        cli.main(["dream", "person", "Ola Nordmann", "--window", *WINDOW, *args])
    except SystemExit as e:
        code = int(e.code or 0)
    out, err = capsys.readouterr()
    return code, out, err


def _drafts(lb: Logbook) -> list[Line]:
    return [line for line in lb.lines() if line.get("kind") == drafts.KIND]


@pytest.fixture
def june(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_network: list[str]
) -> tuple[Logbook, dict[str, str]]:
    lb, ids = _record(tmp_path, monkeypatch)
    _env(monkeypatch)
    monkeypatch.setattr(dream_person, "today", lambda: date(2026, 7, 1))
    return lb, ids


def test_dream_person_writes_one_draft_of_his_set(
    june: tuple[Logbook, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    no_network: list[str],
) -> None:
    lb, ids = june
    seen = _fake(monkeypatch, _person)
    code, out, err = _dream(capsys)
    assert code == 0, err
    assert no_network == []
    [line] = _drafts(lb)
    p = line["payload"]
    assert line["source"] == f"model:{MODEL}" and line["tier"] == 2, "the highest tier read: his set at 2"
    assert p["unit"] == "person" and p["subject"] == OLA["id"]
    assert p["window"] == {"from": WINDOW[0], "to": WINDOW[1]}
    assert p["read_count"] == len(HIS) and p["read_head"] != lb.meta["head"]  # the draft moved it since
    assert p["extra"]["policy_version"] == policy.version(
        policy.Ceiling("relationship", 2, date(2026, 12, 31), False)
    )
    assert p["extra"]["entry"] == "relationship" and p["extra"]["signed_only"] is True
    parts = ["person", "person", "person", "threads", "promises", "questions", "questions"]
    assert p["extra"]["parts"] == parts
    supported, thanks, invented, thread, promise, asked, question = p["segments"]
    assert supported == {"text": "June with Ola was the boat.", "evidence": [ids["his"], ids["meeting"]]}
    assert thanks["evidence"] == [ids["thanks"]] and promise["evidence"] == [ids["mine"]]
    assert invented == {"text": "He brought the charts.", "unsupported": True}, "rule 6: never written"
    assert thread["evidence"] == [ids["recorded"]] and asked["evidence"] == [ids["his_mail"]]
    assert question == {"text": "Will you sail again in July?", "unsupported": True}
    every = {e for s in p["segments"] for e in s.get("evidence", [])}
    assert every <= {ids[n] for n in HIS}, "evidence only ever names lines of his set"
    assert drafts.validate(p) == []
    body = json.dumps(seen["calls"])
    assert "test results" not in body and "says hi" not in body and "Dinner with" not in body
    assert not any(ids[n] in body for n in ("private", "group", "note", "his", "meeting")), "refs, not ids"
    assert KEY not in out + err and f"#{line['seq']}" in out and "unsupported" in out


def test_the_same_person_at_the_same_head_and_window_writes_nothing_and_another_window_supersedes(
    june: tuple[Logbook, dict[str, str]], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """RFC 0036 rule 1 for a person: the key is (source, unit, subject, window, read_head) and the
    entry; a draft at this head, as when a write failed half-way, is not sent again."""
    lb, _ids = june
    seen = _fake(monkeypatch, _person)
    assert _dream(capsys)[0] == 0
    [first] = _drafts(lb)
    head = str(lb.meta["head"])
    payload = dict(first["payload"]) | {"read_head": head, "supersedes": first["id"]}
    lb.append("2026-07-01T05:00:00Z", f"model:{MODEL}", drafts.KIND, 2, payload)
    standing = _drafts(lb)[-1]
    calls = len(seen["calls"])
    with monkeypatch.context() as m:  # read as the half-way write read: at the head it names
        m.setattr(dream_person, "head_of", lambda _lb: head)
        code, _out, err = _dream(capsys)
    assert code == 2 and "nothing new to dream" in err and len(seen["calls"]) == calls, "nothing sent"
    later = _fake(
        monkeypatch,
        lambda m: {"person": [{"text": "Mail, then a call.", "evidence": [m["lines"][0]["ref"]]}]},
    )
    code, _out, err = _run_window(capsys, "2026-06-10", "2026-06-30")
    assert code == 0, err
    latest = _drafts(lb)[-1]
    assert latest["payload"]["window"] == {"from": "2026-06-10", "to": "2026-06-30"}, "another window"
    assert latest["payload"]["supersedes"] == standing["id"], "the standing person draft, whatever its window"
    assert len(later["calls"]) == 1


def _run_window(capsys: pytest.CaptureFixture[str], first: str, last: str) -> tuple[int, str, str]:
    code = 0
    try:
        cli.main(["dream", "person", "Ola Nordmann", "--window", first, last])
    except SystemExit as e:
        code = int(e.code or 0)
    out, err = capsys.readouterr()
    return code, out, err


@pytest.mark.parametrize(
    "entry",
    [None, {"max_tier": 2}, {"max_tier": 2, "until": "2026-06-30"}, "dream-only"],
    ids=["no entry", "no until", "expired", "the dream entry alone"],
)
def test_dream_person_is_refused_without_the_entry_and_sends_nothing(
    entry: Any,
    june: tuple[Logbook, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    no_network: list[str],
) -> None:
    lb, _ids = june
    path = policy.policy_path(lb.root)
    data: dict[str, Any] = {}
    if entry == "dream-only":
        data = {"dream": {"max_tier": 3, "until": "2026-12-31"}}
    elif entry is not None:
        data = {"relationship": entry}
    path.write_text(json.dumps(data), encoding="utf-8")
    seen = _fake(monkeypatch, _person)
    before = _files(lb.root)
    code, _out, err = _dream(capsys)
    assert code == 2 and "relationship" in err and len(err.strip().splitlines()) == 1
    assert seen["calls"] == [] and no_network == [] and _files(lb.root) == before


def test_a_relationship_entry_at_tier_3_is_refused_by_people_ask_and_dream_person(
    june: tuple[Logbook, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    no_network: list[str],
) -> None:
    """`CLOUD_CEILING`, the owner's decision of 18 Oct 2026: nothing above tier 2 goes to the cloud
    model, whatever the entry says. Both readers refuse, naming the ceiling, and no request is made."""
    lb, _ids = june
    _entry(lb, 3, "2026-12-31")
    with monkeypatch.context() as m:  # a store built under the entry, so only the ceiling stands between
        m.setattr(reader, "CLOUD_CEILING", 3)
        _ingest(lb)
    seen = _fake(monkeypatch, _person)
    before = _files(lb.root)
    for argv in (
        ["people", "ask", "Ola Nordmann", "What did we plan for the boat?"],
        ["dream", "person", "Ola Nordmann", "--window", *WINDOW],
    ):
        with pytest.raises(SystemExit) as e:
            cli.main(argv)
        err = capsys.readouterr().err
        assert e.value.code == 2 and "max_tier 3" in err and f"at most {reader.CLOUD_CEILING}" in err, argv
    assert seen["calls"] == [] and no_network == [], "no request was made"
    assert _files(lb.root) == before and _drafts(lb) == []


def test_dream_person_reads_nothing_above_the_ceiling_and_takes_its_tier(
    june: tuple[Logbook, dict[str, str]], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb, _ids = june
    _entry(lb, 1, "2026-12-31")

    def answer(material: dict[str, Any]) -> dict[str, Any]:
        return {"person": [{"text": "A call in June.", "evidence": [material["lines"][0]["ref"]]}]}

    seen = _fake(monkeypatch, answer)
    code, _out, err = _dream(capsys)
    assert code == 0, err
    [line] = _drafts(lb)
    assert line["tier"] == 1 and line["payload"]["read_count"] == 2
    texts = {x["text"] for x in json.loads(seen["calls"][0]["messages"][1]["content"])["lines"]}
    assert texts == {"incoming call, answered, 25 min", "Sail planning"}


def test_an_answer_mostly_unsupported_is_refused_and_the_key_is_never_said(
    june: tuple[Logbook, dict[str, str]], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb, _ids = june
    _fake(monkeypatch, lambda _m: {"person": [{"text": "He seems tired.", "unsupported": True}]})
    code, _out, err = _dream(capsys)
    assert code == 1 and "nothing was written" in err and _drafts(lb) == []

    def echoes(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        return {"error": {"message": f"Incorrect API key provided: {KEY}"}}

    monkeypatch.setattr(model_client, "send", echoes)
    code, out, err = _dream(capsys)
    assert code == 1 and KEY not in out + err and "<key>" in err and _drafts(lb) == []
    _fake(monkeypatch, _person)
    code, out, err = _dream(capsys, "--dry-run", "--show-prompt")
    assert code == 0 and "dry run, nothing written" in out and KEY not in out + err and _drafts(lb) == []


def test_dream_person_refuses_a_window_past_today_and_the_owner(
    june: tuple[Logbook, dict[str, str]], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb, _ids = june
    seen = _fake(monkeypatch, _person)
    code, _out, err = _run_window(capsys, "2026-06-01", "2026-07-02")
    assert code == 2 and "after today" in err
    code, _out, err = _run_window(capsys, "2026-06-30", "2026-06-01")
    assert code == 2 and "backwards" in err
    with pytest.raises(SystemExit) as e:
        cli.main(["dream", "person", "Ines Nordmann", "--window", *WINDOW])
    assert e.value.code == 2 and "owner" in capsys.readouterr().err, (
        "the owner is never a person of their record"
    )
    with pytest.raises(SystemExit) as e:
        cli.main(["dream", "week", "--window", *WINDOW])
    assert e.value.code == 2 and "--window goes with `dream person" in capsys.readouterr().err
    assert seen["calls"] == [] and _drafts(lb) == []


def test_a_person_draft_has_a_window_and_another_unit_has_none() -> None:
    person = {
        "schema": drafts.SCHEMA,
        "unit": drafts.UNIT_PERSON,
        "subject": OLA["id"],
        "window": {"from": "2026-06-01", "to": "2026-06-30"},
        "read_head": "a" * 64,
        "read_count": 7,
        "language": "en",
        "segments": [{"text": "The boat.", "unsupported": True}],
    }
    assert drafts.validate(person) == []
    assert drafts.validate({k: v for k, v in person.items() if k != "window"})
    assert drafts.validate(person | {"window": {"from": "2026-06-30", "to": "2026-06-01"}})
    assert drafts.validate(person | {"subject": [OLA["id"]]})
    day = person | {"unit": "day", "subject": "2026-06-13"}
    assert drafts.validate(day), "a window is a person draft's alone"
    assert drafts.validate({k: v for k, v in day.items() if k != "window"}) == []
