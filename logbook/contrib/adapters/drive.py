"""Google Drive → event/v1 (RFC 0009), live: what happened to the owner's files, from the Drive Activity API.

`logbook sync drive` asks the Drive Activity API v2 (`activity:query`, read-only scope
`drive.activity.readonly`) as the owner, through the service account both Google sources share
(`service_account`: LOGBOOK_DRIVE_SA_KEY, LOGBOOK_DRIVE_USER). The API never returns a file's content,
and nothing here asks for it: a line names the file and references it, nothing more.

**What is asked.** Every activity from `since` on (the API's `time >=` filter; everything it keeps when
there is no `since`), of the actions this source maps (`detail.action_detail_case:`), unconsolidated
(`consolidationStrategy: none`, one action per activity, so an activity is the same object however often
it is read), a page of `PAGE_SIZE` at a time, newest first, retried with backoff by the session. A page
read is a progress line.

**What is an activity.** One action on one Drive item, with its actors and its time: `create` (new,
upload or copy), `edit`, `rename`, `move`, `share` (a permission added or removed), `comment` (a post,
an assignment, a suggestion, on the item), `trash`, `delete` (for good) and `restore`. Anything else
(a DLP flag, a label, a setting, a reference) is skipped and counted, and so is an action on a shared
drive itself rather than a file in it, and one with no time. Its id is the SHA-256 of what identifies
it — the time, the action, the actors and the item's id, every title left out, since the API reports a
file's current title, not the one it had — cut to 16 hex characters.

**Whose files.** The owner's: an activity is kept when the owner did it, or when the item is the
owner's (its owner is the current user, or a shared drive, or the API does not say). Someone else's
activity on someone else's file, shared with the owner, is skipped and counted (`skipped_not_involved`).

**One line per file per hour.** Activities are folded per item, per UTC hour and per activity into one
line with a count, so an afternoon of editing is a few lines, not hundreds. `at` is the first activity's
time, `end` the last one's when there are several (null for one), `tz` the record's zone. An hour is
written once it is over and `SETTLE_S` has passed (Google reports some activity late); until then its
activities wait for the next run and are counted (`held_open_hour`). The line:

- `title`: what happened, `Edited Budget 2027`, `Renamed Crew to Crew list`, `Moved Crew list to Boat`,
  `Shared …`, `Stopped sharing …`, `Changed sharing of …`, `Commented on …`, `Trashed …`, `Deleted …`,
  `Restored …`, followed by `×N` when the line folds N activities;
- `calendar` `{google-drive, Google Drive}`, `all_day` false, `modified_at` the newest activity's time;
- under `extra`: `activity`; `count`; `file` (`id`, `name`, `mime_type`, `url`, a link that opens the
  item in Drive, `https://drive.google.com/open?id=<id>`); `actors`, each once in the order seen —
  `{"kind": "owner"}` for the user the account reads as, `{"kind": "user", "person_name": "people/…"}`
  for anyone else as the API names them (a People API resource, not an address), else `deleted-user`,
  `unknown-user`, `anonymous`, `administrator`, `system`; `by_owner`, whether the owner was among them;
  `activities`, the ids it folds; and what the activity changed: `created` (`new`, `upload`, `copy`),
  `renamed` (`from`, `to`), `moved` (`from`, `to`: the folders' titles) with `folder`, the folder it
  went to — the only folder the API names, so the only one a line says — `shares` (`change` added or
  removed, `role` as the API spells it, lower case, `with` `{user}` a `people/…` name, `{group}` an
  address, `{domain}`, `{anyone}`, `{owner}`) and `comments` (`{"post:added": n, …}`).

No content, no comment text, no size and no modified time: the Activity API gives none of them, and a
size or a time would need the Drive API's metadata scope, which this source does not ask for.

**Tier 1, whoever acted.** RFC 0009 makes an entry tier 1 (SPEC §4: calendar, public activity), and these
lines are the same kind of fact: a file's name, its type, when it changed and who touched it, never
what it says. The tier is where a line may travel, not who wrote it, so a line by someone else on the
owner's file is tier 1 as much as the owner's own.

**Dedupe by activity id.** `raw_id` is `<file id>/<activity>@<hour>Z/<12 hex of the folded ids>`. Before
it folds, a pull drops every activity whose id a line of the record already carries (`recorded`, the
source's lines from the day before `since` on), so a re-run writes nothing, a lookback re-reads the day
before without writing it twice, and an activity Google reports after its hour was written is a line
of its own for that hour, never a second count of the others. The record's own dedupe on `raw_id` is
the safety net.

**Watermark.** The newest activity a line holds; a pull without `--since` starts `LOOKBACK_H` before it.
The first run reads all the activity the API keeps; give `--since` for a shorter first run."""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

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

