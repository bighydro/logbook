"""The week page (`/week/YYYY-Www`, `logbook.contrib.week_page`; RFC 0043 §8, slice D, part 1): the Sunday's
week draft grown into a page, read-only. Seven ribbons, one a day, each a link to its Day; where the week
went, the draft's computed numbers with their lines (sleep and training only where tier 3 is read); each
goal with what the week shows for it, the five verdicts and the command that gives one, and the two honest
moves; the one proposal for next week, in pencil; the stale question, once; the people who moved, names
only; the sprint and the next trip from the plan; Hold's census, counts only. Every part in its fold with
a summary line; nothing written, nothing fetched.

On the Oslo persona's fortnight (`dream_fortnight.py`), the week of 15 June 2026 (2026-W25) dreamed by the
in-process fake model; Kari and Ola Nordmann and Per Hansen do not exist, every address is at example.org,
every Notion id is made up here; no test opens a connection."""

from __future__ import annotations

import html
import json
import re
import shutil
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import phone_width
import pytest
from dream_fortnight import (
    DREAM_ENTRY,
    ENV,
    GOAL_READ,
    GOAL_SAIL,
    MODEL,
    W24,
    W25,
    fake,
    fortnight,
    run_cli,
    set_dream_entry,
)
from ideas_record import notion
from test_day_rhythm import _seen, beside
from test_dream_week_question import MAP, SAUNA
from test_dream_week_question import name as name_entity

from logbook.contrib import dream, entities, serve, week_page
from logbook.core import goals, people, policy
from logbook.core.store import Logbook
from logbook.labs import hold

TZ = ZoneInfo("Europe/Oslo")
MONDAY, SUNDAY = "2026-06-15", "2026-06-21"
DAYS = [f"2026-06-{d}" for d in range(15, 22)]
AFTER = datetime(2026, 6, 22, 8, 0, tzinfo=UTC)  # Monday after, 10:00 in Oslo: the week is over
KEPT = "Send Kari Nordmann the harbour map."  # the fake's first proposal for next week, the one kept
DROPPED = "Plan the summer."  # its second, which the writer drops
SAUNA_ASKED = "Floating Sauna: still exploring? Nothing since September 2023."
TASKS, SPRINTS, TRIPS = (f"{n:08x}-0000-4000-8000-{n:012x}" for n in (0x100, 0x101, 0x102))
SPRINT, TRIP = f"{0x201:08x}-0000-4000-8000-{0x201:012x}", f"{0x301:08x}-0000-4000-8000-{0x301:012x}"
NEWSLETTER = "news@boatclub.example.org"  # a sender Hold counts and never names
OWNER = "ines.nordmann@example.org"
DRIVE_FILE = "Crew list summer"  # a Drive file Hold counts and never names
FOLDS = ("The seven days", "Where the week went", "Goals", "Next week", "The question", "People who moved",
         "The plan", "Hold")  # fmt: skip


def _plan(root: Path) -> list[dict[str, Any]]:
    """A sprint holding the week and a trip after it, as `sync notion` writes them, and the mapping."""
    (root / "policy" / "notion.json").write_text(
        json.dumps({"plan": {"tasks": TASKS, "sprints": SPRINTS, "trips": TRIPS}}),
        encoding="utf-8",
    )
    return [
        notion("2026-06-01T08:00:00Z", SPRINT, "Sprint 12", action="created",
               parent={"type": "database", "id": SPRINTS}, path=["Plan", "Sprints"],
               properties={"Dates": {"start": "2026-06-15", "end": "2026-06-28"}}),
        notion("2026-06-01T08:05:00Z", TRIP, "Lofoten", action="created",
               parent={"type": "database", "id": TRIPS}, path=["Plan", "Trips"],
               properties={"When": {"start": "2026-07-03", "end": "2026-07-10"}}),
    ]  # fmt: skip


