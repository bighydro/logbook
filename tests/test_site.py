"""`logbook export site <folder> [--tier 1|1,2]`: the readers as a folder of static HTML — a Year page
per year, every Trip page, a Days index per year, the places, the people — rendered as `serve` renders
them, written as plain files with relative links, no script, nothing fetched; tier-gated like a crossing
(tier 1 by default) and recorded as a crossing/v1 line. The Oslo persona's fortnight; nobody in it is real."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
from persona import persona_record

from logbook import cli
from logbook.contrib import site
from logbook.store import Logbook

SATURDAY_TRIP = "trip-2026-06-13-2026-06-13"  # the night aboard Solvind: Ola is there by a tier-2 note only
ZURICH_TRIP = "trip-2026-06-15-2026-06-17"  # Ola at the dinner, a tier-1 calendar entry
NOTE_TEXT = "Anchored in the bay with Ola Nordmann"
TRANSCRIPT_TITLE = "Boat plans"
REFERENCE = re.compile(
    r"""(?:href|src|action|formaction|poster|data|srcset|cite)\s*=\s*["']([^"']*)["']""", re.I
)


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    return persona_record(tmp_path, monkeypatch)


def _run(*args: str) -> None:
    cli.main(["export", "site", *args])


def _fails(*args: str) -> int:
    with pytest.raises(SystemExit) as e:
        _run(*args)
    return int(e.value.code or 0)


def _policy(lb: Logbook, max_tier: int) -> Path:
    path = lb.root / "policy" / "crossing.json"
    path.parent.mkdir(exist_ok=True)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data["site"] = {"max_tier": max_tier}
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _read(folder: Path, *parts: str) -> str:
    return folder.joinpath(*parts).read_text(encoding="utf-8")


def _tree(folder: Path) -> dict[Path, bytes]:
    return {p.relative_to(folder): p.read_bytes() for p in sorted(folder.rglob("*.html"))}


def _text(html: str) -> str:
    """The page's text, tags dropped, for assertions on what it says."""
    return re.sub(r"<[^>]+>", " ", html)


# -- the folder ---------------------------------------------------------------------------------------------


