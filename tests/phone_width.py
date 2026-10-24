"""How wide a page of `logbook serve` is on a phone, read from the page alone: its HTML and the
stylesheet in its `<style>`, no browser. The page is parsed (`html.parser`) with every disclosure
open, and its rules are applied as a phone `PHONE_PX` wide applies them: a browser's own defaults
(`DEFAULTS`), then the page's rules and every `@media` block whose condition holds at that width, by
origin, importance, specificity and order. Each element's narrowest width is then worked out from
the bottom up, as a browser's min-content width is: what it fixes of its own (a `width`, `min-width`
or flex basis, a `width` attribute, a form control's or an image's default width), the fixed and
content-sized columns of a grid and its gaps, the cells of a table's widest row, the items of a flex
row that does not wrap, side by side (a flex column's that does not wrap, one under another), and
the longest run of text that may not break (`white-space: nowrap`, or a word that no `overflow-wrap`
breaks) at `CHAR_EM` a character; plus its horizontal margins, borders and padding. A percentage is
of the column its container leaves. Every estimate errs wide.

`problems` names every element that, with the frames around it, needs more than the column, every
image and `pre` without a `max-width` that keeps it inside, and a stylesheet without a phone
breakpoint (`phone_breakpoints`). A selector, a media query or a value the check cannot read is an
error, never a pass."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser

PHONE_PX = 400.0  # the column: a phone held upright
DESKTOP_PX = 1280.0  # a window a phone breakpoint does not hold in
ROOT_PX = 16.0  # 1rem and the root's font size: the browser's default, which the stylesheet keeps
CHAR_EM = 0.6  # a character at its widest, in em: above system-ui's letters and digits on average
CONTROL_CHARS = 20  # a text field's default width in characters (HTML `size`, `cols`)
REPLACED_PX = 300.0  # an image or a canvas that names no width: the browser's default
IMAGES = frozenset({"img", "svg", "canvas", "video", "picture", "iframe", "object", "embed"})
OPAQUE = IMAGES | {"textarea", "select"}  # what is inside is not laid out as boxes on the page
VOID = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}
)
STATES = frozenset(
    {"hover", "focus", "focus-visible", "focus-within", "active", "visited", "link", "target", "checked"}
)  # a rule under one may hold on a phone, so it counts
PSEUDO_ELEMENTS = frozenset({"before", "after", "marker", "placeholder", "first-line", "first-letter"})
WORD_BREAKS = frozenset({"break-all", "break-word"})  # a `word-break` that breaks a long word
SCROLLS = frozenset({"auto", "scroll", "hidden", "clip"})  # an overflow that keeps the content inside
NO_WIDTH = frozenset(
    {"auto", "none", "normal", "initial", "inherit", "unset", "max-content", "min-content", "fit-content"}
)
LENGTH = re.compile(r"(\d*\.?\d+)(px|rem|em|%|vw|ch|ex)?\Z")
BREAKS = re.compile(r"[ \t\n\r\f\u200b]+")  # where text may wrap: a no-break space is not one
BORDER_STYLES = frozenset({"solid", "dashed", "dotted", "double", "groove", "ridge", "inset", "outset"})
FEATURE = re.compile(r"\(\s*([a-z-]+)\s*(?::\s*([^)]*?))?\s*\)")
NOT_WIDTH = frozenset(
    {"prefers-color-scheme", "prefers-reduced-motion", "prefers-contrast", "hover", "any-hover", "pointer"}
)  # a media feature that says nothing of the width: the rules under it count
COMPOUND = re.compile(r"(\*|[a-zA-Z][\w-]*)?((?:\.[\w-]+|#[\w-]+|\[[^\]]+\]|::?[\w-]+)*)\Z")
SIMPLE = re.compile(r"\.[\w-]+|#[\w-]+|\[[^\]]+\]|::?[\w-]+")
ATTRIBUTE = re.compile(r"\[\s*([\w-]+)\s*(?:=\s*(\"[^\"]*\"|'[^']*'|[^\]\s]+)\s*)?\]\Z")

DEFAULTS = """
head,script,style,title,meta,link,template,[hidden],input[type=hidden]{display:none}
table{display:table;border-spacing:2px}td,th{padding:1px}
body{margin:8px}ol,ul,menu{padding-left:40px}dd{margin-left:40px}blockquote,figure{margin:0 40px}
h1{font-size:2em}h2{font-size:1.5em}h3{font-size:1.17em}small,sub,sup{font-size:smaller}
pre{white-space:pre}nobr{white-space:nowrap}
input,select,button{border:2px solid;padding:1px 6px}textarea{border:1px solid;padding:2px}
"""  # the part of a browser's own stylesheet that sets a width, a frame, a font size or a display


@dataclass(eq=False)
class Node:
    tag: str
    attrs: dict[str, str]
    parent: Node | None = None
    children: list[Node | str] = field(default_factory=list)

    def elements(self) -> list[Node]:
        return [c for c in self.children if isinstance(c, Node)]

    def walk(self) -> Iterator[Node]:
        yield self
        for child in self.elements():
            yield from child.walk()

    def text(self) -> str:
        return "".join(c if isinstance(c, str) else c.text() for c in self.children)

    def label(self) -> str:
        """Where the element is: its tag, id and classes, after its three nearest ancestors'."""
        parts: list[str] = []
        node: Node | None = self
        while node is not None and node.tag != "#document" and len(parts) < 4:
            name = node.tag + (f"#{node.attrs['id']}" if node.attrs.get("id") else "")
            parts.append(name + "".join(f".{c}" for c in node.attrs.get("class", "").split()))
            node = node.parent
        return " > ".join(reversed(parts))


