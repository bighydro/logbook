"""iOS/macOS Messages sms.db → message/v1 (RFC 0008): one line per message, media by digest only."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters
from logbook.adapters import dawarich, imessage, ios_contacts, phone, whatsapp
from logbook.adapters.takeout import location
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
DAWARICH = ROOT / "tests" / "fixtures" / "dawarich" / "export.json"
TAKEOUT = ROOT / "tests" / "fixtures" / "takeout" / "Records.json"
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
APPLE_EPOCH = 978_307_200  # 2001-01-01T00:00:00Z, the zero of message.date

DDL = """
CREATE TABLE message (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT, guid TEXT UNIQUE, text TEXT, attributedBody BLOB,
    handle_id INTEGER DEFAULT 0, date INTEGER, is_from_me INTEGER DEFAULT 0, service TEXT,
    associated_message_type INTEGER DEFAULT 0, reply_to_guid TEXT, item_type INTEGER DEFAULT 0,
    cache_has_attachments INTEGER DEFAULT 0
);
CREATE TABLE handle (ROWID INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL, service TEXT NOT NULL);
CREATE TABLE chat (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT, guid TEXT UNIQUE NOT NULL, chat_identifier TEXT,
    display_name TEXT, style INTEGER
);
CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER, PRIMARY KEY (chat_id, message_id));
CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER, PRIMARY KEY (chat_id, handle_id));
CREATE TABLE attachment (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT, guid TEXT UNIQUE NOT NULL, filename TEXT, mime_type TEXT,
    total_bytes INTEGER DEFAULT 0
);
CREATE TABLE message_attachment_join (
    message_id INTEGER, attachment_id INTEGER, PRIMARY KEY (message_id, attachment_id)
);
"""


def _seconds(stamp: str) -> int:
    return int(datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()) - APPLE_EPOCH


def _ns(stamp: str, plus: int = 0) -> int:
    return (_seconds(stamp) + plus) * 1_000_000_000


def _typedstream(text: str) -> bytes:
    """An NSKeyedArchiver typedstream the way iOS 16+ stores attributedBody: the body is the one
    NSString inside, its length one byte or 0x81 + little-endian uint16."""
    data = text.encode("utf-8")
    length = bytes([len(data)]) if len(data) < 128 else b"\x81" + len(data).to_bytes(2, "little")
    return (
        b"\x04\x0bstreamtyped\x81\xe8\x03\x84\x01@\x84\x84\x84\x12NSAttributedString\x00\x84\x84\x08NSObject"
        b"\x00\x85\x92\x84\x84\x84\x08NSString\x01\x94\x84\x01+" + length + data + b"\x86\x84\x02iI\x01\x92"
        b"\x84\x84\x84\x0cNSDictionary\x00\x94\x84\x01i\x01\x92\x84\x96\x96\x1d__kIMMessagePartAttributeName"
        b"\x86\x92\x84\x84\x84\x08NSNumber\x00\x84\x84\x07NSValue\x00\x94\x84\x01*\x84\x99\x99\x00\x86\x86\x86"
    )


OLA = "+4790000001"
INES_PHONE = "+4790000002"
INES_EMAIL = "Ines.Nordmann@example.org"  # the store keeps the case the sender used
CREW = "chat123456789012345678"
TELENOR = "Telenor"  # an alphanumeric SMS sender id

# (ROWID, id, service) — synthetic; nobody here exists
HANDLES = [(1, OLA, "SMS"), (2, INES_EMAIL, "iMessage"), (3, INES_PHONE, "iMessage"), (4, TELENOR, "SMS")]
# (ROWID, guid, chat_identifier, display_name, style)
CHATS = [
    (1, f"SMS;-;{OLA}", OLA, None, 45),
    (2, f"iMessage;-;{INES_EMAIL.lower()}", INES_EMAIL.lower(), None, 45),
    (3, f"iMessage;+;{CREW}", CREW, "Mooring crew", 43),
    (4, f"SMS;-;{TELENOR}", TELENOR, "", 45),
]
CHAT_HANDLES = [(1, 1), (2, 2), (3, 1), (3, 3), (4, 4)]

T0 = "2026-03-02T17:42:10Z"
LONG_TEXT = "the tide table for the week, in full: " + " ".join(f"{h:02d}:00 high" for h in range(24))
assert len(LONG_TEXT.encode("utf-8")) >= 128
# (ROWID, guid, text, attributedBody, handle_id, date, is_from_me, service, associated_message_type,
#  reply_to_guid, item_type, cache_has_attachments)
MESSAGES = [
    (1, "G-1", "mooring photos sent, check your mail", None, 1, _ns(T0), 0, "SMS", 0, None, 0, 0),
    (2, "G-2", "got them, thanks", None, 1, _ns(T0, 60), 1, "SMS", 0, None, 0, 0),
    (
        3,
        "G-3",
        None,
        _typedstream("stern line is chafing again"),
        2,
        _ns(T0, 120),
        0,
        "iMessage",
        0,
        None,
        0,
        0,
    ),
    (4, "G-4", "Loved “got them, thanks”", None, 2, _ns(T0, 180), 0, "iMessage", 2000, None, 0, 0),  # tapback
    (5, "G-5", None, None, 3, _ns(T0, 240), 0, "iMessage", 0, None, 2, 0),  # group rename
    (
        6,
        "G-6",
        "who has the winch handle?",
        None,
        3,
        _seconds(T0) + 300,
        0,
        "iMessage",
        0,
        None,
        0,
        0,
    ),  # seconds
    (7, "G-7", "from before the epoch", None, 1, 12_345, 0, "SMS", 0, None, 0, 0),  # garbage date
    (8, "G-8", "orphan", None, 1, _ns(T0, 420), 0, "SMS", 0, None, 0, 0),  # no chat_message_join row
    (9, "G-9", "\ufffc", None, 1, _ns(T0, 480), 0, "SMS", 0, None, 0, 1),  # image, file exists
    (10, "G-10", None, None, 2, _ns(T0, 540), 0, "iMessage", 0, None, 0, 1),  # video, file missing
    (11, "G-11", "read this", None, 3, _ns(T0, 600), 0, "iMessage", 0, None, 0, 1),  # path escapes
    (12, "G-12", "me", None, 3, _ns(T0, 660), 0, "iMessage", 0, "G-6", 0, 0),  # a reply
    (13, "G-13", "on the boat", None, 0, _ns(T0, 720), 1, "iMessage", 0, None, 0, 0),  # from me, group
    (14, "G-14", "Removed a heart from “me”", None, 3, _ns(T0, 780), 0, "iMessage", 3001, None, 0, 0),
    (15, "G-15", None, None, 1, _ns(T0, 840), 0, "SMS", 0, None, 0, 0),  # nothing at all
    (16, "G-16", None, _typedstream(LONG_TEXT), 3, _ns(T0, 900), 0, "iMessage", 0, None, 0, 0),  # 0x81 length
    (17, "G-17", "Your bill is ready", None, 4, _ns(T0, 960), 0, "SMS", 0, None, 0, 0),  # alphanumeric sender
    (18, "G-18", None, None, 1, _ns(T0, 1020), 0, "SMS", 0, None, 0, 1),  # two attachments
    (19, "G-19", "  ", b"\x04\x0bstreamtyped nothing to see", 1, _ns(T0, 1080), 0, "SMS", 0, None, 0, 0),
    (20, None, "no guid on this one", None, 1, _ns(T0, 1140), 0, "SMS", 0, None, 0, 0),
]
CHAT_MESSAGES = [(1, 1), (1, 2), (2, 3), (2, 4), (3, 5), (3, 6), (1, 7), (1, 9), (2, 10), (3, 11), (3, 12)]
CHAT_MESSAGES += [(3, 13), (3, 14), (1, 15), (3, 16), (4, 17), (1, 18), (1, 19), (1, 20)]

IMAGE_BYTES = b"\xff\xd8not really a jpeg\xff\xd9"
VOICE_BYTES = b"caff\x00\x01not really a voice note"
IMAGE_PATH = "~/Library/SMS/Attachments/ab/12/AT-100/stern.jpg"
VIDEO_PATH = "~/Library/SMS/Attachments/cd/34/AT-101/clip.mov"
ESCAPE_PATH = "~/Library/SMS/Attachments/../../secret.txt"
VOICE_PATH = (
    "/var/mobile/Library/SMS/Attachments/ef/56/AT-103/note.caf"  # absolute, as macOS Messages stores it
)
CARD_PATH = "~/Library/SMS/Attachments/ef/56/AT-104/ola.vcf"
# (ROWID, guid, filename, mime_type, total_bytes)
ATTACHMENTS = [
    (100, "AT-100", IMAGE_PATH, "image/jpeg", len(IMAGE_BYTES)),
    (101, "AT-101", VIDEO_PATH, "video/quicktime", 4_000_000),
    (102, "AT-102", ESCAPE_PATH, "application/pdf", 10),
    (103, "AT-103", VOICE_PATH, "audio/x-caf", len(VOICE_BYTES)),
    (104, "AT-104", CARD_PATH, "text/vcard", 300),
]
MESSAGE_ATTACHMENTS = [(9, 100), (10, 101), (11, 102), (18, 103), (18, 104)]


def _store(tmp_path: Path, name: str = "sms.db", with_media_files: bool = True) -> Path:
    p = tmp_path / name
    con = sqlite3.connect(p)
    try:
        con.executescript(DDL)
        con.executemany("INSERT INTO handle VALUES (?,?,?)", HANDLES)
        con.executemany("INSERT INTO chat VALUES (?,?,?,?,?)", CHATS)
        con.executemany("INSERT INTO chat_handle_join VALUES (?,?)", CHAT_HANDLES)
        con.executemany("INSERT INTO message VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", MESSAGES)
        con.executemany("INSERT INTO chat_message_join VALUES (?,?)", CHAT_MESSAGES)
        con.executemany("INSERT INTO attachment VALUES (?,?,?,?,?)", ATTACHMENTS)
        con.executemany("INSERT INTO message_attachment_join VALUES (?,?)", MESSAGE_ATTACHMENTS)
        con.commit()
    finally:
        con.close()
    if with_media_files:
        image = tmp_path / "Attachments" / "ab" / "12" / "AT-100" / "stern.jpg"
        image.parent.mkdir(parents=True)
        image.write_bytes(IMAGE_BYTES)
        voice = tmp_path / "Attachments" / "ef" / "56" / "AT-103" / "note.caf"
        voice.parent.mkdir(parents=True)
        voice.write_bytes(VOICE_BYTES)
    return p


def _by_rowid(lines: list[dict]) -> dict[int, dict]:
    """Lines keyed by the message.ROWID they came from."""
    guid = {m[1] or f"row{m[0]}": m[0] for m in MESSAGES}
    return {guid[line["payload"]["raw_id"]]: line for line in lines}


@pytest.fixture
def hash_media(monkeypatch):
    monkeypatch.delenv("LOGBOOK_IMESSAGE_HASH_MEDIA", raising=False)


# -- registry ---------------------------------------------------------------


def test_registry_lists_imessage():
    assert "imessage" in [a.NAME for a in adapters.all_adapters()]


def test_registry_find_returns_imessage_for_a_message_store(tmp_path):
    found = adapters.find(_store(tmp_path))
    assert found is not None and found.NAME == "imessage"


def test_registry_find_by_content_not_by_name(tmp_path):
    """A Finder/iTunes backup stores the file under its hashed name, without an extension."""
    found = adapters.find(_store(tmp_path, "3d0d7e5fb2ce288813306e4d4636395e047a3d28"))
    assert found is not None and found.NAME == "imessage"


# -- sniff ------------------------------------------------------------------


def test_sniff_accepts_message_store(tmp_path):
    assert imessage.sniff(_store(tmp_path)) is True


def test_sniff_rejects_other_exports(tmp_path):
    assert imessage.sniff(DAWARICH) is False
    assert imessage.sniff(TAKEOUT) is False


def test_other_adapters_reject_the_message_store(tmp_path):
    p = _store(tmp_path)
    assert dawarich.sniff(p) is False and location.sniff(p) is False
    assert ios_contacts.sniff(p) is False and whatsapp.sniff(p) is False


@pytest.mark.parametrize(
    "ddl",
    [
        "CREATE TABLE lines (seq INTEGER, hash TEXT);",
        "CREATE TABLE message (ROWID INTEGER PRIMARY KEY, text TEXT);",  # a quarter of it
        "CREATE TABLE message (ROWID INTEGER PRIMARY KEY); CREATE TABLE handle (ROWID INTEGER PRIMARY KEY);"
        " CREATE TABLE chat (ROWID INTEGER PRIMARY KEY);",  # no chat_message_join
        "CREATE TABLE ZWACHATSESSION (Z_PK INTEGER PRIMARY KEY);"
        " CREATE TABLE ZWAMESSAGE (Z_PK INTEGER PRIMARY KEY);",
        "CREATE TABLE ABPerson (ROWID INTEGER PRIMARY KEY); CREATE TABLE ABMultiValue (UID INTEGER);",
    ],
)
def test_sniff_rejects_unrelated_sqlite_files(tmp_path, ddl):
    p = tmp_path / "other.sqlite"
    con = sqlite3.connect(p)
    try:
        con.executescript(ddl)
    finally:
        con.close()
    assert imessage.sniff(p) is False


@pytest.mark.parametrize("content", ["", "just words\n", "SQLite format 3\0 but not really a database"])
def test_sniff_rejects_non_sqlite_files(tmp_path, content):
    p = tmp_path / "sms.db"
    p.write_text(content, encoding="utf-8")
    assert imessage.sniff(p) is False


def test_sniff_rejects_directory_and_missing_file(tmp_path):
    assert imessage.sniff(tmp_path) is False
    assert imessage.sniff(tmp_path / "nope.db") is False


def test_sniff_and_run_never_touch_the_source(tmp_path, hash_media):
    p = _store(tmp_path)
    before = p.read_bytes()
    assert imessage.sniff(p) is True
    list(imessage.run(p))
    assert p.read_bytes() == before
    assert sorted(q.name for q in tmp_path.iterdir()) == ["Attachments", "sms.db"]  # no journal, no wal


# -- run: envelope ------------------------------------------------------------


def test_run_yields_message_lines_with_the_source_timestamp(tmp_path, hash_media):
    lines = list(imessage.run(_store(tmp_path)))
    assert len(lines) == 13
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["end"] is None and line["tz"] is None
        assert line["source"] == "imessage" and line["kind"] == "message" and line["tier"] == 2
        assert line["payload"]["schema"] == "message/v1"
    assert _by_rowid(lines)[1]["at"] == "2026-03-02T17:42:10Z"


def test_run_streams_in_row_order(tmp_path, hash_media):
    lines = list(imessage.run(_store(tmp_path)))
    assert list(_by_rowid(lines)) == [1, 2, 3, 6, 9, 10, 11, 12, 13, 16, 17, 18, 20]


def test_run_honours_since(tmp_path, hash_media):
    lines = list(imessage.run(_store(tmp_path), since="2026-03-02T17:53:10Z"))  # T0 + 660
    assert list(_by_rowid(lines)) == [12, 13, 16, 17, 18, 20]


# -- run: dates ----------------------------------------------------------------


def test_run_reads_nanoseconds_since_2001(tmp_path, hash_media):
    assert _by_rowid(list(imessage.run(_store(tmp_path))))[2]["at"] == "2026-03-02T17:43:10Z"


def test_run_reads_seconds_since_2001_on_an_old_store(tmp_path, hash_media):
    assert _by_rowid(list(imessage.run(_store(tmp_path))))[6]["at"] == "2026-03-02T17:47:10Z"


# -- run: chats, senders, text --------------------------------------------------------


def test_run_direct_sms_chat_and_phone_sender(tmp_path, hash_media):
    p = _by_rowid(list(imessage.run(_store(tmp_path))))[1]["payload"]
    assert p["raw_id"] == "G-1"
    assert p["chat"] == {"id": OLA, "type": "direct"}
    assert p["from_me"] is False
    assert p["sender"] == {"kind": "phone", "value": "+4790000001"}
    assert p["text"] == "mooring photos sent, check your mail"
    assert "media_kind" not in p and "reply_to" not in p
    assert p["extra"] == {"service": "SMS"}


def test_run_from_me_has_no_sender(tmp_path, hash_media):
    p = _by_rowid(list(imessage.run(_store(tmp_path))))[2]["payload"]
    assert p["from_me"] is True and "sender" not in p
    assert p["text"] == "got them, thanks"


def test_run_email_handle_is_an_email_ref_lower_cased(tmp_path, hash_media):
    p = _by_rowid(list(imessage.run(_store(tmp_path))))[3]["payload"]
    assert p["chat"] == {"id": INES_EMAIL.lower(), "type": "direct"}
    assert p["sender"] == {"kind": "email", "value": "ines.nordmann@example.org"}
    assert p["extra"] == {"service": "iMessage"}


def test_run_text_from_attributed_body_when_text_is_null(tmp_path, hash_media):
    p = _by_rowid(list(imessage.run(_store(tmp_path))))[3]["payload"]
    assert p["text"] == "stern line is chafing again"


def test_run_text_from_attributed_body_with_a_two_byte_length(tmp_path, hash_media):
    p = _by_rowid(list(imessage.run(_store(tmp_path))))[16]["payload"]
    assert p["text"] == LONG_TEXT


def test_run_prefers_the_text_column_over_attributed_body(tmp_path, hash_media):
    p = _store(tmp_path, with_media_files=False)
    con = sqlite3.connect(p)
    try:
        con.execute("UPDATE message SET text = 'the column wins' WHERE ROWID = 3")
        con.commit()
    finally:
        con.close()
    assert _by_rowid(list(imessage.run(p)))[3]["payload"]["text"] == "the column wins"


def test_run_group_chat_named_and_sender_from_the_handle(tmp_path, hash_media):
    p = _by_rowid(list(imessage.run(_store(tmp_path))))[6]["payload"]
    assert p["chat"] == {"id": CREW, "type": "group", "name": "Mooring crew"}
    assert p["sender"] == {"kind": "phone", "value": "+4790000002"}


def test_run_from_me_in_a_group_has_no_sender(tmp_path, hash_media):
    p = _by_rowid(list(imessage.run(_store(tmp_path))))[13]["payload"]
    assert p["from_me"] is True and "sender" not in p


def test_run_reply_to_is_the_guid_of_the_original(tmp_path, hash_media):
    p = _by_rowid(list(imessage.run(_store(tmp_path))))[12]["payload"]
    assert p["reply_to"] == "G-6" and p["text"] == "me"


def test_run_alphanumeric_sms_sender_is_a_handle(tmp_path, hash_media):
    p = _by_rowid(list(imessage.run(_store(tmp_path))))[17]["payload"]
    assert p["chat"] == {"id": TELENOR, "type": "direct"}  # an empty display_name is no name
    assert p["sender"] == {"kind": "handle", "value": TELENOR}


def test_run_phone_refs_meet_ios_contacts_on_the_same_value(tmp_path, hash_media):
    """The point of RFC 0006: one resolution of +4790000001 covers both adapters' lines."""
    p = _by_rowid(list(imessage.run(_store(tmp_path))))[1]["payload"]
    assert p["sender"]["value"] == phone.normalise("+47 900 00 001", "")[0]


