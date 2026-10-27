"""No number beside a person's name in anything a reader prints (RFC 0043 §2.5, VISION: no metrics near
people), past the drafts #394 fixed: `rollup people`, `show year`'s people, `show asset`'s and `show
place`'s with, and the Library's People page name their people only, in the reader's order, the most
days together first: the order carries the closeness, never a number. The counts stay in `--json`
(SPEC §6.1), unchanged, for the readers that compute from them. Then the strong guard
(`beside_a_name`) over every `show`, `rollup`, `day`, `trip` and `year` reader and every Library page,
on the demo record (thirty days, seed 7; the Oslo persona and her people, who do not exist). A person's
own page (`show person`, /people/ID) may say how many days together: that one person is its subject."""

from __future__ import annotations

import contextlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import beside_a_name
import pytest
from test_library_walk import _walk

from logbook import cli
from logbook.contrib import demo, serve
from logbook.core.store import Logbook

DAYS = [f"2026-06-{d:02d}" for d in range(1, 31)]
JULY = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)  # the morning after the record's last day
SEEDS = (  # the Library from its front door and from every shelf, as `test_library_walk` walks it
    "/", "/shelves", "/days", "/trips", "/places", "/assets", "/gaps", "/world", "/journeys", "/people",
    "/manifest", "/manifest/people", "/ideas", "/promises", "/goals", "/search?q=ola", "/agents",
    "/week/2026-W25", "/timeline", f"/day/{DAYS[7]}", f"/day/{DAYS[7]}?open=1",
)  # fmt: skip


