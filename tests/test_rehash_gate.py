"""`key seal --all` and `repair migrate` give every line a new hash, so both verify the record first:
every original hash under the rule the record was written with, every link, the whole record. A line
whose text was changed on disk with its hash left as it was fails `verify` with `hash does not
recompute`; a rewrite that rehashes it would give it a fresh hash and a clean chain. So the rewrite
refuses, names the first failing line, and changes nothing; and the new files are verified before
they replace the old ones. The gate is in `Logbook._rewrite`, which every rehashing path runs through,
so no command can skip it."""

from __future__ import annotations

import json
import random
import shutil
from pathlib import Path

import pytest
from test_migrate import legacy_logbook

from logbook import FORMAT
from logbook.core import sealing
from logbook.core.chain import GENESIS, compute_hash
from logbook.core.store import Logbook, NotIntact

ROOT = Path(__file__).resolve().parents[1]
CONFORMANCE = ROOT / "conformance"
RECORDED = "2026-10-01T20:00:00Z"
ALTERED = "the words are not what was written"

# A plain record written before any key, with fixed ids and `recorded_at` so its sealed form is a
# fixed point: the salts come from a seeded generator, the ciphertext is outside the hash.
DRAFTS = [
    {
        "id": "00000000-0000-4000-8000-000000000001",
        "at": "2026-10-01T18:42:00Z",
        "source": "manual",
        "kind": "note",
        "tier": 2,
        "payload": {
            "schema": "note/v1",
            "text": "Dinner with Kari at the marina; Solvind needs a new impeller.",
        },
        "recorded_at": RECORDED,
    },
    {
        "id": "00000000-0000-4000-8000-000000000002",
        "at": "2026-10-01T18:43:00Z",
        "source": "sim-phone",
        "kind": "location",
        "tier": 1,
        "payload": {"schema": "location/v1", "lat": 59.911, "lon": 10.75},
        "recorded_at": RECORDED,
    },
    {
        "id": "00000000-0000-4000-8000-000000000003",
        "at": "2026-09-30T19:00:00Z",
        "source": "manual",
        "kind": "note",
        "tier": 3,
        "payload": {"schema": "note/v1", "text": "Pulse 62 after the morning swim at Sognsvann."},
        "recorded_at": RECORDED,
    },
]

# What `seal_all` made of DRAFTS before the gate existed, salts seeded with 25, `payload_enc` aside
# (it is outside the hash and differs on every run); the fixture outputs the gate must not change.
SEALED_BEFORE = {
    1: {
        "digest": "fa568f2e9fb34b7bdde537570d1c4a2704c04041c5209b88ee055118456bea9e",
        "hash": "218349d5d41a041057282e06c64b094e1776810a2e7f196fe0f62f9aebd0117b",
    },
    2: {"hash": "a98f744ebcb0367544bdac220341121b59e32cac09fa5ad0029c825a6b2c86c7"},
    3: {
        "digest": "5b391ae6449cf879730ca201fe0845ab98bab55fb59d102eeb21087c0920519f",
        "hash": "9a5e19930fc4d5995e704f8690790c523cfaae9ecbd64cfc7f740184f1a79e58",
    },
}

# The month files `migrate` wrote for `test_migrate.legacy_logbook` before the gate existed, byte for
# byte (the migration line lands in the month of the run and is checked by shape, not bytes).
MIGRATED_BEFORE = {
    ("2026", "01.jsonl"): [
        '{"at": "2026-01-15T12:00:00Z", "end": null, "hash": "a4840468ccf5ec3889ecec68d2d1042458918d275b02159b54c5c44defce5bb2", "id": "00000000-0000-4000-8000-000000000002", "kind": "location", "payload": {"lat": 60.0, "lon": 5.0, "schema": "location/v1", "speed_mps": 0.0}, "prev": "6b2206a1aac1dca01483e5726e27e8cd673d7c64bd15f1329bbc447df6b6c419", "recorded_at": "2026-03-08T20:00:00Z", "seq": 2, "source": "sim-phone", "tier": 1, "tz": "Europe/Oslo"}',  # noqa: E501
    ],
    ("2026", "03.jsonl"): [
        '{"at": "2026-03-01T07:30:00Z", "end": null, "hash": "6b2206a1aac1dca01483e5726e27e8cd673d7c64bd15f1329bbc447df6b6c419", "id": "00000000-0000-4000-8000-000000000001", "kind": "location", "payload": {"alt_m": 120.0, "lat": 59.911, "lon": 10.75, "schema": "location/v1"}, "prev": "0000000000000000000000000000000000000000000000000000000000000000", "recorded_at": "2026-03-08T20:00:00Z", "seq": 1, "source": "sim-phone", "tier": 1, "tz": "Europe/Oslo"}',  # noqa: E501
        '{"at": "2026-03-02T08:00:00Z", "end": null, "hash": "6e10168ae7fe6b995c4a88f5478e0ecbd2a22e2d9a7dd71bb96bafa8c76dfe5f", "id": "00000000-0000-4000-8000-000000000003", "kind": "note", "payload": {"keys": {"דּ": 1, "\U0001f600": 2}, "schema": "note/v1", "text": "plain"}, "prev": "a4840468ccf5ec3889ecec68d2d1042458918d275b02159b54c5c44defce5bb2", "recorded_at": "2026-03-08T20:00:00Z", "seq": 3, "source": "sim-phone", "tier": 1, "tz": "Europe/Oslo"}',  # noqa: E501
        '{"at": "2026-03-02T09:00:00Z", "end": null, "hash": "dbed1b6d113ddab10bc6372c457efa49b4a798c4db7f993a462811ec74efa8d1", "id": "00000000-0000-4000-8000-000000000004", "kind": "location", "payload": {"accuracy_m": 1e-06, "lat": 59.9, "lon": 10.7, "schema": "location/v1"}, "prev": "6e10168ae7fe6b995c4a88f5478e0ecbd2a22e2d9a7dd71bb96bafa8c76dfe5f", "recorded_at": "2026-03-08T20:00:00Z", "seq": 4, "source": "sim-phone", "tier": 1, "tz": "Europe/Oslo"}',  # noqa: E501
    ],
}


