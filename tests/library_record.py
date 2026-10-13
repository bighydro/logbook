"""The four synthetic years of `four_years.py` with what the Library's Journeys and People pages show
besides: two photos and a promise on the Bergen winter of 2022, a model's draft of that journey (one
sentence with its line, one unsupported, one resting on a line from another year), and an address
the sources saw under Astrid Bakke's name that no resolution line names, which `people review`
proposes against her. Nobody here exists; emails at example.org, numbers in 07700 900xxx."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from four_years import BERGEN, OSLO, OWNER, four_years_record, mail
from persona import note, photo, utc

from logbook.core.store import Logbook

BERGEN_WINTER = "trip:2022-01-03:2022-03-31"  # the first journey of the four years
PHOTO_A = "019cadd3-6bc0-7dcd-9133-0000000002a1"
PHOTO_B = "019cadd3-6bc0-7dcd-9133-0000000002a2"
PHOTO_HOME = "019cadd3-6bc0-7dcd-9133-0000000002a3"
PROMISE = "I'll send Astrid the harbour map by Friday."
DRAFT_SOURCE = "model:qwen2.5-7b-instruct"
ASTRID_ELSEWHERE = {"email": "a.bakke@example.org", "name": "Astrid Bakke"}  # observed, not resolved


def _with_id(line: dict[str, Any], id_: str) -> dict[str, Any]:
    return {"id": id_, **line}


def journey_draft(evidence: list[str], subject: str = BERGEN_WINTER) -> dict[str, Any]:
    """A model's draft of the journey: a sentence on its photos, one unsupported, one on `evidence`."""
    return {
        "at": utc("2022-04-02", "07:00"),
        "source": DRAFT_SOURCE,
        "kind": "draft",
        "tier": 2,
        "payload": {
            "schema": "draft/v1",
            "unit": "journey",
            "subject": [subject],
            "read_head": "b" * 64,
            "read_count": 40,
            "language": "en",
            "segments": [
                {"text": "Two photos of the harbour in the first month.", "evidence": [PHOTO_A, PHOTO_B]},
                {"text": "It rained every day.", "unsupported": True},
                {"text": "The year ended at home.", "evidence": evidence},
            ],
        },
    }


def extras() -> list[dict[str, Any]]:
    return [
        _with_id(photo(utc("2022-01-03", "12:00"), BERGEN), PHOTO_A),
        _with_id(photo(utc("2022-02-01", "12:00"), BERGEN), PHOTO_B),
        _with_id(photo(utc("2022-06-01", "12:00"), OSLO), PHOTO_HOME),
        note(utc("2022-01-10", "14:30"), PROMISE),
        journey_draft([PHOTO_HOME]),
        mail(utc("2025-03-01", "09:00"), ASTRID_ELSEWHERE, [OWNER], "Photos from the harbour"),
    ]


def library_record(root: Path) -> Logbook:
    lb = four_years_record(root)
    lb.append_many(extras())
    return lb
