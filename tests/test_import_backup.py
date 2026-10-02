"""`logbook import-backup <folder>`: an unencrypted iOS backup in, every adapter run on copies."""

from __future__ import annotations

import hashlib
import json
import plistlib
import sqlite3
import sys
from pathlib import Path, PurePosixPath

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_apple_books import LINES as BOOK_LINES
from test_apple_books import _store as _books_store
from test_apple_photos import KEEPERS as PHOTO_KEEPERS
from test_apple_photos import LINES as PHOTO_LINES
from test_apple_photos import _store as _photos_store
from test_apple_reminders import _second_store as _reminders_second_store
from test_apple_reminders import _store as _reminders_store
from test_beeper import _store as _beeper_store
from test_copilot import _store as _copilot_store
from test_easypark import LINES as EASYPARK_LINES
from test_easypark import _recent
from test_flighty import STORE_LINES as FLIGHTY_LINES
from test_flighty import _store as _flighty_store
from test_imessage import _store as _sms_store
from test_import_backup_encrypted import _file_plist
from test_ios_calendar import _calendar
from test_ios_contacts import _address_book
from test_ios_notes import _store as _note_store
from test_ios_wallet import LINES as WALLET_LINES
from test_ios_wallet import _passes
from test_line import _store as _line_store
from test_myfitnesspal import LINES as MFP_LINES
from test_myfitnesspal import _store as _mfp_store
from test_safari import _store as _safari_store
from test_sbb import LINES as SBB_LINES
from test_sbb import _mobile_store as _sbb_mobile
from test_sbb import _trips_store as _sbb_trips
from test_screentime import PHONE_LINES as SCREENTIME_LINES
from test_screentime import _phone_store as _screentime_store
from test_splitwise import _store as _splitwise_store
from test_twitter import _store as _twitter_store
from test_voice_memos import LINES as MEMO_LINES
from test_voice_memos import STORED as MEMO_FILES
from test_voice_memos import _store as _memo_store
from test_whatsapp import _store as _chat_store
from test_whatsapp_contacts import _contacts
from test_wispr_flow import LINES as WISPR_LINES
from test_wispr_flow import _store as _wispr_store
from test_withings import LINES as WITHINGS_LINES
from test_withings import _health_store as _withings_health
from test_withings import _measure_store as _withings_measure

from logbook import cli, ios_backup
from logbook.store import Logbook

