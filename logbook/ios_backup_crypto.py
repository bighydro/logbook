"""The keys of an encrypted iOS backup (Finder, iTunes with "Encrypt local backup" ticked), and the
streaming decryption of its files. Nothing here reads a backup folder: `ios_backup.Manifest` hands
this module the bytes it finds and gets keys back.

The format is the publicly documented one (the iphone-dataprotection project, since reproduced in
many tools); nothing is derived from Apple's own code. What a backup holds:

- `Manifest.plist` → `BackupKeyBag`: a blob of TLV records (4-byte ASCII tag, 4-byte big-endian
  length, the value). A header — `VERS`, `TYPE`, `UUID`, `HMCK`, `WRAP`, `SALT`, `ITER`, and since
  iOS 10.2 `DPWT`, `DPIC`, `DPSL` — then one group per protection class, each opened by a `UUID`
  record: `CLAS` (the class number), `WRAP` (bit 1: wrapped with the device's key, bit 2: with the
  passcode key), `KTYP`, `WPKY` (the wrapped class key, 40 bytes), sometimes `PBKY`.
- The passcode key: PBKDF2-HMAC-SHA256(password, DPSL, DPIC rounds, 32 bytes), then
  PBKDF2-HMAC-SHA1(that, SALT, ITER rounds, 32 bytes). A keybag without DPSL/DPIC (before iOS
  10.2) does the SHA-1 pass alone on the password.
- A class key is AES-256 key-unwrapped (RFC 3394) from `WPKY` with the passcode key when its
  `WRAP` has bit 2. One with bit 1 needs the device's own key and stays unavailable on a host. The
  unwrap's integrity check is what tells a wrong password: it fails on the first class key.
- `Manifest.plist` → `ManifestKey`: 4 bytes, the protection class (little-endian), then the
  Manifest.db key wrapped (40 bytes) with that class key. Manifest.db is AES-256-CBC with a zero IV.
- In the decrypted Manifest.db, the `file` column of `Files` is an NSKeyedArchiver plist (the
  `MBFile` object): `ProtectionClass`, `Size` (the plaintext size), and `EncryptionKey`, a data
  object of the same 4-byte class prefix and 40-byte wrapped file key. Each file's bytes are
  AES-256-CBC, zero IV, PKCS#7-padded, under the unwrapped file key.

Assumed, not seen in a specification: PKCS#7 padding on every file (valid padding in the last
block is stripped; only a last block that is not valid padding falls back to `Size` from the
manifest when that lies within it, else the file is kept whole — `Size` is what the file measured
on the phone and can be stale against the stored blob); a `TYPE` above 3 or a `VERS` other than 3
is not refused, only the records that are needed are; class numbers are whatever `CLAS` says, so
classes iOS adds later just work.

`cryptography` is the only dependency, imported lazily: the package installs and runs without it,
and an encrypted backup then raises `MissingExtra` naming `openlogbook[crypto]`. PBKDF2 is
hashlib's. The password is a parameter, never stored on the keybag, never in a message; the
derived key and the class keys live only in the `Keybag` object."""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Generator, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

EXTRA = 'pip install "openlogbook[crypto]"'
WRAP_DEVICE = 1
WRAP_PASSCODE = 2
CLASS_KEY_TAGS = frozenset({"CLAS", "WRAP", "WPKY", "KTYP", "PBKY"})
WRAPPED_LEN = 40  # a 32-byte key under RFC 3394: 8 bytes of integrity check in front
KEY_LEN = 32
BLOCK = 16
ZERO_IV = bytes(BLOCK)
CHUNK = 1 << 20  # 1 MiB of ciphertext at a time; a file is never held whole


class MissingExtra(ImportError):
    """`cryptography` is not installed: the `crypto` extra is needed."""

    def __init__(self) -> None:
        super().__init__(f"reading an encrypted backup needs the crypto extra: {EXTRA}")


class DecryptError(Exception):
    """The keybag, a key or a file is not what the format says it should be."""


class WrongPassword(DecryptError):
    """The password does not unwrap the keybag's first class key."""


def _primitives() -> tuple[Any, Any, Any, Any, Any, type[Exception]]:
    """(Cipher, algorithms, modes, aes_key_unwrap, aes_key_wrap, InvalidUnwrap), imported now."""
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.keywrap import InvalidUnwrap, aes_key_unwrap, aes_key_wrap
    except ImportError as e:
        raise MissingExtra() from e
    return Cipher, algorithms, modes, aes_key_unwrap, aes_key_wrap, InvalidUnwrap


