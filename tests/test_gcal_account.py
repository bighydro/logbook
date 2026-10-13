"""`logbook sync gcal` on the service account: the Calendar API v3, read-only (`calendar.readonly`), as the
owner, when `LOGBOOK_DRIVE_SA_KEY` and `LOGBOOK_DRIVE_USER` are set; the iCal feeds as before when they
are not. Every event goes through the ics reader the feeds go through, so a calendar pulled either way is
the same line, byte for byte, and a watermark the feeds left carries over.

The calendars are the synthetic ones of `tests/test_ics.py` and `tests/test_gcal.py` as the Calendar API
would return them, served by the in-process fake of `tests/google_fake.py`. Nobody here exists."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

import pytest
from google_fake import CALENDAR_SCOPE, DRIVE_SCOPE, USER, Fake, private_key, write_key
from test_gcal import LUNCH, STANDUP, WORK
from test_ics import AGM, BRIEFING, CALENDAR, DENTIST, SURVEY, TRAINING

from logbook import cli
from logbook.contrib import doctor
from logbook.contrib.adapters import gcal, ics, service_account
from logbook.core.store import Logbook

KEY_ENV, USER_ENV = service_account.KEY_ENV, service_account.USER_ENV
URLS_ENV = "LOGBOOK_GCAL_URLS"
SAILING_ID = "c_sailing1@group.calendar.google.com"
WORK_ID = "c_3f1a@group.calendar.google.com"
HOLIDAYS_ID = "c_holidays1@group.calendar.google.com"  # subscribed to, not hers
EVENTS = "www.googleapis.com/calendar/v3/calendars/{id}/events"
OSLO = "Europe/Oslo"


def _at(local: str, zone: str | None = OSLO) -> dict[str, str]:
    """A start or end as the API spells it: the local time with Oslo's winter offset, and the zone."""
    when = {"dateTime": f"{local}+01:00"}
    if zone is not None:
        when["timeZone"] = zone
    return when


