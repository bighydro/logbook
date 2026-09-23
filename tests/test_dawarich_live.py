"""The dawarich live adapter and `logbook sync dawarich`: the shared mapping (an exported point and the
same point pulled live are the same line), paging, the lookback overlap, the first run continuing
from the record, the watermark, --since, missing environment, bad coordinates. No network: `urlopen`
is replaced by a fake Dawarich that serves synthetic Oslo points from memory."""

from __future__ import annotations

import json
import math
import sys
import urllib.error
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters, cli
from logbook.adapters import dawarich, dawarich_live
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "tests" / "fixtures" / "dawarich" / "export.json"
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
KEY = "synthetic-dawarich-key-0000"
ENV = {"LOGBOOK_DAWARICH_URL": "http://dawarich.test:3000", "LOGBOOK_DAWARICH_KEY": KEY}
CONFIG = dawarich_live.Config(url="http://dawarich.test:3000", key=KEY, lookback_h=24.0)
TRACKER = "5d1f8e2a-3b4c-4d5e-8f60-718293a4b5c6"
T0 = 1_775_970_000  # 2026-04-12T05:00:00Z, the export's first point
HOUR = 3600
RFC0001_FIELDS = {
    "schema",
    "lat",
    "lon",
    "accuracy_m",
    "alt_m",
    "speed_mps",
    "heading_deg",
    "provider",
    "tracker",
    "raw_id",
    "extra",
}


