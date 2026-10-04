"""`logbook demo --days N --seed S --out DIR`: a complete synthetic record, invented here.

The Oslo persona, Ines Nordmann, who does not exist, lives through a four-week story that repeats
for as many days as asked: an office week with a cabin weekend, a week in Zürich for a client
(flown out on a tracked flight, back on one the record's own calendar and location points
infer), a week aboard the yacht Nordlys with the boat's own AIS track as a subject, and a week
ending in Copenhagen (flown out on a tracked flight, back on one the owner declared). Around it,
every profile the format has: location, event, message, transcript (the text stored as an
attachment), note, photo (with favourites and an Art album, so keepers follow), call, mail, task,
browse, watch, listen, trip, highlight, voice-memo (metadata and a digest, no audio), health
samples (sleep stages, steps, heart rate), transaction, flight in all three evidences, and the
resolution lines of a circle of twelve fictional people.

Everything is made up in this file and nothing is read from anywhere: no path outside the record
it writes, no other record, no network. Phone numbers are in the UK reserved range 07700 900xxx,
emails at example.org, the airline is XY (no airline), aircraft registrations ZZ-, the boat's MMSI
in the 970xxxxxx test range. The record is a function of (`days`, `seed`): ids, timestamps, GPS
noise, step counts and the text of every message come from one seeded generator and a fixed
first day, so the same arguments give the same chain head on any machine."""

from __future__ import annotations

import hashlib
import json
import math
import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo

from ..core import attachments, flights, keepers
from ..core import places as named_places
from ..core.store import Logbook

START = date(2026, 6, 1)  # a Monday; day 0 of the story
CYCLE = 28  # the story repeats every four weeks
TZ = "Europe/Oslo"
OSLO, ZURICH, COPENHAGEN = "Europe/Oslo", "Europe/Zurich", "Europe/Copenhagen"
BOAT = "nordlys"
BOAT_NAME = "Nordlys"
MMSI = "970123456"
CARRIER = "XY"
NAMESPACE = uuid.UUID("7e2d5c1a-0000-4000-8000-00000000de30")

KINDS = frozenset(
    {
        "location",
        "event",
        "message",
        "transcript",
        "note",
        "photo",
        "keeper",
        "call",
        "mail",
        "task",
        "browse",
        "watch",
        "listen",
        "trip",
        "highlight",
        "voice-memo",
        "health",
        "transaction",
        "flight",
        "resolution",
    }
)
SCHEMAS = frozenset(
    {
        "location/v1",
        "event/v1",
        "message/v1",
        "transcript/v1",
        "note/v1",
        "photo/v1",
        "keeper/v1",
        "call/v1",
        "mail/v1",
        "task/v1",
        "browse/v1",
        "watch/v1",
        "listen/v1",
        "trip/v1",
        "highlight/v1",
        "voice-memo/v1",
        "health-sample/v1",
        "transaction/v1",
        "flight/v1",
        "resolution/v1",
    }
)


class Spot(NamedTuple):
    name: str
    lat: float
    lon: float
    tz: str


HOME = Spot("Home", 59.9139, 10.7522, OSLO)
OFFICE = Spot("Office", 59.9100, 10.7600, OSLO)
CAFE = Spot("the cafe", 59.9200, 10.7400, OSLO)
PARK = Spot("the park", 59.9260, 10.7000, OSLO)
MARINA = Spot("Marina", 59.9050, 10.7350, OSLO)
CABIN = Spot("Cabin", 60.6000, 9.1000, OSLO)
BAY_A = Spot("the bay", 59.8500, 10.6000, OSLO)
BAY_B = Spot("the southern bay", 59.4300, 10.4800, OSLO)
HARBOUR = Spot("the harbour", 59.0500, 10.0300, OSLO)
TOWN = Spot("the harbour town", 59.0450, 10.0450, OSLO)
OSL = Spot("OSL", 60.1939, 11.1004, OSLO)
ZRH = Spot("ZRH", 47.4581, 8.5481, ZURICH)
ZH_HOTEL = Spot("the Zürich hotel", 47.3769, 8.5417, ZURICH)
ZH_CLIENT = Spot("the client's office", 47.3700, 8.5300, ZURICH)
ZH_MUSEUM = Spot("the museum", 47.3660, 8.5480, ZURICH)
CPH = Spot("CPH", 55.6180, 12.6508, COPENHAGEN)
CPH_HOTEL = Spot("the Copenhagen hotel", 55.6850, 12.5500, COPENHAGEN)
CPH_FRIEND = Spot("Freja's flat", 55.6950, 12.5700, COPENHAGEN)

PLACES: dict[Spot, dict[str, Any]] = {
    HOME: {"radius_m": 120, "kind": "home", "country": "NO"},
    OFFICE: {"radius_m": 120, "kind": "other"},
    MARINA: {"radius_m": 150, "kind": "asset-berth", "tags": ["boat"]},
    CABIN: {"radius_m": 200, "kind": "other", "tags": ["mountains"]},
}


class Person(NamedTuple):
    name: str
    email: str
    phone: str
    face: str | None = None  # the photo library's person id, when the library knows the face

    @property
    def first(self) -> str:
        return self.name.split()[0]

    @property
    def entity(self) -> str:
        return str(uuid.uuid5(NAMESPACE, f"person:{self.email}"))


OWNER = Person("Ines Nordmann", "ines.nordmann@example.org", "+447700900000")
OLA = Person("Ola Nordmann", "ola.nordmann@example.org", "+447700900001", "f_01")
KARI = Person("Kari Nordmann", "kari.nordmann@example.org", "+447700900002", "f_02")
PER = Person("Per Hansen", "per.hansen@example.org", "+447700900003")
LIV = Person("Liv Berg", "liv.berg@example.org", "+447700900004")
ANDERS = Person("Anders Vik", "anders.vik@example.org", "+447700900005", "f_05")
SIGRID = Person("Sigrid Moen", "sigrid.moen@example.org", "+447700900006")
NILS = Person("Nils Haug", "nils.haug@example.org", "+447700900007")
MARTA = Person("Marta Keller", "marta.keller@example.org", "+447700900008")
JONAS = Person("Jonas Weber", "jonas.weber@example.org", "+447700900009")
FREJA = Person("Freja Lund", "freja.lund@example.org", "+447700900010", "f_10")
EVA = Person("Eva Nordmann", "eva.nordmann@example.org", "+447700900011")
TORE = Person("Tore Dahl", "tore.dahl@example.org", "+447700900012")
PEOPLE = (OLA, KARI, PER, LIV, ANDERS, SIGRID, NILS, MARTA, JONAS, FREJA, EVA, TORE)
CREW = (OLA, ANDERS, SIGRID)

# -- the story: one day type per day of the cycle --------------------------------------------------------

DAY_TYPES = {
    0: "office",
    1: "office",
    2: "office_cafe",
    3: "office_meeting",
    4: "office",
    5: "cabin_out",
    6: "cabin_back",
    7: "fly_zrh",
    8: "zurich_meeting",
    9: "zurich_day",
    10: "fly_home_zrh",
    11: "office",
    12: "marina_prep",
    13: "home_run",
    14: "boat_out",
    15: "boat_a_b",
    16: "boat_b_c",
    17: "boat_harbour",
    18: "boat_c_a",
    19: "boat_a_marina",
    20: "boat_home",
    21: "office",
    22: "office_cafe",
    23: "office",
    24: "fly_cph",
    25: "cph_day",
    26: "fly_home_cph",
    27: "home_run",
}


