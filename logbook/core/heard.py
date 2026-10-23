"""What you heard (RFC 0046): the words of a podcast episode or a video the owner played, one
`heard/v1` line per work and text source, the text itself in the attachment store (SPEC §1.1).

The profile's constants, the readers of a text (`words_of`: the words of a WebVTT, SRT, podcasting
2.0 JSON, plain-text or TTML text, timings and tags dropped), the gate that keeps a text home
(`crosses`: only a destination whose entry in `policy/crossing.json` says `"heard": true`), and the
reader `logbook show heard` prints (`read`: the texts of a window of local days, through the index, one
attachment opened per text for its excerpt). Core, so `search` can index a text's words beside a
transcript's. Nothing here writes; `sync heard` (`logbook.contrib.adapters.heard`) is the writer."""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import policy, sealing
from .chain import Line

KIND = "heard"
SCHEMA = "heard/v1"
SOURCE = "heard"  # the envelope's source: the step that wrote the line, `sync heard`
TIER = 2  # RFC 0046 §2: what the owner heard is as private as the listen or the watch it joins
TEXT_SOURCES = ("feed", "apple", "captions", "local")
OF_KINDS = ("listen", "watch")
UNKNOWN_LANGUAGE = "und"  # BCP 47: nothing says what language the text is in
CROSSING_KEY = "heard"  # a destination's entry in policy/crossing.json lets texts cross with `true`
EXCERPT_CHARS = 100  # the first words a row shows
DAYS = 14  # `logbook show heard` without a window: the last two weeks, today included

# the formats a text is stored in, by the media type it is stored under
MEDIA_TYPES = {
    "vtt": "text/vtt",
    "srt": "application/x-subrip",
    "json": "application/json",
    "text": "text/plain",
    "ttml": "application/ttml+xml",
}
FORMATS = {media: fmt for fmt, media in MEDIA_TYPES.items()} | {
    "application/srt": "srt",
    "text/srt": "srt",
    "text/x-srt": "srt",
}
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
SRT_START = re.compile(r"\A\s*\d+\s*\r?\n\s*\d{1,2}:\d\d:\d\d[,.]\d{1,3}\s*-->")
VTT_LANGUAGE = re.compile(r"^Language:\s*([A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})*)\s*$", re.M)
CUE_TAG = re.compile(r"</?[^>]+>")
TIMING = re.compile(r"-->")


class Unreadable(ValueError):
    """The bytes are not a text of the format they claim: one sentence saying which."""


# -- the words of a text ------------------------------------------------------------------------


def format_of(media_type: str | None, name: str | None, data: bytes) -> str | None:
    """The format of a text: from its media type when that names one we keep, else the extension
    of the name it came under (`.vtt`, `.srt`, `.json`, `.txt`, `.ttml`), else its first bytes.
    `html` for an HTML page, which is not kept (RFC 0046 §6.1); None when nothing says."""
    media = (media_type or "").split(";")[0].strip().casefold()
    head = data[:64].lstrip(b"\xef\xbb\xbf").lstrip()
    if head.startswith(b"WEBVTT"):
        return "vtt"  # a server that says text/plain for a WebVTT file is common
    if media in FORMATS:
        return FORMATS[media]
    if media in ("text/html", "application/xhtml+xml"):
        return "html"
    suffix = Path(name).suffix.casefold() if name else ""
    by_suffix = {".vtt": "vtt", ".srt": "srt", ".json": "json", ".txt": "text", ".ttml": "ttml"}
    if suffix in by_suffix:
        return by_suffix[suffix]
    if suffix in (".html", ".htm"):
        return "html"
    if SRT_START.match(data[:200].decode("utf-8", "replace")):
        return "srt"
    if head.startswith((b"{", b"[")):
        return "json"
    if head.startswith(b"<"):
        return "html" if head[:15].lower().startswith((b"<!doctype html", b"<html")) else None
    return None


