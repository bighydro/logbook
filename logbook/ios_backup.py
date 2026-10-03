"""An iOS backup folder (Finder, iTunes), encrypted or not → the files the phone adapters read.

A backup is a folder of files named by hash. Manifest.db, a SQLite file, has one row per file in
its Files table (fileID, domain, relativePath, flags: 1 a file, 2 a directory, 4 a symlink); the
bytes of a file are at <fileID[:2]>/<fileID> (older backups kept them flat at <fileID>).
Manifest.plist says whether the backup is encrypted (IsEncrypted) and carries the phone's
identifier under Lockdown/UniqueDeviceID. Both are read and never written: Manifest.db is opened
`mode=ro`, `immutable=1`, so not even a journal appears beside it.

An encrypted backup (IsEncrypted, with a BackupKeyBag and a ManifestKey in the plist) is the same
folder with every file, Manifest.db included, encrypted under its own key (`ios_backup_crypto`).
`Manifest.unlock(password, dest)` unlocks the keybag — a wrong password fails there, before any
file is touched — and decrypts Manifest.db into `dest`, from where it is read exactly as an
unencrypted one; each file row then also carries its protection class and its unwrapped key, and
`copy` decrypts the file a chunk at a time on the way to its copy. The layout of the copies is the
same either way, so the adapters never know. `unlock` needs the `encrypted` extra
(`openlogbook[encrypted]`, `cryptography`); without it, `MissingExtra` says how to install it.

SOURCES lists, in import order, the store each adapter reads and where the phone keeps it:

    ios-contacts        HomeDomain                                    Library/AddressBook/AddressBook.sqlitedb
    whatsapp-contacts   AppDomainGroup-group.net.whatsapp.WhatsApp.shared  ContactsV2.sqlite
    whatsapp            the same                                      ChatStorage.sqlite, media under Message/
    imessage            HomeDomain                                    Library/SMS/sms.db,
                        MediaDomain                                   media under Library/SMS/Attachments/
    ios-calendar        HomeDomain                                    Library/Calendar/Calendar.sqlitedb
    ios-notes           AppDomainGroup-group.com.apple.notes          NoteStore.sqlite
    apple-wallet        HomeDomain                                    Library/Passes/Cards/…/pass.json (a
                                                                  folder source: every pass.json under
                                                                  Cards/, copied below apple-wallet/;
                                                                  never the images, never nav.db)
    easypark            AppDomain-net.easypark.app                    Documents/recentparkings_<user>.json
                                                                  (a folder source: the glob names the file)
    wispr-flow          AppDomain-com.wispr.flowapp                   Documents/database.sqlite
    flighty             AppDomain-com.flightyapp.flighty              Documents/MainFlightyDatabase.db
    apple-reminders     AppDomainGroup-group.com.apple.reminders      Container_v1/Stores/Data-*.sqlite
                                                                  (one store per account)
    copilot             AppDomainGroup-group.com.copilot.production   database/CopilotDB.sqlite
    splitwise           AppDomain-com.Splitwise.SplitwiseMobile       Library/Application Support/
                                                                  database.sqlite
    beeper              AppDomainGroup-group.beeper.chat.ios          BeeperStore.sqlite
    line                AppDomain-jp.naver.line                       Library/Application Support/
                                                                  PrivateStore/P_*/Contacts Syncing/
                                                                  Contacts.sqlite (copied first, read
                                                                  beside the store)
                        AppDomainGroup-group.com.linecorp.line        .../PrivateStore/P_*/Messages/
                                                                  UnifiedGroup.sqlite (the same)
                        the same                                      .../PrivateStore/P_*/Messages/
                                                                  Line.sqlite
    twitter             AppDomainGroup-group.com.atebits.Tweetie2     com.atebits.tweetie.databases/v1/*/
                                                                  *-dmv2.db (one store per account)
    apple-books         AppDomain-com.apple.iBooks                   Documents/storeFiles/AEAnnotation*.sqlite
                                                                  (+ Documents/BKLibrary/BKLibrary*.sqlite
                                                                  beside it: the titles)
    voice-memos         AppDomainGroup-group.com.apple.VoiceMemos.shared  Recordings/CloudRecordings.db,
                                                                  the .m4a/.qta files under Recordings/
    apple-photos        CameraRollDomain                              Media/PhotoData/Photos.sqlite (the
                                                                  library's metadata; the pixels are hashed in
                                                                  place, never copied)
    withings            AppDomain-com.withings.wiScaleNG              Library/Application Support/coredata/
                                                                  *_WTHealth.sqlite and *_Measure.sqlite
                                                                  (every profile; the adapter runs on the
                                                                  folder)
    myfitnesspal        AppDomain-com.myfitnesspal.mfp                Documents/maindb.sqlite
    sbb                 AppDomainGroup-group.ch.sbb.SBBMobile         SbbMobile.db (+ the app container's
                                                                  Documents/ch.sbb.coredata.pasttrips.sqlite
                                                                  beside it)
    screentime          HomeDomain                                    Library/Application Support/
                                                                  com.apple.remotemanagementd/
                                                                  RMAdminStore-Local.sqlite (Screen
                                                                  Time's hourly totals per app)
    apple-podcasts      AppDomainGroup-group.com.apple.podcasts       Documents/MTLibrary.sqlite (the
                                                                  Podcasts library: one listen per
                                                                  played episode; `--only podcasts`)

A source whose `relative_path` has a wildcard (`pattern`) is found by matching every file row of its
domain against it (`fnmatch`, the whole path): the first match is the store, the rest are copied
beside it like its -wal/-shm siblings, and the adapter runs on the copies' folder, not the store.
A source's `companions` — other files, by path or glob and from any domain — are copied beside the
store the same way, with their own -wal/-shm, so an adapter finds beside the copy what it finds
beside the store on the phone (Books' library next to its annotations).

Contacts come first so the record has its people before the chats that name them; WhatsApp's own
contacts come before its chats for the same reason (RFC 0006).

EXTRAS are the stores only an encrypted backup carries — the call log, Health, Safari's
history. Each has its adapter and runs like the SOURCES:

    ios-calls           HomeDomain                                    Library/CallHistoryDB/
                                                                  CallHistory.storedata
    health              HealthDomain                                  Health/healthdb.sqlite (copied
                                                                  first: it names the sources),
                                                                  Health/healthdb_secure.sqlite
                                                                  (the samples; `apple-health` runs)
    safari              HomeDomain                                    Library/Safari/History.db
                                                                  (`safari` runs, RFC 0017)

An adapter never reads the backup in place. `plan` finds each source's store, its -wal/-shm
siblings and its media files; `copy` puts them under one folder with their original names — the
store, the siblings beside it, the media in the folder the adapter looks for beside the store
(`Message/`, `Attachments/`) — and checks every copy against the stored blob: byte for byte for
a plain file, the blob's length less its PKCS#7 padding for a decrypted one. The manifest's
`Size` is what the file measured on the phone and can be stale against the blob (seen on iOS
26.5), so a copy that matches the blob but not `Size` is one warning naming the file and both
sizes, never an error. The adapters then run on the copies. `write_copies` records every copy
in `copies.json` beside them: domain, path, copy, bytes, whether it was decrypted and under
which protection class, and that warning when there was one — never a key.
"""

