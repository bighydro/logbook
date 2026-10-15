"""Google Workspace sign-ins → event/v1 (RFC 0009), live: the owner's own sign-ins from the Workspace's login
audit log, through the Admin SDK Reports API v1.

`logbook sync gaudit` asks the Reports API (read-only scope `admin.reports.audit.readonly`) for the
activities of the `login` application of one user, the owner (the address the key reads as), never the
other users of the Workspace, from `since` on (`startTime`), a page of `PAGE_SIZE` at a time, retried with
backoff by the session; a page read is a progress line. The Reports API answers only an administrator of
the Workspace, which the owner of his own Workspace is.

**One line per login event.** An activity holds one event or more (a challenge and the sign-in it let
through, at one instant); each is a line: `at` the activity's time, `end` null, `tz` the record's zone,
tier 1 (RFC 0009; the tier says where a line may travel, never who wrote it). `title` says what happened —
`Signed in`, `Sign-in failed`, `Signed out`, `Sign-in challenge`, `Sign-in verification`, `Suspicious
sign-in` — else the event's own name; `calendar` `{google-sign-in, Google sign-ins}`, `all_day` false.
Under `extra`: `app`, the application the log is of (`login`), `event`, the event's name as Google spells
it, the place Google derived from the address (below), and the parameters on the list `KEPT` and no
other: how the owner signed in (`login_type`), the challenges asked and how they went, why a sign-in
failed, and whether Google thought it suspicious.

**Never the raw address.** The activity's `ipAddress` is never in a line: not in the payload, not in the
`raw_id`, not digested into either, since a digest of an IPv4 address protects nothing (there are 2³²
of them, hashed through in minutes). Neither is the network it came through (`networkInfo.ipAsn`) or any
parameter not on the list, some of which carry addresses. What a line may say of where is what Google
derived from the address, when the answer names it: the country (`networkInfo.regionCode`), the
subdivision (`subdivisionCode`) and the city (`city`, which not every answer carries), under `extra` and
as `location` text, `Oslo, NO-03, NO`; coarse, never a coordinate.

**Dedupe.** `raw_id` is `login:<time as spelled>:<uniqueQualifier>:<event name>`, the activity's own id
and the event (`:<n>` after it when an activity names one event twice). The record's dedupe on `(source,
raw_id)` makes a re-run, and the lookback, write nothing twice.

**Watermark.** The sign-in's time, in whole seconds; a pull without `--since` starts `LOOKBACK_H` before
it, since Google can add a sign-in to the log hours after it happened."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from ...core.transcripts import _stamp_of
from . import service_account
from .service_account import Account

__all__ = [
    "ENV",
    "KIND",
    "NAME",
    "SCOPE",
    "TIER",
    "check",
    "configure",
    "group",
    "pull",
    "resume",
    "watermark",
]

NAME = "gaudit"
ENV = service_account.ENV
KIND = "event"
TIER = 1  # RFC 0009, SPEC §4
SCHEMA = "event/v1"
UNIT = "sign-ins"  # what `sync` counts in its progress lines
SCOPE = service_account.SCOPES["gaudit"]
APPLICATION = "login"
LOG_URL = "https://admin.googleapis.com/admin/reports/v1/activity/users/{user}/applications/" + APPLICATION
PAGE_SIZE = 1000  # the API's largest page
LOOKBACK_H = 24.0
CALENDAR = {"id": "google-sign-in", "name": "Google sign-ins"}
TITLES = {
    "login_success": "Signed in",
    "login_failure": "Sign-in failed",
    "logout": "Signed out",
    "login_challenge": "Sign-in challenge",
    "login_verification": "Sign-in verification",
    "suspicious_login": "Suspicious sign-in",
    "suspicious_login_less_secure_app": "Suspicious sign-in",
    "suspicious_programmatic_login": "Suspicious sign-in",
}
KEPT = (  # the parameters a line keeps; any other, some of which carry addresses, is never written
    "login_type",
    "login_challenge_method",
    "login_challenge_status",
    "login_failure_type",
    "is_second_factor",
    "is_suspicious",
)

configure = service_account.configure


def check(config: Account) -> str:
    """What `doctor` says after `configured`: the key read and loadable, no network asked."""
    return service_account.describe(config)


def resume(config: Account, mark: str) -> str:
    """Where a pull starts, given the watermark: a day before it, for a sign-in Google logs late."""
    return _z(_instant(mark) - timedelta(hours=LOOKBACK_H))


def watermark(draft: dict[str, Any]) -> str | None:
    """The sign-in's time, in whole seconds."""
    return _z(_instant(str(draft["at"])))