class Stay(NamedTuple):
    start: str
    end: str
    spot: Spot
    noise_m: float = 30.0


class Move(NamedTuple):
    start: str
    end: str
    a: Spot
    b: Spot
    steps: int = 4


Leg = Stay | Move


def _office(cafe: bool = False) -> list[Leg]:
    legs: list[Leg] = [Stay("00:00", "07:30", HOME), Move("07:30", "07:45", HOME, OFFICE)]
    if cafe:
        legs += [
            Stay("07:45", "11:50", OFFICE),
            Move("11:50", "12:00", OFFICE, CAFE, 3),
            Stay("12:00", "13:00", CAFE),
            Move("13:00", "13:10", CAFE, OFFICE, 3),
            Stay("13:10", "17:30", OFFICE),
        ]
    else:
        legs.append(Stay("07:45", "17:30", OFFICE))
    legs += [Move("17:30", "17:45", OFFICE, HOME), Stay("17:45", "24:00", HOME)]
    return legs


def _boat_leg(a: Spot, b: Spot, dep: str, arr: str) -> list[Leg]:
    return [Stay("00:00", dep, a, 15), Move(dep, arr, a, b, 36), Stay(arr, "24:00", b, 15)]


OWNER_DAYS: dict[str, list[Leg]] = {
    "office": _office(),
    "office_cafe": _office(cafe=True),
    "office_meeting": _office(),
    "home_run": [
        Stay("00:00", "10:00", HOME),
        Move("10:00", "10:30", HOME, PARK, 6),
        Stay("10:30", "11:30", PARK, 60),
        Move("11:30", "12:00", PARK, HOME, 6),
        Stay("12:00", "24:00", HOME),
    ],
    "cabin_out": [
        Stay("00:00", "09:00", HOME),
        Move("09:00", "12:00", HOME, CABIN, 24),
        Stay("12:00", "24:00", CABIN),
    ],
    "cabin_back": [
        Stay("00:00", "14:00", CABIN),
        Move("14:00", "17:00", CABIN, HOME, 24),
        Stay("17:00", "24:00", HOME),
    ],
    "fly_zrh": [
        Stay("00:00", "05:00", HOME),
        Move("05:00", "05:40", HOME, OSL, 6),
        Stay("05:40", "06:55", OSL),
        Stay("09:20", "10:00", ZRH),
        Move("10:00", "10:30", ZRH, ZH_HOTEL, 4),
        Stay("10:30", "24:00", ZH_HOTEL),
    ],
    "zurich_meeting": [
        Stay("00:00", "08:30", ZH_HOTEL),
        Move("08:30", "08:50", ZH_HOTEL, ZH_CLIENT, 3),
        Stay("08:50", "17:00", ZH_CLIENT),
        Move("17:00", "17:20", ZH_CLIENT, ZH_HOTEL, 3),
        Stay("17:20", "24:00", ZH_HOTEL),
    ],
    "zurich_day": [
        Stay("00:00", "09:00", ZH_HOTEL),
        Move("09:00", "09:20", ZH_HOTEL, ZH_CLIENT, 3),
        Stay("09:20", "16:00", ZH_CLIENT),
        Move("16:00", "16:30", ZH_CLIENT, ZH_MUSEUM, 3),
        Stay("16:30", "18:00", ZH_MUSEUM),
        Move("18:00", "18:20", ZH_MUSEUM, ZH_HOTEL, 3),
        Stay("18:20", "24:00", ZH_HOTEL),
    ],
    "fly_home_zrh": [
        Stay("00:00", "15:00", ZH_HOTEL),
        Move("15:00", "15:30", ZH_HOTEL, ZRH, 4),
        Stay("15:30", "17:00", ZRH),
        Stay("19:20", "19:50", OSL),
        Move("19:50", "20:30", OSL, HOME, 6),
        Stay("20:30", "24:00", HOME),
    ],
    "marina_prep": [
        Stay("00:00", "09:30", HOME),
        Move("09:30", "09:45", HOME, MARINA, 3),
        Stay("09:45", "15:00", MARINA, 15),
        Move("15:00", "15:15", MARINA, HOME, 3),
        Stay("15:15", "24:00", HOME),
    ],
    "boat_out": [
        Stay("00:00", "08:30", HOME),
        Move("08:30", "08:45", HOME, MARINA, 3),
        Stay("08:45", "10:00", MARINA, 15),
        Move("10:00", "13:00", MARINA, BAY_A, 36),
        Stay("13:00", "24:00", BAY_A, 15),
    ],
    "boat_a_b": _boat_leg(BAY_A, BAY_B, "10:00", "15:00"),
    "boat_b_c": _boat_leg(BAY_B, HARBOUR, "09:00", "14:00"),
    "boat_harbour": [
        Stay("00:00", "11:00", HARBOUR, 15),
        Move("11:00", "11:20", HARBOUR, TOWN, 3),
        Stay("11:20", "13:00", TOWN),
        Move("13:00", "13:20", TOWN, HARBOUR, 3),
        Stay("13:20", "24:00", HARBOUR, 15),
    ],
    "boat_c_a": _boat_leg(HARBOUR, BAY_A, "09:00", "16:00"),
    "boat_a_marina": _boat_leg(BAY_A, MARINA, "11:00", "14:00"),
    "boat_home": [
        Stay("00:00", "10:00", MARINA, 15),
        Move("10:00", "10:15", MARINA, HOME, 3),
        Stay("10:15", "24:00", HOME),
    ],
    "fly_cph": [
        Stay("00:00", "07:30", HOME),
        Move("07:30", "07:45", HOME, OFFICE),
        Stay("07:45", "13:30", OFFICE),
        Move("13:30", "14:20", OFFICE, OSL, 6),
        Stay("14:20", "15:50", OSL),
        Stay("17:15", "17:50", CPH),
        Move("17:50", "18:30", CPH, CPH_HOTEL, 4),
        Stay("18:30", "24:00", CPH_HOTEL),
    ],
    "cph_day": [
        Stay("00:00", "10:00", CPH_HOTEL),
        Move("10:00", "10:30", CPH_HOTEL, CPH_FRIEND, 3),
        Stay("10:30", "16:00", CPH_FRIEND),
        Move("16:00", "16:30", CPH_FRIEND, CPH_HOTEL, 3),
        Stay("16:30", "24:00", CPH_HOTEL),
    ],
    "fly_home_cph": [
        Stay("00:00", "10:00", CPH_HOTEL),
        Move("10:00", "10:30", CPH_HOTEL, CPH, 4),
        Stay("10:30", "11:55", CPH),
        Stay("13:15", "13:50", OSL),
        Move("13:50", "14:30", OSL, HOME, 6),
        Stay("14:30", "24:00", HOME),
    ],
}

