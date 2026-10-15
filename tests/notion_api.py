"""An in-process fake of the Notion API, on the loopback interface, for `logbook sync notion`.

It serves the calls the source makes, in the shapes Notion's public API (version 2022-06-28) gives:
`GET /v1/users/me`, `GET /v1/users/{id}`, `POST /v1/search` (pages only, newest edit first, paged by
`start_cursor`), `GET /v1/pages/{id}`, `GET /v1/pages/{id}/properties/{property id}` (a relation's
references, paged, as `property_item`s), `GET /v1/databases/{id}`, `GET /v1/blocks/{id}` and `GET
/v1/blocks/{id}/children` (paged). A page keeps a relation's every reference; served, a relation
holds the first `RELATION_LIMIT` and `has_more`, as Notion serves one. A test can hide every relation
property (`relations_hidden`), as the source saw rows before it read them. Every request is recorded
with its method, path, query and body;
anything else (a PATCH, a DELETE, a POST that is not a search) is answered 405 and never acted on, so
a test can hold the client to reading. `throttle` answers 429 with `Retry-After` to the next N
requests of a path; `refuse` answers a path with one error every time. Pages are served `page_size`
at a time, at most `PAGE` here, so every walk pages. A block of a type Notion withholds from
integrations (`WITHHELD`, such as `ai_block`) is never served: the page of children that would hold
it answers 400 `validation_error`, as Notion does.

Everything is synthetic: Ines Nordmann of Oslo, her brother Ola, their pages. Nobody in it is real.
"""

from __future__ import annotations

import copy
import json
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

TOKEN = "ntn_synthetic_token_not_a_real_one"
VERSION = "2022-06-28"
PAGE = 2  # results per page the fake serves, whatever the client asks: every list is paged
WITHHELD = frozenset({"ai_block"})  # block types Notion refuses to give an integration
RELATION_LIMIT = 25  # references a page object's relation holds; the rest through the property endpoint


def uid(n: int) -> str:
    """A synthetic Notion id, dashed as the API spells one."""
    return f"{n:08x}-0000-4000-8000-{n:012x}"


INES, OLA, BOT = uid(0xA1), uid(0xA2), uid(0xB0)
RESEARCH, BOATS, SAIL_PLAN, OLD_NOTES, IDEAS, PACKING = uid(1), uid(2), uid(3), uid(4), uid(5), uid(6)
TASKS, FERRY, COLUMN = uid(10), uid(11), uid(20)
UNSHARED = uid(99)  # a page the integration was never given: 404 to every call
NOTES, AREAS, SERVICE = uid(30), uid(31), uid(12)  # `notes_workspace`: two databases and a task
SEAMANSHIP, ALLOTMENT, WORKSHOP = uid(32), uid(33), uid(34)  # rows of Areas
ENGINE, SHELVES, LOOSE = uid(40), uid(41), uid(42)  # rows of Notes
AREAS_ID, NOTES_ID = "ar%3Bs", "n%3Ft"  # relation property ids, as Notion spells them: URL-encoded
AREA_NAMES = {SEAMANSHIP: "Seamanship", ALLOTMENT: "Allotment", WORKSHOP: "Workshop"}

USERS: dict[str, dict[str, Any]] = {
    INES: {
        "object": "user",
        "id": INES,
        "type": "person",
        "name": "Ines Nordmann",
        "avatar_url": "https://example.org/avatar/ines.png",
        "person": {"email": "ines.nordmann@example.org"},
    },
    OLA: {
        "object": "user",
        "id": OLA,
        "type": "person",
        "name": "Ola Nordmann",
        "avatar_url": None,
        "person": {"email": "ola@example.org"},
    },
    BOT: {"object": "user", "id": BOT, "type": "bot", "name": "Importer", "bot": {}},
}


def stamp(text: str) -> str:
    """`2026-03-01T07:00Z` as Notion spells an instant: milliseconds, `Z`."""
    when = datetime.strptime(text, "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)
    return when.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def rich(text: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "text",
            "text": {"content": text, "link": None},
            "annotations": {"bold": False, "italic": False, "code": False, "color": "default"},
            "plain_text": text,
            "href": None,
        }
    ]


