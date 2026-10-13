"""A mailbox over IMAP → mail/v1 (RFC 0015), live: `logbook sync mail` reads the owner's mailbox, read-only.

IMAP is a standard, so the first server (Gmail, with an app password) is not the only one. The
configuration is the environment alone: `LOGBOOK_IMAP_HOST`, `LOGBOOK_IMAP_USER` (the mailbox
address, which is the account the lines carry) and `LOGBOOK_IMAP_PASSWORD` (an app password: never
logged, never echoed, never written to any file), `LOGBOOK_IMAP_PORT` (993) and `LOGBOOK_IMAP_FOLDERS`
(comma-separated; without it the folder the server flags `\\All` — Gmail's `[Gmail]/All Mail` — else
INBOX and the `\\Sent` folder). TLS from the first byte (`IMAP4_SSL` with the default verifying
context); never STARTTLS, never plaintext.

Every message goes through `mail.parse_message`, the mbox adapter's own parser, with the server's
INTERNALDATE where the separator's date would stand: the same line, the same `raw_id`
(`<account>:<Message-ID>`), so a Takeout export imported with `--account <address>` and the live pull
of the same mailbox never write a message twice, whichever came first, and a walk after a lost mark
writes nothing new. The watermark is for economy, the record's refusal of a (source, raw_id) it holds
is the guarantee. The body is read under the parser's own cap, and every attachment is named, sized
and digested (`sha256`, the bytes are in hand) and never stored.

Read-only, enforced: a folder is opened with EXAMINE, bodies are fetched with `BODY.PEEK[]` (a plain
`BODY[]` would mark them read), and STORE, COPY, MOVE, EXPUNGE, APPEND and every flag change are
absent from this module; the tests assert on the fake server's command log that none was ever sent.

Per folder the state is `{uidvalidity, uid}`: the folder's UIDVALIDITY and the highest UID handled,
kept by `sync` under `resume` in `state/mail.json` through the checkpoint keeper (`RESUMES`), which
writes a mark only once the lines up to it are in the record, so a connection lost midway leaves the
mark at the last batch written and the next run resumes there. A folder whose UIDVALIDITY changed is
read from its first message again (the record refuses what it holds); `--restart` drops every mark;
`--since RFC3339` searches `SINCE` that day instead (day granularity: the overlap is the record's to
refuse) and still advances the marks; `--dry-run` fetches and counts and writes nothing.

Headers first: each batch of `BATCH` UIDs is fetched as `Message-ID` and size alone, the record is
asked which of those ids it holds (`existing`, one SELECT), and only the bodies of the rest are
fetched, in batches bounded by `BODY_BATCH_BYTES` — so the first run over a 400,000-message All Mail
after a Takeout import asks for no body the record would refuse. The progress line per batch says
what is true: fetched, new, already in the record; never a guessed total. One connection, closed on
the way out, on success and on error alike.

Gmail's labels and thread id (the `X-GM-EXT-1` extension: `X-GM-LABELS`, `X-GM-THRID`) are fetched
with the body and written as the mbox adapter writes Takeout's `X-Gmail-Labels` and `X-GM-THRID`:
`payload.labels` (system labels spelled as Takeout spells them, `Inbox`, `Sent`) and
`extra.gmail_thread_id`. They are the state of the mailbox at ingest, taken once; a label moved
later is never revisited. Without the extension the line carries neither.

Errors are one plain sentence each, naming the variable or the folder and never a value: the login
refused (`LOGBOOK_IMAP_USER`, `LOGBOOK_IMAP_PASSWORD`), TLS failed (`LOGBOOK_IMAP_HOST`), a folder
not on the server (`LOGBOOK_IMAP_FOLDERS`). Network happens only inside `pull`, which only
`logbook sync mail` calls (ADR 0012).
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import imaplib
import re
import socket
import ssl
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from . import mail
from .mail import KIND, NAME, SCHEMA, TIER

if TYPE_CHECKING:
    from . import Walk

__all__ = [
    "ENV",
    "KIND",
    "NAME",
    "RESUMES",
    "SCHEMA",
    "TIER",
    "UNIT",
    "Config",
    "configure",
    "decode_utf7",
    "describe",
    "encode_utf7",
    "open_connection",
    "pull",
    "watermark",
]

HOST_ENV = "LOGBOOK_IMAP_HOST"
USER_ENV = "LOGBOOK_IMAP_USER"
PASSWORD_ENV = "LOGBOOK_IMAP_PASSWORD"
PORT_ENV = "LOGBOOK_IMAP_PORT"
FOLDERS_ENV = "LOGBOOK_IMAP_FOLDERS"
ENV = (HOST_ENV, USER_ENV, PASSWORD_ENV)  # the ones a run needs; the port and the folders have defaults
UNIT = "messages"  # what `sync` counts
RESUMES = True  # the checkpoint `sync` keeps for this source is its lasting resume state, per folder
DEFAULT_PORT = 993
TIMEOUT_S = 120
BATCH = 200  # UIDs per header fetch, and the most bodies in one fetch
BODY_BATCH_BYTES = 32 * 1024 * 1024  # bodies fetched together, by the sizes the header pass reported
GMAIL_EXTENSION = "X-GM-EXT-1"
GMAIL_ITEMS = "X-GM-LABELS X-GM-THRID"
HEADER_ITEMS = "(UID RFC822.SIZE BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])"
ALL_FLAGS = ("\\All", "\\AllMail")  # RFC 6154, and XLIST's spelling
SENT_FLAG = "\\Sent"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
ALREADY = "already_in_record"  # messages the record held already, by Message-ID, so no body was fetched
STARTED_OVER = "folders_started_over"  # a folder whose UIDVALIDITY changed, read from the first message again

UID = re.compile(rb"\bUID (\d+)")
SIZE = re.compile(rb"\bRFC822\.SIZE (\d+)")
THRID = re.compile(rb"\bX-GM-THRID (\d+)")
LABELS = re.compile(rb'\bX-GM-LABELS \(((?:[^()"]|"(?:[^"\\]|\\.)*")*)\)')
INTERNALDATE = re.compile(rb'\bINTERNALDATE "([^"]*)"')
DATE_TIME = re.compile(r"^\s*(\d{1,2})-([A-Za-z]{3})-(\d{4}) (\d\d):(\d\d):(\d\d) ([+-])(\d\d)(\d\d)$")
LIST_LINE = re.compile(rb'^\((?P<flags>[^)]*)\) (?:"(?:[^"\\]|\\.)*"|NIL) (?P<name>"(?:[^"\\]|\\.)*"|\S+)$')
ATOM_OR_QUOTED = re.compile(rb'"((?:[^"\\]|\\.)*)"|([^\s()"]+)')
MESSAGE_HEAD = re.compile(rb"^\d+ \(")
UTF7_SHIFT = re.compile(r"&([^-]*)-")


@dataclass(frozen=True)
class Config:
    host: str
    user: str
    password: str = field(repr=False)
    port: int = DEFAULT_PORT
    folders: tuple[str, ...] | None = None  # None: the server's `\\All` folder, else INBOX and `\\Sent`

    @property
    def account(self) -> str:
        """The mailbox the lines carry and the prefix of their `raw_id` (RFC 0015)."""
        return self.user.strip().lower()


def configure(env: Mapping[str, str]) -> Config | None:
    """Config from LOGBOOK_IMAP_HOST, LOGBOOK_IMAP_USER and LOGBOOK_IMAP_PASSWORD; None when any is
    absent or empty. LOGBOOK_IMAP_PORT must be a port number when set (ValueError names the variable,
    never its value); LOGBOOK_IMAP_FOLDERS is split on commas, blanks dropped."""
    host, user, password = (env.get(name, "") for name in ENV)
    if not host.strip() or not user.strip() or not password:
        return None
    port = DEFAULT_PORT
    raw_port = env.get(PORT_ENV, "").strip()
    if raw_port:
        try:
            port = int(raw_port)
        except ValueError:
            port = 0
        if not 1 <= port <= 65535:
            raise ValueError(f"{PORT_ENV} must be a port number, 1 to 65535")
    folders = tuple(name.strip() for name in env.get(FOLDERS_ENV, "").split(",") if name.strip())
    return Config(host=host.strip(), user=user.strip(), password=password, port=port, folders=folders or None)


def watermark(draft: dict[str, Any]) -> str | None:
    """None: the state is per folder (UIDVALIDITY and UID), kept through the checkpoint, not a clock."""
    return None


def describe(checkpoint: dict[str, Any]) -> list[str]:
    """The marks as `sync` prints them after the summary: one line per folder."""
    folders = checkpoint.get("folders")
    if not isinstance(folders, dict):
        return []
    return [
        f"{decode_utf7(str(name))}: uidvalidity {mark.get('uidvalidity')}, uid {mark.get('uid')}"
        for name, mark in folders.items()
        if isinstance(mark, dict)
    ]


def open_connection(config: Config) -> imaplib.IMAP4:
    """The one place a socket is opened: TLS from the first byte, the certificate and the host name
    verified by the default context. A test replaces this with a plain loopback connection."""
    context = ssl.create_default_context()
    return imaplib.IMAP4_SSL(config.host, config.port, ssl_context=context, timeout=TIMEOUT_S)


def pull(
    config: Config,
    since: str | None = None,
    progress: Callable[[int, float], None] | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
    owner_emails: Iterable[str] | None = None,
    existing: Callable[[Iterable[tuple[str, str]]], set[tuple[str, str]]] | None = None,
    walk: Walk | None = None,
    notice: Callable[[str], None] | None = None,
) -> Iterator[dict[str, Any]]:
    """One mail/v1 line draft per message the record does not hold, folder by folder, UID order
    within a folder. `since` (RFC3339 UTC) searches each folder SINCE that day in place of its mark.
    `walk` is `sync`'s checkpoint keeper: its `start()` holds the marks, `reached(ordinal, marks)`
    is told after every batch. `existing` is the record's answer to a batch of (source, raw_id)
    keys. `notice` prints one line per batch; `progress` is not used, since that line is the
    progress and names no total. Raises OSError or ValueError with one plain sentence."""
    counts = counts if counts is not None else {}
    say = notice if notice is not None else (lambda _text: None)
    owners = {e.strip().lower() for e in (owner_emails or []) if e.strip()}
    owners.add(config.account)
    saved = walk.start() if walk is not None else None
    marks: dict[str, dict[str, int]] = _marks(saved)
    day = _search_day(since) if since else None
    imap = _connect(config)
    try:
        _login(imap, config)
        capabilities = {str(c).upper() for c in imap.capabilities}
        gmail = GMAIL_EXTENSION in capabilities
        given = config.folders is not None
        folders = (
            [encode_utf7(f) for f in config.folders]
            if config.folders
            else _default_folders(imap, capabilities)
        )
        ordinal = 0
        for folder in folders:
            shown = decode_utf7(folder)
            uidvalidity = _examine(imap, folder, shown, given)
            mark = marks.get(folder)
            if mark is not None and mark["uidvalidity"] == uidvalidity:
                start = mark["uid"] + 1
            else:
                start = 1
                if mark is not None:
                    _count(counts, STARTED_OVER)
                    say(f"{shown}: UIDVALIDITY changed, reading the folder from its first message again")
                marks[folder] = {"uidvalidity": uidvalidity, "uid": 0}
            uids = _search(imap, shown, start, day)
            fetched = new = already = 0
            for batch in _batches(uids, BATCH):
                heads = _fetch_heads(imap, shown, batch)
                keys = {
                    (NAME, f"{config.account}:{message_id}")
                    for uid in batch
                    if (message_id := heads.get(uid, (None, 0))[0]) is not None
                }
                held = existing(keys) if existing is not None and keys else set()
                wanted = [
                    uid
                    for uid in batch
                    if uid not in heads
                    or heads[uid][0] is None
                    or (NAME, f"{config.account}:{heads[uid][0]}") not in held
                ]
                already += len(batch) - len(wanted)
                _count(counts, ALREADY, len(batch) - len(wanted))
                for bodies in _by_size(wanted, heads):
                    for raw, internaldate, labels, thread_id in _fetch_bodies(imap, shown, bodies, gmail):
                        line, _blobs = mail.parse_message(
                            raw,
                            internaldate,
                            counts,
                            timezone or "UTC",
                            None,
                            owners,
                            config.account,
                            digest_attachments=True,
                            fallback_name="internaldate",
                        )
                        if line is None:
                            continue
                        mail.gmail_fields(line["payload"], labels, thread_id)
                        ordinal += 1
                        new += 1
                        yield line
                fetched += len(batch)
                marks[folder] = {"uidvalidity": uidvalidity, "uid": max(batch[-1], marks[folder]["uid"])}
                if walk is not None:
                    walk.reached(ordinal, {"folders": dict(marks)})
                say(f"{shown}: {fetched:,} fetched, {new:,} new, {already:,} already in the record")
            if not uids and walk is not None:  # an empty folder, or one started over with nothing in it
                walk.reached(ordinal, {"folders": dict(marks)})
    finally:
        _close(imap)


# -- the protocol -----------------------------------------------------------------------------------


def _connect(config: Config) -> imaplib.IMAP4:
    try:
        return open_connection(config)
    except ssl.SSLError as e:
        reason = getattr(e, "reason", None) or type(e).__name__
        where = f"the server named by {HOST_ENV} on port {config.port}"
        raise OSError(f"TLS to {where} failed: {reason}") from None
    except socket.gaierror:
        raise OSError(f"the host named by {HOST_ENV} could not be resolved") from None
    except OSError as e:
        reason = e.strerror or type(e).__name__
        raise OSError(
            f"could not connect to the server named by {HOST_ENV} on port {config.port}: {reason}"
        ) from None
    except imaplib.IMAP4.error:
        raise OSError(
            f"the server named by {HOST_ENV} on port {config.port} did not answer as an IMAP server"
        ) from None


def _login(imap: imaplib.IMAP4, config: Config) -> None:
    try:
        imap.login(config.user, config.password)
    except imaplib.IMAP4.error:
        raise ValueError(
            f"the server refused the login: check {USER_ENV} and {PASSWORD_ENV}"
            " (Gmail takes an app password, which needs 2-step verification)"
        ) from None
    except OSError as e:
        raise OSError(f"the connection was lost during the login: {e.strerror or type(e).__name__}") from None


def _close(imap: imaplib.IMAP4) -> None:
    """LOGOUT, or the socket closed when the server is gone: the connection never outlives the pull."""
    try:
        imap.logout()
    except (imaplib.IMAP4.error, OSError):
        with contextlib.suppress(imaplib.IMAP4.error, OSError):
            imap.shutdown()


def _default_folders(imap: imaplib.IMAP4, capabilities: set[str]) -> list[str]:
    """The folder flagged `\\All` (LIST with SPECIAL-USE, RFC 6154, else Gmail's older XLIST, else a
    plain LIST, which Gmail flags too); without one, INBOX and the folder flagged `\\Sent`."""
    if "SPECIAL-USE" in capabilities:
        rows = _list(imap, "LIST", '""', '"*"', "RETURN", "(SPECIAL-USE)")
    elif "XLIST" in capabilities:
        rows = _list(imap, "XLIST", '""', '"*"')
    else:
        rows = _list(imap, "LIST", '""', '"*"')
    all_mail = next((name for flags, name in rows if any(f in flags for f in ALL_FLAGS)), None)
    if all_mail is not None:
        return [all_mail]
    folders = ["INBOX"]
    sent = next((name for flags, name in rows if SENT_FLAG in flags), None)
    if sent is not None and sent.upper() != "INBOX":
        folders.append(sent)
    return folders


def _list(imap: imaplib.IMAP4, command: str, *args: str) -> list[tuple[set[str], str]]:
    """`(flags, name)` per folder the server lists; a name sent as a literal is skipped."""
    try:
        typ, _dat = imap.xatom(command, *args)
        _typ, rows = imap.response(command)
    except imaplib.IMAP4.error as e:
        raise OSError(f"the server would not list its folders ({command})") from e
    if typ != "OK":
        raise OSError(f"the server would not list its folders ({command})")
    found: list[tuple[set[str], str]] = []
    for row in rows or []:
        if not isinstance(row, bytes):
            continue
        m = LIST_LINE.match(row.strip())
        if m is None:
            continue
        flags = {f.decode("ascii", "replace").lower() for f in m.group("flags").split()}
        found.append(({_flag_case(f) for f in flags}, _unquote(m.group("name"))))
    return found


def _flag_case(flag: str) -> str:
    """`\\all` → `\\All`, `\\allmail` → `\\AllMail`, `\\sent` → `\\Sent`: compared case-insensitively."""
    for known in (*ALL_FLAGS, SENT_FLAG):
        if flag == known.lower():
            return known
    return flag


def _examine(imap: imaplib.IMAP4, folder: str, shown: str, given: bool) -> int:
    """Open the folder read-only (EXAMINE, never SELECT) and return its UIDVALIDITY."""
    try:
        typ, _dat = imap.select(_quote(folder), readonly=True)
    except imaplib.IMAP4.error:
        typ = "NO"
    if typ != "OK":
        where = f"check {FOLDERS_ENV}" if given else "the server's folder list has changed"
        raise ValueError(f"the folder {shown} is not on the server; {where}")
    _typ, values = imap.response("UIDVALIDITY")
    value = values[0] if values else None
    if not isinstance(value, bytes) or not value.strip().isdigit():
        raise OSError(f"the server gave no UIDVALIDITY for the folder {shown}")
    return int(value)


def _search(imap: imaplib.IMAP4, shown: str, start: int, day: str | None) -> list[int]:
    """The UIDs to handle, ascending: from `start` up, or SINCE `day` (every UID of that day and
    later, the mark set aside for this run)."""
    criteria = ["SINCE", day] if day is not None else ["UID", f"{start}:*"]
    try:
        typ, dat = imap.uid("SEARCH", *criteria)
    except (imaplib.IMAP4.error, OSError) as e:
        raise _lost(shown, e) from None
    if typ != "OK":
        raise OSError(f"the server refused the search in the folder {shown}")
    found: set[int] = set()
    for row in dat or []:
        if isinstance(row, bytes):
            found.update(int(token) for token in row.split() if token.isdigit())
    return sorted(uid for uid in found if day is not None or uid >= start)  # `n:*` names the last UID too


def _fetch_heads(imap: imaplib.IMAP4, shown: str, uids: list[int]) -> dict[int, tuple[str | None, int]]:
    """Per UID: the first Message-ID (None when the message has none) and the size."""
    found: dict[int, tuple[str | None, int]] = {}
    for meta, literals in _fetch(imap, shown, uids, HEADER_ITEMS):
        uid = _int(UID, meta)
        if uid is None:
            continue
        header = literals[0] if literals else b""
        message_id = mail.first_id(mail.Headers(header).get("message-id"))
        found[uid] = (message_id, _int(SIZE, meta) or 0)
    return found


def _fetch_bodies(
    imap: imaplib.IMAP4, shown: str, uids: list[int], gmail: bool
) -> Iterator[tuple[bytes, datetime | None, list[str] | None, str | None]]:
    """Per message: its bytes (BODY.PEEK[]: nothing is marked read), its INTERNALDATE, and with the
    Gmail extension its labels and thread id (None without)."""
    if not uids:
        return
    items = f"(UID INTERNALDATE BODY.PEEK[]{' ' + GMAIL_ITEMS if gmail else ''})"
    for meta, literals in _fetch(imap, shown, uids, items):
        uid = _int(UID, meta)
        if uid is None or not literals:
            continue
        when = INTERNALDATE.search(meta)
        internaldate = _internaldate(when.group(1).decode("ascii", "replace")) if when else None
        labels = _labels(meta) if gmail else None
        thread = THRID.search(meta) if gmail else None
        yield literals[0], internaldate, labels, thread.group(1).decode("ascii") if thread else None


def _fetch(imap: imaplib.IMAP4, shown: str, uids: list[int], items: str) -> list[tuple[bytes, list[bytes]]]:
    """One UID FETCH; per message its response text without the literals, and the literals."""
    try:
        typ, data = imap.uid("FETCH", _uid_set(uids), items)
    except (imaplib.IMAP4.error, OSError) as e:
        raise _lost(shown, e) from None
    if typ != "OK":
        raise OSError(f"the server refused a fetch in the folder {shown}")
    return _messages(data)


def _messages(data: list[Any]) -> list[tuple[bytes, list[bytes]]]:
    """imaplib's FETCH data regrouped per message: a message's response begins with `<n> (` and is
    split by imaplib at every literal into `(text, literal)` pairs and trailing text; the literal
    bytes never join the text, so a message's own content cannot read as a response item."""
    found: list[tuple[bytearray, list[bytes]]] = []
    for item in data or []:
        if isinstance(item, tuple) and len(item) == 2:
            head, literal = item
            if not isinstance(head, bytes):
                continue
            if MESSAGE_HEAD.match(head) or not found:
                found.append((bytearray(), []))
            found[-1][0].extend(head + b" ")
            found[-1][1].append(bytes(literal) if isinstance(literal, bytes) else b"")
        elif isinstance(item, bytes):
            if MESSAGE_HEAD.match(item) or not found:
                found.append((bytearray(), []))
            found[-1][0].extend(item + b" ")
    return [(bytes(text), literals) for text, literals in found]