UDID = "00008030-000A1B2C3D4E5F60"
WHATSAPP = "AppDomainGroup-group.net.whatsapp.WhatsApp.shared"
NOTES = "AppDomainGroup-group.com.apple.notes"
REMINDERS = "AppDomainGroup-group.com.apple.reminders"
COPILOT = "AppDomainGroup-group.com.copilot.production"
SPLITWISE = "AppDomain-com.Splitwise.SplitwiseMobile"
BEEPER = "AppDomainGroup-group.beeper.chat.ios"
LINE_APP = "AppDomain-jp.naver.line"
LINE = "AppDomainGroup-group.com.linecorp.line"
LINE_STORE = "Library/Application Support/PrivateStore/P_u0000000000000000000000000000000"
TWITTER = "AppDomainGroup-group.com.atebits.Tweetie2"
TWITTER_STORE = "com.atebits.tweetie.databases/v1/1000000000000000001/1000000000000000001-dmv2.db"
BOOKS = "AppDomain-com.apple.iBooks"
MEMOS = "AppDomainGroup-group.com.apple.VoiceMemos.shared"
WITHINGS = "AppDomain-com.withings.wiScaleNG"
MFP = "AppDomain-com.myfitnesspal.mfp"
COREDATA = "Library/Application Support/coredata"
SBB = "AppDomainGroup-group.ch.sbb.SBBMobile"
SBB_APP = "AppDomain-5Q4J53EFRC.com.sbb.ch"
ALL = (
    "ios-contacts",
    "whatsapp-contacts",
    "whatsapp",
    "imessage",
    "ios-calendar",
    "ios-notes",
    "ios-wallet",
    "easypark",
    "wispr-flow",
    "flighty",
    "apple-reminders",
    "copilot",
    "splitwise",
    "beeper",
    "line",
    "twitter",
    "apple-books",
    "voice-memos",
    "apple-photos",
    "withings",
    "myfitnesspal",
    "sbb",
    "screentime",
)
LINES = {  # with LOGBOOK_DIAL_PREFIX=47 (the `lb` fixture): two numbers without a country code normalise
    "ios-contacts": 7,
    "whatsapp-contacts": 4,
    "whatsapp": 14,
    "imessage": 13,
    "ios-calendar": 7,
    "ios-notes": 4,
    "ios-wallet": WALLET_LINES,
    "easypark": EASYPARK_LINES,
    "wispr-flow": WISPR_LINES,
    "flighty": FLIGHTY_LINES,
    "apple-reminders": 7,
    "copilot": 6,
    "splitwise": 5,
    "beeper": 8,
    "line": 8,
    "twitter": 6,
    "apple-books": BOOK_LINES,
    "voice-memos": MEMO_LINES,
    "apple-photos": PHOTO_LINES,
    "withings": 2 * WITHINGS_LINES,  # two profiles
    "myfitnesspal": MFP_LINES,
    "sbb": SBB_LINES,
    "screentime": SCREENTIME_LINES,
}
TOTAL = sum(LINES.values()) + PHOTO_KEEPERS  # the import writes the keepers for the photos' marks (RFC 0024)
STORES = {
    "ios-contacts": "AddressBook.sqlitedb",
    "whatsapp-contacts": "ContactsV2.sqlite",
    "whatsapp": "ChatStorage.sqlite",
    "imessage": "sms.db",
    "ios-calendar": "Calendar.sqlitedb",
    "ios-notes": "NoteStore.sqlite",
    "wispr-flow": "database.sqlite",
    "flighty": "MainFlightyDatabase.db",
    "apple-reminders": "Data-AAAAAAAA-0000-4000-8000-000000000001.sqlite",  # first in path order
}
STORES["copilot"] = "CopilotDB.sqlite"
STORES["splitwise"] = "database.sqlite"
STORES["beeper"] = "BeeperStore.sqlite"
STORES["line"] = "Line.sqlite"
STORES["twitter"] = "1000000000000000001-dmv2.db"
STORES["apple-books"] = "AEAnnotation_v10312011_1727_local.sqlite"
STORES["voice-memos"] = "CloudRecordings.db"
STORES["apple-photos"] = "Photos.sqlite"
STORES["withings"] = "10000001_WTHealth.sqlite"  # the first match of the glob; the adapter reads the folder
STORES["myfitnesspal"] = "maindb.sqlite"
STORES["sbb"] = "SbbMobile.db"
STORES["screentime"] = "RMAdminStore-Local.sqlite"
REMINDERS_OTHER = "Data-AAAAAAAA-0000-4000-8000-000000000002.sqlite"  # the bigger store, with a -wal


