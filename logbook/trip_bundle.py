"""The shared trip (RFC 0025): `logbook export trip-bundle`, `logbook import trip-bundle`, and the
merged page `logbook trip` shows once a bundle has come in.

**Out.** A trip bundle is a crossing package (RFC 0005, `crossing-package/v1`) with a profile,
`trip-bundle/v1`, cut to one trip: the lines of the trip's days a reader of a trip needs, verbatim —
the `photo/v1` lines (their hashes; the pixels only with `--attachments`) and the standing `flight/v1`
lines — plus `trip.json`, a `trip-share/v1` page of the derived rows the sender's record gives the
trip (ADR 0019: a circle page shares derived rows, never a trip line): the stays away from home with
their nights and labels, the moves between them, the flights, and the people confirmed present with
the refs that name them; and `resolution.jsonl`, the resolution lines (RFC 0006) those refs walk
through, so the recipient can name the same people. The home stay, the location points, the notes,
the calendar entries and everything else of those days stay home. The ceiling is the destination's in
`policy/crossing.json` (ADR 0016) and the tiers are what `--tier` asks: the people rows and the overlay
are tier 2 — a name is a resolution's work — so with the default `--tier 1` the bundle carries the
places and the photos and says how many names it held back. Every real export appends one
`crossing/v1` line (RFC 0011) naming the trip.

**In.** `import trip-bundle` reads such a bundle from another record, checks every digest the
manifest names and every line's own hash, and appends each line as a **received** line: kind
`received`, source `received`, the sender's line verbatim under `payload.line`, `extra.from` the
sender's owner id. A received line is never one of the record's own: no derived reader takes the kind,
so the sender's photos are nobody's photos here and the sender's resolutions name nobody here. A line
whose `raw_id` the record already holds — as its own (the same shared photo, the same invite) or
received before — is skipped and counted, never written twice. The page goes in as one received line
of schema `trip-share/v1`, keyed by the bundle id. Nothing is ever rewritten.

**The merged page.** `logbook trip <id>` reads the received pages whose trip overlaps this one and
shows, per sender, who was there according to each record (the sender's people matched to this
record's through the refs they share, else by name; the owner is `you`), the places the records agree
on (a stay of theirs within `AGREE_M` of a stay of yours), and a `seen only by` column for what one
record has and the other does not. The page compares; it confirms nobody and writes nothing."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from . import crossing, policy, present, stays, trip_page, trips
from .chain import Line, compute_hash
from .flights import Airports
from .places import distance_m
from .reading import Reading
from .resolve import Ref, standing, walk
from .store import Logbook, retractions, uuid7

COMMAND = "trip-bundle"  # `export trip-bundle`, `import trip-bundle`
PROFILE = "trip-bundle/v1"  # the manifest's `profile`: a crossing package cut to one trip
SCHEMA = "trip-share/v1"  # `trip.json`, and the received page line
TRIP_FILE = "trip.json"
RECEIVED = "received"  # the kind and the source of a line that came from another record
RECEIVED_SCHEMA = "received/v1"  # a received line: the sender's line verbatim under `line`
PAGE_RAW_ID = "trip-share:"  # + the bundle id: the received page's dedupe key
KINDS = frozenset({"photo", "flight"})  # the kinds of line a bundle carries
NAMING_TIER = 2  # the people rows and the overlay cross only when this tier is asked for
AGREE_M = 300.0  # a stay of theirs this close to a stay of yours is the same place
DOT = " · "
EN_DASH = "\u2013"


class BundleError(ValueError):
    """A bundle that is not one, does not verify, or is the record's own; the message names it."""


def _dict(obj: object) -> dict[str, Any]:
    """`obj` when it is an object, else nothing: a payload field read without trusting its shape."""
    return obj if isinstance(obj, dict) else {}


# -- out ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Prepared:
    """One export, resolved and selected, before anything is written: what `--dry-run` reports."""

    request: crossing.Request
    selection: crossing.Selection
    share: dict[str, Any]
    trip: trips.Trip
    sender: dict[str, Any]
    attachments: bool  # the photos' files were asked for


@dataclass(frozen=True)
class Export:
    out: Path
    manifest: dict[str, Any]
    package_sha256: str
    line: Line  # the crossing/v1 line appended