def test_run_null_guid_is_keyed_by_row_and_counted(tmp_path, hash_media):
    counts: dict[str, int] = {}
    p = _by_rowid(list(imessage.run(_store(tmp_path), counts=counts)))[20]["payload"]
    assert p["raw_id"] == "row20"
    assert counts["no_guid"] == 1


# -- run: media kinds and files ---------------------------------------------------------


@pytest.mark.parametrize(("rowid", "kind"), [(9, "image"), (10, "video"), (11, "document"), (18, "voice")])
def test_run_media_kind_from_the_mime_type(tmp_path, hash_media, rowid, kind):
    p = _by_rowid(list(imessage.run(_store(tmp_path))))[rowid]["payload"]
    assert p["media_kind"] == kind
    assert "media" not in p  # never payload.media in v1: the §1.1 store is not built yet


@pytest.mark.parametrize(
    ("mime", "kind"),
    [
        ("image/png", "image"),
        ("audio/mpeg", "voice"),
        ("text/vcard", "contact"),
        ("text/plain", "other"),
        (None, "other"),
    ],
)
def test_run_media_kind_covers_every_mime_family(tmp_path, hash_media, mime, kind):
    p = _store(tmp_path, with_media_files=False)
    con = sqlite3.connect(p)
    try:
        con.execute("UPDATE attachment SET mime_type = ? WHERE ROWID = 101", (mime,))
        con.commit()
    finally:
        con.close()
    assert _by_rowid(list(imessage.run(p)))[10]["payload"]["media_kind"] == kind