SAFARI_BYTES = b"SQLite format 3\0" + b"\x02" * 1000


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
    if "ios-wallet" in sources:  # one unpacked .pkpass folder per pass, as the phone keeps them
        _put(backup, rows, "HomeDomain", "Library/Passes/Cards", None)
        _put_tree(backup, rows, "HomeDomain", "Library/Passes/Cards", _passes(_dir(stage, "wallet")))
    if "easypark" in sources:  # the recent-parkings file beside the find-my-car pin, which is not copied
        _put(backup, rows, ios_backup.EASYPARK, "Documents", None)
        _put_tree(backup, rows, ios_backup.EASYPARK, "Documents", _recent(_dir(stage, "easypark")))
    if "wispr-flow" in sources:
        _put(backup, rows, ios_backup.WISPR, "Documents/database.sqlite", _wispr_store(_dir(stage, "wispr")))
    if "flighty" in sources:
        store = _flighty_store(_dir(stage, "flighty"))
        _put(backup, rows, ios_backup.FLIGHTY, "Documents/MainFlightyDatabase.db", store)
    if "safari" in sources:  # HomeDomain, as the phone backs it up
        _put(backup, rows, "HomeDomain", "Library/Safari/History.db", _safari_store(_dir(stage, "safari")))
    if "apple-reminders" in sources:  # one store per account under Stores/, found by pattern
        folder = _dir(stage, "rem")
        first = _reminders_store(folder)
        second = _reminders_second_store(folder)
        _put(backup, rows, REMINDERS, "Container_v1/Stores", None)
        _put(backup, rows, REMINDERS, "Container_v1/Stores/" + first.name, first)
        _put(backup, rows, REMINDERS, "Container_v1/Stores/" + second.name, second)
        _put(backup, rows, REMINDERS, "Container_v1/Stores/" + first.name + "-wal", _blob(stage, b"\0" * 16))
        _put(backup, rows, REMINDERS, "Container_v1/MLModels/RDkNNReminder.json", _blob(stage, b"{}"))
    if "copilot" in sources:
        _put(backup, rows, COPILOT, "database", None)
        _put(backup, rows, COPILOT, "database/CopilotDB.sqlite", _copilot_store(_dir(stage, "copilot")))
    if "splitwise" in sources:
        _put(backup, rows, SPLITWISE, "Library/Application Support", None)
        store = _splitwise_store(_dir(stage, "splitwise"))
        _put(backup, rows, SPLITWISE, "Library/Application Support/database.sqlite", store)
    if "beeper" in sources:
        _put(backup, rows, BEEPER, "BeeperStore.sqlite", _beeper_store(_dir(stage, "beeper")))
        _put(backup, rows, BEEPER, "Contacts.sqlite", _blob(stage, SAFARI_BYTES))  # beside it, never copied
    if "line" in sources:  # the store and the group names in the group container, the contacts in the app's
        store = _line_store(_dir(stage, "line"))
        _put(backup, rows, LINE, LINE_STORE + "/Messages", None)
        _put(backup, rows, LINE, LINE_STORE + "/Messages/Line.sqlite", store)
        _put(
            backup,
            rows,
            LINE,
            LINE_STORE + "/Messages/UnifiedGroup.sqlite",
            store.parent / "UnifiedGroup.sqlite",
        )
        _put(backup, rows, LINE, LINE_STORE + "/Messages/ChatExt.sqlite", _blob(stage, SAFARI_BYTES))
        _put(
            backup,
            rows,
            LINE_APP,
            LINE_STORE + "/Contacts Syncing/Contacts.sqlite",
            store.parent / "Contacts.sqlite",
        )
    if "twitter" in sources:  # one store per account, found by pattern; the scribe db beside them is not one
        store = _twitter_store(_dir(stage, "twitter"))
        _put(backup, rows, TWITTER, "com.atebits.tweetie.databases/v1/1000000000000000001", None)
        _put(backup, rows, TWITTER, TWITTER_STORE, store)
        _put(
            backup,
            rows,
            TWITTER,
            "com.atebits.tweetie.scribe/scribe.2-compact.sqlite",
            _blob(stage, SAFARI_BYTES),
        )
    if "apple-books" in sources:  # the store under storeFiles/, the library under BKLibrary/ beside it
        store = _books_store(_dir(stage, "books") / "storeFiles", library="documents")
        _put(backup, rows, BOOKS, "Documents/storeFiles/AEAnnotation_v10312011_1727_local.sqlite", store)
        _put(
            backup,
            rows,
            BOOKS,
            "Documents/storeFiles/AEAnnotation_v10312011_1727_local.sqlite-wal",
            _blob(stage, b""),
        )
        _put(backup, rows, BOOKS, "Documents/BKLibrary", None)
        library = store.parent.parent / "BKLibrary" / "BKLibrary-1-091020131601.sqlite"
        _put(backup, rows, BOOKS, "Documents/BKLibrary/BKLibrary-1-091020131601.sqlite", library)
    if "voice-memos" in sources:  # the store and the audio share one folder on the phone
        store = _memo_store(_dir(stage, "memos"), layout="phone")
        _put(backup, rows, MEMOS, "Recordings", None)
        _put_tree(backup, rows, MEMOS, "Recordings", store.parent)
        _put(backup, rows, MEMOS, "Recordings/20260302 211407.waveform", _blob(stage, b"\x00" * 64))
        _put(
            backup,
            rows,
            MEMOS,
            "Recordings/20260302 211407.composition/manifest.plist",
            _blob(stage, b"<plist/>"),
        )
    if "apple-photos" in sources:
        store = _photos_store(_dir(stage, "photos"))
        _put(backup, rows, "CameraRollDomain", "Media/PhotoData/Photos.sqlite", store)
        _put(backup, rows, "CameraRollDomain", "Media/PhotoData/Photos.sqlite-wal", _blob(stage, b""))
        _put(backup, rows, "CameraRollDomain", "Media/DCIM/100APPLE/IMG_0001.HEIC", _blob(stage, b"pixels"))
    if "withings" in sources:  # two profiles, two stores each, one of them with a -wal
        folder = _dir(stage, "withings")
        for profile in ("10000002", "10000001"):
            _put(
                backup,
                rows,
                WITHINGS,
                f"{COREDATA}/{profile}_WTHealth.sqlite",
                _withings_health(folder, profile),
            )
            _put(
                backup,
                rows,
                WITHINGS,
                f"{COREDATA}/{profile}_Measure.sqlite",
                _withings_measure(folder, profile),
            )
        _put(backup, rows, WITHINGS, f"{COREDATA}/10000002_Measure.sqlite-wal", _blob(stage, b""))
        _put(
            backup, rows, WITHINGS, f"{COREDATA}/10000002_Food2.sqlite", _blob(stage, SAFARI_BYTES)
        )  # not read
    if "myfitnesspal" in sources:
        _put(backup, rows, MFP, "Documents/maindb.sqlite", _mfp_store(_dir(stage, "mfp")))
    if "sbb" in sources:  # two containers: the shared one holds the tickets, the app's own the past journeys
        _put(backup, rows, SBB, "SbbMobile.db", _sbb_mobile(_dir(stage, "sbb")))
        _put(
            backup,
            rows,
            SBB_APP,
            "Documents/ch.sbb.coredata.pasttrips.sqlite",
            _sbb_trips(_dir(stage, "sbb-app")),
        )
    if "safari" in sources:  # HomeDomain, as the phone backs it up; not a real store, nobody reads it yet
        _put(backup, rows, "HomeDomain", "Library/Safari/History.db", _blob(stage, SAFARI_BYTES))
    if "screentime" in sources:  # Screen Time's own store, in HomeDomain like Safari's history
        _put(backup, rows, "HomeDomain", "Library/Application Support/com.apple.remotemanagementd", None)
        _put(backup, rows, "HomeDomain", ios_backup.SCREEN_TIME, _screentime_store(_dir(stage, "screentime")))
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
    monkeypatch.delenv("LOGBOOK_BACKUP_PASSWORD", raising=False)  # the shell's, never a test's
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
    assert sorted(p.name for p in inbox.iterdir()) == sorted([*ALL, "copies.json"])
    for source, name in STORES.items():
        copy = inbox / source / name
        assert copy.is_file(), source
        assert f"{source}: {name}" in out
    for source in ALL:
        assert f"added {LINES[source]} lines from {source}" in out
    # a folder source: every pass.json below the folder, the folder's path kept, nothing else
    assert (inbox / "ios-wallet" / "01-swiss-style.pkpass" / "pass.json").is_file()
    assert "ios-wallet: 18 pass.json files (" in out and "under Library/Passes/Cards/" in out
    assert (
        "1 passes that would not parse" in out
        and "1 boarding passes whose year nothing on the pass gives" in out
    )
    assert (inbox / "easypark" / "recentparkings_12345.json").is_file()
    assert not (inbox / "easypark" / "findmycar-pin_12345.json").exists()
    assert "easypark: 1 recentparkings_*.json file (" in out
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
    # a companion travels beside the store under its own name, with the store's -wal; the store was
    # found by its glob, the adapter ran on the folder and found the library there (titles, not ids)
    assert (inbox / "apple-books" / "BKLibrary-1-091020131601.sqlite").is_file()
    assert (inbox / "apple-books" / "AEAnnotation_v10312011_1727_local.sqlite-wal").stat().st_size == 0
    assert "BKLibrary-1-091020131601.sqlite (" in out
    titles = {line["payload"].get("title") for line in lb.lines() if line["source"] == "apple-books"}
    assert "The Long Ships" in titles
    # only the audio travels with the voice memo store (the waveform and composition stay behind), under
    # Recordings/ beside it, where the adapter found and hashed it; nothing was stored without --attachments
    audio = sorted(p.name for p in (inbox / "voice-memos" / "Recordings").iterdir())
    assert len(audio) == MEMO_FILES and all(p.rsplit(".", 1)[1] in ("m4a", "qta") for p in audio)
    assert f"{MEMO_FILES} media files" in out and f"{MEMO_FILES} attachments referenced, not stored" in out
    for line in lb.lines():
        if line["source"] == "voice-memos" and "media" in line["payload"]:
            assert "path" not in line["payload"]["media"]
            assert not (lb.root / "attachments" / line["payload"]["media"]["sha256"]).exists()
    # every profile's Withings stores landed in one folder (the glob's first match is the store, the rest
    # and the companions beside it, with their -wal) and the adapter read the folder: both profiles are in
    withings_copies = sorted(p.name for p in (inbox / "withings").iterdir())
    assert withings_copies == [
        "10000001_Measure.sqlite", "10000001_WTHealth.sqlite", "10000002_Measure.sqlite",
        "10000002_Measure.sqlite-wal", "10000002_WTHealth.sqlite",
    ]  # fmt: skip
    profiles = {line["payload"]["extra"]["profile"] for line in lb.lines() if line["source"] == "withings"}
    assert profiles == {"10000001", "10000002"}
    # a companion from another domain lands beside the store, and the adapter read both
    assert (inbox / "sbb" / "ch.sbb.coredata.pasttrips.sqlite").is_file()
    observed = {line["payload"]["extra"]["observed"] for line in lb.lines() if line["source"] == "sbb"}
    assert observed == {"ticket", "journey"}
    # the copies are what the adapters read: media was found and hashed, skips are reported
    assert "also 1 with media hashed, 1 with media missing, 1 without a stanza id, keyed by row id" in out
    assert "skipped 2 reactions, 1 group system events" in out
    assert f"valid — {TOTAL} lines" in out
    seq, _head, errors = lb.verify()
    assert (seq, errors) == (TOTAL, [])
    # LOGBOOK_DIAL_PREFIX reached the adapters: the number saved without a country code got one
    refs = {line["payload"]["ref"]["value"] for line in lb.lines() if line["source"] == "ios-contacts"}
    assert "+4790000055" in refs
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
    # copies.json records every copy; nothing here was encrypted
    copies = json.loads((inbox / "copies.json").read_text(encoding="utf-8"))
    assert copies["backup"] == UDID and copies["encrypted"] is False
    by_copy = {c["copy"]: c for c in copies["files"]}
    never = {
        ("HomeDomain", "Library/Preferences/com.apple.example.plist"),
        (WHATSAPP, "Message/../escape.jpg"),
        (ios_backup.EASYPARK, "Documents/findmycar-pin_12345.json"),  # beside the file, not in the glob
        (REMINDERS, "Container_v1/MLModels/RDkNNReminder.json"),
        (BEEPER, "Contacts.sqlite"),
        (LINE, LINE_STORE + "/Messages/ChatExt.sqlite"),
        (TWITTER, "com.atebits.tweetie.scribe/scribe.2-compact.sqlite"),
        (MEMOS, "Recordings/20260302 211407.waveform"),
        (MEMOS, "Recordings/20260302 211407.composition/manifest.plist"),
        ("CameraRollDomain", "Media/DCIM/100APPLE/IMG_0001.HEIC"),  # the pixels stay on the phone
        (WITHINGS, f"{COREDATA}/10000002_Food2.sqlite"),  # not a store the adapter reads
    }
    assert {(c["domain"], c["path"]) for c in copies["files"]} == set(sizes) - never
    assert by_copy["whatsapp/Message/Media/4790000001@s.whatsapp.net/a/b/photo.jpg"] == {
        "source": "whatsapp",
        "domain": WHATSAPP,
        "path": "Message/Media/4790000001@s.whatsapp.net/a/b/photo.jpg",
        "copy": "whatsapp/Message/Media/4790000001@s.whatsapp.net/a/b/photo.jpg",
        "bytes": photo.stat().st_size,
        "encrypted": False,
        "protection_class": None,
    }


