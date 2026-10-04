"""`logbook setup`: the guided first run, one question at a time, resumable through `state/setup.json`.
Everything here is synthetic: the home directory is a temp folder, the person is the Oslo persona, who
does not exist, every store is a fixture built in the tests, and every variable's value is a sentinel
the output must never show."""

from __future__ import annotations

import io
import json
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_imessage import _store as _messages_store
from test_import_backup import _backup

from logbook import cli, setup
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
TAKEOUT_FIXTURE = ROOT / "tests" / "fixtures" / "takeout"
SENTINEL = "never-printed-7f3a2b1c"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A home directory of its own, with no record in it and no LOGBOOK_HOME, so the wizard starts
    from nothing. `Path.home` is monkeypatched, never `HOME` alone (CLAUDE.md)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.delenv("LOGBOOK_HOME", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("OneDrive", raising=False)
    monkeypatch.chdir(tmp_path)  # never a code checkout, never a record
    for name in setup.live_variable_names():
        monkeypatch.delenv(name, raising=False)
    return home


@pytest.fixture
def run(
    home: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> Callable[..., str]:
    """`logbook setup ...` with the given lines typed, one per question; the text printed."""

    def _run(*args: str, answers: str | None = None) -> str:
        if answers is not None:
            monkeypatch.setattr("sys.stdin", io.StringIO(answers))
        try:
            cli.main(["setup", *args])
        except SystemExit as e:
            assert not e.code, f"setup exited {e.code}"
        return capsys.readouterr().out

    return _run


def _state(root: Path) -> dict[str, str]:
    data = json.loads((root / "state" / "setup.json").read_text(encoding="utf-8"))
    return dict(data["steps"])


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# -- --yes: every default taken, nothing asked -----------------------------------------------------------


def test_yes_creates_the_record_and_walks_every_step(run: Callable[..., str], home: Path) -> None:
    out = run("--yes")
    root = home / "Logbook"
    assert (root / "logbook.json").is_file(), "the default folder is ~/Logbook"
    assert _state(root) == {
        "folder": "done",
        "timezone": "done",
        "owner": "skipped",  # no default for who you are
        "home": "skipped",  # nor for where you live
        "sources": "done",
        "doctor": "done",
    }
    for n, title in enumerate(setup.TITLES.values(), start=1):
        assert f"Step {n} of {len(setup.STEPS)}: {title}" in out
    assert "Why:" in out, "every question says why it is asked"
    own = out[: out.index("Step 6 of 6")]  # doctor's own lines name the record's full path, as always
    assert str(home) not in own, "the home directory is never spelled by the wizard; ~ is"
    assert "never your own company" in out
    assert "record " in out and "folder " in out, "it ends with doctor's checks"
    assert "Setup is complete" in out


def test_a_second_run_says_setup_is_complete(run: Callable[..., str]) -> None:
    run("--yes")
    out = run("--yes")
    assert "already complete" in out
    assert "--step" in out and "--again" in out


def test_yes_never_asks(run: Callable[..., str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(""))  # closed input: a question would stop the run
    out = run("--yes")
    assert "Setup is complete" in out


# -- the folder --------------------------------------------------------------------------------------------


def test_refuses_a_cloud_synced_folder_with_the_reason(run: Callable[..., str], home: Path) -> None:
    cloud = home / "Dropbox" / "Logbook"
    plain = home / "Records" / "Logbook"
    out = run("--yes", "--step", "folder", answers=f"{cloud}\n{plain}\n") if False else None
    # --yes takes defaults, so the folder question is answered by typing, every other step by Enter
    out = run(answers=f"{cloud}\n{plain}\n" + "\n" * 20)
    assert "under Dropbox" in out and "someone else's server" in out
    assert not cloud.exists()
    assert (plain / "logbook.json").is_file()
    hint = f"export LOGBOOK_HOME={Path('~') / 'Records' / 'Logbook'}"
    assert hint in out, "a record elsewhere needs the variable"


def test_default_folder_is_logbook_home_when_set(
    run: Callable[..., str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "elsewhere" / "Logbook"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    out = run("--yes")
    assert (root / "logbook.json").is_file()
    assert "export LOGBOOK_HOME" not in out, "the shell already points at it"


def test_an_existing_record_is_kept_and_setup_continues_in_it(run: Callable[..., str], home: Path) -> None:
    lb = Logbook.init(home / "Logbook", "Europe/Oslo")
    lb.append("2026-06-08T07:00:00Z", "manual", "note", 2, {"schema": "note/v1", "text": "a synthetic note"})
    out = run("--yes")
    assert "Found your record" in out
    assert lb.meta["seq"] == 1, "nothing is written to the record by the defaults"
    assert _state(lb.root)["folder"] == "done"


# -- the timezone ------------------------------------------------------------------------------------------


def test_timezone_is_validated_and_written(run: Callable[..., str], home: Path) -> None:
    out = run(answers="\nMars/Olympus\nEurope/Oslo\n" + "\n" * 20)
    assert "Mars/Olympus" in out and "not a zone this machine knows" in out
    assert _read(home / "Logbook" / "logbook.json")["timezone"] == "Europe/Oslo"
    assert _state(home / "Logbook")["timezone"] == "done"


# -- who you are -------------------------------------------------------------------------------------------


def test_owner_aliases_go_to_policy_owner_json(run: Callable[..., str], home: Path) -> None:
    answers = "\n\nInes Nordmann, Ines\nines.nordmann@example.org\n07700 900123, 07700 900124\n" + "\n" * 20
    out = run(answers=answers)
    assert _read(home / "Logbook" / "policy" / "owner.json") == {
        "names": ["Ines Nordmann", "Ines"],
        "emails": ["ines.nordmann@example.org"],
        "phones": ["07700 900123", "07700 900124"],
    }
    assert "never your own company" in out
    assert _state(home / "Logbook")["owner"] == "done"
    assert _read(home / "Logbook" / "logbook.json")["owner_emails"] == ["ines.nordmann@example.org"]


def test_owner_step_keeps_what_the_file_already_lists(run: Callable[..., str], home: Path) -> None:
    lb = Logbook.init(home / "Logbook", "Europe/Oslo")
    (lb.root / "policy" / "owner.json").write_text(
        json.dumps({"names": ["Ines Nordmann"], "emails": [], "phones": []}), encoding="utf-8"
    )
    out = run(answers="\nInes\nines.nordmann@example.org\n\n" + "\n" * 20)  # the folder is found, not asked
    assert "already listed: Ines Nordmann" in out
    assert _read(lb.root / "policy" / "owner.json") == {
        "names": ["Ines Nordmann", "Ines"],
        "emails": ["ines.nordmann@example.org"],
        "phones": [],
    }


# -- your home place ---------------------------------------------------------------------------------------


def test_home_from_pasted_coordinates_never_an_address(run: Callable[..., str], home: Path) -> None:
    answers = "\n\n\n\n\nsome street 1\n59.9139, 10.7522\n\n" + "\n" * 20  # owner skipped by three Enters
    out = run(answers=answers)
    assert "not coordinates" in out, "an address is refused and the question asked again"
    written = _read(home / "Logbook" / "places.json")
    assert written["Home"]["kind"] == "home"
    assert abs(written["Home"]["lat"] - 59.9139) < 1e-6 and abs(written["Home"]["lon"] - 10.7522) < 1e-6
    lb = Logbook(home / "Logbook")
    notes = [line for line in lb.lines() if line["kind"] == "note"]
    assert len(notes) == 1 and notes[0]["payload"]["text"] == "named 59.9139,10.7522 as Home"
    assert "some street 1" not in json.dumps(written), "no address is kept anywhere"
    assert _state(lb.root)["home"] == "done"


def test_home_step_is_done_when_a_home_place_exists(run: Callable[..., str], home: Path) -> None:
    lb = Logbook.init(home / "Logbook", "Europe/Oslo")
    (lb.root / "places.json").write_text(
        json.dumps({"Home": {"lat": 59.9139, "lon": 10.7522, "radius_m": 120, "kind": "home"}}),
        encoding="utf-8",
    )
    out = run("--yes")
    assert "already named: Home" in out
    assert _state(lb.root)["home"] == "done"


# -- stopping and resuming ---------------------------------------------------------------------------------


def test_quitting_saves_the_steps_done_and_the_next_run_resumes(run: Callable[..., str], home: Path) -> None:
    out = run(answers="\n\nq\n")  # folder, timezone, then q at the owner's first question
    root = home / "Logbook"
    assert _state(root) == {"folder": "done", "timezone": "done"}
    assert "logbook setup" in out and "continues where you stopped" in out
    out = run(answers="q\n")
    assert "Step 1 of" not in out and "Step 2 of" not in out
    assert "Step 3 of 6: who you are" in out, "the next run starts at the first step not yet answered"


def test_closing_the_input_is_a_quiet_stop(run: Callable[..., str], home: Path) -> None:
    out = run(answers="")  # EOF at the first question
    assert "continues where you stopped" in out
    assert not (home / "Logbook").exists(), "nothing was answered, nothing was made"


def test_skip_moves_on_and_is_recorded(run: Callable[..., str], home: Path) -> None:
    run(answers="\n\ns\ns\n" + "\n" * 20)
    assert _state(home / "Logbook")["owner"] == "skipped"
    assert _state(home / "Logbook")["home"] == "skipped"


def test_step_reruns_one_step_and_again_starts_over(
    run: Callable[..., str], home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run("--yes")
    out = run("--step", "owner", answers="Ines Nordmann\n\n\n")
    assert "Step 3 of 6" in out
    assert _read(home / "Logbook" / "policy" / "owner.json")["names"] == ["Ines Nordmann"]
    assert _state(home / "Logbook")["owner"] == "done"
    out = run("--again", "--yes")
    assert "Step 1 of 6" in out and "Found your record" in out
    with pytest.raises(SystemExit):
        cli.main(["setup", "--step", "nonsuch"])
    assert "no step named" in capsys.readouterr().err


# -- the sources checklist -------------------------------------------------------------------------------


def test_nothing_found_says_so_with_where_to_look(run: Callable[..., str]) -> None:
    out = run("--yes")
    assert "Google Takeout" in out and "Downloads" in out
    assert "iPhone backup" in out and "MobileSync" in out
    assert "Messages" in out
    assert "nothing to import yet" in out


def test_a_takeout_in_downloads_is_imported_after_a_dry_run(run: Callable[..., str], home: Path) -> None:
    takeout = home / "Downloads" / "Takeout"
    for product in ("Google Chat", "Google Meet", "My Activity"):
        shutil.copytree(TAKEOUT_FIXTURE / product, takeout / product)
    out = run("--yes")
    assert f"Google Takeout at {Path('~') / 'Downloads' / 'Takeout'}" in out
    assert "google-takeout-chat" in out and "google-takeout-meet" in out
    assert "google-takeout-activity: switched off in policy/import.json" in out
    dry, wet = out.index("lines would be added"), out.index("added ")
    assert dry < wet, "the dry run and its counts come before anything is written"
    lb = Logbook(home / "Logbook")
    sources = {line["source"] for line in lb.lines()}
    assert sources == {"google-takeout"}
    assert lb.meta["seq"] > 0
    assert not any(line["payload"].get("raw_id", "").startswith("activity") for line in lb.lines())


def test_a_takeout_zip_is_named_but_not_read(run: Callable[..., str], home: Path) -> None:
    (home / "Downloads").mkdir()
    (home / "Downloads" / "takeout-20260601T000000Z-001.zip").write_bytes(b"PK\x05\x06" + b"\0" * 18)
    out = run("--yes")
    assert "takeout-20260601T000000Z-001.zip" in out and "unzip" in out.lower()
    assert Logbook(home / "Logbook").meta["seq"] == 0


def test_declining_the_import_writes_nothing(run: Callable[..., str], home: Path) -> None:
    shutil.copytree(TAKEOUT_FIXTURE / "Google Chat", home / "Downloads" / "Takeout" / "Google Chat")
    out = run(answers="\n\ns\ns\nn\n" + "\n" * 20)
    assert "lines would be added" not in out
    assert Logbook(home / "Logbook").meta["seq"] == 0


def test_an_iphone_backup_in_mobilesync_is_imported_with_only(
    run: Callable[..., str], home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOGBOOK_BACKUP_PASSWORD", SENTINEL)  # the shell may hold one; setup never reads it
    (tmp_path / "mk").mkdir()
    built = _backup(tmp_path / "mk", sources=("ios-contacts", "ios-notes"))
    folder = home / "Library" / "Application Support" / "MobileSync" / "Backup" / "00008030-000000000000AAAA"
    folder.parent.mkdir(parents=True)
    shutil.move(str(built), str(folder))
    out = run("--yes")
    assert "iPhone backup" in out and "00008030-000000000000AAAA" in out
    assert "--only ios-contacts,ios-notes" in out, "never run bare against a backup"
    assert "dry run" in out and "would be copied" in out
    lb = Logbook(home / "Logbook")
    kinds = {line["kind"] for line in lb.lines()}
    assert "resolution" in kinds and "note" in kinds
    assert SENTINEL not in out


def test_an_encrypted_backup_names_the_variable_and_asks_for_nothing(
    run: Callable[..., str], home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOGBOOK_BACKUP_PASSWORD", SENTINEL)
    (tmp_path / "mk").mkdir()
    built = _backup(tmp_path / "mk", sources=("ios-contacts",), encrypted=True)
    folder = home / "Library" / "Application Support" / "MobileSync" / "Backup" / "00008030-00000000000000BB"
    folder.parent.mkdir(parents=True)
    shutil.move(str(built), str(folder))
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    out = run("--yes")
    assert "encrypted" in out and "LOGBOOK_BACKUP_PASSWORD" in out and "read -s" in out
    assert SENTINEL not in out
    assert Logbook(home / "Logbook").meta["seq"] == 0


def test_messages_on_this_mac_are_synced_after_a_dry_run(run: Callable[..., str], home: Path) -> None:
    folder = home / "Library" / "Messages"
    folder.mkdir(parents=True)
    _messages_store(folder, "chat.db")
    out = run("--yes")
    assert "Messages on this Mac" in out and "Full Disk Access" in out
    assert "sync imessage" in out
    lb = Logbook(home / "Logbook")
    assert {line["kind"] for line in lb.lines()} == {"message"}
    assert (lb.root / "state" / "imessage.json").is_file(), "the watermark is kept for the next sync"


def test_live_sources_are_named_with_their_variables_never_a_value(
    run: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOGBOOK_DAWARICH_URL", "https://dawarich.example.org")
    monkeypatch.setenv("LOGBOOK_DAWARICH_KEY", SENTINEL)
    out = run("--yes")
    assert "dawarich: configured (LOGBOOK_DAWARICH_URL, LOGBOOK_DAWARICH_KEY)" in out
    assert "adsb: works without a key" in out, "every variable optional and none set is not `configured`"
    assert "LOGBOOK_IMMICH_KEY" in out and "Account settings" in out, "where to get the key"
    assert "LOGBOOK_GCAL_URLS" in out
    assert SENTINEL not in out and "dawarich.example.org" not in out


# -- the module's own pieces -------------------------------------------------------------------------------


def test_coordinates_are_parsed_strictly() -> None:
    assert setup.parse_coordinates("59.9139, 10.7522") == (59.9139, 10.7522)
    assert setup.parse_coordinates("59.9139,10.7522") == (59.9139, 10.7522)
    assert setup.parse_coordinates("-33.8688 151.2093") == (-33.8688, 151.2093)
    for bad in ("some street 1", "91, 0", "0, 181", "59.9139", "", "N59 E10"):
        assert setup.parse_coordinates(bad) is None, bad


def test_the_list_answer_splits_on_commas_and_drops_blanks() -> None:
    assert setup.split_list(" Ines Nordmann ,Ines,, ") == ["Ines Nordmann", "Ines"]
    assert setup.split_list("") == []
