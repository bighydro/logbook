"""pyannote.audio is its own extra, `openlogbook[speakers]`, and brings torch with it: nothing imports
it but a run that separates voices. Here the extra is a real installation on disk, not a stand-in in
`sys.modules`: a distribution `pyannote.audio 9.9.9` and a package `pyannote.audio` whose body writes
its name to a file when it is imported (a `torch` likewise), on `sys.path` ahead of everything else.
`diarize.installed` finds the distribution without importing it; every command that needs no diarizer
leaves the file empty, with the hub's cache full or not; and `diarize.detect` with every model in the
cache does import it, which is what shows the file would have said so. The hub is a fake module whose
cache holds nothing, or everything. Synthetic Oslo persona; no model runs, no socket opens."""

from __future__ import annotations

import importlib.metadata
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from test_derive_speakers import _heard_before
from test_setup_speakers import FakeHub
from test_transcribe import TZ, FakeEngine, _memo, _wav

from logbook import cli
from logbook.core.store import Logbook
from logbook.labs import diarize, transcribe

ROOT = Path(__file__).resolve().parents[1]
LOG_VAR = "SPEAKERS_IMPORT_LOG"  # names the file the fakes write to when they are imported
VERSION = "9.9.9"
FAKES = ("pyannote", "torch")  # the top-level names the installation puts on the path
MEMO_ID = "7A1B2C3D-0000-4000-8000-000000000001"
AT = "2026-03-02T20:14:07Z"
DAY = "2026-03-03"  # a day of the reflection, in the past
NOT_SEPARATED = "speakers: not separated (logbook setup speakers --fetch-model)"
NOT_INSTALLED = (
    "speakers: not separated (install openlogbook[speakers], then logbook setup speakers --fetch-model)"
)


class Installation:
    """The `speakers` extra installed under `site`, and `imports`: the names the fakes wrote, in the
    order they were imported; empty while nothing has imported them."""

    def __init__(self, site: Path, log: Path) -> None:
        self.site = site
        self.log = log

    @property
    def imports(self) -> list[str]:
        try:
            return self.log.read_text(encoding="utf-8").split()
        except FileNotFoundError:
            return []


def _recorder(name: str) -> str:
    """The body of a fake package: its import appends its name to the file `LOG_VAR` names."""
    return (
        "import os\n"
        f'with open(os.environ["{LOG_VAR}"], "a", encoding="utf-8") as f:\n'
        f'    f.write("{name}\\n")\n'
    )


def _install(site: Path) -> None:
    """`pip install pyannote.audio` as far as the import system and `importlib.metadata` can tell: the
    distribution's metadata and the package, `pyannote` a namespace package with no `__init__.py` of
    its own, as the real one is; and a `torch` beside it."""
    info = site / f"pyannote_audio-{VERSION}.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: pyannote.audio\nVersion: {VERSION}\n", encoding="utf-8"
    )
    audio = site / "pyannote" / "audio"
    audio.mkdir(parents=True)
    (audio / "__init__.py").write_text(
        _recorder("pyannote.audio") + f'__version__ = "{VERSION}"\n', encoding="utf-8"
    )
    (site / "torch").mkdir()
    (site / "torch" / "__init__.py").write_text(_recorder("torch"), encoding="utf-8")


@pytest.fixture
def installed_extra(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Installation]:
    """The extra on disk and first on `sys.path`, neither package in the process before the test, and
    whatever the test imported of them gone from the process after it."""
    site, log = tmp_path / "site-packages", tmp_path / "imports.txt"
    _install(site)
    monkeypatch.setenv(LOG_VAR, str(log))
    for name in ("pyannote", "pyannote.audio", "torch"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    before = set(sys.modules)
    monkeypatch.syspath_prepend(str(site))
    yield Installation(site, log)
    for name in set(sys.modules) - before:
        if name.partition(".")[0] in FAKES:
            del sys.modules[name]


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch) -> FakeHub:
    """The hub client, where `import huggingface_hub` finds it; its cache holds what a test puts there."""
    fake = FakeHub()
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake.module())
    return fake


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook.init(root, TZ)


