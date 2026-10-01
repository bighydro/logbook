"""Google Takeout Chrome/ → browse/v1 (RFC 0017).

Takeout writes `Takeout/Chrome/History.json` — `{"Browser History": [{title, url, time_usec,
page_transition, page_transition_qualifier?, client_id, favicon_url}]}` — and
`Takeout/Chrome/Bookmarks.html`, the Netscape bookmark file every browser exports: nested `<DL>`
lists, a folder as `<DT><H3 ADD_DATE=…>name</H3>`, a bookmark as `<DT><A HREF=… ADD_DATE=…>title</A>`.
The folder's other files (Autofill, Extensions, …) are not read.

One line per visit and one per bookmark: kind `browse`, tier 2, source `google-takeout`,
`browser` `chrome`, `tz` the record's zone. A visit: `at` from `time_usec` (to the second),
`raw_id` `chrome:<time_usec>:<sha256(url)[:16]>`, `action` `visit`, `transition` the
`page_transition` lower-cased, `extra.transition_qualifier` when the export has one; `client_id`
and `favicon_url` are not kept. A bookmark: `at` from `ADD_DATE` (unix seconds), `raw_id`
`chrome-bookmark:<add_date>:<sha256(url)[:16]>`, `action` `bookmark`, `folder` the `/`-joined path
of `<H3>` names above it. An entry with no url, or no time, is skipped and counted (RFC 0017
rule 3). Pure: no network, never writes the source.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from . import SOURCE

NAME = "google-takeout-chrome"
KIND = "browse"
TIER = 2
SCHEMA = "browse/v1"
FOLDER = "Chrome"
BROWSER = "chrome"

HISTORY_KEY = "Browser History"
BOOKMARKS_DOCTYPE = b"NETSCAPE-Bookmark-file-1"
SNIFF_BYTES = 512
NO_URL = "skipped_no_url"
NO_TIME = "skipped_no_timestamp"


def sniff(path: Path) -> bool:
    """Chrome's `History.json` or a Netscape `Bookmarks.html`, or a folder holding either — Takeout's
    `Chrome/`. Never raises."""
    path = Path(path)
    try:
        if path.is_dir():
            return any(_kind_of(f) is not None for f in sorted(path.iterdir()))
        return _kind_of(path) is not None
    except OSError:
        return False


def _kind_of(path: Path) -> str | None:
    """`history`, `bookmarks` or None, from the file's name and first bytes."""
    if not path.is_file():
        return None
    suffix = path.suffix.lower()
    if suffix not in (".json", ".html", ".htm"):
        return None
    with path.open("rb") as fh:
        head = fh.read(SNIFF_BYTES)
    if suffix == ".json" and f'"{HISTORY_KEY}"'.encode() in head:
        return "history"
    if suffix != ".json" and BOOKMARKS_DOCTYPE in head:
        return "bookmarks"
    return None


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
) -> Iterator[dict[str, Any]]:
    """One browse/v1 line draft per visit of a `History.json` and per bookmark of a `Bookmarks.html`
    at `path` (or in the folder), oldest first. `since` is RFC3339 UTC; `timezone` is the
    record's zone."""
    counts = counts if counts is not None else {}
    path = Path(path)
    files = [path] if path.is_file() else sorted(path.iterdir())
    drafts: list[dict[str, Any]] = []
    tz = timezone or "UTC"
    for file in files:
        kind = _kind_of(file)
        if kind == "history":
            drafts.extend(_visits(file, tz, counts))
        elif kind == "bookmarks":
            drafts.extend(_bookmarks(file, tz, counts))
    for draft in sorted(drafts, key=lambda d: (d["at"], d["payload"]["raw_id"])):
        if since is None or draft["at"] >= since:
            yield draft


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _visits(file: Path, tz: str, counts: dict[str, int]) -> Iterator[dict[str, Any]]:
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    entries = data.get(HISTORY_KEY) if isinstance(data, dict) else None
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        url = str(entry.get("url") or "")
        usec = entry.get("time_usec")
        if not url:
            _count(counts, NO_URL)
            continue
        if not isinstance(usec, int):
            _count(counts, NO_TIME)
            continue
        payload = _payload(f"{BROWSER}:{usec}:{_digest(url)}", url, entry.get("title"), "visit")
        transition = str(entry.get("page_transition") or "").lower()
        if transition:
            payload["transition"] = transition
        qualifier = str(entry.get("page_transition_qualifier") or "").lower()
        if qualifier:
            payload["extra"] = {"transition_qualifier": qualifier}
        yield _line(_rfc3339(usec / 1_000_000), tz, payload)


def _bookmarks(file: Path, tz: str, counts: dict[str, int]) -> Iterator[dict[str, Any]]:
    parser = _Bookmarks()
    try:
        parser.feed(file.read_text(encoding="utf-8", errors="replace"))
        parser.close()
    except OSError:
        return
    for url, title, added, folder in parser.found:
        if not url:
            _count(counts, NO_URL)
            continue
        if added is None:
            _count(counts, NO_TIME)
            continue
        payload = _payload(f"{BROWSER}-bookmark:{added}:{_digest(url)}", url, title, "bookmark")
        if folder:
            payload["folder"] = folder
        yield _line(_rfc3339(added), tz, payload)


class _Bookmarks(HTMLParser):
    """Walks a Netscape bookmark file: `<H3>` names the folder of the `<DL>` that follows it, `<A>`
    is a bookmark in the current folder."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[tuple[str, str, int | None, str]] = []
        self._path: list[str] = []
        self._pending: str | None = None  # the <H3> just read, named by the next <DL>
        self._link: tuple[str, int | None] | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "h3":
            self._text = []
            self._pending = ""
        elif tag == "dl":
            self._path.append(self._pending or "")
            self._pending = None
        elif tag == "a":
            given = {k.lower(): v for k, v in attrs}
            self._link = (str(given.get("href") or ""), _seconds(given.get("add_date")))
            self._text = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "h3" and self._pending is not None:
            self._pending = " ".join("".join(self._text).split())
        elif tag == "dl" and self._path:
            self._path.pop()
        elif tag == "a" and self._link is not None:
            url, added = self._link
            folder = "/".join(name for name in self._path if name)
            self.found.append((url, " ".join("".join(self._text).split()), added, folder))
            self._link = None

    def handle_data(self, data: str) -> None:
        self._text.append(data)


def _seconds(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None


def _payload(raw_id: str, url: str, title: object, action: str) -> dict[str, Any]:
    payload: dict[str, Any] = {"schema": SCHEMA, "raw_id": raw_id, "url": url}
    name = " ".join(str(title or "").split())
    if name:
        payload["title"] = name
    payload["action"] = action
    payload["browser"] = BROWSER
    return payload


def _line(at: str, tz: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"at": at, "end": None, "tz": tz, "source": SOURCE, "kind": KIND, "tier": TIER, "payload": payload}


def _digest(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def _rfc3339(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
