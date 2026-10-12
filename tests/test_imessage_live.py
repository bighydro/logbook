"""`logbook sync imessage`: the Mac's own Messages database, live, through the file adapter's mapping.

Every database here is synthetic, built by `test_imessage._store`; no test opens a real chat.db. The home
directory is a temp folder (conftest), so the default `~/Library/Messages/chat.db` never resolves to a
real one either.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from test_imessage import IMAGE_BYTES, T0, _by_rowid, _ns, _store

from logbook import cli
from logbook.contrib import adapters
from logbook.contrib.adapters import imessage, imessage_live
from logbook.core.store import Logbook

DB_ENV = "LOGBOOK_IMESSAGE_DB"
LOOKBACK_ENV = "LOGBOOK_IMESSAGE_LOOKBACK_H"
HASH_ENV = "LOGBOOK_IMESSAGE_HASH_MEDIA"
NEWEST = "2026-03-02T18:01:10Z"  # T0 + 1140, the store's last message (row 20)
LINES = 17  # what the synthetic store yields; see test_imessage


def _stamp(base: str, **delta: float) -> str:
    at = datetime.strptime(base, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) + timedelta(**delta)
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A synthetic Messages store standing in for chat.db, named by the override variable."""
    (tmp_path / "Messages").mkdir()
    p = _store(tmp_path / "Messages", name="chat.db")
    monkeypatch.setenv(DB_ENV, str(p))
    for name in (LOOKBACK_ENV, HASH_ENV):
        monkeypatch.delenv(name, raising=False)
    return p


def _add_message(db: Path, rowid: int, guid: str, text: str, at: str, chat: int = 1) -> None:
    """One more message in an existing store, as Messages.app would write it."""
    con = sqlite3.connect(db)
    try:
        con.execute(
            "INSERT INTO message (ROWID, guid, text, handle_id, date, is_from_me, service)"
            " VALUES (?,?,?,?,?,?,?)",
            (rowid, guid, text, 1, _ns(at), 0, "SMS"),
        )
        con.execute("INSERT INTO chat_message_join VALUES (?,?)", (chat, rowid))
        con.commit()
    finally:
        con.close()


# -- registry and configuration --------------------------------------------------------------


def test_registry_has_imessage_both_as_a_file_and_as_a_live_adapter():
    assert adapters.named("imessage") is imessage
    assert adapters.live("imessage") is imessage_live
    assert imessage_live.NAME == imessage.NAME and imessage_live.KIND == imessage.KIND


def test_configure_defaults_to_the_macs_own_store_under_home(monkeypatch):
    monkeypatch.delenv(DB_ENV, raising=False)
    config = imessage_live.configure({})
    assert config is not None
    assert config.db == Path.home() / "Library" / "Messages" / "chat.db"
    assert config.attachments == Path.home() / "Library" / "Messages" / "Attachments"
    assert config.lookback_h == 24.0 and config.hash_media is True


def test_configure_reads_the_override_and_expands_a_tilde(tmp_path):
    config = imessage_live.configure({DB_ENV: "~/copies/chat.db"})
    assert config is not None and config.db == Path.home() / "copies" / "chat.db"


def test_configure_finds_attachments_beside_the_store_when_they_are_there(db):
    config = imessage_live.configure({DB_ENV: str(db)})
    assert config is not None and config.attachments == db.parent / "Attachments"


def test_configure_falls_back_to_the_macs_attachments_for_a_copy_elsewhere(tmp_path):
    copy = tmp_path / "copies" / "chat.db"
    copy.parent.mkdir()
    copy.write_bytes(b"")
    config = imessage_live.configure({DB_ENV: str(copy)})
    assert config is not None
    assert config.attachments == Path.home() / "Library" / "Messages" / "Attachments"


def test_configure_reads_the_lookback_and_hash_switches():
    config = imessage_live.configure({LOOKBACK_ENV: "2", HASH_ENV: "0"})
    assert config is not None and config.lookback_h == 2.0 and config.hash_media is False


