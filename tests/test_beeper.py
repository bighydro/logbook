"""Beeper BeeperStore.sqlite → message/v1 (RFC 0008): what the phone's Matrix cache holds in clear."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_keyed_archive import archive

from logbook import adapters
from logbook.adapters import beeper, ios_notes, whatsapp
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}

DDL = """
CREATE TABLE ZBSEVENT (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZISREDACTED INTEGER,
    ZISREDACTION INTEGER, ZCREATEDDATE TIMESTAMP, ZEVENTID VARCHAR, ZROOMID VARCHAR, ZDATA BLOB);
CREATE TABLE ZBSROOMLASTMESSAGE (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZISECHO INTEGER,
    ZISREDACTED INTEGER, ZORIGINSERVERTS INTEGER, ZEVENTID VARCHAR, ZEVENTTYPE VARCHAR, ZMESSAGEBODY VARCHAR,
    ZROOMID VARCHAR, ZSENDER VARCHAR, ZSENDERDISPLAYNAME VARCHAR);
CREATE TABLE ZROOMITEMMO (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZISONEONONE INTEGER,
    ZTIMESTAMP INTEGER, ZDISPLAYNAME VARCHAR, ZNETWORK VARCHAR, ZROOMID VARCHAR, ZROOMTYPE VARCHAR);
CREATE TABLE ZROOMMEMBERMO (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZMEMBERSHIP VARCHAR,
    ZPROVIDEDDISPLAYNAME VARCHAR, ZROOMID VARCHAR, ZUSERID VARCHAR, ZCONTACTPREFERREDNAME VARCHAR,
    ZEMAILIDENTIFIER VARCHAR, ZPHONENUMBERIDENTIFIER VARCHAR, ZISBRIDGEBOT INTEGER);
