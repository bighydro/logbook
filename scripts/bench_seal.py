"""Benchmark per-line sealing (RFC draft, encryption at rest, open question 1) on a synthetic record.

A pure benchmark: nothing here changes what the product does, and it never touches a real record.
It builds a synthetic record shaped like the stress tests in `tests/test_stress.py` — by default
3,000,000 lines, 1,000,000 of them tier 1 (location points) and 2,000,000 tier 2-3, half of those
`health-sample/v1`-sized at tier 3 and half `message/v1`-sized at tier 2, spread over ten years of
month files — in a temporary folder, then measures what Option C of the draft costs:

    plain    = canonical_json({"payload": <payload>, "salt": <32 hex, 16 random bytes>})
    digest   = sha256(plain)
    payload  = {"schema": "sealed/v1", "digest": digest}         hashed, as any payload
    payload_enc = base64(seal(plain))                            stored beside it, outside the hash

`seal` is age X25519 through `pyrage` to one and to two recipients, and, for comparison, the record
data key of the draft's §9.1: one 32-byte key, ChaCha20-Poly1305 with a fresh 12-byte nonce per
line (`cryptography` has no XChaCha, so the nonce is 12 bytes, not the 24 the draft names).

Phases, each in a subprocess of its own so its peak memory is its own: generation alone; the
primitives in memory (seal and open of a health-sized and a message-sized plaintext); the plain
record written by `Logbook.append_many` (the product's path); the same record written by this
script's writer, plain and sealed each way; opening every sealed line; keyless and keyed verify;
index rebuild, with and without opening; bytes on disk.

The sealed record is written by this script, not by `append_many`, because `append_many` hands a
draft to `Logbook._line` as keyword arguments and knows no `payload_enc`; the writer here computes
the same chain with `logbook.chain`, writes the same stored form (`store._dumps`) in the same
batches, fsyncs, saves `logbook.json` and extends the index the same way. Writing the plain record
through both paths shows how close the two are.

Run it (pyrage is not a dependency of the project; it is pulled in for this run only):

    uv run --with pyrage python scripts/bench_seal.py --quick --markdown
    uv run --with pyrage python scripts/bench_seal.py --out bench.json --markdown

`--quick` is 300,000 lines. The full run is 3,000,000 lines and takes an hour or so on a small
machine; it needs about 5 GB of free disk at its peak (one sealed record plus the plain one). The
folder is deleted at the end unless `--keep`. Memory peaks are `ru_maxrss` on Linux and macOS and
`psutil`'s `peak_wset` on Windows when psutil is installed, else n/a.

Everything generated is synthetic: the Oslo persona, who does not exist, and chat ids in the
reserved UK range. No real personal data.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import random
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from logbook.core import index as index_module
from logbook.core.chain import Line, canonical_json, verify_lines
from logbook.core.store import META_EVERY, Logbook, _dumps

LINES = 3_000_000
TIER1 = 1_000_000
QUICK_LINES = 300_000
TIMEZONE = "Europe/Oslo"
START = 1_475_280_000  # 2016-10-01T00:00:00Z; ten years of month files to 2026-10-01
TEN_YEARS = 10 * 365 * 86400
SEALED_SCHEMA = "sealed/v1"
AGE_PREFIX = b"age-encryption.org/v1\n"
NONCE_BYTES = 12  # ChaCha20-Poly1305 in `cryptography`; XChaCha (24) is not available there
PRIMITIVE_LINES = 100_000
VARIANTS = ("plain_append_many", "plain", "age_1", "age_2", "datakey")
SEALED_VARIANTS = ("age_1", "age_2", "datakey")
CATEGORIES = ("location", "health", "message")

Draft = dict[str, Any]
Sealer = Callable[[dict[str, Any]], tuple[dict[str, Any], str]]
Opener = Callable[[Line], dict[str, Any]]


# -- the synthetic record ------------------------------------------------------------------------------


class Shape:
    """How many lines of each category, and the seed."""

    def __init__(self, lines: int, tier1: int, seed: int):
        if not 0 <= tier1 <= lines:
            raise ValueError("--tier1 must be between 0 and --lines")
        self.lines, self.tier1, self.seed = lines, tier1, seed
        sealed = lines - tier1
        self.health = sealed // 2
        self.message = sealed - self.health

    @property
    def sealed(self) -> int:
        return self.health + self.message

    def targets(self) -> dict[str, int]:
        return {"location": self.tier1, "health": self.health, "message": self.message}


HEALTH_TYPES = (("heart_rate", "bpm", 50, 140), ("steps", "count", 0, 400), ("hrv", "ms", 20, 90))
WORDS = [
    "marina",
    "impeller",
    "saturday",
    "dinner",
    "ferry",
    "tide",
    "harbour",
    "sail",
    "wind",
    "forecast",
    "coffee",
    "office",
    "meeting",
    "notes",
    "tram",
    "evening",
    "weekend",
    "cabin",
    "fjord",
    "island",
    "anchor",
    "rope",
    "fuel",
    "chart",
    "lighthouse",
    "morning",
    "afternoon",
    "bakery",
    "bicycle",
    "rain",
    "sun",
    "snow",
    "spring",
    "autumn",
    "museum",
    "concert",
    "library",
    "kitchen",
    "garden",
    "window",
    "door",
    "bridge",
    "train",
    "station",
    "platform",
    "ticket",
    "luggage",
    "passport",
    "photo",
    "camera",
    "lens",
    "battery",
    "charger",
    "laptop",
    "screen",
    "message",
    "reply",
    "thread",
    "draft",
    "list",
    "plan",
    "budget",
    "invoice",
    "receipt",
    "order",
    "parcel",
    "delivery",
    "address",
    "street",
]


def sentence_pool(seed: int, size: int = 512) -> list[str]:
    """`size` synthetic sentences of eight to fourteen words; a message is six of them."""
    rng = random.Random(seed)
    pool = []
    for _ in range(size):
        words = rng.choices(WORDS, k=rng.randint(8, 14))
        pool.append(" ".join(words).capitalize() + ".")
    return pool


def drafts(shape: Shape) -> Iterator[Draft]:
    """The record's drafts in chain order, `at` spread evenly over ten years, categories interleaved
    so that each month file holds every kind. Deterministic for a seed. Synthetic throughout."""
    targets = shape.targets()
    emitted = dict.fromkeys(targets, 0)
    pool = sentence_pool(shape.seed)
    step = TEN_YEARS / max(shape.lines, 1)
    for i in range(shape.lines):
        category = min(
            (c for c in CATEGORIES if emitted[c] < targets[c]), key=lambda c: emitted[c] / targets[c]
        )
        emitted[category] += 1
        at = datetime.fromtimestamp(START + int(i * step), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        if category == "location":
            yield {
                "at": at,
                "source": "sim",
                "kind": "location",
                "tier": 1,
                "payload": {
                    "schema": "location/v1",
                    "raw_id": f"sim:{i}",
                    "lat": round(59.9 + (i % 700) / 1e4, 6),
                    "lon": round(10.7 + (i % 1000) / 1e4, 6),
                },
            }
        elif category == "health":
            name, unit, low, high = HEALTH_TYPES[i % len(HEALTH_TYPES)]
            yield {
                "at": at,
                "source": "sim-health",
                "kind": "health",
                "tier": 3,
                "payload": {
                    "schema": "health-sample/v1",
                    "raw_id": f"hk:{name}:{i}",
                    "type": name,
                    "value": low + (i * 7919) % (high - low),
                    "unit": unit,
                    "device": "Watch7,1",
                },
            }
        else:
            text = " ".join(pool[(i * 7 + k * 131) % len(pool)] for k in range(6))
            yield {
                "at": at,
                "source": "sim-chat",
                "kind": "message",
                "tier": 2,
                "payload": {
                    "schema": "message/v1",
                    "raw_id": f"{i:016X}",
                    "chat": {
                        "id": f"447700900{i % 1000:03d}@s.whatsapp.net",
                        "type": "direct",
                        "name": "Kari",
                    },
                    "from_me": i % 2 == 0,
                    "text": text,
                },
            }


def category_of(draft: Draft) -> str:
    return "location" if draft["tier"] == 1 else "health" if draft["tier"] == 3 else "message"


# -- sealing and opening (Option C) ---------------------------------------------------------------------


def sealed_bytes(payload: dict[str, Any]) -> tuple[bytes, str]:
    """The plaintext of a sealed line and its digest (draft §5 rule 5): the canonical text of the
    payload with a fresh 16-byte salt, and the SHA-256 of exactly those bytes."""
    plain = canonical_json({"payload": payload, "salt": secrets.token_hex(16)}).encode("utf-8")
    return plain, hashlib.sha256(plain).hexdigest()


def make_sealer(variant: str, keys: dict[str, Any]) -> Sealer:
    if variant.startswith("age_"):
        from pyrage import encrypt, x25519  # type: ignore[import-untyped]

        recipients = [x25519.Recipient.from_str(r) for r in keys["recipients"][: int(variant[4:])]]

        def seal_age(payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
            plain, digest = sealed_bytes(payload)
            enc = base64.b64encode(encrypt(plain, recipients)).decode("ascii")
            return {"schema": SEALED_SCHEMA, "digest": digest}, enc

        return seal_age
    if variant == "datakey":
        from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

        aead = ChaCha20Poly1305(bytes.fromhex(keys["data_key"]))

        def seal_data_key(payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
            plain, digest = sealed_bytes(payload)
            nonce = secrets.token_bytes(NONCE_BYTES)
            enc = base64.b64encode(nonce + aead.encrypt(nonce, plain, None)).decode("ascii")
            return {"schema": SEALED_SCHEMA, "digest": digest}, enc

        return seal_data_key
    raise ValueError(f"no sealer for {variant}")


def make_decryptor(variant: str, keys: dict[str, Any]) -> Callable[[bytes], bytes]:
    if variant.startswith("age_"):
        from pyrage import decrypt, x25519

        identities = [x25519.Identity.from_str(keys["identity"])]
        return lambda raw: decrypt(raw, identities)
    if variant == "datakey":
        from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

        aead = ChaCha20Poly1305(bytes.fromhex(keys["data_key"]))
        return lambda raw: aead.decrypt(raw[:NONCE_BYTES], raw[NONCE_BYTES:], None)
    raise ValueError(f"no opener for {variant}")


def make_opener(variant: str, keys: dict[str, Any]) -> Opener:
    """Open one sealed line: decode, decrypt, compare the digest before parsing (draft §5 rule 6),
    and return the inner payload."""
    decryptor = make_decryptor(variant, keys)

    def open_line(line: Line) -> dict[str, Any]:
        plain = decryptor(base64.b64decode(line["payload_enc"]))
        if hashlib.sha256(plain).hexdigest() != line["payload"]["digest"]:
            raise ValueError(f"seq {line['seq']}: digest does not match the opened bytes")
        payload: dict[str, Any] = json.loads(plain)["payload"]
        return payload

    return open_line


def well_formed(variant: str, enc: object) -> bool:
    """The keyless check on `payload_enc`: base64 of bytes that begin `age-encryption.org/v1\\n`
    (draft §4.3); for the data key, base64 of at least a nonce and a tag."""
    if not isinstance(enc, str):
        return False
    try:
        raw = base64.b64decode(enc, validate=True)
    except ValueError:
        return False
    if variant.startswith("age_"):
        return raw.startswith(AGE_PREFIX)
    return len(raw) >= NONCE_BYTES + 16


def is_sealed(line: Line) -> bool:
    payload = line.get("payload")
    return isinstance(payload, dict) and payload.get("schema") == SEALED_SCHEMA


# -- measuring ----------------------------------------------------------------------------------------


def peak_rss_mb() -> float | None:
    """This process's peak resident set in MB: `ru_maxrss` (kilobytes on Linux, bytes on macOS);
    on Windows `psutil`'s peak working set when psutil is installed, else None."""
    try:
        import resource
    except ImportError:
        try:
            import psutil  # type: ignore[import-not-found, import-untyped, unused-ignore]
        except ImportError:
            return None
        peak: int = psutil.Process().memory_info().peak_wset
        return round(peak / 1e6, 1)
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(rss / 1e6 if sys.platform == "darwin" else rss / 1e3, 1)


