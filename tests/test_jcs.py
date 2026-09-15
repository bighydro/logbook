"""RFC 8785 (JSON Canonicalization Scheme) test vectors, run against ``logbook.chain.canonical_json``.

SPEC.md §3 says ``canonical_json`` *is* RFC 8785. These vectors are transcribed from the RFC text:

* the canonicalisation example, input from §3.2.2 and expected output from §3.2.3;
* the property-sorting example from §3.2.3 (keys sorted as UTF-16 code units, not code points);
* the number serialisation table, Appendix B, Table 1 (IEEE 754 hex -> JSON representation).
"""

import json
import math
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook.chain import canonical_json

# --- RFC 8785 §3.2.2, "Assume the following JSON object is parsed:" (verbatim) ---
SECTION_3_2_2_INPUT = r"""
     {
       "numbers": [333333333.33333329, 1E30, 4.50,
                   2e-3, 0.000000000000000000000000001],
       "string": "\u20ac$\u000F\u000aA'\u0042\u0022\u005c\\\"\/",
       "literals": [null, true, false]
     }
"""

# --- RFC 8785 §3.2.3, "a properly canonicalized version should ... read as:" (line wrap removed) ---
SECTION_3_2_3_EXPECTED = (
    r'{"literals":[null,true,false],"numbers":[333333333.3333333,'
    r'1e+30,4.5,0.002,1e-27],"string":"' + "\u20ac" + r"$\u000f\nA" + "'" + r'B\"\\\\\"/"}'
)

# --- RFC 8785 §3.2.3, "The following JSON test data can be used for verifying the correctness of the
#     sorting scheme" (verbatim), and "Expected argument order after sorting property strings". ---
SECTION_3_2_3_SORTING_INPUT = r"""
     {
       "\u20ac": "Euro Sign",
       "\r": "Carriage Return",
       "\ufb33": "Hebrew Letter Dalet With Dagesh",
       "1": "One",
       "\ud83d\ude00": "Emoji: Grinning Face",
       "\u0080": "Control",
       "\u00f6": "Latin Small Letter O With Diaeresis"
     }
"""
SECTION_3_2_3_SORTING_EXPECTED_ORDER = [
    "Carriage Return",
    "One",
    "Control",
    "Latin Small Letter O With Diaeresis",
    "Euro Sign",
    "Emoji: Grinning Face",
    "Hebrew Letter Dalet With Dagesh",
]

# --- RFC 8785 Appendix B, Table 1: ECMAScript-Compatible JSON Number Serialization Samples ---
# (IEEE 754 hex, JSON representation, comment). NaN and Infinity have no representation:
# note (3) and §3.2.2.3 say they MUST cause the implementation to terminate with an error.
APPENDIX_B_TABLE_1 = [
    ("0000000000000000", "0", "Zero"),
    ("8000000000000000", "0", "Minus zero"),
    ("0000000000000001", "5e-324", "Min pos number"),
    ("8000000000000001", "-5e-324", "Min neg number"),
    ("7fefffffffffffff", "1.7976931348623157e+308", "Max pos number"),
    ("ffefffffffffffff", "-1.7976931348623157e+308", "Max neg number"),
    ("4340000000000000", "9007199254740992", "Max pos int (1)"),
    ("c340000000000000", "-9007199254740992", "Max neg int (1)"),
    ("4430000000000000", "295147905179352830000", "~2**68 (2)"),
    ("7fffffffffffffff", None, "NaN (3)"),
    ("7ff0000000000000", None, "Infinity (3)"),
    ("44b52d02c7e14af5", "9.999999999999997e+22", ""),
    ("44b52d02c7e14af6", "1e+23", ""),
    ("44b52d02c7e14af7", "1.0000000000000001e+23", ""),
    ("444b1ae4d6e2ef4e", "999999999999999700000", ""),
    ("444b1ae4d6e2ef4f", "999999999999999900000", ""),
    ("444b1ae4d6e2ef50", "1e+21", ""),
    ("3eb0c6f7a0b5ed8c", "9.999999999999997e-7", ""),
    ("3eb0c6f7a0b5ed8d", "0.000001", ""),
    ("41b3de4355555553", "333333333.3333332", ""),
    ("41b3de4355555554", "333333333.33333325", ""),
    ("41b3de4355555555", "333333333.3333333", ""),
    ("41b3de4355555556", "333333333.3333334", ""),
    ("41b3de4355555557", "333333333.33333343", ""),
    ("becbf647612f3696", "-0.0000033333333333333333", ""),
    ("43143ff3c1cb0959", "1424953923781206.2", "Round to even (4)"),
]