class _Tree(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#document", {})
        self.open = [self.root]
        self.css: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, {k: v or "" for k, v in attrs}, self.open[-1])
        self.open[-1].children.append(node)
        if tag not in VOID:
            self.open.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.open[-1].children.append(Node(tag, {k: v or "" for k, v in attrs}, self.open[-1]))

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.open) - 1, 0, -1):
            if self.open[i].tag == tag:
                del self.open[i:]
                return

    def handle_data(self, data: str) -> None:
        if self.open[-1].tag == "style":
            self.css.append(data)
        self.open[-1].children.append(data)


def parse(page: str) -> tuple[Node, str]:
    """The page's tree, every `<details>` open, and the text of its stylesheet."""
    tree = _Tree()
    tree.feed(page)
    tree.close()
    for node in tree.root.walk():
        if node.tag == "details":
            node.attrs["open"] = ""
    return tree.root, "".join(tree.css)


# -- the stylesheet --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    steps: tuple[tuple[str, str | None, tuple[str, ...]], ...]  # (combinator, tag, simple selectors)
    specificity: tuple[int, int, int]
    declarations: tuple[tuple[str, str, bool], ...]  # (property, value, important), longhands
    origin: int  # 0 the browser's, 1 the page's
    order: int
    media: str | None


def rules(css: str, origin: int = 1) -> list[Rule]:
    """The rules of `css`, each selector of a group its own, with the `@media` condition it is under."""
    out: list[Rule] = []
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for prelude, body in _blocks(css):
        if prelude.startswith("@media"):
            for inner, declarations in _blocks(body):
                out.extend(_rule(inner, declarations, origin, len(out), prelude[len("@media") :].strip()))
        elif prelude == "@font-face":
            continue  # a face the page loads: it names a typeface and lays out nothing (CHAR_EM holds for it)
        elif prelude.startswith("@"):
            raise ValueError(f"the width check does not read {prelude!r}")
        else:
            out.extend(_rule(prelude, body, origin, len(out), None))
    return out


def _blocks(css: str) -> Iterator[tuple[str, str]]:
    i = 0
    while (start := css.find("{", i)) >= 0:
        depth, j = 1, start + 1
        while depth:
            if j == len(css):
                raise ValueError(f"unbalanced braces after {css[i:start].strip()!r}")
            depth += {"{": 1, "}": -1}.get(css[j], 0)
            j += 1
        yield css[i:start].strip(), css[start + 1 : j - 1]
        i = j
    if css[i:].strip():
        raise ValueError(f"the stylesheet ends in {css[i:].strip()[:40]!r}")


