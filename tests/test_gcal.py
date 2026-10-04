"""`logbook sync gcal`: Google Calendar's private iCal feeds, live, through the ics reader.

Every feed here is synthetic (the Nordmanns of Oslo do not exist), served by a stub HTTP server on the
loopback interface from memory; no test reaches the network. The secret part of every URL is a made-up
token, and the tests assert it never reaches the console.
"""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from test_ics import AGM, BRIEFING, CALENDAR, DENTIST, SURVEY, TRAINING

from logbook import cli
from logbook.contrib import adapters
from logbook.contrib.adapters import gcal, ics
from logbook.core.store import Logbook

URLS_ENV = "LOGBOOK_GCAL_URLS"
LOOKBACK_ENV = "LOGBOOK_GCAL_LOOKBACK_H"
SECRET_A = "private-synthetic-token-aaaa"
SECRET_B = "private-synthetic-token-bbbb"
SAILING_PATH = f"/calendar/ical/kari.nordmann%40example.org/{SECRET_A}/basic.ics"
WORK_PATH = f"/calendar/ical/c_3f1a%40group.calendar.google.com/{SECRET_B}/basic.ics"
STANDUP = "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d@google.com"
LUNCH = "9f8e7d6c5b4a39281706f5e4d3c2b1a0@google.com"
SAILING_NEWEST = "2026-03-10T08:00:00Z"  # the moved crew training, the sailing feed's last change
WORK_NEWEST = "2026-03-11T14:00:00Z"

# A second synthetic feed as Google writes one: a weekly master and a plain event.
WORK = "\r\n".join(
    [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Synthetic//Logbook test//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Work",
        "X-WR-TIMEZONE:Europe/Oslo",
        "BEGIN:VEVENT",
        f"UID:{STANDUP}",
        "DTSTAMP:20260306T101500Z",
        "LAST-MODIFIED:20260306T101500Z",
        "DTSTART;TZID=Europe/Oslo:20260309T090000",
        "DTEND;TZID=Europe/Oslo:20260309T093000",
        "RRULE:FREQ=WEEKLY;BYDAY=MO",
        "SUMMARY:Standup",
        "END:VEVENT",
        "BEGIN:VEVENT",
        f"UID:{LUNCH}",
        "DTSTAMP:20260311T140000Z",
        "LAST-MODIFIED:20260311T140000Z",
        "DTSTART;TZID=Europe/Oslo:20260313T120000",
        "DTEND;TZID=Europe/Oslo:20260313T130000",
        "SUMMARY:Lunch with Ola",
        "LOCATION:Kantina",
        "END:VEVENT",
        "END:VCALENDAR",
        "",
    ]
)
NO_NAME = "\r\n".join(
    [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "BEGIN:VEVENT",
        "UID:U-1",
        "DTSTAMP:20260301T110000Z",
        "DTSTART:20260310T100000Z",
        "SUMMARY:one",
        "END:VEVENT",
        "END:VCALENDAR",
        "",
    ]
)


# -- the stub server ------------------------------------------------------------------------


class _Feeds(ThreadingHTTPServer):
    routes: dict[str, tuple[int, bytes]]
    requests: list[str]


class _Handler(BaseHTTPRequestHandler):
    server: _Feeds

    def do_GET(self) -> None:
        self.server.requests.append(self.path)
        status, body = self.server.routes.get(self.path, (404, b"Not Found"))
        self.send_response(status)
        self.send_header("Content-Type", "text/calendar; charset=UTF-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return None  # never the request line on stderr: the tests read it


@pytest.fixture
def feeds() -> Any:
    server = _Feeds(("127.0.0.1", 0), _Handler)
    server.routes = {SAILING_PATH: (200, CALENDAR.encode("utf-8")), WORK_PATH: (200, WORK.encode("utf-8"))}
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _url(server: _Feeds, path: str) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}{path}"


def _config(server: _Feeds, *paths: str, names: dict[str, str] | None = None, **kw: Any) -> gcal.Config:
    env = {URLS_ENV: ",".join(f"{(names or {}).get(p, '')}={_url(server, p)}".lstrip("=") for p in paths)}
    env.update({k: str(v) for k, v in kw.items()})
    config = gcal.configure(env)
    assert config is not None
    return config


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _no_secret(*texts: str) -> None:
    for text in texts:
        assert SECRET_A not in text and SECRET_B not in text
        assert "/calendar/ical/" not in text


# -- registry and configure ---------------------------------------------------------------------


