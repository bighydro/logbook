"""Google Calendar → event/v1 (RFC 0009), live: the calendars you own, over the Calendar API on the one
Google service-account key, else from their private iCal feeds.

**On the service account.** When `LOGBOOK_DRIVE_SA_KEY` and `LOGBOOK_DRIVE_USER` are set (`service_account`,
the key every Google source shares), `pull` reads the Calendar API v3 as that user, read-only
(`calendar.readonly`), and `LOGBOOK_GCAL_URLS` is not read: the calendars the user owns
(`calendarList`, `minAccessRole=owner`; the primary first, then by name; a calendar shared with the user
or subscribed to, such as a holidays calendar, is not theirs and is not read), each one's events as
stored (`singleEvents=false`: a master with its rule, an exception with its original start, never the
occurrences expanded; `showDeleted=true`, so the first run and the incremental ones, which Google answers
with the deleted events whatever is asked, see the same set) changed since `since` (`updatedMin`), page by
page, retried with backoff by the session. Each event becomes the VEVENT its iCal feed carries — `UID` the
`iCalUID`, `LAST-MODIFIED` the `updated` time cut to the second, `DTSTART`/`DTEND`/`RECURRENCE-ID` in the
event's own zone (`TZID`) or in UTC when it names none, a whole day as a `DATE`, `SUMMARY`, `DESCRIPTION`,
`LOCATION`, `STATUS`, `ORGANIZER` and `ATTENDEE` (name, response, role) as `mailto:` values, the
`recurrence` lines as the API gives them — under a VCALENDAR named by the calendar's summary
(`X-WR-CALNAME`), and goes through `ics.components_lines`: one code path for the line, so an event pulled
here and the same event from the feed or an export are the same line, the same `raw_id`
(`<UID>@<LAST-MODIFIED>`) and the same `source`, `ics`. What the API has no field for is not on the line:
GEO's coordinates, an attendee's DELEGATED. A deleted event Google returns with nothing but its id and
status is counted (`skipped_deleted`), not written; one with its times is a `cancelled` line, as a feed
writes it. An `updatedMin` Google says is too long ago (410, `updatedMinTooLongAgo`) is read as the whole
calendar, filtered here on the change time. The watermark is the same clock as the feeds' (`updated` is
the feed's LAST-MODIFIED), so a record that synced the feeds carries on from their watermark when the two
variables are set, less the lookback, and writes nothing twice (the migration note is in the tour).

**From the feeds.** Google gives every calendar a "secret address in iCal format" (Settings → the
calendar → Integrate calendar): a URL that is the whole calendar as one iCalendar text, readable by
anyone who holds it. `LOGBOOK_GCAL_URLS` lists them, comma-separated, each optionally `name=url` so a
feed with no X-WR-CALNAME of its own is named. Fetched with stdlib urllib, no dependency, no network
anywhere but inside `pull`, which only `logbook sync gcal` calls (ADR 0012).

Every feed goes through `ics.lines`, the file adapter's own reader: an event imported from a calendar
export (`logbook add basic.ics`, Takeout's `Calendar/`) and the same event pulled here are the same
line with the same `raw_id` (`<UID>@<LAST-MODIFIED>`, RFC 0009 rule 5) and the same `source`, `ics`,
so `append_many` dedupes it (ADR 0017: backfill and live share one mapping). Recurring masters,
materialised occurrences, all-day and floating times (read in the record's zone, which `sync` passes
as `timezone`) are the ics adapter's, unchanged. The feed's own X-WR-CALNAME names the calendar as it
does for a file; the given name applies only when the feed has none, where a saved copy would have
used its file name (`basic.ics`, the URL's last part, when no name was given either).

The watermark is the newest LAST-MODIFIED (else DTSTAMP) seen. A feed is the whole calendar every
time, so each pull keeps only the events changed since a lookback (24 h, `LOGBOOK_GCAL_LOOKBACK_H`)
before the watermark, and the `raw_id` dedupe absorbs the overlap; `sync` says how many it saw and
how many were new, per calendar. With no watermark yet the whole feed is read (the record's newest
event is a start time, not a change time, so it cannot stand in). An explicit `--since` is used as
given. An event with neither stamp is always considered; dedupe still keeps it single.

The URLs are secrets: the config's repr hides them, `sync` prints only a calendar's label (its given
name, else eight hex characters of the URL's SHA-256) and an error is composed from the HTTP status or
the reason alone, with the URL scrubbed should a library put it there. A calendar that fails (an HTTP
error, an unreachable host, a body that is not a calendar) is one line in `failed` and the others are
still read; without a `failed` list the pull raises OSError with those lines after the others' events.
"""