# The Sailing club feed of test_ics, event by event, as the Calendar API returns it. What the API has no
# field for is not here: GEO, an attendee's DELEGATED, a floating time (the API gives an offset), a VTODO
# and a VEVENT without a UID. A field the feed leaves out (a status, an end) is left out here too.
SAILING_EVENTS: list[dict[str, Any]] = [
    {
        "id": "survey0001",
        "iCalUID": SURVEY,
        "status": "confirmed",
        "created": "2026-02-01T10:00:00.000Z",
        "updated": "2026-02-27T16:05:00.000Z",
        "summary": "Boat survey — Tromsø marina",
        "description": "bring the papers, the keys\nand a flask of coffee for the surveyor;"
        " who is always cold",
        "location": "Tromsø småbåthavn",
        "organizer": {"email": "kari@example.org", "displayName": "Nordmann, Kari"},
        "start": _at("2026-03-03T09:30:00"),
        "end": _at("2026-03-03T10:15:00"),
        "attendees": [
            {"email": "ola@example.org", "displayName": "Ola Nordmann", "responseStatus": "accepted"},
            {"email": "ines@example.org", "responseStatus": "declined", "self": True},
            {"email": "kalle@example.org", "displayName": "Kalle", "responseStatus": "needsAction"},
        ],
        "sequence": 2,
    },
    {
        "id": "agm0001",
        "iCalUID": AGM,
        "updated": "2026-02-20T09:00:00.000Z",
        "summary": "Sailing club AGM",
        "start": {"date": "2026-03-07"},
        "end": {"date": "2026-03-08"},
        "transparency": "transparent",
    },
    {
        "id": "dentist0001",
        "iCalUID": DENTIST,
        "updated": "2026-03-01T11:00:00.000Z",
        "summary": "Dentist",
        "start": _at("2026-03-10T10:00:00", zone=None),
        "end": _at("2026-03-10T10:30:00", zone=None),
    },
    {
        "id": "training0001",
        "iCalUID": TRAINING,
        "updated": "2026-02-21T12:00:00.000Z",
        "summary": "Crew training",
        "start": _at("2026-03-03T18:00:00"),
        "end": _at("2026-03-03T19:30:00"),
        "recurrence": [
            "RRULE:FREQ=WEEKLY;INTERVAL=2;COUNT=10;BYDAY=TU,TH",
            "EXDATE;TZID=Europe/Oslo:20260331T180000",
        ],
    },
    {
        "id": "training0001_20260317T170000Z",
        "iCalUID": TRAINING,
        "recurringEventId": "training0001",
        "originalStartTime": _at("2026-03-17T18:00:00"),
        "updated": "2026-03-10T08:00:00.000Z",
        "summary": "Crew training (moved)",
        "start": _at("2026-03-17T19:00:00"),
        "end": _at("2026-03-17T20:30:00"),
    },
    {
        "id": "briefing0001",
        "iCalUID": BRIEFING,
        "status": "cancelled",
        "updated": "2026-03-04T20:00:00.000Z",
        "summary": "Regatta briefing",
        "start": _at("2026-03-05T17:00:00"),
    },
]
WORK_EVENTS: list[dict[str, Any]] = [
    {
        "id": "standup0001",
        "iCalUID": STANDUP,
        "updated": "2026-03-06T10:15:00.000Z",
        "summary": "Standup",
        "start": _at("2026-03-09T09:00:00"),
        "end": _at("2026-03-09T09:30:00"),
        "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO"],
    },
    {
        "id": "lunch0001",
        "iCalUID": LUNCH,
        "updated": "2026-03-11T14:00:00.000Z",
        "summary": "Lunch with Ola",
        "location": "Kantina",
        "start": _at("2026-03-13T12:00:00"),
        "end": _at("2026-03-13T13:00:00"),
    },
]
CALENDARS: list[dict[str, Any]] = [
    {"id": WORK_ID, "summary": "Work", "accessRole": "owner", "timeZone": OSLO},
    {"id": HOLIDAYS_ID, "summary": "Holidays in Norway", "accessRole": "reader"},
    {"id": SAILING_ID, "summary": "Sailing club", "accessRole": "owner", "timeZone": OSLO},
    {"id": USER, "summary": USER, "accessRole": "owner", "primary": True, "timeZone": OSLO},
]
NEWEST = "2026-03-11T14:00:00Z"  # the lunch, the last change of either calendar


@pytest.fixture(scope="module")
def key() -> Any:
    return private_key()


@pytest.fixture
def fake(tmp_path: Path, key: Any, monkeypatch: pytest.MonkeyPatch, no_network: list[str]) -> Any:
    server = Fake(
        key,
        calendars=copy.deepcopy(CALENDARS),
        events={
            SAILING_ID: copy.deepcopy(SAILING_EVENTS),
            WORK_ID: copy.deepcopy(WORK_EVENTS),
            USER: [],
            HOLIDAYS_ID: [{"id": "h1", "iCalUID": "h1@google.com", "updated": "2026-01-01T00:00:00.000Z"}],
        },
    )
    server.waits = []  # type: ignore[attr-defined]
    monkeypatch.setattr(service_account, "send", server)
    monkeypatch.setattr(service_account, "sleep", server.waits.append)  # type: ignore[attr-defined]
    monkeypatch.setenv(KEY_ENV, str(write_key(tmp_path / "google-sa.json", key)))
    monkeypatch.setenv(USER_ENV, USER)
    monkeypatch.delenv(URLS_ENV, raising=False)
    yield server
    assert no_network == [], "the fake is the only way out"


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", OSLO)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    return lb


def _config() -> gcal.Config:
    config = gcal.configure(os.environ)
    assert config is not None
    return config


def _pull(**kw: Any) -> tuple[list[dict[str, Any]], dict[str, int]]:
    counts: dict[str, int] = {}
    drafts = list(gcal.pull(_config(), counts=counts, timezone=OSLO, **kw))
    return drafts, counts