# -- helpers --------------------------------------------------------------------------------------


def _keyed_plain_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """DRAFTS written plain, then two recipients named and the first identity put where
    LOGBOOK_IDENTITY_FILE points: the record `key seal --all` is for."""
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    assert lb.append_many([dict(d, payload=dict(d["payload"])) for d in DRAFTS]) == len(DRAFTS)
    pairs = [sealing.generate_identity() for _ in range(2)]
    meta = lb.meta
    meta["recipients"] = [recipient for _, recipient in pairs]
    lb._save_meta(meta)
    identity = tmp_path / "keys" / "owner.txt"
    sealing.write_identity_file(identity, pairs[0][0], "test")
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(identity))
    return Logbook(lb.root)


def _rows(path: Path) -> list[dict]:
    return [json.loads(raw) for raw in path.read_text(encoding="utf-8").splitlines() if raw.strip()]


def _write_rows(path: Path, rows: list[dict]) -> None:
    path.write_bytes("".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in rows).encode())


def _alter(lb: Logbook, seq: int, **fields: object) -> dict:
    """Change a stored line on disk and leave its `hash` as it was: what a verifier must catch. Top-level
    fields are set as given; `text` goes into the payload. Returns the line as it now stands."""
    for path in lb.files():
        rows = _rows(path)
        for row in rows:
            if row["seq"] == seq:
                for key, value in fields.items():
                    if key == "text":
                        row["payload"]["text"] = value
                    else:
                        row[key] = value
                _write_rows(path, rows)
                return row
    raise AssertionError(f"no line with seq {seq}")


