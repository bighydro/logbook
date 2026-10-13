"""`logbook sync notion`: what happened in Notion, one event/v1 line per page and day, never a copy.

Every test runs against `tests/notion_api.py`, an in-process fake of Notion's API on the loopback
interface serving Ines Nordmann's synthetic workspace; no test reaches Notion. The fake records
every request, so the tests hold the client to reading (GET, and POST only to search), to the
rate limit and to the cursor. The clock the client paces and backs off by is a fake one: a wait is
recorded, never slept.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from notion_api import (
    BOATS,
    BOT,
    COLUMN,
    FERRY,
    IDEAS,
    INES,
    OLA,
    OLD_NOTES,
    PACKING,
    RESEARCH,
    SAIL_PLAN,
    SAIL_PLAN_TEXT,
    TASKS,
    TOKEN,
    UNSHARED,
    VERSION,
    FakeNotion,
    page,
    parent_of,
    workspace,
)

from logbook import cli
from logbook.contrib import adapters, doctor
from logbook.contrib.adapters import notion
from logbook.core.store import Logbook

TOKEN_ENV = "LOGBOOK_NOTION_TOKEN"
ROOTS_ENV = "LOGBOOK_NOTION_ROOTS"
OWNER_ENV = "LOGBOOK_NOTION_OWNER_ID"
URL_ENV = "LOGBOOK_NOTION_URL"
FIRST_RUN = 11  # Old notes 1, Boats 1, Research 2, Packing list 1, the ferry 2, Sail plan 2, Ideas 2
NEWEST = "2026-03-02T11:00:00Z"  # Ideas, archived: the newest edit in the workspace


class Clock:
    """The client's clock: `sleep` records the wait and moves time on, never sleeps."""

    def __init__(self) -> None:
        self.t = 1000.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    c = Clock()
    monkeypatch.setattr(notion, "_clock", c.now)
    monkeypatch.setattr(notion, "_sleep", c.sleep)
    return c


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch, clock: Clock) -> Any:
    server = workspace()
    server.start()
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    monkeypatch.setenv(URL_ENV, server.url)
    monkeypatch.setenv(OWNER_ENV, INES)
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    return lb


def _sync(*args: str) -> int:
    try:
        cli.main(["sync", "notion", *args])
    except SystemExit as e:
        return int(e.code or 0)
    return 0


def _lines(lb: Logbook) -> list[dict[str, Any]]:
    return [line for line in lb.lines() if line["source"] == "notion"]


def _keyed(lb: Logbook) -> dict[str, dict[str, Any]]:
    return {line["payload"]["raw_id"]: line for line in _lines(lb)}


def _state(lb: Logbook) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((lb.root / "state" / "notion.json").read_text(encoding="utf-8"))
    return data


def _key(page_id: str, day: str, action: str) -> str:
    return f"{page_id}/{day}/{action}"


def _digest(*paragraphs: str) -> str:
    return hashlib.sha256("\n".join(paragraphs).encode("utf-8")).hexdigest()


# -- registry and configuration -------------------------------------------------------------------


def test_registry_has_notion_as_a_live_adapter_only() -> None:
    assert adapters.live("notion") is notion
    assert "notion" not in [a.NAME for a in adapters.file_adapters()]
    assert notion.ENV == (TOKEN_ENV,), "the token is the one required variable; the others are read beside it"


def test_configure_needs_the_token_and_reads_the_rest_beside_it() -> None:
    assert notion.configure({}) is None
    assert notion.configure({ROOTS_ENV: BOATS}) is None
    config = notion.configure({TOKEN_ENV: f"  {TOKEN} "})
    assert config is not None
    assert config.token == TOKEN and config.url == "https://api.notion.com/v1"
    assert config.roots == () and config.owner_id is None
    assert TOKEN not in repr(config), "the token never reaches a traceback or a log"


