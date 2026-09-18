"""The hash chain. Pure functions, no I/O. This file *is* SPEC.md §3."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from typing import Any

Line = dict[str, Any]

GENESIS = "0" * 64
CONTENT_FIELDS = ("at", "end", "tz", "source", "kind", "tier", "payload")
ENVELOPE_FIELDS = ("id", "seq", *CONTENT_FIELDS, "recorded_at", "prev", "hash")  # all present, SPEC §2


def parse_line(text: str | bytes) -> Line:
    """The stored form of a line (SPEC §2) as a dict. A key given twice in one object, at any
    depth, is invalid: `json.loads` would keep the last value silently, so the pairs are checked."""
    line: Line = json.loads(text, object_pairs_hook=_no_duplicate_keys)
    return line


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"duplicate key {key!r}")
        obj[key] = value
    return obj


def canonical_json(obj: object) -> str:
    """RFC 8785 (JSON Canonicalization Scheme). No whitespace; strings escaped as JSON.stringify does
    (§3.2.2.2); floats serialised as ECMAScript numbers (§3.2.2.3); object keys sorted as UTF-16 code
    units (§3.2.3); NaN, Infinity and lone surrogates are errors. Python ints are written exactly.
    """
    parts: list[str] = []
    _write(obj, parts)
    text = "".join(parts)
    try:
        text.encode("utf-8")  # §3.2.2.2: a lone surrogate must terminate with an error
    except UnicodeEncodeError as e:
        raise ValueError(f"RFC 8785: string is not valid Unicode: {e}") from e
    return text


def _write(obj: object, out: list[str]) -> None:
    if obj is None:
        out.append("null")
    elif obj is True:
        out.append("true")
    elif obj is False:
        out.append("false")
    elif isinstance(obj, int):
        out.append(int.__repr__(obj))
    elif isinstance(obj, float):
        out.append(_es6_number(obj))
    elif isinstance(obj, str):
        out.append(json.dumps(obj, ensure_ascii=False))
    elif isinstance(obj, list | tuple):
        out.append("[")
        for i, item in enumerate(obj):
            if i:
                out.append(",")
            _write(item, out)
        out.append("]")
    elif isinstance(obj, dict):
        out.append("{")
        # §3.2.3: sort by UTF-16 code units; surrogatepass so a bad key is reported by the UTF-8 check
        items = sorted(((_key(k), v) for k, v in obj.items()), key=_utf16)
        for i, (key, value) in enumerate(items):
            if i:
                out.append(",")
            out.append(json.dumps(key, ensure_ascii=False))
            out.append(":")
            _write(value, out)
        out.append("}")
    else:
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _utf16(kv: tuple[str, object]) -> bytes:
    return kv[0].encode("utf-16-be", "surrogatepass")


def _key(k: object) -> str:
    """Object keys are strings; the same coercions json.dumps applies, so old callers keep working."""
    if isinstance(k, str):
        return k
    if k is None or isinstance(k, bool | int | float):
        return "".join(_collect(k))
    raise TypeError(f"keys must be str, int, float, bool or None, not {type(k).__name__}")


def _collect(k: object) -> list[str]:
    parts: list[str] = []
    _write(k, parts)
    return parts


def _es6_number(x: float) -> str:
    """ECMAScript Number::toString (ECMA-262 §7.1.12.1 with Note 2), as RFC 8785 §3.2.2.3 requires.

    Python's repr already gives the shortest digit string that round-trips (the same digits ECMAScript
    picks); only the layout differs, so take the digits and exponent apart and lay them out again.
    """
    if math.isnan(x) or math.isinf(x):
        raise ValueError("RFC 8785: NaN and Infinity are not permitted in JSON")
    if x == 0:
        return "0"  # -0 serialises as 0
    sign = "-" if x < 0 else ""
    mantissa, _, exponent = repr(abs(x)).partition("e")
    whole, _, fraction = mantissa.partition(".")
    digits = whole + fraction
    n = len(whole) + int(exponent or 0)  # value = 0.<digits> * 10**n
    stripped = digits.lstrip("0")
    n -= len(digits) - len(stripped)
    digits = stripped.rstrip("0")
    k = len(digits)
    if k <= n <= 21:
        return sign + digits + "0" * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return sign + "0." + "0" * -n + digits
    e = n - 1
    mant = digits if k == 1 else digits[0] + "." + digits[1:]
    return f"{sign}{mant}e{'+' if e >= 0 else '-'}{abs(e)}"


def content_hash(line: Line) -> str:
    content = {k: line.get(k) for k in CONTENT_FIELDS}
    return hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()


def line_hash(prev: str, seq: int, chash: str, recorded_at: str) -> str:
    return hashlib.sha256(f"{prev}|{seq}|{chash}|{recorded_at}".encode()).hexdigest()


def compute_hash(line: Line) -> str:
    return line_hash(line["prev"], line["seq"], content_hash(line), line["recorded_at"])


TIMESTAMP_FIELDS = ("at", "end", "recorded_at")
OFFSET_WARNING = "is not UTC with a literal Z (SPEC §2); a warning in this release, an error in the next"


def verify_lines(lines: Iterable[Line], warnings: list[str] | None = None) -> tuple[int, str, list[str]]:
    """Walk lines in order. Returns (count, head, errors); what this release only warns about is
    appended to `warnings` when a list is given."""
    errors: list[str] = []
    prev, seq, head = GENESIS, 0, GENESIS
    for n, line in enumerate(lines, 1):
        errors.extend(f"line {n}: {k} is missing" for k in ENVELOPE_FIELDS if k not in line)
        if warnings is not None:
            for k in TIMESTAMP_FIELDS:
                stamp = line.get(k)
                if isinstance(stamp, str) and not stamp.endswith("Z"):
                    warnings.append(f"line {n}: {k} {stamp!r} {OFFSET_WARNING}")
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
