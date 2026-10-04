"""Getting lines in from a file you hold: `add`, `import-backup`, `inbox` and `attach` (the
attachment store filled from an iOS backup)."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from .. import attach, inbox, ios_backup, ios_backup_crypto
from ..core import assets, attachments, flights, keepers, places, story
from ..core.export import parse_day
from ..core.resolve import Ref, identities_from, labels
from ..core.store import Logbook, dedupe_key, now_utc
from .common import (
    Subparsers,
    _airports,
    _csv,
    _is_rfc3339,
    _plural,
    _progress,
    _registry,
    _say_disabled,
    _takes,
    _under_home,
)
from .rows import _flight_text
from .skips import _report_skipped

if TYPE_CHECKING:
    from .. import adapters
    from ..adapters import apple_photos


def _add_file(
    lb: Logbook,
    p: Path,
    options: Mapping[str, Any] | None = None,
    dry_run: bool = False,
    quiet: bool = False,
    shown: str | None = None,
) -> bool:
    """Append one file through the adapter that recognises it. False when nothing does, said unless
    `quiet` (a file met while walking a folder is counted, not named) and under `shown` (the path
    as the walk prints it) when given."""
    from .. import adapters

    adapter = adapters.find(p)
    if adapter is not None:
        _append_with(lb, adapter, p, options, dry_run=dry_run)
        return True
    if p.suffix == ".jsonl":  # observations produced by an adapter run by hand
        if dry_run:
            _say_dry_run(lb, p.name, _jsonl(p))
            return True
        seq_before, produced = int(lb.meta["seq"]), [0]
        n = lb.append_many(_counted(_jsonl(p), produced), progress=_progress)
        print(f"added {n} lines from {p.name}")
        inbox.record(lb.root, inbox.finished(lb, p, inbox.JSONL, produced[0], n, seq_before))
        return True
    if not quiet:
        print(
            f"{shown or p.name}: no adapter for this file yet (roadmap phase 1). "
            "Put it in inbox/ and it will be read when one exists."
        )
    return False


FOLDER_DEPTH = 4  # folders walked below the one given: `Takeout/<Product>/<sub>/<sub>/<file>` and no deeper


def _add_folder(
    lb: Logbook, top: Path, given: Mapping[str, Any], dry_run: bool = False, verbose: bool = False
) -> list[Path]:
    """`add <folder>`: the folder, walked. A folder an adapter claims as a whole (`Google Pay/`,
    `Keep/`) is handed to it, and the subfolders that adapter also claims are left to it; every
    other subfolder is walked the same way, `FOLDER_DEPTH` levels down and no further, so a whole
    Takeout root reaches `My Activity/<product>/MyActivity.json` and `YouTube and YouTube
    Music/history/`. A file in a folder nobody claims goes through the adapter that recognises it;
    one no adapter reads is counted and, with `verbose`, named. Hidden files and folders are not
    exports. Ends with one line naming each folder something was read from, relative to `top`,
    and how many files no adapter read. Returns the inputs read, for the cleanable hint."""
    imported: list[Path] = []
    read: list[Path] = []
    unread: list[Path] = []
    _walk(lb, top, top, 0, given, dry_run, verbose, imported, read, unread)
    folders = [top.name if f == top else f.relative_to(top).as_posix() for f in read]
    n = len(folders)
    text = (
        f"{top.name}: read {n} folder{'s' if n != 1 else ''} — {', '.join(folders)}"
        if n
        else f"{top.name}: nothing read"
    )
    if unread:
        m = len(unread)
        text += f"; {m:,} file{'s' if m != 1 else ''} with no adapter"
        if not verbose:
            text += " (--verbose names them)"
    print(text)
    return imported


def _walk(
    lb: Logbook,
    top: Path,
    folder: Path,
    depth: int,
    given: Mapping[str, Any],
    dry_run: bool,
    verbose: bool,
    imported: list[Path],
    read: list[Path],
    unread: list[Path],
) -> None:
    from .. import adapters

    adapter = adapters.find(folder)
    if adapter is not None and _add_file(lb, folder, given, dry_run=dry_run):
        imported.append(folder)
        read.append(folder)
    for entry in sorted(folder.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            if depth >= FOLDER_DEPTH or (adapter is not None and adapter.sniff(entry)):
                continue
            _walk(lb, top, entry, depth + 1, given, dry_run, verbose, imported, read, unread)
        elif entry.is_file() and adapter is None:
            shown = entry.relative_to(top).as_posix()
            if _add_file(lb, entry, given, dry_run=dry_run, quiet=not verbose, shown=shown):
                imported.append(entry)
                if folder not in read:
                    read.append(folder)
            else:
                unread.append(entry)


def _append_with(
    lb: Logbook,
    adapter: adapters.Adapter,
    p: Path,
    given: Mapping[str, Any] | None = None,
    dry_run: bool = False,
    recorded_as: Path | None = None,
) -> int:
    """Run one file adapter on `p`, append, print what was added and what it skipped; the count.
    A run that reaches its end is recorded in `state/imports.jsonl` (`inbox.finished`) under
    `recorded_as` — the input as the owner knows it (`import-backup` passes the source's folder
    under inbox/, whose every file the run read) — so `inbox list` can say the input is consumed.
    `given` are the command's own options (`source`, `tier`, `at`, `since`, `account`, `attachments`,
    `only_labels`, `skip_labels`, `asset`, `routes`), passed when the adapter's `run` takes them;
    one it does not take exits 2, so a flag is never silently ignored. An adapter whose `run` takes
    `owner_emails` gets the record's own addresses from `logbook.json` (RFC 0015), with a hint when
    there are none; one
    whose `run` takes `resolved` gets the refs the record already resolves, as `{(kind, value):
    entity id}` (RFC 0006), so a contacts import never mints a second id for a person it knows; one
    that takes `asset` must be given a registered one; one whose `run` takes `existing` gets the
    record's standing lines by (source, raw_id), batched through the index, so a later export can
    correct a sample (`health_export.corrected`).
    One whose `run` takes `progress` gets a reporter that prints every report it makes with the
    bytes read and the rate; one whose `run` takes `cursor` gets the inbox manifest's cursor
    (`logbook.inbox`), so an import that stopped resumes where the record holds the source up to,
    and `--restart` reads from the first byte again. With `dry_run` the adapter runs, the drafts
    are counted against the record and nothing is written: not a line, not an attachment, not the
    manifest."""
    if _say_disabled(lb, adapter.NAME):
        return 0
    counts: dict[str, int] = {}
    report: list[str] = []
    run: Callable[..., Iterator[dict[str, Any]]] = adapter.run
    options: dict[str, Any] = {}
    given = {k: v for k, v in (given or {}).items() if v is not None}
    restart = bool(given.pop("restart", False))
    cursor: inbox.Cursor | None = None
    if _takes(adapter, "cursor"):
        keyed = {k: v for k, v in given.items() if k != "at" and isinstance(v, str | int | bool | list)}
        cursor = inbox.Cursor(
            lb.root, adapter.NAME, keyed, restart=restart, notice=lambda text: print(text, file=sys.stderr)
        )
        options["cursor"] = cursor
    elif restart:
        print(f"add: --restart is not an option of the {adapter.NAME} adapter", file=sys.stderr)
        sys.exit(2)
    if _takes(adapter, "counts"):
        options["counts"] = counts
    if _takes(adapter, "progress"):
        options["progress"] = _read_progress(str(getattr(adapter, "UNIT", "items")))
    if _takes(adapter, "report"):
        options["report"] = report
    if _takes(adapter, "timezone"):
        options["timezone"] = lb.meta["timezone"]
    if _takes(adapter, "existing"):
        options["existing"] = _existing(lb)
    if _takes(adapter, "store"):
        options["store"] = (lambda data: Path(attachments.DIR)) if dry_run else lb.attach
    if _takes(adapter, "store_file"):
        options["store_file"] = (lambda path: Path(attachments.DIR)) if dry_run else lb.attach_file
    if _takes(adapter, "assets"):
        options["assets"] = _registry(lb, "add")
    if _takes(adapter, "resolved"):
        options["resolved"] = _resolved(lb)
    if _takes(adapter, "asset"):
        _check_asset(lb, adapter, (given or {}).get("asset"))
    if _takes(adapter, "places"):
        try:
            options["places"] = places.read(lb.root)
        except places.PlaceError as e:
            print(f"add: {e}", file=sys.stderr)
            sys.exit(2)
    if _takes(adapter, "owner_emails"):
        owner_emails = lb.meta.get("owner_emails") or []
        options["owner_emails"] = owner_emails
        if not owner_emails and not (given or {}).get("account"):
            print(
                f"hint: no owner_emails in logbook.json and no --account, so {adapter.NAME} cannot tell"
                " which address is yours (mail: every message is `received`; splitwise: the person on most"
                ' expenses is taken for you); add "owner_emails": ["you@example.org"] to logbook.json',
                file=sys.stderr,
            )
    for name, value in given.items():
        if _takes(adapter, name):
            options[name] = value
        elif name != "at":  # `--at` has always been the sentence's time; a file adapter ignores it
            print(f"add: --{name} is not an option of the {adapter.NAME} adapter", file=sys.stderr)
            sys.exit(2)
    if _takes(adapter, "airports") and "airports" not in options:
        options["airports"] = _airports(None)
    seq_before, produced = int(lb.meta["seq"]), [0]
    drafts = flights.reconcile(lb, run(p, **options), counts, options.get("airports"))
    marked: list[tuple[dict[str, Any], list[str]]] | None = None
    if getattr(adapter, "KEEPERS", False):  # a photo library whose marks are keepers (RFC 0024)
        marked = []
        drafts = _noting_marks(drafts, marked, counts)
    if dry_run:
        _say_dry_run(lb, adapter.NAME, drafts)
        _report_skipped(counts)
        for text in report:
            print(f"  {text}")
        if marked is not None:
            _keepers_of_import(lb, adapter.NAME, marked, counts, dry_run=True)
        return 0
    n = lb.append_many(
        _counted(drafts, produced),
        progress=_progress,
        committed=cursor.commit if cursor is not None else None,
    )
    print(f"added {n} lines from {adapter.NAME}")
    _report_skipped(counts)
    for text in report:
        print(f"  {text}")
    if marked is not None:
        _keepers_of_import(lb, adapter.NAME, marked, counts)
    inbox.record(lb.root, inbox.finished(lb, recorded_as or p, adapter.NAME, produced[0], n, seq_before))
    return n


def _noting_marks(
    drafts: Iterator[dict[str, Any]], marked: list[tuple[dict[str, Any], list[str]]], counts: dict[str, int]
) -> Iterator[dict[str, Any]]:
    """The drafts as they stream, noting each photo draft with a keeper mark (a favourite, the Art
    album; `keepers.marks`) and its lanes, and counting the photos, for `_keepers_of_import`."""
    for draft in drafts:
        if draft.get("kind") == keepers.PHOTO:
            counts["photos"] = counts.get("photos", 0) + 1
            lanes = keepers.marks(draft)
            if lanes:
                marked.append((draft, lanes))
        yield draft


def _keepers_of_import(
    lb: Logbook,
    source: str,
    marked: list[tuple[dict[str, Any], list[str]]],
    counts: dict[str, int],
    dry_run: bool = False,
) -> None:
    """The keeper/v1 lines (RFC 0024) for the marks an import carried, written once the photo lines
    are in the record: each draft's line id is looked up by `(source, raw_id)` through the index, the
    keeper is `keepers.draft` of that line and lane, and `append_many` skips a `(keeper-inference,
    <line id>:<lane>)` already there, retracted or not. A dry run counts the same way: a photo not
    yet in the record would be a new keeper; one already there is looked up. Says what it did."""
    drafts: list[dict[str, Any]] = []
    new_photos = 0
    with lb.index() as idx:
        for draft, lanes in marked:
            raw_id = (draft.get("payload") or {}).get("raw_id")
            line_id = None if raw_id is None else idx.line_id(source, str(raw_id))
            if line_id is None:
                new_photos += len(lanes)  # a dry run: the photo itself is not in the record yet
                continue
            drafts.extend(keepers.draft({**draft, "id": line_id}, lane) for lane in lanes)
        if dry_run:
            already = len(idx.existing({key for d in drafts if (key := dedupe_key(d)) is not None}))
    photos = f"{_plural(len(marked), 'marked photo')} of {counts.get('photos', 0)}"
    if dry_run:
        n = len(drafts) - already + new_photos
        print(f"  keepers: {n} would be written, {already} already in the record (dry run, nothing written)")
        return
    already = 0

    def skipped(_draft: dict[str, Any]) -> None:
        nonlocal already
        already += 1

    n = lb.append_many(drafts, skipped=skipped)
    already_text = f" ({already} already in the record)" if already else ""
    print(f"  keepers: {n} new from {photos}{already_text}")


def _say_dry_run(lb: Logbook, name: str, drafts: Iterable[dict[str, Any]]) -> None:
    """`add --dry-run`: run the drafts out, count those the record already holds by (source,
    raw_id) through the index, say both, write nothing."""
    n = already = 0
    with lb.index() as idx:
        for draft in drafts:
            n += 1
            raw_id = (draft.get("payload") or {}).get("raw_id")
            if raw_id is not None and idx.line_id(str(draft.get("source")), str(raw_id)) is not None:
                already += 1
    print(
        f"{name}: {n - already} lines would be added, {already} already in the record"
        " (dry run, nothing written)"
    )


def _resolved(lb: Logbook) -> dict[Ref, str]:
    """For an adapter whose `run` takes `resolved`: every ref the record resolves to an entity,
    `{(kind, value): entity id}`, from the resolution lines standing (RFC 0006, through the alias
    walk), read through the index."""
    with lb.index() as idx:
        found = identities_from([*idx.retractions(), *idx.resolutions()])
    return {ref: identity.entity for ref, identity in found.items() if identity.entity}


def _counted(drafts: Iterable[dict[str, Any]], tally: list[int]) -> Iterator[dict[str, Any]]:
    """`drafts` as they pass, counting them in `tally[0]`: the lines offered to the record."""
    for draft in drafts:
        tally[0] += 1
        yield draft


def _check_asset(lb: Logbook, adapter: adapters.Adapter, asset: object) -> None:
    """An adapter whose `run` takes `asset` (`passages`) reads a log that belongs to one registered
    asset: `--asset` must be given and name an entry of `assets.json`, else exit 2 saying which."""
    if not asset:
        print(
            f"add: {adapter.NAME} needs --asset ASSET-ID, the registered asset the log belongs to"
            " (logbook assets list)",
            file=sys.stderr,
        )
        sys.exit(2)
    if asset not in {a.id for a in _registry(lb, "add")}:
        print(
            f"add: --asset {asset} is not registered in assets.json; register it first:"
            f" logbook assets add {asset} --kind {'|'.join(assets.KINDS)} --name NAME [--mmsi N]",
            file=sys.stderr,
        )
        sys.exit(2)


def _existing(lb: Logbook) -> Callable[[Iterable[tuple[str, str]]], dict[tuple[str, str], dict[str, Any]]]:
    """For a file adapter whose `run` takes `existing`: the record's line for each (source, raw_id)
    it asks about, read through the index in one batch, so an export can be checked against what
    stands and a changed sample written as a correction."""

    def existing(keys: Iterable[tuple[str, str]]) -> dict[tuple[str, str], dict[str, Any]]:
        with lb.index() as idx:
            return dict(idx.lines_of(keys))

    return existing


def _read_progress(unit: str) -> Callable[[int, int, float], None]:
    """A file adapter's own progress (`mail`, every 10,000 messages): the items read, the bytes
    read and the rate, on stderr."""

    def report(n: int, read: int, elapsed: float) -> None:
        rate = read / 1e6 / elapsed if elapsed > 0 else 0.0
        print(f"  {n:,} {unit} · {read / 1e6:,.0f} MB read · {rate:,.1f} MB/s", file=sys.stderr)

    return report


def _jsonl(p: Path) -> Iterator[dict[str, Any]]:
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


PATH_SUFFIXES = (".json", ".jsonl", ".geojson", ".zip", ".csv", ".txt")


def looks_like_path(arg: str) -> bool:
    """Something the shell would have expanded from a glob, or a file name."""
    return "/" in arg or arg.startswith("~") or arg.lower().endswith(PATH_SUFFIXES)


# `add screentime`'s help names the Screen Time stores. The adapter (`adapters.screentime`) is the
# source of truth and is imported only when the command runs, so `--help` loads no adapter; a test
# holds these copies to it.
SCREENTIME_MAC_STORE = "knowledgeC.db"
SCREENTIME_PHONE_STORE = "RMAdminStore-Local.sqlite"
SCREENTIME_MAC_DEFAULT = Path("~/Library/Application Support/Knowledge") / SCREENTIME_MAC_STORE


def add_arguments(sub: Subparsers) -> None:
    """`logbook add`."""
    s = sub.add_parser(
        "add",
        help='a sentence in your words, an export file, a folder of them, or `flight "LX 561 NCE ZRH …"`',
    )
    s.add_argument(
        "what",
        nargs="+",
        help='the words, the path(s), `<adapter> <file|folder>`, or `flight "<designator> …"`',
    )
    s.add_argument("--at", help="RFC3339 UTC, default now; for a transcript file, its start")
    s.add_argument("--source", help="transcript: the provider, e.g. granola, zoom (default manual)")
    s.add_argument(
        "--tier",
        type=int,
        choices=(1, 2, 3),
        help="transcript, health, mail: privacy tier for the whole import (transcript and health default 3)",
    )
    s.add_argument(
        "--airports",
        metavar="FILE",
        help="flights: a CSV (iata,icao,name,lat,lon,tz) added to the airports table"
        f" (default ${flights.AIRPORTS_ENV})",
    )
    s.add_argument("--since", metavar="DAY|RFC3339", help="mail: only messages from this day or instant on")
    s.add_argument("--account", metavar="EMAIL", help="mail: the mailbox the export came from (in raw_id)")
    s.add_argument(
        "--attachments",
        action="store_const",
        const=True,
        default=None,
        help="mail, keep: store attachments under attachments/ (default: reference them by digest only)",
    )
    s.add_argument("--only-labels", metavar="A,B", help="mail: keep only messages with any of these labels")
    s.add_argument("--skip-labels", metavar="A,B", help="mail: drop messages with any of these labels")
    s.add_argument(
        "--restart",
        action="store_true",
        help="mail: read the file from its first byte again, not from where inbox/manifest.json says"
        " the last import of it got to",
    )
    s.add_argument(
        "--asset", metavar="ASSET-ID", help="passages: the registered asset the deck log belongs to"
    )
    s.add_argument(
        "--routes",
        metavar="DIR",
        help="passages: a folder of ECDIS route files (RTZ) that position the legs they name",
    )
    s.add_argument(
        "--mac",
        nargs="?",
        const=str(SCREENTIME_MAC_DEFAULT),
        metavar="DB",
        help=f"screentime: a Mac's {SCREENTIME_MAC_STORE} (default this Mac's own, behind Full Disk Access)",
    )
    s.add_argument(
        "--backup",
        metavar="DIR",
        help=f"screentime: an iOS backup folder; its {SCREENTIME_PHONE_STORE} is copied into inbox/ and read",
    )
    s.add_argument(
        "--teller",
        metavar="REF",
        help="story: who told it — an address, a +number, kind:value or a name the record knows",
    )
    s.add_argument("--listener", metavar="REF", help="story: who it was told to, the same way")
    s.add_argument(
        "--refers-to",
        metavar="WHEN",
        help="story: the time it is about — 1961, 1961-05, 1961-05-04, 1950s, or words such as"
        " 'before the war'",
    )
    s.add_argument(
        "--confidence",
        choices=story.CONFIDENCES,
        help="story: how sure the teller said they were (default unstated)",
    )
    s.add_argument(
        "--dry-run",
        action="store_true",
        help="run the adapter, say how many lines would be added and how many are already in the record;"
        " write nothing",
    )
    s.add_argument(
        "--verbose",
        action="store_true",
        help="a folder: name every file no adapter reads (default: count them in the folder's last line)",
    )
    s.set_defaults(fn=cmd_add)


def cmd_add(a: argparse.Namespace) -> None:
    from .. import adapters
    from ..adapters import screentime

    lb = Logbook.find()
    given = {
        "source": a.source,
        "tier": a.tier,
        "at": a.at,
        "airports": _airports(a.airports) if a.airports else None,
        "since": _since(a.since, lb.meta["timezone"]) if a.since else None,
        "account": a.account,
        "attachments": a.attachments,
        "only_labels": _csv(a.only_labels),
        "skip_labels": _csv(a.skip_labels),
        "restart": True if a.restart else None,
        "asset": a.asset,
        "routes": Path(a.routes).expanduser() if a.routes else None,
    }
    if a.what[0] == "flight" and len(a.what) > 1 and flights.starts_with_designator(" ".join(a.what[1:])):
        if a.dry_run:
            print("add: --dry-run goes with a file or folder, not a declared flight", file=sys.stderr)
            sys.exit(2)
        _add_flight(lb, " ".join(a.what[1:]), given["airports"] or _airports(None))
        return
    if a.what[0] == story.KIND:
        _add_story(lb, a)
        return
    if a.teller or a.listener or a.refers_to or a.confidence:
        print(
            "add: --teller, --listener, --refers-to and --confidence go with `add story <file>`",
            file=sys.stderr,
        )
        sys.exit(2)
    if a.mac is not None or a.backup is not None or a.what == [screentime.NAME]:
        _add_screentime(lb, a, given)
        return

    if len(a.what) > 1 and (by_name := adapters.named(a.what[0])) is not None:
        paths = [Path(w).expanduser() for w in a.what[1:]]
        if all(p.exists() for p in paths):  # else the whole thing may be a sentence
            _add_named(lb, by_name, paths, given, dry_run=a.dry_run)
            if not a.dry_run:
                _say_cleanable(lb, paths)
            return
    paths = [Path(w).expanduser() for w in a.what]
    # When nothing exists, the arguments are a sentence unless every one of them looks like a
    # path: "had 5/10 sleep" is a note, "~/Downloads/typo.json" is a typo.
    if not any(p.exists() for p in paths) and not all(looks_like_path(w) for w in a.what):
        if a.dry_run:
            print("manual: 1 line would be added (dry run, nothing written)")
            return
        _add_sentence(lb, " ".join(a.what).strip(), a.at)
        return
    # Something exists, so every argument is a path. A glob that matched two files must never
    # become a note, and a path that does not exist is a typo, so nothing is written until every
    # argument checks out.
    for w, p in zip(a.what, paths, strict=True):
        if not p.exists():
            print(f"add: no such file or directory: {w}", file=sys.stderr)
            sys.exit(2)
    ok = True
    imported: list[Path] = []
    for p in paths:
        if p.is_dir():
            imported.extend(_add_folder(lb, p, given, dry_run=a.dry_run, verbose=a.verbose))
        elif _add_file(lb, p, given, dry_run=a.dry_run):
            imported.append(p)
        else:
            ok = False
    if not a.dry_run:
        _say_cleanable(lb, imported)
    if not ok:
        sys.exit(2)


def _say_cleanable(lb: Logbook, imported: list[Path]) -> None:
    """The one line an import ends with: these inputs are in the record and may go (`inbox.hint`)."""
    line = inbox.hint(lb.root, imported)
    if line is not None:
        print(line)


FULL_DISK_ACCESS = (
    "the Mac's Screen Time store is behind Full Disk Access: System Settings → Privacy & Security →"
    " Full Disk Access, add your terminal, then run this again; or copy the store elsewhere and name"
    " the copy with --mac"
)


def _add_screentime(lb: Logbook, a: argparse.Namespace, given: Mapping[str, Any]) -> None:
    """`add screentime --mac [DB]` reads a Mac's knowledgeC.db (this Mac's own without a path;
    a store that cannot be opened names Full Disk Access); `add screentime --backup DIR` copies
    Screen Time's store out of an iOS backup into the inbox, as `import-backup --only screentime`
    does, and runs the adapter on the copy; one or the other, with `screentime` and nothing else."""
    from ..adapters import screentime

    if a.what != [screentime.NAME]:
        print(f"add: --mac and --backup go with `add {screentime.NAME}`", file=sys.stderr)
        sys.exit(2)
    if a.mac is not None and a.backup is not None:
        print("add screentime: give --mac DB or --backup DIR, not both", file=sys.stderr)
        sys.exit(2)
    if a.mac is None and a.backup is None:
        print(
            f"add screentime: --mac [DB] (this Mac's {screentime.MAC_DEFAULT}) or --backup DIR (an iOS"
            f" backup folder), or a store's path: `add screentime <{screentime.MAC_STORE}|"
            f"{screentime.PHONE_STORE}>`",
            file=sys.stderr,
        )
        sys.exit(2)
    if a.mac is not None:
        store = Path(a.mac).expanduser()
        readable = store.is_file()
        if readable:
            try:
                with store.open("rb"):
                    pass
            except OSError:  # PermissionError on a Mac without Full Disk Access
                readable = False
        if not readable:
            print(f"add screentime: cannot read {store}; {FULL_DISK_ACCESS}", file=sys.stderr)
            sys.exit(2)
        _append_with(lb, screentime, store, given, dry_run=a.dry_run)
        return
    try:
        manifest = ios_backup.Manifest(Path(a.backup).expanduser())
    except ios_backup.NotABackup as e:
        print(f"add screentime: {e}", file=sys.stderr)
        sys.exit(2)
    if _say_disabled(lb, screentime.NAME):
        return
    source = ios_backup.source(screentime.NAME)
    assert source is not None
    inbox = lb.root / "inbox" / f"ios-backup-{manifest.udid}"
    if manifest.encrypted:
        _unlock(manifest, inbox)
    (p,) = ios_backup.plan(manifest, (source,))
    print(_plan_row(p, inbox))
    if not p.found:
        sys.exit(1)
    if a.dry_run:
        print(f"dry run: {p.bytes:,} bytes would be copied to {inbox / source.name}; nothing written")
        return
    try:
        store_copy = ios_backup.copy(p, inbox / source.name)
    except (ios_backup.CopyError, ios_backup.DecryptError, OSError) as e:
        print(f"add screentime: {e}", file=sys.stderr)
        sys.exit(1)
    for c in p.copied:
        if c.warning is not None:
            print(f"  warning: {c.warning}")
    ios_backup.write_copies(inbox, manifest, [p])
    _append_with(lb, screentime, store_copy, given)


def _since(value: str, timezone: str) -> str:
    """`--since` as RFC3339 UTC: an instant is normalised, a bare day is that day's local midnight
    in the record's zone. Anything else exits 2."""
    with contextlib.suppress(ValueError):
        day = datetime.combine(parse_day(value), datetime.min.time(), tzinfo=ZoneInfo(timezone))
        return day.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if _is_rfc3339(value):
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"add: --since must be a day (YYYY-MM-DD) or an RFC3339 instant, not {value!r}", file=sys.stderr)
    sys.exit(2)


