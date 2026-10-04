"""Screen Time → `app-use` lines: the Mac's knowledgeC.db (`/app/usage` sessions) and the phone's
RMAdminStore-Local.sqlite from an iOS backup (hourly totals per app). Synthetic stores with the real
table and column names; nobody in them exists, and no window title or URL ever reaches a line."""

from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters, cli
from logbook.adapters import screentime
from logbook.core import apps
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
APPLE_EPOCH = 978_307_200


def _apple(stamp: str) -> float:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp() - APPLE_EPOCH


# -- knowledgeC.db, the Mac -------------------------------------------------------------------------

# CoreDuet's knowledge store, as far as the adapter reads it (the real tables have more columns).
KNOWLEDGE_DDL = """
CREATE TABLE ZOBJECT (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZENDDAYOFWEEK INTEGER, ZENDSECONDOFDAY INTEGER,
    ZHASCUSTOMMETADATA INTEGER, ZHASSTRUCTUREDMETADATA INTEGER, ZSECONDSFROMGMT INTEGER,
    ZSTARTDAYOFWEEK INTEGER, ZSTARTSECONDOFDAY INTEGER, ZVALUECLASS INTEGER, ZVALUEINTEGER INTEGER,
    ZSOURCE INTEGER, ZSTRUCTUREDMETADATA INTEGER, ZCREATIONDATE TIMESTAMP, ZENDDATE TIMESTAMP,
    ZLOCALCREATIONDATE TIMESTAMP, ZSTARTDATE TIMESTAMP, ZVALUEDOUBLE FLOAT, ZSTREAMNAME VARCHAR,
    ZUUID VARCHAR, ZVALUESTRING VARCHAR, ZVALUETYPE VARCHAR);
CREATE TABLE ZSOURCE (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZDELETED INTEGER, ZBUNDLEID VARCHAR,
    ZDEVICEID VARCHAR, ZGROUPID VARCHAR, ZITEMID VARCHAR, ZSOURCEID VARCHAR);
CREATE TABLE ZSTRUCTUREDMETADATA (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER,
    Z_DKAPPLICATIONACTIVITYMETADATAKEY__TITLE VARCHAR,
    Z_DKAPPLICATIONACTIVITYMETADATAKEY__CONTENTURL VARCHAR);
"""
PHONE_DEVICE = "0A1B2C3D-0000-4000-8000-00000000BEEF"  # a device id another device synced under
WINDOW_TITLE = "Quarterly numbers — never recorded"
URL = "https://example.org/private/page"
SESSIONS: list[dict[str, Any]] = [  # one per shape the adapter meets
    {"pk": 1, "stream": "/app/usage", "bundle": "com.apple.Safari", "start": "2026-06-08T07:00:00Z",
     "end": "2026-06-08T07:25:00Z", "source": 1, "uuid": "C0FFEE00-0000-4000-8000-000000000001"},
    {"pk": 2, "stream": "/app/usage", "bundle": "com.apple.MobileSMS", "start": "2026-06-08T07:25:00Z",
     "end": "2026-06-08T07:31:00Z", "source": 1, "uuid": "C0FFEE00-0000-4000-8000-000000000002"},
    {"pk": 3, "stream": "/app/usage", "bundle": "com.apple.dt.Xcode", "start": "2026-06-08T08:00:00Z",
     "end": "2026-06-08T10:30:00Z", "source": 1, "uuid": "C0FFEE00-0000-4000-8000-000000000003"},
    {  # an app the built-in table does not know: the bundle id stands as the title, counted
     "pk": 4, "stream": "/app/usage", "bundle": "org.example.puzzle", "start": "2026-06-08T12:00:00Z",
     "end": "2026-06-08T12:10:00Z", "source": 1, "uuid": "C0FFEE00-0000-4000-8000-000000000004"},
    {  # synced from another device: that device's id
     "pk": 5, "stream": "/app/usage", "bundle": "com.apple.mobilesafari", "start": "2026-06-08T18:00:00Z",
     "end": "2026-06-08T18:20:00Z", "source": 2, "uuid": "C0FFEE00-0000-4000-8000-000000000005"},
    {  # the same session written twice (a re-sync): one line
     "pk": 6, "stream": "/app/usage", "bundle": "com.apple.mobilesafari", "start": "2026-06-08T18:00:00Z",
     "end": "2026-06-08T18:20:00Z", "source": 2, "uuid": "C0FFEE00-0000-4000-8000-000000000006"},
    {  # a window title and a URL: another stream, never read
     "pk": 7, "stream": "/app/activity", "bundle": "com.apple.Safari", "start": "2026-06-08T07:01:00Z",
     "end": "2026-06-08T07:02:00Z", "source": 1, "uuid": "C0FFEE00-0000-4000-8000-000000000007",
     "metadata": 1},
    {  # the focus stream: not a usage session
     "pk": 8, "stream": "/app/inFocus", "bundle": "com.apple.Safari", "start": "2026-06-08T07:00:00Z",
     "end": "2026-06-08T07:25:00Z", "source": 1, "uuid": "C0FFEE00-0000-4000-8000-000000000008"},
    {  # nothing happened in it
     "pk": 9, "stream": "/app/usage", "bundle": "com.apple.Safari", "start": "2026-06-08T13:00:00Z",
     "end": "2026-06-08T13:00:00Z", "source": 1, "uuid": "C0FFEE00-0000-4000-8000-000000000009"},
    {  # ends before it starts
     "pk": 10, "stream": "/app/usage", "bundle": "com.apple.Safari", "start": "2026-06-08T14:00:00Z",
     "end": "2026-06-08T13:59:00Z", "source": 1, "uuid": "C0FFEE00-0000-4000-8000-000000000010"},
    {  # no start
     "pk": 11, "stream": "/app/usage", "bundle": "com.apple.Safari", "start": None,
     "end": "2026-06-08T15:00:00Z", "source": 1, "uuid": "C0FFEE00-0000-4000-8000-000000000011"},
    {  # no bundle id
     "pk": 12, "stream": "/app/usage", "bundle": None, "start": "2026-06-08T16:00:00Z",
     "end": "2026-06-08T16:05:00Z", "source": 1, "uuid": "C0FFEE00-0000-4000-8000-000000000012"},
    {  # the next day, for `since`
     "pk": 13, "stream": "/app/usage", "bundle": "com.apple.Safari", "start": "2026-06-09T07:00:00Z",
     "end": "2026-06-09T07:30:00Z", "source": 1, "uuid": "C0FFEE00-0000-4000-8000-000000000013"},
]  # fmt: skip
MAC_LINES = 6  # Safari, Messages, Xcode, the puzzle, the synced Safari once, the next day's Safari
MAC_SKIPS = {"skipped_empty": 2, "skipped_no_start": 1, "skipped_no_bundle": 1, "skipped_duplicate": 1}


