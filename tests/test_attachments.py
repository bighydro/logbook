"""The SPEC §1.1 attachment store: `attachments.reference` names bytes, `Logbook.attach` writes them
once, `append_many` keeps an id a draft brings, `Index.line_id` finds a line by (source, raw_id), and
`stats` counts a `payload.content` reference."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import attachments
from logbook.store import Logbook, uuid7

TEXT = "Kari: Skal vi ta turen til Tromsø i mai?\nOla: Ja, gjerne.\n".encode()
SHA = hashlib.sha256(TEXT).hexdigest()


@pytest.fixture
def lb(tmp_path: Path) -> Logbook:
    return Logbook.init(tmp_path / "lb", "Europe/Oslo")


def test_reference_has_the_spec_1_1_shape():
    assert attachments.reference(TEXT, "text/markdown") == {
        "sha256": SHA,
        "path": f"attachments/{SHA}",
        "bytes": len(TEXT),
        "media_type": "text/markdown",
    }


def test_attach_writes_the_bytes_under_their_digest(lb: Logbook):
    path = lb.attach(TEXT)
    assert path == lb.root / "attachments" / SHA
    assert path.read_bytes() == TEXT


def test_attach_is_write_once_and_never_rewrites(lb: Logbook):
    first = lb.attach(TEXT)
    stamp = first.stat().st_mtime_ns
    first.write_bytes(TEXT)  # nothing else may touch it; simulate time passing
    second = lb.attach(TEXT)
    assert second == first and second.read_bytes() == TEXT
    assert second.stat().st_mtime_ns >= stamp


def test_attach_refuses_a_file_whose_bytes_do_not_match_its_name(lb: Logbook):
    store = lb.root / "attachments"
    store.mkdir()
    (store / SHA).write_bytes(b"tampered")
    with pytest.raises(ValueError, match=SHA[:12]):
        lb.attach(TEXT)


def test_append_many_keeps_the_id_a_draft_brings(lb: Logbook):
    given = uuid7()
    draft = {
        "at": "2026-03-01T13:00:00Z",
        "end": None,
        "tz": None,
        "source": "granola",
        "kind": "transcript",
        "tier": 3,
        "payload": {"schema": "transcript/v1", "raw_id": "granola:not_00000000000001"},
        "id": given,
    }
    assert lb.append_many([draft]) == 1
    (line,) = lb.lines()
    assert line["id"] == given
    assert lb.verify()[2] == []


def test_append_many_still_mints_an_id_when_the_draft_has_none(lb: Logbook):
    draft = {
        "at": "2026-03-01T13:00:00Z",
        "end": None,
        "tz": None,
        "source": "manual",
        "kind": "note",
        "tier": 2,
        "payload": {"schema": "note/v1", "text": "hei"},
    }
    lb.append_many([draft])
    (line,) = lb.lines()
    assert len(line["id"]) == 36


def test_index_line_id_finds_a_line_by_source_and_raw_id(lb: Logbook):
    line = lb.append(
        at="2026-03-01T13:00:00Z",
        source="granola",
        kind="transcript",
        tier=3,
        payload={"schema": "transcript/v1", "raw_id": "granola:not_00000000000001"},
    )
    with lb.index() as idx:
        assert idx.line_id("granola", "granola:not_00000000000001") == line["id"]
        assert idx.line_id("granola", "granola:nope") is None
        assert idx.line_id("fireflies", "granola:not_00000000000001") is None


def test_stats_counts_a_content_reference_as_an_attachment(lb: Logbook):
    from logbook.cli import record_stats

    lb.attach(TEXT)
    lb.append(
        at="2026-03-01T13:00:00Z",
        source="granola",
        kind="transcript",
        tier=3,
        payload={"schema": "transcript/v1", "content": attachments.reference(TEXT, "text/markdown")},
    )
    m = record_stats(lb)["attachments"]
    assert (m["referenced"], m["lines"], m["present"]) == (1, 1, 1)
