"""No command holds more than a bounded number of files open at once, however many month files
the record has. A record of a few decades has hundreds of month files, and macOS gives a process
256 open files by default: a reader that opened every month file at once (the chain-order merge
of `Logbook.lines` did) failed `doctor` and `verify` with `[Errno 24] Too many open files`.

Nothing here is real: the owner is the Oslo persona, who does not exist, and every line is a
synthetic note."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from logbook.core import store
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parent.parent
MONTHS = 25 * 12  # month files: more than macOS's default limit of 256 open files
LIMIT = 64  # the open-file limit the subprocess runs under; well under the month count
FIRST_YEAR = 2001
LAST_DAY = f"{FIRST_YEAR + 24}-12-15"  # a day of the last month, with lines of both passes


def _drafts(pass_no: int) -> list[dict[str, Any]]:
    """One note per month, in `at` order; a second pass sends the chain through every month file
    again, so chain order (seq) is not file order and a reader must merge the files."""
    drafts = []
    for n in range(MONTHS):
        year, month = FIRST_YEAR + n // 12, n % 12 + 1
        text = f"Ines Nordmann, note {pass_no} of {year}-{month:02d}"
        drafts.append(
            {
                "at": f"{year:04d}-{month:02d}-15T{7 + pass_no:02d}:30:00Z",
                "source": "manual",
                "kind": "note",
                "tier": 1,
                "payload": {"schema": "note/v1", "text": text},
            }
        )
    return drafts


@pytest.fixture(scope="module")
def record(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    """A record of MONTHS month files, each holding two lines appended in two passes."""
    root = tmp_path_factory.mktemp("many-months") / "Logbook"
    lb = Logbook.init(root, "Europe/Oslo")
    lb.append_many(_drafts(0))
    lb.append_many(_drafts(1))
    assert len(lb.files()) == MONTHS
    store.Index.open(lb).discard()  # the subprocess builds its own, under the limit
    return lb


def _run_limited(lb: Logbook, *args: str) -> subprocess.CompletedProcess[str]:
    """`logbook <args>` in a subprocess whose open-file limit is LIMIT, set inside the child."""
    driver = (
        "import resource, sys\n"
        f"resource.setrlimit(resource.RLIMIT_NOFILE, ({LIMIT}, {LIMIT}))\n"
        "from logbook.cli import main\n"
        "main(sys.argv[1:])\n"
    )
    env = {**os.environ, "LOGBOOK_HOME": str(lb.root), "PYTHONPATH": str(ROOT)}
    return subprocess.run(
        [sys.executable, "-c", driver, *args], env=env, capture_output=True, encoding="utf-8"
    )


@pytest.mark.skipif(sys.platform == "win32", reason="RLIMIT_NOFILE does not exist on Windows")
@pytest.mark.parametrize(
    "args",
    [
        ("doctor",),
        ("verify",),
        ("verify", "--progress"),
        ("index",),
        ("day", LAST_DAY),
        ("digest", LAST_DAY),
    ],
    ids=lambda args: " ".join(args),
)
def test_command_runs_under_a_small_open_file_limit(record: Logbook, args: tuple[str, ...]) -> None:
    r = _run_limited(record, *args)
    assert "Too many open files" not in r.stdout + r.stderr, r.stdout + r.stderr
    assert r.returncode == 0, r.stdout + r.stderr
    if args[0] == "verify":
        assert f"valid — {2 * MONTHS} lines" in r.stdout, r.stdout


@pytest.fixture
def open_files(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Counts the files `Path.open` has open at once; `peak` is the most at any moment."""
    counts = {"now": 0, "peak": 0}
    real_open = Path.open

    def counted_open(self: Path, *args: Any, **kwargs: Any) -> Any:
        fh = real_open(self, *args, **kwargs)
        counts["now"] += 1
        counts["peak"] = max(counts["peak"], counts["now"])
        real_close = fh.close

        def close() -> None:
            if not fh.closed:
                counts["now"] -= 1
            real_close()

        fh.close = close  # type: ignore[method-assign]
        return fh

    monkeypatch.setattr(Path, "open", counted_open)
    return counts


def test_readers_hold_a_bounded_number_of_files(record: Logbook, open_files: dict[str, int]) -> None:
    """The chain-order merge, the sorted fallback and the index's reads never hold more month
    files than `store.OPEN_FILES`, whatever the month count; and read every line regardless."""
    seqs = [line["seq"] for line in record.lines()]
    assert seqs == list(range(1, 2 * MONTHS + 1))
    assert [line["seq"] for line in record._lines_by_seq()] == seqs
    with record.index() as idx:
        places = [(f"logbook/{FIRST_YEAR + n // 12}/{n % 12 + 1:02d}.jsonl", 0) for n in range(MONTHS)]
        lines = idx.read(places)
    assert len(lines) == MONTHS
    assert open_files["peak"] <= store.OPEN_FILES + 2, open_files  # plus logbook.json, read once


def test_writers_hold_a_bounded_number_of_files(tmp_path: Path, open_files: dict[str, int]) -> None:
    """`append_many` over every month holds one month file open at a time; the rewrite `migrate`
    and `seal` share reads through one bounded set of handles and writes through another."""
    lb = Logbook.init(tmp_path / "Logbook", "Europe/Oslo")
    assert lb.append_many(_drafts(0)) == MONTHS
    assert lb.append_many(_drafts(1)) == MONTHS
    n, head, changed = lb._rewrite("rewritten", lambda line: line, False, None)
    assert (n, changed) == (2 * MONTHS, 0)
    assert head == lb.meta["head"]
    assert open_files["peak"] <= 2 * store.OPEN_FILES + 2, open_files  # read and write caches, logbook.json