def available() -> bool:
    """Whether the extra is installed; nothing else is imported or touched."""
    try:
        _primitives()
    except MissingExtra:
        return False
    return True


def _unwrap(kek: bytes, wrapped: bytes) -> bytes | None:
    """RFC 3394 unwrap, None when the integrity check fails (a wrong key)."""
    _, _, _, aes_key_unwrap, _, invalid = _primitives()
    try:
        key: bytes = aes_key_unwrap(kek, wrapped)
    except invalid:
        return None
    return key


def _records(blob: bytes) -> Iterator[tuple[str, bytes]]:
    """The keybag's TLV records in order; a truncated record ends the walk with an error."""
    i = 0
    while i < len(blob):
        if i + 8 > len(blob):
            raise DecryptError(f"keybag: truncated record header at byte {i}")
        tag = blob[i : i + 4]
        (length,) = struct.unpack(">L", blob[i + 4 : i + 8])
        i += 8
        if i + length > len(blob):
            raise DecryptError(f"keybag: record {tag!r} runs past the end")
        try:
            name = tag.decode("ascii")
        except UnicodeDecodeError as e:
            raise DecryptError(f"keybag: record tag {tag!r} is not a tag") from e
        if not name.isalpha() or not name.isupper():
            raise DecryptError(f"keybag: record tag {name!r} is not a tag")
        yield name, blob[i : i + length]
        i += length


def _u32(data: bytes) -> int:
    if len(data) != 4:
        raise DecryptError(f"keybag: expected a 4-byte number, got {len(data)} bytes")
    return int(struct.unpack(">L", data)[0])


@dataclass
class _ClassKey:
    number: int
    wrap: int
    wrapped: bytes = field(repr=False)
    key: bytes | None = field(default=None, repr=False)


@dataclass
class Keybag:
    """A parsed BackupKeyBag. `unlock` derives the passcode key and unwraps every class key it
    can; `unwrap` then unwraps a file's or the manifest's key under its protection class."""

    salt: bytes = field(repr=False)
    iterations: int
    dpsl: bytes | None = field(repr=False)
    dpic: int | None
    _class_keys: dict[int, _ClassKey] = field(default_factory=dict, repr=False)
    _unlocked: bool = False

    @classmethod
    def parse(cls, blob: bytes) -> Keybag:
        header: dict[str, bytes] = {}
        class_keys: dict[int, _ClassKey] = {}
        current: dict[str, bytes] | None = None
        seen_uuid = False

        def close(group: dict[str, bytes] | None) -> None:
            if group is None:
                return
            if "CLAS" not in group or "WPKY" not in group or "WRAP" not in group:
                return  # a group without a key cannot unwrap anything; it is simply not there
            number = _u32(group["CLAS"])
            class_keys[number] = _ClassKey(number, _u32(group["WRAP"]), group["WPKY"])

        for tag, data in _records(blob):
            if tag == "UUID":
                if seen_uuid:
                    close(current)
                    current = {}
                seen_uuid = True
            elif current is not None and tag in CLASS_KEY_TAGS:
                current[tag] = data
            elif current is None:
                header[tag] = data
        close(current)
        for needed in ("SALT", "ITER"):
            if needed not in header:
                raise DecryptError(f"keybag: no {needed} record")
        dpsl = header.get("DPSL")
        dpic = _u32(header["DPIC"]) if "DPIC" in header else None
        if (dpsl is None) != (dpic is None):
            raise DecryptError("keybag: DPSL and DPIC come together; one is missing")
        return cls(header["SALT"], _u32(header["ITER"]), dpsl, dpic, class_keys)

    def unlock(self, password: str) -> None:
        """Derive the passcode key and unwrap every class key wrapped with it. Raises WrongPassword
        when the first such key does not unwrap; the password itself is not kept."""
        secret = password.encode("utf-8")
        if self.dpsl is not None and self.dpic is not None:
            secret = hashlib.pbkdf2_hmac("sha256", secret, self.dpsl, self.dpic, KEY_LEN)
        passcode_key = hashlib.pbkdf2_hmac("sha1", secret, self.salt, self.iterations, KEY_LEN)
        for ck in self._class_keys.values():
            if ck.wrap & WRAP_DEVICE or not ck.wrap & WRAP_PASSCODE:
                continue  # needs the device's key, or is not wrapped at all: not for a host
            key = _unwrap(passcode_key, ck.wrapped)
            if key is None:
                raise WrongPassword("the password does not unlock this keybag")
            ck.key = key
        self._unlocked = True

    @property
    def classes(self) -> tuple[int, ...]:
        """The protection classes whose key is in hand, ascending."""
        return tuple(sorted(n for n, ck in self._class_keys.items() if ck.key is not None))

    def unwrap(self, protection_class: int, wrapped: bytes) -> bytes:
        """The 32-byte key `wrapped` under `protection_class`'s class key."""
        if not self._unlocked:
            raise DecryptError("keybag: locked; unlock it with the password first")
        if len(wrapped) != WRAPPED_LEN:
            raise DecryptError(f"a wrapped key is {WRAPPED_LEN} bytes; this one is {len(wrapped)}")
        ck = self._class_keys.get(protection_class)
        if ck is None or ck.key is None:
            raise DecryptError(f"no key for protection class {protection_class} in this keybag")
        key = _unwrap(ck.key, wrapped)
        if key is None:
            raise DecryptError(f"a key under protection class {protection_class} does not unwrap")
        return key


