"""Two MAY keys under `extra` on a mail/v1 line (RFC 0015, amendment of 2026-10-20): Gmail's inbox tab
(`extra.gmail_category`) and the list headers (`extra.list`), never their links. On every road: an mbox
(Takeout), IMAP (`sync mail`, the fake server of `tests/imap_server.py`) and the Gmail API (`sync gmail`,
the fake of `tests/google_fake.py`). Synthetic mail only: Ines and Ola Nordmann of Oslo, who do not
exist, and a boat club at example.org."""

from __future__ import annotations

import hashlib
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

ROOT = Path(__file__).resolve().parents[1]
TAKEOUT = ROOT / "tests" / "fixtures" / "mail" / "takeout.mbox"
INES = "ines.nordmann@example.org"
OLA = "ola@example.org"
CLUB = "news@boatclub.example.org"
T0 = datetime(2026, 3, 2, 10, 15, tzinfo=UTC)
READER = "reader-ines-nordmann"  # what an unsubscribe link carries to name its reader: never in a line
LIST_ID = "Boat club news <news.boatclub.example.org>"
NEWSLETTER_HEADERS = (
    f"List-Id: {LIST_ID}\r\n"
    f"List-Unsubscribe: <https://boatclub.example.org/u/{READER}>,\r\n"
    f" <mailto:leave+{READER}@boatclub.example.org?subject=unsubscribe>\r\n"
    "List-Unsubscribe-Post: List-Unsubscribe=One-Click\r\n"
)
ODD_CASING = (
    "LIST-ID:    <crew.example.org>   \r\n"
    f"list-UNSUBSCRIBE: <mailto:crew-leave+{READER}@example.org>\r\n"
    "LiSt-UnSuBsCrIbE-pOsT: List-Unsubscribe=One-Click\r\n"
)
MALFORMED = f"List-Unsubscribe: please write to crew-leave {READER} at example.org\r\n"


def _raw(message_id: str, when: datetime, sender: str, subject: str, headers: str = "") -> bytes:
    return (
        f"Message-ID: <{message_id}>\r\nDate: {when.strftime('%a, %d %b %Y %H:%M:%S %z')}\r\n"
        f"From: {sender}\r\nTo: Ines Nordmann <{INES}>\r\nSubject: {subject}\r\n{headers}"
        'Content-Type: text/plain; charset="utf-8"\r\n\r\nHei.\r\n'
    ).encode()


NEWSLETTER = _raw(
    "news-1@boatclub.example.org", T0, f"Boat club <{CLUB}>", "Spring launch", NEWSLETTER_HEADERS
)
PERSONAL = _raw("p-1@mail.example.org", T0 + timedelta(hours=1), f"Ola Nordmann <{OLA}>", "Mooring")
ODD = _raw("crew-1@example.org", T0 + timedelta(hours=2), f"Ola Nordmann <{OLA}>", "Crew list", ODD_CASING)
BROKEN = _raw("crew-2@example.org", T0 + timedelta(hours=3), f"Ola Nordmann <{OLA}>", "Crew list", MALFORMED)
ONE_CLICK_LIST = {"unsubscribe": True, "one_click": True, "id": "news.boatclub.example.org"}  # the id alone


def _no_links(line: dict[str, Any]) -> None:
    """Nothing of an unsubscribe link anywhere in the written line, serialized."""
    text = json.dumps(line, ensure_ascii=False)
    for leak in (READER, "https://", "mailto", "boatclub.example.org/u", "One-Click", "leave+"):
        assert leak not in text, leak


def _extra(line: dict[str, Any]) -> dict[str, Any]:
    return dict(line["payload"].get("extra") or {})


def _without_new_keys(line: dict[str, Any]) -> dict[str, Any]:
    """The line as the adapters wrote it before the amendment: the two keys off, `extra` off when empty."""
    out = json.loads(json.dumps(line))
    extra = out["payload"].get("extra")
    if isinstance(extra, dict):
        extra.pop("gmail_category", None)
        extra.pop("list", None)
        if not extra:
            del out["payload"]["extra"]
    return dict(out)


# -- the mbox (Takeout) ----------------------------------------------------------------------------------


