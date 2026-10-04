"""`logbook import-backup <folder>` on an encrypted iOS backup: the keybag is unlocked with
LOGBOOK_BACKUP_PASSWORD, Manifest.db and every file are decrypted while they are copied, and the
adapters run on the copies exactly as for an unencrypted backup.

The backup is built here, synthetically, from a test password: a keybag with a low iteration count,
class keys wrapped with the passcode key, per-file keys wrapped with the class keys, files and
Manifest.db encrypted with AES-256-CBC and a zero IV. Never a real backup; nobody in it exists."""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import sqlite3
import struct
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.keywrap import aes_key_wrap

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_apple_health import LINES as HEALTH_LINES
from test_apple_health import _store as _health_store
from test_imessage import _store as _sms_store
from test_ios_calls import LINES as CALL_LINES
from test_ios_calls import _store as _call_store
from test_safari import LINES as SAFARI_LINES
from test_safari import _store as _safari_store

from logbook import cli, ios_backup, ios_backup_crypto
from logbook.core.store import Logbook

UDID = "00008030-000A1B2C3D4E5F61"
PASSWORD = "correct horse battery staple"
HEALTH = "HealthDomain"
ITERATIONS = 10  # a real keybag says 10,000,000 (DPIC) and 10,000 (ITER); the format does not care
ZERO_IV = bytes(16)
# protection classes as iOS numbers them: 1 complete, 2 unless open, 3 until first unlock, 4 none
CLASSES = (1, 2, 3, 4, 11)


# -- building a keybag and an encrypted backup --------------------------------------------------


def _tlv(tag: str, data: bytes | int) -> bytes:
    body = struct.pack(">L", data) if isinstance(data, int) else data
    return tag.encode("ascii") + struct.pack(">L", len(body)) + body


def _passcode_key(password: str, salt: bytes, iterations: int, dpsl: bytes, dpic: int) -> bytes:
    first = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), dpsl, dpic, 32)
    return hashlib.pbkdf2_hmac("sha1", first, salt, iterations, 32)


def _keybag(password: str, class_keys: dict[int, bytes], *, legacy: bool = False) -> bytes:
    """A BackupKeyBag blob: the header records, then one UUID/CLAS/WRAP/KTYP/WPKY group per class.
    `legacy` leaves out DPWT/DPIC/DPSL, as keybags before iOS 10.2 did (one PBKDF2-SHA1 pass)."""
    salt, dpsl = b"\x11" * 20, b"\x22" * 20
    if legacy:
        pk = hashlib.pbkdf2_hmac("sha1", password.encode("utf-8"), salt, ITERATIONS, 32)
    else:
        pk = _passcode_key(password, salt, ITERATIONS, dpsl, ITERATIONS)
    out = _tlv("VERS", 3) + _tlv("TYPE", 1) + _tlv("UUID", b"\x33" * 16) + _tlv("HMCK", b"\x44" * 40)
    out += _tlv("WRAP", 1) + _tlv("SALT", salt) + _tlv("ITER", ITERATIONS)
    if not legacy:
        out += _tlv("DPWT", 0) + _tlv("DPIC", ITERATIONS) + _tlv("DPSL", dpsl)
    for cls, key in class_keys.items():
        out += _tlv("UUID", bytes([cls]) * 16) + _tlv("CLAS", cls) + _tlv("WRAP", 2) + _tlv("KTYP", 0)
        out += _tlv("WPKY", aes_key_wrap(pk, key))
    return out


def _encrypt(key: bytes, data: bytes) -> bytes:
    """AES-256-CBC, zero IV, PKCS#7 padding — how a backup stores a file."""
    pad = 16 - len(data) % 16
    enc = Cipher(algorithms.AES(key), modes.CBC(ZERO_IV)).encryptor()
    return enc.update(data + bytes([pad]) * pad) + enc.finalize()


def _file_id(domain: str, relative_path: str) -> str:
    return hashlib.sha1(f"{domain}-{relative_path}".encode()).hexdigest()


