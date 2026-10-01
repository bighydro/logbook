"""logbook — init · add · sync · import-backup · infer · retract · show · stats · derive · verify · export ·
index · migrate · assets. Three verbs, eleven rare."""

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
from datetime import UTC, date, datetime, timedelta
from pathlib import Path, PurePath
from typing import Any
from zoneinfo import ZoneInfo

from . import (
    FORMAT,
    __version__,
    adapters,
    assets,
    crossing,
    flights,
    ios_backup,
    ios_backup_crypto,
    places,
    policy,
    stays,
)
from .adapters import ios_contacts
from .chain import Line
from .export import day_packages, day_range, parse_day, write_package
from .index import local_date
from .resolve import Ref, labels
from .store import (
    RETRACTION,
    CodeCheckoutError,
    FormatError,
    Logbook,
    UnsortedFile,
    _dedupe_key,
    now_utc,
    retractions,
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
    `given` are the command's own options (`source`, `tier`, `at`, `since`, `account`, `attachments`,
    `only_labels`, `skip_labels`), passed when the adapter's `run` takes them; one it does not take
    exits 2, so a flag is never silently ignored. An adapter whose `run` takes `owner_emails` gets
    the record's own addresses from `logbook.json` (RFC 0015), with a hint when there are none."""
    counts: dict[str, int] = {}
    run: Callable[..., Iterator[dict[str, Any]]] = adapter.run
    options: dict[str, Any] = {}
    if _takes(adapter, "counts"):
        options["counts"] = counts
    if _takes(adapter, "timezone"):
        options["timezone"] = lb.meta["timezone"]
    if _takes(adapter, "store"):
        options["store"] = lb.attach
    if _takes(adapter, "store_file"):
        options["store_file"] = lb.attach_file
    if _takes(adapter, "assets"):
        options["assets"] = _registry(lb, "add")
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
    drafts = flights.reconcile(lb, run(p, **options), counts, options.get("airports"))
    n = lb.append_many(drafts, progress=_progress)
    print(f"added {n} lines from {adapter.NAME}")
    _report_skipped(counts)
    return n


def _registry(lb: Logbook, command: str) -> list[assets.Asset]:
    """The record's asset registry for an adapter that takes `assets`; a broken file exits 2."""
    try:
        return assets.read(lb.root)
    except assets.AssetError as e:
        print(f"{command}: {e}", file=sys.stderr)
        sys.exit(2)


def _takes(adapter: adapters.Adapter | adapters.LiveAdapter, option: str) -> bool:
    """Whether the adapter's `run` (or a live adapter's `pull`) accepts the optional keyword:
    `counts` (a dict to tally what it skipped), `timezone` (the record's zone, for a source whose
    times are floating), `store` (puts bytes in the attachment store), `store_file` (puts a file
    there, streamed), `lookup` (the id of a line by
    source and raw_id), `failed` (a live adapter's list for the feeds it could not read), or one of
    `assets` (the asset registry, ADR 0018), or one of `add`'s own options."""
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
    "skipped_no_title": "without a title",
    "skipped_no_url": "without a url",
    "skipped_ad": "advertisements",
    "skipped_never_played": "never played",
    "skipped_other_activity": "of another activity",
    "skipped_not_involved": "the owner is not part of",
    "skipped_no_owner": "with nobody to be the owner",
    "skipped_no_amount": "without an amount",
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
    "skipped_sidecar_without_file": "sidecars without a media file",
    "skipped_unreadable_json": "JSON files that would not parse",
    "skipped_unreadable": "passes that would not parse",
    "skipped_no_year": "boarding passes whose year nothing on the pass gives",
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
}
NOTE_PHRASES = {  # counts that are not skips: the line was written, with something worth knowing
    "no_stanza_id": "without a stanza id, keyed by row id",
    "no_guid": "without a guid, keyed by row id",
    "no_unique_id": "without a unique id, keyed by row id",
    "no_counterparty": "without a counterparty",
    "media_hashed": "with media hashed",
    "media_missing": "with media missing",
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
    "no_airport_zone": "with an airport the table does not know",
    "arrival_before_departure": "arriving before departing, kept as given",
    "no_gap": "calendar flights the location points do not confirm",
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


def _file_progress(file: str, n: int, total: int, elapsed: float) -> None:
    """`verify --progress`: one line per month file as its last line is checked, on stderr, so
    stdout stays the one line it always was."""
    print(f"  {file}: {n:,} lines ({total:,} so far, {elapsed:,.0f}s)", file=sys.stderr)


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
    }
    if a.what[0] == "flight" and len(a.what) > 1 and flights.starts_with_designator(" ".join(a.what[1:])):
        _add_flight(lb, " ".join(a.what[1:]), given["airports"] or _airports(None))
        return

    if len(a.what) > 1 and (by_name := adapters.named(a.what[0])) is not None:
        paths = [Path(w).expanduser() for w in a.what[1:]]
        if all(p.exists() for p in paths):  # else the whole thing may be a sentence
            _add_named(lb, by_name, paths, given)
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


