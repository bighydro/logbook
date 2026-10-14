"""GitHub → event/v1 (RFC 0009): the one mapping `sync github` and `add github-export` share (ADR 0017).

What happened on GitHub, one `event/v1` line per act: a commit, an issue or a pull request created,
closed or merged, a review submitted, a comment left; and, from an export alone, each version of a
README or a doc. `github_live` reads them from GitHub's API, and the export reader below from a
clone or an account export; both build their lines here, so the same act read either way is the
same `(source, raw_id)` and the record keeps it once.

**The text, by the profile.** `event/v1` has `notes`, "the description body": a commit's message,
an issue's or a pull request's body, a review's and a comment's text go there in full, verbatim. A
README's or a doc's text is never kept: its version is a digest, its length and its word count, as
Notion's pages are (SPEC §1.1, the record holds a digest, not the text).

**The tier.** Where the words were written, never who wrote them. A public repository's lines are
tier 1, as SPEC §4 and RFC 0009 give `event/v1` ("`tier` SHOULD be 1"; "an entry whose notes carry
someone else's words is still tier 1 by default"): a comment Ola left is tier 1 as one Ines left is.
A private repository's lines are tier 2 (`PRIVATE_TIER`), so an issue's text, a review and other
people's comments there never go where tier 1 crosses by default, with the reason on the line
(`extra.tier_reason`), as SPEC §4 lets a producer write a higher tier than a SHOULD default "for a
reason it states". A repository is public only when GitHub marks it so (`visibility_of`): `private`
false, or a `visibility` of `public`, and nothing that says otherwise; an `internal` one, a mark that
is no boolean or no word GitHub uses, is private; one with no mark at all is not known, and a line of
it is tier 2 too (`repository visibility not known`). Every line is built with its repository's
visibility (`line` takes it and has no default), so none can fall to tier 1 by omission. The same act
may so come at tier 1 one day and tier 2 another (a repository made public, a clone read before the
API); the record keeps the first and never a second, which in a record that seals needs the identity
for the tier 1 lines too, since a sealed line's `raw_id` is blinded (`MIXED_TIERS`).

**A line.** `kind` `event`; `at` when the act happened (a commit's author date, an issue's
creation, its close, a pull request's merge, a review's submission, a comment's creation), `end`
null, `tz` the record's own. The payload: `raw_id` (below); `title` (a commit's first line, an
issue's or a pull request's title, the title of the one a review or a comment is on, a doc's
path); `calendar` `{github, GitHub}`, one for every repo, so two repos' acts never fold into one;
`all_day` false; `modified_at` the source's own clock (a commit's committer date, an item's last
update), the watermark; `notes` the text; `organizer` the person who acted, as a handle ref
`{kind: handle, value: github:<login>}` (RFC 0006), for a person only, never a bot; and under
`extra`: `action` (`committed`, `created`, `closed`, `merged`, `reviewed`, `commented`,
`revised`); `repo` (`owner/name` as GitHub spells it); the thing acted on, referenced and never
copied — `commit` `{sha, url}`, `issue` or `pull` `{number, url}`, `review` `{id, state, url}`,
`comment` `{id, url}`; `actor` `{login, id, type, name, role}`, each when known (`name` is a
commit's author name; `role` `owner` or `other` once the owner is known); and what the act carries:
a commit's `branch` and `files` (how many it changed), an issue's `labels`, a merge's `files`,
`commits`, `base` and `head`, an inline comment's `path` and `review`, a doc's `file` `{path,
blob}` and `content` `{sha256, bytes, media_type, words, words_delta}`. `agent` true when the
line's own text carries the marker of an agent's session (`is_agent`). `tier_reason` on a tier 2
line: `private repository`, or `repository visibility not known`.

**raw_id.** A commit is `commit/<sha>`, whichever repo it was read from: one commit, one line.
Everything else is under the repo, lower case: `<repo>/issues/<n>/created`, `<repo>/pull/<n>/
created`, `<repo>/pull/<n>/merged`, `<repo>/issues/<n>/closed@<closed at>` (an issue closed,
reopened and closed again is a second line), `<repo>/pull/<n>/reviews/<id>`,
`<repo>/issues/comments/<id>`, `<repo>/pulls/comments/<id>` (an inline comment), and a doc's
version `<repo>/file/<path>@<blob>`.

**The owner.** A handle `policy/owner.json` lists is the owner (`Owner`): `ines-example`,
`@ines-example` and `github:ines-example` are one login, case aside; a handle another service
prefixes is not GitHub's. A commit whose author GitHub links to no account is the owner's when its
address is one of the owner's (`owner.json` or `owner_emails` in `logbook.json`) or its author's
name one of their names; the address is read for that, and to find the login a GitHub noreply
address spells (`<id>+<login>@users.noreply.github.com`), and never written. Every other person is
`other`, and a person's handle is a name source for `people review`, as a phone number is.

**An agent's work.** The owner builds with coding agents whose pull requests are the record of what
each did. A line is `agent: true` when its own text — a pull request's body (on every line of that
pull request), a commit's message, a review's or a comment's text — carries one of `AGENT_MARKERS`:
`Generated with Claude Code` (or `by`, the link's brackets aside), a session link
(`claude.ai/code/session_…`), or a commit trailer `Claude-Session:` or `Co-Authored-By: Claude`.

**The export** (`logbook add github-export DIR`, by name only: `sniff` says no to every folder). DIR
is a clone — a working copy (`DIR/.git`) or a bare repository (`DIR/HEAD`, `DIR/objects`) — or an
account export GitHub made (Settings → Account → Export account data; the migration archive, its
`schema.json` beside `repositories_*.json`), unpacked. A clone gives its history on the branch its
`HEAD` names: a line per commit from `git log`, with the message in full and how many files it
changed (a merge against its first parent), and a line per version of a README or a doc — a file at
the top whose name starts with `readme` or ends in a doc's suffix (`DOC_SUFFIXES`), or one under
`docs/` or `doc/` with such a suffix or `.txt` — with its blob, digest, length and words, and the
words since the path's previous version: so an old project's ideas have a first-said date. A
version is a path's content: the same bytes back at the same path later are no new version. The
repo is named by the clone's `origin` when that is a hosting link (`https://<host>/<owner>/<name>`,
`git@<host>:<owner>/<name>`), else by its folder. A clone says nothing of whether its repository is
public, so its lines are tier 2 unless the owner says it is (`public`, `add github-export DIR
--public`), and nothing here asks the network. An account export gives, for every repository its
`repositories_*.json` lists, its bare repository's history as a clone's, under the name it gives; and
from its `issues_*`, `pull_requests_*`, `issue_events_*` (who closed and who merged),
`issue_comments_*`, `pull_request_reviews_*` and `pull_request_review_comments_*` files the lines
`sync github` writes for the same acts, the ids read from their links (`#issuecomment-<id>`,
`#pullrequestreview-<id>`, `#discussion_r<id>`): read leniently, a row without what a line needs
skipped and counted. Each repository row's mark (`private`, `visibility`) sets the tier of every line
of that repository, its history's and its acts'; an act of a repository no row lists, or a row with
no mark, is not known to be public: tier 2, or 1 with `public`, which never overrides a repository
the export marks private. `--since` keeps the acts at or after it; a doc's earlier versions are still
read, so a version is new only once. Git runs here, never a shell, read-only (`rev-parse`,
`symbolic-ref`, `config`, `log`, `cat-file`) and never fetching (`GIT_NO_LAZY_FETCH`, no prompt, no
fsmonitor); a folder that is none of these is one sentence, `Unreadable`, and `add` exits 2. The
input is never called deletable (`KEEPS_INPUT`): a clone is a working copy.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

from ...core import policy
from . import Unreadable

__all__ = [
    "AGENT_MARKERS",
    "KEEPS_INPUT",
    "KIND",
    "MIXED_TIERS",
    "NAME",
    "TIER",
    "Owner",
    "Who",
    "is_agent",
    "login_of_address",
    "repo_name",
    "run",
    "sniff",
    "tier_of",
    "visibility_of",
]

NAME = "github"
KIND = "event"
TIER = 1  # a public repository's lines — SPEC §4, RFC 0009: event/v1, whoever wrote the words
PRIVATE_TIER = 2  # a private repository's, or one not known to be public: SPEC §4, "for a reason it states"
PUBLIC, PRIVATE, UNKNOWN = "public", "private", "unknown"  # a repository's visibility (`visibility_of`)
TIER_REASONS = {PRIVATE: "private repository", UNKNOWN: "repository visibility not known"}
SCHEMA = "event/v1"
CALENDAR = {"id": "github", "name": "GitHub"}
COMMITTED, CREATED, CLOSED, MERGED = "committed", "created", "closed", "merged"
REVIEWED, COMMENTED, REVISED = "reviewed", "commented", "revised"
OWNER, OTHER = "owner", "other"
PREFIX = "github:"  # a handle ref's value: `github:<login>`, lower case
NOREPLY = "users.noreply.github.com"  # the domain of the address GitHub commits under when asked to
USER, BOT = "User", "Bot"
KEEPS_INPUT = True  # `add` never calls the input deletable: a clone is the owner's working copy
MIXED_TIERS = True  # one act may come at tier 1 or 2: a record that seals needs the identity to write any
OWNER_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
REPO_NAME = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
MARKDOWN = frozenset({".md", ".markdown", ".mdx"})
DOC_SUFFIXES = MARKDOWN | {".rst", ".adoc", ".asciidoc", ".org", ".textile"}
DOC_DIRS = ("docs", "doc")
MAX_DOC_BYTES = 5 * 1024 * 1024  # a "doc" larger than this is no doc: counted, never read
BLOBS_PER_ASK = 500
GIT_ENV = {  # read-only and never over a network: no lazy fetch of a partial clone, no prompt, no lock
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_PAGER": "cat",
}
GIT_CONFIG = ("-c", "core.fsmonitor=false", "-c", "log.showSignature=false", "-c", "core.quotepath=off")
COMMIT_FORMAT = "%x1e%H%x1f%an%x1f%ae%x1f%aI%x1f%cI%x1f%B%x1d"  # then the paths, NUL-separated
VERSION_FORMAT = "%x1e%H%x1f%an%x1f%ae%x1f%aI%x1f%cI%x1d"  # then the raw changes, NUL-separated
DOC_PATHS = (
    ":(top,glob,icase)readme*",
    *(f":(top,glob,icase)*{suffix}" for suffix in sorted(DOC_SUFFIXES)),
    *(f":(top,glob){folder}/**" for folder in DOC_DIRS),
)
ARCHIVE_SCHEMA = "schema.json"
FRAGMENT_IDS = {
    "comment": re.compile(r"issuecomment-(\d+)"),
    "review": re.compile(r"pullrequestreview-(\d+)"),
    "inline": re.compile(r"(?:discussion_)?r(\d+)$"),
}
AGENT_MARKERS = (
    re.compile(r"Generated (?:with|by) \[?Claude Code\]?", re.IGNORECASE),
    re.compile(r"\bclaude\.ai/code/session_", re.IGNORECASE),
    re.compile(r"^Claude-Session:", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^Co-Authored-By:\s*Claude\b", re.IGNORECASE | re.MULTILINE),
)


def is_agent(text: str | None) -> bool:
    """Whether the text carries the marker of an agent's session (`AGENT_MARKERS`)."""
    return bool(text) and any(marker.search(text or "") for marker in AGENT_MARKERS)


