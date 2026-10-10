"""A record with 60-odd observed identities for 25 real people, for `people review`. Nobody here
exists: phone numbers are in the UK reserved range 07700 900xxx, emails at example.org, the owner
is Ines Nordmann of Oslo.

Twenty-five people, each a two-word name, an address and a number; what the record has resolved
of each decides which of their identities are *observed* and not yet placed:

- **A, 1 to 10**: the address book minted them from both the address and the number (`ios-contacts`).
  Mail from the address, messages from the number: everything they are seen as resolves. These are
  the canonical people whose `people` row a review must leave as it is.
- **B, 11 to 18**: a Takeout export minted them from the address only. Their messages come from the
  number — as a WhatsApp JID handle for 11 to 14, as a `+44` number for 15 to 18, who also get a reply
  from the owner in the direct chat — under their full display name, on the days their mail came.
  11 and 12 send no mail and are calendar attendees instead, the address spelled with capitals,
  which no resolution line carries as written. The observed numbers match a canonical person by
  name and by the days; the spelled addresses match by address.
- **C, 19 to 22**: the address book knows the number only. Their mail comes from the address, 19 and
  20 under three display names (`Maren Eide`, `Eide, Maren`, `maren eide`): one observed person
  each, by the strongest identifier.
- **D, 23 to 25**: nobody resolved them. Their mail and messages are observed and match no one.

One transcript names person 1 by address, person 19 as `M. Eide` with a provider id (an initial,
which the reader does not resolve by name) and person 23 of group D by name alone."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from circle import mail, message
from duplicates import resolution
from persona import attendee, event, transcript, utc

from logbook.core.store import Logbook

TZ = "Europe/Oslo"
OWNER = {"name": "Ines Nordmann", "email": "ines.nordmann@example.org", "phone": "+447700900100"}
NAMES = (
    "Kari Nordmann",
    "Ola Nordmann",
    "Per Hansen",
    "Liv Berg",
    "Anders Vik",
    "Sigrid Moen",
    "Nils Haug",
    "Marta Keller",
    "Jonas Weber",
    "Freja Lund",
    "Eva Nordmann",
    "Tore Dahl",
    "Ingrid Solberg",
    "Henrik Lie",
    "Astrid Bakke",
    "Magnus Strand",
    "Silje Haugen",
    "Erik Johansen",
    "Maren Eide",
    "Lars Vang",
    "Hanna Foss",
    "Simen Dale",
    "Thea Ronning",
    "Jakob Holm",
    "Nora Aas",
)
A, B, C, D = range(1, 11), range(11, 19), range(19, 23), range(23, 26)
SPELLED = {11: "Eva.Nordmann@example.org", 12: "Tore.Dahl@example.org"}  # as a calendar wrote them
THREE_NAMES = (19, 20)
TRANSCRIPT_SPEAKER = "granola:sp_19"
IOS, TAKEOUT = "ios-contacts", "google-takeout-contacts"


def person(n: int) -> dict[str, Any]:
    first, last = NAMES[n - 1].split()
    return {
        "n": n,
        "id": f"019cadd3-6bc0-7dcd-9133-0000000001{n:02d}",
        "name": NAMES[n - 1],
        "first": first,
        "email": f"{first.lower()}.{last.lower()}@example.org",
        "phone": f"+4477009001{n:02d}",
    }


PEOPLE = {n: person(n) for n in range(1, 26)}


def jid(p: dict[str, Any]) -> str:
    return f"{p['phone'][1:]}@s.whatsapp.net"


def day(n: int, k: int = 0) -> str:
    """Person `n`'s k-th day of June 2026, spread so that a few people share a day."""
    return f"2026-06-{(n + 3 * k - 1) % 27 + 1:02d}"


def clock(n: int, hour: int, k: int = 0) -> str:
    """A wall-clock minute of person `n`'s own, so no two mails share a stamp (a mail's raw id is
    its stamp here)."""
    return f"{hour:02d}:{(2 * n + k) % 60:02d}"


def spellings(p: dict[str, Any]) -> list[str]:
    first, last = p["name"].split()
    return [p["name"], f"{last}, {first}", p["name"].lower()]


