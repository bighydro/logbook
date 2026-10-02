"""The inbox manifest's cursor: an interrupted import of a big export resumes at the last message
the record holds, a finished one reads nothing, a changed file or `--restart` reads from the start."""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import cli, inbox, store
from logbook.adapters import mail
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
MBOX = ROOT / "tests" / "fixtures" / "mail" / "takeout.mbox"
TZ = "Europe/Oslo"
SEVENTH = b"""
From 1795123456789012351@xxx Thu Mar 05 09:00:00 +0000 2026
X-GM-THRID: 1795123456789012351
X-Gmail-Labels: Inbox
Message-ID: <f6a7b8@mail.example.org>
Date: Thu, 5 Mar 2026 10:00:00 +0100
From: Ola Nordmann <ola@example.org>
To: kari.nordmann@example.org
Subject: Seventh
Content-Type: text/plain; charset="utf-8"

A new message at the end of the export.

"""


def _manifest(root: Path) -> list[dict[str, Any]]:
    return list(json.loads((root / "inbox" / "manifest.json").read_text(encoding="utf-8"))["cursors"])


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    return lb


@pytest.fixture
def mbox(tmp_path: Path) -> Path:
    path = tmp_path / "All mail Including Spam and Trash.mbox"
    shutil.copy(MBOX, path)
    return path


# -- the cursor ------------------------------------------------------------------------------------


def test_a_new_file_starts_at_zero_and_commit_writes_the_offset_of_the_last_committed_draft(lb, mbox):
    cursor = inbox.Cursor(lb.root, "mail", {"account": "kari.nordmann@example.org"})
    assert cursor.start(mbox) == 0
    cursor.reached(mbox, 1, 700)
    cursor.reached(mbox, 2, 1200)
    cursor.commit(1)  # draft 2 is not in the record yet: draft 1's offset is the one written
    [entry] = _manifest(lb.root)
    assert entry["offset"] == 700 and entry["drafts"] == 1
    cursor.reached(mbox, 3, 1900)
    cursor.commit(3)
    [entry] = _manifest(lb.root)
    assert entry["adapter"] == "mail" and entry["path"] == str(mbox.resolve())
    assert entry["options"] == {"account": "kari.nordmann@example.org"}
    assert entry["offset"] == 1900 and entry["drafts"] == 3 and entry["done"] is False
    assert len(entry["head"]) == 64 and entry["size"] == mbox.stat().st_size
    again = inbox.Cursor(lb.root, "mail", {"account": "kari.nordmann@example.org"})
    assert again.start(mbox) == 1900 and again.resumed == [(mbox.resolve(), 1900)]


def test_other_options_a_changed_file_or_restart_start_from_zero(lb, mbox):
    cursor = inbox.Cursor(lb.root, "mail", {"since": "2026-03-03T00:00:00Z"})
    cursor.start(mbox)
    cursor.reached(mbox, 4, 2000)
    cursor.commit(4)
    assert inbox.Cursor(lb.root, "mail", {"since": "2026-03-03T00:00:00Z"}).start(mbox) == 2000
    assert inbox.Cursor(lb.root, "mail", {}).start(mbox) == 0  # another import
    assert inbox.Cursor(lb.root, "mail", {"since": "2026-03-03T00:00:00Z"}, restart=True).start(mbox) == 0
    assert inbox.Cursor(lb.root, "ics", {"since": "2026-03-03T00:00:00Z"}).start(mbox) == 0
    with mbox.open("ab") as fh:
        fh.write(SEVENTH)  # grown: the same head, another size
    assert inbox.Cursor(lb.root, "mail", {"since": "2026-03-03T00:00:00Z"}).start(mbox) == 0
    data = mbox.read_bytes()
    mbox.write_bytes(
        b"From other@xxx Mon Mar 02 10:15:00 +0000 2026\n" + data[len(data.split(b"\n", 1)[0]) + 1 :]
    )
    assert inbox.Cursor(lb.root, "mail", {"since": "2026-03-03T00:00:00Z"}).start(mbox) == 0  # another head


def test_commit_writes_every_file_whose_last_draft_is_in_the_record(lb, mbox, tmp_path):
    other = tmp_path / "b.mbox"
    shutil.copy(MBOX, other)
    cursor = inbox.Cursor(lb.root, "mail", {})
    cursor.start(mbox)
    cursor.reached(mbox, 6, mbox.stat().st_size)  # read to the end
    cursor.start(other)
    cursor.reached(other, 7, 500)
    cursor.commit(6)
    [entry] = _manifest(lb.root)
    assert entry["path"] == str(mbox.resolve()) and entry["done"] is True
    cursor.commit(7)
    entries = {e["path"]: e for e in _manifest(lb.root)}
    assert entries[str(other.resolve())]["offset"] == 500 and entries[str(other.resolve())]["done"] is False
    assert len(entries) == 2


def test_a_manifest_that_does_not_parse_is_an_empty_one(lb, mbox):
    (lb.root / "inbox").mkdir(exist_ok=True)
    (lb.root / "inbox" / "manifest.json").write_text("{not json", encoding="utf-8")
    cursor = inbox.Cursor(lb.root, "mail", {})
    assert cursor.start(mbox) == 0
    cursor.reached(mbox, 1, 10)
    cursor.commit(1)
    assert _manifest(lb.root)[0]["offset"] == 10


# -- with the adapter and the record ------------------------------------------------------------


