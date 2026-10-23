"""The agents' sessions of the whole record, kept between readings (`shelf_agents._session_seqs`): which
lines of the transcripts and the messages are a session's, kept beside the index by seq and read on
from where they stopped, so the next reading streams only what was appended since; what stands, and
what the gate reads, is decided from the lines each time. The shelf is the shelf read from every line
after each line appended, a grown session's superseding line and a retraction among them. On the
shelves' synthetic record (`tests/shelves_record.py`: the Oslo persona, who does not exist)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from shelves_record import record

from logbook.contrib import mcp_server, shelf_agents
from logbook.core import index, kept
from logbook.core.store import Logbook

GATES = (None, (1, 2))


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    return record(tmp_path, monkeypatch)


class Streamed:
    """How many messages each reading streamed."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch):
        self.n = 0
        real = index.Index.stream

        def stream(idx: Any, kind: str, *args: Any, **kwargs: Any) -> Any:
            for line in real(idx, kind, *args, **kwargs):
                if kind == shelf_agents.MESSAGE:
                    self.n += 1
                yield line

        monkeypatch.setattr(index.Index, "stream", stream)

    def take(self) -> int:
        n, self.n = self.n, 0
        return n


def _same(lb: Logbook, streamed: Streamed | None = None) -> int:
    """Each gate's standing sessions, kept and read on, as every line reads them; the messages the kept
    readings streamed, when counted."""
    if streamed is not None:
        streamed.take()
    found = [shelf_agents.standing(lb, g) for g in GATES]
    n = streamed.take() if streamed is not None else 0
    with mock.patch.object(kept, "load", return_value=None):
        assert found == [shelf_agents.standing(lb, g) for g in GATES]
    return n


def _session_message(lb: Logbook) -> dict[str, Any]:
    with lb.index() as idx:
        return next(line for line in idx.stream(shelf_agents.MESSAGE) if shelf_agents.is_session(line))


def _again(line: dict[str, Any], n: int, **payload: Any) -> dict[str, Any]:
    return {
        "at": f"2026-03-{21 + n:02d}T10:00:00Z",
        "source": line["source"],
        "kind": line["kind"],
        "tier": line["tier"],
        "payload": {**line["payload"], "raw_id": f"{line['payload'].get('raw_id')}-again-{n}", **payload},
    }


def test_a_line_at_a_time_the_shelf_is_the_reading_of_every_line(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    _same(lb)
    streamed = Streamed(monkeypatch)
    session = _session_message(lb)
    for n in range(4):
        lb.append(**_again(session, n))
        lb.append(
            at=f"2026-03-{21 + n:02d}T11:00:00Z",
            source="manual",
            kind="note",
            tier=2,
            payload={"schema": "note/v1", "text": f"not a session {n}"},
        )
        assert _same(lb, streamed) == 1, "the one message appended streamed once, for every gate"


def test_a_grown_session_and_a_retraction_are_read_from_the_lines(lb: Logbook) -> None:
    _same(lb)
    session = _session_message(lb)
    grown = lb.append(**_again(session, 0, text="grown", supersedes=session["id"]))
    _same(lb)
    lb.retract(int(grown["seq"]), "a wrong session")
    _same(lb)


def test_through_the_mcp_gate_nothing_is_kept(lb: Logbook) -> None:
    _same(lb)
    gated = mcp_server.GatedLogbook(lb.root, mcp_server.Gate(1, set()))
    assert shelf_agents.standing(gated) == shelf_agents.standing(lb, (1,))
