"""`logbook transcribe voice-memos`: a transcript/v1 line per voice-memo line whose audio is in the
attachment store, written by a local engine and pointing back at the memo (RFC 0004, RFC 0023). The
engine here is a fake that reads a synthetic two-second WAV; no model is ever downloaded."""

from __future__ import annotations

import io
import json
import math
import os
import socket
import struct
import wave
from array import array
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.core import attachments
from logbook.core.store import Logbook
from logbook.labs import transcribe

TZ = "Europe/Oslo"
RATE = 16_000
SECONDS = 2
MEMO = "voice-memos"


def _wav(seconds: float = SECONDS, tone_hz: float = 440.0) -> bytes:
    """A mono 16-bit WAV of a sine tone: nobody's voice."""
    n = int(seconds * RATE)
    frames = array("h", (int(12_000 * math.sin(2 * math.pi * tone_hz * i / RATE)) for i in range(n)))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(frames.tobytes())
    return buf.getvalue()


class FakeEngine:
    """Reads the WAV with the stdlib and answers one segment per call, saying how many samples it
    got; `language` is `nb` when none was asked for, else what was asked for."""

    name = "fake-whisper"

    def __init__(self, model: str = "small", ready: bool = True) -> None:
        self.model = model
        self.calls: list[tuple[int, str | None]] = []
        self.fetched = 0
        self._ready = ready
        self.offline_seen: list[str | None] = []

    def ready(self) -> bool:
        return self._ready

    def fetch(self) -> None:
        self.fetched += 1
        self._ready = True

    def load(self, path: Path) -> tuple[list[int], int]:
        with wave.open(str(path), "rb") as w:
            samples = list(array("h", w.readframes(w.getnframes())))
            return samples, w.getframerate()

    def transcribe(self, samples: Any, rate: int, language: str | None) -> transcribe.Result:
        self.calls.append((len(samples), language))
        self.offline_seen.append(os.environ.get("HF_HUB_OFFLINE"))
        seconds = len(samples) / rate
        return transcribe.Result(
            segments=[transcribe.Segment(0.0, seconds, f"{len(samples)} samples heard")],
            language=language or "nb",
        )


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook.init(root, TZ)


def _memo(
    lb: Logbook,
    raw_id: str,
    at: str,
    *,
    title: str = "Idea for the talk",
    audio: bytes | None = None,
    stored: bool = True,
    tier: int = 2,
    supersedes: str | None = None,
) -> dict[str, Any]:
    """A voice-memo/v1 draft, appended; with `audio` the bytes are referenced and, when `stored`, put
    in the §1.1 store (as `logbook add voice-memos --attachments` does)."""
    payload: dict[str, Any] = {"schema": "voice-memo/v1", "raw_id": raw_id, "title": title}
    if audio is not None:
        payload["duration_s"] = SECONDS
        payload["file_name"] = "20260302 211407.wav"
        reference = attachments.reference(audio, "audio/wav")
        if stored:
            lb.attach(audio)
        else:
            del reference["path"]
        payload["media"] = reference
    if supersedes is not None:
        payload["supersedes"] = supersedes
    draft = {
        "at": at,
        "end": f"{at[:17]}{int(at[17:19]) + SECONDS:02d}Z",
        "tz": TZ,
        "source": MEMO,
        "kind": "voice-memo",
        "tier": tier,
        "payload": payload,
    }
    lb.append_many([draft])
    return _line(lb, MEMO, raw_id)


def _line(lb: Logbook, source: str, raw_id: str) -> dict[str, Any]:
    with lb.index() as idx:
        found = [line for line in idx.of_kind("voice-memo") if line["payload"]["raw_id"] == raw_id]
        found += [line for line in idx.of_kind("transcript") if line["payload"]["raw_id"] == raw_id]
    return next(line for line in found if line["source"] == source)


