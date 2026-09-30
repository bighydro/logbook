"""An mbox mailbox — a Google Takeout `Mail/` export — → mail/v1 (RFC 0015).

Takeout writes `Takeout/Mail/All mail Including Spam and Trash.mbox` (and one `.mbox` per label the
owner asked for): one file, every message, each preceded by a separator line

    From <gmail message id>@xxx Mon Mar 02 10:15:00 +0000 2026

and Gmail's own headers on the message: `X-Gmail-Labels` (the labels, comma-separated) and
`X-GM-THRID` (Gmail's thread id). Body lines that begin with `From ` are escaped as `>From ` on the
way out (mboxrd); this reader takes one `>` off every `>+From ` line on the way in.

One line per message: kind `mail`, tier 2 unless the whole import says otherwise, `at` the `Date`
header in UTC (`payload.date` keeps the header's own offset), the separator's date when the header
is missing or unreadable (counted `date_from_separator`), `tz` the record's zone. `raw_id` is the
`Message-ID` without its brackets, prefixed by `<account>:` when `--account` names the mailbox, so a
re-import and a later live puller of the same mailbox append nothing (ADR 0017); a message with no
`Message-ID` is keyed `sha256:<digest of its bytes>` and counted (`no_message_id`), never skipped.
`thread` is the root of `References`, else `In-Reply-To`, else the message's own id. `from`, `to`,
`cc` and `bcc` are `{email, name?}` as the headers spell them, the address lower-cased, never
resolved: a `resolution/v1` line for `{kind: "email", value}` names them (RFC 0006). `direction` is
`sent` when the sender is one of `owner_emails` (`logbook.json`) or the account, else `received`.

The body is the `text/plain` part, else the `text/html` part stripped to text by `strip_html`
(`extra.body_from: "html"`); a part whose charset is unknown or whose bytes do not decode is
decoded with replacement characters and flagged (`extra.decoding_errors`, counted). Every other
leaf part — anything with a file name or a `Content-Disposition: attachment`, or a non-text part —
is an attachment: `{filename, media_type, sha256, bytes}` always, and `path` with the bytes in the
SPEC §1.1 store only with `attachments=True` (`--attachments`); the store callback is called just
before the line is yielded. `--only-labels` keeps messages carrying any of the labels, `--skip-labels`
drops messages carrying any (both case-insensitive, counted `skipped_label`); `since` cuts on `at`.

Streamed: the file is read line by line and one message at a time is in memory, whatever the size
of the export. Pure: no network, never writes the source.
"""

from __future__ import annotations

import email
import email.policy
import hashlib
import html
import re
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import IO, Any

from ..attachments import DIR as ATTACHMENTS_DIR

NAME = "mail"
KIND = "mail"
TIER = 2
SCHEMA = "mail/v1"

SUFFIX = ".mbox"
SNIFF_BYTES = 8192
LABELS_HEADER = "X-Gmail-Labels"
THREAD_HEADER = "X-GM-THRID"
NO_DATE = "skipped_no_date"
BY_LABEL = "skipped_label"

SEPARATOR = re.compile(rb"^From \S+ .*\r?\n$")  # `From <id> <date>`, at the start of a line
ESCAPED_FROM = re.compile(rb"^>(>*From )")  # mboxrd: one `>` off, the rest stays
SEPARATOR_DATE = ("%a %b %d %H:%M:%S %z %Y", "%a %b %d %H:%M:%S %Y")
MESSAGE_ID = re.compile(r"<([^<>]+)>")
POLICY = email.policy.default.clone(raise_on_defect=False)

# `strip_html`: what a browser would not show, then the tags that start a new line, then every other tag
DROP = re.compile(r"<(script|style|head)\b.*?</\1\s*>|<!--.*?-->", re.IGNORECASE | re.DOTALL)
BREAK = re.compile(r"<(?:p|div|br|tr|li|ul|ol|h[1-6]|table|blockquote|pre|hr|title)\b[^>]*>", re.IGNORECASE)
TAG = re.compile(r"<[^>]*>")
BLANK_LINES = re.compile(r"\n{3,}")


