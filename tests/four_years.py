"""Four synthetic years of the Oslo persona's acquaintances, for `people drift`, `people nearby` and
the Day's anniversaries. Nobody here exists.

Ines Nordmann lives in Oslo. From 2022 to 2025 the record holds 25 canonical people (a resolution
line for each address and number), days together in three cities (Oslo at home, Bergen and
Trondheim, each a dwell of the owner's points with a timed calendar entry the person attended held
at the stay), WhatsApp messages in direct chats and in a group, calls answered and missed, mail, a
meeting by video, a transcript, and one person the sources saw and the record never named (Sindre
Holm, an attendee with no resolution line): observed, never canonical. In December 2025 the owner
plans a flight to Bergen and a dinner in Trondheim. Emails are at example.org, phone numbers in the
UK reserved range 07700 900xxx, the airline is XY."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from persona import attendee, dwell, event, transcript, travel, utc
from persona import resolution as _resolution

from logbook.core.store import Logbook

TZ = "Europe/Oslo"
OSLO = (59.9139, 10.7522)  # home
BERGEN = (60.3913, 5.3221)
TRONDHEIM = (63.4305, 10.3951)
LAST_DAY = "2025-12-31"

OWNER = {"name": "Ines Nordmann", "email": "ines.nordmann@example.org", "phone": "+447700900100"}

NAMES = (
    "Astrid Bakke",  # A: 24 days in Bergen in 2022, nothing since: drifted
    "Bjørn Lie",  # B: 22 days in Trondheim in 2023, a direct message in March 2024: drifted
    "Camilla Strand",  # C: 21 days in Oslo in 2022, a call answered in June 2025: not drifted
    "Dag Solberg",  # D: 22 days in Bergen in 2023, then only mail: drifted
    "Elin Moe",  # E: 25 days in Oslo in 2022, then only lines in a group: drifted
    "Frode Berg",  # F: 20 days in Oslo in 2025: recent
    "Guro Lund",  # G: 19 days in Oslo in 2022: under the default floor
    "Hans Nilsen",  # H: about ten days a year, three years: no year reaches the floor
    "Ingrid Aas",  # I: 20 days in Bergen in 2022, a timed meeting by video in September 2025
    "Jon Eide",  # J: 21 days in Trondheim in 2023, a transcript in August 2025
    "Kristin Haugen",  # K..P: a day in Trondheim on 14 October 2024, K on 3 November 2024 too
    "Lars Dahl",
    "Mona Vik",
    "Nils Foss",
    "Oda Brekke",
    "Petter Lunde",
    "Randi Hovland",  # Q..Y: a day in Oslo in 2025 and a direct message
    "Sverre Myhre",
    "Tone Hagen",
    "Ulf Sæther",
    "Vigdis Holen",
    "Willy Tangen",
    "Åse Bjerke",
    "Øystein Ruud",
    "Yngve Kvam",
)
OBSERVED = {"name": "Sindre Holm", "email": "sindre.holm@example.org"}  # never resolved


def _person(n: int, name: str) -> dict[str, Any]:
    first, last = name.split()
    plain = {"ø": "o", "å": "a", "æ": "ae"}
    mail = "".join(plain.get(c, c) for c in f"{first}.{last}".lower())
    return {
        "id": f"019cadd3-6bc0-7dcd-9133-0000000001{n:02d}",
        "name": name,
        "email": f"{mail}@example.org",
        "phone": f"+4477009001{n:02d}",
    }


PEOPLE = [_person(n + 1, name) for n, name in enumerate(NAMES)]
BY_NAME = {p["name"]: p for p in PEOPLE}
ASTRID, BJORN, CAMILLA, DAG, ELIN, FRODE, GURO, HANS, INGRID, JON = PEOPLE[:10]
KRISTIN = PEOPLE[10]
SIX = PEOPLE[10:16]  # a day together in Trondheim on 14 October 2024
LATER = PEOPLE[16:]


def days(start: str, n: int, step: int = 3) -> list[str]:
    first = date.fromisoformat(start)
    return [(first + timedelta(days=i * step)).isoformat() for i in range(n)]


A_DAYS = days("2022-01-03", 24)  # Bergen; Ingrid on the first 20
E_DAYS = days("2022-04-01", 25)  # Oslo; Camilla the first 21, Guro the first 19, Hans the first 10
B_DAYS = days("2023-01-05", 22)  # Trondheim; Jon the first 21
D_DAYS = days("2023-05-02", 22)  # Bergen
H_2023 = days("2023-08-01", 10)  # Oslo
H_2024 = days("2024-02-01", 10)  # Oslo
F_DAYS = days("2025-01-06", 20)  # Oslo
LATER_DAYS = days("2025-04-02", 5, step=4)  # Oslo, two of Q..Y on each, the last one alone
A_YEAR_BEFORE = "2024-10-14"  # Trondheim: Kristin and five more — the day a year before 2025-10-14
KH = "2024-11-03"  # Trondheim: Kristin
HANS_3Y = "2022-11-03"  # Oslo: Hans and Sindre, observed — three years before 2025-11-03


def resolution(ref: tuple[str, str], entity_id: str, label: str) -> dict[str, Any]:
    """The persona's resolution line, dated at the start of the four years."""
    line = _resolution(ref, entity_id, label)
    line["at"] = "2022-01-01T08:00:00Z"
    return line


