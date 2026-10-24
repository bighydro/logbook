"""A place's class (RFC 0043 §12): `home`, `family`, `aboard` or `away`, the colour of a night on the
timeline, read from what `places.json` already says and from no key of its own: `home` for a place of
kind `home` (or a night within reach of one), `family` for a place tagged `family`, `aboard` for a night
aboard an asset, else `away`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from logbook.core import places
from logbook.core.store import Logbook

PLACES = {
    "Home": {"lat": 59.9139, "lon": 10.7522, "radius_m": 120, "kind": "home", "tags": ["oslo"]},
    "Saltbu": {"lat": 59.6600, "lon": 10.6300, "radius_m": 150, "kind": "other", "note": "kept"},
    "Marina": {"lat": 59.9000, "lon": 10.7200, "radius_m": 150, "kind": "asset-berth"},
}


@pytest.fixture
def lb(tmp_path: Path) -> Logbook:
    found = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    places.path_of(found.root).write_text(json.dumps(PLACES, indent=2) + "\n", encoding="utf-8")
    return found


def _known(lb: Logbook, **changed: dict[str, object]) -> dict[str, places.Place]:
    document = json.loads(places.path_of(lb.root).read_text(encoding="utf-8"))
    for name, keys in changed.items():
        document[name].update(keys)
    places.path_of(lb.root).write_text(json.dumps(document), encoding="utf-8")
    return {p.name: p for p in places.read(lb.root)}


def test_without_a_family_tag_a_place_is_home_by_its_kind_aboard_on_an_asset_else_away(lb: Logbook) -> None:
    known = {p.name: p for p in places.read(lb.root)}
    assert places.class_of(known["Home"], None) == "home"
    assert places.class_of(known["Saltbu"], None) == "away"
    assert places.class_of(known["Marina"], None) == "away"
    assert places.class_of(known["Marina"], "nordlys") == "aboard"  # a night aboard the asset
    assert places.class_of(None, "nordlys") == "aboard"
    assert places.class_of(None, None) == "away"
    assert places.class_of(None, None, home=True) == "home"  # a night within reach of home


def test_a_family_tag_makes_a_place_the_family_s_case_aside(lb: Logbook) -> None:
    known = _known(lb, Saltbu={"tags": ["cottage", " Family "]})
    assert known["Saltbu"].tags == ("cottage", " Family ")  # the tags read as they are written
    assert places.class_of(known["Saltbu"], None) == "family"
    assert places.class_of(known["Saltbu"], "nordlys") == "aboard"  # a night aboard is aboard, wherever
    assert places.class_of(known["Saltbu"], None, home=True) == "home"  # within reach of home is home


def test_home_by_its_kind_stays_home_with_a_family_tag(lb: Logbook) -> None:
    known = _known(lb, Home={"tags": ["family"]})  # the places module's own example
    assert places.class_of(known["Home"], None) == "home"


def test_a_class_key_in_places_json_is_not_read(lb: Logbook) -> None:
    """The class is derived, never written: a `class` key some hand put in the file changes nothing."""
    known = _known(lb, Saltbu={"class": "family"}, Home={"class": "away"})
    assert known["Saltbu"] == places.Place("Saltbu", 59.66, 10.63, 150.0, "other")  # the Place is unchanged
    assert places.class_of(known["Saltbu"], None) == "away"
    assert places.class_of(known["Home"], None) == "home"