def _mac_store(
    folder: Path, sessions: list[dict[str, Any]] = SESSIONS, *, name: str = "knowledgeC.db"
) -> Path:
    """A synthetic knowledgeC.db: the local Mac's sessions (ZSOURCE 1, no device id) and one other
    device's (ZSOURCE 2). The one `/app/activity` row carries a title and a URL the adapter must never
    read."""
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    with closing(sqlite3.connect(p)) as con:
        con.executescript(KNOWLEDGE_DDL)
        con.execute(
            "INSERT INTO ZSOURCE VALUES (1, 1, 1, 0, 'com.apple.coreduetd', NULL, NULL, NULL, 'local')"
        )
        con.execute(
            "INSERT INTO ZSOURCE VALUES (2, 1, 1, 0, 'com.apple.coreduetd', ?, NULL, NULL, 'synced')",
            (PHONE_DEVICE,),
        )
        con.execute("INSERT INTO ZSTRUCTUREDMETADATA VALUES (1, 1, 1, ?, ?)", (WINDOW_TITLE, URL))
        for s in sessions:
            con.execute(
                "INSERT INTO ZOBJECT (Z_PK, Z_ENT, Z_OPT, ZSOURCE, ZSTRUCTUREDMETADATA, ZSTARTDATE, ZENDDATE,"
                " ZSTREAMNAME, ZUUID, ZVALUESTRING) VALUES (?, 1, 1, ?, ?, ?, ?, ?, ?, ?)",
                (
                    s["pk"], s["source"], s.get("metadata"),
                    _apple(s["start"]) if s["start"] else None,
                    _apple(s["end"]) if s["end"] else None,
                    s["stream"], s["uuid"], s["bundle"],
                ),
            )  # fmt: skip
        con.commit()
    return p


