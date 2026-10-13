"""The Night line of the Day: when the owner slept, how long, and the training minutes of the day,
derived at read time from the `health-sample/v1` lines already in the record (RFC 0014) — no line is
written. A night is the run of asleep stages of one device with no gap over two hours, and it belongs
to the local day its last stage ends in, under the record's `day_start` (RFC 0036).

The record is the Oslo persona's, who does not exist: the night of 12 to 13 October 2026 (CEST,
UTC+2), from 23:10 to 06:40 local with ten minutes awake at 02:00, so it runs across a 06:00
boundary; a run on the 13th that the watch and a phone app both recorded; steps on the 13th, and on
the 14th with no sleep."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from persona import TZ, utc

from logbook import cli
from logbook.core import day as day_reader
from logbook.core import health
from logbook.core.store import Logbook

EN_DASH = "\u2013"
WATCH, PHONE = "Watch7,1", "iPhone17,1"
NIGHT = [  # (stage, local start, local end): the night of the 12th to the 13th
    ("in_bed", "2026-10-12 23:00", "2026-10-13 07:00"),
    ("core", "2026-10-12 23:10", "2026-10-13 01:00"),
    ("deep", "2026-10-13 01:00", "2026-10-13 02:00"),
    ("awake", "2026-10-13 02:00", "2026-10-13 02:10"),
    ("core", "2026-10-13 02:10", "2026-10-13 04:30"),
    ("rem", "2026-10-13 04:30", "2026-10-13 05:45"),
    ("core", "2026-10-13 05:45", "2026-10-13 06:40"),  # across 06:00
    ("awake", "2026-10-13 06:40", "2026-10-13 06:50"),
]
ASLEEP_S = 7 * 3600 + 20 * 60  # 23:10 to 06:40 less the ten minutes awake


def _at(local: str) -> str:
    day, clock = local.split()
    return utc(day, clock)


def _health(at: str, end: str | None, type_: str, value: float, device: str, **extra: Any) -> dict[str, Any]:
    unit = {"sleep": "s", "workout": "s", "steps": "count"}[type_]
    payload = {
        "schema": "health-sample/v1",
        "raw_id": f"{type_}:{at}:{device}",
        "type": type_,
        "value": value,
        "unit": unit,
        "device": device,
        **extra,
    }
    return {"at": at, "end": end, "source": "apple-health", "kind": "health", "tier": 3, "payload": payload}


def _stage(stage: str, start: str, end: str, device: str = WATCH) -> dict[str, Any]:
    a, b = _at(start), _at(end)
    seconds = (datetime.fromisoformat(b[:-1]) - datetime.fromisoformat(a[:-1])).total_seconds()
    return _health(a, b, "sleep", seconds, device, stage=stage)


def _night_drafts() -> list[dict[str, Any]]:
    return [_stage(stage, start, end) for stage, start, end in NIGHT]


def _workouts() -> list[dict[str, Any]]:
    """A run on the 13th, 17:30 to 18:15, that the watch and a phone app both recorded: one training."""
    return [
        _health(
            _at("2026-10-13 17:30"),
            _at("2026-10-13 18:15"),
            "workout",
            45 * 60,
            WATCH,
            extra={"activity": "running", "activity_type": 37},
        ),
        _health(
            _at("2026-10-13 17:32"),
            _at("2026-10-13 18:10"),
            "workout",
            38 * 60,
            PHONE,
            extra={"activity": "running", "activity_type": 37},
        ),
    ]


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "Logbook", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    steps = [
        _health(_at("2026-10-13 12:00"), _at("2026-10-13 12:15"), "steps", 700, PHONE),
        _health(_at("2026-10-14 12:00"), _at("2026-10-14 12:15"), "steps", 900, PHONE),
    ]
    lb.append_many([*_night_drafts(), *_workouts(), *steps])
    return lb


def _text(capsys: pytest.CaptureFixture[str], day: str) -> list[str]:
    cli.main(["day", day, "--no-anniversaries"])
    return capsys.readouterr().out.splitlines()


def _night_rows(rows: list[str]) -> list[str]:
    return [row for row in rows if row[2:15].strip() == "night"]


# -- the night across the 06:00 boundary ------------------------------------------------------------------


def test_a_night_across_the_boundary_is_the_day_it_ends_in(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    lb.set_meta(day_start="06:00")
    head, seq = lb.meta["head"], lb.meta["seq"]
    data = day_reader.read(lb, "2026-10-13")
    night = data["night"]
    assert night["start"] == _at("2026-10-12 23:10") and night["end"] == _at("2026-10-13 06:40")
    assert night["start_local"] == "2026-10-12T23:10:00+02:00"
    assert night["end_local"] == "2026-10-13T06:40:00+02:00"
    assert night["asleep_s"] == ASLEEP_S, "in bed and awake are never sleep"
    assert night["device"] == WATCH
    assert len(night["lines"]) == 5, "every asleep stage, the one across 06:00 too"
    assert night["training"]["minutes"] == 45, "two devices recording one run are one training"
    assert len(night["training"]["lines"]) == 2
    assert "night" not in day_reader.read(lb, "2026-10-12"), (
        "the stages that end before 06:00 are not a night of the 12th: the night ends on the 13th"
    )
    assert (lb.meta["head"], lb.meta["seq"]) == (head, seq), "read time only: no line is written"

    rows = _text(capsys, "2026-10-13")
    assert _night_rows(rows) == [f"  night         slept 23:10{EN_DASH}06:40 · 7 h 20 min · training 45 min"]
    labels = [row[2:15].strip() for row in rows]
    assert labels.index("night") == labels.index("night before") + 1, "the night ended on the day"
    [health_row] = [row for row in rows if row.startswith("  health")]
    assert health_row == "  health        700 steps", "the night's sleep is said once, on the night row"
    assert _night_rows(_text(capsys, "2026-10-12")) == []


def test_at_midnight_the_same_night_is_the_same_days(lb: Logbook) -> None:
    night = day_reader.read(lb, "2026-10-13")["night"]
    assert night["asleep_s"] == ASLEEP_S and night["end"] == _at("2026-10-13 06:40")
    assert "night" not in day_reader.read(lb, "2026-10-12")


def test_a_day_without_health_data_has_no_night_row(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    lb.set_meta(day_start="06:00")
    for day in ("2026-10-14", "2026-10-20"):  # steps and no sleep; nothing at all
        data = day_reader.read(lb, day)
        assert "night" not in data, "the Day's object is as it was on a day with no night"
        assert _night_rows(_text(capsys, day)) == []
    cli.main(["day", "2026-10-14", "--json"])
    assert "night" not in json.loads(capsys.readouterr().out)


def test_a_night_without_training_says_none_and_a_nap_is_not_the_night() -> None:
    lines = [
        {**draft, "id": f"s{i}", "seq": i + 1}
        for i, draft in enumerate(
            [
                *_night_drafts(),
                _stage("asleep", "2026-10-13 15:00", "2026-10-13 15:25"),  # a nap: more than 2 h after
            ]
        )
    ]
    nights = health.nights(lines, TZ, "06:00")
    night = nights["2026-10-13"]
    assert night["asleep_s"] == ASLEEP_S, "the longest sleep that ends on the day is its night"
    assert health.training(lines, TZ, "06:00") == {}
    row = {**night, "training": None}
    assert day_reader.slept_text(row, TZ) == f"slept 23:10{EN_DASH}06:40 · 7 h 20 min"


def test_two_devices_are_two_observations_and_the_longer_night_is_taken() -> None:
    lines = [
        {**draft, "id": f"s{i}", "seq": i + 1}
        for i, draft in enumerate(
            [
                *_night_drafts(),
                _stage("asleep", "2026-10-13 00:30", "2026-10-13 05:00", device=PHONE),
                _stage("asleep", "2026-10-13 00:30", "2026-10-13 05:00", device=PHONE),  # written twice
            ]
        )
    ]
    night = health.nights(lines, TZ, None)["2026-10-13"]
    assert night["device"] == WATCH and night["asleep_s"] == ASLEEP_S, "never a sum across devices"


def test_the_health_row_keeps_day_start_after_a_sleep_line() -> None:
    """A steps bucket at 05:00 local on the 13th is the 12th's under 06:00, read after a sleep stage
    or before it."""
    lines = [
        {**draft, "id": f"s{i}", "seq": i + 1}
        for i, draft in enumerate(
            [
                _stage("core", "2026-10-13 01:00", "2026-10-13 02:00"),
                _health(_at("2026-10-13 05:00"), _at("2026-10-13 05:15"), "steps", 120, PHONE),
            ]
        )
    ]
    rows = {row["day"]: row for row in health.summary(lines, TZ, "06:00")}
    assert rows["2026-10-12"]["steps"] == 120
    assert "2026-10-13" not in rows