@pytest.mark.parametrize("bad", ["a day", "-1", "nan", "inf"])
def test_configure_refuses_a_lookback_that_is_not_a_non_negative_number(bad):
    with pytest.raises(ValueError, match=LOOKBACK_ENV):
        imessage_live.configure({LOOKBACK_ENV: bad})


def test_resume_is_the_mark_less_the_lookback():
    config = imessage_live.configure({LOOKBACK_ENV: "2"})
    assert config is not None
    assert imessage_live.resume(config, "2026-03-02T18:00:00Z") == "2026-03-02T16:00:00Z"


def test_watermark_is_the_messages_own_time():
    assert imessage_live.watermark({"at": "2026-03-02T18:00:00Z", "payload": {}}) == "2026-03-02T18:00:00Z"


# -- pull: one mapping, one raw_id ------------------------------------------------------------


def test_a_message_imported_from_a_backup_and_the_same_one_pulled_live_are_the_same_line(db):
    config = imessage_live.configure({DB_ENV: str(db)})
    assert config is not None
    imported = list(imessage.run(db))
    live = list(imessage_live.pull(config))
    assert live == imported
    assert [line["payload"]["raw_id"] for line in live] == [line["payload"]["raw_id"] for line in imported]
    assert len(live) == LINES


def test_pull_honours_since_and_reads_both_date_units(db):
    config = imessage_live.configure({DB_ENV: str(db)})
    assert config is not None
    lines = list(imessage_live.pull(config, since="2026-03-02T17:47:10Z"))  # T0 + 300: row 6, in seconds
    assert list(_by_rowid(lines)) == [6, 9, 10, 11, 12, 13, 16, 17, 18, 20]


def test_pull_counts_chat_types_skips_and_media(db):
    config = imessage_live.configure({DB_ENV: str(db)})
    assert config is not None
    counts: dict[str, int] = {}
    lines = list(imessage_live.pull(config, counts=counts))
    direct = sum(1 for line in lines if line["payload"]["chat"]["type"] == "direct")
    assert counts["direct_chat"] == direct == 12 and counts["group_chat"] == LINES - direct == 5
    assert counts["skipped_reaction"] == 2 and counts["skipped_system_event"] == 1
    assert counts["skipped_bad_date"] == 1 and counts["skipped_no_chat"] == 1
    assert counts["skipped_no_body"] == 2
    assert counts["skipped_attachment_no_row"] == 1
    assert counts["skipped_attachment_no_filename"] == 1
    assert counts["skipped_attachment_unsupported_kind"] == 1
    assert counts["skipped_attachment_missing_file"] == 4
    assert counts["media_hashed"] == 2 and counts["no_guid"] == 1


def test_pull_hashes_attachments_from_the_configured_folder(db):
    config = imessage_live.configure({DB_ENV: str(db)})
    assert config is not None
    media = _by_rowid(list(imessage_live.pull(config)))[9]["payload"]["extra"]["media"]
    assert media["bytes"] == len(IMAGE_BYTES) and "sha256" in media


def test_pull_reports_progress_and_the_total(db):
    config = imessage_live.configure({DB_ENV: str(db)})
    assert config is not None
    seen: list[int] = []
    list(imessage_live.pull(config, progress=lambda n, _elapsed: seen.append(n)))
    assert seen and seen[-1] == LINES


def test_pull_never_writes_beside_the_store(db):
    before = sorted(p.name for p in db.parent.iterdir())
    config = imessage_live.configure({DB_ENV: str(db)})
    assert config is not None
    list(imessage_live.pull(config))
    assert sorted(p.name for p in db.parent.iterdir()) == before


