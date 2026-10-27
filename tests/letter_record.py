"""A synthetic fortnight for `logbook export letter`: the dream fortnight (`dream_fortnight.py`, Monday 8
to Sunday 21 June 2026, the Oslo persona, three nights in Zürich from Monday 15 June) with what the
owner, Ines Nordmann, and the dream added to it: a draft of each day from the 8th to the 17th, of the
second week and of the journey (pencil, model `qwen2.5-7b-instruct`); four reflections in her words and
one through the door; a W24 draft resting on the unsigned Friday; stars on the Zürich dinner, on her
note of what was agreed and on a tier-3 workout; five starred photos, four with pixels in the record's
own store (one of them over the letter's cap) and one a HEIC the store does not hold; two goal reviews;
Kari stated present on Saturday 20 June; and every day signed but Friday 12 June. Kari Nordmann, who
lives with Ines, is who the letter is for. Nobody here exists: example.org addresses, carrier XY, which
is no airline, and pixels that are a few bytes of a format's signature."""

from __future__ import annotations

import json
import zlib
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from dream_fortnight import DAYS, DREAM_ENTRY, GOAL_READ, GOAL_SAIL, JOURNEY, MODEL, NOTE_ZURICH, fortnight
from persona import ZURICH, utc

from logbook.contrib import letter
from logbook.core import attachments, drafts, goals, notes, policy, presence, signing, stars
from logbook.core.store import Logbook

FROM, TO = DAYS[0], DAYS[-1]  # 2026-06-08, 2026-06-21
UNSIGNED = "2026-06-12"  # the one day Ines has not signed
FOR = "Kari Nordmann"
LETTER_ENTRY = {"max_tier": 2, "until": "2026-12-31"}
TODAY = date(2026, 6, 25)
NOW = datetime(2026, 6, 25, 8, 0, tzinfo=UTC)

# the reflections, in her words; the 16th's is the longest signed one, the 12th's longer still but unsigned
REFLECTIONS = {
    "2026-06-08": "A long Monday at the office. Kari made soup.",
    UNSIGNED: (
        "Friday, and the week caught up with me in a way I did not expect at all. I sat on the stairs"
        " with a cup of tea and watched the tram go by for an hour before I went in to the others."
    ),
    "2026-06-16": (
        "The dinner ran late and the lake was still when we walked back to the hotel. We agreed on the"
        " berth, and Ola laughed at the price."
    ),
    "2026-06-20": "Home again. The fjord was grey and good.",
}
MONTH_SENTENCE = "The dinner ran late and the lake was still when we walked back to the hotel."
UNSIGNED_WORDS = "watched the tram go by"
STORY = "A day the dream read from the record."  # each day's draft says this, then the day's date
WEEK_STORY = "The second week went to Zürich and back."
WEEK_ONE_STORY = f"On Friday she {UNSIGNED_WORDS} for an hour."  # W24's draft rests on the unsigned day
DOOR_REFLECTION = (  # through the door (`note_day`), not in her hand: never in ink, never the card's
    "An agent wrote this through the door on Friday the nineteenth, a long and careful sentence that is"
    " longer than any reflection Ines wrote in June. It goes on."
)
JOURNEY_STORY = "Three nights in Zürich, a dinner and the berth agreed."  # no figure beside a name (R6)
DINNER_NOTE = "the table by the window"
WORKOUT_NOTE = "a hard morning on the rower"  # on a tier-3 line: never in a letter by default

CAMERA = b"GPS 59.9139,10.7522 synthetic"  # what a camera writes beside the pixels: never in a letter


def _segment(marker: int, data: bytes) -> bytes:
    return bytes([0xFF, marker]) + (len(data) + 2).to_bytes(2, "big") + data


def jpeg(scan: bytes = b"\x10\x20\x30") -> bytes:
    """A JPEG's shape: JFIF, an EXIF segment with a position in it, a comment, then the scan."""
    return (
        b"\xff\xd8"
        + _segment(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
        + _segment(0xE1, b"Exif\x00\x00" + CAMERA)
        + _segment(0xFE, b"comment " + CAMERA)
        + _segment(0xDA, b"\x01\x01\x00\x00\x3f\x00")
        + scan
        + b"\xff\xd9"
    )


def _chunk(kind: bytes, data: bytes) -> bytes:
    return len(data).to_bytes(4, "big") + kind + data + zlib.crc32(kind + data).to_bytes(4, "big")


def png() -> bytes:
    """A PNG's shape: one pixel, and a text chunk and an `eXIf` chunk with a position in them."""
    header = (1).to_bytes(4, "big") * 2 + bytes([8, 2, 0, 0, 0])
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"tEXt", b"Comment\x00" + CAMERA)
        + _chunk(b"eXIf", CAMERA)
        + _chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
        + _chunk(b"IEND", b"")
    )


JPEG, PNG = jpeg(), png()
BIG = jpeg(b"\x01" * (letter.PHOTO_MAX_BYTES + 1))  # over the cap once stripped
STORED_PHOTOS = {  # day → (file name, bytes, media type)
    "2026-06-09": ("IMG_BIG.JPG", BIG, "image/jpeg"),
    UNSIGNED: ("IMG_FRIDAY.JPG", JPEG, "image/jpeg"),
    "2026-06-13": ("IMG_SATURDAY.PNG", PNG, "image/png"),
    "2026-06-16": ("IMG_LAKE.JPG", JPEG + b"lake", "image/jpeg"),
}


