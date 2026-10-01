"""A Pocket CSV export → browse/v1 (RFC 0017) `save` lines with tags and status."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters, cli
from logbook.adapters import pocket

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "pocket"
CSV = FIX / "part_000000.csv"
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
TZ = "Europe/Oslo"


def _digest(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _lines(path=CSV, **kw):
    return list(pocket.run(path, timezone=TZ, **kw))


def test_registry_has_pocket_as_a_file_adapter():
    assert adapters.named("pocket") is pocket
    assert isinstance(pocket, adapters.Adapter)
    assert adapters.find(CSV) is pocket and adapters.find(FIX) is pocket


def test_sniff_wants_pockets_header(tmp_path):
    assert pocket.sniff(CSV) and pocket.sniff(FIX)
    assert not pocket.sniff(ROOT / "tests" / "fixtures" / "shazam" / "shazamlibrary.csv")
    assert not pocket.sniff(ROOT / "tests" / "fixtures" / "takeout" / "Saved" / "Want to go.csv")
    assert not pocket.sniff(tmp_path) and not pocket.sniff(tmp_path / "missing.csv")


def test_every_saved_page_is_a_line_and_the_envelope_is_complete():
    counts: dict[str, int] = {}
    lines = list(pocket.run(CSV, timezone=TZ, counts=counts))
    assert len(lines) == 3
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["kind"] == "browse" and line["source"] == "pocket" and line["tier"] == 2
        assert line["end"] is None and line["tz"] == TZ
        p = line["payload"]
        assert p["schema"] == "browse/v1" and p["action"] == "save" and p["browser"] == "pocket"
    assert counts == {"skipped_no_timestamp": 1, "skipped_no_url": 1}
    assert [line["at"] for line in lines] == sorted(line["at"] for line in lines)


def test_a_row_maps_title_url_time_tags_and_status():
    by = {line["payload"]["url"]: line for line in _lines()}
    url = "https://knots.example.org/splice"
    line = by[url]
    assert line["at"] == "2026-02-11T08:00:00Z"
    assert line["payload"] == {
        "schema": "browse/v1",
        "raw_id": f"pocket:1770796800:{_digest(url)}",
        "url": url,
        "title": "Splicing three-strand rope",
        "action": "save",
        "browser": "pocket",
        "tags": ["boat", "rope"],
        "status": "unread",
    }
    guide = by["https://havn.example.org/winter-guide"]["payload"]
    assert guide["title"] == "Oslofjord: a winter guide" and "tags" not in guide
    assert guide["status"] == "archived"
    untitled = by["https://example.org/untitled"]["payload"]
    assert "title" not in untitled and untitled["tags"] == ["reading"]


def test_since_cuts_on_at_and_a_folder_reads_every_part():
    assert [line["payload"]["url"] for line in _lines(since="2026-03-01T00:00:00Z")] == [
        "https://havn.example.org/winter-guide",
        "https://example.org/untitled",
    ]
    assert len(_lines(FIX)) == 3


def test_cli_add_sniffs_the_export_and_a_re_add_appends_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "lb"))
    cli.main(["init", str(tmp_path / "lb"), "--timezone", TZ])
    capsys.readouterr()
    cli.main(["add", str(FIX)])
    out = capsys.readouterr().out
    assert "added 3 lines from pocket" in out and "1 without a timestamp" in out and "1 without a url" in out
    cli.main(["add", str(CSV)])
    assert "added 0 lines from pocket" in capsys.readouterr().out
