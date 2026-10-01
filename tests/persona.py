"""Two synthetic weeks of the Oslo persona, who does not exist, for the readers' tests.

8 to 21 June 2026 (CEST). Home in central Oslo, an office, a cafe, a marina where the yacht
Solvind lies; two people, Kari and Ola Nordmann, resolved from their addresses; a weekend aboard
Solvind on the fjord; a flight to Zürich and three nights there; favourite photos and an album.
Every coordinate, address and id is invented; the emails are at example.org and the phone numbers
are in the reserved +47 9000 000x range used by the project's RFC examples.

The builders here are the ones `test_stays.py` uses, lifted so every reader test shares one record;
`persona_drafts()` is the whole fortnight, `persona_record()` writes it into a temporary record."""

from __future__ import annotations

import json
import math
import random
import zlib
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from logbook.store import Logbook

TZ = "Europe/Oslo"
UTC = ZoneInfo("UTC")

HOME = (59.9139, 10.7522)
OFFICE = (59.9100, 10.7600)  # ~600 m from HOME
CAFE = (59.9200, 10.7400)  # ~1.1 km from HOME
MARINA = (59.9050, 10.7350)
FJORD = (59.8500, 10.6000)  # the anchorage, out on the fjord
OSL = (60.1939, 11.1004)  # Oslo Gardermoen
ZRH = (47.4581, 8.5481)  # Zürich airport
ZURICH = (47.3769, 8.5417)  # the hotel in the city

BOAT = "solvind"
KARI = {"email": "kari.nordmann@example.org", "phone": "+4790000002", "face": "p_17"}
OLA = {"email": "ola@example.org", "phone": "+4790000001"}
KARI_ID = "019cadd3-6bc0-7dcd-9133-000000000001"
OLA_ID = "019cadd3-6bc0-7dcd-9133-000000000002"

DAYS = [f"2026-06-{d:02d}" for d in range(8, 22)]  # Monday 8 June to Sunday 21 June


def utc(day: str, clock: str) -> str:
    """A local Oslo wall-clock time on `day` as the RFC3339 UTC stamp a line carries."""
    local = datetime.fromisoformat(f"{day}T{clock}:00").replace(tzinfo=ZoneInfo(TZ))
    return local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def point(
    at: str, where: tuple[float, float], subject: str | None = None, source: str = "dawarich"
) -> dict[str, Any]:
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


def jitter(where: tuple[float, float], metres: float, rng: random.Random) -> tuple[float, float]:
    """`where` displaced by up to `metres` in a random direction: GPS noise."""
    bearing = rng.uniform(0, 2 * math.pi)
    d = rng.uniform(0, metres)
    dlat = d * math.cos(bearing) / 111_320
    dlon = d * math.sin(bearing) / (111_320 * math.cos(math.radians(where[0])))
    return (where[0] + dlat, where[1] + dlon)


