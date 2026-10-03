"""logbook — init · setup · add · sync · import-backup · inbox · infer · transcribe · describe · retract ·
show · stats · derive · places · rollup · trips · trip · ledger · keepers · promises · tasks · serve ·
verify · doctor · export · share · receive · circle · index · migrate · assets · sources · mcp · backup.
Three verbs, twenty-eight rare."""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import inspect
import json
import os
import re
import sys
import time
import zoneinfo
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path, PurePath, PurePosixPath
from typing import Any
from zoneinfo import ZoneInfo

from . import (
    FORMAT,
    __version__,
    adapters,
    apps,
    asset_status,
    assets,
    attach,
    attachments,
    backup,
    crossing,
    demo,
    demo_life,
    describe,
    drifting,
    events,
    flights,
    gaps,
    health,
    inbox,
    ios_backup,
    ios_backup_crypto,
    judge,
    keepers,
    ledger,
    listen_rollup,
    mcp_server,
    pages,
    people,
    people_merge,
    places,
    policy,
    print_page,
    promises,
    questions,
    reading,
    repair,
    rollup,
    schedule,
    search,
    serve,
    setup,
    share,
    stays,
    story,
    taskdone,
    transcribe,
    trip_bundle,
    trip_page,
    trips,
    vault,
)
from . import (
    day as day_reader,
)
from . import (
    days as days_reader,
)
from . import (
    digest as digest_reader,
)
from . import (
    doctor as doctor_checks,
)
from . import (
    weather as weather_reader,
)
from . import (
    year as year_reader,
)
from .adapters import ais, apple_photos, ios_contacts, screentime
from .adapters import weather as weather_adapter
from .adapters.takeout import maps as takeout_maps
from .adapters.takeout import places as takeout_places
from .chain import Line, number_text
from .export import day_packages, day_range, parse_day, write_package
from .index import Index, local_date
from .resolve import Ref, identities_from, labels
from .store import (
    RETRACTION,
    CodeCheckoutError,
    FormatError,
    Logbook,
    UnsortedFile,
    dedupe_key,
    now_utc,
    retractions,
    utc,
)

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
        f"created {_under_home(lb.root)}\ntimezone: {timezone_name}{hint}\n"
        f'Drop any export into {_under_home(lb.root / "inbox")}, or: logbook add "what happened"'
    )


def _under_home(path: Path) -> str:
    """`~/Logbook` for a path inside the home directory, else the path as given: what is printed
    (and recorded in a demo) never spells the user's name."""
    try:
        return str(PurePath("~") / path.relative_to(Path.home()))
    except ValueError:
        return str(path)


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
            f"{shown or p.name}: no adapter for this file yet. "
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


def _registry(lb: Logbook, command: str) -> list[assets.Asset]:
    """The record's asset registry for an adapter that takes `assets`; a broken file exits 2."""
    try:
        return assets.read(lb.root)
    except assets.AssetError as e:
        print(f"{command}: {e}", file=sys.stderr)
        sys.exit(2)


def _disabled(lb: Logbook) -> dict[str, str]:
    """The disabled sources of `policy/import.json` by adapter NAME (`books` stands for `apple-books`,
    `health` for `apple-health`, as in `adapters.ALIASES`); a malformed file exits 2 naming it."""
    try:
        listed = policy.disabled(lb.root)
    except policy.PolicyError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)
    return {adapters.ALIASES.get(name, name): reason for name, reason in listed.items()}


def _say_disabled(lb: Logbook, name: str) -> bool:
    """True, having said so, when the owner disabled the source `name` in `policy/import.json`."""
    reason = _disabled(lb).get(adapters.ALIASES.get(name, name))
    if reason is None:
        return False
    print(f"{name}: disabled ({reason}); skipped — {policy.import_path(lb.root)}")
    return True


def _takes(adapter: adapters.Adapter | adapters.LiveAdapter, option: str, live: bool = False) -> bool:
    """Whether the adapter's `run` (or, for `sync`, its `pull`: `live`) accepts the optional keyword:
    `counts` (a dict to tally what it skipped), `timezone` (the record's zone, for a source whose
    times are floating), `store` (puts bytes in the attachment store), `store_file` (puts a file
    there, streamed), `lookup` (the id of a line by
    source and raw_id), `resolved` (the refs the record resolves, `{(kind, value): entity id}`), `failed`
    (a live adapter's list for the feeds it could not read), `progress` (a file adapter's own
    reporter, every 10,000 items with the bytes read), `cursor` (the inbox manifest's, so a long
    import resumes), or one of
    `assets` (the asset registry, ADR 0018), `places` (the record's named places), `report` (lines
    `add` prints after the counts), `listen_s`, `notice` and `status` (a source that listens
    to a stream, `ais`), or one of `add`'s own options. A module can be both a file and a live
    adapter (`ais`), so `sync` asks about `pull`, never `run`."""
    if live and isinstance(adapter, adapters.LiveAdapter):
        return option in inspect.signature(adapter.pull).parameters
    if isinstance(adapter, adapters.Adapter):
        return option in inspect.signature(adapter.run).parameters
    pulls: adapters.LiveAdapter = adapter
    return option in inspect.signature(pulls.pull).parameters


