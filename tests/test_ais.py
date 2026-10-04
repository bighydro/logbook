"""The ais adapter (aisstream.io → location/v1 with `subject`, ADR 0018) in both its modes: a saved
stream of messages read by `logbook add`, and `logbook sync ais` listening to the websocket. No
network: the websocket is a fake fed from the fixture. Every identifier is synthetic: MMSI under
MID 999 (allocated to no country), the yacht `solvind`, which does not exist."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters, cli
from logbook.adapters import ais
from logbook.core import assets
from logbook.core.assets import Asset
from logbook.core.store import Logbook

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


class Clock:
    """A monotonic clock the fakes move by hand, so a test listens for an hour in no time."""

    def __init__(self) -> None:
        self.t = 1_000.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


class FakeSocket:
    """What `websockets.sync.client.connect` returns, fed from a list: records what was sent, serves
    each message once (moving `clock` by `step` seconds per message when it has one), then raises
    TimeoutError as a quiet socket does when the timeout passes (moving the clock by the timeout).
    `then` is raised in place of the timeout once the messages are served: a dropped connection, a
    Ctrl-C."""

    def __init__(
        self,
        messages: list[Any],
        clock: Clock | None = None,
        step: float = 0.0,
        then: BaseException | None = None,
    ):
        self.messages = list(messages)
        self.sent: list[str] = []
        self.closed = False
        self.timeouts: list[float | None] = []
        self.clock = clock
        self.step = step
        self.then = then

    def __enter__(self) -> FakeSocket:
        return self

    def __exit__(self, *a: object) -> None:
        self.closed = True

    def send(self, text: str) -> None:
        self.sent.append(text)

    def recv(self, timeout: float | None = None) -> str:
        self.timeouts.append(timeout)
        if not self.messages:
            if self.then is not None:
                raise self.then
            if self.clock is not None and timeout is not None:
                self.clock.t += timeout
            raise TimeoutError
        if self.clock is not None:
            self.clock.t += self.step
        message = self.messages.pop(0)
        return message if isinstance(message, str) else json.dumps(message)


def _serve(monkeypatch: pytest.MonkeyPatch, messages: list[Any], clock: Clock | None = None) -> FakeSocket:
    """One fake socket on a fake clock (a fresh one when none is given, so a quiet socket's timeout
    ends the window at once instead of after a real minute)."""
    clock = clock if clock is not None else Clock()
    socket = FakeSocket(messages, clock)
    _connect_each(monkeypatch, [socket], clock)
    return socket


def _connect_each(
    monkeypatch: pytest.MonkeyPatch, sockets: list[FakeSocket | Exception], clock: Clock | None = None
) -> list[str]:
    """`_connect` hands out `sockets` in turn (an exception in the list is raised by that attempt),
    on `clock` when given; returns the list that records each attempt's url."""
    attempts: list[str] = []
    queue = list(sockets)

    def connect(url: str, timeout: float) -> FakeSocket:
        attempts.append(url)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(ais, "_connect", connect)
    if clock is not None:
        monkeypatch.setattr(ais, "_now", clock.now)
        monkeypatch.setattr(ais, "_sleep", clock.sleep)
    return attempts


def _dropped() -> Exception:
    from websockets.exceptions import ConnectionClosedError
    from websockets.frames import Close

    return ConnectionClosedError(Close(1011, "server going away"), None, None)


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
    clock = Clock()
    _serve(monkeypatch, MESSAGES, clock)
    ticks: list[int] = []
    drafts = list(
        ais.pull(
            CONFIG, since="2026-03-01T07:31:00+00:00", assets=REGISTRY, progress=lambda n, _s: ticks.append(n)
        )
    )
    assert [d["at"] for d in drafts] == ["2026-03-01T07:31:30Z", "2026-03-01T07:32:00Z"]
    assert ticks == [len(MESSAGES)]  # one line at the 60 s tick, which is the window's end


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


def test_pull_turns_a_connection_closed_at_the_very_end_of_the_window_into_nothing(monkeypatch):
    clock = Clock()
    socket = FakeSocket([MESSAGES[0]], clock, step=59.5, then=_dropped())
    attempts = _connect_each(monkeypatch, [socket], clock)
    notices: list[str] = []
    assert len(list(ais.pull(CONFIG, assets=REGISTRY, notice=notices.append))) == 1
    assert attempts == [ais.DEFAULT_URL] and socket.closed
    assert clock.sleeps == []  # 0.5 s left, the first wait is 1 s: not worth a reconnect
    assert notices == ["connection dropped (server going away); 0s left of the window, not reconnecting"]


# -- the listening window ------------------------------------------------------------------------


