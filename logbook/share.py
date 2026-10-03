"""The shared page: `logbook share day`, `logbook receive`, `logbook circle` (RFC 0025, `shared-page/v1`).

A page is one local day of the record handed to a named member of the owner's circle (ADR 0009) as
one zip: the day's lines verbatim, so the receiver recomputes every hash; the attachments they point
at, under their own digests; the `day-package/v1` summary of those lines; and a manifest signed with
the owner's sharing key, an Ed25519 key made on first use at `~/.config/logbook/share/<owner_id>.key`
whose public half `logbook.json` carries as `share_key`. The tier that may cross to a destination is
the owner's setting, `policy/crossing.json` (ADR 0016), never a constant here; a line above it stays
home and is counted; every real share is a `crossing/v1` line in the chain (RFC 0011), so the record
shows each time a page left it.

The receiver verifies the signature under the key it holds for the sender in `policy/circle.json`,
never under the key the page brought; recomputes every line's hash; checks every file against the
manifest; and keeps the page under `<root>/circle/<from>/<date>/`, outside the chain. Nothing here
appends to the receiver's log, and nothing is read from the network: a page travels however the two
people like, a USB stick included.

`cryptography` is the only dependency, imported lazily: the package installs and runs without it,
and `share` and `receive` then say which extra to install."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo

from . import crossing, policy
from .chain import ENVELOPE_FIELDS, Line, canonical_json, compute_hash, parse_line
from .export import SCHEMA as PACKAGE_SCHEMA
from .export import entry, parse_day
from .index import local_date
from .store import RETRACTION, Logbook, now_utc, retractions, uuid7

SCHEMA = "shared-page/v1"
MANIFEST_FILE = "manifest.json"
LINES_FILE = "lines.jsonl"
PACKAGE_FILE = "package.json"
ATTACHMENTS_DIR = "attachments"
RECEIVED_FILE = "received.json"  # the receiver's own note beside a page: who, which key, when
CIRCLE_DIR = "circle"  # `<root>/circle/<from>/<date>/`: received pages, outside the chain
KEY_DIR = Path(".config") / "logbook" / "share"  # under the home directory
EXTRA = 'pip install "openlogbook[share]"'
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")  # a destination: one folder name, never a path
DIGEST = re.compile(r"[0-9a-f]{64}")
HEX_KEY = re.compile(r"[0-9a-f]{64}")
HEX_SIGNATURE = re.compile(r"[0-9a-f]{128}")
ATTACHMENT = re.compile(r"attachments/([0-9a-f]{64})")
SEED_LEN = 32
Stamp = tuple[int, int, int, int, int, int]  # a zip member's date_time
CHUNK = 1 << 20
TIER3_WARNING = crossing.TIER3_WARNING


class MissingExtra(ImportError):
    """`cryptography` is not installed: the `share` extra is needed."""

    def __init__(self) -> None:
        super().__init__(f"sharing and receiving a page needs the share extra: {EXTRA}")


class ShareError(ValueError):
    """A request the record, the policy or this machine refuses; the message names the file."""


class ReceiveError(ValueError):
    """A page refused: the message says which check failed. Nothing of it is kept."""


class AlreadyReceived(Exception):
    """The same page, byte for byte, is already held: nothing to do, not an error."""


def _ed25519() -> tuple[Any, Any, type[Exception]]:
    """(Ed25519PrivateKey, Ed25519PublicKey, InvalidSignature), imported now."""
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    except ImportError as e:
        raise MissingExtra() from e
    return Ed25519PrivateKey, Ed25519PublicKey, InvalidSignature


# -- keys -------------------------------------------------------------------------------------------


def key_path(owner_id: str) -> Path:
    """`~/.config/logbook/share/<owner_id>.key`: the private seed, this machine's and this record's."""
    return Path.home() / KEY_DIR / f"{owner_id}.key"


def write_key(path: Path, seed: bytes) -> None:
    """The seed as 64 lowercase hex characters and a newline, readable by the owner alone."""
    if len(seed) != SEED_LEN:
        raise ShareError(f"a sharing key seed is {SEED_LEN} bytes, not {len(seed)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        os.chmod(path.parent, 0o700)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes((seed.hex() + "\n").encode("ascii"))
    if sys.platform != "win32":
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def read_key(path: Path) -> bytes:
    text = path.read_text(encoding="utf-8").strip()
    if not HEX_KEY.fullmatch(text):
        raise ShareError(f"{path} is not a sharing key: expected {SEED_LEN * 2} hex characters")
    return bytes.fromhex(text)


def public_key(seed: bytes) -> str:
    """The public half of the key the seed makes, as 64 lowercase hex characters."""
    private, _, _ = _ed25519()
    from cryptography.hazmat.primitives import serialization

    raw: bytes = (
        private.from_private_bytes(seed)
        .public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )
    return raw.hex()


def preimage(manifest: dict[str, Any]) -> bytes:
    """What is signed: the manifest without its `signature`, as RFC 8785 canonical JSON, UTF-8."""
    return canonical_json({k: v for k, v in manifest.items() if k != "signature"}).encode("utf-8")


def sign(seed: bytes, manifest: dict[str, Any]) -> str:
    private, _, _ = _ed25519()
    signature: bytes = private.from_private_bytes(seed).sign(preimage(manifest))
    return signature.hex()


def verify(public_hex: str, manifest: dict[str, Any], signature_hex: str) -> bool:
    """True when `signature_hex` is the sender's Ed25519 signature over the manifest's pre-image."""
    _, public, invalid = _ed25519()
    try:
        public.from_public_bytes(bytes.fromhex(public_hex)).verify(
            bytes.fromhex(signature_hex), preimage(manifest)
        )
    except (invalid, ValueError):
        return False
    return True


def owner_key(lb: Logbook) -> tuple[bytes, str]:
    """This record's sharing key: (the seed, the public key). Made on first use and its public half
    written to `logbook.json` as `share_key`; a record whose `logbook.json` names a key this machine
    does not hold is refused naming the file, so a page is never signed by a key the record does not
    name, and a key is never replaced behind the owner's back."""
    meta = lb.meta
    owner_id = str(meta["owner_id"])
    path = key_path(owner_id)
    named = meta.get("share_key")
    if path.exists():
        seed = read_key(path)
        public = public_key(seed)
        if named is None:
            lb.set_meta(share_key=public)
        elif named != public:
            raise ShareError(
                f"{path} is not the key logbook.json names as share_key; "
                "restore the key file this record was shared with, or remove share_key to start over"
            )
        return seed, public
    if named is not None:
        raise ShareError(
            f"logbook.json names a share_key but the key is not on this machine: {path}; "
            "copy it from the machine that made it, or remove share_key from logbook.json to make a new one"
        )
    seed = os.urandom(SEED_LEN)
    public = public_key(seed)
    write_key(path, seed)
    lb.set_meta(share_key=public)
    return seed, public