def prepare(
    lb: Logbook,
    ref_text: str,
    destination: str,
    tiers: tuple[int, ...],
    airports: Airports | None = None,
    attachments: bool = False,
) -> Prepared:
    """Find the trip (`trip_page.locate`: `ValueError` when there is none on that day or under
    that id), hold the request against the policy (`crossing.request`: `CrossingError` above the
    ceiling or for a destination the file does not name), and select what crosses. Reads only."""
    rd, trip = trip_page.locate(lb, trip_page.parse_ref(ref_text), airports)
    since, until = window_of(rd, trip)
    req = crossing.request(lb, destination, since, until, tiers, KINDS)
    people = people_of(rd, trip)
    sel = select(lb, rd, trip, req, people, attachments)
    sender = sender_of(lb, req.tiers)
    share = share_of(rd, trip, req, sel, people, sender)
    return Prepared(req, sel, share, trip, sender, attachments)


def window_of(rd: Reading, trip: trips.Trip) -> tuple[str, str]:
    """The trip's days as a crossing window: from the first day's local midnight to the end of
    the return day, in UTC."""
    start = datetime.combine(date.fromisoformat(trip.start), datetime.min.time(), tzinfo=rd.tz)
    end = datetime.combine(
        date.fromisoformat(trip.until) + timedelta(days=1), datetime.min.time(), tzinfo=rd.tz
    )
    return stays.instant_text(start.astimezone(UTC)), stays.instant_text(end.astimezone(UTC))


def away_stays(rd: Reading, trip: trips.Trip) -> list[stays.Segment]:
    """The owner's stays of the trip that are not at home (`trips.visited_stays` less the home
    stays either side): nothing of home crosses."""
    return [s for s in trips.visited_stays(rd, trip.start, trip.until) if not stays.is_home(s, rd.places)]


def people_of(rd: Reading, trip: trips.Trip) -> list[dict[str, Any]]:
    """The people confirmed present at the trip's stays away (the with module, SPEC §3.2.5), each
    with the refs that name them: the refs of their evidence, and every ref the record resolves to
    the same person, so the recipient can match them to its own people by an address rather than
    by a spelling."""
    away = away_stays(rd, trip)
    evidence = [
        p
        for stay in away
        for p in present.present(stay, rd.lines, rd.identities, rd.places, rd.owner)
        if p.status == present.CONFIRMED
    ]
    rows = []
    for c in trips.companions(away, rd):
        refs: set[Ref] = set()
        for p in evidence:
            same = (
                (p.person == c.person)
                if c.person
                else (p.person is None and p.name.casefold() == c.name.casefold())
            )
            if same and p.ref is not None:
                refs.add(p.ref)
        if c.person:
            refs |= {ref for ref, who in rd.identities.items() if who.entity == c.person}
        rows.append(
            {
                "person": c.person,
                "name": c.name,
                "status": c.status,
                "sources": list(c.sources),
                "refs": [{"kind": kind, "value": value} for kind, value in sorted(refs)],
                "lines": list(c.lines),
            }
        )
    return rows


def select(
    lb: Logbook,
    rd: Reading,
    trip: trips.Trip,
    req: crossing.Request,
    people: Sequence[Mapping[str, Any]],
    attachments: bool,
) -> crossing.Selection:
    """What crosses: the standing `photo/v1` lines of the window and the trip's standing flights, in
    the requested tiers, in chain order; the resolution lines the photos' people and the people rows
    walk through, those above the requested tiers held back and counted; the photos' files only with
    `attachments`."""
    since, until = crossing.instant(req.since), crossing.instant(req.until)
    with lb.index() as idx:
        retraction_lines = idx.retractions()
        retracted = retractions(retraction_lines)
        inside = [
            p
            for p in idx.window(req.since, req.until)
            if p.kind == "photo" and since <= crossing.instant(p.at) < until and p.id not in retracted
        ]
        photos = idx.read((p.file, p.offset) for p in inside if p.tier in req.tiers)
        flight_ids = list(dict.fromkeys(id_ for f in trip.flights for id_ in f["lines"]))
        found = idx.by_ids(flight_ids)
        last = standing([*retraction_lines, *idx.resolutions()])
    flights = [found[id_] for id_ in flight_ids if id_ in found]
    lines = sorted(
        [*photos, *[f for f in flights if int(f["tier"]) in req.tiers]], key=lambda line: int(line["seq"])
    )
    logged = len(inside) + len(flights)
    refs: set[Ref] = set()
    for line in lines:
        refs.update(crossing.refs(line.get("payload")))
        refs.update(_photo_refs(line))
    for row in people:
        refs.update((str(r["kind"]), str(r["value"])) for r in row["refs"])
    overlay, held = _overlay(refs, last, req.tiers)
    blobs, missing = crossing.blobs(lb, lines) if attachments else ([], 0)
    return crossing.Selection(lines, logged, overlay, held, blobs, missing)


