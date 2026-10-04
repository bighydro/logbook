"""The CLI's output, pinned before the entry module was split into `logbook/commands/`.

`logbook/cli.py` once held every command; the commands now live one family per module under
`logbook/commands/` and `cli.py` is the entry point. A split must change nothing a user sees: the
fixtures under `tests/fixtures/demo/cli/` were written by the unsplit code on the demo record
(thirty days, seed 7) and every command here must print them byte for byte. The record's own
folder is masked as `<root>`, since `demo` prints where it wrote. A fixture that is missing is
written on the first run, as an adapter's expected output is, and checked in."""

from __future__ import annotations

import contextlib
import io
import re
from pathlib import Path

import pytest

from logbook import cli

FIXTURES = Path(__file__).parent / "fixtures" / "demo" / "cli"
DAYS, SEED = 30, 7
COMMANDS: dict[str, tuple[str, ...]] = {
    "show": ("show", "2026-06-08"),
    "show_raw": ("show", "2026-06-08", "--raw"),
    "day": ("day", "2026-06-08"),
    "day_json": ("day", "2026-06-08", "--json"),
    "digest": ("digest", "2026-06-08"),
    "days": ("days",),
    "trips": ("trips",),
    "trips_json": ("trips", "--json"),
    "trip": ("trip", "trip:2026-06-08:2026-06-10"),
    "trip_json": ("trip", "2026-06-16", "--json"),
    "year": ("year", "2026"),
    "people": ("people",),
    "person": ("person", "Ola Nordmann"),
    "show_person": ("show", "person", "Ola Nordmann"),
    "places_list": ("places", "list"),
    "keepers": ("keepers",),
    "promises": ("promises", "--all"),
    "tasks": ("tasks",),
    "ledger": ("ledger",),
    "questions_list": ("questions", "list"),
    "derive_stays": ("derive", "stays", "--since", "2026-06-01", "--until", "2026-06-07"),
    "derive_stays_json": ("derive", "stays", "--since", "2026-06-01", "--until", "2026-06-07", "--json"),
    "rollup_countries": ("rollup", "countries"),
    "rollup_flights": ("rollup", "flights"),
    "rollup_nights": ("rollup", "nights"),
    "rollup_places": ("rollup", "places"),
    "rollup_people": ("rollup", "people"),
    "rollup_health": ("rollup", "health"),
    "rollup_listen": ("rollup", "listen"),
    "rollup_money": ("rollup", "money"),
    "sources": ("sources",),
    "assets_list": ("assets", "list"),
    "verify": ("verify",),
}


def _run(*args: str) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cli.main(list(args))
    return out.getvalue()


def capture(root: Path) -> dict[str, str]:
    """`demo` into `root`, then every command of `COMMANDS` on it, by name; `str(root)` masked."""
    texts = {"demo": _run("demo", "--days", str(DAYS), "--seed", str(SEED), "--out", str(root))}
    for name, args in COMMANDS.items():
        texts[name] = _run(*args)
    return {name: _masked(text, root) for name, text in texts.items()}


def _masked(text: str, root: Path) -> str:
    """`str(root)` as `<root>`, and the separators of a path that continues it as `/`, so the
    fixture written on one platform holds on the others (Windows prints `<root>\\policy\\…`)."""
    masked = text.replace(str(root), "<root>")
    return re.sub(r"<root>[\\/][^\s'\"]*", lambda m: m.group(0).replace("\\", "/"), masked)


@pytest.fixture(scope="module")
def outputs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    root = tmp_path_factory.mktemp("demo") / "Demo"
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LOGBOOK_HOME", str(root))
        return capture(root)


@pytest.mark.parametrize("name", ["demo", *COMMANDS])
def test_prints_what_the_unsplit_cli_printed(name: str, outputs: dict[str, str]) -> None:
    expected_file = FIXTURES / f"{name}.txt"
    if not expected_file.exists():  # the first run writes the fixture; the next ones hold it to it
        expected_file.write_text(outputs[name], encoding="utf-8")
    expected = expected_file.read_text(encoding="utf-8")
    assert outputs[name].splitlines() == expected.splitlines()


def test_the_demo_output_names_the_record(outputs: dict[str, str]) -> None:
    assert "<root>" in outputs["demo"] and "nothing in it is real" in outputs["demo"]
