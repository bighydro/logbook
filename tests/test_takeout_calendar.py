"""Google Takeout's `Calendar/` folder → event/v1 (RFC 0009) through the `ics` adapter, as a property:
for ANY folder named Calendar holding ANY files — iCalendar texts of any events, and files that are
not calendars at all — `sniff` never raises and claims the folder exactly when a calendar file is
directly in it, and `run` yields only valid lines, the `ics` adapter's own and nothing else, each
appending into a record that verifies and validates against the observation schema. The fixture's
exact lines, and the calendar grammar in depth, are tests/test_ics.py's."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator
from logbook.adapters import ics
from logbook.adapters.takeout import calendar as takeout_calendar
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}

_safe = st.text(
    st.characters(blacklist_categories=("Cc", "Cs", "Zl", "Zp"), blacklist_characters='"'), max_size=12
)
_clock = st.datetimes(min_value=datetime(1500, 1, 1), max_value=datetime(2100, 1, 1))
_when = st.one_of(
    _clock.map(lambda d: d.strftime(":%Y%m%dT%H%M%SZ")),
    _clock.map(lambda d: d.strftime(":%Y%m%dT%H%M%S")),
    _clock.map(lambda d: d.strftime(";TZID=Europe/Oslo:%Y%m%dT%H%M%S")),
    _clock.map(lambda d: d.strftime(";VALUE=DATE:%Y%m%d")),
    _safe.map(lambda v: f":{v}"),
)
_event = st.fixed_dictionaries(
    {},
    optional={
        "UID": _safe.map(lambda v: f":{v}"),
        "DTSTART": _when,
        "DTEND": _when,
        "DURATION": st.sampled_from([":PT1H", ":P1D", ":-PT30M", ":bogus"]),
        "SUMMARY": _safe.map(lambda v: f":{v}"),
        "DESCRIPTION": _safe.map(lambda v: f":{v}"),
        "LOCATION": _safe.map(lambda v: f":{v}"),
        "GEO": st.sampled_from([":59.9;10.7", ":91;0", ":x;y", ":nan;1"]),
        "STATUS": st.sampled_from([":CONFIRMED", ":TENTATIVE", ":CANCELLED", ":other", ":"]),
        "RRULE": st.sampled_from([":FREQ=WEEKLY;BYDAY=MO", ":FREQ=DAILY;COUNT=3", ":", ":x"]),
        "RECURRENCE-ID": _when,
        "LAST-MODIFIED": _when,
    },
)
_calendar = st.tuples(
    st.sampled_from(["", "X-WR-CALNAME:Personal\r\n", "X-WR-CALNAME:\r\n", "﻿"]),
    st.lists(_event, max_size=4),
    st.sampled_from(
        ["", "BEGIN:VTODO\r\nUID:T\r\nEND:VTODO\r\n", "BEGIN:VTIMEZONE\r\nTZID:X\r\nEND:VTIMEZONE\r\n"]
    ),
).map(
    lambda t: (
        ("﻿" if t[0] == "﻿" else "")
        + "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
        + ("" if t[0] == "﻿" else t[0])
        + t[2]
        + "".join(_render(e) for e in t[1])
        + "END:VCALENDAR\r\n"
    ).encode("utf-8")
)
# a file in the folder: an iCalendar text, or anything else a Takeout folder may hold
_content = st.one_of(_calendar, st.binary(max_size=80), st.just(b"begin:vcalendar\r\nEND:VCALENDAR\r\n"))
_name = st.tuples(st.sampled_from(["", "."]), st.text("abcdefgh", min_size=1, max_size=5)).map(
    lambda t: f"{t[0]}{t[1]}.ics"
)
_files = st.dictionaries(_name, _content, max_size=4)


def _render(event: dict) -> str:
    return (
        "\r\n".join(["BEGIN:VEVENT", *(f"{name}{value}" for name, value in event.items()), "END:VEVENT"])
        + "\r\n"
    )


def _folder(tmp_path_factory, name: str, files: dict[str, bytes]) -> Path:
    folder = tmp_path_factory.mktemp("takeout") / "Takeout" / name
    folder.mkdir(parents=True)
    for file, content in files.items():
        (folder / file).write_bytes(content)
    return folder


def _rfc_rules(line: dict) -> None:
    assert set(line) == ENVELOPE
    assert (line["source"], line["kind"], line["tier"]) == (ics.NAME, "event", 1)
    assert line["at"].endswith("Z") and len(line["at"]) == 20
    assert line["end"] is None or (line["end"].endswith("Z") and len(line["end"]) == 20)
    p = line["payload"]
    assert p["schema"] == "event/v1"
    assert isinstance(p["raw_id"], str) and p["raw_id"]
    json.dumps(line, allow_nan=False)


@settings(max_examples=40, deadline=None)
@given(_files, st.sampled_from([None, "Europe/Oslo", "UTC"]))
def test_any_calendar_folder_yields_only_the_ics_adapters_valid_lines(tmp_path_factory, files, timezone):
    folder = _folder(tmp_path_factory, "Calendar", files)
    calendars = {
        name for name, content in files.items() if not name.startswith(".") and ics.sniff_bytes(content)
    }
    assert takeout_calendar.sniff(folder) is bool(calendars)
    for name, content in files.items():  # a file is sniffed by its content, hidden or not
        assert takeout_calendar.sniff(folder / name) is ics.sniff_bytes(content)
    counts: dict[str, int] = {}
    lines = list(takeout_calendar.run(folder, counts=counts, timezone=timezone))
    for line in lines:
        _rfc_rules(line)
    through_ics: dict[str, int] = {}
    assert lines == list(ics.run(folder, counts=through_ics, timezone=timezone))
    assert counts == through_ics
    lb = Logbook.init(tmp_path_factory.mktemp("lb"), timezone or "UTC")
    assert lb.append_many(lines) == len({line["payload"]["raw_id"] for line in lines})
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == len({line["payload"]["raw_id"] for line in lines})
    validator = Draft202012Validator(SCHEMA)
    for stored in lb.lines():
        validator.validate(stored)


@settings(max_examples=20, deadline=None)
@given(_files)
def test_a_folder_by_another_name_is_not_takeouts_calendar(tmp_path_factory, files):
    folder = _folder(tmp_path_factory, "Keep", files)
    assert takeout_calendar.sniff(folder) is False
    assert all(takeout_calendar.sniff(folder / name) is False for name in files)


def test_sniff_is_false_for_a_missing_path_and_an_empty_folder(tmp_path):
    assert takeout_calendar.sniff(tmp_path / "Calendar") is False
    (tmp_path / "Calendar").mkdir()
    assert takeout_calendar.sniff(tmp_path / "Calendar") is False
