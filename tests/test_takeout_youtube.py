"""Google Takeout YouTube history → watch/v1 (RFC 0018): one line per watch and per search, ads skipped."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import cli
from logbook.contrib import adapters
from logbook.contrib.adapters.takeout import youtube

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "takeout" / "YouTube and YouTube Music" / "history"
WATCH = FIX / "watch-history.json"
SEARCH = FIX / "search-history.json"
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
TZ = "Europe/Oslo"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _lines(path=FIX, **kw):
    return list(youtube.run(path, timezone=TZ, **kw))


def test_registry_has_youtube_as_a_file_adapter():
    assert adapters.named("google-takeout-youtube") is youtube
    assert isinstance(youtube, adapters.Adapter)
    assert adapters.find(FIX) is youtube
    assert adapters.find(WATCH) is youtube and adapters.find(SEARCH) is youtube


def test_sniff_recognises_the_history_files_and_the_folder_only(tmp_path):
    assert youtube.sniff(WATCH) and youtube.sniff(SEARCH) and youtube.sniff(FIX)
    assert not youtube.sniff(ROOT / "tests" / "fixtures" / "takeout" / "Chrome" / "History.json")
    assert not youtube.sniff(ROOT / "tests" / "fixtures" / "takeout" / "Keep" / "Boat list.json")
    assert not youtube.sniff(tmp_path) and not youtube.sniff(tmp_path / "missing.json")
    (tmp_path / "subscriptions.json").write_text('[{"header": "YouTube", "x": 1}]', encoding="utf-8")
    assert not youtube.sniff(tmp_path / "subscriptions.json")


def test_every_watch_and_search_is_a_line_and_the_envelope_is_complete():
    counts: dict[str, int] = {}
    lines = list(youtube.run(FIX, timezone=TZ, counts=counts))
    assert len(lines) == 4  # 3 watches (one of a removed video) + 1 search
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["kind"] == "watch" and line["source"] == "google-takeout" and line["tier"] == 2
        assert line["end"] is None and line["tz"] == TZ
        assert line["payload"]["schema"] == "watch/v1"
    assert counts == {"skipped_ad": 1, "skipped_other_activity": 1, "skipped_no_timestamp": 1, "no_url": 1}
    assert [line["at"] for line in lines] == sorted(line["at"] for line in lines)


def test_a_watch_maps_title_url_video_id_channel_and_service():
    by = {line["payload"]["raw_id"]: line for line in _lines(WATCH)}
    url = "https://www.youtube.com/watch?v=aB3dE5fG7hI"
    line = by[f"youtube:2026-03-04T09:00:00.123Z:{_digest(url)}"]
    assert line["at"] == "2026-03-04T09:00:00Z"
    assert line["payload"] == {
        "schema": "watch/v1",
        "raw_id": f"youtube:2026-03-04T09:00:00.123Z:{_digest(url)}",
        "action": "watched",
        "title": "Splicing a three-strand rope",
        "url": url,
        "video_id": "aB3dE5fG7hI",
        "channel": {
            "name": "Knots by Ola",
            "url": "https://www.youtube.com/channel/UCa1b2c3d4e5f6g7h8i9j0k1l",
        },
        "service": "youtube",
    }
    music = by[f"youtube:2026-03-04T21:15:30.000Z:{_digest('https://music.youtube.com/watch?v=zY9xW8vU7tS')}"]
    assert music["payload"]["service"] == "youtube-music" and music["payload"]["title"] == "Fjordsang"
    assert music["payload"]["channel"]["name"] == "Kari Nordmann - Topic"  # kept as spelled (rule 4)
    removed = by[f"youtube:2026-02-11T08:00:00.000Z:{_digest('a video that has been removed')}"]["payload"]
    assert removed["title"] == "a video that has been removed"
    assert "url" not in removed and "video_id" not in removed and "channel" not in removed


def test_a_search_is_a_line_whose_title_is_the_query():
    (line,) = _lines(SEARCH)
    assert line["at"] == "2026-03-04T08:59:00Z"
    p = line["payload"]
    assert p["action"] == "searched" and p["title"] == "rope splice three strand"
    assert p["url"] == "https://www.youtube.com/results?search_query=rope+splice+three+strand"
    assert "video_id" not in p and p["service"] == "youtube"


def test_since_cuts_on_at():
    assert [line["payload"]["title"] for line in _lines(since="2026-03-04T21:00:00Z")] == ["Fjordsang"]


def test_cli_add_sniffs_the_history_folder_and_a_re_add_appends_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "lb"))
    cli.main(["init", str(tmp_path / "lb"), "--timezone", TZ])
    capsys.readouterr()
    cli.main(["add", str(FIX)])
    out = capsys.readouterr().out
    assert "added 4 lines from google-takeout-youtube" in out
    assert "1 advertisements" in out and "1 of another activity" in out and "1 without a timestamp" in out
    assert "1 of a removed video, without a url" in out
    cli.main(["add", str(FIX)])
    assert "added 0 lines from google-takeout-youtube" in capsys.readouterr().out


# -- the HTML flavour, Takeout's default ------------------------------------------------------------------

HTML_FIX = ROOT / "tests" / "fixtures" / "takeout" / "YouTube and YouTube Music (html)" / "history"
WATCH_HTML = HTML_FIX / "watch-history.html"
SEARCH_HTML = HTML_FIX / "search-history.html"


def test_the_html_files_and_their_folder_are_sniffed_and_other_html_is_not(tmp_path):
    assert youtube.sniff(WATCH_HTML) and youtube.sniff(SEARCH_HTML) and youtube.sniff(HTML_FIX)
    assert adapters.find(HTML_FIX) is youtube and adapters.find(WATCH_HTML) is youtube
    assert not youtube.sniff(ROOT / "tests" / "fixtures" / "takeout" / "Chrome" / "Bookmarks.html")
    assert not youtube.sniff(ROOT / "tests" / "fixtures" / "takeout" / "Keep" / "Boat list.html")
    (tmp_path / "x.html").write_text("<html><body>outer-cell content-cell</body></html>", encoding="utf-8")
    assert not youtube.sniff(tmp_path / "x.html")


def test_the_html_history_gives_the_same_lines_as_the_json_one():
    counts: dict[str, int] = {}
    lines = list(youtube.run(HTML_FIX, timezone=TZ, counts=counts))
    assert len(lines) == 5  # 3 watches (one removed), the one spelled in UTC, 1 search
    assert counts == {"skipped_ad": 1, "skipped_other_activity": 1, "skipped_unknown_zone": 1, "no_url": 1}
    by = {line["payload"]["title"]: line for line in lines}
    rope = by["Splicing a three-strand rope"]
    assert rope["at"] == "2026-03-04T09:00:00Z" and rope["tz"] == TZ
    url = "https://www.youtube.com/watch?v=aB3dE5fG7hI"
    assert rope["payload"] == {
        "schema": "watch/v1",
        "raw_id": f"youtube:Mar 4, 2026, 10:00:00 AM CET:{_digest(url)}",  # as spelled, one space each
        "action": "watched",
        "title": "Splicing a three-strand rope",
        "url": url,
        "video_id": "aB3dE5fG7hI",
        "channel": {
            "name": "Knots by Ola",
            "url": "https://www.youtube.com/channel/UCa1b2c3d4e5f6g7h8i9j0k1l",
        },
        "service": "youtube",
    }
    music = by["Fjordsang"]
    assert music["at"] == "2026-03-04T21:15:30Z" and music["payload"]["service"] == "youtube-music"
    assert music["payload"]["channel"]["name"] == "Kari Nordmann - Topic"
    removed = by["a video that has been removed"]
    assert removed["at"] == "2026-02-11T08:00:00Z" and "url" not in removed["payload"]
    assert by["A clock set to UTC"]["at"] == "2026-06-10T11:30:05Z"
    search = by["rope splice three strand"]
    assert search["at"] == "2026-03-04T08:59:00Z" and search["payload"]["action"] == "searched"
    assert search["payload"]["url"] == "https://www.youtube.com/results?search_query=rope+splice+three+strand"
    assert (
        "Filmed on another coast" not in by
    )  # PST is not the record's zone: the reader says so, never guesses


def test_the_html_clock_is_read_in_the_record_zone_only_when_the_abbreviation_is_that_zones():
    assert [line["at"] for line in youtube.run(WATCH_HTML, timezone="America/Los_Angeles")] == [
        "2026-03-05T17:00:00Z",  # the one in PST
        "2026-06-10T11:30:05Z",  # UTC reads everywhere
    ]


def test_cli_add_sniffs_the_html_folder_and_says_what_it_could_not_place_in_time(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "lb"))
    cli.main(["init", str(tmp_path / "lb"), "--timezone", TZ])
    capsys.readouterr()
    cli.main(["add", str(HTML_FIX)])
    out = capsys.readouterr().out
    assert "added 5 lines from google-takeout-youtube" in out
    assert "1 advertisements" in out and "1 of another activity" in out and "1 unknown zone" in out
    cli.main(["add", str(HTML_FIX)])
    assert "added 0 lines from google-takeout-youtube" in capsys.readouterr().out
