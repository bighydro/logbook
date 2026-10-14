"""GitHub → event/v1 (RFC 0009), live: commits, issues, pull requests, reviews and comments, read-only.

The owner builds this project, and kept older ones, on GitHub; the record keeps what happened there,
one `event/v1` line per act, built by the mapping `github` shares with `add github-export` (that
module says what a line holds, which text it keeps and its tier: 1 for a public repo, 2 for a
private one, with the reason on the line): a commit on a repo's
default branch, an issue or a pull request created, closed or merged, a review submitted, a comment
left on an issue, a pull request or a line of its diff.

Configured by the environment alone. `LOGBOOK_GITHUB_TOKEN` (required) is a fine-grained personal
access token, read-only: Metadata, Contents, Issues and Pull requests, each `Read`, on the repos it
is to read. `LOGBOOK_GITHUB_REPOS` (required) lists them, `owner/name`, comma- or space-separated,
or as the links GitHub copies (`https://github.com/<owner>/<name>.git`); or it is `--all`: every
repo the token sees, less the forks (someone else's history; a fork named in the list is read).
`LOGBOOK_GITHUB_URL` (optional) is another address for the API — a GitHub Enterprise Server's
`https://<host>/api/v3`; https, or http on this machine only, so the token never crosses a network
in the clear. The owner is whoever `policy/owner.json` lists under `handles` (the mapping's
`Owner`); with none listed, the token's own user, and the run says so.

The calls, `X-GitHub-Api-Version: 2022-11-28`, every one a GET and nothing that writes: `GET /user`
first (the token works; whose it is); the repos, `GET /repos/{repo}` each or `GET /user/repos` for
`--all`, whose answer marks each repo public or private (`private`, `visibility`;
`github.visibility_of`) as it is at this run, so every line of a private repo, or of one the answer
does not mark public, is tier 2, and a repo whose visibility changes is read at its new tier from
then on, the lines already written left as they are; then per repo, every list paged by its `Link`
header, `PAGE_SIZE` a page: `GET .../commits` on the default branch since its start, `GET
.../issues` (issues and pull requests, oldest update first), `GET .../issues/comments` and `GET
.../pulls/comments` since it, and `GET .../pulls/{n}/reviews` for each pull request the issues list
names. Three details are asked one by
one, and only for a line the record does not hold yet (`existing`): `GET .../commits/{sha}` for how
many files a commit changed, its files paged; `GET .../issues/{n}` for who closed one; `GET
.../pulls/{n}` for who merged one and what it changed. A next page at an address other than the
API's is never followed (the token would go with it): the run stops on one sentence.

Requests start at least a tenth of a second apart. A rate limit is waited out as GitHub says: its
secondary limit's `Retry-After`, or at least a minute when it names none; its primary limit's
reset (`X-RateLimit-Reset`); a 429 or a 5xx without either, 1 s doubling to 60 s, up to `RETRIES`
times. A wait longer than `WAIT_MAX_S` stops the run on one sentence, and so does a limit that does
not lift: `sync` keeps the watermark it had, and the next run carries on, the record refusing what
it already holds. A connection that fails is tried `CONNECT_RETRIES` more times. A repo the token
cannot read (404, 403) is said through `failed`, and the others are still read; a repo with its
issues switched off (410) or empty (409) gives what it has. Network happens only inside `pull`,
which only `logbook sync github` calls; `doctor` asks GitHub nothing.

**Where a run starts.** A watermark per repo (`marks`, which `sync` keeps in `state/github.json`):
the newest `modified_at` the run saw there, read back `LOOKBACK_H` — a week, for a commit pushed
days after it was made (the commits list filters by the committer's date) and for the lists GitHub
fills late; a commit pushed later than that comes in with `--since` or the export. A repo with no
mark is read from its beginning, so a repo added to the list later is read whole; `--since` reads
every repo from there. A line is written for an act at or after the start: a created line when the
item was created then, a close or a merge when it happened then, a comment or a review when it was
left then. A comment edited after its line was written is not written again: the record keeps what
was said when it was first read.
"""