from __future__ import annotations

import hashlib
import json
import plistlib
import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass, field
from fnmatch import fnmatch, fnmatchcase
from pathlib import Path, PurePosixPath
from typing import Any

from . import ios_backup_crypto
from .ios_backup_crypto import DecryptError, MissingExtra, WrongPassword

__all__ = ["DecryptError", "MissingExtra", "WrongPassword"]

MANIFEST_DB = "Manifest.db"
MANIFEST_PLIST = "Manifest.plist"
COPIES = "copies.json"
HOME = "HomeDomain"
MEDIA = "MediaDomain"
WHATSAPP = "AppDomainGroup-group.net.whatsapp.WhatsApp.shared"
NOTES = "AppDomainGroup-group.com.apple.notes"
REMINDERS = "AppDomainGroup-group.com.apple.reminders"
COPILOT = "AppDomainGroup-group.com.copilot.production"
SPLITWISE = "AppDomain-com.Splitwise.SplitwiseMobile"
BEEPER = "AppDomainGroup-group.beeper.chat.ios"
LINE_APP = "AppDomain-jp.naver.line"
LINE = "AppDomainGroup-group.com.linecorp.line"
LINE_STORE = "Library/Application Support/PrivateStore/P_*"
TWITTER = "AppDomainGroup-group.com.atebits.Tweetie2"
HEALTH = "HealthDomain"
BOOKS = "AppDomain-com.apple.iBooks"
VOICE_MEMOS = "AppDomainGroup-group.com.apple.VoiceMemos.shared"
CAMERA_ROLL = "CameraRollDomain"
WITHINGS = "AppDomain-com.withings.wiScaleNG"
MYFITNESSPAL = "AppDomain-com.myfitnesspal.mfp"
SBB = "AppDomainGroup-group.ch.sbb.SBBMobile"
SBB_APP = "AppDomain-5Q4J53EFRC.com.sbb.ch"
EASYPARK = "AppDomain-net.easypark.app"
WISPR = "AppDomain-com.wispr.flowapp"
FLIGHTY = "AppDomain-com.flightyapp.flighty"
SCREEN_TIME = "Library/Application Support/com.apple.remotemanagementd/RMAdminStore-Local.sqlite"
PODCASTS = "AppDomainGroup-group.com.apple.podcasts"
FILE_FLAG = 1
SIBLINGS = ("-wal", "-shm")  # a SQLite store's write-ahead log and its index, when the backup has them


