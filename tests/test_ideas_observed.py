"""What `review idea` observes (RFC 0037 §4.3, `entity_review._ideas`) and what it must not count:
the owner's decisions of 14 October 2026 and the fixes after #303. Each test writes a small
synthetic record (`ideas_record`); nothing is looked up and every name is made up.

- A `relations` line (`sync notion --relations-backfill`) links a row to other rows; it is no touch
  of the row's idea: no line, no day, no sample of it.
- Two roads to a repository main's queue did not read, ported from #292: an act `sync github` wrote
  (its own link, else its `extra.repo`), and a task's own `url` beside its links.
- A bot's line is nobody's (the owner's decision of 14 October 2026): a line whose actor is a bot
  (`sync notion`'s `bot`, `sync github`'s `Bot`) or whose words an agent wrote (`extra.machine`) is
  never a touch of an idea, never a person on one; an agent on a call is no participant.
- A database row is its own root (RFC 0037 §4.3, amended 2026-10-16): a row of a Notion database is
  an idea of its own, never folded into the page that holds the database; a page under a row is
  the row's.
- A row is proposed as an idea only when its `Type` select says `Idea` (the owner's decision of 14
  October 2026; `idea_rows` in `policy/entities.json` names another property and option); a page
  under a row that is no idea is none either, and a page that is no row is a candidate as before."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from ideas_record import (
    CLOCK_REPO,
    GARDEN,
    HUB,
    HUB_PATH,
    IDEA_TYPE,
    KIOSK_REPO,
    KIOSK_ROW,
    OLA,
    OLA_ID,
    PRICING,
    TAXES_ROW,
    TAXES_SUB,
    github,
    notion,
    people,
    record,
    row,
    task,
    transcript,
)

from logbook.contrib import entities, entity_review
from logbook.core.store import Logbook


def _observed(lb: Logbook) -> dict[str, entity_review.Observed]:
    return {o.key[1]: o for o in entity_review.observed(lb, "idea")}


def _ids(lb: Logbook) -> list[str]:
    return [str(line["id"]) for line in Logbook(lb.root).lines() if line.get("kind") != "resolution"]


def _lines(lb: Logbook) -> list[dict[str, Any]]:
    return list(Logbook(lb.root).lines())


def test_a_relations_line_links_a_row_and_is_no_touch_of_its_idea(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drafts = [
        row("2026-09-14T19:00:00Z", KIOSK_ROW, "The fjord kiosk", words=480, properties=IDEA_TYPE),
        row("2026-09-22T08:00:00Z", KIOSK_ROW, "The fjord kiosk", action="relations", who=None,
            relations={"Areas": [GARDEN]}),
    ]  # fmt: skip
    lb = record(tmp_path, monkeypatch, drafts)
    edit, _relations = _ids(lb)
    o = _observed(lb)[f"notion:{KIOSK_ROW}"]
    assert o.lines == 1 and dict(o.kinds) == {"event": 1}, "the relations line is not one more line"
    assert o.days == {"2026-09-14"} and o.first == o.last == "2026-09-14"
    assert [line_id for line_id, _tier in o.samples] == [edit]


# -- repositories (ported from #292) ------------------------------------------------------------------------


def test_an_act_sync_github_wrote_names_its_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drafts = [
        github("2024-04-02T10:00:00Z", KIOSK_REPO, "revised", "README.md", words=90),
        github("2026-09-15T10:00:00Z", KIOSK_REPO, "committed", "Price list page"),
    ]
    lb = record(tmp_path, monkeypatch, drafts)
    o = _observed(lb)[f"github.com/{KIOSK_REPO}"]
    assert o.key == ("repo", f"github.com/{KIOSK_REPO}") and dict(o.sources) == {"github": 2}
    assert o.lines == 2 and o.first == "2024-04-02" and o.last == "2026-09-15"
    assert dict(o.labels) == {KIOSK_REPO: 2}, "a commit's own link and a README's repo name one repository"


def test_a_task_s_own_url_names_its_repository_and_its_title_is_then_no_title(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"https://github.com/{CLOCK_REPO}/issues/2"
    drafts = [
        task("2023-05-08T07:00:00Z", "Tide clock enclosure", url=url),
        task("2023-05-09T07:00:00Z", "Tide clock enclosure", links=[url]),
        transcript("2023-05-10T16:00:00Z", "Tide clock enclosure", "2023-05-10T16:30:00Z"),
    ]
    lb = record(tmp_path, monkeypatch, drafts)
    found = _observed(lb)
    o = found[f"github.com/{CLOCK_REPO}"]
    assert o.lines == 2 and dict(o.kinds) == {"task": 2}, "a task's url, as its links, names the repository"
    assert "clock enclosure tide" not in found, "a task a repository names is that repository's, no title"


# -- a bot's line (the owner's decision of 14 October 2026) --------------------------------------------------


def test_a_notion_line_a_bot_made_is_no_touch_and_shows_no_person(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drafts = [
        *people(),
        row("2026-09-14T19:00:00Z", KIOSK_ROW, "The fjord kiosk", words=480, properties=IDEA_TYPE),
        row("2026-09-21T08:00:00Z", KIOSK_ROW, "The fjord kiosk", who="ola-bot", words=700, delta=220,
            properties=IDEA_TYPE),
        notion("2026-05-01T07:00:00Z", GARDEN, "Garden notes", action="created", who="bot"),
    ]  # fmt: skip
    lb = record(tmp_path, monkeypatch, drafts)
    found = _observed(lb)
    o = found[f"notion:{KIOSK_ROW}"]
    assert o.lines == 1 and o.days == {"2026-09-14"}, "the bot's edit is no touch"
    assert o.people == set(), "an integration named after Ola is a bot, never Ola"
    assert f"notion:{GARDEN}" not in found, "a page only a bot touched is no idea of anyone's"


def test_an_act_a_bot_made_on_github_is_no_touch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    drafts = [
        github("2026-09-15T10:00:00Z", KIOSK_REPO, "committed", "Price list page"),
        github("2026-09-17T03:00:00Z", KIOSK_REPO, "committed", "Bump the toolchain", bot=True),
        github("2026-09-18T03:00:00Z", CLOCK_REPO, "committed", "Bump the toolchain", bot=True),
    ]
    lb = record(tmp_path, monkeypatch, drafts)
    found = _observed(lb)
    assert found[f"github.com/{KIOSK_REPO}"].lines == 1, "the bot's commit is no touch"
    assert f"github.com/{CLOCK_REPO}" not in found, "a repository only a bot touched is no idea"


def test_an_agent_s_line_is_no_touch_and_an_agent_on_a_call_no_person(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drafts = [
        *people(),
        task("2026-08-30T07:00:00Z", "Harbour sauna"),
        task("2026-08-31T07:00:00Z", "Harbour sauna", machine=True),
        transcript("2026-10-03T16:00:00Z", "Harbour sauna", "2026-10-03T16:40:00Z", agent=True, ola=False,
                   agent_email=OLA["email"]),
    ]  # fmt: skip
    lb = record(tmp_path, monkeypatch, drafts)
    o = _observed(lb)["harbour sauna"]
    assert o.lines == 2 and dict(o.sources) == {"gtasks": 1, "granola": 1}, "the agent's task is no touch"
    assert o.people == set(), "an agent on the call is nobody, whatever address it joined under"
    assert OLA_ID not in o.people


# -- a database row is its own root (RFC 0037 §4.3, amended 2026-10-16) -------------------------------------


def test_a_database_row_is_its_own_idea_never_the_page_above_its_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = "1f2e3d4c-0000-4000-8000-000000000033"
    drafts = [
        notion("2024-03-02T18:00:00Z", HUB, "Ines' hub", action="created"),
        row("2024-03-04T19:00:00Z", KIOSK_ROW, "The fjord kiosk", action="created", properties=IDEA_TYPE),
        row("2024-03-05T19:00:00Z", other, "The tide clock", action="created", properties=IDEA_TYPE),
        notion("2026-09-20T17:00:00Z", PRICING, "Pricing", action="created", who="ola",
               parent={"type": "page", "id": KIOSK_ROW}, path=[*HUB_PATH, "The fjord kiosk"]),
    ]  # fmt: skip
    lb = record(tmp_path, monkeypatch, drafts)
    found = _observed(lb)
    assert set(found) == {f"notion:{HUB}", f"notion:{KIOSK_ROW}", f"notion:{other}"}, (
        "each row of the Ideas database is an idea of its own, and the page that holds the database another"
    )
    assert found[f"notion:{HUB}"].lines == 1, "no row folds into the page above its database"
    kiosk = found[f"notion:{KIOSK_ROW}"]
    assert kiosk.lines == 2 and ("page", f"notion:{PRICING}") in kiosk.identifiers, (
        "a page under a row is the row's"
    )
    assert dict(kiosk.labels) == {"The fjord kiosk": 2}


def test_a_row_of_a_later_api_s_data_source_is_its_own_root_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = "1f2e3d4c-0000-4000-8000-0000000000d5"
    drafts = [
        notion("2024-03-02T18:00:00Z", HUB, "Ines' hub", action="created"),
        notion("2024-03-04T19:00:00Z", KIOSK_ROW, "The fjord kiosk", action="created",
               parent={"type": "data_source", "id": source}, path=HUB_PATH, properties=IDEA_TYPE),
        notion("2026-09-20T17:00:00Z", PRICING, "Pricing", action="created",
               parent={"type": "page", "id": KIOSK_ROW}, path=[*HUB_PATH, "The fjord kiosk"]),
    ]  # fmt: skip
    lb = record(tmp_path, monkeypatch, drafts)
    found = _observed(lb)
    assert set(found) == {f"notion:{HUB}", f"notion:{KIOSK_ROW}"}
    assert found[f"notion:{KIOSK_ROW}"].lines == 2


# -- a row is an idea only when its `Type` says so (the owner's decision of 14 October 2026) -------------


def test_a_row_is_proposed_as_an_idea_only_when_its_type_is_idea(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    turned = "1f2e3d4c-0000-4000-8000-000000000034"
    bare = "1f2e3d4c-0000-4000-8000-000000000035"
    drafts = [
        row("2024-03-04T19:00:00Z", KIOSK_ROW, "The fjord kiosk", action="created",
            properties={"Status": "Open", **IDEA_TYPE}),
        row("2025-01-10T09:00:00Z", TAXES_ROW, "Quarterly taxes", action="created",
            properties={"Type": "Task"}),
        notion("2025-01-11T09:00:00Z", TAXES_SUB, "Receipts", action="created",
               parent={"type": "page", "id": TAXES_ROW}, path=[*HUB_PATH, "Quarterly taxes"]),
        row("2025-02-01T09:00:00Z", turned, "Boat share", action="created", properties=IDEA_TYPE),
        row("2025-06-01T09:00:00Z", turned, "Boat share", properties={"Type": "Task"}),
        row("2025-03-01T09:00:00Z", bare, "Untyped row", action="created"),
        notion("2026-05-01T07:00:00Z", GARDEN, "Garden notes", action="created"),
    ]  # fmt: skip
    lb = record(tmp_path, monkeypatch, drafts)
    assert set(_observed(lb)) == {f"notion:{KIOSK_ROW}", f"notion:{GARDEN}"}, (
        "an Idea row, and a page that is no row as before: never a Task row, the page under it, a row"
        " whose Type is no longer Idea, or a row that says no Type"
    )


def test_the_type_select_and_its_option_are_the_record_s_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drafts = [
        row("2024-03-04T19:00:00Z", KIOSK_ROW, "The fjord kiosk", action="created", properties=IDEA_TYPE),
        row(
            "2025-01-10T09:00:00Z",
            TAXES_ROW,
            "Quarterly taxes",
            action="created",
            properties={"kind": "spark"},
        ),
    ]
    lb = record(tmp_path, monkeypatch, drafts, settings={"idea_rows": {"property": "Kind", "value": "Spark"}})
    assert set(_observed(lb)) == {f"notion:{TAXES_ROW}"}, "the setting's property and option, case aside"
    assert entities.read_settings(lb.root).idea_rows == ("Kind", "Spark")
    assert entities.read_settings(tmp_path).idea_rows == ("Type", "Idea"), "the default"


@pytest.mark.parametrize("value", [{"property": "Type"}, {"property": "", "value": "Idea"}, ["Type", "Idea"]])
def test_a_setting_that_names_no_property_and_option_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: Any
) -> None:
    lb = record(tmp_path, monkeypatch, [], settings={"idea_rows": value})
    with pytest.raises(entities.EntityError, match="idea_rows"):
        entities.read_settings(lb.root)


# -- what the mutation check of these rules asked for --------------------------------------------------------


def test_a_row_of_a_data_source_is_a_row_the_type_filter_holds_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = "1f2e3d4c-0000-4000-8000-0000000000d5"
    drafts = [
        notion("2025-01-10T09:00:00Z", TAXES_ROW, "Quarterly taxes", action="created",
               parent={"type": "data_source", "id": source}, path=HUB_PATH, properties={"Type": "Task"}),
        notion("2025-01-11T09:00:00Z", TAXES_SUB, "Receipts", action="created",
               parent={"type": "page", "id": TAXES_ROW}, path=[*HUB_PATH, "Quarterly taxes"]),
    ]  # fmt: skip
    lb = record(tmp_path, monkeypatch, drafts)
    assert _observed(lb) == {}, (
        "a row of a data source is a row: a Task row is no idea, nor the page under it"
    )


def test_the_latest_line_is_by_instant_not_by_the_order_the_lines_reached_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    turned = "1f2e3d4c-0000-4000-8000-000000000034"
    drafts = [  # each row's earlier edit reaches the record after its later one, in the same month
        row("2025-06-20T09:00:00Z", KIOSK_ROW, "The fjord kiosk", properties={"Type": "Task"}),
        row("2025-06-02T09:00:00Z", KIOSK_ROW, "The fjord kiosk", action="created", properties=IDEA_TYPE),
        row("2025-06-20T09:00:00Z", turned, "Boat share", properties=IDEA_TYPE),
        row("2025-06-02T09:00:00Z", turned, "Boat share", action="created", properties={"Type": "Task"}),
    ]
    lb = record(tmp_path, monkeypatch, drafts)
    assert set(_observed(lb)) == {f"notion:{turned}"}, "the Type as of the latest edit by its instant"


def test_idea_people_shows_nobody_on_a_bot_s_line_even_under_a_person_s_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drafts = [
        *people(),
        row("2026-09-21T08:00:00Z", KIOSK_ROW, "The fjord kiosk", who="ola", properties=IDEA_TYPE),
        row("2026-09-22T08:00:00Z", KIOSK_ROW, "The fjord kiosk", who="ola-bot", properties=IDEA_TYPE),
    ]
    lb = record(tmp_path, monkeypatch, drafts)
    with lb.index() as idx:
        ctx = entity_review.context(lb, idx)
        ola, bot = list(ctx.standing(idx, "event"))
        assert entity_review.idea_people("event", ola, ctx) == {OLA_ID}
        assert entity_review.idea_people("event", bot, ctx) == set()


def test_a_relations_line_still_shapes_the_tree_as_the_latest_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drafts = [
        row("2026-09-14T19:00:00Z", KIOSK_ROW, "The fjord kiosk", properties=IDEA_TYPE),
        row("2026-09-22T08:00:00Z", KIOSK_ROW, "The fjord kiosk and cafe", action="relations", who=None,
            relations={"Areas": []}),
    ]  # fmt: skip
    lb = record(tmp_path, monkeypatch, drafts)
    o = _observed(lb)[f"notion:{KIOSK_ROW}"]
    assert o.lines == 1 and dict(o.labels) == {"The fjord kiosk and cafe": 1}, "its title, not a touch"