def _rule(selectors: str, body: str, origin: int, order: int, media: str | None) -> Iterator[Rule]:
    declarations = tuple(_declarations(body))
    for selector in selectors.split(","):
        steps = _steps(selector)
        yield Rule(steps, _specificity(steps), declarations, origin, order, media)


def _specificity(steps: tuple[tuple[str, str | None, tuple[str, ...]], ...]) -> tuple[int, int, int]:
    """(ids; classes, attributes and pseudo-classes; tags and pseudo-elements)."""
    simples = [s for _, _, found in steps for s in found]
    ids = sum(s.startswith("#") for s in simples)
    elements = sum(s.startswith(":") and s.lstrip(":") in PSEUDO_ELEMENTS for s in simples)
    tags = sum(tag is not None for _, tag, _ in steps)
    return ids, len(simples) - ids - elements, tags + elements


def _steps(selector: str) -> tuple[tuple[str, str | None, tuple[str, ...]], ...]:
    """A complex selector, from the left: (the combinator before it, tag, simple selectors)."""
    steps: list[tuple[str, str | None, tuple[str, ...]]] = []
    word, combinator, depth = "", "", 0
    for ch in selector.strip() + " ":
        depth += {"[": 1, "]": -1}.get(ch, 0)
        if depth == 0 and (ch.isspace() or ch in ">+~("):
            if ch in "+~(":
                raise ValueError(f"the width check does not read {ch!r} in {selector.strip()!r}")
            if word:
                found = COMPOUND.match(word)
                if found is None:
                    raise ValueError(f"the width check does not read {word!r} in {selector.strip()!r}")
                tag = None if found.group(1) in (None, "*") else found.group(1).lower()
                steps.append((combinator, tag, tuple(SIMPLE.findall(found.group(2)))))
                word, combinator = "", " "
            if ch == ">":
                combinator = ">"
            continue
        word += ch
    return tuple(steps)


def _declarations(body: str) -> Iterator[tuple[str, str, bool]]:
    for part in body.split(";"):
        if not part.strip():
            continue
        name, colon, value = part.partition(":")
        if not colon:
            raise ValueError(f"the width check does not read the declaration {part.strip()!r}")
        value = value.strip()
        important = value.lower().endswith("!important")
        value = value[: -len("!important")].strip() if important else value
        for longhand, v in _longhands(name.strip().lower(), value):
            yield longhand, v, important


def _tokens(value: str) -> list[str]:
    return re.findall(r"[^\s(]+\([^)]*\)|\S+", value)


def _longhands(name: str, value: str) -> Iterator[tuple[str, str]]:
    """The properties the check reads, a shorthand's among them; a layout it cannot read is an error."""
    sides = {1: (0, 0), 2: (1, 1), 3: (1, 1), 4: (3, 1)}  # (left, right) of a box shorthand's values
    if name in ("margin", "padding", "border-width"):
        parts = _tokens(value)
        left, right = sides[len(parts)]
        base = name.removesuffix("-width")
        suffix = "-width" if name == "border-width" else ""
        yield f"{base}-left{suffix}", parts[left]
        yield f"{base}-right{suffix}", parts[right]
    elif name in ("margin-inline", "padding-inline"):
        parts = _tokens(value)
        yield f"{name.removesuffix('-inline')}-left", parts[0]
        yield f"{name.removesuffix('-inline')}-right", parts[-1]
    elif name in ("border", "border-left", "border-right", "border-inline"):
        tokens = _tokens(value)
        widths = [t for t in tokens if LENGTH.match(t) or t in ("thin", "medium", "thick")]
        width = widths[0] if widths else "3px" if BORDER_STYLES & set(tokens) else "0"
        width = {"thin": "1px", "medium": "3px", "thick": "5px"}.get(width, width)
        for side in ("left", "right") if name in ("border", "border-inline") else (name.split("-")[1],):
            yield f"border-{side}-width", width
    elif name == "gap":
        yield "column-gap", _tokens(value)[-1]
    elif name == "flex":
        basis = [t for t in _tokens(value) if LENGTH.match(t) and not re.fullmatch(r"\d*\.?\d+", t)]
        yield "flex-basis", basis[0] if basis else "auto"
    elif name == "font":
        size = [t.split("/")[0] for t in _tokens(value) if LENGTH.match(t.split("/")[0])]
        if size:
            yield "font-size", size[0]
    elif name == "overflow":
        yield "overflow-x", _tokens(value)[0]
    elif name == "word-wrap":
        yield "overflow-wrap", value
    elif name in ("inline-size", "min-inline-size", "max-inline-size"):
        yield name.replace("inline-size", "width"), value
    elif name in ("grid", "grid-template", "grid-area", "columns", "column-count", "column-width"):
        raise ValueError(f"the width check does not read {name}: {value}")
    else:
        yield name, value


