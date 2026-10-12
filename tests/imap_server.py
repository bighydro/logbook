"""An IMAP4rev1 server in this process, on the loopback interface, for the tests of `sync mail`.

Enough of RFC 3501 for one read-only client: CAPABILITY, LOGIN, LIST (with the SPECIAL-USE attributes of
RFC 6154, or XLIST's), EXAMINE, UID SEARCH (SINCE, UID, ALL) and UID FETCH (UID, INTERNALDATE,
RFC822.SIZE, BODY.PEEK[], BODY.PEEK[HEADER.FIELDS (...)], and Gmail's X-GM-LABELS and X-GM-THRID when
the server is `gmail`), LOGOUT. Every command line a client sends is kept in `commands`, so a test can
assert that a client never sent SELECT, STORE, COPY, MOVE, EXPUNGE or APPEND and fetched bodies with
PEEK. SELECT and the writing commands are answered with NO and still logged. `drop_at_fetch` closes
the connection without a reply on that FETCH (the first is 1), for the test of a walk cut off midway.
No TLS: the client under test is given this server through its connection hook. The mailboxes and the
people in them are synthetic (Ines and Ola Nordmann of Oslo, who do not exist)."""

from __future__ import annotations

import re
import socketserver
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|(\(|\))|(\[[^\]]*\])|([^\s()"\[\]]+)')
WRITES = ("SELECT", "STORE", "COPY", "MOVE", "EXPUNGE", "APPEND", "CREATE", "DELETE", "RENAME")


@dataclass
class Message:
    uid: int
    raw: bytes
    internaldate: str  # IMAP date-time: `02-Mar-2026 10:15:00 +0000`
    labels: tuple[str, ...] = ()  # Gmail labels as X-GM-LABELS spells them: `\\Inbox`, `Work`
    thrid: int | None = None

    @property
    def day(self) -> datetime:
        return datetime.strptime(self.internaldate.split()[0], "%d-%b-%Y")


@dataclass
class Folder:
    name: str
    uidvalidity: int
    messages: dict[int, Message] = field(default_factory=dict)
    attributes: tuple[str, ...] = ()  # `\\All`, `\\Sent`, ... (special-use)

    @property
    def uidnext(self) -> int:
        return max(self.messages, default=0) + 1


def internaldate(when: datetime) -> str:
    """A datetime (with offset) as IMAP spells it."""
    return f"{when.day:02d}-{MONTHS[when.month - 1]}-{when.year} {when.strftime('%H:%M:%S %z')}"


class FakeImap:
    """The server: `start()` listens on 127.0.0.1 and returns the port; `stop()` closes it."""

    def __init__(
        self,
        folders: list[Folder],
        user: str = "ines.nordmann@example.org",
        password: str = "abcd efgh ijkl mnop",
        gmail: bool = True,
        special_use: bool = True,
        xlist: bool = False,
    ) -> None:
        self.folders = {f.name: f for f in folders}
        self.user, self.password = user, password
        self.gmail, self.special_use, self.xlist = gmail, special_use, xlist
        self.commands: list[str] = []  # every command line, tag removed
        self.connections = 0
        self.fetches = 0
        self.drop_at_fetch: int | None = None
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def capabilities(self) -> str:
        caps = ["IMAP4rev1", "UIDPLUS", "LIST-EXTENDED"]
        if self.special_use:
            caps.append("SPECIAL-USE")
        if self.xlist:
            caps.append("XLIST")
        if self.gmail:
            caps.append("X-GM-EXT-1")
        return " ".join(caps)

    def start(self) -> int:
        self._server = _Server(("127.0.0.1", 0), _Handler, self)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return int(self._server.server_address[1])

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def __enter__(self) -> FakeImap:
        self.port = self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def sent(self, name: str) -> list[str]:
        """The command lines whose command (`UID FETCH` counts as `FETCH`) is `name`."""
        found = []
        for line in self.commands:
            words = line.split()
            command = words[1] if words and words[0] == "UID" and len(words) > 1 else words[0]
            if command.upper() == name.upper():
                found.append(line)
        return found


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], handler: type, fake: FakeImap) -> None:
        self.fake = fake
        super().__init__(address, handler)


