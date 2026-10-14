"""One email is one line, whichever road brought it: the Takeout mbox (`add mail`), IMAP (`sync mail`) or
the Gmail API (`sync gmail`). Every road reads the message's own Message-ID; the lines carry it normalised
(`payload.message_id`), and each road skips a message the record already holds by it, from any of the
three, before it writes (RFC 0015, amendment of 2026-10-14).

Synthetic mail only: Ines, Ola and Kari Nordmann of Oslo, who do not exist, at example.org."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import imaplib
import random
import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from google_fake import USER, Fake, private_key, write_key
from imap_server import FakeImap, Folder, Message, internaldate

from logbook import cli
from logbook.contrib import mail_lookup
from logbook.contrib.adapters import mail, mail_imap, service_account
from logbook.core import sealing
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
INES = "ines.nordmann@example.org"  # a mailbox of her own, at another address
OLA = "ola@example.org"


# -- the normalised Message-ID ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("<a1b2c3@mail.example.org>", "a1b2c3@mail.example.org"),
        ("a1b2c3@mail.example.org", "a1b2c3@mail.example.org"),
        ("  <a1b2c3@Mail.Example.ORG>\t", "a1b2c3@mail.example.org"),
        (" < a1b2c3@MAIL.EXAMPLE.ORG > ", "a1b2c3@mail.example.org"),
        ("<CAAbC.12+x@Mail.Example.ORG>", "CAAbC.12+x@mail.example.org"),  # the local part as written
        ('<"a@B"@Example.ORG>', '"a@B"@example.org'),  # the domain is after the last `@`
        ("<NoDomainHere>", "NoDomainHere"),  # no `@`: nothing is lowered
        ("<x@[192.0.2.1]>", "x@[192.0.2.1]"),
        ("<x@BÜCHER.Example.ORG>", "x@bÜcher.example.org"),  # ASCII letters only
    ],
)
def test_a_message_id_is_normalised_brackets_whitespace_and_the_domains_case(
    given: str, expected: str
) -> None:
    assert mail.normalise_id(given) == expected
    assert mail.normalise_id(expected) == expected, "normalising twice changes nothing"


@pytest.mark.parametrize("given", [None, "", "   ", "<>", "< >", "<\t>"])
def test_an_empty_message_id_is_no_message_id(given: str | None) -> None:
    assert mail.normalise_id(given) is None


@pytest.mark.parametrize(
    ("one", "other"),
    [
        ("<abc@mail.example.org>", "<ABC@mail.example.org>"),  # the local part's case tells two apart
        ("<CAAbC12@mail.example.org>", "<CAABC12@mail.example.org>"),
        ("<abc@mail.example.org>", "<abc@mail2.example.org>"),
        ("<abc@mail.example.org>", "<abc.@mail.example.org>"),
        ("<a b@mail.example.org>", "<ab@mail.example.org>"),  # inner whitespace is never folded away
        ("<x@BÜCHER.example.org>", "<x@büCHER.example.org>"),  # non-ASCII case is not folded
        ("<abc@mail.example.org>", "<abc@mail.example.org.>"),
    ],
)
def test_two_different_message_ids_never_normalise_to_one(one: str, other: str) -> None:
    assert mail.normalise_id(one) != mail.normalise_id(other)


def test_a_header_with_two_ids_names_the_first() -> None:
    assert mail.normalise_id(mail.first_id("<one@Example.ORG> <two@example.org>")) == "one@example.org"


# -- what the line carries ----------------------------------------------------------------------------------


def _raw(message_id: str | None, extra: str = "", subject: str = "Mooring", body: str = "Hei.") -> bytes:
    head = "" if message_id is None else f"Message-ID: {message_id}\r\n"
    return (
        f"{head}Date: Mon, 02 Mar 2026 11:15:00 +0100\r\nFrom: Ola Nordmann <{OLA}>\r\n"
        f"To: Ines Nordmann <{INES}>\r\nSubject: {subject}\r\n{extra}"
        f'Content-Type: text/plain; charset="utf-8"\r\n\r\n{body}\r\n'
    ).encode()


def _line(raw: bytes, account: str | None = None, counts: dict[str, int] | None = None) -> dict:
    line, _blobs = mail.parse_message(raw, None, {} if counts is None else counts, TZ, None, {INES}, account)
    assert line is not None
    return line


def test_the_line_carries_the_normalised_message_id_and_keeps_the_headers_spelling_elsewhere() -> None:
    """`message_id` is the key the roads share; `raw_id`, `thread` and the reply headers keep the spelling
    every line written before carries, so the store's own dedupe and a thread's join are unchanged."""
    raw = _raw(
        "  <Reply.7@Mail.Example.ORG>",
        extra="In-Reply-To: <Root.1@Mail.Example.ORG>\r\nReferences: <Root.1@Mail.Example.ORG>\r\n",
    )
    payload = _line(raw, account=INES)["payload"]
    assert payload["message_id"] == "Reply.7@mail.example.org"
    assert payload["raw_id"] == f"{INES}:Reply.7@Mail.Example.ORG"
    assert payload["thread"] == "Root.1@Mail.Example.ORG"
    assert payload["extra"]["in_reply_to"] == "Root.1@Mail.Example.ORG"
    assert payload["extra"]["references"] == ["Root.1@Mail.Example.ORG"]
    root = _line(_raw("<Root.1@Mail.Example.ORG>"))["payload"]
    assert root["thread"] == payload["thread"], "a thread's root and its reply still join"
    assert root["message_id"] == "Root.1@mail.example.org" and root["raw_id"] == "Root.1@Mail.Example.ORG"


@pytest.mark.parametrize("header", ["<>", "< >"])
def test_a_blank_message_id_is_keyed_by_the_messages_bytes_as_one_without(header: str) -> None:
    """`Message-ID: <>` names no message: each such message is keyed by its own bytes and counted, never
    folded into one key that every such message would share."""
    counts: dict[str, int] = {}
    first = _line(_raw(header, subject="One"), counts=counts)["payload"]
    second = _line(_raw(header, subject="Two"), counts=counts)["payload"]
    assert "message_id" not in first and "message_id" not in second
    assert first["raw_id"] == f"sha256:{hashlib.sha256(_raw(header, subject='One')).hexdigest()}"
    assert first["raw_id"] != second["raw_id"]
    assert counts["no_message_id"] == 2


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("<>", None),
        ("< >", None),
        ("<<>>", None),
        (">", None),
        ("<> <a@b>", "a@b"),
        ("<> a@B", "a@B"),
        ("<a@b> <>", "a@b"),
        ("<a@b>", "a@b"),
        ("a@b", "a@b"),
        ("<a@b", "<a@b"),
        ("<a@b> (c)", "a@b"),
        ("<one@a> <two@b>", "one@a"),
    ],
)
def test_first_id_drops_a_token_of_brackets_alone_and_nothing_else(value: str, expected: str | None) -> None:
    assert mail.first_id(value) == expected


def test_a_blank_in_reply_to_or_references_threads_the_message_on_itself() -> None:
    payload = _line(_raw("<own@mail.example.org>", extra="In-Reply-To: <>\r\nReferences: <>\r\n"))["payload"]
    assert payload["thread"] == "own@mail.example.org"
    assert "in_reply_to" not in payload.get("extra", {}) and "references" not in payload.get("extra", {})


@pytest.mark.parametrize(
    "header",
    [
        "<Fold.1@\r\n Mail.Example.ORG>",
        "<Fold.2@Mail.Example.ORG>\r\n (added by the relay)",
        "<Fold.3@Mail.Example.ORG\r\n >",
        "\r\n <Fold.4@Mail.Example.ORG>",
        "<Fold.5@Mail.Example.ORG> <Other.5@mail.example.org>",
    ],
)
def test_the_header_pass_and_the_parser_read_one_stored_message_id_alike(header: str) -> None:
    """`sync mail`'s header pass reads HEADER.FIELDS (MESSAGE-ID) through `Headers` and `first_id`, as
    `sync gmail`'s reads the metadata: the same bytes give the key the line carries, and normalising it
    again changes nothing."""
    raw = _raw(header)
    written = _line(raw)["payload"]["message_id"]
    fields = raw.split(b"\r\nDate:")[0] + b"\r\n\r\n"
    asked = mail.ask(mail.first_id(mail.Headers(fields).get("message-id")), INES)
    assert asked is not None and asked.message_id == written == mail.normalise_id(written)


# -- the three roads ----------------------------------------------------------------------------------------
#
# Ines's mailbox, `ines@example.org` (google_fake.USER, the account the service-account key reads as): three
# messages of one week, each as the mailbox stores it, read by the Takeout export (an mbox), by IMAP and by
# the Gmail API. The same bytes on every road, as Gmail serves them; Takeout adds its two headers.

T0 = datetime(2026, 3, 2, 10, 15, tzinfo=UTC)
WEEK = [
    ("<m1@mail.example.org>", T0, False, "Mooring", ""),
    ("<m2@mail.example.org>", T0 + timedelta(hours=12), True, "Re: Mooring", ""),
    ("<m3@mail.example.org>", T0 + timedelta(hours=24), False, "Berth", ""),
]


def _stored(
    message_id: str | None, when: datetime, sent: bool = False, subject: str = "Mooring", extra: str = ""
) -> bytes:
    """A message as the mailbox stores it, CRLF and all; Ines sends when `sent`, else Ola does."""
    sender, to = (f"Ines Nordmann <{USER}>", f"Ola Nordmann <{OLA}>")
    if not sent:
        sender, to = to, sender
    head = "" if message_id is None else f"Message-ID: {message_id}\r\n"
    return (
        f"{head}Date: {when.strftime('%a, %d %b %Y %H:%M:%S %z')}\r\nFrom: {sender}\r\nTo: {to}\r\n"
        f'Subject: {subject}\r\n{extra}Content-Type: text/plain; charset="utf-8"\r\n\r\nHei.\r\n'
    ).encode()


def _week(spell: Callable[[str], str] = lambda message_id: message_id) -> list[tuple[bytes, datetime]]:
    return [
        (_stored(spell(mid), when, sent, subject, extra), when) for mid, when, sent, subject, extra in WEEK
    ]


def _mbox(path: Path, messages: list[tuple[bytes, datetime]]) -> Path:
    """The Takeout export of those messages: a separator line each, and Takeout's own two headers."""
    with path.open("wb") as fh:
        for n, (raw, when) in enumerate(messages, start=1):
            fh.write(
                f"From 17951234567890{n:05d}@xxx {when.strftime('%a %b %d %H:%M:%S +0000 %Y')}\n".encode()
            )
            fh.write(
                f"X-GM-THRID: 17951234567890{n:05d}\r\nX-Gmail-Labels: Inbox\r\n".encode() + raw + b"\r\n"
            )
    return path