def review_drafts(owner_id: str) -> list[dict[str, Any]]:
    """Every line, in a plausible import order: the resolutions, then the evidence."""
    drafts: list[dict[str, Any]] = [
        resolution(IOS, ("email", OWNER["email"]), owner_id, OWNER["name"]),
        resolution(IOS, ("phone", OWNER["phone"]), owner_id, OWNER["name"]),
    ]
    for n in A:
        p = PEOPLE[n]
        drafts.append(resolution(IOS, ("email", p["email"]), p["id"], p["name"]))
        drafts.append(resolution(IOS, ("phone", p["phone"]), p["id"], p["name"]))
    for n in B:
        p = PEOPLE[n]
        drafts.append(resolution(TAKEOUT, ("email", p["email"]), p["id"], p["name"]))
    for n in C:
        p = PEOPLE[n]
        drafts.append(resolution(IOS, ("phone", p["phone"]), p["id"], p["name"]))
    # the evidence: mail from the address, a message from the number, per person
    for n in (*A, *B, *D):
        if n in SPELLED:
            continue  # seen on the calendar only, spelled with capitals; never from the address itself
        p = PEOPLE[n]
        drafts.append(
            mail(
                utc(day(n), clock(n, 9)),
                {"name": p["name"], "email": p["email"]},
                OWNER,
                f"From {p['first']}",
            )
        )
    for n in C:
        p = PEOPLE[n]
        names = spellings(p) if n in THREE_NAMES else [p["name"]]
        for k, shown in enumerate(names):
            drafts.append(
                mail(
                    utc(day(n, k), clock(n, 9, k)),
                    {"name": shown, "email": p["email"]},
                    OWNER,
                    f"From {shown}",
                )
            )
    for n in (*A, *C, *D):
        p = PEOPLE[n]
        chat = (jid(p), "direct", p["first"])
        drafts.append(
            message(utc(day(n, 1), "18:00"), chat, "Hei!", {"name": p["first"], "phone": p["phone"]})
        )
    for n in B:
        p = PEOPLE[n]
        chat = (jid(p), "direct", p["first"])
        for k in (0, 1):
            m = message(
                utc(day(n, k), "18:00"), chat, f"Message {k}", {"name": p["name"], "phone": p["phone"]}
            )
            m["payload"]["sender"]["name"] = p["name"]  # the push name, the full name here
            if n in (11, 12, 13, 14):
                m["payload"]["sender"] = {"kind": "handle", "value": jid(p), "name": p["name"]}
            drafts.append(m)
        if n in (15, 16, 17, 18):
            drafts.append(message(utc(day(n, 1), "18:05"), chat, "Hei tilbake!"))
    # person 1's chat: the owner answers, so the messages run both ways
    kari = PEOPLE[1]
    drafts.append(message(utc(day(1, 1), "18:10"), (jid(kari), "direct", kari["first"]), "Ja!"))
    drafts.append(message(utc(day(1, 2), "18:10"), (jid(kari), "direct", kari["first"]), "Vi ses."))
    for n, spelled in SPELLED.items():
        p = PEOPLE[n]
        drafts.append(
            event(
                utc(day(n, 1), "14:00"),
                utc(day(n, 1), "15:00"),
                f"Meeting {n}",
                [attendee(spelled, p["name"])],
            )
        )
    drafts.append(
        event(
            utc(day(1, 2), "10:00"),
            utc(day(1, 2), "11:00"),
            "Planning",
            [attendee(kari["email"], kari["name"])],
        )
    )
    drafts.append(
        transcript(
            utc("2026-06-15", "10:00"),
            utc("2026-06-15", "11:00"),
            "Boat plans",
            [
                {"name": kari["name"], "email": kari["email"]},
                {"name": "M. Eide", "provider_id": TRANSCRIPT_SPEAKER},
                {"name": PEOPLE[23]["name"]},
                {"name": "me"},
            ],
        )
    )
    return drafts


def identities_seen(drafts: list[dict[str, Any]]) -> set[tuple[str, str, str]]:
    """Every (kind, value, display name) a counterpart is seen as, straight from the payloads: what
    a per-observation id would make a person of each."""
    seen: set[tuple[str, str, str]] = set()
    for draft in drafts:
        payload = draft["payload"]
        if draft["kind"] == "mail":
            seen.add(("email", payload["from"]["email"], payload["from"]["name"]))
        elif draft["kind"] == "message":
            sender = payload.get("sender")
            if sender is None:
                seen.add(("chat", payload["chat"]["id"], payload["chat"]["name"]))
            else:
                seen.add((sender["kind"], sender["value"], sender["name"]))
        elif draft["kind"] == "event":
            for a in payload["attendees"]:
                seen.add((a["ref"]["kind"], a["ref"]["value"], a["name"]))
        elif draft["kind"] == "transcript":
            for part in payload["participants"]:
                value = part.get("email") or part.get("provider_id") or part["name"]
                seen.add(("participant", value, part["name"]))
    return seen


def review_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """The record under `tmp_path`, found by every command through LOGBOOK_HOME, the UK dial
    prefix set so a number without a country code reads as one."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.setenv("LOGBOOK_DIAL_PREFIX", "44")
    lb.append_many(review_drafts(str(lb.meta["owner_id"])))
    return lb
