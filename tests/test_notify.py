"""The notifier (`logbook.contrib.notify`): one Telegram message from the scheduled run, only when
something is wrong or on Sunday evening, counts and names only, never a line's text. The endpoint
is a local HTTP server that records what it is sent; the variables are set by the test and hold
sentinels; the Oslo persona's name is in the record and must never be in a payload."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from test_sync_all import Fake, _fakes

from logbook import cli
from logbook.contrib import backup, doctor, last_run, notify
from logbook.core.store import Logbook

OSLO = ZoneInfo("Europe/Oslo")
THURSDAY = datetime(2026, 10, 8, 17, 0, 12, tzinfo=UTC)  # 19:00 in Oslo
SUNDAY_EVENING = datetime(2026, 10, 11, 17, 0, 12, tzinfo=UTC)
SUNDAY_MORNING = datetime(2026, 10, 11, 5, 0, 12, tzinfo=UTC)
PERSONA = "Nordmann"  # the record names Ines and Kari Nordmann; a payload never does
TOKEN = "000000000:not-a-real-token"


class Endpoint:
    """A local server standing in for the Bot API: every request's path and JSON body, in order."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.answer: dict[str, Any] = {"ok": True, "result": {"message_id": 1}}
        requests = self.requests
        endpoint = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length))
                requests.append((self.path, body))
                raw = json.dumps(endpoint.answer).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *_args: Any) -> None:
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def endpoint() -> Any:
    server = Endpoint()
    yield server
    server.close()


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, endpoint: Endpoint) -> Logbook:
    """A record of the persona, the notifier configured and pointed at the local endpoint."""
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    (lb.root / "policy").mkdir(exist_ok=True)
    (lb.root / "policy" / "owner.json").write_text(
        json.dumps({"names": ["Ines Nordmann"], "emails": ["ines.nordmann@example.org"], "phones": []}),
        encoding="utf-8",
    )
    (lb.root / "places.json").write_text(
        json.dumps({"Home": {"lat": 59.9139, "lon": 10.7522, "radius_m": 120, "kind": "home"}}),
        encoding="utf-8",
    )
    lb.append(
        "2026-10-01T10:00:00Z",
        "manual",
        "note",
        2,
        {"schema": "note/v1", "text": "coffee with Kari Nordmann"},
    )
    monkeypatch.setenv(notify.TOKEN_ENV, TOKEN)
    monkeypatch.setenv(notify.CHAT_ENV, "123456")
    monkeypatch.setenv(notify.API_ENV, endpoint.url)
    monkeypatch.setattr(doctor, "EXTRAS", ())
    monkeypatch.setattr(doctor, "DISK_WARN_BYTES", 0)
    for name in ("LOGBOOK_ALPHA_KEY", "LOGBOOK_GAMMA_KEY"):
        monkeypatch.delenv(name, raising=False)
    return lb


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[datetime]:
    stamps = [THURSDAY]
    monkeypatch.setattr(last_run, "now", lambda: stamps[0])
    monkeypatch.setattr(backup, "now", lambda: datetime(2026, 10, 3, 3, 0, tzinfo=UTC))
    return stamps


def _clean_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    _fakes(monkeypatch, Fake("alpha", ("LOGBOOK_ALPHA_KEY",), drafts=2))
    monkeypatch.setenv("LOGBOOK_ALPHA_KEY", "k")


