"""One phone-number normalisation for every adapter that writes a `phone` ref (RFC 0006).

A resolution joins lines by `ref`, so two adapters that see the same number must write the same
value: `+4790000001` from an address book and `+4790000001` from a chat store meet on one resolution.
This module is that agreement. It knows nothing about any source.
"""

from __future__ import annotations

import re

PUNCTUATION = re.compile(r"[\s\-.()]+")


def normalise(entered: str, prefix: str) -> tuple[str, bool]:
    """(ref value, unnormalised). Empty when nothing usable is left.

    Spaces, dashes, dots and parentheses are dropped; a `00` prefix becomes `+`. A number with no
    country code gets `+<prefix>` when `prefix` is set, after exactly one leading `0` (the national
    trunk prefix) is dropped: `07700 900123` with prefix 44 is `+447700900123`. A number that already
    starts with the prefix digits but no `+` is ambiguous (a trunk-less national number or a country
    code typed without `+`), so it is kept as entered and flagged. With no prefix the number is kept
    as entered (punctuation stripped) and flagged. Anything that is not digits after that is flagged
    too."""
    number = PUNCTUATION.sub("", entered)
    if number.startswith("00"):
        number = "+" + number[2:]
    digits = number[1:] if number.startswith("+") else number
    if not digits.isdigit() or not digits.isascii():
        return number, bool(number)
    if number.startswith("+"):
        return number, False
    if prefix and not number.startswith(prefix):
        national = number.removeprefix("0")
        if national:
            return f"+{prefix}{national}", False
    return number, True
