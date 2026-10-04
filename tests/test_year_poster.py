"""`logbook year YYYY --poster [--sheet A2|A3] [--html PATH]`: the year on one sheet — twelve
columns of thirty-one squares, one a day, each in the ink of its night (home, away, aboard, in
transit: the four tokens of `print_layout`), the countries of the year as a footer line, no name
of anyone or anything, nothing fetched. The demo record's 2026 is a fixture on both sheets; every
document is checked structurally. The Oslo persona does not exist."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
from logbook.store import Logbook
from paper import structure
from persona import TZ, persona_record

from logbook import cli, demo, print_layout
from logbook.contrib import year_poster

FIXTURES = Path(__file__).parent / "fixtures" / "demo"
NAMES = ("Nordlys", "Nordmann", "Ines", "Ola", "Marta", "example.org", "07700", "Home", "Office", "Zürich")


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


def poster(page: str, sheet: str, days: int) -> dict[str, int]:
    """The document is a poster: one SVG the size of the sheet, a square a day in one of the five
    classes, the legend's four tokens, the footer; the squares by class."""
    s = structure(page)
    assert s.tags["svg"] == 1 and s.classes("svg")["poster"] == 1, "one drawing"
    assert (
        f"size: {sheet};" in page
        and f"width: {print_layout.mm(print_layout.POSTER_SHEETS[sheet][0])}" in page
    )
    width, height = print_layout.POSTER_VIEW_MM
    assert f'viewBox="0 0 {width:g} {height:g}"' in page, "drawn in millimetres of A2, scaled to the sheet"
    squares = [attrs for tag, attrs in s.elements if tag == "rect" and "night" in str(attrs.get("class"))]
    assert len(squares) == days, "a square a day, and only those"
    seen = {str(a["data-day"]) for a in squares}
    assert len(seen) == days and all(re.fullmatch(r"\d{4}-\d\d-\d\d", d) for d in seen)
    by_class: dict[str, int] = {}
    for a in squares:
        classes = str(a["class"]).split()
        assert classes[0] == "night" and len(classes) == 2, classes
        assert classes[1] in (*print_layout.NIGHTS, print_layout.NIGHT_NONE), classes
        by_class[classes[1]] = by_class.get(classes[1], 0) + 1
    for token in print_layout.NIGHTS:
        assert f'class="legend {token}"' in page and print_layout.NIGHT_LABEL[token] in page, token
        assert f".night.{token} {{ fill: {print_layout.NIGHT_INK[token]}; }}" in page
    assert page.count('class="legend ') == len(print_layout.NIGHTS), "the legend is the four tokens"
    assert 'class="countries"' in page, "the footer line"
    for month in ("Jan", "Feb", "Dec"):
        assert f">{month}</text>" in page, "a month a column"
    assert ">1</text>" in page and ">31</text>" in page, "a day a row"
    return by_class


# -- the fixtures ------------------------------------------------------------------------------------------


