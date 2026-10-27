"""The record's first and last day, as an export below tier 3 sees them, are those of the lines it
admits (the review of 26 October, R3). `export site` takes Today's date and its span of years from
`reading.record_span`, and `export world` its window: a tier-3 health line on a later day must not
become Today's headline, nor one years earlier add empty years. The Oslo persona's fortnight
(`persona.py`, 8 to 21 June 2026), and the same fortnight with one tier-3 health sample a week after
it and one three years before. Nobody here exists."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
from persona import persona_record

from logbook import cli
from logbook.contrib import world
from logbook.core import reading
from logbook.core.store import Logbook

LATER, EARLIER = "2026-06-28", "2023-03-01"  # the health lines' days: after and before the fortnight
TIERS = ["1", "1,2"]
SPAN = re.compile(r"<p>[\d,]+ lines, (\S+) \S (\S+) \(")  # the root page's span, before its counts


def _health(day: str) -> dict[str, Any]:
    at = f"{day}T10:00:00Z"
    return {
        "at": at,
        "end": None,
        "source": "apple-health",
        "kind": "health",
        "tier": 3,
        "payload": {
            "schema": "health-sample/v1",
            "raw_id": f"resting_hr:{at}:watch",
            "type": "resting_hr",
            "value": 52,
            "unit": "count/min",
            "device": "watch",
        },
    }


def _policy(lb: Logbook) -> None:
    path = lb.root / "policy" / "crossing.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data.update({"site": {"max_tier": 2}, "world": {"max_tier": 2}})
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Logbook, Logbook]:
    """The fortnight, and a copy of it with the two tier-3 lines."""
    plain = persona_record(tmp_path / "plain", monkeypatch)
    _policy(plain)
    root = tmp_path / "health" / "lb"
    shutil.copytree(plain.root, root)
    health = Logbook(root)
    health.append_many([_health(LATER), _health(EARLIER)])
    return Logbook(plain.root), Logbook(root)


def _site(lb: Logbook, folder: Path, tiers: str, monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    cli.main(["export", "site", str(folder), "--tier", tiers])
    return {
        p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()
    }


def test_the_record_span_through_a_gate_spans_only_the_lines_it_admits(
    records: tuple[Logbook, Logbook],
) -> None:
    _plain, health = records
    assert reading.record_span(health) == (EARLIER, LATER), "read whole, the health lines open the span"
    for tiers in ((1,), (1, 2)):
        assert reading.record_span(health, tiers) == ("2026-06-08", "2026-06-21"), tiers
    assert reading.record_span(health, (1, 2, 3)) == (EARLIER, LATER)


@pytest.mark.parametrize("tiers", TIERS)
def test_a_tier_3_line_moves_neither_today_nor_the_span_nor_the_years_of_a_site(
    records: tuple[Logbook, Logbook], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tiers: str
) -> None:
    plain, health = records
    without = _site(plain, tmp_path / "without", tiers, monkeypatch)
    with_health = _site(health, tmp_path / "with", tiers, monkeypatch)
    assert with_health["today.html"] == without["today.html"], "Today's date is the last day a line crosses"
    assert LATER not in with_health["today.html"].decode("utf-8")
    span = SPAN.search(with_health["index.html"].decode("utf-8"))
    assert span is not None and span.groups() == ("2026-06-08", "2026-06-21")
    assert span.groups() == SPAN.search(without["index.html"].decode("utf-8")).groups()  # type: ignore[union-attr]
    years = sorted(name for name in with_health if name.startswith("years/"))
    assert years == sorted(name for name in without if name.startswith("years/")) == ["years/2026.html"]
    for name in years:
        assert with_health[name] == without[name], name
    assert sorted(with_health) == sorted(without), "no page for a year or a day only a tier-3 line holds"


@pytest.mark.parametrize("tiers", [(1,), (1, 2)])
def test_a_tier_3_line_does_not_move_the_world_s_window(
    records: tuple[Logbook, Logbook], tiers: tuple[int, ...]
) -> None:
    plain, health = records
    asked = world.request(health, tiers=tiers, today="2026-12-31")
    expected = world.request(plain, tiers=tiers, today="2026-12-31")
    assert asked is not None and expected is not None
    assert (asked.first, asked.last) == (expected.first, expected.last) == ("2026-06-08", "2026-06-21")
