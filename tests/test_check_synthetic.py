"""`scripts/check_synthetic.py`: the check a published folder passes before it leaves — nothing shaped like
an identifier outside CONTRIBUTING.md's synthetic allowlist (the UK fictional `07700 900xxx` block, the
persona's `+47 9000 000x`, `example.org`, the MMSI `999000001`), no URL, and none of the owner's own
patterns. Every identifier here is synthetic or reserved for fiction (the NANP `555-01xx` block)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_synthetic.py"
CLEAN = """<!doctype html>
<p>Kari Nordmann, kari.nordmann@example.org, +4790000002, 07700 900123, +44 7700 900456</p>
<p>Solvind, MMSI 999000001, at 59.9050,10.7350 on 2026-06-13 09:15 · 114,786 lines · seq 12773</p>
<p>Flight XY 561 OSL → ZRH, 2026-06-15T07:30:00Z, 1 of 365, 2,547 lines, 20260613 17:50\u201318:00</p>
<a href="../years/2026.html">2026</a>
"""


def _run(folder: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(folder)],
        capture_output=True,
        encoding="utf-8",
        env={**_base_env(), **(env or {})},
    )


def _base_env() -> dict[str, str]:
    import os

    env = dict(os.environ)
    env["LOGBOOK_PII_PATTERNS"] = str(ROOT / "nonexistent-patterns")  # never the maintainer's own file
    return env


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    site = tmp_path / "site"
    (site / "years").mkdir(parents=True)
    (site / "years" / "2026.html").write_text(CLEAN, encoding="utf-8")
    (site / "index.html").write_text(CLEAN, encoding="utf-8")
    return site


def test_a_folder_of_synthetic_identifiers_passes_and_dates_and_counts_are_not_phone_numbers(
    folder: Path,
) -> None:
    r = _run(folder)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "only synthetic identifiers" in r.stdout
    assert "no patterns file" in r.stderr, "without the owner's file it says so once and goes on"


@pytest.mark.parametrize(
    ("text", "what"),
    [
        ("write to someone@example.com", "email address"),  # a reserved domain, but not this project's
        ("call +1 202 555 0123 any time", "phone number"),  # NANP fiction, outside this project's ranges
        ("or 020 7946 0999 in the office", "phone number"),  # the UK's fictional London block is not ours
        ("see https://example.org/page", "URL"),
        ("see www.example.org", "URL"),
        ('<a href="mailto:kari.nordmann@example.org">', "URL"),
    ],
)
def test_an_identifier_outside_the_allowlist_fails_naming_the_line_and_never_the_text(
    folder: Path, text: str, what: str
) -> None:
    page = folder / "years" / "2026.html"
    page.write_text(CLEAN + f"<p>{text}</p>\n", encoding="utf-8")
    r = _run(folder)
    assert r.returncode == 1
    assert f"years/2026.html:6: a {what}" in r.stdout or f"years/2026.html:6: an {what}" in r.stdout, r.stdout
    assert "1 hit(s) in 1 file(s)" in r.stdout
    for token in text.split():  # the number's groups, the address, the URL: none of it is printed
        if (len(token) >= 4 and any(c.isdigit() for c in token)) or "@" in token or "." in token:
            assert token not in r.stdout and token not in r.stderr, "the text is never printed"


def test_the_owners_own_patterns_apply_when_the_file_exists(folder: Path, tmp_path: Path) -> None:
    patterns = tmp_path / "pii-patterns"
    patterns.write_text("# synthetic, for the test\nStorgata 1\n", encoding="utf-8")
    (folder / "index.html").write_text(CLEAN + "<p>Storgata 1, Oslo</p>\n", encoding="utf-8")
    r = _run(folder, {"LOGBOOK_PII_PATTERNS": str(patterns)})
    assert r.returncode == 1
    assert "index.html:6: a personal identifier pattern" in r.stdout
    assert "Storgata" not in r.stdout and "no patterns file" not in r.stderr


def test_a_missing_folder_is_a_usage_error(tmp_path: Path) -> None:
    r = _run(tmp_path / "nowhere")
    assert r.returncode == 2 and "not a folder" in r.stderr