from __future__ import annotations

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

from ... import __version__
from . import github
from .github import CLOSED, COMMENTED, CREATED, MERGED, REVIEWED, Owner, Who

__all__ = [
    "ENV",
    "KIND",
    "NAME",
    "TIER",
    "Config",
    "configure",
    "group",
    "pull",
    "watermark",
]

NAME = github.NAME
KIND = github.KIND
TIER = github.TIER
TOKEN_ENV = "LOGBOOK_GITHUB_TOKEN"
REPOS_ENV = "LOGBOOK_GITHUB_REPOS"
URL_ENV = "LOGBOOK_GITHUB_URL"
ENV = (TOKEN_ENV, REPOS_ENV)  # the address is optional and read beside them
EVERY = "--all"  # LOGBOOK_GITHUB_REPOS: every repo the token sees, less the forks
DEFAULT_URL = "https://api.github.com"
API_VERSION = "2022-11-28"
ACCEPT = "application/vnd.github+json"
USER_AGENT = f"openlogbook/{__version__}"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
UNIT = "items"  # what `sync` counts in its progress lines
PAGE_SIZE = 100  # the API's maximum
LOOKBACK_H = 7 * 24.0
REQUESTS_PER_S = 10.0
RETRIES = 6  # a rate limit or a 5xx, then the run stops
CONNECT_RETRIES = 2
BACKOFF_S = 1.0
BACKOFF_MAX_S = 60.0
SECONDARY_WAIT_S = 60.0  # a secondary limit that names no wait: GitHub says wait at least a minute
WAIT_MAX_S = 300.0  # a wait longer than this stops the run: the next one carries on
RETRY_STATUSES = frozenset({500, 502, 503, 504})
GONE = frozenset({404, 409, 410, 451})  # not there, empty, switched off, withheld
TIMEOUT_S = 60
MAX_PAGES = 100_000  # a list longer than this many pages is a cursor that stopped moving
BATCH = 500  # keys per question to the record
NEXT = re.compile(r'<([^>]+)>\s*;\s*rel="?next"?')
TOKEN_HINT = (
    f"check {TOKEN_ENV}: a fine-grained token under GitHub → Settings → Developer settings → Personal"
    " access tokens, read-only"
)

_sleep: Callable[[float], None] = time.sleep  # the tests replace all three: a wait is recorded, never slept
_clock: Callable[[], float] = time.monotonic
_time: Callable[[], float] = time.time  # the wall clock a primary limit's reset is counted against

Existing = Callable[[Iterable[tuple[str, str]]], set[tuple[str, str]]]


@dataclass(frozen=True)
class Config:
    url: str
    token: str = field(repr=False)
    repos: tuple[str, ...] = ()
    every_repo: bool = False


def configure(env: Mapping[str, str]) -> Config | None:
    """Config from the environment: None without the token or the repos; ValueError, one sentence
    naming the variable, for an address that is not https (http only on this machine) or a repo that
    is not `owner/name` or a link to one."""
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
    repos, every = _repos(env.get(REPOS_ENV, ""))
    token = env.get(TOKEN_ENV, "").strip()
    if not token or (not repos and not every):
        return None
    return Config(url=url, token=token, repos=tuple(repos), every_repo=every)


def _repos(text: str) -> tuple[list[str], bool]:
    """The repos `LOGBOOK_GITHUB_REPOS` names, each once (case aside) in the order given, or `--all`."""
    names: list[str] = []
    every = False
    for part in re.split(r"[\s,]+", text.strip()):
        if not part:
            continue
        if part == EVERY:
            every = True
            continue
        name = github.repo_name(part)
        if name is None:
            raise ValueError(
                f"{REPOS_ENV} names repos as owner/name or by the link GitHub copies, and {part!r} is neither"
            )
        if name.casefold() not in {n.casefold() for n in names}:
            names.append(name)
    if every and names:
        raise ValueError(f"{REPOS_ENV} is a list of owner/name or {EVERY}, not both")
    return names, every


