"""An asset is printed by its registered name, once, in every reader's text (the stranger test of 26
October): `aboard nordlys` beside `aboard Nordlys`, and `Nordlys (nordlys) (yacht)`, read as two boats.
The JSON keeps the id where SPEC §6.1 compares it; only the words change. The demo record: Nordlys, a
yacht that does not exist, id `nordlys`."""

from __future__ import annotations

import contextlib
import io
import re

import pytest

from logbook import cli

READERS = {
    "rollup places": ("rollup", "places"),
    "rollup places --with": ("rollup", "places", "--with"),
    "rollup nights": ("rollup", "nights"),
    "rollup people": ("rollup", "people"),
    "show year": ("show", "year", "2026"),
    "show person": ("show", "person", "Anders Vik"),
    "show place": ("show", "place", "Marina"),
    "show asset": ("show", "asset", "nordlys"),
}


def _run(*args: str) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cli.main(list(args))
    return out.getvalue()


@pytest.fixture(scope="module")
def texts(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    root = tmp_path_factory.mktemp("demo") / "Demo"
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LOGBOOK_HOME", str(root))
        _run("demo", "--days", "30", "--seed", "1", "--out", str(root))
        return {name: _run(*args) for name, args in READERS.items()}


@pytest.mark.parametrize("name", list(READERS))
def test_the_asset_is_named_by_its_name_once(name: str, texts: dict[str, str]) -> None:
    text = texts[name]
    assert re.search(r"aboard nordlys\b", text) is None, text
    assert "Nordlys (nordlys)" not in text and "(nordlys) (yacht)" not in text, text


def test_the_readers_that_name_it_say_nordlys(texts: dict[str, str]) -> None:
    assert "6 nights aboard Nordlys" in texts["rollup nights"]
    assert "Nordlys (yacht)" in texts["rollup places"] and "Nordlys (yacht)" in texts["show year"]
    assert "aboard Nordlys" in texts["show person"] and "aboard Nordlys" in texts["show place"]