def ieee754(hex_bits: str) -> float:
    return struct.unpack(">d", bytes.fromhex(hex_bits))[0]


def test_section_3_2_2_example_canonicalises_as_section_3_2_3_shows():
    assert canonical_json(json.loads(SECTION_3_2_2_INPUT)) == SECTION_3_2_3_EXPECTED


def test_section_3_2_3_property_names_sort_as_utf16_code_units():
    out = canonical_json(json.loads(SECTION_3_2_3_SORTING_INPUT))
    values = list(json.loads(out).values())  # json.loads keeps document order
    assert values == SECTION_3_2_3_SORTING_EXPECTED_ORDER
    # and the same holds when the object is nested in an array and in another object (§3.2.3: recursive)
    nested = canonical_json({"z": [json.loads(SECTION_3_2_3_SORTING_INPUT)], "a": 1})
    assert list(json.loads(nested)["z"][0].values()) == SECTION_3_2_3_SORTING_EXPECTED_ORDER


@pytest.mark.parametrize(
    ("hex_bits", "expected", "comment"),
    [pytest.param(*row, id=f"{row[0]} {row[2] or row[1]}") for row in APPENDIX_B_TABLE_1 if row[1]],
)
def test_appendix_b_number_serialisation(hex_bits, expected, comment):
    value = ieee754(hex_bits)
    assert canonical_json(value) == expected
    assert canonical_json([value]) == f"[{expected}]"


@pytest.mark.parametrize(
    ("hex_bits", "comment"),
    [pytest.param(row[0], row[2], id=row[2]) for row in APPENDIX_B_TABLE_1 if row[1] is None],
)
def test_appendix_b_nan_and_infinity_are_rejected(hex_bits, comment):
    value = ieee754(hex_bits)
    assert math.isnan(value) or math.isinf(value)
    with pytest.raises(ValueError):
        canonical_json(value)
    with pytest.raises(ValueError):
        canonical_json({"n": [value]})


def test_section_3_2_2_2_lone_surrogates_are_rejected():
    # §3.2.2.2: invalid Unicode data like "lone surrogates" MUST cause the implementation to
    # terminate with an error. Python's str can hold one; UTF-8 cannot encode it.
    with pytest.raises(ValueError):
        canonical_json("\udead")
    with pytest.raises(ValueError):
        canonical_json({"\udead": 1})


def test_section_3_2_1_no_whitespace_and_section_3_2_2_2_string_escapes():
    # §3.2.1: no whitespace. §3.2.2.2: \b \t \n \f \r short escapes, other controls as lowercase \uhhhh,
    # only " and \ escaped otherwise; "/", DEL and non-ASCII serialised as is.
    obj = {"b": "\b\t\n\f\r\x00\x1f", "a": '"\\/\x7f\u00e9'}
    assert canonical_json(obj) == '{"a":"\\"\\\\/\x7f\u00e9","b":"\\b\\t\\n\\f\\r\\u0000\\u001f"}'


def test_python_ints_are_serialised_exactly():
    # Not an RFC vector. The record stores tier, seq and counts as Python ints; they stay exact
    # (I-JSON, RFC 8785 §3.1, asks callers to keep them within +/-2**53 anyway).
    out = canonical_json({"tier": 1, "n": -0, "big": 9007199254740993})
    assert out == '{"big":9007199254740993,"n":0,"tier":1}'
    assert canonical_json([True, False, None]) == "[true,false,null]"
