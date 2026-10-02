"""`logbook rollup attention [--year Y | --since DAY --until DAY] [--by month|week]`: hours by app and
by category from the `app-use` lines standing, per year, month or ISO week; the categories from the
built-in table under `policy/apps.json`. Synthetic Oslo persona; nothing is appended."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from persona import TZ, utc

from logbook import cli
from logbook.store import Logbook

EM_DASH = "\u2014"
EN_DASH = "\u2013"
IPHONE = "7E7E7E7E-0000-4000-8000-00000000CAFE"


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(["rollup", "attention", *args])
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_run(capsys, *args, "--json"))
    return data


def _use(
    day: str, clock: str, minutes: int, bundle: str, device: str = "mac", app: str | None = None, **extra: Any
) -> dict[str, Any]:
    at = utc(day, clock)
    ended = datetime.fromisoformat(at.replace("Z", "+00:00")) + timedelta(minutes=minutes)
    end = ended.strftime("%Y-%m-%dT%H:%M:%SZ")
    found = {
        "bundle_id": bundle,
        "device": device,
        "duration_s": minutes * 60,
        "observed": "session",
        **extra,
    }
    if app:
        found["app"] = app
    payload: dict[str, Any] = {
        "schema": "event/v1",
        "raw_id": f"{device}:{bundle}:{at}",
        "title": app or bundle,
        "calendar": {"id": "screen-time", "name": "Screen Time"},
        "all_day": False,
        "extra": found,
    }
    return {
        "at": at,
        "end": end,
        "tz": TZ,
        "source": "screentime",
        "kind": "app-use",
        "tier": 2,
        "payload": payload,
    }


def _record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """June 2026 on the Mac and the phone: Safari, Messages, Xcode, Music and a puzzle nobody names;
    July has nothing; one Safari hour in August. One session is written twice and retracted once;
    one is superseded by a correction, so the correction stands."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    d1, d2 = "2026-06-08", "2026-06-09"
    drafts = [
        _use(d1, "09:00", 60, "com.apple.Safari", app="Safari"),
        _use(d1, "10:00", 30, "com.apple.MobileSMS", app="Messages"),
        _use(d1, "11:00", 120, "com.apple.dt.Xcode", app="Xcode"),
        _use(d1, "20:00", 45, "com.apple.Music", app="Music"),
        _use(d1, "21:00", 15, "org.example.puzzle"),
        _use(d2, "09:00", 30, "com.apple.mobilesafari", IPHONE, "Safari", observed="hourly_total"),
        _use(d2, "09:00", 10, "com.apple.MobileSMS", IPHONE, "Messages", observed="hourly_total"),
        _use(d2, "12:00", 90, "com.apple.dt.Xcode", app="Xcode"),  # wrong: it was 60 minutes
        _use(d2, "22:00", 240, "com.apple.Safari", app="Safari"),  # a session to retract
        _use("2026-08-20", "09:00", 60, "com.apple.Safari", app="Safari"),
    ]
    lb.append_many(drafts)
    with lb.index() as idx:
        wrong = next(line for line in idx.day(d2) if line["payload"]["extra"]["duration_s"] == 5400)
        bad = next(line for line in idx.day(d2) if line["payload"]["extra"]["duration_s"] == 240 * 60)
    fix = _use(d2, "12:00", 60, "com.apple.dt.Xcode", app="Xcode")
    fix["payload"]["raw_id"] += "@fixed"
    fix["payload"]["supersedes"] = str(wrong["id"])
    lb.append_many([fix])
    lb.retract(int(bad["seq"]), "the Mac was left on")
    return lb


