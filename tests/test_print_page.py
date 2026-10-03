"""`logbook year YYYY --html PATH --print` and `logbook trip ID --html PATH --print`: the paper
edition — a cover, a contents page, one spread per month or per day with the facts, a map drawn
from the location lines and the keepers as hero photos, page numbers from the page counter; one
inline stylesheet, no script, nothing fetched; the photos referenced, never copied. The demo
record's 2026 and its yacht week are pinned as fixtures; every document is checked structurally;
a day with no photos still lays out. The Oslo persona does not exist."""

from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
from persona import TZ, persona_record, photo, utc

from logbook import attachments, cli, demo, keepers, print_layout, print_page
from logbook.store import Logbook

EN_DASH = "\u2013"
YACHT_WEEK = "trip:2026-06-15:2026-06-20"
FIXTURES = Path(__file__).parent / "fixtures" / "demo"
REGENERATE = "regenerate with `uv run python scripts/make_print_fixtures.py` when the change is meant"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(list(args))
    return capsys.readouterr().out


@pytest.fixture(scope="module")
def record(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    """Thirty days of the demo record (seed 7), generated once for the module; nothing in it is
    real. The fixtures were written from this same record by `scripts/make_print_fixtures.py`."""
    root = tmp_path_factory.mktemp("demo") / "Demo"
    cli.main(["demo", "--days", "30", "--seed", "7", "--out", str(root)])
    return Logbook(root)


@pytest.fixture
def lb(record: Logbook, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    monkeypatch.setenv("LOGBOOK_HOME", str(record.root))
    return record


# -- the structural check -----------------------------------------------------------------------------------


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


def structure(page: str) -> Structure:
    """The document is well formed: every tag closed in order, one stylesheet and nothing else in
    the head, no script, no link, no handler, every `src` an `img`'s with an `alt`, nothing from
    the network, the paged-media rules present."""
    assert page.startswith('<!doctype html>\n<html lang="en">') and page.endswith("</html>\n")
    s = Structure()
    s.feed(page)
    s.close()
    assert s.errors == [] and s.open == [], (s.errors, s.open)
    assert s.tags["style"] == 1, "one inline stylesheet"
    assert s.tags["script"] == 0 and s.tags["link"] == 0 and s.tags["iframe"] == 0
    assert s.tags["title"] == 1 and s.tags["body"] == 1
    for tag, attrs in s.elements:
        assert "href" not in attrs, (tag, attrs)
        assert not any(k.startswith("on") for k in attrs), (tag, attrs)
        if "src" in attrs:
            assert tag == "img", "only a photo is loaded"
            assert not str(attrs["src"]).startswith(("http:", "https:", "//")), attrs["src"]
        if tag == "img":
            assert "alt" in attrs
    assert "http://" not in page and "https://" not in page
    assert "@import" not in page and "url(" not in page and "<link" not in page
    assert "@page" in page and "counter(page)" in page and "break-before: page" in page
    assert '<section class="cover">' in page and '<section class="contents">' in page
    assert '<footer class="colophon">' in page
    return s


# -- the fixtures ------------------------------------------------------------------------------------------


def test_the_year_on_paper_is_the_fixture_and_lays_out(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "paper" / "2026.html"
    assert _run(capsys, "year", "2026", "--html", str(out), "--print") == f"year 2026: wrote {out}\n"
    page = out.read_bytes().decode("utf-8")
    expected = (FIXTURES / "print_year_2026.html").read_text(encoding="utf-8")
    assert page.splitlines() == expected.splitlines(), REGENERATE
    assert page == print_page.html(print_page.read_year(lb, "2026"))
    s = structure(page)
    assert "<title>2026 · Logbook</title>" in page
    assert "<h1>2026</h1>" in page and "ines.nordmann@example.org" in page, "the cover: the year, the name"
    assert f'<p class="dates">1{EN_DASH}30 June 2026 · 30 days</p>' in page
    assert page.count('<section class="spread month"') == 1 and 'id="m-2026-06"' in page, "one spread a month"
    assert "<h2>June</h2>" in page and "Day 1 of" not in page
    for term in ("Nights", "Places, by nights", "With", "Flights", "Sleep", "Steps", "Keepers"):
        assert f"<dt>{term}</dt>" in page, term
    assert f"6 nights aboard {demo.BOAT_NAME}" in page and "XY 561 OSL → ZRH" in page
    assert "Marta Keller" in page and "Per Hansen" in page, "confirmed company"
    assert "<dd>6.8 h a night (29 nights)</dd>" in page and "8,425 a day (30 days)" in page
    assert "<dd>9 (8 memory, 1 art)</dd>" in page
    assert s.tags["svg"] == 1 and '<path class="track"' in page, "the month's track, drawn inline"
    assert s.tags["circle"] >= 1 and s.tags["circle"] <= 8, "one mark per distinct place, eight places"
    assert s.tags["figure"] == 1 + 9 and s.tags["img"] == 0, "nine keepers, none stored: frames"
    assert page.count("not in the record") == 9 and page.count('<article class="photos') == 2
    assert 'class="photos n6"' in page and 'class="photos n4"' in page, "six to a page, then three"
    assert "Trips" in page and f"2026-06-15 {EN_DASH} 2026-06-20" in page, "the contents list the trips"
    assert "Cabin" in page and "Zurich" in page
    assert str(lb.root) not in page, "nothing of this machine is in the document"


def test_the_trip_on_paper_is_the_fixture_a_spread_a_day(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "week.html"
    text = _run(capsys, "trip", YACHT_WEEK, "--html", str(out), "--print")
    assert text == f"trip {YACHT_WEEK}: wrote {out}\n"
    page = out.read_bytes().decode("utf-8")
    expected = (FIXTURES / "print_trip_2026-06-15.html").read_text(encoding="utf-8")
    assert page.splitlines() == expected.splitlines(), REGENERATE
    assert page == print_page.html(print_page.read_trip(lb, YACHT_WEEK))
    s = structure(page)
    assert f"<title>15{EN_DASH}21 June 2026 · Logbook</title>" in page
    assert f"<h1>15{EN_DASH}21 June 2026</h1>" in page, "the cover: the trip's dates, the return day included"
    assert f"6 nights aboard {demo.BOAT_NAME}" in page and "until 2026-06-21" in page
    assert page.count('<section class="spread day"') == 7, "the leaving day to the return day"
    assert "Day 1 of 7" in page and "Day 7 of 7" in page and "<h2>Monday 15 June</h2>" in page
    assert '<section class="route">' in page, "the route on a page of its own"
    assert page.count('<path class="leg') == 4, "one path a leg"
    assert s.tags["svg"] == 1 + 7, "the route and a map a day"
    assert "Marina" in page and "Sandefjord" in page and "Ola Nordmann" in page
    for term in ("Night before", "Night after", "Country", "Places", "With", "Flights", "Sleep", "Steps"):
        assert f"<dt>{term}</dt>" in page, term
    assert "<dd>Home · home</dd>" in page, "the night before the leaving day"
    assert f"59.4300,10.4800 (Sandefjord) · aboard {demo.BOAT_NAME}" in page, "an anchorage is a place"
    assert "Day 1 of 7" in page and "Day 2 of 7" in page
    assert "with Ola Nordmann, Anders Vik" in page, "the contents say who was there"
    assert '<article class="photos n1"' in page, "a day's one keeper takes the page"


def test_a_day_with_no_photos_still_lays_out(lb: Logbook) -> None:
    data = print_page.read_trip(lb, YACHT_WEEK)
    bare = [d for d in data["days"] if not d["keepers"]]
    kept = [d for d in data["days"] if d["keepers"]]
    assert bare and kept, "the yacht week has days with keepers and days without"
    page = print_page.html(data)
    structure(page)
    for d in bare:
        spread = page.split(f'<section class="spread day" id="d-{d["day"]}">')[1].split("</section>")[0]
        assert spread.count("<article") == 1 and '<article class="facts">' in spread, "the facts page alone"
        assert '<article class="photos' not in spread
        assert '<dd class="empty">none</dd>' in spread.split("<dt>Keepers</dt>")[1]
        assert "<dt>Night after</dt>" in spread and "<figure class" in spread, "the facts and the map"
    for d in kept:
        spread = page.split(f'<section class="spread day" id="d-{d["day"]}">')[1].split("</section>")[0]
        assert spread.count("<article") == 2 and '<article class="photos' in spread


# -- the photos ---------------------------------------------------------------------------------------------


def _keepers_for(lb: Logbook, *names: str) -> list[dict[str, Any]]:
    """Memory keeper drafts for the record's photo lines named, as `infer keepers` would write them."""
    found = {str(line["payload"].get("file_name")): line for line in lb.lines() if line["kind"] == "photo"}
    return [keepers.draft(found[name], keepers.MEMORY) for name in names]


def test_photos_are_referenced_where_they_are_never_copied_and_escaped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    pixels = b"\xff\xd8\xff\xe0 not really a jpeg, but bytes the record stores"
    lb.attach(pixels)
    stored = photo(utc("2026-06-13", "12:00"), (59.85, 10.6))
    stored["payload"]["file_name"] = "<b>hero</b>.jpg"
    stored["payload"]["content"] = attachments.reference(pixels, "image/jpeg")
    original = tmp_path / "originals" / "IMG_0613.jpg"
    elsewhere = photo(utc("2026-06-13", "15:00"), (59.85, 10.6))
    elsewhere["payload"]["file_name"] = "IMG_0613.jpg"
    elsewhere["payload"]["extra"] = {"original_path": str(original)}
    named = photo(utc("2026-06-13", "18:00"), (59.85, 10.6))
    named["payload"]["file_name"] = "IMG_ONLY_NAMED.HEIC"
    lb.append_many([stored, elsewhere, named])
    lb.append_many(_keepers_for(lb, "<b>hero</b>.jpg", "IMG_0613.jpg", "IMG_ONLY_NAMED.HEIC"))
    head = lb.meta["head"]
    files_before = sorted(p.name for p in (lb.root / "attachments").iterdir())
    out = tmp_path / "paper" / "2026.html"
    _run(capsys, "year", "2026", "--html", str(out), "--print")
    page = out.read_text(encoding="utf-8")
    s = structure(page)
    srcs = [str(attrs["src"]) for tag, attrs in s.elements if tag == "img"]
    sha = attachments.digest(pixels)
    assert srcs[0] == (lb.root.resolve() / "attachments" / sha).as_uri(), "the attachment, under the record"
    assert srcs[1] == original.as_uri(), "the library's own path, as a file URL"
    assert len(srcs) == 2 and "IMG_ONLY_NAMED.HEIC" in page and "not in the record" in page
    assert "&lt;b&gt;hero&lt;/b&gt;.jpg" in page and "<b>hero</b>" not in page, "escaped"
    assert sorted(p.name for p in (out.parent).iterdir()) == ["2026.html"], "no photo copied beside the page"
    assert sorted(p.name for p in (lb.root / "attachments").iterdir()) == files_before
    assert lb.meta["head"] == head, "nothing written to the record"
    assert "13 June 2026 · memory" in page, "the caption: the day and the lane"


# -- the edges ---------------------------------------------------------------------------------------------


def test_print_needs_html_and_a_year_outside_the_record_still_has_a_cover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch)
    for command in (["year", "2026"], ["trip", "2026-06-16"]):
        with pytest.raises(SystemExit) as e:
            cli.main([*command, "--print"])
        err = capsys.readouterr().err
        assert e.value.code == 2 and "--print" in err and "--html" in err
    out = tmp_path / "2025.html"
    assert _run(capsys, "year", "2025", "--html", str(out), "--print") == f"year 2025: wrote {out}\n"
    page = out.read_text(encoding="utf-8")
    structure(page)
    assert "<h1>2025</h1>" in page and "no days in this year" in page
    assert '<section class="spread' not in page and "No days." in page
    with pytest.raises(SystemExit) as e:
        cli.main(["trip", "2026-06-09", "--html", str(tmp_path / "x.html"), "--print"])
    assert e.value.code == 2 and "at home" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        cli.main(["year", "20x6", "--html", str(tmp_path / "x.html"), "--print"])
    assert e.value.code == 2 and "not a year" in capsys.readouterr().err
    empty = Logbook.init(tmp_path / "empty", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(empty.root))
    _run(capsys, "year", "2026", "--html", str(out), "--print")
    structure(out.read_text(encoding="utf-8"))


def test_the_persona_trip_on_paper_has_its_flights_and_the_name_from_the_owner_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    owner = lb.root / "policy" / "owner.json"
    owner.write_text('{"names": ["Ines Nordmann"], "emails": [], "phones": []}\n', encoding="utf-8")
    data = print_page.read_trip(lb, "2026-06-16")
    assert data["name"] == "Ines Nordmann"
    assert data["start"] == "2026-06-15" and [d["n"] for d in data["days"]] == list(
        range(1, len(data["days"]) + 1)
    )
    first = data["days"][0]
    assert first["flights"] and first["flights"][0]["to"] == "ZRH", "the flight out, on the leaving day"
    page = print_page.html(data)
    structure(page)
    assert '<p class="name">Ines Nordmann</p>' in page and "OSL → ZRH" in page
    assert page.count('<section class="spread day"') == len(data["days"])


# -- the map ------------------------------------------------------------------------------------------------


def test_the_map_is_drawn_from_the_points_and_says_so_without_any() -> None:
    empty = print_page.map_svg([], [], "a day with no line")
    assert "No location lines." in empty and "<svg" not in empty and "a day with no line" in empty
    one = print_page.map_svg([(59.9139, 10.7522)], [], "one point")
    assert one.count("<path") == 2 and 'class="track"' in one, "the point"
    assert "km</text>" in one, "the scale"
    track = [(59.9139 + i / 1000, 10.7522 + i / 1000) for i in range(5000)]
    marks = [{"n": 1, "lat": 59.9139, "lon": 10.7522}, {"n": 2, "lat": 59.9139, "lon": 10.7522}, {"n": 3}]
    page = print_page.map_svg(track, marks, "a long day & <its> marks")
    drawn = page.split('class="track" d="')[1].split('"')[0]
    thinned = print_page._thin(track)
    assert drawn.count(" L ") == len(thinned) - 1 <= print_page.MAX_TRACK_POINTS, "thinned to the page"
    assert thinned[-1] == track[-1] and thinned[0] == track[0], "the ends are kept"
    assert page.count('<circle class="stay"') == 1 and ">1, 2</text>" in page, "one mark for one point"
    assert "a long day &amp; &lt;its&gt; marks" in page and "<its>" not in page


# -- the layout ---------------------------------------------------------------------------------------------


def test_the_layout_fits_both_papers_and_the_stylesheet_is_built_from_it() -> None:
    for width, height in (print_layout.A4_MM, print_layout.LETTER_MM):
        assert (
            width >= print_layout.TEXT_WIDTH_MM + print_layout.MARGIN_INNER_MM + print_layout.MARGIN_OUTER_MM
        )
        assert (
            height >= print_layout.TEXT_HEIGHT_MM + print_layout.MARGIN_TOP_MM + print_layout.MARGIN_BOTTOM_MM
        )
    assert print_layout.COLUMNS * print_layout.COLUMN_MM + (print_layout.COLUMNS - 1) * print_layout.GUTTER_MM
    assert print_layout.PHOTO_ONE_MM + print_layout.CAPTION_MM <= print_layout.TEXT_HEIGHT_MM
    assert 3 * (print_layout.PHOTO_SIX_MM + print_layout.CAPTION_MM + print_layout.GUTTER_MM) <= (
        print_layout.TEXT_HEIGHT_MM + 1e-9
    )
    css = print_layout.stylesheet()
    assert f"size: {print_layout.PAGE_SIZE};" in css and "@page :left" in css and "@page cover" in css
    assert print_layout.mm(print_layout.TEXT_WIDTH_MM) in css and print_layout.pt(print_layout.BASE_PT) in css
    assert print_layout.INK in css and print_layout.FONT_TEXT in css
    assert "rem" not in css and "vh" not in css and "vw" not in css, "paper lengths: mm and pt"
    assert "break-before: page" in css and "counter(page)" in css


def test_the_docs_say_how_to_make_a_pdf() -> None:
    text = (Path(__file__).parent.parent / "docs" / "print.md").read_text(encoding="utf-8")
    assert "--print-to-pdf" in text and "--print" in text and "Save as PDF" in text
    assert "print_layout.py" in text and "A4" in text and "Letter" in text
    nav = (Path(__file__).parent.parent / "mkdocs.yml").read_text(encoding="utf-8")
    assert "print.md" in nav