def watermark(draft: dict[str, Any]) -> str | None:
    """The source's own clock for the act: a commit's committer date, an item's last update."""
    return str(draft["payload"]["modified_at"])


def group(draft: dict[str, Any]) -> str:
    """The action, as `sync` reports seen and new per action."""
    return str(draft["payload"]["extra"]["action"])


def pull(
    config: Config,
    since: str | None = None,
    progress: Callable[[int, float], None] | None = None,
    counts: dict[str, int] | None = None,
    marks: dict[str, str] | None = None,
    existing: Existing | None = None,
    notice: Callable[[str], None] | None = None,
    failed: list[str] | None = None,
    owner_aliases: Mapping[str, Iterable[str]] | None = None,
) -> Iterator[dict[str, Any]]:
    """The lines of every repo, a repo at a time, each repo's oldest act first. A repo starts from its
    mark in `marks` (`<owner>/<name>` in lower case → RFC 3339) less the lookback, which is raised to
    the newest `modified_at` yielded; with no mark, from its beginning when `marks` holds any (a repo
    added since), else from `since` (a first run, or `--since`). `existing` says which of a batch
    of keys the record holds, so no detail is asked twice; `failed` gets one line per repo that could
    not be read, the others still pulled; skips and notes are tallied in `counts`;
    `progress(items_so_far, elapsed)` after every page of a list. Raises OSError with one sentence,
    never the token, when GitHub refuses the token, does not answer, or keeps saying wait; ValueError
    on an answer that is not what the API documents."""
    counts = counts if counts is not None else {}
    marks = marks if marks is not None else {}
    marked = bool(marks)
    floor = github.instant(since) if since is not None else None
    client = _Client(config)
    me = client.get("/user")
    owner = Owner.of(owner_aliases)
    login = _text(me.get("login")) if isinstance(me, dict) else None
    if not owner.handles and login is not None:
        owner = owner.with_handle(login)
        if notice is not None:
            notice(
                f"no handles in policy/owner.json: the token's own user, {login}, is taken for you; list your"
                " handles there"
            )
    listed = _Listed(progress, time.monotonic())
    for name, info in _repos_to_read(client, config, counts, failed):
        key = name.casefold()
        start = _start(marks.get(key), floor, marked)
        reader = _Repo(client, name, info, start, owner, counts, existing, notice, listed)
        for draft in reader.drafts():
            mark = str(draft["payload"]["modified_at"])
            if key not in marks or mark > marks[key]:
                marks[key] = mark
            yield draft


def _start(mark: str | None, floor: datetime | None, marked: bool) -> datetime | None:
    """Where a repo is read from (the docstring of `pull`)."""
    if mark is not None:
        when = github.instant(mark)
        return when - timedelta(hours=LOOKBACK_H) if when is not None else floor
    return None if marked else floor


def _count(counts: dict[str, int], key: str, n: int = 1) -> None:
    if n:
        counts[key] = counts.get(key, 0) + n


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _dict(value: object) -> dict[str, Any]:
    """An object of the answer, or an empty one when it is anything else."""
    return value if isinstance(value, dict) else {}


# -- the API ---------------------------------------------------------------------------------------------


class _Again(Exception):
    """A request worth asking again: a rate limit, a 5xx, a connection that failed."""

    def __init__(self, what: str, after: float | None = None, connect: bool = False) -> None:
        super().__init__(what)
        self.what = what
        self.after = after
        self.connect = connect