BOAT_DAYS: dict[str, list[Leg]] = {  # the yacht's own track; any other day it lies at the berth
    "boat_out": [
        Stay("00:00", "10:00", MARINA, 5),
        Move("10:00", "13:00", MARINA, BAY_A, 36),
        Stay("13:00", "24:00", BAY_A, 5),
    ],
    "boat_a_b": [
        Stay("00:00", "10:00", BAY_A, 5),
        Move("10:00", "15:00", BAY_A, BAY_B, 60),
        Stay("15:00", "24:00", BAY_B, 5),
    ],
    "boat_b_c": [
        Stay("00:00", "09:00", BAY_B, 5),
        Move("09:00", "14:00", BAY_B, HARBOUR, 60),
        Stay("14:00", "24:00", HARBOUR, 5),
    ],
    "boat_harbour": [Stay("00:00", "24:00", HARBOUR, 5)],
    "boat_c_a": [
        Stay("00:00", "09:00", HARBOUR, 5),
        Move("09:00", "16:00", HARBOUR, BAY_A, 84),
        Stay("16:00", "24:00", BAY_A, 5),
    ],
    "boat_a_marina": [
        Stay("00:00", "11:00", BAY_A, 5),
        Move("11:00", "14:00", BAY_A, MARINA, 36),
        Stay("14:00", "24:00", MARINA, 5),
    ],
}
BERTH: list[Leg] = [Stay("00:00", "24:00", MARINA, 5)]

# -- the words ---------------------------------------------------------------------------------------------

OLA_CHAT = (
    ("Picking up bread on the way home?", "Yes, the sourdough. Back by six."),
    ("The forecast for the weekend looks good", "Then we go. I'll check the outboard."),
    ("Did you call your mother?", "Tonight, promise."),
    ("Dinner at eight?", "Perfect. I'll cook."),
    ("Landed?", "Just now. Taxi in ten."),
    ("Mooring photos sent, check your mail", "Got them, the east berth looks fine."),
    ("Ferry or bridge on Sunday?", "Bridge, the ferry queue was awful last time."),
    ("Train is late again", "I'll keep the food warm."),
)
CREW_CHAT = (
    (ANDERS, "Fuel topped up, water tank full."),
    (SIGRID, "I'll bring the charts and the good coffee."),
    (OLA, "Cast off at ten, tide is with us."),
    (ANDERS, "Anchor held all night, 18 metres of chain."),
    (SIGRID, "Wind backing west by the afternoon, says the forecast."),
    (OLA, "Harbour master says the inner quay is free."),
)
MEETINGS = (
    ("Weekly planning", (PER, LIV)),
    ("Design review", (PER,)),
    ("One to one", (LIV,)),
    ("Release sync", (PER, LIV)),
)
NOTES = (
    "Good day. The planning meeting finally agreed on the autumn scope.",
    "Walked home along the river. Thought about the boat all afternoon.",
    "Long call with Eva Nordmann about the summer; she wants to come sailing.",
    "Quiet evening. Read two chapters and slept early.",
    "Rain all day. Fixed the leaking tap at last.",
)
PAGES = (
    ("https://havn.example.org/winter-guide", "Oslofjord: a winter guide"),
    ("https://weather.example.org/oslofjord", "Oslofjord forecast"),
    ("https://knots.example.org/bowline", "The bowline, step by step"),
    ("https://cabin.example.org/firewood", "Stacking firewood that dries"),
    ("https://rail.example.org/timetable", "Timetable"),
    ("https://recipes.example.org/fish-soup", "Fish soup for a crowd"),
    ("https://museum.example.org/hours", "Opening hours"),
    ("https://harbour.example.org/berths", "Visitor berths and prices"),
)
VIDEOS = (
    ("aB3dE5fG7hI", "Splicing a three-strand rope", "Knots by Ola"),
    ("cD4eF6gH8iJ", "Anchoring in a crowded bay", "Fjord Sailing"),
    ("eF5gH7iJ9kL", "Oiling a teak deck", "Fjord Sailing"),
    ("gH6iJ8kL0mN", "Cabin stove maintenance", "Mountain Hut"),
)
TRACKS = (
    ("Fjordsang", "Kari Nordmann"),
    ("Nattseilas", "The Harbour Band"),
    ("Rain on Deck", "Sigrid Moen Trio"),
)
EPISODES = (("The Harbour Hour", "Tides and tales"), ("The Harbour Hour", "Anchors that hold"))
BOOK = ("Tidewater", "Ingrid Solheim")
QUOTES = (
    "The fjord does not care what you planned; it asks only what you can do now.",
    "A good anchorage is one you can leave in the dark.",
    "She wrote the weather in the margin, every day, until the margins were the book.",
    "Rope remembers every knot it has held.",
)
TASKS = (
    ("Book the Zürich hotel", "done", 1),
    ("Service the outboard", "open", 12),
    ("Buy the long rope", "done", 9),
    ("Renew the boat insurance", "open", 20),
    ("Send the Copenhagen slides", "done", 23),
)
MAILS = (
    (LIV, "Autumn scope", "Attached the scope we agreed on. Comments by Friday.\n", 0),
    (MARTA, "Agenda for next week", "Kickoff Tuesday at nine, our office. Lunch after.\n", 2),
    (NILS, "Cabin key", "The key is under the second stone, as always. Enjoy the weekend.\n", 4),
    (ANDERS, "Mooring for the week", "The east berth is free from Monday. Fuel dock opens at eight.\n", 11),
    (FREJA, "Copenhagen!", "Can't wait. I'll meet you at the flat, bring a jumper, it's windy.\n", 22),
    (LIV, "Slides", "Thanks for the slides. Rest well after the trip.\n", 26),
)
MERCHANTS = (
    ("Bakeri Nord", -42.5, "restaurants"),
    ("Kafé Måken", -68.0, "restaurants"),
    ("Havnekiosken", -119.0, "groceries"),
)
VOICE_MEMOS = (("Idea for the talk", 102.4, 1), ("Mooring notes", 44.0, 14), ("List for the cabin", 61.5, 4))


# -- the generator ------------------------------------------------------------------------------------------


