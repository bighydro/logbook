"""`logbook inbox list` and `logbook inbox clean`: what was dropped in inbox/, which import consumed
it, whether every line it produced is in the record, and moving (or deleting) only what is.
Every input here is a synthetic fixture; nobody in them exists."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path, PurePosixPath

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_import_backup import UDID, _backup

from logbook import cli, inbox
from logbook.store import Logbook, now_utc

ROOT = Path(__file__).resolve().parents[1]
DAWARICH = ROOT / "tests" / "fixtures" / "dawarich" / "export.json"
SHAZAM = ROOT / "tests" / "fixtures" / "shazam" / "shazamlibrary.csv"


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    monkeypatch.setenv("LOGBOOK_DIAL_PREFIX", "47")
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook.init(root, "Europe/Oslo")


def _drop(lb: Logbook, fixture: Path, *parts: str) -> Path:
    """A copy of `fixture` under inbox/<parts>, as the owner would drop it."""
    target = lb.root.joinpath("inbox", *parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(fixture, target)
    return target


def _ledger(lb: Logbook) -> list[dict[str, object]]:
    path = lb.root / "state" / "imports.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _rows(out: str) -> dict[str, str]:
    """The list's file rows, by the path they start with."""
    rows: dict[str, str] = {}
    for line in out.splitlines():
        if line.startswith("  "):
            path, _, rest = line.strip().partition("  ")
            rows[path] = rest.strip()
    return rows


# -- the ledger -----------------------------------------------------------------------


def test_add_records_the_import_and_says_the_input_can_be_cleaned(lb: Logbook, capsys):
    dropped = _drop(lb, DAWARICH, "dawarich", "export.json")
    cli.main(["add", str(dropped)])
    out = capsys.readouterr().out
    entries = _ledger(lb)
    assert len(entries) == 1
    e = entries[0]
    assert e["input"] == "inbox/dawarich/export.json"
    assert e["adapter"] == "dawarich"
    assert e["produced"] == 40 and e["appended"] == 40
    assert (e["seq_first"], e["seq_last"]) == (1, 40)
    assert e["last_hash"] == lb.meta["head"]
    assert e["owner_id"] == lb.meta["owner_id"]
    assert e["bytes"] == dropped.stat().st_size
    last = out.strip().splitlines()[-1]
    assert "export.json" in last and "can be cleaned" in last and "logbook inbox clean" in last


def test_add_again_records_a_second_run_that_appended_nothing(lb: Logbook, capsys):
    dropped = _drop(lb, DAWARICH, "export.json")
    cli.main(["add", str(dropped)])
    cli.main(["add", str(dropped)])
    first, second = _ledger(lb)
    assert second["produced"] == 40 and second["appended"] == 0
    assert second["seq_first"] is None and second["seq_last"] is None and second["last_hash"] is None
    assert first["last_hash"] == lb.meta["head"]


def test_add_outside_the_inbox_records_the_absolute_path_and_says_it_can_go(lb: Logbook, tmp_path, capsys):
    elsewhere = tmp_path / "Downloads" / "export.json"
    elsewhere.parent.mkdir()
    shutil.copy(DAWARICH, elsewhere)
    cli.main(["add", str(elsewhere)])
    out = capsys.readouterr().out
    (e,) = _ledger(lb)
    assert PurePosixPath(str(e["input"])).is_absolute() or Path(str(e["input"])).is_absolute()
    assert Path(str(e["input"])) == elsewhere
    last = out.strip().splitlines()[-1]
    assert "export.json" in last and "imported in full" in last


def test_add_a_sentence_records_nothing(lb: Logbook, capsys):
    cli.main(["add", "coffee", "with", "nobody"])
    assert _ledger(lb) == []
    assert "clean" not in capsys.readouterr().out


def test_add_a_folder_records_one_run_per_file(lb: Logbook, capsys):
    _drop(lb, DAWARICH, "drop", "a.json")
    _drop(lb, SHAZAM, "drop", "shazamlibrary.csv")
    cli.main(["add", str(lb.root / "inbox" / "drop")])
    out = capsys.readouterr().out
    inputs = sorted(str(e["input"]) for e in _ledger(lb))
    assert inputs == ["inbox/drop/a.json", "inbox/drop/shazamlibrary.csv"]
    last = out.strip().splitlines()[-1]
    assert "2 files" in last and "can be cleaned" in last


# -- list -----------------------------------------------------------------------------