def test_roots_are_ids_or_the_links_notion_copies() -> None:
    bare = BOATS.replace("-", "")
    config = notion.configure(
        {
            TOKEN_ENV: TOKEN,
            ROOTS_ENV: f"https://www.notion.so/ines/Boats-{bare}?pvs=4, {TASKS.upper()}\n{bare}",
            OWNER_ENV: INES.replace("-", ""),
        }
    )
    assert config is not None
    assert config.roots == (BOATS, TASKS), "dashed, lower case, each once, in the order given"
    assert config.owner_id == INES


@pytest.mark.parametrize(
    ("env", "named"),
    [
        ({ROOTS_ENV: "Boats"}, ROOTS_ENV),
        ({OWNER_ENV: "ines"}, OWNER_ENV),
        ({URL_ENV: "http://api.example.org/v1"}, URL_ENV),
        ({URL_ENV: "ftp://localhost/v1"}, URL_ENV),
    ],
)
def test_a_value_the_source_cannot_use_is_one_sentence_naming_the_variable(
    env: dict[str, str], named: str
) -> None:
    with pytest.raises(ValueError, match=named) as e:
        notion.configure({TOKEN_ENV: TOKEN, **env})
    assert "\n" not in str(e.value) and TOKEN not in str(e.value)


def test_the_token_goes_over_https_or_to_this_machine_only() -> None:
    config = notion.configure({TOKEN_ENV: TOKEN, URL_ENV: "http://127.0.0.1:8080/v1/"})
    assert config is not None and config.url == "http://127.0.0.1:8080/v1"
    config = notion.configure({TOKEN_ENV: TOKEN, URL_ENV: "https://notion-proxy.example.org/v1"})
    assert config is not None and config.url == "https://notion-proxy.example.org/v1"


# -- the first run, and the second ------------------------------------------------------------------


