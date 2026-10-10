"""`logbook backup --restore-test [DEST] [--to DIR]`: the latest snapshot restored into a temporary
folder, verified there (every sealed line opened when the record seals), compared with what the
record said when the backup was taken and with the live chain, the restore deleted, the outcome in
`state/last-restore-test.json`, which `doctor` reads. A synthetic record of the Oslo persona, who
does not exist; a sealed one with two fresh identities; nothing outside `tmp_path`."""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.contrib import backup, doctor, last_run
from logbook.core import sealing
from logbook.core.store import Logbook

pytest.importorskip("pyrage")

BACKUP_AT = datetime(2026, 10, 3, 3, 0, tzinfo=UTC)
TEST_AT = datetime(2026, 10, 4, 5, 0, 12, tzinfo=UTC)
NOTE = {"schema": "note/v1", "text": "coffee with Kari Nordmann at the marina"}


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """A plain record with two lines; `backup.now()` is the backup's stamp, then the test's."""
    root = tmp_path / "Records" / "Logbook"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    monkeypatch.delenv("OneDrive", raising=False)
    lb = Logbook.init(root, "Europe/Oslo")
    lb.append("2026-10-01T10:00:00Z", "manual", "note", 1, {"schema": "note/v1", "text": "a synthetic note"})
    lb.append("2026-10-02T10:00:00Z", "manual", "note", 2, NOTE)
    stamps = [BACKUP_AT, TEST_AT, TEST_AT, TEST_AT]
    monkeypatch.setattr(backup, "now", lambda: stamps.pop(0))
    monkeypatch.setattr(last_run, "now", lambda: TEST_AT)
    monkeypatch.setattr(doctor, "EXTRAS", ())
    return lb


@pytest.fixture
def sealed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lb: Logbook) -> tuple[Logbook, Path]:
    """The same record, sealing tiers 2 and 3 for two recipients, the first identity's file where
    `LOGBOOK_IDENTITY_FILE` points; the tier-2 line sealed."""
    pairs = [sealing.generate_identity() for _ in range(2)]
    meta = lb.meta
    meta["recipients"] = [recipient for _, recipient in pairs]
    lb._save_meta(meta)
    path = tmp_path / "keys" / "owner.txt"
    sealing.write_identity_file(path, pairs[0][0], "test")
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(path))
    sealed = Logbook(lb.root)
    sealed.seal_all()
    return sealed, path


@pytest.fixture
def dest(tmp_path: Path) -> Path:
    return tmp_path / "Backups"