def test_inbox_list_shows_every_file_with_size_and_its_import(lb: Logbook, capsys):
    dropped = _drop(lb, DAWARICH, "dawarich", "export.json")
    cli.main(["add", str(dropped)])
    waiting = _drop(lb, SHAZAM, "shazamlibrary.csv")
    capsys.readouterr()
    cli.main(["inbox", "list"])
    out = capsys.readouterr().out
    rows = _rows(out)
    assert set(rows) == {"dawarich/export.json", "shazamlibrary.csv"}
    assert inbox.size_text(dropped.stat().st_size) in rows["dawarich/export.json"]
    assert "imported by dawarich" in rows["dawarich/export.json"]
    assert "40 lines, all in the record" in rows["dawarich/export.json"]
    assert inbox.size_text(waiting.stat().st_size) in rows["shazamlibrary.csv"]
    assert rows["shazamlibrary.csv"].endswith("not imported")
    assert out.splitlines()[0].startswith("inbox/ (2 files, ")
    summary = out.strip().splitlines()[-1]
    assert f"{inbox.size_text(dropped.stat().st_size)} in 1 file can be cleaned" in summary
    assert "logbook inbox clean --to DIR" in summary


def test_inbox_list_json_carries_the_same(lb: Logbook, capsys):
    dropped = _drop(lb, DAWARICH, "export.json")
    cli.main(["add", str(dropped)])
    _drop(lb, SHAZAM, "later", "shazamlibrary.csv")
    capsys.readouterr()
    cli.main(["inbox", "list", "--json"])
    data = json.loads(capsys.readouterr().out)
    by_path = {f["path"]: f for f in data["files"]}
    assert by_path["export.json"]["ready"] is True
    assert by_path["export.json"]["adapter"] == "dawarich"
    assert by_path["export.json"]["bytes"] == dropped.stat().st_size
    assert by_path["later/shazamlibrary.csv"]["ready"] is False
    assert by_path["later/shazamlibrary.csv"]["adapter"] is None
    assert data["ready_bytes"] == dropped.stat().st_size
    assert data["ready_files"] == 1


def test_inbox_list_flags_a_file_changed_since_its_import(lb: Logbook, capsys):
    dropped = _drop(lb, DAWARICH, "export.json")
    cli.main(["add", str(dropped)])
    with dropped.open("a", encoding="utf-8") as fh:
        fh.write("\n\n")  # a newer export dropped over the old one
    capsys.readouterr()
    cli.main(["inbox", "list"])
    out = capsys.readouterr().out
    assert "changed since dawarich read it" in _rows(out)["export.json"]
    assert "nothing can be cleaned" in out.strip().splitlines()[-1]


def test_inbox_list_flags_an_import_whose_lines_are_not_in_the_record(lb: Logbook, capsys):
    dropped = _drop(lb, DAWARICH, "export.json")
    cli.main(["add", str(dropped)])
    (e,) = _ledger(lb)
    e["seq_last"] = 41  # a line the record does not have
    (lb.root / "state" / "imports.jsonl").write_text(json.dumps(e) + "\n", encoding="utf-8")
    capsys.readouterr()
    cli.main(["inbox", "list"])
    assert "line #41 is not in the record" in _rows(capsys.readouterr().out)["export.json"]


def test_inbox_list_flags_an_import_into_another_record(lb: Logbook, capsys):
    dropped = _drop(lb, DAWARICH, "export.json")
    cli.main(["add", str(dropped)])
    (e,) = _ledger(lb)
    e["owner_id"] = "00000000-0000-7000-8000-000000000000"
    (lb.root / "state" / "imports.jsonl").write_text(json.dumps(e) + "\n", encoding="utf-8")
    capsys.readouterr()
    cli.main(["inbox", "list"])
    assert "into another record" in _rows(capsys.readouterr().out)["export.json"]


