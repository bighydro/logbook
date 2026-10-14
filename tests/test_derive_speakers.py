"""`logbook derive speakers [--since DAY] [--speakers N] [--dry-run]` (RFC 0038 §2.8): the transcripts
heard before the voices were separated, heard again from their recording's audio in the store, each
written as a new `transcript/v1` line that supersedes the old one, `raw_id`
`<old raw_id>#speakers@<12 hex of the spans file's digest>`, so the same spans never write twice. The
engine and the diarizer are fakes; the audio is a synthetic tone; no model is loaded, no socket opened."""

from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Any

import pytest
from test_transcribe import TZ, FakeDiarizer, FakeEngine, _memo, _wav

from logbook import cli
from logbook.core import signing
from logbook.core.store import Logbook
from logbook.labs import diarize, transcribe

MEMO_ID = "7A1B2C3D-0000-4000-8000-000000000038"
AT = "2026-10-03T17:40:12Z"  # 19:40 in Oslo, Saturday 3 October 2026


@pytest.fixture(autouse=True)
def _no_real_diarizer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(diarize, "detect", lambda *_a, **_k: None)


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook.init(root, TZ)


def _heard_before(lb: Logbook, raw_id: str = MEMO_ID, at: str = AT, **memo: Any) -> dict[str, Any]:
    """A memo with its audio, transcribed the way it was before voices were separated: its line."""
    _memo(lb, raw_id, at, title="Middag", audio=_wav(), **memo)
    transcribe.run(lb, FakeEngine(), diarizer=None, chunk_s=1.0)
    return _transcript(lb, raw_id)


def _transcript(lb: Logbook, raw_id: str) -> dict[str, Any]:
    with lb.index() as idx:
        return next(line for line in idx.of_kind("transcript") if line["payload"]["raw_id"] == raw_id)


def _transcripts(lb: Logbook) -> list[dict[str, Any]]:
    with lb.index() as idx:
        return list(idx.of_kind("transcript"))


def _detect(model: str, **kwargs: Any) -> FakeEngine:
    """`transcribe.detect` for a run that separates voices: it asks for word times."""
    assert kwargs == {"words": True}
    return FakeEngine(model)


def test_a_transcript_heard_before_is_heard_again_and_a_new_line_supersedes_it(lb):
    old = _heard_before(lb)
    report = transcribe.unseparated(lb)
    assert [item.line["id"] for item in report.found] == [old["id"]]
    transcribe.rehear(lb, report, lambda model: FakeEngine(model), FakeDiarizer(), chunk_s=1.0)
    assert report.written == 1
    new = next(line for line in _transcripts(lb) if line["id"] != old["id"])
    p = new["payload"]
    spans = p["diarization"]["spans"]["sha256"]
    assert p["raw_id"] == f"{MEMO_ID}#speakers@{spans[:12]}"
    assert p["supersedes"] == old["id"]
    assert (new["source"], new["kind"], new["tier"]) == (old["source"], "transcript", old["tier"])
    assert (new["at"], new["end"], new["tz"], p["title"]) == (old["at"], old["end"], old["tz"], "Middag")
    assert p["provenance"]["source"] == old["payload"]["provenance"]["source"]  # the same recording
    assert p["extra"]["recording"] == MEMO_ID
    assert [s["label"] for s in p["speakers"]] == ["S1", "S2"]
    assert old in _transcripts(lb)  # the old line stays, superseded, as every correction does


def test_a_second_run_hears_nothing_and_writes_nothing(lb):
    _heard_before(lb)
    transcribe.rehear(lb, transcribe.unseparated(lb), lambda model: FakeEngine(model), FakeDiarizer())
    again = transcribe.unseparated(lb)
    assert again.found == [] and again.already == 1  # the new line has speakers; the old one is superseded
    engine = FakeEngine()
    transcribe.rehear(lb, again, lambda model: engine, FakeDiarizer())
    assert again.written == 0 and engine.calls == [] and len(_transcripts(lb)) == 2


