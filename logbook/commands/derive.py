"""What the record derives from itself and may append: `derive stays`, `infer flights|keepers` and
`transcribe` (voice memos to transcript lines)."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator, Mapping
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .. import assets, flights, keepers, reading, stays, transcribe
from ..export import parse_day
from ..store import Logbook, _dedupe_key, retractions
from .common import EM_DASH, EN_DASH, Subparsers, _airports, _distance_text, _duration_text, _plural
from .skips import _report_skipped


def infer_arguments(sub: Subparsers) -> None:
    """`logbook infer`."""
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


def transcribe_arguments(sub: Subparsers) -> None:
    """`logbook transcribe`."""
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
            already = len(idx.existing({key for d in drafts if (key := _dedupe_key(d)) is not None}))
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


def derive_arguments(sub: Subparsers) -> None:
    """`logbook derive`."""
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
