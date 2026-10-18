"""The daily loop's two messages (`notify.daily`): after the 06:00 close, "Your Day page for <date> is
ready" with the count of the day's lines and, when `LOGBOOK_NOTIFY_LINK_HOST` is set, the link; at
`LOGBOOK_NOTIFY_EVENING_HOUR`, the day's question. Nothing of the day beyond the date, the count and
the question; one request each, never more, a day (`state/notify-daily.json`); off unless the
notifier's settings are there; the token never printed. The opener is a fake that keeps what it is
handed; nothing opens a connection. Ines and Kari Nordmann of Oslo are synthetic."""

from __future__ import annotations

import contextlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.contrib import digest, doctor, last_run, notify, schedule
from logbook.core.store import Logbook

TOKEN = "000000000:not-a-real-token"
CHAT = "123456"
PERSONA = "Nordmann"
CLOSE = datetime(2026, 10, 17, 4, 0, 5, tzinfo=UTC)  # 06:00 in Oslo, Saturday: closes Friday the 16th
EVENING = datetime(2026, 10, 17, 18, 30, tzinfo=UTC)  # 20:30 in Oslo
AFTERNOON = datetime(2026, 10, 17, 17, 30, tzinfo=UTC)  # 19:30 in Oslo
GLAD = "What were you glad of today?"
ENV = {notify.TOKEN_ENV: TOKEN, notify.CHAT_ENV: CHAT}


class Opener:
    """A stand-in for `urllib.request.urlopen`: every request kept, the Bot API's yes answered."""

    def __init__(self, answer: dict[str, Any] | None = None, fail: bool = False) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.answer = answer or {"ok": True, "result": {"message_id": 1}}
        self.fail = fail

    def __call__(self, request: Any, timeout: float) -> Any:
        if self.fail:
            raise OSError("connection refused")
        self.requests.append((request.full_url, json.loads(request.data)))
        return io.BytesIO(json.dumps(self.answer).encode("utf-8"))

    @property
    def texts(self) -> list[str]:
        return [body["text"] for _url, body in self.requests]


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """A record of the persona with two lines on Friday 16 October and one retracted, and a question
    bank of one fixed question, so the evening draws it."""
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    kept = lb.append(
        "2026-10-16T10:00:00Z",
        "manual",
        "note",
        2,
        {"schema": "note/v1", "text": "coffee with Kari Nordmann"},
    )
    lb.append(
        "2026-10-16T15:00:00Z",
        "manual",
        "note",
        2,
        {"schema": "note/v1", "text": "Kari Nordmann left for Bergen"},
    )
    gone = lb.append("2026-10-16T16:00:00Z", "manual", "note", 2, {"schema": "note/v1", "text": "a mistake"})
    lb.append(
        "2026-10-16T16:05:00Z",
        "manual",
        "retraction",
        1,
        {"schema": "retraction/v1", "supersedes": gone["id"], "reason": "a mistake"},
    )
    assert kept
    (lb.root / "policy").mkdir(exist_ok=True)
    bank = {
        "questions": [
            {"id": "glad", "text": GLAD, "kind": "gratitude", "when": [], "weight": 1, "source": ""}
        ]
    }
    (lb.root / "policy" / "questions.json").write_text(json.dumps(bank), encoding="utf-8")
    return lb


def run(
    lb: Logbook, env: dict[str, str], now: datetime, close: bool, opener: Opener
) -> tuple[list[str], list[str], list[str]]:
    said: list[str] = []
    warned: list[str] = []
    done = notify.daily(lb, env, now, close=close, say=said.append, warn=warned.append, opener=opener)
    return done, said, warned


def test_after_the_close_one_message_the_date_the_count_and_the_link(lb: Logbook) -> None:
    opener = Opener()
    env = {**ENV, notify.LINK_ENV: "logbook.example.org"}
    done, said, warned = run(lb, env, CLOSE, True, opener)
    assert done == ["ready"] and warned == []
    (text,) = opener.texts
    assert (
        text == "Your Day page for 2026-10-16 is ready · 2 lines\nhttps://logbook.example.org/day/2026-10-16"
    )
    assert PERSONA not in text and "coffee" not in text and "Bergen" not in text, (
        "nothing of the day's content"
    )
    (url, body) = opener.requests[0]
    assert url == f"{notify.API}/bot{TOKEN}/sendMessage" and body["chat_id"] == CHAT
    assert all(TOKEN not in line for line in [*said, *warned]), "the token is never printed"
    assert said == ["notify: telegram: sent (the Day page for 2026-10-16)"]