def dwell(
    day: str,
    start: str,
    end: str,
    where: tuple[float, float],
    every_min: int = 5,
    noise_m: float = 30,
    subject: str | None = None,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """Points every `every_min` minutes from `start` to `end` local, jittered around `where`.
    `end` may be `24:00` for midnight at the end of the day."""
    rng = random.Random(seed if seed is not None else zlib.crc32(repr((day, start, where, subject)).encode()))
    t0 = _local(day, start)
    t1 = _local(day, end)
    out = []
    t = t0
    while t <= t1 and (t < t1 or end != "24:00"):  # a day's last point stays on its day
        stamp = t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        out.append(point(stamp, jitter(where, noise_m, rng), subject))
        t += timedelta(minutes=every_min)
    return out


def travel(
    day: str,
    start: str,
    end: str,
    a: tuple[float, float],
    b: tuple[float, float],
    steps: int = 6,
    subject: str | None = None,
) -> list[dict[str, Any]]:
    """Points on a straight line from `a` (at `start`) to `b` (at `end`), the ends excluded."""
    t0, t1 = _local(day, start), _local(day, end)
    out = []
    for i in range(1, steps):
        f = i / steps
        t = t0 + (t1 - t0) * f
        stamp = t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        out.append(point(stamp, (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f), subject))
    return out


def _local(day: str, clock: str) -> datetime:
    if clock == "24:00":
        return _local(day, "00:00") + timedelta(days=1)
    return datetime.fromisoformat(f"{day}T{clock}:00").replace(tzinfo=ZoneInfo(TZ))


def photo(
    at: str,
    where: tuple[float, float] | None = None,
    people: list[str] | None = None,
    favorite: bool = False,
    album: str | None = None,
    library: str = "immich",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "photo/v1",
        "asset_id": f"p-{at}",
        "library": library,
        "file_name": f"IMG_{at[8:10]}{at[11:13]}{at[14:16]}.HEIC",
        "media": "image",
        "provenance": "camera",
        "faces": len(people or []),
        "people": list(people or []),
        "raw_id": f"p-{at}",
    }
    if where:
        payload["lat"], payload["lon"] = where
    extra: dict[str, Any] = {}
    if favorite:
        extra["favorite"] = True
    if album:
        extra["album"] = album
    if extra:
        payload["extra"] = extra
    return {"at": at, "source": library, "kind": "photo", "tier": 1, "payload": payload}


def event(
    at: str, end: str, title: str, attendees: list[dict[str, Any]] | None = None, **extra: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "event/v1",
        "raw_id": f"e-{at}-{title}",
        "title": title,
        "all_day": False,
    }
    if attendees:
        payload["attendees"] = attendees
    payload.update(extra)
    return {"at": at, "end": end, "source": "ios-calendar", "kind": "event", "tier": 1, "payload": payload}


def attendee(email: str, name: str | None = None, response: str = "accepted") -> dict[str, Any]:
    out: dict[str, Any] = {"ref": {"kind": "email", "value": email}, "response": response}
    if name:
        out["name"] = name
    return out


def transcript(at: str, end: str, title: str, participants: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "at": at,
        "end": end,
        "source": "granola",
        "kind": "transcript",
        "tier": 2,
        "payload": {
            "schema": "transcript/v1",
            "provider": "granola",
            "raw_id": f"t-{at}",
            "title": title,
            "participants": participants,
        },
    }


def note(at: str, text: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "manual",
        "kind": "note",
        "tier": 2,
        "payload": {"schema": "note/v1", "text": text},
    }


def resolution(ref: tuple[str, str], entity_id: str, label: str) -> dict[str, Any]:
    return {
        "at": "2026-06-01T08:00:00Z",
        "source": "manual",
        "kind": "resolution",
        "tier": 2,
        "payload": {
            "schema": "resolution/v1",
            "ref": {"kind": ref[0], "value": ref[1]},
            "entity": {"type": "person", "id": entity_id, "registry": "logbook"},
            "label": label,
            "method": "owner",
        },
    }


def flight(date: str, number: str, from_: str, to: str, dep: str, arr: str) -> dict[str, Any]:
    """A tracked flight/v1 line (RFC 0013) on carrier XY, which is no airline."""
    return {
        "at": dep,
        "end": arr,
        "source": "flighty",
        "kind": "flight",
        "tier": 1,
        "payload": {
            "schema": "flight/v1",
            "raw_id": f"fx-{date}-{number}",
            "date": date,
            "carrier": "XY",
            "number": number,
            "from": {"iata": from_},
            "to": {"iata": to},
            "actual_departure": dep,
            "actual_arrival": arr,
            "role": "passenger",
            "evidence": "tracked",
            "observations": [{"evidence": "tracked", "source": "flighty"}],
        },
    }


def timeline_visit(
    day: str, start: str, end: str, where: tuple[float, float], semantic: str
) -> dict[str, Any]:
    """The start edge of a Google Timeline visit as the takeout adapter writes it."""
    t0, t1 = _local(day, start), _local(day, end)
    raw_start, raw_end = t0.isoformat(timespec="milliseconds"), t1.isoformat(timespec="milliseconds")
    visit = {
        "hierarchyLevel": 0,
        "probability": 0.9,
        "topCandidate": {
            "placeId": f"ChIJ-synthetic-{semantic.lower()}-0001",
            "semanticType": semantic,
            "probability": 0.85,
            "placeLocation": {"latLng": f"{where[0]}°, {where[1]}°"},
        },
    }
    at = t0.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "at": at,
        "source": "google-takeout",
        "kind": "location",
        "tier": 1,
        "payload": {
            "schema": "location/v1",
            "lat": where[0],
            "lon": where[1],
            "raw_id": f"visit:{raw_start}:start",
            "extra": {
                "segment": "visit",
                "edge": "start",
                "segment_start": raw_start,
                "segment_end": raw_end,
                "visit": visit,
            },
        },
    }


