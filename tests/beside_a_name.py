"""The strong guard of the owner's rule, no number beside a person's name in anything a reader prints
(RFC 0043 §2.5, VISION: no metrics near people), over the demo record's people: a digit, then nothing
but a separator, then a name; or a name, then a separator, then a digit. `rows` reads a reader's text
a line at a time; `page_rows` reads a page as a reader sees it (`page_text`), a row at a time: a list
item or a table row is one row, its blocks and cells run together with a dot between them, so a name
in a row's head and a count in its facts stand beside each other, as they do on the screen; a row
inside a row (an evidence row in a person's row) is a row of its own. A date and a clock time are
numbers too (the owner, 27 October): `Ola Nordmann · 2026-06-08` fails, `Ola Nordmann promised you ·
since 8 June` and `with Ola at 14:00` pass, a word between. A line's address on a page is no number
the reader reads: a row's link to its line as written (`#SEQ`) and the tail of its id (`…aa2025cc`)."""

from __future__ import annotations

import re
from collections.abc import Iterable

import page_text

from logbook.contrib import demo

NAMES = tuple(p.name for p in (demo.OWNER, *demo.PEOPLE))  # every person of the demo record, the owner too
_ALT = "|".join(re.escape(n) for n in NAMES)
GUARD = re.compile(rf"(\d[\s(:×x#·,]*(?:{_ALT}))|((?:{_ALT})\??[\s(:×x#·,]*\d)")
ROW = frozenset({"li", "tr"})  # the elements a page lists one thing in: a row each
DOT = " · "
ADDRESS = re.compile(
    r'<a class="raw"[^>]*>#\d+</a>|<span class="id"[^>]*>[^<]*</span>'
)  # a row's link to its line as written, and the tail of a line's id: addresses, not numbers


def beside(row: str) -> bool:
    """Whether a number stands beside a person's name in `row`."""
    return GUARD.search(row) is not None


def rows(texts: str | Iterable[str]) -> list[str]:
    """Every line of `texts` (a reader's output) where a number stands beside a person's name."""
    found: list[str] = []
    for text in [texts] if isinstance(texts, str) else texts:
        found.extend(line.strip() for line in text.splitlines() if beside(line))
    return found


class _Rows(page_text._Reader):
    """`page_text`'s reader, a list item's or a table row's text kept apart as one row, a row inside a
    row as a row of its own; the text outside every row is a row per block."""

    def __init__(self) -> None:
        super().__init__()
        self.outer: list[list[str]] = []  # the text of the rows around the one being read
        self.done: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ROW and not self.unseen:
            self.outer.append(self.parts)
            self.parts = []
        super().handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        super().handle_endtag(tag)
        if tag in ROW and not self.unseen and self.outer:
            self._row()

    def _row(self) -> None:
        self.done.append(DOT.join(line.strip() for line in "".join(self.parts).splitlines() if line.strip()))
        self.parts = self.outer.pop()
        self.parts.append("\n")

    def close(self) -> None:
        super().close()
        while self.outer:  # a row left open is closed where the page ends
            self._row()
        self.done.extend(line.strip() for line in "".join(self.parts).splitlines() if line.strip())


def page_rows(page: str) -> list[str]:
    """`page` as a reader sees it (`page_text`), a row at a time, the addresses taken out."""
    reader = _Rows()
    reader.feed(ADDRESS.sub(" ", page))
    reader.close()
    return [row for row in reader.done if row]


def page(pages: str | Iterable[str]) -> list[str]:
    """Every row of `pages` where a number stands beside a person's name."""
    found: list[str] = []
    for one in [pages] if isinstance(pages, str) else pages:
        found.extend(row for row in page_rows(one) if beside(row))
    return found
