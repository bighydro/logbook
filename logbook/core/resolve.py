"""Names for refs, from the record's own resolution lines (RFC 0006).

A raw line carries what its source gave — an email address, a phone number — and never a name.
The name is a separate resolution line, and the log is the registry: read every resolution, drop
the retracted ones and the ones a later resolution `supersedes`, and for each ref the last one
standing decides. A line may instead say that its ref is an alias of another ref (`alias_of`): the
reader follows it to that ref's own last line, at most `MAX_HOPS` hops, stopping on a cycle, and the
line it stops on decides. A reader that wants "Ola Nordmann" instead of "+4790000001" joins here.
Nothing is written and nothing outside the record is consulted."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, NamedTuple

from .chain import Line
from .store import RETRACTION, retractions

if TYPE_CHECKING:
    from .index import Index
    from .store import Logbook

RESOLUTION = "resolution"
MAX_HOPS = 4  # RFC 0006: a reader follows `alias_of` at most this many times
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

    The last line standing for each ref (`standing`), followed through its aliases (`walk`),
    decides: its `label`, or no entry when it has none."""
    last = standing(lines)
    found: dict[Ref, str] = {}
    for ref in last:
        label = walk(ref, last)[-1]["payload"].get("label")
        if isinstance(label, str) and label:
            found[ref] = label
    return found


class Identity(NamedTuple):
    """What a ref resolves to: the entity the deciding line names (its id and type, `person`,
    `place` or `company`), when it names one, and the label it carries."""

    entity: str | None
    type: str | None
    label: str | None


def identities_from(lines: Iterable[Line]) -> dict[Ref, Identity]:
    """(ref.kind, ref.value) → Identity for every ref with a resolution standing. The deciding
    line is the last one of the alias walk (RFC 0006 rule 6): its `entity` when it has one (a walk
    that ends on an alias line names no entity), and its `label` either way, as `labels_from`."""
    last = standing(lines)
    found: dict[Ref, Identity] = {}
    for ref in last:
        payload = walk(ref, last)[-1].get("payload") or {}
        entity = payload.get("entity")
        label = payload.get("label")
        entity_id = entity.get("id") if isinstance(entity, dict) else None
        entity_type = entity.get("type") if isinstance(entity, dict) else None
        found[ref] = Identity(
            entity_id if isinstance(entity_id, str) and entity_id else None,
            entity_type if isinstance(entity_type, str) and entity_type else None,
            label if isinstance(label, str) and label else None,
        )
    return found


def standing(lines: Iterable[Line]) -> dict[Ref, Line]:
    """(ref.kind, ref.value) → the last resolution line standing for it.

    RFC 0006 rule 4: for one ref the last resolution wins, where "last" is chain order (`seq`).
    A retracted resolution (RFC 0003) counts for nothing, including its `supersedes`. A
    resolution that `supersedes` another removes that one from consideration."""
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
    return last


def walk(ref: Ref, last: dict[Ref, Line]) -> list[Line]:
    """The lines a reader passes through resolving `ref`, the deciding one last: its own last line
    standing, then each `alias_of` target's, at most `MAX_HOPS` hops (RFC 0006 rule 6), stopping
    at a line with no `alias_of`, at a ref with no standing line, or at a ref already visited (a
    cycle). Empty when `ref` has no line standing."""
    line = last.get(ref)
    if line is None:
        return []
    path = [line]
    visited = {ref}
    for _ in range(MAX_HOPS):
        target = _ref(line, "alias_of")
        if target is None or target in visited or target not in last:
            break
        visited.add(target)
        line = last[target]
        path.append(line)
    return path


def _ref(line: Line, field: str = "ref") -> Ref | None:
    ref = (line.get("payload") or {}).get(field)
    if not isinstance(ref, dict):
        return None
    kind, value = ref.get("kind"), ref.get("value")
    if not isinstance(kind, str) or not isinstance(value, str):
        return None
    return kind, value
