"""pre-commit hook: fail the commit when a staged diff adds a line that matches one of the owner's personal
identifiers. Stdlib only.

The identifiers are never in the repository. They live in the file `LOGBOOK_PII_PATTERNS` names, default
`~/.config/logbook/pii-patterns`: one case-insensitive regular expression per line, blank lines and `#`
comments ignored. Without the file (CI, a stranger's checkout) the hook prints one warning and passes.
On a match it prints `<file>:<line>` for every added line that matched, never the text and never the pattern,
and exits 1.

Usage: `check_pii.py [FILE ...]` — the files pre-commit hands over; none means the whole staged diff."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

DEFAULT = Path("~") / ".config" / "logbook" / "pii-patterns"


def patterns_file() -> Path:
    named = os.environ.get("LOGBOOK_PII_PATTERNS")
    return Path(named).expanduser() if named else DEFAULT.expanduser()


def load_patterns(path: Path) -> list[re.Pattern[str]]:
    out: list[re.Pattern[str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(re.compile(line, re.IGNORECASE))
    return out


def staged_diff(files: list[str]) -> str:
    cmd = ["git", "diff", "--cached", "--no-color", "--no-ext-diff", "-U0", "--", *files]
    r = subprocess.run(cmd, capture_output=True, check=True)
    return r.stdout.decode("utf-8", errors="replace")


def added_lines(diff: str) -> list[tuple[str, int, str]]:
    """(file, line number in the new file, text) for every `+` line of a unified diff."""
    out: list[tuple[str, int, str]] = []
    file = ""
    line = 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            name = raw[4:]
            file = "" if name == "/dev/null" else name.removeprefix("b/")
        elif raw.startswith("@@ "):
            m = re.match(r"@@ -\S+ \+(\d+)", raw)
            line = int(m.group(1)) if m else 0
        elif raw.startswith("+") and file:
            out.append((file, line, raw[1:]))
            line += 1
        elif raw.startswith(" "):
            line += 1
    return out


def main(argv: list[str]) -> int:
    path = patterns_file()
    if not path.is_file():
        print(f"check-pii: no patterns file at {path}; skipping (see CLAUDE.md)", file=sys.stderr)
        return 0
    patterns = load_patterns(path)
    hits = [
        (file, line)
        for file, line, text in added_lines(staged_diff(argv))
        if any(p.search(text) for p in patterns)
    ]
    for file, line in hits:
        print(f"{file}:{line}: added line matches a personal identifier pattern")
    if hits:
        print(f"check-pii: {len(hits)} added line(s) match {path}; unstage them or fix the pattern")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
