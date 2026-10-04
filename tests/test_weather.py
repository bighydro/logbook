"""`logbook sync weather` and the `weather/v1` lines (RFC 0026): the owner's overnight stay and every
stay of three hours or more, rounded to a tenth of a degree, one line per local day and place cluster
from Open-Meteo's free archive, cached under `inbox/weather/` so a re-run never refetches. No network
anywhere here: `urlopen` is replaced by a fake Open-Meteo that answers from arithmetic. Synthetic Oslo
persona, who does not exist."""

from __future__ import annotations

import json
import re
import urllib.error
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator
from persona import FJORD, HOME, ZURICH, persona_record

from logbook import cli
from logbook.commands import sync as sync_commands
from logbook.contrib import adapters
from logbook.contrib.adapters import weather as weather_adapter
from logbook.core import weather

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
ONE_DECIMAL = re.compile(r"-?\d{1,3}(\.\d)?")
EN_DASH = "\u2013"
TODAY = "2026-10-01"  # the tests' today: the persona's fortnight is long in the archive


def _daily(start: str, end: str) -> dict[str, list[Any]]:
    """Synthetic daily values for every day of [start, end]: a function of the day, so a test can
    predict what a line says."""
    days = [d.isoformat() for d in _days(start, end)]
    out: dict[str, list[Any]] = {"time": days}
    for i, day in enumerate(days):
        out.setdefault("temperature_2m_min", []).append(round(5.0 + i, 1))
        out.setdefault("temperature_2m_max", []).append(round(15.5 + i, 1))
        out.setdefault("precipitation_sum", []).append(round(i * 0.5, 1))
        out.setdefault("wind_speed_10m_max", []).append(round(20.0 + i, 1))
        out.setdefault("weather_code", []).append(3 if i % 2 == 0 else 63)
        out.setdefault("sunrise", []).append(f"{day}T04:00")
        out.setdefault("sunset", []).append(f"{day}T22:30")
    return out


def _days(start: str, end: str) -> list[date]:
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    return [date.fromordinal(o) for o in range(a.toordinal(), b.toordinal() + 1)]


class FakeOpenMeteo:
    """Answers GET /v1/archive and /v1/forecast with synthetic daily values for the range asked,
    and records every request's URL. `fail` names the latitudes whose requests come back 500."""

    def __init__(self, fail: frozenset[str] = frozenset()):
        self.requests: list[str] = []
        self.fail = fail

    def __call__(self, req: Any, timeout: float) -> Any:
        url = req.full_url if hasattr(req, "full_url") else str(req)
        self.requests.append(url)
        query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        if query["latitude"] in self.fail:
            raise urllib.error.HTTPError(url, 500, "Internal Server Error", {}, BytesIO(b""))  # type: ignore[arg-type]
        body = {
            "latitude": float(query["latitude"]),
            "longitude": float(query["longitude"]),
            "timezone": query["timezone"],
            "daily": _daily(query["start_date"], query["end_date"]),
        }
        return _Response(json.dumps(body).encode("utf-8"))

    def queries(self) -> list[dict[str, str]]:
        return [{k: v[0] for k, v in parse_qs(urlsplit(u).query).items()} for u in self.requests]


class _Response:
    def __init__(self, body: bytes):
        self.body = body

    def read(self) -> bytes:
        return self.body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeOpenMeteo:
    served = FakeOpenMeteo()
    monkeypatch.setattr(weather_adapter, "urlopen", served)
    monkeypatch.setattr(weather_adapter, "sleep", lambda _s: None)
    monkeypatch.setattr(sync_commands, "_today", lambda: TODAY)
    return served


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    try:
        cli.main(list(args))
    except SystemExit as e:
        status = int(e.code or 0)
    else:
        status = 0
    out = capsys.readouterr()
    return status, out.out, out.err


# -- the clusters: where the owner was, to a tenth of a degree ----------------------------------------------