def month_file_bytes(root: Path) -> int:
    return sum(p.stat().st_size for p in Logbook(root).files())


def phase_generate(shape: Shape) -> dict[str, Any]:
    """Generation alone, so the write phases can be read net of it."""
    started = time.perf_counter()
    n = sum(1 for _ in drafts(shape))
    return {"lines": n, "seconds": round(time.perf_counter() - started, 2), "peak_rss_mb": peak_rss_mb()}


def phase_primitives(shape: Shape, keys: dict[str, Any], count: int) -> dict[str, Any]:
    """Seal and open in memory, with nothing else in the loop: `count` health-sized and `count`
    message-sized plaintexts (canonical, salted, as Option C seals them), each sealed to one and to
    two age recipients and with the data key, then opened. Microseconds per operation and bytes."""
    samples: dict[str, list[bytes]] = {"health": [], "message": []}
    for d in drafts(Shape(count * 3, count, shape.seed)):
        c = category_of(d)
        if c != "location":
            samples[c].append(sealed_bytes(d["payload"])[0])
    out: dict[str, Any] = {"lines_per_size": count}
    for size, plains in samples.items():
        out[size] = {"plain_bytes": round(sum(map(len, plains)) / len(plains), 1)}
        for variant in SEALED_VARIANTS:
            sealer_raw = _raw_sealer(variant, keys)
            decryptor = make_decryptor(variant, keys)
            started = time.perf_counter()
            sealed = [sealer_raw(p) for p in plains]
            seal_s = time.perf_counter() - started
            started = time.perf_counter()
            for raw in sealed:
                decryptor(raw)
            open_s = time.perf_counter() - started
            out[size][variant] = {
                "seal_us": round(seal_s / len(plains) * 1e6, 1),
                "open_us": round(open_s / len(plains) * 1e6, 1),
                "ciphertext_bytes": round(sum(map(len, sealed)) / len(sealed), 1),
                "payload_enc_chars": round(sum(len(base64.b64encode(s)) for s in sealed) / len(sealed), 1),
            }
    out["peak_rss_mb"] = peak_rss_mb()
    return out


