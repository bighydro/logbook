"""`verify` walks the attachment references (SPEC §1.1): a file a line names and the store does not
hold is reported and is not an error; a present plain file whose bytes do not hash to its name is an
error, checked unless `--no-attachment-digests` says not to; with the identity, a sealed file is opened
and a plaintext that does not hash to its name is an error (SPEC §1.1 and §3). `doctor` reflects it.
Every key here is generated for the test; the record is the Oslo persona's and nothing in it is real."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from logbook.contrib import doctor
from logbook.core import attachments, sealing
from logbook.core.attachments import Walk
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
PHOTO = b"\xff\xd8\xff\xe0 a synthetic photo of the Oslo fjord"
MEMO = b"a synthetic voice memo: buy rope for Solvind"
TRANSCRIPT = b"Ola: the ferry to Nesodden leaves at nine.\n"


def _line(lb: Logbook, kind: str, tier: int, payload: dict[str, Any]) -> None:
    lb.append(at="2026-03-01T07:30:00Z", source="manual", kind=kind, tier=tier, payload=payload)


def _photo(lb: Logbook, data: bytes) -> str:
    """A tier 1 photo line pointing at `data` by a SPEC §1.1 reference; plain in any record."""
    lb.attach(data, tier=1)
    _line(lb, "photo", 1, {"schema": "photo/v1", "media": attachments.reference(data, "image/jpeg")})
    return attachments.digest(data)


def _transcript(lb: Logbook, data: bytes) -> str:
    """A tier 2 transcript pointing at `data`: sealed with the file in a record that seals."""
    lb.attach(data, tier=2)
    _line(
        lb, "transcript", 2, {"schema": "transcript/v1", "content": attachments.reference(data, "text/plain")}
    )
    return attachments.digest(data)


def _store(lb: Logbook, sha256: str) -> Path:
    return lb.root / attachments.DIR / sha256


def _verify(lb: Logbook, **walk: bool) -> tuple[list[str], Walk]:
    found = Walk(**walk)
    _seq, _head, errors = lb.verify(walk=found)
    return errors, found


# -- what a line points at ------------------------------------------------------------------------


def test_references_are_the_store_files_a_payload_names():
    stored = attachments.reference(MEMO, "audio/mp4")
    pre_attach = {
        "local_path": "Media/4790000001@s.whatsapp.net/a/b/photo.jpg",
        "sha256": "a" * 64,
        "bytes": 21,
    }
    payload = {
        "schema": "message/v1",
        "media": stored,
        "extra": {
            "media": pre_attach,
            "more_media": [{"media_kind": "image", "media": {**pre_attach, "sha256": "b" * 64}}],
        },
        "attachments": [
            {"filename": "berth.jpg", "media_type": "image/jpeg", "bytes": 4, "sha256": "c" * 64}
        ],
        "page": {"lines": 7, "sha256": "d" * 64},  # a signed day's page: a digest, not a file of the store
        "body": {"sha256": "e" * 64, "bytes": 9, "media_type": "text/plain"},  # hashed and never kept
        "other": {"sha256": "f" * 64, "path": "attachments/" + "0" * 64},  # a path to another name
    }
    assert list(attachments.references(payload)) == [stored["sha256"], "a" * 64, "b" * 64]


# -- a record that seals nothing ------------------------------------------------------------------


@pytest.fixture
def plain_lb(tmp_path: Path) -> Logbook:
    return Logbook.init(tmp_path / "lb", "Europe/Oslo")


def test_an_intact_store_is_checked_and_valid(plain_lb: Logbook):
    _photo(plain_lb, PHOTO)
    _photo(plain_lb, PHOTO)  # two lines, one file: checked once
    _transcript(plain_lb, TRANSCRIPT)
    errors, walk = _verify(plain_lb)
    assert errors == []
    assert (len(walk.named), walk.present, walk.checked, walk.missing) == (2, 2, 2, [])


def test_a_missing_attachment_is_reported_and_is_not_an_error(plain_lb: Logbook):
    _photo(plain_lb, PHOTO)
    gone = _transcript(plain_lb, TRANSCRIPT)
    _store(plain_lb, gone).unlink()
    errors, walk = _verify(plain_lb)
    assert errors == []
    assert walk.missing == [(gone, 2)] and walk.checked == 1


def test_a_corrupted_plain_attachment_is_an_error_naming_the_line(plain_lb: Logbook):
    _photo(plain_lb, PHOTO)
    sha256 = _transcript(plain_lb, TRANSCRIPT)
    _store(plain_lb, sha256).write_bytes(b"Ola: the ferry to Nesodden leaves at ten.\n")
    errors, walk = _verify(plain_lb)
    found = attachments.digest(b"Ola: the ferry to Nesodden leaves at ten.\n")
    assert errors == [
        f"line 2: attachments/{sha256} holds bytes that hash to {found[:12]}…, not its name (SPEC §1.1)"
    ]
    assert walk.checked == 1


def test_no_attachment_digests_leaves_present_plain_files_unhashed(plain_lb: Logbook):
    sha256 = _transcript(plain_lb, TRANSCRIPT)
    _store(plain_lb, sha256).write_bytes(b"corrupted")
    errors, walk = _verify(plain_lb, hash_plain=False)
    assert errors == []
    assert (walk.present, walk.checked, walk.unhashed) == (1, 0, 1)


def test_a_retracted_line_still_names_its_file(plain_lb: Logbook):
    gone = _photo(plain_lb, PHOTO)
    plain_lb.retract(1, "the wrong photo")
    _store(plain_lb, gone).unlink()
    errors, walk = _verify(plain_lb)
    assert errors == [] and walk.missing == [(gone, 1)]


def test_a_file_out_of_seq_order_is_walked_once_when_verify_reads_it_again_sorted(plain_lb: Logbook):
    gone = _transcript(plain_lb, TRANSCRIPT)
    _photo(plain_lb, PHOTO)
    _store(plain_lb, gone).unlink()
    (month,) = plain_lb.files()
    first, second = month.read_bytes().splitlines(keepends=True)
    month.write_bytes(second + first)  # SPEC §3 orders by seq wherever a line is: still valid
    errors, walk = _verify(plain_lb)
    assert errors == []
    assert walk.missing == [(gone, 1)] and (len(walk.named), walk.checked) == (2, 1)


# -- a record that seals tiers 2 and 3: keyless and keyed -----------------------------------------


@pytest.fixture
def keys() -> tuple[list[str], list[str]]:
    pairs = [sealing.generate_identity() for _ in range(2)]
    return [r for _, r in pairs], [s for s, _ in pairs]


@pytest.fixture
def sealed_lb(tmp_path: Path, keys: tuple[list[str], list[str]]) -> Logbook:
    recipients, secrets = keys
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    meta = lb.meta
    meta["recipients"] = recipients
    lb._save_meta(meta)
    sealing.write_identity_file(tmp_path / "keys" / "owner.txt", secrets[0], "test")
    return Logbook(lb.root, identity_file=tmp_path / "keys" / "owner.txt")


def _keyless(lb: Logbook) -> Logbook:
    return Logbook(lb.root, identity_file=lb.root.parent / "nowhere.txt")


def test_sealed_attachments_open_and_check_with_the_identity(sealed_lb: Logbook):
    sha256 = _transcript(sealed_lb, TRANSCRIPT)
    assert sealing.is_sealed_file(_store(sealed_lb, sha256))
    errors, walk = _verify(sealed_lb)
    assert errors == [] and (walk.present, walk.checked, walk.unopened) == (1, 1, 0)
    errors, walk = _verify(_keyless(sealed_lb))
    assert errors == [] and len(walk.named) == 0  # the reference is inside the sealed line


@pytest.mark.parametrize("mode", ["keyless", "keyed"])
def test_a_missing_attachment_is_reported_in_either_mode(sealed_lb: Logbook, mode: str):
    gone = _photo(sealed_lb, PHOTO)
    _store(sealed_lb, gone).unlink()
    lb = _keyless(sealed_lb) if mode == "keyless" else sealed_lb
    errors, walk = _verify(lb)
    assert errors == [] and walk.missing == [(gone, 1)]


def test_a_missing_attachment_a_sealed_line_names_is_reported_with_the_identity(sealed_lb: Logbook):
    gone = _transcript(sealed_lb, TRANSCRIPT)
    _store(sealed_lb, gone).unlink()
    errors, walk = _verify(sealed_lb)
    assert errors == [] and walk.missing == [(gone, 1)]


@pytest.mark.parametrize("mode", ["keyless", "keyed"])
def test_a_corrupted_plain_attachment_is_an_error_in_either_mode(sealed_lb: Logbook, mode: str):
    sha256 = _photo(sealed_lb, PHOTO)  # tier 1: stays plain in a record that seals
    _store(sealed_lb, sha256).write_bytes(PHOTO + b"!")
    lb = _keyless(sealed_lb) if mode == "keyless" else sealed_lb
    errors, _walk = _verify(lb)
    assert len(errors) == 1
    assert errors[0].startswith(f"line 1: attachments/{sha256} holds bytes that hash to ")


def test_a_sealed_file_swapped_for_valid_ciphertext_of_other_bytes_fails_keyed_only(sealed_lb: Logbook):
    named = _photo(sealed_lb, PHOTO)
    _transcript(sealed_lb, PHOTO)  # a tier 2 line names the same bytes, so the one file is sealed
    path = _store(sealed_lb, named)
    assert sealing.is_sealed_file(path)
    path.write_bytes(sealing.seal_bytes(MEMO, sealed_lb.recipients))  # opens, to the wrong plaintext
    errors, walk = _verify(_keyless(sealed_lb))
    assert errors == [] and walk.unopened == 1  # cannot tell without the key (SPEC §1.1)
    errors, _walk = _verify(sealed_lb)
    assert errors == [f"line 1: attachments/{named} opens to bytes that do not hash to its name (SPEC §1.1)"]
    errors, _walk = _verify(sealed_lb, hash_plain=False)  # the flag is the plain files'; this is a MUST
    assert len(errors) == 1


def test_a_sealed_file_that_does_not_open_with_the_identity_is_an_error(sealed_lb: Logbook):
    sha256 = _transcript(sealed_lb, TRANSCRIPT)
    stranger = sealing.generate_identity()[1]
    _store(sealed_lb, sha256).write_bytes(sealing.seal_bytes(TRANSCRIPT, [stranger]))
    errors, _walk = _verify(sealed_lb)
    assert len(errors) == 1
    assert errors[0].startswith(f"line 1: attachments/{sha256} does not open with this identity: ")


def test_keyless_verify_never_opens_a_sealed_file(sealed_lb: Logbook):
    named = _photo(sealed_lb, PHOTO)
    _transcript(sealed_lb, PHOTO)
    _store(sealed_lb, named).write_bytes(sealing.seal_bytes(MEMO, sealed_lb.recipients))
    found = Walk()
    assert sealed_lb.verify(keyed=False, walk=found)[2] == []
    assert found.unopened == 1


# -- the command ----------------------------------------------------------------------------------


def _cli(*args: str, identity: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    if identity is not None:
        env["LOGBOOK_IDENTITY_FILE"] = str(identity)
    return subprocess.run(
        [sys.executable, "-m", "logbook.cli", "verify", *args], env=env, capture_output=True, encoding="utf-8"
    )


def test_cli_verify_lists_a_missing_attachment_and_exits_0(plain_lb: Logbook):
    _photo(plain_lb, PHOTO)
    gone = _transcript(plain_lb, TRANSCRIPT)
    _store(plain_lb, gone).unlink()
    r = _cli("--root", str(plain_lb.root))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "valid — 2 lines" in r.stdout
    assert (
        "attachments: 2 files named by the lines; 1 present, checked against its name; 1 missing" in r.stdout
    )
    assert f"attachments/{gone} (line 2)" in r.stdout


def test_cli_verify_exits_1_on_a_corrupted_attachment_unless_told_not_to_hash(plain_lb: Logbook):
    sha256 = _transcript(plain_lb, TRANSCRIPT)
    _store(plain_lb, sha256).write_bytes(b"corrupted")
    r = _cli("--root", str(plain_lb.root))
    assert r.returncode == 1
    assert f"line 1: attachments/{sha256} holds bytes that hash to" in r.stdout
    r = _cli("--root", str(plain_lb.root), "--no-attachment-digests")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 present, not hashed (--no-attachment-digests)" in r.stdout


def test_cli_verify_keyed_fails_on_a_swapped_sealed_attachment(sealed_lb: Logbook):
    named = _photo(sealed_lb, PHOTO)
    _transcript(sealed_lb, PHOTO)
    _store(sealed_lb, named).write_bytes(sealing.seal_bytes(MEMO, sealed_lb.recipients))
    r = _cli("--root", str(sealed_lb.root), identity=sealed_lb.identity_file)
    assert r.returncode == 1
    assert f"attachments/{named} opens to bytes that do not hash to its name" in r.stdout
    r = _cli("--root", str(sealed_lb.root), "--keyless", identity=sealed_lb.identity_file)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 present, sealed and not opened" in r.stdout


def test_cli_verify_says_nothing_of_attachments_when_no_line_names_one(plain_lb: Logbook):
    _line(plain_lb, "note", 2, {"schema": "note/v1", "text": "Coffee with Ines."})
    r = _cli("--root", str(plain_lb.root))
    assert r.returncode == 0 and "attachments" not in r.stdout


# -- doctor ---------------------------------------------------------------------------------------


def test_doctor_reports_a_missing_attachment_and_still_passes(plain_lb: Logbook):
    gone = _transcript(plain_lb, TRANSCRIPT)
    _store(plain_lb, gone).unlink()
    check = doctor.record_check(plain_lb)
    assert check.status == "pass"
    assert "1 attachment missing (SPEC §1.1 allows it; `logbook import attachments status`)" in check.detail


def test_doctor_looks_for_the_files_and_leaves_their_bytes_to_verify(plain_lb: Logbook):
    sha256 = _transcript(plain_lb, TRANSCRIPT)
    _store(plain_lb, sha256).write_bytes(b"corrupted")
    check = doctor.record_check(plain_lb)
    assert check.status == "pass" and "missing" not in check.detail


# -- conformance (SPEC §6): the heads hold, with the walk -----------------------------------------

SAMPLE = ROOT / "conformance" / "sample-logbook"
SEALED = ROOT / "conformance" / "sample-logbook-sealed"
L1 = "58bfa9e704e3388d44d74e63f1d84765d24df79e92fce3b522fbef53b765d3df"
L2 = "0ab4c3e79bacc9a7c19d074094e81d1674fdf6967ceaf0d1711679e3c11481db"


def test_the_conformance_heads_hold_with_the_walk(tmp_path: Path):
    assert json.loads((ROOT / "conformance" / "expected.json").read_text())["head"] == L1
    assert json.loads((ROOT / "conformance" / "expected-sealed.json").read_text())["head"] == L2
    for lb, head in (
        (Logbook(SAMPLE), L1),
        (Logbook(SEALED, identity_file=tmp_path / "nowhere.txt"), L2),
        (Logbook(SEALED, identity_file=ROOT / "conformance" / "identity.txt"), L2),
    ):
        found = Walk()
        assert lb.verify(walk=found) == (32, head, [])
        assert found.missing == []  # the samples name digests, and no file of a store


@pytest.mark.parametrize("sample, expected", [(SAMPLE, "expected.json"), (SEALED, "expected-sealed.json")])
def test_cli_verify_prints_the_conformance_heads(tmp_path: Path, sample: Path, expected: str):
    shutil.copytree(sample, tmp_path / "lb")
    r = _cli("--root", str(tmp_path / "lb"), "--expect", str(ROOT / "conformance" / expected))
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"valid — 32 lines, head {L1 if sample == SAMPLE else L2}" in r.stdout
