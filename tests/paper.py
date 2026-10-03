"""The structural check every printed document shares — the paper edition, the poster, the week's
paper: one HTML file that is well formed, carries one inline stylesheet and nothing else, loads
nothing from anywhere and runs nothing. A test feeds it the document and asserts the rest."""

from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Structure(HTMLParser):
    """One document read tag by tag: every element closed in order (the void elements and the
    self-closing SVG ones apart), every id once, every element's attributes kept."""

    def __init__(self) -> None:
        super().__init__()
        self.open: list[str] = []
        self.errors: list[str] = []
        self.ids: set[str] = set()
        self.tags: Counter[str] = Counter()
        self.elements: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        self.tags[tag] += 1
        self.elements.append((tag, found))
        if found.get("id"):
            if found["id"] in self.ids:
                self.errors.append(f"id {found['id']} twice")
            self.ids.add(str(found["id"]))
        if tag not in VOID:
            self.open.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags[tag] += 1
        self.elements.append((tag, dict(attrs)))

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID:
            return
        if not self.open or self.open[-1] != tag:
            self.errors.append(f"</{tag}> closes <{self.open[-1] if self.open else 'nothing'}>")
        else:
            self.open.pop()

    def classes(self, tag: str) -> Counter[str]:
        """How many elements of `tag` carry each class."""
        found: Counter[str] = Counter()
        for name, attrs in self.elements:
            if name == tag:
                for cls in str(attrs.get("class") or "").split():
                    found[cls] += 1
        return found


def structure(page: str, images: bool = False) -> Structure:
    """The document is well formed: every tag closed in order, one stylesheet and nothing else in
    the head, no script, no link, no handler, no href, nothing from the network, no `src` at all
    unless `images` (then only an `img`'s, with an `alt`), the paged-media rules present."""
    assert page.startswith('<!doctype html>\n<html lang="en">') and page.endswith("</html>\n")
    s = Structure()
    s.feed(page)
    s.close()
    assert s.errors == [] and s.open == [], (s.errors, s.open)
    assert s.tags["style"] == 1, "one inline stylesheet"
    assert s.tags["script"] == 0 and s.tags["link"] == 0 and s.tags["iframe"] == 0 and s.tags["object"] == 0
    assert s.tags["title"] == 1 and s.tags["body"] == 1 and s.tags["html"] == 1
    for tag, attrs in s.elements:
        assert "href" not in attrs and "xlink:href" not in attrs, (tag, attrs)
        assert not any(k.startswith("on") for k in attrs), (tag, attrs)
        if "src" in attrs:
            assert images and tag == "img", "nothing is loaded"
            assert not str(attrs["src"]).startswith(("http:", "https:", "//")), attrs["src"]
        if tag == "img":
            assert "alt" in attrs
    assert "http://" not in page and "https://" not in page and "//" not in page.split("<body>")[1]
    assert "@import" not in page and "url(" not in page and "<link" not in page and "@font-face" not in page
    assert "@page" in page
    return s
