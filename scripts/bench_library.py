"""Benchmark the Library (`logbook serve`) on a synthetic record of millions of lines.

A pure benchmark: nothing here changes what the product does, and it never touches a real record.
It builds a synthetic record shaped like a real one over ten years (19 October 2016 to 18 October
2026) — by default 5,000,000 lines: about 55% messages (a few hundred people, a few thousand handles,
direct chats and groups), 15% mail (people, companies, newsletters), 15% location fixes (home, the
office, the cabin, trips with flights on carrier XY, the boat's AIS track), 8% photos (faces of the
people the owner resolved, favourites), the rest calendar entries with attendees, notes, Notion and
Drive events, calls (some with a transcript), sessions with an agent; the people resolved, orgs and
ideas named with their status lines, a few retractions, goals and a chapter, some signed days and
stars — indexes it, then starts the Library in-process (`serve.Site.respond`, as the tests call it;
no socket) and times every route:

    cold          the first request after the server starts, nothing of this process cached
    warm          the second request, at the same head
    after-append  a third request after one new line is appended (a sync: the head moves)
    peak MB       the child's peak resident memory (`ru_maxrss`), the server's start included

Each route runs in a subprocess of its own, so one route's caches never warm another's and the peak
is that route's. The page cache of the operating system is warm after the first run, as it is on a
machine that serves the record every day.

    uv run python scripts/bench_library.py --lines 1000000 --root ~/bench-1m --keep --markdown
    uv run python scripts/bench_library.py --root ~/bench-1m --profile /people --profile /manifest

`--root` keeps the record (and its index, under `<root>/cache`) for the next run, which reuses it
when it holds the lines asked for; without it the record is built in a temporary folder and deleted
at the end. `--routes` runs some of the routes; `--profile ROUTE` prints the top functions of that
route's cold request by cumulative time (cProfile). `--out` writes the table as JSON.

Everything generated is synthetic: the Oslo persona (Ines Nordmann and the Nordmann family, who do not
exist), addresses at example.org, phone numbers in the reserved UK range 07700 900xxx, the airline XY,
the boat's MMSI 970xxxxxx. No real personal data, and no network.
"""

from __future__ import annotations

import argparse
import bisect
import contextlib
import cProfile
import io
import itertools
import json
import math
import os
import platform
import pstats
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

LINES = 5_000_000
SEED = 7
TZ = "Europe/Oslo"
ZONE = ZoneInfo(TZ)
FIRST_DAY = date(2016, 10, 19)
LAST_DAY = date(2026, 10, 18)
NOW = datetime(2026, 10, 18, 16, 0, tzinfo=UTC)  # the Library's clock: the afternoon of the last day
TIMEOUT_S = 3600  # one route's child, at most
OWNER = {"name": "Ines Nordmann", "email": "ines.nordmann@example.org", "phone": "+447700900000"}
PEOPLE = 300  # resolved people (`--people`)
PHONED = 600  # the people with a number: 07700 900001 up; the reserved range holds 1,000, the rest are mail
PHONES = 1000  # the whole reserved range: the owner, the people, the rest unresolved
EMAILS = 2200  # unresolved addresses at example.org
GROUPS = 40
FACES = 60  # the people with a face in the photo library
ORGS = 30
IDEAS = 40
PAGES = 400  # Notion pages
FILES = 300  # Drive files
BOAT = {"id": "solvind", "kind": "yacht", "name": "Solvind", "mmsi": "970000001"}
SHARE = {  # the shape of the record, as shares of its lines
    "message": 0.55,
    "mail": 0.15,
    "location": 0.15,
    "photo": 0.08,
    "event": 0.025,
    "notion": 0.012,
    "drive": 0.012,
    "call": 0.012,
    "transcript": 0.004,
    "note": 0.005,
}
FIRST_NAMES = (
    "Ines",
    "Ola",
    "Kari",
    "Per",
    "Liv",
    "Nils",
    "Eva",
    "Marta",
    "Sigrid",
    "Anders",
    "Freja",
    "Jonas",
    "Astrid",
    "Bjørn",
    "Camilla",
    "Dag",
    "Elin",
    "Frode",
    "Guro",
    "Hans",
    "Ingrid",
    "Jon",
)
SURNAMES = ("Nordmann", "Bakke", "Lie", "Strand", "Moe", "Berg", "Lund", "Dahl", "Vik", "Foss", "Holm")
WORDS = (
    "harbour",
    "tide",
    "sail",
    "mast",
    "chart",
    "ferry",
    "cabin",
    "fjord",
    "anchor",
    "bay",
    "dinner",
    "weekend",
    "photos",
    "keys",
    "boat",
    "train",
    "office",
    "meeting",
    "draft",
    "plan",
    "lunch",
    "coffee",
    "invoice",
    "kiosk",
    "map",
    "ticket",
    "garden",
    "sauna",
    "paint",
    "winter",
    "summer",
    "rope",
    "engine",
)
ORG_WORDS = ("Verft", "Havbris", "Tidevann", "Fjordkiosk", "Seil", "Bølge", "Skjær", "Losen", "Ankre", "Kai")


class Spot(NamedTuple):
    name: str
    lat: float
    lon: float


HOME = Spot("Home", 59.9139, 10.7522)
OFFICE = Spot("Office", 59.9100, 10.7600)
CAFE = Spot("Cafe", 59.9200, 10.7400)
MARINA = Spot("Marina", 59.9050, 10.7350)
CABIN = Spot("Cabin", 59.7000, 10.6034)
CITIES = (  # a trip's city, its hotel and its airport
    (Spot("Bergen", 60.3913, 5.3221), "BGO"),
    (Spot("Trondheim", 63.4305, 10.3951), "TRD"),
    (Spot("Copenhagen", 55.6761, 12.5683), "CPH"),
    (Spot("Zürich", 47.3769, 8.5417), "ZRH"),
    (Spot("Lisbon", 38.7223, -9.1393), "LIS"),
    (Spot("Rome", 41.9028, 12.4964), "FCO"),
)
OSL = Spot("OSL", 60.1939, 11.1004)
PLACES = {
    "Home": {"lat": HOME.lat, "lon": HOME.lon, "radius_m": 150, "kind": "home"},
    "Office": {"lat": OFFICE.lat, "lon": OFFICE.lon, "radius_m": 120},
    "Marina": {
        "lat": MARINA.lat,
        "lon": MARINA.lon,
        "radius_m": 150,
        "kind": "asset-berth",
        "tags": ["boat"],
    },
    "Cabin": {"lat": CABIN.lat, "lon": CABIN.lon, "radius_m": 200},
}
ROUTES = (
    "/",
    "/today",
    "/day/{day}",
    "/days",
    "/trips",
    "/journeys",
    "/journeys/{journey}",
    "/people",
    "/people/{person}",
    "/manifest",
    "/org/{org}",
    "/manifest/people",
    "/ideas",
    "/idea/{idea}",
    "/places",
    "/assets",
    "/gaps",
    "/world",
    "/promises",
    "/goals",
    "/agents",
    "/week/{week}",
)
JOURNEY_LINK = re.compile(r'href="/journeys/(\d{4}-\d{2}-\d{2}/\d{4}-\d{2}-\d{2})"')


