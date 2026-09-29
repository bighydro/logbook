"""`logbook import-backup <folder>`: an unencrypted iOS backup in, every adapter run on copies."""

from __future__ import annotations

import hashlib
import plistlib
import sqlite3
import sys
from pathlib import Path, PurePosixPath

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_imessage import _store as _sms_store
from test_ios_calendar import _calendar
from test_ios_contacts import _address_book
from test_ios_notes import _store as _note_store
from test_whatsapp import _store as _chat_store
from test_whatsapp_contacts import _contacts

from logbook import cli, ios_backup
from logbook.store import Logbook

UDID = "00008030-000A1B2C3D4E5F60"
WHATSAPP = "AppDomainGroup-group.net.whatsapp.WhatsApp.shared"
NOTES = "AppDomainGroup-group.com.apple.notes"
ALL = ("ios-contacts", "whatsapp-contacts", "whatsapp", "imessage", "ios-calendar", "ios-notes")
LINES = {  # with LOGBOOK_DIAL_PREFIX=47 (the `lb` fixture): two numbers without a country code normalise
    "ios-contacts": 7,
    "whatsapp-contacts": 4,
    "whatsapp": 14,
    "imessage": 13,
    "ios-calendar": 7,
    "ios-notes": 4,
}
STORES = {
    "ios-contacts": "AddressBook.sqlitedb",
    "whatsapp-contacts": "ContactsV2.sqlite",
    "whatsapp": "ChatStorage.sqlite",
    "imessage": "sms.db",
    "ios-calendar": "Calendar.sqlitedb",
    "ios-notes": "NoteStore.sqlite",
}


def _file_id(domain: str, relative_path: str) -> str:
    """How a backup names its files: the SHA-1 of `<domain>-<relativePath>`."""
    return hashlib.sha1(f"{domain}-{relative_path}".encode()).hexdigest()


def _put(
    backup: Path, rows: list[tuple[str, str, str, int]], domain: str, rel: str, source: Path | None
) -> None:
    """One Manifest.db row, and the file at <fileID[:2]>/<fileID> when `source` is given."""
    fid = _file_id(domain, rel)
    rows.append((fid, domain, rel, 1 if source is not None else 2))
    if source is not None:
        target = backup / fid[:2] / fid
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())


def _put_tree(backup: Path, rows: list, domain: str, prefix: str, folder: Path) -> int:
    """Every file under `folder` as `<prefix>/<relative posix path>`; returns how many."""
    n = 0
    for f in sorted(folder.rglob("*")):
        rel = PurePosixPath(prefix, *f.relative_to(folder).parts).as_posix()
        _put(backup, rows, domain, rel, f if f.is_file() else None)
        n += f.is_file()
    return n


