"""The Oslo persona's circle of twelve, for the people reader's tests. Nobody here exists.

On top of the persona's fortnight (`persona.persona_record`: Kari and Ola Nordmann, the stays, the
weekend aboard Solvind, the three nights in Zürich) the circle adds ten more people, resolved from
their addresses, and the channels a record hears them through: WhatsApp messages in a direct chat
and a group, calls answered and missed, mail received and sent, calendar entries timed and all-day,
a transcript, a tagged face, a birthday on a contact's resolution line, and one retracted message.
The owner, Ines Nordmann, is resolved too, so a reader has to leave her out. Phone numbers are in
the UK reserved range 07700 900xxx, emails at example.org."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from persona import KARI as PERSONA_KARI
from persona import (
    KARI_ID,
    OFFICE,
    OLA_ID,
    attendee,
    event,
    persona_record,
    photo,
    resolution,
    transcript,
    utc,
)
from persona import OLA as PERSONA_OLA

from logbook.core.store import Logbook

OWNER = {"name": "Ines Nordmann", "email": "ines.nordmann@example.org", "phone": "+447700900000"}
OLA = {"id": OLA_ID, "name": "Ola Nordmann", **PERSONA_OLA, "face": None}
KARI = {"id": KARI_ID, "name": "Kari Nordmann", **PERSONA_KARI}


def _person(n: int, name: str, face: str | None = None) -> dict[str, Any]:
    first, last = name.split()
    return {
        "id": f"019cadd3-6bc0-7dcd-9133-0000000000{n:02d}",
        "name": name,
        "email": f"{first.lower()}.{last.lower()}@example.org",
        "phone": f"+4477009000{n:02d}",
        "face": face,
    }


PER = _person(3, "Per Hansen")
LIV = _person(4, "Liv Berg")
ANDERS = _person(5, "Anders Vik", "p_05")
SIGRID = _person(6, "Sigrid Moen")
NILS = _person(7, "Nils Haug")
MARTA = _person(8, "Marta Keller")
JONAS = _person(9, "Jonas Weber")
FREJA = _person(10, "Freja Lund")
EVA = _person(11, "Eva Nordmann")
TORE = _person(12, "Tore Dahl")
TEN = (PER, LIV, ANDERS, SIGRID, NILS, MARTA, JONAS, FREJA, EVA, TORE)

OLA_BIRTHDAY = "1985-03-12"
OLA_CHAT = f"{OLA['phone'][1:]}@s.whatsapp.net"  # a direct chat: the JID is the phone number
CREW_CHAT = "120363000000000001@g.us"  # a group: the sender says who spoke, the owner's lines name nobody


def message(
    at: str, chat: tuple[str, str, str], text: str, sender: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A `message/v1` line as the whatsapp adapter writes it: `sender` only when it is not from me."""
    chat_id, chat_type, chat_name = chat
    payload: dict[str, Any] = {
        "schema": "message/v1",
        "raw_id": f"m-{at}-{chat_id}",
        "chat": {"id": chat_id, "type": chat_type, "name": chat_name},
        "from_me": sender is None,
        "text": text,
    }
    if sender is not None:
        payload["sender"] = {"kind": "phone", "value": sender["phone"], "name": sender["name"].split()[0]}
    return {"at": at, "source": "whatsapp", "kind": "message", "tier": 2, "payload": payload}


def call(at: str, person: dict[str, Any], incoming: bool, seconds: int) -> dict[str, Any]:
    """A `call/v1` line; `seconds` 0 is a call that was not answered."""
    return {
        "at": at,
        "source": "ios-calls",
        "kind": "call",
        "tier": 1,
        "payload": {
            "schema": "call/v1",
            "raw_id": f"c-{at}",
            "direction": "incoming" if incoming else "outgoing",
            "answered": seconds > 0,
            "duration_s": seconds,
            "counterparty": {"kind": "phone", "value": person["phone"]},
            "service": "cellular",
        },
    }


def mail(at: str, sender: dict[str, Any], to: dict[str, Any], subject: str) -> dict[str, Any]:
    """A `mail/v1` line; `direction` follows the sender as the mail adapter sets it."""
    message_id = f"{at}@mail.example.org"
    return {
        "at": at,
        "source": "mail",
        "kind": "mail",
        "tier": 2,
        "payload": {
            "schema": "mail/v1",
            "raw_id": f"{OWNER['email']}:{message_id}",
            "message_id": message_id,
            "thread": message_id,
            "from": {"email": sender["email"], "name": sender["name"]},
            "to": [{"email": to["email"], "name": to["name"]}],
            "subject": subject,
            "direction": "sent" if sender is OWNER else "received",
            "size": 1200,
        },
    }


