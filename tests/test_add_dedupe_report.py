"""`logbook add` says how many drafts the store skipped as already in the record (same source and
`raw_id`), beside what it added, instead of skipping them silently (#79)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from logbook import cli
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
DAWARICH = ROOT / "tests" / "fixtures" / "dawarich" / "export.json"


def test_a_second_add_of_the_same_export_reports_the_store_level_skips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    export = tmp_path / "export.json"
    shutil.copy(DAWARICH, export)
    cli.main(["add", str(export)])
    first = capsys.readouterr().out
    assert "added 40 lines from dawarich" in first and "already in the record" not in first
    cli.main(["add", str(export)])
    second = capsys.readouterr().out
    assert "added 0 lines from dawarich" in second
    assert "  40 already in the record (same source and raw_id), nothing written twice" in second