def _imap(messages: list[tuple[bytes, datetime]]) -> FakeImap:
    return FakeImap(
        [
            Folder(
                "[Gmail]/All Mail",
                1234,
                {
                    uid: Message(uid, raw, internaldate(when), labels=("\\Inbox",))
                    for uid, (raw, when) in enumerate(messages, start=1)
                },
                attributes=("\\All",),
            )
        ],
        user=USER,
    )


@pytest.fixture(scope="module")
def key() -> Any:
    return private_key()


@pytest.fixture
def gmail_api(tmp_path: Path, key: Any, monkeypatch: pytest.MonkeyPatch) -> Fake:
    """The Gmail API's fake, holding nothing yet: a test delivers what the mailbox holds."""
    fake = Fake(key)
    fake.labels = [{"id": "INBOX", "name": "INBOX", "type": "system"}]
    monkeypatch.setattr(service_account, "send", fake)
    monkeypatch.setattr(service_account, "sleep", lambda _s: None)
    monkeypatch.setenv(service_account.KEY_ENV, str(write_key(tmp_path / "google-sa.json", key)))
    monkeypatch.setenv(service_account.USER_ENV, USER)
    return fake


def _deliver(fake: Fake, messages: list[tuple[bytes, datetime]]) -> None:
    for raw, when in messages:
        fake.deliver(raw, when, ("INBOX",))


