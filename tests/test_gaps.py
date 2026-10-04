"""`logbook sources --gaps [--since DAY] [--expect SOURCE...]`: where each source went quiet, read
from the index alone — the last line's time, the longest silent stretch and the local days with no
line — so a stopped phone or a dead sync is seen on one screen. Every line here is synthetic; the
clock is pinned, the record lives in a temp dir."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from logbook import cli
from logbook.contrib import gaps
from logbook.core.index import Index
from logbook.core.store import Logbook

TZ = "Europe/Oslo"  # CEST in September: local midnight is 22:00Z the evening before
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)  # a Wednesday afternoon in Oslo


def _location(lb: Logbook, at: str, n: int) -> None:
    lb.append(
        at=at,
        source="sim-phone",
        kind="location",
        tier=1,
        payload={"schema": "location/v1", "lat": 59.91, "lon": 10.75, "raw_id": f"trk:{n}"},
    )


def _event(lb: Logbook, at: str, title: str) -> None:
    lb.append(
        at=at,
        source="sim-calendar",
        kind="event",
        tier=1,
        payload={"schema": "event/v1", "title": title, "raw_id": f"cal:{title}"},
    )


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """A phone that sent two points a day from 1 to 20 September and then stopped; a calendar with
    entries on the 1st, 5th, 8th and 29th and one in the future; one note on the 10th."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.setattr(gaps, "now", lambda: NOW)
    n = 0
    for day in range(1, 21):
        for hour in (7, 19):
            n += 1
            _location(lb, f"2026-09-{day:02d}T{hour:02d}:00:00Z", n)
    _event(lb, "2026-09-01T08:00:00Z", "Standup")
    _event(lb, "2026-09-05T08:00:00Z", "Review")
    _event(lb, "2026-09-08T08:00:00Z", "Planning")
    _event(lb, "2026-09-29T08:00:00Z", "Retro")
    _event(lb, "2026-10-03T08:00:00Z", "Offsite")  # a calendar names the future; not a line of today
    lb.append(
        at="2026-09-10T20:00:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "text": "quiet evening"},
    )
    return lb


def _by_source(data: dict) -> dict[str, dict]:  # type: ignore[type-arg]
    return {s["source"]: s for s in data["sources"]}


# -- the report ----------------------------------------------------------------------------------


def test_every_source_with_lines_most_lines_first(lb: Logbook):
    data = gaps.report(lb)
    assert [s["source"] for s in data["sources"]] == ["sim-phone", "sim-calendar", "manual"]
    assert data["today"] == "2026-09-30"
    assert data["since"] is None
    assert data["timezone"] == TZ


def test_a_stopped_phone_shows_its_last_line_and_the_silence_since(lb: Logbook):
    phone = _by_source(gaps.report(lb))["sim-phone"]
    assert phone["lines"] == 40
    assert phone["first"] == "2026-09-01T07:00:00Z"
    assert phone["last"] == "2026-09-20T19:00:00Z"
    silence = phone["silence"]
    assert silence["from"] == "2026-09-20T19:00:00Z"
    assert silence["to"] is None  # open: it runs to now
    assert silence["seconds"] == (NOW - datetime(2026, 9, 20, 19, tzinfo=UTC)).total_seconds()
    assert phone["missing_days"] == [f"2026-09-{d:02d}" for d in range(21, 31)]
    assert phone["flagged"] is True


def test_a_future_dated_line_is_outside_the_range(lb: Logbook):
    cal = _by_source(gaps.report(lb))["sim-calendar"]
    assert cal["lines"] == 4  # the offsite on 3 October is not counted
    assert cal["last"] == "2026-09-29T08:00:00Z"
    silence = cal["silence"]
    assert (silence["from"], silence["to"]) == ("2026-09-08T08:00:00Z", "2026-09-29T08:00:00Z")
    assert silence["seconds"] == 21 * 86400
    assert "2026-09-30" in cal["missing_days"]
    assert "2026-09-06" in cal["missing_days"] and "2026-09-05" not in cal["missing_days"]
    assert len(cal["missing_days"]) == 30 - 4