def test_run_object_replacement_character_is_not_text(tmp_path, hash_media):
    p = _by_rowid(list(imessage.run(_store(tmp_path))))[9]["payload"]
    assert "text" not in p


def test_run_media_file_that_exists_is_hashed_and_sized(tmp_path, hash_media):
    counts: dict[str, int] = {}
    p = _by_rowid(list(imessage.run(_store(tmp_path), counts=counts)))[9]["payload"]
    assert p["extra"]["media"] == {
        "sha256": hashlib.sha256(IMAGE_BYTES).hexdigest(),
        "bytes": len(IMAGE_BYTES),
        "local_path": IMAGE_PATH,
        "media_type": "image/jpeg",
    }
    assert "media_missing" not in p["extra"] and "more_media" not in p["extra"]
    assert counts["media_hashed"] == 2  # rows 9 and 18


def test_run_media_file_that_is_missing_is_flagged(tmp_path, hash_media):
    counts: dict[str, int] = {}
    p = _by_rowid(list(imessage.run(_store(tmp_path), counts=counts)))[10]["payload"]
    assert p["extra"]["media_missing"] is True
    assert p["extra"]["media"] == {"local_path": VIDEO_PATH, "media_type": "video/quicktime"}
    assert counts["media_missing"] == 3  # rows 10, 11 and the second file on 18


