"""People's mail (RFC 0045): a mail is a person's when someone the record names as a person is on it,
the sender of a mail received or a recipient of a mail sent; bots, agents and no-reply addresses are not
people; `logbook people mail` counts and never prints an address; `replies_owed` reads people's mail,
direct messages and calls. Every string here is synthetic; the people live in Oslo and do not exist."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.core import peoples_mail
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
OWNER_EMAIL = "ines@example.org"
KARI, PER, HARBOUR = (
    "019cadd3-6bc0-7dcd-9133-043f5aabf2a1",
    "019cadd3-6bc0-7dcd-9133-043f5aabf2a2",
    "019cadd3-6bc0-7dcd-9133-043f5aabf2a3",
)
KARI_EMAIL, PER_EMAIL, HARBOUR_EMAIL = "kari@example.org", "per@example.org", "harbour@example.org"
KARI_PHONE, PER_PHONE = "+447700900101", "+447700900102"
NO_REPLY_EMAIL = "no-reply@harbour.example.org"
STRANGER_EMAIL = "someone@example.org"
ADDRESSES = (OWNER_EMAIL, KARI_EMAIL, PER_EMAIL, HARBOUR_EMAIL, NO_REPLY_EMAIL, STRANGER_EMAIL)


def _resolution(kind: str, value: str, label: str, entity: str, type_: str = "person") -> dict[str, Any]:
    return {
        "at": "2026-02-01T09:00:00Z",
        "source": "ios-contacts",
        "kind": "resolution",
        "tier": 2,
        "payload": {
            "schema": "resolution/v1",
            "ref": {"kind": kind, "value": value},
            "entity": {"type": type_, "id": entity, "registry": "logbook"},
            "label": label,
            "method": "exact",
        },
    }


def _mail(
    at: str,
    sender: str,
    to: list[str],
    direction: str = "received",
    extra: dict[str, Any] | None = None,
    thread: str | None = None,
    cc: list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "mail/v1",
        "raw_id": f"m-{at}@mail.example.org",
        "thread": thread or f"m-{at}@mail.example.org",
        "subject": "Mooring for the weekend",
        "direction": direction,
        "from": {"email": sender},
        "to": [{"email": a} for a in to],
        "size": 1024,
    }
    if cc:
        payload["cc"] = [{"email": a} for a in cc]
    if extra is not None:
        payload["extra"] = extra
    return {"at": at, "source": "mail", "kind": "mail", "tier": 2, "payload": payload}


def _message(
    at: str, chat: str, from_me: bool, phone: str, kind: str = "direct", **extra: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "message/v1",
        "raw_id": f"wa:{at}",
        "chat": {"id": chat, "type": kind, "name": "Kari"},
        "from_me": from_me,
        "text": "are you coming to the boat on Saturday?",
    }
    if not from_me:
        payload["sender"] = {"kind": "phone", "value": phone}
    if extra:
        payload["extra"] = extra
    return {"at": at, "source": "whatsapp", "kind": "message", "tier": 2, "payload": payload}


def _call(at: str, phone: str, direction: str, answered: bool) -> dict[str, Any]:
    return {
        "at": at,
        "source": "ios-calls",
        "kind": "call",
        "tier": 2,
        "payload": {
            "schema": "call/v1",
            "raw_id": f"call:{at}",
            "direction": direction,
            "answered": answered,
            "duration_s": 60 if answered else 0,
            "counterparty": {"kind": "phone", "value": phone},
        },
    }


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """Kari and Per are people the record names (an address and a phone each); the harbour's address
    resolves to a company; the owner is Ines, by her address."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.set_owner_emails([OWNER_EMAIL])
    lb.append_many(
        [
            _resolution("email", KARI_EMAIL, "Kari Nordmann", KARI),
            _resolution("phone", KARI_PHONE, "Kari Nordmann", KARI),
            _resolution("email", PER_EMAIL, "Per Hansen", PER),
            _resolution("phone", PER_PHONE, "Per Hansen", PER),
            _resolution("email", HARBOUR_EMAIL, "Oslo Harbour", HARBOUR, type_="company"),
        ]
    )
    return lb