def test_the_demo_year_is_a_poster_on_a2_and_a3(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for sheet in ("A2", "A3"):
        out = tmp_path / "poster" / f"2026-{sheet}.html"
        text = _run(capsys, "show", "year", "2026", "--poster", "--sheet", sheet, "--html", str(out))
        assert text == f"year 2026: wrote {out}\n"
        page = out.read_bytes().decode("utf-8")
        counts = poster(page, sheet, 365)
        assert counts == {"home": 18, "away": 6, "aboard": 6, "none": 335}, "June: 30 nights, the rest empty"
        assert "<title>2026 · Logbook</title>" in page and 'class="year"' in page and ">2026</text>" in page
        footer = page.split('class="countries"')[1].split("</text>")[0]
        assert "NO" in footer and "CH" in footer and "DK" in footer, "the year's countries"
        assert "25" in footer and "days" in footer
        for name in NAMES:
            assert name not in page, f"no names on a poster: {name}"
        assert str(lb.root) not in page
        fixture = (FIXTURES / f"poster_year_2026_{sheet}.html").read_text(encoding="utf-8")
        assert poster(fixture, sheet, 365) == counts, "the fixture is the same poster, structurally"
        assert page.splitlines()[:40] == fixture.splitlines()[:40], "the head of the fixture is current"


def test_the_poster_goes_to_stdout_without_html_and_a2_is_the_sheet(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    page = _run(capsys, "show", "year", "2026", "--poster")
    assert poster(page, "A2", 365)["aboard"] == 6
    assert page == year_poster.html(year_poster.read(lb, "2026"), "A2")


def test_the_reading_names_every_day_and_counts_the_tokens(lb: Logbook) -> None:
    data = year_poster.read(lb, "2026")
    assert data["kind"] == "poster" and data["year"] == "2026" and data["head"] == lb.meta["head"]
    assert data["window"] == {"since": "2026-06-01", "until": "2026-06-30", "days": 30}
    assert [d["day"] for d in data["days"]][:2] == ["2026-01-01", "2026-01-02"] and len(data["days"]) == 365
    nights = {d["day"]: d["night"] for d in data["days"]}
    assert (
        nights["2026-01-01"] is None and nights["2026-06-15"] == "aboard" and nights["2026-06-21"] == "home"
    )
    assert data["counts"] == {"home": 18, "away": 6, "aboard": 6, "transit": 0, "none": 335}
    assert [c["country"] for c in data["countries"]] == ["NO", "CH", "DK"]
    assert data["countries"][0]["days"] == 25 and data["in_transit"] == 0 and data["unknown"] == 0
    assert set(data) == {
        "kind",
        "year",
        "head",
        "window",
        "days",
        "counts",
        "countries",
        "in_transit",
        "unknown",
    }


# -- the edges ---------------------------------------------------------------------------------------------


def test_a_year_outside_the_record_is_an_empty_grid_and_a_leap_year_has_366(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch)
    page = _run(capsys, "show", "year", "2025", "--poster")
    assert poster(page, "A2", 365) == {"none": 365}
    assert "no days in this year" in page
    page = _run(capsys, "show", "year", "2028", "--poster", "--sheet", "A3")
    assert poster(page, "A3", 366) == {"none": 366} and 'data-day="2028-02-29"' in page
    page = _run(capsys, "show", "year", "2026", "--poster")
    counts = poster(page, "A2", 365)
    assert counts["aboard"] >= 1 and counts["away"] >= 3, "the persona's fjord weekend and Zürich"
    assert "Solvind" not in page and "Kari" not in page
    empty = Logbook.init(tmp_path / "empty", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(empty.root))
    assert poster(_run(capsys, "show", "year", "2026", "--poster"), "A2", 365) == {"none": 365}


def test_the_flags_refuse_what_they_cannot_do(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch)
    with pytest.raises(SystemExit) as e:
        cli.main(["show", "year", "2026", "--poster", "--print", "--html", str(tmp_path / "x.html")])
    assert e.value.code == 2 and "--poster" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        cli.main(["show", "year", "20x6", "--poster"])
    assert e.value.code == 2 and "not a year" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        cli.main(["show", "year", "2026", "--poster", "--sheet", "A1"])
    assert e.value.code == 2
    with pytest.raises(SystemExit) as e:
        cli.main(["show", "year", "2026", "--sheet", "A3"])
    assert e.value.code == 2 and "--poster" in capsys.readouterr().err
    with pytest.raises(KeyError):
        year_poster.html(year_poster.read(Logbook.find(), "2026"), "A1")


# -- the layout ---------------------------------------------------------------------------------------------


def test_the_grid_fits_the_sheet_and_the_tokens_are_four() -> None:
    width, height = print_layout.POSTER_VIEW_MM
    grid_w, grid_h = print_layout.POSTER_GRID_MM
    assert grid_w + 2 * print_layout.POSTER_MARGIN_MM + print_layout.POSTER_LABEL_MM <= width
    assert (
        grid_h + 2 * print_layout.POSTER_MARGIN_MM + print_layout.POSTER_HEAD_MM + print_layout.POSTER_FOOT_MM
        <= height + 1e-9
    )
    assert print_layout.POSTER_SQUARE_MM > 5, "a square is a square, not a line"
    for sheet, (w, h) in print_layout.POSTER_SHEETS.items():
        assert abs(w / h - width / height) < 1e-3, f"{sheet} keeps the A proportions"
        css = print_layout.poster_stylesheet(sheet)
        assert f"size: {sheet};" in css and print_layout.mm(w) in css and print_layout.mm(h) in css
        assert "rem" not in css and "vh" not in css and "vw" not in css, "sheet lengths"
        assert print_layout.vu(print_layout.POSTER_TYPE_MM["year"]) in css, "type in the drawing's own units"
        assert css.count("px") == 5, "a user unit of the drawing is the only px: the five type sizes"
    assert len(print_layout.NIGHTS) == 4 and set(print_layout.NIGHT_INK) == set(print_layout.NIGHTS)
    assert set(print_layout.NIGHT_LABEL) == set(print_layout.NIGHTS)
    assert len({*print_layout.NIGHT_INK.values(), print_layout.FRAME}) == 5, "five fills, all different"
    assert date(2026, 1, 1).isoformat() == year_poster.grid_days("2026")[0]["day"]
    assert demo.START.year == 2026


def test_the_docs_say_how_to_print_the_poster() -> None:
    text = (Path(__file__).parent.parent / "docs" / "print.md").read_text(encoding="utf-8")
    assert "--poster" in text and "A2" in text and "A3" in text and "--sheet" in text