def test_the_same_spans_never_write_twice(lb):
    """Retract the new line and the old one stands again; heard again, the voices are the same, the
    spans file is the same, the key is the same, and nothing is written."""
    old = _heard_before(lb)
    transcribe.rehear(lb, transcribe.unseparated(lb), lambda model: FakeEngine(model), FakeDiarizer())
    new = next(line for line in _transcripts(lb) if line["id"] != old["id"])
    lb.retract(new["seq"], "heard wrong")
    again = transcribe.unseparated(lb)
    assert [item.line["id"] for item in again.found] == [old["id"]]  # a retracted line supersedes nothing
    engine = FakeEngine()
    transcribe.rehear(lb, again, lambda model: engine, FakeDiarizer())
    assert engine.calls != [] and again.written == 0 and again.same == 1
    assert len(_transcripts(lb)) == 2
    # other voices are other spans: a new line, superseding the old one again
    other = transcribe.unseparated(lb)
    transcribe.rehear(lb, other, lambda model: FakeEngine(model), FakeDiarizer(turns=[(0.0, 2.0, "A")]))
    assert other.written == 1 and len(_transcripts(lb)) == 3


def test_the_number_of_voices_the_owner_gives_is_a_hint_to_the_diarizer(lb):
    _heard_before(lb)
    diarizer = FakeDiarizer()
    transcribe.rehear(lb, transcribe.unseparated(lb), lambda model: FakeEngine(model), diarizer, hint=3)
    assert [speakers for _n, _rate, speakers in diarizer.calls] == [3]


def test_the_whisper_model_that_heard_a_transcript_hears_it_again(lb):
    _memo(lb, MEMO_ID, AT, title="Middag", audio=_wav())
    transcribe.run(lb, FakeEngine("large-v3"), diarizer=None)
    report = transcribe.unseparated(lb)
    asked: list[str] = []

    def engine_for(model: str) -> FakeEngine:
        asked.append(model)
        return FakeEngine(model)

    transcribe.rehear(lb, report, engine_for, FakeDiarizer())
    assert asked == ["large-v3"]
    new = next(line for line in _transcripts(lb) if "speakers" in line["payload"])
    assert new["payload"]["provenance"]["model"] == "large-v3"


def test_a_model_not_on_this_machine_stops_the_run_before_anything_is_heard(lb):
    _heard_before(lb)
    report = transcribe.unseparated(lb)
    engine = FakeEngine(ready=False)
    with pytest.raises(transcribe.ModelMissing):
        transcribe.rehear(lb, report, lambda model: engine, FakeDiarizer())
    assert engine.calls == [] and engine.fetched == 0 and len(_transcripts(lb)) == 1


def test_what_cannot_be_heard_again_is_left_alone_and_counted(lb):
    _heard_before(lb)  # one to hear again
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000002", "2026-10-04T10:00:00Z", audio=_wav())
    transcribe.run(lb, FakeEngine(), diarizer=FakeDiarizer())  # separated at ingest already
    lb.append_many(  # a provider's transcript, with no recording in the record
        [
            {
                "at": "2026-10-05T10:00:00Z",
                "end": None,
                "tz": TZ,
                "source": "granola",
                "kind": "transcript",
                "tier": 3,
                "payload": {"schema": "transcript/v1", "provider": "granola", "raw_id": "granola:not_1"},
            }
        ]
    )
    gone = _memo(lb, "7A1B2C3D-0000-4000-8000-000000000003", "2026-10-06T10:00:00Z", audio=_wav(1.0))
    transcribe.run(lb, FakeEngine(), diarizer=None)
    (lb.root / gone["payload"]["media"]["path"]).unlink()  # the audio gone from this copy of the record
    report = transcribe.unseparated(lb)
    assert [item.line["payload"]["raw_id"] for item in report.found] == [MEMO_ID]
    assert report.already == 1
    assert report.counts == {"skipped_no_recording": 1, "skipped_no_audio": 1}
    text = transcribe.describe_again(report)
    assert "no recording of their own" in text and "audio" in text


def test_since_takes_the_transcripts_from_that_local_day_on(lb):
    _heard_before(lb)
    _heard_before(lb, "7A1B2C3D-0000-4000-8000-000000000002", "2026-10-10T10:00:00Z")
    report = transcribe.unseparated(lb, since="2026-10-10")
    found = [item.line["payload"]["raw_id"] for item in report.found]
    assert found == ["7A1B2C3D-0000-4000-8000-000000000002"]


def test_a_recording_in_which_no_voice_is_found_writes_nothing(lb):
    _heard_before(lb)
    report = transcribe.unseparated(lb)
    transcribe.rehear(lb, report, lambda model: FakeEngine(model), FakeDiarizer(turns=[]))
    assert report.written == 0 and report.voiceless == 1 and len(_transcripts(lb)) == 1


