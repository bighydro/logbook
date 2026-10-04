"""Apple Books' AEAnnotation store → highlight/v1 (RFC 0022): highlights with notes, bookmarks, the
book looked up in the BKLibrary store beside it; reading positions and deleted marks skipped."""

from __future__ import annotations

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
from logbook.contrib.adapters import apple_books
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
RFC = ROOT / "rfcs" / "0022-highlight-v1.md"
TZ = "Europe/Oslo"
APPLE_EPOCH = 978_307_200

# Books' own layout, as far as the adapter reads it (the real table has many more columns).
ANNOTATION_DDL = """
CREATE TABLE ZAEANNOTATION (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZANNOTATIONDELETED INTEGER,
    ZANNOTATIONISUNDERLINE INTEGER, ZANNOTATIONSTYLE INTEGER, ZANNOTATIONTYPE INTEGER,
    ZPLABSOLUTEPHYSICALLOCATION INTEGER, ZANNOTATIONCREATIONDATE TIMESTAMP,
    ZANNOTATIONMODIFICATIONDATE TIMESTAMP, ZANNOTATIONASSETID VARCHAR, ZANNOTATIONLOCATION VARCHAR,
    ZANNOTATIONNOTE VARCHAR, ZANNOTATIONREPRESENTATIVETEXT VARCHAR, ZANNOTATIONSELECTEDTEXT VARCHAR,
    ZANNOTATIONUUID VARCHAR);
"""
LIBRARY_DDL = """
CREATE TABLE ZBKLIBRARYASSET (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZCONTENTTYPE INTEGER,
    ZASSETID VARCHAR, ZAUTHOR VARCHAR, ZTITLE VARCHAR, ZSORTTITLE VARCHAR, ZPATH VARCHAR);
"""
SHIPS = "A1B2C3D4E5F60718293A4B5C6D7E8F90"  # a local EPUB: 32 hex characters
SAGA = "1234567890"  # a store book: its numeric id
LOST = "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF"  # a book the library no longer has
BOOKS = [
    (1, 1, 1, 1, SHIPS, "Frans G. Bengtsson", "The Long Ships", "long ships", "Books/ships.epub"),
    (2, 1, 1, 1, SAGA, "Snorri Sturluson", "Heimskringla", "heimskringla", None),
]


def _apple(stamp: str) -> float:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp() - APPLE_EPOCH


HIGHLIGHT, BOOKMARK, POSITION = 2, 1, 3
ROWS: list[dict[str, Any]] = [  # one per shape the adapter meets
    {
        "pk": 1, "uuid": "6F1A2B3C-0000-4000-8000-000000000001", "asset": SHIPS, "type": HIGHLIGHT,
        "style": 3, "underline": 0, "deleted": 0, "created": "2026-03-02T20:14:07Z",
        "modified": "2026-03-03T07:00:00Z", "location": "epubcfi(/6/14!/4/2/8,/1:0,/1:66)",
        "quote": "  They sailed west until the coast was a line and then was nothing.  ",
        "note": "the moment the book turns",
    },
    {
        "pk": 2, "uuid": "6F1A2B3C-0000-4000-8000-000000000002", "asset": SAGA, "type": HIGHLIGHT,
        "style": 0, "underline": 1, "deleted": 0, "created": "2026-03-05T06:30:00Z",
        "modified": "2026-03-05T06:30:00Z", "location": "epubcfi(/6/20!/4/2/12,/1:10,/1:80)",
        "quote": "Harald set out from Vik with a small following.", "note": None,
    },
    {
        "pk": 3, "uuid": "6F1A2B3C-0000-4000-8000-000000000003", "asset": SHIPS, "type": BOOKMARK,
        "style": 0, "underline": 0, "deleted": 0, "created": "2026-03-06T21:00:00Z",
        "modified": "2026-03-06T21:00:00Z", "location": "epubcfi(/6/30!/4/2)", "quote": None, "note": None,
    },
    {  # where the owner last stopped reading: the app's state, not a mark
        "pk": 4, "uuid": "6F1A2B3C-0000-4000-8000-000000000004", "asset": SHIPS, "type": POSITION,
        "style": 0, "underline": 0, "deleted": 0, "created": "2026-03-07T21:00:00Z",
        "modified": "2026-03-07T21:00:00Z", "location": "epubcfi(/6/32!/4/2)", "quote": None, "note": None,
    },
    {  # removed by the owner: a tombstone
        "pk": 5, "uuid": "6F1A2B3C-0000-4000-8000-000000000005", "asset": SHIPS, "type": HIGHLIGHT,
        "style": 1, "underline": 0, "deleted": 1, "created": "2026-03-08T21:00:00Z",
        "modified": "2026-03-08T21:00:00Z", "location": "epubcfi(/6/34!/4/2,/1:0,/1:9)", "quote": "Gone now.",
        "note": None,
    },
    {  # a book the library no longer lists
        "pk": 6, "uuid": "6F1A2B3C-0000-4000-8000-000000000006", "asset": LOST, "type": HIGHLIGHT,
        "style": 2, "underline": 0, "deleted": 0, "created": "2026-03-09T21:00:00Z",
        "modified": "2026-03-09T21:00:00Z", "location": None, "quote": "A line from a book that is gone.",
        "note": None,
    },
    {  # no date: nothing to put the line on
        "pk": 7, "uuid": "6F1A2B3C-0000-4000-8000-000000000007", "asset": SHIPS, "type": HIGHLIGHT,
        "style": 3, "underline": 0, "deleted": 0, "created": None, "modified": None,
        "location": "epubcfi(/6/36!/4/2,/1:0,/1:9)", "quote": "Undated.", "note": None,
    },
    {  # a placeholder date
        "pk": 8, "uuid": "6F1A2B3C-0000-4000-8000-000000000008", "asset": SHIPS, "type": HIGHLIGHT,
        "style": 3, "underline": 0, "deleted": 0, "created": "1800-01-01T00:00:00Z", "modified": None,
        "location": "epubcfi(/6/38!/4/2,/1:0,/1:9)", "quote": "Before the epoch.", "note": None,
    },
]  # fmt: skip
LINES = 4  # two highlights, one bookmark, one highlight in a lost book
SKIPS = {
    "skipped_reading_position": 1,
    "skipped_deleted": 1,
    "skipped_no_date": 1,
    "skipped_placeholder_date": 1,
}


