"""`logbook sync github`: commits, issues, pull requests, reviews and comments, one event/v1 line each.

Every test runs against `tests/github_api.py`, an in-process fake of GitHub's REST API on the
loopback interface serving Ines Nordmann's synthetic account; no test reaches GitHub. The fake
records every request, so the tests hold the client to reading (GET and nothing else), to the cursor
and to the rate limits. The clock the client paces and backs off by is a fake one: a wait is
recorded, never slept.

Which text a line carries, by the profile: `event/v1` (RFC 0009) has `notes`, "the description
body", so a commit's message, an issue's or a pull request's body, a review's and a comment's text
are kept in full, and its tier is 1 whoever wrote the words — "an entry whose notes carry someone
else's words is still tier 1 by default". A tier is where a line may travel, never who wrote it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from github_api import (
    AGENT_FOOTER,
    BOT,
    CREW,
    HARBOUR,
    INES,
    OLA,
    SAIL_PLAN_MESSAGE,
    SAILPLAN,
    TIDES_MESSAGE,
    TOKEN,
    VERSION,
    FakeGitHub,
    account,
    comment,
    commit,
    sha,
)

from logbook import cli
from logbook.contrib import adapters, doctor
from logbook.contrib.adapters import github, github_live
from logbook.core.store import Logbook

TOKEN_ENV = "LOGBOOK_GITHUB_TOKEN"
REPOS_ENV = "LOGBOOK_GITHUB_REPOS"
URL_ENV = "LOGBOOK_GITHUB_URL"
SAIL = "ines-example/sailplan"  # the repo as raw_ids spell it
FIRST_RUN = 17  # 5 commits, 7 issue and pull request lines, 1 review, 4 comments
LAST_SEEN = "2026-03-06T18:00:00Z"  # harbour-notes's one commit: the newest change the run sees


class Clock:
    """The client's clocks: `sleep` records the wait and moves both on, never sleeps."""

    def __init__(self, wall: float) -> None:
        self.t = 1000.0
        self.wall = wall
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def time(self) -> float:
        return self.wall

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds
        self.wall += seconds


@pytest.fixture
def server() -> Any:
    fake = account()
    fake.start()
    try:
        yield fake
    finally:
        fake.stop()


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch, server: FakeGitHub) -> Clock:
    c = Clock(server.now)
    monkeypatch.setattr(github_live, "_clock", c.now)
    monkeypatch.setattr(github_live, "_time", c.time)
    monkeypatch.setattr(github_live, "_sleep", c.sleep)
    return c


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch, server: FakeGitHub, clock: Clock) -> FakeGitHub:
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    monkeypatch.setenv(URL_ENV, server.url)
    monkeypatch.setenv(REPOS_ENV, f"{SAILPLAN}, {HARBOUR}")
    return server


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    _owner(lb, handles=["ines-example"], emails=["ines.nordmann@example.org"])
    return lb


def _owner(lb: Logbook, **aliases: list[str]) -> None:
    data = {"names": [], "emails": [], "phones": [], "handles": [], **aliases}
    (lb.root / "policy" / "owner.json").write_text(json.dumps(data), encoding="utf-8")


def _sync(*args: str) -> int:
    try:
        cli.main(["sync", "github", *args])
    except SystemExit as e:
        return int(e.code or 0)
    return 0


def _lines(lb: Logbook) -> list[dict[str, Any]]:
    return [line for line in lb.lines() if line["source"] == "github"]


def _keyed(lb: Logbook) -> dict[str, dict[str, Any]]:
    return {line["payload"]["raw_id"]: line for line in _lines(lb)}


def _state(lb: Logbook) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((lb.root / "state" / "github.json").read_text(encoding="utf-8"))
    return data


def _commit(label: str) -> str:
    return f"commit/{sha(label)}"


# -- registry and configuration -------------------------------------------------------------------


def test_registry_has_github_as_a_live_adapter() -> None:
    assert adapters.live("github") is github_live
    assert github_live.ENV == (TOKEN_ENV, REPOS_ENV)