def _feed_lines() -> dict[str, dict[str, Any]]:
    """What the feeds give for the same two calendars, by raw_id: the existing gcal fixture."""
    lines = [*ics.lines(CALENDAR, "basic.ics", {}, OSLO), *ics.lines(WORK, "basic.ics", {}, OSLO)]
    return {d["payload"]["raw_id"]: d for d in lines}


def _bytes(draft: dict[str, Any]) -> bytes:
    return json.dumps(draft, ensure_ascii=False).encode("utf-8")


def _sync(*args: str) -> int:
    try:
        cli.main(["sync", "gcal", *args])
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    return 0


# -- configure ----------------------------------------------------------------------------------------


def test_configure_takes_the_service_account_when_both_variables_are_set(fake: Fake) -> None:
    config = _config()
    assert config.account is not None and config.calendars == ()
    assert USER not in repr(config) and "google-sa.json" not in repr(config)
    assert gcal.ENV == (URLS_ENV, KEY_ENV, USER_ENV)


def test_the_service_account_wins_over_the_feeds_when_both_are_set(fake: Fake, monkeypatch: Any) -> None:
    monkeypatch.setenv(URLS_ENV, "Sailing=https://calendar.example.org/private-synthetic/basic.ics")
    config = _config()
    assert config.account is not None and config.calendars == ()


def test_without_the_two_variables_the_feeds_are_read_as_before(monkeypatch: Any) -> None:
    monkeypatch.setenv(URLS_ENV, "Sailing=https://calendar.example.org/private-synthetic/basic.ics")
    monkeypatch.setenv(USER_ENV, USER)  # the key alone is missing: not the service account
    config = _config()
    assert config.account is None and [c.name for c in config.calendars] == ["Sailing"]


def test_needs_says_either_way_in(monkeypatch: Any) -> None:
    assert gcal.needs({}) == f"{URLS_ENV}, or {KEY_ENV} and {USER_ENV}"
    assert gcal.needs({KEY_ENV: "~/k.json"}) == f"{USER_ENV} (or {URLS_ENV} for the iCal feeds)"
    assert gcal.configure({KEY_ENV: "~/k.json"}) is None


# -- pull: the same line --------------------------------------------------------------------------------


def test_an_event_from_the_api_is_the_line_its_ical_feed_gives_byte_for_byte(fake: Fake) -> None:
    drafts, _counts = _pull()
    feed = _feed_lines()
    api = {d["payload"]["raw_id"]: d for d in drafts}
    assert set(api) == set(feed), "every event the feed has a UID for, with the same raw_id"
    for raw_id, line in api.items():
        expected = copy.deepcopy(feed[raw_id])
        if raw_id.startswith(SURVEY):  # what the API has no field for: GEO, and a DELEGATED attendee
            del expected["payload"]["extra"]
            del expected["payload"]["attendees"][2]["extra"]
        assert _bytes(line) == _bytes(expected), raw_id


def test_the_survey_differs_only_by_what_the_api_cannot_say(fake: Fake) -> None:
    drafts, _counts = _pull()
    (survey,) = [d for d in drafts if d["payload"]["raw_id"].startswith(SURVEY)]
    feed = next(d for k, d in _feed_lines().items() if k.startswith(SURVEY))
    assert "extra" not in survey["payload"] and feed["payload"]["extra"]["location"]["latitude"] == 69.6489
    assert survey["payload"]["notes"] == feed["payload"]["notes"]
    assert survey["payload"]["organizer"] == {"kind": "email", "value": "kari@example.org"}


def test_pull_reads_the_calendars_the_user_owns_primary_first_and_no_other(fake: Fake) -> None:
    drafts, _counts = _pull()
    assert [d["payload"]["calendar"]["name"] for d in drafts] == ["Sailing club"] * 6 + ["Work"] * 2
    asked = [p for _m, p, _q in fake.requests if p.startswith("www.googleapis.com/calendar")]
    assert asked[0] == "www.googleapis.com/calendar/v3/users/me/calendarList"
    assert list(dict.fromkeys(p for p in asked if p.endswith("/events"))) == [
        EVENTS.format(id=USER),
        EVENTS.format(id=SAILING_ID),
        EVENTS.format(id=WORK_ID),
    ], "the holidays calendar is someone else's: never read"
    assert fake.calls("www.googleapis.com/calendar/v3/users/me/calendarList")[0]["minAccessRole"] == "owner"