def set_policy(root: Path, entry: dict[str, Any] | None, dream: dict[str, Any] = DREAM_ENTRY) -> None:
    """The crossing policy: hermes, mcp, the `dream` entry `dream` (the fortnight's unless given) and
    the `letter` entry `entry`, or none."""
    data: dict[str, Any] = {"hermes": {"max_tier": 2}, "mcp": {"max_tier": 1}, "dream": dream}
    if entry is not None:
        data[letter.DESTINATION] = entry
    path = policy.policy_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _draft(
    unit: str, subject: object, segments: list[tuple[str, str]], evidence: str, at: str
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": drafts.SCHEMA,
        "unit": unit,
        "subject": subject,
        "read_head": "0" * 64,
        "read_count": 1,
        "language": "en",
        "segments": [{"text": text, "evidence": [evidence]} for _, text in segments],
        "extra": {"prompt": "test/1", "parts": [part for part, _ in segments], "policy_version": "0" * 64},
    }
    assert drafts.validate(payload) == []
    return {"at": at, "source": f"model:{MODEL}", "kind": drafts.KIND, "tier": 2, "payload": payload}


def _photo(day: str, name: str, data: bytes, media_type: str) -> dict[str, Any]:
    return {
        "at": utc(day, "12:00"),
        "source": "apple-photos",
        "kind": "photo",
        "tier": 1,
        "payload": {
            "schema": "photo/v1",
            "asset_id": f"stored-{day}",
            "library": "apple-photos",
            "file_name": name,
            "media": "image",
            "raw_id": f"stored-{day}",
            "lat": ZURICH[0],
            "lon": ZURICH[1],
            "content": attachments.reference(data, media_type),
        },
    }


def _on(lines: list[dict[str, Any]], day: str) -> dict[str, Any]:
    """A line of `day` to rest a draft on: the first whose instant is in the middle of it."""
    return next(line for line in lines if utc(day, "06:00") <= line["at"] <= utc(day, "18:00"))


def record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry: dict[str, Any] | None = LETTER_ENTRY
) -> Logbook:
    """The fortnight with everything above, at `tmp_path/lb`; the `letter` entry `entry`, or none; the
    policy's today and the letter's clock pinned to 25 June 2026."""
    lb = fortnight(tmp_path / "lb")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.setattr(policy, "today", lambda: TODAY)
    monkeypatch.setattr(letter, "now", lambda: NOW)
    set_policy(lb.root, entry)
    for day, (name, data, media_type) in STORED_PHOTOS.items():
        attachments.write(lb.root, data)
        lb.append(**_photo(day, name, data, media_type))
    lines = list(lb.lines())
    found = [
        _draft(
            drafts.UNIT_DAY,
            day,
            [("day", f"{STORY} {day}."), ("threads", "The berth.")],
            str(_on(lines, day)["id"]),
            utc(day, "21:30"),
        )
        for day in DAYS[:10]
    ]
    zurich = str(_on(lines, "2026-06-16")["id"])
    friday = str(_on(lines, UNSIGNED)["id"])
    found.append(
        _draft(drafts.UNIT_WEEK, "2026-W24", [("time", WEEK_ONE_STORY)], friday, utc("2026-06-14", "20:00"))
    )
    found.append(
        _draft(drafts.UNIT_WEEK, "2026-W25", [("time", WEEK_STORY)], zurich, utc("2026-06-21", "20:00"))
    )
    found.append(
        _draft(
            drafts.UNIT_JOURNEY, [JOURNEY], [("journey", JOURNEY_STORY)], zurich, utc("2026-06-18", "21:00")
        )
    )
    lb.append_many(found)
    for day, text in REFLECTIONS.items():
        notes.write(lb, day, text, notes.REFLECTION, "reflect")
    notes.write(lb, "2026-06-19", DOOR_REFLECTION, notes.REFLECTION, "mcp")
    lines = list(lb.lines())
    by_kind = {
        "dinner": next(
            line for line in lines if line["kind"] == "event" and line["payload"]["title"] == "Dinner"
        ),
        "note": next(
            line for line in lines if line["kind"] == "note" and line["payload"].get("text") == NOTE_ZURICH
        ),
        "workout": next(
            line for line in lines if line["kind"] == "health" and line["payload"].get("type") == "workout"
        ),
    }
    stars.star(lb, str(by_kind["dinner"]["id"]), DINNER_NOTE)
    stars.star(lb, str(by_kind["note"]["id"]))
    stars.star(lb, str(by_kind["workout"]["id"]), WORKOUT_NOTE)
    for line in lines:
        if line["kind"] == "photo" and (
            line["source"] == "apple-photos" or line["payload"].get("extra", {}).get("favorite")
        ):
            stars.star(lb, str(line["id"]))
    goal_ids = {line["payload"]["text"]: str(line["id"]) for line in lines if line["kind"] == "goal"}
    goals.review(
        lb, goal_ids[GOAL_SAIL], "advancing", "week", "Two days on the water.", utc("2026-06-14", "18:00")
    )
    goals.review(lb, goal_ids[GOAL_READ], "done", "month", None, utc("2026-06-20", "18:00"))
    presence.state(lb, "2026-06-20", [FOR], at="10:00")  # Kari, at home on Saturday
    for day in DAYS:
        if day != UNSIGNED:
            signing.sign(lb, day, at=utc(day, "21:55"))
    return lb
