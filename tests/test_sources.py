"""`policy/import.json`: the owner's list of disabled sources, honoured by `add`, `sync` and
`import-backup`, and `logbook sources`, which lists every adapter with its state. An adapter existing
is not a decision to run it. Every string here is synthetic; nobody in the fixtures exists."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from logbook import adapters, cli, policy
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
POCKET_CSV = ROOT / "tests" / "fixtures" / "pocket" / "part_000000.csv"


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    monkeypatch.delenv("LOGBOOK_DAWARICH_URL", raising=False)
    monkeypatch.delenv("LOGBOOK_DAWARICH_KEY", raising=False)
    return Logbook.init(root, "Europe/Oslo")


def _disable(lb: Logbook, *entries: tuple[str, str]) -> Path:
    path = lb.root / "policy" / "import.json"
    path.write_text(
        json.dumps({"disabled": [{"source": s, "reason": r} for s, r in entries]}, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


# -- the file ------------------------------------------------------------------------------------


def test_init_writes_an_empty_import_policy(lb: Logbook):
    path = lb.root / "policy" / "import.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {"disabled": []}


def test_a_record_without_the_file_gets_an_empty_one_on_first_read(lb: Logbook):
    path = lb.root / "policy" / "import.json"
    path.unlink()  # a record made before 0.5.0
    assert policy.disabled(lb.root) == {}
    assert json.loads(path.read_text(encoding="utf-8")) == {"disabled": []}


def test_disabled_maps_source_to_reason_and_never_overwrites(lb: Logbook):
    path = _disable(lb, ("pocket", "someone else's reading list"), ("sbb", "demo data only"))
    before = path.read_text(encoding="utf-8")
    assert policy.disabled(lb.root) == {"pocket": "someone else's reading list", "sbb": "demo data only"}
    assert path.read_text(encoding="utf-8") == before


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        '{"disabled": "pocket"}',
        '{"disabled": [{"source": "pocket"}]}',
        '{"disabled": [{"source": 3, "reason": "x"}]}',
        '["pocket"]',
    ],
)
def test_a_malformed_policy_is_refused_naming_the_file(lb: Logbook, text: str):
    path = lb.root / "policy" / "import.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(policy.PolicyError) as e:
        policy.disabled(lb.root)
    assert str(path) in str(e.value)


# -- logbook sources -----------------------------------------------------------------------------


def test_sources_lists_every_adapter_as_enabled_by_default(lb: Logbook, capsys):
    cli.main(["sources"])
    out = capsys.readouterr().out
    rows = {line.split()[0]: line for line in out.splitlines() if line and not line.startswith(" ")}
    names = {a.NAME for a in adapters.all_adapters()}
    assert names <= set(rows)
    for name in names:
        assert "enabled" in rows[name] and "disabled" not in rows[name]
    assert "file+live" in rows["dawarich"]  # an export and a live pull under one name
    assert "file+live" in rows["imessage"]
    assert rows["pocket"].split()[1] == "file"
    assert rows["gcal"].split()[1] == "live"
    assert str(lb.root / "policy" / "import.json") in out


def test_sources_shows_a_disabled_adapter_with_its_reason(lb: Logbook, capsys):
    _disable(lb, ("pocket", "someone else's reading list"))
    cli.main(["sources"])
    out = capsys.readouterr().out
    row = next(line for line in out.splitlines() if line.startswith("pocket "))
    assert "disabled" in row and "someone else's reading list" in row
    assert sum("disabled (" in line for line in out.splitlines()) == 1


def test_sources_resolves_an_alias_and_names_an_unknown_source(lb: Logbook, capsys):
    _disable(lb, ("books", "the library is not mine"), ("kindle", "no adapter yet"))
    cli.main(["sources"])
    out = capsys.readouterr().out
    row = next(line for line in out.splitlines() if line.startswith("apple-books "))
    assert "disabled" in row and "the library is not mine" in row
    assert "kindle" in out and "no adapter" in out


def test_sources_writes_the_file_when_missing(lb: Logbook, capsys):
    path = lb.root / "policy" / "import.json"
    path.unlink()
    cli.main(["sources"])
    assert json.loads(path.read_text(encoding="utf-8")) == {"disabled": []}


def test_sources_exits_2_on_a_malformed_policy(lb: Logbook, capsys):
    path = lb.root / "policy" / "import.json"
    path.write_text('{"disabled": 1}', encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        cli.main(["sources"])
    assert e.value.code == 2
    assert str(path) in capsys.readouterr().err


# -- add -----------------------------------------------------------------------------------------


def test_add_skips_a_disabled_adapter_and_says_so(lb: Logbook, capsys):
    _disable(lb, ("pocket", "someone else's reading list"))
    cli.main(["add", str(POCKET_CSV)])  # sniffed
    out = capsys.readouterr().out
    assert "pocket: disabled (someone else's reading list); skipped" in out
    assert "import.json" in out
    assert lb.meta["seq"] == 0
    cli.main(["add", "pocket", str(POCKET_CSV)])  # by name
    assert "skipped" in capsys.readouterr().out
    assert lb.meta["seq"] == 0


def test_add_runs_an_adapter_that_is_not_disabled(lb: Logbook, capsys):
    _disable(lb, ("sbb", "demo data only"))
    cli.main(["add", str(POCKET_CSV)])
    assert "added" in capsys.readouterr().out
    assert lb.meta["seq"] > 0


def test_add_exits_2_on_a_malformed_policy(lb: Logbook, capsys):
    path = lb.root / "policy" / "import.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        cli.main(["add", str(POCKET_CSV)])
    assert e.value.code == 2
    assert str(path) in capsys.readouterr().err
    assert lb.meta["seq"] == 0


# -- sync ----------------------------------------------------------------------------------------


def test_sync_skips_a_disabled_source_before_asking_for_its_variables(lb: Logbook, capsys):
    _disable(lb, ("dawarich", "the server is a demo"))
    cli.main(["sync", "dawarich"])  # no LOGBOOK_DAWARICH_URL set: the skip comes first
    captured = capsys.readouterr()
    assert "dawarich: disabled (the server is a demo); skipped" in captured.out
    assert captured.err == ""
    assert lb.meta["seq"] == 0
    assert not (lb.root / "state").exists()
