"""Gmail → mail/v1 (RFC 0015), live: `logbook sync gmail` reads the owner's mailbox over the API, read-only.

The Gmail API v1 as the owner, on the one Google service-account key every Google source shares
(`service_account`: LOGBOOK_DRIVE_SA_KEY, LOGBOOK_DRIVE_USER, domain-wide delegation), with one scope,
`gmail.readonly`: the client lists, reads and asks for the history, and the scope could do nothing else.
No password, no app password, no refresh token: each run mints an hour's token and keeps it in memory.

**The same line as IMAP.** Every message is fetched whole (`format=raw`, the RFC 822 bytes the mailbox
stores, the bytes IMAP's `BODY[]` gives) and goes through `mail.parse_message`, the mbox adapter's own
parser, as `sync mail` (`mail_imap`) does: Gmail's internal date where IMAP gives INTERNALDATE (the
fallback when the `Date` header is missing or unreadable), the account the address the key reads as,
every attachment named, sized and digested (`sha256`, the bytes are in hand) and never stored, the body
the parser's own (the text part, else the HTML stripped, at most 64 KB of it). So the line is the one the
IMAP source writes for that message — `source` `mail`, `raw_id` `<account>:<Message-ID>` — and a mailbox
synced over IMAP yesterday and over the API today writes nothing twice, whichever came first; a Takeout
dedupes against both, imported with `--account` or without (`held`, by normalised Message-ID).
`SOURCE` says so to `sync`, which counts what the record holds by it.

**Labels**, as the IMAP source spells Gmail's X-GM-LABELS (`mail.gmail_fields`, the one function both
use): the system labels `INBOX`, `SENT`, `IMPORTANT` and `STARRED` as `Inbox`, `Sent`, `Important` and
`Starred`, every label of the owner's by its name (`Boat/Engine` for a nested one), in the API's order,
under `payload.labels`, the profile's slot; the thread id under `extra.gmail_thread_id` in decimal, as
X-GM-THRID and Takeout spell the number the API gives in hex. Dropped, because IMAP never shows them and
the line would differ: `UNREAD` (a flag, not a label), the category tabs (`CATEGORY_*`) and any label the
label list does not name. Labels are the mailbox's state when the message is read, taken once; a label
changed later is never revisited.

**What is not a line.** A draft (`DRAFT`: neither sent nor received, and a draft's Message-ID is often
the one its sent message will carry) is skipped and counted (`skipped_draft`); a message in Spam or Trash
(`skipped_spam_or_trash`, which the history can name though the list never does); one deleted between
being listed and being read (`skipped_gone`).

**Headers first.** Each page of message ids is read as metadata (`format=metadata`, the Message-ID
header alone), the record is asked which of those messages it holds by normalised Message-ID, from any
mail road (`held`, `logbook.contrib.mail_lookup`; without it `existing`, the keys `(mail,
<account>:<Message-ID>)` alone), and only the rest are fetched whole: a mailbox the IMAP source or a Takeout
already wrote costs one small request per message and no body. The progress line per page says what is
true: listed, new, already in the record.

**The watermark: the history id, else the internal date.** The state (`RESUMES`: kept under `resume` in
`state/gmail.json` and written only once the lines up to it are in the record) is `{history_id,
internal_date}`: the mailbox's history id taken from the profile before anything is listed (so nothing
that arrives during a run is missed) and the newest internal date of a message handled. A run with a
history id asks the history for the messages added since (`history.list`, `messageAdded`) and lists
nothing; when Gmail no longer keeps that history (404, after about a week) it says so and lists the
messages received from a day (`LOOKBACK_H`) before the newest internal date (`q=after:<epoch>`), and
the record refuses what it holds. Without a state, the first run lists every message; give `--since`
for a shorter one, which then leaves a mark (its time as the newest date when nothing came after it, so
a later list by date never reaches back past it). `--since` on a later run lists from that time for that run
and leaves the mark alone; `--restart` drops it and lists everything again (the record still refuses
what it holds); `--dry-run` reads and counts and writes nothing.

Every page, message and history call goes through the service account's session: paged, retried with
a doubling wait on 429, 5xx and rate-limit 403s (`Retry-After` honoured), one plain line on anything
else. Network happens only inside `pull`, which only `logbook sync gmail` calls (ADR 0012). When to use
this source and when `sync mail` (IMAP): the tour's *Google, on one key* and docs/adapters/mail.md."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from . import mail, service_account
from .service_account import Account, ApiError

if TYPE_CHECKING:
    from . import Walk

__all__ = [
    "ENV",
    "KIND",
    "NAME",
    "RESUMES",
    "SCHEMA",
    "SCOPE",
    "SOURCE",
    "TIER",
    "UNIT",
    "check",
    "configure",
    "describe",
    "pull",
    "watermark",
]

NAME = "gmail"
SOURCE = mail.NAME  # the lines are the mail source's: IMAP, Takeout and this dedupe each other
KIND = mail.KIND
SCHEMA = mail.SCHEMA
TIER = mail.TIER
UNIT = "messages"  # what `sync` counts
ENV = service_account.ENV
RESUMES = True  # the checkpoint `sync` keeps is this source's lasting state: the history id, the date
SCOPE = service_account.SCOPES["gmail"]
API = "https://gmail.googleapis.com/gmail/v1/users/me"
PAGE_SIZE = 500  # the most the API lists in one page
LOOKBACK_H = 24.0  # reading by date starts this long before the newest message handled
SYSTEM_LABELS = {"INBOX": "Inbox", "SENT": "Sent", "IMPORTANT": "Important", "STARRED": "Starred"}
DRAFT = "DRAFT"
HIDDEN = frozenset({"SPAM", "TRASH"})
ALREADY = "already_in_record"  # the key `sync mail` counts the same thing under
EXPIRED = "the history id is older than Gmail keeps; reading by date from a day before the newest message"

configure = service_account.configure


def check(config: Account) -> str:
    """What `doctor` says after `configured`: the key read and loadable, no network asked."""
    return service_account.describe(config)


def watermark(draft: dict[str, Any]) -> str | None:
    """None: the state is the history id and the newest internal date, kept through the checkpoint."""
    return None


def describe(checkpoint: dict[str, Any]) -> list[str]:
    """The mark as `sync` prints it after the summary."""
    history, newest = checkpoint.get("history_id"), checkpoint.get("internal_date")
    if not history and not newest:
        return []
    return [f"history id {history or '-'}, newest message {newest or '-'}"]


@dataclass(frozen=True)
class Head:
    """What the metadata says of one message before its body is asked for."""

    id: str
    message_id: str | None
    labels: tuple[str, ...]
    internal: datetime | None


def pull(
    config: Account,
    since: str | None = None,
    progress: Callable[[int, float], None] | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
    owner_emails: Iterable[str] | None = None,
    existing: Callable[[Iterable[tuple[str, str]]], set[tuple[str, str]]] | None = None,
    walk: Walk | None = None,
    notice: Callable[[str], None] | None = None,
    held: mail.Held | None = None,
    wait_on_limits: bool = True,
) -> Iterator[dict[str, Any]]:
    """One mail/v1 line draft per message the record does not hold, page by page, newest first within
    the list. `since` (RFC3339) lists the messages received from then on for this run. `walk` is
    `sync`'s checkpoint keeper: its `start()` holds the mark, `reached(ordinal, mark)` is told once the
    last page is read. `held` is the record's answer by Message-ID, from any mail road
    (`logbook.contrib.mail_lookup`): asked for a page's heads before any body is fetched, and again for
    the bodies read, now with their `at`; without it, `existing` answers for this source's own (source,
    raw_id) keys alone. `notice` prints one line per page; `progress` is not used, since that line is
    the progress and names no total. Raises service_account.GoogleError (an OSError) with one plain
    sentence."""
    counts = counts if counts is not None else {}
    say = notice if notice is not None else (lambda _text: None)
    account = config.user.strip().lower()
    owners = {e.strip().lower() for e in (owner_emails or []) if e.strip()}
    owners.add(account)
    saved = walk.start() if walk is not None else None
    stored_history, stored_newest = _mark(saved)
    session = service_account.Session(config, SCOPE, wait_on_limits)
    history = str(session.get_json(f"{API}/profile", {}).get("historyId") or "") or None
    names = _label_names(session)
    newest = stored_newest
    ordinal = listed = new = already = 0
    for page in _pages(session, since, stored_history, stored_newest, say):
        heads = [head for message_id in page if (head := _head(session, message_id, counts)) is not None]
        listed += len(page)
        for head in heads:
            if head.internal is not None and (newest is None or head.internal > newest):
                newest = head.internal
        wanted = _wanted(heads, counts)
        if held is not None:
            fetch = _not_held(wanted, account, held, counts)
        else:
            keys = {(SOURCE, f"{account}:{h.message_id}") for h in wanted if h.message_id is not None}
            refused = existing(keys) if existing is not None and keys else set()
            fetch = [
                h
                for h in wanted
                if h.message_id is None or (SOURCE, f"{account}:{h.message_id}") not in refused
            ]
            _count(counts, ALREADY, len(wanted) - len(fetch))
        already += len(wanted) - len(fetch)
        read = [
            line
            for head in fetch
            if (line := _line(session, head, counts, timezone, owners, account, names)) is not None
        ]
        kept = mail.unheld(read, held, counts)  # read now, so known by their days too
        already += len(read) - len(kept)
        for line in kept:
            ordinal += 1
            new += 1
            yield line
        say(f"{listed:,} listed, {new:,} new, {already:,} already in the record")
    if newest is None and since is not None:  # nothing from `since` on: a later list by date starts there
        newest = _instant(since)
    if walk is not None and (since is None or saved is None):  # --since on a later run leaves the mark
        walk.reached(ordinal, _checkpoint(history or stored_history, newest))


def _mark(saved: dict[str, Any] | None) -> tuple[str | None, datetime | None]:
    """The stored history id and newest internal date, each only when it is the shape."""
    if not isinstance(saved, dict):
        return None, None
    history = saved.get("history_id")
    history = str(history) if isinstance(history, str | int) and str(history).isdigit() else None
    newest = None
    if isinstance(saved.get("internal_date"), str):
        try:
            newest = datetime.fromisoformat(saved["internal_date"].replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            newest = None
    return history, newest


def _checkpoint(history: str | None, newest: datetime | None) -> dict[str, Any]:
    return {"history_id": history, "internal_date": _z(newest) if newest is not None else None}


def _pages(
    session: service_account.Session,
    since: str | None,
    history: str | None,
    newest: datetime | None,
    say: Callable[[str], None],
) -> Iterator[list[str]]:
    """The message ids to read, a page at a time: from `since` when given; else the history since the
    stored id, or, when Gmail no longer keeps it, the list from a day before the newest message; else
    every message."""
    if since is not None:
        yield from _listed(session, _instant(since))
        return
    if history is not None:
        try:
            first = _history_page(session, history, None)
        except ApiError as e:
            if e.status != 404:
                raise
            say(EXPIRED)
        else:
            yield from _history(session, history, first)
            return
    if newest is not None:
        yield from _listed(session, newest - timedelta(hours=LOOKBACK_H))
        return
    yield from _listed(session, None)


def _listed(session: service_account.Session, after: datetime | None) -> Iterator[list[str]]:
    """Every message id the list gives (Spam and Trash left out by the API), from `after` on."""
    params = {"maxResults": str(PAGE_SIZE)}
    if after is not None:
        params["q"] = f"after:{int(after.timestamp()) - 1}"  # Gmail's `after:` is strict, in seconds
    token: str | None = None
    while True:
        query = dict(params, pageToken=token) if token is not None else params
        page = session.get_json(f"{API}/messages", query)
        yield [str(m["id"]) for m in page.get("messages") or [] if isinstance(m, dict) and m.get("id")]
        token = page.get("nextPageToken") or None
        if not isinstance(token, str):
            return


def _history_page(session: service_account.Session, start: str, token: str | None) -> dict[str, Any]:
    params = {"startHistoryId": start, "historyTypes": "messageAdded", "maxResults": str(PAGE_SIZE)}
    if token is not None:
        params["pageToken"] = token
    return session.get_json(f"{API}/history", params)


def _history(session: service_account.Session, start: str, page: dict[str, Any]) -> Iterator[list[str]]:
    """The ids of the messages added since the history id `start`, each once, page by page."""
    seen: set[str] = set()
    while True:
        ids: list[str] = []
        for record in page.get("history") or []:
            for added in record.get("messagesAdded") or [] if isinstance(record, dict) else []:
                message = added.get("message") if isinstance(added, dict) else None
                if isinstance(message, dict) and message.get("id") and str(message["id"]) not in seen:
                    seen.add(str(message["id"]))
                    ids.append(str(message["id"]))
        yield ids
        token = page.get("nextPageToken")
        if not isinstance(token, str) or not token:
            return
        page = _history_page(session, start, token)


def _head(session: service_account.Session, message_id: str, counts: dict[str, int]) -> Head | None:
    """The message's Message-ID, labels and internal date, from its metadata; None when it is gone."""
    try:
        data = session.get_json(
            f"{API}/messages/{message_id}", {"format": "metadata", "metadataHeaders": "Message-ID"}
        )
    except ApiError as e:
        if e.status != 404:
            raise
        _count(counts, "skipped_gone")
        return None
    headers = (data.get("payload") or {}).get("headers") or []
    value = next(
        (str(h.get("value") or "") for h in headers if str(h.get("name") or "").lower() == "message-id"),
        None,
    )
    return Head(
        id=message_id,
        message_id=mail.first_id(value),
        labels=tuple(str(label) for label in data.get("labelIds") or []),
        internal=_internal(data.get("internalDate")),
    )