# -- RMAdminStore-Local.sqlite, the phone ---------------------------------------------------------------

# Screen Time's own store (`com.apple.remotemanagementd`): hourly blocks, a category per block, the apps
# timed under each category, and the devices. The real tables have more columns.
PHONE_DDL = """
CREATE TABLE ZUSAGEBLOCK (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZDURATIONINMINUTES INTEGER,
    ZNUMBEROFPICKUPSWITHOUTAPPLICATIONUSAGE INTEGER, ZSCREENTIMEINSECONDS INTEGER, ZUSAGE INTEGER,
    ZFIRSTPICKUPDATE TIMESTAMP, ZLASTEVENTDATE TIMESTAMP, ZLONGESTSESSIONENDDATE TIMESTAMP,
    ZLONGESTSESSIONSTARTDATE TIMESTAMP, ZSTARTDATE TIMESTAMP);
CREATE TABLE ZUSAGECATEGORY (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZTOTALTIMEINSECONDS INTEGER, ZBLOCK INTEGER,
    ZIDENTIFIER VARCHAR);
CREATE TABLE ZUSAGETIMEDITEM (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZTOTALTIMEINSECONDS INTEGER, ZCATEGORY INTEGER,
    ZBUNDLEIDENTIFIER VARCHAR, ZDOMAIN VARCHAR);
CREATE TABLE ZUSAGECOUNTEDITEM (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZNUMBEROFNOTIFICATIONS INTEGER,
    ZNUMBEROFPICKUPS INTEGER, ZBLOCK INTEGER, ZBUNDLEIDENTIFIER VARCHAR, ZDOMAIN VARCHAR);
CREATE TABLE ZUSAGE (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZDEVICE INTEGER, ZUSER INTEGER,
    ZLASTUPDATEDDATE TIMESTAMP);
CREATE TABLE ZCOREDEVICE (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZPLATFORM INTEGER, ZIDENTIFIER VARCHAR,
    ZNAME VARCHAR);
CREATE TABLE ZINSTALLEDAPP (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZDEVICE INTEGER, ZBUNDLEIDENTIFIER VARCHAR,
    ZDISPLAYNAME VARCHAR);
"""
IPHONE = "7E7E7E7E-0000-4000-8000-00000000CAFE"  # the phone's own identifier in the store
DOMAIN = "private-reading.example.org"
BLOCKS = [  # (pk, usage, start): hourly blocks, local Oslo time 09:00 and 10:00 on 8 June, and one on 9 June
    (1, 1, "2026-06-08T07:00:00Z"),
    (2, 1, "2026-06-08T08:00:00Z"),
    (3, 1, "2026-06-09T07:00:00Z"),
]
CATEGORIES = [  # (pk, block, Apple's own category name, seconds)
    (1, 1, "Social", 900),
    (2, 1, "Productivity & Finance", 1500),
    (3, 2, "Social", 600),
    (4, 3, "Games", 240),
]
ITEMS: list[tuple[int, int, int, str | None, str | None]] = [  # (pk, category, seconds, bundle, domain)
    (1, 1, 900, "com.apple.MobileSMS", None),
    (2, 2, 1200, "com.apple.mobilesafari", None),
    (3, 2, 300, "com.apple.mobilenotes", None),
    (4, 2, 180, None, DOMAIN),  # a web domain under Safari: never a line, never a word of it kept
    (5, 3, 600, "net.whatsapp.WhatsApp", None),
    (6, 3, 0, "com.apple.MobileSMS", None),  # nothing in this hour
    (7, 4, 240, "org.example.puzzle", None),  # named by the store's own app table
]
PHONE_LINES = 5
PHONE_SKIPS = {"skipped_web_domain": 1, "skipped_empty": 1}