def test_one_message_a_day_never_more(lb: Logbook) -> None:
    opener = Opener()
    run(lb, ENV, CLOSE, True, opener)
    run(lb, ENV, CLOSE, True, opener)  # the close run again, by hand
    run(lb, ENV, EVENING, False, opener)  # a later run of the same day: no close, no evening hour set
    assert len(opener.requests) == 1
    assert json.loads((lb.root / "state" / "notify-daily.json").read_text(encoding="utf-8")) == {
        "ready": "2026-10-16"
    }


def test_no_link_without_a_host_and_a_bad_host_is_said_without_its_value(lb: Logbook) -> None:
    opener = Opener()
    run(lb, ENV, CLOSE, True, opener)
    assert opener.texts == ["Your Day page for 2026-10-16 is ready · 2 lines"]
    (lb.root / "state" / "notify-daily.json").unlink()
    _done, _said, warned = run(lb, {**ENV, notify.LINK_ENV: "not a host/<script>"}, CLOSE, True, opener)
    assert warned == [
        f"notify: {notify.LINK_ENV} is not a host (logbook.example.org, or https://host:port); no link"
    ]
    assert opener.texts[-1] == "Your Day page for 2026-10-16 is ready · 2 lines"


def test_the_evening_question_at_its_hour_once(lb: Logbook) -> None:
    opener = Opener()
    env = {**ENV, notify.EVENING_ENV: "20"}
    assert run(lb, env, AFTERNOON, False, opener)[0] == [], "19:30 is before the hour"
    done, said, _warned = run(lb, env, EVENING, False, opener)
    assert done == ["question"] and opener.texts == [f"Your question for 2026-10-17: {GLAD}"]
    assert said == ["notify: telegram: sent (the evening question for 2026-10-17)"]
    assert run(lb, env, EVENING, False, opener)[0] == [] and len(opener.requests) == 1


