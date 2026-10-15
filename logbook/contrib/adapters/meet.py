"""Google Meet → event/v1 (RFC 0009) and transcript/v1 (RFC 0004), live: the calls the owner was in, from
the Meet REST API v2's conference records.

`logbook sync meet` asks the Meet API (read-only scope `meetings.space.readonly`) as the owner, through the
service account the other Google sources share (`service_account`: LOGBOOK_DRIVE_SA_KEY, LOGBOOK_DRIVE_USER).

**What is asked.** The conference records the API lists for the owner that started from `since` on (the
filter `start_time>="…"`; all it keeps without one), a page of `PAGE_SIZE` at a time, retried with backoff
by the session; a page read is a progress line. For each conference that has ended and that the record does
not hold whole: its transcripts first, then, when there is a line to write, its participants, its space
(for the meeting code) and the entries of a transcript Google has finished (`FILE_GENERATED`). Nothing
else: no recording, no chat, no Smart Notes.

**One event per conference.** `at` the conference's start, `end` its end, `tz` the record's zone, tier 1
(RFC 0009: the owner's own time, as a calendar entry; the tier says where a line may travel, never who
wrote it). The Meet API keeps no title: a conference is titled by its meeting code, `Meet abc-mnop-xyz`,
or `Meet call` when the owner cannot read the space (someone else's meeting); the calendar entry it was
planned in is a line of its own, from `sync gcal`. `calendar` `{google-meet, Google Meet}`, `all_day`
false. The participants as the API gives them: a signed-in participant is a Google account, `users/<id>`,
which is an attendee `{ref: {kind: provider_id, value: users/<id>}, name}` (RFC 0009 rule 2: never
resolved here; `people review` sees them); under `extra.participants` every participant, signed-in,
anonymous (a display name) or phone (the number partly hidden, as Meet shows it), with when they first
joined. `extra.conference` is the record's resource name, the reference back; `extra.space` and
`extra.meeting_code` the space's.

**One transcript per conference, built as Granola's.** When Meet transcribed the call, its transcript is
one `transcript/v1` line through `transcript.draft`, the mapping the file adapter and `granola` share
(ADR 0017), at the tier they write (`transcript.TIER`, 3): `provider` and `source` `meet`, `raw_id`
`meet:<conference id>:transcript`, `at`/`end` the first entry's start and the last one's end (else the
transcript's own), `participants` every participant as `{name, provider_id}` (`provider_id` for a
signed-in one), then any speaker the participants do not cover, `language` the entries' most common
language, `source_uri` the transcript's Google Doc, `extra.conference` the record. `content` is the
entries as the API gave them, each with its speaker's display name beside the participant id (`speaker`,
which the readers' JSON turns read), serialised one way, stored once under their digest (SPEC §1.1),
never inline. A conference transcribed in several sittings is one line, its entries in order. A
transcript Google has not finished is counted (`transcript_pending`) and written by a later run.

**Why a Granola transcript of the same call is another line.** Granola and Meet each transcribed the call
on their own: different words, different speaker labels, different ids (`granola:<note id>`,
`meet:<conference id>:transcript`), different providers. RFC 0004 keeps what a source produced, one line
per transcript; that two transcripts are of one call is a judgement for a reader (the times overlap), not
for an adapter, and joining them would make one provider's words the other's.

**Dedupe by conference record id.** The event's `raw_id` is `meet:<conference id>` (the record id after
`conferenceRecords/`), the transcript's the same with `:transcript`. A conference is written once it has
ended (one still going on is counted, `held_ongoing`, and written by the run after it ends) and never
changes after, so its id alone is the snapshot. Before asking about a conference the pull asks the record
(`existing`) whether it holds both lines; a conference it holds is not asked about again
(`conference_in_record`), so a re-run asks only for the list and writes nothing.

**Watermark.** The conference's start, in whole seconds, carried by its event; a pull without `--since`
starts `LOOKBACK_H` before it, for a call that ended or a transcript Google finished after the last run."""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from ...core.attachments import reference
from ...core.transcripts import Turn, _stamp_of
from ...core.transcripts import participants as speakers_of
from . import service_account, transcript
from .service_account import Account, ApiError

