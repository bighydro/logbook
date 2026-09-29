"""logbook — init · add · sync · import-backup · retract · show · stats · verify · export · index · migrate.
Three verbs, eight rare."""

from __future__ import annotations

import argparse
import contextlib
import inspect
import json
import os
import re
import sys
import time
import zoneinfo
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import date, datetime
from pathlib import Path, PurePath
from typing import Any
from zoneinfo import ZoneInfo

from . import FORMAT, __version__, adapters, crossing, ios_backup, policy
from .adapters import ios_contacts
from .chain import Line
from .export import day_packages, day_range, parse_day, write_package
from .resolve import Ref, labels
from .store import RETRACTION, CodeCheckoutError, FormatError, Logbook, now_utc, retractions

_LOCALTIME = "/etc/localtime"


def _zone_or_none(candidate: object) -> str | None:
    """The candidate when it names a real IANA zone, else None."""
    if not isinstance(candidate, str) or not candidate:
        return None
    try:
        zoneinfo.ZoneInfo(candidate)
    except (KeyError, ValueError, OSError):  # ZoneInfoNotFoundError is a KeyError
        return None
    return candidate


def _detect_timezone() -> str | None:
    """The local IANA zone, or None when nothing on this machine says which it is.

    datetime.now().astimezone() has no zone name on macOS (issue #25), so /etc/localtime
    comes first: it is a symlink into a zoneinfo tree whose tail is the zone name.
    """
    parts = PurePath(os.path.realpath(_LOCALTIME)).parts  # Windows: backslash-split
    if "zoneinfo" in parts:
        after_last = len(parts) - parts[::-1].index("zoneinfo")
        if zone := _zone_or_none("/".join(parts[after_last:])):
            return zone
    if zone := _zone_or_none(getattr(datetime.now().astimezone().tzinfo, "key", None)):
        return zone
    return _zone_or_none(os.environ.get("TZ"))


def _tz_default() -> str:
    return _detect_timezone() or "UTC"


def cmd_init(a: argparse.Namespace) -> None:
    root = Path(a.path or Path.home() / "Logbook").expanduser()
    timezone_name, hint = a.timezone, ""
    if not timezone_name:
        timezone_name = _detect_timezone()
    if not timezone_name:
        timezone_name = "UTC"
        hint = " (could not detect; pass --timezone Europe/Zurich to change)"
    try:
        lb = Logbook.init(root, timezone_name)
    except CodeCheckoutError as e:
        print(f"refusing to init: {e}", file=sys.stderr)
        sys.exit(2)
    print(
        f"created {lb.root}\ntimezone: {timezone_name}{hint}\n"
        f'Drop any export into {lb.root / "inbox"}, or: logbook add "what happened"'
    )


def _add_file(lb: Logbook, p: Path, options: Mapping[str, Any] | None = None) -> bool:
    """Append one file through the adapter that recognises it. False when nothing does."""
    adapter = adapters.find(p)
    if adapter is not None:
        _append_with(lb, adapter, p, options)
        return True
    if p.suffix == ".jsonl":  # observations produced by an adapter run by hand
        n = lb.append_many(_jsonl(p), progress=_progress)
        print(f"added {n} lines from {p.name}")
        return True
    print(
        f"{p.name}: no adapter for this file yet (roadmap phase 1). "
        "Put it in inbox/ and it will be read when one exists."
    )
    return False


def _append_with(
    lb: Logbook, adapter: adapters.Adapter, p: Path, given: Mapping[str, Any] | None = None
) -> int:
    """Run one file adapter on `p`, append, print what was added and what it skipped; the count.
    `given` are the command's own options (`source`, `tier`, `at`), passed when the adapter's `run`
    takes them; one it does not take exits 2, so a flag is never silently ignored."""
    counts: dict[str, int] = {}
    run: Callable[..., Iterator[dict[str, Any]]] = adapter.run
    options: dict[str, Any] = {}
    if _takes(adapter, "counts"):
        options["counts"] = counts
    if _takes(adapter, "timezone"):
        options["timezone"] = lb.meta["timezone"]
    if _takes(adapter, "store"):
        options["store"] = lb.attach
    for name, value in (given or {}).items():
        if value is None:
            continue
        if _takes(adapter, name):
            options[name] = value
        elif name != "at":  # `--at` has always been the sentence's time; a file adapter ignores it
            print(f"add: --{name} is not an option of the {adapter.NAME} adapter", file=sys.stderr)
            sys.exit(2)
    drafts = run(p, **options)
    n = lb.append_many(drafts, progress=_progress)
    print(f"added {n} lines from {adapter.NAME}")
    _report_skipped(counts)
    return n


def _takes(adapter: adapters.Adapter | adapters.LiveAdapter, option: str) -> bool:
    """Whether the adapter's `run` (or a live adapter's `pull`) accepts the optional keyword:
    `counts` (a dict to tally what it skipped), `timezone` (the record's zone, for a source whose
    times are floating), `store` (puts bytes in the attachment store), `lookup` (the id of a line by
    source and raw_id), or one of `add`'s own options."""
    if isinstance(adapter, adapters.Adapter):
        return option in inspect.signature(adapter.run).parameters
    live: adapters.LiveAdapter = adapter
    return option in inspect.signature(live.pull).parameters


