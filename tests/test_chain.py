import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook.core.store import CodeCheckoutError, Logbook

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "conformance" / "sample-logbook"


def test_sample_logbook_verifies_to_expected_head():
    lb = Logbook(SAMPLE)
    seq, head, errors = lb.verify()
    expected = json.loads((ROOT / "conformance" / "expected.json").read_text())
    assert errors == []
    assert seq == expected["seq"] and head == expected["head"]


def test_cli_round_trip(tmp_path):
    env = {**os.environ, "LOGBOOK_HOME": str(tmp_path / "lb"), "PYTHONPATH": str(ROOT)}

    def run(*a):
        return subprocess.run(
            [sys.executable, "-m", "logbook.cli", *a],
            env=env,
            capture_output=True,
            encoding="utf-8",
            check=True,
        ).stdout

    assert "created" in run("init", str(tmp_path / "lb"), "--timezone", "UTC")
    run("add", "had", "lunch", "by", "the", "lake")
    assert "valid — 1 lines" in run("verify")
    run("export", str(tmp_path / "all.jsonl"))
    assert len((tmp_path / "all.jsonl").read_text().splitlines()) == 1


# -- issue #12: never mistake a code checkout for a logbook -------------------

CHECKOUT_MARKERS = ["pyproject.toml", ".git/", "logbook/__init__.py"]


def _make_checkout(root, marker):
    """A folder that looks like a clone of this repo, identified by one marker."""
    root.mkdir(parents=True, exist_ok=True)
    if marker.endswith("/"):
        (root / marker).mkdir(parents=True)
    else:
        (root / marker).parent.mkdir(parents=True, exist_ok=True)
        (root / marker).write_text("", encoding="utf-8")


@pytest.mark.parametrize("marker", CHECKOUT_MARKERS)
def test_init_refuses_code_checkout(tmp_path, marker):
    _make_checkout(tmp_path / "clone", marker)
    with pytest.raises(CodeCheckoutError):
        Logbook.init(tmp_path / "clone", "UTC")
    assert not (tmp_path / "clone" / "logbook.json").exists()
    assert not (tmp_path / "clone" / "logbook" / "2026").exists()


@pytest.mark.parametrize("marker", CHECKOUT_MARKERS)
def test_cli_init_refuses_code_checkout_with_exit_2(tmp_path, marker):
    _make_checkout(tmp_path / "clone", marker)
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    env.pop("LOGBOOK_HOME", None)
    r = subprocess.run(
        [sys.executable, "-m", "logbook.cli", "init", str(tmp_path / "clone"), "--timezone", "UTC"],
        env=env,
        capture_output=True,
        encoding="utf-8",
    )
    assert r.returncode == 2
    assert r.stdout == ""
    assert len(r.stderr.strip().splitlines()) == 1
    assert "looks like a code checkout" in r.stderr
    assert not (tmp_path / "clone" / "logbook.json").exists()


