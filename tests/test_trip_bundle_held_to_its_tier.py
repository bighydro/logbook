"""A trip bundle's `trip.json` holds only what the request's tiers select (the review of 26 October,
S5): a flight whose line is above `--tier` is not among its flights, and its stays, moves and nights
rest on lines that cross. The Oslo persona's Zürich trip (`persona.py`, 15 to 18 June 2026) with two
more flight lines dated inside it, XY 563 at tier 2 and XY 564 at tier 3, which no tier-1 or tier-1,2
bundle may carry. Nobody here exists; carrier XY is no airline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from persona import flight, persona_record, utc

from logbook import cli
from logbook.core.store import Logbook

TRIP = "trip:2026-06-15:2026-06-17"
DAY = "2026-06-16"


def _flight(number: str, tier: int, from_: str, to: str, dep: str, arr: str) -> dict[str, Any]:
    line = flight(DAY, number, from_, to, utc(DAY, dep), utc(DAY, arr))
    line["tier"] = tier
    return line


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = persona_record(tmp_path, monkeypatch)
    lb.append_many(
        [_flight("563", 2, "ZRH", "GVA", "08:00", "09:00"), _flight("564", 3, "GVA", "ZRH", "17:00", "18:00")]
    )
    path = lb.root / "policy" / "crossing.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data["ines"] = {"max_tier": 2}
    path.write_text(json.dumps(data), encoding="utf-8")
    return Logbook(lb.root)


def _share(lb: Logbook, folder: Path, tiers: str, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    cli.main(["export", "trip-bundle", TRIP, "--to", "ines", "--tier", tiers, "--out", str(folder)])
    capsys.readouterr()
    return json.loads((folder / "trip.json").read_text(encoding="utf-8"))


def test_read_whole_the_trip_has_all_four_flights(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(["show", "trip", TRIP, "--json"])
    trip = json.loads(capsys.readouterr().out)
    assert [f["number"] for f in trip["flights"]] == ["561", "563", "564", "562"]


@pytest.mark.parametrize(("tiers", "numbers"), [("1", ["561", "562"]), ("1,2", ["561", "563", "562"])])
def test_trip_json_carries_only_the_flights_whose_lines_cross(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str], tiers: str, numbers: list[str]
) -> None:
    share = _share(lb, tmp_path / "bundle", tiers, capsys)
    assert [f["number"] for f in share["flights"]] == numbers
    allowed = {int(t) for t in tiers.split(",")}
    tier_of = {str(line["id"]): int(line["tier"]) for line in lb.lines()}
    for f in share["flights"]:
        assert all(tier_of[i] in allowed for i in f["lines"]), f
    for row in [*share["stays"], *share["moves"]]:
        assert {tier_of[row["lines"]["first"]], tier_of[row["lines"]["last"]]} <= allowed, row
    assert '"number": "564"' not in json.dumps(share)