def test_pull_reads_a_store_in_wal_mode(db):
    """chat.db is in WAL mode on a Mac; a message still in the -wal file must be seen."""
    con = sqlite3.connect(db)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute(
            "INSERT INTO message (ROWID, guid, text, handle_id, date, is_from_me, service)"
            " VALUES (?,?,?,?,?,?,?)",
            (21, "G-21", "still in the wal", 1, _ns(T0, 1200), 0, "SMS"),
        )
        con.execute("INSERT INTO chat_message_join VALUES (?,?)", (1, 21))
        con.commit()
        assert (db.parent / "chat.db-wal").stat().st_size > 0  # not checkpointed yet
        config = imessage_live.configure({DB_ENV: str(db)})
        assert config is not None
        assert "G-21" in {line["payload"]["raw_id"] for line in imessage_live.pull(config)}
    finally:
        con.close()


@pytest.mark.parametrize("what", ["missing", "not-sqlite"])
def test_pull_on_an_unreadable_store_names_full_disk_access(tmp_path, what):
    p = tmp_path / "chat.db"
    if what == "not-sqlite":
        p.write_bytes(b"not a database at all")
    config = imessage_live.configure({DB_ENV: str(p)})
    assert config is not None
    with pytest.raises(OSError, match="Full Disk Access") as e:
        list(imessage_live.pull(config))
    assert "\n" not in str(e.value) and str(p) in str(e.value)


def test_pull_on_a_database_that_is_not_messages_says_so(tmp_path):
    p = tmp_path / "chat.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE lines (seq INTEGER)")
    con.commit()
    con.close()
    config = imessage_live.configure({DB_ENV: str(p)})
    assert config is not None
    with pytest.raises(OSError, match="not a Messages database"):
        list(imessage_live.pull(config))


# -- sync: the CLI ---------------------------------------------------------------------------


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db: Path) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    return lb


def _sync(*args: str) -> None:
    cli.main(["sync", "imessage", *args])


def _state(lb: Logbook) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((lb.root / "state" / "imessage.json").read_text(encoding="utf-8"))
    return data


def _write_state(lb: Logbook, since: str) -> None:
    (lb.root / "state").mkdir(exist_ok=True)
    (lb.root / "state" / "imessage.json").write_text(json.dumps({"since": since}), encoding="utf-8")


def test_sync_appends_every_message_and_stores_the_newest_message_time(lb, capsys):
    _sync()
    out = capsys.readouterr().out
    assert f"imessage: {LINES} new lines of {LINES} seen from the beginning" in out
    assert "also 12 in direct chats, 5 in group chats, 2 with media hashed" in out
    skipped = "skipped 2 reactions, 1 group system events, 1 with an unusable date, 1 without a chat"
    skipped += ", 4 attachments whose file is not in the backup, 2 without a body"
    assert skipped in out
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == LINES
    assert _state(lb) == {"since": NEWEST}
    assert next(lb.lines())["tz"] == "Europe/Oslo"


def test_sync_dedupes_against_a_prior_file_import(lb, db, capsys):
    """The phone backup was imported with `add`; the Mac holds the same messages under the same guids."""
    assert lb.append_many(imessage.run(db)) == LINES
    _sync()
    out = capsys.readouterr().out
    assert f"the record's newest imessage message, {NEWEST}, less the lookback" in out
    assert f"imessage: 0 new lines of {LINES} seen since" in out
    assert f"({LINES} already in the record)" in out
    raw_ids = [line["payload"]["raw_id"] for line in lb.lines()]
    assert len(raw_ids) == len(set(raw_ids)) == LINES
    assert _state(lb) == {"since": NEWEST}


def test_sync_watermark_round_trip_picks_up_only_what_is_new(lb, db, capsys):
    _sync()
    assert _state(lb) == {"since": NEWEST}
    _add_message(db, 21, "G-21", "back on the pontoon", _stamp(NEWEST, hours=1))
    _sync()
    out = capsys.readouterr().out.splitlines()
    assert any("imessage: 1 new lines of" in line for line in out)
    assert _state(lb) == {"since": _stamp(NEWEST, hours=1)}
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == LINES + 1