def words_of(data: bytes, fmt: str) -> str:
    """The words of a text, one cue, segment or paragraph per line, timings, cue numbers, tags and
    styling dropped. Raises Unreadable when the bytes are not UTF-8 or not the format."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise Unreadable("the text is not UTF-8") from None
    if fmt in ("vtt", "srt"):
        parts = _cue_words(text)
    elif fmt == "json":
        parts = _json_words(text)
    elif fmt == "ttml":
        parts = _ttml_words(text)
    elif fmt == "text":
        parts = [" ".join(line.split()) for line in text.splitlines()]
    else:
        raise Unreadable(f"no reader for a {fmt} text")
    return "\n".join(part for part in parts if part)


def language_of(data: bytes, fmt: str) -> str | None:
    """The language a text says it is in: a WebVTT header's `Language:`, a TTML root's
    `xml:lang`, a podcasting 2.0 JSON's `language`; None when it says nothing."""
    text = data[:4096].decode("utf-8", "replace") if fmt == "vtt" else None
    if text is not None:
        header = text.split("\n\n", 1)[0]
        found = VTT_LANGUAGE.search(header)
        return found.group(1) if found else None
    if fmt == "ttml":
        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            return None
        lang = root.get(XML_LANG)
        return lang.strip() if lang and lang.strip() else None
    if fmt == "json":
        try:
            parsed = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError):
            return None
        lang = parsed.get("language") if isinstance(parsed, dict) else None
        return lang.strip() if isinstance(lang, str) and lang.strip() else None
    return None


