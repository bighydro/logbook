"""The scale harness (`tests/perf/run.py`) holds what the owner asked of it: about 2,000 people, of
whom only the reserved range's 1,000 numbers can have one (07700 900xxx, never a real number);
flights with and without their arrival; reflections and goals; every route timed alone and all of
them at once. The quick tier checks the harness on a small record; `stress` (LOGBOOK_STRESS=1, never
in CI) runs it at its size and prints the table. Synthetic throughout: the Oslo persona, who does not
exist, addresses at example.org."""

from __future__ import annotations

import importlib.util
import random
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from logbook.core import notes as notes_module
from logbook.core.store import Logbook

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("perf_run", HERE / "run.py")
assert _spec is not None and _spec.loader is not None
run: Any = importlib.util.module_from_spec(_spec)
sys.modules["perf_run"] = run
_spec.loader.exec_module(run)
bench = run.bench()
RESERVED = re.compile(r"^\+447700900\d{3}$")  # 07700 900000 to 900999, Ofcom's drama range


@pytest.fixture(scope="module")
def small(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    """The harness's record at 20,000 lines and 700 people: more people than numbers, every second
    flight without its arrival, ten days reflected on. Its environment is the module's, undone."""
    root = tmp_path_factory.mktemp("scale")
    with pytest.MonkeyPatch.context() as mp:
        for key, value in bench._environment(root).items():
            if key.startswith("LOGBOOK_"):
                mp.setenv(key, value)
        built = bench.build(root, 20_000, bench.SEED, people=700, open_flights=2, reflections=10)
    return root, built


def test_two_thousand_people_have_at_most_the_reserved_range_s_numbers() -> None:
    cast = bench.Cast(random.Random(1), 2_000)
    phones = [p["phone"] for p in cast.people if p["phone"]]
    assert len(cast.people) == 2_000 and len(phones) == bench.PHONED
    assert all(RESERVED.match(n) for n in [*phones, *cast.phones])
    assert len(set(phones) | set(cast.phones)) == len(phones) + len(cast.phones), "no number twice"
    assert all(p["email"].endswith("@example.org") for p in cast.people)
    assert len({p["id"] for p in cast.people}) == 2_000


def test_the_default_cast_is_the_bench_s_as_it_was() -> None:
    """300 people, each with a number, as the bench's published timings were taken with."""
    cast = bench.Cast(random.Random(bench.SEED))
    assert len(cast.people) == bench.PEOPLE and all(p["phone"] for p in cast.people)
    assert cast.people[0]["phone"] == "+447700900001" and cast.phones[0] == "+447700900301"


def test_the_record_holds_open_flights_reflections_goals_and_mail_only_people(
    small: tuple[Path, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, built = small
    for key, value in bench._environment(root).items():
        if key.startswith("LOGBOOK_"):
            monkeypatch.setenv(key, value)
    lb = Logbook(root / "record")
    with lb.index() as idx:
        flights = idx.by_kind("flight")
        notes = idx.by_kind("note")
        goals = idx.by_kind("goal")
        messages = idx.by_kind("message")
    assert built["counts"].get("open flight", 0) > 0
    assert any(f["end"] is None and "actual_arrival" not in f["payload"] for f in flights)
    assert any(f["end"] is not None for f in flights)
    reflections = [n for n in notes if notes_module.REFLECTION in n["payload"].get("labels", [])]
    assert len(reflections) >= 30, "ten days reflected on, and the thirty signed ones"
    assert len(goals) >= 4
    assert any((m["payload"].get("sender") or {}).get("kind") == "email" for m in messages)


@pytest.mark.slow
def test_every_route_at_once_answers(
    small: tuple[Path, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, built = small
    for key, value in bench._environment(root).items():
        if key.startswith("LOGBOOK_"):
            monkeypatch.setenv(key, value)
    fill = {"day": bench.busiest_day(root), "person": built["busiest_person"], "org": built["org"]}
    routes = [r.format(**fill, idea=built["idea"]) for r in bench.ROUTES if "{journey}" not in r]
    found = bench.together(root, routes)
    assert set(found["routes"]) == set(routes)
    for route, answer in found["routes"].items():
        assert answer["status"] == (302 if route == "/today" else 200), route
    assert found["all_s"] >= max(a["s"] for a in found["routes"].values())


def test_the_table_has_a_row_for_every_route_and_one_for_all_at_once() -> None:
    results = [
        {
            "route": "/people",
            "status": 200,
            "cold_s": 2.5,
            "warm_s": 0.001,
            "after_append_s": 2.0,
            "peak_mb": 90.0,
        },
        {"route": "/", "status": 200, "cold_s": 0.2, "warm_s": 0.001, "after_append_s": 0.1, "peak_mb": None},
        {"route": "/journeys/{journey}", "error": "no journey on /journeys"},
    ]
    at_once = {
        "routes": {"/people": {"status": 200, "s": 3.0}, "/": {"status": 200, "s": 0.3}},
        "all_s": 3.1,
        "peak_mb": 120.0,
    }
    rows = run.table(results, at_once).splitlines()
    assert rows[2].startswith("| `/people` | 200 | 2.500"), "the slowest cold first"
    assert "| 3.000 |" in rows[2]
    assert rows[-1].startswith("| **every route at once** (2)") and "3.100" in rows[-1]
    assert any("no journey" in row for row in rows)


@pytest.mark.stress
def test_the_scale_record_answers_every_route(capsys: pytest.CaptureFixture[str]) -> None:
    """The harness at its size: 2,000,000 lines and 2,000 people (or LOGBOOK_PERF_LINES), kept in
    tests/perf/.record; every route answers, alone and all at once, and the table is printed."""
    import os

    lines = int(os.environ.get("LOGBOOK_PERF_LINES", run.LINES))
    out = run.main(["--lines", str(lines)])
    assert all("error" not in r for r in out["routes"]), [r for r in out["routes"] if "error" in r]
    assert "error" not in out["at_once"]
    with capsys.disabled():
        print("\n" + run.table(out["routes"], out["at_once"]))