@contextlib.contextmanager
def _serving(fake: FakeImap, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeImap]:
    port = fake.start()
    monkeypatch.setenv("LOGBOOK_IMAP_HOST", "imap.example.org")
    monkeypatch.setenv("LOGBOOK_IMAP_USER", fake.user)
    monkeypatch.setenv("LOGBOOK_IMAP_PASSWORD", fake.password)
    monkeypatch.setattr(
        mail_imap, "open_connection", lambda config: imaplib.IMAP4("127.0.0.1", port, timeout=10)
    )
    try:
        yield fake
    finally:
        fake.stop()


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.set_owner_emails([USER])
    return lb


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    try:
        cli.main(list(args))
    except SystemExit as e:
        status = e.code if isinstance(e.code, int) else 1
    else:
        status = 0
    out = capsys.readouterr()
    return status, out.out, out.err


def _record(lb: Logbook) -> bytes:
    """Every month file's bytes, in order: what a run that writes nothing must leave as it was."""
    return b"".join(path.read_bytes() for path in sorted((lb.root / "logbook").glob("*/*.jsonl")))


def _raw_asked(fake: Fake) -> list[dict[str, Any]]:
    return [params for _m, _p, params in fake.requests if params.get("format") == "raw"]


def test_a_takeout_imported_without_its_account_then_gmail_writes_each_message_once(
    lb: Logbook,
    gmail_api: Fake,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    no_network: list[str],
) -> None:
    """The case that wrote every message twice: the export keyed `<Message-ID>` (no `--account`), the API
    `<account>:<Message-ID>`. The dry run says what it would skip and from where; the run writes nothing,
    fetches no body and leaves every line already written as it was."""
    status, out, err = _run(capsys, "add", "mail", str(_mbox(tmp_path / "all.mbox", _week())))
    assert status == 0, err
    assert lb.meta["seq"] == 3 and {line["payload"]["raw_id"] for line in lb.lines()} == {
        "m1@mail.example.org",
        "m2@mail.example.org",
        "m3@mail.example.org",
    }
    before = _record(lb)
    _deliver(gmail_api, _week())
    status, out, err = _run(capsys, "sync", "gmail", "--dry-run")
    assert status == 0, err
    assert "gmail: 0 lines from the beginning (dry run, nothing written)" in out
    assert "  3 already in the record from mail (an import without --account)" in out.splitlines()
    assert _raw_asked(gmail_api) == [], "a dry run fetches no body the record holds either"
    status, out, err = _run(capsys, "sync", "gmail")
    assert status == 0, err
    assert "gmail: 0 new lines of 0 seen from the beginning" in out
    assert "  3 already in the record from mail (an import without --account)" in out.splitlines()
    assert "3 listed, 0 new, 3 already in the record" in err
    assert _raw_asked(gmail_api) == [] and lb.meta["seq"] == 3
    assert _record(lb) == before, "no line written before is touched"
    assert no_network == [], "the fake is the only way out"