def visibility_of(repo: Mapping[str, Any]) -> str:
    """A repository's visibility as GitHub marks it, in the API's answer or an account export's row:
    `public` only when every mark it carries says so (`private` false, `visibility` `public`);
    `unknown` when it carries none; `private` for anything else — `private` true, an `internal` or
    `private` visibility, a mark that is no boolean or no word GitHub uses."""
    private, seen = repo.get("private"), repo.get("visibility")
    if private is None and seen is None:
        return UNKNOWN
    said_public = seen == PUBLIC  # GitHub's own word, as it spells it
    if (private is None or private is False) and (seen is None or said_public):
        return PUBLIC
    return PRIVATE


def tier_of(visibility: str) -> tuple[int, str | None]:
    """The tier of a line of a repository of that visibility, and the reason a tier 2 one says; every
    visibility but `public` is tier 2."""
    if visibility == PUBLIC:
        return TIER, None
    return PRIVATE_TIER, TIER_REASONS.get(visibility, TIER_REASONS[PRIVATE])


def login_of_address(address: str | None) -> str | None:
    """The login a GitHub noreply address spells, `<id>+<login>@` or `<login>@` before `NOREPLY`;
    None for any other address."""
    if not address or "@" not in address:
        return None
    local, _, domain = address.strip().rpartition("@")
    if domain.casefold() != NOREPLY or not local:
        return None
    login = local.split("+", 1)[1] if "+" in local else local
    return login or None