def _backup(
    tmp_path: Path, *, sources: tuple[str, ...] = ALL, encrypted: bool = False, lockdown: bool = True
) -> Path:
    """A tiny fake backup folder: Manifest.db, Manifest.plist, the files at their fileID paths.
    Every store comes from the adapters' own synthetic fixture builders; nobody in them exists."""
    stage = tmp_path / "stage"
    backup = tmp_path / "backup"
    backup.mkdir()
    rows: list[tuple[str, str, str, int]] = []
    _put(backup, rows, "HomeDomain", "Library", None)
    _put(backup, rows, "HomeDomain", "Library/Preferences/com.apple.example.plist", _blob(stage, b"<plist/>"))
    if "ios-contacts" in sources:
        _put(
            backup,
            rows,
            "HomeDomain",
            "Library/AddressBook/AddressBook.sqlitedb",
            _address_book(_dir(stage, "ab")),
        )
    if "whatsapp-contacts" in sources:
        _put(backup, rows, WHATSAPP, "ContactsV2.sqlite", _contacts(_dir(stage, "wac")))
    if "whatsapp" in sources:
        store = _chat_store(_dir(stage, "wa"))
        _put(backup, rows, WHATSAPP, "ChatStorage.sqlite", store)
        _put(backup, rows, WHATSAPP, "ChatStorage.sqlite-shm", _blob(stage, b"\0" * 32))
        _put(backup, rows, WHATSAPP, "Message", None)
        _put_tree(backup, rows, WHATSAPP, "Message", store.parent / "Message")
        _put(backup, rows, WHATSAPP, "Message/../escape.jpg", _blob(stage, b"never copied"))
    if "imessage" in sources:
        store = _sms_store(_dir(stage, "sms"))
        _put(backup, rows, "HomeDomain", "Library/SMS/sms.db", store)
        _put(backup, rows, "HomeDomain", "Library/SMS/sms.db-wal", _blob(stage, b""))
        _put(backup, rows, "MediaDomain", "Library/SMS/Attachments", None)
        _put_tree(backup, rows, "MediaDomain", "Library/SMS/Attachments", store.parent / "Attachments")
    if "ios-calendar" in sources:
        _put(backup, rows, "HomeDomain", "Library/Calendar/Calendar.sqlitedb", _calendar(_dir(stage, "cal")))
    if "ios-notes" in sources:
        _put(backup, rows, NOTES, "NoteStore.sqlite", _note_store(_dir(stage, "notes")))
    con = sqlite3.connect(backup / "Manifest.db")
    try:
        con.execute(
            "CREATE TABLE Files (fileID TEXT PRIMARY KEY, domain TEXT, relativePath TEXT, flags INTEGER,"
            " file BLOB)"
        )
        con.executemany("INSERT INTO Files VALUES (?,?,?,?,NULL)", rows)
        con.commit()
    finally:
        con.close()
    manifest: dict[str, object] = {"IsEncrypted": encrypted, "Version": "10.0"}
    if lockdown:
        manifest["Lockdown"] = {"UniqueDeviceID": UDID, "ProductVersion": "17.5"}
    with (backup / "Manifest.plist").open("wb") as fh:
        plistlib.dump(manifest, fh)
    return backup


def _dir(stage: Path, name: str) -> Path:
    d = stage / name
    d.mkdir(parents=True)
    return d


_blobs = 0


def _blob(stage: Path, data: bytes) -> Path:
    global _blobs
    _blobs += 1
    p = stage / "blobs" / f"{_blobs}.bin"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _snapshot(folder: Path) -> dict[str, str]:
    """Every file under the folder with its SHA-256 (directories too, as empty entries)."""
    out: dict[str, str] = {}
    for f in sorted(folder.rglob("*")):
        key = f.relative_to(folder).as_posix()
        out[key] = hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() else "dir"
    return out


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    monkeypatch.setenv("LOGBOOK_DIAL_PREFIX", "47")
    monkeypatch.delenv("LOGBOOK_WHATSAPP_HASH_MEDIA", raising=False)
    monkeypatch.delenv("LOGBOOK_IMESSAGE_HASH_MEDIA", raising=False)
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook.init(root, "Europe/Oslo")


def _run(*args: str) -> None:
    cli.main(["import-backup", *args])


# -- the whole backup ---------------------------------------------------------------


