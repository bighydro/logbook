"""Google Takeout YouTube history → watch/v1 (RFC 0018): one line per watch and per search, ads skipped."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters, cli
from logbook.adapters.takeout import youtube

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
