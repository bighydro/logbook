"""Apple Notes NoteStore.sqlite → note/v1 (RFC 0010): one line per note, the body out of gzip+protobuf."""

from __future__ import annotations

import gzip
import json
import os
import re
import sqlite3
import struct
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters
from logbook.adapters import dawarich, ios_contacts, ios_notes, whatsapp
from logbook.adapters.takeout import location
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
DAWARICH = ROOT / "tests" / "fixtures" / "dawarich" / "export.json"
TAKEOUT = ROOT / "tests" / "fixtures" / "takeout" / "Records.json"
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
APPLE_EPOCH = 978_307_200  # 2001-01-01T00:00:00Z, the zero of ZCREATIONDATE3/ZMODIFICATIONDATE1

DDL = """
CREATE TABLE ZICCLOUDSYNCINGOBJECT (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER,
    ZMARKEDFORDELETION INTEGER, ZISPASSWORDPROTECTED INTEGER, ZFOLDER INTEGER,
    ZCREATIONDATE3 TIMESTAMP, ZMODIFICATIONDATE1 TIMESTAMP,
    ZIDENTIFIER VARCHAR, ZTITLE1 VARCHAR, ZTITLE2 VARCHAR, ZSNIPPET VARCHAR
);
CREATE TABLE ZICNOTEDATA (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZNOTE INTEGER, ZDATA BLOB
);
"""

# -- a minimal protobuf encoder: what Apple's note archive looks like on the wire --------------

VARINT, FIXED64, LENGTH, FIXED32 = 0, 1, 2, 5


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _key(field: int, wire_type: int) -> bytes:
    return _varint((field << 3) | wire_type)


def _len(field: int, data: bytes) -> bytes:
    return _key(field, LENGTH) + _varint(len(data)) + data


def _int(field: int, n: int) -> bytes:
    return _key(field, VARINT) + _varint(n)


def _fixed64(field: int, n: int) -> bytes:
    return _key(field, FIXED64) + struct.pack("<Q", n)


def _fixed32(field: int, n: int) -> bytes:
    return _key(field, FIXED32) + struct.pack("<I", n)


def note_archive(text: str) -> bytes:
    """The shape of an Apple note archive, gzipped:

        root{ 1: varint, 2: Document{ 2: version, 3: Note{ 1: fixed32, 2: text, 5: run }, 4: fixed64 } }

    The unrelated fields (1, the version, the fixed-width ones, the attribute run) are there so a
    decoder must skip them correctly to reach 2 → 3 → 2."""
    run = _int(1, len(text)) + _len(2, b"\x00\x01")  # an attribute run: length and opaque bytes
    note = _fixed32(1, 0xDEADBEEF) + _len(2, text.encode("utf-8")) + _len(5, run)
    document = _int(2, 1) + _len(3, note) + _fixed64(4, 42)
    root = _int(1, 0) + _len(2, document)
    return gzip.compress(root, mtime=0)


# -- the fixture: synthetic, nobody in it exists ------------------------------------------

T0 = 790_000_000  # 2026-01-13T12:26:40Z
NOTES_FOLDER, BOAT_FOLDER = 100, 101
FOLDER_A, FOLDER_B = "F0000000-0000-4000-8000-00000000000A", "F0000000-0000-4000-8000-00000000000B"
NORMAL, TITLED, LOCKED, DELETED, SNIPPET, NO_DATE = 1, 2, 3, 4, 5, 6
IDS = {
    NORMAL: "A1B2C3D4-0000-4000-8000-000000000001",
    TITLED: "A1B2C3D4-0000-4000-8000-000000000002",
    LOCKED: "A1B2C3D4-0000-4000-8000-000000000003",
    DELETED: "A1B2C3D4-0000-4000-8000-000000000004",
    SNIPPET: "A1B2C3D4-0000-4000-8000-000000000005",
    NO_DATE: "A1B2C3D4-0000-4000-8000-000000000006",
}