def _mail(at: str, sender: str, thread: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "mail",
        "kind": "mail",
        "tier": 2,
        "payload": {
            "schema": "mail/v1",
            "raw_id": f"{OWNER}:{at}.{thread}@mail.example.org",
            "message_id": f"{at}.{thread}@mail.example.org",
            "thread": thread,
            "from": {"email": sender},
            "to": [{"email": OWNER}],
            "subject": "The club in June",
            "direction": "received",
            "size": 1200,
            "account": OWNER,
        },
    }


def _drive(at: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "drive",
        "kind": "event",
        "tier": 1,
        "payload": {
            "schema": "event/v1",
            "raw_id": f"crew-1/edit@{at}",
            "title": f"edit {DRIVE_FILE}",
            "calendar": {"id": "google-drive", "name": "Google Drive"},
            "all_day": False,
            "modified_at": at,
            "extra": {
                "activity": "edit",
                "count": 1,
                "file": {"id": "crew-1", "name": DRIVE_FILE, "mime_type": "application/pdf",
                         "path": ["My Drive", "Boat"]},
                "by_owner": True,
            },
        },
    }  # fmt: skip


def _dreamed(root: Path, mp: pytest.MonkeyPatch, entry: dict[str, Any]) -> Path:
    """The fortnight, two stale ideas, the plan, two newsletters and a Drive edit in May, and both weeks
    dreamed under `entry` by the fake."""
    mp.setenv("LOGBOOK_HOME", str(root))
    for key, value in ENV.items():
        mp.setenv(key, value)
    mp.setattr(policy, "today", lambda: date(2026, 6, 20))
    mp.setattr(dream, "today", lambda: date(2026, 6, 22))
    lb = fortnight(root)
    set_dream_entry(root, entry)
    name_entity(lb, entities.IDEA, SAUNA, "exploring", "2023-09-10")
    name_entity(lb, entities.IDEA, MAP, "exploring", "2023-05-02")
    lb.append_many(
        [
            *_plan(root),
            _mail("2026-05-02T07:00:00Z", NEWSLETTER, "n-1"),
            _mail("2026-05-09T07:00:00Z", NEWSLETTER, "n-2"),
            _drive("2026-05-05T09:00:00Z"),
        ]
    )
    fake(mp)
    _code, out, err = run_cli("dream", "--catch-up")
    assert f"{W25}  dreamed" in out, out + err
    for census in ("senders", "drive"):  # Hold's reports, as the owner's last census left them
        code, _out, err = run_cli("lab", "hold", "census", census)
        assert code == 0, err
    return root


@pytest.fixture(scope="module")
def pristine(tmp_path_factory: pytest.TempPathFactory) -> Path:
    with pytest.MonkeyPatch.context() as mp:
        return _dreamed(tmp_path_factory.mktemp("week-page") / "lb", mp, DREAM_ENTRY)