def _classes(lb: Logbook, first: str = "2026-03-01", last: str = "2026-03-01") -> list[tuple[str, Any]]:
    report = peoples_mail.read(lb, first, last)
    return [(c.cls, c.people if c.person else c.reason) for c in report.mails]


# -- the rule ---------------------------------------------------------------------------------------------


def test_a_mail_from_a_person_the_record_names_is_a_persons_mail(lb: Logbook) -> None:
    lb.append(**_mail("2026-03-01T09:00:00Z", KARI_EMAIL, [OWNER_EMAIL]))
    assert _classes(lb) == [("person", (KARI,))]


def test_a_mail_sent_to_a_person_is_a_persons_mail_and_names_every_person_on_it(lb: Logbook) -> None:
    lb.append(
        **_mail("2026-03-01T09:00:00Z", OWNER_EMAIL, [HARBOUR_EMAIL, PER_EMAIL], "sent", cc=[KARI_EMAIL])
    )
    assert _classes(lb) == [("person", (PER, KARI))]


def test_a_mail_from_a_no_reply_address_is_never_a_person_whatever_resolves(lb: Logbook) -> None:
    """Even when a resolution names the no-reply address as a person, the pattern list wins."""
    lb.append(**_resolution("email", NO_REPLY_EMAIL, "Harbour office", PER))
    lb.append(**_mail("2026-03-01T09:00:00Z", NO_REPLY_EMAIL, [OWNER_EMAIL]))
    lb.append(**_mail("2026-03-01T10:00:00Z", "NoReply+bills@harbour.example.org", [OWNER_EMAIL]))
    assert _classes(lb) == [("other", "no_reply"), ("other", "no_reply")]


def test_a_mail_an_agent_wrote_is_an_agents_whoever_it_names(lb: Logbook) -> None:
    lb.append(**_mail("2026-03-01T09:00:00Z", KARI_EMAIL, [OWNER_EMAIL], extra={"machine": True}))
    counterpart = {"counterpart": {"kind": "agent", "ref": {"kind": "handle", "value": "skipper-bot"}}}
    lb.append(**_mail("2026-03-01T10:00:00Z", OWNER_EMAIL, [KARI_EMAIL], "sent", extra=counterpart))
    assert _classes(lb) == [("other", "agent"), ("other", "agent")]


def test_a_newsletters_list_headers_from_a_person_leave_it_a_persons_mail(lb: Logbook) -> None:
    """`extra.list` and `extra.gmail_category` (#341) are evidence the reader shows, never a rule."""
    extra = {"list": True, "gmail_category": "promotions"}
    lb.append(**_mail("2026-03-01T09:00:00Z", PER_EMAIL, [OWNER_EMAIL], extra=extra))
    report = peoples_mail.read(lb, "2026-03-01", "2026-03-01")
    (classed,) = report.mails
    assert classed.person and classed.people == (PER,)
    assert classed.evidence == {"gmail_category": "promotions", "list": True}


def test_a_mail_with_nobody_resolved_on_it_is_other_mail(lb: Logbook) -> None:
    lb.append(**_mail("2026-03-01T09:00:00Z", STRANGER_EMAIL, [OWNER_EMAIL]))
    lb.append(**_mail("2026-03-01T10:00:00Z", HARBOUR_EMAIL, [OWNER_EMAIL]))  # a company
    lb.append(**_mail("2026-03-01T11:00:00Z", STRANGER_EMAIL, [OWNER_EMAIL], cc=[KARI_EMAIL]))  # cc only
    lb.append(**_mail("2026-03-01T12:00:00Z", OWNER_EMAIL, [HARBOUR_EMAIL], "sent"))
    assert _classes(lb) == [("other", "no_person")] * 4


def test_an_address_meets_its_person_whatever_its_case(lb: Logbook) -> None:
    lb.append(**_mail("2026-03-01T09:00:00Z", " Kari@Example.ORG ", [OWNER_EMAIL]))
    assert _classes(lb) == [("person", (KARI,))]