def parent_of(kind: str, of: str | None = None) -> dict[str, Any]:
    if kind == "workspace":
        return {"type": "workspace", "workspace": True}
    return {"type": f"{kind}_id", f"{kind}_id": of}


def page(
    page_id: str,
    title: str,
    parent: dict[str, Any],
    created: str,
    edited: str,
    created_by: str = INES,
    edited_by: str = INES,
    properties: dict[str, Any] | None = None,
    archived: bool = False,
) -> dict[str, Any]:
    slug = "-".join(title.split())
    props = {"title": {"id": "title", "type": "title", "title": rich(title)}}
    if properties is not None:  # a database row: its title property is the database's own name for it
        props = {"Name": {"id": "title", "type": "title", "title": rich(title)}, **properties}
    return {
        "object": "page",
        "id": page_id,
        "created_time": stamp(created),
        "last_edited_time": stamp(edited),
        "created_by": {"object": "user", "id": created_by},
        "last_edited_by": {"object": "user", "id": edited_by},
        "cover": {"type": "file", "file": {"url": "https://files.example.org/signed/cover.png?X-Amz=1"}},
        "icon": {"type": "emoji", "emoji": "⛵"},
        "parent": parent,
        "archived": archived,
        "in_trash": archived,
        "properties": props,
        "url": f"https://www.notion.so/{slug}-{page_id.replace('-', '')}",
        "public_url": f"https://public.example.org/{slug}-{page_id.replace('-', '')}",
    }


def status(name: str) -> dict[str, Any]:
    return {"id": "st", "type": "status", "status": {"id": f"s-{name}", "name": name, "color": "blue"}}


def select(name: str) -> dict[str, Any]:
    return {"id": "ty", "type": "select", "select": {"id": f"o-{name}", "name": name, "color": "green"}}


def relation(property_id: str, *ids: str) -> dict[str, Any]:
    """A relation property as the workspace keeps it: every reference (served, the first
    `RELATION_LIMIT`)."""
    return {"id": property_id, "type": "relation", "relation": [{"id": i} for i in ids], "has_more": False}


def rollup(property_id: str, count: int) -> dict[str, Any]:
    """A rollup over a relation: a number Notion computes, which a line never carries."""
    return {
        "id": property_id,
        "type": "rollup",
        "rollup": {"type": "number", "number": count, "function": "count"},
    }


def row_properties(state: str, due: str) -> dict[str, Any]:
    """A task row: the documented few (status, a date, select fields, a checkbox) and the ones a line
    never carries (a phone number, text, a person, a number)."""
    return {
        "Status": status(state),
        "Due": {"id": "du", "type": "date", "date": {"start": due, "end": None, "time_zone": None}},
        "Tags": {"id": "tg", "type": "multi_select", "multi_select": [{"id": "t1", "name": "travel"}]},
        "Priority": {"id": "pr", "type": "select", "select": {"id": "p1", "name": "High"}},
        "Done": {"id": "dn", "type": "checkbox", "checkbox": False},
        "Phone": {"id": "ph", "type": "phone_number", "phone_number": "07700 900123"},
        "Notes": {"id": "nt", "type": "rich_text", "rich_text": rich("ask Ola about the car")},
        "Assignee": {"id": "as", "type": "people", "people": [USERS[OLA]]},
        "Cost": {"id": "co", "type": "number", "number": 420},
    }


def block(block_id: str, kind: str, text: str | None = None, children: int = 0) -> dict[str, Any]:
    body: dict[str, Any] = {"rich_text": rich(text) if text is not None else [], "color": "default"}
    if kind == "child_page":
        body = {"title": text or ""}
    return {
        "object": "block",
        "id": block_id,
        "type": kind,
        "has_children": children > 0,
        "archived": False,
        kind: body,
    }


SAIL_PLAN_TEXT = (
    "Leave Oslo at nine.",
    "Fuel at Drøbak before noon.",
    "Anchor off Hvaler if the wind holds.",
)


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, str]
    body: Any
    headers: dict[str, str]


