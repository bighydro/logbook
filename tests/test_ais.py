"""The ais adapter (aisstream.io → location/v1 with `subject`, ADR 0018) in both its modes: a saved
stream of messages read by `logbook add`, and `logbook sync ais` listening to the websocket. No
network: the websocket is a fake fed from the fixture. Every identifier is synthetic: MMSI under
MID 999 (allocated to no country), the yacht `solvind`, which does not exist."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters, assets, cli
from logbook.adapters import ais
from logbook.assets import Asset
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "ais" / "messages.jsonl"
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
KEY = "synthetic-aisstream-key-0000"
ENV = {"LOGBOOK_AISSTREAM_KEY": KEY}
CONFIG = ais.Config(key=KEY, url=ais.DEFAULT_URL, listen_s=ais.LISTEN_S)
YACHT = Asset(id="solvind", kind="yacht", name="Solvind", mmsi="999000001", registration="ZZ-LOG1")
CAR = Asset(id="volvo", kind="car", name="the old Volvo", registration="ZZ 00001")
REGISTRY = [YACHT, CAR]
T0 = 1_772_350_200  # 2026-03-01T07:30:00Z, the fixture's first report
MESSAGES = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]


class FakeSocket:
    """What `websockets.sync.client.connect` returns, fed from a list: records what was sent, serves
    each message once, then raises TimeoutError as a quiet socket does when the deadline passes."""

    def __init__(self, messages: list[Any]):
        self.messages = list(messages)
        self.sent: list[str] = []
        self.closed = False
        self.timeouts: list[float | None] = []

    def __enter__(self) -> FakeSocket:
        return self

    def __exit__(self, *a: object) -> None:
        self.closed = True

    def send(self, text: str) -> None:
        self.sent.append(text)

    def recv(self, timeout: float | None = None) -> str:
        self.timeouts.append(timeout)
        if not self.messages:
            raise TimeoutError
        message = self.messages.pop(0)
        return message if isinstance(message, str) else json.dumps(message)


def _serve(monkeypatch: pytest.MonkeyPatch, messages: list[Any]) -> FakeSocket:
    socket = FakeSocket(messages)
    monkeypatch.setattr(ais, "_connect", lambda url, timeout: socket)
    return socket


# -- registry and configure -------------------------------------------------------------------


def test_ais_is_both_a_file_and_a_live_adapter_and_recognises_a_saved_stream():
    assert adapters.live("ais") is ais
    assert adapters.named("ais") is ais
    assert adapters.find(FIXTURE) is ais
    assert ais.NAME == "ais" and ais.KIND == "location"


def test_sniff_declines_other_files(tmp_path):
    assert ais.sniff(ROOT / "tests" / "fixtures" / "adsb" / "states.json") is False
    assert ais.sniff(ROOT / "tests" / "fixtures" / "dawarich" / "export.json") is False
    assert ais.sniff(tmp_path / "missing.jsonl") is False
    (tmp_path / "empty.jsonl").write_text("", encoding="utf-8")
    assert ais.sniff(tmp_path / "empty.jsonl") is False


def test_configure_reads_the_key_and_the_defaults():
    assert ais.ENV == ("LOGBOOK_AISSTREAM_KEY",)
    assert ais.configure(ENV) == CONFIG
    assert ais.configure({}) is None
    assert ais.configure({"LOGBOOK_AISSTREAM_KEY": "  "}) is None


def test_configure_reads_the_listen_window_and_url_overrides():
    config = ais.configure(
        {**ENV, "LOGBOOK_AISSTREAM_LISTEN_S": "5", "LOGBOOK_AISSTREAM_URL": "ws://ais.test/"}
    )
    assert config == ais.Config(key=KEY, url="ws://ais.test", listen_s=5.0)


@pytest.mark.parametrize("bad", ["soon", "0", "-1", "nan", "inf"])
def test_configure_refuses_a_listen_window_that_is_not_a_positive_number(bad):
    with pytest.raises(ValueError, match="LOGBOOK_AISSTREAM_LISTEN_S"):
        ais.configure({**ENV, "LOGBOOK_AISSTREAM_LISTEN_S": bad})


def test_the_key_never_appears_in_the_configs_repr():
    assert KEY not in repr(CONFIG) and KEY not in str(CONFIG)


# -- the mapping -----------------------------------------------------------------------------------


def test_a_class_b_report_maps_to_a_location_line_of_the_yacht():
    assert ais.draft(MESSAGES[0], YACHT) == {
        "at": "2026-03-01T07:30:00Z",
        "end": None,
        "tz": None,
        "source": "ais",
        "kind": "location",
        "tier": 1,
        "payload": {
            "schema": "location/v1",
            "lat": 59.905,
            "lon": 10.735,
            "speed_mps": 2.62,
            "heading_deg": 184.3,
            "tracker": "aisstream",
            "raw_id": f"aisstream:999000001:{T0}",
            "subject": "solvind",
            "extra": {
                "mmsi": "999000001",
                "message_type": "StandardClassBPositionReport",
                "sog_knots": 5.1,
                "cog_deg": 184.3,
                "true_heading_deg": 183,
                "ship_name": "SOLVIND",
            },
        },
    }


def test_a_class_a_report_keeps_navigational_status_and_rate_of_turn():
    payload = ais.draft(MESSAGES[1], YACHT)["payload"]
    assert payload["raw_id"] == f"aisstream:999000001:{T0 + 30}"
    assert payload["extra"]["message_type"] == "PositionReport"
    assert payload["extra"]["navigational_status"] == 0
    assert payload["extra"]["rate_of_turn"] == -2


def test_unavailable_speed_course_and_heading_are_left_out_not_written_as_sentinels():
    payload = ais.draft(MESSAGES[5], YACHT)["payload"]
    assert "speed_mps" not in payload and "heading_deg" not in payload
    assert "sog_knots" not in payload["extra"] and "cog_deg" not in payload["extra"]
    assert "true_heading_deg" not in payload["extra"]


def test_heading_falls_back_to_true_heading_when_course_is_unavailable():
    message = json.loads(json.dumps(MESSAGES[0]))
    message["Message"]["StandardClassBPositionReport"]["Cog"] = 360
    assert ais.draft(message, YACHT)["payload"]["heading_deg"] == 183


def test_the_file_mode_yields_the_yachts_positions_and_counts_what_it_skipped():
    counts: dict[str, int] = {}
    lines = list(ais.run(FIXTURE, counts=counts, assets=REGISTRY))
    assert [line["at"] for line in lines] == [
        "2026-03-01T07:30:00Z",
        "2026-03-01T07:30:30Z",
        "2026-03-01T07:31:30Z",
        "2026-03-01T07:32:00Z",
    ]
    assert all(line["payload"]["subject"] == "solvind" for line in lines)
    assert counts == {
        "skipped_not_a_position": 1,
        "skipped_unknown_subject": 1,
        "skipped_bad_coordinates": 1,
        "skipped_no_timestamp": 1,
    }


def test_the_file_mode_honours_since():
    lines = list(ais.run(FIXTURE, since="2026-03-01T07:31:00Z", assets=REGISTRY))
    assert [line["at"] for line in lines] == ["2026-03-01T07:31:30Z", "2026-03-01T07:32:00Z"]


def test_without_a_registry_every_report_is_of_an_unknown_subject():
    counts: dict[str, int] = {}
    assert list(ais.run(FIXTURE, counts=counts)) == []
    assert counts["skipped_unknown_subject"] == 7


def test_every_line_validates_against_the_envelope_schema(tmp_path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    lb.append_many(ais.run(FIXTURE, assets=REGISTRY))
    validator = Draft202012Validator(SCHEMA)
    lines = list(lb.lines())
    assert len(lines) == 4
    for line in lines:
        validator.validate(line)
        assert line["payload"]["subject"] == "solvind"


# -- pull: the websocket -------------------------------------------------------------------------


def test_pull_subscribes_with_the_key_the_registered_mmsis_and_position_types_only(monkeypatch):
    socket = _serve(monkeypatch, [])
    assert list(ais.pull(CONFIG, assets=REGISTRY)) == []
    (subscription,) = (json.loads(text) for text in socket.sent)
    assert subscription == {
        "APIKey": KEY,
        "BoundingBoxes": [[[-90, -180], [90, 180]]],
        "FiltersShipMMSI": ["999000001"],
        "FilterMessageTypes": ["PositionReport", "StandardClassBPositionReport"],
    }
    assert socket.closed
    assert all(t is not None and 0 < t <= CONFIG.listen_s for t in socket.timeouts)


def test_a_saved_stream_and_the_same_stream_heard_live_are_the_same_lines(monkeypatch):
    _serve(monkeypatch, MESSAGES)
    from_file = list(ais.run(FIXTURE, assets=REGISTRY))
    live_counts: dict[str, int] = {}
    live = list(ais.pull(CONFIG, assets=REGISTRY, counts=live_counts))
    assert live == from_file and len(live) == 4
    assert live_counts["skipped_unknown_subject"] == 1


def test_pull_yields_oldest_first_whatever_order_the_stream_had(monkeypatch):
    _serve(monkeypatch, [MESSAGES[7], MESSAGES[0], MESSAGES[1]])
    assert [d["at"] for d in ais.pull(CONFIG, assets=REGISTRY)] == [
        "2026-03-01T07:30:00Z",
        "2026-03-01T07:30:30Z",
        "2026-03-01T07:32:00Z",
    ]


def test_pull_honours_since_and_reports_progress(monkeypatch):
    _serve(monkeypatch, MESSAGES)
    ticks: list[int] = []
    drafts = list(
        ais.pull(
            CONFIG, since="2026-03-01T07:31:00+00:00", assets=REGISTRY, progress=lambda n, _s: ticks.append(n)
        )
    )
    assert [d["at"] for d in drafts] == ["2026-03-01T07:31:30Z", "2026-03-01T07:32:00Z"]
    assert ticks and ticks[-1] == len(MESSAGES)


def test_pull_stops_with_a_clear_error_when_the_stream_says_the_key_is_bad(monkeypatch):
    _serve(monkeypatch, [{"error": "Api Key Is Not Valid"}])
    with pytest.raises(OSError, match="Api Key Is Not Valid") as e:
        list(ais.pull(CONFIG, assets=REGISTRY))
    assert KEY not in str(e.value)


def test_pull_ignores_a_message_that_is_not_json(monkeypatch):
    _serve(monkeypatch, ["not json", MESSAGES[0]])
    assert len(list(ais.pull(CONFIG, assets=REGISTRY))) == 1


def test_pull_refuses_to_start_without_a_registered_mmsi(monkeypatch):
    socket = _serve(monkeypatch, MESSAGES)
    with pytest.raises(ValueError, match="logbook assets add") as e:
        list(ais.pull(CONFIG, assets=[CAR]))
    assert "mmsi" in str(e.value) and socket.sent == []


def test_pull_names_the_extra_when_the_websocket_package_is_missing(monkeypatch):
    def missing(url: str, timeout: float) -> Any:
        raise ImportError("No module named 'websockets'")

    monkeypatch.setattr(ais, "_connect", missing)
    with pytest.raises(OSError, match=r"openlogbook\[ais\]"):
        list(ais.pull(CONFIG, assets=REGISTRY))


def test_watermark_is_the_report_time_and_group_is_the_subject():
    draft = ais.draft(MESSAGES[0], YACHT)
    assert ais.watermark(draft) == "2026-03-01T07:30:00Z"
    assert ais.group(draft) == "solvind"
    assert ais.GROUP_MARKS is True
    assert not hasattr(ais, "resume")  # the stream has no history to resume from


# -- the CLI ---------------------------------------------------------------------------------------


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    for name in ("LOGBOOK_AISSTREAM_LISTEN_S", "LOGBOOK_AISSTREAM_URL"):
        monkeypatch.delenv(name, raising=False)
    for asset in REGISTRY:
        assets.add(lb.root, asset)
    return lb


def _sync(*args: str) -> None:
    cli.main(["sync", "ais", *args])


def _state(lb: Logbook) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((lb.root / "state" / "ais.json").read_text(encoding="utf-8"))
    return data


def test_sync_appends_the_yachts_positions_and_keeps_a_watermark_per_asset(lb, monkeypatch, capsys):
    _serve(monkeypatch, MESSAGES)
    _sync()
    out = capsys.readouterr().out
    assert "ais: 4 new lines of 4 seen from the beginning" in out
    assert "solvind: 4 new of 4 seen" in out
    assert "skipped" in out and "not in assets.json" in out
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 4
    assert _state(lb) == {"since": "2026-03-01T07:32:00Z", "groups": {"solvind": "2026-03-01T07:32:00Z"}}
    line = next(lb.lines())
    assert line["tz"] == "Europe/Oslo" and line["payload"]["subject"] == "solvind"


def test_sync_re_run_appends_nothing_and_never_moves_a_watermark_backwards(lb, monkeypatch, capsys):
    _serve(monkeypatch, MESSAGES)
    _sync()
    _serve(monkeypatch, MESSAGES)
    _sync()  # heard again: only the report at the watermark passes the cutoff, and it is in the record
    out = capsys.readouterr().out.splitlines()
    assert any(
        "ais: 0 new lines of 1 seen since 2026-03-01T07:32:00Z (1 already in the record)" in s for s in out
    )
    _serve(monkeypatch, MESSAGES[:2])
    _sync("--since", "2026-03-01T00:00:00Z")  # an explicit --since is used as given: everything is seen
    out = capsys.readouterr().out.splitlines()
    assert any("ais: 0 new lines of 2 seen" in s and "(2 already in the record)" in s for s in out)
    assert _state(lb) == {"since": "2026-03-01T07:32:00Z", "groups": {"solvind": "2026-03-01T07:32:00Z"}}
    assert lb.meta["seq"] == 4


def test_a_saved_stream_added_first_leaves_nothing_for_sync_to_append(lb, monkeypatch, capsys):
    cli.main(["add", str(FIXTURE)])
    assert "added 4 lines from ais" in capsys.readouterr().out
    _serve(monkeypatch, MESSAGES)
    _sync()
    assert "ais: 0 new lines of 4 seen" in capsys.readouterr().out
    assert lb.meta["seq"] == 4


def test_sync_dry_run_writes_nothing(lb, monkeypatch, capsys):
    _serve(monkeypatch, MESSAGES)
    _sync("--dry-run")
    out = capsys.readouterr().out
    assert "ais: 4 lines from the beginning (dry run, nothing written)" in out
    assert "solvind: 4 seen" in out
    assert lb.meta["seq"] == 0 and not (lb.root / "state").exists()


def test_sync_refuses_to_run_without_the_key_on_one_line(lb, monkeypatch, capsys):
    monkeypatch.delenv("LOGBOOK_AISSTREAM_KEY")
    with pytest.raises(SystemExit) as e:
        _sync()
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert err.splitlines() == ["sync: ais: set LOGBOOK_AISSTREAM_KEY"]


def test_sync_with_no_registered_vessel_exits_with_the_command_to_register_one(lb, monkeypatch, capsys):
    assets.write(lb.root, [CAR])
    _serve(monkeypatch, MESSAGES)
    with pytest.raises(SystemExit) as e:
        _sync()
    assert e.value.code == 1
    assert "logbook assets add" in capsys.readouterr().err


def test_sync_bad_key_exits_1_and_never_prints_the_key(lb, monkeypatch, capsys):
    _serve(monkeypatch, [{"error": "Api Key Is Not Valid"}])
    with pytest.raises(SystemExit) as e:
        _sync()
    assert e.value.code == 1
    err = capsys.readouterr().err
    assert "Api Key Is Not Valid" in err and KEY not in err


def test_show_lists_the_yachts_track_as_its_own_run_named_by_the_subject(lb, monkeypatch, capsys):
    _serve(monkeypatch, MESSAGES)
    _sync()
    capsys.readouterr()
    cli.main(["show", "2026-03-01"])
    out = capsys.readouterr().out
    (row,) = (s for s in out.splitlines() if "location" in s)
    assert "4 points" in row and "solvind" in row and "ais" in row


def test_pull_turns_a_connection_closed_by_the_server_into_one_oserror(monkeypatch):
    from websockets.exceptions import ConnectionClosedError
    from websockets.frames import Close

    class Closing(FakeSocket):
        def recv(self, timeout: float | None = None) -> str:
            if not self.messages:
                raise ConnectionClosedError(Close(1011, "server going away"), None, None)
            return super().recv(timeout)

    socket = Closing([MESSAGES[0]])
    monkeypatch.setattr(ais, "_connect", lambda url, timeout: socket)
    with pytest.raises(OSError, match="closed the connection") as e:
        list(ais.pull(CONFIG, assets=REGISTRY))
    assert KEY not in str(e.value)
