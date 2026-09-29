"""`scripts/check_pii.py`: the pre-commit hook that greps staged diffs for the owner's personal identifiers.

The identifiers live outside the repository, one regex per line, in the file `LOGBOOK_PII_PATTERNS` names
(default `~/.config/logbook/pii-patterns`). Every value here is synthetic: `example.org` addresses and the
UK fictional range `07700 900xxx` (CLAUDE.md)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_pii.py"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.name", "Test")
    _git(r, "config", "user.email", "test@example.org")
    _git(r, "config", "commit.gpgsign", "false")
    return r


@pytest.fixture
def patterns(tmp_path: Path) -> Path:
    p = tmp_path / "pii-patterns"
    p.write_text(
        "# synthetic identifiers, one regex per line\n\n07700 900123\nkari\\.nordmann@example\\.org\n",
        encoding="utf-8",
    )
    return p


def _stage(repo: Path, name: str, text: str) -> None:
    (repo / name).write_text(text, encoding="utf-8")
    _git(repo, "add", name)


def _run(repo: Path, patterns: Path | None, *files: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "LOGBOOK_PII_PATTERNS"}
    if patterns is not None:
        env["LOGBOOK_PII_PATTERNS"] = str(patterns)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *files], cwd=repo, env=env, capture_output=True, encoding="utf-8"
    )


def test_added_line_with_an_identifier_fails_and_names_the_file_and_line(repo: Path, patterns: Path) -> None:
    _stage(repo, "notes.md", "# notes\n\ncall 07700 900123 tomorrow\n")
    r = _run(repo, patterns, "notes.md")
    assert r.returncode == 1
    assert "notes.md:3" in r.stdout
    assert "07700" not in r.stdout + r.stderr
    assert "900123" not in r.stdout + r.stderr


def test_the_pattern_itself_is_never_printed(repo: Path, patterns: Path) -> None:
    _stage(repo, "a.txt", "mail Kari.Nordmann@example.org\n")
    r = _run(repo, patterns, "a.txt")
    assert r.returncode == 1
    assert "a.txt:1" in r.stdout
    assert "nordmann" not in (r.stdout + r.stderr).lower()


def test_clean_diff_passes(repo: Path, patterns: Path) -> None:
    _stage(repo, "a.txt", "nothing personal here, 07700 900999 is a different number\n")
    r = _run(repo, patterns, "a.txt")
    assert r.returncode == 0, r.stdout + r.stderr


def test_only_added_lines_are_checked(repo: Path, patterns: Path) -> None:
    _stage(repo, "a.txt", "line one\ncall 07700 900123\nline three\n")
    _git(repo, "commit", "-q", "-m", "seed")
    _stage(repo, "a.txt", "line one\nline three\nline four\n")
    r = _run(repo, patterns, "a.txt")
    assert r.returncode == 0, r.stdout + r.stderr


def test_line_numbers_follow_the_hunk_header(repo: Path, patterns: Path) -> None:
    _stage(repo, "a.txt", "".join(f"line {i}\n" for i in range(1, 21)))
    _git(repo, "commit", "-q", "-m", "seed")
    lines = [f"line {i}" for i in range(1, 21)]
    lines.insert(14, "kari.nordmann@example.org")
    _stage(repo, "a.txt", "\n".join(lines) + "\n")
    r = _run(repo, patterns, "a.txt")
    assert r.returncode == 1
    assert "a.txt:15" in r.stdout


def test_missing_patterns_file_warns_once_and_passes(repo: Path, tmp_path: Path) -> None:
    _stage(repo, "a.txt", "call 07700 900123\n")
    r = _run(repo, tmp_path / "does-not-exist", "a.txt")
    assert r.returncode == 0
    assert r.stdout == ""
    assert len(r.stderr.strip().splitlines()) == 1
    assert "pii-patterns" in r.stderr or "does-not-exist" in r.stderr


def test_default_location_is_under_the_home_config_folder(repo: Path, tmp_path: Path) -> None:
    # conftest pins HOME (and USERPROFILE) under tmp_path; the hook must look there, not in the shell's home
    home = Path(os.environ["HOME"])
    (home / ".config" / "logbook").mkdir(parents=True)
    (home / ".config" / "logbook" / "pii-patterns").write_text("07700 900123\n")
    _stage(repo, "a.txt", "call 07700 900123\n")
    r = _run(repo, None, "a.txt")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "a.txt:1" in r.stdout


def test_no_files_means_the_whole_staged_diff(repo: Path, patterns: Path) -> None:
    _stage(repo, "b.txt", "07700 900123\n")
    r = _run(repo, patterns)
    assert r.returncode == 1
    assert "b.txt:1" in r.stdout