@pytest.fixture(scope="module")
def health(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The same, the weeks dreamed under a `dream` entry that lets health cross: a tier-3 week."""
    with pytest.MonkeyPatch.context() as mp:
        return _dreamed(
            tmp_path_factory.mktemp("week-page-3") / "lb", mp, {"max_tier": 3, "until": "2026-12-31"}
        )


def _copy(source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    shutil.copytree(source, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook(root)


@pytest.fixture
def lb(pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    return _copy(pristine, tmp_path, monkeypatch)


def _site(lb: Logbook, **kw: Any) -> serve.Site:
    return serve.Site(lb, now=lambda: AFTER, **kw)


def _page(site: serve.Site, week: str = W25, query: str = "") -> str:
    response = site.respond(f"/week/{week}", query)
    assert response.status == 200, response.body[:300]
    return response.body.decode("utf-8")


def _fold(page: str, title: str) -> str:
    start = page.index(f"<h2>{title}</h2>")
    return page[start : page.index("</details><!--fold-->", start)]


def _summary(page: str, title: str) -> str:
    found = re.search(rf"<h2>{re.escape(title)}</h2> <span class=\"sum\">([^<]*)</span>", page)
    assert found is not None, title
    return found.group(1)


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", _seen(fragment)).strip()


def _names(lb: Logbook) -> list[str]:
    return sorted({p.name for p in people.directory(lb).known.values()})


# -- the page ------------------------------------------------------------------------------------------------


def test_the_week_page_holds_its_parts_each_folded_with_a_summary(lb: Logbook) -> None:
    page = _page(_site(lb))
    assert "<h1>The week 2026-W25" in page and "15\u201321 June 2026" in page
    titles = re.findall(r'<details class="fold[^"]*"[^>]*><summary><h2>([^<]+)</h2>', page)
    assert titles == list(FOLDS)
    for title in FOLDS:
        assert _summary(page, title).strip(), title
    assert "<form" not in page and "<script" not in page, "read-only: no form, no script (part 2 adds close)"
    pager = re.findall(r'href="/week/(\d{4}-W\d{2})"', page)
    assert W24 in pager and "2026-W26" in pager, "the week before and after"


def test_seven_ribbons_one_a_day_each_a_link_to_its_day(lb: Logbook) -> None:
    page = _page(_site(lb))
    days = _fold(page, "The seven days")
    assert days.count('<svg class="ribbon"') == 7
    assert re.findall(r'href="/day/(\d{4}-\d{2}-\d{2})"', days) == DAYS
    assert "Monday" in days and "Sunday" in days
    assert days.count('<p class="legend">') == 1, "one legend for the seven"
    assert 'class="now"' not in days, "the week's ribbons draw no now line"


def test_where_the_week_went_is_the_draft_s_numbers_each_with_its_lines(lb: Logbook) -> None:
    page = _page(_site(lb))
    went = _fold(page, "Where the week went")
    assert "Home" in went and " h" in went, "the hours by place"
    assert re.search(r'href="/line/[^"]+"', went), "each figure links its lines"
    assert "asleep" not in went and "workout" not in went, "a tier-2 week has no energy: no data, said"
    assert "no data" in went


def test_sleep_and_training_only_where_tier_3_is_read(health: Path, tmp_path: Path, monkeypatch) -> None:
    lb = _copy(health, tmp_path, monkeypatch)
    went = _fold(_page(_site(lb)), "Where the week went")
    assert "asleep" in went and "nights" in went
    assert "workout" in went or "training" in went
    below = _site(lb, tiers=(1, 2))
    page = _page(below)
    assert "asleep" not in page, "a tier-3 draft is not read through a gate of tiers 1 and 2"


def test_goals_with_the_week_the_five_verdicts_and_the_two_moves(lb: Logbook) -> None:
    page = _page(_site(lb))
    found = _fold(page, "Goals")
    assert GOAL_SAIL in found and GOAL_READ in found
    for verdict in goals.DISPOSITIONS:
        assert verdict.replace(" ", "-") in found, verdict
    assert "logbook goal review" in found and f"--at {SUNDAY}" in found and "--period week" in found
    assert "Change the days" in found and "Change the sentence" in found
    assert "--supersedes" in found, "reword: a new goal that supersedes the old"
    assert "proposes" in found and "advancing" in found, "the week's draft proposed a verdict, in pencil"
    text = _text(found)
    assert "73 %" not in text and "off track" not in text, "no verdict drawn by the page"


def test_the_one_proposal_for_next_week_is_pencil_headed_with_the_model(lb: Logbook) -> None:
    page = _page(_site(lb))
    proposal = _fold(page, "Next week")
    assert 'class="paper"' in proposal and MODEL in proposal
    assert KEPT in proposal and DROPPED not in page, "one proposal, never more"
    assert re.search(r'href="/line/[^"]+"', proposal), "with its lines"


def test_the_stale_question_is_asked_once(lb: Logbook) -> None:
    page = _page(_site(lb))
    assert page.count(SAUNA_ASKED) == 1
    assert MAP not in page, "the week before asked about it: passed over"
    assert "logbook status" in _fold(page, "The question")


def test_people_who_moved_names_only(lb: Logbook) -> None:
    page = _page(_site(lb))
    moved = _fold(page, "People who moved")
    assert "Kari Nordmann" in moved or "Ola Nordmann" in moved
    listed = moved[moved.index('<ul class="plain">') : moved.index("</ul>")]
    assert not re.search(r"\d", _text(listed)), "no number in the list of names"
    assert "contacts" not in moved


def test_the_sprint_and_the_next_trip_from_the_plan(lb: Logbook) -> None:
    plan_fold = _fold(_page(_site(lb)), "The plan")
    assert "Sprint 12" in plan_fold and "Lofoten" in plan_fold
    assert "notion.so" not in plan_fold, "no URL but the server's own"
    assert re.search(r'href="/line/[^"]+"', plan_fold)


def test_hold_s_census_counts_only(lb: Logbook) -> None:
    page = _page(_site(lb))
    hold = _fold(page, "Hold")
    assert re.search(r"\d+ senders?", hold) and re.search(r"\d+ files?", hold)
    assert NEWSLETTER not in page and "boatclub" not in page, "never a sender"
    assert DRIVE_FILE not in page and "crew-1" not in page, "never a file name"


def test_hold_is_read_from_its_reports_which_are_in_the_tag(lb: Logbook) -> None:
    """The page reads what `lab hold census` last wrote, where Hold writes it, and never runs a census;
    a census run again is a new page, and without the reports the part is not drawn."""
    assert week_page.HOLD_DIR.parts == hold.REPORTS.parts
    site = _site(lb)
    tag = site.etag(f"/week/{W25}", "", site.current())
    lb.append_many([_mail("2026-05-20T07:00:00Z", NEWSLETTER, "n-3")])
    assert run_cli("lab", "hold", "census", "senders")[0] == 0
    after = site.etag(f"/week/{W25}", "", site.current())
    assert after != tag
    assert "wrote 3 mails" in _fold(_page(site), "Hold")
    shutil.rmtree(lb.root / "state" / "hold")
    page = _page(_site(lb))
    assert "<h2>Hold</h2>" not in page and "Hold" in page[page.index('<p class="nothing">') :]


def test_the_day_and_the_sunday_draft_link_the_week(lb: Logbook) -> None:
    site = _site(lb)
    for day in ("2026-06-17", SUNDAY):
        body = site.respond(f"/day/{day}", "").body.decode("utf-8")
        assert f'href="/week/{W25}"' in body, day
    sunday = site.respond(f"/day/{SUNDAY}", "").body.decode("utf-8")
    week = sunday[sunday.index('id="week"') :]
    assert f'href="/week/{W25}"' in week, "the Sunday's week draft links its page"


# -- the guards ----------------------------------------------------------------------------------------------


def test_a_week_with_no_draft_says_so_in_one_line_and_invents_nothing(lb: Logbook) -> None:
    page = _page(_site(lb), "2026-W23")  # 1-7 June: before the fortnight, no draft
    assert page.count(week_page.NO_DRAFT) == 1
    assert 'class="paper"' not in page and SAUNA_ASKED not in page
    assert "People who moved" not in re.sub(r'<p class="nothing">.*?</p>', "", page, flags=re.S), (
        "a part with nothing is named once, not drawn"
    )
    assert "Nothing from:" in page


def test_no_number_beside_a_name_anywhere_on_the_page(
    lb: Logbook, health: Path, tmp_path: Path, monkeypatch
) -> None:
    names = _names(lb)
    assert "Kari Nordmann" in names and "Ola Nordmann" in names
    for site in (_site(lb), _site(lb, tiers=(1,)), _site(_copy(health, tmp_path / "h", monkeypatch))):
        for week in (W24, W25):
            for query in ("", "open=1"):
                found = beside(_seen(_page(site, week, query)), names)
                assert found == [], (week, query, found)


def test_a_model_s_sentence_with_a_number_beside_a_name_is_withheld(lb: Logbook) -> None:
    """The proposal is the model's words; one that sets a figure beside a person is not shown, only the
    row that says so and the line as written."""
    draft = {
        "line": "019cadd3-0000-7000-8000-000000000001",
        "model": MODEL,
        "segments": [
            {
                "part": "next_week",
                "text": "Call Kari Nordmann 3 times.",
                "evidence": ["e1"],
                "supported": True,
            }
        ],
    }
    shown = week_page.proposal_html(_site(lb), draft, ["Kari Nordmann"])
    assert "Kari Nordmann 3" not in shown and week_page.WITHHELD_BESIDE in html.unescape(shown)
    assert 'href="/line/019cadd3-0000-7000-8000-000000000001"' in shown, "the line as written"
    fine = week_page.proposal_html(_site(lb), draft, ["Per Hansen"])
    assert "Call Kari Nordmann 3 times." in fine


def test_a_static_site_without_its_drafts_shows_no_pencil(lb: Logbook) -> None:
    site = serve.Site(lb, now=lambda: AFTER, href=lambda path: path, with_drafts=False)
    page = _page(site)
    assert 'class="paper"' not in page and MODEL not in page and KEPT not in page
    assert "proposes" not in page and SAUNA_ASKED not in page
    assert week_page.NO_DRAFTS in html.unescape(page)


def test_a_tier_1_page_shows_no_tier_2_name_or_number(lb: Logbook) -> None:
    page = _page(_site(lb, tiers=(1,)))
    for word in ("Kari Nordmann", "Ola Nordmann", GOAL_SAIL, GOAL_READ, KEPT, SAUNA_ASKED, "never answered"):
        assert word not in page, word
    assert "Not read here: the senders census read tier 2" in html.unescape(page), "said, never counted"
    assert page.count('<svg class="ribbon"') == 7, "the ribbons are where you were: tier 1"
    assert "Sprint 12" in page, "the plan is tier 1"
    assert re.search(r"\d+ files?", page), "Drive's lines are tier 1"


def test_a_draft_or_a_report_of_another_shape_is_never_a_traceback(lb: Logbook, monkeypatch) -> None:
    """SPEC §5: a reader never fails on a payload it cannot interpret. Counts that are text, ids that are
    a string, a report whose tier is a word: each part reads what it can and the page answers."""
    odd = {
        "line": "019cadd3-0000-7000-8000-000000000002",
        "model": MODEL,
        "tier": 2,
        "segments": [{"part": "next_week", "text": "<b>Sail</b>", "evidence": "e1", "supported": True}],
        "numbers": {
            "places": [{"place": "<i>Home</i>", "hours": "many", "lines": "abc"}, "not a place"],
            "threads": [{"thread": "Harbour", "kind": "mail", "count": "twelve", "lines": [1, None]}],
            "people": [{"id": 7, "name": "Kari Nordmann", "contacts": "lots"}],
            "energy": {"sleep": {"nights": "seven", "hours": None, "lines": {}}, "training": "none"},
        },
        "proposed": {"goals": [{"goal": 3}, "x"], "question": {"text": 4}},
    }
    monkeypatch.setattr(week_page, "week_draft", lambda site, week: (odd, None))
    (lb.root / "state" / "hold" / "senders.json").write_text('{"tier": "two", "totals": {"received": "x"}}')
    page = _page(_site(lb))
    assert "<b>Sail</b>" not in page and "&lt;b&gt;Sail&lt;/b&gt;" in page, "escaped, never markup"
    assert "<i>Home</i>" not in page


def test_a_plan_title_or_a_place_that_names_a_person_is_never_beside_a_number(lb: Logbook) -> None:
    """The plan's titles are synced text and a place is named by the owner: either may name a person, and
    the page's figures (the dates, the days to go, the hours) never stand beside that name."""
    lb.append_many(
        [
            notion("2026-06-02T08:00:00Z", TRIP, "Lofoten with Kari Nordmann", action="edited",
                   parent={"type": "database", "id": TRIPS}, path=["Plan", "Trips"],
                   properties={"When": {"start": "2026-07-03", "end": "2026-07-10"}}),
        ]
    )  # fmt: skip
    page = _page(_site(lb))
    assert beside(_seen(page), _names(lb)) == []
    assert week_page.WITHHELD_BESIDE in html.unescape(_fold(page, "The plan"))
    draft = {"line": "x", "model": MODEL, "segments": [], "numbers": {"places": [
        {"place": "Kari Nordmann", "hours": 2.0, "lines": []}]}}  # fmt: skip
    summary, body = week_page._went(_site(lb), draft, ["Kari Nordmann"])
    assert beside(_seen(body), ["Kari Nordmann"]) == [] and summary


@pytest.mark.parametrize(
    "report",
    [
        {"totals": {"received": 9, "senders": 5, "never_answered": 1}},  # no tier
        {"tier": "two", "totals": {"received": 9, "senders": 5, "never_answered": 1}},
        {"tier": [1], "totals": {"received": 9, "senders": 5, "never_answered": 1}},
        {"tier": 2, "totals": {"received": 9, "senders": 1e400, "never_answered": 1}},
        {"tier": 1, "newsletters": [1], "settings": "x", "totals": {"received": 9, "senders": 5,
                                                                    "never_answered": 1}},
    ],
)  # fmt: skip
def test_a_hold_report_of_unknown_tier_is_not_read_and_none_is_a_traceback(lb: Logbook, report) -> None:
    (lb.root / "state" / "hold" / "senders.json").write_text(json.dumps(report), encoding="utf-8")
    for tiers in (None, (1,), ()):
        page = _page(_site(lb, tiers=tiers))
        tier = report.get("tier")
        readable = isinstance(tier, int) and (tiers is None or all(t in tiers for t in range(1, tier + 1)))
        if not readable:
            assert "wrote 9 mails" not in page, (tiers, report)


def test_a_question_whose_entity_is_not_an_object_is_never_a_traceback(lb: Logbook, monkeypatch) -> None:
    odd = {"line": "y", "model": MODEL, "tier": 2, "segments": [],
           "proposed": {"question": {"text": "Still exploring?", "entity": "idea", "label": 3},
                        "goals": [{"goal": "g", "disposition": "done", "segment": True}]}}  # fmt: skip
    monkeypatch.setattr(week_page, "week_draft", lambda site, week: (odd, None))
    assert "Still exploring?" in _page(_site(lb))


@pytest.mark.parametrize("week", ["0001-W01", "0001-W02", "9999-W52"])
def test_a_week_at_the_calendar_s_edge_is_a_400_never_a_traceback(lb: Logbook, week: str) -> None:
    assert _site(lb).respond(f"/week/{week}", "").status == 400


def test_a_week_that_is_not_one_is_a_400(lb: Logbook) -> None:
    site = _site(lb)
    assert site.respond("/week/2026-W54", "").status == 400
    assert site.respond("/week/2026-25", "").status == 404


def test_the_week_page_is_kept_by_its_tag_and_the_tag_moves_with_the_record(lb: Logbook) -> None:
    site = _site(lb)
    first = site.respond(f"/week/{W25}", "")
    assert first.etag is not None
    assert site.respond(f"/week/{W25}", "", if_none_match=first.etag).status == 304
    lb.append("2026-06-17T12:00:00Z", "manual", "note", 2, {"schema": "note/v1", "text": "A line later."})
    assert site.etag(f"/week/{W25}", "", site.current()) != first.etag


def test_the_week_page_fits_a_phone_390_px_wide(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(phone_width, "PHONE_PX", 390.0)
    for site in (_site(lb), _site(lb, tiers=(1,))):
        for query in ("", "open=1"):
            page = _page(site, W25, query)
            assert phone_width.problems(page) == []
            assert phone_width.phone_breakpoints(phone_width.parse(page)[1])