def _phone_store(folder: Path, *, device_table: bool = True, name: str = "RMAdminStore-Local.sqlite") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    with closing(sqlite3.connect(p)) as con:
        con.executescript(PHONE_DDL)
        if device_table:
            con.execute("INSERT INTO ZCOREDEVICE VALUES (1, 1, 1, 1, ?, 'iPhone')", (IPHONE,))
            con.execute("INSERT INTO ZUSAGE VALUES (1, 1, 1, 1, 1, ?)", (_apple("2026-06-09T12:00:00Z"),))
            con.execute("INSERT INTO ZINSTALLEDAPP VALUES (1, 1, 1, 1, 'org.example.puzzle', 'Puzzle')")
        else:
            con.execute("DROP TABLE ZCOREDEVICE")
            con.execute("DROP TABLE ZUSAGE")
            con.execute("DROP TABLE ZINSTALLEDAPP")
        for pk, usage, start in BLOCKS:
            con.execute(
                "INSERT INTO ZUSAGEBLOCK (Z_PK, Z_ENT, Z_OPT, ZDURATIONINMINUTES, ZUSAGE, ZSTARTDATE)"
                " VALUES (?, 1, 1, 60, ?, ?)",
                (pk, usage, _apple(start)),
            )
        con.executemany(
            "INSERT INTO ZUSAGECATEGORY VALUES (?, 1, 1, ?, ?, ?)",
            [(pk, s, b, n) for pk, b, n, s in CATEGORIES],
        )
        con.executemany(
            "INSERT INTO ZUSAGETIMEDITEM VALUES (?, 1, 1, ?, ?, ?, ?)",
            [(pk, s, c, b, d) for pk, c, s, b, d in ITEMS],
        )
        con.execute("INSERT INTO ZUSAGECOUNTEDITEM VALUES (1, 1, 1, 12, 3, 1, 'com.apple.MobileSMS', NULL)")
        con.commit()
    return p


def _lines(store: Path, **kw: Any) -> list[dict[str, Any]]:
    return list(screentime.run(store, **kw))