def test_import_backup_copies_every_store_and_runs_every_adapter_in_order(lb, tmp_path, capsys):
    backup = _backup(tmp_path)
    before = _snapshot(backup)
    _run(str(backup))
    out = capsys.readouterr().out
    assert _snapshot(backup) == before  # never written, never journaled
    inbox = lb.root / "inbox" / f"ios-backup-{UDID}"
    assert sorted(p.name for p in inbox.iterdir()) == sorted(ALL)
    for source, name in STORES.items():
        copy = inbox / source / name
        assert copy.is_file(), source
        assert f"{source}: {name}" in out
        assert f"added {LINES[source]} lines from {source}" in out
    # the order is the one that lets each source build on the one before it
    positions = [out.index(f"{source}: ") for source in ALL]
    assert positions == sorted(positions)
    # siblings and media travel with the store, under their original names
    assert (inbox / "whatsapp" / "ChatStorage.sqlite-shm").stat().st_size == 32
    assert (inbox / "imessage" / "sms.db-wal").stat().st_size == 0
    photo = inbox / "whatsapp" / "Message" / "Media" / "4790000001@s.whatsapp.net" / "a" / "b" / "photo.jpg"
    assert photo.is_file()
    assert (inbox / "imessage" / "Attachments" / "ab" / "12" / "AT-100" / "stern.jpg").is_file()
    assert (inbox / "imessage" / "Attachments" / "ef" / "56" / "AT-103" / "note.caf").is_file()
    assert not (inbox / "whatsapp" / "escape.jpg").exists() and not (inbox / "escape.jpg").exists()
    # the copies are what the adapters read: media was found and hashed, skips are reported
    assert "also 1 with media hashed, 1 with media missing, 1 without a stanza id, keyed by row id" in out
    assert "skipped 2 reactions, 1 group system events" in out
    assert "valid — 49 lines" in out
    seq, _head, errors = lb.verify()
    assert (seq, errors) == (49, [])
    # LOGBOOK_DIAL_PREFIX reached the adapters: the number saved without a country code got one
    refs = {line["payload"]["ref"]["value"] for line in lb.lines() if line["source"] == "ios-contacts"}
    assert "+4722334455" in refs
    # every copy is the size of its original
    con = sqlite3.connect(f"{(backup / 'Manifest.db').as_uri()}?mode=ro", uri=True)
    try:
        sizes = {
            (d, r): (backup / f[:2] / f).stat().st_size
            for f, d, r, flags in con.execute("SELECT fileID, domain, relativePath, flags FROM Files")
            if flags == 1
        }
    finally:
        con.close()
    assert (inbox / "ios-contacts" / "AddressBook.sqlitedb").stat().st_size == sizes[
        ("HomeDomain", "Library/AddressBook/AddressBook.sqlitedb")
    ]
    assert photo.stat().st_size == sizes[(WHATSAPP, "Message/Media/4790000001@s.whatsapp.net/a/b/photo.jpg")]


def test_import_backup_again_adds_nothing_and_leaves_one_copy(lb, tmp_path, capsys):
    backup = _backup(tmp_path)
    _run(str(backup))
    capsys.readouterr()
    _run(str(backup))
    out = capsys.readouterr().out
    for source in ALL:
        assert f"added 0 lines from {source}" in out
    assert "valid — 49 lines" in out
    inbox = lb.root / "inbox" / f"ios-backup-{UDID}"
    assert sorted(p.name for p in (inbox / "whatsapp").iterdir()) == [
        "ChatStorage.sqlite",
        "ChatStorage.sqlite-shm",
        "Message",
    ]


# -- not found ------------------------------------------------------------------------


def test_import_backup_reports_what_is_not_there(lb, tmp_path, capsys):
    backup = _backup(tmp_path, sources=("ios-contacts", "ios-notes"))
    _run(str(backup))
    out = capsys.readouterr().out
    assert "ios-contacts: AddressBook.sqlitedb" in out and "added 7 lines from ios-contacts" in out
    assert "ios-notes: NoteStore.sqlite" in out and "added 4 lines from ios-notes" in out
    for source in ("whatsapp-contacts", "whatsapp", "imessage", "ios-calendar"):
        assert f"{source}: {STORES[source]} not found" in out
        assert not (lb.root / "inbox" / f"ios-backup-{UDID}" / source).exists()
    assert "valid — 11 lines" in out


def test_import_backup_treats_a_listed_but_missing_file_as_not_found(lb, tmp_path, capsys):
    backup = _backup(tmp_path, sources=("ios-calendar",))
    fid = _file_id("HomeDomain", "Library/Calendar/Calendar.sqlitedb")
    (backup / fid[:2] / fid).unlink()
    _run(str(backup))
    out = capsys.readouterr().out
    assert "ios-calendar: Calendar.sqlitedb not found (listed in Manifest.db, file missing)" in out
    assert "valid — 0 lines" in out


# -- refusals --------------------------------------------------------------------------