def test_run_hashing_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGBOOK_IMESSAGE_HASH_MEDIA", "0")
    counts: dict[str, int] = {}
    lines = _by_rowid(list(imessage.run(_store(tmp_path), counts=counts)))
    assert lines[9]["payload"]["extra"]["media"] == {"local_path": IMAGE_PATH, "media_type": "image/jpeg"}
    assert lines[10]["payload"]["extra"]["media_missing"] is True  # existence is still checked
    assert "media_hashed" not in counts and counts["media_missing"] == 3


def test_run_media_path_never_escapes_the_attachments_folder(tmp_path, hash_media):
    outside = tmp_path / "secret.txt"
    outside.write_text("not for the log", encoding="utf-8")
    counts: dict[str, int] = {}
    p = _by_rowid(list(imessage.run(_store(tmp_path), counts=counts)))[11]["payload"]
    assert p["media_kind"] == "document" and p["text"] == "read this"
    assert p["extra"]["media_missing"] is True and "sha256" not in p["extra"]["media"]
    assert p["extra"]["media"]["local_path"] == ESCAPE_PATH


def test_run_media_path_outside_any_attachments_folder_is_missing(tmp_path, hash_media):
    p = _store(tmp_path)
    con = sqlite3.connect(p)
    try:
        con.execute("UPDATE attachment SET filename = ? WHERE ROWID = 100", (str(tmp_path / "secret.txt"),))
        con.commit()
    finally:
        con.close()
    (tmp_path / "secret.txt").write_text("not for the log", encoding="utf-8")
    line = _by_rowid(list(imessage.run(p)))[9]["payload"]
    assert line["extra"]["media_missing"] is True and "sha256" not in line["extra"]["media"]