def _labels(meta: bytes) -> list[str]:
    """X-GM-LABELS as the mbox adapter spells Takeout's: system labels without their backslash
    (`\\Inbox` → `Inbox`), the rest decoded from modified UTF-7."""
    m = LABELS.search(meta)
    if m is None:
        return []
    labels: list[str] = []
    for quoted, atom in ATOM_OR_QUOTED.findall(m.group(1)):
        raw = quoted.replace(b'\\"', b'"').replace(b"\\\\", b"\\") if quoted else atom
        text = decode_utf7(raw.decode("utf-8", "replace"))
        if text.startswith("\\"):
            text = text[1:]
        if text:
            labels.append(text)
    return labels


def _lost(shown: str, e: Exception) -> OSError:
    if isinstance(e, imaplib.IMAP4.abort):  # imaplib's word for a socket that went away under it
        reason = "the server closed the connection"
    else:
        reason = getattr(e, "strerror", None) or type(e).__name__
    return OSError(
        f"the connection was lost while reading the folder {shown} ({reason});"
        " the next run resumes from the last batch written"
    )


# -- small helpers ----------------------------------------------------------------------------------


def _marks(saved: dict[str, Any] | None) -> dict[str, dict[str, int]]:
    """The stored marks, `{folder: {uidvalidity, uid}}`, only the entries that are the shape."""
    folders = saved.get("folders") if isinstance(saved, dict) else None
    if not isinstance(folders, dict):
        return {}
    found: dict[str, dict[str, int]] = {}
    for name, mark in folders.items():
        if not isinstance(mark, dict):
            continue
        validity, uid = mark.get("uidvalidity"), mark.get("uid")
        if isinstance(validity, int) and isinstance(uid, int):
            found[str(name)] = {"uidvalidity": validity, "uid": uid}
    return found


