"""Apple Reminders Data-*.sqlite → task/v1 (RFC 0016): one line per reminder, every store in the folder."""

from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from pathlib import Path

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters
from logbook.adapters import apple_reminders, ios_notes, whatsapp
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}

DDL = """
CREATE TABLE ZREMCDBASELIST (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZMARKEDFORDELETION INTEGER, ZISGROUP INTEGER,
    ZPARENTLIST INTEGER, ZNAME VARCHAR, ZIDENTIFIER BLOB, ZCKIDENTIFIER VARCHAR
);
CREATE TABLE ZREMCDREMINDER (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZALLDAY INTEGER, ZCOMPLETED INTEGER,
    ZFLAGGED INTEGER, ZMARKEDFORDELETION INTEGER, ZPRIORITY INTEGER, ZLIST INTEGER, ZPARENTREMINDER INTEGER,
    ZCOMPLETIONDATE TIMESTAMP, ZCREATIONDATE TIMESTAMP, ZDISPLAYDATEDATE TIMESTAMP, ZDUEDATE TIMESTAMP,
    ZLASTMODIFIEDDATE TIMESTAMP, ZSTARTDATE TIMESTAMP, ZCKIDENTIFIER VARCHAR, ZNOTES VARCHAR,
    ZTIMEZONE VARCHAR, ZTITLE VARCHAR, ZIDENTIFIER BLOB, ZTITLEDOCUMENT BLOB
);
"""

# -- the fixture: synthetic, nobody in it exists ------------------------------------------

T0 = 790_000_000  # 2026-01-13T12:26:40Z in Apple-epoch seconds
DAY = 790_387_200  # 2026-01-18T00:00:00Z: an all-day due date is midnight UTC of its day
BOAT, HOME, GROUP, GONE = 1, 2, 3, 4
OPEN, DONE, ALLDAY, FLOATING, DELETED, SUBTASK, UNTITLED, UNDATED = 1, 2, 3, 4, 5, 6, 7, 8
UUIDS = {
    pk: uuid.UUID(f"0000{pk:04d}-0000-4000-8000-00000000000{pk}")
    for pk in (OPEN, DONE, ALLDAY, FLOATING, DELETED, SUBTASK, UNTITLED, UNDATED)
}
LIST_UUIDS = {pk: uuid.UUID(f"1111{pk:04d}-0000-4000-8000-000000000000") for pk in (BOAT, HOME, GROUP, GONE)}

# (Z_PK, ZMARKEDFORDELETION, ZISGROUP, ZPARENTLIST, ZNAME)
LISTS = [
    (BOAT, 0, 0, GROUP, "Boat"),
    (HOME, 0, 0, None, "Home"),
    (GROUP, 0, 1, None, "Projects"),
    (GONE, 1, 0, None, "Old"),
]
# per reminder: (Z_PK, ZALLDAY, ZCOMPLETED, ZFLAGGED, ZMARKEDFORDELETION, ZPRIORITY, ZLIST,
#   ZPARENTREMINDER, ZCOMPLETIONDATE, ZCREATIONDATE, ZDISPLAYDATEDATE, ZDUEDATE, ZLASTMODIFIEDDATE,
#   ZSTARTDATE, ZNOTES, ZTIMEZONE, ZTITLE)
REMINDERS = [
    (OPEN, 0, 0, 1, 0, 1, BOAT, None, None, T0, T0 + 86400, T0 + 86400, T0 + 5.7, None,
     "Ask the yard first", "Europe/Oslo", "Check the bilge pump"),
    (DONE, 0, 1, 0, 0, 0, HOME, None, T0 + 7200.4, T0 + 10, None, None, T0 + 7200.4, None,
     None, None, "Buy milk"),
    (ALLDAY, 1, 0, 0, 0, 0, BOAT, None, None, T0 + 20, DAY - 3600, DAY, T0 + 20, None,
     None, None, "Renew the mooring"),
    (FLOATING, 0, 0, 0, 0, 0, HOME, None, None, T0 + 30, T0 + 90000, T0 + 93600, T0 + 30, None,
     None, None, "Call the dentist"),
    (DELETED, 0, 1, 0, 1, 0, GONE, None, T0 + 50, T0 + 40, None, None, T0 + 50, None,
     None, None, "Sold the dinghy"),
    (SUBTASK, 0, 0, 0, 0, 0, BOAT, OPEN, None, T0 + 60, None, None, T0 + 60, None,
     None, None, "Order the spare impeller"),
    (UNTITLED, 0, 0, 0, 0, 0, HOME, None, None, T0 + 70, None, None, T0 + 70, None,
     None, None, None),
    (UNDATED, 0, 0, 0, 0, 0, HOME, None, None, None, None, None, T0 + 80, None,
     None, None, "No creation date"),
]  # fmt: skip


