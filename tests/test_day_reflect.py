"""`logbook day reflect DAY`: a spoken (or typed, or dictated) reflection at the end of the day becomes
one `note/v1` line on it, labelled `reflection`; the rules of `promises` read it for commitments,
delegations and what became of the day's commitments, printed as numbered proposals and written only
when the owner accepts them; `--sign` signs the day through `signing.sign`, the reflection among the
lines confirmed. The Day shows the reflection in a section of its own. Whisper is faked: no model runs.
Synthetic Oslo persona, who does not exist."""

from __future__ import annotations

import io
import itertools
import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.commands import day as day_command
from logbook.contrib import mcp_server, promises, reflect
from logbook.contrib import serve as serve_module
from logbook.core import attachments, notes, policy, signing, store
from logbook.core.store import Logbook
from logbook.labs import transcribe

TZ = "Europe/Oslo"
DAY = "2026-03-03"  # a Tuesday, CET
AT = "2026-03-03T21:40:00+01:00"  # when the owner spoke, on the day
AT_UTC = "2026-03-03T20:40:00Z"

PROMISES = {
    2: "I'll send the mooring photos to the harbour office by Friday.",
    3: "I need to call the crane company about the haul-out.",
    4: "I have to buy varnish for the hatch.",
}
SENTENCES = [
    "Good day on the boat.",
    "The mooring photos went out to the harbour office.",  # 2: kept #2
    "The crane company call about the haul-out is for next week.",  # 3: carried #3
    "Forget the varnish, the hatch can wait.",  # 4: dropped #4
    "I'll fix the bilge pump on Saturday.",  # 5: a commitment
    "Ola should book the ferry for Sunday.",  # 6: a delegation to Ola
    "Ask Ines to send the insurance papers.",  # 7: a delegation to Ines
    "Ich werde die Rechnung morgen bezahlen.",  # 8: a commitment, in German
    "Ola soll den Anhänger zurückbringen.",  # 9: a delegation to Ola, in German
]
REFLECTION = " ".join(SENTENCES)
# the proposals of REFLECTION, numbered as printed: commitments, delegations, then dispositions
COMMITMENT_BILGE, COMMITMENT_BILL, TO_OLA, TO_INES, TO_OLA_DE, KEPT_2, CARRIED_3, DROPPED_4 = range(1, 9)


def _location(at: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "dawarich",
        "kind": "location",
        "tier": 1,
        "payload": {"schema": "location/v1", "lat": 59.91, "lon": 10.75, "raw_id": f"dawarich:{at}"},
    }


