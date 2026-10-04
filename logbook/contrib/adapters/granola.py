"""Granola → transcript/v1 (RFC 0004), live: pulls recordings from Granola's public API, and the AI
summary of each as a derived note/v1 line (RFC 0010).

The API (docs.granola.ai, public API v1, Business and Enterprise plans; key `grn_…` from
Settings → Connectors → API keys, sent as `Authorization: Bearer`), as documented in September 2026:

    GET /v1/notes?created_after=&page_size=&cursor=
        → {notes: [{id, title, owner, created_at, updated_at}], hasMore, cursor}
    GET /v1/notes/{id}?include=transcript
        → the note: title, attendees [{name, email}], calendar_event, folder_membership,
          summary_text, web_url, transcript [segments]
    GET /v1/notes/{id}/transcript?page_size=&cursor=
        → {transcript: [segments], hasMore, cursor}; used when the note answers
          413 TRANSCRIPT_TOO_LARGE (API v1.4.0)

A segment is `{speaker: {source, attribution, diarization_label?, name?}, text, start_time,
end_time}`.

Every recording goes through `transcript.draft`, the file adapter's mapping (ADR 0017): `at`/`end`
are the first segment's start and the last segment's end (else the calendar event's times, else
`created_at` and null), `raw_id` is `granola:<note id>`, `participants` are the attendees as Granola
names them, then any speaker label the attendees do not cover (source-native, never resolved),
`content` is the segments as JSON, stored once under their digest (SPEC §1.1). A transcript exported
by hand as transcript/v1 JSON and the same one pulled here are one line. Granola's summary is a
model's words, so it is never `payload.summary`; it is a separate note/v1 line, tier 2,
`extra.derived = true`, `extra.derived_from` the transcript line's id (the one already in the
record, else the one this pull mints), skipped with `LOGBOOK_GRANOLA_SUMMARIES=0`. A note Granola
made without recording (one empty turn from an instant to the same instant: `duration_s` 0, no
words) is not a transcript: no transcript/v1 line, nothing stored, only the summary, whose `raw_id`
is as ever and whose `extra.derived_from` names a transcript only when the record already has one.

The watermark is the recording's end; `resume` starts a pull a lookback (24 h,
`LOGBOOK_GRANOLA_LOOKBACK_H`) before it and dedupe absorbs the overlap. Every request is retried
once on a connection failure, a timeout, 429 or a 5xx; then the pull fails with one clear message
and nothing has been yielded, so `sync` writes no partial batch. The key is sent only in the header,
never in a URL, never printed. Network happens only inside `pull` (ADR 0012).
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ...core.attachments import reference
from ...core.store import uuid7
from ...core.transcripts import Turn, _stamp_of, participants
from .transcript import KIND, TIER, draft

__all__ = [
    "ENV",
    "KIND",
    "NAME",
    "TIER",
    "Config",
    "configure",
    "draft",
    "pull",
    "recorded",
    "resume",
    "summary_of",
    "transcript_of",
    "watermark",
]

NAME = "granola"
ENV = ("LOGBOOK_GRANOLA_KEY",)
URL_ENV = "LOGBOOK_GRANOLA_URL"
DEFAULT_URL = "https://public-api.granola.ai/v1"
LOOKBACK_ENV = "LOGBOOK_GRANOLA_LOOKBACK_H"
LOOKBACK_H = 24.0
SUMMARIES_ENV = "LOGBOOK_GRANOLA_SUMMARIES"
UNIT = "notes"
PAGE_SIZE = 30  # the API's maximum for /notes
SEGMENT_PAGE_SIZE = 100  # the API's maximum for /notes/{id}/transcript
TIMEOUT_S = 60
RETRY_AFTER_S = 2.0
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
TOO_LARGE = 413
MEDIA_TYPE = "application/json"
SUMMARY_TIER = 2
NO_SUMMARY = "no_summary"
NO_RECORDING = "no_recording"


@dataclass(frozen=True)
class Config:
    url: str
    key: str = field(repr=False)
    lookback_h: float = LOOKBACK_H
    summaries: bool = True


def configure(env: Mapping[str, str]) -> Config | None:
    """Config from LOGBOOK_GRANOLA_KEY (required), LOGBOOK_GRANOLA_URL (default the public API),
    LOGBOOK_GRANOLA_LOOKBACK_H and LOGBOOK_GRANOLA_SUMMARIES (`0` skips the summary lines). None
    without a key; ValueError for a lookback that is not a number of hours ≥ 0."""
    key = env.get(ENV[0], "").strip()
    if not key:
        return None
    url = env.get(URL_ENV, "").strip() or DEFAULT_URL
    raw = env.get(LOOKBACK_ENV, "").strip()
    lookback = LOOKBACK_H
    if raw:
        try:
            lookback = float(raw)
        except ValueError:
            lookback = -1.0
        if not math.isfinite(lookback) or lookback < 0:
            raise ValueError(f"{LOOKBACK_ENV} must be a number of hours, 0 or more, not {raw!r}")
    summaries = env.get(SUMMARIES_ENV, "").strip().lower() not in ("0", "false", "no", "off")
    return Config(url=url.rstrip("/"), key=key, lookback_h=lookback, summaries=summaries)


def resume(config: Config, mark: str) -> str:
    """Where a pull starts given the watermark (a recording's end): the lookback before it."""
    start = datetime.fromisoformat(mark.replace("Z", "+00:00")).astimezone(UTC) - timedelta(
        hours=config.lookback_h
    )
    return start.strftime("%Y-%m-%dT%H:%M:%SZ")


def watermark(draft: dict[str, Any]) -> str | None:
    """The recording's end, else its start; a summary note sits at the end too."""
    return str(draft["end"] or draft["at"])


def pull(
    config: Config,
    since: str | None = None,
    progress: Callable[[int, float], None] | None = None,
    counts: dict[str, int] | None = None,
    store: Callable[[bytes], object] | None = None,
    lookup: Callable[[str, str], str | None] | None = None,
) -> Iterator[dict[str, Any]]:
    """Every note created after `since` (RFC3339 UTC; None means all), oldest first: one
    transcript/v1 draft each, followed by its summary as a note/v1 draft; a note with no recording
    gives only the summary and is counted. Everything is fetched before the first draft is yielded,
    so a failure yields nothing. `store` is called with the transcript bytes just before its line;
    `lookup(source, raw_id)` gives the id of a transcript already in the record, which the summary
    then points at. `progress(notes, elapsed)` after every page of the listing."""
    counts = counts if counts is not None else {}
    started = time.monotonic()
    listed: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {}
        if since:
            params["created_after"] = since
        params["page_size"] = PAGE_SIZE
        if cursor:
            params["cursor"] = cursor
        page = _get(config, "/notes", params)
        notes = page.get("notes")
        if not isinstance(notes, list):
            raise ValueError("expected a JSON object with a `notes` array from GET /notes")
        listed.extend(n for n in notes if isinstance(n, dict) and isinstance(n.get("id"), str))
        if progress is not None:
            progress(len(listed), time.monotonic() - started)
        cursor = page.get("cursor") if page.get("hasMore") else None
        if not cursor:
            break
    pairs: list[tuple[dict[str, Any], bytes, dict[str, Any] | None, bool]] = []
    for stub in listed:
        note, segments = _note_with_transcript(config, str(stub["id"]))
        line = transcript_of(note, segments)
        has_recording = recorded(line, segments)
        if has_recording:
            line["id"] = uuid7()
        else:
            counts[NO_RECORDING] = counts.get(NO_RECORDING, 0) + 1
        summary: dict[str, Any] | None = None
        if config.summaries:
            existing = lookup(NAME, str(line["payload"]["raw_id"])) if lookup is not None else None
            summary = summary_of(note, line, existing or (str(line["id"]) if has_recording else None))
            if summary is None:
                counts[NO_SUMMARY] = counts.get(NO_SUMMARY, 0) + 1
        pairs.append((line, _content(segments), summary, has_recording))
    pairs.sort(key=lambda p: str(p[0]["at"]))  # stable: the server's order within a second
    for line, data, summary, has_recording in pairs:
        if has_recording:
            if store is not None:
                store(data)
            yield line
        if summary is not None:
            yield summary


def recorded(line: Mapping[str, Any], segments: list[Any]) -> bool:
    """Whether the note has a recording behind its transcript line: a segment with words, or a
    span above zero seconds. A note made without recording has one empty segment that starts and
    ends at the same instant, so `duration_s` is 0 and no turn says anything."""
    words = any(str(s.get("text") or "").strip() for s in segments if isinstance(s, dict))
    return words or line["payload"]["extra"].get("duration_s") != 0


def transcript_of(note: Mapping[str, Any], segments: list[Any]) -> dict[str, Any]:
    """One note and its transcript segments → the transcript/v1 line draft, through the file
    adapter's mapping. `at`/`end` are the segments' span, else the calendar event's, else
    `created_at` and null."""
    turns = [
        Turn(_label(s.get("speaker")), str(s.get("text") or "")) for s in segments if isinstance(s, dict)
    ]
    starts = sorted(str(s["start_time"]) for s in segments if isinstance(s, dict) and s.get("start_time"))
    ends = sorted(str(s["end_time"]) for s in segments if isinstance(s, dict) and s.get("end_time"))
    event: Mapping[str, Any] = note["calendar_event"] if isinstance(note.get("calendar_event"), dict) else {}
    at = _stamp(starts[0] if starts else event.get("scheduled_start_time") or note.get("created_at"))
    end = _stamp(ends[-1] if ends else (event.get("scheduled_end_time") if not starts else None))
    if at is None:
        raise ValueError(f"note {note.get('id')!r} has no created_at")
    note_id = str(note["id"])
    extra: dict[str, Any] = {}
    folders = [
        str(f["name"]) for f in note.get("folder_membership") or [] if isinstance(f, dict) and f.get("name")
    ]
    if folders:
        extra["folders"] = folders
    title = note.get("title")
    web_url = note.get("web_url")
    return draft(
        source=NAME,
        at=at,
        end=end,
        raw_id=f"{NAME}:{note_id}",
        content=reference(_content(segments), MEDIA_TYPE),
        turns=turns,
        tier=TIER,
        title=str(title) if isinstance(title, str) and title else None,
        participants=participants(turns, _attendees(note.get("attendees"))),
        source_uri=str(web_url) if isinstance(web_url, str) and web_url else None,
        extra=extra,
    )


def summary_of(
    note: Mapping[str, Any], line: Mapping[str, Any], transcript_id: str | None
) -> dict[str, Any] | None:
    """Granola's AI summary as a note/v1 draft that points at the transcript line, or None when the
    note has none. Tier 2 (a note); `at` is the recording's end (else start), where the summary was
    made; `raw_id` is stable, so an edited summary is not re-logged. `transcript_id` None (a note
    with no recording and none in the record) leaves `derived_from` out; `derived_from_raw_id`
    still names the transcript the note would have had."""
    text = note.get("summary_text")
    if not isinstance(text, str) or not text.strip():
        return None
    payload: dict[str, Any] = {"schema": "note/v1", "text": text}
    title = note.get("title")
    if isinstance(title, str) and title:
        payload["title"] = title
    payload["raw_id"] = f"{line['payload']['raw_id']}:summary"
    modified = _stamp(note.get("updated_at"))
    if modified:
        payload["modified_at"] = modified
    payload["extra"] = {"derived": True}
    if transcript_id is not None:
        payload["extra"]["derived_from"] = transcript_id
    payload["extra"]["derived_from_raw_id"] = line["payload"]["raw_id"]
    return {
        "at": line["end"] or line["at"],
        "end": None,
        "tz": None,
        "source": NAME,
        "kind": "note",
        "tier": SUMMARY_TIER,
        "payload": payload,
    }


# -- the API -----------------------------------------------------------------------------------------


def _note_with_transcript(config: Config, note_id: str) -> tuple[dict[str, Any], list[Any]]:
    """The note with its segments: inline when the API allows, else the note alone and the paged
    transcript endpoint."""
    try:
        note = _get(config, f"/notes/{note_id}", {"include": "transcript"})
    except _TooLarge:
        note = _get(config, f"/notes/{note_id}", {})
        return note, _paged_transcript(config, note_id)
    segments = note.get("transcript")
    return note, segments if isinstance(segments, list) else []


def _paged_transcript(config: Config, note_id: str) -> list[Any]:
    segments: list[Any] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"page_size": SEGMENT_PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor
        page = _get(config, f"/notes/{note_id}/transcript", params)
        part = page.get("transcript")
        if not isinstance(part, list):
            raise ValueError(f"expected a `transcript` array from GET /notes/{note_id}/transcript")
        segments.extend(part)
        cursor = page.get("cursor") if page.get("hasMore") else None
        if not cursor:
            return segments


class _TooLarge(Exception):
    """413 TRANSCRIPT_TOO_LARGE: fetch the transcript by its own endpoint."""


def _get(config: Config, path: str, params: Mapping[str, Any]) -> dict[str, Any]:
    """One GET, retried once on a connection failure, a timeout, 429 or a 5xx. The only network
    call in this module. Raises OSError with a message that names the request, never the key."""
    query = f"?{urlencode(params)}" if params else ""
    req = Request(
        f"{config.url}{path}{query}",
        headers={"Authorization": f"Bearer {config.key}", "Accept": "application/json"},
        method="GET",
    )
    failure: str | None = None
    for attempt in (1, 2):
        try:
            with urlopen(req, timeout=TIMEOUT_S) as response:
                return _decode(response.read(), path)
        except HTTPError as e:
            if e.code == TOO_LARGE:
                raise _TooLarge() from None
            if e.code not in RETRY_STATUSES:
                raise OSError(_explain(path, f"HTTP {e.code} {e.reason}", e.code)) from None
            failure = f"HTTP {e.code} {e.reason}"
        except URLError as e:
            failure = str(e.reason)
        except TimeoutError:
            failure = f"timed out after {TIMEOUT_S}s"
        if attempt == 1:
            time.sleep(RETRY_AFTER_S)
    raise OSError(_explain(path, f"{failure}, twice", None))


def _explain(path: str, what: str, status: int | None) -> str:
    hint = ""
    if status in (401, 403):
        hint = f" (check {ENV[0]}; the key needs a Granola Business or Enterprise plan)"
    elif status == 404:
        hint = f" (check {URL_ENV}; the default is {DEFAULT_URL})"
    return f"Granola API GET {path}: {what}{hint}"


def _decode(body: bytes, path: str) -> dict[str, Any]:
    try:
        doc = json.loads(body.decode("utf-8"), parse_constant=lambda _name: None)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"Granola API GET {path}: the answer is not JSON ({e})") from None
    if not isinstance(doc, dict):
        raise ValueError(f"Granola API GET {path}: expected a JSON object, got a JSON {type(doc).__name__}")
    return doc


# -- the mapping's pieces --------------------------------------------------------------------------------


def _content(segments: list[Any]) -> bytes:
    """The segments as Granola sent them, serialised one way so the digest is stable."""
    return json.dumps(segments, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _label(speaker: object) -> str | None:
    """The source's own label for a speaker: the name, else the diarization label, else the
    attribution (`me`/`them`); None when Granola names nobody."""
    if not isinstance(speaker, dict):
        return None
    for key in ("name", "diarization_label", "attribution"):
        value = speaker.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _attendees(attendees: object) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(attendees, list):
        return out
    for a in attendees:
        if not isinstance(a, dict):
            continue
        person: dict[str, Any] = {}
        if isinstance(a.get("name"), str) and a["name"]:
            person["name"] = a["name"]
        if isinstance(a.get("email"), str) and a["email"]:
            person["email"] = a["email"]
        if person:
            out.append(person)
    return out


def _stamp(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return _stamp_of(value, None)