"""

# -- the fixture: synthetic, nobody in it exists ------------------------------------------

OWNER = "@kari:beeper.com"
OLA, PER, NILS, ME_ON_WHATSAPP = (
    "@whatsapp_4790000001:beeper.local",
    "@telegram_1001:beeper.local",
    "@facebook_777:beeper.local",
    "@whatsapp_4790000000:beeper.local",
)
ROOM_A, ROOM_B, ROOM_C = "!a:beeper.local", "!b:beeper.local", "!c:beeper.local"
T0 = 1_772_000_000_000  # ms: 2026-02-25T06:13:20Z
ROOMS = [
    (1, 1, T0, "Ola Nordmann", "whatsapp", ROOM_A, "other"),
    (2, 0, T0, "Sailing crew", "telegram", ROOM_B, "other"),
    (3, 1, T0, "Nils", "facebook", ROOM_C, "other"),
]
# (membership, provided name, room, user, contact name, email, phone, bridge bot)
MEMBERS = [
    ("join", "Kari", ROOM_A, OWNER, None, None, None, 0),
    ("join", "Kari", ROOM_B, OWNER, None, None, None, 0),
    ("join", "Kari", ROOM_C, OWNER, None, None, None, 0),
    ("join", "Ola N (WA)", ROOM_A, OLA, "Ola", None, "+4790000001", 0),
    ("join", "Per", ROOM_B, PER, None, None, None, 0),
    ("join", "Nils", ROOM_C, NILS, None, "nils@example.org", None, 0),
    ("join", "WhatsApp bridge", ROOM_A, "@whatsappbot:beeper.local", None, None, None, 1),
    ("join", "Kari (WA)", ROOM_A, ME_ON_WHATSAPP, None, None, "+4790000000", 0),
]


def _event(event_id: str, room: str, sender: str, ts: int, content: dict, clear: dict | None = None,
           matrix_type: str | None = None) -> bytes:  # fmt: skip
    data: dict = {
        "$class": "BSEvent",
        "eventType": 10,
        "eventId": event_id,
        "roomId": room,
        "userId": sender,
        "originServerTs": ts,
        "content": content,
        "clearEvent": clear,
        "redacts": None,
        "stateKey": None,
    }
    if matrix_type is not None:
        data["type"] = matrix_type
    return archive(data)


ENCRYPTED = {
    "algorithm": "m.megolm.v1.aes-sha2",
    "ciphertext": "AwgA…",
    "device_id": "DEV",
    "session_id": "S",
}
CLEAR_TEXT = {
    "$class": "BSEvent",
    "eventType": 10,
    "content": {"msgtype": "m.text", "body": "Mooring photos sent"},
}
REACTION = {"m.relates_to": {"rel_type": "m.annotation", "event_id": "$ev2", "key": "👍"}}
IMAGE = {"msgtype": "m.image", "body": "stern.jpg", "url": "mxc://x/y", "info": {"mimetype": "image/jpeg"}}
VOICE = {"msgtype": "m.audio", "body": "voice.ogg", "org.matrix.msc3245.voice": {}}
PUPPETED = {"msgtype": "m.text", "body": "Got them", "fi.mau.double_puppet_source": "x"}


def _blob(pk: int, room: str, sender: str, offset: int, content: dict, **kw: object) -> bytes:
    return _event(f"$ev{pk}", room, sender, T0 + offset, content, **kw)  # type: ignore[arg-type]


EVENTS = [  # (Z_PK, redacted, redaction, event id, room, blob)
    (1, 0, 0, "$ev1", ROOM_A, _blob(1, ROOM_A, OLA, 0, ENCRYPTED, clear=CLEAR_TEXT)),
    (2, 0, 0, "$ev2", ROOM_B, _blob(2, ROOM_B, OWNER, 1000, {"msgtype": "m.text", "body": "On my way"})),
    (3, 0, 0, "$ev3", ROOM_A, _blob(3, ROOM_A, OLA, 2000, ENCRYPTED)),
    (4, 0, 0, "$ev4", ROOM_B, _blob(4, ROOM_B, PER, 3000, REACTION, matrix_type="m.reaction")),
    (
        5,
        0,
        0,
        "$ev5",
        ROOM_B,
        _blob(5, ROOM_B, PER, 4000, {"membership": "join"}, matrix_type="m.room.member"),
    ),
    (6, 0, 0, "$ev6", ROOM_C, _blob(6, ROOM_C, NILS, 5000, IMAGE)),
    (7, 0, 0, "$ev7", ROOM_A, _blob(7, ROOM_A, ME_ON_WHATSAPP, 6000, PUPPETED)),
    (8, 1, 0, "$ev8", ROOM_A, _blob(8, ROOM_A, OLA, 7000, {})),
    (9, 0, 0, "$ev9", ROOM_A, _event("$ev9", ROOM_A, OLA, 0, {"msgtype": "m.text", "body": "no clock"})),
    (10, 0, 1, "$ev10", ROOM_A, _blob(10, ROOM_A, OLA, 8000, {"reason": "oops"})),
    (11, 0, 0, "$ev11", ROOM_C, _blob(11, ROOM_C, NILS, 9000, VOICE)),
    (12, 0, 0, "$ev12", ROOM_B, _blob(12, ROOM_B, PER, 10000, {"msgtype": "m.emote", "body": "waves"})),
]
# (Z_PK, echo, redacted, ts, event id, event type, body, room, sender, sender display name)
LAST = [
    (1, 0, 0, T0, "$ev1", "m.room.message", "Mooring photos sent", ROOM_A, OLA, "Ola N (WA)"),
    (2, 0, 0, T0 + 20000, "$last-b", "m.room.message", "See you at the marina", ROOM_B, PER, "Per"),
    (3, 0, 0, T0 + 21000, "$last-c1", "m.reaction", "👍", ROOM_C, NILS, "Nils"),
    (4, 0, 0, T0 + 22000, "$last-c2", "m.room.encrypted", "Encrypted message", ROOM_C, NILS, "Nils"),
    (5, 1, 0, 0, "", "", "", ROOM_C, "", ""),
    (6, 1, 0, T0 + 23000, "$last-c3", "m.sticker", "sticker", ROOM_C, OWNER, "Kari"),
]


def _store(folder: Path, name: str = "BeeperStore.sqlite") -> Path:
    p = folder / name
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    try:
        con.executescript(DDL)
        con.executemany("INSERT INTO ZROOMITEMMO VALUES (?,1,1,?,?,?,?,?,?)", ROOMS)
        con.executemany("INSERT INTO ZROOMMEMBERMO VALUES (NULL,1,1,?,?,?,?,?,?,?,?)", MEMBERS)
        con.executemany("INSERT INTO ZBSEVENT VALUES (?,1,1,?,?,700000000,?,?,?)", EVENTS)
        con.executemany("INSERT INTO ZBSROOMLASTMESSAGE VALUES (?,1,1,?,?,?,?,?,?,?,?,?)", LAST)
        con.commit()
    finally:
        con.close()
    return p


def _by_id(lines: list[dict]) -> dict[str, dict]:
    return {line["payload"]["raw_id"]: line for line in lines}


# -- registry and sniff -------------------------------------------------------------------


def test_registry_lists_beeper_and_finds_the_store(tmp_path):
    assert "beeper" in [a.NAME for a in adapters.all_adapters()]
    found = adapters.find(_store(tmp_path))
    assert found is not None and found.NAME == "beeper"


def test_sniff_rejects_other_stores_and_junk(tmp_path):
    assert beeper.sniff(tmp_path) is False
    assert beeper.sniff(tmp_path / "nope.sqlite") is False
    p = tmp_path / "other.sqlite"
    con = sqlite3.connect(p)
    try:
        con.executescript("CREATE TABLE ZBSEVENT (Z_PK INTEGER);")  # a third of it
    finally:
        con.close()
    assert beeper.sniff(p) is False
    (tmp_path / "text.sqlite").write_text("SQLite format 3\0 but not really", encoding="utf-8")
    assert beeper.sniff(tmp_path / "text.sqlite") is False


def test_other_adapters_reject_the_beeper_store(tmp_path):
    p = _store(tmp_path)
    assert ios_notes.sniff(p) is False and whatsapp.sniff(p) is False


def test_sniff_and_run_never_touch_the_source(tmp_path):
    p = _store(tmp_path)
    before = p.read_bytes()
    assert beeper.sniff(p) is True
    list(beeper.run(p))
    assert p.read_bytes() == before
    assert [q.name for q in tmp_path.iterdir()] == [p.name]


# -- run: envelope ------------------------------------------------------------------------


def test_run_yields_tier_2_message_lines_at_the_server_timestamp(tmp_path):
    lines = list(beeper.run(_store(tmp_path)))
    assert len(lines) == 8  # ev1, ev2, ev6, ev7, ev11, ev12 and two last-message rows
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["end"] is None and line["tz"] is None
        assert line["source"] == "beeper" and line["kind"] == "message" and line["tier"] == 2
        assert line["payload"]["schema"] == "message/v1"
    assert _by_id(lines)["$ev1"]["at"] == "2026-02-25T06:13:20Z"


def test_run_streams_events_then_last_messages_and_honours_since(tmp_path):
    p = _store(tmp_path)
    assert list(_by_id(list(beeper.run(p)))) == [
        "$ev1",
        "$ev2",
        "$ev6",
        "$ev7",
        "$ev11",
        "$ev12",
        "$last-b",
        "$last-c3",
    ]
    assert list(_by_id(list(beeper.run(p, since="2026-02-25T06:13:29Z")))) == [
        "$ev11",
        "$ev12",
        "$last-b",
        "$last-c3",
    ]


# -- run: the message fields --------------------------------------------------------------


def test_run_a_decrypted_event_has_chat_sender_phone_hint_and_text(tmp_path):
    p = _by_id(list(beeper.run(_store(tmp_path))))["$ev1"]["payload"]
    assert p["chat"] == {"id": ROOM_A, "type": "direct", "name": "Ola Nordmann"}
    assert p["from_me"] is False
    assert p["sender"] == {"kind": "phone", "value": "+4790000001", "name": "Ola"}  # the contact's name first
    assert p["text"] == "Mooring photos sent"
    assert p["extra"] == {"network": "whatsapp", "matrix_user": OLA}
    assert "media_kind" not in p


def test_run_the_owner_is_the_member_of_most_rooms(tmp_path):
    p = _by_id(list(beeper.run(_store(tmp_path))))["$ev2"]["payload"]
    assert p["from_me"] is True and "sender" not in p
    assert p["chat"] == {"id": ROOM_B, "type": "group", "name": "Sailing crew"}
    assert p["text"] == "On my way" and p["extra"]["network"] == "telegram"


def test_run_a_double_puppeted_message_is_from_me(tmp_path):
    p = _by_id(list(beeper.run(_store(tmp_path))))["$ev7"]["payload"]
    assert p["from_me"] is True and "sender" not in p and p["text"] == "Got them"
    assert p["extra"]["matrix_user"] == ME_ON_WHATSAPP


def test_run_media_messages_keep_the_kind_and_the_file_name_not_as_text(tmp_path):
    lines = _by_id(list(beeper.run(_store(tmp_path))))
    image = lines["$ev6"]["payload"]
    assert image["media_kind"] == "image" and "text" not in image
    assert image["extra"]["filename"] == "stern.jpg" and image["extra"]["media_type"] == "image/jpeg"
    assert image["sender"] == {"kind": "email", "value": "nils@example.org", "name": "Nils"}
    assert lines["$ev11"]["payload"]["media_kind"] == "voice"
    assert (
        lines["$ev12"]["payload"]["text"] == "waves" and lines["$ev12"]["payload"]["extra"]["emote"] is True
    )
    assert lines["$ev12"]["payload"]["sender"] == {"kind": "handle", "value": PER, "name": "Per"}


def test_run_last_message_rows_fill_in_what_the_event_table_lacks(tmp_path):
    counts: dict[str, int] = {}
    lines = _by_id(list(beeper.run(_store(tmp_path), counts=counts)))
    last = lines["$last-b"]["payload"]
    assert last["text"] == "See you at the marina" and last["from_me"] is False
    assert last["sender"] == {"kind": "handle", "value": PER, "name": "Per"}
    assert last["extra"]["from_last_message"] is True and last["extra"]["network"] == "telegram"
    sticker = lines["$last-c3"]["payload"]
    assert sticker["from_me"] is True and sticker["media_kind"] == "sticker" and "text" not in sticker
    assert counts["from_last_message"] == 2


def test_run_skips_and_counts_what_it_cannot_log(tmp_path):
    counts: dict[str, int] = {}
    list(beeper.run(_store(tmp_path), counts=counts))
    assert counts == {
        "skipped_encrypted": 2,  # ev3 and the encrypted last message
        "skipped_reaction": 2,  # ev4 and the reaction last message
        "skipped_system_event": 1,  # ev5, the membership
        "skipped_redacted": 2,  # ev8 (redacted) and ev10 (the redaction)
        "skipped_bad_date": 1,  # ev9
        "from_last_message": 2,
    }


# -- through the logbook -------------------------------------------------------------------


def test_add_dedupes_on_a_second_import_and_validates(tmp_path, monkeypatch):
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    lb = Logbook.init(root, "Europe/Oslo")
    store = _store(tmp_path / "phone")
    assert lb.append_many(beeper.run(store)) == 8
    assert lb.append_many(beeper.run(store)) == 0
    assert lb.verify()[0] == 8
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