# -- share ------------------------------------------------------------------------------------------


def check_name(name: str, what: str = "destination") -> str:
    """A destination or circle name is one folder name: letters, digits, `.`, `_` and `-`."""
    if not NAME.fullmatch(name):
        raise ShareError(f"a {what} is letters, digits, '.', '_' and '-' only, not {name!r}")
    return name


def parse_tier(text: str | int | None) -> int:
    if text is None:
        return 1
    try:
        tier = int(text)
    except (TypeError, ValueError):
        tier = 0
    if tier not in policy.TIERS:
        raise ShareError(f"--tier must be 1, 2 or 3, not {text!r}")
    return tier


def ceiling(lb: Logbook, to: str, max_tier: int) -> int:
    """Hold the request against the policy: a tier above the destination's ceiling, or a destination
    the file does not name, is refused naming the file (ADR 0016)."""
    try:
        allowed = policy.ceiling(lb.root, to)
    except policy.PolicyError as e:
        raise ShareError(str(e)) from e
    if max_tier > allowed:
        raise ShareError(
            f"--tier {max_tier} is above the ceiling for {to!r}: {policy.policy_path(lb.root)} "
            f"allows max_tier {allowed}; raise it there if that is what you want"
        )
    return allowed


@dataclass
class Selection:
    """What one page selects from the record: the lines that cross, in the day's order."""

    lines: list[Line]
    logged: int  # the day's lines, retractions and the retracted aside
    blobs: list[dict[str, Any]]  # SPEC §1.1 references the store holds, in the manifest's shape
    missing: int  # digests referenced whose file the store does not hold

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

    def counts(self) -> dict[str, Any]:
        return {
            "logged": self.logged,
            "crossed": len(self.lines),
            "held_back": self.held_back,
            "by_tier": self.by_tier,
            "by_kind": self.by_kind,
            "resolutions": 0,
            "resolutions_held_back": 0,
            "attachments": {
                "included": len(self.blobs),
                "bytes": sum(int(b["bytes"]) for b in self.blobs),
                "missing": self.missing,
            },
        }


