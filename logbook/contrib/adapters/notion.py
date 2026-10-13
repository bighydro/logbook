"""Notion → event/v1 (RFC 0009), live: what happened to each page on each day, never the page.

The owner keeps ideas, research, notes, tasks and contacts in Notion; the record keeps what happened
there — a page created, edited, moved or archived, a database row's status changed — as one
`event/v1` line per page, local day and action, with a reference to the page (its id and url) and
never a copy of it: no body, no comment, no file, no property but a documented few.

Configured by the environment alone. `LOGBOOK_NOTION_TOKEN` (required) is an internal integration's
secret; the owner shares the workspace's top-level pages with the integration, which then reads them
and everything under them, and nothing else. `LOGBOOK_NOTION_ROOTS` (optional) names pages or
databases, by id or by the link Notion copies, comma- or space-separated: only pages at or under one
of them are read (default: everything the token can see). `LOGBOOK_NOTION_OWNER_ID` (optional) is the
owner's Notion user id, used for one thing, to mark an actor `owner`; without it the user who owns
the token's integration, when Notion names one (an internal integration belongs to the workspace, so
usually it does not, and the run says so). `LOGBOOK_NOTION_URL` (optional) is another address for
the API: https, or http on this machine only, so the token never crosses a network in the clear.

The calls, `Notion-Version: 2022-06-28`, and nothing that writes (the search is a POST that changes
nothing; no other POST, no PATCH, no DELETE is ever sent): `GET /v1/users/me` first (the token
works; whose integration it is); `POST /v1/search` for pages, newest edit first, `PAGE_SIZE` a page
by `start_cursor`, until a page last edited before `since`; `GET /v1/pages/{id}`, `/databases/{id}`
and `/blocks/{id}` for the titles above a page, each once a run; `GET /v1/blocks/{id}/children`,
paged and recursed (a child page or database is its own page, never part of this one's body), for
the body's text, which is hashed and counted and never kept; `GET /v1/users/{id}` for an actor's
name, once per person a run, and never again in the run once Notion says the integration may not
read people. Requests start at least a third of a second apart (Notion's documented average is three
a second); a 429 or a 503 waits what `Retry-After` says, one without a usable one and any other
5xx wait 1 s doubling to 60 s, up to `RETRIES` times, then the pull fails with one sentence and
`sync` keeps the watermark it had. A connection that fails is tried `CONNECT_RETRIES` more times.
Reading a page's blocks, a 400 `validation_error` naming a block type the API withholds from
integrations (`ai_block`) or a 404 (a block deleted while the page is read) marks that page's body
unavailable and the run goes on; the block type is said once a run, never the page; any other 400
stops the run. Network happens only inside `pull`, which only `logbook sync notion` calls; `doctor`
asks Notion nothing.

A line: `kind` `event`, `tier` 1 — SPEC §4 and RFC 0009 give `event/v1` tier 1, and a line here
carries a title, the titles above it and who acted, as a calendar entry carries a title and its
organizer; RFC 0009's tier 2 is for entries with attendees, which a page has none of. The tier is
where a line may travel, never who wrote it: a line Ola made is tier 1 as a line Ines made is.
`at` is the page's `created_time` for `created` and its `last_edited_time` for the other actions,
`end` null; the day is the record's local day of `at`. The payload: `raw_id` `<page id>/<day>/
<action>`, the dedupe key; `title` the page's title verbatim (absent when it has none); `calendar`
`{notion, Notion}`; `all_day` false; `modified_at` the `last_edited_time` this run saw (the
watermark); and under `extra`: `action`; `page` (`id`, `url`, never the public link); `path`, the
titles above the page, the top first, as far as the integration can see (a block between them has
none); `parent` (`type` page, database, block or workspace, and `id`); `actor` (`id`, `name`, `type`
person or bot, and `role` owner or other once the owner is known), the creator on `created`, the
last editor otherwise; `moved_from` (`parent`, `path`) on a move; and on the line that holds the page
as it is now (the action at its last edit; a `created` line only when it is that edit too) `body` —
`sha256` and `bytes` of the text in UTF-8, `media_type` text/plain and no `path`, the record holds a
digest, not the text (SPEC §1.1) — `words` (whitespace-separated) and `words_delta` against the
page's previous line that has a count; or, when the blocks cannot all be read, `{unavailable:
withheld}` (the API withholds a block type the page holds) or `{unavailable: not_found}` (a block was
deleted while the page was read), never a digest of part of the text; `properties`, a database
row's `status`, `select`, `multi_select`, `date` and `checkbox` values by name (never text, a number,
a person, a phone, an email, a url, a file, a formula or a relation); and `changed`, `[{name, old,
new}]` for those that differ from the page's previous line. Notion's API keeps no history of a page,
so the record is its history: `pull` takes `previous`, which hands it the lines the record holds for
a page, and compares with them.

Which lines a page gives, per run: `created` when its `created_time` is at or after `since` (every
page on a first run); then, unless the record already holds the page at this `last_edited_time`,
one line at that edit — `archived` when the page is archived or in the trash, `moved` when its
parent is not the one on its previous line, else `edited`. An edit on the day the page was made,
seen with its creation in one run, is the `created` line, which then holds the page as it is: one
line per page and day touched. A page edited twice on one day is one line: the second edit's key is
the first's, and the record refuses it. A later edit the same day after a `created` line is in the
record is an `edited` line beside it. A page removed without Notion listing it again leaves no line.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

__all__ = [
    "ENV",
    "KIND",
    "NAME",
    "TIER",
    "Config",
    "configure",
    "group",
    "notion_id",
    "pull",
    "resume",
    "watermark",
]

NAME = "notion"
KIND = "event"
TIER = 1  # SPEC §4, RFC 0009: event/v1; the actor never changes it
SCHEMA = "event/v1"
TOKEN_ENV = "LOGBOOK_NOTION_TOKEN"
ROOTS_ENV = "LOGBOOK_NOTION_ROOTS"
OWNER_ENV = "LOGBOOK_NOTION_OWNER_ID"
URL_ENV = "LOGBOOK_NOTION_URL"
ENV = (TOKEN_ENV,)  # the roots, the owner and the address are optional and read beside it
DEFAULT_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
UNIT = "pages"  # what `sync` counts in its progress lines
PAGE_SIZE = 100  # the API's maximum
LOOKBACK_H = 2.0  # Notion stamps an edit to the minute and its search catches up late
REQUESTS_PER_S = 3.0  # Notion's documented average
RETRIES = 6  # a 429 or a 5xx, then the run stops
CONNECT_RETRIES = 2  # a connection that failed
BACKOFF_S = 1.0
BACKOFF_MAX_S = 60.0
WAIT_MAX_S = 300.0  # a Retry-After longer than this stops the run: the next one carries on
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
TIMEOUT_S = 60
MAX_PAGES = 100_000  # a list longer than this many pages is a cursor that stopped moving
MAX_DEPTH = 32  # blocks within blocks, and pages above pages
BATCH = 100  # pages per question to the record
CALENDAR = {"id": "notion", "name": "Notion"}
CREATED, EDITED, MOVED, ARCHIVED = "created", "edited", "moved", "archived"
WITHHELD, NOT_FOUND = "withheld", "not_found"  # why a page's body is unavailable
OWNER, OTHER = "owner", "other"
PROPERTY_TYPES = frozenset({"status", "select", "multi_select", "date", "checkbox"})
UNTITLED = "Untitled"  # an untitled page above another, as Notion shows it
ID = re.compile(
    r"(?<![0-9a-f])([0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$", re.I
)
WITHHELD_BLOCK = re.compile(r"\bblock type [`'\"]?(\w+)[`'\"]? is not supported\b", re.I)
TOKEN_HINT = (
    f"check {TOKEN_ENV}: the internal integration's secret, under Notion → Settings → Connections →"
    " Develop or manage integrations"
)

_sleep: Callable[[float], None] = time.sleep  # the tests replace both: a wait is recorded, never slept
_clock: Callable[[], float] = time.monotonic

Previous = Callable[[Iterable[str]], Mapping[str, list[dict[str, Any]]]]


@dataclass(frozen=True)
class Config:
    url: str
    token: str = field(repr=False)
    roots: tuple[str, ...] = ()
    owner_id: str | None = None


def notion_id(text: str) -> str | None:
    """A Notion id from the id itself (32 hex digits, dashed or not) or from the link Notion copies
    (`https://www.notion.so/<workspace>/<Title>-<id>?pvs=4`), dashed and lower case; None for
    anything else."""
    head = text.strip().split("?", 1)[0].split("#", 1)[0].rstrip("/")
    found = ID.search(head)
    if found is None:
        return None
    raw = found.group(1).replace("-", "").lower()
    return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"


def configure(env: Mapping[str, str]) -> Config | None:
    """Config from the environment: None without the token; ValueError, one sentence naming the
    variable, for an address that is not https (http only on this machine), a root that is not an id
    or a link, or an owner id that is not one."""
    given = env.get(URL_ENV, "").strip()
    url = given.rstrip("/") if given else DEFAULT_URL
    parts = urlsplit(url)
    if (
        not parts.hostname
        or parts.scheme not in ("https", "http")
        or (parts.scheme == "http" and parts.hostname not in LOCAL_HOSTS)
    ):
        raise ValueError(
            f"{URL_ENV} must be an https URL (http only on this machine), such as {DEFAULT_URL},"
            f" not {given!r}"
        )
    roots: list[str] = []
    for part in re.split(r"[\s,]+", env.get(ROOTS_ENV, "")):
        if not part:
            continue
        found = notion_id(part)
        if found is None:
            raise ValueError(
                f"{ROOTS_ENV} names pages and databases by id or by link, and {part!r} is neither"
            )
        if found not in roots:
            roots.append(found)
    owner_text = env.get(OWNER_ENV, "").strip()
    owner = notion_id(owner_text) if owner_text else None
    if owner_text and owner is None:
        raise ValueError(f"{OWNER_ENV} must be a Notion user id, 32 hex digits, not {owner_text!r}")
    token = env.get(TOKEN_ENV, "").strip()
    if not token:
        return None
    return Config(url=url, token=token, roots=tuple(roots), owner_id=owner)


def watermark(draft: dict[str, Any]) -> str | None:
    """The page's `last_edited_time` as the run saw it: the search is read back to it."""
    return str(draft["payload"]["modified_at"])


