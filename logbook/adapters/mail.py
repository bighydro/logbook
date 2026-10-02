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
resolved: a `resolution/v1` line for `{kind: "email", value}` names them (RFC 0006), and the names
a mailbox uses are the candidates a later `people merge` proposes from. `direction` is `sent` when
the sender is one of `owner_emails` (`logbook.json`) or the account, else `received`.

The body is the `text/plain` part, else the `text/html` part stripped to text by `strip_html`
(`extra.body_from: "html"`), read from at most `BODY_CAP` bytes of the part (64 KB; a longer one is
cut and flagged `extra.body_truncated`, counted `body_truncated`); a part whose charset is unknown
or whose bytes do not decode is decoded with replacement characters and flagged
(`extra.decoding_errors`, counted). Every other leaf part — anything with a file name or a
`Content-Disposition: attachment`, or a non-text part — is an attachment: `{filename, media_type,
bytes}` always, the length measured from the base64 text without decoding it; and, only with
`attachments=True` (`--attachments`), the part is decoded and `sha256` and `path` name its bytes in
the SPEC §1.1 store (the store callback is called just before the line is yielded). `--only-labels`
keeps messages carrying any of the labels, `--skip-labels` drops messages carrying any (both
case-insensitive, counted `skipped_label`); `since` cuts on `at`.

