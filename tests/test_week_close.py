"""Closing the week (RFC 0043 §8, slice D, part 2; `logbook.contrib.week_close`): on the week page, one
form, one POST, one writer lock: each standing goal's verdict, one of the five of `review goal`, and the
week's one proposal kept as a `note/v1` labelled `intention` on the Sunday; from the command line, the
same lines through `goal review --period week --at SUNDAY` and `day reflect SUNDAY --intention`, byte for
byte. Next week's mornings show the intention under *what today was for*, in ink, with its Sunday; the
proposal stays pencil until kept. Every item is checked before the first line, and a refusal writes
nothing; the write gate is every act's.

On the Oslo persona's fortnight (`dream_fortnight.py`), the week of 15 June 2026 (2026-W25) dreamed by the
in-process fake model, as `test_week_page.py` reads it. Kari and Ola Nordmann and Per Hansen do not
exist, every address is at example.org; no test opens a connection."""

from __future__ import annotations

import html
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import test_library_walk as walk
from dream_fortnight import DREAM_ENTRY, GOAL_READ, GOAL_SAIL, W25, run_cli
from library_header import without_shell
from test_day_rhythm import _seen, beside
from test_week_page import AFTER, KEPT, SUNDAY, _copy, _dreamed, _names, _page

from logbook.contrib import serve, week_close, week_page
from logbook.core import goals, notes, store
from logbook.core.store import Logbook

LOOPBACK, ORIGIN = "127.0.0.1", "http://127.0.0.1:8765"
CLOSE = f"/week/{W25}/close"
MINE = "Two evenings on the harbour map, Tuesday and Thursday."  # the owner's own words for next week
MONDAY_MORNING = datetime(2026, 6, 22, 5, 30, tzinfo=UTC)  # 07:30 in Oslo: the morning of the week after
SUNDAY_EVENING = datetime(2026, 6, 21, 19, 0, tzinfo=UTC)  # 21:00 on the Sunday itself
CLOCK = "2026-10-24T09:00:00Z"  # the clock every writer reads in a parity test


@pytest.fixture(scope="module")
def pristine(tmp_path_factory: pytest.TempPathFactory) -> Path:
    with pytest.MonkeyPatch.context() as mp:
        return _dreamed(tmp_path_factory.mktemp("week-close") / "lb", mp, DREAM_ENTRY)


