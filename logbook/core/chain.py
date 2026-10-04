"""The hash chain. Pure functions, no I/O. This file *is* SPEC.md §3."""

from __future__ import annotations

import base64
import hashlib
import json
import math
from collections.abc import Callable, Iterable
from typing import Any

Line = dict[str, Any]

GENESIS = "0" * 64
CONTENT_FIELDS = ("at", "end", "tz", "source", "kind", "tier", "payload")
ENVELOPE_FIELDS = ("id", "seq", *CONTENT_FIELDS, "recorded_at", "prev", "hash")  # all present, SPEC §2

# A sealed line (SPEC §2, RFC 0029): its `payload` is a reference to content kept in `payload_enc`,
# an age file as standard base64, outside the hash as `id` is. What a verifier without the key
# checks of it is here; opening it is `logbook/core/sealing.py`.
SEALED_SCHEMA = "sealed/v1"
SEALED_FIELD = "payload_enc"
SEALED_KEYS = frozenset({"schema", "of", "digest"})
AGE_MAGIC = b"age-encryption.org/v1\n"


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
    elif isinstance(obj, int | float):
        out.append(number_text(obj))
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


def number_text(x: int | float) -> str:
    """A JSON number as RFC 8785 writes it, by value: an int exactly, a float as ECMAScript spells it
    (`100000000000000000000` for 1e20, `1e+21`, `0.000001`, `120` for 120.0). A reader prints a number
    this way too (SPEC §3.2), so two implementations agree whatever text the writer stored."""
    return int.__repr__(x) if isinstance(x, int) else _es6_number(x)


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


def is_sealed(line: Line) -> bool:
    payload = line.get("payload")
    return isinstance(payload, dict) and payload.get("schema") == SEALED_SCHEMA


def decode_sealed(payload_enc: object) -> bytes | None:
    """The age file inside `payload_enc`, or None when it is not standard base64 of bytes that
    begin with the age header: all a keyless verifier can check of it."""
    if not isinstance(payload_enc, str) or not payload_enc:
        return None
    try:
        raw = base64.b64decode(payload_enc, validate=True)
    except (ValueError, TypeError):
        return None
    return raw if raw.startswith(AGE_MAGIC) else None


def sealed_envelope_error(line: Line) -> str | None:
    """The envelope rule for sealing (SPEC §2): a `sealed/v1` payload is exactly {schema, of,
    digest} with a well-formed `payload_enc`, and no other payload has a `payload_enc`."""
    enc = line.get(SEALED_FIELD)
    if is_sealed(line):
        payload = line["payload"]
        if set(payload) != SEALED_KEYS or not isinstance(payload["of"], str):
            return "sealed/v1 payload must be exactly {schema, of, digest}"
        digest = payload["digest"]
        if not isinstance(digest, str) or len(digest) != 64 or digest != digest.lower():
            return "sealed/v1 digest is not a lowercase hex sha256"
        if decode_sealed(enc) is None:
            return f"sealed/v1 line without a well-formed {SEALED_FIELD}"
    elif enc is not None:
        return f"{SEALED_FIELD} on a line whose payload is not sealed/v1"
    return None


def content_hash(line: Line) -> str:
    content = {k: line.get(k) for k in CONTENT_FIELDS}
    return hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()


def line_hash(prev: str, seq: int, chash: str, recorded_at: str) -> str:
    return hashlib.sha256(f"{prev}|{seq}|{chash}|{recorded_at}".encode()).hexdigest()


def compute_hash(line: Line) -> str:
    return line_hash(line["prev"], line["seq"], content_hash(line), line["recorded_at"])


TIMESTAMP_FIELDS = ("at", "end", "recorded_at")
OFFSET_WARNING = "is not UTC with a literal Z (SPEC §2); a warning in this release, an error in the next"


# For a sealed line: None when it opened and its bytes hash to its digest, else what went wrong.
Opener = Callable[[Line], str | None]


def verify_lines(
    lines: Iterable[Line],
    warnings: list[str] | None = None,
    opener: Opener | None = None,
    counts: dict[str, int] | None = None,
) -> tuple[int, str, list[str]]:
    """Walk lines in order. Returns (count, head, errors); what this release only warns about is
    appended to `warnings` when a list is given. A sealed line is checked by the envelope rule
    whatever the key, and opened through `opener` when one is given: its error is the record's
    error (SPEC §3). `counts`, when given, is told how many lines were `sealed`, how many of those
    were `opened`, and how many tier 2 or 3 lines are `plain` (RFC 0029 §5 rule 1)."""
    errors: list[str] = []
    prev, seq, head = GENESIS, 0, GENESIS
    tally = {"sealed": 0, "opened": 0, "plain": 0} if counts is None else counts
    for k in ("sealed", "opened", "plain"):
        tally.setdefault(k, 0)
    for n, line in enumerate(lines, 1):
        errors.extend(f"line {n}: {k} is missing" for k in ENVELOPE_FIELDS if k not in line)
        sealed_error = sealed_envelope_error(line)
        if sealed_error is not None:
            errors.append(f"line {n}: {sealed_error}")
        elif is_sealed(line):
            tally["sealed"] += 1
            if opener is not None:
                opened = opener(line)
                if opened is None:
                    tally["opened"] += 1
                else:
                    errors.append(f"line {n}: {opened}")
        elif line.get("tier") in (2, 3):
            tally["plain"] += 1
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
