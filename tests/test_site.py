"""`logbook export site <folder> [--tier 1|1,2]`: the readers as a folder of static HTML — a Year page
per year, a Day page for each of its picks, every Trip page, a Days index per year, the places, the
people — rendered as `serve` renders them, written as plain files with relative links, no script,
nothing fetched; tier-gated like a crossing (tier 1 by default) and recorded as a crossing/v1 line. The
Oslo persona's fortnight; nobody in it is real."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import phone_width
import pytest
from persona import persona_record

from logbook import cli
from logbook.contrib import site
from logbook.core import drafts
from logbook.core.store import Logbook

SATURDAY_TRIP = "trip-2026-06-13-2026-06-13"  # the night aboard Solvind: Ola is there by a tier-2 note only
ZURICH_TRIP = "trip-2026-06-15-2026-06-17"  # Ola at the dinner, a tier-1 calendar entry
NOTE_TEXT = "Anchored in the bay with Ola Nordmann"
TIER_1_PICK = "2026-06-10"  # the June pick of the Year at tier 1: a Wednesday
TIER_2_PICK = "2026-06-13"  # and at tier 1,2: the Saturday aboard, the note naming Ola now crossing
README_DAY = "2025-06-14"  # the demo's day the README links: the June pick of 2025, at the cabin with Ola
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
        f"days/{TIER_1_PICK}.html",
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


def test_each_pick_of_a_year_is_a_day_page_and_its_row_in_the_days_index_links_it(
    lb: Logbook, tmp_path: Path
) -> None:
    """The Year renders twelve picks in full, one day a month; each is also a page of its own,
    `days/<day>.html`, `serve`'s Day page written down with every toggle open: the nights either
    side, the timeline with what attached and who was there, the sources. Nothing to toggle or
    submit on a static page. Its row in the Days index links it; every other day stays a row, the
    anchor its neighbours link to, and no other Day page is written."""
    folder = tmp_path / "Site"
    _run(str(folder))
    day = _read(folder, "days", f"{TIER_1_PICK}.html")
    assert f"<h1>{TIER_1_PICK} <small>Wednesday</small></h1>" in day
    assert "night before" in day and "night after" in day and "<h2>Timeline</h2>" in day
    assert "<h2>Sources</h2>" in day
    assert "<details" not in day or "<details open" in day, "every toggle open"
    assert "<form" not in day and "<script" not in day
    assert "expand all" not in day and "collapse all" not in day and "reflect and sign" not in day
    assert 'href="../index.html"' in day and 'href="../years/2026.html"' in day, "the site's navigation"
    assert 'href="2026.html"' in day, "and its year's Days index"
    assert '<a href="2026.html#2026-06-08">the fortnight around</a>' in day, "from the record's first day"
    assert '<a href="2026.html#2026-06-09">← 2026-06-09</a>' in day, "a neighbour is its row"
    assert '<a href="2026.html#2026-06-11">2026-06-11 →</a>' in day

    days = _read(folder, "days", "2026.html")
    assert f'<td class="day"><a href="{TIER_1_PICK}.html">{TIER_1_PICK}</a></td>' in days
    assert '<td class="day">2026-06-11</td>' in days, "a day with no page of its own is a row, unlinked"
    assert {p.name for p in (folder / "days").iterdir()} == {"2026.html", f"{TIER_1_PICK}.html"}


def test_a_day_page_the_root_and_the_tables_hold_a_phone_s_column(lb: Logbook, tmp_path: Path) -> None:
    """The README sends a stranger straight to one of the demo's Day pages, as often as not on a
    phone: the Day page, the root, the Days index that links it and the other pages in `serve`'s
    stylesheet need no sideways scroll 400 px wide, read from their own HTML and stylesheet
    (`phone_width`, no browser), as the Library's pages are held. A table wider than the column
    scrolls inside itself."""
    _policy(lb, 2)
    folder = tmp_path / "Site"
    _run(str(folder), "--tier", "1,2")
    for parts in (
        ("days", f"{TIER_2_PICK}.html"),
        ("index.html",),
        ("days", "2026.html"),
        ("trips.html",),
        ("places.html",),
        ("people.html",),
        ("people", "ola-nordmann.html"),
    ):
        text = _read(folder, *parts)
        assert phone_width.problems(text) == [], parts
        assert phone_width.phone_breakpoints(phone_width.parse(text)[1]), parts


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
    assert not (folder / "days" / f"{TIER_2_PICK}.html").exists(), "the Saturday is a pick at tier 2 alone"
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
    saturday_page = _read(folder, "days", f"{TIER_2_PICK}.html")
    assert NOTE_TEXT in saturday_page, "her note, in her words, on the day it was written"
    assert "Ola Nordmann" in _text(saturday_page)

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
    assert pages == {"years": 1, "days": 1, "day_pages": 1, "trips": 2, "places": 1, "people": 2}
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
    assert site.slug("Bjørn Aas") == "bjorn-aas" and site.slug("Ærø") == "aero"
    assert site.slug("") == "unnamed"
    assert site.slug("...") == "unnamed"
    assert site.relative("index.html", "years/2026.html") == "years/2026.html"
    assert site.relative("years/2026.html", "index.html") == "../index.html"
    assert site.relative("years/2026.html", "trips/x.html") == "../trips/x.html"
    assert site.relative("years/2026.html", "years/2025.html") == "2025.html"
    assert site.relative("a/b/c.html", "d.html") == "../../d.html"


# -- forty years ---------------------------------------------------------------------------------------------


@pytest.mark.slow
def test_forty_years_export_whole_every_link_resolves_and_the_folder_passes_the_synthetic_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """What the docs workflow publishes: `logbook demo --years 40 --seed 1`, the `site` entry its step
    writes into the record's policy, and `export site --tier 1,2` — a Year page and a Days index for
    each calendar year of the forty (41, July to June), the childhood ones included (lines, no
    track), a Day page per pick, every trip, the people; every link a file in the folder; and
    `scripts/check_synthetic.py` passes. At tier 1 too, the default a real record exports at. The Day
    the README links is a page at the same path on every build, since the seed is fixed: the June
    pick of 2025, at the cabin with Ola, her note on it, held to a phone's column."""
    root = tmp_path / "Life"
    cli.main(["demo", "--years", "40", "--seed", "1", "--out", str(root)])
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    script = Path(__file__).resolve().parents[1] / "scripts" / "check_synthetic.py"
    env = {**os.environ, "LOGBOOK_PII_PATTERNS": str(tmp_path / "no-patterns")}
    for tiers in ("1", "1,2"):
        if tiers == "1,2":
            _policy(Logbook(root), 2)
        folder = tmp_path / f"ines-{tiers.replace(',', '-')}"
        _run(str(folder), "--tier", tiers)
        out = capsys.readouterr().out
        assert f"41 years 1986-07-01 \u2013 2026-06-30, tier {tiers}" in out
        pages = {p.as_posix() for p in _tree(folder)}
        assert {f"years/{y}.html" for y in range(1986, 2027)} <= pages
        assert {f"days/{y}.html" for y in range(1986, 2027)} <= pages
        day_pages = [p for p in pages if re.fullmatch(r"days/\d{4}-\d{2}-\d{2}\.html", p)]
        assert 0 < len(day_pages) <= 12 * 41
        assert len([p for p in pages if p.startswith("trips/")]) > 100
        assert "people/kari-nordmann.html" in pages and "people/ola-nordmann.html" in pages
        for rel, raw in _tree(folder).items():
            text = raw.decode("utf-8")
            assert "<script" not in text.lower(), rel
            for ref in REFERENCE.findall(text):
                assert not ref.startswith(("/", "http:", "https:", "//")), (rel, ref)
                target = (folder / rel).parent.joinpath(*ref.split("#")[0].split("/")).resolve()
                assert target.is_file(), f"{rel} links {ref}, which is not a file in the site"
        r = subprocess.run(
            [sys.executable, str(script), str(folder)], capture_output=True, encoding="utf-8", env=env
        )
        assert r.returncode == 0, r.stdout + r.stderr

    readme_day = _read(folder, "days", f"{README_DAY}.html")
    assert f"<h1>{README_DAY} <small>Saturday</small></h1>" in readme_day
    assert "At the cabin with Ola Nordmann" in readme_day, "her note, at tier 2"
    assert "Ola Nordmann (calendar, note, photo)" in readme_day, "confirmed present"
    assert "2 photos" in readme_day and "Cabin" in readme_day
    assert phone_width.problems(readme_day) == []
    assert phone_width.problems(_read(folder, "index.html")) == []


