"""`logbook setup speakers [--fetch-model]` (RFC 0038 §2.9): what is on this machine, with no socket;
and the one network event, the diarization pipeline and the models it reads fetched into the Hugging
Face cache with the owner's token read from `HF_TOKEN` for those requests only, never written, never
printed. No other command fetches a speaker model. The hub here is a fake module put where
`import huggingface_hub` finds it; no model is downloaded, no socket opened."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.core.store import Logbook
from logbook.labs import diarize, transcribe

TOKEN = "hf_synthetic0000000000000000000000"  # not a token: the shape of one
TZ = "Europe/Oslo"


class GatedRepoError(Exception):
    """As the hub names its refusal of a gated repository whose conditions are not accepted."""


class FakeHub:
    """`snapshot_download` as the hub has it: cached repos answer with `local_files_only`, others
    are fetched (recorded with the token they were asked with) unless they are gated."""

    def __init__(self, cached: set[str] | None = None, gated: set[str] | None = None) -> None:
        self.cached = set(cached or ())
        self.gated = set(gated or ())
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def snapshot_download(self, repo: str, **options: Any) -> str:
        self.calls.append((repo, options))
        if options.get("local_files_only"):
            if repo not in self.cached:
                raise FileNotFoundError(repo)
            return f"/cache/{repo}"
        if repo in self.gated:
            raise GatedRepoError(f"Access to model {repo} is restricted.")
        self.cached.add(repo)
        return f"/cache/{repo}"

    def module(self) -> types.ModuleType:
        module = types.ModuleType("huggingface_hub")
        module.snapshot_download = self.snapshot_download  # type: ignore[attr-defined]
        return module


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook.init(root, TZ)


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch) -> FakeHub:
    fake = FakeHub()
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake.module())
    return fake


@pytest.fixture
def pyannote(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """An installed pyannote.audio, as far as `import pyannote.audio` can tell."""
    module = types.ModuleType("pyannote.audio")
    module.__version__ = "4.0.7"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pyannote.audio", module)
    return module


def _importer(**modules: Any) -> Any:
    def import_module(name: str) -> Any:
        if name in modules:
            return modules[name]
        raise ImportError(name)

    return import_module


# -- what is here ---------------------------------------------------------------------------------


def test_without_the_extra_it_says_what_to_install_and_that_nothing_separates_voices(lb, monkeypatch, capsys):
    monkeypatch.setattr(
        diarize, "status", lambda *_a, **_k: diarize.Status(None, dict.fromkeys(diarize.MODELS, False))
    )
    cli.main(["setup", "speakers"])
    out = capsys.readouterr().out
    assert "not installed" in out and "openlogbook[transcribe]" in out
    assert "logbook setup speakers --fetch-model" in out


def test_it_names_each_model_here_or_not_and_what_the_record_holds(lb, hub, pyannote, capsys):
    hub.cached = {diarize.MODEL, diarize.SEGMENTATION}
    lb.append_many(
        [
            {
                "at": "2026-10-06T07:15:03Z",
                "end": "2026-10-06T07:22:28Z",
                "tz": TZ,
                "source": "transcription",
                "kind": "transcript",
                "tier": 2,
                "payload": {
                    "schema": "transcript/v1",
                    "provider": "mlx-whisper",
                    "raw_id": "7A1B2C3D-0000-4000-8000-000000000039",
                    "speakers": [
                        {"label": "mic", "seconds": 201.7, "turns": 38, "channel": "mic", "from_me": True},
                        {"label": "system", "seconds": 188.3, "turns": 35, "channel": "system"},
                    ],
                    "diarization": {"engine": "pyannote", "channels": 2},
                },
            }
        ]
    )
    cli.main(["setup", "speakers"])
    out = capsys.readouterr().out
    assert "pyannote.audio 4.0.7" in out
    assert f"{diarize.MODEL}  here" in out and f"{diarize.SEGMENTATION}  here" in out
    assert f"{diarize.EMBEDDING}  not here" in out
    assert "voices separated in 1 transcript" in out
    assert "your own microphone: 3 min" in out
    assert all(options == {"local_files_only": True} for _repo, options in hub.calls)


def test_status_asks_the_cache_only_and_with_the_hub_offline():
    hub = FakeHub(cached=set(diarize.MODELS))
    seen: list[str | None] = []

    def snapshot(repo: str, **options: Any) -> str:
        import os

        seen.append(os.environ.get("HF_HUB_OFFLINE"))
        return hub.snapshot_download(repo, **options)

    module = types.SimpleNamespace(snapshot_download=snapshot)
    found = diarize.status(
        _importer(**{"pyannote.audio": types.SimpleNamespace(__version__="3.3.2"), "huggingface_hub": module})
    )
    assert found.ready and found.version == "3.3.2" and seen == ["1", "1", "1"]
    assert [options for _repo, options in hub.calls] == [{"local_files_only": True}] * 3


def test_detect_is_none_until_every_model_the_pipeline_reads_is_here():
    hub = FakeHub(cached={diarize.MODEL, diarize.SEGMENTATION})
    modules = {"pyannote.audio": types.SimpleNamespace(), "huggingface_hub": hub.module()}
    assert diarize.detect(_importer(**modules)) is None
    hub.cached.add(diarize.EMBEDDING)
    assert isinstance(diarize.detect(_importer(**modules)), diarize.Pyannote)
    assert all(options == {"local_files_only": True} for _repo, options in hub.calls)
    assert diarize.detect(_importer(huggingface_hub=hub.module())) is None  # no engine installed


# -- the one download -----------------------------------------------------------------------------


def test_fetch_model_downloads_the_pipeline_and_the_models_it_reads_with_the_token_never_shown(
    lb, hub, pyannote, monkeypatch, capsys, tmp_path
):
    monkeypatch.setenv("HF_TOKEN", TOKEN)
    cli.main(["setup", "speakers", "--fetch-model"])
    out, err = capsys.readouterr()
    fetched = [(repo, options) for repo, options in hub.calls if not options.get("local_files_only")]
    assert fetched == [(repo, {"token": TOKEN}) for repo in diarize.MODELS]
    assert TOKEN not in out and TOKEN not in err
    assert all(f"{repo}  here" in out for repo in diarize.MODELS)
    for file in tmp_path.rglob("*"):  # the record, the home directory: the token is in no file
        if file.is_file():
            assert TOKEN.encode() not in file.read_bytes(), file


def test_without_a_token_the_request_carries_none_of_its_own(lb, hub, pyannote, monkeypatch, capsys):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    cli.main(["setup", "speakers", "--fetch-model"])
    fetched = [options for _repo, options in hub.calls if not options.get("local_files_only")]
    assert fetched == [{"token": None}] * len(diarize.MODELS)


def test_a_refusal_names_the_page_to_accept_the_conditions_on_and_never_the_token(
    lb, hub, pyannote, monkeypatch, capsys
):
    hub.gated = {diarize.SEGMENTATION}
    monkeypatch.setenv("HF_TOKEN", TOKEN)
    with pytest.raises(SystemExit) as e:
        cli.main(["setup", "speakers", "--fetch-model"])
    assert e.value.code == 2
    out, err = capsys.readouterr()
    assert f"https://huggingface.co/{diarize.SEGMENTATION}" in err and "HF_TOKEN" in err
    assert TOKEN not in out and TOKEN not in err
    assert "restricted" not in err  # the hub's own words are not passed on


def test_a_refusal_is_known_by_the_hub_s_error_or_by_a_401_or_403():
    class HfHubHTTPError(Exception):
        def __init__(self, status: int) -> None:
            super().__init__("refused")
            self.response = types.SimpleNamespace(status_code=status)

    for error, refused in (
        (GatedRepoError("x"), True),
        (HfHubHTTPError(401), True),
        (HfHubHTTPError(403), True),
        (HfHubHTTPError(500), False),
        (OSError("unreachable"), False),
    ):

        def snapshot(repo: str, error: Exception = error, **_options: Any) -> str:
            raise error

        hub = types.SimpleNamespace(snapshot_download=snapshot)
        expected: type[Exception] = diarize.Refused if refused else OSError
        with pytest.raises(expected):
            diarize.fetch({"HF_TOKEN": TOKEN}, _importer(huggingface_hub=hub))


def test_fetch_model_without_the_extra_names_it(lb, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)  # an import that fails
    with pytest.raises(SystemExit) as e:
        cli.main(["setup", "speakers", "--fetch-model"])
    assert e.value.code == 2 and "openlogbook[transcribe]" in capsys.readouterr().err


def test_an_offline_shell_is_said_before_the_hub_is_asked(lb, hub, pyannote, monkeypatch, capsys):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    with pytest.raises(SystemExit) as e:
        cli.main(["setup", "speakers", "--fetch-model"])
    assert e.value.code == 2 and "HF_HUB_OFFLINE" in capsys.readouterr().err
    assert hub.calls == []


# -- nothing else fetches a speaker model ---------------------------------------------------------


def test_derive_transcripts_fetch_model_fetches_the_whisper_model_and_no_speaker_model(
    lb, hub, pyannote, monkeypatch, capsys
):
    from test_transcribe import FakeEngine, _memo, _wav

    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav())
    engine = FakeEngine(ready=False)
    monkeypatch.setattr(transcribe, "detect", lambda model, **_k: engine)
    cli.main(["derive", "transcripts", "voice-memos", "--fetch-model"])
    assert engine.fetched == 1  # the Whisper model, as ever
    assert hub.calls and all(options == {"local_files_only": True} for _repo, options in hub.calls)
    assert "speakers: not separated (logbook setup speakers --fetch-model)" in capsys.readouterr().out


# -- the hub's own switch ---------------------------------------------------------------------------


def test_quiet_sets_the_switch_the_hub_read_at_import_and_puts_it_back(monkeypatch):
    """`huggingface_hub` reads `HF_HUB_OFFLINE` once, at import, into `constants.HF_HUB_OFFLINE`, and
    asks that on every request: setting the variable later is not enough."""
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    constants = types.ModuleType("huggingface_hub.constants")
    constants.HF_HUB_OFFLINE = False  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "huggingface_hub.constants", constants)
    with diarize.quiet():
        assert constants.HF_HUB_OFFLINE is True  # type: ignore[attr-defined]
        with diarize.quiet():
            assert constants.HF_HUB_OFFLINE is True  # type: ignore[attr-defined]
        assert constants.HF_HUB_OFFLINE is True  # type: ignore[attr-defined]
    assert constants.HF_HUB_OFFLINE is False  # type: ignore[attr-defined]


def test_a_hub_first_imported_inside_quiet_is_online_again_outside_it(monkeypatch):
    """So `derive transcripts --fetch-model` can still fetch the Whisper model after the diarizer
    was looked for."""
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    monkeypatch.delitem(sys.modules, "huggingface_hub.constants", raising=False)
    constants = types.ModuleType("huggingface_hub.constants")
    with diarize.quiet():
        constants.HF_HUB_OFFLINE = True  # type: ignore[attr-defined]  # what an import reads in here
        monkeypatch.setitem(sys.modules, "huggingface_hub.constants", constants)
    assert constants.HF_HUB_OFFLINE is False  # type: ignore[attr-defined]
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")  # the owner's own shell says offline: that is kept
    monkeypatch.delitem(sys.modules, "huggingface_hub.constants")
    later = types.ModuleType("huggingface_hub.constants")
    with diarize.quiet():
        later.HF_HUB_OFFLINE = True  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "huggingface_hub.constants", later)
    assert later.HF_HUB_OFFLINE is True  # type: ignore[attr-defined]


def test_a_run_that_separates_voices_has_the_hub_offline_even_when_it_was_imported_online(
    monkeypatch, tmp_path
):
    from test_transcribe import FakeDiarizer, FakeEngine, _memo, _wav

    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    constants = types.ModuleType("huggingface_hub.constants")
    constants.HF_HUB_OFFLINE = False  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "huggingface_hub.constants", constants)
    seen: list[bool] = []

    class Watching(FakeDiarizer):
        def diarize(self, samples: Any, rate: int, speakers: int | None = None) -> Any:
            seen.append(constants.HF_HUB_OFFLINE)  # type: ignore[attr-defined]
            return super().diarize(samples, rate, speakers)

    lb = Logbook.init(tmp_path / "lb", TZ)
    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav())
    transcribe.run(lb, FakeEngine(), diarizer=Watching())
    assert seen == [True] and constants.HF_HUB_OFFLINE is False  # type: ignore[attr-defined]


def test_a_refusal_the_hub_wraps_in_another_error_is_still_named_as_one():
    class LocalEntryNotFoundError(FileNotFoundError):
        """As hub 1.33's snapshot_download re-raises a failed call it could not serve from cache."""

    def snapshot(repo: str, **_options: Any) -> str:
        try:
            raise GatedRepoError("restricted")
        except GatedRepoError as e:
            raise LocalEntryNotFoundError("Got: ...") from e

    with pytest.raises(diarize.Refused, match=r"huggingface\.co/pyannote/speaker-diarization-3\.1"):
        diarize.fetch(
            {"HF_TOKEN": TOKEN}, _importer(huggingface_hub=types.SimpleNamespace(snapshot_download=snapshot))
        )


