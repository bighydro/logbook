"""`slow` tests run only with LOGBOOK_SLOW=1 (never in CI)."""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("LOGBOOK_SLOW") == "1":
        return
    skip = pytest.mark.skip(reason="slow; set LOGBOOK_SLOW=1 to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)