# -- the people, the handles, the orgs, the ideas ---------------------------------------------------------


def _uuid(n: int, block: int) -> str:
    return f"019cadd3-6bc0-7dcd-{block:04x}-{n:012x}"


def _slug(text: str) -> str:
    plain = {"ø": "o", "å": "a", "æ": "ae"}
    return "".join(plain.get(c, c) for c in text.lower() if c.isalnum() or c in " øåæ")


class Cast:
    """Everyone and everything the record speaks of, made from the seed."""

    def __init__(self, rng: random.Random, people: int = PEOPLE):
        self.people: list[dict[str, Any]] = []
        phoned = min(people, PHONED)
        for n in range(people):
            first = FIRST_NAMES[n % len(FIRST_NAMES)]
            last = SURNAMES[(n // len(FIRST_NAMES)) % len(SURNAMES)]
            name = (
                f"{first} {last}"
                if n < len(FIRST_NAMES) * len(SURNAMES)
                else f"{first} {chr(65 + n % 26)}. {last}"
            )
            self.people.append(
                {
                    "id": _uuid(n + 1, 0x9133),
                    "name": name,
                    "email": f"{_slug(first)}.{_slug(last)}.{n}@example.org",
                    "phone": f"+447700900{n + 1:03d}" if n < phoned else None,  # reached by mail
                    "face": f"p_{n}" if n < FACES else None,
                }
            )
        self.phones = [f"+447700900{n:03d}" for n in range(phoned + 1, PHONES)]  # unresolved numbers
        self.emails = [f"contact.{n}@example.org" for n in range(EMAILS)]  # unresolved addresses
        weights = [1 / (r + 1) ** 1.1 for r in range(people)]  # a few people most of the time
        self.cumulative = list(itertools.accumulate(weights))
        self.groups: list[dict[str, Any]] = [
            {
                "id": f"120363{n:012d}@g.us",
                "name": f"{rng.choice(WORDS).title()} {n}",
                "members": rng.sample(range(phoned), rng.randint(3, 10)),
            }
            for n in range(GROUPS)
        ]
        self.orgs = [
            {
                "id": _uuid(n + 1, 0x0A10),
                "name": f"Nordmann {ORG_WORDS[n % len(ORG_WORDS)]} {n} AS",
                "domain": f"{_slug(ORG_WORDS[n % len(ORG_WORDS)])}{n}.example.org",
            }
            for n in range(ORGS)
        ]
        self.pages = [_uuid(n + 1, 0x1F2E) for n in range(PAGES)]
        self.ideas = [
            {
                "id": _uuid(n + 1, 0x1DEA),
                "name": f"the {rng.choice(WORDS)} {rng.choice(WORDS)} {n}",
                "page": self.pages[n],
            }
            for n in range(IDEAS)
        ]
        self.files = [f"drivefile{n:05d}" for n in range(FILES)]

    def person(self, rng: random.Random) -> dict[str, Any]:
        return self.people[bisect.bisect_left(self.cumulative, rng.random() * self.cumulative[-1])]

    def phoned(self, rng: random.Random) -> dict[str, Any]:
        """Someone with a number, for a call: drawn as `person` draws, again until they have one."""
        p = self.person(rng)
        while p["phone"] is None:
            p = self.person(rng)
        return p


# -- the days ----------------------------------------------------------------------------------------------


def _utc(day: date, minute: float) -> datetime:
    local = datetime(day.year, day.month, day.day, tzinfo=ZONE) + timedelta(minutes=minute)
    return local.astimezone(UTC)


def _stamp(when: datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


class Trip(NamedTuple):
    first: date
    last: date
    city: Spot
    airport: str


def _trips(rng: random.Random) -> dict[date, Trip]:
    """About five trips a year, two to nine days, to one of the cities; the days of each."""
    out: dict[date, Trip] = {}
    day = FIRST_DAY + timedelta(days=20)
    while day < LAST_DAY - timedelta(days=12):
        day += timedelta(days=rng.randint(40, 100))
        length = rng.randint(2, 9)
        city, airport = rng.choice(CITIES)
        trip = Trip(day, day + timedelta(days=length - 1), city, airport)
        for k in range(length):
            out[day + timedelta(days=k)] = trip
        day = trip.last
    return out


def _segments(day: date, trip: Trip | None, rng: random.Random) -> list[tuple[float, float, Spot, Spot]]:
    """Where the owner is through the day, as (start minute, end minute, from, to) — a stay where
    from is to — in local minutes."""
    if trip is not None:
        here = trip.city
        if day == trip.first:
            return [
                (0, 360, HOME, HOME),
                (360, 420, HOME, OSL),
                (420, 540, OSL, here),
                (540, 1440, here, here),
            ]
        if day == trip.last:
            return [
                (0, 900, here, here),
                (900, 1020, here, OSL),
                (1020, 1080, OSL, HOME),
                (1080, 1440, HOME, HOME),
            ]
        return [(0, 600, here, here), (600, 720, here, here), (720, 1440, here, here)]
    if day.weekday() < 5:
        lunch = CAFE if rng.random() < 0.3 else OFFICE
        return [
            (0, 470, HOME, HOME),
            (470, 490, HOME, OFFICE),
            (490, 690, OFFICE, OFFICE),
            (690, 760, lunch, lunch),
            (760, 1040, OFFICE, OFFICE),
            (1040, 1060, OFFICE, HOME),
            (1060, 1440, HOME, HOME),
        ]
    if day.weekday() == 5 and rng.random() < 0.25:
        away = MARINA if day.month in (6, 7, 8) else CABIN
        return [
            (0, 540, HOME, HOME),
            (540, 600, HOME, away),
            (600, 1080, away, away),
            (1080, 1140, away, HOME),
            (1140, 1440, HOME, HOME),
        ]
    return [(0, 660, HOME, HOME), (660, 780, CAFE, CAFE), (780, 1440, HOME, HOME)]


def _where(segments: list[tuple[float, float, Spot, Spot]], minute: float) -> tuple[float, float]:
    for start, end, a, b in segments:
        if start <= minute < end:
            f = (minute - start) / (end - start)
            return a.lat + (b.lat - a.lat) * f, a.lon + (b.lon - a.lon) * f
    last = segments[-1][3]
    return last.lat, last.lon


def _jitter(where: tuple[float, float], metres: float, rng: random.Random) -> tuple[float, float]:
    bearing, d = rng.uniform(0, 2 * math.pi), rng.uniform(0, metres)
    return (
        round(where[0] + d * math.cos(bearing) / 111_320, 6),
        round(where[1] + d * math.sin(bearing) / (111_320 * math.cos(math.radians(where[0]))), 6),
    )


def _quotas(lines: int) -> list[tuple[date, int]]:
    """Lines per day: the record grows over the years (a third of the rate at the start), weekends
    are lighter, and every day has some."""
    days = [FIRST_DAY + timedelta(days=k) for k in range((LAST_DAY - FIRST_DAY).days + 1)]
    weights = [(0.35 + 0.65 * k / len(days)) * (0.7 if d.weekday() >= 5 else 1.0) for k, d in enumerate(days)]
    total = sum(weights)
    out, carried = [], 0.0
    for d, w in zip(days, weights, strict=True):
        exact = lines * w / total + carried
        n = int(exact)
        carried = exact - n
        out.append((d, n))
    return out


SENTENCES = (
    "See you at the {0} at {1}.",
    "Did you get the {0}?",
    "The {0} is ready.",
    "Thanks for the {0}!",
    "Running late, the {0} again.",
    "Can we move the {0} to {1}?",
    "Good {0} today.",
    "Back from the {0}.",
)
PROMISES = (
    "I'll send you the {0} by Friday.",
    "I will bring the {0} on Saturday.",
    "I'll book the {0} for us.",
)


def _text(rng: random.Random, promise: bool = False) -> str:
    pool = PROMISES if promise else SENTENCES
    return rng.choice(pool).format(rng.choice(WORDS), f"{rng.randint(8, 21)}:{rng.choice(('00', '30'))}")


class Generator:
    """The record's drafts, day by day, in time order."""

    def __init__(self, lines: int, seed: int, people: int = PEOPLE, open_flights: int = 0):
        self.rng = random.Random(seed)
        self.cast = Cast(self.rng, people)
        self.trips = _trips(self.rng)
        self.lines = lines
        self.counts: dict[str, int] = {}
        self.carried: dict[str, float] = {}
        self.n = 0
        self.open_flights = open_flights  # every Nth flight without its arrival (0: none), as #344's
        self.flown = 0

    def drafts(self) -> Iterator[dict[str, Any]]:
        yield from self._resolutions()
        orgs_named = ideas_named = 0
        quotas = _quotas(self.lines - self._fixed())
        for k, (day, quota) in enumerate(quotas):
            yield from self._day(day, quota)
            # the owner names the orgs and the ideas over the years, and says where each stands
            while orgs_named < ORGS and k >= (orgs_named + 1) * len(quotas) // (ORGS + 2):
                yield from self._org(day, self.cast.orgs[orgs_named])
                orgs_named += 1
            while ideas_named < IDEAS and k >= (ideas_named + 1) * len(quotas) // (IDEAS + 2):
                yield from self._idea(day, self.cast.ideas[ideas_named])
                ideas_named += 1

    def _fixed(self) -> int:
        people = self.cast.people
        return 2 + len(people) + sum(1 for p in people if p["phone"]) + FACES + ORGS * 3 + IDEAS * 3

    def _count(self, kind: str) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + 1

    def _resolutions(self) -> Iterator[dict[str, Any]]:
        at = _stamp(_utc(FIRST_DAY, 480))
        refs = [
            ("email", OWNER["email"], "owner", OWNER["name"]),
            ("phone", OWNER["phone"], "owner", OWNER["name"]),
        ]
        for p in self.cast.people:
            refs.append(("email", p["email"], p["id"], p["name"]))
            if p["phone"]:
                refs.append(("phone", p["phone"], p["id"], p["name"]))
            if p["face"]:
                refs.append(("provider_id", f"immich:{p['face']}", p["id"], p["name"]))
        for kind, value, entity, label in refs:
            self._count("resolution")
            yield {
                "at": at,
                "source": "manual",
                "kind": "resolution",
                "tier": 2,
                "payload": {
                    "schema": "resolution/v1",
                    "ref": {"kind": kind, "value": value},
                    "entity": {"type": "person", "id": entity, "registry": "logbook"},
                    "label": label,
                    "method": "owner",
                },
            }

    def _org(self, day: date, org: dict[str, Any]) -> Iterator[dict[str, Any]]:
        from logbook.contrib import entities

        at = _stamp(_utc(day, 1260))
        line_id = _uuid(int(org["id"][-12:], 16), 0xE0A1)
        payload = entities.entity_payload(
            "org", org["id"], org["name"], refs=[("domain", org["domain"])], key=f"domain:{org['domain']}"
        )
        yield {
            "id": line_id,
            "at": at,
            "source": entities.SOURCE,
            "kind": entities.ENTITY,
            "tier": entities.TIER,
            "payload": payload,
        }
        first = self.rng.choice(("hold", "passed"))
        hold = entities.status_payload(
            "org", org["id"], org["name"], first, "the first look" if first == "passed" else None
        )
        status_id = _uuid(int(org["id"][-12:], 16), 0xE0A2)
        yield {
            "id": status_id,
            "at": at,
            "source": entities.SOURCE,
            "kind": entities.STATUS,
            "tier": entities.status_tier("org"),
            "payload": hold,
        }
        later = _stamp(_utc(day + timedelta(days=30), 1260))
        then = entities.status_payload(
            "org", org["id"], org["name"], "add", "follow-on", supersedes=status_id
        )
        yield {
            "at": later,
            "source": entities.SOURCE,
            "kind": entities.STATUS,
            "tier": entities.status_tier("org"),
            "payload": then,
        }
        self.counts["entity"] = self.counts.get("entity", 0) + 1
        self.counts["status"] = self.counts.get("status", 0) + 2

    def _idea(self, day: date, idea: dict[str, Any]) -> Iterator[dict[str, Any]]:
        from logbook.contrib import entities

        at = _stamp(_utc(day, 1270))
        payload = entities.entity_payload(
            "idea", idea["id"], idea["name"], refs=[("page", idea["page"])], key=f"page:{idea['page']}"
        )
        yield {
            "at": at,
            "source": entities.SOURCE,
            "kind": entities.ENTITY,
            "tier": entities.TIER,
            "payload": payload,
        }
        status_id = _uuid(int(idea["id"][-12:], 16), 0xE0A3)
        spark = entities.status_payload("idea", idea["id"], idea["name"], "spark")
        yield {
            "id": status_id,
            "at": at,
            "source": entities.SOURCE,
            "kind": entities.STATUS,
            "tier": entities.TIER,
            "payload": spark,
        }
        later = _stamp(_utc(day + timedelta(days=60), 1270))
        word = self.rng.choice(("exploring", "build", "killed"))
        reason = "not now" if word == "killed" else None
        then = entities.status_payload("idea", idea["id"], idea["name"], word, reason, supersedes=status_id)
        yield {
            "at": later,
            "source": entities.SOURCE,
            "kind": entities.STATUS,
            "tier": entities.TIER,
            "payload": then,
        }
        self.counts["entity"] = self.counts.get("entity", 0) + 1
        self.counts["status"] = self.counts.get("status", 0) + 2

    def _day(self, day: date, quota: int) -> Iterator[dict[str, Any]]:
        rng = self.rng
        trip = self.trips.get(day)
        segments = _segments(day, trip, rng)
        drafts: list[tuple[float, dict[str, Any]]] = []
        counts: dict[str, int] = {}
        for kind, share in SHARE.items():  # the fractions carried from day to day, so a rare kind still comes
            exact = quota * share + self.carried.get(kind, 0.0)
            counts[kind] = int(exact)
            self.carried[kind] = exact - counts[kind]
        boat = 0
        if day.month in (6, 7, 8) or rng.random() < 0.2:  # the boat's AIS: a share of the fixes
            boat = counts["location"] // 6
            counts["location"] -= boat
        n = counts["location"]
        for i in range(n):
            minute = (i + rng.random() * 0.5) * 1440 / max(n, 1)
            drafts.append((minute, self._fix(day, minute, _jitter(_where(segments, minute), 25, rng))))
        for i in range(boat):
            minute = (i + 0.5) * 1440 / boat
            drafts.append(
                (minute, self._fix(day, minute, _jitter((MARINA.lat, MARINA.lon), 8, rng), BOAT["id"]))
            )
        if trip is not None and day in (trip.first, trip.last):
            out = day == trip.first
            dep, arr = (420, 540) if out else (900, 1020)
            drafts.append(
                (
                    dep,
                    self._flight(
                        day, dep, arr, "OSL" if out else trip.airport, trip.airport if out else "OSL"
                    ),
                )
            )
        for _ in range(counts["message"]):
            minute = rng.uniform(420, 1410)
            drafts.append((minute, self._message(day, minute)))
        for _ in range(counts["mail"]):
            minute = rng.uniform(360, 1380)
            drafts.append((minute, self._mail(day, minute)))
        for _ in range(counts["photo"]):
            minute = rng.uniform(480, 1320)
            drafts.append((minute, self._photo(day, minute, _jitter(_where(segments, minute), 15, rng))))
        for _ in range(counts["event"]):
            minute = rng.choice(range(480, 1200, 30))
            drafts.append((minute, self._event(day, minute)))
        for _ in range(counts["notion"]):
            minute = rng.uniform(480, 1320)
            drafts.append((minute, self._notion(day, minute)))
        for _ in range(counts["drive"]):
            minute = rng.uniform(480, 1320)
            drafts.append((minute, self._drive(day, minute)))
        for _ in range(counts["call"]):
            minute = rng.uniform(480, 1320)
            drafts.append((minute, self._call(day, minute)))
        for _ in range(counts["transcript"]):
            minute = rng.uniform(540, 1260)
            drafts.append((minute, self._transcript(day, minute)))
        for _ in range(counts["note"]):
            minute = rng.uniform(1200, 1380)
            drafts.append((minute, self._note(day, minute)))
        drafts.sort(key=lambda pair: pair[0])
        for _minute, draft in drafts:
            self._count(str(draft["kind"]))
            yield draft

    def _fix(
        self, day: date, minute: float, where: tuple[float, float], subject: str | None = None
    ) -> dict[str, Any]:
        at = _stamp(_utc(day, minute))
        source = "ais" if subject else "dawarich"
        payload: dict[str, Any] = {
            "schema": "location/v1",
            "lat": where[0],
            "lon": where[1],
            "accuracy_m": 12,
            "raw_id": f"{source}:{subject or 'owner'}:{at}",
        }
        if subject:
            payload["subject"] = subject
        return {"at": at, "source": source, "kind": "location", "tier": 1, "payload": payload}

    def _message(self, day: date, minute: float) -> dict[str, Any]:
        rng = self.rng
        at = _stamp(_utc(day, minute))
        from_me = rng.random() < 0.45
        promise = rng.random() < 0.001
        sender: dict[str, Any] | None
        roll = rng.random()
        if roll < 0.1:
            group = rng.choice(self.cast.groups)
            chat = {"id": group["id"], "type": "group", "name": group["name"]}
            member = self.cast.people[int(rng.choice(group["members"]))]
            sender = {"kind": "phone", "value": member["phone"], "name": member["name"].split()[0]}
        elif roll < 0.8:
            p = self.cast.person(rng)
            if p["phone"] is None:  # no number: iMessage by their address
                chat = {"id": p["email"], "type": "direct", "name": p["name"]}
                sender = {"kind": "email", "value": p["email"], "name": p["name"].split()[0]}
            else:
                chat = {"id": f"{p['phone'][1:]}@s.whatsapp.net", "type": "direct", "name": p["name"]}
                sender = {"kind": "phone", "value": p["phone"], "name": p["name"].split()[0]}
        else:
            phone = rng.choice(self.cast.phones)
            chat = {"id": f"{phone[1:]}@s.whatsapp.net", "type": "direct", "name": "Chat"}
            sender = {"kind": "phone", "value": phone}
        payload: dict[str, Any] = {
            "schema": "message/v1",
            "raw_id": f"m-{at}-{self.n}",
            "chat": chat,
            "from_me": from_me,
            "text": _text(rng, promise),
        }
        self.n += 1
        if not from_me:
            payload["sender"] = sender
        return {"at": at, "source": "whatsapp", "kind": "message", "tier": 2, "payload": payload}

    def _mail(self, day: date, minute: float) -> dict[str, Any]:
        rng = self.rng
        at = _stamp(_utc(day, minute))
        roll = rng.random()
        if roll < 0.35:
            p = self.cast.person(rng)
            other = {"email": p["email"], "name": p["name"]}
        elif roll < 0.55:
            org = rng.choice(self.cast.orgs)
            other = {"email": f"post@{org['domain']}", "name": org["name"]}
        elif roll < 0.8:
            other = {"email": f"news@nytt{rng.randint(0, 19)}.example.org", "name": "Nytt"}
        else:
            other = {"email": rng.choice(self.cast.emails), "name": "Contact"}
        sent = rng.random() < 0.2
        owner = {"email": OWNER["email"], "name": OWNER["name"]}
        message_id = f"{at}.{self.n}@mail.example.org"
        self.n += 1
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
                "from": owner if sent else other,
                "to": [other if sent else owner],
                "subject": f"{rng.choice(WORDS).title()} {rng.choice(WORDS)}",
                "direction": "sent" if sent else "received",
                "size": rng.randint(800, 90_000),
            },
        }

    def _photo(self, day: date, minute: float, where: tuple[float, float]) -> dict[str, Any]:
        rng = self.rng
        at = _stamp(_utc(day, minute))
        faces = (
            [p["face"] for p in rng.sample(self.cast.people[:FACES], rng.randint(1, 3))]
            if rng.random() < 0.3
            else []
        )
        payload: dict[str, Any] = {
            "schema": "photo/v1",
            "asset_id": f"p-{at}-{self.n}",
            "library": "immich",
            "file_name": f"IMG_{self.n:07d}.HEIC",
            "media": "image",
            "provenance": "camera",
            "faces": len(faces),
            "people": faces,
            "raw_id": f"p-{at}-{self.n}",
            "lat": where[0],
            "lon": where[1],
        }
        self.n += 1
        if rng.random() < 0.02:
            payload["extra"] = {"favorite": True}
        return {"at": at, "source": "immich", "kind": "photo", "tier": 1, "payload": payload}

    def _event(self, day: date, minute: float) -> dict[str, Any]:
        rng = self.rng
        start, end = _utc(day, minute), _utc(day, minute + rng.choice((30, 60, 90)))
        who = [self.cast.person(rng) for _ in range(rng.randint(1, 4))]
        attendees = [
            {"ref": {"kind": "email", "value": p["email"]}, "name": p["name"], "response": "accepted"}
            for p in who
        ]
        title = f"{rng.choice(WORDS).title()} with {who[0]['name'].split()[0]}"
        self.n += 1
        return {
            "at": _stamp(start),
            "end": _stamp(end),
            "source": "ios-calendar",
            "kind": "event",
            "tier": 1,
            "payload": {
                "schema": "event/v1",
                "raw_id": f"e-{_stamp(start)}-{self.n}",
                "title": title,
                "all_day": False,
                "attendees": attendees,
            },
        }

    def _notion(self, day: date, minute: float) -> dict[str, Any]:
        rng = self.rng
        at = _stamp(_utc(day, minute))
        k = rng.randrange(PAGES)
        page = self.cast.pages[k]
        idea = k < IDEAS
        extra: dict[str, Any] = {
            "action": rng.choice(("edited", "created")),
            "page": {"id": page},
            "path": ["Ines' hub", "Ideas" if idea else "Notes"],
        }
        if idea:
            extra["properties"] = {"Type": "Idea"}
        self.n += 1
        return {
            "at": at,
            "end": None,
            "tz": None,
            "source": "notion",
            "kind": "event",
            "tier": 1,
            "payload": {
                "schema": "event/v1",
                "raw_id": f"{page}/{day.isoformat()}/{self.n}",
                "title": self.cast.ideas[k]["name"] if idea else f"Notes on the {rng.choice(WORDS)} {k}",
                "calendar": {"id": "notion", "name": "Notion"},
                "all_day": False,
                "modified_at": at,
                "extra": extra,
            },
        }

    def _drive(self, day: date, minute: float) -> dict[str, Any]:
        rng = self.rng
        at = _stamp(_utc(day, minute))
        file_id = rng.choice(self.cast.files)
        self.n += 1
        return {
            "at": at,
            "end": None,
            "tz": TZ,
            "source": "drive",
            "kind": "event",
            "tier": 1,
            "payload": {
                "schema": "event/v1",
                "raw_id": f"{file_id}/edit@{at}/{self.n}",
                "title": f"Edited {file_id}",
                "calendar": {"id": "google-drive", "name": "Google Drive"},
                "all_day": False,
                "modified_at": at,
                "extra": {
                    "activity": "edit",
                    "count": 1,
                    "file": {"id": file_id, "name": f"{file_id}.txt"},
                    "actors": [{"kind": "owner"}],
                    "by_owner": True,
                    "activities": [str(self.n)],
                },
            },
        }

    def _call(self, day: date, minute: float) -> dict[str, Any]:
        rng = self.rng
        at = _stamp(_utc(day, minute))
        p = self.cast.phoned(rng)
        seconds = rng.choice((0, 45, 300, 900))
        self.n += 1
        return {
            "at": at,
            "source": "ios-calls",
            "kind": "call",
            "tier": 1,
            "payload": {
                "schema": "call/v1",
                "raw_id": f"c-{at}-{self.n}",
                "direction": rng.choice(("incoming", "outgoing")),
                "answered": seconds > 0,
                "duration_s": seconds,
                "counterparty": {"kind": "phone", "value": p["phone"]},
                "service": "cellular",
            },
        }

    def _transcript(self, day: date, minute: float) -> dict[str, Any]:
        rng = self.rng
        start, end = _utc(day, minute), _utc(day, minute + 40)
        self.n += 1
        if rng.random() < 0.3:  # a session with an agent
            return {
                "at": _stamp(start),
                "end": _stamp(end),
                "source": "claude-code",
                "kind": "transcript",
                "tier": 2,
                "payload": {
                    "schema": "transcript/v1",
                    "provider": "claude-code",
                    "raw_id": f"claude-code:{_uuid(self.n, 0x0193)}",
                    "title": f"A {rng.choice(WORDS)} planner for Solvind",
                    "participants": [{"name": "Ines"}, {"name": "Claude", "machine": True}],
                    "extra": {
                        "counterpart": {
                            "kind": "agent",
                            "name": "Claude Code",
                            "ref": {"kind": "provider_id", "value": "claude-code"},
                        },
                        "tool_calls": rng.randint(0, 40),
                        "words": {"owner": 120, "machine": 900},
                    },
                },
            }
        p = self.cast.person(rng)
        return {
            "at": _stamp(start),
            "end": _stamp(end),
            "source": "granola",
            "kind": "transcript",
            "tier": 2,
            "payload": {
                "schema": "transcript/v1",
                "provider": "granola",
                "raw_id": f"t-{_stamp(start)}-{self.n}",
                "title": f"{rng.choice(WORDS).title()} plans",
                "participants": [{"name": p["name"], "email": p["email"]}, {"name": "me"}],
            },
        }

    def _note(self, day: date, minute: float) -> dict[str, Any]:
        rng = self.rng
        return {
            "at": _stamp(_utc(day, minute)),
            "source": "manual",
            "kind": "note",
            "tier": 2,
            "payload": {"schema": "note/v1", "text": _text(rng, promise=rng.random() < 0.05)},
        }

    def _flight(self, day: date, dep: float, arr: float, origin: str, destination: str) -> dict[str, Any]:
        number = f"{self.rng.randint(100, 999)}"
        d, a = _stamp(_utc(day, dep)), _stamp(_utc(day, arr))
        self.flown += 1
        if self.open_flights and self.flown % self.open_flights == 0:
            return self._open_flight(day, d, number, origin, destination)
        return {
            "at": d,
            "end": a,
            "source": "flighty",
            "kind": "flight",
            "tier": 1,
            "payload": {
                "schema": "flight/v1",
                "raw_id": f"fx-{day.isoformat()}-{number}",
                "date": day.isoformat(),
                "carrier": "XY",
                "number": number,
                "from": {"iata": origin},
                "to": {"iata": destination},
                "actual_departure": d,
                "actual_arrival": a,
                "role": "passenger",
                "evidence": "tracked",
                "observations": [{"evidence": "tracked", "source": "flighty"}],
            },
        }

    def _open_flight(self, day: date, d: str, number: str, origin: str, destination: str) -> dict[str, Any]:
        """A flight the tracker never saw land: `end` null, no arrival in the payload (SPEC §2)."""
        self._count("open flight")
        return {
            "at": d,
            "end": None,
            "source": "flighty",
            "kind": "flight",
            "tier": 1,
            "payload": {
                "schema": "flight/v1",
                "raw_id": f"fx-{day.isoformat()}-{number}",
                "date": day.isoformat(),
                "carrier": "XY",
                "number": number,
                "from": {"iata": origin},
                "to": {"iata": destination},
                "actual_departure": d,
                "role": "passenger",
                "evidence": "tracked",
                "observations": [{"evidence": "tracked", "source": "flighty"}],
            },
        }


# -- building -----------------------------------------------------------------------------------------------


def _environment(root: Path) -> dict[str, str]:
    """The child's and the builder's environment: the record found at `root`, the index beside it."""
    env = dict(os.environ)
    env["LOGBOOK_HOME"] = str(root / "record")
    env["LOGBOOK_CACHE_HOME"] = str(root / "cache")
    env["LOGBOOK_DIAL_PREFIX"] = "44"
    return env


def build(
    root: Path, lines: int, seed: int, people: int = PEOPLE, open_flights: int = 0, reflections: int = 0
) -> dict[str, Any]:
    """The synthetic record at `root/record`, indexed, then the owner's acts that go through the
    product's own functions: a chapter and goals with reviews, signed days, stars, retractions; and
    with `reflections`, that many days of the last year reflected on (`day reflect`'s note) before
    the 30 signed ones are signed."""
    from logbook.contrib import reflect
    from logbook.core import chapter, goals, signing, stars
    from logbook.core.store import Logbook

    os.environ.update(_environment(root))
    started = time.monotonic()
    lb = Logbook.init(root / "record", TZ)
    lb.set_owner_emails([OWNER["email"]])
    policy = lb.root / "policy"
    policy.mkdir(exist_ok=True)
    (policy / "owner.json").write_bytes(
        json.dumps(
            {"names": [OWNER["name"]], "emails": [OWNER["email"]], "phones": [OWNER["phone"]]}
        ).encode()
    )
    (lb.root / "places.json").write_bytes(json.dumps(PLACES, indent=2).encode())
    (lb.root / "assets.json").write_bytes(json.dumps({"assets": [BOAT]}).encode())
    gen = Generator(lines, seed, people, open_flights)

    def progress(n: int, elapsed: float) -> None:
        if n % 500_000 == 0:
            print(f"  {n:>10,} lines  {elapsed:7.0f} s", file=sys.stderr, flush=True)

    written = lb.append_many(gen.drafts(), progress=progress)
    bulk_s = time.monotonic() - started
    lb = Logbook(lb.root)
    rng = random.Random(seed + 1)
    with lb.index() as idx:
        days = idx.db.execute(
            "SELECT day_local FROM lines WHERE day_local >= ? GROUP BY day_local ORDER BY day_local",
            ((LAST_DAY - timedelta(days=365)).isoformat(),),
        ).fetchall()
        photos = idx.db.execute(
            "SELECT id FROM lines WHERE kind = 'photo' AND seq % 997 = 0 ORDER BY seq DESC LIMIT 40"
        ).fetchall()
        mistakes = idx.db.execute("SELECT seq FROM lines WHERE kind = 'mail' AND seq % 104729 = 0").fetchall()
    for (line_id,) in photos:
        stars.star(lb, str(line_id))
    for (seq,) in mistakes:
        lb.retract(int(seq), "imported twice")
    year_days = [str(d) for (d,) in days]
    signed = sorted(rng.sample(year_days[:-2], min(30, len(year_days) - 2)))
    reflected = (
        set(rng.sample(year_days[:-2], min(reflections, len(year_days) - 2))) if reflections else set()
    )
    for day in sorted(reflected | set(signed)) if reflections else ():
        said = reflect.Reflection(_text(rng, promise=rng.random() < 0.2), reflect.TYPED)
        reflect.write(lb, day, said, _stamp(_utc(date.fromisoformat(day), 1300)), LAST_DAY.isoformat())
    for day in signed:
        signing.sign(lb, day, at=_stamp(_utc(date.fromisoformat(day), 1320)))
    added = []
    chapter.open_chapter(lb, "The autumn at the yard", start="2026-08-01", rules="the yard, the boat")
    for text, horizon in (
        ("Sail the whole coast to Lofoten", "life"),
        ("Finish the mast", "year"),
        ("Paint the hull", "quarter"),
        ("Read the harbour charts", "quarter"),
    ):
        added.append(goals.add(lb, text, horizon, start="2026-01-01"))
    for goal in added[:3]:
        goals.review(lb, str(goal["id"]), "advancing", at="2026-10-01")
    elapsed = time.monotonic() - started
    with sqlite3.connect(lb.index_path) as db:
        total = db.execute("SELECT count(*) FROM lines").fetchone()[0]
    return {
        "lines": int(total),
        "bulk_lines": written,
        "counts": gen.counts,
        "build_s": round(elapsed, 1),
        "bulk_s": round(bulk_s, 1),
        "record_bytes": sum(f.stat().st_size for f in (lb.root).rglob("*.jsonl")),
        "index_bytes": lb.index_path.stat().st_size,
        "busiest_person": gen.cast.people[0]["id"],
        "org": gen.cast.orgs[0]["id"],
        "idea": gen.cast.ideas[0]["id"],
    }


# -- timing -------------------------------------------------------------------------------------------------


def peak_mb() -> float | None:
    """This process's peak resident memory in MB: `ru_maxrss` (kilobytes on Linux, bytes on macOS);
    on Windows, which has no `resource`, psutil's peak working set when psutil is installed, else
    None (the table says n/a)."""
    try:
        import resource
    except ImportError:
        try:
            import psutil  # type: ignore[import-not-found, import-untyped, unused-ignore]
        except ImportError:
            return None
        peak: int = psutil.Process().memory_info().peak_wset
        return round(peak / 2**20, 1)
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(rss / 2**20 if sys.platform == "darwin" else rss / 1024, 1)


def child(root: Path, route: str, profile: bool) -> dict[str, Any]:
    """One route, in this process: the server starts, the route is asked for three times — cold,
    warm, and after one line is appended."""
    from logbook.contrib import serve
    from logbook.core.store import Logbook

    os.environ.update(_environment(root))
    lb = Logbook(root / "record")
    site = serve.Site(lb, now=lambda: NOW)
    path, _, query = route.partition("?")
    out: dict[str, Any] = {"route": route}
    profiler = cProfile.Profile() if profile else None
    t = time.perf_counter()
    if profiler is not None:
        profiler.enable()
    first = site.respond(path, query)
    if profiler is not None:
        profiler.disable()
    out["cold_s"] = round(time.perf_counter() - t, 3)
    out["status"] = first.status
    out["bytes"] = len(first.body)
    links = JOURNEY_LINK.findall(first.body.decode("utf-8", "replace"))
    if links:
        out["journey"] = links[0]
    t = time.perf_counter()
    second = site.respond(path, query)
    out["warm_s"] = round(time.perf_counter() - t, 3)
    out["same"] = second.body == first.body
    lb.append(
        at=_stamp(NOW - timedelta(minutes=30)),
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "text": "One more line, as a sync would write it."},
    )
    t = time.perf_counter()
    third = site.respond(path, query)
    out["after_append_s"] = round(time.perf_counter() - t, 3)
    out["after_status"] = third.status
    out["peak_mb"] = peak_mb()
    if profiler is not None:
        text = io.StringIO()
        pstats.Stats(profiler, stream=text).sort_stats("cumulative").print_stats(15)
        out["profile"] = text.getvalue()
    return out