@dataclass
class FakeNotion:
    """The workspace and the server. `pages`, `databases`, `children` and `blocks` are the state a
    test edits between runs; `requests` what the client asked."""

    pages: dict[str, dict[str, Any]] = field(default_factory=dict)
    databases: dict[str, dict[str, Any]] = field(default_factory=dict)
    blocks: dict[str, dict[str, Any]] = field(default_factory=dict)
    children: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    users: dict[str, dict[str, Any]] = field(default_factory=lambda: copy.deepcopy(USERS))
    me_owner: dict[str, Any] = field(default_factory=lambda: {"type": "workspace", "workspace": True})
    users_forbidden: bool = False
    requests: list[Request] = field(default_factory=list)
    throttle: dict[str, int] = field(default_factory=dict)  # path → how many more refusals it answers
    throttle_status: int = 429  # the refusal: 429, or a 5xx
    retry_after: str = "7"
    refuse: dict[str, tuple[int, str, str]] = field(default_factory=dict)  # path → (status, code, message)
    relations_hidden: bool = False  # serve pages without their relation properties

    def __post_init__(self) -> None:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _send(self, code: int, doc: Any, headers: dict[str, str] | None = None) -> None:
                data = json.dumps(doc).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(data)

            def _handle(self) -> None:
                url = urlsplit(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                body = json.loads(raw.decode("utf-8")) if raw else None
                query = {k: v[-1] for k, v in parse_qs(url.query).items()}
                fake.requests.append(
                    Request(
                        self.command, url.path, query, body, {k.lower(): v for k, v in self.headers.items()}
                    )
                )
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    self._send(401, _error(401, "unauthorized", "API token is invalid."))
                    return
                if self.headers.get("Notion-Version") != VERSION:
                    self._send(
                        400, _error(400, "missing_version", "Notion-Version header failed validation.")
                    )
                    return
                left = fake.throttle.get(url.path, 0)
                if left > 0:
                    fake.throttle[url.path] = left - 1
                    self._send(
                        fake.throttle_status,
                        _error(fake.throttle_status, "rate_limited", "You have been rate limited."),
                        {"Retry-After": fake.retry_after},
                    )
                    return
                if url.path in fake.refuse:
                    refused, name, message = fake.refuse[url.path]
                    self._send(refused, _error(refused, name, message))
                    return
                code, doc = fake.answer(self.command, url.path, query, body)
                self._send(code, doc)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _handle

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    # -- the server ----------------------------------------------------------------------------------

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}/v1"

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def methods(self) -> set[tuple[str, str]]:
        """(method, route) of every request, ids replaced by `{id}`: what the client did."""
        out = set()
        for r in self.requests:
            parts = ["{id}" if len(p) == 36 and p.count("-") == 4 else p for p in r.path.split("/")]
            out.add((r.method, "/".join(parts)))
        return out

    def answer(self, method: str, path: str, query: dict[str, str], body: Any) -> tuple[int, Any]:
        parts = [unquote(p) for p in path.split("/") if p]
        if parts[:1] != ["v1"]:
            return 404, _error(404, "invalid_request_url", "Invalid request URL.")
        parts = parts[1:]
        if method == "POST" and parts == ["search"]:
            return 200, self._search(body if isinstance(body, dict) else {})
        if method != "GET":
            return 405, _error(405, "invalid_request", "This fake only reads.")
        if parts == ["users", "me"]:
            return 200, {
                "object": "user",
                "id": BOT,
                "type": "bot",
                "name": "Logbook",
                "bot": {"owner": self.me_owner, "workspace_name": "Ines's notes"},
            }
        if len(parts) == 2 and parts[0] == "users":
            if self.users_forbidden:
                return 403, _error(403, "restricted_resource", "Insufficient permissions for this endpoint.")
            found = self.users.get(parts[1])
            return (200, found) if found else (404, _error(404, "object_not_found", "Could not find user."))
        if len(parts) == 2 and parts[0] == "pages":
            found = self.pages.get(parts[1])
            return (200, self._served(found)) if found else (404, _not_found("page", parts[1]))
        if len(parts) == 4 and parts[0] == "pages" and parts[2] == "properties":
            return self._property(parts[1], parts[3], query)
        if len(parts) == 2 and parts[0] == "databases":
            found = self.databases.get(parts[1])
            return (200, found) if found else (404, _not_found("database", parts[1]))
        if len(parts) == 2 and parts[0] == "blocks":
            found = self.blocks.get(parts[1])
            return (200, found) if found else (404, _not_found("block", parts[1]))
        if len(parts) == 3 and parts[0] == "blocks" and parts[2] == "children":
            if parts[1] not in self.pages and parts[1] not in self.blocks:
                return 404, _not_found("block", parts[1])
            rows = self.children.get(parts[1], [])
            served = _page_of(rows, query.get("start_cursor"), int(query.get("page_size") or 100), "block")
            for row in served["results"]:
                if row["type"] in WITHHELD:
                    return 400, _error(
                        400,
                        "validation_error",
                        f"Block type {row['type']} is not supported via the API for your bot type.",
                    )
            return 200, served
        return 404, _error(404, "invalid_request_url", "Invalid request URL.")

    def _search(self, body: dict[str, Any]) -> dict[str, Any]:
        wanted = (body.get("filter") or {}).get("value")
        rows: list[dict[str, Any]] = []
        if wanted in (None, "page"):
            rows += [self._served(p) for p in self.pages.values()]
        if wanted in (None, "database"):
            rows += list(self.databases.values())
        sort = body.get("sort") or {}
        rows.sort(
            key=lambda r: (r["last_edited_time"], r["id"]), reverse=sort.get("direction") != "ascending"
        )
        return _page_of(rows, body.get("start_cursor"), int(body.get("page_size") or 100), "page_or_database")

    def _served(self, kept: dict[str, Any]) -> dict[str, Any]:
        """A page as Notion serves it: a relation's first `RELATION_LIMIT` references and
        `has_more`; none at all while `relations_hidden`."""
        served = copy.deepcopy(kept)
        properties = served.get("properties") or {}
        for name in list(properties):
            prop = properties[name]
            if prop.get("type") != "relation":
                continue
            if self.relations_hidden:
                del properties[name]
                continue
            if isinstance(prop["relation"], list):  # a test may break one on purpose: served as it is
                prop["has_more"] = len(prop["relation"]) > RELATION_LIMIT
                prop["relation"] = prop["relation"][:RELATION_LIMIT]
        return served

    def _property(self, page_id: str, property_id: str, query: dict[str, str]) -> tuple[int, Any]:
        """`GET /v1/pages/{id}/properties/{property id}` for a relation: every reference, paged, one
        `property_item` each. The property id arrives decoded; the page keeps it as Notion spells it."""
        kept = self.pages.get(page_id)
        if kept is None:
            return 404, _not_found("page", page_id)
        found = next(
            (
                p
                for p in (kept.get("properties") or {}).values()
                if unquote(p.get("id", "")) == property_id and not self.relations_hidden
            ),
            None,
        )
        if found is None or found.get("type") != "relation":
            return 404, _error(404, "object_not_found", f"Could not find property with ID: {property_id}.")
        refs = found["relation"]
        cursor = query.get("start_cursor")
        start = int(cursor.removeprefix("ref-")) if cursor else 0  # every item has the property's id
        end = start + min(int(query.get("page_size") or 100), PAGE)
        return 200, {
            "object": "list",
            "results": [
                {
                    "object": "property_item",
                    "id": found["id"],
                    "type": "relation",
                    "relation": {"id": r.get("id")},
                }
                for r in refs[start:end]
            ],
            "next_cursor": f"ref-{end}" if end < len(refs) else None,
            "has_more": end < len(refs),
            "type": "property_item",
            "property_item": {"id": found["id"], "next_url": None, "type": "relation", "relation": {}},
        }

    # -- the workspace, as a test changes it -----------------------------------------------------------

    def edit(self, page_id: str, at: str, by: str = INES, **changes: Any) -> None:
        p = self.pages[page_id]
        p["last_edited_time"] = stamp(at)
        p["last_edited_by"] = {"object": "user", "id": by}
        for key, value in changes.items():
            p[key] = value

    def set_status(self, page_id: str, name: str, at: str, by: str = INES) -> None:
        self.pages[page_id]["properties"]["Status"] = status(name)
        self.edit(page_id, at, by)

    def relate(self, page_id: str, name: str, ids: list[str], at: str, by: str = INES) -> None:
        """The row's relation `name` now references `ids`, in that order: an edit."""
        self.pages[page_id]["properties"][name]["relation"] = [{"id": i} for i in ids]
        self.edit(page_id, at, by)

    def write(self, page_id: str, *paragraphs: str) -> None:
        """The page's body becomes these paragraphs."""
        base = 0x10000 * (1 + list(self.pages).index(page_id))
        self.children[page_id] = [
            block(uid(base + n), "paragraph", text) for n, text in enumerate(paragraphs)
        ]


