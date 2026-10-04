"""The SPEC §1.1 attachment store: `<root>/attachments/<sha256>`, content-addressed, write-once.

`reference(data, media_type)` is the object a payload carries for `data`; it is pure, so an adapter
can name bytes it has not written (a dry run). `write(root, data)` puts the bytes in the store,
once: a digest already present is left alone after its bytes are checked, and a file whose bytes do
not match its name is an error (SPEC §1.1), never overwritten. Written to a temporary name and
renamed into place, so a crash leaves no half file under a digest. `reference_path` and `write_path`
do the same for a file on disk, a chunk at a time, so a recording of a hundred megabytes is never
held whole. `write_chunks` takes a stream of bytes and the digest a line already carries for them
(the attach pass, `logbook attach import-backup`): the bytes are hashed on their way into the
temporary file, and a stream whose digest is not the promised one is removed and refused
(`DigestMismatch`), so the store never holds a file under a name that is not its own.

Sealed files (RFC 0029 §7): when the record names recipients, a file is stored age-sealed under the
same name, the digest of its *plaintext*, so two lines attaching the same bytes still share one file
and a verbatim reference still resolves. The age header in its first 22 bytes is the marker. A plain
file a sealed record attaches again is sealed in place: the content did not change, only its
protection, and that is raised, never lowered. `read_bytes` and `opened` give a reader the plaintext
when the identity is here; `check` tells a verifier whether a file hashes to its name, or that it
could not tell.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import tempfile
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any, BinaryIO

from . import sealing
from .chain import AGE_MAGIC

DIR = "attachments"
CHUNK = 1 << 20
DIGEST = re.compile(r"[0-9a-f]{64}")  # the name of a file in the store (SPEC §1.1), lowercase hex


class DigestMismatch(ValueError):
    """The bytes streamed into the store are not the ones the digest names."""

    def __init__(self, expected: str, actual: str, size: int) -> None:
        super().__init__(
            f"the bytes hash to {actual[:12]}… ({size:,} bytes), not the {expected[:12]}… the line names;"
            " not stored"
        )
        self.expected = expected
        self.actual = actual
        self.size = size


def is_digest(name: str) -> bool:
    """Whether `name` is the name of a file in the store: 64 lowercase hex digits, nothing else."""
    return DIGEST.fullmatch(name) is not None


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_path(path: Path) -> tuple[str, int]:
    """(the file's SHA-256, its length), read a chunk at a time."""
    h = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as fh:
        while chunk := fh.read(CHUNK):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def reference_path(path: Path, media_type: str) -> dict[str, Any]:
    """The §1.1 reference for the file at `path`, streamed."""
    sha256, size = digest_path(path)
    return {"sha256": sha256, "path": f"{DIR}/{sha256}", "bytes": size, "media_type": media_type}


def reference(data: bytes, media_type: str) -> dict[str, Any]:
    """The §1.1 reference for these bytes: `{sha256, path, bytes, media_type}`."""
    sha256 = digest(data)
    return {"sha256": sha256, "path": f"{DIR}/{sha256}", "bytes": len(data), "media_type": media_type}


def write(root: Path, data: bytes, recipients: Sequence[str] = ()) -> Path:
    """Store `data` under its digest and return the file. Write-once: an existing file with the
    same bytes is kept; one with other bytes raises ValueError. With `recipients`, the file is
    age-sealed to them under the plaintext's digest (RFC 0029 §7)."""
    return _place(root, digest(data), lambda fh: fh.write(data), recipients)


def write_path(root: Path, path: Path, recipients: Sequence[str] = ()) -> Path:
    """Store the file at `path` under its digest, a chunk at a time, and return the file in the
    store; write-once as `write`; sealed as `write` with `recipients`."""
    sha256, _size = digest_path(path)

    def copy(fh: BinaryIO) -> None:
        with Path(path).open("rb") as src:
            while chunk := src.read(CHUNK):
                fh.write(chunk)

    return _place(root, sha256, copy, recipients)


def write_chunks(
    root: Path, chunks: Iterator[bytes], sha256: str, recipients: Sequence[str] = ()
) -> tuple[Path, int]:
    """Store a stream of bytes under `sha256`, the digest a line already names, and return the file
    and its length. The stream is hashed as it is written to a temporary file; when the digest is
    not `sha256` the temporary file is removed and DigestMismatch raised, so nothing lands under
    the name. A file already present is kept after its bytes are checked, and the stream is not
    read; one present with other bytes is an error, never overwritten: write-once, as `write`; a
    present file that is sealed is kept as it is (its bytes are checked by whoever can open it).
    With `recipients` the file is sealed under the plaintext's digest, as `write` is."""
    if not is_digest(sha256):
        raise ValueError(f"{sha256!r} is not a sha256: 64 lowercase hex digits")
    store = Path(root) / DIR
    target = store / sha256
    if target.exists():
        if sealing.is_sealed_file(target):
            return target, target.stat().st_size
        found, size = digest_path(target)
        if found != sha256:
            raise ValueError(f"{DIR}/{sha256} holds bytes that do not match its name; not overwritten")
        if recipients:
            _seal_in_place(target, recipients)
        return target, size
    h = hashlib.sha256()
    size = 0

    def fill(fh: BinaryIO) -> None:
        nonlocal size
        for piece in chunks:
            h.update(piece)
            size += len(piece)
            fh.write(piece)
        actual = h.hexdigest()
        if actual != sha256:
            raise DigestMismatch(sha256, actual, size)

    return _place(root, sha256, fill, recipients), size


def _place(root: Path, sha256: str, fill: Callable[[BinaryIO], object], recipients: Sequence[str]) -> Path:
    store = Path(root) / DIR
    target = store / sha256
    if target.exists():
        if sealing.is_sealed_file(target):
            return target  # sealed under this name already; its bytes are checked by whoever can open it
        if digest_path(target)[0] != sha256:
            raise ValueError(f"{DIR}/{sha256} holds bytes that do not match its name; not overwritten")
        if recipients:  # a plain file a sealing record attaches again: its protection is raised
            _seal_in_place(target, recipients)
        return target
    store.mkdir(parents=True, exist_ok=True)
    tmp = store / f".{sha256}.{os.getpid()}.tmp"
    try:
        with tmp.open("wb") as fh:
            fill(fh)
            fh.flush()
            os.fsync(fh.fileno())
        if recipients:
            _seal_in_place(tmp, recipients)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()
    return target


def _seal_in_place(path: Path, recipients: Sequence[str]) -> None:
    """Replace the plain file at `path` with its age-sealed form, streamed through a sibling
    temporary name, so a crash leaves the plain file or the sealed one, never half of either."""
    sealed = path.with_name(f"{path.name}.{os.getpid()}.sealing")
    try:
        sealing.seal_file(path, sealed, recipients)
        with sealed.open("r+b") as fh:  # a writable handle: Windows refuses fsync on a read-only one
            os.fsync(fh.fileno())
        os.replace(sealed, path)
    finally:
        if sealed.exists():
            sealed.unlink()


def read_bytes(root: Path, sha256: str, identities: Sequence[Any] = ()) -> bytes:
    """The plaintext of the store file named `sha256`: the file's bytes when it is plain, opened
    with `identities` when it is sealed (SealError without one, or when the plaintext does not
    hash to the name). FileNotFoundError when the store has no such file."""
    path = Path(root) / DIR / sha256
    data = path.read_bytes()
    if not data.startswith(AGE_MAGIC):
        return data
    if not identities:
        raise sealing.SealError(f"{DIR}/{sha256} is sealed and there is no identity to open it with")
    plain = sealing.open_sealed_bytes(data, identities)
    if digest(plain) != sha256:
        raise sealing.SealError(f"{DIR}/{sha256} opens to bytes that do not hash to its name")
    return plain


@contextlib.contextmanager
def opened(root: Path, sha256: str, identities: Sequence[Any] = ()) -> Iterator[Path]:
    """A path a reader can hand to a decoder: the store file itself when plain; for a sealed file,
    a temporary copy of the plaintext, streamed, removed on exit (closed first, for Windows)."""
    path = Path(root) / DIR / sha256
    if not sealing.is_sealed_file(path):
        yield path
        return
    if not identities:
        raise sealing.SealError(f"{DIR}/{sha256} is sealed and there is no identity to open it with")
    fd, name = tempfile.mkstemp(prefix="logbook-", suffix=".opened")
    os.close(fd)
    tmp = Path(name)
    try:
        sealing.open_file(path, tmp, identities)
        yield tmp
    finally:
        tmp.unlink(missing_ok=True)


def digests_in(obj: object) -> Iterator[str]:
    """Every `sha256` a payload names anywhere, a §1.1 reference or an adapter's pre-attach hash
    (`extra.media`): the files of the store a line points at."""
    if isinstance(obj, dict):
        sha256 = obj.get("sha256")
        if isinstance(sha256, str) and len(sha256) == 64 and all(c in "0123456789abcdef" for c in sha256):
            yield sha256
        for child in obj.values():
            yield from digests_in(child)
    elif isinstance(obj, list):
        for child in obj:
            yield from digests_in(child)


def check(path: Path, identities: Sequence[Any] = ()) -> bool | None:
    """Whether the store file at `path` holds the bytes its name says: True or False for a plain
    file, or a sealed one opened with `identities`; None for a sealed file nobody here can open."""
    path = Path(path)
    if not sealing.is_sealed_file(path):
        return digest_path(path)[0] == path.name
    if not identities:
        return None
    with opened(path.parent.parent, path.name, identities) as plain:
        return digest_path(plain)[0] == path.name
