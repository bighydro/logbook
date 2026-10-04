"""What leaves the record: `export`, `import` (a trip bundle), `share`, `receive` and `circle`."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from pathlib import Path

from ..contrib import trip_bundle, vault
from ..core import crossing, flights, policy, share, stays
from ..core.chain import Line
from ..core.export import day_packages, day_range, parse_day, write_package
from ..core.store import Logbook, UnsortedFile, now_utc
from .common import ARROW, EN_DASH, Subparsers, _airports, _plural


def export_arguments(sub: Subparsers) -> None:
    """`logbook export`."""
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
        " or `trip-bundle` (RFC 0025)",
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
    of Markdown pages with wikilinks (`logbook/contrib/vault.py`), tier-gated under the `vault` ceiling in
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
    [--dry-run]: one crossing package cut to the trip (RFC 0025, profile trip-bundle/v1) under the
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


def import_arguments(sub: Subparsers) -> None:
    """`logbook import`."""
    s = sub.add_parser(
        "import", help="a trip bundle another record exported (RFC 0025): its lines appended as received"
    )
    s.add_argument("what", choices=[trip_bundle.COMMAND], help="what the folder holds")
    s.add_argument("path", metavar="FOLDER", help="the bundle: manifest.json, entries.jsonl, trip.json, …")
    s.add_argument("--dry-run", action="store_true", help="count what would be received; write nothing")
    s.set_defaults(fn=cmd_import)


def cmd_import(a: argparse.Namespace) -> None:
    """`import trip-bundle <folder> [--dry-run]`: a bundle another record exported (RFC 0025), its
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


def share_arguments(sub: Subparsers) -> None:
    """`logbook share`."""
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


def cmd_share(a: argparse.Namespace) -> None:
    """`share day YYYY-MM-DD --to NAME [--tier 1|2|3] [--out FILE]`: one local day as a signed page
    for a member of the circle (RFC 0025, `logbook.core.share`): the day's lines at or under the tier,
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


def receive_arguments(sub: Subparsers) -> None:
    """`logbook receive`."""
    s = sub.add_parser(
        "receive", help="verify a page someone shared and keep it beside the record, never in the chain"
    )
    s.add_argument("file", metavar="FILE", help="the page, a zip")
    s.add_argument("--from", dest="sender", metavar="NAME", help="check against this circle member's key")
    s.set_defaults(fn=cmd_receive)


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


def circle_arguments(sub: Subparsers) -> None:
    """`logbook circle`."""
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
