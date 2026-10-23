"""`logbook sync gmail`: the owner's mailbox over the Gmail API, read-only (`gmail.readonly`), on the one
Google service-account key, through the mbox adapter's own parser: the line the IMAP source writes, with
the same dedupe key (`<account>:<Message-ID>`), so a mailbox synced by IMAP yesterday and by this source
today writes nothing twice.

Against the in-process fake of `tests/google_fake.py` (and, for the crossing with IMAP, the fake server of
`tests/imap_server.py` on the loopback interface). Synthetic mail only: Ines and Ola Nordmann of Oslo, who
do not exist, at example.org."""

from __future__ import annotations

import base64
import imaplib
import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from google_fake import DRIVE_SCOPE, GMAIL_SCOPE, USER, Fake, private_key, write_key
from imap_server import FakeImap, Folder, Message, internaldate

from logbook import cli
from logbook.contrib import adapters, doctor
from logbook.contrib.adapters import gmail, mail, mail_imap, service_account
from logbook.core.store import Logbook

KEY_ENV, USER_ENV = service_account.KEY_ENV, service_account.USER_ENV
OLA = "ola@example.org"
T0 = datetime(2026, 3, 2, 10, 15, tzinfo=UTC)
MESSAGES = "gmail.googleapis.com/gmail/v1/users/me/messages"
HISTORY = "gmail.googleapis.com/gmail/v1/users/me/history"
JPEG = b"\xff\xd8" + bytes(range(256)) * 4
LABELS = [
    {"id": "INBOX", "name": "INBOX", "type": "system"},
    {"id": "SENT", "name": "SENT", "type": "system"},
    {"id": "IMPORTANT", "name": "IMPORTANT", "type": "system"},
    {"id": "STARRED", "name": "STARRED", "type": "system"},
    {"id": "UNREAD", "name": "UNREAD", "type": "system"},
    {"id": "DRAFT", "name": "DRAFT", "type": "system"},
    {"id": "SPAM", "name": "SPAM", "type": "system"},
    {"id": "CATEGORY_UPDATES", "name": "CATEGORY_UPDATES", "type": "system"},
    {"id": "Label_7", "name": "Harbour", "type": "user"},
    {"id": "Label_8", "name": "Boat/Engine", "type": "user"},
]


def _raw(
    message_id: str,
    when: datetime,
    sent: bool = False,
    subject: str = "Mooring",
    body: str = "Hei.",
    extra: str = "",
    attachment: bytes | None = None,
) -> bytes:
    """A message as a mailbox stores it, CRLF and all."""
    sender, to = (f"Ines Nordmann <{USER}>", f"Ola Nordmann <{OLA}>")[:: -1 if not sent else 1]
    head = (
        f"Message-ID: <{message_id}>\r\nDate: {when.strftime('%a, %d %b %Y %H:%M:%S %z')}\r\n"
        f"From: {sender}\r\nTo: {to}\r\nSubject: {subject}\r\n{extra}"
    )
    if attachment is None:
        return (head + 'Content-Type: text/plain; charset="utf-8"\r\n\r\n' + body + "\r\n").encode("utf-8")
    b64 = base64.encodebytes(attachment).decode("ascii").replace("\n", "\r\n")
    return (
        head + 'Content-Type: multipart/mixed; boundary="b1"\r\n\r\n--b1\r\n'
        'Content-Type: text/plain; charset="utf-8"\r\n\r\n' + body + "\r\n--b1\r\n"
        'Content-Type: image/jpeg; name="berth.jpg"\r\n'
        'Content-Disposition: attachment; filename="berth.jpg"\r\n'
        "Content-Transfer-Encoding: base64\r\n\r\n" + b64 + "--b1--\r\n"
    ).encode("utf-8")


ROOT = 1795123456789012301  # the first message's thread, in decimal as IMAP and Takeout spell it