def _by_raw_id(lines: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {line["payload"]["raw_id"]: line for line in lines}


def _text_of(lines: list[dict[str, Any]]) -> str:
    return json.dumps(lines)


# -- registry and sniff ----------------------------------------------------------------------------


def test_registry_lists_screentime_and_sniff_takes_both_stores(tmp_path):
    assert screentime in adapters.file_adapters()
    assert adapters.named("screentime") is screentime
    assert screentime.sniff(_mac_store(tmp_path / "mac"))
    assert screentime.sniff(_phone_store(tmp_path / "phone"))
    other = tmp_path / "other.sqlite"
    with closing(sqlite3.connect(other)) as con:
        con.execute("CREATE TABLE ZOBJECT (x)")  # a Core Data store with no stream column
    assert not screentime.sniff(other)
    assert not screentime.sniff(tmp_path / "missing.db")
    text = tmp_path / "notes.txt"
    text.write_text("not a store", encoding="utf-8")
    assert not screentime.sniff(text)
    assert not screentime.sniff(tmp_path)


# -- the Mac's sessions ----------------------------------------------------------------------------


def test_every_mac_session_is_an_app_use_line_with_an_event_payload(tmp_path):
    counts: dict[str, int] = {}
    lines = _lines(_mac_store(tmp_path / "mac"), counts=counts, timezone=TZ)
    assert len(lines) == MAC_LINES
    for line in lines:
        assert set(line) == {"at", "end", "tz", "source", "kind", "tier", "payload"}
        assert (line["source"], line["kind"], line["tier"], line["tz"]) == ("screentime", "app-use", 2, TZ)
        p = line["payload"]
        assert p["schema"] == "event/v1" and p["all_day"] is False
        assert p["calendar"] == {"id": "screen-time", "name": "Screen Time"}
        assert line["end"] > line["at"]
        assert set(p["extra"]) >= {"bundle_id", "device", "duration_s", "observed"}
        assert p["extra"]["observed"] == "session"
    assert [line["at"] for line in lines] == sorted(line["at"] for line in lines)
    assert {k: v for k, v in counts.items() if k.startswith("skipped_")} == MAC_SKIPS
    assert counts["no_name"] == 1


def test_a_session_carries_the_app_its_bundle_id_its_span_and_the_device(tmp_path):
    by = _by_raw_id(_lines(_mac_store(tmp_path / "mac"), timezone=TZ))
    safari = by["mac:com.apple.Safari:2026-06-08T07:00:00Z"]
    assert safari["at"] == "2026-06-08T07:00:00Z" and safari["end"] == "2026-06-08T07:25:00Z"
    assert safari["payload"] == {
        "schema": "event/v1",
        "raw_id": "mac:com.apple.Safari:2026-06-08T07:00:00Z",
        "title": "Safari",
        "calendar": {"id": "screen-time", "name": "Screen Time"},
        "all_day": False,
        "extra": {
            "bundle_id": "com.apple.Safari",
            "app": "Safari",
            "device": "mac",
            "duration_s": 1500,
            "observed": "session",
            "stream": "/app/usage",
        },
    }
    puzzle = by["mac:org.example.puzzle:2026-06-08T12:00:00Z"]["payload"]
    assert puzzle["title"] == "org.example.puzzle" and "app" not in puzzle["extra"]
    synced = by[f"{PHONE_DEVICE}:com.apple.mobilesafari:2026-06-08T18:00:00Z"]["payload"]
    assert synced["extra"]["device"] == PHONE_DEVICE and synced["title"] == "Safari"


def test_no_window_title_url_or_other_stream_reaches_a_line(tmp_path):
    lines = _lines(_mac_store(tmp_path / "mac"))
    text = _text_of(lines)
    assert WINDOW_TITLE not in text and URL not in text and "example.org" not in text
    assert "/app/activity" not in text and "/app/inFocus" not in text
    assert all(line["payload"]["extra"]["stream"] == "/app/usage" for line in lines)


def test_since_tier_and_the_folder_the_store_is_in(tmp_path):
    store = _mac_store(tmp_path / "mac")
    lines = _lines(store, since="2026-06-09T00:00:00Z", tier=1)
    assert [line["at"] for line in lines] == ["2026-06-09T07:00:00Z"] and lines[0]["tier"] == 1
    assert len(_lines(store.parent)) == MAC_LINES


def test_a_store_without_a_source_table_still_reads_with_every_session_local(tmp_path):
    store = _mac_store(tmp_path / "mac")
    with closing(sqlite3.connect(store)) as con:
        con.execute("DROP TABLE ZSOURCE")
        con.execute("ALTER TABLE ZOBJECT DROP COLUMN ZUUID")
        con.commit()
    counts: dict[str, int] = {}
    lines = _lines(store, counts=counts)
    assert len(lines) == MAC_LINES
    assert {line["payload"]["extra"]["device"] for line in lines} == {"mac"}


def test_a_store_without_the_columns_it_needs_is_one_clear_error(tmp_path):
    p = tmp_path / "knowledgeC.db"
    with closing(sqlite3.connect(p)) as con:
        con.execute("CREATE TABLE ZOBJECT (Z_PK INTEGER PRIMARY KEY, ZSTREAMNAME VARCHAR)")
    with pytest.raises(ValueError, match=r"knowledgeC\.db"):
        _lines(p)


def test_the_store_is_never_written(tmp_path):
    store = _mac_store(tmp_path / "mac")
    before = store.read_bytes()
    _lines(store)
    assert store.read_bytes() == before
    assert sorted(p.name for p in store.parent.iterdir()) == ["knowledgeC.db"]


# -- the phone's hourly totals ---------------------------------------------------------------------


def test_every_phone_hour_per_app_is_a_line_laid_from_the_top_of_the_hour(tmp_path):
    counts: dict[str, int] = {}
    lines = _lines(_phone_store(tmp_path / "phone"), counts=counts, timezone=TZ)
    assert len(lines) == PHONE_LINES
    assert {k: v for k, v in counts.items() if k.startswith("skipped_")} == PHONE_SKIPS
    assert "no_name" not in counts, "the store's own app table names the puzzle"
    by = _by_raw_id(lines)
    messages = by[f"{IPHONE}:com.apple.MobileSMS:2026-06-08T07:00:00Z"]
    assert messages["at"] == "2026-06-08T07:00:00Z" and messages["end"] == "2026-06-08T07:15:00Z"
    assert messages["payload"] == {
        "schema": "event/v1",
        "raw_id": f"{IPHONE}:com.apple.MobileSMS:2026-06-08T07:00:00Z",
        "title": "Messages",
        "calendar": {"id": "screen-time", "name": "Screen Time"},
        "all_day": False,
        "extra": {
            "bundle_id": "com.apple.MobileSMS",
            "app": "Messages",
            "device": IPHONE,
            "device_name": "iPhone",
            "duration_s": 900,
            "observed": "hourly_total",
            "block_s": 3600,
            "apple_category": "Social",
        },
    }
    puzzle = by[f"{IPHONE}:org.example.puzzle:2026-06-09T07:00:00Z"]["payload"]
    assert puzzle["title"] == "Puzzle" and puzzle["extra"]["app"] == "Puzzle"
    assert puzzle["extra"]["apple_category"] == "Games"
    assert DOMAIN not in _text_of(lines) and "example.org" not in _text_of(lines)


def test_a_phone_store_without_a_device_table_reads_as_one_phone(tmp_path):
    lines = _lines(_phone_store(tmp_path / "phone", device_table=False))
    assert len(lines) == PHONE_LINES
    assert {line["payload"]["extra"]["device"] for line in lines} == {"iphone"}
    assert all("device_name" not in line["payload"]["extra"] for line in lines)
    puzzle = next(line for line in lines if line["payload"]["extra"]["bundle_id"] == "org.example.puzzle")
    assert puzzle["payload"]["title"] == "org.example.puzzle"


def test_a_phone_store_missing_the_items_table_is_one_clear_error(tmp_path):
    store = _phone_store(tmp_path / "phone")
    with closing(sqlite3.connect(store)) as con:
        con.execute("DROP TABLE ZUSAGETIMEDITEM")
        con.commit()
    with pytest.raises(ValueError, match=r"RMAdminStore-Local\.sqlite"):
        _lines(store)


# -- the built-in app table and the policy ----------------------------------------------------------


def test_the_built_in_table_names_and_sorts_common_apps_and_the_policy_overrides_it(tmp_path):
    table = apps.read(tmp_path)  # no file: the built-in table alone
    assert table.name("com.apple.Safari") == "Safari" and table.category("com.apple.Safari") == "browser"
    assert table.category("com.apple.MobileSMS") == "communication"
    assert table.category("com.spotify.client") == "media"
    assert table.category("com.apple.dt.Xcode") == "work"
    assert table.category("org.example.puzzle") == "other" and table.name("org.example.puzzle") is None
    assert table.category("org.example.mailer") == "communication", "a hint in the bundle id"
    assert not (tmp_path / "policy" / "apps.json").exists(), "a reader writes nothing"
    path = apps.apps_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "org.example.puzzle": {"name": "Puzzle", "category": "media"},
                "com.apple.dt.Xcode": "other",
            }
        ),
        encoding="utf-8",
    )
    table = apps.read(tmp_path)
    assert table.name("org.example.puzzle") == "Puzzle" and table.category("org.example.puzzle") == "media"
    assert table.category("com.apple.dt.Xcode") == "other" and table.name("com.apple.dt.Xcode") == "Xcode"
    path.write_text(json.dumps({"org.example.puzzle": "gaming"}), encoding="utf-8")
    with pytest.raises(apps.PolicyError, match=r"apps\.json"):
        apps.read(tmp_path)
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(apps.PolicyError, match=r"apps\.json"):
        apps.read(tmp_path)


