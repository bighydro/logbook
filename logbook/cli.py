"""logbook — init · add · sync · retract · show · verify · export · index · migrate. Three verbs, six rare."""

from __future__ import annotations

import argparse
import contextlib
import inspect
import json
import os
import sys
import time
import zoneinfo
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import date, datetime
from pathlib import Path, PurePath
from typing import Any
from zoneinfo import ZoneInfo

from . import FORMAT, __version__, adapters
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


def _add_file(lb: Logbook, p: Path) -> bool:
    """Append one file through the adapter that recognises it. False when nothing does."""
    adapter = adapters.find(p)
    if adapter is not None:
        counts: dict[str, int] = {}
        run: Callable[..., Iterator[dict[str, Any]]] = adapter.run
        options: dict[str, Any] = {}
        if _takes(adapter, "counts"):
            options["counts"] = counts
        if _takes(adapter, "timezone"):
            options["timezone"] = lb.meta["timezone"]
        drafts = run(p, **options)
        n = lb.append_many(drafts, progress=_progress)
        print(f"added {n} lines from {adapter.NAME}")
        _report_skipped(counts)
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


def _takes(adapter: adapters.Adapter, option: str) -> bool:
    """Whether the adapter's `run` accepts the optional keyword: `counts` (a dict to tally what it
    skipped) or `timezone` (the record's zone, for a source whose times are floating)."""
    return option in inspect.signature(adapter.run).parameters


LOCATION_SKIPS = ("skipped_no_timestamp", "skipped_bad_coordinates")
SKIP_PHRASES = {
    "skipped_no_timestamp": "without a timestamp",
    "skipped_bad_coordinates": "with unusable coordinates",
    "skipped_no_ref": "without a phone or email",
    "skipped_empty_ref": "with an empty phone or email",
    "skipped_duplicate_ref": "with a phone or email already seen",
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


def _page_progress(n: int, elapsed: float) -> None:
    """One line per page pulled from a live source, dry runs included."""
    print(f"  {n:,} assets in {elapsed:,.0f}s", file=sys.stderr)


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


def cmd_add(a: argparse.Namespace) -> None:
    lb = Logbook.find()
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
        if p.is_dir():  # every file in it, in name order; hidden files are not exports
            for f in sorted(p.iterdir()):
                if f.is_file() and not f.name.startswith("."):
                    _add_file(lb, f)
        elif not _add_file(lb, p):
            ok = False
    if not ok:
        sys.exit(2)


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
    config = adapter.configure(os.environ)
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
    since = a.since if a.since is not None else _read_state(state_path).get("since")
    seen: dict[str, Any] = {
        "count": 0,
        "first": None,
        "last": None,
        "watermark": None,
        "provenance": Counter(),
    }
    counts: dict[str, int] = {}
    drafts = _watch(
        adapter.pull(config, since, progress=_page_progress, counts=counts), adapter.watermark, seen
    )
    try:
        if a.dry_run:
            for _ in drafts:
                pass
        else:
            n = lb.append_many(drafts)  # the page lines above are the progress; one stream, not two
    except OSError as e:  # urllib's errors are OSErrors; what was pulled before is already checkpointed
        print(f"sync: {a.name}: {e}", file=sys.stderr)
        sys.exit(1)
    where = f"since {since}" if since else "from the beginning"
    pending = counts.get("pending", 0)
    if a.dry_run:
        print(f"{a.name}: {seen['count']} lines {where} (dry run, nothing written)")
        if seen["count"]:
            print(f"  first {seen['first']}  last {seen['last']}  watermark {seen['watermark'] or '-'}")
            for provenance, count in sorted(seen["provenance"].items()):
                print(f"  {provenance}: {count}")
        _report_pending(pending)
        return
    if seen["watermark"] is not None:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({"since": seen["watermark"]}, indent=2) + "\n", encoding="utf-8")
    print(
        f"{a.name}: {n} new lines of {seen['count']} seen {where}; "
        f"watermark {seen['watermark'] or since or '-'}"
    )
    _report_pending(pending)


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
    in time order (then chain order for the same instant). Senders, attendees and unnamed group
    chats are shown by the names the record's own resolution lines give them (RFC 0006), built
    once per call; `--raw` prints the refs as the sources gave them. Nothing is written."""
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
    else the direct chat's own name, else the ref as given; the group is its name, else the
    label of its id (a `provider_id` ref), else the id. Raw (`names` None): the ref, the id."""
    chat = p.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    direct = chat.get("type") == "direct"
    chat_name = str(chat.get("name") or "")
    if p.get("from_me"):
        who = "me"
    elif names is None:
        who = _ref_value(p.get("sender"))
    else:
        who = _name(p.get("sender"), names) or (chat_name if direct else "") or _ref_value(p.get("sender"))
    if direct:
        prefix = f"{who} → {chat_name or chat_id}" if who == "me" else who
    elif names is None:
        prefix = f"{who} in {chat_id}"
    else:
        prefix = f"{who} in {chat_name or names.get(('provider_id', chat_id)) or chat_id}"
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
    s.add_argument("what", nargs="+")
    s.add_argument("--at", help="RFC3339 UTC, default now")
    s.set_defaults(fn=cmd_add)
    s = sub.add_parser("sync", help="pull new items from a live source (immich); safe to re-run")
    s.add_argument("name", help="the source, e.g. immich")
    s.add_argument("--since", metavar="RFC3339", help="pull from here instead of the stored watermark")
    s.add_argument("--dry-run", action="store_true", help="show what would be appended; write nothing")
    s.set_defaults(fn=cmd_sync)
    s = sub.add_parser("retract", help="take back line SEQ with a new line; nothing is rewritten")
    s.add_argument("seq", type=int)
    s.add_argument("reason")
    s.set_defaults(fn=cmd_retract)
    s = sub.add_parser("show", help="one day (default today)")
    s.add_argument("day", nargs="?")
    s.add_argument("--raw", action="store_true", help="print refs as the sources gave them, never a name")
    s.set_defaults(fn=cmd_show)
    s = sub.add_parser("index", help="rebuild index.sqlite from the files (readers do it when needed)")
    s.set_defaults(fn=cmd_index)
    s = sub.add_parser("verify", help="check the chain")
    s.add_argument("--root", help="logbook folder (default: find)")
    s.add_argument("--expect", help="expected.json with seq and head (conformance)")
    s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("export", help="the whole log as one .jsonl, or one day-package/v1 per day")
    s.add_argument("path", nargs="?", help=".jsonl file for the whole log")
    s.add_argument("--day", metavar="YYYY-MM-DD", help="one day-package/v1 directory")
    s.add_argument("--days", nargs=2, metavar=("FROM", "TO"), help="one directory per day, inclusive")
    s.add_argument("--out", metavar="DIR", help="where to write (default <root>/export/<date>/)")
    s.add_argument("--empty", action="store_true", help="with --days: also write days with no entries")
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
