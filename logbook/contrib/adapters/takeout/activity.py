"""Google Takeout My Activity/ → browse/v1 (RFC 0017) and watch/v1 (RFC 0018).

Takeout writes `Takeout/My Activity/<Product>/MyActivity.json` when the owner asked for JSON (an
`.html` otherwise, not read): one array per product of `{header, title, titleUrl?, time, products,
subtitles?, details?, locationInfos?}`. `title` starts with the activity — `Searched for …`,
`Visited …`, `Used …`, `Watched …` — and `header` is the product (`Search`, `Maps`, `YouTube`) or, under
`Android`, the app's name. The input is the `My Activity/` folder, one product's folder, or one file.

This is every search the owner typed and every app they opened, so the source is **off by default**
in `policy/import.json` (the owner removes the entry to opt in). What fits a profile is a line, at
tier 2 (RFC 0017 and 0018, MUST); the rest is skipped and counted:

- `Searched for <query>` with a results url, and `Visited <page>` with a url, are `browse/v1` visits:
  `url`, `title` the query or the page's title, `action` `visit`, `browser` `google-<product>`
  (`google-search`, `google-maps`, `google-play`), `extra.activity` `searched` or `visited`.
- `Used <app>` under Android, whose url is the app's Play Store page, is a `browse/v1` visit to that
  page: `title` the app, `browser` `android`, `extra.activity` `used`.
- A `YouTube` entry is mapped by the YouTube adapter's own function (ADR 0017: one mapping), so a
  watch here and the same watch in `YouTube and YouTube Music/history/` are one line.
- A `Chrome` entry is skipped and counted: `Chrome/History.json` holds the same visits with Chrome's
  own clock, and `google-takeout-chrome` reads that, so one visit never has two spellings.
- An ad (`details: [{name: "From Google Ads"}]`), an entry with no url or no time, and any other
  activity (`Viewed area …`, `Said …`) are skipped and counted.

`raw_id` is `activity:<product slug>:<time as spelled>:<sha256(url)[:16]>`; the first
`locationInfos` entry's `name` and `source` go under `extra.location_hint` (Google's guess at where
the owner was, kept as text, never as a location line). Streamed through `ijson`, one entry in memory
at a time. Pure: no network, never writes the source.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ...stream import ijson
from . import SOURCE, youtube

NAME = "google-takeout-activity"
BROWSE_KIND = "browse"
BROWSE_SCHEMA = "browse/v1"
TIER = 2
FOLDER = "My Activity"
FILE = "MyActivity.json"

SNIFF_BYTES = 4096
AD = "From Google Ads"
ANDROID = "Android"
CHROME = "Chrome"
YOUTUBE = ("YouTube", "YouTube Music")
ACTIONS = (("Searched for ", "searched"), ("Visited ", "visited"), ("Used ", "used"))
SLUG = re.compile(r"[^a-z0-9]+")


def sniff(path: Path) -> bool:
    """A `MyActivity.json`, a product folder holding one, or the `My Activity/` folder of them.
    Never raises."""
    path = Path(path)
    try:
        return bool(_files(path)) if path.is_dir() else _is_activity(path)
    except OSError:
        return False


def _is_activity(path: Path) -> bool:
    if not path.is_file() or path.name != FILE:
        return False
    with path.open("rb") as fh:
        head = fh.read(SNIFF_BYTES)
    return head.lstrip().startswith(b"[") and b'"header"' in head and b'"products"' in head


def _files(folder: Path) -> list[Path]:
    if _is_activity(folder / FILE):
        return [folder / FILE]
    return [sub / FILE for sub in sorted(folder.iterdir()) if sub.is_dir() and _is_activity(sub / FILE)]


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
) -> Iterator[dict[str, Any]]:
    """One browse/v1 or watch/v1 line draft per entry that fits, oldest first. `since` is RFC3339
    UTC; `timezone` is the record's zone."""
    counts = counts if counts is not None else {}
    path = Path(path)
    files = [path] if path.is_file() else _files(path)
    tz = timezone or "UTC"
    drafts: list[dict[str, Any]] = []
    for file in files:
        product = file.parent.name if file.parent.name != FOLDER else ""
        with file.open("rb") as fh:
            for entry in ijson.items(fh, "item"):
                draft = _draft(entry, product, tz, counts) if isinstance(entry, dict) else None
                if draft is not None and (since is None or draft["at"] >= since):
                    drafts.append(draft)
    yield from sorted(drafts, key=lambda d: (d["at"], d["payload"]["raw_id"]))


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _draft(entry: dict[str, Any], product: str, tz: str, counts: dict[str, int]) -> dict[str, Any] | None:
    header = " ".join(str(entry.get("header") or "").split())
    products = [str(p) for p in entry.get("products") or [] if isinstance(p, str)]
    product = product or (products[0] if products else header)
    if header in YOUTUBE or product in YOUTUBE:
        return youtube._draft(entry, tz, counts)
    if any(isinstance(d, dict) and d.get("name") == AD for d in entry.get("details") or []):
        _count(counts, "skipped_ad")
        return None
    if header == CHROME or product == CHROME:
        _count(counts, "skipped_covered_by_chrome")
        return None
    title = " ".join(str(entry.get("title") or "").split())
    activity = next((a for prefix, a in ACTIONS if title.startswith(prefix)), None)
    if activity is None or (activity == "used" and product != ANDROID):
        _count(counts, "skipped_other_activity")
        return None
    url = str(entry.get("titleUrl") or "")
    if not url:
        _count(counts, "skipped_no_url")
        return None
    at, spelled = youtube._time(entry.get("time"))
    if at is None:
        _count(counts, "skipped_no_timestamp")
        return None
    title = title[len(next(p for p, a in ACTIONS if a == activity)) :]
    slug = SLUG.sub("-", product.lower()).strip("-") or "activity"
    payload: dict[str, Any] = {
        "schema": BROWSE_SCHEMA,
        "raw_id": f"activity:{slug}:{spelled}:{hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]}",
        "url": url,
    }
    if title:
        payload["title"] = title
    payload["action"] = "visit"
    payload["browser"] = "android" if product == ANDROID else f"google-{slug}"
    extra: dict[str, Any] = {"activity": activity, "product": header or product}
    hint = next((h for h in entry.get("locationInfos") or [] if isinstance(h, dict) and h.get("name")), None)
    if hint is not None:
        location = {"name": " ".join(str(hint["name"]).split())}
        if hint.get("source"):
            location["source"] = " ".join(str(hint["source"]).split())
        extra["location_hint"] = location
    payload["extra"] = extra
    return {
        "at": at,
        "end": None,
        "tz": tz,
        "source": SOURCE,
        "kind": BROWSE_KIND,
        "tier": TIER,
        "payload": payload,
    }