def test_every_event_is_asked_for_as_stored_deleted_ones_included(fake: Fake) -> None:
    _pull(since="2026-03-01T00:00:00Z")
    (asked, *_more) = fake.calls(EVENTS.format(id=SAILING_ID))
    assert asked["singleEvents"] == "false" and asked["showDeleted"] == "true"
    assert asked["updatedMin"] == "2026-03-01T00:00:00Z"


def test_the_client_only_reads_with_the_calendar_scope(fake: Fake) -> None:
    _pull()
    assert fake.methods() == {("POST", "oauth2.googleapis.com"), ("GET", "www.googleapis.com")}
    assert {a["scope"] for a in fake.assertions} == {CALENDAR_SCOPE}


def test_since_keeps_the_events_changed_from_then_on(fake: Fake) -> None:
    drafts, _counts = _pull(since="2026-03-01T11:00:00Z")
    assert [d["payload"]["title"] for d in drafts] == [
        "Dentist",
        "Crew training (moved)",
        "Regatta briefing",
        "Standup",
        "Lunch with Ola",
    ]


def test_an_updated_min_too_long_ago_reads_the_calendar_whole_and_keeps_the_changed(fake: Fake) -> None:
    fake.updated_min_floor = "2026-03-05T00:00:00Z"
    drafts, _counts = _pull(since="2026-03-01T11:00:00Z")
    assert [d["payload"]["title"] for d in drafts] == [
        "Dentist",
        "Crew training (moved)",
        "Regatta briefing",
        "Standup",
        "Lunch with Ola",
    ]
    sailing = fake.calls(EVENTS.format(id=SAILING_ID))
    assert "updatedMin" in sailing[0] and all("updatedMin" not in c for c in sailing[1:])
    assert len(sailing) == 3, "refused once, then the whole calendar in two pages"


def test_a_deleted_event_with_nothing_left_but_its_id_is_counted_not_written(fake: Fake) -> None:
    fake.events[WORK_ID].append(
        {"id": "gone0001", "status": "cancelled", "updated": "2026-03-12T08:00:00.000Z"}
    )
    drafts, counts = _pull()
    assert len(drafts) == 8 and counts == {"skipped_deleted": 1}


def test_pull_pages_through_calendars_and_events(fake: Fake) -> None:
    fake.page = 2
    drafts, _counts = _pull()
    assert len(drafts) == 8
    assert [c.get("pageToken") for c in fake.calls(EVENTS.format(id=SAILING_ID))] == [None, "2", "4"]
    assert len(fake.calls("www.googleapis.com/calendar/v3/users/me/calendarList")) == 2


def test_pull_backs_off_on_429_and_5xx_and_carries_on(fake: Fake) -> None:
    fake.fail(429, retry_after="3")
    fake.fail(503)
    drafts, _counts = _pull()
    assert len(drafts) == 8
    assert fake.waits == [3.0, 2.0]  # type: ignore[attr-defined]


def test_a_calendar_that_fails_is_one_failed_line_and_the_others_are_read(fake: Fake) -> None:
    del fake.events[WORK_ID]
    failed: list[str] = []
    drafts = list(gcal.pull(_config(), failed=failed, timezone=OSLO))
    assert len(drafts) == 6
    assert failed == ["Work: HTTP 404: Not Found"]


def test_watermark_and_group_are_the_feeds_own(fake: Fake) -> None:
    drafts, _counts = _pull()
    assert max(gcal.watermark(d) or "" for d in drafts) == NEWEST
    assert {gcal.group(d) for d in drafts} == {"Sailing club", "Work"}


# -- sync ----------------------------------------------------------------------------------------------