def _mailbox(fake: Fake) -> None:
    """Four messages of a week, a draft and a spam: what Ines's mailbox holds."""
    fake.labels = list(LABELS)
    fake.deliver(_raw("m1@mail.example.org", T0), T0, ("INBOX", "Label_7"), thread=ROOT)
    fake.deliver(
        _raw("m2@mail.example.org", T0 + timedelta(hours=12), sent=True), T0 + timedelta(hours=12), ("SENT",)
    )
    fake.deliver(
        _raw("m3@mail.example.org", T0 + timedelta(hours=24), subject="Berth", attachment=JPEG),
        T0 + timedelta(hours=24),
        ("INBOX", "IMPORTANT", "CATEGORY_UPDATES", "UNREAD"),
    )
    fake.deliver(
        _raw(
            "m4@mail.example.org",
            T0 + timedelta(hours=36),
            subject="Re: Mooring",
            extra="In-Reply-To: <m1@mail.example.org>\r\nReferences: <m1@mail.example.org>\r\n",
        ),
        T0 + timedelta(hours=36),
        ("INBOX", "STARRED", "Label_8"),
        thread=ROOT,
    )
    fake.deliver(
        _raw("d1@mail.example.org", T0 + timedelta(hours=40), sent=True), T0 + timedelta(hours=40), ("DRAFT",)
    )
    fake.deliver(_raw("s1@spam.example.org", T0 + timedelta(hours=44)), T0 + timedelta(hours=44), ("SPAM",))


LINES = 4


@pytest.fixture(scope="module")
def key() -> Any:
    return private_key()


