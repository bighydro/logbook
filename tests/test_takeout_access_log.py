"""Google Takeout Access Log Activity/ → event/v1 at tier 3 (RFC 0009): one line per access to a Google
service, device and location when the row has them. Every address here is a documentation range."""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import cli
from logbook.contrib import adapters
from logbook.contrib.adapters.takeout import access_log
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "takeout" / "Access Log Activity"
CSV = FIX / "Activities - A list of Google services accessed by.csv"
FIX_2026 = ROOT / "tests" / "fixtures" / "takeout-2026-10" / "Access Log Activity"
CSV_2026 = FIX_2026 / "Activities - A list of Google services accessed by.csv"
DEVICES = FIX_2026 / "Devices - A list of devices (i.e. Nest, Pixel, iPhone, etc.) used to access.csv"
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
TZ = "Europe/Oslo"
AGENT = "Mozilla/5.0 (iPhone; CPU iPhone OS 19_0 like Mac OS X) AppleWebKit/605.1.15"


def _lines(path=FIX, **kw):
    return list(access_log.run(path, timezone=TZ, **kw))


def _without_digest(line) -> str:
    """The line as text, `raw_id` held to its shape and left out: its sixteen hex characters could
    spell a digit-only secret (the account id) by chance, as the wallet test once saw in a hash."""
    assert re.fullmatch(r"access-log:.+:[0-9a-f]{16}", line["payload"]["raw_id"]), line["payload"]["raw_id"]
    return repr({**line, "payload": {k: v for k, v in line["payload"].items() if k != "raw_id"}})


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


def test_device_and_location_are_kept_when_present_and_the_address_and_agent_never_are():
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
            "device": {"type": "Mobile", "model": "iPhone"},
            "country": "NO",
            "city": "Oslo",
        },
    }
    password = by["Google Account: Password changeZurich, CH"]["payload"]
    assert password["extra"]["device"] == {"type": "Desktop"}
    drive = next(line["payload"] for line in _lines() if line["payload"]["title"] == "Google Drive: Access")
    assert "location" not in drive and "device" not in drive["extra"] and "country" not in drive["extra"]
    for line in _lines():  # the address and the browser are hashed into the id, never written
        text = _without_digest(line)
        assert "203.0.113" not in text and "198.51.100" not in text and "Mozilla" not in text


def test_the_2026_export_reads_every_row_with_its_coarse_place_and_never_the_address_or_account():
    counts: dict[str, int] = {}
    lines = list(access_log.run(FIX_2026, timezone=TZ, counts=counts))
    assert len(lines) == 5 and counts == {"skipped_no_timestamp": 1}
    assert [line["at"] for line in lines] == [
        "2026-10-01T06:59:59Z",
        "2026-10-01T07:00:00Z",
        "2026-10-02T18:30:15Z",
        "2026-10-03T09:15:00Z",
        "2026-10-03T09:15:00Z",
    ]
    assert len({line["payload"]["raw_id"] for line in lines}) == 5  # two addresses in one second: two lines
    signin = lines[0]["payload"]
    assert signin["raw_id"].startswith("access-log:2026-10-01 06:59:59 UTC:")
    assert signin["title"] == "Gmail: Sign in" and signin["location"] == "Oslo, NO"
    assert signin["extra"] == {
        "product": "Gmail",
        "sub_product": "Gmail Mobile",
        "activity": "Sign in",
        "channel": "WEB",
        "country": "NO",
        "region": "Oslo",
        "city": "Oslo",
    }
    imap = lines[1]["payload"]
    assert imap["location"] == "Nesodden, Akershus, NO" and imap["extra"]["channel"] == "IMAP"
    assert "sub_product" not in imap["extra"]
    password = lines[2]["payload"]
    assert password["title"] == "Google Account: Password change" and password["location"] == "Zurich, CH"
    assert "device" not in password["extra"] and "channel" not in password["extra"]
    drive = lines[3]["payload"]
    assert "location" not in drive and "country" not in drive["extra"]
    for line in lines:
        text = _without_digest(line)
        assert "203.0.113" not in text and "198.51.100" not in text and "10.0.0.5" not in text
        assert "Mozilla" not in text and "000000000000000000001" not in text and "Gaia" not in text
        assert "ip" not in line["payload"]["extra"] and "user_agent" not in line["payload"]["extra"]


def test_the_devices_csv_is_not_the_log_and_is_ignored_beside_it():
    assert access_log.sniff(CSV_2026) and access_log.sniff(FIX_2026)
    assert not access_log.sniff(DEVICES)
    assert adapters.find(DEVICES) is None
    assert len(list(access_log.run(FIX_2026, timezone=TZ))) == 5
    assert len(list(access_log.run(CSV_2026, timezone=TZ))) == 5


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
