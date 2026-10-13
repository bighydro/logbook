"""The writers of RFC 0036's owner lines: `logbook goal add | review | list | import` and `logbook
chapter open | close | list`. Each writes exactly its profile's line (held here byte for byte to the
example on the profile's page under `rfcs/`), tier 2 and `source` `manual`, through
`Logbook.append`; takes the writer lock for the whole command; and reads the head again before it
appends, writing nothing when it moved. Ines Nordmann of Oslo, her boat and her goals are synthetic;
nobody in them exists."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.core import chapter, goals, store
from logbook.core.chain import canonical_json
from logbook.core.store import LOCK_FILE, Logbook

ROOT = Path(__file__).resolve().parents[1]
TZ = "Europe/Oslo"
FIRST_GOAL = "019cadd3-6bc0-7dcd-9133-000000000301"
SECOND_GOAL = "019cadd3-6bc0-7dcd-9133-000000000302"
FIRST_TEXT = (
    "Sail the boat to Lofoten and back in one summer, without a single night in a marina I didn't choose."
)
SECOND_TEXT = "Sail to Lofoten and back between June and August, at anchor more nights than not."
NOTE = "Engine gone in Bodø on the 9th. Towed home. Next summer."
SUMMER = "The Lofoten summer"
SUMMER_RULES = (
    "Every night at anchor counts. A marina counts against. The engine is not the point; the boat is."
)
ASHORE = "Ashore, fixing things"
ASHORE_RULES = "What counts: the engine rebuilt, the mooring sorted, one weekend a month on the water anyway."


def examples(page: str) -> list[dict[str, Any]]:
    """The lines of the `json` blocks of a profile's page, in order: what the writer must write."""
    text = (ROOT / "rfcs" / page).read_text(encoding="utf-8")
    return [json.loads(block) for block in re.findall(r"```json\n(.*?)```", text, re.S)]


def same_bytes(line: dict[str, Any], example: dict[str, Any]) -> None:
    """The written line, cut to the fields the example shows, has the example's canonical bytes."""
    assert canonical_json({k: line[k] for k in example}) == canonical_json(example)


def pin(monkeypatch: pytest.MonkeyPatch, stamp: str) -> None:
    """The writers' clock reads `stamp`."""
    instant = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    monkeypatch.setattr(goals, "now", lambda: instant)


def ids(monkeypatch: pytest.MonkeyPatch, *wanted: str) -> None:
    """The next lines get these ids, in order (the RFC examples name each other by id)."""
    queue = list(wanted)
    real = store.uuid7
    monkeypatch.setattr(store, "uuid7", lambda: queue.pop(0) if queue else real())


def run(*args: str) -> tuple[int, str, str]:
    """`logbook <args>` in this process: (exit status, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            cli.main(list(args))
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
    return code, out.getvalue(), err.getvalue()


def lines(lb: Logbook, kind: str) -> list[dict[str, Any]]:
    return [line for line in lb.lines() if line["kind"] == kind]


def after(lb: Logbook, seq: int) -> list[str]:
    """The kinds of the lines written after `seq`, in chain order."""
    return [line["kind"] for line in lb.lines() if line["seq"] > seq]


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "Logbook", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    return lb


def write_the_goals(monkeypatch: pytest.MonkeyPatch) -> None:
    """The two goal lines of goal/v1's example: the year's goal in January, reworded in March."""
    pin(monkeypatch, "2026-01-04T10:15:00Z")
    ids(monkeypatch, FIRST_GOAL)
    code, _out, err = run("goal", "add", FIRST_TEXT, "--horizon", "year", "--from", "2026-01-01")
    assert code == 0, err
    pin(monkeypatch, "2026-03-15T08:40:00Z")
    ids(monkeypatch, SECOND_GOAL)
    code, _out, err = run(
        "goal", "add", SECOND_TEXT, "--horizon", "year", "--from", "2026-01-01", "--until", "2026-12-31",
        "--supersedes", FIRST_GOAL,
    )  # fmt: skip
    assert code == 0, err


def write_the_review(monkeypatch: pytest.MonkeyPatch) -> tuple[int, str, str]:
    """review/v1's example: in October, the sailing goal let go at the end of August."""
    pin(monkeypatch, "2026-10-11T18:30:00Z")
    return run(
        "goal", "review", SECOND_GOAL, "let-go", "--period", "month", "--at", "2026-08-31T20:00:00Z",
        "--note", NOTE,
    )  # fmt: skip


