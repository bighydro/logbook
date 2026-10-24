"""A transcript/v1 JSON whose `content` is a reference (SPEC §1.1) and an export that holds the file:
the `transcript` adapter stores the bytes it finds there (ADR 0015) when they hash to the reference,
and counts what it could not find or would not take; `logbook doctor --attachments` lists the lines
whose attachment the store lacks, by source. Synthetic Oslo persona only: a call from Granola and one
from Fireflies, nobody in them real."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.contrib import doctor
from logbook.contrib.adapters import transcript
from logbook.core import attachments
from logbook.core.store import Logbook

TURNS = json.dumps(
    {"turns": [{"speaker": "Kari Nordmann", "text": "Ferja går 07:30."}, {"speaker": "Ola", "text": "Bra."}]},
    ensure_ascii=False,
).encode("utf-8")
SPANS = b'{"format": "speaker-spans/1", "segments": []}'


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _export(
    folder: Path,
    *,
    provider: str = "granola",
    raw_id: str = "granola:not_0synthetic0002",
    content: bytes = TURNS,
    path: str | None = None,
    spans: bytes | None = None,
) -> Path:
    """One transcript/v1 JSON in `folder`, its content a reference, as Granola's and Fireflies'
    exports write it; the bytes themselves are not written here."""
    folder.mkdir(parents=True, exist_ok=True)
    ref = attachments.reference(content, "application/json")
    if path is not None:
        ref["path"] = path
    payload: dict[str, Any] = {
        "schema": "transcript/v1",
        "provider": provider,
        "raw_id": raw_id,
        "title": "Ferja til Nesodden",
        "participants": [{"name": "Kari Nordmann", "email": "kari@example.org"}, {"name": "Ola"}],
        "content": ref,
    }
    if spans is not None:
        payload["diarization"] = {
            "engine": provider,
            "channels": 2,
            "spans": attachments.reference(spans, "application/json"),
        }
    doc = {
        "at": "2026-03-02T08:00:00Z",
        "end": "2026-03-02T08:20:00Z",
        "tz": "Europe/Oslo",
        "source": provider,
    }
    doc.update({"kind": "transcript", "tier": 3, "payload": payload})
    file = folder / f"{raw_id.replace(':', '-')}.json"
    file.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return file


def _held(folder: Path, data: bytes, *parts: str) -> Path:
    place = folder.joinpath(*parts) if parts else folder / "attachments" / _sha(data)
    place.parent.mkdir(parents=True, exist_ok=True)
    place.write_bytes(data)
    return place


def _run(path: Path) -> tuple[list[dict[str, Any]], list[bytes], dict[str, int]]:
    stored: list[bytes] = []
    counts: dict[str, int] = {}
    lines = list(transcript.run(path, counts=counts, store=stored.append))
    return lines, stored, counts


# -- the adapter: what the export holds is stored ---------------------------------------------------


def test_a_reference_the_export_holds_under_attachments_is_stored(tmp_path: Path) -> None:
    folder = tmp_path / "export"
    _export(folder)
    _held(folder, TURNS)
    lines, stored, counts = _run(folder)
    assert stored == [TURNS] and counts == {"attachments_stored": 1}
    assert lines[0]["payload"]["content"]["sha256"] == _sha(TURNS)  # the line is the line it was


def test_the_reference_s_own_path_is_followed_by_its_parts(tmp_path: Path) -> None:
    folder = tmp_path / "export"
    _export(folder, path="files/call.json")
    _held(folder, TURNS, "files", "call.json")
    _lines, stored, counts = _run(folder)
    assert stored == [TURNS] and counts == {"attachments_stored": 1}


def test_a_file_named_by_its_digest_beside_the_json_is_stored(tmp_path: Path) -> None:
    file = _export(tmp_path / "export")
    _held(file.parent, TURNS, _sha(TURNS))
    _lines, stored, _counts = _run(file)  # one file, not the folder
    assert stored == [TURNS]


def test_bytes_that_do_not_hash_to_the_reference_are_refused_and_the_line_kept(tmp_path: Path) -> None:
    folder = tmp_path / "export"
    _export(folder)
    _held(folder, b"something else", "attachments", _sha(TURNS))
    lines, stored, counts = _run(folder)
    assert stored == [] and counts == {"attachments_refused": 1}
    assert len(lines) == 1 and lines[0]["payload"]["content"]["sha256"] == _sha(TURNS)


def test_a_reference_the_export_lacks_is_counted_and_the_line_written(tmp_path: Path) -> None:
    lines, stored, counts = _run(_export(tmp_path / "export"))
    assert stored == [] and counts == {"attachments_missing": 1} and len(lines) == 1


def test_a_path_that_leaves_the_export_is_never_read(tmp_path: Path) -> None:
    folder = tmp_path / "export"
    _export(folder, path="../outside.json")
    (tmp_path / "outside.json").write_bytes(TURNS)  # the right bytes, in the wrong place
    _lines, stored, counts = _run(folder)
    assert stored == [] and counts == {"attachments_missing": 1}


def test_the_spans_file_a_reference_names_is_stored_too(tmp_path: Path) -> None:
    folder = tmp_path / "export"
    _export(folder, spans=SPANS)
    _held(folder, TURNS)
    _held(folder, SPANS)
    _lines, stored, counts = _run(folder)
    assert stored == [TURNS, SPANS] and counts == {"attachments_stored": 2}


# -- `logbook add`: the store is filled, a line already in the record is not written again ------------


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    return lb


def _cli(*args: str) -> int:
    try:
        cli.main(list(args))
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 1
    return 0


def test_adding_the_export_again_with_the_file_fills_the_store_and_writes_no_line(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "export"
    _export(folder)
    assert _cli("add", "transcript", str(folder)) == 0
    assert "1 attachments missing from the export" in capsys.readouterr().out
    assert not (lb.root / attachments.DIR / _sha(TURNS)).exists()
    seq = lb.meta["seq"]
    _held(folder, TURNS)
    assert _cli("add", "transcript", str(folder)) == 0
    assert "1 attachments stored" in capsys.readouterr().out
    assert lb.meta["seq"] == seq  # the line was in the record: nothing appended
    assert (lb.root / attachments.DIR / _sha(TURNS)).read_bytes() == TURNS


# -- `logbook doctor --attachments` -----------------------------------------------------------------


def _line(lb: Logbook, source: str, raw_id: str, data: bytes) -> dict[str, Any]:
    payload: dict[str, Any] = {"schema": "transcript/v1", "provider": source, "raw_id": raw_id}
    payload["content"] = attachments.reference(data, "application/json")
    return dict(
        lb.append(at="2026-03-02T08:00:00Z", source=source, kind="transcript", tier=3, payload=payload)
    )


def test_doctor_attachments_lists_the_lines_whose_file_is_missing_by_source(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    held = b'{"turns": []}'
    lb.attach(held)
    present = _line(lb, "granola", "granola:held", held)["id"]
    one = _line(lb, "granola", "granola:a", b"a")["id"]
    two = _line(lb, "granola", "granola:b", b"b")["id"]
    three = _line(lb, "fireflies", "fireflies:c", b"c")["id"]
    gone = _line(lb, "fireflies", "fireflies:d", b"d")
    lb.retract(int(gone["seq"]), "a duplicate")
    gone = gone["id"]
    for state in ("current", "stale"):
        if state == "current":
            lb.index_rebuild()
        else:
            lb.index_path.unlink()
        assert _cli("doctor", "--attachments") == 0
        out = capsys.readouterr().out
        assert "granola: 2 lines" in out and "fireflies: 1 line" in out
        assert out.index("granola:") < out.index("fireflies:")  # the most first
        for line_id in (one, two, three):
            assert line_id in out
        assert present not in out and gone not in out  # a file in the store; a retracted line
        assert _sha(b"a")[:12] in out
        assert out.rstrip().splitlines()[-1].startswith("3 lines name a file the store lacks")
        assert not lb.index_path.exists() or state == "current"  # doctor never builds the index


def test_doctor_attachments_on_a_whole_store_says_so(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    held = b'{"turns": []}'
    lb.attach(held)
    _line(lb, "granola", "granola:held", held)
    assert _cli("doctor", "--attachments") == 0
    assert "every file the lines name is in the store" in capsys.readouterr().out


def test_doctor_attachments_goes_with_no_other_flag(lb: Logbook) -> None:
    assert _cli("doctor", "--attachments", "--implausible") == 2


def test_doctor_report_reads_through_the_module(lb: Logbook) -> None:
    _line(lb, "fireflies", "fireflies:x", b"x")
    found = doctor.missing_attachments(lb, doctor.index_state(lb)[0])
    assert [(m.source, m.sha256) for m in found] == [("fireflies", _sha(b"x"))]