def sniff(path: Path) -> bool:
    """An mbox file (`.mbox`, or one that starts with a separator line), or a folder holding at
    least one such file — Takeout's `Mail/`. Never raises."""
    path = Path(path)
    try:
        if path.is_dir():
            return any(_is_mbox(f) for f in path.iterdir() if f.is_file())
        return _is_mbox(path)
    except OSError:
        return False


def _is_mbox(path: Path) -> bool:
    if not path.is_file():
        return False
    with path.open("rb") as fh:
        head = fh.read(SNIFF_BYTES)
    first = head.split(b"\n", 1)[0] + b"\n"
    if not SEPARATOR.match(first):
        return False
    return path.suffix.lower() == SUFFIX or b"\nMessage-ID:" in head or b"\nX-Gmail-Labels:" in head


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
    tier: int | None = None,
    owner_emails: Iterable[str] | None = None,
    account: str | None = None,
    attachments: bool | None = None,
    only_labels: Iterable[str] | None = None,
    skip_labels: Iterable[str] | None = None,
    store: Callable[[bytes], object] | None = None,
) -> Iterator[dict[str, Any]]:
    """One mail/v1 line draft per message of the mbox at `path` (or of every `.mbox` in the folder,
    in name order), streamed. `since` is RFC3339 UTC; messages with `at` before it are not
    yielded. `timezone` is the record's zone (the line's `tz`). `tier` applies to the whole run."""
    counts = counts if counts is not None else {}
    path = Path(path)
    files = [path] if path.is_file() else sorted(f for f in path.iterdir() if _is_mbox(f))
    owners = {e.strip().lower() for e in (owner_emails or []) if e.strip()}
    if account:
        owners.add(account.strip().lower())
    only = {label.strip().lower() for label in (only_labels or []) if label.strip()}
    skip = {label.strip().lower() for label in (skip_labels or []) if label.strip()}
    for file in files:
        with file.open("rb") as fh:
            for separator, raw in messages(fh):
                line, blobs = _line(
                    separator, raw, counts, timezone or "UTC", tier, owners, account, bool(attachments)
                )
                if line is None:
                    continue
                labels = {str(label).lower() for label in line["payload"].get("labels", [])}
                if (only and not labels & only) or (skip and labels & skip):
                    counts[BY_LABEL] = counts.get(BY_LABEL, 0) + 1
                    continue
                if since and line["at"] < since:
                    continue
                if store is not None:
                    for blob in blobs:
                        store(blob)
                yield line


def messages(fh: IO[bytes]) -> Iterator[tuple[bytes, bytes]]:
    """Every message of an mbox as `(separator line, message bytes)`, read line by line: one message
    in memory at a time. A message starts at a `From ` separator line at the start of the file or
    after a blank line; `>From ` lines inside it are unescaped (mboxrd) and the blank line that ends
    it is not part of it."""
    separator: bytes | None = None
    body: list[bytes] = []
    previous_blank = True
    for line in fh:
        if previous_blank and SEPARATOR.match(line):
            if separator is not None:
                yield separator, _join(body)
            separator, body = line, []
        elif separator is not None:
            body.append(ESCAPED_FROM.sub(rb"\1", line, count=1))
        previous_blank = line in (b"\n", b"\r\n")
    if separator is not None:
        yield separator, _join(body)


def _join(lines: list[bytes]) -> bytes:
    while lines and lines[-1] in (b"\n", b"\r\n"):
        lines.pop()
    return b"".join(lines)