def write_the_chapters(monkeypatch: pytest.MonkeyPatch) -> None:
    """chapter/v1's two examples, named the same evening in September."""
    pin(monkeypatch, "2026-09-06T17:20:00Z")
    code, _out, err = run(
        "chapter", "open", SUMMER, "--from", "2026-06-20", "--to", "2026-08-09", "--rules", SUMMER_RULES
    )
    assert code == 0, err
    pin(monkeypatch, "2026-09-06T17:25:00Z")
    code, _out, err = run("chapter", "open", ASHORE, "--from", "2026-08-10", "--rules", ASHORE_RULES)
    assert code == 0, err


# -- each writer's line, byte for byte ----------------------------------------------------------------------


def test_goal_add_writes_the_two_lines_of_the_goal_page(lb: Logbook, monkeypatch: pytest.MonkeyPatch):
    write_the_goals(monkeypatch)
    written = lines(lb, "goal")
    first, second = examples("0036-goal-v1.md")
    same_bytes(written[0], first)
    same_bytes(written[1], second)
    assert [line["id"] for line in written] == [FIRST_GOAL, SECOND_GOAL]
    assert [line["recorded_at"] for line in written] == ["2026-01-04T10:15:00Z", "2026-03-15T08:40:00Z"]
    assert lb.verify()[2] == []


def test_goal_review_writes_the_line_of_the_review_page(lb: Logbook, monkeypatch: pytest.MonkeyPatch):
    write_the_goals(monkeypatch)
    code, out, err = write_the_review(monkeypatch)
    assert code == 0, err
    (written,) = lines(lb, "review")
    (example,) = examples("0036-review-v1.md")
    same_bytes(written, example)
    assert written["recorded_at"] == "2026-10-11T18:30:00Z"  # the page's prose: when it was written
    assert written["payload"]["disposition"] == "let go"  # the owner's phrase, with its space
    assert f"#{written['seq']}" in out and "let go" in out and SECOND_TEXT in out


def test_chapter_open_writes_the_two_lines_of_the_chapter_page(lb: Logbook, monkeypatch: pytest.MonkeyPatch):
    write_the_chapters(monkeypatch)
    written = lines(lb, "chapter")
    first, second = examples("0036-chapter-v1.md")
    same_bytes(written[0], first)
    same_bytes(written[1], second)


def test_chapter_close_writes_every_field_again_with_to_and_supersedes(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
):
    write_the_chapters(monkeypatch)
    pin(monkeypatch, "2026-10-01T09:00:00Z")
    code, out, err = run("chapter", "close", "--to", "2026-09-30")
    assert code == 0, err
    opened, closed = lines(lb, "chapter")[1:]
    assert closed["payload"] == {
        "schema": "chapter/v1",
        "name": ASHORE,
        "from": "2026-08-10",
        "to": "2026-09-30",
        "rules": ASHORE_RULES,
        "supersedes": opened["id"],
    }
    assert (closed["tier"], closed["source"], closed["at"]) == (2, "manual", "2026-10-01T09:00:00Z")
    assert ASHORE in out and "2026-09-30" in out


def test_every_line_is_tier_2_and_manual_and_chains(lb: Logbook, monkeypatch: pytest.MonkeyPatch):
    write_the_goals(monkeypatch)
    write_the_review(monkeypatch)
    write_the_chapters(monkeypatch)
    written = [line for line in lb.lines()]
    assert {(line["kind"], line["tier"], line["source"]) for line in written} == {
        ("goal", 2, "manual"),
        ("review", 2, "manual"),
        ("chapter", 2, "manual"),
    }
    assert lb.verify()[2] == []
    assert not (lb.root / LOCK_FILE).exists()


# -- the rules a writer keeps -------------------------------------------------------------------------------