def _raw_sealer(variant: str, keys: dict[str, Any]) -> Callable[[bytes], bytes]:
    if variant.startswith("age_"):
        from pyrage import encrypt, x25519

        recipients = [x25519.Recipient.from_str(r) for r in keys["recipients"][: int(variant[4:])]]
        return lambda plain: encrypt(plain, recipients)
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

    aead = ChaCha20Poly1305(bytes.fromhex(keys["data_key"]))

    def seal(plain: bytes) -> bytes:
        nonce = secrets.token_bytes(NONCE_BYTES)
        return nonce + aead.encrypt(nonce, plain, None)

    return seal


def phase_write(root: Path, variant: str, shape: Shape, keys: dict[str, Any]) -> dict[str, Any]:
    """Write the record at `root`: through `Logbook.append_many` for `plain_append_many`, else
    through `write_record`, plain or sealed. Seconds, lines a second, bytes, peak memory."""
    lb = Logbook.init(root, TIMEZONE)
    started = time.perf_counter()
    if variant == "plain_append_many":
        n = lb.append_many(drafts(shape))
        detail: dict[str, Any] = {}
    else:
        n, detail = write_record(lb, variant, shape, keys)
    elapsed = time.perf_counter() - started
    meta = lb.meta
    return {
        "lines": n,
        "seconds": round(elapsed, 2),
        "lines_per_s": round(n / elapsed),
        "month_file_bytes": month_file_bytes(root),
        "index_bytes": (root / index_module.FILE_NAME).stat().st_size,
        "head": meta["head"],
        "peak_rss_mb": peak_rss_mb(),
        **detail,
    }