LOCATION_SKIPS = ("skipped_no_timestamp", "skipped_bad_coordinates")
SKIP_PHRASES = {
    "skipped_no_timestamp": "without a timestamp",
    "skipped_bad_coordinates": "with unusable coordinates",
    "skipped_no_ref": "without a phone or email",
    "skipped_empty_ref": "with an empty phone or email",
    "skipped_duplicate_ref": "with a phone or email already seen",
    "skipped_no_lid": "without a linked-device id",
    "skipped_no_phone": "without a usable phone number",
    "skipped_duplicate_lid": "with a linked-device id already seen",
    "skipped_status": "in a status chat",
    "skipped_bad_date": "with an unusable date",
    "skipped_no_chat": "without a chat",
    "skipped_system_event": "group system events",
    "skipped_reaction": "reactions",
    "skipped_no_body": "without a body",
    "skipped_password_protected": "password protected",
    "skipped_no_text": "without any text",
    "skipped_no_start": "without a start",
    "skipped_placeholder_date": "with a placeholder start (before 1900)",
    "skipped_bad_start": "with an unusable start",
    "skipped_no_uid": "without a uid",
    "skipped_todo": "to-do items",
    "skipped_journal": "journal entries",
    "skipped_sidecar_without_file": "sidecars without a media file",
    "skipped_unreadable_json": "JSON files that would not parse",
    "skipped_not_media": "files that are not media",
    "skipped_not_transcript": "files that are not transcripts",
}
NOTE_PHRASES = {  # counts that are not skips: the line was written, with something worth knowing
    "no_stanza_id": "without a stanza id, keyed by row id",
    "no_guid": "without a guid, keyed by row id",
    "media_hashed": "with media hashed",
    "media_missing": "with media missing",
    "deleted": "marked for deletion",
    "body_from_snippet": "with the body taken from the snippet",
    "no_identifier": "without an identifier, keyed by row id",
    "no_unique_identifier": "without a unique identifier, keyed by row id",
    "live_photo_pairs": "live-photo pairs",
    "no_sidecar": "without a sidecar",
    "at_from_creation_time": "timed by creation time",
    "at_from_file_time": "timed by the file",
    "direct_chat": "in direct chats",
    "group_chat": "in group chats",
    "no_summary": "without a summary",
}


def _report_skipped(counts: dict[str, int]) -> None:
    """One line naming what an adapter left out and why, or nothing when it skipped nothing."""
    no_time = counts.get("skipped_no_timestamp", 0)
    bad_coords = counts.get("skipped_bad_coordinates", 0)
    if no_time or bad_coords:
        print(f"  skipped {no_time:,} without a timestamp, {bad_coords:,} with unusable coordinates")
    others = [
        f"{n:,} {SKIP_PHRASES.get(key, key.removeprefix('skipped_').replace('_', ' '))}"
        for key, n in counts.items()
        if key not in LOCATION_SKIPS and key.startswith("skipped_") and n
    ]
    if others:
        print("  skipped " + ", ".join(others))
    noted = [
        f"{n:,} {NOTE_PHRASES.get(key, key.replace('_', ' '))}"
        for key, n in counts.items()
        if not key.startswith("skipped_") and n
    ]
    if noted:
        print("  also " + ", ".join(noted))


def _progress(n: int, elapsed: float) -> None:
    print(f"  {n:,} lines in {elapsed:,.0f}s", file=sys.stderr)


def _page_progress(unit: str) -> Callable[[int, float], None]:
    """One line per page pulled from a live source, dry runs included, counting `unit`."""

    def report(n: int, elapsed: float) -> None:
        print(f"  {n:,} {unit} in {elapsed:,.0f}s", file=sys.stderr)

    return report


def _jsonl(p: Path) -> Iterator[dict[str, Any]]:
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


PATH_SUFFIXES = (".json", ".jsonl", ".geojson", ".zip", ".csv", ".txt")
EN_DASH = "\u2013"  # between the two clocks of a time span


def looks_like_path(arg: str) -> bool:
    """Something the shell would have expanded from a glob, or a file name."""
    return "/" in arg or arg.startswith("~") or arg.lower().endswith(PATH_SUFFIXES)


TRANSCRIPT = "transcript"  # `add transcript <file|folder>`: the universal transcript adapter by name


def cmd_add(a: argparse.Namespace) -> None:
    lb = Logbook.find()
    given = {"source": a.source, "tier": a.tier, "at": a.at}
    if a.what[0] == TRANSCRIPT and len(a.what) > 1:
        paths = [Path(w).expanduser() for w in a.what[1:]]
        if all(p.exists() for p in paths):  # else the whole thing may be a sentence
            _add_transcripts(lb, paths, given)
            return
    paths = [Path(w).expanduser() for w in a.what]
    # When nothing exists, the arguments are a sentence unless every one of them looks like a
    # path: "had 5/10 sleep" is a note, "~/Downloads/typo.json" is a typo.
    if not any(p.exists() for p in paths) and not all(looks_like_path(w) for w in a.what):
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
    for p in paths:
        if p.is_dir() and adapters.find(p) is not None:  # a folder one adapter reads as a whole
            _add_file(lb, p, given)
        elif p.is_dir():  # every file in it, in name order; hidden files are not exports
            for f in sorted(p.iterdir()):
                if f.is_file() and not f.name.startswith("."):
                    _add_file(lb, f, given)
        elif not _add_file(lb, p, given):
            ok = False
    if not ok:
        sys.exit(2)


def _add_transcripts(lb: Logbook, paths: list[Path], given: Mapping[str, Any]) -> None:
    """`add transcript <file|folder>...`: every path through the transcript adapter, whatever its
    format (Markdown and plain text are never sniffed), with `--source`, `--tier` and `--at`."""
    adapter = adapters.named(TRANSCRIPT)
    assert adapter is not None
    for p in paths:
        _append_with(lb, adapter, p, given)


def _add_sentence(lb: Logbook, what: str, at: str | None) -> None:
    """A sentence, in your own words."""
    line = lb.append(
        at=at or now_utc(), source="manual", kind="note", tier=2, payload={"schema": "note/v1", "text": what}
    )
    print(f"#{line['seq']} {line['at']}  {what}")