def _normal(name: str) -> str:
    return " ".join(name.split()).casefold()


@dataclass(frozen=True)
class Who:
    """Who acted, as the source said: a GitHub user (login, id, type) and, for a commit, the author's
    name and address. The address is read to tell the owner and never written."""

    login: str | None = None
    id: int | None = None
    type: str | None = None
    name: str | None = None
    address: str | None = None

    @classmethod
    def of(cls, user: object, name: object = None, address: object = None) -> Who | None:
        """From an API user object (`{login, id, type}`) and a commit's author name and address;
        None when there is nobody."""
        login = id_ = kind = None
        if isinstance(user, Mapping):
            login = _text(user.get("login"))
            raw_id = user.get("id")
            id_ = raw_id if isinstance(raw_id, int) and not isinstance(raw_id, bool) else None
            kind = _text(user.get("type"))
        named, addressed = _text(name), _text(address)
        if login is None and addressed is not None:
            login = login_of_address(addressed)
        if login is None and named is None and addressed is None:
            return None
        return cls(login, id_, kind, named, addressed)

    @property
    def person(self) -> bool:
        """A person, not a bot: what `organizer` and `people review` name."""
        if self.login is None:
            return False
        if self.type is not None:
            return self.type == USER
        return not self.login.endswith("[bot]")


@dataclass(frozen=True)
class Owner:
    """The owner as `policy/owner.json` and `logbook.json` know them: GitHub logins (case aside),
    addresses (case aside) and names (whitespace and case aside)."""

    handles: frozenset[str] = frozenset()
    emails: frozenset[str] = frozenset()
    names: frozenset[str] = frozenset()

    @classmethod
    def of(cls, aliases: Mapping[str, Iterable[str]] | None) -> Owner:
        """From `owner_aliases` (`handles`, `emails`, `names`); a handle another service prefixes
        (`x:ines`) is not GitHub's."""
        aliases = aliases or {}
        handles = set()
        for text in aliases.get("handles", ()):
            spelled = policy.handle(text)
            if spelled is None:
                continue
            if spelled.startswith(PREFIX):
                spelled = spelled.removeprefix(PREFIX)
            elif ":" in spelled:
                continue
            if spelled:
                handles.add(spelled)
        emails = {e.strip().casefold() for e in aliases.get("emails", ()) if e.strip()}
        names = {_normal(n) for n in aliases.get("names", ()) if n.strip()}
        return cls(frozenset(handles), frozenset(emails), frozenset(names))

    def with_handle(self, login: str) -> Owner:
        return Owner(self.handles | {login.casefold()}, self.emails, self.names)

    def role(self, who: Who) -> str | None:
        """`owner` when a handle, an address or a name is the owner's; `other` when the owner is
        known by what `who` carries and it is none of theirs; None when nothing can tell."""
        if who.login is not None and who.login.casefold() in self.handles:
            return OWNER
        if who.address is not None and who.address.casefold() in self.emails:
            return OWNER
        if who.name is not None and _normal(who.name) in self.names:
            return OWNER
        if who.login is not None and self.handles:
            return OTHER
        if who.login is None and ((who.address and self.emails) or (who.name and self.names)):
            return OTHER
        return None


# -- the lines -------------------------------------------------------------------------------------------


def actor(who: Who | None, owner: Owner, counts: dict[str, int]) -> dict[str, Any] | None:
    """`extra.actor`: login, id, type, name and role, each when known; never the address."""
    if who is None:
        return None
    out: dict[str, Any] = {}
    if who.login is not None:
        out["login"] = who.login
    if who.id is not None:
        out["id"] = who.id
    if who.type is not None:
        out["type"] = who.type
    if who.name is not None:
        out["name"] = who.name
    role = owner.role(who)
    if role is not None:
        out["role"] = role
    else:
        _count(counts, "github_unmarked")
    return out


