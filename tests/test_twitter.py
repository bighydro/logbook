"""Twitter/X <account>-dmv2.db → message/v1 (RFC 0008): one line per direct message, every account's store."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters
from logbook.adapters import ios_notes, twitter, whatsapp
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}

DDL = """
CREATE TABLE dm_conversation (conversation_id TEXT PRIMARY KEY, custom_title TEXT, muted INTEGER,
    deleted INTEGER, group_type TEXT);
CREATE TABLE dm_entry (entry_id TEXT PRIMARY KEY, conversation_id TEXT, sequence_number INTEGER,
    timestamp INTEGER, entry_type TEXT, contents BLOB, sender_id INTEGER, message_status TEXT,
    plain_text TEXT, has_attachment INTEGER, event_type TEXT, sender_is_owner INTEGER, attachment_types TEXT);
CREATE TABLE dm_user (id INTEGER PRIMARY KEY, contents BLOB, nickname TEXT, deleted INTEGER,
    suspended INTEGER, screen_name TEXT);
"""

# -- the fixture: synthetic, nobody in it exists ------------------------------------------

ME, OLA, PER = 1000000000000000001, 2000000000000000002, 3000000000000000003
DIRECT = f"{ME}:{OLA}"
GROUP = "1700000000000000000"
T0 = 1_772_000_000_000  # ms: 2026-02-25T06:13:20Z
CONVERSATIONS = [(DIRECT, None, 0, 0, None), (GROUP, "Sailing crew", 0, 0, "group")]
USERS = [(ME, b"\x9f", None, 0, 0, "kari_n"), (OLA, b"\x9f", "Ola", 0, 0, "ola_n")]
E = "e0000001-0000-4000-8000-00000000000"  # entry ids end in their sequence number


def _entry(seq: int, conversation: str, offset: int, sender: int, text: str | None, **kw: object) -> tuple:
    """(entry id, conversation, seq, ts, entry type, sender, status, text, attachment?, is owner, types)."""
    kind = kw.get("kind", "message")
    status = kw.get("status", None if kind != "message" else "Sent")
    attachment = kw.get("attachment")
    return (
        f"{E}{seq}", conversation, seq, offset, kind, sender, status, text,
        1 if attachment else 0, 1 if sender == ME else 0, attachment,
    )  # fmt: skip


ENTRIES = [
    _entry(1, DIRECT, T0, OLA, "Mooring photos sent"),
    _entry(2, DIRECT, T0 + 1000, ME, "Got them"),
    _entry(3, GROUP, T0 + 2000, PER, "Fenders?"),
    _entry(4, DIRECT, T0 + 3000, OLA, None, attachment="link"),
    _entry(5, GROUP, T0 + 4000, ME, "Look", attachment="photo"),
    _entry(6, DIRECT, T0 + 5000, OLA, None, kind="informational"),
    _entry(7, DIRECT, T0 + 6000, OLA, None),
    _entry(8, DIRECT, 0, OLA, "no clock"),
    _entry(9, DIRECT, T0 + 7000, ME, "retry", status="Failed"),
]


def _store(folder: Path, account: int = ME, entries: list = ENTRIES) -> Path:
    """One account's store where the app keeps it: com.atebits.tweetie.databases/v1/<id>/<id>-dmv2.db."""
    p = folder / "com.atebits.tweetie.databases" / "v1" / str(account) / f"{account}-dmv2.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    try:
        con.executescript(DDL)
        con.executemany("INSERT INTO dm_conversation VALUES (?,?,?,?,?)", CONVERSATIONS)
        con.executemany("INSERT INTO dm_user VALUES (?,?,?,?,?,?)", USERS)
        con.executemany("INSERT INTO dm_entry VALUES (?,?,?,?,?,X'9f',?,?,?,?,NULL,?,?)", entries)
        con.commit()
    finally:
        con.close()
    return p


def _by_seq(lines: list[dict]) -> dict[int, dict]:
    return {int(line["payload"]["raw_id"][-1]): line for line in lines}


# -- registry and sniff -------------------------------------------------------------------


def test_registry_lists_twitter_and_finds_the_store_and_its_folder(tmp_path):
    assert "twitter" in [a.NAME for a in adapters.all_adapters()]
    p = _store(tmp_path)
    assert adapters.find(p) is not None and adapters.find(p).NAME == "twitter"
    assert adapters.find(tmp_path) is not None and adapters.find(tmp_path).NAME == "twitter"


def test_sniff_rejects_other_stores_and_junk(tmp_path):
    assert twitter.sniff(tmp_path) is False
    assert twitter.sniff(tmp_path / "nope.db") is False
    p = tmp_path / "other.db"
    con = sqlite3.connect(p)
    try:
        con.executescript("CREATE TABLE dm_entry (entry_id TEXT);")  # a third of it
    finally:
        con.close()
    assert twitter.sniff(p) is False
    (tmp_path / "text.db").write_text("SQLite format 3\0 but not really", encoding="utf-8")
    assert twitter.sniff(tmp_path / "text.db") is False