from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from . import ics, service_account
from .ics import KIND
from .service_account import Account

__all__ = [
    "ENV",
    "KIND",
    "NAME",
    "SCOPE",
    "Calendar",
    "Config",
    "check",
    "configure",
    "group",
    "needs",
    "pull",
    "resume",
    "watermark",
]

NAME = "gcal"
URLS_ENV = "LOGBOOK_GCAL_URLS"
LOOKBACK_ENV = "LOGBOOK_GCAL_LOOKBACK_H"
ENV = (URLS_ENV, *service_account.ENV)  # the feeds, or the service account; either is enough
SCOPE = service_account.SCOPES["gcal"]
API = "https://www.googleapis.com/calendar/v3"
PAGE_SIZE = 250  # calendars and events per page; the API's own default for events
PARTSTAT = {
    "accepted": "ACCEPTED",
    "declined": "DECLINED",
    "tentative": "TENTATIVE",
    "needsAction": "NEEDS-ACTION",
}
RECURRENCE = frozenset({"RRULE", "EXRULE", "RDATE", "EXDATE"})
TOO_LONG_AGO = "updatedMinTooLongAgo"
LOOKBACK_H = 24.0
UNIT = "events"  # what `sync` counts in its progress lines
TIMEOUT_S = 60
SCHEMES = ("http", "https")
LABEL_CHARS = 8
USER_AGENT = "logbook"
NOT_A_FEED = "not an iCalendar feed"


@dataclass(frozen=True)
class Calendar:
    """One feed: what `sync` may print (`label`), the URL it never prints, the name it was given."""

    label: str
    url: str = field(repr=False)
    name: str | None = None

    @property
    def fallback_name(self) -> str:
        """The calendar id when the feed carries no X-WR-CALNAME: the given name, else the URL's last
        path part, which is what a saved copy of the feed would be called."""
        if self.name:
            return self.name
        return urlsplit(self.url).path.rsplit("/", 1)[-1] or self.label


@dataclass(frozen=True)
class Config:
    calendars: tuple[Calendar, ...]
    lookback_h: float = LOOKBACK_H
    account: Account | None = field(default=None, repr=False)  # set: the Calendar API, not the feeds


def configure(env: Mapping[str, str]) -> Config | None:
    """The service account when LOGBOOK_DRIVE_SA_KEY and LOGBOOK_DRIVE_USER are both set (the feeds are
    then not read), else the feeds of LOGBOOK_GCAL_URLS; None when neither is there. Raises ValueError,
    never echoing a value, when the key or the user is refused (`service_account.configure`), an entry
    is not an http(s) URL or LOGBOOK_GCAL_LOOKBACK_H is set but not a number of hours ≥ 0."""
    lookback = _lookback(env)
    account = service_account.configure(env)
    if account is not None:
        return Config(calendars=(), lookback_h=lookback, account=account)
    calendars: list[Calendar] = []
    for position, item in enumerate(env.get(URLS_ENV, "").split(","), start=1):
        item = item.strip()
        if not item:
            continue
        name, url = _pair(item)
        parts = urlsplit(url)
        if parts.scheme.lower() not in SCHEMES or not parts.netloc:
            raise ValueError(f"{URLS_ENV}: entry {position} is not an http(s) URL")
        calendars.append(Calendar(label=name or _label(url), url=url, name=name))
    if not calendars:
        return None
    return Config(calendars=tuple(calendars), lookback_h=lookback)


def _lookback(env: Mapping[str, str]) -> float:
    raw = env.get(LOOKBACK_ENV, "").strip()
    lookback = LOOKBACK_H
    if raw:
        try:
            lookback = float(raw)
        except ValueError:
            lookback = -1.0
        if not math.isfinite(lookback) or lookback < 0:
            raise ValueError(f"{LOOKBACK_ENV} must be a number of hours, 0 or more, not {raw!r}")
    return lookback