def _mbox(tmp_path: Path) -> Path:
    path = tmp_path / "All mail Including Spam and Trash.mbox"
    with path.open("wb") as fh:
        for raw, labels in (
            (NEWSLETTER, "Inbox,Category Promotions"),
            (PERSONAL, "Inbox,Important,Category Personal"),
            (ODD, "Inbox,category updates"),
            (BROKEN, "Inbox"),
        ):
            fh.write(b"From 1795123456789012345@xxx Mon Mar 02 10:15:00 +0000 2026\r\n")
            fh.write(f"X-Gmail-Labels: {labels}\r\n".encode() + raw + b"\r\n")
    return path


def _mbox_lines(tmp_path: Path, counts: dict[str, int] | None = None) -> dict[str, dict[str, Any]]:
    lines = mail.run(_mbox(tmp_path), timezone="Europe/Oslo", account=INES, counts=counts)
    return {line["payload"]["message_id"]: line for line in lines}


def test_mbox_a_newsletter_keeps_its_tab_and_that_it_is_a_list_never_the_links(tmp_path: Path) -> None:
    line = _mbox_lines(tmp_path)["news-1@boatclub.example.org"]
    assert _extra(line)["gmail_category"] == "promotions"
    assert _extra(line)["list"] == ONE_CLICK_LIST
    assert "list" not in line["payload"] and "gmail_category" not in line["payload"], "under extra only"
    _no_links(line)


def test_mbox_a_personal_mail_has_no_list_and_its_tab_is_primary(tmp_path: Path) -> None:
    line = _mbox_lines(tmp_path)["p-1@mail.example.org"]
    assert "list" not in _extra(line)
    assert _extra(line)["gmail_category"] == "primary", "Takeout spells the Primary tab `Category Personal`"


def test_mbox_list_headers_are_read_whatever_their_casing_and_the_id_is_trimmed(tmp_path: Path) -> None:
    line = _mbox_lines(tmp_path)["crew-1@example.org"]
    assert _extra(line)["list"] == {"unsubscribe": True, "one_click": True, "id": "crew.example.org"}
    assert _extra(line)["gmail_category"] == "updates", "a label is matched case-insensitively"
    _no_links(line)


def test_mbox_a_malformed_list_header_is_present_by_its_name_and_counted(tmp_path: Path) -> None:
    counts: dict[str, int] = {}
    line = _mbox_lines(tmp_path, counts)["crew-2@example.org"]
    assert _extra(line)["list"] == {"unsubscribe": True}
    assert "gmail_category" not in _extra(line), "no category label, no tab"
    assert counts.get("skipped_list_header") == 1, "only the one header that would not parse"
    _no_links(line)


def test_mbox_labels_and_raw_id_are_what_they_were_for_the_same_input(tmp_path: Path) -> None:
    lines = _mbox_lines(tmp_path)
    assert lines["news-1@boatclub.example.org"]["payload"]["labels"] == ["Inbox", "Category Promotions"]
    assert lines["p-1@mail.example.org"]["payload"]["labels"] == ["Inbox", "Important", "Category Personal"]
    assert lines["crew-1@example.org"]["payload"]["labels"] == ["Inbox", "category updates"]
    assert lines["news-1@boatclub.example.org"]["payload"]["raw_id"] == f"{INES}:news-1@boatclub.example.org"
    assert lines["crew-1@example.org"]["payload"]["raw_id"] == f"{INES}:crew-1@example.org"


