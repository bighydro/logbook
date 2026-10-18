"""`logbook review video`: the owner's say over the scenes `videos infer` proposed, one scene at a time,
the sixth queue of RFC 0037's one review sitting. Accepting a scene writes exactly one `attribution/v1`
line carrying the scene's offsets and touches no other line, the video's least of all; the no is
RFC 0040's `scene-review/v1` and the proposal never returns for that scene; "ask the family" is an open
task the scene leaves the queue with, and answering it later closes the task; every line is tier 2 and
none of them crosses a tier-1 entry; nothing opens a connection.

The synthetic tape of `tests/test_videos_infer.py` (an invented family of Oslo, who does not exist),
inferred with the same fakes, is the queue."""

from __future__ import annotations

import builtins
import copy
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from test_videos_infer import (
    BOAT,
    HOME_01,
    TAPE,
    TAPE_02,
    VOLLEN,
    FakeMedia,
    FakeSpeech,
    FakeVision,
    Recording,
    _cache,
    _video,
    look,
)
from test_videos_infer import _run as _infer

from logbook import cli
from logbook.contrib import entities, places_review, video_review, videos
from logbook.core import crossing
from logbook.core.store import Logbook
from logbook.labs import scenes


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_network: list[str]) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    (lb.root / "places.json").write_text(
        json.dumps({"Vollen Brygge": VOLLEN, "Hjem": {"lat": 59.91, "lon": 10.75, "kind": "home"}}),
        encoding="utf-8",
    )
    (lb.root / "assets.json").write_text(
        json.dumps({"assets": [{"id": "solvind", "kind": "yacht", "name": "Solvind", "mmsi": "970123456"}]}),
        encoding="utf-8",
    )
    found = (FakeMedia({HOME_01: TAPE}), FakeSpeech(), FakeVision())
    monkeypatch.setattr(scenes, "detect", lambda *_a: found)
    lb.video = _video(lb, HOME_01, "Home 01")  # type: ignore[attr-defined]
    _cache(lb, HOME_01)
    assert _infer() == 0
    yield lb
    assert no_network == [], f"review video tried to connect: {no_network}"


def _review(*args: str) -> int:
    try:
        cli.main(["review", "video", *args])
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    return 0


def _new(lb: Logbook, after: int) -> list[dict[str, Any]]:
    return [line for line in Logbook(lb.root).lines() if int(line["seq"]) > after]


def _seq(lb: Logbook) -> int:
    return int(Logbook(lb.root).meta["seq"])


def _ref(lb: Logbook, start: str, end: str) -> str:
    return f"{lb.video['id']}#t={start},{end}"  # type: ignore[attr-defined]


EN_DASH = "\u2013"
PIER = ("40.00", "90.00")
GARDEN = ("90.00", "130.00")