def _stamp(unix: int) -> str:
    return datetime.fromtimestamp(unix, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _unix(stamp: str) -> int:
    return int(datetime.fromisoformat(stamp).timestamp())


def _point(i: int, timestamp: object, **fields: Any) -> dict[str, Any]:
    """One synthetic row as GET /api/v1/points returns it: Oslo, one tracker."""
    row: dict[str, Any] = {
        "id": 1000 + i,
        "latitude": 59.91 + i * 0.001,
        "longitude": 10.75 + i * 0.001,
        "timestamp": timestamp,
        "altitude": "20.0",
        "accuracy": 10,
        "velocity": "1.2",
        "course": "90.0",
        "battery": 80,
        "battery_status": "unplugged",
        "tracker_id": TRACKER,
        "city": "Oslo",
        "country": "Norway",
        "topic": "owntracks/owner/phone",
        "import_id": None,
    }
    row.update(fields)
    return row


def _export_rows() -> list[dict[str, Any]]:
    """The export fixture's points as the API serves the same points: the properties flattened into
    the row, the coordinates as latitude/longitude, plus fields the export does not carry."""
    features = json.loads(EXPORT.read_text(encoding="utf-8"))["features"]
    rows = []
    for i, f in enumerate(features):
        lon, lat = f["geometry"]["coordinates"]
        rows.append(
            {
                "id": 500 + i,
                "latitude": lat,
                "longitude": lon,
                **f["properties"],
                "city": "Oslo",
                "country": "Norway",
                "battery_status": "charging",
                "created_at": "2026-04-12T20:00:00.000Z",
            }
        )
    return rows


class FakeDawarich:
    """Serves GET /api/v1/points from `points`: filtered on start_at/end_at, oldest first, paged by
    page/per_page, an empty array past the end. Records every request."""

    def __init__(self, points: list[dict[str, Any]], ignore_page: bool = False):
        self.points = points
        self.ignore_page = ignore_page
        self.requests: list[dict[str, Any]] = []

    def __call__(self, req: Any, timeout: float) -> Any:
        url = urlsplit(req.full_url)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.requests.append({"path": url.path, "query": query, "headers": dict(req.header_items())})
        start, end = _unix(query["start_at"]), _unix(query["end_at"])
        page, per_page = int(query["page"]), int(query["per_page"])
        timed = [p for p in self.points if isinstance(p.get("timestamp"), int)]
        chosen = sorted((p for p in timed if start <= p["timestamp"] <= end), key=lambda p: p["timestamp"])
        if self.ignore_page:
            page = 1
        body = json.dumps(chosen[(page - 1) * per_page : page * per_page]).encode("utf-8")
        return _Response(body)

    def pages(self) -> list[int]:
        return [int(r["query"]["page"]) for r in self.requests]


class _Response:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def _serve(monkeypatch: pytest.MonkeyPatch, points: list[dict[str, Any]], **kw: Any) -> FakeDawarich:
    fake = FakeDawarich(points, **kw)
    monkeypatch.setattr(dawarich_live, "urlopen", fake)
    return fake


# -- registry and configure -------------------------------------------------------


def test_registry_has_dawarich_both_as_a_file_and_as_a_live_adapter():
    assert adapters.live("dawarich") is dawarich_live
    assert dawarich_live.NAME == dawarich.NAME == "dawarich"
    assert adapters.find(EXPORT) is dawarich
    assert dawarich_live not in adapters.file_adapters()
    assert dawarich not in adapters.live_adapters()


def test_configure_reads_url_key_and_the_default_lookback():
    assert dawarich_live.ENV == ("LOGBOOK_DAWARICH_URL", "LOGBOOK_DAWARICH_KEY")
    assert dawarich_live.configure({**ENV, "LOGBOOK_DAWARICH_URL": "http://dawarich.test:3000/"}) == CONFIG


def test_configure_reads_the_lookback_override():
    config = dawarich_live.configure({**ENV, "LOGBOOK_DAWARICH_LOOKBACK_H": "72"})
    assert config is not None and config.lookback_h == 72.0


@pytest.mark.parametrize("bad", ["soon", "-1", "nan", "inf"])
def test_configure_refuses_a_lookback_that_is_not_a_non_negative_number(bad):
    with pytest.raises(ValueError, match="LOGBOOK_DAWARICH_LOOKBACK_H"):
        dawarich_live.configure({**ENV, "LOGBOOK_DAWARICH_LOOKBACK_H": bad})


@pytest.mark.parametrize("missing", ["LOGBOOK_DAWARICH_URL", "LOGBOOK_DAWARICH_KEY"])
def test_configure_returns_none_when_a_variable_is_absent_or_empty(missing):
    assert dawarich_live.configure({k: v for k, v in ENV.items() if k != missing}) is None
    assert dawarich_live.configure({**ENV, missing: "  "}) is None


def test_the_key_never_appears_in_the_configs_repr():
    assert KEY not in repr(CONFIG) and KEY not in str(CONFIG)


def test_resume_is_the_mark_less_the_lookback():
    assert dawarich_live.resume(CONFIG, "2026-04-12T18:00:00Z") == "2026-04-11T18:00:00Z"
    config = dawarich_live.Config(url=CONFIG.url, key=KEY, lookback_h=1.5)
    assert dawarich_live.resume(config, "2026-04-12T18:00:00Z") == "2026-04-12T16:30:00Z"


# -- the shared mapping ------------------------------------------------------------------


def test_an_exported_point_and_the_same_point_pulled_live_are_the_same_line(monkeypatch):
    _serve(monkeypatch, _export_rows())
    from_export = list(dawarich.run(EXPORT))
    live = list(dawarich_live.pull(CONFIG, "2026-04-01T00:00:00Z"))
    assert len(live) == len(from_export) == 40
    for exported, pulled in zip(from_export, live, strict=True):
        assert pulled == exported
        assert pulled["payload"]["raw_id"] == exported["payload"]["raw_id"]


def test_both_modules_use_one_mapping_function():
    assert dawarich_live.draft is dawarich.draft


def test_a_live_point_maps_exactly_the_file_adapters_fields_and_ignores_the_rest():
    line = dawarich_live._line(_point(0, T0), {})
    assert line == {
        "at": "2026-04-12T05:00:00Z",
        "end": None,
        "tz": None,
        "source": "dawarich",
        "kind": "location",
        "tier": 1,
        "payload": {
            "schema": "location/v1",
            "lat": 59.91,
            "lon": 10.75,
            "accuracy_m": 10.0,
            "alt_m": 20.0,
            "speed_mps": 1.2,
            "heading_deg": 90.0,
            "tracker": TRACKER,
            "raw_id": f"{TRACKER}:{T0}",
            "extra": {"track_id": None, "anomaly": None, "vertical_accuracy": None, "battery": 80},
        },
    }


def test_coordinates_sent_as_numeric_strings_are_read():
    line = dawarich_live._line(_point(0, T0, latitude="59.91", longitude="10.75"), {})
    assert line is not None and (line["payload"]["lat"], line["payload"]["lon"]) == (59.91, 10.75)


# -- pull: requests, paging, defence --------------------------------------------------------


def test_pull_asks_the_points_endpoint_with_a_bearer_key_and_a_fixed_window(monkeypatch):
    fake = _serve(monkeypatch, [_point(i, T0 + i * 60) for i in range(3)])
    list(dawarich_live.pull(CONFIG, "2026-04-12T00:00:00Z"))
    first = fake.requests[0]
    assert first["path"] == "/api/v1/points"
    assert {k.lower(): v for k, v in first["headers"].items()}["authorization"] == f"Bearer {KEY}"
    assert first["query"]["start_at"] == "2026-04-12T00:00:00Z"
    assert first["query"]["per_page"] == str(dawarich_live.PAGE_SIZE)
    assert KEY not in json.dumps(first["query"])
    assert len({r["query"]["end_at"] for r in fake.requests}) == 1  # one window for every page


def test_pull_without_since_starts_at_the_epoch(monkeypatch):
    fake = _serve(monkeypatch, [_point(0, T0)])
    assert len(list(dawarich_live.pull(CONFIG, None))) == 1
    assert fake.requests[0]["query"]["start_at"] == "1970-01-01T00:00:00Z"


def test_pull_pages_until_an_empty_page(monkeypatch):
    monkeypatch.setattr(dawarich_live, "PAGE_SIZE", 3)
    fake = _serve(monkeypatch, [_point(i, T0 + i * 60) for i in range(7)])
    lines = list(dawarich_live.pull(CONFIG, None))
    assert fake.pages() == [1, 2, 3, 4]  # 3 + 3 + 1, then the empty page
    assert [line["at"] for line in lines] == [_stamp(T0 + i * 60) for i in range(7)]


def test_pull_stops_when_the_server_repeats_a_page(monkeypatch):
    monkeypatch.setattr(dawarich_live, "PAGE_SIZE", 3)
    fake = _serve(monkeypatch, [_point(i, T0 + i * 60) for i in range(7)], ignore_page=True)
    assert len(list(dawarich_live.pull(CONFIG, None))) == 3
    assert fake.pages() == [1, 2]


def test_pull_reports_the_running_point_count_after_each_page(monkeypatch):
    monkeypatch.setattr(dawarich_live, "PAGE_SIZE", 3)
    _serve(monkeypatch, [_point(i, T0 + i * 60) for i in range(7)])
    ticks: list[int] = []
    list(dawarich_live.pull(CONFIG, None, progress=lambda n, _elapsed: ticks.append(n)))
    assert ticks == [3, 6, 7]


@pytest.mark.parametrize(
    "fields",
    [
        {"latitude": None},
        {"longitude": None},
        {"latitude": "north"},
        {"latitude": 91.0},
        {"longitude": -180.5},
        {"latitude": float("nan")},
        {"latitude": True},
    ],
)
def test_a_point_with_a_bad_coordinate_is_skipped_and_counted(monkeypatch, fields):
    bad = _point(1, T0 + 60, **fields)
    _serve(monkeypatch, [_point(0, T0), bad, _point(2, T0 + 120)])
    counts: dict[str, int] = {}
    lines = list(dawarich_live.pull(CONFIG, None, counts=counts))
    assert [line["payload"]["raw_id"] for line in lines] == [f"{TRACKER}:{T0}", f"{TRACKER}:{T0 + 120}"]
    assert counts["skipped_bad_coordinates"] == 1


def test_a_point_missing_its_coordinates_altogether_is_skipped_and_counted():
    counts = dawarich_live._counts({})
    row = _point(0, T0)
    del row["latitude"], row["longitude"]
    assert dawarich_live._line(row, counts) is None
    assert counts["skipped_bad_coordinates"] == 1


def test_a_point_without_a_timestamp_or_tracker_is_skipped_and_counted():
    counts = dawarich_live._counts({})
    assert dawarich_live._line(_point(0, None), counts) is None
    assert dawarich_live._line(_point(0, "yesterday"), counts) is None
    assert dawarich_live._line(_point(0, T0, tracker_id=None), counts) is None
    assert counts == {"skipped_no_timestamp": 2, "skipped_bad_coordinates": 0, "skipped_no_tracker": 1}


def test_a_row_that_is_not_an_object_is_skipped_as_unusable():
    counts = dawarich_live._counts({})
    assert dawarich_live._line(["not", "a", "point"], counts) is None  # type: ignore[arg-type]
    assert counts["skipped_bad_coordinates"] == 1


def test_a_response_that_is_not_an_array_is_an_error(monkeypatch):
    monkeypatch.setattr(dawarich_live, "urlopen", lambda req, timeout: _Response(b'{"error": "nope"}'))
    with pytest.raises(ValueError, match="array"):
        list(dawarich_live.pull(CONFIG, None))


def test_watermark_is_the_points_own_time():
    line = dawarich_live._line(_point(0, T0), {})
    assert line is not None and dawarich_live.watermark(line) == "2026-04-12T05:00:00Z"


# -- the property: any row the API might send gives a valid RFC 0001 line or a counted skip ----

_number = st.one_of(
    st.none(),
    st.integers(-1000, 10_000),
    st.floats(allow_nan=True, allow_infinity=True),
    st.from_regex(r"-?[0-9]{1,4}(\.[0-9]{1,3})?", fullmatch=True),
    st.text(max_size=4),
)
_row = st.fixed_dictionaries(
    {
        "id": st.integers(1, 10**9),
        "timestamp": st.one_of(st.integers(0, 4_000_000_000), st.none(), st.text(max_size=3)),
        "latitude": st.one_of(st.floats(-100, 100), _number),
        "longitude": st.one_of(st.floats(-200, 200), _number),
        "tracker_id": st.one_of(st.just(TRACKER), st.none(), st.text(min_size=1, max_size=8)),
    },
    optional={
        "altitude": _number,
        "accuracy": _number,
        "velocity": _number,
        "course": _number,
        "vertical_accuracy": _number,
        "anomaly": st.one_of(st.none(), st.booleans()),
        "track_id": st.one_of(st.none(), st.integers(0, 99)),
        "battery": st.one_of(st.none(), st.integers(0, 100)),
        "ssid": st.one_of(st.none(), st.text(max_size=8)),
        "city": st.one_of(st.none(), st.just("Oslo")),
        "country": st.one_of(st.none(), st.just("Norway")),
        "geodata": st.one_of(
            st.none(), st.just({}), st.just({"properties": {"city": "Oslo", "osm_id": 1, "extent": [1]}})
        ),
        "surprise": st.text(max_size=4),
    },
)


@settings(max_examples=100, deadline=None)
@given(st.lists(_row, max_size=12))
def test_any_page_yields_only_lines_valid_against_the_schema_and_rfc_0001(tmp_path_factory, rows):
    rows = dawarich_live._decode(json.dumps(rows).encode("utf-8"))  # through the wire: NaN is not JSON
    counts = dawarich_live._counts({})
    lines = [line for row in rows if (line := dawarich_live._line(row, counts)) is not None]
    assert len(lines) + sum(counts.values()) == len(rows)
    for line in lines:
        p = line["payload"]
        assert (line["source"], line["kind"], line["tier"], line["end"]) == ("dawarich", "location", 1, None)
        assert set(p) <= RFC0001_FIELDS and p["schema"] == "location/v1"
        assert -90 <= p["lat"] <= 90 and -180 <= p["lon"] <= 180
        assert all(math.isfinite(p[k]) for k in ("lat", "lon"))
        for key in ("accuracy_m", "alt_m", "speed_mps", "heading_deg"):
            assert key not in p or (isinstance(p[key], float) and math.isfinite(p[key]))
        assert "heading_deg" not in p or 0 <= p["heading_deg"] <= 360
        assert isinstance(p["tracker"], str) and isinstance(p["raw_id"], str)
        assert p["raw_id"] == f"{p['tracker']}:{_unix(line['at'])}"
    lb = Logbook.init(tmp_path_factory.mktemp("lb"), "Europe/Oslo")
    assert lb.append_many(lines) == len({line["payload"]["raw_id"] for line in lines})
    _seq, _head, errors = lb.verify()
    assert errors == []
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)