def cmd_sync(a: argparse.Namespace) -> None:
    """Pull from a live source since its stored watermark (or --since), append, advance the watermark.
    The watermark is the source's own clock (adapter.watermark), not the event time, so late uploads of
    old items are still picked up. It lives in <root>/state/<name>.json — bookkeeping, not the record."""
    adapter = adapters.live(a.name)
    if adapter is None:
        known = ", ".join(x.NAME for x in adapters.live_adapters()) or "none"
        print(f"sync: no live source named {a.name!r} (known: {known})", file=sys.stderr)
        sys.exit(2)
    try:
        config = adapter.configure(os.environ)
    except ValueError as e:
        print(f"sync: {a.name}: {e}", file=sys.stderr)
        sys.exit(2)
    if config is None:
        missing = [v for v in adapter.ENV if not os.environ.get(v, "").strip()]
        print(f"sync: {a.name}: set {' and '.join(missing)}", file=sys.stderr)
        sys.exit(2)
    if a.since is not None and not _is_rfc3339(a.since):
        print(
            f"sync: --since must be RFC3339 UTC, e.g. 2026-03-01T00:00:00Z, not {a.since!r}", file=sys.stderr
        )
        sys.exit(2)
    lb = Logbook.find()
    state_path = lb.root / "state" / f"{a.name}.json"
    stored = _read_state(state_path).get("since")
    since, resumed_from_record = _start(lb, adapter, config, a.since, stored)
    seen: dict[str, Any] = {
        "count": 0,
        "first": None,
        "last": None,
        "watermark": None,
        "provenance": Counter(),
        "kinds": Counter(),
    }
    counts: dict[str, int] = {}
    unit = str(getattr(adapter, "UNIT", "assets"))
    item = unit.removesuffix("s")  # one of them: a point, a message, an asset
    pull: Callable[..., Iterator[dict[str, Any]]] = adapter.pull
    options: dict[str, Any] = {}
    if _takes(adapter, "store") and not a.dry_run:
        options["store"] = lb.attach
    if _takes(adapter, "lookup"):
        options["lookup"] = _lookup(lb)
    drafts = _watch(
        pull(config, since, progress=_page_progress(unit), counts=counts, **options), adapter.watermark, seen
    )
    try:
        if a.dry_run:
            for _ in drafts:
                pass
        else:
            n = lb.append_many(drafts)  # the page lines above are the progress; one stream, not two
    except (OSError, ValueError) as e:  # urllib's errors are OSErrors, a malformed page a ValueError;
        print(f"sync: {a.name}: {e}", file=sys.stderr)  # what was pulled before is checkpointed
        sys.exit(1)
    where = f"since {since}" if since else "from the beginning"
    pending = counts.get("pending", 0)
    skipped = {k: v for k, v in counts.items() if k != "pending"}
    if resumed_from_record is not None:
        print(
            f"  starting from the record's newest {a.name} {item}, {resumed_from_record}, less the lookback"
        )
    if a.dry_run:
        print(f"{a.name}: {seen['count']} lines {where} (dry run, nothing written)")
        if seen["count"]:
            print(f"  first {seen['first']}  last {seen['last']}  watermark {seen['watermark'] or '-'}")
            for provenance, count in sorted(seen["provenance"].items()):
                if provenance != "-":
                    print(f"  {provenance}: {count}")
            if len(seen["kinds"]) > 1:
                for kind, count in sorted(seen["kinds"].items()):
                    print(f"  {kind}: {count}")
        _report_skipped(skipped)
        _report_pending(pending)
        return
    mark = seen["watermark"]
    if mark is not None and (stored is None or mark > stored):  # a watermark never moves backwards
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({"since": mark}, indent=2) + "\n", encoding="utf-8")
    else:
        mark = stored
    already = seen["count"] - n
    print(
        f"{a.name}: {n} new lines of {seen['count']} seen {where}"
        + (f" ({already} already in the record)" if already else "")
        + f"; watermark {mark or since or '-'}"
    )
    _report_skipped(skipped)
    _report_pending(pending)


def _lookup(lb: Logbook) -> Callable[[str, str], str | None]:
    """For a live adapter whose `pull` takes `lookup`: the id of the line with (source, raw_id), or
    None, read through the index, so a derived line can point at one already in the record."""

    def lookup(source: str, raw_id: str) -> str | None:
        with lb.index() as idx:
            return idx.line_id(source, raw_id)

    return lookup


def _start(
    lb: Logbook, adapter: adapters.LiveAdapter, config: object, given: str | None, stored: str | None
) -> tuple[str | None, str | None]:
    """Where a pull starts, and the record's newest line when that is what it started from.

    `--since` is used as given. Otherwise the stored watermark; an adapter with `resume` turns it
    into a start (a lookback before it, for a source whose items can arrive late) and, with no
    watermark yet, resumes from the record's newest line of its source and KIND, so a record seeded
    from an export carries on where the export ended."""
    if given is not None:
        return given, None
    resume = getattr(adapter, "resume", None)
    if resume is None:
        return stored, None
    if stored is not None:
        return str(resume(config, stored)), None
    with lb.index() as idx:
        newest = idx.newest(adapter.NAME, str(getattr(adapter, "KIND", "")))
    if newest is None:
        return None, None
    return str(resume(config, newest)), newest


def _report_pending(pending: int) -> None:
    """Assets the source has not finished processing; the adapter left them for a later sync."""
    if pending:
        print(f"  {pending:,} pending (metadata not extracted yet; will arrive on a later sync)")


def _watch(
    drafts: Iterable[dict[str, Any]],
    watermark: Callable[[dict[str, Any]], str | None],
    seen: dict[str, Any],
) -> Iterator[dict[str, Any]]:
    """Pass drafts through, noting count, earliest/latest `at`, the largest watermark and
    per-provenance counts."""
    for d in drafts:
        seen["count"] += 1
        at = d["at"]
        if seen["first"] is None or at < seen["first"]:
            seen["first"] = at
        if seen["last"] is None or at > seen["last"]:
            seen["last"] = at
        mark = watermark(d)
        if mark is not None and (seen["watermark"] is None or mark > seen["watermark"]):
            seen["watermark"] = mark
        seen["provenance"][d["payload"].get("provenance", "-")] += 1
        seen["kinds"][d["kind"]] += 1
        yield d