def test_inbox_list_takes_a_store_siblings_with_it(lb: Logbook, capsys):
    """A -wal or -shm beside an imported store was read with it (SQLite's write-ahead log and its
    index): consumed by the same import, by name."""
    store = lb.root / "inbox" / "phone" / "ChatStorage.sqlite"
    store.parent.mkdir(parents=True)
    store.write_bytes(b"not really a store")
    (store.parent / "ChatStorage.sqlite-wal").write_bytes(b"wal")
    (store.parent / "ChatStorage.sqlite-shm").write_bytes(b"shm")
    (store.parent / "Other.sqlite-wal").write_bytes(b"orphan")
    inbox.record(lb.root, _import(lb, "inbox/phone/ChatStorage.sqlite", store))
    cli.main(["inbox", "list"])
    rows = _rows(capsys.readouterr().out)
    assert "imported by whatsapp" in rows["phone/ChatStorage.sqlite"]
    assert "with ChatStorage.sqlite" in rows["phone/ChatStorage.sqlite-wal"]
    assert "with ChatStorage.sqlite" in rows["phone/ChatStorage.sqlite-shm"]
    assert rows["phone/Other.sqlite-wal"].endswith("not imported")


def test_inbox_list_without_an_inbox_folder_says_so(lb: Logbook, capsys):
    shutil.rmtree(lb.root / "inbox")
    cli.main(["inbox", "list"])
    out = capsys.readouterr().out
    assert "no inbox/ folder" in out


def test_inbox_list_ignores_hidden_files(lb: Logbook, capsys):
    (lb.root / "inbox" / ".DS_Store").write_bytes(b"\0")
    cli.main(["inbox", "list"])
    out = capsys.readouterr().out
    assert ".DS_Store" not in out and "inbox/ is empty" in out


def _import(lb: Logbook, relative: str, path: Path, adapter: str = "whatsapp") -> inbox.Import:
    return inbox.Import(
        at=now_utc(),  # after the files were written, as a real run is
        input=relative,
        adapter=adapter,
        produced=3,
        appended=0,
        seq_first=None,
        seq_last=None,
        last_hash=None,
        owner_id=str(lb.meta["owner_id"]),
        bytes=inbox.input_bytes(path),
    )


# -- clean ----------------------------------------------------------------------------


def test_inbox_clean_moves_what_is_imported_and_refuses_the_rest(lb: Logbook, tmp_path, capsys):
    dropped = _drop(lb, DAWARICH, "dawarich", "export.json")
    cli.main(["add", str(dropped)])
    waiting = _drop(lb, SHAZAM, "shazamlibrary.csv")
    disk = tmp_path / "disk" / "logbook-inbox"
    capsys.readouterr()
    cli.main(["inbox", "clean", "--to", str(disk)])
    out = capsys.readouterr().out
    moved = disk / "dawarich" / "export.json"
    assert moved.is_file() and moved.read_bytes() == DAWARICH.read_bytes()
    assert not dropped.exists() and not dropped.parent.exists()  # the emptied folder goes too
    assert waiting.is_file()  # refused: nothing imported it
    assert "kept shazamlibrary.csv: not imported" in out
    assert f"freed {inbox.size_text(DAWARICH.stat().st_size)}" in out
    assert "1 file" in out and "moved" in out


def test_inbox_clean_refuses_a_changed_file(lb: Logbook, tmp_path, capsys):
    dropped = _drop(lb, DAWARICH, "export.json")
    cli.main(["add", str(dropped)])
    dropped.write_bytes(dropped.read_bytes() + b"\n")
    capsys.readouterr()
    cli.main(["inbox", "clean", "--to", str(tmp_path / "disk")])
    out = capsys.readouterr().out
    assert dropped.is_file() and not (tmp_path / "disk" / "export.json").exists()
    assert "kept export.json: changed since dawarich read it" in out
    assert "freed 0 bytes" in out


def test_inbox_clean_dry_run_moves_nothing(lb: Logbook, tmp_path, capsys):
    dropped = _drop(lb, DAWARICH, "export.json")
    cli.main(["add", str(dropped)])
    capsys.readouterr()
    cli.main(["inbox", "clean", "--to", str(tmp_path / "disk"), "--dry-run"])
    out = capsys.readouterr().out
    assert dropped.is_file() and not (tmp_path / "disk").exists()
    assert "would move export.json" in out
    assert f"would free {inbox.size_text(dropped.stat().st_size)}" in out


def test_inbox_clean_delete_removes_imported_inputs(lb: Logbook, capsys):
    dropped = _drop(lb, DAWARICH, "export.json")
    cli.main(["add", str(dropped)])
    waiting = _drop(lb, SHAZAM, "shazamlibrary.csv")
    capsys.readouterr()
    cli.main(["inbox", "clean", "--delete"])
    out = capsys.readouterr().out
    assert not dropped.exists() and waiting.is_file()
    assert "deleted export.json" in out
    assert f"freed {inbox.size_text(DAWARICH.stat().st_size)}" in out


