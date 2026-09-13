import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "conformance" / "sample-logbook"


def test_sample_logbook_verifies_to_expected_head():
    lb = Logbook(SAMPLE)
    seq, head, errors = lb.verify()
    expected = json.loads((ROOT / "conformance" / "expected.json").read_text())
    assert errors == []
    assert seq == expected["seq"] and head == expected["head"]


def test_append_keeps_chain_valid(tmp_path):
    shutil.copytree(SAMPLE, tmp_path / "lb")
    lb = Logbook(tmp_path / "lb")
    lb.append(
        at="2026-03-02T09:00:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "text": "one more line"},
    )
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == json.loads((ROOT / "conformance" / "expected.json").read_text())["seq"] + 1


def test_tampering_is_detected(tmp_path):
    shutil.copytree(SAMPLE, tmp_path / "lb")
    f = next((tmp_path / "lb" / "logbook").glob("*/*.jsonl"))
    lines = f.read_text().splitlines()
    row = json.loads(lines[3])
    row["payload"]["text"] = "edited"
    lines[3] = json.dumps(row, sort_keys=True)
    f.write_text("\n".join(lines) + "\n")
    _, _, errors = Logbook(tmp_path / "lb").verify()
    assert any("hash does not recompute" in e for e in errors)


def test_missing_line_is_detected(tmp_path):
    shutil.copytree(SAMPLE, tmp_path / "lb")
    f = next((tmp_path / "lb" / "logbook").glob("*/*.jsonl"))
    lines = f.read_text().splitlines()
    del lines[5]
    f.write_text("\n".join(lines) + "\n")
    _, _, errors = Logbook(tmp_path / "lb").verify()
    assert any("seq" in e for e in errors)


def test_cli_round_trip(tmp_path):
    env = {**os.environ, "LOGBOOK_HOME": str(tmp_path / "lb"), "PYTHONPATH": str(ROOT)}

    def run(*a):
        return subprocess.run(
            [sys.executable, "-m", "logbook.cli", *a], env=env, capture_output=True, text=True, check=True
        ).stdout

    assert "created" in run("init", str(tmp_path / "lb"), "--timezone", "UTC")
    run("add", "had", "lunch", "by", "the", "lake")
    assert "valid — 1 lines" in run("verify")
    run("export", str(tmp_path / "all.jsonl"))
    assert len((tmp_path / "all.jsonl").read_text().splitlines()) == 1
