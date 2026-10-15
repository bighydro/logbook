"""`logbook sync mail`: a mailbox read over IMAP, read-only, through the mbox adapter's own parser (RFC
0015), against the fake server of `tests/imap_server.py` on the loopback interface. Synthetic mail only:
Ines and Ola Nordmann of Oslo, who do not exist, at example.org."""

from __future__ import annotations

import imaplib
import json
import ssl
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from imap_server import FakeImap, Folder, Message, internaldate

from logbook import cli
from logbook.contrib import adapters, doctor
from logbook.contrib.adapters import mail, mail_imap
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
MBOX = ROOT / "tests" / "fixtures" / "mail" / "takeout.mbox"
INES = "ines.nordmann@example.org"
OLA = "ola@example.org"
PASSWORD = "abcd efgh ijkl mnop"
ALL_MAIL = "[Gmail]/All Mail"
T0 = datetime(2026, 3, 2, 10, 15, tzinfo=UTC)


# -- the mailbox -----------------------------------------------------------------------------------


def _raw(
    message_id: str,
    when: datetime,
    sender: str,
    to: str,
    subject: str,
    body: str,
    extra: str = "",
    attachment: bytes | None = None,
) -> bytes:
    date = when.strftime("%a, %d %b %Y %H:%M:%S %z")
    head = (
        f"Message-ID: <{message_id}>\r\nDate: {date}\r\nFrom: {sender}\r\nTo: {to}\r\n"
        f"Subject: {subject}\r\n{extra}"
    )
    if attachment is None:
        return (head + 'Content-Type: text/plain; charset="utf-8"\r\n\r\n' + body + "\r\n").encode("utf-8")
    import base64

    b64 = base64.encodebytes(attachment).decode("ascii").replace("\n", "\r\n")
    return (
        head + 'Content-Type: multipart/mixed; boundary="b1"\r\n\r\n--b1\r\n'
        'Content-Type: text/plain; charset="utf-8"\r\n\r\n' + body + "\r\n--b1\r\n"
        'Content-Type: image/jpeg; name="berth.jpg"\r\n'
        'Content-Disposition: attachment; filename="berth.jpg"\r\n'
        "Content-Transfer-Encoding: base64\r\n\r\n" + b64 + "--b1--\r\n"
    ).encode("utf-8")


def _message(uid: int, message_id: str, hours: float, sent: bool = False, **kw: Any) -> Message:
    when = T0 + timedelta(hours=hours)
    sender = f"Ines Nordmann <{INES}>" if sent else f"Ola Nordmann <{OLA}>"
    to = f"Ola Nordmann <{OLA}>" if sent else f"Ines Nordmann <{INES}>"
    labels = ("\\Sent",) if sent else ("\\Inbox", "Harbour")
    raw = _raw(
        message_id, when, sender, to, kw.pop("subject", f"Message {uid}"), kw.pop("body", "Hei."), **kw
    )
    return Message(uid, raw, internaldate(when), labels=labels, thrid=1795123456789012300 + uid)


def _all_mail(n: int = 6, uidvalidity: int = 1234) -> Folder:
    """`n` messages in All Mail, one of them Ines's own (sent), one with an attachment."""
    messages = {}
    for uid in range(1, n + 1):
        kw: dict[str, Any] = {}
        if uid == 2:
            kw["sent"] = True
        if uid == 3:
            kw["attachment"] = b"\xff\xd8" + bytes(range(256)) * 4
        messages[uid] = _message(uid, f"m{uid}@mail.example.org", hours=uid * 12.0, **kw)
    return Folder(ALL_MAIL, uidvalidity, messages, attributes=("\\All",))


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    lb = Logbook.init(root, "Europe/Oslo")
    lb.set_owner_emails([INES])
    return lb


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeImap]:
    """The fake server with All Mail, the environment pointing at it, and the client's connection
    hook opening a plain loopback connection in place of TLS."""
    fake = FakeImap([_all_mail()], user=INES, password=PASSWORD)
    yield from _serve(fake, monkeypatch)


def _serve(fake: FakeImap, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeImap]:
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