# (Z_PK, ZMARKEDFORDELETION, ZISPASSWORDPROTECTED, ZFOLDER, ZCREATIONDATE3, ZMODIFICATIONDATE1,
#  ZIDENTIFIER, ZTITLE1, ZTITLE2, ZSNIPPET)
OBJECTS = [
    (NOTES_FOLDER, 0, 0, None, T0 - 100, T0 - 100, FOLDER_A, None, "Notes", None),
    (BOAT_FOLDER, 0, 0, None, T0 - 50, T0 - 50, FOLDER_B, None, "Boat", None),
    (NORMAL, 0, 0, NOTES_FOLDER, T0, T0 + 3600.5, IDS[NORMAL], "Grocery list", None, "Milk"),
    (TITLED, 0, 0, BOAT_FOLDER, T0 + 10, T0 + 20, IDS[TITLED], "Tromsø move", None, "Boxes: 14."),
    (LOCKED, 0, 1, NOTES_FOLDER, T0 + 30, T0 + 40, IDS[LOCKED], "Passwords", None, None),
    (DELETED, 1, 0, NOTES_FOLDER, T0 + 50, T0 + 60, IDS[DELETED], "Old list", None, "Sold the"),
    (SNIPPET, 0, 0, 999, T0 + 70, T0 + 80, IDS[SNIPPET], "Broken blob", None, "Only the snippet survived"),
    (NO_DATE, 0, 0, NOTES_FOLDER, None, T0 + 100, IDS[NO_DATE], "Undated", None, "Nothing"),
]
# (Z_PK, ZNOTE, ZDATA) — the folders have no note data
DATA = [
    (10, NORMAL, note_archive("Milk\nEggs\nBread")),
    (11, TITLED, note_archive("Tromsø move\nBoxes: 14.\nVan booked for the 20th.")),
    (12, LOCKED, b"\x00\x01\x02 encrypted, opaque"),
    (13, DELETED, note_archive("Sold the dinghy")),
    (14, SNIPPET, b"not gzip at all"),
    (15, NO_DATE, note_archive("Nothing to see")),
]


def _store(tmp_path: Path, name: str = "NoteStore.sqlite") -> Path:
    p = tmp_path / name
    con = sqlite3.connect(p)
    try:
        con.executescript(DDL)
        con.executemany("INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (?,1,1,?,?,?,?,?,?,?,?,?)", OBJECTS)
        con.executemany("INSERT INTO ZICNOTEDATA VALUES (?,1,1,?,?)", DATA)
        con.commit()
    finally:
        con.close()
    return p


def _by_pk(lines: list[dict]) -> dict[int, dict]:
    return {line["payload"]["extra"]["pk"]: line for line in lines}


# -- registry ---------------------------------------------------------------


def test_registry_lists_ios_notes():
    assert "ios-notes" in [a.NAME for a in adapters.all_adapters()]


def test_registry_find_returns_ios_notes_for_a_note_store(tmp_path):
    found = adapters.find(_store(tmp_path))
    assert found is not None and found.NAME == "ios-notes"


def test_registry_find_by_content_not_by_name(tmp_path):
    """A Finder/iTunes backup stores the file under its hashed name, without an extension."""
    found = adapters.find(_store(tmp_path, "4f98687d8ab0d6d1a371110e6b7300f6e465bef2"))
    assert found is not None and found.NAME == "ios-notes"


# -- sniff ------------------------------------------------------------------


def test_sniff_accepts_note_store(tmp_path):
    assert ios_notes.sniff(_store(tmp_path)) is True


def test_sniff_rejects_dawarich_and_takeout_exports():
    assert ios_notes.sniff(DAWARICH) is False
    assert ios_notes.sniff(TAKEOUT) is False


def test_other_adapters_reject_the_note_store(tmp_path):
    p = _store(tmp_path)
    assert dawarich.sniff(p) is False and location.sniff(p) is False
    assert ios_contacts.sniff(p) is False and whatsapp.sniff(p) is False


