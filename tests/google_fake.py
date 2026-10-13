"""An in-process fake of the three Google endpoints `sync drive` and `sync gtasks` call: the OAuth token
endpoint (a service account's signed assertion in, an access token out), the Drive Activity API v2
(`activity:query`) and the Tasks API v1 (task lists, tasks). Nothing listens on a socket: the fake is a
function with the shape of `service_account.send`, which a test puts in its place, and every request it
answers is recorded so a test can say what was asked.

The token endpoint checks what Google checks: the assertion is an RS256 JWT signed by the key the fake
was given, issued by the key's client email for the user it impersonates, for a scope the domain-wide
delegation grants, addressed to the token endpoint and valid for an hour at most. A scope not granted is
`unauthorized_client`, as Google says it. Every API call must carry a token the fake issued.

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
    """The three endpoints with their data. `drive` holds DriveActivity objects as the API returns
    them; `lists` the task lists and `tasks` each list's tasks. `page` is how many items one page
    holds whatever the client asks, so paging shows with a handful of items. `failures` are answered,
    in order, to the next API calls (never to the token endpoint): `(status, headers, body)`."""

    key: rsa.RSAPrivateKey
    delegated: set[str] = field(default_factory=lambda: {DRIVE_SCOPE, TASKS_SCOPE})
    drive: list[dict[str, Any]] = field(default_factory=list)
    lists: list[dict[str, Any]] = field(default_factory=list)
    tasks: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
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


def _json(status: int, data: dict[str, Any]) -> service_account.Response:
    return service_account.Response(status, {"content-type": "application/json"}, json.dumps(data).encode())


def _activity_time(activity: dict[str, Any]) -> datetime:
    when = activity.get("timestamp") or activity["timeRange"]["startTime"]
    return _instant(str(when))


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