def run_route(root: Path, route: str, profile: bool, timeout: int) -> dict[str, Any]:
    argv = [
        sys.executable,
        __file__,
        "--child",
        route,
        "--root",
        str(root),
        *(["--profile-child"] if profile else []),
    ]
    try:
        done = subprocess.run(
            argv, capture_output=True, timeout=timeout, encoding="utf-8", env=_environment(root)
        )
    except subprocess.TimeoutExpired:
        return {"route": route, "error": f"over {timeout} s"}
    if done.returncode != 0:
        return {
            "route": route,
            "error": done.stderr.strip().splitlines()[-1] if done.stderr.strip() else "failed",
        }
    found: dict[str, Any] = json.loads(done.stdout.strip().splitlines()[-1])
    return found


def open_index(root: Path) -> float:
    """Bring the record's index to its head once, as the Library does when it starts, before any
    route is timed, and how long that took: what that does once (an index built by an earlier version
    is given the indexes it lacks) is not any route's."""
    from logbook.contrib import serve
    from logbook.core.store import Logbook

    os.environ.update(_environment(root))
    t = time.perf_counter()
    serve.Site(Logbook(root / "record"), now=lambda: NOW).current()
    return round(time.perf_counter() - t, 3)


def week_of(day: str) -> str:
    """The ISO week a day is in, `YYYY-Www`, as the week page's path names it."""
    year, week, _weekday = date.fromisoformat(day).isocalendar()
    return f"{year}-W{week:02d}"


