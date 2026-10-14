"""The owner's Google contacts as a name source for `people review --from-google`: names, never lines.

A **name source** is somewhere the review can find a name for an observed person: the person the record
saw as an address or a number, not yet placed. The owner's Google contacts are the first. The People API
v1 is read as the owner, through the service account the Google sources share (`service_account`:
LOGBOOK_DRIVE_SA_KEY, LOGBOOK_DRIVE_USER), read-only, one scope per address book (`service_account.NAMES`):

- **contacts** (`people/me/connections`, scope `contacts.readonly`): the people the owner saved;
- **other contacts** (`otherContacts`, scope `contacts.other.readonly`): the ones Google saved for the
  owner from mail exchanged, often an address and a name and nothing more.

Of each, only what a review weighs is kept: the display name (the primary one), the addresses (case
aside), the numbers (Google's E.164 form when it has one, else as entered) and the photo as a reference,
its URL, never fetched. A book whose scope the delegation does not grant is left out and said
(`refused`); both refused is an error naming the scopes.

**Nothing here is a line.** No contact is written to the record, by this module or by the review: a
contact is evidence for a proposal and a name the owner may give, and only what the owner accepts is
written, as the review's own lines (`people_review`). What the record holds after an accept is the
identifiers the record had already seen and the name; a contact's other addresses and numbers, its photo
and its resource name never reach a line.

**The cache.** The contacts read are kept in `state/google-contacts.json` (`CACHE`): bookkeeping, like the
sync watermarks, never the record, written whole and at mode 600 where the system has modes. A review
within `TTL` (24 hours) of the read uses it and asks Google nothing, so the numbers a listing shows are
the ones an `--accept` that follows acts on; after that, or for another user than the one it was read
as, the next `--from-google` reads the books again. Delete the file to read them again sooner. Nothing
prints the cache: a review shows a contact's name, the one identifier a proposal matched, and whether it
has a photo, never the rest.

**A no about a contact.** Rejecting a proposal that would name an observed person after a contact writes
no line, since the contact is not in the record: the proposal's id, a digest that names no one, is kept
in `state/google-contacts-review.json` (`REJECTED`), and the proposal is not made again while it is
there. Delete the file and they come back."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import stat
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import people_merge
from .adapters import service_account
from .adapters.service_account import Account, ScopeRefused

__all__ = [
    "CACHE",
    "REJECTED",
    "TTL",
    "Book",
    "Contact",
    "Duplicate",
    "duplicates",
    "keys",
    "load",
    "read",
    "reject",
    "rejected",
]

CACHE = Path("state") / "google-contacts.json"
REJECTED = Path("state") / "google-contacts-review.json"
TTL = timedelta(hours=24)
VERSION = 1
CONTACTS, OTHER = service_account.NAMES  # "contacts", "other contacts"
FIELDS = "names,emailAddresses,phoneNumbers,photos"
PAGE_SIZE = 1000  # the People API's largest page for both books
API = "https://people.googleapis.com/v1/"
BOOKS = (  # (book, url, the parameter naming the fields, the key the page lists them under)
    (CONTACTS, f"{API}people/me/connections", "personFields", "connections"),
    (OTHER, f"{API}otherContacts", "readMask", "otherContacts"),
)

Ref = tuple[str, str]


@dataclass(frozen=True)
class Contact:
    """One contact as the review weighs it. The resource name and the photo's URL are never printed."""

    id: str = field(repr=False)  # the People API's resource name: people/c…, otherContacts/c…
    book: str  # CONTACTS or OTHER
    name: str | None
    emails: tuple[str, ...] = ()
    phones: tuple[str, ...] = ()
    photo: str | None = field(default=None, repr=False)  # a reference, never fetched

    def to_json(self) -> dict[str, Any]:
        """The cache's form, whole: for state/, never for printing."""
        return {
            "id": self.id,
            "book": self.book,
            "name": self.name,
            "emails": list(self.emails),
            "phones": list(self.phones),
            "photo": self.photo,
        }

    def shown(self) -> dict[str, Any]:
        """What a review may print of it: the name, the book, whether it has a photo."""
        return {"name": self.name, "book": self.book, "photo": self.photo is not None}

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Contact | None:
        if not isinstance(data.get("id"), str) or data.get("book") not in (CONTACTS, OTHER):
            return None
        name = data.get("name")
        photo = data.get("photo")
        return cls(
            str(data["id"]),
            str(data["book"]),
            name if isinstance(name, str) and name else None,
            tuple(str(e) for e in data.get("emails") or [] if isinstance(e, str)),
            tuple(str(p) for p in data.get("phones") or [] if isinstance(p, str)),
            photo if isinstance(photo, str) and photo else None,
        )