def group(draft: dict[str, Any]) -> str:
    """What happened, so `sync` says seen and new per kind of sign-in."""
    return str(draft["payload"]["title"])


def pull(
    config: Account,
    since: str | None = None,
    progress: Callable[[int, float], None] | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
    wait_on_limits: bool = True,
) -> Iterator[dict[str, Any]]:
    """One event/v1 draft per login event of the owner's from `since` on (RFC3339; None for all the log
    keeps), oldest first. Skips are tallied in `counts`; `progress(activities, elapsed)` after each page.
    Raises service_account.GoogleError (an OSError) when Google cannot be read; nothing is yielded before
    every page is in."""
    counts = counts if counts is not None else {}
    session = service_account.Session(config, SCOPE, wait_on_limits)
    params = {"maxResults": str(PAGE_SIZE)}
    if since:
        params["startTime"] = _z(_instant(since))
    url = LOG_URL.format(user=quote(config.user, safe="@"))
    tz = timezone or "UTC"
    drafts: list[tuple[datetime, int, dict[str, Any]]] = []
    started = time.monotonic()
    seen = 0
    asked = dict(params)
    while True:
        page = session.get_json(url, asked)
        for activity in page.get("items") or []:
            if not isinstance(activity, dict):
                continue
            seen += 1
            for draft in _lines(activity, tz, counts):
                drafts.append((_instant(str(draft["at"])), len(drafts), draft))
        if progress is not None:
            progress(seen, time.monotonic() - started)
        token = page.get("nextPageToken")
        if not isinstance(token, str) or not token:
            break
        asked = {**params, "pageToken": token}
    for _at, _n, draft in sorted(drafts, key=lambda d: (d[0], d[1])):
        yield draft


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _lines(activity: dict[str, Any], tz: str, counts: dict[str, int]) -> Iterator[dict[str, Any]]:
    found = activity.get("id")
    ident: dict[str, Any] = found if isinstance(found, dict) else {}
    spelled = str(ident.get("time") or "").strip()
    at = _stamp(spelled)
    if at is None:
        _count(counts, "skipped_no_date")
        return
    qualifier = str(ident.get("uniqueQualifier") or "")
    app = str(ident.get("applicationName") or APPLICATION)
    place = _place(activity.get("networkInfo"))
    named: dict[str, int] = {}
    for event in activity.get("events") or []:
        if not isinstance(event, dict) or not event.get("name"):
            continue
        name = str(event["name"])
        named[name] = named.get(name, 0) + 1
        suffix = f":{named[name]}" if named[name] > 1 else ""
        extra: dict[str, Any] = {"app": app, "event": name, **place}
        extra.update(_kept(event.get("parameters")))
        payload: dict[str, Any] = {
            "schema": SCHEMA,
            "raw_id": f"{APPLICATION}:{spelled}:{qualifier}:{name}{suffix}",
            "title": TITLES.get(name, name.replace("_", " ").capitalize()),
            "calendar": dict(CALENDAR),
            "all_day": False,
        }
        where = ", ".join(place[k] for k in ("city", "subdivision", "country") if k in place)
        if where:
            payload["location"] = where
        payload["extra"] = extra
        yield {
            "at": at,
            "end": None,
            "tz": tz,
            "source": NAME,
            "kind": KIND,
            "tier": TIER,
            "payload": payload,
        }


def _place(info: object) -> dict[str, str]:
    """What Google derived from the address, never the address: country, subdivision, city."""
    if not isinstance(info, dict):
        return {}
    found: dict[str, str] = {}
    for key, field in (("country", "regionCode"), ("subdivision", "subdivisionCode"), ("city", "city")):
        value = info.get(field)
        if isinstance(value, str) and value.strip():
            found[key] = " ".join(value.split())
    return {k: found[k] for k in ("country", "subdivision", "city") if k in found}


def _kept(parameters: object) -> dict[str, Any]:
    """The parameters on the list, as plain values; every other one left out."""
    found: dict[str, Any] = {}
    for parameter in parameters if isinstance(parameters, list) else []:
        if not isinstance(parameter, dict) or parameter.get("name") not in KEPT:
            continue
        for field in ("value", "boolValue", "intValue", "multiValue", "multiIntValue"):
            if field in parameter:
                value = parameter[field]
                found[str(parameter["name"])] = int(value) if field == "intValue" else value
                break
    return {k: found[k] for k in KEPT if k in found}


def _stamp(value: str) -> str | None:
    if not value:
        return None
    return _stamp_of(value, None)


def _instant(text: str) -> datetime:
    when = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC)


def _z(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