def test_sync_lookback_re_reads_the_window_without_duplicates(lb, db, capsys):
    _sync()
    # a message dated inside the lookback window arrives late (the other Mac synced it), and a newer one
    _add_message(db, 21, "G-21", "late from another device", _stamp(NEWEST, hours=-2))
    _add_message(db, 22, "G-22", "newer", _stamp(NEWEST, hours=2))
    _sync()
    out = capsys.readouterr().out.splitlines()
    assert any("imessage: 2 new lines of" in line and "already in the record" in line for line in out)
    raw_ids = [line["payload"]["raw_id"] for line in lb.lines()]
    assert len(raw_ids) == len(set(raw_ids)) == LINES + 2
    assert _state(lb) == {"since": _stamp(NEWEST, hours=2)}
    _sync()
    assert any("imessage: 0 new lines of" in line for line in capsys.readouterr().out.splitlines())


def test_sync_lookback_can_be_overridden(lb, monkeypatch):
    monkeypatch.setenv(LOOKBACK_ENV, "0.1")  # six minutes
    _write_state(lb, NEWEST)
    _sync()
    assert set(_by_rowid(list(lb.lines()))) == {16, 17, 18, 20}  # dated in the six minutes before 18:01:10


def test_sync_since_is_used_as_given_without_lookback(lb):
    _write_state(lb, NEWEST)
    _sync("--since", _stamp(T0, seconds=960))  # row 17 onwards
    assert set(_by_rowid(list(lb.lines()))) == {17, 18, 20}


def test_sync_never_moves_the_watermark_backwards(lb):
    _write_state(lb, "2026-09-01T00:00:00Z")
    _sync("--since", "2026-01-01T00:00:00Z")
    assert _state(lb) == {"since": "2026-09-01T00:00:00Z"}


def test_sync_first_run_ignores_message_lines_from_other_sources(lb, capsys):
    lb.append(
        at="2026-09-01T12:00:00Z",
        source="whatsapp",
        kind="message",
        tier=2,
        payload={
            "schema": "message/v1",
            "raw_id": "x:1",
            "chat": {"id": "c", "type": "direct"},
            "from_me": True,
        },
    )
    _sync()
    out = capsys.readouterr().out
    assert "from the beginning" in out and lb.meta["seq"] == LINES + 1


def test_sync_dry_run_writes_nothing(lb, capsys):
    _sync("--dry-run")
    out = capsys.readouterr().out
    assert f"imessage: {LINES} lines from the beginning (dry run, nothing written)" in out
    assert "in direct chats" in out
    assert lb.meta["seq"] == 0 and not (lb.root / "state").exists()


def test_sync_progress_counts_messages(lb, capsys):
    _sync()
    assert f"  {LINES} messages in 0s" in capsys.readouterr().err.splitlines()


def test_sync_hashing_can_be_switched_off(lb, monkeypatch):
    monkeypatch.setenv(HASH_ENV, "0")
    _sync()
    media = _by_rowid(list(lb.lines()))[9]["payload"]["extra"]["media"]
    assert "sha256" not in media and media["local_path"]


def test_sync_refuses_a_bad_lookback_on_one_line(lb, monkeypatch, capsys):
    monkeypatch.setenv(LOOKBACK_ENV, "a day")
    with pytest.raises(SystemExit) as e:
        _sync()
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and LOOKBACK_ENV in err


def test_sync_unreadable_store_exits_1_with_one_line_naming_full_disk_access(lb, monkeypatch, capsys):
    monkeypatch.setenv(DB_ENV, str(lb.root / "nowhere" / "chat.db"))
    with pytest.raises(SystemExit) as e:
        _sync()
    assert e.value.code == 1
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and err.startswith("sync: imessage:") and "Full Disk Access" in err
    assert lb.meta["seq"] == 0 and not (lb.root / "state").exists()


def test_sync_help_names_imessage(capsys):
    with pytest.raises(SystemExit):
        cli.main(["sync", "--help"])
    assert "imessage" in capsys.readouterr().out
