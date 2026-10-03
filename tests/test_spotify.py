"""Spotify's extended streaming history → listen/v1 (RFC 0019): one line per stream, started and
stopped, with how much played, the skip flag and the device; podcasts as episodes."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters, cli
from logbook.adapters import spotify
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "tests" / "fixtures" / "spotify" / "Spotify Extended Streaming History"
AUDIO = FOLDER / "Streaming_History_Audio_2026_0.json"
VIDEO = FOLDER / "Streaming_History_Video_2026.json"
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
TZ = "Europe/Oslo"
LINES = 6


def _lines(path: Path = FOLDER, **kw):
    return list(spotify.run(path, timezone=TZ, **kw))


def test_registry_has_spotify_as_a_file_adapter():
    assert adapters.named("spotify") is spotify
    assert isinstance(spotify, adapters.Adapter)
    assert adapters.find(FOLDER) is spotify
    assert adapters.find(AUDIO) is spotify


def test_sniff_wants_a_history_file_or_a_folder_holding_one(tmp_path):
    assert spotify.sniff(FOLDER) and spotify.sniff(AUDIO) and spotify.sniff(VIDEO)
    assert not spotify.sniff(ROOT / "tests" / "fixtures" / "takeout" / "Chrome" / "History.json")
    assert not spotify.sniff(ROOT / "tests" / "fixtures" / "shazam" / "shazamlibrary.csv")
    assert not spotify.sniff(tmp_path) and not spotify.sniff(tmp_path / "missing.json")
    (tmp_path / "notes.json").write_text('[{"ts": "x"}]', encoding="utf-8")
    assert not spotify.sniff(tmp_path / "notes.json"), "a JSON array is not a history without the columns"


def test_every_named_stream_is_a_line_and_the_envelope_is_complete():
    counts: dict[str, int] = {}
    lines = list(spotify.run(FOLDER, timezone=TZ, counts=counts))
    assert len(lines) == LINES, "five of the audio file's seven rows, the video file's one"
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["kind"] == "listen" and line["source"] == "spotify" and line["tier"] == 2
        assert line["tz"] == TZ and line["end"] is not None and line["at"] <= line["end"]
        assert line["payload"]["schema"] == "listen/v1" and line["payload"]["service"] == "spotify"
    assert counts == {"skipped_audiobook": 1, "skipped_no_title": 1}
    assert [line["at"] for line in lines] == sorted(line["at"] for line in lines), "oldest first"
    assert len({line["payload"]["raw_id"] for line in lines}) == LINES


def test_a_track_starts_ms_played_before_its_stop_and_keeps_album_device_and_the_flags():
    by = {line["payload"]["raw_id"]: line for line in _lines()}
    line = by["spotify:track:1a2b3c4d5e6f7g8h9i0j1k:2026-03-04T20:19:03Z"]
    assert line["at"] == "2026-03-04T20:15:30Z" and line["end"] == "2026-03-04T20:19:03Z"
    assert line["payload"] == {
        "schema": "listen/v1",
        "raw_id": "spotify:track:1a2b3c4d5e6f7g8h9i0j1k:2026-03-04T20:19:03Z",
        "media": "track",
        "title": "Fjordsang",
        "artist": "Kari Nordmann",
        "album": "Nordlys",
        "url": "https://open.spotify.com/track/1a2b3c4d5e6f7g8h9i0j1k",
        "played_s": 213,
        "service": "spotify",
        "extra": {
            "ms_played": 213000,
            "skipped": False,
            "device": "iOS 19.0 (iPhone17,1)",
            "reason_start": "clickrow",
            "reason_end": "trackdone",
            "shuffle": False,
            "offline": False,
            "country": "NO",
        },
    }
    skipped = by["spotify:track:2b3c4d5e6f7g8h9i0j1k2l:2026-03-04T20:19:33Z"]
    assert skipped["at"] == "2026-03-04T20:19:03Z" and skipped["payload"]["played_s"] == 30
    assert skipped["payload"]["extra"]["skipped"] is True
    assert skipped["payload"]["extra"]["device"] == "osx 26.0 (MacBookPro18,3)"
    nothing = by["spotify:track:2b3c4d5e6f7g8h9i0j1k2l:2026-03-04T20:19:34Z"]
    assert nothing["at"] == nothing["end"] == "2026-03-04T20:19:34Z", "a stream of 0 ms starts when it stops"
    assert nothing["payload"]["played_s"] == 0, "a playhead of zero is a value, not an absence"
    live = by["spotify:track:7g8h9i0j1k2l3m4n5o6p7q:2026-03-06T18:04:00Z"]
    assert live["payload"]["title"] == "Fjordsang (Live)" and live["payload"]["album"] == "Nordlys Live"
    assert live["payload"]["extra"]["device"] == "android" and live["payload"]["extra"]["shuffle"] is True
    for line in by.values():
        assert "ip_addr" not in str(line) and "192.0.2.1" not in str(line), "the address is never kept"


def test_a_podcast_stream_is_an_episode_with_its_show():
    by = {line["payload"]["media"]: line for line in _lines()}
    line = by["episode"]
    assert line["at"] == "2026-03-05T06:10:00Z" and line["end"] == "2026-03-05T06:40:00Z"
    assert line["payload"] == {
        "schema": "listen/v1",
        "raw_id": "spotify:episode:3c4d5e6f7g8h9i0j1k2l3m:2026-03-05T06:40:00Z",
        "media": "episode",
        "title": "Episode 12: the east berth",
        "show": "Havnepodden",
        "url": "https://open.spotify.com/episode/3c4d5e6f7g8h9i0j1k2l3m",
        "played_s": 1800,
        "service": "spotify",
        "extra": {
            "ms_played": 1800000,
            "skipped": False,
            "device": "iOS 19.0 (iPhone17,1)",
            "reason_start": "clickrow",
            "reason_end": "endplay",
            "shuffle": False,
            "offline": False,
            "country": "NO",
        },
    }


def test_an_older_export_without_platform_or_skipped_columns_still_reads():
    by = {line["payload"]["title"]: line for line in _lines()}
    line = by["Midnight"]
    assert line["at"] == "2026-01-01T00:30:00Z" and line["end"] == "2026-01-01T00:33:00Z"
    assert "album" not in line["payload"], "a null album is no album"
    extra = line["payload"]["extra"]
    assert "device" not in extra and "skipped" not in extra
    assert extra["ms_played"] == 180000 and extra["country"] == "NO"
    assert "username" not in str(line), "the account name is never kept"


def test_one_file_reads_alone_and_since_cuts_on_at():
    assert [line["payload"]["title"] for line in _lines(VIDEO)] == ["Fjordsang (Live)"]
    titles = [line["payload"]["title"] for line in _lines(since="2026-03-05T00:00:00Z")]
    assert titles == ["Episode 12: the east berth", "Fjordsang (Live)"]
    assert next(line["at"] for line in spotify.run(AUDIO)) == "2026-01-01T00:30:00Z", "no zone: UTC, the same"


def test_cli_add_by_name_or_sniffed_and_a_re_add_appends_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "lb"))
    cli.main(["init", str(tmp_path / "lb"), "--timezone", TZ])
    capsys.readouterr()
    cli.main(["add", "spotify", str(FOLDER)])
    out = capsys.readouterr().out
    assert f"added {LINES} lines from spotify" in out
    assert "1 of an audiobook" in out and "1 without a title" in out
    cli.main(["add", str(FOLDER)])
    assert "added 0 lines from spotify" in capsys.readouterr().out
    cli.main(["add", str(VIDEO)])
    assert "added 0 lines from spotify" in capsys.readouterr().out, "one file of the folder: the same raw_id"
    lb = Logbook.find()
    assert lb.meta["seq"] == LINES
    with lb.index() as idx:
        kinds = {row["kind"]: row for row in idx.kinds()}
    assert kinds["listen"]["lines"] == LINES


def test_cli_add_dry_run_writes_nothing_and_says_what_would_be_added(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "lb"))
    cli.main(["init", str(tmp_path / "lb"), "--timezone", TZ])
    capsys.readouterr()
    cli.main(["add", "spotify", str(FOLDER), "--dry-run"])
    out = capsys.readouterr().out
    assert f"spotify: {LINES} lines would be added, 0 already in the record" in out
    assert "nothing written" in out
    assert "1 of an audiobook" in out, "a dry run reports what the adapter skipped too"
    lb = Logbook.find()
    assert lb.meta["seq"] == 0 and not list((lb.root / "logbook").rglob("*.jsonl"))
    cli.main(["add", "spotify", str(VIDEO)])
    assert "added 1 lines from spotify" in capsys.readouterr().out
    cli.main(["add", str(FOLDER), "--dry-run"])
    out = capsys.readouterr().out
    assert f"spotify: {LINES - 1} lines would be added, 1 already in the record" in out
    assert Logbook.find().meta["seq"] == 1
    cli.main(["add", "had", "a", "quiet", "evening", "--dry-run"])
    assert "manual: 1 line would be added (dry run, nothing written)" in capsys.readouterr().out
    assert Logbook.find().meta["seq"] == 1