def _cue_words(text: str) -> list[str]:
    """The text lines of every WebVTT or SRT cue: a block's lines after its timing line."""
    out: list[str] = []
    for block in re.split(r"\r?\n\s*\r?\n", text.strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing = next((i for i, line in enumerate(lines) if TIMING.search(line)), None)
        if timing is None:
            continue  # the header, a NOTE, a STYLE or REGION block
        said = " ".join(CUE_TAG.sub("", line) for line in lines[timing + 1 :])
        said = " ".join(said.split())
        if said and (not out or out[-1] != said):  # a rolling caption repeats its last line
            out.append(said)
    return out


def _json_words(text: str) -> list[str]:
    """Podcasting 2.0's JSON transcript: `{"segments": [{"body", "startTime", "speaker"?}]}`, a
    segment's words under `body` (or `text`); a bare list of segments too."""
    try:
        data = json.loads(text)
    except ValueError:
        raise Unreadable("the text is not JSON") from None
    segments = data.get("segments") if isinstance(data, dict) else data
    if not isinstance(segments, list):
        raise Unreadable("the JSON has no segments")
    out: list[str] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        said = segment.get("body", segment.get("text"))
        if isinstance(said, str) and said.strip():
            out.append(" ".join(said.split()))
    return out


def _ttml_words(text: str) -> list[str]:
    """A TTML file's paragraphs (`<p>`), each one's pieces of text joined with a space: Apple's
    transcripts keep every word in a span of its own, with no space between two spans."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        raise Unreadable("the text is not TTML") from None
    out: list[str] = []
    for element in root.iter():
        if not isinstance(element.tag, str) or element.tag.rsplit("}", 1)[-1] != "p":
            continue
        pieces = [" ".join(piece.split()) for piece in element.itertext()]
        said = re.sub(r" ([,.;:!?])", r"\1", " ".join(piece for piece in pieces if piece))
        if said:
            out.append(said)
    return out


def length_of(words: str) -> tuple[int, int]:
    """The `chars` and `words` of a text's words: characters with the line breaks between cues
    counted as spaces, and whitespace-separated words."""
    return len(" ".join(words.split("\n"))), len(words.split())


# -- the work a listen or a watch names ---------------------------------------------------------


def work_key(text_source: str, line: Mapping[str, Any]) -> str | None:
    """The `raw_id` a `heard/v1` line of `text_source` would have for the work `line` names (a
    listen or a watch), or None when the line names none that source can have: `feed` the first 16
    hex of the SHA-256 of the transcript URL, `apple` the episode's uuid in the Podcasts store,
    `captions` the video's id (RFC 0046 §4)."""
    payload = line.get("payload")
    if not isinstance(payload, dict):
        return None
    if text_source == "feed":
        url = transcript_url(payload)
        return None if url is None else f"heard:feed:{hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]}"
    if text_source == "apple":
        uuid = episode_uuid(payload)
        return None if uuid is None else f"heard:apple:{uuid}"
    if text_source == "captions":
        video = video_id(payload)
        return None if video is None else f"heard:captions:{video}"
    return None


def transcript_url(payload: Mapping[str, Any]) -> str | None:
    """A listen line's feed transcript (`extra.transcript_url`, RFC 0019), when it is http(s)."""
    if payload.get("schema") != "listen/v1" or payload.get("media") != "episode":
        return None
    extra = payload.get("extra")
    url = extra.get("transcript_url") if isinstance(extra, dict) else None
    return url if isinstance(url, str) and url.startswith(("https://", "http://")) else None


def episode_uuid(payload: Mapping[str, Any]) -> str | None:
    """The Podcasts store's uuid of an Apple Podcasts listen: `apple-podcasts:<uuid>@<played>`."""
    raw = payload.get("raw_id")
    if payload.get("schema") != "listen/v1" or not isinstance(raw, str):
        return None
    if not raw.startswith("apple-podcasts:") or "@" not in raw:
        return None
    uuid = raw.removeprefix("apple-podcasts:").rsplit("@", 1)[0]
    return uuid or None


def video_id(payload: Mapping[str, Any]) -> str | None:
    """A watched video's id (`watch/v1` `video_id`), when it is one a file can be named by."""
    if payload.get("schema") != "watch/v1" or payload.get("action") != "watched":
        return None
    found = payload.get("video_id")
    return found if isinstance(found, str) and re.fullmatch(r"[A-Za-z0-9_-]{6,64}", found) else None


def title_and_by(line: Mapping[str, Any]) -> tuple[str, str | None]:
    """The work's title and its show or channel, as the listen or watch line spells them."""
    payload = line.get("payload") if isinstance(line.get("payload"), dict) else {}
    assert isinstance(payload, dict)
    title = " ".join(str(payload.get("title") or "").split())
    by = payload.get("show")
    channel = payload.get("channel")
    if not by and isinstance(channel, dict):
        by = channel.get("name")
    by = " ".join(by.split()) if isinstance(by, str) else ""
    return title, by or None


# -- what leaves --------------------------------------------------------------------------------


def crosses(root: Path, destination: str | None) -> bool:
    """Whether a `heard` line, and its text, may cross to `destination`: only when that
    destination's entry in `policy/crossing.json` says `"heard": true` (RFC 0046 §9). The tier and
    the signed days still decide the rest. A destination the file does not name, a file that is
    not a policy, or no destination at all: no."""
    if destination is None:
        return False
    try:
        entry = policy.read(root).get(destination)
    except (policy.PolicyError, OSError, ValueError):
        return False
    return isinstance(entry, dict) and entry.get(CROSSING_KEY) is True


def held(line: Mapping[str, Any], crossing: bool) -> bool:
    """A `heard` line stays home unless the destination lets texts cross (`crosses`)."""
    return line.get("kind") == KIND and not crossing


# -- the reader ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Row:
    """One text the record holds, as `logbook show heard` lists it."""

    id: str
    of: str
    at: str
    day: str
    media: str
    title: str
    by: str | None
    text_source: str
    language: str
    chars: int
    words: int
    excerpt: str | None  # None when the text is sealed and no identity is here, or not in the store
    sealed: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "of": self.of,
            "at": self.at,
            "day": self.day,
            "media": self.media,
            "title": self.title,
            "by": self.by,
            "text_source": self.text_source,
            "language": self.language,
            "chars": self.chars,
            "words": self.words,
            "excerpt": self.excerpt,
            "sealed": self.sealed,
        }


def is_heard(line: Mapping[str, Any]) -> bool:
    payload = line.get("payload")
    return line.get("kind") == KIND and isinstance(payload, dict) and payload.get("schema") == SCHEMA