def _store(folder: Path, name: str = "Data-AAAAAAAA-0000-4000-8000-000000000002.sqlite") -> Path:
    """One Reminders store under <folder>/Container_v1/Stores/, as the phone lays it out."""
    p = folder / "Container_v1" / "Stores" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    try:
        con.executescript(DDL)
        con.executemany(
            "INSERT INTO ZREMCDBASELIST VALUES (?,3,1,?,?,?,?,?,?)",
            [(pk, deleted, group, parent, name, LIST_UUIDS[pk].bytes, str(LIST_UUIDS[pk]).upper())
             for pk, deleted, group, parent, name in LISTS],
        )  # fmt: skip
        con.executemany(
            "INSERT INTO ZREMCDREMINDER VALUES (?,39,1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    r[0],
                    *r[1:14],
                    str(UUIDS[r[0]]).upper(),
                    r[14],
                    r[15],
                    r[16],
                    UUIDS[r[0]].bytes,
                    b"\x00opaque",
                )
                for r in REMINDERS
            ],
        )
        con.commit()
    finally:
        con.close()
    return p


def _second_store(folder: Path) -> Path:
    """A second, local store beside the first: one open reminder in a list of its own, no CloudKit id."""
    p = folder / "Container_v1" / "Stores" / "Data-AAAAAAAA-0000-4000-8000-000000000001.sqlite"
    con = sqlite3.connect(p)
    try:
        con.executescript(DDL)
        local_list = uuid.UUID("22220001-0000-4000-8000-000000000000")
        local = uuid.UUID("00000099-0000-4000-8000-000000000099")
        con.execute("INSERT INTO ZREMCDBASELIST VALUES (1,3,1,0,0,NULL,'Local',?,NULL)", (local_list.bytes,))
        con.execute(
            "INSERT INTO ZREMCDREMINDER VALUES (1,39,1,0,0,0,0,0,1,NULL,NULL,?,NULL,NULL,?,NULL,NULL,NULL,"
            "NULL,'Stays on this phone',?,NULL)",
            (T0 + 500, T0 + 500, local.bytes),
        )
        con.commit()
    finally:
        con.close()
    return p


def _by_pk(lines: list[dict]) -> dict[int, dict]:
    return {line["payload"]["extra"]["pk"]: line for line in lines}


# -- registry and sniff -------------------------------------------------------------------


def test_registry_lists_apple_reminders():
    assert "apple-reminders" in [a.NAME for a in adapters.all_adapters()]
    assert adapters.named("reminders") is not None and adapters.named("reminders").NAME == "apple-reminders"


def test_registry_find_returns_apple_reminders_for_a_store_and_for_its_folder(tmp_path):
    p = _store(tmp_path)
    assert adapters.find(p) is not None and adapters.find(p).NAME == "apple-reminders"
    assert adapters.find(p.parent) is not None and adapters.find(p.parent).NAME == "apple-reminders"