def test_registry_has_gcal_as_a_live_adapter_writing_ics_lines():
    assert adapters.live("gcal") is gcal
    assert gcal.NAME == "gcal" and gcal.KIND == ics.KIND == "event"
    assert gcal not in adapters.file_adapters()
    assert adapters.named("gcal") is None


def test_configure_reads_a_comma_separated_list_of_urls():
    assert gcal.ENV == (URLS_ENV,)
    config = gcal.configure(
        {URLS_ENV: " https://calendar.example.org/a/basic.ics , https://calendar.example.org/b/basic.ics,"}
    )
    assert config is not None and config.lookback_h == 24.0
    assert [c.url for c in config.calendars] == [
        "https://calendar.example.org/a/basic.ics",
        "https://calendar.example.org/b/basic.ics",
    ]
    assert [c.name for c in config.calendars] == [None, None]


def test_configure_reads_name_equals_url_pairs():
    config = gcal.configure(
        {URLS_ENV: "Sailing=https://calendar.example.org/a/basic.ics?x=1,https://calendar.example.org/b"}
    )
    assert config is not None
    assert [(c.name, c.url) for c in config.calendars] == [
        ("Sailing", "https://calendar.example.org/a/basic.ics?x=1"),
        (None, "https://calendar.example.org/b"),
    ]


def test_a_calendars_label_is_its_name_else_a_short_hash_of_the_url():
    config = gcal.configure(
        {
            URLS_ENV: f"Sailing=https://calendar.example.org/{SECRET_A}/basic.ics,https://calendar.example.org/{SECRET_B}/basic.ics"
        }
    )
    assert config is not None
    sailing, other = config.calendars
    assert sailing.label == "Sailing"
    assert len(other.label) == 8 and int(other.label, 16) >= 0 and SECRET_B not in other.label


def test_the_urls_never_appear_in_the_configs_repr():
    config = gcal.configure({URLS_ENV: f"Sailing=https://calendar.example.org/{SECRET_A}/basic.ics"})
    assert config is not None
    _no_secret(repr(config), str(config), repr(config.calendars[0]))


@pytest.mark.parametrize("value", ["", "  ", ",", " , "])
def test_configure_returns_none_without_a_url(value):
    assert gcal.configure({URLS_ENV: value}) is None
    assert gcal.configure({}) is None


@pytest.mark.parametrize("bad", ["basic.ics", "ftp://calendar.example.org/x", "Sailing=nope"])
def test_configure_refuses_a_value_that_is_not_an_http_url_without_echoing_it(bad):
    with pytest.raises(ValueError, match=URLS_ENV) as e:
        gcal.configure({URLS_ENV: bad})
    assert "nope" not in str(e.value) and "ftp://" not in str(e.value)


@pytest.mark.parametrize("bad", ["soon", "-1", "nan", "inf"])
def test_configure_refuses_a_lookback_that_is_not_a_non_negative_number(bad):
    with pytest.raises(ValueError, match=LOOKBACK_ENV):
        gcal.configure({URLS_ENV: "https://calendar.example.org/a", LOOKBACK_ENV: bad})


def test_configure_reads_the_lookback_override():
    config = gcal.configure({URLS_ENV: "https://calendar.example.org/a", LOOKBACK_ENV: "72"})
    assert config is not None and config.lookback_h == 72.0


def test_resume_is_the_mark_less_the_lookback():
    config = gcal.configure({URLS_ENV: "https://calendar.example.org/a"})
    assert config is not None
    assert gcal.resume(config, "2026-03-10T08:00:00Z") == "2026-03-09T08:00:00Z"


def test_watermark_is_the_events_last_modified_time(feeds):
    drafts = {
        d["payload"]["title"]: d for d in gcal.pull(_config(feeds, SAILING_PATH), timezone="Europe/Oslo")
    }
    assert gcal.watermark(drafts["Crew training (moved)"]) == SAILING_NEWEST
    assert gcal.watermark(drafts["Sailing club AGM"]) == "2026-02-20T09:00:00Z"  # DTSTAMP when not modified
    assert gcal.watermark({"payload": {"schema": "event/v1"}}) is None


def test_group_is_the_calendars_name_else_its_id():
    assert gcal.group({"payload": {"calendar": {"id": "Work", "name": "Work"}}}) == "Work"
    assert gcal.group({"payload": {"calendar": {"id": "basic.ics"}}}) == "basic.ics"


# -- pull: the shared mapping ------------------------------------------------------------------


