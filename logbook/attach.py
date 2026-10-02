"""`logbook attach`: the SPEC §1.1 store, `<root>/attachments/<sha256>`, filled from an iOS backup,
counted, and checked.

A message or photo line written from a phone backup names its media by digest and by where the phone
keeps the file: `extra.media = {local_path, sha256, bytes}` (`whatsapp`, `imessage` — and the rest of
a message's files under `extra.more_media` —, `apple-photos`, which also carries the digest as RFC
0002 `content_hash`). The bytes stay on the phone until this pass: `import_backup` reads every such
line of the sources asked for through the index, finds each file in the backup's Manifest.db by the
source's domain and the path below its media folder (SOURCES), streams it — decrypted on the way when
the backup is (`ios_backup.plain_chunks`) — into the store under the digest the line names, hashing
as it goes (`attachments.write_chunks`), and refuses a file whose bytes are not the ones named:
nothing lands under that name, the line on stderr names the file and both digests, and the exit
status is 1 at the end. A file is never held whole. A digest already present is skipped unread, so
a run that stopped is resumed by running it again; one the backup does not hold is counted; a line
whose media was missing at import names no digest and is counted too. A retracted line's media is
left alone. Nothing is appended: the lines already point at the bytes. Until the pass runs, and
after one that stopped, such a line names a file the store does not hold — a missing attachment,
which SPEC §1.1 allows: the chain's `verify` reports it separately and exits 0, `status` counts
it, and the next run fills it in.

`status` counts, through the index alone, the digests each source's standing lines name — the one
attachment a line points at, as `stats` counts — and which are in the store; and the store's files
and bytes. `verify` streams every file whose name is a digest through SHA-256 and reports the ones
whose bytes are not what their name says (SPEC §1.1: an error); an entry under another name is
ignored and counted. Both read only. A progress line every PROGRESS_EVERY files, on stderr.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from . import attachments, ios_backup
from .adapters import ALIASES
from .index import Index
from .store import RETRACTION, Logbook

PROGRESS_EVERY = 500
Progress = Callable[[int, float], None]  # files handled so far, seconds elapsed


def _as_given(local_path: str) -> tuple[str, ...] | None:
    """The path as the source stores it, relative to its media folder (WhatsApp, Photos)."""
    return PurePosixPath(local_path).parts or None


def _below_attachments(local_path: str) -> tuple[str, ...] | None:
    """Messages stores `~/Library/SMS/Attachments/ab/12/<guid>/<name>` or the same under
    `/var/mobile/`: the part after its `Attachments` folder, as the adapter looks it up."""
    parts = PurePosixPath(local_path).parts
    if "Attachments" not in parts:
        return None
    return parts[parts.index("Attachments") + 1 :] or None


@dataclass(frozen=True)
class MediaSource:
    """One source whose lines name media by digest: the adapter's NAME and `kind`, the backup domain
    and the folder below which the phone keeps the files, and how a line's `local_path` is read."""

    name: str
    kind: str
    domain: str
    folder: str  # POSIX, as Manifest.db spells it
    below: Callable[[str], tuple[str, ...] | None]

    def relative_path(self, local_path: str) -> str | None:
        """The Manifest.db `relativePath` of a line's file, or None when the path cannot be placed
        or would leave the folder (`..`, an empty or absolute part): never a file outside it."""
        parts = self.below(local_path) if local_path else None
        if not parts or any(part in ("..", "", "/") for part in parts) or parts[0].startswith("/"):
            return None
        return PurePosixPath(self.folder, *parts).as_posix()


SOURCES: tuple[MediaSource, ...] = (
    MediaSource("whatsapp", "message", ios_backup.WHATSAPP, "Message", _as_given),
    MediaSource("imessage", "message", ios_backup.MEDIA, "Library/SMS/Attachments", _below_attachments),
    MediaSource("apple-photos", "photo", ios_backup.CAMERA_ROLL, "Media", _as_given),
)


