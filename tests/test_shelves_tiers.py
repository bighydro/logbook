"""The tier gate of the Promises, Goals and Agents shelves (`shelf_promises`, `shelf_goals`,
`shelf_agents`), path by path: a page read through a gate never shows a line above it, not as text,
not in a link, a `title` attribute, a count or the people filter, not by its id guessed; and what is
derived (a close, a disposition, a review, a chain of wordings, a session a review names) rests on
lines the gate reads, or is not there. The header's tier is the highest tier actually read. On small
records built here and on `shelves_record` (the Oslo persona); nobody and nothing here exists."""

from __future__ import annotations

import json
import re
import shutil
from html import unescape
from pathlib import Path

import page_text
import pytest
import shelves_record as sr

from logbook.contrib import promises, serve, shelf_agents, shelf_goals, shelf_promises
from logbook.core import signing
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
TODAY = "2026-03-20"
GATE = (1, 2)
CLAUDE = {"kind": "agent", "name": "Claude Code", "ref": {"kind": "provider_id", "value": "claude-code"}}
BOT = {"kind": "agent", "name": "Nordlys", "ref": {"kind": "provider_id", "value": "telegram:900000001"}}
KARI = {"name": "Kari Nordmann", "email": "kari.nordmann@example.org"}
PROMISE = "I'll send Ola the harbour map by Friday."
SECRET_PROMISE = "I'll pay Kari for the sails by Friday."
ASKED = "Can you send me the tide table for Saturday?"
GOAL = "Finish the passage planner"
CANARY = "CANARY-tier-three-never-through-the-gate"


# -- records ----------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("shelves-tiers")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Path, "home", lambda: folder / "home")
        return sr.record(folder, mp).root