def test_pull_listens_for_listen_s_instead_of_the_configured_window(monkeypatch):
    clock = Clock()
    socket = _serve(monkeypatch, [], clock)
    assert list(ais.pull(CONFIG, assets=REGISTRY, listen_s=5)) == []
    assert clock.t == pytest.approx(1_005.0) and socket.timeouts == [5.0]


def test_pull_reports_progress_every_minute_even_when_the_socket_is_quiet(monkeypatch):
    clock = Clock()
    socket = _serve(monkeypatch, [], clock)
    ticks: list[tuple[int, float]] = []
    status: dict[str, Any] = {}
    list(
        ais.pull(
            CONFIG, assets=REGISTRY, listen_s=150, progress=lambda n, s: ticks.append((n, s)), status=status
        )
    )
    assert ticks == [(0, 60.0), (0, 120.0)]  # the window ends between ticks; the summary says the rest
    assert socket.timeouts == [60.0, 60.0, 30.0]  # never longer than the next tick, or the window
    assert status["messages"] == 0 and status["elapsed"] == pytest.approx(150.0)


def test_pull_counts_the_messages_heard_per_asset_in_status(monkeypatch):
    clock = Clock()
    _serve(monkeypatch, MESSAGES, clock)
    status: dict[str, Any] = {}
    list(ais.pull(CONFIG, assets=REGISTRY, status=status))
    assert status["messages"] == len(MESSAGES)
    assert status["heard"] == {"solvind": 7}  # every message of its MMSI, positions or not
    assert status["reconnects"] == 0 and status["interrupted"] is False


def test_seconds_until_is_the_next_time_the_clock_shows_hh_mm():
    oslo = ZoneInfo("Europe/Oslo")
    morning = datetime(2026, 3, 1, 7, 30, tzinfo=oslo)
    assert ais.seconds_until("18:30", oslo, morning) == 11 * 3600
    assert ais.seconds_until("07:30", oslo, morning) == 24 * 3600  # now is not later: tomorrow
    assert ais.seconds_until("07:29", oslo, morning) == 24 * 3600 - 60
    evening = datetime(2026, 3, 1, 19, 0, tzinfo=oslo)
    assert ais.seconds_until("18:30", oslo, evening) == 23 * 3600 + 1800
    # the night the clocks go forward: 01:00 to 04:00 is two hours of listening, not three
    before_dst = datetime(2026, 3, 29, 1, 0, tzinfo=oslo)
    assert ais.seconds_until("04:00", oslo, before_dst) == 2 * 3600


@pytest.mark.parametrize("bad", ["7:30", "24:00", "18:60", "1830", "18:30:00", "", "noon"])
def test_seconds_until_refuses_anything_but_hh_mm(bad):
    with pytest.raises(ValueError, match="HH:MM"):
        ais.seconds_until(
            bad, ZoneInfo("Europe/Oslo"), datetime(2026, 3, 1, 7, 30, tzinfo=ZoneInfo("Europe/Oslo"))
        )


# -- Ctrl-C and a dropped socket -----------------------------------------------------------------


def test_pull_yields_what_it_heard_when_interrupted(monkeypatch):
    clock = Clock()
    socket = FakeSocket(MESSAGES[:2], clock, step=1.0, then=KeyboardInterrupt())
    _connect_each(monkeypatch, [socket], clock)
    notices: list[str] = []
    status: dict[str, Any] = {}
    drafts = list(ais.pull(CONFIG, assets=REGISTRY, listen_s=3600, notice=notices.append, status=status))
    assert [d["at"] for d in drafts] == ["2026-03-01T07:30:00Z", "2026-03-01T07:30:30Z"]
    assert status["interrupted"] is True and socket.closed
    assert notices == ["stopped by Ctrl-C after 2s; writing what was heard"]


def test_pull_reconnects_with_backoff_when_the_socket_drops(monkeypatch):
    clock = Clock()
    first = FakeSocket(MESSAGES[:2], clock, step=1.0, then=_dropped())
    second = FakeSocket([], clock, then=_dropped())  # drops before it delivers anything
    third = FakeSocket([], clock, then=_dropped())
    fourth = FakeSocket([MESSAGES[7]], clock, step=1.0)  # then quiet until the window ends
    attempts = _connect_each(monkeypatch, [first, second, third, fourth], clock)
    notices: list[str] = []
    status: dict[str, Any] = {}
    drafts = list(ais.pull(CONFIG, assets=REGISTRY, listen_s=600, notice=notices.append, status=status))
    assert [d["at"] for d in drafts] == [
        "2026-03-01T07:30:00Z",
        "2026-03-01T07:30:30Z",
        "2026-03-01T07:32:00Z",
    ]
    assert attempts == [ais.DEFAULT_URL] * 4
    assert clock.sleeps == [1.0, 2.0, 4.0]  # doubling while nothing arrives
    assert status["reconnects"] == 3 and status["messages"] == 3
    assert all(s.closed for s in (first, second, third, fourth))
    assert all(json.loads(s.sent[0])["APIKey"] == KEY for s in (first, second, third, fourth))  # resubscribed
    assert notices == [
        "connection dropped (server going away); reconnecting in 1s",
        "connection dropped (server going away); reconnecting in 2s",
        "connection dropped (server going away); reconnecting in 4s",
    ]
    assert KEY not in " ".join(notices)