def _error(code: int, name: str, message: str) -> dict[str, Any]:
    return {"object": "error", "status": code, "code": name, "message": message}


def _not_found(kind: str, object_id: str) -> dict[str, Any]:
    return _error(
        404,
        "object_not_found",
        f"Could not find {kind} with ID: {object_id}. Make sure the relevant pages and databases are shared"
        " with your integration.",
    )


def _page_of(rows: list[dict[str, Any]], cursor: str | None, size: int, kind: str) -> dict[str, Any]:
    """`size` (at most PAGE) results from `cursor`, the id of the first one to serve."""
    start = 0
    if cursor is not None:
        ids = [r["id"] for r in rows]
        start = ids.index(cursor) if cursor in ids else len(rows)
    served = rows[start : start + min(size, PAGE)]
    following = rows[start + len(served) :]
    return {
        "object": "list",
        "results": copy.deepcopy(served),
        "next_cursor": following[0]["id"] if following else None,
        "has_more": bool(following),
        "type": kind,
        kind: {},
    }


def workspace() -> FakeNotion:
    """Ines's workspace as the integration sees it, in March 2026 (Oslo is UTC+1).

    - Research, a top-level page > Boats > Sail plan (Ola edited it last); Research > Old notes,
      untouched since 2025; Research > a column block > Packing list, made at 23:30 UTC on 1 March,
      which is 2 March in Oslo.
    - Tasks, a database at the top > Book the ferry, a row with a status, a date, select fields and
      a checkbox, and a phone number, text, a person and a number a line never carries.
    - Ideas, a top-level page Ines archived.
    """
    fake = FakeNotion()
    top = parent_of("workspace")
    fake.pages[RESEARCH] = page(RESEARCH, "Research", top, "2026-02-01T09:00Z", "2026-02-20T10:00Z")
    fake.pages[BOATS] = page(
        BOATS, "Boats", parent_of("page", RESEARCH), "2026-02-03T08:00Z", "2026-02-03T15:30Z"
    )
    fake.pages[SAIL_PLAN] = page(
        SAIL_PLAN,
        "Sail plan",
        parent_of("page", BOATS),
        "2026-03-01T07:00Z",
        "2026-03-02T10:15Z",
        edited_by=OLA,
    )
    fake.pages[OLD_NOTES] = page(
        OLD_NOTES, "Old notes", parent_of("page", RESEARCH), "2025-12-01T12:00Z", "2025-12-01T12:30Z"
    )
    fake.pages[IDEAS] = page(IDEAS, "Ideas", top, "2026-02-10T18:00Z", "2026-03-02T11:00Z", archived=True)
    fake.databases[TASKS] = {
        "object": "database",
        "id": TASKS,
        "created_time": stamp("2026-01-15T09:00Z"),
        "last_edited_time": stamp("2026-01-15T09:00Z"),
        "title": rich("Tasks"),
        "parent": top,
        "archived": False,
        "in_trash": False,
        "properties": {},
        "url": f"https://www.notion.so/{TASKS.replace('-', '')}",
    }
    fake.pages[FERRY] = page(
        FERRY,
        "Book the ferry",
        parent_of("database", TASKS),
        "2026-03-01T08:00Z",
        "2026-03-02T09:00Z",
        properties=row_properties("Doing", "2026-03-05"),
    )
    fake.blocks[COLUMN] = {**block(COLUMN, "column", children=1), "parent": parent_of("page", RESEARCH)}
    fake.pages[PACKING] = page(
        PACKING, "Packing list", parent_of("block", COLUMN), "2026-03-01T23:30Z", "2026-03-01T23:40Z"
    )
    fake.write(PACKING, "Oilskins, two jumpers, the chart of Oslofjord.")
    nested = uid(0x300)
    fake.children[SAIL_PLAN] = [
        block(uid(0x301), "heading_2", "Plan"),
        block(uid(0x302), "paragraph", SAIL_PLAN_TEXT[0]),
        block(nested, "toggle", SAIL_PLAN_TEXT[1], children=1),
        block(uid(0x303), "child_page", "Crew list"),  # its own page: never read as this one's body
    ]
    fake.blocks[nested] = block(nested, "toggle", SAIL_PLAN_TEXT[1], children=1)
    fake.children[nested] = [block(uid(0x304), "paragraph", SAIL_PLAN_TEXT[2])]
    fake.children[FERRY] = [block(uid(0x310), "to_do", "Compare the two crossings")]
    fake.write(BOATS, "Notes on the boats we looked at.")
    return fake


