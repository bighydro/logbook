"""`logbook add` with several arguments: paths are paths, a sentence is only what is left when
nothing is a path, and a path that does not exist is an error, never a note."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "dawarich" / "export.json"


@pytest.fixture
def lb(tmp_path: Path) -> Logbook:
    return Logbook.init(tmp_path / "lb", "Europe/Oslo")


def _run(lb: Logbook, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "LOGBOOK_HOME": str(lb.root), "PYTHONPATH": str(ROOT)}
    return subprocess.run(
        [sys.executable, "-m", "logbook.cli", "add", *args], env=env, capture_output=True, encoding="utf-8"
    )


def _second_export(dst: Path, n: int = 5) -> Path:
    """The fixture's first `n` features under another tracker id, so nothing dedupes."""
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    features = doc["features"][:n]
    for f in features:
        f["properties"]["tracker_id"] = "00000000-0000-4000-8000-000000000002"
    dst.write_text(json.dumps({**doc, "features": features}), encoding="utf-8")
    return dst


def test_add_several_paths_processes_each_in_order(lb: Logbook, tmp_path: Path):
    a = tmp_path / "a.json"
    shutil.copy(FIXTURE, a)
    b = _second_export(tmp_path / "b.json", 5)
    folder = tmp_path / "some" / "dir"
    folder.mkdir(parents=True)
    _second_export(folder / "c.json", 3)
    for f in folder.iterdir():  # a third tracker id, so the folder's file is new too
        f.write_text(
            f.read_text(encoding="utf-8").replace("-000000000002", "-000000000003"), encoding="utf-8"
        )
    r = _run(lb, str(a), str(b), str(folder))
    assert r.returncode == 0, r.stderr
    added = [line for line in r.stdout.splitlines() if line.startswith("added")]
    assert added == [
        "added 40 lines from dawarich",
        "added 5 lines from dawarich",
        "added 3 lines from dawarich",
    ]
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 48


@pytest.mark.parametrize(
    "missing",
    ["~/Downloads/typo.json", "some/dir/export.json", "export.jsonl", "notes.txt", "takeout.zip"],
)
def test_add_lone_path_that_does_not_exist_is_an_error_not_a_note(lb: Logbook, missing: str):
    r = _run(lb, missing)
    assert r.returncode == 2
    assert r.stdout == ""
    assert len(r.stderr.splitlines()) == 1 and missing in r.stderr
    assert lb.meta["seq"] == 0


def test_add_existing_path_plus_a_word_is_an_error_and_writes_nothing(lb: Logbook, tmp_path: Path):
    a = tmp_path / "a.json"
    shutil.copy(FIXTURE, a)
    r = _run(lb, str(a), "typo")
    assert r.returncode == 2
    assert len(r.stderr.splitlines()) == 1 and "typo" in r.stderr
    assert lb.meta["seq"] == 0  # a.json was not imported before the bad argument was noticed


def test_add_two_globbed_paths_where_one_is_missing_writes_nothing(lb: Logbook, tmp_path: Path):
    a = tmp_path / "a.json"
    shutil.copy(FIXTURE, a)
    r = _run(lb, str(a), str(tmp_path / "b.json"))
    assert r.returncode == 2
    assert lb.meta["seq"] == 0


@pytest.mark.parametrize(
    "words", [["had", "5/10", "sleep"], ["A/B", "test", "went", "well"], ["train", "Zurich/Munich"]]
)
def test_add_sentence_with_a_slash_is_still_a_note(lb: Logbook, words: list[str]):
    r = _run(lb, *words)
    assert r.returncode == 0, r.stderr
    (line,) = lb.lines()
    assert line["kind"] == "note" and line["payload"]["text"] == " ".join(words)


def test_add_words_without_a_path_are_still_a_note(lb: Logbook):
    r = _run(lb, "had", "lunch", "by", "the", "lake")
    assert r.returncode == 0, r.stderr
    (line,) = lb.lines()
    assert line["kind"] == "note" and line["payload"]["text"] == "had lunch by the lake"


def test_add_unknown_file_still_exits_2_after_processing_the_rest(lb: Logbook, tmp_path: Path):
    a = tmp_path / "a.json"
    shutil.copy(FIXTURE, a)
    mystery = tmp_path / "mystery.csv"
    mystery.write_text("a,b\n1,2\n", encoding="utf-8")
    r = _run(lb, str(mystery), str(a))
    assert r.returncode == 2
    assert "no adapter" in r.stdout and "added 40 lines from dawarich" in r.stdout