def holds(condition: str | None, width: float) -> bool:
    """Whether a `@media` condition holds in a window `width` px wide, on a screen."""
    if condition is None:
        return True
    return any(_query(q.strip().lower(), width) for q in condition.split(","))


def _query(query: str, width: float) -> bool:
    words = FEATURE.sub(" ", re.sub(r"^only\s+", "", query)).replace(" and ", " ").split()
    if any(w not in ("all", "screen", "print", "and") for w in words):
        raise ValueError(f"the width check does not read the media query {query!r}")
    if "print" in words:
        return False
    found = True
    for name, value in FEATURE.findall(query):
        if name == "max-width":
            found = found and width <= _px(value, ROOT_PX, 0)
        elif name == "min-width":
            found = found and width >= _px(value, ROOT_PX, 0)
        elif name not in NOT_WIDTH:
            raise ValueError(f"the width check does not read the media feature {name!r}")
    return found


def phone_breakpoints(css: str) -> list[str]:
    """The `@media` conditions of `css` with rules under them that hold on a phone and not in a
    desktop window: where the stylesheet lays a page out for a phone."""
    found = [r.media for r in rules(css) if r.media is not None]
    return list(dict.fromkeys(m for m in found if holds(m, PHONE_PX) and not holds(m, DESKTOP_PX)))


def _px(value: str, font: float, of: float) -> float:
    """A length in px: an em of `font`, a percentage of `of`; 0 for a keyword that fixes no width."""
    value = value.strip().lower()
    if value in NO_WIDTH:
        return 0.0
    found = LENGTH.match(value)
    if found is None or (found.group(2) is None and float(found.group(1)) != 0):
        raise ValueError(f"the width check does not read the length {value!r}")
    unit = found.group(2) or "px"
    scale = {"px": 1, "rem": ROOT_PX, "em": font, "%": of / 100, "vw": PHONE_PX / 100, "ch": CHAR_EM * font}
    return float(found.group(1)) * scale.get(unit, font / 2)


# -- the layout --------------------------------------------------------------------------------------------


def _matches(node: Node, steps: tuple[tuple[str, str | None, tuple[str, ...]], ...], i: int) -> bool:
    combinator, tag, simples = steps[i]
    if (tag is not None and node.tag != tag) or not all(_simple(node, s) for s in simples):
        return False
    if i == 0:
        return True
    above = node.parent
    while above is not None and above.tag != "#document":
        if _matches(above, steps, i - 1):
            return True
        if combinator == ">":
            return False
        above = above.parent
    return False


def _simple(node: Node, simple: str) -> bool:
    if simple.startswith("."):
        return simple[1:] in node.attrs.get("class", "").split()
    if simple.startswith("#"):
        return node.attrs.get("id") == simple[1:]
    if simple.startswith("["):
        found = ATTRIBUTE.match(simple)
        if found is None:
            raise ValueError(f"the width check does not read the selector {simple!r}")
        name, wanted = found.groups()
        return name in node.attrs and (wanted is None or node.attrs[name] == wanted.strip("\"'"))
    name = simple.lstrip(":")
    if name in STATES or name in PSEUDO_ELEMENTS:
        return True
    siblings = node.parent.elements() if node.parent is not None else [node]
    if name == "root":
        return node.tag == "html"
    if name == "first-child":
        return siblings[0] is node
    if name == "last-child":
        return siblings[-1] is node
    raise ValueError(f"the width check does not read the selector {simple!r}")


