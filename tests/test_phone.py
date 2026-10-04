"""One phone-number normalisation for every adapter that writes a `phone` ref (`logbook.adapters.phone`,
RFC 0006), as properties: for ANY text and ANY country prefix `normalise` never raises and returns a
ref value with the punctuation gone; a value it does not flag is `+` and ASCII digits, and is a fixed
point; two spellings of one number meet on one value, which is the point of having one function."""

from __future__ import annotations

import re

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from logbook.adapters import phone

PUNCTUATION = re.compile(r"[\s\-.()]")
E164 = re.compile(r"\+[0-9]+")

_prefix = st.one_of(st.sampled_from(["", "44", "47", "1", "358"]), st.text("0123456789", max_size=3))
_digits = st.text("0123456789", min_size=1, max_size=15)
_punctuated = st.lists(st.sampled_from([" ", "-", ".", "(", ")", "\t", "  "]), max_size=6)


def _sprinkle(text: str, marks: list[str]) -> str:
    """`text` with the punctuation marks dropped in at points along it."""
    out = text
    for n, mark in enumerate(marks):
        at = (n * 7) % (len(out) + 1)
        out = out[:at] + mark + out[at:]
    return out


@settings(max_examples=200, deadline=None)
@given(st.text(max_size=20), _prefix)
def test_any_text_normalises_without_raising_to_a_value_without_punctuation(entered, prefix):
    value, flagged = phone.normalise(entered, prefix)
    assert isinstance(value, str) and isinstance(flagged, bool)
    assert not PUNCTUATION.search(value)
    if value == "":
        assert flagged is False
    if not flagged and value:
        assert E164.fullmatch(value), "an accepted ref is + and ASCII digits"
        assert phone.normalise(value, prefix) == (value, False)  # a fixed point


@settings(max_examples=200, deadline=None)
@given(
    st.one_of(st.text(max_size=20), _digits, _digits.map(lambda d: "+" + d), _digits.map(lambda d: "00" + d)),
    _prefix,
    _punctuated,
)
def test_punctuation_anywhere_changes_nothing(entered, prefix, marks):
    assert phone.normalise(_sprinkle(entered, marks), prefix) == phone.normalise(entered, prefix)


@settings(max_examples=200, deadline=None)
@given(_digits, _prefix)
def test_a_number_with_a_country_code_is_the_ref_and_00_spells_plus(digits, prefix):
    assert phone.normalise("+" + digits, prefix) == ("+" + digits, False)
    assert phone.normalise("00" + digits, prefix) == phone.normalise("+" + digits, prefix)


@settings(max_examples=200, deadline=None)
@given(_digits, st.text("0123456789", min_size=1, max_size=3))
def test_a_national_number_takes_the_prefix_after_one_trunk_zero_else_is_kept_and_flagged(digits, prefix):
    assume(not digits.startswith("00"))  # the international form, the test above
    value, flagged = phone.normalise(digits, prefix)
    national = digits.removeprefix("0")
    if digits.startswith(prefix) or not national:
        assert (value, flagged) == (digits, True)
    else:
        assert (value, flagged) == (f"+{prefix}{national}", False)


def test_the_documented_spellings_meet():
    assert phone.normalise("07700 900123", "44") == ("+447700900123", False)
    assert phone.normalise("+44 (0)7700-900123", "44") == ("+4407700900123", False)
    assert phone.normalise("0047 900 00 001", "44") == ("+4790000001", False)
    assert phone.normalise("+47 900 00 001", "") == ("+4790000001", False)
    assert phone.normalise("900 00 001", "") == ("90000001", True)
    assert phone.normalise("4790000001", "47") == ("4790000001", True)
    assert phone.normalise("Kari", "47") == ("Kari", True)
    assert phone.normalise(" ", "47") == ("", False)
