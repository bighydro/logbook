"""A reading kept between heads: what a whole-record reader keeps beside the index, so the next reading
reads only what was appended since (`people.read_whole`, `promises.extract` over the whole record;
ADR 0025, phase 5 of the Library's rebuild).

A kept reading is a cache, never a line: a JSON file in the cache folder beside the index
(`<cache dir>/logbook/<owner_id>/`, RFC 0029 §8), never in the record's folder, written 0600 and moved
into place whole. Deleting it loses nothing: the next reading reads the whole record again. Each is
stamped (`stamp`) with what it was read under besides the lines: the code that read it (a digest of
the modules' source, so a changed rule never reads a kept answer of the old one), `logbook.json`
without its head and seq, whether the sealed lines open, and every settings file beside the chain
(`places.json`, `assets.json`, `policy/`). A stamp that differs, and a file that does not read, is a
reading made again from the lines.

What it holds names the record's people and counts their lines: on a sealed record that is plain
text on this disk, as the Library's built pages are (docs/serve.md, *Built ahead*), readable by the
record's user alone."""

from __future__ import annotations

import functools
import hashlib
import json
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .store import Logbook

CORE = Path(__file__).resolve().parent


@functools.cache
def code_digest(*files: str) -> str:
    """A digest of the source of `files` (paths), and of every module of `logbook/core`, which every
    reader builds on: read once a process."""
    whole = hashlib.sha256()
    for path in sorted({*(str(p) for p in CORE.glob("*.py")), *files}):
        try:
            whole.update(Path(path).read_bytes())
        except OSError:
            whole.update(b"-")
    return whole.hexdigest()


def stamp(lb: Logbook, *extra: str) -> str:
    """What a kept reading was read under besides the lines (see the module), and `extra`."""
    meta = {k: v for k, v in lb.meta.items() if k not in ("head", "seq")}
    parts = [json.dumps(meta, sort_keys=True), str(bool(lb.identities)), *extra]
    files: Iterable[Path] = [
        lb.root / "places.json",
        lb.root / "assets.json",
        *sorted((lb.root / "policy").glob("*")),
    ]
    for f in files:
        try:
            parts.append(f"{f.name} {hashlib.sha256(f.read_bytes()).hexdigest()}")
        except OSError:
            parts.append(f"{f.name} -")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def path(lb: Logbook, name: str) -> Path | None:
    """Where the kept reading `name` lives: beside the index; None for a record whose index is not the
    plain one (the MCP server's `GatedLogbook`, which serves only what its gate lets through): it keeps
    nothing and reads every line each time, so a reading never crosses from one to the other."""
    if type(lb).index is not Logbook.index:
        return None
    return lb.index_path.parent / name


def load(at: Path | None) -> dict[str, Any] | None:
    """The kept reading at `at`, or None when there is none or it does not read."""
    if at is None:
        return None
    try:
        data = json.loads(at.read_bytes())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def save(at: Path | None, data: Mapping[str, Any]) -> None:
    """`data` at `at`, 0600 from its first byte, moved into place whole; nothing when the cache folder
    cannot be written (the next reading reads the whole record), or for no path (`path`)."""
    if at is None:
        return
    tmp = at.with_name(f".{at.name}.{os.getpid()}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(json.dumps(data, separators=(",", ":")).encode("utf-8"))
        os.replace(tmp, at)
    except OSError:
        tmp.unlink(missing_ok=True)