class _Unreachable(OSError):
    """403, 404, 409, 410 or 451: the token may not read it, or it is not there."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class _Client:
    """Every call to GitHub: paced, retried, GET only. The token goes in the header only, and only to
    the configured address."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.base = urlsplit(config.url)
        self.last: float | None = None

    def get(self, path: str, query: Mapping[str, Any] | None = None) -> Any:
        doc, _following = self._call(self._url(path, query))
        return doc

    def walk(self, path: str, query: Mapping[str, Any] | None = None) -> Iterator[Any]:
        """Every page of a paged answer, by its `Link` header's next."""
        url = self._url(path, query)
        for _ in range(MAX_PAGES):
            doc, following = self._call(url)
            yield doc
            if following is None:
                return
            if following == url:
                raise ValueError(f"GitHub API GET {path}: the next page is this one; stopped")
            url = following
        raise ValueError(f"GitHub API GET {path}: more than {MAX_PAGES:,} pages; stopped")

    def items(self, path: str, query: Mapping[str, Any] | None = None) -> Iterator[list[Any]]:
        """Every page of a paged list, as its list."""
        for doc in self.walk(path, query):
            if not isinstance(doc, list):
                raise ValueError(f"GitHub API GET {path} did not answer with a list")
            yield doc

    def _url(self, path: str, query: Mapping[str, Any] | None) -> str:
        return self.config.url + path + (f"?{urlencode(query)}" if query else "")

    def _pace(self) -> None:
        gap = 1.0 / REQUESTS_PER_S
        if self.last is not None:
            waited = _clock() - self.last
            if waited < gap:
                _sleep(gap - waited)
        self.last = _clock()

    def _call(self, url: str) -> tuple[Any, str | None]:
        path = urlsplit(url).path.removeprefix(self.base.path)
        failure, tries, connects = "", 0, 0
        for attempt in range(RETRIES + 1):
            self._pace()
            tries += 1
            try:
                return self._once(url, path)
            except _Again as again:
                failure = again.what if again.connect else f"GitHub API GET {path}: {again.what}"
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

    def _once(self, url: str, path: str) -> tuple[Any, str | None]:
        headers = {
            "Authorization": f"Bearer {self.config.token}",
            "Accept": ACCEPT,
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": USER_AGENT,
        }
        try:
            with urlopen(Request(url, headers=headers, method="GET"), timeout=TIMEOUT_S) as response:
                raw = response.read()
                link = response.headers.get("Link")
        except HTTPError as e:
            raise self._refused(e, path) from None
        except (URLError, TimeoutError, OSError, HTTPException) as e:  # refused, reset, timed out, cut off
            reason = e.reason if isinstance(e, URLError) else (str(e) or type(e).__name__)
            raise _Again(f"GitHub did not answer at {self.config.url} ({reason})", connect=True) from None
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ValueError(f"GitHub API GET {path} did not answer with JSON") from None
        return doc, self._next(link, path)

    def _refused(self, e: HTTPError, path: str) -> Exception:
        """What an error answer is: worth asking again (a rate limit, a 5xx), not there, or the end."""
        said = _message(e)
        retry_after = _seconds(e.headers.get("Retry-After"))
        if e.code in (403, 429):
            if retry_after is not None:
                return _Again("rate limited (GitHub's secondary limit)", retry_after)
            if e.headers.get("X-RateLimit-Remaining") == "0":
                reset = _seconds(e.headers.get("X-RateLimit-Reset"))
                if reset is not None:
                    until = datetime.fromtimestamp(reset, UTC).strftime("%H:%M UTC")
                    return _Again(
                        f"rate limited until {until} (GitHub's hourly limit)", max(reset - _time(), 0) + 1
                    )
                return _Again("rate limited (GitHub's hourly limit)")
            if e.code == 429:
                return _Again("rate limited (429)")
            if "secondary rate limit" in said.casefold():
                return _Again("rate limited (GitHub's secondary limit)", SECONDARY_WAIT_S)
        if e.code in RETRY_STATUSES:
            return _Again(f"answered {e.code}")
        if e.code == 401:
            return OSError(f"GitHub refused the token (401): {TOKEN_HINT}")
        if e.code == 403 or e.code in GONE:
            return _Unreachable(e.code, f"GitHub API GET {path} answered {e.code}: {said}")
        return OSError(f"GitHub API GET {path} answered {e.code}: {said}")

    def _next(self, link: str | None, path: str) -> str | None:
        """The next page's address from a `Link` header, when it is the API's own; ValueError when it
        is anywhere else, since the token would go with the request."""
        if not link:
            return None
        found = NEXT.search(link)
        if found is None:
            return None
        following = found.group(1)
        parts = urlsplit(following)
        if (
            parts.scheme != self.base.scheme
            or parts.netloc != self.base.netloc
            or not parts.path.startswith(self.base.path)
        ):
            raise ValueError(
                f"GitHub API GET {path}: the next page is at another address ({parts.netloc or 'none'}),"
                " never asked with the token; stopped"
            )
        return following


