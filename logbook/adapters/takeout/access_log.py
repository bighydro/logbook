"""Google Takeout Access Log Activity/ → event/v1 at tier 3 (RFC 0009).

Takeout writes `Takeout/Access Log Activity/Activities - A list of Google services accessed by.csv`,
one row per access to a Google service from the account: `Activity Timestamp`, `Product Name`,
`Activity Type`, `IP Address`, `User Agent String`, and, when Google had them, the device (`Device
Type`, `Device Model`) and the location it placed the address at (`Country Code`, `City`, or a
`Region`). The columns are found by what their header says, not by position, since the set differs
between exports; a column that is not there leaves its field out. The input is the CSV or its folder.

This is the noisiest thing in a Takeout — every open of Gmail is a row — and it says where the owner's
devices were, so the source is **off by default** in `policy/import.json` (the owner removes the entry
to opt in) and every line is **tier 3**: a sign-in from a city on a date is a location fact as
sensitive as a transaction. One line per row: kind `event`, source `google-takeout`, `at` the
timestamp in UTC, `end` null, `all_day` false, `tz` the record's zone. `title` is `<product>:
<activity>` (`Gmail: Sign in`), `calendar` `{id: google-access-log, name: Google Account access}`,
`location` the city and country as text when the row has either. The product, the activity, the IP
address, the user agent, the device (`{type, model}`) and the country and city go under `extra`.
`raw_id` is `access-log:<timestamp as spelled>:<sha256(product|activity|ip|agent)[:16]>`: the export
has no row id, and two accesses in one second from two addresses are two rows. A row with no
timestamp is skipped and counted. Pure: no network, never writes the source.
"""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from . import SOURCE, times
from .meet import columns

NAME = "google-takeout-access-log"
KIND = "event"
TIER = 3
SCHEMA = "event/v1"
FOLDER = "Access Log Activity"
CALENDAR = {"id": "google-access-log", "name": "Google Account access"}

SUFFIX = ".csv"
SNIFF_BYTES = 4096
COLUMNS = {
    "time": ("activity", "timestamp"),
    "product": ("product",),
    "activity": ("activity", "type"),
    "ip": ("ip",),
    "agent": ("user", "agent"),
    "device_type": ("device", "type"),
    "device_model": ("device", "model"),
    "country": ("country",),
    "city": ("city",),
    "region": ("region",),
}
REQUIRED = ("time", "product")


def sniff(path: Path) -> bool:
    """The access log CSV, or a folder holding one. Never raises."""
    path = Path(path)
    try:
        if path.is_dir():
            return any(_is_log(f) for f in sorted(path.iterdir()))
        return _is_log(path)
    except OSError:
        return False


def _is_log(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != SUFFIX:
        return False
    with path.open("rb") as fh:
        header = fh.read(SNIFF_BYTES).split(b"\n", 1)[0].lower()
    return b"activity timestamp" in header and b"product" in header and b"activity type" in header


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
) -> Iterator[dict[str, Any]]:
    """One event/v1 line draft per row of the access log at `path` (or in the folder), oldest
    first. `since` is RFC3339 UTC; `timezone` is the record's zone."""
    counts = counts if counts is not None else {}
    path = Path(path)
    files = [path] if path.is_file() else sorted(f for f in path.iterdir() if _is_log(f))
    tz = timezone or "UTC"
    drafts: list[dict[str, Any]] = []
    for file in files:
        drafts.extend(_rows(file, tz, counts))
    for draft in sorted(drafts, key=lambda d: (d["at"], d["payload"]["raw_id"])):
        if since is None or draft["at"] >= since:
            yield draft


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _rows(file: Path, tz: str, counts: dict[str, int]) -> Iterator[dict[str, Any]]:
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
            return " ".join(row[i].split()) if i is not None and i < len(row) else ""

        for row in reader:
            if not any(c.strip() for c in row):
                continue
            at, spelled = times.parse(cell(row, "time"))
            if at is None:
                _count(counts, "skipped_no_timestamp")
                continue
            product, activity = cell(row, "product"), cell(row, "activity")
            ip, agent = cell(row, "ip"), cell(row, "agent")
            digest = hashlib.sha256(f"{product}|{activity}|{ip}|{agent}".encode()).hexdigest()[:16]
            payload: dict[str, Any] = {"schema": SCHEMA, "raw_id": f"access-log:{spelled}:{digest}"}
            title = ": ".join(part for part in (product, activity) if part)
            if title:
                payload["title"] = title
            payload["calendar"] = dict(CALENDAR)
            payload["all_day"] = False
            city, region, country = cell(row, "city"), cell(row, "region"), cell(row, "country")
            where = ", ".join(part for part in (city or region, country) if part)
            if where:
                payload["location"] = where
            extra: dict[str, Any] = {}
            for key, value in (
                ("product", product),
                ("activity", activity),
                ("ip", ip),
                ("user_agent", agent),
            ):
                if value:
                    extra[key] = value
            device = {
                k: v
                for k, v in (("type", cell(row, "device_type")), ("model", cell(row, "device_model")))
                if v
            }
            if device:
                extra["device"] = device
            for key, value in (("country", country), ("city", city), ("region", region)):
                if value:
                    extra[key] = value
            payload["extra"] = extra
            yield {
                "at": at,
                "end": None,
                "tz": tz,
                "source": SOURCE,
                "kind": KIND,
                "tier": TIER,
                "payload": payload,
            }