def database(database_id: str, title: str, created: str) -> dict[str, Any]:
    """A database at the top of the workspace, as `GET /v1/databases/{id}` gives it."""
    return {
        "object": "database",
        "id": database_id,
        "created_time": stamp(created),
        "last_edited_time": stamp(created),
        "title": rich(title),
        "parent": parent_of("workspace"),
        "archived": False,
        "in_trash": False,
        "properties": {},
        "url": f"https://www.notion.so/{database_id.replace('-', '')}",
    }


def note_properties(kind: str, *areas: str) -> dict[str, Any]:
    """A Notes row: its Type, its Areas (a relation to rows of Areas), a rollup counting them, a
    rollup showing their titles and a formula spelling them: the related rows' titles as Notion
    serves them on this row, which a line never carries."""
    names = [AREA_NAMES.get(a, "") for a in areas]
    return {
        "Type": select(kind),
        "Areas": relation(AREAS_ID, *areas),
        "Area count": rollup("rc", len(areas)),
        "Area names": {
            "id": "rn",
            "type": "rollup",
            "rollup": {
                "type": "array",
                "array": [{"type": "title", "title": rich(n)} for n in names],
                "function": "show_original",
            },
        },
        "Area label": {
            "id": "fl",
            "type": "formula",
            "formula": {"type": "string", "string": ", ".join(names)},
        },
    }