def test_import_backup_unencrypted_warns_when_the_manifest_size_is_stale(lb, tmp_path, capsys):
    """An unencrypted backup's file plist can also carry a stale Size: when the copy equals the
    blob on disk byte for byte, that is one warning, not an error."""
    backup = _backup(tmp_path, sources=("ios-contacts",))
    rel = "Library/AddressBook/AddressBook.sqlitedb"
    fid = _file_id("HomeDomain", rel)
    real = (backup / fid[:2] / fid).stat().st_size
    con = sqlite3.connect(backup / "Manifest.db")
    try:
        con.execute("UPDATE Files SET file = ? WHERE fileID = ?", (_file_plist(35_745_792, 4, None), fid))
        con.commit()
    finally:
        con.close()
    _run(str(backup))
    captured = capsys.readouterr()
    warnings = [line for line in captured.out.splitlines() if "warning" in line]
    assert len(warnings) == 1
    assert rel in warnings[0] and f"{real:,}" in warnings[0] and "35,745,792" in warnings[0]
    assert captured.err == ""
    inbox = lb.root / "inbox" / f"ios-backup-{UDID}"
    copies = json.loads((inbox / "copies.json").read_text(encoding="utf-8"))
    entry = next(c for c in copies["files"] if c["path"] == rel)
    assert entry["bytes"] == real and "35,745,792" in entry["warning"]


