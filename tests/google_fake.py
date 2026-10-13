"""An in-process fake of the Google endpoints the sources on the one service-account key call: the OAuth
token endpoint (a service account's signed assertion in, an access token out), the Drive Activity API v2
(`activity:query`), the Drive API v3's file metadata (`files.get`), the Tasks API v1 (task lists, tasks),
the Gmail API v1 (profile, labels, messages, history), the Calendar API v3 (calendar list, events), the
People API v1 (the owner's contacts and other contacts), the Meet REST API v2 (conference records, their
participants, transcripts and transcript entries, spaces) and the Admin SDK Reports API v1 (the login
audit log).
Nothing listens on a socket: the fake is a function with the shape of `service_account.send`, which a
test puts in its place, and every request it answers is recorded so a test can say what was asked.

The token endpoint checks what Google checks: the assertion is an RS256 JWT signed by the key the fake
was given, issued by the key's client email for the user it impersonates, for a scope the domain-wide
delegation grants, addressed to the token endpoint and valid for an hour at most. A scope not granted is
`unauthorized_client`, as Google says it. Every API call must carry a token the fake issued.

Every API answers only a token minted for its own scope, as Google does (`Request had insufficient
scopes`), and only GET, except the one POST the Activity API takes: a test reads `methods()` to see the
client never asked for anything else.

Everything is synthetic: the persona is Ines Nordmann of Oslo, `ines@example.org`; the people who share
her files are `people/1001` and `people/1002` as the API would name them; the service account is
`logbook-sync@example.org`. Nobody here exists."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from logbook.contrib.adapters import service_account

CLIENT_EMAIL = "logbook-sync@example.org"
USER = "ines@example.org"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.activity.readonly"
TASKS_SCOPE = "https://www.googleapis.com/auth/tasks.readonly"
METADATA_SCOPE = "https://www.googleapis.com/auth/drive.metadata.readonly"
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
CONTACTS_SCOPE = "https://www.googleapis.com/auth/contacts.readonly"
OTHER_CONTACTS_SCOPE = "https://www.googleapis.com/auth/contacts.other.readonly"
MEET_SCOPE = "https://www.googleapis.com/auth/meetings.space.readonly"
AUDIT_SCOPE = "https://www.googleapis.com/auth/admin.reports.audit.readonly"
SCOPES = {  # what the owner delegated
    DRIVE_SCOPE,
    TASKS_SCOPE,
    METADATA_SCOPE,
    GMAIL_SCOPE,
    CALENDAR_SCOPE,
    CONTACTS_SCOPE,
    OTHER_CONTACTS_SCOPE,
    MEET_SCOPE,
    AUDIT_SCOPE,
}
GMAIL = "gmail.googleapis.com/gmail/v1/users/me"
CALENDAR = "www.googleapis.com/calendar/v3"
FILES = "www.googleapis.com/drive/v3/files/"
PEOPLE = "people.googleapis.com/v1/"
MEET = "meet.googleapis.com/v2/"
LOGINS = "admin.googleapis.com/admin/reports/v1/activity/users/"
OLA, PER = "people/1001", "people/1002"  # as the Activity API names a person: a People API resource


def private_key() -> rsa.RSAPrivateKey:
    """A fresh key for one test session: never a key on disk in the repository."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def write_key(path: Path, key: rsa.RSAPrivateKey, client_email: str = CLIENT_EMAIL) -> Path:
    """A service-account key file as the Cloud console downloads one, at mode 600."""
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode("ascii")
    data = {
        "type": "service_account",
        "project_id": "oslo-logbook",
        "private_key_id": "synthetic-key-id",
        "private_key": pem,
        "client_email": client_email,
        "client_id": "synthetic-client-id",
        "token_uri": service_account.TOKEN_URL,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    path.chmod(0o600)
    return path


def _b64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _instant(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


@dataclass
class Fake:
    """The endpoints with their data. `drive` holds DriveActivity objects as the API returns them and
    `files` the Drive items by id (`{id, name, mimeType, parents}`); `lists` the task lists and `tasks`
    each list's tasks; `mail` the Gmail messages (`deliver` adds one, with its history record),
    `labels` the mailbox's labels and `history` its history records, oldest first, a start before
    `history_floor` being too old (404, as Gmail says it); `calendars` the calendar list and `events`
    each calendar's events, an `updatedMin` before `updated_min_floor` being too long ago (410). `page`
    is how many items one page holds whatever the client asks, so paging shows with a handful of items.
    `contacts` and `other_contacts` are People API person objects (`connections`, `otherContacts`);
    `conferences` Meet conference records, with `participants`, `transcripts` (per record name) and
    `entries` (per transcript name) below them and `spaces` by name; `logins` the login audit log's
    activities, every user's, the client asking for one user by address. `failures` are answered, in
    order, to the next API calls (never to the token endpoint): `(status, headers, body)`."""

    key: rsa.RSAPrivateKey
    delegated: set[str] = field(default_factory=lambda: set(SCOPES))
    drive: list[dict[str, Any]] = field(default_factory=list)
    files: dict[str, dict[str, Any]] = field(default_factory=dict)
    lists: list[dict[str, Any]] = field(default_factory=list)
    tasks: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    mail: list[dict[str, Any]] = field(default_factory=list)
    labels: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    history_id: int = 1000
    history_floor: int = 0
    calendars: list[dict[str, Any]] = field(default_factory=list)
    events: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    updated_min_floor: str | None = None
    contacts: list[dict[str, Any]] = field(default_factory=list)
    other_contacts: list[dict[str, Any]] = field(default_factory=list)
    conferences: list[dict[str, Any]] = field(default_factory=list)
    participants: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    transcripts: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    entries: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    spaces: dict[str, dict[str, Any]] = field(default_factory=dict)
    logins: list[dict[str, Any]] = field(default_factory=list)
    page: int = 3
    failures: list[tuple[int, dict[str, str], bytes]] = field(default_factory=list)
    requests: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    issued: dict[str, str] = field(default_factory=dict)  # token → scope
    assertions: list[dict[str, Any]] = field(default_factory=list)

    # -- what a test reads back ---------------------------------------------------------------

    def calls(self, path: str) -> list[dict[str, Any]]:
        """The parameters (query or JSON body) of every request to `path`, in order."""
        return [params for _method, p, params in self.requests if p == path]

    def methods(self) -> set[tuple[str, str]]:
        """Every (method, host) asked: what the client may do to Google, in one set."""
        return {(m, p.split("/")[0]) for m, p, _ in self.requests}

    def deliver(
        self,
        raw: bytes,
        when: datetime,
        labels: tuple[str, ...] = ("INBOX",),
        thread: int | None = None,
    ) -> str:
        """A message arriving in the mailbox: its id (hex, as Gmail's are), a history record that adds
        it, and the mailbox's history id moved on. `thread` is the thread's number (the API spells it
        in hex, IMAP's X-GM-THRID in decimal); the message's own when not given."""
        self.history_id += 1
        number = 0x18E0_0000_0000_0000 + len(self.mail) + 1
        message = {
            "id": f"{number:x}",
            "threadId": f"{thread if thread is not None else number:x}",
            "labelIds": list(labels),
            "internalDate": str(int(when.timestamp() * 1000)),
            "historyId": str(self.history_id),
            "sizeEstimate": len(raw),
            "raw": raw,
        }
        self.mail.append(message)
        self.history.append(
            {
                "id": str(self.history_id),
                "messages": [{"id": message["id"], "threadId": message["threadId"]}],
                "messagesAdded": [{"message": {k: message[k] for k in ("id", "threadId", "labelIds")}}],
            }
        )
        return str(message["id"])

    def fail(self, status: int, retry_after: str | None = None, reason: str | None = None) -> None:
        headers = {"retry-after": retry_after} if retry_after is not None else {}
        error: dict[str, Any] = {"code": status, "message": f"synthetic failure {status}"}
        if reason is not None:
            error["errors"] = [{"reason": reason, "message": reason}]
        self.failures.append((status, headers, json.dumps({"error": error}).encode("utf-8")))

    # -- the transport ------------------------------------------------------------------------

    def __call__(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float
    ) -> service_account.Response:
        parts = urlsplit(url)
        path = parts.netloc + unquote(parts.path)
        if url == service_account.TOKEN_URL:
            form = {k: v[0] for k, v in parse_qs((body or b"").decode("ascii")).items()}
            self.requests.append((method, path, {"grant_type": form.get("grant_type")}))
            return self._token(method, headers, form)
        params: dict[str, Any] = (
            json.loads(body) if body else {k: v[0] for k, v in parse_qs(parts.query).items()}
        )
        self.requests.append((method, path, params))
        if self.failures:
            status, more, text = self.failures.pop(0)
            return service_account.Response(status, more, text)
        scope = self.issued.get(headers.get("Authorization", "").removeprefix("Bearer "))
        if scope is None:
            return _json(401, {"error": {"code": 401, "message": "Request had invalid authentication."}})
        if path == "driveactivity.googleapis.com/v2/activity:query" and method == "POST":
            return self._activity(scope, params)
        if method != "GET":
            return _json(405, {"error": {"code": 405, "message": f"{method} is not allowed here"}})
        if path.startswith(GMAIL + "/"):
            return self._gmail(scope, path.removeprefix(GMAIL + "/"), params)
        if path.startswith(CALENDAR + "/"):
            return self._calendar(scope, path.removeprefix(CALENDAR + "/"), params)
        if path.startswith(FILES):
            return self._file(scope, path.removeprefix(FILES))
        if path.startswith(PEOPLE):
            return self._people(scope, path.removeprefix(PEOPLE), params)
        if path.startswith(MEET):
            return self._meet(scope, path.removeprefix(MEET), params)
        if path.startswith(LOGINS) and path.endswith("/applications/login"):
            user = path.removeprefix(LOGINS).removesuffix("/applications/login")
            return self._logins(scope, user, params)
        if path == "tasks.googleapis.com/tasks/v1/users/@me/lists" and method == "GET":
            return self._paged(scope, self.lists, params, "tasks#taskLists")
        if (
            path.startswith("tasks.googleapis.com/tasks/v1/lists/")
            and path.endswith("/tasks")
            and method == "GET"
        ):
            list_id = path.split("/")[-2]
            return self._tasks(scope, list_id, params)
        return _json(404, {"error": {"code": 404, "message": f"no such endpoint: {method} {path}"}})

    def _token(self, method: str, headers: dict[str, str], form: dict[str, str]) -> service_account.Response:
        if method != "POST" or form.get("grant_type") != service_account.GRANT:
            return _json(400, {"error": "unsupported_grant_type"})
        head, claims, signature = form["assertion"].split(".")
        try:
            self.key.public_key().verify(
                _b64(signature), f"{head}.{claims}".encode("ascii"), padding.PKCS1v15(), hashes.SHA256()
            )
        except Exception:
            return _json(400, {"error": "invalid_grant", "error_description": "Invalid JWT Signature."})
        header, body = json.loads(_b64(head)), json.loads(_b64(claims))
        self.assertions.append(body)
        if header.get("alg") != "RS256" or body.get("aud") != service_account.TOKEN_URL:
            return _json(400, {"error": "invalid_grant", "error_description": "Invalid JWT."})
        if body.get("iss") != CLIENT_EMAIL or body.get("sub") != USER:
            return _json(400, {"error": "invalid_grant", "error_description": "Invalid email or User ID"})
        if not 0 < body["exp"] - body["iat"] <= 3600:
            return _json(400, {"error": "invalid_grant", "error_description": "Invalid JWT: lifetime."})
        if body.get("scope") not in self.delegated:
            return _json(
                401,
                {
                    "error": "unauthorized_client",
                    "error_description": "Client is unauthorized to retrieve access tokens using this"
                    " method, or client not authorized for any of the scopes requested.",
                },
            )
        token = f"synthetic-token-{len(self.issued) + 1}"
        self.issued[token] = body["scope"]
        return _json(200, {"access_token": token, "expires_in": 3599, "token_type": "Bearer"})

    def _activity(self, scope: str, params: dict[str, Any]) -> service_account.Response:
        if scope != DRIVE_SCOPE:
            return _json(403, {"error": {"code": 403, "message": "Request had insufficient scopes."}})
        since, until = _window(str(params.get("filter") or ""))
        found = [
            a
            for a in sorted(self.drive, key=_activity_time, reverse=True)  # the API: newest first
            if (since is None or _activity_time(a) >= since) and (until is None or _activity_time(a) < until)
        ]
        start = int(params.get("pageToken") or 0)
        page: dict[str, Any] = {"activities": found[start : start + self.page]}
        if start + self.page < len(found):
            page["nextPageToken"] = str(start + self.page)
        return _json(200, page)

    def _paged(
        self, scope: str, items: list[dict[str, Any]], params: dict[str, Any], kind: str
    ) -> service_account.Response:
        if scope != TASKS_SCOPE:
            return _json(403, {"error": {"code": 403, "message": "Request had insufficient scopes."}})
        start = int(params.get("pageToken") or 0)
        page: dict[str, Any] = {"kind": kind, "items": items[start : start + self.page]}
        if start + self.page < len(items):
            page["nextPageToken"] = str(start + self.page)
        return _json(200, page)

    def _tasks(self, scope: str, list_id: str, params: dict[str, Any]) -> service_account.Response:
        if list_id not in self.tasks:
            return _json(404, {"error": {"code": 404, "message": "Task list not found."}})
        since = _instant(params["updatedMin"]) if params.get("updatedMin") else None
        shown = [
            t
            for t in self.tasks[list_id]
            if (since is None or _instant(t["updated"]) >= since)
            and (params.get("showDeleted") == "true" or not t.get("deleted"))
            and (params.get("showHidden") == "true" or not t.get("hidden"))
            and (params.get("showCompleted", "true") == "true" or t.get("status") != "completed")
        ]
        return self._paged(scope, shown, params, "tasks#tasks")

    # -- Gmail ----------------------------------------------------------------------------------

    def _gmail(self, scope: str, rest: str, params: dict[str, Any]) -> service_account.Response:
        if scope != GMAIL_SCOPE:
            return _insufficient()
        if rest == "profile":
            return _json(
                200,
                {
                    "emailAddress": USER,
                    "messagesTotal": len(self.mail),
                    "threadsTotal": len({m["threadId"] for m in self.mail}),
                    "historyId": str(self.history_id),
                },
            )
        if rest == "labels":
            return _json(200, {"labels": list(self.labels)})
        if rest == "messages":
            return self._messages(params)
        if rest.startswith("messages/"):
            return self._message(rest.removeprefix("messages/"), params)
        if rest == "history":
            return self._history(params)
        return _json(404, {"error": {"code": 404, "message": f"no such endpoint: {rest}"}})

    def _messages(self, params: dict[str, Any]) -> service_account.Response:
        after = None
        for term in str(params.get("q") or "").split():
            if term.startswith("after:"):
                after = int(term.removeprefix("after:"))
        hidden = set() if params.get("includeSpamTrash") == "true" else {"SPAM", "TRASH"}
        found = [
            m
            for m in sorted(self.mail, key=lambda m: int(m["internalDate"]), reverse=True)  # newest first
            if not hidden & set(m["labelIds"]) and (after is None or int(m["internalDate"]) // 1000 > after)
        ]
        start = int(params.get("pageToken") or 0)
        page: dict[str, Any] = {"resultSizeEstimate": len(found)}
        if found[start : start + self.page]:
            page["messages"] = [
                {"id": m["id"], "threadId": m["threadId"]} for m in found[start : start + self.page]
            ]
        if start + self.page < len(found):
            page["nextPageToken"] = str(start + self.page)
        return _json(200, page)

    def _message(self, message_id: str, params: dict[str, Any]) -> service_account.Response:
        message = next((m for m in self.mail if m["id"] == message_id), None)
        if message is None:
            return _json(404, {"error": {"code": 404, "message": "Requested entity was not found."}})
        shown = {
            k: message[k] for k in ("id", "threadId", "labelIds", "historyId", "internalDate", "sizeEstimate")
        }
        raw = bytes(message["raw"])
        if params.get("format") == "raw":
            shown["raw"] = base64.urlsafe_b64encode(raw).decode("ascii")
        elif params.get("format") == "metadata":
            wanted = {str(params.get("metadataHeaders") or "").lower()}
            head = raw.split(b"\r\n\r\n", 1)[0].decode("utf-8", "replace")
            headers = [
                {"name": name.strip(), "value": value.strip()}
                for name, _, value in (line.partition(":") for line in head.split("\r\n"))
                if name.strip().lower() in wanted
            ]
            shown["payload"] = {"mimeType": "multipart/mixed", "headers": headers}
        else:
            return _json(
                400, {"error": {"code": 400, "message": "the fake answers format=raw and format=metadata"}}
            )
        return _json(200, shown)

    def _history(self, params: dict[str, Any]) -> service_account.Response:
        start = int(params["startHistoryId"])
        if start < self.history_floor:
            return _json(
                404,
                {"error": {"code": 404, "message": "Requested entity was not found.", "status": "NOT_FOUND"}},
            )
        types = str(params.get("historyTypes") or "")
        records = [
            r
            if types != "messageAdded"
            else {k: v for k, v in r.items() if k in ("id", "messages", "messagesAdded")}
            for r in self.history
            if int(r["id"]) > start
        ]
        offset = int(params.get("pageToken") or 0)
        page: dict[str, Any] = {"historyId": str(self.history_id)}
        if records[offset : offset + self.page]:
            page["history"] = records[offset : offset + self.page]
        if offset + self.page < len(records):
            page["nextPageToken"] = str(offset + self.page)
        return _json(200, page)

    # -- Calendar -------------------------------------------------------------------------------

    def _calendar(self, scope: str, rest: str, params: dict[str, Any]) -> service_account.Response:
        if scope != CALENDAR_SCOPE:
            return _insufficient()
        if rest == "users/me/calendarList":
            shown = [
                c
                for c in self.calendars
                if params.get("minAccessRole") != "owner" or c.get("accessRole") == "owner"
            ]
            return self._page(shown, params, "calendar#calendarList")
        parts = rest.split("/")
        if len(parts) == 3 and parts[0] == "calendars" and parts[2] == "events":
            return self._events(parts[1], params)
        return _json(404, {"error": {"code": 404, "message": f"no such endpoint: {rest}"}})

    def _events(self, calendar_id: str, params: dict[str, Any]) -> service_account.Response:
        if calendar_id not in self.events:
            return _json(404, {"error": {"code": 404, "message": "Not Found"}})
        since = params.get("updatedMin")
        if since and self.updated_min_floor and _instant(since) < _instant(self.updated_min_floor):
            reason = "updatedMinTooLongAgo"
            message = "The requested minimum modification time lies too far in the past."
            error = {
                "code": 410,
                "message": message,
                "errors": [{"domain": "calendar", "reason": reason, "message": message}],
            }
            return _json(410, {"error": error})
        shown = [
            e
            for e in self.events[calendar_id]
            if (not since or _instant(e["updated"]) >= _instant(since))
            and (since or params.get("showDeleted") == "true" or e.get("status") != "cancelled")
        ]
        return self._page(shown, params, "calendar#events")

    def _page(
        self, items: list[dict[str, Any]], params: dict[str, Any], kind: str
    ) -> service_account.Response:
        start = int(params.get("pageToken") or 0)
        page: dict[str, Any] = {"kind": kind, "items": items[start : start + self.page]}
        if start + self.page < len(items):
            page["nextPageToken"] = str(start + self.page)
        return _json(200, page)

    # -- Drive metadata -------------------------------------------------------------------------

    def _file(self, scope: str, file_id: str) -> service_account.Response:
        if scope != METADATA_SCOPE:
            return _insufficient()
        found = self.files.get(file_id)
        if found is None:
            return _json(404, {"error": {"code": 404, "message": f"File not found: {file_id}."}})
        return _json(200, dict(found))

    # -- People ---------------------------------------------------------------------------------

    def _people(self, scope: str, rest: str, params: dict[str, Any]) -> service_account.Response:
        if rest == "people/me/connections":
            if scope != CONTACTS_SCOPE:
                return _insufficient()
            if not params.get("personFields"):
                return _json(400, {"error": {"code": 400, "message": "personMask is required."}})
            return self._listed(self.contacts, params, "connections", {"totalPeople": len(self.contacts)})
        if rest == "otherContacts":
            if scope != OTHER_CONTACTS_SCOPE:
                return _insufficient()
            if not params.get("readMask"):
                return _json(400, {"error": {"code": 400, "message": "readMask is required."}})
            extra = {"totalSize": len(self.other_contacts)}
            return self._listed(self.other_contacts, params, "otherContacts", extra)
        return _json(404, {"error": {"code": 404, "message": f"no such endpoint: {rest}"}})

    def _listed(
        self,
        items: list[dict[str, Any]],
        params: dict[str, Any],
        key: str,
        extra: dict[str, Any] | None = None,
    ) -> service_account.Response:
        """A page of `items` under `key`, the key left out when the page is empty, as Google's newer
        APIs answer."""
        start = int(params.get("pageToken") or 0)
        page: dict[str, Any] = dict(extra or {})
        if items[start : start + self.page]:
            page[key] = items[start : start + self.page]
        if start + self.page < len(items):
            page["nextPageToken"] = str(start + self.page)
        return _json(200, page)

    # -- Meet -----------------------------------------------------------------------------------

    def _meet(self, scope: str, rest: str, params: dict[str, Any]) -> service_account.Response:
        if scope != MEET_SCOPE:
            return _insufficient()
        parts = rest.split("/")
        if rest == "conferenceRecords":
            since = _start_filter(str(params.get("filter") or ""))
            found = [
                c
                for c in sorted(self.conferences, key=lambda c: _instant(c["startTime"]), reverse=True)
                if since is None or _instant(c["startTime"]) >= since
            ]
            return self._listed(found, params, "conferenceRecords")
        if len(parts) == 2 and parts[0] == "spaces":
            space = self.spaces.get(rest)
            if space is None:
                return _json(404, {"error": {"code": 404, "message": "Requested entity was not found."}})
            return _json(200, dict(space))
        record = "/".join(parts[:2])
        if parts[0] != "conferenceRecords" or not any(c["name"] == record for c in self.conferences):
            return _json(404, {"error": {"code": 404, "message": "Requested entity was not found."}})
        if len(parts) == 3 and parts[2] == "participants":
            return self._listed(self.participants.get(record, []), params, "participants")
        if len(parts) == 3 and parts[2] == "transcripts":
            return self._listed(self.transcripts.get(record, []), params, "transcripts")
        if len(parts) == 5 and parts[2] == "transcripts" and parts[4] == "entries":
            return self._listed(self.entries.get("/".join(parts[:4]), []), params, "transcriptEntries")
        return _json(404, {"error": {"code": 404, "message": f"no such endpoint: {rest}"}})

    # -- Reports: the login audit log ----------------------------------------------------------------

    def _logins(self, scope: str, user: str, params: dict[str, Any]) -> service_account.Response:
        if scope != AUDIT_SCOPE:
            return _insufficient()
        since = _instant(params["startTime"]) if params.get("startTime") else None
        found = [
            a
            for a in sorted(
                self.logins, key=lambda a: _instant(a["id"]["time"]), reverse=True
            )  # newest first
            if (user == "all" or a.get("actor", {}).get("email") == user)
            and (since is None or _instant(a["id"]["time"]) >= since)
        ]
        return self._listed(found, params, "items", {"kind": "admin#reports#activities"})


def _insufficient() -> service_account.Response:
    return _json(403, {"error": {"code": 403, "message": "Request had insufficient authentication scopes."}})


def _json(status: int, data: dict[str, Any]) -> service_account.Response:
    return service_account.Response(status, {"content-type": "application/json"}, json.dumps(data).encode())


def _activity_time(activity: dict[str, Any]) -> datetime:
    when = activity.get("timestamp") or activity["timeRange"]["startTime"]
    return _instant(str(when))


def _start_filter(text: str) -> datetime | None:
    """The bound a Meet filter may carry: `start_time>="…"`."""
    for clause in text.split(" AND "):
        clause = clause.strip().replace(" ", "")
        if clause.startswith("start_time>="):
            return _instant(clause.removeprefix("start_time>=").strip('"'))
    return None


def _window(text: str) -> tuple[datetime | None, datetime | None]:
    """The two bounds the client's filter may carry: `time >= "…"` and `time < "…"`."""
    since = until = None
    for clause in text.split(" AND "):
        clause = clause.strip()
        if clause.startswith("time >= "):
            since = _instant(clause.removeprefix("time >= ").strip('"'))
        elif clause.startswith("time < "):
            until = _instant(clause.removeprefix("time < ").strip('"'))
    return since, until


# -- the shapes the APIs return, built small ----------------------------------------------------------

Actor = dict[str, Any]
OWNER: Actor = {"user": {"knownUser": {"personName": "people/1000", "isCurrentUser": True}}}


def person(name: str) -> Actor:
    return {"user": {"knownUser": {"personName": name}}}


def item(
    file_id: str, title: str, mime: str = "application/vnd.google-apps.document", owner: Actor = OWNER
) -> dict[str, Any]:
    return {
        "name": f"items/{file_id}",
        "title": title,
        "mimeType": mime,
        "driveFile": {},
        "owner": owner,
    }


def activity(
    when: str,
    detail: dict[str, Any],
    target: dict[str, Any],
    actor: Actor = OWNER,
    comment: bool = False,
) -> dict[str, Any]:
    """One DriveActivity as `consolidationStrategy: none` returns it: one action, one actor, one target."""
    wrapped = (
        {"fileComment": {"legacyCommentId": "c1", "parent": target}} if comment else {"driveItem": target}
    )
    return {
        "primaryActionDetail": detail,
        "actors": [actor],
        "actions": [{"detail": detail}],
        "targets": [wrapped],
        "timestamp": when,
    }
