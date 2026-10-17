"""The voiceprint registry kept by the commands that hear (RFC 0038 §5.2): `derive transcripts` and
`derive speakers` add the voices they separate, `setup speakers --rebuild` makes it again from the
record, `setup speakers` says when and with which model it was written and for how many people,
never what is in it. The engines are fakes: a WAV of silence is "heard" by the transcription fake,
the diarizer fake answers the turns it is given, the embedder fakes answer vectors made from the
pieces they are asked for. `PyannoteEmbedding` itself runs against stand-in modules: no model is
downloaded, loaded or called, no socket opened. Synthetic Oslo persona."""

from __future__ import annotations

import io
import os
import sys
import types
import wave
from array import array
from pathlib import Path
from typing import Any

import pytest
from persona import TZ
from test_transcribe import FakeDiarizer, FakeEngine
from voiceprints_record import FakeEmbedder, as_text, seal, stored, voiced_record

from logbook import cli
from logbook.core import attachments, voiceprints
from logbook.core.store import Logbook
from logbook.labs import diarize, transcribe

RATE = 16_000
SECONDS = 20
TURNS = [(0.0, 10.0, "SPEAKER_00"), (10.0, 20.0, "SPEAKER_01")]


class WavEmbedder:
    """Reads the WAV as the engine does and answers, for a voice's pieces, a vector made of them:
    two voices, two directions. Records the switches the run had set when it loaded."""

    model = voiceprints.MODEL
    digest = "e" * 64
    dim = 4

    def __init__(self) -> None:
        self.offline: list[str | None] = []

    def load(self, path: Path) -> tuple[list[int], int]:
        self.offline.append(os.environ.get("HF_HUB_OFFLINE"))
        with wave.open(str(path), "rb") as w:
            return list(array("h", w.readframes(w.getnframes()))), w.getframerate()

    def embed(self, samples: Any, rate: int, pieces: Any) -> list[float]:
        start, end = pieces[0]
        return [start + 1.0, end, len(samples) / rate, 1.0]