def test_import_backup_again_adds_nothing_and_leaves_one_copy(lb, tmp_path, capsys):
    backup = _backup(tmp_path)
    _run(str(backup))
    capsys.readouterr()
    _run(str(backup))
    out = capsys.readouterr().out
    for source in ALL:
        assert f"added 0 lines from {source}" in out
    assert f"valid — {TOTAL} lines" in out
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


def test_import_backup_refuses_an_encrypted_backup_without_a_password(lb, tmp_path, capsys):
    """The full encrypted path is in test_import_backup_encrypted.py; here: no password, no attempt."""
    backup = _backup(tmp_path, encrypted=True)
    before = _snapshot(backup)
    with pytest.raises(SystemExit) as e:
        _run(str(backup))
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "encrypted" in err and "LOGBOOK_BACKUP_PASSWORD" in err
    assert "Finder" in err and "Encrypt local backup" in err
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
    assert sorted(p.name for p in inbox.iterdir()) == [
        "copies.json",
        "ios-contacts",
        "whatsapp",
        "whatsapp-contacts",
    ]
    copies = json.loads((inbox / "copies.json").read_text(encoding="utf-8"))
    assert {c["source"] for c in copies["files"]} == {"ios-contacts", "whatsapp", "whatsapp-contacts"}
    # a later run of other sources keeps these entries and adds its own
    _run(str(backup), "--only", "notes")
    copies = json.loads((inbox / "copies.json").read_text(encoding="utf-8"))
    assert {c["source"] for c in copies["files"]} == {
        "ios-contacts",
        "whatsapp",
        "whatsapp-contacts",
        "ios-notes",
    }


