"""The Library at a phone's width, held to what a thumb and an eye need: every target a page names
is 44 px or more, every text it names keeps its size, and every colour a kind or a badge is shown in
keeps 4.5:1 on the page's paper in both faces. Read from the pages' own HTML and stylesheet with
`phone_width`'s cascade (no browser), on the demo record; nobody in it exists."""

from __future__ import annotations

import contextlib
import io
import re
from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import phone_width
import pytest

from logbook import cli
from logbook.contrib import day_rhythm, serve, shelf_promises, world
from logbook.core.store import Logbook

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)  # after the record: every Day in its evening shape
DAY, WEEK = "2026-06-17", "2026-W25"  # a day aboard Nordlys, with stays, a move and time aboard
TARGET_PX, TEXT_PX, RATIO = 44.0, 14.0, 4.5
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
TOKEN = re.compile(r"--([\w-]+):(#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?)\b")
DARK = re.compile(r"@media \(prefers-color-scheme:dark\)\{((?:[^{}]|\{[^{}]*\})*)\}")
BOXED = {"input": "inline-block", "button": "inline-block", "select": "inline-block", "summary": "list-item"}


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    root = tmp_path_factory.mktemp("phone-targets") / "Demo"
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LOGBOOK_HOME", str(root))
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["demo", "--days", "30", "--out", str(root)])
    return Logbook(root)


def _page(lb: Logbook, path: str) -> str:
    response = serve.Site(lb, now=lambda: NOW).respond(path)
    assert response.status == 200, path
    return response.body.decode("utf-8")


Is = Callable[[phone_width.Node], bool]


def _styled(page: str, wanted: Is) -> Iterator[tuple[phone_width.Node, phone_width.Style]]:
    """Each element of `page` that `wanted` picks, with its style as a phone applies the sheet."""
    root, css = phone_width.parse(page)
    sheet = [
        r
        for r in phone_width.rules(phone_width.DEFAULTS, 0) + phone_width.rules(css)
        if phone_width.holds(r.media, phone_width.PHONE_PX)
    ]
    layout = phone_width.Layout(sheet)
    for node in root.walk():
        if node.tag != "#document" and wanted(node):
            yield node, layout.style(node)


def _tag(tag: str, cls: str | None = None, **attrs: str) -> Is:
    def wanted(n: phone_width.Node) -> bool:
        classes = n.attrs.get("class", "").split()
        return (
            n.tag == tag
            and (cls is None or cls in classes)
            and all(n.attrs.get(k) == v for k, v in attrs.items())
        )

    return wanted


def _within(inner: Is, *outer: Is) -> Is:
    def wanted(n: phone_width.Node) -> bool:
        if not inner(n):
            return False
        above, i = n.parent, len(outer) - 1
        while above is not None and i >= 0:
            if outer[i](above):
                i -= 1
            above = above.parent
        return i < 0

    return wanted


def _display(n: phone_width.Node, s: phone_width.Style) -> str:
    """The element's display: its own, or a browser's for a form control (an inline block) and a
    summary (a list item), which `phone_width.DEFAULTS` leaves out as they set no width."""
    return s.get("display") or BOXED.get(n.tag, "inline")


def _height(n: phone_width.Node, s: phone_width.Style) -> float:
    """The least height the element's box keeps: a `min-height`, a `height` or a `line-height`, none of
    which an inline box keeps."""
    if _display(n, s) == "inline":
        return 0.0
    line = s.get("line-height", "normal")
    lines = (
        phone_width._px(line, s.font, 0) if phone_width.LENGTH.match(line) and not line[-1].isdigit() else 0.0
    )
    return max(s.px("min-height", 0), s.px("height", 0) if s.get("height") else 0.0, lines)


def _width(n: phone_width.Node, s: phone_width.Style) -> float:
    if _display(n, s) == "inline":
        return 0.0
    return max(s.px("min-width", 0), s.px("width", 0) if s.get("width") else 0.0)


def _tall(page: str, wanted: Is) -> list[str]:
    found = list(_styled(page, wanted))
    assert found, "the page shows none of these"
    return [f"{n.label()}: {_height(n, s):.0f} px" for n, s in found if _height(n, s) < TARGET_PX]


def _wide(page: str, wanted: Is) -> list[str]:
    found = list(_styled(page, wanted))
    assert found, "the page shows none of these"
    return [f"{n.label()}: {_width(n, s):.0f} px" for n, s in found if _width(n, s) < TARGET_PX]


def _small(page: str, wanted: Is, least: float = TEXT_PX) -> list[str]:
    found = list(_styled(page, wanted))
    assert found, "the page shows none of these"
    return [f"{n.label()}: {s.font:.1f} px" for n, s in found if s.font < least - 0.01]


# -- the targets ---------------------------------------------------------------------------------------


def test_the_day_s_line_as_written_is_a_44_px_target_at_14_px(demo: Logbook) -> None:
    page = _page(demo, f"/day/{DAY}")
    raw = _tag("a", "raw")
    assert _tall(page, raw) == []
    assert _wide(page, raw) == []
    assert _small(page, raw) == []


