"""Apple Music's CSVs from Apple's data export → listen/v1 (RFC 0019): the play activity (one line
per play), the library (one line per track per last-played time) and the daily play history (one
line per track per day, at the hour)."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import cli
from logbook.contrib import adapters
from logbook.contrib.adapters import apple_music
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "tests" / "fixtures" / "apple-music" / "Apple Music Activity"
ACTIVITY = FOLDER / "Apple Music Play Activity.csv"
LIBRARY = FOLDER / "Apple Music Library Tracks.csv"
DAILY = FOLDER / "Apple Music - Play History Daily Tracks.csv"
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
TZ = "Europe/Oslo"


def _lines(path: Path, **kw):
    return list(apple_music.run(path, timezone=TZ, **kw))


def _digest(artist: str, title: str) -> str:
    return hashlib.sha256(f"{artist}\n{title}".encode()).hexdigest()[:16]


def test_registry_has_apple_music_as_a_file_adapter():
    assert adapters.named("apple-music") is apple_music
    assert adapters.named("music") is apple_music, "the alias, as `books` and `photos`"
    assert isinstance(apple_music, adapters.Adapter)
    for path in (ACTIVITY, LIBRARY, DAILY):
        assert adapters.find(path) is apple_music, path.name


def test_sniff_wants_one_of_the_three_headers(tmp_path):
    assert apple_music.sniff(ACTIVITY) and apple_music.sniff(LIBRARY) and apple_music.sniff(DAILY)
    assert not apple_music.sniff(FOLDER), "a file, never the folder: the three overlap"
    assert not apple_music.sniff(ROOT / "tests" / "fixtures" / "shazam" / "shazamlibrary.csv")
    assert not apple_music.sniff(ROOT / "tests" / "fixtures" / "takeout" / "Saved" / "Want to go.csv")
    assert not apple_music.sniff(tmp_path / "missing.csv") and not apple_music.sniff(tmp_path)


def test_play_activity_is_one_line_per_play_end_with_device_duration_and_the_skip_flag():
    counts: dict[str, int] = {}
    lines = list(apple_music.run(ACTIVITY, timezone=TZ, counts=counts))
    assert len(lines) == 3
    assert counts == {"skipped_not_a_play": 2, "skipped_no_timestamp": 1, "skipped_no_title": 1}
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["kind"] == "listen" and line["source"] == "apple-music" and line["tier"] == 2
        assert line["tz"] == TZ and line["payload"]["service"] == "apple-music"
        # the line without `raw_id`: its sixteen hex characters could spell a digit-only secret by
        # chance (the wallet test did, once in several runs), so the digest is held to its shape instead
        assert re.fullmatch(r"apple-music:[0-9a-f]{16}:.+", line["payload"]["raw_id"])
        text = json.dumps({**line, "payload": {k: v for k, v in line["payload"].items() if k != "raw_id"}})
        assert "192.0.2.1" not in text and "1000000001" not in text, "no address, no Apple ID"
    by = {line["payload"]["title"]: line for line in lines}
    assert [line["at"] for line in lines] == sorted(line["at"] for line in lines)
    line = by["Fjordsang"]
    assert line["at"] == "2026-03-04T20:15:30Z" and line["end"] == "2026-03-04T20:19:03Z"
    assert line["payload"] == {
        "schema": "listen/v1",
        "raw_id": f"apple-music:{_digest('Kari Nordmann', 'Fjordsang')}:2026-03-04T20:15:30.000Z",
        "media": "track",
        "title": "Fjordsang",
        "artist": "Kari Nordmann",
        "duration_s": 213,
        "played_s": 213,
        "service": "apple-music",
        "extra": {
            "ms_played": 213000,
            "skipped": False,
            "device": "iPhone17-1",
            "end_reason": "NATURAL_END_OF_TRACK",
            "offline": False,
        },
    }
    skipped = by["Bowline"]
    assert skipped["at"] == "2026-03-04T20:19:03Z" and skipped["end"] == "2026-03-04T20:19:33Z"
    assert skipped["payload"]["played_s"] == 30 and skipped["payload"]["duration_s"] == 180
    assert skipped["payload"]["extra"]["skipped"] is True
    assert skipped["payload"]["extra"]["device"] == "MacBookPro18-3"
    older = by["Midnight"]
    assert older["at"] == "2026-01-01T00:30:00Z", "the title from Content Name when Song Name is empty"
    assert older["payload"]["extra"]["offline"] is True


def test_library_tracks_is_one_line_per_track_per_last_played_time():
    counts: dict[str, int] = {}
    lines = list(apple_music.run(LIBRARY, timezone=TZ, counts=counts))
    assert len(lines) == 2 and counts == {"skipped_never_played": 1}
    by = {line["payload"]["title"]: line for line in lines}
    line = by["Fjordsang"]
    assert line["at"] == "2026-03-04T20:19:03Z" and line["end"] is None
    assert line["payload"] == {
        "schema": "listen/v1",
        "raw_id": "apple-music:1000000001@2026-03-04T20:19:03Z",
        "media": "track",
        "title": "Fjordsang",
        "artist": "Kari Nordmann",
        "album": "Nordlys",
        "duration_s": 213,
        "service": "apple-music",
        "extra": {"play_count": 12, "skip_count": 1},
    }
    other = by["Midnight"]
    assert other["payload"]["raw_id"] == "apple-music:2000000003@2026-01-01T00:33:00Z", "the library id"
    assert "album" not in other["payload"] and other["payload"]["extra"] == {"play_count": 1}


def test_daily_play_history_is_one_line_per_track_per_day_at_its_first_hour_in_the_records_zone():
    counts: dict[str, int] = {}
    lines = list(apple_music.run(DAILY, timezone=TZ, counts=counts))
    assert len(lines) == 3 and counts == {"skipped_no_timestamp": 1}
    by = {line["payload"]["title"]: line for line in lines}
    line = by["Fjordsang"]
    assert line["at"] == "2026-03-04T19:00:00Z" and line["end"] is None  # 20:00 in Oslo (CET)
    assert line["payload"] == {
        "schema": "listen/v1",
        "raw_id": "apple-music:1000000001:20260304 20, 21",
        "media": "track",
        "title": "Fjordsang",
        "artist": "Kari Nordmann",
        "played_s": 426,
        "service": "apple-music",
        "extra": {
            "ms_played": 426000,
            "hours": [20, 21],
            "play_count": 2,
            "end_reason": "NATURAL_END_OF_TRACK",
        },
    }
    no_hour = by["Bowline"]
    assert no_hour["at"] == "2026-03-03T23:00:00Z", "no hour: the day's local midnight"
    assert no_hour["payload"]["raw_id"] == "apple-music:1000000002:20260304"
    assert no_hour["payload"]["extra"]["skip_count"] == 1 and "hours" not in no_hour["payload"]["extra"]
    alone = by["Midnight"]
    assert "artist" not in alone["payload"], "a description with no ` - ` is a title alone"
    assert alone["at"] == "2026-01-01T00:00:00Z" and alone["payload"]["extra"]["hours"] == [1]


def test_since_cuts_on_at_and_no_zone_means_utc():
    assert [line["payload"]["title"] for line in _lines(ACTIVITY, since="2026-03-01T00:00:00Z")] == [
        "Fjordsang",
        "Bowline",
    ]
    assert next(line["at"] for line in apple_music.run(DAILY)) == "2026-01-01T01:00:00Z"


def test_cli_add_by_name_and_sniffed_and_a_re_add_appends_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "lb"))
    cli.main(["init", str(tmp_path / "lb"), "--timezone", TZ])
    capsys.readouterr()
    cli.main(["add", "apple-music", str(ACTIVITY)])
    out = capsys.readouterr().out
    assert "added 3 lines from apple-music" in out
    assert "2 not a play" in out and "1 without a timestamp" in out and "1 without a title" in out
    cli.main(["add", str(LIBRARY)])
    out = capsys.readouterr().out
    assert "added 2 lines from apple-music" in out and "1 never played" in out
    cli.main(["add", "apple-music", str(ACTIVITY), str(LIBRARY)])
    out = capsys.readouterr().out
    assert out.count("added 0 lines from apple-music") == 2
    assert Logbook.find().meta["seq"] == 5
