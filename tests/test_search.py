"""`logbook search TEXT`: full-text search through the FTS5 table of index.sqlite — literal words,
phrases in quotes, the tier guard, a window and a cut of kinds, results grouped by day with the row
`show` prints and a snippet; a line appended after the index was built is found without a rebuild."""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import cli
from logbook.core import index, search
from logbook.core.store import Logbook

TZ = "Europe/Oslo"  # CEST in June: 18:00Z is 20:00 local
TRANSCRIPT = "Speaker A: We will ship the search feature by Friday.\nSpeaker B: Fine, Friday then.\n"
MAIL_ROW = (
    "  11:00  mail       mail           ✉ Zürich hotel booking — Hotel Example → "
    + "kari.nordmann@example.org"
)
MAIL_SNIPPET = (
    "…reservations@example.org · Hotel Example · Zürich hotel booking · " + "[kari].nordmann@example.org"
)


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """A synthetic week of the Oslo persona, who does not exist: a note, a message, a mail, a calendar
    entry, a tier-3 transcript whose text is in the attachment store, a second note, a retracted note
    and a location point. No index yet."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append(
        at="2026-06-10T18:00:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "text": "Dinner with Kari at the cafe, running late"},
    )
    lb.append(
        at="2026-06-11T07:00:00Z",
        source="whatsapp",
        kind="message",
        tier=2,
        payload={
            "schema": "message/v1",
            "raw_id": "wa:1",
            "chat": {"id": "4790000001@s.whatsapp.net", "type": "direct", "name": "Ola Nordmann"},
            "from_me": False,
            "sender": {"kind": "phone", "value": "+4790000001", "name": "Ola"},
            "text": "Are we still on for the Zürich trip?",
        },
    )
    lb.append(
        at="2026-06-11T09:00:00Z",
        source="mail",
        kind="mail",
        tier=2,
        payload={
            "schema": "mail/v1",
            "raw_id": "m:1",
            "thread": "m:1",
            "from": {"email": "reservations@example.org", "name": "Hotel Example"},
            "to": [{"email": "kari.nordmann@example.org"}],
            "subject": "Zürich hotel booking",
            "direction": "received",
            "body": "Your room at the Hotel Example is confirmed.",
            "size": 512,
        },
    )
    lb.append(
        at="2026-06-12T08:00:00Z",
        source="ics",
        kind="event",
        tier=1,
        payload={
            "schema": "event/v1",
            "raw_id": "e:1",
            "title": "Standup",
            "all_day": False,
            "location": "Office",
            "notes": "weekly standup with the team",
        },
    )
    stored = lb.attach(TRANSCRIPT.encode("utf-8"))
    lb.append(
        at="2026-06-12T13:00:00Z",
        source="granola",
        kind="transcript",
        tier=3,
        payload={
            "schema": "transcript/v1",
            "provider": "granola",
            "raw_id": "g:1",
            "title": "Client call",
            "participants": [{"name": "Speaker A"}],
            "content": {
                "sha256": stored.name,
                "path": f"attachments/{stored.name}",
                "bytes": len(TRANSCRIPT.encode("utf-8")),
                "media_type": "text/plain",
            },
        },
    )
    lb.append(
        at="2026-06-13T10:00:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "text": "Kari said the run was good"},
    )
    lb.append(
        at="2026-06-13T11:00:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "text": "secret dinner plan"},
    )
    lb.retract(7, "never happened")
    lb.append(
        at="2026-06-13T12:00:00Z",
        source="dawarich",
        kind="location",
        tier=1,
        payload={"schema": "location/v1", "lat": 59.91, "lon": 10.75, "extra": {"place": {"city": "Oslo"}}},
    )
    return lb


def _search(capsys: pytest.CaptureFixture[str], *args: str) -> list[str]:
    cli.main(["search", *args])
    return capsys.readouterr().out.splitlines()


def _rows(lb: Logbook, sql: str) -> list[tuple[Any, ...]]:
    with closing(sqlite3.connect(lb.index_path)) as db:
        return list(db.execute(sql))


def _tamper(lb: Logbook, *sql: str) -> None:
    with closing(sqlite3.connect(lb.index_path)) as db:
        for statement in sql:
            db.execute(statement)
        db.commit()


# -- the index ----------------------------------------------------------------------------------------


def test_index_command_builds_the_search_table_for_the_lines_that_carry_text(lb: Logbook, capsys):
    cli.main(["repair", "index"])
    assert "indexed 9 lines" in capsys.readouterr().out
    tables = {r[0] for r in _rows(lb, "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "search" in tables
    # the note, the message, the mail, the event, the transcript, the second note, the retracted note;
    # never the retraction, never the location point
    assert _rows(lb, "SELECT rowid, kind, tier, day FROM search ORDER BY rowid") == [
        (1, "note", 2, "2026-06-10"),
        (2, "message", 2, "2026-06-11"),
        (3, "mail", 2, "2026-06-11"),
        (4, "event", 1, "2026-06-12"),
        (5, "transcript", 3, "2026-06-12"),
        (6, "note", 2, "2026-06-13"),
        (7, "note", 2, "2026-06-13"),
    ]
    assert _rows(lb, "SELECT value FROM meta WHERE key = 'schema'") == [(index.SCHEMA_VERSION,)]


def test_an_index_built_by_the_previous_schema_is_rebuilt_once_with_the_search_table(lb: Logbook, capsys):
    cli.main(["repair", "index"])
    capsys.readouterr()
    _tamper(lb, "DROP TABLE search", "UPDATE meta SET value = '5' WHERE key = 'schema'")
    assert _search(capsys, "kari")[0].startswith("2026-06-")
    assert _rows(lb, "SELECT count(*) FROM search") == [(7,)]
    assert _rows(lb, "SELECT value FROM meta WHERE key = 'schema'") == [(index.SCHEMA_VERSION,)]


def test_a_line_appended_after_the_index_was_built_is_found_without_a_rebuild(
    lb: Logbook, monkeypatch, capsys
):
    with lb.index():
        pass

    def no_rebuild(self: index.Index, progress: Any = None) -> int:
        raise AssertionError("the index was current; nothing should rebuild it")

    monkeypatch.setattr(index.Index, "rebuild", no_rebuild)
    lb.append(
        at="2026-06-14T09:00:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "text": "a unicorn on the fjord"},
    )
    lb.append_many(
        [
            {
                "at": "2026-06-14T10:00:00Z",
                "source": "manual",
                "kind": "note",
                "tier": 2,
                "payload": {"schema": "note/v1", "text": "a second unicorn, by append_many"},
            }
        ]
    )
    out = _search(capsys, "unicorn")
    assert out[0] == "2026-06-14 Sunday"
    assert "a unicorn on the fjord" in out[1] and "a second unicorn, by append_many" in out[3]
    assert "2 hits" in out[-1]


def test_a_line_with_no_words_is_not_in_the_search_table(lb: Logbook):
    lb.append(
        at="2026-06-14T09:00:00Z",
        source="whatsapp",
        kind="message",
        tier=2,
        payload={
            "schema": "message/v1",
            "raw_id": "wa:2",
            "chat": {"id": "x@g.us", "type": "group"},
            "from_me": True,
            "media_kind": "image",
        },
    )
    with lb.index():
        pass
    assert _rows(lb, "SELECT count(*) FROM search WHERE rowid = 10") == [(0,)]


# -- the command --------------------------------------------------------------------------------------


def test_search_groups_hits_by_day_with_the_row_show_prints_and_a_snippet(lb: Logbook, capsys):
    out = _search(capsys, "kari")
    cli.main(["show", "2026-06-10"])
    shown = capsys.readouterr().out.splitlines()
    assert out[0] == "2026-06-13 Saturday"
    assert out[1] == "  12:00  note       manual         Kari said the run was good"
    assert out[2] == "         [Kari] said the run was good"
    assert out[3] == "2026-06-11 Thursday"  # the mail is to Kari
    assert out[4] == MAIL_ROW
    assert out[5] == f"         {MAIL_SNIPPET}"
    assert out[6] == "2026-06-10 Wednesday"
    assert (
        out[7] == shown[1] == "  20:00  note       manual         Dinner with Kari at the cafe, running late"
    )
    assert out[8] == "         Dinner with [Kari] at the cafe, running late"
    assert out[9] == "3 hits in 3 days"


def test_search_is_literal_no_stemming_but_case_and_accents_aside(lb: Logbook, capsys):
    assert [r for r in _search(capsys, "run") if r.startswith("  ")] == [
        "  12:00  note       manual         Kari said the run was good",
        "         Kari said the [run] was good",
    ]
    assert [r for r in _search(capsys, "running") if r.startswith("  ")] == [
        "  20:00  note       manual         Dinner with Kari at the cafe, running late",
        "         Dinner with Kari at the cafe, [running] late",
    ]
    out = _search(capsys, "zurich")
    assert out[0] == "2026-06-11 Thursday"
    assert [r for r in out if r.startswith("  ") and not r.startswith("   ")] == [
        "  09:00  message    whatsapp       Ola: Are we still on for the Zürich trip?",
        MAIL_ROW,
    ]
    assert "[Zürich]" in out[2] and "[Zürich]" in out[4]


def test_search_a_phrase_in_quotes_must_appear_in_that_order(lb: Logbook, capsys):
    assert _search(capsys, '"with kari"')[1].endswith("Dinner with Kari at the cafe, running late")
    assert _search(capsys, '"kari with"')[0] == 'nothing matches: "kari with"'
    assert _search(capsys, "kari dinner")[1].endswith("Dinner with Kari at the cafe, running late")
    assert _search(capsys, "kari dinner")[-1] == "1 hit in 1 day"


def test_search_cuts_the_kinds_and_the_window(lb: Logbook, capsys):
    out = _search(capsys, "zürich", "--kinds", "mail")
    assert len(out) == 4 and "mail" in out[1] and "whatsapp" not in "".join(out)
    out = _search(capsys, "kari", "--since", "2026-06-12")
    assert out[0] == "2026-06-13 Saturday" and out[-1] == "1 hit in 1 day"
    out = _search(capsys, "kari", "--until", "2026-06-12")
    assert [r for r in out if not r.startswith(" ")] == [
        "2026-06-11 Thursday",
        "2026-06-10 Wednesday",
        "2 hits in 2 days",
    ]
    out = _search(capsys, "kari", "--since", "2026-06-11", "--until", "2026-06-12")
    assert out[0] == "2026-06-11 Thursday" and out[-1] == "1 hit in 1 day"
    assert (
        _search(capsys, "kari", "--since", "2026-06-12", "--until", "2026-06-12")[0]
        == "nothing matches: kari"
    )


def test_search_tier_3_only_with_the_flag(lb: Logbook, capsys):
    assert _search(capsys, "ship") == [
        "nothing matches: ship",
        "tier 3 was not searched; --tier 3 includes it",
    ]
    out = _search(capsys, "ship", "--tier", "3")
    assert out[0] == "2026-06-12 Friday"
    assert out[1] == "  15:00  transcript granola        Client call — Speaker A"
    assert out[2].startswith(
        "         …We will [ship] the search feature by Friday. · Speaker B: Fine, Friday then."
    )
    assert out[-1] == "1 hit in 1 day"
    assert _search(capsys, "standup", "--tier", "1")[-1] == "1 hit in 1 day"
    assert _search(capsys, "kari", "--tier", "1")[0] == "nothing matches: kari"


def test_search_a_retracted_line_is_never_a_hit(lb: Logbook, capsys):
    assert _search(capsys, "secret")[0] == "nothing matches: secret"
    assert _search(capsys, "dinner")[-1] == "1 hit in 1 day"


def test_search_reads_no_location_point(lb: Logbook, capsys):
    assert _search(capsys, "oslo")[0] == "nothing matches: oslo"


def test_search_takes_fts5_operators_as_words_never_as_syntax(lb: Logbook, capsys):
    for text in ("kari OR ola", "kari NOT dinner", "kind:note", "^kari", "kari AND", '"unbalanced', "kari -"):
        assert _search(capsys, text)[0] in (f"nothing matches: {text}", "2026-06-13 Saturday"), text
    assert _search(capsys, "kari OR ola")[0] == "nothing matches: kari OR ola"
    assert _search(capsys, '"unbalanced')[0] == 'nothing matches: "unbalanced'
    assert _search(capsys, "kar*")[-1] == "3 hits in 3 days"


def test_search_json(lb: Logbook, capsys):
    cli.main(["search", "kari", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["query"] == {
        "text": "kari",
        "expression": '"kari"',
        "since": None,
        "until": None,
        "kinds": None,
        "max_tier": 2,
        "limit": search.LIMIT,
        "standing": False,
    }
    assert data["hits"] == 3 and data["more"] is False
    assert [d["day"] for d in data["days"]] == ["2026-06-13", "2026-06-11", "2026-06-10"]
    hit = data["days"][2]["lines"][0]
    assert hit["seq"] == 1 and hit["kind"] == "note" and hit["source"] == "manual" and hit["tier"] == 2
    assert hit["at"] == "2026-06-10T18:00:00Z" and len(hit["id"]) == 36
    assert hit["summary"] == "Dinner with Kari at the cafe, running late"
    assert hit["snippet"] == "Dinner with [Kari] at the cafe, running late"
    assert isinstance(hit["rank"], float) and hit["rank"] < 0


def test_search_refuses_an_empty_query_an_unknown_kind_and_a_backwards_window(lb: Logbook, capsys):
    for args in (
        ['""'],
        ["   "],
        ["kari", "--kinds", "location"],
        ["kari", "--since", "2026-06-13", "--until", "2026-06-10"],
    ):
        with pytest.raises(SystemExit) as e:
            cli.main(["search", *args])
        assert e.value.code == 2, args
        assert capsys.readouterr().err.startswith("search: ")


def test_search_limit_says_when_it_was_reached(lb: Logbook, capsys):
    out = _search(capsys, "kari", "--limit", "1")
    assert out[1] == "  12:00  note       manual         Kari said the run was good"  # the best by bm25
    assert out[-1] == "1 hit in 1 day; the first 1 by rank, --limit for more"
    cli.main(["search", "kari", "--limit", "2", "--json"])
    assert json.loads(capsys.readouterr().out)["more"] is True


# -- standing: a hit a later line of its kind supersedes is marked, and `--standing` leaves it out ----


def _correct_the_dinner(lb: Logbook) -> int:
    """Kari's dinner moved: a note on the 14th that supersedes the note of the 10th (seq 1); its seq."""
    first = lb.line_by_seq(1)
    assert first is not None
    line = lb.append(
        at="2026-06-14T16:00:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload={
            "schema": "note/v1",
            "text": "Dinner with Kari moved to the marina",
            "supersedes": first["id"],
        },
    )
    return int(line["seq"])