# -- the fortnight -------------------------------------------------------------------------------------


def _home_night(day: str, next_day: str) -> list[dict[str, Any]]:
    return dwell(day, "18:30", "24:00", HOME, every_min=5) + dwell(
        next_day, "00:00", "07:30", HOME, every_min=5
    )


def _office_day(day: str) -> list[dict[str, Any]]:
    return (
        dwell(day, "07:30", "08:00", HOME, every_min=5)
        + travel(day, "08:00", "08:10", HOME, OFFICE, steps=3)
        + dwell(day, "08:10", "17:50", OFFICE, every_min=5)
        + travel(day, "17:50", "18:00", OFFICE, HOME, steps=3)
        + dwell(day, "18:00", "18:30", HOME, every_min=5)
    )


def persona_drafts() -> list[dict[str, Any]]:
    """Every line of the fortnight, in a plausible import order (people and places first)."""
    drafts: list[dict[str, Any]] = [
        resolution(("email", KARI["email"]), KARI_ID, "Kari Nordmann"),
        resolution(("phone", KARI["phone"]), KARI_ID, "Kari Nordmann"),
        resolution(("provider_id", f"immich:{KARI['face']}"), KARI_ID, "Kari Nordmann"),
        resolution(("email", OLA["email"]), OLA_ID, "Ola Nordmann"),
        resolution(("phone", OLA["phone"]), OLA_ID, "Ola Nordmann"),
    ]
    # Week one: office days, home nights. Wednesday lunch with Kari at the cafe; Thursday a call
    # with Ola transcribed at the office; a favourite photo of Kari at the cafe, an "Art" photo.
    for day, next_day in pairwise(DAYS[:6]):
        if day == "2026-06-10":
            drafts += (
                dwell(day, "07:30", "08:00", HOME, every_min=5)
                + travel(day, "08:00", "08:10", HOME, OFFICE, steps=3)
                + dwell(day, "08:10", "11:50", OFFICE, every_min=5)
                + travel(day, "11:50", "12:00", OFFICE, CAFE, steps=3)
                + dwell(day, "12:00", "13:00", CAFE, every_min=5)
                + travel(day, "13:00", "13:10", CAFE, OFFICE, steps=3)
                + dwell(day, "13:10", "17:50", OFFICE, every_min=5)
                + travel(day, "17:50", "18:00", OFFICE, HOME, steps=3)
                + dwell(day, "18:00", "18:30", HOME, every_min=5)
            )
            drafts.append(
                event(
                    utc(day, "12:00"),
                    utc(day, "13:00"),
                    "Lunch",
                    [attendee(KARI["email"], "Kari Nordmann")],
                    location="the cafe",
                )
            )
            drafts.append(photo(utc(day, "12:30"), CAFE, people=[KARI["face"]], favorite=True))
            drafts.append(timeline_visit(day, "12:00", "13:00", CAFE, "RESTAURANT"))
        else:
            drafts += _office_day(day)
        if day == "2026-06-11":
            drafts.append(
                transcript(
                    utc(day, "14:00"),
                    utc(day, "14:30"),
                    "Boat plans",
                    [{"name": "Ola Nordmann", "email": OLA["email"]}],
                )
            )
            drafts.append(photo(utc(day, "16:00"), OFFICE, album="Art"))
        drafts += _home_night(day, next_day)
    # The weekend aboard Solvind: Saturday out to the anchorage with Ola, Sunday back.
    sat, sun, mon = "2026-06-13", "2026-06-14", "2026-06-15"
    drafts += (
        dwell(sat, "07:30", "09:00", HOME, every_min=5)
        + travel(sat, "09:00", "09:15", HOME, MARINA, steps=3)
        + dwell(sat, "09:15", "10:00", MARINA, every_min=5, noise_m=15)
        + travel(sat, "10:00", "12:00", MARINA, FJORD, steps=24)
        + dwell(sat, "12:00", "24:00", FJORD, every_min=5, noise_m=15)
        + dwell(sun, "00:00", "14:00", FJORD, every_min=5, noise_m=15)
        + travel(sun, "14:00", "16:00", FJORD, MARINA, steps=24)
        + dwell(sun, "16:00", "16:40", MARINA, every_min=5, noise_m=15)
        + travel(sun, "16:40", "16:55", MARINA, HOME, steps=3)
        + dwell(sun, "16:55", "24:00", HOME, every_min=5)
        + dwell(mon, "00:00", "05:00", HOME, every_min=5)
        # the boat's AIS track: at the berth, out, at anchor, back
        + dwell(DAYS[0], "00:00", "24:00", MARINA, every_min=8, noise_m=5, subject=BOAT)
        + dwell(sat, "06:00", "10:00", MARINA, every_min=2, noise_m=5, subject=BOAT)
        + travel(sat, "10:00", "12:00", MARINA, FJORD, steps=120, subject=BOAT)
        + dwell(sat, "12:00", "24:00", FJORD, every_min=2, noise_m=5, subject=BOAT)
        + dwell(sun, "00:00", "14:00", FJORD, every_min=2, noise_m=5, subject=BOAT)
        + travel(sun, "14:00", "16:00", FJORD, MARINA, steps=120, subject=BOAT)
        + dwell(sun, "16:00", "23:00", MARINA, every_min=2, noise_m=5, subject=BOAT)
    )
    drafts.append(note(utc(sat, "19:00"), "Anchored in the bay with Ola Nordmann. Grilled."))
    drafts.append(photo(utc(sat, "19:30"), FJORD, favorite=True))
    # Monday: fly to Zürich (XY 561), three nights at the hotel, dinner with Ola on Tuesday,
    # Thursday back (XY 562) and home.
    thu, fri = "2026-06-18", "2026-06-19"
    drafts += (
        travel(mon, "05:00", "05:40", HOME, OSL, steps=4)
        + dwell(mon, "05:40", "07:00", OSL, every_min=5)
        + dwell(mon, "09:20", "10:00", ZRH, every_min=5)
        + travel(mon, "10:00", "10:30", ZRH, ZURICH, steps=3)
        + dwell(mon, "10:30", "24:00", ZURICH, every_min=5)
        + dwell("2026-06-16", "00:00", "24:00", ZURICH, every_min=5)
        + dwell("2026-06-17", "00:00", "24:00", ZURICH, every_min=5)
        + dwell(thu, "00:00", "15:00", ZURICH, every_min=5)
        + travel(thu, "15:00", "15:30", ZURICH, ZRH, steps=3)
        + dwell(thu, "15:30", "17:00", ZRH, every_min=5)
        + dwell(thu, "19:20", "20:00", OSL, every_min=5)
        + travel(thu, "20:00", "20:40", OSL, HOME, steps=4)
        + dwell(thu, "20:40", "24:00", HOME, every_min=5)
        + dwell(fri, "00:00", "07:30", HOME, every_min=5)
    )
    drafts.append(flight("2026-06-15", "561", "OSL", "ZRH", utc(mon, "07:05"), utc(mon, "09:15")))
    drafts.append(flight("2026-06-18", "562", "ZRH", "OSL", utc(thu, "17:10"), utc(thu, "19:15")))
    drafts.append(event(utc(mon, "07:05"), utc(mon, "09:15"), "Flight to Zürich (XY 561)"))
    drafts.append(
        event(utc("2026-06-16", "19:00"), utc("2026-06-16", "21:00"), "Dinner", [attendee(OLA["email"])])
    )
    drafts.append(photo(utc("2026-06-16", "20:00"), ZURICH, favorite=True))
    # The last weekend at home.
    for day, next_day in pairwise(DAYS[11:14]):
        drafts += _office_day(day) + _home_night(day, next_day)
    drafts += dwell(DAYS[13], "07:30", "24:00", HOME, every_min=5)
    return drafts


PLACES = {
    "Home": {"lat": HOME[0], "lon": HOME[1], "radius_m": 120, "kind": "home"},
    "Office": {"lat": OFFICE[0], "lon": OFFICE[1], "radius_m": 120},
    "Marina": {"lat": MARINA[0], "lon": MARINA[1], "radius_m": 150, "kind": "asset-berth", "tags": ["boat"]},
}


def persona_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, places: dict[str, Any] | None = PLACES
) -> Logbook:
    """The fortnight written into a fresh record under `tmp_path`, with the boat registered and
    `places.json` naming Home, Office and Marina (or `places`, or none)."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(persona_drafts())
    (lb.root / "assets.json").write_text(
        json.dumps({"assets": [{"id": BOAT, "kind": "yacht", "name": "Solvind", "mmsi": "999000001"}]}),
        encoding="utf-8",
    )
    if places:
        (lb.root / "places.json").write_text(json.dumps(places, indent=2), encoding="utf-8")
    return lb