def test_a_socket_that_drops_while_subscribing_is_reconnected_too(monkeypatch):
    class DropsOnSend(FakeSocket):
        def send(self, text: str) -> None:
            super().send(text)
            raise _dropped()

    clock = Clock()
    first = DropsOnSend([], clock)
    second = FakeSocket([MESSAGES[0]], clock, step=1.0)
    _connect_each(monkeypatch, [first, second], clock)
    status: dict[str, Any] = {}
    assert len(list(ais.pull(CONFIG, assets=REGISTRY, listen_s=120, status=status))) == 1
    assert first.closed and status["reconnects"] == 1 and clock.sleeps == [1.0]


def test_backoff_starts_again_at_one_second_once_a_connection_delivers(monkeypatch):
    clock = Clock()
    sockets = [
        FakeSocket([MESSAGES[0]], clock, step=1.0, then=_dropped()),
        FakeSocket([], clock, then=_dropped()),
        FakeSocket([MESSAGES[1]], clock, step=1.0, then=_dropped()),
        FakeSocket([], clock, then=_dropped()),
        FakeSocket([MESSAGES[5]], clock, step=1.0),
    ]
    _connect_each(monkeypatch, sockets, clock)  # type: ignore[arg-type]
    assert len(list(ais.pull(CONFIG, assets=REGISTRY, listen_s=600))) == 3
    assert clock.sleeps == [1.0, 2.0, 1.0, 2.0]


def test_backoff_is_capped_and_a_failed_reconnect_counts_as_a_drop(monkeypatch):
    clock = Clock()
    first = FakeSocket([MESSAGES[0]], clock, step=1.0, then=_dropped())
    sockets: list[FakeSocket | Exception] = [first]
    sockets += [OSError("[Errno 101] Network is unreachable")] * 8
    last = FakeSocket([MESSAGES[1]], clock, step=1.0)
    sockets.append(last)
    attempts = _connect_each(monkeypatch, sockets, clock)
    notices: list[str] = []
    status: dict[str, Any] = {}
    assert (
        len(list(ais.pull(CONFIG, assets=REGISTRY, listen_s=3600, notice=notices.append, status=status))) == 2
    )
    assert len(attempts) == 10 and status["reconnects"] == 9
    assert clock.sleeps == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0, 60.0]
    assert notices[1] == "connection failed ([Errno 101] Network is unreachable); reconnecting in 2s"


def test_pull_stops_reconnecting_when_the_window_ends_while_waiting(monkeypatch):
    clock = Clock()
    first = FakeSocket([MESSAGES[0]], clock, step=4.5, then=_dropped())
    attempts = _connect_each(monkeypatch, [first], clock)
    status: dict[str, Any] = {}
    assert len(list(ais.pull(CONFIG, assets=REGISTRY, listen_s=5, status=status))) == 1
    assert attempts == [ais.DEFAULT_URL] and clock.sleeps == [] and status["reconnects"] == 0


def test_pull_fails_at_once_when_the_first_connection_cannot_be_made(monkeypatch):
    clock = Clock()
    _connect_each(monkeypatch, [OSError("[Errno 101] Network is unreachable")], clock)
    with pytest.raises(OSError, match=r"could not connect to aisstream: .*unreachable"):
        list(ais.pull(CONFIG, assets=REGISTRY))
    assert clock.sleeps == []


def test_a_refused_subscription_is_never_retried(monkeypatch):
    clock = Clock()
    attempts = _connect_each(monkeypatch, [FakeSocket([{"error": "Api Key Is Not Valid"}], clock)], clock)
    with pytest.raises(OSError, match="refused"):
        list(ais.pull(CONFIG, assets=REGISTRY, listen_s=3600))
    assert attempts == [ais.DEFAULT_URL] and clock.sleeps == []


# -- the CLI: --listen, --until, Ctrl-C ---------------------------------------------------------------


