"""`logbook rollup health [--year Y | --since DAY --until DAY] [--by month|week]`: sleep, steps,
resting heart rate and HRV per month or ISO week from the `health-sample/v1` lines standing (RFC
0014), a period without a number printing an em dash and never a zero. Synthetic Oslo persona;
nothing is appended."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from persona import TZ, utc

from logbook import cli
from logbook.core.store import Logbook

EM_DASH = "\u2014"
EN_DASH = "\u2013"


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(["rollup", "health", *args])
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_run(capsys, *args, "--json"))
    return data


def _health(
    at: str,
    type_: str,
    value: float,
    device: str = "Watch7,1",
    end: str | None = None,
    unit: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "health-sample/v1",
        "raw_id": f"{type_}:{at}:{device}:{value}",
        "type": type_,
        "value": value,
        "unit": unit or {"steps": "count", "sleep": "s", "resting_hr": "bpm", "hrv": "ms"}[type_],
        "device": device,
        **extra,
    }
    return {"at": at, "end": end, "source": "apple-health", "kind": "health", "tier": 3, "payload": payload}


def _record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """June 2026: two nights, two days of steps, resting readings and HRV; then nothing until one
    day of steps in August, so July is a month in the window with no line at all. The night of
    2 June is written twice by the watch (a sync, RFC 0014 rule 4) and once, shorter, by the phone
    (rule 5); its resting reading is written sixty times too large, corrected once, then corrected
    again, so the latest correction stands; a reading in count/s reads in bpm; a retracted reading
    is out."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    d1, d2, d3 = "2026-06-01", "2026-06-02", "2026-06-03"
    watch, phone = "Watch7,1", "iPhone17,1"
    drafts: list[dict[str, Any]] = [
        # the night that ends on 2 June: 23:00 to 06:00 local, 7 h asleep, in bed 8 h
        _health(utc(d1, "23:00"), "sleep", 3 * 3600, watch, end=utc(d2, "02:00"), stage="core"),
        _health(utc(d2, "02:00"), "sleep", 4 * 3600, watch, end=utc(d2, "06:00"), stage="deep"),
        _health(utc(d1, "22:30"), "sleep", 8 * 3600, watch, end=utc(d2, "06:30"), stage="in_bed"),
        # the same night again from the same watch (a re-sync): the union, not the sum
        _health(
            utc(d1, "23:00"), "sleep", 3 * 3600, watch, end=utc(d2, "02:00"), stage="core", raw_id="again"
        ),
        # the phone saw five hours of it: the longest device wins, devices are never summed
        _health(utc(d2, "01:00"), "sleep", 5 * 3600, phone, end=utc(d2, "06:00"), stage="asleep"),
        # the night that ends on 3 June: 6 h
        _health(utc(d3, "00:00"), "sleep", 6 * 3600, watch, end=utc(d3, "06:00"), stage="asleep"),
        # steps: the larger device per quarter hour, summed over the day
        _health(utc(d2, "08:00"), "steps", 250, watch, end=utc(d2, "08:15")),
        _health(utc(d2, "08:00"), "steps", 200, phone, end=utc(d2, "08:15")),
        _health(utc(d2, "17:00"), "steps", 3000, watch, end=utc(d2, "17:15")),
        _health(utc(d3, "09:00"), "steps", 1000, watch, end=utc(d3, "09:15")),
        # resting heart rate: a wrong line (count/min written sixty times too large)
        _health(utc(d2, "07:00"), "resting_hr", 3360, watch),
        # a reading the store keeps in count/s reads in bpm
        _health(utc(d3, "07:00"), "resting_hr", 1.0, watch, unit="count/s"),
        # a reading to retract
        _health(utc(d3, "08:00"), "resting_hr", 200, watch),
        # HRV on one day only
        _health(utc(d2, "07:00"), "hrv", 40, watch),
        _health(utc(d2, "07:30"), "hrv", 50, watch),
        # August: one day of steps, nothing else
        _health(utc("2026-08-20", "10:00"), "steps", 5000, watch, end=utc("2026-08-20", "10:15")),
    ]
    lb.append_many(drafts)
    with lb.index() as idx:
        wrong = next(line for line in idx.day(d2) if line["payload"].get("type") == "resting_hr")
        bad = next(line for line in idx.day(d3) if line["payload"].get("value") == 200)
    first_fix = _health(utc(d2, "07:00"), "resting_hr", 56, watch, supersedes=str(wrong["id"]))
    lb.append_many([first_fix])
    second_fix = _health(utc(d2, "07:00"), "resting_hr", 54, watch, supersedes=str(wrong["id"]))
    lb.append_many([second_fix])
    lb.retract(int(bad["seq"]), "a strap artefact")
    return lb