def needs(env: Mapping[str, str]) -> str:
    """What to set before a run, in words, for `sync` and `doctor`: either way in will do."""
    half = [v for v in service_account.ENV if not env.get(v, "").strip()]
    if len(half) == 1:
        return f"{half[0]} (or {URLS_ENV} for the iCal feeds)"
    return f"{URLS_ENV}, or {' and '.join(service_account.ENV)}"


def check(config: Config) -> str:
    """What `doctor` says after `configured`, asking no one: the service account's key read and loadable,
    or how many feeds there are."""
    if config.account is not None:
        return (
            f"the calendars the user owns, on the service account; {service_account.describe(config.account)}"
        )
    n = len(config.calendars)
    return f"{n} iCal feed{'' if n == 1 else 's'}"


def _pair(item: str) -> tuple[str | None, str]:
    """`name=url` when there is an `=` before anything that could only be part of a URL (`:` or `/`);
    else the item is the URL."""
    name, sep, url = item.partition("=")
    if sep and name and ":" not in name and "/" not in name:
        return name.strip(), url.strip()
    return None, item


def _label(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:LABEL_CHARS]


def resume(config: Config, mark: str) -> str:
    """Where a pull starts, given the watermark: the lookback before it."""
    start = datetime.fromisoformat(mark).astimezone(UTC) - timedelta(hours=config.lookback_h)
    return start.strftime("%Y-%m-%dT%H:%M:%SZ")


def watermark(draft: dict[str, Any]) -> str | None:
    """The event's LAST-MODIFIED (else DTSTAMP): the calendar's own clock for it."""
    modified = draft["payload"].get("modified_at")
    return str(modified) if modified else None


def group(draft: dict[str, Any]) -> str:
    """The calendar the event belongs to, as `sync` reports seen and new per calendar."""
    calendar = draft["payload"]["calendar"]
    return str(calendar.get("name") or calendar["id"])


def pull(
    config: Config,
    since: str | None = None,
    progress: Callable[[int, float], None] | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
    failed: list[str] | None = None,
) -> Iterator[dict[str, Any]]:
    """Every event of every calendar changed since `since` (RFC3339; None means all), calendar by
    calendar (the order configured, or the primary first and then by name on the service account) and
    in the source's order within one, one event/v1 line draft each, through the ics reader whichever
    way the calendar was read. Every calendar is read before the first line is yielded. Skips are
    tallied in `counts` as the ics adapter tallies them; `progress(events_so_far, elapsed_seconds)` is
    called after each calendar. A calendar that cannot be read is one line in `failed` (its label and
    the reason, never a URL); with no list given, OSError carries those lines once every other
    calendar's events are out. On the service account, a failure before any calendar is read (the
    token, the calendar list) is raised as it comes."""
    counts = counts if counts is not None else {}
    cutoff = _cutoff(since)
    started = time.monotonic()
    problems: list[str] = []
    read = (
        _from_account(config.account, since, counts, problems)
        if config.account is not None
        else _from_feeds(config, problems)
    )
    count = 0
    for fallback, given, roots in read:
        for draft in ics.components_lines(roots, fallback, counts, timezone):
            modified = draft["payload"].get("modified_at")
            if cutoff is not None and modified and str(modified) < cutoff:
                continue
            if given and "name" not in draft["payload"]["calendar"]:  # a feed with no name of its own
                draft["payload"]["calendar"]["name"] = given
            count += 1
            yield draft
        if progress is not None:
            progress(count, time.monotonic() - started)
    if problems:
        if failed is None:
            raise OSError("; ".join(problems))
        failed.extend(problems)


Read = list[tuple[str, str | None, list[ics.Component]]]  # per calendar: fallback id, given name, components


def _from_feeds(config: Config, problems: list[str]) -> Read:
    """Each feed fetched and parsed, in the order configured; a feed that fails is a line in `problems`."""
    read: Read = []
    for calendar in config.calendars:
        try:
            text = _fetch(calendar)
        except OSError as e:
            problems.append(f"{calendar.label}: {_scrub(str(e), calendar)}")
            continue
        read.append((calendar.fallback_name, calendar.name, ics.parse(text)))
    return read


