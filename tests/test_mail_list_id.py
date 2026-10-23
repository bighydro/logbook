"""`extra.list.id` is the list-id alone (RFC 2919: the dot-atom inside the angle brackets), never the
phrase, a link or an address the `List-Id` header carries (RFC 0015, amendment of 2026-10-20). On every
road: an mbox (Takeout), IMAP (`sync mail`, the fake server of `tests/imap_server.py`) and the Gmail API
(`sync gmail`, the fake of `tests/google_fake.py`). Synthetic mail only: Ines and Ola Nordmann of Oslo,
who do not exist, at example.org."""

from __future__ import annotations

import imaplib
import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from google_fake import USER, Fake, private_key, write_key
from imap_server import FakeImap, Folder, Message, internaldate

from logbook import cli
from logbook.contrib.adapters import gmail, mail, mail_imap, service_account
from logbook.core.store import Logbook

INES = "ines.nordmann@example.org"
T0 = datetime(2026, 3, 2, 10, 15, tzinfo=UTC)
UNSUBSCRIBE = (
    "List-Unsubscribe: <mailto:leave-ines@letters.example.org>\r\n"
    "List-Unsubscribe-Post: List-Unsubscribe=One-Click\r\n"
)
# (Message-ID, the List-Id header's value, the id the line keeps or None)
CASES = (
    ("phrase@letters.example.org", "Ines's letters <letters.example.org>", "letters.example.org"),
    ("bare@letters.example.org", "letters.example.org", "letters.example.org"),
    ("url@letters.example.org", "<https://letters.example.org/x>", None),
    ("mailto@letters.example.org", "<mailto:list@example.org>", None),
    ("address@letters.example.org", "list@example.org", None),
    ("empty@letters.example.org", "", None),
)
NOT_PARSED = sum(1 for _m, _v, kept in CASES if kept is None)
LEAKS = ("http", "mailto:", "list@example.org", "letters.example.org/x", "leave-ines", "Ines's letters")


def _raw(message_id: str, list_id: str, n: int) -> bytes:
    when = T0 + timedelta(hours=n)
    return (
        f"Message-ID: <{message_id}>\r\nDate: {when.strftime('%a, %d %b %Y %H:%M:%S %z')}\r\n"
        f"From: Ola Nordmann <ola@example.org>\r\nTo: Ines Nordmann <{INES}>\r\n"
        f"Subject: Letter {n}\r\nList-Id: {list_id}\r\n{UNSUBSCRIBE}"
        'Content-Type: text/plain; charset="utf-8"\r\n\r\nHei.\r\n'
    ).encode()


RAWS = [_raw(message_id, value, n) for n, (message_id, value, _kept) in enumerate(CASES, start=1)]


def _check(lines: dict[str, dict[str, Any]]) -> None:
    """Each line keeps the id alone or none, the unsubscribe facts as they were, and nothing of a link
    or an address from the list headers anywhere in the serialized line."""
    assert set(lines) == {message_id for message_id, _v, _k in CASES}
    for message_id, _value, kept in CASES:
        line = lines[message_id]
        listed = line["payload"]["extra"]["list"]
        expected = {"unsubscribe": True, "one_click": True, **({"id": kept} if kept else {})}
        assert listed == expected, message_id
        text = json.dumps(line, ensure_ascii=False)
        for leak in LEAKS:
            assert leak not in text, (message_id, leak)
        assert "@" not in json.dumps(listed), message_id


# -- the mbox (Takeout) ----------------------------------------------------------------------------------


def test_mbox_keeps_the_list_id_alone_and_counts_the_ones_that_do_not_parse(tmp_path: Path) -> None:
    path = tmp_path / "letters.mbox"
    with path.open("wb") as fh:
        for raw in RAWS:
            fh.write(b"From 1795123456789012345@xxx Mon Mar 02 10:15:00 +0000 2026\r\n")
            fh.write(b"X-Gmail-Labels: Inbox,Category Updates\r\n" + raw + b"\r\n")
    counts: dict[str, int] = {}
    lines = mail.run(path, timezone="Europe/Oslo", account=INES, counts=counts)
    _check({line["payload"]["message_id"]: line for line in lines})
    assert counts.get("skipped_list_header") == NOT_PARSED


