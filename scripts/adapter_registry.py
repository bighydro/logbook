"""`BUILT_IN` in logbook/adapters/__init__.py, generated from pyproject.toml.

The adapter registry is pyproject.toml's `logbook.adapters` entry-point table, in the order
`logbook.adapters.find` tries the adapters on a file. The installed metadata sorts that table by name
(hatchling writes it sorted), so the package cannot read the order back from it and keeps a copy: the
`BUILT_IN` tuple, which this script writes and never a hand edits.

    uv run python scripts/adapter_registry.py            # rewrite the tuple from pyproject.toml
    uv run python scripts/adapter_registry.py --check    # exit 1 when the tuple differs (the test runs this)
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
MODULE = ROOT / "logbook" / "adapters" / "__init__.py"
GROUP = "logbook.adapters"
PREFIX = "logbook.adapters."
BLOCK = re.compile(r"BUILT_IN = \(.*?\n\)\n", re.S)


def table() -> dict[str, str]:
    with PYPROJECT.open("rb") as f:
        return tomllib.load(f)["project"]["entry-points"][GROUP]


def modules() -> tuple[str, ...]:
    """The built-in adapter modules, relative to the package, in the table's order."""
    out = []
    for name, value in table().items():
        if not value.startswith(PREFIX):
            raise SystemExit(f"{name} = {value!r}: a built-in adapter lives under {PREFIX}")
        out.append(value.removeprefix(PREFIX))
    return tuple(out)


def block(names: tuple[str, ...]) -> str:
    lines = [
        "BUILT_IN = (  # generated from pyproject.toml by scripts/adapter_registry.py; never edited by hand"
    ]
    lines += [f'    "{name}",' for name in names]
    lines.append(")\n")
    return "\n".join(lines)


def current() -> str:
    found = BLOCK.findall(MODULE.read_text(encoding="utf-8"))
    if len(found) != 1:
        raise SystemExit(f"{MODULE}: expected one BUILT_IN block, found {len(found)}")
    return found[0]


def main(argv: list[str]) -> int:
    wanted = block(modules())
    if argv == ["--check"]:
        if current() == wanted:
            return 0
        print(f'{MODULE}: BUILT_IN differs from pyproject.toml\'s [project.entry-points."{GROUP}"]')
        print(f"run: uv run python {Path(__file__).relative_to(ROOT)}")
        return 1
    if argv:
        raise SystemExit(__doc__)
    text = MODULE.read_text(encoding="utf-8")
    MODULE.write_bytes(text.replace(current(), wanted).encode("utf-8"))
    print(f"{MODULE.relative_to(ROOT)}: BUILT_IN is {len(modules())} modules, as pyproject.toml lists them")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