__all__ = [
    "ENV",
    "KIND",
    "NAME",
    "SCOPE",
    "TIER",
    "TRANSCRIPT_TIER",
    "check",
    "configure",
    "pull",
    "resume",
    "watermark",
]

NAME = "meet"
ENV = service_account.ENV
KIND = "event"
TIER = 1  # RFC 0009, SPEC §4
SCHEMA = "event/v1"
TRANSCRIPT_TIER = transcript.TIER  # granola's: the same profile, the same tier
UNIT = "conferences"  # what `sync` counts in its progress lines
SCOPE = service_account.SCOPES["meet"]
API = "https://meet.googleapis.com/v2/"
RECORDS_URL = f"{API}conferenceRecords"
PAGE_SIZE = 100  # the API's largest page for conference records, transcripts and their entries
LOOKBACK_H = 24.0
CALENDAR = {"id": "google-meet", "name": "Google Meet"}
UNTITLED = "Meet call"
MEDIA_TYPE = "application/json"
GENERATED = "FILE_GENERATED"  # the transcript is final: Google has written its document

configure = service_account.configure
Existing = Callable[[Iterable[tuple[str, str]]], set[tuple[str, str]]]


def check(config: Account) -> str:
    """What `doctor` says after `configured`: the key read and loadable, no network asked."""
    return service_account.describe(config)


def resume(config: Account, mark: str) -> str:
    """Where a pull starts, given the watermark: a day before it."""
    return _z(_instant(mark) - timedelta(hours=LOOKBACK_H))


def watermark(draft: dict[str, Any]) -> str | None:
    """The conference's start in whole seconds, carried by its event; a transcript line carries none."""
    if draft["kind"] != KIND:
        return None
    return _z(_instant(str(draft["at"])))


def pull(
    config: Account,
    since: str | None = None,
    progress: Callable[[int, float], None] | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
    store: Callable[[bytes], object] | None = None,
    existing: Existing | None = None,
    wait_on_limits: bool = True,
) -> Iterator[dict[str, Any]]:
    """One event/v1 draft per conference that started from `since` on (RFC3339; None for all) and has
    ended, and one transcript/v1 draft per conference Meet transcribed, oldest first. `existing(keys)`
    says which (source, raw_id) keys the record holds, so a conference already written is not asked
    about again; `store` is called with a transcript's bytes just before its line. Skips and held calls
    are tallied in `counts`; `progress(conferences, elapsed)` after each page. Raises
    service_account.GoogleError (an OSError) when Google cannot be read; nothing is yielded before every
    conference is in."""
    counts = counts if counts is not None else {}
    session = service_account.Session(config, SCOPE, wait_on_limits)
    records = _records(session, since, progress)
    tz = timezone or "UTC"
    keys = {(NAME, key) for record in records if (rid := _id(record)) for key in _keys(rid)}
    held = existing(keys) if existing is not None and keys else set()
    spaces: dict[str, dict[str, Any] | None] = {}
    out: list[tuple[dict[str, Any], bytes | None]] = []
    for record in records:
        rid, start = _id(record), _stamp(record.get("startTime"))
        if not rid or start is None:
            _count(counts, "skipped_no_start")
            continue
        if _stamp(record.get("endTime")) is None:
            _count(counts, "held_ongoing")
            continue
        event_key, transcript_key = _keys(rid)
        want_event, want_transcript = (NAME, event_key) not in held, (NAME, transcript_key) not in held
        if not want_event and not want_transcript:
            _count(counts, "conference_in_record")
            continue
        name = str(record["name"])
        found = _all(session, f"{API}{name}/transcripts", "transcripts") if want_transcript else []
        ready = bool(found) and all(t.get("state") == GENERATED for t in found)
        if found and not ready:
            _count(counts, "transcript_pending")
        if not want_event and not ready:
            continue  # the call is written and nothing new is ready: nothing more to ask
        people = _all(session, f"{API}{name}/participants", "participants")
        space = _space(session, str(record.get("space") or ""), spaces)
        title = f"Meet {space['meetingCode']}" if space and space.get("meetingCode") else UNTITLED
        if want_event:
            out.append((_event(record, rid, start, people, space, title, tz), None))
        if ready:
            out.append(_transcript(session, record, rid, found, people, title))
    out.sort(key=lambda pair: (_instant(str(pair[0]["at"])), pair[0]["kind"] != KIND))
    for draft, data in out:
        if data is not None and store is not None:
            store(data)
        yield draft


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _keys(rid: str) -> tuple[str, str]:
    return f"{NAME}:{rid}", f"{NAME}:{rid}:transcript"


