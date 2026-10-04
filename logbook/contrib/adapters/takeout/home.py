"""Google Takeout Home App/ → event/v1 (RFC 0009): who came home, who left, and the alarm.

Takeout's `Home App/` folder holds `HomeHistory.json`, the Google Home app's history of what the
home's devices saw, beside folders this adapter never opens: `SoundSensing/` (the sounds a speaker
or display heard, with their recordings) and `SecurityAlarmClips/` (the camera clips an alarm
kept). The history is one array of events; Google has moved its keys between exports, so the reader
finds what it needs by what a key says rather than its exact name — the time under `timestamp`,
`time`, `eventTime`, `createdTime` or `timestampMs` (an epoch in milliseconds), the kind under
`eventType`, `type`, `event` or `activityType`, the home under `structureName`, `structure` or
`home`, the device under `deviceName` or `device`, the words under `description`, `summary`,
`message` or `title`, the alarm level under `alarmLevel`, `level` or `securityLevel` — and the
event's own `eventId` or `id` when it has one.

What is a line is the household's presence: an **arrival** (a member's phone came home), a
**departure** (it left), the alarm **armed** (to home or away) and **disarmed**. These are the
evidence of a night at home that the Day looks for (SPEC §3.2.3 rule 5: an `event/v1` line inside
a short cluster at home promotes it to a stay, and rule 8 then makes that stay the night). One
`event/v1` line each, tier 1 (the owner's own home): `at` the event's instant, `end` null, `title`
`Arrived home`, `Left home` (the home's name when it is not called Home), `Alarm armed (away)` or
`Alarm disarmed`, `calendar` `{google-home, Google Home}`, `location` the home's name; under `extra`
the `activity` (`arrival`, `departure`, `alarm_armed`, `alarm_disarmed`), the export's `event_type`,
the `structure`, the `device`, the alarm `level`, the household `member` the words name (`Ines
arrived home`) and the `description` verbatim. `raw_id` is `home:<event id>`, else
`home:<time as spelled>:<sha256(type, description)[:16]>`.

A sound event (`skipped_sound_sensing`) and an alarm clip (`skipped_security_alarm_clips`) are
counted, never lines, by their type or by what they carry; so is any other event (a device added,
a routine run: `skipped_other_activity`) and one with no time. Pure: no network, never writes the
source, never opens a recording or a clip.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from . import SOURCE, times

NAME = "google-takeout-home"
KIND = "event"
TIER = 1
SCHEMA = "event/v1"
FOLDER = "Home App"
FILE = "HomeHistory.json"
CALENDAR = {"id": "google-home", "name": "Google Home"}

SUFFIX = ".json"
IGNORED_FOLDERS = ("SoundSensing", "SecurityAlarmClips")
TIME_KEYS = ("timestamp", "time", "eventTime", "createdTime", "timestampMs", "timestamp_ms")
TYPE_KEYS = ("eventType", "type", "event", "activityType", "event_type")
STRUCTURE_KEYS = ("structureName", "structure", "home", "homeName", "structure_name")
DEVICE_KEYS = ("deviceName", "device", "device_name", "deviceId")
TEXT_KEYS = ("description", "summary", "message", "title")
LEVEL_KEYS = ("alarmLevel", "level", "securityLevel", "alarm_level")
ID_KEYS = ("eventId", "id", "event_id")
SOUND = re.compile(r"sound", re.IGNORECASE)
CLIP = re.compile(r"clip", re.IGNORECASE)
DISARMED = re.compile(r"disarm", re.IGNORECASE)
ARMED = re.compile(r"\barm(ed|ing)?\b|_ARMED\b|security_level|alarm_level", re.IGNORECASE)
ARRIVAL = re.compile(r"arriv|came home|\bhome\b.*(arrived|presence)|ARRIVED|PRESENCE_HOME", re.IGNORECASE)
DEPARTURE = re.compile(r"\bleft\b|depart|went away|PRESENCE_AWAY", re.IGNORECASE)
MEMBER = re.compile(r"^(?P<who>[^,.:]+?)\s+(?:arrived|left|came|departed|went)\b", re.IGNORECASE)
MEMBER_BY = re.compile(r"\bby\s+(?P<who>[^,.:]+?)\s*$", re.IGNORECASE)
NOBODY = ("alarm", "the alarm", "security", "schedule", "routine", "a routine", "the app")
LEVEL_AWAY = re.compile(r"away", re.IGNORECASE)
LEVEL_HOME = re.compile(r"home", re.IGNORECASE)
DEFAULT_HOME = "Home"


def sniff(path: Path) -> bool:
    """`HomeHistory.json` with at least one timed event, or a folder holding it. Never raises."""
    path = Path(path)
    try:
        if path.is_dir():
            return _is_history(path / FILE)
        return _is_history(path)
    except OSError:
        return False


def _is_history(path: Path) -> bool:
    if not path.is_file() or path.name != FILE:
        return False
    events = _events(path)
    return any(
        _first(e, TIME_KEYS) is not None and _first(e, TYPE_KEYS + TEXT_KEYS) is not None for e in events
    )


def _events(path: Path) -> list[dict[str, Any]]:
    """The history's events: the top-level array, or the first array of objects under the top-level
    object (an export that wraps them under `events` or `homeHistory`)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(data, dict):
        data = next(
            (v for v in data.values() if isinstance(v, list) and any(isinstance(x, dict) for x in v)), []
        )
    if not isinstance(data, list):
        return []
    return [e for e in data if isinstance(e, dict)]