@pytest.fixture
def fake(tmp_path: Path, key: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    server = Fake(key)
    _mailbox(server)
    server.waits = []  # type: ignore[attr-defined]
    monkeypatch.setattr(service_account, "send", server)
    monkeypatch.setattr(service_account, "sleep", server.waits.append)  # type: ignore[attr-defined]
    monkeypatch.setenv(KEY_ENV, str(write_key(tmp_path / "google-sa.json", key)))
    monkeypatch.setenv(USER_ENV, USER)
    return server


@pytest.fixture
def offline(fake: Fake, no_network: list[str]) -> Iterator[Fake]:
    yield fake
    assert no_network == [], "the fake is the only way out"


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.set_owner_emails([USER])
    return lb


def _config() -> service_account.Account:
    account = gmail.configure(os.environ)
    assert account is not None
    return account


class Walk:
    """`sync`'s checkpoint keeper as the adapter sees it."""

    def __init__(self, saved: dict[str, Any] | None = None) -> None:
        self.saved = saved
        self.reached: list[tuple[int, dict[str, Any]]] = []

    def start(self) -> dict[str, Any] | None:
        return self.saved

    def reach(self, ordinal: int, checkpoint: dict[str, Any]) -> None:
        self.reached.append((ordinal, checkpoint))


def _pull(**kw: Any) -> tuple[list[dict[str, Any]], dict[str, int]]:
    counts: dict[str, int] = {}
    walk = kw.pop("walk", None)
    if walk is not None:
        kw["walk"] = type("W", (), {"start": walk.start, "reached": walk.reach})()
    drafts = list(gmail.pull(_config(), counts=counts, timezone="Europe/Oslo", owner_emails=[USER], **kw))
    return drafts, counts


def _by_id(drafts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {d["payload"]["message_id"]: d for d in drafts}


def _sync(capsys: pytest.CaptureFixture[str], *args: str, source: str = "gmail") -> tuple[int, str, str]:
    try:
        cli.main(["sync", source, *args])
    except SystemExit as e:
        status = e.code if isinstance(e.code, int) else 1
    else:
        status = 0
    out = capsys.readouterr()
    return status, out.out, out.err


def _state(lb: Logbook) -> dict[str, Any]:
    path = lb.root / "state" / "gmail.json"
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return dict(data.get("resume", {}).get("checkpoint", {}))


# -- registry and configuration ------------------------------------------------------------------------


def test_registry_has_gmail_as_a_live_adapter_writing_mail_lines() -> None:
    assert adapters.live("gmail") is gmail
    assert adapters.named("gmail") is None
    assert isinstance(gmail, adapters.LiveAdapter)
    assert gmail.NAME == "gmail" and gmail.SOURCE == mail.NAME == "mail"
    assert gmail.KIND == "mail" and gmail.UNIT == "messages" and gmail.RESUMES is True
    assert gmail.ENV == service_account.ENV and gmail.SCOPE == GMAIL_SCOPE


def test_configure_is_the_one_service_account(offline: Fake) -> None:
    account = _config()
    assert account == service_account.configure(os.environ)
    assert gmail.configure({}) is None


# -- pull: the line --------------------------------------------------------------------------------------


def test_pull_writes_one_mail_line_per_message_keyed_by_account_and_message_id(offline: Fake) -> None:
    drafts, _counts = _pull()
    assert len(drafts) == LINES
    lines = _by_id(drafts)
    assert set(lines) == {f"m{i}@mail.example.org" for i in (1, 2, 3, 4)}
    for message_id, line in lines.items():
        assert line["source"] == "mail" and line["kind"] == "mail" and line["tier"] == 2
        assert line["payload"]["raw_id"] == f"{USER}:{message_id}"
        assert line["payload"]["account"] == USER and line["tz"] == "Europe/Oslo"
    assert lines["m2@mail.example.org"]["payload"]["direction"] == "sent"
    assert lines["m1@mail.example.org"]["payload"]["direction"] == "received"
    assert lines["m4@mail.example.org"]["payload"]["thread"] == "m1@mail.example.org"


def test_the_line_is_the_one_the_imap_source_writes_for_the_same_message(offline: Fake) -> None:
    """The same bytes through the same parser, the server's date as the fallback, the attachments
    digested and never stored, Gmail's labels and thread id where the IMAP source puts them, and the
    tab its CATEGORY_UPDATES label names, which IMAP cannot say (RFC 0015, amendment of 2026-10-20)."""
    raw = _raw("m3@mail.example.org", T0 + timedelta(hours=24), subject="Berth", attachment=JPEG)
    expected, _blobs = mail.parse_message(
        raw, T0, {}, "Europe/Oslo", None, {USER}, USER, digest_attachments=True, fallback_name="internaldate"
    )
    assert expected is not None
    mail.gmail_fields(expected["payload"], ["Inbox", "Important"], str(0x18E0_0000_0000_0003), "updates")
    drafts, _counts = _pull()
    line = _by_id(drafts)["m3@mail.example.org"]
    assert json.dumps(line, ensure_ascii=False) == json.dumps(expected, ensure_ascii=False)


def test_labels_are_folded_into_the_profiles_slot_as_imap_spells_them(offline: Fake) -> None:
    lines = _by_id(_pull()[0])
    assert lines["m1@mail.example.org"]["payload"]["labels"] == ["Inbox", "Harbour"]
    assert lines["m2@mail.example.org"]["payload"]["labels"] == ["Sent"]
    assert lines["m3@mail.example.org"]["payload"]["labels"] == ["Inbox", "Important"], (
        "no UNREAD, no category"
    )
    assert lines["m4@mail.example.org"]["payload"]["labels"] == ["Inbox", "Starred", "Boat/Engine"]


def test_the_thread_id_is_gmails_in_decimal_as_imap_and_takeout_spell_it(offline: Fake) -> None:
    lines = _by_id(_pull()[0])
    assert lines["m1@mail.example.org"]["payload"]["extra"]["gmail_thread_id"] == str(ROOT)
    assert lines["m4@mail.example.org"]["payload"]["extra"]["gmail_thread_id"] == str(ROOT)


def test_attachments_are_references_name_size_type_and_digest_never_content(offline: Fake) -> None:
    import hashlib

    line = _by_id(_pull()[0])["m3@mail.example.org"]
    assert line["payload"]["attachments"] == [
        {
            "filename": "berth.jpg",
            "media_type": "image/jpeg",
            "bytes": len(JPEG),
            "sha256": hashlib.sha256(JPEG).hexdigest(),
        }
    ]
    text = json.dumps(line)
    assert (
        base64.b64encode(JPEG[:48]).decode("ascii") not in text
        and "path" not in line["payload"]["attachments"][0]
    )


def test_the_body_is_the_text_the_mail_source_stores_and_the_size_the_message(offline: Fake) -> None:
    line = _by_id(_pull()[0])["m3@mail.example.org"]
    raw = _raw("m3@mail.example.org", T0 + timedelta(hours=24), subject="Berth", attachment=JPEG)
    assert line["payload"]["body"] == "Hei." and line["payload"]["size"] == len(raw)


def test_drafts_spam_and_trash_are_never_lines(offline: Fake) -> None:
    drafts, counts = _pull()
    assert "d1@mail.example.org" not in _by_id(drafts) and "s1@spam.example.org" not in _by_id(drafts)
    assert counts == {"skipped_draft": 1, "attachments_referenced": 1}
    assert all(c.get("includeSpamTrash") in (None, "false") for c in offline.calls(MESSAGES))


def test_a_message_without_a_date_header_takes_gmails_internal_date(offline: Fake) -> None:
    when = T0 + timedelta(hours=50)
    raw = _raw("m5@mail.example.org", when).replace(b"Date: ", b"X-Old-Date: ")
    offline.deliver(raw, when, ("INBOX",))
    drafts, counts = _pull()
    assert _by_id(drafts)["m5@mail.example.org"]["at"] == "2026-03-04T12:15:00Z"
    assert counts["date_from_internaldate"] == 1


# -- pull: what is asked ---------------------------------------------------------------------------------


def test_the_client_only_reads_with_the_gmail_scope(offline: Fake) -> None:
    _pull()
    assert offline.methods() == {("POST", "oauth2.googleapis.com"), ("GET", "gmail.googleapis.com")}
    assert {a["scope"] for a in offline.assertions} == {GMAIL_SCOPE}


def test_headers_first_and_no_body_the_record_holds_is_fetched(offline: Fake) -> None:
    held = {("mail", f"{USER}:m1@mail.example.org"), ("mail", f"{USER}:m3@mail.example.org")}
    drafts, counts = _pull(existing=lambda keys: {k for k in keys if k in held})
    assert sorted(_by_id(drafts)) == ["m2@mail.example.org", "m4@mail.example.org"]
    assert counts["already_in_record"] == 2
    raw_asked = [
        p for _m, p, q in offline.requests if p.startswith(MESSAGES + "/") and q.get("format") == "raw"
    ]
    m1, m3 = (
        m["id"] for m in offline.mail if m["raw"].startswith((b"Message-ID: <m1@", b"Message-ID: <m3@"))
    )
    assert f"{MESSAGES}/{m1}" not in raw_asked and f"{MESSAGES}/{m3}" not in raw_asked
    metadata = [
        q
        for p, q in ((p, q) for _m, p, q in offline.requests if p.startswith(MESSAGES + "/"))
        if q.get("format") == "metadata"
    ]
    assert metadata and all(q["metadataHeaders"] == "Message-ID" for q in metadata)


def test_since_lists_the_messages_gmail_received_from_then_on(offline: Fake) -> None:
    since = "2026-03-03T10:15:00Z"
    drafts, _counts = _pull(since=since)
    assert sorted(_by_id(drafts)) == ["m3@mail.example.org", "m4@mail.example.org"]
    epoch = int(datetime(2026, 3, 3, 10, 15, tzinfo=UTC).timestamp())
    assert offline.calls(MESSAGES)[0]["q"] == f"after:{epoch - 1}"


def test_pull_pages_until_the_last_page_and_says_each(offline: Fake) -> None:
    said: list[str] = []
    offline.page = 2
    drafts, _counts = _pull(notice=said.append)
    assert len(drafts) == LINES
    assert [c.get("pageToken") for c in offline.calls(MESSAGES)] == [None, "2", "4"]
    assert said == [  # newest first: the draft, then m4; m3 and m2; m1
        "2 listed, 1 new, 0 already in the record",
        "4 listed, 3 new, 0 already in the record",
        "5 listed, 4 new, 0 already in the record",
    ]


def test_pull_backs_off_on_429_and_5xx_and_carries_on(offline: Fake) -> None:
    offline.fail(429, retry_after="5")
    offline.fail(500)
    offline.fail(503)
    drafts, _counts = _pull()
    assert len(drafts) == LINES
    assert offline.waits == [5.0, 2.0, 4.0]  # type: ignore[attr-defined]


def test_a_message_gone_between_the_list_and_the_read_is_counted(offline: Fake) -> None:
    gone = offline.mail[0]
    real = offline.__class__._message

    def vanishing(self: Fake, message_id: str, params: dict[str, Any]) -> Any:
        if message_id == gone["id"] and params.get("format") == "raw":
            return real(self, "0", params)
        return real(self, message_id, params)

    offline._message = vanishing.__get__(offline)  # type: ignore[method-assign]
    drafts, counts = _pull()
    assert len(drafts) == LINES - 1 and counts["skipped_gone"] == 1


# -- the watermark: the history id, else the internal date ---------------------------------------------


def test_a_first_run_marks_the_history_id_from_before_the_list_and_the_newest_message(offline: Fake) -> None:
    walk = Walk()
    _pull(walk=walk)
    assert walk.reached == [
        (LINES, {"history_id": str(offline.history_id), "internal_date": "2026-03-04T02:15:00Z"})
    ]


def test_a_run_with_a_history_id_reads_the_history_and_nothing_else(offline: Fake) -> None:
    mark = {"history_id": str(offline.history_id), "internal_date": "2026-03-04T02:15:00Z"}
    when = T0 + timedelta(days=3)
    offline.deliver(_raw("m6@mail.example.org", when), when, ("INBOX",))
    walk = Walk(mark)
    drafts, _counts = _pull(walk=walk)
    assert list(_by_id(drafts)) == ["m6@mail.example.org"]
    assert offline.calls(MESSAGES) == [], "nothing listed: the history names what is new"
    assert offline.calls(HISTORY)[0]["startHistoryId"] == mark["history_id"]
    assert offline.calls(HISTORY)[0]["historyTypes"] == "messageAdded"
    assert walk.reached == [
        (1, {"history_id": str(offline.history_id), "internal_date": "2026-03-05T10:15:00Z"})
    ]


def test_a_history_id_gmail_no_longer_keeps_falls_back_to_the_internal_date_less_a_day(offline: Fake) -> None:
    offline.history_floor = offline.history_id + 1
    said: list[str] = []
    walk = Walk({"history_id": "1001", "internal_date": "2026-03-03T22:15:00Z"})
    drafts, _counts = _pull(walk=walk, notice=said.append)
    assert sorted(_by_id(drafts)) == ["m2@mail.example.org", "m3@mail.example.org", "m4@mail.example.org"]
    epoch = int(datetime(2026, 3, 2, 22, 15, tzinfo=UTC).timestamp())
    assert offline.calls(MESSAGES)[0]["q"] == f"after:{epoch - 1}"
    assert (
        said[0]
        == "the history id is older than Gmail keeps; reading by date from a day before the newest message"
    )


def test_spam_and_trash_the_history_names_are_counted_not_written(offline: Fake) -> None:
    mark = {"history_id": str(offline.history_id), "internal_date": "2026-03-04T02:15:00Z"}
    when = T0 + timedelta(days=3)
    offline.deliver(_raw("s2@spam.example.org", when), when, ("SPAM",))
    offline.deliver(_raw("m8@mail.example.org", when), when, ("TRASH",))
    drafts, counts = _pull(walk=Walk(mark))
    assert drafts == [] and counts == {"skipped_spam_or_trash": 2}


def test_since_on_a_run_with_a_mark_leaves_the_mark_alone(offline: Fake) -> None:
    mark = {"history_id": "1003", "internal_date": "2026-03-03T10:15:00Z"}
    walk = Walk(mark)
    _pull(walk=walk, since="2026-03-01T00:00:00Z")
    assert walk.reached == []


# -- sync --------------------------------------------------------------------------------------------------


def test_sync_first_run_writes_every_message_and_the_second_none(
    lb: Logbook, offline: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    status, out, err = _sync(capsys)
    assert status == 0, err
    assert "gmail: 0 messages already in the record" in out
    assert f"gmail: {LINES} new lines of {LINES} seen from the beginning; marks in state/gmail.json" in out
    assert f"  history id {offline.history_id}, newest message 2026-03-04T02:15:00Z" in out.splitlines()
    assert "  skipped 1 drafts (neither sent nor received)" in out.splitlines()
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == LINES
    assert {line["source"] for line in lb.lines()} == {"mail"}
    status, out, _err = _sync(capsys)
    assert status == 0 and "gmail: 0 new lines of 0 seen from the beginning" in out
    assert f"gmail: {LINES} messages already in the record" in out
    assert lb.meta["seq"] == LINES
    assert offline.calls(HISTORY), "the second run read the history"


def test_sync_a_message_arriving_later_is_the_one_new_line(
    lb: Logbook, offline: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    _sync(capsys)
    when = T0 + timedelta(days=4)
    offline.deliver(_raw("m7@mail.example.org", when), when, ("INBOX",))
    status, out, _err = _sync(capsys)
    assert status == 0 and "gmail: 1 new lines of 1 seen from the beginning" in out
    assert _state(lb) == {"history_id": str(offline.history_id), "internal_date": "2026-03-06T10:15:00Z"}


def test_sync_since_and_dry_run(lb: Logbook, offline: Fake, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _err = _sync(capsys, "--dry-run")
    assert status == 0 and f"gmail: {LINES} lines from the beginning (dry run, nothing written)" in out
    assert lb.meta["seq"] == 0 and not (lb.root / "state").exists()
    status, out, _err = _sync(capsys, "--since", "2026-03-03T10:15:00Z")
    assert status == 0 and "gmail: 2 new lines of 2 seen since 2026-03-03T10:15:00Z" in out
    assert _state(lb)["history_id"] == str(offline.history_id), "a first run with --since leaves a mark"


def test_sync_restart_reads_the_mailbox_again_and_writes_nothing_twice(
    lb: Logbook, offline: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    _sync(capsys)
    status, _out, err = _sync(capsys, "--restart")
    assert status == 0 and "--restart: the stored marks are dropped" in err
    assert lb.meta["seq"] == LINES


def test_sync_a_scope_the_delegation_lacks_is_one_line_and_exit_1(
    lb: Logbook, offline: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    offline.delegated = {DRIVE_SCOPE}
    status, _out, err = _sync(capsys)
    assert status == 1 and err.count("\n") == 1 and GMAIL_SCOPE in err
    assert lb.meta["seq"] == 0 and _state(lb) == {}


def test_doctor_shows_sync_gmail_configured_and_asks_nothing(lb: Logbook, offline: Fake) -> None:
    checks = {c.name: c for c in doctor.run(lb, dict(os.environ), installed=lambda _m: True)}
    check = checks["sync:gmail"]
    assert check.status == "pass" and check.detail.startswith(f"configured ({KEY_ENV}, {USER_ENV}); ")
    assert offline.requests == []


# -- the same mailbox over IMAP, then over the API -------------------------------------------------------


@pytest.fixture
def imap(fake: Fake, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeImap]:
    """The same mailbox on the fake IMAP server: the four messages in All Mail, with the labels and
    thread ids IMAP gives them."""
    imap_labels = {"INBOX": "\\Inbox", "SENT": "\\Sent", "IMPORTANT": "\\Important", "STARRED": "\\Starred"}
    names = {label["id"]: label["name"] for label in LABELS if label["type"] == "user"}
    messages = {}
    for uid, m in enumerate((m for m in fake.mail if not {"DRAFT", "SPAM"} & set(m["labelIds"])), start=1):
        labels = tuple(
            imap_labels.get(i) or names[i] for i in m["labelIds"] if i in imap_labels or i in names
        )
        when = datetime.fromtimestamp(int(m["internalDate"]) / 1000, UTC)
        messages[uid] = Message(
            uid, m["raw"], internaldate(when), labels=labels, thrid=int(m["threadId"], 16)
        )
    server = FakeImap([Folder("[Gmail]/All Mail", 1234, messages, attributes=("\\All",))], user=USER)
    port = server.start()
    monkeypatch.setenv("LOGBOOK_IMAP_HOST", "imap.example.org")
    monkeypatch.setenv("LOGBOOK_IMAP_USER", USER)
    monkeypatch.setenv("LOGBOOK_IMAP_PASSWORD", server.password)
    monkeypatch.setattr(
        mail_imap, "open_connection", lambda config: imaplib.IMAP4("127.0.0.1", port, timeout=10)
    )
    try:
        yield server
    finally:
        server.stop()


def test_a_mailbox_synced_by_imap_then_by_gmail_is_written_once(
    lb: Logbook, fake: Fake, imap: FakeImap, capsys: pytest.CaptureFixture[str]
) -> None:
    status, out, err = _sync(capsys, source="mail")
    assert status == 0, err
    assert lb.meta["seq"] == LINES
    by_imap = {line["payload"]["raw_id"]: line for line in lb.lines()}
    status, out, err = _sync(capsys)
    assert status == 0, err
    assert "gmail: 0 new lines of 0 seen from the beginning" in out
    assert f"{LINES + 1} listed, 0 new, {LINES} already in the record" in err, "the draft is listed too"
    assert lb.meta["seq"] == LINES, "nothing twice"
    raw_asked = [q for _m, _p, q in fake.requests if q.get("format") == "raw"]
    assert raw_asked == [], "no body the record holds was fetched"
    drafts, _counts = _pull()
    tabs = {}
    for draft in drafts:
        line = by_imap[draft["payload"]["raw_id"]]
        assert "gmail_category" not in line["payload"].get("extra", {}), "IMAP cannot say the tab"
        tabs[draft["payload"]["message_id"]] = draft["payload"]["extra"].pop("gmail_category", None)
        assert {k: line[k] for k in draft} == draft, draft["payload"]["raw_id"]
    assert tabs == {f"m{i}@mail.example.org": "updates" if i == 3 else None for i in (1, 2, 3, 4)}, (
        "the tab is the one difference, and only where a CATEGORY_* label names it"
    )


def test_sync_all_runs_gmail_after_mail() -> None:
    from logbook.commands import sync

    names = [a.NAME for a in sync._all_order(adapters.live_adapters())]
    assert names.index("mail") < names.index("gmail") < names.index("immich")


def test_a_first_run_with_since_and_nothing_after_it_marks_since_as_the_newest_date(
    lb: Logbook, offline: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    status, out, _err = _sync(capsys, "--since", "2026-05-01T00:00:00Z")
    assert status == 0 and "gmail: 0 new lines of 0 seen" in out
    assert _state(lb) == {"history_id": str(offline.history_id), "internal_date": "2026-05-01T00:00:00Z"}
    offline.history_floor = offline.history_id + 1  # a week on, Gmail keeps that history no more
    status, out, _err = _sync(capsys)
    assert status == 0 and "gmail: 0 new lines of 0 seen" in out
    epoch = int(datetime(2026, 4, 30, 0, 0, tzinfo=UTC).timestamp())
    assert offline.calls(MESSAGES)[-1]["q"] == f"after:{epoch - 1}", "a day before the mark, never everything"


def test_a_bounded_first_scheduled_run_lists_two_weeks_and_skips_what_another_mail_road_wrote(
    lb: Logbook,
    offline: Fake,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`sync --scheduled` bounds gmail's first run to the last 14 local days, and within them the record
    is still asked by Message-ID, from any mail road, before a body is fetched: two messages a Takeout
    wrote without `--account` (keyed by the bare id, a key gmail's own never matches) are counted, not
    fetched and not written; the two it does not hold are; one from before the window is never listed."""
    from logbook.contrib import first_run, last_run, notify

    monkeypatch.setattr(adapters, "live_adapters", lambda: [gmail])
    monkeypatch.setattr(last_run, "now", lambda: datetime(2026, 3, 10, 12, 0, tzinfo=UTC))  # a Tuesday
    for name in notify.ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(doctor, "EXTRAS", ())  # what this machine has installed is not the test's
    monkeypatch.setattr(doctor, "DISK_WARN_BYTES", 0)
    early = T0 - timedelta(days=45)  # mid-January: history the bound leaves for a `--since`
    offline.deliver(_raw("m0@mail.example.org", early), early, ("INBOX",))
    mbox = tmp_path / "takeout.mbox"
    with mbox.open("wb") as fh:  # the export of m1 and m2, as Takeout writes it
        for n, (message_id, when, sent) in enumerate(
            [("m1@mail.example.org", T0, False), ("m2@mail.example.org", T0 + timedelta(hours=12), True)]
        ):
            fh.write(f"From 179512345678901{n} {when.strftime('%a %b %d %H:%M:%S +0000 %Y')}\n".encode())
            fh.write(b"X-Gmail-Labels: Inbox\r\n" + _raw(message_id, when, sent=sent) + b"\r\n")
    cli.main(["add", "mail", str(mbox)])
    assert {line["payload"]["raw_id"] for line in lb.lines()} == {
        "m1@mail.example.org",
        "m2@mail.example.org",
    }
    capsys.readouterr()

    try:
        cli.main(["sync", "--scheduled"])
    except SystemExit as e:
        assert not e.code, capsys.readouterr()
    out, err = capsys.readouterr()

    assert (
        out.count(
            "gmail: first scheduled run read from 2026-02-25; for the history run"
            " `logbook sync gmail --since <date>`"
        )
        == 1
    )
    bound = int(datetime(2026, 2, 24, 23, 0, tzinfo=UTC).timestamp())  # Oslo's midnight of the 25th
    assert offline.calls(MESSAGES)[0]["q"] == f"after:{bound - 1}", "the window, never the whole mailbox"
    assert "  2 already in the record from mail (an import without --account)" in out.splitlines()
    assert f"{LINES + 1} listed, 2 new, 2 already in the record" in err, "the draft is listed too"
    fetched = [path for _m, path, q in offline.requests if q.get("format") == "raw"]
    assert len(fetched) == 2, "no body the record holds from the Takeout was fetched"
    written = [line["payload"]["raw_id"] for line in lb.lines()]
    assert len(written) == 4 and set(written) == {
        "m1@mail.example.org",
        "m2@mail.example.org",
        f"{USER}:m3@mail.example.org",
        f"{USER}:m4@mail.example.org",
    }, "each message once, m0 not read"
    mark = first_run.read(lb.root, "gmail")
    assert mark is not None and mark["from"] == "2026-02-24T23:00:00Z" and mark["day"] == "2026-02-25"
    found = {c.name: c for c in doctor.run(Logbook.find(), os.environ)}
    assert "history not read (before 2026-02-25" in found["sync:gmail"].detail