def _file_plist(size: int, protection_class: int, wrapped_key: bytes | None) -> bytes:
    """The Files.file blob: an NSKeyedArchiver plist whose root is the MBFile dict."""
    root: dict[str, object] = {
        "$class": plistlib.UID(3),
        "Size": size,
        "ProtectionClass": protection_class,
        "Mode": 0o100644,
        "Flags": 0,
    }
    objects: list[object] = ["$null", root]
    if wrapped_key is not None:
        root["EncryptionKey"] = plistlib.UID(2)
        objects.append(
            {"$class": plistlib.UID(4), "NS.data": struct.pack("<L", protection_class) + wrapped_key}
        )
    else:
        objects.append("$null")
    objects.append({"$classname": "MBFile", "$classes": ["MBFile", "NSObject"]})
    objects.append({"$classname": "NSMutableData", "$classes": ["NSMutableData", "NSData", "NSObject"]})
    return plistlib.dumps(
        {
            "$version": 100000,
            "$archiver": "NSKeyedArchiver",
            "$top": {"root": plistlib.UID(1)},
            "$objects": objects,
        },
        fmt=plistlib.FMT_BINARY,
    )


def _random(seed: int, n: int = 32) -> bytes:
    return hashlib.sha256(f"key-{seed}".encode()).digest()[:n]


