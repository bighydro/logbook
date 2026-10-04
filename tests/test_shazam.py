"""Shazam's library CSV → listen/v1 (RFC 0019): one track per row, zoneless tag times in the record's zone."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import cli
from logbook.contrib import adapters
from logbook.contrib.adapters import shazam

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "tests" / "fixtures" / "shazam" / "shazamlibrary.csv"
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
TZ = "Europe/Oslo"


def _lines(**kw):
    return list(shazam.run(CSV, timezone=TZ, **kw))


def test_registry_has_shazam_as_a_file_adapter():
    assert adapters.named("shazam") is shazam
    assert isinstance(shazam, adapters.Adapter)
    assert adapters.find(CSV) is shazam


def test_sniff_wants_the_title_line_or_the_header(tmp_path):
    assert shazam.sniff(CSV)
    headed = tmp_path / "export.csv"
    headed.write_text("Index,TagTime,Title,Artist,URL,TrackKey\n", encoding="utf-8")
    assert shazam.sniff(headed)
    assert not shazam.sniff(ROOT / "tests" / "fixtures" / "takeout" / "Saved" / "Want to go.csv")
    assert not shazam.sniff(tmp_path) and not shazam.sniff(tmp_path / "missing.csv")


def test_every_timed_titled_row_is_a_line_and_the_envelope_is_complete():
    counts: dict[str, int] = {}
    lines = list(shazam.run(CSV, timezone=TZ, counts=counts))
    assert len(lines) == 3
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["kind"] == "listen" and line["source"] == "shazam" and line["tier"] == 2
        assert line["end"] is None and line["tz"] == TZ
        assert line["payload"]["schema"] == "listen/v1" and line["payload"]["media"] == "track"
    assert counts == {"skipped_no_timestamp": 1, "skipped_no_title": 1}
    assert [line["at"] for line in lines] == sorted(line["at"] for line in lines)


def test_a_row_maps_title_artist_url_and_the_tag_time_in_the_records_zone():
    by = {line["payload"]["title"]: line for line in _lines()}
    line = by["Fjordsang"]
    assert line["at"] == "2026-03-04T20:15:30Z"  # 21:15:30 in Oslo (CET)
    assert line["payload"] == {
        "schema": "listen/v1",
        "raw_id": "shazam:100000001:2026-03-04 21:15:30",
        "media": "track",
        "title": "Fjordsang",
        "artist": "Kari Nordmann",
        "url": "https://www.shazam.com/track/100000001/fjordsang",
        "service": "shazam",
        "extra": {"track_key": "100000001"},
    }
    assert by["Rope, Knots & Splices"]["at"] == "2026-02-11T07:00:00Z"  # a `T` reads the same
    assert by["Midnight"]["at"] == "2026-01-01T00:30:00Z"  # a `Z` is read as given (rule 4)
    assert [line["at"] for line in shazam.run(CSV)][-1] == "2026-03-04T21:15:30Z"  # no zone given: UTC


def test_since_cuts_on_at():
    assert [line["payload"]["title"] for line in _lines(since="2026-03-01T00:00:00Z")] == ["Fjordsang"]


def test_cli_add_sniffs_the_export_and_a_re_add_appends_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "lb"))
    cli.main(["init", str(tmp_path / "lb"), "--timezone", TZ])
    capsys.readouterr()
    cli.main(["add", str(CSV)])
    out = capsys.readouterr().out
    assert (
        "added 3 lines from shazam" in out and "1 without a timestamp" in out and "1 without a title" in out
    )
    cli.main(["add", str(CSV)])
    assert "added 0 lines from shazam" in capsys.readouterr().out
