"""A re-sign keeps your confirmations (RFC 0034 amendment 4, the owner's v1 choice of 18 October
2026). A day signed again without `--confirm` keeps what its standing signature said, as `day reflect
--sign` and the Day page's "Sign again" always have (`reflect.signature`, the one rule): the lines it
confirmed that are still on the page and not retracted, its dispositions on them, and its note; a
line added to the day since stays unconfirmed until the owner confirms it. What the owner types wins:
a disposition flag on a line replaces the one kept for it, `--note` the note kept, and `--confirm`
(ids, `all` for the whole page, or `none`) is a fresh reading that keeps nothing. A day not signed
yet is signed as before: without `--confirm`, the whole page.

`day sign` and the MCP tool `sign_day` both sign through here and then `signing.sign`, under the
writer lock their callers hold, so the standing signature read is the one the new line supersedes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..core import signing
from ..core.store import Logbook
from . import reflect

EVERY = "all"  # `--confirm all`: every line on the page not retracted, a day signed before too


@dataclass(frozen=True)
class Again:
    """What `signing.sign` is given, and what was kept from the standing signature for the owner to
    read (`reflect.signature`'s sentence; None when nothing was kept)."""

    confirm: list[str] | None
    dispositions: dict[str, list[str]]
    note: str | None
    kept: str | None = None


def confirmation(entries: Sequence[str] | None, disposed: bool) -> tuple[list[str] | None, bool]:
    """The confirmation as typed (`--confirm ID,ID|all|none`, or `sign_day`'s `confirm`): what
    `signing.sign` takes (`signing.confirmation`) and whether the standing signature's confirmations
    are kept, which they are only when nothing was typed. `all` is the whole page, as a first
    signature without `--confirm` is, and goes alone, as `none` does."""
    if entries is None:
        return None, True
    if any(entry.strip().lower() == EVERY for entry in entries):
        if len(entries) > 1:
            raise signing.SignError(
                f"--confirm {EVERY} goes alone: it confirms every line on the page, so no id beside it"
            )
        return None, False
    return signing.confirmation(entries, disposed), False


def again(
    lb: Logbook,
    day: str,
    confirm: list[str] | None,
    keep: bool,
    dispositions: Mapping[str, Sequence[str]],
    note: str | None,
) -> Again:
    """The arguments of the signature of `day`, the standing signature's kept when `keep` (nothing
    was typed for `--confirm`) and the day has one; else the arguments as given. Read under the
    writer lock the caller holds."""
    given = {word: list(entries) for word, entries in dispositions.items()}
    if not keep:
        return Again(confirm, given, note)
    lines, retracted = reflect.day_lines(lb, day)
    with lb.index() as idx:
        earlier = signing.signature_of(idx, day, str(lb.meta["owner_id"]))
    if earlier is None:
        return Again(None, given, note)
    kept = reflect.signature(earlier, reflect.on_page(lines, retracted), [], [])
    by_seq = {int(line["seq"]): str(line["id"]) for line in lines}
    typed = [entry.strip() for entries in given.values() for entry in entries]
    named = {by_seq.get(int(entry), entry) if entry.isdigit() else entry for entry in typed}  # as `sign` does
    merged: dict[str, list[str]] = {}
    for word in signing.DISPOSITIONS:
        entries = [id_ for id_ in kept.dispositions.get(word, []) if id_ not in named] + given.get(word, [])
        if entries:
            merged[word] = entries
    # the lines typed beside the kept ones, so that a standing signature that confirmed nothing and a
    # disposition typed now confirm that line, never read as `--confirm none` beside a disposition
    chosen = [*(kept.confirm or []), *typed]
    return Again(chosen, merged, note if note is not None else kept.note, kept.kept)
