"""`ijson` is the `stream` extra (`logbook.contrib.stream`): the five adapters that stream a large JSON
export import it lazily, a file is still recognised without it, and `logbook add` says which extra to
install instead of failing in the parser."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from logbook import cli
from logbook.contrib import adapters, stream
from logbook.contrib.adapters import dawarich, spotify
from logbook.contrib.adapters.takeout import activity, location, youtube
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
DAWARICH = ROOT / "tests" / "fixtures" / "dawarich" / "export.json"
STREAMING = (dawarich, spotify, activity, location, youtube)


def _without_ijson(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse() -> None:
        raise stream.MissingExtra(stream.MESSAGE)

    monkeypatch.setattr(stream, "_import", refuse)


def test_the_extra_is_declared_and_ijson_is_no_longer_a_dependency() -> None:
    with (ROOT / "pyproject.toml").open("rb") as f:
        project = tomllib.load(f)["project"]
    assert not any(dep.startswith("ijson") for dep in project["dependencies"])
    assert project["optional-dependencies"]["stream"] == ["ijson>=3.3"]
    assert stream.EXTRA == "openlogbook[stream]"


def test_the_streaming_adapters_take_ijson_from_the_extra_module() -> None:
    for adapter in STREAMING:
        assert adapter.ijson is stream.ijson, adapter.__name__


def test_with_ijson_the_module_stands_in_for_it() -> None:
    import ijson

    assert stream.available()
    assert stream.ijson.items is ijson.items


def test_without_ijson_the_message_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    _without_ijson(monkeypatch)
    assert not stream.available()
    with pytest.raises(stream.MissingExtra, match=r"openlogbook\[stream\]"):
        _ = stream.ijson.items
    with pytest.raises(ImportError):  # it is an ImportError, for a caller that only knows that
        _ = stream.ijson.parse


def test_without_ijson_a_file_is_still_recognised_and_other_files_still_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _without_ijson(monkeypatch)
    assert dawarich.sniff(DAWARICH) is True
    notes = tmp_path / "notes.txt"
    notes.write_text("just words\n", encoding="utf-8")
    assert dawarich.sniff(notes) is False and location.sniff(notes) is False
    assert adapters.find(notes) is None
    assert adapters.find(DAWARICH) is dawarich


def test_without_ijson_add_says_what_to_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _without_ijson(monkeypatch)
    root = tmp_path / "Logbook"
    Logbook.init(root, "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    with pytest.raises(SystemExit) as e:
        cli.main(["add", str(DAWARICH)])
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "add: dawarich:" in err and "openlogbook[stream]" in err
    assert Logbook(root).meta["seq"] == 0, "nothing was written"
