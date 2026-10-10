"""`policy/crossing.json` entries with an `until` date (ADR 0022): a ceiling the owner lends to a
cloud model or service for a while. The entry holds through its `until` day; from the next day it
counts as `max_tier` 0, so nothing crosses to that destination until the owner writes a new date or
removes the line. The record and the destinations here are synthetic."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from logbook.contrib import mcp_server
from logbook.core import crossing, policy
from logbook.core.store import Logbook

TODAY = date(2026, 10, 9)


@pytest.fixture(autouse=True)
def _today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(policy, "today", lambda: TODAY)


@pytest.fixture
def lb(tmp_path: Path) -> Logbook:
    return Logbook.init(tmp_path / "Logbook", "Europe/Oslo")


def _policy(lb: Logbook, data: dict[str, object]) -> Path:
    path = policy.policy_path(lb.root)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_an_entry_with_a_future_until_keeps_its_ceiling(lb: Logbook) -> None:
    _policy(lb, {"cloud-model": {"max_tier": 2, "until": "2026-12-31"}})
    assert policy.ceiling(lb.root, "cloud-model") == 2


def test_an_entry_holds_through_its_until_day(lb: Logbook) -> None:
    _policy(lb, {"cloud-model": {"max_tier": 2, "until": "2026-10-09"}})
    assert policy.ceiling(lb.root, "cloud-model") == 2


def test_an_expired_entry_counts_as_tier_0(lb: Logbook) -> None:
    _policy(lb, {"cloud-model": {"max_tier": 2, "until": "2026-10-08"}})
    assert policy.ceiling(lb.root, "cloud-model") == 0
    assert policy.expired_on(lb.root, "cloud-model") == date(2026, 10, 8)


def test_a_live_entry_has_no_expiry(lb: Logbook) -> None:
    _policy(lb, {"hermes": {"max_tier": 2}, "cloud-model": {"max_tier": 1, "until": "2027-01-01"}})
    assert policy.expired_on(lb.root, "hermes") is None
    assert policy.expired_on(lb.root, "cloud-model") is None


def test_the_mcp_vault_and_site_ceilings_expire_too(lb: Logbook) -> None:
    _policy(
        lb,
        {
            "mcp": {"max_tier": 2, "until": "2026-01-01"},
            "vault": {"max_tier": 2, "until": "2026-01-01"},
            "site": {"max_tier": 2, "until": "2026-01-01"},
        },
    )
    assert policy.mcp_ceiling(lb.root) == 0
    assert policy.vault_ceiling(lb.root) == 0
    assert policy.site_ceiling(lb.root) == 0
    assert mcp_server.ceiling(lb.root) == 0


def test_an_until_that_is_not_a_date_is_refused_naming_the_file(lb: Logbook) -> None:
    path = _policy(lb, {"cloud-model": {"max_tier": 2, "until": "next spring"}})
    with pytest.raises(policy.PolicyError, match=r"until.*YYYY-MM-DD") as e:
        policy.ceiling(lb.root, "cloud-model")
    assert str(path) in str(e.value)
    with pytest.raises(policy.PolicyError):
        policy.ceilings(lb.root)


def test_ceilings_lists_every_destination_with_its_state(lb: Logbook) -> None:
    _policy(
        lb,
        {
            "hermes": {"max_tier": 2},
            "cloud-model": {"max_tier": 2, "until": "2026-10-01"},
            "mcp": {"max_tier": 1, "until": "2026-12-31"},
        },
    )
    found = policy.ceilings(lb.root)
    assert [(c.destination, c.max_tier, c.until, c.expired) for c in found] == [
        ("hermes", 2, None, False),
        ("cloud-model", 0, date(2026, 10, 1), True),
        ("mcp", 1, date(2026, 12, 31), False),
    ]
    assert found[1].written == 2  # what the file says, beside what counts


def test_a_crossing_to_an_expired_destination_is_refused_naming_the_date(lb: Logbook, tmp_path: Path) -> None:
    _policy(lb, {"cloud-model": {"max_tier": 2, "until": "2026-09-30"}})
    with pytest.raises(crossing.CrossingError) as e:
        crossing.request(lb, "cloud-model", "2026-06-01T00:00:00Z", "2026-06-02T00:00:00Z", (1,))
    message = str(e.value)
    assert "expired on 2026-09-30" in message and "max_tier 0" in message
    assert str(policy.policy_path(lb.root)) in message
