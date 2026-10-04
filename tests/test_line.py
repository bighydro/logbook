"""LINE Line.sqlite → message/v1 (RFC 0008): one line per message, contacts and group names beside it."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook.contrib import adapters
from logbook.contrib.adapters import ios_notes, line, whatsapp
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}

DDL = """
CREATE TABLE ZCHAT (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZTYPE INTEGER,
    ZLASTUPDATED TIMESTAMP, ZLASTMESSAGE VARCHAR, ZMID VARCHAR);
CREATE TABLE ZMESSAGE (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZCONTENTTYPE INTEGER,
    ZREADCOUNT INTEGER, ZSENDSTATUS INTEGER, ZTIMESTAMP INTEGER, ZCHAT INTEGER, ZSENDER INTEGER,
    ZLATITUDE FLOAT, ZLONGITUDE FLOAT, ZID VARCHAR, ZMESSAGETYPE VARCHAR, ZTEXT VARCHAR,
    ZCONTENTMETADATA BLOB, ZTHUMBNAIL BLOB);
CREATE TABLE ZUSER (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZUSERTYPE INTEGER,
    ZADDRESSBOOKNAME VARCHAR, ZCUSTOMNAME VARCHAR, ZMID VARCHAR, ZNAME VARCHAR);
CREATE TABLE Z_1MEMBERS (Z_1CHATS INTEGER, Z_12MEMBERS INTEGER);
"""
CONTACTS_DDL = """
CREATE TABLE ZMANAGEDCNCONTACT (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZMID VARCHAR,
    ZNAME VARCHAR, ZPHONENUMBER VARCHAR);
"""
GROUPS_DDL = """
CREATE TABLE ZUNIFIEDGROUP (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZID VARCHAR,
    ZNAME VARCHAR);