def _snapshot(root: Path) -> dict[Path, bytes]:
    return {p.relative_to(root): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _staging(root: Path) -> list[str]:
    return sorted(
        p.name for p in root.iterdir() if p.is_dir() and p.name.startswith("logbook") and p.name != "logbook"
    )


def _seeded_salts(monkeypatch: pytest.MonkeyPatch, seed: int = 25) -> None:
    salts = random.Random(seed)
    monkeypatch.setattr(sealing, "new_salt", lambda: f"{salts.getrandbits(128):032x}")


# -- seal --all: the reviewer's sequence -----------------------------------------------------------


def test_seal_all_refuses_a_line_whose_text_changed_under_its_hash_and_replaces_nothing(
    tmp_path, monkeypatch
):
    lb = _keyed_plain_record(tmp_path, monkeypatch)
    altered = _alter(lb, 1, text=ALTERED)
    assert lb.verify()[2] == ["line 1: hash does not recompute"]
    before = _snapshot(lb.root)
    meta_before = lb.meta

    with pytest.raises(NotIntact) as e:
        lb.seal_all()

    message = str(e.value)
    assert message.startswith("line 1: hash does not recompute"), message
    assert f"id {altered['id']}" in message and message.endswith("nothing was changed")
    assert _snapshot(lb.root) == before, "no file of the record changed"
    assert _staging(lb.root) == [], "no staging folder is left behind"
    assert lb.meta == meta_before and "lineage" not in lb.meta
    assert lb.verify()[2] == ["line 1: hash does not recompute"], "keyed verify still reports the failure"
    assert (
        json.loads(lb.files()[-1].read_text(encoding="utf-8").splitlines()[0])["payload"]["text"] == ALTERED
    )


def test_seal_all_refuses_a_broken_link_before_it_writes(tmp_path, monkeypatch):
    lb = _keyed_plain_record(tmp_path, monkeypatch)
    _alter(lb, 2, prev="f" * 64)
    before = _snapshot(lb.root)
    with pytest.raises(NotIntact, match=r"^line 2: prev does not match previous hash; id 0000") as e:
        lb.seal_all()
    assert str(e.value).endswith("nothing was changed")
    assert _snapshot(lb.root) == before and _staging(lb.root) == []


def test_reseal_runs_through_the_same_gate(tmp_path, monkeypatch):
    lb = _keyed_plain_record(tmp_path, monkeypatch)
    lb.seal_all()
    assert lb.verify()[2] == []
    _alter(lb, 2, source="not-the-phone")  # tier 1, plain: the hash no longer recomputes
    before = _snapshot(lb.root)
    _, third = sealing.generate_identity()
    with pytest.raises(NotIntact, match=r"^line 2: hash does not recompute; id "):
        lb.reseal([*lb.recipients, third])
    assert _snapshot(lb.root) == before and _staging(lb.root) == []


def test_cli_seal_all_exits_2_naming_the_line_and_its_id_and_replaces_nothing(tmp_path, monkeypatch, capsys):
    from logbook import cli

    lb = _keyed_plain_record(tmp_path, monkeypatch)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    altered = _alter(lb, 3, text=ALTERED)
    before = _snapshot(lb.root)
    with pytest.raises(SystemExit) as e:
        cli.main(["key", "seal", "--all"])
    out, err = capsys.readouterr()
    assert e.value.code == 2 and out == ""
    assert "line 3: hash does not recompute" in err and altered["id"] in err and "nothing was changed" in err
    assert "replaced" not in err
    assert _snapshot(lb.root) == before


# -- a clean record seals exactly as before -------------------------------------------------------


def test_a_clean_record_seals_to_the_same_chain_as_before_the_gate(tmp_path, monkeypatch):
    lb = _keyed_plain_record(tmp_path, monkeypatch)
    _seeded_salts(monkeypatch)
    result = lb.seal_all()
    assert (result["lines"], result["sealed_lines"], result["sealed_attachments"]) == (3, 2, 0)
    stored = {row["seq"]: row for f in lb.files() for row in _rows(f)}
    for seq, expected in SEALED_BEFORE.items():
        row = stored[seq]
        assert row["hash"] == expected["hash"], seq
        if "digest" in expected:
            assert row["payload"] == {"schema": "sealed/v1", "of": "note/v1", "digest": expected["digest"]}
            assert "payload_enc" in row
        else:
            assert row["payload"] == DRAFTS[seq - 1]["payload"] and "payload_enc" not in row
    migration = stored[4]
    assert migration["kind"] == "migration" and migration["prev"] == SEALED_BEFORE[3]["hash"]
    assert migration["payload"]["from_head"] == result["from_head"]
    assert lb.meta["lineage"][0]["from_head"] == result["from_head"]
    counts: dict[str, int] = {}
    assert lb.verify(counts=counts)[2] == [] and counts == {"sealed": 2, "opened": 2, "plain": 0}
    assert _staging(lb.root) == []


def test_the_conformance_sample_seals_and_verifies_keyed_from_its_published_head(tmp_path):
    """Level 1 in, Level 2 out: the plain sample, sealed to the fixture identity and the recovery
    recipient, verifies with the key and names the L1 head as what it replaced."""
    shutil.copytree(CONFORMANCE / "sample-logbook", tmp_path / "lb")
    expected = json.loads((CONFORMANCE / "expected.json").read_text(encoding="utf-8"))
    identity = CONFORMANCE / "identity.txt"
    recovery = (CONFORMANCE / "recovery-recipient.txt").read_text(encoding="utf-8").split()[0]
    lb = Logbook(tmp_path / "lb", identity_file=identity)
    assert lb.verify()[1] == expected["head"]
    meta = lb.meta
    meta["recipients"] = [sealing.recipient_of(str(lb.identities[0])), recovery]
    lb._save_meta(meta)

    result = lb.seal_all()

    assert result["from_head"] == expected["head"] and result["lines"] == expected["seq"]
    counts: dict[str, int] = {}
    seq, head, errors = lb.verify(counts=counts)
    assert errors == [] and seq == expected["seq"] + 1 and head == result["head"]
    assert counts["plain"] == 0 and counts["sealed"] == counts["opened"] == result["sealed_lines"] > 0
    assert lb.meta["format"] == FORMAT and lb.meta["lineage"][0]["from_head"] == expected["head"]
    keyless = Logbook(tmp_path / "lb", identity_file=tmp_path / "nowhere.txt")
    assert keyless.verify()[2] == []


# -- the new files must verify before they replace the old --------------------------------------------


def test_the_new_files_are_verified_before_the_old_are_replaced(tmp_path, monkeypatch):
    lb = _keyed_plain_record(tmp_path, monkeypatch)
    before = _snapshot(lb.root)

    def drop_the_tier(line: dict) -> dict:
        del line["tier"]
        return line

    with pytest.raises(NotIntact, match=r"the new files do not verify") as e:
        lb._rewrite("logbook.rewriting", drop_the_tier, True, None)
    assert "line 1: tier is missing" in str(e.value) and str(e.value).endswith("the record was not replaced")
    assert _snapshot(lb.root) == before and _staging(lb.root) == []
    assert lb.verify()[2] == []


# -- migrate: the same gate under the 0.1 rule --------------------------------------------------------


def test_migrate_refuses_a_line_whose_text_changed_under_its_0_1_hash_and_touches_nothing(tmp_path):
    lb, old = legacy_logbook(tmp_path / "lb")
    altered = _alter(lb, 3, text=ALTERED)
    before = _snapshot(lb.root)

    with pytest.raises(NotIntact) as e:
        lb.migrate()

    message = str(e.value)
    assert message.startswith("line 3: hash does not recompute"), message
    assert f"id {altered['id']}" in message
    assert message.endswith("the 0.1 record is not intact; nothing was changed")
    assert _snapshot(lb.root) == before and _staging(lb.root) == []
    assert not (lb.root / "logbook-0.1").exists()
    assert (
        lb.meta["format"] == "logbook/0.1" and lb.meta["head"] == old[-1]["hash"] and "lineage" not in lb.meta
    )
    assert lb.index_path.exists()


def test_migrate_checks_the_0_1_hashes_under_the_0_1_rule_not_the_current_one(tmp_path):
    """A 0.1 record whose hashes were computed with the current rule is not a 0.1 record: the first
    line where the two rules disagree (`120.0`) fails under the rule its format names."""
    lb, old = legacy_logbook(tmp_path / "lb")
    rehashed, prev = [], GENESIS
    for line in sorted(old, key=lambda row: row["seq"]):
        line = dict(line, prev=prev)
        line["hash"] = prev = compute_hash(line)
        rehashed.append(line)
    for path in lb.files():
        _write_rows(path, [row for row in rehashed if row["at"][:7] == f"{path.parent.name}-{path.stem}"])
    meta = lb.meta
    meta["head"] = prev
    (lb.root / "logbook.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    before = _snapshot(lb.root)
    with pytest.raises(NotIntact, match=r"^line 1: hash does not recompute; id "):
        lb.migrate()
    assert _snapshot(lb.root) == before and _staging(lb.root) == []


def test_cli_migrate_exits_2_naming_the_line_and_touches_nothing(tmp_path, monkeypatch, capsys):
    from logbook import cli

    lb, _ = legacy_logbook(tmp_path / "lb")
    altered = _alter(lb, 1, text=None, kind="note")  # a 0.1 line whose kind was changed under its hash
    before = _snapshot(lb.root)
    with pytest.raises(SystemExit) as e:
        cli.main(["repair", "migrate", "--root", str(lb.root)])
    out, err = capsys.readouterr()
    assert e.value.code == 2 and out == ""
    assert "line 1: hash does not recompute" in err and altered["id"] in err and "nothing was changed" in err
    assert _snapshot(lb.root) == before and lb.meta["format"] == "logbook/0.1"


def test_a_clean_0_1_record_migrates_to_the_same_bytes_as_before_the_gate(tmp_path):
    lb, old = legacy_logbook(tmp_path / "lb")
    result = lb.migrate()
    for (year, month), lines in MIGRATED_BEFORE.items():
        assert (lb.log_dir / year / month).read_bytes() == "".join(f"{line}\n" for line in lines).encode(
            "utf-8"
        )
    others = [f for f in lb.files() if (f.parent.name, f.name) not in MIGRATED_BEFORE]
    assert len(others) == 1  # the month of the run, holding the migration line alone
    (migration,) = _rows(others[0])
    assert (
        migration["kind"] == "migration"
        and migration["prev"] == json.loads(MIGRATED_BEFORE["2026", "03.jsonl"][-1])["hash"]
    )
    assert migration["payload"]["from_head"] == old[-1]["hash"] == result["from_head"]
    assert lb.verify()[2] == [] and lb.meta["format"] == FORMAT
    assert (lb.root / "logbook-0.1").is_dir() and _staging(lb.root) == ["logbook-0.1"]


def test_the_0_1_rule_the_gate_reads_is_the_one_the_fixture_was_written_with(tmp_path):
    from test_migrate import old_hash

    from logbook.core.store import hash_0_1

    _, old = legacy_logbook(tmp_path / "lb")
    assert (
        [hash_0_1(line) for line in old] == [old_hash(line) for line in old] == [line["hash"] for line in old]
    )
    assert any(compute_hash(line) != line["hash"] for line in old), "the fixture tells the two rules apart"