def busiest_day(root: Path) -> str:
    with sqlite3.connect(next((root / "cache").rglob("index.sqlite"))) as db:
        day = db.execute(
            "SELECT day_local FROM lines WHERE day_local > ? GROUP BY day_local"
            " ORDER BY count(*) DESC, day_local DESC LIMIT 1",
            ((LAST_DAY - timedelta(days=365)).isoformat(),),
        )  # the busiest day of the last year: the first day holds every resolution line, and is no Day
        return str(day.fetchone()[0])


def time_routes(
    root: Path, built: dict[str, Any], routes: list[str] | None, profiles: list[str], timeout: int
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Every route of `ROUTES` (or those `routes` names), each in a child of its own (`run_route`),
    filled in from the record (`fill`): the busiest day and its week, person, org, idea and the first
    journey.
    Says each as it goes, on stderr."""
    busiest = busiest_day(root)
    fill: dict[str, Any] = {
        "day": busiest,
        "week": week_of(busiest),  # the busiest day's week
        "person": built["busiest_person"],
        "org": built["org"],
        "idea": built["idea"],
        "journey": None,
    }
    wanted = routes or list(ROUTES)
    results: list[dict[str, Any]] = []
    for template in ROUTES:
        if template not in wanted and template.split("{")[0] not in wanted:  # `/people/` is every person
            continue
        if "{journey}" in template and fill["journey"] is None:
            found = run_route(root, "/journeys", False, timeout) if "/journeys" not in wanted else None
            fill["journey"] = (found or {}).get("journey")
            if fill["journey"] is None:
                results.append({"route": template, "error": "no journey on /journeys"})
                continue
        route = template.format(**fill)
        profile = template in profiles or route in profiles
        print(f"  {route} …", file=sys.stderr, flush=True)
        r = run_route(root, route, profile, timeout)
        r["template"] = template
        if r.get("journey") and fill["journey"] is None:
            fill["journey"] = r["journey"]
        results.append(r)
        if "profile" in r:
            print(f"\n== {route} (cold) ==\n{r['profile']}", file=sys.stderr, flush=True)
        if "error" in r:
            print(f"    {r['error']}", file=sys.stderr, flush=True)
        else:
            print(
                f"    cold {r['cold_s']} s, warm {r['warm_s']} s, after append {r['after_append_s']} s,"
                f" {r['peak_mb']} MB",
                file=sys.stderr,
                flush=True,
            )
    return fill, results


def together(root: Path, routes: list[str]) -> dict[str, Any]:
    """Every route asked for at once, cold, by one thread each, of one server (as a browser opens the
    whole menu): how long the last one took to answer, and each route's own time and status."""
    import threading

    from logbook.contrib import serve
    from logbook.core.store import Logbook

    os.environ.update(_environment(root))
    site = serve.Site(Logbook(root / "record"), now=lambda: NOW)
    each: dict[str, dict[str, Any]] = {}
    begun = time.perf_counter()

    def ask(route: str) -> None:
        path, _, query = route.partition("?")
        t = time.perf_counter()
        response = site.respond(path, query)
        each[route] = {"status": response.status, "s": round(time.perf_counter() - t, 3)}

    threads = [threading.Thread(target=ask, args=(route,)) for route in routes]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return {"routes": each, "all_s": round(time.perf_counter() - begun, 3), "peak_mb": peak_mb()}


def run_together(root: Path, routes: list[str], timeout: int) -> dict[str, Any]:
    """`together` in a child of its own, so no route is warm from another's run."""
    argv = [sys.executable, __file__, "--together", *routes, "--root", str(root)]
    try:
        done = subprocess.run(
            argv, capture_output=True, timeout=timeout, encoding="utf-8", env=_environment(root)
        )
    except subprocess.TimeoutExpired:
        return {"error": f"over {timeout} s"}
    if done.returncode != 0:
        return {"error": done.stderr.strip().splitlines()[-1] if done.stderr.strip() else "failed"}
    found: dict[str, Any] = json.loads(done.stdout.strip().splitlines()[-1])
    return found


def machine() -> dict[str, Any]:
    cpu = platform.processor() or platform.machine()
    try:
        for row in Path("/proc/cpuinfo").read_text().splitlines():
            if row.startswith("model name"):
                cpu = row.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    memory = None
    with contextlib.suppress(ValueError, OSError, AttributeError):  # no sysconf on Windows
        memory = round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1)
    return {
        "cpu": cpu,
        "cpus": os.cpu_count(),
        "memory_gb": memory,
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "system": platform.platform(),
    }