def test_gmail_then_imap_writes_each_message_once(
    lb: Logbook, gmail_api: Fake, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _deliver(gmail_api, _week())
    status, _out, err = _run(capsys, "sync", "gmail")
    assert status == 0 and lb.meta["seq"] == 3, err
    before = _record(lb)
    with _serving(_imap(_week()), monkeypatch) as imap:
        status, out, err = _run(capsys, "sync", "mail")
        assert status == 0, err
        assert "mail: 0 new lines of 0 seen" in out
        assert "3 fetched, 0 new, 3 already in the record" in err
        assert not [line for line in imap.sent("FETCH") if "BODY.PEEK[]" in line], "no body was fetched"
    assert lb.meta["seq"] == 3 and _record(lb) == before


def test_the_same_message_id_spelled_with_other_case_and_brackets_is_one_message(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The export spells `<Berth.9@Mail.Example.ORG>`, the server ` Berth.9@MAIL.EXAMPLE.ORG` (no brackets,
    other case): neither spelling is a key of the other, so the server's message is read and, once read,
    known by its normalised id among the lines of its days. The local part's case is never folded."""
    messages = [(_stored("<Berth.9@Mail.Example.ORG>", T0, subject="Berth"), T0)]
    status, _out, err = _run(
        capsys, "add", "mail", str(_mbox(tmp_path / "all.mbox", messages)), "--account", USER
    )
    assert status == 0 and lb.meta["seq"] == 1, err
    respelled = [(_stored(" Berth.9@MAIL.EXAMPLE.ORG", T0, subject="Berth"), T0)]
    with _serving(_imap(respelled), monkeypatch):
        status, out, err = _run(capsys, "sync", "mail")
    assert status == 0, err
    assert "mail: 0 new lines of 0 seen" in out
    assert f"  1 already in the record from mail ({USER})" in out.splitlines()
    assert lb.meta["seq"] == 1
    (line,) = list(lb.lines())
    assert line["payload"]["message_id"] == "Berth.9@mail.example.org"
    assert line["payload"]["raw_id"] == f"{USER}:Berth.9@Mail.Example.ORG"


def test_ids_that_differ_before_the_at_are_two_messages(
    lb: Logbook, gmail_api: Fake, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Same time, same people, same domain, the local part in another case: two messages, two lines."""
    _run(
        capsys,
        "add",
        "mail",
        str(_mbox(tmp_path / "all.mbox", [(_stored("<AbC.1@mail.example.org>", T0), T0)])),
    )
    _deliver(gmail_api, [(_stored("<abc.1@mail.example.org>", T0), T0)])
    status, out, err = _run(capsys, "sync", "gmail")
    assert status == 0, err
    assert "gmail: 1 new lines of 1 seen" in out and "already in the record from" not in out
    assert sorted(line["payload"]["message_id"] for line in lb.lines()) == [
        "AbC.1@mail.example.org",
        "abc.1@mail.example.org",
    ]


def test_a_reply_with_its_own_message_id_is_a_new_line(
    lb: Logbook, gmail_api: Fake, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(capsys, "add", "mail", str(_mbox(tmp_path / "all.mbox", _week())))
    when = T0 + timedelta(hours=30)
    reply = _stored(
        "<r1@mail.example.org>",
        when,
        sent=True,
        subject="Re: Berth",
        extra="In-Reply-To: <m3@mail.example.org>\r\nReferences: <m3@mail.example.org>\r\n",
    )
    _deliver(gmail_api, [*_week(), (reply, when)])
    status, out, err = _run(capsys, "sync", "gmail")
    assert status == 0, err
    assert "gmail: 1 new lines of 1 seen" in out
    assert "  3 already in the record from mail (an import without --account)" in out.splitlines()
    new = list(lb.lines())[-1]["payload"]
    assert new["message_id"] == "r1@mail.example.org" and new["thread"] == "m3@mail.example.org"
    assert [len(_raw_asked(gmail_api))] == [1], "only the reply's body was fetched"


def test_a_message_without_a_message_id_falls_back_to_each_roads_own_key(
    lb: Logbook, gmail_api: Fake, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No Message-ID, no shared key: the export keys the message by its own bytes (Takeout's headers
    among them), the API by the bytes it serves, so each road dedupes itself, as before, and never asks the
    record by an id it does not have."""
    messages = [(_stored(None, T0, subject="No id"), T0)]
    path = _mbox(tmp_path / "all.mbox", messages)
    for _ in range(2):
        status, out, err = _run(capsys, "add", "mail", str(path), "--restart")
        assert status == 0, err
    assert lb.meta["seq"] == 1
    _deliver(gmail_api, messages)
    for _ in range(2):
        status, out, err = _run(capsys, "sync", "gmail", "--restart")
        assert status == 0, err
        assert "already in the record from" not in out
    lines = list(lb.lines())
    assert len(lines) == 2 and all("message_id" not in line["payload"] for line in lines)
    assert lines[0]["payload"]["raw_id"].startswith("sha256:")
    assert lines[1]["payload"]["raw_id"].startswith(f"{USER}:sha256:")


def test_a_message_in_a_second_mailbox_is_a_line_of_its_own(
    lb: Logbook, gmail_api: Fake, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """RFC 0015 rule 1: a message the owner received in two mailboxes is two messages. A Takeout imported
    with `--account` names its mailbox; the API reads another, so its copy is written."""
    other = "kari.nordmann@example.org"
    _run(capsys, "add", "mail", str(_mbox(tmp_path / "kari.mbox", _week())), "--account", other)
    _deliver(gmail_api, _week())
    status, out, err = _run(capsys, "sync", "gmail")
    assert status == 0, err
    assert "gmail: 3 new lines of 3 seen" in out and "already in the record from" not in out
    assert {line["payload"].get("account") for line in lb.lines()} == {other, USER}


def test_add_mail_after_gmail_skips_what_the_api_wrote_and_says_so_in_the_dry_run(
    lb: Logbook, gmail_api: Fake, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The other way round: the API first, then the export without `--account`, which asks the record
    under the owner's addresses too."""
    _deliver(gmail_api, _week())
    assert _run(capsys, "sync", "gmail")[0] == 0 and lb.meta["seq"] == 3
    before = _record(lb)
    path = _mbox(tmp_path / "all.mbox", _week())
    status, out, err = _run(capsys, "add", "mail", str(path), "--dry-run")
    assert status == 0, err
    assert "mail: 0 lines would be added, 0 already in the record (dry run, nothing written)" in out
    assert f"  3 already in the record from mail ({USER})" in out.splitlines()
    status, out, err = _run(capsys, "add", "mail", str(path))
    assert status == 0, err
    assert "added 0 lines from mail" in out
    assert f"  3 already in the record from mail ({USER})" in out.splitlines()
    assert _record(lb) == before


def test_the_skip_works_in_a_record_that_seals_its_mail(
    lb: Logbook,
    gmail_api: Fake,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Mail is tier 2: in a record that seals (RFC 0029) its payload is sealed and the index holds its
    raw_id blinded. With the identity here, both the exact keys and the lines of the day still answer."""
    pairs = [sealing.generate_identity() for _ in range(2)]
    meta = lb.meta
    meta["recipients"] = [recipient for _, recipient in pairs]
    lb._save_meta(meta)
    identity = tmp_path / "keys" / "owner.txt"
    sealing.write_identity_file(identity, pairs[0][0], "test")
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(identity))
    _deliver(gmail_api, _week())
    assert _run(capsys, "sync", "gmail")[0] == 0
    sealed = Logbook(lb.root)
    assert sealed.meta["seq"] == 3 and all(
        line["payload"]["schema"] == "sealed/v1" for line in sealed.lines()
    )
    respelled = _week(
        lambda mid: mid.upper().replace("<", " ").replace(">", "")
    )  # local parts upper-cased too
    status, out, err = _run(capsys, "add", "mail", str(_mbox(tmp_path / "all.mbox", _week())))
    assert status == 0, err
    assert (
        "added 0 lines from mail" in out
        and f"  3 already in the record from mail ({USER})" in out.splitlines()
    )
    status, out, err = _run(capsys, "add", "mail", str(_mbox(tmp_path / "upper.mbox", respelled)))
    assert status == 0, err
    assert "added 3 lines from mail" in out, (
        "an id whose local part differs is another message, sealed or not"
    )
    assert Logbook(lb.root).meta["seq"] == 6


# -- the pieces: what `run` asks, and whose line holds a message --------------------------------------------


class Asking:
    """A `held` that records what it was asked and answers from a table of normalised ids."""

    def __init__(self, answers: dict[str, mail.Holder]) -> None:
        self.answers = answers
        self.asked: list[mail.Asked] = []

    def __call__(self, asked: Sequence[mail.Asked]) -> list[mail.Holder | None]:
        self.asked.extend(asked)
        return [self.answers.get(q.message_id) for q in asked]


class Reached:
    def __init__(self) -> None:
        self.told: list[tuple[int, int]] = []

    def start(self, file: Path) -> int:
        return 0

    def reached(self, file: Path, ordinal: int, offset: int) -> None:
        self.told.append((ordinal, offset))


def test_run_asks_once_per_window_never_about_a_message_without_an_id_and_keeps_the_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mail, "LOOKUP_BATCH", 2)
    messages = [
        (_stored("<m1@mail.example.org>", T0), T0),
        (_stored(None, T0 + timedelta(hours=1), subject="No id"), T0 + timedelta(hours=1)),
        (_stored("<m2@Mail.Example.ORG>", T0 + timedelta(hours=2)), T0 + timedelta(hours=2)),
        (_stored("<m3@mail.example.org>", T0 + timedelta(hours=3)), T0 + timedelta(hours=3)),
    ]
    path = _mbox(tmp_path / "all.mbox", messages)
    asking = Asking({"m2@mail.example.org": mail.Holder(own=False, account=USER)})
    cursor, counts = Reached(), {}
    lines = list(mail.run(path, timezone=TZ, counts=counts, held=asking, cursor=cursor))
    assert [line["payload"].get("message_id") for line in lines] == [
        "m1@mail.example.org",
        None,
        "m3@mail.example.org",
    ]
    assert [q.message_id for q in asking.asked] == [
        "m1@mail.example.org",
        "m2@mail.example.org",
        "m3@mail.example.org",
    ], "the message without an id is never asked about"
    assert [q.spelled for q in asking.asked][1] == "m2@Mail.Example.ORG" and asking.asked[1].at is not None
    assert counts[f"{mail.HELD}mail ({USER})"] == 1 and counts["no_message_id"] == 1
    ordinals = [ordinal for ordinal, _offset in cursor.told]
    offsets = [offset for _ordinal, offset in cursor.told]
    assert ordinals == [1, 2, 3, 3] and offsets == sorted(offsets), (
        "the cursor is told in order, the end last"
    )
    unasked = list(mail.run(path, timezone=TZ, counts={}))
    assert len(unasked) == 4 and [unasked[0], unasked[1], unasked[3]] == lines, (
        "the same drafts, less the held"
    )


def _draft(message_id: str | None, account: str | None, when: datetime = T0) -> dict[str, Any]:
    line, _blobs = mail.parse_message(_stored(message_id, when), None, {}, TZ, None, {USER}, account)
    assert line is not None
    return line


@pytest.mark.parametrize(
    ("written", "asking", "expected"),
    [
        # (spelling, account) written; (spelling, account) asking; the holder, or None
        (
            ("<m1@mail.example.org>", USER),
            ("<m1@mail.example.org>", USER),
            mail.Holder(own=True, account=USER),
        ),
        (
            ("<m1@mail.example.org>", None),
            ("<m1@mail.example.org>", USER),
            mail.Holder(own=False, account=None),
        ),
        (
            ("<m1@mail.example.org>", USER),
            ("<m1@mail.example.org>", None),
            mail.Holder(own=False, account=USER),
        ),
        (
            ("<m1@mail.example.org>", USER),
            ("<m1@Mail.Example.ORG>", USER),
            mail.Holder(own=False, account=USER),
        ),
        (("<m1@Mail.Example.ORG>", USER), ("<m1@mail.example.org>", USER), None),  # the day's lines find it
        (("<m1@mail.example.org>", INES), ("<m1@mail.example.org>", USER), None),  # another mailbox
        (("<M1@mail.example.org>", USER), ("<m1@mail.example.org>", USER), None),  # another message
    ],
)
def test_whose_line_holds_a_message_by_the_keys_alone(
    lb: Logbook, written: tuple[str, str | None], asking: tuple[str, str | None], expected: mail.Holder | None
) -> None:
    lb.append_many([_draft(*written)])
    spelled, account = asking
    q = mail.ask(mail.first_id(spelled), account)
    assert q is not None
    assert mail_lookup.Lookup(lb)([q]) == [expected]


def test_the_lines_of_the_day_find_a_spelling_and_a_mailbox_the_keys_cannot_guess(lb: Logbook) -> None:
    """Written as `<m1@Mail.Example.ORG>` from Ines's other mailbox; an import without `--account` finds it
    only once it knows the message's `at`, and a road reading a third mailbox never does."""
    lb.append_many([_draft("<m1@Mail.Example.ORG>", INES)])
    lookup = mail_lookup.Lookup(lb)
    unknown = mail.ask("m1@MAIL.example.org", None)
    assert unknown is not None
    assert lookup([unknown]) == [None], "no key names that spelling under that mailbox"
    assert lookup([replace(unknown, at="2026-03-02T10:15:00Z")]) == [mail.Holder(own=False, account=INES)]
    third = mail.ask("m1@MAIL.example.org", "kari.nordmann@example.org", at="2026-03-02T10:15:00Z")
    assert lookup([third]) == [None], "another mailbox's copy is its own line (RFC 0015 rule 1)"
    far = replace(unknown, at="2026-03-09T10:15:00Z")
    assert lookup([far]) == [None], "only the days around the message are read"


@pytest.mark.parametrize("junk", ["unknown", "<1234>", "(none)"])
def test_an_id_without_an_at_is_never_a_key_across_roads(
    lb: Logbook, gmail_api: Fake, tmp_path: Path, capsys: pytest.CaptureFixture[str], junk: str
) -> None:
    """RFC 5322 has no Message-ID without an `@`: a mailer that writes `unknown` writes it on every
    message. Each road's own key still dedupes it, as before; across roads it is never the key, so one
    message is never taken for another."""
    _run(capsys, "add", "mail", str(_mbox(tmp_path / "all.mbox", [(_stored(junk, T0, subject="One"), T0)])))
    _deliver(
        gmail_api, [(_stored(junk, T0 + timedelta(hours=1), subject="Another"), T0 + timedelta(hours=1))]
    )
    status, out, err = _run(capsys, "sync", "gmail")
    assert status == 0, err
    assert "gmail: 1 new lines of 1 seen" in out and "already in the record from" not in out
    assert [line["payload"]["subject"] for line in lb.lines()] == ["One", "Another"]


def test_a_message_without_a_message_id_on_imap_dedupes_on_the_stores_key_alone(
    lb: Logbook, gmail_api: Fake, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    messages = [(_stored(None, T0, subject="No id"), T0)]
    _deliver(gmail_api, messages)
    assert _run(capsys, "sync", "gmail")[0] == 0 and lb.meta["seq"] == 1
    before = _record(lb)
    with _serving(_imap(messages), monkeypatch) as imap:
        for _ in range(2):
            status, out, err = _run(capsys, "sync", "mail", "--restart")
            assert status == 0, err
            assert "mail: 0 new lines of 1 seen from the beginning (1 already in the record)" in out
            assert "already in the record from" not in out
        assert len([c for c in imap.sent("FETCH") if "BODY.PEEK[]" in c]) == 2, "the body is read each time"
    assert lb.meta["seq"] == 1 and _record(lb) == before
    (line,) = list(lb.lines())
    assert line["payload"]["raw_id"].startswith(f"{USER}:sha256:") and "message_id" not in line["payload"]


def test_a_takeout_with_blank_ids_reimported_over_the_one_line_the_old_key_wrote(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Before this change every `Message-ID: <>` shared the key `<>`: one line for all of them. Now each
    is keyed by its bytes, so a re-import writes one line per message, the first a second copy of the
    message the old line holds (nothing written is touched to avoid it). The old line never trips the
    lookup."""
    messages = [
        (_stored("<>", T0 + timedelta(hours=n), subject=f"Blank {n}"), T0 + timedelta(hours=n))
        for n in range(3)
    ]
    old, _ = mail.parse_message(messages[0][0], None, {}, TZ, None, {USER}, None)
    assert old is not None
    old["payload"].update(raw_id="<>", message_id="<>", thread="<>")  # as the key `<>` wrote it
    assert lb.append_many([old]) == 1
    path = _mbox(tmp_path / "old.mbox", messages)
    status, out, err = _run(capsys, "add", "mail", str(path), "--dry-run")
    assert status == 0 and "mail: 3 lines would be added, 0 already in the record" in out, err
    status, out, err = _run(capsys, "add", "mail", str(path))
    assert status == 0 and "added 3 lines from mail" in out, err
    assert [line["payload"]["subject"] for line in lb.lines()] == ["Blank 0", "Blank 0", "Blank 1", "Blank 2"]


def test_imap_whose_head_and_body_disagree_on_the_message_id_never_drops_or_crashes(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The header pass and the body read may disagree (a server that adds or strips the header): a head
    naming an id the body lacks is fetched and keyed by its bytes; a body whose id the head did not give is
    found once read, among the lines of its days."""
    real, heads = mail_imap._fetch_heads, {1: "ghost@mail.example.org", 2: None}
    monkeypatch.setattr(
        mail_imap,
        "_fetch_heads",
        lambda imap, shown, uids: {u: (heads.get(u, m), s) for u, (m, s) in real(imap, shown, uids).items()},
    )
    t1 = T0 + timedelta(hours=1)
    messages = [
        (_stored(None, T0, subject="Head only"), T0),
        (_stored("<real@mail.example.org>", t1, subject="Body only"), t1),
    ]
    with _serving(_imap(messages), monkeypatch):
        status, out, err = _run(capsys, "sync", "mail")
        assert status == 0 and "mail: 2 new lines of 2 seen" in out, err
        status, out, err = _run(capsys, "sync", "mail", "--restart")
        assert status == 0 and "(2 already in the record)" in out, err
    first, second = (line["payload"] for line in lb.lines())
    assert first["raw_id"].startswith(f"{USER}:sha256:") and "message_id" not in first
    assert second["raw_id"] == f"{USER}:real@mail.example.org"
    other = Logbook.init(tmp_path / "other", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(other.root))
    other.set_owner_emails([USER])
    assert _run(capsys, "add", "mail", str(_mbox(tmp_path / "t.mbox", messages[1:])))[0] == 0
    assert other.meta["seq"] == 1
    with _serving(_imap(messages), monkeypatch) as imap:
        status, out, err = _run(capsys, "sync", "mail")
        assert status == 0, err
        assert "mail: 1 new lines of 1 seen" in out
        assert "  1 already in the record from mail (an import without --account)" in out.splitlines()
        assert len([c for c in imap.sent("FETCH") if "BODY.PEEK[]" in c]) == 1, "one fetch, both bodies"
    assert [line["payload"]["subject"] for line in Logbook(other.root).lines()] == ["Body only", "Head only"]


def test_sealed_lines_answer_by_blinded_key_and_by_the_opened_lines_of_the_day(
    lb: Logbook,
    gmail_api: Fake,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """In a record that seals, an export spelled `Mail.Example.ORG` is found by neither key the server's
    spelling gives, only among the opened lines of its days; without the identity nothing is read by id,
    nothing is skipped, and nothing is written (the store asks for the identity)."""
    pairs = [sealing.generate_identity() for _ in range(2)]
    meta = lb.meta
    meta["recipients"] = [recipient for _, recipient in pairs]
    lb._save_meta(meta)
    identity = tmp_path / "keys" / "owner.txt"
    sealing.write_identity_file(identity, pairs[0][0], "test")
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(identity))
    odd = _week(lambda mid: mid.replace("mail.example.org", "Mail.Example.ORG"))
    assert _run(capsys, "add", "mail", str(_mbox(tmp_path / "a.mbox", odd)), "--account", USER)[0] == 0
    before = _record(lb)
    with _serving(_imap(_week()), monkeypatch) as imap:
        status, out, err = _run(capsys, "sync", "mail")
    assert status == 0 and "mail: 0 new lines of 0 seen" in out, err
    assert f"  3 already in the record from mail ({USER})" in out.splitlines()
    assert [c for c in imap.sent("FETCH") if "BODY.PEEK[]" in c], "no key matched: the day's lines did"
    _deliver(gmail_api, _week())
    status, out, err = _run(capsys, "sync", "gmail")
    assert status == 0 and "gmail: 0 new lines of 0 seen" in out and _record(lb) == before, err
    monkeypatch.delenv("LOGBOOK_IDENTITY_FILE")
    status, out, err = _run(capsys, "add", "mail", str(_mbox(tmp_path / "b.mbox", _week())), "--dry-run")
    assert status == 0 and "3 lines would be added" in out and "already in the record from" not in out, err
    status, out, err = _run(capsys, "add", "mail", str(tmp_path / "b.mbox"))
    assert status == 2 and "needs the identity" in err and _record(lb) == before


def test_the_cursor_resumes_past_a_held_message_without_losing_or_repeating_one(
    lb: Logbook,
    gmail_api: Fake,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from logbook.contrib import inbox

    monkeypatch.setattr(mail, "LOOKUP_BATCH", 2)
    week = _week()
    _deliver(gmail_api, [week[1]])
    assert _run(capsys, "sync", "gmail")[0] == 0
    t4 = T0 + timedelta(hours=36)
    path = _mbox(tmp_path / "all.mbox", [*week, (_stored("<m4@mail.example.org>", t4, subject="Fender"), t4)])
    cursor = inbox.Cursor(lb.root, "mail", {})
    drafts = mail.run(path, timezone=TZ, counts={}, held=mail_lookup.Lookup(lb), cursor=cursor)
    lb.append_many([next(drafts)])
    cursor.commit(1)
    drafts.close()  # stopped after the first line: m2 is held, m3 and m4 not read yet
    again, counts = inbox.Cursor(lb.root, "mail", {}), {}
    rest = list(mail.run(path, timezone=TZ, counts=counts, held=mail_lookup.Lookup(lb), cursor=again))
    assert again.resumed
    assert [d["payload"]["message_id"] for d in rest] == ["m3@mail.example.org", "m4@mail.example.org"]
    assert counts[f"{mail.HELD}mail ({USER})"] == 1
    lb.append_many(rest)
    again.commit(2)
    assert sorted(line["payload"]["message_id"] for line in lb.lines()) == [
        f"m{n}@mail.example.org" for n in (1, 2, 3, 4)
    ]
    last = inbox.Cursor(lb.root, "mail", {})
    assert list(mail.run(path, timezone=TZ, counts={}, held=mail_lookup.Lookup(lb), cursor=last)) == []


def test_a_retracted_line_and_a_repeated_id_are_counted_never_dropped_silently(
    lb: Logbook, gmail_api: Fake, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A retracted line holds its message as the store holds its key: nothing is written again. A message
    repeated in one export is asked about twice and written once, the store counting the repeat."""
    _deliver(gmail_api, _week()[:1])
    assert _run(capsys, "sync", "gmail")[0] == 0
    lb.retract(1, "wrong")
    before = _record(lb)
    status, out, _err = _run(capsys, "add", "mail", str(_mbox(tmp_path / "a.mbox", _week()[:1])))
    assert status == 0 and f"  1 already in the record from mail ({USER})" in out.splitlines()
    assert _record(lb) == before
    twice = [
        (_stored("<x@mail.example.org>", T0, subject="One"), T0),
        (_stored("<x@mail.example.org>", T0, subject="Two"), T0),
    ]
    status, out, _err = _run(capsys, "add", "mail", str(_mbox(tmp_path / "b.mbox", twice)))
    assert "added 1 lines from mail" in out and "1 already in the record (same source and raw_id)" in out


def test_a_held_messages_attachments_are_never_stored(tmp_path: Path) -> None:
    jpeg = base64.encodebytes(b"\xff\xd8" + bytes(range(64))).decode("ascii").replace("\n", "\r\n")
    with_file = (
        f"Message-ID: <{{}}>\r\nDate: Mon, 02 Mar 2026 11:15:00 +0100\r\nFrom: Ola Nordmann <{OLA}>\r\n"
        'Content-Type: multipart/mixed; boundary="b1"\r\n\r\n--b1\r\nContent-Type: text/plain\r\n\r\nHei.\r\n'
        '--b1\r\nContent-Type: image/jpeg; name="berth.jpg"\r\nContent-Disposition: attachment; '
        'filename="berth.jpg"\r\nContent-Transfer-Encoding: base64\r\n\r\n' + jpeg + "--b1--\r\n"
    )
    messages = [
        (with_file.format(mid).encode(), T0) for mid in ("kept@mail.example.org", "held@mail.example.org")
    ]
    stored: list[bytes] = []
    asking = Asking({"held@mail.example.org": mail.Holder(own=False, account=None)})
    path = _mbox(tmp_path / "all.mbox", messages)
    lines = list(mail.run(path, timezone=TZ, attachments=True, store=stored.append, held=asking))
    assert [line["payload"]["message_id"] for line in lines] == ["kept@mail.example.org"]
    assert len(stored) == 1, "only the written line's attachment reaches the store"


@pytest.mark.parametrize("hollow", ["<@>", "<a@>", "<@mail.example.org>"])
def test_an_id_with_nothing_on_one_side_of_the_at_is_never_a_key_across_roads(hollow: str) -> None:
    assert mail.ask(mail.first_id(hollow), USER) is None
    assert mail.ask(mail.first_id("<a@b>"), USER) is not None


def test_the_count_key_is_the_one_the_report_reads() -> None:
    from logbook.commands import skips

    assert skips.HELD == mail.HELD


def test_each_day_is_read_once_per_run_whatever_the_order_and_what_is_kept_is_bounded(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An export out of day order (a second mailbox's, every key missing) reads each day's lines once;
    what the run keeps of them is ids and mailboxes, up to IDS_KEPT, the days asked longest ago let go."""
    from logbook.core.index import Index

    days = [T0 + timedelta(days=n) for n in range(0, 300, 3)]  # more days than any small cache holds
    lb.append_many([_draft(f"<d{n}@mail.example.org>", INES, when) for n, when in enumerate(days)])
    read: list[str] = []
    of_source = Index.of_source

    def counted(self: Index, kind: str, source: str, first: str, last: str, *rest: Any) -> Any:
        read.append(first)
        return of_source(self, kind, source, first, last, *rest)

    monkeypatch.setattr(Index, "of_source", counted)
    lookup = mail_lookup.Lookup(lb)
    order = list(enumerate(days))
    random.Random(7).shuffle(order)
    for _round in range(3):
        for n, when in order:
            q = mail.ask(f"d{n}@MAIL.example.org", USER, at=when.strftime("%Y-%m-%dT%H:%M:%SZ"))
            assert q is not None and lookup([q]) == [None], "Ines's other mailbox's copy is its own"
    assert len(read) == len(set(read)), "no day read twice"
    monkeypatch.setattr(mail_lookup, "IDS_KEPT", 2)
    small = mail_lookup.Lookup(lb)
    for n, when in order:
        q = mail.ask(f"d{n}@mail.example.org", None, at=when.strftime("%Y-%m-%dT%H:%M:%SZ"))
        assert q is not None and small([q]) == [mail.Holder(own=False, account=INES)]
        assert small.kept <= 2 or len(small.days) == 1
