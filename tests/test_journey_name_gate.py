"""A journey's name through the reader's gate: the name is a `note/v1` line at tier 2, so a Journeys
list, one journey or the Journeys page read through a gate without tier 2 shows no name. On the
Oslo persona's fortnight (`persona.py`); nobody here exists."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from persona import persona_record

from logbook.contrib import journeys, serve
from logbook.core.store import Logbook

ZURICH_TRIP = "trip:2026-06-15:2026-06-17"
NAME = "Zürich with Kari"


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = persona_record(tmp_path, monkeypatch)
    journeys.name(lb, "2026-06-15", NAME, today="2026-06-21")
    return lb


def _name(lb: Logbook, tiers: Sequence[int] | None) -> str | None:
    found = {j.id: j for j in journeys.shelf(lb, "2026", tiers=tiers).journeys}
    named = found[ZURICH_TRIP].name
    return named.text if named else None


def test_a_journey_s_name_crosses_only_a_gate_that_holds_its_tier(lb: Logbook) -> None:
    assert _name(lb, None) == NAME
    assert _name(lb, (1, 2)) == NAME
    assert _name(lb, (1,)) is None, "a tier 2 name never shows through a gate of tier 1"


def test_one_journey_through_a_gate_of_tier_1_has_no_name(lb: Logbook) -> None:
    assert journeys.read(lb, ZURICH_TRIP)["journey"]["name"] is not None
    assert journeys.read(lb, ZURICH_TRIP, tiers=(1,))["journey"]["name"] is None


def test_the_journeys_page_through_a_gate_of_tier_1_does_not_show_the_name(lb: Logbook) -> None:
    whole = serve.Site(lb).respond("/journeys", "year=2026").body.decode("utf-8")
    assert NAME in whole
    gated = serve.Site(lb, tiers=(1,)).respond("/journeys", "year=2026")
    assert gated.status == 200
    assert NAME not in gated.body.decode("utf-8")
