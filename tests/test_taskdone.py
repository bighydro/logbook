"""`logbook tasks`: the task/v1 lines (RFC 0016) as the tasks they are, the latest snapshot of each
standing; `--propose-done` finds, by rules alone, the mail, calendar entry or transaction that says an
open task was done; `tasks done <id> --evidence <line>` appends the closing task/v1 line and nothing
else. Synthetic Oslo persona; every address is at example.org."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from logbook import cli, taskdone
from logbook.store import Logbook

OWNER_EMAIL = "ines@example.org"
OLA_EMAIL = "ola@example.org"
FLIGHTS_MAIL = "Your booking confirmation: Oslo \u2013 Z\u00fcrich, 20 June"
TROMSO_MAIL = "Buchungsbest\u00e4tigung: Oslo \u2013 Troms\u00f8"


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main([*args])
    return capsys.readouterr().out


def _task(at: str, key: str, title: str, status: str = "open", **fields: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "task/v1",
        "raw_id": f"{key}@{at}",
        "title": title,
        "status": status,
        "modified_at": at,
        **fields,
    }
    if status == "done":
        payload["completed_at"] = at
    return {"at": at, "source": "google-takeout", "kind": "task", "tier": 2, "payload": payload}


def _mail(at: str, subject: str, direction: str = "received") -> dict[str, Any]:
    sender = {"email": OWNER_EMAIL} if direction == "sent" else {"email": "noreply@example.org"}
    return {
        "at": at,
        "source": "mail",
        "kind": "mail",
        "tier": 2,
        "payload": {
            "schema": "mail/v1",
            "raw_id": f"{OWNER_EMAIL}:{at}-{abs(hash(subject)) % 10**6}@mail.example.org",
            "thread": f"{at}@mail.example.org",
            "from": sender,
            "subject": subject,
            "direction": direction,
            "size": 1024,
        },
    }


def _event(at: str, end: str, title: str, source: str = "ios-calendar") -> dict[str, Any]:
    return {
        "at": at,
        "end": end,
        "source": source,
        "kind": "event",
        "tier": 1,
        "payload": {
            "schema": "event/v1",
            "raw_id": f"{source}-{at}@{at}",
            "title": title,
            "all_day": False,
            "attendees": [{"ref": {"kind": "email", "value": OLA_EMAIL}, "name": "Ola Nordmann"}],
        },
    }


def _transaction(at: str, merchant: str, amount: float) -> dict[str, Any]:
    return {
        "at": at,
        "source": "copilot",
        "kind": "transaction",
        "tier": 3,
        "payload": {
            "schema": "transaction/v1",
            "raw_id": f"tx-{at}-{merchant}",
            "amount": amount,
            "currency": "NOK",
            "merchant": merchant,
            "provider": "copilot",
        },
    }


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    meta = lb.meta
    meta["owner_emails"] = [OWNER_EMAIL]
    lb._save_meta(meta)
    drafts = [
        # the tasks: Google Tasks snapshots, each keyed by its source id and modification time
        _task("2026-06-08T06:30:00Z", "Zmxp", "Book flights to Zürich", due="2026-06-20", list="Work"),
        _task("2026-06-09T07:00:00Z", "Y2Fs", "Call Ola about the mooring", list="Boat"),
        _task("2026-06-10T07:00:00Z", "YmVy", "Pay the berth fee at Marina Solvind", list="Boat"),
        _task("2026-06-10T08:00:00Z", "dHJv", "Flüge nach Tromsø buchen", list="Reisen"),
        _task("2026-06-08T09:00:00Z", "cm9w", "Buy the long rope", list="Boat"),
        _task("2026-06-11T12:10:00Z", "cm9w", "Buy the long rope", status="done", list="Boat"),
        _task("2026-06-09T09:00:00Z", "cGxh", "Water the plants"),
        _task("2026-06-01T09:00:00Z", "aW5z", "Renew the boat insurance"),
        _task("2026-06-09T10:00:00Z", "cmV0", "Retract me"),
        # evidence that is, and evidence that only looks like it
        _mail("2026-06-12T10:00:00Z", FLIGHTS_MAIL),
        _mail("2026-06-13T10:00:00Z", "Zürich newsletter: 10 things to do this summer"),
        _mail("2026-06-13T11:00:00Z", "Book club: June reading"),
        _mail("2026-06-16T09:00:00Z", TROMSO_MAIL),
        _mail("2026-06-17T09:00:00Z", "Insurance renewal confirmed"),  # 16 days after the task
        _event("2026-06-15T13:00:00Z", "2026-06-15T13:30:00Z", "Call with Ola Nordmann"),
        _event("2026-06-15T13:00:00Z", "2026-06-15T13:30:00Z", "Call with Ola Nordmann", source="ics"),
        _event("2026-06-16T07:00:00Z", "2026-06-16T07:15:00Z", "Zürich standup"),
        _transaction("2026-06-05T10:00:00Z", "Marina Solvind", -1200.0),  # before the task was written
        _transaction("2026-06-14T10:00:00Z", "Marina Solvind", -1200.0),
        _transaction("2026-06-14T12:00:00Z", "Harbour Cafe", -85.0),
    ]
    lb.append_many(drafts)
    retract = next(line for line in lb.lines() if line["payload"].get("title") == "Retract me")
    lb.retract(int(retract["seq"]), "not a task")
    return lb


def _by_title(report: taskdone.Report) -> dict[str, taskdone.Task]:
    return {t.title: t for t in report.tasks}


def _line_id(lb: Logbook, **payload: Any) -> str:
    ((key, value),) = payload.items()
    found = [line for line in lb.lines() if line["payload"].get(key) == value]
    return str(found[0]["id"])


# -- the words -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "nouns", "verbs"),
    [
        ("Book flights to Zürich", ("flights", "zürich"), ("book",)),
        ("Call Ola about the mooring", ("ola", "mooring"), ("call",)),
        ("Pay the berth fee at Marina Solvind", ("berth", "fee", "marina", "solvind"), ("pay",)),
        ("Flüge nach Tromsø buchen", ("flüge", "tromsø"), ("buchen",)),
        ("Die Rechnung der Werft bezahlen", ("rechnung", "werft"), ("bezahlen",)),
        ("Ola anrufen", ("ola",), ("anrufen",)),
        ("Renew the boat insurance", ("boat", "insurance"), ("renew",)),
        ("Water the plants", ("water", "plants"), ()),
        ("Do it", (), ("do",)),
    ],
)
def test_the_key_nouns_of_a_title_are_its_content_words_in_english_and_german(
    title: str, nouns: tuple[str, ...], verbs: tuple[str, ...]
) -> None:
    words = taskdone.words_of(title)
    assert words.nouns == nouns and words.verbs == verbs


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Zürich", "zurich"),
        ("flights", "flight"),
        ("Tromsø", "tromso"),
        ("Flüge", "fluge"),
        ("Flug", "Flugtickets"),
    ],
)
def test_words_match_across_case_accents_plurals_and_german_compounds(a: str, b: str) -> None:
    assert taskdone.same_word(a, b)


@pytest.mark.parametrize(("a", "b"), [("ola", "olav"), ("tee", "teeth"), ("fee", "feel"), ("rope", "europe")])
def test_short_or_unrelated_words_do_not_match(a: str, b: str) -> None:
    assert not taskdone.same_word(a, b)


# -- the tasks -----------------------------------------------------------------------------------------


def test_tasks_are_the_latest_snapshot_per_source_id_and_a_retracted_line_is_out(lb: Logbook) -> None:
    report = taskdone.propose(lb)
    found = _by_title(report)
    assert set(found) == {
        "Book flights to Zürich",
        "Call Ola about the mooring",
        "Pay the berth fee at Marina Solvind",
        "Flüge nach Tromsø buchen",
        "Buy the long rope",
        "Water the plants",
        "Renew the boat insurance",
    }
    rope = found["Buy the long rope"]
    assert rope.status == "done" and rope.day == "2026-06-11" and rope.key == "cm9w"
    assert rope.id == taskdone.task_id("cm9w") and len(rope.id) == 16
    flights = found["Book flights to Zürich"]
    assert (flights.status, flights.due, flights.list, flights.day, flights.source) == (
        "open",
        "2026-06-20",
        "Work",
        "2026-06-08",
        "google-takeout",
    )
    assert flights.line == _line_id(lb, raw_id="Zmxp@2026-06-08T06:30:00Z")
    assert [t.day for t in report.tasks] == sorted(t.day for t in report.tasks)
    assert len({t.id for t in report.tasks}) == len(report.tasks)


# -- the evidence --------------------------------------------------------------------------------------


def _proposals(report: taskdone.Report, title: str) -> list[taskdone.Proposal]:
    return [p for p in report.proposals if p.task.title == title]


def test_a_booking_confirmation_mail_is_evidence_for_booking_the_flights(lb: Logbook) -> None:
    report = taskdone.propose(lb)
    (found,) = _proposals(report, "Book flights to Zürich")
    assert found.kind == "mail" and found.day == "2026-06-12"
    assert found.line == _line_id(lb, subject=FLIGHTS_MAIL)
    assert found.evidence.rule == "mail-confirmation" and found.evidence.shared == ("zürich",)
    assert found.text == FLIGHTS_MAIL


def test_a_german_booking_confirmation_is_evidence_for_a_german_task(lb: Logbook) -> None:
    report = taskdone.propose(lb)
    (found,) = _proposals(report, "Flüge nach Tromsø buchen")
    assert found.kind == "mail" and found.evidence.shared == ("tromsø",)
    assert found.line == _line_id(lb, subject=TROMSO_MAIL)


def test_a_calendar_entry_is_evidence_for_a_call_and_two_calendars_are_one_entry(lb: Logbook) -> None:
    report = taskdone.propose(lb)
    (found,) = _proposals(report, "Call Ola about the mooring")
    assert found.kind == "event" and found.day == "2026-06-15" and found.text == "Call with Ola Nordmann"
    assert found.evidence.rule == "event" and found.evidence.shared == ("ola",)
    assert found.line == _line_id(lb, raw_id="ios-calendar-2026-06-15T13:00:00Z@2026-06-15T13:00:00Z")
    assert found.lines == (found.line, _line_id(lb, raw_id="ics-2026-06-15T13:00:00Z@2026-06-15T13:00:00Z"))
    assert found.sources == ("ios-calendar", "ics")


def test_a_transaction_at_the_merchant_named_is_evidence_for_paying(lb: Logbook) -> None:
    report = taskdone.propose(lb)
    (found,) = _proposals(report, "Pay the berth fee at Marina Solvind")
    assert found.kind == "transaction" and found.day == "2026-06-14" and found.tier == 3
    assert found.evidence.rule == "transaction" and found.evidence.shared == ("marina", "solvind")
    assert found.line == _line_id(lb, raw_id="tx-2026-06-14T10:00:00Z-Marina Solvind")


def test_what_only_looks_like_evidence_is_not_proposed(lb: Logbook) -> None:
    report = taskdone.propose(lb)
    texts = {(p.task.title, p.text) for p in report.proposals}
    # a received mail that shares a noun but confirms nothing
    assert ("Book flights to Zürich", "Zürich newsletter: 10 things to do this summer") not in texts
    # a mail that shares only the task's verb
    assert all("Book club" not in text for _title, text in texts)
    # a calendar entry that shares one place name with a task that is no appointment
    assert ("Book flights to Zürich", "Zürich standup") not in texts
    # a transaction before the task was written, and one at another merchant
    assert [p.day for p in _proposals(report, "Pay the berth fee at Marina Solvind")] == ["2026-06-14"]
    assert all("Harbour Cafe" not in text for _title, text in texts)
    # evidence outside the fortnight after the task
    assert _proposals(report, "Renew the boat insurance") == []
    # a task with no evidence, and a task already done
    assert _proposals(report, "Water the plants") == [] and _proposals(report, "Buy the long rope") == []
    assert len(report.proposals) == 4
    assert report.matcher == {"name": "rules", "version": taskdone.RULES.version, "languages": ["en", "de"]}
    assert report.window_days == 14


def test_evidence_is_read_in_the_fortnight_after_the_task_only() -> None:
    at = "2026-06-01T09:00:00Z"
    task = taskdone.Task(
        "x", "k", "Renew the boat insurance", "open", None, None, at, "2026-06-01", 1, "l", "s"
    )
    assert taskdone.in_window(task, at) and taskdone.in_window(task, "2026-06-15T09:00:00Z")
    assert not taskdone.in_window(task, "2026-06-15T09:00:01Z")
    assert not taskdone.in_window(task, "2026-06-01T08:59:59Z")


# -- the command ---------------------------------------------------------------------------------------


def test_tasks_lists_the_tasks_and_open_hides_the_done(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _run(capsys, "tasks")
    assert out.startswith("7 tasks, 6 open")
    row = next(line for line in out.splitlines() if "Book flights" in line)
    assert "2026-06-08" in row and "08:30" in row and "open" in row
    assert "due 2026-06-20" in row and "Work" in row
    assert taskdone.task_id("Zmxp") in row
    row = next(line for line in out.splitlines() if "long rope" in line)
    assert "done" in row and "2026-06-11" in row
    assert "Retract me" not in out
    open_only = _run(capsys, "tasks", "--open")
    assert open_only.startswith("6 open tasks") and "long rope" not in open_only


def test_tasks_json_is_the_report(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    out = json.loads(_run(capsys, "tasks", "--json"))
    assert set(out) == {"open_only", "propose_done", "window_days", "matcher", "tasks", "proposals"}
    assert out["open_only"] is False and out["propose_done"] is False and out["matcher"] is None
    assert out["proposals"] == [] and len(out["tasks"]) == 7
    row = next(t for t in out["tasks"] if t["title"] == "Book flights to Zürich")
    assert set(row) == {"id", "key", "title", "status", "due", "list", "at", "day", "seq", "line", "source"}
    assert row["status"] == "open" and row["key"] == "Zmxp"


def test_propose_done_prints_proposals_with_the_evidence_line_id(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _run(capsys, "tasks", "--propose-done")
    head = out.splitlines()[0]
    assert head.startswith("4 open tasks") and "rules" in head and "not facts" in head
    assert "logbook tasks done <id> --evidence <line>" in head
    lines = out.splitlines()
    task_row = next(i for i, line in enumerate(lines) if "Book flights to Zürich" in line)
    assert taskdone.task_id("Zmxp") in lines[task_row]
    evidence = lines[task_row + 1]
    assert "2026-06-12" in evidence and "12:00" in evidence and "mail" in evidence
    assert "booking confirmation" in evidence
    assert _line_id(lb, subject=FLIGHTS_MAIL) in evidence
    call = next(line for line in lines if "Call with Ola Nordmann" in line)
    assert "×2 sources" in call and "event" in call
    assert "Zürich newsletter" not in out and "Book club" not in out and "standup" not in out
    assert "2 open tasks with no evidence found" in out
    out = json.loads(_run(capsys, "tasks", "--propose-done", "--json"))
    assert out["propose_done"] is True and out["matcher"]["name"] == "rules" and out["window_days"] == 14
    row = next(p for p in out["proposals"] if p["kind"] == "transaction")
    assert set(row) == {
        "task", "line", "lines", "kind", "source", "sources", "at", "day", "tier", "text", "evidence"
    }  # fmt: skip
    assert row["task"] == taskdone.task_id("YmVy") and row["text"] == "Marina Solvind"
    assert row["evidence"] == {"rule": "transaction", "shared": ["marina", "solvind"], "confidence": 0.7}


def test_done_appends_the_closing_task_line_and_nothing_else(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    flights = taskdone.task_id("Zmxp")
    evidence = _line_id(lb, subject=FLIGHTS_MAIL)
    before = _line_id(lb, raw_id="Zmxp@2026-06-08T06:30:00Z")
    seq = lb.meta["seq"]
    out = _run(capsys, "tasks", "done", flights, "--evidence", evidence)
    assert f"#{seq + 1}" in out and "done" in out and "Book flights to Zürich" in out
    assert lb.meta["seq"] == seq + 1
    task = lb.line_by_seq(seq + 1)
    assert task is not None
    assert (task["source"], task["kind"], task["tier"], task["end"]) == ("manual", "task", 2, None)
    payload = task["payload"]
    assert payload == {
        "schema": "task/v1",
        "raw_id": f"Zmxp@{task['at']}",
        "title": "Book flights to Zürich",
        "status": "done",
        "due": "2026-06-20",
        "completed_at": task["at"],
        "list": "Work",
        "modified_at": task["at"],
        "supersedes": before,
        "extra": {"evidence": evidence},
    }
    assert lb.verify()[2] == []
    listed = json.loads(_run(capsys, "tasks", "--json"))
    row = next(t for t in listed["tasks"] if t["id"] == flights)
    assert row["status"] == "done" and row["line"] == task["id"] and len(listed["tasks"]) == 7
    open_only = json.loads(_run(capsys, "tasks", "--open", "--json"))
    assert flights not in {t["id"] for t in open_only["tasks"]}
    proposed = json.loads(_run(capsys, "tasks", "--propose-done", "--json"))
    assert flights not in {p["task"] for p in proposed["proposals"]}


def test_done_without_evidence_closes_too_and_the_payload_says_nothing_of_evidence(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = lb.meta["seq"]
    _run(capsys, "tasks", "done", taskdone.task_id("cGxh"))
    task = lb.line_by_seq(seq + 1)
    assert task is not None and task["payload"]["title"] == "Water the plants"
    assert "extra" not in task["payload"] and "due" not in task["payload"] and "list" not in task["payload"]


def test_done_twice_appends_nothing_and_unknown_ids_are_refused(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    rope = taskdone.task_id("cm9w")
    seq = lb.meta["seq"]
    out = _run(capsys, "tasks", "done", rope)
    assert "already done" in out and lb.meta["seq"] == seq
    with pytest.raises(SystemExit) as e:
        cli.main(["tasks", "done", "0123456789abcdef"])
    assert e.value.code == 2 and "no task 0123456789abcdef" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        cli.main(["tasks", "done", taskdone.task_id("Zmxp"), "--evidence", "not-a-line"])
    assert e.value.code == 2 and "no line not-a-line" in capsys.readouterr().err
    assert lb.meta["seq"] == seq


def test_a_record_with_no_tasks_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append("2026-06-01T10:00:00Z", "manual", "note", 2, {"schema": "note/v1", "text": "Calm day."})
    assert _run(capsys, "tasks").startswith("no tasks")
    assert _run(capsys, "tasks", "--propose-done").startswith("no tasks")
    assert _run(capsys, "tasks", "--open").startswith("no tasks")
    assert json.loads(_run(capsys, "tasks", "--json"))["tasks"] == []


# -- the matcher is a value ----------------------------------------------------------------------------


class _Fake:
    """A stand-in for a later model-backed matcher: the same contract, another reading."""

    name = "fake-model"
    version = "0"

    def __call__(self, task: taskdone.Task, candidate: taskdone.Candidate) -> taskdone.Evidence | None:
        if "plants" in task.title and candidate.kind == "transaction":
            return taskdone.Evidence("model", ("plants",), 0.9)
        return None


def test_the_matcher_is_replaceable_without_changing_the_report(lb: Logbook) -> None:
    report = taskdone.propose(lb, matcher=_Fake())
    assert report.matcher == {"name": "fake-model", "version": "0"}
    assert [(p.task.title, p.text) for p in report.proposals] == [
        ("Water the plants", "Marina Solvind"),
        ("Water the plants", "Harbour Cafe"),
    ]
    assert report.proposals[0].evidence == taskdone.Evidence("model", ("plants",), 0.9)
    assert len(report.tasks) == 7
