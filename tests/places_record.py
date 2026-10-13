"""A synthetic fortnight at sea for `places review`: 2,000 tracker points that form twelve observed
places in the open North Sea, where nobody lives, around 55.6 N 4.4 E. Every coordinate, name and
address is invented; the record's zone is the persona's, Europe/Oslo.

Twelve nights (the 2nd to the 13th of February 2026) and twelve days. The owner sleeps at S1 six
nights, at S2 three, at S3 two and at S4 one; the days go to S5 (20 hours), S6 (15), S7 (12), S8 (10),
S9 (8), S10 (6), S11 (4) and S12 (3). A Google Timeline export (the archive's Semantic Location
History, read through the takeout adapter) names S1, S2 and S4; a photo Photos named names S5; a
calendar entry held during a visit names S6. A Teams meeting and an all-day entry name nothing; an
Immich photo at S1 gives its city, which loses to the Timeline's name."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from persona import dwell, event, photo, travel, utc

from logbook.contrib.adapters.takeout import location
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
TRACKER_POINTS = 2000


def spot(i: int) -> tuple[float, float]:
    """S1 … S12: four columns, three rows, about 1.1 km apart, all at sea."""
    row, col = divmod(i - 1, 4)
    return (round(55.60 + 0.01 * row, 6), round(4.40 + 0.018 * col, 6))


S = {i: spot(i) for i in range(1, 13)}
FIRST = date(2026, 2, 2)
DAYS = [(FIRST + timedelta(days=d)).isoformat() for d in range(13)]
NIGHTS = [1, 1, 2, 1, 2, 3, 1, 4, 1, 3, 2, 1]  # the spot of the night after each day 0 … 11
VISITS: dict[int, list[tuple[int, int]]] = {  # day → (spot, hours), in order
    1: [(5, 4), (7, 3)],
    2: [(6, 3), (8, 2)],
    3: [(5, 4), (8, 2), (9, 2)],
    4: [(6, 3), (7, 3), (10, 2)],
    5: [(5, 4), (8, 2)],
    6: [(6, 3), (9, 2), (11, 2)],
    7: [(5, 4), (7, 3)],
    8: [(6, 3), (8, 2)],
    9: [(5, 4), (9, 2), (10, 2)],
    10: [(6, 3), (7, 3)],
    11: [(8, 2), (11, 2)],
    12: [(9, 2), (10, 2), (12, 3)],
}
NIGHTS_AT = {1: 6, 2: 3, 3: 2, 4: 1}
HOURS_BY_DAY = {5: 20, 6: 15, 7: 12, 8: 10, 9: 8, 10: 6, 11: 4, 12: 3}
CABIN, WORKSHOP, BOATHOUSE = "Hytta på banken", "Verkstedet", "Sjøbua"
LIGHTHOUSE, CLUBHOUSE = "Fyrlykta", "Klubbhuset"
TIMELINE_NIGHTS = {
    0: (1, CABIN),
    3: (1, CABIN),
    6: (1, CABIN),
    2: (2, WORKSHOP),
    4: (2, WORKSHOP),
    7: (4, BOATHOUSE),
}


def _clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def tracker_points() -> list[dict[str, Any]]:
    """The 2,000 points, in time order: each night every 15 minutes from arrival to 08:00, each visit
    every 5 minutes, half an hour of travel between spots (five points on the way)."""
    out: list[dict[str, Any]] = []
    at = 21 * 60  # day 0: the owner reaches S1 at 21:00
    where = S[NIGHTS[0]]
    for d, day in enumerate(DAYS):
        if d > 0:  # the morning: leave the night's spot at 08:00
            at = 8 * 60
            for spot_n, hours in VISITS[d]:
                out += travel(day, _clock(at), _clock(at + 30), where, S[spot_n])
                at += 30
                out += dwell(day, _clock(at), _clock(at + 60 * hours), S[spot_n], every_min=5, noise_m=20)
                at += 60 * hours
                where = S[spot_n]
        if d < len(NIGHTS):
            night = S[NIGHTS[d]]
            if d > 0:
                out += travel(day, _clock(at), _clock(at + 30), where, night)
                at += 30
            out += dwell(day, _clock(at), "24:00", night, every_min=15, noise_m=20)
            out += dwell(DAYS[d + 1], "00:00", "08:00", night, every_min=15, noise_m=20)
            where = night
    pad = TRACKER_POINTS - len(out)  # the last night at S1 is heard more often after midnight
    assert 0 <= pad <= 90, pad
    out += dwell(DAYS[12], "00:02", "07:47", S[1], every_min=5, noise_m=20)[:pad]
    out.sort(key=lambda line: line["at"])
    return out


def timeline_export(folder: Path) -> Path:
    """The archive's monthly file, as Google wrote them before 2025: one placeVisit per night the
    Timeline knew, named, 25 m from where the tracker put the owner (Google's pin of the place)."""
    objects = []
    for d, (spot_n, name) in sorted(TIMELINE_NIGHTS.items()):
        lat, lon = S[spot_n]
        objects.append(
            {
                "placeVisit": {
                    "location": {
                        "latitudeE7": round((lat + 0.000225) * 1e7),
                        "longitudeE7": round(lon * 1e7),
                        "placeId": f"ChIJ-synthetic-s{spot_n}",
                        "address": f"Plattformveien {spot_n}, Nordsjøen",
                        "name": name,
                        "semanticType": "TYPE_HOME" if spot_n == 1 else "TYPE_UNKNOWN",
                    },
                    "duration": {
                        "startTimestamp": utc(DAYS[d], "22:00"),
                        "endTimestamp": utc(DAYS[d + 1], "06:00"),
                    },
                    "placeConfidence": "HIGH_CONFIDENCE",
                }
            }
        )
    path = folder / "Semantic Location History" / "2026" / "2026_FEBRUARY.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"timelineObjects": objects}, ensure_ascii=False), encoding="utf-8")
    return path


def evidence_lines() -> list[dict[str, Any]]:
    """The photos and calendar entries: the lighthouse photo Photos named, an Immich photo with its
    city at the cabin, the clubhouse meeting, a Teams call and an all-day entry naming nothing."""
    lighthouse = []
    for day, clock in ((DAYS[1], "10:00"), (DAYS[3], "09:30")):
        line = photo(utc(day, clock), (S[5][0] + 0.00005, S[5][1]), library="apple-photos")
        line["payload"]["extra"] = {"place": {"names": [LIGHTHOUSE, "Nordsjøen"], "city": "Nordsjøen"}}
        lighthouse.append(line)
    cabin = photo(utc(DAYS[4], "23:00"), (S[1][0], S[1][1] + 0.00005))
    cabin["payload"]["extra"] = {"place": {"city": "Nordsjøen", "country": "Nordsjøen"}}
    regatta = event(utc(DAYS[3], "00:00"), utc(DAYS[4], "00:00"), "Regatta", location="Somewhere else")
    regatta["payload"]["all_day"] = True
    return [
        *lighthouse,
        cabin,
        event(utc(DAYS[2], "09:00"), utc(DAYS[2], "10:30"), "Board meeting", location=CLUBHOUSE),
        event(
            utc(DAYS[1], "13:30"), utc(DAYS[1], "14:30"), "Weekly sync", location="Microsoft Teams Meeting"
        ),
        regatta,
    ]


def record(root: Path) -> Logbook:
    lb = Logbook.init(root, TZ)
    lb.append_many(tracker_points())
    lb.append_many(location.run(timeline_export(root.parent / "takeout")))
    lb.append_many(evidence_lines())
    return lb


# -- photos the libraries can name: `places review --ask-photos` -------------------------------------------
#
# Photo lines imported before #255 carry no place: the record holds their coordinates and asset ids, the
# libraries the names. Twelve Immich photos at S3 (the 404th at 120 m is no longer on the server), two at
# S1 (named by the Timeline: asked only with --all), three Photos pictures at S7 (and one the library
# has lost), none at S8. Immich's city and Photos' area are invented, as everything here.

HARBOUR_TOWN, PLATFORM = "Havbyen", "Plattformen"


def immich_id(n: int) -> str:
    return f"0000a5e7-0000-4000-8000-{n:012x}"


def apple_id(n: int) -> str:
    return f"A7000000-0000-4000-8000-{n:012d}"


AT_S3 = [immich_id(0x300 + k) for k in range(12)]  # 0, 8, … 88 m north of S3: the nearest first
GONE = immich_id(0x3FF)  # 120 m north of S3, deleted from the server since the import
AT_S1 = [immich_id(0x100 + k) for k in range(2)]
AT_S7 = [apple_id(k) for k in range(1, 4)]
LOST = apple_id(9)  # at S7, not in the library any more


def _north(where: tuple[float, float], metres: float) -> tuple[float, float]:
    return (round(where[0] + metres / 111_320, 7), where[1])


def _photo_line(at: str, where: tuple[float, float], asset_id: str, library: str) -> dict[str, Any]:
    line = photo(at, where, library=library)
    line["payload"]["asset_id"] = line["payload"]["raw_id"] = asset_id
    return line


def unplaced_photos() -> list[dict[str, Any]]:
    """The photo lines without `extra.place`: their libraries know the place, the record does not."""
    out = [
        _photo_line(utc(DAYS[5], f"22:{k:02d}"), _north(S[3], 8 * k), asset, "immich")
        for k, asset in enumerate(AT_S3)
    ]
    out.append(_photo_line(utc(DAYS[9], "23:00"), _north(S[3], 120), GONE, "immich"))
    out += [
        _photo_line(utc(DAYS[1], f"21:{10 + k:02d}"), _north(S[1], 10 * k), asset, "immich")
        for k, asset in enumerate(AT_S1)
    ]
    out += [
        _photo_line(utc(DAYS[4], f"11:{10 + k:02d}"), _north(S[7], 5 * k), asset, "apple-photos")
        for k, asset in enumerate([*AT_S7, LOST])
    ]
    return out


def immich_asset(asset_id: str) -> dict[str, Any] | None:
    """What `GET /api/assets/{id}` answers for an asset of the record, or None for one it lost: the
    asset with the city its server named from the coordinates."""
    if asset_id not in AT_S3 + AT_S1:
        return None
    return {
        "id": asset_id,
        "type": "IMAGE",
        "originalFileName": f"IMG_{asset_id[-4:]}.HEIC",
        "exifInfo": {"city": HARBOUR_TOWN, "state": None, "country": "Nordsjøen"},
    }


def library_assets() -> list[tuple[str, bytes | None, int | None]]:
    """The Photos library's rows for the pictures at S7: the area Photos named on the phone."""
    from photos_library import reverse_location

    blob = reverse_location("Plattformveien 7, Nordsjøen", "Nordsjøen", [PLATFORM, "Nordsjøen"])
    return [(asset, blob, 1) for asset in AT_S7]


def record_with_photos(root: Path) -> Logbook:
    """The fortnight, and then the photos whose places only their libraries know."""
    lb = record(root)
    lb.append_many(unplaced_photos())
    return lb