def test_a_question_filled_from_the_day_is_not_sent(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    """`Was {proposed} with you?` would carry a name of the record: the message says where it waits."""
    bank = {
        "questions": [
            {
                "id": "with",
                "text": "Was {proposed} with you?",
                "kind": "people",
                "when": [],
                "weight": 1,
                "source": "",
            }
        ]
    }
    (lb.root / "policy" / "questions.json").write_text(json.dumps(bank), encoding="utf-8")
    monkeypatch.setattr(
        digest, "read", lambda _lb, day: {"question": {"id": "with", "text": "Was Kari Nordmann with you?"}}
    )
    opener = Opener()
    run(lb, {**ENV, notify.EVENING_ENV: "20"}, EVENING, False, opener)
    assert opener.texts == ["Your question for 2026-10-17 waits in `logbook digest`"]


def test_the_close_and_the_evening_hour_are_one_message_each(lb: Logbook) -> None:
    opener = Opener()
    late_close = datetime(2026, 10, 17, 19, 0, tzinfo=UTC)  # a close run by hand at 21:00
    done, _said, _warned = run(lb, {**ENV, notify.EVENING_ENV: "20"}, late_close, True, opener)
    assert done == ["ready", "question"] and len(opener.requests) == 2


def test_nothing_is_sent_when_the_notifier_is_not_set(lb: Logbook) -> None:
    opener = Opener()
    for env in (
        {notify.LINK_ENV: "logbook.example.org", notify.EVENING_ENV: "20"},
        {notify.TOKEN_ENV: TOKEN, notify.EVENING_ENV: "20"},
        {notify.CHAT_ENV: CHAT},
        {},
    ):
        assert run(lb, env, CLOSE, True, opener) == ([], [], [])
        assert run(lb, env, EVENING, False, opener)[0] == []
    assert opener.requests == [] and not (lb.root / "state" / "notify-daily.json").exists()


def test_a_failed_request_is_one_warning_without_the_token_and_the_day_is_given_back(lb: Logbook) -> None:
    failing = Opener(fail=True)
    done, _said, warned = run(lb, ENV, CLOSE, True, failing)
    assert done == [] and warned == ["notify: telegram: connection refused"]
    refused = Opener(answer={"ok": False, "description": "chat not found"})
    _done, _said, warned = run(lb, ENV, CLOSE, True, refused)
    assert warned == ["notify: telegram: the API refused the message: chat not found"]
    assert all(TOKEN not in w for w in warned)
    opener = Opener()
    assert run(lb, ENV, CLOSE, True, opener)[0] == ["ready"] and len(opener.requests) == 1


def test_a_bad_evening_hour_is_said_and_asks_nothing(lb: Logbook) -> None:
    opener = Opener()
    _done, _said, warned = run(lb, {**ENV, notify.EVENING_ENV: "25"}, EVENING, False, opener)
    assert warned == [f"notify: {notify.EVENING_ENV} is not an hour from 0 to 23; no evening question"]
    assert opener.requests == []


def test_the_scheduled_close_sends_the_day_page_through_the_notifier(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`sync --scheduled --close`: the daily message goes after the run, one request, and a run
    that is not the close sends no Day page."""
    sent: list[str] = []
    monkeypatch.setattr(notify, "send", lambda config, text, opener=None: sent.append(text))
    monkeypatch.setattr(last_run, "now", lambda: CLOSE)
    monkeypatch.setattr(doctor, "EXTRAS", ())
    monkeypatch.setattr(doctor, "DISK_WARN_BYTES", 0)
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv(notify.EVENING_ENV, raising=False)
    monkeypatch.delenv(notify.LINK_ENV, raising=False)
    monkeypatch.delenv(notify.API_ENV, raising=False)
    for args in (
        ["sync", "--scheduled", "--close"],
        ["sync", "--scheduled"],
        ["sync", "--scheduled", "--close"],
    ):
        with contextlib.suppress(SystemExit):
            cli.main(args)
    out = capsys.readouterr()
    daily = [text for text in sent if text.startswith("Your Day page")]
    assert daily == ["Your Day page for 2026-10-16 is ready · 2 lines"]
    assert "notify: telegram: sent (the Day page for 2026-10-16)" in out.out
    assert TOKEN not in out.out and TOKEN not in out.err


def test_the_schedule_runs_at_the_evening_hour_when_it_is_none_of_the_four(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".config" / "logbook").mkdir(parents=True)
    (home / ".config" / "logbook" / "sync.env").write_text(
        f"LOGBOOK_IMMICH_KEY=secret\n{notify.EVENING_ENV}=21\n", encoding="utf-8"
    )
    hour = schedule.evening_hour_of({}, home)
    assert hour == 21
    assert schedule.evening_hour_of({notify.EVENING_ENV: "18"}, home) == 18, "the shell's wins"
    plan = schedule.plan("linux", home, "/opt/py", evening_hour=hour)
    timers = [text for path, text in plan.files.items() if path.name == f"{schedule.UNIT}.timer"]
    assert timers and "OnCalendar=*-*-* 00,12,18,21:00:00" in timers[0]
    plan = schedule.plan("linux", home, "/opt/py", evening_hour=18)
    timers = [text for path, text in plan.files.items() if path.name == f"{schedule.UNIT}.timer"]
    assert "OnCalendar=*-*-* 00,12,18:00:00" in timers[0], "18 is a run already"
    said: list[str] = []
    assert schedule.evening_hour_of({notify.EVENING_ENV: "nine"}, home, said.append) is None
    assert said == [f"schedule: {notify.EVENING_ENV} is not an hour from 0 to 23; no evening question"]
    darwin = schedule.plan("darwin", home, "/opt/py", evening_hour=21)
    runs = next(text for path, text in darwin.files.items() if path.name == f"{schedule.LABEL}.plist")
    assert runs.count("<key>Hour</key>") == 4 and "<integer>21</integer>" in runs


def test_a_message_that_cannot_be_composed_is_one_warning_and_the_run_goes_on(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_lb: Logbook, _day: str) -> dict[str, Any]:
        raise KeyError("question")

    monkeypatch.setattr(digest, "read", broken)
    opener = Opener()
    done, _said, warned = run(lb, {**ENV, notify.EVENING_ENV: "20"}, EVENING, False, opener)
    assert done == [] and opener.requests == []
    assert warned == ["notify: telegram: the question message for 2026-10-17 was not sent: 'question'"]
    assert not (lb.root / "state" / "notify-daily.json").exists(), "nothing claimed: a later run may send it"


def test_a_state_file_that_cannot_be_written_sends_nothing_and_says_so(lb: Logbook) -> None:
    (lb.root / "state" / "notify-daily.json").mkdir(parents=True)  # a directory where the file goes
    opener = Opener()
    done, _said, warned = run(lb, ENV, CLOSE, True, opener)
    assert done == [] and opener.requests == []
    assert len(warned) == 1 and warned[0].startswith(
        "notify: telegram: state/notify-daily.json cannot be written"
    )
    assert all(TOKEN not in w for w in warned)


def test_a_timeout_keeps_the_day_claimed_so_a_delivered_message_is_never_sent_twice(lb: Logbook) -> None:
    class Slow(Opener):
        def __call__(self, request: Any, timeout: float) -> Any:
            self.requests.append((request.full_url, json.loads(request.data)))
            raise TimeoutError("timed out")

    slow = Slow()
    _done, _said, warned = run(lb, ENV, CLOSE, True, slow)
    assert warned == ["notify: telegram: timed out"] and len(slow.requests) == 1
    opener = Opener()
    assert run(lb, ENV, CLOSE, True, opener)[0] == [] and opener.requests == [], "the claim stands"