def organizer(who: Who | None) -> dict[str, str] | None:
    """The person who acted as a handle ref (RFC 0006), `github:<login>` in lower case; None for a
    bot or an author GitHub links to no account."""
    if who is None or who.login is None or not who.person:
        return None
    return {"kind": "handle", "value": f"{PREFIX}{who.login.casefold()}"}


def line(
    at: datetime,
    raw_id: str,
    title: str | None,
    modified: datetime,
    action: str,
    repo: str,
    who: Who | None,
    owner: Owner,
    counts: dict[str, int],
    notes: str | None = None,
    refs: Mapping[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
    agent: bool = False,
    *,
    visibility: str,
) -> dict[str, Any]:
    """One draft: the act, its text, who did it, the thing it was done to, at the tier of a repository
    whose visibility is `visibility` (`tier_of`); there is no default, so no line is tier 1 by omission."""
    tier, reason = tier_of(visibility)
    payload: dict[str, Any] = {"schema": SCHEMA, "raw_id": raw_id}
    if title:
        payload["title"] = title
    payload["calendar"] = dict(CALENDAR)
    payload["all_day"] = False
    payload["modified_at"] = stamp(modified)
    if notes:
        payload["notes"] = notes
    found = organizer(who)
    if found is not None:
        payload["organizer"] = found
    body: dict[str, Any] = {"action": action, "repo": repo, **(refs or {}), **(extra or {})}
    acted = actor(who, owner, counts)
    if acted is not None:
        body["actor"] = acted
    if agent:
        body["agent"] = True
    if reason is not None:
        body["tier_reason"] = reason
        _count(counts, "github_private" if visibility == PRIVATE else "github_visibility_unknown")
    payload["extra"] = body
    return {
        "at": stamp(at),
        "end": None,
        "tz": None,  # the record's own
        "source": NAME,
        "kind": KIND,
        "tier": tier,
        "payload": payload,
    }


def commit_line(
    repo: str,
    branch: str | None,
    sha: str,
    message: str,
    url: str | None,
    files: int | None,
    authored: datetime,
    committed: datetime,
    who: Who | None,
    owner: Owner,
    counts: dict[str, int],
    *,
    visibility: str,
) -> dict[str, Any]:
    reference: dict[str, Any] = {"sha": sha}
    if url:
        reference["url"] = url
    extra: dict[str, Any] = {}
    if branch:
        extra["branch"] = branch
    extra["commit"] = reference
    if files is not None:
        extra["files"] = files
    return line(
        authored,
        commit_key(sha),
        subject(message),
        committed,
        COMMITTED,
        repo,
        who,
        owner,
        counts,
        notes=message,
        extra=extra,
        agent=is_agent(message),
        visibility=visibility,
    )


def item_ref(pull: bool, number: int, url: str | None) -> dict[str, Any]:
    """`{issue: {number, url}}` or `{pull: {number, url}}`."""
    reference: dict[str, Any] = {"number": number}
    if url:
        reference["url"] = url
    return {"pull" if pull else "issue": reference}


def commit_key(sha: str) -> str:
    return f"commit/{sha.lower()}"


def item_key(repo: str, pull: bool, number: int, action: str, at: datetime | None = None) -> str:
    """`<repo>/issues/<n>/<action>` or `<repo>/pull/<n>/<action>`; a close carries its time."""
    tail = f"{action}@{stamp(at)}" if action == CLOSED and at is not None else action
    return f"{repo.lower()}/{'pull' if pull else 'issues'}/{number}/{tail}"


def subject(message: str) -> str | None:
    """A commit message's first line, stripped; None when it has none."""
    for text in message.splitlines():
        if text.strip():
            return text.strip()
    return None


def _count(counts: dict[str, int], key: str, n: int = 1) -> None:
    if n:
        counts[key] = counts.get(key, 0) + n


def _text(value: object) -> str | None:
    """A non-blank string, stripped; anything else is None."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def instant(value: object) -> datetime | None:
    """An RFC 3339 instant (GitHub's `2026-03-01T07:00:00Z`, git's `2026-03-01T08:00:00+01:00`, an
    export's `2026-03-01T08:00:00.000+01:00`) in UTC; None for anything else."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        when = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC)


def stamp(when: datetime) -> str:
    """The record's spelling: UTC to the second, `Z`."""
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def repo_name(text: str) -> str | None:
    """`owner/name` from itself, from a web or clone link (`https://<host>/<owner>/<name>.git`) or
    from an SSH one (`git@<host>:<owner>/<name>.git`); None for anything else, a local path among
    them."""
    text = text.strip().split("?", 1)[0].split("#", 1)[0]
    linked = "://" in text
    ssh = re.match(r"^[\w.-]+@[\w.-]+:", text) is not None
    if linked:
        path = urlsplit(text).path
    elif ssh:
        path = text.split(":", 1)[1]
    else:
        path = text
    segments = [unquote(s) for s in path.strip("/").split("/") if s]
    if len(segments) < 2 or (not linked and not ssh and len(segments) != 2):
        return None
    owner, name = segments[-2], segments[-1].removesuffix(".git")
    if not OWNER_NAME.match(owner) or not REPO_NAME.match(name) or name in (".", ".."):
        return None
    return f"{owner}/{name}"


# -- the export ------------------------------------------------------------------------------------------


def sniff(path: Path) -> bool:
    """Never: a folder is a project only when the owner says so, `add github-export DIR`."""
    return False


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    report: list[str] | None = None,
    owner_aliases: Mapping[str, Iterable[str]] | None = None,
    public: bool = False,
) -> Iterator[dict[str, Any]]:
    """The lines of a clone or an account export (the module docstring), the acts at or after `since`
    (every one when None). `public`: the owner says a repository not known to be public is (a clone,
    a repository the export does not mark), so its lines are tier 1; a repository the export marks
    private stays tier 2. Raises `Unreadable`, one sentence, for a folder that is neither, or one git
    cannot read."""
    counts = counts if counts is not None else {}
    report = report if report is not None else []
    owner = Owner.of(owner_aliases)
    floor = instant(since) if since is not None else None
    path = Path(path)
    if not owner.handles:
        report.append("no handles in policy/owner.json: the owner is known by addresses and names alone")
    if _is_archive(path):
        yield from _archive(path, floor, owner, counts, report, public)
        return
    if _is_repository(path):
        git = _Git.of(path)
        origin = git.text("config", "--get", "remote.origin.url")
        name = (repo_name(origin) if origin else None) or path.name.removesuffix(".git")
        if not public:
            report.append(
                f"{name}: a clone does not say whether its repository is public, so its lines are tier 2;"
                " a public one's are tier 1 with --public, for the lines not yet in the record (a line"
                " keeps the tier it was written at)"
            )
        yield from _history(git, name, None, floor, owner, counts, PUBLIC if public else UNKNOWN)
        return
    raise Unreadable(f"{path}: not a git clone, a bare repository or a GitHub account export; nothing read")


def _is_repository(path: Path) -> bool:
    """A working copy (`.git`, a folder or a worktree's file) or a bare repository."""
    if not path.is_dir():
        return False
    if (path / ".git").exists():
        return True
    return (path / "HEAD").is_file() and (path / "objects").is_dir() and (path / "refs").is_dir()


def _is_archive(path: Path) -> bool:
    return path.is_dir() and (path / ARCHIVE_SCHEMA).is_file() and any(path.glob("repositories_*.json"))


class _Git:
    """`git` in one repository, read-only and never fetching (`GIT_ENV`, `GIT_CONFIG`)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.env = {**os.environ, **GIT_ENV}

    @classmethod
    def of(cls, path: Path) -> _Git:
        if shutil.which("git") is None:
            raise Unreadable(f"{path}: git is not on PATH, and the history is read with it; nothing read")
        return cls(path)

    def run(self, *args: str, given: bytes | None = None) -> tuple[int, bytes, str]:
        done = subprocess.run(
            ["git", "-C", str(self.path), *GIT_CONFIG, *args],
            input=given,
            capture_output=True,
            env=self.env,
            check=False,
        )
        said = done.stderr.decode("utf-8", "replace").strip().splitlines()
        return done.returncode, done.stdout, said[0] if said else ""

    def text(self, *args: str) -> str | None:
        """One value (a branch, a remote), or None when git has none."""
        code, out, _said = self.run(*args)
        value = out.decode("utf-8", "replace").strip()
        return value if code == 0 and value else None

    def log(self, *args: str) -> bytes:
        """`git log`'s output; nothing for a repository without a commit; `Unreadable` when git refuses."""
        code, out, said = self.run("log", *args)
        if code == 0:
            return out
        if "does not have any commits" in said or "bad default revision" in said:
            return b""
        raise Unreadable(f"{self.path}: git log failed: {said or f'status {code}'}")

    def blobs(self, shas: Iterable[str]) -> dict[str, bytes]:
        """The bytes of each blob, asked `BLOBS_PER_ASK` at a time; a missing one left out."""
        wanted = list(dict.fromkeys(shas))
        found: dict[str, bytes] = {}
        for n in range(0, len(wanted), BLOBS_PER_ASK):
            batch = wanted[n : n + BLOBS_PER_ASK]
            code, out, said = self.run("cat-file", "--batch", given="".join(f"{b}\n" for b in batch).encode())
            if code != 0:
                raise Unreadable(f"{self.path}: git cat-file failed: {said or f'status {code}'}")
            at = 0
            while at < len(out):
                end = out.index(b"\n", at)
                header = out[at:end].decode("ascii", "replace").split()
                at = end + 1
                if len(header) != 3 or header[1] != "blob":
                    continue  # `<sha> missing`
                size = int(header[2])
                found[header[0]] = out[at : at + size]
                at += size + 1
        return found


@dataclass(frozen=True)
class _Commit:
    sha: str
    who: Who | None
    authored: datetime
    committed: datetime
    message: str
    paths: tuple[str, ...]


def _records(out: bytes, fields: int, counts: dict[str, int]) -> Iterator[tuple[list[str], bytes]]:
    """Each commit of a `git log` in the module's formats: its header fields and what follows them."""
    for record in out.split(b"\x1e")[1:]:
        head, sep, tail = record.partition(b"\x1d")
        values = head.decode("utf-8", "replace").split("\x1f", fields - 1)
        if not sep or len(values) != fields:
            _count(counts, "skipped_unreadable_commit")
            continue
        yield values, tail.lstrip(b"\0\n")


def _commits(git: _Git, counts: dict[str, int]) -> Iterator[_Commit]:
    out = git.log("--reverse", f"--format={COMMIT_FORMAT}", "--name-only", "-z", "--diff-merges=first-parent")
    for values, tail in _records(out, 6, counts):
        sha, name, address, authored_text, committed_text, message = values
        authored, committed = instant(authored_text), instant(committed_text)
        if authored is None or committed is None:
            _count(counts, "skipped_bad_date")
            continue
        paths = tuple(p.decode("utf-8", "replace") for p in tail.split(b"\0") if p)
        yield _Commit(sha, Who.of(None, name, address), authored, committed, message, paths)


def _history(
    git: _Git,
    repo: str,
    web: str | None,
    floor: datetime | None,
    owner: Owner,
    counts: dict[str, int],
    visibility: str,
) -> Iterator[dict[str, Any]]:
    """A repository's commits and doc versions on the branch `HEAD` names, oldest first, those at or
    after `floor`, at the tier its `visibility` gives."""
    branch = git.text("symbolic-ref", "-q", "--short", "HEAD")
    for c in _commits(git, counts):
        if floor is not None and c.authored < floor:
            continue
        url = f"{web}/commit/{c.sha}" if web else None
        yield commit_line(
            repo,
            branch,
            c.sha,
            c.message,
            url,
            len(c.paths),
            c.authored,
            c.committed,
            c.who,
            owner,
            counts,
            visibility=visibility,
        )
    yield from _versions(git, repo, floor, owner, counts, visibility)


@dataclass(frozen=True)
class _Version:
    sha: str
    who: Who | None
    authored: datetime
    committed: datetime
    path: str
    blob: str


def is_doc(path: str) -> bool:
    """A README at the top (any suffix), a file at the top with a doc's suffix, or one under `docs/`
    or `doc/` with a doc's suffix or `.txt`."""
    spelled = PurePosixPath(path)  # git's own spelling of a path in the tree, never this machine's
    suffix = spelled.suffix.casefold()
    if len(spelled.parts) == 1:
        return spelled.name.casefold().startswith("readme") or suffix in DOC_SUFFIXES
    return spelled.parts[0] in DOC_DIRS and (suffix in DOC_SUFFIXES or suffix == ".txt")


def _version_list(git: _Git, counts: dict[str, int]) -> list[_Version]:
    out = git.log(
        "--reverse",
        f"--format={VERSION_FORMAT}",
        "--raw",
        "--no-abbrev",
        "-z",
        "--diff-merges=first-parent",
        "HEAD",
        "--",
        *DOC_PATHS,
    )
    found: list[_Version] = []
    for values, tail in _records(out, 5, counts):
        sha, name, address, authored_text, committed_text = values
        authored, committed = instant(authored_text), instant(committed_text)
        if authored is None or committed is None:
            _count(counts, "skipped_bad_date")
            continue
        who = Who.of(None, name, address)
        items = tail.split(b"\0")
        n = 0
        while n < len(items):
            entry = items[n].decode("utf-8", "replace")
            n += 1
            if not entry.startswith(":"):
                continue
            meta = entry[1:].split()
            status = meta[4] if len(meta) == 5 else ""
            taken = 2 if status[:1] in ("R", "C") else 1
            paths = [p.decode("utf-8", "replace") for p in items[n : n + taken]]
            n += taken
            if len(meta) != 5 or not paths or status.startswith("D") or meta[1] not in ("100644", "100755"):
                continue
            if is_doc(paths[-1]):
                found.append(_Version(sha, who, authored, committed, paths[-1], meta[3]))
    return found


def _versions(
    git: _Git, repo: str, floor: datetime | None, owner: Owner, counts: dict[str, int], visibility: str
) -> Iterator[dict[str, Any]]:
    """One line per version of each doc: a path's content seen for the first time, the whole history
    read so that `floor` never makes an old version new."""
    versions = _version_list(git, counts)
    contents = git.blobs(v.blob for v in versions)
    seen: set[tuple[str, str]] = set()
    words_before: dict[str, int] = {}
    for v in versions:
        data = contents.get(v.blob)
        if data is None or len(data) > MAX_DOC_BYTES:
            _count(counts, "skipped_unreadable_doc" if data is None else "skipped_large_doc")
            continue
        words = len(data.decode("utf-8", "replace").split())
        previous = words_before.get(v.path)
        words_before[v.path] = words
        if (v.path, v.blob) in seen:
            continue
        seen.add((v.path, v.blob))
        if floor is not None and v.authored < floor:
            continue
        suffix = PurePosixPath(v.path).suffix.casefold()
        content: dict[str, Any] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "media_type": "text/markdown" if suffix in MARKDOWN else "text/plain",
            "words": words,
        }
        if previous is not None:
            content["words_delta"] = words - previous
        yield line(
            v.authored,
            f"{repo.lower()}/file/{v.path}@{v.blob}",
            v.path,
            v.committed,
            REVISED,
            repo,
            v.who,
            owner,
            counts,
            refs={"commit": {"sha": v.sha}, "file": {"path": v.path, "blob": v.blob}},
            extra={"content": content},
            visibility=visibility,
        )


