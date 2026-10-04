"""Google Takeout YouTube history → watch/v1 (RFC 0018).

Takeout writes `Takeout/YouTube and YouTube Music/history/watch-history.json` and
`search-history.json` (when the owner asked for JSON): one array each of
`{header, title, titleUrl?, subtitles?: [{name, url?}], time, products, activityControls?,
details?: [{name}]}`. `title` starts with the activity — `Watched …`, `Searched for …`, `Visited …`
— and `header` is the product (`YouTube`, `YouTube Music`). An ad carries
`details: [{name: "From Google Ads"}]`.

Takeout's default is HTML, `watch-history.html` and `search-history.html`: the same entries as
Material cards, one `div.outer-cell` each, with the product in its `header-cell`, the activity and
the video's link, the channel's link and the time as `<br>`-separated lines of the first
`content-cell`, and `Products:` and `Details:` in the caption cell. The reader walks that structure
(the stdlib `html.parser`, fed a chunk at a time, so a history of any size streams) into the same
entry shape and maps it the same way. The HTML spells the time in the owner's own zone by its
abbreviation (`Mar 4, 2026, 10:00:00 AM CET`): a time in UTC is read as it is, one whose
abbreviation the record's zone uses at that wall-clock time (`times.parse_in_zone`) is read in that
zone, and any other is skipped and counted (`skipped_unknown_zone`), never guessed. `raw_id` carries
the time as the file spells it (its runs of whitespace, the narrow no-break space newer exports put
before `AM`, as one space), so the JSON and the HTML flavour of one export are two spellings of one
watch and dedupe within their own flavour.

One line per watch and per search: kind `watch`, tier 2, source `google-takeout`, `at` the
entry's `time` in UTC to the second, `tz` the record's zone. `raw_id` is
`youtube:<time as the export spells it>:<sha256(titleUrl, else the title)[:16]>`. `action` is
`watched` or `searched`, `title` the words after the activity (a search's query), `url` the
`titleUrl`, `video_id` its `v=` when it has one, `channel` the first subtitle as `{name, url?}`,
`service` `youtube` or `youtube-music` from `header`. An ad (rule 2) and an activity that is
neither a watch nor a search (rule 3) are skipped and counted; an entry with no `time` too; a
removed video (no `titleUrl`) is a line without `url`, counted. Streamed through `ijson`, one
entry in memory at a time, whatever the size of the history. Pure: no network, never writes the
source.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from ...stream import ijson
from . import SOURCE, times

NAME = "google-takeout-youtube"
KIND = "watch"
TIER = 2
SCHEMA = "watch/v1"
FOLDER = "history"

SUFFIX = ".json"
HTML_SUFFIX = ".html"
MY_ACTIVITY = "MyActivity.json"  # `My Activity/YouTube/` is this history too; `My Activity/Search/` is not
SNIFF_BYTES = 4096
HTML_SNIFF_BYTES = 65536  # the HTML head carries a style block before the first card
MARKS = (b'"YouTube watch history"', b'"YouTube search history"', b'"Watched ', b'"Searched for ')
HTML_MARKS = (b"YouTube watch history", b"YouTube search history", b"Watched", b"Searched for")
HTML_CELLS = (b"outer-cell", b"content-cell")
HTML_CHUNK = 1 << 20
ACTIONS = (("Watched ", "watched"), ("Searched for ", "searched"))
SERVICES = {"YouTube": "youtube", "YouTube Music": "youtube-music"}
AD = "From Google Ads"


def sniff(path: Path) -> bool:
    """A `watch-history.json` or `search-history.json`, or a folder holding one. Never raises."""
    path = Path(path)
    try:
        if path.is_dir():
            return any(_is_history(f) for f in sorted(path.iterdir()))
        return _is_history(path)
    except OSError:
        return False


def _is_history(path: Path) -> bool:
    if not path.is_file():
        return False
    suffix = path.suffix.lower()
    if suffix == HTML_SUFFIX:
        with path.open("rb") as fh:
            head = fh.read(HTML_SNIFF_BYTES)
        return all(cell in head for cell in HTML_CELLS) and any(mark in head for mark in HTML_MARKS)
    if suffix != SUFFIX:
        return False
    with path.open("rb") as fh:
        head = fh.read(SNIFF_BYTES)
    if path.name == MY_ACTIVITY and b"YouTube" not in head:  # another product's My Activity file
        return False
    return head.lstrip().startswith(b"[") and b'"header"' in head and any(mark in head for mark in MARKS)


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
) -> Iterator[dict[str, Any]]:
    """One watch/v1 line draft per watch and per search in `path` (a history file, or the folder
    of them), oldest first. `since` is RFC3339 UTC; `timezone` is the record's zone."""
    counts = counts if counts is not None else {}
    path = Path(path)
    files = [path] if path.is_file() else sorted(f for f in path.iterdir() if _is_history(f))
    tz = timezone or "UTC"
    drafts: list[dict[str, Any]] = []
    for file in files:
        for entry in _entries(file):
            draft = _draft(entry, tz, counts)
            if draft is not None and (since is None or draft["at"] >= since):
                drafts.append(draft)
    yield from sorted(drafts, key=lambda d: (d["at"], d["payload"]["raw_id"]))