@pytest.mark.parametrize("path", [f"/day/{DAY}", "/people"])
def test_every_fold_s_summary_is_44_px_tall(demo: Logbook, path: str) -> None:
    assert _tall(_page(demo, path), _tag("summary")) == []


def test_the_evidence_summary_on_the_people_page_is_14_px(demo: Logbook) -> None:
    assert _small(_page(demo, "/people"), _within(_tag("summary"), _tag("details", "evidence"))) == []


PEOPLE_DOOR = ("/people", "/people/4f8c85f9-0e6a-56f0-a9db-0d09bfdd3d56")  # the door, and Ola's whole thread


@pytest.mark.parametrize("path", PEOPLE_DOOR)
def test_the_people_door_s_links_are_44_px_tall(demo: Logbook, path: str) -> None:
    """The People door (RFC 0047 §4.3): beside its folds, its targets are its pills (the whole thread,
    Life, Places, what was said), each 44 px tall, as every fold's is."""
    assert _tall(_page(demo, path), _tag("a", "pill")) == []


def test_the_people_door_s_secondary_lines_are_14_px(demo: Logbook) -> None:
    """Beside the evidence, the door's other smaller words: the lead, the legend, the kicker, a moment's
    date, each 14 px on a phone."""
    page = _page(demo, "/people")
    for wanted in (_tag("p", "lead"), _tag("ul", "legend"), _tag("p", "kicker"), _tag("span", "date")):
        assert _small(page, wanted) == []


def test_the_places_review_s_name_skip_and_reject_are_44_px_tall(demo: Logbook) -> None:
    page = _page(demo, "/places")
    form = _tag("form", "name")
    assert _tall(page, _within(_tag("input", type="text"), form)) == []
    assert _tall(page, _within(_tag("button"), form)) == []
    assert _tall(page, _tag("a", "skip")) == []


def test_the_week_s_keep_box_and_its_day_links_are_44_px_targets(demo: Logbook) -> None:
    """The keep box is its label: the box drawn at the text's size, the label around it and its words,
    a row 44 px tall, the target a tap toggles it by."""
    page = _page(demo, f"/week/{WEEK}")
    assert _tall(page, _tag("label", "keep")) == []
    assert [n.tag for n in phone_width.parse(page)[0].walk() if n.tag == "input" and _in_keep(n)] == ["input"]
    assert _tall(page, _within(_tag("a"), _tag("p", "day"))) == []


def _in_keep(n: phone_width.Node) -> bool:
    return (
        n.attrs.get("type") == "checkbox"
        and n.parent is not None
        and "keep" in n.parent.attrs.get("class", "")
    )


def test_the_life_s_year_links_and_zooms_are_44_px_wide(demo: Logbook) -> None:
    page = _page(demo, "/timeline/life")
    assert _wide(page, _tag("a", "tap")) == []
    assert _wide(page, _within(_tag("a"), _tag("p", "zooms"))) == []


@pytest.mark.parametrize("path", ["/days", f"/week/{WEEK}"])
def test_a_pager_s_links_are_44_px_tall(demo: Logbook, path: str) -> None:
    assert _tall(_page(demo, path), _within(_tag("a"), _tag("p", "pager"))) == []


def test_the_days_links_window_and_show_button_are_44_px_tall(demo: Logbook) -> None:
    page = _page(demo, "/days")
    assert _tall(page, _within(_tag("a"), _tag("td", "day"))) == []
    window = _tag("form", "window")
    assert _tall(page, _within(_tag("input", type="date"), window)) == []
    assert _tall(page, _within(_tag("button"), window)) == []


def test_the_world_s_map_buttons_are_44_px_square(demo: Logbook) -> None:
    page = _page(demo, "/world")
    for name in ("zoom-in", "zoom-out", "fit", "whole", "play"):
        button = _tag("button", id=name)
        assert _tall(page, button) == [], name
        assert _wide(page, button) == [], name


def test_the_world_s_scrubber_stays_above_the_doors_bar(demo: Logbook) -> None:
    """On a phone the doors are a bar fixed at the foot and the page's body is padded for it; the world
    page's body is the screen's height (`height:100%`), so the padding must be inside that height, or
    the scrubber and the play button are laid out under the bar."""
    [(_, body)] = _styled(_page(demo, "/world"), _tag("body"))
    assert body.get("height") == "100%"
    assert body.px("padding-bottom", 0) > 0
    assert body.get("box-sizing") == "border-box"