def write_record(lb: Logbook, variant: str, shape: Shape, keys: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """`append_many`'s shape with sealing added: META_EVERY drafts at a time, the chain computed in
    memory through `Logbook._line`, the sealed lines given their `payload_enc` after hashing (it is
    outside the hash), every batch written and fsynced, then `logbook.json`, then the index. The
    seal step alone is timed per line (two `perf_counter` calls a line, well under a microsecond)."""
    meta = lb.meta
    tz = str(meta["timezone"])
    sealer = make_sealer(variant, keys) if variant in SEALED_VARIANTS else None
    idx = lb.index()
    seq, head = int(meta["seq"]), str(meta["head"])
    handles: dict[Path, Any] = {}
    counts = dict.fromkeys(CATEGORIES, 0)
    sizes = dict.fromkeys(CATEGORIES, 0)
    seal_seconds, sealed_lines, n = 0.0, 0, 0
    it = drafts(shape)
    try:
        while True:
            batch: list[Draft] = []
            for d in it:
                batch.append(d)
                if len(batch) >= META_EVERY:
                    break
            if not batch:
                break
            pending: dict[Path, list[tuple[str, Line]]] = {}
            for d in batch:
                category = category_of(d)
                if sealer is not None and d["tier"] in (2, 3):
                    t = time.perf_counter()
                    reference, enc = sealer(d["payload"])
                    seal_seconds += time.perf_counter() - t
                    sealed_lines += 1
                    line = lb._line(meta, seq + 1, head, **{**d, "payload": reference})
                    line["payload_enc"] = enc
                else:
                    line = lb._line(meta, seq + 1, head, **d)
                seq, head = line["seq"], line["hash"]
                n += 1
                pending.setdefault(lb._path_for(line["at"]), []).append((category, line))
            rows: list[index_module.Row] = []
            for path, lines in pending.items():
                fh = handles.get(path)
                if fh is None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    fh = handles[path] = path.open("ab")
                    fh.seek(0, os.SEEK_END)
                rel, offset = lb._relative(path), fh.tell()
                encoded = []
                for category, line in lines:
                    raw = _dumps(line).encode("utf-8")
                    encoded.append(raw)
                    counts[category] += 1
                    sizes[category] += len(raw)
                    rows.append(index_module.row(line, tz, rel, offset))
                    offset += len(raw)
                fh.write(b"".join(encoded))
                fh.flush()
                os.fsync(fh.fileno())
            meta["seq"], meta["head"] = seq, head
            lb._save_meta(meta)
            idx.add(rows, meta)
    finally:
        for fh in handles.values():
            fh.close()
        idx.close()
    detail: dict[str, Any] = {
        "per_line_bytes": {c: round(sizes[c] / counts[c], 1) for c in CATEGORIES if counts[c]},
        "counts": counts,
    }
    if sealer is not None:
        detail["sealed_lines"] = sealed_lines
        detail["seal_seconds"] = round(seal_seconds, 2)
        detail["seal_us_per_line"] = round(seal_seconds / sealed_lines * 1e6, 1)
        detail["seal_lines_per_s"] = round(sealed_lines / seal_seconds)
    return n, detail


def phase_open(root: Path, variant: str, keys: dict[str, Any]) -> dict[str, Any]:
    """Open every sealed line of the record, streamed file by file: decode, decrypt, digest compare,
    parse. The decrypt-to-payload step alone is timed per line as well as the whole pass."""
    lb = Logbook(root)
    opener = make_opener(variant, keys)
    opened, open_seconds = 0, 0.0
    started = time.perf_counter()
    for line in lb.lines_unsorted():
        if is_sealed(line):
            t = time.perf_counter()
            opener(line)
            open_seconds += time.perf_counter() - t
            opened += 1
    elapsed = time.perf_counter() - started
    return {
        "sealed_lines": opened,
        "seconds": round(elapsed, 2),
        "open_seconds": round(open_seconds, 2),
        "open_us_per_line": round(open_seconds / opened * 1e6, 1) if opened else None,
        "open_lines_per_s": round(opened / open_seconds) if opened else None,
        "peak_rss_mb": peak_rss_mb(),
    }


def phase_verify(root: Path, variant: str, keys: dict[str, Any], keyed: bool) -> dict[str, Any]:
    """`verify` as the draft describes it. Keyless: the chain (`chain.verify_lines` over
    `Logbook.lines()`, which is what `Logbook.verify` does) plus a well-formedness check of every
    `payload_enc`; on the plain record the product's own `Logbook.verify`. Keyed: the chain plus
    every sealed line opened and its digest compared."""
    lb = Logbook(root)
    meta = lb.meta
    started = time.perf_counter()
    sealed = 0
    if variant in SEALED_VARIANTS:
        opener = make_opener(variant, keys) if keyed else None
        problems: list[str] = []

        def checked(lines: Iterable[Line]) -> Iterator[Line]:
            nonlocal sealed
            for line in lines:
                if is_sealed(line):
                    sealed += 1
                    if opener is not None:
                        opener(line)
                    elif not well_formed(variant, line.get("payload_enc")):
                        problems.append(f"seq {line.get('seq')}: payload_enc is not well-formed")
                yield line

        seq, head, errors = verify_lines(checked(lb.lines()))
        errors += problems
    else:
        seq, head, errors = lb.verify()
    elapsed = time.perf_counter() - started
    if errors or (seq, head) != (meta["seq"], meta["head"]):
        raise SystemExit(f"verify failed on {root}: {errors[:3]}")
    return {
        "lines": seq,
        "sealed_lines": sealed,
        "keyed": keyed,
        "seconds": round(elapsed, 2),
        "lines_per_s": round(seq / elapsed),
        "peak_rss_mb": peak_rss_mb(),
    }


def phase_index(root: Path, variant: str, keys: dict[str, Any], opening: bool) -> dict[str, Any]:
    """Rebuild the index from the files. Without opening: the product's `Logbook.index_rebuild`.
    With opening: the same pass (`located_lines`, `index.row`, one INSERT per 10,000 rows, one
    transaction) into a second SQLite file, every sealed line opened first so the four payload
    columns (`raw_id` among them) are filled, as draft §8 says a keyed rebuild does."""
    lb = Logbook(root)
    started = time.perf_counter()
    if not opening:
        n = lb.index_rebuild()
    else:
        opener = make_opener(variant, keys)
        tz = str(lb.meta["timezone"])
        path = root / "index-opened.sqlite"
        path.unlink(missing_ok=True)
        db = sqlite3.connect(path, isolation_level=None)
        n = 0
        batch: list[index_module.Row] = []
        try:
            db.execute("BEGIN")
            for statement in index_module.SCHEMA:
                db.execute(statement)
            for file, offset, line in lb.located_lines():
                if is_sealed(line):
                    line["payload"] = opener(line)
                batch.append(index_module.row(line, tz, file, offset))
                n += 1
                if len(batch) >= index_module.INSERT_EVERY:
                    db.executemany(index_module.INSERT, batch)
                    batch.clear()
            db.executemany(index_module.INSERT, batch)
            db.execute("COMMIT")
        finally:
            db.close()
    elapsed = time.perf_counter() - started
    return {
        "lines": n,
        "opening": opening,
        "seconds": round(elapsed, 2),
        "lines_per_s": round(n / elapsed),
        "peak_rss_mb": peak_rss_mb(),
    }


# -- the driver ---------------------------------------------------------------------------------------


def machine() -> dict[str, Any]:
    info: dict[str, Any] = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or cpu_model(),
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
        "pyrage": version_of("pyrage"),
        "cryptography": version_of("cryptography"),
        "github_runner": os.environ.get("RUNNER_OS"),
        "memory_gb": memory_gb(),
    }
    return info