def _id(record: dict[str, Any]) -> str:
    """The record's id: its resource name after `conferenceRecords/`."""
    name = str(record.get("name") or "")
    return name.removeprefix("conferenceRecords/") if name.startswith("conferenceRecords/") else ""


def _records(
    session: service_account.Session, since: str | None, progress: Callable[[int, float], None] | None
) -> list[dict[str, Any]]:
    """Every conference record from `since` on, oldest first (the API lists the newest first)."""
    params = {"pageSize": str(PAGE_SIZE)}
    if since:
        params["filter"] = f'start_time>="{_z(_instant(since))}"'
    found: list[dict[str, Any]] = []
    started = time.monotonic()
    for page in _pages(session, RECORDS_URL, params, "conferenceRecords"):
        found.extend(page)
        if progress is not None:
            progress(len(found), time.monotonic() - started)
    return sorted(found, key=lambda r: (_instant_or_min(r.get("startTime")), str(r.get("name") or "")))


def _pages(
    session: service_account.Session, url: str, params: dict[str, str], key: str
) -> Iterator[list[dict[str, Any]]]:
    """Each page's items under `key` (absent on an empty page), following `nextPageToken`."""
    asked = dict(params)
    while True:
        page = session.get_json(url, asked)
        yield [x for x in page.get(key) or [] if isinstance(x, dict)]
        token = page.get("nextPageToken")
        if not isinstance(token, str) or not token:
            return
        asked = {**params, "pageToken": token}


def _all(session: service_account.Session, url: str, key: str) -> list[dict[str, Any]]:
    return [x for page in _pages(session, url, {"pageSize": str(PAGE_SIZE)}, key) for x in page]


def _space(
    session: service_account.Session, name: str, spaces: dict[str, dict[str, Any] | None]
) -> dict[str, Any] | None:
    """The space a conference was held in, asked once a run; None when the owner cannot read it."""
    if not name.startswith("spaces/"):
        return None
    if name not in spaces:
        try:
            spaces[name] = session.get_json(f"{API}{name}", {})
        except ApiError as e:
            if e.status not in (403, 404):
                raise
            spaces[name] = None
    return spaces[name]


def _participant(p: dict[str, Any]) -> dict[str, Any] | None:
    """A participant as `extra.participants` names it: what kind, the account or the display name, and
    when they first joined."""
    found: dict[str, Any]
    if isinstance(p.get("signedinUser"), dict):
        user = p["signedinUser"]
        found = {"kind": "signed-in", "user": str(user.get("user") or "")}
        if _text(user.get("displayName")):
            found["name"] = _text(user.get("displayName"))
    elif isinstance(p.get("anonymousUser"), dict):
        found = {"kind": "anonymous", "name": _text(p["anonymousUser"].get("displayName"))}
    elif isinstance(p.get("phoneUser"), dict):
        found = {"kind": "phone", "name": _text(p["phoneUser"].get("displayName"))}
    else:
        return None
    joined = _stamp(p.get("earliestStartTime"))
    if joined is not None:
        found["joined"] = joined
    return {k: v for k, v in found.items() if v}