def test_clusters_take_the_night_and_every_stay_of_three_hours_rounded_and_deduped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    found = weather.clusters(lb, "2026-06-09", "2026-06-16")
    by_day: dict[str, list[tuple[float, float]]] = {}
    for c in found:
        by_day.setdefault(c.day, []).append((c.lat, c.lon))
    home = (weather.round_coordinate(HOME[0]), weather.round_coordinate(HOME[1]))
    assert home == (59.9, 10.8)
    assert by_day["2026-06-09"] == [home], "home, the office 600 m away: one cluster, not two"
    fjord = (weather.round_coordinate(FJORD[0]), weather.round_coordinate(FJORD[1]))
    # the night at anchor and the morning at home, where the stay from the night before ran past 07:30
    assert fjord != home
    assert sorted(by_day["2026-06-13"]) == sorted([home, fjord])
    zurich = (weather.round_coordinate(ZURICH[0]), weather.round_coordinate(ZURICH[1]))
    assert zurich == (47.4, 8.5) and by_day["2026-06-16"] == [zurich]
    # the travel day: the morning's end of the home night and the hotel; the airports are under 3 h
    assert sorted(by_day["2026-06-15"]) == sorted([home, zurich])
    assert found == sorted(found), "in day order, then by coordinates"
    assert len(found) == len(set(found)), "deduped on (day, lat, lon)"
    for c in found:
        assert c.lat == round(c.lat, 1) and c.lon == round(c.lon, 1)


@given(st.floats(min_value=-90, max_value=90), st.floats(min_value=-180, max_value=180))
@settings(max_examples=200)
def test_the_request_url_never_carries_more_than_one_decimal_of_latitude_or_longitude(
    lat: float, lon: float
) -> None:
    rounded_lat, rounded_lon = weather.round_coordinate(lat), weather.round_coordinate(lon)
    request = weather_adapter.Request(
        rounded_lat, rounded_lon, "2026-06-01", "2026-06-03", weather_adapter.ARCHIVE
    )
    url = weather_adapter.url(request, "Europe/Oslo")
    query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert ONE_DECIMAL.fullmatch(query["latitude"]), query["latitude"]
    assert ONE_DECIMAL.fullmatch(query["longitude"]), query["longitude"]
    assert float(query["latitude"]) == rounded_lat and float(query["longitude"]) == rounded_lon
    assert (
        abs(float(query["latitude"]) - lat) <= 0.05 + 1e-9
        and abs(float(query["longitude"]) - lon) <= 0.05 + 1e-9
    )
    assert "-0.0" not in (query["latitude"], query["longitude"])
    assert url.startswith("https://archive-api.open-meteo.com/v1/archive?")
    assert "timezone=Europe%2FOslo" in url and "daily=" in url


def test_plan_batches_date_ranges_per_cluster_and_sends_recent_days_to_the_forecast_api() -> None:
    a, b = (59.9, 10.8), (47.4, 8.5)
    needed = [
        *(
            weather.Cluster(f"2026-09-{d:02d}", *a) for d in (1, 2, 3, 5, 20)
        ),  # a hole of one day is one range
        weather.Cluster("2026-09-29", *a),  # within the last 7 days: the forecast api
        weather.Cluster("2026-09-03", *b),
        weather.Cluster("2026-07-01", *a),  # far from the September run: its own range
    ]
    plan = weather_adapter.plan(needed, date.fromisoformat(TODAY))
    assert [(r.lat, r.lon, r.start, r.end, r.api) for r in plan] == [
        (47.4, 8.5, "2026-09-03", "2026-09-03", weather_adapter.ARCHIVE),
        (59.9, 10.8, "2026-07-01", "2026-07-01", weather_adapter.ARCHIVE),
        (59.9, 10.8, "2026-09-01", "2026-09-05", weather_adapter.ARCHIVE),
        (59.9, 10.8, "2026-09-20", "2026-09-20", weather_adapter.ARCHIVE),
        (59.9, 10.8, "2026-09-29", "2026-09-29", weather_adapter.FORECAST),
    ]
    assert weather_adapter.url(plan[-1], "Europe/Oslo").startswith("https://api.open-meteo.com/v1/forecast?")


def test_configure_lists_weather_in_sync_all_only_when_the_owner_says_so() -> None:
    assert weather_adapter.configure({}) is None
    assert weather_adapter.configure({"LOGBOOK_WEATHER": ""}) is None
    assert weather_adapter.configure({"LOGBOOK_WEATHER": "1"}) is not None
    assert weather_adapter.configure({"LOGBOOK_WEATHER": "on"}) is not None
    with pytest.raises(ValueError, match="LOGBOOK_WEATHER"):
        weather_adapter.configure({"LOGBOOK_WEATHER": "maybe"})
    assert weather_adapter.ENV == ("LOGBOOK_WEATHER",)
    assert adapters.live("weather") is weather_adapter and adapters.named("weather") is None


