"""The look on every page (RFC 0047, the brief of 24 October 2026): every page of the Library that is not
a door's carries the doors' one stylesheet and its pages' rules (`doors.library_style`), and nothing of the
old one: no token of its own on `:root`, no `--fg`, `--bg`, `--mute` or `--accent`, no blue. The tokens
keep 4.5:1 for text in both faces, computed here; the signal is text only as `--signal-deep`. Pencil is
lighter, with a dotted rule and the model's or the rule's name in a title (RFC 0043 §3, RFC 0047 §7).
Every control is a 44 px target. An exported page carries the sheet without a face.

The records are the demo's fortnight and the shelves' synthetic record: nobody here exists."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
import test_names_held_to_their_tier as tiers_test
import test_no_count_beside_a_name as guard
from dream_fortnight import ENV, fake, run_cli
from persona import attendee, event, persona_record, resolution, utc

from logbook.contrib import (
    day_rhythm,
    demo,
    doors,
    search_page,
    serve,
    shelf_agents,
    shelf_goals,
    shelf_promises,
    timeline_page,
    week_page,
    world,
)
from logbook.core import figures
from logbook.core.store import Logbook

STYLE = re.compile(r"<style>(.*?)</style>", re.S)
LEGACY = re.compile(r"var\(--(?:fg|bg|mute|accent|graphite|gfaint|rule|card)\)|#2f5d7c|#8fb8d6", re.I)
ROOT_TOKENS = ":root{color-scheme:light dark;--paper"
SEEDS = ("/shelves", "/days", "/trips", "/journeys", "/people", "/places", "/promises", "/goals", "/ideas",
         "/manifest", "/manifest/people", "/agents", "/assets", "/gaps", "/timeline", "/search?q=home",
         "/week/2026-W23", "/day/2026-06-03", "/day/2026-06-03?shape=morning", "/day/2026-06-03?shape=live",
         "/day/2026-06-03?shape=signed", "/nowhere")  # fmt: skip


@pytest.fixture(scope="module")
def record(tmp_path_factory: pytest.TempPathFactory) -> Path:
    with pytest.MonkeyPatch.context() as mp:
        root = tmp_path_factory.mktemp("look") / "Demo"
        mp.setenv("LOGBOOK_HOME", str(root))
        return demo.generate(root, days=10, seed=1).root


def _pages(site: serve.Site, most: int = 70) -> Iterator[tuple[str, str]]:
    """target → the HTML of every page the seeds reach, breadth first, at most `most`."""
    queue, seen = list(SEEDS), set()
    while queue and len(seen) < most:
        target = queue.pop(0)
        if target in seen:
            continue
        seen.add(target)
        path, _, query = target.partition("?")
        response = site.respond(path, query)
        if not response.content_type.startswith("text/html"):
            continue
        text = response.body.decode("utf-8")
        yield target, text
        for found in re.findall(r'href="(/[^"#]*)', text):
            link = html.unescape(found)
            if not link.startswith(("/photo/", "/font/", "/world")) and link != "/":
                queue.append(link)


def test_every_page_wears_the_doors_look_and_nothing_of_the_old(record: Path) -> None:
    pages = list(_pages(serve.Site(Logbook(record))))
    assert len(pages) >= 40
    sheet = doors.library_style()
    doors_seen = 0
    for target, page in pages:
        styles = STYLE.findall(page)
        assert len(styles) == 1, target
        if '<main class="door">' in page:  # a door's own page (`doors.page`): its frame and its own look
            assert styles[0].startswith(doors.style()) and doors.PAGES not in styles[0], target
            assert ":root" not in styles[0].replace(doors.style(), "", 1), (target, "a door defines no token")
            assert LEGACY.search(styles[0]) is None, (target, LEGACY.search(styles[0]))
            doors_seen += 1
            continue
        assert styles[0].count(sheet) == 1 and styles[0].startswith(sheet), (target, "the one sheet, first")
        own = styles[0].replace(sheet, "", 1)
        assert ":root" not in own and "prefers-color-scheme" not in own.replace(
            "@media (prefers-color-scheme:dark){main{", ""
        ), (target, "the tokens and the dark face are the doors'")
        assert LEGACY.search(styles[0]) is None, (target, LEGACY.search(styles[0]))
        assert page.count("<main>") == 1 and page.count("<footer>") == 1, (
            target,
            "the frame the sheet styles",
        )
    assert doors.PAGES in sheet and doors.style() in sheet and sheet.count(ROOT_TOKENS) == 1
    assert doors_seen < len(pages) // 2, "the old pages are the most of what a crawl reaches"


def test_the_world_keeps_its_map_under_the_doors_tokens(record: Path) -> None:
    page = serve.Site(Logbook(record)).respond("/world").body.decode("utf-8")
    style = STYLE.search(page)
    assert style is not None
    css = style.group(1)
    assert world.LIBRARY_STYLE in css and doors.ROOT in css and doors.header_style() in css
    assert doors.PAGES not in css and css.index(world.STYLE) < css.index(doors.ROOT), "the doors' tokens last"
    assert "html:root{--fg:var(--ink);--bg:var(--paper);--mute:var(--pencil)" in world.LIBRARY_STYLE


def test_the_doors_header_is_the_only_header_and_no_page_rule_restyles_it(record: Path) -> None:
    """Every page carries the doors' header (#417); the pages' rules never name a bare `header` or a `nav`,
    which would reach into it."""
    assert not re.search(r"(^|[},\s>])(header|nav)[\s>{.:,]", doors.PAGES), "a rule that reaches the header"
    site = serve.Site(Logbook(record))
    for path in ("/days", "/people", "/day/2026-06-03", "/goals", "/search"):
        page = site.respond(path).body.decode("utf-8")
        assert page.count("<header") == 1 and page.count('<header class="doors">') == 1, path


def test_the_old_sheets_are_gone() -> None:
    for name in ("STYLE", "MANIFEST_STYLE", "TABLES_STYLE", "IDEAS_STYLE", "LINE_STYLE"):
        assert not hasattr(serve, name), name
    assert not hasattr(search_page, "TOKENS") and not hasattr(timeline_page, "TOKENS")
    for css in (serve.DAY_STYLE, day_rhythm.STYLE, week_page.WEEK_STYLE, search_page.SEARCH_STYLE,
                timeline_page.STYLE, shelf_agents.SHELF_STYLE, shelf_goals.SHELF_STYLE,
                doors.PAGES):  # fmt: skip
        assert ":root" not in css and LEGACY.search(css) is None, LEGACY.search(css)


def _luminance(colour: str) -> float:
    channels = [int(colour.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_contrast_is_4_5_to_1_for_text_in_both_faces() -> None:
    assert round(contrast("#000000", "#FFFFFF"), 2) == 21.0 and contrast("#777777", "#FFFFFF") < 4.5
    for face in (dict(doors.TOKENS), dict(doors.DARK)):
        for text in ("--ink", "--pencil", "--signal-deep"):
            for ground in ("--paper", "--surface", "--tint"):
                assert contrast(face[text], face[ground]) >= 4.5, (text, ground, face[text])
        for text in ("--card-dark-text", "--card-dark-muted"):
            assert contrast(face[text], face["--card-dark"]) >= 4.5, text
        assert contrast(face["--paper"], face["--ink"]) >= 4.5, "a primary pill's word on the ink"
    assert contrast(dict(doors.TOKENS)["--signal"], dict(doors.TOKENS)["--paper"]) < 4.5, "why: deep for text"
    sheets = doors.PAGES + day_rhythm.STYLE + serve.DAY_STYLE + search_page.SEARCH_STYLE + timeline_page.STYLE
    assert re.search(r"(?<![-\w])color:var\(--signal\)", sheets) is None, "the signal is text only when deep"
    assert re.search(r"(?<![-\w])color:var\(--(?:stay|move|aboard|call|plan)\)", sheets) is None, (
        "charts only"
    )


def test_pencil_is_lighter_with_a_dotted_rule_and_its_author_on_hover(record: Path) -> None:
    for rule in (
        r"\.pencil\{[^}]*",
        r"div\.paper p\.segment\{[^}]*",
        r"p\.proposal\{[^}]*",
        r"li\.decision\{[^}]*",
    ):
        found = re.search(rule, doors.REST + day_rhythm.STYLE)
        assert found is not None and "underline dotted var(--pencil-rule)" in found.group(0), rule
    assert re.search(r"div\.paper\{[^}]*color:var\(--pencil\)", day_rhythm.STYLE)
    assert re.search(r"\.ink,[^{]*\{font-family:var\(--serif\);color:var\(--ink\)", day_rhythm.STYLE)
    assert timeline_page.PROPOSED_BY.startswith("Pencil: proposed by")
    found = day_rhythm.proposal_html({"model": "a-model", "text": "Sail.", "supported": True, "line": "1"},
                                      lambda text, path: text)  # fmt: skip
    assert found.startswith('<p class="proposal" title="Pencil: drafted by a-model">')


def test_every_control_is_a_44_px_target() -> None:
    for rule in (r"main button,a\.skip\{", r"main input,main select\{", r"\nsummary\{",
                 r"p\.pager a,p\.zooms a,p\.facets a\{", r"a\.name\{",
                 r"main form\.star button\{"):  # fmt: skip
        found = re.search(rule + r"[^}]*", doors.PAGES)
        assert found is not None, rule
        assert "min-height:44px" in found.group(0) or "min-width:44px" in found.group(0), rule
    pill = re.search(r"main button,a\.skip\{[^}]*", doors.PAGES)
    assert pill is not None and "border-radius:23px" in pill.group(0)


def test_type_is_the_doors_serif_inter_and_mono() -> None:
    assert re.search(r"main h1\{[^}]*font-size:72px[^}]*font-family:var\(--serif\)", doors.PAGES)
    assert re.search(r"main h1\{font-size:40px", doors.PAGES), "the title on a phone"
    assert re.search(r"main h2\{[^}]*font-size:36px[^}]*font-family:var\(--serif\)", doors.PAGES)
    for label in (r"\.kind\{", r"dl\.header dt\{", r"main th\{"):
        found = re.search(label + r"[^}]*", doors.PAGES)
        assert found is not None and "font-family:var(--mono)" in found.group(0), label
        assert "font-size:13px" in found.group(0) or "font-size:14px" in found.group(0), label
        assert "text-transform:uppercase" in found.group(0), label


SIZE = re.compile(r"font(?:-size)?:(\d*\.?\d+)(px|rem)")


def test_no_text_falls_under_the_library_s_floor() -> None:
    """The Library's floor at a phone's width (tests/test_phone_targets.py, #428): text 14 px, the mono
    labels 13 px; under it only the drawings' own text (an SVG's, 12 px, the ribbon's floor) and the
    fold's marker glyph."""
    for css in (doors.PAGES, serve.DAY_STYLE, day_rhythm.STYLE, week_page.WEEK_STYLE,
                search_page.SEARCH_STYLE,
                timeline_page.STYLE, world.LIBRARY_STYLE):  # fmt: skip
        for rule in re.findall(r"[^{}]+\{[^{}]*\}", css):
            selector = rule.split("{")[0]
            for found in SIZE.finditer(rule):
                px = float(found.group(1)) * (16 if found.group(2) == "rem" else 1)
                if "svg" in selector or "::before" in selector:
                    assert px >= 11, rule
                else:
                    assert px >= 13, rule.strip()


def test_tables_scroll_in_their_own_box_on_a_phone() -> None:
    phone = doors.PAGES[doors.PAGES.index("@media (max-width:40rem){") :]
    assert "main table{display:block;overflow-x:auto}" in phone


def test_an_exported_page_carries_the_sheet_without_a_face(record: Path) -> None:
    site = serve.Site(Logbook(record), href=lambda path: "days.html" if path == "/days" else None)
    page = site.document("days", "<h1>Days</h1>\n")
    assert doors.library_style(fonts=False) in page and "@font-face" not in page and "url(" not in page


def test_a_promise_the_rules_read_is_pencil_wherever_it_shows(record: Path) -> None:
    """The blind review's finding: the shelf, a promise's page, a journey and a person set a promise the
    rules read in ink. It is pencil, with the rules named in its title; a promise's page keeps its title."""
    site = serve.Site(Logbook(record))
    shelf = site.respond("/promises").body.decode("utf-8")
    first = re.search(r'href="(/promises/[0-9a-f]+)"', shelf)
    assert first is not None
    titled = f'title="{shelf_promises.PENCIL}"'
    page = site.respond(first.group(1)).body.decode("utf-8")
    assert re.search(rf'<h1><q class="said" {re.escape(titled)}>', page), "the page's title, in pencil"
    assert shelf.count(f'<q class="said" {titled}>') == shelf.count('<q class="said"'), "every quote"
    journeys = site.respond("/journeys").body.decode("utf-8")
    pencils = 0
    for path in sorted(set(re.findall(r'href="(/journeys/[0-9-]+/[0-9-]+)"', journeys))):
        journey = site.respond(path).body.decode("utf-8")
        pencils += journey.count(f'<p class="pencil" {titled}>')
    assert pencils >= 1, "a journey's promises in pencil"
    assert re.search(r"main h1 q\.said\{font-size:inherit\}", doors.PAGES), "the title keeps its size"
    assert re.search(r"q\.said\{[^}]*underline dotted var\(--pencil-rule\)", doors.PAGES)
    phone = doors.PAGES[doors.PAGES.index("@media (max-width:40rem){") :]
    assert "main th,main td{white-space:nowrap}" in phone, "a date whole in a table on a phone"
    assert "p.head>a b," in doors.PAGES, "the serif in its one weight, never a bold drawn from it"


# -- the rules of the record, on every page in the look ----------------------------------------------------

ATTRIBUTE = re.compile(r'\b(?:title|aria-label|alt)="([^"]*)"')
SHAPES = ("", "?shape=morning", "?shape=live", "?shape=evening", "?shape=signed", "?open=1")


def _people_names(site: serve.Site) -> list[str]:
    """The names the People page links, at the Site's tiers: whoever the record names to it."""
    page = site.respond("/people").body.decode("utf-8")
    return sorted({html.unescape(n) for n in re.findall(r'<a href="/people/[^"]+"><b>([^<]+)</b></a>', page)})


def _beside(text: str, names: list[str]) -> list[str]:
    """`tests/test_no_count_beside_a_name.py`'s strong guard (#423, #430) for `names`: the markup taken out,
    a row's link to its line and a draft's short ids left out as addresses, each SVG tooltip a text of its
    own; every attribute a person reads (`title`, `aria-label`, `alt`) a text of its own too."""
    texts = [html.unescape(a) for a in ATTRIBUTE.findall(text)]
    unmarked = re.sub(r"<[^>]*>", " ", guard.TOOLTIP_END.sub("\n", guard.RAW.sub(" ", text)))
    texts += guard.SHORT.sub(" ", html.unescape(unmarked)).splitlines()
    return [t.strip() for t in texts for name in names if figures.adjacent(t, name)]


def _every_state(site: serve.Site) -> Iterator[tuple[str, str]]:
    """Every page the crawl reaches, and every Day it reaches in every shape and opened whole."""
    for target, page in _pages(site, most=120):
        yield target, page
        path, _, _ = target.partition("?")
        if path.startswith("/day/") and target == path:
            for shape in SHAPES[1:]:
                query = shape[1:]
                yield f"{path}{shape}", site.respond(path, query).body.decode("utf-8")


@pytest.fixture(scope="module")
def persona(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The Oslo persona's fortnight (people named by tier-2 resolutions, Kari also by a tier-1 attendee
    name), a model's drafts of three days and their week, and Per Hemmelig, whom only a tier-3 line names,
    at a tier-1 dinner (`tests/test_names_held_to_their_tier.py`)."""
    with pytest.MonkeyPatch.context() as mp:
        root = tmp_path_factory.mktemp("look-persona")
        lb = persona_record(root, mp)
        secret = resolution(("email", tiers_test.PER_EMAIL), tiers_test.PER_ID, tiers_test.PER)
        secret["tier"] = 3
        lb.append_many(
            [
                secret,
                event(
                    utc(tiers_test.DINNER_DAY, "18:00"),
                    utc(tiers_test.DINNER_DAY, "21:00"),
                    "Dinner",
                    [attendee(tiers_test.PER_EMAIL)],
                ),
            ]
        )
        mp.setenv("LOGBOOK_HOME", str(lb.root))
        for name, value in ENV.items():
            mp.setenv(name, value)
        path = lb.root / "policy" / "crossing.json"
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        data["dream"] = {"max_tier": 2, "until": "2027-12-31"}
        path.write_text(json.dumps(data), encoding="utf-8")
        fake(mp)
        for day in ("2026-06-17", "2026-06-18", "2026-06-19"):
            assert run_cli("dream", "day", day)[0] == 0, day
        return lb.root


def test_no_number_date_or_clock_touches_a_name_on_any_page_or_state(persona: Path, record: Path) -> None:
    for root in (persona, record):
        site = serve.Site(Logbook(root))
        names = sorted({*_people_names(site), *guard.NAMES})
        assert len(names) >= 5
        checked = 0
        for target, page in _every_state(site):
            assert _beside(page, names) == [], (target, _beside(page, names)[:3])
            checked += 1
        assert checked >= 60, checked


@pytest.mark.parametrize(
    ("tiers", "hidden"),
    [((1,), ("Ola Nordmann", tiers_test.PER)), ((1, 2), (tiers_test.PER,))],
)
def test_a_page_reads_nothing_above_its_tier_in_the_look(
    persona: Path, tiers: tuple[int, ...], hidden: tuple[str, ...]
) -> None:
    """A name only a higher tier's line gives is on no page, in no text, title, aria-label, alt or
    completion list (the Day's `with` field, `resolve.at_tiers`): Ola Nordmann is named by tier-2 lines
    alone, Per Hemmelig by a tier-3 line alone."""
    site = serve.Site(Logbook(persona), tiers=list(tiers))
    pages = list(_every_state(site))  # the People door (#410) among them, through its gate
    assert len(pages) >= 30
    full = serve.Site(Logbook(persona))
    day = full.respond(f"/day/{tiers_test.DINNER_DAY}").body.decode("utf-8")
    assert all(f'<option value="{name}">' in day for name in hidden), (
        "the record holds what the gate keeps out"
    )
    for target, page in pages:
        said = html.unescape(page) + " ".join(html.unescape(a) for a in ATTRIBUTE.findall(page))
        for name in hidden:
            assert name not in said, (tiers, target, name)


def test_every_page_in_the_look_is_unframed_and_fetches_nothing(record: Path) -> None:
    """The doors' policy on every response (#421: `frame-ancestors 'none'`, nothing by default), and no
    address outside the Library in any page's markup or its style: the faces are the server's own."""
    site = serve.Site(Logbook(record))
    seen = 0
    for target, _page in _pages(site):
        path, _, query = target.partition("?")
        response = site.respond(path, query)
        assert response.csp.startswith("default-src 'none'"), target
        assert "frame-ancestors 'none'" in response.csp, target
        body = response.body.decode("utf-8")
        assert not re.search(r"""(?:src|href|action)=["'](?:https?:)?//""", body), target
        assert "http://" not in "".join(STYLE.findall(body)) and "https://" not in "".join(
            STYLE.findall(body)
        )
        seen += 1
    assert seen >= 40
