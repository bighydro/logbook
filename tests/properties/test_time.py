"""Time (SPEC §2: `at`, `end` and `recorded_at` are RFC 3339 UTC with a literal Z, `tz` an IANA name;
§3.2: every reader assigns every line to a local day by the record's zone; §3.2.2: an output instant
is UTC to the second, a `*_local` field the same instant in the record's zone; §3.2.7: a Day runs from
00:00 to 24:00 local). Stated for any instant and any zone the host knows: the day of a line is the
calendar date its wall clock reads there, midnight is where the day turns, a DST transition never
leaves an instant without a day or with two, and a duration is the real seconds elapsed, whatever the
offsets at either end."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from functools import cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from hypothesis import assume, given, settings
from hypothesis import strategies as st
from logbook.index import local_date
from logbook.store import utc

from logbook import stays
from properties.common import CI, instants, stamp

# Zones with a DST rule, a half-hour or quarter-hour offset, a 30-minute DST step, an offset past ±12,
# a transition at midnight, and none at all. A zone the host's database lacks is left out (SPEC §2).
WANTED = (
    "UTC",
    "Europe/Oslo",
    "Europe/London",
    "America/New_York",
    "America/Santiago",
    "America/Sao_Paulo",
    "Asia/Kolkata",
    "Asia/Tehran",
    "Australia/Lord_Howe",
    "Pacific/Chatham",
    "Pacific/Kiritimati",
    "Pacific/Pago_Pago",
    "Africa/Casablanca",
)


def known(names: tuple[str, ...]) -> list[str]:
    found = []
    for name in names:
        try:
            ZoneInfo(name)
        except ZoneInfoNotFoundError:
            continue
        found.append(name)
    return found


ZONES = known(WANTED)
START, END = datetime(1990, 1, 1, tzinfo=UTC), datetime(2040, 1, 1, tzinfo=UTC)
zones = st.sampled_from(ZONES)
anywhen = instants(START, END)


def wall(instant: datetime, zone: str) -> datetime:
    """The wall clock in `zone`, computed from the offset alone and not through `astimezone`'s date."""
    return instant.replace(tzinfo=None) + instant.astimezone(ZoneInfo(zone)).utcoffset()  # type: ignore[operator]


@cache
def transitions(zone: str, year: int) -> list[datetime]:
    """The instants in `year` at which the zone's offset changes, found by scanning at 15 minutes."""
    z = ZoneInfo(zone)
    found = []
    t = datetime(year, 1, 1, tzinfo=UTC)
    offset = t.astimezone(z).utcoffset()
    while t.year == year:
        t += timedelta(minutes=15)
        now = t.astimezone(z).utcoffset()
        if now != offset:
            found.append(t)
            offset = now
    return found


@settings(CI, max_examples=200)
@given(anywhen, zones)
def test_the_day_of_a_line_is_the_local_date_in_the_records_zone(instant: datetime, zone: str) -> None:
    """§3.2: a line is on the local day its `at` falls on in the record's zone — the date the wall
    clock reads there, which is the UTC instant plus the zone's offset at that instant."""
    assert local_date(stamp(instant), zone) == wall(instant, zone).date().isoformat()
    assert local_date(stamp(instant), "UTC") == instant.date().isoformat()


@settings(CI, max_examples=200)
@given(st.dates(date(1990, 1, 1), date(2039, 12, 31)), zones)
def test_the_last_second_of_a_day_and_the_first_of_the_next_are_consecutive_days(
    day: date, zone: str
) -> None:
    """§3.2.7: a Day runs from 00:00 to 24:00 local. A line at 23:59:59 and one a second later whose
    clock reads 00:00:00 are on consecutive days; the second line is on the day after, never the same
    day and never two days on."""
    z = ZoneInfo(zone)
    last = datetime.combine(day, time(23, 59, 59), tzinfo=z)
    assume(wall(last.astimezone(UTC), zone) == last.replace(tzinfo=None))  # 23:59:59 exists on this day
    after = last.astimezone(UTC) + timedelta(seconds=1)
    assume(wall(after, zone).time() == time(0, 0, 0))  # and the clock then reads midnight
    assert local_date(stamp(last), zone) == day.isoformat()
    assert local_date(stamp(after), zone) == (day + timedelta(days=1)).isoformat()


@settings(CI, max_examples=120)
@given(zones, st.integers(1990, 2039), st.data())
def test_a_dst_transition_never_leaves_an_instant_without_a_day_or_with_two(
    zone: str, year: int, data: st.DataObject
) -> None:
    """§3.2: every instant has exactly one local day. Around every offset change of the year — a gap,
    where a wall-clock hour does not exist, or a fold, where one happens twice — each instant is
    assigned one day, the one its wall clock reads, and two instants that read the same wall clock in
    a fold are both on that clock's day; the stamps `at` may carry (a literal Z, or an offset that
    `store.utc` turns into one) agree on it."""
    found = transitions(zone, year)
    assume(found)
    at = data.draw(st.sampled_from(found)) + timedelta(seconds=data.draw(st.integers(-3 * 3600, 3 * 3600)))
    day = local_date(stamp(at), zone)
    assert day == wall(at, zone).date().isoformat()
    assert local_date(stamp(at), zone) == day, "one day, every time it is asked"
    assert local_date(utc(at.astimezone(ZoneInfo(zone)).isoformat()), zone) == day
    date.fromisoformat(day)
    twin = at + timedelta(hours=1)  # in a fold, an hour later reads the same wall clock
    if wall(twin, zone) == wall(at, zone):
        assert local_date(stamp(twin), zone) == day


@settings(CI, max_examples=200)
@given(anywhen, st.integers(1, 400 * 86400), zones)
def test_a_duration_across_a_dst_change_is_the_real_elapsed_seconds(
    start: datetime, seconds: int, zone: str
) -> None:
    """§2 and §3.2.2: timestamps denote instants and a duration is the difference of two instants, so
    a span that crosses an offset change is its real length in seconds — read from the Z stamps the
    record stores, from local stamps with their offsets, and as a stay's `duration_s`."""
    end = start + timedelta(seconds=seconds)
    a, b = stays.instant(stamp(start)), stays.instant(stamp(end))
    assert a is not None and b is not None and (b - a).total_seconds() == seconds
    z = ZoneInfo(zone)
    local_a, local_b = utc(start.astimezone(z).isoformat()), utc(end.astimezone(z).isoformat())
    assert (local_a, local_b) == (stamp(start), stamp(end))
    assert stays.Segment("stay", None, a, b, 2).duration_s == seconds