def _add_named(
    lb: Logbook, adapter: adapters.Adapter, paths: list[Path], given: Mapping[str, Any], dry_run: bool = False
) -> None:
    """`add <adapter> <file|folder>...`: every path through the named adapter, sniffed or not
    (`transcript` reads Markdown and plain text this way only; `ios-calls` a store copied out of a
    backup under any name), with `--source`, `--tier` and `--at` when it takes them."""
    for p in paths:
        _append_with(lb, adapter, p, given, dry_run=dry_run)


def _add_flight(lb: Logbook, sentence: str, airports: flights.Airports) -> None:
    """`add flight "LX 561 NCE ZRH 2026-09-27 pilot"`: one declared flight/v1 line (RFC 0013), merged
    into the flight already standing for its key when there is one."""
    try:
        draft = flights.parse_declaration(sentence, airports, flights.Airlines.load())
    except ValueError as e:
        print(f"add: {e}", file=sys.stderr)
        sys.exit(2)
    counts: dict[str, int] = {}
    if not lb.append_many(flights.reconcile(lb, [draft], counts, airports)):
        print(f"already in the record: {_flight_text(draft['payload'])}")
        return
    line = lb.line_by_seq(lb.meta["seq"])  # the one line just written
    assert line is not None
    superseded = line["payload"].get("supersedes")
    print(
        f"#{line['seq']} {line['at']}  flight {_flight_text(line['payload'])}"
        + (" (merged into the flight already in the record)" if superseded else "")
    )