def test_a_mail_with_no_direction_is_sent_when_it_is_from_the_owner(lb: Logbook) -> None:
    sent = _mail("2026-03-01T09:00:00Z", OWNER_EMAIL, [KARI_EMAIL])
    received = _mail("2026-03-01T10:00:00Z", PER_EMAIL, [OWNER_EMAIL])
    for line in (sent, received):
        del line["payload"]["direction"]
        lb.append(**line)
    report = peoples_mail.read(lb, "2026-03-01", "2026-03-01")
    assert [(c.direction, c.people) for c in report.mails] == [("sent", (KARI,)), ("received", (PER,))]


def test_a_sender_let_go_in_hold_is_never_a_persons_mail(lb: Logbook) -> None:
    """The hook of RFC 0045 §4: until Hold writes fates the set is empty and removes nothing."""
    line = lb.append(**_mail("2026-03-01T09:00:00Z", PER_EMAIL, [OWNER_EMAIL]))
    with lb.index() as idx:
        marks, resolutions = idx.retractions(), idx.resolutions()
    assert peoples_mail.Rule.of(lb, marks, resolutions).classify(line).person
    by_address = peoples_mail.Rule.of(lb, marks, resolutions, let_go=frozenset({("email", PER_EMAIL)}))
    by_domain = peoples_mail.Rule.of(lb, marks, resolutions, let_go=frozenset({("domain", "example.org")}))
    assert by_address.classify(line).reason == "let_go"
    assert by_domain.classify(line).reason == "let_go"


def test_a_retracted_mail_and_one_outside_the_window_are_not_read(lb: Logbook) -> None:
    line = lb.append(**_mail("2026-03-01T09:00:00Z", KARI_EMAIL, [OWNER_EMAIL]))
    lb.append(**_mail("2026-03-02T09:00:00Z", KARI_EMAIL, [OWNER_EMAIL]))
    lb.append(
        at="2026-03-03T09:00:00Z",
        source="manual",
        kind="retraction",
        tier=1,
        payload={"schema": "retraction/v1", "supersedes": line["id"], "seq": line["seq"], "reason": "a test"},
    )
    assert _classes(lb) == []
    assert _classes(lb, "2026-03-01", "2026-03-02") == [("person", (KARI,))]


def test_the_counts(lb: Logbook) -> None:
    lb.append(**_mail("2026-03-01T09:00:00Z", KARI_EMAIL, [OWNER_EMAIL]))
    lb.append(**_mail("2026-03-01T10:00:00Z", OWNER_EMAIL, [KARI_EMAIL, PER_EMAIL], "sent"))
    lb.append(**_mail("2026-03-01T11:00:00Z", NO_REPLY_EMAIL, [OWNER_EMAIL]))
    lb.append(**_mail("2026-03-01T12:00:00Z", STRANGER_EMAIL, [OWNER_EMAIL]))
    counts = peoples_mail.read(lb, "2026-03-01", "2026-03-01").counts()
    assert counts == {
        "mail": 4,
        "person": 2,
        "received": 1,
        "sent": 1,
        "people": 2,
        "other": 2,
        "by_reason": {"no_person": 1, "no_reply": 1, "agent": 0, "let_go": 0, "sealed": 0},
    }


# -- the command ------------------------------------------------------------------------------------------


def _cli(*args: str) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cli.main(["people", "mail", *args])
    return out.getvalue()


def _a_day_of_mail(lb: Logbook) -> None:
    lb.append(**_mail("2026-03-01T09:00:00Z", KARI_EMAIL, [OWNER_EMAIL]))
    lb.append(**_mail("2026-03-01T10:00:00Z", OWNER_EMAIL, [PER_EMAIL], "sent"))
    lb.append(**_mail("2026-03-01T11:00:00Z", NO_REPLY_EMAIL, [OWNER_EMAIL]))
    lb.append(**_mail("2026-03-01T12:00:00Z", HARBOUR_EMAIL, [OWNER_EMAIL]))


def test_the_command_prints_counts_and_never_an_address_or_a_name(lb: Logbook) -> None:
    _a_day_of_mail(lb)
    text = _cli("--since", "2026-03-01", "--until", "2026-03-01")
    assert "people's mail: 2" in text and "other mail: 2" in text
    assert "@" not in text
    for word in (*ADDRESSES, "Kari", "Per", "Hansen", "Nordmann", "Harbour", "harbour", KARI, PER):
        assert word not in text