def _add_named(lb: Logbook, adapter: adapters.Adapter, paths: list[Path], given: Mapping[str, Any]) -> None:
    """`add <adapter> <file|folder>...`: every path through the named adapter, sniffed or not
    (`transcript` reads Markdown and plain text this way only; `ios-calls` a store copied out of a
    backup under any name), with `--source`, `--tier` and `--at` when it takes them."""
    for p in paths:
        _append_with(lb, adapter, p, given)


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
    options: dict[str, Any] = {}
    if _takes(adapter, "store") and not a.dry_run:
        options["store"] = lb.attach
    if _takes(adapter, "lookup"):
        options["lookup"] = _lookup(lb)
    if _takes(adapter, "timezone"):
        options["timezone"] = lb.meta["timezone"]
    failed: list[str] = []  # one line per feed the adapter could not read, the others still pulled
    if _takes(adapter, "failed"):
        options["failed"] = failed
    if _takes(adapter, "assets"):
        options["assets"] = _registry(lb, "sync")
    group: Callable[[dict[str, Any]], str] | None = getattr(adapter, "group", None)
    seen["groups"] = Counter()
    seen["group_marks"] = {}  # the largest watermark per group, kept in the state when GROUP_MARKS
    already_in_group: Counter[str] = Counter()
    drafts = _watch(
        adapter.pull(config, since, progress=_page_progress(unit), counts=counts, **options),
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
        if failed:
            sys.exit(1)
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
    if failed:
        sys.exit(1)


def cmd_infer(a: argparse.Namespace) -> None:
    """`infer flights [--since DAY] [--until DAY] [--airports FILE] [--dry-run]`: flight/v1 lines
    (RFC 0013, evidence `inferred`) from the record's own calendar entries and location points,
    merged into the flights already standing; a re-run appends nothing new."""
    if a.what != "flights":
        print(f"infer: only flights can be inferred yet, not {a.what!r}", file=sys.stderr)
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
            already = len(idx.existing({key for d in found if (key := _dedupe_key(d)) is not None}))
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


def cmd_assets(a: argparse.Namespace) -> None:
    """`assets list`: one line per registered asset. `assets add`: register one (ADR 0018). The
    registry is <root>/assets.json, a setting of the record, outside the chain."""
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
    except assets.AssetError as e:
        print(f"assets: {e}", file=sys.stderr)
        sys.exit(2)
    if not registry:
        print(
            "no assets registered; register one with: logbook assets add <id> --kind "
            f"{'|'.join(assets.KINDS)} --name NAME [--mmsi N] [--icao24 HEX] [--registration REG]"
        )
        return
    for asset in registry:
        print(_asset_row(asset))


def cmd_places(a: argparse.Namespace) -> None:
    """`places import-takeout <path> [--write]`: Google Maps' saved and starred places (the Takeout
    `Maps (your places)/` and `Saved/` folders, or one file of them) proposed as entries of
    <root>/places.json — a setting of the record, outside the chain — and written only with
    `--write`, never changing an entry already there (`logbook/places.py`)."""
    lb = Logbook.find()
    try:
        proposals = places.read(Path(a.path).expanduser())
        report = places.merge(lb.root, proposals, write=a.write)
    except FileNotFoundError as e:
        print(f"places: no such file or directory: {e}", file=sys.stderr)
        sys.exit(2)
    except ValueError as e:
        print(f"places: {e}", file=sys.stderr)
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
    beside it), Safari's history through `safari` (RFC 0017)."""
    lb = Logbook.find()
    try:
        manifest = ios_backup.Manifest(Path(a.backup).expanduser())
    except ios_backup.NotABackup as e:
        print(f"import-backup: {e}", file=sys.stderr)
        sys.exit(2)
    sources = _only(a.only, manifest.encrypted)
    inbox = lb.root / "inbox" / f"ios-backup-{manifest.udid}"
    if manifest.encrypted:
        _unlock(manifest, inbox)
    plans = ios_backup.plan(manifest, sources)
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
        adapter = adapters.named(p.source.name) if p.source.adapter else None
        if adapter is None and p.source.adapter:  # a build without this adapter: say so, copy nothing
            print(f"  no adapter named {p.source.name} in this build; skipped")
            continue
        try:
            store_copy = ios_backup.copy(p, inbox / p.source.name)
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
        _append_with(lb, adapter, store_copy.parent if p.source.pattern else store_copy, given)
    if any(p.copied for p in plans):
        ios_backup.write_copies(inbox, manifest, plans)
    seq, head, errors = lb.verify()
    if errors:
        print(f"INVALID — {len(errors)} problem(s):")
        for problem in errors:
            print("  " + problem)
        sys.exit(1)
    print(f"valid — {seq} lines, head {head}")