# -- sync: the CLI ---------------------------------------------------------------------------


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("LOGBOOK_DAWARICH_LOOKBACK_H", raising=False)
    return lb


def _sync(*args: str) -> None:
    cli.main(["sync", "dawarich", *args])


def _state(lb: Logbook) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((lb.root / "state" / "dawarich.json").read_text(encoding="utf-8"))
    return data


def _write_state(lb: Logbook, since: str) -> None:
    (lb.root / "state").mkdir(exist_ok=True)
    (lb.root / "state" / "dawarich.json").write_text(json.dumps({"since": since}), encoding="utf-8")


DAY = [_point(i, T0 + i * HOUR) for i in range(6)]  # 05:00Z … 10:00Z


def test_sync_appends_every_point_and_stores_the_newest_point_time(lb, monkeypatch, capsys):
    _serve(monkeypatch, DAY)
    _sync()
    assert "dawarich: 6 new lines of 6 seen from the beginning" in capsys.readouterr().out
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 6
    assert _state(lb) == {"since": _stamp(T0 + 5 * HOUR)}
    assert next(lb.lines())["tz"] == "Europe/Oslo"


def test_sync_resumes_from_the_watermark_less_the_lookback_and_dedupes_the_overlap(lb, monkeypatch, capsys):
    _serve(monkeypatch, DAY)
    _sync()
    # the phone uploads a batch late: one point from two hours before the watermark, one after it
    late, newer = _point(10, T0 + 3 * HOUR + 30 * 60), _point(11, T0 + 7 * HOUR)
    fake = _serve(monkeypatch, [*DAY, late, newer])
    _sync()
    assert fake.requests[0]["query"]["start_at"] == _stamp(T0 + 5 * HOUR - 24 * HOUR)
    last = capsys.readouterr().out.splitlines()
    assert any("dawarich: 2 new lines of 8 seen" in line for line in last)
    assert any("6 already in the record" in line for line in last)
    raw_ids = [line["payload"]["raw_id"] for line in lb.lines()]
    assert len(raw_ids) == len(set(raw_ids)) == 8
    assert _state(lb) == {"since": _stamp(T0 + 7 * HOUR)}