def test_a_second_review_of_the_goal_for_the_period_on_the_day_writes_nothing(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
):
    write_the_goals(monkeypatch)
    assert write_the_review(monkeypatch)[0] == 0
    seq = lb.meta["seq"]
    pin(monkeypatch, "2026-10-12T07:00:00Z")
    code, out, _err = run(  # the earlier line of the chain, the same month, the same local day
        "goal", "review", FIRST_GOAL, "done", "--period", "month", "--at", "2026-08-31T21:00:00+02:00"
    )
    assert code == 0 and "nothing was written" in out and "already" in out
    assert lb.meta["seq"] == seq
    code, _out, err = run(  # another period on the same day is another verdict
        "goal", "review", FIRST_GOAL, "stalled", "--period", "year", "--at", "2026-08-31"
    )
    assert code == 0, err
    assert lb.meta["seq"] == seq + 1


@pytest.mark.parametrize(
    ("args", "said"),
    [
        (("let-go", "--at", "2026-10-13T12:00:00Z"), "in the future"),
        (("let-go", "--at", "2026-10-12"), "in the future"),
        (("let-go", "--at", "2025-12-31"), "before the goal's first day, 2026-01-01"),
        (("let-go", "--at", "31 August"), "neither a local day"),
        (("let-go", "--period", "fortnight"), "invalid choice"),
        (("gave-up",), "'gave-up' is not a disposition; a goal is advancing, stalled, done, let-go or"),
    ],
)
def test_a_review_the_profile_refuses_writes_nothing(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, args: tuple[str, ...], said: str
):
    write_the_goals(monkeypatch)
    pin(monkeypatch, "2026-10-11T18:30:00Z")
    seq = lb.meta["seq"]
    code, _out, err = run("goal", "review", SECOND_GOAL, *args)
    assert code == 2 and said in err, err
    assert lb.meta["seq"] == seq


def test_a_review_names_a_goal_line_by_id_or_seq_and_never_a_retracted_one(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
):
    write_the_goals(monkeypatch)
    pin(monkeypatch, "2026-10-11T18:30:00Z")
    code, _out, err = run("goal", "review", "019cadd3-6bc0-7dcd-9133-000000000999", "done")
    assert code == 2 and "is not a goal line" in err
    code, _out, err = run("goal", "review", "#2", "advancing", "--at", "2026-06-30")
    assert code == 0, err
    review = lines(lb, "review")[0]
    assert review["payload"]["goal"] == SECOND_GOAL and review["payload"]["period"] == "year"
    assert review["at"] == "2026-06-30T21:59:00Z"  # a local day: its last minute, 23:59 in Oslo
    lb.retract(1, "written twice")
    code, _out, err = run("goal", "review", FIRST_GOAL, "done")
    assert code == 2 and "retracted" in err


def test_a_review_given_today_is_now(lb: Logbook, monkeypatch: pytest.MonkeyPatch):
    write_the_goals(monkeypatch)
    pin(monkeypatch, "2026-10-11T08:00:00Z")
    code, _out, err = run("goal", "review", SECOND_GOAL, "stalled", "--at", "2026-10-11")
    assert code == 0, err
    assert lines(lb, "review")[0]["at"] == "2026-10-11T08:00:00Z"


def test_goal_add_refuses_what_the_profile_does_not_allow(lb: Logbook, monkeypatch: pytest.MonkeyPatch):
    write_the_goals(monkeypatch)
    seq = lb.meta["seq"]
    for args, said in [
        (("--horizon", "month"), "invalid choice"),
        (("--horizon", "year", "--from", "2026-03-01", "--until", "2026-02-01"), "before --from"),
        (("--horizon", "year", "--from", "1 March"), "not a local day"),
        (("--horizon", "year", "--supersedes", FIRST_GOAL), "superseded by"),
        (("--horizon", "year", "--supersedes", "no-such-goal"), "is not a goal line"),
    ]:
        code, _out, err = run("goal", "add", "Learn to splice a rope.", *args)
        assert code == 2 and said in err, (args, err)
    code, _out, err = run("goal", "add", "   ", "--horizon", "life")
    assert code == 2 and "empty" in err
    assert lb.meta["seq"] == seq