def _search_day(since: str) -> str:
    """`--since` as IMAP's date: `04-Mar-2026`, the day of the instant in UTC."""
    when = datetime.fromisoformat(since.replace("Z", "+00:00")).astimezone(UTC)
    return f"{when.day:02d}-{MONTHS[when.month - 1]}-{when.year}"


def _internaldate(text: str) -> datetime | None:
    """`02-Mar-2026 10:15:00 +0000` as a datetime with its offset; None when not readable."""
    m = DATE_TIME.match(text)
    if m is None:
        return None
    day, month, year, hour, minute, second, sign, oh, om = m.groups()
    try:
        month_number = [name.lower() for name in MONTHS].index(month.lower()) + 1
        offset = timedelta(hours=int(oh), minutes=int(om)) * (1 if sign == "+" else -1)
        return datetime(
            int(year), month_number, int(day), int(hour), int(minute), int(second), tzinfo=timezone(offset)
        )
    except ValueError:
        return None


def _batches(uids: list[int], size: int) -> Iterator[list[int]]:
    for i in range(0, len(uids), size):
        yield uids[i : i + size]


def _by_size(uids: list[int], heads: Mapping[int, tuple[str | None, int]]) -> Iterator[list[int]]:
    """The bodies to fetch together: at most BODY_BATCH_BYTES by the sizes reported, at least one."""
    batch: list[int] = []
    total = 0
    for uid in uids:
        size = heads.get(uid, (None, 0))[1]
        if batch and total + size > BODY_BATCH_BYTES:
            yield batch
            batch, total = [], 0
        batch.append(uid)
        total += size
    if batch:
        yield batch


