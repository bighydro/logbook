"""The owner's rule, anywhere: no number beside a person's name in anything a reader prints. The people
of `rollup people`, of `show year`, of an asset's and a place's page, of `logbook people` and its
`--priority`, `drift` and `nearby`, and of the Library's People page are names only, in the reader's
own order (most days together first): the order carries closeness, never a number. The counts stay in
each reader's JSON (SPEC §6.1), unchanged, for the readers that compute from them. A person's own page
(`show person NAME`, `people NAME`, /people/ID) keeps its days together: the page's subject.

The guard (`name_guard`) runs over the text of every reader `tests/test_no_network.py` lists and the
pages it writes, the `show`, `rollup`, `day`, `trip`, `year` and `people` readers, `export letter`, and
every Library page reached from its doors, matched on every canonical, first and last name of the
record's directory. On the demo record: thirty days of the Oslo persona, who does not exist."""

from __future__ import annotations

import html
import json
import re
import sys
import types
from collections import deque
from pathlib import Path

import name_guard
import pytest
from policy_entry import allow
from test_no_network import INSTALLED, OUT, PAGES, READERS

from logbook import cli
from logbook.contrib import dream, journeys, serve
from logbook.core import people
from logbook.core.store import Logbook

DAYS = tuple(f"2026-06-{d:02d}" for d in range(1, 31))
# the rows `show DAY` prints for a call and a mail are the conformance fixtures' own
# (conformance/profiles/call/show.txt, conformance/profiles/mail/show.txt): frozen until the tag
PINNED = re.compile(r"^\s*\d{2}:\d{2}\s+(?:call\s+ios-calls\s+[←→]|mail\s+mail\s+✉)")
OWN = (("show", "person", "Ola Nordmann"), ("people", "Ola Nordmann"), ("people", "Per Hansen"))
TEXT_READERS: tuple[tuple[str, ...], ...] = (
    *(r for r in READERS if "--json" not in r and "BACKUPS" not in r),
    *(("show", d) for d in DAYS),
    *(("day", d) for d in DAYS),
    *(("digest", d) for d in DAYS),
    ("show", "asset", "nordlys"),
    *(("show", "place", p) for p in ("Cabin", "Marina", "Office", "Home")),
    ("show", "year", "2026"),
    ("show", "year", "2026", "--html", OUT),
    ("show", "stats", "--people"),
    *(("show", "trip", d) for d in ("2026-06-06", "2026-06-09", "2026-06-17", "2026-06-25")),
    ("show", "timeline", "--week", "2026-W25"),
    ("show", "timeline", "--month", "2026-06"),
    ("show", "timeline", "--year", "2026"),
    ("show", "timeline", "--life"),
    *(("rollup", w) for w in ("countries", "flights", "nights", "places", "people", "money", "health")),
    *(("rollup", w) for w in ("attention", "listen", "ledger")),
    ("rollup", "places", "--with"),
    ("rollup", "people", "--year", "2026"),
    ("rollup", "people", "--drifting", "--since", "2026-06-01", "--until", "2026-06-30", "--min-contacts", "1"),  # noqa: E501
    ("people",),
    ("people", "--priority"),
    ("people", "drift"),
    ("people", "drift", "--min-days", "1", "--quiet-days", "1", "--show"),
    *(("people", "nearby", p) for p in ("Cabin", "Office", "Marina", "Home")),
    ("people", "city", "Zurich"),
    *OWN,
    ("search", "ola"),
    ("search", "kari"),
)  # fmt: skip
SEEDS = (*PAGES, "/people", "/shelves", "/promises", "/search?q=ola", "/search?q=per", "/search?q=nordmann")
HREF = re.compile(r"""href\s*=\s*["']([^"']*)["']""", re.I)