def resume(config: Config, mark: str) -> str:
    """Where a run starts: `LOOKBACK_H` before the watermark, for an edit Notion's search lists late."""
    when = _instant(mark)
    if when is None:
        return mark
    return _stamp(when - timedelta(hours=LOOKBACK_H))


def group(draft: dict[str, Any]) -> str:
    """The action, as `sync` reports seen and new per action."""
    return str(draft["payload"]["extra"]["action"])


def pull(
    config: Config,
    since: str | None = None,
    progress: Callable[[int, float], None] | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
    previous: Previous | None = None,
    notice: Callable[[str], None] | None = None,
) -> Iterator[dict[str, Any]]:
    """The lines for every page last edited at or after `since` (every page when None), oldest edit
    first, each page's `created` line before its edit's. The pages are listed first, newest edit
    first as the search serves them (`progress(pages_so_far, elapsed)` after each page of the
    list), then read in batches of `BATCH`, each batch's lines in the record asked for once through
    `previous` (`{"<page id>/": [payload, ...]}`, in chain order); `notice` says how far the reading
    is when there is more than one batch. Skips and notes are tallied in `counts`. Raises OSError
    with one sentence, never the token, when Notion refuses the token, does not answer, or keeps
    saying wait; ValueError on an answer that is not what the API documents."""
    counts = counts if counts is not None else {}
    zone = ZoneInfo(timezone or "UTC")
    started = time.monotonic()
    client = _Client(config)
    me = client.get("/users/me")
    owner = config.owner_id or _token_owner(me)
    floor = _instant(since) if since is not None else None
    listed = _list(client, floor, progress, started)
    pages = [p for p in (_Page.of(item) for item in listed) if p is not None]
    _count(counts, "skipped_bad_date", len(listed) - len(pages))
    tree = _Tree(client, pages)
    people = _People(client, owner)
    bodies = _Bodies(client, notice)
    pages.sort(key=lambda p: (p.edited, p.id))
    for n in range(0, len(pages), BATCH):
        batch = pages[n : n + BATCH]
        held = previous([f"{p.id}/" for p in batch]) if previous is not None else {}
        for p in batch:
            yield from _drafts(
                p, _Seen.of(held.get(f"{p.id}/", [])), floor, zone, config, tree, people, bodies, counts
            )
        if notice is not None and len(pages) > BATCH:
            notice(f"{n + len(batch):,} of {len(pages):,} pages read")
    if owner is None and notice is not None and people.seen:  # so a dry run tells the owner their id
        named = ", ".join(f"{name or 'unnamed'} ({user_id})" for user_id, name in people.seen.items())
        notice(f"no owner known; the people who acted: {named}; set {OWNER_ENV} to yours")