def test_sniff_rejects_other_stores_and_junk(tmp_path):
    assert apple_reminders.sniff(tmp_path) is False  # an empty folder
    assert apple_reminders.sniff(tmp_path / "nope.sqlite") is False
    p = tmp_path / "other.sqlite"
    con = sqlite3.connect(p)
    try:
        con.executescript("CREATE TABLE ZREMCDBASELIST (Z_PK INTEGER);")  # half of it
    finally:
        con.close()
    assert apple_reminders.sniff(p) is False
    (tmp_path / "text.sqlite").write_text("SQLite format 3\0 but not really", encoding="utf-8")
    assert apple_reminders.sniff(tmp_path / "text.sqlite") is False


def test_other_adapters_reject_the_reminders_store(tmp_path):
    p = _store(tmp_path)
    assert ios_notes.sniff(p) is False and whatsapp.sniff(p) is False


def test_sniff_and_run_never_touch_the_source(tmp_path):
    p = _store(tmp_path)
    before = p.read_bytes()
    assert apple_reminders.sniff(p) is True
    list(apple_reminders.run(p))
    assert p.read_bytes() == before
    assert [q.name for q in p.parent.iterdir()] == [p.name]  # no -journal, -wal, -shm


# -- run: envelope ------------------------------------------------------------------------


def test_run_yields_task_lines_at_the_creation_time(tmp_path):
    lines = list(apple_reminders.run(_store(tmp_path)))
    assert len(lines) == 6  # open, done, all-day, floating, deleted, subtask; untitled and undated skipped
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["end"] is None and line["tz"] is None
        assert line["source"] == "apple-reminders" and line["kind"] == "task" and line["tier"] == 2
        assert line["payload"]["schema"] == "task/v1" and "source" not in line["payload"]
    assert _by_pk(lines)[OPEN]["at"] == "2026-01-13T12:26:40Z"


def test_run_streams_in_row_order_and_honours_since(tmp_path):
    p = _store(tmp_path)
    assert list(_by_pk(list(apple_reminders.run(p)))) == [OPEN, DONE, ALLDAY, FLOATING, DELETED, SUBTASK]
    assert list(_by_pk(list(apple_reminders.run(p, since="2026-01-13T12:27:10Z")))) == [
        FLOATING,
        DELETED,
        SUBTASK,
    ]


# -- run: the task fields -----------------------------------------------------------------


def test_run_open_reminder_has_title_status_due_list_and_notes(tmp_path):
    p = _by_pk(list(apple_reminders.run(_store(tmp_path))))[OPEN]["payload"]
    assert p["title"] == "Check the bilge pump"
    assert p["status"] == "open" and "completed_at" not in p
    assert p["due"] == "2026-01-14T12:26:40Z"  # a timed reminder: the instant
    assert p["list"] == "Boat"
    assert p["notes"] == "Ask the yard first"
    assert p["priority"] == "high" and p["extra"]["priority_number"] == 1
    assert p["modified_at"] == "2026-01-13T12:26:45Z"
    assert p["extra"]["list_group"] == "Projects"
    assert p["extra"]["flagged"] is True
    assert p["extra"]["timezone"] == "Europe/Oslo"
    assert "deleted" not in p["extra"] and "parent" not in p


def test_run_completed_reminder_has_completed_at(tmp_path):
    p = _by_pk(list(apple_reminders.run(_store(tmp_path))))[DONE]["payload"]
    assert p["status"] == "done" and p["completed_at"] == "2026-01-13T14:26:40Z"
    assert (
        "due" not in p and "notes" not in p and "flagged" not in p["extra"] and "priority" not in p["extra"]
    )
    assert p["list"] == "Home" and "list_group" not in p["extra"]


def test_run_all_day_due_is_a_date(tmp_path):
    p = _by_pk(list(apple_reminders.run(_store(tmp_path))))[ALLDAY]["payload"]
    assert p["due"] == "2026-01-18"  # ZDUEDATE is midnight UTC of the day; the display date is local midnight


def test_run_floating_timed_due_is_the_display_instant(tmp_path):
    """A timed reminder without a zone keeps its wall clock in ZDUEDATE and the instant the phone
    showed it at in ZDISPLAYDATEDATE; the instant is the due."""
    p = _by_pk(list(apple_reminders.run(_store(tmp_path))))[FLOATING]["payload"]
    assert p["due"] == "2026-01-14T13:26:40Z"  # T0 + 90000, not T0 + 93600