class Built:
    """What the builder made: the folder and, per (domain, path), the plaintext bytes and class."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.plain: dict[tuple[str, str], bytes] = {}
        self.classes: dict[tuple[str, str], int] = {}
        self.stored: dict[tuple[str, str], Path] = {}  # the encrypted blob in the backup folder
        self.manifest_db_plain: bytes = b""


def _encrypted_backup(
    tmp_path: Path,
    password: str = PASSWORD,
    *,
    files: dict[tuple[str, str], tuple[Path, int]] | None = None,
    claimed: dict[tuple[str, str], int] | None = None,
    legacy: bool = False,
    lockdown: bool = True,
) -> Built:
    """A tiny encrypted backup. `files` maps (domain, relativePath) → (plaintext file, protection
    class); by default sms.db with one attachment, the call log, Health's secure store and Safari's
    history. `claimed` overrides the `Size` the manifest records for a file (a stale one, as a real
    backup can carry)."""
    stage = tmp_path / "stage"
    stage.mkdir()
    if files is None:
        (stage / "sms").mkdir()
        sms = _sms_store(stage / "sms")
        calls = _call_store(stage)
        health = _health_store(stage / "health")  # synthetic; healthdb.sqlite beside it names the sources
        safari = _safari_store(stage / "safari")
        files = {
            ("HomeDomain", "Library/SMS/sms.db"): (sms, 3),
            ("MediaDomain", "Library/SMS/Attachments/ab/12/AT-100/stern.jpg"): (
                sms.parent / "Attachments" / "ab" / "12" / "AT-100" / "stern.jpg",
                4,
            ),
            ("HomeDomain", "Library/CallHistoryDB/CallHistory.storedata"): (calls, 3),
            (HEALTH, "Health/healthdb_secure.sqlite"): (health, 1),
            (HEALTH, "Health/healthdb.sqlite"): (health.parent / "healthdb.sqlite", 1),
            ("HomeDomain", "Library/Safari/History.db"): (safari, 2),
        }
    backup = tmp_path / "backup"
    backup.mkdir()
    built = Built(backup)
    class_keys = {cls: _random(cls) for cls in CLASSES}
    rows: list[tuple[str, str, str, int, bytes | None]] = []
    rows.append((_file_id("HomeDomain", "Library"), "HomeDomain", "Library", 2, _file_plist(0, 4, None)))
    for n, ((domain, rel), (src, cls)) in enumerate(sorted(files.items())):
        data = src.read_bytes()
        file_key = _random(100 + n)
        fid = _file_id(domain, rel)
        target = backup / fid[:2] / fid
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_encrypt(file_key, data))
        claimed_size = (claimed or {}).get((domain, rel), len(data))
        rows.append(
            (fid, domain, rel, 1, _file_plist(claimed_size, cls, aes_key_wrap(class_keys[cls], file_key)))
        )
        built.stored[(domain, rel)] = target
        built.plain[(domain, rel)] = data
        built.classes[(domain, rel)] = cls
    plain_db = stage / "Manifest.db"
    con = sqlite3.connect(plain_db)
    try:
        con.execute(
            "CREATE TABLE Files (fileID TEXT PRIMARY KEY, domain TEXT, relativePath TEXT, flags INTEGER,"
            " file BLOB)"
        )
        con.executemany("INSERT INTO Files VALUES (?,?,?,?,?)", rows)
        con.commit()
    finally:
        con.close()
    built.manifest_db_plain = plain_db.read_bytes()
    manifest_key = _random(999)
    (backup / "Manifest.db").write_bytes(_encrypt(manifest_key, built.manifest_db_plain))
    plist: dict[str, object] = {
        "IsEncrypted": True,
        "Version": "10.0",
        "BackupKeyBag": _keybag(password, class_keys, legacy=legacy),
        "ManifestKey": struct.pack("<L", 4) + aes_key_wrap(class_keys[4], manifest_key),
    }
    if lockdown:
        plist["Lockdown"] = {"UniqueDeviceID": UDID, "ProductVersion": "17.5"}
    with (backup / "Manifest.plist").open("wb") as fh:
        plistlib.dump(plist, fh)
    return built


def _snapshot(folder: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for f in sorted(folder.rglob("*")):
        out[f.relative_to(folder).as_posix()] = (
            hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() else "dir"
        )
    return out


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    monkeypatch.setenv("LOGBOOK_DIAL_PREFIX", "47")
    monkeypatch.delenv("LOGBOOK_IMESSAGE_HASH_MEDIA", raising=False)
    monkeypatch.delenv("LOGBOOK_BACKUP_PASSWORD", raising=False)
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook.init(root, "Europe/Oslo")


def _run(*args: str) -> None:
    cli.main(["import-backup", *args])


# -- round trip -----------------------------------------------------------------------------------


def test_import_backup_decrypts_copies_byte_for_byte_and_runs_the_adapters(lb, tmp_path, monkeypatch, capsys):
    built = _encrypted_backup(tmp_path)
    before = _snapshot(built.folder)
    monkeypatch.setenv("LOGBOOK_BACKUP_PASSWORD", PASSWORD)
    _run(str(built.folder))
    captured = capsys.readouterr()
    out = captured.out
    assert _snapshot(built.folder) == before  # the backup is only ever read
    assert PASSWORD not in out and PASSWORD not in captured.err
    inbox = lb.root / "inbox" / f"ios-backup-{UDID}"
    # the same layout as an unencrypted backup gives: the adapters ran unchanged on the copies
    sms = inbox / "imessage" / "sms.db"
    assert sms.read_bytes() == built.plain[("HomeDomain", "Library/SMS/sms.db")]
    photo = inbox / "imessage" / "Attachments" / "ab" / "12" / "AT-100" / "stern.jpg"
    assert (
        photo.read_bytes() == built.plain[("MediaDomain", "Library/SMS/Attachments/ab/12/AT-100/stern.jpg")]
    )
    assert "added 13 lines from imessage" in out
    # the call log, which only an encrypted backup carries, runs through its own adapter
    store = inbox / "ios-calls" / "CallHistory.storedata"
    assert store.read_bytes() == built.plain[("HomeDomain", "Library/CallHistoryDB/CallHistory.storedata")]
    assert f"added {CALL_LINES} lines from ios-calls" in out
    assert f"valid — {13 + CALL_LINES + HEALTH_LINES + SAFARI_LINES} lines" in out
    # Health: the companion is copied first, then the store, and the adapter runs on the store with
    # the companion beside it, so the lines carry the source names
    health = inbox / "health" / "healthdb_secure.sqlite"
    assert health.read_bytes() == built.plain[(HEALTH, "Health/healthdb_secure.sqlite")]
    companion = inbox / "health" / "healthdb.sqlite"
    assert companion.read_bytes() == built.plain[(HEALTH, "Health/healthdb.sqlite")]
    assert out.index("health: healthdb.sqlite") < out.index("health: healthdb_secure.sqlite")
    assert f"added {HEALTH_LINES} lines from apple-health" in out
    assert "copied, read beside healthdb_secure.sqlite" in out
    named = [ln for ln in lb.lines() if ln["source"] == "apple-health" and "source_name" in ln["payload"]]
    assert named and {ln["payload"]["source_name"] for ln in named} == {"Apple Watch", "iPhone"}
    # Safari is copied out and read by its adapter (RFC 0017)
    safari = inbox / "safari" / "History.db"
    assert safari.read_bytes() == built.plain[("HomeDomain", "Library/Safari/History.db")]
    assert "safari: History.db" in out and f"added {SAFARI_LINES} lines from safari" in out
    assert "ios-calls: CallHistory.storedata" in out and "CallHistory.storedata not found" not in out
    assert "healthdb.sqlite not found" not in out and "healthdb_secure.sqlite not found" not in out
    # the decrypted Manifest.db is beside the copies, and it is the plaintext
    assert (inbox / "Manifest.db").read_bytes() == built.manifest_db_plain
    # the manifest of copies records the encryption and each file's protection class
    copies = json.loads((inbox / "copies.json").read_text(encoding="utf-8"))
    assert copies["encrypted"] is True
    by_path = {(c["domain"], c["path"]): c for c in copies["files"]}
    assert by_path[("HomeDomain", "Library/SMS/sms.db")] == {
        "domain": "HomeDomain",
        "path": "Library/SMS/sms.db",
        "copy": "imessage/sms.db",
        "bytes": len(built.plain[("HomeDomain", "Library/SMS/sms.db")]),
        "encrypted": True,
        "protection_class": 3,
        "source": "imessage",
    }
    assert by_path[("HomeDomain", "Library/CallHistoryDB/CallHistory.storedata")]["copy"] == (
        "ios-calls/CallHistory.storedata"
    )
    assert by_path[(HEALTH, "Health/healthdb_secure.sqlite")]["protection_class"] == 1
    assert by_path[(HEALTH, "Health/healthdb_secure.sqlite")]["copy"] == "health/healthdb_secure.sqlite"
    assert by_path[("HomeDomain", "Library/Safari/History.db")]["protection_class"] == 2
    assert "key" not in json.dumps(copies).lower().replace("encryption", "")  # never a key


def test_import_backup_warns_when_the_manifest_size_is_stale_and_the_blob_decrypts_exactly(
    lb, tmp_path, monkeypatch, capsys
):
    """Apple records a file's size on the phone; the stored blob can be another size. The real check
    is the decrypted length against the blob less its PKCS#7 padding; the manifest's Size is only
    a warning naming the file and both sizes, never an error."""
    key = ("HomeDomain", "Library/Safari/History.db")
    built = _encrypted_backup(tmp_path, claimed={key: 35_745_792})
    real = len(built.plain[key])
    assert real != 35_745_792
    monkeypatch.setenv("LOGBOOK_BACKUP_PASSWORD", PASSWORD)
    _run(str(built.folder))  # no SystemExit: the copy succeeds
    captured = capsys.readouterr()
    inbox = lb.root / "inbox" / f"ios-backup-{UDID}"
    assert (inbox / "safari" / "History.db").read_bytes() == built.plain[key]
    warnings = [line for line in captured.out.splitlines() if "warning" in line]
    assert len(warnings) == 1
    assert "Library/Safari/History.db" in warnings[0]
    assert f"{real:,}" in warnings[0] and "35,745,792" in warnings[0]
    assert f"valid — {13 + CALL_LINES + HEALTH_LINES + SAFARI_LINES} lines" in captured.out
    assert captured.err == ""
    copies = json.loads((inbox / "copies.json").read_text(encoding="utf-8"))
    by_path = {(c["domain"], c["path"]): c for c in copies["files"]}
    entry = by_path[key]
    assert entry["bytes"] == real
    assert "Library/Safari/History.db" in entry["warning"] and "35,745,792" in entry["warning"]
    assert all("warning" not in c for k, c in by_path.items() if k != key)


def test_import_backup_fails_when_the_decrypted_length_is_not_the_blob_less_its_padding(
    lb, tmp_path, monkeypatch, capsys
):
    """A blob whose last block does not decrypt to PKCS#7 padding is not the plaintext the manifest
    describes: the copy fails as before, with both lengths in the message."""
    key = ("HomeDomain", "Library/Safari/History.db")
    built = _encrypted_backup(tmp_path)
    blob = built.stored[key]
    data = blob.read_bytes()
    blob.write_bytes(data[:-16] + bytes(b ^ 0x5A for b in data[-16:]))  # the last cipher block, damaged
    monkeypatch.setenv("LOGBOOK_BACKUP_PASSWORD", PASSWORD)
    with pytest.raises(SystemExit) as e:
        _run(str(built.folder))
    assert e.value.code == 1
    err = capsys.readouterr().err
    assert "Library/Safari/History.db" in err
    assert f"{len(data):,}" in err and f"{len(built.plain[key]):,}" in err
    assert "padding" in err
    inbox = lb.root / "inbox" / f"ios-backup-{UDID}"
    assert not (inbox / "copies.json").exists()


def test_import_backup_encrypted_again_adds_nothing(lb, tmp_path, monkeypatch, capsys):
    built = _encrypted_backup(tmp_path)
    monkeypatch.setenv("LOGBOOK_BACKUP_PASSWORD", PASSWORD)
    _run(str(built.folder))
    capsys.readouterr()
    _run(str(built.folder))
    out = capsys.readouterr().out
    assert "added 0 lines from imessage" in out and "added 0 lines from ios-calls" in out
    assert "added 0 lines from apple-health" in out
    assert f"valid — {13 + CALL_LINES + HEALTH_LINES + SAFARI_LINES} lines" in out


def test_import_backup_encrypted_dry_run_decrypts_only_the_manifest(lb, tmp_path, monkeypatch, capsys):
    built = _encrypted_backup(tmp_path)
    monkeypatch.setenv("LOGBOOK_BACKUP_PASSWORD", PASSWORD)
    _run(str(built.folder), "--dry-run")
    out = capsys.readouterr().out
    inbox = lb.root / "inbox" / f"ios-backup-{UDID}"
    assert sorted(p.name for p in inbox.iterdir()) == ["Manifest.db"]
    assert "imessage: sms.db" in out and "health: healthdb_secure.sqlite" in out
    assert f"{len(built.plain[('HomeDomain', 'Library/SMS/sms.db')]):,} bytes" in out  # the plaintext size
    assert "dry run" in out and "encrypted" in out and "added" not in out
    assert lb.verify()[0] == 0


def test_import_backup_reads_a_keybag_from_before_ios_10_2(lb, tmp_path, monkeypatch, capsys):
    built = _encrypted_backup(tmp_path, legacy=True)
    monkeypatch.setenv("LOGBOOK_BACKUP_PASSWORD", PASSWORD)
    _run(str(built.folder))
    out = capsys.readouterr().out
    assert "added 13 lines from imessage" in out


# -- refusals ---------------------------------------------------------------------------------------


def test_import_backup_wrong_password_fails_before_any_file_is_touched(lb, tmp_path, monkeypatch, capsys):
    built = _encrypted_backup(tmp_path)
    before = _snapshot(built.folder)
    monkeypatch.setenv("LOGBOOK_BACKUP_PASSWORD", "not the password")
    with pytest.raises(SystemExit) as e:
        _run(str(built.folder))
    assert e.value.code == 2
    captured = capsys.readouterr()
    assert captured.err.count("\n") == 1
    assert "LOGBOOK_BACKUP_PASSWORD" in captured.err and "keybag" in captured.err
    assert "not the password" not in captured.err and "not the password" not in captured.out
    assert _snapshot(built.folder) == before
    assert not any((lb.root / "inbox").glob("ios-backup-*"))
    assert lb.verify()[0] == 0


def test_import_backup_without_a_password_says_which_variable_to_set(lb, tmp_path, capsys):
    built = _encrypted_backup(tmp_path)
    with pytest.raises(SystemExit) as e:
        _run(str(built.folder))
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "encrypted" in err and "LOGBOOK_BACKUP_PASSWORD" in err
    assert not any((lb.root / "inbox").glob("ios-backup-*"))


def test_import_backup_without_the_extra_says_how_to_install_it(lb, tmp_path, monkeypatch, capsys):
    built = _encrypted_backup(tmp_path)
    monkeypatch.setenv("LOGBOOK_BACKUP_PASSWORD", PASSWORD)
    for name in [m for m in sys.modules if m == "cryptography" or m.startswith("cryptography.")]:
        monkeypatch.setitem(sys.modules, name, None)  # an import of any of them now raises ImportError
    with pytest.raises(SystemExit) as e:
        _run(str(built.folder))
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and 'pip install "openlogbook[encrypted]"' in err
    assert not any((lb.root / "inbox").glob("ios-backup-*"))


def test_import_backup_encrypted_without_a_keybag_is_not_a_backup(lb, tmp_path, monkeypatch, capsys):
    built = _encrypted_backup(tmp_path)
    with (built.folder / "Manifest.plist").open("rb") as fh:
        plist = plistlib.load(fh)
    del plist["BackupKeyBag"]
    with (built.folder / "Manifest.plist").open("wb") as fh:
        plistlib.dump(plist, fh)
    monkeypatch.setenv("LOGBOOK_BACKUP_PASSWORD", PASSWORD)
    with pytest.raises(SystemExit) as e:
        _run(str(built.folder))
    assert e.value.code == 2
    assert "BackupKeyBag" in capsys.readouterr().err


# -- the module ----------------------------------------------------------------------------------


def test_keybag_unlocks_and_unwraps_class_keys():
    class_keys = {cls: _random(cls) for cls in CLASSES}
    bag = ios_backup_crypto.Keybag.parse(_keybag(PASSWORD, class_keys))
    assert bag.iterations == ITERATIONS and bag.dpic == ITERATIONS
    bag.unlock(PASSWORD)
    file_key = _random(7)
    assert bag.unwrap(3, aes_key_wrap(class_keys[3], file_key)) == file_key
    assert sorted(bag.classes) == sorted(CLASSES)
    with pytest.raises(ios_backup_crypto.DecryptError, match="protection class 9"):
        bag.unwrap(9, aes_key_wrap(class_keys[3], file_key))
    with pytest.raises(ios_backup_crypto.DecryptError, match="40 bytes"):
        bag.unwrap(3, b"short")


def test_keybag_wrong_password_is_detected_on_the_first_class_key():
    bag = ios_backup_crypto.Keybag.parse(_keybag(PASSWORD, {4: _random(4)}))
    with pytest.raises(ios_backup_crypto.WrongPassword):
        bag.unlock("something else")
    with pytest.raises(ios_backup_crypto.DecryptError, match="locked"):
        bag.unwrap(4, b"\0" * 40)


def test_keybag_skips_a_class_key_wrapped_with_the_device_key():
    """WRAP bit 1 means the device's own key (never on a host): the class stays unavailable."""
    blob = _keybag(PASSWORD, {4: _random(4)})
    blob = blob.replace(_tlv("WRAP", 2), _tlv("WRAP", 3))
    bag = ios_backup_crypto.Keybag.parse(blob)
    bag.unlock(PASSWORD)
    assert bag.classes == ()
    with pytest.raises(ios_backup_crypto.DecryptError, match="protection class 4"):
        bag.unwrap(4, b"\0" * 40)


