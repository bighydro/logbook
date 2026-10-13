"""`logbook sync drive` with the Drive metadata scope (`drive.metadata.readonly`): each line names the folder
path of its file, which the Activity API alone could not give. A file's parents are asked once per sync,
each folder's name and parent once and then kept in `state/drive-cache.json`, never in the record; lines
already written are never rewritten.

The synthetic Monday of `tests/test_drive.py` (Ines Nordmann of Oslo, who does not exist), with her
Drive's folders in the in-process fake of `tests/google_fake.py`."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from google_fake import DRIVE_SCOPE, METADATA_SCOPE, USER, Fake, activity, item, private_key, write_key
from test_drive import BUDGET, CREW, DAY, DRIVE_FILES, FOLDER, LINES, _activities, _t

from logbook import cli
from logbook.contrib.adapters import drive, service_account
from logbook.core.store import Logbook

KEY_ENV, USER_ENV = service_account.KEY_ENV, service_account.USER_ENV
FILES = "www.googleapis.com/drive/v3/files/"


@pytest.fixture(scope="module")
def key() -> Any:
    return private_key()


@pytest.fixture
def fake(tmp_path: Path, key: Any, monkeypatch: pytest.MonkeyPatch, no_network: list[str]) -> Any:
    server = Fake(key, drive=_activities(), files=json.loads(json.dumps(DRIVE_FILES)))
    server.waits = []  # type: ignore[attr-defined]
    monkeypatch.setattr(service_account, "send", server)
    monkeypatch.setattr(service_account, "sleep", server.waits.append)  # type: ignore[attr-defined]
    monkeypatch.setenv(KEY_ENV, str(write_key(tmp_path / "google-sa.json", key)))
    monkeypatch.setenv(USER_ENV, USER)
    yield server
    assert no_network == [], "the fake is the only way out"


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    return lb


def _config() -> service_account.Account:
    account = drive.configure(os.environ)
    assert account is not None
    return account


def _pull(**kw: Any) -> tuple[list[dict[str, Any]], dict[str, int]]:
    counts: dict[str, int] = {}
    drafts = list(drive.pull(_config(), counts=counts, timezone="Europe/Oslo", **kw))
    return drafts, counts


def _paths(drafts: list[dict[str, Any]]) -> dict[str, list[str] | None]:
    return {d["payload"]["extra"]["file"]["id"]: d["payload"]["extra"]["file"].get("path") for d in drafts}


def _asked(fake: Fake) -> list[str]:
    return [p.removeprefix(FILES) for _m, p, _q in fake.requests if p.startswith(FILES)]


def _sync(*args: str) -> int:
    try:
        cli.main(["sync", "drive", *args])
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    return 0


def _cache(lb: Logbook) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((lb.root / "state" / "drive-cache.json").read_text(encoding="utf-8"))
    return data


# -- the path on the line -------------------------------------------------------------------------------


def test_a_line_carries_the_folder_path_of_its_file_root_first(fake: Fake) -> None:
    drafts, _counts = _pull()
    paths = _paths(drafts)
    assert paths["1BudgetSheet"] == ["My Drive", "Money"]
    assert paths["1CrewDoc"] == ["My Drive", "Boat"]
    budget = next(d for d in drafts if d["payload"]["extra"]["file"]["id"] == "1BudgetSheet")
    assert list(budget["payload"]["extra"]["file"]) == ["id", "name", "mime_type", "url", "path"]


def test_a_file_gone_or_with_no_folder_of_the_owners_has_no_path_and_is_counted(fake: Fake) -> None:
    drafts, counts = _pull()
    paths = _paths(drafts)
    assert paths["1OldNotes"] is None and paths["1PackingDoc"] is None
    lines_without = sum(1 for d in drafts if "path" not in d["payload"]["extra"]["file"])
    assert counts["no_folder_path"] == lines_without == 4  # notes trashed, restored, deleted; Per's list


def test_each_file_and_each_folder_is_asked_once_per_sync(fake: Fake) -> None:
    _pull()
    asked = _asked(fake)
    assert sorted(asked) == sorted(
        ["1BudgetSheet", "1CrewDoc", "1OldNotes", "1PackingDoc", "1Money", "0Root", "1Boat"]
    )
    for _m, path, query in fake.requests:
        if path.startswith(FILES):
            assert query == {"fields": "id,name,parents", "supportsAllDrives": "true"}, (
                "metadata, never content"
            )


def test_the_client_only_reads_with_the_two_drive_scopes(fake: Fake) -> None:
    _pull()
    assert fake.methods() == {
        ("POST", "oauth2.googleapis.com"),
        ("POST", "driveactivity.googleapis.com"),
        ("GET", "www.googleapis.com"),
    }
    assert {a["scope"] for a in fake.assertions} == {DRIVE_SCOPE, METADATA_SCOPE}


def test_without_the_metadata_scope_the_lines_carry_no_path_and_say_so(fake: Fake) -> None:
    fake.delegated = {DRIVE_SCOPE}
    said: list[str] = []
    drafts, counts = _pull(notice=said.append)
    assert len(drafts) == LINES and all("path" not in d["payload"]["extra"]["file"] for d in drafts)
    assert said == [
        f"folder paths: {METADATA_SCOPE} is not delegated to this key; these lines carry none"
        " (the tour, Google, on one key)"
    ]
    assert "no_folder_path" not in counts


# -- the cache ------------------------------------------------------------------------------------------


def test_the_folders_are_kept_in_state_and_not_asked_again(lb: Logbook, fake: Fake) -> None:
    assert _sync() == 0
    folders = _cache(lb)["folders"]
    assert {k: (v["name"], v["parent"]) for k, v in folders.items()} == {
        "0Root": ("My Drive", None),
        "1Money": ("Money", "0Root"),
        "1Boat": ("Boat", "0Root"),
    }
    text = json.dumps([line for line in lb.lines()])
    assert "1Money" not in text and "0Root" not in text, "folder ids stay in state/, never in the record"
    fake.drive.append(activity(_t("18:00:00"), {"edit": {}}, BUDGET))
    fake.requests.clear()
    assert _sync("--since", f"{DAY}T17:59:00Z") == 0
    assert _asked(fake) == ["1BudgetSheet"], "the file once more, its folders from the cache"
    (line,) = [x for x in lb.lines() if x["at"] == f"{DAY}T18:00:00Z"]
    assert line["payload"]["extra"]["file"]["path"] == ["My Drive", "Money"]


def test_a_folder_renamed_or_moved_since_is_asked_again(lb: Logbook, fake: Fake) -> None:
    assert _sync() == 0
    fake.files["1Money"]["name"] = "Money and boats"
    folder = item("1Money", "Money and boats", FOLDER)
    fake.drive.append(
        activity(_t("18:00:00"), {"rename": {"oldTitle": "Money", "newTitle": "Money and boats"}}, folder)
    )
    fake.drive.append(activity(_t("18:05:00"), {"edit": {}}, BUDGET))
    assert _sync("--since", f"{DAY}T17:59:00Z") == 0
    (edit,) = [x for x in lb.lines() if x["at"] == f"{DAY}T18:05:00Z"]
    assert edit["payload"]["extra"]["file"]["path"] == ["My Drive", "Money and boats"]
    assert _cache(lb)["folders"]["1Money"]["name"] == "Money and boats"


def test_a_folder_kept_longer_than_a_week_is_asked_again(lb: Logbook, fake: Fake) -> None:
    path = lb.root / "state" / "drive-cache.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    old = (datetime.now(UTC) - timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fresh = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(
        json.dumps(
            {
                "folders": {
                    "0Root": {"name": "My Drive", "parent": None, "resolved_at": fresh},
                    "1Money": {"name": "Old money", "parent": "0Root", "resolved_at": old},
                }
            }
        ),
        encoding="utf-8",
    )
    assert _sync() == 0
    assert "1Money" in _asked(fake) and "0Root" not in _asked(fake)
    budget = next(x for x in lb.lines() if x["payload"]["extra"]["file"]["id"] == "1BudgetSheet")
    assert budget["payload"]["extra"]["file"]["path"] == ["My Drive", "Money"]


def test_a_cache_that_is_not_the_shape_is_read_as_empty(lb: Logbook, fake: Fake) -> None:
    path = lb.root / "state" / "drive-cache.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json", encoding="utf-8")
    assert _sync() == 0
    assert set(_cache(lb)["folders"]) == {"0Root", "1Money", "1Boat"}


def test_a_dry_run_asks_and_writes_no_cache(lb: Logbook, fake: Fake) -> None:
    assert _sync("--dry-run") == 0
    assert not (lb.root / "state").exists()


# -- what was written stays written ---------------------------------------------------------------------


def test_lines_already_written_are_not_rewritten(lb: Logbook, fake: Fake, capsys: Any) -> None:
    fake.delegated = {DRIVE_SCOPE}  # before the owner delegated the metadata scope
    assert _sync() == 0
    assert "is not delegated to this key" in capsys.readouterr().err
    before = [json.dumps(line, sort_keys=True) for line in lb.lines()]
    assert len(before) == LINES and all("path" not in line for line in before)
    fake.delegated = {DRIVE_SCOPE, METADATA_SCOPE}
    fake.drive.append(activity(_t("18:00:00"), {"edit": {}}, CREW))
    assert _sync() == 0
    after = [json.dumps(line, sort_keys=True) for line in lb.lines()]
    assert after[:LINES] == before, "the record is appended to, never rewritten"
    (new,) = [json.loads(x) for x in after[LINES:]]
    assert new["payload"]["extra"]["file"]["path"] == ["My Drive", "Boat"]
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == LINES + 1