# -- an account export -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Link:
    """What a link of the export names: a repo, and an issue or a pull request in it, and its fragment."""

    repo: str | None
    pull: bool | None
    number: int | None
    fragment: str

    @classmethod
    def of(cls, url: object) -> _Link:
        if not isinstance(url, str):
            return cls(None, None, None, "")
        parts = urlsplit(url.strip())
        segments = [unquote(s) for s in parts.path.strip("/").split("/") if s]
        repo = f"{segments[0]}/{segments[1]}" if len(segments) >= 2 else None
        pull = number = None
        if len(segments) >= 4 and segments[2] in ("issues", "pull") and segments[3].isdigit():
            pull, number = segments[2] == "pull", int(segments[3])
        return cls(repo, pull, number, parts.fragment)

    def id(self, kind: str) -> int | None:
        found = FRAGMENT_IDS[kind].search(self.fragment)
        return int(found.group(1)) if found is not None else None


def _person(url: object) -> Who | None:
    """The user a link names: `https://<host>/<login>`, or an app's `https://<host>/apps/<name>`."""
    if not isinstance(url, str):
        return None
    segments = [unquote(s) for s in urlsplit(url.strip()).path.strip("/").split("/") if s]
    if len(segments) == 2 and segments[0] == "apps":
        return Who(f"{segments[1]}[bot]", type=BOT)
    return Who(segments[0]) if len(segments) == 1 else None