@dataclass
class _Story:
    rng: random.Random
    airports: flights.Airports
    airlines: flights.Airlines
    recorded_at: str
    drafts: list[dict[str, Any]] = field(default_factory=list)
    photos: list[dict[str, Any]] = field(default_factory=list)
    blobs: list[bytes] = field(default_factory=list)
    _counter: int = 0

    # -- primitives --

    def uuid7(self, at: str) -> str:
        """A UUIDv7 whose time is `at` and whose random bits come from the seed."""
        ms = int(_instant(at).timestamp() * 1000)
        value = (
            (ms << 80)
            | (0x7 << 76)
            | (self.rng.getrandbits(12) << 64)
            | (0b10 << 62)
            | self.rng.getrandbits(62)
        )
        return str(uuid.UUID(int=value))

    def line(
        self,
        at: str,
        source: str,
        kind: str,
        tier: int,
        payload: dict[str, Any],
        end: str | None = None,
        tz: str = TZ,
    ) -> dict[str, Any]:
        draft = {
            "id": self.uuid7(at),
            "at": at,
            "end": end,
            "tz": tz,
            "source": source,
            "kind": kind,
            "tier": tier,
            "payload": payload,
            "recorded_at": self.recorded_at,
        }
        self.drafts.append(draft)
        return draft

    def jitter(self, spot: Spot, metres: float) -> tuple[float, float]:
        bearing = self.rng.uniform(0, 2 * math.pi)
        d = self.rng.uniform(0, metres)
        dlat = d * math.cos(bearing) / 111_320
        dlon = d * math.sin(bearing) / (111_320 * math.cos(math.radians(spot.lat)))
        return (round(spot.lat + dlat, 6), round(spot.lon + dlon, 6))

    def point(
        self, at: str, where: tuple[float, float], tz: str, subject: str | None, moving: bool
    ) -> dict[str, Any]:
        if subject is None:
            payload: dict[str, Any] = {
                "schema": "location/v1",
                "lat": where[0],
                "lon": where[1],
                "accuracy_m": self.rng.choice((8, 10, 12, 15, 20)),
                "raw_id": f"dawarich:{at}",
            }
            return self.line(at, "dawarich", "location", 1, payload, tz=tz)
        payload = {
            "schema": "location/v1",
            "lat": where[0],
            "lon": where[1],
            "speed_mps": round(self.rng.uniform(2.2, 3.4), 1) if moving else 0,
            "heading_deg": self.rng.randint(0, 359),
            "tracker": "aisstream",
            "raw_id": f"aisstream:{MMSI}:{int(_instant(at).timestamp())}",
            "subject": subject,
            "extra": {"mmsi": MMSI},
        }
        return self.line(at, "ais", "location", 1, payload)

    # -- tracks --

    def track(self, day: date, legs: list[Leg], subject: str | None, every_min: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for leg in legs:
            if isinstance(leg, Stay):
                t, t1 = _local(day, leg.start, leg.spot.tz), _local(day, leg.end, leg.spot.tz)
                while t < t1:
                    out.append(
                        self.point(_stamp(t), self.jitter(leg.spot, leg.noise_m), leg.spot.tz, subject, False)
                    )
                    t += timedelta(minutes=every_min)
            else:
                t0, t1 = _local(day, leg.start, leg.a.tz), _local(day, leg.end, leg.b.tz)
                for i in range(1, leg.steps):
                    f = i / leg.steps
                    where = (
                        round(leg.a.lat + (leg.b.lat - leg.a.lat) * f, 6),
                        round(leg.a.lon + (leg.b.lon - leg.a.lon) * f, 6),
                    )
                    tz = leg.a.tz if f < 0.5 else leg.b.tz
                    out.append(self.point(_stamp(t0 + (t1 - t0) * f), where, tz, subject, True))
        return out

    # -- the other lines --

    def resolution(self, ref: tuple[str, str], person: Person, at: str) -> None:
        self.line(
            at,
            "manual",
            "resolution",
            2,
            {
                "schema": "resolution/v1",
                "ref": {"kind": ref[0], "value": ref[1]},
                "entity": {"type": "person", "id": person.entity, "registry": "logbook"},
                "label": person.name,
                "method": "owner",
            },
        )

    def event(
        self,
        at: str,
        end: str,
        title: str,
        people: tuple[Person, ...] = (),
        tz: str = TZ,
        all_day: bool = False,
        location: str | None = None,
        source: str = "ios-calendar",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": "event/v1",
            "raw_id": f"cal:{at}:{title}",
            "title": title,
            "all_day": all_day,
        }
        if people:
            payload["attendees"] = [
                {"ref": {"kind": "email", "value": p.email}, "name": p.name, "response": "accepted"}
                for p in people
            ]
        if location:
            payload["location"] = location
        return self.line(at, source, "event", 1, payload, end=end, tz=tz)

    def message(
        self,
        at: str,
        text: str,
        from_me: bool,
        sender: Person,
        chat: tuple[str, str, str],
        tz: str = TZ,
        source: str = "whatsapp",
    ) -> None:
        chat_id, chat_type, chat_name = chat
        payload: dict[str, Any] = {
            "schema": "message/v1",
            "raw_id": hashlib.sha256(f"{chat_id}:{at}:{text}".encode()).hexdigest()[:16].upper(),
            "chat": {"id": chat_id, "type": chat_type, "name": chat_name},
            "from_me": from_me,
            "text": text,
        }
        if not from_me:
            payload["sender"] = {"kind": "phone", "value": sender.phone, "name": sender.first}
        self.line(at, source, "message", 2, payload, tz=tz)

    def transcript(
        self, at: str, end: str, title: str, people: tuple[Person, ...], lines: list[str], tz: str = TZ
    ) -> None:
        text = f"# {title}\n\n" + "\n".join(f"- {line}" for line in lines) + "\n"
        data = text.encode("utf-8")
        self.blobs.append(data)
        self.line(
            at,
            "granola",
            "transcript",
            2,
            {
                "schema": "transcript/v1",
                "provider": "granola",
                "raw_id": f"granola:{at}",
                "title": title,
                "participants": [{"name": p.name, "email": p.email} for p in people],
                "summary": lines[0],
                "language": "en",
                "content": attachments.reference(data, "text/markdown"),
            },
            end=end,
            tz=tz,
        )

    def note(self, at: str, text: str, tz: str = TZ) -> None:
        self.line(at, "manual", "note", 2, {"schema": "note/v1", "text": text}, tz=tz)

    def photo(
        self,
        at: str,
        spot: Spot,
        people: tuple[Person, ...] = (),
        favorite: bool = False,
        album: str | None = None,
        provenance: str = "camera",
    ) -> None:
        where = self.jitter(spot, 20)
        stamp = f"{at[5:7]}{at[8:10]}{at[11:13]}{at[14:16]}"
        payload: dict[str, Any] = {
            "schema": "photo/v1",
            "asset_id": f"p-{at}",
            "library": "immich",
            "file_name": f"IMG_{stamp}.HEIC" if provenance == "camera" else f"scan_{at[:4]}_{stamp}.jpg",
            "media": "image",
            "provenance": provenance,
            "lat": where[0],
            "lon": where[1],
            "faces": len(people),
            "people": [p.face for p in people if p.face],
            "raw_id": f"p-{at}",
        }
        extra: dict[str, Any] = {}
        if favorite:
            extra["favorite"] = True
        if album:
            extra["album"] = album
        if extra:
            payload["extra"] = extra
        self.photos.append(self.line(at, "immich", "photo", 1, payload, tz=spot.tz))

    def call(self, at: str, person: Person, minutes: float, incoming: bool, tz: str = TZ) -> None:
        seconds = round(minutes * 60)
        self.line(
            at,
            "ios-calls",
            "call",
            1,
            {
                "schema": "call/v1",
                "raw_id": str(uuid.uuid5(NAMESPACE, f"call:{at}")),
                "direction": "incoming" if incoming else "outgoing",
                "answered": True,
                "duration_s": seconds,
                "counterparty": {"kind": "phone", "value": person.phone},
                "service": "cellular",
            },
            end=_stamp(_instant(at) + timedelta(seconds=seconds)),
            tz=tz,
        )

    def mail(self, at: str, sender: Person, subject: str, body: str, tz: str = TZ) -> None:
        message_id = f"{hashlib.sha256(f'{at}:{subject}'.encode()).hexdigest()[:10]}@mail.example.org"
        payload: dict[str, Any] = {
            "schema": "mail/v1",
            "raw_id": f"{OWNER.email}:{message_id}",
            "message_id": message_id,
            "thread": message_id,
            "from": {"email": sender.email, "name": sender.name},
            "to": [{"email": OWNER.email, "name": OWNER.name}],
            "subject": subject,
            "date": _instant(at).astimezone(ZoneInfo(tz)).isoformat(),
            "direction": "received",
            "body": body,
            "account": OWNER.email,
        }
        if "Attached" in body:
            blob = f"scope {at}".encode()
            payload["attachments"] = [
                {
                    "filename": "scope.pdf",
                    "media_type": "application/pdf",
                    "sha256": attachments.digest(blob),
                    "bytes": 41002,
                }
            ]
        self.line(at, "mail", "mail", 2, payload, tz=tz)

    def task(self, at: str, title: str, status: str, due: date) -> None:
        payload: dict[str, Any] = {
            "schema": "task/v1",
            "raw_id": f"{hashlib.sha256(title.encode()).hexdigest()[:12]}@{at}",
            "title": title,
            "status": status,
            "due": due.isoformat(),
            "list": "Boat"
            if "boat" in title.lower() or "outboard" in title.lower() or "rope" in title.lower()
            else "Work",
            "modified_at": at,
        }
        if status == "done":
            payload["completed_at"] = at
        self.line(at, "google-takeout", "task", 2, payload)

    def browse(self, at: str, url: str, title: str, tz: str = TZ) -> None:
        self.line(
            at,
            "safari",
            "browse",
            2,
            {
                "schema": "browse/v1",
                "raw_id": f"safari:{int(_instant(at).timestamp()) - 978307200}:{_hex(url)}",
                "url": url,
                "title": title,
                "action": "visit",
                "browser": "safari",
            },
            tz=tz,
        )

    def watch(self, at: str, video: tuple[str, str, str], tz: str = TZ) -> None:
        video_id, title, channel = video
        self.line(
            at,
            "google-takeout",
            "watch",
            2,
            {
                "schema": "watch/v1",
                "raw_id": f"youtube:{at}:{hashlib.sha256(video_id.encode()).hexdigest()[:16]}",
                "action": "watched",
                "title": title,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "video_id": video_id,
                "channel": {"name": channel},
                "service": "youtube",
            },
            tz=tz,
        )

    def listen(
        self, at: str, track: tuple[str, str] | None, episode: tuple[str, str] | None, tz: str = TZ
    ) -> None:
        if track:
            title, artist = track
            tagged = _instant(at).astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M:%S")
            payload: dict[str, Any] = {
                "schema": "listen/v1",
                "raw_id": f"shazam:{_digits(title, 9)}:{tagged}",
                "media": "track",
                "title": title,
                "artist": artist,
                "service": "shazam",
            }
            self.line(at, "shazam", "listen", 2, payload, tz=tz)
        elif episode:
            show, title = episode
            payload = {
                "schema": "listen/v1",
                "raw_id": f"apple-podcasts:{uuid.uuid5(NAMESPACE, title)}@{at}",
                "media": "episode",
                "title": title,
                "show": show,
                "publisher": "Harbour Radio",
                "duration_s": 2400,
                "played_s": self.rng.randint(1200, 2400),
                "service": "apple-podcasts",
            }
            self.line(at, "apple-podcasts", "listen", 2, payload, tz=tz)

    def highlight(self, at: str, quote: str, tz: str = TZ) -> None:
        title, author = BOOK
        self.line(
            at,
            "apple-books",
            "highlight",
            2,
            {
                "schema": "highlight/v1",
                "raw_id": str(uuid.uuid5(NAMESPACE, f"highlight:{quote}")),
                "type": "highlight",
                "title": title,
                "author": author,
                "quote": quote,
                "location": f"epubcfi(/6/{4 + 2 * QUOTES.index(quote)}!/4/2/8,/1:0,/1:{len(quote)})",
            },
            tz=tz,
        )

    def voice_memo(self, at: str, title: str, seconds: float) -> None:
        blob = f"voice memo {title} {at}".encode()
        self.line(
            at,
            "voice-memos",
            "voice-memo",
            2,
            {
                "schema": "voice-memo/v1",
                "raw_id": str(uuid.uuid5(NAMESPACE, f"memo:{at}")),
                "title": title,
                "duration_s": seconds,
                "file_name": f"{_instant(at).astimezone(ZoneInfo(TZ)):%Y%m%d %H%M%S}.m4a",
                "media": {
                    "sha256": attachments.digest(blob),
                    "bytes": round(seconds * 16000),
                    "media_type": "audio/mp4",
                },
            },
            end=_stamp(_instant(at) + timedelta(seconds=seconds)),
        )

    def trip(
        self,
        at: str,
        end: str | None,
        mode: str,
        provider: str,
        from_: Spot,
        to: Spot | None,
        amount: float,
        currency: str,
        tz: str = TZ,
    ) -> None:
        payload: dict[str, Any] = {
            "schema": "trip/v1",
            "raw_id": f"{provider}:{_digits(from_.name, 6)}@{at}",
            "mode": mode,
            "provider": provider,
            "from": {"name": from_.name, "latitude": from_.lat, "longitude": from_.lon},
            "price": {"amount": amount, "currency": currency},
            "status": "completed",
        }
        if to:
            payload["to"] = {"name": to.name, "latitude": to.lat, "longitude": to.lon}
        self.line(at, provider, "trip", 3, payload, end=end, tz=tz)

    def transaction(
        self, at: str, merchant: str, amount: float, category: str, currency: str = "NOK", tz: str = TZ
    ) -> None:
        self.line(
            at,
            "copilot",
            "transaction",
            3,
            {
                "schema": "transaction/v1",
                "raw_id": str(uuid.uuid5(NAMESPACE, f"txn:{at}")),
                "amount": amount,
                "currency": currency,
                "merchant": merchant,
                "category": category,
                "date": _instant(at).astimezone(ZoneInfo(tz)).date().isoformat(),
                "account": "acct_0000000000000001",
                "provider": "copilot",
                "status": "posted",
            },
            tz=tz,
        )

    def health(
        self,
        at: str,
        type_: str,
        value: float,
        unit: str,
        device: str,
        end: str | None = None,
        tz: str = TZ,
        **more: Any,
    ) -> None:
        payload: dict[str, Any] = {
            "schema": "health-sample/v1",
            "raw_id": f"{type_}:{at}:{device}",
            "type": type_,
            "value": value,
            "unit": unit,
            "device": device,
            "source_name": "Watch" if device == "Watch" else "Phone",
            **more,
        }
        self.line(at, "apple-health", "health", 3, payload, end=end, tz=tz)


def _digits(text: str, n: int) -> str:
    """`n` decimal digits from the text, the same on every machine (unlike `hash`)."""
    return str(int(hashlib.sha256(text.encode()).hexdigest(), 16) % 10**n).zfill(n)


def _hex(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _instant(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(UTC)


def _stamp(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _local(day: date, clock: str, tz: str) -> datetime:
    if clock == "24:00":
        return _local(day + timedelta(days=1), "00:00", tz)
    hours, minutes = clock.split(":")
    return datetime(day.year, day.month, day.day, int(hours), int(minutes), tzinfo=ZoneInfo(tz))


def _utc(day: date, clock: str, tz: str = TZ) -> str:
    return _stamp(_local(day, clock, tz))


def _zone_of(kind: str) -> str:
    if kind.startswith("zurich") or kind == "fly_home_zrh":
        return ZURICH
    if kind in ("cph_day", "fly_home_cph"):
        return COPENHAGEN
    return OSLO


# -- the days ------------------------------------------------------------------------------------------


def _day(story: _Story, d: int, day: date, points: list[dict[str, Any]]) -> None:
    """Everything of one day but the tracks and the night's health, by the day's type."""
    kind = DAY_TYPES[d % CYCLE]
    tz = _zone_of(kind)
    rng = story.rng
    if kind.startswith("office") or kind == "fly_cph":
        title, people = MEETINGS[d % len(MEETINGS)]
        story.event(_utc(day, "09:00"), _utc(day, "09:45"), title, people, location="Office")
        if kind == "office_meeting":
            story.transcript(
                _utc(day, "14:00"),
                _utc(day, "14:30"),
                "Autumn scope",
                (PER, LIV),
                [
                    "Agreed the autumn scope: the import pipeline first, then the pages.",
                    f"{PER.first} takes the adapters, {LIV.first} the review in September.",
                    "Next check-in in two weeks.",
                ],
            )
        if kind == "office_cafe":
            story.event(_utc(day, "12:00"), _utc(day, "13:00"), "Lunch", (KARI,), location="the cafe")
            story.photo(_utc(day, "12:30"), CAFE, (KARI,), favorite=True)
            story.note(
                _utc(day, "13:05"), f"Lunch with {KARI.name} at the cafe. She is thinking about Tromsø again."
            )
            story.transaction(_utc(day, "12:48"), "Kafé Måken", -168, "restaurants")
    if kind == "cabin_out":
        story.event(
            _utc(day, "12:00"),
            _utc(day + timedelta(days=1), "14:00"),
            "Cabin weekend",
            (OLA,),
            location="Cabin",
        )
        story.note(
            _utc(day, "19:00"),
            f"At the cabin with {OLA.name}. Stacked the firewood, lit the stove, no signal.",
        )
        story.photo(_utc(day, "18:30"), CABIN, (OLA,), favorite=True)
        story.photo(_utc(day, "20:10"), CABIN)
        story.transaction(_utc(day, "10:40"), "Havnekiosken", -319, "groceries")
    if kind == "cabin_back":
        story.photo(_utc(day, "11:00"), CABIN, (OLA,))
        story.note(_utc(day, "18:00"), "Home from the cabin. The road over the pass was clear.")
    if kind == "fly_zrh":
        _flight_out(
            story,
            d,
            day,
            "561",
            OSL,
            ZRH,
            "Flight to Zürich (XY 561)",
            ("07:05", "09:15"),
            ("07:12", "09:10"),
        )
        story.trip(
            _utc(day, "10:00", ZURICH),
            _utc(day, "10:30", ZURICH),
            "ride",
            "taxi",
            ZRH,
            ZH_HOTEL,
            62,
            "CHF",
            tz=ZURICH,
        )
        story.message(_utc(day, "09:25", ZURICH), "Landed?", False, OLA, _chat(OLA), tz=ZURICH)
        story.message(
            _utc(day, "09:27", ZURICH), "Just now. Taxi in ten.", True, OWNER, _chat(OLA), tz=ZURICH
        )
        story.note(
            _utc(day, "22:00", ZURICH), "Zürich. The hotel by the river; kickoff tomorrow at nine.", tz=ZURICH
        )
    if kind == "zurich_meeting":
        story.event(
            _utc(day, "09:00", ZURICH),
            _utc(day, "12:00", ZURICH),
            "Project kickoff",
            (MARTA, JONAS),
            tz=ZURICH,
            location="the client's office",
        )
        story.transcript(
            _utc(day, "09:00", ZURICH),
            _utc(day, "09:40", ZURICH),
            "Project kickoff",
            (MARTA, JONAS),
            [
                "Kickoff: the pilot runs over the summer, the review in September.",
                f"{MARTA.first} owns the data, {JONAS.first} the integration.",
                "Weekly call on Tuesdays.",
            ],
            tz=ZURICH,
        )
        story.event(_utc(day, "19:00", ZURICH), _utc(day, "21:00", ZURICH), "Dinner", (MARTA,), tz=ZURICH)
        story.transaction(
            _utc(day, "21:05", ZURICH), "Gasthaus zur Brücke", -94.5, "restaurants", "CHF", tz=ZURICH
        )
    if kind == "zurich_day":
        story.photo(_utc(day, "17:00", ZURICH), ZH_MUSEUM, album="Art")
        story.photo(_utc(day, "17:20", ZURICH), ZH_MUSEUM, favorite=True)
        story.highlight(_utc(day, "21:30", ZURICH), QUOTES[0], tz=ZURICH)
    if kind == "fly_home_zrh":
        _flight_inferred(story, d, day, points)
    if kind == "marina_prep":
        story.event(_utc(day, "10:00"), _utc(day, "15:00"), "Boat prep", CREW, location="Marina")
        story.trip(_utc(day, "09:45"), _utc(day, "15:00"), "parking", "easypark", MARINA, None, 58, "NOK")
        story.photo(_utc(day, "13:00"), MARINA, (OLA, ANDERS))
        for i, (who, text) in enumerate(CREW_CHAT[:3]):
            story.message(_utc(day, f"{16 + i}:{10 + 7 * i:02d}"), text, False, who, _chat(None))
        story.message(_utc(day, "19:30"), "See you all Monday at nine.", True, OWNER, _chat(None))
    if kind == "boat_out":
        story.event(
            _utc(day, "00:00"),
            _utc(day + timedelta(days=7), "00:00"),
            f"{BOAT_NAME}: summer cruise",
            CREW,
            all_day=True,
        )
        story.note(
            _utc(day, "10:05"),
            f"Cast off at ten with {OLA.name} and {ANDERS.name}. Light wind from the south.",
        )
        story.voice_memo(_utc(day, "16:00"), "Mooring notes", 44.0)
    if kind.startswith("boat_") and kind not in ("boat_out", "boat_home"):
        who, text = CREW_CHAT[d % len(CREW_CHAT)]
        story.message(_utc(day, "08:15"), text, False, who, _chat(None))
        story.photo(_utc(day, "19:30"), _end_spot(kind), (OLA,) if d % 2 else (ANDERS,), favorite=d % 3 == 0)
        story.note(
            _utc(day, "21:00"),
            rng.choice(("Anchored by nine. Grilled.", "Harbour night; showers ashore.", "Flat calm. Stars.")),
        )
        story.health(_utc(day, "14:00"), "heart_rate", rng.randint(95, 130), "bpm", "Watch")
    if kind == "boat_home":
        story.note(_utc(day, "12:00"), "Home. Six nights aboard, no rain. The boat needs a new bilge pump.")
        story.photo(_utc(day, "09:30"), MARINA, (OLA, ANDERS, SIGRID), favorite=True)
    if kind == "home_run":
        story.event(_utc(day, "10:30"), _utc(day, "11:30"), "Run in the park", (TORE,), location="the park")
        story.health(
            _utc(day, "10:35"),
            "workout",
            3300,
            "s",
            "Watch",
            end=_utc(day, "11:30"),
            extra={"activity": "running", "distance_m": 9800},
        )
        story.photo(_utc(day, "11:25"), PARK)
        story.call(_utc(day, "16:00"), EVA, rng.uniform(12, 30), incoming=True)
    if kind == "fly_cph":
        _flight_out(
            story,
            d,
            day,
            "571",
            OSL,
            CPH,
            "Flight to Copenhagen (XY 571)",
            ("16:00", "17:10"),
            ("16:08", "17:05"),
        )
        story.trip(
            _utc(day, "17:55", COPENHAGEN),
            _utc(day, "18:30", COPENHAGEN),
            "transit",
            "metro",
            CPH,
            CPH_HOTEL,
            36,
            "DKK",
            tz=COPENHAGEN,
        )
        story.message(_utc(day, "17:12", COPENHAGEN), "Landed?", False, OLA, _chat(OLA), tz=COPENHAGEN)
        story.message(
            _utc(day, "17:14", COPENHAGEN),
            "Just now. Metro to the hotel.",
            True,
            OWNER,
            _chat(OLA),
            tz=COPENHAGEN,
        )
    if kind == "cph_day":
        story.event(
            _utc(day, "11:00", COPENHAGEN),
            _utc(day, "15:00", COPENHAGEN),
            "Lunch and a walk",
            (FREJA,),
            tz=COPENHAGEN,
        )
        story.photo(_utc(day, "13:00", COPENHAGEN), CPH_FRIEND, (FREJA,), favorite=True)
        story.note(
            _utc(day, "22:00", COPENHAGEN),
            f"Copenhagen with {FREJA.name}. The harbour baths, then her roof.",
            tz=COPENHAGEN,
        )
        story.transaction(
            _utc(day, "14:10", COPENHAGEN), "Café Havnen", -240, "restaurants", "DKK", tz=COPENHAGEN
        )
    if kind == "fly_home_cph":
        _flight_declared(story, d, day)
    # the daily background: a chat with Ola, a page or two, the odd call, something to listen to
    if not kind.startswith("boat"):
        asked, answered = OLA_CHAT[d % len(OLA_CHAT)]
        hour = rng.randint(10, 17)
        story.message(_utc(day, f"{hour}:{rng.randint(0, 59):02d}", tz), asked, False, OLA, _chat(OLA), tz=tz)
        story.message(
            _utc(day, f"{hour}:{rng.randint(0, 59):02d}", tz), answered, True, OWNER, _chat(OLA), tz=tz
        )
    for url, title in rng.sample(PAGES, rng.randint(1, 3)):
        story.browse(_utc(day, f"{rng.randint(7, 22)}:{rng.randint(0, 59):02d}", tz), url, title, tz=tz)
    if d % 3 == 1:
        story.watch(
            _utc(day, f"{rng.randint(19, 22)}:{rng.randint(0, 59):02d}", tz), VIDEOS[d % len(VIDEOS)], tz=tz
        )
    if d % 2 == 0:
        story.listen(
            _utc(day, f"{rng.randint(8, 21)}:{rng.randint(0, 59):02d}", tz),
            TRACKS[d % len(TRACKS)],
            None,
            tz=tz,
        )
    else:
        story.listen(_utc(day, "07:40", tz), None, EPISODES[d % len(EPISODES)], tz=tz)
    if d % 4 == 2:
        story.call(
            _utc(day, f"{rng.randint(17, 20)}:{rng.randint(0, 59):02d}", tz),
            (KARI, EVA, OLA, TORE)[d % 4],
            rng.uniform(3, 25),
            incoming=d % 8 == 2,
            tz=tz,
        )
    if d % 5 == 3 and kind.startswith("office"):
        story.note(_utc(day, "21:30"), NOTES[d % len(NOTES)])
    if d % 6 == 5:
        story.transaction(
            _utc(day, f"{rng.randint(8, 10)}:{rng.randint(0, 59):02d}", tz),
            *MERCHANTS[d % len(MERCHANTS)],
            tz=tz,
        )
    if d % 9 == 4:
        story.highlight(_utc(day, "22:10", tz), QUOTES[(d // 9 + 1) % len(QUOTES)], tz=tz)
    for sender, subject, body, offset in MAILS:
        if offset == d % CYCLE:
            story.mail(
                _utc(day, f"{rng.randint(8, 16)}:{rng.randint(0, 59):02d}", tz), sender, subject, body, tz=tz
            )
    for title, status, offset in TASKS:
        if offset == d % CYCLE:
            story.task(_utc(day, "08:30", tz), title, status, day + timedelta(days=rng.randint(2, 9)))
    for title, seconds, offset in VOICE_MEMOS:
        if offset == d % CYCLE and title != "Mooring notes":
            story.voice_memo(_utc(day, "17:45", tz), title, seconds)


def _end_spot(kind: str) -> Spot:
    legs = OWNER_DAYS[kind]
    last = legs[-1]
    return last.spot if isinstance(last, Stay) else last.b


def _chat(person: Person | None) -> tuple[str, str, str]:
    if person is None:
        return (f"{MMSI}-crew@g.us", "group", f"{BOAT_NAME} crew")
    return (f"{person.phone.lstrip('+')}@s.whatsapp.net", "direct", person.first)


def _flight_out(
    story: _Story,
    d: int,
    day: date,
    number: str,
    origin: Spot,
    destination: Spot,
    title: str,
    scheduled: tuple[str, str],
    actual: tuple[str, str],
) -> None:
    """A calendar entry for the flight and the flight tracker's line of it (evidence `tracked`)."""
    dep, arr = _utc(day, scheduled[0], origin.tz), _utc(day, scheduled[1], destination.tz)
    story.event(dep, arr, title, tz=origin.tz)
    k = (day.isoformat(), CARRIER, number)
    story.drafts.append(
        {
            "id": story.uuid7(dep),
            "recorded_at": story.recorded_at,
            **flights.build(
                source="flighty",
                raw_id=f"fx-{number}@{flights.digest(k)}",
                airports=story.airports,
                date=day.isoformat(),
                carrier=CARRIER,
                number=number,
                from_=flights.airport_ref(origin.name, story.airports),
                to=flights.airport_ref(destination.name, story.airports),
                aircraft={"type": "A320", "registration": "ZZ-ABC"},
                times={
                    "scheduled_departure": dep,
                    "scheduled_arrival": arr,
                    "actual_departure": _utc(day, actual[0], origin.tz),
                    "actual_arrival": _utc(day, actual[1], destination.tz),
                },
                extra={"seat": f"{story.rng.randint(4, 28)}{story.rng.choice('ACDF')}", "cabin": "economy"},
            ),
        }
    )


def _flight_inferred(story: _Story, d: int, day: date, points: list[dict[str, Any]]) -> None:
    """XY 562 home from Zürich: the calendar entry, and the line `logbook infer flights` would
    write from it and the points — the last at ZRH, the first at OSL — so the command finds it
    already in the record and only merges the others."""
    dep, arr = _utc(day, "17:10", ZURICH), _utc(day, "19:15", OSLO)
    event = story.event(dep, arr, "Flight to Oslo (XY 562)", tz=ZURICH)
    before = next(p for p in reversed(points) if p["at"] <= _utc(day, "17:00", ZURICH))
    after = next(p for p in points if p["at"] >= _utc(day, "19:20", OSLO))
    k = (day.isoformat(), CARRIER, "562")
    times = {
        "actual_departure": before["at"],
        "actual_arrival": after["at"],
        "scheduled_departure": dep,
        "scheduled_arrival": arr,
    }
    story.drafts.append(
        {
            "id": story.uuid7(before["at"]),
            "recorded_at": story.recorded_at,
            **flights.build(
                source=flights.INFERENCE,
                raw_id=f"{flights.key_text(k)}@{before['at']}/{after['at']}",
                airports=story.airports,
                date=day.isoformat(),
                carrier=CARRIER,
                number="562",
                carrier_icao=story.airlines.icao(CARRIER),
                from_=flights.airport_ref("ZRH", story.airports),
                to=flights.airport_ref("OSL", story.airports),
                extra={"event": event["id"], "gap": [before["id"], after["id"]]},
                times=times,
            ),
        }
    )


def _flight_declared(story: _Story, d: int, day: date) -> None:
    """XY 572 home from Copenhagen: the calendar entry and the owner's own word (evidence
    `declared`), as `logbook add flight "XY 572 CPH OSL <day> 12:05-13:08"` writes it."""
    dep, arr = _utc(day, "12:00", COPENHAGEN), _utc(day, "13:10", OSLO)
    story.event(dep, arr, "Flight to Oslo (XY 572)", tz=COPENHAGEN)
    declared = f"XY 572 CPH OSL {day.isoformat()} passenger 12:05-13:08"
    k = (day.isoformat(), CARRIER, "572")
    story.drafts.append(
        {
            "id": story.uuid7(dep),
            "recorded_at": story.recorded_at,
            **flights.build(
                source="manual",
                raw_id=f"{flights.key_text(k)}@{flights.digest(declared)}",
                airports=story.airports,
                date=day.isoformat(),
                carrier=CARRIER,
                number="572",
                from_=flights.airport_ref("CPH", story.airports),
                to=flights.airport_ref("OSL", story.airports),
                times={
                    "actual_departure": _utc(day, "12:05", COPENHAGEN),
                    "actual_arrival": _utc(day, "13:08", OSLO),
                },
                extra={"declared": declared},
            ),
        }
    )


def _night(story: _Story, day: date, tz: str) -> None:
    """The night that starts on `day`: sleep stages from the watch, in bed, a few cycles."""
    rng = story.rng
    t = _local(day, "23:40", tz) + timedelta(minutes=rng.randint(0, 80))  # a stage that ends before
    total = timedelta(minutes=rng.randint(420, 520))  # midnight is the previous day's (RFC 0014)
    end = t + total
    story.health(
        _stamp(t), "sleep", round(total.total_seconds()), "s", "Watch", end=_stamp(end), tz=tz, stage="in_bed"
    )
    while t < end:
        for stage, lo, hi in (("core", 35, 70), ("deep", 15, 40), ("rem", 12, 30), ("awake", 1, 6)):
            if stage == "awake" and rng.random() < 0.5:
                continue
            length = min(timedelta(minutes=rng.randint(lo, hi)), end - t)
            if length <= timedelta(0):
                break
            story.health(
                _stamp(t),
                "sleep",
                round(length.total_seconds()),
                "s",
                "Watch",
                end=_stamp(t + length),
                tz=tz,
                stage=stage,
            )
            t += length


def _daytime_health(story: _Story, day: date, tz: str, kind: str) -> None:
    rng = story.rng
    story.health(_utc(day, "06:00", tz), "resting_hr", rng.randint(52, 61), "bpm", "Watch", tz=tz)
    busy = (
        1.4
        if kind.startswith(("zurich", "cph", "home_run", "cabin"))
        else 0.8
        if kind.startswith("boat")
        else 1.0
    )
    start = _local(day, "07:00", tz).astimezone(UTC).replace(minute=0)
    for i in range(60):  # quarter hours from seven in the morning to ten at night
        t = start + timedelta(minutes=15 * i)
        count = round(rng.randint(50, 220) * busy)
        story.health(
            _stamp(t),
            "steps",
            count,
            "count",
            "Phone",
            end=_stamp(t + timedelta(minutes=15)),
            tz=tz,
            extra={"samples": rng.randint(2, 9)},
        )
    for hour in range(8, 23, 2):
        story.health(
            _utc(day, f"{hour:02d}:{rng.randint(0, 59):02d}", tz),
            "heart_rate",
            rng.randint(58, 104),
            "bpm",
            "Watch",
            tz=tz,
        )


def _resolutions(story: _Story, people: tuple[Person, ...] = PEOPLE, first: date = START) -> None:
    """The circle, named the day before the record's first day, as a contacts import would."""
    at = _utc(first - timedelta(days=1), "08:00")
    for person in people:
        story.resolution(("email", person.email), person, at)
        story.resolution(("phone", person.phone), person, at)
        if person.face:
            story.resolution(("provider_id", f"immich:{person.face}"), person, at)


def story_of(days: int, seed: int, recorded_at: str) -> _Story:
    """The whole record as drafts, in a plausible import order: people first, then each day's
    tracks (the owner's, then the boat's), its lines and the night; keepers last, as
    `logbook infer keepers` would add them."""
    story = _Story(random.Random(seed), flights.Airports.load(), flights.Airlines.load(), recorded_at)
    _resolutions(story)
    for d in range(days):
        day = START + timedelta(days=d)
        kind = DAY_TYPES[d % CYCLE]
        points = story.track(day, OWNER_DAYS[kind], None, 5)
        story.track(day, BOAT_DAYS.get(kind, BERTH), BOAT, 10 if kind in BOAT_DAYS else 60)
        _day(story, d, day, points)
        _daytime_health(story, day, _zone_of(kind), kind)
        if d + 1 < days:
            _night(story, day, _end_spot(kind).tz)
    for keeper in keepers.infer(story.photos):
        story.drafts.append({"id": story.uuid7(keeper["at"]), "recorded_at": recorded_at, **keeper})
    return story


def generate(root: Path, days: int | None = None, seed: int = 1, years: int | None = None) -> Logbook:
    """Write the demo record under `root` (a folder that is not yet a logbook) and return it:
    `logbook.json` with an owner id from the seed, every line, the transcripts' text in the
    attachment store, two notes files, `assets.json` with the boat and `places.json` with home,
    the office, the marina and the cabin. `days` (30 by default) is the month from `START`;
    `years` instead is the persona's whole life to the month's last day (`logbook.demo_life`),
    with its own places and the homes she moved between."""
    if days is not None and years is not None:
        raise ValueError("give days or years, not both")
    if years is not None:
        from .. import demo_life

        if years < 1:
            raise ValueError("years must be at least 1")
        return demo_life.generate(root, years, seed)
    days = 30 if days is None else days
    if days < 1:
        raise ValueError("days must be at least 1")
    last = START + timedelta(days=days - 1)
    recorded_at = _utc(last + timedelta(days=1), "08:00")
    story = story_of(days, seed, recorded_at)
    notes = {}
    for d in range(days):
        text = NOTE_FILES.get(DAY_TYPES[d % CYCLE])
        if text:
            notes[START + timedelta(days=d)] = text
    return write(root, seed, story, START, PLACES, notes)


def write(
    root: Path,
    seed: int,
    story: _Story,
    first: date,
    places: dict[Spot, dict[str, Any]],
    notes: dict[date, str],
) -> Logbook:
    """The record on disk: the meta with an owner id from the seed, the blobs, the lines, the
    boat in `assets.json`, `places` in `places.json` and a notes file per day of `notes`."""
    lb = Logbook.init(root, TZ)
    meta = lb.meta
    meta["owner_id"] = str(uuid.uuid5(NAMESPACE, f"owner:{seed}"))
    meta["created_at"] = _utc(first - timedelta(days=1), "06:00")
    meta["owner_emails"] = [OWNER.email]
    lb._save_meta(meta)
    for blob in story.blobs:
        lb.attach(blob)
    lb.append_many(story.drafts)
    (lb.root / "assets.json").write_text(
        json.dumps(
            {
                "assets": [
                    {"id": BOAT, "kind": "yacht", "name": BOAT_NAME, "mmsi": MMSI, "registration": "ZZ-NLY"}
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    for spot, entry in places.items():
        named_places.add(
            lb.root,
            named_places.Place(
                spot.name,
                spot.lat,
                spot.lon,
                float(entry["radius_m"]),
                str(entry["kind"]),
                tuple(entry.get("tags", ())),
                entry.get("country"),
            ),
        )
    for day, text in notes.items():
        folder = lb.root / "notes" / str(day.year)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{day.isoformat()}.md").write_bytes(text.encode("utf-8"))
    return lb


NOTE_FILES = {
    "cabin_out": "Cabin. Snow still in the gullies above the tree line. Ola split wood; I read.\n",
    "boat_harbour": "Harbour day. Walked into town for bread and a chart. The bilge pump is dying.\n",
}
