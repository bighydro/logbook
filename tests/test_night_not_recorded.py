"""A night the record does not place reads `not recorded`, never `in transit`: the Day (`logbook day`),
the Day page and Today say `in transit` only when the record holds a flight or a move across that night.
The JSON keeps `in_transit` as SPEC §3.2.3 rule 8 defines it (a night with no stay): only the words change.
Synthetic Oslo persona, who does not exist."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from persona import HOME, TZ, ZURICH, dwell, flight, travel, utc

from logbook import cli
from logbook.contrib import serve
from logbook.core.store import Logbook

DRIVE = "2026-06-10"  # the record's first day: home in the evening, then on the road through the night
ZURICH_DAY = "2026-06-11"
FLOWN = "2026-06-12"  # Zürich until 21:00, then the 23:00 flight home, no point until morning


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(
        dwell(DRIVE, "10:00", "21:00", HOME)
        + travel(DRIVE, "21:00", "07:45", HOME, ZURICH, steps=24, end_day=ZURICH_DAY)
        + dwell(ZURICH_DAY, "07:45", "24:00", ZURICH)
        + dwell(FLOWN, "00:00", "21:00", ZURICH)
        + [flight(FLOWN, "562", "ZRH", "OSL", utc(FLOWN, "23:00"), utc("2026-06-13", "01:30"))]
        + dwell("2026-06-13", "09:00", "24:00", HOME)
    )
    (lb.root / "places.json").write_text(
        json.dumps({"Home": {"lat": HOME[0], "lon": HOME[1], "radius_m": 120, "kind": "home"}}),
        encoding="utf-8",
    )
    return lb


def _day(capsys: pytest.CaptureFixture[str], day: str) -> dict[str, str]:
    cli.main(["day", day])
    rows: dict[str, str] = {}
    for row in capsys.readouterr().out.splitlines()[1:]:
        label, _, text = row.strip().partition("  ")
        rows.setdefault(label, text.strip())
    return rows


def _json(capsys: pytest.CaptureFixture[str], day: str) -> dict[str, Any]:
    cli.main(["day", day, "--json"])
    data: dict[str, Any] = json.loads(capsys.readouterr().out)
    return data


def test_a_night_with_no_line_is_not_recorded_and_the_json_is_unchanged(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = _day(capsys, DRIVE)
    assert rows["night before"] == "not recorded", "nothing places the night of the 9th"
    assert "in transit" not in rows["night before"]
    data = _json(capsys, DRIVE)
    assert data["nights"]["before"]["in_transit"] is True, "SPEC §3.2.3 rule 8: a night with no stay"
    assert "transit" not in {k for k in data if k != "nights"}, "the Day's object is unchanged"


def test_a_move_through_the_night_is_in_transit_on_both_days(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _day(capsys, DRIVE)["night after"] == "in transit", "on the road from 21:00 to 07:45"
    assert _day(capsys, ZURICH_DAY)["night before"] == "in transit"


def test_a_flight_across_the_night_is_in_transit(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    assert _day(capsys, FLOWN)["night after"] == "in transit", "XY 562 left at 23:00"
    assert _day(capsys, "2026-06-13")["night before"] == "in transit", (
        "the review: one night reads one way from both Days, though the flight is dated the 12th"
    )


def test_a_day_with_no_line_at_all_has_nights_not_recorded(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = _day(capsys, "2026-07-20")
    assert rows["night before"] == "not recorded" and rows["night after"] == "not recorded"


def _site(lb: Logbook, day: str) -> serve.Site:
    at = datetime.fromisoformat(f"{day}T07:00:00").replace(tzinfo=ZoneInfo(TZ))
    return serve.Site(lb, now=lambda: at)


def _text(page: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", page))


def test_the_day_page_says_the_same(lb: Logbook) -> None:
    page = _text(_site(lb, ZURICH_DAY).respond(f"/day/{DRIVE}", "").body.decode("utf-8"))
    assert re.search(r"night before\s*not recorded", page), page[:2000]
    assert re.search(r"night after\s*in transit", page)


def test_today_says_last_night_not_recorded(lb: Logbook) -> None:
    quiet = _text(_site(lb, DRIVE).respond("/", "").body.decode("utf-8"))
    assert "Last night: not recorded" in quiet and "Last night in transit" not in quiet
    moving = _text(_site(lb, ZURICH_DAY).respond("/", "").body.decode("utf-8"))
    assert "Last night in transit" in moving
    landed = _text(_site(lb, "2026-06-13").respond("/", "").body.decode("utf-8"))
    assert "Last night in transit" in landed, "Today and the Day of the 13th say the same night the same way"
    day = _text(_site(lb, "2026-06-13").respond("/day/2026-06-13", "").body.decode("utf-8"))
    assert re.search(r"night before\s*in transit", day)