def _add_story(lb: Logbook, a: argparse.Namespace) -> None:
    """`add story <file>... --teller <ref> --listener <ref> [--refers-to …] [--confidence …] [--at …]
    [--tier 2|3]`: one story/v1 line per file (RFC 0028), a text or Markdown file whose front
    matter may carry the same fields, or a transcript/v1 JSON whose text becomes the story and whose
    bytes go to the attachment store. Every file is read and every flag checked before anything is
    written; a file already in the record (same bytes) is said so and skipped."""
    paths = [Path(w).expanduser() for w in a.what[1:]]
    if not paths:
        print(
            "add story: give one or more files: `add story <file> --teller <ref> --listener <ref>`",
            file=sys.stderr,
        )
        sys.exit(2)
    for w, p in zip(a.what[1:], paths, strict=True):
        if not p.is_file():
            print(f"add story: no such file: {w}", file=sys.stderr)
            sys.exit(2)
    timezone = str(lb.meta["timezone"])
    drafts: list[tuple[Path, dict[str, Any], bytes | None]] = []
    with lb.index() as idx:
        identities = identities_from([*idx.retractions(), *idx.resolutions()])
        for p in paths:
            try:
                parsed = story.read_file(p, timezone)
                transcript_line = idx.line_id(*parsed.transcript_key) if parsed.transcript_key else None
                line = story.draft(
                    parsed,
                    identities,
                    teller=a.teller,
                    listener=a.listener,
                    refers_to=a.refers_to,
                    confidence=a.confidence,
                    at=a.at,
                    tier=a.tier,
                    timezone=timezone,
                    transcript_line=transcript_line,
                )
            except story.StoryError as e:
                print(f"add story: {p.name}: {e}", file=sys.stderr)
                sys.exit(2)
            drafts.append((p, line, parsed.to_store))
        names = labels(lb, idx)
    if a.dry_run:
        print(f"story: {len(drafts)} line(s) would be added (dry run, nothing written)")
        return
    for _p, _line, to_store in drafts:
        if to_store is not None:
            lb.attach(to_store)
    skipped: list[str] = []
    lb.append_many(
        [line for _p, line, _bytes in drafts], skipped=lambda d: skipped.append(d["payload"]["raw_id"])
    )
    by_raw_id = {line["payload"]["raw_id"]: p for p, line, _bytes in drafts}
    with lb.index() as idx:
        written = {str(line["payload"].get("raw_id")): line for line in idx.by_kind(story.KIND)}
    for _p, line, _bytes in drafts:
        raw_id = line["payload"]["raw_id"]
        if raw_id in skipped:
            print(f"already in the record: {by_raw_id[raw_id].name}")
            continue
        found = written.get(raw_id)
        if found is not None:
            print(f"#{found['seq']} {found['at']}  {story.KIND} {story.text(found['payload'], names)}")