def test_inbox_clean_needs_a_destination_or_delete(lb: Logbook, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["inbox", "clean"])
    assert e.value.code == 2
    assert "--to DIR or --delete" in capsys.readouterr().err


def test_inbox_clean_refuses_a_destination_inside_the_inbox(lb: Logbook, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["inbox", "clean", "--to", str(lb.root / "inbox" / "done")])
    assert e.value.code == 2
    assert "inside inbox/" in capsys.readouterr().err


def test_inbox_clean_never_overwrites_at_the_destination(lb: Logbook, tmp_path, capsys):
    dropped = _drop(lb, DAWARICH, "export.json")
    cli.main(["add", str(dropped)])
    disk = tmp_path / "disk"
    disk.mkdir()
    (disk / "export.json").write_bytes(b"something else")
    capsys.readouterr()
    cli.main(["inbox", "clean", "--to", str(disk)])
    out = capsys.readouterr().out
    assert dropped.is_file() and (disk / "export.json").read_bytes() == b"something else"
    assert "kept export.json: already at" in out


# -- import-backup ----------------------------------------------------------------------


def test_import_backup_records_each_source_folder_and_the_backup_can_be_cleaned(lb, tmp_path, capsys):
    backup = _backup(tmp_path, sources=("ios-contacts", "whatsapp"))
    cli.main(["import-backup", str(backup), "--only", "contacts,whatsapp"])
    out = capsys.readouterr().out
    inputs = sorted(str(e["input"]) for e in _ledger(lb))
    assert inputs == [f"inbox/ios-backup-{UDID}/ios-contacts", f"inbox/ios-backup-{UDID}/whatsapp"]
    last = out.strip().splitlines()[-1]
    assert "2 sources" in last and f"ios-backup-{UDID}" in last and "can be cleaned" in last
    cli.main(["inbox", "list"])
    rows = _rows(capsys.readouterr().out)
    folder = f"ios-backup-{UDID}"
    assert "imported by ios-contacts" in rows[f"{folder}/ios-contacts/AddressBook.sqlitedb"]
    assert "imported by whatsapp" in rows[f"{folder}/whatsapp/ChatStorage.sqlite"]
    assert "imported by whatsapp" in rows[f"{folder}/whatsapp/ChatStorage.sqlite-shm"]
    assert (
        "bookkeeping of the backup import; every file beside it is imported" in rows[f"{folder}/copies.json"]
    )
    assert all(not r.endswith("not imported") for r in rows.values()), rows
    disk = tmp_path / "disk"
    cli.main(["inbox", "clean", "--to", str(disk)])
    out = capsys.readouterr().out
    assert not (lb.root / "inbox" / folder).exists()
    assert (disk / folder / "copies.json").is_file()
    assert (disk / folder / "whatsapp" / "ChatStorage.sqlite").is_file()
    assert "kept" not in out


def test_import_backup_bookkeeping_stays_while_a_source_is_not_imported(lb, tmp_path, capsys):
    backup = _backup(tmp_path, sources=("ios-contacts", "whatsapp"))
    cli.main(["import-backup", str(backup), "--only", "contacts"])
    folder = lb.root / "inbox" / f"ios-backup-{UDID}"
    (folder / "whatsapp").mkdir()
    (folder / "whatsapp" / "ChatStorage.sqlite").write_bytes(b"copied by hand, never imported")
    capsys.readouterr()
    cli.main(["inbox", "list"])
    rows = _rows(capsys.readouterr().out)
    assert "1 file beside it is not" in rows[f"ios-backup-{UDID}/copies.json"]
    cli.main(["inbox", "clean", "--delete"])
    assert (folder / "copies.json").is_file()
    assert (folder / "whatsapp" / "ChatStorage.sqlite").is_file()
    assert not (folder / "ios-contacts").exists()


# -- sizes ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("n", "text"),
    [
        (0, "0 bytes"),
        (1, "1 byte"),
        (999, "999 bytes"),
        (1000, "1.0 kB"),
        (551, "551 bytes"),
        (41_532, "41.5 kB"),
    ],
)
def test_size_text_small(n: int, text: str):
    assert inbox.size_text(n) == text


@pytest.mark.parametrize(
    ("n", "text"), [(1_260_000, "1.3 MB"), (812_300_000, "812.3 MB"), (1_200_000_000, "1.2 GB")]
)
def test_size_text_large(n: int, text: str):
    assert inbox.size_text(n) == text