# -- through the CLI --------------------------------------------------------------------------------


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook.init(root, TZ)


def test_add_screentime_mac_appends_once_and_show_prints_the_app_and_its_minutes(lb, tmp_path, capsys):
    store = _mac_store(tmp_path / "mac")
    cli.main(["add", "screentime", "--mac", str(store)])
    out = capsys.readouterr().out
    assert f"added {MAC_LINES} lines from screentime" in out
    assert "skipped 1 without a start, 2 with nothing in them, 1 without a bundle id, 1 already seen" in out
    assert "also 1 without an app name" in out
    cli.main(["add", "screentime", "--mac", str(store)])
    assert "added 0 lines" in capsys.readouterr().out
    cli.main(["add", "screentime", "--mac", str(store), "--dry-run"])
    assert f"screentime: 0 lines would be added, {MAC_LINES} already in the record" in capsys.readouterr().out
    cli.main(["show", "2026-06-08"])
    out = capsys.readouterr().out
    assert "app-use" in out and "Safari · 25 min · mac" in out and "Xcode · 2 h 30 min · mac" in out
    assert "org.example.puzzle · 10 min" in out
    assert WINDOW_TITLE not in out and URL not in out
    seq, _head, errors = lb.verify()
    assert (seq, errors) == (MAC_LINES, [])