def _all_clean(lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sources that pull, a backup and a restore test that passed: nothing for doctor to warn about."""
    _clean_sources(monkeypatch)
    cli.main(["backup", str(tmp_path / "Backups")])
    cli.main(["backup", "--restore-test"])


def _scheduled(capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    try:
        cli.main(["sync", "--scheduled"])
    except SystemExit as e:
        status = int(e.code or 0)
    else:
        status = 0
    out = capsys.readouterr()
    return status, out.out, out.err


# -- when it speaks --------------------------------------------------------------------------------------


def test_a_failed_source_sends_one_message_naming_the_source_and_the_checks(
    lb: Logbook,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clock: list[datetime],
    endpoint: Endpoint,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _all_clean(lb, tmp_path, monkeypatch)
    _fakes(
        monkeypatch,
        Fake("alpha", ("LOGBOOK_ALPHA_KEY",), drafts=2),
        Fake("gamma", ("LOGBOOK_GAMMA_KEY",), fail=OSError("the service is down")),
    )
    monkeypatch.setenv("LOGBOOK_GAMMA_KEY", "k")
    capsys.readouterr()
    status, out, _err = _scheduled(capsys)
    assert status == 1
    assert len(endpoint.requests) == 1, "one message, not one per problem"
    path, body = endpoint.requests[0]
    assert path == f"/bot{TOKEN}/sendMessage"
    assert body["chat_id"] == "123456"
    lines = body["text"].splitlines()
    assert lines[0] == "logbook 2026-10-08 19:00: something is wrong"
    assert lines[1] == "sync: 2 sources: 1 ok, 1 failed (gamma), 0 skipped"
    assert lines[2].startswith("doctor: ") and "warn: last-run" in lines[2], (
        "the doctor saw this run's failure"
    )
    assert len(lines) == 3, "not Sunday: no week block"
    assert PERSONA not in body["text"] and "coffee" not in body["text"]
    assert "notify: telegram: sent (something is wrong)" in out
    assert TOKEN not in out


def test_a_doctor_warning_sends_a_message_with_the_check_name_only(
    lb: Logbook,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clock: list[datetime],
    endpoint: Endpoint,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _all_clean(lb, tmp_path, monkeypatch)
    (lb.root / "places.json").unlink()
    capsys.readouterr()
    status, _out, _err = _scheduled(capsys)
    assert status == 0
    [(_path, body)] = endpoint.requests
    lines = body["text"].splitlines()
    assert lines[1] == "sync: 1 sources: 1 ok, 0 failed, 0 skipped"
    assert lines[2].endswith("warn: places")
    assert "places.json" not in body["text"], "names of checks, never their detail"


def test_sunday_evening_sends_the_week_even_when_nothing_is_wrong(
    lb: Logbook,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clock: list[datetime],
    endpoint: Endpoint,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _all_clean(lb, tmp_path, monkeypatch)
    clock[0] = datetime(2026, 10, 7, 17, 0, tzinfo=UTC)  # Wednesday: the two lines land
    _scheduled(capsys)
    assert endpoint.requests == [], "nothing wrong on a Wednesday"
    clock[0] = SUNDAY_EVENING
    status, out, _err = _scheduled(capsys)
    assert status == 0
    [(_path, body)] = endpoint.requests
    lines = body["text"].splitlines()
    assert lines[0] == "logbook week to 2026-10-11: 2 runs, 2 clean"
    assert lines[1] == "lines: alpha 2; 2 in all"
    assert lines[2].startswith("doctor: ") and lines[2].endswith(" 0 warn, 0 fail")
    assert lines[3] == "restore test: passed 2026-10-03"
    assert PERSONA not in body["text"]
    assert "notify: telegram: sent (the week)" in out
    assert (
        json.loads((lb.root / "state" / "last-run.json").read_text(encoding="utf-8"))["weekly_sent"]
        == "2026-10-11"
    )
    clock[0] = datetime(2026, 10, 11, 20, 0, tzinfo=UTC)  # run again the same evening
    _scheduled(capsys)
    assert len(endpoint.requests) == 1, "the week goes out once"


def test_sunday_evening_with_something_wrong_is_one_message_with_both_blocks(
    lb: Logbook,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clock: list[datetime],
    endpoint: Endpoint,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _all_clean(lb, tmp_path, monkeypatch)
    (lb.root / "places.json").unlink()
    clock[0] = SUNDAY_EVENING
    _scheduled(capsys)
    [(_path, body)] = endpoint.requests
    blocks = body["text"].split("\n\n")
    assert len(blocks) == 2
    assert blocks[0].startswith("logbook 2026-10-11 19:00: something is wrong")
    assert blocks[1].startswith("logbook week to 2026-10-11: 1 runs, 0 clean")


# -- when it is silent -----------------------------------------------------------------------------------


def test_nothing_is_sent_when_nothing_is_wrong_and_it_is_not_sunday_evening(
    lb: Logbook,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clock: list[datetime],
    endpoint: Endpoint,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _all_clean(lb, tmp_path, monkeypatch)
    for when in (THURSDAY, SUNDAY_MORNING):
        clock[0] = when
        status, out, err = _scheduled(capsys)
        assert status == 0
        assert "notify" not in out and "notify" not in err
    assert endpoint.requests == []


def test_without_the_variables_nothing_is_sent_and_nothing_is_said(
    lb: Logbook,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clock: list[datetime],
    endpoint: Endpoint,
    capsys: pytest.CaptureFixture[str],
    no_network: list[str],
) -> None:
    for name in notify.ENV:
        monkeypatch.delenv(name)
    _fakes(monkeypatch, Fake("gamma", ("LOGBOOK_GAMMA_KEY",), fail=OSError("down")))
    monkeypatch.setenv("LOGBOOK_GAMMA_KEY", "k")
    status, out, err = _scheduled(capsys)
    assert status == 1
    assert "notify" not in out and "notify" not in err and "telegram" not in (out + err).lower()
    assert endpoint.requests == [] and no_network == []


def test_one_variable_without_the_other_names_the_missing_one_and_sends_nothing(
    lb: Logbook,
    monkeypatch: pytest.MonkeyPatch,
    clock: list[datetime],
    endpoint: Endpoint,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(notify.CHAT_ENV)
    _fakes(monkeypatch, Fake("gamma", ("LOGBOOK_GAMMA_KEY",), fail=OSError("down")))
    monkeypatch.setenv("LOGBOOK_GAMMA_KEY", "k")
    _status, _out, err = _scheduled(capsys)
    assert "notify: telegram: set LOGBOOK_NOTIFY_TELEGRAM_CHAT too" in err
    assert TOKEN not in err
    assert endpoint.requests == []


def test_sync_all_by_hand_sends_nothing(
    lb: Logbook,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: Endpoint,
    no_network: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _fakes(monkeypatch, Fake("gamma", ("LOGBOOK_GAMMA_KEY",), fail=OSError("down")))
    monkeypatch.setenv("LOGBOOK_GAMMA_KEY", "k")
    with pytest.raises(SystemExit):
        cli.main(["sync", "--all"])
    assert endpoint.requests == [] and no_network == []


# -- delivery --------------------------------------------------------------------------------------------


def test_an_endpoint_that_refuses_is_one_line_on_stderr_and_the_run_still_ends_normally(
    lb: Logbook,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clock: list[datetime],
    endpoint: Endpoint,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _all_clean(lb, tmp_path, monkeypatch)
    (lb.root / "places.json").unlink()
    endpoint.answer = {"ok": False, "description": "chat not found"}
    capsys.readouterr()
    status, _out, err = _scheduled(capsys)
    assert status == 0
    assert "notify: telegram: the API refused the message: chat not found" in err
    assert TOKEN not in err
    assert (lb.root / "state" / "last-run.json").exists(), "the outcome is written before the message goes"


def test_an_endpoint_that_cannot_be_reached_is_one_line_on_stderr(
    lb: Logbook,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clock: list[datetime],
    endpoint: Endpoint,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _all_clean(lb, tmp_path, monkeypatch)
    (lb.root / "places.json").unlink()
    endpoint.close()
    capsys.readouterr()
    status, _out, err = _scheduled(capsys)
    assert status == 0
    assert "notify: telegram:" in err and TOKEN not in err


# -- the message, as text --------------------------------------------------------------------------------


def _run(
    *sources: last_run.Source, warned: tuple[str, ...] = (), failed: tuple[str, ...] = ()
) -> last_run.Run:
    first = next((f"{s.name}  {s.result}" for s in sources if s.failed), None)
    return last_run.Run(THURSDAY, sources, last_run.Doctor(10, warned, failed), first)


def test_the_alert_block_is_counts_source_names_and_check_names(tmp_path: Path) -> None:
    run = _run(
        last_run.Source("immich", "ok", 12),
        last_run.Source("gcal", "failed (status 1)", 0),
        last_run.Source("ais", "skipped (LOGBOOK_AISSTREAM_KEY not set)", 0),
        warned=("sync:gcal",),
        failed=("record",),
    )
    text = notify.compose(run, (), THURSDAY.astimezone(OSLO), None, weekly=False)
    assert text == (
        "logbook 2026-10-08 19:00: something is wrong\n"
        "sync: 3 sources: 1 ok, 1 failed (gcal), 1 skipped\n"
        "doctor: 10 pass, 1 warn, 1 fail; fail: record; warn: sync:gcal"
    )


def test_the_week_block_sums_the_lines_and_names_the_restore_test() -> None:
    run = _run(last_run.Source("immich", "ok", 4))
    week = (
        last_run.WeekEntry(THURSDAY, True, {"immich": 1200, "gcal": 31}),
        last_run.WeekEntry(THURSDAY, False, {"immich": 4}),
    )
    test = backup.RestoreTest(datetime(2026, 10, 4, 5, 0, tzinfo=UTC), "passed", None, 2, "a" * 64, None)
    text = notify.compose(run, week, SUNDAY_EVENING.astimezone(OSLO), test, weekly=True)
    assert text == (
        "logbook week to 2026-10-11: 2 runs, 1 clean\n"
        "lines: immich 1,204, gcal 31; 1,235 in all\n"
        "doctor: 10 pass, 0 warn, 0 fail\n"
        "restore test: passed 2026-10-04"
    )
    assert notify.compose(run, week, SUNDAY_EVENING.astimezone(OSLO), None, weekly=False) is None
    assert "restore test: none yet" in str(
        notify.compose(run, (), SUNDAY_EVENING.astimezone(OSLO), None, weekly=True)
    )