def _hits(capsys: pytest.CaptureFixture[str], *args: str) -> dict[int, dict[str, Any]]:
    cli.main(["search", *args, "--json"])
    data = json.loads(capsys.readouterr().out)
    return {hit["seq"]: hit for day in data["days"] for hit in day["lines"]}


def test_search_marks_a_note_a_later_note_supersedes(lb: Logbook, capsys):
    later = _correct_the_dinner(lb)
    out = _search(capsys, "dinner")
    assert out == [
        "2026-06-14 Sunday",
        "  18:00  note       manual         Dinner with Kari moved to the marina",
        "         [Dinner] with Kari moved to the marina",
        "2026-06-10 Wednesday",
        "  20:00  note       manual         Dinner with Kari at the cafe, running late"
        + f" · superseded by #{later}",
        "         [Dinner] with Kari at the cafe, running late",
        "2 hits in 2 days",
    ]


def test_search_a_standing_hit_has_no_mark(lb: Logbook, capsys):
    out = _search(capsys, "run")
    assert out[1] == "  12:00  note       manual         Kari said the run was good"
    assert not any("superseded" in row for row in out)
    hit = _hits(capsys, "run")[6]
    assert hit["standing"] is True and hit["superseded_by"] is None


def test_search_json_says_standing_and_superseded_by(lb: Logbook, capsys):
    later = _correct_the_dinner(lb)
    superseder = lb.line_by_seq(later)
    assert superseder is not None
    hits = _hits(capsys, "dinner")
    assert hits[1]["standing"] is False and hits[1]["superseded_by"] == superseder["id"]
    assert hits[later]["standing"] is True and hits[later]["superseded_by"] is None
    cli.main(["search", "dinner", "--json"])
    assert json.loads(capsys.readouterr().out)["query"]["standing"] is False


