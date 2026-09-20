"""Names for refs, from the record's own resolution lines (RFC 0006).

A raw line carries what its source gave — an email address, a phone number — and never a name.
The name is a separate resolution line, and the log is the registry: read every resolution, drop
the retracted ones and the ones a later resolution `supersedes`, and for each ref the last one
standing decides. A reader that wants "Ola Nordmann" instead of "+4790000001" joins here. Nothing
is written and nothing outside the record is consulted."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from .chain import Line
from .store import RETRACTION, retractions

if TYPE_CHECKING:
    from .index import Index
    from .store import Logbook

RESOLUTION = "resolution"
Ref = tuple[str, str]  # (ref.kind, ref.value), as the raw lines carry it


def labels(lb: Logbook, idx: Index | None = None) -> dict[Ref, str]:
    """(ref.kind, ref.value) → label for every ref the record resolves. Reads the resolution and
    retraction lines through the index (the caller's open one, or a fresh one that is closed
    before returning)."""
    if idx is not None:
        return labels_from([*idx.retractions(), *idx.resolutions()])
    with lb.index() as own:
        return labels_from([*own.retractions(), *own.resolutions()])


def labels_from(lines: Iterable[Line]) -> dict[Ref, str]:
    """The pure function: resolution and retraction lines, in any order, to the label map.

    RFC 0006 rule 4: for one ref the last resolution wins, where "last" is chain order (`seq`).
    A retracted resolution (RFC 0003) counts for nothing, including its `supersedes`. A
    resolution that `supersedes` another removes that one from consideration. The last one
    standing decides: its `label`, or no entry when it has none."""
    lines = sorted(lines, key=lambda line: int(line["seq"]))
    retracted = retractions(line for line in lines if line.get("kind") == RETRACTION)
    live = [line for line in lines if line.get("kind") == RESOLUTION and str(line["id"]) not in retracted]
    superseded = {
        superseded
        for line in live
        if isinstance(superseded := (line.get("payload") or {}).get("supersedes"), str)
    }
    last: dict[Ref, Line] = {}
    for line in live:
        if str(line["id"]) in superseded:
            continue
        ref = _ref(line)
        if ref is not None:
            last[ref] = line
    found: dict[Ref, str] = {}
    for ref, line in last.items():
        label = line["payload"].get("label")
        if isinstance(label, str) and label:
            found[ref] = label
    return found


def _ref(line: Line) -> Ref | None:
    ref = (line.get("payload") or {}).get("ref")
    if not isinstance(ref, dict):
        return None
    kind, value = ref.get("kind"), ref.get("value")
    if not isinstance(kind, str) or not isinstance(value, str):
        return None
    return kind, value