def test_run_second_and_later_attachments_go_under_more_media(tmp_path, hash_media):
    p = _by_rowid(list(imessage.run(_store(tmp_path))))[18]["payload"]
    assert p["media_kind"] == "voice"
    assert p["extra"]["media"] == {
        "sha256": hashlib.sha256(VOICE_BYTES).hexdigest(),
        "bytes": len(VOICE_BYTES),
        "local_path": VOICE_PATH,
        "media_type": "audio/x-caf",
    }
    assert "media_missing" not in p["extra"]
    assert p["extra"]["more_media"] == [
        {
            "media_kind": "contact",
            "media_missing": True,
            "media": {"local_path": CARD_PATH, "media_type": "text/vcard"},
        }
    ]


# -- run: what is skipped ------------------------------------------------------------------


def test_run_skips_and_counts_what_is_not_a_message(tmp_path, hash_media):
    counts: dict[str, int] = {}
    lines = _by_rowid(list(imessage.run(_store(tmp_path), counts=counts)))
    assert {4, 5, 7, 8, 14, 15, 19}.isdisjoint(lines)
    assert counts == {
        "skipped_reaction": 2,
        "skipped_system_event": 1,
        "skipped_bad_date": 1,
        "skipped_no_chat": 1,
        "skipped_no_body": 2,
        "media_hashed": 2,
        "media_missing": 3,
        "no_guid": 1,
    }


