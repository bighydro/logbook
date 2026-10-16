"""`logbook review video`: the owner's say over the scenes `videos infer` proposed, one scene at a time,
the sixth queue of RFC 0037's one review sitting. Accepting a scene writes exactly one `attribution/v1`
line carrying the scene's offsets and touches no other line, the video's least of all; the no is
RFC 0037's `entity-review/v1` and the proposal never returns for that scene; "ask the family" is an open
task the scene leaves the queue with, and answering it later closes the task; every line is tier 2 and
none of them crosses a tier-1 entry; nothing opens a connection.

The synthetic tape of `tests/test_videos_infer.py` (an invented family of Oslo, who does not exist),
inferred with the same fakes, is the queue."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from test_videos_infer import (
    HOME_01,
    TAPE,
    VOLLEN,
    FakeMedia,
    FakeSpeech,
    FakeVision,
    _cache,
    _video,
)
from test_videos_infer import _run as _infer

from logbook import cli
from logbook.contrib import video_review
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
    assert (no["kind"], no["tier"], no["source"]) == ("entity-review", 2, "manual")
    assert no["payload"]["schema"] == "entity-review/v1"
    assert no["payload"]["type"] == "scene" and no["payload"]["verdict"] == "different"
    assert no["payload"]["ref"] == {"kind": "scene", "value": _ref(lb, *PIER)}
    assert no["payload"]["entity"] == {"type": "place", "id": "Vollen Brygge", "registry": "logbook"}
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
        "entity-review",
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
        "entity-review",
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
    assert review.KINDS[-1] == "video" and isinstance(review.queue_of("video"), review.Queue)


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
        (("review", "video", "--asked", "--answered"), "not allowed with argument"),
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
    ]
    block = out[out.index("video") + 1 :]
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