def test_import_backup_refuses_an_encrypted_backup(lb, tmp_path, capsys):
    backup = _backup(tmp_path, encrypted=True)
    before = _snapshot(backup)
    with pytest.raises(SystemExit) as e:
        _run(str(backup))
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "encrypted" in err and "Finder" in err and "Encrypt local backup" in err
    assert _snapshot(backup) == before
    assert not any((lb.root / "inbox").glob("ios-backup-*"))
    assert lb.verify()[0] == 0


def test_import_backup_refuses_a_folder_that_is_not_a_backup(lb, tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        _run(str(tmp_path))
    assert e.value.code == 2
    assert "Manifest.db" in capsys.readouterr().err


def test_import_backup_refuses_an_unknown_only_name(lb, tmp_path, capsys):
    backup = _backup(tmp_path, sources=("ios-notes",))
    with pytest.raises(SystemExit) as e:
        _run(str(backup), "--only", "notes,telegram")
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "telegram" in err and "ios-notes" in err


# -- --only and --dry-run ---------------------------------------------------------------


def test_import_backup_only_takes_the_named_sources_in_the_fixed_order(lb, tmp_path, capsys):
    backup = _backup(tmp_path)
    _run(str(backup), "--only", "whatsapp,contacts,whatsapp-contacts")
    out = capsys.readouterr().out
    assert "added 7 lines from ios-contacts" in out
    assert "added 4 lines from whatsapp-contacts" in out
    assert "added 14 lines from whatsapp" in out
    assert out.index("ios-contacts:") < out.index("whatsapp-contacts:") < out.index("whatsapp:")
    for source in ("imessage", "ios-calendar", "ios-notes"):
        assert source not in out
    assert "valid — 25 lines" in out
    inbox = lb.root / "inbox" / f"ios-backup-{UDID}"
    assert sorted(p.name for p in inbox.iterdir()) == ["ios-contacts", "whatsapp", "whatsapp-contacts"]


def test_import_backup_dry_run_lists_files_and_sizes_and_writes_nothing(lb, tmp_path, capsys):
    backup = _backup(tmp_path)
    before = _snapshot(backup)
    _run(str(backup), "--dry-run")
    out = capsys.readouterr().out
    assert _snapshot(backup) == before
    assert not any((lb.root / "inbox").glob("ios-backup-*"))
    assert lb.verify()[0] == 0
    for source, name in STORES.items():
        assert f"{source}: {name}" in out
    size = (
        (
            backup
            / _file_id("HomeDomain", "Library/SMS/sms.db")[:2]
            / _file_id("HomeDomain", "Library/SMS/sms.db")
        )
        .stat()
        .st_size
    )
    assert f"{size:,} bytes" in out
    assert "sms.db-wal" in out and "ChatStorage.sqlite-shm" in out
    assert "1 media file (" in out and "under Message/" in out
    assert "2 media files (" in out and "under Attachments/" in out
    assert "dry run" in out and "added" not in out and "valid" not in out


# -- naming the folder ------------------------------------------------------------------


def test_import_backup_names_the_folder_after_the_backup_folder_without_a_lockdown(lb, tmp_path, capsys):
    backup = _backup(tmp_path, sources=("ios-notes",), lockdown=False)
    _run(str(backup))
    assert (lb.root / "inbox" / "ios-backup-backup" / "ios-notes" / "NoteStore.sqlite").is_file()


# -- the module: sources and the manifest ----------------------------------------------


def test_sources_are_in_the_documented_order():
    assert tuple(s.name for s in ios_backup.SOURCES) == ALL


def test_manifest_opens_read_only_and_finds_files(tmp_path):
    backup = _backup(tmp_path, sources=("ios-notes",))
    before = _snapshot(backup)
    manifest = ios_backup.Manifest(backup)
    assert manifest.encrypted is False
    assert manifest.udid == UDID
    found = manifest.file(NOTES, "NoteStore.sqlite")
    assert found is not None and found.path.is_file() and found.name == "NoteStore.sqlite"
    assert manifest.file(NOTES, "NoteStore.sqlite-wal") is None
    assert manifest.file("HomeDomain", "Library") is None  # a directory row is not a file
    assert _snapshot(backup) == before
