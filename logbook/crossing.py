"""The crossing package: `logbook export crossing` (RFC 0005, `crossing-package/v1`).

A bundle for one named member of the owner's circle: the lines of a window `[since, until)` that
the tier policy lets cross, verbatim; copies of the attachments they point at that the store holds
(SPEC §1.1); the resolution lines their refs resolve through (RFC 0006), so the reader can name
people without the whole registry; and a manifest a JSON parser can read. The ceiling per
destination is a setting in the record, `policy/crossing.json` (ADR 0016), never a constant here.
Every real export is itself a line in the chain, `crossing/v1` (RFC 0011), and moves a watermark
per destination in `exports/crossing.json`. Nothing here rewrites a line; the only write to the
log is that one `Logbook.append`."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from . import __version__, attachments, policy, sealing
from .chain import Line, is_sealed
from .resolve import Ref, standing, walk
from .store import Logbook, retractions, utc, uuid7

SCHEMA = "crossing-package/v1"
LINE_SCHEMA = "crossing/v1"
KIND = "crossing"  # of the line a real export appends
SOURCE = "logbook"  # its source: the tool itself, not the owner and not an adapter
MANIFEST_FILE = "manifest.json"
ENTRIES_FILE = "entries.jsonl"
RESOLUTION_FILE = "resolution.jsonl"
OPEN_FIELD = "payload_open"  # a sealed line shipped opened: {payload, salt}, the digest's pre-image
ATTACHMENTS_DIR = "attachments"  # the SPEC §1.1 layout, so a verbatim `path` resolves in the bundle
WATERMARK_FILE = PurePosixPath("exports/crossing.json")
LAST = "last"  # `--since last`: from the watermark
TIER_SETS = {"1": (1,), "1,2": (1, 2), "1,2,3": (1, 2, 3)}
TIER3_WARNING = "TIER-3 CONTENT IS IN THIS PACKAGE"
DIGEST = re.compile(r"[0-9a-f]{64}")
REF_KINDS = frozenset({"email", "phone", "handle", "provider_id", "device_id", "domain", "line"})  # RFC 0006
COPY_CHUNK = 1 << 20


class CrossingError(ValueError):
    """A request the record or the policy refuses; the message says why and names the file."""


class EmptyWindow(Exception):
    """`since` equals `until`: nothing to cross, nothing to write, not an error (a nightly job may
    run twice in one second)."""


def parse_tiers(text: str) -> tuple[int, ...]:
    """`--tier 1`, `1,2` or `1,2,3`. Tier 3 is only ever here because the owner typed it."""
    key = ",".join(part.strip() for part in text.split(","))
    if key not in TIER_SETS:
        raise CrossingError(f"--tier must be 1, 1,2 or 1,2,3, not {text!r}")
    return TIER_SETS[key]


def parse_kinds(text: str | None) -> frozenset[str] | None:
    if text is None:
        return None
    kinds = frozenset(part.strip() for part in text.split(",") if part.strip())
    if not kinds:
        raise CrossingError("--kinds names no kind")
    return kinds


def instant(stamp: str) -> datetime:
    """An RFC3339 stamp as an aware UTC datetime; one with no zone is refused."""
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        raise CrossingError(f"{stamp!r} is not RFC3339, e.g. 2026-03-01T00:00:00Z") from None
    if parsed.tzinfo is None:
        raise CrossingError(f"{stamp!r} has no zone; use UTC, e.g. 2026-03-01T00:00:00Z")
    return parsed.astimezone(UTC)


@dataclass(frozen=True)
class Request:
    """One export, checked against the policy: the destination, the window, the tiers asked for
    and the ceiling in force. Built by `request`, which is the only place the policy is read."""

    destination: str
    since: str
    until: str
    tiers: tuple[int, ...]
    kinds: frozenset[str] | None
    max_tier: int
    recipient: str | None = None  # the destination's age recipient (policy), to reseal sealed lines to
    open_sealed: bool = False  # `--open`: ship sealed lines and files opened, when there is no recipient

    @property
    def tier3(self) -> bool:
        return 3 in self.tiers


def request(
    lb: Logbook,
    destination: str,
    since: str,
    until: str,
    tiers: tuple[int, ...],
    kinds: frozenset[str] | None = None,
    open_sealed: bool = False,
) -> Request:
    """Resolve `--since last`, check the window, and hold the request against the policy: a tier
    above the destination's ceiling is refused naming the policy file. Tier 3 is in `tiers` only
    when `--tier 1,2,3` was typed, so a policy edit alone never lets it cross (ADR 0016). The
    destination's recipient, when the policy names one, is what sealed lines are resealed to."""
    if since == LAST:
        since = last_until(lb, destination)
    since, until = utc(_checked(since)), utc(_checked(until))
    if instant(until) == instant(since):
        raise EmptyWindow(f"nothing to cross: the window is empty, --since {since} --until {until}")
    if instant(until) < instant(since):
        raise CrossingError(f"the window runs backwards: --since {since} --until {until}")
    try:
        max_tier = policy.ceiling(lb.root, destination)
        recipient = policy.recipient(lb.root, destination)
    except policy.PolicyError as e:
        raise CrossingError(str(e)) from e
    if max(tiers) > max_tier:
        raise CrossingError(
            f"--tier {','.join(map(str, tiers))} is above the ceiling for {destination!r}: "
            f"{policy.policy_path(lb.root)} allows max_tier {max_tier}; "
            "raise it there if that is what you want"
        )
    return Request(destination, since, until, tiers, kinds, max_tier, recipient, open_sealed)