# -- a model's drafts (pencil): left out unless asked for ---------------------------------------------------

MODEL = "model:local-7b"
DRAFT_TEXT = "A quiet day ashore, by the marina."
WEEK_TEXT = "A week of the boat and the office."
REFLECTION_TEXT = "Glad to be back on the water."


def _draft(unit: str, subject: object, evidence: str, text: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": drafts.SCHEMA,
        "unit": unit,
        "subject": subject,
        "read_head": "0" * 64,
        "read_count": 1,
        "language": "en",
        "segments": [{"text": text, "evidence": [evidence]}],
        "extra": {"prompt": "test/1", "parts": [unit], "policy_version": "0" * 64, "entry": "dream"},
    }
    assert drafts.validate(payload) == []
    return {
        "at": f"{TIER_1_PICK}T20:00:00Z",
        "source": MODEL,
        "kind": drafts.KIND,
        "tier": 1,
        "payload": payload,
    }


def _pencil(lb: Logbook) -> None:
    """A local model's draft of the tier-1 pick and of its week, both tier 1, under a `dream` entry
    that allows tier 2: what `dream` writes, as the Day page shows it."""
    path = lb.root / "policy" / "crossing.json"
    path.parent.mkdir(exist_ok=True)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data["dream"] = {"max_tier": 2}
    path.write_text(json.dumps(data), encoding="utf-8")
    with lb.index() as idx:
        evidence = next(str(line["id"]) for line in idx.day(TIER_1_PICK) if line["kind"] == "location")
    lb.append_many(
        [
            _draft(drafts.UNIT_DAY, TIER_1_PICK, evidence, DRAFT_TEXT),
            _draft(drafts.UNIT_WEEK, "2026-W24", evidence, WEEK_TEXT),
        ]
    )