# -- the Calendar API, on the service account ----------------------------------------------------------


def _from_account(account: Account, since: str | None, counts: dict[str, int], problems: list[str]) -> Read:
    """Each calendar the user owns as one VCALENDAR of the VEVENTs its feed would carry; a calendar
    whose events cannot be read is a line in `problems` and the others are still read."""
    session = service_account.Session(account, SCOPE)
    read: Read = []
    for calendar in _owned(session):
        calendar_id = str(calendar["id"])
        label = _clean(calendar.get("summary")) or calendar_id
        try:
            events = _events(session, calendar_id, since)
        except service_account.ApiError as e:
            problems.append(f"{label}: {e}")
            continue
        root = ics.Component("VCALENDAR")
        if summary := _clean(calendar.get("summary")):
            root.properties.append(ics.Property("X-WR-CALNAME", {}, _escape(summary)))
        for event in events:
            vevent = _vevent(event)
            if vevent is None:
                counts["skipped_deleted"] = counts.get("skipped_deleted", 0) + 1
                continue
            root.children.append(vevent)
        read.append((calendar_id, None, [root]))
    return read


def _owned(session: service_account.Session) -> list[dict[str, Any]]:
    """The calendars the user owns, every page: the primary first, then by name."""
    found = _pages(session, f"{API}/users/me/calendarList", {"minAccessRole": "owner"})
    owned = [c for c in found if c.get("id") and c.get("accessRole", "owner") == "owner"]
    return sorted(
        owned, key=lambda c: (not c.get("primary"), _clean(c.get("summary")).casefold(), str(c["id"]))
    )


def _events(session: service_account.Session, calendar_id: str, since: str | None) -> list[dict[str, Any]]:
    """Every event of the calendar as stored, deleted ones included, changed since `since`; the whole
    calendar when Google says `since` is too long ago (the cutoff is then `pull`'s)."""
    url = f"{API}/calendars/{quote(calendar_id, safe='')}/events"
    params = {"singleEvents": "false", "showDeleted": "true"}
    if since:
        try:
            return _pages(session, url, {**params, "updatedMin": _cutoff(since) or since})
        except service_account.ApiError as e:
            if e.status != 410 or TOO_LONG_AGO not in e.reasons:
                raise
    return _pages(session, url, params)


