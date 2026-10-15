"""`logbook sync drive`: what happened to the owner's Drive files, from the Drive Activity API v2, read-only,
with the service account (`tests/test_service_account.py`). One `event/v1` line per file per hour per
activity, a count for the activities it folds; the file named and referenced, never its content.

Against the in-process fake of `tests/google_fake.py`, on one synthetic Monday of Ines Nordmann of Oslo:
her budget sheet created and edited all morning, partly by Ola; her crew list renamed, moved, shared and
commented on; old notes trashed, restored and deleted; and the activity the source leaves out. Nobody in
it exists, and nothing leaves the process (`no_network`)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from google_fake import (
    DRIVE_SCOPE,
    METADATA_SCOPE,
    OLA,
    PER,
    USER,
    Fake,
    activity,
    item,
    person,
    private_key,
    write_key,
)

from logbook import cli
from logbook.contrib import adapters, doctor
from logbook.contrib.adapters import drive, service_account
from logbook.core.store import Logbook

KEY_ENV, USER_ENV = service_account.KEY_ENV, service_account.USER_ENV
DAY = "2026-09-14"
SHEET = "application/vnd.google-apps.spreadsheet"
DOC = "application/vnd.google-apps.document"
BUDGET = item("1BudgetSheet", "Budget 2027", SHEET)
CREW = item("1CrewDoc", "Crew list", DOC)
NOTES = item("1OldNotes", "Old notes", "text/plain")
PACKING = item("1PackingDoc", "Per's packing list", DOC, owner=person(PER))
BOAT = {"driveItem": {"name": "items/1Boat", "title": "Boat", "driveFolder": {"type": "STANDARD_FOLDER"}}}
INBOX = {"driveItem": {"name": "items/1Inbox", "title": "Inbox", "driveFolder": {"type": "STANDARD_FOLDER"}}}


def _t(clock: str) -> str:
    """A time of the day as the API spells it, with milliseconds."""
    return f"{DAY}T{clock}.000Z"


def _at(clock: str) -> str:
    """The same instant as a line spells it."""
    return f"{DAY}T{clock}Z"


EDIT: dict[str, Any] = {"edit": {}}


def _activities() -> list[dict[str, Any]]:
    shared_drive = activity(_t("16:10:00"), {"rename": {"oldTitle": "Team", "newTitle": "Crew"}}, {})
    shared_drive["targets"] = [{"drive": {"name": "drives/1Team", "title": "Crew"}}]
    return [
        activity(_t("09:05:00"), {"create": {"new": {}}}, BUDGET),
        activity(_t("09:10:00"), EDIT, BUDGET),
        activity(_t("09:20:00"), EDIT, BUDGET),
        activity(_t("09:30:00"), EDIT, BUDGET, actor=person(OLA)),
        activity(_t("09:50:00"), EDIT, BUDGET),
        activity(_t("10:15:00"), EDIT, BUDGET),
        activity(_t("11:00:00"), {"rename": {"oldTitle": "Crew", "newTitle": "Crew list"}}, CREW),
        activity(_t("11:05:00"), {"move": {"addedParents": [BOAT], "removedParents": [INBOX]}}, CREW),
        activity(
            _t("11:10:00"),
            {
                "permissionChange": {
                    "addedPermissions": [
                        {"role": "EDITOR", "user": {"knownUser": {"personName": OLA}}},
                        {"role": "COMMENTER", "group": {"email": "crew@example.org", "title": "Crew"}},
                    ]
                }
            },
            CREW,
        ),
        activity(
            _t("11:20:00"),
            {
                "permissionChange": {
                    "removedPermissions": [{"role": "VIEWER", "domain": {"name": "example.org"}}]
                }
            },
            CREW,
        ),
        activity(_t("12:00:00"), {"delete": {"type": "TRASH"}}, NOTES),
        activity(_t("12:30:00"), {"restore": {"type": "UNTRASH"}}, NOTES),
        activity(_t("13:00:00"), {"delete": {"type": "PERMANENT_DELETE"}}, NOTES),
        activity(
            _t("14:00:00"),
            {
                "comment": {
                    "post": {"subtype": "ADDED"},
                    "mentionedUsers": [{"knownUser": {"personName": OLA}}],
                }
            },
            CREW,
            actor=person(PER),
            comment=True,
        ),
        activity(_t("14:10:00"), {"comment": {"post": {"subtype": "REPLY_ADDED"}}}, CREW, comment=True),
        activity(_t("15:00:00"), EDIT, BUDGET, actor=person(PER)),
        activity(_t("16:00:00"), {"dlpChange": {"type": "FLAGGED"}}, BUDGET),
        shared_drive,
        activity(_t("17:00:00"), EDIT, PACKING, actor=person(PER)),
        activity(_t("17:30:00"), EDIT, PACKING),
    ]


LINES = 12  # the twenty activities above, folded per file, hour and activity, less the three left out

FOLDER = "application/vnd.google-apps.folder"
DRIVE_FILES = {
    "0Root": {"id": "0Root", "name": "My Drive", "mimeType": FOLDER},
    "1Money": {"id": "1Money", "name": "Money", "mimeType": FOLDER, "parents": ["0Root"]},
    "1Boat": {"id": "1Boat", "name": "Boat", "mimeType": FOLDER, "parents": ["0Root"]},
    "1Inbox": {"id": "1Inbox", "name": "Inbox", "mimeType": FOLDER, "parents": ["0Root"]},
    "1BudgetSheet": {"id": "1BudgetSheet", "name": "Budget 2027", "parents": ["1Money"]},
    "1CrewDoc": {"id": "1CrewDoc", "name": "Crew list", "parents": ["1Boat"]},
    "1PackingDoc": {"id": "1PackingDoc", "name": "Per's packing list"},  # shared with her: no parent of hers
    # 1OldNotes was deleted for good: the API no longer knows it
}


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
    import os

    account = drive.configure(os.environ)
    assert account is not None
    return account


def _pull(**kw: Any) -> tuple[list[dict[str, Any]], dict[str, int]]:
    counts: dict[str, int] = {}
    drafts = list(drive.pull(_config(), counts=counts, timezone="Europe/Oslo", **kw))
    return drafts, counts


def _line(drafts: list[dict[str, Any]], activity: str, file_id: str, hour: str) -> dict[str, Any]:
    (found,) = [
        d
        for d in drafts
        if d["payload"]["extra"]["activity"] == activity
        and d["payload"]["extra"]["file"]["id"] == file_id
        and d["at"].startswith(f"{DAY}T{hour}")
    ]
    return found


# -- registry and configuration -------------------------------------------------------------------


def test_registry_has_drive_as_a_live_adapter_of_tier_1_event_lines() -> None:
    assert adapters.live("drive") is drive
    assert drive.ENV == service_account.ENV == (KEY_ENV, USER_ENV)
    assert (drive.KIND, drive.TIER, drive.SCOPE) == ("event", 1, DRIVE_SCOPE)


def test_configure_is_the_shared_service_account(fake: Fake) -> None:
    assert isinstance(_config(), service_account.Account)
    assert drive.configure({}) is None


# -- the lines ------------------------------------------------------------------------------------


def test_pull_writes_one_line_per_file_per_hour_per_activity_oldest_first(fake: Fake) -> None:
    drafts, counts = _pull()
    assert len(drafts) == LINES
    assert [d["at"] for d in drafts] == sorted(d["at"] for d in drafts)
    assert counts == {
        "skipped_other_activity": 1,
        "skipped_not_a_file": 1,
        "skipped_not_involved": 1,
        "no_folder_path": 4,  # the notes deleted for good, Per's list in no folder of hers
    }
    assert {d["source"] for d in drafts} == {"drive"} and {d["kind"] for d in drafts} == {"event"}
    assert {d["tz"] for d in drafts} == {"Europe/Oslo"}
    assert len({d["payload"]["raw_id"] for d in drafts}) == LINES


def test_a_long_editing_session_is_one_line_with_a_count(fake: Fake) -> None:
    drafts, _ = _pull()
    line = _line(drafts, "edit", "1BudgetSheet", "09")
    extra = line["payload"]["extra"]
    assert extra["count"] == 4 and len(extra["activities"]) == 4
    assert (line["at"], line["end"]) == (_at("09:10:00"), _at("09:50:00"))
    assert line["payload"]["title"] == "Edited Budget 2027 ×4"
    assert line["payload"]["modified_at"] == _at("09:50:00")
    single = _line(drafts, "edit", "1BudgetSheet", "10")
    assert single["payload"]["extra"]["count"] == 1 and single["end"] is None
    assert single["payload"]["title"] == "Edited Budget 2027"


@pytest.mark.parametrize(
    ("activity_name", "file_id", "hour", "title"),
    [
        ("create", "1BudgetSheet", "09", "Created Budget 2027"),
        ("edit", "1BudgetSheet", "10", "Edited Budget 2027"),
        ("rename", "1CrewDoc", "11", "Renamed Crew to Crew list"),
        ("move", "1CrewDoc", "11", "Moved Crew list to Boat"),
        ("share", "1CrewDoc", "11", "Changed sharing of Crew list ×2"),
        ("comment", "1CrewDoc", "14", "Commented on Crew list ×2"),
        ("trash", "1OldNotes", "12", "Trashed Old notes"),
        ("restore", "1OldNotes", "12", "Restored Old notes"),
        ("delete", "1OldNotes", "13", "Deleted Old notes"),
    ],
)
def test_each_activity_is_a_line_titled_by_what_happened(
    fake: Fake, activity_name: str, file_id: str, hour: str, title: str
) -> None:
    drafts, _ = _pull()
    assert _line(drafts, activity_name, file_id, hour)["payload"]["title"] == title


def test_each_activity_carries_what_it_changed(fake: Fake) -> None:
    drafts, _ = _pull()
    assert _line(drafts, "create", "1BudgetSheet", "09")["payload"]["extra"]["created"] == "new"
    assert _line(drafts, "rename", "1CrewDoc", "11")["payload"]["extra"]["renamed"] == {
        "from": "Crew",
        "to": "Crew list",
    }
    moved = _line(drafts, "move", "1CrewDoc", "11")["payload"]["extra"]
    assert moved["moved"] == {"from": ["Inbox"], "to": ["Boat"]} and moved["folder"] == "Boat"
    assert _line(drafts, "comment", "1CrewDoc", "14")["payload"]["extra"]["comments"] == {
        "post:added": 1,
        "post:reply_added": 1,
    }


def test_a_share_says_with_whom_as_the_api_gives_it_and_the_role(fake: Fake) -> None:
    drafts, _ = _pull()
    assert _line(drafts, "share", "1CrewDoc", "11")["payload"]["extra"]["shares"] == [
        {"change": "added", "role": "editor", "with": {"user": OLA}},
        {"change": "added", "role": "commenter", "with": {"group": "crew@example.org"}},
        {"change": "removed", "role": "viewer", "with": {"domain": "example.org"}},
    ]


def test_the_owner_is_marked_owner_and_others_named_as_the_api_names_them(fake: Fake) -> None:
    drafts, _ = _pull()
    session = _line(drafts, "edit", "1BudgetSheet", "09")["payload"]["extra"]
    assert session["actors"] == [{"kind": "owner"}, {"kind": "user", "person_name": OLA}]
    assert session["by_owner"] is True
    others = _line(drafts, "edit", "1BudgetSheet", "15")["payload"]["extra"]
    assert others["actors"] == [{"kind": "user", "person_name": PER}] and others["by_owner"] is False
    assert "people/1000" not in json.dumps(drafts), "the owner is `owner`, never their account id"


def test_every_line_is_tier_1_whoever_acted(fake: Fake) -> None:
    drafts, _ = _pull()
    assert {d["tier"] for d in drafts} == {1}
    assert {d["tier"] for d in drafts if not d["payload"]["extra"]["by_owner"]} == {1}


def test_a_line_names_and_references_the_file_and_never_holds_its_content(fake: Fake) -> None:
    drafts, _ = _pull()
    payload = _line(drafts, "edit", "1BudgetSheet", "09")["payload"]
    assert payload["extra"]["file"] == {
        "id": "1BudgetSheet",
        "name": "Budget 2027",
        "mime_type": SHEET,
        "url": "https://drive.google.com/open?id=1BudgetSheet",
        "path": ["My Drive", "Money"],  # the folders' names, from the metadata scope; never the content
    }
    assert (
        payload["calendar"] == {"id": "google-drive", "name": "Google Drive"} and payload["all_day"] is False
    )
    allowed = set(drive.EXTRA_KEYS)
    for d in drafts:
        assert set(d["payload"]["extra"]) <= allowed, d["payload"]["extra"]
        assert set(d["payload"]) == {
            "schema",
            "raw_id",
            "title",
            "calendar",
            "all_day",
            "modified_at",
            "extra",
        }
    assert "legacyCommentId" not in json.dumps(drafts) and "mentionedUsers" not in json.dumps(drafts)


def test_others_activity_on_others_files_is_left_out_and_the_owners_kept(fake: Fake) -> None:
    drafts, counts = _pull()
    (packing,) = [d for d in drafts if d["payload"]["extra"]["file"]["id"] == "1PackingDoc"]
    assert packing["at"] == _at("17:30:00") and packing["payload"]["extra"]["actors"] == [{"kind": "owner"}]
    assert counts["skipped_not_involved"] == 1


def test_the_hour_still_open_waits_for_the_next_run(fake: Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(drive, "_now", lambda: datetime(2026, 9, 14, 14, 20, tzinfo=UTC))
    drafts, counts = _pull()
    assert max(d["at"] for d in drafts) < _at("14:00:00")
    assert len(drafts) == 9 and counts["held_open_hour"] == 4


# -- what is asked, and how -----------------------------------------------------------------------


def test_the_query_asks_for_the_mapped_actions_unconsolidated_from_since(fake: Fake) -> None:
    _pull(since=_at("12:00:00"))
    first = fake.calls("driveactivity.googleapis.com/v2/activity:query")[0]
    assert first["consolidationStrategy"] == {"none": {}} and first["pageSize"] == drive.PAGE_SIZE
    assert f'time >= "{_at("12:00:00")}"' in first["filter"]
    assert (
        "detail.action_detail_case:(CREATE EDIT MOVE RENAME DELETE RESTORE PERMISSION_CHANGE COMMENT)"
        in (first["filter"])
    )


def test_since_keeps_the_activity_from_then_on(fake: Fake) -> None:
    drafts, _ = _pull(since=_at("12:00:00"))
    assert len(drafts) == 6 and min(d["at"] for d in drafts) == _at("12:00:00")


def test_pull_pages_until_the_last_page_and_reports_each(fake: Fake) -> None:
    pages: list[int] = []
    drafts, _ = _pull(progress=lambda n, _s: pages.append(n))
    calls = fake.calls("driveactivity.googleapis.com/v2/activity:query")
    assert len(calls) == 7 and [c.get("pageToken") for c in calls] == [None, "3", "6", "9", "12", "15", "18"]
    assert pages == [3, 6, 9, 12, 15, 18, 20] and len(drafts) == LINES


def test_pull_backs_off_on_429_and_5xx_and_carries_on(fake: Fake) -> None:
    fake.fail(429, retry_after="3")
    fake.fail(503)
    drafts, _ = _pull()
    assert len(drafts) == LINES and fake.waits == [3.0, 2.0]  # type: ignore[attr-defined]


def test_the_client_only_reads(fake: Fake) -> None:
    _pull()
    assert fake.methods() == {
        ("POST", "oauth2.googleapis.com"),
        ("POST", "driveactivity.googleapis.com"),
        ("GET", "www.googleapis.com"),  # the folders' names, for the path
    }
    assert {c["scope"] for c in fake.assertions} == {DRIVE_SCOPE, METADATA_SCOPE}


def test_watermark_is_the_newest_activity_of_the_line_and_resume_looks_back_a_day(fake: Fake) -> None:
    drafts, _ = _pull()
    line = _line(drafts, "edit", "1BudgetSheet", "09")
    assert drive.watermark(line) == _at("09:50:00")
    assert drive.resume(_config(), _at("09:50:00")) == f"{'2026-09-13'}T09:50:00Z"
    assert drive.group(line) == "edit"


# -- sync: the CLI --------------------------------------------------------------------------------


def _sync(*args: str) -> int:
    try:
        cli.main(["sync", "drive", *args])
    except SystemExit as e:
        return int(e.code or 0)
    return 0


def _state(lb: Logbook) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((lb.root / "state" / "drive.json").read_text(encoding="utf-8"))
    return data


def test_sync_first_run_writes_every_line_and_the_second_none(lb: Logbook, fake: Fake, capsys: Any) -> None:
    assert _sync() == 0
    out = capsys.readouterr().out
    assert f"drive: {LINES} new lines of {LINES} seen from the beginning" in out
    assert "edit: 4 new of 4 seen" in out
    assert "skipped 1 of another activity, 1 not a file, 1 the owner is not part of" in out
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == LINES
    assert _state(lb)["since"] == _at("17:30:00")
    assert _sync() == 0
    out = capsys.readouterr().out
    assert f"drive: 0 new lines of 0 seen since {'2026-09-13'}T17:30:00Z" in out
    assert lb.meta["seq"] == LINES


def test_sync_a_late_activity_in_a_written_hour_is_its_own_line_and_never_counted_twice(
    lb: Logbook, fake: Fake, capsys: Any
) -> None:
    _sync()
    fake.drive.append(activity(_t("09:40:00"), EDIT, BUDGET))  # Google reported it late
    assert _sync() == 0
    assert "drive: 1 new lines of 1 seen" in capsys.readouterr().out
    edits = [
        line
        for line in lb.lines()
        if line["payload"]["extra"]["activity"] == "edit" and line["at"].startswith(f"{DAY}T09")
    ]
    assert sorted(line["payload"]["extra"]["count"] for line in edits) == [1, 4]
    ids = [i for line in edits for i in line["payload"]["extra"]["activities"]]
    assert len(ids) == len(set(ids)) == 5


def test_sync_since_is_used_as_given(lb: Logbook, fake: Fake, capsys: Any) -> None:
    assert _sync("--since", _at("12:00:00")) == 0
    assert f"drive: 6 new lines of 6 seen since {_at('12:00:00')}" in capsys.readouterr().out
    assert _sync("--since", "2026-09-14T00:00:00Z") == 0
    assert "drive: 6 new lines of 6 seen" in capsys.readouterr().out, "the morning, and nothing twice"
    assert lb.meta["seq"] == LINES


def test_sync_dry_run_counts_and_writes_nothing(lb: Logbook, fake: Fake, capsys: Any) -> None:
    assert _sync("--dry-run") == 0
    out = capsys.readouterr().out
    assert f"drive: {LINES} lines from the beginning (dry run, nothing written)" in out
    assert lb.meta["seq"] == 0 and not (lb.root / "state").exists()


def test_sync_without_the_variables_says_which(lb: Logbook, monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.delenv(KEY_ENV, raising=False)
    monkeypatch.setenv(USER_ENV, USER)
    assert _sync() == 2
    assert capsys.readouterr().err == f"sync: drive: set {KEY_ENV}\n"


def test_sync_a_scope_the_delegation_lacks_is_one_line_and_exit_1(
    lb: Logbook, fake: Fake, capsys: Any
) -> None:
    fake.delegated = set()
    assert _sync() == 1
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and err.startswith("sync: drive:") and "domain-wide delegation" in err
    assert lb.meta["seq"] == 0


def test_doctor_shows_sync_drive_configured_and_the_key_checked(lb: Logbook, fake: Fake) -> None:
    import os

    checks = {c.name: c for c in doctor.run(lb, dict(os.environ), installed=lambda _m: True)}
    check = checks["sync:drive"]
    assert check.status == "pass" and f"configured ({KEY_ENV}, {USER_ENV})" in check.detail
    assert "never stored" in check.detail
    assert fake.requests == [], "doctor asks Google nothing"


# -- a dry run and the day's quota ------------------------------------------------------------------------

QUOTA = (
    "Quota exceeded for quota metric 'Queries' and limit 'Queries per day' of service"
    " 'driveactivity.googleapis.com'"
)


def _spent(fake: Fake) -> None:
    """Google's answer once the project's daily quota is used up: 429, RESOURCE_EXHAUSTED."""
    error = {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": QUOTA}
    fake.failures.append((429, {"retry-after": "60"}, json.dumps({"error": error}).encode("utf-8")))


def test_a_dry_run_that_meets_the_days_quota_stops_at_once_on_one_line(
    lb: Logbook, fake: Fake, capsys: Any
) -> None:
    _spent(fake)
    assert _sync("--dry-run") == 1
    out = capsys.readouterr()
    lines = [line for line in out.err.splitlines() if line.strip()]
    assert lines == [f"sync: drive: dry run stopped at the source's limit after 0 lines: HTTP 429: {QUOTA}"]
    assert "dry run, nothing written" not in out.out
    assert fake.waits == [], "nothing waited out"  # type: ignore[attr-defined]
    assert lb.meta["seq"] == 0 and not (lb.root / "state").exists(), "no watermark, no cache"


def test_a_run_that_writes_still_waits_the_limit_out(lb: Logbook, fake: Fake, capsys: Any) -> None:
    _spent(fake)
    assert _sync() == 0
    assert fake.waits == [60.0]  # type: ignore[attr-defined]
    assert f"drive: {LINES} new lines" in capsys.readouterr().out


def test_a_dry_run_stopped_after_some_pages_says_how_far_it_read(
    lb: Logbook, fake: Fake, capsys: Any
) -> None:
    real = fake._activity

    def spent_after_the_first_page(scope: str, params: dict[str, Any]) -> Any:
        if params.get("pageToken"):
            error = {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": QUOTA}
            return service_account.Response(429, {}, json.dumps({"error": error}).encode("utf-8"))
        return real(scope, params)

    fake._activity = spent_after_the_first_page  # type: ignore[method-assign]
    fake.page = 3
    assert _sync("--dry-run") == 1
    err = capsys.readouterr().err
    stop = "sync: drive: dry run stopped at the source's limit after 0 lines, 3 activities read"
    assert err.splitlines()[-1] == f"{stop}: HTTP 429: {QUOTA}", "drive yields nothing before its last page"
    assert fake.waits == [] and not (lb.root / "state").exists()  # type: ignore[attr-defined]
