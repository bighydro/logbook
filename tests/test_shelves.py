"""The Promises, Goals and Agents shelves of `logbook serve` (`shelf_promises`, `shelf_goals`,
`shelf_agents`): what each lists and in what order, what a page above its gate never shows, the empty
shelves, and that no page carries a form. On `shelves_record` (the Oslo persona's goals, promises and
sessions with her own agents); nobody and nothing here exists."""

from __future__ import annotations

import re
import shutil
from datetime import UTC, datetime
from html import unescape
from pathlib import Path

import claude_sessions as cs
import page_text
import pytest
import shelves_record as sr
from library_header import without_shell

from logbook.contrib import promises, serve, shelf_agents, shelf_goals, shelf_promises
from logbook.core.store import Logbook

PAGES = ("/promises", "/goals", "/agents")
GATE = (1, 2)  # a page read through tiers 1 and 2: the tier-3 note and session never on it


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("shelves")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Path, "home", lambda: folder / "home")
        return sr.record(folder, mp).root


@pytest.fixture
def lb(built: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    shutil.copytree(built, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook(root)


def _site(lb: Logbook, tiers: tuple[int, ...] | None = None) -> serve.Site:
    return serve.Site(lb, now=lambda: sr.NOW, tiers=tiers)


def _get(site: serve.Site, target: str) -> tuple[int, str]:
    path, _, query = target.partition("?")
    response = site.respond(path, query)
    return response.status, response.body.decode("utf-8")


def _main(page: str) -> str:
    """The page's main as text, entities read."""
    return page_text.seen(page[page.index("<main>") : page.index("</main>")])


def _hrefs(page: str) -> list[str]:
    return [unescape(h) for h in re.findall(r'href="([^"]*)"', page)]


# -- the Promises shelf -----------------------------------------------------------------------------------


def test_the_promises_are_open_first_then_kept_then_dropped(lb: Logbook) -> None:
    status, page = _get(_site(lb), "/promises")
    text = _main(page)
    assert status == 200
    open_, kept, dropped = text.index("Open"), text.index("Kept"), text.index("Dropped")
    assert open_ < text.index(sr.OPEN) < kept < text.index(sr.KEPT) < dropped < text.index(sr.DROPPED)
    assert text.index(sr.ASKED) < kept  # a request to the owner is open too
    assert "asked of you by Ola Nordmann" in text


def test_a_promise_row_says_who_what_when_and_links_its_line(lb: Logbook) -> None:
    shelf = shelf_promises.read(lb)
    asked = next(r for r in shelf.rows if r.proposal.match.quote == sr.ASKED)
    _status, page = _get(_site(lb), "/promises")
    row = page[page.index(f'<li id="{asked.proposal.id}"') :]
    row = row[: row.index("</li>")]
    assert "Ola Nordmann" in row and "said 2026-03-04" in row
    assert f"/promises/{asked.proposal.id}" in row
    assert f"/day/2026-03-04#l-{asked.proposal.line}" in row  # the evidence: the line on its Day


def test_the_local_model_s_verdict_is_shown_as_the_reader_gives_it(lb: Logbook) -> None:
    shelf = shelf_promises.read(lb)
    judged = next(r for r in shelf.rows if r.proposal.match.quote == sr.OPEN)
    assert judged.proposal.judgement is not None and judged.proposal.judgement.model == sr.JUDGED_MODEL
    verdict = shelf_promises.verdict_text(judged.proposal)
    assert (
        verdict == "due 2026-03-09? · judged 0.9"
    )  # `promises`' own words: the judge's due day, its confidence
    _status, page = _get(_site(lb), "/promises")
    assert verdict in _main(page)
    _status, one = _get(_site(lb), f"/promises/{judged.proposal.id}")
    assert sr.JUDGED_MODEL in _main(one) and "call the yard about the mast" in _main(one)


def test_a_broken_judgement_cache_is_no_verdict_and_no_traceback(lb: Logbook) -> None:
    (lb.root / "policy" / "promises-cache.json").write_bytes(b'{"judgements": {"x": {"confidence": 7}}')
    assert shelf_promises.read_judgements(lb.root) == {}
    (lb.root / "policy" / "promises-cache.json").write_bytes(
        b'{"version": 1, "judgements": {"abc": {"is_commitment": true, "confidence": 2}}}'
    )
    assert shelf_promises.read_judgements(lb.root) == {}
    assert _get(_site(lb), "/promises")[0] == 200


def test_the_shelf_filters_by_person_and_never_lists_an_agent_as_one(lb: Logbook) -> None:
    shelf = shelf_promises.read(lb)
    assert shelf.people == ["Ola Nordmann"]  # the bots and the assistant are agents, never people
    status, page = _get(_site(lb), "/promises?person=Ola Nordmann")
    text = _main(page)
    assert status == 200 and sr.ASKED in text
    assert sr.OPEN not in text and sr.KEPT not in text
    assert "/promises?person=Ola%20Nordmann" in _hrefs(_get(_site(lb), "/promises")[1])


def test_a_promise_page_links_its_transcript_line(lb: Logbook) -> None:
    shelf = shelf_promises.read(lb)
    said = next(r.proposal for r in shelf.rows if r.proposal.match.quote in cs.OWNER_SECOND)
    status, page = _get(_site(lb), f"/promises/{said.id}")
    assert status == 200
    assert f"/day/{said.day}#l-{said.line}" in _hrefs(page)
    assert "the transcript line it was read in" in _main(page)
    assert "the agent assistant" in _main(page)


def test_a_promise_the_record_does_not_hold_is_a_404(lb: Logbook) -> None:
    status, page = _get(_site(lb), "/promises/0123456789abcdef")
    assert status == 404 and "no promise 0123456789abcdef" in page


# -- the Goals shelf --------------------------------------------------------------------------------------


def test_the_goals_are_by_horizon_with_their_latest_review(lb: Logbook) -> None:
    status, page = _get(_site(lb), "/goals")
    text = _main(page)
    assert status == 200
    assert sr.CHAPTER in text and "the yard, the planner, the boat" in text
    life, year, quarter = text.index("Life"), text.index("This year"), text.index("This quarter")
    assert life < text.index(sr.LIFE) < year < text.index(sr.YEAR_REWORDED) < quarter < text.index(sr.QUARTER)
    assert f"{sr.YEAR} " not in text.replace(sr.YEAR_REWORDED, "")  # the standing wording only
    shelf = shelf_goals.read(lb, today=sr.TODAY)
    by_text = {g.text: g for g in shelf.goals}
    quarter_goal = by_text[sr.QUARTER]
    assert quarter_goal.review is not None
    assert (quarter_goal.review.disposition, quarter_goal.review.day) == ("advancing", "2026-03-02")
    assert by_text[sr.YEAR_REWORDED].review is None and "not reviewed yet" in text


def test_a_goal_s_page_is_its_review_thread_newest_first(lb: Logbook) -> None:
    found = sr.ids(lb)
    status, page = _get(_site(lb), f"/goals/{found['quarter']}")
    text = _main(page)
    assert status == 200
    assert text.index(sr.ADVANCING_NOTE) < text.index(sr.STALLED_NOTE)
    assert "stalled" in text and "month" in text


def test_a_goal_is_reached_by_any_line_of_its_chain(lb: Logbook) -> None:
    found = sr.ids(lb)
    status, page = _get(_site(lb), f"/goals/{found['year']}")  # the first wording, superseded
    text = _main(page)
    assert status == 200 and sr.YEAR_REWORDED in text
    assert "Earlier wordings" in text and sr.YEAR in text


def test_a_session_served_a_goal_only_where_a_review_says_so(lb: Logbook) -> None:
    found = sr.ids(lb)
    shelf = shelf_goals.read(lb, today=sr.TODAY)
    served = {g.text: [i for i, _day in g.served] for g in shelf.goals}
    assert served == {sr.LIFE: [], sr.YEAR_REWORDED: [], sr.QUARTER: [found["session"]]}
    _status, page = _get(_site(lb), f"/goals/{found['quarter']}")
    assert shelf_agents.session_path(found["session"], "2026-03-01") in _hrefs(page)
    sessions = shelf_agents.read(lb).sessions
    named = [s for s in sessions if s.served]
    assert [s.line for s in named] == [found["session"]]
    assert named[0].served == ((found["quarter"], sr.QUARTER),)


def test_an_empty_goals_shelf_says_how_to_add_the_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = Logbook.init(tmp_path / "empty", sr.TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(empty.root))
    status, page = _get(_site(empty), "/goals")
    assert status == 200
    assert "logbook goal import ~/goals.txt" in _main(page)
    for target in ("/promises", "/agents"):
        assert _get(_site(empty), target)[0] == 200


def test_a_goal_the_record_does_not_hold_is_a_404(lb: Logbook) -> None:
    status, page = _get(_site(lb), "/goals/not-a-goal")
    assert status == 404 and "no goal not-a-goal" in page


# -- the Agents shelf -------------------------------------------------------------------------------------


def test_the_sessions_are_by_day_the_latest_first(lb: Logbook) -> None:
    status, page = _get(_site(lb), "/agents")
    text = _main(page)
    assert status == 200
    days = re.findall(r"<h2><a href=\"/day/(\d{4}-\d{2}-\d{2})\"", page)
    assert days == sorted(set(days), reverse=True) and "2026-03-01" in days
    for source in ("Claude Code", "Claude", "Telegram"):
        assert source in text


def test_a_session_shows_its_length_the_owner_s_words_and_the_agent_s_apart(lb: Logbook) -> None:
    found = sr.ids(lb)
    session = next(s for s in shelf_agents.read(lb).sessions if s.line == found["session"])
    assert session.source == "claude-code" and session.agent == "Claude Code"
    assert session.summary == "Passage planner for Solvind"  # Claude Code's own summary of it
    assert session.owner == (cs.OWNER_FIRST, cs.OWNER_SECOND)
    assert session.machine == (cs.MACHINE_FIRST, cs.MACHINE_SECOND)
    assert session.minutes == 1 and session.tool_calls == 2
    _status, page = _get(_site(lb), "/agents?day=2026-03-01")
    row = page[page.index(f'id="{shelf_agents.anchor(session.line)}"') :]
    row = unescape(row[: row.index("</li>")])
    mine, theirs = row.index(cs.OWNER_FIRST), row.index(cs.MACHINE_FIRST)
    assert mine < theirs and "machine text" in row[mine:theirs]
    assert '<blockquote class="said machine">' in row
    assert "the agent's summary:" in row and "/goals/" in row


def test_a_telegram_day_is_one_session_and_a_forward_is_not_the_owner_s(lb: Logbook) -> None:
    telegram = [s for s in shelf_agents.read(lb).sessions if s.source == "telegram"]
    assert {s.agent for s in telegram} == {"Nordlys", "Fjordvakt"}
    nordlys = next(s for s in telegram if s.agent == "Nordlys")
    assert len(nordlys.lines) > 1 and nordlys.day == "2026-03-01"
    assert "I'll bring the charts on Friday" not in nordlys.owner  # forwarded from Ola: his words
    assert all("I will check the anchor chain tomorrow" not in t for t in nordlys.machine)
    _status, page = _get(_site(lb), f"/agents?day={nordlys.day}")
    assert all(f'id="{shelf_agents.anchor(i)}"' in page for i in nordlys.lines)  # any message a review names


def test_a_bad_page_or_day_is_a_400(lb: Logbook) -> None:
    assert _get(_site(lb), "/agents?page=0")[0] == 400
    assert _get(_site(lb), "/agents?day=2026-13-01")[0] == 400


# -- the gate --------------------------------------------------------------------------------------------


def test_nothing_above_the_gate_is_on_any_shelf(lb: Logbook) -> None:
    """Read through tiers 1 and 2, the tier-3 note's promise and the tier-3 session are on no page:
    not listed, not counted, not reachable by their own address; the header says tier 2."""
    found = sr.ids(lb)
    every = shelf_promises.read(lb)
    secret = next(r.proposal for r in every.rows if r.proposal.match.quote == sr.SECRET)
    hidden = next(r.proposal for r in every.rows if sr.HIDDEN_WORDS in r.proposal.match.quote)
    assert {r.tier for r in every.rows} >= {3}
    site = _site(lb, GATE)
    for target in (*PAGES, "/agents?day=2026-03-04", f"/goals/{found['quarter']}"):
        status, page = _get(site, target)
        assert status == 200, target
        for word in (sr.SECRET, sr.HIDDEN_WORDS, "I'll pay the yard", found["hidden"], secret.id, hidden.id):
            assert word not in unescape(page), (target, word)
        assert "tier 3" not in _main(page), target
    assert _get(site, f"/promises/{secret.id}")[0] == 404
    assert _get(site, f"/promises/{hidden.id}")[0] == 404
    assert shelf_agents.read(lb, GATE).tier == 2 and shelf_promises.read(lb, GATE).tier == 2


def test_a_close_above_the_gate_does_not_close_the_promise(lb: Logbook) -> None:
    """The task line that kept a promise is tier 2: read through tier 1 alone it is not there, and
    neither is the promise it closed, which is tier 2 itself; at home it is kept."""
    assert [r.section for r in shelf_promises.read(lb, (1,)).rows] == []
    kept = next(r for r in shelf_promises.read(lb).rows if r.proposal.match.quote == sr.KEPT)
    assert kept.section == shelf_promises.KEPT and kept.tier == 2


def test_a_gate_without_tier_two_shows_no_goal_and_says_why(lb: Logbook) -> None:
    status, page = _get(_site(lb, (1,)), "/goals")
    text = _main(page)
    assert status == 200
    for word in (sr.LIFE, sr.QUARTER, sr.CHAPTER, sr.STALLED_NOTE):
        assert word not in text
    assert "tier 2" in text and "goal import" not in text


def test_a_review_above_the_gate_names_no_session(lb: Logbook) -> None:
    """The review naming the session is tier 2; through tier 1 and 3 the session (tier 2) is not read
    either, and the tier-3 session is read but served nothing."""
    sessions = shelf_agents.read(lb, (1, 3)).sessions
    assert [s.tier for s in sessions] == [3] and sessions[0].served == ()


# -- read-only --------------------------------------------------------------------------------------------


def test_no_shelf_page_carries_a_form_and_a_post_is_refused(lb: Logbook) -> None:
    found = sr.ids(lb)
    site = _site(lb)
    promise = shelf_promises.read(lb).rows[0].proposal.id
    for target in (*PAGES, f"/goals/{found['quarter']}", f"/promises/{promise}"):
        status, page = _get(site, target)
        page = without_shell(page)  # the header's one form is Ask, a GET, and it is the doors' own
        assert status == 200 and "<form" not in page and 'method="post"' not in page, target
    before = sorted(p.name for p in (lb.root).rglob("*.jsonl"))
    response = site.write("/goals", {}, "127.0.0.1", None)
    assert response.status in (403, 404, 405)
    assert sorted(p.name for p in (lb.root).rglob("*.jsonl")) == before


def test_the_shelves_join_the_navigation_after_ideas(lb: Logbook) -> None:
    """The shelves are listed behind the gear (`/shelves`, the front page before Today) after Ideas,
    and before Places, as the navigation listed them."""
    _status, nav = _get(_site(lb), "/shelves")
    nav = nav[nav.index("<main>") :]
    assert nav.index('"/ideas"') < nav.index('"/promises"') < nav.index('"/goals"') < nav.index('"/agents"')
    assert nav.index('"/agents"') < nav.index('"/places"')


def test_the_pages_live_outside_serve() -> None:
    """serve.py holds the shelves' routes and dispatch, never their pages."""
    source = Path(serve.__file__).read_text(encoding="utf-8")
    for word in ("No goals yet", "the agent's summary", "asked of you by", "Sessions that served it"):
        assert word not in source
    assert datetime(2026, 3, 20, tzinfo=UTC) <= sr.NOW


# -- the independent review's findings --------------------------------------------------------------------


def test_a_promise_whose_task_is_cancelled_is_dropped(lb: Logbook) -> None:
    report = promises.extract(lb)
    said = next(p for p in report.proposals if p.match.quote == sr.OPEN)
    payload = promises.draft_done(said, "2026-03-10T10:00:00Z", report.extractor)
    payload["status"] = "cancelled"
    lb.append(at="2026-03-10T10:00:00Z", source="manual", kind="task", tier=2, payload=payload)
    row = next(r for r in shelf_promises.read(lb).rows if r.proposal.id == said.id)
    assert row.section == shelf_promises.DROPPED
    kept = next(r for r in shelf_promises.read(lb).rows if r.proposal.match.quote == sr.KEPT)
    assert kept.section == shelf_promises.KEPT  # a task done is kept


def test_the_person_filter_never_keeps_an_agent(lb: Logbook) -> None:
    for name in ("assistant", "Nordlys"):
        status, page = _get(_site(lb), f"/promises?person={name}")
        text = _main(page)
        assert status == 200 and "0 promises" in text
        assert "no promise with anyone of that name" in text


def test_a_verdict_names_the_judgement_apart(lb: Logbook) -> None:
    judged = next(r for r in shelf_promises.read(lb).rows if r.proposal.match.quote == sr.OPEN)
    assert shelf_promises.verdict_text(judged.proposal) == "due 2026-03-09? · judged 0.9"


def test_a_cut_first_line_is_the_owner_s_never_the_agent_s_summary() -> None:
    first = (
        "Plan the passage to Drøbak with the tides, the wind and the ferry times for every day of the week"
    )
    cut = first[:79].rstrip() + "…"  # `claude_code.first_words`
    assert shelf_agents._summary(None, cut, first) is None
    assert shelf_agents._summary(None, "Passage planner for Solvind", first) == "Passage planner for Solvind"
    assert shelf_agents._summary("The provider's own summary", cut, first) == "The provider's own summary"


def test_an_empty_shelf_under_a_gate_says_the_gate_hides_it(lb: Logbook) -> None:
    for target, word in (
        ("/agents", "No session this page reads"),
        ("/promises", "No promise this page reads"),
    ):
        status, page = _get(_site(lb, (1,)), target)
        text = _main(page)
        assert status == 200 and word in text and "tier 1 only" in text
        assert "yet" not in text


def test_a_page_past_the_last_says_so(lb: Logbook) -> None:
    status, page = _get(_site(lb), "/agents?page=99")
    assert status == 200 and "no sessions on page 99" in _main(page) and 'href="/agents"' in page


def test_a_session_s_row_counts_the_tier_of_the_review_that_names_it(lb: Logbook) -> None:
    """A tier-1 bot chat named by a tier-2 review shows the goal's words: its row says tier 2."""
    session = lb.append(
        at="2026-03-07T09:00:00Z",
        source="telegram",
        kind="message",
        tier=1,
        payload={
            "schema": "message/v1",
            "service": "telegram",
            "chat": {"id": "900000001", "type": "direct", "name": "Nordlys"},
            "from_me": True,
            "text": "Log the tide clock test.",
            "extra": {"counterpart": {"kind": "agent", "name": "Nordlys"}},
        },
    )
    quarter = sr.ids(lb)["quarter"]
    lb.append(
        at="2026-03-07T20:00:00Z",
        source="manual",
        kind="review",
        tier=2,
        payload={
            "schema": "review/v1",
            "goal": quarter,
            "disposition": "advancing",
            "period": "day",
            "extra": {"lines": [str(session["id"])]},
        },
    )
    row = next(s for s in shelf_agents.read(lb).sessions if s.line == str(session["id"]))
    assert row.served == ((quarter, sr.QUARTER),) and row.tier == 2
    gated = next(s for s in shelf_agents.read(lb, (1,)).sessions if s.line == str(session["id"]))
    assert gated.served == () and gated.tier == 1


def test_a_long_turn_is_cut_on_the_page_and_whole_in_its_fold() -> None:
    long = "I'll test the planner on Saturday. " * 20
    html = shelf_agents._said([long], "your words", "said")
    assert "…" in html and "the whole turn" in html and unescape(html).count(long.strip()) == 1
    folded = shelf_agents._said([long], "the agent's words", "said machine", folded=True)
    assert unescape(folded).count(long.strip()) == 1


def test_a_grown_session_whose_newer_line_is_retracted_stands_again(lb: Logbook) -> None:
    found = sr.ids(lb)
    with lb.index() as idx:
        old = idx.by_id(found["session"])
    assert old is not None
    newer = lb.append(
        at=str(old["at"]),
        source="claude-code",
        kind="transcript",
        tier=2,
        payload={
            **old["payload"],
            "raw_id": f"{old['payload']['raw_id']}:v2",
            "supersedes": found["session"],
        },
    )
    lines = {s.line for s in shelf_agents.read(lb).sessions}
    assert str(newer["id"]) in lines and found["session"] not in lines
    lb.retract(int(newer["seq"]), reason="imported twice")
    lines = {s.line for s in shelf_agents.read(lb).sessions}
    assert found["session"] in lines and str(newer["id"]) not in lines


def test_the_shelves_lists_carry_a_tag_and_the_goals_move_with_the_day(lb: Logbook) -> None:
    site = _site(lb)
    for target in PAGES:
        assert site.respond(target, "").etag is not None, target
    later = serve.Site(lb, now=lambda: datetime(2026, 12, 31, 12, tzinfo=UTC))
    assert later.respond("/goals", "").etag != site.respond("/goals", "").etag
