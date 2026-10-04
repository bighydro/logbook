"""Google Takeout Home App/ → event/v1 (RFC 0009): arrivals, departures and the alarm as lines, the
sound events and the alarm clips left alone."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import cli
from logbook.contrib import adapters
from logbook.contrib.adapters.takeout import home

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "takeout" / "Home App"
HISTORY = FIX / "HomeHistory.json"
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
TZ = "Europe/Oslo"


def _lines(path=FIX, **kw):
    return list(home.run(path, timezone=TZ, **kw))


def test_registry_has_home_as_a_file_adapter_and_the_folder_is_its():
    assert adapters.named("google-takeout-home") is home
    assert adapters.named("takeout-home") is home
    assert isinstance(home, adapters.Adapter)
    assert adapters.find(FIX) is home and adapters.find(HISTORY) is home


def test_sniff_recognises_the_history_and_the_folder_and_nothing_else(tmp_path):
    assert home.sniff(HISTORY) and home.sniff(FIX)
    assert not home.sniff(FIX / "SoundSensing") and not home.sniff(FIX / "SecurityAlarmClips")
    assert not home.sniff(FIX / "SoundSensing" / "2026-06-09T03_12_00.json")
    assert not home.sniff(ROOT / "tests" / "fixtures" / "takeout" / "Tasks" / "Tasks.json")
    assert not home.sniff(ROOT / "tests" / "fixtures" / "takeout" / "YouTube and YouTube Music" / "history")
    assert not home.sniff(tmp_path) and not home.sniff(tmp_path / "HomeHistory.json")
    (tmp_path / "HomeHistory.json").write_text("[]", encoding="utf-8")
    assert not home.sniff(tmp_path / "HomeHistory.json")  # nothing in it
    (tmp_path / "HomeHistory.json").write_text('[{"title": "x"}]', encoding="utf-8")
    assert not home.sniff(tmp_path / "HomeHistory.json")  # no time, no event


def test_every_arrival_departure_and_alarm_change_is_a_line_and_the_rest_is_counted():
    counts: dict[str, int] = {}
    lines = _lines(counts=counts)
    assert len(lines) == 7
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["kind"] == "event" and line["source"] == "google-takeout" and line["tier"] == 1
        assert line["end"] is None and line["tz"] == TZ
        assert line["payload"]["schema"] == "event/v1" and line["payload"]["all_day"] is False
        assert line["payload"]["calendar"] == {"id": "google-home", "name": "Google Home"}
    assert counts == {
        "skipped_sound_sensing": 1,
        "skipped_security_alarm_clips": 1,
        "skipped_other_activity": 1,
        "skipped_no_timestamp": 1,
    }
    assert [line["at"] for line in lines] == sorted(line["at"] for line in lines)


def test_an_arrival_a_departure_and_the_alarm_map_to_title_location_and_extra():
    by = {line["payload"]["raw_id"]: line for line in _lines(HISTORY)}
    arrival = by["home:evt-0001"]
    assert arrival["at"] == "2026-06-08T06:40:12Z"
    assert arrival["payload"] == {
        "schema": "event/v1",
        "raw_id": "home:evt-0001",
        "title": "Arrived home",
        "calendar": {"id": "google-home", "name": "Google Home"},
        "all_day": False,
        "location": "Home",
        "extra": {
            "activity": "arrival",
            "event_type": "PRESENCE_CHANGED",
            "structure": "Home",
            "device": "Ines's phone",
            "member": "Ines",
            "description": "Ines arrived home",
        },
    }
    assert by["home:evt-0003"]["payload"]["title"] == "Left home"
    assert by["home:evt-0003"]["payload"]["extra"]["activity"] == "departure"
    armed = by["home:evt-0002"]["payload"]
    assert armed["title"] == "Alarm armed (away)"
    assert armed["extra"]["activity"] == "alarm_armed" and armed["extra"]["level"] == "away"
    assert "member" not in armed["extra"]
    assert by["home:evt-0006"]["payload"]["title"] == "Alarm armed (home)"
    assert by["home:evt-0006"]["payload"]["extra"]["level"] == "home"
    disarmed = by["home:evt-0004"]["payload"]
    assert disarmed["title"] == "Alarm disarmed" and disarmed["extra"]["activity"] == "alarm_disarmed"
    assert disarmed["extra"]["member"] == "Ola"


def test_an_event_with_no_id_is_keyed_by_its_time_and_an_epoch_in_milliseconds_is_read():
    (cabin,) = (line for line in _lines(HISTORY) if line["payload"].get("location") == "Cabin")
    assert cabin["at"] == "2026-06-13T08:00:00Z"
    assert (
        cabin["payload"]["raw_id"].startswith("home:1781337600000:") and len(cabin["payload"]["raw_id"]) == 35
    )
    assert cabin["payload"]["title"] == "Left Cabin" and cabin["payload"]["extra"]["member"] == "Ola"


def test_since_cuts_on_at():
    assert [line["payload"]["title"] for line in _lines(since="2026-06-08T22:00:00Z")] == [
        "Alarm armed (home)",
        "Left Cabin",
    ]


def test_cli_add_sniffs_the_folder_reads_the_history_only_and_a_re_add_appends_nothing(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "lb"))
    cli.main(["init", str(tmp_path / "lb"), "--timezone", TZ])
    capsys.readouterr()
    cli.main(["add", str(FIX)])
    out = capsys.readouterr().out
    assert "added 7 lines from google-takeout-home" in out
    assert "1 sound sensing" in out and "1 security alarm clips" in out
    assert "1 of another activity" in out and "1 without a timestamp" in out
    cli.main(["add", str(FIX)])
    assert "added 0 lines from google-takeout-home" in capsys.readouterr().out


def test_a_home_line_is_evidence_the_day_attaches_to_the_night_at_home(tmp_path, monkeypatch, capsys):
    """The alarm armed at 00:30 local falls inside the owner's stay at home that night: `derive
    stays` attaches it as an event (rule 5) and the night of the 8th is at home (rule 8)."""
    import json

    from persona import HOME, dwell

    from logbook.core import places as named
    from logbook.core.store import Logbook

    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    named.add(lb.root, named.Place("Home", HOME[0], HOME[1], 120.0, "home"))
    lb.append_many([*dwell("2026-06-09", "00:10", "01:00", HOME), *home.run(HISTORY, timezone=TZ)])
    cli.main(["derive", "stays", "--day", "2026-06-08", "--json"])
    data = json.loads(capsys.readouterr().out)
    (stay,) = (s for s in data["segments"] if s["subject"] is None and s["kind"] == "stay")
    assert stay["place"] == "Home" and stay["attached"] == {"event": 1}
    night = next(n for n in data["nights"] if n["day"] == "2026-06-08")
    assert night["home"] is True and night["in_transit"] is False and night["stay"]["id"] == stay["id"]