def _unlock(manifest: ios_backup.Manifest, inbox: Path) -> None:
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
        manifest.unlock(password, inbox / ios_backup.MANIFEST_DB)
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
        f" {ios_backup.MANIFEST_DB} decrypted to {inbox / ios_backup.MANIFEST_DB}"
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


def _plan_row(p: ios_backup.Plan, inbox: Path) -> str:
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
            f" under {p.source.relative_path}/ → {inbox / p.source.name}"
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
        superseded = idx.superseded(flights.KIND)  # a flight another flight line replaced (RFC 0013 rule 4)
        names: dict[Ref, str] | None = None if a.raw else labels(lb, idx)
    if not rows:
        print(f"{day}: nothing logged")
        return
    rows.sort(key=lambda line: (line["at"], line["seq"]))
    print(day)
    for text in _day_rows(rows, retracted, tz, names, superseded):
        print(text)
    note = lb.root / "notes" / day[:4] / f"{day}.md"
    if note.exists():
        print("  — note —\n" + "\n".join("  " + s for s in note.read_text(encoding="utf-8").splitlines()))


def _day_rows(
    rows: list[Line],
    retracted: dict[str, Line],
    tz: ZoneInfo,
    names: Mapping[Ref, str] | None,
    superseded: Mapping[str, int] | None = None,
) -> Iterator[str]:
    """One printed row per line, except that a run of location points from one source, unbroken
    by any other row, collapses into one summary, and one calendar entry that several sources
    carry (`_fold_events`) is one row naming them. `names` is the label map; None is the `--raw`
    path: refs exactly as the sources gave them, no label, no fallback."""
    run: list[Line] = []
    rows, sources = _fold_events(rows, retracted)
    for line in rows:
        retraction = retracted.get(line["id"])
        point = line["kind"] == "location" and retraction is None
        if run and not (point and (line["source"], _subject(line)) == (run[0]["source"], _subject(run[0]))):
            yield _run_row(run, tz)
            run = []
        if point:
            run.append(line)
        else:
            yield _line_row(line, retraction, tz, names, superseded, sources.get(str(line["id"])))
    if run:
        yield _run_row(run, tz)


SAME_EVENT_WITHIN = timedelta(minutes=5)


def _fold_events(rows: list[Line], retracted: Mapping[str, Line]) -> tuple[list[Line], dict[str, str]]:
    """The rows with every calendar entry that repeats an earlier one from another source
    dropped, and, for each entry kept in their place, its sources as `ics+ios-calendar`. Two
    entries are one event when they carry the same title, or name the same flight (`Flight to
    Zürich (LX 561)`, `Flug LX561 nach Zürich`), and start within five minutes of each other;
    the fold happens only across sources — one calendar holding an entry twice is two entries."""
    airlines = flights.Airlines.load()
    clusters: list[list[Line]] = []
    for line in rows:
        if line["kind"] != "event" or line["id"] in retracted:
            continue
        for cluster in clusters:
            first = cluster[0]
            apart = abs(_instant(str(line["at"])) - _instant(str(first["at"])))
            if apart <= SAME_EVENT_WITHIN and _same_event(first, line, airlines):
                cluster.append(line)
                break
        else:
            clusters.append([line])
    dropped: set[str] = set()
    sources: dict[str, str] = {}
    for cluster in clusters:
        seen = list(dict.fromkeys(str(line["source"]) for line in cluster))
        if len(seen) < 2:
            continue
        sources[str(cluster[0]["id"])] = "+".join(seen)
        dropped.update(str(line["id"]) for line in cluster[1:])
    return [line for line in rows if str(line["id"]) not in dropped], sources


def _same_event(a: Line, b: Line, airlines: flights.Airlines) -> bool:
    title_a, title_b = (str((line.get("payload") or {}).get("title") or "") for line in (a, b))
    if " ".join(title_a.split()).casefold() == " ".join(title_b.split()).casefold():
        return True
    flight = flights.designator(title_a, airlines)
    return flight is not None and flight == flights.designator(title_b, airlines)