def test_search_standing_shows_standing_hits_only(lb: Logbook, capsys):
    later = _correct_the_dinner(lb)
    out = _search(capsys, "dinner", "--standing")
    assert out == [
        "2026-06-14 Sunday",
        "  18:00  note       manual         Dinner with Kari moved to the marina",
        "         [Dinner] with Kari moved to the marina",
        "1 hit in 1 day",
    ]
    assert list(_hits(capsys, "dinner", "--standing")) == [later]
    cli.main(["search", "dinner", "--standing", "--json"])
    assert json.loads(capsys.readouterr().out)["query"]["standing"] is True


def test_search_standing_fills_the_limit_with_standing_hits(lb: Logbook, capsys):
    _correct_the_dinner(lb)  # kari: the corrected note, the second note, the mail, the superseded note
    assert len(_hits(capsys, "kari")) == 4
    for limit in ("1", "2", "3"):
        cli.main(["search", "kari", "--standing", "--limit", limit, "--json"])
        data = json.loads(capsys.readouterr().out)
        hits = [hit for day in data["days"] for hit in day["lines"]]
        assert len(hits) == data["hits"] == int(limit) and data["more"] is True, limit
        assert all(hit["standing"] for hit in hits) and 1 not in {hit["seq"] for hit in hits}
    cli.main(["search", "kari", "--standing", "--limit", "4", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["hits"] == 3 and data["more"] is False


def test_search_a_retracted_superseder_supersedes_nothing(lb: Logbook, capsys):
    later = _correct_the_dinner(lb)
    lb.retract(later, "the dinner did not move")
    out = _search(capsys, "dinner")
    assert out[-1] == "1 hit in 1 day"  # the retracted correction is never a hit
    assert out[1] == "  20:00  note       manual         Dinner with Kari at the cafe, running late"
    assert _hits(capsys, "dinner", "--standing")[1]["standing"] is True


def test_search_a_retracted_line_is_never_a_hit_marked_or_not(lb: Logbook, capsys):
    for args in (["secret"], ["secret", "--standing"]):
        assert _search(capsys, *args)[0] == "nothing matches: secret"
    assert _hits(capsys, "secret") == {}


def test_search_gives_an_index_built_before_the_supersedes_index_that_index_once(lb: Logbook, capsys):
    later = _correct_the_dinner(lb)
    _search(capsys, "dinner")  # the index is current
    _tamper(lb, "DROP INDEX lines_kind_supersedes")
    indexes = "SELECT name FROM sqlite_master WHERE type = 'index'"
    assert "lines_kind_supersedes" not in {r[0] for r in _rows(lb, indexes)}
    assert _search(capsys, "dinner")[4].endswith(f" · superseded by #{later}")
    assert "lines_kind_supersedes" in {r[0] for r in _rows(lb, indexes)}  # the mark asks it


def test_search_a_superseder_of_another_kind_marks_nothing(lb: Logbook, capsys):
    first = lb.line_by_seq(1)
    assert first is not None
    lb.append(
        at="2026-06-14T16:00:00Z",
        source="manual",
        kind="task",
        tier=2,
        payload={"schema": "task/v1", "title": "book the marina table", "supersedes": first["id"]},
    )
    assert _hits(capsys, "dinner")[1]["standing"] is True
    assert not any("superseded" in row for row in _search(capsys, "dinner"))


def _solvind_berths(lb: Logbook) -> tuple[list[int], int]:
    """Three short notes about the yacht Solvind, each superseded by a correction without the word,
    and one long note that stands: the superseded ones rank first (bm25 favours a short line)."""
    superseded = []
    for n, day in enumerate(("2026-06-15", "2026-06-16", "2026-06-17")):
        line = lb.append(
            at=f"{day}T08:00:00Z",
            source="manual",
            kind="note",
            tier=2,
            payload={"schema": "note/v1", "text": "Solvind"},
        )
        superseded.append(int(line["seq"]))
        lb.append(
            at=f"{day}T09:00:00Z",
            source="manual",
            kind="note",
            tier=2,
            payload={"schema": "note/v1", "text": f"the yacht moved to berth {n}", "supersedes": line["id"]},
        )
    standing = lb.append(
        at="2026-06-18T08:00:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload={
            "schema": "note/v1",
            "text": "Per Hansen and Ola sailed Solvind out of the fjord past the cabins",
        },
    )
    return superseded, int(standing["seq"])


def test_search_standing_asks_again_until_the_limit_holds_standing_hits(lb: Logbook, capsys):
    superseded, standing = _solvind_berths(lb)
    cli.main(["search", "solvind", "--limit", "1", "--json"])
    best = json.loads(capsys.readouterr().out)["days"][0]["lines"][0]
    assert best["seq"] in superseded and best["standing"] is False  # the superseded ones rank first
    assert list(_hits(capsys, "solvind", "--standing", "--limit", "1")) == [standing]
    assert list(_hits(capsys, "solvind", "--standing")) == [standing]
    assert len(_hits(capsys, "solvind")) == 4


def test_superseded_by_takes_the_rule_index_superseded_reads_by(lb: Logbook):
    first, second = lb.line_by_seq(1), lb.line_by_seq(6)
    assert first is not None and second is not None
    corrections = []
    for at, text in (
        ("2026-06-14T08:00:00Z", "dinner moved"),
        ("2026-06-14T09:00:00Z", "dinner moved again"),
    ):
        line = lb.append(
            at=at,
            source="manual",
            kind="note",
            tier=2,
            payload={"schema": "note/v1", "text": text, "supersedes": first["id"]},
        )
        corrections.append(line)
    wrong = lb.append(
        at="2026-06-14T10:00:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "text": "the run was bad", "supersedes": second["id"]},
    )
    lb.retract(int(wrong["seq"]), "it was good")  # a retracted superseder supersedes nothing
    lb.append(
        at="2026-06-14T11:00:00Z",
        source="manual",
        kind="task",
        tier=2,
        payload={"schema": "task/v1", "title": "write it up", "supersedes": second["id"]},  # another kind
    )
    with lb.index() as idx:
        lines = idx.by_kind("note")
        by = search.superseded_by(idx, lines)
        rule = idx.superseded("note")
    latest = corrections[1]  # superseded twice: the last in chain order is the one that stands
    assert rule == {first["id"]: int(latest["seq"])}
    assert by == {1: (int(latest["seq"]), latest["id"])}


# -- the module ---------------------------------------------------------------------------------------


def test_expression_quotes_every_word_and_keeps_phrases_and_prefixes():
    assert search.expression("kari") == '"kari"'
    assert search.expression("Kari  Nordmann") == '"Kari" "Nordmann"'
    assert search.expression('"with kari" late') == '"with kari" "late"'
    assert search.expression('kar* "zür*') == '"kar" * "zür" *'
    assert search.expression('"with kar*"') == '"with kar" *'
    assert search.expression('say "hi" there') == '"say" "hi" "there"'
    assert search.expression("kari OR ola") == '"kari" "OR" "ola"'
    assert search.expression("kind:note") == '"kind:note"'
    assert search.expression("a - b") == '"a" "b"'
    assert (
        search.expression("") is None and search.expression('""') is None and search.expression("- *") is None
    )


def test_body_of_gathers_the_words_of_a_payload_and_never_its_ids():
    line = {
        "kind": "message",
        "payload": {
            "schema": "message/v1",
            "raw_id": "wa:1",
            "chat": {"id": "4790000001@s.whatsapp.net", "type": "direct", "name": "Ola Nordmann"},
            "sender": {"kind": "phone", "value": "+4790000001", "name": "Ola"},
            "text": "hello",
            "media": {
                "sha256": "a" * 64,
                "path": "attachments/" + "a" * 64,
                "bytes": 3,
                "media_type": "image/png",
            },
        },
    }
    body = search.body_of(line, None)
    assert body is not None
    assert body.split("\n") == ["Ola Nordmann", "+4790000001", "Ola", "hello"]
    assert (
        search.body_of(
            {"kind": "location", "payload": {"schema": "location/v1", "extra": {"place": {"city": "Oslo"}}}},
            None,
        )
        is None
    )


# -- scale --------------------------------------------------------------------------------------------

BIG = 2_000_000
WORDS = ("fjord", "cabin", "office", "marina", "standup", "dinner", "flight", "hotel", "sailing", "kari")


def _big_drafts(n: int):
    from datetime import UTC, datetime

    start, step = 1_500_000_000, (8 * 365 * 86400) // n
    for i in range(n):
        at = datetime.fromtimestamp(start + i * step, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        words = " ".join(WORDS[(i * k) % len(WORDS)] for k in (1, 3, 7))
        text = f"synthetic line {i} about the {words}" + (" unicorn" if i % 400_000 == 7 else "")
        yield {
            "at": at,
            "source": "sim",
            "kind": "note",
            "tier": 2,
            "payload": {"schema": "note/v1", "raw_id": f"sim-{i}", "text": text},
        }


@pytest.mark.stress  # asserts wall time: a benchmark of the machine, never of CI (LOGBOOK_STRESS=1)
def test_search_answers_in_under_a_second_on_two_million_lines(tmp_path: Path, monkeypatch, capsys):
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    started = time.perf_counter()
    assert lb.append_many(_big_drafts(BIG)) == BIG
    print(f"\nbuilt {BIG:,} lines in {time.perf_counter() - started:.0f}s")
    timings = []
    for args in (
        ["unicorn"],
        ["fjord cabin"],
        ['"the kari"', "--since", "2020-01-01", "--until", "2020-12-31"],
    ):
        started = time.perf_counter()
        out = _search(capsys, *args)
        timings.append((args, time.perf_counter() - started, out[-1]))
    for args, elapsed, footer in timings:
        print(f"search {' '.join(args)}: {elapsed:.2f}s, {footer}")
        assert elapsed < 1.0, (args, elapsed)
