"""An in-process fake of GitHub's REST API, on the loopback interface, for `logbook sync github`.

It serves the calls the source makes, in the shapes GitHub's REST API (version 2022-11-28) gives:
`GET /user`, `GET /user/repos`, `GET /repos/{owner}/{repo}`, `.../commits` (newest first, by
`sha` and `since`) and `.../commits/{sha}` (its files paged), `.../issues` (issues and pull requests,
by `state`, `sort`, `direction` and `since`) and `.../issues/{n}`, `.../pulls/{n}` and
`.../pulls/{n}/reviews`, `.../issues/comments` and `.../pulls/comments` (by `since`). Every list is
paged by `page`, `PAGE` results at a time whatever `per_page` asks, with a `Link` header naming the
next page, as GitHub's are. Every request is recorded with its method, path, query and headers;
anything but a GET is answered 405 and never acted on, so a test can hold the client to reading.
`throttle` answers the next N requests of a path with a rate limit (GitHub's secondary limit, a 403
with `Retry-After`; its primary limit, a 403 with `X-RateLimit-Remaining: 0` and the reset; a 429;
or a 502); `refuse` answers a path with one error every time.

Everything is synthetic: Ines Nordmann of Oslo, her brother Ola, their repositories and logins, the
ids (970000001 and up, above any account GitHub has numbered) and the commit hashes (the SHA-1 of a
label). Nobody in it is real.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

TOKEN = "github_pat_synthetic_token_not_a_real_one"
VERSION = "2022-11-28"
PAGE = 2  # results per page the fake serves, whatever the client asks: every list is paged
WEB = "https://github.example.org"  # where the html_url of everything points; never fetched

INES = {"login": "ines-example", "id": 970000001, "type": "User", "site_admin": False}
OLA = {"login": "ola-example", "id": 970000002, "type": "User", "site_admin": False}
BOT = {"login": "example-ci[bot]", "id": 970000003, "type": "Bot", "site_admin": False}
INES_EMAIL, OLA_EMAIL = "ines.nordmann@example.org", "ola@example.org"
SAILPLAN, HARBOUR, CREW = "ines-example/sailplan", "ines-example/harbour-notes", "ines-example/crew-list"
AGENT_FOOTER = "🤖 Generated with [Claude Code](https://claude.com/claude-code)"


def sha(label: str) -> str:
    """A synthetic commit hash: the SHA-1 of a label."""
    return hashlib.sha1(label.encode("utf-8")).hexdigest()


def stamp(text: str) -> str:
    """`2026-03-01T07:00Z` as GitHub spells an instant: to the second, `Z`."""
    when = datetime.strptime(text, "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def repo(full_name: str, branch: str = "main", private: bool = False, fork: bool = False) -> dict[str, Any]:
    owner, name = full_name.split("/")
    return {
        "id": 970100000 + sum(full_name.encode("utf-8")),
        "name": name,
        "full_name": full_name,
        "owner": INES if owner == INES["login"] else OLA,
        "private": private,
        "visibility": "private" if private else "public",
        "fork": fork,
        "archived": False,
        "default_branch": branch,
        "html_url": f"{WEB}/{full_name}",
        "has_issues": True,
    }


def commit(
    full_name: str,
    label: str,
    message: str,
    at: str,
    by: dict[str, Any] | None,
    name: str,
    email: str,
    files: int,
    committed: str | None = None,
) -> dict[str, Any]:
    """A commit as the list serves it, and its files under `_files` for the single commit."""
    digest = sha(label)
    author = {"name": name, "email": email, "date": stamp(at)}
    committer = {"name": name, "email": email, "date": stamp(committed or at)}
    return {
        "sha": digest,
        "node_id": f"C_{digest[:12]}",
        "commit": {"author": author, "committer": committer, "message": message, "comment_count": 0},
        "author": copy.deepcopy(by),
        "committer": copy.deepcopy(by),
        "parents": [],
        "html_url": f"{WEB}/{full_name}/commit/{digest}",
        "_files": [
            {"filename": f"file-{n}.md", "status": "modified", "additions": 1, "deletions": 0}
            for n in range(files)
        ],
    }


def issue(
    full_name: str,
    number: int,
    title: str,
    body: str | None,
    by: dict[str, Any],
    created: str,
    closed: str | None = None,
    closed_by: dict[str, Any] | None = None,
    pull: bool = False,
    merged: str | None = None,
    merged_by: dict[str, Any] | None = None,
    labels: tuple[str, ...] = (),
    files: int = 0,
) -> dict[str, Any]:
    """An issue as the issues list serves it (a pull request carries `pull_request`), and what the
    single issue and the single pull request add, under `_closed_by` and `_pull`."""
    kind = "pull" if pull else "issues"
    item: dict[str, Any] = {
        "number": number,
        "title": title,
        "body": body,
        "user": copy.deepcopy(by),
        "state": "closed" if closed else "open",
        "created_at": stamp(created),
        "updated_at": stamp(merged or closed or created),
        "closed_at": stamp(closed) if closed else None,
        "html_url": f"{WEB}/{full_name}/{kind}/{number}",
        "labels": [{"id": 970200000 + n, "name": name} for n, name in enumerate(labels)],
        "author_association": "OWNER" if by is INES else "COLLABORATOR",
        "comments": 0,
        "_closed_by": copy.deepcopy(closed_by),
    }
    if pull:
        item["pull_request"] = {
            "url": f"https://api.github.example.org/repos/{full_name}/pulls/{number}",
            "html_url": item["html_url"],
            "merged_at": stamp(merged) if merged else None,
        }
        item["draft"] = False
        item["_pull"] = {
            "number": number,
            "html_url": item["html_url"],
            "merged_at": stamp(merged) if merged else None,
            "merged_by": copy.deepcopy(merged_by),
            "changed_files": files,
            "commits": 1,
            "additions": 10,
            "deletions": 2,
            "base": {"ref": "main"},
            "head": {"ref": f"feature-{number}"},
        }
    return item


def comment(
    full_name: str, comment_id: int, number: int, body: str, by: dict[str, Any], at: str, pull: bool = False
) -> dict[str, Any]:
    kind = "pull" if pull else "issues"
    return {
        "id": comment_id,
        "body": body,
        "user": copy.deepcopy(by),
        "created_at": stamp(at),
        "updated_at": stamp(at),
        "html_url": f"{WEB}/{full_name}/{kind}/{number}#issuecomment-{comment_id}",
        "issue_url": f"https://api.github.example.org/repos/{full_name}/issues/{number}",
        "author_association": "OWNER" if by is INES else "NONE",
    }


def review(
    full_name: str, review_id: int, number: int, body: str, by: dict[str, Any], state: str, at: str | None
) -> dict[str, Any]:
    found: dict[str, Any] = {
        "id": review_id,
        "user": copy.deepcopy(by),
        "body": body,
        "state": state,
        "html_url": f"{WEB}/{full_name}/pull/{number}#pullrequestreview-{review_id}",
        "commit_id": sha(f"review-{review_id}"),
    }
    if at is not None:
        found["submitted_at"] = stamp(at)
    return found


def review_comment(
    full_name: str,
    comment_id: int,
    number: int,
    body: str,
    by: dict[str, Any],
    at: str,
    path: str,
    review_id: int,
) -> dict[str, Any]:
    return {
        "id": comment_id,
        "body": body,
        "user": copy.deepcopy(by),
        "path": path,
        "pull_request_review_id": review_id,
        "created_at": stamp(at),
        "updated_at": stamp(at),
        "html_url": f"{WEB}/{full_name}/pull/{number}#discussion_r{comment_id}",
        "pull_request_url": f"https://api.github.example.org/repos/{full_name}/pulls/{number}",
    }


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, str]
    headers: dict[str, str]


@dataclass
class FakeGitHub:
    """The account and the server. `repos`, `commits`, `issues`, `comments`, `reviews` and
    `review_comments` are the state a test edits between runs; `requests` what the client asked."""

    me: dict[str, Any] = field(default_factory=lambda: copy.deepcopy(INES))
    repos: dict[str, dict[str, Any]] = field(default_factory=dict)
    commits: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # full name → newest first
    issues: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    comments: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    reviews: dict[tuple[str, int], list[dict[str, Any]]] = field(default_factory=dict)
    review_comments: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    disabled_issues: set[str] = field(default_factory=set)  # repos whose issues are switched off: 410
    requests: list[Request] = field(default_factory=list)
    throttle: dict[str, int] = field(default_factory=dict)  # path → how many more refusals it answers
    throttle_mode: str = "secondary"  # "secondary", "primary", "429" or "502"
    retry_after: str = "7"
    reset_in: int = 30  # the primary limit's reset, seconds after `now`
    now: float = 1_773_000_000.0  # the fake's wall clock, which the client's is set to in the tests
    refuse: dict[str, tuple[int, str]] = field(default_factory=dict)  # path → (status, message)
    next_host: str | None = None  # a Link header that names another host (the client must refuse it)

    def __post_init__(self) -> None:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _send(self, code: int, doc: Any, headers: dict[str, str] | None = None) -> None:
                data = json.dumps(doc).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(data)

            def _handle(self) -> None:
                url = urlsplit(self.path)
                query = {k: v[-1] for k, v in parse_qs(url.query).items()}
                headers = {k.lower(): v for k, v in self.headers.items()}
                fake.requests.append(Request(self.command, url.path, query, headers))
                if self.command != "GET":
                    self._send(405, {"message": "This fake only reads."})
                    return
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    self._send(401, {"message": "Bad credentials", "status": "401"})
                    return
                if self.headers.get("X-GitHub-Api-Version") != VERSION or not self.headers.get("User-Agent"):
                    self._send(400, {"message": "The API version or the user agent is missing."})
                    return
                left = fake.throttle.get(url.path, 0)
                if left > 0:
                    fake.throttle[url.path] = left - 1
                    self._send(*fake._limited())
                    return
                if url.path in fake.refuse:
                    refused, message = fake.refuse[url.path]
                    self._send(refused, {"message": message, "status": str(refused)})
                    return
                code, doc, page_headers = fake.answer(url.path, query)
                self._send(code, doc, page_headers)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _handle

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    # -- the server ------------------------------------------------------------------------------------

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def paths(self) -> list[str]:
        return [r.path for r in self.requests]

    def _limited(self) -> tuple[int, Any, dict[str, str]]:
        if self.throttle_mode == "primary":
            return (
                403,
                {"message": "API rate limit exceeded for user ID 970000001."},
                {
                    "X-RateLimit-Limit": "5000",
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(self.now) + self.reset_in),
                },
            )
        if self.throttle_mode == "429":
            return 429, {"message": "Too many requests."}, {}
        if self.throttle_mode == "502":
            return 502, {"message": "Server Error"}, {}
        return (
            403,
            {"message": "You have exceeded a secondary rate limit. Please wait a few minutes."},
            {"Retry-After": self.retry_after, "X-RateLimit-Remaining": "4000"},
        )

    def answer(self, path: str, query: dict[str, str]) -> tuple[int, Any, dict[str, str]]:
        parts = [unquote(p) for p in path.split("/") if p]
        if parts == ["user"]:
            return 200, copy.deepcopy(self.me), {}
        if parts == ["user", "repos"]:
            rows = sorted(self.repos.values(), key=lambda r: r["full_name"])
            return self._page(path, query, rows)
        if len(parts) < 3 or parts[0] != "repos":
            return 404, {"message": "Not Found"}, {}
        full_name, rest = f"{parts[1]}/{parts[2]}", parts[3:]
        found = self.repos.get(full_name)
        if found is None:
            return 404, {"message": "Not Found"}, {}
        if not rest:
            return 200, copy.deepcopy(found), {}
        if rest == ["commits"]:
            branch = query.get("sha", found["default_branch"])
            if branch != found["default_branch"]:
                return 404, {"message": "No commit found for SHA: " + branch}, {}
            rows = self.commits.get(full_name, [])
            if not rows:
                return 409, {"message": "Git Repository is empty."}, {}
            since = query.get("since")
            rows = [c for c in rows if since is None or c["commit"]["committer"]["date"] >= since]
            return self._page(path, query, [_public(c) for c in rows])
        if len(rest) == 2 and rest[0] == "commits":
            found_commit = next((c for c in self.commits.get(full_name, []) if c["sha"] == rest[1]), None)
            if found_commit is None:
                return 404, {"message": "Not Found"}, {}
            code, files, headers = self._page(path, query, found_commit["_files"])
            single = {
                **_public(found_commit),
                "files": files,
                "stats": {"total": len(found_commit["_files"])},
            }
            return code, single, headers
        if full_name in self.disabled_issues and rest[0] == "issues":
            return 410, {"message": "Issues are disabled for this repo"}, {}
        if rest == ["issues"]:
            since = query.get("since")
            rows = sorted(self.issues.get(full_name, []), key=lambda i: (i["updated_at"], i["number"]))
            if query.get("direction") == "desc":
                rows.reverse()
            rows = [i for i in rows if since is None or i["updated_at"] >= since]
            return self._page(path, query, [_public(i) for i in rows])
        if rest == ["issues", "comments"]:
            return self._since(path, query, self.comments.get(full_name, []))
        if rest == ["pulls", "comments"]:
            return self._since(path, query, self.review_comments.get(full_name, []))
        if len(rest) == 2 and rest[0] == "issues":
            item = self._issue(full_name, int(rest[1]))
            if item is None:
                return 404, {"message": "Not Found"}, {}
            return 200, {**_public(item), "closed_by": copy.deepcopy(item["_closed_by"])}, {}
        if len(rest) == 2 and rest[0] == "pulls":
            item = self._issue(full_name, int(rest[1]))
            if item is None or "_pull" not in item:
                return 404, {"message": "Not Found"}, {}
            return 200, {**copy.deepcopy(item["_pull"]), "title": item["title"], "body": item["body"]}, {}
        if len(rest) == 3 and rest[0] == "pulls" and rest[2] == "reviews":
            return self._page(path, query, self.reviews.get((full_name, int(rest[1])), []))
        return 404, {"message": "Not Found"}, {}

    def _issue(self, full_name: str, number: int) -> dict[str, Any] | None:
        return next((i for i in self.issues.get(full_name, []) if i["number"] == number), None)

    def _since(
        self, path: str, query: dict[str, str], rows: list[dict[str, Any]]
    ) -> tuple[int, Any, dict[str, str]]:
        since = query.get("since")
        ordered = sorted(rows, key=lambda c: (c["updated_at"], c["id"]))
        return self._page(path, query, [c for c in ordered if since is None or c["updated_at"] >= since])

    def _page(self, path: str, query: dict[str, str], rows: list[Any]) -> tuple[int, Any, dict[str, str]]:
        """`PAGE` rows from `page` (1 when absent), and a `Link` to the next page when there is one."""
        number = int(query.get("page") or 1)
        served = copy.deepcopy(rows[(number - 1) * PAGE : number * PAGE])
        headers = {}
        if number * PAGE < len(rows):
            base = f"http://{self.next_host}" if self.next_host is not None else self.url
            following = urlencode({**query, "page": str(number + 1)})
            headers["Link"] = f'<{base}{path}?{following}>; rel="next", <{base}{path}?page=99>; rel="last"'
        return 200, served, headers

    # -- the account, as a test changes it ---------------------------------------------------------------

    def add_commit(self, full_name: str, item: dict[str, Any]) -> None:
        self.commits.setdefault(full_name, []).insert(0, item)  # newest first, as GitHub lists them


def _public(item: dict[str, Any]) -> dict[str, Any]:
    """What the API serves: the fake's own keys (`_files`, `_closed_by`, `_pull`) left out."""
    return {k: copy.deepcopy(v) for k, v in item.items() if not k.startswith("_")}