def _add_sentence(lb: Logbook, what: str, at: str | None) -> None:
    """A sentence, in your own words."""
    line = lb.append(
        at=at or now_utc(), source="manual", kind="note", tier=2, payload={"schema": "note/v1", "text": what}
    )
    print(f"#{line['seq']} {line['at']}  {what}")


PASSWORD_ENV = "LOGBOOK_BACKUP_PASSWORD"


ENCRYPTED_NO_PASSWORD = (  # each printed after `<command>: ` (`import-backup`, `attach import-backup`)
    f"this backup is encrypted; put its password in {PASSWORD_ENV} (never a flag) and re-run,"
    " or in Finder untick “Encrypt local backup”, back up again, then re-run"
)


ENCRYPTED_NO_EXTRA = f"this backup is encrypted; reading it needs {ios_backup_crypto.EXTRA}"


WRONG_PASSWORD = f"{PASSWORD_ENV} does not unlock this backup's keybag (wrong password?); nothing was copied"


def _dial_prefix_hint() -> str:
    from ..adapters import ios_contacts

    return (
        f"  {ios_contacts.DIAL_PREFIX_ENV} is not set: numbers saved without a country code stay as entered;"
        f" set it (for example {ios_contacts.DIAL_PREFIX_ENV}=41) to complete them"
    )