@dataclass
class Style:
    values: dict[str, str]
    font: float  # px

    def get(self, name: str, default: str = "") -> str:
        return self.values.get(name, default).strip().lower()

    def px(self, name: str, of: float) -> float:
        return _px(self.get(name, "auto"), self.font, of)


INHERITED = ("white-space", "overflow-wrap", "word-break", "letter-spacing")


def _style(node: Node, sheet: list[Rule], parent: Style | None) -> Style:
    best: dict[str, tuple[tuple[bool, int, tuple[int, int, int], int], str]] = {}
    for rule in sheet:
        if not _matches(node, rule.steps, len(rule.steps) - 1):
            continue
        for name, value, important in rule.declarations:
            key = (important, rule.origin, rule.specificity, rule.order)
            if name not in best or key >= best[name][0]:
                best[name] = (key, value)
    for name, value, important in _declarations(node.attrs.get("style", "")):
        key = (important, 2, (0, 0, 0), 0)
        if name not in best or key >= best[name][0]:
            best[name] = (key, value)
    values = {name: value for name, (_, value) in best.items()}
    for name in INHERITED:
        if parent is not None and name not in values and name in parent.values:
            values[name] = parent.values[name]
    above = parent.font if parent is not None else ROOT_PX
    size = values.get("font-size", "inherit").strip().lower()
    keywords = {"smaller": above / 1.2, "larger": above * 1.2, "inherit": above, "medium": ROOT_PX}
    font = keywords[size] if size in keywords else _px(size, above, above)
    return Style(values, font)