@pytest.fixture
def whisper(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Whisper engine is the fake of `test_transcribe`; the diarizer is never faked here."""
    monkeypatch.setattr(transcribe, "detect", lambda model="small", **_k: FakeEngine(model))


def _nothing_imported(installation: Installation) -> None:
    assert installation.imports == []
    assert not {"pyannote", "pyannote.audio", "torch"} & set(sys.modules)


def _only_the_cache_was_asked(hub: FakeHub) -> None:
    assert hub.calls and all(options == {"local_files_only": True} for _repo, options in hub.calls)


# -- the installation ------------------------------------------------------------------------------


def test_installed_finds_the_extra_on_disk_without_importing_it(installed_extra, monkeypatch):
    found = importlib.metadata.distribution("pyannote.audio")
    assert found.version == VERSION
    assert Path(str(found.locate_file(""))).resolve() == installed_extra.site.resolve()  # this one, no other
    assert diarize.installed() is True
    assert diarize.missing() == NOT_SEPARATED  # the extra is here: what is missing is the models
    _nothing_imported(installed_extra)
    monkeypatch.setitem(sys.modules, "pyannote.audio", None)  # the distribution here, its import failed
    assert diarize.installed() is False and diarize.missing() == NOT_INSTALLED  # install it again


def test_detect_with_every_model_in_the_cache_imports_the_engine_and_the_record_of_imports_shows_it(
    installed_extra, hub
):
    """The one path that needs the engine, and the proof that the fakes record what imports them: the
    tests below would be empty if they did not."""
    hub.cached = set(diarize.MODELS)
    found = diarize.detect()
    assert isinstance(found, diarize.Pyannote)
    assert installed_extra.imports == ["pyannote.audio"]  # torch waits for the first recording
    module = sys.modules["pyannote.audio"]
    assert module.__version__ == VERSION
    assert Path(module.__file__).resolve().is_relative_to(installed_extra.site.resolve())
    assert diarize.status().ready and diarize.status().version == VERSION
    assert "torch" not in sys.modules
    _only_the_cache_was_asked(hub)


# -- derive transcripts ----------------------------------------------------------------------------


def test_derive_transcripts_without_the_models_in_the_cache_names_the_fetch_and_imports_no_engine(
    lb, installed_extra, hub, whisper, capsys
):
    """The cache is asked before the engine is imported: on a machine without the models the memo is
    transcribed, the run ends with the fetch (the extra is here, so not the install), and torch was
    never paid for."""
    _memo(lb, MEMO_ID, AT, audio=_wav())
    cli.main(["derive", "transcripts", "voice-memos"])
    out = capsys.readouterr().out
    assert "transcribed 1 voice memo" in out and out.splitlines()[-1] == NOT_SEPARATED
    assert "install" not in out
    _only_the_cache_was_asked(hub)
    _nothing_imported(installed_extra)


@pytest.mark.parametrize(
    ("flag", "said"),
    [
        ("--no-speakers", "transcribed 1 voice memo"),
        ("--dry-run", "dry run: 1 voice memo would be transcribed"),
    ],
)
def test_derive_transcripts_told_not_to_or_dry_asks_for_no_diarizer_even_with_the_models_here(
    lb, installed_extra, hub, whisper, capsys, flag, said
):
    """With every model in the cache a diarizer would be found, and finding it imports the engine:
    neither run looks."""
    hub.cached = set(diarize.MODELS)
    _memo(lb, MEMO_ID, AT, audio=_wav())
    cli.main(["derive", "transcripts", "voice-memos", flag])
    out = capsys.readouterr().out
    assert said in out and "speakers" not in out
    assert hub.calls == []
    _nothing_imported(installed_extra)


def test_derive_transcripts_with_nothing_to_hear_asks_for_no_diarizer_even_with_the_models_here(
    lb, installed_extra, hub, whisper, capsys
):
    """Every memo already heard, or none at all: the run hears nothing, so it neither asks the cache nor
    imports the engine, however often the close runs it."""
    hub.cached = set(diarize.MODELS)
    cli.main(["derive", "transcripts", "voice-memos"])
    _memo(lb, MEMO_ID, AT, audio=_wav())
    transcribe.run(lb, FakeEngine(), diarizer=None, separate=False)  # heard before, without voices
    cli.main(["derive", "transcripts", "voice-memos"])
    out = capsys.readouterr().out
    assert "transcribed 0 voice memos (1 already transcribed)" in out and "speakers" not in out
    assert hub.calls == []
    _nothing_imported(installed_extra)


# -- derive speakers -------------------------------------------------------------------------------


def test_derive_speakers_with_nothing_to_do_or_a_dry_run_asks_for_no_diarizer_even_with_the_models_here(
    lb, installed_extra, hub, capsys
):
    hub.cached = set(diarize.MODELS)
    cli.main(["derive", "speakers"])
    assert "nothing to separate" in capsys.readouterr().out
    _heard_before(lb)
    cli.main(["derive", "speakers", "--dry-run"])
    out = capsys.readouterr().out
    assert "dry run: the voices of 1 transcript would be separated" in out and "openlogbook" not in out
    assert hub.calls == []
    _nothing_imported(installed_extra)


def test_derive_speakers_without_the_models_in_the_cache_names_the_fetch_alone_and_imports_no_engine(
    lb, installed_extra, hub, whisper, capsys
):
    """`detect` answers None from the cache alone; then `installed` reads the metadata, not the module,
    and the sentence names the fetch and not the extra."""
    _heard_before(lb)
    with pytest.raises(SystemExit) as e:
        cli.main(["derive", "speakers"])
    err = capsys.readouterr().err
    assert e.value.code == 2 and diarize.FETCH in err and "install" not in err
    _only_the_cache_was_asked(hub)
    _nothing_imported(installed_extra)
    with lb.index() as idx:
        assert len(list(idx.of_kind("transcript"))) == 1


# -- day reflect -----------------------------------------------------------------------------------


def test_day_reflect_hears_a_recording_and_asks_for_no_diarizer_even_with_the_models_here(
    lb, installed_extra, hub, whisper, tmp_path, capsys
):
    """`transcribe.hear` is the Whisper engine and the hub offline, nothing of voices."""
    hub.cached = set(diarize.MODELS)
    audio = tmp_path / "evening.wav"
    audio.write_bytes(_wav())
    cli.main(["day", "reflect", DAY, "--audio", str(audio)])
    out = capsys.readouterr().out
    assert "heard by fake-whisper" in out and "speakers" not in out
    assert hub.calls == []
    _nothing_imported(installed_extra)


# -- a fresh process -------------------------------------------------------------------------------

SCRIPT = """\
import contextlib, io, json, sys
from logbook.labs import diarize, transcribe
from logbook import cli
with contextlib.redirect_stdout(io.StringIO()), contextlib.suppress(SystemExit):
    cli.main(["--help"])
print(json.dumps({
    "installed": diarize.installed(),
    "missing": diarize.missing(),
    "modules": sorted(m for m in sys.modules if m.partition(".")[0] in ("pyannote", "torch")),
}))
"""


@pytest.mark.parametrize(
    ("with_the_extra", "installed", "missing"),
    [(True, True, NOT_SEPARATED), (False, False, NOT_INSTALLED)],
)
def test_a_fresh_process_imports_neither_package_for_the_modules_or_for_help_and_reads_its_path(
    installed_extra, tmp_path, with_the_extra, installed, missing
):
    """Without `site` (`-S`) the process has the stdlib, this checkout and, when given, the
    installation under its tmp_path, and nothing a machine may hold besides: `installed` is what the
    path says, both ways, and importing the two modules and printing the help imports neither package."""
    paths = [str(ROOT)] + ([str(installed_extra.site)] if with_the_extra else [])
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(paths), LOG_VAR: str(installed_extra.log)}
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    run = subprocess.run(
        [sys.executable, "-S", "-c", SCRIPT], cwd=cwd, env=env, capture_output=True, encoding="utf-8"
    )
    assert run.returncode == 0, run.stderr
    said: dict[str, Any] = json.loads(run.stdout.strip().splitlines()[-1])
    assert said == {"installed": installed, "missing": missing, "modules": []}
    assert installed_extra.imports == []