def import_backup_arguments(sub: Subparsers) -> None:
    """`logbook import-backup`."""
    s = sub.add_parser(
        "import-backup",
        help="every phone source from an iOS backup folder: copy each store into inbox/, add it"
        f" (an encrypted backup's password comes from {PASSWORD_ENV})",
    )
    s.add_argument("backup", help="the backup folder (Finder → Manage Backups → Show in Finder)")
    s.add_argument(
        "--dry-run", action="store_true", help="list what would be copied and imported; write nothing"
    )
    s.add_argument(
        "--attachments",
        action="store_true",
        help="store the media of sources that keep it (voice memos' audio) under attachments/"
        " (default: reference it by digest only)",
    )
    s.add_argument(
        "--only",
        metavar="NAMES",
        help="comma-separated sources, e.g. contacts,whatsapp (known: "
        + ", ".join(dict.fromkeys(src.name for src in ios_backup.SOURCES + ios_backup.EXTRAS))
        + "; calls, health and safari only from an encrypted backup)",
    )
    s.set_defaults(fn=cmd_import_backup)


def cmd_import_backup(a: argparse.Namespace) -> None:
    """Every phone source in one go, from an iOS backup folder: each store is copied (with its
    -wal/-shm siblings and its media) into <root>/inbox/ios-backup-<udid>/<source>/, checked by
    size, and the adapter runs on the copy — never on the backup, which is only read. Sources run
    in `ios_backup.SOURCES` order (contacts before chats), then the chain is verified.

    An encrypted backup is unlocked with the password in LOGBOOK_BACKUP_PASSWORD (only there: never
    a flag, never printed). The keybag check comes first, so a wrong password fails before any file
    is touched; then Manifest.db is decrypted into the inbox folder and every copy is decrypted on
    the way, so the adapters run on the same layout as for an unencrypted backup. The stores only an
    encrypted backup carries (`ios_backup.EXTRAS`) run too: the call log through `ios-calls`, Health
    through `apple-health` (its `healthdb.sqlite` copied first, so the store finds the source names
    beside it), Safari's history through `safari` (RFC 0017). A source the owner disabled in
    `policy/import.json` is skipped and said so before anything is copied, `--only` or not."""
    from .. import adapters
    from ..adapters import ios_contacts

    lb = Logbook.find()
    try:
        manifest = ios_backup.Manifest(Path(a.backup).expanduser())
    except ios_backup.NotABackup as e:
        print(f"import-backup: {e}", file=sys.stderr)
        sys.exit(2)
    sources = tuple(src for src in _only(a.only, manifest.encrypted) if not _say_disabled(lb, src.name))
    inbox_folder = lb.root / inbox.INBOX / f"ios-backup-{manifest.udid}"
    if manifest.encrypted:
        _unlock(manifest, inbox_folder)
    plans = ios_backup.plan(manifest, sources)
    if a.dry_run:
        for p in plans:
            print(_plan_row(p, inbox_folder))
        found = [p for p in plans if p.found]
        print(
            f"dry run: {len(found)} of {len(plans)} sources found, {sum(p.bytes for p in found):,} bytes"
            f" would be copied to {inbox_folder}; nothing written"
        )
        return
    wants_prefix = any(p.found and p.source.name in ("ios-contacts", "whatsapp-contacts") for p in plans)
    if wants_prefix and not os.environ.get(ios_contacts.DIAL_PREFIX_ENV, "").strip():
        print(_dial_prefix_hint())
    imported = 0
    for p in plans:
        print(_plan_row(p, inbox_folder))
        if not p.found:
            continue
        adapter = adapters.named(p.source.name) if p.source.adapter else None
        if adapter is None and p.source.adapter:  # a build without this adapter: say so, copy nothing
            print(f"  no adapter named {p.source.name} in this build; skipped")
            continue
        try:
            store_copy = ios_backup.copy(p, inbox_folder / p.source.name)
        except (ios_backup.CopyError, ios_backup.DecryptError, OSError) as e:
            print(f"import-backup: {p.source.name}: {e}", file=sys.stderr)
            sys.exit(1)
        for c in p.copied:
            if c.warning is not None:
                print(f"  warning: {c.warning}")
        if adapter is None:
            print(f"  copied, {p.source.note}")
            continue
        given: dict[str, Any] = {}
        if a.attachments and _takes(adapter, "attachments"):
            given["attachments"] = True
        if _takes(adapter, "media_digest") and os.environ.get(PHOTOS_HASH_MEDIA_ENV, "1").strip() != "0":
            given["media_digest"] = _media_digest(manifest, p.source)  # hashed in place, never copied
        try:
            _append_with(
                lb,
                adapter,
                store_copy.parent if p.source.pattern else store_copy,
                given or None,
                recorded_as=inbox_folder / p.source.name,
            )
        except (ios_backup.DecryptError, OSError) as e:  # a blob that will not decrypt or read while hashing
            print(f"import-backup: {p.source.name}: {e}", file=sys.stderr)
            sys.exit(1)
        imported += 1
    if any(p.copied for p in plans):
        ios_backup.write_copies(inbox_folder, manifest, plans)
    seq, head, errors = lb.verify()
    if errors:
        print(f"INVALID — {len(errors)} problem(s):")
        for problem in errors:
            print("  " + problem)
        sys.exit(1)
    print(f"valid — {seq} lines, head {head}")
    said = inbox.backup_hint(lb.root, inbox_folder, imported)
    if said is not None:
        print(said)