def _line(
    separator: bytes,
    raw: bytes,
    counts: dict[str, int],
    tz: str,
    tier: int | None,
    owners: set[str],
    account: str | None,
    keep_attachments: bool,
) -> tuple[dict[str, Any] | None, list[bytes]]:
    msg = email.message_from_bytes(raw, policy=POLICY)
    at, date = _when(msg, separator)
    if at is None:
        _count(counts, NO_DATE)
        return None, []
    if date is None:
        _count(counts, "date_from_separator")
    message_id = _first_id(_header(msg, "Message-ID"))
    if message_id is None:
        _count(counts, "no_message_id")
        own = f"sha256:{hashlib.sha256(raw).hexdigest()}"
    else:
        own = message_id
    references = _ids(_header(msg, "References"))
    in_reply_to = _first_id(_header(msg, "In-Reply-To"))
    sender = _addresses(msg, "From")
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": f"{account.strip().lower()}:{own}" if account else own,
    }
    if message_id is not None:
        payload["message_id"] = message_id
    payload["thread"] = references[0] if references else in_reply_to or own
    if sender:
        payload["from"] = sender[0]
    for field in ("to", "cc", "bcc"):
        recipients = _addresses(msg, field)
        if recipients:
            payload[field] = recipients
    subject = _text_header(msg, "Subject")
    if subject:
        payload["subject"] = subject
    if date is not None:
        payload["date"] = date
    payload["direction"] = "sent" if sender and sender[0]["email"] in owners else "received"
    labels = _labels(_header(msg, LABELS_HEADER))
    if labels:
        payload["labels"] = labels
    extra: dict[str, Any] = {}
    body, body_from, trouble = _body(msg)
    if body is not None:
        payload["body"] = body
    if body_from == "html":
        extra["body_from"] = "html"
        _count(counts, "body_from_html")
    if trouble:
        extra["decoding_errors"] = True
        _count(counts, "decoding_errors")
    payload["size"] = len(raw)
    attachments, blobs = _attachments(msg, keep_attachments)
    if attachments:
        payload["attachments"] = attachments
        noted = "attachments_stored" if keep_attachments else "attachments_referenced"
        _count(counts, noted, len(attachments))
    if account:
        payload["account"] = account.strip().lower()
    thread_id = _header(msg, THREAD_HEADER)
    if thread_id:
        extra["gmail_thread_id"] = thread_id.strip()
    if in_reply_to:
        extra["in_reply_to"] = in_reply_to
    if references:
        extra["references"] = references
    if extra:
        payload["extra"] = extra
    line = {
        "at": at,
        "end": None,
        "tz": tz,
        "source": NAME,
        "kind": KIND,
        "tier": tier if tier is not None else TIER,
        "payload": payload,
    }
    return line, blobs


def _count(counts: dict[str, int], key: str, n: int = 1) -> None:
    counts[key] = counts.get(key, 0) + n


def _header(msg: Message, name: str) -> str | None:
    """A header's decoded text, or None; a header the parser cannot make sense of is its raw text."""
    try:
        value = msg.get(name)
    except (LookupError, ValueError, TypeError):
        raw = msg.get_all(name, failobj=None)
        value = None if not raw else str(raw[0])
    if value is None:
        return None
    return str(value).replace("\r", "").replace("\n", " ")


def _text_header(msg: Message, name: str) -> str | None:
    value = _header(msg, name)
    if value is None:
        return None
    folded = " ".join(value.split())
    return folded or None


def _first_id(value: str | None) -> str | None:
    ids = _ids(value)
    return ids[0] if ids else None


def _ids(value: str | None) -> list[str]:
    """Message ids without their angle brackets; a bare token without brackets counts too."""
    if not value:
        return []
    found = MESSAGE_ID.findall(value)
    if found:
        return [token.strip() for token in found if token.strip()]
    return [token for token in value.split() if token]


def _addresses(msg: Message, name: str) -> list[dict[str, Any]]:
    """`{email, name?}` for every address in the header, in header order, the address lower-cased;
    an entry with no address is dropped."""
    try:
        values = [str(v) for v in msg.get_all(name, failobj=[])]
    except (LookupError, ValueError, TypeError):
        return []
    found: list[dict[str, Any]] = []
    for display, address in getaddresses(values):
        address = address.strip().lower()
        if not address or "@" not in address:
            continue
        entry: dict[str, Any] = {"email": address}
        display = " ".join(display.split())
        if display:
            entry["name"] = display
        found.append(entry)
    return found


def _labels(value: str | None) -> list[str]:
    if not value:
        return []
    return [label.strip() for label in value.split(",") if label.strip()]