def test_the_hub_s_own_words_never_reach_the_screen_even_when_they_hold_the_token(lb, monkeypatch, capsys):
    for failure in (GatedRepoError(f"denied for {TOKEN}"), RuntimeError(f"500 for Bearer {TOKEN}")):

        def snapshot(repo: str, failure: Exception = failure, **_options: Any) -> str:
            raise failure

        module = types.ModuleType("huggingface_hub")
        module.snapshot_download = snapshot  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "huggingface_hub", module)
        monkeypatch.setenv("HF_TOKEN", TOKEN)
        with pytest.raises(SystemExit):
            cli.main(["setup", "speakers", "--fetch-model"])
        out, err = capsys.readouterr()
        assert TOKEN not in out and TOKEN not in err and "Bearer" not in err


def test_transformers_offline_is_an_offline_shell_too(lb, hub, monkeypatch, capsys):
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    with pytest.raises(SystemExit) as e:
        cli.main(["setup", "speakers", "--fetch-model"])
    assert e.value.code == 2 and "TRANSFORMERS_OFFLINE" in capsys.readouterr().err and hub.calls == []


def test_quiet_puts_everything_back_when_the_block_raises(monkeypatch):
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.setenv("PYANNOTE_METRICS_ENABLED", "true")
    constants = types.ModuleType("huggingface_hub.constants")
    constants.HF_HUB_OFFLINE = False  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "huggingface_hub.constants", constants)
    with pytest.raises(RuntimeError), diarize.quiet():
        raise RuntimeError("the pipeline failed")
    assert constants.HF_HUB_OFFLINE is False  # type: ignore[attr-defined]
    assert "HF_HUB_OFFLINE" not in __import__("os").environ
    assert __import__("os").environ["PYANNOTE_METRICS_ENABLED"] == "true"


