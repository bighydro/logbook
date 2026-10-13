"""A synthetic long weekend for `logbook export world`: Ines Nordmann, who does not exist, in Oslo.

Friday 10 to Monday 13 July 2026 (CEST), Europe/Oslo. Three named places (Home, Marina, Hytta), two
assets on their own tracks — the yacht Havbris (MMSI 970000117, in the 970 test range) and the club's
aircraft Lerka (icao24 000a07, in the unallocated block; registration ZZ-LRK, under the unassigned
prefix) — and one journey: the deck log's passage Marina → Hytta on Friday evening, Havbris's own.

- Friday: home until 16:00, to the marina, aboard Havbris at 16:30; the passage 17:00 to 20:00, owner
  and boat together; the night at anchor off Hytta, aboard. A photo aboard under way at 18:30.
- Saturday: ashore at 10:30, the day and the night at Hytta. Two photos there in the afternoon.
- Sunday: the boat goes back to the marina without anyone the record knows (12:00 to 15:00); the
  owner takes a taxi home (15:00 to 16:30): a journey line that carries a price, so tier 3, which no
  default world shows. The night at home.
- Monday: home all day; Lerka flies a loop over the fjord from 11:00 to 12:30, nobody aboard the
  record knows of. In the evening the owner names the summer a chapter (tier 2): 1 July to 15 August.

The coordinates are written at a precision each source keeps on its own, so a test can tell whether a
reader added any: the owner's tracker at 3 decimals, the boat's AIS at 4, the aircraft's ADS-B at 3,
`places.json` at 4, the passage's two ends at 3 and its route at 4. Every coordinate is invented on
the Oslo fjord; every identifier is synthetic."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from persona import TZ, UTC, utc

from logbook.core.store import Logbook

DAYS = ["2026-07-10", "2026-07-11", "2026-07-12", "2026-07-13"]
FRI, SAT, SUN, MON = DAYS

HOME = (59.9139, 10.7522)
MARINA = (59.9050, 10.7350)
HYTTA = (59.7000, 10.6034)  # the cabin, ashore
ANCHORAGE = (59.6950, 10.5850)  # off Hytta, 1.1 km west of the cabin
FJORD = (59.8000, 10.6500)  # where Lerka turns
KJELLER = (59.9700, 11.0400)  # Lerka's field

YACHT, PLANE = "havbris", "lerka"
YACHT_MMSI = "970000117"
PLANE_ICAO24, PLANE_REGISTRATION = "000a07", "ZZ-LRK"
PLACES = {
    "Home": {"lat": HOME[0], "lon": HOME[1], "radius_m": 120, "kind": "home"},
    "Marina": {"lat": MARINA[0], "lon": MARINA[1], "radius_m": 150, "kind": "asset-berth"},
    "Hytta": {"lat": HYTTA[0], "lon": HYTTA[1], "radius_m": 150},
}
ASSETS = [
    {"id": YACHT, "kind": "yacht", "name": "Havbris", "mmsi": YACHT_MMSI},
    {
        "id": PLANE,
        "kind": "aircraft",
        "name": "Lerka",
        "icao24": PLANE_ICAO24,
        "registration": PLANE_REGISTRATION,
    },
]
CHAPTER = "Sommer på sjøen"
OWNER_DECIMALS, YACHT_DECIMALS, PLANE_DECIMALS = 3, 4, 3
PASSAGE_ROUTE = [(10.7350, 59.9050), (10.7000, 59.8500), (10.6200, 59.7500), (10.5850, 59.6950)]  # lon, lat


def _local(day: str, clock: str) -> datetime:
    if clock == "24:00":
        return _local(day, "00:00") + timedelta(days=1)
    return datetime.fromisoformat(f"{day}T{clock}:00").replace(tzinfo=ZoneInfo(TZ))


def _stamp(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def fix(at: str, where: tuple[float, float], subject: str | None, decimals: int) -> dict[str, Any]:
    """One location/v1 line: the owner's tracker, or an asset's receiver, at `decimals`."""
    source = {None: "dawarich", PLANE: "adsb"}.get(subject, "ais")
    payload: dict[str, Any] = {
        "schema": "location/v1",
        "lat": round(where[0], decimals),
        "lon": round(where[1], decimals),
        "raw_id": f"{source}:{subject or 'owner'}:{at}",
    }
    if subject:
        payload["subject"] = subject
    return {"at": at, "source": source, "kind": "location", "tier": 1, "payload": payload}


def still(
    day: str, start: str, end: str, where: tuple[float, float], every_min: int, subject: str | None = None
) -> list[dict[str, Any]]:
    """A fix every `every_min` minutes at `where`, `start` to `end` local (`end` may be 24:00)."""
    decimals = {None: OWNER_DECIMALS, YACHT: YACHT_DECIMALS, PLANE: PLANE_DECIMALS}[subject]
    t, t1 = _local(day, start), _local(day, end)
    out = []
    while t < t1:
        out.append(fix(_stamp(t), where, subject, decimals))
        t += timedelta(minutes=every_min)
    return out


def under_way(
    day: str,
    start: str,
    end: str,
    route: list[tuple[float, float]],
    every_min: int,
    subject: str | None = None,
) -> list[dict[str, Any]]:
    """A fix every `every_min` minutes along `route` (lat, lon pairs), evenly in time, ends excluded."""
    decimals = {None: OWNER_DECIMALS, YACHT: YACHT_DECIMALS, PLANE: PLANE_DECIMALS}[subject]
    t0, t1 = _local(day, start), _local(day, end)
    legs = len(route) - 1
    out = []
    t = t0 + timedelta(minutes=every_min)
    while t < t1:
        f = (t - t0) / (t1 - t0) * legs
        i = min(int(f), legs - 1)
        g = f - i
        (a_lat, a_lon), (b_lat, b_lon) = route[i], route[i + 1]
        out.append(
            fix(_stamp(t), (a_lat + (b_lat - a_lat) * g, a_lon + (b_lon - a_lon) * g), subject, decimals)
        )
        t += timedelta(minutes=every_min)
    return out


def photo(at: str, where: tuple[float, float]) -> dict[str, Any]:
    return {
        "at": at,
        "source": "immich",
        "kind": "photo",
        "tier": 1,
        "payload": {
            "schema": "photo/v1",
            "asset_id": f"p-{at}",
            "library": "immich",
            "file_name": f"IMG_{at[8:10]}{at[11:13]}{at[14:16]}.HEIC",
            "media": "image",
            "provenance": "camera",
            "lat": round(where[0], 3),
            "lon": round(where[1], 3),
            "raw_id": f"p-{at}",
        },
    }


def passage() -> dict[str, Any]:
    """The deck log's leg Marina → Hytta (RFC 0020 rule 6), Havbris's own, positioned from its route."""
    return {
        "at": utc(FRI, "17:00"),
        "end": utc(FRI, "20:00"),
        "source": "passages",
        "kind": "journey",
        "tier": 1,
        "payload": {
            "schema": "journey/v1",
            "raw_id": f"passages:{YACHT}:{FRI}T17:00:marina",
            "mode": "passage",
            "provider": "deck-log",
            "subject": YACHT,
            "evidence": "declared",
            "name": "Marina → Hytta",
            "from": {"name": "Marina", "latitude": 59.905, "longitude": 10.735},
            "to": {"name": "Hytta", "latitude": 59.695, "longitude": 10.585},
            "geometry": {"type": "LineString", "coordinates": [list(p) for p in PASSAGE_ROUTE]},
            "distance_m": 26100,
        },
    }


def taxi() -> dict[str, Any]:
    """The ride home on Sunday: a price, so tier 3 (RFC 0020)."""
    return {
        "at": utc(SUN, "15:00"),
        "end": utc(SUN, "16:30"),
        "source": "taxi",
        "kind": "journey",
        "tier": 3,
        "payload": {
            "schema": "journey/v1",
            "raw_id": f"taxi:{SUN}T15:00",
            "mode": "ride",
            "provider": "taxi",
            "from": {"name": "Hytta", "latitude": 59.7, "longitude": 10.603},
            "to": {"name": "Home", "latitude": 59.914, "longitude": 10.752},
            "price": {"amount": "640.00", "currency": "NOK"},
        },
    }


def chapter() -> dict[str, Any]:
    return {
        "at": utc(MON, "20:00"),
        "source": "manual",
        "kind": "chapter",
        "tier": 2,
        "payload": {
            "schema": "chapter/v1",
            "name": CHAPTER,
            "from": "2026-07-01",
            "to": "2026-08-15",
            "rules": "Every night on the water counts.",
        },
    }


def world_drafts() -> list[dict[str, Any]]:
    route = [(lat, lon) for lon, lat in PASSAGE_ROUTE]
    drafts: list[dict[str, Any]] = []
    # the owner
    drafts += still(FRI, "00:00", "16:00", HOME, 5)
    drafts += under_way(FRI, "16:00", "16:30", [HOME, MARINA], 5)
    drafts += still(FRI, "16:30", "17:00", MARINA, 5)
    drafts += under_way(FRI, "17:00", "20:00", route, 5)
    drafts += still(FRI, "20:00", "24:00", ANCHORAGE, 5)
    drafts += still(SAT, "00:00", "10:00", ANCHORAGE, 5)
    drafts += under_way(SAT, "10:00", "10:30", [ANCHORAGE, HYTTA], 5)
    drafts += still(SAT, "10:30", "24:00", HYTTA, 5)
    drafts += still(SUN, "00:00", "15:00", HYTTA, 5)
    drafts += under_way(SUN, "15:00", "16:30", [HYTTA, HOME], 5)
    drafts += still(SUN, "16:30", "24:00", HOME, 5)
    drafts += still(MON, "00:00", "24:00", HOME, 5)
    # Havbris: in her berth, the passage with the owner aboard, at anchor, home alone on Sunday
    drafts += still(FRI, "00:00", "17:00", MARINA, 2, YACHT)
    drafts += under_way(FRI, "17:00", "20:00", route, 2, YACHT)
    drafts += still(FRI, "20:00", "24:00", ANCHORAGE, 2, YACHT)
    drafts += still(SAT, "00:00", "24:00", ANCHORAGE, 2, YACHT)
    drafts += still(SUN, "00:00", "12:00", ANCHORAGE, 2, YACHT)
    drafts += under_way(SUN, "12:00", "15:00", list(reversed(route)), 2, YACHT)
    drafts += still(SUN, "15:00", "24:00", MARINA, 2, YACHT)
    drafts += still(MON, "00:00", "24:00", MARINA, 10, YACHT)
    # Lerka: one loop over the fjord
    drafts += under_way(MON, "11:00", "12:30", [KJELLER, FJORD, HYTTA, KJELLER], 1, PLANE)
    # the rest
    drafts += [photo(utc(FRI, "18:30"), (59.85, 10.70)), photo(utc(SAT, "14:00"), HYTTA)]
    drafts += [photo(utc(SAT, "14:05"), HYTTA), passage(), taxi(), chapter()]
    return drafts


def world_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """The weekend written into a fresh record under `tmp_path`, both assets registered and the
    three places named."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(world_drafts())
    (lb.root / "assets.json").write_text(json.dumps({"assets": ASSETS}, indent=2), encoding="utf-8")
    (lb.root / "places.json").write_text(json.dumps(PLACES, indent=2, ensure_ascii=False), encoding="utf-8")
    return lb
