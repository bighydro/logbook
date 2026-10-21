"""A place's class (RFC 0043 §12): `home`, `family`, `aboard` or `away`, the colour of a night on the
timeline. A reader-side key of `places.json`, `class`, that the spec does not know and never needs:
absent, it is `home` for a place of kind `home`, `aboard` for a night aboard an asset, else `away`.
`logbook setup places class NAME CLASS` writes it, saying what it will write and asking first."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest

from logbook import cli
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


def _run(
    *args: str, answer: str | None = None, monkeypatch: pytest.MonkeyPatch | None = None
) -> tuple[str, int]:
    out = io.StringIO()
    if answer is not None and monkeypatch is not None:
        monkeypatch.setattr("builtins.input", lambda prompt: (print(prompt, end=""), answer)[1])
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            cli.main(list(args))
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
    return out.getvalue(), code


def test_without_a_class_a_place_is_home_by_its_kind_aboard_on_an_asset_else_away(lb: Logbook) -> None:
    known = {p.name: p for p in places.read(lb.root)}
    explicit = places.classes(lb.root)
    assert explicit == {}
    assert places.class_of(known["Home"], None, explicit) == "home"
    assert places.class_of(known["Saltbu"], None, explicit) == "away"
    assert places.class_of(known["Marina"], None, explicit) == "away"
    assert places.class_of(known["Marina"], "nordlys", explicit) == "aboard"  # a night aboard the asset
    assert places.class_of(None, "nordlys", explicit) == "aboard"
    assert places.class_of(None, None, explicit) == "away"
    assert places.class_of(None, None, explicit, home=True) == "home"  # a night within reach of home


def test_a_class_in_the_file_wins_and_the_spec_s_keys_read_as_before(lb: Logbook) -> None:
    document = json.loads(places.path_of(lb.root).read_text(encoding="utf-8"))
    document["Saltbu"]["class"] = "family"
    places.path_of(lb.root).write_text(json.dumps(document), encoding="utf-8")
    known = {p.name: p for p in places.read(lb.root)}
    assert known["Saltbu"] == places.Place("Saltbu", 59.66, 10.63, 150.0, "other")  # the Place is unchanged
    explicit = places.classes(lb.root)
    assert explicit == {"Saltbu": "family"}
    assert places.class_of(known["Saltbu"], None, explicit) == "family"


def test_a_class_that_is_not_one_is_refused_naming_the_file(lb: Logbook) -> None:
    document = json.loads(places.path_of(lb.root).read_text(encoding="utf-8"))
    document["Saltbu"]["class"] = "cottage"
    places.path_of(lb.root).write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(places.PlaceError, match=r"places\.json.*Saltbu.*class"):
        places.classes(lb.root)


def test_setup_places_class_says_what_it_writes_asks_and_keeps_every_other_key(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    before = places.path_of(lb.root).read_text(encoding="utf-8")
    said, code = _run("setup", "places", "class", "saltbu", "family", answer="n", monkeypatch=monkeypatch)
    assert code == 0
    assert "Saltbu: class family (now away, by its kind)" in said
    assert "nothing written" in said
    assert places.path_of(lb.root).read_text(encoding="utf-8") == before  # asked, said no: nothing written
    said, code = _run("setup", "places", "class", "saltbu", "family", answer="y", monkeypatch=monkeypatch)
    assert code == 0 and "wrote class family for Saltbu" in said
    document = json.loads(places.path_of(lb.root).read_text(encoding="utf-8"))
    assert document["Saltbu"] == {**PLACES["Saltbu"], "class": "family"}  # its unknown key kept
    assert document["Home"] == PLACES["Home"] and list(document) == list(PLACES)
    said, code = _run("setup", "places", "class", "Saltbu", "family", "--yes")
    assert code == 0 and "already" in said


def test_setup_places_class_with_yes_writes_and_refuses_what_is_not_a_place_or_a_class(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    said, code = _run("setup", "places", "class", "Home", "away", "--yes")
    assert code == 0 and places.classes(lb.root) == {"Home": "away"}
    said, code = _run("setup", "places", "class", "Drøbak", "away", "--yes")
    assert code == 2 and "Drøbak" in said and "not a place" in said
    said, code = _run("setup", "places", "class", "Home", "cottage", "--yes")
    assert code == 2  # argparse refuses a class outside the four
    assert places.classes(lb.root) == {"Home": "away"}