def test_the_takeout_fixture_is_byte_identical_to_before_but_for_the_two_keys(tmp_path: Path) -> None:
    """The fixture's six lines, with the two new keys taken off, digest as they did before the
    amendment (`labels`, `raw_id` and every other field untouched); two of them gain a tab. Read from
    the fixture's bytes with LF endings, as the repository stores them: a Windows checkout turns them
    into CRLF, which changes `size` and the body and so the digest."""
    copy = tmp_path / "takeout.mbox"
    copy.write_bytes(TAKEOUT.read_bytes().replace(b"\r\n", b"\n"))
    lines = list(mail.run(copy, timezone="Europe/Oslo", account="kari.nordmann@example.org"))
    before = [_without_new_keys(line) for line in lines]
    digest = hashlib.sha256(json.dumps(before, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    assert digest == "d47162e685b850a25aa7940eb00cadf3fd617505b4daf9c1056b294f9100b0de"
    tabs = {line["payload"]["raw_id"].split(":", 1)[1]: _extra(line).get("gmail_category") for line in lines}
    assert tabs["a1b2c3@mail.example.org"] == "primary"
    assert tabs["news-2026-03-03@news.example.org"] == "promotions"
    assert [tab for tab in tabs.values() if tab is not None] == ["primary", "promotions"]


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    lb = Logbook.init(root, "Europe/Oslo")
    lb.set_owner_emails([INES])
    return lb


def test_mbox_a_reimport_appends_nothing_and_rewrites_nothing(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _mbox(tmp_path)
    capsys.readouterr()
    cli.main(["add", "mail", str(path), "--account", INES])
    assert (
        "skipped 1 list headers that would not parse (each kept by its name alone)" in capsys.readouterr().out
    )
    written = [json.dumps(line, sort_keys=True) for line in lb.lines()]
    assert len(written) == 4
    cli.main(["add", "mail", str(path), "--account", INES, "--restart"])
    assert [json.dumps(line, sort_keys=True) for line in lb.lines()] == written
    capsys.readouterr()


# -- IMAP (`sync mail`) ----------------------------------------------------------------------------------


def _imap_folder() -> Folder:
    """The four messages in All Mail; the newsletter's bytes carry a Takeout header too (a message once
    uploaded from an export), which the live road must not read as a tab."""
    raws = (b"X-Gmail-Labels: Inbox,Category Promotions\r\n" + NEWSLETTER, PERSONAL, ODD, BROKEN)
    messages = {}
    for uid, raw in enumerate(raws, start=1):
        when = T0 + timedelta(hours=uid)
        messages[uid] = Message(
            uid, raw, internaldate(when), labels=("\\Inbox",), thrid=1795123456789012300 + uid
        )
    return Folder("[Gmail]/All Mail", 1234, messages, attributes=("\\All",))


def _imap_sync(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], gmail_ext: bool
):
    server = FakeImap([_imap_folder()], user=INES, gmail=gmail_ext)
    port = server.start()
    monkeypatch.setenv("LOGBOOK_IMAP_HOST", "imap.example.org")
    monkeypatch.setenv("LOGBOOK_IMAP_USER", INES)
    monkeypatch.setenv("LOGBOOK_IMAP_PASSWORD", server.password)
    monkeypatch.setattr(
        mail_imap, "open_connection", lambda config: imaplib.IMAP4("127.0.0.1", port, timeout=10)
    )
    try:
        cli.main(["sync", "mail"])
    finally:
        server.stop()
    out = capsys.readouterr()
    return {line["payload"]["message_id"]: line for line in lb.lines() if line["source"] == "mail"}, out


@pytest.mark.parametrize("gmail_ext", [True, False], ids=["X-GM-EXT-1", "plain IMAP"])
def test_imap_keeps_the_list_headers_and_writes_no_tab(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], gmail_ext: bool
) -> None:
    lines, out = _imap_sync(lb, monkeypatch, capsys, gmail_ext)
    assert len(lines) == 4, out.err
    assert _extra(lines["news-1@boatclub.example.org"])["list"] == ONE_CLICK_LIST
    assert "list" not in _extra(lines["p-1@mail.example.org"])
    assert _extra(lines["crew-1@example.org"])["list"] == {
        "unsubscribe": True,
        "one_click": True,
        "id": "crew.example.org",
    }
    assert _extra(lines["crew-2@example.org"])["list"] == {"unsubscribe": True}
    for line in lines.values():
        assert "gmail_category" not in _extra(line), "X-GM-LABELS carries no tab; nothing is guessed"
        _no_links(line)
    if gmail_ext:
        assert lines["news-1@boatclub.example.org"]["payload"]["labels"] == ["Inbox"]
        assert (
            lines["news-1@boatclub.example.org"]["payload"]["raw_id"] == f"{INES}:news-1@boatclub.example.org"
        )


# -- the Gmail API (`sync gmail`) ------------------------------------------------------------------------


@pytest.fixture
def google(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_network: list[str]) -> Iterator[Fake]:
    key = private_key()
    fake = Fake(key)
    fake.labels = [
        {"id": "INBOX", "name": "INBOX", "type": "system"},
        {"id": "IMPORTANT", "name": "IMPORTANT", "type": "system"},
        {"id": "CATEGORY_PROMOTIONS", "name": "CATEGORY_PROMOTIONS", "type": "system"},
        {"id": "CATEGORY_PERSONAL", "name": "CATEGORY_PERSONAL", "type": "system"},
        {"id": "CATEGORY_UPDATES", "name": "CATEGORY_UPDATES", "type": "system"},
    ]
    fake.deliver(NEWSLETTER, T0, ("INBOX", "CATEGORY_PROMOTIONS", "UNREAD"))
    fake.deliver(PERSONAL, T0 + timedelta(hours=1), ("INBOX", "IMPORTANT", "CATEGORY_PERSONAL"))
    fake.deliver(ODD, T0 + timedelta(hours=2), ("INBOX", "CATEGORY_UPDATES"))
    fake.deliver(BROKEN, T0 + timedelta(hours=3), ("INBOX",))
    monkeypatch.setattr(service_account, "send", fake)
    monkeypatch.setattr(service_account, "sleep", lambda _s: None)
    monkeypatch.setenv(service_account.KEY_ENV, str(write_key(tmp_path / "google-sa.json", key)))
    monkeypatch.setenv(service_account.USER_ENV, USER)  # the fake's own user
    yield fake
    assert no_network == [], "the fake is the only way out"


def _gmail_lines(counts: dict[str, int] | None = None) -> dict[str, dict[str, Any]]:
    config = gmail.configure(os.environ)
    assert config is not None
    drafts = gmail.pull(config, counts=counts, timezone="Europe/Oslo", owner_emails=[USER])
    return {line["payload"]["message_id"]: line for line in drafts}


def test_gmail_api_records_the_tab_its_category_label_names_and_keeps_it_out_of_labels(google: Fake) -> None:
    lines = _gmail_lines()
    assert _extra(lines["news-1@boatclub.example.org"])["gmail_category"] == "promotions"
    assert _extra(lines["p-1@mail.example.org"])["gmail_category"] == "primary"
    assert _extra(lines["crew-1@example.org"])["gmail_category"] == "updates"
    assert "gmail_category" not in _extra(lines["crew-2@example.org"]), "no category label, no tab"
    assert lines["news-1@boatclub.example.org"]["payload"]["labels"] == ["Inbox"], "no CATEGORY_*, no UNREAD"
    assert lines["p-1@mail.example.org"]["payload"]["labels"] == ["Inbox", "Important"]
    assert lines["news-1@boatclub.example.org"]["payload"]["raw_id"] == f"{USER}:news-1@boatclub.example.org"


def test_gmail_api_keeps_the_list_headers_never_the_links(google: Fake) -> None:
    counts: dict[str, int] = {}
    lines = _gmail_lines(counts)
    assert _extra(lines["news-1@boatclub.example.org"])["list"] == ONE_CLICK_LIST
    assert "list" not in _extra(lines["p-1@mail.example.org"])
    assert _extra(lines["crew-1@example.org"])["list"]["id"] == "crew.example.org"
    assert _extra(lines["crew-2@example.org"])["list"] == {"unsubscribe": True}
    assert counts.get("skipped_list_header") == 1
    for line in lines.values():
        _no_links(line)
    metadata = [q for _m, _p, q in google.requests if q.get("format") == "metadata"]
    assert metadata and all(q["metadataHeaders"] == "Message-ID" for q in metadata), "no new request"


def test_the_three_roads_differ_only_in_the_tab(google: Fake, tmp_path: Path) -> None:
    """The newsletter through the API and through the parser as IMAP calls it: the same line but for
    the tab, which only the API (and a Takeout) can say."""
    api = _gmail_lines()["news-1@boatclub.example.org"]
    parsed, _blobs = mail.parse_message(
        NEWSLETTER, T0, {}, "Europe/Oslo", None, {USER}, USER, digest_attachments=True,
        fallback_name="internaldate",
    )  # fmt: skip
    assert parsed is not None
    mail.gmail_fields(parsed["payload"], ["Inbox"], api["payload"]["extra"]["gmail_thread_id"])
    assert "gmail_category" not in _extra(parsed)
    assert _without_new_keys(api) == _without_new_keys(parsed)
    assert _extra(api)["list"] == _extra(parsed)["list"]