PHOTOS_HASH_MEDIA_ENV = "LOGBOOK_APPLE_PHOTOS_HASH_MEDIA"


def _media_digest(manifest: ios_backup.Manifest, source: ios_backup.Source) -> apple_photos.MediaDigest:
    """For an adapter whose `run` takes `media_digest` (`apple-photos`): the (sha256, bytes) of the
    file at a path below the phone's `Media/` folder, hashed straight from the backup through
    `ios_backup.digest` — decrypted on the way when the backup is, never copied — or None when the
    backup has no such file (an iCloud-optimised library keeps a thumbnail on the phone). Set
    LOGBOOK_APPLE_PHOTOS_HASH_MEDIA=0 to skip the hashing on a large library."""
    media_root = PurePosixPath(source.relative_path).parts[0]  # `Media`, of `Media/PhotoData/Photos.sqlite`

    def found(local_path: str) -> tuple[str, int] | None:
        parts = PurePosixPath(local_path).parts
        if not parts or any(part in ("..", "", "/") for part in parts):
            return None
        f = manifest.file(source.domain, PurePosixPath(media_root, *parts).as_posix())
        if f is None or f.size is None:
            return None
        return ios_backup.digest(f)

    return found


def _unlock(manifest: ios_backup.Manifest, inbox_folder: Path, command: str = "import-backup") -> None:
    """Unlock an encrypted backup with LOGBOOK_BACKUP_PASSWORD and decrypt its Manifest.db into
    the inbox. The extra, the variable, then the keybag are checked in that order; each failure is
    one line on stderr, prefixed by `command`, and exit 2, and none of them names the password."""
    if not ios_backup_crypto.available():
        print(f"{command}: {ENCRYPTED_NO_EXTRA}", file=sys.stderr)
        sys.exit(2)
    password = os.environ.get(PASSWORD_ENV, "")
    if not password:
        print(f"{command}: {ENCRYPTED_NO_PASSWORD}", file=sys.stderr)
        sys.exit(2)
    try:
        manifest.unlock(password, inbox_folder / ios_backup.MANIFEST_DB)
    except ios_backup.WrongPassword:
        print(f"{command}: {WRONG_PASSWORD}", file=sys.stderr)
        sys.exit(2)
    except (ios_backup.NotABackup, ios_backup.DecryptError, ios_backup.MissingExtra) as e:
        print(f"{command}: {e}", file=sys.stderr)
        sys.exit(2)
    finally:
        del password
    assert manifest.keybag is not None
    print(
        f"encrypted backup: keybag unlocked, keys for {len(manifest.keybag.classes)} protection classes;"
        f" {ios_backup.MANIFEST_DB} decrypted to {inbox_folder / ios_backup.MANIFEST_DB}"
    )


