"""Voice Memos' CloudRecordings.db → voice-memo/v1 (RFC 0023): one line per recording, the audio
hashed from the Recordings/ folder beside the store and put in the §1.1 store only with
`--attachments`; recordings whose file is gone are lines without media."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import cli
from logbook.contrib import adapters
from logbook.contrib.adapters import voice_memos
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
RFC = ROOT / "rfcs" / "0023-voice-memo-v1.md"
TZ = "Europe/Oslo"
APPLE_EPOCH = 978_307_200

DDL = """
CREATE TABLE ZFOLDER (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZCOUNTOFRECORDINGS INTEGER, ZRANK INTEGER,
    ZENCRYPTEDNAME VARCHAR, ZUUID VARCHAR);
CREATE TABLE ZCLOUDRECORDING (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZFLAGS INTEGER, ZSHAREDFLAGS INTEGER,
    ZFOLDER INTEGER, ZDATE TIMESTAMP, ZDURATION FLOAT, ZEVICTIONDATE TIMESTAMP, ZLOCALDURATION FLOAT,
    ZCUSTOMLABEL VARCHAR, ZCUSTOMLABELFORSORTING VARCHAR, ZENCRYPTEDTITLE VARCHAR, ZPATH VARCHAR,
    ZUNIQUEID VARCHAR, ZAUDIODIGEST BLOB, ZPLAYBACKPOSITION FLOAT);