def _note(at: str, text: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "manual",
        "kind": "note",
        "tier": 2,
        "payload": {"schema": "note/v1", "text": text},
    }


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """3 March 2026 (CET): two locations and three of the owner's commitments on the page."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.setattr(day_command, "_on_a_tty", lambda: False)
    lb.append_many(
        [
            _location("2026-03-03T06:30:00Z"),  # seq 1
            _note("2026-03-03T07:00:00Z", PROMISES[2]),  # seq 2
            _note("2026-03-03T08:00:00Z", PROMISES[3]),  # seq 3
            _note("2026-03-03T09:00:00Z", PROMISES[4]),  # seq 4
            _location("2026-03-03T18:00:00Z"),  # seq 5
        ]
    )
    return lb


def _dictation(lb: Logbook, at: str, text: str, n: int) -> dict[str, Any]:
    """A Wispr Flow dictation as the adapter writes it: a transcript/v1 line, tier 3, its text in the
    attachment store."""
    data = text.encode("utf-8")
    lb.attach(data)
    return lb.append(
        at=at,
        source="wispr-flow",
        kind="transcript",
        tier=3,
        payload={
            "schema": "transcript/v1",
            "provider": "wispr-flow",
            "raw_id": f"wispr-flow:0000000{n}-0000-4000-8000-000000000000",
            "participants": [],
            "content": attachments.reference(data, "text/plain"),
            "extra": {"text": "formatted", "app": "com.example.notes"},
        },
    )


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(list(args))
    return capsys.readouterr().out


def _fails(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    with pytest.raises(SystemExit) as e:
        cli.main(list(args))
    assert e.value.code == 2
    return capsys.readouterr().err


def _by_seq(lb: Logbook) -> dict[int, dict[str, Any]]:
    return {int(line["seq"]): line for line in lb.lines()}


def _kinds(lb: Logbook) -> list[str]:
    return [str(line["kind"]) for line in lb.lines()]


def _files(root: Path) -> dict[Path, bytes]:
    return {
        p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file() and "state" not in p.parts
    }


def _ids(lb: Logbook) -> dict[int, str]:
    return {seq: str(line["id"]) for seq, line in _by_seq(lb).items()}


class FakeEngine:
    """Hears REFLECTION in every recording, cut in two mid-sentence as whisper cuts its segments."""

    name = "fake-whisper"

    def __init__(self, model: str = "small", ready: bool = True) -> None:
        self.model = model
        self._ready = ready
        self.loaded: list[Path] = []
        self.offline: list[str | None] = []

    def ready(self) -> bool:
        return self._ready

    def fetch(self) -> None:
        self._ready = True

    def load(self, path: Path) -> tuple[list[float], int]:
        self.loaded.append(Path(path))
        return [0.0] * 32_000, 16_000

    def transcribe(self, samples: Any, rate: int, language: str | None) -> transcribe.Result:
        self.offline.append(os.environ.get("HF_HUB_OFFLINE"))
        cut = REFLECTION.index(" to the harbour office")
        return transcribe.Result(
            [transcribe.Segment(0.0, 9.0, REFLECTION[:cut]), transcribe.Segment(9.0, 18.0, REFLECTION[cut:])],
            language or "en",
        )


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> FakeEngine:
    found = FakeEngine()
    monkeypatch.setattr(transcribe, "detect", lambda model="small", **_k: found)
    return found


def _audio(tmp_path: Path) -> Path:
    path = tmp_path / "evening.m4a"
    path.write_bytes(b"not really audio: the fake engine never decodes it")
    return path


# -- 1. the reflection: one note/v1 line, labelled, tier 2 -----------------------------------------------


def test_text_writes_one_reflection_note_and_prints_it_back_with_line_numbers(
    lb: Logbook, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    def no_engine(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("--text never asks for an engine")

    monkeypatch.setattr(transcribe, "detect", no_engine)
    out = _run(capsys, "day", "reflect", DAY, "--text", REFLECTION, "--at", AT)
    assert lb.meta["seq"] == 6, "one line and nothing else"
    line = _by_seq(lb)[6]
    assert (line["kind"], line["tier"], line["source"], line["at"]) == ("note", 2, "reflect", AT_UTC)
    assert line["payload"] == {"schema": "note/v1", "text": REFLECTION, "labels": ["reflection"]}
    for n, sentence in enumerate(SENTENCES, 1):
        assert f"  {n:>3}  {sentence}" in out
    assert "wrote the reflection as #6 note/v1" in out
    assert "nothing else was written" in out
    assert "signed-day" not in _kinds(lb)
    assert lb.verify()[2] == []


def test_text_without_at_lands_on_the_day(lb: Logbook, capsys: pytest.CaptureFixture[str]):
    _run(capsys, "day", "reflect", DAY, "--text", "A quiet one.")
    assert _by_seq(lb)[6]["at"] == "2026-03-03T22:59:00Z", "a past day without --at: its last minute"


def test_audio_is_heard_locally_and_written_as_the_reflection(
    lb: Logbook, tmp_path: Path, engine: FakeEngine, capsys: pytest.CaptureFixture[str]
):
    audio = _audio(tmp_path)
    out = _run(capsys, "day", "reflect", DAY, "--audio", str(audio), "--at", AT)
    line = _by_seq(lb)[6]
    assert line["payload"]["text"] == REFLECTION, "segments joined with a space, never split mid-sentence"
    assert line["payload"]["labels"] == ["reflection"]
    assert line["payload"]["extra"] == {
        "heard_by": {"engine": "fake-whisper", "model": "small", "language": "en"}
    }
    assert (line["source"], line["tier"]) == ("reflect", 2)
    assert engine.loaded == [audio]
    assert engine.offline and all(flag == "1" for flag in engine.offline), "the hub is offline while hearing"
    assert "  9  Ola soll den Anhänger zurückbringen." in out


def test_audio_without_the_extra_refuses_with_the_install_hint(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    real = transcribe.detect

    def nothing_installed(model: str = "small", **_k: Any) -> Any:
        def importer(name: str) -> Any:
            raise ImportError(name)

        return real(model, importer=importer)

    monkeypatch.setattr(transcribe, "detect", nothing_installed)
    before = _files(lb.root)
    err = _fails(capsys, "day", "reflect", DAY, "--audio", str(_audio(tmp_path)))
    assert "openlogbook[transcribe]" in err
    assert _files(lb.root) == before
    _run(capsys, "day", "reflect", DAY, "--text", "Typed instead.")  # --text always works
    assert _by_seq(lb)[6]["payload"]["text"] == "Typed instead."


def test_audio_refuses_a_model_not_on_this_machine_and_a_missing_file(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    absent = FakeEngine(ready=False)
    monkeypatch.setattr(transcribe, "detect", lambda model="small", **_k: absent)
    err = _fails(capsys, "day", "reflect", DAY, "--audio", str(_audio(tmp_path)))
    assert "--fetch-model" in err and lb.meta["seq"] == 5
    err = _fails(capsys, "day", "reflect", DAY, "--audio", str(tmp_path / "nowhere.m4a"))
    assert "nowhere.m4a" in err and lb.meta["seq"] == 5


def test_mic_refuses_plainly_off_macos_and_without_ffmpeg(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], engine: FakeEngine
):
    monkeypatch.setattr(reflect, "_platform", lambda: "linux")
    assert "macOS" in _fails(capsys, "day", "reflect", DAY, "--mic", "30")
    monkeypatch.setattr(reflect, "_platform", lambda: "darwin")
    monkeypatch.setattr(reflect.shutil, "which", lambda _name: None)
    assert "ffmpeg" in _fails(capsys, "day", "reflect", DAY, "--mic", "30")
    assert lb.meta["seq"] == 5


def test_mic_takes_one_second_to_half_an_hour(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], engine: FakeEngine
):
    monkeypatch.setattr(reflect, "_platform", lambda: "darwin")
    assert "from 1 to 1800" in _fails(capsys, "day", "reflect", DAY, "--mic", "0.5")
    assert "from 1 to 1800" in _fails(capsys, "day", "reflect", DAY, "--mic", "3600")
    assert lb.meta["seq"] == 5


def test_mic_refuses_when_no_microphone_answers(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], engine: FakeEngine
):
    monkeypatch.setattr(reflect, "_platform", lambda: "darwin")
    monkeypatch.setattr(reflect.shutil, "which", lambda _name: "/opt/example/bin/ffmpeg")

    def fails(command: list[str], **_k: Any) -> Any:
        return reflect.subprocess.CompletedProcess(command, 1, b"", b"Input/output error")

    monkeypatch.setattr(reflect.subprocess, "run", fails)
    assert "no microphone" in _fails(capsys, "day", "reflect", DAY, "--mic", "30")
    assert lb.meta["seq"] == 5


def test_mic_records_then_hears_the_recording(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], engine: FakeEngine
):
    monkeypatch.setattr(reflect, "_platform", lambda: "darwin")
    monkeypatch.setattr(reflect.shutil, "which", lambda _name: "/opt/example/bin/ffmpeg")
    ran: list[list[str]] = []

    def records(command: list[str], **_k: Any) -> Any:
        ran.append(command)
        Path(command[-1]).write_bytes(b"RIFF" + b"\0" * 4096)
        return reflect.subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(reflect.subprocess, "run", records)
    _run(capsys, "day", "reflect", DAY, "--mic", "45", "--at", AT)
    [command] = ran
    assert command[0] == "/opt/example/bin/ffmpeg" and "avfoundation" in command and "45" in command
    assert _by_seq(lb)[6]["payload"]["text"] == REFLECTION
    assert not Path(command[-1]).exists(), "the recording is not kept"


def test_one_input_at_a_time_and_the_flags_belong_to_reflect(lb: Logbook, capsys: pytest.CaptureFixture[str]):
    assert "one of" in _fails(capsys, "day", "reflect", DAY, "--text", "a", "--audio", "b.m4a")
    assert "day reflect" in _fails(capsys, "day", DAY, "--text", "a")
    assert "day reflect" in _fails(capsys, "day", "sign", DAY, "--accept", "1")
    assert "--accept" in _fails(capsys, "day", "reflect", DAY, "--text", "a", "--accept", "1")
    assert "day sign" in _fails(capsys, "day", "reflect", DAY, "--text", "a", "--sign", "--kept", "2")
    assert "the day" in _fails(capsys, "day", "reflect")
    assert lb.meta["seq"] == 5


# -- 2. the Wispr Flow draft: a dictation that begins with "reflect" ---------------------------------------


def test_a_reflect_dictation_is_offered_as_the_draft_and_nothing_is_written_without_confirmation(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
):
    _dictation(lb, "2026-03-03T20:30:00Z", f"Reflect: {REFLECTION}", 1)
    before = _files(lb.root)
    out = _run(capsys, "day", "reflect", DAY)
    assert "Wispr Flow" in out and "21:30" in out
    assert f"    1  {SENTENCES[0]}" in out, "the draft without the word that marks it"
    assert "--from-wispr" in out and "nothing was written" in out
    assert _files(lb.root) == before


def test_from_wispr_accepts_the_draft_as_is(lb: Logbook, capsys: pytest.CaptureFixture[str]):
    said = _dictation(lb, "2026-03-03T20:30:00Z", f"  …REFLECT — {REFLECTION}", 1)
    _run(capsys, "day", "reflect", DAY, "--from-wispr")
    line = _by_seq(lb)[7]
    assert line["payload"] == {
        "schema": "note/v1",
        "text": REFLECTION,
        "labels": ["reflection"],
        "extra": {"dictation": said["id"]},
    }
    assert (line["source"], line["tier"], line["at"]) == ("reflect", 2, "2026-03-03T20:30:00Z")
    out = _run(capsys, "day", "reflect", DAY)
    assert "Wispr Flow" not in out, "a dictation taken up is not offered again"
    assert "the reflection #7" in out and lb.meta["seq"] == 7


def test_a_dictation_that_does_not_begin_with_reflect_is_ignored(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
):
    _dictation(lb, "2026-03-03T12:00:00Z", "Remind me: the guest dock is free on Saturday. Reflect later.", 1)
    _dictation(lb, "2026-03-03T13:00:00Z", "Reflection on the meeting: it went well.", 2)
    _dictation(lb, "2026-03-03T14:00:00Z", "Reflecting on it, I'll call the yard.", 3)
    err = _fails(capsys, "day", "reflect", DAY)
    assert "nothing to reflect on" in err and "reflect" in err
    assert lb.meta["seq"] == 8
    assert not reflect.begins_with_cue("Reflection on the meeting")
    assert reflect.begins_with_cue("reflect")
    assert reflect.begins_with_cue('"Reflect, quickly: done.')
    assert reflect.without_cue("¿Reflect: the day was long.") == "the day was long."


def test_the_latest_reflect_dictation_wins_and_from_wispr_id_picks_another(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
):
    early = _dictation(lb, "2026-03-03T19:00:00Z", "reflect. A first go at it.", 1)
    _dictation(lb, "2026-03-03T20:45:00Z", "Reflect: the second, and the one that counts.", 2)
    _dictation(lb, "2026-03-03T20:50:00Z", "Remind me to buy coffee.", 3)
    out = _run(capsys, "day", "reflect", DAY, "--dry-run")
    assert "the second, and the one that counts." in out and "first go" not in out
    _run(capsys, "day", "reflect", DAY, "--from-wispr", str(early["seq"]))
    assert _by_seq(lb)[9]["payload"]["text"] == "A first go at it."
    assert "not a Wispr Flow dictation" in _fails(capsys, "day", "reflect", DAY, "--from-wispr", "2")


def test_on_a_terminal_the_draft_is_confirmed_edited_or_left(
    lb: Logbook, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    _dictation(lb, "2026-03-03T20:30:00Z", "Reflect: a long day on the water.", 1)
    monkeypatch.setattr(day_command, "_on_a_tty", lambda: True)
    monkeypatch.setattr("sys.stdin", io.StringIO("n\n"))
    out = _run(capsys, "day", "reflect", DAY)
    assert "left as it is" in out and lb.meta["seq"] == 6
    monkeypatch.setattr("sys.stdin", io.StringIO("e\nA long day on the water.\nI'll call Ola tomorrow.\n\n"))
    _run(capsys, "day", "reflect", DAY)
    assert _by_seq(lb)[7]["payload"]["text"] == "A long day on the water.\nI'll call Ola tomorrow."
    assert _by_seq(lb)[7]["payload"]["extra"]["dictation"] == _by_seq(lb)[6]["id"]


def test_on_a_terminal_y_takes_the_draft(
    lb: Logbook, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    _dictation(lb, "2026-03-03T20:30:00Z", "Reflect: a long day on the water.", 1)
    monkeypatch.setattr(day_command, "_on_a_tty", lambda: True)
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
    _run(capsys, "day", "reflect", DAY)
    assert _by_seq(lb)[7]["payload"]["text"] == "a long day on the water."


# -- 3. proposals: rules only, numbered, nothing written until accepted -------------------------------------


def test_proposals_of_all_three_kinds(lb: Logbook, capsys: pytest.CaptureFixture[str]):
    ids = _ids(lb)
    found = reflect.propose(REFLECTION, DAY, reflect.commitments(lb, DAY))
    by_number = {p.number: p for p in found}
    assert sorted(by_number) == list(range(1, 9))
    bilge, bill = by_number[COMMITMENT_BILGE], by_number[COMMITMENT_BILL]
    assert (bilge.kind, bilge.sentence, bilge.due) == ("commitment", 5, "2026-03-07")
    assert (bill.kind, bill.sentence, bill.due, bill.cue) == ("commitment", 8, "2026-03-04", "Ich werde")
    assert [
        (by_number[n].kind, by_number[n].counterpart, by_number[n].sentence)
        for n in (TO_OLA, TO_INES, TO_OLA_DE)
    ] == [
        ("delegation", "Ola", 6),
        ("delegation", "Ines", 7),
        ("delegation", "Ola", 9),
    ]
    assert [
        (by_number[n].kind, by_number[n].value, by_number[n].line, by_number[n].sentence)
        for n in (KEPT_2, CARRIED_3, DROPPED_4)
    ] == [
        ("disposition", "kept", ids[2], 2),
        ("disposition", "carried", ids[3], 3),
        ("disposition", "dropped", ids[4], 4),
    ]
    assert all(p.score is not None and p.score >= reflect.MATCH for p in found if p.kind == "disposition")
    out = _run(capsys, "day", "reflect", DAY, "--text", REFLECTION, "--dry-run")
    assert "a guess until you accept it" in out
    assert "    3  delegation" in out and "to Ola" in out and "to Ines" in out
    assert "    6  kept" in out and "#2" in out and "went out" in out
    assert "    7  carried" in out and "#3" in out and "next week" in out
    assert "    8  dropped" in out and "#4" in out


def test_the_commitments_are_read_from_the_day_alone(lb: Logbook):
    lb.append(**_note("2026-03-04T08:00:00Z", "I'll send the mooring photos again tomorrow."))  # the 4th
    found = promises.extract(lb, since=DAY, until=DAY)
    assert {p.seq for p in found.proposals} == {2, 3, 4}
    assert {c.seq for c in reflect.commitments(lb, DAY)} == {2, 3, 4}
    assert {p.seq for p in promises.extract(lb, since=DAY).proposals} == {2, 3, 4, 6}


@pytest.mark.parametrize(
    ("sentence", "word"),
    [
        ("The photos went out this morning.", "kept"),
        ("Done with the photos.", "kept"),
        ("Sent the photos.", "kept"),
        ("I didn't send the photos.", "missed"),
        ("The photos, not yet.", "missed"),
        ("Drop the photos.", "dropped"),
        ("The photos? Forget it.", "dropped"),
        ("The photos go out tomorrow.", "carried"),
        ("Photos next week.", "carried"),
        ("Die Fotos sind erledigt.", "kept"),
        ("Die Fotos habe ich noch nicht geschickt.", "missed"),
        ("Die Fotos schicke ich morgen.", "carried"),
        ("The photos are lovely.", None),
    ],
)
def test_the_disposition_a_sentence_suggests(sentence: str, word: str | None):
    found = reflect.disposition_of(sentence)
    assert (found[0] if found else None) == word


def test_a_near_miss_stays_below_the_threshold(lb: Logbook, monkeypatch: pytest.MonkeyPatch):
    near = "The harbour office sent a letter about the berth fee."
    commitments = reflect.commitments(lb, DAY)
    assert reflect.propose(near, DAY, commitments) == [], "two words shared of nine is no reference"
    score = reflect.overlap(reflect.tokens(near), reflect.tokens(PROMISES[2]))
    assert 0 < score < reflect.MATCH
    monkeypatch.setattr(reflect, "MATCH", score)
    [found] = reflect.propose(near, DAY, commitments)
    assert (found.kind, found.value, found.line) == ("disposition", "kept", _ids(lb)[2])


def test_a_delegation_needs_a_name(lb: Logbook):
    for sentence in (
        "Someone should book the ferry.",
        "The ferry should leave at nine.",
        "Die Fähre soll um neun fahren.",
        "We should book the ferry.",
    ):
        assert reflect.delegation_of(sentence) is None, sentence
    assert reflect.delegation_of("Ola Nordmann should book the ferry.") == ("Ola Nordmann", "should")
    assert reflect.delegation_of("Ola, can you book the ferry?") == ("Ola", "can you")
    assert reflect.delegation_of("Frag Ines, ob sie die Papiere hat.") == ("Ines", "Frag")


# -- nothing written on the dry and unaccepted paths --------------------------------------------------------


def test_a_dry_run_writes_nothing(lb: Logbook, capsys: pytest.CaptureFixture[str]):
    before = _files(lb.root)
    out = _run(capsys, "day", "reflect", DAY, "--text", REFLECTION, "--sign", "--accept", "3,6", "--dry-run")
    assert "dry run" in out and "nothing was written" in out
    assert _files(lb.root) == before


def test_without_sign_only_the_reflection_is_written(lb: Logbook, capsys: pytest.CaptureFixture[str]):
    _run(capsys, "day", "reflect", DAY, "--text", REFLECTION)
    assert _kinds(lb)[5:] == ["note"]


def test_sign_off_a_terminal_without_accept_writes_nothing(lb: Logbook, capsys: pytest.CaptureFixture[str]):
    before = _files(lb.root)
    with pytest.raises(SystemExit) as e:
        cli.main(["day", "reflect", DAY, "--text", REFLECTION, "--sign"])
    assert e.value.code == 2
    captured = capsys.readouterr()
    assert "    8  dropped" in captured.out, "the proposals are printed first"
    assert "--accept" in captured.err and "nothing was written" in captured.err
    assert _files(lb.root) == before


def test_accept_none_signs_with_the_reflection_and_writes_no_proposal(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
):
    _run(capsys, "day", "reflect", DAY, "--text", REFLECTION, "--sign", "--accept", "none", "--at", AT)
    assert _kinds(lb)[5:] == ["note", "signed-day"]
    p = _by_seq(lb)[7]["payload"]
    assert "dispositions" not in p
    assert _by_seq(lb)[6]["id"] in p["confirmed"]


def test_an_unknown_proposal_number_is_refused_before_anything_is_written(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
):
    before = _files(lb.root)
    err = _fails(capsys, "day", "reflect", DAY, "--text", REFLECTION, "--sign", "--accept", "3,12")
    assert "12" in err and _files(lb.root) == before
    err = _fails(capsys, "day", "reflect", DAY, "--text", REFLECTION, "--sign", "--accept", "three")
    assert "three" in err and _files(lb.root) == before


def test_on_a_terminal_one_y_or_n_per_proposal_and_q_writes_nothing(
    lb: Logbook, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(day_command, "_on_a_tty", lambda: True)
    before = _files(lb.root)
    monkeypatch.setattr("sys.stdin", io.StringIO("y\nq\n"))
    out = _run(capsys, "day", "reflect", DAY, "--text", REFLECTION, "--sign", "--at", AT)
    assert "stopped" in out and _files(lb.root) == before
    # delegations 3, 4, 5 then dispositions 6, 7, 8: the commitments are read by `promises`, not asked
    monkeypatch.setattr("sys.stdin", io.StringIO("y\nn\nn\ny\nn\nn\n"))
    out = _run(capsys, "day", "reflect", DAY, "--text", REFLECTION, "--sign", "--at", AT)
    assert out.count("y/n") == 6
    assert _kinds(lb)[5:] == ["note", "note", "signed-day"]
    assert _by_seq(lb)[7]["payload"]["extra"]["to"] == "Ola"
    assert _by_seq(lb)[8]["payload"]["dispositions"] == {_ids(lb)[2]: "kept"}


# -- 4. --sign: the day signed in one go through signing.sign ---------------------------------------------


def test_sign_writes_exactly_the_expected_lines(lb: Logbook, capsys: pytest.CaptureFixture[str]):
    ids = _ids(lb)
    accepted = f"{COMMITMENT_BILGE},{TO_OLA},{TO_INES},{KEPT_2},{CARRIED_3},{DROPPED_4}"
    out = _run(
        capsys, "day", "reflect", DAY, "--text", REFLECTION, "--sign", "--accept", accepted, "--at", AT
    )
    lines = _by_seq(lb)
    assert sorted(lines) == list(range(1, 10)), "the reflection, two delegations and the signature"
    note, ola, ines, signature = lines[6], lines[7], lines[8], lines[9]
    assert note["payload"] == {"schema": "note/v1", "text": REFLECTION, "labels": ["reflection"]}
    for line, name, sentence in ((ola, "Ola", SENTENCES[5]), (ines, "Ines", SENTENCES[6])):
        assert (line["kind"], line["tier"], line["source"], line["at"]) == ("note", 2, "reflect", AT_UTC)
        assert line["payload"] == {
            "schema": "note/v1",
            "text": sentence,
            "labels": ["delegation"],
            "extra": {"to": name, "reflection": note["id"]},
        }
    assert (signature["kind"], signature["tier"], signature["source"], signature["at"]) == (
        "signed-day",
        1,
        "manual",
        AT_UTC,
    )
    p = signature["payload"]
    assert p["confirmed"] == [ids[1], ids[2], ids[3], ids[4], ids[5], note["id"], ola["id"], ines["id"]]
    assert p["dispositions"] == {ids[2]: "kept", ids[3]: "carried", ids[4]: "dropped"}
    assert "supersedes" not in p and "note" not in p
    assert "wrote delegation 3 to Ola as #7" in out and "wrote delegation 4 to Ines as #8" in out
    assert signing.summary(signature)[0] in out
    assert "commitment 1: nothing to write" in out
    assert lb.verify()[2] == []


def test_two_dispositions_for_one_line_are_refused_before_anything_is_written(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
):
    text = (
        "The mooring photos went out to the harbour office."
        " The mooring photos for the harbour office, forget it."
    )
    before = _files(lb.root)
    err = _fails(capsys, "day", "reflect", DAY, "--text", text, "--sign", "--accept", "1,2")
    assert "#2" in err and "one disposition" in err
    assert _files(lb.root) == before


def _counting_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every new line's id and `recorded_at` fixed and in order, so two records' lines compare."""
    counter = itertools.count(1)
    monkeypatch.setattr(store, "uuid7", lambda: f"019ca000-0000-7000-8000-{next(counter):012d}")
    monkeypatch.setattr(store, "now_utc", lambda: "2026-03-03T20:45:00Z")