def source(name: str) -> MediaSource | None:
    """The media source called `name`; `photos` stands for `apple-photos` as `add` has it."""
    wanted = ALIASES.get(name, name)
    return next((s for s in SOURCES if s.name == wanted), None)


@dataclass(frozen=True)
class Reference:
    """One file a line names: the line, the digest, the size the line gives, where the phone kept
    the file and where that is in the backup (None when the path cannot be placed)."""

    line_id: str
    seq: int
    source: str
    sha256: str
    bytes: int | None
    local_path: str
    relative_path: str | None


def _references_of(line: dict[str, Any], src: MediaSource) -> Iterator[Reference]:
    """Every `extra.media` and `extra.more_media[]` item of the line that carries a digest."""
    payload = line.get("payload") or {}
    extra = payload.get("extra")
    if not isinstance(extra, dict):
        return
    more = extra.get("more_media")
    items: list[object] = [extra.get("media"), *(more if isinstance(more, list) else [])]
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("media"), dict):
            item = item["media"]  # `imessage` keeps each further file as {media_kind, media, media_missing?}
        if not isinstance(item, dict):
            continue
        sha256, size, local_path = item.get("sha256"), item.get("bytes"), item.get("local_path")
        if not isinstance(sha256, str) or not attachments.is_digest(sha256):
            continue
        local_path = local_path if isinstance(local_path, str) else ""
        yield Reference(
            str(line["id"]),
            int(line["seq"]),
            src.name,
            sha256,
            size if isinstance(size, int) and not isinstance(size, bool) else None,
            local_path,
            src.relative_path(local_path),
        )


def references(
    idx: Index, src: MediaSource, since: str | None, counts: dict[str, int] | None = None
) -> Iterator[Reference]:
    """Every digest the standing lines of the source name — not retracted; from the local day
    `since` on — streamed through the index in file order, one line read at a time. A line that
    names media but no digest (the file was missing at import, or the hashing was skipped) yields
    nothing and is counted under `without_digest` in `counts`."""
    retracted = frozenset(idx.superseded(RETRACTION))
    for line in idx.of_kind(src.kind, since, None, source=src.name):
        if str(line["id"]) in retracted:
            continue
        found = list(_references_of(line, src))
        if found:
            yield from found
        elif counts is not None and _names_media(line):
            counts["without_digest"] = counts.get("without_digest", 0) + 1


def _names_media(line: dict[str, Any]) -> bool:
    """Whether the line names media at all (a file was there, or missing, at import)."""
    extra = (line.get("payload") or {}).get("extra")
    return isinstance(extra, dict) and ("media" in extra or extra.get("media_missing") is True)


@dataclass
class Tally:
    """What one source's pass did, by distinct digest: `referenced` is the digests its lines name,
    `lines` the lines naming one; each digest is stored, present, not in the backup or refused."""

    source: str
    referenced: int = 0
    lines: int = 0
    without_digest: int = 0
    stored: int = 0
    stored_bytes: int = 0
    present: int = 0
    not_in_backup: int = 0
    refused: int = 0
    would_store: int = 0  # dry run: the files the backup holds and the store does not
    would_store_bytes: int = 0

    def row(self, dry_run: bool) -> str:
        files = f"{self.referenced:,} file{'s' if self.referenced != 1 else ''}"
        lines = f"{self.lines:,} line{'s' if self.lines != 1 else ''}"
        head = f"{self.source}: {files} referenced by {lines}: "
        if dry_run:
            parts = [
                f"{self.would_store:,} would be stored ({self.would_store_bytes:,} bytes)",
                f"{self.present:,} present",
                f"{self.not_in_backup:,} not in the backup",
            ]
        else:
            parts = [
                f"{self.stored:,} stored",
                f"{self.present:,} present",
                f"{self.not_in_backup:,} not in the backup",
                f"{self.refused:,} refused",
            ]
        text = head + ", ".join(parts)
        if self.without_digest:
            n = self.without_digest
            text += f"; {n:,} line{'s' if n != 1 else ''} without a digest"
        return text