def test_keybag_rejects_a_blob_that_is_not_a_keybag():
    with pytest.raises(ios_backup_crypto.DecryptError):
        ios_backup_crypto.Keybag.parse(b"not a keybag at all")
    with pytest.raises(ios_backup_crypto.DecryptError, match="SALT"):
        ios_backup_crypto.Keybag.parse(_tlv("VERS", 3) + _tlv("ITER", 10))


@pytest.mark.parametrize("size", [0, 1, 15, 16, 17, 64, 1000, 4096 + 5])
def test_decrypt_file_streams_in_chunks_and_strips_the_padding(tmp_path, size):
    key = _random(1)
    plain = os.urandom(size)
    src = tmp_path / "enc"
    src.write_bytes(_encrypt(key, plain))
    dest = tmp_path / "dec"
    done = ios_backup_crypto.decrypt_file(src, dest, key, size=size, chunk=64)
    assert done.written == size and done.padding == 16 - size % 16 and dest.read_bytes() == plain
    # without a size from the manifest, PKCS#7 padding decides
    done = ios_backup_crypto.decrypt_file(src, dest, key, size=None, chunk=64)
    assert done.written == size and done.padding == 16 - size % 16 and dest.read_bytes() == plain


def test_decrypt_file_prefers_valid_padding_over_a_stale_size_in_the_last_block(tmp_path):
    key = _random(4)
    plain = os.urandom(20)  # 2 blocks stored; 12 bytes of padding
    src = tmp_path / "enc"
    src.write_bytes(_encrypt(key, plain))
    dest = tmp_path / "dec"
    done = ios_backup_crypto.decrypt_file(src, dest, key, size=25)
    assert done.written == 20 and done.padding == 12 and dest.read_bytes() == plain


