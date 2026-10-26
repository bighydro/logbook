"""The doors' header on a page `logbook serve` renders (`logbook/contrib/doors.py`, `header` and
`header_style`): on every page, with its one form (Ask, a GET to `/search`), and the stylesheet with the
faces the Library serves itself. A test that holds a page to having no form, or no `url()` in its style,
reads the page without them (`without_shell`), after checking they are exactly the doors' and nothing
else: what the page itself carries is held as strictly as before the header."""

from __future__ import annotations

import re
from collections.abc import Callable

from logbook.contrib import doors

HEADER = re.compile(r'<header class="doors">.*?</header>\n', re.S)


class _Site:
    """What `doors.header` reads of a Site: how it writes a link and whether it is static."""

    def __init__(self, href: Callable[[str], str | None], static: bool) -> None:
        self.href, self.static = href, static


def header_of(page: str) -> str:
    """The page's header, which must be there, once."""
    found = HEADER.findall(page)
    assert len(found) == 1, f"{len(found)} headers"
    return found[0]


def without_shell(
    page: str, href: Callable[[str], str | None] = lambda path: path, static: bool = False
) -> str:
    """`page` less the doors' header and the header's stylesheet, each checked to be exactly the doors'
    (the header as `doors.header` writes it: the door marked aside)."""
    header = header_of(page)
    unmarked = header.replace(' aria-current="page"', "")
    assert unmarked == doors.header(_Site(href, static), ""), header[:200]  # type: ignore[arg-type]
    style = doors.header_style(fonts=not static)
    assert page.count(style) == 1, "the header's stylesheet, once"
    return page.replace(header, "", 1).replace(style, "", 1)
