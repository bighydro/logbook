"""A vault's day page is made of the lines that cross (the review of 26 October, S4): its Sources row
counts only the lines whose tier is in `--tier`, and a day whose every line is held back has no page.
A flight is on a day, trip or year page only when its line crosses. The Oslo persona's fortnight
(`persona.py`) and the same fortnight with tier-3 health samples on Wednesday 10 June and on
Wednesday 24 June, a day with no other line. Nobody here exists; carrier XY is no airline."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from persona import flight, persona_record, utc

from logbook import cli
from logbook.core.store import Logbook

WEDNESDAY, LATER = "2026-06-10", "2026-06-24"
ZURICH_DAY = "2026-06-16"  # inside the trip to Zürich
HEALTH = "apple-health"


def _health(day: str, clock: str) -> dict[str, Any]:
    at = f"{day}T{clock}:00Z"
    return {
        "at": at,
        "end": None,
        "source": HEALTH,
        "kind": "health",
        "tier": 3,
        "payload": {
            "schema": "health-sample/v1",
            "raw_id": f"resting_hr:{at}:watch",
            "type": "resting_hr",
            "value": 52,
            "unit": "count/min",
            "device": "watch",
        },
    }


@pytest.fixture
def records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Logbook, Logbook]:
    """The fortnight, and a copy of it with the health samples; tier 2 may go to a vault."""
    plain = persona_record(tmp_path / "plain", monkeypatch)
    path = plain.root / "policy" / "crossing.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data["vault"] = {"max_tier": 2}
    path.write_text(json.dumps(data), encoding="utf-8")
    root = tmp_path / "health" / "lb"
    shutil.copytree(plain.root, root)
    health = Logbook(root)
    health.append_many([_health(WEDNESDAY, "06:00"), _health(WEDNESDAY, "21:00"), _health(LATER, "10:00")])
    return Logbook(plain.root), Logbook(root)


def _vault(lb: Logbook, folder: Path, tiers: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    cli.main(["export", "vault", str(folder), "--tier", tiers, "--until", LATER])
    return folder


@pytest.mark.parametrize("tiers", ["1", "1,2"])
def test_a_day_page_counts_only_the_lines_that_cross_and_a_day_of_none_has_no_page(
    records: tuple[Logbook, Logbook], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tiers: str
) -> None:
    plain, health = records
    without = _vault(plain, tmp_path / "without", tiers, monkeypatch)
    with_health = _vault(health, tmp_path / "with", tiers, monkeypatch)
    page = (with_health / "days" / "2026" / f"{WEDNESDAY}.md").read_text(encoding="utf-8")
    assert HEALTH not in page, "a tier-3 source is not a source of a vault's day"
    assert page == (without / "days" / "2026" / f"{WEDNESDAY}.md").read_text(encoding="utf-8")
    assert not (with_health / "days" / "2026" / f"{LATER}.md").exists(), "only a tier-3 line is on it"
    days = sorted(p.name for p in (with_health / "days" / "2026").glob("*.md"))
    assert days == sorted(p.name for p in (without / "days" / "2026").glob("*.md"))
    assert LATER not in (with_health / "Logbook.md").read_text(encoding="utf-8").split("---\n", 2)[2]


def _flight(number: str, tier: int, from_: str, to: str, dep: str, arr: str) -> dict[str, Any]:
    line = flight(ZURICH_DAY, number, from_, to, utc(ZURICH_DAY, dep), utc(ZURICH_DAY, arr))
    line["tier"] = tier
    return line


@pytest.mark.parametrize(("tiers", "shown", "held"), [("1", [], ["563", "564"]), ("1,2", ["563"], ["564"])])
def test_a_vault_shows_only_the_flights_whose_lines_cross(
    records: tuple[Logbook, Logbook],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tiers: str,
    shown: list[str],
    held: list[str],
) -> None:
    """XY 563, a tier-2 line, and XY 564, a tier-3 one, inside the Zürich trip: on no day, trip or year
    page of a vault below their tier."""
    plain, _health = records
    plain.append_many(
        [_flight("563", 2, "ZRH", "GVA", "08:00", "09:00"), _flight("564", 3, "GVA", "ZRH", "17:00", "18:00")]
    )
    folder = _vault(Logbook(plain.root), tmp_path / "flights", tiers, monkeypatch)
    whole = "\n".join(p.read_text(encoding="utf-8") for p in sorted(folder.rglob("*.md")))
    assert "XY 561" in whole, "the tier-1 flight out is there"
    for number in shown:
        assert f"XY {number}" in whole, number
    for number in held:
        assert f"XY {number}" not in whole, number
