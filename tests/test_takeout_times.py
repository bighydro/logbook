"""The clocks Google Takeout writes (`takeout/times.py`): RFC3339, the two English forms, and the
`YYYY-MM-DD HH:MM:SS UTC` form of the 2026 CSVs, all to one UTC instant."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook.adapters.takeout import times


@pytest.mark.parametrize(
    "text, at",
    [
        ("2026-10-01 06:59:59 UTC", "2026-10-01T06:59:59Z"),
        ("2026-10-01 06:59:59.123 UTC", "2026-10-01T06:59:59Z"),
        ("2026-10-01 06:59:59 GMT", "2026-10-01T06:59:59Z"),
        ("2026-10-01 06:59:59", "2026-10-01T06:59:59Z"),
        ("2026-10-01 08:59:59 +02:00", "2026-10-01T06:59:59Z"),
        ("2026-10-01T06:59:59.412Z", "2026-10-01T06:59:59Z"),
        ("Jun 15, 2026, 7:40:10 AM UTC", "2026-06-15T07:40:10Z"),
        (
            "Jun 15, 2026, 7:40:10" + chr(0x202F) + "AM UTC",
            "2026-06-15T07:40:10Z",
        ),  # the narrow no-break space
        ("Wednesday, June 10, 2026 at 11:30:05 AM UTC", "2026-06-10T11:30:05Z"),
    ],
)
def test_every_clock_reads_to_the_same_instant_and_keeps_its_spelling(text: str, at: str):
    assert times.parse(text) == (at, text)


@pytest.mark.parametrize(
    "text", ["", "   ", "yesterday", "2026-10-01 06:59:59 CET", "06:59:59 UTC", 42, None]
)
def test_what_is_not_a_known_clock_is_none(text: object):
    assert times.parse(text) == (None, "")
