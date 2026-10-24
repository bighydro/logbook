"""A server that is up and says nothing is found and started again (phase 6 of the Library's rebuild).
`service.probe` tells three things apart on 127.0.0.1: a logbook server answering, a listener that takes
the connection and says nothing for 5 s (stuck, or paused by the system), and nothing at all.
`serve --status` says "not answering" for the second, with the command that restarts it; the
scheduled run restarts it (`service.keep_answering`); and the server's own `Watchdog` writes every
thread's stack to the log and leaves, for its service manager to start it again. Synthetic: an empty
record in the Oslo zone, ports on loopback."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from logbook import cli
from logbook.contrib import serve, service
from logbook.contrib.schedule import Command
from logbook.core.store import Logbook

LOOPBACK = "127.0.0.1"
ANSWER_WITHIN_S = 5.0  # a server a test expects to answer does so in this, or the test fails, never hangs
PROBE = service.probe  # the real one, before any test patches it


def answers(port: int, within_s: float = ANSWER_WITHIN_S) -> str:
    """`service.probe` of a server the test expects to answer, waited on until it answers or
    `within_s` passes: a server that stops answering fails the test, saying so."""
    seen = PROBE(port, within_s)
    if seen == service.NOT_ANSWERING:
        pytest.fail(f"the server on {LOOPBACK}:{port} said nothing in {within_s:g} s", pytrace=False)
    return seen


@pytest.fixture
def mute() -> Iterator[int]:
    """A port that takes connections and never answers: a listener nobody accepts from, as a server
    whose every thread is stuck, or a process the system paused, looks from outside."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((LOOPBACK, 0))
    sock.listen(16)
    try:
        yield int(sock.getsockname()[1])
    finally:
        sock.close()


@pytest.fixture
def free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((LOOPBACK, 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


@pytest.fixture
def answering(tmp_path: Path) -> Iterator[int]:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    server = serve.make_server(lb, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()


def test_probe_tells_answering_stuck_and_nothing_apart(answering: int, mute: int, free_port: int) -> None:
    assert service.probe(answering) == service.ANSWERING
    began = time.monotonic()
    assert service.probe(mute, timeout=0.5) == service.NOT_ANSWERING
    assert time.monotonic() - began < 3
    assert service.probe(free_port, timeout=0.5) == service.NOTHING
    assert service.PROBE_TIMEOUT_S == 5.0, "not answering after five seconds"


def test_a_server_that_stops_answering_fails_the_test_instead_of_hanging_it(mute: int) -> None:
    began = time.monotonic()
    with pytest.raises(pytest.fail.Exception, match=r"said nothing in 0\.2 s"):
        answers(mute, within_s=0.2)
    assert time.monotonic() - began < 3


def test_status_says_not_answering_and_how_it_is_restarted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    item = service.Installed(
        "launchd agent", tmp_path / "org.logbook.serve.plist", 8765, "~/Library/Logs/x.log"
    )
    monkeypatch.setattr(service, "find", lambda *_a, **_k: [item])
    monkeypatch.setattr(service, "answering", lambda port: False)
    monkeypatch.setattr(service, "probe", lambda port, timeout=5.0: service.NOT_ANSWERING)
    with pytest.raises(SystemExit) as e:
        cli.main(["serve", "--status"])
    assert e.value.code == 1
    out = capsys.readouterr().out
    assert "not answering at http://127.0.0.1:8765/" in out and "says nothing in 5 s" in out
    assert "launchctl kickstart -k gui/" in out and "org.logbook.serve" in out


def test_the_restart_is_the_service_manager_s_own(tmp_path: Path) -> None:
    agent = service.Installed("launchd agent", tmp_path / "a.plist", 8765, "")
    unit = service.Installed("systemd user service", tmp_path / "u.service", 8765, "")
    daemon = service.Installed("launchd daemon", tmp_path / "d.plist", 8765, "")
    system_unit = service.Installed("systemd system service", tmp_path / "s.service", 8765, "")
    assert service.restart_command(agent, uid=501) == Command(
        ("launchctl", "kickstart", "-k", "gui/501/org.logbook.serve")
    )
    assert service.restart_command(unit) == Command(("systemctl", "--user", "restart", "logbook-serve"))
    assert service.restart_command(daemon) is None and service.restart_command(system_unit) is None
    assert service.restart_by_hand(daemon).text == "sudo launchctl kickstart -k system/org.logbook.serve"
    assert service.restart_by_hand(system_unit).text == "sudo systemctl restart logbook-serve"


def test_the_scheduled_run_restarts_a_stuck_service_and_names_a_system_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mute: int, answering: int
) -> None:
    stuck = service.Installed("systemd user service", tmp_path / "u.service", mute, "journalctl --user")
    fine = service.Installed("launchd agent", tmp_path / "a.plist", answering, "")
    daemon = service.Installed("launchd daemon", tmp_path / "d.plist", mute, "")
    monkeypatch.setattr(service, "find", lambda *_a, **_k: [stuck, fine, daemon])
    monkeypatch.setattr(service, "PROBE_TIMEOUT_S", 0.5)

    # `mute` is connected to by the kernel and never answered, so 0.5 s or any wait reads it as stuck;
    # the server that answers is waited on until it answers, up to `ANSWER_WITHIN_S`, and one that
    # stops answering fails the test instead of hanging it
    def probe(port: int, timeout: float = 0.5) -> str:
        return PROBE(port, timeout) if port == mute else answers(port)

    monkeypatch.setattr(service, "probe", probe)
    ran: list[tuple[str, ...]] = []
    said: list[str] = []
    restarted = service.keep_answering(
        "linux", tmp_path, None, said.append, run=lambda c: ran.append(c.args) or 0
    )
    assert restarted == [stuck]
    assert ran == [("systemctl", "--user", "restart", "logbook-serve")], "the answering one is left alone"
    assert said[0].startswith(f"serve: not answering at http://127.0.0.1:{mute}/") and "restarted" in said[0]
    assert "as an administrator: sudo launchctl kickstart -k system/org.logbook.serve" in said[1]


def test_the_watchdog_writes_the_stacks_and_leaves_when_the_server_says_nothing(
    mute: int, capsys: pytest.CaptureFixture[str]
) -> None:
    left = threading.Event()
    said: list[str] = []
    dog = serve.Watchdog(mute, stuck=left.set, every_s=0.05, silent_s=0.2, after=2, say=said.append).start()
    try:
        assert left.wait(10), "two silences in a row, and it leaves"
    finally:
        dog.stop()
    assert dog.misses == 2
    assert said and "no answer from itself in 0.2 s, 2 times running" in said[0]
    assert "logbook-watchdog" in capsys.readouterr().err, "every thread's stack, its own among them"


def test_the_watchdog_of_a_server_that_answers_never_leaves(answering: int) -> None:
    left = threading.Event()
    dog = serve.Watchdog(answering, stuck=left.set, every_s=0.05, silent_s=2.0, after=2).start()
    try:
        assert not left.wait(0.6)
        assert dog.misses == 0
    finally:
        dog.stop()


def test_the_watchdog_leaves_with_a_failure_its_service_manager_restarts() -> None:
    """KeepAlive with SuccessfulExit false (launchd) and Restart=on-failure (systemd) start again a
    process that exits non-zero: the watchdog's exit is one."""
    assert serve.STUCK_EXIT != 0