def _sync(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    try:
        cli.main(["sync", "mail", *args])
    except SystemExit as e:
        status = e.code if isinstance(e.code, int) else 1
    else:
        status = 0
    out = capsys.readouterr()
    return status, out.out, out.err


def _marks(lb: Logbook) -> dict[str, Any]:
    path = lb.root / "state" / "mail.json"
    if not path.exists():
        return {}
    state = json.loads(path.read_text(encoding="utf-8"))
    return dict(state.get("resume", {}).get("checkpoint", {}).get("folders", {}))


def _mail_lines(lb: Logbook) -> list[dict[str, Any]]:
    return [line for line in lb.lines() if line["source"] == "mail"]


# -- registry and configuration --------------------------------------------------------------------


def test_registry_has_mail_as_a_live_adapter_beside_the_file_adapter() -> None:
    assert adapters.live("mail") is mail_imap
    assert adapters.named("mail") is mail
    assert isinstance(mail_imap, adapters.LiveAdapter)
    assert mail_imap.NAME == mail.NAME == "mail"
    assert mail_imap.KIND == "mail" and mail_imap.UNIT == "messages"
    assert mail_imap.ENV == ("LOGBOOK_IMAP_HOST", "LOGBOOK_IMAP_USER", "LOGBOOK_IMAP_PASSWORD")


def test_configure_needs_host_user_and_password_and_hides_the_password() -> None:
    assert mail_imap.configure({}) is None
    assert mail_imap.configure({"LOGBOOK_IMAP_HOST": "imap.example.org", "LOGBOOK_IMAP_USER": INES}) is None
    env = {
        "LOGBOOK_IMAP_HOST": "imap.example.org",
        "LOGBOOK_IMAP_USER": INES,
        "LOGBOOK_IMAP_PASSWORD": PASSWORD,
    }
    config = mail_imap.configure(env)
    assert config is not None
    assert config.host == "imap.example.org" and config.port == 993 and config.folders is None
    assert config.user == INES and config.account == INES
    assert PASSWORD not in repr(config) and PASSWORD not in str(config)
    assert mail_imap.configure({**env, "LOGBOOK_IMAP_PORT": "1993"}).port == 1993  # type: ignore[union-attr]
    folders = mail_imap.configure({**env, "LOGBOOK_IMAP_FOLDERS": " INBOX, Sendt ,,"}).folders  # type: ignore[union-attr]
    assert folders == ("INBOX", "Sendt")


@pytest.mark.parametrize("port", ["abc", "0", "70000", "-1"])
def test_configure_refuses_a_port_that_is_not_one_naming_the_variable_not_the_value(port: str) -> None:
    env = {
        "LOGBOOK_IMAP_HOST": "imap.example.org",
        "LOGBOOK_IMAP_USER": INES,
        "LOGBOOK_IMAP_PASSWORD": PASSWORD,
        "LOGBOOK_IMAP_PORT": port,
    }
    with pytest.raises(ValueError, match="LOGBOOK_IMAP_PORT") as e:
        mail_imap.configure(env)
    assert port not in str(e.value) or port in (
        "0",
        "-1",
    )  # a number this short may be in the sentence's words


def test_the_connection_is_tls_on_993_with_a_verifying_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """The one place a socket is opened: IMAP4_SSL, never IMAP4 with STARTTLS, with the default
    verifying context (hostname checked, certificate required)."""
    opened: list[dict[str, Any]] = []

    class Fake:
        def __init__(self, host: str, port: int, *, ssl_context: ssl.SSLContext, timeout: float) -> None:
            opened.append({"host": host, "port": port, "context": ssl_context, "timeout": timeout})

    monkeypatch.setattr(imaplib, "IMAP4_SSL", Fake)
    config = mail_imap.configure(
        {
            "LOGBOOK_IMAP_HOST": "imap.example.org",
            "LOGBOOK_IMAP_USER": INES,
            "LOGBOOK_IMAP_PASSWORD": PASSWORD,
        }
    )
    assert config is not None
    mail_imap.open_connection(config)
    assert len(opened) == 1 and opened[0]["host"] == "imap.example.org" and opened[0]["port"] == 993
    context = opened[0]["context"]
    assert context.check_hostname is True and context.verify_mode == ssl.CERT_REQUIRED
    assert opened[0]["timeout"] > 0


# -- the first run, the second run, the record's refusal -------------------------------------------


def test_first_run_writes_every_message_and_the_second_writes_nothing(
    lb: Logbook, server: FakeImap, capsys: pytest.CaptureFixture[str]
) -> None:
    status, out, err = _sync(capsys)
    assert status == 0, err
    assert "mail: 6 new lines of 6 seen" in out
    lines = _mail_lines(lb)
    assert len(lines) == 6
    validator = Draft202012Validator(SCHEMA)
    for line in lines:
        validator.validate(line)
        assert line["kind"] == "mail" and line["tier"] == 2 and line["tz"] == "Europe/Oslo"
        assert line["payload"]["schema"] == "mail/v1" and line["payload"]["account"] == INES
    by_id = {line["payload"]["message_id"]: line for line in lines}
    first = by_id["m1@mail.example.org"]
    assert first["payload"]["raw_id"] == f"{INES}:m1@mail.example.org"
    assert first["at"] == "2026-03-02T22:15:00Z" and first["payload"]["direction"] == "received"
    assert first["payload"]["from"] == {"email": OLA, "name": "Ola Nordmann"}
    assert first["payload"]["body"] == "Hei.\n"
    assert by_id["m2@mail.example.org"]["payload"]["direction"] == "sent"
    assert _marks(lb) == {ALL_MAIL: {"uidvalidity": 1234, "uid": 6}}
    # the second run asks for what came after the mark and writes nothing
    status, out, _err = _sync(capsys)
    assert status == 0 and "mail: 0 new lines of 0 seen" in out
    assert len(_mail_lines(lb)) == 6
    assert any("UID 7:*" in line for line in server.sent("SEARCH")), server.commands
    assert lb.verify()[0] == 6


def test_a_message_already_imported_from_the_mbox_export_is_refused_without_fetching_its_body(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The Takeout import (`add mail --account <address>`) and the live sync of the same mailbox write
    the same raw_id, so neither writes what the other holds; the headers-first pass means the record's
    refusal costs no body fetch."""
    account = "kari.nordmann@example.org"
    cli.main(["add", "mail", str(MBOX), "--account", account])
    capsys.readouterr()
    before = len(_mail_lines(lb))
    assert before == 6
    when = datetime(2026, 3, 2, 10, 15, tzinfo=UTC)
    same = Message(
        41,
        _raw(
            "a1b2c3@mail.example.org",
            when,
            f"Ola Nordmann <{OLA}>",
            account,
            "Re: Mooring",
            "Photos attached.",
        ),
        internaldate(when),
    )
    new = Message(
        42,
        _raw(
            "fresh@mail.example.org",
            when,
            f"Ola Nordmann <{OLA}>",
            account,
            "A new one",
            "Not in the export.",
        ),
        internaldate(when),
    )
    fake = FakeImap([Folder(ALL_MAIL, 7, {41: same, 42: new}, attributes=("\\All",))], user=account)
    for _ in _serve(fake, monkeypatch):
        status, out, _err = _sync(capsys)
        assert status == 0
        assert "mail: 1 new lines of 1 seen" in out and "1 already in the record" in out
        assert len(_mail_lines(lb)) == before + 1
        bodies = [line for line in fake.sent("FETCH") if "BODY.PEEK[]" in line]
        assert len(bodies) == 1 and "42" in bodies[0] and "41" not in bodies[0].split("(")[0], fake.commands


def test_a_uidvalidity_change_starts_the_folder_over_and_writes_nothing_new(
    lb: Logbook, server: FakeImap, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _sync(capsys)[0] == 0
    server.folders[ALL_MAIL].uidvalidity = 9999
    del server.commands[:]
    status, out, err = _sync(capsys)
    assert status == 0
    assert "mail: 0 new lines of 0 seen" in out and "6 already in the record" in out
    assert any("UID 1:*" in line for line in server.sent("SEARCH")), "the folder was walked from the start"
    assert "uidvalidity" in err.lower() or "started over" in err
    assert len(_mail_lines(lb)) == 6
    assert _marks(lb) == {ALL_MAIL: {"uidvalidity": 9999, "uid": 6}}


def test_since_narrows_the_search_to_the_day(
    lb: Logbook, server: FakeImap, capsys: pytest.CaptureFixture[str]
) -> None:
    status, out, _err = _sync(capsys, "--since", "2026-03-04T06:00:00Z")
    assert status == 0
    searches = server.sent("SEARCH")
    assert len(searches) == 1 and "SINCE 04-Mar-2026" in searches[0], searches
    # the day holds uid 4 (2026-03-04T10:15Z) and later: 4, 5, 6
    assert "mail: 3 new lines of 3 seen" in out
    assert {line["payload"]["message_id"] for line in _mail_lines(lb)} == {
        f"m{u}@mail.example.org" for u in (4, 5, 6)
    }
    assert _marks(lb) == {ALL_MAIL: {"uidvalidity": 1234, "uid": 6}}
    # the next run without --since starts after the mark; the dedupe covers what --since left out
    status, out, _err = _sync(capsys)
    assert status == 0 and "0 new lines" in out


def test_since_must_be_rfc3339(lb: Logbook, server: FakeImap, capsys: pytest.CaptureFixture[str]) -> None:
    status, _out, err = _sync(capsys, "--since", "2026-03-04")
    assert status == 2 and "RFC3339" in err


def test_restart_discards_the_marks_and_the_record_refuses_what_it_holds(
    lb: Logbook, server: FakeImap, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _sync(capsys)[0] == 0
    del server.commands[:]
    status, out, _err = _sync(capsys, "--restart")
    assert status == 0
    assert any("UID 1:*" in line for line in server.sent("SEARCH"))
    assert "0 new lines of 0 seen" in out and "6 already in the record" in out
    assert len(_mail_lines(lb)) == 6


def test_dry_run_fetches_headers_counts_and_writes_nothing(
    lb: Logbook, server: FakeImap, capsys: pytest.CaptureFixture[str]
) -> None:
    status, out, _err = _sync(capsys, "--dry-run")
    assert status == 0
    assert "mail: 6 lines from the beginning (dry run, nothing written)" in out
    assert _mail_lines(lb) == []
    assert not (lb.root / "state" / "mail.json").exists()
    assert server.sent("FETCH"), "the headers were fetched"


# -- Gmail's extension: labels and the thread id, a snapshot ---------------------------------------


def test_with_the_gmail_extension_labels_and_the_thread_id_are_on_the_line(
    lb: Logbook, server: FakeImap, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _sync(capsys)[0] == 0
    by_id = {line["payload"]["message_id"]: line["payload"] for line in _mail_lines(lb)}
    assert by_id["m1@mail.example.org"]["labels"] == ["Inbox", "Harbour"]
    assert by_id["m2@mail.example.org"]["labels"] == ["Sent"]
    assert by_id["m1@mail.example.org"]["extra"]["gmail_thread_id"] == "1795123456789012301"
    fetches = [line for line in server.sent("FETCH") if "BODY.PEEK[]" in line]
    assert all("X-GM-LABELS" in line and "X-GM-THRID" in line for line in fetches)


def test_without_the_gmail_extension_no_labels_and_no_thread_id(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeImap([_all_mail(2)], user=INES, password=PASSWORD, gmail=False)
    for _ in _serve(fake, monkeypatch):
        assert _sync(capsys)[0] == 0
        for line in _mail_lines(lb):
            assert "labels" not in line["payload"]
            assert "gmail_thread_id" not in line["payload"].get("extra", {})
        assert not any("X-GM-" in line for line in fake.commands)


def test_a_label_in_modified_utf7_is_decoded() -> None:
    assert mail_imap.decode_utf7("Bl&AOU-b&AOY-r") == "Blåbær"
    assert mail_imap.decode_utf7("Sendt") == "Sendt"
    assert mail_imap.decode_utf7("Tom &- Jerry") == "Tom & Jerry"
    assert mail_imap.encode_utf7("Blåbær") == "Bl&AOU-b&AOY-r"
    assert mail_imap.encode_utf7("INBOX") == "INBOX"
    assert mail_imap.decode_utf7(mail_imap.encode_utf7("Tom & Jerry/日本")) == "Tom & Jerry/日本"


# -- read-only, enforced -----------------------------------------------------------------------------


def test_the_source_never_sends_a_command_that_writes_and_fetches_bodies_with_peek(
    lb: Logbook, server: FakeImap, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _sync(capsys)[0] == 0
    assert _sync(capsys, "--since", "2026-03-01T00:00:00Z")[0] == 0
    commands = {line.split()[0].upper() for line in server.commands}
    commands |= {
        " ".join(line.split()[:2]).upper() for line in server.commands if line.upper().startswith("UID ")
    }
    forbidden = {"SELECT", "STORE", "COPY", "MOVE", "EXPUNGE", "APPEND", "CREATE", "DELETE", "RENAME"}
    forbidden |= {f"UID {c}" for c in ("STORE", "COPY", "MOVE", "EXPUNGE")}
    assert not commands & forbidden, commands
    assert any(line.upper().startswith("EXAMINE") for line in server.commands)
    for line in server.sent("FETCH"):
        upper = line.upper()
        assert "BODY[" not in upper and "RFC822" not in upper.replace("RFC822.SIZE", ""), line
        assert "BODY.PEEK[" in upper
    assert server.commands[-1].upper() == "LOGOUT"


# -- the folders --------------------------------------------------------------------------------------


def test_without_an_all_folder_the_default_is_inbox_and_the_sent_folder(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inbox = Folder("INBOX", 11, {1: _message(1, "in1@mail.example.org", 1.0)})
    sent = Folder(
        "Sendt", 12, {1: _message(1, "out1@mail.example.org", 2.0, sent=True)}, attributes=("\\Sent",)
    )
    drafts = Folder("Kladd", 13, {1: _message(1, "draft@mail.example.org", 3.0)}, attributes=("\\Drafts",))
    fake = FakeImap([inbox, sent, drafts], user=INES, password=PASSWORD, gmail=False)
    for _ in _serve(fake, monkeypatch):
        status, out, _err = _sync(capsys)
        assert status == 0 and "2 new lines of 2 seen" in out
        examined = [line.split(None, 1)[1] for line in fake.sent("EXAMINE")]
        assert examined == ['"INBOX"', '"Sendt"']
        assert _marks(lb) == {"INBOX": {"uidvalidity": 11, "uid": 1}, "Sendt": {"uidvalidity": 12, "uid": 1}}


def test_xlist_names_the_all_folder_when_special_use_is_absent(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeImap(
        [_all_mail(1), Folder("INBOX", 2)], user=INES, password=PASSWORD, special_use=False, xlist=True
    )
    for _ in _serve(fake, monkeypatch):
        status, out, _err = _sync(capsys)
        assert status == 0 and "1 new lines" in out
        assert fake.sent("XLIST") and [line.split(None, 1)[1] for line in fake.sent("EXAMINE")] == [
            f'"{ALL_MAIL}"'
        ]


def test_the_folders_variable_names_the_folders_in_order(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inbox = Folder("INBOX", 11, {1: _message(1, "in1@mail.example.org", 1.0)})
    fake = FakeImap([_all_mail(2), inbox], user=INES, password=PASSWORD)
    monkeypatch.setenv("LOGBOOK_IMAP_FOLDERS", "INBOX, [Gmail]/All Mail")
    for _ in _serve(fake, monkeypatch):
        status, out, _err = _sync(capsys)
        assert status == 0 and "3 new lines of 3 seen" in out
        assert [line.split(None, 1)[1] for line in fake.sent("EXAMINE")] == ['"INBOX"', f'"{ALL_MAIL}"']
        assert not fake.sent("LIST"), "the folders are given: the server is not asked for its list"


def test_a_missing_folder_is_refused_naming_the_folder_and_the_variable(
    lb: Logbook, server: FakeImap, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOGBOOK_IMAP_FOLDERS", "Nope")
    status, _out, err = _sync(capsys)
    assert status == 1
    assert "sync: mail: " in err and "Nope" in err and "LOGBOOK_IMAP_FOLDERS" in err
    assert "Failure" not in err, "the server's wording is not echoed"
    assert _mail_lines(lb) == []


# -- errors: one plain sentence, never a value -------------------------------------------------------


def test_an_authentication_failure_names_the_variables_and_never_the_password(
    lb: Logbook, server: FakeImap, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOGBOOK_IMAP_PASSWORD", "wrong password")
    status, out, err = _sync(capsys)
    assert status == 1
    assert "LOGBOOK_IMAP_PASSWORD" in err and "LOGBOOK_IMAP_USER" in err
    assert "wrong password" not in err + out and PASSWORD not in err + out and INES not in err + out
    assert err.count("\n") == 1, err
    assert server.commands[-1].upper() == "LOGOUT", "the connection is closed on the way out"


def test_a_tls_failure_names_the_host_variable_and_not_the_host(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOGBOOK_IMAP_HOST", "imap.example.org")
    monkeypatch.setenv("LOGBOOK_IMAP_USER", INES)
    monkeypatch.setenv("LOGBOOK_IMAP_PASSWORD", PASSWORD)

    def refuse(config: Any) -> Any:
        raise ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")

    monkeypatch.setattr(mail_imap, "open_connection", refuse)
    status, out, err = _sync(capsys)
    assert status == 1
    assert "TLS" in err and "LOGBOOK_IMAP_HOST" in err and "imap.example.org" not in err + out
    assert err.count("\n") == 1


def test_sync_refuses_to_run_without_the_variables_naming_them(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOGBOOK_IMAP_HOST", "imap.example.org")
    status, _out, err = _sync(capsys)
    assert status == 2 and "set LOGBOOK_IMAP_USER and LOGBOOK_IMAP_PASSWORD" in err


def test_a_connection_lost_midway_keeps_the_mark_at_the_last_written_batch_and_the_next_run_resumes(
    lb: Logbook, server: FakeImap, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Two messages per batch: the header fetch of batch 1, its body fetch, the header fetch of batch 2
    (dropped). The two lines of batch 1 are in the record, the mark is at uid 2, and the next run asks
    for uid 3 onwards."""
    monkeypatch.setattr(mail_imap, "BATCH", 2)
    server.drop_at_fetch = 3
    status, out, err = _sync(capsys)
    assert status == 1
    assert "sync: mail:" in err and "connection" in err.lower()
    assert len(_mail_lines(lb)) == 2
    assert _marks(lb) == {ALL_MAIL: {"uidvalidity": 1234, "uid": 2}}
    server.drop_at_fetch = None
    del server.commands[:]
    status, out, _err = _sync(capsys)
    assert status == 0 and "4 new lines of 4 seen" in out
    assert any("UID 3:*" in line for line in server.sent("SEARCH")), server.commands
    assert len(_mail_lines(lb)) == 6 and _marks(lb) == {ALL_MAIL: {"uidvalidity": 1234, "uid": 6}}
    assert lb.verify()[0] == 6


# -- what the line carries: the mbox parser's rules, one function -------------------------------------


def test_attachments_are_named_sized_and_digested_never_stored(
    lb: Logbook, server: FakeImap, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _sync(capsys)[0] == 0
    by_id = {line["payload"]["message_id"]: line["payload"] for line in _mail_lines(lb)}
    attachment = by_id["m3@mail.example.org"]["attachments"][0]
    assert attachment["filename"] == "berth.jpg" and attachment["media_type"] == "image/jpeg"
    assert attachment["bytes"] == 2 + 256 * 4 and len(attachment["sha256"]) == 64
    assert "path" not in attachment
    assert not (lb.root / "attachments").exists() or not any((lb.root / "attachments").iterdir())
    assert by_id["m3@mail.example.org"]["body"] == "Hei."  # the part's last CRLF belongs to the boundary


def test_the_progress_line_says_fetched_new_and_already_in_the_record_never_a_total(
    lb: Logbook, server: FakeImap, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(mail_imap, "BATCH", 4)
    status, _out, err = _sync(capsys)
    assert status == 0
    progress = [line for line in err.splitlines() if "fetched" in line]
    assert progress, err
    assert progress[-1].strip().startswith(f"{ALL_MAIL}: 6 fetched, 6 new, 0 already in the record")
    assert " of " not in progress[-1] and "total" not in progress[-1]


def test_the_summary_names_each_folder_mark(
    lb: Logbook, server: FakeImap, capsys: pytest.CaptureFixture[str]
) -> None:
    status, out, _err = _sync(capsys)
    assert status == 0
    assert f"  {ALL_MAIL}: uidvalidity 1234, uid 6" in out


def test_the_parser_is_the_mbox_adapters_own(
    lb: Logbook, server: FakeImap, capsys: pytest.CaptureFixture[str]
) -> None:
    """One function parses both: the mbox adapter exposes it and the IMAP source calls it."""
    import inspect

    source = inspect.getsource(mail_imap)
    assert "mail.parse_message(" in source
    assert "def parse_message" not in source and "def _body(" not in source and "def leaves(" not in source


# -- doctor, sources, sync --all ----------------------------------------------------------------------


def test_doctor_shows_sync_mail_configured_or_unconfigured_by_name_only(
    lb: Logbook, server: FakeImap
) -> None:
    env = {
        "LOGBOOK_IMAP_HOST": "imap.example.org",
        "LOGBOOK_IMAP_USER": INES,
        "LOGBOOK_IMAP_PASSWORD": PASSWORD,
    }
    checks = {c.name: c for c in doctor.run(lb, {}, installed=lambda _m: True)}
    assert "sync:mail" not in checks, "no mail, no mark, no variable: the record does not use the source"
    checks = {c.name: c for c in doctor.run(lb, env, installed=lambda _m: True)}  # a variable set: it does
    assert checks["sync:mail"].status == "pass"
    assert (
        checks["sync:mail"].detail
        == "configured (LOGBOOK_IMAP_HOST, LOGBOOK_IMAP_USER, LOGBOOK_IMAP_PASSWORD)"
    )
    assert PASSWORD not in checks["sync:mail"].detail and INES not in checks["sync:mail"].detail
    checks = {
        c.name: c
        for c in doctor.run(lb, {"LOGBOOK_IMAP_HOST": "imap.example.org"}, installed=lambda _m: True)
    }
    assert checks["sync:mail"].status == "warn"
    assert checks["sync:mail"].detail == "set LOGBOOK_IMAP_USER and LOGBOOK_IMAP_PASSWORD"


def test_sources_lists_mail_as_file_and_live(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(["doctor", "sources"])
    rows = {line.split()[0]: line for line in capsys.readouterr().out.splitlines() if line.strip()}
    assert "file+live" in rows["mail"]


def test_sync_all_runs_mail_among_the_quick_sources(
    lb: Logbook, server: FakeImap, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from logbook.commands import sync

    order = [a.NAME for a in sync._all_order(adapters.live_adapters())]
    assert "mail" in order and order.index("mail") < order.index("immich")
    for adapter in adapters.live_adapters():
        if adapter.NAME != "mail":
            for name in adapter.ENV:
                monkeypatch.delenv(name, raising=False)
    try:
        cli.main(["sync", "--all"])
    except SystemExit as e:
        assert e.code == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert "mail: 6 new lines of 6 seen" in out
    assert any(line.split() == ["mail", "ok"] for line in out.splitlines())
    assert len(_mail_lines(lb)) == 6


def test_since_on_a_folder_with_nothing_from_that_day_marks_its_last_message(
    lb: Logbook, server: FakeImap, capsys: pytest.CaptureFixture[str]
) -> None:
    status, out, _err = _sync(capsys, "--since", "2026-05-01T00:00:00Z")
    assert status == 0 and "mail: 0 new lines of 0 seen" in out
    assert _marks(lb) == {ALL_MAIL: {"uidvalidity": 1234, "uid": 6}}, "UIDNEXT less one, not 0"
    server.folders[ALL_MAIL].messages[7] = _message(7, "m7@mail.example.org", hours=24.0 * 70)
    del server.commands[:]
    status, out, _err = _sync(capsys)
    assert status == 0 and "mail: 1 new lines of 1 seen" in out, "what came before the day stays unread"
    assert any("UID 7:*" in line for line in server.sent("SEARCH"))
    assert [line["payload"]["message_id"] for line in _mail_lines(lb)] == ["m7@mail.example.org"]


def test_since_with_nothing_from_that_day_leaves_a_folder_that_has_a_mark_as_it_was(
    lb: Logbook, server: FakeImap, capsys: pytest.CaptureFixture[str]
) -> None:
    del server.folders[ALL_MAIL].messages[6]
    _sync(capsys)
    assert _marks(lb) == {ALL_MAIL: {"uidvalidity": 1234, "uid": 5}}
    server.folders[ALL_MAIL].messages[6] = _message(6, "m6@mail.example.org", hours=72.0)
    status, out, _err = _sync(capsys, "--since", "2026-05-01T00:00:00Z")
    assert status == 0 and "mail: 0 new lines of 0 seen" in out
    assert _marks(lb) == {ALL_MAIL: {"uidvalidity": 1234, "uid": 5}}, "uid 6 is still the next run's"
    status, out, _err = _sync(capsys)
    assert status == 0 and "mail: 1 new lines of 1 seen" in out
