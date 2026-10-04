"""story/v1 (RFC 0028): `logbook add story <file>` writes one told story per file, `show` prints it
on the day it was told, and `day <date>` lists the stories about that date apart from the
timeline. Synthetic: Ola Nordmann tells, Kari Nordmann listens; neither exists."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from persona import KARI, KARI_ID, OLA, OLA_ID, TZ, persona_record, resolution

from logbook import cli
from logbook.core import story
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "story"
LAKE = FIXTURES / "house-by-the-lake.md"
BEES = FIXTURES / "before-the-war.txt"
BOAT = FIXTURES / "told-on-the-boat.json"
BOOK = "\U0001f4d6"  # 📖
TOLD_BY = f"{BOOK} refers to 1961 — told by Ola Nordmann to Kari Nordmann"
LAKE_FIRST = "In 1961 we moved to the house by the lake. Father rowed the furniture across in two"
LAKE_CUT = LAKE_FIRST[:71] + "\u2026"  # the Day cuts a first line at 72 characters, as it does a note's


def _people() -> list[dict[str, Any]]:
    return [
        resolution(("email", KARI["email"]), KARI_ID, "Kari Nordmann"),
        resolution(("phone", KARI["phone"]), KARI_ID, "Kari Nordmann"),
        resolution(("email", OLA["email"]), OLA_ID, "Ola Nordmann"),
        resolution(("phone", OLA["phone"]), OLA_ID, "Ola Nordmann"),
    ]


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(_people())
    return lb


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main([*args])
    return capsys.readouterr().out


def _fails(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    with pytest.raises(SystemExit) as e:
        cli.main([*args])
    assert e.value.code == 2
    return capsys.readouterr().err


def _stories(lb: Logbook) -> list[dict[str, Any]]:
    return [line for line in lb.lines() if line["kind"] == "story"]


def _raw_id(path: Path) -> str:
    return f"story:{hashlib.sha256(path.read_bytes()).hexdigest()}"


# -- the grammar of refers_to ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("1961", {"text": "1961", "from": "1961-01-01", "to": "1961-12-31", "precision": "year"}),
        ("1961-05", {"text": "1961-05", "from": "1961-05-01", "to": "1961-05-31", "precision": "month"}),
        ("1961-05-04", {"text": "1961-05-04", "from": "1961-05-04", "to": "1961-05-04", "precision": "day"}),
        ("1950s", {"text": "1950s", "from": "1950-01-01", "to": "1959-12-31", "precision": "decade"}),
        ("before the war", {"text": "before the war", "from": None, "to": None, "precision": "phrase"}),
        ("  Before  the war ", {"text": "Before the war", "from": None, "to": None, "precision": "phrase"}),
    ],
)
def test_refers_to_reads_a_year_a_month_a_day_a_decade_or_a_phrase(
    given: str, expected: dict[str, Any]
) -> None:
    assert story.parse_refers_to(given) == expected


@pytest.mark.parametrize("given", ["196", "1961-13", "1961-5", "1961-02-30", "19500s", "1961s", "", "   "])
def test_refers_to_refuses_what_looks_like_a_date_but_is_not(given: str) -> None:
    with pytest.raises(ValueError):
        story.parse_refers_to(given)


def test_a_story_covers_every_day_of_its_span_and_a_phrase_covers_none() -> None:
    decade = story.parse_refers_to("1950s")
    assert story.covers(decade, "1950-01-01") and story.covers(decade, "1955-03-02")
    assert story.covers(decade, "1959-12-31") and not story.covers(decade, "1960-01-01")
    assert not story.covers(story.parse_refers_to("before the war"), "1939-01-01")
    assert not story.covers(None, "1939-01-01")


# -- add story -----------------------------------------------------------------------------------------------


def test_add_story_from_markdown_takes_every_field_from_the_front_matter(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _run(capsys, "add", "story", str(LAKE))
    assert out.splitlines() == [f"#5 2026-06-10T18:30:00Z  story {TOLD_BY}"]
    (line,) = _stories(lb)
    assert (line["source"], line["kind"], line["tier"], line["at"], line["end"]) == (
        "manual",
        "story",
        2,
        "2026-06-10T18:30:00Z",
        None,
    )
    assert line["payload"] == {
        "schema": "story/v1",
        "raw_id": _raw_id(LAKE),
        "title": "The house by the lake",
        "text": (
            "In 1961 we moved to the house by the lake. Father rowed the furniture across in two\n"
            "trips; the piano went last, on a raft he had built that morning.\n\n"
            "We stayed until the winter the lake did not freeze."
        ),
        "told_at": "2026-06-10T18:30:00Z",
        "refers_to": {"text": "1961", "from": "1961-01-01", "to": "1961-12-31", "precision": "year"},
        "teller": {"ref": {"kind": "email", "value": OLA["email"]}, "name": "Ola Nordmann"},
        "listener": {"ref": {"kind": "email", "value": KARI["email"]}, "name": "Kari Nordmann"},
        "confidence": "sure",
        "source": "conversation",
    }
    _seq, _head, errors = lb.verify()
    assert errors == []


def test_add_story_plain_text_takes_the_people_and_the_time_from_the_flags(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """A name is resolved through the record's resolution lines to one of that person's refs
    (an address before a number); a bare address, a `+` number and `kind:value` are refs as
    given. A phrase is kept as told, with no dates."""
    out = _run(
        capsys,
        "add",
        "story",
        str(BEES),
        "--teller",
        "Ola",
        "--listener",
        "Kari Nordmann",
        "--refers-to",
        "before the war",
        "--confidence",
        "fuzzy",
        "--at",
        "2026-06-11T07:00:00Z",
    )
    assert out.splitlines() == [
        f"#5 2026-06-11T07:00:00Z  story {BOOK} refers to before the war \u2014"
        " told by Ola Nordmann to Kari Nordmann"
    ]
    (line,) = _stories(lb)
    p = line["payload"]
    assert p["text"].startswith("Before the war grandmother kept bees") and "title" not in p
    assert p["told_at"] == line["at"] == "2026-06-11T07:00:00Z"
    assert p["refers_to"] == {"text": "before the war", "from": None, "to": None, "precision": "phrase"}
    assert p["teller"] == {"ref": {"kind": "email", "value": OLA["email"]}, "name": "Ola Nordmann"}
    assert p["listener"] == {"ref": {"kind": "email", "value": KARI["email"]}, "name": "Kari Nordmann"}
    assert p["confidence"] == "fuzzy" and "source" not in p


@pytest.mark.parametrize(
    ("teller", "expected"),
    [
        ("+47 900 00 001", {"ref": {"kind": "phone", "value": "+4790000001"}, "name": "Ola Nordmann"}),
        ("phone:+4790000001", {"ref": {"kind": "phone", "value": "+4790000001"}, "name": "Ola Nordmann"}),
        ("handle:ola.n", {"ref": {"kind": "handle", "value": "ola.n"}}),  # nobody the record knows: no name
        ("someone@example.org", {"ref": {"kind": "email", "value": "someone@example.org"}}),
    ],
)
def test_a_teller_may_be_any_ref_the_record_does_or_does_not_know(
    lb: Logbook, capsys: pytest.CaptureFixture[str], teller: str, expected: dict[str, Any]
) -> None:
    _run(capsys, "add", "story", str(BEES), "--teller", teller, "--listener", KARI["email"])
    (line,) = _stories(lb)
    assert line["payload"]["teller"] == expected


def test_flags_win_over_the_front_matter(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    _run(
        capsys,
        "add",
        "story",
        str(LAKE),
        "--teller",
        KARI["email"],
        "--listener",
        OLA["email"],
        "--refers-to",
        "1962-03",
        "--confidence",
        "disputed",
        "--tier",
        "3",
    )
    (line,) = _stories(lb)
    p = line["payload"]
    assert line["tier"] == 3
    assert p["teller"]["name"] == "Kari Nordmann" and p["listener"]["name"] == "Ola Nordmann"
    assert p["refers_to"]["text"] == "1962-03" and p["refers_to"]["to"] == "1962-03-31"
    assert p["confidence"] == "disputed" and p["told_at"] == "2026-06-10T18:30:00Z"  # not a flag: kept


def test_add_story_from_a_transcript_json_keeps_the_transcript_as_an_attachment(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """The story is told at the transcript's start; its text is the transcript's; the transcript's
    bytes go to the SPEC §1.1 store and the line points at them. When the transcript/v1 line is in
    the record too, `transcript_line` names it."""
    _run(capsys, "add", "transcript", str(BOAT))
    transcript = next(line for line in lb.lines() if line["kind"] == "transcript")
    out = _run(
        capsys,
        "add",
        "story",
        str(BOAT),
        "--teller",
        OLA["email"],
        "--listener",
        KARI["email"],
        "--refers-to",
        "1955",
    )
    assert "refers to 1955" in out
    (line,) = _stories(lb)
    p = line["payload"]
    assert line["at"] == p["told_at"] == "2026-06-13T17:30:00Z" and line["tier"] == 2
    assert p["title"] == "Kari asks about the summer of fifty-five"
    assert p["text"].startswith("Kari Nordmann: When did the family first sail out here?")
    assert p["source"] == "voice-memo"
    content = p["transcript"]
    assert (
        set(content) == {"sha256", "path", "bytes", "media_type"} and content["media_type"] == "text/markdown"
    )
    stored = lb.root / content["path"]
    assert stored.is_file() and hashlib.sha256(stored.read_bytes()).hexdigest() == content["sha256"]
    assert p["transcript_line"] == transcript["id"]
    assert transcript["payload"]["content"]["sha256"] == content["sha256"]


def test_add_story_json_that_is_not_a_transcript_is_an_error(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"payload": {"schema": "note/v1", "text": "x"}}), encoding="utf-8")
    err = _fails(capsys, "add", "story", str(other), "--teller", OLA["email"], "--listener", KARI["email"])
    assert "transcript/v1" in err and lb.meta["seq"] == 4


def test_a_story_needs_a_teller_and_a_listener(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    err = _fails(capsys, "add", "story", str(BEES), "--listener", KARI["email"])
    assert "teller" in err and lb.meta["seq"] == 4
    err = _fails(capsys, "add", "story", str(BEES), "--teller", OLA["email"])
    assert "listener" in err and lb.meta["seq"] == 4
    err = _fails(capsys, "add", "story", str(BEES), "--teller", "Nobody", "--listener", KARI["email"])
    assert "Nobody" in err and lb.meta["seq"] == 4


def test_a_misspelt_date_or_confidence_writes_nothing(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    err = _fails(
        capsys, "add", "story", str(BEES), "--teller", "Ola", "--listener", "Kari", "--refers-to", "1961-5"
    )
    assert "1961-5" in err and lb.meta["seq"] == 4
    err = _fails(
        capsys, "add", "story", str(BEES), "--teller", "Ola", "--listener", "Kari", "--confidence", "maybe"
    )
    assert "maybe" in err and lb.meta["seq"] == 4


def test_tier_1_is_refused_because_a_story_carries_someone_elses_words(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    err = _fails(capsys, "add", "story", str(LAKE), "--tier", "1")
    assert "tier" in err and lb.meta["seq"] == 4


def test_a_missing_file_and_story_flags_without_story_are_errors(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    err = _fails(capsys, "add", "story", str(tmp_path / "nowhere.md"))
    assert "nowhere.md" in err
    err = _fails(capsys, "add", "had", "lunch", "--teller", "Ola")
    assert "add story" in err and lb.meta["seq"] == 4


def test_the_same_file_twice_is_one_line(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    _run(capsys, "add", "story", str(LAKE))
    out = _run(capsys, "add", "story", str(LAKE), "--confidence", "fuzzy")
    assert "already in the record" in out and len(_stories(lb)) == 1


def test_several_files_are_one_line_each_in_order(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    out = _run(capsys, "add", "story", str(LAKE), str(BEES), "--teller", "Ola", "--listener", "Kari")
    assert [row.split()[0] for row in out.splitlines()] == ["#5", "#6"]
    lake, bees = _stories(lb)
    assert lake["payload"]["refers_to"]["text"] == "1961" and "refers_to" not in bees["payload"]
    assert lake["payload"]["teller"]["name"] == bees["payload"]["teller"]["name"] == "Ola Nordmann"


# -- show ----------------------------------------------------------------------------------------------------


def test_show_prints_the_story_on_the_day_it_was_told(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(capsys, "add", "story", str(LAKE))
    out = _run(capsys, "show", "2026-06-10").splitlines()
    assert out[1] == f"  20:30  story      manual         {TOLD_BY}"
    assert _run(capsys, "show", "1961-05-04").startswith("1961-05-04: nothing logged")


def test_show_raw_prints_the_refs_as_given(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    _run(capsys, "add", "story", str(LAKE))
    out = _run(capsys, "show", "2026-06-10", "--raw")
    assert f"{BOOK} refers to 1961 — told by {OLA['email']} to {KARI['email']}" in out


def test_show_a_story_with_no_time_and_an_unknown_teller(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(
        capsys,
        "add",
        "story",
        str(BEES),
        "--teller",
        "handle:ola.n",
        "--listener",
        "Kari",
        "--at",
        "2026-06-11T07:00:00Z",
    )
    out = _run(capsys, "show", "2026-06-11")
    assert f"{BOOK} refers to an unsaid time — told by ola.n to Kari Nordmann" in out


# -- day -----------------------------------------------------------------------------------------------------


def _tell_three(capsys: pytest.CaptureFixture[str]) -> None:
    _run(capsys, "add", "story", str(LAKE))  # 1961, told 10 June
    _run(capsys, "add", "story", str(BOAT), "--teller", "Ola", "--listener", "Kari", "--refers-to", "1950s")
    _run(
        capsys,
        "add",
        "story",
        str(BEES),
        "--teller",
        "Ola",
        "--listener",
        "Kari",
        "--refers-to",
        "before the war",
    )


def test_day_lists_the_stories_about_the_day_apart_from_the_timeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    _tell_three(capsys)
    out = _run(capsys, "day", "1961-05-04")
    rows = out.splitlines()
    assert "  timeline      nothing logged" in rows
    heading = rows.index("  Stories about this day")
    assert rows[heading + 1] == f"    {TOLD_BY}{story.DOT}sure{story.DOT}told 2026-06-10"
    assert rows[heading + 2] == f"       {LAKE_CUT}"
    assert (
        "fifty-five" not in out and "grandmother" not in out
    )  # the 1950s story and the phrase are not about 1961
    data = json.loads(_run(capsys, "day", "1961-05-04", "--json"))
    assert data["timeline"] == [] and data["unplaced"] == [] and data["sources"] == []
    (told,) = data["stories"]
    lake = next(line for line in lb.lines() if line["kind"] == "story" and "title" in line["payload"])
    assert told == {
        "line": lake["id"],
        "told_at": "2026-06-10T18:30:00Z",
        "title": "The house by the lake",
        "text": LAKE_CUT,
        "refers_to": {"text": "1961", "from": "1961-01-01", "to": "1961-12-31", "precision": "year"},
        "teller": {"ref": {"kind": "email", "value": OLA["email"]}, "name": "Ola Nordmann"},
        "listener": {"ref": {"kind": "email", "value": KARI["email"]}, "name": "Kari Nordmann"},
        "confidence": "sure",
        "source": "conversation",
    }


def test_a_decade_is_about_every_day_in_it_and_a_phrase_about_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch)
    _tell_three(capsys)
    data = json.loads(_run(capsys, "day", "1955-03-02", "--json"))
    assert [s["refers_to"]["text"] for s in data["stories"]] == ["1950s"]
    assert data["stories"][0]["source"] == "voice-memo"
    assert json.loads(_run(capsys, "day", "1939-01-01", "--json"))["stories"] == []
    assert "Stories about this day" not in _run(capsys, "day", "1939-01-01")


def test_the_day_a_story_was_told_does_not_list_it_as_an_event_of_that_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Told at home on 10 June: the telling is on no row's attachments, not unplaced, and not a
    story about 10 June; the source count still says a manual line was written that day."""
    persona_record(tmp_path, monkeypatch)
    _tell_three(capsys)
    data = json.loads(_run(capsys, "day", "2026-06-10", "--json"))
    assert data["stories"] == []
    assert all(item["kind"] != "story" for item in data["unplaced"])
    assert "story" not in json.dumps(data["timeline"])
    assert any(s["source"] == "manual" and s["lines"] == 1 for s in data["sources"])
    assert "Stories about this day" not in _run(capsys, "day", "2026-06-10")