def _transcripts(lb: Logbook) -> list[dict[str, Any]]:
    with lb.index() as idx:
        return list(idx.of_kind("transcript"))


# -- the line --------------------------------------------------------------------------------------


def test_a_memo_with_its_audio_in_the_store_gets_one_transcript_line_pointing_back_at_it(lb):
    memo = _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav())
    engine = FakeEngine()
    report = transcribe.run(lb, engine)
    assert (report.written, report.found) == (1, 1)
    [line] = _transcripts(lb)
    assert (line["source"], line["kind"], line["tier"]) == (transcribe.SOURCE, "transcript", 2)
    assert (line["at"], line["end"], line["tz"]) == (memo["at"], memo["end"], TZ)
    p = line["payload"]
    assert p["schema"] == "transcript/v1" and p["provider"] == "fake-whisper"
    assert p["raw_id"] == memo["payload"]["raw_id"]  # the memo's own id: the dedupe key (ADR 0017)
    assert p["title"] == "Idea for the talk" and p["participants"] == [] and p["language"] == "nb"
    assert p["provenance"] == {"source": memo["id"], "engine": "fake-whisper", "model": "small"}
    assert p["extra"]["recording"] == memo["payload"]["raw_id"]  # RFC 0023's pointer
    assert p["extra"]["chunks"] == 1 and p["extra"]["segments"] == 1
    assert p["extra"]["duration_s"] == SECONDS
    assert "supersedes" not in p  # the memo line stands; the transcript is beside it, never over it
    content = p["content"]
    assert content["media_type"] == "text/plain" and content["path"] == f"attachments/{content['sha256']}"
    text = (lb.root / content["path"]).read_text(encoding="utf-8")
    assert text == f"{SECONDS * RATE} samples heard\n"
    assert content["bytes"] == len(text.encode("utf-8"))


def test_a_second_run_transcribes_nothing(lb):
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav())
    transcribe.run(lb, FakeEngine())
    engine = FakeEngine()
    report = transcribe.run(lb, engine)
    assert (report.written, report.found, report.already) == (0, 0, 1)
    assert engine.calls == [] and len(_transcripts(lb)) == 1


def test_memos_without_their_audio_in_the_store_are_skipped_and_counted(lb):
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z")  # no media at all
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000002", "2026-03-03T20:14:07Z", audio=_wav(), stored=False)
    engine = FakeEngine()
    report = transcribe.run(lb, engine)
    assert report.written == 0 and engine.calls == []
    assert report.counts == {"skipped_no_audio": 2}
    assert "--attachments" in transcribe.describe(report)


def test_the_transcript_tier_is_the_memo_tier_when_that_is_higher(lb):
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav(), tier=3)
    transcribe.run(lb, FakeEngine())
    assert _transcripts(lb)[0]["tier"] == 3


# -- supersede safety: only standing memos, and the transcript never hides one ---------------------


def test_a_retracted_memo_is_not_transcribed(lb):
    memo = _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav())
    lb.retract(memo["seq"], "wrong phone")
    engine = FakeEngine()
    report = transcribe.run(lb, engine)
    assert report.written == 0 and engine.calls == [] and report.counts == {"skipped_retracted": 1}


def test_a_superseded_memo_is_not_transcribed_and_the_standing_one_is(lb):
    old = _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav())
    new = _memo(
        lb,
        "7A1B2C3D-0000-4000-8000-000000000001:v2",
        "2026-03-02T20:14:07Z",
        title="Idea for the talk (trimmed)",
        audio=_wav(1.5),
        supersedes=old["id"],
    )
    report = transcribe.run(lb, FakeEngine())
    assert report.written == 1 and report.counts == {"skipped_superseded": 1}
    [line] = _transcripts(lb)
    assert line["payload"]["provenance"]["source"] == new["id"]
    assert line["payload"]["raw_id"] == new["payload"]["raw_id"]


# -- chunks, language, since ----------------------------------------------------------------------


