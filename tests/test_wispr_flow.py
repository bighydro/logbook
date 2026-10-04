"""Wispr Flow's database.sqlite → transcript/v1 (RFC 0004): one line per dictation, the text as a
SPEC §1.1 attachment, tier 3. A synthetic Core Data store; the sentences are the Oslo persona's."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import cli
from logbook.contrib import adapters
from logbook.contrib.adapters import wispr_flow
from logbook.core import attachments
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
LINES = 4
APPLE = 978307200  # 2001-01-01T00:00:00Z as Unix seconds
T0 = 1789000000 - APPLE  # 2026-09-10T00:26:40Z in Apple's epoch

ROWS = [  # (ZID, start, end, status, origin, language, app, asr, llm, text)
    (
        "A1B2C3D4-0000-4000-8000-000000000001",
        T0,
        T0 + 17.2,
        "formatted",
        None,
        "de",
        "net.whatsapp.WhatsApp",
        "hallo ola kommst du heute abend",
        "Hallo Ola, kommst du heute Abend?",
        "Hallo Ola, kommst du heute Abend?",
    ),
    (
        "A1B2C3D4-0000-4000-8000-000000000002",
        T0 + 3600,
        T0 + 3606,
        "raw_transcript",
        "internal",
        "en",
        "com.apple.mobilenotes",
        "buy milk and call the marina",
        None,
        None,
    ),
    ("A1B2C3D4-0000-4000-8000-000000000003", T0 + 7200, T0 + 7210, None, None, None, None, None, None, None),
    (
        "A1B2C3D4-0000-4000-8000-000000000004",
        None,
        T0 + 9000,
        "formatted",
        None,
        "en",
        "com.example.chat",
        "no start",
        "No start.",
        "No start.",
    ),
    (
        "A1B2C3D4-0000-4000-8000-000000000005",
        T0 + 10800,
        T0 + 10700,
        "formatted",
        None,
        "en",
        "com.example.chat",
        "ends before it starts",
        "Ends before it starts.",
        "Ends before it starts.",
    ),
    (
        "A1B2C3D4-0000-4000-8000-000000000006",
        T0 + 14400,
        None,
        "formatted",
        None,
        "en",
        "com.example.mail",
        "two sentences here and there",
        "Two sentences. Here and there.",
        "Two sentences. Here and there.",
    ),
]


def _store(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "database.sqlite"
    con = sqlite3.connect(path)
    try:
        con.execute(
            "CREATE TABLE ZTRANSCRIPTION (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER,"
            " ZCALLEDEXTERNALASR INTEGER, ZDIDUPLOADHISTORY INTEGER, ZFALLBACKLEVEL INTEGER,"
            " ZENDDATE TIMESTAMP, ZPROCESSINGDURATION FLOAT, ZSTARTDATE TIMESTAMP, ZAPPBUNDLEID VARCHAR,"
            " ZASRTEXT VARCHAR, ZAUDIOFILENAME VARCHAR, ZERRORSTRING VARCHAR, ZID VARCHAR, ZLANGUAGE VARCHAR,"
            " ZLLMTEXT VARCHAR, ZSTATUS VARCHAR, ZTRANSCRIPTORIGIN VARCHAR, ZTRANSCRIPTIONTEXT VARCHAR)"
        )
        con.execute("CREATE TABLE ZDICTIONARYWORD (Z_PK INTEGER PRIMARY KEY, ZVALUE VARCHAR)")
        con.execute("CREATE TABLE Z_PRIMARYKEY (Z_ENT INTEGER PRIMARY KEY, Z_NAME VARCHAR, Z_MAX INTEGER)")
        for i, (zid, start, end, status, origin, lang, app, asr, llm, text) in enumerate(ROWS, 1):
            con.execute(
                "INSERT INTO ZTRANSCRIPTION (Z_PK, Z_ENT, Z_OPT, ZENDDATE, ZSTARTDATE, ZAPPBUNDLEID,"
                " ZASRTEXT, ZAUDIOFILENAME, ZID, ZLANGUAGE, ZLLMTEXT, ZSTATUS, ZTRANSCRIPTORIGIN,"
                " ZTRANSCRIPTIONTEXT)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (i, 5, 1, end, start, app, asr, f"{zid}.wav", zid, lang, llm, status, origin, text),
            )
        con.commit()
    finally:
        con.close()
    return path


@pytest.fixture
def store(tmp_path: Path) -> Path:
    return _store(tmp_path / "wispr")


def _drafts(path: Path, **options) -> tuple[list[dict], dict[str, int], list[bytes]]:
    counts: dict[str, int] = {}
    stored: list[bytes] = []
    drafts = list(wispr_flow.run(path, counts=counts, store=stored.append, **options))
    return drafts, counts, stored


def test_registry_has_wispr_flow_by_name_and_alias():
    assert adapters.named("wispr-flow") is wispr_flow
    assert adapters.named("wispr") is wispr_flow


def test_sniff_recognises_the_store_by_its_table(store, tmp_path):
    assert wispr_flow.sniff(store)
    assert not wispr_flow.sniff(tmp_path / "missing.sqlite")
    other = tmp_path / "other.sqlite"
    con = sqlite3.connect(other)
    con.execute("CREATE TABLE ZNOTE (Z_PK INTEGER)")
    con.commit()
    con.close()
    assert not wispr_flow.sniff(other)
    assert not wispr_flow.sniff(tmp_path)


def test_each_dictation_is_one_transcript_with_its_text_as_an_attachment(store):
    drafts, _counts, stored = _drafts(store)
    assert len(drafts) == LINES
    d = drafts[0]
    assert d["at"] == "2026-09-10T00:26:40Z" and d["end"] == "2026-09-10T00:26:57Z" and d["tz"] is None
    assert (d["source"], d["kind"], d["tier"]) == ("wispr-flow", "transcript", 3)
    p = d["payload"]
    text = b"Hallo Ola, kommst du heute Abend?"
    assert p["schema"] == "transcript/v1" and p["provider"] == "wispr-flow"
    assert p["raw_id"] == "wispr-flow:A1B2C3D4-0000-4000-8000-000000000001"
    assert p["content"] == attachments.reference(text, "text/plain")
    assert p["participants"] == [] and p["language"] == "de"
    assert p["extra"] == {"app": "net.whatsapp.WhatsApp", "status": "formatted", "text": "formatted"}
    assert stored[0] == text
    assert "title" not in p and "summary" not in p


def test_the_raw_transcript_is_the_text_when_nothing_was_formatted(store):
    drafts, _, stored = _drafts(store)
    raw = drafts[1]["payload"]
    assert raw["content"] == attachments.reference(b"buy milk and call the marina", "text/plain")
    assert raw["extra"] == {
        "app": "com.apple.mobilenotes",
        "status": "raw_transcript",
        "origin": "internal",
        "text": "asr",
    }
    assert stored[1] == b"buy milk and call the marina"


def test_rows_without_text_or_start_are_counted_and_a_bad_end_is_dropped(store):
    drafts, counts, _ = _drafts(store)
    assert counts == {"skipped_no_text": 1, "skipped_no_timestamp": 1, "end_before_start": 1}
    bad_end = next(d for d in drafts if d["payload"]["raw_id"].endswith("0005"))
    assert bad_end["end"] is None
    no_end = next(d for d in drafts if d["payload"]["raw_id"].endswith("0006"))
    assert no_end["end"] is None


def test_the_spoken_words_are_never_inline(store):
    drafts, _, _ = _drafts(store)
    text = json.dumps(drafts)
    assert "Hallo Ola" not in text and "marina" not in text


def test_tier_and_since(store):
    drafts, _, _ = _drafts(store, tier=2)
    assert {d["tier"] for d in drafts} == {2}
    drafts, _, _ = _drafts(store, since="2026-09-10T02:00:00Z")
    assert [d["payload"]["raw_id"][-1] for d in drafts] == ["5", "6"]


def test_add_puts_the_text_in_the_store_and_the_record_validates(store, tmp_path, monkeypatch, capsys):
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    lb = Logbook.init(root, "Europe/Oslo")
    cli.main(["add", "wispr", str(store)])
    out = capsys.readouterr().out
    assert f"added {LINES} lines from wispr-flow" in out
    assert (
        "skipped 1 without any text" in out
        and "1 without a timestamp" in out
        and "also 1 end before start" in out
    )
    lines = list(lb.lines())
    assert len(lines) == LINES and {ln["tz"] for ln in lines} == {"Europe/Oslo"}
    for line in lines:
        Draft202012Validator(SCHEMA).validate(line)
        ref = line["payload"]["content"]
        assert (root / ref["path"]).is_file() and (root / ref["path"]).stat().st_size == ref["bytes"]
    cli.main(["add", "wispr", str(store)])
    assert "added 0 lines from wispr-flow" in capsys.readouterr().out
    seq, _head, errors = lb.verify()
    assert (seq, errors) == (LINES, [])