def test_import_backup_skips_a_disabled_source_and_says_so(lb, tmp_path, capsys):
    """policy/import.json: a disabled source is neither copied nor run, with or without --only, and
    the alias `health` stands for `apple-health` on both sides."""
    (lb.root / "policy" / "import.json").write_text(
        json.dumps(
            {
                "disabled": [
                    {"source": "whatsapp", "reason": "a demo account"},
                    {"source": "notes", "reason": "someone else's notes"},
                ]
            }
        ),
        encoding="utf-8",
    )
    backup = _backup(tmp_path)
    _run(str(backup), "--only", "whatsapp,contacts,notes,whatsapp-contacts")
    out = capsys.readouterr().out
    assert "whatsapp: disabled (a demo account); skipped" in out
    assert "ios-notes: disabled (someone else's notes); skipped" in out
    assert "added 7 lines from ios-contacts" in out
    assert "added 4 lines from whatsapp-contacts" in out
    assert "added 14 lines from whatsapp" not in out and "ios-notes: NoteStore" not in out
    inbox = lb.root / "inbox" / f"ios-backup-{UDID}"
    assert sorted(p.name for p in inbox.iterdir()) == ["copies.json", "ios-contacts", "whatsapp-contacts"]
    assert "valid — 11 lines" in out
    # --dry-run says the same, and a disabled source is never counted as found
    _run(str(backup), "--only", "whatsapp,contacts", "--dry-run")
    out = capsys.readouterr().out
    assert "whatsapp: disabled (a demo account); skipped" in out
    assert "dry run: 1 of 1 sources found" in out


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


def test_import_backup_copies_every_store_a_pattern_source_matches_and_runs_on_the_folder(
    lb, tmp_path, capsys
):
    """Reminders keeps one store per account, `Data-<UUID>.sqlite`: the source names a pattern,
    every match is copied beside the first with its -wal/-shm, and the adapter runs on the folder."""
    backup = _backup(tmp_path, sources=("apple-reminders",))
    _run(str(backup), "--dry-run")
    out = capsys.readouterr().out
    row = next(line for line in out.splitlines() if line.startswith("apple-reminders: "))
    assert f"{STORES['apple-reminders']} (" in row and f"{REMINDERS_OTHER} (" in row  # path order
    assert f"{REMINDERS_OTHER}-wal (16 bytes)" in row
    assert "RDkNNReminder" not in out
    _run(str(backup))
    out = capsys.readouterr().out
    folder = lb.root / "inbox" / f"ios-backup-{UDID}" / "apple-reminders"
    assert sorted(p.name for p in folder.iterdir()) == sorted(
        [STORES["apple-reminders"], REMINDERS_OTHER, REMINDERS_OTHER + "-wal"]
    )
    assert "added 7 lines from apple-reminders" in out
    assert "skipped 1 without a title, 1 with an unusable date" in out
    assert "also 1 marked for deletion" in out
    stores = {line["payload"]["extra"]["store"] for line in lb.lines()}
    assert stores == {STORES["apple-reminders"], REMINDERS_OTHER}