def test_the_json_carries_person_ids_and_never_an_address(lb: Logbook) -> None:
    _a_day_of_mail(lb)
    lb.append(
        **_mail("2026-03-01T13:00:00Z", PER_EMAIL, [OWNER_EMAIL], extra={"list": {"id": "club@example.org"}})
    )
    text = _cli("--since", "2026-03-01", "--until", "2026-03-01", "--json")
    data = json.loads(text)
    assert data["counts"]["person"] == 3 and data["counts"]["other"] == 2
    assert [m["class"] for m in data["mails"]] == ["person", "person", "other", "other", "person"]
    assert data["mails"][0]["people"] == [KARI] and data["mails"][2]["reason"] == "no_reply"
    assert data["mails"][4]["evidence"] == {"list": True}
    assert "@" not in text and "Kari" not in text


def test_the_command_refuses_a_bad_day(lb: Logbook) -> None:
    with pytest.raises(SystemExit) as e:
        _cli("--since", "1 March")
    assert e.value.code == 2


def test_since_and_until_go_with_people_mail_only(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    """`people mail` is a verb of `people`, no command of its own; its window is refused elsewhere."""
    with pytest.raises(SystemExit) as e:
        cli.main(["people", "--since", "2026-03-01"])
    assert e.value.code == 2
    assert "--since and --until go with `people mail`" in capsys.readouterr().err


def test_people_mail_shares_until_with_who_was_there_and_refuses_its_from_and_to(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--until` is one option of `people`: who was there's (lives-with) and the mail window's last day."""
    lb.append(**_mail("2026-03-01T09:00:00Z", KARI_EMAIL, [OWNER_EMAIL]))
    lb.append(**_mail("2026-03-02T09:00:00Z", KARI_EMAIL, [OWNER_EMAIL]))
    assert "2026-03-01: 1 line" in _cli("--since", "2026-03-01", "--until", "2026-03-01")
    for flag in ("--from", "--to"):
        with pytest.raises(SystemExit) as e:
            _cli(flag, "2026-03-01")
        assert e.value.code == 2
        assert "--from and --to are not its window" in capsys.readouterr().err


# -- replies owed (RFC 0043 §4.5) ------------------------------------------------------------------------


def _owed(lb: Logbook, day: str) -> list[tuple[str, tuple[str, ...]]]:
    return [(o.person, o.lines) for o in peoples_mail.replies_owed(lb, day)]


def test_a_message_from_a_person_unanswered_for_over_a_week_is_a_reply_owed(lb: Logbook) -> None:
    first = lb.append(**_message("2026-03-01T09:00:00Z", "kari-chat", False, KARI_PHONE))
    second = lb.append(**_message("2026-03-01T09:05:00Z", "kari-chat", False, KARI_PHONE))
    assert _owed(lb, "2026-03-09") == [(KARI, (first["id"], second["id"]))]


def test_a_reply_under_a_week_old_is_not_owed_yet(lb: Logbook) -> None:
    lb.append(**_message("2026-03-01T09:00:00Z", "kari-chat", False, KARI_PHONE))
    assert _owed(lb, "2026-03-08") == []  # a week to the day is not older than a week
    assert _owed(lb, "2026-03-02") == []


def test_when_the_last_word_is_the_owners_no_reply_is_owed(lb: Logbook) -> None:
    lb.append(**_message("2026-03-01T09:00:00Z", "kari-chat", False, KARI_PHONE))
    lb.append(**_message("2026-03-01T10:00:00Z", "kari-chat", True, KARI_PHONE))
    lb.append(**_mail("2026-03-01T11:00:00Z", PER_EMAIL, [OWNER_EMAIL], thread="t-per"))
    lb.append(**_mail("2026-03-02T11:00:00Z", OWNER_EMAIL, [PER_EMAIL], "sent", thread="t-per"))
    assert _owed(lb, "2026-03-20") == []


def test_a_call_back_answers_a_message_and_a_missed_call_is_their_word(lb: Logbook) -> None:
    lb.append(**_message("2026-03-01T09:00:00Z", "kari-chat", False, KARI_PHONE))
    lb.append(**_call("2026-03-01T18:00:00Z", KARI_PHONE, "outgoing", answered=True))
    missed = lb.append(**_call("2026-03-01T19:00:00Z", PER_PHONE, "incoming", answered=False))
    assert _owed(lb, "2026-03-20") == [(PER, (missed["id"],))]


def test_replies_owed_read_peoples_mail_only_and_never_a_group_or_an_agent(lb: Logbook) -> None:
    mail = lb.append(**_mail("2026-03-01T09:00:00Z", KARI_EMAIL, [OWNER_EMAIL]))
    lb.append(**_mail("2026-03-01T09:30:00Z", NO_REPLY_EMAIL, [OWNER_EMAIL]))
    lb.append(**_mail("2026-03-01T09:40:00Z", HARBOUR_EMAIL, [OWNER_EMAIL]))
    lb.append(**_message("2026-03-01T10:00:00Z", "club@g.us", False, PER_PHONE, kind="group"))
    lb.append(**_message("2026-03-01T11:00:00Z", "bot-chat", False, PER_PHONE, machine=True))
    assert _owed(lb, "2026-03-20") == [(KARI, (mail["id"],))]


def test_replies_owed_ignore_what_came_after_the_day(lb: Logbook) -> None:
    owed = lb.append(**_message("2026-03-01T09:00:00Z", "kari-chat", False, KARI_PHONE))
    lb.append(**_message("2026-03-25T09:00:00Z", "kari-chat", True, KARI_PHONE))
    assert _owed(lb, "2026-03-20") == [(KARI, (owed["id"],))]
    assert _owed(lb, "2026-03-25") == []


def test_replies_owed_read_through_the_gate(lb: Logbook) -> None:
    """`tiers` is the page's gate: a line above it is no word, and a person a resolution above it
    names is nobody the reader can name, so no reply is owed through a gate of tier 1."""
    owed = lb.append(**_message("2026-03-01T09:00:00Z", "kari-chat", False, KARI_PHONE))
    assert [(o.person, o.lines) for o in peoples_mail.replies_owed(lb, "2026-03-20", [1, 2])] == [
        (KARI, (owed["id"],))
    ]
    assert peoples_mail.replies_owed(lb, "2026-03-20", [1]) == []
    loud = _message("2026-03-02T09:00:00Z", "kari-chat", True, KARI_PHONE)
    loud["tier"] = 3  # the owner's answer, above a gate of 1 and 2: the gate does not see it
    lb.append(**loud)
    assert peoples_mail.replies_owed(lb, "2026-03-20") == []
    assert [o.person for o in peoples_mail.replies_owed(lb, "2026-03-20", [1, 2])] == [KARI]


def test_a_sealed_mail_this_machine_cannot_open_is_said_and_never_called_nobodys(lb: Logbook) -> None:
    """A reader without the key lists the line and says so (`Logbook.opened`): `sealed`, not `no_person`."""
    line = {
        "id": "019cadd3-6bc0-7dcd-9133-0000000000aa",
        "at": "2026-03-01T09:00:00Z",
        "kind": "mail",
        "payload": {"schema": "sealed/v1", "of": "mail/v1", "digest": "a" * 64},
    }
    with lb.index() as idx:
        rule = peoples_mail.Rule.of(lb, idx.retractions(), idx.resolutions())
    classed = rule.classify(line)
    assert classed.cls == "other" and classed.reason == "sealed"


def test_a_domain_let_go_meets_its_sender_whatever_the_case(lb: Logbook) -> None:
    line = lb.append(**_mail("2026-03-01T09:00:00Z", "Per@Example.ORG", [OWNER_EMAIL]))
    with lb.index() as idx:
        marks, resolutions = idx.retractions(), idx.resolutions()
    rule = peoples_mail.Rule.of(lb, marks, resolutions, let_go=frozenset({("domain", "example.org")}))
    assert rule.classify(line).reason == "let_go"


def test_a_sender_resolved_to_an_agent_is_an_agents_mail(lb: Logbook) -> None:
    lb.append(**_resolution("email", "skipper@example.org", "Skipper", PER, type_="agent"))
    lb.append(**_mail("2026-03-01T09:00:00Z", "skipper@example.org", [OWNER_EMAIL]))
    assert _classes(lb) == [("other", "agent")]