def _not_held(heads: list[Head], account: str, held: mail.Held, counts: dict[str, int]) -> list[Head]:
    """The heads whose bodies are to be fetched: every one the record does not hold by its Message-ID,
    from any mail road; one it holds is counted, `ALREADY` under this source's own key, by its holder's
    mailbox under another (`mail.count_held`). A head without a Message-ID is fetched: the store's own
    key is its dedupe."""
    asked = {n: q for n, head in enumerate(heads) if (q := mail.ask(head.message_id, account)) is not None}
    holders = dict(zip(asked, held(list(asked.values())), strict=True)) if asked else {}
    fetch: list[Head] = []
    for n, head in enumerate(heads):
        holder = holders.get(n)
        if holder is None:
            fetch.append(head)
        elif holder.own:
            _count(counts, ALREADY)
        else:
            mail.count_held(counts, holder)
    return fetch


def _wanted(heads: list[Head], counts: dict[str, int]) -> list[Head]:
    """The messages that are lines: no draft, nothing in Spam or Trash."""
    wanted: list[Head] = []
    for head in heads:
        if DRAFT in head.labels:
            _count(counts, "skipped_draft")
        elif HIDDEN & set(head.labels):
            _count(counts, "skipped_spam_or_trash")
        else:
            wanted.append(head)
    return wanted