def _photo_refs(line: Line) -> set[Ref]:
    """The refs a photo line's `people` make (RFC 0002: the library's ids): `provider_id`
    `<library>:<id>`, as the with module resolves them."""
    payload = line.get("payload") or {}
    if line.get("kind") != "photo":
        return set()
    library = str(payload.get("library") or line.get("source") or "")
    people = payload.get("people")
    return {
        ("provider_id", f"{library}:{p}")
        for p in (people if isinstance(people, list) else [])
        if isinstance(p, str) and p
    }


def _overlay(refs: Iterable[Ref], last: dict[Ref, Line], tiers: tuple[int, ...]) -> tuple[list[Line], int]:
    """Every resolution line standing the refs walk through, alias hops included, once each in chain
    order; a line above the requested tiers stays home and is counted (ADR 0016 rule 5)."""
    found: dict[str, Line] = {}
    for ref in sorted(set(refs)):
        for hop in walk(ref, last):
            found[str(hop["id"])] = hop
    ordered = sorted(found.values(), key=lambda line: int(line["seq"]))
    crossing_lines = [line for line in ordered if int(line["tier"]) in tiers]
    return crossing_lines, len(ordered) - len(crossing_lines)


def sender_of(lb: Logbook, tiers: tuple[int, ...]) -> dict[str, Any]:
    """Who the bundle is from, in the sender's own words: the owner id, the first name of
    `policy/owner.json` (else the id), and, when tier 2 crosses, the owner's addresses and numbers
    from `owner.json` and `logbook.json`, so the recipient can match the sender to one of its own
    people by a ref."""
    aliases = policy.owner_aliases(lb.root)
    owner_id = str(lb.meta.get("owner_id") or "")
    names = aliases.get("names") or []
    refs: list[dict[str, str]] = []
    if NAMING_TIER in tiers:
        emails = [
            *(str(e) for e in lb.meta.get("owner_emails") or [] if isinstance(e, str)),
            *aliases.get("emails", []),
        ]
        refs += [{"kind": "email", "value": e} for e in dict.fromkeys(emails)]
        refs += [{"kind": "phone", "value": p} for p in dict.fromkeys(aliases.get("phones", []))]
    return {"id": owner_id, "name": names[0] if names else owner_id, "refs": refs}


def share_of(
    rd: Reading,
    trip: trips.Trip,
    req: crossing.Request,
    sel: crossing.Selection,
    people: Sequence[Mapping[str, Any]],
    sender: Mapping[str, Any],
) -> dict[str, Any]:
    """`trip.json`: the trip as the sender's readers derive it — the stays away with their nights
    and the label the route gives them, the moves of the span, the flights, the people (when tier 2
    crosses; else held back and counted), the photo lines that crossed — and the sender."""
    first = datetime.combine(date.fromisoformat(trip.start), datetime.min.time(), tzinfo=rd.tz)
    last = datetime.combine(date.fromisoformat(trip.until), datetime.max.time(), tzinfo=rd.tz)
    nights_at: Counter[str] = Counter()
    for night in rd.nights:
        if trip.start <= night.day <= trip.end:
            nights_at.update({s.id for s in (night.stay, night.innermost) if s is not None})
    stay_rows = []
    for stay in away_stays(rd, trip):
        row = stay.to_json(rd.tz)
        row.pop("inside", None)
        row["label"] = (
            stay.place
            if stay.place
            else trips.coordinates_label(stay.lat, stay.lon, rd.places, rd.airports)
            if stay.lat is not None and stay.lon is not None
            else "unknown"
        )
        row["nights"] = nights_at.get(stay.id, 0)
        stay_rows.append(row)
    moves = [
        m.to_json(rd.tz)
        for m in rd.segments
        if m.subject is None and m.kind == stays.MOVE and m.start < last and m.end > first
    ]
    named = NAMING_TIER in req.tiers
    photos = [str(line["id"]) for line in sel.lines if line.get("kind") == "photo"]
    tier = max([1, *(int(line["tier"]) for line in sel.lines), *([NAMING_TIER] if named and people else [])])
    return {
        "schema": SCHEMA,
        "trip": {
            "id": trip.id,
            "start": trip.start,
            "end": trip.end,
            "until": trip.until,
            "nights": trip.nights,
            "in_transit": trip.in_transit,
            "route": list(trip.route),
        },
        "sender": dict(sender),
        "stays": stay_rows,
        "moves": moves,
        "flights": [dict(f) for f in trip.flights],
        "people": [dict(p) for p in people] if named else [],
        "photos": {"count": len(photos), "lines": photos},
        "held_back": {
            "people": 0 if named else len(people),
            "lines": sel.held_back,
            "resolutions": sel.resolutions_held_back,
        },
        "tiers": list(req.tiers),
        "tier": tier,
    }


