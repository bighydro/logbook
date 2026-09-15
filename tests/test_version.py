"""The package version and the distribution version must never drift apart."""

import tomllib
from pathlib import Path

import logbook

ROOT = Path(__file__).resolve().parent.parent


def test_package_version_matches_pyproject() -> None:
    with (ROOT / "pyproject.toml").open("rb") as f:
        pyproject = tomllib.load(f)
    assert logbook.__version__ == pyproject["project"]["version"]
