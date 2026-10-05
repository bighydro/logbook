"""`show` orders a day by the instant of `at`, then `seq` (SPEC §3.2), never by the text of `at`:
`10:00:00.5Z` is later than `10:00:00Z`, though it sorts first as a string (#123)."""

from __future__ import annotations

import contextlib
import io
from pathlib import Path

import pytest

from logbook import cli
from logbook.core.store import Logbook


def test_a_fractional_second_sorts_by_instant_not_by_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append(
        at="2026-06-01T10:00:00.5Z",
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "text": "later"},
    )
    lb.append(
        at="2026-06-01T10:00:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "text": "earlier"},
    )
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.suppress(SystemExit):
        cli.main(["show", "2026-06-01"])
    rows = [line for line in out.getvalue().splitlines() if "  note " in line]
    assert len(rows) == 2 and "earlier" in rows[0] and "later" in rows[1], out.getvalue()