def _together(day: str, where: tuple[float, float], who: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The owner at `where` from 10:00 to 17:00 and a timed entry from 11:00 to 14:00, no location,
    the people attending: held at the stay, a day together for each."""
    out = dwell(day, "10:00", "17:00", where, every_min=20, noise_m=20)
    out.append(
        event(
            utc(day, "11:00"),
            utc(day, "14:00"),
            "Lunch",
            [attendee(p["email"], p["name"]) for p in who],
        )
    )
    return out


def message(
    at: str, chat: tuple[str, str], text: str, sender: dict[str, Any] | None = None
) -> dict[str, Any]:
    chat_id, chat_type = chat
    payload: dict[str, Any] = {
        "schema": "message/v1",
        "raw_id": f"m-{at}-{chat_id}",
        "chat": {"id": chat_id, "type": chat_type, "name": "Chat"},
        "from_me": sender is None,
        "text": text,
    }
    if sender is not None:
        payload["sender"] = {"kind": "phone", "value": sender["phone"], "name": sender["name"].split()[0]}
    return {"at": at, "source": "whatsapp", "kind": "message", "tier": 2, "payload": payload}


def direct(p: dict[str, Any]) -> tuple[str, str]:
    return (f"{p['phone'][1:]}@s.whatsapp.net", "direct")


GROUP = ("120363000000000009@g.us", "group")


def call(at: str, p: dict[str, Any], seconds: int) -> dict[str, Any]:
    return {
        "at": at,
        "source": "ios-calls",
        "kind": "call",
        "tier": 1,
        "payload": {
            "schema": "call/v1",
            "raw_id": f"c-{at}",
            "direction": "incoming",
            "answered": seconds > 0,
            "duration_s": seconds,
            "counterparty": {"kind": "phone", "value": p["phone"]},
            "service": "cellular",
        },
    }


def mail(at: str, sender: dict[str, Any], to: list[dict[str, Any]], subject: str) -> dict[str, Any]:
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
            "to": [{"email": t["email"], "name": t["name"]} for t in to],
            "subject": subject,
            "direction": "sent" if sender is OWNER else "received",
            "size": 1200,
        },
    }


def flight(day: str, number: str, from_: str, to: str, dep: str, arr: str) -> dict[str, Any]:
    return {
        "at": dep,
        "end": arr,
        "source": "manual",
        "kind": "flight",
        "tier": 1,
        "payload": {
            "schema": "flight/v1",
            "raw_id": f"fx-{day}-{number}",
            "date": day,
            "carrier": "XY",
            "number": number,
            "from": {"iata": from_},
            "to": {"iata": to},
            "scheduled_departure": dep,
            "scheduled_arrival": arr,
            "role": "passenger",
            "evidence": "declared",
            "observations": [{"evidence": "declared", "source": "manual"}],
        },
    }


def journey(day: str) -> dict[str, Any]:
    """A train journey bought as a ticket, to Trondheim, whose `to` names the station alone."""
    return {
        "at": utc(day, "07:00"),
        "end": utc(day, "13:30"),
        "source": "manual",
        "kind": "journey",
        "tier": 1,
        "payload": {
            "schema": "journey/v1",
            "raw_id": f"j-{day}",
            "mode": "transit",
            "provider": "rail",
            "from": {"name": "Oslo S"},
            "to": {"name": "Trondheim"},
        },
    }


def drafts(owner_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [
        resolution(("email", OWNER["email"]), owner_id, OWNER["name"]),
        resolution(("phone", OWNER["phone"]), owner_id, OWNER["name"]),
    ]
    for p in PEOPLE:
        out.append(resolution(("email", p["email"]), p["id"], p["name"]))
        out.append(resolution(("phone", p["phone"]), p["id"], p["name"]))
    for i, day in enumerate(A_DAYS):
        out += _together(day, BERGEN, [ASTRID, INGRID] if i < 20 else [ASTRID])
    for i, day in enumerate(E_DAYS):
        who = [ELIN, OBSERVED]
        who += [CAMILLA] if i < 21 else []
        who += [GURO] if i < 19 else []
        who += [HANS] if i < 10 else []
        out += _together(day, OSLO, who)
    for i, day in enumerate(B_DAYS):
        out += _together(day, TRONDHEIM, [BJORN, JON] if i < 21 else [BJORN])
    for day in D_DAYS:
        out += _together(day, BERGEN, [DAG])
    for day in [*H_2023, *H_2024]:
        out += _together(day, OSLO, [HANS])
    for day in F_DAYS:
        out += _together(day, OSLO, [FRODE])
    for i, day in enumerate(LATER_DAYS):
        out += _together(day, OSLO, LATER[2 * i : 2 * i + 2])
    out += _together(A_YEAR_BEFORE, TRONDHEIM, SIX)
    out += _together(KH, TRONDHEIM, [KRISTIN])
    out += _together(HANS_3Y, OSLO, [HANS, OBSERVED])
    # Bjørn: a direct chat in March 2024, a promise each way, then nothing.
    out += [
        message(utc("2024-03-09", "09:00"), direct(BJORN), "I'll send you the photos by Friday."),
        message(utc("2024-03-10", "10:00"), direct(BJORN), "I will bring the charts next time.", BJORN),
    ]
    # Camilla: a call answered in June 2025, one missed in November (not a real contact).
    out += [call(utc("2025-06-01", "18:00"), CAMILLA, 600), call(utc("2025-11-01", "18:00"), CAMILLA, 0)]
    # Dag: a newsletter, and the owner's mail to everyone at once: mail is never a real contact.
    out += [
        mail(utc("2025-05-01", "07:00"), DAG, [OWNER], "Club news, May"),
        mail(utc("2025-11-20", "09:00"), OWNER, [DAG, ELIN, ASTRID], "Moving house"),
    ]
    # Elin: lines in a group only — the group's, not a contact with her.
    out += [
        message(utc("2025-01-01", "00:05"), GROUP, "Happy new year, all!", ELIN),
        message(utc("2025-01-01", "00:10"), GROUP, "And to you!"),
    ]
    # Ingrid: a timed meeting by video, held nowhere the record can place; Jon: a transcript.
    out.append(
        event(
            utc("2025-09-01", "10:00"),
            utc("2025-09-01", "11:00"),
            "Catch-up",
            [attendee(INGRID["email"], INGRID["name"])],
            location="Video call",
        )
    )
    # Jon's call is recorded on the road to Bergen, inside no stay: a meeting, not a day together.
    out += dwell("2025-08-01", "12:00", "14:00", OSLO, every_min=20, noise_m=20)
    out += travel("2025-08-01", "14:00", "18:00", OSLO, BERGEN, steps=24)
    out += dwell("2025-08-01", "18:00", "20:00", BERGEN, every_min=20, noise_m=20)
    out.append(
        transcript(
            utc("2025-08-01", "15:00"),
            utc("2025-08-01", "15:40"),
            "Planning",
            [{"name": JON["name"], "email": JON["email"]}, {"name": "me"}],
        )
    )
    # Q..Y: a direct message each in 2025.
    for i, p in enumerate(LATER):
        out.append(message(utc("2025-10-01", f"{8 + i // 6:02d}:{(i % 6) * 10:02d}"), direct(p), "Hi!", p))
    # The two anniversary days themselves, at home.
    out += dwell("2025-10-14", "10:00", "17:00", OSLO, every_min=30, noise_m=20)
    out += dwell("2025-11-03", "10:00", "17:00", OSLO, every_min=30, noise_m=20)
    # December 2025, planned: a flight to Bergen, a train and a dinner in Trondheim, a party at home.
    out.append(
        flight("2025-12-20", "601", "OSL", "BGO", utc("2025-12-20", "08:00"), utc("2025-12-20", "08:50"))
    )
    out.append(journey("2025-12-21"))
    out.append(
        event(
            utc("2025-12-22", "19:00"), utc("2025-12-22", "22:00"), "Dinner", location="Solsiden, Trondheim"
        )
    )
    out.append(event(utc("2025-12-19", "19:00"), utc("2025-12-19", "23:00"), "Party", location="Home"))
    out += dwell(LAST_DAY, "10:00", "12:00", OSLO, every_min=30, noise_m=20)
    return out


PLACES = {"Home": {"lat": OSLO[0], "lon": OSLO[1], "radius_m": 150, "kind": "home"}}


def four_years_record(root: Path) -> Logbook:
    """The four years written into a fresh record at `root`, with `places.json` naming Home and the
    owner's aliases in `policy/owner.json`."""
    lb = Logbook.init(root, TZ)
    lb.append_many(drafts(str(lb.meta["owner_id"])))
    (lb.root / "places.json").write_text(json.dumps(PLACES, indent=2), encoding="utf-8")
    policy = lb.root / "policy"
    policy.mkdir(exist_ok=True)
    (policy / "owner.json").write_text(
        json.dumps({"names": [OWNER["name"]], "emails": [OWNER["email"]], "phones": [OWNER["phone"]]}),
        encoding="utf-8",
    )
    return lb