def test_pyannote_is_imported_with_its_usage_reporting_and_the_hub_already_off():
    """pyannote.audio 4 writes PYANNOTE_METRICS_ENABLED=true at import when it finds none."""
    import os

    seen: dict[str, str | None] = {}

    def import_module(name: str) -> Any:
        if name == "pyannote.audio":
            seen.update({v: os.environ.get(v) for v in ("PYANNOTE_METRICS_ENABLED", "HF_HUB_OFFLINE")})
            return types.SimpleNamespace(__version__="4.0.7")
        if name == "huggingface_hub":
            return FakeHub().module()
        raise ImportError(name)

    diarize.status(import_module)
    assert seen == {"PYANNOTE_METRICS_ENABLED": "0", "HF_HUB_OFFLINE": "1"}


def test_a_cache_that_is_not_whole_is_one_sentence_naming_the_fetch_not_a_traceback(lb, monkeypatch, capsys):
    class LocalEntryNotFoundError(FileNotFoundError):
        pass

    class Pipeline:
        @staticmethod
        def from_pretrained(name: str) -> Any:
            raise LocalEntryNotFoundError(name)

    modules: dict[str, Any] = {  # numpy and torch are asked for and never used: the load fails first
        "pyannote.audio": types.SimpleNamespace(Pipeline=Pipeline),
        "numpy": types.SimpleNamespace(),
        "torch": types.SimpleNamespace(),
    }
    with pytest.raises(diarize.ModelsMissing, match="logbook setup speakers --fetch-model"):
        diarize.Pyannote(_importer(**modules)).diarize([0.0], 16_000)

    class Nothing:
        @staticmethod
        def from_pretrained(name: str) -> Any:
            return None

    modules["pyannote.audio"] = types.SimpleNamespace(Pipeline=Nothing)
    with pytest.raises(diarize.ModelsMissing):
        diarize.Pyannote(_importer(**modules)).diarize([0.0], 16_000)

    from test_transcribe import FakeEngine, _memo, _wav

    class Broken:
        name, model = diarize.ENGINE, diarize.MODEL

        def diarize(self, *_a: Any, **_k: Any) -> Any:
            raise diarize.ModelsMissing()

        def channels(self, path: Path) -> Any:
            raise AssertionError("a room")

    _memo(lb, "7A1B2C3D-0000-4000-8000-000000000001", "2026-03-02T20:14:07Z", audio=_wav())
    monkeypatch.setattr(transcribe, "detect", lambda model, **_k: FakeEngine(model))
    monkeypatch.setattr(diarize, "detect", lambda *_a, **_k: Broken())
    with pytest.raises(SystemExit) as e:
        cli.main(["derive", "transcripts", "voice-memos"])
    assert e.value.code == 2 and "logbook setup speakers --fetch-model" in capsys.readouterr().err