def test_health_per_month_takes_the_latest_correction_and_prints_a_dash_for_a_missing_period(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = _record(tmp_path, monkeypatch)
    head = lb.meta["head"]
    data = _json(capsys, "--since", "2026-05-01", "--until", "2026-09-30")
    assert data["kind"] == "health" and data["by"] == "month"
    assert data["window"]["since"] == "2026-06-01" and data["window"]["until"] == "2026-08-20"
    assert [p["period"] for p in data["periods"]] == ["2026-06", "2026-07", "2026-08"]
    june, july, august = data["periods"]
    assert june["first"] == "2026-06-01" and june["last"] == "2026-06-30"
    assert august["first"] == "2026-08-01" and august["last"] == "2026-08-20"
    assert june["sleep"] == {"mean_h": 6.5, "nights": 2, "lines": june["sleep"]["lines"]}
    assert len(june["sleep"]["lines"]) == 4, "the watch's three asleep stages, the second night's one"
    assert june["steps"] == {"mean": 2125, "days": 2, "lines": june["steps"]["lines"]}
    assert len(june["steps"]["lines"]) == 3, "the larger device per quarter hour"
    assert june["resting_hr"] == {
        "mean": 57,
        "min": 54,
        "max": 60,
        "days": 2,
        "lines": june["resting_hr"]["lines"],
    }, "the latest correction (54) and the count/s reading (60); the retracted one is out"
    assert len(june["resting_hr"]["lines"]) == 2
    assert june["hrv"] == {"mean_ms": 45, "days": 1, "lines": june["hrv"]["lines"]}
    assert len(june["hrv"]["lines"]) == 2
    for key in ("sleep", "steps", "resting_hr", "hrv"):
        assert all(len(id_) == 36 for id_ in june[key]["lines"])
    assert july == {"period": "2026-07", "first": "2026-07-01", "last": "2026-07-31"} | dict.fromkeys(
        ("sleep", "steps", "resting_hr", "hrv")
    ), "a period with no line is listed with nothing, never a zero"
    assert august["steps"] == {"mean": 5000, "days": 1, "lines": august["steps"]["lines"]}
    assert august["sleep"] is None and august["resting_hr"] is None and august["hrv"] is None
    assert lb.meta["head"] == head, "a reader never writes"
    text = _run(capsys, "--year", "2026")
    assert text.startswith(f"health 2026-06-01 {EN_DASH} 2026-08-20 · by month")
    assert "2026-06  sleep 6.5 h (2 nights) · 2,125 steps (2 days)" in text
    assert f"resting 57 bpm (54{EN_DASH}60, 2 days)" in text
    assert "hrv 45 ms (1 day)" in text
    assert f"2026-07  sleep {EM_DASH} · steps {EM_DASH} · resting {EM_DASH} · hrv {EM_DASH}" in text
    assert f"2026-08  sleep {EM_DASH} · 5,000 steps (1 day) · resting {EM_DASH} · hrv {EM_DASH}" in text


def test_health_per_iso_week(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _record(tmp_path, monkeypatch)
    data = _json(capsys, "--by", "week")
    assert data["by"] == "week"
    periods = [p["period"] for p in data["periods"]]
    assert periods[0] == "2026-W23" and periods[-1] == "2026-W34" and len(periods) == 12
    first = data["periods"][0]
    assert first["first"] == "2026-06-01" and first["last"] == "2026-06-07", "clipped to the window"
    assert first["sleep"]["mean_h"] == 6.5 and first["resting_hr"]["mean"] == 57
    assert data["periods"][5]["period"] == "2026-W28"
    assert data["periods"][5]["steps"] is None and data["periods"][5]["sleep"] is None
    assert data["periods"][-1]["steps"]["mean"] == 5000
    text = _run(capsys, "--by", "week")
    assert "by week" in text and f"2026-W28  sleep {EM_DASH}" in text


def test_the_window_is_the_health_lines_span_and_by_is_for_health_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from persona import HOME, dwell

    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(dwell("2026-03-01", "09:00", "20:00", HOME))  # a location day months before
    lb.append_many([_health(utc("2026-06-02", "08:00"), "steps", 400, end=utc("2026-06-02", "08:15"))])
    data = _json(capsys)
    assert data["window"] == {"since": "2026-06-02", "until": "2026-06-02", "days": ["2026-06-02"]}
    [june] = data["periods"]
    assert june["steps"]["mean"] == 400 and june["sleep"] is None
    assert _json(capsys, "--year", "2025")["periods"] == [], "a year the health lines never reach"
    assert "nothing" in _run(capsys, "--year", "2025")
    with pytest.raises(SystemExit) as e:
        cli.main(["rollup", "nights", "--by", "week"])
    assert e.value.code == 2
    with pytest.raises(SystemExit):
        cli.main(["rollup", "health", "--by", "day"])


def test_an_empty_record_has_no_periods(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    data = _json(capsys)
    assert data == {
        "kind": "health",
        "window": {"since": None, "until": None, "days": []},
        "by": "month",
        "periods": [],
    }
    assert "nothing" in _run(capsys)


def test_hrv_is_reported_in_ms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A single SDNN sample of 45 ms is `hrv 45 ms (1 day)`, in the JSON `mean_ms` 45. A line
    stored in seconds (`unit` `s`, as a store might keep it) reads in ms too, as a resting rate
    in count/s reads in bpm; a line in `ms` is taken as it is, never rescaled."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(
        [
            _health(utc("2026-06-02", "07:00"), "hrv", 45, "Watch7,1"),
            _health(utc("2026-06-09", "07:00"), "hrv", 0.045, "Watch7,1", unit="s"),
        ]
    )
    data = _json(capsys, "--since", "2026-06-01", "--until", "2026-06-14", "--by", "week")
    first, second = data["periods"]
    assert first["hrv"] == {"mean_ms": 45, "days": 1, "lines": first["hrv"]["lines"]}
    assert second["hrv"] == {"mean_ms": 45, "days": 1, "lines": second["hrv"]["lines"]}
    text = _run(capsys, "--since", "2026-06-01", "--until", "2026-06-14", "--by", "week")
    assert text.count("hrv 45 ms (1 day)") == 2
    cli.main(["stats", "--health", "--json"])
    rows = json.loads(capsys.readouterr().out)["days"]
    assert [row["hrv"] for row in rows] == [45, 45]


def test_the_adapter_and_the_repair_keep_hrv_in_ms() -> None:
    """The Apple Health adapter writes HRV (type 183) as the store keeps it, in ms, and never
    rescales it; `repair health-units` stamps the corrected line `ms`."""
    from logbook.contrib.adapters import apple_health
    from logbook.core import repair

    assert apple_health.TYPES[183] == "hrv" and apple_health.UNITS["hrv"] == "ms"
    assert "hrv" not in apple_health.SCALE
    assert repair.HEALTH_UNITS == {"resting_hr": "bpm", "hrv": "ms"}