# -- the sync ---------------------------------------------------------------------------------------------


def test_sync_weather_writes_one_line_per_cluster_day_caches_it_and_never_refetches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], fake: FakeOpenMeteo
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    clusters = weather.clusters(lb, "2026-06-08", "2026-06-21")
    status, out, err = _run(capsys, "sync", "weather", "--since", "2026-06-08", "--until", "2026-06-21")
    assert status == 0, err
    lines = [line for line in lb.lines() if line["kind"] == "weather"]
    assert len(lines) == len(clusters) > 14
    assert {(p["day"], p["lat"], p["lon"]) for p in (line["payload"] for line in lines)} == set(clusters)
    assert f"weather: {len(lines)} new lines of {len(lines)} seen" in out
    assert f"{len(fake.requests)} request" in out
    for query in fake.queries():
        assert ONE_DECIMAL.fullmatch(query["latitude"]) and ONE_DECIMAL.fullmatch(query["longitude"])
        assert query["timezone"] == "Europe/Oslo"
        assert query["daily"] == ",".join(weather_adapter.DAILY)
    assert len(fake.requests) < len(lines), "batched by date range per cluster, not one request a day"
    [home_run] = [q for q in fake.queries() if q["latitude"] == "59.9" and q["longitude"] == "10.8"]
    assert (home_run["start_date"], home_run["end_date"]) == ("2026-06-08", "2026-06-21")
    cache = lb.root / "inbox" / "weather"
    cached = sorted(p.relative_to(cache).as_posix() for p in cache.rglob("*.json"))
    assert len(cached) >= len(lines), "every fetched cluster-day is cached, even the days no stay needed"
    assert "59.9_10.8/2026-06-09.json" in cached and "47.4_8.5/2026-06-16.json" in cached
    for p in cache.rglob("*.json"):
        text = p.read_text(encoding="utf-8")
        assert "59.91" not in text and "10.75" not in text, "only rounded coordinates reach the cache"
    state = json.loads((lb.root / "state" / "weather.json").read_text(encoding="utf-8"))
    assert state["since"] == "2026-06-21"

    line = next(line for line in lines if line["payload"]["day"] == "2026-06-16")
    p = line["payload"]
    assert p["schema"] == "weather/v1" and p["raw_id"] == "2026-06-16@47.4,8.5"
    assert p["evidence"] == "external" and p["provider"] == "open-meteo" and p["dataset"] == "archive"
    assert (line["tier"], line["source"], line["tz"]) == (1, "weather", "Europe/Oslo")
    assert line["at"] == "2026-06-15T22:00:00Z" and line["end"] == "2026-06-16T22:00:00Z", "the local day"
    assert p["sunrise"] == "2026-06-16T02:00:00Z" and p["sunset"] == "2026-06-16T20:30:00Z"
    assert isinstance(p["t_min_c"], float) and p["t_max_c"] - p["t_min_c"] == 10.5
    assert isinstance(p["weather_code"], int) and p["precipitation_mm"] >= 0 and p["wind_max_kmh"] >= 20
    Draft202012Validator(SCHEMA).validate(line)

    fetched = len(fake.requests)
    head = lb.meta["head"]
    status, out, _err = _run(capsys, "sync", "weather", "--since", "2026-06-08", "--until", "2026-06-21")
    assert status == 0 and len(fake.requests) == fetched, "a re-run reads the cache, never the network"
    assert (
        f"weather: 0 new lines of {len(lines)} seen" in out and f"({len(lines)} already in the record)" in out
    )
    assert lb.meta["head"] == head