def test_the_queue_is_the_scenes_surest_first_and_writes_nothing(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = _seq(lb)
    capsys.readouterr()
    assert _review() == 0
    out = capsys.readouterr().out
    assert _seq(lb) == seq
    rows = [line for line in out.splitlines() if line[:4].strip().isdigit()]
    assert [r.split("·")[1].strip() for r in rows] == [
        "scene 2 of 4",
        "scene 3 of 4",
        "scene 1 of 4",
        "scene 4 of 4",
    ]
    assert "→ Vollen Brygge (place)" in rows[0] and "[high]" in rows[0]
    assert "→ 1994-07-14" in rows[1]
    assert "→ ____" in rows[2]
    assert 'reads "VOLLEN BRYGGE"' in out and "[frames 0:50]" in out and "[speech 0:50\u20130:53]" in out
    assert "frame 0:50: A wooden pier" in out
    assert "nothing written" in out


def test_accept_writes_exactly_one_attribution_line_carrying_the_scenes_offsets(lb: Logbook) -> None:
    before = {line["id"]: line for line in Logbook(lb.root).lines()}
    seq = _seq(lb)
    assert _review("--accept", "1") == 0
    (line,) = _new(lb, seq)
    assert (line["kind"], line["source"], line["tier"]) == ("attribution", "manual", 2)
    payload = line["payload"]
    assert payload["schema"] == "attribution/v1"
    assert payload["ref"] == {"kind": "scene", "value": _ref(lb, *PIER)}
    assert payload["scene"] == {"video": lb.video["id"], "start_s": 40.0, "end_s": 90.0}  # type: ignore[attr-defined]
    assert payload["place"] == {
        "type": "place",
        "id": "Vollen Brygge",
        "registry": "logbook",
        "label": "Vollen Brygge",
    }
    assert "when" not in payload and payload["method"] == "owner"
    assert payload["draft"] in payload["evidence"] and lb.video["id"] in payload["evidence"]  # type: ignore[attr-defined]
    after = {line["id"]: line for line in Logbook(lb.root).lines()}
    assert {k: v for k, v in after.items() if k in before} == before, "a line was rewritten"
    assert after[lb.video["id"]] == lb.video  # type: ignore[attr-defined]
    cli.main(["verify"])


def test_an_accepted_scene_leaves_the_queue_and_the_same_answer_twice_writes_nothing(lb: Logbook) -> None:
    assert _review("--accept", "1") == 0
    queue = video_review.read(lb)
    assert _ref(lb, *PIER) not in [row.ref for row in queue.rows]
    assert queue.confirmed == 1
    seq = _seq(lb)
    assert _review("--answered", "--accept", "1") == 0
    assert _seq(lb) == seq


def test_a_corrected_answer_supersedes_the_standing_one(lb: Logbook) -> None:
    assert _review("--accept", "1") == 0
    first = _new(lb, 0)[-1]
    seq = _seq(lb)
    assert _review("--answered", "--date", "1", "summer 1994") == 0
    (line,) = _new(lb, seq)
    assert line["payload"]["supersedes"] == first["id"]
    assert line["payload"]["place"]["id"] == "Vollen Brygge"  # kept from the standing answer
    assert line["payload"]["when"] == {"from": "1994-06-01", "to": "1994-08-31", "precision": "season"}
    assert line["payload"]["extra"]["changed"] is True


def test_the_stamp_scene_is_confirmed_to_its_day(lb: Logbook) -> None:
    seq = _seq(lb)
    assert _review("--accept", "2") == 0
    (line,) = _new(lb, seq)
    assert line["payload"]["ref"]["value"] == _ref(lb, *GARDEN)
    assert line["payload"]["when"] == {"from": "1994-07-14", "to": "1994-07-14", "precision": "day"}
    assert "place" not in line["payload"]


def test_your_own_place_and_date_for_a_scene_with_nothing_to_go_on(lb: Logbook) -> None:
    seq = _seq(lb)
    assert _review("--place", "3", "hjem", "--date", "3", "1993-05-17") == 0
    (line,) = _new(lb, seq)
    assert line["payload"]["place"]["id"] == "Hjem"
    assert line["payload"]["when"] == {"from": "1993-05-17", "to": "1993-05-17", "precision": "day"}
    assert line["payload"]["extra"] == {"proposal": None, "changed": True}


def test_reject_writes_the_reviews_no_and_the_proposal_never_returns(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    seq = _seq(lb)
    assert _review("--reject", "1") == 0
    (no,) = _new(lb, seq)
    assert (no["kind"], no["tier"], no["source"]) == ("scene-review", 2, "manual")
    assert no["payload"]["schema"] == "scene-review/v1" and no["payload"]["verdict"] == "different"
    assert no["payload"]["ref"] == {"kind": "scene", "value": _ref(lb, *PIER)}
    assert no["payload"]["proposal"]["place"] == {
        "type": "place",
        "id": "Vollen Brygge",
        "registry": "logbook",
        "label": "Vollen Brygge",
    }
    assert "entity" not in no["payload"] and "type" not in no["payload"], "never an entity-review/v1 line"
    assert video_review.validate_scene_review(no["payload"]) == []
    assert _ref(lb, *PIER) not in [row.ref for row in video_review.read(lb).rows]
    vision = FakeVision()
    vision.model = "another-vision-model"  # another model: the file is inferred again, the same proposal
    monkeypatch.setattr(scenes, "detect", lambda *_a: (FakeMedia({HOME_01: TAPE}), FakeSpeech(), vision))
    _cache(lb, HOME_01)
    assert _infer() == 0
    rows = video_review.read(lb).rows
    assert _ref(lb, *PIER) not in [row.ref for row in rows], "a refused proposal came back"
    assert _ref(lb, *GARDEN) in [row.ref for row in rows]


def test_ask_the_family_keeps_the_scene_for_them_and_an_answer_closes_it(lb: Logbook) -> None:
    seq = _seq(lb)
    assert _review("--ask", "2") == 0
    (task,) = _new(lb, seq)
    assert (task["kind"], task["tier"], task["source"]) == ("task", 2, "manual")
    payload = task["payload"]
    assert payload["schema"] == "task/v1" and payload["status"] == "open" and payload["list"] == "videos"
    assert payload["extra"]["scene"] == _ref(lb, *GARDEN)
    assert _ref(lb, *GARDEN) not in [row.ref for row in video_review.read(lb).rows]
    asked = video_review.read(lb, "asked").rows
    assert [row.ref for row in asked] == [_ref(lb, *GARDEN)]
    seq = _seq(lb)
    assert _review("--asked", "--accept", "1") == 0
    attribution, closed = _new(lb, seq)
    assert attribution["kind"] == "attribution"
    assert closed["payload"]["status"] == "done" and closed["payload"]["supersedes"] == task["id"]
    assert video_review.read(lb, "asked").rows == []


@pytest.mark.parametrize(
    ("args", "why"),
    [
        (("--accept", "9"), "not in the queue"),
        (("--accept", "1", "--reject", "1"), "say one"),
        (("--accept", "3"), "nothing to confirm"),
        (("--place", "1", "Hytta på Banken"), "not a place of places.json"),
        (("--date", "1", "next summer"), "is not a date"),
        (("--date", "1", "2031"), "after today"),
        (("--accept", "x"), "not a scene's number"),
    ],
)
def test_an_answer_the_queue_cannot_take_writes_nothing(
    lb: Logbook, capsys: pytest.CaptureFixture[str], args: tuple[str, ...], why: str
) -> None:
    seq = _seq(lb)
    capsys.readouterr()
    assert _review(*args) == 2
    assert why in capsys.readouterr().err
    assert _seq(lb) == seq


def test_the_record_of_a_proposed_day_is_shown_beside_it(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    start = datetime(1994, 7, 14, 9, 0, tzinfo=UTC)
    for minutes in range(0, 300, 30):
        at = (start + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
        lb.append(
            at,
            "synthetic",
            "location",
            1,
            {"schema": "location/v1", "lat": VOLLEN["lat"], "lon": VOLLEN["lon"]},
        )
    lb.append(
        "1994-07-14T12:00:00Z",
        "synthetic",
        "location",
        1,
        {"schema": "location/v1", "lat": 59.8, "lon": 10.46, "subject": "solvind"},
    )
    capsys.readouterr()
    assert _review() == 0
    out = capsys.readouterr().out
    (said,) = [line for line in out.splitlines() if "that day in the record" in line]
    assert "Vollen Brygge" in said and "Solvind: 1 position" in said


def test_a_proposed_day_with_nothing_in_the_record_says_so(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    assert _review() == 0
    assert "nothing in the record within 3 days of 1994-07-14" in capsys.readouterr().out


def _dated(first: str, last: str, precision: str, confidence: str) -> dict[str, Any]:
    return {"when": {"from": first, "to": last, "precision": precision}, "when_confidence": confidence}


@pytest.mark.parametrize(
    ("proposal", "day"),
    [
        (_dated("1994-07-14", "1994-07-14", "day", "high"), True),
        (_dated("2000-01-01", "2000-01-01", "day", "low"), False),  # 1 January without a time
        (_dated("1994-07-01", "1994-07-31", "month", "high"), False),
        (None, False),
    ],
)
def test_the_record_is_set_beside_a_day_only_when_the_rules_trust_it(proposal: Any, day: bool) -> None:
    class Row:
        pass

    row = Row()
    row.proposal = proposal  # type: ignore[attr-defined]
    assert (video_review.trusted_day(row) is not None) is day  # type: ignore[arg-type]


def test_json_carries_a_stable_id_per_row(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    assert _review("--json") == 0
    first = json.loads(capsys.readouterr().out)
    assert _review("--json") == 0
    again = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in first["rows"]] == [r["id"] for r in again["rows"]]
    assert first["rows"][0]["scene"] == _ref(lb, *PIER) and first["tier"] == 2


def test_every_line_of_a_family_video_is_tier_2_and_none_crosses_a_tier_1_entry(lb: Logbook) -> None:
    assert _review("--accept", "1", "--reject", "2", "--ask", "3") == 0
    mine = [line for line in Logbook(lb.root).lines() if line["kind"] != "migration"]
    assert {line["tier"] for line in mine} == {2}
    assert {line["kind"] for line in mine} == {
        "video",
        "transcript",
        "draft",
        "attribution",
        "scene-review",
        "task",
    }
    window = ("2026-01-01T00:00:00Z", "2100-01-01T00:00:00Z")
    request = crossing.request(lb, "mcp", *window, (1,), signed_only=False)
    assert crossing.select(lb, request).lines == []
    (lb.root / "policy").mkdir(exist_ok=True)
    (lb.root / "policy" / "crossing.json").write_text(
        json.dumps({"hermes": {"max_tier": 2}}), encoding="utf-8"
    )
    request = crossing.request(lb, "hermes", *window, (1, 2), signed_only=False)
    assert len(crossing.select(lb, request).lines) == len(mine)  # crossing is the tier's say, never hidden


def test_nothing_proposed_yet_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = Logbook.init(tmp_path / "empty", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(empty.root))
    assert _review() == 0
    assert "nothing to review" in capsys.readouterr().out


def test_show_prints_the_video_and_the_attribution_readably(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = _seq(lb)
    assert _review("--accept", "1") == 0
    (line,) = _new(lb, seq)
    day = datetime.fromisoformat(line["at"].replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Oslo")).date()
    capsys.readouterr()
    cli.main(["show", day.isoformat()])
    cli.main(["show", "2026-10-14"])
    out = capsys.readouterr().out
    assert f"scene 0:40{EN_DASH}1:30 \u2192 Vollen Brygge" in out
    assert "Home 01 \u00b7 3 min \u00b7 12 bytes" in out  # its name, length and size; nothing it shows


def test_on_a_terminal_it_asks_one_scene_at_a_time_and_holds_no_lock_while_it_waits(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import builtins
    import sys

    from logbook.core import store

    answers = iter(["", "y", "q"])  # skip the pier, confirm the garden's day, stop

    def ask(prompt: str) -> str:
        assert not store._held, "the writer lock was held while the owner thought"
        assert not (lb.root / store.LOCK_FILE).exists()
        return next(answers)

    monkeypatch.setattr(builtins, "input", ask)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    seq = _seq(lb)
    assert _review() == 0
    (line,) = _new(lb, seq)
    assert line["kind"] == "attribution" and line["payload"]["ref"]["value"] == _ref(lb, *GARDEN)
    out = capsys.readouterr().out
    assert out.count("scene 2 of 4") == 1 and out.count("scene 3 of 4") == 1  # one scene at a time


# -- the independent check of tiers and the attribution line --------------------------------------------


def test_the_same_no_twice_and_a_second_ask_write_nothing(lb: Logbook) -> None:
    assert _review("--ask", "2") == 0
    assert _review("--asked", "--reject", "1") == 0
    seq = _seq(lb)
    assert _review("--asked", "--reject", "1") == 0
    assert _new(lb, seq) == [], "the same no twice wrote a second line"
    assert _review("--asked", "--ask", "1") == 0
    assert _new(lb, seq) == [], "a scene already asked got a second open task"


def test_a_no_on_a_confirmed_scene_is_refused(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    assert _review("--accept", "1") == 0
    seq = _seq(lb)
    capsys.readouterr()
    assert _review("--answered", "--reject", "1") == 2
    assert "does not undo" in capsys.readouterr().err and _seq(lb) == seq
    assert video_review.read(lb).confirmed == 1


def test_the_sitting_shows_the_asked_scenes_with_asked(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins
    import sys

    assert _review("--ask", "2") == 0
    shown: list[str] = []
    real = video_review.row_lines
    monkeypatch.setattr(
        video_review, "row_lines", lambda book, n, row: (shown.append(row.ref), real(book, n, row))[1]
    )
    monkeypatch.setattr(builtins, "input", lambda _p: "q")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert _review("--asked") == 0
    assert shown == [_ref(lb, *GARDEN)]


def test_retracting_the_no_brings_the_proposal_back(lb: Logbook) -> None:
    assert _review("--reject", "1") == 0
    no = _new(lb, 0)[-1]
    Logbook(lb.root).retract(int(no["seq"]), "wrong")
    assert _ref(lb, *PIER) in [r.ref for r in video_review.read(lb).rows]


def test_a_scene_cut_again_elsewhere_says_it_overlaps_a_confirmed_one(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from test_videos_infer import Recording, look

    assert _review("--accept", "1") == 0  # the pier, 0:40 to 1:30
    shifted = (
        Recording(45, -30, 0.0, TAPE[0].look, TAPE[0].said, TAPE[0].inside),
        TAPE[1],
        TAPE[2],
        Recording(35, -40, 0.5, look("A snowy road between trees.", "outdoors, a road", "winter")),
    )
    vision = FakeVision()
    vision.model = "another-vision-model"
    monkeypatch.setattr(scenes, "detect", lambda *_a: (FakeMedia({HOME_01: shifted}), FakeSpeech(), vision))
    _cache(lb, HOME_01)
    assert _infer() == 0
    queue = video_review.read(lb)
    assert queue.confirmed == 1 and _ref(lb, "45.00", "95.00") in [r.ref for r in queue.rows]
    capsys.readouterr()
    assert _review() == 0
    assert f"overlaps a scene you confirmed, 0:40{EN_DASH}1:30 → Vollen Brygge" in capsys.readouterr().out
    assert [r.ref for r in video_review.read(lb, "answered").rows] == [_ref(lb, *PIER)]


@pytest.fixture
def sealed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_network: list[str]) -> Logbook:
    """The same tape, in a record that names recipients: every tier-2 line and file is sealed."""
    from logbook.core import sealing

    pairs = [sealing.generate_identity() for _ in range(2)]
    lb = Logbook.init(tmp_path / "sealed", "Europe/Oslo")
    meta = lb.meta
    meta["recipients"] = [recipient for _secret, recipient in pairs]
    lb._save_meta(meta)
    path = tmp_path / "keys" / "owner.txt"
    sealing.write_identity_file(path, str(sealing.parse_identity(pairs[0][0])), "test")
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(path))
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb = Logbook(lb.root)
    (lb.root / "places.json").write_text(json.dumps({"Vollen Brygge": VOLLEN}), encoding="utf-8")
    engines = (FakeMedia({HOME_01: TAPE}), FakeSpeech(), FakeVision())
    monkeypatch.setattr(scenes, "detect", lambda *_a: engines)
    _video(lb, HOME_01, "Home 01")
    _cache(lb, HOME_01)
    assert _infer() == 0
    yield lb
    assert no_network == []


def test_every_line_and_the_vtt_are_sealed_and_the_review_reads_them_with_the_identity(
    sealed: Logbook,
) -> None:
    from logbook.core import sealing
    from logbook.core.chain import is_sealed

    assert _review("--accept", "1", "--reject", "2", "--ask", "3") == 0
    stored = [
        json.loads(raw)
        for f in Logbook(sealed.root).files()
        for raw in f.read_text(encoding="utf-8").splitlines()
        if raw.strip()
    ]
    mine = [line for line in stored if line["kind"] != "migration"]
    assert {line["kind"] for line in mine} == {
        "video",
        "transcript",
        "draft",
        "attribution",
        "scene-review",
        "task",
    }
    assert all(is_sealed(line) for line in mine)
    for f in (sealed.root / "attachments").iterdir():
        if f.is_file() and not f.name.startswith("."):
            assert sealing.is_sealed_file(f), f.name
    queue = video_review.read(sealed)
    assert (queue.confirmed, queue.rejected, queue.asked) == (1, 1, 1)
    cli.main(["verify"])


def test_without_the_identity_the_review_names_it_and_writes_nothing(
    sealed: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(tmp_path / "keys" / "nowhere.txt"))
    seq = _seq(sealed)
    capsys.readouterr()
    assert _review() == 2
    assert "identity" in capsys.readouterr().err
    assert _review("--accept", "1") == 2
    assert "identity" in capsys.readouterr().err and _seq(sealed) == seq


# -- one more queue of the one sitting (RFC 0037 §5; the owner's decision 1 of 15 October) ---------------


def _said(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str]:
    capsys.readouterr()
    try:
        cli.main([*args])
    except SystemExit as e:
        return (e.code if isinstance(e.code, int) else 1), capsys.readouterr().err
    return 0, capsys.readouterr().err


def test_review_video_is_one_more_queue_of_the_one_sitting(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    from logbook.commands import review

    driven: list[str] = []
    real = review.sitting

    def spy(queue: review.Queue, book: Logbook, a: Any) -> None:
        driven.append(queue.kind)
        real(queue, book, a)

    monkeypatch.setattr(review, "sitting", spy)
    assert _review() == 0
    assert _review("--accept", "1") == 0
    assert driven == ["video", "video"]
    # after the place's, and before main's speakers, which `review` lists last (tests/test_review_speakers.py)
    assert review.KINDS.index("video") == review.KINDS.index("place") + 1
    assert review.KINDS[-1] == "speakers" and isinstance(review.queue_of("video"), review.Queue)


@pytest.mark.parametrize(
    ("args", "said"),
    [
        (("review", "place", "--ask", "1"), "review place: --ask goes with `review video`"),
        (
            ("review", "org", "--place", "1", "Hjem", "--date", "1", "1994"),
            "review org: --place, --date go with `review video`",
        ),
        (("review", "person", "--asked"), "review person: --asked goes with `review video`"),
        (("review", "asset", "--answered"), "review asset: --answered goes with `review video`"),
        (("review", "idea", "--top", "2"), "review idea: --top goes with `review place` or `review video`"),
        (
            ("review", "idea", "--top", "2", "--near", "Hjem"),
            "review idea: --top, --near go with `review place`",
        ),
        (
            ("review", "person", "--top", "1", "--verbose"),
            "review person: --top, --verbose go with `review place`",
        ),
        (("review", "asset", "--top", "1", "--ask", "2"), "review asset: --top goes with `review place` or"),
        (("review", "video", "--near", "Hjem"), "review video: --near goes with `review place`"),
        (
            ("review", "video", "--migrate-rejects"),
            "review video: --migrate-rejects goes with `review place`",
        ),
        (("review", "--ask", "1"), "review: say which kind --ask is for"),
        (("review", "--top", "1"), "review: say which kind --top is for"),
        (("review", "video", "--name", "1", "Hjem"), "review video: --name goes with a new org, idea, asset"),
        (("review", "video", "--all-above", "50"), "review video: a scene's proposal has no score"),
        (("review", "video", "--ask", "1", "--reject", "1"), "scene 1 is given --reject and --ask; say one"),
        (("review", "video", "--place", "1", "Hjem", "--ask", "1"), "scene 1 is given --place and --ask"),
        (
            ("review", "video", "--date", "2", "1994", "--reject", "2"),
            "proposal 2 is both accepted and rejected",
        ),
        (("review", "video", "--ask", "9"), "review video: scene 9 is not in the queue (1 to 4)"),
        (("review", "video", "--top", "-1"), "review video: --top takes a number from 0, not -1"),
        (("review", "video", "--asked", "--answered"), "--asked and --answered are two lists; say one"),
    ],
)
def test_a_scenes_own_options_go_with_review_video_and_nothing_else(
    lb: Logbook, capsys: pytest.CaptureFixture[str], args: tuple[str, ...], said: str
) -> None:
    seq = _seq(lb)
    code, err = _said(capsys, *args)
    assert code == 2 and said in err, (args, err)
    assert _seq(lb) == seq, "refused before the first line"


def test_review_alone_lists_the_video_queue_with_the_others(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = _seq(lb)
    capsys.readouterr()
    cli.main(["review"])
    out = capsys.readouterr().out.splitlines()
    assert [line for line in out if not line.startswith(" ")] == [
        "person",
        "org",
        "idea",
        "asset",
        "place",
        "video",
        "goal",  # RFC 0036 amendment 1, after the video's
        "speakers",
    ]
    block = out[out.index("video") + 1 : out.index("goal")]
    assert block[0] == "  " + video_review.head_text(video_review.read(lb))
    assert any("Home 01 · scene 2 of 4" in line and "→ Vollen Brygge (place)" in line for line in block)
    cli.main(["review", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert [row["scene"] for row in data["video"]["rows"]][:2] == [_ref(lb, *PIER), _ref(lb, *GARDEN)]
    assert _seq(lb) == seq, "nothing written"


def test_top_counts_scenes(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    assert _review("--top", "1") == 0
    out = capsys.readouterr().out
    (row,) = [line for line in out.splitlines() if line[:4].strip().isdigit()]
    assert row.startswith("   1  [high]")
    assert "and 3 more; --top shows more" in out
    assert _review("--top", "2", "--json") == 0
    assert len(json.loads(capsys.readouterr().out)["rows"]) == 2


def test_what_was_written_is_said_as_the_sitting_says_it(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    assert _review("--accept", "1", "--json") == 0
    data = json.loads(capsys.readouterr().out)
    line = _new(lb, 0)[-1]
    assert data == {
        "written": [
            {
                "scene": _ref(lb, *PIER),
                "answer": "accept",
                "line": line["id"],
                "text": "confirmed Vollen Brygge (place)",
            }
        ]
    }
    assert _review("--ask", "1") == 0
    assert "Home 01 · t=90.00,130.00: kept to ask the family" in capsys.readouterr().out


def test_the_queue_is_read_with_no_lock_held_and_written_under_it(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Main's rule, one for every queue: the sitting reads the queue with no lock held, and the lines
    of the answers are appended under the writer lock."""
    from logbook.core import store

    held: list[bool] = []
    real_read, real_append = video_review.read, Logbook.append

    def read(book: Logbook, mode: str = "open") -> video_review.Queue:
        held.append(bool(store._held))
        return real_read(book, mode)

    def append(self: Logbook, *args: Any, **kwargs: Any) -> Any:
        held.append(bool(store._held))
        return real_append(self, *args, **kwargs)

    monkeypatch.setattr(video_review, "read", read)
    monkeypatch.setattr(Logbook, "append", append)
    assert _review("--accept", "1", "--reject", "2") == 0
    assert held == [False, True, True], "read with no lock; both answers under one hold"


def test_one_review_command_and_one_review_row() -> None:
    page = (Path(__file__).resolve().parents[1] / "docs" / "commands.md").read_text(encoding="utf-8")
    (row,) = [line for line in page.splitlines() if line.startswith("| `review` |")]
    assert "`review video`" in row and "`review videos`" not in row


# -- the scene's no is a line of its own (RFC 0040 §5; the owner's decision 2 of 15 October) --------------


def _place_and_asset_queues(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> list[str]:
    """What `review place` and `review asset` print, as text and as JSON, byte for byte, but for the
    place's JSON's `head`, which is the record's head and moves with any line written (as main's own
    `--migrate-rejects` test sets it aside)."""
    head = str(Logbook(lb.root).meta["head"])
    found = []
    for kind in ("place", "asset"):
        for extra in ((), ("--json",)):
            capsys.readouterr()
            cli.main(["review", kind, *extra])
            found.append(capsys.readouterr().out.replace(f'"head": "{head}"', '"head": "<the head>"'))
    return found


def _sightings(lb: Logbook) -> None:
    """Something for the place's and the asset's queues to propose: an afternoon at a spot nobody
    named, and a hull the registry does not hold (a synthetic MMSI)."""
    start = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    for minutes in range(0, 180, 15):
        at = (start + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
        lb.append(at, "synthetic", "location", 1, {"schema": "location/v1", "lat": 59.9211, "lon": 10.7302})
        lb.append(
            at,
            "synthetic",
            "location",
            1,
            {"schema": "location/v1", "lat": 59.82, "lon": 10.52, "subject": "970654321"},
        )


def test_a_scene_no_naming_a_place_or_an_asset_leaves_their_queues_byte_identical(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    found = (FakeMedia({HOME_01: TAPE, TAPE_02: BOAT}), FakeSpeech(), FakeVision())
    monkeypatch.setattr(scenes, "detect", lambda *_a: found)
    _video(lb, TAPE_02, "02")
    _cache(lb, TAPE_02)
    assert _infer() == 0
    _sightings(lb)
    queue = video_review.read(lb)
    named: dict[str, int] = {}
    for n, row in enumerate(queue.rows, 1):
        kind = ((row.proposal or {}).get("place") or {}).get("type")
        if kind is not None:
            named.setdefault(kind, n)
    assert set(named) >= {"place", "asset"}, named
    before = _place_and_asset_queues(lb, capsys)
    assert "[new]" in before[2] and "970654321" in before[2], "the asset's queue has something to show"
    assert json.loads(before[1])["proposals"], "and so has the place's"
    assert '"head": "<the head>"' in before[1] and "<the head>" not in before[3]
    seq = _seq(lb)
    assert _review("--reject", f"{named['place']},{named['asset']}") == 0
    noes = _new(lb, seq)
    assert [line["kind"] for line in noes] == ["scene-review", "scene-review"]
    assert {line["payload"]["proposal"]["place"]["id"] for line in noes} == {"Vollen Brygge", "solvind"}
    assert _place_and_asset_queues(lb, capsys) == before, (
        "a scene's no reached the place's or the asset's queue"
    )
    # the control: the line this PR wrote before (RFC 0037's entity-review/v1, type scene) is read as an
    # asset's no by every entity-review reader, so the asset's queue would not have stayed the same
    (asset_no,) = [line for line in noes if line["payload"]["proposal"]["place"]["type"] == "asset"]
    Logbook(lb.root).append(
        asset_no["at"],
        "manual",
        "entity-review",
        2,
        {
            "schema": "entity-review/v1",
            "type": "scene",
            "verdict": "different",
            "ref": asset_no["payload"]["ref"],
            "entity": {"type": "asset", "id": "solvind", "registry": "logbook"},
        },
    )
    after = _place_and_asset_queues(lb, capsys)
    assert json.loads(after[3])["rejected"] == json.loads(before[3])["rejected"] + 1


def test_entities_reviews_never_sees_a_scene_no(lb: Logbook) -> None:
    assert _review("--reject", "1") == 0
    every = list(Logbook(lb.root).lines())
    (no,) = [line for line in every if line["kind"] == "scene-review"]
    assert all(review.line != no["id"] for review in entities.reviews(every))
    assert entities.reviews(every) == entities.reviews([line for line in every if line is not no])
    assert entities.validate_entity_review(no["payload"]), "not an entity-review/v1 payload either"


def test_a_scene_does_not_come_back_in_review_video_after_its_no(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    assert _review("--json") == 0
    scenes_before = [row["scene"] for row in json.loads(capsys.readouterr().out)["rows"]]
    assert _review("--reject", "1,4") == 0
    capsys.readouterr()
    assert _review("--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert [row["scene"] for row in data["rows"]] == [scenes_before[1], scenes_before[2]]
    assert data["rejected"] == 2
    capsys.readouterr()
    cli.main(["review"])
    block = capsys.readouterr().out.split("\nvideo\n", 1)[1]
    assert _ref(lb, *PIER).split("#")[1] not in block and "2 refused" in block


def test_a_second_no_supersedes_the_first_and_is_the_scenes_no_now(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """SPEC §3: a derived reader reads the standing lines of a kind. The second no on the pier (a later
    inference proposed Hjem) supersedes the first (Vollen Brygge): it is the scene's no now, and the
    proposal the first answered is held back no longer; `show` marks the first superseded."""
    from test_videos_infer import Recording, look

    assert _review("--reject", "1") == 0  # the pier: not Vollen Brygge
    first = _new(lb, 0)[-1]

    def infer_again(model: str, tape: Any) -> None:
        vision = FakeVision()
        vision.model = model  # another model: the file is inferred again, the scenes cut the same way
        monkeypatch.setattr(scenes, "detect", lambda *_a: (FakeMedia({HOME_01: tape}), FakeSpeech(), vision))
        _cache(lb, HOME_01)
        assert _infer() == 0

    pier = TAPE[1]
    home = Recording(
        pier.length, pier.level_db, pier.cut_in, look("A pier.", "outdoors, a harbour", "summer", ["HJEM"])
    )
    infer_again("second-vision-model", (TAPE[0], home, TAPE[2], TAPE[3]))
    rows = video_review.read(lb).rows
    (n,) = [n for n, row in enumerate(rows, 1) if row.ref == _ref(lb, *PIER)]
    assert rows[n - 1].proposal["place"]["id"] == "Hjem"  # type: ignore[index]
    seq = _seq(lb)
    assert _review("--reject", str(n)) == 0
    (second,) = _new(lb, seq)
    assert second["payload"]["supersedes"] == first["id"]
    assert second["payload"]["proposal"]["place"]["id"] == "Hjem"
    queue = video_review.read(lb)
    assert queue.noes[_ref(lb, *PIER)]["id"] == second["id"], "one standing no for the scene"
    assert queue.rejected == 1, "one scene refused"
    with lb.index() as idx:
        assert idx.superseded("scene-review") == {first["id"]: int(second["seq"])}
    infer_again("third-vision-model", TAPE)  # Vollen Brygge proposed again: the superseded no is out
    (row,) = [row for row in video_review.read(lb).rows if row.ref == _ref(lb, *PIER)]
    assert row.proposal["place"]["id"] == "Vollen Brygge"  # type: ignore[index]
    capsys.readouterr()
    day = (
        datetime.fromisoformat(second["at"].replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Oslo")).date()
    )
    cli.main(["show", day.isoformat()])
    out = capsys.readouterr().out
    assert f"scene-review manual         superseded by #{second['seq']}" in out
    assert f"scene 0:40{EN_DASH}1:30 \u2260 Hjem" in out and "\u2260 Vollen Brygge" not in out


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"schema": "entity-review/v1"}, "schema"),
        ({"verdict": "same"}, "verdict"),
        ({"ref": {"kind": "point", "value": "59.9,10.7"}}, "ref"),
        ({"scene": {"video": "another", "start_s": 40.0, "end_s": 90.0}}, "scene"),
        ({"proposal": "Vollen Brygge"}, "proposal"),
        ({"draft": ""}, "draft"),
        ({"method": "model"}, "method"),
        ({"supersedes": 7}, "supersedes"),
        ({"logbook_head": "abc"}, "logbook_head"),
    ],
)
def test_the_profile_refuses_what_is_not_a_scene_review(
    lb: Logbook, change: dict[str, Any], problem: str
) -> None:
    assert _review("--reject", "1") == 0
    (no,) = [line for line in Logbook(lb.root).lines() if line["kind"] == "scene-review"]
    assert video_review.validate_scene_review(no["payload"]) == []
    problems = video_review.validate_scene_review({**no["payload"], **change})
    assert problems and problems[0].startswith(problem), problems


def test_rfc_0040_says_scene_review_v1_as_the_writer_writes_it(lb: Logbook) -> None:
    """The profile's JSON Schema in RFC 0040 §5 holds its own example (§8) and a line the writer wrote,
    and `validate_scene_review` agrees with it on both."""
    import re

    from jsonschema import Draft202012Validator

    page = (Path(__file__).resolve().parents[1] / "rfcs" / "0040-videos.md").read_text(encoding="utf-8")
    blocks = [json.loads(b) for b in re.findall(r"```json\n(.*?)\n```", page, re.S)]
    (schema,) = [b for b in blocks if b.get("title") == "scene-review/v1"]
    (example,) = [b for b in blocks if b.get("kind") == "scene-review"]
    assert _review("--reject", "1") == 0
    (written,) = [line for line in Logbook(lb.root).lines() if line["kind"] == "scene-review"]
    validator = Draft202012Validator(schema)
    for line in (example, written):
        validator.validate(line["payload"])
        assert video_review.validate_scene_review(line["payload"]) == []
        assert (line["kind"], line["source"], line["tier"]) == ("scene-review", "manual", 2)
    assert set(written["payload"]) == set(example["payload"])


# -- the independent check of the queue: every option, every number, the terminal, the identity ------


KINDS = ("person", "org", "idea", "asset", "place", "video", "goal", "speakers")
EVERY = "`review person|org|idea|asset|place|video|goal|speakers …`"
PLACE_ARGS: dict[str, tuple[str, ...]] = {
    "--near": ("--near", "Hjem"),
    "--radius": ("--radius", "5"),
    "--verbose": ("--verbose",),
    "--ask-photos": ("--ask-photos",),
    "--all": ("--all",),
    "--limit": ("--limit", "3"),
    "--photos-library": ("--photos-library", "x"),
    "--migrate-rejects": ("--migrate-rejects",),
}
VIDEO_ARGS: dict[str, tuple[str, ...]] = {
    "--place": ("--place", "1", "Hjem"),
    "--date": ("--date", "1", "1994"),
    "--ask": ("--ask", "1"),
    "--asked": ("--asked",),
    "--answered": ("--answered",),
}
SPEAKER_ARGS: dict[str, tuple[str, ...]] = {  # main's `review speakers` (RFC 0038 §4)
    "--unnamed": ("--unnamed", "1"),
    "--same-as": ("--same-as", "2"),
    "--consent": ("--consent", "1=yes"),
    "--play": ("--play", "1"),
    "--named": ("--named",),
    "--recording": ("--recording", "1"),
    "--day": ("--day", "2026-06-08"),
}
TELL_ARGS: dict[str, tuple[str, ...]] = {
    "--accept": ("--accept", "1"),
    "--reject": ("--reject", "1"),
    "--name": ("--name", "1", "X"),
    "--all-above": ("--all-above", "5"),
}
TOP = ("--top", "1")


def _out(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    capsys.readouterr()
    cli.main([*args])
    return capsys.readouterr().out


def _tty(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> None:
    it = iter(answers)
    monkeypatch.setattr(builtins, "input", lambda _p: next(it))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)


def _refusals() -> list[tuple[str | None, tuple[str, ...], str]]:
    found: list[tuple[str | None, tuple[str, ...], str]] = []
    for kind in KINDS:
        if kind != "place":
            for flag, argv in PLACE_ARGS.items():
                found.append((kind, argv, f"review {kind}: {flag} goes with `review place`"))
            found.append(
                (
                    kind,
                    (*PLACE_ARGS["--near"], *PLACE_ARGS["--verbose"]),
                    f"review {kind}: --near, --verbose go with `review place`",
                )
            )
        if kind != "video":
            for flag, argv in VIDEO_ARGS.items():
                found.append((kind, argv, f"review {kind}: {flag} goes with `review video`"))
            found.append(
                (
                    kind,
                    (*VIDEO_ARGS["--place"], *VIDEO_ARGS["--date"], *VIDEO_ARGS["--ask"]),
                    f"review {kind}: --place, --date, --ask go with `review video`",
                )
            )
        if kind != "speakers":
            for flag, argv in SPEAKER_ARGS.items():
                found.append((kind, argv, f"review {kind}: {flag} goes with `review speakers`"))
        if kind not in ("place", "video"):
            found.append((kind, TOP, f"review {kind}: --top goes with `review place` or `review video`"))
    # combinations: main's order, a place's option first, then a video's, then --top
    found += [
        ("place", (*TOP, *VIDEO_ARGS["--ask"]), "review place: --ask goes with `review video`"),
        ("video", (*TOP, *PLACE_ARGS["--near"]), "review video: --near goes with `review place`"),
        ("org", (*TOP, *VIDEO_ARGS["--ask"]), "review org: --top goes with `review place` or `review video`"),
        ("org", (*TOP, *PLACE_ARGS["--near"]), "review org: --top, --near go with `review place`"),
        ("org", (*PLACE_ARGS["--near"], *VIDEO_ARGS["--ask"]), "review org: --near goes with `review place`"),
        (
            "person",
            (*VIDEO_ARGS["--asked"], "--accept", "1"),
            "review person: --asked goes with `review video`",
        ),
        (
            "video",
            ("--name", "1", "Hjem"),
            "review video: --name goes with a new org, idea, asset or place;"
            " a scene takes --place N NAME or --date N WHEN",
        ),
        (
            "video",
            ("--all-above", "50"),
            "review video: a scene's proposal has no score;"
            " --all-above goes with person, org, idea and asset",
        ),
    ]
    for flag, argv in {**TELL_ARGS, "--top": TOP, **PLACE_ARGS, **VIDEO_ARGS, **SPEAKER_ARGS}.items():
        found.append((None, argv, f"review: say which kind {flag} is for: {EVERY}"))
    found.append((None, (*VIDEO_ARGS["--ask"], *TOP), f"review: say which kind --top --ask is for: {EVERY}"))
    found.append(
        (
            None,
            ("--accept", "1", *VIDEO_ARGS["--asked"]),
            f"review: say which kind --accept --asked is for: {EVERY}",
        )
    )
    return found


@pytest.mark.parametrize(
    ("kind", "argv", "sentence"),
    _refusals(),
    ids=[f"{kind or 'none'}:{' '.join(argv)}" for kind, argv, _ in _refusals()],
)
def test_an_option_of_another_kind_is_one_sentence_in_mains_form_and_writes_nothing(
    lb: Logbook,
    capsys: pytest.CaptureFixture[str],
    kind: str | None,
    argv: tuple[str, ...],
    sentence: str,
) -> None:
    seq = _seq(lb)
    code, err = _said(capsys, "review", *([kind] if kind else []), *argv)
    assert code == 2, (kind, argv, err)
    assert err.splitlines() == [sentence], (kind, argv, err)
    assert _seq(lb) == seq, "refused before the first line"


CROSSED: list[tuple[tuple[str, ...], str]] = [
    *(
        (("speakers", *argv), f"review speakers: {flag} goes with `review video`")
        for flag, argv in VIDEO_ARGS.items()
    ),
    (
        ("speakers", *VIDEO_ARGS["--place"], *VIDEO_ARGS["--date"], *VIDEO_ARGS["--asked"]),
        "review speakers: --place, --date, --asked go with `review video`",
    ),
    (
        ("speakers", *VIDEO_ARGS["--ask"], *SPEAKER_ARGS["--unnamed"]),
        "review speakers: --ask goes with `review video`",
    ),
    *(
        (("video", *argv), f"review video: {flag} goes with `review speakers`")
        for flag, argv in SPEAKER_ARGS.items()
    ),
    (
        ("video", *SPEAKER_ARGS["--unnamed"], *SPEAKER_ARGS["--consent"], *SPEAKER_ARGS["--named"]),
        "review video: --unnamed, --consent, --named go with `review speakers`",
    ),
    (
        ("video", *SPEAKER_ARGS["--play"], *VIDEO_ARGS["--ask"]),
        "review video: --play goes with `review speakers`",
    ),
]


@pytest.mark.parametrize(("argv", "sentence"), CROSSED, ids=[" ".join(argv) for argv, _ in CROSSED])
def test_review_speakers_refuses_a_scenes_options_and_review_video_a_voices(
    lb: Logbook, capsys: pytest.CaptureFixture[str], argv: tuple[str, ...], sentence: str
) -> None:
    """Main's speakers and this branch's video are two queues of one `review`, each with options of its
    own: each refuses the other's in main's one sentence, before anything is read or written."""
    seq = _seq(lb)
    code, err = _said(capsys, "review", *argv)
    assert code == 2, (argv, err)
    assert err.splitlines() == [sentence], (argv, err)
    assert _seq(lb) == seq, "refused before the first line"


@pytest.mark.parametrize("kind", ["video", "place", None], ids=["video", "place", "none"])
def test_asked_with_answered_is_refused_in_the_sittings_form(
    lb: Logbook, capsys: pytest.CaptureFixture[str], kind: str | None
) -> None:
    """One sentence, as every refusal of the sitting: two lists for `review video`, a video's options
    for any other kind, and `say which kind` for `review` alone."""
    seq = _seq(lb)
    code, err = _said(capsys, "review", *([kind] if kind else []), "--asked", "--answered")
    assert code == 2 and _seq(lb) == seq
    lines = err.splitlines()
    assert len(lines) == 1 and lines[0].startswith("review"), err


@pytest.mark.parametrize(
    ("argv", "why"),
    [
        (("--accept", "1", "--place", "9", "Hjem"), "scene 9 is not in the queue (1 to 4)"),
        (("--accept", "1", "--date", "9", "1994"), "scene 9 is not in the queue (1 to 4)"),
        (("--accept", "1", "--ask", "9"), "scene 9 is not in the queue (1 to 4)"),
        (("--reject", "1", "--ask", "0"), "scene 0 is not in the queue (1 to 4)"),
        (("--accept", "1,9"), "scene 9 is not in the queue (1 to 4)"),
        (("--reject", "2", "--accept", "9"), "scene 9 is not in the queue (1 to 4)"),
        (("--accept", "1", "--date", "2", "2031"), "2031-01-01 is after today"),
        (("--accept", "1", "--date", "2", "summer 2031"), "after today"),
        (("--accept", "1", "--date", "2", "1994-13"), "is not a date of the calendar"),
        (("--accept", "1", "--date", "2", "1994-02-30"), "is not a date of the calendar"),
        (("--accept", "1", "--date", "2", "1994-08..1994-06"), "a range runs from an earlier date"),
        (("--accept", "1", "--date", "2", "..1994"), "is not a date"),
        (("--accept", "1", "--place", "3", "Nowhere"), "'Nowhere' is not a place of places.json"),
        (("--accept", "1", "--reject", "2", "--ask", "3", "--place", "4", "Nowhere"), "not a place"),
        (("--accept", "1", "--reject", "2", "--ask", "3", "--date", "4", "2031"), "after today"),
        (("--ask", "1", "--accept", "1"), "scene 1 is given --accept and --ask; say one"),
        (("--ask", "1", "--date", "1", "1994"), "scene 1 is given --date and --ask; say one"),
        (("--ask", "1", "--reject", "1"), "scene 1 is given --reject and --ask; say one"),
        (("--ask", "1,2", "--reject", "2"), "scene 2 is given --reject and --ask; say one"),
        (("--accept", "3", "--place", "3", "none", "--date", "3", "none"), "scene 3: nothing to confirm"),
        (("--place", "3", "none"), "scene 3: nothing to confirm"),
        (("--place", "x", "Hjem"), "'x' is not a scene's number"),
        (("--date", "1.5", "1994"), "'1.5' is not a scene's number"),
        (("--ask", "1,x"), "'x' is not a scene's number"),
        (("--asked", "--accept", "1"), "scene 1 is not in the queue (1 to 0)"),
        (("--answered", "--reject", "1"), "scene 1 is not in the queue (1 to 0)"),
        (("--top", "-1", "--accept", "1"), "--top takes a number from 0, not -1"),
    ],
    ids=lambda v: " ".join(v) if isinstance(v, tuple) else None,
)
def test_every_number_and_answer_is_checked_before_the_first_line(
    lb: Logbook, capsys: pytest.CaptureFixture[str], argv: tuple[str, ...], why: str
) -> None:
    seq = _seq(lb)
    code, err = _said(capsys, "review", "video", *argv)
    assert code == 2 and why in err, (argv, err)
    assert len(err.splitlines()) == 1 and err.startswith("review video: "), err
    assert _seq(lb) == seq, "nothing written"


@pytest.mark.parametrize(
    "argv",
    [
        ("--place", "1", "Hjem", "--place", "1", "Vollen Brygge"),
        ("--date", "1", "1994", "--date", "1", "1995"),
    ],
    ids=["place-twice", "date-twice"],
)
def test_the_same_part_of_a_scene_given_twice_is_refused_as_name_twice_is(
    lb: Logbook, capsys: pytest.CaptureFixture[str], argv: tuple[str, ...]
) -> None:
    """Main's sitting refuses `--name 1 A --name 1 B` ("say one"); a scene's --place or --date twice
    takes the last silently (a dict comprehension)."""
    seq = _seq(lb)
    code, err = _said(capsys, "review", "video", *argv)
    assert code == 2 and "say one" in err, (argv, err)
    assert _seq(lb) == seq


def test_json_of_what_was_written_names_every_answer_and_its_line(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    third = video_review.read(lb).rows[2].ref
    seq = _seq(lb)
    capsys.readouterr()
    assert _review("--accept", "1", "--reject", "2", "--ask", "3", "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert list(data) == ["written"]
    lines = _new(lb, seq)
    assert [(w["answer"], w["scene"], w["line"]) for w in data["written"]] == [
        ("accept", _ref(lb, *PIER), lines[0]["id"]),
        ("reject", _ref(lb, *GARDEN), lines[1]["id"]),
        ("ask", third, lines[2]["id"]),
    ]
    assert data["written"][1]["text"] == "not so: never proposed for this scene again"
    assert data["written"][2]["text"] == "kept to ask the family: an open task in the list videos"
    capsys.readouterr()
    assert _review("--answered", "--accept", "1", "--json") == 0
    again = json.loads(capsys.readouterr().out)
    assert again == {
        "written": [
            {
                "scene": _ref(lb, *PIER),
                "answer": "accept",
                "line": None,
                "text": "already confirmed so; nothing written",
            }
        ]
    }


def test_text_of_what_was_written_is_one_row_per_answer(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = _seq(lb)
    capsys.readouterr()
    assert _review("--reject", "2", "--accept", "1") == 0
    out = capsys.readouterr().out.splitlines()
    first, second = _new(lb, seq)
    assert out == [
        f"Familiens videoer / Home 01 · t=40.00,90.00: confirmed Vollen Brygge (place) (#{first['seq']})",
        f"Familiens videoer / Home 01 · t=90.00,130.00: not so: never proposed for this scene again"
        f" (#{second['seq']})",
    ]


def test_review_alone_on_a_record_with_no_videos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = Logbook.init(tmp_path / "empty", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(empty.root))
    seq = _seq(empty)
    out = _out(capsys, "review").splitlines()
    assert [line for line in out if not line.startswith(" ")] == list(KINDS)
    assert out[out.index("video") + 1 : out.index("goal")] == [
        "  0 scenes proposed, 0 with nothing to go on · 0 confirmed, 0 refused, 0 kept to ask the family"
        " · tier 2",
        "  nothing to review: `videos infer` proposes the scenes of the files in the cache",
    ]
    data = json.loads(_out(capsys, "review", "--json"))
    assert data["video"]["rows"] == [] and data["video"]["confirmed"] == 0
    assert _seq(empty) == seq


def test_review_alone_without_the_identity_is_one_sentence_naming_the_queue(
    sealed: Logbook,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """The identity a sealed line needs is said as the video queue's refusal, `review video:`, as every
    other refusal of a queue in the loop is."""
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(tmp_path / "keys" / "nowhere.txt"))
    seq = _seq(sealed)
    code, err = _said(capsys, "review")
    assert code == 2 and _seq(sealed) == seq
    assert len(err.splitlines()) == 1 and "identity" in err, err
    assert err.startswith("review video: "), err


def test_review_alone_as_json_without_the_identity_prints_no_half_object(
    sealed: Logbook,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(tmp_path / "keys" / "nowhere.txt"))
    seq = _seq(sealed)
    capsys.readouterr()
    with pytest.raises(SystemExit) as e:
        cli.main(["review", "--json"])
    out, err = capsys.readouterr()
    assert e.value.code == 2 and _seq(sealed) == seq
    assert out == "" and len(err.splitlines()) == 1 and "identity" in err, (out, err)


def test_an_asks_answer_and_the_tasks_close_are_appended_under_one_hold(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    from logbook.core import store

    assert _review("--ask", "1") == 0
    held: list[Any] = []
    real_read, real_append = video_review.read, Logbook.append

    def read(book: Logbook, mode: str = "open") -> video_review.Queue:
        held.append(("read", bool(store._held)))
        return real_read(book, mode)

    def append(self: Logbook, *args: Any, **kwargs: Any) -> Any:
        held.append(bool(store._held))
        return real_append(self, *args, **kwargs)

    monkeypatch.setattr(video_review, "read", read)
    monkeypatch.setattr(Logbook, "append", append)
    assert _review("--asked", "--accept", "1") == 0
    assert held == [("read", False), True, True], "the attribution and the task's close, one hold"
    assert not store._held and not (lb.root / store.LOCK_FILE).exists()


def test_on_a_terminal_an_answer_it_does_not_know_asks_the_same_scene_again(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """As every queue asks on a terminal, an answer it does not know asks the same scene again: `x`
    then `y` confirms the pier, not the garden after it."""
    _tty(monkeypatch, ["x", "y", "q"])
    seq = _seq(lb)
    assert _review() == 0
    (line,) = _new(lb, seq)
    assert line["payload"]["ref"]["value"] == _ref(lb, *PIER)


def test_on_a_terminal_an_answer_the_scene_cannot_take_asks_the_same_scene_again(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`y` on a scene with nothing to go on is refused ("nothing to confirm"), and the same scene is
    asked again, as the other queues ask the same proposal again: the `a` is that scene's."""
    third = video_review.read(lb).rows[2].ref
    _tty(monkeypatch, ["", "", "y", "a", "q"])
    seq = _seq(lb)
    assert _review() == 0
    assert "nothing to confirm" in capsys.readouterr().out
    (task,) = _new(lb, seq)
    assert task["kind"] == "task" and task["payload"]["extra"]["scene"] == third


def test_on_a_terminal_the_end_of_input_stops_with_nothing_written(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def eof(_p: str) -> str:
        raise EOFError

    monkeypatch.setattr(builtins, "input", eof)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    seq = _seq(lb)
    assert _review() == 0
    assert _seq(lb) == seq


def test_top_zero_lists_no_scene_and_says_how_many_more(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _out(capsys, "review", "video", "--top", "0").splitlines()
    assert not any(line[:4].strip().isdigit() for line in out)
    assert "  and 4 more; --top shows more" in out and out[-1].startswith("nothing written")
    assert json.loads(_out(capsys, "review", "video", "--top", "0", "--json"))["rows"] == []


def test_asking_the_family_about_a_confirmed_scene_and_confirming_it_again_closes_the_ask(
    lb: Logbook,
) -> None:
    """`--answered --ask N` keeps a confirmed scene to ask the family; confirming it again with the
    same answer writes no second attribution and closes the family's task."""
    assert _review("--accept", "1") == 0
    assert _review("--answered", "--ask", "1") == 0
    assert [r.ref for r in video_review.read(lb, "asked").rows] == [_ref(lb, *PIER)]
    assert _review("--asked", "--accept", "1") == 0
    assert video_review.read(lb, "asked").rows == [], "the family's task is closed"
    closed = _new(lb, 0)[-1]
    assert (closed["kind"], closed["payload"]["status"]) == ("task", "done")


def test_the_other_queues_and_verify_read_a_record_with_every_scene_answer(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _review("--accept", "1", "--reject", "2", "--ask", "3", "--reject", "4") == 0
    out = _out(capsys, "review").splitlines()
    assert [line for line in out if not line.startswith(" ")] == list(KINDS)
    assert json.loads(_out(capsys, "review", "place", "--json"))["proposals"] == []
    assert places_review.rejections(lb) == [], "a scene's no is no place's no"
    cli.main(["verify"])


# -- the independent check of scene-review/v1: tier, the chain under retraction, the other queues -----


A_PIER_AT_HOME = (
    TAPE[0],
    Recording(
        TAPE[1].length,
        TAPE[1].level_db,
        TAPE[1].cut_in,
        look("A pier.", "outdoors, a harbour", "summer", ["HJEM"]),
    ),
    TAPE[2],
    TAPE[3],
)


def _infer_again(lb: Logbook, monkeypatch: pytest.MonkeyPatch, model: str, tape: Any) -> None:
    """The file inferred again under another vision model: the scenes cut the same way, the proposals
    whatever `tape` says."""
    vision = FakeVision()
    vision.model = model
    monkeypatch.setattr(scenes, "detect", lambda *_a: (FakeMedia({HOME_01: tape}), FakeSpeech(), vision))
    _cache(lb, HOME_01)
    assert _infer() == 0


def _pier_row(lb: Logbook) -> video_review.Row | None:
    return next((row for row in video_review.read(lb).rows if row.ref == _ref(lb, *PIER)), None)


def _pier_number(lb: Logbook) -> str:
    (n,) = [n for n, row in enumerate(video_review.read(lb).rows, 1) if row.ref == _ref(lb, *PIER)]
    return str(n)


def _two_noes(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], dict[str, Any]]:
    """The pier refused as Vollen Brygge, inferred again as Hjem and refused again: two noes, the
    second superseding the first."""
    assert _review("--reject", "1") == 0
    first = _new(lb, 0)[-1]
    assert first["payload"]["proposal"]["place"]["id"] == "Vollen Brygge"
    _infer_again(lb, monkeypatch, "second-vision-model", A_PIER_AT_HOME)
    seq = _seq(lb)
    assert _review("--reject", _pier_number(lb)) == 0
    (second,) = _new(lb, seq)
    assert second["payload"]["supersedes"] == first["id"]
    assert second["payload"]["proposal"]["place"]["id"] == "Hjem"
    return first, second


def test_answered_tier_is_the_highest_of_the_lines_answered_and_never_under_2(lb: Logbook) -> None:
    three = Logbook(lb.root).append(
        "2026-10-14T18:00:00Z", "synthetic", "note", 3, {"schema": "note/v1", "text": "a tier-3 note"}
    )
    assert video_review.answered_tier(lb, []) == 2
    assert video_review.answered_tier(lb, ["no-such-line"]) == 2
    assert video_review.answered_tier(lb, [lb.video["id"]]) == 2  # type: ignore[attr-defined]
    assert video_review.answered_tier(lb, [lb.video["id"], str(three["id"])]) == 3  # type: ignore[attr-defined]


def test_a_no_on_a_scene_whose_draft_cites_a_tier_3_line_is_tier_3(lb: Logbook) -> None:
    """A draft of the latest inference, forged at tier 3 with a tier-3 line among its evidence, for a
    stretch of the file no other draft names: its no takes the highest tier of what it answers."""
    book = Logbook(lb.root)
    three = book.append(
        "2026-10-14T18:00:00Z", "synthetic", "note", 3, {"schema": "note/v1", "text": "a tier-3 note"}
    )
    (pier,) = [
        line
        for line in book.lines()
        if line["kind"] == "draft" and line["payload"]["subject"] == [_ref(lb, *PIER)]
    ]
    payload = copy.deepcopy(pier["payload"])
    ref = _ref(lb, "170.00", "200.00")
    payload["subject"] = [ref]
    payload["raw_id"] = f"{payload.get('raw_id', 'draft')}:forged"
    payload["extra"]["scene"].update({"start_s": 170.0, "end_s": 200.0, "n": 5, "of": 5})
    payload["segments"][0]["evidence"] = [lb.video["id"], str(three["id"])]  # type: ignore[attr-defined]
    book.append(pier["at"], pier["source"], "draft", 3, payload, tz=pier["tz"])
    queue = video_review.read(lb)
    assert queue.tier == 3
    (n,) = [n for n, row in enumerate(queue.rows, 1) if row.ref == ref]
    seq = _seq(lb)
    assert _review("--reject", str(n)) == 0
    (no,) = _new(lb, seq)
    assert no["kind"] == "scene-review" and no["tier"] == 3, no["tier"]
    assert str(three["id"]) in no["payload"]["evidence"]


def test_a_sealed_record_reads_the_tier_of_what_the_no_answers(sealed: Logbook) -> None:
    three = Logbook(sealed.root).append(
        "2026-10-14T18:00:00Z", "synthetic", "note", 3, {"schema": "note/v1", "text": "sealed tier three"}
    )
    assert video_review.answered_tier(sealed, [str(three["id"])]) == 3
    seq = _seq(sealed)
    assert _review("--reject", "1") == 0
    (no,) = _new(sealed, seq)
    assert no["kind"] == "scene-review" and no["tier"] == 2


def test_retracting_the_superseding_no_makes_the_first_the_standing_one_and_the_second_proposal_returns(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = _two_noes(lb, monkeypatch)
    Logbook(lb.root).retract(int(second["seq"]), "wrong")
    queue = video_review.read(lb)
    assert queue.noes[_ref(lb, *PIER)]["id"] == first["id"]
    assert queue.rejected == 1
    row = _pier_row(lb)
    assert row is not None, "the retracted no's proposal returns"
    assert row.proposal["place"]["id"] == "Hjem"  # type: ignore[index]
    seq = _seq(lb)
    assert _review("--reject", _pier_number(lb)) == 0
    (third,) = _new(lb, seq)
    assert third["payload"]["supersedes"] == first["id"], (
        "the third no supersedes the standing one, the first"
    )
    assert video_review.read(lb).noes[_ref(lb, *PIER)]["id"] == third["id"]


def test_retracting_the_superseded_no_brings_its_proposal_back_and_the_second_stands(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = _two_noes(lb, monkeypatch)
    Logbook(lb.root).retract(int(first["seq"]), "wrong")
    queue = video_review.read(lb)
    assert queue.noes[_ref(lb, *PIER)]["id"] == second["id"]
    assert _pier_row(lb) is None, "Hjem, the latest draft's proposal, is still refused"
    _infer_again(lb, monkeypatch, "third-vision-model", TAPE)  # Vollen Brygge proposed again
    row = _pier_row(lb)
    assert row is not None and row.proposal["place"]["id"] == "Vollen Brygge"  # type: ignore[index]


def test_a_superseded_no_is_out_as_spec_3_says(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    """SPEC §3: a line is standing when not retracted and no later line of its kind names it in
    `supersedes`, and a derived reader takes the standing lines of a kind. The index says the first no
    is superseded; the queue reads it as out, so Vollen Brygge is asked again when proposed again."""
    first, second = _two_noes(lb, monkeypatch)
    with lb.index() as idx:
        assert idx.superseded(videos.NO_KIND) == {first["id"]: int(second["seq"])}
    _infer_again(lb, monkeypatch, "third-vision-model", TAPE)  # Vollen Brygge proposed again
    row = _pier_row(lb)
    assert row is not None and row.proposal["place"]["id"] == "Vollen Brygge", (  # type: ignore[index]
        "a superseded no holds nothing back"
    )


def test_the_same_no_again_after_its_retraction_is_written_and_supersedes_nothing(lb: Logbook) -> None:
    assert _review("--reject", "1") == 0
    first = _new(lb, 0)[-1]
    Logbook(lb.root).retract(int(first["seq"]), "wrong")
    assert _pier_row(lb) is not None
    seq = _seq(lb)
    assert _review("--reject", "1") == 0
    (again,) = _new(lb, seq)
    assert again["payload"]["raw_id"] == first["payload"]["raw_id"]
    assert "supersedes" not in again["payload"], "a retracted no is nothing to supersede"
    assert _pier_row(lb) is None
    assert video_review.read(lb).rejected == 1


def test_a_no_on_an_asked_scene_keeps_the_ask_open_and_offers_no_proposal(lb: Logbook) -> None:
    assert _review("--ask", "1") == 0
    seq = _seq(lb)
    assert _review("--asked", "--reject", "1") == 0
    (no,) = _new(lb, seq)
    assert no["kind"] == "scene-review" and no["payload"]["proposal"]["place"]["id"] == "Vollen Brygge"
    asked = video_review.read(lb, "asked")
    (row,) = asked.rows
    assert row.refused and row.proposal is None and asked.asked == 1 and asked.rejected == 1
    assert _ref(lb, *PIER) not in [r.ref for r in video_review.read(lb).rows]
    assert _review("--asked", "--accept", "1") == 2, "nothing left to confirm without --place or --date"
    seq = _seq(lb)
    assert _review("--asked", "--place", "1", "Hjem") == 0
    attribution, closed = _new(lb, seq)
    assert attribution["kind"] == "attribution" and closed["payload"]["status"] == "done"


def test_the_sitting_and_every_other_queue_print_the_same_after_a_scene_no(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    def others() -> list[str]:
        found = []
        for args in (
            ["review"],
            *[["review", kind, "--json"] for kind in ("person", "org", "idea", "asset", "place")],
        ):
            capsys.readouterr()
            cli.main(args)
            out = capsys.readouterr().out
            if args == ["review"]:
                out = out.split("\nvideo\n", 1)[0]
            else:
                data = json.loads(out)
                data.pop("head", None)
                out = json.dumps(data, sort_keys=True)
            found.append(out)
        return found

    before = others()
    assert _review("--reject", "1,2") == 0
    assert others() == before


def test_the_rfc_schema_and_the_validator_agree_and_the_validator_says_what_the_schema_cannot(
    lb: Logbook,
) -> None:
    """Both texts say the profile: the schema types the scene's offsets as numbers, as the validator
    does; that they are the ref's, and the ref's end after its start, the schema cannot say and the
    validator does."""
    import re
    from pathlib import Path

    from jsonschema import Draft202012Validator

    page = (Path(__file__).resolve().parents[1] / "rfcs" / "0040-videos.md").read_text(encoding="utf-8")
    blocks = [json.loads(b) for b in re.findall(r"```json\n(.*?)\n```", page, re.S)]
    (schema,) = [b for b in blocks if b.get("title") == "scene-review/v1"]
    assert _review("--reject", "1") == 0
    (no,) = [line for line in Logbook(lb.root).lines() if line["kind"] == "scene-review"]
    validator = Draft202012Validator(schema)
    text_offsets = {
        **no["payload"],
        "scene": {**no["payload"]["scene"], "start_s": "40.00", "end_s": "90.00"},
    }
    assert not validator.is_valid(text_offsets) and video_review.validate_scene_review(text_offsets)
    video = lb.video["id"]  # type: ignore[attr-defined]
    backwards = {**no["payload"], "ref": {"kind": "scene", "value": f"{video}#t=90.00,40.00"}}
    backwards.pop("scene")
    assert validator.is_valid(backwards) and video_review.validate_scene_review(backwards)


def test_show_marks_a_corrected_attribution_superseded(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """SPEC §3: `show` lists a superseded line with a mark; a scene's answer corrected is one."""
    assert _review("--accept", "1") == 0
    first = _new(lb, 0)[-1]
    assert _review("--answered", "--date", "1", "summer 1994") == 0
    second = _new(lb, 0)[-1]
    assert second["payload"]["supersedes"] == first["id"]
    day = (
        datetime.fromisoformat(second["at"].replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Oslo")).date()
    )
    capsys.readouterr()
    cli.main(["show", day.isoformat()])
    out = capsys.readouterr().out
    assert f"superseded by #{second['seq']}" in out
    assert f"scene 0:40{EN_DASH}1:30 → Vollen Brygge, 1994-06-01..1994-08-31" in out


def test_a_no_on_a_confirmed_scene_is_refused_from_the_asked_list_too(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """RFC 0040 §5 rule 5, whatever list the scene is shown in: confirmed, then kept to ask the family,
    then refused from `--asked`, the scene would stand both confirmed and refused."""
    assert _review("--accept", "1") == 0
    assert _review("--answered", "--ask", "1") == 0
    seq = _seq(lb)
    code, err = _said(capsys, "review", "video", "--asked", "--reject", "1")
    assert code == 2 and "a no does not undo it" in err, err
    assert _seq(lb) == seq, "nothing written"
    assert video_review.read(lb).confirmed == 1 and video_review.read(lb).noes == {}
