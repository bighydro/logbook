"""`logbook sync gtasks`: the owner's Google Tasks as `task/v1` (RFC 0016), from the Tasks API v1, read-only,
with the service account `sync drive` uses (`tests/test_service_account.py`). A task is a snapshot: one line
per task as it stands when it last changed, the same mapping and the same `(source, raw_id)` as the Takeout
Tasks adapter, so a Takeout export of tasks already seen live writes nothing, and the other way round
(ADR 0017). A done snapshot says how long the task was open, from the first open snapshot the record holds.
The notes are never stored, only their digest and word count.

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
from logbook.contrib.adapters.takeout import tasks as takeout_tasks
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


LINES = 6  # t1, t2, t3, t4 (deleted: still a line, RFC 0016 rule 5), t5, t7; t6 has no title
KEYS = [
    "t1@2026-09-14T08:00:00Z",
    "t2@2026-09-14T10:05:00Z",
    "t3@2026-09-14T09:00:00Z",
    "t4@2026-09-14T09:30:00Z",
    "t5@2026-09-10T16:00:00Z",
    "t7@2026-09-14T09:05:00Z",
]


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


def test_registry_has_gtasks_as_a_live_adapter_of_tier_2_task_lines() -> None:
    assert adapters.live("gtasks") is gtasks
    assert gtasks.ENV == drive.ENV == service_account.ENV, "one place to configure both"
    assert (gtasks.KIND, gtasks.TIER, gtasks.SCOPE) == ("task", 2, TASKS_SCOPE)
    assert (
        (gtasks.SOURCE, gtasks.SCHEMA) == (takeout_tasks.SOURCE, "task/v1") == ("google-takeout", "task/v1")
    )


# -- the lines ------------------------------------------------------------------------------------


def test_pull_writes_one_task_v1_snapshot_per_task(fake: Fake) -> None:
    drafts, counts = _pull()
    assert sorted(_by(drafts)) == KEYS
    assert [d["at"] for d in drafts] == sorted(d["at"] for d in drafts)
    assert counts == {"skipped_no_title": 1, "deleted": 1}
    assert {(d["source"], d["kind"], d["tier"], d["tz"], d["end"]) for d in drafts} == {
        ("google-takeout", "task", 2, "Europe/Oslo", None)
    }
    assert {d["payload"]["schema"] for d in drafts} == {"task/v1"}


def test_an_open_snapshot_has_the_title_the_list_the_due_day_and_the_parent(fake: Fake) -> None:
    drafts, _ = _pull()
    line = _by(drafts)["t1@2026-09-14T08:00:00Z"]
    payload = line["payload"]
    assert line["at"] == "2026-09-14T08:00:00Z", "Google keeps no creation time: the snapshot's own"
    assert payload["title"] == "Buy the long rope" and payload["status"] == "open"
    assert payload["list"] == "Inbox" and payload["due"] == "2026-09-20", "a day, never the midnight instant"
    assert payload["modified_at"] == "2026-09-14T08:00:00Z" and "completed_at" not in payload
    assert _by(drafts)["t7@2026-09-14T09:05:00Z"]["payload"]["parent"] == "t3"
    assert "open_for_s" not in payload.get("extra", {}), "an open task has not been open for a while yet"


def test_the_notes_are_a_digest_and_a_word_count_never_the_words(fake: Fake) -> None:
    drafts, _ = _pull()
    payload = _by(drafts)["t1@2026-09-14T08:00:00Z"]["payload"]
    plain = NOTES.replace("\r\n", "\n")
    assert "notes" not in payload, "the profile's `notes` is the words, which this source never keeps"
    assert payload["extra"]["notes"] == {
        "sha256": hashlib.sha256(plain.encode("utf-8")).hexdigest(),
        "words": 8,
    }
    text = json.dumps(drafts)
    assert "chandlery" not in text and "12 mm" not in text
    assert "extra" not in _by(drafts)["t3@2026-09-14T09:00:00Z"]["payload"]


def test_a_task_first_seen_done_is_done_and_open_for_an_unknown_time(fake: Fake) -> None:
    drafts, _ = _pull()
    line = _by(drafts)["t2@2026-09-14T10:05:00Z"]
    payload = line["payload"]
    assert line["at"] == "2026-09-14T10:05:00Z" and payload["title"] == "Call Ola about the mooring"
    assert payload["status"] == "done" and payload["completed_at"] == "2026-09-14T10:00:00Z"
    assert payload["extra"] == {"open_for_s": None}, "the record never saw it open"
    hidden = _by(drafts)["t5@2026-09-10T16:00:00Z"]["payload"]
    assert hidden["status"] == "done" and hidden["extra"]["hidden"] is True, "done and cleared from the list"


def test_a_deleted_task_is_still_a_line(fake: Fake) -> None:
    drafts, counts = _pull()
    payload = _by(drafts)["t4@2026-09-14T09:30:00Z"]["payload"]
    assert payload["title"] == "Old idea" and payload["extra"] == {"deleted": True}
    assert counts["deleted"] == 1


def test_a_done_snapshot_is_open_for_since_the_first_open_snapshot_and_supersedes_the_last(
    fake: Fake,
) -> None:
    earlier = [
        {
            "id": "line-a",
            "at": "2026-09-14T08:00:00Z",
            "payload": {"schema": "task/v1", "raw_id": "t1@2026-09-14T08:00:00Z", "status": "open"},
        },
        {
            "id": "line-b",
            "at": "2026-09-15T07:00:00Z",
            "payload": {"schema": "task/v1", "raw_id": "t1@2026-09-15T07:00:00Z", "status": "open"},
        },
        {
            "id": "line-other",
            "at": "2026-09-13T07:00:00Z",
            "payload": {"schema": "task/v1", "raw_id": "t10@2026-09-13T07:00:00Z", "status": "open"},
        },
    ]
    asked: list[str | None] = []

    def recorded(since: str | None) -> list[dict[str, Any]]:
        asked.append(since)
        return earlier

    fake.tasks["L-inbox"][0].update(
        status="completed", completed="2026-09-16T12:00:00.000Z", updated="2026-09-16T12:00:30.000Z"
    )
    drafts, _ = _pull(recorded=recorded)
    line = _by(drafts)["t1@2026-09-16T12:00:30Z"]
    payload = line["payload"]
    assert payload["status"] == "done" and payload["completed_at"] == "2026-09-16T12:00:00Z"
    assert payload["extra"]["open_for_s"] == 52 * 3600, "from the first open snapshot, not the latest"
    assert payload["supersedes"] == "line-b", "the newest earlier snapshot of the same task"
    assert asked == [None], "every snapshot the record holds, however old"
    assert "supersedes" not in _by(drafts)["t3@2026-09-14T09:00:00Z"]["payload"]


def test_the_file_and_the_api_give_the_same_line_but_the_notes(fake: Fake, tmp_path: Path) -> None:
    """ADR 0017: one mapping, two entrances. The Takeout export of the same tasks and the API's answer
    are the same drafts, but for the notes, which this source keeps as a digest."""
    live, _ = _pull()
    from_file = list(takeout_tasks.run(_export(tmp_path, fake), timezone="Europe/Oslo"))
    assert sorted(_by(from_file)) == KEYS

    def without_notes(draft: dict[str, Any]) -> dict[str, Any]:
        payload = dict(draft["payload"])
        payload.pop("notes", None)
        extra = {
            k: v for k, v in (payload.pop("extra", None) or {}).items() if k not in ("notes", "open_for_s")
        }
        return {**draft, "payload": {**payload, **({"extra": extra} if extra else {})}}

    assert [without_notes(d) for d in live] == [without_notes(d) for d in from_file]


# -- what is asked, and how -----------------------------------------------------------------------


def test_every_list_is_asked_for_every_task_done_hidden_and_deleted_from_since(fake: Fake) -> None:
    _pull(since="2026-09-14T09:00:00Z")
    calls = _tasks_calls(fake)
    assert {c["showCompleted"] for c in calls} == {c["showHidden"] for c in calls} == {"true"}
    assert {c["showDeleted"] for c in calls} == {"true"} and {c["maxResults"] for c in calls} == {"100"}
    assert {c["updatedMin"] for c in calls} == {"2026-09-14T09:00:00Z"}


def test_since_keeps_the_tasks_changed_from_then_on(fake: Fake) -> None:
    drafts, _ = _pull(since="2026-09-14T09:00:00Z")
    assert sorted(_by(drafts)) == [
        "t2@2026-09-14T10:05:00Z",
        "t3@2026-09-14T09:00:00Z",
        "t4@2026-09-14T09:30:00Z",
        "t7@2026-09-14T09:05:00Z",
    ]


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
    line = _by(drafts)["t2@2026-09-14T10:05:00Z"]
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
    return {line["payload"]["raw_id"]: line for line in lb.lines() if line["kind"] == "task"}


def _export(tmp_path: Path, fake: Fake) -> Path:
    """The tasks the fake serves as Takeout writes them, `Takeout/Tasks/Tasks.json`: the API's own task
    objects under their lists."""
    path = tmp_path / "Takeout" / "Tasks" / "Tasks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "kind": "tasks#taskLists",
        "items": [
            {**task_list, "items": [dict(t) for t in fake.tasks[task_list["id"]]]} for task_list in LISTS
        ],
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def _add(path: Path, capsys: Any) -> str:
    cli.main(["add", str(path)])
    out: str = capsys.readouterr().out
    return out


def test_sync_first_run_writes_every_line_and_the_second_none(lb: Logbook, fake: Fake, capsys: Any) -> None:
    assert _sync() == 0
    out = capsys.readouterr().out
    assert f"gtasks: {LINES} new lines of {LINES} seen from the beginning" in out
    assert "Inbox: 2 new of 2 seen" in out and "Boat: 4 new of 4 seen" in out
    assert "skipped 1 without a title" in out and "1 marked for deletion" in out
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == LINES
    assert {(line["source"], line["kind"], line["tier"]) for line in lb.lines()} == {
        ("google-takeout", "task", 2)
    }
    state = json.loads((lb.root / "state" / "gtasks.json").read_text(encoding="utf-8"))
    assert state["since"] == "2026-09-14T10:05:00Z"
    assert _sync() == 0
    assert "gtasks: 0 new lines of" in capsys.readouterr().out
    assert lb.meta["seq"] == LINES


def test_logbook_tasks_lists_a_task_seen_live(lb: Logbook, fake: Fake, capsys: Any) -> None:
    _sync()
    capsys.readouterr()
    cli.main(["tasks", "--json"])
    report = json.loads(capsys.readouterr().out)
    by_title = {t["title"]: t for t in report["tasks"]}
    rope = by_title["Buy the long rope"]
    assert (rope["status"], rope["due"], rope["list"], rope["key"]) == ("open", "2026-09-20", "Inbox", "t1")
    assert rope["source"] == "google-takeout"
    assert by_title["Call Ola about the mooring"]["status"] == "done"
    cli.main(["tasks", "--open"])
    out = capsys.readouterr().out
    assert "Buy the long rope" in out and "Renew the boat insurance" in out
    assert "Call Ola about the mooring" not in out


def test_a_takeout_export_of_the_tasks_seen_live_writes_nothing(
    lb: Logbook, fake: Fake, capsys: Any, tmp_path: Path
) -> None:
    assert _sync() == 0
    capsys.readouterr()
    out = _add(_export(tmp_path, fake), capsys)
    assert "added 0 lines from google-takeout-tasks" in out
    assert lb.meta["seq"] == LINES


def test_a_live_sync_after_a_takeout_export_of_the_same_tasks_writes_nothing(
    lb: Logbook, fake: Fake, capsys: Any, tmp_path: Path
) -> None:
    out = _add(_export(tmp_path, fake), capsys)
    assert f"added {LINES} lines from google-takeout-tasks" in out
    assert _sync() == 0
    out = capsys.readouterr().out
    assert "starting from the record's newest gtasks task, 2026-09-14T10:05:00Z, less the lookback" in out, (
        "the first sync carries on where the export ended (ADR 0017)"
    )
    assert "gtasks: 0 new lines of 5 seen since 2026-09-13T10:05:00Z" in out
    assert lb.meta["seq"] == LINES
    assert _sync("--since", "2026-01-01T00:00:00Z") == 0
    assert f"gtasks: 0 new lines of {LINES} seen" in capsys.readouterr().out, "every task, none new"
    assert "chandlery" in _lines(lb)["t1@2026-09-14T08:00:00Z"]["payload"]["notes"], (
        "the first to arrive stands: the export's line, with the words it carries"
    )


def test_sync_a_task_done_later_is_a_done_snapshot_with_how_long_it_was_open(
    lb: Logbook, fake: Fake, capsys: Any
) -> None:
    _sync()
    fake.tasks["L-inbox"][0].update(
        status="completed", completed="2026-09-16T12:00:00.000Z", updated="2026-09-16T12:00:30.000Z"
    )
    assert _sync() == 0
    assert "gtasks: 1 new lines of" in capsys.readouterr().out
    lines = _lines(lb)
    done = lines["t1@2026-09-16T12:00:30Z"]
    assert done["payload"]["status"] == "done" and done["tier"] == 2
    assert done["payload"]["extra"]["open_for_s"] == 52 * 3600
    assert done["payload"]["supersedes"] == lines["t1@2026-09-14T08:00:00Z"]["id"]
    cli.main(["tasks", "--open"])
    assert "Buy the long rope" not in capsys.readouterr().out, "the newest snapshot is the task's state"


def test_a_done_task_backfilled_open_from_takeout_is_open_for_since_the_export(
    lb: Logbook, fake: Fake, capsys: Any, tmp_path: Path
) -> None:
    _add(_export(tmp_path, fake), capsys)
    fake.tasks["L-inbox"][0].update(
        status="completed", completed="2026-09-16T12:00:00.000Z", updated="2026-09-16T12:00:30.000Z"
    )
    assert _sync() == 0
    done = _lines(lb)["t1@2026-09-16T12:00:30Z"]
    assert done["payload"]["extra"]["open_for_s"] == 52 * 3600


def test_sync_an_edited_task_is_a_new_snapshot_and_an_unchanged_one_appends_nothing(
    lb: Logbook, fake: Fake, capsys: Any
) -> None:
    _sync()
    boat = fake.tasks["L-boat"][0]
    boat.update(title="Renew the boat insurance before October", updated="2026-09-15T09:00:00.000Z")
    assert _sync() == 0
    assert "gtasks: 1 new lines of" in capsys.readouterr().out
    assert _sync() == 0
    assert "gtasks: 0 new lines of" in capsys.readouterr().out
    snapshots = sorted(key for key in _lines(lb) if key.startswith("t3@"))
    assert snapshots == ["t3@2026-09-14T09:00:00Z", "t3@2026-09-15T09:00:00Z"]
    assert _lines(lb)["t3@2026-09-14T09:00:00Z"]["payload"]["title"] == "Renew the boat insurance", (
        "the earlier snapshot is never rewritten"
    )
    assert lb.meta["seq"] == LINES + 1


def test_sync_a_task_deleted_later_is_a_deleted_snapshot(lb: Logbook, fake: Fake, capsys: Any) -> None:
    _sync()
    fake.tasks["L-boat"][3].update(deleted=True, updated="2026-09-15T08:00:00.000Z")
    assert _sync() == 0
    out = capsys.readouterr().out
    assert "gtasks: 1 new lines of" in out and "1 marked for deletion" in out
    lines = _lines(lb)
    assert lines["t7@2026-09-15T08:00:00Z"]["payload"]["extra"] == {"deleted": True}
    assert "t7@2026-09-14T09:05:00Z" in lines, "what was written stays"


def test_sync_since_is_used_as_given(lb: Logbook, fake: Fake, capsys: Any) -> None:
    assert _sync("--since", "2026-09-14T09:00:00Z") == 0
    assert "gtasks: 4 new lines of 4 seen since 2026-09-14T09:00:00Z" in capsys.readouterr().out
    assert sorted(_lines(lb)) == [
        "t2@2026-09-14T10:05:00Z",
        "t3@2026-09-14T09:00:00Z",
        "t4@2026-09-14T09:30:00Z",
        "t7@2026-09-14T09:05:00Z",
    ]


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
    assert {line["source"] for line in lb.lines()} == {"drive", "google-takeout"}


def test_both_are_registered_live_sources_sync_all_takes() -> None:
    from logbook.commands import sync

    names = [a.NAME for a in sync._all_order(adapters.live_adapters())]
    assert names.index("gcal") < names.index("drive") < names.index("gtasks") < names.index("immich")