def test_priority_maps_apples_nine_levels_to_three_words():
    assert [apple_reminders._priority(n) for n in range(10)] == [
        None, "high", "high", "high", "high", "medium", "low", "low", "low", "low"
    ]  # fmt: skip
    assert apple_reminders._priority(None) is None and apple_reminders._priority(True) is None


def test_run_raw_id_is_the_uuid_at_modification_time(tmp_path):
    lines = _by_pk(list(apple_reminders.run(_store(tmp_path))))
    assert lines[OPEN]["payload"]["raw_id"] == f"reminders:{UUIDS[OPEN]}@2026-01-13T12:26:45Z"
    assert lines[DONE]["payload"]["raw_id"] == f"reminders:{UUIDS[DONE]}@2026-01-13T14:26:40Z"
    assert lines[OPEN]["payload"]["extra"]["identifier"] == str(UUIDS[OPEN])


def test_run_deleted_reminder_is_a_line_flagged_and_counted(tmp_path):
    counts: dict[str, int] = {}
    p = _by_pk(list(apple_reminders.run(_store(tmp_path), counts=counts)))[DELETED]["payload"]
    assert p["title"] == "Sold the dinghy" and p["extra"]["deleted"] is True
    assert p["list"] == "Old" and p["extra"]["list_deleted"] is True
    assert counts["deleted"] == 1


def test_run_subtask_names_its_parent(tmp_path):
    p = _by_pk(list(apple_reminders.run(_store(tmp_path))))[SUBTASK]["payload"]
    assert p["parent"] == f"reminders:{UUIDS[OPEN]}"  # the parent's raw_id without its @ suffix


def test_run_skips_and_counts_untitled_and_undated(tmp_path):
    counts: dict[str, int] = {}
    lines = _by_pk(list(apple_reminders.run(_store(tmp_path), counts=counts)))
    assert UNTITLED not in lines and UNDATED not in lines
    assert counts["skipped_no_title"] == 1 and counts["skipped_bad_date"] == 1


# -- run: a folder of stores --------------------------------------------------------------


def test_run_on_the_folder_reads_every_store(tmp_path):
    first = _store(tmp_path)
    _second_store(tmp_path)
    lines = list(apple_reminders.run(first.parent))
    assert len(lines) == 7
    local = next(line for line in lines if line["payload"]["title"] == "Stays on this phone")
    assert local["payload"]["list"] == "Local"
    assert local["payload"]["raw_id"] == "reminders:00000099-0000-4000-8000-000000000099@2026-01-13T12:35:00Z"
    assert local["payload"]["extra"]["store"] == "Data-AAAAAAAA-0000-4000-8000-000000000001.sqlite"
    # the container folder works too, and so does one file alone
    assert len(list(apple_reminders.run(tmp_path))) == 7
    assert len(list(apple_reminders.run(first))) == 6


# -- through the logbook -------------------------------------------------------------------


def test_add_dedupes_on_a_second_import(tmp_path, monkeypatch):
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    lb = Logbook.init(root, "Europe/Oslo")
    store = _store(tmp_path / "phone")
    assert lb.append_many(apple_reminders.run(store)) == 6
    assert lb.append_many(apple_reminders.run(store)) == 0
    seq, _head, errors = lb.verify()
    assert (seq, errors) == (6, [])
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
    line = next(line for line in lb.lines() if line["payload"]["title"] == "Buy milk")
    assert line["tz"] == "Europe/Oslo" and line["payload"]["status"] == "done"


def test_rfc3339_converts_apple_epoch_seconds_and_rejects_the_rest():
    assert apple_reminders._rfc3339(T0) == "2026-01-13T12:26:40Z"
    assert apple_reminders._rfc3339(T0 + 5.7) == "2026-01-13T12:26:45Z"
    for value in (None, "", True, 1.0):  # 1.0 is 2001-01-01, a placeholder, not a date
        assert apple_reminders._rfc3339(value) is None