def _rows(archive: Path, prefix: str, report: list[str]) -> Iterator[dict[str, Any]]:
    """Every object of the export's `<prefix>_NNNNNN.json` files, in their order."""
    for path in sorted(archive.glob(f"{prefix}_*.json")):
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            report.append(f"{path.name}: not JSON; skipped")
            continue
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict):
                yield row


class _Marks:
    """The visibility of each repository an account export lists, by its mark (`visibility_of`), and what
    a repository not known to be public is taken for: public when the owner says so (`public`), else
    not known. Each repository that is not public is said once in `report`."""

    def __init__(self, rows: Iterable[Mapping[str, Any]], public: bool, report: list[str]) -> None:
        self.marks: dict[str, str] = {}
        for row in rows:
            link = _Link.of(row.get("url"))
            if link.repo is None:
                continue
            key, found = link.repo.lower(), visibility_of(row)
            before = self.marks.get(key, found)  # a repository listed twice: private if either says so
            self.marks[key] = (
                PRIVATE if PRIVATE in (before, found) else PUBLIC if PUBLIC in (before, found) else found
            )
        self.public = public
        self.report = report
        self.said: set[str] = set()

    def __call__(self, repo: str) -> str:
        key = repo.lower()
        found = self.marks.get(key)
        visibility = PUBLIC if found in (None, UNKNOWN) and self.public else found or UNKNOWN
        if visibility != PUBLIC and key not in self.said:
            self.said.add(key)
            if visibility == PRIVATE:
                why = "the export marks it private" + (", whatever --public says" if self.public else "")
                self.report.append(f"{repo}: {why}; its lines are tier 2")
            else:
                where = "the export does not mark it" if found is not None else "the export does not list it"
                self.report.append(
                    f"{repo}: {where} public or private, so its lines are tier 2; a public one's are tier 1"
                    " with --public, for the lines not yet in the record (a line keeps the tier it was"
                    " written at)"
                )
        return visibility


