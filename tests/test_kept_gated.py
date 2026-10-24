"""A gated record keeps nothing (`kept.path`): the MCP server reads through a `GatedLogbook`, whose index
serves only what its gate lets through, beside the same index folder as the plain record. A reading it
kept would be brought forward by the Library, short of the lines above the ceiling; one the Library
kept, brought forward through the gate, would hand the client lines above it. On the demo month (the
Oslo persona and the people around her, who do not exist)."""

from __future__ import annotations

from pathlib import Path

import pytest

from logbook.contrib import demo, mcp_server, promises
from logbook.core import kept, people
from logbook.core.store import Logbook


@pytest.fixture
def lb(tmp_path: Path) -> Logbook:
    return demo.generate(tmp_path / "Demo", days=20, seed=1)


def _gated(lb: Logbook, ceiling: int) -> Logbook:
    return mcp_server.GatedLogbook(lb.root, mcp_server.Gate(ceiling, set()))


def test_a_gated_record_has_no_kept_reading(lb: Logbook) -> None:
    assert kept.path(lb, promises.KEPT_FILE) is not None
    assert kept.path(_gated(lb, 1), promises.KEPT_FILE) is None


@pytest.mark.parametrize("plain_first", (True, False))
def test_the_promises_through_a_gate_are_the_gate_s_and_the_library_s_its_own(
    lb: Logbook, plain_first: bool
) -> None:
    gated = _gated(lb, 1)
    readings = [lambda: promises.extract(lb), lambda: promises.extract(gated)]
    for read in readings if plain_first else readings[::-1]:
        read()
    held = kept.path(lb, promises.KEPT_FILE)
    assert held is not None
    before = held.read_bytes()
    through_gate = promises.extract(gated)
    assert through_gate.proposals == promises._extract(gated)[0].proposals
    assert held.read_bytes() == before, "the gated reading wrote nothing beside the index"
    assert promises.extract(lb).proposals == promises._extract(lb)[0].proposals
    assert through_gate.proposals != promises.extract(lb).proposals, "the demo has promises above tier 1"


def test_the_people_through_a_gate_are_read_from_its_lines(lb: Logbook) -> None:
    people.read_whole(lb)
    gated = _gated(lb, 1)
    whole = people.read_whole(gated)
    days = people.reading.record_days(gated)
    assert whole is not None and days is not None
    assert whole == people.read(gated, *days)
