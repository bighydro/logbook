"""The Library's shell on a page `logbook serve` renders (`logbook/contrib/library_shell.py`): the header
on every page, with its one form (Ask, a GET to `/search`), and the stylesheet with the fonts the
Library serves itself. A test that holds a page to having no form, or no `url()` in its style, reads
the page without them (`without_shell`), after checking they are exactly the shell's and nothing
else: what the page itself carries is held as strictly as before the doors."""

from __future__ import annotations

import re
from collections.abc import Callable

from logbook.contrib import library_shell

HEADER = re.compile(r'<header class="shell">.*?</header>\n', re.S)


def header_of(page: str) -> str:
    """The page's header, which must be there, once."""
    found = HEADER.findall(page)
    assert len(found) == 1, f"{len(found)} headers"
    return found[0]


def without_shell(page: str, href: Callable[[str], str | None] = lambda path: path, ask: bool = True) -> str:
    """`page` less the shell's header and the shell's stylesheet, each checked to be exactly the shell's
    (the header as the shell writes it for some page: the door marked aside)."""
    header = header_of(page)
    unmarked = header.replace(' aria-current="page"', "")
    assert unmarked == library_shell.header_html("", href, ask), header[:200]
    assert page.count(library_shell.STYLE) == 1, "the shell's stylesheet, once"
    return page.replace(header, "", 1).replace(library_shell.STYLE, "", 1)