def _read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _is_rfc3339(value: str) -> bool:
    try:
        return datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False


ENCRYPTED_BACKUP = (
    "import-backup: this backup is encrypted and cannot be read; in Finder select the iPhone, untick"
    " “Encrypt local backup”, back up again, then re-run"
)
DIAL_PREFIX_HINT = (
    f"  {ios_contacts.DIAL_PREFIX_ENV} is not set: numbers saved without a country code stay as entered;"
    f" set it (for example {ios_contacts.DIAL_PREFIX_ENV}=41) to complete them"
)


def cmd_import_backup(a: argparse.Namespace) -> None:
    """Every phone source in one go, from an unencrypted iOS backup folder: each store is copied
    (with its -wal/-shm siblings and its media) into <root>/inbox/ios-backup-<udid>/<source>/,
    checked by size, and the adapter runs on the copy — never on the backup, which is only read.
    Sources run in `ios_backup.SOURCES` order (contacts before chats), then the chain is verified."""
    lb = Logbook.find()
    sources = _only(a.only)
    try:
        manifest = ios_backup.Manifest(Path(a.backup).expanduser())
    except ios_backup.NotABackup as e:
        print(f"import-backup: {e}", file=sys.stderr)
        sys.exit(2)
    if manifest.encrypted:
        print(ENCRYPTED_BACKUP, file=sys.stderr)
        sys.exit(2)
    plans = ios_backup.plan(manifest, sources)
    inbox = lb.root / "inbox" / f"ios-backup-{manifest.udid}"
    if a.dry_run:
        for p in plans:
            print(_plan_row(p, inbox))
        found = [p for p in plans if p.found]
        print(
            f"dry run: {len(found)} of {len(plans)} sources found, {sum(p.bytes for p in found):,} bytes"
            f" would be copied to {inbox}; nothing written"
        )
        return
    wants_prefix = any(p.found and p.source.name in ("ios-contacts", "whatsapp-contacts") for p in plans)
    if wants_prefix and not os.environ.get(ios_contacts.DIAL_PREFIX_ENV, "").strip():
        print(DIAL_PREFIX_HINT)
    for p in plans:
        print(_plan_row(p, inbox))
        if not p.found:
            continue
        adapter = adapters.named(p.source.name)
        if adapter is None:  # a build without this adapter: say so, copy nothing
            print(f"  no adapter named {p.source.name} in this build; skipped")
            continue
        try:
            store_copy = ios_backup.copy(p, inbox / p.source.name)
        except (ios_backup.CopyError, OSError) as e:
            print(f"import-backup: {p.source.name}: {e}", file=sys.stderr)
            sys.exit(1)
        _append_with(lb, adapter, store_copy)
    seq, head, errors = lb.verify()
    if errors:
        print(f"INVALID — {len(errors)} problem(s):")
        for problem in errors:
            print("  " + problem)
        sys.exit(1)
    print(f"valid — {seq} lines, head {head}")


def _only(spec: str | None) -> tuple[ios_backup.Source, ...]:
    """`--only a,b,c` as sources in SOURCES order; an unknown name exits 2 naming the known ones."""
    if spec is None:
        return ios_backup.SOURCES
    wanted: set[str] = set()
    for word in spec.split(","):
        name = word.strip()
        if not name:
            continue
        source = ios_backup.source(name)
        if source is None:
            known = ", ".join(s.name for s in ios_backup.SOURCES)
            print(f"import-backup: no source named {name!r} (known: {known})", file=sys.stderr)
            sys.exit(2)
        wanted.add(source.name)
    if not wanted:
        print("import-backup: --only names no source", file=sys.stderr)
        sys.exit(2)
    return tuple(s for s in ios_backup.SOURCES if s.name in wanted)


def _plan_row(p: ios_backup.Plan, inbox: Path) -> str:
    """`<source>: <store> (<size>) [+ siblings] [+ N media files (<size>) under <folder>/] → <dest>`,
    or `<source>: <store> not found`."""
    name = p.source.store_name
    if not p.found:
        why = " (listed in Manifest.db, file missing)" if p.listed else ""
        return f"{p.source.name}: {name} not found{why}"
    assert p.store is not None
    parts = [f"{name} ({p.store.size or 0:,} bytes)"]
    parts += [f"{s.name} ({s.size:,} bytes)" for s in p.siblings if s.size is not None]
    media = [m for m in p.media if m.size is not None]
    if media:
        n, total = len(media), sum(m.size or 0 for m in media)
        parts.append(
            f"{n:,} media file{'s' if n != 1 else ''} ({total:,} bytes) under {p.source.media_folder}/"
        )
    return f"{p.source.name}: {' + '.join(parts)} → {inbox / p.source.name}"


def cmd_retract(a: argparse.Namespace) -> None:
    lb = Logbook.find()
    try:
        line = lb.retract(a.seq, a.reason)
    except ValueError as e:
        print(f"retract: {e}", file=sys.stderr)
        sys.exit(2)
    print(f"#{line['seq']} {line['at']}  retracted #{a.seq}: {a.reason}")