def test_the_cost_is_said_before_anything_is_written(lb):
    """A superseding line on a signed day changes the day's page; a promise closed on the old line is
    proposed again from the new one (SPEC §3.2.10 rule 2 takes a promise's id from its line)."""
    old = _heard_before(lb)
    signing.sign(lb, "2026-10-03")
    lb.append_many(
        [
            {
                "at": "2026-10-04T08:00:00Z",
                "end": None,
                "tz": TZ,
                "source": "manual",
                "kind": "task",
                "tier": 2,
                "payload": {
                    "schema": "task/v1",
                    "raw_id": "promise:0123456789abcdef@2026-10-04T08:00:00Z",
                    "title": "Jeg sender deg bildene i morgen.",
                    "status": "done",
                    "extra": {"promise": "0123456789abcdef", "origin": old["id"]},
                },
            }
        ]
    )
    report = transcribe.unseparated(lb)
    assert report.signed == ["2026-10-03"] and report.promises == 1
    said = transcribe.cost(report)
    assert any("2026-10-03" in s and "logbook day sign" in s for s in said)
    assert any("1 promise" in s and "promises done" in s for s in said)


def test_no_socket_is_opened_while_voices_are_separated_again(lb, monkeypatch):
    _heard_before(lb)

    def refuse(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a socket was opened")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    diarizer = FakeDiarizer()
    report = transcribe.unseparated(lb)
    transcribe.rehear(lb, report, lambda model: FakeEngine(model), diarizer)
    assert report.written == 1 and diarizer.env_seen == [("1", "0")]
    assert os.environ.get("HF_HUB_OFFLINE") != "1"


# -- through the CLI --------------------------------------------------------------------------------


def test_the_command_separates_says_what_it_did_and_a_rerun_writes_nothing(lb, monkeypatch, capsys):
    _heard_before(lb)
    monkeypatch.setattr(transcribe, "detect", _detect)
    monkeypatch.setattr(diarize, "detect", lambda *_a, **_k: FakeDiarizer())
    cli.main(["derive", "speakers"])
    out = capsys.readouterr().out
    assert "Middag: 2 voices" in out
    assert "separated the voices of 1 transcript" in out and "superseding" in out
    cli.main(["derive", "speakers"])
    out = capsys.readouterr().out
    assert "nothing to separate" in out and "1 separated already" in out


def test_the_command_passes_the_number_of_voices_and_refuses_a_number_that_is_none(lb, monkeypatch, capsys):
    _heard_before(lb)
    diarizer = FakeDiarizer()
    monkeypatch.setattr(transcribe, "detect", _detect)
    monkeypatch.setattr(diarize, "detect", lambda *_a, **_k: diarizer)
    for bad in ("0", "-2", "two"):
        with pytest.raises(SystemExit) as e:
            cli.main(["derive", "speakers", "--speakers", bad])
        assert e.value.code == 2
    cli.main(["derive", "speakers", "--speakers", "2", "--since", "2026-10-01"])
    assert [speakers for _n, _rate, speakers in diarizer.calls] == [2]


def test_a_dry_run_lists_what_would_be_heard_again_and_the_signed_days_and_needs_no_engine(
    lb, monkeypatch, capsys
):
    _heard_before(lb)
    signing.sign(lb, "2026-10-03")

    def nothing(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a dry run asked for an engine")

    monkeypatch.setattr(transcribe, "detect", nothing)
    monkeypatch.setattr(diarize, "detect", nothing)
    cli.main(["derive", "speakers", "--dry-run"])
    out = capsys.readouterr().out
    assert "2026-10-03 19:40  Middag" in out
    assert "dry run: the voices of 1 transcript would be separated" in out and "nothing written" in out
    assert "2026-10-03" in out and "logbook day sign" in out
    assert len(_transcripts(lb)) == 1


def test_without_the_diarizer_the_command_names_the_one_that_fetches_it_and_writes_nothing(
    lb, monkeypatch, capsys
):
    _heard_before(lb)
    monkeypatch.setattr(transcribe, "detect", lambda model, **_k: FakeEngine(model))
    with pytest.raises(SystemExit) as e:
        cli.main(["derive", "speakers"])
    assert e.value.code == 2
    assert "logbook setup speakers --fetch-model" in capsys.readouterr().err
    assert len(_transcripts(lb)) == 1


def test_with_nothing_to_separate_the_command_needs_no_diarizer(lb, monkeypatch, capsys):
    cli.main(["derive", "speakers"])
    assert "nothing to separate" in capsys.readouterr().out
