"""`logbook digest --paper [--week YYYY-Www] [--html PATH]`: the week as a four-page A4 paper — the
days with their one line each, the people confirmed, the week's keepers, the promises due, what
was read (the browse lines, titles only) — set from the Year's typographic constants. The demo
record's yacht week is a fixture; every document is checked structurally. The Oslo persona does
not exist."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from logbook.store import Logbook
from paper import structure
from persona import TZ, note, persona_record, utc

from logbook import cli, demo, gaps, print_layout
from logbook.contrib import week_paper

FIXTURES = Path(__file__).parent / "fixtures" / "demo"
WEEK = "2026-W25"  # 15 to 21 June: the demo's yacht week
EN_DASH = "\u2013"


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(list(args))
    return capsys.readouterr().out


@pytest.fixture(scope="module")
def record(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    root = tmp_path_factory.mktemp("demo") / "Demo"
    cli.main(["demo", "--days", "30", "--seed", "7", "--out", str(root)])
    return Logbook(root)


@pytest.fixture
def lb(record: Logbook, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    monkeypatch.setenv("LOGBOOK_HOME", str(record.root))
    return record


def paper(page: str) -> list[str]:
    """The document is the week's paper: four pages, each a section with its heading, A4 pinned,
    the Year's stylesheet; the pages' HTML in order."""
    s = structure(page)
    assert (
        s.tags["section"] == print_layout.PAPER_PAGES
        and s.classes("section")["page"] == print_layout.PAPER_PAGES
    )
    assert f"size: {print_layout.PAPER_SHEET};" in page and "counter(page)" in page
    assert (
        print_layout.mm(print_layout.TEXT_WIDTH_MM) in page and print_layout.pt(print_layout.BASE_PT) in page
    )
    pages = page.split('<section class="page"')[1:]
    assert [p.split("<h2>")[1].split("</h2>")[0] for p in pages] == [
        "The week",
        "With",
        "Promises due",
        "Read",
    ]
    assert s.tags["h2"] == 4 and s.tags["img"] == 0
    assert '<footer class="note">' in pages[-1] and "<footer" not in "".join(pages[:-1])
    return pages


# -- the fixture -------------------------------------------------------------------------------------------


def test_the_yacht_week_is_the_fixture_on_four_pages(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "paper" / "week.html"
    assert (
        _run(capsys, "digest", "--paper", "--week", WEEK, "--html", str(out))
        == f"digest {WEEK}: wrote {out}\n"
    )
    page = out.read_bytes().decode("utf-8")
    days, with_, due, read = paper(page)
    assert f"<title>{WEEK} · Logbook</title>" in page
    assert f"15{EN_DASH}21 June 2026" in days and "ines.nordmann@example.org" in days, "the week, the name"
    assert days.count('<li class="day"') == 7 and "Monday 15 June" in days and "Sunday 21 June" in days
    assert days.count(f"aboard {demo.BOAT_NAME}") == 6 and "Home" in days, "the night of each day"
    assert "47.2 km" in days and "2 stays (2 attached)" in days and "sleep 6.2 h" in days, "the one line"
    assert "Ola Nordmann" in with_ and "Anders Vik" in with_, "the crew confirmed on the leaving day"
    assert "Sigrid Moen" not in with_, "an attendee of the calendar entry, never confirmed present"
    assert "<h3>Keepers</h3>" in with_ and "memory" in with_ and "not in the record" not in with_
    assert '<dd class="empty">' in due or '<p class="muted">none due' in due, "the demo makes no promise"
    assert "Fish soup for a crowd" in read and "The bowline, step by step" in read, "titles"
    assert "example.org/" not in read and "safari" not in read, "titles only: never a URL, never a source"
    assert read.count("<h3>") >= 5, "a day a heading, the days with nothing read left out"
    assert '<footer class="note">' in read and lb.meta["head"][:12] in read
    fixture = (FIXTURES / f"paper_week_{WEEK}.html").read_text(encoding="utf-8")
    fixture_pages = paper(fixture)
    assert [p.count('<li class="day"') for p in fixture_pages] == [7, 0, 0, 0]
    assert page.splitlines()[:40] == fixture.splitlines()[:40], "the head of the fixture is current"
    assert str(lb.root) not in page


def test_the_paper_goes_to_stdout_and_as_json(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    page = _run(capsys, "digest", "--paper", "--week", WEEK)
    paper(page)
    assert page == week_paper.html(week_paper.read(lb, WEEK))
    data = json.loads(_run(capsys, "digest", "--paper", "--week", WEEK, "--json"))
    assert data["kind"] == "paper" and data["week"] == WEEK
    assert data["first"] == "2026-06-15" and data["last"] == "2026-06-21"
    assert [d["day"] for d in data["days"]] == [f"2026-06-{n}" for n in range(15, 22)]
    assert all(set(d) >= {"day", "weekday", "night", "line", "people"} for d in data["days"])
    assert data["days"][1]["line"].startswith("2026-06-16  Tue  aboard"), "the line `days` prints"
    assert {p["name"] for p in data["people"]} >= {"Ola Nordmann", "Anders Vik"}
    assert all(p["days"] >= 1 for p in data["people"])
    assert data["keepers"] and all(set(k) == {"day", "lane", "name"} for k in data["keepers"])
    assert data["promises"] == []
    assert data["read"] and all(set(r) == {"day", "title"} for r in data["read"])
    assert all("http" not in r["title"] for r in data["read"])
    keys = (
        "kind",
        "week",
        "first",
        "last",
        "name",
        "head",
        "tz",
        "days",
        "people",
        "keepers",
        "promises",
        "read",
    )
    assert set(data) == set(keys)


# -- the week ----------------------------------------------------------------------------------------------


def test_a_week_is_iso_monday_to_sunday() -> None:
    assert week_paper.parse_week("2026-W40") == ("2026-W40", "2026-09-28", "2026-10-04")
    assert week_paper.parse_week("2026-W01") == ("2026-W01", "2025-12-29", "2026-01-04")
    assert week_paper.parse_week("2026-W53")[1:] == ("2026-12-28", "2027-01-03"), "2026 has 53 weeks"
    assert week_paper.week_of("2026-06-17") == "2026-W25" and week_paper.week_of("2027-01-01") == "2026-W53"
    for bad in ("2026-W54", "2026-W00", "2026-40", "W40", "2026-W4", "2026-w40", "x"):
        with pytest.raises(ValueError):
            week_paper.parse_week(bad)


def test_the_promises_due_in_the_week_and_the_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    lb.append_many(
        [
            note(
                utc("2026-06-09", "19:00"),
                "Long day. I'll send Ola the mooring photos by Friday."
                " I need to renew the insurance by July 20.",
            )
        ]
    )
    page = _run(capsys, "digest", "--paper", "--week", "2026-W24")
    _days, with_, due, read = paper(page)
    assert "mooring photos by Friday" in due and "2026-06-12" in due and "insurance" not in due
    assert "Kari Nordmann" in with_ or "Ola Nordmann" in with_
    assert '<p class="muted">nothing read' in read, "the persona browses nothing"
    data = week_paper.read(lb, "2026-W30")
    assert [p["due"]["date"] for p in data["promises"]] == ["2026-07-20"]
    assert data["days"][0]["line"].endswith("nothing logged") and data["people"] == [] and data["read"] == []
    real_now = gaps.now()
    monkeypatch.setattr(gaps, "now", lambda: real_now.replace(2026, 6, 17))
    page = _run(capsys, "digest", "--paper")
    assert "<title>2026-W25 · Logbook</title>" in page, "this week, by the record's clock"
    page = _run(capsys, "digest", "2026-06-09", "--paper")
    assert "<title>2026-W24 · Logbook</title>" in page, "the week of the day"
    for args in (
        ["digest", "--week", "2026-W24"],
        ["digest", "--paper", "--week", "2026-W99"],
        ["digest", "--paper", "--week", "2026-W24", "--markdown"],
        ["digest", "2026-06-09", "--paper", "--week", "2026-W24"],
    ):
        with pytest.raises(SystemExit) as e:
            cli.main(args)
        assert e.value.code == 2, args
        assert capsys.readouterr().err.startswith("digest:")
    empty = Logbook.init(tmp_path / "empty", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(empty.root))
    paper(_run(capsys, "digest", "--paper", "--week", "2026-W24"))


def test_the_docs_say_how_to_print_the_week() -> None:
    text = (Path(__file__).parent.parent / "docs" / "print.md").read_text(encoding="utf-8")
    assert "--paper" in text and "--week" in text and "2026-W40" in text
    digest = (Path(__file__).parent.parent / "docs" / "digest.md").read_text(encoding="utf-8")
    assert "--paper" in digest