def _pages(session: service_account.Session, url: str, params: Mapping[str, str]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        query = {**params, "maxResults": str(PAGE_SIZE)}
        if token is not None:
            query["pageToken"] = token
        page = session.get_json(url, query)
        found.extend(item for item in page.get("items") or [] if isinstance(item, dict))
        next_token = page.get("nextPageToken")
        if not isinstance(next_token, str) or not next_token:
            return found
        token = next_token


def _vevent(event: dict[str, Any]) -> ics.Component | None:
    """The VEVENT the calendar's iCal feed carries for this event; None for a deleted one that has
    nothing left but its id."""
    start = event.get("start")
    timed = isinstance(start, dict) and bool(start.get("date") or start.get("dateTime"))
    if not timed and event.get("status") == "cancelled":
        return None
    zone = str(start.get("timeZone") or "") if isinstance(start, dict) else ""
    vevent = ics.Component("VEVENT")
    add = vevent.properties.append
    uid = _clean(event.get("iCalUID")) or (f"{event['id']}@google.com" if event.get("id") else "")
    if uid:
        add(ics.Property("UID", {}, _escape(uid)))
    if stamp := _utc_text(event.get("updated")):
        add(ics.Property("LAST-MODIFIED", {}, stamp))
    for name, key in (("DTSTART", "start"), ("DTEND", "end"), ("RECURRENCE-ID", "originalStartTime")):
        prop = _time(name, event.get(key), zone)
        if prop is not None:
            add(prop)
    for name, key in (("SUMMARY", "summary"), ("DESCRIPTION", "description"), ("LOCATION", "location")):
        if isinstance(event.get(key), str) and event[key].strip():
            add(ics.Property(name, {}, _escape(event[key])))
    if isinstance(event.get("status"), str) and event["status"]:
        add(ics.Property("STATUS", {}, event["status"].upper()))
    organizer = event.get("organizer")
    if isinstance(organizer, dict) and organizer.get("email"):
        add(ics.Property("ORGANIZER", _cn(organizer), f"mailto:{organizer['email']}"))
    for attendee in event.get("attendees") or []:
        if not isinstance(attendee, dict) or not attendee.get("email"):
            continue
        params = _cn(attendee)
        status = str(attendee.get("responseStatus") or "")
        if status:
            params["PARTSTAT"] = [PARTSTAT.get(status, status.upper())]
        params["ROLE"] = ["OPT-PARTICIPANT" if attendee.get("optional") else "REQ-PARTICIPANT"]
        if attendee.get("resource"):
            params["CUTYPE"] = ["RESOURCE"]
        add(ics.Property("ATTENDEE", params, f"mailto:{attendee['email']}"))
    for line in event.get("recurrence") or []:
        prop = ics.content_line(str(line))
        if prop is not None and prop.name in RECURRENCE:
            add(prop)
    return vevent


def _time(name: str, value: Any, zone: str) -> ics.Property | None:
    """A start, end or original start as the feed spells it: a whole day as `VALUE=DATE`; a time in the
    zone the API names for it (else the event's start's) as `TZID=<zone>` wall-clock; in UTC with `Z`
    when it names none, or one the zone database does not know."""
    if not isinstance(value, dict):
        return None
    if isinstance(value.get("date"), str) and value["date"]:
        return ics.Property(name, {"VALUE": ["DATE"]}, value["date"].replace("-", ""))
    if not isinstance(value.get("dateTime"), str) or not value["dateTime"]:
        return None
    try:
        when = datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    named = str(value.get("timeZone") or zone or "")
    try:
        local = when.astimezone(ZoneInfo(named)) if named else None
    except (KeyError, ValueError, OSError):  # ZoneInfoNotFoundError is a KeyError
        local = None
    if local is None:
        return ics.Property(name, {}, when.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ"))
    return ics.Property(name, {"TZID": [named]}, local.strftime("%Y%m%dT%H%M%S"))


def _utc_text(value: Any) -> str | None:
    """`2026-03-10T08:00:00.123Z` as `20260310T080000Z`: the API's change time as the feed's LAST-MODIFIED."""
    if not isinstance(value, str) or not value:
        return None
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _cn(person: dict[str, Any]) -> dict[str, list[str]]:
    name = _clean(person.get("displayName"))
    return {"CN": [name]} if name else {}


def _clean(value: Any) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _escape(text: str) -> str:
    """TEXT as RFC 5545 escapes it, so the reader's unescaping gives the text back."""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\n")
        .replace("\n", "\\n")
    )


# -- the feeds --------------------------------------------------------------------------------------------


def _cutoff(since: str | None) -> str | None:
    """`since` as the RFC3339 UTC text a `modified_at` compares with, whatever offset it was given in."""
    if not since:
        return None
    return datetime.fromisoformat(since).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fetch(calendar: Calendar) -> str:
    """The feed's text. The only network call in this module. Raises OSError, its message free of the
    URL, for an HTTP error, an unreachable server or a body that is not a calendar."""
    req = Request(calendar.url, headers={"User-Agent": USER_AGENT, "Accept": "text/calendar"}, method="GET")
    try:
        with urlopen(req, timeout=TIMEOUT_S) as response:
            body = response.read()
    except HTTPError as e:
        raise OSError(f"HTTP {e.code} {e.reason}") from None
    except URLError as e:
        raise OSError(str(e.reason)) from None
    if not ics.sniff_bytes(body):
        raise OSError(NOT_A_FEED)
    text: str = body.decode("utf-8-sig", errors="replace")
    return text


def _scrub(message: str, calendar: Calendar) -> str:
    """The message with the URL, and its secret path on its own, replaced: belt and braces for a
    library error that quotes what it was asked to open."""
    for secret in (calendar.url, urlsplit(calendar.url).path):
        if secret and secret != "/":
            message = message.replace(secret, "<url>")
    return message