class _Drop(Exception):
    """Close the connection now, without a reply."""


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        fake: FakeImap = self.server.fake  # type: ignore[attr-defined]
        fake.connections += 1
        self.selected: Folder | None = None
        self.authenticated = False
        self._write(f"* OK [CAPABILITY {fake.capabilities}] fake imap ready")
        while True:
            line = self.rfile.readline()
            if not line:
                return
            text = line.decode("utf-8", errors="replace").rstrip("\r\n")
            tag, _, rest = text.partition(" ")
            fake.commands.append(rest)
            try:
                if not self._dispatch(fake, tag, rest):
                    return
            except _Drop:
                return

    def _write(self, text: str) -> None:
        self.wfile.write(text.encode("utf-8") + b"\r\n")

    def _dispatch(self, fake: FakeImap, tag: str, rest: str) -> bool:
        tokens = _tokens(rest)
        command = str(tokens[0]).upper() if tokens else ""
        args = tokens[1:]
        if command == "UID" and args:
            command = "UID " + str(args[0]).upper()
            args = args[1:]
        if command == "CAPABILITY":
            self._write(f"* CAPABILITY {fake.capabilities}")
            self._write(f"{tag} OK CAPABILITY completed")
        elif command == "NOOP":
            self._write(f"{tag} OK NOOP completed")
        elif command == "LOGOUT":
            self._write("* BYE fake imap logging out")
            self._write(f"{tag} OK LOGOUT completed")
            return False
        elif command == "LOGIN":
            if len(args) == 2 and args[0] == fake.user and args[1] == fake.password:
                self.authenticated = True
                self._write(f"{tag} OK [CAPABILITY {fake.capabilities}] {fake.user} authenticated")
            else:
                self._write(f"{tag} NO [AUTHENTICATIONFAILED] Invalid credentials (Failure)")
        elif not self.authenticated:
            self._write(f"{tag} BAD not authenticated")
        elif command in ("LIST", "XLIST", "LSUB"):
            self._list(fake, tag, command)
        elif command == "EXAMINE":
            self._examine(fake, tag, args)
        elif command == "UID SEARCH":
            self._search(fake, tag, args)
        elif command == "UID FETCH":
            self._fetch(fake, tag, args)
        elif command in WRITES or command.removeprefix("UID ") in WRITES:
            self._write(f"{tag} NO this server is read-only in the tests")
        else:
            self._write(f"{tag} BAD unknown command")
        return True

    def _list(self, fake: FakeImap, tag: str, command: str) -> None:
        for folder in fake.folders.values():
            attributes = ["\\HasNoChildren"]
            if fake.special_use or command == "XLIST":
                attributes += list(folder.attributes)
            if command == "XLIST":  # Gmail's older spelling: `\\AllMail`, and INBOX flagged `\\Inbox`
                attributes = ["\\AllMail" if a == "\\All" else a for a in attributes]
                if folder.name == "INBOX":
                    attributes.append("\\Inbox")
            self._write(f'* {command} ({" ".join(attributes)}) "/" {_quote(folder.name)}')
        self._write(f"{tag} OK {command} completed")

    def _examine(self, fake: FakeImap, tag: str, args: list[Any]) -> None:
        name = str(args[0]) if args else ""
        folder = fake.folders.get(name)
        if folder is None:
            self.selected = None
            self._write(f"{tag} NO [NONEXISTENT] Unknown Mailbox: {name} (Failure)")
            return
        self.selected = folder
        self._write("* FLAGS (\\Answered \\Flagged \\Draft \\Deleted \\Seen)")
        self._write(f"* {len(folder.messages)} EXISTS")
        self._write("* 0 RECENT")
        self._write(f"* OK [UIDVALIDITY {folder.uidvalidity}] UIDs valid")
        self._write(f"* OK [UIDNEXT {folder.uidnext}] Predicted next UID")
        self._write(f"{tag} OK [READ-ONLY] {name} selected. (Success)")

    def _search(self, fake: FakeImap, tag: str, args: list[Any]) -> None:
        folder = self.selected
        if folder is None:
            self._write(f"{tag} BAD no folder selected")
            return
        uids = sorted(folder.messages)
        i = 0
        while i < len(args):
            word = str(args[i]).upper()
            if word == "SINCE":
                day = datetime.strptime(str(args[i + 1]), "%d-%b-%Y")
                uids = [u for u in uids if folder.messages[u].day >= day]
                i += 2
            elif word == "UID":
                wanted = _uid_set(str(args[i + 1]), uids)
                uids = [u for u in uids if u in wanted]
                i += 2
            elif word == "ALL":
                i += 1
            else:
                self._write(f"{tag} BAD unknown search key {word}")
                return
        self._write("* SEARCH" + "".join(f" {u}" for u in uids))
        self._write(f"{tag} OK SEARCH completed")

    def _fetch(self, fake: FakeImap, tag: str, args: list[Any]) -> None:
        folder = self.selected
        if folder is None:
            self._write(f"{tag} BAD no folder selected")
            return
        fake.fetches += 1
        if fake.drop_at_fetch is not None and fake.fetches == fake.drop_at_fetch:
            raise _Drop()
        uids = sorted(_uid_set(str(args[0]), sorted(folder.messages)) & set(folder.messages))
        items = args[1] if len(args) > 1 and isinstance(args[1], list) else args[1:]
        for sequence, uid in enumerate(uids, start=1):
            self._fetch_one(fake, folder.messages[uid], sequence, [str(i) for i in items])
        self._write(f"{tag} OK FETCH completed")

    def _fetch_one(self, fake: FakeImap, message: Message, sequence: int, items: list[str]) -> None:
        # Items are answered in the order asked, UID first: a literal (the body) ends its line, and the
        # items asked after it follow the literal's bytes, so the client must read a response whose
        # literal is not last.
        before: list[bytes] = [f"UID {message.uid}".encode()]
        literal: bytes | None = None
        after: list[bytes] = []
        for item in items:
            upper = item.upper()
            target = after if literal is not None else before
            if upper == "UID":
                continue
            if upper == "INTERNALDATE":
                target.append(f'INTERNALDATE "{message.internaldate}"'.encode())
            elif upper == "RFC822.SIZE":
                target.append(f"RFC822.SIZE {len(message.raw)}".encode())
            elif upper == "X-GM-THRID" and fake.gmail:
                target.append(f"X-GM-THRID {message.thrid or message.uid}".encode())
            elif upper == "X-GM-LABELS" and fake.gmail:
                labels = " ".join(_label(label) for label in message.labels)
                target.append(f"X-GM-LABELS ({labels})".encode())
            elif (upper.startswith("BODY.PEEK[") or upper.startswith("BODY[")) and literal is None:
                section = item[item.index("[") + 1 : item.rindex("]")]
                literal = _section(message.raw, section)
                before.append(f"BODY[{section}] {{{len(literal)}}}".encode())
            elif upper in ("RFC822", "RFC822.HEADER", "RFC822.TEXT") and literal is None:
                literal = message.raw
                before.append(f"{upper} {{{len(literal)}}}".encode())
        head = f"* {sequence} FETCH (".encode() + b" ".join(before)
        if literal is None:
            self.wfile.write(head + b")\r\n")
            return
        tail = (b" " + b" ".join(after) if after else b"") + b")\r\n"
        self.wfile.write(head + b"\r\n" + literal + tail)


