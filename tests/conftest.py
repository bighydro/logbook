"""Every test runs against a temporary record; `slow` tests run only with LOGBOOK_SLOW=1 (never in CI)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _logbook_home_is_temporary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The shell's LOGBOOK_HOME names a real record; a test must never open it. Every test gets its own
    folder instead (`Logbook.find` looks there first), and a test that wants a record creates one in it.
    Never remove this fixture (CLAUDE.md)."""
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "logbook-home"))


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("LOGBOOK_SLOW") == "1":
        return
    skip = pytest.mark.skip(reason="slow; set LOGBOOK_SLOW=1 to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)