def select(lb: Logbook, day: str, max_tier: int) -> Selection:
    """The day's lines at or under `max_tier`, in time order then chain order (SPEC §3.2): a
    retracted line stays home, and a retraction is not an event of the day it was written."""
    with lb.index() as idx:
        rows = [line for line in idx.day(day) if line.get("kind") != RETRACTION]
        retracted = retractions(idx.retractions())
    rows = [line for line in rows if str(line["id"]) not in retracted]
    lines = sorted(
        (line for line in rows if int(line["tier"]) <= max_tier), key=lambda r: (str(r["at"]), int(r["seq"]))
    )
    blobs, missing = crossing.blobs(lb, lines)
    return Selection(lines, len(rows), [_attachment(b) for b in blobs], missing)


def _attachment(blob: dict[str, Any]) -> dict[str, Any]:
    return {"sha256": blob["sha256"], "bytes": blob["bytes"], "media_type": blob["media_type"]}


def window(day: str, tz: str) -> tuple[str, str]:
    """The local day's bounds as UTC stamps, for the crossing line's window."""
    start = datetime.combine(parse_day(day), time.min, tzinfo=ZoneInfo(tz))
    return _stamp(start), _stamp(start + timedelta(days=1))


def _stamp(when: datetime) -> str:
    return when.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Shared:
    out: Path
    manifest: dict[str, Any]
    selection: Selection
    package_sha256: str  # of manifest.json's bytes, as the crossing line records it
    line: Line  # the crossing/v1 line appended


def share_day(
    lb: Logbook,
    day: str,
    to: str,
    max_tier: int,
    out: Path,
    created: str | None = None,
    bundle_id: str | None = None,
) -> Shared:
    """Write the page for `to` at `out`, then append the crossing line: in that order, so a crash
    leaves at worst a page no line names. The key is made on first use; the policy is checked first,
    so nothing is written when the request is refused."""
    day = parse_day(day).isoformat()
    check_name(to)
    allowed = ceiling(lb, to, max_tier)
    meta = lb.meta
    lb._check_format(meta)  # a 0.1 record is refused here, before a page exists that no line could record
    seed, public = owner_key(lb)
    policy.write_default(lb.root)
    tz, head, owner_id = str(meta["timezone"]), str(meta["head"]), str(meta["owner_id"])
    created = created or now_utc()
    bundle_id = bundle_id or uuid7()
    sel = select(lb, day, max_tier)
    lines_raw = _jsonl(sel.lines)
    package = {
        "schema": PACKAGE_SCHEMA,
        "date": day,
        "tz": tz,
        "owner_id": owner_id,
        "generated_at": created,
        "logbook_head": head,
        "entries": [entry(line) for line in sel.lines],
        "derived": {},
        "attachments": sel.blobs,
    }
    package_raw = (canonical_json(package) + "\n").encode("utf-8")
    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "bundle_id": bundle_id,
        "from": owner_id,
        "to": to,
        "date": day,
        "tz": tz,
        "created": created,
        "max_tier": max_tier,
        "lines": len(sel.lines),
        "held_back": sel.held_back,
        "lines_sha256": hashlib.sha256(lines_raw).hexdigest(),
        "package_sha256": hashlib.sha256(package_raw).hexdigest(),
        "attachments": sel.blobs,
        "logbook_head": head,
        "key": public,
    }
    manifest["signature"] = sign(seed, manifest)
    manifest_raw = _manifest_bytes(manifest)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    stamp = datetime.fromisoformat(created.replace("Z", "+00:00"))
    when = (stamp.year, stamp.month, stamp.day, stamp.hour, stamp.minute, stamp.second)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(zipfile.ZipInfo(LINES_FILE, when), lines_raw, zipfile.ZIP_DEFLATED)
            zf.writestr(zipfile.ZipInfo(PACKAGE_FILE, when), package_raw, zipfile.ZIP_DEFLATED)
            for blob in sel.blobs:
                sha256 = str(blob["sha256"])
                _copy_checked(lb.root / ATTACHMENTS_DIR / sha256, zf, f"{ATTACHMENTS_DIR}/{sha256}", when)
            zf.writestr(zipfile.ZipInfo(MANIFEST_FILE, when), manifest_raw, zipfile.ZIP_DEFLATED)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, out)
    package_sha256 = hashlib.sha256(manifest_raw).hexdigest()
    since, until = window(day, tz)
    line = lb.append(
        at=created,
        source=crossing.SOURCE,
        kind=crossing.KIND,
        tier=1,
        payload={
            "schema": crossing.LINE_SCHEMA,
            "destination": to,
            "bundle_id": bundle_id,
            "window": {"from": since, "to": until},
            "tiers": [t for t in policy.TIERS if t <= max_tier],
            "counts": sel.counts(),
            "policy": {"file": policy.POLICY_FILE.as_posix(), "max_tier": allowed},
            "logbook_head": head,
            "package_sha256": package_sha256,
            "extra": {"schema": SCHEMA, "date": day},
        },
        recorded_at=created,
    )
    return Shared(out, manifest, sel, package_sha256, line)


