"""Two synthetic records of the same cabin weekend, for the shared-trip tests (RFC 0030).

Ines Lund and Ola Nordmann, who do not exist, spend Friday 12 to Sunday 14 June 2026 at a cabin in
the mountains, each with their own record: Ines calls the place "Cabin", Ola calls it "Hytta" and
names it a few dozen metres off; Ola also walks to a bakery on the Saturday that Ines's record
knows nothing about, has Kari Nordmann in the calendar entry and in a note, and tags Kari's face
in a photo. One photo was shared between the two libraries under the same asset id, so both records
carry a line with the same `raw_id`. Every coordinate, address and id is invented; the emails are
at example.org and the phone numbers are in the reserved +47 9000 000x range the RFC examples use.
Ola's record has a crossing policy that lets tier 2 cross to `ines`."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from persona import attendee, dwell, event, note, photo, resolution, travel, utc

from logbook.core.store import Logbook

TZ = "Europe/Oslo"
INES_HOME = (59.9300, 10.7000)
OLA_HOME = (59.8900, 10.8000)
CABIN = (60.8600, 8.5500)  # as Ines's record names it
HYTTA = (60.8604, 8.5506)  # the same cabin, as Ola's record names it: about 55 m off
BAKERY = (60.8700, 8.5700)  # Ola's Saturday walk, 1.5 km from the cabin; Ines never went
INES = {"email": "ines@example.org", "phone": "+4790000003", "name": "Ines Lund"}
OLA = {"email": "ola@example.org", "phone": "+4790000001", "name": "Ola Nordmann"}
KARI = {"email": "kari.nordmann@example.org", "face": "p_17", "name": "Kari Nordmann"}
OLA_IN_INES = "019cadd3-6bc0-7dcd-9133-00000000a001"  # Ola's entity id in Ines's record
INES_IN_OLA = "019cadd3-6bc0-7dcd-9133-00000000b001"  # Ines's entity id in Ola's record
KARI_IN_OLA = "019cadd3-6bc0-7dcd-9133-00000000b002"
THU, FRI, SAT, SUN, MON = "2026-06-11", "2026-06-12", "2026-06-13", "2026-06-14", "2026-06-15"
TRIP = "trip:2026-06-12:2026-06-13"
SHARED_PHOTO = "p-shared-0001"  # the asset id a photo has in both libraries
PIXELS = b"not a photo, eleven bytes of nothing\n"
PIXELS_SHA = hashlib.sha256(PIXELS).hexdigest()


def _home_nights(home: tuple[float, float]) -> list[dict[str, Any]]:
    """Thursday evening and Friday morning at home, Sunday evening and Monday morning at home."""
    return (
        dwell(THU, "18:30", "24:00", home)
        + dwell(FRI, "00:00", "07:30", home)
        + dwell(SUN, "15:00", "24:00", home)
        + dwell(MON, "00:00", "07:30", home)
    )


def ines_drafts() -> list[dict[str, Any]]:
    cabin_photo = photo(utc(SAT, "15:00"), CABIN)
    cabin_photo["payload"]["asset_id"] = cabin_photo["payload"]["raw_id"] = SHARED_PHOTO
    return [
        resolution(("email", OLA["email"]), OLA_IN_INES, OLA["name"]),
        resolution(("phone", OLA["phone"]), OLA_IN_INES, OLA["name"]),
        *_home_nights(INES_HOME),
        *travel(FRI, "07:30", "11:00", INES_HOME, CABIN, steps=12),
        *dwell(FRI, "11:00", "24:00", CABIN),
        *dwell(SAT, "00:00", "24:00", CABIN),
        *dwell(SUN, "00:00", "11:00", CABIN),
        *travel(SUN, "11:00", "15:00", CABIN, INES_HOME, steps=12),
        event(
            utc(FRI, "12:00"),
            utc(FRI, "20:00"),
            "Cabin weekend",
            [attendee(INES["email"], INES["name"]), attendee(OLA["email"], OLA["name"])],
        ),
        cabin_photo,
    ]


def ola_drafts() -> list[dict[str, Any]]:
    shared = photo(utc(SAT, "15:00"), HYTTA)
    shared["payload"]["asset_id"] = shared["payload"]["raw_id"] = SHARED_PHOTO
    with_pixels = photo(utc(SAT, "11:30"), HYTTA)
    with_pixels["payload"]["extra"] = {
        "media": {
            "sha256": PIXELS_SHA,
            "path": f"attachments/{PIXELS_SHA}",
            "bytes": len(PIXELS),
            "media_type": "image/jpeg",
        }
    }
    return [
        resolution(("email", INES["email"]), INES_IN_OLA, INES["name"]),
        resolution(("email", KARI["email"]), KARI_IN_OLA, KARI["name"]),
        resolution(("provider_id", f"immich:{KARI['face']}"), KARI_IN_OLA, KARI["name"]),
        *_home_nights(OLA_HOME),
        *travel(FRI, "07:30", "12:30", OLA_HOME, HYTTA, steps=12),
        *dwell(FRI, "12:30", "24:00", HYTTA),
        *dwell(SAT, "00:00", "09:30", HYTTA),
        *travel(SAT, "09:30", "09:45", HYTTA, BAKERY, steps=3),
        *dwell(SAT, "09:45", "10:30", BAKERY),
        *travel(SAT, "10:30", "10:45", BAKERY, HYTTA, steps=3),
        *dwell(SAT, "10:45", "24:00", HYTTA),
        *dwell(SUN, "00:00", "10:00", HYTTA),
        *travel(SUN, "10:00", "15:00", HYTTA, OLA_HOME, steps=12),
        event(
            utc(FRI, "13:00"),
            utc(FRI, "21:00"),
            "Hyttetur",
            [attendee(INES["email"], INES["name"]), attendee(KARI["email"], KARI["name"])],
        ),
        note(utc(SAT, "19:00"), f"Grilling with {KARI['name']}"),
        photo(utc(SAT, "11:00"), HYTTA, people=[KARI["face"]]),
        with_pixels,
        shared,
    ]


def _record(
    root: Path,
    drafts: list[dict[str, Any]],
    home: tuple[float, float],
    cabin: tuple[str, tuple[float, float]],
    owner: dict[str, str],
) -> Logbook:
    lb = Logbook.init(root, TZ)
    lb.append_many(drafts)
    (lb.root / "places.json").write_text(
        json.dumps(
            {
                "Home": {"lat": home[0], "lon": home[1], "radius_m": 120, "kind": "home"},
                cabin[0]: {"lat": cabin[1][0], "lon": cabin[1][1], "radius_m": 150},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (lb.root / "policy" / "owner.json").write_text(
        json.dumps({"names": [owner["name"]], "emails": [owner["email"]], "phones": [owner["phone"]]}),
        encoding="utf-8",
    )
    return lb


def ines_record(tmp_path: Path) -> Logbook:
    """Ines's record under `tmp_path / "ines"`: the cabin weekend as she saw it."""
    return _record(tmp_path / "ines", ines_drafts(), INES_HOME, ("Cabin", CABIN), INES)


def ola_record(tmp_path: Path) -> Logbook:
    """Ola's record under `tmp_path / "ola"`: the same weekend, the bakery, Kari, one photo's bytes
    in the store, and a crossing policy that lets tier 2 cross to `ines`."""
    lb = _record(tmp_path / "ola", ola_drafts(), OLA_HOME, ("Hytta", HYTTA), OLA)
    lb.attach(PIXELS)
    policy_file = lb.root / "policy" / "crossing.json"
    policy_data = json.loads(policy_file.read_text(encoding="utf-8"))
    policy_data["ines"] = {"max_tier": 2}
    policy_file.write_text(json.dumps(policy_data, indent=2) + "\n", encoding="utf-8")
    return lb