def test_add_screentime_takes_a_plain_path_and_add_sniffs_a_store(lb, tmp_path, capsys):
    cli.main(["add", "screentime", str(_phone_store(tmp_path / "phone"))])
    assert f"added {PHONE_LINES} lines from screentime" in capsys.readouterr().out
    cli.main(["add", str(_mac_store(tmp_path / "mac"))])
    assert f"added {MAC_LINES} lines from screentime" in capsys.readouterr().out


def test_add_screentime_refuses_a_missing_mac_store_naming_full_disk_access(lb, tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["add", "screentime", "--mac", str(tmp_path / "nowhere" / "knowledgeC.db")])
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "knowledgeC.db" in err and "Full Disk Access" in err


def test_mac_and_backup_go_with_screentime_only_and_not_together(lb, tmp_path, capsys):
    store = _mac_store(tmp_path / "mac")
    with pytest.raises(SystemExit) as e:
        cli.main(["add", "books", "--mac", str(store)])
    assert e.value.code == 2 and "screentime" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        cli.main(["add", "screentime", "--mac", str(store), "--backup", str(tmp_path)])
    assert e.value.code == 2 and "not both" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        cli.main(["add", "screentime"])
    assert e.value.code == 2 and "--mac" in capsys.readouterr().err


def test_add_screentime_backup_copies_the_store_out_of_a_backup_and_runs(lb, tmp_path, capsys):
    from test_import_backup import UDID, _backup

    backup = _backup(tmp_path, sources=("screentime", "ios-notes"))
    cli.main(["add", "screentime", "--backup", str(backup), "--dry-run"])
    out = capsys.readouterr().out
    assert "screentime: RMAdminStore-Local.sqlite (" in out and "nothing written" in out
    inbox = lb.root / "inbox" / f"ios-backup-{UDID}"
    assert not inbox.exists()
    cli.main(["add", "screentime", "--backup", str(backup)])
    out = capsys.readouterr().out
    assert (inbox / "screentime" / "RMAdminStore-Local.sqlite").is_file()
    assert f"added {PHONE_LINES} lines from screentime" in out
    assert "ios-notes" not in out, "only the store asked for is read"
    copies = json.loads((inbox / "copies.json").read_text(encoding="utf-8"))
    assert copies["files"][0]["source"] == "screentime"
    seq, _head, errors = lb.verify()
    assert (seq, errors) == (PHONE_LINES, [])
    cli.main(["add", "screentime", "--backup", str(backup)])
    assert "added 0 lines" in capsys.readouterr().out


def test_add_screentime_backup_says_when_the_backup_has_no_store(lb, tmp_path, capsys):
    from test_import_backup import _backup

    backup = _backup(tmp_path, sources=("ios-notes",))
    with pytest.raises(SystemExit) as e:
        cli.main(["add", "screentime", "--backup", str(backup)])
    assert e.value.code == 1
    assert "RMAdminStore-Local.sqlite not found" in capsys.readouterr().out
    with pytest.raises(SystemExit) as e:
        cli.main(["add", "screentime", "--backup", str(tmp_path / "not-a-backup")])
    assert e.value.code == 2 and "Manifest.db" in capsys.readouterr().err


def test_a_disabled_source_is_skipped_either_way(lb, tmp_path, capsys):
    from logbook.core import policy

    policy.import_path(lb.root).write_text(
        json.dumps({"disabled": [{"source": "screentime", "reason": "not this year"}]}), encoding="utf-8"
    )
    cli.main(["add", "screentime", "--mac", str(_mac_store(tmp_path / "mac"))])
    assert "screentime: disabled (not this year); skipped" in capsys.readouterr().out
    assert lb.meta["seq"] == 0