def read(lb: Any, first: str, last: str, day_of: Any) -> list[Row]:
    """The texts whose listen or watch falls on a local day of [first, last], in time order: the
    `heard` lines of those days through the index (`by_kind` on kind and day), never the record;
    a retracted one, or one whose listen or watch is retracted, left out; one attachment opened
    per text for its excerpt. `day_of(at)` is the local day of an instant under the record's
    `day_start`."""
    from .store import retractions

    with lb.index() as idx:
        found = idx.by_kind(KIND, first, last)
        retracted = retractions(idx.retractions())
    rows: list[Row] = []
    for line in sorted(found, key=lambda line: (str(line["at"]), int(line["seq"]))):
        if str(line["id"]) in retracted:
            continue
        if _sealed_heard(line):  # no identity on this machine: a row that says so, nothing more
            rows.append(_sealed_row(line, day_of))
            continue
        if not is_heard(line):
            continue
        p = line["payload"]
        if str(p.get("of")) in retracted:
            continue
        excerpt, sealed = _excerpt(lb, p)
        rows.append(
            Row(
                id=str(line["id"]),
                of=str(p.get("of") or ""),
                at=str(line["at"]),
                day=str(day_of(str(line["at"]))),
                media=str(p.get("media") or ""),
                title=str(p.get("title") or ""),
                by=p.get("by") if isinstance(p.get("by"), str) else None,
                text_source=str(p.get("text_source") or ""),
                language=str(p.get("language") or UNKNOWN_LANGUAGE),
                chars=_count(p.get("chars")),
                words=_count(p.get("words")),
                excerpt=excerpt,
                sealed=sealed,
            )
        )
    return rows


def _sealed_heard(line: Mapping[str, Any]) -> bool:
    payload = line.get("payload")
    return isinstance(payload, dict) and payload.get("schema") == "sealed/v1" and payload.get("of") == SCHEMA


def _sealed_row(line: Mapping[str, Any], day_of: Any) -> Row:
    at = str(line["at"])
    return Row(
        id=str(line["id"]), of="", at=at, day=str(day_of(at)), media="", title="", by=None,
        text_source="?", language=UNKNOWN_LANGUAGE, chars=0, words=0, excerpt=None, sealed=True,
    )  # fmt: skip


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def text_of(lb: Any, payload: Mapping[str, Any]) -> str | None:
    """The words of a `heard/v1` line's text from the store, or None when the store does not hold
    it, it is sealed and no identity is here, or it is not the format the line says."""
    ref = payload.get("text")
    fmt = payload.get("format")
    if not isinstance(ref, dict) or not isinstance(fmt, str):
        return None
    sha256 = ref.get("sha256")
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
        return None
    try:
        return words_of(lb.attachment_bytes(sha256), fmt)
    except (OSError, ValueError, sealing.SealError):
        return None


def _excerpt(lb: Any, payload: Mapping[str, Any]) -> tuple[str | None, bool]:
    """The first words of the text, up to `EXCERPT_CHARS` and cut at a word, and whether the
    text was sealed with no identity to open it."""
    words = text_of(lb, payload)
    if words is None:
        ref = payload.get("text")
        sha256 = ref.get("sha256") if isinstance(ref, dict) else None
        sealed = isinstance(sha256, str) and sealing.is_sealed_file(Path(lb.root) / "attachments" / sha256)
        return None, sealed
    return excerpt(words), False


def excerpt(words: str, limit: int = EXCERPT_CHARS) -> str:
    """One line: the first words of a text, cut at a word, with `…` when there is more."""
    flat = " ".join(words.split())
    if len(flat) <= limit:
        return flat
    cut = flat[:limit].rsplit(" ", 1)[0] if " " in flat[:limit] else flat[:limit]
    return cut.rstrip(",;:") + "…"


def row_text(payload: Mapping[str, Any]) -> str:
    """The row `show` prints for a `heard/v1` line: `Title — Show · feed · nb · 7,012 words`."""
    title = str(payload.get("title") or "")
    by = payload.get("by")
    parts = [f"{title} — {by}" if isinstance(by, str) and by else title]
    parts.append(str(payload.get("text_source") or "?"))
    parts.append(str(payload.get("language") or UNKNOWN_LANGUAGE))
    words = _count(payload.get("words"))
    parts.append(f"{words:,} {'word' if words == 1 else 'words'}")
    return " · ".join(parts)


def body_of(line: Line, lb: Any) -> list[str]:
    """What `search` indexes for a `heard` line: its title and show or channel, then the words of
    its text from the store (RFC 0046 §8). Never the ids, the digest or the URL."""
    payload = line.get("payload")
    if not isinstance(payload, dict):
        return []
    parts = [str(payload[key]) for key in ("title", "by") if isinstance(payload.get(key), str)]
    words = text_of(lb, payload)
    if words:
        parts.append(words)
    return parts