@dataclass(frozen=True)
class Book:
    """The contacts a review weighs: when they were read, whether from the cache, and the books whose
    scope the delegation does not grant."""

    contacts: tuple[Contact, ...]
    read_at: str
    cached: bool
    refused: tuple[str, ...] = ()

    def counts(self) -> dict[str, int]:
        return {book: sum(1 for c in self.contacts if c.book == book) for book, *_rest in BOOKS}

    def to_json(self) -> dict[str, Any]:
        return {
            "read_at": self.read_at,
            "cached": self.cached,
            "ttl_hours": int(TTL.total_seconds() // 3600),
            "books": self.counts(),
            "refused": list(self.refused),
        }


# -- reading the books ---------------------------------------------------------------------------------


def load(
    root: Path,
    account: Account,
    now: datetime | None = None,
    fetch: Callable[[Account], tuple[list[Contact], list[str]]] | None = None,
) -> Book:
    """The contacts for a review: the cache when it was read within TTL for this user, else both books
    read again (`fetch`, `read` by default) and the cache written. Raises service_account.GoogleError
    (an OSError) when Google cannot be read."""
    when = now or _now()
    path = root.joinpath(*CACHE.parts)
    cached = _cached(path, account, when)
    if cached is not None:
        return cached
    contacts, refused = (fetch or read)(account)
    stamp = _z(when)
    _write(
        path,
        {
            "version": VERSION,
            "user": _user(account),
            "read_at": stamp,
            "refused": refused,
            "contacts": [c.to_json() for c in contacts],
        },
    )
    return Book(tuple(contacts), stamp, cached=False, refused=tuple(refused))


def read(account: Account) -> tuple[list[Contact], list[str]]:
    """Both books, every page, and the books whose scope is refused; GoogleError when both are."""
    contacts: list[Contact] = []
    refused: list[str] = []
    problems: list[ScopeRefused] = []
    for book, url, fields, key in BOOKS:
        session = service_account.Session(account, service_account.SCOPES[book])
        params = {fields: FIELDS, "pageSize": str(PAGE_SIZE)}
        try:
            for page in _pages(session, url, params, key):
                contacts.extend(c for raw in page if (c := person(raw, book)) is not None)
        except ScopeRefused as e:
            refused.append(book)
            problems.append(e)
    if len(refused) == len(BOOKS):
        scopes = " and ".join(service_account.SCOPES[book] for book in refused)
        raise service_account.GoogleError(
            f"neither address book can be read: domain-wide delegation grants neither {scopes}"
        )
    return contacts, refused


def _pages(
    session: service_account.Session, url: str, params: dict[str, str], key: str
) -> Iterator[list[dict[str, Any]]]:
    asked = dict(params)
    while True:
        page = session.get_json(url, asked)
        yield [x for x in page.get(key) or [] if isinstance(x, dict)]
        token = page.get("nextPageToken")
        if not isinstance(token, str) or not token:
            return
        asked = {**params, "pageToken": token}


def person(raw: Mapping[str, Any], book: str) -> Contact | None:
    """A People API person as a Contact; None for one with no resource name."""
    resource = raw.get("resourceName")
    if not isinstance(resource, str) or not resource:
        return None
    names = [n for n in raw.get("names") or [] if isinstance(n, dict) and _text(n.get("displayName"))]
    primary = next(
        (n for n in names if (n.get("metadata") or {}).get("primary")), names[0] if names else None
    )
    emails: list[str] = []
    for entry in raw.get("emailAddresses") or []:
        value = _text(entry.get("value")) if isinstance(entry, dict) else None
        if value and value.casefold() not in emails:
            emails.append(value.casefold())
    phones: list[str] = []
    for entry in raw.get("phoneNumbers") or []:
        if not isinstance(entry, dict):
            continue
        value = _text(entry.get("canonicalForm")) or _text(entry.get("value"))
        if value and value not in phones:
            phones.append(value)
    photo = next(
        (
            str(p["url"])
            for p in raw.get("photos") or []
            if isinstance(p, dict) and isinstance(p.get("url"), str) and not p.get("default")
        ),
        None,
    )
    return Contact(
        resource,
        book,
        _text(primary.get("displayName")) if primary is not None else None,
        tuple(emails),
        tuple(phones),
        photo,
    )


def _cached(path: Path, account: Account, now: datetime) -> Book | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        read_at = datetime.fromisoformat(str(data["read_at"]).replace("Z", "+00:00"))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("version") != VERSION or data.get("user") != _user(account):
        return None
    if not timedelta(0) <= now - read_at <= TTL:
        return None
    contacts = tuple(
        c for raw in data.get("contacts") or [] if isinstance(raw, dict) and (c := Contact.from_json(raw))
    )
    refused = tuple(str(b) for b in data.get("refused") or [] if b in (CONTACTS, OTHER))
    return Book(contacts, _z(read_at), cached=True, refused=refused)


def _user(account: Account) -> str:
    """Which user the cache was read as: a digest, so the file does not spell the address."""
    return hashlib.sha256(account.user.strip().casefold().encode("utf-8")).hexdigest()[:16]


# -- what a review weighs ------------------------------------------------------------------------------


def keys(contact: Contact, prefix: str) -> frozenset[Ref]:
    """The contact's addresses and numbers as the review keys an identifier: (`email`, the address case
    aside), (`phone`, E.164); a number that does not read as one is left out."""
    found: set[Ref] = set()
    for email in contact.emails:
        key = people_merge._email_key(("email", email))
        if key is not None:
            found.add(key)
    for phone in contact.phones:
        key = people_merge._phone_key(("phone", phone), prefix)
        if key is not None:
            found.add(key)
    return frozenset(found)


@dataclass(frozen=True)
class Duplicate:
    """Contacts that share an address or a number: proposed as one person, merged only in Google."""

    contacts: tuple[Contact, ...]
    evidence: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {"contacts": [c.shown() for c in self.contacts], "evidence": list(self.evidence)}


def duplicates(contacts: Sequence[Contact], prefix: str) -> list[Duplicate]:
    """The contacts that share an address or a number, each group once (two that share one, and a
    third that shares another with either, are one group), with what they share; by name."""
    parent = list(range(len(contacts)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    holders: dict[Ref, list[int]] = {}
    for i, contact in enumerate(contacts):
        for key in keys(contact, prefix):
            holders.setdefault(key, []).append(i)
    for held in holders.values():
        for i in held[1:]:
            parent[root(i)] = root(held[0])
    groups: dict[int, list[int]] = {}
    for i in range(len(contacts)):
        groups.setdefault(root(i), []).append(i)
    sharing: dict[int, list[Ref]] = {}
    for key, held in holders.items():
        if len(held) > 1:
            sharing.setdefault(root(held[0]), []).append(key)
    found = []
    for group, members in groups.items():
        if len(members) < 2:
            continue
        shared = sorted(sharing.get(group, []))
        ordered = sorted(
            (contacts[i] for i in members), key=lambda c: ((c.name or "").casefold(), c.book, c.id)
        )
        found.append(Duplicate(tuple(ordered), tuple(f"same {kind} {value}" for kind, value in shared)))
    return sorted(found, key=lambda d: ((d.contacts[0].name or "").casefold(), d.evidence))


# -- the owner's no ------------------------------------------------------------------------------------


def rejected(root: Path) -> frozenset[str]:
    """The ids of the contact proposals the owner rejected."""
    try:
        data = json.loads(root.joinpath(*REJECTED.parts).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    found = data.get("rejected") if isinstance(data, dict) else None
    return frozenset(str(k) for k in found) if isinstance(found, dict) else frozenset()


def reject(root: Path, ids: Iterable[str], at: str) -> Path:
    """Keep these proposal ids as rejected, beside the ones already kept; the file's path."""
    path = root.joinpath(*REJECTED.parts)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        kept = dict(data.get("rejected") or {}) if isinstance(data, dict) else {}
    except (OSError, ValueError):
        kept = {}
    for proposal in ids:
        kept.setdefault(proposal, at)
    _write(path, {"rejected": dict(sorted(kept.items()))})
    return path


# -- files ----------------------------------------------------------------------------------------------


def _write(path: Path, data: dict[str, Any]) -> None:
    """Whole, never half-written: a temporary beside it, owner-only where the system has modes, then
    one rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes((json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    if os.name == "posix":
        with contextlib.suppress(OSError):
            tmp.chmod(stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp, path)


def _now() -> datetime:
    return datetime.now(UTC)  # a test puts its own clock here


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return " ".join(value.split()) or None


def _z(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