def _store(folder: Path, rows: list[dict[str, Any]] = ROWS, *, library: bool | str = True) -> Path:
    """A synthetic AEAnnotation store and, beside it (`library=True`) or in Books' own `../BKLibrary/`
    folder (`library="documents"`), the library store that names the books. Nobody in it exists."""
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / "AEAnnotation_v10312011_1727_local.sqlite"
    with closing(sqlite3.connect(p)) as con:
        con.executescript(ANNOTATION_DDL)
        for r in rows:
            con.execute(
                "INSERT INTO ZAEANNOTATION VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    r["pk"], 1, 1, r["deleted"], r["underline"], r["style"], r["type"], None,
                    _apple(r["created"]) if r["created"] else None,
                    _apple(r["modified"]) if r["modified"] else None,
                    r["asset"], r["location"], r["note"], None, r["quote"], r["uuid"],
                ),
            )  # fmt: skip
        con.commit()
    if library:
        lib = folder if library is True else folder.parent / "BKLibrary"
        lib.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(lib / "BKLibrary-1-091020131601.sqlite")) as con:
            con.executescript(LIBRARY_DDL)
            con.executemany("INSERT INTO ZBKLIBRARYASSET VALUES (?,?,?,?,?,?,?,?,?)", BOOKS)
            con.commit()
    return p


def _lines(tmp_path: Path, **kw: Any) -> list[dict[str, Any]]:
    return list(apple_books.run(_store(tmp_path / "books"), **kw))


