"""`logbook repair fork`: a record whose month files hold two chains that fork at one head — a long
writer computed its batch from a head another writer had moved past (#234) — diagnosed, and with
`--apply` the orphan chain moved out of the record into `repair/`, nothing deleted. Synthetic Oslo
persona throughout; nobody in it exists."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.contrib import doctor
from logbook.core import fork
from logbook.core.index import Index
from logbook.core.store import Logbook

DAYS = ("2026-09-10", "2026-09-11", "2026-10-02")  # the affected days: two month files


def _draft(prefix: str, i: int, source: str = "dawarich") -> dict[str, Any]:
    day = DAYS[i % len(DAYS)]
    return {
        "at": f"{day}T{6 + i % 12:02d}:{i % 60:02d}:00Z",
        "source": source,
        "kind": "location",
        "tier": 1,
        "payload": {"schema": "location/v1", "lat": 59.91, "lon": 10.75, "raw_id": f"{prefix}:{i}"},
    }


def _batch(prefix: str, n: int, source: str = "dawarich") -> list[dict[str, Any]]:
    return [_draft(prefix, i, source) for i in range(n)]


def _forked(root: Path, a: int, b: int, b_source: str = "immich") -> tuple[Logbook, dict[str, Any]]:
    """A record with three seed lines (head h0), batch A (`a` lines) chained from h0 by one writer,
    and batch B (`b` lines) also chained from h0, written into the month files the way the bug did:
    through the real `append_many`, whose head went stale while another writer appended A. The
    index refuses B's seqs, so it still describes A's chain; logbook.json carries B's head.
    Returns the record and logbook.json as it was right after A."""
    lb = Logbook.init(root, "Europe/Oslo")
    lb.append_many(_batch("seed", 3, "manual"))
    stale = lb.meta  # the head the slow writer reads when it starts
    after_a: dict[str, Any] = {}

    def slow_writer_drafts() -> Iterator[dict[str, Any]]:
        other = Logbook(root)  # the fast command, while the slow one walks
        other.append_many(_batch("a", a))
        after_a.update(other.meta)
        # logbook.json back to the head the slow writer read: the single-writer guard re-checks the
        # head before it writes a batch, and this is a test of the repair, not of the guard
        other._save_meta(stale)
        yield from _batch("b", b, b_source)

    with pytest.raises(sqlite3.IntegrityError):
        lb.append_many(slow_writer_drafts())
    return lb, after_a


def _raw_lines(lb: Logbook) -> dict[Path, list[bytes]]:
    return {f: f.read_bytes().splitlines(keepends=True) for f in lb.files()}


def _raw_ids(lines: list[bytes]) -> list[str]:
    return [str(json.loads(raw)["payload"]["raw_id"]) for raw in lines]


def _cli(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    try:
        cli.main(["repair", "fork", *args])
    except SystemExit as e:
        code = int(e.code or 0)
    else:
        code = 0
    out, err = capsys.readouterr()
    return code, out, err


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "Records" / "Logbook"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    monkeypatch.delenv("OneDrive", raising=False)
    return root


# -- the bug, reproduced ------------------------------------------------------------------------------


def test_the_stale_head_leaves_two_chains_and_verify_says_so(root: Path):
    lb, after_a = _forked(root, a=5, b=4)
    _seq, _head, errors = lb.verify()
    assert errors, "two chains forked at one head must not verify"
    assert any("expected" in e for e in errors) and any("prev does not match" in e for e in errors)
    assert lb.meta["seq"] == 3 + 4 and after_a["seq"] == 3 + 5  # logbook.json carries B's head
    assert any(e.startswith("logbook.json says") for e in errors)
    files = _raw_lines(lb)
    assert sum(len(v) for v in files.values()) == 3 + 5 + 4


# -- the diagnosis --------------------------------------------------------------------------------------


def test_dry_run_reports_the_fork_and_writes_nothing(root: Path, capsys: pytest.CaptureFixture[str]):
    lb, after_a = _forked(root, a=5, b=4)
    before = {f: f.read_bytes() for f in lb.files()}
    meta_before = lb.meta_path.read_bytes()
    code, out, _err = _cli(capsys)
    assert code == 0
    assert "fork at seq 3" in out and "orphan chain" in out
    assert "4 lines, seq 4" in out and "immich" in out and "logbook/2026/09.jsonl" in out
    assert "logbook/2026/10.jsonl" in out
    assert "main chain: 8 lines, seq 1" in out and "the index agrees" in out
    assert "logbook.json says seq=7" in out and "main chain ends at seq=8" in out
    assert "nothing written — run with --apply to repair" in out
    assert {f: f.read_bytes() for f in lb.files()} == before
    assert lb.meta_path.read_bytes() == meta_before
    assert not (root / "repair").exists()
    # never a line's contents: no payload, no coordinates, no raw ids
    assert "59.91" not in out and "raw_id" not in out and "b:0" not in out
    assert after_a["head"][:12] in out


def test_dry_run_on_a_sound_record_says_one_chain(root: Path, capsys: pytest.CaptureFixture[str]):
    lb = Logbook.init(root, "Europe/Oslo")
    lb.append_many(_batch("seed", 3, "manual"))
    code, out, _err = _cli(capsys)
    assert code == 0 and "one chain" in out and "nothing to repair" in out
    code, out, _err = _cli(capsys, "--apply")
    assert code == 0 and "nothing to repair" in out and not (root / "repair").exists()


# -- --apply ----------------------------------------------------------------------------------------------


def test_apply_moves_batch_b_out_and_the_record_verifies(root: Path, capsys: pytest.CaptureFixture[str]):
    lb, after_a = _forked(root, a=5, b=4)
    files_before = _raw_lines(lb)
    code, out, _err = _cli(capsys, "--apply")
    assert code == 0, out
    removed = sorted((root / "repair").glob("*-removed.jsonl"))
    reports = sorted((root / "repair").glob("*-report.json"))
    assert len(removed) == 1 and len(reports) == 1
    moved = removed[0].read_bytes().splitlines(keepends=True)
    assert _raw_ids(moved) == [f"b:{i}" for i in range(4)]  # exactly batch B, in order
    kept = _raw_lines(lb)
    assert sum(len(v) for v in kept.values()) == 3 + 5
    for f, lines in files_before.items():  # the kept lines are the old bytes, B's cut out
        assert kept[f] == [raw for raw in lines if raw not in moved]
    meta = lb.meta
    assert (meta["seq"], meta["head"]) == (after_a["seq"], after_a["head"])
    seq, head, errors = lb.verify()
    assert errors == [] and (seq, head) == (after_a["seq"], after_a["head"])
    with Index.open(lb) as idx:
        assert idx.matches(meta)
    for day in DAYS:
        ids = [line["payload"]["raw_id"] for line in lb.day_lines(day)]
        assert ids and all(i.startswith(("a:", "seed:")) for i in ids)
        assert not any(i.startswith("b:") for i in ids)
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["orphans"][0]["lines"] == 4 and report["main"]["last_seq"] == 8
    assert report["main"]["chosen_by"] == "index"
    assert "valid — 8 lines" in out and "moved 4 lines" in out


def test_apply_with_the_index_gone_keeps_the_longer_chain(root: Path, capsys: pytest.CaptureFixture[str]):
    lb, after_a = _forked(root, a=6, b=3)
    lb.index_path.unlink()
    code, out, _err = _cli(capsys, "--apply")
    assert code == 0, out
    assert "the longer chain" in out
    moved = next((root / "repair").glob("*-removed.jsonl")).read_bytes().splitlines(keepends=True)
    assert _raw_ids(moved) == [f"b:{i}" for i in range(3)]
    assert (lb.meta["seq"], lb.meta["head"]) == (after_a["seq"], after_a["head"])
    assert lb.verify()[2] == []


def test_two_chains_of_equal_length_and_no_index_refuse(root: Path, capsys: pytest.CaptureFixture[str]):
    lb, _after_a = _forked(root, a=4, b=4)
    lb.index_path.unlink()
    before = {f: f.read_bytes() for f in lb.files()}
    code, out, _err = _cli(capsys)  # the dry run still works
    assert code == 0 and "nothing written" in out
    assert "cannot tell which chain is the record" in out
    code, out, err = _cli(capsys, "--apply")
    assert code == 2 and "cannot tell which chain is the record" in err
    assert {f: f.read_bytes() for f in lb.files()} == before and not (root / "repair").exists()


def test_a_main_chain_line_is_never_touched(root: Path):
    lb, _after_a = _forked(root, a=5, b=4)
    report = fork.diagnose(lb)
    assert report.main is not None and len(report.orphans) == 1
    main_bytes = {raw for f, lines in _raw_lines(lb).items() for raw in lines}
    orphan_bytes = {raw for raw in fork.orphan_bytes(lb, report)}
    main_bytes -= orphan_bytes
    # the file changes under the diagnosis: a main-chain line re-serialised where an orphan was
    path = lb.root / "logbook" / "2026" / "09.jsonl"
    lines = path.read_bytes().splitlines(keepends=True)
    swapped = [json.loads(raw) for raw in lines]
    path.write_bytes(b"".join(json.dumps(line, separators=(",", ":")).encode() + b"\n" for line in swapped))
    with pytest.raises(fork.Refused, match="changed since"):
        fork.apply(lb, report)
    assert not (root / "repair").exists() or not list((root / "repair").glob("*-removed.jsonl"))
    # and after a sound apply every main-chain line is the bytes it was
    lb, _after_a = _forked(root / "again", a=5, b=4)
    report = fork.diagnose(lb)
    before = {raw for f, lines in _raw_lines(lb).items() for raw in lines} - set(
        fork.orphan_bytes(lb, report)
    )
    fork.apply(lb, report)
    assert {raw for f, lines in _raw_lines(lb).items() for raw in lines} == before


def test_apply_refuses_under_a_cloud_folder(tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture[str]):
    root = tmp_path / "Dropbox" / "Logbook"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    monkeypatch.delenv("OneDrive", raising=False)
    lb, _after_a = _forked(root, a=5, b=4)
    code, out, _err = _cli(capsys)
    assert code == 0 and "nothing written" in out
    code, _out, err = _cli(capsys, "--apply")
    assert code == 2 and "Dropbox" in err and not (root / "repair").exists()
    assert lb.verify()[2]  # untouched


def test_apply_refuses_a_sealed_orphan_line_it_cannot_open(root: Path, monkeypatch, capsys):
    pytest.importorskip("pyrage")
    from logbook.core import sealing

    pairs = [sealing.generate_identity() for _ in range(2)]
    lb = Logbook.init(root, "Europe/Oslo")
    meta = lb.meta
    meta["recipients"] = [r for _, r in pairs]
    lb._save_meta(meta)
    key_file = root.parent / "keys" / "owner.txt"
    sealing.write_identity_file(key_file, pairs[0][0], "test")
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(key_file))
    lb = Logbook(root)
    lb.append_many(_batch("seed", 3, "manual"))

    def slow_writer_drafts() -> Iterator[dict[str, Any]]:
        Logbook(root).append_many(_batch("a", 5))
        for d in _batch("b", 2, "manual"):
            yield {
                **d,
                "tier": 2,
                "kind": "note",
                "payload": {"schema": "note/v1", "text": "x", "raw_id": d["payload"]["raw_id"]},
            }

    with pytest.raises(sqlite3.IntegrityError):
        lb.append_many(slow_writer_drafts())
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(root.parent / "keys" / "missing.txt"))
    code, _out, err = _cli(capsys, "--apply")
    assert code == 2 and "sealed" in err and not (root / "repair").exists()
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(key_file))
    code, out, _err = _cli(capsys, "--apply")
    assert code == 0, out
    assert Logbook(root).verify()[2] == []


def test_doctor_names_repair_when_verify_fails(root: Path):
    lb, _after_a = _forked(root, a=5, b=4)
    check = doctor.record_check(lb)
    assert check.status == "fail" and "logbook repair fork" in check.detail


# -- --keep-head: the owner names the chain -----------------------------------------------------------


def test_the_dry_run_prints_full_heads(root: Path, capsys: pytest.CaptureFixture[str]):
    lb, after_a = _forked(root, a=5, b=4)
    report = fork.diagnose(lb)
    orphan_head = report.segments[report.orphans[0]].head
    code, out, _err = _cli(capsys)
    assert code == 0
    assert f"head {after_a['head']};" in out and f"head {orphan_head}," in out  # the full 64 characters
    assert len(after_a["head"]) == 64


def test_equal_chains_without_an_index_succeed_with_keep_head(root: Path, capsys: pytest.CaptureFixture[str]):
    lb, after_a = _forked(root, a=4, b=4)
    lb.index_path.unlink()
    code, out, _err = _cli(capsys, "--keep-head", after_a["head"][:12])  # a unique prefix is enough
    assert code == 0 and "the owner named it (--keep-head)" in out and "nothing written" in out
    code, out, _err = _cli(capsys, "--apply", "--keep-head", after_a["head"])
    assert code == 0, out
    moved = next((root / "repair").glob("*-removed.jsonl")).read_bytes().splitlines(keepends=True)
    assert _raw_ids(moved) == [f"b:{i}" for i in range(4)]
    assert (lb.meta["seq"], lb.meta["head"]) == (after_a["seq"], after_a["head"])
    assert lb.verify()[2] == []
    report = json.loads(next((root / "repair").glob("*-report.json")).read_text(encoding="utf-8"))
    assert report["main"]["chosen_by"] == "owner" and report["keep_head"] == after_a["head"]


def test_a_head_no_chain_ends_in_refuses(root: Path, capsys: pytest.CaptureFixture[str]):
    lb, _after_a = _forked(root, a=5, b=4)
    before = {f: f.read_bytes() for f in lb.files()}
    code, out, _err = _cli(capsys, "--keep-head", "0123456789abcdef")
    assert code == 0 and "nothing written" in out
    assert "no chain ends in a head beginning 0123456789abcdef" in out
    code, _out, err = _cli(capsys, "--apply", "--keep-head", "0123456789abcdef")
    assert code == 2 and "no chain ends in a head beginning 0123456789abcdef" in err
    assert {f: f.read_bytes() for f in lb.files()} == before and not (root / "repair").exists()
    code, _out, err = _cli(capsys, "--apply", "--keep-head", "xyz")  # not a hash at all
    assert code == 2 and "--keep-head" in err and not (root / "repair").exists()


def test_without_an_index_a_longer_stray_batch_is_kept_unless_told(root: Path, capsys):
    lb, after_a = _forked(root, a=3, b=6)  # the stray batch is the longer chain, as in life
    lb.index_path.unlink()
    code, out, _err = _cli(capsys)
    assert code == 0 and "main chain: 9 lines" in out  # rule (b) proposes the stray batch
    assert "--keep-head" in out and "safer" in out
    code, out, _err = _cli(capsys, "--apply", "--keep-head", after_a["head"])
    assert code == 0, out
    moved = next((root / "repair").glob("*-removed.jsonl")).read_bytes().splitlines(keepends=True)
    assert _raw_ids(moved) == [f"b:{i}" for i in range(6)]
    assert (lb.meta["seq"], lb.meta["head"]) == (after_a["seq"], after_a["head"])
    assert lb.verify()[2] == []
    for day in DAYS:
        assert not any(line["payload"]["raw_id"].startswith("b:") for line in lb.day_lines(day))


def test_keep_head_overrides_the_index(root: Path, capsys: pytest.CaptureFixture[str]):
    """Rule (a) would keep A; the owner says B, and B it is."""
    lb, _after_a = _forked(root, a=5, b=4)
    report = fork.diagnose(lb)
    b_head = report.segments[report.orphans[0]].head
    code, out, _err = _cli(capsys, "--apply", "--keep-head", b_head)
    assert code == 0, out
    moved = next((root / "repair").glob("*-removed.jsonl")).read_bytes().splitlines(keepends=True)
    assert _raw_ids(moved) == [f"a:{i}" for i in range(5)]
    assert lb.meta["head"] == b_head and lb.verify()[2] == []