class NotABackup(Exception):
    """The folder is not an iOS backup this module can read."""


class CopyError(Exception):
    """A copy came out a different size from the stored blob it was made from."""


@dataclass(frozen=True)
class Source:
    """One adapter's store: where the phone keeps it, and its media folder when it has one."""

    name: str  # the adapter's NAME, and the copy's folder name
    domain: str
    relative_path: str  # POSIX, as Manifest.db spells it; with `*` or `?` a pattern over the domain
    media: tuple[str, str] | None = None  # (domain, folder prefix); copied beside the store as its last part
    adapter: bool = True  # False: copied out, nothing runs on it; `note` says why it is there
    note: str = "no adapter yet"
    files: str | None = None  # a folder source: `relative_path` is a folder, this the file names under it
    # (domain, path or glob) of files copied beside the store under their own names, with their -wal/-shm:
    # a library the adapter looks up beside the store, a store from another container (`fnmatch`, as
    # `relative_path`). A plain path names one file.
    companions: tuple[tuple[str, str], ...] = ()
    media_suffixes: tuple[
        str, ...
    ] = ()  # when set, only media whose suffix (lower-case) is one of these is copied

    @property
    def store_name(self) -> str:
        return self.files if self.files is not None else PurePosixPath(self.relative_path).name

    @property
    def pattern(self) -> bool:
        """Whether `relative_path` is a pattern: several stores may match, and the adapter then
        runs on the folder they were copied to."""
        return any(c in self.relative_path for c in "*?[")

    @property
    def media_folder(self) -> str | None:
        """The folder name the adapter looks for beside the store (`Message`, `Attachments`)."""
        return PurePosixPath(self.media[1]).name if self.media else None


SOURCES: tuple[Source, ...] = (
    Source("ios-contacts", HOME, "Library/AddressBook/AddressBook.sqlitedb"),
    Source("whatsapp-contacts", WHATSAPP, "ContactsV2.sqlite"),
    Source("whatsapp", WHATSAPP, "ChatStorage.sqlite", media=(WHATSAPP, "Message")),
    Source("imessage", HOME, "Library/SMS/sms.db", media=(MEDIA, "Library/SMS/Attachments")),
    Source("ios-calendar", HOME, "Library/Calendar/Calendar.sqlitedb"),
    Source("ios-notes", NOTES, "NoteStore.sqlite"),
    Source(
        "apple-wallet", HOME, "Library/Passes/Cards", files="pass.json"
    ),  # an unpacked .pkpass folder per pass; pass.json is the one file the adapter reads
    Source("easypark", EASYPARK, "Documents", files="recentparkings_*.json"),  # named after the user
    Source("wispr-flow", WISPR, "Documents/database.sqlite"),  # the recordings beside it are not copied
    Source("flighty", FLIGHTY, "Documents/MainFlightyDatabase.db"),  # the same lines as the CSV export
    Source("apple-reminders", REMINDERS, "Container_v1/Stores/Data-*.sqlite"),
    Source("copilot", COPILOT, "database/CopilotDB.sqlite"),
    Source("splitwise", SPLITWISE, "Library/Application Support/database.sqlite"),
    Source("beeper", BEEPER, "BeeperStore.sqlite"),
    Source(  # the companions first, so they are beside the store when the adapter reads it
        "line",
        LINE_APP,
        LINE_STORE + "/Contacts Syncing/Contacts.sqlite",
        adapter=False,
        note="read beside Line.sqlite",
    ),
    Source(
        "line",
        LINE,
        LINE_STORE + "/Messages/UnifiedGroup.sqlite",
        adapter=False,
        note="read beside Line.sqlite",
    ),
    Source("line", LINE, LINE_STORE + "/Messages/Line.sqlite"),
    Source("twitter", TWITTER, "com.atebits.tweetie.databases/v1/*/*-dmv2.db"),
    Source(  # `apple-books` (RFC 0022); the library that names the books is copied beside the store
        "apple-books",
        BOOKS,
        "Documents/storeFiles/AEAnnotation*.sqlite",
        companions=((BOOKS, "Documents/BKLibrary/BKLibrary*.sqlite"),),
    ),
    Source(  # `voice-memos` (RFC 0023); the audio beside the store on the phone lands under Recordings/
        "voice-memos",
        VOICE_MEMOS,
        "Recordings/CloudRecordings.db",
        media=(VOICE_MEMOS, "Recordings"),
        media_suffixes=(".m4a", ".qta"),
    ),
    Source("apple-photos", CAMERA_ROLL, "Media/PhotoData/Photos.sqlite"),  # the library, not the pixels
    Source(  # `withings` (RFC 0014): every profile's WTHealth and Measure stores, read as one folder
        "withings",
        WITHINGS,
        "Library/Application Support/coredata/*_WTHealth.sqlite",
        companions=((WITHINGS, "Library/Application Support/coredata/*_Measure.sqlite"),),
    ),
    Source("myfitnesspal", MYFITNESSPAL, "Documents/maindb.sqlite"),  # `myfitnesspal` (RFC 0014)
    Source(  # `sbb` (RFC 0020): the tickets, with the past journeys from the app's own container beside them
        "sbb",
        SBB,
        "SbbMobile.db",
        companions=((SBB_APP, "Documents/ch.sbb.coredata.pasttrips.sqlite"),),
    ),
    Source("screentime", HOME, SCREEN_TIME),  # `screentime`: Screen Time's hourly totals per app
    Source("apple-podcasts", PODCASTS, "Documents/MTLibrary.sqlite"),  # `apple-podcasts` (RFC 0019)
)