def test_configure_needs_the_token_and_the_repos() -> None:
    assert github_live.configure({}) is None
    assert github_live.configure({TOKEN_ENV: TOKEN}) is None
    assert github_live.configure({REPOS_ENV: SAILPLAN}) is None
    config = github_live.configure({TOKEN_ENV: f" {TOKEN} ", REPOS_ENV: SAILPLAN})
    assert config is not None
    assert config.token == TOKEN and config.url == "https://api.github.com"
    assert config.repos == (SAILPLAN,) and not config.every_repo
    assert TOKEN not in repr(config), "the token never reaches a traceback or a log"
    assert adapters.needs(github_live, {TOKEN_ENV: TOKEN}) == REPOS_ENV


def test_repos_are_names_or_the_links_github_copies_and_all_is_every_one() -> None:
    config = github_live.configure(
        {
            TOKEN_ENV: TOKEN,
            REPOS_ENV: f"https://github.example.org/{SAILPLAN}.git,\n{HARBOUR} {SAILPLAN.upper()}",
        }
    )
    assert config is not None and config.repos == (SAILPLAN, HARBOUR), "each once, case aside, in order"
    every = github_live.configure({TOKEN_ENV: TOKEN, REPOS_ENV: "--all"})
    assert every is not None and every.every_repo and every.repos == ()


@pytest.mark.parametrize(
    ("env", "named"),
    [
        ({REPOS_ENV: "sailplan"}, REPOS_ENV),
        ({REPOS_ENV: f"{SAILPLAN}, --all"}, REPOS_ENV),
        ({URL_ENV: "http://api.github.example.org"}, URL_ENV),
        ({URL_ENV: "ftp://localhost"}, URL_ENV),
    ],
)
def test_a_value_the_source_cannot_use_is_one_sentence_naming_the_variable(
    env: dict[str, str], named: str
) -> None:
    with pytest.raises(ValueError, match=named) as e:
        github_live.configure({TOKEN_ENV: TOKEN, REPOS_ENV: SAILPLAN, **env})
    assert "\n" not in str(e.value) and TOKEN not in str(e.value)


def test_the_token_goes_over_https_or_to_this_machine_only() -> None:
    local = github_live.configure({TOKEN_ENV: TOKEN, REPOS_ENV: SAILPLAN, URL_ENV: "http://127.0.0.1:8080/"})
    assert local is not None and local.url == "http://127.0.0.1:8080"
    server = github_live.configure(
        {TOKEN_ENV: TOKEN, REPOS_ENV: SAILPLAN, URL_ENV: "https://github.example.org/api/v3"}
    )
    assert server is not None and server.url == "https://github.example.org/api/v3"


# -- the first run, and the second ------------------------------------------------------------------


