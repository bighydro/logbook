"""The readers that count days with a person agree, or say in words what they count (the stranger
test of 26 October, on the demo record): Ola Nordmann, who does not exist, had 3 days in `rollup
people`, 4 on `show person`, 2 on `show asset` and `show place Cabin`, and `show person` said `last
2026-06-15` above stays on the 16th, 18th and 20th.

There are two counts, both SPEC's (§3.2.8): a person's **days together** (`rollup people`, now `show
person` too) are the days of the confirmed evidence; a person's days **at a place or aboard an asset**
(`rollup places`, `show place`, `show asset`) are the days of the evidence that put them there, a face on
the morning after a confirmed evening included. `show asset` reads the runs aboard as `rollup places`
does. No text prints a count beside a name."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

import beside_a_name
import pytest

from logbook import cli

OLA = "Ola Nordmann"


def _run(*args: str) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cli.main(list(args))
    return out.getvalue()


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("demo") / "Demo"
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LOGBOOK_HOME", str(root))
        _run("demo", "--days", "30", "--seed", "1", "--out", str(root))
    return root


@pytest.fixture
def run(demo: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("LOGBOOK_HOME", str(demo))
    return _run


def _ola(people: list[dict[str, Any]]) -> dict[str, Any]:
    [found] = [p for p in people if p["name"] == OLA]
    return found


def test_show_person_counts_the_days_rollup_people_counts(run: Any) -> None:
    rollup = json.loads(run("rollup", "people", "--json"))
    [year] = rollup["years"]
    person = json.loads(run("show", "person", OLA, "--json"))
    assert person["days_together"] == {"2026": _ola(year["people"])["days"]} == {"2026": 3}
    assert person["last_contact"] == _ola(year["people"])["last_contact"] == "2026-06-15"


def test_show_person_says_its_last_contact_is_confirmed_and_its_stays_may_be_proposed(run: Any) -> None:
    text = run("show", "person", OLA)
    assert "last confirmed 2026-06-15" in text, text
    assert "shared stays, confirmed or proposed" in text and "(proposed)" in text
    assert "2026  3 days together, by the confirmed evidence" in text


def test_the_place_and_the_asset_pages_count_what_rollup_places_counts(run: Any) -> None:
    rollup = json.loads(run("rollup", "places", "--json"))
    [year] = rollup["years"]
    by_place = {e["place"]: e for e in year["places"]}
    [aboard] = year["aboard"]
    cabin = json.loads(run("show", "place", "Cabin", "--json"))
    assert _ola(cabin["people"])["days"] == _ola(by_place["Cabin"]["people"])["days"]
    asset = json.loads(run("show", "asset", "nordlys", "--json"))
    assert _ola(asset["people"])["days"] == _ola(aboard["people"])["days"]
    assert (asset["stays_aboard"], asset["hours_aboard"]) == (aboard["stays"], aboard["hours"])


@pytest.mark.parametrize(
    "args",
    [("rollup", "people"), ("show", "asset", "nordlys"), ("show", "place", "Cabin"), ("show", "person", OLA)],
)
def test_no_count_beside_a_name(run: Any, args: tuple[str, ...]) -> None:
    """The strong guard (`beside_a_name`): no number, a date or a clock among them, beside any person's
    name, the person page's own head included; a word stands between (the desk, 28 October)."""
    assert beside_a_name.rows(run(*args)) == []
