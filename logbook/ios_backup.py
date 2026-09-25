"""An unencrypted iOS backup folder (Finder, iTunes) → the files the phone adapters read.

A backup is a folder of files named by hash. Manifest.db, a SQLite file, has one row per file in
its Files table (fileID, domain, relativePath, flags: 1 a file, 2 a directory, 4 a symlink); the
bytes of a file are at <fileID[:2]>/<fileID> (older backups kept them flat at <fileID>).
Manifest.plist says whether the backup is encrypted (IsEncrypted), in which case Manifest.db is
encrypted too and nothing here can be read; it also carries the phone's identifier under
Lockdown/UniqueDeviceID. Both are read and never written: Manifest.db is opened `mode=ro`,
`immutable=1`, so not even a journal appears beside it.

SOURCES lists, in import order, the store each adapter reads and where the phone keeps it:

    ios-contacts        HomeDomain                                    Library/AddressBook/AddressBook.sqlitedb
    whatsapp-contacts   AppDomainGroup-group.net.whatsapp.WhatsApp.shared  ContactsV2.sqlite
    whatsapp            the same                                      ChatStorage.sqlite, media under Message/
    imessage            HomeDomain                                    Library/SMS/sms.db,
                        MediaDomain                                   media under Library/SMS/Attachments/
    ios-calendar        HomeDomain                                    Library/Calendar/Calendar.sqlitedb
    ios-notes           AppDomainGroup-group.com.apple.notes          NoteStore.sqlite

Contacts come first so the record has its people before the chats that name them; WhatsApp's own
contacts come before its chats for the same reason (RFC 0006).

An adapter never reads the backup in place. `plan` finds each source's store, its -wal/-shm
siblings and its media files; `copy` puts them under one folder with their original names — the
store, the siblings beside it, the media in the folder the adapter looks for beside the store
(`Message/`, `Attachments/`) — and checks every copy by size. The adapters then run on the copies.
"""

from __future__ import annotations

import plistlib
import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

MANIFEST_DB = "Manifest.db"
MANIFEST_PLIST = "Manifest.plist"
HOME = "HomeDomain"
MEDIA = "MediaDomain"
WHATSAPP = "AppDomainGroup-group.net.whatsapp.WhatsApp.shared"
NOTES = "AppDomainGroup-group.com.apple.notes"
FILE_FLAG = 1
SIBLINGS = ("-wal", "-shm")  # a SQLite store's write-ahead log and its index, when the backup has them


class NotABackup(Exception):
    """The folder is not an iOS backup this module can read."""


class CopyError(Exception):
    """A copy came out a different size from its original."""


@dataclass(frozen=True)
class Source:
    """One adapter's store: where the phone keeps it, and its media folder when it has one."""

    name: str  # the adapter's NAME, and the copy's folder name
    domain: str
    relative_path: str  # POSIX, as Manifest.db spells it
    media: tuple[str, str] | None = None  # (domain, folder prefix); copied beside the store as its last part

    @property
    def store_name(self) -> str:
        return PurePosixPath(self.relative_path).name

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
)


def source(name: str) -> Source | None:
    """The source called `name`; `contacts`, `calendar` and `notes` stand for their `ios-` names."""
    return next((s for s in SOURCES if name in (s.name, s.name.removeprefix("ios-"))), None)


