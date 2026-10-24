"""A journey's name is held to the tier of the line that gave it (24 October, the Life door's finding):
the name is a `note/v1` line, tier 2, so a page read at tier 1 never shows it, nor anything that says
one exists — the journey shows as it would unnamed, by its dates and places — and a page read at tiers
1,2 shows it. Every reader that prints a journey's name: the Journeys shelf and one journey (`serve`,
which the Library and `export site` render), the Day page, `show trips` and `show trip`, `export
letter`'s journey units and the dream's material for a journey. On the synthetic records of
`library_record.py` and `letter_record.py` (Ines and Ola Nordmann's Oslo, example.org); nobody here
exists."""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Iterator
from datetime import UTC, datetime
from html import escape
from pathlib import Path

import pytest
from dream_fortnight import DREAM_ENTRY, fake, run_cli
from dream_fortnight import JOURNEY as ZURICH_JOURNEY
from library_record import BERGEN_WINTER, library_record
from test_dream_journey import _closed
from test_dream_journey import lb as fortnight_lb  # noqa: F401 (the fortnight at 06:00 on 18 June)

from logbook import cli
from logbook.contrib import journeys, serve
from logbook.core.store import Logbook

NAME = "Ines and Ola's Bergen winter"  # given only through its note: tier 2, as every note is
ZURICH_NAME = "Ines and Ola in Zürich"
OCTOBER = datetime(2025, 10, 20, 12, 0, tzinfo=UTC)
FIRST, LAST = BERGEN_WINTER.split(":")[1:]
ONE, ONE_TWO = (1,), (1, 2)
HEAD = re.compile(r"head <code>[0-9a-f]+…</code>")  # the footer's head moves with every line appended