def test_a_long_memo_is_transcribed_in_chunks_with_the_language_of_the_first_kept(lb):
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav())
    engine = FakeEngine()
    transcribe.run(lb, engine, chunk_s=0.5)
    assert engine.calls == [(8000, None), (8000, "nb"), (8000, "nb"), (8000, "nb")]
    [line] = _transcripts(lb)
    assert line["payload"]["extra"]["chunks"] == 4 and line["payload"]["extra"]["segments"] == 4
    text = (lb.root / line["payload"]["content"]["path"]).read_text(encoding="utf-8")
    assert text == "8000 samples heard\n" * 4


def test_chunks_are_fixed_windows_of_samples_with_a_last_short_one():
    assert transcribe.chunks(32_000, 16_000, 0.5) == [
        (0, 8000),
        (8000, 16_000),
        (16_000, 24_000),
        (24_000, 32_000),
    ]
    assert transcribe.chunks(20_000, 16_000, 1.0) == [(0, 16_000), (16_000, 20_000)]
    assert transcribe.chunks(0, 16_000, 1.0) == []


def test_since_takes_memos_from_that_local_day_on(lb):
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav())
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000002", "2026-03-05T06:30:00Z", audio=_wav())
    report = transcribe.run(lb, FakeEngine(), since="2026-03-05")
    assert report.written == 1
    assert _transcripts(lb)[0]["payload"]["raw_id"] == "7A1B2C3D-0000-4000-8000-000000000002"


# -- dry run, offline, the model ------------------------------------------------------------------


def test_a_dry_run_lists_what_would_be_transcribed_and_needs_no_engine(lb):
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav())
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000002", "2026-03-03T20:14:07Z")
    before = sorted(p.name for p in (lb.root / "attachments").iterdir())
    report = transcribe.run(lb, None, dry_run=True)
    assert (report.found, report.written, report.dry_run) == (1, 0, True)
    assert [m.title for m in report.memos] == ["Idea for the talk"]
    assert _transcripts(lb) == []
    assert sorted(p.name for p in (lb.root / "attachments").iterdir()) == before
    assert "dry run" in transcribe.describe(report) and "nothing written" in transcribe.describe(report)


def test_no_socket_is_opened_during_transcription(lb, monkeypatch):
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav())

    def refuse(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a socket was opened during transcription")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    engine = FakeEngine()
    report = transcribe.run(lb, engine)
    assert report.written == 1
    assert engine.offline_seen == ["1"]  # the hub is told so too, for the real engines' sake
    assert os.environ.get("HF_HUB_OFFLINE") != "1"  # and only for the run


def test_a_model_not_on_this_machine_stops_with_the_flag_that_fetches_it_unless_asked(lb):
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav())
    engine = FakeEngine(ready=False)
    with pytest.raises(transcribe.ModelMissing, match="--fetch-model"):
        transcribe.run(lb, engine)
    assert engine.fetched == 0 and _transcripts(lb) == []
    report = transcribe.run(lb, engine, fetch_model=True)
    assert engine.fetched == 1 and report.written == 1


# -- engines ---------------------------------------------------------------------------------------


def _importer(*present: str) -> Any:
    def import_module(name: str) -> Any:
        if name in present:
            return object()
        raise ImportError(name)

    return import_module


def test_apple_silicon_prefers_mlx_whisper_and_anything_else_takes_faster_whisper():
    both = _importer("mlx_whisper", "faster_whisper")
    assert transcribe.detect("small", importer=both, platform=("darwin", "arm64")).name == "mlx-whisper"
    assert transcribe.detect("small", importer=both, platform=("darwin", "x86_64")).name == "faster-whisper"
    assert transcribe.detect("small", importer=both, platform=("linux", "aarch64")).name == "faster-whisper"
    only_faster = _importer("faster_whisper")
    assert (
        transcribe.detect("small", importer=only_faster, platform=("darwin", "arm64")).name
        == "faster-whisper"
    )