@pytest.fixture
def persona(built: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """The Oslo persona's record, a copy a test may write to."""
    root = tmp_path / "lb"
    shutil.copytree(built, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook(root)


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """An empty record of Ines Nordmann's, for the lines a test appends itself."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.set_owner_emails([sr.OWNER_EMAIL])
    return lb


def _note(lb: Logbook, at: str, text: str, tier: int = 2) -> str:
    line = lb.append(
        at=at, source="manual", kind="note", tier=tier, payload={"schema": "note/v1", "text": text}
    )
    return str(line["id"])


def _goal(lb: Logbook, at: str, text: str, tier: int = 2, supersedes: str | None = None) -> str:
    payload = {"schema": "goal/v1", "text": text, "horizon": "year", "from": "2026-01-01"}
    if supersedes:
        payload["supersedes"] = supersedes
    return str(lb.append(at=at, source="manual", kind="goal", tier=tier, payload=payload)["id"])


def _review(
    lb: Logbook,
    at: str,
    goal: str,
    disposition: str,
    tier: int = 2,
    note: str | None = None,
    lines: list[str] | None = None,
) -> str:
    payload: dict[str, object] = {
        "schema": "review/v1",
        "goal": goal,
        "disposition": disposition,
        "period": "day",
    }
    if note:
        payload["note"] = note
    if lines is not None:
        payload["extra"] = {"lines": lines}
    return str(lb.append(at=at, source="manual", kind="review", tier=tier, payload=payload)["id"])


def _chapter(
    lb: Logbook,
    at: str,
    name: str,
    start: str,
    tier: int = 2,
    supersedes: str | None = None,
    to: str | None = None,
) -> str:
    payload = {"schema": "chapter/v1", "name": name, "from": start}
    if to:
        payload["to"] = to
    if supersedes:
        payload["supersedes"] = supersedes
    return str(lb.append(at=at, source="manual", kind="chapter", tier=tier, payload=payload)["id"])


def _transcript(lb: Logbook, at: str, title: str, tier: int, summary: str | None = None) -> str:
    """A Claude Code session's line as the adapter writes it, without its text in the store."""
    payload: dict[str, object] = {
        "schema": "transcript/v1",
        "participants": [{"name": "owner"}, {"name": "assistant", "machine": True}],
        "title": title,
        "extra": {"counterpart": CLAUDE, "tool_calls": 2, "words": {"owner": 5, "machine": 7}},
    }
    if summary:
        payload["summary"] = summary
    line = lb.append(
        at=at, end=at[:-3] + "59Z", source="claude-code", kind="transcript", tier=tier, payload=payload
    )
    return str(line["id"])


def _telegram(lb: Logbook, at: str, text: str, tier: int, mine: bool = True) -> str:
    """One message of a Telegram bot chat, the owner's or the bot's, as the adapter writes it."""
    payload: dict[str, object] = {
        "schema": "message/v1",
        "chat": {"id": "900000001", "name": "Nordlys", "type": "direct"},
        "from_me": mine,
        "text": text,
        "extra": {"counterpart": BOT, **({} if mine else {"machine": True})},
    }
    if not mine:
        payload["sender"] = {"kind": "provider_id", "name": "Nordlys", "value": "telegram:900000001"}
    return str(lb.append(at=at, source="telegram", kind="message", tier=tier, payload=payload)["id"])


def _from_kari(lb: Logbook, at: str, text: str, tier: int) -> str:
    payload = {
        "schema": "message/v1",
        "service": "imessage",
        "chat": {"id": "chat-kari", "type": "direct", "name": KARI["name"]},
        "from_me": False,
        "sender": {"kind": "email", "value": KARI["email"], "name": KARI["name"]},
        "text": text,
    }
    return str(lb.append(at=at, source="imessage", kind="message", tier=tier, payload=payload)["id"])


def _resolution(lb: Logbook, at: str, email: str, label: str, tier: int) -> str:
    payload = {
        "schema": "resolution/v1",
        "ref": {"kind": "email", "value": email},
        "entity": {"type": "person", "id": "019cadd3-6bc0-7dcd-9133-000000000003", "registry": "logbook"},
        "label": label,
        "method": "owner",
    }
    return str(lb.append(at=at, source="manual", kind="resolution", tier=tier, payload=payload)["id"])


def _proposal(lb: Logbook, quote: str) -> promises.Proposal:
    return next(p for p in promises.extract(lb).proposals if p.match.quote == quote)


def _cache(lb: Logbook, pid: str, what: str) -> None:
    cache = {
        "version": 1,
        "judgements": {
            pid: {
                "is_commitment": True,
                "by": "owner",
                "to": "unknown",
                "what": what,
                "due": "2026-03-13",
                "confidence": 0.9,
                "engine": "synthetic",
                "model": sr.JUDGED_MODEL,
                "judged_at": "2026-03-10T09:00:00Z",
            }
        },
    }
    (lb.root / "policy").mkdir(exist_ok=True)
    (lb.root / "policy" / "promises-cache.json").write_bytes(json.dumps(cache).encode("utf-8"))


# -- pages ------------------------------------------------------------------------------------------------


def _site(lb: Logbook, tiers: tuple[int, ...] | None = None) -> serve.Site:
    return serve.Site(lb, now=lambda: sr.NOW, tiers=tiers)


def _get(lb: Logbook, tiers: tuple[int, ...] | None, target: str) -> tuple[int, str]:
    path, _, query = target.partition("?")
    response = _site(lb, tiers).respond(path, query)
    return response.status, unescape(response.body.decode("utf-8"))


def _page(lb: Logbook, tiers: tuple[int, ...] | None, target: str) -> str:
    status, page = _get(lb, tiers, target)
    assert status == 200, (target, status)
    return page


def _main(page: str) -> str:
    return page_text.seen(page[page.index("<main>") : page.index("</main>")])


def _header_tier(page: str) -> str:
    """The tier the page's heading says: N of a shelf's `nothing read above tier N` or of a detail
    page's `tier N`, `-` for a shelf's `no lines`."""
    found = re.search(r"<h1>.*?(?:tier (\S+)|no lines)</small></h1>", page, re.S)
    assert found is not None, page[:400]
    return found.group(1) or "-"


def _absent(page: str, *words: str) -> None:
    """Nowhere in the page's source: not in text, not in an href, not in a title attribute."""
    for word in words:
        assert word and word not in page, word


# -- Promises: a close, a disposition, a judgement, a person, a resolution ---------------------------------


def test_a_task_close_above_the_gate_leaves_the_promise_open_and_unnamed(lb: Logbook) -> None:
    """A tier-3 task line closed a tier-2 promise: through tiers 1 and 2 the promise is open, no
    `done`, no task id anywhere, and the row's tier is 2; read whole it is kept at tier 3."""
    _note(lb, "2026-03-02T17:00:00Z", PROMISE)
    p = _proposal(lb, PROMISE)
    task = lb.append(
        at="2026-03-06T10:00:00Z",
        source="manual",
        kind=promises.TASK,
        tier=3,
        payload=promises.draft_done(p, "2026-03-06T10:00:00Z", {"name": "rules", "version": "2"}),
    )
    gated = shelf_promises.read(lb, GATE)
    row = gated.row(p.id)
    assert row.section == shelf_promises.OPEN and row.proposal.closed_by is None and row.tier == 2
    assert gated.tier == 2
    for target in ("/promises", f"/promises/{p.id}"):
        page = _page(lb, GATE, target)
        _absent(page, str(task["id"]), "closed by the task line", "tier 3")
        assert "done" not in _main(page).replace("promises done", "")
        assert _header_tier(page) == "2"
    assert "Open 1" in _main(_page(lb, GATE, "/promises")) and "Kept 0" in _main(_page(lb, GATE, "/promises"))
    whole = shelf_promises.read(lb).row(p.id)
    assert whole.section == shelf_promises.KEPT and whole.tier == 3
    page = _page(lb, None, f"/promises/{p.id}")
    assert str(task["id"]) in page and _header_tier(page) == "3"


def test_a_signed_day_s_disposition_rests_on_its_tier_one_line(persona: Logbook) -> None:
    """The signature that dropped a promise is tier 1 (`signing.TIER`): through tier 2 alone the
    promise is open and the signature unnamed; through 1 and 2 it is dropped, at tier 2."""
    lb = persona
    with lb.index() as idx:
        signature = next(line for line in idx.by_kind(signing.KIND) if line["payload"]["day"] == "2026-03-04")
    assert int(signature["tier"]) == 1
    dropped = next(r for r in shelf_promises.read(lb, (2,)).rows if r.proposal.match.quote == sr.DROPPED)
    assert dropped.section == shelf_promises.OPEN and dropped.proposal.disposition is None
    page = _page(lb, (2,), f"/promises/{dropped.proposal.id}")
    _absent(page, str(signature["id"]), "signed day", "dropped")
    assert _header_tier(page) == "2"
    listing = _main(_page(lb, (2,), "/promises"))
    assert "Dropped 0" in listing
    whole = next(r for r in shelf_promises.read(lb, GATE).rows if r.proposal.match.quote == sr.DROPPED)
    assert whole.section == shelf_promises.DROPPED and whole.tier == 2
    page = _page(lb, GATE, f"/promises/{whole.proposal.id}")
    assert str(signature["id"]) in page and "dropped on the signed day 2026-03-04" in _main(page)


def test_a_disposition_above_the_gate_does_not_drop_the_promise(lb: Logbook) -> None:
    """A signature written at tier 3 by hand (not `sign`'s tier): through 1 and 2 the promise it
    dropped stays open, and the signature's id is nowhere."""
    note = _note(lb, "2026-03-04T08:00:00Z", PROMISE)
    p = _proposal(lb, PROMISE)
    signature = lb.append(
        at="2026-03-04T21:00:00Z",
        source="manual",
        kind=signing.KIND,
        tier=3,
        payload={
            "schema": signing.SCHEMA,
            "day": "2026-03-04",
            "subject": str(lb.meta["owner_id"]),
            "confirmed": [note],
            "dispositions": {note: "dropped"},
            "page": {"sha256": "0" * 64, "lines": 1},
        },
    )
    assert shelf_promises.read(lb).row(p.id).section == shelf_promises.DROPPED
    gated = shelf_promises.read(lb, GATE).row(p.id)
    assert gated.section == shelf_promises.OPEN and gated.tier == 2
    page = _page(lb, GATE, f"/promises/{p.id}")
    _absent(page, str(signature["id"]), "signed day", "tier 3")


def test_a_promise_above_the_gate_keeps_its_judgement_and_its_person_off_the_page(lb: Logbook) -> None:
    """A tier-3 note's promise and a tier-3 message from Kari: through 1 and 2 neither is listed or
    counted, Kari is not in the people filter nor in any link, the judgement cached for the note's
    promise is not on the page, and both ids are a 404 that says nothing of them."""
    _note(lb, "2026-03-02T17:00:00Z", PROMISE)
    _note(lb, "2026-03-05T08:00:00Z", SECRET_PROMISE, tier=3)
    _from_kari(lb, "2026-03-04T09:00:00Z", ASKED, tier=3)
    secret, asked = _proposal(lb, SECRET_PROMISE), _proposal(lb, ASKED)
    _cache(lb, secret.id, CANARY)
    whole = shelf_promises.read(lb)
    assert whole.people == [KARI["name"]] and whole.tier == 3
    assert whole.row(secret.id).proposal.judgement is not None
    gated = shelf_promises.read(lb, GATE)
    assert (
        gated.people == []
        and gated.tier == 2
        and {r.proposal.id for r in gated.rows} == {_proposal(lb, PROMISE).id}
    )
    for target in ("/promises", f"/promises?person={KARI['name']}", "/promises?person=Kari"):
        page = _page(lb, GATE, target)
        _absent(
            page, SECRET_PROMISE, ASKED, CANARY, KARI["name"], KARI["email"], secret.id, asked.id, "tier 3"
        )
        _absent(page, secret.line, asked.line, "person=Kari")
        assert _header_tier(page) == "2"
    assert "1 promise" in _main(_page(lb, GATE, "/promises"))
    for pid in (secret.id, asked.id):
        status, page = _get(lb, GATE, f"/promises/{pid}")
        assert status == 404
        _absent(page, SECRET_PROMISE, ASKED, CANARY, KARI["name"], secret.line, asked.line)
    assert CANARY in _main(_page(lb, None, f"/promises/{secret.id}"))


def test_a_resolution_above_the_gate_names_nobody(lb: Logbook) -> None:
    """Kari's address is on a tier-2 message; the resolution that names it is tier 3: through 1 and
    2 the page shows the address, never the label."""
    payload = {
        "schema": "message/v1",
        "service": "imessage",
        "chat": {"id": "chat-kari", "type": "direct"},
        "from_me": False,
        "sender": {"kind": "email", "value": KARI["email"]},
        "text": ASKED,
    }
    lb.append(at="2026-03-04T09:00:00Z", source="imessage", kind="message", tier=2, payload=payload)
    resolution = _resolution(lb, "2026-02-01T10:00:00Z", KARI["email"], KARI["name"], tier=3)
    whole = shelf_promises.read(lb)
    assert whole.people == [KARI["name"]]
    gated = shelf_promises.read(lb, GATE)
    assert gated.people == [KARI["email"]] and gated.tier == 2
    asked = next(r for r in gated.rows if r.proposal.match.quote == ASKED)
    assert asked.who == KARI["email"]
    for target in ("/promises", f"/promises/{asked.proposal.id}", f"/promises?person={KARI['email']}"):
        page = _page(lb, GATE, target)
        _absent(page, KARI["name"], "Kari", resolution, "tier 3")
    assert KARI["name"] in _main(_page(lb, None, "/promises"))


def test_a_name_read_from_a_higher_resolution_lifts_the_tier(lb: Logbook) -> None:
    """Read whole, the label `Kari Nordmann` rests on a tier-3 resolution; the page that shows it
    must say tier 3 (derived material takes the highest tier it read)."""
    _from_kari(lb, "2026-03-04T09:00:00Z", ASKED, tier=2)
    _resolution(lb, "2026-02-01T10:00:00Z", KARI["email"], KARI["name"], tier=3)
    whole = shelf_promises.read(lb)
    assert whole.people == [KARI["name"]]
    assert whole.tier == 3


# -- Goals: a review, a chain of wordings, a session a review names, a chapter ------------------------------


def test_a_review_above_the_gate_does_not_close_or_count_for_the_goal(lb: Logbook) -> None:
    """A tier-3 review said the tier-2 goal is done: through 1 and 2 the goal is open, unreviewed,
    its note and the review's id nowhere, `0 reviews`; read whole it is done at tier 3."""
    goal = _goal(lb, "2026-01-01T09:00:00Z", GOAL)
    review = _review(lb, "2026-03-03T09:00:00Z", goal, "done", tier=3, note=CANARY)
    whole = shelf_goals.read(lb, None, TODAY)
    assert whole.goal(goal).state == "done" and whole.goal(goal).tier == 3 and whole.tier == 3
    gated = shelf_goals.read(lb, GATE, TODAY)
    g = gated.goal(goal)
    assert (g.state, g.review, g.reviews, g.tier, gated.tier) == ("open", None, (), 2, 2)
    for target in ("/goals", f"/goals/{goal}"):
        page = _page(lb, GATE, target)
        _absent(page, CANARY, review, "badge done", "tier 3")
        assert _header_tier(page) == "2"
    text = _main(_page(lb, GATE, f"/goals/{goal}"))
    assert "0 reviews" in text and "not reviewed yet" in text
    assert "not reviewed yet" in _main(_page(lb, GATE, "/goals"))
    page = _page(lb, None, f"/goals/{goal}")
    assert CANARY in _main(page) and _header_tier(page) == "3"


def test_a_later_wording_above_the_gate_leaves_the_earlier_standing_and_unreachable(lb: Logbook) -> None:
    """The goal was reworded at tier 3, and the rewording reviewed at tier 2: through 1 and 2 the
    first wording stands, unreviewed; the rewording's text and id are nowhere, its page a 404 that
    says nothing, and the review of it (naming a tier-3 line) is not attached to the first."""
    first = _goal(lb, "2026-01-01T09:00:00Z", GOAL)
    later = _goal(lb, "2026-02-01T09:00:00Z", f"{GOAL} {CANARY}", tier=3, supersedes=first)
    review = _review(lb, "2026-03-01T09:00:00Z", later, "advancing", note="the planner carries the tides")
    whole = shelf_goals.read(lb, None, TODAY)
    assert [g.line for g in whole.goals] == [later] and whole.goal(first).line == later
    assert whole.goal(later).review is not None and whole.goal(later).tier == 3
    gated = shelf_goals.read(lb, GATE, TODAY)
    assert [g.line for g in gated.goals] == [first] and gated.tier == 2
    g = gated.goal(first)
    assert (g.text, g.state, g.review, g.reviews, g.earlier) == (GOAL, "open", None, (), ())
    with pytest.raises(shelf_goals.GoalNotFound):
        gated.goal(later)
    for target in ("/goals", f"/goals/{first}"):
        page = _page(lb, GATE, target)
        _absent(page, CANARY, later, review, "the planner carries the tides", "Earlier wordings", "tier 3")
        assert _header_tier(page) == "2"
    status, page = _get(lb, GATE, f"/goals/{later}")
    assert status == 404
    _absent(page, CANARY, GOAL, review, first)
    page = _page(lb, None, f"/goals/{first}")
    assert CANARY in _main(page) and "Earlier wordings" in _main(page) and _header_tier(page) == "3"


def test_an_earlier_wording_above_the_gate_is_not_among_the_earlier_wordings(lb: Logbook) -> None:
    """The first wording is tier 3 and the standing one tier 2: through 1 and 2 the standing goal
    shows with no earlier wording, the first's text and id nowhere (not in a `title`), its page a
    404; a tier-2 review of the first wording is not attached to the standing goal."""
    first = _goal(lb, "2026-01-01T09:00:00Z", f"{GOAL} {CANARY}", tier=3)
    later = _goal(lb, "2026-02-01T09:00:00Z", GOAL, supersedes=first)
    review = _review(lb, "2026-03-01T09:00:00Z", first, "stalled", note="the yard has not answered")
    whole = shelf_goals.read(lb, None, TODAY)
    assert (
        whole.goal(later).earlier == ((first, f"{GOAL} {CANARY}"),) and whole.goal(later).review is not None
    )
    assert whole.goal(later).tier == 3
    gated = shelf_goals.read(lb, GATE, TODAY)
    g = gated.goal(later)
    assert (g.earlier, g.review, g.reviews, g.tier) == ((), None, (), 2)
    with pytest.raises(shelf_goals.GoalNotFound):
        gated.goal(first)
    for target in ("/goals", f"/goals/{later}"):
        page = _page(lb, GATE, target)
        _absent(page, CANARY, first, review, "Earlier wordings", "badge stalled", "the yard has not answered")
        assert _header_tier(page) == "2"
    status, page = _get(lb, GATE, f"/goals/{first}")
    assert status == 404
    _absent(page, CANARY, GOAL, later)


def test_a_review_naming_a_session_above_the_gate_lists_no_session(lb: Logbook) -> None:
    """A tier-2 review names a tier-3 session and a tier-3 message: through 1 and 2 the goal's page
    lists no session, no id of either, no count on the shelf, and the Agents page is empty."""
    goal = _goal(lb, "2026-01-01T09:00:00Z", GOAL)
    session = _transcript(lb, "2026-03-01T10:00:00Z", CANARY, tier=3, summary=f"summary {CANARY}")
    message = _telegram(lb, "2026-03-02T10:00:00Z", f"message {CANARY}", tier=3)
    _review(lb, "2026-03-03T09:00:00Z", goal, "advancing", lines=[session, message])
    whole = shelf_goals.read(lb, None, TODAY)
    assert whole.goal(goal).served == ((session, "2026-03-01"), (message, "2026-03-02"))
    gated = shelf_goals.read(lb, GATE, TODAY)
    assert gated.goal(goal).served == () and gated.goal(goal).reviews[0].lines == (session, message)
    for target in ("/goals", f"/goals/{goal}"):
        page = _page(lb, GATE, target)
        _absent(page, CANARY, session, message, "/agents?day=", "session served it", "tier 3")
        assert _header_tier(page) == "2"
    assert "none a review names" in _main(_page(lb, GATE, f"/goals/{goal}"))
    agents = shelf_agents.read(lb, GATE)
    assert agents.sessions == [] and agents.tier == 0
    for target in ("/agents", "/agents?day=2026-03-01", "/agents?day=2026-03-02"):
        page = _page(lb, GATE, target)
        _absent(page, CANARY, session, message, GOAL, "tier 3")
        assert _header_tier(page) == "-"
    page = _page(lb, None, f"/goals/{goal}")
    assert shelf_agents.session_path(session, "2026-03-01") in page


def test_a_session_listed_from_a_higher_tier_lifts_the_goal_s_tier(lb: Logbook) -> None:
    """Read whole, the goal's page shows a tier-3 session's id and day: it must say tier 3."""
    goal = _goal(lb, "2026-01-01T09:00:00Z", GOAL)
    session = _transcript(lb, "2026-03-01T10:00:00Z", "Passage planner", tier=3)
    _review(lb, "2026-03-03T09:00:00Z", goal, "advancing", lines=[session])
    whole = shelf_goals.read(lb, None, TODAY)
    assert whole.goal(goal).served == ((session, "2026-03-01"),)
    assert whole.goal(goal).tier == 3
    assert whole.tier == 3


def test_a_chapter_above_the_gate_is_not_the_day_s_chapter(lb: Logbook) -> None:
    """A tier-3 chapter holds today beside the tier-2 one, and a tier-3 chapter supersedes another
    tier-2 one: through 1 and 2 neither tier-3 name nor id is on the page, no clash is said, and the
    superseded tier-2 chapter stands."""
    spring = _chapter(lb, "2026-02-01T09:00:00Z", sr.CHAPTER, "2026-02-01")
    secret = _chapter(lb, "2026-03-01T09:00:00Z", f"Chapter {CANARY}", "2026-03-01", tier=3)
    old = _chapter(lb, "2025-06-01T09:00:00Z", "The summer at sea", "2025-06-01", to="2025-08-31")
    renamed = _chapter(
        lb, "2025-06-02T09:00:00Z", f"Summer {CANARY}", "2025-06-01", tier=3, supersedes=old, to="2025-08-31"
    )
    whole = shelf_goals.read(lb, None, TODAY)
    assert whole.chapter is not None and CANARY in whole.chapter.name and whole.tier == 3
    assert {c.line for c in whole.chapters} == {spring, secret, renamed}
    gated = shelf_goals.read(lb, GATE, TODAY)
    assert gated.chapter is not None and gated.chapter.line == spring and gated.clash == []
    assert {c.line for c in gated.chapters} == {spring, old} and gated.tier == 2
    page = _page(lb, GATE, "/goals")
    _absent(page, CANARY, secret, renamed, "clashes with", "tier 3")
    assert sr.CHAPTER in _main(page) and "The summer at sea" in _main(page)
    assert _header_tier(page) == "2"


# -- Agents: a session, a Telegram day at mixed tiers, a goal above the gate --------------------------------


def test_a_telegram_day_at_mixed_tiers_shows_only_the_messages_the_gate_reads(lb: Logbook) -> None:
    """One bot chat on one day: the owner's first message is tier 3, the bot's reply and the owner's
    second tier 2. Through 1 and 2 the day is one session of two messages at tier 2, anchored on
    the first message read, the tier-3 words and id nowhere; read whole it is three at tier 3."""
    secret = _telegram(lb, "2026-03-02T10:00:00Z", f"Plan the passage {CANARY}", tier=3)
    reply = _telegram(lb, "2026-03-02T10:01:00Z", "Noted, I'll plan it.", tier=2, mine=False)
    second = _telegram(lb, "2026-03-02T10:02:00Z", "Plan the passage for Saturday.", tier=2)
    whole = shelf_agents.read(lb)
    assert [s.lines for s in whole.sessions] == [(secret, reply, second)] and whole.tier == 3
    assert whole.sessions[0].owner == (f"Plan the passage {CANARY}", "Plan the passage for Saturday.")
    gated = shelf_agents.read(lb, GATE)
    (s,) = gated.sessions
    assert (s.line, s.lines, s.tier, gated.tier) == (reply, (reply, second), 2, 2)
    assert s.owner == ("Plan the passage for Saturday.",) and s.machine == ("Noted, I'll plan it.",)
    assert s.minutes == 1 and s.words == {"owner": 5, "machine": 4}
    for target in ("/agents", "/agents?day=2026-03-02"):
        page = _page(lb, GATE, target)
        _absent(page, CANARY, secret, "tier 3", "3 messages")
        text = _main(page)
        assert "2 messages" in text and "1 turn of yours, 1 of the agent's" in text and "1 session" in text
        assert f'id="{shelf_agents.anchor(reply)}"' in page
        assert _header_tier(page) == "2"
    page = _page(lb, None, "/agents?day=2026-03-02")
    assert "3 messages" in _main(page) and CANARY in _main(page) and _header_tier(page) == "3"


def test_a_session_above_the_gate_is_not_counted_nor_on_its_day_s_page(lb: Logbook) -> None:
    """A tier-3 session beside a tier-2 one: through 1 and 2 the header counts one, its day's page
    says `none this day`, and its title, summary, agent's words and id are nowhere."""
    shown = _transcript(lb, "2026-03-01T10:00:00Z", "Passage planner for Solvind", tier=2)
    hidden = _transcript(lb, "2026-03-04T10:00:00Z", f"Title {CANARY}", tier=3, summary=f"Summary {CANARY}")
    assert [s.line for s in shelf_agents.read(lb).sessions] == [hidden, shown]
    gated = shelf_agents.read(lb, GATE)
    assert [s.line for s in gated.sessions] == [shown] and gated.tier == 2
    page = _page(lb, GATE, "/agents")
    _absent(page, CANARY, hidden, "2026-03-04", "tier 3")
    assert "1 session" in _main(page) and _header_tier(page) == "2"
    page = _page(lb, GATE, "/agents?day=2026-03-04")
    _absent(page, CANARY, hidden, "tier 3")
    assert "none this day" in _main(page) and "0 sessions" in _main(page)
    assert _header_tier(page) == "2"
    assert "earlier →" not in _main(_page(lb, GATE, "/agents"))


def test_a_goal_or_a_review_above_the_gate_serves_no_session(lb: Logbook) -> None:
    """A tier-2 review names a tier-2 session for a tier-3 goal, and a tier-3 review names it for a
    tier-2 goal: through 1 and 2 the session served nothing; no goal text, id or link is on it."""
    session = _transcript(lb, "2026-03-01T10:00:00Z", "Passage planner for Solvind", tier=2)
    secret_goal = _goal(lb, "2026-01-01T09:00:00Z", f"Goal {CANARY}", tier=3)
    goal = _goal(lb, "2026-01-01T09:30:00Z", GOAL)
    _review(lb, "2026-03-03T09:00:00Z", secret_goal, "advancing", lines=[session])
    secret_review = _review(lb, "2026-03-03T09:30:00Z", goal, "advancing", tier=3, lines=[session])
    whole = shelf_agents.read(lb)
    assert whole.sessions[0].served == ((secret_goal, f"Goal {CANARY}"), (goal, GOAL))
    gated = shelf_agents.read(lb, GATE)
    assert gated.sessions[0].served == () and gated.tier == 2
    for target in ("/agents", "/agents?day=2026-03-01"):
        page = _page(lb, GATE, target)
        _absent(page, CANARY, secret_goal, secret_review, "/goals/", "as your review says", GOAL, "tier 3")
        assert _header_tier(page) == "2"
    gated_goals = shelf_goals.read(lb, GATE, TODAY)
    assert gated_goals.goal(goal).served == ()
    with pytest.raises(shelf_goals.GoalNotFound):
        gated_goals.goal(secret_goal)
    _absent(_page(lb, GATE, f"/goals/{goal}"), session, secret_review, "/agents?day=")


# -- the persona's record, whole and through the gate -----------------------------------------------------


def test_each_page_s_tier_is_the_highest_tier_it_read(persona: Logbook) -> None:
    """Read whole, every shelf has read a tier-3 line and says so; through 1 and 2, tier 2; through
    tier 1 alone nothing is read and the pages say `tier -` (Goals says why)."""
    found = sr.ids(persona)
    pages = ("/promises", "/goals", "/agents", f"/goals/{found['quarter']}", "/agents?day=2026-03-01")
    for target in ("/promises", "/agents"):
        assert _header_tier(_page(persona, None, target)) == "3", target
    assert _header_tier(_page(persona, None, "/goals")) == "2"  # every goal line is tier 2, even whole
    for target in pages:
        page = _page(persona, GATE, target)
        assert _header_tier(page) == "2", target
        _absent(page, sr.SECRET, sr.HIDDEN_WORDS, found["hidden"], "tier 3")
    for target in ("/promises", "/agents"):
        page = _page(persona, (1,), target)
        assert _header_tier(page) == "-", target
        for word in (sr.KEPT, sr.OPEN, sr.DROPPED, sr.ASKED, sr.SECRET, sr.HIDDEN_WORDS, "Ola Nordmann"):
            assert word not in page, (target, word)
    assert _header_tier(_page(persona, (1,), "/goals")) == "-"


def test_the_counts_and_the_people_through_the_gate_are_of_the_rows_shown(persona: Logbook) -> None:
    """Through 1 and 2 the Promises header counts the rows listed, each section its own, and the
    people filter lists only the people of those rows; through tier 2 alone the signature (tier 1)
    is not read and the dropped promise is open."""
    gated = shelf_promises.read(persona, GATE)
    text = _main(_page(persona, GATE, "/promises"))
    assert f"{len(gated.rows)} promises" in text
    for name, title in shelf_promises.SECTIONS:
        assert f"{title} {len(gated.section(name))}" in text
    assert gated.people == ["Ola Nordmann"]
    secret = next(r for r in shelf_promises.read(persona).rows if r.proposal.match.quote == sr.SECRET)
    assert secret.tier == 3 and secret.proposal.id not in {r.proposal.id for r in gated.rows}
    through_two = shelf_promises.read(persona, (2,))
    dropped = next(r for r in through_two.rows if r.proposal.match.quote == sr.DROPPED)
    assert dropped.section == shelf_promises.OPEN and through_two.tier == 2
    kept = next(r for r in through_two.rows if r.proposal.match.quote == sr.KEPT)
    assert kept.section == shelf_promises.KEPT  # its task line is tier 2, read through tier 2


def test_a_guessed_id_above_the_gate_is_a_404_that_says_nothing_of_the_line(persona: Logbook) -> None:
    found = sr.ids(persona)
    every = shelf_promises.read(persona)
    secret = next(r.proposal for r in every.rows if r.proposal.match.quote == sr.SECRET)
    hidden = next(r.proposal for r in every.rows if sr.HIDDEN_WORDS in r.proposal.match.quote)
    for p in (secret, hidden):
        status, page = _get(persona, GATE, f"/promises/{p.id}")
        assert status == 404
        _absent(page, sr.SECRET, sr.HIDDEN_WORDS, p.line, "I'll pay")
        assert _get(persona, None, f"/promises/{p.id}")[0] == 200
    status, page = _get(persona, GATE, f"/goals/{found['hidden']}")  # a session's id is no goal's
    assert status == 404
    _absent(page, sr.HIDDEN_WORDS, sr.QUARTER)