EXTRAS: tuple[Source, ...] = (  # only an encrypted backup carries these
    Source("ios-calls", HOME, "Library/CallHistoryDB/CallHistory.storedata"),
    Source(  # the companion first, so it is beside the store when the adapter reads the store
        "health", HEALTH, "Health/healthdb.sqlite", adapter=False, note="read beside healthdb_secure.sqlite"
    ),
    Source("health", HEALTH, "Health/healthdb_secure.sqlite"),  # `apple-health` (RFC 0014)
    Source("safari", HOME, "Library/Safari/History.db"),  # HomeDomain, not the app's; `safari` (RFC 0017)
)


def source(name: str) -> Source | None:
    """The source called `name`; `contacts`, `calendar`, `notes`, `calls` and `reminders` stand for
    their `ios-` and `apple-` names."""
    return next(
        (
            s
            for s in SOURCES + EXTRAS
            if name in (s.name, s.name.removeprefix("ios-"), s.name.removeprefix("apple-"))
        ),
        None,
    )


@dataclass(frozen=True)
class BackupFile:
    """One file row of Manifest.db and where its bytes are; `size` is None when they are not there,
    else the manifest's `Size` (the file as measured on the phone, the plaintext size for an
    encrypted one; it can be stale against the stored blob) or, when the row has none, the
    blob's. `key` is the file's unwrapped key when the backup is encrypted — never printed — and
    `protection_class` the class it was wrapped under."""

    domain: str
    relative_path: str
    path: Path
    size: int | None
    protection_class: int | None = None
    key: bytes | None = field(default=None, repr=False, compare=False)

    @property
    def encrypted(self) -> bool:
        return self.key is not None

    @property
    def name(self) -> str:
        return PurePosixPath(self.relative_path).name

    @property
    def parts(self) -> tuple[str, ...]:
        return PurePosixPath(self.relative_path).parts


