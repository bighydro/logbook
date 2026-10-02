"""The clocks Google Takeout writes, read to one RFC3339 UTC instant.

Takeout spells a time three ways across its products: RFC3339 with a `Z` and fractional seconds
(`2026-06-10T07:00:00.123Z`, My Activity and YouTube), a long English form (`Wednesday, June 10, 2026
at 11:30:05 AM UTC`, Google Chat) and a short one (`Jun 10, 2026, 11:35:12 AM UTC`, the CSVs of
Google Pay and Access Log). Newer exports put a narrow no-break space before `AM`. `parse` reads all
three and returns the instant to the second with the text as the export spelled it, so a `raw_id`
can carry the spelling (RFC 0017, 0018) and `at` the instant. A zone name other than UTC or GMT is
not interpreted: the export is UTC, and a reader that is not sure says so (SPEC §2) rather than guess.
"""

from __future__ import annotations

from datetime import UTC, datetime

ENGLISH = (
    "%A, %B %d, %Y at %I:%M:%S %p",
    "%b %d, %Y, %I:%M:%S %p",
    "%B %d, %Y, %I:%M:%S %p",
    "%b %d, %Y, %I:%M %p",
)
UTC_NAMES = ("UTC", "GMT", "Z")
SPACES = str.maketrans({chr(0x202F): " ", chr(0xA0): " "})  # narrow and plain no-break spaces


def parse(value: object) -> tuple[str | None, str]:
    """(`at` to the second in UTC, the string as the export spells it), or (None, "") when the
    value is not a time this module knows."""
    if not isinstance(value, str) or not value.strip():
        return None, ""
    text = " ".join(value.translate(SPACES).split())
    when = _iso(text)
    if when is None:
        when = _english(text)
    if when is None:
        return None, ""
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), value


def _iso(text: str) -> datetime | None:
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo is not None else when.replace(tzinfo=UTC)


def _english(text: str) -> datetime | None:
    words = text.split(" ")
    if len(words) < 2 or words[-1].upper() not in UTC_NAMES:
        return None
    body = " ".join(words[:-1])
    for form in ENGLISH:
        try:
            return datetime.strptime(body, form).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None
