"""The transcript source: a participant of a `transcript/v1` recorded inside the stay."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from ..chain import Line
from ..places import Place
from ..resolve import Identity, Ref
from ..stays import Segment
from .evidence import _overlaps
from .model import CONFIRMED, TRANSCRIPT, Presence
from .names import _by_name, _resolve


def from_transcript(
    stay: Segment, lines: Iterable[Line], identities: Mapping[Ref, Identity], places: Sequence[Place] = ()
) -> list[Presence]:
    found = []
    for line in lines:
        if line.get("kind") != "transcript" or not _overlaps(stay, line):
            continue
        payload = line.get("payload") or {}
        title = str(payload.get("title") or "a recording")
        participants = payload.get("participants")
        for participant in participants if isinstance(participants, list) else []:
            if not isinstance(participant, dict):
                continue
            person, label, ref = None, None, None
            for kind, field in (("email", "email"), ("phone", "phone"), ("provider_id", "provider_id")):
                value = participant.get(field)
                if isinstance(value, str) and value:
                    ref = (kind, value)
                    person, label = _resolve(ref, identities)
                    if person:
                        break
            spoken = participant.get("name")
            spoken = spoken if isinstance(spoken, str) and spoken.strip() else None
            if person is None and spoken:
                person, label = _by_name(spoken, identities)
            if person is None or not label:
                continue  # Speaker A, me, them, Unknown, a name the record has no person for
            found.append(
                Presence(
                    person,
                    label,
                    ref,
                    TRANSCRIPT,
                    CONFIRMED,
                    "transcript",
                    f"spoke in {title}",
                    str(line["id"]),
                )
            )
    return found
