"""The guard for the owner's rule, no number beside a person's name in anything a reader prints (VISION:
no metrics near people; RFC 0043 §2.5), shared by every test that reads a page or a reader's text.

`seen` turns a page into the text a person reads: style and script dropped, the words of every
attribute that carries them (`title`, `aria-label`, `alt`, `data-*` and the rest, `WORDS`) a block of
their own, a block's text (`BLOCK`) joined across its newlines, every block's end a break the guard
never crosses. A table row is one block: its cells read together, as a person reads a row.

`beside` finds, in that text, a digit and a name with nothing but a separator between them
(`SEPARATOR`, a possessive `'s` included), or `N <word> with NAME`, matched case-insensitively on
whole words. Clock times are numbers here, as the Day-page guard reads them; an ISO date, an ISO week
and a row's link to its line as written (`#SEQ`, an address) are not."""

from __future__ import annotations

import html
import re
from collections.abc import Iterable

from logbook.core import people
from logbook.core.store import Logbook

EN_DASH, RSQUO = "\u2013", "\u2019"
# what may stand between a name and a number and still be beside it
SEPARATOR = rf"[\s(:×x#·,\-{EN_DASH}—/|;=•.'{RSQUO}]*"
BREAK = "¶"  # a block's end: never crossed
BLOCK = re.compile(
    r"</?(?:li|ol|ul|dl|section|article|aside|main|header|footer|nav|h[1-6]|table|thead|tbody|tr|blockquote"
    r"|form|figure|svg|br|hr|title|option|select|textarea|button|body|html)\b[^>]*>",
    re.I,
)  # a list's item, a row, a section: what a person reads as one; its paragraphs, cells and spans together
WORDS = re.compile(
    r"""\s(?:title|aria-[\w-]+|alt|placeholder|label|summary|content|value|data-[\w-]+)\s*=\s*"""
    r"""(?:"([^"]*)"|'([^']*)')""",
    re.I,
)  # every attribute that carries words a person or a reader can see
RAW = re.compile(r'<a class="raw"[^>]*>#\d+</a>')  # a row's link to its line as written: an address
NOT_A_NUMBER = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T[\d:]+(?:Z|[+-]\d{2}:\d{2})?)?\b|\b\d{4}-W\d{2}\b")


def seen(page: str) -> str:
    """`page` as the text a person reads, its blocks apart (`BREAK`), its attributes' words read."""
    page = RAW.sub(" ", page)
    page = re.sub(r"<(style|script)\b.*?</\1>", "", page, flags=re.S | re.I)

    def tag(found: re.Match[str]) -> str:
        said = [a or b for a, b in WORDS.findall(found.group(0))]
        return "".join(f"{BREAK}{words}{BREAK}" for words in said if words) + (
            BREAK if BLOCK.fullmatch(found.group(0)) else " "
        )

    return html.unescape(re.sub(r"<[^>]+>", tag, page)) if "<" in page else page


def names_of(lb: Logbook) -> list[str]:
    """Every canonical, first and last name in the record's directory, the owner's never."""
    found: set[str] = set()
    for person in people.directory(lb).known.values():
        words = person.name.split()
        found |= {person.name, *({words[0], words[-1]} if words else ())}
    return sorted(n for n in found if n.strip())


def _guard(names: Iterable[str]) -> re.Pattern[str]:
    alt = "|".join(re.escape(n) for n in sorted(set(names), key=len, reverse=True))
    name = rf"(?<!\w)(?:{alt})(?!\w)"
    return re.compile(
        rf"(\d{SEPARATOR}{name})|({name}(?:['{RSQUO}]s)?\??{SEPARATOR}\d)"
        rf"|(\d[\d,.]*\s+[^\W\d_]+\s+with\s+{name})",
        re.I,
    )


def beside(texts: str | Iterable[str], names: Iterable[str], *, html_page: bool | None = None) -> list[str]:
    """Every block of `texts` (a page, seen; a reader's text, line by line) where a number stands beside
    one of `names`."""
    guard = _guard(names)
    found: list[str] = []
    for text in [texts] if isinstance(texts, str) else texts:
        page = ("<" in text and ">" in text) if html_page is None else html_page
        blocks = seen(text).replace("\n", " ").split(BREAK) if page else text.splitlines()
        for block in blocks:
            if guard.search(NOT_A_NUMBER.sub(" ", block)):
                found.append(" ".join(block.split()))
    return found