def test_other_adapters_reject_the_twitter_store(tmp_path):
    p = _store(tmp_path)
    assert ios_notes.sniff(p) is False and whatsapp.sniff(p) is False


def test_sniff_and_run_never_touch_the_source(tmp_path):
    p = _store(tmp_path)
    before = p.read_bytes()
    assert twitter.sniff(p) is True
    list(twitter.run(p))
    assert p.read_bytes() == before
    assert [q.name for q in p.parent.iterdir()] == [p.name]


# -- run: envelope ------------------------------------------------------------------------


def test_run_yields_tier_2_message_lines_at_the_message_timestamp(tmp_path):
    lines = list(twitter.run(_store(tmp_path)))
    assert len(lines) == 6  # 1, 2, 3, 4, 5, 9
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["end"] is None and line["tz"] is None
        assert line["source"] == "twitter" and line["kind"] == "message" and line["tier"] == 2
        assert line["payload"]["schema"] == "message/v1"
    assert _by_seq(lines)[1]["at"] == "2026-02-25T06:13:20Z"


def test_run_streams_in_timestamp_order_and_honours_since(tmp_path):
    p = _store(tmp_path)
    assert list(_by_seq(list(twitter.run(p)))) == [1, 2, 3, 4, 5, 9]
    assert list(_by_seq(list(twitter.run(p, since="2026-02-25T06:13:24Z")))) == [5, 9]


# -- run: the message fields --------------------------------------------------------------


def test_run_a_received_direct_message_names_the_chat_after_the_other_account(tmp_path):
    p = _by_seq(list(twitter.run(_store(tmp_path))))[1]["payload"]
    assert p["raw_id"] == "e0000001-0000-4000-8000-000000000001"
    assert p["chat"] == {"id": DIRECT, "type": "direct", "name": "Ola"}
    assert p["from_me"] is False
    assert p["sender"] == {"kind": "handle", "value": "ola_n", "name": "Ola"}
    assert p["text"] == "Mooring photos sent"
    assert p["extra"] == {"account": str(ME), "twitter_user_id": str(OLA)}


def test_run_the_owners_messages_are_from_me(tmp_path):
    p = _by_seq(list(twitter.run(_store(tmp_path))))[2]["payload"]
    assert p["from_me"] is True and "sender" not in p and p["text"] == "Got them"
    assert p["extra"] == {"account": str(ME)}


def test_run_a_group_message_from_an_unknown_user_is_a_provider_id(tmp_path):
    p = _by_seq(list(twitter.run(_store(tmp_path))))[3]["payload"]
    assert p["chat"] == {"id": GROUP, "type": "group", "name": "Sailing crew"}
    assert p["sender"] == {"kind": "provider_id", "value": str(PER)}
    assert p["text"] == "Fenders?"


def test_run_attachments_give_a_media_kind_with_or_without_text(tmp_path):
    lines = _by_seq(list(twitter.run(_store(tmp_path))))
    assert lines[4]["payload"]["media_kind"] == "link" and "text" not in lines[4]["payload"]
    assert lines[5]["payload"]["media_kind"] == "image" and lines[5]["payload"]["text"] == "Look"
    assert lines[5]["payload"]["extra"]["attachment_types"] == "photo"


def test_run_a_message_that_did_not_send_keeps_its_status(tmp_path):
    p = _by_seq(list(twitter.run(_store(tmp_path))))[9]["payload"]
    assert p["extra"]["status"] == "Failed" and p["from_me"] is True


def test_run_skips_and_counts_informational_empty_and_undated_entries(tmp_path):
    counts: dict[str, int] = {}
    lines = _by_seq(list(twitter.run(_store(tmp_path), counts=counts)))
    assert 6 not in lines and 7 not in lines and 8 not in lines
    assert counts == {"skipped_system_event": 1, "skipped_no_body": 1, "skipped_bad_date": 1}


def test_run_on_a_folder_reads_every_accounts_store(tmp_path):
    _store(tmp_path)
    _store(tmp_path, account=1000000000000000009, entries=[])
    lines = list(twitter.run(tmp_path))
    assert len(lines) == 6 and {line["payload"]["extra"]["account"] for line in lines} == {str(ME)}


def test_run_takes_the_account_from_the_file_name_when_no_message_is_the_owners(tmp_path):
    received = [e for e in ENTRIES if not e[9]]
    p = _store(tmp_path, entries=received)
    lines = list(twitter.run(p))
    assert lines and all(line["payload"]["extra"]["account"] == str(ME) for line in lines)
    assert all(line["payload"]["from_me"] is False for line in lines)


# -- through the logbook -------------------------------------------------------------------


def test_add_dedupes_on_a_second_import_and_validates(tmp_path, monkeypatch):
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    lb = Logbook.init(root, "Europe/Oslo")
    store = _store(tmp_path / "phone")
    assert lb.append_many(twitter.run(store)) == 6
    assert lb.append_many(twitter.run(store)) == 0
    assert lb.verify()[0] == 6
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