class Manifest:
    """A backup folder's Manifest.db and Manifest.plist, read only."""

    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)
        self.db = self.folder / MANIFEST_DB
        if not self.db.is_file():
            raise NotABackup(
                f"{self.folder}: no {MANIFEST_DB} here; an iOS backup folder is what Finder shows under"
                " Manage Backups → Show in Finder"
            )
        self.encrypted, self.udid, self._keybag_blob, self._manifest_key = self._plist()
        self.keybag: ios_backup_crypto.Keybag | None = None
        if not self.encrypted:
            self._check_readable()

    def _check_readable(self) -> None:
        try:
            with closing(self._open()) as con:
                con.execute("SELECT fileID, domain, relativePath, flags, file FROM Files LIMIT 1").fetchall()
        except sqlite3.Error as e:
            raise NotABackup(f"{self.db}: cannot be read as a backup manifest ({e})") from e

    def _plist(self) -> tuple[bool, str, bytes | None, bytes | None]:
        """(IsEncrypted, the phone's identifier — else the folder's own name, BackupKeyBag, ManifestKey)."""
        fallback = self.folder.resolve().name or "unknown"
        plist = self.folder / MANIFEST_PLIST
        if not plist.is_file():
            return False, fallback, None, None
        try:
            with plist.open("rb") as fh:
                data = plistlib.load(fh)
        except (plistlib.InvalidFileException, ValueError, OSError):
            return False, fallback, None, None
        if not isinstance(data, dict):
            return False, fallback, None, None
        lockdown = data.get("Lockdown")
        udid = lockdown.get("UniqueDeviceID") if isinstance(lockdown, dict) else None
        udid = udid.strip() if isinstance(udid, str) and udid.strip() else fallback
        keybag = data.get("BackupKeyBag")
        manifest_key = data.get("ManifestKey")
        return (
            bool(data.get("IsEncrypted", False)),
            udid,
            keybag if isinstance(keybag, bytes) else None,
            manifest_key if isinstance(manifest_key, bytes) else None,
        )

    @property
    def unlocked(self) -> bool:
        """Whether the rows can be read: an unencrypted backup always, an encrypted one after `unlock`."""
        return not self.encrypted or self.keybag is not None

    def unlock(self, password: str, dest_db: Path) -> None:
        """Unlock the keybag with `password` and decrypt Manifest.db into `dest_db`, which the rows
        are read from afterwards. Raises MissingExtra without `cryptography`, NotABackup when the
        plist lacks the keybag or the manifest key, WrongPassword before anything is written, and
        DecryptError when the manifest's key or bytes are not what the format says."""
        if not self.encrypted:
            return
        if self._keybag_blob is None:
            raise NotABackup(f"{self.folder / MANIFEST_PLIST}: encrypted, but no BackupKeyBag in it")
        if self._manifest_key is None:
            raise NotABackup(f"{self.folder / MANIFEST_PLIST}: encrypted, but no ManifestKey in it")
        if not ios_backup_crypto.available():
            raise MissingExtra()
        keybag = ios_backup_crypto.Keybag.parse(self._keybag_blob)
        keybag.unlock(password)  # WrongPassword here, before any file is touched
        number, wrapped = ios_backup_crypto.split_class(self._manifest_key)
        key = keybag.unwrap(number, wrapped)
        dest_db.parent.mkdir(parents=True, exist_ok=True)
        try:
            ios_backup_crypto.decrypt_file(self.folder / MANIFEST_DB, dest_db, key)
        except OSError as e:
            raise DecryptError(f"{MANIFEST_DB}: {e}") from e
        self.db = dest_db
        self.keybag = keybag
        self._check_readable()

    def _open(self) -> sqlite3.Connection:
        """Read-only and immutable: SQLite neither locks the file nor writes a journal beside it."""
        return sqlite3.connect(f"{self.db.resolve().as_uri()}?mode=ro&immutable=1", uri=True)

    def _located(self, file_id: str, domain: str, relative_path: str, blob: object) -> BackupFile:
        candidates = (self.folder / file_id[:2] / file_id, self.folder / file_id)  # two-level, then flat
        protection_class: int | None = None
        key: bytes | None = None
        size: int | None = None
        if self.keybag is not None:
            protection_class, key, size = self._file_key(relative_path, blob)
        else:
            size = _claimed_size(blob)
        for path in candidates:
            if path.is_file():
                if size is None:
                    size = path.stat().st_size
                return BackupFile(domain, relative_path, path, size, protection_class, key)
        return BackupFile(domain, relative_path, candidates[0], None, protection_class, key)

    def _file_key(self, relative_path: str, blob: object) -> tuple[int | None, bytes | None, int | None]:
        """From the row's `file` plist (an NSKeyedArchiver MBFile): (protection class, the unwrapped
        file key, the plaintext size). A row without a key is a plaintext file; a key that will
        not unwrap is a DecryptError naming the path, never a silent skip."""
        assert self.keybag is not None
        if not isinstance(blob, bytes):
            return None, None, None
        try:
            data = plistlib.loads(blob)
        except (plistlib.InvalidFileException, ValueError) as e:
            raise DecryptError(f"{relative_path}: its Manifest.db row is not a file plist ({e})") from e
        root = _archived_root(data)
        if root is None:
            return None, None, None
        size = root.get("Size")
        number = root.get("ProtectionClass")
        wrapped = _archived(data, root.get("EncryptionKey"))
        if isinstance(wrapped, dict):
            wrapped = wrapped.get("NS.data")
        if not isinstance(wrapped, bytes):
            return number if isinstance(number, int) else None, None, size if isinstance(size, int) else None
        try:
            prefixed_class, wrapped_key = ios_backup_crypto.split_class(wrapped)
            key = self.keybag.unwrap(prefixed_class, wrapped_key)
        except DecryptError as e:
            raise DecryptError(f"{relative_path}: {e}") from e
        return prefixed_class, key, size if isinstance(size, int) else None

    def file(self, domain: str, relative_path: str) -> BackupFile | None:
        """The file row at exactly this domain and path, or None (a directory row is not a file;
        an encrypted backup that is not unlocked has no readable rows)."""
        if not self.unlocked:
            return None
        with closing(self._open()) as con:
            rows = con.execute(
                "SELECT fileID, flags, file FROM Files WHERE domain = ? AND relativePath = ?",
                (domain, relative_path),
            ).fetchall()
        for file_id, flags, blob in rows:
            if flags == FILE_FLAG and isinstance(file_id, str):
                return self._located(file_id, domain, relative_path, blob)
        return None

    def files_matching(self, domain: str, pattern: str) -> list[BackupFile]:
        """Every file row of `domain` whose whole relativePath matches `pattern` (fnmatch, case
        kept), in path order. The rows of a domain are read once; the match is in Python, so a
        bracket or a `?` in the pattern means what fnmatch says, not what SQL would."""
        if not self.unlocked:
            return []
        with closing(self._open()) as con:
            rows = con.execute(
                "SELECT fileID, relativePath, flags, file FROM Files WHERE domain = ? ORDER BY relativePath",
                (domain,),
            ).fetchall()
        return [
            self._located(file_id, domain, relative_path, blob)
            for file_id, relative_path, flags, blob in rows
            if flags == FILE_FLAG
            and isinstance(file_id, str)
            and isinstance(relative_path, str)
            and fnmatchcase(relative_path, pattern)
        ]

    def files_under(self, domain: str, prefix: str) -> Iterator[BackupFile]:
        """Every file row below `prefix` in `domain`, in path order. A path that would leave the
        folder (`..`, an empty part) is never yielded: the copy stays inside its media folder."""
        if not self.unlocked:
            return
        head = PurePosixPath(prefix).parts
        with closing(self._open()) as con:
            rows = con.execute(
                "SELECT fileID, relativePath, flags, file FROM Files WHERE domain = ? AND relativePath LIKE ?"
                " ORDER BY relativePath",
                (domain, prefix + "/%"),
            ).fetchall()
        for file_id, relative_path, flags, blob in rows:
            if flags != FILE_FLAG or not isinstance(file_id, str) or not isinstance(relative_path, str):
                continue
            parts = PurePosixPath(relative_path).parts
            rest = parts[len(head) :]
            if parts[: len(head)] != head or not rest or any(p in ("..", "", "/") for p in rest):
                continue
            yield self._located(file_id, domain, relative_path, blob)


