"""`logbook migrate`: a logbook/0.1 record (hashed with the pre-RFC 8785 canonicalisation) becomes
logbook/0.2. Content is untouched; prev and hash are recomputed; lineage is kept (SPEC §3.1, ADR 0014).

The 0.1 serialiser lives only here: the code carries one canonicalisation (ADR 0014)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import FORMAT
from logbook.chain import CONTENT_FIELDS, GENESIS, Line
from logbook.store import MIGRATE_MESSAGE, FormatError, Logbook

ROOT = Path(__file__).resolve().parents[1]
KEPT_FIELDS = ("id", "seq", *CONTENT_FIELDS, "recorded_at")
RECORDED = "2026-03-08T20:00:00Z"


# -- the 0.1 rule, kept here and nowhere else ---------------------------------


def old_canonical_json(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def old_hash(line: Line) -> str:
    content = {k: line.get(k) for k in CONTENT_FIELDS}
    chash = hashlib.sha256(old_canonical_json(content).encode("utf-8")).hexdigest()
    return hashlib.sha256(f"{line['prev']}|{line['seq']}|{chash}|{line['recorded_at']}".encode()).hexdigest()


# Payloads chosen so the 0.1 and 0.2 rules disagree: integer-valued and tiny floats, and a key
# outside the BMP (sorted after U+FB33 by code point, before it by UTF-16 code units).
LOCATION, NOTE = "location/v1", "note/v1"
ROWS: list[tuple[str, dict[str, Any]]] = [
    ("2026-03-01T07:30:00Z", {"schema": LOCATION, "lat": 59.911, "lon": 10.75, "alt_m": 120.0}),
    ("2026-01-15T12:00:00Z", {"schema": LOCATION, "lat": 60.0, "lon": 5.0, "speed_mps": 0.0}),  # backfilled
    ("2026-03-02T08:00:00Z", {"schema": NOTE, "text": "plain", "keys": {chr(0xFB33): 1, chr(0x1F600): 2}}),
    ("2026-03-02T09:00:00Z", {"schema": LOCATION, "lat": 59.9, "lon": 10.7, "accuracy_m": 1e-06}),
]


def legacy_logbook(root: Path) -> tuple[Logbook, list[Line]]:
    """A synthetic logbook/0.1 record, written the way the 0.1 code wrote it. A test fixture is the
    one place a log is written without Logbook.append: there is no 0.1 writer any more."""
    lb = Logbook.init(root, "Europe/Oslo")
    lines: list[Line] = []
    prev = GENESIS
    for seq, (at, payload) in enumerate(ROWS, 1):
        line: Line = {
            "id": f"00000000-0000-4000-8000-{seq:012d}",
            "seq": seq,
            "at": at,
            "end": None,
            "tz": "Europe/Oslo",
            "source": "sim-phone",
            "kind": "location" if payload["schema"] == "location/v1" else "note",
            "tier": 1,
            "payload": payload,
            "recorded_at": RECORDED,
            "prev": prev,
        }
        line["hash"] = prev = old_hash(line)
        path = root / "logbook" / at[:4] / f"{at[5:7]}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
        lines.append(line)
    meta = lb.meta
    meta.update(format="logbook/0.1", seq=len(lines), head=prev)
    (root / "logbook.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (root / "index.sqlite").write_bytes(b"a disposable index")
    return lb, lines


@pytest.fixture
def legacy(tmp_path: Path) -> tuple[Logbook, list[Line]]:
    return legacy_logbook(tmp_path / "lb")


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "LOGBOOK_HOME": str(root), "PYTHONPATH": str(ROOT)}
    return subprocess.run(
        [sys.executable, "-m", "logbook.cli", *args], env=env, capture_output=True, encoding="utf-8"
    )


# -- refusals -------------------------------------------------------------------


def test_verify_refuses_a_0_1_record(legacy):
    lb, _ = legacy
    with pytest.raises(FormatError, match=re.escape(MIGRATE_MESSAGE)):
        lb.verify()
    assert MIGRATE_MESSAGE == "created as logbook/0.1 before the canonicalisation fix; run: logbook migrate"


def test_every_writer_refuses_a_0_1_record(legacy):
    lb, lines = legacy
    before = {f: f.read_bytes() for f in lb.files()}
    draft = {"at": RECORDED, "source": "manual", "kind": "note", "tier": 2, "payload": {"schema": "note/v1"}}
    with pytest.raises(FormatError, match=re.escape(MIGRATE_MESSAGE)):
        lb.append(**draft)
    with pytest.raises(FormatError, match=re.escape(MIGRATE_MESSAGE)):
        lb.append_many([draft])
    with pytest.raises(FormatError, match=re.escape(MIGRATE_MESSAGE)):
        lb.retract(1, "no")
    assert {f: f.read_bytes() for f in lb.files()} == before
    assert lb.meta["seq"] == len(lines)


def test_migrate_refuses_a_0_2_record(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "UTC")
    with pytest.raises(FormatError, match="nothing to migrate"):
        lb.migrate()


# -- the migration --------------------------------------------------------------


def test_migrate_recomputes_the_chain_and_keeps_everything_else(legacy):
    lb, old = legacy
    old_head = lb.meta["head"]
    assert lb.meta["head"] == old[-1]["hash"]

    result = lb.migrate()

    seq, head, errors = lb.verify()
    assert errors == []
    assert seq == len(old) + 1  # the migration line
    new = list(lb.lines())
    for before, after in zip(old, new, strict=False):
        for field in KEPT_FIELDS:
            assert after[field] == before[field], field
    assert [line["prev"] for line in new] == [GENESIS, *(line["hash"] for line in new[:-1])]
    assert new[0]["hash"] != old[0]["hash"]  # 120.0 lays out as 120 now: the fixture exercised the fix
    assert new[2]["hash"] != old[2]["hash"]  # key order changed

    meta = lb.meta
    assert meta["format"] == FORMAT == "logbook/0.2"
    assert meta["head"] == head == new[-1]["hash"]
    (lineage,) = meta["lineage"]
    assert lineage["from_format"] == "logbook/0.1" and lineage["from_head"] == old_head
    assert lineage["migrated_at"].endswith("Z")

    last = new[-1]
    assert (last["source"], last["kind"], last["tier"]) == ("manual", "migration", 1)
    assert last["payload"] == {"schema": "migration/v1", "from_format": "logbook/0.1", "from_head": old_head}
    assert last["at"] == lineage["migrated_at"]

    assert result["lines"] == len(old) and result["from_head"] == old_head and result["head"] == head
    assert not (lb.root / "index.sqlite").exists()
    assert not (lb.root / "logbook.migrating").exists()


def test_migrate_keeps_the_0_1_files_beside_the_record(legacy):
    lb, _ = legacy
    before = {f.relative_to(lb.log_dir): f.read_bytes() for f in lb.files()}
    result = lb.migrate()
    kept = Path(result["kept"])
    assert kept == lb.root / "logbook-0.1"
    assert {f.relative_to(kept): f.read_bytes() for f in sorted(kept.glob("*/*.jsonl"))} == before
    now = {f.relative_to(lb.log_dir) for f in lb.files()}
    assert set(before) <= now and len(now) <= len(before) + 1  # same partition, plus the migration month


def test_migrate_runs_once(legacy):
    lb, _ = legacy
    lb.migrate()
    head = lb.meta["head"]
    with pytest.raises(FormatError, match="nothing to migrate"):
        lb.migrate()
    assert lb.meta["head"] == head and len(lb.meta["lineage"]) == 1


def test_migrate_reports_progress(legacy, monkeypatch):
    from logbook import store

    monkeypatch.setattr(store, "MIGRATE_PROGRESS_EVERY", 2)
    lb, old = legacy
    seen: list[int] = []
    lb.migrate(progress=lambda n, _elapsed: seen.append(n))
    assert seen == [2, 4] and len(old) == 4


def test_migrate_refuses_a_broken_0_1_chain_and_touches_nothing(legacy):
    lb, old = legacy
    path = lb.log_dir / "2026" / "03.jsonl"
    rows = [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines()]
    rows[1]["prev"] = "f" * 64
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    before = {f: f.read_bytes() for f in lb.files()}
    with pytest.raises(ValueError, match="line 3: prev"):
        lb.migrate()
    assert {f: f.read_bytes() for f in lb.files()} == before
    assert lb.meta["format"] == "logbook/0.1" and lb.meta["head"] == old[-1]["hash"]
    assert not (lb.root / "logbook.migrating").exists() and not (lb.root / "logbook-0.1").exists()
    assert (lb.root / "index.sqlite").exists()


def test_migrate_empty_0_1_record(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "UTC")
    meta = lb.meta
    meta["format"] = "logbook/0.1"
    (lb.root / "logbook.json").write_text(json.dumps(meta) + "\n", encoding="utf-8")
    lb.migrate()
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 1 and lb.meta["lineage"][0]["from_head"] == GENESIS


# -- CLI --------------------------------------------------------------------------


def test_cli_verify_and_add_refuse_then_migrate_then_verify(legacy):
    lb, old = legacy
    r = _run(lb.root, "verify")
    assert r.returncode == 2 and MIGRATE_MESSAGE in r.stderr and "valid" not in r.stdout
    r = _run(lb.root, "add", "a note that must not land")
    assert r.returncode == 2 and MIGRATE_MESSAGE in r.stderr
    assert lb.meta["seq"] == len(old)

    r = _run(lb.root, "migrate")
    assert r.returncode == 0, r.stderr
    assert f"migrated {len(old)} lines" in r.stdout and "logbook-0.1" in r.stdout

    r = _run(lb.root, "verify")
    assert r.returncode == 0 and r.stdout.startswith(f"valid — {len(old) + 1} lines")

    r = _run(lb.root, "migrate")
    assert r.returncode == 2 and "nothing to migrate" in r.stderr


def test_cli_migrate_takes_root(legacy):
    lb, old = legacy
    r = _run(Path("/nonexistent"), "migrate", "--root", str(lb.root))
    assert r.returncode == 0, r.stderr
    assert lb.meta["format"] == FORMAT and lb.meta["seq"] == len(old) + 1


def test_conformance_sample_is_0_2():
    sample = json.loads((ROOT / "conformance" / "sample-logbook" / "logbook.json").read_text("utf-8"))
    expected = json.loads((ROOT / "conformance" / "expected.json").read_text(encoding="utf-8"))
    assert sample["format"] == expected["format"] == "logbook/0.2"