def test_sync_weather_defaults_to_the_days_since_the_watermark_and_yesterday(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], fake: FakeOpenMeteo
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    status, out, _err = _run(capsys, "sync", "weather")
    assert status == 0
    assert f"2026-06-08 {EN_DASH} 2026-09-30" in out, "the record's first located day to yesterday"
    assert all(q["end_date"] <= "2026-09-30" for q in fake.queries()), "today is never asked for"
    state = json.loads((lb.root / "state" / "weather.json").read_text(encoding="utf-8"))
    assert state["since"] == "2026-09-30"
    fetched = len(fake.requests)
    status, out, _err = _run(capsys, "sync", "weather")
    assert status == 0 and len(fake.requests) == fetched
    assert f"2026-09-23 {EN_DASH} 2026-09-30" in out, "a lookback of a week before the watermark"


def test_sync_weather_dry_run_fetches_nothing_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], fake: FakeOpenMeteo
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    head = lb.meta["head"]
    status, out, _err = _run(
        capsys, "sync", "weather", "--since", "2026-06-08", "--until", "2026-06-21", "--dry-run"
    )
    assert status == 0 and fake.requests == []
    clusters = weather.clusters(lb, "2026-06-08", "2026-06-21")
    assert f"weather: {len(clusters)} cluster-days over 14 days" in out and "dry run, nothing written" in out
    assert "to fetch in" in out and "request" in out
    assert lb.meta["head"] == head
    assert not (lb.root / "inbox" / "weather").exists() and not (lb.root / "state").exists()


def test_sync_all_leaves_weather_out_unless_the_owner_lists_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], fake: FakeOpenMeteo
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    monkeypatch.setattr(adapters, "live_adapters", lambda: [weather_adapter])
    monkeypatch.delenv("LOGBOOK_WEATHER", raising=False)
    status, out, _err = _run(capsys, "sync", "--all")
    assert status == 0 and fake.requests == []
    assert "weather: LOGBOOK_WEATHER not set; skipped" in out
    assert [line for line in lb.lines() if line["kind"] == "weather"] == []
    monkeypatch.setenv("LOGBOOK_WEATHER", "1")
    status, out, _err = _run(capsys, "sync", "--all")
    assert status == 0 and fake.requests
    assert "weather  ok" in out or "weather ok" in out.replace("  ", " ")
    assert [line for line in lb.lines() if line["kind"] == "weather"]


def test_a_disabled_weather_source_is_skipped_without_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], fake: FakeOpenMeteo
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    (lb.root / "policy").mkdir(exist_ok=True)
    (lb.root / "policy" / "import.json").write_text(
        json.dumps({"disabled": [{"source": "weather", "reason": "no third parties"}]}), encoding="utf-8"
    )
    status, out, _err = _run(capsys, "sync", "weather", "--since", "2026-06-08", "--until", "2026-06-09")
    assert status == 0 and fake.requests == []
    assert "weather: disabled (no third parties); skipped" in out


def test_a_failed_request_is_said_the_rest_is_written_and_the_run_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], fake: FakeOpenMeteo
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    fake.fail = frozenset({"47.4"})
    status, _out, err = _run(capsys, "sync", "weather", "--since", "2026-06-08", "--until", "2026-06-21")
    assert status == 1
    assert f"sync: weather: 47.4,8.5 2026-06-15 {EN_DASH} 2026-06-18: HTTP Error 500" in err
    written = [line["payload"] for line in lb.lines() if line["kind"] == "weather"]
    assert written and all(p["lat"] != 47.4 for p in written), "the other clusters are in the record"
    assert not (lb.root / "inbox" / "weather" / "47.4_8.5").exists(), "nothing is cached for a failed request"
    assert not (lb.root / "state" / "weather.json").exists(), "the watermark waits for a clean run"
    fake.fail = frozenset()
    status, _out, _err = _run(capsys, "sync", "weather", "--since", "2026-06-08", "--until", "2026-06-21")
    assert status == 0
    assert any(
        p["lat"] == 47.4 for p in (line["payload"] for line in lb.lines() if line["kind"] == "weather")
    )


def test_sync_weather_refuses_a_bad_day_and_a_listen_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], fake: FakeOpenMeteo
) -> None:
    persona_record(tmp_path, monkeypatch)
    status, _out, err = _run(capsys, "sync", "weather", "--since", "2026-06-01T00:00:00Z")
    assert status == 2 and "YYYY-MM-DD" in err
    status, _out, err = _run(capsys, "sync", "weather", "--since", "2026-06-10", "--until", "2026-06-09")
    assert status == 2 and "backwards" in err
    status, _out, err = _run(capsys, "sync", "weather", "--listen", "10")
    assert status == 2 and "--listen" in err
    assert fake.requests == []


