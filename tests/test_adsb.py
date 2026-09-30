"""The adsb adapter (OpenSky Network → location/v1 with `subject`, ADR 0018) in both its modes: a
saved `states/all` response read by `logbook add`, and `logbook sync adsb` polling the REST API. No
network: `urlopen` is a fake serving the fixture. Every identifier is synthetic: icao24 addresses in
the unallocated 000000 block, registrations under the unassigned `ZZ` prefix."""

from __future__ import annotations

import base64
import json
import sys
import urllib.error
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters, assets, cli
from logbook.adapters import adsb, ais
from logbook.assets import Asset
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "adsb" / "states.json"
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
PLANE = Asset(id="ln-zz1", kind="aircraft", name="the club's Cub", icao24="000a01", registration="ZZ-ZZ1")
PARKED = Asset(id="ln-zz2", kind="aircraft", name="the other one", icao24="000a02")
NOFIX = Asset(id="ln-zz3", kind="aircraft", name="the third", icao24="000a03")
YACHT = Asset(id="solvind", kind="yacht", name="Solvind", mmsi="999000001")
REGISTRY = [PLANE, PARKED, NOFIX, YACHT]
T0 = 1_772_350_200  # 2026-03-01T07:30:00Z
RESPONSE = json.loads(FIXTURE.read_text(encoding="utf-8"))
ANON = adsb.Config(url=adsb.DEFAULT_URL, user=None, password=None)
PASSWORD = "synthetic-opensky-password-0000"


class FakeOpenSky:
    """Serves GET /api/states/all from `response`; records every request; can fail with a status."""

    def __init__(self, response: Any, status: int | None = None):
        self.response = response
        self.status = status
        self.requests: list[dict[str, Any]] = []

    def __call__(self, req: Any, timeout: float) -> Any:
        url = urlsplit(req.full_url)
        self.requests.append(
            {"path": url.path, "query": parse_qs(url.query), "headers": dict(req.header_items())}
        )
        if self.status is not None:
            raise urllib.error.HTTPError(req.full_url, self.status, "nope", {}, None)  # type: ignore[arg-type]
        body = (
            self.response if isinstance(self.response, bytes) else json.dumps(self.response).encode("utf-8")
        )
        return _Response(body)


class _Response:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def _serve(monkeypatch: pytest.MonkeyPatch, response: Any = None, **kw: Any) -> FakeOpenSky:
    fake = FakeOpenSky(RESPONSE if response is None else response, **kw)
    monkeypatch.setattr(adsb, "urlopen", fake)
    return fake


# -- registry and configure -------------------------------------------------------------------


def test_adsb_is_both_a_file_and_a_live_adapter_and_recognises_a_saved_response():
    assert adapters.live("adsb") is adsb
    assert adapters.named("adsb") is adsb
    assert adapters.find(FIXTURE) is adsb
    assert adsb.NAME == "adsb" and adsb.KIND == "location"


def test_sniff_declines_other_files(tmp_path):
    assert adsb.sniff(ROOT / "tests" / "fixtures" / "ais" / "messages.jsonl") is False
    assert adsb.sniff(ROOT / "tests" / "fixtures" / "dawarich" / "export.json") is False
    assert adsb.sniff(tmp_path / "missing.json") is False


def test_configure_needs_nothing_and_reads_the_optional_credentials():
    assert adsb.ENV == ("LOGBOOK_OPENSKY_USER", "LOGBOOK_OPENSKY_PASS")
    assert adsb.configure({}) == ANON
    config = adsb.configure({"LOGBOOK_OPENSKY_USER": "pilot", "LOGBOOK_OPENSKY_PASS": PASSWORD})
    assert config == adsb.Config(url=adsb.DEFAULT_URL, user="pilot", password=PASSWORD)
    assert PASSWORD not in repr(config)
    assert adsb.configure({"LOGBOOK_OPENSKY_URL": "http://sky.test/api/"}).url == "http://sky.test/api"


def test_configure_refuses_a_user_without_a_password_and_the_reverse():
    with pytest.raises(ValueError, match="LOGBOOK_OPENSKY_PASS"):
        adsb.configure({"LOGBOOK_OPENSKY_USER": "pilot"})
    with pytest.raises(ValueError, match="LOGBOOK_OPENSKY_USER"):
        adsb.configure({"LOGBOOK_OPENSKY_PASS": PASSWORD})


# -- the mapping -----------------------------------------------------------------------------------