def notes_workspace() -> FakeNotion:
    """`workspace()` and Ines's notes, kept as database rows that link to other rows.

    - Areas, a database at the top: Seamanship, Allotment and Workshop, rows with a name only.
    - Notes, a database at the top, each row with a Type (a select), Areas (a relation to rows of
      Areas, in the order Ines put them) and a rollup counting them: Engine noise (Seamanship), made
      on 1 March and edited on 2 March; Garden shelves (Workshop, then Allotment), made and edited on
      2 March; Loose ends, with no area, made on 25 February.
    - Tasks gains a Notes relation: Service the engine, made on 2 March, links Engine noise; Book
      the ferry links none.
    """
    fake = workspace()
    fake.databases[AREAS] = database(AREAS, "Areas", "2026-01-20T09:00Z")
    fake.databases[NOTES] = database(NOTES, "Notes", "2026-01-20T09:05Z")
    for area, name in AREA_NAMES.items():
        fake.pages[area] = page(
            area, name, parent_of("database", AREAS), "2026-01-20T09:10Z", "2026-01-20T09:10Z", properties={}
        )
    in_notes = parent_of("database", NOTES)
    fake.pages[ENGINE] = page(
        ENGINE,
        "Engine noise",
        in_notes,
        "2026-03-01T10:00Z",
        "2026-03-02T08:00Z",
        properties=note_properties("Idea", SEAMANSHIP),
    )
    fake.pages[SHELVES] = page(
        SHELVES,
        "Garden shelves",
        in_notes,
        "2026-03-02T12:00Z",
        "2026-03-02T12:20Z",
        properties=note_properties("Idea", WORKSHOP, ALLOTMENT),
    )
    fake.pages[LOOSE] = page(
        LOOSE,
        "Loose ends",
        in_notes,
        "2026-02-25T18:00Z",
        "2026-02-25T18:00Z",
        properties=note_properties("Reference"),
    )
    fake.pages[SERVICE] = page(
        SERVICE,
        "Service the engine",
        parent_of("database", TASKS),
        "2026-03-02T13:00Z",
        "2026-03-02T13:00Z",
        properties={**row_properties("To do", "2026-03-10"), "Notes": relation(NOTES_ID, ENGINE)},
    )
    fake.pages[FERRY]["properties"]["Notes"] = relation(NOTES_ID)
    fake.write(ENGINE, "Knocking at low revs; check the mounts.")
    return fake