# -- the readers, no network -------------------------------------------------------------------------------


def _row(day: str, lat: float, lon: float, **values: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "weather/v1",
        "raw_id": f"{day}@{lat},{lon}",
        "day": day,
        "lat": lat,
        "lon": lon,
        "t_min_c": 3.2,
        "t_max_c": 11.8,
        "precipitation_mm": 4.2,
        "wind_max_kmh": 31.3,
        "weather_code": 3,
        "sunrise": f"{day}T06:12:00Z",
        "sunset": f"{day}T16:03:00Z",
        "evidence": "external",
        "provider": "open-meteo",
        "dataset": "archive",
    }
    payload.update(values)
    return {
        "id": f"id-{day}-{lat}-{lon}",
        "seq": 1,
        "at": f"{day}T00:00:00Z",
        "end": None,
        "tz": "Europe/Oslo",
        "source": "weather",
        "kind": "weather",
        "tier": 1,
        "payload": payload,
    }


def test_rows_by_day_leave_retracted_lines_out_and_the_day_row_prefers_the_night_cluster() -> None:
    home = _row("2026-01-10", 59.9, 10.8)
    away = _row("2026-01-10", 60.4, 5.3, t_min_c=-2.0, t_max_c=1.0, weather_code=73)
    old = _row("2026-01-09", 59.9, 10.8)
    retraction = {
        "id": "r1",
        "seq": 9,
        "at": "2026-01-11T00:00:00Z",
        "end": None,
        "tz": "Europe/Oslo",
        "source": "manual",
        "kind": "retraction",
        "tier": 2,
        "payload": {"schema": "retraction/v1", "supersedes": old["id"], "reason": "wrong"},
    }
    by_day = weather.by_day([home, away, old, retraction])
    assert sorted(by_day) == ["2026-01-10"]
    row = weather.day_row(by_day["2026-01-10"], (60.39, 5.32))
    assert row is not None and row["lat"] == 60.4 and row["description"] == "snow" and len(row["places"]) == 2
    assert row["line"] == away["id"] and row["places"][1]["line"] == home["id"]
    row = weather.day_row(by_day["2026-01-10"], None)
    assert row is not None and row["lat"] == 59.9, "with no night, the first cluster"
    assert weather.day_row([], None) is None
    text = weather.text(row, "Europe/Oslo")
    assert text == f"3°{EN_DASH}12° · 4.2 mm · wind 31 km/h · overcast · sun 07:12{EN_DASH}17:03 · 2 places"


def test_text_says_what_it_has_and_describes_the_wmo_code() -> None:
    bare = _row(
        "2026-01-10",
        59.9,
        10.8,
        t_min_c=None,
        precipitation_mm=None,
        wind_max_kmh=None,
        weather_code=None,
        sunrise=None,
        sunset=None,
    )
    sparse = weather.day_row(weather.by_day([bare])["2026-01-10"], None)
    assert sparse is not None and weather.text(sparse, "Europe/Oslo") == "max 12°"
    assert weather.describe(0) == "clear" and weather.describe(95) == "thunderstorm"
    assert weather.describe(45) == "fog" and weather.describe(1234) is None and weather.describe(None) is None
    frozen = _row("2026-01-10", 59.9, 10.8, t_min_c=-12.4, t_max_c=-3.6, precipitation_mm=0.0)
    cold = weather.day_row(weather.by_day([frozen])["2026-01-10"], None)
    assert cold is not None and weather.text(cold, "Europe/Oslo").startswith(f"-12°{EN_DASH}-4° · 0 mm")


