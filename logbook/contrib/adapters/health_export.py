"""What the Withings and MyFitnessPal export readers share: CSV rows by header name, the clocks, the
numbers, and the correction pass that lets a later export supersede a sample already in the record.

Not an adapter (no NAME): `withings` and `myfitnesspal` call in here from their `run`.

**Corrections (RFC 0014).** An export is a snapshot: a weight re-measured, a meal re-logged, a night
the app re-scored comes out of the next export under the same date, so the same `raw_id`. Appending it
would be deduped (same key) and the record would keep the old number. `corrected` takes the drafts of
one run and the record's `existing` (the standing lines by `(source, raw_id)`, one batched lookup
through the index per round) and, for a draft whose key the record has with another sample —
`value`, `end`, `stage`, `device`, `unit` or `extra` differ — rewrites it as a correction: `raw_id`
suffixed `:v2` (`:v3` … when corrected before; the suffix the correction pass of `logbook repair`
also uses, so the dedupe key never takes it for the old line) and `supersedes` the id of the line it
replaces, the latest version standing. A draft equal to what stands is yielded as it is (and deduped by
`append_many`); one the record has not seen is new. Nothing is ever rewritten: the old line stays, and
a reader that follows `supersedes` (`logbook/health.py`) sees the correction only. Without `existing`
(an adapter run by hand) every draft passes through. `counts["corrected"]` tallies the corrections."""

from __future__ import annotations

import csv
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

Existing = Callable[[Iterable[tuple[str, str]]], dict[tuple[str, str], dict[str, Any]]]

SAME = ("value", "unit", "stage", "device", "extra")  # the payload fields that make a sample the same


def rows(path: Path) -> tuple[list[str], list[dict[str, str]]] | None:
    """The header (lower-cased, stripped) and every row as `{column: text}`; None when the file is
    not readable as CSV at all."""
    try:
        with Path(path).open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh)
            header = [cell.strip().lower() for cell in next(reader, [])]
            out = []
            for cells in reader:
                if not any(cell.strip() for cell in cells):
                    continue
                out.append(
                    {name: cells[i].strip() if i < len(cells) else "" for i, name in enumerate(header)}
                )
    except (OSError, UnicodeDecodeError, csv.Error):
        return None
    return header, out


def column(header: Iterable[str], *names: str) -> str | None:
    """The header cell that is one of `names` (lower-case), else None."""
    wanted = set(names)
    return next((cell for cell in header if cell in wanted), None)


def number(text: object) -> int | float | None:
    """The number a cell holds — an int when it is whole — else None (empty, text, inf, nan)."""
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        value = float(text.strip())
    except ValueError:
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return int(value) if value == int(value) else value


def rounded(value: float) -> int | float:
    """Whole numbers as ints, else three decimals, as the health adapters write them."""
    out = round(float(value), 3)
    return int(out) if out == int(out) else out


def zone(name: str | None) -> tzinfo:
    """The record's zone, or UTC when it names none or one this machine does not know."""
    if not name:
        return UTC
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return UTC


def when(text: str, local: tzinfo) -> datetime | None:
    """A cell's instant in UTC: an ISO stamp with an offset as it says, a naive one (`2026-06-08
    07:12:33`, the export's local clock) in `local`. None when it is no stamp."""
    text = text.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=local)
    return parsed.astimezone(UTC)


def stamp(instant: datetime) -> str:
    return instant.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


def slug(text: str) -> str:
    """`Fat (g)` → `fat_g`, `Saturated Fat` → `saturated_fat`: a header as an `extra` key."""
    out = "".join(ch if ch.isalnum() else "_" for ch in text.strip().lower())
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")


def count(counts: dict[str, int], key: str, n: int = 1) -> None:
    counts[key] = counts.get(key, 0) + n


def corrected(
    drafts: Iterable[dict[str, Any]], existing: Existing | None, counts: dict[str, int]
) -> Iterator[dict[str, Any]]:
    """The drafts in their order, a draft that corrects a sample the record holds rewritten as a
    correction (module docstring). Rounds of one batched lookup each: round n asks for `raw_id` with
    the `:v<n>` suffix of every draft still unresolved, so an export of ten thousand lines costs a
    handful of SELECTs, never one per line."""
    drafts = list(drafts)
    if existing is None:
        yield from drafts
        return
    pending = list(range(len(drafts)))
    version = dict.fromkeys(pending, 1)
    latest: dict[int, dict[str, Any]] = {}
    while pending:
        keys = {_key(drafts[i], version[i]): i for i in pending}
        found = existing(list(keys))
        still: list[int] = []
        for key, i in keys.items():
            line = found.get(key)
            if line is None:
                continue
            latest[i] = line
            version[i] += 1
            still.append(i)
        pending = still
    for i, draft in enumerate(drafts):
        last = latest.get(i)
        if last is None or _same(last, draft):
            yield draft
            continue
        payload = dict(draft["payload"])
        payload["raw_id"] = _key(draft, version[i])[1]
        payload["supersedes"] = str(last["id"])
        count(counts, "corrected")
        yield {**draft, "payload": payload}


def _key(draft: dict[str, Any], version: int) -> tuple[str, str]:
    raw_id = str(draft["payload"]["raw_id"])
    return str(draft["source"]), raw_id if version == 1 else f"{raw_id}:v{version}"


def _same(line: dict[str, Any], draft: dict[str, Any]) -> bool:
    """The same sample: the same span and the same payload but for the key and the pointer."""
    if line.get("at") != draft.get("at") or line.get("end") != draft.get("end"):
        return False
    stored, fresh = line.get("payload") or {}, draft["payload"]
    return all(stored.get(field) == fresh.get(field) for field in SAME)