NAME = "drive"
ENV = service_account.ENV
KIND = "event"
TIER = 1
SCHEMA = "event/v1"
UNIT = "activities"  # what `sync` counts in its progress lines
SCOPE = service_account.SCOPES["drive"]
QUERY_URL = "https://driveactivity.googleapis.com/v2/activity:query"
FILE_URL = "https://drive.google.com/open?id={id}"
PAGE_SIZE = 100
LOOKBACK_H = 24.0
SETTLE_S = 15 * 60  # an hour is written once it is over by this much
CALENDAR = {"id": "google-drive", "name": "Google Drive"}
CASES = ("CREATE", "EDIT", "MOVE", "RENAME", "DELETE", "RESTORE", "PERMISSION_CHANGE", "COMMENT")
ID_CHARS = 16
DIGEST_CHARS = 12
EXTRA_KEYS = (
    "activity",
    "count",
    "file",
    "actors",
    "by_owner",
    "activities",
    "created",
    "renamed",
    "moved",
    "folder",
    "shares",
    "comments",
)
VERBS = {
    "create": "Created",
    "edit": "Edited",
    "comment": "Commented on",
    "trash": "Trashed",
    "delete": "Deleted",
    "restore": "Restored",
}
UNTITLED = "an untitled item"

configure = service_account.configure


def check(config: Account) -> str:
    """What `doctor` says after `configured`: the key read and loadable, no network asked."""
    return service_account.describe(config)


def resume(config: Account, mark: str) -> str:
    """Where a pull starts, given the watermark: a day before it, for activity Google reports late."""
    start = _instant(mark) - timedelta(hours=LOOKBACK_H)
    return _z(start)


def watermark(draft: dict[str, Any]) -> str | None:
    """The newest activity the line holds."""
    modified = draft["payload"].get("modified_at")
    return str(modified) if modified else None


def group(draft: dict[str, Any]) -> str:
    """The activity, so `sync` says seen and new per activity."""
    return str(draft["payload"]["extra"]["activity"])


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Activity:
    """One action on one item, as this source reads it."""

    id: str
    activity: str  # create, edit, …
    start: datetime
    end: datetime
    item: dict[str, Any]
    actors: tuple[dict[str, Any], ...]
    detail: dict[str, Any]  # the action's detail, one key: create, edit, move, …


def pull(
    config: Account,
    since: str | None = None,
    progress: Callable[[int, float], None] | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
    recorded: Callable[[str | None], Iterable[dict[str, Any]]] | None = None,
) -> Iterator[dict[str, Any]]:
    """Every activity from `since` (RFC3339; None for all the API keeps) folded per file, hour and
    activity into event/v1 line drafts, oldest first. Skips and held activities are tallied in `counts`;
    `progress(activities_so_far, elapsed_seconds)` after each page; `recorded(since)` gives the lines the
    record already holds, whose activities are not written again. Raises service_account.GoogleError
    (an OSError) when Google cannot be read; nothing is yielded before every page is in."""
    counts = counts if counts is not None else {}
    session = service_account.Session(config, SCOPE)
    raw = _query(session, since, progress)
    known = _known(recorded(since) if recorded is not None else ())
    cutoff = _now() - timedelta(seconds=SETTLE_S)
    hours: dict[tuple[str, str, str], list[Activity]] = {}
    for activity in _activities(raw, counts):
        if activity.id in known:
            _count(counts, "already_in_lines")
            continue
        hour = activity.start.replace(minute=0, second=0, microsecond=0)
        if hour + timedelta(hours=1) > cutoff:
            _count(counts, "held_open_hour")
            continue
        key = (_item_id(activity.item), activity.activity, hour.strftime("%Y-%m-%dT%H"))
        hours.setdefault(key, []).append(activity)
    tz = timezone or "UTC"
    drafts = [_draft(file_id, word, hour, folded, tz) for (file_id, word, hour), folded in hours.items()]
    yield from sorted(drafts, key=lambda d: (d["at"], d["payload"]["raw_id"]))


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _query(
    session: service_account.Session, since: str | None, progress: Callable[[int, float], None] | None
) -> list[dict[str, Any]]:
    """Every page of activity:query from `since`, as the API returns it."""
    clauses = [f'time >= "{_z(_instant(since))}"'] if since else []
    clauses.append(f"detail.action_detail_case:({' '.join(CASES)})")
    body: dict[str, Any] = {
        "filter": " AND ".join(clauses),
        "consolidationStrategy": {"none": {}},
        "pageSize": PAGE_SIZE,
    }
    found: list[dict[str, Any]] = []
    started = time.monotonic()
    while True:
        page = session.post_json(QUERY_URL, body)
        found.extend(a for a in page.get("activities") or [] if isinstance(a, dict))
        if progress is not None:
            progress(len(found), time.monotonic() - started)
        token = page.get("nextPageToken")
        if not isinstance(token, str) or not token:
            return found
        body = {**body, "pageToken": token}