@dataclass
class Layout:
    sheet: list[Rule]
    styles: dict[Node, Style] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    def style(self, node: Node) -> Style:
        if node not in self.styles:
            parent = node.parent if node.parent is not None and node.parent.tag != "#document" else None
            above = self.style(parent) if parent is not None else None
            self.styles[node] = _style(node, self.sheet, above)
        return self.styles[node]

    def need(self, node: Node, taken: float) -> tuple[float, str]:
        """The narrowest the element can be, margins, borders and padding included, and why; `taken`
        is what the frames around it take of the column. Records the element when it reaches past
        the column and nothing inside it does."""
        s = self.style(node)
        if s.get("display") == "none":
            return 0.0, ""
        column = PHONE_PX - taken  # its containing block's width, at most
        margin = s.px("margin-left", column) + s.px("margin-right", column)
        sides = ("border-left-width", "border-right-width", "padding-left", "padding-right")
        pad = sum(s.px(n, column) for n in sides)
        flagged = len(self.problems)
        own = (self.own(node, s, column), f"fixed by {self.why(node, s)}")
        inside = (0.0, "")
        if node.tag not in OPAQUE and s.get("overflow-x") not in SCROLLS:
            inside = self.content(node, s, taken + margin + pad, column - margin - pad)
        if s.get("box-sizing") == "border-box":
            box, why = max(own, (inside[0] + pad, inside[1]), (pad, "its frame"))
        else:
            box, why = max(own, inside)
            box += pad
        total = margin + box
        if taken + total > PHONE_PX + 0.5 and len(self.problems) == flagged:
            self.problems.append(f"{node.label()}: {taken + total:.0f} px, past the column ({why})")
        return total, why

    def own(self, node: Node, s: Style, column: float) -> float:
        """What the element fixes of its own width, whatever is inside it."""
        width, least = s.get("width", "auto"), s.px("min-width", column)
        if node.tag in IMAGES or node.tag in ("input", "textarea", "select"):
            if width.endswith("%") or s.get("max-width").endswith("%"):
                return least  # held by a percentage, a replaced element or a control shrinks with the column
            if width not in NO_WIDTH:
                return max(s.px("width", column), least)
            return max(self.default(node, s), least)
        basis = s.get("flex-basis", "auto")
        return max(s.px("width", column), least, 0.0 if basis.endswith("%") else _px(basis, s.font, column))

    def default(self, node: Node, s: Style) -> float:
        """A replaced element's or a form control's width when no rule gives one."""
        char = CHAR_EM * s.font
        kind = node.attrs.get("type", "text").lower()
        if node.tag == "input" and kind in ("checkbox", "radio"):
            return s.font
        if node.tag == "input" and kind in ("submit", "button", "reset"):
            return len(node.attrs.get("value", "Submit")) * char
        if node.tag in ("input", "textarea"):
            count = node.attrs.get("size" if node.tag == "input" else "cols", "")
            return (int(count) if count.isdigit() else CONTROL_CHARS) * char
        if node.tag == "select":
            longest = max((len(o.text()) for o in node.walk() if o.tag == "option"), default=0)
            return longest * char + 2 * s.font
        given = node.attrs.get("width", "").removesuffix("px")
        return float(given) if re.fullmatch(r"\d*\.?\d+", given) else REPLACED_PX

    def why(self, node: Node, s: Style) -> str:
        named = [
            f"{n} {s.get(n)}" for n in ("width", "min-width", "flex-basis") if s.get(n, "auto") != "auto"
        ]
        return ", ".join(named) or f"the {node.tag}'s default width"

    def content(self, node: Node, s: Style, taken: float, inner: float) -> tuple[float, str]:
        """The narrowest its content can be laid out in: a grid's columns, a table's widest row, a
        flex row's items side by side, else (a flex column's among them) the widest child or run of
        text."""
        kids = [k for k in node.elements() if self.style(k).get("display") != "none"]
        display = s.get("display")
        if display in ("grid", "inline-grid"):
            return self.grid(s, kids, taken, inner)
        if display in ("table", "inline-table"):
            spacing = 0.0 if s.get("border-collapse") == "collapse" else s.px("border-spacing", inner)
            found = [(0.0, "")]
            for row in _rows(node):
                cells = [self.need(c, taken)[0] for c in row.elements() if c.tag in ("td", "th")]
                found.append((sum(cells) + spacing * (len(cells) + 1), f"a table row of {len(cells)} cells"))
            return max(found)
        runs = [self.text(t, s) for t in node.children if isinstance(t, str) and t.strip()]
        whole = (0.0, "")  # where a stretch that may not break begins, its children's text is in it
        unbroken, above = ("nowrap", "pre"), node.parent
        if (
            s.get("white-space") in unbroken
            and above
            and self.style(above).get("white-space") not in unbroken
        ):
            whole = self.text(node.text(), s)
        needs = [self.need(k, taken) for k in kids]
        column = s.get("flex-direction", "row").startswith("column")  # one under another
        wraps = s.get("flex-wrap", "nowrap") != "nowrap"  # a column that wraps may lay columns side by side
        if display in ("flex", "inline-flex") and column == wraps:
            items = len(needs) + len(runs)
            line = sum(px for px, _ in [*needs, *runs]) + s.px("column-gap", inner) * max(items - 1, 0)
            return max((line, f"{items} items side by side"), whole)
        return max([(0.0, ""), whole, *needs, *runs])

    def text(self, text: str, s: Style) -> tuple[float, str]:
        return self.run(text, s), f"the text {' '.join(text.split())[:40]!r}"

    def grid(self, s: Style, kids: list[Node], taken: float, inner: float) -> tuple[float, str]:
        tracks = _tokens(s.get("grid-template-columns", "none"))
        if tracks == ["none"]:
            tracks = ["auto"]
        expanded: list[str] = []
        for track in tracks:
            found = re.fullmatch(r"repeat\((\d+),\s*(.+)\)", track)
            expanded.extend(_tokens(found.group(2)) * int(found.group(1)) if found else [track])
        if any(self.style(k).get("grid-column") for k in kids):
            raise ValueError("the width check does not read a grid item placed by grid-column")
        total = s.px("column-gap", inner) * (len(expanded) - 1)
        for j, track in enumerate(expanded):
            items = kids[j :: len(expanded)]
            least = re.fullmatch(r"minmax\(([^,]+),.*\)", track)
            track = least.group(1).strip() if least else track
            if track == "max-content":
                total += max((self.widest(k, taken) for k in items), default=0.0)
            else:
                fixed = 0.0 if track in NO_WIDTH or track.endswith("fr") else _px(track, s.font, inner)
                total += max([fixed, *(self.need(k, taken)[0] for k in items)])
        return total, f"a grid of {len(expanded)} columns, {s.get('grid-template-columns')}"

    def widest(self, node: Node, taken: float) -> float:
        """Its max-content width, about: its text on one line, or its narrowest when that is wider."""
        style = self.style(node)
        line = self.run(node.text(), Style({**style.values, "white-space": "nowrap"}, style.font))
        return max(self.need(node, taken)[0], line)

    def run(self, text: str, s: Style) -> float:
        """The widest piece of `text` that may not break, in px."""
        space = s.get("white-space", "normal")
        if space not in ("normal", "nowrap", "pre", "pre-wrap", "pre-line", "break-spaces"):
            raise ValueError(f"the width check does not read white-space {space!r}")
        if space == "nowrap":
            pieces = [" ".join(BREAKS.split(text.strip()))]
        elif space == "pre":
            pieces = text.split("\n")
        elif s.get("overflow-wrap") in ("anywhere", "break-word") or s.get("word-break") in WORD_BREAKS:
            pieces = [text.strip()[:1]]
        else:
            pieces = BREAKS.split(text)
        letter = 0.0 if s.get("letter-spacing", "normal") == "normal" else s.px("letter-spacing", 0)
        return max((len(p) for p in pieces), default=0) * (CHAR_EM * s.font + letter)


