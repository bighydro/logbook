"""The old-to-new command table in docs/commands.md, generated from `logbook/commands/aliases.py`.

`ALIASES` there is the one list of the top-level command names the October 2026 audit folded away
and the words each became; this script writes it as a Markdown table between the two markers in
docs/commands.md, so the doc never drifts from the code.

    uv run python scripts/command_aliases.py            # rewrite the table in docs/commands.md
    uv run python scripts/command_aliases.py --check    # exit 1 when the table differs (the test runs this)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from logbook.commands.aliases import ALIASES  # noqa: E402

DOC = ROOT / "docs" / "commands.md"
START, END = "<!-- aliases:start -->", "<!-- aliases:end -->"


def table() -> str:
    """The Markdown table, one row per old name, in alphabetical order."""
    rows = [
        "| Was | Is now |",
        "|---|---|",
        *(f"| `logbook {old}` | `logbook {' '.join(new)}` |" for old, new in sorted(ALIASES.items())),
    ]
    return "\n".join(rows) + "\n"


def current() -> tuple[str, str, str]:
    """The doc as (before the table, the table, after the table)."""
    text = DOC.read_text(encoding="utf-8")
    start = text.index(START) + len(START)
    end = text.index(END)
    return text[: start + 1], text[start + 1 : end], text[end:]


def main(argv: list[str]) -> int:
    head, body, tail = current()
    if argv == ["--check"]:
        if body == table():
            return 0
        print(f"{DOC.relative_to(ROOT)}: the alias table differs from ALIASES; run {Path(__file__).name}")
        return 1
    if argv:
        print(__doc__)
        return 2
    DOC.write_text(head + table() + tail, encoding="utf-8")
    print(f"wrote {len(ALIASES)} rows to {DOC.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