def test_sync_lookback_can_be_overridden(lb, monkeypatch):
    monkeypatch.setenv("LOGBOOK_DAWARICH_LOOKBACK_H", "2")
    _write_state(lb, _stamp(T0 + 5 * HOUR))
    fake = _serve(monkeypatch, DAY)
    _sync()
    assert fake.requests[0]["query"]["start_at"] == _stamp(T0 + 3 * HOUR)
    assert lb.meta["seq"] == 3  # 08:00, 09:00, 10:00


def test_sync_first_run_continues_from_the_records_newest_point(lb, monkeypatch, capsys):
    lb.append_many(dawarich.run(EXPORT))  # a record seeded from an export ending 2026-04-12T18:00:00Z
    after = [_point(100 + i, 1_776_016_800 + (i + 1) * HOUR) for i in range(3)]
    fake = _serve(monkeypatch, [*_export_rows(), *after])
    _sync()
    assert fake.requests[0]["query"]["start_at"] == "2026-04-11T18:00:00Z"
    out = capsys.readouterr().out
    assert "the record's newest dawarich point, 2026-04-12T18:00:00Z" in out
    assert "3 new lines of 43 seen" in out and "40 already in the record" in out
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 43
    assert _state(lb) == {"since": "2026-04-12T21:00:00Z"}


