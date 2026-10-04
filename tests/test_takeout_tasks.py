"""Google Takeout Tasks/ → task/v1 (RFC 0016): one snapshot line per task, subtasks their own lines."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters, cli
from logbook.adapters.takeout import tasks
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "takeout" / "Tasks"
FILE = FIX / "Tasks.json"
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
TZ = "Europe/Oslo"


def _lines(**kw):
    return list(tasks.run(FILE, timezone=TZ, **kw))


def _by_title(lines):
    return {line["payload"]["title"]: line for line in lines}


def test_registry_has_tasks_as_a_file_adapter():
    assert adapters.named("google-takeout-tasks") is tasks
    assert isinstance(tasks, adapters.Adapter)
    assert adapters.find(FILE) is tasks
    assert adapters.find(FIX) is tasks


def test_sniff_recognises_the_tasks_export_and_nothing_else(tmp_path):
    assert tasks.sniff(FILE) and tasks.sniff(FIX)
    assert not tasks.sniff(ROOT / "tests" / "fixtures" / "takeout" / "Keep" / "Boat list.json")
    assert not tasks.sniff(ROOT / "tests" / "fixtures" / "takeout" / "Records.json")
    assert not tasks.sniff(tmp_path) and not tasks.sniff(tmp_path / "missing.json")
    (tmp_path / "x.json").write_text('{"kind": "tasks#taskLists"}', encoding="utf-8")
    assert not tasks.sniff(tmp_path / "x.json")  # no items


def test_every_titled_task_is_a_line_and_the_envelope_is_complete():
    counts: dict[str, int] = {}
    lines = list(tasks.run(FILE, timezone=TZ, counts=counts))
    assert len(lines) == 5
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["kind"] == "task" and line["source"] == "google-takeout" and line["tier"] == 2
        assert line["end"] is None and line["tz"] == TZ
        assert line["payload"]["schema"] == "task/v1"
    assert counts == {"skipped_no_title": 1, "deleted": 1}
    assert [line["at"] for line in lines] == sorted(line["at"] for line in lines)


def test_a_done_task_maps_status_due_day_completed_notes_list_and_extra():
    line = _by_title(_lines())["Buy the long rope"]
    assert line["at"] == "2026-03-04T12:10:00Z"
    p = line["payload"]
    assert p["raw_id"] == "aGVsbG8tcm9wZQ@2026-03-04T12:10:00Z"
    assert p["status"] == "done" and p["due"] == "2026-03-05"  # a day, not a midnight instant (rule 4)
    assert p["completed_at"] == "2026-03-04T12:10:00Z"
    assert p["list"] == "My Tasks" and p["modified_at"] == "2026-03-04T12:10:00Z"
    assert p["notes"] == "30 m, 12 mm. Ask at the chandlery on Storgata 1."
    assert p["extra"] == {
        "hidden": True,
        "links": [
            {"type": "email", "description": "the quote", "url": "https://mail.example.org/u/0/#inbox/abc"}
        ],
    }
    assert "parent" not in p


def test_an_open_task_a_subtask_and_a_deleted_one():
    by = _by_title(_lines())
    fenders = by["Fenders"]["payload"]
    assert fenders["status"] == "open" and fenders["due"] == "2026-03-20"
    assert "completed_at" not in fenders and "notes" not in fenders and "extra" not in fenders
    sub = by["Two blue ones"]["payload"]
    assert sub["parent"] == "ZmVuZGVycw" and "due" not in sub
    old = by["Old idea"]["payload"]
    assert old["status"] == "open" and old["extra"] == {"deleted": True}
    assert by["Antifoul before launch"]["payload"]["list"] == "Boat"


def test_since_cuts_on_at_and_a_folder_reads_every_export_in_it():
    titles = [line["payload"]["title"] for line in _lines(since="2026-03-04T00:00:00Z")]
    assert titles == ["Buy the long rope"]
    assert len(list(tasks.run(FIX, timezone=TZ))) == 5


def test_a_ticked_task_is_a_new_line_and_a_re_import_appends_nothing(tmp_path):
    lb = Logbook.init(tmp_path / "lb", timezone_name=TZ)
    folder = tmp_path / "Tasks"
    shutil.copytree(FIX, folder)
    assert lb.append_many(tasks.run(folder, timezone=TZ)) == 5
    assert lb.append_many(tasks.run(folder, timezone=TZ)) == 0
    data = json.loads((folder / "Tasks.json").read_text(encoding="utf-8"))
    fenders = data["items"][0]["items"][1]
    done = "2026-03-19T10:00:00.000Z"
    fenders.update(status="completed", completed=done, updated=done)
    (folder / "Tasks.json").write_text(json.dumps(data), encoding="utf-8")
    assert lb.append_many(tasks.run(folder, timezone=TZ)) == 1
    new = next(line for line in lb.lines() if line["payload"]["raw_id"] == "ZmVuZGVycw@2026-03-19T10:00:00Z")
    assert new["payload"]["status"] == "done" and new["at"] == "2026-03-19T10:00:00Z"
    seq, _head, errors = lb.verify()
    assert seq == 6 and not errors


def test_cli_add_sniffs_the_tasks_folder(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "lb"))
    cli.main(["init", str(tmp_path / "lb"), "--timezone", TZ])
    capsys.readouterr()
    cli.main(["add", str(FIX)])
    out = capsys.readouterr().out
    assert "added 5 lines from google-takeout-tasks" in out
    assert "skipped 1 without a title" in out and "1 marked for deletion" in out