"""
M4A = b"\x00\x00\x00\x1cftypM4A \x00\x00\x00\x00M4A isommp42" + b"\x01" * 200  # an ISO base media header
QTA = b"\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00qt  " + b"\x02" * 300  # a QuickTime container
FILES = {
    "20260302 211407.m4a": M4A,
    "20260305 073000.qta": QTA,
    "20260306 220000-0A1B2C3D.m4a": M4A + b"\x03",
}


def _apple(stamp: str) -> float:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp() - APPLE_EPOCH


ROWS: list[dict[str, Any]] = [
    {
        "pk": 1, "uid": "7A1B2C3D-0000-4000-8000-000000000001", "date": "2026-03-02T20:14:07Z",
        "duration": 102.4, "label": "Idea for the talk",
        "path": "20260302 211407.m4a", "folder": None, "flags": 4,
    },
    {
        "pk": 2, "uid": "7A1B2C3D-0000-4000-8000-000000000002", "date": "2026-03-05T06:30:00Z",
        "duration": 3.5, "label": "Storgata",
        "path": "20260305 073000.qta", "folder": 1, "flags": 4100,
    },
    {  # a file the store no longer has
        "pk": 3, "uid": "7A1B2C3D-0000-4000-8000-000000000003", "date": "2026-03-06T21:00:00Z",
        "duration": 60, "label": "New Recording 12",
        "path": "20260306 220000.m4a", "folder": None, "flags": 4,
    },
    {  # the audio of a trimmed recording keeps a suffix in its name
        "pk": 4, "uid": "7A1B2C3D-0000-4000-8000-000000000004", "date": "2026-03-06T21:30:00Z",
        "duration": None, "label": "  Rehearsal  ",
        "path": "20260306 220000-0A1B2C3D.m4a", "folder": None, "flags": 4,
    },
    {  # no date: nowhere to put it
        "pk": 5, "uid": "7A1B2C3D-0000-4000-8000-000000000005", "date": None, "duration": 9,
        "label": "Undated", "path": "20260307 100000.m4a", "folder": None, "flags": 4,
    },
]  # fmt: skip
LINES = 4
STORED = 3  # files present: two from ROWS 1-2, one from ROW 4


def _store(folder: Path, rows: list[dict[str, Any]] = ROWS, *, layout: str = "backup") -> Path:
    """A synthetic CloudRecordings.db with the audio beside it: `layout="backup"` puts the files under
    `Recordings/` next to the store as `import-backup` does; `"phone"` puts them beside the store as the
    phone keeps them. Nobody in it exists."""
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / "CloudRecordings.db"
    with closing(sqlite3.connect(p)) as con:
        con.executescript(DDL)
        con.execute(
            "INSERT INTO ZFOLDER VALUES (1, 2, 1, 1, 0, 'c2VjcmV0', 'F0000000-0000-4000-8000-000000000001')"
        )
        for r in rows:
            con.execute(
                "INSERT INTO ZCLOUDRECORDING VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    r["pk"], 3, 1, r["flags"], 0, r["folder"], _apple(r["date"]) if r["date"] else None,
                    r["duration"], None, r["duration"], r["label"], r["label"].strip().lower(),
                    "ZW5jcnlwdGVk", r["path"], r["uid"], None, 0.0,
                ),
            )  # fmt: skip
        con.commit()
    media = folder / "Recordings" if layout == "backup" else folder
    media.mkdir(exist_ok=True)
    for name, data in FILES.items():
        (media / name).write_bytes(data)
    return p


def _lines(tmp_path: Path, **kw: Any) -> list[dict[str, Any]]:
    return list(voice_memos.run(_store(tmp_path / "vm"), **kw))


def _by_raw_id(lines: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {line["payload"]["raw_id"]: line for line in lines}


def _profile() -> dict[str, Any]:
    block = re.search(r"## JSON Schema\n\n```json\n(.*?)\n```", RFC.read_text(encoding="utf-8"), re.S)
    assert block is not None
    schema: dict[str, Any] = json.loads(block.group(1))
    return schema


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# -- registry and sniff ----------------------------------------------------------------------------


def test_registry_lists_voice_memos():
    assert voice_memos in adapters.file_adapters()
    assert adapters.named("voice-memos") is voice_memos


def test_sniff_takes_a_recordings_store_and_nothing_else(tmp_path):
    assert voice_memos.sniff(_store(tmp_path / "vm"))
    other = tmp_path / "other.sqlite"
    with closing(sqlite3.connect(other)) as con:
        con.execute("CREATE TABLE ZRECORDING (x)")
    assert not voice_memos.sniff(other)
    assert not voice_memos.sniff(tmp_path / "missing.db")


# -- the lines -------------------------------------------------------------------------------------


def test_every_line_is_a_voice_memo_line_with_the_rfc_payload(tmp_path):
    lines = _lines(tmp_path, timezone=TZ)
    assert len(lines) == LINES
    validator = Draft202012Validator(_profile())
    for line in lines:
        assert set(line) == {"at", "end", "tz", "source", "kind", "tier", "payload"}
        assert (line["source"], line["kind"], line["tier"], line["tz"]) == (
            "voice-memos",
            "voice-memo",
            2,
            TZ,
        )
        validator.validate(line["payload"])
    assert [line["at"] for line in lines] == sorted(line["at"] for line in lines)


def test_a_recording_is_a_span_with_its_title_duration_and_audio_by_digest(tmp_path):
    counts: dict[str, int] = {}
    line = _by_raw_id(_lines(tmp_path, counts=counts))["7A1B2C3D-0000-4000-8000-000000000001"]
    assert (line["at"], line["end"], line["tz"]) == ("2026-03-02T20:14:07Z", "2026-03-02T20:15:49Z", None)
    assert line["payload"] == {
        "schema": "voice-memo/v1",
        "raw_id": "7A1B2C3D-0000-4000-8000-000000000001",
        "title": "Idea for the talk",
        "duration_s": 102.4,
        "file_name": "20260302 211407.m4a",
        "media": {"sha256": _sha(M4A), "bytes": len(M4A), "media_type": "audio/mp4"},
        "extra": {"flags": 4},
    }
    assert counts["attachments_referenced"] == STORED and "attachments_stored" not in counts


def test_a_qta_composition_is_quicktime_and_a_folder_name_the_store_hides_is_not_copied(tmp_path):
    p = _by_raw_id(_lines(tmp_path))["7A1B2C3D-0000-4000-8000-000000000002"]["payload"]
    assert p["media"]["media_type"] == "video/quicktime" and p["media"]["sha256"] == _sha(QTA)
    assert "folder" not in p and p["title"] == "Storgata"


def test_a_recording_whose_file_is_gone_is_a_line_without_media_and_counted(tmp_path):
    counts: dict[str, int] = {}
    by = _by_raw_id(_lines(tmp_path, counts=counts))
    gone = by["7A1B2C3D-0000-4000-8000-000000000003"]
    assert "media" not in gone["payload"] and gone["payload"]["file_name"] == "20260306 220000.m4a"
    assert gone["end"] == "2026-03-06T21:01:00Z"
    assert counts["media_missing"] == 1
    trimmed = by["7A1B2C3D-0000-4000-8000-000000000004"]
    assert trimmed["end"] is None and "duration_s" not in trimmed["payload"]
    assert trimmed["payload"]["title"] == "Rehearsal" and trimmed["payload"]["media"]["sha256"] == _sha(
        M4A + b"\x03"
    )


def test_undated_rows_are_skipped_and_counted(tmp_path):
    counts: dict[str, int] = {}
    assert len(_lines(tmp_path, counts=counts)) == LINES and counts["skipped_no_date"] == 1


def test_the_audio_is_found_beside_the_store_too(tmp_path):
    store = _store(tmp_path / "phone", layout="phone")
    lines = list(voice_memos.run(store))
    assert sum("media" in line["payload"] for line in lines) == STORED


def test_with_attachments_the_bytes_go_through_the_store_callback_and_the_line_has_a_path(tmp_path):
    stored: list[Path] = []
    counts: dict[str, int] = {}
    store = _store(tmp_path / "vm")
    lines = list(voice_memos.run(store, counts=counts, attachments=True, store_file=stored.append))
    media = [line["payload"]["media"] for line in lines if "media" in line["payload"]]
    assert len(media) == STORED and all(m["path"] == f"attachments/{m['sha256']}" for m in media)
    assert sorted(p.name for p in stored) == sorted(FILES)
    assert counts["attachments_stored"] == STORED and "attachments_referenced" not in counts
    # without the flag the callback is never called, even when given
    stored.clear()
    list(voice_memos.run(store, store_file=stored.append))
    assert stored == []


def test_since_and_tier(tmp_path):
    lines = _lines(tmp_path, since="2026-03-06T00:00:00Z", tier=3)
    assert len(lines) == 2 and {line["tier"] for line in lines} == {3}


def test_the_store_and_the_audio_are_never_written(tmp_path):
    store = _store(tmp_path / "vm")
    before = {p: p.read_bytes() for p in store.parent.rglob("*") if p.is_file()}
    list(voice_memos.run(store, attachments=True, store_file=lambda p: None))
    assert {p: p.read_bytes() for p in store.parent.rglob("*") if p.is_file()} == before


# -- through the CLI --------------------------------------------------------------------------------


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook.init(root, TZ)


def test_add_stores_the_audio_only_with_attachments_and_show_prints_the_title(lb, tmp_path, capsys):
    store = _store(tmp_path / "vm")
    cli.main(["add", "voice-memos", str(store)])
    out = capsys.readouterr().out
    assert f"added {LINES} lines from voice-memos" in out and "1 with media missing" in out
    assert f"{STORED} attachments referenced, not stored" in out
    assert not (lb.root / "attachments").exists()
    cli.main(["add", "voice-memos", str(store), "--attachments"])
    assert "added 0 lines" in capsys.readouterr().out  # the same lines: nothing appended …
    assert len(list((lb.root / "attachments").iterdir())) == STORED  # … but the store now has the audio
    cli.main(["show", "stats"])
    assert f"{STORED} present under attachments/" in capsys.readouterr().out
    cli.main(["show", "2026-03-02"])
    out = capsys.readouterr().out
    assert "voice-memo" in out and "Idea for the talk" in out and "1:42" in out


def test_add_with_attachments_on_a_fresh_record_puts_every_file_in_the_store_once(lb, tmp_path, capsys):
    store = _store(tmp_path / "vm")
    cli.main(["add", "voice-memos", str(store), "--attachments"])
    out = capsys.readouterr().out
    assert f"{STORED} attachments stored" in out
    files = sorted(p.name for p in (lb.root / "attachments").iterdir())
    assert files == sorted({_sha(data) for data in FILES.values()})
    for name in files:
        assert _sha((lb.root / "attachments" / name).read_bytes()) == name
    cli.main(["show", "stats"])
    assert f"{STORED} present under attachments/" in capsys.readouterr().out
