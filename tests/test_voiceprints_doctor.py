"""`doctor`'s `voiceprints` line (RFC 0038 §5.1, §5.2): that the registry is there, when it was written,
with which model and for how many people, never what is in it; a warn when its model is not the
configured one or it will not open; which of the two a record without it is in. Synthetic Oslo
persona (`voiceprints_record`), a fake embedder, no model, no socket."""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest
from persona import TZ
from voiceprints_record import FakeEmbedder, as_text, seal, stored, voiced_record

from logbook import cli
from logbook.contrib import doctor
from logbook.core import sealing, voiceprints
from logbook.core.store import Logbook


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    lb = seal(Logbook.init(root, TZ), monkeypatch, tmp_path)
    voiced_record(lb)
    return Logbook(root)


def _check(lb: Logbook) -> doctor.Check | None:
    fresh = Logbook(lb.root)
    return doctor.voiceprints_check(fresh, doctor.index_state(fresh)[0])


def test_none_yet_then_when_with_which_model_and_for_how_many_never_what(lb: Logbook) -> None:
    check = _check(lb)
    assert (
        check is not None
        and check.status == "pass"
        and "none yet: `logbook setup speakers --rebuild`" in check.detail
    )
    voiceprints.update(lb, FakeEmbedder())
    check = _check(lb)
    assert check is not None and check.status == "pass"
    assert check.detail.startswith("voiceprints.age written ")
    assert f"with {voiceprints.MODEL}, for 1 person, you among them; 3 voices not yet named" in check.detail
    assert not any(text in check.detail for who in ("ines", "kari", "ola") for text in as_text(stored(who)))


def test_another_model_is_a_warn_naming_the_rebuild(lb: Logbook) -> None:
    voiceprints.update(lb, FakeEmbedder(model="example/older-embedding"))
    check = _check(lb)
    assert check is not None and check.status == "warn"
    assert (
        "with example/older-embedding" in check.detail and "logbook setup speakers --rebuild" in check.detail
    )


def test_a_file_that_will_not_open_is_a_warn_and_without_the_identity_a_pass(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    voiceprints.update(lb, FakeEmbedder())
    stranger = tmp_path / "keys" / "stranger.txt"
    sealing.write_identity_file(stranger, sealing.generate_identity()[0], "not this record's")
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(stranger))
    check = _check(lb)
    assert check is not None and check.status == "warn" and "does not open" in check.detail
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(tmp_path / "keys" / "absent.txt"))
    check = _check(lb)
    assert check is not None and check.status == "pass" and "no identity to open it" in check.detail


def test_no_file_and_no_identity_here_says_what_a_write_here_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A machine that holds the record's recipients and not its identity writes no registry, so the
    line says that, as `update` answers it, and not that a rebuild here would make one. The voices
    show without the identity when the transcripts were written before the record had recipients
    (`logbook key seal --all` not yet run)."""
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    plain = Logbook.init(root, TZ)
    voiced_record(plain)
    lb = seal(plain, monkeypatch, tmp_path)
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(tmp_path / "keys" / "absent.txt"))
    assert lb.recipients and not Logbook(root).identities
    check = _check(lb)
    assert check is not None and check.status == "pass"
    assert check.detail == f"none, and none is written here: {voiceprints.NEEDS_IDENTITY}"
    assert "no identity on this machine" in check.detail
    assert "none yet" not in check.detail and "--rebuild" not in check.detail
    summary = voiceprints.update(Logbook(lb.root), FakeEmbedder())
    assert summary.state == voiceprints.NO_IDENTITY and summary.reason == voiceprints.NEEDS_IDENTITY
    assert voiceprints.describe(summary) == f"voiceprints: not written: {voiceprints.NEEDS_IDENTITY}"
    assert not (lb.root / voiceprints.FILE).exists()


def test_a_record_without_recipients_is_said_and_one_without_voices_has_no_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bare = Logbook.init(tmp_path / "bare", TZ)
    assert doctor.voiceprints_check(bare, doctor.index_state(bare)[0]) is None
    voiced_record(bare)
    check = doctor.voiceprints_check(Logbook(bare.root), doctor.index_state(Logbook(bare.root))[0])
    assert check is not None and check.status == "pass" and "names no recipients" in check.detail


def test_doctor_prints_the_line_and_writes_nothing(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    voiceprints.update(lb, FakeEmbedder())
    path = lb.root / voiceprints.FILE
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    with contextlib.suppress(SystemExit):  # another check may fail on a test machine; this one is read
        cli.main(["doctor"])
    out = capsys.readouterr().out
    line = next(row for row in out.splitlines() if "voiceprints" in row and "written" in row)
    assert line.startswith("pass") and "for 1 person, you among them" in line
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert not any(text in out for who in ("ines", "kari", "ola") for text in as_text(stored(who)))