def _only(spec: str | None, encrypted: bool = False) -> tuple[ios_backup.Source, ...]:
    """`--only a,b,c` as sources in SOURCES order (EXTRAS after them); an unknown name exits 2
    naming the known ones. Without `--only`, every adapter's source, plus the EXTRAS when the
    backup is encrypted (only such a backup carries them)."""
    known_sources = ios_backup.SOURCES + ios_backup.EXTRAS
    if spec is None:
        return known_sources if encrypted else ios_backup.SOURCES
    wanted: set[str] = set()
    for word in spec.split(","):
        name = word.strip()
        if not name:
            continue
        source = ios_backup.source(name)
        if source is None:
            known = ", ".join(dict.fromkeys(s.name for s in known_sources))
            print(f"import-backup: no source named {name!r} (known: {known})", file=sys.stderr)
            sys.exit(2)
        wanted.add(source.name)
    if not wanted:
        print("import-backup: --only names no source", file=sys.stderr)
        sys.exit(2)
    return tuple(s for s in known_sources if s.name in wanted)


def _plan_row(p: ios_backup.Plan, inbox_folder: Path) -> str:
    """`<source>: <store> (<size>) [+ siblings] [+ N media files (<size>) under <folder>/] → <dest>`,
    or `<source>: <store> not found`; a folder source: `<source>: N <files> files (<size>) under
    <folder>/ → <dest>`, or `<source>: no <files> under <folder>`."""
    name = p.source.store_name
    if p.source.files is not None:
        if not p.found:
            return f"{p.source.name}: no {name} under {p.source.relative_path}"
        n = len(p.files)
        return (
            f"{p.source.name}: {n:,} {name} file{'s' if n != 1 else ''} ({p.bytes:,} bytes)"
            f" under {p.source.relative_path}/ → {inbox_folder / p.source.name}"
        )
    if not p.found:
        why = " (listed in Manifest.db, file missing)" if p.listed else ""
        return f"{p.source.name}: {p.source.store_name} not found{why}"
    assert p.store is not None
    parts = [f"{p.store.name} ({p.store.size or 0:,} bytes)"]
    parts += [f"{s.name} ({s.size:,} bytes)" for s in p.siblings if s.size is not None]
    media = [m for m in p.media if m.size is not None]
    if media:
        n, total = len(media), sum(m.size or 0 for m in media)
        parts.append(
            f"{n:,} media file{'s' if n != 1 else ''} ({total:,} bytes) under {p.source.media_folder}/"
        )
    return f"{p.source.name}: {' + '.join(parts)} → {inbox_folder / p.source.name}"


def inbox_arguments(sub: Subparsers) -> None:
    """`logbook inbox`."""
    s = sub.add_parser(
        "inbox", help="what is in inbox/, which import consumed it, and moving or deleting what is done"
    )
    verbs = s.add_subparsers(dest="verb", required=True)
    v = verbs.add_parser(
        "list", help="every file under inbox/: size, the import that read it, whether its lines are all in"
    )
    v.add_argument("--json", action="store_true", help="the same as one JSON object")
    v = verbs.add_parser(
        "clean",
        help="move every fully imported file to DIR (an external disk), or --delete it; the rest stays",
    )
    v.add_argument("--to", metavar="DIR", help="where the files go, keeping their path under inbox/")
    v.add_argument("--delete", action="store_true", help="remove the files instead of moving them")
    v.add_argument("--dry-run", action="store_true", help="say what would go and how much; touch nothing")
    s.set_defaults(fn=cmd_inbox)


def cmd_inbox(a: argparse.Namespace) -> None:
    """`inbox list [--json]`: every file under inbox/ with its size, the import that consumed it and
    whether every line it produced is in the record (`inbox.files`, the rules are there), then what
    may go. `inbox clean --to DIR | --delete [--dry-run]`: move every ready file to DIR (an external
    disk), keeping its path under inbox/, or delete it; a file not imported in full, changed since,
    or already at DIR is kept and said so; the freed size last. Nothing is ever read into the
    record here, and nothing is written to it."""
    lb = Logbook.find()
    if a.verb == "list":
        _inbox_list(lb, a.json)
        return
    if a.to is None and not a.delete:
        print("inbox clean: say where the files go: --to DIR or --delete", file=sys.stderr)
        sys.exit(2)
    if a.to is not None and a.delete:
        print("inbox clean: either --to DIR or --delete, not both", file=sys.stderr)
        sys.exit(2)
    to = Path(a.to).expanduser() if a.to is not None else None
    if to is not None and _inside(to, lb.root / inbox.INBOX):
        print(f"inbox clean: {to} is inside inbox/; name a folder outside it", file=sys.stderr)
        sys.exit(2)
    done = inbox.clean(lb, to, a.delete, a.dry_run)
    verb = (
        ("would delete" if a.dry_run else "deleted") if a.delete else ("would move" if a.dry_run else "moved")
    )
    for f in done.gone:
        print(f"{verb} {f.name}")
    for f in done.kept:
        print(f"kept {f.name}: {f.status}")
    n = len(done.gone)
    count = f"{n:,} file{'s' if n != 1 else ''}"
    where = "deleted" if a.delete else f"moved to {to}"
    if a.dry_run:
        print(f"would free {inbox.size_text(done.freed)}: {count}; nothing touched")
    else:
        print(f"freed {inbox.size_text(done.freed)}: {count} {where}")
    if done.kept:
        k = len(done.kept)
        print(f"kept {k:,} file{'s' if k != 1 else ''} not imported in full; logbook inbox list says which")


