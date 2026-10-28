"""What leaves the record: `export`, `import` (a trip bundle), `share`, `receive` and `circle`."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..contrib import letter, notion_export, site, trip_bundle, vault, world, world_chart
from ..core import crossing, day_start, flights, policy, sealing, share, stays
from ..core.chain import Line, is_sealed
from ..core.export import day_packages, day_range, parse_day, write_package
from ..core.store import Logbook, UnsortedFile, now_utc, uuid7
from .common import ARROW, EN_DASH, Subparsers, _airports, _plural


def export_arguments(sub: Subparsers) -> None:
    """`logbook export`."""
    s = sub.add_parser(
        "export",
        help=".jsonl, days, crossing, vault, site, world, trip-bundle, share day",
        description="the whole log as one .jsonl, one day-package/v1 per day, `crossing`: a"
        " crossing-package/v1, `notion FOLDER`: the record's facts for the owner's Notion, as a crossing,"
        " `vault FOLDER`: Markdown pages with wikilinks for Obsidian or Logseq, `site FOLDER`: the"
        " readers as static HTML, `world`: one page with the globe (or the chart, `--style chart`), the"
        " places, the assets and a time scrubber, `trip-bundle TRIP`: one trip for a member of the circle,"
        " `letter FROM TO`: a range of signed days read back, to print or hand to someone, or `share day"
        " YYYY-MM-DD --to NAME`: one day as a signed page",
    )
    s.add_argument(
        "path",
        nargs="?",
        help=".jsonl file for the whole log, `crossing` (RFC 0005), `notion` (docs/export-notion.md),"
        " `vault` (docs/vault.md),"
        " `site` (docs/site.md), `world` (docs/world.md), `trip-bundle` (RFC 0030) or `share day` (RFC 0025)",
    )
    s.add_argument(
        "target",
        nargs="?",
        metavar="FOLDER|TRIP|day",
        help="notion: the folder to write, replaced whole; vault: the folder to write the pages into (an"
        " Obsidian vault); site: the folder to write"
        " the HTML into; trip-bundle: the trip id as `show trips` prints it, or a day inside it; share:"
        " the word `day`",
    )
    s.add_argument("shared_day", nargs="?", metavar="YYYY-MM-DD", help="share day: the local day")
    s.add_argument("--day", metavar="YYYY-MM-DD", help="one day-package/v1 directory")
    s.add_argument("--days", nargs=2, metavar=("FROM", "TO"), help="one directory per day, inclusive")
    s.add_argument(
        "--out",
        metavar="DIR",
        help="where to write (default <root>/export/<date>/); share: the zip (default"
        " <root>/export/share/<to>/<date>.zip); world: the folder for world.html (default"
        " <root>/export/world/); letter: the folder (default <root>/export/letter/<FROM>_<TO>_<unit>/)",
    )
    s.add_argument("--empty", action="store_true", help="with --days: also write days with no entries")
    s.add_argument(
        "--to",
        metavar="DESTINATION",
        help="crossing: the circle member, e.g. hermes; share: the member as policy/crossing.json names them;"
        " world: the last day, YYYY-MM-DD (default: the record's); letter: the person it is for",
    )
    s.add_argument(
        "--from",
        dest="from_day",
        metavar="YYYY-MM-DD",
        help="world: the first day (default: the record's)",
    )
    s.add_argument(
        "--since",
        metavar="RFC3339|last|DAY",
        help="crossing: window start, or the last window's end; vault, notion: the first day (default: the"
        " record's)",
    )
    s.add_argument(
        "--until",
        metavar="RFC3339|DAY",
        help="crossing: window end, exclusive (default now); vault: the last day, inclusive (default: the"
        " record's)",
    )
    s.add_argument(
        "--tier",
        metavar="1|1,2|1,2,3",
        help="crossing: tiers to cross (default 1); --day, --days: 1, 1,2, 1,2,3 or a bare 2 or 3, never"
        " above the folder entry's ceiling (default: up to it, tier 1 without an entry); vault, site: 1 or"
        " 1,2, never 3; share: the highest tier to share (default 1; never above the ceiling); world: 1, 1,2"
        " or 1,2,3 (default 1,2, under the ceiling); letter: up to the letter entry's ceiling, tier 3 only"
        " when typed",
    )
    s.add_argument("--kinds", metavar="a,b", help="crossing: only these kinds")
    s.add_argument(
        "--dry-run",
        action="store_true",
        help="crossing, trip-bundle, notion, letter: count and show the policy; write nothing",
    )
    s.add_argument(
        "--attachments",
        action="store_true",
        help="trip-bundle: copy the photos' files into the bundle (default: their hashes only)",
    )
    s.add_argument(
        "--airports",
        metavar="FILE",
        help=f"trip-bundle, site, world: a CSV that adds to the airports table (else {flights.AIRPORTS_ENV})",
    )
    s.add_argument(
        "--with-drafts",
        action="store_true",
        help="site: put a model's drafts (pencil) on the Day pages, each headed with its model (default:"
        " left out)",
    )
    s.add_argument(
        "--style",
        choices=world_chart.STYLES,
        help="world: modern, the globe (default), or chart, the record on a period chart (docs/world.md)",
    )
    s.add_argument(
        "--chart",
        metavar="FILE",
        help="world: your own chart, a PNG or JPEG, as the paper of --style chart (with --control-points"
        " and --chart-credit); read from disk, carried in the page",
    )
    s.add_argument(
        "--control-points",
        metavar="FILE",
        help='world --chart: {"points": [{"x", "y", "lat", "lon", "name"}, …]}, three or more pixels of the'
        " image tied to positions",
    )
    s.add_argument(
        "--chart-credit",
        metavar="TEXT",
        help="world --chart: the chart's source in your words, for the legend",
    )
    s.add_argument(
        "--journey",
        action="append",
        metavar="ID",
        help="world: the page of one journey, a trip as `show trips` prints it (trip:FIRST:LAST, or a day"
        " inside it) or a journey/v1 line's id; again for another page",
    )
    s.add_argument(
        "--open",
        action="store_true",
        help="crossing: ship sealed lines and files opened, for a destination the policy gives no recipient",
    )
    s.add_argument(
        "--sealed",
        action="store_true",
        help="whole log: write sealed lines verbatim (default: opened, the form a line re-enters by)",
    )
    s.add_argument(
        "--unsigned",
        action="store_true",
        help="crossing, letter: take the unsigned days too (default: signed days only; RFC 0034)",
    )
    s.add_argument(
        "--all-mail",
        action="store_true",
        help="crossing: every mail the tiers and signed days let through, not people's mail only (RFC 0045)",
    )
    s.add_argument(
        "--include-unsigned",
        action="store_true",
        help="notion: the facts of unsigned days too, when the policy's notion entry allows it"
        " (default: signed days only)",
    )
    s.add_argument(
        "--force",
        action="store_true",
        help="crossing, trip-bundle, notion, letter: replace an --out (notion: FOLDER) that is not an earlier"
        " bundle, and all in it",
    )
    s.add_argument(
        "--unit",
        choices=letter.UNITS,
        help="letter: a page per day (default), week, month or journey",
    )
    s.add_argument("--title", metavar="TEXT", help="letter: the title on its front page")
    s.add_argument("--front", metavar="FILE", help="letter: the front page, in your words, as written")
    s.add_argument("--paper", choices=tuple(letter.PAPERS), help="letter: a5 (default) or letter")
    s.add_argument(
        "--card", action="store_true", help="letter --unit month: the month card, one page a month"
    )
    s.set_defaults(fn=cmd_export)


SHARE = "share"  # `export share day`: the command `share day` until 0.6
FOLDER = "folder"  # `export --day`/`--days`: the crossing line's destination, a folder the owner names
LETTER_ONLY = (
    ("--unit", "unit"),
    ("--title", "title"),
    ("--front", "front"),
    ("--paper", "paper"),
    ("--card", "card"),
)


def cmd_export(a: argparse.Namespace) -> None:
    if a.with_drafts and a.path != site.DESTINATION:
        print(f"export {a.path}: --with-drafts goes with `export site`", file=sys.stderr)
        sys.exit(2)
    given = [flag for flag, dest in LETTER_ONLY if getattr(a, dest, None)]
    if given and a.path != letter.DESTINATION:
        what = f"export {a.path}" if a.path else "export"
        print(
            f"{what}: {given[0]} is the letter's, `logbook export letter FROM TO {given[0]} …`;"
            " no other export takes it",
            file=sys.stderr,
        )
        sys.exit(2)
    if a.path == SHARE:
        if a.target != "day" or a.shared_day is None:
            print("export share: `export share day YYYY-MM-DD --to NAME` hands one day over", file=sys.stderr)
            sys.exit(2)
        if not a.to:
            print("export share day: --to NAME, the circle member, is needed", file=sys.stderr)
            sys.exit(2)
        a.day = a.shared_day
        cmd_share(a)
        return
    if a.path == letter.DESTINATION:
        _export_letter(a)
        return
    if a.shared_day is not None:
        print(f"export: {a.path!r} takes one argument, not {a.shared_day!r}", file=sys.stderr)
        sys.exit(2)
    lb = Logbook.find()
    if a.path == crossing.KIND:
        _export_crossing(lb, a)
        return
    if a.path == notion_export.DESTINATION:
        _export_notion(lb, a)
        return
    if a.path == vault.DESTINATION:
        _export_vault(lb, a)
        return
    if a.path == site.DESTINATION:
        _export_site(lb, a)
        return
    if a.path == world.DESTINATION:
        _export_world(lb, a)
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
    opener = None if a.sealed else _export_opener(lb)
    try:
        n = _write_lines(lb.lines(), out, opener)
        if n is None:  # a month file not in seq order (not one this code wrote): the sorted read
            n = _write_lines(lb._lines_by_seq(), out, opener)
    except sealing.IdentityRequired:
        out.unlink(missing_ok=True)
        raise
    how = "sealed lines verbatim" if a.sealed else "sealed lines opened for re-entry"
    print(f"exported {n} lines to {out} ({how}) — verify with: logbook verify")


def _export_opener(lb: Logbook) -> Callable[[Line], Line]:
    """`export` writes every line with its real payload (ADR 0017: the interchange form a line
    re-enters the record by), so a sealed line needs the identity; `--sealed` is the other way."""

    def opened(line: Line) -> Line:
        if is_sealed(line) and not lb.identities:
            raise sealing.IdentityRequired(
                "export writes opened payloads unless --sealed, and this record has sealed lines; "
                f"no identity at {lb.identity_file}"
            )
        return lb.opened(line)

    return opened


def _write_lines(
    lines: Iterator[Line], out: Path, opener: Callable[[Line], Line] | None = None
) -> int | None:
    """Stream `lines` to `out` as JSON lines, one in memory at a time, each through `opener` when
    one is given; the count, or None when the files turned out to need the sorted read (the
    caller starts the file over)."""
    n = 0
    with out.open("w", encoding="utf-8") as fh:
        try:
            for line in lines:
                if opener is not None:
                    line = opener(line)
                fh.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
                n += 1
        except UnsortedFile:
            return None
    return n


def _export_days(lb: Logbook, a: argparse.Namespace) -> None:
    """--day DATE [--out DIR] [--tier N|1,2|1,2,3]: one package at DIR (default <root>/export/DATE).
    --days FROM TO [--out DIR] [--empty] [--tier …]: one package per day at DIR/DATE (default
    <root>/export/DATE). A package holds the lines up to the ceiling of the policy's `folder` entry, tier
    1 when there is none (ADR 0016, ADR 0026); `--tier` may lower it, never raise it. The run leaves one
    crossing/v1 line (RFC 0011) naming the folder, as every export does."""
    try:
        ceiling = policy.folder_ceiling(lb.root)
        tiers = (
            _folder_tiers(a.tier, ceiling)
            if a.tier is not None
            else crossing.TIER_SETS.get(",".join(str(t) for t in range(1, ceiling + 1)), ())
        )
        if not tiers or max(tiers) > ceiling:
            asked = a.tier if a.tier is not None else "1"
            allows = (
                f"allows max_tier {ceiling}{policy.expiry_note(lb.root, FOLDER)}"
                if _folder_entry(lb.root)
                else f"names no {FOLDER!r} entry, so the default, max_tier {ceiling}, applies"
            )
            raise crossing.CrossingError(
                f"--tier {asked} is above the ceiling for {FOLDER!r}: {policy.policy_path(lb.root)} {allows};"
                f' write {{"{FOLDER}": {{"max_tier": {max(tiers or (1,))}}}}} in it to let that tier leave'
            )
        if a.day:
            days = [parse_day(a.day).isoformat()]
            dirs = [Path(a.out).expanduser() if a.out else lb.root / "export" / a.day]
            folder = dirs[0]
        else:
            days = day_range(*a.days)
            base = Path(a.out).expanduser() if a.out else lb.root / "export"
            dirs = [base / d for d in days]
            folder = base
    except (ValueError, crossing.CrossingError, policy.PolicyError) as e:
        print(f"export: {e}", file=sys.stderr)
        sys.exit(2)
    generated_at = now_utc()  # the packages' `generated_at` and the crossing line's `at`
    written: dict[str, bytes] = {}  # the folder's files by their path inside it, as written
    logged: list[dict[str, Any]] = []
    crossed: list[dict[str, Any]] = []
    packages = day_packages(lb, days, generated_at)  # one read of the log for the whole range
    for day, out in zip(days, dirs, strict=True):
        package = packages[day]
        logged += package["entries"]
        package["entries"] = [e for e in package["entries"] if e["tier"] in tiers]
        n = len(package["entries"])
        if a.days and not a.empty and n == 0:
            continue
        written[day if a.days else "package.json"] = write_package(package, out)
        crossed += package["entries"]
        print(f"{day}: {n} entries → {out}")
    if a.days:
        print(f"wrote {len(written)} day package(s)")
    if not written:  # no folder written, nothing left: no line says it did
        print("  nothing was written, so nothing is recorded")
        return
    files = {(f"{key}/package.json" if a.days else key): raw for key, raw in written.items()}
    found = list(written) if a.days else days
    line = _record_folder(lb, folder, found, days, tiers, ceiling, logged, crossed, files, generated_at)
    line_said = f"#{line['seq']} {crossing.LINE_SCHEMA}"
    print(
        f"  recorded as {line_said}: the folder {folder.name!r}, tier {','.join(map(str, tiers))},"
        f" {_plural(len(crossed), 'line')}"
    )


def _folder_entry(root: Path) -> bool:
    """Whether `policy/crossing.json` names the `folder` entry (`policy.folder_ceiling` read it already)."""
    return FOLDER in policy.read(root)


def _folder_policy(root: Path, ceiling: int) -> dict[str, Any]:
    """The crossing line's `policy`: the `folder` entry by name and its ceiling, or no entry and the
    default tier that applied in its place."""
    file = policy.POLICY_FILE.as_posix()
    if _folder_entry(root):
        return {"file": file, "entry": FOLDER, "max_tier": ceiling}
    return {"file": file, "entry": None, "default_tier": ceiling}


def _record_folder(
    lb: Logbook,
    folder: Path,
    written_days: list[str],
    days: list[str],
    tiers: tuple[int, ...],
    ceiling: int,
    logged: list[dict[str, Any]],
    crossed: list[dict[str, Any]],
    files: dict[str, bytes],
    generated_at: str,
) -> Line:
    """The crossing/v1 line (RFC 0011) a folder of day packages leaves, after it is written: destination
    `folder`, the window of the days asked for, the tiers, the counts (per tier and kind, of the lines that
    crossed), the folder's last part, the days written and the kinds, never a path of this machine. The
    digest is the folder's, as `export vault` hashes one: each file's sha256 and path, in path order. The
    ceiling is the policy's `folder` entry's, recorded by name with its `max_tier`; without one the line
    says so, `"entry": null`, and the `default_tier` that applied (`policy.folder_ceiling`), never a
    `max_tier` no policy set."""
    bounds = day_start.of(lb.meta)
    since, until = bounds.span(days[0])[0], bounds.span(days[-1])[1]
    head = str(lb.meta["head"])  # the head the packages reflect: the one before this line
    by_kind = Counter(str(e["kind"]) for e in crossed)
    return lb.append(
        at=generated_at,
        source=crossing.SOURCE,
        kind=crossing.KIND,
        tier=1,
        payload={
            "schema": crossing.LINE_SCHEMA,
            "destination": FOLDER,
            "bundle_id": uuid7(),
            "window": {"from": _utc_text(since), "to": _utc_text(until)},
            "tiers": list(tiers),
            "counts": {
                "logged": len(logged),
                "crossed": len(crossed),
                "held_back": len(logged) - len(crossed),
                "by_tier": {str(t): sum(1 for e in crossed if e["tier"] == t) for t in tiers},
                "by_kind": dict(sorted(by_kind.items())),
                "resolutions": 0,
                "resolutions_held_back": 0,
                "attachments": {"included": 0, "bytes": 0, "missing": 0},
            },
            "policy": _folder_policy(lb.root, ceiling),
            "logbook_head": head,
            "package_sha256": vault.digest(files),
            "extra": {
                "folder": folder.name,
                "days": written_days,
                "kinds": sorted(by_kind),
                "lines": len(crossed),
            },
        },
        recorded_at=generated_at,
    )


def _folder_tiers(text: str, ceiling: int) -> tuple[int, ...]:
    """`--tier` for a folder: `1`, `1,2` or `1,2,3` as `export crossing` takes it, or a bare `2` or `3`,
    every tier up to it. The ceiling is checked by the caller, so a tier above it is refused naming the
    entry, never read as another value."""
    if text.strip() in ("2", "3"):
        return tuple(range(1, int(text) + 1))
    return crossing.parse_tiers(text)


def _utc_text(instant: datetime) -> str:
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _export_crossing(lb: Logbook, a: argparse.Namespace) -> None:
    """crossing --to DEST --since RFC3339|last [--until RFC3339] [--tier 1|1,2|1,2,3] [--kinds a,b]
    [--unsigned] [--all-mail] [--out DIR] [--force] [--dry-run]: one crossing-package/v1 (RFC 0005)
    under the destination's ceiling in policy/crossing.json (ADR 0016), the lines of signed days unless
    `--unsigned` (RFC 0034), people's mail only unless `--all-mail` (RFC 0045), recorded as a
    crossing/v1 line (RFC 0011). The bundle replaces DIR whole; a DIR that is not an earlier bundle is
    refused unless `--force` (docs/crossing.md)."""
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
            open_sealed=a.open,
            signed_only=not a.unsigned,
            all_mail=a.all_mail,
        )
    except crossing.EmptyWindow as e:
        print(f"{a.to}: {e}; nothing written")
        return
    except crossing.CrossingError as e:
        print(f"export crossing: {e}", file=sys.stderr)
        sys.exit(2)
    out = Path(a.out).expanduser() if a.out else crossing.default_out(lb, req.destination, generated_at)
    try:
        sel = crossing.select(lb, req)
    except crossing.CrossingError as e:  # sealed lines with no recipient and no --open, or no identity
        print(f"export crossing: {e}", file=sys.stderr)
        sys.exit(2)
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
        crossing.check_target(out, a.force, lb.root)  # before the policy file or anything else is written
    except crossing.CrossingError as e:
        print(f"export crossing: {e}", file=sys.stderr)
        sys.exit(2)
    try:
        result = crossing.export(lb, req, sel, out, generated_at, force=a.force)
    except (crossing.CrossingError, OSError) as e:
        print(f"export crossing: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"{req.destination}: {sel.counts()['crossed']} lines crossed, {window}, tiers {tiers} → {out}")
    for text in _crossing_rows(sel):
        print(text)
    if sel.sealed:
        how = f"resealed to {req.recipient}" if req.recipient else "opened (--open)"
        print(f"  sealed: {_plural(len(sel.sealed), 'line')} {how}")
    review = result.manifest.get("review")
    if review is not None:
        print(f"  review: {len(review)} tier-2 line(s) listed in {crossing.MANIFEST_FILE}")
    if req.tier3:
        _tier3_warning(req, sel)
    seq, digest = result.line["seq"], result.package_sha256[:12]
    print(f"  recorded as #{seq} {crossing.LINE_SCHEMA}, package sha256 {digest}…; watermark {req.until}")


def _export_notion(lb: Logbook, a: argparse.Namespace) -> None:
    """notion FOLDER [--since DAY] [--include-unsigned] [--force] [--dry-run]: the record's facts for the
    owner's Notion (`logbook/contrib/notion_export.py`): persons, ideas and orgs, each by the key Notion
    matches on, under the `notion` entry of policy/crossing.json (ADR 0016), signed days only unless
    the entry and the flag both lift it (RFC 0034), recorded as a crossing/v1 line (RFC 0011). The
    folder replaces FOLDER whole (docs/crossing.md); nothing is asked of or created in Notion."""
    try:
        if not a.target:
            raise notion_export.NotionError("export notion needs a folder: logbook export notion <folder>")
        crossing_only = (
            ("--until", a.until),
            ("--tier", a.tier),
            ("--unsigned", a.unsigned),
            ("--out", a.out),
            ("--to", a.to),
            ("--from", a.from_day),
            ("--kinds", a.kinds),
            ("--open", a.open),
            ("--attachments", a.attachments),
            ("--sealed", a.sealed),
            ("--empty", a.empty),
            ("--day", a.day),
            ("--days", a.days),
        )
        unused = [flag for flag, given in crossing_only if given]
        if unused:
            raise notion_export.NotionError(
                f"export notion takes no {unused[0]}: FOLDER is where it writes, the window ends now, the"
                " tiers are the notion entry's, and --include-unsigned lifts the signed-day gate when the"
                " entry allows it"
            )
        req = notion_export.request(lb, a.since, include_unsigned=a.include_unsigned)
        out = Path(a.target).expanduser()
        if a.dry_run:
            built = notion_export.build(lb, req, _airports(a.airports))
            print(f"dry run: {notion_export.describe(req)}; nothing written")
            entry = req.entry
            print(f"  policy: {policy.policy_path(lb.root)} {entry.destination} max_tier {entry.max_tier}")
            for text in notion_export.rows(req, built):
                print(text)
            try:
                notion_export.check_target(lb, out, a.force)
            except notion_export.NotionError as e:
                print(f"  a real run would be refused: {e}")
            return
        built, result = notion_export.export(lb, req, out, force=a.force, airports=_airports(a.airports))
    except (ValueError, stays.SettingsError) as e:  # NotionError, and a policy file a reader refuses
        print(f"export notion: {e}", file=sys.stderr)
        sys.exit(2)
    except OSError as e:
        print(f"export notion: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"{notion_export.describe(req)} {ARROW} {out}")
    for text in notion_export.rows(req, built):
        print(text)
    seq, digest = result.line["seq"], result.package_sha256[:12]
    print(f"  recorded as #{seq} {crossing.LINE_SCHEMA}, manifest sha256 {digest}…; nothing sent to Notion")


def _export_letter(a: argparse.Namespace) -> None:
    """letter FROM TO [--unit day|journey|week|month] [--card] [--title TEXT] [--front FILE] [--to NAME]
    [--paper a5|letter] [--tier 1|1,2|1,2,3] [--unsigned] [--out DIR] [--force] [--dry-run]: a range of
    signed days read back as one HTML file and the same as Markdown (`logbook/contrib/letter.py`), under
    the `letter` entry of policy/crossing.json (ADR 0016), recorded as a crossing/v1 line (RFC 0011)."""
    try:
        if a.target is None or a.shared_day is None:
            raise letter.LetterError("export letter takes two days, FROM TO: logbook export letter FROM TO")
        unused = [
            flag
            for flag, given in (
                ("--day", a.day),
                ("--days", a.days),
                ("--since", a.since),
                ("--until", a.until),
                ("--from", a.from_day),
                ("--kinds", a.kinds),
                ("--sealed", a.sealed),
                ("--open", a.open),
                ("--empty", a.empty),
                ("--include-unsigned", a.include_unsigned),
            )
            if given
        ]
        if unused:
            raise letter.LetterError(f"export letter takes no {unused[0]}: FROM TO is its range")
        lb = Logbook.find()
        req = letter.request(
            lb,
            a.target,
            a.shared_day,
            unit=a.unit,
            tiers=a.tier,
            unsigned=a.unsigned,
            to=a.to,
            title=a.title,
            front=a.front,
            paper=a.paper,
            card=a.card,
        )
        out = Path(a.out).expanduser() if a.out else letter.default_out(lb, req)
        if a.dry_run:
            built = letter.build(lb, req, _airports(a.airports))
            print(f"dry run: {letter.describe(req)}; nothing written")
            print(
                f"  policy: {policy.policy_path(lb.root)} {letter.DESTINATION} max_tier {req.entry.max_tier}"
            )
            for text in letter.rows(req, built):
                print(text)
            return
        built, result = letter.export(lb, req, out, force=a.force, airports=_airports(a.airports))
    except (ValueError, stays.SettingsError) as e:  # LetterError, and a policy file a reader refuses
        print(f"export letter: {e}", file=sys.stderr)
        sys.exit(2)
    except OSError as e:
        print(f"export letter: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"{letter.describe(req)} {ARROW} {out}")
    for text in letter.rows(req, built):
        print(text)
    seq, digest = result.line["seq"], result.package_sha256[:12]
    print(f"  recorded as #{seq} {crossing.LINE_SCHEMA}, manifest sha256 {digest}…")


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


def _export_site(lb: Logbook, a: argparse.Namespace) -> None:
    """site FOLDER [--tier 1|1,2] [--with-drafts]: the readers as a folder of static HTML
    (`logbook/contrib/site.py`): a Year page per year, a Day page per pick, every Trip page, a Days index
    per year, the places and the people, with relative links, no script and nothing fetched; tier-gated
    under the `site` ceiling in policy/crossing.json (ADR 0016; tier 1 when the file does not name it),
    a model's drafts left out unless `--with-drafts`, recorded as a crossing/v1 line (RFC 0011). Only
    the files whose content changed are rewritten."""
    generated_at = now_utc()
    try:
        if not a.target:
            raise site.SiteError("export site needs a folder: logbook export site <folder>")
        req = site.request(lb, site.parse_tiers("1" if a.tier is None else a.tier), drafts=a.with_drafts)
    except site.SiteError as e:
        print(f"export site: {e}", file=sys.stderr)
        sys.exit(2)
    folder = Path(a.target).expanduser()
    if req is None:
        print("site: the record has no day; nothing written, nothing appended")
        return
    try:
        built = site.build(lb, req, _airports(a.airports))
        result = site.export(lb, req, built, folder, generated_at)
    except (site.SiteError, stays.SettingsError, OSError) as e:
        print(f"export site: {e}", file=sys.stderr)
        sys.exit(2)
    tiers = ",".join(map(str, req.tiers))
    window = f"{req.since} {EN_DASH} {req.until}"
    drafts = "a model's drafts included" if req.drafts else "drafts left out"
    print(f"site: {_plural(built.years, 'year')} {window}, tier {tiers}, {drafts} {ARROW} {folder}")
    pages = ", ".join(_plural(n, *site.PAGE_NOUNS[kind]) for kind, n in built.pages.items())
    print(f"  pages: {pages}; {result.written} written, {result.unchanged} unchanged")
    if built.held_back:
        by_kind = ", ".join(f"{kind} {n}" for kind, n in built.held_by_kind.items())
        print(f"  held back: {_plural(built.held_back, 'line')} above tier {max(req.tiers)} ({by_kind})")
    for warning in built.warnings:
        print(f"  {warning}")
    seq, sha = result.line["seq"], result.sha256[:12]
    print(f"  recorded as #{seq} {crossing.LINE_SCHEMA}, site sha256 {sha}…")


def _export_world(lb: Logbook, a: argparse.Namespace) -> None:
    """world [--out DIR] [--from DAY] [--to DAY] [--tier 1|1,2|1,2,3] [--style modern|chart] [--chart
    FILE --control-points FILE --chart-credit TEXT] [--journey ID]…: one self-contained HTML page,
    the globe (or the chart) with the places, the assets on their tracks, the stays, the journeys and
    a time scrubber (`logbook/contrib/world.py`), tier-gated under the `world` ceiling in
    policy/crossing.json (ADR 0016; tier 2 when the file does not name it), recorded as a crossing/v1
    line (RFC 0011); with `--journey`, one page per journey, each its own line. A page is rewritten
    only when its content changed. The chart and its points are read and the fit checked before any
    page is written."""
    generated_at = now_utc()
    asked = a.chart or a.control_points or a.chart_credit
    style = a.style or (world_chart.CHART if asked else world_chart.MODERN)
    paper = None
    try:
        if a.target:
            raise world.WorldError(f"export world takes no folder but --out DIR, not {a.target!r}")
        tiers = None if a.tier is None else world.parse_tiers(a.tier)
        if style == world_chart.MODERN and asked:
            raise world.WorldError("--chart, --control-points and --chart-credit draw on --style chart")
        if a.journey and (a.from_day or a.to):
            raise world.WorldError("--journey sets the page's days; give --journey or --from and --to")
        if style == world_chart.CHART:
            paper = world_chart.paper(
                Path(a.chart).expanduser() if a.chart else None,
                Path(a.control_points).expanduser() if a.control_points else None,
                a.chart_credit,
            )
        airports = _airports(a.airports)
        if a.journey:
            asked_for = list(dict.fromkeys(text.strip() for text in a.journey))  # one page each, once
            reqs = [world.journey_request(lb, text, tiers, airports) for text in asked_for]
        else:
            found = world.request(lb, a.from_day, a.to, tiers)
            reqs = [] if found is None else [found]
    except (world.WorldError, world_chart.ChartError) as e:
        print(f"export world: {e}", file=sys.stderr)
        sys.exit(2)
    if not reqs:
        print("world: the record has no day; nothing written, nothing appended")
        return
    folder = Path(a.out).expanduser() if a.out else world.default_out(lb)
    try:
        pages = [
            world.build(lb, req, airports, style, paper) for req in reqs
        ]  # every page, before any is written
    except (world.WorldError, stays.SettingsError) as e:
        print(f"export world: {e}", file=sys.stderr)
        sys.exit(2)
    for req, built in zip(reqs, pages, strict=True):
        try:
            result = world.export(lb, built, folder, generated_at)
        except OSError as e:
            print(f"export world: {e}", file=sys.stderr)
            sys.exit(2)
        for text in world.console(built, result):
            print(text)
        if 3 in req.tiers:
            lines = _plural(built.by_tier["3"], "tier-3 line")
            text = f"WARNING: {crossing.TIER3_WARNING}: {lines} of the window"
            print(text)
            print(text, file=sys.stderr)


def _export_trip_bundle(lb: Logbook, a: argparse.Namespace) -> None:
    """trip-bundle <trip-id-or-day> --to DEST [--tier 1|1,2|1,2,3] [--attachments] [--out DIR]
    [--force] [--dry-run]: one crossing package cut to the trip (RFC 0030, profile trip-bundle/v1)
    under the destination's ceiling in policy/crossing.json, recorded as a crossing/v1 line naming
    the trip. It replaces DIR as a crossing does (docs/crossing.md)."""
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
        crossing.check_target(out, a.force, lb.root)
    except crossing.CrossingError as e:
        print(f"export trip-bundle: {e}", file=sys.stderr)
        sys.exit(2)
    try:
        result = trip_bundle.export(lb, prepared, out, generated_at, force=a.force)
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
    """`logbook import backup|trip-bundle|page|inbox|attachments|pickup`: what a phone backup, another
    record, a friend or the receiving side hands over. `backup`, `inbox`, `attachments` and `pickup`
    are declared beside `add`, the family that reads the files; `page` beside `share`, its other side."""
    from .add import attach_arguments, import_backup_arguments, inbox_arguments, pickup_arguments

    s = sub.add_parser(
        "import",
        help="an iOS backup, a trip bundle, a page, a pickup; inbox; attachments",
        description="an iOS backup (`backup DIR`), a trip bundle (`trip-bundle FOLDER`), a shared page"
        " (`page FILE`) or a folder of transcripts collected from the receiving side (`pickup FOLDER`)"
        " brought in; `inbox`: what was imported; `attachments`: the store",
    )
    verbs = s.add_subparsers(dest="what", required=True, metavar="<what>")
    import_backup_arguments(verbs)
    v = verbs.add_parser(
        trip_bundle.COMMAND,
        help="a trip bundle another record exported (RFC 0030): its lines appended as received",
    )
    v.add_argument("path", metavar="FOLDER", help="the bundle: manifest.json, entries.jsonl, trip.json, …")
    v.add_argument("--dry-run", action="store_true", help="count what would be received; write nothing")
    v.set_defaults(fn=cmd_import)
    receive_arguments(verbs)
    inbox_arguments(verbs)
    attach_arguments(verbs)
    pickup_arguments(verbs)


def cmd_import(a: argparse.Namespace) -> None:
    """`import trip-bundle <folder> [--dry-run]`: a bundle another record exported (RFC 0030), its
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
    if c.get("held_back_by_entry"):
        yield (
            f"  {c['held_back_by_entry']} draft(s) held back: the entry they were written under (the"
            " 'dream' entry, a person's the 'relationship' entry) no longer allows their tier"
        )
    if c.get("mail_held_back"):
        yield (
            f"  {c['mail_held_back']} mail(s) held back: no person the record names is on them"
            " (--all-mail sends them)"
        )
    if c["held_back_unsigned"]:
        yield (
            f"  {c['held_back_unsigned']} held back on unsigned days"
            " (`logbook day sign YYYY-MM-DD` signs one; --unsigned crosses them anyway)"
        )
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
    """`export share day YYYY-MM-DD --to NAME [--tier 1|2|3] [--out FILE]` (`share day` until 0.6):
    one local day as a signed page
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
    """`logbook import page` (`logbook receive` until 0.6)."""
    s = sub.add_parser(
        "page", help="verify a page someone shared and keep it beside the record, never in the chain"
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
    """`logbook key circle [add NAME KEY | key]` (`logbook circle` until 0.6)."""
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