def circle_drafts(owner_id: str) -> list[dict[str, Any]]:
    """Every line the circle adds to the fortnight, in a plausible import order."""
    drafts: list[dict[str, Any]] = [
        resolution(("email", OWNER["email"]), owner_id, OWNER["name"]),
        resolution(("phone", OWNER["phone"]), owner_id, OWNER["name"]),
    ]
    for p in TEN:
        drafts.append(resolution(("email", p["email"]), p["id"], p["name"]))
        drafts.append(resolution(("phone", p["phone"]), p["id"], p["name"]))
        if p["face"]:
            drafts.append(resolution(("provider_id", f"immich:{p['face']}"), p["id"], p["name"]))
    # Ola's contact card carries a birthday: a later resolution of the phone, last standing for it.
    with_birthday = resolution(("phone", OLA["phone"]), OLA_ID, "Ola Nordmann")
    with_birthday["at"] = "2026-06-02T08:00:00Z"
    with_birthday["source"] = "ios-contacts"
    with_birthday["payload"]["extra"] = {"birthday": OLA_BIRTHDAY}
    drafts.append(with_birthday)
    # Messages: a direct chat with Ola (three from me, two from Ola), the crew group (Anders and
    # Sigrid spoke; the owner's two lines in a group name nobody).
    direct = (OLA_CHAT, "direct", "Ola")
    crew = (CREW_CHAT, "group", "Crew")
    drafts += [
        message(utc("2026-06-09", "08:15"), direct, "Boat this weekend?"),
        message(utc("2026-06-09", "08:20"), direct, "Yes! Saturday.", OLA),
        message(utc("2026-06-12", "17:00"), direct, "Marina at nine."),
        message(utc("2026-06-14", "18:00"), direct, "Thanks for a great weekend.", OLA),
        message(utc("2026-06-14", "18:05"), direct, "Likewise."),
        message(utc("2026-06-11", "09:00"), crew, "Who is in for the regatta?"),
        message(utc("2026-06-11", "09:10"), crew, "Count me in.", ANDERS),
        message(utc("2026-06-11", "09:30"), crew, "Me too.", SIGRID),
        message(utc("2026-06-11", "09:40"), crew, "Great."),
    ]
    # Calls: Eva, answered, from the hotel in Zürich; Per, not answered.
    drafts.append(call(utc("2026-06-17", "20:00"), EVA, True, 25 * 60))
    drafts.append(call(utc("2026-06-12", "12:00"), PER, False, 0))
    # Mail: Nils's newsletter received; a mail the owner sent Marta.
    drafts.append(mail(utc("2026-06-19", "07:00"), NILS, OWNER, "Club news, June"))
    drafts.append(mail(utc("2026-06-09", "16:00"), OWNER, MARTA, "Draft contract"))
    # Calendar: Liv at a timed review at the office (confirmed company); Jonas on an all-day
    # workshop with no place (a channel, never a day together); Tore declined.
    drafts.append(
        event(
            utc("2026-06-09", "14:00"),
            utc("2026-06-09", "16:00"),
            "Review",
            [attendee(LIV["email"], "Liv Berg"), attendee(TORE["email"], "Tore Dahl", response="declined")],
        )
    )
    workshop = event(
        utc("2026-06-12", "00:00"), utc("2026-06-13", "00:00"), "Workshop", [attendee(JONAS["email"])]
    )
    workshop["payload"]["all_day"] = True
    drafts.append(workshop)
    # A transcript at the office with Freja; Anders's face in a photo at the anchorage.
    drafts.append(
        transcript(
            utc("2026-06-19", "10:00"),
            utc("2026-06-19", "11:00"),
            "Client call",
            [{"name": "Freja Lund", "email": FREJA["email"]}, {"name": "me"}],
        )
    )
    drafts.append(photo(utc("2026-06-13", "20:00"), (59.8500, 10.6000), people=[ANDERS["face"]]))
    drafts.append(photo(utc("2026-06-10", "12:45"), OFFICE, people=[KARI["face"]]))
    return drafts


RETRACTED_TEXT = "Wrong group, sorry."


def circle_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """The persona's fortnight and the circle's lines in a fresh record under `tmp_path`, with the
    owner's aliases in `policy/owner.json` and Sigrid's second group message retracted."""
    lb = persona_record(tmp_path, monkeypatch)
    lb.append_many(circle_drafts(str(lb.meta["owner_id"])))
    stray = lb.append(
        at=utc("2026-06-20", "09:00"),
        source="whatsapp",
        kind="message",
        tier=2,
        payload=message(utc("2026-06-20", "09:00"), (CREW_CHAT, "group", "Crew"), RETRACTED_TEXT, SIGRID)[
            "payload"
        ],
    )
    lb.retract(int(stray["seq"]), "not a message of the owner's", at=utc("2026-06-20", "09:30"))
    policy = lb.root / "policy"
    policy.mkdir(exist_ok=True)
    (policy / "owner.json").write_text(
        json.dumps({"names": [OWNER["name"]], "emails": [OWNER["email"]], "phones": [OWNER["phone"]]}),
        encoding="utf-8",
    )
    return lb


__all__ = ["KARI", "KARI_ID", "OLA", "OLA_ID", "TEN", "circle_record"]
