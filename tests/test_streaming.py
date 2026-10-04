"""verify, `lines()` and the whole-log export stream the month files (#28): one open handle and
one parsed line per file, merged by seq, never the whole log in memory. show and export --day
locate through the index and never scan the files."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import cli
from logbook.core import store
from logbook.core.store import Logbook, UnsortedFile


def _draft(i: int, month: str) -> dict[str, Any]:
    return {
        "at": f"2026-{month}-10T05:{i % 60:02d}:00Z",
        "source": "sim",
        "kind": "note",
        "tier": 1,
        "payload": {"schema": "note/v1", "text": f"line {i}", "raw_id": f"n:{i}"},
    }


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """Thirty lines over three month files, appended in an order that interleaves the files:
    chain order (seq) is not file order, and no file holds a run of consecutive seqs."""
    lb = Logbook.init(tmp_path / "lb", "UTC")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(_draft(i, ("03", "01", "02")[i % 3]) for i in range(30))
    return lb


def _files(lb: Logbook) -> list[str]:
    return [p.relative_to(lb.root).as_posix() for p in lb.files()]


# -- lines(): a merge of the month files, by seq ------------------------------------------------


def test_lines_come_out_in_chain_order_across_month_files(lb: Logbook):
    assert _files(lb) == ["logbook/2026/01.jsonl", "logbook/2026/02.jsonl", "logbook/2026/03.jsonl"]
    assert [line["seq"] for line in lb.lines()] == list(range(1, 31))


def test_lines_are_streamed_one_per_file_not_materialised(lb: Logbook, monkeypatch: pytest.MonkeyPatch):
    parsed: list[int] = []
    original = store.parse_line

    def counting(raw: str | bytes) -> Any:
        line = original(raw)
        parsed.append(int(line["seq"]))
        return line

    monkeypatch.setattr(store, "parse_line", counting)
    it = lb.lines()
    first = next(it)
    assert first["seq"] == 1
    assert len(parsed) <= len(lb.files())  # one line per file was enough to know which comes first
    assert [line["seq"] for line in it] == list(range(2, 31))
    assert len(parsed) == 30  # and every line was parsed exactly once


def test_a_file_out_of_seq_order_is_refused_by_lines_and_still_verifies(lb: Logbook):
    """SPEC §3 orders by seq wherever a line lives; the writer keeps every file in seq order,
    so the merge assumes it and says so when a file is not. verify falls back to a sorted read."""
    seq, head, errors = lb.verify()
    assert errors == [] and seq == 30
    path = lb.root / "logbook" / "2026" / "02.jsonl"
    rows = path.read_bytes().splitlines(keepends=True)
    path.write_bytes(b"".join(reversed(rows)))
    with pytest.raises(UnsortedFile, match=r"02\.jsonl"):
        list(lb.lines())
    assert lb.verify() == (seq, head, [])


def test_a_parse_error_is_still_reported_by_file_and_line(lb: Logbook):
    path = lb.root / "logbook" / "2026" / "02.jsonl"
    rows = path.read_bytes().splitlines(keepends=True)
    rows[4] = b'{"seq": 1, "seq": 2}\n'
    path.write_bytes(b"".join(rows))
    seq, _head, errors = lb.verify()
    assert seq == 0 and errors == ["logbook/2026/02.jsonl line 5: duplicate key 'seq'"]


# -- verify --progress: one line per month file, stdout byte-identical ---------------------------


def test_verify_reports_each_month_file_as_it_is_finished(lb: Logbook):
    """Heap merge finishes files in last-seq order (03, 01, 02); progress is held until
    every earlier path is done so reports read as 01, 02, 03."""
    seen: list[tuple[str, int, int]] = []
    seq, _head, errors = lb.verify(progress=lambda file, n, total, _elapsed: seen.append((file, n, total)))
    assert errors == [] and seq == 30
    assert seen == [
        ("logbook/2026/01.jsonl", 10, 29),
        ("logbook/2026/02.jsonl", 10, 30),
        ("logbook/2026/03.jsonl", 10, 30),
    ]


def test_cli_verify_progress_prints_one_line_per_file_on_stderr_and_the_same_stdout(lb: Logbook, capsys):
    cli.main(["verify"])
    plain = capsys.readouterr()
    cli.main(["verify", "--progress"])
    with_progress = capsys.readouterr()
    assert plain.err == ""
    assert with_progress.out == plain.out
    assert plain.out.startswith("valid — 30 lines, head ")
    lines = with_progress.err.splitlines()
    assert [text.split(": ", 1)[1].split(":")[0] for text in lines] == [
        "logbook/2026/01.jsonl",
        "logbook/2026/02.jsonl",
        "logbook/2026/03.jsonl",
    ]
    assert lines[0].startswith("  file 1 of 3:")
    assert lines[2].startswith("  file 3 of 3:")
    assert "10 lines (29 so far" in lines[0] and "10 lines (30 so far" in lines[-1]


def test_verify_fallback_does_not_gather_the_warnings_twice(lb: Logbook):
    """The merge yields nearly every line before it meets the disorder; the sorted read that
    follows starts the warnings over rather than adding to them."""
    first = lb.root / "logbook" / "2026" / "03.jsonl"  # holds seq 1
    rows = first.read_bytes().splitlines(keepends=True)
    rows[0] = rows[0].replace(b'"at": "2026-03-10T05:00:00Z"', b'"at": "2026-03-10T06:00:00+01:00"', 1)
    first.write_bytes(b"".join(rows))
    second = lb.root / "logbook" / "2026" / "02.jsonl"
    second.write_bytes(b"".join(reversed(second.read_bytes().splitlines(keepends=True))))
    warnings: list[str] = []
    _seq, _head, errors = lb.verify(warnings)
    assert any("line 1: hash does not recompute" in e for e in errors)  # `at` is hashed as written
    assert len(warnings) == 1 and warnings[0].startswith("line 1: at '2026-03-10T06:00:00+01:00'")


# -- the whole-log export streams too ------------------------------------------------------------


def test_export_whole_log_streams_and_accepts_an_unsorted_file(lb: Logbook, tmp_path: Path, capsys):
    cli.main(["export", str(tmp_path / "a.jsonl")])
    path = lb.root / "logbook" / "2026" / "02.jsonl"
    rows = path.read_bytes().splitlines(keepends=True)
    path.write_bytes(b"".join(reversed(rows)))
    cli.main(["export", str(tmp_path / "b.jsonl")])
    assert (tmp_path / "a.jsonl").read_bytes() == (tmp_path / "b.jsonl").read_bytes()
    assert capsys.readouterr().out.count("exported 30 lines") == 2


# -- show and export --day: the index says where; the files are never scanned (#28 part 3) ------


def test_show_with_a_current_index_does_not_scan_the_files(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    with lb.index():
        pass
    calls: list[str] = []
    for name in ("files", "lines", "lines_unsorted", "located_lines"):
        original = getattr(Logbook, name)

        def counting(self: Logbook, *a: Any, _name: str = name, _original: Any = original, **kw: Any) -> Any:
            calls.append(_name)
            return _original(self, *a, **kw)

        monkeypatch.setattr(Logbook, name, counting)
    cli.main(["show", "2026-02-10"])
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "2026-02-10" and len(out) == 11
    assert calls == []