def _by_raw_id(lines: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {line["payload"]["raw_id"]: line for line in lines}


def _profile() -> dict[str, Any]:
    """The RFC's own JSON Schema, read from the document so the two cannot drift."""
    text = RFC.read_text(encoding="utf-8")
    block = re.search(r"## JSON Schema\n\n```json\n(.*?)\n```", text, re.S)
    assert block is not None
    schema: dict[str, Any] = json.loads(block.group(1))
    return schema


# -- registry and sniff ----------------------------------------------------------------------------


def test_registry_lists_apple_books_and_books_is_an_alias():
    assert apple_books in adapters.file_adapters()
    assert adapters.named("apple-books") is apple_books
    assert adapters.named("books") is apple_books


def test_sniff_takes_an_annotation_store_and_nothing_else(tmp_path):
    store = _store(tmp_path / "books")
    assert apple_books.sniff(store)
    assert not apple_books.sniff(tmp_path / "books" / "BKLibrary-1-091020131601.sqlite")
    other = tmp_path / "other.sqlite"
    with closing(sqlite3.connect(other)) as con:
        con.execute("CREATE TABLE t (x)")
    assert not apple_books.sniff(other)
    assert not apple_books.sniff(tmp_path / "missing.sqlite")
    text = tmp_path / "notes.txt"
    text.write_text("not a store", encoding="utf-8")
    assert not apple_books.sniff(text)


# -- the lines -------------------------------------------------------------------------------------


def test_every_line_is_a_highlight_line_with_the_rfc_payload(tmp_path):
    lines = _lines(tmp_path, timezone=TZ)
    assert len(lines) == LINES
    validator = Draft202012Validator(_profile())
    for line in lines:
        assert set(line) == {"at", "end", "tz", "source", "kind", "tier", "payload"}
        assert (line["source"], line["kind"], line["tier"], line["tz"], line["end"]) == (
            "apple-books", "highlight", 2, TZ, None,
        )  # fmt: skip
        validator.validate(line["payload"])
    assert [line["at"] for line in lines] == sorted(line["at"] for line in lines)


def test_a_highlight_carries_the_book_the_quote_the_note_and_where(tmp_path):
    p = _by_raw_id(_lines(tmp_path))["6F1A2B3C-0000-4000-8000-000000000001"]
    assert p["at"] == "2026-03-02T20:14:07Z" and p["tz"] is None
    assert p["payload"] == {
        "schema": "highlight/v1",
        "raw_id": "6F1A2B3C-0000-4000-8000-000000000001",
        "type": "highlight",
        "title": "The Long Ships",
        "author": "Frans G. Bengtsson",
        "asset_id": SHIPS,
        "quote": "They sailed west until the coast was a line and then was nothing.",
        "note": "the moment the book turns",
        "location": "epubcfi(/6/14!/4/2/8,/1:0,/1:66)",
        "modified_at": "2026-03-03T07:00:00Z",
        "extra": {"style": 3, "underline": False},
    }


def test_an_underline_without_a_note_and_a_bookmark_without_a_quote(tmp_path):
    by = _by_raw_id(_lines(tmp_path))
    underline = by["6F1A2B3C-0000-4000-8000-000000000002"]["payload"]
    assert underline["title"] == "Heimskringla" and underline["extra"] == {"style": 0, "underline": True}
    assert "note" not in underline and "modified_at" not in underline  # not later than `at`
    bookmark = by["6F1A2B3C-0000-4000-8000-000000000003"]["payload"]
    assert bookmark["type"] == "bookmark" and "quote" not in bookmark
    assert bookmark["location"] == "epubcfi(/6/30!/4/2)" and bookmark["title"] == "The Long Ships"


def test_a_book_the_library_does_not_have_keeps_its_asset_id_and_is_counted(tmp_path):
    counts: dict[str, int] = {}
    p = _by_raw_id(_lines(tmp_path, counts=counts))["6F1A2B3C-0000-4000-8000-000000000006"]["payload"]
    assert "title" not in p and "author" not in p and "location" not in p
    assert p["asset_id"] == LOST and p["quote"] == "A line from a book that is gone."
    assert counts["no_title"] == 1


def test_reading_positions_deleted_marks_and_undated_rows_are_skipped_and_counted(tmp_path):
    counts: dict[str, int] = {}
    lines = _lines(tmp_path, counts=counts)
    assert len(lines) == LINES
    assert {k: v for k, v in counts.items() if k.startswith("skipped_")} == SKIPS


def test_the_library_is_found_in_books_own_documents_layout(tmp_path):
    store = _store(tmp_path / "Documents" / "storeFiles", library="documents")
    titles = {line["payload"].get("title") for line in apple_books.run(store)}
    assert titles == {"The Long Ships", "Heimskringla", None}


def test_without_a_library_every_line_has_an_asset_id_and_no_title(tmp_path):
    counts: dict[str, int] = {}
    lines = list(apple_books.run(_store(tmp_path / "books", library=False), counts=counts))
    assert len(lines) == LINES and all("title" not in line["payload"] for line in lines)
    assert counts["no_title"] == LINES


def test_since_and_tier(tmp_path):
    lines = _lines(tmp_path, since="2026-03-06T00:00:00Z", tier=1)
    assert [line["at"] for line in lines] == ["2026-03-06T21:00:00Z", "2026-03-09T21:00:00Z"]
    assert {line["tier"] for line in lines} == {1}


def test_the_store_is_never_written(tmp_path):
    store = _store(tmp_path / "books")
    before = store.read_bytes()
    list(apple_books.run(store))
    assert store.read_bytes() == before
    assert sorted(p.name for p in store.parent.iterdir()) == [
        "AEAnnotation_v10312011_1727_local.sqlite", "BKLibrary-1-091020131601.sqlite",
    ]  # fmt: skip


# -- through the CLI --------------------------------------------------------------------------------


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook.init(root, TZ)


def test_add_books_appends_once_and_show_prints_the_quote_with_the_title(lb, tmp_path, capsys):
    store = _store(tmp_path / "books")
    cli.main(["add", "books", str(store)])
    out = capsys.readouterr().out
    assert f"added {LINES} lines from apple-books" in out
    for phrase in ("1 reading positions", "1 deleted", "1 without a date", "1 with a placeholder start"):
        assert phrase in out, phrase
    assert "also 1 without a title" in out
    cli.main(["add", "books", str(store)])
    assert "added 0 lines" in capsys.readouterr().out
    cli.main(["show", "2026-03-02"])
    out = capsys.readouterr().out
    assert "highlight" in out and "“They sailed west" in out and "The Long Ships" in out
    assert "the moment the book turns" in out
    cli.main(["show", "2026-03-06"])
    assert "bookmark" in capsys.readouterr().out
    seq, _head, errors = lb.verify()
    assert (seq, errors) == (LINES, [])


def test_run_takes_the_folder_the_store_is_in(tmp_path):
    store = _store(tmp_path / "books")
    assert len(list(apple_books.run(store.parent))) == LINES