def split_class(prefixed: bytes) -> tuple[int, bytes]:
    """`ManifestKey` and a file's `EncryptionKey` alike: (protection class, the wrapped key)."""
    if len(prefixed) != 4 + WRAPPED_LEN:
        raise DecryptError(
            f"a class-prefixed wrapped key is {4 + WRAPPED_LEN} bytes; this one is {len(prefixed)}"
        )
    (number,) = struct.unpack("<L", prefixed[:4])
    return int(number), prefixed[4:]


@dataclass(frozen=True)
class Decrypted:
    """What `decrypt_file` wrote: the plaintext bytes and the PKCS#7 padding it stripped (0 when
    the last block was not valid padding)."""

    written: int
    padding: int


def decrypt_chunks(
    src: Path, key: bytes, size: int | None = None, chunk: int = CHUNK
) -> Generator[bytes, None, Decrypted]:
    """The plaintext of `src` (AES-256-CBC, zero IV), yielded a chunk at a time, never whole; the
    generator's return value is what was written and the padding stripped. Valid PKCS#7 padding in
    the last block is stripped; without it, `size`, the manifest's plaintext size, decides what the
    last block keeps when it lies within it; else every byte is kept."""
    Cipher, algorithms, modes, _, _, _ = _primitives()
    total = src.stat().st_size
    if total % BLOCK:
        raise DecryptError(f"{src.name}: {total} bytes is not a whole number of cipher blocks")
    if chunk % BLOCK:
        raise ValueError("chunk must be a multiple of the block size")
    decryptor = Cipher(algorithms.AES(key), modes.CBC(ZERO_IV)).decryptor()
    written = 0
    tail = b""
    with src.open("rb") as fin:
        while True:
            block = fin.read(chunk)
            if not block:
                break
            out = tail + decryptor.update(block)
            tail = out[-BLOCK:]
            head = out[:-BLOCK]
            if head:
                yield head
            written += len(head)
        decryptor.finalize()
    last, padding = _last_block(tail, written, size)
    if last:
        yield last
    written += len(last)
    return Decrypted(written, padding)


def decrypt_file(src: Path, dest: Path, key: bytes, size: int | None = None, chunk: int = CHUNK) -> Decrypted:
    """Decrypt `src` into `dest` through `decrypt_chunks`. `dest`'s parent must exist; on an error
    nothing is left at `dest`."""
    chunks = decrypt_chunks(src, key, size, chunk)
    try:
        with dest.open("wb") as fout:
            while True:
                try:
                    fout.write(next(chunks))
                except StopIteration as stop:
                    done: Decrypted = stop.value
                    return done
    except BaseException:
        dest.unlink(missing_ok=True)
        raise


def _last_block(tail: bytes, written: int, size: int | None) -> tuple[bytes, int]:
    """(What the last block keeps, the padding stripped from it.)"""
    if tail:
        pad = tail[-1]
        if 1 <= pad <= BLOCK and tail.endswith(bytes([pad]) * pad):
            return tail[:-pad], pad
    if size is not None and written <= size <= written + len(tail):
        return tail[: size - written], 0
    return tail, 0
