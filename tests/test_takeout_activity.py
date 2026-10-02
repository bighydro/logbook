"""Google Takeout My Activity/ → browse/v1 (RFC 0017) for searches, visited results and apps opened,
watch/v1 (RFC 0018) for YouTube through the YouTube adapter's own mapping. Synthetic throughout."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters, cli
from logbook.adapters.takeout import activity, youtube
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "takeout" / "My Activity"
SEARCH = FIX / "Search" / "MyActivity.json"
YT_HISTORY = ROOT / "tests" / "fixtures" / "takeout" / "YouTube and YouTube Music" / "history"
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
TZ = "Europe/Oslo"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _lines(path=FIX, **kw):
    return list(activity.run(path, timezone=TZ, **kw))


def test_registry_has_activity_as_a_file_adapter_under_both_names():
    assert adapters.named("google-takeout-activity") is activity
    assert adapters.named("takeout-activity") is activity
    assert isinstance(activity, adapters.Adapter)
    assert adapters.find(FIX) is activity and adapters.find(SEARCH) is activity
    assert adapters.find(FIX / "Search") is activity
    assert adapters.find(FIX / "YouTube") is youtube  # the YouTube adapter claims its own history first


def test_sniff_recognises_my_activity_json_its_product_folder_and_the_root(tmp_path):
    assert activity.sniff(SEARCH) and activity.sniff(FIX / "Android") and activity.sniff(FIX)
    assert not activity.sniff(ROOT / "tests" / "fixtures" / "takeout" / "Keep")
    assert not activity.sniff(tmp_path) and not activity.sniff(tmp_path / "MyActivity.json")
    (tmp_path / "MyActivity.html").write_text("<html></html>", encoding="utf-8")
    assert not activity.sniff(tmp_path / "MyActivity.html") and not activity.sniff(tmp_path)


def test_every_search_visit_app_and_watch_is_a_line_and_the_rest_is_counted():
    counts: dict[str, int] = {}
    lines = list(activity.run(FIX, timezone=TZ, counts=counts))
    assert len(lines) == 6  # 2 searches, 1 visited result, 2 apps, 1 watch; Maps' search too makes 6
    for line in lines:
        assert set(line) == ENVELOPE and line["source"] == "google-takeout" and line["tier"] == 2
        assert line["end"] is None and line["tz"] == TZ
    kinds = sorted(line["kind"] for line in lines)
    assert kinds == ["browse"] * 5 + ["watch"]
    assert counts == {
        "skipped_no_url": 1,
        "skipped_no_timestamp": 1,
        "skipped_ad": 1,
        "skipped_covered_by_chrome": 1,
        "skipped_other_activity": 1,
    }
    assert [line["at"] for line in lines] == sorted(line["at"] for line in lines)


def test_a_search_is_a_visit_to_its_results_page_with_the_query_as_title():
    by = {line["payload"]["raw_id"]: line for line in _lines(SEARCH)}
    url = "https://www.google.com/search?q=impeller+volvo+penta+md2030"
    line = by[f"activity:search:2026-06-10T07:00:00.123Z:{_digest(url)}"]
    assert line["at"] == "2026-06-10T07:00:00Z"
    assert line["payload"] == {
        "schema": "browse/v1",
        "raw_id": f"activity:search:2026-06-10T07:00:00.123Z:{_digest(url)}",
        "url": url,
        "title": "impeller volvo penta md2030",
        "action": "visit",
        "browser": "google-search",
        "extra": {
            "activity": "searched",
            "product": "Search",
            "location_hint": {"name": "At this general area", "source": "From your places (Home)"},
        },
    }
    visited = by[
        f"activity:search:2026-06-10T07:02:30.000Z:{_digest('https://www.google.com/url?q=https://parts.example.org/md2030')}"
    ]
    assert (
        visited["payload"]["title"] == "Volvo Penta spare parts"
        and visited["payload"]["extra"]["activity"] == "visited"
    )


def test_an_app_opened_is_a_visit_to_its_store_page_and_maps_searches_name_maps():
    by = {line["payload"]["raw_id"]: line["payload"] for line in _lines()}
    store = "https://play.google.com/store/apps/details?id=org.example.tides"
    app = by[f"activity:android:2026-06-13T09:10:00.000Z:{_digest(store)}"]
    assert app["title"] == "Tide tables" and app["browser"] == "android"
    assert app["extra"] == {"activity": "used", "product": "Tide tables"}
    maps = by[
        f"activity:maps:2026-06-13T07:00:00.000Z:{_digest('https://www.google.com/maps/search/Nesoddtangen')}"
    ]
    assert maps["browser"] == "google-maps" and maps["title"] == "Nesoddtangen"


def test_a_youtube_entry_is_the_youtube_adapters_own_line_so_the_two_dedupe():
    (ours,) = [line for line in _lines() if line["kind"] == "watch"]
    (theirs,) = [
        line
        for line in youtube.run(YT_HISTORY / "watch-history.json", timezone=TZ)
        if line["payload"]["title"] == "Splicing a three-strand rope"
    ]
    assert ours == theirs


def test_since_cuts_on_at():
    assert all(line["at"] >= "2026-06-13T00:00:00Z" for line in _lines(since="2026-06-13T00:00:00Z"))
    assert len(_lines(since="2026-06-13T00:00:00Z")) == 3  # the two apps and the Maps search


def test_the_source_is_off_by_default_and_dedupes_with_the_youtube_adapter_once_on(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "lb"))
    cli.main(["init", str(tmp_path / "lb"), "--timezone", TZ])
    lb = Logbook.find()
    capsys.readouterr()
    cli.main(["add", "takeout-activity", str(FIX)])
    out = capsys.readouterr().out
    assert "google-takeout-activity: disabled (every search and app opened; opt in); skipped" in out
    assert lb.meta["seq"] == 0
    path = lb.root / "policy" / "import.json"
    listed = json.loads(path.read_text(encoding="utf-8"))
    listed["disabled"] = [e for e in listed["disabled"] if e["source"] != "google-takeout-activity"]
    path.write_text(json.dumps(listed), encoding="utf-8")
    cli.main(["add", str(YT_HISTORY)])
    capsys.readouterr()
    cli.main(["add", "takeout-activity", str(FIX), "--dry-run"])
    out = capsys.readouterr().out
    assert "google-takeout-activity: 5 lines would be added, 1 already in the record (dry run" in out
    assert "1 Chrome visits" in out
    cli.main(["add", "takeout-activity", str(FIX)])
    assert "added 5 lines from google-takeout-activity" in capsys.readouterr().out
    cli.main(["add", "takeout-activity", str(FIX)])
    assert "added 0 lines from google-takeout-activity" in capsys.readouterr().out