def _checked(stamp: str) -> str:
    instant(stamp)
    return stamp


def last_until(lb: Logbook, destination: str) -> str:
    """The end of the last real export to `destination`, from the watermark file."""
    path = watermark_path(lb.root)
    marks = _read_marks(path)
    entry = marks.get(destination)
    if not isinstance(entry, dict) or not isinstance(entry.get("until"), str):
        raise CrossingError(
            f"no crossing to {destination!r} is recorded at {path}; "
            "give the first window explicitly: --since <RFC3339>"
        )
    return str(entry["until"])


def watermark_path(root: Path) -> Path:
    return Path(root).joinpath(*WATERMARK_FILE.parts)


def _read_marks(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


# -- selection: what crosses, read through the index --------------------------------------------


@dataclass
class Selection:
    """What one request selects from the record, before anything is written."""

    lines: list[Line]  # the entries, in chain order
    logged: int  # every line in the window, whatever its tier or kind
    resolutions: list[Line]  # the overlay: every line the entries' refs resolve through, by tier
    resolutions_held_back: int  # overlay lines above the requested tiers
    blobs: list[dict[str, Any]]  # SPEC §1.1 references whose file the store holds
    missing: int  # distinct digests referenced whose file the store does not hold
    sealed: dict[str, Line] = field(default_factory=dict)  # id → the line as the file holds it, when sealed

    @property
    def held_back(self) -> int:
        return self.logged - len(self.lines)

    @property
    def by_tier(self) -> dict[str, int]:
        found = Counter(int(line["tier"]) for line in self.lines)
        return {str(t): found.get(t, 0) for t in policy.TIERS}

    @property
    def by_kind(self) -> dict[str, int]:
        return dict(sorted(Counter(str(line["kind"]) for line in self.lines).items()))

    @property
    def attachment_bytes(self) -> int:
        return sum(int(b["bytes"]) for b in self.blobs)

    def counts(self) -> dict[str, Any]:
        return {
            "logged": self.logged,
            "crossed": len(self.lines),
            "held_back": self.held_back,
            "by_tier": self.by_tier,
            "by_kind": self.by_kind,
            "resolutions": len(self.resolutions),
            "resolutions_held_back": self.resolutions_held_back,
            "attachments": {
                "included": len(self.blobs),
                "bytes": self.attachment_bytes,
                "missing": self.missing,
            },
        }


def select(lb: Logbook, req: Request) -> Selection:
    """The lines of `[since, until)` in the requested tiers and kinds, not retracted, in chain
    order; the resolution lines their refs walk through; the attachments they reference. The
    index says where; only the lines that cross are read from the files."""
    since, until = instant(req.since), instant(req.until)
    with lb.index() as idx:
        inside = [p for p in idx.window(req.since, req.until) if since <= instant(p.at) < until]
        retraction_lines = idx.retractions()
        retracted = retractions(retraction_lines)
        wanted = [
            p
            for p in inside
            if p.tier in req.tiers and (req.kinds is None or p.kind in req.kinds) and p.id not in retracted
        ]
        raw = idx.read(((p.file, p.offset) for p in wanted), opened=False)
        raw_resolutions = idx.resolutions(opened=False)
    sealed = {str(line["id"]): line for line in [*raw, *raw_resolutions] if is_sealed(line)}
    if sealed:
        if not lb.identities:
            raise CrossingError(
                f"{len(sealed)} sealed line(s) are in the window and there is no identity at "
                f"{lb.identity_file} to open them with"
            )
        if req.recipient is None and not req.open_sealed:
            raise CrossingError(
                f"{req.destination!r} has no recipient in {policy.policy_path(lb.root)} and sealed lines "
                "are in the window: add one (RFC 0029 §7), or pass --open to ship them opened"
            )
    lines = [lb.opened(line) for line in raw]
    last = standing([*retraction_lines, *(lb.opened(line) for line in raw_resolutions)])
    overlay, held = _overlay(lines, last, req.tiers)
    found, missing = blobs(lb, lines)
    crossed = {str(line["id"]) for line in [*lines, *overlay]}
    carried = {k: v for k, v in sealed.items() if k in crossed}
    return Selection(lines, len(inside), overlay, held, found, missing, carried)


def _overlay(lines: list[Line], last: dict[Ref, Line], tiers: tuple[int, ...]) -> tuple[list[Line], int]:
    """Every resolution line standing that the lines' refs resolve through, alias hops included,
    once each in chain order; a line above the requested tiers stays home and is counted."""
    found: dict[str, Line] = {}
    for ref in sorted({ref for line in lines for ref in refs(line.get("payload"))}):
        for hop in walk(ref, last):
            found[str(hop["id"])] = hop
    ordered = sorted(found.values(), key=lambda line: int(line["seq"]))
    crossing = [line for line in ordered if int(line["tier"]) in tiers]
    return crossing, len(ordered) - len(crossing)


def refs(obj: object) -> Iterator[Ref]:
    """Every source-native ref `{kind, value}` (RFC 0006) anywhere in a payload."""
    if isinstance(obj, dict):
        kind, value = obj.get("kind"), obj.get("value")
        if isinstance(kind, str) and kind in REF_KINDS and isinstance(value, str) and value:
            yield kind, value
        for child in obj.values():
            yield from refs(child)
    elif isinstance(obj, list):
        for child in obj:
            yield from refs(child)


def blobs(lb: Logbook, lines: list[Line]) -> tuple[list[dict[str, Any]], int]:
    """The SPEC §1.1 references the lines carry whose file is in the store, once per digest in
    the manifest's shape, and how many digests the store does not hold (those stay references).
    The shared page (`share`) selects its attachments with this too."""
    store = lb.root / ATTACHMENTS_DIR
    present: dict[str, dict[str, Any]] = {}
    absent: set[str] = set()
    for line in lines:
        for ref in references(line.get("payload")):
            sha256 = str(ref["sha256"])
            if sha256 in present or sha256 in absent:
                continue
            file = store / sha256
            if file.is_file():
                media_type = ref.get("media_type")
                size = ref.get("bytes")  # the plaintext's length; the file may be sealed (RFC 0029 §7)
                known = isinstance(size, int) and not isinstance(size, bool)
                present[sha256] = {
                    "sha256": sha256,
                    "path": f"{ATTACHMENTS_DIR}/{sha256}",
                    "bytes": size if known else file.stat().st_size,
                    "media_type": media_type
                    if isinstance(media_type, str) and media_type
                    else "application/octet-stream",
                }
            else:
                absent.add(sha256)
    return [present[k] for k in sorted(present)], len(absent)


def references(obj: object) -> Iterator[dict[str, Any]]:
    """Every object with a `sha256` digest anywhere in a payload: a §1.1 reference, or an
    adapter's pre-attach hash (`extra.media`), which names the same bytes if the store has them."""
    if isinstance(obj, dict):
        sha256 = obj.get("sha256")
        if isinstance(sha256, str) and DIGEST.fullmatch(sha256):
            yield obj
        for child in obj.values():
            yield from references(child)
    elif isinstance(obj, list):
        for child in obj:
            yield from references(child)


# -- the bundle --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Result:
    out: Path
    manifest: dict[str, Any]
    package_sha256: str  # of manifest.json's bytes; the manifest names every other file's digest
    line: Line  # the crossing/v1 line appended


def export(lb: Logbook, req: Request, sel: Selection, out: Path, generated_at: str) -> Result:
    """Write the bundle, append the crossing line, move the watermark: in that order, so a crash
    leaves at worst a bundle no line names, and the next `--since last` covers the window again."""
    policy.write_default(lb.root)  # the first export writes the default; an existing file is kept
    head = str(lb.meta["head"])
    bundle_id = uuid7()
    manifest = build_manifest(lb, req, sel, generated_at, bundle_id, head)
    package_sha256 = write_bundle(lb, sel, manifest, out, req)
    line = record(lb, req, sel, generated_at, bundle_id, head, package_sha256)
    write_watermark(lb, req.destination, req.until, generated_at, bundle_id)
    return Result(out, manifest, package_sha256, line)


def record(
    lb: Logbook,
    req: Request,
    sel: Selection,
    generated_at: str,
    bundle_id: str,
    head: str,
    package_sha256: str,
    extra: dict[str, Any] | None = None,
) -> Line:
    """Append the one crossing/v1 line a real export leaves in the chain (RFC 0011, ADR 0016 rule
    4): the destination, the window, the tiers, the counts, the ceiling and the package digest;
    `extra` is what a particular package adds (a trip bundle names its trip). The only write to
    the log an export makes."""
    payload: dict[str, Any] = {
        "schema": LINE_SCHEMA,
        "destination": req.destination,
        "bundle_id": bundle_id,
        "window": {"from": req.since, "to": req.until},
        "tiers": list(req.tiers),
        "counts": sel.counts(),
        "policy": {"file": policy.POLICY_FILE.as_posix(), "max_tier": req.max_tier},
        "logbook_head": head,
        "package_sha256": package_sha256,
    }
    if extra:
        payload["extra"] = extra
    return lb.append(
        at=generated_at, source=SOURCE, kind=KIND, tier=1, payload=payload, recorded_at=generated_at
    )


def build_manifest(
    lb: Logbook, req: Request, sel: Selection, generated_at: str, bundle_id: str, head: str
) -> dict[str, Any]:
    """RFC 0005's manifest, plus what the policy adds: the requested tiers, the counts per tier
    and kind, the tier-2 `review` list, the tier-3 warning, and the tool that wrote it."""
    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "bundle_id": bundle_id,
        "generated_at": generated_at,
        "owner": lb.meta["owner_id"],
        "recipient": req.destination,
        "logbook_head": head,
        "covers": {"from": req.since, "to": req.until},
        "policy": {
            "version": "1",
            "file": policy.POLICY_FILE.as_posix(),
            "destination": req.destination,
            "max_tier": req.max_tier,
            "tiers": {
                "1": "auto",
                "2": "reviewed" if 2 in req.tiers else "never",
                "3": "explicit" if req.tier3 else "never",
            },
            "carve_outs": [],
        },
        "tiers": list(req.tiers),
        "counts": sel.counts(),
        "entries_file": ENTRIES_FILE,
        "blobs": sel.blobs,
        "tool": {"name": "openlogbook", "version": __version__},
    }
    if req.kinds is not None:
        manifest["kinds"] = sorted(req.kinds)
    if sel.resolutions:
        manifest["resolution_file"] = RESOLUTION_FILE
    if 2 in req.tiers:
        manifest["review"] = [
            {"id": line["id"], "kind": line["kind"], "source": line["source"], "at": line["at"]}
            for line in [*sel.lines, *sel.resolutions]
            if int(line["tier"]) == 2
        ]
    if req.tier3:
        n = sum(1 for line in [*sel.lines, *sel.resolutions] if int(line["tier"]) == 3)
        manifest["tier3"] = {
            "lines": n,
            "warning": f"{TIER3_WARNING}: {n} tier-3 line(s) for {req.destination}",
        }
    if sel.sealed:  # RFC 0029 §7: how the sealed lines and files of the record are carried
        manifest["sealing"] = (
            {"lines": len(sel.sealed), "mode": "resealed", "recipient": req.recipient}
            if req.recipient
            else {"lines": len(sel.sealed), "mode": "opened"}
        )
    return manifest


