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
from logbook.core import attachments, speakers
from logbook.core.store import Logbook
from logbook.labs import diarize, transcribe

TZ = "Europe/Oslo"
RATE = 16_000
SECONDS = 2
MEMO = "voice-memos"


def _wav(seconds: float = SECONDS, tone_hz: float = 440.0, channels: int = 1) -> bytes:
    """A 16-bit WAV of a sine tone, the same in every channel: nobody's voice."""
    n = int(seconds * RATE)
    tone = [int(12_000 * math.sin(2 * math.pi * tone_hz * i / RATE)) for i in range(n)]
    frames = array("h", (sample for sample in tone for _channel in range(channels)))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
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
        """Mono, as both real engines decode: the channels of a stereo file averaged."""
        with wave.open(str(path), "rb") as w:
            frames = list(array("h", w.readframes(w.getnframes())))
            n = w.getnchannels()
            return [sum(frames[i : i + n]) // n for i in range(0, len(frames), n)], w.getframerate()

    def transcribe(self, samples: Any, rate: int, language: str | None) -> transcribe.Result:
        self.calls.append((len(samples), language))
        self.offline_seen.append(os.environ.get("HF_HUB_OFFLINE"))
        seconds = len(samples) / rate
        return transcribe.Result(
            segments=[transcribe.Segment(0.0, seconds, f"{len(samples)} samples heard")],
            language=language or "nb",
        )


@pytest.fixture(autouse=True)
def _no_diarizer_unless_a_test_gives_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI asks `diarize.detect`; a machine with the extra and the models must not diarize here."""
    monkeypatch.setattr(diarize, "detect", lambda *_a, **_k: None)


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
    channels: Any = None,
) -> dict[str, Any]:
    """A voice-memo/v1 draft, appended; with `audio` the bytes are referenced and, when `stored`, put
    in the §1.1 store (as `logbook add voice-memos --attachments` does). `channels` is what a source
    that keeps a call's sides apart says of the file's channels (`extra.channels`)."""
    payload: dict[str, Any] = {"schema": "voice-memo/v1", "raw_id": raw_id, "title": title}
    if channels is not None:
        payload["extra"] = {"channels": channels}
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
    cli.main(["derive", "transcripts", "voice-memos"])
    out = capsys.readouterr().out
    assert "transcribed 2 voice memos" in out
    assert "Idea for the talk" in out and "Rehearsal" in out and "nb" in out
    cli.main(["derive", "transcripts", "voice-memos"])
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
    cli.main(["derive", "transcripts", "voice-memos", "--dry-run"])
    out = capsys.readouterr().out
    assert "dry run" in out and "2 voice memos" in out and seen == []
    assert _transcripts(lb) == []
    cli.main(["derive", "transcripts", "voice-memos", "--since", "2026-03-05", "--model", "medium"])
    assert "transcribed 1 voice memo" in capsys.readouterr().out and seen == ["medium"]
    [line] = _transcripts(lb)
    assert line["payload"]["provenance"]["model"] == "medium"
    with pytest.raises(SystemExit) as e:
        cli.main(["derive", "transcripts", "voice-memos", "--since", "yesterday"])
    assert e.value.code == 2


def test_the_command_says_when_no_engine_is_installed_and_refuses_other_kinds(lb, monkeypatch, capsys):
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav())

    def detect(model: str, **_k: Any) -> FakeEngine:
        raise transcribe.EngineMissing("no transcription engine: install openlogbook[transcribe]")

    monkeypatch.setattr(transcribe, "detect", detect)
    with pytest.raises(SystemExit) as e:
        cli.main(["derive", "transcripts", "voice-memos"])
    assert e.value.code == 2 and "openlogbook[transcribe]" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        cli.main(["derive", "transcripts", "photos"])
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


# -- voices: RFC 0038 §2 --------------------------------------------------------------------------

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[1] / "schema" / "transcript-v1.schema.json").read_text(encoding="utf-8")
)


class FakeDiarizer:
    """Answers the turns it was given, the pipeline's own ids and all: `turns` for one channel, or
    `by_channel`, one list per channel of the file, for a recording whose source keeps them apart.
    Records what it was asked and the switches the run had set."""

    name = "fake-pyannote"
    model = "example/speaker-diarization"

    def __init__(
        self,
        turns: list[tuple[float, float, str]] | None = None,
        by_channel: list[list[tuple[float, float, str]]] | None = None,
    ) -> None:
        self.turns = turns if turns is not None else [(0.0, 1.2, "SPEAKER_01"), (1.0, 2.0, "SPEAKER_00")]
        self.by_channel = by_channel
        self.calls: list[tuple[int, int, int | None]] = []
        self.split: list[str] = []
        self.env_seen: list[tuple[str | None, str | None]] = []

    def diarize(self, samples: Any, rate: int, speakers: int | None = None) -> list[tuple[float, float, str]]:
        self.calls.append((len(samples), rate, speakers))
        self.env_seen.append((os.environ.get("HF_HUB_OFFLINE"), os.environ.get("PYANNOTE_METRICS_ENABLED")))
        if self.by_channel is not None:
            return list(self.by_channel[len(self.calls) - 1])
        return list(self.turns)

    def channels(self, path: Path) -> tuple[list[list[int]], int]:
        self.split.append(path.name)
        with wave.open(str(path), "rb") as w:
            frames = list(array("h", w.readframes(w.getnframes())))
            n = w.getnchannels()
            return [frames[c::n] for c in range(n)], w.getframerate()


class WordEngine(FakeEngine):
    """One segment over the whole window, its one word late in it, as an engine with word times."""

    def transcribe(self, samples: Any, rate: int, language: str | None) -> transcribe.Result:
        seconds = len(samples) / rate
        word = (seconds * 0.6, seconds * 0.9)
        return transcribe.Result([transcribe.Segment(0.0, seconds, "Hei", words=(word,))], language or "nb")


def _spans(lb: Logbook, line: dict[str, Any]) -> dict[str, Any]:
    reference = line["payload"]["diarization"]["spans"]
    data = lb.attachment_bytes(reference["sha256"])
    assert attachments.reference(data, "application/json") == reference
    return json.loads(data)


def _valid(payload: dict[str, Any]) -> None:
    from jsonschema import Draft202012Validator

    assert [e.message for e in Draft202012Validator(SCHEMA).iter_errors(payload)] == []


def test_with_the_diarizer_here_the_same_run_separates_the_voices_and_labels_them_by_first_speech(lb):
    memo = _memo(
        lb, "7A1B2C3D-0000-4000-8000-000000000038", "2026-10-03T17:40:12Z", title="Middag", audio=_wav()
    )
    diarizer = FakeDiarizer()
    report = transcribe.run(lb, FakeEngine(), diarizer=diarizer, chunk_s=1.0)
    assert report.written == 1 and report.separated == 1
    [line] = _transcripts(lb)
    p = line["payload"]
    assert diarizer.calls == [(SECONDS * RATE, RATE, None)]  # the samples the engine decoded, heard once
    assert p["speakers"] == [
        {"label": "S1", "seconds": 1.2, "turns": 1},  # SPEAKER_01 spoke first
        {"label": "S2", "seconds": 1.0, "turns": 1},
    ]
    content = p["content"]
    assert p["diarization"] == {
        "engine": "fake-pyannote",
        "model": "example/speaker-diarization",
        "audio": memo["payload"]["media"]["sha256"],
        "channels": 1,
        "overlap_s": 0.2,
        "spans": p["diarization"]["spans"],
    }
    spans = _spans(lb, line)
    assert spans == {
        "format": "speaker-spans/1",
        "content": content["sha256"],
        "segments": [{"from": 0.0, "to": 1.0, "speaker": "S1"}, {"from": 1.0, "to": 2.0, "speaker": "S2"}],
        "turns": [{"from": 0.0, "to": 1.2, "speaker": "S1"}, {"from": 1.0, "to": 2.0, "speaker": "S2"}],
    }
    text = lb.attachment_bytes(content["sha256"])
    assert speakers.segment_count(text, content["media_type"]) == len(spans["segments"])
    _valid(p)
    assert "speakers: not separated" not in transcribe.describe(report)


def test_the_text_is_the_same_whether_or_not_the_voices_were_separated(lb, tmp_path, monkeypatch):
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav())
    transcribe.run(lb, FakeEngine(), diarizer=FakeDiarizer(), chunk_s=1.0)
    other = Logbook.init(tmp_path / "other", TZ)
    _memo(other, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav())
    transcribe.run(other, FakeEngine(), chunk_s=1.0)
    [with_voices], [without] = _transcripts(lb), _transcripts(other)
    assert with_voices["payload"]["content"] == without["payload"]["content"]
    assert {k: v for k, v in with_voices["payload"].items() if k not in ("speakers", "diarization")} == {
        k: v for k, v in without["payload"].items() if k != "provenance"
    } | {"provenance": with_voices["payload"]["provenance"]}


def test_without_the_model_the_line_is_today_s_and_the_run_says_so_once_at_the_end(lb):
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav())
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000002", "2026-03-03T20:14:07Z", audio=_wav())
    report = transcribe.run(lb, FakeEngine(), diarizer=None)
    for line in _transcripts(lb):
        assert "speakers" not in line["payload"] and "diarization" not in line["payload"]
        assert set(line["payload"]) == {
            "schema",
            "provider",
            "raw_id",
            "title",
            "participants",
            "language",
            "content",
            "extra",
            "provenance",
        }
    text = transcribe.describe(report)
    assert text.count("speakers: not separated (logbook setup speakers --fetch-model)") == 1
    assert text.splitlines()[-1] == "speakers: not separated (logbook setup speakers --fetch-model)"


def test_told_not_to_the_run_neither_separates_nor_says_anything_about_it(lb):
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav())
    diarizer = FakeDiarizer()
    report = transcribe.run(lb, FakeEngine(), diarizer=diarizer, separate=False)
    assert diarizer.calls == [] and "speakers" not in _transcripts(lb)[0]["payload"]
    assert "speakers" not in transcribe.describe(report)


def test_two_channels_the_source_keeps_apart_are_heard_one_at_a_time_and_the_mic_is_from_me(lb):
    memo = _memo(
        lb,
        "7A1B2C3D-0000-4000-8000-000000000039",
        "2026-10-06T07:15:03Z",
        title="Samtale",
        audio=_wav(channels=2),
        channels=["mic", "system"],
    )
    diarizer = FakeDiarizer(by_channel=[[(0.0, 1.0, "SPEAKER_00")], [(0.9, 2.0, "SPEAKER_00")]])
    transcribe.run(lb, FakeEngine(), diarizer=diarizer, chunk_s=1.0)
    assert diarizer.split == [memo["payload"]["media"]["sha256"]] and len(diarizer.calls) == 2
    [line] = _transcripts(lb)
    p = line["payload"]
    assert p["speakers"] == [
        {"label": "mic", "seconds": 1.0, "turns": 1, "channel": "mic", "from_me": True},
        {"label": "system", "seconds": 1.1, "turns": 1, "channel": "system"},
    ]
    assert p["diarization"]["channels"] == 2 and p["diarization"]["overlap_s"] == 0.1
    _valid(p)


def test_a_channel_holding_several_voices_numbers_them_and_none_of_them_is_from_me(lb):
    _memo(
        lb,
        "7A1B2C3D-0000-4000-8000-000000000040",
        "2026-10-06T08:00:00Z",
        audio=_wav(channels=2),
        channels=["system", "mic"],
    )  # the source's order: the mic is the second channel here
    diarizer = FakeDiarizer(
        by_channel=[[(1.0, 2.0, "SPEAKER_00")], [(0.0, 0.6, "SPEAKER_03"), (0.6, 1.0, "SPEAKER_01")]]
    )
    transcribe.run(lb, FakeEngine(), diarizer=diarizer, chunk_s=1.0)
    p = _transcripts(lb)[0]["payload"]
    assert [(s["label"], s.get("channel"), s.get("from_me")) for s in p["speakers"]] == [
        ("mic.1", "mic", None),
        ("mic.2", "mic", None),
        ("system", "system", None),
    ]
    assert [s["turns"] for s in p["speakers"]] == [1, 0, 1]
    _valid(p)


def test_a_file_that_does_not_hold_the_channels_its_source_named_is_heard_as_a_room(lb):
    _memo(
        lb,
        "7A1B2C3D-0000-4000-8000-000000000041",
        "2026-10-06T09:00:00Z",
        audio=_wav(),
        channels=["mic", "system"],
    )
    diarizer = FakeDiarizer()
    transcribe.run(lb, FakeEngine(), diarizer=diarizer, chunk_s=1.0)
    p = _transcripts(lb)[0]["payload"]
    assert [s["label"] for s in p["speakers"]] == ["S1", "S2"]
    assert p["diarization"]["channels"] == 1 and not any("from_me" in s for s in p["speakers"])


@pytest.mark.parametrize("said", [None, ["mic"], ["mic", "mic"], ["left", "right"], "mic,system", [1, 2]])
def test_a_stereo_memo_is_a_room_unless_its_source_names_a_mic_and_a_system_channel(lb, said):
    """An iPhone's stereo memo is two microphones in one room, not a call: without a statement the
    run can read, the recording is one room and no voice is `from_me`."""
    _memo(
        lb,
        "7A1B2C3D-0000-4000-8000-000000000042",
        "2026-10-06T10:00:00Z",
        audio=_wav(channels=2),
        channels=said,
    )
    diarizer = FakeDiarizer()
    transcribe.run(lb, FakeEngine(), diarizer=diarizer, chunk_s=1.0)
    assert diarizer.split == []
    p = _transcripts(lb)[0]["payload"]
    assert [s["label"] for s in p["speakers"]] == ["S1", "S2"] and p["diarization"]["channels"] == 1


def test_word_times_decide_whose_a_segment_is_when_the_engine_gives_them(lb):
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav())
    # the segment is 0 to 2 s; S1 speaks 0 to 1.1 s, S2 1.1 to 2 s; the one word, 1.2 to 1.8 s, is S2's
    diarizer = FakeDiarizer(turns=[(0.0, 1.1, "A"), (1.1, 2.0, "B")])
    transcribe.run(lb, WordEngine(), diarizer=diarizer)
    p = _transcripts(lb)[0]["payload"]
    assert [(s["label"], s["turns"]) for s in p["speakers"]] == [("S1", 0), ("S2", 1)]


def test_a_recording_in_which_no_voice_is_found_is_transcribed_without_labels(lb):
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav())
    report = transcribe.run(lb, FakeEngine(), diarizer=FakeDiarizer(turns=[]))
    assert report.written == 1 and report.separated == 0 and report.voiceless == 1
    assert "speakers" not in _transcripts(lb)[0]["payload"]
    assert "no voice found" in transcribe.describe(report)


def test_no_socket_is_opened_during_a_run_that_separates_voices(lb, monkeypatch):
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav())

    def refuse(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a socket was opened during transcription")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.delenv("PYANNOTE_METRICS_ENABLED", raising=False)
    diarizer = FakeDiarizer()
    report = transcribe.run(lb, FakeEngine(), diarizer=diarizer)
    assert report.written == 1 and report.separated == 1
    assert diarizer.env_seen == [("1", "0")]  # the hub offline, pyannote's usage reporting off
    assert os.environ.get("PYANNOTE_METRICS_ENABLED") is None  # and only for the run


def test_a_memo_whose_audio_is_gone_is_neither_heard_nor_separated(lb):
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z")
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000002", "2026-03-03T20:14:07Z", audio=_wav(), stored=False)
    diarizer = FakeDiarizer()
    report = transcribe.run(lb, FakeEngine(), diarizer=diarizer)
    assert report.written == 0 and diarizer.calls == [] and report.counts == {"skipped_no_audio": 2}


def test_the_command_separates_with_the_diarizer_here_and_asks_the_engine_for_word_times(
    lb, monkeypatch, capsys
):
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav())
    asked: list[dict[str, Any]] = []

    def detect(model: str, **kwargs: Any) -> FakeEngine:
        asked.append(kwargs)
        return FakeEngine(model)

    monkeypatch.setattr(transcribe, "detect", detect)
    monkeypatch.setattr(diarize, "detect", lambda *_a, **_k: FakeDiarizer())
    cli.main(["derive", "transcripts", "voice-memos"])
    out = capsys.readouterr().out
    assert asked == [{"words": True}]
    assert "voices separated in 1 voice memo" in out and "not separated" not in out
    assert [s["label"] for s in _transcripts(lb)[0]["payload"]["speakers"]] == ["S1", "S2"]


def test_the_command_without_the_model_transcribes_and_names_the_command_that_fetches_it(
    lb, monkeypatch, capsys
):
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav())
    asked: list[dict[str, Any]] = []

    def detect(model: str, **kwargs: Any) -> FakeEngine:
        asked.append(kwargs)
        return FakeEngine(model)

    monkeypatch.setattr(transcribe, "detect", detect)
    cli.main(["derive", "transcripts", "voice-memos"])
    out = capsys.readouterr().out
    assert asked == [{"words": False}]
    assert out.count("speakers: not separated (logbook setup speakers --fetch-model)") == 1
    assert "transcribed 1 voice memo" in out and "speakers" not in _transcripts(lb)[0]["payload"]


def test_the_command_with_no_speakers_asks_for_no_diarizer_and_says_nothing_of_voices(
    lb, monkeypatch, capsys
):
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav())
    monkeypatch.setattr(transcribe, "detect", lambda model, **_k: FakeEngine(model))

    def detect(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("--no-speakers asked for a diarizer")

    monkeypatch.setattr(diarize, "detect", detect)
    cli.main(["derive", "transcripts", "voice-memos", "--no-speakers"])
    out = capsys.readouterr().out
    assert "transcribed 1 voice memo" in out and "speakers" not in out and "voices" not in out
    assert "speakers" not in _transcripts(lb)[0]["payload"]


def test_the_engines_ask_for_word_times_only_when_told_and_read_them_back():
    class Mlx:
        def __init__(self) -> None:
            self.options: list[dict[str, Any]] = []

        def transcribe(self, samples: Any, **options: Any) -> dict[str, Any]:
            self.options.append(options)
            words = [{"word": " Hei", "start": 0.1, "end": 0.4}] if options.get("word_timestamps") else None
            return {
                "segments": [{"start": 0.0, "end": 1.0, "text": " Hei", "words": words}],
                "language": "nb",
            }

    mlx = Mlx()
    plain = transcribe.MlxWhisper("small", mlx, _importer())
    assert plain.transcribe([0.0], RATE, None).segments[0].words == ()
    worded = transcribe.MlxWhisper("small", mlx, _importer(), words=True)
    assert worded.transcribe([0.0], RATE, "nb").segments[0].words == ((0.1, 0.4),)
    assert ["word_timestamps" in o for o in mlx.options] == [False, True]

    class Word:
        start, end = 0.2, 0.5

    class Found:
        start, end, text, words = 0.0, 1.0, " Ja", [Word()]

    class Model:
        def __init__(self) -> None:
            self.asked: list[bool] = []

        def transcribe(self, samples: Any, language: str | None, word_timestamps: bool) -> Any:
            self.asked.append(word_timestamps)
            return iter([Found()]), type("Info", (), {"language": "nb"})()

    class Fw:
        model = Model()

        def WhisperModel(self, *_a: Any, **_k: Any) -> Model:
            return self.model

    fw = Fw()
    found = transcribe.FasterWhisper("small", fw, _importer(), words=True).transcribe([0.0], RATE, None)
    assert found.segments[0].words == ((0.2, 0.5),) and fw.model.asked == [True]
    transcribe.FasterWhisper("small", fw, _importer()).transcribe([0.0], RATE, None)
    assert fw.model.asked == [True, False]


def test_a_segment_holding_several_lines_is_a_span_per_line_so_the_spans_number_the_content(lb):
    class Lines(FakeEngine):
        def transcribe(self, samples: Any, rate: int, language: str | None) -> transcribe.Result:
            seconds = len(samples) / rate
            return transcribe.Result([transcribe.Segment(0.0, seconds, "Hei.\n\nHar du sett vannet?")], "nb")

    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav())
    transcribe.run(lb, Lines(), diarizer=FakeDiarizer(turns=[(0.0, 2.0, "A")]))
    [line] = _transcripts(lb)
    text = lb.attachment_bytes(line["payload"]["content"]["sha256"])
    spans = _spans(lb, line)
    assert speakers.segment_count(text, "text/plain") == len(spans["segments"]) == 2
    assert line["payload"]["speakers"] == [{"label": "S1", "seconds": 2.0, "turns": 2}]