def cmd_show(a: argparse.Namespace) -> None:
    """One local day (the owner's timezone), located through the index, read from the files,
    in time order (then chain order for the same instant). Senders, organizers and attendees
    are shown by the names the record's own resolution lines give them (RFC 0006), built once
    per call; `--raw` prints the refs as the sources gave them. Nothing is written."""
    lb = Logbook.find()
    day = date.today().isoformat() if a.day in (None, "today") else a.day
    tz = ZoneInfo(lb.meta["timezone"])
    with lb.index() as idx:
        # A retraction is not an event of its own day; it shows as a marker where the line it hides was.
        rows = [line for line in idx.day(day) if line["kind"] != RETRACTION]
        retracted = retractions(idx.retractions())
        names: dict[Ref, str] | None = None if a.raw else labels(lb, idx)
    if not rows:
        print(f"{day}: nothing logged")
        return
    rows.sort(key=lambda line: (line["at"], line["seq"]))
    print(day)
    for text in _day_rows(rows, retracted, tz, names):
        print(text)
    note = lb.root / "notes" / day[:4] / f"{day}.md"
    if note.exists():
        print("  — note —\n" + "\n".join("  " + s for s in note.read_text(encoding="utf-8").splitlines()))


def _day_rows(
    rows: list[Line], retracted: dict[str, Line], tz: ZoneInfo, names: Mapping[Ref, str] | None
) -> Iterator[str]:
    """One printed row per line, except that a run of location points from one source, unbroken
    by any other row, collapses into one summary. `names` is the label map; None is the `--raw`
    path: refs exactly as the sources gave them, no label, no fallback."""
    run: list[Line] = []
    for line in rows:
        retraction = retracted.get(line["id"])
        point = line["kind"] == "location" and retraction is None
        if run and not (point and line["source"] == run[0]["source"]):
            yield _run_row(run, tz)
            run = []
        if point:
            run.append(line)
        else:
            yield _line_row(line, retraction, tz, names)
    if run:
        yield _run_row(run, tz)


def _line_row(line: Line, retraction: Line | None, tz: ZoneInfo, names: Mapping[Ref, str] | None) -> str:
    clock = _clock(line["at"], tz)
    if retraction is not None:
        return f"  {clock}  retracted #{line['seq']}: {retraction['payload'].get('reason', '')}"
    p = line["payload"]
    if line["kind"] == "message":
        text = _message_text(p, names)
    elif line["kind"] == "event":
        text = _event_text(p, names)
    elif line["kind"] == "transcript":
        text = _transcript_text(p, names)
    else:
        text = (
            p.get("text")
            or p.get("title")
            or p.get("name")
            or ", ".join(f"{k}={v}" for k, v in p.items() if k != "schema")
        )
    return f"  {clock}  {line['kind']:<10} {line['source']:<14} {text}"


def _name(ref: object, names: Mapping[Ref, str] | None) -> str | None:
    """The label of a source-native ref `{kind, value}` (RFC 0006), else None."""
    if names is None or not isinstance(ref, dict):
        return None
    kind, value = ref.get("kind"), ref.get("value")
    if not isinstance(kind, str) or not isinstance(value, str):
        return None
    return names.get((kind, value))


def _ref_value(ref: object) -> str:
    return str(ref.get("value", "")) if isinstance(ref, dict) else ""


def _message_text(p: dict[str, Any], names: Mapping[Ref, str] | None) -> str:
    """`who: text`, `who in group: text`, `me → other: text` (RFC 0008). The sender is its label,
    else the name the source showed for it (`sender.name`), else the direct chat's own name, else
    the ref as given. A group is its name, else its id: a chat is not an entity (RFC 0006), so its
    id is never looked up. Raw (`names` None): the ref."""
    chat = p.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    direct = chat.get("type") == "direct"
    chat_name = str(chat.get("name") or "")
    if p.get("from_me"):
        who = "me"
    elif names is None:
        who = _ref_value(p.get("sender"))
    else:
        sender = p.get("sender")
        own = sender.get("name") if isinstance(sender, dict) else None
        who = (
            _name(sender, names)
            or (own if isinstance(own, str) else "")
            or (chat_name if direct else "")
            or _ref_value(sender)
        )
    if direct:
        prefix = f"{who} → {chat_name or chat_id}" if who == "me" else who
    else:
        prefix = f"{who} in {chat_name or chat_id}"
    body = p.get("text") or f"[{p.get('media_kind') or 'media'}]"
    return f"{prefix}: {body}"


def _event_text(p: dict[str, Any], names: Mapping[Ref, str] | None) -> str:
    """`title · by organizer · with attendees` (RFC 0009). An attendee is its label, else the
    name the calendar gave it, else the ref; raw (`names` None) is always the ref."""
    parts = [str(p.get("title") or "")]
    organizer = p.get("organizer")
    if organizer:
        parts.append(f"by {_name(organizer, names) or _ref_value(organizer)}")
    attendees = p.get("attendees") or []
    if attendees:
        parts.append("with " + ", ".join(_attendee(a, names) for a in attendees))
    return " · ".join(part for part in parts if part)


def _transcript_text(p: dict[str, Any], names: Mapping[Ref, str] | None) -> str:
    """`<title> — <participants>; <turns>, <length>` (RFC 0004). A participant is named by a
    resolution of its email when one exists, else as the source names it; `--raw` uses the source's
    name. Never the text: that is an attachment."""
    who = [
        _name({"kind": "email", "value": q.get("email")}, names) or str(q.get("name") or q.get("email") or "")
        for q in p.get("participants") or []
        if isinstance(q, dict)
    ]
    head = str(p.get("title") or "transcript")
    if any(who):
        head += " — " + ", ".join(w for w in who if w)
    extra: dict[str, Any] = p["extra"] if isinstance(p.get("extra"), dict) else {}
    parts: list[str] = []
    turns = extra.get("turns")
    if isinstance(turns, int):
        parts.append(_plural(turns, "turn"))
    duration = extra.get("duration_s")
    if isinstance(duration, int | float) and duration >= 0:
        parts.append(f"{duration / 60:.0f} min" if duration >= 60 else f"{duration:.0f} s")
    return head + ("; " + ", ".join(parts) if parts else "")


def _attendee(attendee: dict[str, Any], names: Mapping[Ref, str] | None) -> str:
    ref = attendee.get("ref")
    label = _name(ref, names)
    if label:
        return label
    own = attendee.get("name")
    if names is not None and isinstance(own, str) and own:
        return own
    return _ref_value(ref) or str(own or "")