def _jsonl(lines: list[Line]) -> bytes:
    """Lines verbatim, one per line, sorted keys (SPEC §2: the stored form may be re-serialised)."""
    return "".join(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n" for line in lines).encode(
        "utf-8"
    )


def _manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return (json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def _copy_checked(src: Path, zf: zipfile.ZipFile, name: str, when: Stamp) -> None:
    """One attachment into the zip, hashed on the way: a store file whose bytes do not match its
    name is an error (SPEC §1.1), never something a receiver should find out."""
    digest = hashlib.sha256()
    info = zipfile.ZipInfo(name, when)
    info.compress_type = zipfile.ZIP_DEFLATED
    with src.open("rb") as fi, zf.open(info, "w") as fo:
        while chunk := fi.read(CHUNK):
            digest.update(chunk)
            fo.write(chunk)
    if f"{ATTACHMENTS_DIR}/{digest.hexdigest()}" != name:
        raise ShareError(f"{src} does not hash to its name (SPEC §1.1); the record needs repair first")


def default_out(lb: Logbook, to: str, day: str) -> Path:
    """`<root>/export/share/<to>/<date>.zip`."""
    return lb.root / "export" / "share" / to / f"{day}.zip"


# -- receive ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Received:
    page: Path  # `<root>/circle/<from>/<date>/`
    sender: str
    manifest: dict[str, Any]
    replaced: bool  # an earlier page for the same day from the same sender was replaced whole


def receive(lb: Logbook, bundle: Path, sender: str | None = None) -> Received:
    """Verify the page at `bundle` and keep it under `<root>/circle/<from>/<date>/`. Every check
    fails before anything is kept; `AlreadyReceived` when the same page is held already. The log,
    `logbook.json` and the attachment store are never touched."""
    bundle = Path(bundle)
    if not zipfile.is_zipfile(bundle):
        raise ReceiveError(f"{bundle} is not a zip, so not a shared page")
    circle = _circle(lb)
    if sender is not None and sender not in circle:
        raise ShareError(
            f"{policy.circle_path(lb.root)} names nobody called {sender!r}; "
            f"add them: logbook circle add {sender} <key>"
        )
    with zipfile.ZipFile(bundle) as zf:
        names = _names(zf)
        manifest = _manifest(zf)
        sender = _sender(manifest, circle, sender, lb)
        if not verify(circle[sender], manifest, str(manifest["signature"])):
            raise ReceiveError(
                f"the signature does not verify under the key held for {sender!r} in "
                f"{policy.CIRCLE_FILE.as_posix()}; the page is not {sender}'s, or it was changed"
            )
        lines_raw = zf.read(LINES_FILE)
        lines = _checked_lines(lines_raw, manifest)
        package_raw = zf.read(PACKAGE_FILE)
        _check_package(package_raw, manifest, lines)
        listed = {str(a["sha256"]) for a in manifest["attachments"]}
        present = {m.group(1) for name in names if (m := ATTACHMENT.fullmatch(name))}
        for sha256 in sorted(listed - present):
            raise ReceiveError(f"attachment {sha256[:12]}… is missing from the bundle")
        for sha256 in sorted(present - listed):
            raise ReceiveError(f"{ATTACHMENTS_DIR}/{sha256}: not named by the manifest")
        page = lb.root / CIRCLE_DIR / sender / str(manifest["date"])
        tmp = page.with_name(page.name + ".receiving")
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True)
        try:
            (tmp / MANIFEST_FILE).write_bytes(zf.read(MANIFEST_FILE))
            (tmp / LINES_FILE).write_bytes(lines_raw)
            (tmp / PACKAGE_FILE).write_bytes(package_raw)
            for blob in manifest["attachments"]:
                _extract_checked(zf, blob, tmp / ATTACHMENTS_DIR)
            note = {
                "from": sender,
                "owner_id": manifest["from"],
                "key": circle[sender],
                "received_at": now_utc(),
                "bundle": bundle.name,
                "bundle_sha256": _file_digest(bundle),
            }
            (tmp / RECEIVED_FILE).write_text(json.dumps(note, indent=2) + "\n", encoding="utf-8")
            replaced = _settle(page, tmp, manifest)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            _prune(tmp.parent, lb.root / CIRCLE_DIR)
            raise
    return Received(page, sender, manifest, replaced)


