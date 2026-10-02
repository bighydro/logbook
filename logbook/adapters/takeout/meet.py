"""Google Takeout Google Meet/ → call/v1 (RFC 0012).

Takeout writes `Takeout/Google Meet/Call history/Call history.csv`, one row per call the account was
in: `Conference ID`, `Meeting Code`, `Start Time`, `Duration (seconds)`, `Participant Count`,
`Organizer Email`, `Product Type`, `Device Type`, `Call Type`. Google renames and reorders these
between exports, so the columns are found by what their header says (a header with `conference`, one
with `start`, one with `duration`, …), not by position; a column that is not there leaves its field
out. The input is the CSV, its folder, or the `Google Meet/` folder above.

One line per row: kind `call`, tier 1 (RFC 0012: the owner's own time, no words), source
`google-takeout`, `at` the start in UTC, `end` the start plus the duration when it lasted, else null;
`tz` the record's zone. `direction` is `outgoing` when the organizer is the owner — `owner_emails`
from `logbook.json`, passed by `logbook add` — and `incoming` otherwise; with no owner named every
call is `incoming` and that is counted (`no_owner`). `answered` is true: a call in the history was
joined, even one nobody else came to (`duration_s` 0, RFC 0012 rule 3). `counterparty` is the
organizer as an email ref when it is not the owner; never resolved here (RFC 0006). `service` is
`meet`. The meeting code, the participant count, the product, the device and the call type go under
`extra`, with `role` (`organizer` or `participant`). `raw_id` is `meet:<conference id>`; a row
without one is keyed `meet:<start>:<sha256(start|organizer)[:16]>` and counted. A row with no start
is skipped and counted. Pure: no network, never writes the source.
"""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import SOURCE, times

NAME = "google-takeout-meet"
KIND = "call"
TIER = 1
SCHEMA = "call/v1"
SERVICE = "meet"
FOLDER = "Google Meet"

SUFFIX = ".csv"
SNIFF_BYTES = 4096
COLUMNS = {  # field → the words a header must carry (lower-cased, in order)
    "conference": ("conference",),
    "code": ("meeting", "code"),
    "start": ("start",),
    "duration": ("duration",),
    "participants": ("participant",),
    "organizer": ("organizer",),
    "product": ("product",),
    "device": ("device",),
    "call_type": ("call", "type"),
}
REQUIRED = ("start", "duration")
MARKS = (b"conference", b"meeting code", b"organizer")


def sniff(path: Path) -> bool:
    """Meet's call history CSV, or a folder holding one directly or one folder down. Never raises."""
    path = Path(path)
    try:
        return bool(_files(path)) if path.is_dir() else _is_history(path)
    except OSError:
        return False


def _is_history(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != SUFFIX:
        return False
    with path.open("rb") as fh:
        head = fh.read(SNIFF_BYTES).lower()
    header = head.split(b"\n", 1)[0]
    return b"start" in header and b"duration" in header and any(mark in header for mark in MARKS)


def _files(folder: Path) -> list[Path]:
    found = [f for f in sorted(folder.iterdir()) if _is_history(f)]
    for sub in sorted(d for d in folder.iterdir() if d.is_dir()):
        found.extend(f for f in sorted(sub.iterdir()) if _is_history(f))
    return found


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
    owner_emails: list[str] | None = None,
) -> Iterator[dict[str, Any]]:
    """One call/v1 line draft per row of the call history at `path` (or under it), oldest first.
    `since` is RFC3339 UTC; `timezone` is the record's zone; `owner_emails` says who is me."""
    counts = counts if counts is not None else {}
    path = Path(path)
    files = [path] if path.is_file() else _files(path)
    owner = {e.strip().lower() for e in owner_emails or [] if e.strip()}
    if not owner:
        _count(counts, "no_owner")
    tz = timezone or "UTC"
    drafts: list[dict[str, Any]] = []
    for file in files:
        drafts.extend(_rows(file, owner, tz, counts))
    for draft in sorted(drafts, key=lambda d: (d["at"], d["payload"]["raw_id"])):
        if since is None or draft["at"] >= since:
            yield draft


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def columns(header: list[str], wanted: dict[str, tuple[str, ...]]) -> dict[str, int]:
    """field → column index, by the words the header carries; shared with the other CSV readers."""
    found: dict[str, int] = {}
    for field, words in wanted.items():
        for i, name in enumerate(header):
            lowered = name.strip().lower()
            if all(word in lowered for word in words) and i not in found.values():
                found[field] = i
                break
    return found


def _rows(file: Path, owner: set[str], tz: str, counts: dict[str, int]) -> Iterator[dict[str, Any]]:
    with file.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header is None:
            return
        at_col = columns(header, COLUMNS)
        if any(field not in at_col for field in REQUIRED):
            return

        def cell(row: list[str], field: str) -> str:
            i = at_col.get(field)
            return row[i].strip() if i is not None and i < len(row) else ""

        for row in reader:
            if not any(c.strip() for c in row):
                continue
            at, _spelled = times.parse(cell(row, "start"))
            if at is None:
                _count(counts, "skipped_no_timestamp")
                continue
            organizer = cell(row, "organizer").lower()
            conference = cell(row, "conference")
            if conference:
                raw_id = f"{SERVICE}:{conference}"
            else:
                digest = hashlib.sha256(f"{at}|{organizer}".encode()).hexdigest()[:16]
                raw_id = f"{SERVICE}:{at}:{digest}"
                _count(counts, "no_conference_id")
            duration = _seconds(cell(row, "duration"))
            mine = bool(organizer) and organizer in owner
            payload: dict[str, Any] = {
                "schema": SCHEMA,
                "raw_id": raw_id,
                "direction": "outgoing" if mine else "incoming",
                "answered": True,
                "duration_s": duration,
            }
            if organizer and not mine:
                payload["counterparty"] = {"kind": "email", "value": organizer}
            payload["service"] = SERVICE
            extra: dict[str, Any] = {"role": "organizer" if mine else "participant"}
            if code := cell(row, "code"):
                extra["meeting_code"] = code
            participants = cell(row, "participants")
            if participants.isdigit():
                extra["participants"] = int(participants)
            for field, key in (("product", "product"), ("device", "device_type"), ("call_type", "call_type")):
                if value := cell(row, field):
                    extra[key] = value
            payload["extra"] = extra
            end = None
            if duration > 0:
                started = datetime.fromisoformat(at.replace("Z", "+00:00"))
                end = (started + timedelta(seconds=duration)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            yield {
                "at": at,
                "end": end,
                "tz": tz,
                "source": SOURCE,
                "kind": KIND,
                "tier": TIER,
                "payload": payload,
            }


def _seconds(text: str) -> int:
    try:
        return max(0, round(float(text)))
    except ValueError:
        return 0
