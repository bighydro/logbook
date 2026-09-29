"""iCalendar (.ics, RFC 5545) → event/v1: one line per VEVENT, never expanded; folders and Takeout too."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import zoneinfo
from datetime import datetime
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters
from logbook.adapters import dawarich, ics, ios_calendar, ios_contacts, takeout, whatsapp
from logbook.adapters.takeout import calendar as takeout_calendar
from logbook.adapters.takeout import location
from logbook.export import write_day_package
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
DAWARICH = ROOT / "tests" / "fixtures" / "dawarich" / "export.json"
TAKEOUT = ROOT / "tests" / "fixtures" / "takeout" / "Records.json"
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}

SURVEY = "7E0C2D4A-9B1F-4C7E-8A2B-5D3E1F6A9C0B"
AGM = "A1F3C6D9-2B4E-4F7A-9C1D-3E5B7A9C2D4F"
DENTIST = "B7C2D9E4-6F1A-4B3C-8D5E-2A7F9C1B4D6E"
TRAINING = "C4D7E1A2-5B8F-4A3C-9D6E-1F2A3B4C5D6E"
BRIEFING = "D9E2F5A8-1C4B-4E7D-8A3F-6B9C2D5E8F1A"
MODIFIED = "2026-02-27T16:05:00Z"

# A hand-written, synthetic export (the Nordmanns of Oslo do not exist), CRLF-terminated as RFC 5545 writes
# it: a timed event with a TZID, a folded long line, an escaped comma, semicolon and newline, an organizer
# whose CN is quoted, attendees with PARTSTAT and an alarm; an all-day event; a floating-time event; a
# fortnightly master with one RECURRENCE-ID exception; a cancelled event with no end; a VTODO; an event
# with no UID.
CALENDAR = "\r\n".join(
    [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Synthetic//Logbook test//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Sailing club",
        "X-WR-TIMEZONE:Europe/Oslo",
        "BEGIN:VTIMEZONE",
        "TZID:Europe/Oslo",
        "BEGIN:STANDARD",
        "DTSTART:19701025T030000",
        "TZOFFSETFROM:+0200",
        "TZOFFSETTO:+0100",
        "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU",
        "END:STANDARD",
        "BEGIN:DAYLIGHT",
        "DTSTART:19700329T020000",
        "TZOFFSETFROM:+0100",
        "TZOFFSETTO:+0200",
        "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU",
        "END:DAYLIGHT",
        "END:VTIMEZONE",
        "BEGIN:VEVENT",
        f"UID:{SURVEY}",
        "DTSTAMP:20260227T160500Z",
        "CREATED:20260201T100000Z",
        "LAST-MODIFIED:20260227T160500Z",
        "SEQUENCE:2",
        "DTSTART;TZID=Europe/Oslo:20260303T093000",
        "DTEND;TZID=Europe/Oslo:20260303T101500",
        "SUMMARY:Boat survey — Tromsø marina",
        "DESCRIPTION:bring the papers\\, the keys\\nand a flask of coffee for the surv",
        " eyor\; who is always cold",
        "LOCATION:Tromsø småbåthavn",
        "GEO:69.6489;18.9551",
        "STATUS:CONFIRMED",
        'ORGANIZER;CN="Nordmann, Kari":mailto:Kari@Example.org',
        "ATTENDEE;CN=Ola Nordmann;PARTSTAT=ACCEPTED;ROLE=REQ-PARTICIPANT:mailto:ola@example.org",
        "ATTENDEE;PARTSTAT=DECLINED:mailto:ines@example.org",
        "ATTENDEE;CN=Kalle;PARTSTAT=DELEGATED:mailto:kalle@example.org",
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        "TRIGGER:-PT15M",
        "DESCRIPTION:Reminder",
        "END:VALARM",
        "END:VEVENT",
        "BEGIN:VEVENT",
        f"UID:{AGM}",
        "DTSTAMP:20260220T090000Z",
        "DTSTART;VALUE=DATE:20260307",
        "DTEND;VALUE=DATE:20260308",
        "SUMMARY:Sailing club AGM",
        "TRANSP:TRANSPARENT",
        "END:VEVENT",
        "BEGIN:VEVENT",
        f"UID:{DENTIST}",
        "DTSTAMP:20260301T110000Z",
        "DTSTART:20260310T100000",
        "DTEND:20260310T103000",
        "SUMMARY:Dentist",
        "END:VEVENT",
        "BEGIN:VEVENT",
        f"UID:{TRAINING}",
        "DTSTAMP:20260221T120000Z",
        "LAST-MODIFIED:20260221T120000Z",
        "DTSTART;TZID=Europe/Oslo:20260303T180000",
        "DTEND;TZID=Europe/Oslo:20260303T193000",
        "RRULE:FREQ=WEEKLY;INTERVAL=2;COUNT=10;BYDAY=TU,TH",
        "EXDATE;TZID=Europe/Oslo:20260331T180000",
        "SUMMARY:Crew training",
        "END:VEVENT",
        "BEGIN:VEVENT",
        f"UID:{TRAINING}",
        "RECURRENCE-ID;TZID=Europe/Oslo:20260317T180000",
        "DTSTAMP:20260310T080000Z",
        "LAST-MODIFIED:20260310T080000Z",
        "DTSTART;TZID=Europe/Oslo:20260317T190000",
        "DTEND;TZID=Europe/Oslo:20260317T203000",
        "SUMMARY:Crew training (moved)",
        "END:VEVENT",
        "BEGIN:VEVENT",
        f"UID:{BRIEFING}",
        "DTSTAMP:20260304T200000Z",
        "LAST-MODIFIED:20260304T200000Z",
        "DTSTART;TZID=Europe/Oslo:20260305T170000",
        "SUMMARY:Regatta briefing",
        "STATUS:CANCELLED",
        "END:VEVENT",
        "BEGIN:VTODO",
        "UID:E5F8B1C4-7A2D-4C6E-9B3F-8D1A4E7C2B5F",
        "DTSTAMP:20260301T090000Z",
        "DUE;VALUE=DATE:20260320",
        "SUMMARY:Varnish the tiller",
        "END:VTODO",
        "BEGIN:VEVENT",
        "DTSTAMP:20260302T110000Z",
        "DTSTART;TZID=Europe/Oslo:20260312T190000",
        "DTEND;TZID=Europe/Oslo:20260312T210000",
        "SUMMARY:Dinner",
        "END:VEVENT",
        "END:VCALENDAR",
        "",
    ]
)
TITLES = [
    "Boat survey — Tromsø marina",
    "Sailing club AGM",
    "Dentist",
    "Crew training",
    "Crew training (moved)",
    "Regatta briefing",
]


def _export(tmp_path: Path, name: str = "sailing.ics", text: str = CALENDAR) -> Path:
    p = tmp_path / name
    p.write_bytes(text.encode("utf-8"))
    return p


def _by_title(lines: list[dict]) -> dict[str, dict]:
    return {line["payload"]["title"]: line for line in lines}


def _calendar(*events: str, head: str = "X-WR-CALNAME:Personal") -> str:
    """A calendar around the given VEVENT bodies (each a string of property lines)."""
    body = "".join(f"BEGIN:VEVENT\n{event.strip()}\nEND:VEVENT\n" for event in events)
    return f"BEGIN:VCALENDAR\nVERSION:2.0\n{head}\n{body}END:VCALENDAR\n"


def _one(
    tmp_path: Path, *lines: str, timezone: str | None = "Europe/Oslo", head: str = "X-WR-CALNAME:Personal"
):
    """One VEVENT built from `lines` (a UID, DTSTAMP and SUMMARY are added unless given), run; the lines."""
    given_names = {line.split(":", 1)[0].split(";", 1)[0].upper() for line in lines}
    defaults = [
        line
        for line in ("UID:U-1", "DTSTAMP:20260301T110000Z", "SUMMARY:one")
        if line.split(":", 1)[0] not in given_names
    ]
    p = _export(tmp_path, "one.ics", _calendar("\n".join([*defaults, *lines]), head=head))
    counts: dict[str, int] = {}
    lines_out = list(ics.run(p, counts=counts, timezone=timezone))
    return lines_out, counts


def _only(
    tmp_path: Path, *lines: str, timezone: str | None = "Europe/Oslo", head: str = "X-WR-CALNAME:Personal"
):
    lines_out, counts = _one(tmp_path, *lines, timezone=timezone, head=head)
    assert counts == {} and len(lines_out) == 1
    return lines_out[0]


def _day_package(tmp_path: Path) -> Path:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    lb.append(
        at="2026-03-01T07:30:00Z",
        source="sim-phone",
        kind="location",
        tier=1,
        payload={"schema": "location/v1", "lat": 59.911, "lon": 10.75},
    )
    out = tmp_path / "pkg"
    write_day_package(lb, "2026-03-01", out)
    return out / "package.json"


# -- registry ---------------------------------------------------------------


def test_registry_lists_ics():
    assert "ics" in [a.NAME for a in adapters.all_adapters()]


def test_registry_find_returns_ics_for_an_icalendar_file(tmp_path):
    found = adapters.find(_export(tmp_path))
    assert found is not None and found.NAME == "ics"


def test_registry_find_by_content_not_by_extension(tmp_path):
    found = adapters.find(_export(tmp_path, "basic"))
    assert found is not None and found.NAME == "ics"
    found = adapters.find(_export(tmp_path, "invite.txt"))
    assert found is not None and found.NAME == "ics"


def test_other_adapters_reject_the_icalendar_file(tmp_path):
    p = _export(tmp_path)
    assert dawarich.sniff(p) is False and location.sniff(p) is False
    assert ios_contacts.sniff(p) is False and whatsapp.sniff(p) is False and ios_calendar.sniff(p) is False


# -- sniff ------------------------------------------------------------------


def test_sniff_accepts_a_file_starting_with_begin_vcalendar(tmp_path):
    assert ics.sniff(_export(tmp_path)) is True
    assert ics.sniff(_export(tmp_path, "lf.ics", CALENDAR.replace("\r\n", "\n"))) is True


def test_sniff_tolerates_a_byte_order_mark_and_leading_blank_lines(tmp_path):
    assert ics.sniff(_export(tmp_path, "bom.ics", "﻿" + CALENDAR)) is True
    assert ics.sniff(_export(tmp_path, "blank.ics", "\r\n\r\n" + CALENDAR)) is True
    assert ics.sniff(_export(tmp_path, "lower.ics", "begin:vcalendar\nend:vcalendar\n")) is True


def test_sniff_rejects_other_exports(tmp_path):
    assert ics.sniff(DAWARICH) is False
    assert ics.sniff(TAKEOUT) is False
    assert ics.sniff(_day_package(tmp_path)) is False


@pytest.mark.parametrize(
    "content",
    ["", "just words\n", "BEGIN:VEVENT\nEND:VEVENT\n", "VERSION:2.0\nBEGIN:VCALENDAR\n", "{}", "BEGIN:VCAL"],
)
def test_sniff_rejects_files_that_do_not_start_with_the_calendar(tmp_path, content):
    p = tmp_path / "file.ics"
    p.write_text(content, encoding="utf-8")
    assert ics.sniff(p) is False


def test_sniff_rejects_binary_junk(tmp_path):
    p = tmp_path / "file.ics"
    p.write_bytes(b"\xff\xfe\x00BEGIN:VCALENDAR")
    assert ics.sniff(p) is False


def test_sniff_rejects_missing_file_and_a_folder_without_calendars(tmp_path):
    assert ics.sniff(tmp_path / "nope.ics") is False
    assert ics.sniff(tmp_path) is False
    (tmp_path / "notes.txt").write_text("just words\n", encoding="utf-8")
    assert ics.sniff(tmp_path) is False


def test_sniff_and_run_never_touch_the_source(tmp_path):
    p = _export(tmp_path)
    before = p.read_bytes()
    assert ics.sniff(p) is True
    list(ics.run(p))
    assert p.read_bytes() == before
    assert sorted(q.name for q in tmp_path.iterdir()) == [p.name]


# -- run: envelope ------------------------------------------------------------


def test_run_yields_one_event_line_per_vevent_with_the_source_span(tmp_path):
    lines = list(ics.run(_export(tmp_path)))
    assert len(lines) == 6
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["source"] == "ics" and line["kind"] == "event" and line["tier"] == 1
        assert line["payload"]["schema"] == "event/v1"
    survey = _by_title(lines)["Boat survey — Tromsø marina"]
    assert survey["at"] == "2026-03-03T08:30:00Z" and survey["end"] == "2026-03-03T09:15:00Z"
    assert survey["tz"] == "Europe/Oslo"


def test_run_streams_in_file_order(tmp_path):
    assert [line["payload"]["title"] for line in ics.run(_export(tmp_path))] == TITLES


def test_run_honours_since(tmp_path):
    p = _export(tmp_path)
    lines = list(ics.run(p, since="2026-03-07T00:00:00Z"))
    assert [line["payload"]["title"] for line in lines] == [
        "Sailing club AGM",
        "Dentist",
        "Crew training (moved)",
    ]
    lines = list(ics.run(p, since="2026-03-07T00:00:00Z", timezone="Europe/Oslo"))
    assert [line["payload"]["title"] for line in lines] == ["Dentist", "Crew training (moved)"]


def test_run_skips_and_counts_todos_and_events_without_a_uid(tmp_path):
    counts: dict[str, int] = {}
    lines = list(ics.run(_export(tmp_path), counts=counts))
    assert "Dinner" not in _by_title(lines) and "Varnish the tiller" not in _by_title(lines)
    assert counts == {"skipped_todo": 1, "skipped_no_uid": 1}


def test_run_reads_lf_endings_and_a_byte_order_mark_alike(tmp_path):
    crlf = list(ics.run(_export(tmp_path, "crlf.ics")))
    lf = list(ics.run(_export(tmp_path, "lf.ics", CALENDAR.replace("\r\n", "\n"))))
    bom = list(ics.run(_export(tmp_path, "bom.ics", "﻿" + CALENDAR)))
    for lines in (lf, bom):
        for got, want in zip(lines, crlf, strict=True):
            assert {k: v for k, v in got["payload"].items() if k != "calendar"} == {
                k: v for k, v in want["payload"].items() if k != "calendar"
            }


# -- run: the timed event -----------------------------------------------------------


def test_run_timed_event_payload(tmp_path):
    p = _by_title(list(ics.run(_export(tmp_path))))["Boat survey — Tromsø marina"]["payload"]
    assert p["raw_id"] == f"{SURVEY}@{MODIFIED}"
    assert p["modified_at"] == MODIFIED
    assert p["title"] == "Boat survey — Tromsø marina"
    assert p["calendar"] == {"id": "Sailing club", "name": "Sailing club"}
    assert p["all_day"] is False
    assert p["status"] == "confirmed"
    assert p["location"] == "Tromsø småbåthavn"
    assert p["extra"]["location"] == {"latitude": 69.6489, "longitude": 18.9551}
    assert "recurrence" not in p and "recurrence_of" not in p


def test_run_unfolds_the_long_line_and_unescapes_comma_semicolon_and_newline(tmp_path):
    p = _by_title(list(ics.run(_export(tmp_path))))["Boat survey — Tromsø marina"]["payload"]
    assert (
        p["notes"] == "bring the papers, the keys\nand a flask of coffee for the surveyor; who is always cold"
    )


def test_run_unescapes_backslash_and_upper_case_newline(tmp_path):
    line = _only(tmp_path, "DTSTART:20260310T100000", "DESCRIPTION:a\\\\b\\Nc\;d\\,e\\x")
    assert line["payload"]["notes"] == "a\\b\nc;d,e\\x"  # an escape we do not know keeps its backslash


def test_run_organizer_and_attendees_are_source_native_refs(tmp_path):
    p = _by_title(list(ics.run(_export(tmp_path))))["Boat survey — Tromsø marina"]["payload"]
    assert p["organizer"] == {"kind": "email", "value": "kari@example.org"}
    assert p["attendees"] == [
        {
            "ref": {"kind": "email", "value": "ola@example.org"},
            "name": "Ola Nordmann",
            "response": "accepted",
        },
        {"ref": {"kind": "email", "value": "ines@example.org"}, "response": "declined"},
        {
            "ref": {"kind": "email", "value": "kalle@example.org"},
            "name": "Kalle",
            "response": "none",
            "extra": {"partstat": "DELEGATED"},
        },
    ]
    assert "organizer_name" not in p


def test_run_attendee_without_partstat_has_no_response_and_tentative_maps(tmp_path):
    line = _only(
        tmp_path,
        "DTSTART:20260310T100000",
        "ATTENDEE:mailto:ola@example.org",
        "ATTENDEE;PARTSTAT=TENTATIVE:mailto:ines@example.org",
        "ATTENDEE;PARTSTAT=NEEDS-ACTION:mailto:kalle@example.org",
        "ATTENDEE;CN=Nobody:https://example.org/nobody",
    )
    assert line["payload"]["attendees"] == [
        {"ref": {"kind": "email", "value": "ola@example.org"}},
        {"ref": {"kind": "email", "value": "ines@example.org"}, "response": "tentative"},
        {"ref": {"kind": "email", "value": "kalle@example.org"}, "response": "none"},
    ]


def test_run_organizer_by_chair_role_when_no_organizer_property(tmp_path):
    line = _only(tmp_path, "DTSTART:20260310T100000", "ATTENDEE;ROLE=CHAIR;CN=Kari:mailto:Kari@Example.org")
    assert line["payload"]["organizer"] == {"kind": "email", "value": "kari@example.org"}
    assert "attendees" not in line["payload"]


def test_run_organizer_that_is_not_a_mailto_is_left_out(tmp_path):
    line = _only(tmp_path, "DTSTART:20260310T100000", "ORGANIZER;CN=Kari:https://example.org/kari")
    assert "organizer" not in line["payload"]


def test_run_cancelled_event_is_a_line_with_no_end(tmp_path):
    line = _by_title(list(ics.run(_export(tmp_path))))["Regatta briefing"]
    assert line["at"] == "2026-03-05T16:00:00Z" and line["end"] is None
    assert line["payload"]["status"] == "cancelled"


def test_run_status_is_case_insensitive_and_an_unknown_one_is_kept_under_extra(tmp_path):
    assert _only(tmp_path, "DTSTART:20260310T100000", "STATUS:tentative")["payload"]["status"] == "tentative"
    p = _only(tmp_path, "DTSTART:20260310T100000", "STATUS:FINAL")["payload"]
    assert "status" not in p and p["extra"]["status"] == "FINAL"


def test_run_calendar_id_is_the_file_name_when_the_calendar_has_no_name(tmp_path):
    line = _only(tmp_path, "DTSTART:20260310T100000", head="PRODID:-//x//y//EN")
    assert line["payload"]["calendar"] == {"id": "one.ics"}


def test_run_modified_at_falls_back_to_dtstamp_then_to_nothing(tmp_path):
    p = _by_title(list(ics.run(_export(tmp_path))))["Sailing club AGM"]["payload"]
    assert p["raw_id"] == f"{AGM}@2026-02-20T09:00:00Z" and p["modified_at"] == "2026-02-20T09:00:00Z"
    p = _only(tmp_path, "UID:U-2", "DTSTART:20260310T100000", "DTSTAMP:")["payload"]
    assert p["raw_id"] == "U-2" and "modified_at" not in p


def test_run_location_geo_out_of_range_or_unparseable_is_left_out(tmp_path):
    p = _only(tmp_path, "DTSTART:20260310T100000", "GEO:91;18.9")["payload"]
    assert "extra" not in p
    p = _only(tmp_path, "DTSTART:20260310T100000", "GEO:north;east", "LOCATION:Tromsø")["payload"]
    assert p["location"] == "Tromsø" and "extra" not in p


# -- run: all-day -----------------------------------------------------------------


def test_run_all_day_event_without_the_record_timezone_stays_at_utc_midnight(tmp_path):
    line = _by_title(list(ics.run(_export(tmp_path))))["Sailing club AGM"]
    assert line["at"] == "2026-03-07T00:00:00Z" and line["end"] == "2026-03-08T00:00:00Z"
    assert line["tz"] is None
    assert line["payload"]["all_day"] is True


def test_run_all_day_event_takes_local_midnight_in_the_record_timezone(tmp_path):
    line = _by_title(list(ics.run(_export(tmp_path), timezone="Europe/Oslo")))["Sailing club AGM"]
    assert line["at"] == "2026-03-06T23:00:00Z" and line["end"] == "2026-03-07T23:00:00Z"
    assert line["tz"] is None  # the record's own
    assert line["payload"]["all_day"] is True


def test_run_all_day_event_with_its_own_zone(tmp_path):
    line = _only(tmp_path, "DTSTART;VALUE=DATE;TZID=America/New_York:20260701", "DTEND;VALUE=DATE:20260702")
    assert line["tz"] == "America/New_York"
    assert line["at"] == "2026-07-01T04:00:00Z" and line["end"] == "2026-07-02T04:00:00Z"


def test_run_all_day_event_end_is_the_next_local_midnight_when_dtend_is_absent(tmp_path):
    line = _only(tmp_path, "DTSTART;VALUE=DATE:20260307")
    assert line["at"] == "2026-03-06T23:00:00Z" and line["end"] == "2026-03-07T23:00:00Z"
    line = _only(tmp_path, "DTSTART;VALUE=DATE:20260307", timezone=None)
    assert line["at"] == "2026-03-07T00:00:00Z" and line["end"] == "2026-03-08T00:00:00Z"


def test_run_all_day_event_spanning_days_and_one_ending_before_it_starts(tmp_path):
    line = _only(tmp_path, "DTSTART;VALUE=DATE:20260307", "DTEND;VALUE=DATE:20260310")
    assert line["at"] == "2026-03-06T23:00:00Z" and line["end"] == "2026-03-09T23:00:00Z"
    line = _only(tmp_path, "DTSTART;VALUE=DATE:20260307", "DTEND;VALUE=DATE:20260307")
    assert line["end"] == "2026-03-07T23:00:00Z"  # an end not after the start is not one (RFC 5545)
    line = _only(tmp_path, "DTSTART;VALUE=DATE:20260307", "DTEND;VALUE=DATE:20260301")
    assert line["end"] == "2026-03-07T23:00:00Z"


def test_run_all_day_event_across_the_daylight_switch_ends_at_the_next_midnight(tmp_path):
    line = _only(tmp_path, "DTSTART;VALUE=DATE:20260329")  # Oslo moves to CEST that night
    assert line["at"] == "2026-03-28T23:00:00Z" and line["end"] == "2026-03-29T22:00:00Z"


def test_run_a_bare_date_without_value_date_is_still_a_day(tmp_path):
    line = _only(tmp_path, "DTSTART:20260307", "DTEND:20260308")
    assert line["payload"]["all_day"] is True
    assert line["at"] == "2026-03-06T23:00:00Z" and line["end"] == "2026-03-07T23:00:00Z"


# -- run: floating, UTC, zones, durations ------------------------------------------------


def test_run_floating_time_is_read_in_the_record_timezone_else_as_utc(tmp_path):
    line = _by_title(list(ics.run(_export(tmp_path), timezone="Europe/Oslo")))["Dentist"]
    assert (
        line["at"] == "2026-03-10T09:00:00Z" and line["end"] == "2026-03-10T09:30:00Z" and line["tz"] is None
    )
    line = _by_title(list(ics.run(_export(tmp_path))))["Dentist"]
    assert (
        line["at"] == "2026-03-10T10:00:00Z" and line["end"] == "2026-03-10T10:30:00Z" and line["tz"] is None
    )


def test_run_utc_times_are_taken_as_given_with_no_zone_of_their_own(tmp_path):
    line = _only(tmp_path, "DTSTART:20260310T100000Z", "DTEND:20260310T103000Z")
    assert (
        line["at"] == "2026-03-10T10:00:00Z" and line["end"] == "2026-03-10T10:30:00Z" and line["tz"] is None
    )


def test_run_unknown_tzid_falls_back_to_the_record_and_keeps_the_text(tmp_path):
    line = _only(tmp_path, "DTSTART;TZID=W. Europe Standard Time:20260310T100000")
    assert line["at"] == "2026-03-10T09:00:00Z" and line["tz"] is None
    assert line["payload"]["extra"]["tzid"] == "W. Europe Standard Time"


def test_run_prefixed_tzid_is_read_by_its_zone_suffix(tmp_path):
    line = _only(tmp_path, "DTSTART;TZID=/mozilla.org/20050126_1/Europe/Oslo:20260310T100000")
    assert (
        line["at"] == "2026-03-10T09:00:00Z"
        and line["tz"] == "Europe/Oslo"
        and "extra" not in line["payload"]
    )


def test_run_start_and_end_may_name_different_zones(tmp_path):
    line = _only(
        tmp_path, "DTSTART;TZID=Europe/Oslo:20260310T100000", "DTEND;TZID=America/New_York:20260310T100000"
    )
    assert (
        line["at"] == "2026-03-10T09:00:00Z" and line["end"] == "2026-03-10T14:00:00Z"
    )  # New York is on EDT
    assert line["tz"] == "Europe/Oslo"


@pytest.mark.parametrize(
    ("duration", "end"),
    [
        ("PT1H30M", "2026-03-10T10:30:00Z"),
        ("P1D", "2026-03-11T09:00:00Z"),
        ("P1W", "2026-03-17T09:00:00Z"),
        ("PT45S", "2026-03-10T09:00:45Z"),
        ("-PT30M", None),  # an end before the start is not one
        ("PT", None),
        ("bogus", None),
    ],
)
def test_run_duration_gives_the_end_when_dtend_is_absent(tmp_path, duration, end):
    line = _only(tmp_path, "DTSTART;TZID=Europe/Oslo:20260310T100000", f"DURATION:{duration}")
    assert line["at"] == "2026-03-10T09:00:00Z" and line["end"] == end


def test_run_duration_in_days_counts_wall_clock_days_across_the_daylight_switch(tmp_path):
    line = _only(tmp_path, "DTSTART;TZID=Europe/Oslo:20260328T100000", "DURATION:P1D")
    assert line["at"] == "2026-03-28T09:00:00Z" and line["end"] == "2026-03-29T08:00:00Z"
    line = _only(tmp_path, "DTSTART;TZID=Europe/Oslo:20260328T100000", "DURATION:PT24H")
    assert line["end"] == "2026-03-29T09:00:00Z"


def test_run_timed_end_before_the_start_is_dropped_and_equal_is_kept(tmp_path):
    line = _only(tmp_path, "DTSTART:20260310T100000Z", "DTEND:20260310T090000Z")
    assert line["end"] is None
    line = _only(tmp_path, "DTSTART:20260310T100000Z", "DTEND:20260310T100000Z")
    assert line["end"] == "2026-03-10T10:00:00Z"


def test_run_seconds_may_be_absent_and_the_marker_lower_case(tmp_path):
    line = _only(tmp_path, "DTSTART:20260310t1000z")
    assert line["at"] == "2026-03-10T10:00:00Z"


# -- run: skipped events ---------------------------------------------------------


def test_run_skips_and_counts_an_event_without_a_start(tmp_path):
    lines, counts = _one(tmp_path, "SUMMARY:no start")
    assert lines == [] and counts == {"skipped_no_start": 1}


@pytest.mark.parametrize("start", ["DTSTART:tomorrow", "DTSTART:20261340T100000", "DTSTART:", "DTSTART:2026"])
def test_run_skips_and_counts_an_unusable_start(tmp_path, start):
    lines, counts = _one(tmp_path, start)
    assert lines == [] and counts == {"skipped_bad_start": 1}


def test_run_skips_and_counts_a_placeholder_start_before_1900(tmp_path):
    lines, counts = _one(tmp_path, "DTSTART:16010101T000000Z")
    assert lines == [] and counts == {"skipped_placeholder_date": 1}
    line = _only(tmp_path, "DTSTART;VALUE=DATE:19850615")  # a birthday master is a plan the owner keeps
    assert line["at"] == "1985-06-14T22:00:00Z" and line["end"] == "1985-06-15T22:00:00Z"  # Oslo summer time


def test_run_skips_an_all_day_event_whose_next_midnight_does_not_exist(tmp_path):
    lines, counts = _one(tmp_path, "DTSTART;VALUE=DATE:99991231")
    assert lines == [] and counts == {"skipped_bad_start": 1}


def test_run_skips_and_counts_a_blank_uid(tmp_path):
    lines, counts = _one(tmp_path, "UID: ", "DTSTART:20260310T100000")
    assert lines == [] and counts == {"skipped_no_uid": 1}


def test_run_skips_and_counts_journal_entries_and_ignores_other_components(tmp_path):
    text = _calendar("UID:U-1\nDTSTAMP:20260301T110000Z\nDTSTART:20260310T100000\nSUMMARY:one").replace(
        "END:VCALENDAR",
        "BEGIN:VJOURNAL\nUID:J-1\nDTSTART;VALUE=DATE:20260310\nSUMMARY:log\nEND:VJOURNAL\n"
        "BEGIN:VFREEBUSY\nUID:F-1\nEND:VFREEBUSY\nBEGIN:X-WR-SOMETHING\nX-FOO:bar\nEND:X-WR-SOMETHING\n"
        "END:VCALENDAR",
    )
    counts: dict[str, int] = {}
    lines = list(ics.run(_export(tmp_path, "j.ics", text), counts=counts))
    assert [line["payload"]["title"] for line in lines] == ["one"]
    assert counts == {"skipped_journal": 1}


# -- run: recurrence ----------------------------------------------------------------


def test_run_master_carries_the_rule_as_rrule_text_and_its_exdates_under_extra(tmp_path):
    p = _by_title(list(ics.run(_export(tmp_path))))["Crew training"]["payload"]
    assert p["recurrence"] == "FREQ=WEEKLY;INTERVAL=2;COUNT=10;BYDAY=TU,TH"
    assert "recurrence_of" not in p
    assert p["extra"]["exdate"] == ["20260331T180000"]
    assert p["raw_id"] == f"{TRAINING}@2026-02-21T12:00:00Z"


def test_run_exception_points_at_the_master_bare_uid(tmp_path):
    line = _by_title(list(ics.run(_export(tmp_path))))["Crew training (moved)"]
    assert line["at"] == "2026-03-17T18:00:00Z" and line["end"] == "2026-03-17T19:30:00Z"
    p = line["payload"]
    assert p["recurrence_of"] == TRAINING
    assert "recurrence" not in p
    assert p["extra"]["original_date"] == "2026-03-17T17:00:00Z"
    assert p["raw_id"] == f"{TRAINING}/2026-03-17T17:00:00Z@2026-03-10T08:00:00Z"  # not the master's key


def test_run_exception_with_an_all_day_recurrence_id(tmp_path):
    line = _only(tmp_path, "RECURRENCE-ID;VALUE=DATE:20260317", "DTSTART;VALUE=DATE:20260318")
    p = line["payload"]
    assert p["recurrence_of"] == "U-1" and p["extra"]["original_date"] == "2026-03-16T23:00:00Z"
    assert p["raw_id"] == "U-1/2026-03-16T23:00:00Z@2026-03-01T11:00:00Z"


def test_run_exception_with_an_unreadable_recurrence_id_is_keyed_by_its_text(tmp_path):
    p = _only(tmp_path, "RECURRENCE-ID:whenever", "DTSTART:20260310T100000")["payload"]
    assert p["recurrence_of"] == "U-1" and "extra" not in p
    assert p["raw_id"] == "U-1/whenever@2026-03-01T11:00:00Z"


def test_run_rule_on_an_exception_and_a_rule_without_freq_are_kept_under_extra(tmp_path):
    p = _only(tmp_path, "RECURRENCE-ID:20260317T100000", "DTSTART:20260310T100000", "RRULE:FREQ=DAILY")[
        "payload"
    ]
    assert "recurrence" not in p and p["extra"]["rrule"] == "FREQ=DAILY"
    p = _only(tmp_path, "DTSTART:20260310T100000", "RRULE:INTERVAL=2")["payload"]
    assert "recurrence" not in p and p["extra"]["rrule"] == "INTERVAL=2"


def test_run_rdate_is_kept_under_extra(tmp_path):
    p = _only(
        tmp_path, "DTSTART:20260310T100000", "RDATE:20260311T100000,20260312T100000", "RDATE:20260401T100000"
    )
    assert p["payload"]["extra"]["rdate"] == ["20260311T100000,20260312T100000", "20260401T100000"]


def test_run_master_and_exception_with_the_same_modified_time_never_collide(tmp_path):
    text = _calendar(
        "UID:M-1\nLAST-MODIFIED:20260301T110000Z\nDTSTART:20260310T100000Z\nRRULE:FREQ=DAILY\nSUMMARY:m",
        "UID:M-1\nLAST-MODIFIED:20260301T110000Z\nRECURRENCE-ID:20260311T100000Z\nDTSTART:20260311T110000Z\nSUMMARY:x",
    )
    lines = list(ics.run(_export(tmp_path, "m.ics", text)))
    assert [line["payload"]["raw_id"] for line in lines] == [
        "M-1@2026-03-01T11:00:00Z",
        "M-1/2026-03-11T10:00:00Z@2026-03-01T11:00:00Z",
    ]
    lb = Logbook.init(tmp_path / "lb", "UTC")
    assert lb.append_many(lines) == 2


# -- the parser: tolerant ------------------------------------------------------------


def test_parse_quoted_parameter_values_may_hold_the_delimiters(tmp_path):
    line = _only(
        tmp_path,
        "DTSTART:20260310T100000",
        'ATTENDEE;CN="Nordmann; Ola: skipper";PARTSTAT=ACCEPTED'
        ';MEMBER="mailto:a@example.org","mailto:b@example.org":mailto:ola@example.org',
    )
    assert line["payload"]["attendees"] == [
        {
            "ref": {"kind": "email", "value": "ola@example.org"},
            "name": "Nordmann; Ola: skipper",
            "response": "accepted",
        }
    ]


def test_parse_property_names_and_parameters_are_case_insensitive(tmp_path):
    text = (
        "begin:vcalendar\nx-wr-calname:Lower\nbegin:vevent\nuid:U-1\n"
        "dtstart;tzid=Europe/Oslo;value=date-time:20260310T100000\nsummary:one\nend:vevent\nend:vcalendar\n"
    )
    (line,) = ics.run(_export(tmp_path, "lower.ics", text))
    assert line["at"] == "2026-03-10T09:00:00Z" and line["tz"] == "Europe/Oslo"
    assert line["payload"]["title"] == "one" and line["payload"]["calendar"] == {
        "id": "Lower",
        "name": "Lower",
    }


def test_parse_ignores_lines_without_a_colon_and_ends_without_a_begin(tmp_path):
    text = (
        "BEGIN:VCALENDAR\nthis line has no colon\nEND:VEVENT\nBEGIN:VEVENT\nUID:U-1\n"
        "DTSTART:20260310T100000\nSUMMARY:one\n;PARAM=x:no name\nEND:VEVENT\nEND:VCALENDAR\n"
    )
    (line,) = ics.run(_export(tmp_path, "odd.ics", text))
    assert line["payload"]["title"] == "one"


def test_parse_closes_a_component_left_open_at_the_end_of_the_file(tmp_path):
    text = "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:U-1\nDTSTART:20260310T100000\nSUMMARY:cut off"
    (line,) = ics.run(_export(tmp_path, "cut.ics", text))
    assert line["payload"]["title"] == "cut off"


def test_parse_an_outer_end_closes_the_inner_component(tmp_path):
    text = (
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:U-1\nDTSTART:20260310T100000\n"
        "BEGIN:VALARM\nACTION:DISPLAY\nEND:VEVENT\nEND:VCALENDAR\n"
    )
    (line,) = ics.run(_export(tmp_path, "alarm.ics", text))
    assert line["payload"]["raw_id"] == "U-1" and "title" not in line["payload"]


def test_parse_reads_every_calendar_in_a_concatenated_file(tmp_path):
    text = _calendar("UID:U-1\nDTSTART:20260310T100000\nSUMMARY:first", head="X-WR-CALNAME:A") + _calendar(
        "UID:U-2\nDTSTART:20260311T100000\nSUMMARY:second", head="X-WR-CALNAME:B"
    )
    lines = list(ics.run(_export(tmp_path, "two.ics", text)))
    assert [(line["payload"]["title"], line["payload"]["calendar"]["id"]) for line in lines] == [
        ("first", "A"),
        ("second", "B"),
    ]


def test_parse_folding_with_a_tab_and_a_fold_inside_an_escape(tmp_path):
    text = _calendar("UID:U-1\nDTSTART:20260310T100000\nSUMMARY:one two\n\tthree\\\n ,four")
    (line,) = ics.run(_export(tmp_path, "tab.ics", text))
    assert line["payload"]["title"] == "one twothree,four"


def test_parse_undecodable_bytes_do_not_stop_the_file(tmp_path):
    p = tmp_path / "latin.ics"
    p.write_bytes(_calendar("UID:U-1\nDTSTART:20260310T100000\nSUMMARY:Troms\xf8").encode("latin-1"))
    (line,) = ics.run(p)
    assert line["payload"]["title"] == "Troms�"


def test_parse_first_of_a_repeated_property_wins(tmp_path):
    line = _only(tmp_path, "DTSTART:20260310T100000", "DTSTART:20260311T100000", "SUMMARY:a", "SUMMARY:b")
    assert line["at"] == "2026-03-10T09:00:00Z" and line["payload"]["title"] == "a"


# -- folders and Google Takeout ----------------------------------------------------------


def _folder(tmp_path: Path, name: str = "calendars") -> Path:
    folder = tmp_path / name
    folder.mkdir(parents=True)
    _export(folder, "a.ics")
    _export(
        folder, "b.ics", _calendar("UID:U-9\nDTSTART:20260401T100000\nSUMMARY:b", head="PRODID:-//x//y//EN")
    )
    _export(folder, ".hidden.ics")
    (folder / "notes.txt").write_text("just words\n", encoding="utf-8")
    (folder / "nested").mkdir()
    _export(folder / "nested", "c.ics")
    return folder


def test_sniff_accepts_a_folder_holding_icalendar_files(tmp_path):
    assert ics.sniff(_folder(tmp_path)) is True


def test_run_on_a_folder_reads_its_calendar_files_in_name_order_and_nothing_else(tmp_path):
    counts: dict[str, int] = {}
    lines = list(ics.run(_folder(tmp_path), counts=counts, timezone="Europe/Oslo"))
    assert [line["payload"]["title"] for line in lines] == [*TITLES, "b"]
    assert lines[0]["payload"]["calendar"] == {"id": "Sailing club", "name": "Sailing club"}
    assert lines[-1]["payload"]["calendar"] == {"id": "b.ics"}
    assert counts == {"skipped_todo": 1, "skipped_no_uid": 1}


def test_takeout_dispatch_stub_lists_calendar_beside_location():
    assert takeout.SUB_ADAPTERS == ("location", "calendar")
    assert takeout_calendar.NAME == ics.NAME == "ics"


def test_takeout_calendar_sniffs_the_calendar_folder_and_its_files(tmp_path):
    folder = _folder(tmp_path, str(Path("Takeout") / "Calendar"))
    assert takeout_calendar.sniff(folder) is True
    assert takeout_calendar.sniff(folder / "a.ics") is True
    assert takeout_calendar.sniff(_folder(tmp_path, str(Path("Takeout") / "Location History"))) is False
    assert takeout_calendar.sniff(tmp_path / "Takeout" / "Location History" / "a.ics") is False
    empty = tmp_path / "Empty" / "Calendar"
    empty.mkdir(parents=True)
    assert takeout_calendar.sniff(empty) is False
    assert takeout_calendar.sniff(tmp_path / "nope" / "Calendar") is False


def test_takeout_calendar_runs_through_the_ics_adapter(tmp_path):
    folder = _folder(tmp_path, str(Path("Takeout") / "Calendar"))
    counts: dict[str, int] = {}
    lines = list(takeout_calendar.run(folder, counts=counts, timezone="Europe/Oslo"))
    assert lines == list(ics.run(folder, timezone="Europe/Oslo"))
    assert all(line["source"] == "ics" for line in lines)
    assert counts == {"skipped_todo": 1, "skipped_no_uid": 1}


# -- through the log: append, dedupe on re-run, CLI -----------------------------------


def test_run_lines_append_and_re_running_appends_nothing(tmp_path):
    p = _export(tmp_path)
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    assert lb.append_many(ics.run(p, timezone="Europe/Oslo")) == 6
    assert lb.append_many(ics.run(p, timezone="Europe/Oslo")) == 0
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 6
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
        assert line["tz"] == "Europe/Oslo"


def _cli(tmp_path):
    env = {**os.environ, "LOGBOOK_HOME": str(tmp_path / "lb"), "PYTHONPATH": str(ROOT)}

    def run(*a):
        return subprocess.run(
            [sys.executable, "-m", "logbook.cli", *a],
            env=env,
            capture_output=True,
            encoding="utf-8",
            check=True,
        )

    return run


def test_cli_add_reports_lines_and_skips_and_places_all_day_events_in_the_record_zone(tmp_path):
    run = _cli(tmp_path)
    run("init", str(tmp_path / "lb"), "--timezone", "Europe/Oslo")
    p = _export(tmp_path)
    out = run("add", str(p)).stdout
    assert "added 6 lines from ics" in out
    assert "skipped 1 to-do items, 1 without a uid" in out
    assert "added 0 lines from ics" in run("add", str(p)).stdout
    assert "valid — 6 lines" in run("verify").stdout
    lb = Logbook(tmp_path / "lb")
    agm = next(line for line in lb.lines() if line["payload"].get("title") == "Sailing club AGM")
    assert agm["at"] == "2026-03-06T23:00:00Z" and agm["tz"] == "Europe/Oslo"


def test_cli_add_a_takeout_calendar_folder_imports_every_calendar(tmp_path):
    run = _cli(tmp_path)
    run("init", str(tmp_path / "lb"), "--timezone", "Europe/Oslo")
    folder = _folder(tmp_path, str(Path("Takeout") / "Calendar"))
    out = run("add", str(folder)).stdout
    assert "added 6 lines from ics" in out and "added 1 lines from ics" in out
    assert "valid — 7 lines" in run("verify").stdout
    assert "added 0 lines from ics" in run("add", str(folder)).stdout


# -- property: every emitted line is a valid event/v1 observation -------------------

STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
PAYLOAD_KEYS = {
    "schema", "raw_id", "modified_at", "title", "calendar", "all_day", "location", "organizer", "attendees",
    "status", "recurrence", "recurrence_of", "notes", "extra",
}  # fmt: skip


def _rfc_rules(line: dict) -> None:
    assert set(line) == ENVELOPE
    assert line["kind"] == "event" and line["tier"] == 1 and line["source"] == "ics"
    assert STAMP.match(line["at"]) and line["at"] >= "1900-"
    assert line["end"] is None or STAMP.match(line["end"])
    if line["end"] is not None:
        assert line["end"] >= line["at"]
    if line["tz"] is not None:
        zoneinfo.ZoneInfo(line["tz"])
    p = line["payload"]
    assert set(p) <= PAYLOAD_KEYS and {"schema", "raw_id", "all_day", "calendar"} <= set(p)
    assert p["schema"] == "event/v1"
    assert isinstance(p["raw_id"], str) and p["raw_id"]
    assert isinstance(p["all_day"], bool)
    if p["all_day"]:
        assert line["end"] is not None and line["end"] > line["at"]
    for key in ("title", "notes", "location", "recurrence_of", "modified_at", "recurrence"):
        if key in p:
            assert isinstance(p[key], str) and p[key]
    if "modified_at" in p:
        assert STAMP.match(p["modified_at"]) and p["raw_id"].endswith("@" + p["modified_at"])
    assert (
        set(p["calendar"]) - {"name"} == {"id"}
        and isinstance(p["calendar"]["id"], str)
        and p["calendar"]["id"]
    )
    if "organizer" in p:
        assert (
            p["organizer"]["kind"] == "email" and p["organizer"]["value"] == p["organizer"]["value"].lower()
        )
    for a in p.get("attendees", []):
        assert set(a) - {"name", "response", "extra"} == {"ref"}
        assert a["ref"]["kind"] == "email" and a["ref"]["value"] == a["ref"]["value"].strip().lower()
        assert a.get("response", "none") in {"accepted", "declined", "tentative", "none"}
    if "status" in p:
        assert p["status"] in {"confirmed", "tentative", "cancelled"}
    if "recurrence" in p:
        assert any(part.upper().startswith("FREQ=") for part in p["recurrence"].split(";"))
        assert "recurrence_of" not in p
    if "extra" in p:
        assert isinstance(p["extra"], dict) and p["extra"]
    json.dumps(line, allow_nan=False)


_safe = st.text(
    st.characters(blacklist_categories=("Cc", "Cs", "Zl", "Zp"), blacklist_characters='"'), max_size=12
)
_clock = st.datetimes(min_value=datetime(1500, 1, 1), max_value=datetime(2100, 1, 1))
_tzid = st.sampled_from(
    [
        "Europe/Oslo",
        "UTC",
        "America/New_York",
        "W. Europe Standard Time",
        "/mozilla.org/20050126_1/Europe/Oslo",
        "X",
    ]
)
_when = st.one_of(
    _clock.map(lambda d: ("", d.strftime("%Y%m%dT%H%M%SZ"))),
    _clock.map(lambda d: ("", d.strftime("%Y%m%dT%H%M%S"))),
    st.tuples(_tzid, _clock).map(lambda t: (f";TZID={t[0]}", t[1].strftime("%Y%m%dT%H%M%S"))),
    _clock.map(lambda d: (";VALUE=DATE", d.strftime("%Y%m%d"))),
    st.tuples(_tzid, _clock).map(lambda t: (f";TZID={t[0]};VALUE=DATE", t[1].strftime("%Y%m%d"))),
    _safe.map(lambda v: ("", v)),
)
_email = st.one_of(
    st.emails().map(lambda e: "mailto:" + e[:30]),
    st.just("mailto: Ola@Example.org "),
    st.just("mailto:"),
    _safe,
)
_attendee = st.tuples(
    st.one_of(st.none(), _safe),  # CN
    st.one_of(
        st.none(),
        st.sampled_from(["ACCEPTED", "DECLINED", "TENTATIVE", "NEEDS-ACTION", "DELEGATED", "x", ""]),
    ),
    st.sampled_from(["", ";ROLE=CHAIR", ";ROLE=REQ-PARTICIPANT"]),
    _email,
)
_event = st.fixed_dictionaries(
    {},
    optional={
        "UID": _safe,
        "DTSTART": _when,
        "DTEND": _when,
        "DURATION": st.sampled_from(["PT1H", "P1D", "P2W", "-PT30M", "PT", "bogus", "P1DT2H3M4S"]),
        "SUMMARY": _safe,
        "DESCRIPTION": _safe,
        "LOCATION": _safe,
        "GEO": st.sampled_from(["59.9;10.7", "91;0", "x;y", "1", "nan;1", "-90;180"]),
        "STATUS": st.sampled_from(["CONFIRMED", "TENTATIVE", "CANCELLED", "confirmed", "FINAL", ""]),
        "ORGANIZER": st.tuples(st.one_of(st.none(), _safe), _email),
        "ATTENDEE": st.lists(_attendee, max_size=3),
        "RRULE": st.sampled_from(["FREQ=WEEKLY;BYDAY=MO", "FREQ=DAILY;COUNT=3", "INTERVAL=2", "", "x"]),
        "EXDATE": _when,
        "RECURRENCE-ID": _when,
        "LAST-MODIFIED": _when,
        "DTSTAMP": _when,
        "X-CUSTOM": _safe,
    },
)


def _render(event: dict) -> str:
    lines = ["BEGIN:VEVENT"]
    for name, value in event.items():
        if name == "ATTENDEE":
            for cn, partstat, role, address in value:
                params = (f';CN="{cn}"' if cn is not None else "") + (
                    f";PARTSTAT={partstat}" if partstat is not None else ""
                )
                lines.append(f"ATTENDEE{params}{role}:{address}")
        elif name == "ORGANIZER":
            cn, address = value
            lines.append(f"ORGANIZER{f';CN={chr(34)}{cn}{chr(34)}' if cn is not None else ''}:{address}")
        elif isinstance(value, tuple):
            lines.append(f"{name}{value[0]}:{value[1]}")
        else:
            lines.append(f"{name}:{value}")
    lines.append("END:VEVENT")
    return "\r\n".join(lines) + "\r\n"


_calendar_head = st.sampled_from(
    ["", "X-WR-CALNAME:Personal\r\n", "X-WR-CALNAME:\r\n", "X-WR-CALNAME:Regatta\\, 2026\r\n"]
)
_other = st.sampled_from(
    [
        "",
        "BEGIN:VTODO\r\nUID:T\r\nEND:VTODO\r\n",
        "BEGIN:VJOURNAL\r\nUID:J\r\nEND:VJOURNAL\r\n",
        "BEGIN:VTIMEZONE\r\nTZID:X\r\nEND:VTIMEZONE\r\n",
    ]
)


@settings(max_examples=40, deadline=None)
@given(_calendar_head, st.lists(_event, max_size=6), _other, st.sampled_from([None, "Europe/Oslo", "UTC"]))
def test_any_icalendar_file_yields_only_valid_lines(tmp_path_factory, head, events, other, timezone):
    p = tmp_path_factory.mktemp("ics") / "any.ics"
    text = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
        + head
        + other
        + "".join(map(_render, events))
        + "END:VCALENDAR\r\n"
    )
    p.write_text(text, encoding="utf-8", newline="")
    assert ics.sniff(p) is True
    counts: dict[str, int] = {}
    lines = list(ics.run(p, counts=counts, timezone=timezone))
    for line in lines:
        _rfc_rules(line)
    skipped = sum(
        n
        for key, n in counts.items()
        if key.startswith("skipped_") and key not in ("skipped_todo", "skipped_journal")
    )
    assert len(lines) + skipped == len(events)
    lb = Logbook.init(tmp_path_factory.mktemp("lb"), timezone or "UTC")
    appended = lb.append_many(lines)
    assert appended == len({line["payload"]["raw_id"] for line in lines})
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