def test_hearing_again_has_the_hub_s_own_switch_off_too(lb, monkeypatch):
    from test_derive_speakers import _heard_before
    from test_transcribe import FakeDiarizer, FakeEngine

    _heard_before(lb)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    constants = types.ModuleType("huggingface_hub.constants")
    constants.HF_HUB_OFFLINE = False  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "huggingface_hub.constants", constants)
    seen: list[bool] = []

    class Watching(FakeDiarizer):
        def diarize(self, samples: Any, rate: int, speakers: int | None = None) -> Any:
            seen.append(constants.HF_HUB_OFFLINE)  # type: ignore[attr-defined]
            return super().diarize(samples, rate, speakers)

    transcribe.rehear(lb, transcribe.unseparated(lb), lambda model: FakeEngine(model), Watching())
    assert seen == [True] and constants.HF_HUB_OFFLINE is False  # type: ignore[attr-defined]


def test_the_diarizer_is_in_the_transcribe_extra_and_nowhere_else():
    import tomllib

    project = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )

    def names(specs: list[str]) -> set[str]:
        return {
            spec.split(";")[0].split(">")[0].split("=")[0].split("<")[0].strip().lower() for spec in specs
        }

    extras = project["project"]["optional-dependencies"]
    assert "pyannote.audio" in names(extras["transcribe"])
    assert all(
        "pyannote.audio" not in names(specs) for extra, specs in extras.items() if extra != "transcribe"
    )
    assert "pyannote.audio" not in names(project["project"]["dependencies"])
    assert all(
        "pyannote.audio" not in names([s for s in specs if isinstance(s, str)])
        for specs in project["dependency-groups"].values()
    )


def test_detect_asks_the_cache_before_it_imports_the_engine():
    asked: list[str] = []
    hub = FakeHub(cached={diarize.MODEL})

    def import_module(name: str) -> Any:
        asked.append(name)
        if name == "huggingface_hub":
            return hub.module()
        raise AssertionError(f"{name} imported for a run that cannot use it")

    assert diarize.detect(import_module) is None and asked == ["huggingface_hub"]


def test_once_pyannote_is_in_the_process_its_usage_reporting_stays_off(monkeypatch):
    monkeypatch.delenv("PYANNOTE_METRICS_ENABLED", raising=False)
    monkeypatch.setitem(sys.modules, "pyannote.audio", types.ModuleType("pyannote.audio"))
    with diarize.quiet():
        pass
    import os

    assert os.environ["PYANNOTE_METRICS_ENABLED"] == "0"
