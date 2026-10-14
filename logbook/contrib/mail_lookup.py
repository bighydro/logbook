"""Which mail the record holds already, by Message-ID, whichever road wrote it: the `held` that `add mail`
(the Takeout mbox), `sync mail` (IMAP) and `sync gmail` (the Gmail API) give their source, so that one
email is one line (RFC 0015, the amendment of 2026-10-14).

Every road writes `source` `mail`, keyed `<account>:<Message-ID>` when it knows the mailbox and
`<Message-ID>` when it does not (an mbox imported without `--account`), the Message-ID as the header
spells it; `payload.message_id` carries it normalised (`mail.normalise_id`). The store refuses only the
very same (source, raw_id). This asks the record, for a batch of messages (`mail.Asked`), in two steps,
both through the index's public readers — `core/index.py` is not changed and no table is added:

1. **The keys a line of the message can carry**: the Message-ID as spelled and normalised, under the
   source's own account and bare; for a source that names no mailbox, under each of the owner's
   addresses (`owner_emails`) too. One `Index.existing` for the batch: the (source, raw_id) index
   answers, a sealed line's blinded raw_id included (RFC 0029 §8).
2. **The lines of the message's days**, for a message already read (its `at` known) that no key found:
   the mail lines whose local day is within two days of its instant (`Index.of_source`, opened when
   sealed and the identity is here), compared by normalised Message-ID. A spelling the first step did
   not guess, or an account no address names, is still found. Each day is read once per run, the last
   DAYS_KEPT kept.

**Whose line holds it** is the mailbox's question (RFC 0015 rule 1: a message in two mailboxes is two
lines). A line of the source's own account, or one written without an account, holds the message; a
line of another account does not, unless the source itself names no mailbox (an mbox imported without
`--account`), which cannot say it is a second one. A message without a Message-ID is never asked: its
line is keyed by its own bytes, as before.

Nothing is written, and only the record's own lines are read. A record that seals, read without its
identity, answers nothing here (the index holds no raw_id of a sealed line then, and no payload opens):
the store's (source, raw_id) stays the guard, as it was."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from .adapters import mail
from .adapters.mail import Asked, Holder

if TYPE_CHECKING:
    from ..core.index import Index
    from ..core.store import Logbook

SOURCE = mail.NAME  # the `source` every mail road writes (gmail's SOURCE is the same)
KIND = mail.KIND
DAYS_AROUND = 2  # local days either side of a message's UTC date whose lines step 2 reads
DAYS_KEPT = 64  # days step 2 keeps read, newest asked last

# per normalised Message-ID, the (raw_id, account) of every mail line of a day that carries it
Day = dict[str, list[tuple[str, str | None]]]


class Lookup:
    """The `held` callable for one run of a mail source over the record `lb`."""

    def __init__(self, lb: Logbook) -> None:
        self.lb = lb
        self.owners = tuple(
            dict.fromkeys(str(e).strip().lower() for e in lb.meta.get("owner_emails") or [] if str(e).strip())
        )
        self.days: OrderedDict[str, Day] = OrderedDict()

    def __call__(self, asked: Sequence[Asked]) -> list[Holder | None]:
        """The holder of each message asked about, in order; None where the record holds none."""
        found: list[Holder | None] = [None] * len(asked)
        with self.lb.index() as idx:
            candidates = [self._keys(q) for q in asked]
            held = idx.existing({key for keys in candidates for key, _holder in keys})
            for n, keys in enumerate(candidates):
                found[n] = next((holder for key, holder in keys if key in held), None)
            for n, q in enumerate(asked):
                if found[n] is None and q.at is not None:
                    found[n] = self._by_day(idx, q)
        return found

    def _keys(self, q: Asked) -> list[tuple[tuple[str, str], Holder]]:
        """The (source, raw_id) keys a line holding this message may carry, the one the store refuses
        first, then the same mailbox, then a line with no mailbox, then (for a source that names no
        mailbox) each of the owner's addresses."""
        keys: dict[tuple[str, str], Holder] = {(SOURCE, q.raw_id): Holder(own=True, account=q.account)}
        for spelling in dict.fromkeys((q.spelled, q.message_id)):
            if q.account:
                keys.setdefault((SOURCE, f"{q.account}:{spelling}"), Holder(own=False, account=q.account))
            keys.setdefault((SOURCE, spelling), Holder(own=False, account=None))
        if not q.account:
            for owner in self.owners:
                for spelling in dict.fromkeys((q.spelled, q.message_id)):
                    keys.setdefault((SOURCE, f"{owner}:{spelling}"), Holder(own=False, account=owner))
        return list(keys.items())

    def _by_day(self, idx: Index, q: Asked) -> Holder | None:
        """Step 2: the holder among the mail lines of the message's days, by normalised Message-ID."""
        assert q.at is not None
        date = datetime.fromisoformat(q.at.replace("Z", "+00:00")).date()
        lines = [
            entry
            for offset in range(-DAYS_AROUND, DAYS_AROUND + 1)
            for entry in self._day(idx, (date + timedelta(days=offset)).isoformat()).get(q.message_id, [])
        ]
        best: Holder | None = None
        for raw_id, account in lines:
            if raw_id == q.raw_id:
                return Holder(own=True, account=q.account)
            if q.account is not None and account is not None and account != q.account:
                continue  # another mailbox's copy: a line of its own (RFC 0015 rule 1)
            holder = Holder(own=False, account=account)
            if best is None or (holder.account == q.account and best.account != q.account):
                best = holder
        return best

    def _day(self, idx: Index, day: str) -> Day:
        """The mail lines of one local day, by normalised Message-ID, read once and kept."""
        if day in self.days:
            self.days.move_to_end(day)
            return self.days[day]
        found: Day = {}
        for line in idx.of_source(KIND, SOURCE, day, day):
            payload = line.get("payload") or {}
            normal = mail.normalise_id(_text(payload.get("message_id")))
            raw_id = _text(payload.get("raw_id"))
            if normal is None or raw_id is None:
                continue  # no Message-ID, or a sealed line this run cannot open
            account = _text(payload.get("account"))
            found.setdefault(normal, []).append((raw_id, account.lower() if account else None))
        self.days[day] = found
        while len(self.days) > DAYS_KEPT:
            self.days.popitem(last=False)
        return found


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