def _entries(file: Path) -> Iterator[dict[str, Any]]:
    """The file's entries in the JSON shape, one at a time, whichever flavour the file is."""
    if file.suffix.lower() == HTML_SUFFIX:
        yield from _html_entries(file)
        return
    with file.open("rb") as fh:
        for entry in ijson.items(fh, "item"):
            if isinstance(entry, dict):
                yield entry


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _draft(entry: dict[str, Any], tz: str, counts: dict[str, int]) -> dict[str, Any] | None:
    if any(isinstance(d, dict) and d.get("name") == AD for d in entry.get("details") or []):
        _count(counts, "skipped_ad")
        return None
    title = " ".join(str(entry.get("title") or "").split())
    action = next((a for prefix, a in ACTIONS if title.startswith(prefix)), None)
    if action is None:
        _count(counts, "skipped_other_activity")
        return None
    at, spelled = _time(entry.get("time"), tz)
    if at is None:
        zone = times.english_zone(entry.get("time"))
        _count(counts, "skipped_unknown_zone" if zone else "skipped_no_timestamp")
        return None
    title = title[len(next(p for p, a in ACTIONS if a == action)) :]
    url = str(entry.get("titleUrl") or "")
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": f"youtube:{spelled}:{hashlib.sha256((url or title).encode('utf-8')).hexdigest()[:16]}",
        "action": action,
        "title": title,
    }
    if url:
        payload["url"] = url
        video_id = parse_qs(urlsplit(url).query).get("v", [""])[0]
        if video_id and action == "watched":
            payload["video_id"] = video_id
    else:
        _count(counts, "no_url")
    subtitles = [s for s in entry.get("subtitles") or [] if isinstance(s, dict) and s.get("name")]
    if subtitles:
        channel: dict[str, str] = {"name": " ".join(str(subtitles[0]["name"]).split())}
        if subtitles[0].get("url"):
            channel["url"] = str(subtitles[0]["url"])
        payload["channel"] = channel
    header = str(entry.get("header") or "")
    payload["service"] = SERVICES.get(header, header.lower().replace(" ", "-") or "youtube")
    return {"at": at, "end": None, "tz": tz, "source": SOURCE, "kind": KIND, "tier": TIER, "payload": payload}


def _time(value: object, zone: str | None = None) -> tuple[str | None, str]:
    """(`at` to the second in UTC, the string as the export spells it), or (None, ""): RFC 3339 as
    the JSON spells it; the HTML's English clock in UTC, or in `zone` when its abbreviation is that
    zone's at that wall-clock time."""
    if not isinstance(value, str) or not value:
        return None, ""
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        at, spelled = times.parse(value)
        if at is None and zone:
            at, spelled = times.parse_in_zone(value, zone)
        return at, spelled
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), value


# -- the HTML flavour ----------------------------------------------------------------------------------