def _state(lb: Logbook) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((lb.root / "state" / "gcal.json").read_text(encoding="utf-8"))
    return data


def test_sync_first_run_writes_every_event_and_the_second_none(lb: Logbook, fake: Fake, capsys: Any) -> None:
    assert _sync() == 0
    out = capsys.readouterr().out.splitlines()
    assert f"gcal: 8 new lines of 8 seen from the beginning; watermark {NEWEST}" in out
    assert "  Sailing club: 6 new of 6 seen" in out and "  Work: 2 new of 2 seen" in out
    assert _state(lb) == {"since": NEWEST}
    assert {line["source"] for line in lb.lines()} == {"ics"}
    assert _sync() == 0
    out = capsys.readouterr().out.splitlines()
    assert "gcal: 0 new lines of 1 seen since 2026-03-10T14:00:00Z (1 already in the record)" in out[-2]
    assert lb.meta["seq"] == 8


def test_a_watermark_the_feeds_left_carries_over_and_nothing_is_written_twice(
    lb: Logbook, fake: Fake, monkeypatch: Any, capsys: Any
) -> None:
    """The migration: the feeds' lines are in the record and their watermark in state/gcal.json; the
    two variables are set; the next run reads the API from that watermark less the lookback."""
    for text in (CALENDAR, WORK):
        lb.append_many(ics.lines(text, "basic.ics", {}, OSLO))
    state = lb.root / "state" / "gcal.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"since": NEWEST}), encoding="utf-8")
    assert _sync() == 0
    out = capsys.readouterr().out
    assert "gcal: 0 new lines of 1 seen since 2026-03-10T14:00:00Z (1 already in the record)" in out
    assert fake.calls(EVENTS.format(id=WORK_ID))[0]["updatedMin"] == "2026-03-10T14:00:00Z"
    assert lb.meta["seq"] == 8 and _state(lb) == {"since": NEWEST}


def test_sync_since_and_dry_run(lb: Logbook, fake: Fake, capsys: Any) -> None:
    assert _sync("--dry-run", "--since", "2026-03-11T00:00:00Z") == 0
    out = capsys.readouterr().out
    assert "gcal: 1 lines since 2026-03-11T00:00:00Z (dry run, nothing written)" in out
    assert lb.meta["seq"] == 0 and not (lb.root / "state").exists()


def test_sync_a_scope_the_delegation_lacks_is_one_line_and_exit_1(
    lb: Logbook, fake: Fake, capsys: Any
) -> None:
    fake.delegated = {DRIVE_SCOPE}
    assert _sync() == 1
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and CALENDAR_SCOPE in err and "domain-wide delegation" in err
    assert lb.meta["seq"] == 0


def test_sync_without_either_way_in_says_both(lb: Logbook, monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.delenv(KEY_ENV, raising=False)
    monkeypatch.delenv(USER_ENV, raising=False)
    assert _sync() == 2
    assert capsys.readouterr().err == f"sync: gcal: set {URLS_ENV}, or {KEY_ENV} and {USER_ENV}\n"


# -- doctor --------------------------------------------------------------------------------------------


def test_doctor_says_gcal_runs_on_the_service_account_and_asks_nothing(lb: Logbook, fake: Fake) -> None:
    checks = {c.name: c for c in doctor.run(lb, dict(os.environ), installed=lambda _m: True)}
    check = checks["sync:gcal"]
    assert check.status == "pass"
    assert check.detail.startswith(f"configured ({KEY_ENV}, {USER_ENV}); ")
    assert "the calendars the user owns, on the service account" in check.detail
    assert fake.requests == []


def test_doctor_says_how_many_feeds_without_the_service_account(lb: Logbook, monkeypatch: Any) -> None:
    env = {URLS_ENV: "a=https://calendar.example.org/a/basic.ics,https://calendar.example.org/b/basic.ics"}
    checks = {c.name: c for c in doctor.run(lb, env, installed=lambda _m: True)}
    assert checks["sync:gcal"].detail == f"configured ({URLS_ENV}); 2 iCal feeds"
