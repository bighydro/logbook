"""What puts lines in: `add` (a sentence, a flight, an export file, a folder of them), `import-backup`
(the stores of an iOS backup) and `inbox` (what was dropped in the inbox folder)."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .. import adapters, attachments, flights, inbox, ios_backup, ios_backup_crypto
from ..adapters import ios_contacts
from ..export import parse_day
from ..resolve import Ref, identities_from
from ..store import Logbook, now_utc
from .common import (
    Subparsers,
    _airports,
    _csv,
    _is_rfc3339,
    _progress,
    _registry,
    _say_disabled,
    _takes,
    _under_home,
)
from .rows import _flight_text
from .skips import _report_skipped


def _add_file(lb: Logbook, p: Path, options: Mapping[str, Any] | None = None, dry_run: bool = False) -> bool:
    """Append one file through the adapter that recognises it. False when nothing does."""
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
    print(
        f"{p.name}: no adapter for this file yet (roadmap phase 1). "
        "Put it in inbox/ and it will be read when one exists."
    )
    return False


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
    `only_labels`, `skip_labels`), passed when the adapter's `run` takes them; one it does not take
    exits 2, so a flag is never silently ignored. An adapter whose `run` takes `owner_emails` gets
    the record's own addresses from `logbook.json` (RFC 0015), with a hint when there are none; one
    whose `run` takes `resolved` gets the refs the record already resolves, as `{(kind, value):
    entity id}` (RFC 0006), so a contacts import never mints a second id for a person it knows.
    With `dry_run` the adapter runs, the drafts are counted against the record and nothing is
    written: not a line, not an attachment."""
    if _say_disabled(lb, adapter.NAME):
        return 0
    counts: dict[str, int] = {}
    run: Callable[..., Iterator[dict[str, Any]]] = adapter.run
    options: dict[str, Any] = {}
    if _takes(adapter, "counts"):
        options["counts"] = counts
    if _takes(adapter, "timezone"):
        options["timezone"] = lb.meta["timezone"]
    if _takes(adapter, "store"):
        options["store"] = (lambda data: Path(attachments.DIR)) if dry_run else lb.attach
    if _takes(adapter, "store_file"):
        options["store_file"] = (lambda path: Path(attachments.DIR)) if dry_run else lb.attach_file
    if _takes(adapter, "assets"):
        options["assets"] = _registry(lb, "add")
    if _takes(adapter, "resolved"):
        options["resolved"] = _resolved(lb)
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
    for name, value in (given or {}).items():
        if value is None:
            continue
        if _takes(adapter, name):
            options[name] = value
        elif name != "at":  # `--at` has always been the sentence's time; a file adapter ignores it
            print(f"add: --{name} is not an option of the {adapter.NAME} adapter", file=sys.stderr)
            sys.exit(2)
    if _takes(adapter, "airports") and "airports" not in options:
        options["airports"] = _airports(None)
    seq_before, produced = int(lb.meta["seq"]), [0]
    drafts = flights.reconcile(lb, run(p, **options), counts, options.get("airports"))
    if dry_run:
        _say_dry_run(lb, adapter.NAME, drafts)
        _report_skipped(counts)
        return 0
    n = lb.append_many(_counted(drafts, produced), progress=_progress)
    print(f"added {n} lines from {adapter.NAME}")
    _report_skipped(counts)
    inbox.record(lb.root, inbox.finished(lb, recorded_as or p, adapter.NAME, produced[0], n, seq_before))
    return n


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


def _jsonl(p: Path) -> Iterator[dict[str, Any]]:
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


PATH_SUFFIXES = (".json", ".jsonl", ".geojson", ".zip", ".csv", ".txt")


def looks_like_path(arg: str) -> bool:
    """Something the shell would have expanded from a glob, or a file name."""
    return "/" in arg or arg.startswith("~") or arg.lower().endswith(PATH_SUFFIXES)


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
        "--dry-run",
        action="store_true",
        help="run the adapter, say how many lines would be added and how many are already in the record;"
        " write nothing",
    )
    s.set_defaults(fn=cmd_add)


def cmd_add(a: argparse.Namespace) -> None:
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
    }
    if a.what[0] == "flight" and len(a.what) > 1 and flights.starts_with_designator(" ".join(a.what[1:])):
        _add_flight(lb, " ".join(a.what[1:]), given["airports"] or _airports(None))
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
        if p.is_dir() and adapters.find(p) is not None:  # a folder one adapter reads as a whole
            if _add_file(lb, p, given, dry_run=a.dry_run):
                imported.append(p)
        elif p.is_dir():  # every file in it, in name order; hidden files are not exports
            for f in sorted(p.iterdir()):
                if f.is_file() and not f.name.startswith(".") and _add_file(lb, f, given, dry_run=a.dry_run):
                    imported.append(f)
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


def _add_sentence(lb: Logbook, what: str, at: str | None) -> None:
    """A sentence, in your own words."""
    line = lb.append(
        at=at or now_utc(), source="manual", kind="note", tier=2, payload={"schema": "note/v1", "text": what}
    )
    print(f"#{line['seq']} {line['at']}  {what}")


PASSWORD_ENV = "LOGBOOK_BACKUP_PASSWORD"
ENCRYPTED_NO_PASSWORD = (
    f"import-backup: this backup is encrypted; put its password in {PASSWORD_ENV} (never a flag) and re-run,"
    " or in Finder untick “Encrypt local backup”, back up again, then re-run"
)
ENCRYPTED_NO_EXTRA = f"import-backup: this backup is encrypted; reading it needs {ios_backup_crypto.EXTRA}"
WRONG_PASSWORD = (
    f"import-backup: {PASSWORD_ENV} does not unlock this backup's keybag (wrong password?);"
    " nothing was copied"
)
DIAL_PREFIX_HINT = (
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
        print(DIAL_PREFIX_HINT)
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
        given = {"attachments": True} if a.attachments and _takes(adapter, "attachments") else None
        _append_with(
            lb,
            adapter,
            store_copy.parent if p.source.pattern else store_copy,
            given,
            recorded_as=inbox_folder / p.source.name,
        )
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


def _unlock(manifest: ios_backup.Manifest, inbox_folder: Path) -> None:
    """Unlock an encrypted backup with LOGBOOK_BACKUP_PASSWORD and decrypt its Manifest.db into
    the inbox. The extra, the variable, then the keybag are checked in that order; each failure is
    one line on stderr and exit 2, and none of them names the password."""
    if not ios_backup_crypto.available():
        print(ENCRYPTED_NO_EXTRA, file=sys.stderr)
        sys.exit(2)
    password = os.environ.get(PASSWORD_ENV, "")
    if not password:
        print(ENCRYPTED_NO_PASSWORD, file=sys.stderr)
        sys.exit(2)
    try:
        manifest.unlock(password, inbox_folder / ios_backup.MANIFEST_DB)
    except ios_backup.WrongPassword:
        print(WRONG_PASSWORD, file=sys.stderr)
        sys.exit(2)
    except (ios_backup.NotABackup, ios_backup.DecryptError, ios_backup.MissingExtra) as e:
        print(f"import-backup: {e}", file=sys.stderr)
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