SAIL_PLAN_MESSAGE = "Start the sail plan\n\nLeave Oslo at nine; fuel at Drøbak before noon.\n"
TIDES_MESSAGE = (
    "Fix the tide table\n\nThe 14:00 entry was an hour late.\n\n"
    "Co-Authored-By: Claude <noreply@example.org>\n"
)


def account() -> FakeGitHub:
    """Ines's account as the token sees it, in March 2026 (Oslo is UTC+1).

    - sailplan (public, `main`): four commits — Ines's first, Ola's crew list, a tide fix an agent
      co-wrote (three files, so its files page), and one whose address GitHub links to no account;
      issue #1 (Ola asks, Ines closes), pull request #2 (Ines's, written by an agent, merged, with
      Ola's review and inline comment and the bot's comment), pull request #3 (Ola's, closed without
      merging) and issue #4 (open, no body).
    - harbour-notes (private, `trunk`): one commit; its issues are switched off.
    - crew-list: a fork, which `LOGBOOK_GITHUB_REPOS=--all` leaves out.
    """
    fake = FakeGitHub()
    fake.repos[SAILPLAN] = repo(SAILPLAN)
    fake.repos[HARBOUR] = repo(HARBOUR, branch="trunk", private=True)
    fake.repos[CREW] = repo(CREW, fork=True)
    for item in (
        commit(SAILPLAN, "c1", SAIL_PLAN_MESSAGE, "2026-03-01T08:00Z", INES, "Ines Nordmann", INES_EMAIL, 2),
        commit(SAILPLAN, "c2", "Add the crew list", "2026-03-02T09:30Z", OLA, "Ola Nordmann", OLA_EMAIL, 1),
        commit(SAILPLAN, "c3", TIDES_MESSAGE, "2026-03-03T10:00Z", INES, "Ines Nordmann", INES_EMAIL, 3),
        commit(
            SAILPLAN, "c4", "Note the harbour fees", "2026-03-04T07:00Z", None, "Ines Nordmann", INES_EMAIL, 1
        ),
    ):
        fake.add_commit(SAILPLAN, item)
    fake.add_commit(
        HARBOUR,
        commit(HARBOUR, "h1", "Harbour notes", "2026-03-06T18:00Z", INES, "Ines Nordmann", INES_EMAIL, 1),
    )
    fake.add_commit(CREW, commit(CREW, "f1", "Fork", "2026-02-01T10:00Z", OLA, "Ola Nordmann", OLA_EMAIL, 1))
    fake.disabled_issues.add(HARBOUR)
    fake.issues[SAILPLAN] = [
        issue(
            SAILPLAN,
            1,
            "Which harbour first?",
            "Drøbak or Hvaler? The wind decides.",
            OLA,
            "2026-03-01T12:00Z",
            closed="2026-03-02T08:00Z",
            closed_by=INES,
            labels=("question",),
        ),
        issue(
            SAILPLAN,
            2,
            "Tide table for March",
            f"Adds the table for the month.\n\n{AGENT_FOOTER}",
            INES,
            "2026-03-03T10:30Z",
            closed="2026-03-03T15:00Z",
            pull=True,
            merged="2026-03-03T15:00Z",
            merged_by=INES,
            files=3,
        ),
        issue(
            SAILPLAN,
            3,
            "Bigger sails",
            "Why not?",
            OLA,
            "2026-03-04T08:00Z",
            closed="2026-03-05T09:30Z",
            closed_by=OLA,
            pull=True,
        ),
        issue(SAILPLAN, 4, "Buy a new anchor", None, INES, "2026-03-05T16:00Z"),
    ]
    fake.comments[SAILPLAN] = [
        comment(SAILPLAN, 970300101, 1, "Drøbak first.", INES, "2026-03-01T13:00Z"),
        comment(SAILPLAN, 970300102, 2, "Checks passed.", BOT, "2026-03-03T11:00Z", pull=True),
        comment(SAILPLAN, 970300103, 3, "Closing, too windy.", OLA, "2026-03-05T09:00Z", pull=True),
    ]
    fake.reviews[(SAILPLAN, 2)] = [
        review(SAILPLAN, 970400201, 2, "Looks right.", OLA, "APPROVED", "2026-03-03T14:00Z"),
        review(SAILPLAN, 970400202, 2, "", INES, "PENDING", None),
    ]
    fake.review_comments[SAILPLAN] = [
        review_comment(
            SAILPLAN, 970500301, 2, "Check the 14:00 entry.", OLA, "2026-03-03T13:50Z", "tides.md", 970400201
        )
    ]
    return fake