Built for a 20 GB export: the file is read in chunks and scanned for separators, one message is in
memory at a time, the headers are parsed by hand, the MIME tree is walked by offsets, and no
attachment is ever decoded or copied. `progress(messages, bytes_read, elapsed)` is called every
`PROGRESS_EVERY` messages. A `cursor` (the inbox manifest's, `logbook.inbox`) says where to start
in each file and is told, before every draft, how far the file is read, so an interrupted import
resumes at the last message the record holds. Pure: no network, never writes the source.
"""

from __future__ import annotations

import base64
import binascii
import codecs
import hashlib
import html
import quopri
import re
import time
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import IO, Any, Protocol
from urllib.parse import unquote_to_bytes

from ..attachments import DIR as ATTACHMENTS_DIR

NAME = "mail"
KIND = "mail"
TIER = 2
SCHEMA = "mail/v1"
UNIT = "messages"

SUFFIX = ".mbox"
SNIFF_BYTES = 8192
LABELS_HEADER = "x-gmail-labels"
THREAD_HEADER = "x-gm-thrid"
NO_DATE = "skipped_no_date"
BY_LABEL = "skipped_label"

CHUNK = 8 * 1024 * 1024  # bytes read at a time
BODY_CAP = 64 * 1024  # bytes of a body part read; the rest is cut
PROGRESS_EVERY = 10_000  # messages between progress reports
MAX_DEPTH = 32  # nested multiparts walked

SEPARATOR = re.compile(rb"From \S+ [^\r\n]*\r?\n")  # `From <id> <date>`, at the start of a line
ESCAPED_FROM = re.compile(rb"^>(>*From )", re.MULTILINE)  # mboxrd: one `>` off, the rest stays
BLANK_LINE = re.compile(rb"\r?\n\r?\n")  # ends a header block
SEPARATOR_DATE = ("%a %b %d %H:%M:%S %z %Y", "%a %b %d %H:%M:%S %Y")
MESSAGE_ID = re.compile(r"<([^<>]+)>")
PARAM = re.compile(r';\s*([^=;\s]+)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|([^;]*))')
PARAM_KEY = re.compile(r"^(.*?)(?:\*(\d+))?(\*)?$")
SIMPLE_ADDRESS = re.compile(
    r'^(?:"([^"\\]*)"|([^"<>,]*?))\s*(?:<([^<>\s",]+@[^<>\s",]+)>|([^<>\s",]+@[^<>\s",]+))$'
)

# `strip_html`: what a browser would not show, then the tags that start a new line, then every other tag
DROP = re.compile(r"<(script|style|head)\b.*?</\1\s*>|<!--.*?-->", re.IGNORECASE | re.DOTALL)
BREAK = re.compile(r"<(?:p|div|br|tr|li|ul|ol|h[1-6]|table|blockquote|pre|hr|title)\b[^>]*>", re.IGNORECASE)
TAG = re.compile(r"<[^>]*>")
BLANK_LINES = re.compile(r"\n{3,}")

Progress = Callable[[int, int, float], None]


class Cursor(Protocol):
    """Where an import of each file got to, kept by the consumer (`logbook.inbox.Cursor`)."""

    def start(self, file: Path) -> int:
        """The byte offset to begin reading `file` at: 0, or the end of the last message the
        record holds."""
        ...

    def reached(self, file: Path, ordinal: int, offset: int) -> None:
        """Every message of `file` before `offset` is either draft `ordinal` or an earlier one, or
        was skipped: called just before draft `ordinal` is yielded, and once more at the end of the
        file with its size."""
        ...


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
    progress: Progress | None = None,
    cursor: Cursor | None = None,
    chunk_size: int = CHUNK,
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
    read = ordinal = 0
    started = time.monotonic()
    for file in files:
        start = cursor.start(file) if cursor is not None else 0
        with file.open("rb") as fh:
            if start:
                fh.seek(start)
            for separator, raw, end in messages(fh, chunk_size, start):
                read += 1
                if progress is not None and read % PROGRESS_EVERY == 0:
                    progress(read, end, time.monotonic() - started)
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
                ordinal += 1
                if cursor is not None:
                    cursor.reached(file, ordinal, end)
                yield line
            size = fh.seek(0, 2)
        if cursor is not None:
            cursor.reached(file, ordinal, size)


def messages(fh: IO[bytes], chunk_size: int = CHUNK, base: int = 0) -> Iterator[tuple[bytes, bytes, int]]:
    """Every message of an mbox as `(separator line, message bytes, offset of the next message)`,
    read `chunk_size` bytes at a time: one message in memory at a time, whatever its size. A message
    starts at a `From ` separator line at the start of the file (or of the read, `base` being the
    offset `fh` is at) or after a blank line; `>From ` lines inside it are unescaped (mboxrd) and
    the blank lines that end it are not part of it."""
    buf = bytearray()
    first = True  # nothing consumed yet: a separator may stand at the very start
    pending: tuple[int, int] | None = None  # the current message's separator line in `buf`
    scan = 0  # where the search for the next separator resumes
    eof = False
    while not eof:
        chunk = fh.read(chunk_size)
        if not chunk:
            eof = True
        buf += chunk
        while True:
            if first and buf.startswith(b"From "):
                j = 0
            else:
                k = buf.find(b"\nFrom ", max(scan - 1, 0))
                if k < 0:
                    scan = max(len(buf) - 1, 0)
                    break
                j = k + 1
            e = buf.find(b"\n", j)
            if e < 0:
                if not eof:
                    scan = j  # the line is not whole yet
                    break
                scan = len(buf)
                break
            after_blank = buf[j - 2 : j] == b"\n\n" or buf[j - 3 : j] == b"\n\r\n"
            if ((j == 0 and first) or after_blank) and SEPARATOR.match(buf, j, e + 1):
                if pending is not None:
                    yield bytes(buf[pending[0] : pending[1]]), _message(buf, pending[1], j), base + j
                pending = (j, e + 1)
                first = False
                scan = e + 1
                continue
            scan = e + 1
            first = False
        if pending is not None and pending[0] > 0:  # drop what was yielded; the pending message stays
            cut = pending[0]
            del buf[:cut]
            base += cut
            pending = (0, pending[1] - cut)
            scan -= cut
    if pending is not None:
        yield bytes(buf[pending[0] : pending[1]]), _message(buf, pending[1], len(buf)), base + len(buf)


def _message(buf: bytearray, lo: int, hi: int) -> bytes:
    """The message between the separator line's end and the next separator, trailing blank lines
    off, `>From ` lines unescaped (mboxrd)."""
    while hi > lo and buf[hi - 1] == 0x0A:
        hi -= 1
        if hi > lo and buf[hi - 1] == 0x0D:
            hi -= 1
        if hi > lo and buf[hi - 1] != 0x0A:
            hi = _line_end(buf, lo, hi)
            break
    raw = bytes(buf[lo:hi])
    if b">From " in raw:
        raw = ESCAPED_FROM.sub(rb"\1", raw)
    return raw


def _line_end(buf: bytearray, lo: int, hi: int) -> int:
    """`hi` plus the line ending the last line had, so a message keeps its final newline."""
    end = buf.find(b"\n", hi)
    return end + 1 if end >= 0 else hi


class Headers:
    """A header block parsed by hand: names lower-cased, values unfolded, raw (encoded words
    stay until `text` or `addresses` asks for them)."""

    __slots__ = ("_disposition", "_type", "found")

    def __init__(self, block: bytes) -> None:
        self.found: dict[str, list[str]] = {}
        self._type: tuple[str, dict[str, str]] | None = None
        self._disposition: tuple[str, dict[str, str]] | None = None
        name = ""
        for raw in block.decode("utf-8", errors="replace").split("\n"):
            raw = raw.rstrip("\r")
            if not raw:
                continue
            if raw[0] in " \t":
                if name:
                    values = self.found[name]
                    values[-1] = values[-1] + " " + raw.strip()
                continue
            key, colon, value = raw.partition(":")
            if not colon:
                continue
            name = key.strip().lower()
            self.found.setdefault(name, []).append(value.strip())

    def get(self, name: str) -> str | None:
        values = self.found.get(name)
        return values[0] if values else None

    def all(self, name: str) -> list[str]:
        return self.found.get(name, [])

    def text(self, name: str) -> str | None:
        """A header's decoded text, whitespace folded, or None when absent or empty."""
        value = self.get(name)
        if value is None:
            return None
        folded = " ".join(decode_words(value).split())
        return folded or None

    def content_type(self) -> tuple[str, dict[str, str]]:
        """(`type/subtype` lower-cased, its parameters), `text/plain` when the header is absent."""
        if self._type is None:
            value = self.get("content-type")
            if not value:
                self._type = ("text/plain", {})
            else:
                head, _, rest = value.partition(";")
                ctype = head.strip().lower()
                self._type = (ctype if "/" in ctype else "text/plain", _params(";" + rest) if rest else {})
        return self._type

    def disposition(self) -> tuple[str, dict[str, str]]:
        if self._disposition is None:
            value = self.get("content-disposition")
            if not value:
                self._disposition = ("", {})
            else:
                head, _, rest = value.partition(";")
                self._disposition = (head.strip().lower(), _params(";" + rest) if rest else {})
        return self._disposition

    def encoding(self) -> str:
        return (self.get("content-transfer-encoding") or "").strip().lower()

    def filename(self) -> str:
        """The part's file name: the disposition's `filename`, else the type's `name`, else empty."""
        name = self.disposition()[1].get("filename") or self.content_type()[1].get("name") or ""
        return " ".join(decode_words(name).split())


def decode_words(value: str) -> str:
    """RFC 2047 encoded words decoded; a charset Python does not know is read as UTF-8 with
    replacement characters; anything else is returned as it came."""
    if "=?" not in value:
        return value
    try:
        return str(make_header(decode_header(value)))
    except (LookupError, UnicodeError, ValueError):
        pass
    parts: list[str] = []
    try:
        for chunk, charset in decode_header(value):
            if isinstance(chunk, bytes):
                try:
                    parts.append(chunk.decode(charset or "ascii", errors="replace"))
                except LookupError:
                    parts.append(chunk.decode("utf-8", errors="replace"))
            else:
                parts.append(chunk)
    except (UnicodeError, ValueError):
        return value
    return "".join(parts)


def _params(rest: str) -> dict[str, str]:
    """`; a=b; c="d e"; f*=utf-8''g%20h; i*0=j; i*1=k` as `{a: b, c: d e, f: g h, i: jk}` (RFC 2045
    parameters, RFC 2231 encoded and continued ones joined), keys lower-cased."""
    pieces: dict[str, list[tuple[int, bool, str]]] = {}
    for m in PARAM.finditer(rest):
        key, quoted, bare = m.group(1).lower(), m.group(2), m.group(3)
        value = quoted.replace('\\"', '"') if quoted is not None else (bare or "").strip()
        parsed = PARAM_KEY.match(key)
        if parsed is None:
            continue
        name, index, encoded = parsed.group(1), parsed.group(2), parsed.group(3) is not None
        pieces.setdefault(name, []).append((int(index) if index is not None else -1, encoded, value))
    found: dict[str, str] = {}
    for name, sections in pieces.items():
        charset: str | None = None
        out: list[str] = []
        for _index, encoded, value in sorted(sections, key=lambda s: s[0]):
            if not encoded:
                out.append(value)
                continue
            if charset is None and value.count("'") >= 2:
                charset, _lang, value = value.split("'", 2)
            data = unquote_to_bytes(value)
            try:
                out.append(data.decode(charset or "utf-8", errors="replace"))
            except LookupError:
                out.append(data.decode("utf-8", errors="replace"))
        found[name] = "".join(out)
    return found


class Part:
    """One leaf of a message's MIME tree: its headers and where its body lies in the message."""

    __slots__ = ("headers", "hi", "lo")

    def __init__(self, headers: Headers, lo: int, hi: int) -> None:
        self.headers, self.lo, self.hi = headers, lo, hi


def leaves(raw: bytes, headers: Headers, lo: int, hi: int, depth: int = 0) -> Iterator[Part]:
    """The leaf parts of the body `raw[lo:hi]` whose headers are `headers`, in message order; a
    multipart is split on its boundary by offsets, nothing is copied."""
    ctype, params = headers.content_type()
    boundary = params.get("boundary") if ctype.startswith("multipart/") else None
    if not boundary or depth >= MAX_DEPTH:
        yield Part(headers, lo, hi)
        return
    delimiter = b"--" + boundary.encode("utf-8", errors="replace")
    body_lo = -1
    pos = lo
    while True:
        i = raw.find(delimiter, pos, hi)
        if i < 0:
            if body_lo >= 0:
                yield from _part(raw, body_lo, hi, depth)
            return
        if i > lo and raw[i - 1] != 0x0A:
            pos = i + len(delimiter)
            continue
        line_end = raw.find(b"\n", i, hi)
        line_end = hi if line_end < 0 else line_end + 1
        closing = raw[i + len(delimiter) : i + len(delimiter) + 2] == b"--"
        if body_lo >= 0:
            part_hi = i - 1
            if part_hi > body_lo and raw[part_hi - 1] == 0x0D:
                part_hi -= 1
            yield from _part(raw, body_lo, max(part_hi, body_lo), depth)
        if closing:
            return
        body_lo = pos = line_end


def _part(raw: bytes, lo: int, hi: int, depth: int) -> Iterator[Part]:
    """A body part: its header block up to the first blank line, then its leaves."""
    if raw[lo : lo + 2] == b"\r\n" or raw[lo : lo + 1] == b"\n":  # no headers at all
        head, body_lo = b"", lo + (2 if raw[lo] == 0x0D else 1)
    else:
        m = BLANK_LINE.search(raw, lo, hi)
        if m is None:
            head, body_lo = raw[lo:hi], hi
        else:
            head, body_lo = raw[lo : m.start()], m.end()
    yield from leaves(raw, Headers(head), body_lo, hi, depth + 1)


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
    m = BLANK_LINE.search(raw)
    if m is None:
        headers, body_lo = Headers(raw), len(raw)
    else:
        headers, body_lo = Headers(raw[: m.start()]), m.end()
    at, date = _when(headers.get("date"), separator)
    if at is None:
        _count(counts, NO_DATE)
        return None, []
    if date is None:
        _count(counts, "date_from_separator")
    message_id = _first_id(headers.get("message-id"))
    if message_id is None:
        _count(counts, "no_message_id")
        own = f"sha256:{hashlib.sha256(raw).hexdigest()}"
    else:
        own = message_id
    references = _ids(headers.get("references"))
    in_reply_to = _first_id(headers.get("in-reply-to"))
    sender = _addresses(headers, "from")
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
        recipients = _addresses(headers, field)
        if recipients:
            payload[field] = recipients
    subject = headers.text("subject")
    if subject:
        payload["subject"] = subject
    if date is not None:
        payload["date"] = date
    payload["direction"] = "sent" if sender and sender[0]["email"] in owners else "received"
    labels = _labels(headers.get(LABELS_HEADER))
    if labels:
        payload["labels"] = labels
    extra: dict[str, Any] = {}
    parts = list(leaves(raw, headers, body_lo, len(raw)))
    body, body_from, trouble, truncated = _body(raw, parts)
    if body is not None:
        payload["body"] = body
    if body_from == "html":
        extra["body_from"] = "html"
        _count(counts, "body_from_html")
    if trouble:
        extra["decoding_errors"] = True
        _count(counts, "decoding_errors")
    if truncated:
        extra["body_truncated"] = True
        _count(counts, "body_truncated")
    payload["size"] = len(raw)
    attachments, blobs = _attachments(raw, parts, keep_attachments)
    if attachments:
        payload["attachments"] = attachments
        noted = "attachments_stored" if keep_attachments else "attachments_referenced"
        _count(counts, noted, len(attachments))
    if account:
        payload["account"] = account.strip().lower()
    thread_id = headers.get(THREAD_HEADER)
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


def _addresses(headers: Headers, name: str) -> list[dict[str, Any]]:
    """`{email, name?}` for every address in the header, in header order, the address lower-cased;
    an entry with no address is dropped."""
    values = headers.all(name)
    if not values:
        return []
    pairs = _simple_addresses(values)
    if pairs is None:
        try:
            pairs = getaddresses(values)
        except (LookupError, ValueError, TypeError, IndexError):
            return []
    found: list[dict[str, Any]] = []
    for display, address in pairs:
        address = address.strip().lower()
        if not address or "@" not in address:
            continue
        entry: dict[str, Any] = {"email": address}
        display = " ".join(decode_words(display).split())
        if display:
            entry["name"] = display
        found.append(entry)
    return found


def _simple_addresses(values: list[str]) -> list[tuple[str, str]] | None:
    """`(display, address)` for headers in the common shapes — `Name <a@b>`, `"Name" <a@b>`,
    `a@b`, comma-separated — read by one regular expression each; None for anything else
    (groups, comments, a comma inside a name), left to `getaddresses`."""
    found: list[tuple[str, str]] = []
    for value in values:
        if "(" in value or ":" in value:
            return None
        for item in value.split(","):
            item = item.strip()
            if not item:
                continue
            m = SIMPLE_ADDRESS.match(item)
            if m is None:
                return None
            quoted, bare, bracketed, alone = m.groups()
            display = quoted if quoted is not None else (bare or "")
            found.append((display.strip(), bracketed or alone or ""))
    return found


def _labels(value: str | None) -> list[str]:
    if not value:
        return []
    return [label.strip() for label in decode_words(value).split(",") if label.strip()]


def _when(header: str | None, separator: bytes) -> tuple[str | None, str | None]:
    """(`at` in UTC, `date` with the header's offset), the header's own; the separator's date, and
    no `date`, when the header is missing or unreadable; (None, None) when neither is readable."""
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


def _body(raw: bytes, parts: list[Part]) -> tuple[str | None, str | None, bool, bool]:
    """(text, where it came from — `plain` or `html` — or None, whether bytes were replaced,
    whether the part was cut at BODY_CAP): the first `text/plain` leaf that is not an attachment,
    else the first `text/html` one stripped."""
    plain: tuple[str, bool, bool] | None = None
    html_part: tuple[str, bool, bool] | None = None
    for part in parts:
        if _is_attachment(part.headers):
            continue
        ctype = part.headers.content_type()[0]
        if ctype == "text/plain" and plain is None:
            plain = _decode_text(raw, part)
            break
        if ctype == "text/html" and html_part is None:
            html_part = _decode_text(raw, part)
    if plain is not None:
        return plain[0], "plain", plain[1], plain[2]
    if html_part is not None:
        return strip_html(html_part[0]), "html", html_part[1], html_part[2]
    return None, None, False, False


def _is_attachment(headers: Headers) -> bool:
    if headers.disposition()[0] == "attachment":
        return True
    if headers.filename():
        return True
    return not headers.content_type()[0].startswith("text/")


def _decode_text(raw: bytes, part: Part) -> tuple[str, bool, bool]:
    """A text part as str from at most BODY_CAP bytes of it: its charset when Python knows it and
    the bytes obey it, else UTF-8 with replacement characters; the flags say whether anything was
    replaced or guessed, and whether the part was cut."""
    data, truncated = _window(raw, part.lo, part.hi, part.headers.encoding())
    charset = (part.headers.content_type()[1].get("charset") or "utf-8").strip() or "utf-8"
    try:
        if truncated:  # a multi-byte character may be cut: an incremental decoder holds its start
            text = codecs.getincrementaldecoder(charset)(errors="strict").decode(data, final=False)
        else:
            text = data.decode(charset)
        trouble = False
    except (LookupError, UnicodeDecodeError, ValueError):
        text = data.decode("utf-8", errors="replace")
        trouble = True
    return text.replace("\r\n", "\n").replace("\r", "\n"), trouble, truncated


def _window(raw: bytes, lo: int, hi: int, encoding: str) -> tuple[bytes, bool]:
    """At most BODY_CAP bytes of the part `raw[lo:hi]` decoded from its transfer encoding, and
    whether the part was longer than what was read."""
    if encoding == "base64":
        take = BODY_CAP * 4 // 3 + BODY_CAP // 16 + 8  # the cap in base64 with its line breaks
        window = b"".join(raw[lo : min(hi, lo + take)].split())
        truncated = hi - lo > take
        if truncated:
            window = window[: len(window) - len(window) % 4]
        try:
            data = base64.b64decode(window, validate=False)
        except (binascii.Error, ValueError):
            data = raw[lo : lo + BODY_CAP]
    elif encoding == "quoted-printable":
        truncated = hi - lo > BODY_CAP + 128
        end = min(hi, lo + BODY_CAP + 128)
        if truncated:
            cut = raw.rfind(b"\n", lo, end)
            end = cut + 1 if cut > lo else end
        data = quopri.decodestring(raw[lo:end])
    else:
        truncated = hi - lo > BODY_CAP
        data = raw[lo : min(hi, lo + BODY_CAP)]
    if len(data) > BODY_CAP:
        data, truncated = data[:BODY_CAP], True
    return data, truncated


def _attachments(raw: bytes, parts: list[Part], keep: bool) -> tuple[list[dict[str, Any]], list[bytes]]:
    """Every attachment leaf as `{filename, media_type, bytes}` (+ `sha256` and `path` when `keep`,
    the only time the bytes are decoded), and the bytes to store, in message order."""
    found: list[dict[str, Any]] = []
    blobs: list[bytes] = []
    for part in parts:
        if not _is_attachment(part.headers):
            continue
        entry: dict[str, Any] = {
            "filename": part.headers.filename(),
            "media_type": part.headers.content_type()[0],
        }
        if keep:
            data = _decode(raw, part)
            sha256 = hashlib.sha256(data).hexdigest()
            entry.update(bytes=len(data), sha256=sha256, path=f"{ATTACHMENTS_DIR}/{sha256}")
            blobs.append(data)
        else:
            entry["bytes"] = _decoded_length(raw, part)
        found.append(entry)
    return found, blobs


def _decoded_length(raw: bytes, part: Part) -> int:
    """How long the part is once decoded, measured without decoding it: for base64 from the count
    of its characters and padding; for anything else the part's own length."""
    lo, hi = part.lo, part.hi
    if part.headers.encoding() != "base64":
        return hi - lo
    newlines = raw.count(b"\n", lo, hi)
    first = raw.find(b"\n", lo, hi)
    crlf = first > lo and raw[first - 1] == 0x0D
    chars = (hi - lo) - newlines * (2 if crlf else 1)
    padding = raw.count(b"=", max(lo, hi - 8), hi)
    return max((chars // 4) * 3 - padding, 0)


def _decode(raw: bytes, part: Part) -> bytes:
    encoding = part.headers.encoding()
    data = raw[part.lo : part.hi]
    if encoding == "base64":
        try:
            return base64.b64decode(b"".join(data.split()), validate=False)
        except (binascii.Error, ValueError):
            return data
    if encoding == "quoted-printable":
        return quopri.decodestring(data)
    return data


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