def _last_lines(root: Path) -> list[bytes]:
    return (root / "logbook" / "2026" / "03.jsonl").read_bytes().splitlines()


def _replay(lines: list[dict[str, Any]], root: Path) -> None:
    """Append these lines' content to the record at `root` as its own writer would."""
    twin = Logbook(root)
    for line in lines:
        twin.append(
            at=line["at"],
            source=line["source"],
            kind=line["kind"],
            tier=line["tier"],
            payload=line["payload"],
            end=line.get("end"),
            tz=line.get("tz"),
        )


def test_the_signature_is_byte_for_byte_what_day_sign_writes(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    twin = Path(shutil.copytree(lb.root, tmp_path / "twin"))
    _counting_ids(monkeypatch)
    accepted = f"{TO_OLA},{KEPT_2},{CARRIED_3}"
    _run(capsys, "day", "reflect", DAY, "--text", REFLECTION, "--sign", "--accept", accepted, "--at", AT)
    written = [_by_seq(lb)[6], _by_seq(lb)[7]]
    _counting_ids(monkeypatch)
    monkeypatch.setenv("LOGBOOK_HOME", str(twin))
    _replay(written, twin)
    _run(capsys, "day", "sign", DAY, "--kept", "2", "--carried", "3", "--at", AT)
    assert _last_lines(lb.root) == _last_lines(twin)
    assert (lb.root / "logbook.json").read_bytes() == (twin / "logbook.json").read_bytes()


def test_re_signing_supersedes_and_keeps_what_the_standing_signature_said(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    _run(
        capsys,
        "day",
        "sign",
        DAY,
        "--confirm",
        "1,2,3,4",
        "--kept",
        "4",
        "--note",
        "Quiet day.",
        "--at",
        "2026-03-03T19:00:00+01:00",
    )
    first = _by_seq(lb)[6]
    twin = Path(shutil.copytree(lb.root, tmp_path / "twin"))
    _counting_ids(monkeypatch)
    out = _run(
        capsys, "day", "reflect", DAY, "--text", REFLECTION, "--sign", "--accept", f"{CARRIED_3}", "--at", AT
    )
    assert "supersedes" in out and "keeps from the signature it supersedes" in out
    ids = _ids(lb)
    p = _by_seq(lb)[8]["payload"]
    assert p["supersedes"] == first["id"]
    assert p["confirmed"] == [ids[1], ids[2], ids[3], ids[4], ids[7]], (
        "what was confirmed, and the reflection"
    )
    assert p["dispositions"] == {ids[3]: "carried", ids[4]: "kept"}
    assert p["note"] == "Quiet day."
    with lb.index() as idx:
        assert signing.signature_of(idx, DAY)["id"] == _by_seq(lb)[8]["id"]
    _counting_ids(monkeypatch)
    monkeypatch.setenv("LOGBOOK_HOME", str(twin))
    _replay([_by_seq(lb)[7]], twin)
    _run(
        capsys,
        "day",
        "sign",
        DAY,
        "--confirm",
        "1,2,3,4,7",
        "--kept",
        "4",
        "--carried",
        "3",
        "--note",
        "Quiet day.",
        "--at",
        AT,
    )
    assert _last_lines(lb.root) == _last_lines(twin)


def test_an_accepted_disposition_wins_over_the_one_it_supersedes(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
):
    _run(capsys, "day", "sign", DAY, "--carried", "4", "--at", "2026-03-03T19:00:00+01:00")
    _run(
        capsys, "day", "reflect", DAY, "--text", REFLECTION, "--sign", "--accept", f"{DROPPED_4}", "--at", AT
    )
    assert _by_seq(lb)[8]["payload"]["dispositions"] == {_ids(lb)[4]: "dropped"}


def test_signing_again_later_reuses_the_reflection_already_on_the_day(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
):
    out = _run(capsys, "day", "reflect", DAY, "--text", REFLECTION, "--at", AT)
    assert "--sign --accept" in out
    out = _run(capsys, "day", "reflect", DAY, "--sign", "--accept", f"{KEPT_2}")
    assert "the reflection #6" in out
    assert _kinds(lb)[5:] == ["note", "signed-day"], "the same words are not written twice"
    assert _by_seq(lb)[7]["payload"]["dispositions"] == {_ids(lb)[2]: "kept"}
    out = _run(capsys, "day", "reflect", DAY, "--text", REFLECTION)
    assert "the reflection #6" in out and _kinds(lb)[5:] == ["note", "signed-day"]


def test_another_writer_and_a_moved_head_are_the_documented_errors(
    lb: Logbook, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    path = lb.root / "state" / "writer.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    holder = {"pid": os.getppid(), "command": "logbook sync", "since": "2026-03-03T20:00:00Z"}
    path.write_text(json.dumps(holder), encoding="utf-8")
    err = _fails(
        capsys,
        "--no-wait",
        "day",
        "reflect",
        DAY,
        "--text",
        REFLECTION,
        "--sign",
        "--accept",
        "none",
        "--at",
        AT,
    )
    assert "another logbook command is writing to this record (logbook sync" in err
    assert lb.meta["seq"] == 5
    path.unlink()
    read = signing.page

    def page_then_append(*args: Any, **kwargs: Any) -> Any:
        found = read(*args, **kwargs)
        Logbook(lb.root).append(**_location("2026-03-03T21:00:00Z"))  # a writer inside this process's hold
        return found

    monkeypatch.setattr(signing, "page", page_then_append)
    err = _fails(
        capsys, "day", "reflect", DAY, "--text", REFLECTION, "--sign", "--accept", "none", "--at", AT
    )
    assert "head moved" in err and "nothing was signed" in err
    assert "signed-day" not in _kinds(lb)


def test_at_must_fall_on_the_day_and_a_day_ahead_is_refused(lb: Logbook, capsys: pytest.CaptureFixture[str]):
    assert "not on 2026-03-03" in _fails(
        capsys, "day", "reflect", DAY, "--text", "x", "--at", "2026-03-04T08:00:00+01:00"
    )
    assert "RFC 3339" in _fails(capsys, "day", "reflect", DAY, "--text", "x", "--at", "tonight")
    assert "ahead" in _fails(capsys, "day", "reflect", "2099-01-01", "--text", "x")
    assert "empty" in _fails(capsys, "day", "reflect", DAY, "--text", "   ")
    assert lb.meta["seq"] == 5


# -- 5. the Day shows the reflection in a section of its own -----------------------------------------------


def test_the_day_shows_the_reflection_between_the_header_and_the_timeline(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
):
    out = _run(capsys, "day", DAY, "--no-anniversaries")
    assert "reflection" not in out
    data = json.loads(_run(capsys, "day", DAY, "--json", "--no-anniversaries"))
    assert "reflection" not in data, "absent when there is none: the Day's object is unchanged"
    _run(capsys, "day", "reflect", DAY, "--text", REFLECTION, "--at", AT)
    rows = _run(capsys, "day", DAY, "--no-anniversaries").splitlines()
    at = next(i for i, row in enumerate(rows) if row.startswith("  reflection"))
    country = next(i for i, row in enumerate(rows) if row.startswith("  country"))
    first_timeline = next(
        i for i, row in enumerate(rows) if i > at and row.startswith("  ") and "\u2013" in row
    )
    assert country < at < first_timeline
    assert "21:40" in rows[at]
    words = " ".join(" ".join(rows[at + 1 : first_timeline]).split())
    assert REFLECTION in words
    data = json.loads(_run(capsys, "day", DAY, "--json", "--no-anniversaries"))
    assert data["reflection"] == {
        "line": _by_seq(lb)[6]["id"],
        "seq": 6,
        "at": AT_UTC,
        "at_local": "2026-03-03T21:40:00+01:00",
        "source": "reflect",
        "text": REFLECTION,
    }


def test_the_latest_reflection_stands_and_a_retracted_one_is_gone(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
):
    _run(capsys, "day", "reflect", DAY, "--text", "First thoughts.", "--at", "2026-03-03T20:00:00+01:00")
    _run(capsys, "day", "reflect", DAY, "--text", "Second thoughts.", "--at", AT)
    data = json.loads(_run(capsys, "day", DAY, "--json", "--no-anniversaries"))
    assert data["reflection"]["text"] == "Second thoughts."
    lb.retract(7, "said twice")
    data = json.loads(_run(capsys, "day", DAY, "--json", "--no-anniversaries"))
    assert data["reflection"]["text"] == "First thoughts."


def test_the_day_page_in_the_browser_shows_the_reflection_above_the_timeline(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
):
    _run(capsys, "day", "reflect", DAY, "--text", REFLECTION, "--at", AT)
    page = serve_module.Site(lb).page_day(DAY)
    assert "<h2>Reflection</h2>" in page
    assert page.index("<h2>Reflection</h2>") < page.index("<h2>Timeline</h2>")
    assert "Ola soll den Anhänger zurückbringen." in page and "bilge pump on Saturday" in page


# -- 6. the MCP: day_lines shows a reflection like any note -------------------------------------------------


def test_day_lines_shows_the_reflection_like_any_note(lb: Logbook, capsys: pytest.CaptureFixture[str]):
    _run(capsys, "day", "reflect", DAY, "--text", "Good day on the boat.", "--at", AT)
    path = policy.policy_path(lb.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcp": {"max_tier": 2}}), encoding="utf-8")
    rows = mcp_server.call(lb.root, "day_lines", {"day": DAY})["data"]["lines"]
    row = next(r for r in rows if r["seq"] == 6)
    assert (row["kind"], row["source"], row["tier"]) == ("note", "reflect", 2)
    assert "Good day on the boat." in row["text"]


def test_note_day_and_reflect_share_one_note_path(lb: Logbook, monkeypatch: pytest.MonkeyPatch):
    written: list[tuple[str, str]] = []
    real = notes.write

    def spy(*args: Any, **kwargs: Any) -> Any:
        line = real(*args, **kwargs)
        written.append((line["source"], line["payload"]["labels"][0]))
        return line

    monkeypatch.setattr(notes, "write", spy)
    path = policy.policy_path(lb.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"mcp": {"max_tier": 1, "write": ["note_day"], "write_window_days": 400}}),
        encoding="utf-8",
    )
    mcp_server.call(lb.root, "note_day", {"day": DAY, "text": "From the phone.", "kind": "reflection"})
    cli.main(["day", "reflect", DAY, "--text", "From the shell."])
    assert written == [("mcp", "reflection"), ("reflect", "reflection")]