def test_goal_add_without_from_starts_today_in_the_record_s_day(lb: Logbook, monkeypatch: pytest.MonkeyPatch):
    lb.set_meta(day_start="06:00")
    pin(monkeypatch, "2026-10-13T03:30:00Z")  # 05:30 in Oslo: still the 12th, the owner's day
    code, _out, err = run("goal", "add", "Rebuild the engine before May.", "--horizon", "quarter")
    assert code == 0, err
    assert lines(lb, "goal")[0]["payload"]["from"] == "2026-10-12"


def test_chapter_open_refuses_an_overlap_naming_the_chapter(lb: Logbook, monkeypatch: pytest.MonkeyPatch):
    write_the_chapters(monkeypatch)
    seq = lb.meta["seq"]
    code, _out, err = run("chapter", "open", "The yard", "--from", "2026-09-01")
    assert code == 2 and f"overlaps {ASHORE}" in err and "close it first" in err
    code, _out, err = run("chapter", "open", "June", "--from", "2026-06-01", "--to", "2026-06-25")
    assert code == 2 and f"overlaps {SUMMER}" in err
    code, out, _err = run("chapter", "open", SUMMER, "--from", "2026-06-20")
    assert code == 0 and "already" in out and "nothing was written" in out
    assert lb.meta["seq"] == seq
    code, _out, err = run("chapter", "open", "June", "--from", "2026-06-01", "--to", "2026-06-19")
    assert code == 0, err


def test_chapter_close_with_nothing_open_writes_nothing(lb: Logbook, monkeypatch: pytest.MonkeyPatch):
    pin(monkeypatch, "2026-09-06T17:20:00Z")
    code, _out, err = run("chapter", "close")
    assert code == 2 and "no chapter is open" in err
    run("chapter", "open", ASHORE, "--from", "2026-08-10")
    code, _out, err = run("chapter", "close", "--to", "2026-08-01")
    assert code == 2 and "before" in err
    assert len(lines(lb, "chapter")) == 1
    code, _out, err = run("chapter", "close")  # today, in the record's day
    assert code == 0, err
    assert lines(lb, "chapter")[-1]["payload"]["to"] == "2026-09-06"
    assert run("chapter", "close")[0] == 2  # closed now: nothing open


# -- the head, read again ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("module", "hook", "args"),
    [
        (goals, "validate", ("goal", "add", "Learn to splice a rope.", "--horizon", "year")),
        (goals, "validate_review", ("goal", "review", SECOND_GOAL, "advancing")),
        (chapter, "validate", ("chapter", "open", "Winter", "--from", "2026-01-01", "--to", "2026-01-31")),
        (chapter, "validate", ("chapter", "close")),
    ],
)
def test_a_head_that_moved_under_the_writer_is_head_moved_and_nothing_is_written(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, module: Any, hook: str, args: tuple[str, ...]
):
    write_the_goals(monkeypatch)
    write_the_chapters(monkeypatch)
    pin(monkeypatch, "2026-10-11T18:30:00Z")
    real = getattr(module, hook)

    def moved(payload: Any) -> list[str]:
        other = Logbook(lb.root)  # a writer that ignored the lock, in this process: the lock re-enters
        other.append("2026-10-11T18:00:00Z", "manual", "note", 2, {"schema": "note/v1", "text": "Late."})
        return real(payload)

    monkeypatch.setattr(module, hook, moved)
    seq = lb.meta["seq"]
    code, _out, err = run(*args)
    assert code == 2 and "head moved" in err and "nothing was written" in err, err
    assert lb.meta["seq"] == seq + 1 and after(lb, seq) == ["note"]
    assert not (lb.root / LOCK_FILE).exists()


# -- the lock -----------------------------------------------------------------------------------------------

SLOW_WRITER = """
import sys, time
from logbook.core import store
from logbook.core.store import Logbook
store.COMMAND = "sync immich"
lb = Logbook.find()
def drafts():
    for i in range({n}):
        time.sleep({pause})
        yield {{"at": f"2026-09-2{{i % 3}}T07:{{i % 60:02d}}:00Z", "source": "immich", "kind": "photo",
               "tier": 1, "payload": {{"schema": "photo/v1", "raw_id": f"slow:{{i}}"}}}}
print(lb.append_many(drafts()))
"""