def _section(raw: bytes, section: str) -> bytes:
    """`BODY[]` is the message; `BODY[HEADER.FIELDS (A B)]` the named header lines, then a blank line."""
    if not section:
        return raw
    m = re.match(r"HEADER\.FIELDS \(([^)]*)\)", section, re.IGNORECASE)
    if m is None:
        return raw
    wanted = {name.lower() for name in m.group(1).split()}
    header = raw.split(b"\r\n\r\n", 1)[0] if b"\r\n\r\n" in raw else raw.split(b"\n\n", 1)[0]
    out: list[bytes] = []
    keep = False
    for line in header.splitlines(keepends=True):
        if line[:1] in (b" ", b"\t"):
            if keep:
                out.append(line)
            continue
        name = line.split(b":", 1)[0].decode("ascii", errors="replace").lower()
        keep = name in wanted
        if keep:
            out.append(line)
    text = b"".join(out)
    if not text.endswith(b"\n"):
        text += b"\r\n"
    return text + b"\r\n"


def _label(label: str) -> str:
    """A system label (`\\Inbox`) is an atom; anything else is quoted."""
    return label if label.startswith("\\") else _quote(label)


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _tokens(text: str) -> list[Any]:
    """Atoms and quoted strings as str, parenthesised lists as lists, `[...]` kept with its atom."""
    stack: list[list[Any]] = [[]]
    pos = 0
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if m is None:
            pos += 1
            continue
        pos = m.end()
        quoted, paren, bracket, atom = m.groups()
        if paren == "(":
            stack.append([])
        elif paren == ")":
            done = stack.pop()
            stack[-1].append(done)
        elif quoted is not None:
            stack[-1].append(quoted.replace('\\"', '"').replace("\\\\", "\\"))
        elif bracket is not None:
            if stack[-1] and isinstance(stack[-1][-1], str) and stack[-1][-1].upper().startswith("BODY"):
                stack[-1][-1] = stack[-1][-1] + bracket
            else:
                stack[-1].append(bracket)
        else:
            stack[-1].append(atom)
    while len(stack) > 1:
        done = stack.pop()
        stack[-1].append(done)
    return stack[0]


def _uid_set(text: str, known: list[int]) -> set[int]:
    """`1,3:5,7:*` as the UIDs it names; `*` is the largest UID the folder has."""
    largest = max(known, default=0)
    found: set[int] = set()
    for piece in text.split(","):
        lo, _, hi = piece.partition(":")
        a = largest if lo == "*" else int(lo)
        b = a if not hi else (largest if hi == "*" else int(hi))
        if a > b:
            a, b = b, a
        if a == b == largest or not known:
            found.add(a)
        found.update(u for u in known if a <= u <= b)
    return found