def test_decrypt_file_without_padding_keeps_every_byte(tmp_path):
    """A store encrypted without padding (a whole number of blocks): the manifest's size, or if
    there is none, a last block that is not PKCS#7, keeps everything."""
    key = _random(2)
    plain = bytes(range(256)) * 16  # 4096 bytes; the last byte is 0xff, never a padding value
    enc = Cipher(algorithms.AES(key), modes.CBC(ZERO_IV)).encryptor()
    src = tmp_path / "enc"
    src.write_bytes(enc.update(plain) + enc.finalize())
    dest = tmp_path / "dec"
    done = ios_backup_crypto.decrypt_file(src, dest, key, size=4096)
    assert done.written == 4096 and done.padding == 0 and dest.read_bytes() == plain
    done = ios_backup_crypto.decrypt_file(src, dest, key, size=None)
    assert done.written == 4096 and done.padding == 0 and dest.read_bytes() == plain


def test_decrypt_file_refuses_a_file_that_is_not_whole_blocks(tmp_path):
    src = tmp_path / "enc"
    src.write_bytes(b"\0" * 33)
    with pytest.raises(ios_backup_crypto.DecryptError, match="33 bytes"):
        ios_backup_crypto.decrypt_file(src, tmp_path / "dec", _random(3))
    assert not (tmp_path / "dec").exists()


