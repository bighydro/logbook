"""`logbook derive stays`: the first reader of the record. Synthetic tracks of the Oslo persona,
who does not exist, turned into stays, stops and moves; nothing is ever appended by it."""

from __future__ import annotations

import json
import math
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from logbook import cli, stays
from logbook.cli import EN_DASH
from logbook.store import Logbook

TZ = "Europe/Oslo"
DAY = "2026-06-10"  # CEST, UTC+2
HOME = (59.9139, 10.7522)  # synthetic: a point in central Oslo
OFFICE = (59.9100, 10.7600)  # ~600 m from HOME
CAFE = (59.9200, 10.7400)  # ~1.1 km from HOME
MARINA = (59.9050, 10.7350)
FJORD = (59.8500, 10.6000)  # out on the fjord
OSL = (60.1939, 11.1004)  # Oslo Gardermoen
BGO = (60.2934, 5.2181)  # Bergen Flesland
TROMSO = (69.6833, 18.9189)


def _utc(day: str, clock: str) -> str:
    """A local Oslo wall-clock time on `day` as the RFC3339 UTC stamp a line carries."""
    local = datetime.fromisoformat(f"{day}T{clock}:00").replace(tzinfo=ZoneInfo(TZ))
    return local.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")


def _point(
    at: str, where: tuple[float, float], subject: str | None = None, source: str = "dawarich"
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "location/v1",
        "lat": where[0],
        "lon": where[1],
        "accuracy_m": 12,
        "raw_id": f"{source}:{subject or 'owner'}:{at}",
    }
    if subject:
        payload["subject"] = subject
    return {"at": at, "source": source, "kind": "location", "tier": 1, "payload": payload}


def _jitter(where: tuple[float, float], metres: float, rng: random.Random) -> tuple[float, float]:
    """`where` displaced by up to `metres` in a random direction: GPS noise."""
    bearing = rng.uniform(0, 2 * math.pi)
    d = rng.uniform(0, metres)
    dlat = d * math.cos(bearing) / 111_320
    dlon = d * math.sin(bearing) / (111_320 * math.cos(math.radians(where[0])))
    return (where[0] + dlat, where[1] + dlon)


def _dwell(
    day: str,
    start: str,
    end: str,
    where: tuple[float, float],
    every_min: int = 2,
    noise_m: float = 40,
    subject: str | None = None,
    seed: int = 1,
) -> list[dict[str, Any]]:
    """Points every `every_min` minutes from `start` to `end` local, jittered around `where`."""
    rng = random.Random(seed)
    t0 = datetime.fromisoformat(f"{day}T{start}:00").replace(tzinfo=ZoneInfo(TZ))
    t1 = datetime.fromisoformat(f"{day}T{end}:00").replace(tzinfo=ZoneInfo(TZ))
    out = []
    t = t0
    while t <= t1:
        stamp = t.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
        out.append(_point(stamp, _jitter(where, noise_m, rng), subject))
        t += timedelta(minutes=every_min)
    return out


def _travel(
    day: str,
    start: str,
    end: str,
    a: tuple[float, float],
    b: tuple[float, float],
    steps: int = 6,
    subject: str | None = None,
) -> list[dict[str, Any]]:
    """Points on a straight line from `a` (at `start`) to `b` (at `end`), the ends excluded."""
    t0 = datetime.fromisoformat(f"{day}T{start}:00").replace(tzinfo=ZoneInfo(TZ))
    t1 = datetime.fromisoformat(f"{day}T{end}:00").replace(tzinfo=ZoneInfo(TZ))
    out = []
    for i in range(1, steps):
        f = i / steps
        t = t0 + (t1 - t0) * f
        stamp = t.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
        out.append(_point(stamp, (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f), subject))
    return out


def _photo(at: str, where: tuple[float, float] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "photo/v1",
        "asset_id": f"p-{at}",
        "media": "image",
        "provenance": "camera",
    }
    if where:
        payload["lat"], payload["lon"] = where
    return {"at": at, "source": "immich", "kind": "photo", "tier": 1, "payload": payload}