def _run_row(run: list[Line], tz: ZoneInfo) -> str:
    """Time span, count, and the first and last named place of a run of location points."""
    first, last = _clock(run[0]["at"], tz), _clock(run[-1]["at"], tz)
    span = first if first == last else f"{first}{EN_DASH}{last}"
    n = len(run)
    text = f"{n:,} point{'s' if n != 1 else ''}"
    places = [place for place in map(_place, run) if place]
    if places:
        text += f" · {places[0]}" if places[0] == places[-1] else f" · {places[0]} → {places[-1]}"
    return f"  {span}  {'location':<10} {run[0]['source']:<14} {text}"


def _place(line: Line) -> str | None:
    """extra.place.district, else extra.place.city, else None (RFC 0001: `extra` is the source's)."""
    place = ((line.get("payload") or {}).get("extra") or {}).get("place") or {}
    value = place.get("district") or place.get("city")
    return str(value) if value else None


def _clock(at: str, tz: ZoneInfo) -> str:
    return datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(tz).strftime("%H:%M")


DIGEST = re.compile(r"[0-9a-f]{64}")  # an attachment's name (SPEC §1.1); anything else is never looked up
BAR = "\u2588"  # one full block per ~1% of the busiest year
BAR_WIDTH = 100


def cmd_stats(a: argparse.Namespace) -> None:
    """One screen of what the record holds, counted through the index (one SELECT per table,
    nothing read from the files): kinds, sources, years, retractions, resolutions, attachments.
    Numbers, kinds, sources and dates only; never what a line says. Nothing is written."""
    lb = Logbook.find()
    started = time.monotonic()
    stats = record_stats(lb)
    stats["took_seconds"] = round(time.monotonic() - started, 3)
    if a.json:
        print(json.dumps(stats, indent=2))
        return
    for text in _stats_rows(stats):
        print(text)


def record_stats(lb: Logbook) -> dict[str, Any]:
    """The numbers `stats` prints, as one JSON-ready object (no `took_seconds`)."""
    meta = lb.meta
    store = lb.root / "attachments"

    def present(sha256: str) -> bool:
        return DIGEST.fullmatch(sha256) is not None and (store / sha256).is_file()

    with lb.index() as idx:
        lines, first, last = idx.totals()
        return {
            "format": meta.get("format"),
            "head": meta.get("head"),
            "lines": lines,
            "first": first,
            "last": last,
            "kinds": idx.kinds(),
            "sources": idx.sources(),
            "years": idx.years(),
            "retractions": idx.retraction_counts(),
            "resolutions": idx.resolution_counts(),
            "attachments": idx.attachment_counts(present),
        }


def _stats_rows(s: dict[str, Any]) -> Iterator[str]:
    yield f"{s['format']}  head {s['head']}"
    if not s["lines"]:
        yield "0 lines"
    else:
        yield f"{s['lines']:,} lines  first {s['first']}  last {s['last']}"
    width = max(5, len(f"{s['lines']:,}"))
    if s["kinds"]:
        name = max(10, *(len(k["kind"]) for k in s["kinds"]))
        yield ""
        yield f"  {'kind':<{name}}  {'lines':>{width}}   first       last"
        for k in s["kinds"]:
            yield (
                f"  {k['kind']:<{name}}  {k['lines']:>{width},}   {k['first']}  {k['last']}"
                f"   {_plural(k['sources'], 'source')}"
            )
    if s["sources"]:
        name = max(10, *(len(x["source"]) for x in s["sources"]))
        yield ""
        yield f"  {'source':<{name}}  {'lines':>{width}}"
        for x in s["sources"]:
            yield f"  {x['source']:<{name}}  {x['lines']:>{width},}"
    if s["years"]:
        busiest = max(y["lines"] for y in s["years"])
        yield ""
        yield f"  year  {'lines':>{width}}"
        for y in s["years"]:
            bar = BAR * max(1, round(BAR_WIDTH * y["lines"] / busiest))  # a year with any line shows
            yield f"  {y['year']}  {y['lines']:>{width},}  {bar}"
    r, e, m = s["retractions"], s["resolutions"], s["attachments"]
    yield ""
    yield f"{_plural(r['lines'], 'retraction')} hiding {_plural(r['hidden'], 'line')}"
    yield f"{_plural(e['lines'], 'resolution line')} minting {_plural(e['entities'], 'entity', 'entities')}"
    yield (
        f"{_plural(m['referenced'], 'attachment')} referenced by {_plural(m['lines'], 'line')},"
        f" {m['present']:,} present under attachments/"
    )
    yield ""
    yield f"took {s['took_seconds']:.3f}s"


def _plural(n: int, noun: str, plural: str | None = None) -> str:
    return f"{n:,} {noun if n == 1 else plural or noun + 's'}"


def cmd_index(a: argparse.Namespace) -> None:
    """Rebuild index.sqlite from the files. Readers do this by themselves when it is missing or
    stale; this is the command that shows progress, or that you run after copying a logbook."""
    lb = Logbook.find()
    started = time.monotonic()
    n = lb.index_rebuild(progress=_progress)
    print(f"indexed {n:,} lines in {time.monotonic() - started:,.1f}s → {lb.root / 'index.sqlite'}")


def cmd_verify(a: argparse.Namespace) -> None:
    """Files only, never the index (ADR 0001)."""
    lb = Logbook(Path(a.root).expanduser()) if a.root else Logbook.find()
    warnings: list[str] = []
    seq, head, errors = lb.verify(warnings)
    if a.expect:
        exp = json.loads(Path(a.expect).read_text(encoding="utf-8"))
        if (exp["seq"], exp["head"]) != (seq, head):
            errors.append(
                f"expected seq={exp['seq']} head={exp['head'][:12]}…, got seq={seq} head={head[:12]}…"
            )
    if errors:
        print(f"INVALID — {len(errors)} problem(s):")
        for e in errors:
            print("  " + e)
        sys.exit(1)
    print(f"valid — {seq} lines, head {head}")
    if warnings:
        print(f"WARNING — {len(warnings)} timestamp(s) the next release will reject:")
        for w in warnings:
            print("  " + w)


