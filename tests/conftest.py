"""Every test runs against a temporary record. Two tiers of test are opt-in, by marker and variable:
`slow` (over about five seconds) runs with LOGBOOK_SLOW=1, which CI sets on push to main and nightly and
never on a pull request; `stress` (generated millions of lines, timing and memory assertions) runs with
LOGBOOK_STRESS=1 and never in CI. The suite runs in parallel (`pytest -n auto`, as CI does): a test owns
nothing but its tmp_path, and a module-scoped fixture is built once per worker (`--dist loadfile`)."""

from __future__ import annotations

import os
from pathlib import Path

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
