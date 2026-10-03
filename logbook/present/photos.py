"""The photo source: a face the library tagged in a `photo/v1` taken inside the stay."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from ..chain import Line
from ..places import Place
from ..resolve import Identity, Ref
from ..stays import Segment
from .evidence import _inside
from .model import PHOTO, PROPOSED, Presence
from .names import _resolve


def from_photos(
    stay: Segment, lines: Iterable[Line], identities: Mapping[Ref, Identity], places: Sequence[Place] = ()
) -> list[Presence]:
    found = []
    for line in lines:
        if line.get("kind") != "photo" or not _inside(stay, line):
            continue
        payload = line.get("payload") or {}
        library = str(payload.get("library") or line.get("source") or "")
        file_name = str(payload.get("file_name") or payload.get("asset_id") or "a photo")
        people = payload.get("people")
        for person_id in people if isinstance(people, list) else []:
            if not isinstance(person_id, str) or not person_id:
                continue
            ref: Ref = ("provider_id", f"{library}:{person_id}")
            person, label = _resolve(ref, identities)
            found.append(
                Presence(
                    person,
                    label or ref[1],
                    ref,
                    PHOTO,
                    PROPOSED,
                    "photo",
                    f"face in {file_name}",
                    str(line["id"]),
                )
            )
    return found