def version_of(package: str) -> str | None:
    import importlib.metadata

    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def cpu_model() -> str:
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for text in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
            if text.startswith("model name"):
                return text.split(":", 1)[1].strip()
    return ""


def memory_gb() -> float | None:
    try:
        pages, page_size = os.sysconf("SC_PHYS_PAGES"), os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError, AttributeError):
        return None
    return round(pages * page_size / 1e9, 1)


def run_phase(
    args: argparse.Namespace, phase: str, root: Path, variant: str, **flags: bool
) -> dict[str, Any]:
    """One phase in a subprocess of its own; it prints a JSON object as its last line."""
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--phase",
        phase,
        "--root",
        str(root),
        "--variant",
        variant,
        "--lines",
        str(args.lines),
        "--tier1",
        str(args.tier1),
        "--seed",
        str(args.seed),
        "--keys",
        str(args.keys),
        "--primitive-lines",
        str(args.primitive_lines),
    ]
    command += [f"--{name}" for name, on in flags.items() if on]
    label = " ".join([phase, variant, *(name for name, on in flags.items() if on)])
    print(f"  {label} ...", end="", file=sys.stderr, flush=True)
    started = time.perf_counter()
    out = subprocess.run(command, capture_output=True, encoding="utf-8", check=False)
    if out.returncode != 0:
        print(out.stderr, file=sys.stderr)
        raise SystemExit(f"phase {label} failed")
    result: dict[str, Any] = json.loads(out.stdout.strip().splitlines()[-1])
    print(f" {time.perf_counter() - started:.0f}s, peak {result.get('peak_rss_mb')} MB", file=sys.stderr)
    return result