def test_the_site_is_a_year_page_a_days_index_every_trip_the_places_and_the_people(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "Site"
    _run(str(folder))
    out = capsys.readouterr().out
    assert "1 year" in out and str(folder) in out

    pages = {p.as_posix() for p in _tree(folder)}
    assert pages == {
        "index.html",
        "years/2026.html",
        "days/2026.html",
        "trips.html",
        f"trips/{SATURDAY_TRIP}.html",
        f"trips/{ZURICH_TRIP}.html",
        "places.html",
        "people.html",
        "people/kari-nordmann.html",
        "people/ola-nordmann.html",
    }

    # The Year is the `logbook year --html` page, with the site's navigation above it and its trips
    # and people linked to their pages.
    year = _read(folder, "years", "2026.html")
    assert "<h1>2026</h1>" in year
    assert 'href="../trips/trip-2026-06-15-2026-06-17.html"' in year
    assert 'href="../people/ola-nordmann.html"' in year
    assert 'href="../days/2026.html"' in year, "the year links its days index"
    assert "Days per country" in year and "One day each" in year

    # The Days index is `serve`'s `/days` table over the year's days the record covers, one row per
    # day with its date as an anchor, and no form or pager: a static page has nothing to submit.
    days = _read(folder, "days", "2026.html")
    assert days.count("<tr") == 1 + 14, "the head and one row per day, 8 to 21 June"
    assert 'id="2026-06-10"' in days and 'id="2026-06-21"' in days
    assert "<form" not in days and "earlier" not in days
    assert "Kari Nordmann" in days, "the `with` column, as serve prints it"

    # The Trip is the `logbook trip --html` page: the route map, the days, the people.
    trip = _read(folder, "trips", f"{ZURICH_TRIP}.html")
    assert "<svg" in trip and "XY 561" in trip and "ZRH" in trip
    assert 'href="../people/ola-nordmann.html"' in trip
    assert 'href="../years/2026.html"' in trip, "a trip links its year"

    # The trips index lists every trip with a link to its page; the places table is serve's; the
    # people index links each person, whose page lists the years together and the trips.
    trips = _read(folder, "trips.html")
    assert f'href="trips/{SATURDAY_TRIP}.html"' in trips and f'href="trips/{ZURICH_TRIP}.html"' in trips
    places = _read(folder, "places.html")
    assert "<h1>Places</h1>" in places and "Marina" in places and "59.9050,10.7350" in places
    people = _read(folder, "people.html")
    assert 'href="people/kari-nordmann.html"' in people and 'href="people/ola-nordmann.html"' in people
    ola = _read(folder, "people", "ola-nordmann.html")
    assert "<h1>Ola Nordmann</h1>" in ola
    assert 'href="../years/2026.html"' in ola and f'href="../trips/{ZURICH_TRIP}.html"' in ola
    index = _read(folder, "index.html")
    assert 'href="years/2026.html"' in index and 'href="days/2026.html"' in index
    assert "tier 1" in _text(index)


def test_every_page_is_self_contained_and_every_link_is_relative_and_resolves(
    lb: Logbook, tmp_path: Path
) -> None:
    """No script, no stylesheet link, no image, no reference to any URL: the only references are
    relative paths to files in the folder (with an optional fragment), so the site reads the same
    from a file manager, a web server at any prefix, or in twenty years."""
    folder = tmp_path / "Site"
    _run(str(folder))
    tree = _tree(folder)
    assert tree
    for rel, raw in tree.items():
        text = raw.decode("utf-8")
        assert "<script" not in text.lower(), rel
        assert "<link" not in text.lower(), rel
        assert "<img" not in text.lower(), rel
        assert "@import" not in text and "url(" not in text, rel
        assert text.startswith("<!doctype html>"), rel
        assert "<nav" in text, f"{rel}: every page carries the site's navigation"
        for ref in REFERENCE.findall(text):
            assert not ref.startswith(("/", "#", "http:", "https:", "//", "data:", "mailto:")), (rel, ref)
            assert ":" not in ref.split("#")[0], (rel, ref)
            target = (folder / rel).parent.joinpath(*ref.split("#")[0].split("/")).resolve()
            assert target.is_file(), f"{rel} links {ref}, which is not a file in the site"
            assert folder.resolve() in target.parents, (rel, ref)


# -- the gate (ADR 0016) -----------------------------------------------------------------------------------


def test_tier_1_is_the_shape_of_the_record_and_names_nobody_a_tier_2_line_places(
    lb: Logbook, tmp_path: Path
) -> None:
    folder = tmp_path / "Site"
    _run(str(folder))
    whole = "\n".join(raw.decode("utf-8") for raw in _tree(folder).values())
    assert NOTE_TEXT not in whole, "a tier-2 note's text is in no page"
    assert TRANSCRIPT_TITLE not in whole, "nor a tier-2 transcript's title"
    saturday = _read(folder, "trips", f"{SATURDAY_TRIP}.html")
    assert "Ola Nordmann" not in _text(saturday), "aboard with Ola by a tier-2 note only: nobody confirmed"
    assert "Nobody confirmed" in saturday
    zurich = _read(folder, "trips", f"{ZURICH_TRIP}.html")
    assert "Ola Nordmann" in _text(zurich), "the dinner is a tier-1 calendar entry"
    index = _read(folder, "index.html")
    assert re.search(r"held back: [\d,]+ lines above tier 1", _text(index)), index


def test_tier_2_crosses_when_the_policy_names_the_site_and_is_refused_otherwise(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "Site"
    assert _fails(str(folder), "--tier", "1,2") == 2
    err = capsys.readouterr().err
    assert "above the ceiling" in err and "policy" in err and '"site"' in err
    assert not folder.exists(), "nothing written"
    assert lb.meta["seq"] == len(list(lb.lines())), "nothing appended"

    _policy(lb, 2)
    _run(str(folder), "--tier", "1,2")
    saturday = _read(folder, "trips", f"{SATURDAY_TRIP}.html")
    assert "Ola Nordmann" in _text(saturday), "the tier-2 note crosses, and names him"
    whole = "\n".join(raw.decode("utf-8") for raw in _tree(folder).values())
    assert "tier 1,2" in _text(_read(folder, "index.html"))
    assert TRANSCRIPT_TITLE in whole or NOTE_TEXT in whole, "tier-2 text is on some page now"

    assert _fails(str(folder), "--tier", "1,2,3") == 2
    assert "never" in capsys.readouterr().err


def test_health_never_goes_to_a_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The demo month has a health line a day, at tier 3, and tier 3 never crosses: the Year says
    it has no health lines, and no day of the index carries a heart rate."""
    root = tmp_path / "Demo"
    cli.main(["demo", "--out", str(root)])
    lb = Logbook(root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    assert any(line["kind"] == "health" and line["tier"] == 3 for line in lb.lines())
    _policy(lb, 2)
    folder = tmp_path / "Site"
    _run(str(folder), "--tier", "1,2")
    whole = "\n".join(raw.decode("utf-8") for raw in _tree(folder).values())
    assert not re.search(r"\d bpm", whole), "no resting heart rate on any page"
    assert not re.search(r"sleep \d", whole), "no night's sleep on any page"
    assert re.search(r"held back: [\d,]+ lines above tier 2", _text(_read(folder, "index.html")))


# -- the record shows it left (RFC 0011) --------------------------------------------------------------------


def test_every_run_appends_one_crossing_line_naming_the_site_and_the_folder_digest(
    lb: Logbook, tmp_path: Path
) -> None:
    folder = tmp_path / "Site"
    before = lb.meta["seq"]
    _run(str(folder))
    line = lb.line_by_seq(before + 1)
    assert line is not None and line["kind"] == "crossing" and line["tier"] == 1
    p = line["payload"]
    assert p["schema"] == "crossing/v1" and p["destination"] == "site"
    assert p["tiers"] == [1] and p["policy"] == {"file": "policy/crossing.json", "max_tier": 1}
    assert p["window"] == {"from": "2026-06-07T22:00:00Z", "to": "2026-06-21T22:00:00Z"}
    counts = p["counts"]
    assert counts["logged"] == counts["crossed"] + counts["held_back"]
    assert counts["held_back"] > 0 and counts["by_tier"]["2"] == 0
    assert set(counts["by_kind"]) >= {"location", "event", "photo"}
    files = {rel.as_posix(): raw for rel, raw in _tree(folder).items()}
    whole = hashlib.sha256()
    for rel in sorted(files):
        whole.update(f"{hashlib.sha256(files[rel]).hexdigest()}  {rel}\n".encode())
    assert p["package_sha256"] == whole.hexdigest()
    pages = p["extra"]["site"]["pages"]
    assert pages == {"years": 1, "days": 1, "trips": 2, "places": 1, "people": 2}
    assert p["extra"]["site"]["files"] == {"written": len(files), "unchanged": 0, "total": len(files)}
    assert lb.meta["seq"] == before + 1, "one line, nothing else"


def test_rerunning_rewrites_nothing_when_the_record_did_not_change(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every page is a function of the record's lines and settings: no head (the crossing line the
    first run appended would change it), no timestamp. A stranger's file beside the pages stays."""
    folder = tmp_path / "Site"
    _run(str(folder))
    first = _tree(folder)
    (folder / "CNAME").write_text("example.org\n", encoding="utf-8")
    _run(str(folder))
    out = capsys.readouterr().out
    assert f"0 written, {len(first)} unchanged" in out
    assert _tree(folder) == first
    assert (folder / "CNAME").read_text(encoding="utf-8") == "example.org\n"


# -- refusals -----------------------------------------------------------------------------------------------


def test_needs_a_folder_and_a_record_with_a_day(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _fails() == 2
    assert "export site needs a folder" in capsys.readouterr().err
    empty = Logbook.init(tmp_path / "empty", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(empty.root))
    _run(str(tmp_path / "Nothing"))
    assert "no day" in capsys.readouterr().out
    assert not (tmp_path / "Nothing").exists()
    assert empty.meta["seq"] == 0


def test_slugs_and_relative_paths() -> None:
    assert site.slug("Kari Nordmann") == "kari-nordmann"
    assert site.slug("  Ola   Nordmann ") == "ola-nordmann"
    assert site.slug("Zürich café / bar") == "zurich-cafe-bar"
    assert site.slug("") == "unnamed"
    assert site.slug("...") == "unnamed"
    assert site.relative("index.html", "years/2026.html") == "years/2026.html"
    assert site.relative("years/2026.html", "index.html") == "../index.html"
    assert site.relative("years/2026.html", "trips/x.html") == "../trips/x.html"
    assert site.relative("years/2026.html", "years/2025.html") == "2025.html"
    assert site.relative("a/b/c.html", "d.html") == "../../d.html"
