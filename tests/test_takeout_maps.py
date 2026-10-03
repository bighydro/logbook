"""Google Takeout Maps (your places)/ → the reviews as highlight/v1 lines (RFC 0022); the saved
places are never lines: they are candidates for `places propose --takeout` and `places add`."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters, cli
from logbook.adapters.takeout import location, maps

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "takeout" / "Maps (your places)"
REVIEWS = FIX / "Reviews.json"
SAVED = FIX / "Saved Places.json"
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
TZ = "Europe/Oslo"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def test_registry_has_maps_as_a_file_adapter_and_the_folder_is_its():
    assert adapters.named("google-takeout-maps") is maps
    assert adapters.named("takeout-maps") is maps
    assert isinstance(maps, adapters.Adapter)
    assert adapters.find(FIX) is maps
    assert adapters.find(REVIEWS) is maps and adapters.find(SAVED) is maps
    assert not location.sniff(SAVED) and not location.sniff(REVIEWS)


def test_sniff_recognises_the_two_files_and_the_folder_only(tmp_path):
    assert maps.sniff(REVIEWS) and maps.sniff(SAVED) and maps.sniff(FIX)
    assert not maps.sniff(ROOT / "tests" / "fixtures" / "takeout" / "Tasks" / "Tasks.json")
    assert not maps.sniff(ROOT / "tests" / "fixtures" / "takeout" / "Keep")
    assert not maps.sniff(tmp_path) and not maps.sniff(tmp_path / "missing.json")
    (tmp_path / "Reviews.json").write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")
    assert not maps.sniff(tmp_path / "Reviews.json")  # nothing in it
    (tmp_path / "other.json").write_text(
        '{"type": "FeatureCollection", "features": [{"x": 1}]}', encoding="utf-8"
    )
    assert not maps.sniff(tmp_path / "other.json")  # a GeoJSON that is neither file


def test_a_review_is_a_highlight_line_and_a_saved_place_is_not_a_line():
    counts: dict[str, int] = {}
    lines = list(maps.run(FIX, timezone=TZ, counts=counts))
    assert len(lines) == 2
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["kind"] == "highlight" and line["source"] == "google-takeout" and line["tier"] == 2
        assert line["end"] is None and line["tz"] == TZ
        assert line["payload"]["schema"] == "highlight/v1"
    assert counts == {"skipped_no_date": 1, "skipped_no_title": 1, "saved_places_left_to_places_propose": 3}
    assert [line["at"] for line in lines] == sorted(line["at"] for line in lines)


def test_both_spellings_of_a_review_map_to_the_same_shape():
    by = {line["payload"]["title"]: line for line in maps.run(REVIEWS, timezone=TZ)}
    new = by["Havnekontoret"]
    assert new["at"] == "2026-02-12T16:20:00Z"
    assert new["payload"] == {
        "schema": "highlight/v1",
        "raw_id": f"maps-review:2026-02-12T16:20:00Z:{_digest('http://maps.google.com/?cid=1234567890123456789')}",
        "type": "highlight",
        "title": "Havnekontoret",
        "quote": "Good coffee and a view of the harbour.\nThe chart table is tiny.",
        "location": "Storgata 1, 0155 Oslo, Norway",
        "extra": {
            "rating": 4,
            "url": "http://maps.google.com/?cid=1234567890123456789",
            "lat": 59.9075,
            "lon": 10.7389,
            "country": "NO",
        },
    }
    old = by["Bygdøy sjøbad"]  # the older spelling: a rating with no words is a bookmark of the place
    assert old["at"] == "2026-06-14T18:05:00Z"
    assert old["payload"]["type"] == "bookmark" and "quote" not in old["payload"]
    assert old["payload"]["location"] == "Bygdøy, 0287 Oslo, Norway"
    assert old["payload"]["extra"] == {
        "rating": 5,
        "url": "http://maps.google.com/?cid=9876543210987654321",
        "lat": 59.9052,
        "lon": 10.6792,
        "country": "NO",
    }


def test_since_cuts_on_at_and_saved_places_alone_give_no_lines():
    assert [line["payload"]["title"] for line in maps.run(FIX, since="2026-03-01T00:00:00Z")] == [
        "Bygdøy sjøbad"
    ]
    counts: dict[str, int] = {}
    assert list(maps.run(SAVED, counts=counts)) == []
    assert counts == {"saved_places_left_to_places_propose": 3}


def test_candidates_carry_name_coordinates_list_and_saved_date(tmp_path):
    found = maps.candidates(FIX)
    assert [c.name for c in found] == ["Havnekontoret", "59°51'00.0\"N 10°39'00.0\"E"]  # Nowhere has no point
    first = found[0]
    assert (first.lat, first.lon, first.list, first.saved_at) == (
        59.9075,
        10.7389,
        "Saved Places",
        "2026-02-11",
    )
    assert first.address == "Storgata 1, 0155 Oslo, Norway"
    assert found[1].saved_at == "2026-03-04"
    # the whole Takeout root brings the Saved/ lists too, each under its list's name, with no date
    everything = maps.candidates(ROOT / "tests" / "fixtures" / "takeout")
    starred = next(c for c in everything if c.list == "Starred places")
    assert starred.name == "Oslofjord chart shop" and starred.saved_at is None
    assert maps.candidates(tmp_path) == []


def test_near_ranks_the_candidates_within_the_distance_by_metres():
    found = maps.candidates(ROOT / "tests" / "fixtures" / "takeout")
    near = maps.near(found, 59.9070, 10.7380, 300)
    assert [c.name for c in near] == ["Havnekontoret"]
    assert near[0].metres == round(near[0].metres) and 0 < near[0].metres < 100
    assert maps.near(found, 47.3769, 8.5417, 300) == []


def test_cli_add_sniffs_the_folder_writes_the_reviews_and_says_what_it_left(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "lb"))
    cli.main(["init", str(tmp_path / "lb"), "--timezone", TZ])
    capsys.readouterr()
    cli.main(["add", str(FIX)])
    out = capsys.readouterr().out
    assert "added 2 lines from google-takeout-maps" in out
    assert "1 without a date" in out and "1 without a title" in out
    assert "3 saved places left to places propose" in out
    cli.main(["add", str(FIX)])
    assert "added 0 lines from google-takeout-maps" in capsys.readouterr().out
