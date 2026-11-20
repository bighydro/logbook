"""What a reader sees of a page `logbook serve` serves, read from its HTML alone (`html.parser`, no
browser): the page's text, every disclosure's among it, and what its fields show (a text field's
value, a textarea's words, an empty field's placeholder); never a tag, an attribute (a link's target,
a `title`), a hidden field's value, the stylesheet or the script. A block, a cell or a field is a
word apart from the next; the inline elements of a line run on, as a browser shows them.

A check that a page never says a number reads this, as a word (`says`), and not the page's source
(or, for a value the page must not carry anywhere, the source as whole values, `holds`):
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


# a line id (uuid7, or a fixture's uuid4), whole or cut short after its version group, set aside before
# a word is looked for: its groups of four stand between hyphens, as a year does in a date, and are random
# (`019cadd3-2055-7dcd-…` says no year). Only that shape, standing alone: eight digits and four
# (`22334455-1234`, `20260615-0930`) are a phone number or a time, and are read.
LINE_ID = re.compile(
    r"(?<![0-9A-Za-z])[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[47][0-9A-Fa-f]{3}"
    r"(?:-[0-9A-Fa-f]{4}(?:-[0-9A-Fa-f]{1,12})?)?(?![0-9A-Za-z])"
)


def whole(text: str, word: str) -> bool:
    """Whether `text` holds `word` as a value of its own: not inside a longer run of letters and digits
    (a hash, a digest, a token, an id's tail: `3c4aea205561` holds no 2055) nor inside a line id. Any
    other mark beside it is an edge: a space, a hyphen, a slash, an underscore, a quote, `=`, `(`. A
    compact stamp counts too: `20550301T0900Z` (a stay's or a crossing's id) holds 2055."""
    rest = LINE_ID.sub(" ", text)
    found = rf"(?<![0-9A-Za-z]){re.escape(word)}(?:(?![0-9A-Za-z])|(?=\d{{4}}T\d{{4}}))"
    return re.search(found, rest) is not None


def says(page: str, word: str) -> bool:
    """Whether a reader sees `word` on the page as a word of its own (`whole`, over `seen`): not inside
    a longer run of letters and digits, as three digits are in a line id's tail or the head's hash."""
    return whole(seen(page), word)


def holds(page: str, word: str) -> bool:
    """Whether the page's source holds `word` as a value of its own (`whole`) anywhere: its text, a
    link's target, an attribute, a field, the script. The check for a value the page must not carry at
    all, read or not, without the luck of a random id that happens to spell it."""
    return whole(page, word)