def _wav(seconds: int = SECONDS, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(array("h", [0] * (seconds * RATE * channels)).tobytes())
    return buf.getvalue()


def _memo(lb: Logbook, raw_id: str, at: str, channels: list[str] | None = None) -> None:
    audio = _wav(channels=2 if channels else 1)
    lb.attach(audio)
    payload: dict[str, Any] = {
        "schema": "voice-memo/v1",
        "raw_id": raw_id,
        "title": "Middag",
        "media": attachments.reference(audio, "audio/wav"),
    }
    if channels:
        payload["extra"] = {"channels": channels}
    lb.append_many(
        [
            {
                "at": at,
                "end": f"{at[:17]}{SECONDS:02d}Z",
                "tz": TZ,
                "source": "voice-memos",
                "kind": "voice-memo",
                "tier": 2,
                "payload": payload,
            }
        ]
    )


@pytest.fixture
def sealed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return seal(Logbook.init(root, TZ), monkeypatch, tmp_path)


def _transcripts(lb: Logbook) -> list[dict[str, Any]]:
    return [line for line in Logbook(lb.root).lines() if line["kind"] == "transcript"]


# -- derive transcripts ---------------------------------------------------------------------------------


def test_derive_transcripts_adds_the_voices_it_separated_with_the_hub_offline(sealed: Logbook) -> None:
    _memo(sealed, "7A1B2C3D-0000-4000-8000-000000000038", "2026-10-03T17:40:00Z")
    embedder = WavEmbedder()
    report = transcribe.run(
        sealed, FakeEngine(), diarizer=FakeDiarizer(turns=TURNS), chunk_s=10.0, embedder=embedder
    )
    (line,) = _transcripts(sealed)
    found = voiceprints.read(Logbook(sealed.root))
    assert found is not None and sorted(found.voices) == [f"{line['id']}#S1", f"{line['id']}#S2"]
    assert found.voices[f"{line['id']}#S1"].clean_s == 10.0
    assert report.registry is not None and report.registry.heard == 2
    assert "voiceprints: 2 voices heard; 0 people, 2 voices not yet named" in transcribe.describe(report)
    assert embedder.offline == ["1"], "the embedding model hears with the hub offline"


def test_a_call_enrols_the_owner_s_microphone_without_a_line(sealed: Logbook) -> None:
    _memo(sealed, "7A1B2C3D-0000-4000-8000-000000000039", "2026-10-06T07:15:00Z", ["mic", "system"])
    diarizer = FakeDiarizer(by_channel=[[(0.0, 10.0, "SPEAKER_00")], [(10.0, 20.0, "SPEAKER_00")]])
    transcribe.run(sealed, FakeEngine(), diarizer=diarizer, chunk_s=10.0, embedder=WavEmbedder())
    (line,) = _transcripts(sealed)
    found = voiceprints.read(Logbook(sealed.root))
    owner = str(sealed.meta["owner_id"])
    assert found is not None and found.people[owner].refs == [f"{line['id']}#mic"]
    assert not any(other["kind"] == "resolution" for other in Logbook(sealed.root).lines())


def test_a_record_without_recipients_keeps_none_and_says_nothing_of_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = Logbook.init(tmp_path / "open", TZ)
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000040", "2026-10-03T17:40:00Z")
    embedder = WavEmbedder()
    report = transcribe.run(
        lb, FakeEngine(), diarizer=FakeDiarizer(turns=TURNS), chunk_s=10.0, embedder=embedder
    )
    assert not (lb.root / voiceprints.FILE).exists() and embedder.offline == []
    assert "voiceprints" not in transcribe.describe(report)


def test_derive_speakers_adds_the_voices_of_a_transcript_heard_again(sealed: Logbook) -> None:
    _memo(sealed, "7A1B2C3D-0000-4000-8000-000000000041", "2026-10-03T17:40:00Z")
    transcribe.run(sealed, FakeEngine(), diarizer=None, chunk_s=10.0)
    (old,) = _transcripts(sealed)
    again = transcribe.unseparated(Logbook(sealed.root))
    report = transcribe.rehear(
        Logbook(sealed.root),
        again,
        lambda model: FakeEngine(model),
        FakeDiarizer(turns=TURNS),
        chunk_s=10.0,
        embedder=WavEmbedder(),
    )
    new = next(line for line in _transcripts(sealed) if line["id"] != old["id"])
    found = voiceprints.read(Logbook(sealed.root))
    assert found is not None and sorted(found.voices) == [f"{new['id']}#S1", f"{new['id']}#S2"]
    assert "voiceprints: 2 voices heard" in transcribe.describe_again(report)


# -- setup speakers ----------------------------------------------------------------------------------------


@pytest.fixture
def engine_here(monkeypatch: pytest.MonkeyPatch) -> FakeEmbedder:
    """The `speakers` extra and every model on this machine, as far as the command can tell; the
    embedding model a fake."""
    monkeypatch.setitem(sys.modules, "pyannote.audio", types.ModuleType("pyannote.audio"))
    monkeypatch.setattr(
        diarize, "status", lambda *_a, **_k: diarize.Status("4.0.7", dict.fromkeys(diarize.MODELS, True))
    )
    embedder = FakeEmbedder()
    monkeypatch.setattr(diarize, "embedder", lambda *_a, **_k: embedder)
    return embedder


def _setup(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    try:
        cli.main(["setup", "speakers", *args])
        code = 0
    except SystemExit as e:
        code = int(e.code or 0)
    out, err = capsys.readouterr()
    return code, out, err


def test_rebuild_makes_the_registry_and_setup_says_what_it_holds_never_its_numbers(
    sealed: Logbook, engine_here: FakeEmbedder, capsys: pytest.CaptureFixture[str], no_network: list[str]
) -> None:
    voiced_record(sealed)
    code, out, _err = _setup(capsys)
    assert code == 0 and "registry   none yet: logbook setup speakers --rebuild" in out
    code, out, _err = _setup(capsys, "--rebuild")
    assert code == 0 and (sealed.root / voiceprints.FILE).exists()
    assert "voiceprints: 4 voices heard; 1 person, you among them, 3 voices not yet named" in out
    row = next(line for line in out.splitlines() if line.startswith("registry"))
    assert f"with {voiceprints.MODEL}, for 1 person, you among them; 3 voices not yet named" in row
    assert not any(text in out for who in ("ines", "kari", "ola") for text in as_text(stored(who)))
    assert no_network == []


def test_setup_says_a_machine_without_the_identity_writes_no_registry(
    sealed: Logbook,
    engine_here: FakeEmbedder,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    voiced_record(sealed)
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(tmp_path / "keys" / "absent.txt"))
    code, out, _err = _setup(capsys)
    assert code == 0 and f"registry   none, and none is written here: {voiceprints.NEEDS_IDENTITY}" in out
    code, out, _err = _setup(capsys, "--rebuild")
    assert code == 0 and f"voiceprints: not written: {voiceprints.NEEDS_IDENTITY}" in out
    assert not (sealed.root / voiceprints.FILE).exists()


def test_setup_says_when_the_registry_was_made_with_another_model(
    sealed: Logbook, engine_here: FakeEmbedder, capsys: pytest.CaptureFixture[str]
) -> None:
    voiced_record(sealed)
    voiceprints.update(Logbook(sealed.root), FakeEmbedder(model="example/older-embedding"))
    _code, out, _err = _setup(capsys)
    assert f"not the configured model, {voiceprints.MODEL}: logbook setup speakers --rebuild" in out


def test_rebuild_refuses_a_record_without_recipients_and_a_machine_without_the_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    engine_here: FakeEmbedder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "open"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    voiced_record(Logbook.init(root, TZ))
    code, _out, err = _setup(capsys, "--rebuild")
    assert code == 2 and "names no recipients, so it keeps no voiceprint registry on disk" in err
    assert not (root / voiceprints.FILE).exists()
    _code, out, _err = _setup(capsys)
    assert "registry   none on disk: this record names no recipients" in out
    sealed = seal(Logbook(root), monkeypatch, tmp_path)
    monkeypatch.setattr(
        diarize, "status", lambda *_a, **_k: diarize.Status("4.0.7", dict.fromkeys(diarize.MODELS, False))
    )
    code, _out, err = _setup(capsys, "--rebuild")
    assert code == 2 and "the speaker models are not on this machine" in err
    assert not (sealed.root / voiceprints.FILE).exists()


# -- the embedding model -----------------------------------------------------------------------------------


class _Tensor:
    def __init__(self, data: Any) -> None:
        self.data = data

    def numpy(self) -> Any:
        return self.data


class _Array:
    """What the embedder asks of numpy: an array of one row, made of a chunk of samples."""

    def __init__(self, values: Any) -> None:
        self.shape = (1, len(values))

    def reshape(self, *_shape: int) -> _Array:
        return self


def _stand_ins(tmp_path: Path, calls: list[str], *, cached: bool = True, loads: bool = True) -> Any:
    """Stand-ins for numpy, torch, the hub and pyannote.audio: the hub's cache a folder of two files,
    the model an `Inference` that answers a vector made of the chunk's length."""
    numpy = types.ModuleType("numpy")
    numpy.float32 = "float32"  # type: ignore[attr-defined]
    numpy.asarray = lambda values, dtype=None: _Array(values)  # type: ignore[attr-defined]
    folder = tmp_path / "cache" / "snapshot"
    folder.mkdir(parents=True)
    (folder / "pytorch_model.bin").write_bytes(b"not weights")
    (folder / "config.yaml").write_bytes(b"dimension: 4\n")

    hub = types.ModuleType("huggingface_hub")

    def snapshot_download(repo: str, **options: Any) -> str:
        calls.append(f"hub {repo} {options}")
        if not cached:
            raise FileNotFoundError(repo)
        return str(folder)

    hub.snapshot_download = snapshot_download  # type: ignore[attr-defined]
    torch = types.ModuleType("torch")
    torch.from_numpy = lambda array: array  # type: ignore[attr-defined]
    audio = types.ModuleType("pyannote.audio")

    class Audio:
        def __init__(self, sample_rate: int, mono: Any) -> None:
            calls.append(f"audio {sample_rate} {mono} {os.environ.get('HF_HUB_OFFLINE')}")

        def __call__(self, path: str) -> tuple[list[_Tensor], int]:
            return [_Tensor([1.0] * 10 * RATE)], RATE

    class Model:
        @staticmethod
        def from_pretrained(repo: str) -> Any:
            calls.append(f"model {repo} {os.environ.get('HF_HUB_OFFLINE')}")
            if not loads:
                raise OSError(repo)
            return object()

    class Inference:
        def __init__(self, model: Any, window: str) -> None:
            calls.append(f"inference {window}")

        def __call__(self, given: dict[str, Any]) -> Any:
            n = given["waveform"].shape[1]
            return [[float(n), 0.0, 0.0, 0.0]] if n < 3 * RATE else [0.0, float(n), 0.0, 0.0]

    audio.Audio = Audio  # type: ignore[attr-defined]
    audio.Model = Model  # type: ignore[attr-defined]
    audio.Inference = Inference  # type: ignore[attr-defined]
    modules = {"numpy": numpy, "torch": torch, diarize.HUB: hub, diarize.MODULE: audio}

    def import_module(name: str) -> Any:
        if name in modules:
            return modules[name]
        raise ImportError(name)

    return import_module


def test_the_embedding_model_hears_each_clean_piece_whole_offline(tmp_path: Path) -> None:
    calls: list[str] = []
    model = diarize.PyannoteEmbedding(_stand_ins(tmp_path, calls))
    assert calls == [], "nothing is loaded until it is asked"
    samples, rate = model.load(tmp_path / "memo.wav")
    vector = model.embed(samples, rate, [(0.0, 2.0), (2.0, 6.0)])
    # each piece a unit vector, weighted by its seconds: 2 s along the first axis, 4 s along the second
    assert vector == [2.0, 4.0, 0.0, 0.0]
    assert calls == [
        f"audio {RATE} downmix 1",
        f"model {voiceprints.MODEL} 1",
        "inference whole",
    ]
    assert model.dim == diarize.EMBEDDING_DIM
    assert (
        len(model.digest) == 64
        and model.digest == diarize.PyannoteEmbedding(_stand_ins(tmp_path / "b", [])).digest
    )
    assert diarize.EMBEDDING == voiceprints.MODEL


def test_the_embedding_model_not_whole_here_is_one_sentence_naming_the_fetch(tmp_path: Path) -> None:
    with pytest.raises(diarize.ModelsMissing, match="setup speakers --fetch-model"):
        _ = diarize.PyannoteEmbedding(_stand_ins(tmp_path / "a", [], cached=False)).digest
    model = diarize.PyannoteEmbedding(_stand_ins(tmp_path / "b", [], loads=False))
    with pytest.raises(diarize.ModelsMissing, match="setup speakers --fetch-model"):
        model.embed([0.0] * RATE * 4, RATE, [(0.0, 3.0)])
