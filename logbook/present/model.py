"""What the with module says: a `Presence` (one piece of evidence that puts one person at a stay),
a `Companion` (the evidence merged per person), the two statuses, the sources in the order a Day
lists them, the kinds they read and the confidence each source gives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..resolve import Ref

CONFIRMED, PROPOSED = "confirmed", "proposed"
SOURCES = ("circle", "calendar", "transcript", "note", "photo")
EVIDENCE_KINDS = ("event", "transcript", "note", "photo")  # the kinds the sources above read
ACCEPTED, TENTATIVE, TRANSCRIPT, NOTE, PHOTO, ALL_DAY = 0.8, 0.6, 0.9, 1.0, 0.5, 0.3
PERSON_TYPES = (None, "person")


@dataclass(frozen=True)
class Presence:
    """One piece of evidence that one person was present."""

    person: str | None  # the entity id the ref or name resolves to, when it does
    name: str  # the label, else the ref's value or the name as written
    ref: Ref | None  # the source-native ref, when the evidence carried one
    confidence: float
    status: str  # confirmed or proposed
    source: str  # calendar, transcript, note, photo (circle: not yet)
    reason: str
    line: str  # the evidence line's id

    def to_json(self) -> dict[str, Any]:
        return {
            "person": self.person,
            "name": self.name,
            "ref": None if self.ref is None else {"kind": self.ref[0], "value": self.ref[1]},
            "confidence": self.confidence,
            "status": self.status,
            "source": self.source,
            "reason": self.reason,
            "line": self.line,
        }


@dataclass(frozen=True)
class Companion:
    """One person at a stay, every piece of evidence merged: the best status and confidence,
    the sources and reasons in evidence order, the lines."""

    person: str | None
    name: str
    status: str
    confidence: float
    sources: tuple[str, ...]
    reasons: tuple[str, ...]
    lines: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "person": self.person,
            "name": self.name,
            "status": self.status,
            "confidence": self.confidence,
            "sources": list(self.sources),
            "reasons": list(self.reasons),
            "lines": list(self.lines),
        }
