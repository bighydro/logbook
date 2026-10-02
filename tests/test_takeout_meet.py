"""Google Takeout Google Meet/ → call/v1 (RFC 0012): one line per call in the call history, the owner
from `owner_emails`. Everyone here is synthetic."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters, cli
from logbook.adapters.takeout import meet
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "takeout" / "Google Meet"
CSV = FIX / "Call history" / "Call history.csv"
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
TZ = "Europe/Oslo"
OWNER = ["per.persona@example.org"]


def _lines(path=FIX, **kw):
    return list(meet.run(path, timezone=TZ, owner_emails=OWNER, **kw))


def test_registry_has_meet_as_a_file_adapter_under_both_names():
    assert adapters.named("google-takeout-meet") is meet and adapters.named("takeout-meet") is meet
    assert isinstance(meet, adapters.Adapter)
    assert adapters.find(FIX) is meet and adapters.find(CSV) is meet and adapters.find(CSV.parent) is meet


def test_sniff_recognises_the_call_history_and_nothing_else(tmp_path):
    assert meet.sniff(CSV) and meet.sniff(FIX)
    assert not meet.sniff(ROOT / "tests" / "fixtures" / "pocket" / "part_000000.csv")
    assert not meet.sniff(tmp_path) and not meet.sniff(tmp_path / "x.csv")
    (tmp_path / "x.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    assert not meet.sniff(tmp_path / "x.csv")


def test_every_call_is_a_line_and_the_envelope_is_complete():
    counts: dict[str, int] = {}
    lines = list(meet.run(FIX, timezone=TZ, owner_emails=OWNER, counts=counts))
    assert len(lines) == 4
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["kind"] == "call" and line["source"] == "google-takeout" and line["tier"] == 1
        assert line["tz"] == TZ and line["payload"]["schema"] == "call/v1"
        assert line["payload"]["service"] == "meet" and line["payload"]["answered"] is True
    assert counts == {"skipped_no_timestamp": 1, "no_conference_id": 1}
    assert [line["at"] for line in lines] == sorted(line["at"] for line in lines)


def test_direction_follows_the_organizer_and_the_counterparty_is_the_organizer_when_not_me():
    by = {line["payload"]["raw_id"]: line for line in _lines()}
    mine = by["meet:c-7a1b2c3d4e5f"]
    assert mine["at"] == "2026-06-11T14:00:00Z" and mine["end"] == "2026-06-11T14:30:12Z"
    assert mine["payload"] == {
        "schema": "call/v1",
        "raw_id": "meet:c-7a1b2c3d4e5f",
        "direction": "outgoing",
        "answered": True,
        "duration_s": 1812,
        "service": "meet",
        "extra": {
            "role": "organizer",
            "meeting_code": "abc-defg-hij",
            "participants": 2,
            "product": "Google Meet",
            "device_type": "Desktop",
            "call_type": "Video",
        },
    }
    theirs = by["meet:c-8b2c3d4e5f60"]["payload"]
    assert theirs["direction"] == "incoming" and theirs["extra"]["role"] == "participant"
    assert theirs["counterparty"] == {"kind": "email", "value": "kari.nordmann@example.org"}
    alone = by["meet:c-9c3d4e5f6071"]
    assert alone["end"] is None and alone["payload"]["duration_s"] == 0  # nobody joined; still answered
    digest = hashlib.sha256(b"2026-06-18T09:00:00Z|ola@example.org").hexdigest()[:16]
    no_id = by[f"meet:2026-06-18T09:00:00Z:{digest}"]["payload"]
    assert no_id["counterparty"]["value"] == "ola@example.org" and "meeting_code" not in no_id["extra"]


def test_without_owner_emails_every_call_is_incoming_and_that_is_counted():
    counts: dict[str, int] = {}
    lines = list(meet.run(CSV, timezone=TZ, counts=counts))
    assert counts["no_owner"] == 1
    assert all(line["payload"]["direction"] == "incoming" for line in lines)


def test_since_cuts_on_at():
    first = next(iter(_lines(since="2026-06-17T00:00:00Z")))
    assert first["payload"]["raw_id"] == "meet:c-9c3d4e5f6071"


def test_cli_add_uses_owner_emails_dry_run_writes_nothing_and_a_re_add_appends_nothing(
    tmp_path, capsys, monkeypatch
):
    import json

    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "lb"))
    cli.main(["init", str(tmp_path / "lb"), "--timezone", TZ])
    lb = Logbook.find()
    meta = json.loads((lb.root / "logbook.json").read_text(encoding="utf-8"))
    meta["owner_emails"] = OWNER
    (lb.root / "logbook.json").write_text(json.dumps(meta), encoding="utf-8")
    capsys.readouterr()
    cli.main(["add", "takeout-meet", str(FIX), "--dry-run"])
    out = capsys.readouterr().out
    assert "google-takeout-meet: 4 lines would be added, 0 already in the record (dry run" in out
    assert lb.meta["seq"] == 0
    cli.main(["add", str(FIX)])
    out = capsys.readouterr().out
    assert "added 4 lines from google-takeout-meet" in out and "1 without a conference id" in out
    cli.main(["add", str(FIX)])
    assert "added 0 lines from google-takeout-meet" in capsys.readouterr().out
