"""A record whose resolution lines name the same person twice or more, for `people merge`. Nobody
here exists: phone numbers are in the UK reserved range 07700 900xxx, emails at example.org.

Four people are duplicated across five sources, each by a different road:

- **Kari Nordmann**: `ios-contacts` minted her from her phone and address; an older chat import
  wrote her sender as a WhatsApp JID (`447700900101@s.whatsapp.net`), and the owner named that
  handle `Kari` by hand — a second entity for the same number (exact phone, E.164). A
  `whatsapp-contacts` alias of her linked-device id already points at the phone.
- **Per Hansen**: `google-takeout-contacts` minted him from `per.hansen@example.org`; the owner
  resolved a calendar attendee spelled `Per.Hansen@example.org` by hand (exact email, case
  aside); and an `ios-contacts` import run without `LOGBOOK_DIAL_PREFIX` minted a third from the
  number as entered, `07700900102` (exact phone once the prefix is known), with a
  `whatsapp-contacts` alias of a linked-device id hanging off that unnormalised number.
- **Liv Berg**: `ios-contacts` knows her as Liv Berg; a mail sender `liv@work.example.org` was named
  `Berg, Liv` by hand. Same name, and both come through mail (a shared channel).
- **Anders Vik**: `google-takeout-contacts` knows him; a transcript speaker, `granola:sp_7`, was
  named `A. Vik` by hand. An initial for a first name, and both come through transcripts.

The near misses that must stay separate: **Eva Nordmann** shares Kari's surname and the mail
channel; **Anna Hansen** and **Anne Hansen** are one letter apart and both on the calendar."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from circle import mail, message
from persona import attendee, event, transcript, utc

from logbook.core.store import Logbook

TZ = "Europe/Oslo"
OWNER = {"name": "Ines Nordmann", "email": "ines.nordmann@example.org", "phone": "+447700900100"}


def _id(n: int) -> str:
    return f"019cadd3-6bc0-7dcd-9133-0000000000d{n:01x}"


KARI_A, KARI_B = _id(1), _id(2)
PER_A, PER_B, PER_C = _id(3), _id(4), _id(5)
LIV_A, LIV_B = _id(6), _id(7)
ANDERS_A, ANDERS_B = _id(8), _id(9)
EVA, ANNA, ANNE = _id(10), _id(11), _id(12)

KARI_PHONE = "+447700900101"
KARI_JID = "447700900101@s.whatsapp.net"
KARI_LID = "236000000000101@lid"
KARI_EMAIL = "kari.nordmann@example.org"
PER_EMAIL = "per.hansen@example.org"
PER_EMAIL_SPELLED = "Per.Hansen@example.org"
PER_PHONE = "+447700900102"
PER_ENTERED = "07700900102"
PER_LID = "236000000000102@lid"
LIV_EMAIL = "liv.berg@example.org"
LIV_WORK = "liv@work.example.org"
ANDERS_EMAIL = "anders.vik@example.org"
ANDERS_SPEAKER = "granola:sp_7"
EVA_EMAIL = "eva.nordmann@example.org"
ANNA_EMAIL = "anna.hansen@example.org"
ANNE_EMAIL = "anne.hansen@example.org"

KARI_CHAT = (f"{KARI_PHONE[1:]}@s.whatsapp.net", "direct", "Kari")


def resolution(
    source: str,
    ref: tuple[str, str],
    entity_id: str,
    label: str,
    at: str = "2026-06-01T08:00:00Z",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "resolution/v1",
        "ref": {"kind": ref[0], "value": ref[1]},
        "entity": {"type": "person", "id": entity_id, "registry": "logbook"},
        "label": label,
        "method": "owner",
        "raw_id": f"{ref[0]}:{ref[1]}",
    }
    if extra:
        payload["extra"] = extra
    return {"at": at, "source": source, "kind": "resolution", "tier": 2, "payload": payload}


def alias(source: str, ref: tuple[str, str], of: tuple[str, str], label: str) -> dict[str, Any]:
    return {
        "at": "2026-06-02T08:00:00Z",
        "source": source,
        "kind": "resolution",
        "tier": 2,
        "payload": {
            "schema": "resolution/v1",
            "ref": {"kind": ref[0], "value": ref[1]},
            "alias_of": {"kind": of[0], "value": of[1]},
            "label": label,
            "method": "exact",
            "raw_id": f"alias:{ref[0]}:{ref[1]}",
        },
    }


def duplicate_drafts(owner_id: str) -> list[dict[str, Any]]:
    """Every line, in a plausible import order: the contacts, the hand-made resolutions, then
    the evidence each person is heard through."""
    ios, takeout, wa, manual = "ios-contacts", "google-takeout-contacts", "whatsapp-contacts", "manual"
    later = "2026-06-03T09:00:00Z"
    drafts: list[dict[str, Any]] = [
        resolution(ios, ("email", OWNER["email"]), owner_id, OWNER["name"]),
        resolution(ios, ("phone", OWNER["phone"]), owner_id, OWNER["name"]),
        # Kari: the phone and address from the phone's address book; the JID named by hand
        resolution(ios, ("phone", KARI_PHONE), KARI_A, "Kari Nordmann"),
        resolution(ios, ("email", KARI_EMAIL), KARI_A, "Kari Nordmann"),
        alias(wa, ("handle", KARI_LID), ("phone", KARI_PHONE), "Kari Nordmann"),
        resolution(manual, ("handle", KARI_JID), KARI_B, "Kari", at=later),
        # Per: Google, then the attendee by hand, then the phone as entered (no dial prefix)
        resolution(takeout, ("email", PER_EMAIL), PER_A, "Per Hansen"),
        resolution(takeout, ("phone", PER_PHONE), PER_A, "Per Hansen"),
        resolution(manual, ("email", PER_EMAIL_SPELLED), PER_B, "Per Hansen", at=later),
        resolution(ios, ("phone", PER_ENTERED), PER_C, "Per Hansen", extra={"unnormalised": True}),
        alias(wa, ("handle", PER_LID), ("phone", PER_ENTERED), "Per Hansen"),
        # Liv: the address book, and a work address named by hand
        resolution(ios, ("email", LIV_EMAIL), LIV_A, "Liv Berg"),
        resolution(ios, ("phone", "+447700900103"), LIV_A, "Liv Berg"),
        resolution(manual, ("email", LIV_WORK), LIV_B, "Berg, Liv", at=later),
        # Anders: Google, and a transcript speaker named by hand
        resolution(takeout, ("email", ANDERS_EMAIL), ANDERS_A, "Anders Vik"),
        resolution(manual, ("provider_id", ANDERS_SPEAKER), ANDERS_B, "A. Vik", at=later),
        # the near misses
        resolution(ios, ("email", EVA_EMAIL), EVA, "Eva Nordmann"),
        resolution(ios, ("email", ANNA_EMAIL), ANNA, "Anna Hansen"),
        resolution(takeout, ("email", ANNE_EMAIL), ANNE, "Anne Hansen"),
    ]
    kari = {"name": "Kari Nordmann", "phone": KARI_PHONE}
    drafts += [
        message(utc("2026-06-05", "08:15"), KARI_CHAT, "Lunch?", kari),
        message(utc("2026-06-05", "08:20"), KARI_CHAT, "Yes, at one."),
    ]
    jid_message = message(utc("2026-06-04", "19:00"), KARI_CHAT, "Back in town.", kari)
    jid_message["payload"]["sender"] = {"kind": "handle", "value": KARI_JID}
    drafts.append(jid_message)
    for day, sender in (
        ("2026-06-06", {"name": "Liv Berg", "email": LIV_EMAIL}),
        ("2026-06-08", {"name": "Liv Berg", "email": LIV_WORK}),
        ("2026-06-09", {"name": "Eva Nordmann", "email": EVA_EMAIL}),
        ("2026-06-10", {"name": "Kari Nordmann", "email": KARI_EMAIL}),
    ):
        drafts.append(mail(utc(day, "10:00"), sender, OWNER, f"From {sender['name']}"))
    drafts.append(
        event(
            utc("2026-06-11", "14:00"),
            utc("2026-06-11", "15:00"),
            "Planning",
            [attendee(PER_EMAIL, "Per Hansen"), attendee(ANNA_EMAIL, "Anna Hansen")],
        )
    )
    drafts.append(
        event(
            utc("2026-06-12", "14:00"),
            utc("2026-06-12", "15:00"),
            "Budget",
            [attendee(ANNE_EMAIL, "Anne Hansen")],
        )
    )
    drafts.append(
        transcript(
            utc("2026-06-15", "10:00"),
            utc("2026-06-15", "11:00"),
            "Boat plans",
            [{"name": "Anders Vik", "email": ANDERS_EMAIL}, {"name": "me"}],
        )
    )
    drafts.append(
        transcript(
            utc("2026-06-16", "10:00"),
            utc("2026-06-16", "11:00"),
            "Regatta",
            [{"name": "A. Vik", "provider_id": ANDERS_SPEAKER}, {"name": "me"}],
        )
    )
    return drafts


def duplicate_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """The record under `tmp_path`, found by every command through LOGBOOK_HOME, with the UK dial
    prefix set so a number entered without a country code reads as one."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.setenv("LOGBOOK_DIAL_PREFIX", "44")
    lb.append_many(duplicate_drafts(str(lb.meta["owner_id"])))
    return lb
