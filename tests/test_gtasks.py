"""`logbook sync gtasks`: the owner's Google Tasks as events, from the Tasks API v1, read-only, with the
service account `sync drive` uses (`tests/test_service_account.py`). A task seen open for the first time
is a `created` line, a task done is a `completed` line with how long it was open; a due day passing is no
event, an edit is no second `created`, a deletion writes nothing. The title is the line's title; the notes
are never stored, only their digest and word count.

Against the in-process fake of `tests/google_fake.py`: Ines Nordmann's two lists, Inbox and Boat. Nobody
in them exists, and nothing leaves the process (`no_network`)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from google_fake import DRIVE_SCOPE, TASKS_SCOPE, USER, Fake, private_key, write_key

from logbook import cli
from logbook.contrib import adapters, doctor
from logbook.contrib.adapters import drive, gtasks, service_account
from logbook.core.store import Logbook

KEY_ENV, USER_ENV = service_account.KEY_ENV, service_account.USER_ENV
NOTES = "30 m, 12 mm.\r\nAsk at the chandlery."


def _task(task_id: str, title: str, updated: str, **more: Any) -> dict[str, Any]:
    return {
        "kind": "tasks#task",
        "id": task_id,
        "title": title,
        "updated": f"{updated}.000Z",
        "status": "needsAction",
        "position": "00000000000000000001",
        "selfLink": f"https://www.googleapis.com/tasks/v1/lists/x/tasks/{task_id}",
        **more,
    }


def _done(task_id: str, title: str, updated: str, completed: str, **more: Any) -> dict[str, Any]:
    return _task(task_id, title, updated, status="completed", completed=f"{completed}.000Z", **more)


LISTS = [
    {"kind": "tasks#taskList", "id": "L-inbox", "title": "Inbox", "updated": "2026-09-14T10:05:00.000Z"},
    {"kind": "tasks#taskList", "id": "L-boat", "title": "Boat", "updated": "2026-09-14T09:30:00.000Z"},
]


def _tasks() -> dict[str, list[dict[str, Any]]]:
    return {
        "L-inbox": [
            _task(
                "t1", "Buy the  long rope", "2026-09-14T08:00:00", due="2026-09-20T00:00:00.000Z", notes=NOTES
            ),
            _done("t2", "Call Ola about the mooring", "2026-09-14T10:05:00", "2026-09-14T10:00:00"),
            _task("t6", "   ", "2026-09-14T08:30:00"),
        ],
        "L-boat": [
            _task(
                "t3",
                "Renew the boat insurance",
                "2026-09-14T09:00:00",
                webViewLink="https://tasks.google.com/t3",
            ),
            _task("t4", "Old idea", "2026-09-14T09:30:00", deleted=True),
            _done("t5", "Varnish the tiller", "2026-09-10T16:00:00", "2026-09-10T16:00:00", hidden=True),
            _task("t7", "Ask two brokers", "2026-09-14T09:05:00", parent="t3"),
        ],
    }


LINES = 5  # created t1, t3, t7; completed t2, t5 (first seen done: no created line)


@pytest.fixture(scope="module")
def key() -> Any:
    return private_key()


@pytest.fixture
def fake(tmp_path: Path, key: Any, monkeypatch: pytest.MonkeyPatch, no_network: list[str]) -> Any:
    server = Fake(key, lists=[dict(x) for x in LISTS], tasks=_tasks())
    server.waits = []  # type: ignore[attr-defined]
    monkeypatch.setattr(service_account, "send", server)
    monkeypatch.setattr(service_account, "sleep", server.waits.append)  # type: ignore[attr-defined]
    monkeypatch.setenv(KEY_ENV, str(write_key(tmp_path / "google-sa.json", key)))
    monkeypatch.setenv(USER_ENV, USER)
    yield server
    assert no_network == [], "the fake is the only way out"


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    return lb


def _config() -> service_account.Account:
    account = gtasks.configure(os.environ)
    assert account is not None
    return account


def _pull(**kw: Any) -> tuple[list[dict[str, Any]], dict[str, int]]:
    counts: dict[str, int] = {}
    return list(gtasks.pull(_config(), counts=counts, timezone="Europe/Oslo", **kw)), counts


def _by(drafts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {d["payload"]["raw_id"]: d for d in drafts}


def _tasks_calls(fake: Fake) -> list[dict[str, Any]]:
    return [p for _m, path, p in fake.requests if path.endswith("/tasks") and "/lists/" in path]


# -- registry and configuration -------------------------------------------------------------------


def test_registry_has_gtasks_as_a_live_adapter_of_tier_2_event_lines() -> None:
    assert adapters.live("gtasks") is gtasks
    assert gtasks.ENV == drive.ENV == service_account.ENV, "one place to configure both"
    assert (gtasks.KIND, gtasks.TIER, gtasks.SCOPE) == ("event", 2, TASKS_SCOPE)


# -- the lines ------------------------------------------------------------------------------------


def test_pull_writes_created_for_an_open_task_and_completed_for_a_done_one(fake: Fake) -> None:
    drafts, counts = _pull()
    assert sorted(_by(drafts)) == ["t1/created", "t2/completed", "t3/created", "t5/completed", "t7/created"]
    assert [d["at"] for d in drafts] == sorted(d["at"] for d in drafts)
    assert counts == {"skipped_no_title": 1, "skipped_deleted": 1}
    assert {(d["source"], d["kind"], d["tier"], d["tz"]) for d in drafts} == {
        ("gtasks", "event", 2, "Europe/Oslo")
    }


def test_a_created_line_has_the_title_the_list_the_due_day_and_a_reference(fake: Fake) -> None:
    drafts, _ = _pull()
    line = _by(drafts)["t1/created"]
    payload = line["payload"]
    assert line["at"] == "2026-09-14T08:00:00Z" and line["end"] is None
    assert payload["title"] == "Buy the long rope"
    assert (
        payload["calendar"] == {"id": "google-tasks", "name": "Google Tasks"} and payload["all_day"] is False
    )
    assert payload["modified_at"] == "2026-09-14T08:00:00Z"
    extra = payload["extra"]
    assert extra["activity"] == "created" and extra["list"] == "Inbox" and extra["due"] == "2026-09-20"
    assert extra["task"] == {"id": "t1", "list_id": "L-inbox"}
    assert _by(drafts)["t3/created"]["payload"]["extra"]["task"]["url"] == "https://tasks.google.com/t3"
    assert _by(drafts)["t7/created"]["payload"]["extra"]["parent"] == "t3"


def test_the_notes_are_a_digest_and_a_word_count_never_the_words(fake: Fake) -> None:
    drafts, _ = _pull()
    notes = _by(drafts)["t1/created"]["payload"]["extra"]["notes"]
    plain = NOTES.replace("\r\n", "\n")
    assert notes == {"sha256": hashlib.sha256(plain.encode("utf-8")).hexdigest(), "words": 8}
    text = json.dumps(drafts)
    assert "chandlery" not in text and "12 mm" not in text
    assert "notes" not in _by(drafts)["t3/created"]["payload"]["extra"]


def test_a_task_first_seen_done_is_one_completed_line_open_for_an_unknown_time(fake: Fake) -> None:
    drafts, _ = _pull()
    line = _by(drafts)["t2/completed"]
    assert line["at"] == "2026-09-14T10:00:00Z" and line["payload"]["title"] == "Call Ola about the mooring"
    extra = line["payload"]["extra"]
    assert extra["activity"] == "completed" and extra["list"] == "Inbox" and extra["open_for_s"] is None
    assert "t2/created" not in _by(drafts), "the record never saw it open: its creation is not a line"
    assert _by(drafts)["t5/completed"]["at"] == "2026-09-10T16:00:00Z", (
        "a done task cleared from the list too"
    )


def test_completed_is_open_for_since_the_created_line_the_record_holds(fake: Fake) -> None:
    created = {"at": "2026-09-14T08:00:00Z", "payload": {"raw_id": "t1/created"}}
    asked: list[tuple[str, str]] = []

    def held(keys: Any) -> dict[tuple[str, str], dict[str, Any]]:
        keys = list(keys)
        asked.extend(keys)
        return {("gtasks", "t1/created"): created} if ("gtasks", "t1/created") in keys else {}

    fake.tasks["L-inbox"][0].update(
        status="completed", completed="2026-09-16T12:00:00.000Z", updated="2026-09-16T12:00:30.000Z"
    )
    drafts, _ = _pull(held=held)
    line = _by(drafts)["t1/completed"]
    assert line["at"] == "2026-09-16T12:00:00Z" and line["payload"]["extra"]["open_for_s"] == 52 * 3600
    assert ("gtasks", "t1/created") in asked and ("gtasks", "t1/completed") in asked


def test_due_passing_without_completion_is_no_event(fake: Fake) -> None:
    drafts, _ = _pull()
    assert {d["payload"]["extra"]["activity"] for d in drafts} == {"created", "completed"}
    assert [d for d in drafts if d["payload"]["extra"]["task"]["id"] == "t1"] == [_by(drafts)["t1/created"]]


# -- what is asked, and how -----------------------------------------------------------------------


def test_every_list_is_asked_for_every_task_done_hidden_and_deleted_from_since(fake: Fake) -> None:
    _pull(since="2026-09-14T09:00:00Z")
    calls = _tasks_calls(fake)
    assert {c["showCompleted"] for c in calls} == {c["showHidden"] for c in calls} == {"true"}
    assert {c["showDeleted"] for c in calls} == {"true"} and {c["maxResults"] for c in calls} == {"100"}
    assert {c["updatedMin"] for c in calls} == {"2026-09-14T09:00:00Z"}


def test_since_keeps_the_tasks_changed_from_then_on(fake: Fake) -> None:
    drafts, _ = _pull(since="2026-09-14T09:00:00Z")
    assert sorted(_by(drafts)) == ["t2/completed", "t3/created", "t7/created"]


def test_pull_pages_lists_and_tasks_until_the_last_page(fake: Fake) -> None:
    fake.page = 2
    reported: list[int] = []
    drafts, _ = _pull(progress=lambda n, _s: reported.append(n))
    assert len(drafts) == LINES
    tokens = [c.get("pageToken") for c in _tasks_calls(fake)]
    assert tokens == [None, "2", None, "2"]
    assert reported[-1] == 7 and reported == sorted(reported)


def test_pull_backs_off_on_5xx_and_carries_on(fake: Fake) -> None:
    fake.fail(503)
    fake.fail(429, retry_after="5")
    drafts, _ = _pull()
    assert len(drafts) == LINES and fake.waits == [1.0, 5.0]  # type: ignore[attr-defined]


def test_the_client_only_reads(fake: Fake) -> None:
    _pull()
    assert fake.methods() == {("POST", "oauth2.googleapis.com"), ("GET", "tasks.googleapis.com")}
    assert {c["scope"] for c in fake.assertions} == {TASKS_SCOPE}


def test_watermark_is_the_tasks_last_change_and_resume_looks_back_a_day(fake: Fake) -> None:
    drafts, _ = _pull()
    line = _by(drafts)["t2/completed"]
    assert gtasks.watermark(line) == "2026-09-14T10:05:00Z"
    assert gtasks.resume(_config(), "2026-09-14T10:05:00Z") == "2026-09-13T10:05:00Z"
    assert gtasks.group(line) == "Inbox"


# -- sync: the CLI --------------------------------------------------------------------------------


def _sync(*args: str, source: str = "gtasks") -> int:
    try:
        cli.main(["sync", source, *args])
    except SystemExit as e:
        return int(e.code or 0)
    return 0


def _lines(lb: Logbook) -> dict[str, dict[str, Any]]:
    return {line["payload"]["raw_id"]: line for line in lb.lines() if line["source"] == "gtasks"}


def test_sync_first_run_writes_every_line_and_the_second_none(lb: Logbook, fake: Fake, capsys: Any) -> None:
    assert _sync() == 0
    out = capsys.readouterr().out
    assert f"gtasks: {LINES} new lines of {LINES} seen from the beginning" in out
    assert "Inbox: 2 new of 2 seen" in out and "Boat: 3 new of 3 seen" in out
    assert "skipped 1 without a title, 1 deleted" in out
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == LINES
    state = json.loads((lb.root / "state" / "gtasks.json").read_text(encoding="utf-8"))
    assert state["since"] == "2026-09-14T10:05:00Z"
    assert _sync() == 0
    assert "gtasks: 0 new lines of" in capsys.readouterr().out
    assert lb.meta["seq"] == LINES


def test_sync_a_task_done_later_is_completed_with_how_long_it_was_open(
    lb: Logbook, fake: Fake, capsys: Any
) -> None:
    _sync()
    fake.tasks["L-inbox"][0].update(
        status="completed", completed="2026-09-16T12:00:00.000Z", updated="2026-09-16T12:00:30.000Z"
    )
    assert _sync() == 0
    assert "gtasks: 1 new lines of" in capsys.readouterr().out
    done = _lines(lb)["t1/completed"]
    assert done["payload"]["extra"]["open_for_s"] == 52 * 3600 and done["tier"] == 2


def test_sync_a_task_updated_twice_is_not_two_created_lines(lb: Logbook, fake: Fake, capsys: Any) -> None:
    _sync()
    boat = fake.tasks["L-boat"][0]
    boat.update(title="Renew the boat insurance before October", updated="2026-09-15T09:00:00.000Z")
    assert _sync() == 0
    boat.update(notes="Two quotes.", updated="2026-09-15T10:00:00.000Z")
    capsys.readouterr()
    assert _sync() == 0
    assert "gtasks: 0 new lines of" in capsys.readouterr().out
    created = [key for key in _lines(lb) if key.startswith("t3/")]
    assert created == ["t3/created"] and lb.meta["seq"] == LINES
    assert _lines(lb)["t3/created"]["payload"]["title"] == "Renew the boat insurance", (
        "the line is never rewritten"
    )


def test_sync_a_deleted_task_writes_nothing_new(lb: Logbook, fake: Fake, capsys: Any) -> None:
    _sync()
    fake.tasks["L-boat"][3].update(deleted=True, updated="2026-09-15T08:00:00.000Z")
    assert _sync() == 0
    out = capsys.readouterr().out
    assert "gtasks: 0 new lines of" in out and "1 deleted" in out
    assert lb.meta["seq"] == LINES and "t7/created" in _lines(lb), "what was written stays"


def test_sync_a_reopened_task_never_seen_open_is_no_created_line(lb: Logbook, fake: Fake) -> None:
    _sync()
    fake.tasks["L-inbox"][1].update(status="needsAction", updated="2026-09-15T08:00:00.000Z")
    del fake.tasks["L-inbox"][1]["completed"]
    assert _sync() == 0
    assert "t2/created" not in _lines(lb) and lb.meta["seq"] == LINES


def test_sync_since_is_used_as_given(lb: Logbook, fake: Fake, capsys: Any) -> None:
    assert _sync("--since", "2026-09-14T09:00:00Z") == 0
    assert "gtasks: 3 new lines of 3 seen since 2026-09-14T09:00:00Z" in capsys.readouterr().out
    assert sorted(_lines(lb)) == ["t2/completed", "t3/created", "t7/created"]


def test_sync_dry_run_counts_and_writes_nothing(lb: Logbook, fake: Fake, capsys: Any) -> None:
    assert _sync("--dry-run") == 0
    assert f"gtasks: {LINES} lines from the beginning (dry run, nothing written)" in capsys.readouterr().out
    assert lb.meta["seq"] == 0 and not (lb.root / "state").exists()


def test_sync_without_the_tasks_scope_delegated_is_one_line_and_exit_1(
    lb: Logbook, fake: Fake, capsys: Any
) -> None:
    fake.delegated = {DRIVE_SCOPE}  # the delegation grants Drive, not Tasks
    assert _sync() == 1
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and err.startswith("sync: gtasks:") and TASKS_SCOPE in err


# -- the two sources together: doctor, sync --all, the schedule ------------------------------------


def test_doctor_shows_sync_drive_and_sync_gtasks(lb: Logbook, fake: Fake) -> None:
    checks = {c.name: c for c in doctor.run(lb, dict(os.environ), installed=lambda _m: True)}
    for name in ("sync:drive", "sync:gtasks"):
        assert checks[name].status == "pass" and f"configured ({KEY_ENV}, {USER_ENV})" in checks[name].detail
    assert fake.requests == [], "doctor asks Google nothing"


def test_doctor_without_the_variables_lists_neither(lb: Logbook) -> None:
    names = {c.name for c in doctor.run(lb, {}, installed=lambda _m: True)}
    assert "sync:drive" not in names and "sync:gtasks" not in names


def test_sync_all_runs_both_with_the_two_variables_and_nothing_else(
    lb: Logbook, fake: Fake, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """What the schedule runs (`sync --scheduled` is `sync --all`, then doctor): the two variables in the
    environment, from `~/.config/logbook/sync.env`, are all either source needs."""
    from google_fake import activity, item

    fake.drive = [activity("2026-09-14T09:10:00.000Z", {"edit": {}}, item("1BudgetSheet", "Budget 2027"))]
    monkeypatch.setattr(adapters, "live_adapters", lambda: [drive, gtasks])
    try:
        cli.main(["sync", "--all"])
    except SystemExit as e:
        assert e.code in (0, None)
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "running drive, gtasks"
    assert [line.split()[:2] for line in out[out.index("sync --all:") :].splitlines()[1:]] == [
        ["drive", "ok"],
        ["gtasks", "ok"],
    ]
    assert {line["source"] for line in lb.lines()} == {"drive", "gtasks"}


def test_both_are_registered_live_sources_sync_all_takes() -> None:
    from logbook.commands import sync

    names = [a.NAME for a in sync._all_order(adapters.live_adapters())]
    assert names.index("gcal") < names.index("drive") < names.index("gtasks") < names.index("immich")