def _event(
    record: dict[str, Any],
    rid: str,
    start: str,
    people: list[dict[str, Any]],
    space: dict[str, Any] | None,
    title: str,
    tz: str,
) -> dict[str, Any]:
    listed = [x for p in people if (x := _participant(p)) is not None]
    attendees = [
        {"ref": {"kind": "provider_id", "value": x["user"]}, **({"name": x["name"]} if x.get("name") else {})}
        for x in listed
        if x["kind"] == "signed-in" and x.get("user")
    ]
    extra: dict[str, Any] = {"conference": str(record["name"])}
    if record.get("space"):
        extra["space"] = str(record["space"])
    if space and space.get("meetingCode"):
        extra["meeting_code"] = str(space["meetingCode"])
    extra["participants"] = listed
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": _keys(rid)[0],
        "title": title,
        "calendar": dict(CALENDAR),
        "all_day": False,
    }
    if attendees:
        payload["attendees"] = attendees
    payload["extra"] = extra
    return {
        "at": start,
        "end": _stamp(record.get("endTime")),
        "tz": tz,
        "source": NAME,
        "kind": KIND,
        "tier": TIER,
        "payload": payload,
    }


def _transcript(
    session: service_account.Session,
    record: dict[str, Any],
    rid: str,
    found: list[dict[str, Any]],
    people: list[dict[str, Any]],
    title: str,
) -> tuple[dict[str, Any], bytes]:
    """The conference's transcript line, from its transcripts (every one finished), and the bytes to
    store."""
    name = str(record["name"])
    found = sorted(found, key=lambda t: (_instant_or_min(t.get("startTime")), str(t.get("name") or "")))
    names = {str(p.get("name")): _participant(p) for p in people}
    entries: list[dict[str, Any]] = []
    for t in found:
        for entry in _all(session, f"{API}{t['name']}/entries", "transcriptEntries"):
            who = names.get(str(entry.get("participant") or ""))
            if who is not None and who.get("name"):
                entry = {**entry, "speaker": {"name": who["name"]}}
            entries.append(entry)
    turns = [Turn(_speaker(e), str(e.get("text") or "")) for e in entries]
    starts = [s for e in entries if (s := _stamp(e.get("startTime")))]
    ends = [s for e in entries if (s := _stamp(e.get("endTime")))]
    at = min(starts, key=_instant) if starts else _stamp(found[0].get("startTime"))
    end = max(ends, key=_instant) if ends else _stamp(found[-1].get("endTime"))
    if at is None:
        at = _stamp(record.get("startTime"))
    data = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    named = [
        {"name": x["name"], **({"provider_id": x["user"]} if x.get("user") else {})}
        for p in people
        if (x := _participant(p)) is not None and x.get("name")
    ]
    languages = Counter(str(e["languageCode"]) for e in entries if e.get("languageCode"))
    docs = found[0].get("docsDestination")
    uri = docs.get("exportUri") if isinstance(docs, dict) else None
    line = transcript.draft(
        source=NAME,
        at=str(at),
        end=end,
        raw_id=_keys(rid)[1],
        content=reference(data, MEDIA_TYPE),
        turns=turns,
        tier=TRANSCRIPT_TIER,
        title=title,
        participants=speakers_of(turns, named),
        language=languages.most_common(1)[0][0] if languages else None,
        source_uri=str(uri) if isinstance(uri, str) and uri else None,
        extra={"conference": name},
    )
    return line, data


def _speaker(entry: dict[str, Any]) -> str | None:
    speaker = entry.get("speaker")
    return _text(speaker.get("name")) if isinstance(speaker, dict) else None


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return " ".join(value.split()) or None


def _stamp(value: object) -> str | None:
    """An API time as RFC3339 UTC, milliseconds kept when it has them; None when it is none."""
    if not isinstance(value, str) or not value.strip():
        return None
    return _stamp_of(value, None)


def _instant(text: str) -> datetime:
    when = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC)


def _instant_or_min(value: object) -> datetime:
    try:
        return (
            _instant(str(value))
            if isinstance(value, str) and value.strip()
            else datetime.min.replace(tzinfo=UTC)
        )
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)


def _z(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