def test_attention_per_year_sums_hours_by_app_and_by_category(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = _record(tmp_path, monkeypatch)
    head = lb.meta["head"]
    data = _json(capsys)
    assert data["kind"] == "attention" and data["by"] == "year"
    assert data["window"] == {"since": "2026-06-08", "until": "2026-08-20", "days": data["window"]["days"]}
    assert data["categories"] == ["communication", "browser", "media", "work", "other"]
    [year] = data["periods"]
    assert year["period"] == "2026" and year["first"] == "2026-06-08" and year["last"] == "2026-08-20"
    # Safari 60 + 30 + 60 = 150 min; Messages 40; Xcode 120 + 60 (the correction, not the 90) = 180;
    # Music 45; the puzzle 15: 430 min = 7.2 h. The retracted four hours are out.
    assert year["seconds"] == 430 * 60 and year["hours"] == 7.2
    assert year["by_category"] == {
        "communication": {"hours": 0.7, "seconds": 40 * 60},
        "browser": {"hours": 2.5, "seconds": 150 * 60},
        "media": {"hours": 0.8, "seconds": 45 * 60},
        "work": {"hours": 3.0, "seconds": 180 * 60},
        "other": {"hours": 0.2, "seconds": 15 * 60},
    }
    apps = {a["bundle_id"]: a for a in year["apps"]}
    assert [a["app"] for a in year["apps"]] == ["Xcode", "Safari", "Music", "Messages", "Safari", None]
    assert apps["com.apple.MobileSMS"]["devices"] == {"mac": 30 * 60, IPHONE: 10 * 60}, "one app, two devices"
    xcode = apps["com.apple.dt.Xcode"]
    assert xcode == {
        "bundle_id": "com.apple.dt.Xcode",
        "app": "Xcode",
        "category": "work",
        "hours": 3.0,
        "seconds": 180 * 60,
        "sessions": 2,
        "devices": {"mac": 180 * 60},
        "lines": xcode["lines"],
    }
    assert len(xcode["lines"]) == 2 and all(len(id_) == 36 for id_ in xcode["lines"])
    safari = [a for a in year["apps"] if a["app"] == "Safari"]
    assert [(a["bundle_id"], a["seconds"], a["devices"]) for a in safari] == [
        ("com.apple.Safari", 120 * 60, {"mac": 120 * 60}),
        ("com.apple.mobilesafari", 30 * 60, {IPHONE: 30 * 60}),
    ], "an app is its bundle id, so the Mac's Safari and the phone's are two rows"
    puzzle = apps["org.example.puzzle"]
    assert puzzle["app"] is None and puzzle["category"] == "other"
    assert lb.meta["head"] == head, "a reader never writes"
    text = _run(capsys)
    assert text.startswith(f"attention 2026-06-08 {EN_DASH} 2026-08-20 · by year")
    assert (
        "  2026  7.2 h · communication 0.7 h · browser 2.5 h · media 0.8 h · work 3.0 h · other 0.2 h" in text
    )
    assert "Xcode" in text and "3.0 h · work · 2 sessions · com.apple.dt.Xcode" in text
    assert "org.example.puzzle" in text and "0.2 h · other · 1 session" in text
    assert "mac" not in text.split("\n")[1], "the devices are under --json"


def test_attention_per_month_lists_a_month_with_nothing_and_per_week(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _record(tmp_path, monkeypatch)
    data = _json(capsys, "--since", "2026-05-01", "--until", "2026-09-30", "--by", "month")
    assert data["by"] == "month" and data["window"]["since"] == "2026-06-08"
    assert [p["period"] for p in data["periods"]] == ["2026-06", "2026-07", "2026-08"]
    june, july, august = data["periods"]
    assert june["first"] == "2026-06-08" and june["last"] == "2026-06-30"
    assert june["seconds"] == 370 * 60 and august["seconds"] == 60 * 60
    assert july == {
        "period": "2026-07",
        "first": "2026-07-01",
        "last": "2026-07-31",
        "hours": 0.0,
        "seconds": 0,
        "by_category": None,
        "apps": [],
    }, "a period with no line has no categories and no apps, never a zero per category"
    text = _run(capsys, "--year", "2026", "--by", "month")
    assert f"attention 2026-06-08 {EN_DASH} 2026-08-20 · by month" in text
    assert "  2026-06  6.2 h · communication 0.7 h · browser 1.5 h" in text
    assert f"  2026-07  {EM_DASH}" in text
    assert "  2026-08  1.0 h · communication 0.0 h · browser 1.0 h" in text
    weeks = _json(capsys, "--by", "week")
    assert weeks["periods"][0]["period"] == "2026-W24" and weeks["periods"][0]["seconds"] == 370 * 60
    assert weeks["periods"][-1]["period"] == "2026-W34" and weeks["periods"][-1]["seconds"] == 3600
    assert len(weeks["periods"]) == 11


def test_attention_reads_the_owners_apps_json_over_the_built_in_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = _record(tmp_path, monkeypatch)
    path = lb.root / "policy" / "apps.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"org.example.puzzle": {"name": "Puzzle", "category": "media"}, "com.apple.dt.Xcode": "other"}
        ),
        encoding="utf-8",
    )
    [year] = _json(capsys)["periods"]
    apps = {a["bundle_id"]: a for a in year["apps"]}
    assert apps["org.example.puzzle"]["app"] == "Puzzle" and apps["org.example.puzzle"]["category"] == "media"
    assert apps["com.apple.dt.Xcode"]["category"] == "other" and apps["com.apple.dt.Xcode"]["app"] == "Xcode"
    assert year["by_category"]["media"]["seconds"] == 60 * 60 and year["by_category"]["work"] is not None
    assert year["by_category"]["work"]["seconds"] == 0 and year["by_category"]["other"]["seconds"] == 180 * 60
    assert "Puzzle" in _run(capsys)
    path.write_text(json.dumps({"org.example.puzzle": "gaming"}), encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        cli.main(["rollup", "attention"])
    assert e.value.code == 2 and "apps.json" in capsys.readouterr().err


def test_the_window_is_the_app_use_lines_span_and_by_is_refused_elsewhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from persona import HOME, dwell

    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(dwell("2026-03-01", "09:00", "20:00", HOME))  # a location day months before
    lb.append_many([_use("2026-06-02", "08:00", 20, "com.apple.Safari", app="Safari")])
    data = _json(capsys)
    assert data["window"] == {"since": "2026-06-02", "until": "2026-06-02", "days": ["2026-06-02"]}
    [year] = data["periods"]
    assert year["hours"] == 0.3 and year["by_category"]["browser"]["seconds"] == 1200
    assert _json(capsys, "--year", "2025")["periods"] == []
    assert "nothing" in _run(capsys, "--year", "2025")
    with pytest.raises(SystemExit) as e:
        cli.main(["rollup", "nights", "--by", "month"])
    assert e.value.code == 2
    with pytest.raises(SystemExit):
        cli.main(["rollup", "attention", "--by", "day"])


def test_an_empty_record_has_no_periods(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    data = _json(capsys)
    assert data == {
        "kind": "attention",
        "window": {"since": None, "until": None, "days": []},
        "by": "year",
        "categories": ["communication", "browser", "media", "work", "other"],
        "periods": [],
    }
    assert "nothing" in _run(capsys)