def test_sync_listen_sets_the_window_in_seconds(lb, monkeypatch, capsys):
    clock = Clock()
    socket = _serve(monkeypatch, MESSAGES, clock)
    monkeypatch.setenv("LOGBOOK_AISSTREAM_LISTEN_S", "7")  # the flag wins over the variable
    _sync("--listen", "300")
    out, err = capsys.readouterr()
    assert "ais: 4 new lines of 4 seen" in out
    assert "listening for 5 min" in err
    assert all(t is not None and 0 < t <= 60 for t in socket.timeouts)
    assert clock.t == pytest.approx(1_300.0)


def test_sync_progress_line_every_minute_counts_messages_per_asset(lb, monkeypatch, capsys):
    clock = Clock()
    _serve(monkeypatch, MESSAGES, clock)
    _sync("--listen", "130")
    err = capsys.readouterr().err
    assert "  8 reports in 60s (solvind 7)" in err
    assert "  8 reports in 120s (solvind 7)" in err


def test_sync_until_listens_to_the_next_time_the_clock_shows_hh_mm(lb, monkeypatch, capsys):
    clock = Clock()
    socket = _serve(monkeypatch, [], clock)
    seen: dict[str, Any] = {}

    def seconds_until(clock_text: str, zone: Any, now: datetime | None = None) -> float:
        seen.update(clock=clock_text, zone=zone, now=now)
        return 7_200.0

    monkeypatch.setattr(ais, "seconds_until", seconds_until)
    _sync("--until", "18:30")
    out, err = capsys.readouterr()
    assert seen["clock"] == "18:30" and str(seen["zone"]) == "Europe/Oslo" and seen["now"] is not None
    assert "listening until 18:30 Europe/Oslo (2 h)" in err
    assert "ais: 0 new lines of 0 seen" in out
    assert clock.t == pytest.approx(1_000.0 + 7_200.0) and socket.closed


@pytest.mark.parametrize(
    ("args", "complaint"),
    [
        (["--listen", "0"], "--listen must be a number of seconds above 0"),
        (["--listen", "-5"], "--listen must be a number of seconds above 0"),
        (["--listen", "soon"], "--listen must be a number of seconds above 0"),
        (["--listen", "nan"], "--listen must be a number of seconds above 0"),
        (["--until", "7:30"], "--until must be a local time as HH:MM"),
        (["--until", "25:00"], "--until must be a local time as HH:MM"),
        (["--listen", "60", "--until", "18:30"], "give --listen or --until, not both"),
    ],
)
def test_sync_refuses_a_bad_window_on_one_line(lb, monkeypatch, capsys, args, complaint):
    socket = _serve(monkeypatch, MESSAGES)
    with pytest.raises(SystemExit) as e:
        _sync(*args)
    assert e.value.code == 2
    assert complaint in capsys.readouterr().err
    assert not socket.sent  # refused before any connection


def test_sync_listen_is_refused_for_a_source_that_does_not_listen(lb, monkeypatch, capsys):
    monkeypatch.setenv("LOGBOOK_DAWARICH_URL", "http://dawarich.test")
    monkeypatch.setenv("LOGBOOK_DAWARICH_KEY", "synthetic")
    with pytest.raises(SystemExit) as e:
        cli.main(["sync", "dawarich", "--listen", "60"])
    assert e.value.code == 2
    assert "sync: --listen and --until are for a source that listens to a stream (ais), not dawarich" in (
        capsys.readouterr().err
    )


def test_sync_ctrl_c_writes_what_was_heard_and_exits_130(lb, monkeypatch, capsys):
    clock = Clock()
    socket = FakeSocket(MESSAGES[:2], clock, step=1.0, then=KeyboardInterrupt())
    _connect_each(monkeypatch, [socket], clock)
    with pytest.raises(SystemExit) as e:
        _sync("--listen", "3600")
    assert e.value.code == 130
    out, err = capsys.readouterr()
    assert "  stopped by Ctrl-C after 2s; writing what was heard" in err
    assert "ais: 2 new lines of 2 seen from the beginning" in out
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 2
    assert _state(lb)["since"] == "2026-03-01T07:30:30Z"


def test_sync_says_when_it_reconnected(lb, monkeypatch, capsys):
    clock = Clock()
    first = FakeSocket(MESSAGES[:2], clock, step=1.0, then=_dropped())
    second = FakeSocket(MESSAGES[2:], clock, step=1.0)
    _connect_each(monkeypatch, [first, second], clock)
    _sync("--listen", "120")
    out, err = capsys.readouterr()
    assert "  connection dropped (server going away); reconnecting in 1s" in err
    assert "ais: 4 new lines of 4 seen" in out
    assert "  reconnected once" in out
    assert KEY not in out + err
