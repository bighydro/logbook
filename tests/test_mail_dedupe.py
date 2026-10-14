"""One email is one line, whichever road brought it: the Takeout mbox (`add mail`), IMAP (`sync mail`) or
the Gmail API (`sync gmail`). Every road reads the message's own Message-ID; the lines carry it normalised
(`payload.message_id`), and each road skips a message the record already holds by it, from any of the
three, before it writes (RFC 0015, amendment of 2026-10-14).

Synthetic mail only: Ines, Ola and Kari Nordmann of Oslo, who do not exist, at example.org."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook.contrib.adapters import mail

TZ = "Europe/Oslo"
INES = "ines.nordmann@example.org"
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