def test_first_run_writes_every_page_and_day_and_the_second_none(
    lb: Logbook, fake: FakeNotion, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _sync() == 0
    out = capsys.readouterr().out
    assert f"notion: {FIRST_RUN} new lines of {FIRST_RUN} seen from the beginning" in out
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == FIRST_RUN
    assert set(_keyed(lb)) == {
        _key(OLD_NOTES, "2025-12-01", "created"),
        _key(BOATS, "2026-02-03", "created"),
        _key(RESEARCH, "2026-02-01", "created"),
        _key(RESEARCH, "2026-02-20", "edited"),
        _key(PACKING, "2026-03-02", "created"),
        _key(FERRY, "2026-03-01", "created"),
        _key(FERRY, "2026-03-02", "edited"),
        _key(SAIL_PLAN, "2026-03-01", "created"),
        _key(SAIL_PLAN, "2026-03-02", "edited"),
        _key(IDEAS, "2026-02-10", "created"),
        _key(IDEAS, "2026-03-02", "archived"),
    }
    assert _state(lb)["since"] == NEWEST
    assert _sync() == 0
    out = capsys.readouterr().out
    assert "notion: 0 new lines of 0 seen since 2026-03-02T09:00:00Z" in out, "a lookback of two hours"
    assert lb.meta["seq"] == FIRST_RUN and _state(lb)["since"] == NEWEST


def test_a_line_is_an_event_with_a_reference_never_a_copy(lb: Logbook, fake: FakeNotion) -> None:
    assert _sync() == 0
    line = _keyed(lb)[_key(SAIL_PLAN, "2026-03-02", "edited")]
    assert line["kind"] == "event" and line["tier"] == 1 and line["end"] is None
    assert line["at"] == "2026-03-02T10:15:00Z" and line["tz"] == "Europe/Oslo"
    payload = line["payload"]
    assert payload["schema"] == "event/v1"
    assert payload["title"] == "Sail plan"
    assert payload["calendar"] == {"id": "notion", "name": "Notion"} and payload["all_day"] is False
    assert payload["modified_at"] == "2026-03-02T10:15:00Z"
    extra = payload["extra"]
    assert extra["action"] == "edited"
    assert extra["page"] == {
        "id": SAIL_PLAN,
        "url": f"https://www.notion.so/Sail-plan-{SAIL_PLAN.replace('-', '')}",
    }
    assert extra["path"] == ["Research", "Boats"]
    assert extra["parent"] == {"type": "page", "id": BOATS}
    assert extra["body"] == {
        "sha256": _digest("Plan", *SAIL_PLAN_TEXT),
        "bytes": len("\n".join(("Plan", *SAIL_PLAN_TEXT)).encode("utf-8")),
        "media_type": "text/plain",
        "words": 17,
    }
    assert "path" not in extra["body"], "a digest of text the record does not hold: no path (SPEC §1.1)"


def test_no_line_holds_the_body_a_contact_detail_or_a_link_that_opens_the_page(
    lb: Logbook, fake: FakeNotion
) -> None:
    assert _sync() == 0
    text = json.dumps(_lines(lb), ensure_ascii=False)
    for never in (
        *SAIL_PLAN_TEXT,
        "Notes on the boats we looked at",
        "Oilskins",
        "Compare the two crossings",
        "Crew list",  # a child page's title is its own line's, never part of this body
        "07700 900123",
        "ask Ola about the car",
        "example.org",  # the people's addresses, their avatars, the public link
        "files.example.org",
        "public_url",
        "⛵",
        "Cost",  # a number, a person, a phone, text: never among the properties a line carries
        "Assignee",
        "Phone",
    ):
        assert never not in text, never


def test_an_edit_on_the_day_a_page_was_made_is_the_created_line(lb: Logbook, fake: FakeNotion) -> None:
    """Boats was made and edited on 3 February: one line, `created`, holding the page as it was then."""
    assert _sync() == 0
    lines = [line for line in _lines(lb) if line["payload"]["extra"]["page"]["id"] == BOATS]
    assert [line["payload"]["raw_id"] for line in lines] == [_key(BOATS, "2026-02-03", "created")]
    (line,) = lines
    assert line["at"] == "2026-02-03T08:00:00Z" and line["payload"]["modified_at"] == "2026-02-03T15:30:00Z"
    assert line["payload"]["extra"]["body"]["words"] == 7


def test_a_created_line_on_another_day_than_the_last_edit_holds_no_body(
    lb: Logbook, fake: FakeNotion
) -> None:
    """The body as it is now is not the body on the day the page was made: it goes on the edit's line."""
    assert _sync() == 0
    created = _keyed(lb)[_key(SAIL_PLAN, "2026-03-01", "created")]
    assert created["at"] == "2026-03-01T07:00:00Z"
    assert "body" not in created["payload"]["extra"] and "properties" not in created["payload"]["extra"]
    assert created["payload"]["extra"]["actor"]["role"] == "owner", "Ines made it"


def test_the_day_is_the_records_local_day(lb: Logbook, fake: FakeNotion) -> None:
    """23:30 UTC on 1 March is half past midnight on 2 March in Oslo."""
    assert _sync() == 0
    line = _keyed(lb)[_key(PACKING, "2026-03-02", "created")]
    assert line["at"] == "2026-03-01T23:30:00Z"
    assert line["payload"]["extra"]["path"] == ["Research"], "a column block has no title of its own"
    assert line["payload"]["extra"]["parent"] == {"type": "block", "id": COLUMN}


# -- edits, rows, people, moves, archival --------------------------------------------------------------


def test_a_page_edited_twice_on_one_day_is_one_line(
    lb: Logbook, fake: FakeNotion, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _sync() == 0
    fake.write(SAIL_PLAN, "Plan", *SAIL_PLAN_TEXT, "Back by Sunday evening.")
    fake.edit(SAIL_PLAN, "2026-03-03T09:00Z")
    assert _sync() == 0
    assert "notion: 1 new lines of 1 seen" in capsys.readouterr().out
    fake.edit(SAIL_PLAN, "2026-03-03T14:00Z")
    assert _sync() == 0
    assert "notion: 0 new lines of 1 seen" in capsys.readouterr().out
    edits = [k for k in _keyed(lb) if k.startswith(f"{SAIL_PLAN}/2026-03-03/")]
    assert edits == [_key(SAIL_PLAN, "2026-03-03", "edited")]
    line = _keyed(lb)[edits[0]]
    assert line["payload"]["extra"]["body"]["words"] == 21
    assert line["payload"]["extra"]["body"]["words_delta"] == 4, "against the page's previous line"
    assert _state(lb)["since"] == "2026-03-03T14:00:00Z"


def test_a_rows_status_change_carries_the_property_old_and_new(lb: Logbook, fake: FakeNotion) -> None:
    assert _sync() == 0
    first = _keyed(lb)[_key(FERRY, "2026-03-02", "edited")]["payload"]["extra"]
    assert first["properties"] == {
        "Done": False,
        "Due": {"start": "2026-03-05", "end": None},
        "Priority": "High",
        "Status": "Doing",
        "Tags": ["travel"],
    }
    assert "changed" not in first, "nothing in the record to compare with"
    assert first["path"] == ["Tasks"] and first["parent"] == {"type": "database", "id": TASKS}
    fake.set_status(FERRY, "Done", "2026-03-03T08:00Z", by=OLA)
    assert _sync() == 0
    line = _keyed(lb)[_key(FERRY, "2026-03-03", "edited")]
    extra = line["payload"]["extra"]
    assert extra["changed"] == [{"name": "Status", "old": "Doing", "new": "Done"}]
    assert extra["properties"]["Status"] == "Done"
    assert extra["actor"] == {"id": OLA, "name": "Ola Nordmann", "type": "person", "role": "other"}


def test_the_actor_is_marked_owner_or_other_and_the_tier_never_follows_it(
    lb: Logbook, fake: FakeNotion
) -> None:
    assert _sync() == 0
    keyed = _keyed(lb)
    mine = keyed[_key(SAIL_PLAN, "2026-03-01", "created")]["payload"]["extra"]["actor"]
    theirs = keyed[_key(SAIL_PLAN, "2026-03-02", "edited")]["payload"]["extra"]["actor"]
    assert mine == {"id": INES, "name": "Ines Nordmann", "type": "person", "role": "owner"}
    assert theirs == {"id": OLA, "name": "Ola Nordmann", "type": "person", "role": "other"}
    assert {line["tier"] for line in _lines(lb)} == {1}, "where a line may travel, not who wrote it"


def test_without_the_variable_the_tokens_own_user_is_the_owner(
    lb: Logbook, fake: FakeNotion, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(OWNER_ENV)
    fake.me_owner = {"type": "user", "user": {"object": "user", "id": INES}}
    assert _sync() == 0
    roles = {
        line["payload"]["extra"]["actor"]["id"]: line["payload"]["extra"]["actor"]["role"]
        for line in _lines(lb)
    }
    assert roles == {INES: "owner", OLA: "other"}


def test_a_workspace_integration_without_the_variable_marks_no_one_and_says_so(
    lb: Logbook, fake: FakeNotion, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(OWNER_ENV)
    assert _sync("--dry-run") == 0
    err = capsys.readouterr().err
    assert (
        f"no owner known; the people who acted: Ines Nordmann ({INES}), Ola Nordmann ({OLA}); set {OWNER_ENV}"
        " to yours"
    ) in err, "a dry run tells the owner their id before anything is written"
    assert _sync() == 0
    assert all("role" not in line["payload"]["extra"]["actor"] for line in _lines(lb))
    out = capsys.readouterr().out
    assert f"{FIRST_RUN} with the actor marked neither owner nor other (set {OWNER_ENV})" in out


def test_an_integration_that_may_not_read_people_names_them_by_id(
    lb: Logbook, fake: FakeNotion, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.users_forbidden = True
    assert _sync() == 0
    actors = [line["payload"]["extra"]["actor"] for line in _lines(lb)]
    assert {a["id"] for a in actors} == {INES, OLA} and not any("name" in a for a in actors)
    assert {a["role"] for a in actors} == {"owner", "other"}
    assert f"{FIRST_RUN} with the actor named by id only" in capsys.readouterr().out
    asked = [r.path for r in fake.requests if r.path.startswith("/v1/users/") and r.path != "/v1/users/me"]
    assert len(asked) == 1, "asked once, then never again in the run"


def test_a_bot_is_another_actor(lb: Logbook, fake: FakeNotion) -> None:
    fake.edit(OLD_NOTES, "2026-03-04T10:00Z", by=BOT)
    assert _sync() == 0
    actor = _keyed(lb)[_key(OLD_NOTES, "2026-03-04", "edited")]["payload"]["extra"]["actor"]
    assert actor == {"id": BOT, "name": "Importer", "type": "bot", "role": "other"}


def test_a_moved_page_says_where_it_was(
    lb: Logbook, fake: FakeNotion, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _sync() == 0
    fake.edit(SAIL_PLAN, "2026-03-03T12:00Z", parent=parent_of("page", RESEARCH))
    assert _sync() == 0
    line = _keyed(lb)[_key(SAIL_PLAN, "2026-03-03", "moved")]
    extra = line["payload"]["extra"]
    assert extra["action"] == "moved"
    assert extra["path"] == ["Research"] and extra["parent"] == {"type": "page", "id": RESEARCH}
    assert extra["moved_from"] == {"parent": {"type": "page", "id": BOATS}, "path": ["Research", "Boats"]}
    capsys.readouterr()
    assert _sync() == 0
    assert "notion: 0 new lines of 0 seen" in capsys.readouterr().out, "a move is said once"


def test_archival_is_a_line_and_said_once(
    lb: Logbook, fake: FakeNotion, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _sync() == 0
    ideas = _keyed(lb)[_key(IDEAS, "2026-03-02", "archived")]
    assert ideas["at"] == "2026-03-02T11:00:00Z" and ideas["payload"]["extra"]["action"] == "archived"
    fake.edit(BOATS, "2026-03-04T20:00Z", archived=True, in_trash=True)
    assert _sync() == 0
    assert "notion: 1 new lines of 1 seen" in capsys.readouterr().out
    assert _keyed(lb)[_key(BOATS, "2026-03-04", "archived")]["payload"]["extra"]["path"] == ["Research"]
    assert _sync() == 0
    assert "notion: 0 new lines" in capsys.readouterr().out


def test_a_page_whose_parent_is_not_shared_has_the_path_it_can_see(lb: Logbook, fake: FakeNotion) -> None:
    lone = "0000000c-0000-4000-8000-00000000000c"
    fake.pages[lone] = page(
        lone, "Shared alone", parent_of("page", UNSHARED), "2026-03-02T12:00Z", "2026-03-02T12:00Z"
    )
    assert _sync() == 0
    extra = _keyed(lb)[_key(lone, "2026-03-02", "created")]["payload"]["extra"]
    assert extra["path"] == [] and extra["parent"] == {"type": "page", "id": UNSHARED}


# -- --since, --dry-run, roots ------------------------------------------------------------------------


def test_since_is_used_as_given(lb: Logbook, fake: FakeNotion, capsys: pytest.CaptureFixture[str]) -> None:
    assert _sync("--since", "2026-03-02T00:00:00Z") == 0
    assert "notion: 3 new lines of 3 seen since 2026-03-02T00:00:00Z" in capsys.readouterr().out
    assert set(_keyed(lb)) == {
        _key(FERRY, "2026-03-02", "edited"),
        _key(SAIL_PLAN, "2026-03-02", "edited"),
        _key(IDEAS, "2026-03-02", "archived"),
    }
    searched = [r for r in fake.requests if r.path == "/v1/search"]
    assert len(searched) == 2, "the walk stops at the first page edited before --since"


def test_dry_run_writes_nothing(lb: Logbook, fake: FakeNotion, capsys: pytest.CaptureFixture[str]) -> None:
    assert _sync("--dry-run") == 0
    out = capsys.readouterr().out
    assert f"notion: {FIRST_RUN} lines from the beginning (dry run, nothing written)" in out
    assert lb.meta["seq"] == 0 and not (lb.root / "state").exists()


def test_roots_limit_the_pages_to_those_under_them(
    lb: Logbook, fake: FakeNotion, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(ROOTS_ENV, f"https://www.notion.so/Boats-{BOATS.replace('-', '')}")
    assert _sync() == 0
    assert set(_keyed(lb)) == {
        _key(BOATS, "2026-02-03", "created"),
        _key(SAIL_PLAN, "2026-03-01", "created"),
        _key(SAIL_PLAN, "2026-03-02", "edited"),
    }
    assert "skipped 5 outside LOGBOOK_NOTION_ROOTS" in capsys.readouterr().out


def test_a_database_root_keeps_its_rows(
    lb: Logbook, fake: FakeNotion, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ROOTS_ENV, TASKS)
    assert _sync() == 0
    assert set(_keyed(lb)) == {_key(FERRY, "2026-03-01", "created"), _key(FERRY, "2026-03-02", "edited")}


# -- the API: reading only, the cursor, the rate limit --------------------------------------------------


def test_the_client_only_reads_and_names_its_api_version(lb: Logbook, fake: FakeNotion) -> None:
    assert _sync() == 0
    assert {method for method, _route in fake.methods()} <= {"GET", "POST"}
    assert {route for method, route in fake.methods() if method == "POST"} == {"/v1/search"}
    assert all(r.headers.get("notion-version") == VERSION for r in fake.requests)
    assert all(TOKEN not in r.path and TOKEN not in json.dumps(r.query) for r in fake.requests)


def test_the_walk_follows_the_cursor(lb: Logbook, fake: FakeNotion) -> None:
    """The fake serves two results a page: seven pages are four searches, Sail plan's body two pages."""
    assert _sync() == 0
    searched = [r.body for r in fake.requests if r.path == "/v1/search"]
    assert len(searched) == 4
    assert searched[0]["sort"] == {"direction": "descending", "timestamp": "last_edited_time"}
    assert searched[0]["filter"] == {"property": "object", "value": "page"}
    assert "start_cursor" not in searched[0]
    assert all(body.get("start_cursor") for body in searched[1:])
    pages = [r.query for r in fake.requests if r.path == f"/v1/blocks/{SAIL_PLAN}/children"]
    assert len(pages) == 2 and "start_cursor" not in pages[0] and pages[1]["start_cursor"]


def test_the_client_paces_itself_under_three_requests_a_second(
    lb: Logbook, fake: FakeNotion, clock: Clock
) -> None:
    started = clock.now()
    assert _sync() == 0
    n = len(fake.requests)
    assert n > 10
    assert clock.now() - started >= (n - 1) / 3 - 1e-9, "never faster than Notion's average of three a second"


def test_a_429_is_waited_out_as_retry_after_says(
    lb: Logbook, fake: FakeNotion, clock: Clock, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.throttle["/v1/search"] = 2
    assert _sync() == 0
    assert clock.sleeps.count(7.0) == 2
    assert f"notion: {FIRST_RUN} new lines" in capsys.readouterr().out


def test_a_429_without_retry_after_backs_off_doubling(lb: Logbook, fake: FakeNotion, clock: Clock) -> None:
    fake.retry_after = "soon"
    fake.throttle["/v1/users/me"] = 3
    assert _sync() == 0
    waits = [s for s in clock.sleeps if s >= 1]
    assert waits[:3] == [1.0, 2.0, 4.0]


def test_a_server_error_is_asked_again_after_a_wait(lb: Logbook, fake: FakeNotion, clock: Clock) -> None:
    fake.throttle_status, fake.retry_after = 502, "1"
    fake.throttle[f"/v1/blocks/{SAIL_PLAN}/children"] = 2
    assert _sync() == 0
    assert [s for s in clock.sleeps if s >= 1] == [1.0, 2.0], "a 502's Retry-After is not Notion's to give"
    assert _keyed(lb)[_key(SAIL_PLAN, "2026-03-02", "edited")]["payload"]["extra"]["body"]["words"] == 17


def test_a_rate_limit_that_does_not_lift_stops_the_run_on_one_line(
    lb: Logbook, fake: FakeNotion, clock: Clock, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.throttle["/v1/search"] = 1000
    assert _sync() == 1
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and err.startswith("sync: notion:") and "429" in err
    assert len([r for r in fake.requests if r.path == "/v1/search"]) == notion.RETRIES + 1
    assert lb.meta["seq"] == 0 and not (lb.root / "state").exists()


def test_a_refused_token_is_one_line_that_never_holds_it(
    lb: Logbook, fake: FakeNotion, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(TOKEN_ENV, "ntn_another_synthetic_token")
    assert _sync() == 1
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "refused the token (401)" in err and "ntn_" not in err
    assert lb.meta["seq"] == 0


def test_a_closed_port_is_one_line(
    lb: Logbook, fake: FakeNotion, clock: Clock, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.stop()  # the fixture's own stop finds the server already stopped, which is no error
    assert _sync() == 1
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "Notion did not answer" in err
    assert lb.meta["seq"] == 0


def test_sync_without_the_token_says_which_variable(
    lb: Logbook, fake: FakeNotion, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(TOKEN_ENV)
    assert _sync() == 2
    assert capsys.readouterr().err == f"sync: notion: set {TOKEN_ENV}\n"
    assert not fake.requests


# -- doctor, sources, sync --all ------------------------------------------------------------------------


def test_doctor_shows_sync_notion_by_name_only_and_asks_notion_nothing(lb: Logbook, fake: FakeNotion) -> None:
    checks = {c.name: c for c in doctor.run(lb, {}, installed=lambda _m: True)}
    assert "sync:notion" not in checks
    env = {TOKEN_ENV: TOKEN, ROOTS_ENV: BOATS}
    checks = {c.name: c for c in doctor.run(lb, env, installed=lambda _m: True)}
    assert checks["sync:notion"].status == "pass"
    assert checks["sync:notion"].detail == f"configured ({TOKEN_ENV})"
    checks = {c.name: c for c in doctor.run(lb, {ROOTS_ENV: BOATS}, installed=lambda _m: True)}
    assert "sync:notion" not in checks, "the token is the variable that says the source is used"
    assert not fake.requests, "doctor makes no call to Notion"


def test_sources_lists_notion_as_live(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(["doctor", "sources"])
    rows = {line.split()[0]: line for line in capsys.readouterr().out.splitlines() if line.strip()}
    assert rows["notion"].split()[1] == "live"


def test_sync_all_runs_notion_among_the_quick_sources(
    lb: Logbook, fake: FakeNotion, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from logbook.commands import sync

    order = [a.NAME for a in sync._all_order(adapters.live_adapters())]
    assert "notion" in order and order.index("notion") < order.index("immich")
    for adapter in adapters.live_adapters():
        if adapter.NAME != "notion":
            for name in adapter.ENV:
                monkeypatch.delenv(name, raising=False)
    try:
        cli.main(["sync", "--all"])
    except SystemExit as e:
        assert e.code == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert f"notion: {FIRST_RUN} new lines of {FIRST_RUN} seen" in out
    assert any(line.split() == ["notion", "ok"] for line in out.splitlines())
