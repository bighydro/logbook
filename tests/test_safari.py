"""Safari's History.db (an iPhone backup, or the Mac's own) → browse/v1 (RFC 0017), one line per visit."""

from __future__ import annotations

import hashlib
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import cli
from logbook.contrib import adapters
from logbook.contrib.adapters import safari

ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
TZ = "Europe/Oslo"
APPLE_EPOCH = 978_307_200
LINES = 3  # what `_store` yields; the import-backup tests count on it

ITEMS = [  # (id, url, visit_count)
    (1, "https://havn.example.org/", 2),
    (2, "https://charts.example.org/oslofjord", 1),
    (3, "https://example.org/never-visited", 0),
]
VISITS = [  # (id, history_item, visit_time since 2001, title, load_successful, redirect_destination)
    (10, 1, 1772614800.0 - APPLE_EPOCH, "Havnekontoret", 1, None),  # 2026-03-04T09:00:00Z
    (11, 1, 1772614860.5 - APPLE_EPOCH, "Havnekontoret - priser", 1, None),  # 09:01:00.5
    (12, 2, 1770796800.0 - APPLE_EPOCH, None, 0, None),  # 2026-02-11T08:00:00Z, failed to load
]


def _store(folder: Path, modern: bool = True) -> Path:
    """A synthetic History.db with Safari's two tables; `modern=False` leaves out the columns an
    older Safari did not have (title on the visit, redirect_destination)."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "History.db"
    con = sqlite3.connect(path)
    try:
        con.execute(
            "CREATE TABLE history_items (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL UNIQUE,"
            " domain_expansion TEXT NULL, visit_count INTEGER NOT NULL, daily_visit_counts BLOB NOT NULL,"
            " weekly_visit_counts BLOB NULL, autocomplete_triggers BLOB NULL,"
            " should_recompute_derived_visit_counts INTEGER NOT NULL, visit_count_score INTEGER NOT NULL,"
            " status_code INTEGER NOT NULL DEFAULT 0)"
        )
        columns = (
            "id INTEGER PRIMARY KEY AUTOINCREMENT, history_item INTEGER NOT NULL, visit_time REAL NOT NULL,"
            + (" title TEXT NULL," if modern else "")
            + " load_successful BOOLEAN NOT NULL DEFAULT 1, http_non_get BOOLEAN NOT NULL DEFAULT 0,"
            " synthesized BOOLEAN NOT NULL DEFAULT 0, redirect_source INTEGER NULL,"
            + (" redirect_destination INTEGER NULL," if modern else "")
            + " origin INTEGER NOT NULL DEFAULT 0, generation INTEGER NOT NULL DEFAULT 0,"
            " attributes INTEGER NOT NULL DEFAULT 0, score INTEGER NOT NULL DEFAULT 0"
        )
        con.execute(f"CREATE TABLE history_visits ({columns})")
        con.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value)")
        for item_id, url, count in ITEMS:
            con.execute(
                "INSERT INTO history_items (id, url, visit_count, daily_visit_counts,"
                " should_recompute_derived_visit_counts, visit_count_score) VALUES (?,?,?,?,0,0)",
                (item_id, url, count, b""),
            )
        for visit_id, item, when, title, ok, redirect in VISITS:
            if modern:
                con.execute(
                    "INSERT INTO history_visits (id, history_item, visit_time, title, load_successful,"
                    " redirect_destination) VALUES (?,?,?,?,?,?)",
                    (visit_id, item, when, title, ok, redirect),
                )
            else:
                con.execute(
                    "INSERT INTO history_visits (id, history_item, visit_time, load_successful)"
                    " VALUES (?,?,?,?)",
                    (visit_id, item, when, ok),
                )
        con.commit()
    finally:
        con.close()
    return path


def _digest(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def test_registry_has_safari_as_a_file_adapter(tmp_path):
    assert adapters.named("safari") is safari
    assert isinstance(safari, adapters.Adapter)
    assert adapters.find(_store(tmp_path)) is safari


def test_sniff_wants_safaris_two_tables(tmp_path):
    assert safari.sniff(_store(tmp_path / "a"))
    assert not safari.sniff(tmp_path / "a")  # the folder is not the store
    assert not safari.sniff(tmp_path / "missing.db")
    other = tmp_path / "other.db"
    con = sqlite3.connect(other)
    con.execute("CREATE TABLE history_items (id INTEGER)")
    con.commit()
    con.close()
    assert not safari.sniff(other)
    (tmp_path / "garbage.db").write_bytes(b"SQLite format 3\0" + b"\x02" * 1000)
    assert not safari.sniff(tmp_path / "garbage.db")


def test_every_visit_is_a_line_and_the_envelope_is_complete(tmp_path):
    counts: dict[str, int] = {}
    lines = list(safari.run(_store(tmp_path), timezone=TZ, counts=counts))
    assert len(lines) == LINES
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["kind"] == "browse" and line["source"] == "safari" and line["tier"] == 2
        assert line["end"] is None and line["tz"] == TZ
        assert line["payload"]["schema"] == "browse/v1" and line["payload"]["browser"] == "safari"
        assert line["payload"]["action"] == "visit"
    assert counts == {"load_failed": 1}
    assert [line["at"] for line in lines] == sorted(line["at"] for line in lines)


def test_a_visit_maps_url_title_and_time_from_the_apple_epoch(tmp_path):
    by = {line["payload"]["raw_id"]: line for line in safari.run(_store(tmp_path), timezone=TZ)}
    url = "https://havn.example.org/"
    first = by[f"safari:794307600.0:{_digest(url)}"]
    assert first["at"] == "2026-03-04T09:00:00Z"
    assert first["payload"] == {
        "schema": "browse/v1",
        "raw_id": f"safari:794307600.0:{_digest(url)}",
        "url": url,
        "title": "Havnekontoret",
        "action": "visit",
        "browser": "safari",
    }
    second = by[f"safari:794307660.5:{_digest(url)}"]
    assert second["at"] == "2026-03-04T09:01:00Z"
    assert second["payload"]["title"] == "Havnekontoret - priser"
    failed = by[f"safari:792489600.0:{_digest('https://charts.example.org/oslofjord')}"]["payload"]
    assert "title" not in failed and failed["extra"] == {"load_successful": False}


def test_an_older_store_without_the_optional_columns_still_reads(tmp_path):
    lines = list(safari.run(_store(tmp_path, modern=False), timezone=TZ))
    assert len(lines) == LINES and all("title" not in line["payload"] for line in lines)


def test_since_cuts_on_at_and_the_store_is_opened_read_only(tmp_path):
    store = _store(tmp_path)
    before = store.read_bytes()
    lines = list(safari.run(store, timezone=TZ, since="2026-03-01T00:00:00Z"))
    assert len(lines) == 2
    assert store.read_bytes() == before
    assert not (tmp_path / "History.db-journal").exists() and not (tmp_path / "History.db-wal").exists()


def test_cli_add_safari_names_a_copy_under_any_name(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "lb"))
    cli.main(["init", str(tmp_path / "lb"), "--timezone", TZ])
    capsys.readouterr()
    store = _store(tmp_path / "copy").rename(tmp_path / "copy" / "history-from-the-mac.sqlite")
    cli.main(["add", "safari", str(store)])
    out = capsys.readouterr().out
    assert f"added {LINES} lines from safari" in out and "1 that did not load" in out
    cli.main(["add", "safari", str(store)])
    assert "added 0 lines from safari" in capsys.readouterr().out
