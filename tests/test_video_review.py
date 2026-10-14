"""`logbook review videos`: the owner's say over the scenes `videos infer` proposed, one scene at a time,
in RFC 0037's review shape. Accepting a scene writes exactly one `attribution/v1` line carrying the
scene's offsets and touches no other line, the video's least of all; the no is RFC 0037's
`entity-review/v1` and the proposal never returns for that scene; "ask the family" is an open task the
scene leaves the queue with, and answering it later closes the task; every line is tier 2 and none of
them crosses a tier-1 entry; nothing opens a connection.

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
    assert no_network == [], f"review videos tried to connect: {no_network}"


def _review(*args: str) -> int:
    try:
        cli.main(["review", "videos", *args])
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