def _archive(
    archive: Path,
    floor: datetime | None,
    owner: Owner,
    counts: dict[str, int],
    report: list[str],
    public: bool,
) -> Iterator[dict[str, Any]]:
    """An account export: each repository's history, then its issues, pull requests, reviews and
    comments, oldest first, each at the tier its repository's mark gives (`_Marks`)."""
    rows = list(_rows(archive, "repositories", report))
    marks = _Marks(rows, public, report)
    for row in rows:
        link = _Link.of(row.get("url"))
        if link.repo is None:
            _count(counts, "skipped_no_url")
            continue
        git_url = _text(row.get("git_url")) or ""  # `tarball://root/repositories/<owner>/<name>.git`
        inside = (
            PurePosixPath(urlsplit(git_url).path.lstrip("/")) if git_url.startswith("tarball://") else None
        )
        inside = inside if inside is not None and inside.parts and ".." not in inside.parts else None
        bare = archive.joinpath(*inside.parts) if inside is not None else None  # never outside the export
        if bare is None or not _is_repository(bare):
            report.append(f"{link.repo}: its repository is not in the export; its commits are not read")
            continue
        web = str(row["url"]).rstrip("/")
        yield from _history(_Git.of(bare), link.repo, web, floor, owner, counts, marks(link.repo))
    acts = sorted(
        _acts(archive, floor, owner, counts, report, marks), key=lambda d: (d["at"], d["payload"]["raw_id"])
    )
    yield from acts