def _cli(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    try:
        cli.main(["backup", *args])
    except SystemExit as e:
        captured = capsys.readouterr()
        return int(e.code or 0), captured.out, captured.err
    captured = capsys.readouterr()
    return 0, captured.out, captured.err


def _state(lb: Logbook, name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((lb.root / "state" / name).read_text(encoding="utf-8"))
    return data


def _doctor_line(capsys: pytest.CaptureFixture[str], name: str) -> str:
    with contextlib.suppress(SystemExit):
        cli.main(["doctor"])
    out = capsys.readouterr().out
    return next(line for line in out.splitlines() if line.split()[1:2] == [name])


# -- the backup records what the record said -------------------------------------------------------------


def test_a_backup_records_where_it_went_and_what_the_record_said(
    lb: Logbook, dest: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status, _out, _err = _cli(capsys, str(dest))
    assert status == 0
    recorded = _state(lb, "last-backup.json")
    snapshot = dest / lb.meta["owner_id"] / "2026-10-03T030000Z"
    assert recorded == {
        "at": "2026-10-03T03:00:00Z",
        "dest": str(dest),
        "snapshot": str(snapshot),
        "seq": 2,
        "head": lb.meta["head"],
    }
    assert not (snapshot / "state").exists(), "the snapshot leaves state/ out, this file included"


# -- pass ------------------------------------------------------------------------------------------------


def test_the_restore_test_passes_on_a_good_backup_and_leaves_nothing_behind(
    lb: Logbook,
    dest: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _cli(capsys, str(dest))
    lb.append("2026-10-03T10:00:00Z", "manual", "note", 1, {"schema": "note/v1", "text": "after the backup"})
    made: list[Path] = []
    real = backup.tempfile.mkdtemp

    def mkdtemp(**kwargs: Any) -> str:
        made.append(Path(real(**kwargs)))
        return str(made[-1])

    monkeypatch.setattr(backup.tempfile, "mkdtemp", mkdtemp)
    status, out, _err = _cli(capsys, "--restore-test")
    assert status == 0, out
    assert "restore test: 2026-10-03T030000Z" in out
    assert "valid — 2 lines, head " in out and "line 2 of the live chain" in out
    assert "passed; state/last-restore-test.json" in out
    assert [p.exists() for p in made] == [False], "the temporary restore is deleted"
    test = _state(lb, "last-restore-test.json")
    assert test["status"] == "passed" and test["at"] == "2026-10-04T05:00:12Z"
    assert test["seq"] == 2 and test["reason"] is None and test["kept"] is None
    assert test["snapshot"].endswith("2026-10-03T030000Z")
    assert _doctor_line(capsys, "restore-test").startswith("pass  restore-test")


def test_to_keeps_the_restore_where_asked(
    lb: Logbook, dest: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _cli(capsys, str(dest))
    target = tmp_path / "restored"
    status, out, _err = _cli(capsys, "--restore-test", "--to", str(target))
    assert status == 0
    assert f"→ {target} (kept" in out
    assert (target / "logbook.json").exists()
    assert Logbook(target).verify()[2] == []
    assert _state(lb, "last-restore-test.json")["kept"] == str(target)
    status, _out, err = _cli(capsys, "--restore-test", "--to", str(target))
    assert status == 2 and "not empty" in err, "never over anything"


def test_dest_may_be_named_and_a_tilde_is_expanded(
    lb: Logbook, dest: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _cli(capsys, str(dest))
    (lb.root / "state" / "last-backup.json").unlink()
    status, out, _err = _cli(capsys, "--restore-test", str(dest))
    assert status == 0 and "passed" in out


# -- fail ------------------------------------------------------------------------------------------------


def test_a_tampered_backup_fails_and_doctor_fails_with_the_reason(
    lb: Logbook, dest: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _cli(capsys, str(dest))
    snapshot = dest / lb.meta["owner_id"] / "2026-10-03T030000Z"
    [month] = (snapshot / "logbook").rglob("*.jsonl")
    month.write_text(
        month.read_text(encoding="utf-8").replace("Kari Nordmann", "Kari Normann"), encoding="utf-8"
    )
    status, out, _err = _cli(capsys, "--restore-test")
    assert status == 1
    assert "failed: 2026-10-03T030000Z: the copy does not verify" in out
    test = _state(lb, "last-restore-test.json")
    assert test["status"] == "failed" and "does not verify" in test["reason"]
    line = _doctor_line(capsys, "restore-test")
    assert line.startswith(
        "fail  restore-test  failed 2026-10-04 (2026-10-03T030000Z): 2026-10-03T030000Z: the copy"
    )


def test_a_backup_of_another_chain_fails(lb: Logbook, dest: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _cli(capsys, str(dest))
    snapshot = dest / lb.meta["owner_id"] / "2026-10-03T030000Z"
    other = Logbook.init(dest.parent / "other", "Europe/Oslo")
    other.append("2026-10-01T10:00:00Z", "manual", "note", 1, {"schema": "note/v1", "text": "another record"})
    other.append("2026-10-02T10:00:00Z", "manual", "note", 1, {"schema": "note/v1", "text": "of two lines"})
    for name in ("logbook.json", "logbook/2026/10.jsonl"):
        (snapshot / name).write_bytes((other.root / name).read_bytes())
    status, out, _err = _cli(capsys, "--restore-test")
    assert status == 1
    assert "when the backup was taken" in out, "the record said another head"


def test_a_backup_disk_that_is_gone_fails_naming_the_destination(
    lb: Logbook, dest: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _cli(capsys, str(dest))
    backup.shutil.rmtree(dest)
    status, out, _err = _cli(capsys, "--restore-test")
    assert status == 1
    assert f"no snapshot of this record under {dest}" in out and "is the backup disk there?" in out


# -- skipped ---------------------------------------------------------------------------------------------


def test_without_a_backup_recorded_the_test_is_skipped_and_says_what_to_run(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    backup.now()  # no backup was made: its stamp goes unused
    status, out, _err = _cli(capsys, "--restore-test")
    assert status == 2
    assert "skipped: no backup recorded" in out and "logbook backup DEST" in out
    assert _state(lb, "last-restore-test.json")["status"] == "skipped"
    line = _doctor_line(capsys, "restore-test")
    assert line.startswith("warn  restore-test  skipped 2026-10-04: no backup recorded")


def test_a_sealed_record_without_the_identity_is_skipped_with_how_to_enable_it(
    sealed: tuple[Logbook, Path],
    dest: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lb, identity = sealed
    _cli(capsys, str(dest))
    monkeypatch.delenv("LOGBOOK_IDENTITY_FILE")  # the agent's environment never had it
    status, out, _err = _cli(capsys, "--restore-test")
    assert status == 2
    assert "skipped: the record seals tiers 2 and 3" in out
    assert "LOGBOOK_IDENTITY_FILE=<path to the identity file> in ~/.config/logbook/sync.env" in out
    assert str(identity) not in out, "the path named is where the identity is looked for, not where it is"
    test = _state(lb, "last-restore-test.json")
    assert test["status"] == "skipped" and "sync.env" in test["reason"]
    line = _doctor_line(capsys, "restore-test")
    assert line.startswith("warn  restore-test  skipped 2026-10-04: the record seals") and "sync.env" in line


def test_a_sealed_record_with_the_identity_opens_every_sealed_line_and_passes(
    sealed: tuple[Logbook, Path], dest: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lb, _identity = sealed
    _cli(capsys, str(dest))
    status, out, _err = _cli(capsys, "--restore-test")
    assert status == 0, out
    assert _state(lb, "last-restore-test.json")["status"] == "passed"


def test_a_sealed_line_the_identity_cannot_open_fails(
    sealed: tuple[Logbook, Path], dest: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lb, _identity = sealed
    _cli(capsys, str(dest))
    snapshot = dest / lb.meta["owner_id"] / "2026-10-03T030000Z"
    [month] = (snapshot / "logbook").rglob("*.jsonl")
    lines = month.read_text(encoding="utf-8").splitlines()
    sealed_line = json.loads(lines[1])
    assert "payload_enc" in sealed_line
    sealed_line["payload_enc"] = (
        sealed_line["payload_enc"][:-8] + "AAAAAAAA"
    )  # the ciphertext, outside the hash
    lines[1] = json.dumps(sealed_line, separators=(",", ":"))
    month.write_text("\n".join(lines) + "\n", encoding="utf-8")
    status, out, _err = _cli(capsys, "--restore-test")
    assert status == 1
    assert "the copy does not verify: line 2: does not open with this identity" in out


# -- the arguments ---------------------------------------------------------------------------------------


def test_restore_test_takes_at_most_one_path_and_no_keep_or_verify(
    lb: Logbook, dest: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for args in (
        ["--restore-test", str(dest), str(dest)],
        ["--restore-test", "--keep", "3"],
        ["--restore-test", "--verify"],
        ["list", str(dest), "--to", "x"],
        [],
    ):
        status, _out, err = _cli(capsys, *args)
        assert status == 2, args
        assert "backup" in err