def test_append_many_reports_every_checkpoint_with_the_drafts_taken(lb, monkeypatch):
    monkeypatch.setattr(store, "META_EVERY", 4)
    taken: list[int] = []
    drafts = [
        {
            "at": "2026-01-01T00:00:00Z",
            "source": "sim",
            "kind": "note",
            "tier": 1,
            "payload": {"schema": "n/v1"},
        }
        for _ in range(10)
    ]
    assert lb.append_many(drafts, committed=taken.append) == 10
    assert taken == [4, 8, 10]
    taken.clear()
    assert lb.append_many([], committed=taken.append) == 0
    assert taken == [0]


def test_an_interrupted_import_resumes_at_the_last_message_the_record_holds(lb, mbox, monkeypatch):
    monkeypatch.setattr(store, "META_EVERY", 2)

    def three_then_crash(drafts: Iterator[dict[str, Any]]) -> Iterator[dict[str, Any]]:
        for i, draft in enumerate(drafts):
            if i == 3:
                raise RuntimeError("disk full")
            yield draft

    cursor = inbox.Cursor(lb.root, "mail", {})
    with pytest.raises(RuntimeError):
        lb.append_many(three_then_crash(mail.run(mbox, timezone=TZ, cursor=cursor)), committed=cursor.commit)
    assert len(list(lb.lines())) == 3  # the batch of two, then the one before the crash
    [entry] = _manifest(lb.root)
    with mbox.open("rb") as fh:
        offsets = [end for _sep, _raw, end in mail.messages(fh)]
    assert entry["offset"] == offsets[2] and entry["drafts"] == 3

    cursor = inbox.Cursor(lb.root, "mail", {})
    assert lb.append_many(mail.run(mbox, timezone=TZ, cursor=cursor), committed=cursor.commit) == 3
    assert cursor.resumed == [(mbox.resolve(), offsets[2])]
    assert len(list(lb.lines())) == 6 and lb.verify()[2] == []
    [entry] = _manifest(lb.root)
    assert entry["offset"] == mbox.stat().st_size and entry["done"] is True and entry["drafts"] == 3


# -- the CLI ---------------------------------------------------------------------------------------


def test_add_mail_resumes_where_the_last_run_got_to_and_restart_reads_it_all(lb, mbox, capsys):
    cli.main(["add", "mail", str(mbox)])
    out, err = capsys.readouterr()
    assert "added 6 lines from mail" in out and "resuming" not in err
    [entry] = _manifest(lb.root)
    assert entry["offset"] == mbox.stat().st_size and entry["done"] is True and entry["drafts"] == 6

    cli.main(["add", "mail", str(mbox)])
    out, err = capsys.readouterr()
    assert "added 0 lines from mail" in out and "read to the end already" in err and "--restart" in err

    with mbox.open("ab") as fh:
        fh.write(SEVENTH)  # the export grew: another size, so it is read from the start, deduped
    cli.main(["add", "mail", str(mbox)])
    out, err = capsys.readouterr()
    assert "added 1 lines from mail" in out and "resuming" not in err
    [entry] = _manifest(lb.root)
    assert entry["offset"] == mbox.stat().st_size and entry["drafts"] == 7
    assert len(list(lb.lines())) == 7

    entry["offset"] = 0  # as if the run had stopped at once
    entry["drafts"] = 0
    (lb.root / "inbox" / "manifest.json").write_text(json.dumps({"cursors": [entry]}), encoding="utf-8")
    cli.main(["add", "mail", str(mbox)])
    out, err = capsys.readouterr()
    assert "added 0 lines from mail" in out and "resuming" not in err  # offset 0 is a start, not a resume
    [entry] = _manifest(lb.root)
    assert entry["drafts"] == 7

    cli.main(["add", "mail", str(mbox), "--restart"])
    out, err = capsys.readouterr()
    assert "added 0 lines from mail" in out and "read to the end" not in err
    assert len(list(lb.lines())) == 7


def test_add_mail_with_other_options_is_another_import_and_a_dry_run_writes_no_manifest(lb, mbox, capsys):
    cli.main(["add", "mail", str(mbox), "--dry-run"])
    assert "6 lines would be added" in capsys.readouterr().out
    assert not (lb.root / "inbox" / "manifest.json").exists()
    cli.main(["add", "mail", str(mbox), "--only-labels", "Sent"])
    assert "added 1 lines" in capsys.readouterr().out
    cli.main(["add", "mail", str(mbox), "--skip-labels", "Spam"])
    out, err = capsys.readouterr()
    assert "added 4 lines" in out and "read to the end" not in err
    entries = _manifest(lb.root)
    assert [e["options"] for e in entries] == [{"only_labels": ["Sent"]}, {"skip_labels": ["Spam"]}]
    assert all(e["done"] for e in entries)


def test_add_restart_is_refused_for_an_adapter_without_a_cursor(lb, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["add", str(ROOT / "tests" / "fixtures" / "dawarich" / "export.json"), "--restart"])
    assert e.value.code == 2 and "--restart" in capsys.readouterr().err


def test_add_mail_prints_progress_with_the_rate(lb, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(mail, "PROGRESS_EVERY", 4)
    cli.main(["add", "mail", str(MBOX)])
    err = capsys.readouterr().err
    assert "  4 messages · 0 MB read · " in err and err.rstrip().endswith("MB/s")
