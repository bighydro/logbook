"""Release-time step: fold the changelog fragments in `changelog.d/` into one new version section at the top
of CHANGELOG.md, then delete the fragment files. Stdlib only.

A pull request never edits CHANGELOG.md (many of them run at once and all conflict on the same lines); it
adds `changelog.d/<short-slug>.md` instead: one or a few `- ` lines in the changelog's own wording, optionally
under `### Heading` lines. Here they become `## X.Y.Z — YYYY-MM-DD`: lines without a heading first, then one
block per heading, headings in the order first met (a `## Unreleased` block in CHANGELOG.md, while one
exists, counts as the first fragment, so its headings come first and fragments under the same heading append
to it), then the fragments by file name. Everything from the first version heading down is kept byte for
byte.

Usage: `changelog_assemble.py X.Y.Z [--date YYYY-MM-DD] [--dry-run] [--changelog PATH] [--fragments DIR]`."""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
HEADING = "### "
NO_HEADING = ""


def fragment_paths(fragments: Path) -> list[Path]:
    """Every `*.md` in the directory but README.md, by name."""
    if not fragments.is_dir():
        return []
    return sorted(p for p in fragments.iterdir() if p.suffix == ".md" and p.name != "README.md")


def parse_lines(lines: list[str], name: str) -> dict[str, list[str]]:
    """Heading → its lines, in order of first appearance; `NO_HEADING` for lines before any heading."""
    out: dict[str, list[str]] = {}
    heading = NO_HEADING
    for raw in lines:
        line = raw.rstrip()
        if not line:
            continue
        if line.startswith(HEADING):
            heading = line[len(HEADING) :].strip()
            out.setdefault(heading, [])
        elif line.startswith("- ") or line[0].isspace():
            out.setdefault(heading, []).append(line)
        else:
            sys.exit(f"{name}: not a `- ` line, a `### ` heading or an indented continuation: {line[:60]!r}")
    if not any(out.values()):
        sys.exit(f"{name}: no lines")
    return out


def parse_fragment(path: Path) -> dict[str, list[str]]:
    return parse_lines(path.read_text(encoding="utf-8").splitlines(), str(path))


def split_changelog(text: str) -> tuple[str, list[str], str]:
    """(head above the first `## `, the lines of a leading `## Unreleased` block, everything from the first
    version heading down)."""
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.startswith("## ")]
    if not starts:
        return text, [], ""
    first = starts[0]
    head = "".join(lines[:first])
    if lines[first].strip().lower() != "## unreleased":
        return head, [], "".join(lines[first:])
    end = starts[1] if len(starts) > 1 else len(lines)
    return head, [line.rstrip("\r\n") for line in lines[first + 1 : end]], "".join(lines[end:])


def render(version: str, date: str, sections: dict[str, list[str]]) -> str:
    out = [f"## {version} — {date}"]
    if sections.get(NO_HEADING):
        out.extend(sections[NO_HEADING])
    for heading, lines in sections.items():
        if heading != NO_HEADING and lines:
            out.extend(["", f"### {heading}", *lines])
    return "\n".join(out) + "\n\n"


def assemble(changelog: Path, fragments: Path, version: str, date: str, *, dry_run: bool = False) -> int:
    """Write the new section; return how many fragment files it took (and, unless `dry_run`, deleted)."""
    text = changelog.read_text(encoding="utf-8")
    if re.search(rf"^## {re.escape(version)}(\s|$)", text, re.MULTILINE):
        sys.exit(f"{changelog}: {version} is already a section")
    head, unreleased, rest = split_changelog(text)
    paths = fragment_paths(fragments)
    if not unreleased and not paths:
        sys.exit(
            f"nothing to release: no fragments in {fragments} and no `## Unreleased` block in {changelog}"
        )

    sections: dict[str, list[str]] = {}
    parsed = [parse_lines(unreleased, f"{changelog} (Unreleased)")] if unreleased else []
    parsed.extend(parse_fragment(p) for p in paths)
    for fragment in parsed:
        for heading, lines in fragment.items():
            sections.setdefault(heading, []).extend(lines)

    section = render(version, date, sections)
    if dry_run:
        sys.stdout.write(section)
        return len(paths)
    if head and not head.endswith("\n\n"):
        head = head.rstrip("\r\n") + "\n\n"
    changelog.write_text(head + section + rest, encoding="utf-8", newline="\n")
    for p in paths:
        p.unlink()
    return len(paths)


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252; the section has an em dash
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("version", help="the version being released, X.Y.Z")
    ap.add_argument("--date", default=dt.date.today().isoformat(), help="YYYY-MM-DD; default today")
    ap.add_argument("--dry-run", action="store_true", help="print the new section; write and delete nothing")
    ap.add_argument("--changelog", type=Path, default=ROOT / "CHANGELOG.md")
    ap.add_argument("--fragments", type=Path, default=ROOT / "changelog.d")
    args = ap.parse_args(argv)
    if not VERSION.match(args.version):
        ap.error(f"version must be X.Y.Z, not {args.version!r}")
    taken = assemble(args.changelog, args.fragments, args.version, args.date, dry_run=args.dry_run)
    verb = "would take" if args.dry_run else "took"
    print(
        f"changelog-assemble: {args.version} {verb} {taken} fragment(s) from {args.fragments}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