def write_bundle(
    lb: Logbook, sel: Selection, manifest: dict[str, Any], out: Path, req: Request | None = None
) -> str:
    """The files under `out` in RFC 0005's layout; the manifest last, carrying the digest of each
    other file. Returns the digest of manifest.json. Re-running into the same folder overwrites.
    A line the record holds sealed crosses in its sealed form with `payload_enc` resealed to the
    destination's recipient, or, under `--open`, with `payload_open` in its place (RFC 0029 §7);
    its hashed fields are the owner's, verbatim, either way."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    carry = _carrier(lb, sel, req)
    manifest["entries_sha256"] = _write_jsonl(out / ENTRIES_FILE, (carry(line) for line in sel.lines))
    if sel.resolutions:
        resolutions = (carry(line) for line in sel.resolutions)
        manifest["resolution_sha256"] = _write_jsonl(out / RESOLUTION_FILE, resolutions)
    if sel.blobs:
        (out / ATTACHMENTS_DIR).mkdir(exist_ok=True)
        for blob in sel.blobs:
            sha256 = str(blob["sha256"])
            _copy_checked(lb, req, lb.root / ATTACHMENTS_DIR / sha256, out / ATTACHMENTS_DIR / sha256, sha256)
    # Encoded once and written as bytes: text mode would turn the newlines into CRLF on Windows
    # and the digest must name the bytes on disk, never the string that was formatted.
    raw = (json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    (out / MANIFEST_FILE).write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _write_jsonl(path: Path, lines: Iterable[Line]) -> str:
    """Lines verbatim (the standard envelope; SPEC §2 lets a reader re-serialise), and the digest."""
    digest = hashlib.sha256()
    with path.open("wb") as fh:
        for line in lines:
            raw = (json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
            digest.update(raw)
            fh.write(raw)
    return digest.hexdigest()


def _carrier(lb: Logbook, sel: Selection, req: Request | None) -> Callable[[Line], Line]:
    """How an opened line is written into the bundle: as it is when the record holds it plain;
    else the sealed line with `payload_enc` resealed to the destination, or opened into
    `payload_open` = {payload, salt} so the member recomputes the digest (RFC 0029 §4.3, §7)."""
    identities = lb.identities if sel.sealed else []

    def carry(line: Line) -> Line:
        raw = sel.sealed.get(str(line.get("id")))
        if raw is None:
            return line
        plain = sealing.open_bytes(raw, identities)
        crossed = dict(raw)
        if req is not None and req.recipient:
            crossed[sealing.FIELD] = sealing.encode(sealing.seal_bytes(plain, [req.recipient]))
        else:
            crossed.pop(sealing.FIELD, None)
            crossed[OPEN_FIELD] = json.loads(plain.decode("utf-8"))
        return crossed

    return carry


def _copy_checked(lb: Logbook, req: Request | None, src: Path, dst: Path, sha256: str) -> None:
    """Copy one attachment, hashing on the way: a store file whose bytes do not match its name is
    an error (SPEC §1.1), never something a recipient should find out. A sealed file is opened
    with the identity, checked, and resealed to the destination or copied opened (RFC 0029 §7)."""
    if sealing.is_sealed_file(src):
        with attachments.opened(lb.root, sha256, lb.identities) as plain:
            if attachments.digest_path(plain)[0] != sha256:
                raise CrossingError(f"{src} opens to bytes that do not hash to its name; repair the record")
            if req is not None and req.recipient:
                sealing.seal_file(plain, dst, [req.recipient])
            else:
                shutil.copyfile(plain, dst)
        return
    digest = hashlib.sha256()
    with src.open("rb") as fi, dst.open("wb") as fo:
        while chunk := fi.read(COPY_CHUNK):
            digest.update(chunk)
            fo.write(chunk)
    if digest.hexdigest() != sha256:
        dst.unlink()
        raise CrossingError(f"{src} does not hash to its name (SPEC §1.1); the record needs repair first")


def write_watermark(lb: Logbook, destination: str, until: str, exported_at: str, bundle_id: str) -> None:
    """`exports/crossing.json`: the window end per destination, for `--since last`. Bookkeeping,
    not the record; the crossing line in the chain is the record."""
    path = watermark_path(lb.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    marks = _read_marks(path)
    marks[destination] = {"until": until, "exported_at": exported_at, "bundle_id": bundle_id}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(marks, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def default_out(lb: Logbook, destination: str, generated_at: str) -> Path:
    """`<root>/export/crossing/<destination>/<generated_at, compact>`: one folder per run."""
    stamp = generated_at.replace("-", "").replace(":", "")
    return lb.root / "export" / KIND / destination / stamp