def test_manifest_reads_file_keys_and_classes_after_unlock(tmp_path, monkeypatch):
    built = _encrypted_backup(tmp_path)
    manifest = ios_backup.Manifest(built.folder)
    assert manifest.encrypted is True and manifest.udid == UDID
    assert manifest.file("HomeDomain", "Library/SMS/sms.db") is None  # locked: nothing can be read
    manifest.unlock(PASSWORD, tmp_path / "out" / "Manifest.db")
    found = manifest.file("HomeDomain", "Library/SMS/sms.db")
    assert found is not None
    assert found.size == len(built.plain[("HomeDomain", "Library/SMS/sms.db")])
    assert found.protection_class == 3 and found.key is not None and len(found.key) == 32
    assert "key=" not in repr(found) and found.key.hex() not in repr(found)
    media = list(manifest.files_under("MediaDomain", "Library/SMS/Attachments"))
    assert [m.protection_class for m in media] == [4]
    assert [s.name for s in ios_backup.EXTRAS] == ["ios-calls", "health", "health", "safari"]
    assert ios_backup.EXTRAS[0].adapter and not ios_backup.EXTRAS[1].adapter


# -- streaming: the plaintext of a file as chunks, never whole --------------------------------------


@pytest.mark.parametrize("size", [0, 1, 15, 16, 17, 64, 1000, 4096 + 5])
def test_decrypt_chunks_yields_the_plaintext_and_returns_what_it_stripped(tmp_path, size):
    key = _random(1)
    plain = os.urandom(size)
    src = tmp_path / "enc"
    src.write_bytes(_encrypt(key, plain))
    gen = ios_backup_crypto.decrypt_chunks(src, key, size=size, chunk=64)
    out = bytearray()
    while True:
        try:
            piece = next(gen)
        except StopIteration as stop:
            done = stop.value
            break
        assert len(piece) <= 64 + 16
        out += piece
    assert bytes(out) == plain
    assert done.written == size and done.padding == 16 - size % 16


def test_plain_chunks_streams_an_encrypted_file_and_a_plain_one_alike(tmp_path):
    built = _encrypted_backup(tmp_path)
    manifest = ios_backup.Manifest(built.folder)
    manifest.unlock(PASSWORD, tmp_path / "out" / "Manifest.db")
    key = ("MediaDomain", "Library/SMS/Attachments/ab/12/AT-100/stern.jpg")
    found = manifest.file(*key)
    assert found is not None and found.encrypted
    assert b"".join(ios_backup.plain_chunks(found, chunk=16)) == built.plain[key]
    plain = tmp_path / "plain.bin"
    plain.write_bytes(bytes(range(256)) * 5)
    row = ios_backup.BackupFile("HomeDomain", "x/plain.bin", plain, plain.stat().st_size)
    assert b"".join(ios_backup.plain_chunks(row, chunk=100)) == plain.read_bytes()
    assert ios_backup.digest(found) == (hashlib.sha256(built.plain[key]).hexdigest(), len(built.plain[key]))
