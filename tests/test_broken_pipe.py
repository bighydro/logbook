"""Every reader piped into `head`: when the reader on the other end goes away, the command stops
quietly — nothing on stderr, exit status 0 — whether the pipe breaks on a write in the middle of a
long listing or, for a short one that fits the buffer, on the flush at exit. Synthetic Oslo persona."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from persona import persona_record

from logbook import cli

ROOT = Path(__file__).resolve().parents[1]
READERS = [
    ["show", "2026-06-10"],
    ["day", "2026-06-10"],
    ["days", "--from", "2026-06-08", "--to", "2026-06-21"],
    ["trips", "--year", "2026"],
    ["rollup", "nights", "--year", "2026"],
    ["rollup", "health", "--year", "2026"],
    ["stats"],
    ["stats", "--health"],
    ["sources"],
    ["verify"],
]


class _ClosedPipe(io.StringIO):
    """`head` is gone: the first write fails."""

    def write(self, s: str) -> int:
        raise BrokenPipeError


class _LatePipe(io.StringIO):
    """A short listing: every write lands in the buffer, and the flush is what fails — so the
    command must flush before it returns, or the interpreter's final flush reports the pipe."""

    asked = False

    def flush(self) -> None:
        self.asked = True
        raise BrokenPipeError


@pytest.mark.parametrize("args", READERS, ids=lambda a: " ".join(a))
def test_a_reader_into_a_closed_pipe_returns_quietly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], args: list[str]
) -> None:
    persona_record(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "stdout", _ClosedPipe())
    cli.main(args)  # no exception, no exit status other than 0
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("args", [READERS[0], READERS[2]], ids=lambda a: " ".join(a))
def test_a_short_listing_whose_pipe_breaks_on_the_final_flush_returns_quietly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], args: list[str]
) -> None:
    persona_record(tmp_path, monkeypatch)
    pipe = _LatePipe()
    monkeypatch.setattr(sys, "stdout", pipe)
    cli.main(args)
    assert pipe.asked, "the command flushed before returning"
    assert capsys.readouterr().err == ""


def test_an_exit_status_survives_a_pipe_that_breaks_on_the_final_flush(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`sources --gaps --expect` exits 1 when a source is flagged; the status stands and the
    broken pipe is still quiet."""
    persona_record(tmp_path, monkeypatch)
    pipe = _LatePipe()
    monkeypatch.setattr(sys, "stdout", pipe)
    with pytest.raises(SystemExit) as e:
        cli.main(["sources", "--gaps", "--expect", "no-such-source"])
    assert e.value.code == 1 and pipe.asked
    assert capsys.readouterr().err == ""


def _pipeline(lb_root: Path, command: str) -> subprocess.CompletedProcess[str]:
    """`logbook <command>` through bash with pipefail, stdout block-buffered as a pipe makes it (the
    shell's PYTHONUNBUFFERED, which a CI image may set, would hide the flush at exit)."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"}
    env.update({"LOGBOOK_HOME": str(lb_root), "PYTHONPATH": str(ROOT)})
    return subprocess.run(
        ["bash", "-o", "pipefail", "-c", f"{sys.executable} -m logbook.cli {command}"],
        env=env,
        capture_output=True,
        encoding="utf-8",
    )


needs_bash = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="needs a real bash for a pipeline with pipefail (the Windows stub is not one)",
)


@needs_bash
@pytest.mark.parametrize("args", [READERS[2], READERS[3]], ids=lambda a: " ".join(a))
def test_a_listing_piped_into_head_exits_0_with_nothing_on_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    r = _pipeline(lb.root, f"{' '.join(args)} | head -1")
    assert r.returncode == 0, r.stderr
    assert r.stdout.count("\n") == 1 and r.stderr == ""


@needs_bash
@pytest.mark.parametrize("args", [READERS[0], READERS[2], READERS[6]], ids=lambda a: " ".join(a))
def test_a_short_listing_whose_reader_quit_already_exits_0_with_nothing_on_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    """A fortnight of days is a dozen lines, under the buffer: nothing reaches the pipe until the
    flush at exit, by when `true` is long gone. Without a flush of our own that is `Exception
    ignored in: <_io.TextIOWrapper name='<stdout>'> BrokenPipeError` on stderr and status 120."""
    lb = persona_record(tmp_path, monkeypatch)
    r = _pipeline(lb.root, f"{' '.join(args)} | true")
    assert r.returncode == 0, r.stderr
    assert r.stderr == ""


@needs_bash
def test_a_flagged_gap_report_keeps_its_status_when_the_reader_quit_already(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    r = _pipeline(lb.root, "sources --gaps --expect no-such-source | true")
    assert r.returncode == 1, r.stderr
    assert r.stderr == ""
