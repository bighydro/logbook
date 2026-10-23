"""`logbook review receipts` (RFC 0043 §12, the money bridge): the receipt mails proposed as payments,
and the owner's say.

The sitting is `review KIND`'s (`logbook.commands.review.sitting`): the queue listed, as JSON or
printed; the numbers told checked, every one before the first line, then written and said. `--accept
N,N` writes each as one tier-3 `transaction/v1` line, `--reject N` one tier-3 `not-a-payment` line
(`receipt-review/v1`); a second of one payment in a batch is refused and counted; a
receipt the record already holds is never numbered. A receipt is accepted by its number, so `--name`
and `--all-above` are refused. `--since D` is the first day of mail read. The reading, the rules and
the writers are `logbook.contrib.receipts`; nothing here writes a line."""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from typing import Any

from ..core.store import Logbook
from .review import Queue

FLAGS = (("--since", "since"),)


class ReceiptQueue(Queue):
    """The receipts' queue as `review` drives it."""

    kind = "receipts"

    def __init__(self) -> None:
        from ..contrib import receipts

        self.module = receipts
        self.error = receipts.ReviewError

    def check(self, a: argparse.Namespace) -> None:
        if getattr(a, "name", None):
            raise self.error("--name goes with a new org or person; a receipt is accepted by its number")
        if getattr(a, "all_above", None) is not None:
            raise self.error("--all-above: a receipt is accepted by its number, each one you have read")

    def read(self, lb: Logbook, a: argparse.Namespace) -> Any:
        return self.module.read(lb, getattr(a, "since", None))

    def numbers(self, text: Sequence[str] | None) -> list[int]:
        return self.module.numbers(text)

    def pick(self, report: Any, wanted: Sequence[int]) -> list[Any]:
        return self.module.pick(report, wanted)

    def write(
        self, lb: Logbook, report: Any, chosen: Sequence[tuple[Any, str | None]], rejected: Sequence[Any]
    ) -> list[Any]:
        return [
            *self.module.accept(lb, report, [c for c, _ in chosen]),
            *self.module.reject(lb, report, rejected),
        ]

    def rows(self, report: Any, shown: Sequence[Any], a: argparse.Namespace) -> Iterable[str]:
        return self.module.rows(report)

    def written_rows(self, written: Sequence[Any]) -> Iterable[str]:
        return self.module.written_rows(written)


def receipts_arguments(s: argparse.ArgumentParser) -> None:
    """The option `review receipts` adds to `review`'s."""
    g = s.add_argument_group("receipts", "with `review receipts` (RFC 0043 §12, the money bridge)")
    g.add_argument(
        "--since",
        metavar="YYYY-MM-DD",
        help="the first day of mail read for receipts (default 90 days ago)",
    )


def refuse_flags(a: argparse.Namespace) -> list[str]:
    """The receipts' options given to another kind."""
    return [flag for flag, dest in FLAGS if getattr(a, dest, None) not in (None, False)]