def _line(
    session: service_account.Session,
    head: Head,
    counts: dict[str, int],
    timezone: str | None,
    owners: set[str],
    account: str,
    names: dict[str, str],
) -> dict[str, Any] | None:
    """The message read whole and parsed as the IMAP source parses it; None when it is gone, or has
    neither a Date header nor an internal date."""
    try:
        data = session.get_json(f"{API}/messages/{head.id}", {"format": "raw"})
    except ApiError as e:
        if e.status != 404:
            raise
        _count(counts, "skipped_gone")
        return None
    raw = _bytes(data.get("raw"))
    labels = [str(label) for label in data.get("labelIds") or head.labels]
    line, _blobs = mail.parse_message(
        raw,
        _internal(data.get("internalDate")) or head.internal,
        counts,
        timezone or "UTC",
        None,
        owners,
        account,
        digest_attachments=True,
        fallback_name="internaldate",
    )
    if line is None:
        return None
    mail.gmail_fields(line["payload"], _labels(labels, names), _thread(data.get("threadId")))
    return line


def _label_names(session: service_account.Session) -> dict[str, str]:
    """The owner's own labels by id; the system ones are spelled by `SYSTEM_LABELS`."""
    found = session.get_json(f"{API}/labels", {}).get("labels") or []
    return {
        str(label["id"]): str(label["name"])
        for label in found
        if isinstance(label, dict) and label.get("type") == "user" and label.get("id") and label.get("name")
    }


def _labels(ids: list[str], names: dict[str, str]) -> list[str]:
    """The labels as IMAP's X-GM-LABELS gives them: the four system labels it shows, the owner's by name."""
    labels: list[str] = []
    for label_id in ids:
        name = SYSTEM_LABELS.get(label_id) or names.get(label_id)
        if name and name not in labels:
            labels.append(name)
    return labels


def _thread(value: Any) -> str | None:
    """Gmail's thread id in decimal, as X-GM-THRID and Takeout spell the number the API gives in hex."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return str(int(value, 16))
    except ValueError:
        return value


def _bytes(value: Any) -> bytes:
    """The `raw` field: base64url, padded or not."""
    if not isinstance(value, str):
        return b""
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError):
        return b""


def _internal(value: Any) -> datetime | None:
    """Gmail's internal date, milliseconds since the epoch as a string, as an aware UTC datetime."""
    try:
        return datetime.fromtimestamp(int(str(value)) / 1000, UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _instant(text: str) -> datetime:
    when = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    return (when if when.tzinfo is not None else when.replace(tzinfo=UTC)).astimezone(UTC)


def _z(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _count(counts: dict[str, int], key: str, n: int = 1) -> None:
    if n:
        counts[key] = counts.get(key, 0) + n