def _claimed_size(blob: object) -> int | None:
    """The `Size` an unencrypted backup's file plist claims, or None when the row has no readable
    plist (an older or a synthetic backup leaves the column NULL)."""
    if not isinstance(blob, bytes):
        return None
    try:
        root = _archived_root(plistlib.loads(blob))
    except (plistlib.InvalidFileException, ValueError):
        return None
    size = root.get("Size") if root is not None else None
    return size if isinstance(size, int) else None


def _archived_root(data: object) -> dict[str, Any] | None:
    """The root object of an NSKeyedArchiver plist, when it is a dictionary."""
    if not isinstance(data, dict):
        return None
    top = data.get("$top")
    root = _archived(data, top.get("root")) if isinstance(top, dict) else None
    return root if isinstance(root, dict) else None


def _archived(data: dict[str, Any], value: object) -> object:
    """`value` with one level of NSKeyedArchiver indirection followed: a UID names an `$objects` entry."""
    if isinstance(value, plistlib.UID):
        objects = data.get("$objects")
        if isinstance(objects, list) and 0 <= value.data < len(objects):
            return objects[value.data]
        return None
    return value


@dataclass(frozen=True)
class Copy:
    """One file `copy` made: the row it came from, where the copy is, how many bytes it holds,
    and the one-line warning when the manifest's `Size` disagreed with the stored blob."""

    file: BackupFile
    target: Path
    bytes: int
    warning: str | None = None


