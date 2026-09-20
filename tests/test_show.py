"""`logbook show DAY`: lines in time order, runs of location points collapsed to one summary line,
and a closed pipe (`| head`) ending the command quietly."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import cli
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
DAY = "2026-03-01"
DASH = "\u2013"  # the en dash of a time span


def _location(at: str, source: str = "dawarich", **place: str) -> dict[str, Any]:
    payload: dict[str, Any] = {"schema": "location/v1", "lat": 48.15, "lon": 11.58}
    payload["raw_id"] = f"{source}:{at}"
    if place:
        payload["extra"] = {"place": place}
    return {"at": at, "source": source, "kind": "location", "tier": 1, "payload": payload}


def _note(at: str, text: str, kind: str = "note", source: str = "manual") -> dict[str, Any]:
    key = "text" if kind == "note" else "title"
    payload = {"schema": f"{kind}/v1", key: text}
    return {"at": at, "source": source, "kind": kind, "tier": 2, "payload": payload}


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """Oslo (UTC+1 in March). Appended out of time order, so chain order is not day order."""
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(
        [
            _note("2026-03-01T11:00:00Z", "lunch"),  # seq 1, 12:00 local
            _location("2026-03-01T17:18:00Z", district="Schwabing", city="München"),  # seq 2, 18:18
            _location("2026-03-01T20:00:00Z"),  # seq 3, no place
            _location("2026-03-01T22:59:00Z", district="Trudering"),  # seq 4, 23:59
            _note("2026-03-01T08:00:00Z", "breakfast"),  # seq 5, 09:00 — appended last, shown first
            _location("2026-03-01T09:30:00Z", city="München"),  # seq 6, 10:30, a run of one
            # seq 7, the same instant as seq 5
            _note("2026-03-01T08:00:00Z", "Standup", kind="event", source="sim-calendar"),
        ]
    )
    return lb


def _show(capsys: pytest.CaptureFixture[str], day: str = DAY) -> list[str]:
    cli.main(["show", day])
    return capsys.readouterr().out.splitlines()


# -- order ------------------------------------------------------------------------------------


def test_show_orders_a_day_by_time_then_seq(lb: Logbook, capsys):
    out = _show(capsys)
    assert out[0] == DAY
    assert [line.split()[0] for line in out[1:]] == ["09:00", "09:00", "10:30", "12:00", f"18:18{DASH}23:59"]
    assert "breakfast" in out[1] and "Standup" in out[2]  # same instant: seq 5 before seq 7


# -- runs of location points ----------------------------------------------------------------------


def test_show_collapses_consecutive_location_lines_into_one_summary(lb: Logbook, capsys):
    out = _show(capsys)
    assert out[-1] == f"  18:18{DASH}23:59  location   dawarich       3 points · Schwabing → Trudering"
    assert sum("location" in line for line in out) == 2


def test_show_summary_prefers_district_and_falls_back_to_city(lb: Logbook, capsys):
    out = _show(capsys)
    assert out[3] == "  10:30  location   dawarich       1 point · München"


def test_show_run_without_any_place_has_no_place_part(tmp_path: Path, monkeypatch, capsys):
    lb = Logbook.init(tmp_path / "lb", "UTC")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many([_location("2026-03-01T10:00:00Z"), _location("2026-03-01T10:10:00Z")])
    assert _show(capsys)[1] == f"  10:00{DASH}10:10  location   dawarich       2 points"


def test_show_run_with_one_place_names_it_once(tmp_path: Path, monkeypatch, capsys):
    lb = Logbook.init(tmp_path / "lb", "UTC")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(
        [
            _location("2026-03-01T10:00:00Z", district="Schwabing"),
            _location("2026-03-01T10:10:00Z"),
            _location("2026-03-01T10:20:00Z", district="Schwabing"),
        ]
    )
    assert _show(capsys)[1] == f"  10:00{DASH}10:20  location   dawarich       3 points · Schwabing"


def test_show_run_is_broken_by_a_non_location_line(tmp_path: Path, monkeypatch, capsys):
    lb = Logbook.init(tmp_path / "lb", "UTC")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(
        [
            _location("2026-03-01T10:00:00Z"),
            _location("2026-03-01T10:10:00Z"),
            _note("2026-03-01T10:15:00Z", "coffee"),
            _location("2026-03-01T10:20:00Z"),
        ]
    )
    out = _show(capsys)
    assert [line.split()[0] for line in out[1:]] == [f"10:00{DASH}10:10", "10:15", "10:20"]
    assert "2 points" in out[1] and "1 point" in out[3]


def test_show_run_is_broken_by_a_change_of_source(tmp_path: Path, monkeypatch, capsys):
    lb = Logbook.init(tmp_path / "lb", "UTC")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(
        [
            _location("2026-03-01T10:00:00Z"),
            _location("2026-03-01T10:10:00Z", source="owntracks"),
        ]
    )
    out = _show(capsys)
    assert "dawarich" in out[1] and "owntracks" in out[2]


def test_show_retracted_point_shows_its_marker_and_breaks_the_run(tmp_path: Path, monkeypatch, capsys):
    lb = Logbook.init(tmp_path / "lb", "UTC")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(
        [
            _location("2026-03-01T10:00:00Z"),
            _location("2026-03-01T10:10:00Z"),
            _location("2026-03-01T10:20:00Z"),
        ]
    )
    lb.retract(2, "glitch", at="2026-03-02T00:00:00Z")
    out = _show(capsys)
    assert [line.split()[0] for line in out[1:]] == ["10:00", "10:10", "10:20"]
    assert "retracted #2: glitch" in out[2]


def test_show_counts_points_with_thousands_separators(tmp_path: Path, monkeypatch, capsys):
    lb = Logbook.init(tmp_path / "lb", "UTC")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(_location(f"2026-03-01T{i // 60:02d}:{i % 60:02d}:00Z") for i in range(1_237))
    assert "1,237 points" in _show(capsys)[1]


# -- a closed pipe --------------------------------------------------------------------------------


class _ClosedPipe(io.StringIO):
    def write(self, s: str) -> int:
        raise BrokenPipeError


def test_show_into_a_closed_pipe_returns_quietly(lb: Logbook, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdout", _ClosedPipe())
    cli.main(["show", DAY])  # no exception, no exit status other than 0
    assert capsys.readouterr().err == ""


@pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="needs a real bash for a pipeline with pipefail (the Windows stub is not one)",
)
def test_show_piped_into_head_exits_0_with_nothing_on_stderr(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "UTC")
    stamps = (f"2026-03-01T{i // 3600:02d}:{i // 60 % 60:02d}:{i % 60:02d}Z" for i in range(20_000))
    lb.append_many(_note(at, f"note {i}") for i, at in enumerate(stamps))
    env = {**os.environ, "LOGBOOK_HOME": str(lb.root), "PYTHONPATH": str(ROOT)}
    r = subprocess.run(
        ["bash", "-o", "pipefail", "-c", f"{sys.executable} -m logbook.cli show {DAY} | head -1"],
        env=env,
        capture_output=True,
        encoding="utf-8",
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == f"{DAY}\n" and r.stderr == ""


# -- names: refs rendered through the record's own resolution lines (RFC 0006) ----------------

PERSON_A = "019cadd3-6bc0-7dcd-9133-043f5aabf2a9"
PERSON_B = "019cadd3-6bc0-7dcd-9133-043f5aabf2aa"
PERSON_C = "019cadd3-6bc0-7dcd-9133-043f5aabf2ab"
GROUP = "019cadd3-6bc0-7dcd-9133-043f5aabf2ac"


def _resolution(
    kind: str, value: str, label: str, entity: str, entity_type: str = "person", supersedes: str | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "resolution/v1",
        "ref": {"kind": kind, "value": value},
        "entity": {"type": entity_type, "id": entity, "registry": "logbook"},
        "label": label,
        "method": "owner",
    }
    if supersedes is not None:
        payload["supersedes"] = supersedes
    return {
        "at": "2026-02-28T09:00:00Z",
        "source": "manual",
        "kind": "resolution",
        "tier": 2,
        "payload": payload,
    }


def _message(
    at: str, chat: dict[str, Any], sender: str | None, text: str | None, **more: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "message/v1",
        "raw_id": f"wa:{at}",
        "chat": chat,
        "from_me": sender is None,
    }
    if sender is not None:
        payload["sender"] = {"kind": "phone", "value": sender}
    if text is not None:
        payload["text"] = text
    payload.update(more)
    return {"at": at, "source": "whatsapp", "kind": "message", "tier": 2, "payload": payload}


OLA_CHAT = {"id": "4790000001@s.whatsapp.net", "type": "direct", "name": "Ola"}
GROUP_CHAT = {"id": "1234@g.us", "type": "group"}  # the source has no name for it


@pytest.fixture
def people(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """Ola (two refs), Kari (one superseded resolution, one pair where the later wins), a
    retracted resolution of a third number, a named group chat; three messages and one event."""
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append(**_resolution("email", "ola@example.org", "Ola Nordmann", PERSON_A))
    lb.append(**_resolution("phone", "+4790000001", "Ola Nordmann", PERSON_A))
    old = lb.append(**_resolution("phone", "+4790000002", "K. Nordmann", PERSON_B))
    lb.append(**_resolution("phone", "+4790000002", "Kari Nordmann", PERSON_B, supersedes=old["id"]))
    lb.append(**_resolution("email", "kari@example.org", "Kari Older", PERSON_B))
    lb.append(**_resolution("email", "kari@example.org", "Kari Nordmann", PERSON_B))
    wrong = lb.append(**_resolution("phone", "+4790000003", "Mistaken Match", PERSON_C))
    lb.retract(wrong["seq"], "wrong person")
    lb.append(**_resolution("provider_id", "1234@g.us", "Boat club", GROUP, entity_type="company"))
    lb.append_many(
        [
            _message("2026-03-01T10:00:00Z", OLA_CHAT, "+4790000001", "mooring photos sent"),
            _message("2026-03-01T10:05:00Z", GROUP_CHAT, "+4790000002", "who brings rope"),
            _message(
                "2026-03-01T10:10:00Z",
                {"id": "4790000003@s.whatsapp.net", "type": "direct", "name": "Mystery"},
                "+4790000003",
                "hello?",
            ),
            {
                "at": "2026-03-01T08:30:00Z",
                "end": "2026-03-01T09:15:00Z",
                "source": "ios-calendar",
                "kind": "event",
                "tier": 1,
                "payload": {
                    "schema": "event/v1",
                    "raw_id": "uid@2026-02-27T16:05:00Z",
                    "title": "Boat survey",
                    "all_day": False,
                    "organizer": {"kind": "email", "value": "ola@example.org"},
                    "attendees": [
                        {
                            "ref": {"kind": "email", "value": "kari@example.org"},
                            "name": "Kari (work)",
                            "response": "accepted",
                        },
                        {"ref": {"kind": "email", "value": "guest@example.org"}, "name": "Guest Person"},
                        {"ref": {"kind": "email", "value": "anon@example.org"}},
                    ],
                },
            },
        ]
    )
    return lb


def _text(out: list[str]) -> list[str]:
    """The part of each row after the kind and source columns."""
    return [" ".join(line.split()[3:]) for line in out[1:]]


def test_show_names_senders_attendees_and_group_chats_from_resolution_lines(people: Logbook, capsys):
    assert _text(_show(capsys)) == [
        "Boat survey · by Ola Nordmann · with Kari Nordmann, Guest Person, anon@example.org",
        "Ola Nordmann: mooring photos sent",
        "Kari Nordmann in Boat club: who brings rope",
        "Mystery: hello?",  # the resolution of +4790000003 is retracted: the direct chat's own name
    ]


def test_show_raw_prints_refs_unchanged(people: Logbook, capsys):
    cli.main(["show", DAY, "--raw"])
    out = capsys.readouterr().out.splitlines()
    assert _text(out) == [
        "Boat survey · by ola@example.org · with kari@example.org, guest@example.org, anon@example.org",
        "+4790000001: mooring photos sent",
        "+4790000002 in 1234@g.us: who brings rope",
        "+4790000003: hello?",
    ]


def test_show_a_retracted_resolution_does_not_resolve_even_without_a_chat_name(people: Logbook, capsys):
    people.append(
        **_message(
            "2026-03-01T10:20:00Z", {"id": "x@s.whatsapp.net", "type": "direct"}, "+4790000003", "still me"
        )
    )
    assert _text(_show(capsys))[-1] == "+4790000003: still me"


def test_show_last_resolution_wins_when_neither_supersedes(people: Logbook, capsys):
    people.append(**_resolution("phone", "+4790000001", "Ola N. (new phone)", PERSON_A))
    assert _text(_show(capsys))[1] == "Ola N. (new phone): mooring photos sent"


def test_show_own_messages_say_me_and_name_the_other_side(people: Logbook, capsys):
    people.append(**_message("2026-03-01T10:30:00Z", OLA_CHAT, None, "on my way"))
    people.append(**_message("2026-03-01T10:31:00Z", GROUP_CHAT, None, None, media_kind="image"))
    assert _text(_show(capsys))[-2:] == ["me → Ola: on my way", "me in Boat club: [image]"]


def test_show_writes_nothing(people: Logbook, capsys):
    before = people.meta["head"]
    _show(capsys)
    cli.main(["show", DAY, "--raw"])
    assert people.meta["head"] == before


def test_show_without_any_resolution_still_uses_the_names_the_sources_gave(lb: Logbook, capsys):
    lb.append(**_message("2026-03-01T10:00:00Z", OLA_CHAT, "+4790000001", "hi"))
    lb.append(
        at="2026-03-01T10:01:00Z",
        source="ios-calendar",
        kind="event",
        tier=1,
        payload={
            "schema": "event/v1",
            "title": "Survey",
            "all_day": False,
            "attendees": [{"ref": {"kind": "email", "value": "guest@example.org"}, "name": "Guest Person"}],
        },
    )
    rows = _text(_show(capsys))
    assert "Ola: hi" in rows
    assert "Survey · with Guest Person" in rows