def _first(event: dict[str, Any], keys: Sequence[str]) -> object:
    for key in keys:
        value = event.get(key)
        if value is not None and value != "":
            return value
    return None


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
) -> Iterator[dict[str, Any]]:
    """One event/v1 line draft per arrival, departure and alarm change in `path` (`HomeHistory.json`
    or the `Home App/` folder), oldest first. `since` is RFC3339 UTC; `timezone` the record's zone."""
    counts = counts if counts is not None else {}
    path = Path(path)
    file = path / FILE if path.is_dir() else path
    tz = timezone or "UTC"
    drafts: list[dict[str, Any]] = []
    for event in _events(file) if _is_history(file) else []:
        draft = _draft(event, tz, counts)
        if draft is not None and (since is None or draft["at"] >= since):
            drafts.append(draft)
    yield from sorted(drafts, key=lambda d: (d["at"], d["payload"]["raw_id"]))


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _draft(event: dict[str, Any], tz: str, counts: dict[str, int]) -> dict[str, Any] | None:
    event_type = _text(_first(event, TYPE_KEYS))
    description = _text(_first(event, TEXT_KEYS))
    words = f"{event_type} {description}"
    if SOUND.search(event_type) or (not event_type and SOUND.search(description)):
        _count(counts, "skipped_sound_sensing")
        return None
    if CLIP.search(event_type) or any(CLIP.search(str(k)) for k in event):
        _count(counts, "skipped_security_alarm_clips")
        return None
    activity = _activity(event_type, description)
    if activity is None:
        _count(counts, "skipped_other_activity")
        return None
    at, spelled = _instant(_first(event, TIME_KEYS))
    if at is None:
        _count(counts, "skipped_no_timestamp")
        return None
    structure = _text(_first(event, STRUCTURE_KEYS))
    level = _level(_text(_first(event, LEVEL_KEYS)) or words) if activity == "alarm_armed" else None
    event_id = _text(_first(event, ID_KEYS))
    raw_id = (
        f"home:{event_id}"
        if event_id
        else f"home:{spelled}:{hashlib.sha256(words.encode('utf-8')).hexdigest()[:16]}"
    )
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": raw_id,
        "title": _title(activity, structure, level),
        "calendar": dict(CALENDAR),
        "all_day": False,
    }
    if structure:
        payload["location"] = structure
    extra: dict[str, Any] = {"activity": activity}
    if event_type:
        extra["event_type"] = event_type
    if structure:
        extra["structure"] = structure
    device = _text(_first(event, DEVICE_KEYS))
    if device:
        extra["device"] = device
    if level:
        extra["level"] = level
    member = MEMBER.match(description) or MEMBER_BY.search(description)
    if member and member.group("who").casefold() not in NOBODY:
        extra["member"] = member.group("who")
    if description:
        extra["description"] = description
    payload["extra"] = extra
    return {"at": at, "end": None, "tz": tz, "source": SOURCE, "kind": KIND, "tier": TIER, "payload": payload}


def _activity(event_type: str, description: str) -> str | None:
    """`arrival`, `departure`, `alarm_armed`, `alarm_disarmed`, or None for anything else: the type
    says first, the words when the type is not specific."""
    for text in (event_type, description):
        if not text:
            continue
        if DISARMED.search(text):
            return "alarm_disarmed"
        if ARMED.search(text):
            return "alarm_armed"
        if ARRIVAL.search(text):
            return "arrival"
        if DEPARTURE.search(text):
            return "departure"
    return None


def _level(text: str) -> str | None:
    if LEVEL_AWAY.search(text):
        return "away"
    if LEVEL_HOME.search(text):
        return "home"
    return None


def _title(activity: str, structure: str, level: str | None) -> str:
    where = structure if structure and structure.casefold() != DEFAULT_HOME.casefold() else "home"
    if activity == "arrival":
        return f"Arrived {where}"
    if activity == "departure":
        return f"Left {where}"
    if activity == "alarm_armed":
        return f"Alarm armed ({level})" if level else "Alarm armed"
    return "Alarm disarmed"


def _text(value: object) -> str:
    return (
        " ".join(str(value).split())
        if isinstance(value, str | int | float) and not isinstance(value, bool)
        else ""
    )


def _instant(value: object) -> tuple[str | None, str]:
    """(`at` to the second in UTC, the time as the export spells it): RFC 3339, or an epoch in
    milliseconds (a number, or digits in a string) — or (None, "")."""
    if isinstance(value, bool):
        return None, ""
    if isinstance(value, int | float) or (isinstance(value, str) and value.strip().isdigit()):
        from datetime import UTC, datetime

        millis = int(float(value))
        if millis <= 0:
            return None, ""
        when = datetime.fromtimestamp(millis / 1000, UTC)
        return when.strftime("%Y-%m-%dT%H:%M:%SZ"), str(value).strip()
    return times.parse(value)
