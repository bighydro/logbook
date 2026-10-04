"""`logbook repair health-units`: the migration for a record whose `apple-health` lines were written
with resting heart rate 60 times and HRV 1000 times too large (RFC 0014, "Units as the store keeps
them"). Every wrong line is retracted (RFC 0003) and re-emitted corrected, `raw_id` suffixed `:u2`;
nothing is rewritten. Synthetic Oslo persona; nobody in it exists."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.core.store import Logbook

WRONG: list[dict[str, Any]] = [  # what the adapter wrote before the fix: the store's 56 bpm became 3360
    {
        "at": "2026-03-02T05:00:00Z",
        "end": None,
        "tz": "Europe/Oslo",
        "source": "apple-health",
        "kind": "health",
        "tier": 3,
        "payload": {
            "schema": "health-sample/v1",
            "raw_id": "resting_hr:15",
            "type": "resting_hr",
            "value": 3360,
            "unit": "bpm",
            "device": "Watch7,1",
            "source_name": "Apple Watch",
            "extra": {"original": {"quantity": 0.933, "unit": "count/s"}},
        },
    },
    {
        "at": "2026-03-02T07:30:00Z",
        "end": None,
        "tz": "Europe/Oslo",
        "source": "apple-health",
        "kind": "health",
        "tier": 3,
        "payload": {
            "schema": "health-sample/v1",
            "raw_id": "hrv:16",
            "type": "hrv",
            "value": 45000,
            "unit": "ms",
            "device": "Watch7,1",
        },
    },
    {
        "at": "2026-03-03T05:00:00Z",
        "end": None,
        "tz": "Europe/Oslo",
        "source": "apple-health",
        "kind": "health",
        "tier": 3,
        "payload": {
            "schema": "health-sample/v1",
            "raw_id": "resting_hr:27",
            "type": "resting_hr",
            "value": 3600,
            "unit": "bpm",
            "device": "Watch7,1",
        },
    },
]
RIGHT: list[dict[str, Any]] = [  # lines the repair must leave alone
    {
        "at": "2026-03-02T07:00:05Z",
        "end": None,
        "tz": "Europe/Oslo",
        "source": "apple-health",
        "kind": "health",
        "tier": 3,
        "payload": {
            "schema": "health-sample/v1",
            "raw_id": "heart_rate:11",
            "type": "heart_rate",
            "value": 72,
            "unit": "bpm",
            "device": "Watch7,1",
        },
    },
    {
        "at": "2026-03-02T07:00:00Z",
        "end": "2026-03-02T07:15:00Z",
        "tz": "Europe/Oslo",
        "source": "apple-health",
        "kind": "health",
        "tier": 3,
        "payload": {
            "schema": "health-sample/v1",
            "raw_id": "steps:2026-03-02T07:00:00Z:Watch7,1",
            "type": "steps",
            "value": 250,
            "unit": "count",
            "device": "Watch7,1",
            "extra": {"samples": 3},
        },
    },
    {  # another source's resting heart rate is not apple-health's and is never touched
        "at": "2026-03-02T06:00:00Z",
        "end": None,
        "tz": "Europe/Oslo",
        "source": "withings",
        "kind": "health",
        "tier": 3,
        "payload": {
            "schema": "health-sample/v1",
            "raw_id": "resting_hr:p1:9",
            "type": "resting_hr",
            "value": 58,
            "unit": "bpm",
        },
    },
]


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    assert lb.append_many([*WRONG, *RIGHT]) == 6
    return lb


def _repair(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(["repair", "health-units", *args])
    return capsys.readouterr().out


def _standing(lb: Logbook) -> dict[str, dict[str, Any]]:
    """The health lines a reader sees, by raw_id: retracted ones out."""
    with lb.index() as idx:
        hidden = {r["payload"]["supersedes"] for r in idx.retractions()}
        return {line["payload"]["raw_id"]: line for line in idx.of_kind("health") if line["id"] not in hidden}


def test_dry_run_counts_and_writes_nothing(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    head = lb.meta["head"]
    out = _repair(capsys, "--dry-run")
    assert "2 resting_hr" in out and "1 hrv" in out and "dry run" in out
    assert lb.meta["head"] == head and lb.meta["seq"] == 6


def test_repair_retracts_each_wrong_line_and_re_emits_it_corrected(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    before = {line["payload"]["raw_id"]: line for line in lb.lines()}
    out = _repair(capsys)
    assert "2 resting_hr" in out and "1 hrv" in out and "6 lines" in out
    assert lb.meta["seq"] == 12, "three corrected lines and three retractions"
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 12
    standing = _standing(lb)
    assert set(standing) == {
        "resting_hr:15:u2",
        "hrv:16:u2",
        "resting_hr:27:u2",
        "heart_rate:11",
        "steps:2026-03-02T07:00:00Z:Watch7,1",
        "resting_hr:p1:9",
    }
    fixed = standing["resting_hr:15:u2"]
    original = before["resting_hr:15"]
    assert fixed["payload"]["value"] == 56 and fixed["payload"]["unit"] == "bpm"
    assert fixed["payload"]["supersedes"] == original["id"]
    assert fixed["payload"]["extra"] == original["payload"]["extra"], "the store's original stays"
    for key in ("at", "end", "tz", "source", "kind", "tier"):
        assert fixed[key] == original[key]
    assert {k: v for k, v in fixed["payload"].items() if k not in ("raw_id", "value", "supersedes")} == {
        k: v for k, v in original["payload"].items() if k not in ("raw_id", "value")
    }
    hrv = standing["hrv:16:u2"]["payload"]
    assert hrv["value"] == 45 and hrv["unit"] == "ms", "HRV is reported in ms (RFC 0014)"
    assert standing["resting_hr:27:u2"]["payload"]["value"] == 60
    with lb.index() as idx:
        retractions = idx.retractions()
    assert len(retractions) == 3
    by_target = {r["payload"]["supersedes"]: r for r in retractions}
    retraction = by_target[original["id"]]
    assert retraction["payload"]["seq"] == original["seq"] and retraction["payload"]["reason"]
    assert retraction["source"] == "logbook" and retraction["tier"] == 2
    assert all(r["seq"] > int(by_target[t]["payload"]["seq"]) for t, r in by_target.items())


def test_repair_is_idempotent(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    _repair(capsys)
    head = lb.meta["head"]
    out = _repair(capsys)
    assert "nothing to repair" in out
    assert lb.meta["head"] == head and lb.meta["seq"] == 12


def test_stats_health_reads_the_corrected_resting_rate(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["stats", "--health", "--json"])
    before = json.loads(capsys.readouterr().out)["days"]
    assert [d["resting_hr"] for d in before] == [1709, 3600], "apple-health's 3360 averaged with withings' 58"
    _repair(capsys)
    cli.main(["stats", "--health", "--json"])
    after = json.loads(capsys.readouterr().out)["days"]
    assert [d["resting_hr"] for d in after] == [57, 60]


def test_repair_on_a_record_with_nothing_wrong(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(RIGHT)
    assert "nothing to repair" in _repair(capsys)
    assert "nothing to repair" in _repair(capsys, "--dry-run")
    assert lb.meta["seq"] == 3
