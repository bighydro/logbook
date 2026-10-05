"""RFC 0031: `trip/v1` is renamed `journey/v1` for new lines. The three writers of RFC 0020 lines
(easypark, sbb, passages) write kind `journey`, schema `journey/v1`; `show` formats a `trip`/`trip/v1`
line and a `journey`/`journey/v1` line the same way; `search --kinds trip` and `--kinds journey` each
find both. No migration: a `trip/v1` line written before the rename stays as it is (SPEC §3)."""

from __future__ import annotations

import contextlib
import io
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from logbook import cli
from logbook.commands import rows
from logbook.contrib.adapters import easypark, passages, sbb
from logbook.core import search
from logbook.core.store import Logbook

TZ = "Europe/Zurich"
PAYLOAD = {
    "raw_id": "sbb:ticket-0001",
    "mode": "transit",
    "provider": "sbb",
    "from": {"name": "Zürich HB"},
    "to": {"name": "Bern"},
    "price": {"amount": "58.00", "currency": "CHF"},
    "extra": {"changes": 1},
}


def _lines() -> tuple[dict, dict]:
    old = {
        "at": "2026-05-04T07:02:00Z",
        "end": "2026-05-04T07:58:00Z",
        "tz": TZ,
        "source": "sbb",
        "kind": "trip",
        "tier": 3,
        "payload": {"schema": "trip/v1", **PAYLOAD},
    }
    new = {
        **old,
        "at": "2026-05-04T16:02:00Z",
        "end": "2026-05-04T16:58:00Z",
        "kind": "journey",
        "payload": {"schema": "journey/v1", **PAYLOAD, "raw_id": "sbb:ticket-0002"},
    }
    return old, new


def test_the_three_writers_say_journey() -> None:
    for adapter in (easypark, sbb, passages):
        assert (adapter.KIND, adapter.SCHEMA) == ("journey", "journey/v1"), adapter.__name__


def test_show_formats_both_spellings_the_same() -> None:
    old, new = _lines()
    tz = ZoneInfo(TZ)
    assert rows._line_text(old, tz, None) == rows._line_text(new, tz, None)
    assert "Zürich HB → Bern" in rows._line_text(new, tz, None)


def test_search_finds_both_under_either_kind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    old, new = _lines()
    assert lb.append_many([old, new]) == 2
    for kinds in (["trip"], ["journey"], None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.suppress(SystemExit):
            cli.main(["search", "Bern", "--tier", "3", *(["--kinds", ",".join(kinds)] if kinds else [])])
        text = out.getvalue()
        assert text.count("Zürich HB → Bern") == 2, (kinds, text)
    assert search.body_of(new, None) is not None
    assert "journey" in search.KINDS and "trip" in search.KINDS
