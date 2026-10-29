"""Star (RFC 0041): `logbook star LINE [--note …]` marks a line worth keeping and `logbook unstar LINE`
takes the mark back. A star is a `star/v1` line at the starred line's `at` and tier; a photo's star is
a `keeper/v1` line of lane `memory` (RFC 0024), the hero and the press's pick; unstarring is a
retraction at the star's tier. Every line is checked byte for byte, but for the clock. On the Oslo
persona, who does not exist."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
from persona import TZ, persona_record, utc

from logbook import cli
from logbook.core import keepers, stars
from logbook.core.chain import Line
from logbook.core.store import HeadMoved, Logbook

CLOCK = ("id", "seq", "prev", "hash", "recorded_at")  # what the clock and the chain decide


@pytest.fixture(scope="module")
def pristine(tmp_path_factory: pytest.TempPathFactory) -> Path:
    with pytest.MonkeyPatch.context() as mp:
        return persona_record(tmp_path_factory.mktemp("stars"), mp).root


@pytest.fixture
def lb(pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    shutil.copytree(pristine, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook(root)


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main([*args])
    return capsys.readouterr().out


def _refused(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    with pytest.raises(SystemExit) as stop:
        cli.main([*args])
    assert stop.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    return captured.err


def _of_kind(lb: Logbook, kind: str) -> list[Line]:
    return [line for line in lb.lines() if line["kind"] == kind]


def _at(lb: Logbook, kind: str, at: str) -> Line:
    (found,) = [line for line in _of_kind(lb, kind) if line["at"] == at]
    return found


def _content(line: Line) -> dict[str, Any]:
    return {k: v for k, v in line.items() if k not in CLOCK}


LUNCH = utc("2026-06-10", "12:00")  # a timed calendar entry, tier 1
BOAT_PLANS = utc("2026-06-11", "14:00")  # a transcript, tier 2
ART = utc("2026-06-11", "16:00")  # a photo in the Art album, no favourite
CAFE_PHOTO = utc("2026-06-10", "12:30")  # a favourite


# -- star ----------------------------------------------------------------------------------------------------


def test_star_writes_one_star_line_at_the_line_s_at_and_tier(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    lunch = _at(lb, "event", LUNCH)
    seq = lb.meta["seq"]
    out = _run(capsys, "star", lunch["id"], "--note", "the table by the window")
    [star] = _of_kind(lb, "star")
    assert _content(star) == {
        "at": lunch["at"],
        "end": None,
        "tz": TZ,
        "source": "manual",
        "kind": "star",
        "tier": 1,
        "payload": {
            "schema": "star/v1",
            "line": lunch["id"],
            "kind": "event",
            "note": "the table by the window",
        },
    }
    assert lb.meta["seq"] == seq + 1 and star["seq"] == seq + 1
    assert out == f"#{star['seq']} star/v1  ★ #{lunch['seq']} event  Lunch · the table by the window\n"
    assert lb.verify()[2] == []


def test_a_star_takes_the_tier_of_its_line_whoever_made_it(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """A tier is where a line may travel: the star on a tier-2 transcript is tier 2, and without a
    note the payload carries none."""
    plans = _at(lb, "transcript", BOAT_PLANS)
    _run(capsys, "star", plans["id"])
    [star] = _of_kind(lb, "star")
    assert (star["tier"], star["at"]) == (2, plans["at"])
    assert star["payload"] == {"schema": "star/v1", "line": plans["id"], "kind": "transcript"}


def test_a_photo_s_star_is_a_memory_keeper_the_press_picks(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    photo = _at(lb, "photo", ART)
    out = _run(capsys, "star", photo["id"], "--note", "the light on the desk")
    assert _of_kind(lb, "star") == []
    [keeper] = _of_kind(lb, "keeper")
    assert _content(keeper) == {
        "at": photo["at"],
        "end": None,
        "tz": TZ,
        "source": "manual",
        "kind": "keeper",
        "tier": 1,
        "payload": {
            "schema": "keeper/v1",
            "raw_id": f"{photo['id']}:memory",
            "photo": {
                "line": photo["id"],
                "asset_id": photo["payload"]["asset_id"],
                "library": "immich",
                "file_name": photo["payload"]["file_name"],
            },
            "at": photo["at"],
            "lane": "memory",
            "source": "manual",
            "note": "the light on the desk",
        },
    }
    assert out == (
        f"#{keeper['seq']} keeper/v1  ★ #{photo['seq']} photo  {photo['payload']['file_name']}"
        " · the light on the desk\n"
    )
    listed = json.loads(_run(capsys, "show", "keepers", "--json"))["keepers"]
    assert [(k["line"], k["lane"], k["source"]) for k in listed] == [(keeper["id"], "memory", "manual")]
    from logbook.contrib import print_page
    from logbook.core import reading

    rd = reading.read(lb, "2026-06-11", "2026-06-11")
    [picked] = print_page.keepers_by_day(rd, lb.root)["2026-06-11"]
    assert (picked["photo"], picked["lane"]) == (photo["id"], "memory"), "the press picks it"


def test_a_photo_the_library_marked_a_favourite_is_starred_already(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(capsys, "derive", "keepers")
    seq = lb.meta["seq"]
    photo = _at(lb, "photo", CAFE_PHOTO)
    out = _run(capsys, "star", photo["id"])
    assert out == f"#{photo['seq']} is starred already; nothing written\n"
    assert lb.meta["seq"] == seq


def test_starring_again_writes_nothing_or_supersedes_with_a_new_note(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    lunch = _at(lb, "event", LUNCH)
    _run(capsys, "star", lunch["id"], "--note", "first")
    seq = lb.meta["seq"]
    for again in ((), ("--note", "first"), ("--note", "  first ")):
        assert "starred already; nothing written" in _run(capsys, "star", lunch["id"], *again)
    assert lb.meta["seq"] == seq, "a bare star, or the same note, writes nothing"
    _run(capsys, "star", lunch["id"], "--note", "second")
    first, second = _of_kind(lb, "star")
    assert second["payload"] == {
        "schema": "star/v1",
        "line": lunch["id"],
        "kind": "event",
        "note": "second",
        "supersedes": first["id"],
    }
    with Logbook(lb.root).index() as idx:
        found = stars.standing([*_of_kind(lb, "star"), *idx.retractions()])
    assert list(found) == [lunch["id"]] and found[lunch["id"]].star == second["id"]
    assert found[lunch["id"]].note == "second"


def test_a_photo_star_given_a_new_note_supersedes_the_keeper_and_the_reader_honours_it(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(capsys, "derive", "keepers")
    photo = _at(lb, "photo", CAFE_PHOTO)
    inferred = [k for k in _of_kind(lb, "keeper") if k["payload"]["photo"]["line"] == photo["id"]]
    _run(capsys, "star", photo["id"], "--note", "Kari laughing")
    mine = _of_kind(lb, "keeper")[-1]
    assert mine["source"] == "manual" and mine["payload"]["supersedes"] == inferred[0]["id"]
    kept = keepers.standing([*_of_kind(lb, "keeper"), *_of_kind(lb, "retraction")])
    assert [k["id"] for k in kept if k["payload"]["photo"]["line"] == photo["id"]] == [mine["id"]]


# -- unstar --------------------------------------------------------------------------------------------------


def test_unstar_retracts_the_star_at_the_star_s_tier(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    plans = _at(lb, "transcript", BOAT_PLANS)
    _run(capsys, "star", plans["id"])
    [star] = _of_kind(lb, "star")
    out = _run(capsys, "unstar", plans["id"])
    [retraction] = _of_kind(lb, "retraction")
    assert {k: v for k, v in _content(retraction).items() if k != "at"} == {
        "end": None,
        "tz": TZ,
        "source": "manual",
        "kind": "retraction",
        "tier": 2,
        "payload": {
            "schema": "retraction/v1",
            "supersedes": star["id"],
            "seq": star["seq"],
            "reason": "unstarred",
        },
    }
    assert out == f"#{retraction['seq']} retraction/v1  unstarred #{plans['seq']} transcript  Boat plans\n"
    with Logbook(lb.root).index() as idx:
        assert stars.standing([star, *idx.retractions()]) == {}
    _run(capsys, "star", plans["id"])
    assert len(_of_kind(lb, "star")) == 2, "starred again: a new act, a new line"


def test_unstar_takes_the_star_s_own_id_too(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    lunch = _at(lb, "event", LUNCH)
    _run(capsys, "star", lunch["id"])
    [star] = _of_kind(lb, "star")
    _run(capsys, "unstar", star["id"])
    [retraction] = _of_kind(lb, "retraction")
    assert retraction["payload"]["supersedes"] == star["id"] and retraction["tier"] == 1


def test_unstar_of_a_superseded_star_s_id_takes_back_the_star_that_stands(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """Rule 4: an unstar retracts the star standing on the line, whichever of the line's marks it was
    named by; the superseded star it was named by stays as it is, and the line is unstarred."""
    lunch = _at(lb, "event", LUNCH)
    _run(capsys, "star", lunch["id"], "--note", "first")
    _run(capsys, "star", lunch["id"], "--note", "second")
    first, second = _of_kind(lb, "star")
    assert second["payload"]["supersedes"] == first["id"]
    out = _run(capsys, "unstar", first["id"])
    [retraction] = _of_kind(lb, "retraction")
    assert retraction["payload"]["supersedes"] == second["id"], "the standing star, not the one it replaced"
    assert out == f"#{retraction['seq']} retraction/v1  unstarred #{lunch['seq']} event  Lunch\n"
    with Logbook(lb.root).index() as idx:
        assert stars.standing([first, second, *idx.retractions()]) == {}
    seq = Logbook(lb.root).meta["seq"]
    for mark in (first, second):
        assert "is not starred" in _refused(capsys, "unstar", mark["id"])
    assert Logbook(lb.root).meta["seq"] == seq


def test_unstar_of_an_art_keeper_is_refused(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    """An `art` keeper is the Art album's mark, not a star: `unstar` naming it writes nothing."""
    _run(capsys, "derive", "keepers")
    art = _at(lb, "photo", ART)
    [keeper] = [k for k in _of_kind(lb, "keeper") if k["payload"]["photo"]["line"] == art["id"]]
    assert keeper["payload"]["lane"] == "art"
    seq = Logbook(lb.root).meta["seq"]
    assert "lane art" in _refused(capsys, "unstar", keeper["id"])
    assert Logbook(lb.root).meta["seq"] == seq and _of_kind(lb, "retraction") == []


