"""The SPEC §1.1 attachment store: `<root>/attachments/<sha256>`, content-addressed, write-once.

`reference(data, media_type)` is the object a payload carries for `data`; it is pure, so an adapter
can name bytes it has not written (a dry run). `write(root, data)` puts the bytes in the store,
once: a digest already present is left alone after its bytes are checked, and a file whose bytes do
not match its name is an error (SPEC §1.1), never overwritten. Written to a temporary name and
renamed into place, so a crash leaves no half file under a digest. `reference_path` and `write_path`
do the same for a file on disk, a chunk at a time, so a recording of a hundred megabytes is never
held whole.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, BinaryIO

DIR = "attachments"
CHUNK = 1 << 20


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


def write(root: Path, data: bytes) -> Path:
    """Store `data` under its digest and return the file. Write-once: an existing file with the
    same bytes is kept; one with other bytes raises ValueError."""
    return _place(root, digest(data), lambda fh: fh.write(data))


def write_path(root: Path, path: Path) -> Path:
    """Store the file at `path` under its digest, a chunk at a time, and return the file in the
    store; write-once as `write`."""
    sha256, _size = digest_path(path)

    def copy(fh: BinaryIO) -> None:
        with Path(path).open("rb") as src:
            while chunk := src.read(CHUNK):
                fh.write(chunk)

    return _place(root, sha256, copy)


def _place(root: Path, sha256: str, fill: Callable[[BinaryIO], object]) -> Path:
    store = Path(root) / DIR
    target = store / sha256
    if target.exists():
        if digest_path(target)[0] != sha256:
            raise ValueError(f"{DIR}/{sha256} holds bytes that do not match its name; not overwritten")
        return target
    store.mkdir(parents=True, exist_ok=True)
    tmp = store / f".{sha256}.{os.getpid()}.tmp"
    try:
        with tmp.open("wb") as fh:
            fill(fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()
    return target
