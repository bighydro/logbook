"""WhatsApp iOS ChatStorage.sqlite → message/v1 (RFC 0008): one line per message, media by digest only."""

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
from logbook.adapters import dawarich, ios_contacts, phone, whatsapp
from logbook.adapters.takeout import location
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
DAWARICH = ROOT / "tests" / "fixtures" / "dawarich" / "export.json"
TAKEOUT = ROOT / "tests" / "fixtures" / "takeout" / "Records.json"
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
APPLE_EPOCH = 978_307_200  # 2001-01-01T00:00:00Z, the zero of ZMESSAGEDATE

DDL = """
CREATE TABLE ZWACHATSESSION (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER,
    ZSESSIONTYPE INTEGER, ZCONTACTJID VARCHAR, ZPARTNERNAME VARCHAR
);
CREATE TABLE ZWAGROUPMEMBER (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZMEMBERJID VARCHAR, ZCONTACTNAME VARCHAR
);
CREATE TABLE ZWAMESSAGE (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER,
    ZISFROMME INTEGER, ZMESSAGETYPE INTEGER, ZCHATSESSION INTEGER, ZGROUPMEMBER INTEGER,
    ZMEDIAITEM INTEGER, ZMESSAGEDATE TIMESTAMP, ZFROMJID VARCHAR, ZSTANZAID VARCHAR, ZTEXT VARCHAR
);
CREATE TABLE ZWAMEDIAITEM (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER,
    ZFILESIZE INTEGER, ZMESSAGE INTEGER, ZMEDIALOCALPATH VARCHAR, ZTITLE VARCHAR
);
"""


def _apple(stamp: str) -> int:
    return int(datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()) - APPLE_EPOCH


OLA = "4790000001@s.whatsapp.net"
INES = "4790000002@s.whatsapp.net"
CREW = "12036300000000001@g.us"
STATUS = "status@broadcast"
LIST = "1663000000000@broadcast"
LID = "236000000000001@lid"  # a linked-device id, not a phone number

# (Z_PK, ZSESSIONTYPE, ZCONTACTJID, ZPARTNERNAME) — synthetic; nobody here exists
CHATS = [
    (1, 0, OLA, "Ola Nordmann"),
    (2, 0, INES, "Ines Nordmann"),
    (3, 1, CREW, "Mooring crew"),
    (4, 3, STATUS, None),
    (5, 2, LIST, "Regatta list"),
]
# (Z_PK, ZMEMBERJID, ZCONTACTNAME)
MEMBERS = [(10, OLA, "Ola"), (11, INES, "Ines"), (12, LID, None)]
# (Z_PK, ZISFROMME, ZMESSAGETYPE, ZCHATSESSION, ZGROUPMEMBER, ZMEDIAITEM, ZMESSAGEDATE, ZFROMJID,
#  ZSTANZAID, ZTEXT)
T0 = _apple("2026-03-02T17:42:10Z")
MESSAGES = [
    (1, 0, 0, 1, None, None, T0, OLA, "3EB0A1F5C2D4E6B7", "mooring photos sent, check your mail"),
    (2, 1, 0, 1, None, None, T0 + 60, None, "3EB0A1F5C2D4E6B8", "got them, thanks"),
    (3, 0, 1, 1, None, 100, T0 + 120, OLA, "3EB0A1F5C2D4E6B9", "the stern line"),  # image, file exists
    (4, 0, 2, 2, None, 101, T0 + 180, INES, "3EB0A1F5C2D4E6C0", None),  # video, file missing
    (5, 1, 3, 2, None, None, T0 + 240, None, "3EB0A1F5C2D4E6C1", None),  # voice note, no media row
    (6, 0, 0, 3, 10, None, T0 + 300, OLA, None, "who has the winch handle?"),  # null stanza id
    (7, 0, 0, 3, 12, None, T0 + 360, LID, "3EB0A1F5C2D4E6C3", "me"),  # sender is a lid, not a phone
    (8, 0, 0, 3, None, None, T0 + 420, INES, "3EB0A1F5C2D4E6C4", "on the boat"),  # sender from ZFROMJID
    (9, 0, 6, 3, 10, None, T0 + 480, OLA, "3EB0A1F5C2D4E6C5", None),  # group system event
    (10, 0, 0, 1, None, None, 12_345, OLA, "3EB0A1F5C2D4E6C6", "from before the epoch"),  # garbage date
    (11, 0, 1, 4, None, None, T0 + 540, OLA, "3EB0A1F5C2D4E6C7", None),  # status chat
    (12, 1, 0, 5, None, None, T0 + 600, None, "3EB0A1F5C2D4E6C8", "regatta moved to sunday"),
    (13, 0, 99, 1, None, None, T0 + 660, OLA, "3EB0A1F5C2D4E6C9", "a poll, say"),  # unknown type
    (14, 0, 5, 1, None, None, T0 + 720, OLA, "3EB0A1F5C2D4E6D0", None),  # location
    (15, 1, 7, 1, None, None, T0 + 780, None, "3EB0A1F5C2D4E6D1", "https://example.org/tide"),  # link
    (16, 0, 15, 2, None, None, T0 + 840, INES, "3EB0A1F5C2D4E6D2", None),  # sticker
    (17, 1, 0, 2, None, None, T0 + 900, None, "3EB0A1F5C2D4E6D3", None),  # text type, nothing in it
    (18, 0, 0, 999, None, None, T0 + 960, OLA, "3EB0A1F5C2D4E6D4", "orphan"),  # no such chat
]
IMAGE_PATH = f"Media/{OLA}/a/b/photo.jpg"
VIDEO_PATH = f"Media/{INES}/c/d/clip.mp4"
IMAGE_BYTES = b"\xff\xd8not really a jpeg\xff\xd9"
# (Z_PK, ZFILESIZE, ZMESSAGE, ZMEDIALOCALPATH, ZTITLE)
MEDIA = [(100, len(IMAGE_BYTES), 3, IMAGE_PATH, None), (101, 4_000_000, 4, VIDEO_PATH, "clip.mp4")]