def run_child(args: argparse.Namespace) -> None:
    shape = Shape(args.lines, args.tier1, args.seed)
    keys = json.loads(Path(args.keys).read_text(encoding="utf-8"))
    root = Path(args.root)
    if args.phase == "generate":
        result = phase_generate(shape)
    elif args.phase == "primitives":
        result = phase_primitives(shape, keys, args.primitive_lines)
    elif args.phase == "write":
        result = phase_write(root, args.variant, shape, keys)
    elif args.phase == "open":
        result = phase_open(root, args.variant, keys)
    elif args.phase == "verify":
        result = phase_verify(root, args.variant, keys, args.keyed)
    elif args.phase == "index":
        result = phase_index(root, args.variant, keys, args.opening)
    else:
        raise SystemExit(f"unknown phase {args.phase}")
    print(json.dumps(result))


def new_keys() -> dict[str, Any]:
    """Fresh keys for this run only: two age identities (the second a recipient only) and one
    32-byte data key. Written to a file in the run's folder so every phase's subprocess shares them."""
    from pyrage import x25519

    first, second = x25519.Identity.generate(), x25519.Identity.generate()
    return {
        "identity": str(first),
        "recipients": [str(first.to_public()), str(second.to_public())],
        "data_key": secrets.token_hex(32),
    }


