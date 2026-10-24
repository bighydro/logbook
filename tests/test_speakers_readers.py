"""The voices of a transcript where the readers print transcripts (RFC 0038 §2, §3.4 as far as build 1
goes): `show`, the Day (text and `--json`) and `serve`'s Day. Nothing binds a label to a person yet:
a voice reads as its label, or the name its source displayed, and the owner only from `from_me`. A
transcript without `speakers` reads exactly as before. Synthetic Oslo persona."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from persona import HOME, TZ, dwell, utc

from logbook import cli
from logbook.contrib import serve
from logbook.core.store import Logbook

DAY = "2026-10-06"
CONTENT = {
    "sha256": "0b77" + "0" * 60,
    "path": f"attachments/0b77{'0' * 60}",
    "bytes": 5120,
    "media_type": "text/plain",
}
CALL = [
    {"label": "mic", "seconds": 201.7, "turns": 38, "channel": "mic", "from_me": True},
    {"label": "system", "seconds": 188.3, "turns": 35, "channel": "system", "name": "Ola Nordmann"},
]
ROOM = [{"label": "S1", "seconds": 1862.4, "turns": 212}, {"label": "S2", "seconds": 41.5, "turns": 4}]


def _transcript(
    at: str, title: str, voices: list[dict[str, Any]] | None, raw_id: str, **more: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "transcript/v1",
        "provider": "mlx-whisper",
        "raw_id": raw_id,
        "title": title,
        "participants": [],
        "content": CONTENT,
        **more,
    }
    if voices is not None:
        payload["speakers"] = voices
        payload["diarization"] = {"engine": "pyannote", "channels": 2 if voices is CALL else 1}
    return {
        "at": at,
        "end": None,
        "tz": TZ,
        "source": "transcription",
        "kind": "transcript",
        "tier": 2,
        "payload": payload,
    }


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    return lb


def _day(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(["day", DAY, *args])
    return capsys.readouterr().out


def test_show_names_the_voices_after_the_transcript_and_the_owner_only_from_from_me(lb, capsys):
    lb.append_many(
        [
            _transcript(utc(DAY, "09:15"), "Samtale", CALL, "call"),
            _transcript(utc(DAY, "19:40"), "Middag", ROOM, "dinner"),
            _transcript(utc(DAY, "21:00"), "Idé", None, "idea"),
        ]
    )
    cli.main(["show", DAY])
    rows = [row for row in capsys.readouterr().out.splitlines() if "transcript" in row]
    assert rows[0].endswith("Samtale · you · Ola Nordmann")  # who spoke most first, never their minutes
    assert rows[1].endswith("Middag · S1 · S2")  # a room's first voice is not taken for the owner
    assert rows[2].endswith("Idé") and "·" not in rows[2]  # without speakers: as before


def test_the_day_shows_the_voices_of_an_unplaced_transcript_and_its_json_shaped_for_attribution(lb, capsys):
    lb.append_many(
        [
            _transcript(utc(DAY, "09:15"), "Samtale", CALL, "call"),
            _transcript(utc(DAY, "21:00"), "Idé", None, "idea"),
        ]
    )
    text = _day(capsys)
    assert "Samtale · you · Ola Nordmann" in text and "min · Ola" not in text and "Ola Nordmann 3" not in text
    data = json.loads(_day(capsys, "--json"))
    call, idea = data["unplaced"]
    assert call["speakers"] == [
        {
            "label": "mic",
            "person": lb.meta[
                "owner_id"
            ],  # the owner's microphone is the owner, without a line (RFC 0038 §3.4)
            "name": None,
            "seconds": 201.7,
            "basis": "channel",
            "consent": None,
            "owner": True,
        },
        {
            "label": "system",
            "person": None,
            "name": "Ola Nordmann",
            "seconds": 188.3,
            "basis": None,
            "consent": None,
            "owner": False,
        },
    ]
    assert "speakers" not in idea  # a transcript without voices: the Day's object as it was


def test_the_day_shows_the_voices_of_a_transcript_attached_to_a_stay(lb, capsys):
    lb.append_many(
        [
            *dwell(DAY, "18:00", "23:00", HOME, seed=3),
            _transcript(utc(DAY, "19:40"), "Middag", ROOM, "dinner"),
        ]
    )
    text = _day(capsys)
    assert "Middag · S1 · S2\n" in text
    data = json.loads(_day(capsys, "--json"))
    attached = [
        t for entry in data["timeline"] if entry.get("attached") for t in entry["attached"]["transcripts"]
    ]
    assert [(t["title"], [s["label"] for s in t["speakers"]]) for t in attached] == [("Middag", ["S1", "S2"])]
    assert all(s["owner"] is False and s["person"] is None for s in attached[0]["speakers"])


def test_a_transcript_heard_again_stands_in_the_day_for_the_one_it_supersedes(lb, capsys):
    """`derive speakers` writes a line that supersedes the old one at the same instant: the Day lists
    the standing line; a retracted superseder hides nothing."""
    lb.append_many([_transcript(utc(DAY, "19:40"), "Middag", None, "dinner")])
    with lb.index() as idx:
        [old] = list(idx.of_kind("transcript"))
    lb.append_many(
        [_transcript(utc(DAY, "19:40"), "Middag", ROOM, "dinner#speakers@a9e2", supersedes=old["id"])]
    )
    data = json.loads(_day(capsys, "--json"))
    assert [(item["title"], "speakers" in item) for item in data["unplaced"]] == [("Middag", True)]
    with lb.index() as idx:
        new = next(line for line in idx.of_kind("transcript") if line["id"] != old["id"])
    lb.retract(new["seq"], "heard wrong")
    data = json.loads(_day(capsys, "--json"))
    assert [(item["line"], "speakers" in item) for item in data["unplaced"]] == [(old["id"], False)]


def test_serve_s_day_shows_the_voices(lb):
    lb.append_many([_transcript(utc(DAY, "09:15"), "Samtale", CALL, "call")])
    response = serve.Site(lb).respond(f"/day/{DAY}", "")
    assert response.status == 200
    body = response.body if isinstance(response.body, str) else response.body.decode("utf-8")
    assert "Samtale · you · Ola Nordmann" in body and "Ola Nordmann 3 min" not in body


def test_a_reader_shows_nothing_for_voices_it_cannot_read(lb, capsys):
    lb.append_many([_transcript(utc(DAY, "09:15"), "Samtale", None, "call", speakers="mic,system")])
    assert "Samtale" in _day(capsys) and "speakers" not in json.loads(_day(capsys, "--json"))["unplaced"][0]
    cli.main(["show", DAY])
    assert capsys.readouterr().out.rstrip().endswith("Samtale")


def test_show_marks_the_transcript_heard_again_as_superseded_and_drops_the_writer_s_zero_turns(lb, capsys):
    lb.append_many(
        [_transcript(utc(DAY, "19:40"), "Middag", None, "dinner", extra={"turns": 0, "duration_s": 2})]
    )
    with lb.index() as idx:
        [old] = list(idx.of_kind("transcript"))
    lb.append_many(
        [
            _transcript(
                utc(DAY, "19:40"),
                "Middag",
                ROOM,
                "dinner#speakers@a9e2",
                supersedes=old["id"],
                extra={"turns": 0, "duration_s": 2},
            )
        ]
    )
    with lb.index() as idx:
        new = next(line for line in idx.of_kind("transcript") if line["id"] != old["id"])
    cli.main(["show", DAY])
    rows = [row for row in capsys.readouterr().out.splitlines() if "transcript" in row]
    assert rows[0].endswith(f"superseded by #{new['seq']}")
    assert rows[1].endswith("Middag; 2 s · S1 · S2")  # no "0 turns" beside the voices, nor their minutes
    lb.retract(new["seq"], "heard wrong")
    cli.main(["show", DAY])
    out = capsys.readouterr().out
    assert "Middag; 0 turns, 2 s" in out and "superseded by" not in out  # a retracted line supersedes nothing
