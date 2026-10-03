"""The owner's own identities, so they are never their own company."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ..resolve import Identity, Ref
from .model import PERSON_TYPES, Presence
from .names import _normal


@dataclass(frozen=True)
class Owner:
    """The owner's own identities, so they are never their own company: the entity ids the record
    resolves them to, the refs (emails, phones, provider ids) that resolve to those, and every name
    those resolutions and `policy/owner.json` spell them by, normalised (`_normal`)."""

    entities: frozenset[str]
    refs: frozenset[Ref]
    names: frozenset[str]

    def holds(self, p: Presence) -> bool:
        return (
            (p.person is not None and p.person in self.entities)
            or (p.ref is not None and p.ref in self.refs)
            or _normal(p.name) in self.names
        )


def owner_of(
    owner_id: str,
    owner_emails: Iterable[str],
    aliases: Mapping[str, Iterable[str]],
    identities: Mapping[Ref, Identity],
) -> Owner:
    """`Owner` from `logbook.json` (`owner_id`, `owner_emails`), `policy/owner.json` (`aliases`:
    `names`, `emails`, `phones`) and the resolution lines: a ref that resolves to an owner entity
    is the owner's, an owner ref's entity is the owner, to a fixpoint; the names are the aliases'
    and every label an owner ref resolves to."""
    entities = {owner_id}
    refs: set[Ref] = {("email", _normal(e)) for e in owner_emails if e.strip()}
    refs |= {("email", _normal(e)) for e in aliases.get("emails", ()) if e.strip()}
    refs |= {("phone", p.strip()) for p in aliases.get("phones", ()) if p.strip()}
    names = {_normal(n) for n in aliases.get("names", ()) if n.strip()}
    while True:
        before = (len(entities), len(refs))
        for ref, who in identities.items():
            if who.entity and (who.entity in entities or ref in refs) and who.type in PERSON_TYPES:
                entities.add(who.entity)
                refs.add(ref)
        if before == (len(entities), len(refs)):
            break
    for ref in refs:
        resolved = identities.get(ref)
        if resolved is not None and resolved.label:
            names.add(_normal(resolved.label))
    return Owner(frozenset(entities), frozenset(refs), frozenset(names))
