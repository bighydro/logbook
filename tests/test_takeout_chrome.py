"""Google Takeout Chrome/ → browse/v1 (RFC 0017): a visit per history entry, a bookmark per link."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters, cli
from logbook.adapters.takeout import chrome

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "takeout" / "Chrome"
HISTORY = FIX / "History.json"
BOOKMARKS = FIX / "Bookmarks.html"
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
TZ = "Europe/Oslo"


def _digest(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _lines(path=FIX, **kw):
    return list(chrome.run(path, timezone=TZ, **kw))


def test_registry_has_chrome_as_a_file_adapter():
    assert adapters.named("google-takeout-chrome") is chrome
    assert isinstance(chrome, adapters.Adapter)
    assert adapters.find(FIX) is chrome
    assert adapters.find(HISTORY) is chrome and adapters.find(BOOKMARKS) is chrome


def test_sniff_recognises_the_history_the_bookmarks_and_the_folder_only(tmp_path):
    assert chrome.sniff(HISTORY) and chrome.sniff(BOOKMARKS) and chrome.sniff(FIX)
    assert not chrome.sniff(ROOT / "tests" / "fixtures" / "takeout" / "Keep" / "Boat list.json")
    assert not chrome.sniff(ROOT / "tests" / "fixtures" / "takeout" / "Keep" / "Boat list.html")
    assert not chrome.sniff(tmp_path) and not chrome.sniff(tmp_path / "missing.json")
    (tmp_path / "Autofill.json").write_text('{"Autofill": []}', encoding="utf-8")
    assert not chrome.sniff(tmp_path / "Autofill.json") and not chrome.sniff(tmp_path)


def test_every_visit_and_bookmark_is_a_line_and_the_envelope_is_complete():
    counts: dict[str, int] = {}
    lines = list(chrome.run(FIX, timezone=TZ, counts=counts))
    assert len(lines) == 6  # 3 visits + 3 bookmarks
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["kind"] == "browse" and line["source"] == "google-takeout" and line["tier"] == 2
        assert line["end"] is None and line["tz"] == TZ
        assert line["payload"]["schema"] == "browse/v1" and line["payload"]["browser"] == "chrome"
    assert counts == {"skipped_no_timestamp": 2, "skipped_no_url": 1}
    assert [line["at"] for line in lines] == sorted(line["at"] for line in lines)


def test_a_history_entry_maps_url_title_time_and_transition():
    by = {line["payload"]["raw_id"]: line for line in _lines(HISTORY)}
    url = "https://vans.example.org/booking/42"
    line = by[f"chrome:1770796800000000:{_digest(url)}"]
    assert line["at"] == "2026-02-11T08:00:00Z"
    assert line["payload"] == {
        "schema": "browse/v1",
        "raw_id": f"chrome:1770796800000000:{_digest(url)}",
        "url": url,
        "title": "Van hire - Oslo",
        "action": "visit",
        "browser": "chrome",
        "transition": "typed",
    }
    confirmed = by[f"chrome:1770796860500000:{_digest(url + '/confirmed')}"]["payload"]
    assert confirmed["extra"] == {"transition_qualifier": "client_redirect"}
    assert "client_id" not in confirmed.get("extra", {})  # a sync id, not the owner's
    reload = by[f"chrome:1772614800000000:{_digest('https://havn.example.org/')}"]["payload"]
    assert "title" not in reload and reload["transition"] == "reload"


def test_a_bookmark_maps_url_title_folder_and_add_date():
    by = {line["payload"]["url"]: line for line in _lines(BOOKMARKS)}
    chart = by["https://charts.example.org/oslofjord"]
    assert chart["at"] == "2026-03-04T09:00:00Z"
    assert chart["payload"] == {
        "schema": "browse/v1",
        "raw_id": f"chrome-bookmark:1772614800:{_digest('https://charts.example.org/oslofjord')}",
        "url": "https://charts.example.org/oslofjord",
        "title": "Oslofjord chart",
        "action": "bookmark",
        "browser": "chrome",
        "folder": "Bookmarks bar/Boat",
    }
    havn = by["https://havn.example.org/"]["payload"]
    assert havn["title"] == "Havnekontoret & co" and havn["folder"] == "Bookmarks bar"
    assert "https://example.org/no-date" not in by  # no instant to put it on (rule 3)


def test_since_cuts_on_at_and_a_visit_and_a_bookmark_of_one_page_are_two_lines():
    later = _lines(since="2026-03-01T00:00:00Z")
    assert {line["payload"]["action"] for line in later} == {"visit", "bookmark"} and len(later) == 2
    url = "https://vans.example.org/booking/42"
    same = [line["payload"]["action"] for line in _lines() if line["payload"]["url"] == url]
    assert sorted(same) == ["bookmark", "visit"]


def test_cli_add_sniffs_the_chrome_folder_and_a_re_add_appends_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "lb"))
    cli.main(["init", str(tmp_path / "lb"), "--timezone", TZ])
    capsys.readouterr()
    cli.main(["add", str(FIX)])
    out = capsys.readouterr().out
    assert "added 6 lines from google-takeout-chrome" in out
    assert "skipped 2 without a timestamp" in out
    assert "1 without a url" in out
    cli.main(["add", str(FIX)])
    assert "added 0 lines from google-takeout-chrome" in capsys.readouterr().out


def test_show_prints_a_visit_by_its_title_or_else_its_url(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "lb"))
    cli.main(["init", str(tmp_path / "lb"), "--timezone", TZ])
    cli.main(["add", str(HISTORY)])
    capsys.readouterr()
    cli.main(["show", "2026-03-04"])
    out = capsys.readouterr().out
    assert "browse" in out and "https://havn.example.org/" in out  # the untitled reload: its url
    cli.main(["show", "2026-02-11"])
    assert "Van hire - Oslo" in capsys.readouterr().out