@pytest.mark.parametrize(
    "ddl",
    [
        "CREATE TABLE lines (seq INTEGER, hash TEXT);",  # the logbook's own index
        "CREATE TABLE ABPerson (ROWID INTEGER PRIMARY KEY); CREATE TABLE ABMultiValue (UID INTEGER);",
        "CREATE TABLE ZWACHATSESSION (Z_PK INTEGER); CREATE TABLE ZWAMESSAGE (Z_PK INTEGER);",
        "CREATE TABLE ZICCLOUDSYNCINGOBJECT (Z_PK INTEGER PRIMARY KEY);",  # half of it
        "CREATE TABLE ZICNOTEDATA (Z_PK INTEGER PRIMARY KEY, ZDATA BLOB);",
    ],
)
def test_sniff_rejects_other_sqlite_files(tmp_path, ddl):
    p = tmp_path / "other.sqlite"
    con = sqlite3.connect(p)
    try:
        con.executescript(ddl)
    finally:
        con.close()
    assert ios_notes.sniff(p) is False


@pytest.mark.parametrize("content", ["", "just words\n", "SQLite format 3\0 but not really a database"])
def test_sniff_rejects_non_sqlite_files(tmp_path, content):
    p = tmp_path / "NoteStore.sqlite"
    p.write_text(content, encoding="utf-8")
    assert ios_notes.sniff(p) is False


def test_sniff_rejects_directory_and_missing_file(tmp_path):
    assert ios_notes.sniff(tmp_path) is False
    assert ios_notes.sniff(tmp_path / "nope.sqlite") is False


def test_sniff_and_run_never_touch_the_source(tmp_path):
    p = _store(tmp_path)
    before = p.read_bytes()
    assert ios_notes.sniff(p) is True
    list(ios_notes.run(p))
    assert p.read_bytes() == before
    assert sorted(q.name for q in tmp_path.iterdir()) == ["NoteStore.sqlite"]  # no -journal, -wal, -shm


# -- run: envelope ------------------------------------------------------------