@dataclass(frozen=True)
class BackupFile:
    """One file row of Manifest.db and where its bytes are; `size` is None when they are not there."""

    domain: str
    relative_path: str
    path: Path
    size: int | None

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
        self.encrypted, self.udid = self._plist()
        if not self.encrypted:
            try:
                with closing(self._open()) as con:
                    con.execute("SELECT fileID, domain, relativePath, flags FROM Files LIMIT 1").fetchall()
            except sqlite3.Error as e:
                raise NotABackup(f"{self.db}: cannot be read as a backup manifest ({e})") from e

    def _plist(self) -> tuple[bool, str]:
        """(IsEncrypted, the phone's identifier — else the folder's own name)."""
        fallback = self.folder.resolve().name or "unknown"
        plist = self.folder / MANIFEST_PLIST
        if not plist.is_file():
            return False, fallback
        try:
            with plist.open("rb") as fh:
                data = plistlib.load(fh)
        except (plistlib.InvalidFileException, ValueError, OSError):
            return False, fallback
        if not isinstance(data, dict):
            return False, fallback
        lockdown = data.get("Lockdown")
        udid = lockdown.get("UniqueDeviceID") if isinstance(lockdown, dict) else None
        udid = udid.strip() if isinstance(udid, str) and udid.strip() else fallback
        return bool(data.get("IsEncrypted", False)), udid

    def _open(self) -> sqlite3.Connection:
        """Read-only and immutable: SQLite neither locks the file nor writes a journal beside it."""
        return sqlite3.connect(f"{self.db.resolve().as_uri()}?mode=ro&immutable=1", uri=True)

    def _located(self, file_id: str, domain: str, relative_path: str) -> BackupFile:
        candidates = (self.folder / file_id[:2] / file_id, self.folder / file_id)  # two-level, then flat
        for path in candidates:
            if path.is_file():
                return BackupFile(domain, relative_path, path, path.stat().st_size)
        return BackupFile(domain, relative_path, candidates[0], None)

    def file(self, domain: str, relative_path: str) -> BackupFile | None:
        """The file row at exactly this domain and path, or None (a directory row is not a file)."""
        with closing(self._open()) as con:
            rows = con.execute(
                "SELECT fileID, flags FROM Files WHERE domain = ? AND relativePath = ?",
                (domain, relative_path),
            ).fetchall()
        for file_id, flags in rows:
            if flags == FILE_FLAG and isinstance(file_id, str):
                return self._located(file_id, domain, relative_path)
        return None

    def files_under(self, domain: str, prefix: str) -> Iterator[BackupFile]:
        """Every file row below `prefix` in `domain`, in path order. A path that would leave the
        folder (`..`, an empty part) is never yielded: the copy stays inside its media folder."""
        head = PurePosixPath(prefix).parts
        with closing(self._open()) as con:
            rows = con.execute(
                "SELECT fileID, relativePath, flags FROM Files WHERE domain = ? AND relativePath LIKE ?"
                " ORDER BY relativePath",
                (domain, prefix + "/%"),
            ).fetchall()
        for file_id, relative_path, flags in rows:
            if flags != FILE_FLAG or not isinstance(file_id, str) or not isinstance(relative_path, str):
                continue
            parts = PurePosixPath(relative_path).parts
            rest = parts[len(head) :]
            if parts[: len(head)] != head or not rest or any(p in ("..", "", "/") for p in rest):
                continue
            yield self._located(file_id, domain, relative_path)


@dataclass
class Plan:
    """What one source would import: its store (None when the backup has no row for it), the
    store's siblings and its media files. `found` is false when the row is there but the bytes
    are not (`listed`)."""

    source: Source
    store: BackupFile | None
    siblings: list[BackupFile] = field(default_factory=list)
    media: list[BackupFile] = field(default_factory=list)

    @property
    def listed(self) -> bool:
        return self.store is not None

    @property
    def found(self) -> bool:
        return self.store is not None and self.store.size is not None

    @property
    def files(self) -> list[BackupFile]:
        """Every file that would be copied, the store first; only the ones the backup really holds."""
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
        store = manifest.file(s.domain, s.relative_path)
        p = Plan(s, store)
        if p.found:
            for suffix in SIBLINGS:
                sibling = manifest.file(s.domain, s.relative_path + suffix)
                if sibling is not None:
                    p.siblings.append(sibling)
            if s.media is not None:
                p.media.extend(manifest.files_under(*s.media))
        plans.append(p)
    return plans


def copy(p: Plan, dest: Path) -> Path:
    """Copy the plan's files under `dest` with their original names and return the store's copy.

    The store and its siblings land in `dest` itself; a sibling left by an earlier copy that this
    backup does not have is removed, so the store is never read with someone else's journal. Media
    lands under `dest/<media folder>/` with its path below the backup's media prefix. Every copy is
    checked by size against its original; a mismatch raises CopyError."""
    if not p.found or p.store is None:
        raise ValueError(f"{p.source.name}: nothing to copy")
    dest.mkdir(parents=True, exist_ok=True)
    store_copy = _copy_file(p.store, dest / p.store.name)
    present = {f.name for f in p.siblings if f.size is not None}
    for suffix in SIBLINGS:
        stale = dest / (p.store.name + suffix)
        if p.store.name + suffix not in present and stale.is_file():
            stale.unlink()
    for sibling in p.siblings:
        if sibling.size is not None:
            _copy_file(sibling, dest / sibling.name)
    if p.source.media is not None and p.source.media_folder is not None:
        head = len(PurePosixPath(p.source.media[1]).parts)
        folder = dest / p.source.media_folder
        for f in p.media:
            if f.size is not None:
                _copy_file(f, folder.joinpath(*f.parts[head:]))
    return store_copy


def _copy_file(f: BackupFile, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(f.path, target)
    copied = target.stat().st_size
    if copied != f.size:
        raise CopyError(f"{f.relative_path}: copied {copied:,} bytes, the backup has {f.size:,}")
    return target
