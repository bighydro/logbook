"""`logbook stats [--json]`: a one-screen picture of what a record holds, counted through the index
in one pass per table, never printing what any line says."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from logbook import cli, store
from logbook.store import Logbook

# Every string here is synthetic; the person lives in Oslo and does not exist.
PERSON_A = "019cadd3-6bc0-7dcd-9133-043f5aabf2a9"
PERSON_B = "019cadd3-6bc0-7dcd-9133-043f5aabf2aa"
NAME_A, NAME_B = "Ola Nordmann", "Kari Nordmann"
PHONE_A, PHONE_B = "+4790000001", "+4790000002"
EMAIL_A = "ola@example.org"
NOTE_TEXT = "lunch by the lake with the boat club"
MESSAGE_TEXT = "mooring photos sent"
EVENT_TITLE = "Boat survey"
PRIVATE = (NAME_A, NAME_B, PHONE_A, PHONE_B, EMAIL_A, NOTE_TEXT, MESSAGE_TEXT, EVENT_TITLE)
WORDS = ("Ola", "Kari", "Nordmann", "90000001", "example.org", "lake", "boat", "mooring", "photos", "survey")
SHA_PRESENT = "a" * 64
SHA_MISSING = "b" * 64


def _location(at: str, source: str = "dawarich") -> dict[str, Any]:
    payload = {"schema": "location/v1", "lat": 59.91, "lon": 10.75, "raw_id": f"{source}:{at}"}
    return {"at": at, "source": source, "kind": "location", "tier": 1, "payload": payload}


def _resolution(kind: str, value: str, label: str, entity: str) -> dict[str, Any]:
    return {
        "at": "2024-02-01T09:00:00Z",
        "source": "ios-contacts",
        "kind": "resolution",
        "tier": 2,
        "payload": {
            "schema": "resolution/v1",
            "ref": {"kind": kind, "value": value},
            "entity": {"type": "person", "id": entity, "registry": "logbook"},
            "label": label,
            "method": "exact",
        },
    }


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """Oslo. 2024: a note, three resolutions (two people), a location, a message with a media file
    that exists. 2025: four locations from two sources, an event. 2026: a note that gets retracted,
    a message with a media file that is missing. 14 lines, one retraction = 15."""
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(
        [
            {  # seq 1
                "at": "2024-01-15T11:00:00Z",
                "source": "manual",
                "kind": "note",
                "tier": 2,
                "payload": {"schema": "note/v1", "text": NOTE_TEXT},
            },
            _resolution("phone", PHONE_A, NAME_A, PERSON_A),  # seq 2
            _resolution("email", EMAIL_A, NAME_A, PERSON_A),  # seq 3: same person, minted once
            _resolution("phone", PHONE_B, NAME_B, PERSON_B),  # seq 4
            _location("2024-06-01T10:00:00Z"),  # seq 5
            {  # seq 6: a message whose media is in the store
                "at": "2024-12-31T23:30:00Z",  # 00:30 local on 2025-01-01: the local day counts
                "source": "whatsapp",
                "kind": "message",
                "tier": 2,
                "payload": {
                    "schema": "message/v1",
                    "raw_id": "wa:1",
                    "chat": {"id": "4790000001@s.whatsapp.net", "type": "direct", "name": NAME_A},
                    "from_me": False,
                    "sender": {"kind": "phone", "value": PHONE_A, "name": NAME_A},
                    "text": MESSAGE_TEXT,
                    "media_kind": "image",
                    "extra": {"media": {"sha256": SHA_PRESENT, "bytes": 3, "local_path": "Message/x.jpg"}},
                },
            },
            _location("2025-03-01T10:00:00Z"),  # seq 7
            _location("2025-03-01T10:05:00Z"),  # seq 8
            _location("2025-03-01T10:10:00Z", source="owntracks"),  # seq 9
            _location("2025-07-01T10:00:00Z"),  # seq 10
            {  # seq 11
                "at": "2025-05-05T08:30:00Z",
                "end": "2025-05-05T09:15:00Z",
                "source": "ios-calendar",
                "kind": "event",
                "tier": 1,
                "payload": {
                    "schema": "event/v1",
                    "raw_id": "uid@2025-05-01T00:00:00Z",
                    "title": EVENT_TITLE,
                    "all_day": False,
                    "organizer": {"kind": "email", "value": EMAIL_A},
                },
            },
            {  # seq 12: retracted below
                "at": "2026-02-02T12:00:00Z",
                "source": "manual",
                "kind": "note",
                "tier": 2,
                "payload": {"schema": "note/v1", "text": NOTE_TEXT},
            },
            {  # seq 13: a §1.1 reference whose file is not in the store
                "at": "2026-02-03T12:00:00Z",
                "source": "imessage",
                "kind": "message",
                "tier": 2,
                "payload": {
                    "schema": "message/v1",
                    "raw_id": "im:1",
                    "chat": {"id": "chat1", "type": "direct"},
                    "from_me": True,
                    "text": MESSAGE_TEXT,
                    "media": {
                        "sha256": SHA_MISSING,
                        "path": f"attachments/{SHA_MISSING}",
                        "bytes": 3,
                        "media_type": "image/jpeg",
                    },
                },
            },
            {  # seq 14: the present file, referenced a second time
                "at": "2026-02-04T12:00:00Z",
                "source": "whatsapp",
                "kind": "message",
                "tier": 2,
                "payload": {
                    "schema": "message/v1",
                    "raw_id": "wa:2",
                    "chat": {"id": "1234@g.us", "type": "group"},
                    "from_me": True,
                    "media_kind": "image",
                    "extra": {"media": {"sha256": SHA_PRESENT, "bytes": 3, "local_path": "Message/y.jpg"}},
                },
            },
        ]
    )
    lb.retract(12, "wrong day", at="2026-02-05T00:00:00Z")  # seq 15
    (lb.root / "attachments").mkdir()
    (lb.root / "attachments" / SHA_PRESENT).write_bytes(b"abc")
    return lb


def _stats(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(["stats", *args])
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_stats(capsys, "--json"))
    return data


# -- the numbers --------------------------------------------------------------------------------


def test_stats_json_holds_every_number(lb: Logbook, capsys):
    s = _json(capsys)
    assert s["format"] == "logbook/0.2" and s["head"] == lb.meta["head"]
    assert s["lines"] == 15
    assert s["first"] == "2024-01-15T11:00:00Z" and s["last"] == "2026-02-05T00:00:00Z"
    assert s["kinds"] == [
        {"kind": "location", "lines": 5, "first": "2024-06-01", "last": "2025-07-01", "sources": 2},
        {"kind": "message", "lines": 3, "first": "2025-01-01", "last": "2026-02-04", "sources": 2},
        {"kind": "resolution", "lines": 3, "first": "2024-02-01", "last": "2024-02-01", "sources": 1},
        {"kind": "note", "lines": 2, "first": "2024-01-15", "last": "2026-02-02", "sources": 1},
        {"kind": "event", "lines": 1, "first": "2025-05-05", "last": "2025-05-05", "sources": 1},
        {"kind": "retraction", "lines": 1, "first": "2026-02-05", "last": "2026-02-05", "sources": 1},
    ]
    assert s["sources"] == [
        {"source": "dawarich", "lines": 4},
        {"source": "ios-contacts", "lines": 3},  # ties by name
        {"source": "manual", "lines": 3},
        {"source": "whatsapp", "lines": 2},
        {"source": "imessage", "lines": 1},
        {"source": "ios-calendar", "lines": 1},
        {"source": "owntracks", "lines": 1},
    ]
    assert s["years"] == [
        {"year": "2024", "lines": 5},
        {"year": "2025", "lines": 6},
        {"year": "2026", "lines": 4},
    ]
    assert s["retractions"] == {"lines": 1, "hidden": 1}
    assert s["resolutions"] == {"lines": 3, "entities": 2}
    assert s["attachments"] == {"referenced": 2, "lines": 3, "present": 1}
    assert isinstance(s["took_seconds"], float) and s["took_seconds"] >= 0
    assert set(s) == {
        "format",
        "head",
        "lines",
        "first",
        "last",
        "kinds",
        "sources",
        "years",
        "retractions",
        "resolutions",
        "attachments",
        "took_seconds",
    }


def test_stats_prints_the_same_numbers_on_one_screen(lb: Logbook, capsys):
    out = _stats(capsys)
    lines = out.splitlines()
    assert lines[0] == f"logbook/0.2  head {lb.meta['head']}"
    assert lines[1] == "15 lines  first 2024-01-15T11:00:00Z  last 2026-02-05T00:00:00Z"
    assert "  location        5   2024-06-01  2025-07-01   2 sources" in lines
    assert "  event           1   2025-05-05  2025-05-05   1 source" in lines
    assert "  dawarich          4" in lines  # the name column is as wide as the longest source
    assert "  owntracks         1" in lines
    assert "  2024      5  " + "█" * 83 in lines  # 5 of the busiest year's 6: 83%
    assert "  2025      6  " + "█" * 100 in lines
    assert "  2026      4  " + "█" * 67 in lines
    assert "1 retraction hiding 1 line" in out
    assert "3 resolution lines minting 2 entities" in out
    assert "2 attachments referenced by 3 lines, 1 present under attachments/" in out
    assert re.fullmatch(r"took \d+\.\d{3}s", lines[-1]), lines[-1]
    assert len(lines) <= 30


def test_stats_bar_is_one_character_per_percent_of_the_busiest_year(tmp_path: Path, monkeypatch, capsys):
    lb = Logbook.init(tmp_path / "lb", "UTC")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(_location(f"2026-01-01T{i // 60:02d}:{i % 60:02d}:00Z") for i in range(1_000))
    lb.append(**_location("2025-01-01T00:00:00Z"))
    bars = [line for line in _stats(capsys).splitlines() if "█" in line]
    assert bars == ["  2025      1  █", "  2026  1,000  " + "█" * 100]  # a year with any line shows


# -- privacy: numbers, kinds, sources and dates only ------------------------------------------------


@pytest.mark.parametrize("args", [(), ("--json",)])
def test_stats_never_prints_what_a_line_says(lb: Logbook, capsys, args: tuple[str, ...]):
    out = _stats(capsys, *args)
    for secret in (*PRIVATE, *WORDS, PERSON_A, PERSON_B):
        assert secret not in out, secret
    assert SHA_PRESENT not in out and SHA_MISSING not in out


# -- the index: one pass per table, no read of the files -------------------------------------------


def test_stats_reads_the_index_and_never_the_files(lb: Logbook, monkeypatch, capsys):
    with lb.index():
        pass
    touched: list[str] = []
    monkeypatch.setattr(Logbook, "files", lambda self: touched.append("files") or [])
    monkeypatch.setattr(store, "read_line_at", lambda fh, offset: touched.append("read") or {})
    statements: list[str] = []
    original_connect = sqlite3.connect

    def tracing(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        db = original_connect(*args, **kwargs)
        db.set_trace_callback(statements.append)
        return db

    monkeypatch.setattr(sqlite3, "connect", tracing)
    s = _json(capsys)
    assert s["lines"] == 15 and touched == []
    selects = [x for x in statements if x.lstrip().upper().startswith("SELECT") and "FROM lines" in x]
    assert len(selects) <= 8  # header, kinds, sources, years, retractions, resolutions, attachments


def test_stats_writes_nothing(lb: Logbook, capsys):
    before = lb.meta
    _stats(capsys)
    _stats(capsys, "--json")
    assert lb.meta == before


# -- an empty record --------------------------------------------------------------------------------


def test_stats_on_an_empty_record(tmp_path: Path, monkeypatch, capsys):
    lb = Logbook.init(tmp_path / "lb", "UTC")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    s = _json(capsys)
    assert s["lines"] == 0 and s["first"] is None and s["last"] is None
    assert s["kinds"] == [] and s["sources"] == [] and s["years"] == []
    assert s["retractions"] == {"lines": 0, "hidden": 0}
    assert s["resolutions"] == {"lines": 0, "entities": 0}
    assert s["attachments"] == {"referenced": 0, "lines": 0, "present": 0}
    out = _stats(capsys)
    assert out.splitlines()[1] == "0 lines"
    assert out.splitlines()[-1].startswith("took ")


# -- an index built before schema 2 is rebuilt once, by the first reader ---------------------------


def test_stats_rebuilds_an_index_built_by_an_earlier_schema(lb: Logbook, capsys):
    with lb.index():
        pass
    with closing(sqlite3.connect(lb.root / "index.sqlite")) as db:
        db.execute("UPDATE meta SET value = '1' WHERE key = 'schema'")
        db.execute("ALTER TABLE lines DROP COLUMN media")
        db.commit()
    assert _json(capsys)["attachments"] == {"referenced": 2, "lines": 3, "present": 1}
    with closing(sqlite3.connect(lb.root / "index.sqlite")) as db:
        assert list(db.execute("SELECT value FROM meta WHERE key = 'schema'")) == [("2",)]
