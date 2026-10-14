"""`logbook repair tail`: a process that dies between the fsync of an appended line and the replacement of
`logbook.json` leaves the files one line ahead of it (SPEC §3, write order). `verify` says so. `append` and
`append_many` then refuse under the writer lock, in one sentence naming `repair tail`, and write nothing:
the documented recovery before this (`repair index`, then append) wrote a second seq 2 and the record held
1, 2, 2. `repair tail` validates every line past the head `logbook.json` names (hash, link, seq, a sealed
line opened when the identity is here) and only then brings `logbook.json` forward and extends the index,
in that order; `--dry-run` lists what it would do; a tail line that does not verify makes it refuse and
change nothing. Synthetic Oslo persona; nobody in it exists."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.core import sealing
from logbook.core.index import Index
from logbook.core.store import LOCK_FILE, HeadMoved, Logbook, TailAhead

ROOT = Path(__file__).resolve().parents[1]
CONFORMANCE = ROOT / "conformance"
L1_HEAD = "58bfa9e704e3388d44d74e63f1d84765d24df79e92fce3b522fbef53b765d3df"  # sample-logbook, 32 lines
L2_HEAD = "0ab4c3e79bacc9a7c19d074094e81d1674fdf6967ceaf0d1711679e3c11481db"  # sample-logbook-sealed


def _note(i: int, tier: int = 1) -> dict[str, Any]:
    return {
        "at": f"2026-09-1{i % 3}T{7 + i:02d}:00:00Z",
        "source": "manual",
        "kind": "note",
        "tier": tier,
        "payload": {"schema": "note/v1", "text": f"synthetic note {i} from the marina"},
    }


class Crash(Exception):
    """The process is gone at this point: what `os._exit` does in the subprocess test, in-process."""


def _dies_before_logbook_json(mp: pytest.MonkeyPatch) -> None:
    """The reviewer's injection: the line is fsynced, then the process exits before `_save_meta`."""

    def gone(self: Logbook, meta: dict[str, Any]) -> None:
        raise Crash("exit before logbook.json is replaced")

    mp.setattr(Logbook, "_save_meta", gone)


def _lagging_append(lb: Logbook, draft: dict[str, Any]) -> None:
    with pytest.MonkeyPatch.context() as mp:
        _dies_before_logbook_json(mp)
        with pytest.raises(Crash):
            lb.append(**draft)


def _seqs(lb: Logbook) -> list[int]:
    """Every seq in the files, in file order: the bytes, never the index."""
    rows = [raw for f in lb.files() for raw in f.read_bytes().splitlines() if raw.strip()]
    return [int(json.loads(raw)["seq"]) for raw in rows]


def _snapshot(lb: Logbook) -> dict[str, bytes]:
    files = {f.relative_to(lb.root).as_posix(): f.read_bytes() for f in lb.files()}
    files["logbook.json"] = lb.meta_path.read_bytes()
    return files