def problems(page: str) -> list[str]:
    """What on `page` a phone `PHONE_PX` wide would scroll sideways for, or nothing holds inside
    the column: an element that needs more than the column with the frames around it, an image or
    a `pre` with no `max-width` that keeps it inside, a stylesheet with no phone breakpoint."""
    root, css = parse(page)
    sheet = [r for r in rules(DEFAULTS, 0) + rules(css) if holds(r.media, PHONE_PX)]
    layout = Layout(sheet)
    found = [] if phone_breakpoints(css) else [f"no @media rule lays the page out {PHONE_PX:.0f} px wide"]
    html = next((n for n in root.walk() if n.tag == "html"), None)
    if html is None:
        return [*found, "the page has no <html>"]
    layout.need(html, 0.0)
    for node in html.walk():
        if (node.tag in IMAGES or node.tag == "pre") and not _held(layout, node):
            found.append(f"{node.label()}: no max-width keeps it inside the column")
    return found + layout.problems


def images(page: str) -> list[str]:
    """The labels of the images and `pre` elements on `page` that `problems` holds to a max-width."""
    root, _ = parse(page)
    return [n.label() for n in root.walk() if n.tag in IMAGES or n.tag == "pre"]


def _held(layout: Layout, node: Node) -> bool:
    """Whether a `max-width` keeps the element inside the column: a share of it, a length no wider
    than it, or a wider length on an element whose width is a share of the column."""
    s = layout.style(node)
    if s.get("display") == "none" or any(a.tag in OPAQUE for a in _ancestors(node)):
        return True
    limit, width = s.get("max-width", "none"), s.get("width", "auto")
    if limit in NO_WIDTH:
        return False
    if limit.endswith("%"):
        return float(limit[:-1]) <= 100
    return _px(limit, s.font, PHONE_PX) <= PHONE_PX or (width.endswith("%") and float(width[:-1]) <= 100)


def _rows(table: Node) -> Iterator[Node]:
    """The table's own rows, in its row groups or not; never a row of a table inside a cell."""
    for child in table.elements():
        if child.tag == "tr":
            yield child
        elif child.tag in ("thead", "tbody", "tfoot"):
            yield from (row for row in child.elements() if row.tag == "tr")


def _ancestors(node: Node) -> Iterator[Node]:
    above = node.parent
    while above is not None:
        yield above
        above = above.parent