def run_driver(args: argparse.Namespace) -> None:
    shape = Shape(args.lines, args.tier1, args.seed)
    recipients = {int(r) for r in args.recipients.split(",") if r.strip()}
    variants = [
        v
        for v in VARIANTS
        if (not v.startswith("age_") or int(v[4:]) in recipients)
        and (args.variants is None or v in args.variants)
    ]
    root = Path(args.root) if args.root else Path(tempfile.mkdtemp(prefix="bench-seal-"))
    root.mkdir(parents=True, exist_ok=True)
    args.keys = root / "keys.json"
    args.keys.write_text(json.dumps(new_keys()), encoding="utf-8")
    results: dict[str, Any] = {
        "machine": machine(),
        "config": {
            "lines": shape.lines,
            "tier1": shape.tier1,
            "health": shape.health,
            "message": shape.message,
            "sealed": shape.sealed,
            "seed": shape.seed,
            "recipients": sorted(recipients),
            "variants": variants,
            "primitive_lines": args.primitive_lines,
            "started_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        },
        "records": {},
    }
    print(f"bench_seal: {shape.lines:,} lines ({shape.sealed:,} sealed) in {root}", file=sys.stderr)
    started = time.perf_counter()
    try:
        results["generation"] = run_phase(args, "generate", root, "none")
        results["primitives"] = run_phase(args, "primitives", root, "none")
        save(args, results)
        for variant in variants:
            record_root = root / variant
            record: dict[str, Any] = {"write": run_phase(args, "write", record_root, variant)}
            if variant in SEALED_VARIANTS:
                record["open"] = run_phase(args, "open", record_root, variant)
                record["verify_keyless"] = run_phase(args, "verify", record_root, variant)
                record["verify_keyed"] = run_phase(args, "verify", record_root, variant, keyed=True)
                record["index_rebuild_opening"] = run_phase(args, "index", record_root, variant, opening=True)
            elif variant == "plain_append_many":
                record["verify_keyless"] = run_phase(args, "verify", record_root, variant)
                record["index_rebuild"] = run_phase(args, "index", record_root, variant)
            results["records"][variant] = record
            save(args, results)
            if not args.keep:
                shutil.rmtree(record_root, ignore_errors=True)
        results["config"]["total_seconds"] = round(time.perf_counter() - started)
        save(args, results)
    finally:
        if not args.keep:
            shutil.rmtree(root, ignore_errors=True)
    if args.markdown:
        print(markdown(results))


def save(args: argparse.Namespace, results: dict[str, Any]) -> None:
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")


# -- the table ----------------------------------------------------------------------------------------

COLUMNS = (
    ("plain_append_many", "plain"),
    ("age_1", "age, 1 recipient"),
    ("age_2", "age, 2 recipients"),
    ("datakey", "data key"),
)


def markdown(results: dict[str, Any]) -> str:
    records = results["records"]
    columns = [(key, title) for key, title in COLUMNS if key in records]
    cfg = results["config"]
    out = [
        f"{cfg['lines']:,} lines, {cfg['sealed']:,} of them tier 2-3 ({cfg['health']:,} health-sized,"
        f" {cfg['message']:,} message-sized); generation alone {results['generation']['seconds']} s.",
        "",
        "| Phase | " + " | ".join(title for _key, title in columns) + " |",
        "|---|" + "---|" * len(columns),
    ]

    def cell(record: dict[str, Any], phase: str, fmt: Callable[[dict[str, Any]], str]) -> str:
        return fmt(record[phase]) if phase in record else "n/a"

    def rate(m: dict[str, Any]) -> str:
        return f"{m['seconds']:,.0f} s, {m['lines_per_s']:,} lines/s, peak {m['peak_rss_mb']} MB"

    rows: list[tuple[str, str, Callable[[dict[str, Any]], str]]] = [
        ("Write the record (end to end)", "write", rate),
        (
            "Seal step alone (tier 2-3 lines)",
            "write",
            lambda m: (
                f"{m['seal_us_per_line']} us/line, {m['seal_lines_per_s']:,} lines/s"
                if "seal_us_per_line" in m
                else "-"
            ),
        ),
        (
            "Open every sealed line",
            "open",
            lambda m: (
                f"{m['open_us_per_line']} us/line, {m['open_lines_per_s']:,} lines/s;"
                f" pass {m['seconds']:,.0f} s, peak {m['peak_rss_mb']} MB"
            ),
        ),
        ("Keyless verify", "verify_keyless", rate),
        ("Keyed verify", "verify_keyed", rate),
        ("Index rebuild (plain)", "index_rebuild", rate),
        ("Index rebuild with opening", "index_rebuild_opening", rate),
        ("Month files on disk", "write", lambda m: f"{m['month_file_bytes'] / 1e6:,.0f} MB"),
    ]
    for title, phase, fmt in rows:
        out.append(f"| {title} | " + " | ".join(cell(records[key], phase, fmt) for key, _t in columns) + " |")
    out += [
        "",
        "Per line, stored form (bytes):",
        "",
        "| Lines | " + " | ".join(t for _k, t in columns) + " |",
        "|---|" + "---|" * len(columns),
    ]
    plain = records.get("plain", {}).get("write", {}).get("per_line_bytes", {})
    for category in ("health", "message", "location"):
        cells = []
        for key, _title in columns:
            source = "plain" if key == "plain_append_many" else key
            size = records.get(source, {}).get("write", {}).get("per_line_bytes", {}).get(category)
            if size is None:
                cells.append("n/a")
            elif category in plain and source != "plain":
                cells.append(f"{size:,.0f} ({size / plain[category]:.2f}x)")
            else:
                cells.append(f"{size:,.0f}")
        out.append(f"| {category} | " + " | ".join(cells) + " |")
    prim = results.get("primitives", {})
    if prim:
        out += [
            "",
            f"Primitives in memory, {prim['lines_per_size']:,} plaintexts per size (us per operation):",
            "",
        ]
        out.append("| Plaintext | age 1: seal / open | age 2: seal / open | data key: seal / open |")
        out.append("|---|---|---|---|")
        for size in ("health", "message"):
            p = prim[size]
            out.append(
                f"| {size}, {p['plain_bytes']:.0f} B | {p['age_1']['seal_us']} / {p['age_1']['open_us']}"
                f" | {p['age_2']['seal_us']} / {p['age_2']['open_us']}"
                f" | {p['datakey']['seal_us']} / {p['datakey']['open_us']} |"
            )
    return "\n".join(out)


def parse(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--lines", type=int, default=LINES)
    ap.add_argument(
        "--tier1", type=int, default=None, help=f"tier-1 lines (default {TIER1:,}; a third under --quick)"
    )
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--recipients", default="1,2", help="age recipient counts to measure, e.g. 1,2")
    ap.add_argument("--variants", nargs="*", choices=VARIANTS, default=None, help="only these variants")
    ap.add_argument("--primitive-lines", type=int, default=PRIMITIVE_LINES)
    ap.add_argument("--quick", action="store_true", help=f"{QUICK_LINES:,} lines, for a smoke run")
    ap.add_argument("--root", default=None, help="work here instead of a temporary folder")
    ap.add_argument("--keep", action="store_true", help="leave the generated records on disk")
    ap.add_argument("--out", default=None, help="write the results as JSON here")
    ap.add_argument("--markdown", action="store_true", help="print the results table")
    ap.add_argument("--phase", default=None, help=argparse.SUPPRESS)  # a subprocess of the driver
    ap.add_argument("--variant", default="none", help=argparse.SUPPRESS)
    ap.add_argument("--keys", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--keyed", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--opening", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.quick and args.lines == LINES:
        args.lines = QUICK_LINES
        args.primitive_lines = min(args.primitive_lines, 20_000)
    if args.tier1 is None:
        args.tier1 = TIER1 if args.lines == LINES else args.lines // 3
    return args


def main(argv: list[str] | None = None) -> None:
    args = parse(argv)
    if args.phase:
        run_child(args)
    else:
        run_driver(args)


if __name__ == "__main__":
    main()