def _cli(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    try:
        cli.main(list(args))
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
    return root


@pytest.fixture
def lagging(root: Path) -> Logbook:
    """A record of one line, indexed, whose second append fsynced its line and died before
    `logbook.json`: the files say seq 2, `logbook.json` says seq 1, the index describes seq 1."""
    lb = Logbook.init(root, "Europe/Oslo")
    lb.append(**_note(0))
    lb.index_rebuild()
    _lagging_append(lb, _note(1))
    return lb


# -- the finding, reproduced ----------------------------------------------------------------------------


def test_the_crash_leaves_the_files_one_line_ahead_and_verify_says_so(lagging: Logbook) -> None:
    lb = lagging
    assert _seqs(lb) == [1, 2] and lb.meta["seq"] == 1
    seq, head, errors = lb.verify()
    assert seq == 2
    was = lb.meta["head"][:12]
    assert errors == [f"logbook.json says seq=1 head={was}…, files say seq=2 head={head[:12]}…"]
    with Index.open(lb) as idx:  # the index never runs ahead of logbook.json
        assert idx.matches(lb.meta) and idx.by_seq(2) is None


def test_repair_index_does_not_mend_it_and_the_record_never_holds_1_2_2(
    lagging: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """The procedure recovery.md gave before: rebuild the index, then append. The rebuilt index held seq 2
    under a logbook.json that said seq 1, the next append wrote a second seq 2 and the index refused it.
    Now the append refuses; and `repair tail` after that rebuild sees an index that already holds the
    tail and builds it again rather than inserting seq 2 twice."""
    lb = lagging
    assert lb.index_rebuild() == 2
    with pytest.raises(TailAhead):
        lb.append(**_note(2))
    assert _seqs(lb) == [1, 2]
    code, out, err = _cli(capsys, "repair", "tail")
    assert code == 0, err
    assert "index rebuilt, 2 lines" in out and "valid — 2 lines" in out
    assert lb.append(**_note(2))["seq"] == 3 and _seqs(lb) == [1, 2, 3]
    assert lb.verify()[2] == []


# -- append refuses -------------------------------------------------------------------------------------


def test_append_refuses_in_one_sentence_naming_repair_tail_and_writes_nothing(lagging: Logbook) -> None:
    lb = lagging
    before = _snapshot(lb)
    with pytest.raises(TailAhead, match="`logbook repair tail`") as e:
        lb.append(**_note(2))
    assert "files" in str(e.value) and "seq 2" in str(e.value) and "seq 1" in str(e.value)
    assert "\n" not in str(e.value)
    assert isinstance(e.value, HeadMoved)  # the CLI says it in one line and exits 2, as it does for HeadMoved
    assert _snapshot(lb) == before
    with Index.open(lb) as idx:
        assert idx.matches(lb.meta) and idx.by_seq(2) is None
    assert not (lb.root / LOCK_FILE).exists()


def test_append_many_and_the_add_command_refuse_the_same_way(
    lagging: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = lagging
    before = _snapshot(lb)
    with pytest.raises(TailAhead, match="repair tail"):
        lb.append_many([_note(2), _note(3)])
    assert _snapshot(lb) == before
    drafts = tmp_path / "more.jsonl"
    drafts.write_text("".join(json.dumps(_note(i)) + "\n" for i in (2, 3)), encoding="utf-8")
    code, _out, err = _cli(capsys, "add", str(drafts))
    assert code == 2
    assert "add: the files are ahead of logbook.json" in err and "`logbook repair tail`" in err
    assert err.count("\n") == 1
    assert _snapshot(lb) == before
    assert not (lb.root / LOCK_FILE).exists()


def test_the_same_seq_under_another_head_refuses_too(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Not a lag: logbook.json names the files' seq but not their head. `append` refuses and `repair tail`
    has nothing to bring forward, so it refuses too and says to run `verify`."""
    lb = Logbook.init(root, "Europe/Oslo")
    lb.append(**_note(0))
    meta = lb.meta
    meta["head"] = "f" * 64
    lb.meta_path.write_text(json.dumps(meta) + "\n", encoding="utf-8")
    before = _snapshot(lb)
    with pytest.raises(TailAhead, match="repair tail"):
        lb.append(**_note(1))
    code, _out, err = _cli(capsys, "repair", "tail")
    assert code == 2 and "nothing was changed" in err and "logbook verify" in err
    assert _snapshot(lb) == before


# -- repair tail ----------------------------------------------------------------------------------------


def test_dry_run_lists_the_tail_and_writes_nothing(lagging: Logbook, capsys: pytest.CaptureFixture[str]):
    lb = lagging
    before = _snapshot(lb)
    tail_hash = str(lb.verify()[1])
    code, out, err = _cli(capsys, "repair", "tail", "--dry-run")
    assert code == 0, err
    assert "logbook.json says seq=1" in out and "1 line past it" in out
    assert "seq 2  logbook/2026/09.jsonl line 2" in out and tail_hash[:12] in out
    assert "would set logbook.json to seq=2" in out and "extend the index by 1 line" in out
    assert "nothing written" in out
    assert "synthetic note" not in out and "marina" not in out  # never a line's contents
    assert _snapshot(lb) == before
    with Index.open(lb) as idx:
        assert idx.matches(lb.meta) and idx.by_seq(2) is None


def test_repair_tail_brings_logbook_json_forward_and_append_then_writes_seq_3(
    lagging: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = lagging
    files_before = {f: f.read_bytes() for f in lb.files()}
    _seq, tail_head, _errors = lb.verify()
    code, out, err = _cli(capsys, "repair", "tail")
    assert code == 0, err
    assert "logbook.json: seq 2" in out and "index extended by 1 line" in out
    assert f"valid — 2 lines, head {tail_head}" in out
    assert {f: f.read_bytes() for f in lb.files()} == files_before  # no line touched
    meta = lb.meta
    assert (meta["seq"], meta["head"]) == (2, tail_head)
    assert lb.verify()[2] == []
    with Index.open(lb) as idx:
        assert idx.matches(meta) and idx.by_seq(2) is not None
    line = lb.append(**_note(2))
    assert line["seq"] == 3 and line["prev"] == tail_head
    seq, head, errors = lb.verify()
    assert (seq, head, errors) == (3, line["hash"], [])
    assert _seqs(lb) == [1, 2, 3]
    assert [r["seq"] for r in lb.day_lines("2026-09-12")] == [3]


def test_a_tail_of_several_lines_across_two_month_files(root: Path, capsys: pytest.CaptureFixture[str]):
    """`append_many` writes a batch to its month files, fsyncs each, then logbook.json: a crash there leaves
    a whole batch ahead, in chain order across the files."""
    lb = Logbook.init(root, "Europe/Oslo")
    lb.append(**_note(0))
    batch = [
        {**_note(1), "at": "2026-09-20T08:00:00Z"},
        {**_note(2), "at": "2026-10-02T08:00:00Z"},
        {**_note(3), "at": "2026-09-21T08:00:00Z"},
        {**_note(4), "at": "2026-10-03T08:00:00Z"},
    ]
    with pytest.MonkeyPatch.context() as mp:
        _dies_before_logbook_json(mp)
        with pytest.raises(Crash):
            lb.append_many(batch)
    assert lb.meta["seq"] == 1 and lb.verify()[0] == 5
    code, out, err = _cli(capsys, "repair", "tail", "--dry-run")
    assert code == 0, err
    listed = [line for line in out.splitlines() if line.startswith("  seq ")]
    assert [line.split()[1] for line in listed] == ["2", "3", "4", "5"]
    assert "logbook/2026/10.jsonl" in listed[1] and "logbook/2026/09.jsonl" in listed[2]
    code, out, err = _cli(capsys, "repair", "tail")
    assert code == 0, err
    seq, head, errors = lb.verify()
    assert (seq, errors) == (5, []) and lb.meta["head"] == head
    assert [r["seq"] for r in lb.day_lines("2026-10-02")] == [3]


def test_a_sound_record_has_nothing_to_repair(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    lb = Logbook.init(root, "Europe/Oslo")
    lb.append(**_note(0))
    before = _snapshot(lb)
    for flag in ((), ("--dry-run",)):
        code, out, _err = _cli(capsys, "repair", "tail", *flag)
        assert code == 0 and "nothing to repair" in out and "seq=1" in out
    assert _snapshot(lb) == before
    assert lb.append(**_note(1))["seq"] == 2


@pytest.mark.parametrize("state", ["current", "stale", "missing"])
def test_the_index_is_extended_when_current_rebuilt_when_stale_left_when_missing(
    lagging: Logbook, state: str, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = lagging
    if state == "stale":
        lb.set_timezone("UTC")  # a setting, not a line: the index was built under the other zone
    elif state == "missing":
        lb.index_path.unlink()
    code, out, err = _cli(capsys, "repair", "tail")
    assert code == 0, err
    said = {"current": "index extended by 1 line", "stale": "index rebuilt, 2 lines", "missing": "no index"}
    assert said[state] in out
    assert lb.index_path.exists() == (state != "missing")
    assert lb.verify()[2] == []
    assert [r["seq"] for r in lb.day_lines("2026-09-11")] == [2]  # the reader finds the line either way


@pytest.mark.parametrize("damage", ["text", "link", "torn"])
def test_a_tail_line_that_does_not_verify_makes_repair_tail_refuse_and_change_nothing(
    lagging: Logbook, damage: str, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = lagging
    path = lb.root / "logbook" / "2026" / "09.jsonl"
    rows = path.read_bytes().splitlines(keepends=True)
    if damage == "text":
        rows[1] = rows[1].replace(b"synthetic note 1", b"another note 1")
        said = "line 2: hash does not recompute; id "
    elif damage == "link":
        line = json.loads(rows[1])
        line["prev"] = "e" * 64
        rows[1] = (json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        said = "line 2: prev does not match previous hash; id "
    else:
        rows[1] = rows[1][: len(rows[1]) // 2]
        said = "logbook/2026/09.jsonl line 2: the file ends inside this line (cut short)"
    path.write_bytes(b"".join(rows))
    before = _snapshot(lb)
    for flag in (("--dry-run",), ()):
        code, out, err = _cli(capsys, "repair", "tail", *flag)
        assert code == 2, out
        assert err.startswith(f"repair tail: {said}") and err.rstrip().endswith("nothing was changed")
        assert err.count("\n") == 1
    assert _snapshot(lb) == before
    with Index.open(lb) as idx:
        assert idx.matches(lb.meta) and idx.by_seq(2) is None
    with pytest.raises(TailAhead, match="repair tail"):  # append still refuses: the files are still ahead
        lb.append(**_note(2))
    assert _snapshot(lb) == before


def test_a_second_seq_2_already_in_the_files_is_refused_not_adopted(lagging: Logbook, capsys) -> None:
    """A record the old procedure left at 1, 2, 2: a fork, `repair fork`'s case. `repair tail` must not pick
    one of the two and bring logbook.json to it."""
    lb = lagging
    path = lb.root / "logbook" / "2026" / "09.jsonl"
    rows = path.read_bytes().splitlines(keepends=True)
    line = json.loads(rows[1])
    line["id"], line["recorded_at"] = "0199e000-0000-7000-8000-000000000002", "2026-09-11T09:00:01Z"
    line["hash"] = "a" * 64
    path.write_bytes(b"".join(rows) + (json.dumps(line, sort_keys=True) + "\n").encode("utf-8"))
    assert _seqs(lb) == [1, 2, 2]
    before = _snapshot(lb)
    code, _out, err = _cli(capsys, "repair", "tail")
    assert code == 2 and "nothing was changed" in err
    assert _snapshot(lb) == before


def test_logbook_json_ahead_of_the_files_is_refused_never_rewound(root: Path, capsys) -> None:
    """No crash leaves this (SPEC §3); month files restored from an older backup under a newer logbook.json
    do. `repair tail` brings logbook.json forward only, and says so."""
    lb = Logbook.init(root, "Europe/Oslo")
    lb.append(**_note(0))
    lb.append(**_note(1))
    path = lb.root / "logbook" / "2026" / "09.jsonl"
    rows = path.read_bytes().splitlines(keepends=True)
    path.write_bytes(rows[0])
    before = _snapshot(lb)
    code, _out, err = _cli(capsys, "repair", "tail")
    assert code == 2
    assert "logbook.json says seq=2" in err and "files end at seq=1" in err and "nothing was changed" in err
    assert _snapshot(lb) == before


# -- sealed lines (RFC 0029) ------------------------------------------------------------------------------


@pytest.fixture
def sealed(root: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """A record that names two recipients, this machine's identity where LOGBOOK_IDENTITY_FILE points, one
    tier-1 line, indexed; then a tier-2 line, sealed on append, whose append died before logbook.json."""
    pairs = [sealing.generate_identity() for _ in range(2)]
    lb = Logbook.init(root, "Europe/Oslo")
    meta = lb.meta
    meta["recipients"] = [r for _, r in pairs]
    lb._save_meta(meta)
    path = root.parent / "keys" / "owner.txt"
    sealing.write_identity_file(path, pairs[0][0], "test")
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(path))
    lb = Logbook(root)
    lb.append(**_note(0))
    lb.index_rebuild()
    _lagging_append(lb, _note(1, tier=2))
    return lb


def test_a_sealed_tail_line_is_opened_against_its_digest_and_indexed_opened(
    sealed: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = sealed
    stored = json.loads(lb.files()[0].read_bytes().splitlines()[1])
    assert stored["payload"]["schema"] == "sealed/v1" and "marina" not in json.dumps(stored)
    code, out, err = _cli(capsys, "repair", "tail")
    assert code == 0, err
    assert "index extended by 1 line" in out
    assert lb.meta["seq"] == 2 and lb.verify(keyed=True)[2] == []
    (line,) = lb.day_lines("2026-09-11")
    assert lb.opened(line)["payload"]["text"] == "synthetic note 1 from the marina"


def test_a_sealed_tail_line_whose_bytes_do_not_open_is_refused_with_the_identity(
    sealed: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = sealed
    path = lb.files()[0]
    rows = path.read_bytes().splitlines(keepends=True)
    line = json.loads(rows[1])
    line["payload"]["digest"] = "0" * 64  # inside the hash: the chain says the line changed
    line["hash"] = "0" * 64
    rows[1] = (json.dumps(line, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(b"".join(rows))
    before = _snapshot(lb)
    code, _out, err = _cli(capsys, "repair", "tail")
    assert code == 2 and "line 2: hash does not recompute" in err and "nothing was changed" in err
    assert _snapshot(lb) == before


# -- the write order (SPEC §3): line, logbook.json, then the index ------------------------------------------


def test_a_crash_after_logbook_json_leaves_the_index_behind_and_the_next_reader_rebuilds(root: Path) -> None:
    """The index is written after logbook.json, so a crash leaves at most the files ahead, never the
    index or logbook.json ahead of the files; a stale index is rebuilt by the next reader."""
    lb = Logbook.init(root, "Europe/Oslo")
    lb.append(**_note(0))
    lb.index_rebuild()

    def gone(self: Index, *args: Any, **kwargs: Any) -> None:
        raise Crash("exit before the index is extended")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Index, "add", gone)
        with pytest.raises(Crash):
            lb.append(**_note(1))
    assert lb.meta["seq"] == 2 and lb.verify()[2] == []
    with Index.open(lb) as idx:
        assert not idx.matches(lb.meta) and idx.by_seq(2) is None
    assert [r["seq"] for r in lb.day_lines("2026-09-11")] == [2]
    assert lb.append(**_note(2))["seq"] == 3 and _seqs(lb) == [1, 2, 3]


# -- two processes: the reviewer's shape, and the lock ------------------------------------------------------

DYING_WRITER = """
import os
from logbook.core.store import Logbook
lb = Logbook.find()
def gone(self, meta):
    os._exit(0)  # the line is on disk; the process is gone before logbook.json is replaced
Logbook._save_meta = gone
lb.append(at="2026-09-11T08:00:00Z", source="manual", kind="note", tier=1,
          payload={"schema": "note/v1", "text": "synthetic note from the other process"})
"""

SLOW_WRITER = """
import time
from logbook.core import store
from logbook.core.store import Logbook
store.COMMAND = "sync immich"
lb = Logbook.find()
def drafts():
    for i in range(4):
        time.sleep(0.4)
        yield {"at": f"2026-09-2{i}T07:00:00Z", "source": "immich", "kind": "photo", "tier": 1,
               "payload": {"schema": "photo/v1", "raw_id": f"slow:{i}"}}
print(lb.append_many(drafts()))
"""


def _env(root: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"}
    env.update({"LOGBOOK_HOME": str(root), "PYTHONPATH": str(ROOT)})
    return env


def _logbook(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "logbook.cli", *args],
        env=_env(root),
        capture_output=True,
        encoding="utf-8",
        timeout=60,
    )


def test_a_process_that_exits_before_logbook_json_is_recovered_by_repair_tail_in_the_cli(
    root: Path, tmp_path: Path
) -> None:
    """The finding end to end, in processes: the writer dies after the fsync; verify reports the lag and the
    stale lock stays; `add` takes the lock over and refuses naming `repair tail`; `repair tail` brings
    logbook.json forward; `add` then writes seq 3; the files never hold 1, 2, 2."""
    lb = Logbook.init(root, "Europe/Oslo")
    lb.append(**_note(0))
    dying = subprocess.run(
        [sys.executable, "-c", DYING_WRITER],
        env=_env(root),
        capture_output=True,
        encoding="utf-8",
        timeout=60,
    )
    assert dying.returncode == 0, dying.stderr
    assert (root / LOCK_FILE).exists()  # the lock of a process that is gone
    assert _seqs(lb) == [1, 2] and lb.meta["seq"] == 1
    verify = _logbook(root, "verify")
    assert verify.returncode == 1 and "logbook.json says seq=1" in verify.stdout
    drafts = tmp_path / "next.jsonl"
    drafts.write_text(json.dumps(_note(2)) + "\n", encoding="utf-8")
    add = _logbook(root, "add", str(drafts))
    assert add.returncode == 2, add.stdout
    assert "stale lock" in add.stderr and "taking it over" in add.stderr
    assert "`logbook repair tail`" in add.stderr and "nothing was written" in add.stderr
    assert _seqs(lb) == [1, 2] and lb.meta["seq"] == 1
    assert not (root / LOCK_FILE).exists()
    repaired = _logbook(root, "repair", "tail")
    assert repaired.returncode == 0, repaired.stderr
    assert "logbook.json: seq 2" in repaired.stdout and "valid — 2 lines" in repaired.stdout
    add = _logbook(root, "add", str(drafts))
    assert add.returncode == 0, add.stderr
    assert _seqs(lb) == [1, 2, 3]
    verify = _logbook(root, "verify")
    assert verify.returncode == 0 and verify.stdout.startswith("valid — 3 lines")


def test_repair_tail_holds_the_writer_lock(root: Path) -> None:
    lb = Logbook.init(root, "Europe/Oslo")
    lb.append(**_note(0))
    slow = subprocess.Popen(
        [sys.executable, "-c", SLOW_WRITER],
        env=_env(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
    )
    try:
        deadline = time.monotonic() + 20
        while not (root / LOCK_FILE).exists():
            assert slow.poll() is None and time.monotonic() < deadline, slow.communicate()
            time.sleep(0.05)
        refused = _logbook(root, "--no-wait", "repair", "tail")
        assert refused.returncode == 2
        assert "another logbook command is writing to this record (sync immich" in refused.stderr
    finally:
        out, err = slow.communicate(timeout=60)
    assert slow.returncode == 0 and out.strip() == "4", err
    assert lb.verify()[2] == [] and lb.meta["seq"] == 5


# -- conformance: the published heads hold, and a lag on either sample is brought forward to them -----------


@pytest.mark.parametrize(
    ("sample", "head"), [("sample-logbook", L1_HEAD), ("sample-logbook-sealed", L2_HEAD)], ids=["L1", "L2"]
)
def test_the_conformance_heads_hold_and_a_lagging_copy_is_brought_forward(
    sample: str,
    head: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    assert Logbook(CONFORMANCE / sample).verify() == (32, head, [])
    copy = tmp_path / "record"
    shutil.copytree(CONFORMANCE / sample, copy)
    monkeypatch.setenv("LOGBOOK_HOME", str(copy))
    lb = Logbook(copy)
    _lagging_append(lb, {**_note(0), "at": "2026-03-08T07:00:00Z"})  # a tier-1 line needs no identity
    seq, new_head, errors = lb.verify()
    assert seq == 33
    assert errors == [f"logbook.json says seq=32 head={head[:12]}…, files say seq=33 head={new_head[:12]}…"]
    code, _out, err = _cli(capsys, "repair", "tail")
    assert code == 0, err
    assert lb.meta["seq"] == 33 and lb.meta["head"] == new_head
    assert lb.verify() == (33, new_head, [])
    assert next(line for line in lb.lines() if line["seq"] == 33)["prev"] == head
    assert Logbook(CONFORMANCE / sample).verify() == (32, head, [])  # the committed sample is untouched