@dataclass
class Report:
    """The whole pass: one Tally per source, and what the store holds afterwards."""

    tallies: list[Tally] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)  # one message per refused file, as printed

    @property
    def stored(self) -> int:
        return sum(t.stored for t in self.tallies)

    @property
    def would_store(self) -> tuple[int, int]:
        return sum(t.would_store for t in self.tallies), sum(t.would_store_bytes for t in self.tallies)


def import_backup(
    lb: Logbook,
    manifest: ios_backup.Manifest,
    sources: tuple[MediaSource, ...],
    since: str | None,
    dry_run: bool,
    progress: Progress | None = None,
    say: Callable[[str], None] | None = None,
) -> Report:
    """The pass (module docstring). `say` gets each refusal as it happens, so the owner sees it
    beside the progress; `progress` is told every PROGRESS_EVERY files handled."""
    report = Report()
    started = time.monotonic()
    handled = 0
    seen: dict[str, bool] = {}  # digest → in the store (after this run's own stores)
    store = lb.root / attachments.DIR
    with lb.index() as idx:
        for src in sources:
            tally = Tally(src.name)
            report.tallies.append(tally)
            digests: set[str] = set()
            lines: set[str] = set()
            counts: dict[str, int] = {}
            for ref in references(idx, src, since, counts):
                lines.add(ref.line_id)
                if ref.sha256 in digests:
                    continue
                digests.add(ref.sha256)
                tally.referenced += 1
                if ref.sha256 not in seen:
                    seen[ref.sha256] = (store / ref.sha256).is_file()
                if seen[ref.sha256]:
                    tally.present += 1
                else:
                    f = manifest.file(src.domain, ref.relative_path) if ref.relative_path else None
                    if f is None or f.size is None:
                        tally.not_in_backup += 1
                    elif dry_run:
                        tally.would_store += 1
                        tally.would_store_bytes += f.size
                        seen[ref.sha256] = True  # the same digest from another line would be one file
                    else:
                        try:
                            _target, size = attachments.write_chunks(
                                lb.root, ios_backup.plain_chunks(f), ref.sha256
                            )
                        except (attachments.DigestMismatch, ios_backup.DecryptError, OSError) as e:
                            tally.refused += 1
                            message = f"attach import-backup: {src.name}: {ref.relative_path}: refused: {e}"
                            report.refused.append(message)
                            if say is not None:
                                say(message)
                        else:
                            tally.stored += 1
                            tally.stored_bytes += size
                            seen[ref.sha256] = True
                handled += 1
                if progress is not None and handled % PROGRESS_EVERY == 0:
                    progress(handled, time.monotonic() - started)
            tally.lines = len(lines)
            tally.without_digest = counts.get("without_digest", 0)
    return report


# -- status ---------------------------------------------------------------------------------------


def store_size(lb: Logbook) -> tuple[int, int, int]:
    """(files whose name is a digest, their bytes, other entries) under `attachments/`; (0, 0, 0)
    when there is no store."""
    folder = lb.root / attachments.DIR
    if not folder.is_dir():
        return 0, 0, 0
    files = total = other = 0
    for p in folder.iterdir():
        if attachments.is_digest(p.name) and p.is_file():
            files += 1
            total += p.stat().st_size
        else:
            other += 1
    return files, total, other


def status(lb: Logbook) -> dict[str, Any]:
    """Per source with lines naming an attachment: the distinct digests referenced, the lines naming
    one, how many are present and how many missing; then the store: files, bytes, other entries,
    and the files no standing line references. Through the index and one listing of the folder."""
    folder = lb.root / attachments.DIR
    referenced: set[str] = set()
    rows: list[dict[str, Any]] = []
    with lb.index() as idx:
        per_source: dict[str, dict[str, int]] = {}
        for name, sha256, n in idx.media_by_source():
            if not attachments.is_digest(sha256):
                continue
            counts = per_source.setdefault(name, {"referenced": 0, "lines": 0, "present": 0, "missing": 0})
            counts["referenced"] += 1
            counts["lines"] += n
            referenced.add(sha256)
            if (folder / sha256).is_file():
                counts["present"] += 1
            else:
                counts["missing"] += 1
    for name in sorted(per_source, key=lambda s: (-per_source[s]["referenced"], s)):
        rows.append({"source": name, **per_source[name]})
    files, total, other = store_size(lb)
    unreferenced = 0
    if folder.is_dir():
        unreferenced = sum(
            1 for p in folder.iterdir() if attachments.is_digest(p.name) and p.name not in referenced
        )
    return {
        "sources": rows,
        "store": {"files": files, "bytes": total, "other": other, "unreferenced": unreferenced},
    }


