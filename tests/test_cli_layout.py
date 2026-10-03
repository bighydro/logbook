"""The CLI's output, pinned before the entry module was split into `logbook/commands/`.

`logbook/cli.py` once held every command; the commands now live one family per module under
`logbook/commands/` and `cli.py` is the entry point and re-exports. A split must change nothing a
user sees: the fixtures under `tests/fixtures/demo/cli/` were written by the unsplit code on the
demo record (thirty days, seed 7) and every command here must print them byte for byte. The
record's own folder is masked as `<root>`, since `demo` prints where it wrote."""

from __future__ import annotations

import contextlib
import io
from pathlib import Path

import pytest

from logbook import cli

FIXTURES = Path(__file__).parent / "fixtures" / "demo" / "cli"
DAYS, SEED = 30, 7
COMMANDS: dict[str, tuple[str, ...]] = {
    "show": ("show", "2026-06-08"),
    "day": ("day", "2026-06-08"),
    "days": ("days",),
    "trips": ("trips",),
    "rollup_countries": ("rollup", "countries"),
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
    return {name: text.replace(str(root), "<root>") for name, text in texts.items()}


@pytest.fixture(scope="module")
def outputs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    root = tmp_path_factory.mktemp("demo") / "Demo"
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LOGBOOK_HOME", str(root))
        return capture(root)


@pytest.mark.parametrize("name", ["demo", *COMMANDS])
def test_prints_what_the_unsplit_cli_printed(name: str, outputs: dict[str, str]) -> None:
    expected = (FIXTURES / f"{name}.txt").read_text(encoding="utf-8")
    assert outputs[name].splitlines() == expected.splitlines()


def test_the_demo_output_names_the_record(outputs: dict[str, str]) -> None:
    assert "<root>" in outputs["demo"] and "nothing in it is real" in outputs["demo"]