def _inbox_list(lb: Logbook, as_json: bool) -> None:
    folder = lb.root / inbox.INBOX
    found = inbox.files(lb) if folder.is_dir() else None
    ready = [f for f in found or [] if f.ready]
    ready_bytes = sum(f.bytes for f in ready)
    if as_json:
        print(
            json.dumps(
                {
                    "inbox": _under_home(folder),
                    "files": [f.to_json() for f in found or []],
                    "ready_files": len(ready),
                    "ready_bytes": ready_bytes,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return
    if found is None:
        print(f"no inbox/ folder at {_under_home(lb.root)}; `logbook init` makes one, or mkdir it")
        return
    if not found:
        print(f"inbox/ is empty ({_under_home(folder)})")
        return
    total = sum(f.bytes for f in found)
    n = len(found)
    print(f"inbox/ ({n:,} file{'s' if n != 1 else ''}, {inbox.size_text(total)})")
    width = min(max(len(f.name) for f in found), 60)
    for f in found:
        print(f"  {f.name:<{width}}  {inbox.size_text(f.bytes):>9}  {f.status}")
    if ready:
        r = len(ready)
        print(
            f"{inbox.size_text(ready_bytes)} in {r:,} file{'s' if r != 1 else ''} can be cleaned:"
            " logbook inbox clean --to DIR (or --delete)"
        )
    else:
        print("nothing can be cleaned yet: no file here is imported in full")


def _inside(path: Path, folder: Path) -> bool:
    """Whether `path` is `folder` or lies under it, resolved, part by part."""
    try:
        path.resolve().relative_to(folder.resolve())
    except ValueError:
        return False
    return True


def attach_arguments(sub: Subparsers) -> None:
    """`logbook attach`."""
    s = sub.add_parser(
        "attach",
        help="the attachment store (SPEC §1.1): fill it from an iOS backup, count it, check every file",
    )
    verbs = s.add_subparsers(dest="verb", required=True)
    v = verbs.add_parser(
        "import-backup",
        help="stream every media file the record's message and photo lines name out of an iOS backup into"
        " attachments/<sha256>, checked against the line; resumable, present files skipped",
    )
    v.add_argument("backup", help="the backup folder (Finder → Manage Backups → Show in Finder)")
    v.add_argument(
        "--only",
        required=True,
        metavar="NAMES",
        help="comma-separated sources, e.g. whatsapp,imessage,photos (known: "
        + ", ".join(src.name for src in attach.SOURCES)
        + ")",
    )
    v.add_argument("--since", metavar="YYYY-MM-DD", help="only the lines from this local day on")
    v.add_argument(
        "--dry-run", action="store_true", help="count what would be stored and what is missing; write nothing"
    )
    v.set_defaults(fn=cmd_attach)
    v = verbs.add_parser(
        "status", help="per source: attachments referenced, present and missing; the store's size"
    )
    v.add_argument("--json", action="store_true", help="the report as JSON")
    v.set_defaults(fn=cmd_attach)
    v = verbs.add_parser(
        "verify", help="stream every present file through SHA-256 against its name; exit 1 on a mismatch"
    )
    v.set_defaults(fn=cmd_attach)


def cmd_attach(a: argparse.Namespace) -> None:
    """`attach import-backup <folder> --only a,b [--since DAY] [--dry-run]`, `attach status`, `attach
    verify`: the SPEC §1.1 store filled from an iOS backup, counted, checked (`logbook/attach.py`).
    The pass appends nothing and holds no file whole; a file whose bytes are not the digest its line
    names is refused on one line and the command exits 1 at the end. `--only` is required: a run
    reads only the stores it was asked for, and a source disabled in `policy/import.json` is skipped
    and said so. An encrypted backup is unlocked as `import-backup` unlocks it, the password from
    LOGBOOK_BACKUP_PASSWORD and never a flag."""
    lb = Logbook.find()
    if a.verb == "status":
        counted = attach.status(lb)
        if a.json:
            print(json.dumps(counted, indent=2))
            return
        for text in attach.status_rows(counted):
            print(text)
        return
    if a.verb == "verify":
        checked = attach.verify(lb, attach.progress_line)
        for text in attach.verify_rows(checked):
            print(text)
        if checked.bad:
            sys.exit(1)
        return
    command = "attach import-backup"
    since: str | None = None
    if a.since is not None:
        try:
            since = date.fromisoformat(a.since).isoformat()
        except ValueError:
            print(f"{command}: --since takes a local day, YYYY-MM-DD, not {a.since!r}", file=sys.stderr)
            sys.exit(2)
    sources = _attach_only(a.only, command)
    try:
        manifest = ios_backup.Manifest(Path(a.backup).expanduser())
    except ios_backup.NotABackup as e:
        print(f"{command}: {e}", file=sys.stderr)
        sys.exit(2)
    sources = tuple(src for src in sources if not _say_disabled(lb, src.name))
    if manifest.encrypted:
        _unlock(manifest, lb.root / "inbox" / f"ios-backup-{manifest.udid}", command)
    report = attach.import_backup(
        lb,
        manifest,
        sources,
        since,
        a.dry_run,
        progress=attach.progress_line,
        say=lambda message: print(message, file=sys.stderr),
    )
    for tally in report.tallies:
        print(tally.row(a.dry_run))
    if a.dry_run:
        n, size = report.would_store
        print(f"dry run: {_plural(n, 'file')} ({size:,} bytes) would be stored; nothing written")
        return
    stored = sum(t.stored_bytes for t in report.tallies)
    store = attach.store_line(attach.status(lb)["store"])
    print(f"{_plural(report.stored, 'file')} stored ({stored:,} bytes); {store}")
    if report.refused:
        n = len(report.refused)
        print(f"{_plural(n, 'file')} refused: the bytes in the backup are not the ones the line names")
        sys.exit(1)


def _attach_only(spec: str, command: str) -> tuple[attach.MediaSource, ...]:
    """`--only a,b` as media sources in SOURCES order; an unknown name, or one whose lines name no
    media (`contacts`), exits 2 naming the known ones."""
    known = ", ".join(s.name for s in attach.SOURCES)
    wanted: set[str] = set()
    for word in spec.split(","):
        name = word.strip()
        if not name:
            continue
        found = attach.source(name)
        if found is None:
            print(f"{command}: no media source named {name!r} (known: {known})", file=sys.stderr)
            sys.exit(2)
        wanted.add(found.name)
    if not wanted:
        print(f"{command}: --only names no source (known: {known})", file=sys.stderr)
        sys.exit(2)
    return tuple(s for s in attach.SOURCES if s.name in wanted)