def test_the_range_starts_at_the_source_first_day_without_since(lb: Logbook):
    note = _by_source(gaps.report(lb))["manual"]
    assert note["missing_days"][0] == "2026-09-11"  # nothing is missing before a source began
    assert note["silence"] == {
        "from": "2026-09-10T20:00:00Z",
        "to": None,
        "seconds": (NOW - datetime(2026, 9, 10, 20, tzinfo=UTC)).total_seconds(),
    }


def test_since_cuts_the_range_and_counts_the_silence_from_its_midnight(lb: Logbook):
    data = gaps.report(lb, since="2026-09-15")
    assert data["since"] == "2026-09-15"
    phone = _by_source(data)["sim-phone"]
    assert phone["lines"] == 12
    assert phone["first"] == "2026-09-15T07:00:00Z"
    assert phone["missing_days"] == [f"2026-09-{d:02d}" for d in range(21, 31)]
    cal = _by_source(data)["sim-calendar"]
    assert cal["lines"] == 1
    # local midnight on the 15th is 22:00Z on the 14th (CEST); the calendar was silent from there
    assert cal["silence"]["from"] == "2026-09-14T22:00:00Z"
    assert cal["silence"]["to"] == "2026-09-29T08:00:00Z"
    assert cal["missing_days"][0] == "2026-09-15"
    assert "manual" not in _by_source(data)  # no line in the range, not expected: not listed