def test_a_calendar_exported_to_a_file_and_the_same_calendar_pulled_by_url_are_the_same_lines(
    feeds, tmp_path
):
    export = tmp_path / "basic.ics"
    export.write_bytes(CALENDAR.encode("utf-8"))
    from_file = list(ics.run(export, timezone="Europe/Oslo"))
    live = list(gcal.pull(_config(feeds, SAILING_PATH), timezone="Europe/Oslo"))
    assert len(live) == len(from_file) == 6
    for exported, pulled in zip(from_file, live, strict=True):
        assert pulled == exported
    assert all(d["source"] == "ics" and d["kind"] == "event" for d in live)


def test_pull_keys_events_by_uid_and_last_modified_and_keeps_masters_and_exceptions(feeds):
    raw_ids = [
        d["payload"]["raw_id"] for d in gcal.pull(_config(feeds, SAILING_PATH), timezone="Europe/Oslo")
    ]
    assert raw_ids == [
        f"{SURVEY}@2026-02-27T16:05:00Z",
        f"{AGM}@2026-02-20T09:00:00Z",
        f"{DENTIST}@2026-03-01T11:00:00Z",
        f"{TRAINING}@2026-02-21T12:00:00Z",
        f"{TRAINING}/2026-03-17T17:00:00Z@{SAILING_NEWEST}",
        f"{BRIEFING}@2026-03-04T20:00:00Z",
    ]


def test_pull_reads_every_calendar_in_the_order_given_and_counts_the_skips(feeds):
    counts: dict[str, int] = {}
    drafts = list(gcal.pull(_config(feeds, WORK_PATH, SAILING_PATH), counts=counts, timezone="Europe/Oslo"))
    assert [d["payload"]["calendar"]["name"] for d in drafts] == ["Work"] * 2 + ["Sailing club"] * 6
    assert drafts[0]["payload"]["recurrence"] == "FREQ=WEEKLY;BYDAY=MO"
    assert counts == {"skipped_todo": 1, "skipped_no_uid": 1}
    assert feeds.requests == [WORK_PATH, SAILING_PATH]


def test_pull_reports_the_running_event_count_after_each_calendar(feeds):
    ticks: list[int] = []
    list(
        gcal.pull(
            _config(feeds, WORK_PATH, SAILING_PATH),
            progress=lambda n, _e: ticks.append(n),
            timezone="Europe/Oslo",
        )
    )
    assert ticks == [2, 8]


def test_pull_since_keeps_only_events_changed_since_then(feeds):
    drafts = list(
        gcal.pull(_config(feeds, SAILING_PATH), since="2026-03-01T11:00:00Z", timezone="Europe/Oslo")
    )
    assert [d["payload"]["title"] for d in drafts] == ["Dentist", "Crew training (moved)", "Regatta briefing"]
    drafts = list(
        gcal.pull(_config(feeds, SAILING_PATH), since="2026-03-01T12:00:00+01:00", timezone="Europe/Oslo")
    )
    assert [d["payload"]["title"] for d in drafts] == ["Dentist", "Crew training (moved)", "Regatta briefing"]


def test_pull_reads_floating_and_all_day_times_in_the_record_zone(feeds):
    drafts = {
        d["payload"]["title"]: d for d in gcal.pull(_config(feeds, SAILING_PATH), timezone="Europe/Oslo")
    }
    assert drafts["Dentist"]["at"] == "2026-03-10T09:00:00Z"
    assert drafts["Sailing club AGM"]["at"] == "2026-03-06T23:00:00Z"
    drafts = {d["payload"]["title"]: d for d in gcal.pull(_config(feeds, SAILING_PATH))}
    assert drafts["Dentist"]["at"] == "2026-03-10T10:00:00Z"


def test_a_given_name_names_a_feed_that_has_none_and_never_overrides_the_feeds_own(feeds):
    feeds.routes["/no-name/basic.ics"] = (200, NO_NAME.encode("utf-8"))
    named = _config(
        feeds,
        "/no-name/basic.ics",
        SAILING_PATH,
        names={"/no-name/basic.ics": "Chores", SAILING_PATH: "Boat"},
    )
    calendars = [d["payload"]["calendar"] for d in gcal.pull(named, timezone="Europe/Oslo")]
    assert calendars[0] == {"id": "Chores", "name": "Chores"}
    assert calendars[1] == {"id": "Sailing club", "name": "Sailing club"}
    unnamed = _config(feeds, "/no-name/basic.ics")
    assert [d["payload"]["calendar"] for d in gcal.pull(unnamed)] == [{"id": "basic.ics"}]  # as a saved copy