def _known(lines: Iterable[dict[str, Any]]) -> set[str]:
    """The activity ids the record's lines already carry."""
    known: set[str] = set()
    for line in lines:
        extra = (line.get("payload") or {}).get("extra")
        if isinstance(extra, dict) and isinstance(extra.get("activities"), list):
            known.update(str(i) for i in extra["activities"])
    return known


def _activities(raw: list[dict[str, Any]], counts: dict[str, int]) -> Iterator[Activity]:
    """Each action of each activity, oldest first, those this source does not keep counted."""
    for entry in sorted(raw, key=_entry_time):
        actions = [a for a in entry.get("actions") or [] if isinstance(a, dict)]
        if not actions:
            actions = [{"detail": entry.get("primaryActionDetail")}]
        for action in actions:
            yield from _of_action(entry, action, counts)


def _entry_time(entry: dict[str, Any]) -> datetime:
    """When an activity began, for the order they are read in; one with no time first."""
    span = _span(entry)
    return span[0] if span is not None else datetime.min.replace(tzinfo=UTC)


def _of_action(entry: dict[str, Any], action: dict[str, Any], counts: dict[str, int]) -> Iterator[Activity]:
    found = action.get("detail")
    detail: dict[str, Any] = found if isinstance(found, dict) else {}
    word = _word(detail)
    if word is None:
        _count(counts, "skipped_other_activity")
        return
    span = _span(action) or _span(entry)
    if span is None:
        _count(counts, "skipped_no_date")
        return
    raw_actors = (
        [action["actor"]] if isinstance(action.get("actor"), dict) else list(entry.get("actors") or [])
    )
    actors = tuple(_actor(a) for a in raw_actors if isinstance(a, dict))
    targets = (
        [action["target"]] if isinstance(action.get("target"), dict) else list(entry.get("targets") or [])
    )
    for target in targets:
        item = _item(target)
        if item is None or not _item_id(item):
            _count(counts, "skipped_not_a_file")
            continue
        if not any(a["kind"] == "owner" for a in actors) and _others(item):
            _count(counts, "skipped_not_involved")
            continue
        yield Activity(_id(span, detail, raw_actors, item), word, span[0], span[1], item, actors, detail)


def _word(detail: dict[str, Any]) -> str | None:
    """The action as this source names it, or None for one it does not map."""
    if "delete" in detail:
        kind = str((detail.get("delete") or {}).get("type") or "")
        return "delete" if kind == "PERMANENT_DELETE" else "trash"
    for key, word in (
        ("create", "create"),
        ("edit", "edit"),
        ("rename", "rename"),
        ("move", "move"),
        ("permissionChange", "share"),
        ("comment", "comment"),
        ("restore", "restore"),
    ):
        if key in detail:
            return word
    return None


def _span(holder: dict[str, Any]) -> tuple[datetime, datetime] | None:
    """(start, end) of an action or activity: its timestamp twice, or its time range."""
    try:
        if holder.get("timestamp"):
            at = _instant(str(holder["timestamp"]))
            return at, at
        span = holder.get("timeRange")
        if isinstance(span, dict) and span.get("startTime"):
            start = _instant(str(span["startTime"]))
            return start, _instant(str(span.get("endTime") or span["startTime"]))
    except ValueError:
        return None
    return None