def _store(tmp_path: Path, name: str = "ChatStorage.sqlite", with_media_file: bool = True) -> Path:
    p = tmp_path / name
    con = sqlite3.connect(p)
    try:
        con.executescript(DDL)
        con.executemany("INSERT INTO ZWACHATSESSION VALUES (?,1,1,?,?,?)", CHATS)
        con.executemany("INSERT INTO ZWAGROUPMEMBER VALUES (?,1,1,?,?)", MEMBERS)
        con.executemany("INSERT INTO ZWAMESSAGE VALUES (?,1,1,?,?,?,?,?,?,?,?,?)", MESSAGES)
        con.executemany("INSERT INTO ZWAMEDIAITEM VALUES (?,1,1,?,?,?,?)", MEDIA)
        con.commit()
    finally:
        con.close()
    if with_media_file:
        image = tmp_path / "Message" / Path(*IMAGE_PATH.split("/"))  # the fixture's own POSIX string
        image.parent.mkdir(parents=True)
        image.write_bytes(IMAGE_BYTES)
    return p


def _by_pk(lines: list[dict]) -> dict[int, dict]:
    """Lines keyed by the ZWAMESSAGE.Z_PK they came from (the fixture's stanza ids are unique)."""
    stanza = {m[8] or f"pk{m[0]}": m[0] for m in MESSAGES}
    return {stanza[line["payload"]["raw_id"].split(":", 1)[1]]: line for line in lines}


@pytest.fixture
def hash_media(monkeypatch):
    monkeypatch.delenv("LOGBOOK_WHATSAPP_HASH_MEDIA", raising=False)


# -- registry ---------------------------------------------------------------


def test_registry_lists_whatsapp():
    assert "whatsapp" in [a.NAME for a in adapters.all_adapters()]


def test_registry_find_returns_whatsapp_for_a_chat_store(tmp_path):
    found = adapters.find(_store(tmp_path))
    assert found is not None and found.NAME == "whatsapp"


def test_registry_find_by_content_not_by_name(tmp_path):
    """A Finder/iTunes backup stores the file under its hashed name, without an extension."""
    found = adapters.find(_store(tmp_path, "7c7fba66680ef796b916b067077cc246adacf01d"))
    assert found is not None and found.NAME == "whatsapp"


# -- sniff ------------------------------------------------------------------


def test_sniff_accepts_chat_store(tmp_path):
    assert whatsapp.sniff(_store(tmp_path)) is True


def test_sniff_rejects_other_exports(tmp_path):
    assert whatsapp.sniff(DAWARICH) is False
    assert whatsapp.sniff(TAKEOUT) is False