def _when(msg: Message, separator: bytes) -> tuple[str | None, str | None]:
    """(`at` in UTC, `date` with the header's offset), the header's own; the separator's date, and
    no `date`, when the header is missing or unreadable; (None, None) when neither is readable."""
    header = _header(msg, "Date")
    if header:
        try:
            parsed = parsedate_to_datetime(header)
        except (TypeError, ValueError, IndexError, OverflowError):
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:  # `-0000`: the sender said nothing about its zone
                parsed = parsed.replace(tzinfo=UTC)
            return _utc(parsed), parsed.isoformat()
    text = separator.decode("ascii", errors="replace").rstrip("\r\n")
    parts = text.split(None, 2)
    if len(parts) < 3:
        return None, None
    stamp = " ".join(parts[2].split())
    for layout in SEPARATOR_DATE:
        try:
            when = datetime.strptime(stamp, layout)
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return _utc(when), None
    return None, None


def _utc(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _body(msg: Message) -> tuple[str | None, str | None, bool]:
    """(text, where it came from — `plain` or `html` — or None, whether bytes were replaced): the
    first `text/plain` leaf that is not an attachment, else the first `text/html` one stripped."""
    plain: tuple[str, bool] | None = None
    html_part: tuple[str, bool] | None = None
    for part in _leaves(msg):
        if _is_attachment(part):
            continue
        content_type = part.get_content_type()
        if content_type == "text/plain" and plain is None:
            plain = _decode_text(part)
        elif content_type == "text/html" and html_part is None:
            html_part = _decode_text(part)
        if plain is not None:
            break
    if plain is not None:
        return plain[0], "plain", plain[1]
    if html_part is not None:
        return strip_html(html_part[0]), "html", html_part[1]
    return None, None, False


def _leaves(msg: Message) -> Iterator[Message]:
    for part in msg.walk():
        if not part.is_multipart():
            yield part


def _is_attachment(part: Message) -> bool:
    disposition = str(part.get("Content-Disposition") or "").split(";", 1)[0].strip().lower()
    if disposition == "attachment":
        return True
    if part.get_filename():
        return True
    return part.get_content_maintype() not in ("text",)


def _decode_text(part: Message) -> tuple[str, bool]:
    """A text part's payload as str: its charset when Python knows it and the bytes obey it, else
    UTF-8 with replacement characters; the flag says whether anything was replaced or guessed."""
    payload = part.get_payload(decode=True)
    data = payload if isinstance(payload, bytes) else str(payload or "").encode("utf-8")
    charset = (part.get_content_charset() or "utf-8").strip() or "utf-8"
    try:
        text = data.decode(charset)
        trouble = False
    except (LookupError, UnicodeDecodeError, ValueError):
        text = data.decode("utf-8", errors="replace")
        trouble = True
    return text.replace("\r\n", "\n").replace("\r", "\n"), trouble


def _attachments(msg: Message, keep: bool) -> tuple[list[dict[str, Any]], list[bytes]]:
    """Every attachment leaf as `{filename, media_type, sha256, bytes}` (+ `path` when `keep`), and
    the bytes to store, in message order."""
    found: list[dict[str, Any]] = []
    blobs: list[bytes] = []
    for part in _leaves(msg):
        if not _is_attachment(part):
            continue
        payload = part.get_payload(decode=True)
        data = payload if isinstance(payload, bytes) else str(payload or "").encode("utf-8")
        sha256 = hashlib.sha256(data).hexdigest()
        entry: dict[str, Any] = {
            "filename": _filename(part),
            "media_type": part.get_content_type(),
            "sha256": sha256,
            "bytes": len(data),
        }
        if keep:
            entry["path"] = f"{ATTACHMENTS_DIR}/{sha256}"
            blobs.append(data)
        found.append(entry)
    return found, blobs


def _filename(part: Message) -> str:
    try:
        name = part.get_filename()
    except (LookupError, ValueError, TypeError):
        name = None
    return " ".join(str(name).split()) if name else ""


def strip_html(text: str) -> str:
    """HTML to plain text with no library: scripts, styles, the head and comments dropped; a tag
    that opens a block, and a line break, start a new line; every other tag is removed; entities
    are decoded; trailing spaces and runs of blank lines are folded. Rough on purpose: readable,
    searchable, never a rendering."""
    text = DROP.sub("", text)
    text = BREAK.sub("\n", text)
    text = TAG.sub("", text)
    text = html.unescape(text)
    lines = [" ".join(line.split()) for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return BLANK_LINES.sub("\n\n", "\n".join(lines)).strip("\n")
