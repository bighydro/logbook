"""Names and refs to people: a ref or a spoken name to the person the record's resolution lines
give it (RFC 0006), and the normal form of a name. `resolve_ref` and `by_name` are the two lookups
the other readers of people share."""

from __future__ import annotations

from collections.abc import Mapping

from ..resolve import Identity, Ref
from .model import PERSON_TYPES


def _normal(name: str) -> str:
    return " ".join(name.split()).casefold()


def _ref(value: object) -> Ref | None:
    if not isinstance(value, dict):
        return None
    kind, ref_value = value.get("kind"), value.get("value")
    if not isinstance(kind, str) or not isinstance(ref_value, str) or not ref_value:
        return None
    return kind, ref_value


def _resolve(ref: Ref, identities: Mapping[Ref, Identity]) -> tuple[str | None, str | None]:
    who = identities.get(ref)
    if who is None or who.type not in PERSON_TYPES:
        return None, None
    return who.entity, who.label


def _by_name(name: str, identities: Mapping[Ref, Identity]) -> tuple[str | None, str | None]:
    """The person whose label is `name` (case aside), else the one person whose label's first
    word is `name`'s first word; None when none or several."""
    wanted = " ".join(name.split()).casefold()
    labels: dict[str, str] = {}  # entity → label
    for who in identities.values():
        if who.entity and who.label and who.type in PERSON_TYPES:
            labels.setdefault(who.entity, who.label)
    exact = {
        entity: label for entity, label in labels.items() if " ".join(label.split()).casefold() == wanted
    }
    if len(exact) == 1:
        return next(iter(exact.items()))
    first = wanted.split(" ")[0]
    loose = {entity: label for entity, label in labels.items() if label.split()[0].casefold() == first}
    if len(loose) == 1:
        return next(iter(loose.items()))
    return None, None


# The two lookups other readers of people share (`people`): a ref to the person it resolves to, and a
# spoken or written name to the person whose label it is.
resolve_ref = _resolve
by_name = _by_name