def test_a_state_vector_maps_to_a_location_line_of_the_aircraft():
    assert adsb.draft(RESPONSE["states"][0], PLANE) == {
        "at": "2026-03-01T07:30:00Z",
        "end": None,
        "tz": None,
        "source": "adsb",
        "kind": "location",
        "tier": 1,
        "payload": {
            "schema": "location/v1",
            "lat": 59.905,
            "lon": 10.735,
            "alt_m": 350.52,
            "speed_mps": 41.2,
            "heading_deg": 184.3,
            "tracker": "opensky",
            "raw_id": f"opensky:000a01:{T0}",
            "subject": "ln-zz1",
            "extra": {
                "icao24": "000a01",
                "callsign": "ZZZZ1",
                "on_ground": False,
                "baro_alt_m": 320.04,
                "vertical_rate_mps": 1.3,
                "squawk": "7000",
                "last_contact": T0 + 4,
                "position_source": 0,
            },
        },
    }


def test_altitude_falls_back_to_barometric_when_geometric_is_null():
    state = list(RESPONSE["states"][0])
    state[13] = None
    assert adsb.draft(state, PLANE)["payload"]["alt_m"] == 320.04


def test_the_file_mode_yields_the_registered_aircraft_and_counts_what_it_skipped():
    counts: dict[str, int] = {}
    lines = list(adsb.run(FIXTURE, counts=counts, assets=REGISTRY))
    assert [(d["at"], d["payload"]["subject"]) for d in lines] == [("2026-03-01T07:30:00Z", "ln-zz1")]
    assert counts == {"skipped_unknown_subject": 1, "skipped_no_timestamp": 1, "skipped_bad_coordinates": 1}


def test_the_file_mode_honours_since():
    assert list(adsb.run(FIXTURE, since="2026-03-01T07:30:01Z", assets=REGISTRY)) == []
    assert len(list(adsb.run(FIXTURE, since="2026-03-01T07:30:00Z", assets=REGISTRY))) == 1


