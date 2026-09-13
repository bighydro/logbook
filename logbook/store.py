"""The folder. The only code that writes to logbook/*.jsonl."""
from __future__ import annotations
import json, os, secrets, time, uuid
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from . import FORMAT
from .chain import GENESIS, compute_hash, verify_lines


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def uuid7() -> str:
    """RFC 9562 UUIDv7: 48-bit ms timestamp, then random. Time-ordered, so ids sort like the log."""
    ms = time.time_ns() // 1_000_000
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    value = (ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return str(uuid.UUID(int=value))


class Logbook:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.meta_path = self.root / "logbook.json"
        self.log_dir = self.root / "logbook"

    # -- lifecycle -----------------------------------------------------------
    @classmethod
    def init(cls, root: Path, timezone_name: str) -> "Logbook":
        root = Path(root)
        if (root / "logbook.json").exists():
            raise FileExistsError(f"{root} is already a logbook")
        for d in ("logbook", "notes", "inbox", "inbox/done"):
            (root / d).mkdir(parents=True, exist_ok=True)
        meta = {"format": FORMAT, "owner_id": uuid7(), "created_at": now_utc(),
                "timezone": timezone_name, "seq": 0, "head": GENESIS}
        (root / "logbook.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        return cls(root)

    @classmethod
    def find(cls, start: Path | None = None) -> "Logbook":
        env = os.environ.get("LOGBOOK_HOME")
        candidates = [Path(env)] if env else []
        p = Path(start or Path.cwd()).resolve()
        candidates += [p, *p.parents, Path.home() / "Logbook"]
        for c in candidates:
            if (c / "logbook.json").exists():
                return cls(c)
        raise FileNotFoundError("no logbook found; run `logbook init`")

    @property
    def meta(self) -> dict:
        return json.loads(self.meta_path.read_text(encoding="utf-8"))

    def _save_meta(self, meta: dict) -> None:
        self.meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    # -- reading -------------------------------------------------------------
    def files(self) -> list[Path]:
        return sorted(self.log_dir.glob("*/*.jsonl"))

    def lines(self) -> Iterator[dict]:
        """All lines in chain order (by seq). Files partition by month of `at`; backfilled
        history lands in old files, so file order is not chain order."""
        rows: list[dict] = []
        for f in self.files():
            with f.open(encoding="utf-8") as fh:
                rows.extend(json.loads(raw) for raw in fh if raw.strip())
        rows.sort(key=lambda r: r.get("seq", 0))
        return iter(rows)

    def verify(self) -> tuple[int, str, list[str]]:
        seq, head, errors = verify_lines(self.lines())
        meta = self.meta
        if meta["seq"] != seq or meta["head"] != head:
            errors.append(f"logbook.json says seq={meta['seq']} head={meta['head'][:12]}…, files say seq={seq} head={head[:12]}…")
        return seq, head, errors

    # -- writing -------------------------------------------------------------
    def append(self, at: str, source: str, kind: str, tier: int, payload: dict,
               end: str | None = None, tz: str | None = None, recorded_at: str | None = None) -> dict:
        if "schema" not in payload:
            raise ValueError("payload.schema is required")
        if tier not in (1, 2, 3):
            raise ValueError("tier must be 1, 2 or 3")
        meta = self.meta
        line: dict[str, object] = {"id": uuid7(), "seq": meta["seq"] + 1, "at": at, "end": end,
                "tz": tz or meta["timezone"], "source": source, "kind": kind, "tier": tier,
                "payload": payload, "recorded_at": recorded_at or now_utc(), "prev": meta["head"]}
        line["hash"] = compute_hash(line)
        year, month = at[:4], at[5:7]
        path = self.log_dir / year / f"{month}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
        meta["seq"], meta["head"] = line["seq"], line["hash"]
        self._save_meta(meta)
        return line

    def append_many(self, drafts: Iterable[dict]) -> int:
        n = 0
        for d in drafts:
            self.append(**d)
            n += 1
        return n