def _acts(
    archive: Path,
    floor: datetime | None,
    owner: Owner,
    counts: dict[str, int],
    report: list[str],
    marks: Callable[[str], str],
) -> Iterator[dict[str, Any]]:
    """The export's issues, pull requests, reviews and comments as the lines `sync github` writes, each
    at the tier of its repository's visibility (`marks`)."""
    closers: dict[tuple[str, bool, int, str], Who | None] = {}
    for row in _rows(archive, "issue_events", report):
        event = _text(row.get("event"))
        link = _Link.of(row.get("pull_request") or row.get("issue"))
        if (
            event in (CLOSED, MERGED)
            and link.repo is not None
            and link.number is not None
            and link.pull is not None
        ):
            closers[(link.repo.lower(), link.pull, link.number, event)] = _person(row.get("actor"))
    titles: dict[tuple[str, int], str] = {}
    items = [*_rows(archive, "issues", report), *_rows(archive, "pull_requests", report)]
    for row in items:
        link = _Link.of(row.get("url"))
        title = _text(row.get("title"))
        if link.repo is not None and link.number is not None and title is not None:
            titles[(link.repo.lower(), link.number)] = title
    for row in items:
        yield from _item(row, floor, owner, counts, closers, marks)

    for row in _rows(archive, "issue_comments", report):
        link = _Link.of(row.get("url"))
        parent = _Link.of(row.get("pull_request") or row.get("issue") or row.get("url"))
        comment_id, at = link.id("comment"), instant(row.get("created_at"))
        if parent.repo is None or parent.number is None or comment_id is None or at is None:
            _count(counts, "skipped_bad_row")
            continue
        if _since(at, floor):
            body = _body(row)
            yield line(
                at,
                f"{parent.repo.lower()}/issues/comments/{comment_id}",
                titles.get((parent.repo.lower(), parent.number)) or f"#{parent.number}",
                instant(row.get("updated_at")) or at,
                COMMENTED,
                parent.repo,
                _person(row.get("user")),
                owner,
                counts,
                notes=body,
                refs={**item_ref(bool(parent.pull), parent.number, None), "comment": _ref(comment_id, row)},
                agent=is_agent(body),
                visibility=marks(parent.repo),
            )
    for row in _rows(archive, "pull_request_reviews", report):
        link = _Link.of(row.get("url"))
        parent = _Link.of(row.get("pull_request") or row.get("url"))
        review_id = link.id("review")
        at = instant(row.get("submitted_at")) or instant(row.get("created_at"))
        state = row.get("state") if isinstance(row.get("state"), str) else None
        if state is not None and state.casefold() == "pending":
            _count(counts, "skipped_pending_review")
            continue
        if parent.repo is None or parent.number is None or review_id is None or at is None:
            _count(counts, "skipped_bad_row")
            continue
        if _since(at, floor):
            reference: dict[str, Any] = {"id": review_id}
            if state is not None:
                reference["state"] = state.casefold()
            reference.update({k: v for k, v in _ref(review_id, row).items() if k == "url"})
            body = _body(row)
            yield line(
                at,
                f"{parent.repo.lower()}/pull/{parent.number}/reviews/{review_id}",
                titles.get((parent.repo.lower(), parent.number)) or f"#{parent.number}",
                at,
                REVIEWED,
                parent.repo,
                _person(row.get("user")),
                owner,
                counts,
                notes=body,
                refs={**item_ref(True, parent.number, None), "review": reference},
                agent=is_agent(body),
                visibility=marks(parent.repo),
            )
    for row in _rows(archive, "pull_request_review_comments", report):
        link = _Link.of(row.get("url"))
        parent = _Link.of(row.get("pull_request") or row.get("url"))
        comment_id, at = link.id("inline"), instant(row.get("created_at"))
        if parent.repo is None or parent.number is None or comment_id is None or at is None:
            _count(counts, "skipped_bad_row")
            continue
        if _since(at, floor):
            extra: dict[str, Any] = {}
            path = _text(row.get("path"))
            if path is not None:
                extra["path"] = path
            review_id = _Link.of(row.get("pull_request_review")).id("review")
            if review_id is not None:
                extra["review"] = {"id": review_id}
            body = _body(row)
            yield line(
                at,
                f"{parent.repo.lower()}/pulls/comments/{comment_id}",
                titles.get((parent.repo.lower(), parent.number)) or f"#{parent.number}",
                instant(row.get("updated_at")) or at,
                COMMENTED,
                parent.repo,
                _person(row.get("user")),
                owner,
                counts,
                notes=body,
                refs={**item_ref(True, parent.number, None), "comment": _ref(comment_id, row)},
                extra=extra,
                agent=is_agent(body),
                visibility=marks(parent.repo),
            )


def _item(
    row: Mapping[str, Any],
    floor: datetime | None,
    owner: Owner,
    counts: dict[str, int],
    closers: Mapping[tuple[str, bool, int, str], Who | None],
    marks: Callable[[str], str],
) -> Iterator[dict[str, Any]]:
    """An issue's or a pull request's lines: created, then closed or merged, at its repository's tier."""
    link = _Link.of(row.get("url"))
    created = instant(row.get("created_at"))
    if link.repo is None or link.number is None or link.pull is None or created is None:
        _count(counts, "skipped_bad_row")
        return
    repo, pull, number = link.repo, link.pull, link.number
    visibility = marks(repo)
    title, body, url = _text(row.get("title")), _body(row), _text(row.get("url"))
    agent = pull and is_agent(body)
    closed, merged = instant(row.get("closed_at")), instant(row.get("merged_at")) if pull else None
    updated = instant(row.get("updated_at")) or merged or closed or created
    labels = [name for name in map(_label, row.get("labels") or []) if name is not None]
    if _since(created, floor):
        yield line(
            created,
            item_key(repo, pull, number, CREATED),
            title,
            updated,
            CREATED,
            repo,
            _person(row.get("user")),
            owner,
            counts,
            notes=body,
            refs=item_ref(pull, number, url),
            extra={"labels": labels} if labels else None,
            agent=agent,
            visibility=visibility,
        )
    if merged is not None and _since(merged, floor):
        extra = {
            k: v for k, v in (("base", _ref_name(row.get("base"))), ("head", _ref_name(row.get("head")))) if v
        }
        yield line(
            merged,
            item_key(repo, True, number, MERGED),
            title,
            updated,
            MERGED,
            repo,
            closers.get((repo.lower(), True, number, MERGED)),
            owner,
            counts,
            refs=item_ref(True, number, url),
            extra=extra,
            agent=agent,
            visibility=visibility,
        )
    elif merged is None and closed is not None and _since(closed, floor):
        yield line(
            closed,
            item_key(repo, pull, number, CLOSED, closed),
            title,
            updated,
            CLOSED,
            repo,
            closers.get((repo.lower(), pull, number, CLOSED)),
            owner,
            counts,
            refs=item_ref(pull, number, url),
            agent=agent,
            visibility=visibility,
        )


def _since(when: datetime, floor: datetime | None) -> bool:
    """An act at or after `floor`, or any act when there is none."""
    return floor is None or when >= floor


def _ref(item_id: int, row: Mapping[str, Any]) -> dict[str, Any]:
    url = _text(row.get("url"))
    return {"id": item_id, "url": url} if url is not None else {"id": item_id}


def _body(row: Mapping[str, Any]) -> str | None:
    body = row.get("body")
    return body if isinstance(body, str) and body.strip() else None


def _label(value: object) -> str | None:
    """A label's name: the export's link to it (`…/labels/<name>`) or an object with a `name`."""
    if isinstance(value, dict):
        return _text(value.get("name"))
    if isinstance(value, str) and "/labels/" in value:
        return _text(unquote(value.rsplit("/labels/", 1)[1]))
    return None


def _ref_name(value: object) -> str | None:
    return _text(value.get("ref")) if isinstance(value, dict) else None