def _item(target: dict[str, Any]) -> dict[str, Any] | None:
    """The Drive item a target is or is on (a comment's file); None for a shared drive itself."""
    if isinstance(target.get("driveItem"), dict):
        return dict(target["driveItem"])
    comment = target.get("fileComment")
    if isinstance(comment, dict) and isinstance(comment.get("parent"), dict):
        return dict(comment["parent"])
    return None


def _item_id(item: dict[str, Any]) -> str:
    return str(item.get("name") or "").removeprefix("items/")


def _others(item: dict[str, Any]) -> bool:
    """Whether the item is known to be someone else's: owned by a user who is not the owner."""
    owner = item.get("owner")
    if not isinstance(owner, dict) or not isinstance(owner.get("user"), dict):
        return False  # a shared drive's, or the API does not say: kept
    known = owner["user"].get("knownUser")
    return not (isinstance(known, dict) and known.get("isCurrentUser") is True)


def _actor(actor: dict[str, Any]) -> dict[str, Any]:
    """An actor as a line names it: the owner as `owner`, anyone else as the API gives them."""
    if isinstance(actor.get("user"), dict):
        return _user(actor["user"])
    if "anonymous" in actor:
        return {"kind": "anonymous"}
    if "administrator" in actor:
        return {"kind": "administrator"}
    if isinstance(actor.get("impersonation"), dict):
        return {"kind": "impersonation"}
    if isinstance(actor.get("system"), dict):
        kind = str(actor["system"].get("type") or "").lower()
        return {"kind": "system", "type": kind} if kind else {"kind": "system"}
    return {"kind": "unknown"}


def _user(user: dict[str, Any]) -> dict[str, Any]:
    known = user.get("knownUser")
    if isinstance(known, dict):
        if known.get("isCurrentUser") is True:
            return {"kind": "owner"}
        if known.get("personName"):
            return {"kind": "user", "person_name": str(known["personName"])}
    if "deletedUser" in user:
        return {"kind": "deleted-user"}
    return {"kind": "unknown-user"}


def _id(
    span: tuple[datetime, datetime], detail: dict[str, Any], actors: list[Any], item: dict[str, Any]
) -> str:
    """The activity's id: what identifies it, every title left out (the API reports the current one)."""
    what = {
        "time": [span[0].isoformat(timespec="milliseconds"), span[1].isoformat(timespec="milliseconds")],
        "detail": _untitled(detail),
        "actors": _untitled(actors),
        "item": _item_id(item),
    }
    text = json.dumps(what, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:ID_CHARS]


def _untitled(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _untitled(v) for k, v in value.items() if k != "title"}
    if isinstance(value, list):
        return [_untitled(v) for v in value]
    return value


def _draft(file_id: str, word: str, hour: str, folded: list[Activity], tz: str) -> dict[str, Any]:
    folded = sorted(folded, key=lambda a: (a.start, a.id))
    first, last = folded[0], folded[-1]
    end = max(a.end for a in folded)
    newest = max(a.start for a in folded)
    file = _file(file_id, last.item)
    actors: list[dict[str, Any]] = []
    for activity in folded:
        for actor in activity.actors:
            if actor not in actors:
                actors.append(actor)
    ids = [a.id for a in folded]
    extra: dict[str, Any] = {
        "activity": word,
        "count": len(folded),
        "file": file,
        "actors": actors,
        "by_owner": any(a["kind"] == "owner" for a in actors),
        "activities": ids,
    }
    extra.update(_changed(word, folded))
    digest = hashlib.sha256("\n".join(ids).encode("ascii")).hexdigest()[:DIGEST_CHARS]
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": f"{file_id}/{word}@{hour}Z/{digest}",
        "title": _title(word, str(file.get("name") or UNTITLED), extra),
        "calendar": dict(CALENDAR),
        "all_day": False,
        "modified_at": _z(newest),
        "extra": extra,
    }
    return {
        "at": _z(first.start),
        "end": _z(end) if end != first.start else None,
        "tz": tz,
        "source": NAME,
        "kind": KIND,
        "tier": TIER,
        "payload": payload,
    }


