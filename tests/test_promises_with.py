"""`people_drift.promises_with` has two callers that read promises two ways: the week's dream counts a
mover's promises from the proposals it found open as its Sunday stood (`proposals`), and `export
notion` reads its owed promises afresh, in its window and through its gate (`since`, `until`,
`admit`). Every argument after `who` is named, so neither can land in the other's place, and the two
ways never mix. Each caller still reads what it read before. On the synthetic fortnight of
`dream_fortnight.py` and `test_export_notion`'s record (Ines and Ola Nordmann of Oslo, who do not
exist); the dream's endpoint is the in-process fake."""

from __future__ import annotations

import inspect
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from dream_fortnight import ENV, OLA_PROMISE, W25, fake, fortnight, run_cli
from test_export_notion import CALL, DRAWINGS, NOW, OLA, _entry, _person, _run, build

from logbook.contrib import dream, dream_week, notion_export, people_drift
from logbook.contrib import promises as promise_reader
from logbook.core import people, policy
from logbook.core.store import Logbook

MONDAY, SUNDAY = "2026-06-15", "2026-06-21"  # W25


@pytest.fixture
def week_lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = fortnight(tmp_path / "week")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(policy, "today", lambda: date(2026, 6, 20))
    monkeypatch.setattr(dream, "today", lambda: date(2026, 6, 22))
    return lb


@pytest.fixture
def notion_lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = build(tmp_path / "notion")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.setattr(notion_export, "now", lambda: NOW)
    monkeypatch.setattr(policy, "today", lambda: date(2026, 10, 15))
    _entry(lb)
    return lb


def _extracts(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every call of `promises.extract` from now on, by its arguments' names (the record left out)."""
    calls: list[dict[str, Any]] = []
    real = promise_reader.extract
    signature = inspect.signature(real)

    def spy(*args: Any, **kwargs: Any) -> promise_reader.Report:
        bound = signature.bind(*args, **kwargs).arguments
        calls.append({name: value for name, value in bound.items() if name != "lb"})
        return real(*args, **kwargs)

    monkeypatch.setattr(promise_reader, "extract", spy)
    return calls


# -- one way or the other, never both -----------------------------------------------------------------


def test_every_argument_after_who_is_named(notion_lb: Logbook):
    """A third positional argument is refused: the week's proposals cannot become the export's gate."""
    params = list(inspect.signature(people_drift.promises_with).parameters.values())
    assert [p.name for p in params[:2]] == ["lb", "who"]
    assert {p.name: p.kind for p in params[2:]} == {
        name: inspect.Parameter.KEYWORD_ONLY for name in ("admit", "since", "until", "proposals")
    }
    with pytest.raises(TypeError):
        people_drift.promises_with(notion_lb, [], [])  # type: ignore[misc]


@pytest.mark.parametrize(
    "reading",
    [{"admit": lambda line: True}, {"since": "2026-09-01"}, {"until": "2026-10-15"}],
    ids=["admit", "since", "until"],
)
def test_proposals_with_a_gate_or_a_window_is_a_mistake(
    notion_lb: Logbook, monkeypatch: pytest.MonkeyPatch, reading: dict[str, Any]
):
    """Proposals found already were read under their caller's own window; a gate or a window beside
    them would be silently ignored, so it is refused, and nothing is read."""
    calls = _extracts(monkeypatch)
    with pytest.raises(ValueError, match="proposals"):
        people_drift.promises_with(notion_lb, [], proposals=[], **reading)
    assert calls == []


# -- each caller reads what it read before ----------------------------------------------------------


def test_the_week_s_movers_read_the_promises_open_on_its_sunday_and_none_again(
    week_lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """Ola's promise to the owner, made in Zürich, was open on the Sunday and is kept today: the week
    counts it owed to the owner, from the proposals it read once, to its Sunday; read afresh today it
    is gone. The movers read no promise of their own."""
    fake(monkeypatch)
    assert run_cli("dream", "--catch-up")[0] == 0
    (theirs,) = [p for p in promise_reader.extract(week_lb).proposals if p.match.quote == OLA_PROMISE]
    assert run_cli("promises", "done", theirs.id)[0] == 0
    calls = _extracts(monkeypatch)
    read = dream_week.material(week_lb, W25, MONDAY, SUNDAY, policy.dream_entry(week_lb.root))
    assert calls == [{"until": SUNDAY}], "the week's one read of promises, to its Sunday"
    ola = next(m for m in read.made.data["people"]["movers"] if m["name"] == "Ola Nordmann")
    assert (ola["they_owe"], ola["you_owe"]) == (1, 0), "open on the Sunday, kept after it"

    persons = [people.read(week_lb, MONDAY, SUNDAY).known[ola["id"]]]
    then = people_drift.promises_with(
        week_lb, persons, proposals=promise_reader.extract(week_lb, until=SUNDAY).proposals
    )
    assert [(p.match.quote, owed) for p, owed in then[ola["id"]]] == [(OLA_PROMISE, False)]
    assert ola["id"] not in people_drift.promises_with(week_lb, persons), "kept: not open today"


def test_export_notion_s_owed_promises_are_read_in_its_window_through_its_gate(
    notion_lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """`export notion` reads promises once, from the first day of its window to its read time and
    only through its gate, and Ola's bundle owes what it owed before: the owner's call to him, and his
    drawings to her."""
    calls = _extracts(monkeypatch)
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01")
    (call,) = calls
    assert (call["since"], call["until"]) == ("2026-09-01", "2026-10-15")
    assert isinstance(getattr(call["admit"], "__self__", None), notion_export.Gate), "the crossing's gate"
    ola = _person(out, OLA["id"])
    assert ola is not None
    owed = ola["facts"]["promises"]
    assert [p["sentence"] for p in owed["owed_by_owner"]] == [CALL]
    assert [p["sentence"] for p in owed["owed_to_owner"]] == [DRAWINGS]
