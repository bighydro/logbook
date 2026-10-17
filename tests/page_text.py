"""What a reader sees of a page `logbook serve` serves, read from its HTML alone (`html.parser`, no
browser): the page's text, every disclosure's among it, and what its fields show (a text field's
value, a textarea's words, an empty field's placeholder); never a tag, an attribute (a link's target,
a `title`), a hidden field's value, the stylesheet or the script. A block, a cell or a field is a
word apart from the next; the inline elements of a line run on, as a browser shows them.

A check that a page never says a number reads this, as a word (`says`), and not the page's source:
the line ids in a kept form's hidden fields and in the evidence rows' `title`s, the tail of one a row
shows (`…aa2025cc`), and the record's head in the footer are random hex, and hold any three digits now
and then. The busy test of #315 failed a right page that way, on "503" in a hidden field's id."""

from __future__ import annotations

import re
from html.parser import HTMLParser

UNSEEN = frozenset({"style", "script"})  # their content is no text on the page
NOT_SHOWN = frozenset({"hidden", "checkbox", "radio", "file", "image", "password"})  # inputs, value unseen
# the elements a line of text runs on through; any other is a word apart from what is beside it
INLINE = frozenset(
    {"a", "abbr", "b", "bdi", "bdo", "cite", "code", "data", "del", "dfn", "em", "i", "ins", "kbd", "label"}
    | {"mark", "q", "s", "samp", "small", "span", "strong", "sub", "sup", "time", "u", "var", "wbr"}
)


class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.unseen = 0  # inside a style or a script

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in UNSEEN:
            self.unseen += 1
        elif self.unseen:
            return
        elif tag not in INLINE:
            self.parts.append("\n")
        a = {k: v or "" for k, v in attrs}
        if tag == "input" and a.get("type", "text").lower() not in NOT_SHOWN:
            self.parts.append((a.get("value") or a.get("placeholder", "")) + "\n")
        elif tag == "textarea":  # its hint, shown while it is empty; its words are its text
            self.parts.append(a.get("placeholder", "") + "\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in UNSEEN:
            self.unseen = max(0, self.unseen - 1)
        elif not self.unseen and tag not in INLINE:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.unseen:
            self.parts.append(data)


def seen(page: str) -> str:
    """The page's text as a reader sees it: `page` may be a whole document or a part of one."""
    reader = _Reader()
    reader.feed(page)
    reader.close()
    return "".join(reader.parts)


def says(page: str, word: str) -> bool:
    """Whether a reader sees `word` on the page as a word of its own: not inside a longer run of
    letters and digits, as three digits are in a line id's tail or the head's hash."""
    return re.search(rf"(?<!\w){re.escape(word)}(?!\w)", seen(page)) is not None