# -- pull: failures ---------------------------------------------------------------------------


def test_a_calendar_that_fails_is_reported_by_label_and_the_others_still_come(feeds):
    feeds.routes[WORK_PATH] = (500, b"Internal Server Error")
    failed: list[str] = []
    config = _config(feeds, WORK_PATH, SAILING_PATH, names={WORK_PATH: "Work"})
    drafts = list(gcal.pull(config, failed=failed, timezone="Europe/Oslo"))
    assert len(drafts) == 6
    assert failed == ["Work: HTTP 500 Internal Server Error"]
    del feeds.routes[SAILING_PATH]
    failed = []
    drafts = list(gcal.pull(config, failed=failed, timezone="Europe/Oslo"))
    assert drafts == []
    assert failed == [
        "Work: HTTP 500 Internal Server Error",
        f"{config.calendars[1].label}: HTTP 404 Not Found",
    ]
    _no_secret(*failed)


def test_a_server_that_cannot_be_reached_is_a_failure_line_too(feeds):
    config = gcal.configure({URLS_ENV: f"Down=http://127.0.0.1:{_closed_port()}/{SECRET_A}/basic.ics"})
    assert config is not None
    failed: list[str] = []
    assert list(gcal.pull(config, failed=failed)) == []
    assert len(failed) == 1 and failed[0].startswith("Down: ")
    _no_secret(*failed)


def test_a_body_that_is_not_a_calendar_is_a_failure_line(feeds):
    feeds.routes[WORK_PATH] = (200, b"<html><title>Sign in</title></html>")
    failed: list[str] = []
    assert list(gcal.pull(_config(feeds, WORK_PATH, names={WORK_PATH: "Work"}), failed=failed)) == []
    assert failed == ["Work: not an iCalendar feed"]


def test_without_a_failed_list_a_failure_raises_after_the_other_calendars(feeds):
    feeds.routes[WORK_PATH] = (500, b"Internal Server Error")
    config = _config(feeds, SAILING_PATH, WORK_PATH, names={WORK_PATH: "Work"})
    drafts = []
    with pytest.raises(OSError, match="Work: HTTP 500") as e:
        for d in gcal.pull(config, timezone="Europe/Oslo"):
            drafts.append(d)
    assert len(drafts) == 6
    _no_secret(str(e.value))


# -- sync: the CLI ----------------------------------------------------------------------------


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, feeds: _Feeds) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.setenv(URLS_ENV, f"Sailing={_url(feeds, SAILING_PATH)},{_url(feeds, WORK_PATH)}")
    monkeypatch.delenv(LOOKBACK_ENV, raising=False)
    return lb


def _sync(*args: str) -> None:
    cli.main(["sync", "gcal", *args])


def _state(lb: Logbook) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((lb.root / "state" / "gcal.json").read_text(encoding="utf-8"))
    return data


def test_sync_appends_every_event_reports_per_calendar_and_stores_the_newest_change(lb, capsys):
    _sync()
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert "gcal: 8 new lines of 8 seen from the beginning; watermark 2026-03-11T14:00:00Z" in lines
    assert "  Sailing club: 6 new of 6 seen" in lines
    assert "  Work: 2 new of 2 seen" in lines
    assert "  skipped 1 to-do items, 1 without a uid" in lines
    assert "  8 events in 0s" in captured.err.splitlines()
    _no_secret(captured.out, captured.err)
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 8
    assert _state(lb) == {"since": WORK_NEWEST}
    assert {line["source"] for line in lb.lines()} == {"ics"}
    assert (
        next(line for line in lb.lines() if line["payload"]["title"] == "Sailing club AGM")["at"]
        == "2026-03-06T23:00:00Z"
    )


def test_sync_after_the_files_import_appends_nothing(lb, tmp_path, capsys):
    export = tmp_path / "Sailing club.ics"
    export.write_bytes(CALENDAR.encode("utf-8"))
    cli.main(["add", str(export)])
    assert lb.meta["seq"] == 6
    _sync()
    captured = capsys.readouterr()
    assert "gcal: 2 new lines of 8 seen from the beginning (6 already in the record)" in captured.out
    assert "  Sailing club: 0 new of 6 seen" in captured.out.splitlines()
    assert "  Work: 2 new of 2 seen" in captured.out.splitlines()
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 8
    _no_secret(captured.out, captured.err)


