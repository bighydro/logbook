"""The folder. The only code that writes to logbook/*.jsonl."""

from __future__ import annotations

import json
import os
import secrets
import time
import uuid
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from . import FORMAT
from .chain import GENESIS, Line, compute_hash, verify_lines


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def uuid7() -> str:
    """RFC 9562 UUIDv7: 48-bit ms timestamp, then random. Time-ordered, so ids sort like the log."""
    ms = time.time_ns() // 1_000_000
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    value = (ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return str(uuid.UUID(int=value))


CHECKOUT_MARKERS = ("pyproject.toml", ".git", "logbook/__init__.py")

META_EVERY = 10_000  # append_many: lines between checkpoints (files flushed, then logbook.json)
PROGRESS_EVERY = 50_000  # append_many: lines between progress reports

RETRACTION = "retraction"  # kind of the line that supersedes another (SPEC §3)


class CodeCheckoutError(Exception):
    """The folder looks like a clone of this repository, not a personal record."""


def code_checkout_marker(root: Path) -> str | None:
    """The first thing in `root` that says "source code, not a diary", or None.

    On a case-insensitive disk ~/Logbook and a clone at ~/logbook are the same folder,
    so a logbook must never be created in, or found in, a folder that has one of these."""
    return next((m for m in CHECKOUT_MARKERS if (Path(root) / m).exists()), None)


class Logbook:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.meta_path = self.root / "logbook.json"
        self.log_dir = self.root / "logbook"

    # -- lifecycle -----------------------------------------------------------
    @classmethod
    def init(cls, root: Path, timezone_name: str) -> Logbook:
        root = Path(root)
        marker = code_checkout_marker(root)
        if marker is not None:
            raise CodeCheckoutError(
                f"{root} looks like a code checkout (it has {marker}); "
                "choose another folder or set LOGBOOK_HOME"
            )
        if (root / "logbook.json").exists():
            raise FileExistsError(f"{root} is already a logbook")
        for d in ("logbook", "notes", "inbox", "inbox/done"):
            (root / d).mkdir(parents=True, exist_ok=True)
        meta = {
            "format": FORMAT,
            "owner_id": uuid7(),
            "created_at": now_utc(),
            "timezone": timezone_name,
            "seq": 0,
            "head": GENESIS,
        }
        (root / "logbook.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        return cls(root)

    @classmethod
    def find(cls, start: Path | None = None) -> Logbook:
        env = os.environ.get("LOGBOOK_HOME")
        candidates = [Path(env)] if env else []
        p = Path(start or Path.cwd()).resolve()
        candidates += [p, *p.parents, Path.home() / "Logbook"]
        for c in candidates:
            if (c / "logbook.json").exists() and code_checkout_marker(c) is None:
                return cls(c)
        raise FileNotFoundError("no logbook found; run `logbook init`")

    @property
    def meta(self) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self.meta_path.read_text(encoding="utf-8"))
        return data

    def _save_meta(self, meta: dict[str, Any]) -> None:
        self.meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    # -- reading -------------------------------------------------------------
    def files(self) -> list[Path]:
        return sorted(self.log_dir.glob("*/*.jsonl"))

    def lines(self) -> Iterator[Line]:
        """All lines in chain order (by seq). Files partition by month of `at`; backfilled
        history lands in old files, so file order is not chain order."""
        rows = list(self.lines_unsorted())
        rows.sort(key=lambda r: r.get("seq", 0))
        return iter(rows)

    def lines_unsorted(self) -> Iterator[Line]:
        """Every line, streamed file by file, in file order — not chain order. For a pass that
        groups or indexes and must not hold the whole log in memory; `lines()` does."""
        for f in self.files():
            with f.open(encoding="utf-8") as fh:
                for raw in fh:
                    if raw.strip():
                        yield json.loads(raw)

    def line_by_seq(self, seq: int) -> Line | None:
        return next((line for line in self.lines_unsorted() if line.get("seq") == seq), None)

    def verify(self) -> tuple[int, str, list[str]]:
        seq, head, errors = verify_lines(self.lines())
        meta = self.meta
        if meta["seq"] != seq or meta["head"] != head:
            errors.append(
                f"logbook.json says seq={meta['seq']} head={meta['head'][:12]}…, "
                f"files say seq={seq} head={head[:12]}…"
            )
        return seq, head, errors

    # -- writing -------------------------------------------------------------
    def append(
        self,
        at: str,
        source: str,
        kind: str,
        tier: int,
        payload: dict[str, Any],
        end: str | None = None,
        tz: str | None = None,
        recorded_at: str | None = None,
    ) -> Line:
        meta = self.meta
        line = self._line(
            meta, meta["seq"] + 1, meta["head"], at, source, kind, tier, payload, end, tz, recorded_at
        )
        path = self._path_for(at)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(_dumps(line))
        meta["seq"], meta["head"] = line["seq"], line["hash"]
        self._save_meta(meta)
        return line

    def retract(self, seq: int, reason: str, at: str | None = None) -> Line:
        """Retract line `seq`: a new manual line, kind `retraction`, whose payload supersedes it
        (SPEC §3). The retracted line stays; readers hide it. Raises ValueError when there is no
        such line or it is itself a retraction."""
        target = self.line_by_seq(seq)
        if target is None:
            raise ValueError(f"no line with seq {seq}")
        if target.get("kind") == RETRACTION:
            raise ValueError(f"#{seq} is itself a retraction")
        return self.append(
            at=at or now_utc(),
            source="manual",
            kind=RETRACTION,
            tier=2,
            payload={"schema": "retraction/v1", "supersedes": target["id"], "seq": seq, "reason": reason},
        )

    def append_many(
        self,
        drafts: Iterable[dict[str, Any]],
        progress: Callable[[int, float], None] | None = None,
    ) -> int:
        """Append drafts in order; returns how many were written.

        A draft whose (source, payload.raw_id) is already in the log is skipped, so re-adding the
        same export appends nothing. Drafts without a raw_id are never deduped.

        Built for millions of drafts: the dedupe set is read once, the chain is computed in
        memory, month files stay open, and every META_EVERY lines the pending lines are written
        and flushed and then logbook.json is saved (a checkpoint). Lines never reach disk ahead of
        a checkpoint, so an interruption leaves the log exactly as it was at the last checkpoint —
        a valid chain — and re-adding the same export finishes the job. On a Python-level
        interruption (Ctrl-C, an exception in an adapter) the final checkpoint still runs, so
        nothing already drafted is lost. `progress(count, elapsed_seconds)` is called every
        PROGRESS_EVERY lines.

        Chain order is import order: `seq` and `prev` follow the order the drafts arrive in,
        and `at` is the event time. A batch is never sorted."""
        seen = set(self._dedupe_keys())
        meta = self.meta
        seq, head = meta["seq"], meta["head"]
        handles: dict[Path, TextIO] = {}
        pending: dict[Path, list[str]] = {}
        n, since_checkpoint, started = 0, 0, time.monotonic()

        def checkpoint() -> None:
            for path, rows in pending.items():
                fh = handles.get(path)
                if fh is None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    fh = handles[path] = path.open("a", encoding="utf-8")
                fh.write("".join(rows))
                fh.flush()
            pending.clear()
            if (meta["seq"], meta["head"]) != (seq, head):
                meta["seq"], meta["head"] = seq, head
                self._save_meta(meta)

        try:
            for d in drafts:
                key = _dedupe_key(d)
                if key is not None:
                    if key in seen:
                        continue
                    seen.add(key)
                line = self._line(meta, seq + 1, head, **d)
                pending.setdefault(self._path_for(line["at"]), []).append(_dumps(line))
                seq, head = line["seq"], line["hash"]
                n += 1
                since_checkpoint += 1
                if since_checkpoint >= META_EVERY:
                    checkpoint()
                    since_checkpoint = 0
                if progress is not None and n % PROGRESS_EVERY == 0:
                    progress(n, time.monotonic() - started)
        finally:
            checkpoint()
            for fh in handles.values():
                fh.close()
        return n

    def _line(
        self,
        meta: dict[str, Any],
        seq: int,
        prev: str,
        at: str,
        source: str,
        kind: str,
        tier: int,
        payload: dict[str, Any],
        end: str | None = None,
        tz: str | None = None,
        recorded_at: str | None = None,
    ) -> Line:
        """A complete, hashed line; nothing is written."""
        if "schema" not in payload:
            raise ValueError("payload.schema is required")
        if tier not in (1, 2, 3):
            raise ValueError("tier must be 1, 2 or 3")
        line: Line = {
            "id": uuid7(),
            "seq": seq,
            "at": at,
            "end": end,
            "tz": tz or meta["timezone"],
            "source": source,
            "kind": kind,
            "tier": tier,
            "payload": payload,
            "recorded_at": recorded_at or now_utc(),
            "prev": prev,
        }
        line["hash"] = compute_hash(line)
        return line

    def _path_for(self, at: str) -> Path:
        year, month = at[:4], at[5:7]
        return self.log_dir / year / f"{month}.jsonl"

    def _dedupe_keys(self) -> Iterator[tuple[str, str]]:
        """(source, raw_id) of every line — order does not matter here."""
        for line in self.lines_unsorted():
            key = _dedupe_key(line)
            if key is not None:
                yield key


def retractions(lines: Iterable[Line]) -> dict[str, Line]:
    """The retraction that supersedes each retracted line, keyed by the retracted line's id.
    When a line is retracted more than once the one written last wins."""
    found: dict[str, Line] = {}
    for line in lines:
        if line.get("kind") == RETRACTION:
            superseded = (line.get("payload") or {}).get("supersedes")
            if isinstance(superseded, str):
                found[superseded] = line
    return found


def _dumps(line: Line) -> str:
    return json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n"


def _dedupe_key(line: dict[str, Any]) -> tuple[str, str] | None:
    raw_id = (line.get("payload") or {}).get("raw_id")
    return (str(line.get("source")), str(raw_id)) if raw_id is not None else None