def export(lb: Logbook, prepared: Prepared, out: Path, generated_at: str) -> Export:
    """Write the bundle — `trip.json`, then RFC 0005's files with the manifest last — and append the
    crossing line, in that order, so a crash leaves at worst a bundle no line names. The watermark
    of `export crossing` is not moved: a trip is not a delta window."""
    policy.write_default(lb.root)
    req, sel = prepared.request, prepared.selection
    head = str(lb.meta["head"])
    bundle_id = uuid7()
    manifest = crossing.build_manifest(lb, req, sel, generated_at, bundle_id, head)
    manifest["profile"] = PROFILE
    manifest["timezone"] = str(lb.meta.get("timezone") or "")
    manifest["trip"] = {k: prepared.share["trip"][k] for k in ("id", "start", "end", "until")}
    manifest["sender"] = dict(prepared.sender)
    manifest["attachments_included"] = prepared.attachments
    manifest["trip_file"] = TRIP_FILE
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(prepared.share, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    (out / TRIP_FILE).write_bytes(raw)
    manifest["trip_sha256"] = hashlib.sha256(raw).hexdigest()
    package_sha256 = crossing.write_bundle(lb, sel, manifest, out)
    line = crossing.record(
        lb,
        req,
        sel,
        generated_at,
        bundle_id,
        head,
        package_sha256,
        {"trip": prepared.trip.id, "profile": PROFILE},
    )
    return Export(out, manifest, package_sha256, line)


def default_out(lb: Logbook, destination: str, generated_at: str) -> Path:
    """`<root>/export/trip-bundle/<destination>/<generated_at, compact>`: one folder per run."""
    stamp = generated_at.replace("-", "").replace(":", "")
    return lb.root / "export" / COMMAND / destination / stamp


# -- in ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Bundle:
    folder: Path
    manifest: dict[str, Any]
    package_sha256: str
    entries: list[Line]
    overlay: list[Line]
    share: dict[str, Any]


@dataclass
class Report:
    sender: dict[str, Any]
    trip: dict[str, Any]
    bundle_id: str
    received: int = 0  # entry lines written
    resolutions: int = 0  # overlay lines written
    kept_own: int = 0  # skipped: the record holds the raw_id as its own line
    received_before: int = 0  # skipped: received already
    attachments: int = 0  # files put in the store
    attachments_missing: int = 0  # files the manifest names that are not in the bundle, or do not hash
    page: bool = False  # the page line written
    page_before: bool = False


def read_bundle(folder: Path) -> Bundle:
    """The bundle at `folder`, every digest the manifest names checked and every line's own hash
    recomputed; `BundleError` for anything else (RFC 0005: provenance is the manifest's digests and
    each line's hash, since a subset cannot replay the chain)."""
    folder = Path(folder)
    manifest_file = folder / crossing.MANIFEST_FILE
    if not manifest_file.is_file():
        raise BundleError(f"{folder} has no {crossing.MANIFEST_FILE}: not a trip bundle")
    raw = manifest_file.read_bytes()
    try:
        manifest = json.loads(raw)
    except ValueError as e:
        raise BundleError(f"{manifest_file} is not JSON: {e}") from e
    if not isinstance(manifest, dict) or manifest.get("schema") != crossing.SCHEMA:
        raise BundleError(f"{manifest_file} is not a {crossing.SCHEMA} manifest")
    if manifest.get("profile") != PROFILE:
        raise BundleError(
            f"{manifest_file} is a {manifest.get('profile') or 'plain'} crossing package, not {PROFILE}"
        )
    entries = _checked_lines(
        folder, str(manifest.get("entries_file") or crossing.ENTRIES_FILE), manifest.get("entries_sha256")
    )
    overlay = (
        _checked_lines(folder, str(manifest["resolution_file"]), manifest.get("resolution_sha256"))
        if manifest.get("resolution_file")
        else []
    )
    share_file = folder / str(manifest.get("trip_file") or TRIP_FILE)
    share_raw = _checked_bytes(share_file, manifest.get("trip_sha256"))
    try:
        share = json.loads(share_raw)
    except ValueError as e:
        raise BundleError(f"{share_file} is not JSON: {e}") from e
    if (
        not isinstance(share, dict)
        or share.get("schema") != SCHEMA
        or not isinstance(share.get("trip"), dict)
    ):
        raise BundleError(f"{share_file} is not a {SCHEMA} page")
    return Bundle(folder, manifest, hashlib.sha256(raw).hexdigest(), entries, overlay, share)


def _checked_bytes(file: Path, expected: object) -> bytes:
    if not file.is_file():
        raise BundleError(f"{file} is missing from the bundle")
    raw = file.read_bytes()
    if not isinstance(expected, str) or hashlib.sha256(raw).hexdigest() != expected:
        raise BundleError(
            f"{file} does not match its digest in the manifest; the bundle is not what was sent"
        )
    return raw


def _checked_lines(folder: Path, name: str, expected: object) -> list[Line]:
    file = folder / name
    lines: list[Line] = []
    for n, text in enumerate(_checked_bytes(file, expected).decode("utf-8").splitlines(), 1):
        if not text.strip():
            continue
        try:
            line = json.loads(text)
        except ValueError as e:
            raise BundleError(f"{file} line {n} is not JSON: {e}") from e
        if not isinstance(line, dict) or not all(
            k in line for k in ("id", "at", "kind", "tier", "payload", "hash")
        ):
            raise BundleError(f"{file} line {n} is not a log line")
        try:
            ok = compute_hash(line) == line["hash"]
        except (KeyError, TypeError, ValueError):
            ok = False
        if not ok:
            raise BundleError(f"{file} line {n} does not verify: its hash does not recompute")
        lines.append(line)
    return lines


def import_bundle(lb: Logbook, folder: Path, received_at: str, dry_run: bool = False) -> Report:
    """Read the bundle and append what the record does not hold yet, as received lines; with
    `dry_run`, count and write nothing. `BundleError` when the bundle does not verify or is this
    record's own export."""
    bundle = read_bundle(folder)
    manifest = bundle.manifest
    owner = str(manifest.get("owner") or "")
    if owner == str(lb.meta.get("owner_id") or ""):
        raise BundleError(
            f"{bundle.folder} is your own record's export; a trip bundle is received from another record"
        )
    given = _dict(manifest.get("sender"))
    sender = {"id": owner, "name": str(given.get("name") or owner), "refs": given.get("refs") or []}
    bundle_id = str(manifest.get("bundle_id") or bundle.package_sha256)
    extra = {
        "from": owner,
        "sender": sender["name"],
        "bundle_id": bundle_id,
        "logbook_head": manifest.get("logbook_head"),
        "package_sha256": bundle.package_sha256,
        "received_at": received_at,
    }
    report = Report(sender, dict(bundle.share["trip"]), bundle_id)
    wrapped = [_wrap(line, owner, extra) for line in [*bundle.entries, *bundle.overlay]]
    page = _page(bundle, extra)
    with lb.index() as idx:
        holders = idx.holders([str(d["payload"]["raw_id"]) for d in [*wrapped, page]])
    drafts = []
    for draft in wrapped:
        sources = holders.get(str(draft["payload"]["raw_id"]))
        if sources is None:
            drafts.append(draft)
            if draft["payload"]["line"]["kind"] == "resolution":
                report.resolutions += 1
            else:
                report.received += 1
        elif sources - {RECEIVED}:
            report.kept_own += 1
        else:
            report.received_before += 1
    if holders.get(str(page["payload"]["raw_id"])):
        report.page_before = True
    else:
        drafts.append(page)
        report.page = True
    for blob in manifest.get("blobs") or []:
        if not isinstance(blob, dict) or not isinstance(blob.get("sha256"), str):
            continue
        file = bundle.folder / crossing.ATTACHMENTS_DIR / blob["sha256"]
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != blob["sha256"]:
            report.attachments_missing += 1
            continue
        if not dry_run:
            lb.attach_file(file)
        report.attachments += 1
    if not dry_run and drafts:
        lb.append_many(drafts)
    return report


def _wrap(line: Line, owner: str, extra: Mapping[str, Any]) -> dict[str, Any]:
    """A received line: the sender's line verbatim under `line`, its `raw_id` the sender's (else
    one made of the sender and the line's id), the envelope's `at`, `end`, `tz` and `tier` the
    inner line's, so it lands on its day at its tier."""
    payload = line.get("payload") or {}
    raw_id = payload.get("raw_id") if isinstance(payload, dict) else None
    key = raw_id if isinstance(raw_id, str) and raw_id else f"{RECEIVED}:{owner}:{line['id']}"
    draft: dict[str, Any] = {
        "at": str(line["at"]),
        "end": line.get("end"),
        "source": RECEIVED,
        "kind": RECEIVED,
        "tier": int(line["tier"]),
        "payload": {"schema": RECEIVED_SCHEMA, "raw_id": key, "line": line, "extra": dict(extra)},
    }
    if isinstance(line.get("tz"), str) and line["tz"]:
        draft["tz"] = line["tz"]
    return draft


def _page(bundle: Bundle, extra: Mapping[str, Any]) -> dict[str, Any]:
    """The received page: `trip.json` as one line, keyed by the bundle id, from the first day's
    midnight to the end of the return day in the sender's zone (the manifest's window)."""
    share = {k: v for k, v in bundle.share.items() if k != "schema"}
    covers = _dict(bundle.manifest.get("covers"))
    tier = share.get("tier")
    draft: dict[str, Any] = {
        "at": str(covers.get("from") or f"{share['trip']['start']}T00:00:00Z"),
        "end": covers.get("to") if isinstance(covers.get("to"), str) else None,
        "source": RECEIVED,
        "kind": RECEIVED,
        "tier": tier if tier in policy.TIERS else NAMING_TIER,
        "payload": {
            "schema": SCHEMA,
            "raw_id": f"{PAGE_RAW_ID}{extra['bundle_id']}",
            **share,
            "extra": dict(extra),
        },
    }
    zone = bundle.manifest.get("timezone")
    if isinstance(zone, str) and zone:
        draft["tz"] = zone
    return draft


# -- the merged page ----------------------------------------------------------------------------------------


def shares(
    lb: Logbook,
    rd: Reading,
    trip: trips.Trip,
    route: Sequence[Mapping[str, Any]],
    confirmed: Sequence[present.Companion],
) -> list[dict[str, Any]]:
    """The received pages whose trip touches this one, each compared with this record: `people`,
    `places`, the sender's flights and how many of their photos came in. Pages are found by their
    raw_id prefix through the index; a retracted page is out."""
    with lb.index() as idx:
        pages = idx.of_source(RECEIVED, RECEIVED, "", "9999-12-31", PAGE_RAW_ID)
        photos = [
            line
            for line in idx.of_source(RECEIVED, RECEIVED, trip.start, trip.until)
            if _dict(line.get("payload")).get("schema") == RECEIVED_SCHEMA
            and _dict(_dict(line.get("payload")).get("line")).get("kind") == "photo"
        ]
    out = []
    for line in pages:
        payload = _dict(line.get("payload"))
        their = _dict(payload.get("trip"))
        if str(line["id"]) in rd.retracted or payload.get("schema") != SCHEMA:
            continue
        if not (str(their.get("start") or "") <= trip.until and str(their.get("until") or "") >= trip.start):
            continue
        out.append(_share(line, rd, route, confirmed, photos))
    return out


def _share(
    line: Line,
    rd: Reading,
    route: Sequence[Mapping[str, Any]],
    confirmed: Sequence[present.Companion],
    photos: Sequence[Line],
) -> dict[str, Any]:
    payload = _dict(line.get("payload"))
    extra = _dict(payload.get("extra"))
    sender = _dict(payload.get("sender"))
    who = {
        "id": str(extra.get("from") or sender.get("id") or ""),
        "name": str(extra.get("sender") or sender.get("name") or "another record"),
    }
    bundle_id = str(extra.get("bundle_id") or "")
    their = _dict(payload.get("trip"))
    return {
        "from": who,
        "bundle_id": bundle_id,
        "received_at": extra.get("received_at"),
        "logbook_head": extra.get("logbook_head"),
        "line": str(line["id"]),
        "trip": {k: their.get(k) for k in ("id", "start", "end", "until", "nights", "in_transit", "route")},
        "people": _people_rows(rd, confirmed, who["name"], sender, payload.get("people") or []),
        "places": _place_rows(route, payload.get("stays") or [], who["name"]),
        "flights": list(payload.get("flights") or []),
        "photos": sum(
            1 for p in photos if _dict(_dict(p.get("payload")).get("extra")).get("bundle_id") == bundle_id
        ),
    }


def _normal(name: object) -> str:
    return " ".join(str(name or "").split()).casefold()


def _refs_of(row: Mapping[str, Any]) -> set[Ref]:
    refs = row.get("refs")
    return {
        (str(r["kind"]), str(r["value"]))
        for r in (refs if isinstance(refs, list) else [])
        if isinstance(r, dict) and r.get("kind") and r.get("value")
    }


def _people_rows(
    rd: Reading,
    confirmed: Sequence[present.Companion],
    sender_name: str,
    sender: Mapping[str, Any],
    theirs: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Who was there according to each record: `you` and this record's confirmed people on one
    side, the sender and their confirmed people on the other, matched through a shared ref (one
    of the owner's, or one this record resolves to a person), else by name; the rest is seen by
    one record only."""
    by_entity = {c.person: c for c in confirmed if c.person}
    by_name = {_normal(c.name): c for c in confirmed}

    def match(row: Mapping[str, Any]) -> str | present.Companion | None:
        refs = _refs_of(row)
        name = _normal(row.get("name"))
        if refs & rd.owner.refs or name in rd.owner.names:
            return "you"
        for ref in sorted(refs):
            who = rd.identities.get(ref)
            if who is not None and who.entity and who.entity in by_entity:
                return by_entity[who.entity]
        return by_name.get(name)

    their_rows: list[tuple[Mapping[str, Any], str]] = [
        ({"name": sender_name, "refs": sender.get("refs") or []}, "owner"),
        *(
            (row, f"confirmed ({', '.join(str(s) for s in row.get('sources') or [])})".replace(" ()", ""))
            for row in theirs
        ),
    ]
    matched: dict[str, str] = {}  # own key → the sender's word for them
    unmatched: list[tuple[Mapping[str, Any], str]] = []
    for row, word in their_rows:
        found = match(row)
        if found == "you":
            matched.setdefault("you", word)
        elif isinstance(found, present.Companion):
            matched.setdefault(found.person or _normal(found.name), word)
        else:
            unmatched.append((row, word))
    rows = [_people_row("you", None, "owner", matched.get("you"), sender_name)]
    for c in confirmed:
        yours = f"confirmed ({', '.join(c.sources)})"
        rows.append(
            _people_row(c.name, c.person, yours, matched.get(c.person or _normal(c.name)), sender_name)
        )
    for row, word in unmatched:
        rows.append(_people_row(str(row.get("name") or "?"), None, None, word, sender_name))
    return rows


def _people_row(
    name: str, person: str | None, yours: str | None, theirs: str | None, sender: str
) -> dict[str, Any]:
    only = None if yours and theirs else "you" if yours else sender
    return {"name": name, "person": person, "yours": yours, "theirs": theirs, "seen_only_by": only}


def _place_rows(
    route: Sequence[Mapping[str, Any]], theirs: Sequence[Mapping[str, Any]], sender: str
) -> list[dict[str, Any]]:
    """The places the records agree on: each located stay of this trip's route with the sender's
    stays within `AGREE_M` of it, then the sender's stays that match none."""
    located = [
        s
        for s in theirs
        if isinstance(s, dict)
        and isinstance(s.get("lat"), int | float)
        and isinstance(s.get("lon"), int | float)
    ]
    used: set[int] = set()
    rows = []
    for s in route:
        if s.get("lat") is None or s.get("lon") is None:
            continue
        near = [
            (n, t)
            for n, t in enumerate(located)
            if distance_m(float(s["lat"]), float(s["lon"]), float(t["lat"]), float(t["lon"])) <= AGREE_M
        ]
        used.update(n for n, _t in near)
        labels = list(dict.fromkeys(str(t.get("label") or t.get("place") or "?") for _n, t in near))
        nights = sum(int(t.get("nights") or 0) for _n, t in near)
        rows.append(
            {
                "label": str(s["label"]),
                "nights": int(s.get("nights") or 0),
                "lat": s["lat"],
                "lon": s["lon"],
                "theirs": ", ".join(labels) or None,
                "their_nights": nights if near else None,
                "seen_only_by": None if near else "you",
            }
        )
    for n, t in enumerate(located):
        if n in used:
            continue
        rows.append(
            {
                "label": None,
                "nights": None,
                "lat": t["lat"],
                "lon": t["lon"],
                "theirs": str(t.get("label") or t.get("place") or "?"),
                "their_nights": int(t.get("nights") or 0),
                "seen_only_by": sender,
            }
        )
    return rows


# -- text -------------------------------------------------------------------------------------------------


def rows(share: Mapping[str, Any]) -> list[str]:
    """One share as text: a header line, then the people and the places as two small tables with a
    `seen only by` column."""
    their = share["trip"]
    nights = their.get("nights")
    head = [
        f"their {their.get('id')}",
        f"{nights} night" + ("" if nights == 1 else "s"),
        f"received {str(share.get('received_at') or '')[:10]}".rstrip(),
        f"{share['photos']} photo" + ("" if share["photos"] == 1 else "s"),
    ]
    out = [f"  shared with {share['from']['name']}{DOT}{DOT.join(head)}"]
    people = share["people"]
    name_w = max([3, *(len(str(p["name"])) for p in people)])
    yours_w = max([5, *(len(str(p["yours"] or EN_DASH)) for p in people)])
    theirs_w = max([6, *(len(str(p["theirs"] or EN_DASH)) for p in people)])
    out.append(f"    {'who':<{name_w}}  {'yours':<{yours_w}}  {'theirs':<{theirs_w}}  seen only by")
    for p in people:
        yours, theirs = p["yours"] or EN_DASH, p["theirs"] or EN_DASH
        row = (
            f"    {p['name']:<{name_w}}  {yours:<{yours_w}}  {theirs:<{theirs_w}}  {p['seen_only_by'] or ''}"
        )
        out.append(row.rstrip())
    places = share["places"]
    if places:
        mine = [_place_text(p["label"], p["nights"]) for p in places]
        theirs_all = [_place_text(p["theirs"], p["their_nights"]) for p in places]
        mine_w = max([5, *(len(t) for t in mine)])
        theirs_w = max([6, *(len(t) for t in theirs_all)])
        out.append(f"    {'where':<{mine_w}}  {'theirs':<{theirs_w}}  seen only by")
        for p, yours, theirs in zip(places, mine, theirs_all, strict=True):
            out.append(f"    {yours:<{mine_w}}  {theirs:<{theirs_w}}  {p['seen_only_by'] or ''}".rstrip())
    return out


def _place_text(label: object, nights: object) -> str:
    if label is None:
        return EN_DASH
    if not nights:
        return str(label)
    return f"{label}, {nights} night" + ("" if nights == 1 else "s")


def text(line: Line, render: Callable[[Line], str]) -> str:
    """A received line as `show` prints it: `from <sender>: <kind> <source> · <the line as it would
    read>`, the inner line rendered by `render`; a page as its trip and counts."""
    payload = _dict(line.get("payload"))
    extra = _dict(payload.get("extra"))
    who = str(extra.get("sender") or extra.get("from") or "another record")
    inner = payload.get("line")
    if payload.get("schema") == RECEIVED_SCHEMA and isinstance(inner, dict):
        return f"from {who}: {inner.get('kind')} {inner.get('source')}{DOT}{render(inner)}"
    if payload.get("schema") == SCHEMA:
        their = _dict(payload.get("trip"))
        n_stays, n_people = len(payload.get("stays") or []), len(payload.get("people") or [])
        n_photos = _dict(payload.get("photos")).get("count", 0)
        return f"from {who}: trip {their.get('id')}{DOT}{n_stays} stays, {n_people} people, {n_photos} photos"
    return f"from {who}"