def test_sync_first_run_on_an_empty_record_pulls_from_the_beginning(lb, monkeypatch):
    fake = _serve(monkeypatch, DAY)
    _sync()
    assert fake.requests[0]["query"]["start_at"] == "1970-01-01T00:00:00Z"


def test_sync_first_run_ignores_location_lines_from_other_sources(lb, monkeypatch):
    lb.append(
        at="2026-09-01T12:00:00Z",
        source="owntracks",
        kind="location",
        tier=1,
        payload={"schema": "location/v1", "lat": 59.9, "lon": 10.7},
    )
    fake = _serve(monkeypatch, DAY)
    _sync()
    assert fake.requests[0]["query"]["start_at"] == "1970-01-01T00:00:00Z"


def test_sync_since_is_used_as_given_without_lookback(lb, monkeypatch):
    _write_state(lb, _stamp(T0 + 5 * HOUR))
    fake = _serve(monkeypatch, DAY)
    _sync("--since", _stamp(T0 + 4 * HOUR))
    assert fake.requests[0]["query"]["start_at"] == _stamp(T0 + 4 * HOUR)
    assert lb.meta["seq"] == 2


def test_sync_never_moves_the_watermark_backwards(lb, monkeypatch):
    _write_state(lb, "2026-09-01T00:00:00Z")
    _serve(monkeypatch, DAY)
    _sync("--since", "2026-04-01T00:00:00Z")
    assert _state(lb) == {"since": "2026-09-01T00:00:00Z"}


