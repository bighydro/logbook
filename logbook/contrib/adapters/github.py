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

**The tier.** 1, as SPEC §4 and RFC 0009 give `event/v1`, whoever wrote the words: "an entry whose
notes carry someone else's words is still tier 1 by default". The tier is where a line may travel,
never who wrote it; a comment Ola left is tier 1 as one Ines left is.

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
line's own text carries the marker of an agent's session (`is_agent`).

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
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ...core import policy

__all__ = [
    "AGENT_MARKERS",
    "KIND",
    "NAME",
    "TIER",
    "Owner",
    "Who",
    "is_agent",
    "login_of_address",
]

NAME = "github"
KIND = "event"
TIER = 1  # SPEC §4, RFC 0009: event/v1, whoever wrote the words
SCHEMA = "event/v1"
CALENDAR = {"id": "github", "name": "GitHub"}
COMMITTED, CREATED, CLOSED, MERGED = "committed", "created", "closed", "merged"
REVIEWED, COMMENTED, REVISED = "reviewed", "commented", "revised"
OWNER, OTHER = "owner", "other"
PREFIX = "github:"  # a handle ref's value: `github:<login>`, lower case
NOREPLY = "users.noreply.github.com"  # the domain of the address GitHub commits under when asked to
USER, BOT = "User", "Bot"
AGENT_MARKERS = (
    re.compile(r"Generated (?:with|by) \[?Claude Code\]?", re.IGNORECASE),
    re.compile(r"\bclaude\.ai/code/session_", re.IGNORECASE),
    re.compile(r"^Claude-Session:", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^Co-Authored-By:\s*Claude\b", re.IGNORECASE | re.MULTILINE),
)


def is_agent(text: str | None) -> bool:
    """Whether the text carries the marker of an agent's session (`AGENT_MARKERS`)."""
    return bool(text) and any(marker.search(text or "") for marker in AGENT_MARKERS)


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
) -> dict[str, Any]:
    """One draft: the act, its text, who did it, the thing it was done to."""
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
    payload["extra"] = body
    return {
        "at": stamp(at),
        "end": None,
        "tz": None,  # the record's own
        "source": NAME,
        "kind": KIND,
        "tier": TIER,
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
