"""`scripts/changelog_assemble.py`: at release time the fragments in `changelog.d/` (and the `## Unreleased`
block, while one exists) become one new version section at the top of CHANGELOG.md; the fragment files go."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "changelog_assemble.py"

OLDER = """## 0.5.0 — 2026-10-01

### Fixes
- An older line, kept byte for byte.

## 0.4.1 — 2026-09-25
- Another.
"""


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("changelog_assemble", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tree(tmp_path: Path) -> tuple[Path, Path]:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n" + OLDER, encoding="utf-8")
    fragments = tmp_path / "changelog.d"
    fragments.mkdir()
    (fragments / "README.md").write_text("# how fragments work\n", encoding="utf-8")
    return changelog, fragments


def test_fragments_become_one_version_section_and_are_removed(tree: tuple[Path, Path]) -> None:
    changelog, fragments = tree
    (fragments / "b-fix.md").write_text("### Fixed\n- A fix.\n", encoding="utf-8")
    (fragments / "a-feature.md").write_text(
        "### Added\n- A feature.\n  Continued on a second line.\n\n### Fixed\n- An earlier fix.\n",
        encoding="utf-8",
    )
    (fragments / "c-plain.md").write_text("- A line with no heading.\n", encoding="utf-8")
    (fragments / "notes.txt").write_text("not a fragment\n", encoding="utf-8")

    m = _load()
    assert m.assemble(changelog, fragments, "0.6.0", "2026-10-03") == 3

    assert changelog.read_text(encoding="utf-8") == (
        "# Changelog\n\n"
        "## 0.6.0 — 2026-10-03\n"
        "- A line with no heading.\n\n"
        "### Added\n- A feature.\n  Continued on a second line.\n\n"
        "### Fixed\n- An earlier fix.\n- A fix.\n\n" + OLDER
    )
    assert sorted(p.name for p in fragments.iterdir()) == ["README.md", "notes.txt"]


def test_an_unreleased_block_is_folded_into_the_version_with_the_fragments(tree: tuple[Path, Path]) -> None:
    changelog, fragments = tree
    changelog.write_text(
        "# Changelog\n\n## Unreleased\n\n### Added\n- Already listed.\n\n### Docs\n- A page.\n\n" + OLDER,
        encoding="utf-8",
    )
    (fragments / "x.md").write_text("### Added\n- From a fragment.\n", encoding="utf-8")

    _load().assemble(changelog, fragments, "0.6.0", "2026-10-03")

    assert changelog.read_text(encoding="utf-8") == (
        "# Changelog\n\n## 0.6.0 — 2026-10-03\n\n"
        "### Added\n- Already listed.\n- From a fragment.\n\n"
        "### Docs\n- A page.\n\n" + OLDER
    )


def test_nothing_to_release_is_an_error_and_changes_nothing(tree: tuple[Path, Path]) -> None:
    changelog, fragments = tree
    before = changelog.read_text(encoding="utf-8")
    with pytest.raises(SystemExit, match="nothing to release"):
        _load().assemble(changelog, fragments, "0.6.0", "2026-10-03")
    assert changelog.read_text(encoding="utf-8") == before


def test_a_version_already_in_the_changelog_is_refused(tree: tuple[Path, Path]) -> None:
    changelog, fragments = tree
    (fragments / "x.md").write_text("- A line.\n", encoding="utf-8")
    with pytest.raises(SystemExit, match=r"0\.5\.0 is already"):
        _load().assemble(changelog, fragments, "0.5.0", "2026-10-03")
    assert (fragments / "x.md").exists()


def test_a_fragment_that_is_not_a_bullet_list_is_refused_by_name(tree: tuple[Path, Path]) -> None:
    changelog, fragments = tree
    (fragments / "prose.md").write_text("Some prose, no bullet.\n", encoding="utf-8")
    with pytest.raises(SystemExit, match=r"prose\.md"):
        _load().assemble(changelog, fragments, "0.6.0", "2026-10-03")


def test_cli_dry_run_prints_the_section_and_writes_nothing(tree: tuple[Path, Path]) -> None:
    changelog, fragments = tree
    (fragments / "x.md").write_text("### Added\n- A line.\n", encoding="utf-8")
    before = changelog.read_text(encoding="utf-8")
    r = subprocess.run(
        [
            sys.executable, str(SCRIPT), "0.6.0", "--date", "2026-10-03", "--dry-run",
            "--changelog", str(changelog), "--fragments", str(fragments),
        ],
        capture_output=True, encoding="utf-8",
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    assert "## 0.6.0 — 2026-10-03" in r.stdout and "- A line." in r.stdout
    assert changelog.read_text(encoding="utf-8") == before
    assert (fragments / "x.md").exists()


def test_cli_rejects_a_bad_version() -> None:
    r = subprocess.run([sys.executable, str(SCRIPT), "v0.6"], capture_output=True, encoding="utf-8")
    assert r.returncode == 2
    assert "X.Y.Z" in r.stderr


def test_every_fragment_in_the_repository_is_well_formed() -> None:
    """A fragment that would stop the release is caught on the PR that adds it."""
    m = _load()
    for path in m.fragment_paths(ROOT / "changelog.d"):
        m.parse_fragment(path)
