"""`logbook import pickup FOLDER`: a folder of call transcripts the Purser collected from the receiving
side, moved into the record as transcript lines with the right source, through the transcript
adapter's one mapping; a dry run unless `--write`; a file already taken skipped by its hash. On the
persona record: the Oslo owner's calls, synthetic, nobody in them real."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.contrib import pickup
from logbook.core import attachments
from logbook.core.store import Logbook

VTT = "WEBVTT\n\n00:00:00.000 --> 00:00:04.000\n<v Kari Nordmann>Ferja går 07:30.\n"


def _call(provider: str, raw_id: str, text: str, at: str = "2026-03-02T08:00:00Z") -> str:
    """A transcript/v1 JSON as the receiving side hands one back: its own source, the text inline."""
    doc = {
        "at": at,
        "end": None,
        "tz": "Europe/Oslo",
        "source": provider,
        "tier": 3,
        "payload": {
            "schema": "transcript/v1",
            "provider": provider,
            "raw_id": raw_id,
            "title": "Ferja til Nesodden",
            "content": {"media_type": "text/markdown", "text": text},
        },
    }
    return json.dumps(doc, ensure_ascii=False)


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    return lb


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    """What the Purser left: two calls from Granola (one in a subfolder), one from Fireflies, a
    subtitle file that names no source, a photo, and the Mac's own hidden file."""
    f = tmp_path / "Purser" / "pickup"
    (f / "granola").mkdir(parents=True)
    (f / "granola" / "call-1.json").write_text(
        _call("granola", "granola:not_0synthetic0010", "Kari Nordmann: Ferja går 07:30.\n"), encoding="utf-8"
    )
    (f / "call-2.json").write_text(
        _call("granola", "granola:not_0synthetic0011", "Ola: Vi tar neste.\n", "2026-03-03T09:00:00Z"),
        encoding="utf-8",
    )
    (f / "call-3.json").write_text(
        _call("fireflies", "fireflies:01SYNTHETIC0003", "Kari Nordmann: Takk.\n", "2026-03-04T10:00:00Z"),
        encoding="utf-8",
    )
    (f / "2026-03-05T12-00-00Z call.vtt").write_text(VTT, encoding="utf-8")
    (f / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (f / ".DS_Store").write_bytes(b"")
    return f


def _cli(*args: str) -> int:
    try:
        cli.main(list(args))
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 1
    return 0


def _transcripts(lb: Logbook) -> list[dict[str, Any]]:
    return [dict(line) for line in lb.lines_unsorted() if line.get("kind") == "transcript"]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files(folder: Path) -> list[str]:
    """The files under the folder, the hidden one the command never touches aside."""
    return sorted(
        p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file() and p.name != ".DS_Store"
    )


# -- a dry run, unless --write ---------------------------------------------------------------------


def test_a_dry_run_says_what_it_would_take_and_writes_nothing(
    lb: Logbook, folder: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _files(folder)
    assert _cli("import", "pickup", str(folder)) == 0
    out = capsys.readouterr().out
    assert "3 to take: granola 2, fireflies 1" in out
    assert "1 without a source (name it with --source)" in out and "1 not a transcript" in out
    assert "dry run: nothing written; --write takes them" in out
    assert lb.meta["seq"] == 0 and _files(folder) == before
    assert not (lb.root / attachments.DIR).exists()


def test_write_moves_each_call_into_the_record_with_its_own_source(
    lb: Logbook, folder: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    hashes = {name: _sha(folder / name) for name in ("granola/call-1.json", "call-2.json", "call-3.json")}
    assert _cli("import", "pickup", str(folder), "--write") == 0
    out = capsys.readouterr().out
    assert "took 3 files: 3 lines appended (granola 2, fireflies 1); 3 files removed from the folder" in out
    lines = {line["payload"]["raw_id"]: line for line in _transcripts(lb)}
    assert sorted(line["source"] for line in lines.values()) == ["fireflies", "granola", "granola"]
    one = lines["granola:not_0synthetic0010"]
    assert one["payload"]["extra"]["picked_up"] == {
        "sha256": hashes["granola/call-1.json"],
        "file": "granola/call-1.json",
    }
    assert one["tier"] == 3
    content = one["payload"]["content"]
    assert (
        lb.root / attachments.DIR / content["sha256"]
    ).read_bytes() == "Kari Nordmann: Ferja går 07:30.\n".encode()
    # what was not taken stays where it was, the folder's own subfolder included
    assert _files(folder) == ["2026-03-05T12-00-00Z call.vtt", "photo.png"]
    assert lb.verify()[2] == []


def test_a_file_already_taken_is_skipped_by_its_hash_whatever_its_name(
    lb: Logbook, folder: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    copy = folder.parent / "copy.json"
    shutil.copy(folder / "call-3.json", copy)
    assert _cli("import", "pickup", str(folder), "--write", "--keep") == 0
    capsys.readouterr()
    seq = lb.meta["seq"]
    shutil.copy(copy, folder / "renamed by the Purser.json")
    assert _cli("import", "pickup", str(folder), "--write", "--keep") == 0
    out = capsys.readouterr().out
    assert "0 to take" in out and "4 already taken (by hash)" in out
    assert lb.meta["seq"] == seq  # nothing appended
    assert _cli("import", "pickup", str(folder), "--write") == 0  # a move a crash left half done is finished
    assert "4 already taken, removed from the folder" in capsys.readouterr().out
    assert _files(folder) == ["2026-03-05T12-00-00Z call.vtt", "photo.png"]


def test_a_file_whose_line_is_in_the_record_already_is_left_and_not_written_twice(
    lb: Logbook, folder: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same call as Granola's own pull wrote it: the same raw_id, other bytes."""
    lb.append(
        at="2026-03-02T08:00:00Z",
        source="granola",
        kind="transcript",
        tier=3,
        payload={"schema": "transcript/v1", "provider": "granola", "raw_id": "granola:not_0synthetic0010"},
    )
    assert _cli("import", "pickup", str(folder), "--write") == 0
    out = capsys.readouterr().out
    assert "2 to take" in out and "1 already in the record (same source and raw_id)" in out
    assert lb.meta["seq"] == 3
    assert (folder / "granola" / "call-1.json").exists()  # not taken, so not moved: the owner decides


def test_keep_leaves_the_files_where_they_are(lb: Logbook, folder: Path) -> None:
    before = _files(folder)
    assert _cli("import", "pickup", str(folder), "--write", "--keep") == 0
    assert _files(folder) == before and len(_transcripts(lb)) == 3


def test_source_names_the_provider_of_a_file_that_names_none(
    lb: Logbook, folder: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("granola", "call-2.json", "call-3.json"):
        target = folder / name
        shutil.rmtree(target) if target.is_dir() else target.unlink()
    assert _cli("import", "pickup", str(folder), "--write", "--source", "plaud") == 0
    (line,) = _transcripts(lb)
    assert line["source"] == "plaud" and line["at"] == "2026-03-05T12:00:00Z"
    assert line["payload"]["extra"]["picked_up"]["file"] == "2026-03-05T12-00-00Z call.vtt"


def test_source_never_relabels_a_file_that_names_its_own(lb: Logbook, folder: Path) -> None:
    assert _cli("import", "pickup", str(folder), "--write", "--source", "plaud") == 0
    sources = sorted(line["source"] for line in _transcripts(lb))
    assert sources == ["fireflies", "granola", "granola", "plaud"]  # only the .vtt is plaud's


def test_a_folder_that_is_not_there_or_is_the_record_is_refused(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _cli("import", "pickup", str(tmp_path / "nowhere")) == 2
    assert "not a folder" in capsys.readouterr().err
    assert _cli("import", "pickup", str(lb.root / "logbook")) == 2
    assert "inside the record" in capsys.readouterr().err


def test_survey_reads_through_the_module(lb: Logbook, folder: Path) -> None:
    found = pickup.survey(lb, folder)
    assert [(f.name, f.status) for f in found] == [
        ("2026-03-05T12-00-00Z call.vtt", pickup.NO_SOURCE),
        ("call-2.json", pickup.TAKE),
        ("call-3.json", pickup.TAKE),
        ("granola/call-1.json", pickup.TAKE),
        ("photo.png", pickup.NOT_TRANSCRIPT),
    ]