def _uid_set(uids: list[int]) -> str:
    """`1,3:5,7`: runs of consecutive UIDs as ranges."""
    parts: list[str] = []
    i = 0
    while i < len(uids):
        j = i
        while j + 1 < len(uids) and uids[j + 1] == uids[j] + 1:
            j += 1
        parts.append(str(uids[i]) if i == j else f"{uids[i]}:{uids[j]}")
        i = j + 1
    return ",".join(parts)


def _int(pattern: re.Pattern[bytes], text: bytes) -> int | None:
    m = pattern.search(text)
    return int(m.group(1)) if m else None


def _count(counts: dict[str, int], key: str, n: int = 1) -> None:
    if n:
        counts[key] = counts.get(key, 0) + n


def _quote(name: str) -> str:
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _unquote(token: bytes) -> str:
    text = token.decode("utf-8", "replace")
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return text


def decode_utf7(name: str) -> str:
    """IMAP's modified UTF-7 (RFC 3501 §5.1.3) to text: `&AOU-` is `å`, `&-` is `&`; a shift that
    does not decode is kept as it came."""
    if "&" not in name:
        return name

    def shift(m: re.Match[str]) -> str:
        inner = m.group(1)
        if not inner:
            return "&"
        padded = inner.replace(",", "/") + "=" * (-len(inner) % 4)
        try:
            return base64.b64decode(padded).decode("utf-16-be")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return m.group(0)

    return UTF7_SHIFT.sub(shift, name)


def encode_utf7(name: str) -> str:
    """Text to IMAP's modified UTF-7: printable ASCII as is (`&` as `&-`), every other run shifted."""
    out: list[str] = []
    run: list[str] = []

    def flush() -> None:
        if run:
            encoded = base64.b64encode("".join(run).encode("utf-16-be")).decode("ascii").rstrip("=")
            out.append("&" + encoded.replace("/", ",") + "-")
            run.clear()

    for char in name:
        if 0x20 <= ord(char) <= 0x7E:
            flush()
            out.append("&-" if char == "&" else char)
        else:
            run.append(char)
    flush()
    return "".join(out)