def _html_entries(file: Path) -> Iterator[dict[str, Any]]:
    """The cards of a `watch-history.html` or `search-history.html` as JSON-shaped entries, one at a
    time; the file is fed to the parser a chunk at a time."""
    parser = _Cards()
    with file.open(encoding="utf-8", errors="replace") as fh:
        while chunk := fh.read(HTML_CHUNK):
            parser.feed(chunk)
            yield from parser.drain()
    parser.close()
    yield from parser.drain()


class _Cards(HTMLParser):
    """Collects each `div.outer-cell`: the `header-cell` text, the first `content-cell`'s lines of
    text and links (split on `<br>`), and the caption cell's `Products:` and `Details:` lists."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.done: list[dict[str, Any]] = []
        self._depth = 0
        self._card: int | None = None  # the div depth of the open card
        self._cell: str | None = None  # header, content, caption
        self._cell_depth = 0
        self._header: list[str] = []
        self._lines: list[list[Any]] = []  # content: each line a list of str and (href, text)
        self._content_seen = False
        self._caption: list[str] = []
        self._href: str | None = None
        self._link: list[str] = []

    def drain(self) -> list[dict[str, Any]]:
        found, self.done = self.done, []
        return found

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "div":
            self._depth += 1
            classes = (dict(attrs).get("class") or "").split()
            if "outer-cell" in classes:
                self._card, self._cell = self._depth, None
                self._header, self._lines, self._caption, self._content_seen = [], [], [""], False
            elif self._card is not None and self._cell is None:
                if "header-cell" in classes:
                    self._cell, self._cell_depth = "header", self._depth
                elif "content-cell" in classes and "mdl-typography--caption" in classes:
                    self._cell, self._cell_depth = "caption", self._depth
                elif "content-cell" in classes and not self._content_seen:
                    self._cell, self._cell_depth, self._content_seen = "content", self._depth, True
                    self._lines = [[]]
        elif tag == "br":
            if self._cell == "content":
                self._lines.append([])
            elif self._cell == "caption":
                self._caption.append("")
        elif tag == "a" and self._cell == "content":
            self._href, self._link = dict(attrs).get("href") or "", []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._cell == "content" and self._href is not None:
            self._lines[-1].append((self._href, "".join(self._link)))
            self._href = None
        elif tag == "div":
            if self._cell is not None and self._depth == self._cell_depth:
                self._cell = None
            elif self._card is not None and self._depth == self._card:
                self.done.append(self._entry())
                self._card = None
            self._depth = max(self._depth - 1, 0)

    def handle_data(self, data: str) -> None:
        if self._cell == "header":
            self._header.append(data)
        elif self._cell == "content":
            if self._href is not None:
                self._link.append(data)
            else:
                self._lines[-1].append(data)
        elif self._cell == "caption":
            self._caption[-1] += data

    def _entry(self) -> dict[str, Any]:
        lines = [
            line
            for line in self._lines
            if any(_text(part if isinstance(part, str) else part[1]) for part in line)
        ]
        entry: dict[str, Any] = {"header": _text("".join(self._header))}
        if lines:
            first = lines[0]
            entry["title"] = _text("".join(part if isinstance(part, str) else part[1] for part in first))
            links = [part for part in first if isinstance(part, tuple)]
            if links:
                entry["titleUrl"] = links[0][0]
        subtitles = [
            {"name": _text(part[1]), "url": part[0]}
            for line in lines[1:]
            for part in line
            if isinstance(part, tuple) and _text(part[1])
        ]
        if subtitles:
            entry["subtitles"] = subtitles
        plain = [_text("".join(part for part in line if isinstance(part, str))) for line in lines[1:]]
        plain = [text for text in plain if text]
        if plain:
            entry["time"] = plain[-1]
        heading = None
        for text in (_text(t) for t in self._caption):
            if text.endswith(":"):
                heading = text[:-1].lower()
            elif text and heading == "products":
                entry.setdefault("products", []).append(text)
            elif text and heading == "details":
                entry.setdefault("details", []).append({"name": text})
        return entry


def _text(value: object) -> str:
    return " ".join(str(value).split()) if isinstance(value, str) else ""
