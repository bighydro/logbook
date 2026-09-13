"""The hash chain. Pure functions, no I/O. This file *is* SPEC.md §3."""
from __future__ import annotations
import hashlib, json

GENESIS = "0" * 64
CONTENT_FIELDS = ("at", "end", "tz", "source", "kind", "tier", "payload")


def canonical_json(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def content_hash(line: dict) -> str:
    content = {k: line.get(k) for k in CONTENT_FIELDS}
    return hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()


def line_hash(prev: str, seq: int, chash: str, recorded_at: str) -> str:
    return hashlib.sha256(f"{prev}|{seq}|{chash}|{recorded_at}".encode("utf-8")).hexdigest()


def compute_hash(line: dict) -> str:
    return line_hash(line["prev"], line["seq"], content_hash(line), line["recorded_at"])


from collections.abc import Iterable


def verify_lines(lines: Iterable[dict]) -> tuple[int, str, list[str]]:
    """Walk lines in order. Returns (count, head, errors)."""
    errors, prev, seq, head = [], GENESIS, 0, GENESIS
    for n, line in enumerate(lines, 1):
        if line.get("seq") != seq + 1:
            errors.append(f"line {n}: seq {line.get('seq')} expected {seq + 1}")
        if line.get("prev") != prev:
            errors.append(f"line {n}: prev does not match previous hash")
        if "payload" not in line or "schema" not in (line.get("payload") or {}):
            errors.append(f"line {n}: payload.schema missing")
        if line.get("tier") not in (1, 2, 3):
            errors.append(f"line {n}: tier must be 1, 2 or 3")
        expected = compute_hash(line) if all(k in line for k in ("prev", "seq", "recorded_at")) else None
        if expected != line.get("hash"):
            errors.append(f"line {n}: hash does not recompute")
        prev, seq, head = line.get("hash", prev), line.get("seq", seq), line.get("hash", head)
        if len(errors) > 20:
            errors.append("…stopping after 20 errors")
            break
    return seq, head, errors