def test_import_backup_copies_lines_companions_beside_its_store(lb, tmp_path, capsys):
    backup = _backup(tmp_path, sources=("line",))
    _run(str(backup))
    out = capsys.readouterr().out
    folder = lb.root / "inbox" / f"ios-backup-{UDID}" / "line"
    assert sorted(p.name for p in folder.iterdir()) == [
        "Contacts.sqlite",
        "Line.sqlite",
        "UnifiedGroup.sqlite",
    ]
    assert out.count("copied, read beside Line.sqlite") == 2
    assert "added 8 lines from line" in out
    senders = {line["payload"].get("sender", {}).get("kind") for line in lb.lines()}
    assert "phone" in senders  # Contacts.sqlite was found beside the store


def test_import_backup_pattern_source_with_no_match_is_not_found(lb, tmp_path, capsys):
    backup = _backup(tmp_path, sources=("ios-notes",))
    _run(str(backup), "--only", "reminders")
    out = capsys.readouterr().out
    assert "apple-reminders: Data-*.sqlite not found" in out


# -- naming the folder ------------------------------------------------------------------


def test_import_backup_names_the_folder_after_the_backup_folder_without_a_lockdown(lb, tmp_path, capsys):
    backup = _backup(tmp_path, sources=("ios-notes",), lockdown=False)
    _run(str(backup))
    assert (lb.root / "inbox" / "ios-backup-backup" / "ios-notes" / "NoteStore.sqlite").is_file()


# -- the module: sources and the manifest ----------------------------------------------


def test_sources_are_in_the_documented_order():
    """One name per adapter, in import order; a companion store repeats its adapter's name."""
    assert tuple(dict.fromkeys(s.name for s in ios_backup.SOURCES)) == ALL
    companions = [s for s in ios_backup.SOURCES if not s.adapter]
    assert [(s.name, s.store_name) for s in companions] == [
        ("line", "Contacts.sqlite"),
        ("line", "UnifiedGroup.sqlite"),
    ]


def test_safari_history_is_found_in_home_domain_by_domain_and_path_not_by_file_id(tmp_path):
    """The phone backs Safari's history up as HomeDomain Library/Safari/History.db. The row is
    resolved through Manifest.db by domain and path: its fileID here is not the SHA-1 a backup
    would give it, and the copy still comes from where that row points."""
    backup = _backup(tmp_path, sources=("ios-notes",))
    fid = "f" * 40
    (backup / fid[:2]).mkdir()
    (backup / fid[:2] / fid).write_bytes(SAFARI_BYTES)
    con = sqlite3.connect(backup / "Manifest.db")
    try:
        con.execute(
            "INSERT INTO Files VALUES (?,?,?,?,NULL)", (fid, "HomeDomain", "Library/Safari/History.db", 1)
        )
        con.commit()
    finally:
        con.close()
    safari = ios_backup.source("safari")
    assert safari is not None and safari.domain == "HomeDomain"
    (p,) = ios_backup.plan(ios_backup.Manifest(backup), (safari,))
    assert p.found and p.store is not None
    assert p.store.path == backup / fid[:2] / fid and p.store.name == "History.db"
    copied = ios_backup.copy(p, tmp_path / "out")
    assert copied == tmp_path / "out" / "History.db" and copied.read_bytes() == SAFARI_BYTES


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


# -- folder sources: a glob of files under a folder, the adapter runs on the folder's copy ----------


FOLDER = ios_backup.Source("cards", "HomeDomain", "Library/Cards", files="card.json", adapter=False)


def _with_cards(tmp_path: Path, n: int = 2) -> Path:
    backup = _backup(tmp_path, sources=("ios-notes",))
    con = sqlite3.connect(backup / "Manifest.db")
    try:
        for i in range(n):
            rel = f"Library/Cards/{i:04d}.pkpass/card.json"
            fid = _file_id("HomeDomain", rel)
            (backup / fid[:2]).mkdir(exist_ok=True)
            (backup / fid[:2] / fid).write_bytes(b'{"n": %d}' % i)
            con.execute("INSERT INTO Files VALUES (?,?,?,?,NULL)", (fid, "HomeDomain", rel, 1))
            con.execute(
                "INSERT INTO Files VALUES (?,?,?,?,NULL)", (fid[::-1], "HomeDomain", rel.rsplit("/", 1)[0], 2)
            )
        other = "Library/Cards/0000.pkpass/logo.png"
        con.execute(
            "INSERT INTO Files VALUES (?,?,?,?,NULL)", (_file_id("HomeDomain", other), "HomeDomain", other, 1)
        )
        con.commit()
    finally:
        con.close()
    return backup