@pytest.fixture
def lb(pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    return _copy(pristine, tmp_path, monkeypatch)


def _site(lb: Logbook, now: datetime = AFTER, **kw: Any) -> serve.Site:
    return serve.Site(lb, now=lambda: now, **kw)


def _post(site: serve.Site, form: dict[str, str], path: str = CLOSE, **kw: Any) -> serve.Response:
    return site.write(
        path, {"act": "close", **form}, kw.pop("client", LOOPBACK), kw.pop("origin", ORIGIN), **kw
    )


def _ids(lb: Logbook) -> dict[str, str]:
    """text → id of the standing goals."""
    found = goals.listing(lb)["goals"]
    return {g["text"]: g["line"] for g in found}


def _new(lb: Logbook, before: int) -> list[dict[str, Any]]:
    return [line for line in lb.lines() if int(line["seq"]) > before]


def _intentions(lb: Logbook) -> list[dict[str, Any]]:
    return [line for line in lb.lines() if notes.labelled(line, notes.INTENTION)]


def _close_part(page: str) -> str:
    start = page.index('<section class="part close">')
    return page[start : page.index("</section><!--part-->", start)]


def _pin(monkeypatch: pytest.MonkeyPatch, clock: str = CLOCK) -> None:
    """Every writer's clock at `clock`: the goals' `now`, a note's today and the store's `recorded_at`."""
    instant = datetime.fromisoformat(clock.replace("Z", "+00:00"))
    monkeypatch.setattr(goals, "now", lambda: instant)
    monkeypatch.setattr(notes, "now_utc", lambda: clock)
    monkeypatch.setattr(store, "now_utc", lambda: clock)
    monkeypatch.setattr(notes, "today_in", lambda days: days.today(instant).isoformat())


# -- the form ------------------------------------------------------------------------------------------------


def test_the_week_page_carries_one_form_to_close_the_week_and_no_script(lb: Logbook) -> None:
    page = _page(_site(lb))
    forms = walk._forms(page)
    assert [f.action for f in forms] == [CLOSE], "one form, Close the week"
    assert "<script" not in page
    part = _close_part(page)
    assert '<h2 id="close">Close the week</h2>' in part
    ids = _ids(lb)
    for text in (GOAL_SAIL, GOAL_READ):
        goal = ids[text]
        radios = re.findall(rf'<input type="radio" name="verdict-{goal}" value="([^"]*)"', part)
        assert radios == ["", *week_page.VERDICTS], "no verdict, then the five, as one choice"
        assert f'name="verdict-{goal}" value="" checked' in part, "none chosen until you choose"
        assert f"logbook goal review {goal} advancing|stalled|done|let-go|superseded --period week" in part
        assert f"--supersedes {goal}" in part and f'href="/goals/{goal}"' in part, "change the sentence"
    assert "change the days" in part and "change the sentence" in part
    assert f"logbook day reflect {SUNDAY} --intention" in part, "the command beside the intention"
    assert '<textarea name="intention"' in part and KEPT in part, "the proposal in the field"
    assert f'<textarea name="intention" class="pencil" title="{week_page.PROPOSAL_PENCIL}"' in part, (
        "a model's words in the field are pencil until you keep them"
    )
    assert '<input type="checkbox" name="keep" value="1">' in part and "checked" not in part.split("keep")[-1]
    assert beside(_seen(page), _names(lb)) == []


def test_no_form_on_a_static_site_or_a_page_that_does_not_read_tier_2(lb: Logbook) -> None:
    static = serve.Site(lb, now=lambda: AFTER, href=lambda path: path)
    for site in (static, _site(lb, tiers=(1,))):
        page = _page(site)
        own = without_shell(page, static=site.static)  # the header's one form is Ask, a GET
        assert "<form" not in own and "Close the week" not in page


def test_a_week_whose_sunday_is_ahead_says_when_it_closes_and_writes_nothing(lb: Logbook) -> None:
    site = _site(lb, datetime(2026, 6, 18, 10, 0, tzinfo=UTC))  # Thursday of the week
    page = _page(site)
    own = without_shell(page)  # the header's one form is Ask, a GET
    assert "<form" not in own and f"The week closes on its Sunday, {SUNDAY}" in html.unescape(page)
    head = lb.meta["seq"]
    response = _post(site, {"keep": "1", "intention": MINE})
    assert response.status == 400 and "ahead of today" in response.body.decode("utf-8")
    assert lb.meta["seq"] == head


# -- the intention -------------------------------------------------------------------------------------------


def test_keep_writes_one_intention_on_the_sunday_and_again_supersedes_never_duplicates(lb: Logbook) -> None:
    site = _site(lb)
    response = _post(site, {"keep": "1", "intention": KEPT})
    assert response.status == 303 and response.location == f"/week/{W25}#close"
    (first,) = _intentions(lb)
    assert first["payload"] == {"schema": "note/v1", "text": KEPT, "labels": ["intention"]}
    assert first["source"] == "reflect" and first["tier"] == 2 and first["kind"] == "note"
    assert first["at"] == "2026-06-21T21:59:00Z", "the Sunday's last minute in Oslo"
    head = lb.meta["seq"]
    assert _post(site, {"keep": "1", "intention": f"  {KEPT}\r\n"}).status == 303
    assert lb.meta["seq"] == head, "the same words again: nothing written"
    assert _post(site, {"keep": "1", "intention": MINE}).status == 303
    _first, second = _intentions(lb)
    assert second["payload"]["supersedes"] == first["id"] and second["payload"]["text"] == MINE
    assert [str(x["id"]) for x in week_close.standing(_intentions(lb))] == [second["id"]], "one stands"
    page = _page(site)
    assert MINE in page and "Kept on Sunday 21 June" in html.unescape(page)
    assert "the intention kept" in page, "Next week's summary says so"


def test_the_words_without_keep_are_not_written(lb: Logbook) -> None:
    head = lb.meta["seq"]
    response = _post(_site(lb), {"intention": MINE})
    assert response.status == 400 and "nothing to write" in response.body.decode("utf-8")
    assert lb.meta["seq"] == head


def test_day_reflect_intention_writes_the_page_s_line_byte_for_byte(
    pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin(monkeypatch)
    page_lb = _copy(pristine, tmp_path / "page", monkeypatch)
    assert _post(_site(page_lb), {"keep": "1", "intention": KEPT}).status == 303
    cli_lb = _copy(pristine, tmp_path / "cli", monkeypatch)
    code, out, err = run_cli("day", "reflect", SUNDAY, "--intention", KEPT)
    assert code == 0, err
    assert "kept the intention" in out and SUNDAY in out
    (a,), (b,) = _intentions(page_lb), _intentions(cli_lb)
    assert {k: v for k, v in a.items() if k != "id"} == {k: v for k, v in b.items() if k != "id"}
    assert a["hash"] == b["hash"]
    code, out, _err = run_cli("day", "reflect", SUNDAY, "--intention", KEPT)
    assert code == 0 and "nothing was written" in out, "the same words: nothing"
    assert len(_intentions(cli_lb)) == 1


@pytest.mark.parametrize(
    ("args", "said"),
    [
        (["2026-06-20", "--intention", MINE], "not a Sunday"),
        (["2099-06-21", "--intention", MINE], "ahead of today"),
        ([SUNDAY, "--intention", "  "], "empty"),
        ([SUNDAY, "--intention", MINE, "--text", "A day."], "--text"),
        ([SUNDAY, "--intention", MINE, "--sign"], "--sign"),
        ([SUNDAY, "--intention", MINE, "--at", "2026-06-21T20:00:00+02:00"], "--at"),
    ],
)
def test_day_reflect_intention_refuses_and_writes_nothing(lb: Logbook, args: list[str], said: str) -> None:
    head = lb.meta["seq"]
    code, _out, err = run_cli("day", "reflect", *args)
    assert code == 2 and said in err, err
    assert lb.meta["seq"] == head


def test_intention_belongs_to_day_reflect(lb: Logbook) -> None:
    for args in (["day", SUNDAY, "--intention", MINE], ["day", "sign", SUNDAY, "--intention", MINE]):
        code, _out, err = run_cli(*args)
        assert code == 2 and "--intention" in err, (args, err)


# -- next week's mornings ------------------------------------------------------------------------------------


def _for(page: str) -> str:
    start = page.index('<section class="part for">')
    return page[start : page.index("</section><!--part-->", start)]


def test_next_week_s_mornings_show_the_intention_in_ink_with_its_sunday(lb: Logbook) -> None:
    site = _site(lb, MONDAY_MORNING)
    before = site.respond("/day/2026-06-22", "").body.decode("utf-8")
    assert re.search(
        r'<p class="proposal" title="Pencil: drafted by [^"]+">.*?' + re.escape(KEPT), before, re.S
    ), "pencil, until kept"
    assert 'class="for intention"' not in before
    assert _post(_site(lb), {"keep": "1", "intention": MINE}).status == 303
    after = site.respond("/day/2026-06-22", "").body.decode("utf-8")
    found = _for(after)
    assert f'<span class="ink">{html.escape(MINE)}</span>' in found
    assert 'href="/day/2026-06-21"' in found and "Sunday 21 June" in found, "with its Sunday"
    assert 'class="proposal"' not in after, "kept, it is ink: no pencil beside it"
    sunday = _site(lb, datetime(2026, 6, 28, 6, 0, tzinfo=UTC))  # the next week's Sunday morning, 08:00
    assert MINE in _for(sunday.respond("/day/2026-06-28", "").body.decode("utf-8"))
    later = _site(lb, datetime(2026, 6, 29, 6, 0, tzinfo=UTC))  # the Monday after: another week
    assert MINE not in later.respond("/day/2026-06-29", "").body.decode("utf-8")
    gated = _site(lb, MONDAY_MORNING, tiers=(1,))
    assert MINE not in gated.respond("/day/2026-06-22", "").body.decode("utf-8"), "tier 2: not read"


def test_an_intention_with_a_number_beside_a_name_is_withheld_on_both_pages(lb: Logbook) -> None:
    said = "Call Kari Nordmann 3 times."
    assert _post(_site(lb), {"keep": "1", "intention": said}).status == 303
    day = _site(lb, MONDAY_MORNING).respond("/day/2026-06-22", "").body.decode("utf-8")
    week = _page(_site(lb))
    for page in (day, week):
        assert said not in html.unescape(page) and beside(_seen(page), _names(lb)) == []
    assert "withheld" in html.unescape(_for(day))


# -- the verdicts --------------------------------------------------------------------------------------------


def test_one_post_writes_the_verdicts_and_the_intention_as_the_commands_do(
    pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin(monkeypatch)
    lb = _copy(pristine, tmp_path / "page", monkeypatch)
    ids = _ids(lb)
    sail, read = ids[GOAL_SAIL], ids[GOAL_READ]
    head = int(lb.meta["seq"])
    form = {
        f"verdict-{sail}": "stalled",
        f"note-{sail}": "The boat is on land.",
        f"verdict-{read}": "let-go",
        f"note-{read}": "",
        "keep": "1",
        "intention": KEPT,
    }
    assert _post(_site(lb), form).status == 303
    written = _new(lb, head)
    assert [line["kind"] for line in written] == ["review", "review", "note"]
    assert [line["payload"]["disposition"] for line in written[:2]] == ["stalled", "let go"]
    assert all(line["payload"]["period"] == "week" for line in written[:2])
    cli = _copy(pristine, tmp_path / "cli", monkeypatch)
    for args in (
        [
            "goal",
            "review",
            sail,
            "stalled",
            "--period",
            "week",
            "--at",
            SUNDAY,
            "--note",
            "The boat is on land.",
        ],
        ["goal", "review", read, "let-go", "--period", "week", "--at", SUNDAY],
        ["day", "reflect", SUNDAY, "--intention", KEPT],
    ):
        code, _out, err = run_cli(*args)
        assert code == 0, (args, err)
    same = _new(cli, head)
    strip = [{k: v for k, v in line.items() if k != "id"} for line in written]
    assert [{k: v for k, v in line.items() if k != "id"} for line in same] == strip
    assert [x["hash"] for x in written] == [x["hash"] for x in same], "byte for byte"
    page = _close_part(_page(_site(lb)))
    assert "Your verdict for the week: stalled, 2026-06-21" in page, "given: said, no choice"
    assert f'name="verdict-{sail}"' not in page


@pytest.mark.parametrize(
    "bad",
    [
        {"verdict-X": "stalled"},  # X: replaced by the first goal's id
        {"verdict-X": "sixth"},
        {"verdict-nobody": "done"},
        {"verdict-X": "", "note-X": "words with no verdict"},
        {"keep": "1", "intention": "   "},
        {"act": "open"},
    ],
)
def test_any_refusal_writes_nothing_not_even_the_items_before_it(lb: Logbook, bad: dict[str, str]) -> None:
    ids = _ids(lb)
    sail, read = ids[GOAL_SAIL], ids[GOAL_READ]
    form = {f"verdict-{read}": "advancing", "keep": "1", "intention": MINE}
    form.update({k.replace("X", sail): v for k, v in bad.items()})
    if bad == {"verdict-X": "stalled"}:  # the goal reviewed already this week, another verdict
        assert run_cli("goal", "review", sail, "advancing", "--period", "week", "--at", "2026-06-19")[0] == 0
    files, head = walk._files(lb.root), lb.meta["head"]
    response = _post(_site(lb), form)
    assert response.status == 400, (bad, response.status)
    assert "nothing" in html.unescape(response.body.decode("utf-8")) or bad == {"act": "open"}
    assert lb.meta["head"] == head and walk._files(lb.root) == files, bad


def test_the_same_verdict_again_on_the_same_day_writes_nothing(lb: Logbook) -> None:
    sail = _ids(lb)[GOAL_SAIL]
    assert _post(_site(lb), {f"verdict-{sail}": "advancing"}).status == 303
    head = lb.meta["seq"]
    assert _post(_site(lb), {f"verdict-{sail}": "advancing"}).status == 303
    assert lb.meta["seq"] == head


def test_closed_on_the_sunday_itself_the_lines_are_now(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    _pin(monkeypatch, "2026-06-21T19:00:00Z")
    sail = _ids(lb)[GOAL_SAIL]
    head = int(lb.meta["seq"])
    form = {f"verdict-{sail}": "advancing", "keep": "1", "intention": MINE}
    assert _post(_site(lb, SUNDAY_EVENING), form).status == 303
    assert [line["at"] for line in _new(lb, head)] == ["2026-06-21T19:00:00Z"] * 2


# -- the gate ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("client", "origin"),
    [("192.0.2.7", ORIGIN), (LOOPBACK, "https://evil.example.org"), (LOOPBACK, "null")],
)
def test_the_write_gate_refuses_every_other_client_and_origin(lb: Logbook, client: str, origin: str) -> None:
    files = walk._files(lb.root)
    response = _post(_site(lb), {"keep": "1", "intention": MINE}, client=client, origin=origin)
    said = html.unescape(response.body.decode("utf-8"))
    assert response.status == 403 and "a week is closed from this machine only" in said
    assert "nothing was written" in said and walk._files(lb.root) == files


def test_a_get_of_the_act_is_a_405_and_a_post_elsewhere_a_404(lb: Logbook) -> None:
    site = _site(lb)
    assert site.respond(CLOSE, "").status == 405
    assert _post(site, {}, path=f"/week/{W25}/open").status == 404
    assert _post(site, {"keep": "1", "intention": MINE}, path="/week/2026-W54/close").status == 400


def test_a_sealed_record_without_its_identity_refuses_and_writes_nothing(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sealed record's rule is the store's (RFC 0029 §6.3): a tier-2 line needs the identity."""
    from logbook.core import sealing

    def refuse(self: Logbook, tiers: Any) -> None:
        raise sealing.IdentityRequired("no identity at /nowhere to seal with")

    monkeypatch.setattr(Logbook, "_require_identity", refuse)
    files = walk._files(lb.root)
    response = _post(_site(lb), {f"verdict-{_ids(lb)[GOAL_SAIL]}": "done", "keep": "1", "intention": MINE})
    assert response.status == 400 and "identity" in response.body.decode("utf-8")
    assert walk._files(lb.root) == files


def test_the_close_section_fits_a_phone_390_px_wide(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    import phone_width

    monkeypatch.setattr(phone_width, "PHONE_PX", 390.0)
    page = _page(_site(lb))
    assert phone_width.problems(page) == []


def test_the_record_still_verifies_after_a_close(lb: Logbook) -> None:
    sail = _ids(lb)[GOAL_SAIL]
    assert _post(_site(lb), {f"verdict-{sail}": "done", "keep": "1", "intention": MINE}).status == 303
    code, out, err = run_cli("verify")
    assert code == 0, out + err
    assert json.loads(json.dumps(lb.meta))["seq"] > 0


# -- from the independent review -------------------------------------------------------------------------


def test_an_intention_kept_as_the_sunday_turns_to_monday_stays_on_the_sunday(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kept while the record's today is the Sunday, written after midnight: the line is the Sunday's,
    its last minute, so the week finds it and the next Keep supersedes it rather than adding one."""
    monkeypatch.setattr(notes, "now_utc", lambda: "2026-06-21T22:00:30Z")  # 00:00:30 Monday in Oslo
    done = week_close.keep(lb, SUNDAY, MINE, today=SUNDAY)
    assert done.line is not None and done.line["at"] == "2026-06-21T21:59:00Z"
    assert week_close.kept(lb, SUNDAY) is not None
    again = week_close.keep(lb, SUNDAY, KEPT, today=SUNDAY)
    assert again.line is not None and again.line["payload"]["supersedes"] == done.line["id"]


def test_the_same_verdict_with_other_words_is_refused_not_dropped(lb: Logbook) -> None:
    sail = _ids(lb)[GOAL_SAIL]
    assert _post(_site(lb), {f"verdict-{sail}": "stalled", f"note-{sail}": "On land."}).status == 303
    files = walk._files(lb.root)
    response = _post(_site(lb), {f"verdict-{sail}": "stalled", f"note-{sail}": "Still on land."})
    said = html.unescape(response.body.decode("utf-8"))
    assert response.status == 400 and GOAL_SAIL in said and "nothing was written" in said
    assert walk._files(lb.root) == files
    assert _post(_site(lb), {f"verdict-{sail}": "stalled"}).status == 303, "the same verdict: nothing"
    assert walk._files(lb.root) == files


def test_words_without_a_verdict_name_the_goal(lb: Logbook) -> None:
    sail = _ids(lb)[GOAL_SAIL]
    response = _post(
        _site(lb), {f"verdict-{sail}": "", f"note-{sail}": "On land.", "keep": "1", "intention": MINE}
    )
    said = html.unescape(response.body.decode("utf-8"))
    assert response.status == 400 and GOAL_SAIL in said and "nothing was written" in said
    assert _intentions(lb) == []


def test_two_lines_of_one_goal_s_chain_are_one_goal(lb: Logbook) -> None:
    sail = _ids(lb)[GOAL_SAIL]
    code, _out, err = run_cli("goal", "add", "Sail to Lofoten and back in July.", "--horizon", "year",
                              "--from", "2026-06-01", "--supersedes", sail)  # fmt: skip
    assert code == 0, err
    later = _ids(lb)["Sail to Lofoten and back in July."]
    files = walk._files(lb.root)
    response = _post(_site(lb), {f"verdict-{sail}": "stalled", f"verdict-{later}": "advancing"})
    assert response.status == 400 and "two verdicts" in html.unescape(response.body.decode("utf-8"))
    assert walk._files(lb.root) == files
