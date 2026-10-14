"""`scripts/check_pii.py`: the pre-commit hook that greps the lines a commit adds (the staged diff, or a
commit range pre-commit names) for the owner's personal identifiers, and sweeps a whole tree on request.

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


def _commit(repo: Path, name: str, text: str) -> str:
    _stage(repo, name, text)
    _git(repo, "commit", "-q", "-m", f"change {name}")
    return _head(repo)


def _head(repo: Path) -> str:
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, encoding="utf-8"
    )
    return r.stdout.strip()


# what `pre-commit run --from-ref A --to-ref B` sets for every hook; a test sets them itself or not at all
RANGE = ("PRE_COMMIT_FROM_REF", "PRE_COMMIT_TO_REF")


def _run(
    repo: Path, patterns: Path | None, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    environ = {k: v for k, v in os.environ.items() if k != "LOGBOOK_PII_PATTERNS" and k not in RANGE}
    if patterns is not None:
        environ["LOGBOOK_PII_PATTERNS"] = str(patterns)
    environ.update(env or {})
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], cwd=repo, env=environ, capture_output=True, encoding="utf-8"
    )


def _last(r: subprocess.CompletedProcess[str]) -> str:
    """The line every run ends with: on stdout when something was checked, on stderr as a warning when not."""
    return (r.stdout or r.stderr).strip().splitlines()[-1]


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


def test_a_staged_run_ends_with_how_much_it_checked(repo: Path, patterns: Path) -> None:
    _stage(repo, "a.txt", "one\ntwo\n")
    r = _run(repo, patterns, "a.txt")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stderr == ""
    assert "2 patterns, 2 lines, 0 matches" in _last(r)


def test_a_match_names_the_pattern_never_the_text(repo: Path, tmp_path: Path) -> None:
    named = tmp_path / "named-patterns"
    named.write_text(
        "# synthetic\n(?P<phone>07700 900123)\nkari\\.nordmann@example\\.org\n", encoding="utf-8"
    )
    _stage(repo, "a.txt", "ring 07700 900123\nmail kari.nordmann@example.org\n")
    r = _run(repo, named, "a.txt")
    assert r.returncode == 1
    out = r.stdout.splitlines()
    assert out[0].startswith("a.txt:1:") and "phone" in out[0]
    assert out[1].startswith("a.txt:2:") and "line 3" in out[1]  # unnamed: its line in the patterns file
    assert "2 patterns, 2 lines, 2 matches" in _last(r)
    assert "900123" not in r.stdout + r.stderr
    assert "nordmann" not in (r.stdout + r.stderr).lower()


def test_a_range_with_an_identifier_fails_though_nothing_is_staged(repo: Path, patterns: Path) -> None:
    start = _commit(repo, "notes.md", "# notes\n")
    end = _commit(repo, "notes.md", "# notes\ncall 07700 900123 tomorrow\n")
    # as `pre-commit run --from-ref --to-ref` runs it: the variables set, the range's files handed over
    r = _run(repo, patterns, "notes.md", env={"PRE_COMMIT_FROM_REF": start, "PRE_COMMIT_TO_REF": end})
    assert r.returncode == 1, r.stdout + r.stderr
    assert "notes.md:2" in r.stdout
    assert "2 patterns, 1 line, 1 match" in _last(r)
    assert "900123" not in r.stdout + r.stderr


def test_the_range_flags_read_the_same_range(repo: Path, patterns: Path) -> None:
    start = _commit(repo, "a.txt", "one\n")
    _commit(repo, "b.txt", "kari.nordmann@example.org\n")
    end = _commit(repo, "a.txt", "one\ntwo\n")
    r = _run(repo, patterns, "--from-ref", start, "--to-ref", end)  # no files: the whole range
    assert r.returncode == 1, r.stdout + r.stderr
    assert "b.txt:1" in r.stdout
    assert "2 patterns, 2 lines, 1 match" in _last(r)


def test_a_clean_range_passes_and_says_how_many_lines_it_checked(repo: Path, patterns: Path) -> None:
    start = _commit(repo, "a.txt", "one\n")
    end = _commit(repo, "a.txt", "one\ntwo\nthree, 07700 900999\nfour\n")
    r = _run(repo, patterns, "a.txt", env={"PRE_COMMIT_FROM_REF": start, "PRE_COMMIT_TO_REF": end})
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stderr == ""
    assert "2 patterns, 3 lines, 0 matches" in _last(r)
    assert "warning" not in _last(r)


def test_a_range_that_adds_nothing_is_a_warning_not_a_clean_pass(repo: Path, patterns: Path) -> None:
    start = _commit(repo, "a.txt", "one\ncall 07700 900123\n")
    end = _commit(repo, "a.txt", "one\n")  # removes a line, adds none
    r = _run(repo, patterns, "a.txt", env={"PRE_COMMIT_FROM_REF": start, "PRE_COMMIT_TO_REF": end})
    assert r.returncode == 0
    assert r.stdout == ""
    assert len(r.stderr.strip().splitlines()) == 1
    assert "warning" in r.stderr and "2 patterns, 0 lines, 0 matches" in r.stderr


def test_tree_finds_an_identifier_in_a_file_outside_any_diff(repo: Path, patterns: Path) -> None:
    _commit(repo, "old.md", "# old\n\nmail kari.nordmann@example.org\n")
    start = _commit(repo, "other.md", "first\n")
    end = _commit(repo, "other.md", "first\nsecond\n")
    (repo / "untracked.txt").write_text("07700 900123\n", encoding="utf-8")  # not tracked: not swept
    in_range = _run(repo, patterns, "--from-ref", start, "--to-ref", end)
    assert in_range.returncode == 0, in_range.stdout + in_range.stderr
    r = _run(repo, patterns, "--tree", end)
    assert r.returncode == 1, r.stdout + r.stderr
    assert r.stdout.splitlines()[0].startswith("old.md:3:")
    assert "untracked" not in r.stdout
    assert "2 patterns, 5 lines, 1 match" in _last(r)  # old.md's three and other.md's two
    assert "nordmann" not in (r.stdout + r.stderr).lower()


def test_no_patterns_file_ends_with_a_warning_that_nothing_was_checked(repo: Path, tmp_path: Path) -> None:
    start = _commit(repo, "a.txt", "one\n")
    end = _commit(repo, "a.txt", "one\ncall 07700 900123\n")
    r = _run(repo, tmp_path / "does-not-exist", "--from-ref", start, "--to-ref", end)
    assert r.returncode == 0
    assert r.stdout == ""
    assert len(r.stderr.strip().splitlines()) == 1
    assert "warning" in r.stderr and "0 patterns, 1 line, 0 matches" in r.stderr
    assert "900123" not in r.stderr


def test_a_patterns_file_of_comments_only_is_the_same_warning(repo: Path, tmp_path: Path) -> None:
    empty = tmp_path / "pii-patterns"
    empty.write_text("# nothing yet\n\n", encoding="utf-8")
    _stage(repo, "a.txt", "call 07700 900123\n")
    r = _run(repo, empty, "a.txt")
    assert r.returncode == 0
    assert r.stdout == ""
    assert "warning" in r.stderr and "0 patterns, 1 line, 0 matches" in r.stderr


def test_an_unknown_ref_is_one_clear_error(repo: Path, patterns: Path) -> None:
    _commit(repo, "a.txt", "one\n")
    r = _run(repo, patterns, "--from-ref", "no-such-ref", "--to-ref", "HEAD")
    assert r.returncode == 2
    assert "no-such-ref" in r.stderr
    assert "Traceback" not in r.stderr


def test_half_a_range_is_refused(repo: Path, patterns: Path) -> None:
    _commit(repo, "a.txt", "one\n")
    r = _run(repo, patterns, env={"PRE_COMMIT_FROM_REF": "HEAD"})
    assert r.returncode == 2
    assert "Traceback" not in r.stderr