def test_every_line_validates_against_the_envelope_schema(tmp_path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    lb.append_many(adsb.run(FIXTURE, assets=REGISTRY))
    validator = Draft202012Validator(SCHEMA)
    (line,) = list(lb.lines())
    validator.validate(line)
    assert line["payload"]["subject"] == "ln-zz1"


# -- pull: the REST API ------------------------------------------------------------------------


def test_pull_asks_states_all_for_every_registered_icao24_anonymously_by_default(monkeypatch):
    fake = _serve(monkeypatch)
    drafts = list(adsb.pull(ANON, assets=REGISTRY))
    assert len(drafts) == 1 and drafts[0]["payload"]["subject"] == "ln-zz1"
    (request,) = fake.requests
    assert request["path"] == "/api/states/all"
    assert request["query"] == {"icao24": ["000a01", "000a02", "000a03"]}
    assert "authorization" not in {k.lower() for k in request["headers"]}


def test_pull_sends_basic_credentials_when_configured_and_never_in_the_url(monkeypatch):
    fake = _serve(monkeypatch)
    config = adsb.Config(url=adsb.DEFAULT_URL, user="pilot", password=PASSWORD)
    list(adsb.pull(config, assets=REGISTRY))
    (request,) = fake.requests
    headers = {k.lower(): v for k, v in request["headers"].items()}
    assert headers["authorization"] == "Basic " + base64.b64encode(f"pilot:{PASSWORD}".encode()).decode()
    assert PASSWORD not in request["path"] and PASSWORD not in json.dumps(request["query"])


def test_a_saved_response_and_the_same_response_polled_live_are_the_same_lines(monkeypatch):
    _serve(monkeypatch)
    assert list(adsb.pull(ANON, assets=REGISTRY)) == list(adsb.run(FIXTURE, assets=REGISTRY))


def test_pull_with_states_null_yields_nothing(monkeypatch):
    _serve(monkeypatch, {"time": T0, "states": None})
    assert list(adsb.pull(ANON, assets=REGISTRY)) == []


def test_pull_refuses_to_start_without_a_registered_icao24(monkeypatch):
    fake = _serve(monkeypatch)
    with pytest.raises(ValueError, match="logbook assets add") as e:
        list(adsb.pull(ANON, assets=[YACHT]))
    assert "icao24" in str(e.value) and fake.requests == []


@pytest.mark.parametrize(("status", "phrase"), [(401, "credentials"), (429, "rate"), (503, "503")])
def test_pull_turns_an_http_error_into_one_clear_oserror_without_the_password(monkeypatch, status, phrase):
    _serve(monkeypatch, status=status)
    config = adsb.Config(url=adsb.DEFAULT_URL, user="pilot", password=PASSWORD)
    with pytest.raises(OSError, match=phrase) as e:
        list(adsb.pull(config, assets=REGISTRY))
    assert PASSWORD not in str(e.value)


def test_pull_refuses_a_body_that_is_not_a_states_response(monkeypatch):
    _serve(monkeypatch, b"<html>login</html>")
    with pytest.raises(ValueError, match="states"):
        list(adsb.pull(ANON, assets=REGISTRY))
    _serve(monkeypatch, [1, 2, 3])
    with pytest.raises(ValueError, match="states"):
        list(adsb.pull(ANON, assets=REGISTRY))


def test_watermark_is_the_fix_time_and_group_is_the_subject():
    draft = adsb.draft(RESPONSE["states"][0], PLANE)
    assert adsb.watermark(draft) == "2026-03-01T07:30:00Z"
    assert adsb.group(draft) == "ln-zz1"
    assert adsb.GROUP_MARKS is True
    assert not hasattr(adsb, "resume")


def test_ais_and_adsb_write_the_same_shape_of_line():
    from_ais = ais.draft(
        json.loads(
            (ROOT / "tests" / "fixtures" / "ais" / "messages.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()[0]
        ),
        YACHT,
    )
    from_adsb = adsb.draft(RESPONSE["states"][0], PLANE)
    assert set(from_ais) == set(from_adsb)
    for key in ("schema", "lat", "lon", "tracker", "raw_id", "subject", "extra"):
        assert key in from_ais["payload"] and key in from_adsb["payload"]


# -- the CLI ---------------------------------------------------------------------------------------


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    for name in ("LOGBOOK_OPENSKY_USER", "LOGBOOK_OPENSKY_PASS", "LOGBOOK_OPENSKY_URL"):
        monkeypatch.delenv(name, raising=False)
    for asset in REGISTRY:
        assets.add(lb.root, asset)
    return lb


def _sync(*args: str) -> None:
    cli.main(["sync", "adsb", *args])


def _state(lb: Logbook) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((lb.root / "state" / "adsb.json").read_text(encoding="utf-8"))
    return data


def test_sync_appends_each_aircrafts_state_once_and_keeps_a_watermark_per_asset(lb, monkeypatch, capsys):
    _serve(monkeypatch)
    _sync()
    out = capsys.readouterr().out
    assert "adsb: 1 new lines of 1 seen from the beginning" in out
    assert "ln-zz1: 1 new of 1 seen" in out
    assert _state(lb) == {"since": "2026-03-01T07:30:00Z", "groups": {"ln-zz1": "2026-03-01T07:30:00Z"}}
    _sync()  # the same state vector again: a parked aircraft's last fix, or a poll too soon
    assert "adsb: 0 new lines of 1 seen" in capsys.readouterr().out
    assert lb.meta["seq"] == 1
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 1


def test_sync_a_later_poll_adds_the_new_fix_and_advances_only_that_assets_mark(lb, monkeypatch, capsys):
    _serve(monkeypatch)
    _sync()
    later = json.loads(json.dumps(RESPONSE))
    later["states"][0][3] = T0 + 60
    later["states"][2][3], later["states"][2][5], later["states"][2][6] = T0 + 30, 10.61, 59.94
    _serve(monkeypatch, later)
    _sync()
    out = capsys.readouterr().out
    assert "adsb: 2 new lines of 2 seen" in out
    assert _state(lb) == {
        "since": "2026-03-01T07:31:00Z",
        "groups": {"ln-zz1": "2026-03-01T07:31:00Z", "ln-zz2": "2026-03-01T07:30:30Z"},
    }


def test_sync_dry_run_writes_nothing(lb, monkeypatch, capsys):
    _serve(monkeypatch)
    _sync("--dry-run")
    assert "adsb: 1 lines from the beginning (dry run, nothing written)" in capsys.readouterr().out
    assert lb.meta["seq"] == 0 and not (lb.root / "state").exists()


def test_sync_server_error_exits_1_on_one_line(lb, monkeypatch, capsys):
    _serve(monkeypatch, status=503)
    with pytest.raises(SystemExit) as e:
        _sync()
    assert e.value.code == 1
    assert capsys.readouterr().err.startswith("sync: adsb: ")


def test_sync_with_a_broken_registry_exits_2_naming_the_file(lb, monkeypatch, capsys):
    assets.assets_path(lb.root).write_text("[]", encoding="utf-8")
    _serve(monkeypatch)
    with pytest.raises(SystemExit) as e:
        _sync()
    assert e.value.code == 2
    assert "assets.json" in capsys.readouterr().err