def status_rows(report: dict[str, Any]) -> Iterator[str]:
    sources = report["sources"]
    if sources:
        width = max(12, *(len(s["source"]) for s in sources))
        yield f"  {'source':<{width}}  referenced  present  missing  lines"
        for s in sources:
            yield (
                f"  {s['source']:<{width}}  {s['referenced']:>10,}  {s['present']:>7,}  {s['missing']:>7,}"
                f"  {s['lines']:>5,}"
            )
    else:
        yield "no line names an attachment"
    yield store_line(report["store"])


def store_line(store: dict[str, Any]) -> str:
    if not store["files"] and not store["other"]:
        return "attachments/: no store yet"
    files = f"{store['files']:,} file{'s' if store['files'] != 1 else ''}"
    text = f"attachments/: {files}, {store['bytes']:,} bytes ({human(store['bytes'])})"
    if store.get("unreferenced"):
        n = store["unreferenced"]
        text += f"; {n:,} file{'s' if n != 1 else ''} no line references"
    if store["other"]:
        n = store["other"]
        text += f"; {n:,} other entr{'ies' if n != 1 else 'y'} (not a digest name)"
    return text


def human(n: int) -> str:
    """`1.2 GiB`, `345.6 MiB`, `12.3 KiB`, `59 B`."""
    value = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{n} B" if unit == "B" else f"{value:,.1f} {unit}"
        value /= 1024
    return f"{n} B"


# -- verify ---------------------------------------------------------------------------------------


@dataclass
class VerifyReport:
    checked: int = 0
    bytes: int = 0
    other: int = 0
    bad: list[tuple[str, str]] = field(default_factory=list)  # (name, the digest the bytes hash to)


def verify(lb: Logbook, progress: Progress | None = None) -> VerifyReport:
    """Every file under `attachments/` whose name is a digest, streamed through SHA-256 (a chunk
    at a time, never whole); a file whose bytes hash to another digest is listed. An entry under
    another name (a temporary file a run left behind, a stray) is counted and otherwise ignored."""
    report = VerifyReport()
    folder = lb.root / attachments.DIR
    if not folder.is_dir():
        return report
    started = time.monotonic()
    for p in sorted(folder.iterdir()):
        if not attachments.is_digest(p.name) or not p.is_file():
            report.other += 1
            continue
        found, size = attachments.digest_path(p)
        report.checked += 1
        report.bytes += size
        if found != p.name:
            report.bad.append((p.name, found))
        if progress is not None and report.checked % PROGRESS_EVERY == 0:
            progress(report.checked, time.monotonic() - started)
    return report


def verify_rows(report: VerifyReport) -> Iterator[str]:
    if not report.checked and not report.other:
        yield "attachments/: no store yet"
        return
    files = f"{report.checked:,} file{'s' if report.checked != 1 else ''}"
    if report.bad:
        n = len(report.bad)
        yield f"CORRUPT — {n:,} of {files} does not match its name:"
        for name, found in report.bad:
            yield f"  {attachments.DIR}/{name}: hashes to {found[:12]}…"
    else:
        yield f"attachments/: {files} checked, {report.bytes:,} bytes, every file matches its name"
    if report.other:
        n = report.other
        yield f"{n:,} other entr{'ies' if n != 1 else 'y'} ignored (not a digest name)"


def progress_line(n: int, elapsed: float) -> None:
    """On stderr, so stdout stays the summary."""
    print(f"  {n:,} files: {elapsed:,.0f}s so far", file=sys.stderr)