@dataclass
class Plan:
    """What one source would import: its store (None when the backup has no row for it), the
    store's siblings — its -wal/-shm, for a pattern source the other stores that matched, and the
    source's companions, each with theirs — and its media files. `found` is false when the row is
    there but the bytes are not (`listed`). A folder source (`Source.files`) has no store: its files
    are `media`, and it is listed and found when at least one of them is."""

    source: Source
    store: BackupFile | None
    siblings: list[BackupFile] = field(default_factory=list)
    media: list[BackupFile] = field(default_factory=list)
    copied: list[Copy] = field(default_factory=list)  # filled by `copy`

    @property
    def listed(self) -> bool:
        if self.source.files is not None:
            return bool(self.media)
        return self.store is not None

    @property
    def found(self) -> bool:
        if self.source.files is not None:
            return any(f.size is not None for f in self.media)
        return self.store is not None and self.store.size is not None

    @property
    def files(self) -> list[BackupFile]:
        """Every file that would be copied, the store first; only the ones the backup really holds."""
        if self.source.files is not None:
            return [f for f in self.media if f.size is not None]
        if not self.found or self.store is None:
            return []
        return [f for f in (self.store, *self.siblings, *self.media) if f.size is not None]

    @property
    def bytes(self) -> int:
        return sum(f.size or 0 for f in self.files)


def plan(manifest: Manifest, sources: tuple[Source, ...] = SOURCES) -> list[Plan]:
    """One Plan per source, in SOURCES order."""
    plans: list[Plan] = []
    for s in sources:
        if s.files is not None:
            found = [f for f in manifest.files_under(s.domain, s.relative_path) if fnmatch(f.name, s.files)]
            plans.append(Plan(s, None, media=found))
            continue
        stores = manifest.files_matching(s.domain, s.relative_path) if s.pattern else []
        store = (stores[0] if stores else None) if s.pattern else manifest.file(s.domain, s.relative_path)
        p = Plan(s, store)
        if p.found:
            for i, each in enumerate(stores if s.pattern else [p.store]):
                if i and each is not None and each.size is not None:
                    p.siblings.append(each)
                if each is not None:
                    for suffix in SIBLINGS:
                        sibling = manifest.file(s.domain, each.relative_path + suffix)
                        if sibling is not None:
                            p.siblings.append(sibling)
            for domain, glob in s.companions:
                for other in manifest.files_matching(domain, glob):
                    if other.relative_path.endswith(SIBLINGS):
                        continue
                    p.siblings.append(other)
                    for suffix in SIBLINGS:
                        sibling = manifest.file(domain, other.relative_path + suffix)
                        if sibling is not None:
                            p.siblings.append(sibling)
            if s.media is not None:
                suffixes = s.media_suffixes
                p.media.extend(
                    f
                    for f in manifest.files_under(*s.media)
                    if not suffixes or PurePosixPath(f.relative_path).suffix.lower() in suffixes
                )
        plans.append(p)
    return plans


def copy(p: Plan, dest: Path) -> Path:
    """Copy the plan's files under `dest` with their original names and return the store's copy.

    The store and its siblings land in `dest` itself (a second store of a pattern source whose
    name repeats the first's goes under its own parent folder's name); a sibling left by an
    earlier copy that this backup does not have is removed, so the store is never read with
    someone else's journal. Media
    lands under `dest/<media folder>/` with its path below the backup's media prefix. Every copy is
    checked against the stored blob (`_copy_file`); a mismatch raises CopyError, a stale manifest
    `Size` is only a warning on the Copy. An encrypted file is decrypted on the way, a chunk at a
    time. Every copy is noted in `p.copied`. A folder source's files land under `dest` with their
    paths below the backup's folder, and `dest` itself is returned: the adapter reads the folder."""
    if not p.found:
        raise ValueError(f"{p.source.name}: nothing to copy")
    dest.mkdir(parents=True, exist_ok=True)
    p.copied.clear()
    if p.source.files is not None:
        head = len(PurePosixPath(p.source.relative_path).parts)
        for f in p.files:
            p.copied.append(_copy_file(f, dest.joinpath(*f.parts[head:])))
        return dest
    if p.store is None:
        raise ValueError(f"{p.source.name}: nothing to copy")
    store_copy = _copy_file(p.store, dest / p.store.name)
    p.copied.append(store_copy)
    present = {f.name for f in p.siblings if f.size is not None}
    for suffix in SIBLINGS:
        stale = dest / (p.store.name + suffix)
        if p.store.name + suffix not in present and stale.is_file():
            stale.unlink()
    used = {p.store.name}
    for sibling in p.siblings:
        if sibling.size is not None:
            target = dest / sibling.name
            if sibling.name in used and len(sibling.parts) > 1:
                target = dest / sibling.parts[-2] / sibling.name
            used.add(sibling.name)
            p.copied.append(_copy_file(sibling, target))
    if p.source.media is not None and p.source.media_folder is not None:
        head = len(PurePosixPath(p.source.media[1]).parts)
        folder = dest / p.source.media_folder
        for f in p.media:
            if f.size is not None:
                p.copied.append(_copy_file(f, folder.joinpath(*f.parts[head:])))
    return store_copy.target