@pytest.mark.parametrize("marker", CHECKOUT_MARKERS)
def test_find_never_falls_back_to_code_checkout(tmp_path, monkeypatch, marker):
    # a clone that already carries a stray logbook.json (the captain's day-one accident)
    _make_checkout(tmp_path / "clone", marker)
    (tmp_path / "clone" / "logbook.json").write_text("{}", encoding="utf-8")
    monkeypatch.delenv("LOGBOOK_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    with pytest.raises(FileNotFoundError):
        Logbook.find(start=tmp_path / "clone" / "logbook")


def test_find_skips_home_logbook_that_is_a_code_checkout(tmp_path, monkeypatch):
    # on a case-insensitive disk ~/Logbook and a clone at ~/logbook are the same folder
    home = tmp_path / "home"
    _make_checkout(home / "Logbook", "pyproject.toml")
    (home / "Logbook" / "logbook.json").write_text("{}", encoding="utf-8")
    monkeypatch.delenv("LOGBOOK_HOME", raising=False)
    monkeypatch.setenv("HOME", str(home))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    with pytest.raises(FileNotFoundError):
        Logbook.find(start=elsewhere)


def test_find_is_pinned_to_a_temporary_record_by_conftest(tmp_path):
    """tests/conftest.py sets LOGBOOK_HOME, HOME and USERPROFILE per test, so neither the variable nor
    the ~/Logbook fallback can ever reach a real record."""
    home = Path(os.environ["LOGBOOK_HOME"])
    assert home.resolve().is_relative_to(tmp_path.resolve())
    assert (Path.home() / "Logbook").resolve().is_relative_to(tmp_path.resolve())
    with pytest.raises(FileNotFoundError):  # nothing anywhere yet: the fallback found no real record
        Logbook.find(start=tmp_path)
    Logbook.init(home, "UTC")
    assert Logbook.find().root.resolve().is_relative_to(tmp_path.resolve())


def test_find_still_locates_a_real_logbook_past_a_checkout(tmp_path, monkeypatch):
    real = Logbook.init(tmp_path / "real", "UTC")
    _make_checkout(tmp_path / "real" / "clone", ".git/")
    monkeypatch.delenv("LOGBOOK_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert Logbook.find(start=tmp_path / "real" / "clone").root == real.root


# -- Level 2: the sealed sample (SPEC §6, RFC 0029) -----------------------------------------------

SEALED = ROOT / "conformance" / "sample-logbook-sealed"
IDENTITY = ROOT / "conformance" / "identity.txt"


def test_sealed_sample_verifies_to_its_head_keyless_and_keyed():
    expected = json.loads((ROOT / "conformance" / "expected-sealed.json").read_text())
    keyless = Logbook(SEALED, identity_file=SEALED / "nowhere.txt")
    counts: dict[str, int] = {}
    seq, head, errors = keyless.verify(counts=counts)
    assert errors == [] and (seq, head) == (expected["seq"], expected["head"])
    assert counts["sealed"] > 0 and counts["opened"] == 0 and counts["plain"] == 0
    keyed = Logbook(SEALED, identity_file=IDENTITY)
    opened: dict[str, int] = {}
    seq, head, errors = keyed.verify(counts=opened)
    assert errors == [] and (seq, head) == (expected["seq"], expected["head"])
    assert opened["opened"] == opened["sealed"] == counts["sealed"]
    assert expected["format"] == json.loads((SEALED / "logbook.json").read_text())["format"] == "logbook/0.3"


def test_sealed_sample_tampered_ciphertext_passes_keyless_and_fails_keyed(tmp_path):
    shutil.copytree(SEALED, tmp_path / "lb")
    f = next((tmp_path / "lb" / "logbook").glob("*/*.jsonl"))
    lines = f.read_text().splitlines()
    rows = [json.loads(line) for line in lines]
    i, row = next((i, r) for i, r in enumerate(rows) if "payload_enc" in r)
    raw = bytearray(__import__("base64").b64decode(row["payload_enc"]))
    raw[-1] ^= 0x01  # one bit of the last chunk's tag
    row["payload_enc"] = __import__("base64").b64encode(bytes(raw)).decode()
    lines[i] = json.dumps(row, sort_keys=True)
    f.write_text("\n".join(lines) + "\n")
    assert Logbook(tmp_path / "lb", identity_file=tmp_path / "none").verify()[2] == []
    _, _, errors = Logbook(tmp_path / "lb", identity_file=IDENTITY).verify()
    assert len(errors) == 1 and "does not open" in errors[0]


def test_a_tier_2_line_appended_to_the_sealed_sample_is_sealed(tmp_path):
    shutil.copytree(SEALED, tmp_path / "lb")
    lb = Logbook(tmp_path / "lb", identity_file=IDENTITY)
    note = {"schema": "note/v1", "text": "one more"}
    line = lb.append(at="2026-03-02T09:00:00Z", source="manual", kind="note", tier=2, payload=note)
    assert line["payload"]["schema"] == "sealed/v1" and line["payload"]["of"] == "note/v1"
    assert lb.verify()[2] == [] and lb.opened(line)["payload"]["text"] == "one more"
