"""One index table for what the sources saw (RFC 0037, decision 7): `observed_entities`, a row per
observed person, org, idea, asset or place, stamped per kind; `observed_people` and `observed_places`
its views for one release, so people review and places review read on unchanged; an index built by
0.6 (schema 7, the two tables of their own) is rebuilt and its tables become the views."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from places_record import record
from review_people import review_record

from logbook.contrib import people_review, places_review
from logbook.core import index
from logbook.core.store import Logbook


def _rows(lb: Logbook, sql: str, *args: object) -> list[tuple[object, ...]]:
    with sqlite3.connect(lb.index_path) as db:
        return list(db.execute(sql, args))


def test_one_table_holds_every_kind_and_the_views_read_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = review_record(tmp_path / "people", monkeypatch)
    people = people_review.observed(lb)
    root = tmp_path / "places" / "lb"
    places_lb = record(root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    spots = places_review.observed(places_lb)
    assert _rows(lb, "SELECT kind, count(*) FROM observed_entities GROUP BY kind") == [
        ("person", len(people))
    ]
    assert _rows(places_lb, "SELECT kind, count(*) FROM observed_entities GROUP BY kind") == [
        ("place", len(spots))
    ]
    for which in (lb, places_lb):
        assert sorted(_rows(which, "SELECT name, type FROM sqlite_master WHERE name LIKE 'observed%'")) == [
            ("observed_entities", "table"),
            ("observed_entities_key", "index"),
            ("observed_entities_meta", "table"),
            ("observed_people", "view"),
            ("observed_places", "view"),
        ]
    assert _rows(lb, "SELECT count(*) FROM observed_people") == [(len(people),)]
    assert _rows(places_lb, "SELECT id FROM observed_places ORDER BY rowid") == [(o.id,) for o in spots]
    assert _rows(lb, "SELECT DISTINCT hint FROM observed_entities") == [(None,)], "a hint is an org's alone"
    assert people_review.observed(lb) == people and places_review.observed(places_lb) == spots, "read back"


def test_a_schema_seven_index_is_rebuilt_and_its_old_tables_become_views(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = review_record(tmp_path, monkeypatch)
    before = people_review.observed(lb)
    with sqlite3.connect(lb.index_path) as db:  # the index as 0.6 left it
        for view in index.OBSERVED_VIEWS:
            db.execute(f"DROP VIEW {view}")
        db.execute("DROP TABLE observed_entities")
        db.execute("DROP TABLE observed_entities_meta")
        db.execute("CREATE TABLE observed_people (key_kind TEXT, key_value TEXT, entity TEXT)")
        db.execute("CREATE TABLE observed_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("CREATE TABLE observed_places (id TEXT, lat REAL, lon REAL)")
        db.execute("CREATE TABLE observed_places_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("UPDATE meta SET value = '7' WHERE key = 'schema'")
    with Logbook(lb.root).index():
        pass
    kinds = dict(_rows(lb, "SELECT name, type FROM sqlite_master WHERE name LIKE 'observed%'"))
    assert kinds["observed_people"] == "view" and kinds["observed_places"] == "view"
    assert "observed_meta" not in kinds and "observed_places_meta" not in kinds, "the old stamps go"
    assert _rows(lb, "SELECT value FROM meta WHERE key = 'schema'") == [(index.SCHEMA_VERSION,)]
    assert people_review.observed(Logbook(lb.root)) == before, "built again from the lines, the same"
    assert lb.verify()[2] == [], "nothing in the record changed"


def test_store_observed_replaces_one_kind_and_keeps_the_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = review_record(tmp_path, monkeypatch)
    people = people_review.observed(lb)
    rows = [
        {
            "key_kind": "domain",
            "key_value": "nordmann-verft.example.org",
            "name": "Nordmann Verft",
            "hint": "company",
        },
        {
            "key_kind": "merchant",
            "key_value": "fjordkiosk",
            "name": "FJORDKIOSK",
            "hint": "brand",
            "count": 4,
        },
    ]
    with lb.index() as idx:
        idx.store_observed("org", rows, {"head": str(lb.meta["head"]), "version": "1"})
        assert idx.observed_stamp("org") == {"head": str(lb.meta["head"]), "version": "1"}
        found = idx.observed("org")
        assert [(r["ord"], r["key_value"], r["hint"], r["count"]) for r in found] == [
            (0, "nordmann-verft.example.org", "company", 0),
            (1, "fjordkiosk", "brand", 4),
        ]
        idx.store_observed("org", rows[1:], {"head": "x"})
        assert [r["key_value"] for r in idx.observed("org")] == ["fjordkiosk"]
        assert idx.observed_stamp("org") == {"head": "x"}
        assert len(idx.observed("person")) == len(people), "the person rows stand"
    assert set(index.HINTS) == {"company", "brand", "community", "personal"}
    assert people_review.observed(lb) == people