def test_run_yields_note_lines_at_the_creation_time(tmp_path):
    lines = list(ios_notes.run(_store(tmp_path)))
    assert len(lines) == 4  # normal, titled, deleted, snippet; locked and undated are skipped
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["end"] is None and line["tz"] is None
        assert line["source"] == "ios-notes" and line["kind"] == "note" and line["tier"] == 2
        assert line["payload"]["schema"] == "note/v1"
    assert _by_pk(lines)[NORMAL]["at"] == datetime.fromtimestamp(APPLE_EPOCH + T0, UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    assert _by_pk(lines)[NORMAL]["at"] == "2026-01-13T12:26:40Z"


def test_run_streams_in_row_order(tmp_path):
    assert list(_by_pk(list(ios_notes.run(_store(tmp_path))))) == [NORMAL, TITLED, DELETED, SNIPPET]


def test_run_honours_since(tmp_path):
    lines = list(ios_notes.run(_store(tmp_path), since="2026-01-13T12:27:30Z"))  # T0 + 50
    assert list(_by_pk(lines)) == [DELETED, SNIPPET]


# -- run: body, title, folder, ids --------------------------------------------------


def test_run_body_is_the_string_at_field_path_2_3_2(tmp_path):
    p = _by_pk(list(ios_notes.run(_store(tmp_path))))[NORMAL]["payload"]
    assert p["text"] == "Milk\nEggs\nBread"
    assert p["title"] == "Grocery list"
    assert p["folder"] == "Notes"
    assert "deleted" not in p["extra"] and "body_from_snippet" not in p["extra"]


def test_run_raw_id_is_identifier_at_modification_time(tmp_path):
    p = _by_pk(list(ios_notes.run(_store(tmp_path))))[NORMAL]["payload"]
    assert p["modified_at"] == "2026-01-13T13:26:40Z"  # T0 + 3600.5, whole seconds
    assert p["raw_id"] == f"{IDS[NORMAL]}@2026-01-13T13:26:40Z"


def test_run_strips_a_first_line_that_repeats_the_title(tmp_path):
    p = _by_pk(list(ios_notes.run(_store(tmp_path))))[TITLED]["payload"]
    assert p["title"] == "Tromsø move"
    assert p["text"] == "Boxes: 14.\nVan booked for the 20th."
    assert p["folder"] == "Boat"


def test_run_password_protected_note_is_skipped_and_counted(tmp_path):
    counts: dict[str, int] = {}
    lines = _by_pk(list(ios_notes.run(_store(tmp_path), counts=counts)))
    assert LOCKED not in lines
    assert counts["skipped_password_protected"] == 1


def test_run_deleted_note_is_a_line_flagged_and_counted(tmp_path):
    counts: dict[str, int] = {}
    p = _by_pk(list(ios_notes.run(_store(tmp_path), counts=counts)))[DELETED]["payload"]
    assert p["text"] == "Sold the dinghy" and p["extra"]["deleted"] is True
    assert counts["deleted"] == 1


def test_run_undecodable_data_falls_back_to_the_snippet(tmp_path):
    counts: dict[str, int] = {}
    p = _by_pk(list(ios_notes.run(_store(tmp_path), counts=counts)))[SNIPPET]["payload"]
    assert p["text"] == "Only the snippet survived"
    assert p["extra"]["body_from_snippet"] is True
    assert "folder" not in p  # ZFOLDER points at a row that is not there
    assert counts["body_from_snippet"] == 1


def test_run_null_creation_date_is_skipped_and_counted(tmp_path):
    counts: dict[str, int] = {}
    lines = _by_pk(list(ios_notes.run(_store(tmp_path), counts=counts)))
    assert NO_DATE not in lines
    assert counts == {
        "skipped_password_protected": 1,
        "deleted": 1,
        "body_from_snippet": 1,
        "skipped_bad_date": 1,
    }


def _one_note(tmp_path: Path, data: bytes | None, **columns: object) -> tuple[list[dict], dict[str, int]]:
    row = {
        "ZMARKEDFORDELETION": 0,
        "ZISPASSWORDPROTECTED": 0,
        "ZFOLDER": None,
        "ZCREATIONDATE3": T0,
        "ZMODIFICATIONDATE1": T0 + 1,
        "ZIDENTIFIER": IDS[NORMAL],
        "ZTITLE1": "Grocery list",
        "ZTITLE2": None,
        "ZSNIPPET": None,
        **columns,
    }
    p = tmp_path / "NoteStore.sqlite"
    con = sqlite3.connect(p)
    try:
        con.executescript(DDL)
        con.execute(
            "INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (1,1,1,?,?,?,?,?,?,?,?,?)",
            (
                row["ZMARKEDFORDELETION"],
                row["ZISPASSWORDPROTECTED"],
                row["ZFOLDER"],
                row["ZCREATIONDATE3"],
                row["ZMODIFICATIONDATE1"],
                row["ZIDENTIFIER"],
                row["ZTITLE1"],
                row["ZTITLE2"],
                row["ZSNIPPET"],
            ),
        )
        con.execute("INSERT INTO ZICNOTEDATA VALUES (1,1,1,1,?)", (data,))
        con.commit()
    finally:
        con.close()
    counts: dict[str, int] = {}
    return list(ios_notes.run(p, counts=counts)), counts


def test_run_creation_date_before_2010_is_skipped(tmp_path):
    lines, counts = _one_note(tmp_path, note_archive("old"), ZCREATIONDATE3=299_999_999)
    assert lines == [] and counts == {"skipped_bad_date": 1}


def test_run_note_with_no_text_anywhere_is_skipped(tmp_path):
    lines, counts = _one_note(tmp_path, b"garbage", ZSNIPPET="   ")
    assert lines == [] and counts == {"body_from_snippet": 1, "skipped_no_text": 1}


def test_run_decoded_but_empty_body_is_skipped(tmp_path):
    lines, counts = _one_note(tmp_path, note_archive(""), ZSNIPPET=None)
    assert lines == [] and counts == {"skipped_no_text": 1}


def test_run_body_that_is_only_the_title_keeps_it_as_text(tmp_path):
    (line,), _ = _one_note(tmp_path, note_archive("Grocery list"))
    assert line["payload"]["text"] == "Grocery list"
    assert "title" not in line["payload"]  # not distinct from the body (RFC 0010)


def test_run_missing_modification_date_uses_the_creation_time_in_raw_id(tmp_path):
    (line,), _ = _one_note(tmp_path, note_archive("Milk"), ZMODIFICATIONDATE1=None)
    assert "modified_at" not in line["payload"]
    assert line["payload"]["raw_id"] == f"{IDS[NORMAL]}@{line['at']}"


def test_run_missing_identifier_is_keyed_by_row_id_and_counted(tmp_path):
    (line,), counts = _one_note(tmp_path, note_archive("Milk"), ZIDENTIFIER=None)
    assert line["payload"]["raw_id"] == f"pk1@{line['payload']['modified_at']}"
    assert counts == {"no_identifier": 1}


def test_run_null_data_falls_back_to_the_snippet(tmp_path):
    (line,), counts = _one_note(tmp_path, None, ZSNIPPET="from the snippet")
    assert line["payload"]["text"] == "from the snippet"
    assert counts == {"body_from_snippet": 1}


def test_run_gzip_that_is_not_the_archive_falls_back_to_the_snippet(tmp_path):
    (line,), counts = _one_note(tmp_path, gzip.compress(b"\xff\xff\xff"), ZSNIPPET="snippet")
    assert line["payload"]["text"] == "snippet"
    assert counts == {"body_from_snippet": 1}


def test_run_field_2_that_is_not_a_message_falls_back_to_the_snippet(tmp_path):
    root = _int(2, 7)  # field 2 as a varint: no Document to walk into
    (line,), counts = _one_note(tmp_path, gzip.compress(root), ZSNIPPET="snippet")
    assert line["payload"]["text"] == "snippet"
    assert counts == {"body_from_snippet": 1}


# -- through the log: append, dedupe on re-run, CLI -----------------------------------


def test_run_lines_append_and_re_running_appends_nothing(tmp_path):
    p = _store(tmp_path)
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    assert lb.append_many(ios_notes.run(p)) == 4
    assert lb.append_many(ios_notes.run(p)) == 0
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 4
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
        assert line["tz"] == "Europe/Oslo"


def test_run_an_edited_note_is_a_new_line(tmp_path):
    """RFC 0010 rule 2: the dedupe key carries the modification time, so an edit appends."""
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    lines, _ = _one_note(tmp_path, note_archive("Milk"))
    assert lb.append_many(lines) == 1
    (tmp_path / "NoteStore.sqlite").unlink()
    lines, _ = _one_note(tmp_path, note_archive("Milk\nEggs"), ZMODIFICATIONDATE1=T0 + 2)
    assert lb.append_many(lines) == 1


def _cli(tmp_path):
    env = {**os.environ, "LOGBOOK_HOME": str(tmp_path / "lb"), "PYTHONPATH": str(ROOT)}

    def run(*a):
        return subprocess.run(
            [sys.executable, "-m", "logbook.cli", *a],
            env=env,
            capture_output=True,
            encoding="utf-8",
            check=True,
        )

    return run


def test_cli_add_reports_lines_skips_and_notes(tmp_path):
    run = _cli(tmp_path)
    run("init", str(tmp_path / "lb"), "--timezone", "Europe/Oslo")
    p = _store(tmp_path)
    out = run("add", str(p)).stdout
    assert "added 4 lines from ios-notes" in out
    assert "skipped 1 password protected, 1 with an unusable date" in out
    assert "also 1 marked for deletion, 1 with the body taken from the snippet" in out
    assert "added 0 lines from ios-notes" in run("add", str(p)).stdout
    assert "valid — 4 lines" in run("verify").stdout


# -- property: every emitted line is a valid note/v1 observation -------------------------


def _rfc_rules(line: dict) -> None:
    assert set(line) == ENVELOPE
    assert line["kind"] == "note" and line["tier"] == 2 and line["end"] is None
    assert line["source"] == "ios-notes" and line["source"] != "manual"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", line["at"])
    assert line["at"] >= "2010-07-07T"  # ZCREATIONDATE3 >= 300000000
    p = line["payload"]
    assert {"schema", "text", "raw_id", "extra"} <= set(p)
    assert set(p) <= {"schema", "text", "title", "raw_id", "modified_at", "folder", "extra"}
    assert p["schema"] == "note/v1"
    assert isinstance(p["text"], str) and p["text"].strip()
    if "title" in p:
        assert isinstance(p["title"], str) and p["title"].strip() and p["title"] != p["text"]
    if "modified_at" in p:
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", p["modified_at"])
        assert p["raw_id"].endswith("@" + p["modified_at"])
    else:
        assert p["raw_id"].endswith("@" + line["at"])
    if "folder" in p:
        assert isinstance(p["folder"], str) and p["folder"].strip()
    assert isinstance(p["extra"]["pk"], int)
    assert set(p["extra"]) <= {"pk", "deleted", "body_from_snippet"}
    json.dumps(line, allow_nan=False)


_chars = st.characters(exclude_categories=["Cs"])  # anything UTF-8 can carry
_text = st.one_of(st.none(), st.text(alphabet=_chars, max_size=24))
_date = st.one_of(
    st.none(),
    st.integers(-(2**40), 2**40),
    st.floats(allow_nan=False, allow_infinity=False, min_value=-1e12, max_value=1e12),
)
_flag = st.one_of(st.none(), st.integers(0, 1))
_data = st.one_of(
    st.none(),
    st.text(alphabet=_chars, max_size=40).map(note_archive),
    st.binary(max_size=40),
    st.binary(max_size=40).map(lambda b: gzip.compress(b)),
)
_folder = st.one_of(st.none(), st.integers(0, 8))
_object = st.tuples(_flag, _flag, _folder, _date, _date, _text, _text, _text, _text)
_store_rows = st.lists(st.tuples(_object, st.one_of(st.none(), _data)), max_size=6)


@settings(max_examples=40, deadline=None)
@given(_store_rows)
def test_any_note_store_yields_only_valid_lines(tmp_path_factory, rows):
    p = tmp_path_factory.mktemp("notes") / "NoteStore.sqlite"
    con = sqlite3.connect(p)
    notes = 0
    try:
        con.executescript(DDL)
        for pk, (obj, data) in enumerate(rows, start=1):
            obj = list(obj)
            if obj[5] is not None:
                obj[5] = f"{obj[5]}#{pk}"  # ZIDENTIFIER is unique in a real store
            con.execute("INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (?,1,1,?,?,?,?,?,?,?,?,?)", (pk, *obj))
            if pk % 3:  # every third row is a folder: no note data
                notes += 1
                con.execute("INSERT INTO ZICNOTEDATA VALUES (?,1,1,?,?)", (pk, pk, data))
        con.commit()
    finally:
        con.close()
    counts: dict[str, int] = {}
    lines = list(ios_notes.run(p, counts=counts))
    for line in lines:
        _rfc_rules(line)
    raw_ids = [line["payload"]["raw_id"] for line in lines]
    assert len(raw_ids) == len(set(raw_ids))
    skipped = sum(n for key, n in counts.items() if key.startswith("skipped_"))
    assert len(lines) + skipped == notes
    lb = Logbook.init(tmp_path_factory.mktemp("lb"), "UTC")
    assert lb.append_many(lines) == len(lines)
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