def plain_chunks(f: BackupFile, chunk: int = ios_backup_crypto.CHUNK) -> Iterator[bytes]:
    """The bytes of a file row as the phone held them, a chunk at a time and never whole: read
    straight from the stored blob for a plain file, decrypted on the way for an encrypted one
    (`decrypt_chunks`, the manifest's `Size` deciding a last block that is not padding). The
    backup is only read. For a reader that hashes or streams a file somewhere without a copy."""
    if f.key is not None:
        yield from ios_backup_crypto.decrypt_chunks(f.path, f.key, f.size, chunk)
        return
    with f.path.open("rb") as fh:
        while piece := fh.read(chunk):
            yield piece


def digest(f: BackupFile) -> tuple[str, int]:
    """(the SHA-256 of the file's plaintext, its length), streamed through `plain_chunks`."""
    h = hashlib.sha256()
    size = 0
    for piece in plain_chunks(f):
        h.update(piece)
        size += len(piece)
    return h.hexdigest(), size


def _copy_file(f: BackupFile, target: Path) -> Copy:
    """Copy (or decrypt) `f` to `target` and check the copy against the stored blob: a plain file
    byte for byte, a decrypted one against the blob's length less the PKCS#7 padding stripped (a
    blob whose last block is not valid padding is not the plaintext the manifest describes, so
    it fails). The manifest's `Size` is only compared afterwards, and a difference is the Copy's
    warning."""
    target.parent.mkdir(parents=True, exist_ok=True)
    stored = f.path.stat().st_size
    if f.key is not None:
        done = ios_backup_crypto.decrypt_file(f.path, target, f.key, f.size)
        copied = target.stat().st_size
        if not done.padding:
            raise CopyError(
                f"{f.relative_path}: decrypted {copied:,} bytes, but the stored blob ({stored:,} bytes)"
                " does not end in PKCS#7 padding"
            )
        expected = stored - done.padding
        if copied != expected:
            raise CopyError(
                f"{f.relative_path}: decrypted {copied:,} bytes, the stored blob is {stored:,}"
                f" less {done.padding} bytes of padding = {expected:,}"
            )
    else:
        shutil.copyfile(f.path, target)
        copied = target.stat().st_size
        if copied != stored:
            raise CopyError(f"{f.relative_path}: copied {copied:,} bytes, the stored blob is {stored:,}")
    warning = None
    if copied != f.size:
        warning = (
            f"{f.relative_path}: copied {copied:,} bytes, the manifest says {f.size:,}"
            " (its Size is what the file measured on the phone; the stored blob is what was copied)"
        )
    return Copy(f, target, copied, warning)


def write_copies(inbox: Path, manifest: Manifest, plans: list[Plan]) -> Path:
    """`<inbox>/copies.json`: one entry per file `copy` put under `inbox`, merged over the entries
    an earlier run left for sources this run did not touch. `encrypted` says whether the backup
    was; each entry says whether its file was decrypted and under which protection class, its
    `bytes` are the copy's, and `warning` is there when the manifest's `Size` disagreed with the
    stored blob. Keys are never written. Returns the file's path."""
    path = inbox / COPIES
    previous: list[dict[str, Any]] = []
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("files"), list):
                previous = [e for e in data["files"] if isinstance(e, dict)]
        except (OSError, ValueError):
            previous = []
    touched = {p.source.name for p in plans}
    entries = [e for e in previous if e.get("source") not in touched]
    for p in plans:
        for c in p.copied:
            entry: dict[str, Any] = {
                "source": p.source.name,
                "domain": c.file.domain,
                "path": c.file.relative_path,
                "copy": c.target.relative_to(inbox).as_posix(),
                "bytes": c.bytes,
                "encrypted": c.file.encrypted,
                "protection_class": c.file.protection_class,
            }
            if c.warning is not None:
                entry["warning"] = c.warning
            entries.append(entry)
    entries.sort(key=lambda e: str(e.get("copy", "")))
    record = {"backup": manifest.udid, "encrypted": manifest.encrypted, "files": entries}
    inbox.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