def cmd_migrate(a: argparse.Namespace) -> None:
    """A logbook/0.1 record becomes logbook/0.2: same lines, hashes recomputed, lineage kept (SPEC §3.1)."""
    lb = Logbook(Path(a.root).expanduser()) if a.root else Logbook.find()
    try:
        result = lb.migrate(progress=_progress)
    except (FormatError, FileExistsError, ValueError) as e:
        print(f"migrate: {e}", file=sys.stderr)
        sys.exit(2)
    old, new = result["from_head"][:12], result["head"][:12]
    print(
        f"migrated {result['lines']} lines to {FORMAT}: head {old}… → {new}…\n"
        f"the 0.1 files are kept at {result['kept']}; delete them once `logbook verify` is green"
    )


def cmd_export(a: argparse.Namespace) -> None:
    lb = Logbook.find()
    if a.path == crossing.KIND:
        _export_crossing(lb, a)
        return
    if a.day or a.days:
        _export_days(lb, a)
        return
    if not a.path:
        print("export: give a .jsonl path, or --day YYYY-MM-DD, or --days FROM TO", file=sys.stderr)
        sys.exit(2)
    out = Path(a.path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w", encoding="utf-8") as fh:
        for line in lb.lines():
            fh.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
            n += 1
    print(f"exported {n} lines to {out} — verify with: logbook verify")


def _export_days(lb: Logbook, a: argparse.Namespace) -> None:
    """--day DATE [--out DIR]: one package at DIR (default <root>/export/DATE).
    --days FROM TO [--out DIR] [--empty]: one package per day at DIR/DATE (default <root>/export/DATE)."""
    try:
        if a.day:
            days = [parse_day(a.day).isoformat()]
            dirs = [Path(a.out).expanduser() if a.out else lb.root / "export" / a.day]
        else:
            days = day_range(*a.days)
            base = Path(a.out).expanduser() if a.out else lb.root / "export"
            dirs = [base / d for d in days]
    except ValueError as e:
        print(f"export: {e}", file=sys.stderr)
        sys.exit(2)
    written = 0
    packages = day_packages(lb, days)  # one read of the log for the whole range
    for day, out in zip(days, dirs, strict=True):
        package = packages[day]
        n = len(package["entries"])
        if a.days and not a.empty and n == 0:
            continue
        write_package(package, out)
        written += 1
        print(f"{day}: {n} entries → {out}")
    if a.days:
        print(f"wrote {written} day package(s)")


def _export_crossing(lb: Logbook, a: argparse.Namespace) -> None:
    """crossing --to DEST --since RFC3339|last [--until RFC3339] [--tier 1|1,2|1,2,3] [--kinds a,b]
    [--out DIR] [--dry-run]: one crossing-package/v1 (RFC 0005) under the destination's ceiling
    in policy/crossing.json (ADR 0016), recorded as a crossing/v1 line (RFC 0011)."""
    generated_at = now_utc()  # also the default window end, and the crossing line's `at`
    try:
        if not a.to or not a.since:
            raise crossing.CrossingError(
                "export crossing needs --to <destination> and --since <RFC3339|last>"
            )
        req = crossing.request(
            lb,
            a.to,
            a.since,
            a.until or generated_at,
            crossing.parse_tiers("1" if a.tier is None else a.tier),
            crossing.parse_kinds(a.kinds),
        )
    except crossing.EmptyWindow as e:
        print(f"{a.to}: {e}; nothing written")
        return
    except crossing.CrossingError as e:
        print(f"export crossing: {e}", file=sys.stderr)
        sys.exit(2)
    out = Path(a.out).expanduser() if a.out else crossing.default_out(lb, req.destination, generated_at)
    sel = crossing.select(lb, req)
    window = f"{req.since} {EN_DASH} {req.until}"
    tiers = ",".join(map(str, req.tiers))
    if a.dry_run:
        policy_file = policy.policy_path(lb.root)
        state = "" if policy_file.exists() else " (default; the first export writes it)"
        print(f"dry run: {req.destination}, {window}, tiers {tiers}; nothing written")
        print(f"  policy: {policy_file} {req.destination} max_tier {req.max_tier}{state}")
        for text in _crossing_rows(sel):
            print(text)
        if req.tier3:
            _tier3_warning(req, sel)
        return
    try:
        result = crossing.export(lb, req, sel, out, generated_at)
    except (crossing.CrossingError, OSError) as e:
        print(f"export crossing: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"{req.destination}: {sel.counts()['crossed']} lines crossed, {window}, tiers {tiers} → {out}")
    for text in _crossing_rows(sel):
        print(text)
    review = result.manifest.get("review")
    if review is not None:
        print(f"  review: {len(review)} tier-2 line(s) listed in {crossing.MANIFEST_FILE}")
    if req.tier3:
        _tier3_warning(req, sel)
    seq, digest = result.line["seq"], result.package_sha256[:12]
    print(f"  recorded as #{seq} {crossing.LINE_SCHEMA}, package sha256 {digest}…; watermark {req.until}")


def _crossing_rows(sel: crossing.Selection) -> Iterator[str]:
    c = sel.counts()
    yield f"  {c['logged']} lines in the window, {c['crossed']} cross, {c['held_back']} held back"
    yield "  " + "   ".join(f"tier {t}: {n}" for t, n in c["by_tier"].items())
    if c["by_kind"]:
        yield "  " + "   ".join(f"{k}: {n}" for k, n in c["by_kind"].items())
    yield f"  resolutions: {c['resolutions']} cross, {c['resolutions_held_back']} held back by tier"
    m = c["attachments"]
    files, missing = _plural(m["included"], "file"), m["missing"]
    yield f"  attachments: {files}, {m['bytes']:,} bytes; {missing} missing from the store"


def _tier3_warning(req: crossing.Request, sel: crossing.Selection) -> None:
    n = sum(1 for line in [*sel.lines, *sel.resolutions] if int(line["tier"]) == 3)
    text = f"WARNING: {crossing.TIER3_WARNING}: {_plural(n, 'tier-3 line')} for {req.destination}"
    print(text)
    print(text, file=sys.stderr)


def main(argv: list[str] | None = None) -> None:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252; the CLI speaks UTF-8
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="logbook", description="A diary that writes itself.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init", help="create a logbook (default ~/Logbook)")
    s.add_argument("path", nargs="?")
    s.add_argument("--timezone")
    s.set_defaults(fn=cmd_init)
    s = sub.add_parser("add", help="a sentence in your words, an export file, or a folder of them")
    s.add_argument("what", nargs="+", help="the words, the path(s), or `transcript <file|folder>`")
    s.add_argument("--at", help="RFC3339 UTC, default now; for a transcript file, its start")
    s.add_argument("--source", help="transcript: the provider, e.g. granola, zoom (default manual)")
    s.add_argument("--tier", type=int, choices=(1, 2, 3), help="transcript: privacy tier (default 3)")
    s.set_defaults(fn=cmd_add)
    s = sub.add_parser(
        "sync", help="pull new items from a live source (immich, dawarich, imessage); safe to re-run"
    )
    s.add_argument("name", help="the source: immich, dawarich, or imessage (this Mac's Messages)")
    s.add_argument("--since", metavar="RFC3339", help="pull from here instead of the stored watermark")
    s.add_argument("--dry-run", action="store_true", help="show what would be appended; write nothing")
    s.set_defaults(fn=cmd_sync)
    s = sub.add_parser(
        "import-backup",
        help="every phone source from an unencrypted iOS backup folder: copy each store into inbox/, add it",
    )
    s.add_argument("backup", help="the backup folder (Finder → Manage Backups → Show in Finder)")
    s.add_argument(
        "--dry-run", action="store_true", help="list what would be copied and imported; write nothing"
    )
    s.add_argument(
        "--only",
        metavar="NAMES",
        help="comma-separated sources, e.g. contacts,whatsapp (known: "
        + ", ".join(src.name for src in ios_backup.SOURCES)
        + ")",
    )
    s.set_defaults(fn=cmd_import_backup)
    s = sub.add_parser("retract", help="take back line SEQ with a new line; nothing is rewritten")
    s.add_argument("seq", type=int)
    s.add_argument("reason")
    s.set_defaults(fn=cmd_retract)
    s = sub.add_parser("show", help="one day (default today)")
    s.add_argument("day", nargs="?")
    s.add_argument("--raw", action="store_true", help="print refs as the sources gave them, never a name")
    s.set_defaults(fn=cmd_show)
    s = sub.add_parser("stats", help="what the record holds: counts by kind, source and year, never its text")
    s.add_argument("--json", action="store_true", help="the same numbers as one JSON object")
    s.set_defaults(fn=cmd_stats)
    s = sub.add_parser("index", help="rebuild index.sqlite from the files (readers do it when needed)")
    s.set_defaults(fn=cmd_index)
    s = sub.add_parser("verify", help="check the chain")
    s.add_argument("--root", help="logbook folder (default: find)")
    s.add_argument("--expect", help="expected.json with seq and head (conformance)")
    s.set_defaults(fn=cmd_verify)
    s = sub.add_parser(
        "export",
        help="the whole log as one .jsonl, one day-package/v1 per day, or `crossing`: a crossing-package/v1",
    )
    s.add_argument("path", nargs="?", help=".jsonl file for the whole log, or `crossing` (RFC 0005)")
    s.add_argument("--day", metavar="YYYY-MM-DD", help="one day-package/v1 directory")
    s.add_argument("--days", nargs=2, metavar=("FROM", "TO"), help="one directory per day, inclusive")
    s.add_argument("--out", metavar="DIR", help="where to write (default <root>/export/<date>/)")
    s.add_argument("--empty", action="store_true", help="with --days: also write days with no entries")
    s.add_argument("--to", metavar="DESTINATION", help="crossing: the circle member, e.g. hermes")
    s.add_argument("--since", metavar="RFC3339|last", help="crossing: window start, or the last window's end")
    s.add_argument("--until", metavar="RFC3339", help="crossing: window end, exclusive (default now)")
    s.add_argument("--tier", metavar="1|1,2|1,2,3", help="crossing: tiers to cross (default 1)")
    s.add_argument("--kinds", metavar="a,b", help="crossing: only these kinds")
    s.add_argument(
        "--dry-run", action="store_true", help="crossing: count and show the policy; write nothing"
    )
    s.set_defaults(fn=cmd_export)
    s = sub.add_parser("migrate", help="bring a logbook/0.1 record to logbook/0.2 (same lines, new hashes)")
    s.add_argument("--root", help="logbook folder (default: find)")
    s.set_defaults(fn=cmd_migrate)
    a = ap.parse_args(argv)
    try:
        a.fn(a)
    except FormatError as e:  # verify and every writer refuse a record hashed by another rule
        print(f"{a.cmd}: {e}", file=sys.stderr)
        sys.exit(2)
    except BrokenPipeError:  # the reader went away (`| head`): stop quietly, status 0
        _stdout_to_devnull()


def _stdout_to_devnull() -> None:
    """Point stdout at the null device so the interpreter's final flush does not report the
    broken pipe on stderr and turn the exit status into 120."""
    with contextlib.suppress(OSError, ValueError):  # no real file behind stdout (a test capture)
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())


if __name__ == "__main__":
    main()
