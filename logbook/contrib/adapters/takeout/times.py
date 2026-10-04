"""The clocks Google Takeout writes, read to one RFC3339 UTC instant.

Takeout spells a time four ways across its products: RFC3339 with a `Z` and fractional seconds
(`2026-06-10T07:00:00.123Z`, My Activity and YouTube), a long English form (`Wednesday, June 10, 2026
at 11:30:05 AM UTC`, Google Chat), a short one (`Jun 10, 2026, 11:35:12 AM UTC`, the CSVs of Google
Pay, Google Meet and Access Log until 2026) and, in the CSVs Takeout writes today, a plain
`2026-10-01 06:59:59 UTC` (a date, a 24-hour clock, the zone's name). Newer exports put a narrow
no-break space before `AM`. `parse` reads all four and returns the instant to the second with the text
as the export spelled it, so a `raw_id` can carry the spelling (RFC 0017, 0018) and `at` the instant.
A zone name other than UTC or GMT is not interpreted: the export is UTC, and a reader that is not
sure says so (SPEC §2) rather than guess.
The HTML flavour of an export spells the owner's own zone by its abbreviation (`Mar 4, 2026,
10:00:00 AM CET`); `parse_in_zone` reads such a time in the record's zone when, and only when, that
zone uses that abbreviation at that wall-clock time, and `english_zone` names the abbreviation so a
reader can count what it could not place.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ENGLISH = (
    "%A, %B %d, %Y at %I:%M:%S %p",
    "%b %d, %Y, %I:%M:%S %p",
    "%B %d, %Y, %I:%M:%S %p",
    "%b %d, %Y, %I:%M %p",
)
UTC_NAMES = ("UTC", "GMT", "Z")
SPACES = str.maketrans({chr(0x202F): " ", chr(0xA0): " "})  # narrow and plain no-break spaces
OFFSET = re.compile(r" ([+-]\d{2}:?\d{2})$")  # `2026-10-01 08:59:59 +02:00`: the space before the offset


def parse(value: object) -> tuple[str | None, str]:
    """(`at` to the second in UTC, the string as the export spells it), or (None, "") when the
    value is not a time this module knows."""
    if not isinstance(value, str) or not value.strip():
        return None, ""
    text = " ".join(value.translate(SPACES).split())
    when = _iso(text)
    if when is None and (body := _without_zone(text)) is not None:
        when = _iso(body) or _english(body)
    if when is None:
        return None, ""
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), value


def _iso(text: str) -> datetime | None:
    """RFC3339, or ISO 8601 with a space for the `T`, with or without a zone; naive is UTC."""
    try:
        when = datetime.fromisoformat(OFFSET.sub(r"\1", text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo is not None else when.replace(tzinfo=UTC)


def _without_zone(text: str) -> str | None:
    """The text before a trailing `UTC`, `GMT` or `Z`; None when it ends in anything else."""
    words = text.split(" ")
    if len(words) < 2 or words[-1].upper() not in UTC_NAMES:
        return None
    return " ".join(words[:-1])


def _english(body: str) -> datetime | None:
    """A UTC instant from one of the English forms, None when the body is none of them."""
    naive = _strptime(body)
    return naive.replace(tzinfo=UTC) if naive is not None else None


def _strptime(body: str) -> datetime | None:
    for form in ENGLISH:
        try:
            return datetime.strptime(body, form)
        except ValueError:
            continue
    return None


def english_zone(value: object) -> str | None:
    """The zone name an English time ends with (`CET`, `UTC`, `PST`), or None when the value is not
    an English time with one."""
    if not isinstance(value, str) or not value.strip():
        return None
    words = " ".join(value.translate(SPACES).split()).split(" ")
    if len(words) < 2 or not words[-1].isalpha() or _strptime(" ".join(words[:-1])) is None:
        return None
    return words[-1]


def parse_in_zone(value: object, zone: str) -> tuple[str | None, str]:
    """An English time whose zone name is the abbreviation `zone` uses at that wall-clock time
    (`CET` in `Europe/Oslo` in March, `CEST` in June) read in that zone: (`at` in UTC, the text as
    spelled). (None, "") when the name is UTC (that is `parse`), another zone's, or the text is not
    a time: the reader says so rather than guess (SPEC §2)."""
    name = english_zone(value)
    if name is None or name.upper() in UTC_NAMES or not isinstance(value, str):
        return None, ""
    words = " ".join(value.translate(SPACES).split()).split(" ")
    naive = _strptime(" ".join(words[:-1]))
    try:
        tz = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        return None, ""
    assert naive is not None  # english_zone said the body is a time
    when = naive.replace(tzinfo=tz)
    if when.tzname() != name:
        return None, ""
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), value