def test_the_parser_never_keeps_a_phrase_link_or_address_however_the_id_is_dressed() -> None:
    """The shapes a List-Id may take that are not one RFC 2919 id: the line keeps no `id` for each."""
    for value in (
        "<letters.example.org> <other.example.org>",  # two ids: neither is the one
        "<letters.example.org/archive>",
        "<letters example.org>",
        "<letters.example.org?reader=ines>",
        "<ines@letters.example.org>",
        "<lettersexampleorg>",  # no dot: no namespace
        "https://letters.example.org",
        "letters.example.org <>",
        "=?utf-8?q?Ines=27s_letters?= <https:letters.example.org>",
    ):
        counts: dict[str, int] = {}
        line, _blobs = mail.parse_message(
            _raw("odd@letters.example.org", value, 1), None, counts, "UTC", None, set(), None
        )
        assert line is not None
        assert line["payload"]["extra"]["list"] == {"unsubscribe": True, "one_click": True}, value
        assert counts == {"skipped_list_header": 1}, value


# -- IMAP (`sync mail`) ----------------------------------------------------------------------------------


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    lb = Logbook.init(root, "Europe/Oslo")
    lb.set_owner_emails([INES])
    return lb


def test_imap_keeps_the_list_id_alone_and_counts_the_ones_that_do_not_parse(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    messages = {
        uid: Message(uid, raw, internaldate(T0 + timedelta(hours=uid)), labels=("\\Inbox",), thrid=uid)
        for uid, raw in enumerate(RAWS, start=1)
    }
    server = FakeImap([Folder("[Gmail]/All Mail", 1234, messages, attributes=("\\All",))], user=INES)
    port = server.start()
    monkeypatch.setenv("LOGBOOK_IMAP_HOST", "imap.example.org")
    monkeypatch.setenv("LOGBOOK_IMAP_USER", INES)
    monkeypatch.setenv("LOGBOOK_IMAP_PASSWORD", server.password)
    monkeypatch.setattr(
        mail_imap, "open_connection", lambda config: imaplib.IMAP4("127.0.0.1", port, timeout=10)
    )
    capsys.readouterr()
    try:
        cli.main(["sync", "mail"])
    finally:
        server.stop()
    out = capsys.readouterr()
    _check({line["payload"]["message_id"]: line for line in lb.lines() if line["source"] == "mail"})
    said = out.out + out.err
    assert f"skipped {NOT_PARSED} list headers that would not parse (each kept by its name alone)" in said


# -- the Gmail API (`sync gmail`) ------------------------------------------------------------------------


@pytest.fixture
def google(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_network: list[str]) -> Iterator[Fake]:
    key = private_key()
    fake = Fake(key)
    fake.labels = [{"id": "INBOX", "name": "INBOX", "type": "system"}]
    for n, raw in enumerate(RAWS, start=1):
        fake.deliver(raw, T0 + timedelta(hours=n), ("INBOX", "CATEGORY_UPDATES"))
    monkeypatch.setattr(service_account, "send", fake)
    monkeypatch.setattr(service_account, "sleep", lambda _s: None)
    monkeypatch.setenv(service_account.KEY_ENV, str(write_key(tmp_path / "google-sa.json", key)))
    monkeypatch.setenv(service_account.USER_ENV, USER)  # the fake's own user
    yield fake
    assert no_network == [], "the fake is the only way out"


def test_gmail_api_keeps_the_list_id_alone_and_counts_the_ones_that_do_not_parse(google: Fake) -> None:
    config = gmail.configure(os.environ)
    assert config is not None
    counts: dict[str, int] = {}
    drafts = gmail.pull(config, counts=counts, timezone="Europe/Oslo", owner_emails=[USER])
    _check({line["payload"]["message_id"]: line for line in drafts})
    assert counts.get("skipped_list_header") == NOT_PARSED
