"""`logbook review goal` (RFC 0036 amendment 1, RFC 0037 §12): the goal joins the one-loop sitting.
Each standing goal open today is asked once a week, while its chain has no review dated this ISO
week; the verdict, one of the five, is written through the writer `goal review` uses, period `week`,
so the line is the one `goal review GOAL DISPOSITION --period week` writes, byte for byte. The other
kinds' options are refused for a goal with the sentence they are refused with everywhere, and a
goal's own for every other kind. Ines Nordmann of Oslo and her goals are synthetic."""

from __future__ import annotations

import contextlib
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.core import goals, store
from logbook.core.chain import canonical_json
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
SAIL = "Sail to Lofoten and back between June and August, at anchor more nights than not."
ENGINE = "Rebuild the engine over the winter."
RUN = "Run the Holmenkollen relay with the office team."
WEDNESDAY = "2026-10-14T09:00:00Z"  # ISO week 2026-W42, Monday 12 October
LINE_FIELDS = ("id", "at", "recorded_at", "source", "kind", "tier", "payload")


def run(*args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            cli.main(list(args))
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
    return code, out.getvalue(), err.getvalue()


def pin(monkeypatch: pytest.MonkeyPatch, stamp: str) -> None:
    instant = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    monkeypatch.setattr(goals, "now", lambda: instant)


def ids(monkeypatch: pytest.MonkeyPatch, prefix: str) -> None:
    """Every new line gets the next id of a fixed sequence, so two records written alike match."""
    counter = iter(range(1, 10_000))
    monkeypatch.setattr(store, "uuid7", lambda: f"019cadd3-6bc0-7dcd-9133-{prefix}{next(counter):08d}")


def record(root: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """Three goals of the persona: a year goal reviewed last week, a quarter goal never reviewed, and
    a year goal reviewed on the Monday of this week, which the sitting does not ask again."""
    lb = Logbook.init(root, TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    ids(monkeypatch, "0000")
    pin(monkeypatch, "2026-01-02T09:00:00Z")
    assert run("goal", "add", SAIL, "--horizon", "year", "--from", "2026-01-01")[0] == 0
    assert run("goal", "add", ENGINE, "--horizon", "quarter", "--from", "2026-10-01")[0] == 0
    assert run("goal", "add", RUN, "--horizon", "year", "--from", "2026-01-01")[0] == 0
    pin(monkeypatch, "2026-10-08T18:00:00Z")  # Thursday of W41
    assert run("goal", "review", "1", "advancing", "--period", "week")[0] == 0
    pin(monkeypatch, "2026-10-12T18:00:00Z")  # Monday of W42
    assert run("goal", "review", "3", "stalled", "--period", "week")[0] == 0
    pin(monkeypatch, WEDNESDAY)
    return lb


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    return record(tmp_path / "Logbook", monkeypatch)


def reviews(lb: Logbook) -> list[dict[str, Any]]:
    return [line for line in Logbook(lb.root).lines() if line.get("kind") == "review"]


def queue(capsys: Any = None) -> dict[str, Any]:
    code, out, err = run("review", "goal", "--json")
    assert code == 0, err
    data: dict[str, Any] = json.loads(out)
    return data


def test_the_queue_asks_each_open_goal_not_reviewed_this_week(lb: Logbook) -> None:
    data = queue()
    assert data["kind"] == "goal" and data["week"] == "2026-W42" and data["tier"] == 2
    assert [p["text"] for p in data["proposals"]] == [SAIL, ENGINE]  # the relay was reviewed Monday
    assert data["reviewed"] == 1
    assert data["proposals"][0]["last_review"]["disposition"] == "advancing"
    assert data["proposals"][1]["last_review"] is None
    code, out, _err = run("review", "goal")
    assert code == 0
    rows = out.splitlines()
    assert rows[0] == "2 goals to review this week (2026-W42) · 1 reviewed · tier 2"
    assert rows[1].startswith("  1  #") and SAIL in rows[1] and "last: advancing on 2026-10-08" in rows[1]
    assert "never reviewed" in rows[2]
    assert rows[-1].startswith(
        "nothing written: `review goal --say N advancing|stalled|done|let-go|superseded`"
    )


def test_a_verdict_is_the_line_goal_review_writes_byte_for_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same record twice, the same clock and the same ids: `review goal --say` in one and
    `goal review --period week` in the other write the same line."""
    sitting = record(tmp_path / "a", monkeypatch)
    ids(monkeypatch, "0001")
    code, out, err = run("review", "goal", "--say", "1", "let-go", "--note", "1", "The engine came first.")
    assert code == 0, err
    assert "let go 1 “" in out and "review/v1 (seq" in out
    by_sitting = reviews(sitting)[-1]
    by_hand_record = record(tmp_path / "b", monkeypatch)
    ids(monkeypatch, "0001")
    goal = str(reviews(by_hand_record)[0]["payload"]["goal"])
    code, _out, err = run(
        "goal", "review", goal, "let-go", "--period", "week", "--note", "The engine came first."
    )
    assert code == 0, err
    by_hand = reviews(by_hand_record)[-1]
    assert canonical_json({k: by_sitting[k] for k in LINE_FIELDS}) == canonical_json(
        {k: by_hand[k] for k in LINE_FIELDS}
    )
    assert by_sitting["payload"] == {
        "schema": "review/v1",
        "goal": goal,
        "disposition": "let go",
        "period": "week",
        "note": "The engine came first.",
    }
    assert by_sitting["tier"] == 2 and by_sitting["source"] == "manual"


def test_a_goal_answered_is_not_asked_again_this_week_and_a_second_answer_writes_nothing(lb: Logbook) -> None:
    code, _out, err = run("review", "goal", "--say", "2", "advancing")
    assert code == 0, err
    assert [p["text"] for p in queue()["proposals"]] == [SAIL]
    seq = int(Logbook(lb.root).meta["seq"])
    code, _out, err = run("review", "goal", "--say", "1", "stalled", "--say", "1", "done")
    assert code == 2 and "--say twice" in err
    assert int(Logbook(lb.root).meta["seq"]) == seq


def test_every_answer_is_checked_before_the_first_line_is_written(lb: Logbook) -> None:
    seq = int(Logbook(lb.root).meta["seq"])
    for args, words in (
        (("--say", "1", "advancing", "--say", "9", "done"), "no goal 9"),
        (("--say", "1", "advancing", "--say", "2", "paused"), "'paused' is not a disposition"),
        (("--say", "x", "done"), "not a proposal number"),
        (("--say", "1", "done", "--note", "2", "why"), "--note 2 goes with --say 2"),
        (("--accept", "1"), "--accept goes with a proposal"),
        (("--reject", "1"), "--reject goes with a proposal"),
        (("--name", "1", "Sailing"), "--name goes with a proposal"),
        (("--all-above", "10"), "--all-above goes with a proposal"),
    ):
        code, _out, err = run("review", "goal", *args)
        assert code == 2, (args, err)
        assert err.startswith("review goal: ") and words in err, (args, err)
        assert "Traceback" not in err
    assert int(Logbook(lb.root).meta["seq"]) == seq, "nothing written"


def test_review_goal_refuses_the_other_kinds_options_with_their_sentence(lb: Logbook) -> None:
    seq = int(Logbook(lb.root).meta["seq"])
    for args, sentence in (
        (("--near", "Home"), "review goal: --near goes with `review place`"),
        (("--top", "2"), "review goal: --top goes with `review place` or `review video`"),
        (("--asked",), "review goal: --asked goes with `review video`"),
        (("--radius", "50", "--verbose"), "review goal: --radius, --verbose go with `review place`"),
        (("--unnamed", "1"), "review goal: --unnamed goes with `review speakers`"),
        (("--consent", "1=yes"), "review goal: --consent goes with `review speakers`"),
    ):
        code, _out, err = run("review", "goal", *args)
        assert code == 2 and err.strip() == sentence, (args, err)
    for kind in ("person", "org", "idea", "asset", "place", "video", "speakers"):
        code, _out, err = run("review", kind, "--say", "1", "done")
        assert code == 2 and err.strip() == f"review {kind}: --say goes with `review goal`", (kind, err)
        code, _out, err = run("review", kind, "--say", "1", "done", "--note", "1", "x")
        assert code == 2 and err.strip() == f"review {kind}: --say, --note go with `review goal`", (kind, err)
    code, _out, err = run("review", "--say", "1", "done")
    assert code == 2 and "say which kind --say is for" in err
    assert int(Logbook(lb.root).meta["seq"]) == seq


def test_review_with_no_kind_lists_the_goal_queue_and_writes_nothing(lb: Logbook) -> None:
    seq = int(Logbook(lb.root).meta["seq"])
    code, out, err = run("review")
    assert code == 0, err
    rows = out.splitlines()
    at = rows.index("goal")
    assert rows[at + 1] == "  2 goals to review this week (2026-W42) · 1 reviewed · tier 2"
    code, out, err = run("review", "--json")
    assert code == 0, err
    assert [p["text"] for p in json.loads(out)["goal"]["proposals"]] == [SAIL, ENGINE]
    assert int(Logbook(lb.root).meta["seq"]) == seq


def test_a_closed_a_past_and_a_future_goal_are_not_asked(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert run("review", "goal", "--say", "1", "done")[0] == 0
    pin(monkeypatch, "2026-10-19T09:00:00Z")  # the next week: the relay and the engine are asked again
    assert [p["text"] for p in queue()["proposals"]] == [ENGINE, RUN]
    assert run("goal", "add", "Learn the fiddle.", "--horizon", "year", "--from", "2026-11-01")[0] == 0
    assert (
        run(
            "goal",
            "add",
            "Paint the hull.",
            "--horizon",
            "quarter",
            "--from",
            "2026-07-01",
            "--until",
            "2026-09-30",
        )[0]
        == 0
    )
    assert [p["text"] for p in queue()["proposals"]] == [ENGINE, RUN]


def test_an_empty_queue_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lb = Logbook.init(tmp_path / "Logbook", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    pin(monkeypatch, WEDNESDAY)
    code, out, _err = run("review", "goal")
    assert code == 0 and out.strip() == "no goal to review this week (2026-W42): no open goal"


def test_on_a_terminal_each_goal_is_asked_in_turn(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["paused", "stalled", ""])  # a word that is none of the five, asked again; then skipped
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    class Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

    out = Terminal()
    with contextlib.redirect_stdout(out):
        cli.main(["review", "goal"])
    text = out.getvalue()
    assert "'paused' is not a disposition" in text and "stalled 1 “" in text
    (written,) = [line for line in reviews(lb) if line["payload"]["period"] == "week"][-1:]
    assert written["payload"]["disposition"] == "stalled"
    assert [p["text"] for p in queue()["proposals"]] == [ENGINE], "the skipped goal waits"