def _message(e: HTTPError) -> str:
    """GitHub's own `message` from an error's body, else the reason."""
    try:
        doc = json.loads(e.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return str(e.reason)
    if isinstance(doc, dict) and isinstance(doc.get("message"), str):
        return str(doc["message"])
    return str(e.reason)


def _seconds(value: str | None) -> float | None:
    """A header's number of seconds (or epoch seconds); None for anything else."""
    try:
        seconds = float(value) if value is not None else -1.0
    except ValueError:
        return None
    return seconds if 0 <= seconds < float("inf") else None


def _repos_to_read(
    client: _Client, config: Config, counts: dict[str, int], failed: list[str] | None
) -> Iterator[tuple[str, dict[str, Any]]]:
    """(full name, the repo as the API has it) for every repo to read: those named, each asked for
    once (one the token cannot read is said through `failed`), or every one the token sees less
    the forks."""
    if config.every_repo:
        for page in client.items(
            "/user/repos", {"per_page": PAGE_SIZE, "sort": "full_name", "direction": "asc"}
        ):
            for item in page:
                if not isinstance(item, dict) or _text(item.get("full_name")) is None:
                    continue
                if item.get("fork"):
                    _count(counts, "skipped_fork")
                    continue
                yield str(item["full_name"]), item
        return
    for name in config.repos:
        try:
            item = client.get(f"/repos/{name}")
        except _Unreachable as e:
            said = (
                f"{name}: GitHub answered {e.status} (not there, or not readable with this token); not read"
            )
            if failed is None:
                raise OSError(said) from None
            failed.append(said)
            continue
        if not isinstance(item, dict):
            raise ValueError(f"GitHub API GET /repos/{name} did not answer with a repo")
        yield str(item.get("full_name") or name), item


# -- one repo --------------------------------------------------------------------------------------------


class _Listed:
    """How many items the lists have served so far, said after every page."""

    def __init__(self, progress: Callable[[int, float], None] | None, started: float) -> None:
        self.progress = progress
        self.started = started
        self.n = 0

    def add(self, n: int) -> None:
        self.n += n
        if self.progress is not None:
            self.progress(self.n, time.monotonic() - self.started)


@dataclass(frozen=True)
class _Act:
    """One line to be: when, its key, and how to build it; `detail` when the record does not hold it yet
    and building it asks GitHub once more."""

    at: datetime
    key: str
    build: Callable[[bool], dict[str, Any]]  # build(ask): ask for the detail, or not
    detail: bool = False


class _Repo:
    """One repo's lines since its start, oldest first."""

    def __init__(
        self,
        client: _Client,
        name: str,
        info: Mapping[str, Any],
        start: datetime | None,
        owner: Owner,
        counts: dict[str, int],
        existing: Existing | None,
        notice: Callable[[str], None] | None,
        listed: _Listed,
    ) -> None:
        self.client = client
        self.name = name
        self.key = name.casefold()
        self.visibility = github.visibility_of(
            info
        )  # as the API marks it at this run: the tier of every line
        self.branch = _text(info.get("default_branch"))
        self.start = start
        self.owner = owner
        self.counts = counts
        self.existing = existing
        self.notice = notice
        self.listed = listed
        if self.visibility == github.UNKNOWN and notice is not None:
            notice(f"{name}: GitHub does not say whether it is public, so its lines are tier 2")
        self.titles: dict[int, str] = {}
        self.pulls: set[int] = set()

    def drafts(self) -> Iterator[dict[str, Any]]:
        acts = [
            *self._commits(),
            *self._issues(),
            *self._comments(),
            *self._review_comments(),
            *self._reviews(),
        ]
        acts.sort(key=lambda act: (act.at, act.key))
        known = self._known([act.key for act in acts if act.detail])
        for act in acts:
            yield act.build(act.detail and act.key not in known)

    # -- the lists ---------------------------------------------------------------------------------------

    def _list(self, part: str, path: str, query: dict[str, Any]) -> list[dict[str, Any]]:
        """Every item of one list, paged; nothing when the repo has none of it (empty, switched off) or
        the token may not read it, said once."""
        found: list[dict[str, Any]] = []
        try:
            for page in self.client.items(f"/repos/{self.name}/{path}", query):
                found.extend(item for item in page if isinstance(item, dict))
                self.listed.add(len(page))
        except _Unreachable as e:
            if e.status == 410 and part == "issues":
                _count(self.counts, "github_issues_off")
            elif e.status not in (409, 410):
                _count(self.counts, "github_part_unreadable")
                if self.notice is not None:
                    self.notice(
                        f"{self.name}: its {part} not readable with this token ({e.status}); the rest is read"
                    )
            raise _Skip from None
        return found

    def _since(self) -> dict[str, Any]:
        return {} if self.start is None else {"since": github.stamp(self.start)}

    def _after(self, when: datetime | None) -> bool:
        return when is not None and (self.start is None or when >= self.start)

    def _commits(self) -> list[_Act]:
        query: dict[str, Any] = {"per_page": PAGE_SIZE, **self._since()}
        if self.branch is not None:
            query = {"sha": self.branch, **query}
        try:
            items = self._list("commits", "commits", query)
        except _Skip:
            return []
        acts = []
        for item in items:
            act = self._commit(item)
            if act is not None:
                acts.append(act)
        return acts

    def _commit(self, item: Mapping[str, Any]) -> _Act | None:
        found = _text(item.get("sha"))
        body = _dict(item.get("commit"))
        author, committer = _dict(body.get("author")), _dict(body.get("committer"))
        authored = github.instant(author.get("date"))
        committed = github.instant(committer.get("date")) or authored
        if found is None or authored is None or committed is None:
            _count(self.counts, "skipped_bad_date")
            return None
        sha: str = found
        message = str(body["message"]) if isinstance(body.get("message"), str) else ""
        who = Who.of(item.get("author"), author.get("name"), author.get("email"))
        url = _text(item.get("html_url"))

        def build(ask: bool) -> dict[str, Any]:
            files = self._files(sha) if ask else None
            return github.commit_line(
                self.name,
                self.branch,
                sha,
                message,
                url,
                files,
                authored,
                committed,
                who,
                self.owner,
                self.counts,
                visibility=self.visibility,
            )

        return _Act(authored, github.commit_key(sha), build, detail=True)

    def _files(self, sha: str) -> int | None:
        """How many files a commit changed, its files paged."""
        n = 0
        try:
            for page in self.client.walk(f"/repos/{self.name}/commits/{sha}", {"per_page": PAGE_SIZE}):
                files = page.get("files") if isinstance(page, dict) else None
                n += len(files) if isinstance(files, list) else 0
        except _Unreachable:
            return None
        return n

    def _issues(self) -> list[_Act]:
        query = {
            "state": "all",
            "sort": "updated",
            "direction": "asc",
            "per_page": PAGE_SIZE,
            **self._since(),
        }
        try:
            items = self._list("issues", "issues", query)
        except _Skip:
            return []
        acts: list[_Act] = []
        for item in items:
            acts.extend(self._issue(item))
        return acts

    def _issue(self, item: Mapping[str, Any]) -> list[_Act]:
        number = _int(item.get("number"))
        created = github.instant(item.get("created_at"))
        if number is None or created is None:
            _count(self.counts, "skipped_bad_date")
            return []
        title = _text(item.get("title"))
        pull_request = item.get("pull_request")
        pull = isinstance(pull_request, dict)
        if title is not None:
            self.titles[number] = title
        if pull:
            self.pulls.add(number)
        updated = github.instant(item.get("updated_at")) or created
        body = item.get("body") if isinstance(item.get("body"), str) else None
        agent = pull and github.is_agent(body)
        url = _text(item.get("html_url"))
        refs = github.item_ref(pull, number, url)
        labels = [
            str(label["name"])
            for label in item.get("labels") or []
            if isinstance(label, dict) and _text(label.get("name")) is not None
        ]
        acts: list[_Act] = []
        if self._after(created):
            who = Who.of(item.get("user"))
            extra = {"labels": labels} if labels else None

            def opened(_ask: bool) -> dict[str, Any]:
                return github.line(
                    created,
                    github.item_key(self.name, pull, number, CREATED),
                    title,
                    updated,
                    CREATED,
                    self.name,
                    who,
                    self.owner,
                    self.counts,
                    notes=body,
                    refs=refs,
                    extra=extra,
                    agent=agent,
                    visibility=self.visibility,
                )

            acts.append(_Act(created, github.item_key(self.name, pull, number, CREATED), opened))
        closed = github.instant(item.get("closed_at")) if item.get("state") == "closed" else None
        merged = github.instant(pull_request.get("merged_at")) if isinstance(pull_request, dict) else None
        if merged is not None and self._after(merged):
            acts.append(self._merged(number, title, url, merged, updated, agent))
        elif merged is None and closed is not None and self._after(closed):
            acts.append(self._closed(number, pull, title, url, closed, updated, agent))
        return acts

    def _closed(
        self,
        number: int,
        pull: bool,
        title: str | None,
        url: str | None,
        at: datetime,
        updated: datetime,
        agent: bool,
    ) -> _Act:
        key = github.item_key(self.name, pull, number, CLOSED, at)

        def build(ask: bool) -> dict[str, Any]:
            who = None
            if ask:
                detail = self._detail(f"issues/{number}")
                who = Who.of(detail.get("closed_by")) if detail is not None else None
            return github.line(
                at,
                key,
                title,
                updated,
                CLOSED,
                self.name,
                who,
                self.owner,
                self.counts,
                refs=github.item_ref(pull, number, url),
                agent=agent,
                visibility=self.visibility,
            )

        return _Act(at, key, build, detail=True)

    def _merged(
        self, number: int, title: str | None, url: str | None, at: datetime, updated: datetime, agent: bool
    ) -> _Act:
        key = github.item_key(self.name, True, number, MERGED)

        def build(ask: bool) -> dict[str, Any]:
            who, extra = None, {}
            detail = self._detail(f"pulls/{number}") if ask else None
            if detail is not None:
                who = Who.of(detail.get("merged_by"))
                for name, value in (
                    ("files", _int(detail.get("changed_files"))),
                    ("commits", _int(detail.get("commits"))),
                    ("base", _ref_name(detail.get("base"))),
                    ("head", _ref_name(detail.get("head"))),
                ):
                    if value is not None:
                        extra[name] = value
            return github.line(
                at,
                key,
                title,
                updated,
                MERGED,
                self.name,
                who,
                self.owner,
                self.counts,
                refs=github.item_ref(True, number, url),
                extra=extra,
                agent=agent,
                visibility=self.visibility,
            )

        return _Act(at, key, build, detail=True)

    def _detail(self, path: str) -> dict[str, Any] | None:
        try:
            found = self.client.get(f"/repos/{self.name}/{path}")
        except _Unreachable:
            return None
        return found if isinstance(found, dict) else None

    def _comments(self) -> list[_Act]:
        query = {"sort": "updated", "direction": "asc", "per_page": PAGE_SIZE, **self._since()}
        try:
            items = self._list("comments", "issues/comments", query)
        except _Skip:
            return []
        acts = []
        for item in items:
            number = _number(item.get("issue_url"))
            act = self._comment(item, number, f"issues/comments/{item.get('id')}", inline=False)
            if act is not None:
                acts.append(act)
        return acts

    def _review_comments(self) -> list[_Act]:
        query = {"sort": "updated", "direction": "asc", "per_page": PAGE_SIZE, **self._since()}
        try:
            items = self._list("review comments", "pulls/comments", query)
        except _Skip:
            return []
        acts = []
        for item in items:
            number = _number(item.get("pull_request_url"))
            act = self._comment(item, number, f"pulls/comments/{item.get('id')}", inline=True)
            if act is not None:
                acts.append(act)
        return acts

    def _comment(self, item: Mapping[str, Any], number: int | None, tail: str, inline: bool) -> _Act | None:
        comment_id = _int(item.get("id"))
        created = github.instant(item.get("created_at"))
        if comment_id is None or number is None or created is None:
            _count(self.counts, "skipped_bad_date")
            return None
        if not self._after(created):
            return None
        url = _text(item.get("html_url"))
        pull = inline or number in self.pulls or (url is not None and f"/pull/{number}" in url)
        updated = github.instant(item.get("updated_at")) or created
        body = item.get("body") if isinstance(item.get("body"), str) else None
        reference: dict[str, Any] = {"id": comment_id}
        if url is not None:
            reference["url"] = url
        refs: dict[str, Any] = {**github.item_ref(pull, number, None), "comment": reference}
        extra: dict[str, Any] = {}
        if inline:
            path = _text(item.get("path"))
            if path is not None:
                extra["path"] = path
            review_id = _int(item.get("pull_request_review_id"))
            if review_id is not None:
                extra["review"] = {"id": review_id}
        key = f"{self.key}/{tail}"
        draft = github.line(
            created,
            key,
            self.titles.get(number) or f"#{number}",
            updated,
            COMMENTED,
            self.name,
            Who.of(item.get("user")),
            self.owner,
            self.counts,
            notes=body,
            refs=refs,
            extra=extra,
            agent=github.is_agent(body),
            visibility=self.visibility,
        )
        return _Act(created, key, lambda _ask: draft)

    def _reviews(self) -> list[_Act]:
        acts = []
        for number in sorted(self.pulls):
            try:
                items = self._list("reviews", f"pulls/{number}/reviews", {"per_page": PAGE_SIZE})
            except _Skip:
                continue
            for item in items:
                act = self._review(number, item)
                if act is not None:
                    acts.append(act)
        return acts

    def _review(self, number: int, item: Mapping[str, Any]) -> _Act | None:
        review_id = _int(item.get("id"))
        state = _text(item.get("state"))
        if state is not None and state.upper() == "PENDING":
            _count(self.counts, "skipped_pending_review")
            return None
        submitted = github.instant(item.get("submitted_at"))
        if review_id is None or submitted is None:
            _count(self.counts, "skipped_bad_date")
            return None
        if not self._after(submitted):
            return None
        reference: dict[str, Any] = {"id": review_id}
        if state is not None:
            reference["state"] = state.lower()
        url = _text(item.get("html_url"))
        if url is not None:
            reference["url"] = url
        body = item.get("body") if isinstance(item.get("body"), str) else None
        key = f"{self.key}/pull/{number}/reviews/{review_id}"
        draft = github.line(
            submitted,
            key,
            self.titles.get(number) or f"#{number}",
            submitted,
            REVIEWED,
            self.name,
            Who.of(item.get("user")),
            self.owner,
            self.counts,
            notes=body,
            refs={**github.item_ref(True, number, None), "review": reference},
            agent=github.is_agent(body),
            visibility=self.visibility,
        )
        return _Act(submitted, key, lambda _ask: draft)

    # -- what the record holds ---------------------------------------------------------------------------

    def _known(self, keys: list[str]) -> set[str]:
        """Which of the keys the record holds, a batch at a time; none when the run cannot ask."""
        if self.existing is None or not keys:
            return set()
        held: set[str] = set()
        for n in range(0, len(keys), BATCH):
            batch = [(NAME, key) for key in keys[n : n + BATCH]]
            held |= {key for _source, key in self.existing(batch)}
        return held


class _Skip(Exception):
    """A list the repo does not have, or the token may not read: said, and passed over."""


def _number(url: object) -> int | None:
    """The number an `issue_url` or a `pull_request_url` ends in."""
    if not isinstance(url, str):
        return None
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else None


def _ref_name(value: object) -> str | None:
    """A pull request's base or head branch name."""
    return _text(value.get("ref")) if isinstance(value, dict) else None