def test_a_retracted_or_superseded_story_is_not_about_any_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    _run(capsys, "add", "story", str(LAKE))
    lake = next(line for line in lb.lines() if line["kind"] == "story")
    assert len(json.loads(_run(capsys, "day", "1961-05-04", "--json"))["stories"]) == 1
    # a correction: the same story told again, the year put right, superseding the first
    corrected = {
        **{k: lake[k] for k in ("at", "end", "source", "kind", "tier")},
        "payload": {
            **lake["payload"],
            "raw_id": lake["payload"]["raw_id"] + ":2",
            "refers_to": story.parse_refers_to("1962"),
            "supersedes": lake["id"],
        },
    }
    lb.append_many([corrected])
    assert json.loads(_run(capsys, "day", "1961-05-04", "--json"))["stories"] == []
    assert len(json.loads(_run(capsys, "day", "1962-05-04", "--json"))["stories"]) == 1
    lb.retract(lb.meta["seq"], "told wrong")
    assert json.loads(_run(capsys, "day", "1962-05-04", "--json"))["stories"] == []
    assert (
        json.loads(_run(capsys, "day", "1961-05-04", "--json"))["stories"] == []
    )  # superseded stays superseded


def test_a_file_with_windows_line_endings_reads_the_same(tmp_path: Path) -> None:
    # git on Windows checks text out with CRLF, and a story typed there has it too: the front
    # matter, the heading and the text read the same, only the digest (the raw bytes) differs.
    unix_bytes = (FIXTURES / "house-by-the-lake.md").read_bytes().replace(b"\r\n", b"\n")
    lf, crlf = tmp_path / "lf" / "house-by-the-lake.md", tmp_path / "crlf" / "house-by-the-lake.md"
    lf.parent.mkdir()
    crlf.parent.mkdir()
    lf.write_bytes(unix_bytes)  # the fixture itself is CRLF on a Windows checkout, so both are written here
    crlf.write_bytes(unix_bytes.replace(b"\n", b"\r\n"))
    unix, windows = story.read_file(lf), story.read_file(crlf)
    assert windows.fields == unix.fields and windows.title == unix.title
    assert windows.text == unix.text
    assert windows.raw_id != unix.raw_id
