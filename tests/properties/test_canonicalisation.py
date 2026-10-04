"""Canonicalisation (SPEC §3: `canonical_json` is RFC 8785, the JSON Canonicalization Scheme; §3.1:
the rule is fixed, not versioned). The RFC's own test vectors are in `tests/test_jcs.py`; here are the
rules the chain relies on, stated for any JSON value: canonicalising is idempotent, independent of key
order and of the whitespace and escapes a writer chose, injective on values, and loses no character of
a string; and a whole number canonicalises the same whether a writer spelled it `1` or `1.0`."""

from __future__ import annotations

import json
import random
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from logbook.chain import canonical_json
from properties.common import CI

I_JSON = 2**53  # RFC 8785 §3.1 / RFC 7493: the integers every implementation represents exactly

scalars = (
    st.none()
    | st.booleans()
    | st.integers(-I_JSON, I_JSON)
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(max_size=20)
)
values = st.recursive(
    scalars,
    lambda inner: st.lists(inner, max_size=5) | st.dictionaries(st.text(max_size=8), inner, max_size=5),
    max_leaves=25,
)


def same(a: Any, b: Any) -> bool:
    """Equality in the JSON data model: `true` is not `1`, a number is its value, a string its code
    points, an object its pairs. Python's `==` says `True == 1`, which JSON does not."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a is b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return bool(a == b)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    return type(a) is type(b) and bool(a == b)


def shuffled(value: Any, rng: random.Random) -> Any:
    """The same value with every object's pairs in another order (Python dicts keep insertion order)."""
    if isinstance(value, dict):
        keys = list(value)
        rng.shuffle(keys)
        return {k: shuffled(value[k], rng) for k in keys}
    if isinstance(value, list):
        return [shuffled(v, rng) for v in value]
    return value


def leaves(value: Any, path: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    """The path of every scalar in a value."""
    if isinstance(value, dict):
        return [p for k, v in value.items() for p in leaves(v, (*path, k))]
    if isinstance(value, list):
        return [p for i, v in enumerate(value) for p in leaves(v, (*path, i))]
    return [path]


def replaced(value: Any, path: tuple[Any, ...], new: Any) -> Any:
    if not path:
        return new
    if isinstance(value, dict):
        return {k: (replaced(v, path[1:], new) if k == path[0] else v) for k, v in value.items()}
    return [replaced(v, path[1:], new) if i == path[0] else v for i, v in enumerate(value)]


@settings(CI, max_examples=150)
@given(values)
def test_canonicalising_is_idempotent(value: Any) -> None:
    """SPEC §3: the canonical form is a fixed point — parsing it and canonicalising again gives the
    same bytes, so two implementations hashing a line from its stored form agree."""
    once = canonical_json(value)
    assert canonical_json(json.loads(once)) == once
    assert once.encode("utf-8").decode("utf-8") == once  # UTF-8, as §3 says


@settings(CI, max_examples=150)
@given(values, st.integers(0, 2**32))
def test_key_order_does_not_matter(value: Any, seed: int) -> None:
    """RFC 8785 §3.2.3: object keys are sorted by the canonicaliser, so the order a writer stored
    them in, at any depth, changes nothing."""
    assert canonical_json(shuffled(value, random.Random(seed))) == canonical_json(value)


@settings(CI, max_examples=150)
@given(values, st.sampled_from((None, 1, 4)), st.booleans(), st.booleans())
def test_whitespace_and_escapes_of_the_stored_form_do_not_matter(
    value: Any, indent: int | None, ensure_ascii: bool, sort_keys: bool
) -> None:
    """RFC 8785 §3.2.1 and §3.2.2.2: a stored form with indentation, `\\uXXXX` escapes for non-ASCII
    or any key order parses to the same value and canonicalises to the same bytes (SPEC §2: the
    stored form is not what is hashed)."""
    stored = json.dumps(value, indent=indent, ensure_ascii=ensure_ascii, sort_keys=sort_keys)
    assert canonical_json(json.loads(stored)) == canonical_json(value)


@settings(CI, max_examples=150)
@given(values, values)
def test_different_values_have_different_canonical_bytes(a: Any, b: Any) -> None:
    """SPEC §3 and §6: the hash covers the canonical bytes, so two lines whose content differs in any
    value must canonicalise differently — the canonical form is injective on JSON values (a number
    being its value: `1` and `1.0` are one value)."""
    assert (canonical_json(a) == canonical_json(b)) == same(a, b)


@settings(CI, max_examples=150)
@given(values, st.data())
def test_changing_one_leaf_changes_the_bytes(value: Any, data: st.DataObject) -> None:
    """The same rule from the other side, as tampering sees it: replace any one scalar of a value
    with another and the canonical bytes differ."""
    paths = leaves(value)
    if not paths:
        return
    path = data.draw(st.sampled_from(paths))
    old = value
    for step in path:
        old = old[step]
    new = data.draw(scalars.filter(lambda v: not same(v, old)))
    assert canonical_json(replaced(value, path, new)) != canonical_json(value)


@settings(CI, max_examples=200)
@given(st.text())
def test_strings_round_trip(s: str) -> None:
    """RFC 8785 §3.2.2.2: a string is escaped, never normalised or transliterated; every code point
    comes back, as a value and as a key, and the canonical text is valid UTF-8."""
    assert json.loads(canonical_json(s)) == s
    assert json.loads(canonical_json({s: s})) == {s: s}
    canonical_json(s).encode("utf-8")


@settings(CI, max_examples=150)
@given(st.integers(-I_JSON, I_JSON))
def test_a_whole_number_canonicalises_the_same_as_int_or_float(n: int) -> None:
    """RFC 8785 §3.2.2.3: a number is serialised from its value as an ECMAScript Number, so the
    writer's `1.0` and `1` are the same bytes (SPEC §3.1: the 0.1 format got this wrong)."""
    assert canonical_json(float(n)) == canonical_json(n)
    assert canonical_json(json.loads(f"{n}.0")) == canonical_json(json.loads(f"{n}"))
    assert canonical_json({"n": float(n)}) == canonical_json({"n": n})
    assert "." not in canonical_json(float(n)) and "e" not in canonical_json(float(n))


@settings(CI, max_examples=150)
@given(st.floats(allow_nan=False, allow_infinity=False))
def test_a_float_round_trips_through_its_canonical_text(x: float) -> None:
    """RFC 8785 §3.2.2.3: the shortest digits that read back as the same double, so the canonical
    text of a float, read as the double it is (I-JSON numbers are doubles; `45920385883743210` is
    4.592038588374321e+16, whatever integer a Python reader makes of it), is the float."""
    assert float(canonical_json(x)) == x