LOCATION_SKIPS = ("skipped_no_timestamp", "skipped_bad_coordinates")
SKIP_PHRASES = {
    "skipped_no_timestamp": "without a timestamp",
    "skipped_bad_coordinates": "with unusable coordinates",
    "skipped_no_ref": "without a phone or email",
    "skipped_no_place": "without a departure place",
    "skipped_unknown_timezone": "with a timezone the zone database does not know",
    "skipped_empty_ref": "with an empty phone or email",
    "skipped_duplicate_ref": "with a phone or email already seen",
    "skipped_already_resolved": "already resolved in the record",
    "skipped_no_lid": "without a linked-device id",
    "skipped_no_phone": "without a usable phone number",
    "skipped_audiobook": "of an audiobook (RFC 0019 has tracks and episodes)",
    "skipped_not_a_play": "not a play (a start, a lyric view)",
    "skipped_duplicate_lid": "with a linked-device id already seen",
    "skipped_status": "in a status chat",
    "skipped_bad_date": "with an unusable date",
    "skipped_no_chat": "without a chat",
    "skipped_system_event": "group system events",
    "skipped_reaction": "reactions",
    "skipped_no_body": "without a body",
    "skipped_password_protected": "password protected",
    "skipped_no_text": "without any text",
    "skipped_no_title": "without a title",
    "skipped_no_url": "without a url",
    "skipped_ad": "advertisements",
    "skipped_never_played": "never played",
    "skipped_other_activity": "of another activity",
    "skipped_not_involved": "the owner is not part of",
    "skipped_no_owner": "with nobody to be the owner",
    "skipped_no_amount": "without an amount",
    "skipped_no_currency": "without a currency",
    "skipped_gift_cards": "gift cards",
    "skipped_covered_by_chrome": "Chrome visits, which google-takeout-chrome reads from Chrome/History.json",
    "skipped_encrypted": "encrypted with no decrypted copy in the store",
    "skipped_redacted": "redacted, or redactions",
    "skipped_call": "calls, not messages",
    "skipped_no_start": "without a start",
    "skipped_no_date": "without a date",
    "skipped_placeholder_date": "with a placeholder start (before 1900)",
    "skipped_bad_start": "with an unusable start",
    "skipped_no_uid": "without a uid",
    "skipped_todo": "to-do items",
    "skipped_journal": "journal entries",
    "skipped_empty": "with nothing in them",
    "skipped_no_bundle": "without a bundle id",
    "skipped_duplicate": "already seen",
    "skipped_web_domain": "per-site web time (the domain is never kept)",
    "skipped_sidecar_without_file": "sidecars without a media file",
    "skipped_unreadable_json": "JSON files that would not parse",
    "skipped_unreadable": "passes that would not parse",
    "skipped_no_flight": "boarding passes without a readable flight",
    "skipped_store_cards": "store and loyalty cards",
    "skipped_coupons": "coupons",
    "skipped_generic_passes": "generic passes",
    "skipped_unknown_style": "passes of no known style",
    "skipped_not_media": "files that are not media",
    "skipped_not_transcript": "files that are not transcripts",
    "skipped_unknown_subject": "of a vessel or aircraft not in assets.json",
    "skipped_not_a_position": "that are not position reports",
    "skipped_no_designator": "without a carrier and flight number",
    "skipped_no_route": "without both airports",
    "skipped_label": "by label",
    "skipped_no_value": "without a value",
    "skipped_bad_span": "ending before they start",
    "skipped_other_type": "of a type this version does not know",
    "skipped_unknown_stage": "with a sleep stage this version does not know",
    "skipped_over_cap": "over the one-per-minute heart-rate cap",
    "skipped_reading_position": "reading positions",
    "skipped_deleted": "deleted",
    "skipped_trashed": "in the trash",
    "skipped_relayed": "relayed from another app",
    "skipped_daily_total": "daily totals",
    "skipped_no_data": "days the provider had no values for (asked again next run)",
    "skipped_unreadable_csv": "CSV files without the columns this reader needs",
    "skipped_unreadable_row": "rows that would not parse",
}
NOTE_PHRASES = {  # counts that are not skips: the line was written, with something worth knowing
    "merged_into_known_people": "contacts merged into people the record knows",
    "no_chat_message_id": "without a message id, keyed by time and text",
    "no_owner": "with nobody named as the owner (owner_emails in logbook.json), so nothing is mine",
    "no_conference_id": "without a conference id, keyed by start and organizer",
    "no_transaction_id": "without a transaction id, keyed by time, merchant and amount",
    "media_stored": "with media stored",
    "no_stanza_id": "without a stanza id, keyed by row id",
    "no_guid": "without a guid, keyed by row id",
    "no_unique_id": "without a unique id, keyed by row id",
    "no_counterparty": "without a counterparty",
    "media_hashed": "with media hashed",
    "media_missing": "with media missing",
    "no_name": "without an app name",
    "deleted": "marked for deletion",
    "load_failed": "that did not load",
    "no_url": "of a removed video, without a url",
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
    "no_recording": "without a recording (summary only)",
    "merged": "merged into a flight already in the record",
    "corrected": "corrected: a later export changed a sample, the line in the record is superseded",
    "no_airport_zone": "with an airport the table does not know",
    "arrival_before_departure": "arriving before departing, kept as given",
    "no_gap": "calendar flights the location points do not confirm",
    "covered": "legs a tracked flight already covers",
    "no_message_id": "without a Message-ID, keyed by digest",
    "date_from_separator": "timed by the mbox separator (no Date header)",
    "body_from_html": "with the body taken from HTML",
    "decoding_errors": "with undecodable bytes replaced",
    "attachments_referenced": "attachments referenced, not stored",
    "attachments_stored": "attachments stored",
    "attachments_missing": "attachments missing from the export",
    "trashed": "marked trashed",
    "pending": "still pending",
    "from_last_message": "from a room's last-message row (not in the event cache)",
    "owner_guessed": "owner taken as the person on most expenses (no owner_emails matched)",
    "no_title": "without a title",
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


def _read_progress(unit: str) -> Callable[[int, int, float], None]:
    """A file adapter's own progress (`mail`, every 10,000 messages): the items read, the bytes
    read and the rate, on stderr."""

    def report(n: int, read: int, elapsed: float) -> None:
        rate = read / 1e6 / elapsed if elapsed > 0 else 0.0
        print(f"  {n:,} {unit} · {read / 1e6:,.0f} MB read · {rate:,.1f} MB/s", file=sys.stderr)

    return report


def _file_progress(n_files: int) -> Callable[[str, int, int, float], None]:
    """`verify --progress`: one line per month file in path order, on stderr, so
    stdout stays the one line it always was. `file i of N` is that path rank."""
    i = 0

    def report(file: str, n: int, total: int, elapsed: float) -> None:
        nonlocal i
        i += 1
        print(
            f"  file {i} of {n_files}: {file}: {n:,} lines ({total:,} so far, {elapsed:,.0f}s)",
            file=sys.stderr,
        )

    return report


def _page_progress(unit: str, status: Mapping[str, Any] | None = None) -> Callable[[int, float], None]:
    """One line per page pulled from a live source, dry runs included, counting `unit`. A source
    that listens (`ais`) calls it once a minute and keeps a tally per asset in `status["heard"]`,
    which the line carries in parentheses."""

    def report(n: int, elapsed: float) -> None:
        heard = status.get("heard") if status is not None else None
        per_asset = f" ({', '.join(f'{k} {v:,}' for k, v in sorted(heard.items()))})" if heard else ""
        print(f"  {n:,} {unit} in {elapsed:,.0f}s{per_asset}", file=sys.stderr)

    return report


def _window_text(seconds: float) -> str:
    """A window in words: `45 s`, `5 min`, `2 h 12 min`."""
    hours, rest = divmod(round(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    parts = [f"{hours} h"] if hours else []
    if minutes:
        parts.append(f"{minutes} min")
    if secs or not parts:
        parts.append(f"{secs} s")
    return " ".join(parts)


def _jsonl(p: Path) -> Iterator[dict[str, Any]]:
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


PATH_SUFFIXES = (".json", ".jsonl", ".geojson", ".zip", ".csv", ".txt")
EN_DASH = "\u2013"  # between the two clocks of a time span
EM_DASH = "\u2014"  # heads an asset's section of `derive stays`


def looks_like_path(arg: str) -> bool:
    """Something the shell would have expanded from a glob, or a file name."""
    return "/" in arg or arg.startswith("~") or arg.lower().endswith(PATH_SUFFIXES)


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


def _csv(value: str | None) -> list[str] | None:
    """A comma-separated flag as a list, None when the flag was not given."""
    if value is None:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def _add_named(
    lb: Logbook, adapter: adapters.Adapter, paths: list[Path], given: Mapping[str, Any], dry_run: bool = False
) -> None:
    """`add <adapter> <file|folder>...`: every path through the named adapter, sniffed or not
    (`transcript` reads Markdown and plain text this way only; `ios-calls` a store copied out of a
    backup under any name), with `--source`, `--tier` and `--at` when it takes them."""
    for p in paths:
        _append_with(lb, adapter, p, given, dry_run=dry_run)


def _airports(given: str | None) -> flights.Airports:
    """The airports table with the override `--airports` names, else `LOGBOOK_AIRPORTS`, else none;
    a file that will not read exits 2 naming the line."""
    path = given or os.environ.get(flights.AIRPORTS_ENV, "").strip() or None
    try:
        return flights.Airports.load(Path(path).expanduser() if path else None)
    except (OSError, ValueError) as e:
        print(f"add: --airports: {e}", file=sys.stderr)
        sys.exit(2)


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


def cmd_sync(a: argparse.Namespace) -> None:
    """`sync <source>`: pull from a live source since its stored watermark (or --since), append,
    advance the watermark. `sync --all`: every configured source in turn (`_sync_all`). `sync
    --install-schedule` / `--uninstall-schedule`: `sync --all` twice a day by the machine's own
    scheduler (`_sync_schedule`, `logbook.schedule`)."""
    if a.install_schedule or a.uninstall_schedule:
        _sync_schedule(a)
        return
    if a.all:
        _sync_all(a)
        return
    if a.name is None:
        known = ", ".join(x.NAME for x in adapters.live_adapters()) or "none"
        print(f"sync: say a source or --all, e.g. `logbook sync immich` (known: {known})", file=sys.stderr)
        sys.exit(2)
    _sync_source(a)


def _sync_all(a: argparse.Namespace) -> None:
    """Every live source that is configured — at least one of its `ENV` variables set, and its
    `configure` taking the environment — pulled in turn, each from its own watermark; a source the
    owner disabled or one with no variable set is skipped and said so. A failure in one (its exit
    status, or an error its adapter let through) never stops the next: it is said on stderr as a
    single run says it, and the run goes on. At the end one summary line per source — `ok`,
    `failed (status N)`, `skipped (why)` — and exit 1 when any failed. A Ctrl-C while a source
    listens to a stream (ais, status 130) ends the run there: the sources not reached are listed as
    `not run` and the status is 130. `--dry-run` passes through; `--since`, `--listen` and `--until`
    are a single source's and refused."""
    if a.name is not None:
        print(
            f"sync: --all takes no source name; run `logbook sync {a.name}` for that one alone",
            file=sys.stderr,
        )
        sys.exit(2)
    for flag, value in (("--since", a.since), ("--listen", a.listen), ("--until", a.until)):
        if value is not None:
            print(f"sync: --all takes no {flag}: each source starts from its own watermark", file=sys.stderr)
            sys.exit(2)
    lb = Logbook.find()
    disabled = _disabled(lb)
    live = adapters.live_adapters()
    results: list[tuple[str, str]] = []
    interrupted = False
    for adapter in live:
        name = adapter.NAME
        if interrupted:
            results.append((name, "not run"))
            continue
        if name in disabled:
            _say_disabled(lb, name)
            results.append((name, "skipped (disabled)"))
            continue
        reason = _unconfigured(adapter)
        if reason is not None:
            print(f"{name}: {reason}; skipped")
            results.append((name, f"skipped ({reason})"))
            continue
        status = 0
        try:
            _sync_source(argparse.Namespace(**{**vars(a), "name": name, "all": False}))
        except SystemExit as e:
            status = e.code if isinstance(e.code, int) else 1
        except Exception as e:
            print(f"sync: {name}: {type(e).__name__}: {e}", file=sys.stderr)
            status = 1
        if status == 130:  # Ctrl-C while the source listened: the owner wants out, not the next source
            interrupted = True
            results.append((name, "interrupted"))
            continue
        results.append((name, "ok" if status == 0 else f"failed (status {status})"))
    ok = sum(1 for _, r in results if r == "ok")
    failed = sum(1 for _, r in results if r.startswith("failed"))
    skipped = sum(1 for _, r in results if r.startswith("skipped"))
    print(
        f"sync --all: {_plural(len(results), 'source')}: {ok} ok, {failed} failed, {skipped} skipped"
        + (", interrupted" if interrupted else "")
    )
    width = max((len(name) for name, _ in results), default=0)
    for name, result in results:
        print(f"  {name:<{width}}  {result}")
    if interrupted:
        sys.exit(130)
    if failed:
        sys.exit(1)


def _unconfigured(adapter: adapters.LiveAdapter) -> str | None:
    """Why `sync --all` leaves a source out, or None when it is configured: none of its variables
    set (`LOGBOOK_IMMICH_URL, LOGBOOK_IMMICH_KEY not set`), one still missing (`set
    LOGBOOK_IMMICH_KEY`), or a value its `configure` refuses. A source whose variables are all
    optional (`imessage`) joins the run once the owner sets one of them."""
    if not adapter.ENV:
        return "takes no variables; run it by name"
    if not any(os.environ.get(v, "").strip() for v in adapter.ENV):
        return f"{', '.join(adapter.ENV)} not set"
    try:
        config = adapter.configure(os.environ)
    except ValueError as e:
        return str(e)
    if config is None:
        missing = [v for v in adapter.ENV if not os.environ.get(v, "").strip()]
        return f"set {' and '.join(missing)}"
    return None


def _sync_schedule(a: argparse.Namespace) -> None:
    """`sync --install-schedule`: a launchd agent (macOS) or a systemd user timer (Linux) running
    `logbook sync --all` at 07:00 and 19:00 local, the plist or units printed before they are
    written, nothing written outside that one directory, then handed to the scheduler (or, when it
    is not on PATH, the command to run said). `--uninstall-schedule`: the reverse. The record found
    now is the one the agent is pointed at (`LOGBOOK_HOME`)."""
    if a.install_schedule and a.uninstall_schedule:
        print("sync: --install-schedule or --uninstall-schedule, not both", file=sys.stderr)
        sys.exit(2)
    flag = "--install-schedule" if a.install_schedule else "--uninstall-schedule"
    others = (a.name, a.all or None, a.dry_run or None, a.since, a.listen, a.until)
    if any(x is not None for x in others):
        print(f"sync: {flag} takes no source and no other option", file=sys.stderr)
        sys.exit(2)
    lb = Logbook.find()
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    try:
        plan = schedule.plan(
            schedule.system(), Path.home(), sys.executable, lb.root, Path(xdg).expanduser() if xdg else None
        )
    except schedule.ScheduleError as e:
        print(f"sync: {flag}: {e}", file=sys.stderr)
        sys.exit(2)
    if a.uninstall_schedule:
        if not any(path.exists() for path in plan.files):
            print(f"no schedule installed ({plan.directory})")
            return
        problem = schedule.run(plan.deactivate, plan.tool, print)
        for path in schedule.uninstall(plan):
            print(f"removed {path}")
        if problem is not None:
            print(f"sync: {flag}: {problem}", file=sys.stderr)
            sys.exit(1)
        return
    schedule.install(plan, print)
    for text in schedule.summary(plan):
        print(text)
    problem = schedule.run(plan.activate, plan.tool, print)
    if problem is not None:
        print(f"sync: {flag}: {problem}", file=sys.stderr)
        sys.exit(1)


def _sync_source(a: argparse.Namespace) -> None:
    """Pull from a live source since its stored watermark (or --since), append, advance the watermark.
    The watermark is the source's own clock (adapter.watermark), not the event time, so late uploads of
    old items are still picked up. It lives in <root>/state/<name>.json — bookkeeping, not the record."""
    adapter = adapters.live(a.name)
    if adapter is None:
        known = ", ".join(x.NAME for x in adapters.live_adapters()) or "none"
        print(f"sync: no live source named {a.name!r} (known: {known})", file=sys.stderr)
        sys.exit(2)
    if adapter.NAME == weather_adapter.NAME:  # a window of local days from the record, not a watermark pull
        _sync_weather(a)
        return
    listens = _takes(adapter, "listen_s", live=True)  # a source that listens to a stream for a window (ais)
    listen_s = _listen_flag(a, listens)
    lb = Logbook.find()
    if _say_disabled(lb, adapter.NAME):  # before the variables: a switched-off source needs none
        return
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
    options: dict[str, Any] = {}
    if _takes(adapter, "store", live=True) and not a.dry_run:
        options["store"] = lb.attach
    if _takes(adapter, "lookup", live=True):
        options["lookup"] = _lookup(lb)
    if _takes(adapter, "timezone", live=True):
        options["timezone"] = lb.meta["timezone"]
    failed: list[str] = []  # one line per feed the adapter could not read, the others still pulled
    if _takes(adapter, "failed", live=True):
        options["failed"] = failed
    if _takes(adapter, "assets", live=True):
        options["assets"] = _registry(lb, "sync")
    status: dict[str, Any] = {}  # what a listening source reports: messages per asset, reconnects, Ctrl-C
    if listens:
        zone = ZoneInfo(str(lb.meta["timezone"]))
        if a.until is not None:
            try:
                listen_s = ais.seconds_until(a.until, zone, datetime.now(zone))
            except ValueError as e:
                print(f"sync: --until {e}", file=sys.stderr)
                sys.exit(2)
            print(
                f"  listening until {a.until.strip()} {zone.key} ({_window_text(listen_s)})", file=sys.stderr
            )
        else:
            listen_s = listen_s if listen_s is not None else float(getattr(config, "listen_s", 0.0))
            print(f"  listening for {_window_text(listen_s)}", file=sys.stderr)
        options["listen_s"] = listen_s
        options["status"] = status
        options["notice"] = lambda text: print(f"  {text}", file=sys.stderr)
    group: Callable[[dict[str, Any]], str] | None = getattr(adapter, "group", None)
    seen["groups"] = Counter()
    seen["group_marks"] = {}  # the largest watermark per group, kept in the state when GROUP_MARKS
    already_in_group: Counter[str] = Counter()
    drafts = _watch(
        adapter.pull(config, since, progress=_page_progress(unit, status), counts=counts, **options),
        adapter.watermark,
        seen,
        group,
    )
    try:
        if a.dry_run:
            for _ in drafts:
                pass
        else:
            n = lb.append_many(  # the page lines above are the progress; one stream, not two
                drafts, skipped=(lambda d: already_in_group.update([group(d)])) if group else None
            )
    except (OSError, ValueError) as e:  # urllib's errors are OSErrors, a malformed page a ValueError;
        print(f"sync: {a.name}: {e}", file=sys.stderr)  # what was pulled before is checkpointed
        sys.exit(1)
    for problem in failed:
        print(f"sync: {a.name}: {problem}", file=sys.stderr)
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
        for name, count in seen["groups"].items():
            print(f"  {name}: {count} seen")
        _report_skipped(skipped)
        _report_pending(pending)
        _report_listening(status)
        if failed:
            sys.exit(1)
        if status.get("interrupted"):
            sys.exit(130)
        return
    mark = seen["watermark"]
    if failed:  # a feed that was not read may hold changes older than the lookback: try again from here
        kept = f" (kept: {len(failed)} {'feed' if len(failed) == 1 else 'feeds'} failed)"
        mark = stored
    elif mark is not None and (stored is None or mark > stored):  # a watermark never moves backwards
        kept = ""
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(_state(state_path, adapter, mark, seen), indent=2) + "\n", encoding="utf-8"
        )
    else:
        kept = ""
        mark = stored
    already = seen["count"] - n
    print(
        f"{a.name}: {n} new lines of {seen['count']} seen {where}"
        + (f" ({already} already in the record)" if already else "")
        + f"; watermark {mark or since or '-'}{kept}"
    )
    for name, count in seen["groups"].items():
        print(f"  {name}: {count - already_in_group[name]} new of {count} seen")
    _report_skipped(skipped)
    _report_pending(pending)
    _report_listening(status)
    if failed:
        sys.exit(1)
    if status.get("interrupted"):  # what was heard is written and summed up above; the shell still learns
        sys.exit(130)


WEATHER_LOOKBACK_DAYS = 7  # a run without --since starts this far before the last day it covered


def _sync_weather(a: argparse.Namespace) -> None:
    """`sync weather [--since DAY] [--until DAY] [--dry-run]`: for every local day of the window, the
    owner's overnight stay and every stay of three hours or more, each place rounded to a tenth of a
    degree (`weather.clusters`), the daily values fetched from Open-Meteo once per cluster and run of
    days and cached under `inbox/weather/` (`adapters.weather.pull`), one `weather/v1` line per
    cluster-day appended; a re-run refetches nothing and appends nothing already there. The window
    defaults to the day after the last day covered (`state/weather.json`, less a week's lookback for
    points that arrive late) — or the record's first located day — up to yesterday. A dry run plans
    and counts and neither fetches nor writes. The variable `LOGBOOK_WEATHER` is `sync --all`'s to
    read: by name the command needs none."""
    if a.listen is not None:
        print("sync: --listen is for a source that listens to a stream (ais), not weather", file=sys.stderr)
        sys.exit(2)
    lb = Logbook.find()
    if _say_disabled(lb, weather_adapter.NAME):
        return
    state_path = lb.root / "state" / f"{weather_adapter.NAME}.json"
    stored = _read_state(state_path).get("since")
    try:
        window = _weather_window(lb, a.since, a.until, stored if isinstance(stored, str) else None)
    except ValueError as e:
        print(f"sync: weather: {e}", file=sys.stderr)
        sys.exit(2)
    if window is None:
        print("weather: no days to cover (the record has no location lines, or none before today)")
        return
    first, last = window
    try:
        clusters = weather_reader.clusters(lb, first, last)
    except stays.SettingsError as e:
        print(f"sync: weather: {e}", file=sys.stderr)
        sys.exit(2)
    days = len(day_range(first, last))
    cache = lb.root.joinpath(*weather_adapter.CACHE_DIR.parts)
    tz = str(lb.meta["timezone"])
    today = date.fromisoformat(_today())
    span = f"{first} {EN_DASH} {last}"
    if a.dry_run:
        to_fetch = weather_adapter.outstanding(clusters, cache)
        requests = weather_adapter.plan(to_fetch, today)
        print(
            f"weather: {len(clusters)} cluster-days over {_plural(days, 'day')} {span}, "
            f"{len(clusters) - len(to_fetch)} cached, {len(to_fetch)} to fetch in "
            f"{_plural(len(requests), 'request')} (dry run, nothing written)"
        )
        return
    from_cache = len(clusters) - len(weather_adapter.outstanding(clusters, cache))
    counts: dict[str, int] = {}
    failed: list[str] = []
    seen = 0

    def counted(draft: dict[str, Any]) -> dict[str, Any]:
        nonlocal seen
        seen += 1
        return draft

    fetched: list[int] = [0]

    def progress(n: int, elapsed: float) -> None:
        fetched[0] = n
        _page_progress(weather_adapter.UNIT)(n, elapsed)

    drafts = (
        counted(d)
        for d in weather_adapter.pull(
            weather_adapter.Config(),
            progress=progress,
            counts=counts,
            clusters=clusters,
            cache=cache,
            timezone=tz,
            failed=failed,
            today=today,
        )
    )
    try:
        n = lb.append_many(drafts)
    except (OSError, ValueError) as e:
        print(f"sync: weather: {e}", file=sys.stderr)
        sys.exit(1)
    for problem in failed:
        print(f"sync: weather: {problem}", file=sys.stderr)
    already = seen - n
    print(
        f"weather: {n} new lines of {seen} seen for {_plural(days, 'day')} {span}"
        + (f" ({already} already in the record)" if already else "")
        + f"; {_plural(fetched[0], 'request')}, {from_cache} cluster-days from the cache"
    )
    _report_skipped(counts)
    if failed:
        sys.exit(1)
    if stored is None or last > str(stored):
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps({"source": weather_adapter.NAME, "since": last, "updated_at": now_utc()}, indent=2)
            + "\n",
            encoding="utf-8",
        )


def _weather_window(
    lb: Logbook, since: str | None, until: str | None, stored: str | None
) -> tuple[str, str] | None:
    """The local days `sync weather` covers: `--since` to `--until`, each a day; without `--until`,
    yesterday; without `--since`, a week before the last day covered, or the record's first located
    day. None when nothing is left to cover. ValueError for a day that is not one or a window that
    runs backwards."""
    for text in (since, until):
        if text is not None:
            try:
                parse_day(text)
            except ValueError:
                raise ValueError(f"days are YYYY-MM-DD, not {text!r}") from None
    yesterday = (date.fromisoformat(_today()) - timedelta(days=1)).isoformat()
    last = until if until is not None else yesterday
    if since is not None:
        first = since
    elif stored is not None:
        first = (date.fromisoformat(stored) - timedelta(days=WEATHER_LOOKBACK_DAYS)).isoformat()
    else:
        whole = reading.record_days(lb, "location")
        if whole is None:
            return None
        first = whole[0]
    if last < first:
        if since is not None and until is not None:
            raise ValueError(f"range runs backwards: {since} > {until}")
        return None
    return first, last


def _listen_flag(a: argparse.Namespace, listens: bool) -> float | None:
    """`--listen SECONDS` as a number, None when not given; exits 2 when the source does not listen,
    when both --listen and --until are given, or when the seconds are not a number above 0.
    `--until` is turned into seconds later, once the record's zone is known."""
    if a.listen is None and a.until is None:
        return None
    if not listens:
        print(
            f"sync: --listen and --until are for a source that listens to a stream (ais), not {a.name}",
            file=sys.stderr,
        )
        sys.exit(2)
    if a.listen is not None and a.until is not None:
        print("sync: give --listen or --until, not both", file=sys.stderr)
        sys.exit(2)
    if a.listen is None:
        return None
    try:
        return ais.seconds(a.listen)
    except ValueError as e:
        print(f"sync: --listen {e}", file=sys.stderr)
        sys.exit(2)


def _report_listening(status: Mapping[str, Any]) -> None:
    """How a listening source's run went, after the counts: the reconnects, if any."""
    n = int(status.get("reconnects", 0))
    if n:
        print(f"  reconnected {'once' if n == 1 else f'{n} times'}")


def cmd_infer(a: argparse.Namespace) -> None:
    """`infer flights [--since DAY] [--until DAY] [--airports FILE] [--dry-run]`: flight/v1 lines
    (RFC 0013, evidence `inferred`) from the record's own calendar entries and location points,
    merged into the flights already standing; a re-run appends nothing new."""
    if a.what == "keepers":
        _infer_keepers(a)
        return
    if a.what != "flights":
        print(f"infer: flights or keepers can be inferred, not {a.what!r}", file=sys.stderr)
        sys.exit(2)
    for day in (a.since, a.until):
        if day is not None:
            try:
                parse_day(day)
            except ValueError as e:
                print(f"infer: {e}", file=sys.stderr)
                sys.exit(2)
    lb = Logbook.find()
    airports = _airports(a.airports)
    counts: dict[str, int] = {}
    drafts = flights.reconcile(lb, flights.infer(lb, airports, a.since, a.until, counts), counts, airports)
    already = 0

    def skipped(_draft: dict[str, Any]) -> None:
        nonlocal already
        already += 1

    if a.dry_run:
        found = list(drafts)
        with lb.index() as idx:  # what append_many would skip: the observations the record already holds
            already = len(idx.existing({key for d in found if (key := dedupe_key(d)) is not None}))
        n = len(found) - already
    else:
        n = lb.append_many(drafts, skipped=skipped)
    entries_text = _plural(counts.pop("calendar_flights", 0), "calendar entry", "calendar entries")
    already_text = f" ({already} already in the record)" if already else ""
    if a.dry_run:
        would = f"{_plural(n, 'flight')} from {entries_text} would be written"
        print(f"dry run: {would}{already_text}; nothing written")
    else:
        print(f"inferred {_plural(n, 'new flight')} from {entries_text}{already_text}")
    _report_skipped(counts)


def cmd_transcribe(a: argparse.Namespace) -> None:
    """`transcribe voice-memos [--since DAY] [--model NAME] [--dry-run] [--fetch-model]`: a
    transcript/v1 line per standing voice memo whose audio is in the store, heard by a local engine
    (RFC 0004, RFC 0023); a re-run transcribes nothing twice. No engine is needed for a dry run."""
    if a.what != "voice-memos":
        print(f"transcribe: voice-memos can be transcribed, not {a.what!r}", file=sys.stderr)
        sys.exit(2)
    if a.since is not None:
        try:
            parse_day(a.since)
        except ValueError as e:
            print(f"transcribe: {e}", file=sys.stderr)
            sys.exit(2)
    lb = Logbook.find()
    engine: transcribe.Engine | None = None
    if not a.dry_run:
        try:
            engine = transcribe.detect(a.model)
        except transcribe.EngineMissing as e:
            print(f"transcribe: {e}", file=sys.stderr)
            sys.exit(2)
    try:
        report = transcribe.run(
            lb, engine, since=a.since, dry_run=a.dry_run, fetch_model=a.fetch_model, progress=print
        )
    except transcribe.ModelMissing as e:
        print(f"transcribe: {e}", file=sys.stderr)
        sys.exit(2)
    print(transcribe.describe(report))


def cmd_describe(a: argparse.Namespace) -> None:
    """`describe keepers [--since DAY] [--limit N] [--photos DIR ...] [--model NAME] [--fetch-model]
    [--dry-run] [--json]`: a derived note/v1 line per standing keeper (RFC 0024) whose photo file is
    reachable — one factual sentence and the visible things, by a local vision model, never a
    person's name, never a place (`logbook.describe`); a photo already described is skipped. No
    model runs unless asked; a dry run needs no engine. Without the engine or the model the command
    prints the install and fetch lines and exits 2."""
    if a.what != "keepers":
        print(f"describe: keepers can be described, not {a.what!r}", file=sys.stderr)
        sys.exit(2)
    if a.since is not None:
        try:
            parse_day(a.since)
        except ValueError as e:
            print(f"describe: {e}", file=sys.stderr)
            sys.exit(2)
    lb = Logbook.find()
    roots = describe.Roots(Path(p) for p in (a.photos or []))
    engine: describe.Engine | None = None
    if not a.dry_run:
        try:
            engine = describe.detect(a.model)
        except describe.EngineMissing as e:
            print(f"describe: {e}", file=sys.stderr)
            print(describe.how_to(a.model), file=sys.stderr)
            sys.exit(2)
    try:
        report = describe.run(
            lb,
            engine,
            since=a.since,
            limit=a.limit,
            fetch_model=bool(a.fetch_model),
            roots=roots,
            dry_run=bool(a.dry_run),
            progress=lambda text: print(text, file=sys.stderr),
        )
    except describe.ModelMissing as e:
        print(f"describe: {e}", file=sys.stderr)
        print(describe.how_to(a.model), file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(report.to_json(), indent=2, ensure_ascii=False))
        return
    print(describe.summary(report))


def cmd_sources(a: argparse.Namespace) -> None:
    """`sources`: every adapter this build has, file and live, with its state under
    `policy/import.json` — `enabled`, or `disabled (<reason>)`; then any disabled name that is no
    adapter, so a typo in the file is seen rather than silently ignored.

    `sources --gaps [--since DAY] [--expect SOURCE...] [--json]`: where each source went quiet, from
    the index alone (`gaps.report`, the rules are there) — per source its lines in the range, its
    last line's time, the longest silent stretch and the days with no line. With `--expect` only
    those sources are shown, a flagged one marked `!`, and the command exits 1 when any is flagged,
    so a cron job can say so. Nothing is written."""
    if not a.gaps and (a.since is not None or a.expect is not None or a.json):
        print("sources: --since, --expect and --json go with --gaps", file=sys.stderr)
        sys.exit(2)
    lb = Logbook.find()
    if a.gaps:
        try:
            data = gaps.report(lb, since=a.since, expect=a.expect)
        except ValueError as e:
            print(f"sources: {e}", file=sys.stderr)
            sys.exit(2)
        if a.json:
            print(json.dumps(data, indent=2))
        else:
            for text in gaps.rows(data):
                print(text)
        if data["flagged"]:
            sys.exit(1)
        return
    disabled = _disabled(lb)
    kinds: dict[str, list[str]] = {}
    for file_adapter in adapters.file_adapters():
        kinds.setdefault(file_adapter.NAME, []).append("file")
    for live_adapter in adapters.live_adapters():
        kinds.setdefault(live_adapter.NAME, []).append("live")
    for name in sorted(kinds):
        reason = disabled.get(name)
        state = "enabled" if reason is None else f"disabled ({reason})"
        print(f"{name:<20} {'+'.join(kinds[name]):<10} {state}")
    for name, reason in disabled.items():
        if name not in kinds:
            print(f"{name:<20} {'-':<10} disabled ({reason}); no adapter by that name in this build")
    n = len(kinds)
    off = sum(name in kinds for name in disabled)
    print(f"{n} adapters, {off} disabled; the list is {policy.import_path(lb.root)}")


def _infer_keepers(a: argparse.Namespace) -> None:
    """`infer keepers [--dry-run]`: keeper/v1 lines (RFC 0024) from the marks on the record's
    photo lines — a favourite is a `memory`, the Art album is `art` — through `append_many`, so a
    mark already in the record, retracted or not, is never written twice."""
    lb = Logbook.find()
    counts: dict[str, int] = {}
    with lb.index() as idx:
        retracted = retractions(idx.retractions())
        photos = [line for line in idx.of_kind("photo") if str(line["id"]) not in retracted]
    drafts = list(keepers.infer(photos, counts))
    already = 0

    def skipped(_draft: dict[str, Any]) -> None:
        nonlocal already
        already += 1

    if a.dry_run:
        with lb.index() as idx:
            already = len(idx.existing({key for d in drafts if (key := dedupe_key(d)) is not None}))
        n = len(drafts) - already
    else:
        n = lb.append_many(drafts, skipped=skipped)
    photos_text = f"{_plural(counts.get('marked', 0), 'marked photo')} of {counts.get('photos', 0)}"
    already_text = f" ({already} already in the record)" if already else ""
    if a.dry_run:
        would = f"{_plural(n, 'keeper')} from {photos_text} would be written"
        print(f"dry run: {would}{already_text}; nothing written")
    else:
        print(f"inferred {_plural(n, 'new keeper')} from {photos_text}{already_text}")


def cmd_keepers(a: argparse.Namespace) -> None:
    """`keepers [--since DAY] [--until DAY] [--lane memory|art] [--people] [--json]`: the keeper
    lines standing (RFC 0024), by day; with `--people`, who appears on them per month — the faces
    the library named and the people it tagged on each keeper's photo, resolved through the
    resolution lines where a name is exactly a label, every one proposed (`keepers.people_by_month`).
    Nothing is written."""
    lb = Logbook.find()
    for day in (a.since, a.until):
        if day is not None:
            try:
                parse_day(day)
            except ValueError as e:
                print(f"keepers: {e}", file=sys.stderr)
                sys.exit(2)
    tz = str(lb.meta["timezone"])
    with lb.index() as idx:
        found = keepers.standing([*idx.by_kind(keepers.KIND, a.since, a.until), *idx.retractions()])
        if a.lane is not None:
            found = [line for line in found if (line.get("payload") or {}).get("lane") == a.lane]
        if a.people:
            _keepers_people(lb, idx, found, tz, a)
            return
    rows = [keepers.summary(line, local_date(str(line["at"]), tz)) for line in found]
    rows.sort(key=lambda r: (r["day"], r["at"], r["lane"]))
    if a.json:
        print(json.dumps({"keepers": rows}, indent=2, ensure_ascii=False))
        return
    if not rows:
        print(_no_keepers(a))
        return
    zone = ZoneInfo(tz)
    for r in rows:
        photo = r["photo"] if isinstance(r["photo"], dict) else {}
        name = photo.get("file_name") or photo.get("asset_id") or "?"
        print(f"  {r['day']}  {_clock(r['at'], zone)}  {r['lane']:<6} {r['source']:<10} {name}")


def _no_keepers(a: argparse.Namespace) -> str:
    lane = f" in lane {a.lane}" if a.lane else ""
    return f"no keepers{lane}; `logbook infer keepers` reads the marks"


def _keepers_people(lb: Logbook, idx: Index, found: list[Line], tz: str, a: argparse.Namespace) -> None:
    """`keepers --people`: the keepers' photo lines by id and the identities through the index, then
    `keepers.people_by_month`; a table by month, or `{"people": [...]}`."""
    photo_ids = {
        str(ref.get("line"))
        for line in found
        if isinstance(ref := (line.get("payload") or {}).get("photo"), dict) and ref.get("line")
    }
    photos = idx.by_ids(photo_ids)
    identities = identities_from([*idx.retractions(), *idx.resolutions()])
    rows = keepers.people_by_month(found, photos, identities, tz)
    if a.json:
        print(json.dumps({"people": rows}, indent=2, ensure_ascii=False))
        return
    if not found:
        print(_no_keepers(a))
        return
    if not rows:
        print(f"{_plural(len(found), 'keeper')}, nobody named on them")
        return
    month = None
    for r in rows:
        if r["month"] != month:
            month = r["month"]
            print(month)
        lanes = " · ".join(f"{lane} {n}" for lane, n in r["lanes"].items() if n)
        who = r["name"] if r["person"] else f"{r['name']} (no person)"
        print(f"  {who:<28} {_plural(r['keepers'], 'keeper'):>11}  {lanes:<22} {r['status']}")


def cmd_promises(a: argparse.Namespace) -> None:
    """`promises [--since DAY] [--open] [--all] [--judge [--limit N] [--model NAME] [--fetch-model]]
    [--json]`: the commitments the transcript and note lines suggest, found by rules
    (`logbook.promises`), printed as proposals and never as facts. By default the ones a local model
    judged a commitment at confidence 0.6 or above (`logbook.judge`, the verdicts kept in
    `policy/promises-cache.json`); `--all` every candidate; `--judge` runs the model on the unjudged
    ones first, at most `--limit`. `promises done <id>` appends the `task/v1` line (RFC 0016) that
    marks one done, so `--open` hides it. Nothing else is written to the chain."""
    since = a.since
    if since is not None:
        try:
            parse_day(since)
        except ValueError as e:
            print(f"promises: {e}", file=sys.stderr)
            sys.exit(2)
    lb = Logbook.find()
    if a.verb == "done":
        _promises_done(lb, a)
        return
    report = promises.extract(lb, since)
    judged: judge.Judged | None = None
    try:
        if a.judge:
            try:
                engine = judge.detect(a.model)
            except judge.EngineMissing as e:
                print(f"promises: {e}", file=sys.stderr)
                sys.exit(2)
            judged = judge.run(
                lb.root,
                report,
                engine,
                limit=a.limit,
                fetch_model=bool(a.fetch_model),
                progress=lambda text: print(text, file=sys.stderr),
            )
        report = promises.with_judgements(report, judge.read_cache(lb.root))
    except (judge.ModelMissing, judge.CacheError) as e:
        print(f"promises: {e}", file=sys.stderr)
        sys.exit(2)
    judged_only = not a.all
    found = [
        p
        for p in report.proposals
        if (not a.open or p.status == "open")
        and (not judged_only or (p.judgement is not None and p.judgement.shows()))
    ]
    if a.json:
        out = {
            "since": report.since,
            "open_only": bool(a.open),
            "judged_only": judged_only,
            "threshold": promises.THRESHOLD,
            "extractor": report.extractor,
            "judge": None if judged is None else judged.to_json(),
            "unjudged": len(report.unjudged),
            "proposals": [p.to_json() for p in found],
            "skipped": report.skipped,
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return
    zone = ZoneInfo(str(lb.meta["timezone"]))
    for text in promises.rows(
        report,
        found,
        lambda at: _clock(at, zone),
        open_only=bool(a.open),
        judged_only=judged_only,
        judge=None if judged is None else judged.to_json(),
    ):
        print(text)


def _promises_done(lb: Logbook, a: argparse.Namespace) -> None:
    report = promises.extract(lb)
    found = next((p for p in report.proposals if p.id == a.id), None)
    if found is None:
        print(f"promises: no proposal {a.id}; `logbook promises` lists them with their ids", file=sys.stderr)
        sys.exit(2)
    if found.closed_by:
        print(f"already done: \u201c{found.match.quote}\u201d (task line {found.closed_by})")
        return
    at = utc(now_utc())
    line = lb.append(
        at=at,
        source="manual",
        kind=promises.TASK,
        tier=promises.TASK_TIER,
        payload=promises.draft_done(found, at, report.extractor, a.note),
    )
    print(
        f"#{line['seq']} {line['at']}  done: \u201c{found.match.quote}\u201d"
        f"  ({found.day}, task/v1 line {line['id']})"
    )


def cmd_tasks(a: argparse.Namespace) -> None:
    """`tasks [--open] [--propose-done] [--json]`: the record's tasks (`task/v1`, RFC 0016), each as
    its latest standing snapshot (`logbook.taskdone`); `--propose-done` adds, for every open task,
    the mail, calendar entry or transaction of the fortnight after it that the rules read as evidence
    it was done, each with its line id, as proposals and never as facts. `tasks done <id> [--evidence
    LINE-ID]` appends the `task/v1` line that marks one done and nothing else."""
    lb = Logbook.find()
    if a.verb == "done":
        _tasks_done(lb, a)
        return
    report = taskdone.propose(lb) if a.propose_done else taskdone.read(lb)
    found = [t for t in report.tasks if not a.open or t.open]
    if a.json:
        out = {
            "open_only": bool(a.open),
            "propose_done": bool(a.propose_done),
            "window_days": report.window_days,
            "matcher": report.matcher or None,
            "tasks": [t.to_json() for t in found],
            "proposals": [p.to_json() for p in report.proposals],
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return
    zone = ZoneInfo(str(lb.meta["timezone"]))
    clock = lambda at: _clock(at, zone)  # noqa: E731
    texts = (
        taskdone.proposal_rows(report, clock)
        if a.propose_done
        else taskdone.rows(report, found, clock, open_only=bool(a.open))
    )
    for text in texts:
        print(text)


def _tasks_done(lb: Logbook, a: argparse.Namespace) -> None:
    report = taskdone.read(lb)
    found = next((t for t in report.tasks if t.id == a.id), None)
    if found is None:
        print(f"tasks: no task {a.id}; `logbook tasks` lists them with their ids", file=sys.stderr)
        sys.exit(2)
    if not found.open:
        print(f"already {found.status}: “{found.title}” (task line {found.line})")
        return
    if a.evidence is not None:
        with lb.index() as idx:
            line = idx.by_id(a.evidence)
        if line is None:
            print(
                f"tasks: no line {a.evidence} in the record; `--evidence` names a line by its id",
                file=sys.stderr,
            )
            sys.exit(2)
    at = utc(now_utc())
    line = lb.append(
        at=at,
        source="manual",
        kind=taskdone.TASK,
        tier=taskdone.TASK_TIER,
        payload=taskdone.draft_done(found, at, a.evidence),
    )
    tail = f", evidence {a.evidence}" if a.evidence else ""
    print(
        f"#{line['seq']} {line['at']}  done: “{found.title}”  ({found.day}, task/v1 line {line['id']}{tail})"
    )


def cmd_assets(a: argparse.Namespace) -> None:
    """`assets list`: one line per registered asset. `assets add`: register one (ADR 0018). The
    registry is <root>/assets.json, a setting of the record, outside the chain. `assets status`:
    per asset, its last known position (its latest standing location line, through the index,
    `logbook/asset_status.py`) and the age of that fix; a table in local time, or JSON."""
    lb = Logbook.find()
    try:
        if a.verb == "add":
            asset = assets.Asset(
                id=a.id, kind=a.kind, name=a.name, mmsi=a.mmsi, icao24=a.icao24, registration=a.registration
            )
            assets.add(lb.root, asset)
            print(_asset_row(asset))
            return
        registry = assets.read(lb.root)
        named = places.read(lb.root) if a.verb == "status" else []
    except (assets.AssetError, places.PlaceError) as e:
        print(f"assets: {e}", file=sys.stderr)
        sys.exit(2)
    if not registry:
        print(
            "no assets registered; register one with: logbook assets add <id> --kind "
            f"{'|'.join(assets.KINDS)} --name NAME [--mmsi N] [--icao24 HEX] [--registration REG]"
        )
        return
    if a.verb == "status":
        statuses = asset_status.read(lb, registry, named, datetime.now(UTC))
        if a.json:
            print(json.dumps({"assets": [s.to_json() for s in statuses]}, indent=2))
            return
        zone = ZoneInfo(str(lb.meta["timezone"]))
        for status in statuses:
            print(_status_row(status, zone))
        return
    for asset in registry:
        print(_asset_row(asset))


def _status_row(status: asset_status.Status, zone: ZoneInfo) -> str:
    """`<id> <kind> <name>  <local time>  <lat>,<lon>  near <place>, x km  <speed> m/s  <age> ago`,
    or `no fix yet`. The distance to the place is in metres under a kilometre."""
    head = f"{status.asset.id:<16} {status.asset.kind:<9} {status.asset.name:<24}"
    fix = status.fix
    if fix is None:
        return f"{head} no fix yet"
    when = datetime.fromisoformat(fix.at.replace("Z", "+00:00")).astimezone(zone).strftime("%Y-%m-%d %H:%M")
    parts = [when, f"{fix.lat:.4f},{fix.lon:.4f}"]
    if fix.near is not None:
        name, m = fix.near
        parts.append(f"near {name}, {m:.0f} m" if m < 1000 else f"near {name}, {m / 1000:.1f} km")
    if fix.speed_mps is not None:
        parts.append(f"{fix.speed_mps:.1f} m/s")
    parts.append(asset_status.age_text(fix.age_s))
    return f"{head} {'  '.join(parts)}"


def _places_import_takeout(lb: Logbook, a: argparse.Namespace) -> None:
    """`places import-takeout <path> [--write]`: Google Maps' saved and starred places (the Takeout
    `Maps (your places)/` and `Saved/` folders, or one file of them) proposed as entries of
    <root>/places.json — a setting of the record, outside the chain — and written only with
    `--write`, never changing an entry already there (`logbook/adapters/takeout/places.py`)."""
    try:
        proposals = takeout_places.read(Path(a.path).expanduser())
        report = takeout_places.merge(lb.root, proposals, write=a.write)
    except FileNotFoundError as e:
        print(f"places: no such file or directory: {e}", file=sys.stderr)
        sys.exit(2)
    for p in report.new:
        print(f"  {p.name:<40} {p.lat:.4f}, {p.lon:.4f}  {p.category}")
    for p in report.existing:
        print(f"  {p.name:<40} already in {places.PLACES_FILE}")
    for p in report.without_coordinates:
        print(f"  {p.name:<40} no coordinates in the export ({p.category})")
    summary = [f"{_plural(len(report.new), 'place')} proposed"]
    if report.existing:
        summary.append(f"{len(report.existing)} already in {places.PLACES_FILE}")
    if report.without_coordinates:
        summary.append(f"{len(report.without_coordinates)} without coordinates")
    if report.written:
        print(f"wrote {_plural(len(report.new), 'place')} to {lb.root / places.PLACES_FILE}")
    elif a.write:
        print(f"{'; '.join(summary)}; nothing new to write")
    else:
        print(f"{'; '.join(summary)}; nothing written (add --write)")


def _asset_row(asset: assets.Asset) -> str:
    ids = [f"{key} {value}" for key in ("mmsi", "icao24") if (value := getattr(asset, key)) is not None]
    if asset.registration is not None:
        ids.append(asset.registration)
    return f"{asset.id:<16} {asset.kind:<9} {asset.name}" + (f"  ({', '.join(ids)})" if ids else "")


def _state(path: Path, adapter: adapters.LiveAdapter, mark: str, seen: dict[str, Any]) -> dict[str, Any]:
    """The state to store: the watermark and, for an adapter with GROUP_MARKS, one per group (per
    tracked asset), each merged with the stored one and never moved backwards."""
    state: dict[str, Any] = {"since": mark}
    if getattr(adapter, "GROUP_MARKS", False):
        groups: dict[str, str] = dict(_read_state(path).get("groups") or {})
        for name, group_mark in seen["group_marks"].items():
            if name not in groups or group_mark > groups[name]:
                groups[name] = group_mark
        state["groups"] = dict(sorted(groups.items()))
    return state


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
    group: Callable[[dict[str, Any]], str] | None = None,
) -> Iterator[dict[str, Any]]:
    """Pass drafts through, noting count, earliest/latest `at`, the largest watermark, per-provenance
    counts and, given `group`, the count per group (per calendar, for `gcal`)."""
    for d in drafts:
        if group is not None:
            seen["groups"][group(d)] += 1
        seen["count"] += 1
        at = d["at"]
        if seen["first"] is None or at < seen["first"]:
            seen["first"] = at
        if seen["last"] is None or at > seen["last"]:
            seen["last"] = at
        mark = watermark(d)
        if mark is not None and (seen["watermark"] is None or mark > seen["watermark"]):
            seen["watermark"] = mark
        if mark is not None and group is not None:
            name = group(d)
            if name not in seen["group_marks"] or mark > seen["group_marks"][name]:
                seen["group_marks"][name] = mark
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


PASSWORD_ENV = "LOGBOOK_BACKUP_PASSWORD"
ENCRYPTED_NO_PASSWORD = (  # each printed after `<command>: ` (`import-backup`, `attach import-backup`)
    f"this backup is encrypted; put its password in {PASSWORD_ENV} (never a flag) and re-run,"
    " or in Finder untick “Encrypt local backup”, back up again, then re-run"
)
ENCRYPTED_NO_EXTRA = f"this backup is encrypted; reading it needs {ios_backup_crypto.EXTRA}"
WRONG_PASSWORD = f"{PASSWORD_ENV} does not unlock this backup's keybag (wrong password?); nothing was copied"
DIAL_PREFIX_HINT = (
    f"  {ios_contacts.DIAL_PREFIX_ENV} is not set: numbers saved without a country code stay as entered;"
    f" set it (for example {ios_contacts.DIAL_PREFIX_ENV}=41) to complete them"
)


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


def cmd_retract(a: argparse.Namespace) -> None:
    lb = Logbook.find()
    try:
        line = lb.retract(a.seq, a.reason)
    except ValueError as e:
        print(f"retract: {e}", file=sys.stderr)
        sys.exit(2)
    print(f"#{line['seq']} {line['at']}  retracted #{a.seq}: {a.reason}")


def cmd_repair(a: argparse.Namespace) -> None:
    """`repair health-units`: the migration for a record whose `apple-health` lines carry resting
    heart rate and HRV in the wrong unit (RFC 0014). Appends a corrected line and a retraction per
    wrong line; `--dry-run` prints the counts and writes nothing. Nothing is ever rewritten."""
    lb = Logbook.find()
    report = repair.health_units(lb, dry_run=a.dry_run)
    print(repair.describe_health_units(report))


def cmd_show(a: argparse.Namespace) -> None:
    """One local day (the owner's timezone), located through the index, read from the files,
    in time order (then chain order for the same instant). Senders, organizers and attendees
    are shown by the names the record's own resolution lines give them (RFC 0006), built once
    per call; `--raw` prints the refs as the sources gave them. Nothing is written."""
    lb = Logbook.find()
    if a.day in pages.PAGES:
        _show_page(lb, a)
        return
    if a.name is not None:
        print(f"show: {a.day!r} takes no name; a page is `show person|asset|place <name>`", file=sys.stderr)
        sys.exit(2)
    day = date.today().isoformat() if a.day in (None, "today") else a.day
    tz = ZoneInfo(lb.meta["timezone"])
    with lb.index() as idx:
        # A retraction is not an event of its own day; it shows as a marker where the line it hides was.
        rows = [line for line in idx.day(day) if line["kind"] != RETRACTION]
        retracted = retractions(idx.retractions())
        superseded = idx.superseded(flights.KIND)  # a flight another flight line replaced (RFC 0013 rule 4)
        names: dict[Ref, str] | None = None if a.raw else labels(lb, idx)
    if not rows:
        print(f"{day}: nothing logged")
        return
    rows.sort(key=lambda line: (line["at"], line["seq"]))
    print(day)
    hero = keepers.hero_row([*rows, *retracted.values()])  # RFC 0024 rule 4: the day's hero photos
    if hero:
        print(f"  {hero}")
    descriptions = describe.by_photo(line for line in rows if line["id"] not in retracted)
    for text in _day_rows(rows, retracted, tz, names, superseded, descriptions):
        print(text)
    note = lb.root / "notes" / day[:4] / f"{day}.md"
    if note.exists():
        print("  — note —\n" + "\n".join("  " + s for s in note.read_text(encoding="utf-8").splitlines()))


def cmd_day(a: argparse.Namespace) -> None:
    """`day [YYYY-MM-DD] [--json]`: the Day — the nights either side, the country, the timeline of
    stays, moves, stops and flights with what attached to each and who was there, the health
    line, the sources — read through the index from one reading of the day and the day before
    (`logbook.day`). Nothing is written, not even `policy/stays.json`."""
    lb = Logbook.find()
    day = date.today().isoformat() if a.day in (None, "today") else a.day
    try:
        data = day_reader.read(lb, day, _airports(a.airports))
    except (ValueError, stays.SettingsError) as e:
        print(f"day: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    for text in day_reader.rows(data):
        print(text)


def _today() -> str:
    """The local day, as one function so a test can pin it."""
    return date.today().isoformat()


def cmd_digest(a: argparse.Namespace) -> None:
    """`digest [YYYY-MM-DD] [--json | --markdown]`: the day in at most `digest.LIMIT` lines — its
    shape in three (where, with whom confirmed, what attached), the flights, the open promises due
    within the week, the usual sources with no line, tomorrow's timed calendar entries and one
    closing question the owner answers in a word (`logbook.digest`, composed from the readers).
    Nothing is written and nothing is sent: delivery is a later decision (ADR 0005)."""
    lb = Logbook.find()
    day = _today() if a.day in (None, "today") else a.day
    try:
        data = digest_reader.read(lb, day, _airports(a.airports))
    except (ValueError, stays.SettingsError) as e:
        print(f"digest: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    for text in digest_reader.markdown(data) if a.markdown else digest_reader.rows(data):
        print(text)


def cmd_questions(a: argparse.Namespace) -> None:
    """`questions list [--json]`: the question bank of the digest, `policy/questions.json`, one line
    per question — id, kind, weight, the facts it asks on, the text, `(disabled)` when it is.
    `questions add ID --text TEXT --kind KIND [--when FACT]... [--weight N] [--source TEXT] [--de TEXT]`:
    one more, refused when the id is taken or the shape is not the documented one. `questions
    disable ID`: kept in the file, never asked (RFC 0027). A record without the file gets the
    defaults first."""
    lb = Logbook.find()
    try:
        if a.verb == "add":
            q = questions.add(
                lb.root,
                questions.Question(
                    id=a.id,
                    text=a.text,
                    kind=a.kind,
                    when=tuple(a.when or ()),
                    weight=a.weight,
                    source=a.source or "",
                    text_de=a.de,
                ),
            )
            print(_question_row(q))
            return
        if a.verb == "disable":
            q = questions.disable(lb.root, a.id)
            print(f"{q.id}: disabled; it stays in {_under_home(questions.questions_path(lb.root))}")
            return
        bank = questions.read(lb.root)
    except policy.PolicyError as e:
        print(f"questions: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps({"questions": [q.to_json() for q in bank]}, indent=2, ensure_ascii=False))
        return
    for q in bank:
        print(_question_row(q))


def _question_row(q: questions.Question) -> str:
    weight = int(q.weight) if q.weight == int(q.weight) else q.weight
    row = f"  {q.id:<16} {q.kind:<10} {weight!s:<4} {' '.join(q.when):<32} {q.text}"
    return row if q.enabled else f"{row} (disabled)"


def cmd_days(a: argparse.Namespace) -> None:
    """`days [--from DAY] [--to DAY] [--json]`: a window of the record one line per day — the
    night, the kilometres moved, the flights, the stays with what attached, the people confirmed,
    the health triple, and a gap marker for a usual source with no line that day — streamed from
    readings of the window in chunks through the index (`logbook.days`), never one per day. The
    window defaults to the days the owner's track covers. `--json` is one object per line. Nothing
    is written."""
    lb = Logbook.find()
    try:
        window = _days_window(lb, a.since, a.until)
        if window is None:
            if not a.json:
                print("no days: the record has no lines")
            return
        for r in days_reader.read(lb, window[0], window[1], _airports(a.airports)):
            print(json.dumps(r, ensure_ascii=False) if a.json else days_reader.row(r))
    except (ValueError, stays.SettingsError) as e:
        print(f"days: {e}", file=sys.stderr)
        sys.exit(2)


def cmd_year(a: argparse.Namespace) -> None:
    """`year YYYY [--html PATH] [--json]`: the Year — days per country, nights, the trips, the
    flights, the places by nights, the people by days together, health and keepers by month, and
    twelve picks, one day a month, rendered with the day reader — composed from one reading of
    the year's days (`logbook.year`). `--html` writes one self-contained page. Nothing is written
    to the record."""
    lb = Logbook.find()
    try:
        if a.print:  # the paper edition (`logbook.print_page`), written where --html says
            out = _print_target(a, "year")
            data = print_page.read_year(lb, a.year, _airports(a.airports))
            out.write_bytes(print_page.html(data).encode("utf-8"))
            print(f"year {data['year']}: wrote {out}")
            return
        data = year_reader.read(lb, a.year, _airports(a.airports))
    except (ValueError, stays.SettingsError) as e:
        print(f"year: {e}", file=sys.stderr)
        sys.exit(2)
    if a.html:
        out = Path(a.html)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(year_reader.html(data).encode("utf-8"))
        print(f"year {data['year']}: wrote {out}")
        return
    if a.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    for text in year_reader.rows(data):
        print(text)


def cmd_trip(a: argparse.Namespace) -> None:
    """`trip <id-or-date> [--html PATH] [--json]`: one trip read back — the route as the stays
    slept at with their nights and the legs between them, the days from the leaving day to the
    return day one line each, the flights in and out, the people confirmed and proposed, the
    nights aboard, the keepers per day, the health of the span and the spend — from one reading
    of the days around it (`logbook.trip_page`). The trip is named by the id `trips` prints or by
    any day inside it. `--html` writes one self-contained page with an inline SVG map of the
    route. Nothing is written to the record."""
    lb = Logbook.find()
    try:
        if a.print:  # the paper edition (`logbook.print_page`), written where --html says
            out = _print_target(a, "trip")
            data = print_page.read_trip(lb, a.ref, _airports(a.airports))
            out.write_bytes(print_page.html(data).encode("utf-8"))
            print(f"trip {data['id']}: wrote {out}")
            return
        data = trip_page.read(lb, a.ref, _airports(a.airports))
    except (ValueError, stays.SettingsError) as e:
        print(f"trip: {e}", file=sys.stderr)
        sys.exit(2)
    if a.html:
        out = Path(a.html)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(trip_page.html(data).encode("utf-8"))
        print(f"trip {data['id']}: wrote {out}")
        return
    if a.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    for text in trip_page.rows(data):
        print(text)


def _print_target(a: argparse.Namespace, command: str) -> Path:
    """`--print` writes the paper edition of a Year or a Trip (one HTML document for A4 and US
    Letter) to `--html PATH`: the path, its folder made; exit 2 without `--html`, before anything
    is read."""
    if not a.html:
        print(
            f"{command}: --print writes the paper edition where --html PATH says; give both", file=sys.stderr
        )
        sys.exit(2)
    out = Path(a.html)
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def _days_window(lb: Logbook, since: str | None, until: str | None) -> tuple[str, str] | None:
    """`--from` and `--to`, each defaulting to the record's first or last day with a location line
    (else any line); None when a bound is missing and the record has no lines."""
    if since is not None and until is not None:
        return parse_day(since).isoformat(), parse_day(until).isoformat()
    whole = reading.record_days(lb, "location") or reading.record_days(lb)
    if whole is None:
        return None
    first = parse_day(since).isoformat() if since else whole[0]
    last = parse_day(until).isoformat() if until else whole[1]
    return first, last


def _show_page(lb: Logbook, a: argparse.Namespace) -> None:
    """`show person|asset|place <name> [--json]`: a page read from the whole record (the days the
    owner's track covers) through `pages`. Nothing is written."""
    if a.name is None:
        print(f"show {a.day}: say who or what, e.g. `logbook show {a.day} <name>`", file=sys.stderr)
        sys.exit(2)
    try:
        whole = reading.record_days(lb, "location") or reading.record_days(lb)
        if whole is None:
            raise pages.PageError("the record has no lines")
        read = reading.read(lb, whole[0], whole[1])
        page = {"person": pages.person, "asset": pages.asset, "place": pages.place}[a.day](read, a.name)
    except (pages.PageError, stays.SettingsError) as e:
        print(f"show {a.day}: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(page, indent=2, ensure_ascii=False))
        return
    for text in pages.rows(page):
        print(text)


def _day_rows(
    rows: list[Line],
    retracted: dict[str, Line],
    tz: ZoneInfo,
    names: Mapping[Ref, str] | None,
    superseded: Mapping[str, int] | None = None,
    descriptions: Mapping[str, Line] | None = None,
) -> Iterator[str]:
    """One printed row per line, except that a run of location points from one source, unbroken
    by any other row, collapses into one summary, one calendar entry that several sources
    carry (`events.fold`) is one row, `×N sources`, and a photo's description (`descriptions`,
    photo line id → the derived note, `describe.by_photo`) prints under the first keeper row for
    that photo instead of as a row of its own; with no keeper row standing it is a row. `names` is
    the label map; None is the `--raw` path: refs exactly as the sources gave them, no label, no
    fallback."""
    run: list[Line] = []
    rows, folded = events.fold(rows, flights.Airlines.load(), retracted)
    described = descriptions or {}
    under: dict[str, str] = {}  # description line id → the keeper line id it prints under
    for line in rows:
        pid = (
            keepers.photo_id_of(line)
            if line["kind"] == keepers.KIND and line["id"] not in retracted
            else None
        )
        if pid is not None and pid in described and str(described[pid]["id"]) not in under:
            under[str(described[pid]["id"])] = str(line["id"])
    for line in rows:
        retraction = retracted.get(line["id"])
        point = line["kind"] == "location" and retraction is None
        if run and not (point and (line["source"], _subject(line)) == (run[0]["source"], _subject(run[0]))):
            yield _run_row(run, tz)
            run = []
        if point:
            run.append(line)
        elif str(line["id"]) in under:
            continue  # shown under its keeper
        else:
            stands_for = folded.get(str(line["id"]))
            sources = f"×{len(stands_for.sources)} sources" if stands_for else None
            yield _line_row(line, retraction, tz, names, superseded, sources)
            pid = keepers.photo_id_of(line) if line["kind"] == keepers.KIND else None
            if (
                pid is not None
                and pid in described
                and under.get(str(described[pid]["id"])) == str(line["id"])
            ):
                yield f"{' ' * DESCRIPTION_INDENT}{describe.under_keeper(described[pid])}"
    if run:
        yield _run_row(run, tz)


DESCRIPTION_INDENT = 2 + 5 + 2 + 10 + 1 + 14 + 1  # the text column of a row: margin, clock, kind, source


def _line_row(
    line: Line,
    retraction: Line | None,
    tz: ZoneInfo,
    names: Mapping[Ref, str] | None,
    superseded: Mapping[str, int] | None = None,
    sources: str | None = None,
) -> str:
    """`sources` stands in for the line's own source on a calendar entry several sources carry
    (`events.fold`): `×2 sources`."""
    clock = _clock(line["at"], tz)
    if retraction is not None:
        return f"  {clock}  retracted #{line['seq']}: {retraction['payload'].get('reason', '')}"
    by = (superseded or {}).get(str(line["id"]))
    if by is not None:
        return f"  {clock}  {line['kind']:<10} {line['source']:<14} superseded by #{by}"
    text = _line_text(line, tz, names)
    return f"  {clock}  {line['kind']:<10} {sources or line['source']:<14} {text}"


def _line_text(line: Line, tz: ZoneInfo, names: Mapping[Ref, str] | None) -> str:
    """The text part of a line's row: the profile's own summary where the kind has one, else the
    payload's text, title, name or url, else every field as `key=value`."""
    p = line["payload"]
    if line["kind"] == "flight":
        text = _flight_text(p, tz)
    elif line["kind"] == "message":
        text = _message_text(p, names)
    elif line["kind"] == "event":
        text = _event_text(p, names)
    elif line["kind"] == "transcript":
        text = _transcript_text(p, names)
    elif line["kind"] == "call":
        text = _call_text(p, names)
    elif line["kind"] == "mail":
        text = _mail_text(p, names)
    elif line["kind"] == "note" and describe.is_description(line):
        text = describe.row_text(line)  # a photo's description, when its keeper is not shown
    elif line["kind"] == "note":
        text = _note_text(p, raw=names is None)
    elif line["kind"] == keepers.KIND:
        text = keepers.text(line)
    elif line["kind"] == story.KIND and p.get("schema") == story.SCHEMA:
        text = story.text(p, names)
    elif line["kind"] == "highlight" and p.get("schema") == "highlight/v1":
        text = _highlight_text(p)
    elif line["kind"] == "voice-memo" and p.get("schema") == "voice-memo/v1":
        text = _voice_memo_text(p)
    elif line["kind"] == "trip" and p.get("schema") == "trip/v1":
        text = _trip_text(p)
    elif line["kind"] == "crossing" and p.get("schema") == "crossing/v1":
        text = _crossing_text(p)
    elif line["kind"] == trip_bundle.RECEIVED:
        text = trip_bundle.text(line, lambda inner: _line_text(inner, tz, names))
    elif line["kind"] == screentime.KIND and p.get("schema") == screentime.SCHEMA:
        text = _app_use_text(p)
    else:
        text = (
            p.get("text")
            or p.get("title")
            or p.get("name")
            or p.get("url")
            or ", ".join(f"{k}={_value_text(v)}" for k, v in p.items() if k != "schema")
        )
    return str(text)


def cmd_search(a: argparse.Namespace) -> None:
    """`search TEXT [--since DAY] [--until DAY] [--kinds a,b] [--tier 1|2|3] [--limit N] [--json]`:
    full-text search through the index's FTS5 table (`logbook/search.py`): words and quoted
    phrases, literal (no stemming), case and accents aside; the hits ranked by bm25, grouped by
    local day, each as the row `show` prints with a snippet of the matching words under it. Tiers
    1 and 2 unless `--tier 3`. Nothing is written."""
    lb = Logbook.find()
    try:
        q = search.query(
            a.text,
            since=parse_day(a.since).isoformat() if a.since else None,
            until=parse_day(a.until).isoformat() if a.until else None,
            kinds=_csv(a.kinds),
            max_tier=a.tier,
            limit=a.limit,
        )
    except (search.QueryError, ValueError) as e:
        print(f"search: {e}", file=sys.stderr)
        sys.exit(2)
    tz = ZoneInfo(lb.meta["timezone"])
    try:
        with lb.index() as idx:
            result = search.search(idx, q)
            names = labels(lb, idx)
    except RuntimeError as e:  # no FTS5 in this SQLite
        print(f"search: {e}", file=sys.stderr)
        sys.exit(1)
    if a.json:
        print(
            json.dumps(result.to_json(lambda line: _line_text(line, tz, names)), indent=2, ensure_ascii=False)
        )
        return
    for text in search.rows(result, lambda line: _line_row(line, None, tz, names)):
        print(text)


def _value_text(value: object) -> str:
    """A payload value in the generic row: a string as itself, anything else as `_value_repr`."""
    return value if isinstance(value, str) else _value_repr(value)


def _value_repr(value: object) -> str:
    """Python's repr of a JSON value, except that a number is spelled as RFC 8785 writes it
    (`chain.number_text`): `100000000000000000000`, not the stored `1e+20`; `0.000001`; `120`. The
    row then depends on the value alone, never on the text the writer chose, so another
    implementation can print the same row from the same record (SPEC §3.2)."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, int | float):
        return number_text(value)
    if isinstance(value, list):
        return "[" + ", ".join(_value_repr(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{_value_repr(k)}: {_value_repr(v)}" for k, v in value.items()) + "}"
    return repr(value)


def _app_use_text(p: dict[str, Any]) -> str:
    """An app-use line as `Safari · 25 min · mac`: the app (its name, else its bundle id), the span's
    length, the device (its name, else its identifier). Never a title or a URL: the line has none."""
    extra: dict[str, Any] = p["extra"] if isinstance(p.get("extra"), dict) else {}
    app = p.get("title") or extra.get("bundle_id") or "an app"
    parts = [str(app)]
    seconds = extra.get("duration_s")
    if isinstance(seconds, int | float) and not isinstance(seconds, bool):
        parts.append(duration_text(int(seconds)))
    device = extra.get("device_name") or extra.get("device")
    if device:
        parts.append(str(device))
    return " · ".join(parts)


def duration_text(seconds: int) -> str:
    """`40 s`, `25 min`, `2 h 30 min`, `3 h`: whole units, the smaller one left out when zero."""
    if seconds < 60:
        return f"{seconds} s"
    hours, minutes = divmod(round(seconds / 60), 60)
    if not hours:
        return f"{minutes} min"
    return f"{hours} h {minutes:02d} min" if minutes else f"{hours} h"


def _crossing_text(p: dict[str, Any]) -> str:
    """A crossing/v1 line as `crossed to <destination>: N lines (tier 1: a, tier 2: b)`."""
    counts = p["counts"]
    by_tier = counts["by_tier"]
    tiers = ", ".join(f"tier {tier}: {by_tier[tier]}" for tier in ("1", "2", "3") if by_tier.get(tier))
    text = f"crossed to {p['destination']}: {_plural(counts['crossed'], 'line')}"
    if tiers:
        text += f" ({tiers})"
    return text


def _note_text(p: dict[str, Any], raw: bool) -> str:
    """A note's first line, with `… (+N lines)` when there are more (RFC 0010); `--raw` prints the
    whole text as written."""
    text = str(p.get("text") or "")
    if raw:
        return text
    lines = text.rstrip().splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return ""
    rest = len(lines) - 1
    return lines[0] if rest == 0 else f"{lines[0]} … (+{_plural(rest, 'line')})"


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


def _highlight_text(p: dict[str, Any]) -> str:
    """`“quote” — Title · note` for a highlight, `bookmark — Title @ location` for a bookmark
    (RFC 0022); the title is the library's, else the asset id."""
    book = p.get("title") or p.get("asset_id") or ""
    if p.get("type") == "bookmark":
        where = p.get("location")
        return f"bookmark — {book}" + (f" @ {where}" if where else "")
    text = f"\u201c{p.get('quote', '')}\u201d" + (f" — {book}" if book else "")
    if p.get("note"):
        text += f" · {p['note']}"
    return text


def _trip_text(p: dict[str, Any]) -> str:
    """`From → To, transit, sbb, 58.00 CHF, 1 change` (RFC 0020); a parking session names one place."""
    origin = _place_name(p.get("from"))
    destination = _place_name(p.get("to"))
    route = f"{origin} → {destination}" if destination and destination != origin else origin
    parts = [part for part in (route, str(p.get("mode") or ""), str(p.get("provider") or "")) if part]
    price = p.get("price")
    if isinstance(price, dict) and price.get("amount"):
        parts.append(f"{price['amount']} {price.get('currency', '')}".strip())
    if p.get("status") == "cancelled":
        parts.append("cancelled")
    extra = p.get("extra")
    if isinstance(extra, dict):
        transfers = extra.get("transfers")
        if isinstance(transfers, int) and not isinstance(transfers, bool) and transfers > 0:
            parts.append(_plural(transfers, "change"))
        if extra.get("observed") == "ticket":
            parts.append("ticket")
    return ", ".join(parts)


def _place_name(place: object) -> str:
    if isinstance(place, dict):
        return str(place.get("name") or place.get("address") or place.get("code") or "")
    return str(place) if isinstance(place, str) else ""


def _voice_memo_text(p: dict[str, Any]) -> str:
    """`Title (m:ss)`, then `audio missing` when the line has no media, `not stored` when it has
    the digest and no file (RFC 0023)."""
    text = str(p.get("title") or p.get("file_name") or "recording")
    duration = p.get("duration_s")
    if isinstance(duration, int | float) and not isinstance(duration, bool) and duration >= 0:
        minutes, seconds = divmod(round(duration), 60)
        text += f" ({minutes}:{seconds:02d})"
    media = p.get("media")
    if not isinstance(media, dict):
        text += ", audio missing"
    elif "path" not in media:
        text += ", not stored"
    return text


def _flight_text(p: dict[str, Any], tz: ZoneInfo | None = None) -> str:
    """`XY 561 OSL → ZRH, arrives 09:24, Airbus A320 LN-XYA, tracked, as pilot` (RFC 0013): the
    arrival clock in the owner's zone when `tz` is given; `cancelled` when it did not fly."""
    origin, destination = _airport_code(p.get("from")), _airport_code(p.get("to"))
    diverted = _airport_code(p.get("diverted_to"))
    route = f"{origin} → {destination}" + (f" (landed {diverted})" if diverted else "")
    parts = [f"{p.get('carrier', '')} {p.get('number', '')} {route}".strip()]
    if p.get("cancelled"):
        parts.append("cancelled")
    arrival = p.get("actual_arrival") or p.get("scheduled_arrival")
    if tz is not None and isinstance(arrival, str) and arrival:
        parts.append(f"arrives {_clock(arrival, tz)}")
    aircraft = p.get("aircraft")
    if isinstance(aircraft, dict):
        plane = " ".join(str(v) for v in (aircraft.get("type"), aircraft.get("registration")) if v)
        if plane:
            parts.append(plane)
    parts.append(str(p.get("evidence", "")))
    if p.get("role") == "pilot":
        parts.append("as pilot")
    return ", ".join(part for part in parts if part)


def _airport_code(ref: object) -> str:
    return str(ref.get("iata") or ref.get("icao") or "") if isinstance(ref, dict) else ""


def _call_text(p: dict[str, Any], names: Mapping[Ref, str] | None) -> str:
    """`← who, 7 min, cellular` for an answered incoming call, `→ who` outgoing, `missed` or `no
    answer` when it did not connect (RFC 0012). The counterparty is its label, else the ref as given;
    a withheld number is `withheld`. Raw (`names` None): the ref."""
    ref = p.get("counterparty")
    who = _name(ref, names) or _ref_value(ref) or "withheld"
    arrow = "→" if p.get("direction") == "outgoing" else "←"
    parts = [f"{arrow} {who}"]
    if not p.get("answered"):
        parts.append("no answer" if p.get("direction") == "outgoing" else "missed")
    else:
        seconds = p.get("duration_s")
        if isinstance(seconds, int) and seconds > 0:
            parts.append(f"{seconds // 60} min" if seconds >= 60 else f"{seconds} s")
    if isinstance(p.get("service"), str):
        parts.append(p["service"])
    return ", ".join(parts)


MAIL = "\u2709"  # ✉
ARROW = "\u2192"  # →
EM_DASH = "\u2014"  # —
BODY_INDENT = "    "


def _mail_text(p: dict[str, Any], names: Mapping[Ref, str] | None) -> str:
    """`✉ subject — from → to (n attachments)` (RFC 0015). A person is the label a resolution
    gives their address, else the name the header gave, else the address; the owner's own mail says
    `me`. Raw (`names` None): the addresses as given, and the body indented under the row — the
    only time `show` prints a body."""
    subject = str(p.get("subject") or "(no subject)")
    sender = p.get("from")
    own = p.get("direction") == "sent" and names is not None
    who = "me" if own else _mail_person(sender, names) or "?"
    recipients = [*(p.get("to") or []), *(p.get("cc") or [])]
    to = ", ".join(name for r in recipients if (name := _mail_person(r, names)))
    head = f"{MAIL} {subject} {EM_DASH} {who}"
    if to:
        head += f" {ARROW} {to}"
    attachments = p.get("attachments")
    if isinstance(attachments, list) and attachments:
        head += f" ({_plural(len(attachments), 'attachment')})"
    if names is None and isinstance(p.get("body"), str) and p["body"].strip():
        head += "\n" + "\n".join(BODY_INDENT + row for row in p["body"].rstrip("\n").split("\n"))
    return head


def _mail_person(person: object, names: Mapping[Ref, str] | None) -> str:
    """A mail/v1 `{email, name?}`: its resolution label, else its header name, else the address;
    raw is always the address."""
    if not isinstance(person, dict):
        return ""
    address = str(person.get("email") or "")
    if names is None:
        return address
    label = names.get(("email", address)) if address else None
    own = person.get("name")
    return label or (own if isinstance(own, str) and own else "") or address


def _message_text(p: dict[str, Any], names: Mapping[Ref, str] | None) -> str:
    """`who: text`, `who in group: text`, `me → other: text` (RFC 0008). The sender is its label,
    else the name the source showed for it (`sender.name`), else the direct chat's own name, else
    the ref as given. A group is its name, else its id: a chat is not an entity (RFC 0006), so its
    id is never looked up. Raw (`names` None): the ref."""
    chat = p.get("chat")
    if isinstance(chat, str):
        # SPEC §3.2: a string `chat` (the conformance sample's shape, before RFC 0008) is a direct chat's name
        chat = {"type": "direct", "name": chat}
    elif not isinstance(chat, dict):
        chat = {}
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


def _attendee(attendee: object, names: Mapping[Ref, str] | None) -> str:
    """An attendee's name, else its ref. A string attendee is the shape before RFC 0009 (SPEC §3.2
    reads it as an `email` ref); anything else is printed as it is, never a failure (SPEC §5)."""
    if isinstance(attendee, str):
        return _name({"kind": "email", "value": attendee}, names) or attendee
    if not isinstance(attendee, dict):
        return str(attendee)
    ref = attendee.get("ref")
    label = _name(ref, names)
    if label:
        return label
    own = attendee.get("name")
    if names is not None and isinstance(own, str) and own:
        return own
    return _ref_value(ref) or str(own or "")


def _run_row(run: list[Line], tz: ZoneInfo) -> str:
    """Time span, count, and the first and last named place of a run of location points. The span
    ends at the last point's `end` when it has one, else at its `at` (SPEC §3.2); one point is a row
    of its own and prints its `at`, as every other row does."""
    until = run[-1].get("end") if len(run) > 1 else None
    first = _clock(run[0]["at"], tz)
    last = _clock(until, tz) if isinstance(until, str) else _clock(run[-1]["at"], tz)
    span = first if first == last else f"{first}{EN_DASH}{last}"
    n = len(run)
    text = f"{n:,} point{'s' if n != 1 else ''}"
    places = [place for place in map(_place, run) if place]
    if places:
        text += f" · {places[0]}" if places[0] == places[-1] else f" · {places[0]} → {places[-1]}"
    subject = _subject(run[0])
    if subject is not None:  # an asset's own track (RFC 0001 `subject`, ADR 0018), never the owner's
        text = f"{subject}: {text}"
    return f"  {span}  {'location':<10} {run[0]['source']:<14} {text}"


def _subject(line: Line) -> str | None:
    """The asset whose position a location line is, or None for the owner's own."""
    subject = (line.get("payload") or {}).get("subject")
    return str(subject) if subject else None


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
    Numbers, kinds, sources and dates only; never what a line says. Nothing is written.

    `--health` is the one summary that reads lines: every `health` line (RFC 0014) through the
    index, one row per local day — sleep hours, steps, resting heart rate — and no device, no
    zone, no other field of any line."""
    lb = Logbook.find()
    if a.health:
        days = health_days(lb)
        if a.json:
            print(json.dumps({"days": days}, indent=2))
        elif not days:
            print("no health lines")
        else:
            for text in _health_rows(days):
                print(text)
        return
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


def health_days(lb: Logbook) -> list[dict[str, Any]]:
    """One row per local day of the record's health lines, through `health.summary` (the rules are
    there): every `health` line streamed through the index, the retractions beside them; the
    `lines` each row carries are dropped here, since `stats` prints numbers and never ids."""
    tz = str(lb.meta["timezone"])
    with lb.index() as idx:
        rows = health.summary([*idx.of_kind(health.KIND), *idx.retractions()], tz)
    return [{k: v for k, v in row.items() if k not in ("lines", "by")} for row in rows]


def _health_rows(days: list[dict[str, Any]]) -> Iterator[str]:
    yield f"  {'day':<10}  {'sleep':>5}  {'steps':>6}  {'resting':>7}"
    for d in days:
        sleep = "-" if d["sleep_h"] is None else f"{d['sleep_h']:.1f}"
        steps = "-" if d["steps"] is None else f"{d['steps']:,}"
        resting = "-" if d["resting_hr"] is None else str(d["resting_hr"])
        yield f"  {d['day']:<10}  {sleep:>5}  {steps:>6}  {resting:>7}"
    yield ""
    yield f"{_plural(len(days), 'day')}; sleep in hours, steps per day, resting heart rate in bpm"


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


def cmd_derive(a: argparse.Namespace) -> None:
    """`derive stays`: the location lines of a window read into stays, stops and moves, the owner's
    first and every asset's after (ADR 0018), the owner's run of stays and moves aboard an asset
    one stay `aboard <asset>` with the run inside it (`stays.fold`), and the overnight stay of each
    day, a night aboard with the asset's position; a table in local time, or JSON. The window
    runs from the first day's midnight to the night's end after the last day, so the night is
    inside it. Read through the index. The only thing written is `policy/stays.json` with the
    defaults, on the first run and never again; `--dry-run` writes nothing at all. Never a line:
    derived is disposable (ADR 0013)."""
    try:
        first, last = _derive_days(a)
    except ValueError as e:
        print(f"derive: {e}", file=sys.stderr)
        sys.exit(2)
    lb = Logbook.find()
    try:
        path = stays.settings_path(lb.root)
        if a.dry_run:
            note = f"settings from {path}" if path.exists() else f"default settings; {path} not written"
            print(f"dry run: {note}", file=sys.stderr)
        else:
            stays.write_default_settings(lb.root)
        read = reading.read(lb, first, last, _airports(a.airports))
    except stays.SettingsError as e:
        print(f"derive: {e}", file=sys.stderr)
        sys.exit(2)
    tz, days, settings, registered, derived = read.tz, read.days, read.settings, read.assets, read.derived
    start = datetime.combine(date.fromisoformat(first), datetime.min.time(), tzinfo=tz)
    _night_start, end = stays.night_window(last, tz, settings)
    subjects = derived.subjects
    if a.subject:
        wanted = None if a.subject == "owner" else a.subject
        if wanted is not None and wanted not in registered and wanted not in subjects:
            print(
                f"derive: no subject {a.subject!r}: assets.json does not name it and no location line"
                " in this window carries it",
                file=sys.stderr,
            )
            sys.exit(2)
        subjects = [wanted]
    segments = [
        *(derived.folded if None in subjects else []),
        *(s for s in derived.segments if s.subject is not None and s.subject in subjects),
    ]
    nights = read.nights if None in subjects else []
    if a.json:
        out = {
            "window": {"since": stays.instant_text(start), "until": stays.instant_text(end), "days": days},
            "settings": settings.to_json(),
            "subjects": subjects,
            "segments": [s.to_json(tz) for s in segments],
            "nights": [n.to_json(tz) for n in nights],
            "noise_points": derived.noise_points,
        }
        print(json.dumps(out, indent=2))
        return
    for text in _stays_rows(segments, nights, days, subjects, registered, tz):
        print(text)


def _derive_days(a: argparse.Namespace) -> tuple[str, str]:
    """The first and last local day of the window: `--day` (default today), or `--since`/`--until`."""
    if a.day and (a.since or a.until):
        raise ValueError("give --day, or --since and --until, not both")
    if a.day:
        day = date.today().isoformat() if a.day == "today" else parse_day(a.day).isoformat()
        return day, day
    if a.since or a.until:
        since = parse_day(a.since).isoformat() if a.since else None
        until = parse_day(a.until).isoformat() if a.until else since
        since = since or until
        assert since is not None and until is not None
        if until < since:
            raise ValueError(f"range runs backwards: {since} > {until}")
        return since, until
    today = date.today().isoformat()
    return today, today


def _stays_rows(
    segments: list[stays.Segment],
    nights: list[stays.Night],
    days: list[str],
    subjects: list[str | None],
    registered: Mapping[str, assets.Asset],
    tz: ZoneInfo,
) -> Iterator[str]:
    """One section per subject (the owner unheaded, an asset headed by its id and registry entry),
    each day's rows under its date, a stay aboard an asset with its run indented under it, the
    owner's night after each day's rows."""
    by_night = {n.day: n for n in nights}
    for subject in subjects:
        mine = [s for s in segments if s.subject == subject]
        if subject is not None:
            info = registered.get(subject)
            yield f"{EM_DASH} {subject}" + (f" ({info.name}, {info.kind})" if info else "")
        by_day: dict[str, list[stays.Segment]] = {}
        for s in mine:
            by_day.setdefault(s.start.astimezone(tz).date().isoformat(), []).append(s)
        for day in sorted(set(days) | set(by_day)):
            rows = by_day.get(day, [])
            if rows:
                yield day
                for s in rows:
                    yield _segment_row(s, tz)
                    for inner in s.inside:
                        yield _segment_row(inner, tz, inside=True)
            elif day in days:
                yield f"{day}: no location lines"
            if subject is None and day in by_night:
                yield _night_row(by_night[day], tz)


def _segment_row(s: stays.Segment, tz: ZoneInfo, inside: bool = False) -> str:
    """One row; an `inside` row is part of a stay aboard and does not repeat the asset's name."""
    parts: list[str]
    if s.kind == stays.MOVE:
        parts = [_distance_text(s.distance_m or 0), _duration_text(s.duration_s), s.mode or "gap"]
        if s.airports:
            parts.append(f"{s.airports[0]} → {s.airports[1]}")
    else:
        parts = [_where(s), _duration_text(s.duration_s)]
        if s.attached:
            parts.append(", ".join(_plural(n, kind) for kind, n in s.attached.items()))
        elif s.kind == stays.STOP:
            parts.append("nothing attached")
        if s.promoted:
            parts.append("promoted")
    if s.aboard and not s.inside and not inside:
        parts.append(f"aboard {s.aboard}")
    indent = "      " if inside else "  "
    return f"{indent}{_span(s.start, s.end, tz):<14} {s.kind:<5} {' · '.join(parts)}"


def _night_row(n: stays.Night, tz: ZoneInfo) -> str:
    """The night's stay, a night aboard with the asset's position (where it lay for the longest
    part of the night)."""
    if n.stay is None:
        return "  night          in transit"
    parts = [_where(n.stay)]
    if n.stay.aboard and n.position is not None:
        parts.append(f"{n.position[0]:.4f},{n.position[1]:.4f}")
    parts.append(_span(n.stay.start, n.stay.end, tz))
    if n.stay.aboard and not n.stay.inside:
        parts.append(f"aboard {n.stay.aboard}")
    if n.home:
        parts.append("home")
    return f"  night          {' · '.join(parts)}"


def _where(s: stays.Segment) -> str:
    """A stay's place: `aboard <asset>` for a stay aboard one, else its name, else its centre."""
    if s.inside:
        return f"aboard {s.aboard}"
    if s.place:
        return s.place
    assert s.lat is not None and s.lon is not None
    return f"{s.lat:.4f},{s.lon:.4f}"


def _span(start: datetime, end: datetime, tz: ZoneInfo) -> str:
    a, b = start.astimezone(tz), end.astimezone(tz)
    days = (b.date() - a.date()).days
    return f"{a:%H:%M}{EN_DASH}{b:%H:%M}" + (f"+{days}" if days else "")


def _duration_text(seconds: int) -> str:
    minutes = round(seconds / 60)
    if minutes < 1:
        return "< 1 min"
    hours, minutes = divmod(minutes, 60)
    if not hours:
        return f"{minutes} min"
    return f"{hours} h" if not minutes else f"{hours} h {minutes} min"


def _distance_text(metres: float) -> str:
    if metres < 1000:
        return f"{round(metres)} m"
    km = metres / 1000
    return f"{km:.1f} km" if km < 100 else f"{round(km)} km"


def cmd_places(a: argparse.Namespace) -> None:
    """`places list|add|name|propose`: the named places of the record (`places.json`). `list` and
    `add` touch the registry only. `name` adds a place and appends one note/v1 line, "named
    <lat>,<lon> as <name>", so the naming is in the record. `propose` is a reader: the owner's
    unnamed stays of the window, grouped and ranked by hours, with the nearest known place, any
    Google Timeline visit overlapping them and a suggested name; `--write` asks for each and
    names the ones accepted (a name, Enter for the suggestion, `s` to skip, `q` to stop).
    `--takeout` adds Google Maps' saved places as candidates (`takeout.maps.candidates`): one near a
    proposal is shown under it with its list and the day it was saved and becomes the suggested
    name; the rest are listed after the proposals for `places add`. `import-takeout` proposes
    entries from Google Maps' saved places in bulk (`_places_import_takeout`)."""
    lb = Logbook.find()
    try:
        if a.verb == "list":
            _places_list(lb)
        elif a.verb == "add":
            place = _place_from_args(a.name, a.lat, a.lon, a.radius, a.kind, a.tags)
            places.add(lb.root, place)
            print(f"added {_place_row(place)}")
        elif a.verb == "name":
            lat, lon = places.parse_stay_id(a.where)
            _name_place(lb, _place_from_args(a.name, lat, lon, a.radius, a.kind, a.tags))
        elif a.verb == "import-takeout":
            _places_import_takeout(lb, a)
        else:
            _places_propose(lb, a)
    except (places.PlaceError, stays.SettingsError, ValueError) as e:
        print(f"places: {e}", file=sys.stderr)
        sys.exit(2)


def _place_from_args(
    name: str, lat: float, lon: float, radius: float | None, kind: str | None, tags: str | None
) -> places.Place:
    return places.Place(
        name.strip(),
        float(lat),
        float(lon),
        places.DEFAULT_RADIUS_M if radius is None else float(radius),
        kind or places.OTHER,
        tuple(_csv(tags) or ()),
    ).check()


def _places_list(lb: Logbook) -> None:
    found = places.read(lb.root)
    if not found:
        print(f"no places ({places.path_of(lb.root)}); `logbook places add` or `logbook places propose`")
        return
    for place in found:
        print(_place_row(place))


def _place_row(place: places.Place) -> str:
    parts = [
        f"{place.name:<24}",
        f"{place.lat:.4f},{place.lon:.4f}",
        f"{_number_text(place.radius_m)} m",
        place.kind,
    ]
    if place.tags:
        parts.append(", ".join(place.tags))
    return "  ".join(parts)


def _number_text(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _name_place(lb: Logbook, place: places.Place) -> Line:
    """Add the place to places.json and put the naming in the record as one note/v1 line."""
    places.add(lb.root, place)
    text = places.naming_text(place.lat, place.lon, place.name)
    line = lb.append(
        at=now_utc(), source="manual", kind="note", tier=2, payload={"schema": "note/v1", "text": text}
    )
    print(f"{text} (#{line['seq']}); {_place_row(place)}")
    return line


def _places_propose(lb: Logbook, a: argparse.Namespace) -> None:
    """The owner's unnamed stays of the window, from the index alone (`reading.owner_track`): the
    window cut in the query, the points and the evidence its own columns, no month file opened."""
    first, last = _reader_days(lb, a.since, a.until)
    read = reading.owner_track(lb, first, last)
    unnamed = [
        places.Stay(s.id, s.start, s.end, s.lat, s.lon, s.aboard, s.first_line, s.last_line, s.points)
        for s in read.stays
        if s.place is None and s.lat is not None and s.lon is not None
    ]
    proposals = places.propose(unnamed, read.places, read.timeline_visits)
    if a.top is not None:
        proposals = proposals[: a.top]
    saved = _saved_candidates(a.takeout) if getattr(a, "takeout", None) else []
    nearby = {p.id: takeout_maps.near(saved, p.lat, p.lon, places.GROUP_M) for p in proposals}
    if saved:  # a saved place at the stay is the better name than a timeline's semantic type
        proposals = [
            dataclasses.replace(p, suggested=nearby[p.id][0].name) if nearby[p.id] else p for p in proposals
        ]
    at_a_proposal = {c.name.casefold() for found in nearby.values() for c in found}
    named = {place.name.casefold() for place in read.places}
    elsewhere = [
        c for c in saved if c.name.casefold() not in at_a_proposal and c.name.casefold() not in named
    ]
    if a.json:
        out: dict[str, Any] = {"window": reading.window_json(read), "proposals": []}
        for p in proposals:
            row = p.to_json()
            if saved:
                row["saved"] = [c.to_json() for c in nearby[p.id]]
            out["proposals"].append(row)
        if saved:
            out["saved_elsewhere"] = [c.to_json() for c in elsewhere]
        print(json.dumps(out, indent=2))
        return
    if not proposals:
        print(f"{first} {EN_DASH} {last}: no unnamed stays")
        _say_saved_elsewhere(elsewhere)
        return
    print(f"{first} {EN_DASH} {last}: {_plural(len(proposals), 'unnamed place')}, by hours")
    for n, proposal in enumerate(proposals, 1):
        for text in _proposal_rows(n, proposal):
            print(text)
        for c in nearby[proposal.id][:3]:
            print(f"      saved: {_saved_row(c)}")
        if a.write:
            accepted = _ask_name(proposal)
            if accepted is None:
                break
            if accepted:
                _name_place(lb, places.Place(accepted, proposal.lat, proposal.lon, read.settings.radius_m))
    _say_saved_elsewhere(elsewhere)


def _saved_candidates(path: str) -> list[takeout_maps.Candidate]:
    try:
        return takeout_maps.candidates(Path(path).expanduser())
    except FileNotFoundError as e:
        raise ValueError(f"--takeout: no such file or directory: {e}") from e


def _saved_row(c: takeout_maps.Candidate) -> str:
    parts = [c.name, f"{c.lat:.4f},{c.lon:.4f}", c.list]
    if c.saved_at:
        parts.append(f"saved {c.saved_at}")
    if c.metres is not None:
        parts.append(f"{_distance_text(c.metres)} away")
    return " · ".join(parts)


def _say_saved_elsewhere(elsewhere: list[takeout_maps.Candidate]) -> None:
    """The saved places at no unnamed stay and not yet named: for `places add`, by hand."""
    if not elsewhere:
        return
    print(f"{_plural(len(elsewhere), 'saved place')} near no unnamed stay; `logbook places add` names one:")
    for c in elsewhere:
        print(f"      {_saved_row(c)}")


def _proposal_rows(n: int, p: places.Proposal) -> Iterator[str]:
    parts = [f"{p.hours:6.1f} h", f"{p.lat:.4f},{p.lon:.4f}", _plural(len(p.stays), "stay")]
    if p.aboard:
        parts.append(f"aboard {p.aboard}")
    if p.nearest is not None:
        parts.append(f"{_distance_text(p.nearest[1])} from {p.nearest[0].name}")
    yield f"{n:3}. {' · '.join(parts)}   {p.id}"
    details = []
    for visit in p.timeline[:3]:
        details.append(f"timeline {visit.semantic_type or 'visit'} {visit.place_id or ''}".rstrip())
    if p.suggested:
        details.append(f"suggested: {p.suggested}")
    if details:
        yield f"      {' · '.join(details)}"


def _ask_name(p: places.Proposal) -> str | None:
    """The name the captain gives a proposal: Enter for the suggestion, `s` (or Enter with none)
    to skip (empty), `q` or the end of input to stop (None)."""
    hint = f" [{p.suggested}]" if p.suggested else ""
    try:
        answer = input(f"      name{hint}, s to skip, q to stop: ").strip()
    except EOFError:
        return None
    if answer.casefold() == "q":
        return None
    if answer.casefold() == "s" or (not answer and not p.suggested):
        return ""
    return answer or p.suggested


def _reader_days(lb: Logbook, since: str | None, until: str | None) -> tuple[str, str]:
    """A reader's window: `--since` and `--until` (local days, each defaulting to the first or
    last day with a location line); a record with none is today."""
    whole = reading.record_days(lb, "location")
    today = date.today().isoformat()
    first = parse_day(since).isoformat() if since else (whole[0] if whole else today)
    last = parse_day(until).isoformat() if until else (whole[1] if whole else today)
    if last < first:
        raise ValueError(f"range runs backwards: {first} > {last}")
    return first, last


def cmd_rollup(a: argparse.Namespace) -> None:
    """`rollup countries|flights|nights|places|people|health|listen [--year YYYY | --since DAY
    --until DAY] [--by month|week] [--json]`: the record summed up per year from one reading of the window,
    clipped to the days the owner's track covers (the first to the last day with a location line;
    for flights, with any line), so a day outside them is nothing, not a night in transit; or, for
    health, per month or ISO week from the health lines of the window, clipped to the days they
    cover, with no reading of the track; or, for listen, per year with the months inside it from
    the listen lines of the window (`listen_rollup`), the same way; or, for `people --drifting
    [--until DAY] [--window N] [--min-contacts N]`, the people whose contact frequency fell most
    between the last N days and the N before them (`drifting`). Every number carries the ids of
    its lines under --json. Nothing is written."""
    lb = Logbook.find()
    try:
        if a.by and a.what not in ("health", "attention"):
            raise ValueError("--by is for rollup health and rollup attention")
        if a.with_ and a.what != "places":
            raise ValueError("--with goes with `rollup places`: the place × person table")
        if a.drifting and a.what != "people":
            raise ValueError("--drifting goes with `rollup people`: whose contact frequency fell")
        if (a.window is not None or a.min_contacts is not None) and not a.drifting:
            raise ValueError("--window and --min-contacts go with --drifting")
        window = None if a.drifting else _rollup_days(lb, a)
        if a.drifting:
            data = _drifting(lb, a)
        elif window is None:
            data = listen_rollup.empty() if a.what == "listen" else rollup.empty(a.what, a.by)
        elif a.what == "health":
            tz = str(lb.meta["timezone"])
            data = rollup.health(_health_window(lb, *window), tz, *window, a.by or "month")
        elif a.what == "listen":
            data = listen_rollup.listen(_listen_window(lb, *window), str(lb.meta["timezone"]), *window)
        elif a.what == "attention":
            tz = str(lb.meta["timezone"])
            data = rollup.attention(
                _kind_window(lb, screentime.KIND, *window), tz, *window, a.by, apps.read(lb.root)
            )
        else:
            read = reading.read(lb, window[0], window[1], _airports(a.airports))
            data = rollup.places(read, with_table=a.with_) if a.what == "places" else ROLLUPS[a.what](read)
    except (ValueError, stays.SettingsError) as e:
        print(f"rollup: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(data, indent=2))
        return
    text_rows = drifting.rows if a.drifting else listen_rollup.rows if a.what == "listen" else rollup.rows
    for text in text_rows(data):
        print(text)


def _drifting(lb: Logbook, a: argparse.Namespace) -> dict[str, Any]:
    """`rollup people --drifting`: the recent window is `--window` days (365) ending on `--until`,
    the record's last day with a line of any kind by default; the earlier window the same number of
    days before it. `--year` and `--since` do not apply: the window is a length, not a range."""
    if a.year or a.since:
        raise ValueError("--drifting takes --until and --window, not --year or --since")
    whole = reading.record_days(lb)
    if whole is None:
        return drifting.empty()
    until = parse_day(a.until).isoformat() if a.until else whole[1]
    return drifting.read(
        lb,
        until,
        drifting.DEFAULT_WINDOW if a.window is None else a.window,
        drifting.DEFAULT_MIN_CONTACTS if a.min_contacts is None else a.min_contacts,
        _airports(a.airports),
        record_first=whole[0],
    )


def _listen_window(lb: Logbook, first: str, last: str) -> list[Line]:
    """The listen lines whose local day is in `[first, last]`, through the index, with every
    retraction line."""
    with lb.index() as idx:
        return [*idx.by_kind(listen_rollup.KIND, first, last), *idx.retractions()]


def _health_window(lb: Logbook, first: str, last: str) -> list[Line]:
    """The health lines of `[first, last]` and of the day before (the night that ends on the first
    day starts then), through the index, with every retraction line."""
    before = (parse_day(first) - timedelta(days=1)).isoformat()
    with lb.index() as idx:
        return [*idx.by_kind(health.KIND, before, last), *idx.retractions()]


def _kind_window(lb: Logbook, kind: str, first: str, last: str) -> list[Line]:
    """The lines of one kind whose local day is in `[first, last]`, through the index, with every
    retraction line (a retraction applies wherever its line is)."""
    with lb.index() as idx:
        return [*idx.by_kind(kind, first, last), *idx.retractions()]


ROLLUPS: dict[str, Callable[[reading.Reading], dict[str, Any]]] = {
    "countries": rollup.countries,
    "flights": rollup.flights,
    "nights": rollup.nights,
    "places": rollup.places,
    "people": rollup.people,
    "money": ledger.rollup,
}


def _rollup_days(lb: Logbook, a: argparse.Namespace) -> tuple[str, str] | None:
    """The window of a rollup: `--year`, or `--since`/`--until`, each clipped to the record's
    first and last day; None for an empty record or a window the record has no day in."""
    if a.year and (a.since or a.until):
        raise ValueError("give --year, or --since and --until, not both")
    what = str(getattr(a, "what", None) or "")
    kinds = {
        "flights": None,
        "health": health.KIND,
        "listen": listen_rollup.KIND,
        "attention": screentime.KIND,
        "money": ledger.KIND,
    }
    whole = reading.record_days(lb, kinds.get(what, "location"))
    if whole is None:
        return None
    if a.year:
        if not re.fullmatch(r"\d{4}", a.year):
            raise ValueError(f"not a year (YYYY): {a.year!r}")
        since, until = f"{a.year}-01-01", f"{a.year}-12-31"
    else:
        since = parse_day(a.since).isoformat() if a.since else whole[0]
        until = parse_day(a.until).isoformat() if a.until else whole[1]
    first, last = max(since, whole[0]), min(until, whole[1])
    if last < first:
        return None if a.year or since > whole[1] or until < whole[0] else _raise_backwards(since, until)
    return first, last


def _raise_backwards(since: str, until: str) -> tuple[str, str]:
    raise ValueError(f"range runs backwards: {since} > {until}")


def cmd_people(a: argparse.Namespace) -> None:
    """`people [--year YYYY] [--json]`: every person the record's resolution lines name and has
    heard from in the window, never the owner — the channels, first and last contact, days
    together, nights under one roof, places shared, birthday and last real contact — read through
    the index (`logbook.people`). The window is the whole record, or one year, clipped to the days
    the record has a line on. Nothing is written."""
    lb = Logbook.find()
    if a.verb == "merge":
        _people_merge(lb, a)
        return
    try:
        window = _people_window(lb, a.year)
        if window is None:
            print(json.dumps(people.empty(), indent=2) if a.json else f"no people: {_no_days(a.year)}")
            return
        report = people.read(lb, *window)
    except (ValueError, stays.SettingsError, policy.PolicyError) as e:
        print(f"people: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(report.to_json(), indent=2, ensure_ascii=False))
        return
    for text in people.rows(report):
        print(text)


def _people_merge(lb: Logbook, a: argparse.Namespace) -> None:
    """`people merge [--propose | --apply ID... | --export-review FILE | --apply-review FILE] [--json]`:
    the same person named twice or more by the resolution lines (`logbook.people_merge`), proposed
    with the evidence and never merged on its own. `--apply` and `--apply-review` append the alias
    lines (RFC 0006) through `Logbook.append`; every id or row is checked before the first one."""
    try:
        report = people_merge.read(lb)
        if a.apply:
            _say_merged(people_merge.apply(lb, report, a.apply), a.json)
            return
        if a.apply_review:
            rows = people_merge.read_review(Path(a.apply_review))
            applied, done = people_merge.apply_review(lb, report, rows)
            for row in done:
                print(f"row {row.line}: already merged, skipped")
            if not applied and not done:
                print(f"nothing marked in {a.apply_review}: write `yes` in `apply` on the rows to merge")
            _say_merged(applied, a.json)
            return
        if a.export_review:
            n = people_merge.export_review(report, Path(a.export_review))
            proposals = _plural(len(report.proposals), "proposal")
            count = _plural(n, "row")
            print(f"wrote {count} for {proposals} to {a.export_review}; mark `apply` and run --apply-review")
            return
    except (people_merge.MergeError, ValueError, stays.SettingsError, policy.PolicyError) as e:
        print(f"people merge: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(report.to_json(), indent=2, ensure_ascii=False))
        return
    for text in people_merge.rows(report):
        print(text)


def _say_merged(applied: list[people_merge.Applied], as_json: bool) -> None:
    if as_json:
        print(json.dumps({"applied": [a.to_json() for a in applied]}, indent=2, ensure_ascii=False))
        return
    for text in people_merge.applied_rows(applied):
        print(text)


def cmd_person(a: argparse.Namespace) -> None:
    """`person <name-or-ref> [--year YYYY] [--json]`: one person's page — the same numbers as
    `people`, then the shared days, most recent first. The name is a label, a unique first or last
    name, an entity id, an email address, a phone number or `kind:value`. Nothing is written."""
    lb = Logbook.find()
    try:
        window = _people_window(lb, a.year)
        if window is None:
            raise ValueError(_no_days(a.year))
        report = people.read(lb, *window)
        who = people.find(a.name, report)
    except (ValueError, stays.SettingsError, policy.PolicyError) as e:
        print(f"person: {e}", file=sys.stderr)
        sys.exit(2)
    data = people.page(report, who)
    if a.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    for text in people.person_rows(data):
        print(text)


def _people_window(lb: Logbook, year: str | None) -> tuple[str, str] | None:
    """The whole record (the first to the last local day with a line of any kind), or `--year`
    clipped to it; None for an empty record or a year the record has no day in."""
    whole = reading.record_days(lb)
    if whole is None:
        return None
    if year is None:
        return whole
    if not re.fullmatch(r"\d{4}", year):
        raise ValueError(f"not a year (YYYY): {year!r}")
    first, last = max(f"{year}-01-01", whole[0]), min(f"{year}-12-31", whole[1])
    return None if last < first else (first, last)


def _no_days(year: str | None) -> str:
    return "the record has no lines" if year is None else f"the record has no days in {year}"


def cmd_trips(a: argparse.Namespace) -> None:
    """`trips [--year YYYY | --since DAY --until DAY] [--json]`: runs of consecutive days whose
    overnight stay is outside every home region, derived from one reading of the window and
    never written (ADR 0019)."""
    lb = Logbook.find()
    try:
        window = _rollup_days(lb, a)
        if window is None:
            print(
                json.dumps({"window": None, "trips": []}, indent=2)
                if a.json
                else "no trips: the record has no days"
            )
            return
        read = reading.read(lb, window[0], window[1], _airports(a.airports))
    except (ValueError, stays.SettingsError) as e:
        print(f"trips: {e}", file=sys.stderr)
        sys.exit(2)
    found, warning = trips.trips(read)
    if a.json:
        out: dict[str, Any] = {"window": reading.window_json(read), "trips": [t.to_json() for t in found]}
        if warning:
            out["warning"] = warning
        print(json.dumps(out, indent=2))
        return
    for text in trips.rows(read, found, warning):
        print(text)


def cmd_ledger(a: argparse.Namespace) -> None:
    """`ledger [--month YYYY-MM | --trip ID] [--json]`: the transaction lines (tier 3) of the window
    in context — each at the stay the owner was in, in its trip, per day, a shared expense's shares
    per person — from one reading of the window through the index (`logbook.ledger`). The window
    is the days the record has a transaction on, one month of them, or one trip's days (its first
    day to the return day). Amounts in the line's currency, nothing converted; nothing is written."""
    lb = Logbook.find()
    try:
        if a.month and a.trip:
            raise ValueError("give --month, or --trip, not both")
        window = _ledger_days(lb, a.month, a.trip)
        if window is None:
            data = ledger.empty()
        else:
            read = reading.read(lb, window[0], window[1], _airports(a.airports))
            book = ledger.ledger(read)
            if a.trip and a.trip not in {t.id for t in book.trips}:
                raise ValueError(f"no trip {a.trip}: no run of nights away from home has that id")
            data = book.to_json()
    except (ValueError, stays.SettingsError) as e:
        print(f"ledger: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    for text in ledger.rows(data):
        print(text)


def _ledger_days(lb: Logbook, month: str | None, trip: str | None) -> tuple[str, str] | None:
    """The ledger's window: the days the record has a transaction on; `--month` clipped to them;
    `--trip` the trip's days, its first to the return day (`trip:<start>:<end>`). None when the
    record has no transaction in it."""
    whole = reading.record_days(lb, ledger.KIND)
    if trip:
        found = re.fullmatch(r"trip:(\d{4}-\d{2}-\d{2}):(\d{4}-\d{2}-\d{2})", trip)
        if not found:
            raise ValueError(
                f"not a trip id (trip:YYYY-MM-DD:YYYY-MM-DD, as `trips --json` prints it): {trip!r}"
            )
        start, end = parse_day(found.group(1)), parse_day(found.group(2))
        if end < start:
            raise ValueError(f"range runs backwards: {start} > {end}")
        return start.isoformat(), (end + timedelta(days=1)).isoformat()
    if whole is None:
        return None
    if month:
        if not re.fullmatch(r"\d{4}-\d{2}", month) or not 1 <= int(month[5:]) <= 12:
            raise ValueError(f"not a month (YYYY-MM): {month!r}")
        first_day = date.fromisoformat(f"{month}-01")
        last_day = (first_day.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        first, last = max(first_day.isoformat(), whole[0]), min(last_day.isoformat(), whole[1])
        return None if last < first else (first, last)
    return whole


def cmd_serve(a: argparse.Namespace) -> None:
    """`serve [--port N]`: the record read in a browser, from this machine only (`logbook/serve.py`).
    Server-rendered pages from the index and the readers — the Day as a timeline, a window one row
    per day, the trips of a year, the places, the assets and their last fix, where each source went
    quiet — at http://127.0.0.1:8765/. Any other host is refused before a socket is opened; no page
    references a URL outside itself; nothing is written."""
    if a.host != serve.HOST:
        print(
            f"serve: binds {serve.HOST} only, never {a.host!r}: the record is read from this machine",
            file=sys.stderr,
        )
        sys.exit(2)
    lb = Logbook.find()
    try:
        serve.serve(lb, host=a.host, port=a.port, airports=_airports(a.airports))
    except serve.HostError as e:
        print(f"serve: {e}", file=sys.stderr)
        sys.exit(2)
    except OSError as e:
        print(f"serve: cannot listen on {a.host}:{a.port}: {e}", file=sys.stderr)
        sys.exit(2)


def cmd_mcp(a: argparse.Namespace) -> None:
    """`mcp [--root DIR] [--allow-tier-3]`: serve the record to an MCP host over this process's
    stdin and stdout, nothing else open, until the host closes them (`logbook.mcp_server`; the
    tools and the ceiling are documented in `docs/mcp.md`). `--inspect` prints the tool table and
    one sample request and needs neither a record nor the `mcp` extra."""
    if a.inspect:
        print(mcp_server.inspect_text())
        return
    lb = Logbook(Path(a.root).expanduser()) if a.root else Logbook.find()
    if not lb.meta_path.exists():
        print(f"mcp: {lb.root} is not a logbook (no logbook.json)", file=sys.stderr)
        sys.exit(2)
    try:
        mcp_server.serve(lb.root, allow_tier_3=a.allow_tier_3)
    except ImportError as e:
        print(f"mcp: {e}", file=sys.stderr)
        sys.exit(2)


def cmd_demo(a: argparse.Namespace) -> None:
    """`demo [--days N | --years N] [--seed S] --out DIR`: a complete synthetic record of the Oslo
    persona, invented in `logbook/demo.py` (a month) or `logbook/demo_life.py` (a life), written
    to a new folder; the same days or years and seed give the same head. Nothing in it is real
    and nothing outside the folder is read."""
    root = Path(a.out).expanduser()
    if a.years is not None and a.days is not None:
        print("demo: give --days or --years, not both", file=sys.stderr)
        sys.exit(2)
    if a.years is not None and a.years < 1:
        print("demo: --years must be at least 1", file=sys.stderr)
        sys.exit(2)
    if a.days is not None and a.days < 1:
        print("demo: --days must be at least 1", file=sys.stderr)
        sys.exit(2)
    try:
        lb = demo.generate(root, days=a.days, seed=a.seed, years=a.years)
    except (FileExistsError, CodeCheckoutError, OSError) as e:
        print(f"demo: {e}", file=sys.stderr)
        sys.exit(2)
    meta = lb.meta
    if a.years is not None:
        first, last = demo_life.birthday(a.years), demo_life.TODAY
        span = _plural(a.years, "year")
        show = last if a.years < demo_life.FULL_MONTH_FROM else first.replace(year=last.year, month=6, day=17)
    else:
        days = 30 if a.days is None else a.days
        first, last = demo.START, demo.START + timedelta(days=days - 1)
        span = _plural(days, "day")
        show = min(last, first + timedelta(days=7))
    where = _under_home(lb.root)
    print(
        f"demo record: {span}, {first} to {last}, seed {a.seed}; nothing in it is real\n"
        f"wrote {meta['seq']:,} lines to {where}, head {str(meta['head'])[:12]}…\n"
        f"  export LOGBOOK_HOME={where}\n"
        f"  logbook show {show}"
    )


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
    seq, head, errors = lb.verify(warnings, progress=_file_progress(len(lb.files())) if a.progress else None)
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


def cmd_setup(a: argparse.Namespace) -> None:
    """The guided first run (`logbook/setup.py`): one question at a time, each with its default and why
    it is asked; resumable through `state/setup.json`; `--yes` takes every default and asks nothing."""
    status = setup.run(a, os.environ)
    if status:
        sys.exit(status)


def cmd_doctor(a: argparse.Namespace) -> None:
    """One line per check of the record and this machine (`logbook/doctor.py`); exit 1 when one fails.
    Reads only: a missing settings file is reported, never written."""
    try:
        lb: Logbook | None = Logbook.find()
    except FileNotFoundError:
        lb = None
    status = doctor_checks.report(doctor_checks.run(lb, os.environ), sys.stdout)
    if status:
        sys.exit(status)


def cmd_backup(a: argparse.Namespace) -> None:
    """`backup DEST [--keep N] [--verify]`: one snapshot of the record under `DEST/<owner_id>/`, hard
    links to the previous one for what did not change, verified there, its head the live head.
    `backup list DEST`: every snapshot with its lines, head and size. `backup restore SNAPSHOT
    TARGET`: a copy back, verified (`logbook/backup.py`, docs/backup.md). A refusal exits 2; a copy
    that does not verify is removed and exits 1."""
    verb, paths = (a.paths[0], a.paths[1:]) if a.paths[0] in ("list", "restore") else (None, a.paths)
    usage = {None: "backup DEST", "list": "backup list DEST", "restore": "backup restore SNAPSHOT TARGET"}
    if len(paths) != (2 if verb == "restore" else 1):
        print(f"backup: usage: logbook {usage[verb]}", file=sys.stderr)
        sys.exit(2)
    if verb is not None and (a.keep is not None or a.verify):
        print(f"backup {verb}: --keep and --verify belong to `logbook backup DEST`", file=sys.stderr)
        sys.exit(2)
    if a.keep is not None and a.keep < 1:
        print("backup: --keep takes a number of snapshots to keep, 1 or more", file=sys.stderr)
        sys.exit(2)
    try:
        if verb == "list":
            _backup_list(Path(paths[0]).expanduser())
        elif verb == "restore":
            _backup_restore(Path(paths[0]).expanduser(), Path(paths[1]).expanduser())
        else:
            _backup_snapshot(Logbook.find(), Path(paths[0]).expanduser(), a)
    except backup.Invalid as e:
        print(f"backup: {e}; nothing kept", file=sys.stderr)
        sys.exit(1)
    except backup.Refused as e:
        print(f"backup: {e}", file=sys.stderr)
        sys.exit(2)


def _backup_snapshot(lb: Logbook, dest: Path, a: argparse.Namespace) -> None:
    result = backup.snapshot(lb, dest, verify_attachments=a.verify)
    print(f"backup: {result.path.name} → {result.path}")
    for text in backup.describe(result):
        print(text)
    if result.attachments_checked is not None:
        print(f"  {_plural(result.attachments_checked, 'attachment')} checked, every one matches its name")
    if a.keep is not None:
        removed = backup.prune(result.path.parent, a.keep, result.path)
        kept = len(backup.snapshots(result.path.parent))
        pruned = ", ".join(p.name for p in removed) if removed else "nothing"
        print(f"  kept {_plural(kept, 'snapshot')}; pruned {pruned}")


def _backup_list(dest: Path) -> None:
    shown = 0
    for owner, entries in backup.listing(dest):
        print(owner)
        for e in entries:
            size = f"{backup.human(e.bytes)} ({backup.human(e.new_bytes)} new)"
            if e.error is not None:
                print(f"  {e.path.name}  not a readable snapshot: {e.error}  {size}")
            else:
                print(f"  {e.path.name}  {_plural(e.seq or 0, 'line')}  head {(e.head or '')[:12]}…  {size}")
            shown += 1
    if not shown:
        print(f"no snapshots under {dest}")


def _backup_restore(source: Path, target: Path) -> None:
    result = backup.restore(source, target)
    print(f"restored {source.name} → {result.path}")
    for text in backup.describe(result):
        print(text)
    print(f"  point LOGBOOK_HOME at {result.path}; the next reader builds its index")


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
    if a.path == vault.DESTINATION:
        _export_vault(lb, a)
        return
    if a.path == trip_bundle.COMMAND:
        _export_trip_bundle(lb, a)
        return
    if a.day or a.days:
        _export_days(lb, a)
        return
    if not a.path:
        print("export: give a .jsonl path, or --day YYYY-MM-DD, or --days FROM TO", file=sys.stderr)
        sys.exit(2)
    out = Path(a.path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    n = _write_lines(lb.lines(), out)
    if n is None:  # a month file not in seq order (not one this code wrote): the sorted read
        n = _write_lines(lb._lines_by_seq(), out)
    print(f"exported {n} lines to {out} — verify with: logbook verify")


def _write_lines(lines: Iterator[Line], out: Path) -> int | None:
    """Stream `lines` to `out` as JSON lines, one in memory at a time; the count, or None when
    the files turned out to need the sorted read (the caller starts the file over)."""
    n = 0
    with out.open("w", encoding="utf-8") as fh:
        try:
            for line in lines:
                fh.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
                n += 1
        except UnsortedFile:
            return None
    return n


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


def _export_vault(lb: Logbook, a: argparse.Namespace) -> None:
    """vault FOLDER [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--tier 1|1,2]: the record as a folder
    of Markdown pages with wikilinks (`logbook/vault.py`), tier-gated under the `vault` ceiling in
    policy/crossing.json (ADR 0016; tier 1 when the file does not name it), recorded as a crossing/v1
    line (RFC 0011). Only the files whose content changed are rewritten."""
    generated_at = now_utc()
    try:
        if not a.target:
            raise vault.VaultError("export vault needs a folder: logbook export vault <folder>")
        req = vault.request(lb, a.since, a.until, vault.parse_tiers("1" if a.tier is None else a.tier))
    except vault.VaultError as e:
        print(f"export vault: {e}", file=sys.stderr)
        sys.exit(2)
    folder = Path(a.target).expanduser()
    if req is None:
        print("vault: the record has no day; nothing written, nothing appended")
        return
    try:
        built = vault.build(lb, req)
        result = vault.export(lb, req, built, folder, generated_at)
    except (vault.VaultError, stays.SettingsError, OSError) as e:
        print(f"export vault: {e}", file=sys.stderr)
        sys.exit(2)
    tiers = ",".join(map(str, req.tiers))
    window = f"{req.since} {EN_DASH} {req.until}"
    print(f"vault: {_plural(built.days, 'day')} {window}, tier {tiers} {ARROW} {folder}")
    pages = ", ".join(_plural(n, *vault.PAGE_NOUNS[kind]) for kind, n in built.pages.items())
    print(f"  pages: {pages}; {result.written} written, {result.unchanged} unchanged")
    if built.held_back:
        by_kind = ", ".join(f"{kind} {n}" for kind, n in built.held_by_kind.items())
        print(f"  held back: {_plural(built.held_back, 'line')} above tier {max(req.tiers)} ({by_kind})")
    seq, sha = result.line["seq"], result.sha256[:12]
    print(f"  recorded as #{seq} {crossing.LINE_SCHEMA}, vault sha256 {sha}…")


def _export_trip_bundle(lb: Logbook, a: argparse.Namespace) -> None:
    """trip-bundle <trip-id-or-day> --to DEST [--tier 1|1,2|1,2,3] [--attachments] [--out DIR]
    [--dry-run]: one crossing package cut to the trip (RFC 0029, profile trip-bundle/v1) under the
    destination's ceiling in policy/crossing.json, recorded as a crossing/v1 line naming the trip."""
    generated_at = now_utc()
    try:
        if not a.target or not a.to:
            raise crossing.CrossingError(
                "export trip-bundle needs the trip (an id or a day) and --to <member>"
            )
        prepared = trip_bundle.prepare(
            lb,
            a.target,
            a.to,
            crossing.parse_tiers("1" if a.tier is None else a.tier),
            _airports(a.airports),
            attachments=bool(a.attachments),
        )
    except (crossing.CrossingError, ValueError, stays.SettingsError) as e:
        print(f"export trip-bundle: {e}", file=sys.stderr)
        sys.exit(2)
    req, sel, trip = prepared.request, prepared.selection, prepared.trip
    out = Path(a.out).expanduser() if a.out else trip_bundle.default_out(lb, req.destination, generated_at)
    tiers = ",".join(map(str, req.tiers))
    span = f"{trip.start} {EN_DASH} {trip.end}"
    if a.dry_run:
        print(f"dry run: {req.destination}, {trip.id} {span}, tiers {tiers}; nothing written")
        for text in _trip_bundle_rows(prepared):
            print(text)
        return
    try:
        result = trip_bundle.export(lb, prepared, out, generated_at)
    except (crossing.CrossingError, OSError) as e:
        print(f"export trip-bundle: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"{req.destination}: {trip.id} {span}, tiers {tiers} {ARROW} {out}")
    for text in _trip_bundle_rows(prepared):
        print(text)
    if req.tier3:
        _tier3_warning(req, sel)
    seq, digest = result.line["seq"], result.package_sha256[:12]
    print(f"  recorded as #{seq} {crossing.LINE_SCHEMA}, package sha256 {digest}…")


def _trip_bundle_rows(prepared: trip_bundle.Prepared) -> Iterator[str]:
    sel, share = prepared.selection, prepared.share
    c = sel.counts()
    yield (
        f"  {c['logged']} photo and flight lines on the trip's days, {c['crossed']} lines cross,"
        f" {c['held_back']} held back"
    )
    yield (
        f"  stays: {len(share['stays'])}   moves: {len(share['moves'])}   flights: {len(share['flights'])}"
        f"   photos: {share['photos']['count']}"
    )
    held = share["held_back"]["people"]
    people = f"  people: {len(share['people'])}"
    if held:
        people += f" ({held} held back: names are tier 2, cross with --tier 1,2)"
    yield people
    yield f"  resolutions: {c['resolutions']} cross, {c['resolutions_held_back']} held back by tier"
    m = c["attachments"]
    if prepared.attachments:
        files = _plural(m["included"], "file")
        yield f"  attachments: {files}, {m['bytes']:,} bytes; {m['missing']} missing from the store"
    else:
        yield "  attachments: hashes only (--attachments copies the photos' files)"


def cmd_import(a: argparse.Namespace) -> None:
    """`import trip-bundle <folder> [--dry-run]`: a bundle another record exported (RFC 0029), its
    lines appended as received — never over this record's own, never twice."""
    lb = Logbook.find()
    received_at = now_utc()
    try:
        report = trip_bundle.import_bundle(lb, Path(a.path).expanduser(), received_at, dry_run=a.dry_run)
    except trip_bundle.BundleError as e:
        print(f"import trip-bundle: {e}", file=sys.stderr)
        sys.exit(2)
    except OSError as e:
        print(f"import trip-bundle: {e}", file=sys.stderr)
        sys.exit(1)
    trip = report.trip
    head = f"{report.sender['name']}: {trip.get('id')} {trip.get('start')} {EN_DASH} {trip.get('end')}"
    print(f"{'dry run: ' if a.dry_run else ''}{head}{trip_bundle.DOT}bundle {report.bundle_id[:8]}…")
    page = "page received" if report.page else "page received before"
    print(f"  {_plural(report.received, 'line')} received, {report.resolutions} resolutions, {page}")
    print(f"  skipped: {report.kept_own} kept as yours, {report.received_before} received before")
    if report.attachments or report.attachments_missing:
        missing = (
            f"; {report.attachments_missing} missing or not matching" if report.attachments_missing else ""
        )
        print(f"  {_plural(report.attachments, 'attachment')} in the store{missing}")
    if a.dry_run:
        print("  nothing written")


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


def cmd_share(a: argparse.Namespace) -> None:
    """`share day YYYY-MM-DD --to NAME [--tier 1|2|3] [--out FILE]`: one local day as a signed page
    for a member of the circle (RFC 0025, `logbook.share`): the day's lines at or under the tier,
    verbatim, the attachments they point at, the day-package summary and a manifest signed with
    this record's sharing key (made on first use). The tier may not exceed the destination's ceiling
    in policy/crossing.json (ADR 0016); the page is recorded as a crossing/v1 line."""
    lb = Logbook.find()
    try:
        day = parse_day(a.day).isoformat()
        to = share.check_name(a.to)
        tier = share.parse_tier(a.tier)
        out = Path(a.out).expanduser() if a.out else share.default_out(lb, to, day)
        result = share.share_day(lb, day, to, tier, out)
    except (ValueError, share.MissingExtra) as e:  # ShareError and PolicyError are ValueErrors
        print(f"share: {e}", file=sys.stderr)
        sys.exit(2)
    except OSError as e:
        print(f"share: {e}", file=sys.stderr)
        sys.exit(1)
    sel = result.selection
    print(f"{to}: {day}, {_plural(len(sel.lines), 'line')} at tier {tier} {ARROW} {result.out}")
    print(f"  {sel.logged} lines on the day, {len(sel.lines)} shared, {sel.held_back} held back")
    if sel.by_kind:
        print("  " + "   ".join(f"{k}: {n}" for k, n in sel.by_kind.items()))
    m = sel.counts()["attachments"]
    files, missing = _plural(m["included"], "file"), m["missing"]
    print(f"  attachments: {files}, {m['bytes']:,} bytes; {missing} missing from the store")
    if tier == 3:
        text = f"WARNING: {share.TIER3_WARNING}: {_plural(sel.by_tier['3'], 'tier-3 line')} for {to}"
        print(text)
        print(text, file=sys.stderr)
    print(f"  signed with key {result.manifest['key'][:12]}…; recorded as #{result.line['seq']} crossing/v1")


def cmd_receive(a: argparse.Namespace) -> None:
    """`receive FILE [--from NAME]`: verify a page someone shared — its signature under the key
    policy/circle.json holds for them, every line's hash, every file against the manifest — and keep
    it under <root>/circle/<from>/<date>/, outside the chain. Nothing is appended."""
    lb = Logbook.find()
    try:
        result = share.receive(lb, Path(a.file).expanduser(), a.sender)
    except share.AlreadyReceived as e:
        print(f"{e}; nothing changed")
        return
    except (share.ShareError, share.MissingExtra) as e:
        print(f"receive: {e}", file=sys.stderr)
        sys.exit(2)
    except (share.ReceiveError, OSError, ValueError) as e:
        print(f"receive: refused: {e}", file=sys.stderr)
        sys.exit(1)
    manifest = result.manifest
    state = "replaced the page held before" if result.replaced else "kept"
    lines, files = (
        _plural(int(manifest["lines"]), "line"),
        _plural(len(manifest["attachments"]), "attachment"),
    )
    print(
        f"from {result.sender}: {manifest['date']}, {lines} at tier {manifest['max_tier']}, {files} "
        f"{ARROW} {result.page} ({state})"
    )
    print(f"  signature verified under the key held for {result.sender}; every line's hash recomputes")
    print(f"  logbook day {manifest['date']} shows it as a `from {result.sender}` section")


def cmd_circle(a: argparse.Namespace) -> None:
    """`circle` lists the people whose pages this record accepts, with their keys; `circle add NAME
    KEY` adds one, once; `circle key` prints this record's own public key for handing to a friend
    (made on first use)."""
    lb = Logbook.find()
    try:
        if a.verb == "add":
            name = share.check_name(a.name, "name")
            if not policy.KEY.fullmatch(a.key):
                raise share.ShareError(f"a sharing key is 64 hex characters, not {a.key!r}")
            if policy.circle_add(lb.root, name, a.key):
                print(f"{name}: key {a.key.lower()[:12]}… added to {policy.CIRCLE_FILE.as_posix()}")
            else:
                print(f"{name}: already in the circle with that key; nothing changed")
            return
        if a.verb == "key":
            _, public = share.owner_key(lb)
            print(public)
            print(
                f"  this record's sharing key; hand it to a friend: logbook circle add <you> {public}",
                file=sys.stderr,
            )
            return
        circle = policy.circle(lb.root)
    except (ValueError, share.MissingExtra) as e:
        print(f"circle: {e}", file=sys.stderr)
        sys.exit(2)
    if not circle:
        print("nobody in the circle yet: logbook circle add NAME KEY")
        return
    width = max(len(name) for name in circle)
    for name, key in circle.items():
        print(f"{name:<{width}}  {key}")


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
        const=str(screentime.MAC_DEFAULT),
        metavar="DB",
        help=f"screentime: a Mac's {screentime.MAC_STORE} (default this Mac's own, behind Full Disk Access)",
    )
    s.add_argument(
        "--backup",
        metavar="DIR",
        help=f"screentime: an iOS backup folder; its {screentime.PHONE_STORE} is copied into inbox/ and read",
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
    s = sub.add_parser(
        "sync",
        help="pull new items from a live source (immich, dawarich, imessage, gcal, granola, ais, adsb,"
        " weather); safe to re-run; --all for every configured source, --install-schedule for twice a day",
    )
    s.add_argument(
        "name",
        nargs="?",
        help="the source: immich, dawarich, imessage (this Mac's Messages), gcal (Google Calendar), granola,"
        " ais (your vessels via aisstream.io), adsb (your aircraft via OpenSky), weather (the places of your"
        " days, one decimal of latitude, from Open-Meteo)",
    )
    s.add_argument(
        "--all",
        action="store_true",
        help="every configured live source in turn (one with its LOGBOOK_* variables set), a failure in one"
        " never stopping the next; one summary line per source; exit 1 when any failed",
    )
    s.add_argument(
        "--install-schedule",
        action="store_true",
        help="run `sync --all` at 07:00 and 19:00 local: a launchd agent (macOS) or a systemd user timer"
        " (Linux), printed before it is written under your LaunchAgents or systemd user directory",
    )
    s.add_argument("--uninstall-schedule", action="store_true", help="remove that agent or timer")
    s.add_argument(
        "--since",
        metavar="RFC3339",
        help="pull from here instead of the stored watermark (weather: a local day, YYYY-MM-DD)",
    )
    s.add_argument(
        "--listen",
        metavar="SECONDS",
        help="ais: listen this long, then write (default: LOGBOOK_AISSTREAM_LISTEN_S, 60 s)",
    )
    s.add_argument(
        "--until",
        metavar="HH:MM",
        help="ais: listen until the record's local clock next shows this time, then write;"
        " weather: the last local day to cover, YYYY-MM-DD (default yesterday)",
    )
    s.add_argument("--dry-run", action="store_true", help="show what would be appended; write nothing")
    s.set_defaults(fn=cmd_sync)
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
    s = sub.add_parser(
        "infer", help="flights: from the record's own calendar entries and location points (RFC 0013)"
    )
    s.add_argument("what", help="what to infer: flights, or keepers (favourites and the Art album, RFC 0024)")
    s.add_argument("--since", metavar="YYYY-MM-DD", help="only calendar entries from this local day")
    s.add_argument("--until", metavar="YYYY-MM-DD", help="… up to this local day, inclusive")
    s.add_argument(
        "--airports",
        metavar="FILE",
        help="a CSV (iata,icao,name,lat,lon,tz) added to the airports table"
        f" (default ${flights.AIRPORTS_ENV})",
    )
    s.add_argument("--dry-run", action="store_true", help="say what would be written; write nothing")
    s.set_defaults(fn=cmd_infer)
    s = sub.add_parser(
        "transcribe",
        help="voice-memos: a transcript/v1 line per voice memo whose audio is in the store, by a local"
        " engine (RFC 0004); nothing leaves the machine",
    )
    s.add_argument("what", help="what to transcribe: voice-memos")
    s.add_argument("--since", metavar="YYYY-MM-DD", help="only memos from this local day on")
    s.add_argument(
        "--model",
        default=transcribe.DEFAULT_MODEL,
        help="the Whisper model: a size (tiny, base, small, medium, large-v3) or a Hugging Face"
        f" repository (default {transcribe.DEFAULT_MODEL})",
    )
    s.add_argument("--dry-run", action="store_true", help="list what would be transcribed; write nothing")
    s.add_argument(
        "--fetch-model",
        action="store_true",
        help="download the model first when it is not on this machine (the only network use, ever)",
    )
    s.set_defaults(fn=cmd_transcribe)
    s = sub.add_parser(
        "describe",
        help="keepers: a derived note per keeper whose photo file is reachable — one sentence and the"
        " visible things, by a local vision model (RFC 0024, RFC 0010); nothing leaves the machine",
    )
    s.add_argument("what", help="what to describe: keepers")
    s.add_argument("--since", metavar="YYYY-MM-DD", help="only keepers from this local day on")
    s.add_argument("--limit", type=int, metavar="N", help="describe at most N photos this run")
    s.add_argument(
        "--photos",
        action="append",
        metavar="DIR",
        help="a folder holding the photo files: an Apple Photos library (.photoslibrary, by asset UUID) or"
        " any folder (by file name); may repeat. The record's own attachment store is always searched",
    )
    s.add_argument(
        "--model",
        default=describe.DEFAULT_MODEL,
        metavar="NAME",
        help=f"the MLX vision model's repository (default {describe.DEFAULT_MODEL})",
    )
    s.add_argument("--dry-run", action="store_true", help="list what would be described; write nothing")
    s.add_argument(
        "--fetch-model",
        action="store_true",
        help="download the model first when it is not on this machine (the only network use, ever)",
    )
    s.add_argument("--json", action="store_true", help="the run as one JSON object, with line ids")
    s.set_defaults(fn=cmd_describe)
    s = sub.add_parser("retract", help="take back line SEQ with a new line; nothing is rewritten")
    s.add_argument("seq", type=int)
    s.add_argument("reason")
    s.set_defaults(fn=cmd_retract)
    s = sub.add_parser(
        "search",
        help='full-text search: words, "a phrase", kar* — literal, ranked, grouped by day, through the index',
    )
    s.add_argument("text", help='the words; "in quotes" a phrase; a word ending in * matches by prefix')
    s.add_argument("--since", metavar="YYYY-MM-DD", help="the first local day searched")
    s.add_argument("--until", metavar="YYYY-MM-DD", help="the last local day searched")
    s.add_argument(
        "--kinds",
        metavar="note,transcript,message,mail,event",
        help=f"only these kinds (default every kind with words: {', '.join(search.KINDS)})",
    )
    s.add_argument(
        "--tier",
        type=int,
        choices=(1, 2, 3),
        default=search.MAX_TIER,
        help="search up to this tier (default 2); tier 3 — money, health, the transcripts at 3 — only with 3",
    )
    s.add_argument("--limit", type=int, default=search.LIMIT, help=f"the hits shown (default {search.LIMIT})")
    s.add_argument(
        "--json", action="store_true", help="the query, the hits by day with rank, snippet, summary"
    )
    s.set_defaults(fn=cmd_search)
    s = sub.add_parser("show", help="one day (default today), or a page: person, asset or place")
    s.add_argument("day", nargs="?", help="YYYY-MM-DD, or person|asset|place")
    s.add_argument("name", nargs="?", help="with person|asset|place: the name, entity id or asset id")
    s.add_argument("--raw", action="store_true", help="print refs as the sources gave them, never a name")
    s.add_argument("--json", action="store_true", help="a page as one JSON object")
    s.set_defaults(fn=cmd_show)
    s = sub.add_parser(
        "people",
        help="everyone the record names, never the owner: channels, days together, last real contact",
    )
    s.add_argument("--year", metavar="YYYY", help="one year (default the whole record)")
    s.add_argument("--json", action="store_true", help="the report as one JSON object")
    s.set_defaults(fn=cmd_people, verb=None)
    verbs = s.add_subparsers(dest="verb", required=False)
    v = verbs.add_parser(
        "merge",
        help="the same person named twice or more: proposals with the evidence; merged only when told",
    )
    g = v.add_mutually_exclusive_group()
    g.add_argument(
        "--propose", action="store_true", help="list the proposals with their evidence (the default)"
    )
    g.add_argument(
        "--apply",
        nargs="+",
        metavar="ID",
        help="merge these proposals: one alias line per ref of a secondary",
    )
    g.add_argument(
        "--export-review", metavar="FILE", help="write the proposals as a CSV to mark, one row per secondary"
    )
    g.add_argument("--apply-review", metavar="FILE", help="merge the rows marked `yes` in a review file")
    v.add_argument(
        "--json", action="store_true", help="the proposals, or the lines written, as one JSON object"
    )
    v.set_defaults(fn=cmd_people)
    s = sub.add_parser(
        "person", help="one person's page: the numbers, then the shared days, most recent first"
    )
    s.add_argument("name", help="a name, an entity id, an email address, a phone number or kind:value")
    s.add_argument("--year", metavar="YYYY", help="one year (default the whole record)")
    s.add_argument("--json", action="store_true", help="the page as one JSON object")
    s.set_defaults(fn=cmd_person)
    s = sub.add_parser(
        "day", help="one day read back: nights, country, stays and moves with who and what, flights, health"
    )
    s.add_argument("day", nargs="?", metavar="YYYY-MM-DD", help="the local day (default today)")
    s.add_argument(
        "--airports",
        metavar="FILE",
        help=f"a CSV that adds to the airports table (else {flights.AIRPORTS_ENV})",
    )
    s.add_argument(
        "--json", action="store_true", help="the Day as one JSON object, every row with its line ids"
    )
    s.set_defaults(fn=cmd_day)
    s = sub.add_parser(
        "digest",
        help="one day in 25 lines at most: where, with whom, what attached, flights, promises due, gaps,"
        " tomorrow, one question",
    )
    s.add_argument("day", nargs="?", metavar="YYYY-MM-DD", help="the local day (default today)")
    s.add_argument(
        "--airports",
        metavar="FILE",
        help=f"a CSV that adds to the airports table (else {flights.AIRPORTS_ENV})",
    )
    form = s.add_mutually_exclusive_group()
    form.add_argument("--json", action="store_true", help="the digest as one JSON object, with line ids")
    form.add_argument("--markdown", action="store_true", help="the same lines as Markdown")
    s.set_defaults(fn=cmd_digest)
    s = sub.add_parser(
        "questions",
        help="the digest's closing questions (policy/questions.json): list, add one, disable one",
    )
    verbs = s.add_subparsers(dest="verb", required=True)
    v = verbs.add_parser("list", help="one line per question: id, kind, weight, when, text")
    v.add_argument("--json", action="store_true", help="the bank as JSON, as the file holds it")
    v.set_defaults(fn=cmd_questions)
    v = verbs.add_parser("add", help="one more question; the id must be new")
    v.add_argument("id", help="the question's own name, free text")
    v.add_argument(
        "--text", required=True, help="the question, in English; {person}, {place}, ... are filled"
    )
    v.add_argument("--kind", required=True, choices=questions.KINDS)
    v.add_argument(
        "--when",
        action="append",
        metavar="FACT",
        help=f"a fact of the day that must hold (prefix ! for one that must not); repeatable;"
        f" one of {', '.join(questions.FACTS)}",
    )
    v.add_argument("--weight", type=float, default=1.0, help="its share of the draw (default 1)")
    v.add_argument("--source", help="the research behind it, free text")
    v.add_argument("--de", metavar="TEXT", help="the same question in German")
    v.set_defaults(fn=cmd_questions)
    v = verbs.add_parser("disable", help="never ask this one again; it stays in the file")
    v.add_argument("id")
    v.set_defaults(fn=cmd_questions)
    s = sub.add_parser(
        "days", help="a window of days one line each: night, km moved, flights, stays, people, health, gaps"
    )
    s.add_argument("--from", dest="since", metavar="YYYY-MM-DD", help="the first day (default the record's)")
    s.add_argument("--to", dest="until", metavar="YYYY-MM-DD", help="the last day (default the record's)")
    s.add_argument(
        "--airports",
        metavar="FILE",
        help=f"a CSV that adds to the airports table (else {flights.AIRPORTS_ENV})",
    )
    s.add_argument("--json", action="store_true", help="one JSON object per line (JSON Lines)")
    s.set_defaults(fn=cmd_days)
    s = sub.add_parser(
        "year",
        help="one year read back: countries, trips, flights, places, people, health, keepers, a day a month",
    )
    s.add_argument("year", metavar="YYYY", help="the calendar year")
    s.add_argument(
        "--html", metavar="PATH", help="write one self-contained page (inline CSS, no script) instead"
    )
    s.add_argument(
        "--print",
        action="store_true",
        help="with --html: the paper edition — a cover, contents, one spread per month, for A4 and US Letter",
    )
    s.add_argument(
        "--airports",
        metavar="FILE",
        help=f"a CSV that adds to the airports table (else {flights.AIRPORTS_ENV})",
    )
    s.add_argument("--json", action="store_true", help="the Year as one JSON object, the picks' Days inside")
    s.set_defaults(fn=cmd_year)
    s = sub.add_parser(
        "trip", help="one trip read back: the route with a map, days, flights, people, keepers, health, spend"
    )
    s.add_argument(
        "ref",
        metavar="ID-OR-DAY",
        help="a trip id as `trips` prints it (trip:YYYY-MM-DD:YYYY-MM-DD), or any day inside the trip",
    )
    s.add_argument(
        "--html",
        metavar="PATH",
        help="write one self-contained page (inline CSS and SVG map, no script) instead",
    )
    s.add_argument(
        "--print",
        action="store_true",
        help="with --html: the paper edition — a cover, contents, one spread per day, for A4 and US Letter",
    )
    s.add_argument(
        "--airports",
        metavar="FILE",
        help=f"a CSV that adds to the airports table (else {flights.AIRPORTS_ENV})",
    )
    s.add_argument("--json", action="store_true", help="the Trip as one JSON object, the days' rows inside")
    s.set_defaults(fn=cmd_trip)
    s = sub.add_parser("stats", help="what the record holds: counts by kind, source and year, never its text")
    s.add_argument("--json", action="store_true", help="the same numbers as one JSON object")
    s.add_argument(
        "--health",
        action="store_true",
        help="one row per day of the health lines: sleep hours, steps, resting HR",
    )
    s.set_defaults(fn=cmd_stats)
    s = sub.add_parser(
        "derive", help="read the record into stays and moves (`derive stays`); nothing is appended"
    )
    s.add_argument(
        "what", choices=["stays"], help="stays: stays, stops and moves per subject, and each night"
    )
    s.add_argument("--day", metavar="YYYY-MM-DD", help="one local day (default today)")
    s.add_argument("--since", metavar="YYYY-MM-DD", help="first day of a range")
    s.add_argument("--until", metavar="YYYY-MM-DD", help="last day of a range (default --since)")
    s.add_argument("--subject", metavar="ID", help="only this asset's track (assets.json), or `owner`")
    s.add_argument(
        "--airports",
        metavar="FILE",
        help=f"a CSV that adds to the airports table (else {flights.AIRPORTS_ENV})",
    )
    s.add_argument("--dry-run", action="store_true", help="never create policy/stays.json; say what applies")
    s.add_argument("--json", action="store_true", help="the segments and nights as one JSON object")
    s.set_defaults(fn=cmd_derive)
    s = sub.add_parser(
        "places", help="the named places of the record (places.json): list, add, name, propose"
    )
    verbs = s.add_subparsers(dest="verb", required=True)
    v = verbs.add_parser("list", help="one line per place")
    v.set_defaults(fn=cmd_places)
    for verb in ("add", "name"):
        v = verbs.add_parser(
            verb,
            help="add one place"
            if verb == "add"
            else "name a stay (or lat,lon) and put the naming in the record",
        )
        if verb == "name":
            v.add_argument("where", help="lat,lon or a stay id as `places propose` prints it")
        v.add_argument("name", help="what you call it")
        if verb == "add":
            v.add_argument("--lat", type=float, required=True)
            v.add_argument("--lon", type=float, required=True)
        v.add_argument("--radius", type=float, metavar="M", help="metres (default 150)")
        v.add_argument("--kind", choices=places.KINDS, help="home, asset-berth or other (default other)")
        v.add_argument("--tags", metavar="A,B", help="free text, comma-separated")
        v.set_defaults(fn=cmd_places)
    v = verbs.add_parser(
        "import-takeout", help="propose entries from Google Maps' saved and starred places (Takeout)"
    )
    v.add_argument("path", help="Takeout/, `Maps (your places)/`, `Saved/`, or one file of them")
    v.add_argument("--write", action="store_true", help="add the new entries to places.json")
    v.set_defaults(fn=cmd_places)
    v = verbs.add_parser("propose", help="unnamed stays ranked by hours, with what is near; appends nothing")
    v.add_argument("--since", metavar="YYYY-MM-DD", help="first day (default: the record's first)")
    v.add_argument("--until", metavar="YYYY-MM-DD", help="last day (default: the record's last)")
    v.add_argument("--top", type=int, metavar="N", help="only the N biggest")
    v.add_argument(
        "--write", action="store_true", help="ask for each name; accepted ones become places and a note"
    )
    v.add_argument("--json", action="store_true", help="the proposals as one JSON object")
    v.add_argument(
        "--takeout",
        metavar="PATH",
        help="Google Maps' saved places (Takeout/, `Maps (your places)/`, `Saved/` or one file) as"
        " candidates: one near an unnamed stay suggests its name; the rest are listed for `places add`",
    )
    v.set_defaults(fn=cmd_places)
    s = sub.add_parser(
        "rollup",
        help="the record per year: countries, flights, nights, places, people, listen, attention (hours by"
        " app and category), money; per month or week: health, attention",
    )
    s.add_argument("what", choices=(*rollup.KINDS, listen_rollup.KIND), help="what to sum up")
    s.add_argument("--year", metavar="YYYY", help="one calendar year (default: the whole record)")
    s.add_argument("--since", metavar="YYYY-MM-DD", help="first day of a range")
    s.add_argument("--until", metavar="YYYY-MM-DD", help="last day of a range")
    s.add_argument(
        "--by",
        choices=rollup.PERIODS,
        help="health and attention: per calendar month (health's default) or per ISO week; attention is"
        " per year without it",
    )
    s.add_argument(
        "--airports",
        metavar="FILE",
        help=f"a CSV that adds to the airports table (else {flights.AIRPORTS_ENV})",
    )
    s.add_argument(
        "--with",
        dest="with_",
        action="store_true",
        help="places only: the place × person table — stays, days and nights at each place per person",
    )
    s.add_argument(
        "--drifting",
        action="store_true",
        help="people only: whose contact frequency fell most, the last --window days against the same"
        " number of days before them, with days since the last real contact, the channels that went"
        " quiet and the last shared place",
    )
    s.add_argument(
        "--window",
        type=int,
        metavar="DAYS",
        help=f"--drifting: the length of each window in days (default {drifting.DEFAULT_WINDOW}); the"
        " recent one ends on --until, else on the record's last day",
    )
    s.add_argument(
        "--min-contacts",
        type=int,
        metavar="N",
        help="--drifting: list only people with at least this many contacts in the earlier window"
        f" (default {drifting.DEFAULT_MIN_CONTACTS})",
    )
    s.add_argument(
        "--json", action="store_true", help="the rollup as one JSON object, every number with its line ids"
    )
    s.set_defaults(fn=cmd_rollup)
    s = sub.add_parser(
        "trips", help="runs of nights away from home: route, places, people, flights in and out"
    )
    s.add_argument("--year", metavar="YYYY", help="one calendar year (default: the whole record)")
    s.add_argument("--since", metavar="YYYY-MM-DD", help="first day of a range")
    s.add_argument("--until", metavar="YYYY-MM-DD", help="last day of a range")
    s.add_argument(
        "--airports",
        metavar="FILE",
        help=f"a CSV that adds to the airports table (else {flights.AIRPORTS_ENV})",
    )
    s.add_argument("--json", action="store_true", help="the trips as one JSON object, with line ids")
    s.set_defaults(fn=cmd_trips)
    s = sub.add_parser(
        "ledger", help="the transactions in context: at the stay, in the trip, per day; shares per person"
    )
    s.add_argument(
        "--month", metavar="YYYY-MM", help="one calendar month (default: every day with a transaction)"
    )
    s.add_argument("--trip", metavar="ID", help="one trip's days, by the id `trips --json` prints")
    s.add_argument(
        "--airports",
        metavar="FILE",
        help=f"a CSV that adds to the airports table (else {flights.AIRPORTS_ENV})",
    )
    s.add_argument("--json", action="store_true", help="the ledger as one JSON object, with line ids")
    s.set_defaults(fn=cmd_ledger)
    s = sub.add_parser("keepers", help="the photos marked keepers (RFC 0024), by day")
    s.add_argument("--since", metavar="YYYY-MM-DD", help="from this local day")
    s.add_argument("--until", metavar="YYYY-MM-DD", help="up to this local day, inclusive")
    s.add_argument("--lane", choices=keepers.LANES, help="only this lane")
    s.add_argument(
        "--people",
        action="store_true",
        help="who appears on the keepers, per month: the faces the library named, proposed only",
    )
    s.add_argument("--json", action="store_true", help="the keepers as one JSON object")
    s.set_defaults(fn=cmd_keepers)
    s = sub.add_parser(
        "promises",
        help="commitments the transcripts and notes suggest, by rules, as proposals; `done <id>` closes one",
    )
    s.add_argument("--since", metavar="YYYY-MM-DD", help="only lines from this local day on")
    s.add_argument("--open", action="store_true", help="hide the ones a `promises done` closed")
    s.add_argument(
        "--all",
        action="store_true",
        help="every candidate the rules found, not only the judged commitments"
        f" (confidence {promises.THRESHOLD:g} or above)",
    )
    s.add_argument(
        "--judge",
        action="store_true",
        help=f"judge the unjudged candidates with a local model first ({judge.EXTRA}; never the network)",
    )
    s.add_argument("--limit", type=int, metavar="N", help="with --judge: judge at most N candidates this run")
    s.add_argument(
        "--model",
        default=judge.DEFAULT_MODEL,
        metavar="NAME",
        help=f"with --judge: the MLX instruct model's repository (default {judge.DEFAULT_MODEL})",
    )
    s.add_argument(
        "--fetch-model",
        action="store_true",
        help="with --judge: download the model if it is not on this machine (the only network use)",
    )
    s.add_argument("--json", action="store_true", help="the report as one JSON object, with line ids")
    s.set_defaults(fn=cmd_promises, verb=None)
    verbs = s.add_subparsers(dest="verb", required=False)
    v = verbs.add_parser("done", help="mark one proposal done: appends a task/v1 line (RFC 0016)")
    v.add_argument("id", help="the proposal's id, as `promises` prints it")
    v.add_argument("--note", metavar="TEXT", help="your words on how it was kept, kept in the task's notes")
    v.set_defaults(fn=cmd_promises)
    s = sub.add_parser(
        "tasks",
        help="the tasks (task/v1), each as it stands; `--propose-done` the evidence an open one was done;"
        " `done <id>` closes one",
    )
    s.add_argument("--open", action="store_true", help="only the tasks still open")
    s.add_argument(
        "--propose-done",
        action="store_true",
        help="for every open task, the mail, calendar entry or transaction of the"
        f" {taskdone.WINDOW.days} days after it that reads as evidence it was done, by rules;"
        " proposals, with the evidence line's id",
    )
    s.add_argument("--json", action="store_true", help="the report as one JSON object, with line ids")
    s.set_defaults(fn=cmd_tasks, verb=None)
    verbs = s.add_subparsers(dest="verb", required=False)
    v = verbs.add_parser("done", help="mark one task done: appends a task/v1 line (RFC 0016), nothing else")
    v.add_argument("id", help="the task's id, as `tasks` prints it")
    v.add_argument(
        "--evidence",
        metavar="LINE-ID",
        help="the id of the line that shows it was done, kept under the task's extra",
    )
    v.set_defaults(fn=cmd_tasks)
    s = sub.add_parser(
        "serve", help="read the record in a browser, from this machine only (http://127.0.0.1:8765/)"
    )
    s.add_argument(
        "--port", type=int, default=serve.PORT, metavar="N", help=f"the port (default {serve.PORT})"
    )
    s.add_argument(
        "--host", default=serve.HOST, help=f"must be {serve.HOST}; the server refuses any other host"
    )
    s.add_argument("--airports", metavar="FILE", help="an airports table that overrides the built-in one")
    s.set_defaults(fn=cmd_serve)
    s = sub.add_parser(
        "mcp",
        help="serve the record to an MCP host over stdin and stdout; every tool behind the mcp ceiling of"
        " policy/crossing.json (docs/mcp.md)",
    )
    s.add_argument("--root", metavar="DIR", help="logbook folder (default: find)")
    s.add_argument(
        "--allow-tier-3",
        action="store_true",
        help="let tier 3 cross when policy/crossing.json allows it for mcp; without this flag 2 is the most",
    )
    s.add_argument(
        "--inspect", action="store_true", help="print the tool list and a sample call; serve nothing"
    )
    s.set_defaults(fn=cmd_mcp)
    s = sub.add_parser("demo", help="write a synthetic record to try the commands on; nothing in it is real")
    s.add_argument("--days", type=int, metavar="N", help="local days from 2026-06-01 (default 30)")
    s.add_argument(
        "--years",
        type=int,
        metavar="N",
        help="instead: the persona's whole life, N years from her birth to 2026-06-30, in phases",
    )
    s.add_argument("--seed", type=int, default=1, metavar="S", help="the same seed gives the same record")
    s.add_argument("--out", required=True, metavar="DIR", help="a folder that is not yet a logbook")
    s.set_defaults(fn=cmd_demo)
    s = sub.add_parser("index", help="rebuild index.sqlite from the files (readers do it when needed)")
    s.set_defaults(fn=cmd_index)
    s = sub.add_parser("verify", help="check the chain")
    s.add_argument("--root", help="logbook folder (default: find)")
    s.add_argument("--expect", help="expected.json with seq and head (conformance)")
    s.add_argument(
        "--progress",
        action="store_true",
        help="one line per month file on stderr, in path order, as file n of N",
    )
    s.set_defaults(fn=cmd_verify)
    s = sub.add_parser(
        "setup",
        help="the guided first run: where the record lives, your timezone, who you are, your home, what is"
        " on this machine to import; one question at a time, resumable; --yes takes every default",
    )
    s.add_argument("--yes", action="store_true", help="take every default, ask nothing (tests, scripts)")
    s.add_argument("--step", metavar="NAME", help="run one step again: " + ", ".join(setup.STEPS))
    s.add_argument("--again", action="store_true", help="run every step again (the record is kept)")
    s.set_defaults(fn=cmd_setup)
    s = sub.add_parser(
        "doctor", help="is this machine set up to keep the record? one line per check; exit 1 on a fail"
    )
    s.set_defaults(fn=cmd_doctor)
    s = sub.add_parser(
        "export",
        help="the whole log as one .jsonl, one day-package/v1 per day, `crossing`: a crossing-package/v1,"
        " or `vault FOLDER`: Markdown pages with wikilinks for Obsidian or Logseq, or `trip-bundle TRIP`:"
        " one trip for a member of the circle",
    )
    s.add_argument(
        "path",
        nargs="?",
        help=".jsonl file for the whole log, `crossing` (RFC 0005), `vault` (docs/vault.md)"
        " or `trip-bundle` (RFC 0029)",
    )
    s.add_argument(
        "target",
        nargs="?",
        metavar="FOLDER|TRIP",
        help="vault: the folder to write the pages into (an Obsidian vault);"
        " trip-bundle: the trip id as `trips` prints it, or a day inside it",
    )
    s.add_argument("--day", metavar="YYYY-MM-DD", help="one day-package/v1 directory")
    s.add_argument("--days", nargs=2, metavar=("FROM", "TO"), help="one directory per day, inclusive")
    s.add_argument("--out", metavar="DIR", help="where to write (default <root>/export/<date>/)")
    s.add_argument("--empty", action="store_true", help="with --days: also write days with no entries")
    s.add_argument("--to", metavar="DESTINATION", help="crossing: the circle member, e.g. hermes")
    s.add_argument(
        "--since",
        metavar="RFC3339|last|DAY",
        help="crossing: window start, or the last window's end; vault: the first day (default: the record's)",
    )
    s.add_argument(
        "--until",
        metavar="RFC3339|DAY",
        help="crossing: window end, exclusive (default now); vault: the last day, inclusive (default: the"
        " record's)",
    )
    s.add_argument(
        "--tier", metavar="1|1,2|1,2,3", help="crossing: tiers to cross (default 1); vault: 1 or 1,2, never 3"
    )
    s.add_argument("--kinds", metavar="a,b", help="crossing: only these kinds")
    s.add_argument(
        "--dry-run",
        action="store_true",
        help="crossing, trip-bundle: count and show the policy; write nothing",
    )
    s.add_argument(
        "--attachments",
        action="store_true",
        help="trip-bundle: copy the photos' files into the bundle (default: their hashes only)",
    )
    s.add_argument(
        "--airports",
        metavar="FILE",
        help=f"trip-bundle: a CSV that adds to the airports table (else {flights.AIRPORTS_ENV})",
    )
    s.set_defaults(fn=cmd_export)
    s = sub.add_parser(
        "import", help="a trip bundle another record exported (RFC 0029): its lines appended as received"
    )
    s.add_argument("what", choices=[trip_bundle.COMMAND], help="what the folder holds")
    s.add_argument("path", metavar="FOLDER", help="the bundle: manifest.json, entries.jsonl, trip.json, …")
    s.add_argument("--dry-run", action="store_true", help="count what would be received; write nothing")
    s.set_defaults(fn=cmd_import)
    s = sub.add_parser(
        "sources",
        help="every adapter, file and live, and whether policy/import.json has disabled it;"
        " --gaps: where each source went quiet",
    )
    s.add_argument(
        "--gaps",
        action="store_true",
        help="per source with lines: its last line's time, the longest silent stretch and the days with"
        " no line, from the index",
    )
    s.add_argument(
        "--since",
        metavar="YYYY-MM-DD",
        help="with --gaps: the range starts here (default: each source's first line)",
    )
    s.add_argument(
        "--expect",
        nargs="+",
        metavar="SOURCE",
        help="with --gaps: only these sources; one silent for a day or more, or with no line, is flagged"
        " and the command exits 1",
    )
    s.add_argument("--json", action="store_true", help="with --gaps: the report as JSON")
    s.set_defaults(fn=cmd_sources)
    s = sub.add_parser("assets", help="the boats, aircraft and cars the record tracks (assets.json)")
    verbs = s.add_subparsers(dest="verb", required=True)
    v = verbs.add_parser("list", help="one line per registered asset")
    v.set_defaults(fn=cmd_assets)
    v = verbs.add_parser(
        "status", help="per asset, its last known position (time, place, speed) and how old that fix is"
    )
    v.add_argument("--json", action="store_true", help="the statuses as JSON")
    v.set_defaults(fn=cmd_assets)
    v = verbs.add_parser("add", help="register one asset")
    v.add_argument("id", help="the subject id its positions carry: lower-case letters, digits, hyphens")
    v.add_argument("--kind", required=True, choices=assets.KINDS)
    v.add_argument("--name", required=True, help="what you call it")
    v.add_argument("--mmsi", help="nine digits; `sync ais` asks aisstream.io for it")
    v.add_argument("--icao24", help="six hex digits; `sync adsb` asks OpenSky for it")
    v.add_argument("--registration", help="call sign or plate, free text")
    v.set_defaults(fn=cmd_assets)
    s = sub.add_parser("repair", help="append the lines that put a known mistake right; nothing is rewritten")
    verbs = s.add_subparsers(dest="verb", required=True)
    v = verbs.add_parser(
        "health-units",
        help="retract apple-health resting_hr and hrv lines written 60 and 1,000 times too large and"
        " re-emit them corrected (RFC 0014)",
    )
    v.add_argument(
        "--dry-run", action="store_true", help="print how many lines would be appended; write nothing"
    )
    v.set_defaults(fn=cmd_repair)
    s = sub.add_parser("share", help="hand one day to a member of the circle as a signed page (RFC 0025)")
    verbs = s.add_subparsers(dest="what", required=True)
    v = verbs.add_parser(
        "day", help="one local day: its lines at or under the tier, their attachments, signed"
    )
    v.add_argument("day", metavar="YYYY-MM-DD", help="the local day")
    v.add_argument(
        "--to", required=True, metavar="NAME", help="the circle member, as policy/crossing.json names them"
    )
    v.add_argument(
        "--tier", metavar="1|2|3", help="the highest tier to share (default 1; never above the ceiling)"
    )
    v.add_argument(
        "--out", metavar="FILE", help="the zip to write (default <root>/export/share/<to>/<date>.zip)"
    )
    v.set_defaults(fn=cmd_share)
    s = sub.add_parser(
        "receive", help="verify a page someone shared and keep it beside the record, never in the chain"
    )
    s.add_argument("file", metavar="FILE", help="the page, a zip")
    s.add_argument("--from", dest="sender", metavar="NAME", help="check against this circle member's key")
    s.set_defaults(fn=cmd_receive)
    s = sub.add_parser("circle", help="the people whose pages this record accepts: their sharing keys")
    s.set_defaults(fn=cmd_circle, verb=None)
    verbs = s.add_subparsers(dest="verb", required=False)
    v = verbs.add_parser("add", help="add one person's public sharing key, once")
    v.add_argument("name", metavar="NAME", help="what you call them; the folder their pages go under")
    v.add_argument(
        "key", metavar="KEY", help="their public key, 64 hex characters (`logbook circle key` on their side)"
    )
    v.set_defaults(fn=cmd_circle)
    v = verbs.add_parser("key", help="print this record's own public sharing key (made on first use)")
    v.set_defaults(fn=cmd_circle)
    s = sub.add_parser("migrate", help="bring a logbook/0.1 record to logbook/0.2 (same lines, new hashes)")
    s.add_argument("--root", help="logbook folder (default: find)")
    s.set_defaults(fn=cmd_migrate)
    s = sub.add_parser(
        "backup",
        help="a verified snapshot of the record under DEST/<owner_id>/<timestamp>/, hard-linked to the"
        " previous one where nothing changed; `backup list DEST`; `backup restore SNAPSHOT TARGET`",
    )
    s.add_argument(
        "paths",
        nargs="+",
        metavar="DEST",
        help="where the snapshots go (another disk; never inside the record, never a sync client's"
        " folder); or `list DEST`; or `restore SNAPSHOT TARGET`",
    )
    s.add_argument(
        "--keep", type=int, metavar="N", help="after the new snapshot verifies, prune the oldest so N remain"
    )
    s.add_argument(
        "--verify",
        action="store_true",
        help="also hash every attachment in the copy against its name (the chain is always verified)",
    )
    s.set_defaults(fn=cmd_backup)
    a = ap.parse_args(argv)
    try:
        a.fn(a)
        sys.stdout.flush()  # a short listing sits in the buffer until exit: meet the closed pipe here
    except FormatError as e:  # verify and every writer refuse a record hashed by another rule
        print(f"{a.cmd}: {e}", file=sys.stderr)
        sys.exit(2)
    except zoneinfo.ZoneInfoNotFoundError as e:  # SPEC §2: a zone this host lacks is said, never swapped
        reason = e.args[0] if e.args else str(e)
        print(f"{a.cmd}: {reason}; this machine's zone database does not know it", file=sys.stderr)
        sys.exit(2)
    except BrokenPipeError:  # the reader went away (`| head`): stop quietly, status 0
        _stdout_to_devnull()
    except SystemExit:  # a command's own status (`sources --gaps` exits 1) stands; the pipe is still quiet
        _flush_quietly()
        raise


def _flush_quietly() -> None:
    """Flush stdout now, so a pipe whose reader is gone is seen here and not reported by the
    interpreter's final flush."""
    try:
        sys.stdout.flush()
    except BrokenPipeError:
        _stdout_to_devnull()


def _stdout_to_devnull() -> None:
    """Point stdout at the null device so the interpreter's final flush does not report the
    broken pipe on stderr and turn the exit status into 120. Python ignores SIGPIPE at start-up,
    so a write to a closed pipe is a BrokenPipeError, never a signal; this is where every reader
    meets it."""
    with contextlib.suppress(OSError, ValueError):  # no real file behind stdout (a test capture)
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())


if __name__ == "__main__":
    main()