def test_without_an_engine_the_message_names_the_extra():
    with pytest.raises(transcribe.EngineMissing, match=r"openlogbook\[transcribe\]"):
        transcribe.detect("small", importer=_importer(), platform=("linux", "x86_64"))


def test_a_model_name_becomes_each_engine_s_repository_and_a_repository_passes_through():
    assert transcribe.MlxWhisper.repo("small") == "mlx-community/whisper-small-mlx"
    assert transcribe.FasterWhisper.repo("small") == "Systran/faster-whisper-small"
    assert transcribe.MlxWhisper.repo("example/whisper-x") == "example/whisper-x"
    assert transcribe.FasterWhisper.repo("example/whisper-x") == "example/whisper-x"


# -- through the CLI --------------------------------------------------------------------------------


def test_the_command_prints_a_line_per_memo_and_show_lists_the_transcript(lb, monkeypatch, capsys):
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav())
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000002", "2026-03-03T20:14:07Z", title="Rehearsal", audio=_wav())
    engine = FakeEngine()
    monkeypatch.setattr(transcribe, "detect", lambda model, **_k: engine)
    cli.main(["transcribe", "voice-memos"])
    out = capsys.readouterr().out
    assert "transcribed 2 voice memos" in out
    assert "Idea for the talk" in out and "Rehearsal" in out and "nb" in out
    cli.main(["transcribe", "voice-memos"])
    assert "transcribed 0 voice memos (2 already transcribed)" in capsys.readouterr().out
    cli.main(["show", "2026-03-02"])
    out = capsys.readouterr().out
    assert "transcript" in out and "voice-memo" in out


def test_the_command_takes_the_model_and_since_and_a_dry_run_needs_no_engine(lb, monkeypatch, capsys):
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav())
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000002", "2026-03-05T06:30:00Z", audio=_wav())
    seen: list[str] = []

    def detect(model: str, **_k: Any) -> FakeEngine:
        seen.append(model)
        return FakeEngine(model)

    monkeypatch.setattr(transcribe, "detect", detect)
    cli.main(["transcribe", "voice-memos", "--dry-run"])
    out = capsys.readouterr().out
    assert "dry run" in out and "2 voice memos" in out and seen == []
    assert _transcripts(lb) == []
    cli.main(["transcribe", "voice-memos", "--since", "2026-03-05", "--model", "medium"])
    assert "transcribed 1 voice memo" in capsys.readouterr().out and seen == ["medium"]
    [line] = _transcripts(lb)
    assert line["payload"]["provenance"]["model"] == "medium"
    with pytest.raises(SystemExit) as e:
        cli.main(["transcribe", "voice-memos", "--since", "yesterday"])
    assert e.value.code == 2


def test_the_command_says_when_no_engine_is_installed_and_refuses_other_kinds(lb, monkeypatch, capsys):
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav())

    def detect(model: str, **_k: Any) -> FakeEngine:
        raise transcribe.EngineMissing("no transcription engine: install openlogbook[transcribe]")

    monkeypatch.setattr(transcribe, "detect", detect)
    with pytest.raises(SystemExit) as e:
        cli.main(["transcribe", "voice-memos"])
    assert e.value.code == 2 and "openlogbook[transcribe]" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        cli.main(["transcribe", "photos"])
    assert e.value.code == 2


def test_the_extra_is_declared():
    project = json.loads(json.dumps(_toml()))  # a plain dict either way
    assert "transcribe" in project["project"]["optional-dependencies"]


def _toml() -> dict[str, Any]:
    import tomllib

    return tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8"))


def test_the_wav_fixture_is_what_the_fake_engine_expects():
    data = _wav()
    with wave.open(io.BytesIO(data), "rb") as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (
            1,
            2,
            RATE,
            SECONDS * RATE,
        )
    assert struct.unpack("<4s", data[:4])[0] == b"RIFF"