def test_folder_source_plans_every_matching_file_and_copies_them_below_the_folder(tmp_path):
    backup = _with_cards(tmp_path)
    (p,) = ios_backup.plan(ios_backup.Manifest(backup), (FOLDER,))
    assert p.listed and p.found and p.store is None
    assert [f.relative_path for f in p.files] == [
        "Library/Cards/0000.pkpass/card.json",
        "Library/Cards/0001.pkpass/card.json",
    ]
    assert p.bytes == 2 * len(b'{"n": 0}')
    out = ios_backup.copy(p, tmp_path / "out")
    assert out == tmp_path / "out"
    assert (out / "0000.pkpass" / "card.json").read_bytes() == b'{"n": 0}'
    assert (out / "0001.pkpass" / "card.json").read_bytes() == b'{"n": 1}'
    assert not (out / "0000.pkpass" / "logo.png").exists()
    assert len(p.copied) == 2
    row = cli._plan_row(p, tmp_path / "inbox")
    assert row.startswith("cards: 2 card.json files (16 bytes) under Library/Cards/ → ")


def test_folder_source_with_no_matching_file_is_not_found(tmp_path):
    backup = _backup(tmp_path, sources=("ios-notes",))
    (p,) = ios_backup.plan(ios_backup.Manifest(backup), (FOLDER,))
    assert not p.listed and not p.found and p.files == []
    assert cli._plan_row(p, tmp_path / "inbox") == "cards: no card.json under Library/Cards"
    with pytest.raises(ValueError):
        ios_backup.copy(p, tmp_path / "out")


def test_import_backup_hashes_the_photos_pixels_from_the_backup_without_copying_them(lb, tmp_path, capsys):
    """`apple-photos`: the line carries the pixels' digest (RFC 0002 `content_hash`, and `extra.media`
    as the message adapters write it), hashed straight from the backup, decrypted on the way when
    need be, and never copied: the inbox holds the library and nothing under DCIM/."""
    backup = _backup(tmp_path, sources=("apple-photos",))
    _run(str(backup), "--only", "photos")
    out = capsys.readouterr().out
    assert f"added {PHOTO_LINES} lines from apple-photos" in out
    assert f"also 1 with media hashed, {PHOTO_LINES - 1} with media missing" in out
    inbox = lb.root / "inbox" / f"ios-backup-{UDID}"
    copies = sorted(p.name for p in (inbox / "apple-photos").iterdir())
    assert copies == ["Photos.sqlite", "Photos.sqlite-wal"]
    assert not list(inbox.rglob("IMG_0001.HEIC")) and not list(lb.root.glob("attachments"))
    photos = {line["payload"]["file_name"]: line["payload"] for line in lb.lines()}
    pixels = hashlib.sha256(b"pixels").hexdigest()
    assert photos["IMG_0001.HEIC"]["content_hash"] == pixels
    assert photos["IMG_0001.HEIC"]["extra"]["media"] == {
        "local_path": "DCIM/100APPLE/IMG_0001.HEIC",
        "sha256": pixels,
        "bytes": len(b"pixels"),
    }
    assert photos["IMG_0002.PNG"]["extra"]["media"] == {"local_path": "DCIM/100APPLE/IMG_0002.PNG"}
    assert photos["IMG_0002.PNG"]["extra"]["media_missing"] is True
    with lb.index() as idx:
        assert idx.attachment_counts(lambda sha: False) == {"referenced": 1, "lines": 1, "present": 0}


def test_import_backup_skips_hashing_the_photos_when_told_to(lb, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOGBOOK_APPLE_PHOTOS_HASH_MEDIA", "0")
    backup = _backup(tmp_path, sources=("apple-photos",))
    _run(str(backup), "--only", "photos")
    out = capsys.readouterr().out
    assert f"added {PHOTO_LINES} lines from apple-photos" in out and "media" not in out
    for line in lb.lines():
        p = line["payload"]
        assert "content_hash" not in p and "media_missing" not in p["extra"]
        assert set(p["extra"]["media"]) == {"local_path"}


def test_import_backup_attachments_stores_the_voice_memo_audio(lb, tmp_path, capsys):
    backup = _backup(tmp_path, sources=("voice-memos",))
    _run(str(backup), "--only", "voice-memos", "--attachments")
    out = capsys.readouterr().out
    assert f"added {MEMO_LINES} lines from voice-memos" in out and f"{MEMO_FILES} attachments stored" in out
    stored = sorted(p.name for p in (lb.root / "attachments").iterdir())
    assert len(stored) == MEMO_FILES
    for line in lb.lines():
        media = line["payload"].get("media")
        if media is not None:
            assert media["path"] == f"attachments/{media['sha256']}" and media["sha256"] in stored