def test_the_world_with_a_navigation_of_its_own_wraps_it(demo: Logbook) -> None:
    """The world page beside a navigation (`nav`, as a Library with no doors passed it) wraps its links
    as the other pages' navigation does: links written edge to edge, with no space between them, are
    one word a browser never breaks, which once laid `/world` out 935 px wide on a phone."""
    bundle = world.embedded_json(_page(demo, "/world"))
    nav = "".join(
        f'<a href="/{w}">{w}</a>' for w in ("days", "trips", "places", "world", "journeys", "people")
    )
    page = world.page(bundle, nav=nav * 2, standalone=False)
    navs = [s for _, s in _styled(page, _within(_tag("nav"), _tag("header")))]
    assert [(s.get("display"), s.get("flex-wrap")) for s in navs] == [("flex", "wrap")]
    assert phone_width.problems(page) == []


# -- the sizes -----------------------------------------------------------------------------------------


def test_the_day_s_eyebrows_ribbon_kinds_and_footer_are_readable(demo: Logbook) -> None:
    page = _page(demo, f"/day/{DAY}")
    assert _small(page, _within(_tag("h2"), _tag("section", "part")), 13.0) == []
    assert _small(page, _tag("p", "eyebrow"), 13.0) == []
    assert _small(page, _within(_tag("text"), _tag("svg", "ribbon")), 12.0) == []
    assert _small(page, _within(_tag("span", "kind"), _tag("li", "row"))) == []
    assert _small(page, _tag("footer")) == []


def test_the_people_page_s_ids_and_evidence_are_14_px(demo: Logbook) -> None:
    page = _page(demo, "/people")
    assert _small(page, _tag("span", "id")) == []
    assert _small(page, _tag("ul", "evidence")) == []


def test_the_people_door_s_dates_addresses_and_facts_are_14_px(demo: Logbook) -> None:
    """A person's whole thread: its dates, its line on the strip of days and its addresses are small
    words too, each 14 px on a phone."""
    page = _page(demo, PEOPLE_DOOR[1])
    for wanted in (_tag("span", "date"), _tag("p", "fact"), _tag("dl", "refs")):
        assert _small(page, wanted) == []


# -- the colours ---------------------------------------------------------------------------------------


def _luminance(colour: str) -> float:
    def channel(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    digits = colour[1:] if len(colour) == 7 else "".join(c * 2 for c in colour[1:])
    r, g, b = (int(digits[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _ratio(a: str, b: str) -> float:
    x, y = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


def _faces(css: str) -> tuple[dict[str, str], dict[str, str]]:
    """The tokens a stylesheet sets on `:root`, light and under its dark media rules, each face in the
    order the sheet sets them."""
    dark = "".join(DARK.findall(css))
    return dict(TOKEN.findall(DARK.sub("", css))), dict(TOKEN.findall(dark))


def _colour_of(css: str, selector: str) -> str:
    found = re.search(re.escape(selector) + r"\{color:([^;}]+)", css)
    assert found is not None, selector
    return found.group(1)


KINDS = ("stay", "move", "flight", "aboard", "gap")


@pytest.mark.parametrize("kind", KINDS)
def test_a_row_s_kind_is_a_token_that_keeps_4_5_to_1_in_both_faces(kind: str) -> None:
    colour = _colour_of(serve.STYLE, f".row.{kind}>.kind")
    assert not HEX.search(colour), f"{kind}: a hard-coded colour has no dark value"
    token = colour.removeprefix("var(--").removesuffix(")")
    light, dark = _faces(serve.STYLE)
    day_light, day_dark = _faces(day_rhythm.STYLE)
    for face, tokens in (
        ("light", light),
        ("dark", {**light, **dark}),
        ("the Day's light", {**light, **day_light}),  # the Day sets its tokens after the old pages'
        ("the Day's dark", {**light, **dark, **day_light, **day_dark}),
    ):
        assert _ratio(tokens[token], tokens["bg"]) >= RATIO, (kind, face, tokens[token], tokens["bg"])


def test_the_day_keeps_the_tokens_of_its_own_design() -> None:
    """The Day's kinds are the owner's tokens (`day_rhythm.LIGHT`, `DARK`): the old pages carry the same
    values, so a kind is one colour wherever it is shown."""
    light, dark = _faces(serve.STYLE)
    for token in ("stay", "move", "aboard"):
        assert light[token] == dict(TOKEN.findall(day_rhythm.LIGHT))[token]
        assert dark[token] == dict(TOKEN.findall(day_rhythm.DARK))[token]


@pytest.mark.parametrize(
    ("css", "selectors"),
    [
        (shelf_promises.SHELF_STYLE, (".badge.open", ".badge.kept")),
        (serve.MANIFEST_STYLE, (".badge.passed", ".badge.sell", ".stale-flag")),
    ],
)
def test_a_badge_keeps_4_5_to_1_in_both_faces(css: str, selectors: tuple[str, ...]) -> None:
    light, dark = _faces(serve.STYLE)
    dark = {**light, **dark}
    for selector in selectors:
        colour = _colour_of(css, selector)
        assert not HEX.search(colour), f"{selector}: a hard-coded colour has no dark value"
        token = colour.removeprefix("var(--").removesuffix(")")
        for face, tokens in (("light", light), ("dark", dark)):
            assert _ratio(tokens[token], tokens["bg"]) >= RATIO, (selector, face, tokens[token])