def _prune(folder: Path, stop: Path) -> None:
    """Remove the folders a refused page left empty, up to and including `<root>/circle`."""
    while folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()
        if folder == stop:
            break
        folder = folder.parent


def _circle(lb: Logbook) -> dict[str, str]:
    try:
        return policy.circle(lb.root)
    except policy.PolicyError as e:
        raise ShareError(str(e)) from e


def _names(zf: zipfile.ZipFile) -> list[str]:
    """Every member name, each one a file a shared page carries and nothing else: no directory,
    no other file, and never a path (so nothing the page says can land outside its folder)."""
    names: list[str] = []
    for info in zf.infolist():
        name = info.filename
        if name == f"{ATTACHMENTS_DIR}/":
            continue  # a tool that wrote a directory entry
        if name not in (MANIFEST_FILE, LINES_FILE, PACKAGE_FILE) and not ATTACHMENT.fullmatch(name):
            raise ReceiveError(f"{name}: not named by the manifest, not a file of a shared page (RFC 0025)")
        names.append(name)
    for required in (MANIFEST_FILE, LINES_FILE, PACKAGE_FILE):
        if required not in names:
            raise ReceiveError(f"{required} is missing from the bundle")
    return names


def _manifest(zf: zipfile.ZipFile) -> dict[str, Any]:
    try:
        manifest = json.loads(zf.read(MANIFEST_FILE).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise ReceiveError(f"{MANIFEST_FILE} is not JSON: {e}") from e
    if not isinstance(manifest, dict):
        raise ReceiveError(f"{MANIFEST_FILE} is not an object")
    if manifest.get("schema") != SCHEMA:
        raise ReceiveError(f"{MANIFEST_FILE}: schema {manifest.get('schema')!r} is not {SCHEMA}")
    for key in ("bundle_id", "from", "to", "tz", "created"):
        if not isinstance(manifest.get(key), str) or not manifest[key]:
            raise ReceiveError(f"{MANIFEST_FILE}: {key} is missing or not a string")
    try:
        parse_day(str(manifest.get("date")))
        _instant(str(manifest["created"]))
    except ValueError as e:
        raise ReceiveError(f"{MANIFEST_FILE}: {e}") from e
    if manifest.get("max_tier") not in policy.TIERS:
        raise ReceiveError(f"{MANIFEST_FILE}: max_tier must be 1, 2 or 3")
    for key in ("lines", "held_back"):
        if not isinstance(manifest.get(key), int) or isinstance(manifest[key], bool) or manifest[key] < 0:
            raise ReceiveError(f"{MANIFEST_FILE}: {key} is not a count")
    for key in ("lines_sha256", "package_sha256", "logbook_head"):
        if not isinstance(manifest.get(key), str) or not DIGEST.fullmatch(manifest[key]):
            raise ReceiveError(f"{MANIFEST_FILE}: {key} is not a lowercase hex sha256")
    if not isinstance(manifest.get("key"), str) or not HEX_KEY.fullmatch(manifest["key"]):
        raise ReceiveError(f"{MANIFEST_FILE}: key is not an Ed25519 public key in hex")
    if not isinstance(manifest.get("signature"), str) or not HEX_SIGNATURE.fullmatch(manifest["signature"]):
        raise ReceiveError(f"{MANIFEST_FILE}: signature is not an Ed25519 signature in hex")
    blobs = manifest.get("attachments")
    if not isinstance(blobs, list):
        raise ReceiveError(f"{MANIFEST_FILE}: attachments is not a list")
    for blob in blobs:
        if (
            not isinstance(blob, dict)
            or not isinstance(blob.get("sha256"), str)
            or not DIGEST.fullmatch(blob["sha256"])
            or not isinstance(blob.get("bytes"), int)
            or not isinstance(blob.get("media_type"), str)
        ):
            raise ReceiveError(f"{MANIFEST_FILE}: an attachment is not {{sha256, bytes, media_type}}")
    return manifest


def _sender(manifest: dict[str, Any], circle: dict[str, str], sender: str | None, lb: Logbook) -> str:
    """Who the page is checked against: `--from`, else the circle member whose key the manifest
    names. Nobody with that key is refused with the line that would add them; the key is checked by
    the signature, never taken from the page."""
    if sender is not None:
        return sender
    for name, key in circle.items():
        if key == manifest["key"]:
            return name
    raise ReceiveError(
        f"nobody in {policy.circle_path(lb.root)} holds the key this page names (owner {manifest['from']}); "
        f"if you know whose it is: logbook circle add <name> {manifest['key']}"
    )


def _checked_lines(raw: bytes, manifest: dict[str, Any]) -> list[Line]:
    """Every line of the page: the file hashes to what the manifest says, the count matches, each
    line is a whole envelope at or under the page's tier, on the page's day, whose hash recomputes."""
    if hashlib.sha256(raw).hexdigest() != manifest["lines_sha256"]:
        raise ReceiveError(f"{LINES_FILE} does not hash to the manifest's lines_sha256")
    lines: list[Line] = []
    for n, text in enumerate((s for s in raw.decode("utf-8").splitlines() if s.strip()), 1):
        try:
            line = parse_line(text)
        except ValueError as e:
            raise ReceiveError(f"line {n}: {e}") from e
        for key in ENVELOPE_FIELDS:
            if key not in line:
                raise ReceiveError(f"line {n}: {key} is missing")
        if line["tier"] not in policy.TIERS:
            raise ReceiveError(f"line {n}: tier must be 1, 2 or 3")
        if int(line["tier"]) > int(manifest["max_tier"]):
            raise ReceiveError(
                f"line {n}: tier {line['tier']} is above the page's max_tier {manifest['max_tier']}"
            )
        if not isinstance(line.get("payload"), dict) or "schema" not in line["payload"]:
            raise ReceiveError(f"line {n}: payload.schema missing")
        try:
            on = local_date(str(line["at"]), str(manifest["tz"]))
        except (ValueError, KeyError) as e:
            raise ReceiveError(f"line {n}: at {line['at']!r} in {manifest['tz']!r}: {e}") from e
        if on != manifest["date"]:
            raise ReceiveError(f"line {n}: {line['at']} is {on} in {manifest['tz']}, not {manifest['date']}")
        try:
            expected = compute_hash(line)
        except (TypeError, ValueError) as e:
            raise ReceiveError(f"line {n}: hash does not recompute: {e}") from e
        if expected != line["hash"]:
            raise ReceiveError(f"line {n}: hash does not recompute (seq {line['seq']}, {line['kind']})")
        lines.append(line)
    if len(lines) != manifest["lines"]:
        raise ReceiveError(f"{len(lines)} lines in {LINES_FILE}; the manifest says {manifest['lines']}")
    if len({str(line["id"]) for line in lines}) != len(lines):
        raise ReceiveError(f"{LINES_FILE}: two lines share an id")
    return lines


def _check_package(raw: bytes, manifest: dict[str, Any], lines: list[Line]) -> None:
    if hashlib.sha256(raw).hexdigest() != manifest["package_sha256"]:
        raise ReceiveError(f"{PACKAGE_FILE} does not hash to the manifest's package_sha256")
    try:
        package = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise ReceiveError(f"{PACKAGE_FILE} is not JSON: {e}") from e
    if not isinstance(package, dict) or package.get("schema") != PACKAGE_SCHEMA:
        raise ReceiveError(f"{PACKAGE_FILE} is not a {PACKAGE_SCHEMA}")
    if package.get("date") != manifest["date"] or package.get("owner_id") != manifest["from"]:
        raise ReceiveError(f"{PACKAGE_FILE} is not the page's day or owner")
    entries = package.get("entries")
    ids = (
        [e.get("id") for e in entries]
        if isinstance(entries, list) and all(isinstance(e, dict) for e in entries)
        else None
    )
    if ids != [line["id"] for line in lines]:
        raise ReceiveError(f"{PACKAGE_FILE} entries are not the page's lines")


def _extract_checked(zf: zipfile.ZipFile, blob: dict[str, Any], into: Path) -> None:
    """One attachment out of the zip, hashed on the way; bytes that are not its name are refused."""
    sha256 = str(blob["sha256"])
    into.mkdir(exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    with zf.open(f"{ATTACHMENTS_DIR}/{sha256}") as fi, (into / sha256).open("wb") as fo:
        while chunk := fi.read(CHUNK):
            digest.update(chunk)
            size += len(chunk)
            fo.write(chunk)
    if digest.hexdigest() != sha256 or size != int(blob["bytes"]):
        raise ReceiveError(f"attachment {sha256[:12]}… does not hash to its name, or is not its stated size")


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _settle(page: Path, tmp: Path, manifest: dict[str, Any]) -> bool:
    """Move the verified page into place. The same page again is nothing to do; a page older than
    the one held never replaces it; a newer one replaces it whole, never merged."""
    if page.exists():
        held = page / MANIFEST_FILE
        if held.read_bytes() == (tmp / MANIFEST_FILE).read_bytes():
            shutil.rmtree(tmp)
            raise AlreadyReceived(f"this page from {manifest['from']} for {manifest['date']} is held already")
        try:
            before = json.loads(held.read_text(encoding="utf-8")).get("created")
        except ValueError:
            before = None
        if isinstance(before, str) and _instant(before) > _instant(str(manifest["created"])):
            shutil.rmtree(tmp)
            raise ReceiveError(
                f"a newer page for {manifest['date']} is held already (created {before}); "
                f"this one was created {manifest['created']}"
            )
        shutil.rmtree(page)
        os.replace(tmp, page)
        return True
    os.replace(tmp, page)
    return False


def _instant(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


# -- for the day ------------------------------------------------------------------------------------


class Page(NamedTuple):
    sender: str
    manifest: dict[str, Any]
    lines: list[Line]
    received: dict[str, Any]


def pages(lb: Logbook, day: str) -> list[Page]:
    """Every received page for `day`, by sender name: what `receive` kept, read back. A folder
    without a manifest, or one that is not JSON, is not a page and is skipped."""
    root = lb.root / CIRCLE_DIR
    if not root.is_dir():
        return []
    found: list[Page] = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        page = folder / day
        manifest_path = page / MANIFEST_FILE
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            raw = (page / LINES_FILE).read_text(encoding="utf-8")
            lines = [parse_line(s) for s in raw.splitlines() if s.strip()]
            note_path = page / RECEIVED_FILE
            received = json.loads(note_path.read_text(encoding="utf-8")) if note_path.is_file() else {}
        except (OSError, ValueError):
            continue
        if isinstance(manifest, dict) and isinstance(received, dict):
            found.append(Page(folder.name, manifest, lines, received))
    return found