def _instant(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def _line_row(
    line: Line,
    retraction: Line | None,
    tz: ZoneInfo,
    names: Mapping[Ref, str] | None,
    superseded: Mapping[str, int] | None = None,
    sources: str | None = None,
) -> str:
    """`sources` names every source of a folded calendar entry (`_fold_events`) in place of the
    line's own."""
    clock = _clock(line["at"], tz)
    if retraction is not None:
        return f"  {clock}  retracted #{line['seq']}: {retraction['payload'].get('reason', '')}"
    p = line["payload"]
    by = (superseded or {}).get(str(line["id"]))
    if by is not None:
        return f"  {clock}  {line['kind']:<10} {line['source']:<14} superseded by #{by}"
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
    elif line["kind"] == "note":
        text = _note_text(p, raw=names is None)
    elif line["kind"] == "highlight" and p.get("schema") == "highlight/v1":
        text = _highlight_text(p)
    elif line["kind"] == "voice-memo" and p.get("schema") == "voice-memo/v1":
        text = _voice_memo_text(p)
    elif line["kind"] == "trip" and p.get("schema") == "trip/v1":
        text = _trip_text(p)
    elif line["kind"] == "crossing" and p.get("schema") == "crossing/v1":
        text = _crossing_text(p)
    else:
        text = (
            p.get("text")
            or p.get("title")
            or p.get("name")
            or p.get("url")
            or ", ".join(f"{k}={v}" for k, v in p.items() if k != "schema")
        )
    return f"  {clock}  {line['kind']:<10} {sources or line['source']:<14} {text}"


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


ASLEEP = frozenset({"asleep", "core", "deep", "rem"})  # RFC 0014 rule 4: never in_bed, never awake


def health_days(lb: Logbook) -> list[dict[str, Any]]:
    """One row per local day (the record's zone) that has any of: `sleep_h`, the asleep stages of
    the night that ends on that day, summed per device and the longest device taken (rule 5),
    in hours to one decimal; `steps`, the sum over the day's quarter hours of the larger device's
    count (rule 5); `resting_hr`, the mean of the day's resting readings, whole bpm. A field the
    day has no line for is None. Retracted lines are left out."""
    tz = str(lb.meta["timezone"])
    steps: dict[str, dict[str, float]] = {}  # day → bucket `at` → the larger device's count
    sleep: dict[str, dict[str, float]] = {}  # day → device → seconds asleep
    resting: dict[str, list[float]] = {}
    with lb.index() as idx:
        hidden = {r.get("payload", {}).get("supersedes") for r in idx.retractions()}
        for line in idx.of_kind("health"):
            if line.get("id") in hidden:
                continue
            payload = line.get("payload") or {}
            value = payload.get("value")
            if isinstance(value, bool) or not isinstance(value, int | float):
                continue
            kind = payload.get("type")
            try:
                if kind == "steps":
                    day = local_date(str(line["at"]), tz)
                    buckets = steps.setdefault(day, {})
                    buckets[str(line["at"])] = max(buckets.get(str(line["at"]), 0.0), float(value))
                elif kind == "sleep" and payload.get("stage") in ASLEEP:
                    day = local_date(str(line.get("end") or line["at"]), tz)
                    device = str(payload.get("device") or "-")
                    per_device = sleep.setdefault(day, {})
                    per_device[device] = per_device.get(device, 0.0) + float(value)
                elif kind == "resting_hr":
                    resting.setdefault(local_date(str(line["at"]), tz), []).append(float(value))
            except (KeyError, ValueError, TypeError):  # a stamp that does not parse is on no day
                continue
    rows: list[dict[str, Any]] = []
    for day in sorted(set(steps) | set(sleep) | set(resting)):
        nights, readings = sleep.get(day), resting.get(day)
        rows.append(
            {
                "day": day,
                "sleep_h": round(max(nights.values()) / 3600, 1) if nights else None,
                "steps": round(sum(steps[day].values())) if day in steps else None,
                "resting_hr": round(sum(readings) / len(readings)) if readings else None,
            }
        )
    return rows


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
    first and every asset's after (ADR 0018), the owner's stays marked aboard where an asset's
    track matches, and the overnight stay of each day; a table in local time, or JSON. The window
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
    tz = ZoneInfo(lb.meta["timezone"])
    try:
        path = stays.settings_path(lb.root)
        if a.dry_run:
            note = f"settings from {path}" if path.exists() else f"default settings; {path} not written"
            print(f"dry run: {note}", file=sys.stderr)
        else:
            stays.write_default_settings(lb.root)
        settings = stays.read_settings(lb.root)
        places = stays.read_places(lb.root, settings.radius_m)
        registered = stays.read_assets(lb.root)
    except stays.SettingsError as e:
        print(f"derive: {e}", file=sys.stderr)
        sys.exit(2)
    days = day_range(first, last)
    start = datetime.combine(date.fromisoformat(first), datetime.min.time(), tzinfo=tz)
    _night_start, end = stays.night_window(last, tz, settings)
    with lb.index() as idx:
        spill = (date.fromisoformat(last) + timedelta(days=1)).isoformat()
        lines = [line for _day, line in idx.between(first, spill)]
        lines += idx.retractions()  # from every file: a retraction applies wherever its line is
    window = [
        line
        for line in lines
        if line["kind"] == RETRACTION or ((at := stays.instant(line["at"])) is not None and start <= at < end)
    ]
    derived = stays.derive(
        window,
        settings,
        places,
        {k: v.kind for k, v in registered.items()},
        lb.meta["timezone"],
        _airports(a.airports),
    )
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
    segments = [s for s in derived.segments if s.subject in subjects]
    nights = [stays.night(segments, day, tz, settings) for day in days] if None in subjects else []
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
    each day's rows under its date, the owner's night after each day's rows."""
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
            elif day in days:
                yield f"{day}: no location lines"
            if subject is None and day in by_night:
                yield _night_row(by_night[day], tz)


def _segment_row(s: stays.Segment, tz: ZoneInfo) -> str:
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
    if s.aboard:
        parts.append(f"aboard {s.aboard}")
    return f"  {_span(s.start, s.end, tz):<14} {s.kind:<5} {' · '.join(parts)}"


def _night_row(n: stays.Night, tz: ZoneInfo) -> str:
    if n.stay is None:
        return "  night          in transit"
    return f"  night          {_where(n.stay)} · {_span(n.stay.start, n.stay.end, tz)}"


def _where(s: stays.Segment) -> str:
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
    seq, head, errors = lb.verify(warnings, progress=_file_progress if a.progress else None)
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
    s.set_defaults(fn=cmd_add)
    s = sub.add_parser(
        "sync",
        help="pull new items from a live source (immich, dawarich, imessage, gcal, granola, ais, adsb);"
        " safe to re-run",
    )
    s.add_argument(
        "name",
        help="the source: immich, dawarich, imessage (this Mac's Messages), gcal (Google Calendar), granola,"
        " ais (your vessels via aisstream.io), adsb (your aircraft via OpenSky)",
    )
    s.add_argument("--since", metavar="RFC3339", help="pull from here instead of the stored watermark")
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
        "infer", help="flights: from the record's own calendar entries and location points (RFC 0013)"
    )
    s.add_argument("what", help="what to infer: flights")
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
    s = sub.add_parser("index", help="rebuild index.sqlite from the files (readers do it when needed)")
    s.set_defaults(fn=cmd_index)
    s = sub.add_parser("verify", help="check the chain")
    s.add_argument("--root", help="logbook folder (default: find)")
    s.add_argument("--expect", help="expected.json with seq and head (conformance)")
    s.add_argument(
        "--progress", action="store_true", help="one line per month file on stderr, as each is finished"
    )
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
    s = sub.add_parser("assets", help="the boats, aircraft and cars the record tracks (assets.json)")
    verbs = s.add_subparsers(dest="verb", required=True)
    v = verbs.add_parser("list", help="one line per registered asset")
    v.set_defaults(fn=cmd_assets)
    v = verbs.add_parser("add", help="register one asset")
    v.add_argument("id", help="the subject id its positions carry: lower-case letters, digits, hyphens")
    v.add_argument("--kind", required=True, choices=assets.KINDS)
    v.add_argument("--name", required=True, help="what you call it")
    v.add_argument("--mmsi", help="nine digits; `sync ais` asks aisstream.io for it")
    v.add_argument("--icao24", help="six hex digits; `sync adsb` asks OpenSky for it")
    v.add_argument("--registration", help="call sign or plate, free text")
    v.set_defaults(fn=cmd_assets)
    s = sub.add_parser("places", help="the named places derive stays uses (places.json)")
    verbs = s.add_subparsers(dest="verb", required=True)
    v = verbs.add_parser(
        "import-takeout", help="propose entries from Google Maps' saved and starred places (Takeout)"
    )
    v.add_argument("path", help="Takeout/, `Maps (your places)/`, `Saved/`, or one file of them")
    v.add_argument("--write", action="store_true", help="add the new entries to places.json")
    v.set_defaults(fn=cmd_places)
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