def _count(counts: dict[str, int], key: str, n: int = 1) -> None:
    if n:
        counts[key] = counts.get(key, 0) + n


# -- the API ---------------------------------------------------------------------------------------------


class _Again(Exception):
    """A request worth asking again: a 429, a 5xx, a connection that failed."""

    def __init__(self, what: str, after: float | None = None, connect: bool = False) -> None:
        super().__init__(what)
        self.what = what
        self.after = after
        self.connect = connect


class _Unreachable(OSError):
    """403 or 404: the integration may not read this object, or it is gone."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class _Withheld(OSError):
    """400 `validation_error`: the API withholds a block type from integrations (`ai_block`)."""

    def __init__(self, block_type: str, message: str) -> None:
        super().__init__(message)
        self.block_type = block_type


class _Client:
    """Every call to Notion: paced, retried, read-only. The token goes in the header only."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.last: float | None = None

    def get(self, path: str, query: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self._call("GET", path, query, None)

    def search(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """`POST /search`: the API's query, which reads and changes nothing."""
        return self._call("POST", "/search", None, body)

    def _pace(self) -> None:
        """Never sooner than a third of a second after the last request started."""
        gap = 1.0 / REQUESTS_PER_S
        if self.last is not None:
            waited = _clock() - self.last
            if waited < gap:
                _sleep(gap - waited)
        self.last = _clock()

    def _call(
        self, method: str, path: str, query: Mapping[str, Any] | None, body: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        failure, tries, connects = "", 0, 0
        for attempt in range(RETRIES + 1):
            self._pace()
            tries += 1
            try:
                return self._once(method, path, query, body)
            except _Again as again:
                failure = again.what if again.connect else f"Notion API {method} {path}: {again.what}"
                connects += again.connect
                if attempt == RETRIES or connects > CONNECT_RETRIES:
                    break
                wait = again.after if again.after is not None else min(BACKOFF_S * 2**attempt, BACKOFF_MAX_S)
                if wait > WAIT_MAX_S:
                    raise OSError(
                        f"{failure}, and it asks to wait {wait:,.0f}s; stopped, the next run carries on from"
                        " the watermark"
                    ) from None
                _sleep(wait)
        raise OSError(f"{failure}, {tries} times; stopped, the next run carries on from the watermark")

    def _once(
        self, method: str, path: str, query: Mapping[str, Any] | None, body: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        url = self.config.url + path + (f"?{urlencode(query)}" if query else "")
        headers = {
            "Authorization": f"Bearer {self.config.token}",
            "Notion-Version": NOTION_VERSION,
            "Accept": "application/json",
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            with urlopen(
                Request(url, data=data, headers=headers, method=method), timeout=TIMEOUT_S
            ) as response:
                raw = response.read()
        except HTTPError as e:
            said = _error_text(e)
            if e.code in RETRY_STATUSES:
                what = "rate limited (429)" if e.code == 429 else f"answered {e.code}"
                after = _retry_after(e.headers.get("Retry-After")) if e.code in (429, 503) else None
                raise _Again(what, after) from None
            if e.code == 401:
                raise OSError(f"Notion refused the token (401): {TOKEN_HINT}") from None
            if e.code in (403, 404):
                raise _Unreachable(e.code, f"Notion API {method} {path} answered {e.code}: {said}") from None
            withheld = _withheld_type(said) if e.code == 400 else None
            if withheld is not None:
                raise _Withheld(withheld, f"Notion API {method} {path} answered 400: {said}") from None
            raise OSError(f"Notion API {method} {path} answered {e.code}: {said}") from None
        except (URLError, TimeoutError, OSError, HTTPException) as e:  # refused, reset, timed out, cut off
            reason = e.reason if isinstance(e, URLError) else (str(e) or type(e).__name__)
            raise _Again(f"Notion did not answer at {self.config.url} ({reason})", connect=True) from None
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ValueError(f"Notion API {method} {path} did not answer with JSON") from None
        if not isinstance(doc, dict):
            raise ValueError(f"Notion API {method} {path} did not answer with an object")
        return doc

    def pages_of(self, path: str) -> Iterator[list[Any]]:
        """`GET` a paged list, one list of results per page, by `start_cursor`."""
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            query: dict[str, Any] = {"page_size": PAGE_SIZE}
            if cursor is not None:
                query["start_cursor"] = cursor
            page = self.get(path, query)
            following, results = _following(page, path, cursor)
            yield results
            if following is None:
                return
            cursor = following
        raise ValueError(f"Notion API GET {path}: more than {MAX_PAGES:,} pages; stopped")


def _following(page: dict[str, Any], path: str, cursor: str | None) -> tuple[str | None, list[Any]]:
    """(the next cursor or None, the results) of one page of a list."""
    results = page.get("results")
    if not isinstance(results, list):
        raise ValueError(f"Notion API {path} did not answer with a list of results")
    following = page.get("next_cursor")
    if not page.get("has_more") or not isinstance(following, str) or not following:
        return None, results
    if following == cursor:
        raise ValueError(f"Notion API {path}: the cursor {following!r} does not move; stopped")
    return following, results


def _error_text(e: HTTPError) -> str:
    """Notion's own `code: message` from an error's body, else the reason."""
    try:
        doc = json.loads(e.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return str(e.reason)
    if isinstance(doc, dict) and isinstance(doc.get("message"), str):
        return f"{doc.get('code', 'error')}: {doc['message']}"
    return str(e.reason)


def _withheld_type(said: str) -> str | None:
    """The block type a 400 says the API withholds from integrations (`validation_error: Block type
    ai_block is not supported via the API for your bot type.`); None for any other 400."""
    if not said.startswith("validation_error: "):
        return None
    found = WITHHELD_BLOCK.search(said)
    return found.group(1) if found is not None else None


def _retry_after(value: str | None) -> float | None:
    """`Retry-After` in seconds when it is a number of them; None for a date or anything else."""
    try:
        seconds = float(value) if value is not None else -1.0
    except ValueError:
        return None
    return seconds if 0 <= seconds < float("inf") else None


def _token_owner(me: dict[str, Any]) -> str | None:
    """The user who owns the token's integration, when Notion names one (a public integration);
    an internal integration belongs to the workspace and names nobody."""
    bot = me.get("bot")
    owner = bot.get("owner") if isinstance(bot, dict) else None
    if isinstance(owner, dict) and owner.get("type") == "user" and isinstance(owner.get("user"), dict):
        return _id(owner["user"].get("id"))
    return None


def _list(
    client: _Client, floor: datetime | None, progress: Callable[[int, float], None] | None, started: float
) -> list[dict[str, Any]]:
    """Every page the search lists, newest edit first, until one last edited before `floor`; each
    page once, however the list shifts under an edit made while it is read."""
    found: dict[str, dict[str, Any]] = {}
    cursor: str | None = None
    for _ in range(MAX_PAGES):
        body: dict[str, Any] = {
            "filter": {"property": "object", "value": "page"},
            "sort": {"direction": "descending", "timestamp": "last_edited_time"},
            "page_size": PAGE_SIZE,
        }
        if cursor is not None:
            body["start_cursor"] = cursor
        following, results = _following(client.search(body), "POST /search", cursor)
        reached = False
        for item in results:
            if not isinstance(item, dict) or item.get("object") != "page":
                continue
            edited = _instant(item.get("last_edited_time"))
            if floor is not None and edited is not None and edited < floor:
                reached = True
                continue
            page_id = _id(item.get("id"))
            if page_id is not None and page_id not in found:
                found[page_id] = item
        if progress is not None:
            progress(len(found), time.monotonic() - started)
        if reached or following is None:
            return list(found.values())
        cursor = following
    raise ValueError(f"Notion API POST /search: more than {MAX_PAGES:,} pages; stopped")


# -- a page, what is above it, who acted -----------------------------------------------------------------


@dataclass(frozen=True)
class _Ref:
    """Where a page lives: a page, a database, a block or the workspace, and its id."""

    type: str
    id: str | None

    @classmethod
    def of(cls, raw: object) -> _Ref | None:
        if not isinstance(raw, dict):
            return None
        kind = raw.get("type")
        if kind == "workspace":
            return cls("workspace", None)
        if kind in ("page_id", "database_id", "block_id"):
            found = _id(raw.get(kind))
            return cls(kind.removesuffix("_id"), found) if found is not None else None
        if kind == "data_source_id":  # a later API version's database: its database is the parent
            database = _id(raw.get("database_id"))
            return (
                cls("database", database) if database is not None else cls("data_source", _id(raw.get(kind)))
            )
        return None

    def to_json(self) -> dict[str, Any]:
        return {"type": self.type} if self.id is None else {"type": self.type, "id": self.id}


@dataclass(frozen=True)
class _Page:
    id: str
    created: datetime
    edited: datetime
    created_by: object
    edited_by: object
    archived: bool
    parent: _Ref | None
    title: str | None
    url: str | None
    properties: dict[str, Any]

    @classmethod
    def of(cls, item: dict[str, Any]) -> _Page | None:
        page_id = _id(item.get("id"))
        created = _instant(item.get("created_time"))
        edited = _instant(item.get("last_edited_time"))
        if page_id is None or created is None or edited is None:
            return None
        url = item.get("url")
        return cls(
            id=page_id,
            created=created,
            edited=edited,
            created_by=item.get("created_by"),
            edited_by=item.get("last_edited_by"),
            archived=bool(item.get("archived")) or bool(item.get("in_trash")),
            parent=_Ref.of(item.get("parent")),
            title=_page_title(item),
            url=url if isinstance(url, str) and url else None,
            properties=_properties(item.get("properties")),
        )


@dataclass(frozen=True)
class _Node:
    title: str | None
    parent: _Ref | None


class _Tree:
    """The titles above a page, each object asked for once a run; the pages listed are known."""

    def __init__(self, client: _Client, pages: Iterable[_Page]) -> None:
        self.client = client
        self.nodes: dict[tuple[str, str], _Node | None] = {
            ("page", p.id): _Node(p.title or UNTITLED, p.parent) for p in pages
        }

    def node(self, ref: _Ref) -> _Node | None:
        if ref.id is None:
            return None
        key = (ref.type, ref.id)
        if key not in self.nodes:
            self.nodes[key] = self._fetch(ref.type, ref.id)
        return self.nodes[key]

    def _fetch(self, kind: str, object_id: str) -> _Node | None:
        path = {"page": "/pages/", "database": "/databases/", "block": "/blocks/"}.get(kind)
        if path is None:
            return None
        try:
            found = self.client.get(path + object_id)
        except _Unreachable:  # not shared with the integration, or gone: the path stops here
            return None
        if kind == "page":
            title: str | None = _page_title(found) or UNTITLED
        elif kind == "database":
            title = _plain(found.get("title")) or UNTITLED
        else:
            title = None  # a block (a column, a toggle) holds a page but has no title of its own
        return _Node(title, _Ref.of(found.get("parent")))

    def above(self, parent: _Ref | None) -> tuple[list[str], set[str]]:
        """(the titles above, the top first; the ids of everything above, reachable or not)."""
        titles: list[str] = []
        ids: set[str] = set()
        ref = parent
        for _ in range(MAX_DEPTH):
            if ref is None or ref.id is None or ref.id in ids:
                break
            ids.add(ref.id)
            node = self.node(ref)
            if node is None:
                break
            if node.title is not None:
                titles.append(node.title)
            ref = node.parent
        return titles[::-1], ids


class _People:
    """Who acted: the id, and the name and type when the integration may read people, each asked
    once a run; `role` owner or other when the owner is known."""

    def __init__(self, client: _Client, owner: str | None) -> None:
        self.client = client
        self.owner = owner
        self.users: dict[str, dict[str, Any] | None] = {}
        self.forbidden = False
        self.seen: dict[str, str | None] = {}  # every person who acted this run, with their name

    def actor(self, ref: object, counts: dict[str, int]) -> dict[str, Any] | None:
        user_id = _id(ref.get("id")) if isinstance(ref, dict) else None
        if user_id is None:
            return None
        actor: dict[str, Any] = {"id": user_id}
        user = self._user(user_id)
        name = _text(user.get("name")) if user is not None else None
        if name is not None:
            actor["name"] = name
        else:
            _count(counts, "actor_unnamed")
        self.seen.setdefault(user_id, name)
        kind = user.get("type") if user is not None else None
        if kind in ("person", "bot"):
            actor["type"] = kind
        if self.owner is not None:
            actor["role"] = OWNER if user_id == self.owner else OTHER
        else:
            _count(counts, "actor_unmarked")
        return actor

    def _user(self, user_id: str) -> dict[str, Any] | None:
        if self.forbidden:
            return None
        if user_id not in self.users:
            try:
                self.users[user_id] = self.client.get(f"/users/{user_id}")
            except _Unreachable as e:
                self.users[user_id] = None
                self.forbidden = e.status == 403  # the integration may not read people: ask no more
        return self.users[user_id]


# -- what the record already says ------------------------------------------------------------------------


@dataclass(frozen=True)
class _Seen:
    """A page as its lines in the record have it: their keys, the latest edit any of them saw, and
    the parent, path, word count and properties of the latest line that carries each."""

    keys: frozenset[str] = frozenset()
    modified: datetime | None = None
    parent: dict[str, Any] | None = None
    path: list[Any] | None = None
    words: int | None = None
    properties: dict[str, Any] | None = None

    @classmethod
    def of(cls, payloads: Iterable[dict[str, Any]]) -> _Seen:
        keys: set[str] = set()
        modified: datetime | None = None
        parent = path = words = properties = None
        for payload in payloads:
            if isinstance(payload.get("raw_id"), str):
                keys.add(payload["raw_id"])
            when = _instant(payload.get("modified_at"))
            if when is not None and (modified is None or when > modified):
                modified = when
            extra = payload.get("extra")
            if not isinstance(extra, dict):
                continue
            if isinstance(extra.get("parent"), dict):
                parent = extra["parent"]
                path = extra.get("path") if isinstance(extra.get("path"), list) else []
            body = extra.get("body")
            if isinstance(body, dict) and isinstance(body.get("words"), int):
                words = body["words"]
            if isinstance(extra.get("properties"), dict):
                properties = extra["properties"]
        return cls(frozenset(keys), modified, parent, path, words, properties)


# -- the lines -------------------------------------------------------------------------------------------


def _drafts(
    page: _Page,
    seen: _Seen,
    floor: datetime | None,
    zone: ZoneInfo,
    config: Config,
    tree: _Tree,
    people: _People,
    bodies: _Bodies,
    counts: dict[str, int],
) -> Iterator[dict[str, Any]]:
    """The page's lines this run: `created`, then the action at its last edit (module docstring)."""
    path, above = tree.above(page.parent)
    if config.roots and page.id not in config.roots and not above.intersection(config.roots):
        _count(counts, "skipped_outside_roots")
        return
    created_day = _day(page.created, zone)
    edited_day = _day(page.edited, zone)
    with_created = floor is None or page.created >= floor
    created_new = with_created and _raw_id(page.id, created_day, CREATED) not in seen.keys
    parent = page.parent.to_json() if page.parent is not None else None
    action: str | None = None
    if seen.modified is None or seen.modified < page.edited:  # an edit the record has not seen
        if page.archived:
            action = ARCHIVED
        elif seen.parent is not None and parent is not None and seen.parent != parent:
            action = MOVED
        else:
            action = EDITED
    folded = action == EDITED and created_new and edited_day == created_day
    if folded:
        action = None  # the creation day's edit: the created line holds the page as it is
    if with_created:
        state = _state(bodies, page, seen, counts) if folded else None
        actor = people.actor(page.created_by, counts)
        yield _line(page, CREATED, page.created, created_day, path, parent, actor, state, counts)
    if action is not None:
        known = _raw_id(page.id, edited_day, action) in seen.keys  # the record refuses it: fetch nothing
        state = None if known else _state(bodies, page, seen, counts)
        actor = people.actor(page.edited_by, counts)
        line = _line(page, action, page.edited, edited_day, path, parent, actor, state, counts)
        if action == MOVED:
            line["payload"]["extra"]["moved_from"] = {"parent": seen.parent, "path": seen.path or []}
        yield line


def _state(bodies: _Bodies, page: _Page, seen: _Seen, counts: dict[str, int]) -> dict[str, Any]:
    """The page as it is now: its body's digest and word count, its properties, what changed."""
    state: dict[str, Any] = {}
    body = bodies.of(page.id, counts)
    if body is not None:
        if seen.words is not None and "words" in body:
            body["words_delta"] = body["words"] - seen.words
        state["body"] = body
    if page.properties:
        state["properties"] = page.properties
        changed = _changed(seen.properties, page.properties)
        if changed:
            state["changed"] = changed
    return state


def _line(
    page: _Page,
    action: str,
    at: datetime,
    day: str,
    path: list[str],
    parent: dict[str, Any] | None,
    actor: dict[str, Any] | None,
    state: dict[str, Any] | None,
    counts: dict[str, int],
) -> dict[str, Any]:
    """One draft: the page's reference, where it is, who acted, and its state when it holds it."""
    payload: dict[str, Any] = {"schema": SCHEMA, "raw_id": _raw_id(page.id, day, action)}
    if page.title is not None:
        payload["title"] = page.title
    else:
        _count(counts, "no_title")
    payload["calendar"] = dict(CALENDAR)
    payload["all_day"] = False
    payload["modified_at"] = _stamp(page.edited)
    reference: dict[str, Any] = {"id": page.id}
    if page.url is not None:
        reference["url"] = page.url
    extra: dict[str, Any] = {"action": action, "page": reference, "path": path}
    if parent is not None:
        extra["parent"] = parent
    if actor is not None:
        extra["actor"] = actor
    extra.update(state or {})
    payload["extra"] = extra
    return {
        "at": _stamp(at),
        "end": None,
        "tz": None,  # the record's own
        "source": NAME,
        "kind": KIND,
        "tier": TIER,
        "payload": payload,
    }


def _raw_id(page_id: str, day: str, action: str) -> str:
    return f"{page_id}/{day}/{action}"


def _changed(before: dict[str, Any] | None, now: dict[str, Any]) -> list[dict[str, Any]]:
    """`[{name, old, new}]` for each property whose value differs from the page's previous line;
    nothing when the record has no previous properties to compare with."""
    if before is None:
        return []
    return [
        {"name": name, "old": before.get(name), "new": now.get(name)}
        for name in sorted(set(before) | set(now))
        if before.get(name) != now.get(name)
    ]


def _properties(raw: object) -> dict[str, Any]:
    """A row's status, select, multi-select, date and checkbox values by name, sorted; nothing else."""
    if not isinstance(raw, dict):
        return {}
    found: dict[str, Any] = {}
    for name, prop in raw.items():
        kind = prop.get("type") if isinstance(prop, dict) else None
        if not isinstance(name, str) or kind not in PROPERTY_TYPES:
            continue
        value = prop.get(kind)
        if kind in ("status", "select"):
            found[name] = _text(value.get("name")) if isinstance(value, dict) else None
        elif kind == "multi_select":
            options = value if isinstance(value, list) else []
            found[name] = [
                o["name"] for o in options if isinstance(o, dict) and isinstance(o.get("name"), str)
            ]
        elif kind == "date":
            found[name] = (
                {"start": value.get("start"), "end": value.get("end")} if isinstance(value, dict) else None
            )
        else:
            found[name] = bool(value)
    return dict(sorted(found.items()))


class _Bodies:
    """A page's text as its digest and word count, read through its blocks and never kept; each
    block type the API withholds is said once a run, by type, never by page."""

    def __init__(self, client: _Client, notice: Callable[[str], None] | None) -> None:
        self.client = client
        self.notice = notice
        self.withheld: set[str] = set()

    def of(self, page_id: str, counts: dict[str, int]) -> dict[str, Any] | None:
        """The digest of the page's text and its words; `{unavailable: ...}` when a block is withheld
        or deleted while the page is read; None when the integration may not read the blocks."""
        try:
            text = "\n".join(_text_of(self.client, page_id, 0))
        except _Withheld as e:
            _count(counts, "body_withheld")
            if e.block_type not in self.withheld:
                self.withheld.add(e.block_type)
                if self.notice is not None:
                    self.notice(
                        f"Notion's API withholds {e.block_type} blocks from integrations: a page that"
                        " holds one is written with its body unavailable"
                    )
            return {"unavailable": WITHHELD}
        except _Unreachable as e:
            if e.status != 404:
                return None
            _count(counts, "body_not_found")
            return {"unavailable": NOT_FOUND}
        data = text.encode("utf-8")
        return {
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "media_type": "text/plain",
            "words": len(text.split()),
        }


def _text_of(client: _Client, block_id: str, depth: int) -> list[str]:
    """The text of every block under `block_id`, depth first, one string per block that has any; a
    child page or database is its own page and is passed over."""
    out: list[str] = []
    for results in client.pages_of(f"/blocks/{block_id}/children"):
        for item in results:
            if not isinstance(item, dict):
                continue
            kind = item.get("type")
            if kind in ("child_page", "child_database"):
                continue
            text = _block_text(kind, item.get(kind) if isinstance(kind, str) else None)
            if text:
                out.append(text)
            child = _id(item.get("id"))
            if item.get("has_children") and child is not None and depth < MAX_DEPTH:
                out.extend(_text_of(client, child, depth + 1))
    return out


def _block_text(kind: object, content: object) -> str:
    if not isinstance(content, dict):
        return ""
    if kind == "table_row":
        cells = content.get("cells")
        return "\t".join(_plain(cell) for cell in cells) if isinstance(cells, list) else ""
    if kind == "equation":
        expression = content.get("expression")
        return expression if isinstance(expression, str) else ""
    return _plain(content.get("rich_text"))


def _page_title(item: dict[str, Any]) -> str | None:
    """The text of the page's title property, whatever the database calls it; None when empty."""
    properties = item.get("properties")
    if not isinstance(properties, dict):
        return None
    for prop in properties.values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            return _plain(prop.get("title")).strip() or None
    return None


def _plain(rich: object) -> str:
    """Notion's rich text as its plain text."""
    if not isinstance(rich, list):
        return ""
    return "".join(
        r["plain_text"] for r in rich if isinstance(r, dict) and isinstance(r.get("plain_text"), str)
    )


def _id(value: object) -> str | None:
    return notion_id(value) if isinstance(value, str) else None


def _text(value: object) -> str | None:
    """A non-blank string, stripped; anything else is None."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def _instant(value: object) -> datetime | None:
    """An RFC 3339 instant (Notion's `2026-03-01T07:00:00.000Z`, the record's `…:00Z`) in UTC."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        when = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC)


def _stamp(when: datetime) -> str:
    """The record's spelling: UTC to the second, `Z`."""
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _day(when: datetime, zone: ZoneInfo) -> str:
    return when.astimezone(zone).date().isoformat()
