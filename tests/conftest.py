"""Every test runs against a temporary record. Two tiers of test are opt-in, by marker and variable:
`slow` (over about five seconds) runs with LOGBOOK_SLOW=1, which CI sets on push to main and nightly and
never on a pull request; `stress` (generated millions of lines, timing and memory assertions) runs with
LOGBOOK_STRESS=1 and never in CI. The suite runs in parallel (`pytest -n auto`, as CI does): a test owns
nothing but its tmp_path, and a module-scoped fixture is built once per worker (`--dist loadfile`)."""

from __future__ import annotations

import http.client
import importlib
import os
import socket
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _logbook_home_is_temporary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The shell's LOGBOOK_HOME names a real record, and so may ~/Logbook; a test must never open either.
    Every test gets its own folder for both: LOGBOOK_HOME (`Logbook.find` looks there first) and the home
    directory (its last fallback; `Path.home()` reads HOME here and USERPROFILE on Windows). A test that
    wants a record creates one in it. Never remove this fixture (CLAUDE.md)."""
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "logbook-home"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    # The shell may hold the password of a real backup; a test that needs one sets its own.
    monkeypatch.delenv("LOGBOOK_BACKUP_PASSWORD", raising=False)


# marker -> the variable that, set to 1, runs the tests it marks (pyproject.toml lists both markers)
OPT_IN = {"slow": "LOGBOOK_SLOW", "stress": "LOGBOOK_STRESS"}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for marker, variable in OPT_IN.items():
        if os.environ.get(variable) == "1":
            continue
        skip = pytest.mark.skip(reason=f"{marker}; set {variable}=1 to run")
        for item in items:
            if marker in item.keywords:
                item.add_marker(skip)


class NetworkAttempt(RuntimeError):
    """Raised by `no_network` where a test's code tried to open a connection."""


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every way out of the process refuses and is recorded: `socket.socket` (any socket, before it
    could connect, bind or send), `socket.create_connection`, `socket.getaddrinfo` (a name lookup is
    a packet), `urllib.request.urlopen`, `http.client.HTTPConnection.connect` and, when the package
    is installed, the request path of `httpx`, `requests` and `websockets`. Each call appends its
    name to the returned list and raises `NetworkAttempt`, which is not an OSError, so a reader that
    swallows connection errors still fails the test: assert the list is empty once the command has
    run, whatever the command printed. The guard holds for the test's duration only."""
    attempts: list[str] = []

    def refuse(where: str) -> Callable[..., Any]:
        def _refuse(*args: Any, **kwargs: Any) -> Any:
            attempts.append(where)
            raise NetworkAttempt(f"{where}: this command may not open a connection")

        return _refuse

    class Socket(socket.socket):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            attempts.append("socket.socket")
            raise NetworkAttempt("socket.socket: this command may not open a socket")

    monkeypatch.setattr(socket, "socket", Socket)
    monkeypatch.setattr(socket, "create_connection", refuse("socket.create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", refuse("socket.getaddrinfo"))
    monkeypatch.setattr(urllib.request, "urlopen", refuse("urllib.request.urlopen"))
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", refuse("urllib.request.OpenerDirector.open"))
    monkeypatch.setattr(http.client.HTTPConnection, "connect", refuse("http.client.HTTPConnection.connect"))
    for path in (  # the request path of the clients the adapters use, patched where the package imports
        "httpx.HTTPTransport.handle_request",
        "httpx.AsyncHTTPTransport.handle_async_request",
        "requests.Session.request",
        "requests.adapters.HTTPAdapter.send",
        "websockets.sync.client.connect",
        "websockets.asyncio.client.connect",
    ):
        _patch_if_present(monkeypatch, path, refuse(path))
    return attempts


def _patch_if_present(monkeypatch: pytest.MonkeyPatch, path: str, replacement: Any) -> None:
    """`package.module.Class.attribute` replaced when the package is installed; nothing otherwise."""
    parts = path.split(".")
    for n in range(len(parts) - 1, 0, -1):
        try:
            holder: Any = importlib.import_module(".".join(parts[:n]))
        except ImportError:
            continue
        for part in parts[n:-1]:
            holder = getattr(holder, part, None)
            if holder is None:
                return
        if hasattr(holder, parts[-1]):
            monkeypatch.setattr(holder, parts[-1], replacement)
        return