def test_unstar_on_a_photo_retracts_its_memory_keepers_and_leaves_the_art_lane(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(capsys, "derive", "keepers")
    art = _at(lb, "photo", ART)
    _run(capsys, "star", art["id"])
    memory = [
        k
        for k in _of_kind(lb, "keeper")
        if k["payload"]["photo"]["line"] == art["id"] and k["payload"]["lane"] == "memory"
    ]
    assert len(memory) == 1
    _run(capsys, "unstar", art["id"])
    [retraction] = _of_kind(lb, "retraction")
    assert retraction["payload"]["supersedes"] == memory[0]["id"] and retraction["tier"] == 1
    kept = keepers.standing([*_of_kind(lb, "keeper"), retraction])
    lanes = [k["payload"]["lane"] for k in kept if k["payload"]["photo"]["line"] == art["id"]]
    assert lanes == ["art"], "the Art album's mark is not a star"
    assert "0 new keepers" in _run(capsys, "derive", "keepers"), "an unstarred favourite stays unstarred"


def test_unstar_of_the_library_s_favourite_sticks(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    _run(capsys, "derive", "keepers")
    photo = _at(lb, "photo", CAFE_PHOTO)
    _run(capsys, "unstar", photo["id"])
    assert "0 new keepers" in _run(capsys, "derive", "keepers")
    with Logbook(lb.root).index() as idx:
        found = stars.standing([*idx.by_kind("keeper"), *idx.retractions()])
    assert photo["id"] not in found


# -- refusals ------------------------------------------------------------------------------------------------


def test_what_a_star_refuses_writes_nothing(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    lunch = _at(lb, "event", LUNCH)
    _run(capsys, "star", lunch["id"])
    [star] = _of_kind(lb, "star")
    note = _of_kind(lb, "note")[0]
    cli.main(["repair", "retract", str(note["seq"]), "a test"])
    [retraction] = _of_kind(lb, "retraction")
    capsys.readouterr()
    seq = lb.meta["seq"]
    assert "no line" in _refused(capsys, "star", "019cadd3-6bc0-7dcd-9133-00000000ffff")
    assert "no line" in _refused(capsys, "star", "#999999")
    assert "is a star" in _refused(capsys, "star", star["id"])
    assert "is a retraction" in _refused(capsys, "star", retraction["id"])
    assert "is retracted" in _refused(capsys, "star", note["id"])
    assert "one line" in _refused(capsys, "star", lunch["id"], "--note", "two\nlines")
    plans = _at(lb, "transcript", BOAT_PLANS)
    assert "not starred" in _refused(capsys, "unstar", plans["id"])
    assert lb.meta["seq"] == seq


def test_a_keeper_is_a_mark_and_takes_no_star(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    _run(capsys, "derive", "keepers")
    keeper = _of_kind(lb, "keeper")[0]
    seq = lb.meta["seq"]
    assert "is a keeper" in _refused(capsys, "star", keeper["id"])
    assert lb.meta["seq"] == seq


def test_a_line_is_named_by_its_id_or_its_seq(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    lunch = _at(lb, "event", LUNCH)
    _run(capsys, "star", f"#{lunch['seq']}")
    _run(capsys, "unstar", str(lunch["seq"]))
    [star], [retraction] = _of_kind(lb, "star"), _of_kind(lb, "retraction")
    assert star["payload"]["line"] == lunch["id"] and retraction["payload"]["supersedes"] == star["id"]


def test_a_star_on_a_line_retracted_since_does_not_stand(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    lunch = _at(lb, "event", LUNCH)
    _run(capsys, "star", lunch["id"])
    cli.main(["repair", "retract", str(lunch["seq"]), "a test"])
    with Logbook(lb.root).index() as idx:
        assert stars.standing([*_of_kind(lb, "star"), *idx.retractions()]) == {}


def test_the_head_is_read_again_under_the_lock(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    """Another writer moving the head between the read and the append: `HeadMoved`, nothing starred."""
    lunch = _at(lb, "event", LUNCH)
    read = stars._read

    def moved(*args: Any, **kwargs: Any) -> Any:
        found = read(*args, **kwargs)
        Logbook(lb.root).append(
            at=LUNCH, source="manual", kind="note", tier=2, payload={"schema": "note/v1", "text": "x"}
        )
        return found

    monkeypatch.setattr(stars, "_read", moved)
    with pytest.raises(HeadMoved):
        stars.star(Logbook(lb.root), lunch["id"])
    assert _of_kind(lb, "star") == []


# -- the Day ---------------------------------------------------------------------------------------------


def test_the_day_carries_its_stars_and_marks_the_starred_rows(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    lunch = _at(lb, "event", LUNCH)
    assert "stars" not in json.loads(_run(capsys, "day", "2026-06-10", "--json")), "no star, no key"
    before = _run(capsys, "day", "2026-06-10")
    _run(capsys, "star", lunch["id"], "--note", "the table by the window")
    [star] = _of_kind(lb, "star")
    data = json.loads(_run(capsys, "day", "2026-06-10", "--json"))
    assert data["stars"] == [
        {"line": lunch["id"], "star": star["id"], "kind": "event", "note": "the table by the window"}
    ]
    text = _run(capsys, "day", "2026-06-10")
    [row] = [r for r in text.splitlines() if "Lunch" in r and r.strip().startswith("event")]
    assert "★ Lunch, from 12:00 to 13:00" in row, "the star first, then the title, then its time"
    assert [r for r in before.splitlines() if "★" in r] == []
    _run(capsys, "unstar", lunch["id"])
    assert "stars" not in json.loads(_run(capsys, "day", "2026-06-10", "--json"))
    assert _run(capsys, "day", "2026-06-10") == before


def test_a_starred_photo_is_on_the_day_as_its_keeper(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    """The Day's object for a keeper is the frozen one (`conformance/profiles/keeper/`): the photo's
    star is its keeper, under the row's `keepers`, and adds no `stars` key."""
    photo = _at(lb, "photo", ART)
    _run(capsys, "star", photo["id"])
    [keeper] = _of_kind(lb, "keeper")
    data = json.loads(_run(capsys, "day", "2026-06-11", "--json"))
    assert "stars" not in data
    kept = [k for e in data["timeline"] for k in (e.get("attached") or {}).get("keepers", [])]
    assert kept == [{"name": photo["payload"]["file_name"], "lane": "memory", "line": keeper["id"]}]
    assert f"keeper       {photo['payload']['file_name']} (memory)" in _run(capsys, "day", "2026-06-11")


def test_the_press_prints_a_photo_star_s_note_under_the_photo(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A photo star is how the press picks pictures: the keeper is laid out with the trip's or the
    year's photos, and its note is the caption."""
    photo = _at(lb, "photo", ART)
    _run(capsys, "star", photo["id"], "--note", "the light on the desk")
    out = tmp_path / "year.html"
    _run(capsys, "show", "year", "2026", "--html", str(out), "--print")
    page = out.read_text(encoding="utf-8")
    caption = re.search(
        rf"<figcaption>[^<]*{re.escape(photo['payload']['file_name'])}<br>([^<]*)</figcaption>", page
    )
    assert caption is not None and caption.group(1) == "the light on the desk"


def test_a_row_s_disposition_is_read_on_its_own_line_and_its_star_on_any_it_folds() -> None:
    """Main's Day reads the signed day's disposition on a row's own line (a kept calendar entry's,
    not the other sources' lines it folds); the star is on any of them, the folded ones included."""
    from logbook.core import day as day_reader

    marks = day_reader.Marks({"folded": "kept"}, frozenset({"folded"}))
    assert day_reader._mark(marks, "kept-entry", also=["kept-entry", "folded"]) == "★ "
    both = day_reader.Marks({"kept-entry": "kept"}, frozenset({"folded"}))
    alone = day_reader._mark(both, "kept-entry")
    assert alone.strip() and "★" not in alone, "the disposition, on the entry's own line"
    assert day_reader._mark(both, "kept-entry", also=["folded"]) == alone + "★ "