def test_sync_resumes_from_the_watermark_less_the_lookback_and_picks_up_an_edit(lb, feeds, capsys):
    _sync()
    capsys.readouterr()
    _sync()
    out = capsys.readouterr().out.splitlines()
    summary = "gcal: 0 new lines of 1 seen since 2026-03-10T14:00:00Z (1 already in the record)"
    assert f"{summary}; watermark {WORK_NEWEST}" in out
    assert "  Work: 0 new of 1 seen" in out
    assert not any(line.startswith("  Sailing club") for line in out)
    edited = CALENDAR.replace("LAST-MODIFIED:20260227T160500Z", "LAST-MODIFIED:20260312T090000Z").replace(
        "SUMMARY:Boat survey — Tromsø marina", "SUMMARY:Boat survey — Tromsø marina (moved to Friday)"
    )
    feeds.routes[SAILING_PATH] = (200, edited.encode("utf-8"))
    _sync()
    out = capsys.readouterr().out.splitlines()
    summary = "gcal: 1 new lines of 2 seen since 2026-03-10T14:00:00Z (1 already in the record)"
    assert f"{summary}; watermark 2026-03-12T09:00:00Z" in out
    assert "  Sailing club: 1 new of 1 seen" in out
    assert _state(lb) == {"since": "2026-03-12T09:00:00Z"}
    raw_ids = [line["payload"]["raw_id"] for line in lb.lines()]
    assert len(raw_ids) == len(set(raw_ids)) == 9
    assert raw_ids[-1] == f"{SURVEY}@2026-03-12T09:00:00Z"


def test_sync_since_is_used_as_given_without_lookback(lb, capsys):
    _sync("--since", "2026-03-11T00:00:00Z")
    assert (
        "gcal: 1 new lines of 1 seen since 2026-03-11T00:00:00Z; watermark 2026-03-11T14:00:00Z"
        in capsys.readouterr().out
    )


def test_sync_dry_run_counts_per_calendar_and_writes_nothing(lb, capsys):
    _sync("--dry-run")
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert "gcal: 8 lines from the beginning (dry run, nothing written)" in lines
    assert "  Sailing club: 6 seen" in lines and "  Work: 2 seen" in lines
    assert lb.meta["seq"] == 0 and not (lb.root / "state").exists()
    _no_secret(captured.out, captured.err)


def test_sync_one_failing_calendar_is_one_line_the_others_are_written_and_the_exit_is_1(lb, feeds, capsys):
    feeds.routes[SAILING_PATH] = (404, b"Not Found")
    with pytest.raises(SystemExit) as e:
        _sync()
    assert e.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.splitlines()[-1] == "sync: gcal: Sailing: HTTP 404 Not Found"
    assert captured.err.count("sync: gcal:") == 1
    assert "gcal: 2 new lines of 2 seen from the beginning; watermark - (kept: 1 feed failed)" in captured.out
    assert "  Work: 2 new of 2 seen" in captured.out.splitlines()
    _no_secret(captured.out, captured.err)
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 2
    assert not (lb.root / "state").exists()


def test_sync_keeps_the_watermark_when_a_calendar_fails(lb, feeds, capsys):
    _sync()
    feeds.routes[WORK_PATH] = (500, b"Internal Server Error")
    with pytest.raises(SystemExit) as e:
        _sync()
    assert e.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.splitlines()[-1].startswith("sync: gcal: ") and "HTTP 500" in captured.err
    assert "watermark 2026-03-11T14:00:00Z (kept: 1 feed failed)" in captured.out
    assert _state(lb) == {"since": WORK_NEWEST}
    _no_secret(captured.out, captured.err)


def test_sync_refuses_to_run_without_the_urls_on_one_line(lb, monkeypatch, capsys):
    monkeypatch.delenv(URLS_ENV)
    with pytest.raises(SystemExit) as e:
        _sync()
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and URLS_ENV in err


def test_sync_refuses_a_bad_url_on_one_line_without_echoing_it(lb, monkeypatch, capsys):
    monkeypatch.setenv(URLS_ENV, f"Sailing=ftp://calendar.example.org/{SECRET_A}/basic.ics")
    with pytest.raises(SystemExit) as e:
        _sync()
    assert e.value.code == 2
    captured = capsys.readouterr()
    assert captured.err.count("\n") == 1 and URLS_ENV in captured.err
    _no_secret(captured.out, captured.err)
    assert "ftp://" not in captured.err