def test_span_sums_a_window_and_names_the_extremes() -> None:
    rows = [
        _row("2026-01-10", 59.9, 10.8, t_min_c=-5.0, t_max_c=2.0, precipitation_mm=0.4, wind_max_kmh=20.0),
        _row("2026-01-10", 60.4, 5.3, t_min_c=1.0, t_max_c=6.0, precipitation_mm=12.0, wind_max_kmh=80.0),
        _row("2026-01-11", 59.9, 10.8, t_min_c=-1.0, t_max_c=9.5, precipitation_mm=1.0, wind_max_kmh=30.0),
        _row("2026-01-13", 59.9, 10.8, t_min_c=None, t_max_c=None, precipitation_mm=None, wind_max_kmh=None),
    ]
    span = weather.span(weather.by_day(rows), ["2026-01-10", "2026-01-11", "2026-01-12", "2026-01-13"])
    assert span is not None
    assert span["days"] == 3 and span["of"] == 4
    assert span["t_min"] == {"value": -5.0, "day": "2026-01-10"} and span["t_max"] == {
        "value": 9.5,
        "day": "2026-01-11",
    }
    assert span["precipitation_mm"] == 13.0, "per day the wettest place, never the sum of the places"
    assert span["wet_days"] == 2, "a day is wet at 1 mm"
    assert span["wind_max"] == {"value": 80.0, "day": "2026-01-10"}
    assert len(span["lines"]) == 4
    assert (
        weather.span_text(span) == f"-5°{EN_DASH}10° · 13 mm, 2 wet days · wind up to 80 km/h · 3 of 4 days"
    )
    assert weather.span({}, ["2026-01-10"]) is None


def test_day_year_and_trips_show_the_weather_without_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], fake: FakeOpenMeteo
) -> None:
    persona_record(tmp_path, monkeypatch)
    status, _out, err = _run(capsys, "sync", "weather", "--since", "2026-06-08", "--until", "2026-06-21")
    assert status == 0, err

    def bomb(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a reader opened the network")

    monkeypatch.setattr(weather_adapter, "urlopen", bomb)
    status, out, _err = _run(capsys, "day", "2026-06-16", "--json")
    assert status == 0
    data = json.loads(out)
    row = data["weather"]
    assert row["lat"] == 47.4 and row["lon"] == 8.5 and row["day"] == "2026-06-16" and len(row["places"]) == 1
    assert row["description"] in ("overcast", "rain") and row["line"]
    status, out, _err = _run(capsys, "day", "2026-06-16")
    assert status == 0
    [weather_line] = [text for text in out.splitlines() if text.startswith("  weather")]
    assert re.search(
        rf"weather\s+\d+°{EN_DASH}\d+° · [\d.]+ mm · wind \d+ km/h · (overcast|rain) · "
        rf"sun 04:00{EN_DASH}22:30$",
        weather_line,
    ), weather_line
    assert out.index("  health") < out.index("  weather") < out.index("  sources")
    status, out, _err = _run(capsys, "day", "2026-06-13")
    assert status == 0 and "· 2 places" in out, "the night at anchor and the morning at home"

    status, out, _err = _run(capsys, "year", "2026", "--json")
    assert status == 0
    span = json.loads(out)["weather"]
    assert span["of"] == 14 and span["days"] == 14 and span["t_min"]["day"] >= "2026-06-08"
    status, out, _err = _run(capsys, "year", "2026")
    assert status == 0
    [year_line] = [text for text in out.splitlines() if text.startswith("  weather")]
    assert "wet days" in year_line and "14 of 14 days" in year_line

    status, out, _err = _run(capsys, "trips", "--year", "2026", "--json")
    assert status == 0
    boat, zurich = json.loads(out)["trips"]
    assert zurich["weather"]["of"] == 4 and zurich["weather"]["days"] == 4, "15 June to the return day"
    assert boat["weather"]["of"] == 2
    status, out, _err = _run(capsys, "trips", "--year", "2026")
    assert status == 0 and out.count("weather ") == 2

    status, out, _err = _run(capsys, "year", "2026", "--html", str(tmp_path / "year.html"))
    assert status == 0 and "Weather" in (tmp_path / "year.html").read_text(encoding="utf-8")


def test_a_record_without_weather_lines_shows_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch)
    status, out, _err = _run(capsys, "day", "2026-06-09", "--json")
    assert status == 0 and json.loads(out)["weather"] is None
    status, out, _err = _run(capsys, "day", "2026-06-09")
    assert status == 0 and "weather" not in out
    status, out, _err = _run(capsys, "year", "2026", "--json")
    assert status == 0 and json.loads(out)["weather"] is None
    status, out, _err = _run(capsys, "trips", "--year", "2026", "--json")
    assert status == 0 and all(t["weather"] is None for t in json.loads(out)["trips"])