def _file(file_id: str, item: dict[str, Any]) -> dict[str, Any]:
    file: dict[str, Any] = {"id": file_id}
    title = " ".join(str(item.get("title") or "").split())
    if title:
        file["name"] = title
    if item.get("mimeType"):
        file["mime_type"] = str(item["mimeType"])
    file["url"] = FILE_URL.format(id=file_id)
    return file


def _changed(word: str, folded: list[Activity]) -> dict[str, Any]:
    """What the activity changed, from its details: the first and last for a rename or a move, every
    permission for a share, the subtypes counted for comments."""
    first, last = folded[0].detail, folded[-1].detail
    if word == "create":
        made = first.get("create") or {}
        return {"created": next((k for k in ("upload", "copy", "new") if k in made), "new")}
    if word == "rename":
        renamed = {
            "from": (first.get("rename") or {}).get("oldTitle"),
            "to": (last.get("rename") or {}).get("newTitle"),
        }
        return {"renamed": {k: str(v) for k, v in renamed.items() if v}}
    if word == "move":
        moved = {
            "from": _titles((first.get("move") or {}).get("removedParents")),
            "to": _titles((last.get("move") or {}).get("addedParents")),
        }
        out: dict[str, Any] = {"moved": moved}
        if moved["to"]:
            out["folder"] = moved["to"][0]
        return out
    if word == "share":
        shares: list[dict[str, Any]] = []
        for activity in folded:
            change = activity.detail.get("permissionChange") or {}
            for side, permissions in (("added", "addedPermissions"), ("removed", "removedPermissions")):
                for permission in change.get(permissions) or []:
                    share = _share(side, permission)
                    if share is not None and share not in shares:
                        shares.append(share)
        return {"shares": shares}
    if word == "comment":
        said: Counter[str] = Counter()
        for activity in folded:
            comment = activity.detail.get("comment") or {}
            kind = next(
                (k for k in ("post", "assignment", "suggestion") if isinstance(comment.get(k), dict)), None
            )
            if kind is not None:
                said[f"{kind}:{str(comment[kind].get('subtype') or 'unspecified').lower()}"] += 1
        return {"comments": dict(sorted(said.items()))}
    return {}


def _titles(parents: Any) -> list[str]:
    """The folders of a move, by title, as the API names them (a shared drive's root by its name)."""
    found: list[str] = []
    for parent in parents or []:
        if not isinstance(parent, dict):
            continue
        ref = parent.get("driveItem") or parent.get("drive") or parent.get("teamDrive") or {}
        title = " ".join(str(ref.get("title") or "").split()) if isinstance(ref, dict) else ""
        if title:
            found.append(title)
    return found


def _share(side: str, permission: Any) -> dict[str, Any] | None:
    if not isinstance(permission, dict):
        return None
    role = str(permission.get("role") or "unspecified").lower()
    if isinstance(permission.get("user"), dict):
        user = _user(permission["user"])
        whom: dict[str, Any] = (
            {"owner": True} if user["kind"] == "owner" else {"user": user.get("person_name", user["kind"])}
        )
    elif isinstance(permission.get("group"), dict):
        whom = {"group": str(permission["group"].get("email") or permission["group"].get("title") or "")}
    elif isinstance(permission.get("domain"), dict):
        whom = {"domain": str(permission["domain"].get("name") or "")}
    elif "anyone" in permission:
        whom = {"anyone": True}
    else:
        return None
    return {"change": side, "role": role, "with": whom}


def _title(word: str, name: str, extra: Mapping[str, Any]) -> str:
    if word == "rename":
        renamed = extra.get("renamed") or {}
        text = (
            f"Renamed {renamed['from']} to {renamed['to']}"
            if renamed.get("from") and renamed.get("to")
            else f"Renamed {name}"
        )
    elif word == "move":
        text = f"Moved {name} to {extra['folder']}" if extra.get("folder") else f"Moved {name}"
    elif word == "share":
        sides = {s["change"] for s in extra.get("shares") or []}
        text = (
            f"Shared {name}"
            if sides == {"added"}
            else f"Stopped sharing {name}"
            if sides == {"removed"}
            else f"Changed sharing of {name}"
        )
    else:
        text = f"{VERBS[word]} {name}"
    count = int(extra.get("count") or 1)
    return f"{text} ×{count}" if count > 1 else text


def _instant(text: str) -> datetime:
    """An RFC 3339 time as an aware UTC datetime; ValueError for one that is not."""
    when = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC)


def _z(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