def markdown(results: dict[str, Any]) -> str:
    rows = ["| route | cold s | warm s | after-append s | peak MB |", "|---|--:|--:|--:|--:|"]
    for r in results["routes"]:
        if "error" in r:
            rows.append(f"| `{r['route']}` | {r['error']} | | | |")
            continue
        times = f"{r['cold_s']:.2f} | {r['warm_s']:.2f} | {r['after_append_s']:.2f}"
        peak = "n/a" if r["peak_mb"] is None else f"{r['peak_mb']:.0f}"
        rows.append(f"| `{r['route']}` | {times} | {peak} |")
    return "\n".join(rows)


def parse(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--lines",
        type=int,
        help=f"lines in the synthetic record (default {LINES:,}, or the record kept at --root)",
    )
    p.add_argument("--seed", type=int, default=SEED)
    p.add_argument("--people", type=int, default=PEOPLE, help=f"resolved people (default {PEOPLE})")
    p.add_argument("--open-flights", type=int, default=0, help="every Nth flight without its arrival")
    p.add_argument("--reflections", type=int, default=0, help="days of the last year reflected on")
    p.add_argument("--root", type=Path, help="keep the record here and reuse it on the next run")
    p.add_argument("--routes", nargs="*", help="these routes only (as written in ROUTES, e.g. /people)")
    p.add_argument(
        "--profile",
        action="append",
        default=[],
        help="print the top 15 functions of this route's cold request",
    )
    p.add_argument(
        "--timeout", type=int, default=TIMEOUT_S, help="seconds one route may take, all three requests"
    )
    p.add_argument("--out", type=Path, help="write the results as JSON here")
    p.add_argument("--markdown", action="store_true", help="print the table as Markdown")
    p.add_argument("--build-only", action="store_true", help="build the record and stop")
    p.add_argument("--child", help=argparse.SUPPRESS)
    p.add_argument("--together", nargs="+", help=argparse.SUPPRESS)
    p.add_argument("--profile-child", action="store_true", help=argparse.SUPPRESS)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse(argv)
    if args.child is not None:
        print(json.dumps(child(args.root, args.child, args.profile_child)))
        return
    if args.together is not None:
        print(json.dumps(together(args.root, args.together)))
        return
    keep = args.root is not None
    root = args.root or Path(tempfile.mkdtemp(prefix="bench-library-"))
    root.mkdir(parents=True, exist_ok=True)
    built_file = root / "built.json"
    try:
        built = json.loads(built_file.read_text()) if built_file.exists() else None
        asked = args.lines or (built or {}).get("asked") or LINES  # no --lines: the record kept at --root
        shape = {
            "seed": args.seed,
            "people": args.people,
            "open_flights": args.open_flights,
            "reflections": args.reflections,
        }
        kept = {"people": PEOPLE, "open_flights": 0, "reflections": 0, **(built or {})}  # an older built.json
        if built is None or built.get("asked") != asked or any(kept.get(k) != v for k, v in shape.items()):
            if (root / "record").exists():
                shutil.rmtree(root / "record")
                shutil.rmtree(root / "cache", ignore_errors=True)
            print(f"building a record of {asked:,} lines in {root} …", file=sys.stderr, flush=True)
            built = {
                "asked": asked,
                **shape,
                **build(root, asked, args.seed, args.people, args.open_flights, args.reflections),
            }
            built_file.write_text(json.dumps(built, indent=2))
            print(f"built in {built['build_s']} s", file=sys.stderr, flush=True)
        if args.build_only:
            print(json.dumps(built, indent=2))
            return
        opened = open_index(root)
        print(f"  the index opened in {opened} s", file=sys.stderr, flush=True)
        fill, results = time_routes(root, built, args.routes, args.profile, args.timeout)
        out = {
            "record": built,
            "machine": machine(),
            "index_open_s": opened,
            "day": fill["day"],
            "routes": results,
            "when": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if args.out is not None:
            args.out.write_text(json.dumps(out, indent=2) + "\n")
        if args.markdown:
            print(markdown(out))
    finally:
        if not keep:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
