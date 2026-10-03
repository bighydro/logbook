"""The note source: a `note/v1` written inside the stay that says "with <name>"."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

from ..chain import Line
from ..places import Place
from ..resolve import Identity, Ref
from ..stays import Segment
from .evidence import _inside
from .model import CONFIRMED, NOTE, Presence
from .names import _by_name

NAME = r"[A-ZÆØÅÄÖÜ][\w'\-]*"
WITH = re.compile(rf"\bwith\s+({NAME}(?:\s+(?:(?:and|og|&)\s+)?{NAME})*)")  # with Ola Nordmann and Kari
AND = re.compile(r"\s+(?:and|og|&)\s+")


def from_notes(
    stay: Segment, lines: Iterable[Line], identities: Mapping[Ref, Identity], places: Sequence[Place] = ()
) -> list[Presence]:
    found = []
    for line in lines:
        if line.get("kind") != "note" or not _inside(stay, line):
            continue
        text = str((line.get("payload") or {}).get("text") or "")
        for match in WITH.finditer(text):
            for name in AND.split(match.group(1)):
                name = name.strip()
                if not name:
                    continue
                person, label = _by_name(name, identities)
                if person is None or not label:
                    continue  # US, XYZ, a country, an acronym, a name the record has no person for
                found.append(
                    Presence(
                        person,
                        label,
                        None,
                        NOTE,
                        CONFIRMED,
                        "note",
                        f"note says with {name}",
                        str(line["id"]),
                    )
                )
    return found
