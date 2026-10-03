"""The calendar source: an attendee of an `event/v1` held at the stay."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from ..chain import Line
from ..places import Place, distance_m
from ..resolve import Identity, Ref
from ..stays import Segment
from .evidence import _overlap_s, _overlaps
from .model import ACCEPTED, ALL_DAY, CONFIRMED, PROPOSED, TENTATIVE, Presence
from .names import _ref, _resolve

EVENT_INSIDE_M = 1000.0  # a located event this close to the stay's centre is held at the stay
EVENT_OVERLAP_S = 3600  # an event with no location must overlap the stay by more than this
SYSTEM_ADDRESS = re.compile(r"(calendar\.google\.com$)|(^(no-?reply|reservations|invite)(@|[.+-]))")


def from_calendar(
    stay: Segment, lines: Iterable[Line], identities: Mapping[Ref, Identity], places: Sequence[Place] = ()
) -> list[Presence]:
    found = []
    for line in lines:
        if line.get("kind") != "event" or not _held_at(stay, line, places):
            continue
        payload = line.get("payload") or {}
        title = str(payload.get("title") or "an event")
        all_day = payload.get("all_day") is True
        attendees = payload.get("attendees")
        for attendee in attendees if isinstance(attendees, list) else []:
            if not isinstance(attendee, dict):
                continue
            response = attendee.get("response")
            if response == "declined":
                continue
            ref = _ref(attendee.get("ref"))
            if ref is None or _system_address(ref):
                continue
            person, label = _resolve(ref, identities)
            given = attendee.get("name")
            name = label or (str(given) if isinstance(given, str) and given.strip() else None)
            if name is None:
                continue  # a bare address nobody has named
            if all_day:
                confidence, status, reason = ALL_DAY, PROPOSED, f"attendee of {title} (all day)"
            else:
                confidence = ACCEPTED if response == "accepted" else TENTATIVE
                status, reason = CONFIRMED, f"attendee of {title}"
            found.append(Presence(person, name, ref, confidence, status, "calendar", reason, str(line["id"])))
    return found


def _held_at(stay: Segment, line: Line, places: Sequence[Place]) -> bool:
    """Whether a calendar entry was held at the stay: timed, and either located within
    `EVENT_INSIDE_M` of the stay's centre or unlocated and overlapping it by more than
    `EVENT_OVERLAP_S`."""
    payload = line.get("payload") or {}
    if not _overlaps(stay, line):
        return False
    where = _event_coordinates(payload, places)
    if payload.get("all_day") is True and where is None:
        return False  # it overlaps every stay of its day and places nobody at any one of them
    if where is None:
        return payload.get("location") in (None, "") and _overlap_s(stay, line) > EVENT_OVERLAP_S
    if stay.lat is None or stay.lon is None:
        return False
    return distance_m(stay.lat, stay.lon, where[0], where[1]) <= EVENT_INSIDE_M


def _event_coordinates(payload: Mapping[str, Any], places: Sequence[Place]) -> tuple[float, float] | None:
    """Where an event/v1 was held: `extra.location.latitude`/`longitude` as ios-calendar and ics
    write them, else the place in places.json whose name is the `location` text, case aside."""
    extra = payload.get("extra")
    detail = extra.get("location") if isinstance(extra, dict) else None
    if isinstance(detail, dict):
        lat, lon = detail.get("latitude"), detail.get("longitude")
        if isinstance(lat, int | float) and isinstance(lon, int | float):
            return float(lat), float(lon)
    location = payload.get("location")
    if isinstance(location, str) and location.strip():
        wanted = " ".join(location.split()).casefold()
        for place in places:
            if place.name.casefold() == wanted:
                return place.lat, place.lon
    return None


def _system_address(ref: Ref) -> bool:
    return ref[0] == "email" and SYSTEM_ADDRESS.search(ref[1].strip().casefold()) is not None