@pytest.mark.parametrize("code", [2000, 2005, 3000, 3005])
def test_run_skips_every_tapback_code(tmp_path, hash_media, code):
    p = _store(tmp_path, with_media_files=False)
    con = sqlite3.connect(p)
    try:
        con.execute("UPDATE message SET associated_message_type = ? WHERE ROWID = 1", (code,))
        con.commit()
    finally:
        con.close()
    counts: dict[str, int] = {}
    assert 1 not in _by_rowid(list(imessage.run(p, counts=counts)))
    assert counts["skipped_reaction"] == 3


def test_run_other_associated_types_are_kept_and_noted(tmp_path, hash_media):
    p = _store(tmp_path, with_media_files=False)
    con = sqlite3.connect(p)
    try:
        con.execute("UPDATE message SET associated_message_type = 1000 WHERE ROWID = 1")  # a sticker, say
        con.commit()
    finally:
        con.close()
    line = _by_rowid(list(imessage.run(p)))[1]["payload"]
    assert line["extra"] == {"service": "SMS", "associated_message_type": 1000}


# -- through the log: append, dedupe on re-run, CLI -----------------------------------


def test_run_lines_append_and_re_running_appends_nothing(tmp_path, hash_media):
    p = _store(tmp_path)
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    assert lb.append_many(imessage.run(p)) == 13
    assert lb.append_many(imessage.run(p)) == 0
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 13
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
        assert line["tz"] == "Europe/Oslo"


def _cli(tmp_path):
    env = {**os.environ, "LOGBOOK_HOME": str(tmp_path / "lb"), "PYTHONPATH": str(ROOT)}
    env.pop("LOGBOOK_IMESSAGE_HASH_MEDIA", None)

    def run(*a):
        return subprocess.run(
            [sys.executable, "-m", "logbook.cli", *a],
            env=env,
            capture_output=True,
            encoding="utf-8",
            check=True,
        )

    return run


def test_cli_add_reports_lines_skips_and_media(tmp_path):
    run = _cli(tmp_path)
    run("init", str(tmp_path / "lb"), "--timezone", "Europe/Oslo")
    p = _store(tmp_path)
    out = run("add", str(p)).stdout
    assert "added 13 lines from imessage" in out
    skipped = "skipped 2 reactions, 1 group system events, 1 with an unusable date, 1 without a chat"
    assert f"{skipped}, 2 without a body" in out
    assert "also 2 with media hashed, 3 with media missing, 1 without a guid, keyed by row id" in out
    assert "added 0 lines from imessage" in run("add", str(p)).stdout
    assert "valid — 13 lines" in run("verify").stdout


