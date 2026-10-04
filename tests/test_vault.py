"""`logbook export vault <folder>`: the record as a folder of plain Markdown an Obsidian or Logseq
user opens as a vault — a page per day, per named place, per person, per trip and per year, linked
with wikilinks; tier-gated like a crossing (tier 1 by default: shape, never a note's or a message's
text) and recorded as a crossing/v1 line. The Oslo persona's fortnight; nobody in it is real."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
from persona import KARI_ID, OLA_ID, persona_record

from logbook import cli
from logbook.contrib import vault
from logbook.core.store import Logbook

SATURDAY = "2026-06-13"  # aboard Solvind with Ola, by a tier-2 note
TUESDAY = "2026-06-16"  # dinner in Zürich with Ola, by a tier-1 calendar entry
WEDNESDAY = "2026-06-10"  # lunch with Kari at the cafe, by a tier-1 calendar entry
NOTE_TEXT = "Anchored in the bay with Ola Nordmann"
TRANSCRIPT_TITLE = "Boat plans"


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    return persona_record(tmp_path, monkeypatch)


def _run(*args: str) -> None:
    cli.main(["export", "vault", *args])


def _fails(*args: str) -> int:
    with pytest.raises(SystemExit) as e:
        _run(*args)
    return int(e.value.code or 0)


def _policy(lb: Logbook, max_tier: int) -> Path:
    path = lb.root / "policy" / "crossing.json"
    path.parent.mkdir(exist_ok=True)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data["vault"] = {"max_tier": max_tier}
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _read(folder: Path, *parts: str) -> str:
    return folder.joinpath(*parts).read_text(encoding="utf-8")


def _front_matter(text: str) -> str:
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert match, text[:200]
    return match.group(1)


def _links(text: str) -> set[str]:
    return set(re.findall(r"\[\[([^\]|#]+)", text))


def _tree(folder: Path) -> dict[Path, bytes]:
    return {p.relative_to(folder): p.read_bytes() for p in sorted(folder.rglob("*.md"))}


# -- the folder --------------------------------------------------------------------------------------------


def test_the_vault_is_a_page_per_day_place_person_trip_and_year_linked_by_wikilinks(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "Vault"
    _run(str(folder))
    out = capsys.readouterr().out
    assert "14 days" in out and str(folder) in out

    days = sorted(p.name for p in (folder / "days" / "2026").glob("*.md"))
    assert days == [f"2026-06-{d:02d}.md" for d in range(8, 22)], "one page per day the record has lines on"
    assert sorted(p.stem for p in (folder / "places").glob("*.md")) == ["Home", "Marina", "Office"]
    assert sorted(p.stem for p in (folder / "people").glob("*.md")) == ["Kari Nordmann", "Ola Nordmann"]
    assert sorted(p.stem for p in (folder / "trips").glob("*.md")) == [
        "Trip 2026-06-13 to 2026-06-13",
        "Trip 2026-06-15 to 2026-06-17",
    ]
    assert [p.stem for p in (folder / "years").glob("*.md")] == ["2026"]
    assert (folder / "Logbook.md").is_file()

    # The day page: YAML front matter with the date, the country, the nights, the places and the
    # people; the body links every place, person and trip it names, and its year.
    wednesday = _read(folder, "days", "2026", f"{WEDNESDAY}.md")
    front = _front_matter(wednesday)
    assert "date: 2026-06-10" in front
    assert "weekday: Wednesday" in front
    assert 'country: "NO"' in front, "quoted: a bare NO is false in YAML"
    assert re.search(r"nights:\n  before: \"Home\"\n  after: \"Home\"", front)
    assert "places:\n" in front and '  - "Office"' in front and '  - "Home"' in front
    assert 'people:\n  - "Kari Nordmann"' in front
    links = _links(wednesday)
    assert {"Home", "Office", "Kari Nordmann", "2026"} <= links
    assert "Lunch" in wednesday, "a tier-1 calendar entry is named"

    tuesday = _read(folder, "days", "2026", f"{TUESDAY}.md")
    assert "Trip 2026-06-15 to 2026-06-17" in _links(tuesday)
    assert 'country: "CH"' in _front_matter(tuesday)
    assert "Ola Nordmann" in _links(tuesday), "confirmed by the dinner, a tier-1 calendar entry"

    # The place page links back to its days and the people met there; the person page to the
    # days together, the places shared and the trips; the trip page to its days; the year to all.
    home = _read(folder, "places", "Home.md")
    assert 'kind: "home"' in _front_matter(home)
    assert {WEDNESDAY, "2026-06-08", "2026-06-21"} <= _links(home)
    kari = _read(folder, "people", "Kari Nordmann.md")
    assert {WEDNESDAY} <= _links(kari)
    ola = _read(folder, "people", "Ola Nordmann.md")
    assert {TUESDAY, "Trip 2026-06-15 to 2026-06-17"} <= _links(ola)
    trip = _read(folder, "trips", "Trip 2026-06-15 to 2026-06-17.md")
    assert {"2026-06-15", TUESDAY, "2026-06-17", "Ola Nordmann", "2026"} <= _links(trip)
    assert "XY 561" in trip and "ZRH" in trip
    year = _read(folder, "years", "2026.md")
    assert {d[:-3] for d in days} <= _links(year)
    assert {"Trip 2026-06-13 to 2026-06-13", "Home", "Kari Nordmann"} <= _links(year)
    assert {"2026"} <= _links(_read(folder, "Logbook.md"))


def test_a_night_aboard_is_in_the_front_matter_as_the_day_shows_it(lb: Logbook, tmp_path: Path) -> None:
    folder = tmp_path / "Vault"
    _run(str(folder))
    saturday = _read(folder, "days", "2026", f"{SATURDAY}.md")
    assert 'after: "aboard Solvind"' in _front_matter(saturday)
    assert "aboard Solvind" in saturday


# -- the tier gate (ADR 0016) --------------------------------------------------------------------------------


def test_tier_1_is_shape_only_no_note_or_message_text(lb: Logbook, tmp_path: Path) -> None:
    folder = tmp_path / "Vault"
    _run(str(folder))
    saturday = _read(folder, "days", "2026", f"{SATURDAY}.md")
    assert NOTE_TEXT not in saturday
    assert "held back" in saturday and "1 note" in saturday, "the shape of the day stays: a note was written"
    assert "Ola Nordmann" not in saturday, "his only evidence that day is the tier-2 note"
    assert "1 photo" in saturday, "a photo is tier 1"
    thursday = _read(folder, "days", "2026", "2026-06-11.md")
    assert TRANSCRIPT_TITLE not in thursday and "1 transcript" in thursday
    whole = "".join(p.read_text(encoding="utf-8") for p in folder.rglob("*.md"))
    assert NOTE_TEXT not in whole and TRANSCRIPT_TITLE not in whole


def test_tier_2_names_the_note_and_the_transcript_when_the_policy_allows(lb: Logbook, tmp_path: Path) -> None:
    _policy(lb, 2)
    folder = tmp_path / "Vault"
    _run(str(folder), "--tier", "1,2")
    saturday = _read(folder, "days", "2026", f"{SATURDAY}.md")
    assert NOTE_TEXT in saturday
    assert "Ola Nordmann" in _links(saturday), "confirmed by the note once tier 2 crosses"
    assert "held back" not in saturday
    thursday = _read(folder, "days", "2026", "2026-06-11.md")
    assert TRANSCRIPT_TITLE in thursday
    ola = _read(folder, "people", "Ola Nordmann.md")
    assert SATURDAY in _links(ola)


def test_a_tier_above_the_ceiling_is_refused_naming_the_policy_file(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "Vault"
    assert _fails(str(folder), "--tier", "1,2") == 2
    err = capsys.readouterr().err
    assert "policy" in err and "crossing.json" in err and "vault" in err
    assert not folder.exists(), "nothing written"
    assert lb.meta["seq"] == len(list(lb.lines())), "nothing appended"
    _policy(lb, 3)
    assert _fails(str(folder), "--tier", "1,2,3") == 2, "tier 3 never goes to a vault"
    assert "1,2" in capsys.readouterr().err


def test_default_tier_is_1_without_any_policy_entry(lb: Logbook, tmp_path: Path) -> None:
    (lb.root / "policy" / "crossing.json").unlink()
    _run(str(tmp_path / "Vault"))
    line = list(lb.lines())[-1]
    assert line["payload"]["tiers"] == [1]
    assert line["payload"]["policy"] == {"file": "policy/crossing.json", "max_tier": 1}
    assert (lb.root / "policy" / "crossing.json").is_file(), "the first export writes the default"


# -- the record shows it left (RFC 0011) ---------------------------------------------------------------------


def test_every_export_appends_one_crossing_line_and_the_chain_stays_valid(
    lb: Logbook, tmp_path: Path
) -> None:
    head = lb.meta["head"]
    seq = lb.meta["seq"]
    folder = tmp_path / "Vault"
    _run(str(folder))
    _seq, _head, errors = lb.verify()
    assert errors == []
    line = list(lb.lines())[-1]
    assert (line["kind"], line["tier"], line["source"], line["seq"]) == ("crossing", 1, "logbook", seq + 1)
    p = line["payload"]
    assert p["schema"] == "crossing/v1"
    assert p["destination"] == "vault"
    assert p["window"] == {"from": "2026-06-07T22:00:00Z", "to": "2026-06-21T22:00:00Z"}, "local days, UTC"
    assert p["tiers"] == [1]
    assert p["logbook_head"] == head
    counts = p["counts"]
    assert counts["crossed"] + counts["held_back"] == counts["logged"]
    assert counts["by_tier"]["2"] == 0 and counts["held_back"] == 2, "the note and the transcript"
    assert counts["by_kind"]["location"] > 0 and "note" not in counts["by_kind"]
    files = _tree(folder)
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda p: p.as_posix()):
        digest.update(f"{hashlib.sha256(files[path]).hexdigest()}  {path.as_posix()}\n".encode())
    assert p["package_sha256"] == digest.hexdigest(), "the digest names the folder as written"
    assert p["extra"]["vault"]["files"] == {"written": len(files), "unchanged": 0, "total": len(files)}
    assert p["extra"]["vault"]["pages"] == {"days": 14, "places": 3, "people": 2, "trips": 2, "years": 1}


def test_rerunning_rewrites_only_the_files_whose_content_changed(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _policy(lb, 2)
    folder = tmp_path / "Vault"
    _run(str(folder), "--tier", "1,2")
    first = _tree(folder)
    capsys.readouterr()
    _run(str(folder), "--tier", "1,2")
    out = capsys.readouterr().out
    assert "0 written" in out and f"{len(first)} unchanged" in out
    assert _tree(folder) == first, "the crossing line appended between the runs is in no page"
    line = list(lb.lines())[-1]
    assert line["payload"]["extra"]["vault"]["files"]["written"] == 0

    # A new note on the Wednesday changes that day's page (and the pages that count it), not the Saturday's.
    lb.append(
        at="2026-06-10T13:30:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "text": "Back at the desk after lunch."},
    )
    _run(str(folder), "--tier", "1,2")
    second = _tree(folder)
    wednesday, saturday = Path("days", "2026", f"{WEDNESDAY}.md"), Path("days", "2026", f"{SATURDAY}.md")
    assert second[wednesday] != first[wednesday] and b"Back at the desk" in second[wednesday]
    assert second[saturday] == first[saturday]
    changed = {p for p in second if second[p] != first.get(p)}
    assert wednesday in changed and len(changed) < len(second)


def test_since_and_until_pick_the_days(lb: Logbook, tmp_path: Path) -> None:
    folder = tmp_path / "Vault"
    _run(str(folder), "--since", "2026-06-15", "--until", "2026-06-17")
    assert sorted(p.stem for p in (folder / "days" / "2026").glob("*.md")) == [
        "2026-06-15",
        "2026-06-16",
        "2026-06-17",
    ]
    assert sorted(p.stem for p in (folder / "people").glob("*.md")) == ["Ola Nordmann"]
    line = list(lb.lines())[-1]
    assert line["payload"]["window"] == {"from": "2026-06-14T22:00:00Z", "to": "2026-06-17T22:00:00Z"}


def test_a_backwards_window_and_a_bad_day_are_refused(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _fails(str(tmp_path / "V"), "--since", "2026-06-17", "--until", "2026-06-15") == 2
    assert "backwards" in capsys.readouterr().err
    assert _fails(str(tmp_path / "V"), "--since", "2026-6-1") == 2
    assert _fails(str(tmp_path / "V"), "--tier", "2") == 2
    assert _fails() == 2, "the folder is required"


def test_an_empty_record_writes_nothing_and_appends_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = Logbook.init(tmp_path / "empty", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    _run(str(tmp_path / "Vault"))
    assert "nothing" in capsys.readouterr().out
    assert not (tmp_path / "Vault").exists()
    assert lb.meta["seq"] == 0


# -- file names ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "stem"),
    [
        ("Home", "Home"),
        ("Café Ø/Å: the <best> | one?", "Café Ø-Å- the -best- - one-"),
        ("  spaced   out  ", "spaced out"),
        ("[[not a link]] #tag ^block", "-not a link- -tag -block"),
        ("trailing dots...", "trailing dots"),
        ("", "unnamed"),
        ("CON", "CON-"),
    ],
)
def test_page_names_are_safe_on_every_platform_and_inside_a_wikilink(name: str, stem: str) -> None:
    assert vault.safe_stem(name) == stem


def test_names_that_differ_only_by_case_get_distinct_pages() -> None:
    names = vault.Names()
    assert names.claim("Marina") == "Marina"
    assert names.claim("marina") == "marina (2)"
    assert names.claim("Marina") == "Marina", "claiming the same name again is the same page"
    assert names.claim("MARINA") == "MARINA (3)"


def test_people_are_keyed_by_entity_so_one_person_is_one_page(lb: Logbook, tmp_path: Path) -> None:
    folder = tmp_path / "Vault"
    _run(str(folder))
    kari = _read(folder, "people", "Kari Nordmann.md")
    assert f'id: "{KARI_ID}"' in _front_matter(kari)
    ola = _read(folder, "people", "Ola Nordmann.md")
    assert f'id: "{OLA_ID}"' in _front_matter(ola)
