"""The SPEC §1.1 attachment store: `<root>/attachments/<sha256>`, content-addressed, write-once.

`reference(data, media_type)` is the object a payload carries for `data`; it is pure, so an adapter
can name bytes it has not written (a dry run). `write(root, data)` puts the bytes in the store,
once: a digest already present is left alone after its bytes are checked, and a file whose bytes do
not match its name is an error (SPEC §1.1), never overwritten. Written to a temporary name and
renamed into place, so a crash leaves no half file under a digest.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

DIR = "attachments"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def reference(data: bytes, media_type: str) -> dict[str, Any]:
    """The §1.1 reference for these bytes: `{sha256, path, bytes, media_type}`."""
    sha256 = digest(data)
    return {"sha256": sha256, "path": f"{DIR}/{sha256}", "bytes": len(data), "media_type": media_type}


def write(root: Path, data: bytes) -> Path:
    """Store `data` under its digest and return the file. Write-once: an existing file with the
    same bytes is kept; one with other bytes raises ValueError."""
    sha256 = digest(data)
    store = Path(root) / DIR
    target = store / sha256
    if target.exists():
        if digest(target.read_bytes()) != sha256:
            raise ValueError(f"{DIR}/{sha256} holds bytes that do not match its name; not overwritten")
        return target
    store.mkdir(parents=True, exist_ok=True)
    tmp = store / f".{sha256}.{os.getpid()}.tmp"
    try:
        with tmp.open("wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()
    return target