def _env(root: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"}
    env.update({"LOGBOOK_HOME": str(root), "PYTHONPATH": str(ROOT)})
    return env


def _slow_writer(root: Path, n: int = 6, pause: float = 0.4) -> subprocess.Popen[str]:
    """Another process that holds the writer lock for `n * pause` seconds."""
    proc = subprocess.Popen(
        [sys.executable, "-c", SLOW_WRITER.format(n=n, pause=pause)],
        env=_env(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
    )
    lock = root / LOCK_FILE
    deadline = time.monotonic() + 20
    while not lock.exists():
        if proc.poll() is not None or time.monotonic() > deadline:
            out, err = proc.communicate()
            raise AssertionError(f"the slow writer did not take the lock: {out!r} {err!r}")
        time.sleep(0.05)
    return proc


def _logbook(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "logbook.cli", *args],
        env=_env(root),
        capture_output=True,
        encoding="utf-8",
        timeout=60,
    )


def test_a_goal_waits_for_the_writer_before_it_and_chains_after_its_batch(lb: Logbook, tmp_path: Path):
    slow = _slow_writer(lb.root)
    added = _logbook(lb.root, "goal", "add", "Learn to splice a rope.", "--horizon", "quarter")
    out, err = slow.communicate(timeout=60)
    assert slow.returncode == 0 and out.strip() == "6", (out, err)
    assert added.returncode == 0, added.stderr
    assert "another logbook command is writing to this record (sync immich" in added.stderr
    assert "waiting" in added.stderr
    kinds = [line["kind"] for line in lb.lines()]
    assert kinds == ["photo"] * 6 + ["goal"]  # the slow writer's batch whole, then the goal
    assert lb.verify()[2] == []
    assert not (lb.root / LOCK_FILE).exists()


@pytest.mark.parametrize(
    "args",
    [
        ("goal", "add", "Learn to splice a rope.", "--horizon", "quarter"),
        ("goal", "review", "1", "advancing"),
        ("chapter", "open", "The yard", "--from", "2026-10-01"),
        ("chapter", "close"),
        ("goal", "import", "GOALS"),
    ],
)
def test_no_wait_refuses_every_writer_with_exit_2_and_nothing_written(
    lb: Logbook, tmp_path: Path, args: tuple[str, ...]
):
    lb.append("2026-01-04T10:15:00Z", "manual", "goal", 2, {"schema": "goal/v1", "text": FIRST_TEXT,
              "horizon": "year", "from": "2026-01-01"})  # fmt: skip
    lb.append("2026-09-06T17:25:00Z", "manual", "chapter", 2, {"schema": "chapter/v1", "name": ASHORE,
              "from": "2026-08-10", "rules": ""})  # fmt: skip
    path = tmp_path / "goals.txt"
    path.write_text("Rebuild the engine. | quarter\n", encoding="utf-8")
    seq = lb.meta["seq"]
    slow = _slow_writer(lb.root)
    refused = _logbook(lb.root, "--no-wait", *[str(path) if arg == "GOALS" else arg for arg in args])
    assert refused.returncode == 2, refused.stdout + refused.stderr
    assert "another logbook command is writing to this record (sync immich" in refused.stderr
    assert "not waiting" in refused.stderr
    slow.communicate(timeout=60)
    assert slow.returncode == 0
    assert after(lb, seq) == ["photo"] * 6


# -- the import ---------------------------------------------------------------------------------------------

GOALS_FILE = """\
# Ines, written down in October for the year so far
Sail to Lofoten and back. | year | 2026-01-01
Rebuild the engine. | quarter | 2026-07-01

Read one book a month.
Keep the boat.  |  | 2026-03-01
"""


def test_goal_import_writes_one_goal_per_line_with_its_columns(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "goals.txt"
    path.write_text(GOALS_FILE, encoding="utf-8")
    pin(monkeypatch, "2026-10-11T18:30:00Z")
    code, out, err = run("goal", "import", str(path), "--horizon", "life", "--from", "2026-01-01")
    assert code == 0, err
    written = lines(lb, "goal")
    assert [line["payload"] for line in written] == [
        {"schema": "goal/v1", "text": "Sail to Lofoten and back.", "horizon": "year", "from": "2026-01-01"},
        {"schema": "goal/v1", "text": "Rebuild the engine.", "horizon": "quarter", "from": "2026-07-01"},
        {"schema": "goal/v1", "text": "Read one book a month.", "horizon": "life", "from": "2026-01-01"},
        {"schema": "goal/v1", "text": "Keep the boat.", "horizon": "life", "from": "2026-03-01"},
    ]
    assert {(line["tier"], line["source"], line["at"]) for line in written} == {
        (2, "manual", "2026-10-11T18:30:00Z")
    }
    assert lines(lb, "review") == []
    assert "4 goals" in out
    assert lb.verify()[2] == []


def test_goal_import_with_review_applies_one_verdict_to_every_goal(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "goals.txt"
    path.write_text(GOALS_FILE, encoding="utf-8")
    pin(monkeypatch, "2026-10-11T18:30:00Z")
    code, out, err = run(
        "goal", "import", str(path), "--horizon", "year", "--from", "2026-01-01",
        "--review", "let-go", "--at", "2026-08-31", "--note", NOTE,
    )  # fmt: skip
    assert code == 0, err
    written, reviews = lines(lb, "goal"), lines(lb, "review")
    assert [r["payload"]["goal"] for r in reviews] == [g["id"] for g in written]
    assert {r["at"] for r in reviews} == {"2026-08-31T21:59:00Z"}  # 23:59 on the 31st in Oslo
    assert {r["recorded_at"] for r in reviews} == {"2026-10-11T18:30:00Z"}
    assert [r["payload"]["period"] for r in reviews] == ["year", "quarter", "year", "year"]
    assert {r["payload"]["disposition"] for r in reviews} == {"let go"}
    assert {r["payload"]["note"] for r in reviews} == {NOTE}
    assert "4 goals" in out and "4 reviews" in out
    assert [line["kind"] for line in lb.lines()] == ["goal"] * 4 + ["review"] * 4
    code, out, _err = run("goal", "list", "--open")
    assert code == 0 and "0 open" in out


@pytest.mark.parametrize(
    ("text", "args", "said"),
    [
        ("Sail.\nRebuild. | month\n", ("--horizon", "year"), "line 2: horizon 'month'"),
        ("Sail.\n", (), "line 1: no horizon"),
        ("Sail. | year | June\n", (), "line 1: from 'June'"),
        ("Sail. | year | 2026-01-01 | x\n", (), "line 1: more than three columns"),
        ("# nothing\n\n", ("--horizon", "year"), "no goal in it"),
        (
            "Sail. | year | 2026-01-01\nRebuild. | quarter | 2026-09-01\n",
            ("--review", "let-go", "--at", "2026-08-31"),
            "line 2: --at 2026-08-31 is before the goal's first day, 2026-09-01",
        ),
        ("Sail. | year\n", ("--at", "2026-08-31"), "go with --review"),
    ],
)
def test_goal_import_checks_every_line_before_it_writes_any(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str, args: tuple[str, ...], said: str
):
    path = tmp_path / "goals.txt"
    path.write_text(text, encoding="utf-8")
    pin(monkeypatch, "2026-10-11T18:30:00Z")
    code, _out, err = run("goal", "import", str(path), *args)
    assert code == 2 and said in err, err
    assert lb.meta["seq"] == 0


def test_goal_import_dry_run_prints_and_writes_nothing(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "goals.txt"
    path.write_text(GOALS_FILE, encoding="utf-8")
    pin(monkeypatch, "2026-10-11T18:30:00Z")
    code, out, err = run(
        "goal", "import", str(path), "--horizon", "year", "--from", "2026-01-01", "--review", "done",
        "--at", "2026-09-30", "--dry-run",
    )  # fmt: skip
    assert code == 0, err
    assert "Rebuild the engine." in out and "would write 4 goals and 4 reviews" in out
    assert lb.meta["seq"] == 0


def test_goal_import_reads_a_file_written_on_windows(lb: Logbook, tmp_path: Path, monkeypatch):
    path = tmp_path / "goals.txt"
    path.write_bytes(
        b"\xef\xbb\xbfSail to Lofoten and back. | year | 2026-01-01\r\nKeep the boat. | life\r\n"
    )
    pin(monkeypatch, "2026-10-11T18:30:00Z")
    code, _out, err = run("goal", "import", str(path))
    assert code == 0, err
    assert [g["payload"]["text"] for g in lines(lb, "goal")] == [
        "Sail to Lofoten and back.",
        "Keep the boat.",
    ]


# -- the listings -------------------------------------------------------------------------------------------


def test_goal_list_shows_each_standing_goal_with_its_latest_review(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
):
    write_the_goals(monkeypatch)
    pin(monkeypatch, "2026-06-30T19:00:00Z")
    run("goal", "review", FIRST_GOAL, "advancing", "--period", "month")  # on the earlier line: one goal
    write_the_review(monkeypatch)
    pin(monkeypatch, "2026-10-11T19:00:00Z")
    run("goal", "add", "Learn to splice a rope.", "--horizon", "quarter", "--from", "2026-10-01")
    code, out, err = run("goal", "list")
    assert code == 0, err
    assert out.splitlines()[0] == "2 goals · 1 open"
    assert FIRST_TEXT not in out  # superseded: the standing goal is the reworded one
    assert SECOND_TEXT in out and "let go 2026-08-31 · month · " + NOTE in out
    assert "unreviewed" in out
    code, out, _err = run("goal", "list", "--json")
    found = json.loads(out)
    (sail, rope) = found["goals"]
    assert (sail["line"], sail["state"], sail["review"]["disposition"]) == (SECOND_GOAL, "let go", "let go")
    assert sail["review"]["recorded_at"] == "2026-10-11T18:30:00Z" and sail["supersedes"] == FIRST_GOAL
    assert (rope["state"], rope["review"]) == ("open", None)
    code, out, _err = run("goal", "list", "--open")
    assert "Learn to splice a rope." in out and SECOND_TEXT not in out


def test_chapter_list_shows_each_standing_chapter_and_the_one_today_is_in(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
):
    write_the_chapters(monkeypatch)
    code, out, err = run("chapter", "list")
    assert code == 0, err
    rows = out.splitlines()
    assert SUMMER in rows[0] and f"2026-06-20 {chapter.EN_DASH} 2026-08-09" in rows[0]
    assert rows[1].strip() == SUMMER_RULES
    assert ASHORE in rows[2] and rows[2].endswith("· today") and f"2026-08-10 {chapter.EN_DASH}" in rows[2]
    code, out, _err = run("chapter", "list", "--json")
    found = json.loads(out)
    assert [(c["name"], c["from"], c["to"], c["today"]) for c in found["chapters"]] == [
        (SUMMER, "2026-06-20", "2026-08-09", False),
        (ASHORE, "2026-08-10", None, True),
    ]


def test_the_listings_say_so_when_there_is_nothing(lb: Logbook):
    assert "no goals yet" in run("goal", "list")[1]
    assert "no chapters yet" in run("chapter", "list")[1]
    assert json.loads(run("goal", "list", "--json")[1])["goals"] == []


def test_goal_list_reads_a_review_of_a_goal_the_record_does_not_hold(lb: Logbook):
    """SPEC §5: a reader never fails on a line it cannot place."""
    lb.append("2026-08-31T20:00:00Z", "manual", "review", 2, {"schema": "review/v1", "goal": "elsewhere",
              "disposition": "done", "period": "month"})  # fmt: skip
    lb.append("2026-08-31T20:00:00Z", "manual", "goal", 2, {"schema": "goal/v1", "text": 7})
    assert run("goal", "list")[0] == 0
    assert run("chapter", "list")[0] == 0


def test_the_clock_is_one_function() -> None:
    assert goals.now().tzinfo is UTC