def test_sync_re_run_appends_nothing(lb, monkeypatch, capsys):
    _serve(monkeypatch, DAY)
    _sync()
    _sync()
    last = capsys.readouterr().out.splitlines()
    assert any("dawarich: 0 new lines of 6 seen since" in line for line in last)
    assert "(6 already in the record)" in last[-1]
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 6


def test_sync_dry_run_writes_nothing(lb, monkeypatch, capsys):
    _serve(monkeypatch, DAY)
    _sync("--dry-run")
    out = capsys.readouterr().out
    assert "dawarich: 6 lines from the beginning (dry run, nothing written)" in out
    assert "-: 6" not in out  # no provenance tally for a source that has none
    assert lb.meta["seq"] == 0 and not (lb.root / "state").exists()


def test_sync_reports_skipped_points(lb, monkeypatch, capsys):
    _serve(monkeypatch, [*DAY, _point(50, T0 + 90, latitude="north"), _point(51, T0 + 95, longitude=None)])
    _sync()
    out = capsys.readouterr().out
    assert "skipped 0 without a timestamp, 2 with unusable coordinates" in out
    assert lb.meta["seq"] == 6


def test_sync_progress_counts_points(lb, monkeypatch, capsys):
    _serve(monkeypatch, DAY)
    _sync()
    assert "  6 points in 0s" in capsys.readouterr().err.splitlines()


@pytest.mark.parametrize("missing", ["LOGBOOK_DAWARICH_URL", "LOGBOOK_DAWARICH_KEY"])
def test_sync_refuses_to_run_without_a_variable_naming_it_on_one_line(lb, monkeypatch, capsys, missing):
    fake = _serve(monkeypatch, DAY)
    monkeypatch.delenv(missing)
    with pytest.raises(SystemExit) as e:
        _sync()
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and missing in err
    other = next(v for v in ENV if v != missing)
    assert other not in err and KEY not in err
    assert fake.requests == [] and lb.meta["seq"] == 0


def test_sync_refuses_a_bad_lookback_on_one_line(lb, monkeypatch, capsys):
    fake = _serve(monkeypatch, DAY)
    monkeypatch.setenv("LOGBOOK_DAWARICH_LOOKBACK_H", "a day")
    with pytest.raises(SystemExit) as e:
        _sync()
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "LOGBOOK_DAWARICH_LOOKBACK_H" in err
    assert fake.requests == []


def test_sync_server_error_exits_1_and_never_prints_the_key(lb, monkeypatch, capsys):
    def refused(req: Any, timeout: float) -> Any:
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", None, None)  # type: ignore[arg-type]

    monkeypatch.setattr(dawarich_live, "urlopen", refused)
    with pytest.raises(SystemExit) as e:
        _sync()
    assert e.value.code == 1
    captured = capsys.readouterr()
    assert "401" in captured.err
    assert KEY not in captured.err and KEY not in captured.out
    assert not (lb.root / "state").exists()


def test_sync_malformed_response_exits_1(lb, monkeypatch, capsys):
    monkeypatch.setattr(dawarich_live, "urlopen", lambda req, timeout: _Response(b"<html>login</html>"))
    with pytest.raises(SystemExit) as e:
        _sync()
    assert e.value.code == 1
    assert "dawarich" in capsys.readouterr().err