@pytest.fixture(scope="module")
def pristine(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    root = tmp_path_factory.mktemp("journey-name-tier") / "lb"
    library_record(root)
    yield root


@pytest.fixture
def lb(pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    shutil.copytree(pristine, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook(root)


def _named(lb: Logbook) -> Logbook:
    line = journeys.name(lb, BERGEN_WINTER, NAME)
    assert line["tier"] == 2, "a journey's name is a note, and a note is tier 2"
    return Logbook(lb.root)


def _page(lb: Logbook, tiers: tuple[int, ...], page: str) -> str:
    path, _, query = page.partition("?")
    response = serve.Site(lb, now=lambda: OCTOBER, tiers=tiers).respond(path, query)
    assert response.status == 200, (page, response.body[:300])
    return response.body.decode("utf-8")


SHELF, JOURNEY = "/journeys?year=2022", f"/journeys/{FIRST}/{LAST}"


def test_the_journeys_reader_holds_the_name_to_its_line_s_tier(lb: Logbook) -> None:
    lb = _named(lb)
    for tiers in (ONE_TWO, None):
        (row,) = [j for j in journeys.shelf(lb, "2022", tiers=tiers).journeys if j.id == BERGEN_WINTER]
        assert row.name is not None and row.name.text == NAME, tiers
        assert journeys.read(lb, BERGEN_WINTER, tiers=tiers)["journey"]["name"]["text"] == NAME
    (row,) = [j for j in journeys.shelf(lb, "2022", tiers=ONE).journeys if j.id == BERGEN_WINTER]
    assert row.name is None, "a tier-1 reading never learns a name a tier-2 line gave"
    one = journeys.read(lb, BERGEN_WINTER, tiers=ONE)
    assert one["journey"]["name"] is None
    assert NAME not in json.dumps(one, ensure_ascii=False)


def test_the_journeys_shelf_and_page_at_tier_1_read_as_if_it_were_unnamed(lb: Logbook) -> None:
    """Withheld, the journey is the journey unnamed, byte for byte: its dates and places as title,
    no "named" evidence, an empty name field — nothing that hints a name exists."""
    before = {page: _page(lb, ONE, page) for page in (SHELF, JOURNEY)}
    lb = _named(lb)
    for page, unnamed in before.items():
        assert HEAD.sub("", _page(lb, ONE, page)) == HEAD.sub("", unnamed), page
        assert NAME not in _page(lb, ONE, page) and escape(NAME) not in _page(lb, ONE, page)
        assert escape(NAME) in _page(lb, ONE_TWO, page), page


def test_the_day_page_at_tier_1_does_not_show_the_name(lb: Logbook) -> None:
    """The Day links no journey by name; a day of it, read at tier 1, carries the name nowhere."""
    lb = _named(lb)
    for day in (FIRST, LAST):
        assert escape(NAME) not in _page(lb, ONE, f"/day/{day}")


def test_show_trips_and_trip_never_print_a_journey_s_name(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """The trips reader is the derived run of nights (ADR 0019), never the name: its text and its
    JSON carry none at any tier, so there is nothing for them to hold back."""
    lb = _named(lb)
    capsys.readouterr()
    for args in (
        ["show", "trips", "--year", "2022"],
        ["show", "trips", "--year", "2022", "--json"],
        ["show", "trip", BERGEN_WINTER],
        ["show", "trip", BERGEN_WINTER, "--json"],
    ):
        cli.main(args)
        assert NAME not in capsys.readouterr().out, args


def test_export_site_at_tier_1_carries_no_name(lb: Logbook, tmp_path: Path) -> None:
    lb = _named(lb)
    folder = tmp_path / "site"
    cli.main(["export", "site", str(folder)])
    files = [p for p in folder.rglob("*") if p.is_file()]
    assert files, "the site was written"
    for path in files:
        data = path.read_bytes()
        for text in (NAME, escape(NAME)):
            assert text.encode("utf-8") not in data, path.relative_to(folder).parts


# -- the letter ----------------------------------------------------------------------------------------------


def test_a_letter_s_journey_unit_takes_the_name_only_under_its_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from letter_record import FROM, TO, record, set_policy

    lb = record(tmp_path, monkeypatch, {"max_tier": 1})
    journeys.name(lb, ZURICH_JOURNEY, ZURICH_NAME)
    args = ["export", "letter", FROM, TO, "--unit", "journey", "--unsigned", "--out"]
    code, _out, err = run_cli(*args, str(tmp_path / "one"))
    assert code == 0, err
    for path in (tmp_path / "one").iterdir():
        assert ZURICH_NAME not in path.read_text(encoding="utf-8"), path.name
    set_policy(lb.root, {"max_tier": 2})
    code, _out, err = run_cli(*args, str(tmp_path / "two"))
    assert code == 0, err
    assert ZURICH_NAME in (tmp_path / "two" / "letter.md").read_text(encoding="utf-8")


# -- the dream ----------------------------------------------------------------------------------------------


@pytest.mark.usefixtures("no_network")
def test_the_dream_reads_a_journey_s_name_only_under_its_ceiling(
    fortnight_lb: Logbook,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dream_fortnight import set_dream_entry

    lb = fortnight_lb
    _closed(lb, monkeypatch)
    journeys.name(lb, ZURICH_JOURNEY, ZURICH_NAME)
    set_dream_entry(lb.root, {"max_tier": 1, "until": "2026-12-31"})
    seen = fake(
        monkeypatch, lambda m: {"journey": [{"text": "Zürich.", "evidence": m["journey"]["ref"][:1]}]}
    )
    code, _out, err = run_cli("dream", "journey", ZURICH_JOURNEY)
    assert code == 0, err
    (m,) = seen["journeys"]
    assert m["journey"]["named"] is None
    assert ZURICH_NAME not in json.dumps(seen["calls"][-1], ensure_ascii=False)

    set_dream_entry(lb.root, DREAM_ENTRY)
    code, _out, err = run_cli("dream", "journey", ZURICH_JOURNEY)
    assert code == 0, err
    assert seen["journeys"][-1]["journey"]["named"] == ZURICH_NAME
