"""The ideas read back (RFC 0037 §7, §11): `show ideas`, the shelf, every idea the owner named by its
stage, the most recent touch first, each with its reason and never a person's name; `show idea NAME`,
one idea's page, its timeline newest first, the people it was discussed with by name, its documents
as references, its title thread and its words. A bot's line, an agent's and a relations line are no
touch, no person and no words here either. On `ideas_record`: three ideas across Notion, two
repositories, tasks and a call, over three years, of people who do not exist."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from ideas_record import (
    CLOCK,
    KIOSK,
    KIOSK_REASON,
    KIOSK_REPO,
    KIOSK_ROW,
    OLA_ID,
    PRICING,
    SAUNA,
    SAUNA_REASON,
    TAXES_ROW,
    TODAY,
    github,
    ideas_drafts,
    record,
    settle,
)

from logbook import cli
from logbook.contrib import entity_review, ideas
from logbook.core.store import Logbook


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    found = record(tmp_path, monkeypatch, ideas_drafts())
    settle(found)
    return found


def _ids(lb: Logbook) -> dict[str, str]:
    return {e.label: e.id for e in ideas.named(lb).values()}


def _line_ids(lb: Logbook, test: Any) -> set[str]:
    return {str(line["id"]) for line in Logbook(lb.root).lines() if test(line)}


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main([*args])
    return capsys.readouterr().out


def _refused(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    with pytest.raises(SystemExit) as e:
        cli.main([*args])
    assert e.value.code == 2, args
    return capsys.readouterr().err


# -- the shelf -----------------------------------------------------------------------------------------------


def test_the_shelf_is_every_idea_by_stage_the_most_recent_touch_first_with_its_reason(lb: Logbook) -> None:
    shelf = ideas.shelf(lb, today=TODAY)
    assert [(name, [r.idea.label for r in rows]) for name, rows in shelf.grouped()] == [
        ("exploring", [KIOSK, CLOCK]),
        ("spark", [SAUNA]),
    ], "RFC 0037 §11's order, the most recent touch first within each"
    text = "\n".join(ideas.shelf_rows(shelf))
    assert text.startswith(f"ideas · 3 · {TODAY} · tier 2\nexploring\n")
    assert f"reason: {KIOSK_REASON}" in text
    assert f"reason (killed 2026-10-05): {SAUNA_REASON}" in text, (
        "a killed idea sparked again keeps its reason"
    )
    rows = {r.idea.label: r for r in shelf.rows}
    kiosk, clock, sauna = rows[KIOSK], rows[CLOCK], rows[SAUNA]
    assert kiosk.words == 360 + 300, "this year's Notion deltas: Ines's edit and Ola's new page, no bot's"
    assert kiosk.repos == [f"github.com/{KIOSK_REPO}"] and kiosk.pages == 2
    assert kiosk.last is not None and kiosk.last.day == "2026-09-20" and kiosk.first == "2024-03-04"
    assert kiosk.titles == ["Pricing", "Fjord kiosk"], (
        "the title thread: pages, tasks and calls, newest first"
    )
    assert clock.stale and clock.stale_since == "2023-05-10", "exploring for over two years, untouched"
    assert "stale: nothing since 2023-05-10" in text and not kiosk.stale
    assert sauna.status is not None and sauna.status.status == "spark" and sauna.reason is not None


def test_the_shelf_counts_the_people_it_was_discussed_with_and_never_names_them(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    shelf = ideas.shelf(lb, today=TODAY)
    assert {r.idea.label: r.people for r in shelf.rows} == {KIOSK: 1, CLOCK: 0, SAUNA: 1}
    text = _run(capsys, "show", "ideas")
    data = json.loads(_run(capsys, "show", "ideas", "--json"))
    assert "1 person" in text and "Ola" not in text
    assert "Ola" not in json.dumps(data) and OLA_ID not in json.dumps(data)
    assert [i["name"] for i in data["ideas"]] == [SAUNA, KIOSK, CLOCK]


# -- the page ------------------------------------------------------------------------------------------------


def test_the_page_is_its_status_first_said_timeline_people_documents_titles_words_and_history(
    lb: Logbook,
) -> None:
    page = ideas.page(lb, _ids(lb)[KIOSK], today=TODAY)
    assert page.status is not None and page.status.status == "exploring" and page.since == "2026-09-14"
    assert page.first is not None and page.first.day == "2024-03-04", "first said: its earliest touch"
    days = [i.day for i in page.timeline]
    assert days == sorted(days, reverse=True) and len(days) == 7, "every touch, newest first"
    assert [p.name for p in page.people] == ["Ola Nordmann"] and page.unplaced == 0
    docs = {d.ref: d for d in page.documents}
    assert docs[KIOSK_ROW].words == 480 and docs[PRICING].words == 300
    assert docs[KIOSK_ROW].path == ("Ines' hub", "Ideas")
    assert docs[f"github.com/{KIOSK_REPO}"].versions == 2 and docs[f"github.com/{KIOSK_REPO}"].words == 210
    assert page.words == {"2024-03": 120, "2026-09": 660}
    assert [(s.status, s.current) for s in page.history] == [("spark", False), ("exploring", True)]
    text = "\n".join(ideas.page_rows(page))
    assert "Ola Nordmann: 1 day, last 2026-09-20" in text and "README 2 versions, 210 words" in text


def test_a_bot_s_line_an_agent_and_a_relations_line_are_no_touch_no_person_and_no_words(lb: Logbook) -> None:
    ids = _ids(lb)
    page = ideas.page(lb, ids[KIOSK], today=TODAY)
    shown = {i.line for i in page.timeline}
    bots = _line_ids(
        lb, lambda x: ((x["payload"].get("extra") or {}).get("actor") or {}).get("type") in ("bot", "Bot")
    )
    relations = _line_ids(lb, lambda x: (x["payload"].get("extra") or {}).get("action") == "relations")
    assert len(bots) == 2 and len(relations) == 1
    assert not shown & (bots | relations), (
        "the bot's edit, the bot's commit and the relations line touch nothing"
    )
    assert page.words["2026-09"] == 660, "the bot's +220 words are no words written"
    sauna = ideas.page(lb, ids[SAUNA], today=TODAY)
    assert [p.person for p in sauna.people] == [OLA_ID] and sauna.unplaced == 0, "the call's agent is nobody"


def test_a_collaborator_not_yet_placed_is_counted_on_the_page_and_never_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commit = github("2026-09-19T10:00:00Z", KIOSK_REPO, "committed", "Menu board")
    commit["payload"]["organizer"] = {"kind": "handle", "value": "github:per-example"}
    commit["payload"]["extra"]["actor"] = {"login": "per-example", "type": "User", "name": "Per Nordmann",
                                           "role": "other"}  # fmt: skip
    found = record(tmp_path, monkeypatch, [*ideas_drafts(), commit])
    ids = settle(found)
    page = ideas.page(found, ids[KIOSK], today=TODAY)
    assert [p.name for p in page.people] == ["Ola Nordmann"] and page.unplaced == 1, "by its handle"
    text = "\n".join([*ideas.page_rows(page), *ideas.shelf_rows(ideas.shelf(found, today=TODAY))])
    assert "and 1 not yet placed" in text and "Per" not in text and "per-example" not in text


def test_a_row_the_owner_bound_touches_its_idea_whatever_its_type(lb: Logbook) -> None:
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(entity_review, "uuid7", lambda: "019cadd3-6bc0-7dcd-9133-000000000399")
        entity_review.write_entity(
            lb,
            {"schema": "entity/v1", "entity": {"type": "idea", "id": "019cadd3-6bc0-7dcd-9133-000000000399",
             "registry": "logbook"}, "label": "the tax folder", "method": "owner",
             "refs": [{"kind": "page", "value": f"notion:{TAXES_ROW}"}]},
        )  # fmt: skip
    page = ideas.page(lb, ideas.find(lb, "the tax folder").id, today=TODAY)
    assert [i.what for i in page.timeline] == [
        'created notion "Quarterly taxes / Receipts"',
        'created notion "Ideas / Quarterly taxes"',
    ], "the type keeps a row out of the queue, never out of an idea the owner named"


def test_the_page_never_shows_a_body_or_a_commit_s_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    commit = github("2026-09-15T10:00:00Z", KIOSK_REPO, "committed", "Price list page")
    commit["payload"]["notes"] = "the ferry company's private numbers"
    found = record(tmp_path, monkeypatch, [*ideas_drafts(), commit])
    ids = settle(found)
    text = _run(capsys, "show", "idea", "kiosk") + _run(capsys, "show", "idea", ids[KIOSK], "--json")
    assert 'commit nordmann-verft/fjord-kiosk "Price list page"' in text
    assert "private numbers" not in text and "sha256" not in text


# -- the commands --------------------------------------------------------------------------------------------


def test_show_idea_finds_an_idea_by_a_word_a_ref_or_its_id_and_refuses_the_rest(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    ids = _ids(lb)
    by_word = _run(capsys, "show", "idea", "kiosk")
    assert by_word.startswith(f"{KIOSK} (notion:{KIOSK_ROW}")
    assert _run(capsys, "show", "idea", f"notion:{KIOSK_ROW}") == by_word
    assert json.loads(_run(capsys, "show", "idea", ids[SAUNA], "--json"))["idea"]["label"] == SAUNA
    assert "no idea is" in _refused(capsys, "show", "idea", "rowing club")
    assert "say which idea" in _refused(capsys, "show", "idea")
    assert "takes no name" in _refused(capsys, "show", "ideas", "kiosk")
    assert "is not a year" in _refused(capsys, "show", "ideas", "--year", "26")


def _files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_reading_the_ideas_writes_nothing(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    _run(capsys, "show", "ideas")  # the observed table, built once, is the index's
    head, before = lb.meta["head"], _files(lb.root)
    _run(capsys, "show", "ideas", "--json")
    _run(capsys, "show", "idea", "kiosk", "--json")
    after = _files(lb.root)
    assert Logbook(lb.root).meta["head"] == head
    assert {k: v for k, v in after.items() if not k.startswith("index")} == {
        k: v for k, v in before.items() if not k.startswith("index")
    }