def _event(at: str, end: str, title: str = "Standup") -> dict[str, Any]:
    return {
        "at": at,
        "end": end,
        "source": "ios-calendar",
        "kind": "event",
        "tier": 1,
        "payload": {"schema": "event/v1", "raw_id": f"e-{at}", "title": title, "all_day": False},
    }


def _message(at: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "whatsapp",
        "kind": "message",
        "tier": 2,
        "payload": {
            "schema": "message/v1",
            "raw_id": f"m-{at}",
            "chat": {"id": "4790000001@s.whatsapp.net", "type": "direct"},
            "from_me": True,
            "text": "on my way",
        },
    }


def _record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, drafts: list[dict[str, Any]]) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(drafts)
    return lb


def _derive(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(["derive", "stays", *args])
    return capsys.readouterr().out


def _derive_json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    text = _derive(capsys, "--json", *args)
    data: dict[str, Any] = json.loads(text)
    return data


def _owner(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in data["segments"] if s["subject"] is None]


# -- settings and places -----------------------------------------------------------------------------


def test_settings_file_is_written_with_defaults_on_first_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = _record(tmp_path, monkeypatch, [])
    path = lb.root / "policy" / "stays.json"
    _derive(capsys, "--day", DAY, "--dry-run")
    assert not path.exists(), "a dry run writes nothing, not even the settings"
    _derive(capsys, "--day", DAY)
    assert path.exists()
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["stay_min_s"] == 1200
    assert written["merge_gap_s"] == 600
    assert written["radius_m"] == 150
    assert written["night"] == ["22:00", "08:00"]
    assert written["modes"]["flight_min_kmh"] == 150
    # An edited file is honoured and never rewritten.
    written["stay_min_s"] = 60
    path.write_text(json.dumps(written), encoding="utf-8")
    assert stays.read_settings(lb.root).stay_min_s == 60
    _derive(capsys, "--day", DAY)
    assert json.loads(path.read_text(encoding="utf-8"))["stay_min_s"] == 60
    head_before = lb.meta["head"]
    assert lb.meta["head"] == head_before and lb.meta["seq"] == 0, "derive never appends"


def test_places_file_names_a_stay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = _record(tmp_path, monkeypatch, _dwell(DAY, "08:00", "09:00", HOME))
    (lb.root / "places.json").write_text(
        json.dumps({"Home": {"lat": HOME[0], "lon": HOME[1], "radius_m": 120}}), encoding="utf-8"
    )
    data = _derive_json(capsys, "--day", DAY)
    [stay] = _owner(data)
    assert stay["kind"] == "stay"
    assert stay["place"] == "Home"
    text = _derive(capsys, "--day", DAY)
    assert "Home" in text


# -- stays, noise, merging ----------------------------------------------------------------------------


def test_gps_noise_is_one_stay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An hour at home, a point every two minutes with up to 40 m of noise, is one stay."""
    _record(tmp_path, monkeypatch, _dwell(DAY, "08:00", "09:00", HOME, noise_m=40))
    data = _derive_json(capsys, "--day", DAY)
    [stay] = _owner(data)
    assert stay["kind"] == "stay"
    assert stay["start"] == _utc(DAY, "08:00") and stay["end"] == _utc(DAY, "09:00")
    assert stay["points"] == 31
    assert abs(stay["lat"] - HOME[0]) < 0.001 and abs(stay["lon"] - HOME[1]) < 0.001
    assert stay["place"] is None
    assert stay["attached"] == {}
    assert stay["promoted"] is False


def test_a_single_outlier_point_does_not_break_a_stay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    drafts = _dwell(DAY, "08:00", "09:00", HOME, noise_m=10)
    drafts.append(_point(_utc(DAY, "08:31"), (HOME[0] + 0.004, HOME[1])))  # a 450 m jump for one fix
    _record(tmp_path, monkeypatch, drafts)
    data = _derive_json(capsys, "--day", DAY)
    [stay] = _owner(data)
    assert stay["kind"] == "stay"
    assert stay["points"] == 31
    assert data["noise_points"] == 1


def test_a_silence_at_the_same_place_never_splits_a_stay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The tracker sends nothing while the owner is still: a gap whose next point is back inside
    the radius continues the stay, however long it was."""
    quiet = _dwell(DAY, "10:00", "10:30", HOME) + _dwell(DAY, "10:45", "11:15", HOME, seed=2)
    _record(tmp_path, monkeypatch, quiet)
    [stay] = _owner(_derive_json(capsys, "--day", DAY))
    assert stay["kind"] == "stay"
    assert (stay["start"], stay["end"]) == (_utc(DAY, "10:00"), _utc(DAY, "11:15"))
    assert "gap" not in _derive(capsys, "--day", DAY)


def test_fifteen_hours_at_home_with_eight_silences_is_one_stay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    silences = [
        ("08:10", "08:40"),
        ("09:00", "10:30"),
        ("11:00", "11:15"),
        ("12:00", "14:00"),
        ("14:30", "15:00"),
        ("16:00", "19:00"),
        ("19:30", "20:00"),
        ("21:00", "22:30"),
    ]
    drafts: list[dict[str, Any]] = []
    cursor = "08:00"
    for n, (quiet_from, quiet_until) in enumerate(silences):
        drafts += _dwell(DAY, cursor, quiet_from, HOME, seed=n + 1)
        cursor = quiet_until
    drafts += _dwell(DAY, cursor, "23:00", HOME, seed=9)
    _record(tmp_path, monkeypatch, drafts)
    [stay] = _owner(_derive_json(capsys, "--day", DAY))
    assert stay["kind"] == "stay"
    assert (stay["start"], stay["end"]) == (_utc(DAY, "08:00"), _utc(DAY, "23:00"))
    assert stay["points"] == len(drafts)
    text = _derive(capsys, "--day", DAY)
    assert "gap" not in text and text.count("stay") == 1


def test_merge_gap_governs_an_excursion_outside_the_radius(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Out of the radius and back within `merge_gap_s`: one stay. Back later: two stays and a move."""
    out = [_point(_utc(DAY, "10:33"), CAFE), _point(_utc(DAY, "10:34"), CAFE)]
    brief = _dwell(DAY, "10:00", "10:30", HOME) + out + _dwell(DAY, "10:36", "11:00", HOME, seed=2)
    _record(tmp_path, monkeypatch, brief)
    [stay] = _owner(_derive_json(capsys, "--day", DAY))
    assert (stay["start"], stay["end"]) == (_utc(DAY, "10:00"), _utc(DAY, "11:00"))

    long = _dwell(DAY, "10:00", "10:30", HOME) + out + _dwell(DAY, "10:45", "11:15", HOME, seed=2)
    _record(tmp_path / "second", monkeypatch, long)
    kinds = [s["kind"] for s in _owner(_derive_json(capsys, "--day", DAY))]
    assert kinds == ["stay", "move", "stay"]


# -- stops and promotion -------------------------------------------------------------------------------


def _morning_with_cafe(extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Home 08:00 to 09:00, a 12-minute walk to the cafe, ten minutes there, a walk back, home again."""
    return (
        _dwell(DAY, "08:00", "09:00", HOME)
        + _travel(DAY, "09:00", "09:12", HOME, CAFE)
        + _dwell(DAY, "09:12", "09:22", CAFE, noise_m=15)
        + _travel(DAY, "09:22", "09:34", CAFE, HOME)
        + _dwell(DAY, "09:34", "10:30", HOME, seed=3)
        + extra
    )


def test_a_short_stop_with_nothing_attached_is_a_flagged_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _record(tmp_path, monkeypatch, _morning_with_cafe([]))
    data = _derive_json(capsys, "--day", DAY)
    kinds = [s["kind"] for s in _owner(data)]
    assert kinds == ["stay", "move", "stop", "move", "stay"]
    stop = _owner(data)[2]
    assert stop["attached"] == {} and stop["promoted"] is False
    assert abs(stop["lat"] - CAFE[0]) < 0.001
    text = _derive(capsys, "--day", DAY)
    assert "stop" in text


def test_a_short_stop_with_a_photo_is_promoted_to_a_stay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _record(tmp_path, monkeypatch, _morning_with_cafe([_photo(_utc(DAY, "09:15"), CAFE)]))
    data = _derive_json(capsys, "--day", DAY)
    kinds = [s["kind"] for s in _owner(data)]
    assert kinds == ["stay", "move", "stay", "move", "stay"]
    cafe = _owner(data)[2]
    assert cafe["attached"] == {"photo": 1}
    assert cafe["promoted"] is True
    text = _derive(capsys, "--day", DAY)
    assert "1 photo" in text


def test_attached_counts_every_evidence_kind_and_never_a_retracted_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    drafts = [
        *_dwell(DAY, "08:00", "09:00", HOME),
        _photo(_utc(DAY, "08:10")),
        _photo(_utc(DAY, "08:12")),
        _event(_utc(DAY, "08:45"), _utc(DAY, "09:30")),  # overlaps the stay's end: counts
        _event(_utc(DAY, "07:00"), _utc(DAY, "07:30")),  # before: does not
        _message(_utc(DAY, "08:20")),
        _message(_utc(DAY, "08:21")),  # retracted below
        {
            "at": _utc(DAY, "08:30"),
            "source": "manual",
            "kind": "note",
            "tier": 2,
            "payload": {"schema": "note/v1", "text": "coffee"},
        },
    ]
    lb = _record(tmp_path, monkeypatch, drafts)
    seq_of_second_message = next(
        line["seq"] for line in lb.lines() if line["payload"].get("raw_id") == f"m-{_utc(DAY, '08:21')}"
    )
    lb.retract(seq_of_second_message, "wrong chat")
    data = _derive_json(capsys, "--day", DAY)
    [stay] = _owner(data)
    assert stay["attached"] == {"photo": 2, "event": 1, "message": 1, "note": 1}
    text = _derive(capsys, "--day", DAY)
    assert "2 photos" in text and "1 event" in text and "1 message" in text and "1 note" in text
    assert "coffee" not in text and "on my way" not in text, "counts only, never a line's text"


# -- moves ----------------------------------------------------------------------------------------------


def test_moves_have_distance_duration_and_a_mode_from_speed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    drafts = (
        _dwell(DAY, "08:00", "08:30", HOME)
        + _travel(DAY, "08:30", "08:44", HOME, CAFE)  # ~1.1 km in 14 min: a walk
        + _dwell(DAY, "08:44", "09:30", CAFE)
        + _travel(DAY, "09:30", "09:33", CAFE, OFFICE, steps=3)  # ~1.4 km in 3 min: a car
        + _dwell(DAY, "09:33", "10:30", OFFICE)
    )
    _record(tmp_path, monkeypatch, drafts)
    data = _derive_json(capsys, "--day", DAY)
    moves = [s for s in _owner(data) if s["kind"] == "move"]
    assert [m["mode"] for m in moves] == ["walk", "car"]
    assert 900 < moves[0]["distance_m"] < 1400
    assert moves[0]["duration_s"] == 14 * 60
    assert moves[0]["start"] == _utc(DAY, "08:30") and moves[0]["end"] == _utc(DAY, "08:44")
    text = _derive(capsys, "--day", DAY)
    assert "walk" in text and "car" in text and "km" in text


def test_a_fast_move_is_a_flight_and_so_is_a_gap_between_airports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Home, a train to the airport at ~140 km/h, an hour at OSL, no points for an hour, an hour at BGO.
    drafts = (
        _dwell(DAY, "07:00", "07:30", HOME)
        + _travel(DAY, "07:30", "07:50", HOME, OSL, steps=4)  # ~38 km in 20 min: ~115 km/h
        + _dwell(DAY, "07:50", "08:50", OSL)
        + _dwell(DAY, "09:50", "10:50", BGO)
        + _travel(DAY, "10:50", "10:55", BGO, TROMSO, steps=2)  # absurdly fast: > 150 km/h
        + _dwell(DAY, "10:55", "12:00", TROMSO)
    )
    _record(tmp_path, monkeypatch, drafts)
    data = _derive_json(capsys, "--day", DAY)
    moves = [s for s in _owner(data) if s["kind"] == "move"]
    assert [m["mode"] for m in moves] == ["car", "flight", "flight"]
    assert moves[1]["points"] == 0, "a gap: no points between the two airport stays"
    assert moves[1]["airports"] == ["OSL", "BGO"]


# -- nights ----------------------------------------------------------------------------------------------


def test_overnight_stay_is_the_longest_stay_between_22_and_08(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    next_day = "2026-06-11"
    drafts = (
        _dwell(DAY, "18:00", "22:40", OFFICE, every_min=5)
        + _travel(DAY, "22:40", "22:50", OFFICE, HOME, steps=2)
        + _dwell(DAY, "22:50", "23:59", HOME, every_min=5)
        + _dwell(next_day, "00:00", "09:00", HOME, every_min=5, seed=4)
    )
    _record(tmp_path, monkeypatch, drafts)
    data = _derive_json(capsys, "--day", DAY)
    [night] = data["nights"]
    assert night["day"] == DAY
    assert night["in_transit"] is False
    assert night["stay"]["start"] == _utc(DAY, "22:50")
    assert abs(night["stay"]["lat"] - HOME[0]) < 0.001
    text = _derive(capsys, "--day", DAY)
    assert "night" in text and "in transit" not in text


def _evening_home() -> list[dict[str, Any]]:
    """Two hours at the office, a walk home arriving 19:30, ten minutes of points there, then the
    tracker falls silent for the night."""
    return (
        _dwell(DAY, "17:00", "19:00", OFFICE)
        + _travel(DAY, "19:00", "19:30", OFFICE, HOME, steps=3)
        + _dwell(DAY, "19:30", "19:40", HOME)
    )


def test_an_evening_at_home_with_no_points_until_morning_is_the_night(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    next_day = "2026-06-11"
    _record(tmp_path, monkeypatch, _evening_home() + _dwell(next_day, "07:30", "08:30", HOME, seed=3))
    data = _derive_json(capsys, "--day", DAY)
    kinds = [s["kind"] for s in _owner(data)]
    assert kinds == ["stay", "move", "stay"], "office, the walk, home: no gap row, no stop"
    home = _owner(data)[-1]
    assert home["start"] == _utc(DAY, "19:30") and home["end"] >= _utc(next_day, "07:58")
    [night] = data["nights"]
    assert night["in_transit"] is False and night["stay"]["start"] == _utc(DAY, "19:30")
    text = _derive(capsys, "--day", DAY)
    assert "gap" not in text and "in transit" not in text


def test_the_last_stay_lasts_until_the_next_point_even_the_next_morning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The first point of the morning is already away from home and after the night window's end:
    the stay still lasts until it, so the night is at home, not in transit."""
    next_day = "2026-06-11"
    _record(tmp_path, monkeypatch, _evening_home() + _dwell(next_day, "09:00", "10:00", OFFICE, seed=3))
    data = _derive_json(capsys, "--day", DAY)
    home = _owner(data)[-1]
    assert home["kind"] == "stay"
    assert (home["start"], home["end"]) == (_utc(DAY, "19:30"), _utc(next_day, "09:00"))
    [night] = data["nights"]
    assert night["in_transit"] is False and night["stay"]["start"] == _utc(DAY, "19:30")
    text = _derive(capsys, "--day", DAY)
    assert f"19:30{EN_DASH}09:00+1" in text and "in transit" not in text and next_day not in text


def test_a_red_eye_night_is_in_transit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    next_day = "2026-06-11"
    drafts = (
        _dwell(DAY, "09:00", "20:00", HOME, every_min=10)
        + _travel(DAY, "20:00", "20:40", HOME, OSL, steps=4)
        + _dwell(DAY, "20:40", "21:50", OSL, every_min=5)  # ends before 22:00
        + _dwell(next_day, "08:30", "12:00", TROMSO, every_min=10)  # lands, first fix after 08:00
    )
    _record(tmp_path, monkeypatch, drafts)
    data = _derive_json(capsys, "--day", DAY)
    [night] = data["nights"]
    assert night["in_transit"] is True and night["stay"] is None
    text = _derive(capsys, "--day", DAY)
    assert "in transit" in text


def test_a_range_of_days_gives_one_night_per_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    drafts = (
        _dwell(DAY, "20:00", "23:59", HOME, every_min=5)
        + _dwell("2026-06-11", "00:00", "23:59", HOME, every_min=5, seed=5)
        + _dwell("2026-06-12", "00:00", "09:00", HOME, every_min=5, seed=6)
    )
    _record(tmp_path, monkeypatch, drafts)
    data = _derive_json(capsys, "--since", DAY, "--until", "2026-06-11")
    assert [n["day"] for n in data["nights"]] == [DAY, "2026-06-11"]
    assert all(n["in_transit"] is False for n in data["nights"])
    text = _derive(capsys, "--since", DAY, "--until", "2026-06-11")
    assert DAY in text and "2026-06-11" in text


# -- subjects and aboard ------------------------------------------------------------------------------


def _boat_day(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """The owner is at the marina from 09:00, the boat leaves at 10:00 with the owner's phone on
    board and anchors on the fjord at 12:00; the owner's points track the boat's. The boat's AIS
    reports come every minute, the phone's every five."""
    boat = "solvind"
    drafts = (
        _dwell(DAY, "08:00", "09:00", HOME, every_min=5)
        + _travel(DAY, "09:00", "09:10", HOME, MARINA, steps=2)
        + _dwell(DAY, "09:10", "10:00", MARINA, every_min=5, noise_m=20)
        + _travel(DAY, "10:00", "12:00", MARINA, FJORD, steps=24)
        + _dwell(DAY, "12:00", "14:00", FJORD, every_min=5, noise_m=20, seed=7)
        # the boat
        + _dwell(DAY, "06:00", "10:00", MARINA, every_min=1, noise_m=5, subject=boat, seed=8)
        + _travel(DAY, "10:00", "12:00", MARINA, FJORD, steps=120, subject=boat)
        + _dwell(DAY, "12:00", "14:00", FJORD, every_min=1, noise_m=5, subject=boat, seed=9)
    )
    lb = _record(tmp_path, monkeypatch, drafts)
    (lb.root / "assets.json").write_text(
        json.dumps({"assets": [{"id": boat, "kind": "yacht", "name": "Solvind", "mmsi": "999000001"}]}),
        encoding="utf-8",
    )
    return lb


def test_a_stay_matching_an_asset_is_aboard_and_the_asset_has_its_own_stays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _boat_day(tmp_path, monkeypatch)
    data = _derive_json(capsys, "--day", DAY)
    owner = _owner(data)
    assert [s["kind"] for s in owner] == ["stay", "move", "stay"], "the run aboard is one stay"
    home, _walk, aboard = owner
    assert home["aboard"] is None and "inside" not in home
    assert aboard["aboard"] == "solvind" and aboard["place"] is None
    assert (aboard["start"], aboard["end"]) == (_utc(DAY, "09:10"), _utc(DAY, "14:00"))
    marina, sail, fjord = aboard["inside"]
    assert marina["aboard"] == "solvind" and abs(marina["lat"] - MARINA[0]) < 0.001
    assert sail["aboard"] == "solvind" and sail["mode"] == "boat"
    assert fjord["aboard"] == "solvind" and abs(fjord["lat"] - FJORD[0]) < 0.001
    assert aboard["lat"] == fjord["lat"], "the stay's centre is the inner stay the owner spent longest at"
    boat = [s for s in data["segments"] if s["subject"] == "solvind"]
    assert [s["kind"] for s in boat] == ["stay", "move", "stay"]
    assert all(s["aboard"] is None for s in boat), "aboard is the owner's relation, never the asset's"
    assert boat[0]["start"] == _utc(DAY, "06:00")
    assert data["subjects"] == [None, "solvind"]
    text = _derive(capsys, "--day", DAY)
    assert "aboard solvind" in text
    assert "Solvind" in text, "the registry names the asset's own section"


def test_subject_filters_the_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _boat_day(tmp_path, monkeypatch)
    data = _derive_json(capsys, "--day", DAY, "--subject", "solvind")
    assert data["subjects"] == ["solvind"]
    assert {s["subject"] for s in data["segments"]} == {"solvind"}
    assert data["nights"] == [], "nights are the owner's"
    data = _derive_json(capsys, "--day", DAY, "--subject", "owner")
    assert data["subjects"] == [None]
    assert {s["subject"] for s in data["segments"]} == {None}


def test_an_unknown_subject_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _record(tmp_path, monkeypatch, _dwell(DAY, "08:00", "09:00", HOME))
    with pytest.raises(SystemExit) as e:
        cli.main(["derive", "stays", "--day", DAY, "--subject", "nobody"])
    assert e.value.code == 2
    assert "nobody" in capsys.readouterr().err


# -- the command --------------------------------------------------------------------------------------


def test_an_empty_day_says_so_and_a_bad_date_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _record(tmp_path, monkeypatch, [])
    text = _derive(capsys, "--day", DAY)
    assert "no location" in text
    data = _derive_json(capsys, "--day", DAY)
    assert data["segments"] == []
    assert data["nights"] == [
        {
            "day": DAY,
            "stay": None,
            "in_transit": True,
            "home": False,
            "aboard": None,
            "inside": None,
            "position": None,
        }
    ]
    with pytest.raises(SystemExit) as e:
        cli.main(["derive", "stays", "--day", "yesterday"])
    assert e.value.code == 2
    with pytest.raises(SystemExit) as e:
        cli.main(["derive", "stays", "--day", DAY, "--since", DAY])
    assert e.value.code == 2


def test_the_table_reads_in_local_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _record(tmp_path, monkeypatch, _morning_with_cafe([_photo(_utc(DAY, "09:15"))]))
    text = _derive(capsys, "--day", DAY)
    lines = text.splitlines()
    assert lines[0].startswith(DAY)
    assert any(line.lstrip().startswith(f"08:00{EN_DASH}09:00") and "stay" in line for line in lines)
    assert any(f"09:12{EN_DASH}09:22" in line and "1 photo" in line for line in lines)
    assert any("move" in line and "walk" in line for line in lines)
    assert f"{HOME[0]:.4f}" in text, "an unnamed place is its coordinates"


def test_derive_is_pure(monkeypatch: pytest.MonkeyPatch) -> None:
    """The derivation is a function of the lines: same lines, same segments, and it takes a
    settings object rather than a record, so an engine can call it without a folder."""
    settings = stays.Settings()
    lines = [
        dict(d, seq=i + 1, id=f"id-{i}", tz=TZ, end=d.get("end"))
        for i, d in enumerate(_morning_with_cafe([]))
    ]
    first = stays.derive(lines, settings, places=[], assets={}, tz=TZ)
    second = stays.derive(lines, settings, places=[], assets={}, tz=TZ)
    assert first.segments == second.segments
    assert [s.kind for s in first.segments] == ["stay", "move", "stop", "move", "stay"]