def test_a_source_alive_within_a_day_is_not_flagged(lb: Logbook, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(gaps, "now", lambda: datetime(2026, 9, 21, 6, 0, tzinfo=UTC))
    phone = _by_source(gaps.report(lb))["sim-phone"]
    assert phone["silence"]["seconds"] == 12 * 3600  # between an evening and the next morning
    assert phone["missing_days"] == []  # today has had no line yet: it is not a missing day
    assert phone["flagged"] is False


def test_expect_lists_only_the_named_sources_and_flags_one_with_no_lines(lb: Logbook):
    data = gaps.report(lb, expect=["sim-phone", "imessage"])
    assert [s["source"] for s in data["sources"]] == ["sim-phone", "imessage"]
    missing = _by_source(data)["imessage"]
    assert missing["lines"] == 0 and missing["last"] is None and missing["silence"] is None
    assert missing["missing_days"] == []
    assert missing["flagged"] is True
    assert data["flagged"] == ["sim-phone", "imessage"]


def test_the_report_reads_the_index_and_never_the_files(lb: Logbook, monkeypatch: pytest.MonkeyPatch):
    with lb.index():
        pass  # built; from here the files are not opened

    def refuse(*_a: object, **_k: object) -> None:
        raise AssertionError("a line was read from the files")

    monkeypatch.setattr(Index, "_read", refuse)
    monkeypatch.setattr(Index, "of_kind", refuse)
    data = gaps.report(lb, expect=["sim-phone", "sim-calendar", "manual"])
    assert len(data["sources"]) == 3


def test_an_empty_record_has_no_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    lb = Logbook.init(tmp_path / "empty", TZ)
    monkeypatch.setattr(gaps, "now", lambda: NOW)
    assert gaps.report(lb)["sources"] == []
    data = gaps.report(lb, expect=["sim-phone"])
    assert data["sources"][0]["flagged"] is True


def test_since_after_today_is_refused(lb: Logbook):
    with pytest.raises(ValueError, match="after today"):
        gaps.report(lb, since="2026-10-01")


# -- text ----------------------------------------------------------------------------------------


def test_missing_days_collapse_into_runs():
    assert gaps.runs([]) == ""
    assert gaps.runs(["2026-09-21"]) == "2026-09-21"
    assert gaps.runs(["2026-09-21", "2026-09-22", "2026-09-23"]) == "2026-09-21..2026-09-23"
    days = ["2026-09-02", "2026-09-03", "2026-09-06", "2026-09-09", "2026-09-10", "2026-09-30"]
    assert gaps.runs(days) == "2026-09-02..2026-09-03, 2026-09-06, 2026-09-09..2026-09-10, +1 run"
    assert (
        gaps.runs(days, limit=4) == "2026-09-02..2026-09-03, 2026-09-06, 2026-09-09..2026-09-10, 2026-09-30"
    )


def test_durations_read_as_days_hours_or_minutes():
    assert gaps.duration(9 * 86400 + 17 * 3600 + 59) == "9d 17h"
    assert gaps.duration(86400) == "1d 0h"
    assert gaps.duration(12 * 3600 + 30 * 60) == "12h 30m"
    assert gaps.duration(45) == "0m"
    assert gaps.duration(90) == "1m"


# -- the command ---------------------------------------------------------------------------------


def test_sources_gaps_is_one_screen(lb: Logbook, capsys):
    cli.main(["sources", "--gaps"])
    out = capsys.readouterr().out
    rows = {line.split()[0]: line for line in out.splitlines() if line.startswith("  ")}
    phone = rows["sim-phone"]
    assert "2026-09-20 21:00" in phone  # the last line, in the record's zone
    assert "9d 17h" in phone and "since 2026-09-20 21:00" in phone
    assert "10  2026-09-21..2026-09-30" in phone
    cal = rows["sim-calendar"]
    assert "2026-09-29 10:00" in cal and "21d 0h" in cal and "2026-09-08 10:00 → 2026-09-29 10:00" in cal
    assert "3 sources" in out and "2026-09-30" in out
    assert "!" not in out  # nothing is flagged without --expect


def test_sources_gaps_expect_flags_and_exits_1(lb: Logbook, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["sources", "--gaps", "--expect", "sim-phone", "imessage", "--since", "2026-09-15"])
    assert e.value.code == 1
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert sum(line.startswith("! ") for line in lines) == 2
    assert any(line.startswith("! imessage") and "no lines" in line for line in lines)
    assert "manual" not in out and "sim-calendar" not in out
    assert "2 of 2 expected sources flagged: sim-phone, imessage" in out


def test_sources_gaps_expect_exits_0_when_every_source_is_alive(lb: Logbook, capsys, monkeypatch):
    monkeypatch.setattr(gaps, "now", lambda: datetime(2026, 9, 21, 6, 0, tzinfo=UTC))
    cli.main(["sources", "--gaps", "--expect", "sim-phone"])
    out = capsys.readouterr().out
    assert "1 expected source, none flagged" in out
    assert not any(line.startswith("! ") for line in out.splitlines())


def test_sources_gaps_json(lb: Logbook, capsys):
    cli.main(["sources", "--gaps", "--json", "--since", "2026-09-15"])
    data = json.loads(capsys.readouterr().out)
    assert data["since"] == "2026-09-15" and data["today"] == "2026-09-30"
    assert data["sources"][0]["source"] == "sim-phone"
    assert data["sources"][0]["missing_days"][0] == "2026-09-21"


def test_sources_gaps_on_an_empty_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    lb = Logbook.init(tmp_path / "empty", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.setattr(gaps, "now", lambda: NOW)
    cli.main(["sources", "--gaps"])
    assert "no lines" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        ["sources", "--since", "2026-09-15"],
        ["sources", "--expect", "sim-phone"],
        ["sources", "--json"],
        ["sources", "--gaps", "--since", "15.09.2026"],
        ["sources", "--gaps", "--since", "2026-10-01"],
    ],
)
def test_sources_gaps_usage_errors_exit_2(lb: Logbook, capsys, argv: list[str]):
    with pytest.raises(SystemExit) as e:
        cli.main(argv)
    assert e.value.code == 2
    assert capsys.readouterr().err


def test_sources_without_gaps_is_unchanged(lb: Logbook, capsys):
    cli.main(["sources"])
    out = capsys.readouterr().out
    assert "adapters," in out and "sim-phone" not in out