@pytest.fixture(scope="module")
def record(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    root = tmp_path_factory.mktemp("demo") / "Demo"
    cli.main(["demo", "--days", "30", "--seed", "7", "--out", str(root)])
    allow(root, "hermes", 2)
    return Logbook(root)


@pytest.fixture
def lb(record: Logbook, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    monkeypatch.setenv("LOGBOOK_HOME", str(record.root))
    return record


@pytest.fixture(scope="module")
def names(record: Logbook) -> list[str]:
    found = name_guard.names_of(record)
    assert {"Per Hansen", "Per", "Hansen", "Ola Nordmann", "Ola", "Nordmann", "Sigrid Moen"} <= set(found)
    return found


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    capsys.readouterr()
    code = cli.main(list(argv))
    out, err = capsys.readouterr()
    assert code in (0, None), (argv, code, err)
    return out


# -- the guard -----------------------------------------------------------------------------------------------


def test_the_guard_reads_attributes_rows_and_every_separator() -> None:
    names = ["Ola Nordmann", "Ola", "Nordmann", "Per Hansen", "Per", "Hansen"]

    def found(text: str) -> bool:
        return bool(name_guard.beside(text, names))

    for said in (
        "Ola · 3",
        "Ola (3)",
        "Ola: 3",
        "Ola ×3",
        "Ola, 3",
        "Ola - 3",
        "Ola \u2013 3",
        "Ola — 3",
        "Ola / 3",
        "Ola | 3",
        "Ola; 3",
        "Ola = 3",
        "Ola • 3",
        "Ola. 3",
        "Ola's 3",
        "Ola\u2019s 3",
        "3 · Ola",
        "3 messages with Ola",
        "OLA NORDMANN 3",
        "nordmann: 3",
        "per 3",
        "Ola 19:30",
    ):
        assert found(said), said  # fmt: skip
    assert found("<table><tr><td>Ola</td>\n<td>3</td></tr></table>"), "a row's cells read together"
    assert found('<a title="Ola Nordmann (3)" href="/x">x</a>') and found('<img alt="Per Hansen, 12">')
    assert found('<li data-who="Ola · 4 days">x</li>') and found('<svg aria-label="Per Hansen 19:30"></svg>')
    assert found('<li><p class="head"><b>Per Hansen</b></p>\n<p>10 days together</p></li>'), "one item"
    assert not found("with  Ola Nordmann · Per Hansen") and not found("Olav 3") and not found("3 Perth")
    assert not found("<li>12:00</li><li>Per Hansen</li>"), "an item's end is not crossed"
    assert not found('<p title="12:00">Per Hansen</p>'), "an attribute is its own block"
    assert not found("Ola Nordmann, 2026-06-17") and not found("week 2026-W25 · Ola Nordmann")
    assert not found('<a class="raw" href="/line/x">#12</a> Ola Nordmann')


# -- the readers ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("argv", TEXT_READERS, ids=lambda argv: " ".join(argv))
def test_no_reader_prints_a_number_beside_a_name(
    argv: tuple[str, ...],
    lb: Logbook,
    names: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in INSTALLED.get(argv, ()):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    page = tmp_path / "page.html"
    capsys.readouterr()
    cli.main([str(page) if arg == OUT else arg for arg in argv])
    out = capsys.readouterr().out
    found = [row for row in name_guard.beside(out, names, html_page=False) if not PINNED.match(row)]
    assert found == [], found
    if page.is_file():
        found = name_guard.beside(page.read_text(encoding="utf-8"), names, html_page=True)
        assert found == [], found


def test_a_letter_names_its_people_with_no_number_beside_them(
    lb: Logbook, names: list[str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "letter"
    run(capsys, "export", "letter", DAYS[0], DAYS[-1], "--out", str(out), "--include-unsigned")
    pages = [p for p in out.rglob("*") if p.suffix in (".html", ".md")]
    assert pages
    for p in pages:
        text = p.read_text(encoding="utf-8")
        assert name_guard.beside(text, names, html_page=p.suffix == ".html") == [], p.name


def test_the_people_are_names_only_in_the_reader_s_order(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    order = ["Per Hansen", "Liv Berg", "Ola Nordmann", "Anders Vik", "Jonas Weber", "Marta Keller",
             "Sigrid Moen",
             "Freja Lund"]  # fmt: skip
    rows = run(capsys, "rollup", "people").splitlines()
    assert [r.strip() for r in rows[2:]] == order, rows
    year = run(capsys, "show", "year", "2026").splitlines()
    at = year.index("  people        by days together")
    assert [r.strip() for r in year[at + 1 : at + 1 + len(order)]] == order, year[at:]
    assert (
        "  with  Anders Vik, Ola Nordmann, Sigrid Moen"
        in run(capsys, "show", "asset", "nordlys").splitlines()
    )
    assert "  with  Ola Nordmann" in run(capsys, "show", "place", "Cabin").splitlines()
    priority = [r.strip() for r in run(capsys, "people", "--priority").splitlines()[1:] if r.strip()]
    assert priority[:3] == ["Per Hansen", "Liv Berg", "Ola Nordmann"], priority
    listed = [r.strip() for r in run(capsys, "people").splitlines()[1:] if r.strip()]
    assert listed[:3] == ["Per Hansen", "Liv Berg", "Ola Nordmann"], listed
    nearby = run(capsys, "people", "nearby", "Office")
    assert nearby.index("Per Hansen") < nearby.index("Liv Berg") and "days there" not in nearby, nearby


def test_the_json_keeps_every_count(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    (year,) = json.loads(run(capsys, "rollup", "people", "--json"))["years"]
    per = year["people"][0]
    assert per["name"] == "Per Hansen" and (per["days"], per["nights"], per["confirmed"]) == (10, 0, 11), per
    data = json.loads(run(capsys, "show", "year", "2026", "--json"))
    assert data["people"][0]["days"] == 10, data["people"][0]
    asset = json.loads(run(capsys, "show", "asset", "nordlys", "--json"))
    assert {p["name"]: p["days"] for p in asset["people"]}["Anders Vik"] == 2, asset["people"]
    ranked = json.loads(run(capsys, "people", "--priority", "--json"))
    assert ranked["people"][0]["name"] == "Per Hansen" and ranked["people"][0]["score"] > 0, ranked["people"][
        0
    ]


def test_a_person_s_own_page_keeps_the_days_together(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    assert "days together" in run(capsys, "show", "person", "Ola Nordmann")
    assert "3 days together" in run(capsys, "people", "Ola Nordmann")
    ola = people.find("Ola Nordmann", people.directory(lb)).entity
    page = serve.Site(lb).respond(f"/people/{ola}", "").body.decode("utf-8")
    assert "days together" in page


# -- the Library ---------------------------------------------------------------------------------------------


def _target(path: str, lb: Logbook) -> str:
    if path == "/journeys/FIRST/LAST":
        trip = journeys.shelf(lb, "2026").journeys[0].trip
        return f"/journeys/{trip.start}/{trip.end}"
    if path == "/people/ID":
        return f"/people/{people.find('Ola Nordmann', people.directory(lb)).entity}"
    if path == "/line/ID":
        with lb.index() as idx:
            return f"/line/{idx.day('2026-06-08')[0]['id']}"
    return path


def test_no_library_page_puts_a_number_beside_a_name(lb: Logbook, names: list[str]) -> None:
    """Every page the Library serves, from the doors `tests/test_no_network.py` lists and the People
    page, through every link on every page: the people pages, each journey, each day, each search."""
    site = serve.Site(lb)
    queue, seen, found = deque(_target(p, lb) for p in SEEDS), set(), {}
    while queue:
        target = queue.popleft()
        if target in seen:
            continue
        seen.add(target)
        path, _, query = target.partition("?")
        page = site.respond(path, query)
        if page.status != 200 or not page.content_type.startswith("text/html"):
            continue
        body = page.body.decode("utf-8")
        if hits := name_guard.beside(body, names, html_page=True):
            found[target] = hits
        for href in HREF.findall(body):
            href = html.unescape(href).partition("#")[0]
            if href.startswith("/") and not href.startswith("//") and href not in seen:
                queue.append(href)
    assert len(seen) > 300 and "/people" in seen and any(s.startswith("/people/") for s in seen)
    assert found == {}, found


def test_a_search_excerpt_shows_the_name_and_the_words_never_an_address(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    out = run(capsys, "search", "landed")
    assert "Landed?" in out and "+44" not in out and "@example.org" not in out, out
    body = serve.Site(lb).respond("/search", "q=landed").body.decode("utf-8")
    assert "Landed?" in body and "+44" not in body and "7700900" not in body, body


def test_the_dream_holds_a_sentence_that_puts_a_number_beside_any_name_of_the_directory() -> None:
    made = dream.Material(
        "2026-06-17", 1, 0, "", "", "en", {}, canonical={"e1": "Per Hansen", "e2": "Ola Nordmann"}
    )
    for said in (
        "Lunch with per hansen, 3 courses.",
        "Hansen: 4.",
        "Lunch with Per at 19:30.",
        "Ola Nordmann's 3 photos.",
        "3 messages with Ola.",
    ):
        assert dream.beside_a_name(said, made), said  # fmt: skip
    assert not dream.beside_a_name("Lunch with Per Hansen at the cafe.", made)
    assert not dream.beside_a_name("Three hours at the Office on 2026-06-17.", made)