def _site_extra(lb: Logbook) -> dict[str, Any]:
    line = [line for line in lb.lines() if line["kind"] == "crossing"][-1]
    return dict(line["payload"]["extra"]["site"])


def test_a_site_leaves_a_models_drafts_out_unless_asked(lb: Logbook, tmp_path: Path) -> None:
    """The Day page the site writes is the server's, but a draft is a model's pencil, never the
    owner's ink: by default no page carries the day's draft, the week's, or a word of either, and
    the crossing line says the drafts were left out."""
    _pencil(lb)
    folder = tmp_path / "Site"
    _run(str(folder))
    day = _read(folder, "days", f"{TIER_1_PICK}.html")
    assert "<h2>Draft</h2>" not in day and "has a draft" not in day
    for rel, raw in _tree(folder).items():
        text = raw.decode("utf-8")
        assert MODEL not in text and DRAFT_TEXT not in text and WEEK_TEXT not in text, rel
    assert _site_extra(lb)["drafts"] is False


def test_with_drafts_a_day_page_shows_the_draft_headed_as_a_models_with_its_name(
    lb: Logbook, tmp_path: Path
) -> None:
    """`--with-drafts`: the day's draft and the line to its week's, each as the Day page heads
    them, `draft · model:<name> · read at …`; the footer and the crossing line say so."""
    _pencil(lb)
    folder = tmp_path / "Site"
    _run(str(folder), "--with-drafts")
    day = _read(folder, "days", f"{TIER_1_PICK}.html")
    assert "<h2>Draft</h2>" in day and f"draft{site.DOT}{MODEL}{site.DOT}read at" in day
    assert DRAFT_TEXT in day
    assert "The week 2026-W24 has a draft" in day
    assert "a model's drafts included, each headed with its model" in day
    assert _site_extra(lb)["drafts"] is True


def test_with_drafts_is_for_the_site_alone(lb: Logbook, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as e:
        cli.main(["export", "vault", str(tmp_path / "Vault"), "--with-drafts"])
    assert e.value.code == 2


def test_the_owners_reflection_follows_its_own_tier_with_or_without_drafts(
    lb: Logbook, tmp_path: Path
) -> None:
    """A reflection is the owner's words (tier 2, `day reflect`), not a draft: a tier-1,2 site
    shows it on its day with no flag; a tier-1 site shows it nowhere, drafts or not."""
    _policy(lb, 2)
    cli.main(["day", "reflect", TIER_2_PICK, "--text", REFLECTION_TEXT])
    wide = tmp_path / "Wide"
    _run(str(wide), "--tier", "1,2")
    assert REFLECTION_TEXT in _read(wide, "days", f"{TIER_2_PICK}.html")
    for flags in ((), ("--with-drafts",)):
        narrow = tmp_path / ("Narrow" + "".join(flags))
        _run(str(narrow), *flags)
        assert not any(REFLECTION_TEXT in raw.decode("utf-8") for raw in _tree(narrow).values())
