"""Fail when a folder of pages carries an identifier outside the project's synthetic allowlist. Stdlib only.

The allowlist is CONTRIBUTING.md's *Synthetic data*: the only identifiers a fixture, a doc or a published
page may carry are the UK fictional phone block `07700 900xxx` (national or `+44 7700 900xxx`), the Oslo
persona's `+47 9000 000x` block, email addresses at `example.org`, and the unassigned MMSI `999000001`.
Everything else that is shaped like an identifier — an email at any other domain, a phone number in any
other range, a nine-digit MMSI in an assigned range, a URL of any kind (a page fetches nothing and links
nowhere outside itself) — is the allowlist's complement, and one of them in a page fails the check.

On top of that, as `check_pii.py` does for a staged diff, every line is grepped against the owner's own
identifiers when the file `LOGBOOK_PII_PATTERNS` names (default `~/.config/logbook/pii-patterns`) exists;
without it the check says so once and goes on, so CI and strangers are unaffected.

The output is the scrub rule's: `<file>:<line>: <what>` for every hit and a count, never the text and
never the pattern. Exit 1 on any hit, 2 when the folder is not one.

Usage: `check_synthetic.py FOLDER` — the folder `logbook export site` wrote, before it is published."""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path

DEFAULT_PATTERNS = Path("~") / ".config" / "logbook" / "pii-patterns"
TEXT_SUFFIXES = {".html", ".htm", ".md", ".txt", ".json", ".jsonl", ".css", ".svg", ".xml", ".csv", ".yml"}

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
ALLOWED_DOMAINS = frozenset({"example.org"})
# What a page is full of that is not a phone number, blanked before the phone pattern runs: an ISO
# date with or without its time, a clock, a decimal (a coordinate, a kilometre), a grouped count.
NOT_PHONES = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?Z?)?|\d{1,2}:\d{2}(?::\d{2})?"
    r"|-?\d+\.\d+|\d{1,3}(?:,\d{3})+"
)
# A phone number: an optional country code, then eight or more digits in groups of two to five,
# separated by spaces, dashes or dots; never inside a longer run of digits.
PHONE = re.compile(
    r"(?<![\w.:/-])(?:\+\d{1,3}[ .-]?)?(?:\(\d{1,5}\)[ .-]?|\d{2,5}[ .-])\d{2,5}(?:[ .-]?\d{2,5}){1,2}"
    r"(?![\w.:/-])"
)
ALLOWED_PHONES = (
    re.compile(r"^(?:\+44[ .-]?7700|07700)[ .-]?900[ .-]?\d{3}$"),  # the UK fictional block 07700 900xxx
    re.compile(r"^\+47[ .-]?9000[ .-]?000[ .-]?\d$"),  # the Oslo persona's block, as the RFCs spell it
)
MMSI = re.compile(r"(?<![\w.:/-])[2-7]\d{8}(?![\w.:/-])")  # nine digits in an assigned maritime range
ALLOWED_MMSI = frozenset({"999000001"})  # never matched by MMSI above; here for the record
URL = re.compile(r"(?:https?:|ftp:|mailto:|tel:)[^\s\"'<>]*|(?<![\w.])www\.[A-Za-z0-9-]+\.[A-Za-z]", re.I)


def patterns_file() -> Path:
    named = os.environ.get("LOGBOOK_PII_PATTERNS")
    return Path(named).expanduser() if named else DEFAULT_PATTERNS.expanduser()


def load_patterns(path: Path) -> list[re.Pattern[str]]:
    out: list[re.Pattern[str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(re.compile(line, re.IGNORECASE))
    return out


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def findings(text: str, own: list[re.Pattern[str]]) -> Iterator[str]:
    """What one line carries that is outside the allowlist, named by kind and never by text."""
    for m in EMAIL.finditer(text):
        if m.group(0).rsplit("@", 1)[1].lower() not in ALLOWED_DOMAINS:
            yield "an email address at a domain other than example.org"
    for m in PHONE.finditer(NOT_PHONES.sub(" ", text)):
        found = m.group(0)
        if len(_digits(found)) < 8:
            continue
        if not any(p.match(found) for p in ALLOWED_PHONES):
            yield "a phone number outside the reserved fictional ranges"
    for m in MMSI.finditer(text):
        if m.group(0) not in ALLOWED_MMSI:
            yield "a nine-digit number in an assigned MMSI range"
    if URL.search(text):
        yield "a URL (a page fetches nothing and links nowhere outside the folder)"
    if any(p.search(text) for p in own):
        yield "a personal identifier pattern"


def check(folder: Path, own: list[re.Pattern[str]]) -> list[tuple[str, int, str]]:
    """(file, line number, what) for every hit in every text file under `folder`, in path order."""
    hits: list[tuple[str, int, str]] = []
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = path.relative_to(folder).as_posix()
        for n, line in enumerate(text.splitlines(), 1):
            hits.extend((rel, n, what) for what in findings(line, own))
    return hits


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: check_synthetic.py FOLDER", file=sys.stderr)
        return 2
    folder = Path(argv[0])
    if not folder.is_dir():
        print(f"check-synthetic: not a folder: {folder}", file=sys.stderr)
        return 2
    path = patterns_file()
    if path.is_file():
        own = load_patterns(path)
    else:
        own = []
        print(f"check-synthetic: no patterns file at {path}; checking the allowlist alone", file=sys.stderr)
    hits = check(folder, own)
    for rel, n, what in hits:
        print(f"{rel}:{n}: {what}")
    files = len({rel for rel, _n, _what in hits})
    if hits:
        print(f"check-synthetic: {len(hits)} hit(s) in {files} file(s) under {folder}; publish nothing")
        return 1
    print(f"check-synthetic: {folder}: only synthetic identifiers; nothing outside the allowlist")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
