"""The four synthetic years of `four_years.py` with what the Library's Journeys and People pages show
besides: two photos and a promise on the Bergen winter of 2022, a model's draft of that journey (one
sentence with its line, one unsupported, one resting on a line from another year) under the `dream`
entry of the crossing policy that let it be written (`DREAM_ENTRY`, its version under
`extra.policy_version`, as every draft records it), and an address the sources saw under Astrid
Bakke's name that no resolution line names, which `people review` proposes against her. Nobody here
exists; emails at example.org, numbers in 07700 900xxx."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from four_years import BERGEN, OSLO, OWNER, four_years_record, mail
from persona import note, photo, utc

from logbook.core import policy
from logbook.core.store import Logbook

BERGEN_WINTER = "trip:2022-01-03:2022-03-31"  # the first journey of the four years
PHOTO_A = "019cadd3-6bc0-7dcd-9133-0000000002a1"
PHOTO_B = "019cadd3-6bc0-7dcd-9133-0000000002a2"
PHOTO_HOME = "019cadd3-6bc0-7dcd-9133-0000000002a3"
PROMISE = "I'll send Astrid the harbour map by Friday."
DRAFT_SOURCE = "model:qwen2.5-7b-instruct"
ASTRID_ELSEWHERE = {"email": "a.bakke@example.org", "name": "Astrid Bakke"}  # observed, not resolved
DREAM_ENTRY = {"max_tier": 2}  # the `dream` entry the journey's draft was written under


def _with_id(line: dict[str, Any], id_: str) -> dict[str, Any]:
    return {"id": id_, **line}


def journey_draft(evidence: list[str], version: str, subject: str = BERGEN_WINTER) -> dict[str, Any]:
    """A model's draft of the journey: a sentence on its photos, one unsupported, one on `evidence`;
    written under the `dream` entry of `version` (`policy.version`)."""
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
            "extra": {"policy_version": version},
        },
    }


def dream(root: Path, entry: dict[str, Any] | None) -> None:
    """The crossing policy's `dream` entry as `entry`, or none; the rest of the file as it is."""
    path = policy.policy_path(root)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data.pop(policy.DREAM_DESTINATION, None)
    if entry is not None:
        data[policy.DREAM_DESTINATION] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def extras(version: str) -> list[dict[str, Any]]:
    return [
        _with_id(photo(utc("2022-01-03", "12:00"), BERGEN), PHOTO_A),
        _with_id(photo(utc("2022-02-01", "12:00"), BERGEN), PHOTO_B),
        _with_id(photo(utc("2022-06-01", "12:00"), OSLO), PHOTO_HOME),
        note(utc("2022-01-10", "14:30"), PROMISE),
        journey_draft([PHOTO_HOME], version),
        mail(utc("2025-03-01", "09:00"), ASTRID_ELSEWHERE, [OWNER], "Photos from the harbour"),
    ]


def library_record(root: Path) -> Logbook:
    lb = four_years_record(root)
    dream(root, DREAM_ENTRY)
    lb.append_many(extras(policy.version(policy.dream_entry(root))))
    return lb