# -- property: every emitted line is a valid message/v1 observation -------------------

MEDIA_KINDS = {"image", "video", "voice", "contact", "document", "other"}
MEDIA_KEYS = {"sha256", "bytes", "local_path", "media_type"}


def _rfc_rules(line: dict) -> None:
    assert set(line) == ENVELOPE
    assert line["kind"] == "message" and line["tier"] == 2 and line["end"] is None
    assert line["source"] == "imessage"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", line["at"])
    assert line["at"] >= "2010-07-07T"  # date >= 300000000 seconds
    p = line["payload"]
    assert set(p) <= {
        "schema",
        "raw_id",
        "chat",
        "from_me",
        "sender",
        "text",
        "media_kind",
        "reply_to",
        "extra",
    }
    assert {"schema", "raw_id", "chat", "from_me", "extra"} <= set(p)
    assert p["schema"] == "message/v1"
    assert isinstance(p["raw_id"], str) and p["raw_id"]
    assert set(p["chat"]) - {"name"} == {"id", "type"} and p["chat"]["type"] in {"direct", "group"}
    assert isinstance(p["chat"]["id"], str) and p["chat"]["id"]
    if "name" in p["chat"]:
        assert isinstance(p["chat"]["name"], str) and p["chat"]["name"].strip()
    assert isinstance(p["from_me"], bool)
    if p["from_me"]:
        assert "sender" not in p
    if "sender" in p:
        assert set(p["sender"]) == {"kind", "value"} and p["sender"]["kind"] in {"phone", "email", "handle"}
        assert p["sender"]["value"]
        if p["sender"]["kind"] == "phone":
            assert re.fullmatch(r"\+[0-9]+", p["sender"]["value"])
        if p["sender"]["kind"] == "email":
            assert "@" in p["sender"]["value"] and p["sender"]["value"] == p["sender"]["value"].lower()
    if "text" in p:
        assert isinstance(p["text"], str) and p["text"].strip()
    else:
        assert "media_kind" in p  # no body and no attachment is not a line
    if "media_kind" in p:
        assert p["media_kind"] in MEDIA_KINDS
    if "reply_to" in p:
        assert isinstance(p["reply_to"], str) and p["reply_to"]
    assert "media" not in p
    extra = p["extra"]
    assert set(extra) <= {"service", "associated_message_type", "media", "media_missing", "more_media"}
    if "service" in extra:
        assert isinstance(extra["service"], str) and extra["service"]
    if "associated_message_type" in extra:
        assert isinstance(extra["associated_message_type"], int)
        assert not (
            2000 <= extra["associated_message_type"] <= 2005
            or 3000 <= extra["associated_message_type"] <= 3005
        )
    if "media" in extra:
        assert "media_kind" in p
        assert set(extra["media"]) <= MEDIA_KEYS
        assert ("sha256" in extra["media"]) == ("bytes" in extra["media"])
        assert not ("sha256" in extra["media"] and extra.get("media_missing"))
    if "more_media" in extra:
        assert "media" in extra and isinstance(extra["more_media"], list) and extra["more_media"]
        for item in extra["more_media"]:
            assert (
                set(item) - {"media_missing"} == {"media_kind", "media"} and item["media_kind"] in MEDIA_KINDS
            )
            assert set(item["media"]) <= MEDIA_KEYS
    json.dumps(line, allow_nan=False)