def test_first_run_writes_a_line_per_commit_issue_pull_review_and_comment(
    lb: Logbook, fake: FakeGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _sync() == 0
    out = capsys.readouterr().out
    assert f"github: {FIRST_RUN} new lines of {FIRST_RUN} seen from the beginning" in out
    for group, n in (("committed", 5), ("created", 4), ("closed", 2), ("merged", 1), ("reviewed", 1)):
        assert f"  {group}: {n} new of {n} seen" in out
    assert "  commented: 4 new of 4 seen" in out
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == FIRST_RUN
    assert set(_keyed(lb)) == {
        _commit("c1"),
        _commit("c2"),
        _commit("c3"),
        _commit("c4"),
        _commit("h1"),
        f"{SAIL}/issues/1/created",
        f"{SAIL}/issues/1/closed@2026-03-02T08:00:00Z",
        f"{SAIL}/pull/2/created",
        f"{SAIL}/pull/2/merged",
        f"{SAIL}/pull/3/created",
        f"{SAIL}/pull/3/closed@2026-03-05T09:30:00Z",
        f"{SAIL}/issues/4/created",
        f"{SAIL}/issues/comments/970300101",
        f"{SAIL}/issues/comments/970300102",
        f"{SAIL}/issues/comments/970300103",
        f"{SAIL}/pull/2/reviews/970400201",
        f"{SAIL}/pulls/comments/970500301",
    }
    for line in _lines(lb):
        assert (line["kind"], line["tier"], line["end"]) == ("event", 1, None)
        assert line["payload"]["schema"] == "event/v1"
        assert line["payload"]["calendar"] == {"id": "github", "name": "GitHub"}
        assert line["payload"]["all_day"] is False
    assert _state(lb)["since"] == LAST_SEEN
    assert _state(lb)["marks"] == {
        "ines-example/harbour-notes": "2026-03-06T18:00:00Z",
        SAIL: "2026-03-05T16:00:00Z",
    }
    assert _sync() == 0
    out = capsys.readouterr().out
    assert len(_lines(lb)) == FIRST_RUN, "a second run writes nothing it has written"
    assert "github: 0 new lines" in out


def test_dry_run_counts_and_writes_nothing(
    lb: Logbook, fake: FakeGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _sync("--dry-run") == 0
    out = capsys.readouterr().out
    assert f"github: {FIRST_RUN:,} lines from the beginning (dry run, nothing written)" in out
    assert "  committed: 5 seen" in out
    assert _lines(lb) == [] and not (lb.root / "state" / "github.json").exists()


def test_the_client_only_reads_and_says_who_it_is(lb: Logbook, fake: FakeGitHub) -> None:
    assert _sync() == 0
    assert {r.method for r in fake.requests} == {"GET"}
    for r in fake.requests:
        assert r.headers["authorization"] == f"Bearer {TOKEN}"
        assert r.headers["x-github-api-version"] == VERSION
        assert r.headers["accept"] == "application/vnd.github+json"
        assert r.headers["user-agent"].startswith("openlogbook")


# -- the lines --------------------------------------------------------------------------------------


def test_a_commit_holds_its_message_in_full_its_files_and_who_wrote_it(lb: Logbook, fake: FakeGitHub) -> None:
    assert _sync() == 0
    keyed = _keyed(lb)
    first = keyed[_commit("c1")]
    assert first["at"] == "2026-03-01T08:00:00Z"
    p = first["payload"]
    assert p["title"] == "Start the sail plan" and p["notes"] == SAIL_PLAN_MESSAGE
    assert p["modified_at"] == "2026-03-01T08:00:00Z"
    assert p["extra"] == {
        "action": "committed",
        "repo": SAILPLAN,
        "branch": "main",
        "commit": {"sha": sha("c1"), "url": f"https://github.example.org/{SAILPLAN}/commit/{sha('c1')}"},
        "files": 2,
        "actor": {
            "login": "ines-example",
            "id": 970000001,
            "type": "User",
            "name": "Ines Nordmann",
            "role": "owner",
        },
    }
    assert p["organizer"] == {"kind": "handle", "value": "github:ines-example"}
    assert keyed[_commit("c3")]["payload"]["extra"]["files"] == 3, "the files of a commit are paged"
    assert keyed[_commit("h1")]["payload"]["extra"]["branch"] == "trunk"


def test_someone_elses_commit_is_theirs_and_tier_1_all_the_same(lb: Logbook, fake: FakeGitHub) -> None:
    assert _sync() == 0
    line = _keyed(lb)[_commit("c2")]
    assert line["tier"] == 1
    assert line["payload"]["extra"]["actor"]["role"] == "other"
    assert line["payload"]["organizer"] == {"kind": "handle", "value": "github:ola-example"}


def test_a_commit_github_links_to_no_account_is_the_owners_by_the_address(
    lb: Logbook, fake: FakeGitHub
) -> None:
    assert _sync() == 0
    p = _keyed(lb)[_commit("c4")]["payload"]
    assert p["extra"]["actor"] == {"name": "Ines Nordmann", "role": "owner"}
    assert "organizer" not in p
    assert "ines.nordmann@example.org" not in json.dumps(p), (
        "an address is read to tell the owner, never kept"
    )


def test_issues_and_pull_requests_created_closed_merged(lb: Logbook, fake: FakeGitHub) -> None:
    assert _sync() == 0
    keyed = _keyed(lb)
    opened = keyed[f"{SAIL}/issues/1/created"]
    assert opened["at"] == "2026-03-01T12:00:00Z"
    p = opened["payload"]
    assert p["title"] == "Which harbour first?"
    assert p["notes"] == "Drøbak or Hvaler? The wind decides.", "Ola's words, in full, at tier 1"
    assert opened["tier"] == 1
    assert p["extra"]["issue"] == {"number": 1, "url": f"https://github.example.org/{SAILPLAN}/issues/1"}
    assert p["extra"]["labels"] == ["question"]
    assert p["extra"]["actor"]["role"] == "other" and p["organizer"]["value"] == "github:ola-example"
    closed = keyed[f"{SAIL}/issues/1/closed@2026-03-02T08:00:00Z"]
    assert closed["at"] == "2026-03-02T08:00:00Z"
    assert closed["payload"]["extra"]["action"] == "closed"
    assert closed["payload"]["extra"]["actor"]["login"] == "ines-example"
    assert "notes" not in closed["payload"], "the body is on the created line, once"
    merged = keyed[f"{SAIL}/pull/2/merged"]
    assert merged["at"] == "2026-03-03T15:00:00Z"
    extra = merged["payload"]["extra"]
    assert extra["pull"] == {"number": 2, "url": f"https://github.example.org/{SAILPLAN}/pull/2"}
    assert (extra["files"], extra["commits"], extra["base"], extra["head"]) == (3, 1, "main", "feature-2")
    assert extra["actor"]["role"] == "owner"
    assert f"{SAIL}/pull/2/closed@2026-03-03T15:00:00Z" not in keyed, "a merge is not also a close"
    unmerged = keyed[f"{SAIL}/pull/3/closed@2026-03-05T09:30:00Z"]
    assert unmerged["payload"]["extra"]["actor"]["login"] == "ola-example"
    bare = keyed[f"{SAIL}/issues/4/created"]["payload"]
    assert "notes" not in bare and bare["title"] == "Buy a new anchor"


def test_reviews_and_comments_carry_their_text_and_where_they_were_left(
    lb: Logbook, fake: FakeGitHub
) -> None:
    assert _sync() == 0
    keyed = _keyed(lb)
    approved = keyed[f"{SAIL}/pull/2/reviews/970400201"]
    assert approved["at"] == "2026-03-03T14:00:00Z"
    p = approved["payload"]
    assert (p["title"], p["notes"]) == ("Tide table for March", "Looks right.")
    assert p["extra"]["review"] == {
        "id": 970400201,
        "state": "approved",
        "url": f"https://github.example.org/{SAILPLAN}/pull/2#pullrequestreview-970400201",
    }
    assert not any("970400202" in key for key in keyed), "a pending review was never submitted"
    inline = keyed[f"{SAIL}/pulls/comments/970500301"]["payload"]
    assert inline["notes"] == "Check the 14:00 entry." and inline["extra"]["path"] == "tides.md"
    assert inline["extra"]["pull"]["number"] == 2 and inline["extra"]["review"] == {"id": 970400201}
    own = keyed[f"{SAIL}/issues/comments/970300101"]["payload"]
    assert own["title"] == "Which harbour first?" and own["extra"]["issue"]["number"] == 1
    assert own["extra"]["actor"]["role"] == "owner"
    bot = keyed[f"{SAIL}/issues/comments/970300102"]["payload"]
    assert bot["extra"]["actor"] == {"login": BOT["login"], "id": BOT["id"], "type": "Bot", "role": "other"}
    assert "organizer" not in bot, "a bot is no person to meet"
    assert bot["extra"]["pull"]["number"] == 2


def test_an_agents_work_is_flagged_by_its_marker(lb: Logbook, fake: FakeGitHub) -> None:
    assert _sync() == 0
    keyed = _keyed(lb)
    for key in (f"{SAIL}/pull/2/created", f"{SAIL}/pull/2/merged", _commit("c3")):
        assert keyed[key]["payload"]["extra"]["agent"] is True, key
    assert AGENT_FOOTER in keyed[f"{SAIL}/pull/2/created"]["payload"]["notes"]
    assert keyed[_commit("c3")]["payload"]["notes"] == TIDES_MESSAGE
    for key in (_commit("c1"), f"{SAIL}/pull/3/created", f"{SAIL}/issues/1/created"):
        assert "agent" not in keyed[key]["payload"]["extra"], key


@pytest.mark.parametrize(
    ("text", "agent"),
    [
        ("Done.\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)", True),
        ("Generated with Claude Code", True),
        ("_Generated by [Claude Code](https://claude.ai/code)_", True),
        ("Session: https://claude.ai/code/session_01ExampleExampleExample", True),
        ("Fix\n\nClaude-Session: https://claude.ai/code/session_x", True),
        ("Fix\n\nCo-Authored-By: Claude Example <noreply@example.org>", True),
        ("I asked Claude about the code and wrote this myself.", False),
        ("", False),
    ],
)
def test_the_markers_of_an_agents_session(text: str, agent: bool) -> None:
    assert github.is_agent(text) is agent


# -- the owner --------------------------------------------------------------------------------------


def test_without_handles_the_tokens_own_user_is_the_owner_and_the_run_says_so(
    lb: Logbook, fake: FakeGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    _owner(lb)
    assert _sync() == 0
    err = capsys.readouterr().err
    assert "no handles in policy/owner.json" in err and "ines-example" in err
    keyed = _keyed(lb)
    assert keyed[_commit("c1")]["payload"]["extra"]["actor"]["role"] == "owner"
    assert keyed[_commit("c2")]["payload"]["extra"]["actor"]["role"] == "other"
    assert keyed[_commit("c4")]["payload"]["extra"]["actor"] == {"name": "Ines Nordmann"}, "unmarked"


def test_any_listed_handle_is_the_owner_spelt_as_the_owner_likes(lb: Logbook, fake: FakeGitHub) -> None:
    _owner(lb, handles=["@Ola-Example", "github:Ines-Example"])
    assert _sync() == 0
    keyed = _keyed(lb)
    assert keyed[_commit("c1")]["payload"]["extra"]["actor"]["role"] == "owner"
    assert keyed[_commit("c2")]["payload"]["extra"]["actor"]["role"] == "owner"


# -- watermarks, --since, the repos ------------------------------------------------------------------


def test_a_second_run_starts_each_repo_from_its_own_mark_less_the_lookback(
    lb: Logbook, fake: FakeGitHub
) -> None:
    assert _sync() == 0
    fake.requests.clear()
    assert _sync() == 0
    since = {(r.path, r.query.get("since")) for r in fake.requests if "since" in r.query}
    assert (f"/repos/{SAILPLAN}/commits", "2026-02-26T16:00:00Z") in since, "a week before sailplan's mark"
    assert (f"/repos/{HARBOUR}/commits", "2026-02-27T18:00:00Z") in since


def test_a_repo_added_to_the_list_later_is_read_from_its_beginning(
    lb: Logbook, fake: FakeGitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(REPOS_ENV, HARBOUR)
    assert _sync() == 0
    monkeypatch.setenv(REPOS_ENV, f"{HARBOUR},{SAILPLAN}")
    assert _sync() == 0
    assert _commit("c1") in _keyed(lb), "sailplan's history, older than harbour-notes's watermark"


def test_since_reads_every_repo_from_there(lb: Logbook, fake: FakeGitHub) -> None:
    assert _sync("--since", "2026-03-03T00:00:00Z") == 0
    keyed = _keyed(lb)
    assert _commit("c1") not in keyed and _commit("c3") in keyed
    assert f"{SAIL}/issues/1/created" not in keyed, "created before --since"
    assert f"{SAIL}/pull/2/created" in keyed and f"{SAIL}/pull/3/closed@2026-03-05T09:30:00Z" in keyed
    assert f"{SAIL}/issues/comments/970300101" not in keyed


def test_every_repo_the_token_sees_but_the_forks(
    lb: Logbook, fake: FakeGitHub, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(REPOS_ENV, "--all")
    assert _sync() == 0
    assert len(_lines(lb)) == FIRST_RUN
    assert "/user/repos" in fake.paths()
    assert not any(p.startswith(f"/repos/{CREW}/") for p in fake.paths()), "a fork is someone else's history"
    assert "skipped 1 repos that are forks" in capsys.readouterr().out


def test_a_repo_the_token_cannot_read_fails_alone_and_the_watermark_stays(
    lb: Logbook, fake: FakeGitHub, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(REPOS_ENV, f"ines-example/missing, {SAILPLAN}")
    assert _sync() == 1
    err = capsys.readouterr().err
    assert "ines-example/missing" in err and "404" in err
    assert _commit("c1") in _keyed(lb), "the other repos are still read"
    assert not (lb.root / "state" / "github.json").exists(), "the watermark is kept for a retry"


def test_a_repo_with_its_issues_switched_off_gives_its_commits(
    lb: Logbook, fake: FakeGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _sync() == 0
    assert _commit("h1") in _keyed(lb)
    assert "issues switched off" in capsys.readouterr().out


def test_a_known_commit_or_pull_is_never_asked_for_again(lb: Logbook, fake: FakeGitHub) -> None:
    assert _sync() == 0
    fake.requests.clear()
    fake.add_commit(
        SAILPLAN,
        commit(SAILPLAN, "c5", "Reef earlier", "2026-03-07T08:00Z", INES, "Ines", "ines@example.org", 1),
    )
    assert _sync() == 0
    details = [p for p in fake.paths() if p.startswith(f"/repos/{SAILPLAN}/commits/")]
    assert details == [f"/repos/{SAILPLAN}/commits/{sha('c5')}"]
    assert not any(
        p.startswith((f"/repos/{SAILPLAN}/pulls/2", f"/repos/{SAILPLAN}/issues/1"))
        for p in fake.paths()
        if not p.endswith("/reviews")
    )


def test_a_comment_edited_later_is_not_written_twice(lb: Logbook, fake: FakeGitHub) -> None:
    assert _sync() == 0
    edited = fake.comments[SAILPLAN][0]
    edited["body"], edited["updated_at"] = "Drøbak first, then Hvaler.", "2026-03-08T10:00:00Z"
    fake.comments[SAILPLAN].append(comment(SAILPLAN, 970300104, 1, "Agreed.", OLA, "2026-03-08T11:00Z"))
    assert _sync() == 0
    keyed = _keyed(lb)
    assert keyed[f"{SAIL}/issues/comments/970300101"]["payload"]["notes"] == "Drøbak first."
    assert keyed[f"{SAIL}/issues/comments/970300104"]["payload"]["notes"] == "Agreed."


# -- paging and backoff --------------------------------------------------------------------------------


def test_every_list_is_read_page_by_page(lb: Logbook, fake: FakeGitHub) -> None:
    assert _sync() == 0
    pages = {(r.path, r.query.get("page")) for r in fake.requests}
    for path in ("commits", "issues", "issues/comments"):
        assert (f"/repos/{SAILPLAN}/{path}", "2") in pages, path
    assert (f"/repos/{SAILPLAN}/commits/{sha('c3')}", "2") in pages, "a commit's files are paged too"
    assert all(
        r.query.get("per_page") == "100" for r in fake.requests if r.path.endswith(("/commits", "/issues"))
    )


def test_a_next_page_at_another_address_is_never_followed(
    lb: Logbook, fake: FakeGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.next_host = "github.example.org"
    assert _sync() == 1
    err = capsys.readouterr().err
    assert "another address" in err and TOKEN not in err
    assert not (lb.root / "state" / "github.json").exists()


def test_the_secondary_limit_waits_what_retry_after_says(lb: Logbook, fake: FakeGitHub, clock: Clock) -> None:
    fake.throttle[f"/repos/{SAILPLAN}/issues"] = 2
    assert _sync() == 0
    assert clock.sleeps.count(7.0) == 2
    assert len(_lines(lb)) == FIRST_RUN


def test_the_primary_limit_waits_for_its_reset(lb: Logbook, fake: FakeGitHub, clock: Clock) -> None:
    fake.throttle_mode = "primary"
    fake.throttle[f"/repos/{SAILPLAN}/commits"] = 1
    assert _sync() == 0
    assert any(29.0 <= s <= 32.0 for s in clock.sleeps), clock.sleeps
    assert len(_lines(lb)) == FIRST_RUN


def test_a_reset_too_far_off_stops_the_run_on_one_line_and_keeps_the_watermark(
    lb: Logbook, fake: FakeGitHub, clock: Clock, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.throttle_mode, fake.reset_in = "primary", 3600
    fake.throttle[f"/repos/{SAILPLAN}/commits"] = 1
    assert _sync() == 1
    err = capsys.readouterr().err
    assert "rate limit" in err and "the next run carries on" in err and TOKEN not in err
    assert len([line for line in err.splitlines() if line.strip()]) == 1
    assert not (lb.root / "state" / "github.json").exists()


def test_a_server_error_backs_off_doubling(lb: Logbook, fake: FakeGitHub, clock: Clock) -> None:
    fake.throttle_mode = "502"
    fake.throttle[f"/repos/{SAILPLAN}/issues/comments"] = 3
    assert _sync() == 0
    assert [s for s in clock.sleeps if s >= 1.0][:3] == [1.0, 2.0, 4.0]


def test_a_refused_token_is_one_sentence_and_never_the_token(
    lb: Logbook, fake: FakeGitHub, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(TOKEN_ENV, "github_pat_another_synthetic_one")
    assert _sync() == 1
    err = capsys.readouterr().err
    assert "401" in err and TOKEN_ENV in err and "github_pat_another" not in err


# -- doctor and --all ----------------------------------------------------------------------------------


def test_doctor_names_sync_github_by_its_variables_only(lb: Logbook, fake: FakeGitHub) -> None:
    fake.requests.clear()
    checks = {c.name: c for c in doctor.run(lb, {TOKEN_ENV: TOKEN, REPOS_ENV: SAILPLAN})}
    check = checks["sync:github"]
    assert check.status == "pass" and check.detail == f"configured ({TOKEN_ENV}, {REPOS_ENV})"
    assert TOKEN not in check.detail
    assert fake.requests == [], "doctor asks GitHub nothing"


def test_sync_all_runs_github_among_the_quick_sources(
    lb: Logbook, fake: FakeGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    from logbook.commands import sync

    names = [a.NAME for a in sync._all_order(adapters.live_adapters())]
    assert "github" in names and names.index("github") < names.index("immich")
    try:
        cli.main(["sync", "--all"])
    except SystemExit as e:
        assert e.code in (0, None)
    out = capsys.readouterr().out
    assert any(line.split() == ["github", "ok"] for line in out.splitlines())
    assert len(_lines(lb)) == FIRST_RUN


# -- handles are people to review ----------------------------------------------------------------------


def _observed(lb: Logbook) -> dict[tuple[str, str], Any]:
    from logbook.contrib import people_review

    return {row.key: row for row in people_review.observed(lb)}


def test_a_handle_is_an_observed_person_as_a_number_is(lb: Logbook, fake: FakeGitHub) -> None:
    assert _sync() == 0
    rows = _observed(lb)
    ola = rows[("handle", "github:ola-example")]
    assert ola.sources == {"github": 7} and ola.kinds == {"event": 7}
    assert ola.labels == {"Ola Nordmann": 1}, "the name his commit gave, as a contact's name"
    assert ("handle", "github:ines-example") not in rows, "the owner is never their own company"
    assert not any("example-ci" in key[1] for key in rows), "a bot is no person"
    assert ("name", "nordmann ola") not in rows, "one person, keyed by the handle"


def test_handles_listed_after_the_lines_were_written_still_leave_the_owner_out(
    lb: Logbook, fake: FakeGitHub
) -> None:
    _owner(lb)
    assert _sync() == 0
    assert ("handle", "github:ines-example") in _observed(lb), "nothing tells the owner yet"
    _owner(lb, handles=["@ines-example"])
    lb.append("2026-03-09T08:00:00Z", "manual", "note", 2, {"schema": "note/v1", "text": "a synthetic note"})
    assert ("handle", "github:ines-example") not in _observed(lb)


def test_people_review_proposes_a_handle_to_the_person_of_that_name(
    lb: Logbook, fake: FakeGitHub, capsys: pytest.CaptureFixture[str]
) -> None:
    lb.append(
        "2026-01-01T09:00:00Z",
        "ios-contacts",
        "resolution",
        2,
        {
            "schema": "resolution/v1",
            "ref": {"kind": "email", "value": "ola@example.org"},
            "entity": {"type": "person", "id": "019cadd3-6bc0-7dcd-9133-043f5aabf2a9", "registry": "logbook"},
            "label": "Ola Nordmann",
            "method": "exact",
        },
    )
    assert _sync() == 0
    capsys.readouterr()
    try:
        cli.main(["people", "review"])
    except SystemExit as e:
        assert e.code in (0, None)
    out = capsys.readouterr().out
    assert "github:ola-example (Ola Nordmann; event 7) → Ola Nordmann: same name Ola Nordmann" in out
