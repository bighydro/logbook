"""Google Takeout Access Log Activity/ → event/v1 at tier 3 (RFC 0009): one line per access to a Google
service, device and location when the row has them. Every address here is a documentation range."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters, cli
from logbook.adapters.takeout import access_log
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "takeout" / "Access Log Activity"
CSV = FIX / "Activities - A list of Google services accessed by.csv"
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
TZ = "Europe/Oslo"
AGENT = "Mozilla/5.0 (iPhone; CPU iPhone OS 19_0 like Mac OS X) AppleWebKit/605.1.15"


def _lines(path=FIX, **kw):
    return list(access_log.run(path, timezone=TZ, **kw))


def test_registry_has_access_log_as_a_file_adapter_under_both_names():
    assert adapters.named("google-takeout-access-log") is access_log
    assert adapters.named("takeout-access-log") is access_log
    assert isinstance(access_log, adapters.Adapter)
    assert adapters.find(FIX) is access_log and adapters.find(CSV) is access_log


def test_sniff_recognises_the_activities_csv_and_nothing_else(tmp_path):
    assert access_log.sniff(CSV) and access_log.sniff(FIX)
    assert not access_log.sniff(ROOT / "tests" / "fixtures" / "takeout" / "Google Meet")
    assert not access_log.sniff(ROOT / "tests" / "fixtures" / "pocket" / "part_000000.csv")
    assert not access_log.sniff(tmp_path) and not access_log.sniff(tmp_path / "x.csv")


def test_every_access_is_a_line_at_tier_3_and_the_envelope_is_complete():
    counts: dict[str, int] = {}
    lines = list(access_log.run(FIX, timezone=TZ, counts=counts))
    assert len(lines) == 4  # two accesses in the same second from two addresses are two lines
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["kind"] == "event" and line["source"] == "google-takeout" and line["tier"] == 3
        assert line["end"] is None and line["tz"] == TZ
        p = line["payload"]
        assert p["schema"] == "event/v1" and p["all_day"] is False
        assert p["calendar"] == {"id": "google-access-log", "name": "Google Account access"}
    assert counts == {"skipped_no_timestamp": 1}
    assert [line["at"] for line in lines] == sorted(line["at"] for line in lines)
    assert len({line["payload"]["raw_id"] for line in lines}) == 4


def test_device_and_location_are_kept_when_present_and_left_out_when_not():
    by = {line["payload"]["title"] + line["payload"].get("location", ""): line for line in _lines()}
    signin = by["Gmail: Sign inOslo, NO"]
    digest = hashlib.sha256(f"Gmail|Sign in|203.0.113.7|{AGENT}".encode()).hexdigest()[:16]
    assert signin["at"] == "2026-06-10T06:58:03Z"
    assert signin["payload"] == {
        "schema": "event/v1",
        "raw_id": f"access-log:2026-06-10T06:58:03.412Z:{digest}",
        "title": "Gmail: Sign in",
        "calendar": {"id": "google-access-log", "name": "Google Account access"},
        "all_day": False,
        "location": "Oslo, NO",
        "extra": {
            "product": "Gmail",
            "activity": "Sign in",
            "ip": "203.0.113.7",
            "user_agent": AGENT,
            "device": {"type": "Mobile", "model": "iPhone"},
            "country": "NO",
            "city": "Oslo",
        },
    }
    password = by["Google Account: Password changeZurich, CH"]["payload"]
    assert password["extra"]["device"] == {"type": "Desktop"}
    drive = next(line["payload"] for line in _lines() if line["payload"]["title"] == "Google Drive: Access")
    assert "location" not in drive and "device" not in drive["extra"] and "country" not in drive["extra"]


def test_since_cuts_on_at():
    assert len(_lines(since="2026-06-16T00:00:00Z")) == 2


def test_the_source_is_off_by_default_and_runs_once_the_owner_opts_in(tmp_path, capsys, monkeypatch):
    import json

    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "lb"))
    cli.main(["init", str(tmp_path / "lb"), "--timezone", TZ])
    lb = Logbook.find()
    capsys.readouterr()
    cli.main(["add", str(FIX)])
    out = capsys.readouterr().out
    assert (
        "google-takeout-access-log: disabled (every sign-in to every Google service; opt in); skipped" in out
    )
    assert lb.meta["seq"] == 0
    path = lb.root / "policy" / "import.json"
    listed = json.loads(path.read_text(encoding="utf-8"))
    listed["disabled"] = [e for e in listed["disabled"] if e["source"] != "google-takeout-access-log"]
    path.write_text(json.dumps(listed), encoding="utf-8")
    cli.main(["add", "takeout-access-log", str(FIX), "--dry-run"])
    out = capsys.readouterr().out
    assert "google-takeout-access-log: 4 lines would be added, 0 already in the record (dry run" in out
    cli.main(["add", str(FIX)])
    assert "added 4 lines from google-takeout-access-log" in capsys.readouterr().out
    cli.main(["add", str(FIX)])
    assert "added 0 lines from google-takeout-access-log" in capsys.readouterr().out