@pytest.fixture(scope="module")
def record(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    root = tmp_path_factory.mktemp("demo") / "Demo"
    cli.main(["demo", "--days", "30", "--seed", "7", "--out", str(root)])
    return Logbook(root)


@pytest.fixture
def lb(record: Logbook, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    monkeypatch.setenv("LOGBOOK_HOME", str(record.root))
    return record


def _run(*args: str) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = cli.main(list(args))
    assert code in (0, None), args
    return out.getvalue()


def _json(*args: str) -> Any:
    return json.loads(_run(*args, "--json"))


def test_the_guard_finds_a_count_a_date_or_a_clock_beside_a_name_and_lets_a_word_between_be() -> None:
    assert beside_a_name.rows("        Eva Nordmann             2026-06-12         messages, calls")
    assert beside_a_name.rows("  due  Kari Nordmann, 2026-06-05") and beside_a_name.rows("14:00 Ola Nordmann")
    assert beside_a_name.rows("Ola Nordmann promised you · since 8 June") == [], "a word between"
    assert beside_a_name.rows("with Ola Nordmann at 14:00") == [], "a word between"
    assert beside_a_name.rows("        Per Hansen               10 days · 0 nights · 11 confirmed")
    assert beside_a_name.rows("  with  Anders Vik (2 days), Ola Nordmann (2 days)")
    assert beside_a_name.rows("        Marta Keller                   4      0  -100%  21 days ago")
    assert beside_a_name.rows("  with  Anders Vik, Ola Nordmann, Sigrid Moen") == []
    assert beside_a_name.rows("        Per Hansen               last 2026-06-30 · Office") == []
    row = '<li><p class="head"><b>Per Hansen</b></p>\n<p class="facts">10 days together</p></li>'
    assert beside_a_name.page(row) == ["Per Hansen · 10 days together"], "a row's head and its facts"
    folded = (
        "<li><b>Per Hansen</b><details><summary>evidence</summary><ol><li>1 photo</li></ol></details></li>"
    )
    assert beside_a_name.page(folded) == [], "a row inside a row is a row of its own"
    assert (
        beside_a_name.page('<li><b>Liv Berg</b> <span class="id" title="line x">…c2955c12</span></li>') == []
    )
    assert beside_a_name.page("<tr><td>Marina</td><td>27</td><td>Anders Vik</td></tr>"), "a table row"


# -- the readers the stranger test found ---------------------------------------------------------------------


def test_rollup_people_names_its_people_only_the_most_days_first(lb: Logbook) -> None:
    out = _run("rollup", "people")
    data = _json("rollup", "people")
    (year,) = data["years"]
    order = [p["name"] for p in [*year["people"], *year["unresolved"]]]
    assert order[:3] == ["Per Hansen", "Liv Berg", "Ola Nordmann"], "the most days together first"
    rows = out.splitlines()[2:]
    assert [r.strip()[: len(n)] for r, n in zip(rows, order, strict=True)] == order, "in the reader's order"
    assert rows[0] == "        Per Hansen               last 2026-06-30 · Office", rows[0]
    assert beside_a_name.rows(out) == [], beside_a_name.rows(out)
    assert "confirmed" not in out and " days" not in out and " nights" not in out, out
    per = year["people"][0]
    assert (per["name"], per["days"], per["nights"], per["confirmed"]) == ("Per Hansen", 10, 0, 11), (
        "the counts stay in the JSON, unchanged"
    )


def test_show_year_names_its_people_only_and_keeps_the_counts_in_its_json(
    lb: Logbook, tmp_path: Path
) -> None:
    out = _run("show", "year", "2026")
    head = out.splitlines().index("  people        by days together")
    rows = out.splitlines()[head + 1 : head + 9]
    assert [r.split()[0] + " " + r.split()[1] for r in rows] == [
        "Per Hansen", "Liv Berg", "Ola Nordmann", "Anders Vik",
        "Jonas Weber", "Marta Keller", "Sigrid Moen", "Freja Lund",
    ]  # fmt: skip
    assert rows[0] == f"    {'Per Hansen':<43} last 2026-06-30 · Office", rows[0]
    assert beside_a_name.rows(out) == [], beside_a_name.rows(out)
    people = _json("show", "year", "2026")["people"]
    assert (people[0]["days"], people[0]["nights"]) == (10, 0), "the counts stay in the JSON"
    for flags in ((), ("--print",), ("--poster",)):  # the year's page, its paper edition and its poster
        page = tmp_path / f"year{''.join(flags)}.html"
        _run("show", "year", "2026", "--html", str(page), *flags)
        text = page.read_text(encoding="utf-8")
        assert ("Per Hansen" in text) is (flags != ("--poster",)), "the poster names nobody"
        assert beside_a_name.page(text) == [], (flags, beside_a_name.page(text))


def test_show_asset_and_show_place_name_who_was_aboard_and_there_without_their_days(lb: Logbook) -> None:
    out = _run("show", "asset", "nordlys")
    assert "  with  Anders Vik, Ola Nordmann, Sigrid Moen\n" in out, out
    assert "  with  Ola Nordmann\n" in _run("show", "place", "Cabin")
    assert "  with  Per Hansen, Liv Berg\n" in _run("show", "place", "Office")
    for args in (("asset", "nordlys"), ("place", "Cabin"), ("place", "Office"), ("place", "Marina")):
        assert beside_a_name.rows(_run("show", *args)) == [], args
    asset = _json("show", "asset", "nordlys")
    assert [(p["name"], p["days"]) for p in asset["people"]] == [
        ("Anders Vik", 2), ("Ola Nordmann", 2), ("Sigrid Moen", 1)
    ], "the counts stay in the JSON, the order with them"  # fmt: skip
    assert [(p["name"], p["days"]) for p in _json("show", "place", "Cabin")["people"]] == [
        ("Ola Nordmann", 2)
    ]


def test_the_people_page_names_its_people_only_the_most_days_first(lb: Logbook) -> None:
    site = serve.Site(lb, now=lambda: JULY)
    page = site.respond("/people", "")
    assert page.status == 200
    body = page.body.decode("utf-8")
    found = beside_a_name.page(body)
    assert found == [], found
    rows = [r for r in beside_a_name.page_rows(body) if r.startswith(("Per Hansen ·", "Liv Berg ·"))]
    assert rows[0].startswith("Per Hansen · last real contact 2026-06-30"), rows
    assert body.index("Per Hansen") < body.index("Liv Berg") < body.index("Ola Nordmann"), "the order"
    shelf = body.split('id="review"')[0]  # the people the record names; the review queue below
    assert " together</p>" not in shelf and "under one roof" not in shelf
    assert "<summary>evidence</summary>" in shelf and "evidence · " not in shelf, "the evidence uncounted"
    assert "<summary>… and more</summary>" in shelf and " more</summary>" not in shelf.replace(
        "<summary>… and more</summary>", ""
    ), "the evidence past the first rows is folded, uncounted: its count followed the days together"


# -- the strong guard, over every reader ---------------------------------------------------------------------

# the rows left as they are, each for its reason: never a person's count of anything
LEFT = (
    # `show DAY`'s call and mail rows (`← who, 7 min, cellular`, `✉ subject — a → b (1 attachment)`):
    # the conformance fixtures' own (conformance/profiles/call/show.txt, mail/show.txt), frozen to the tag
    lambda args, row: args[0] == "show" and args[1][:1] == "2" and ("ios-calls " in row or " mail  " in row),
)


def _readers(lb: Logbook) -> list[tuple[str, ...]]:
    """Every `show`, `rollup`, `day`, `trip` and `year` reader of the demo record, in text."""
    trips = [t["id"] for t in _json("show", "trips")["trips"]]
    readers: list[tuple[str, ...]] = []
    for day in DAYS:
        readers += [("day", day), ("show", day), ("show", day, "--raw")]
    readers += [("show", "trip", t) for t in trips]
    readers += [("show", "year", "2026"), ("show", "trips"), ("show", "days"), ("show", "keepers")]
    readers += [("show", "stats"), ("show", "orgs"), ("show", "ideas"), ("show", "plan")]
    readers += [("show", "timeline", f) for f in ("--life",)]
    readers += [("show", "timeline", "--year", "2026"), ("show", "timeline", "--month", "2026-06")]
    readers += [("show", "timeline", "--week", "2026-W25"), ("show", "heard", "--since", DAYS[0])]
    readers += [("show", "person", p.name) for p in demo.PEOPLE]
    readers += [
        ("show", "asset", "nordlys"),
        *(("show", "place", p) for p in ("Home", "Office", "Marina", "Cabin")),
    ]
    for what in ("countries", "flights", "nights", "places", "people", "money", "health", "attention"):
        readers.append(("rollup", what))
    readers += [("rollup", "listen"), ("rollup", "ledger"), ("rollup", "places", "--with")]
    readers += [("rollup", "people", "--drifting", "--window", str(w)) for w in (7, 14, 365)]
    return readers


def test_no_reader_prints_a_number_beside_a_name(lb: Logbook, tmp_path: Path) -> None:
    found: list[tuple[str, str]] = []
    readers = _readers(lb)
    for args in readers:
        for row in beside_a_name.rows(_run(*args)):
            if not any(left(args, row) for left in LEFT):
                found.append((" ".join(args), row))
    assert ("rollup", "people", "--drifting", "--window", "14") in readers
    for trip in [t["id"] for t in _json("show", "trips")["trips"]]:
        for flags in ((), ("--print",)):
            page = tmp_path / f"{trip.replace(':', '-')}{''.join(flags)}.html"
            _run("show", "trip", trip, "--html", str(page), *flags)
            found += [
                (f"show trip {trip} --html {' '.join(flags)}", r)
                for r in beside_a_name.page(page.read_text("utf-8"))
            ]
    assert found == [], "\n".join(f"{a} | {r}" for a, r in found)


def test_no_library_page_sets_a_number_beside_a_name(lb: Logbook) -> None:
    pages = _walk(serve.Site(lb, now=lambda: JULY), SEEDS)
    assert {"/people", "/places", "/assets", "/journeys", "/manifest"} <= set(pages)
    assert any(t.startswith("/people/") for t in pages), "a person's own page is read too"
    found = [(t, row) for t, (_status, text) in pages.items() for row in beside_a_name.page(text)]
    assert found == [], "\n".join(f"{t} | {r}" for t, r in found)


def test_rollup_places_with_keeps_two_places_of_one_label_apart() -> None:
    from logbook.core import rollup

    table = [
        {"place": "Nordlys", "label": "Nordlys", "kind": "place", "name": "Ola Nordmann"},
        {"place": "Nordlys", "label": "Nordlys", "kind": "asset", "name": "Per Hansen"},
    ]
    rows = list(rollup._with_table(table))[1:]
    assert [r.split()[-2:] for r in rows] == [["Ola", "Nordmann"], ["Per", "Hansen"]], rows