"""

# -- the fixture: synthetic, nobody in it exists ------------------------------------------

OLA_MID = "u0000000000000000000000000000001a"
PER_MID = "u0000000000000000000000000000002b"
GROUP_MID = "c0000000000000000000000000000003c"
OLA, PER = 1, 2
DIRECT, GROUP = 1, 2
T0 = 1_772_000_000_000  # ms: 2026-02-25T06:13:20Z
USERS = [(OLA, 0, "Ola N", "Ola", OLA_MID, "ola_profile"), (PER, 0, None, None, PER_MID, "Per")]
CHATS = [(DIRECT, 0, T0, "last", OLA_MID), (GROUP, 2, T0, "last", GROUP_MID)]
MEMBERS = [(DIRECT, OLA), (GROUP, OLA), (GROUP, PER)]
# (Z_PK, content type, send status, ts, chat, sender, id, text)
MESSAGES = [
    (1, 0, 1, T0, DIRECT, OLA, "500000000001", "Mooring photos sent"),
    (2, 0, 1, T0 + 1000, DIRECT, None, "500000000002", "Got them, thanks"),
    (3, 1, 1, T0 + 2000, DIRECT, OLA, "500000000003", None),
    (4, 7, 1, T0 + 3000, DIRECT, None, "500000000004", None),
    (5, 6, 1, T0 + 4000, DIRECT, OLA, "500000000005", "12:30"),
    (6, 112, 1, T0 + 5000, GROUP, PER, "500000000006", "Who brings the fenders?"),
    (7, 112, 1, T0 + 6000, GROUP, PER, "500000000007", None),
    (8, 0, 0, T0 + 7000, GROUP, None, None, "never sent"),
    (9, 0, 1, 0, DIRECT, OLA, "500000000009", "no clock"),
    (10, 3, 1, T0 + 8000, GROUP, OLA, "500000000010", None),
    (11, 0, 1, T0 + 9000, GROUP, 99, "500000000011", "from a user the store forgot"),
]
CONTACTS = [(1, OLA_MID, "Ola Nordmann", "4790000001")]
GROUPS = [(1, GROUP_MID, "Sailing crew")]


def _store(folder: Path, name: str = "Line.sqlite", companions: bool = True) -> Path:
    p = folder / name
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    try:
        con.executescript(DDL)
        con.executemany("INSERT INTO ZUSER VALUES (?,12,1,?,?,?,?,?)", USERS)
        con.executemany("INSERT INTO ZCHAT VALUES (?,1,1,?,?,?,?)", CHATS)
        con.executemany("INSERT INTO Z_1MEMBERS VALUES (?,?)", MEMBERS)
        con.executemany(
            "INSERT INTO ZMESSAGE VALUES (?,5,1,?,0,?,?,?,?,NULL,NULL,?,NULL,?,NULL,NULL)", MESSAGES
        )
        con.commit()
    finally:
        con.close()
    if companions:
        con = sqlite3.connect(folder / "Contacts.sqlite")
        try:
            con.executescript(CONTACTS_DDL)
            con.executemany("INSERT INTO ZMANAGEDCNCONTACT VALUES (?,1,1,?,?,?)", CONTACTS)
            con.commit()
        finally:
            con.close()
        con = sqlite3.connect(folder / "UnifiedGroup.sqlite")
        try:
            con.executescript(GROUPS_DDL)
            con.executemany("INSERT INTO ZUNIFIEDGROUP VALUES (?,1,1,?,?)", GROUPS)
            con.commit()
        finally:
            con.close()
    return p


def _by_pk(lines: list[dict]) -> dict[int, dict]:
    return {line["payload"]["extra"]["pk"]: line for line in lines}


# -- registry and sniff -------------------------------------------------------------------


def test_registry_lists_line_and_finds_the_store_and_its_folder(tmp_path):
    assert "line" in [a.NAME for a in adapters.all_adapters()]
    p = _store(tmp_path / "Messages")
    assert adapters.find(p) is not None and adapters.find(p).NAME == "line"
    assert adapters.find(tmp_path) is not None and adapters.find(tmp_path).NAME == "line"


def test_sniff_rejects_other_stores_and_junk(tmp_path):
    assert line.sniff(tmp_path) is False  # an empty folder
    assert line.sniff(tmp_path / "nope.sqlite") is False
    p = tmp_path / "other.sqlite"
    con = sqlite3.connect(p)
    try:
        con.executescript("CREATE TABLE ZMESSAGE (Z_PK INTEGER); CREATE TABLE ZCHAT (Z_PK INTEGER);")
    finally:
        con.close()
    assert line.sniff(p) is False
    (tmp_path / "text.sqlite").write_text("SQLite format 3\0 but not really", encoding="utf-8")
    assert line.sniff(tmp_path / "text.sqlite") is False


def test_other_adapters_reject_the_line_store(tmp_path):
    p = _store(tmp_path)
    assert ios_notes.sniff(p) is False and whatsapp.sniff(p) is False


def test_sniff_and_run_never_touch_the_source(tmp_path):
    p = _store(tmp_path, companions=False)
    before = p.read_bytes()
    assert line.sniff(p) is True
    list(line.run(p))
    assert p.read_bytes() == before
    assert [q.name for q in tmp_path.iterdir()] == [p.name]


# -- run: envelope ------------------------------------------------------------------------


def test_run_yields_tier_2_message_lines_at_the_message_timestamp(tmp_path):
    lines = list(line.run(_store(tmp_path)))
    assert len(lines) == 8  # 1, 2, 3, 4, 6, 8, 10, 11
    for item in lines:
        assert set(item) == ENVELOPE
        assert item["end"] is None and item["tz"] is None
        assert item["source"] == "line" and item["kind"] == "message" and item["tier"] == 2
        assert item["payload"]["schema"] == "message/v1"
    assert _by_pk(lines)[1]["at"] == "2026-02-25T06:13:20Z"


def test_run_streams_in_row_order_and_honours_since(tmp_path):
    p = _store(tmp_path)
    assert list(_by_pk(list(line.run(p)))) == [1, 2, 3, 4, 6, 8, 10, 11]
    assert list(_by_pk(list(line.run(p, since="2026-02-25T06:13:25Z")))) == [6, 8, 10, 11]


# -- run: the message fields --------------------------------------------------------------


def test_run_a_received_text_has_the_chat_the_sender_phone_hint_and_the_text(tmp_path):
    p = _by_pk(list(line.run(_store(tmp_path))))[1]["payload"]
    assert p["raw_id"] == "500000000001"
    assert p["chat"] == {"id": OLA_MID, "type": "direct", "name": "Ola"}  # the owner's custom name
    assert p["from_me"] is False
    assert p["sender"] == {"kind": "phone", "value": "+4790000001", "name": "Ola"}
    assert p["text"] == "Mooring photos sent"
    assert p["extra"] == {"pk": 1, "line_mid": OLA_MID, "address_book_name": "Ola N"}


def test_run_a_message_without_a_sender_is_from_me(tmp_path):
    p = _by_pk(list(line.run(_store(tmp_path))))[2]["payload"]
    assert p["from_me"] is True and "sender" not in p and p["text"] == "Got them, thanks"


def test_run_media_and_stickers_carry_a_kind_and_no_text(tmp_path):
    lines = _by_pk(list(line.run(_store(tmp_path))))
    assert lines[3]["payload"]["media_kind"] == "image" and "text" not in lines[3]["payload"]
    assert lines[3]["payload"]["extra"]["content_type"] == 1
    assert lines[4]["payload"]["media_kind"] == "sticker" and lines[4]["payload"]["from_me"] is True
    assert lines[10]["payload"]["media_kind"] == "voice"


def test_run_group_messages_name_the_group_and_fall_back_to_the_profile_name_and_the_handle(tmp_path):
    lines = _by_pk(list(line.run(_store(tmp_path))))
    p = lines[6]["payload"]
    assert p["chat"] == {"id": GROUP_MID, "type": "group", "name": "Sailing crew"}
    assert p["sender"] == {"kind": "handle", "value": PER_MID, "name": "Per"}  # no contact, no custom name
    assert p["text"] == "Who brings the fenders?" and p["extra"]["content_type"] == 112
    assert lines[11]["payload"]["sender"] == {"kind": "handle", "value": "pk99"}


def test_run_an_unsent_message_is_keyed_by_row_id_and_counted(tmp_path):
    counts: dict[str, int] = {}
    p = _by_pk(list(line.run(_store(tmp_path), counts=counts)))[8]["payload"]
    assert p["raw_id"] == "pk8" and p["extra"]["unsent"] is True
    assert counts["no_unique_id"] == 1


def test_run_skips_and_counts_calls_empty_unknown_types_and_bad_dates(tmp_path):
    counts: dict[str, int] = {}
    lines = _by_pk(list(line.run(_store(tmp_path), counts=counts)))
    assert 5 not in lines and 7 not in lines and 9 not in lines
    assert counts == {"skipped_call": 1, "skipped_system_event": 1, "skipped_bad_date": 1, "no_unique_id": 1}


def test_run_without_the_companions_uses_handles_and_no_group_names(tmp_path):
    lines = _by_pk(list(line.run(_store(tmp_path, companions=False))))
    assert lines[1]["payload"]["sender"] == {"kind": "handle", "value": OLA_MID, "name": "Ola"}
    assert lines[6]["payload"]["chat"] == {"id": GROUP_MID, "type": "group"}


def test_run_on_a_folder_finds_the_store_and_the_companions_anywhere_below(tmp_path):
    _store(tmp_path / "PrivateStore" / "P_x" / "Messages", companions=False)
    syncing = tmp_path / "PrivateStore" / "P_x" / "Contacts Syncing"
    syncing.mkdir(parents=True)
    con = sqlite3.connect(syncing / "Contacts.sqlite")
    try:
        con.executescript(CONTACTS_DDL)
        con.executemany("INSERT INTO ZMANAGEDCNCONTACT VALUES (?,1,1,?,?,?)", CONTACTS)
        con.commit()
    finally:
        con.close()
    lines = _by_pk(list(line.run(tmp_path)))
    assert len(lines) == 8
    assert lines[1]["payload"]["sender"]["kind"] == "phone"


# -- through the logbook -------------------------------------------------------------------


def test_add_dedupes_on_a_second_import_and_validates(tmp_path, monkeypatch):
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    lb = Logbook.init(root, "Europe/Oslo")
    store = _store(tmp_path / "phone")
    assert lb.append_many(line.run(store)) == 8
    assert lb.append_many(line.run(store)) == 0
    assert lb.verify()[0] == 8
    validator = Draft202012Validator(SCHEMA)
    for item in lb.lines():
        validator.validate(item)