_handle_id = st.one_of(
    st.text(alphabet="0123456789", min_size=1, max_size=15).map(lambda d: "+" + d),
    st.text(alphabet="0123456789", min_size=1, max_size=6),
    st.text(alphabet="abcXYZ.", min_size=1, max_size=8).map(lambda s: s + "@Example.org"),
    st.text(max_size=12),
)
_handle = st.tuples(_handle_id, st.sampled_from(["SMS", "iMessage"]))
_name = st.one_of(st.none(), st.text(max_size=12))
_chat = st.tuples(st.one_of(st.none(), st.text(max_size=24)), _name, st.one_of(st.none(), st.integers(0, 50)))
_date = st.one_of(
    st.none(),
    st.integers(-(2**33), 2**33),
    st.integers(0, 2**62),
    st.floats(min_value=-1e10, max_value=1e19, allow_nan=False, allow_infinity=False),
)
_blob = st.one_of(
    st.none(),
    st.binary(max_size=40),
    st.text(max_size=200).map(_typedstream),
    st.just(b"NSString\x01\x94\x84\x01+\x81\xff\xff"),  # a length past the end of the blob
    st.just(b"NSString\x01\x94\x84\x01+\x03\xff\xfe\xfd"),  # not UTF-8
)
_message = st.tuples(
    st.one_of(st.none(), st.text(max_size=16)),  # guid
    st.one_of(st.none(), st.text(max_size=40), st.just("\ufffc")),  # text
    _blob,
    st.one_of(st.none(), st.integers(0, 5)),  # handle index; may point past the end
    _date,
    st.one_of(st.none(), st.integers(0, 1)),  # from me
    st.one_of(st.none(), st.sampled_from(["SMS", "iMessage", "RCS"])),
    st.one_of(st.none(), st.integers(0, 3), st.integers(1000, 3006)),  # associated_message_type
    st.one_of(st.none(), st.text(max_size=16)),  # reply_to_guid
    st.one_of(st.none(), st.integers(0, 6)),  # item_type
    st.one_of(st.none(), st.integers(0, 6)),  # chat index; may point past the end, or nothing
    st.lists(st.integers(0, 3), max_size=3, unique=True),  # attachment indexes
)
_attachment = st.tuples(
    st.one_of(
        st.none(),
        st.text(max_size=30),
        st.just("~/Library/SMS/Attachments/x/y/z/a.jpg"),
        st.just("/var/mobile/Library/SMS/Attachments/x/y/z/a.jpg"),
        st.just("~/Library/SMS/Attachments/../escape"),
    ),
    st.one_of(
        st.none(),
        st.sampled_from(["image/jpeg", "video/mp4", "audio/x-caf", "text/vcard", "application/pdf", "x/y"]),
    ),
    st.one_of(st.none(), st.integers(0, 2**31)),
)
_store_strategy = st.tuples(
    st.lists(_handle, max_size=4),
    st.lists(_chat, max_size=5),
    st.lists(_attachment, max_size=3),
    st.lists(_message, max_size=12),
)


@settings(max_examples=40, deadline=None)
@given(_store_strategy)
def test_any_message_store_yields_only_valid_lines(tmp_path_factory, store):
    handles, chats, attachments, messages = store
    folder = tmp_path_factory.mktemp("im")
    p = folder / "sms.db"
    (folder / "Attachments" / "x" / "y" / "z").mkdir(parents=True)
    (folder / "Attachments" / "x" / "y" / "z" / "a.jpg").write_bytes(b"jpeg")
    con = sqlite3.connect(p)
    try:
        con.executescript(DDL)
        for rowid, handle in enumerate(handles, start=1):
            con.execute("INSERT INTO handle VALUES (?,?,?)", (rowid, *handle))
        for rowid, chat in enumerate(chats, start=1):
            con.execute("INSERT INTO chat VALUES (?,?,?,?,?)", (rowid, f"chat-{rowid}", *chat))
        for rowid, item in enumerate(attachments, start=1):
            con.execute("INSERT INTO attachment VALUES (?,?,?,?,?)", (rowid, f"at-{rowid}", *item))
        guids: set[str] = set()
        for rowid, m in enumerate(messages, start=1):
            guid, text, blob, handle, date, from_me, service, assoc, reply_to, item_type, chat, items = m
            guid = None if guid in guids else guid  # the real store's guid is UNIQUE
            guids.add(guid)
            con.execute(
                "INSERT INTO message VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    rowid,
                    guid,
                    text,
                    blob,
                    handle,
                    date,
                    from_me,
                    service,
                    assoc,
                    reply_to,
                    item_type,
                    int(bool(items)),
                ),
            )
            if chat is not None:
                con.execute("INSERT INTO chat_message_join VALUES (?,?)", (chat + 1, rowid))
            for item in items:
                con.execute("INSERT INTO message_attachment_join VALUES (?,?)", (rowid, item + 1))
        con.commit()
    finally:
        con.close()
    counts: dict[str, int] = {}
    env = {k: v for k, v in os.environ.items() if k != "LOGBOOK_IMESSAGE_HASH_MEDIA"}
    with mock.patch.dict(os.environ, env, clear=True):
        lines = list(imessage.run(p, counts=counts))
    for line in lines:
        _rfc_rules(line)
    skipped = sum(n for key, n in counts.items() if key.startswith("skipped_"))
    assert len(lines) + skipped == len(messages)
    lb = Logbook.init(tmp_path_factory.mktemp("lb"), "UTC")
    appended = lb.append_many(lines)
    raw_ids = {line["payload"]["raw_id"] for line in lines}
    assert appended == len(raw_ids)  # the log dedupes on (source, raw_id); collisions are the store's
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