def test_other_adapters_reject_the_chat_store(tmp_path):
    p = _store(tmp_path)
    assert dawarich.sniff(p) is False and location.sniff(p) is False and ios_contacts.sniff(p) is False


@pytest.mark.parametrize(
    "ddl",
    [
        "CREATE TABLE lines (seq INTEGER, hash TEXT);",
        "CREATE TABLE ZWACHATSESSION (Z_PK INTEGER PRIMARY KEY, ZCONTACTJID TEXT);",  # half of it
        "CREATE TABLE ZWAMESSAGE (Z_PK INTEGER PRIMARY KEY, ZTEXT TEXT);",
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
    assert whatsapp.sniff(p) is False


@pytest.mark.parametrize("content", ["", "just words\n", "SQLite format 3\0 but not really a database"])
def test_sniff_rejects_non_sqlite_files(tmp_path, content):
    p = tmp_path / "ChatStorage.sqlite"
    p.write_text(content, encoding="utf-8")
    assert whatsapp.sniff(p) is False


def test_sniff_rejects_directory_and_missing_file(tmp_path):
    assert whatsapp.sniff(tmp_path) is False
    assert whatsapp.sniff(tmp_path / "nope.sqlite") is False


def test_sniff_and_run_never_touch_the_source(tmp_path, hash_media):
    p = _store(tmp_path)
    before = p.read_bytes()
    assert whatsapp.sniff(p) is True
    list(whatsapp.run(p))
    assert p.read_bytes() == before
    assert sorted(q.name for q in tmp_path.iterdir()) == ["ChatStorage.sqlite", "Message"]  # no journal


# -- run: envelope ------------------------------------------------------------


def test_run_yields_message_lines_with_the_source_timestamp(tmp_path, hash_media):
    lines = list(whatsapp.run(_store(tmp_path)))
    assert len(lines) == 14
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["end"] is None and line["tz"] is None
        assert line["source"] == "whatsapp" and line["kind"] == "message" and line["tier"] == 2
        assert line["payload"]["schema"] == "message/v1"
    assert _by_pk(lines)[1]["at"] == "2026-03-02T17:42:10Z"


def test_run_streams_in_row_order(tmp_path, hash_media):
    lines = list(whatsapp.run(_store(tmp_path)))
    assert list(_by_pk(lines)) == [1, 2, 3, 4, 5, 6, 7, 8, 12, 13, 14, 15, 16, 17]


def test_run_honours_since(tmp_path, hash_media):
    lines = list(whatsapp.run(_store(tmp_path), since="2026-03-02T17:52:10Z"))  # T0 + 600
    assert list(_by_pk(lines)) == [12, 13, 14, 15, 16, 17]


# -- run: chats, senders, text --------------------------------------------------------


def test_run_direct_chat_and_sender_from_the_chat_jid(tmp_path, hash_media):
    p = _by_pk(list(whatsapp.run(_store(tmp_path))))[1]["payload"]
    assert p["raw_id"] == f"{OLA}:3EB0A1F5C2D4E6B7"
    assert p["chat"] == {"id": OLA, "type": "direct", "name": "Ola Nordmann"}
    assert p["from_me"] is False
    assert p["sender"] == {"kind": "phone", "value": "+4790000001"}
    assert p["text"] == "mooring photos sent, check your mail"
    assert "media_kind" not in p and "extra" not in p


def test_run_from_me_has_no_sender(tmp_path, hash_media):
    p = _by_pk(list(whatsapp.run(_store(tmp_path))))[2]["payload"]
    assert p["from_me"] is True and "sender" not in p
    assert p["text"] == "got them, thanks"


def test_run_group_sender_from_the_group_member(tmp_path, hash_media):
    p = _by_pk(list(whatsapp.run(_store(tmp_path))))[6]["payload"]
    assert p["chat"] == {"id": CREW, "type": "group", "name": "Mooring crew"}
    assert p["sender"] == {"kind": "phone", "value": "+4790000001"}


def test_run_group_sender_falls_back_to_zfromjid(tmp_path, hash_media):
    p = _by_pk(list(whatsapp.run(_store(tmp_path))))[8]["payload"]
    assert p["sender"] == {"kind": "phone", "value": "+4790000002"}


def test_run_sender_that_is_not_a_phone_is_a_handle(tmp_path, hash_media):
    p = _by_pk(list(whatsapp.run(_store(tmp_path))))[7]["payload"]
    assert p["sender"] == {"kind": "handle", "value": LID}


def test_run_phone_refs_meet_ios_contacts_on_the_same_value(tmp_path, hash_media):
    """The point of RFC 0006: one resolution of +4790000001 covers both adapters' lines."""
    p = _by_pk(list(whatsapp.run(_store(tmp_path))))[1]["payload"]
    assert p["sender"]["value"] == phone.normalise("+47 900 00 001", "")[0]


def test_run_broadcast_list_is_a_group(tmp_path, hash_media):
    p = _by_pk(list(whatsapp.run(_store(tmp_path))))[12]["payload"]
    assert p["chat"] == {"id": LIST, "type": "group", "name": "Regatta list"}
    assert p["from_me"] is True
    assert p["extra"] == {"broadcast_list": True}


def test_run_null_stanza_id_is_keyed_by_row_and_counted(tmp_path, hash_media):
    counts: dict[str, int] = {}
    p = _by_pk(list(whatsapp.run(_store(tmp_path), counts=counts)))[6]["payload"]
    assert p["raw_id"] == f"{CREW}:pk6"
    assert counts["no_stanza_id"] == 1


def test_run_empty_text_is_absent(tmp_path, hash_media):
    lines = _by_pk(list(whatsapp.run(_store(tmp_path))))
    assert "text" not in lines[17]["payload"]
    assert "text" not in lines[14]["payload"]


# -- run: media kinds and files ---------------------------------------------------------


@pytest.mark.parametrize(
    ("pk", "kind"),
    [(3, "image"), (4, "video"), (5, "voice"), (14, "location"), (15, "link"), (16, "sticker")],
)
def test_run_media_kind_from_the_message_type(tmp_path, hash_media, pk, kind):
    p = _by_pk(list(whatsapp.run(_store(tmp_path))))[pk]["payload"]
    assert p["media_kind"] == kind
    assert "media" not in p  # never payload.media in v1: the §1.1 store is not built yet


def test_run_unknown_message_type_keeps_the_code(tmp_path, hash_media):
    p = _by_pk(list(whatsapp.run(_store(tmp_path))))[13]["payload"]
    assert "media_kind" not in p
    assert p["text"] == "a poll, say"
    assert p["extra"] == {"message_type": 99}


def test_run_media_file_that_exists_is_hashed_and_sized(tmp_path, hash_media):
    counts: dict[str, int] = {}
    p = _by_pk(list(whatsapp.run(_store(tmp_path), counts=counts)))[3]["payload"]
    assert p["text"] == "the stern line"  # the caption
    assert p["extra"]["media"] == {
        "sha256": hashlib.sha256(IMAGE_BYTES).hexdigest(),
        "bytes": len(IMAGE_BYTES),
        "local_path": IMAGE_PATH,
    }
    assert "media_missing" not in p["extra"]
    assert counts["media_hashed"] == 1


def test_run_media_file_that_is_missing_is_flagged(tmp_path, hash_media):
    counts: dict[str, int] = {}
    p = _by_pk(list(whatsapp.run(_store(tmp_path), counts=counts)))[4]["payload"]
    assert p["extra"]["media_missing"] is True
    assert p["extra"]["media"] == {"local_path": VIDEO_PATH, "title": "clip.mp4"}
    assert counts["media_missing"] == 1


def test_run_media_message_without_a_media_row_has_no_media_extra(tmp_path, hash_media):
    p = _by_pk(list(whatsapp.run(_store(tmp_path))))[5]["payload"]
    assert p["media_kind"] == "voice" and "extra" not in p


def test_run_hashing_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGBOOK_WHATSAPP_HASH_MEDIA", "0")
    counts: dict[str, int] = {}
    lines = _by_pk(list(whatsapp.run(_store(tmp_path), counts=counts)))
    assert lines[3]["payload"]["extra"] == {"media": {"local_path": IMAGE_PATH}}
    assert lines[4]["payload"]["extra"]["media_missing"] is True  # existence is still checked
    assert "media_hashed" not in counts and counts["media_missing"] == 1


def test_run_media_path_never_escapes_the_message_folder(tmp_path, hash_media):
    outside = tmp_path / "secret.txt"
    outside.write_text("not for the log", encoding="utf-8")
    p = _store(tmp_path, with_media_file=False)
    con = sqlite3.connect(p)
    try:
        con.execute("UPDATE ZWAMEDIAITEM SET ZMEDIALOCALPATH = '../secret.txt' WHERE Z_PK = 100")
        con.commit()
    finally:
        con.close()
    counts: dict[str, int] = {}
    line = _by_pk(list(whatsapp.run(p, counts=counts)))[3]["payload"]
    assert line["extra"]["media_missing"] is True and "sha256" not in line["extra"]["media"]
    assert "media_hashed" not in counts


# -- run: what is skipped ------------------------------------------------------------------


def test_run_skips_and_counts_what_is_not_a_message(tmp_path, hash_media):
    counts: dict[str, int] = {}
    lines = _by_pk(list(whatsapp.run(_store(tmp_path), counts=counts)))
    assert {9, 10, 11, 18}.isdisjoint(lines)
    assert counts == {
        "skipped_system_event": 1,
        "skipped_bad_date": 1,
        "skipped_status": 1,
        "skipped_no_chat": 1,
        "no_stanza_id": 1,
        "media_hashed": 1,
        "media_missing": 1,
    }


def test_run_skips_a_status_chat_by_jid_even_with_another_session_type(tmp_path, hash_media):
    p = _store(tmp_path, with_media_file=False)
    con = sqlite3.connect(p)
    try:
        con.execute("UPDATE ZWACHATSESSION SET ZSESSIONTYPE = 0 WHERE Z_PK = 4")
        con.commit()
    finally:
        con.close()
    counts: dict[str, int] = {}
    assert 11 not in _by_pk(list(whatsapp.run(p, counts=counts)))
    assert counts["skipped_status"] == 1


# -- through the log: append, dedupe on re-run, CLI -----------------------------------


def test_run_lines_append_and_re_running_appends_nothing(tmp_path, hash_media):
    p = _store(tmp_path)
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    assert lb.append_many(whatsapp.run(p)) == 14
    assert lb.append_many(whatsapp.run(p)) == 0
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 14
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
        assert line["tz"] == "Europe/Oslo"


def _cli(tmp_path):
    env = {**os.environ, "LOGBOOK_HOME": str(tmp_path / "lb"), "PYTHONPATH": str(ROOT)}
    env.pop("LOGBOOK_WHATSAPP_HASH_MEDIA", None)

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
    assert "added 14 lines from whatsapp" in out
    skipped = "skipped 1 group system events, 1 with an unusable date, 1 in a status chat, 1 without a chat"
    assert skipped in out
    assert "also 1 with media hashed, 1 with media missing, 1 without a stanza id, keyed by row id" in out
    assert "added 0 lines from whatsapp" in run("add", str(p)).stdout
    assert "valid — 14 lines" in run("verify").stdout


# -- property: every emitted line is a valid message/v1 observation -------------------

MEDIA_KINDS = {"image", "video", "voice", "contact", "location", "link", "document", "gif", "sticker"}


def _rfc_rules(line: dict, chats: dict[int, tuple]) -> None:
    assert set(line) == ENVELOPE
    assert line["kind"] == "message" and line["tier"] == 2 and line["end"] is None
    assert line["source"] == "whatsapp"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", line["at"])
    assert line["at"] >= "2010-07-07T"  # ZMESSAGEDATE >= 300000000
    p = line["payload"]
    assert set(p) <= {"schema", "raw_id", "chat", "from_me", "sender", "text", "media_kind", "extra"}
    assert {"schema", "raw_id", "chat", "from_me"} <= set(p)
    assert p["schema"] == "message/v1"
    assert isinstance(p["raw_id"], str) and p["raw_id"].startswith(p["chat"]["id"] + ":")
    assert set(p["chat"]) - {"name"} == {"id", "type"} and p["chat"]["type"] in {"direct", "group"}
    assert p["chat"]["id"] != "status@broadcast"
    assert isinstance(p["from_me"], bool)
    if p["from_me"]:
        assert "sender" not in p
    if "sender" in p:
        assert set(p["sender"]) == {"kind", "value"} and p["sender"]["kind"] in {"phone", "handle"}
        if p["sender"]["kind"] == "phone":
            assert re.fullmatch(r"\+[0-9]+", p["sender"]["value"])
    if "text" in p:
        assert isinstance(p["text"], str) and p["text"].strip()
    if "media_kind" in p:
        assert p["media_kind"] in MEDIA_KINDS
    assert "media" not in p
    if "extra" in p:
        assert isinstance(p["extra"], dict) and p["extra"]
        if "media" in p["extra"]:
            assert set(p["extra"]["media"]) <= {"sha256", "bytes", "local_path", "title"}
            assert isinstance(p["extra"]["media"]["local_path"], str)
        if "message_type" in p["extra"]:
            assert isinstance(p["extra"]["message_type"], int) and "media_kind" not in p
    json.dumps(line, allow_nan=False)


_jid = st.one_of(
    st.text(alphabet="0123456789", min_size=1, max_size=15).map(lambda d: d + "@s.whatsapp.net"),
    st.text(alphabet="0123456789", min_size=1, max_size=18).map(lambda d: d + "@g.us"),
    st.just("status@broadcast"),
    st.text(max_size=20),
    st.none(),
)
_name = st.one_of(st.none(), st.text(max_size=12))
_chat = st.tuples(st.one_of(st.none(), st.integers(0, 4)), _jid, _name)
_member = st.tuples(_jid, _name)
_date = st.one_of(
    st.none(),
    st.integers(-(2**33), 2**33),
    st.floats(min_value=-1e10, max_value=1e10, allow_nan=False, allow_infinity=False),
)
_type = st.one_of(st.none(), st.integers(0, 20), st.integers(0, 2**31))
_message = st.tuples(
    st.one_of(st.none(), st.integers(0, 1)),  # from me
    _type,
    st.integers(0, 6),  # chat index; may point past the end
    st.one_of(st.none(), st.integers(0, 4)),  # member index
    st.one_of(st.none(), st.integers(0, 3)),  # media index
    _date,
    _jid,
    st.one_of(st.none(), st.text(max_size=16)),  # stanza id
    st.one_of(st.none(), st.text(max_size=40)),  # text
)
_media = st.tuples(
    st.one_of(st.none(), st.integers(0, 2**31)),
    st.one_of(st.none(), st.text(max_size=30), st.just("Media/x/y.jpg"), st.just("../escape")),
    _name,
)
_store_strategy = st.tuples(
    st.lists(_chat, max_size=5),
    st.lists(_member, max_size=4),
    st.lists(_media, max_size=3),
    st.lists(_message, max_size=12),
)


@settings(max_examples=40, deadline=None)
@given(_store_strategy)
def test_any_chat_store_yields_only_valid_lines(tmp_path_factory, store):
    chats, members, media, messages = store
    folder = tmp_path_factory.mktemp("wa")
    p = folder / "ChatStorage.sqlite"
    (folder / "Message" / "Media" / "x").mkdir(parents=True)
    (folder / "Message" / "Media" / "x" / "y.jpg").write_bytes(b"jpeg")
    con = sqlite3.connect(p)
    try:
        con.executescript(DDL)
        for pk, chat in enumerate(chats, start=1):
            con.execute("INSERT INTO ZWACHATSESSION VALUES (?,1,1,?,?,?)", (pk, *chat))
        for pk, member in enumerate(members, start=1):
            con.execute("INSERT INTO ZWAGROUPMEMBER VALUES (?,1,1,?,?)", (pk, *member))
        for pk, item in enumerate(media, start=1):
            con.execute("INSERT INTO ZWAMEDIAITEM VALUES (?,1,1,?,NULL,?,?)", (pk, *item))
        for pk, (from_me, mtype, chat, member, item, date, jid, stanza, text) in enumerate(messages, start=1):
            con.execute(
                "INSERT INTO ZWAMESSAGE VALUES (?,1,1,?,?,?,?,?,?,?,?,?)",
                (pk, from_me, mtype, chat + 1, member, item, date, jid, stanza, text),
            )
        con.commit()
    finally:
        con.close()
    counts: dict[str, int] = {}
    env = {k: v for k, v in os.environ.items() if k != "LOGBOOK_WHATSAPP_HASH_MEDIA"}
    with mock.patch.dict(os.environ, env, clear=True):
        lines = list(whatsapp.run(p, counts=counts))
    by_pk = dict(enumerate(chats, start=1))
    for line in lines:
        _rfc_rules(line, by_pk)
    skipped = sum(n for key, n in counts.items() if key.startswith("skipped_"))
    assert len(lines) + skipped == len(messages)
    lb = Logbook.init(tmp_path_factory.mktemp("lb"), "UTC")
    appended = lb.append_many(lines)
    raw_ids = {(line["payload"]["raw_id"]) for line in lines}
    assert appended == len(raw_ids)  # the log dedupes on (source, raw_id); collisions are the store's
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
