"""`logbook videos infer`: each cached file read on this machine, scene by scene, one transcript line for
the file and one draft per scene proposing where and when, every sentence with its evidence; nothing
more precise than the evidence, no coordinate of the line's own, no socket opened, every line tier 2,
the video's line untouched, the file deleted from the cache once inferred unless `--keep`, and a file
inferred under the same models and settings never inferred twice.

The tape is synthetic: four recordings of an invented family's (Ines and Ola Nordmann of Oslo, who do
not exist) — a birthday indoors, a pier with a sign, a garden with the camera's date stamp burned in,
a snowy road. `FakeMedia` stands in for ffmpeg with the signals those recordings would give; the speech
and vision engines are fakes in the shape of the transcribe and describe extras', reading what the
fake media wrote, so no model and no decoder runs. The last test does the same on a tape ffmpeg
generates, where ffmpeg is installed."""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from test_videos_scenes import FFMPEG, make_tape

from logbook import cli
from logbook.contrib import media
from logbook.core import drafts
from logbook.core.store import Logbook
from logbook.labs import scenes as infer
from logbook.labs import transcribe

TODAY = date(2026, 10, 14)
IMPORTED = "2026-10-14T18:00:00Z"
HOME_01 = "1HomeTape01SyntheticVideoId01"
TAPE_02 = "1Tape02SyntheticVideoId000002"
VOLLEN = {"lat": 59.8012, "lon": 10.4613, "radius_m": 150, "kind": "other"}


@dataclass(frozen=True)
class Recording:
    """One synthetic recording: how long, how loud, how sharply the picture changes into it, what the
    vision model would say of its frames, what is said in it (offsets within it), and any weak change of
    picture inside it (a pan)."""

    length: float
    level_db: float
    cut_in: float
    look: dict[str, Any]
    said: tuple[tuple[float, float, str], ...] = ()
    inside: tuple[tuple[float, float], ...] = ()


def look(
    description: str, setting: str, season: str, signs: Sequence[str] = (), stamp: str | None = None
) -> dict[str, Any]:
    return {
        "description": description,
        "setting": setting,
        "season": season,
        "signs": list(signs),
        "stamp": stamp,
    }


TAPE = (
    Recording(
        40,
        -30,
        0.0,
        look("A birthday table with a cake and candles.", "indoors, a living room", "unknown"),
        ((5, 8, "Gratulerer med dagen"),),
        ((20, 0.15),),
    ),
    Recording(
        50,
        -18,
        0.7,
        look(
            "A wooden pier in a small harbour with sailing boats.",
            "outdoors, a harbour",
            "summer",
            ["VOLLEN BRYGGE"],
        ),
        ((10, 13, "Nå er vi på Vollen Brygge igjen"),),
    ),
    Recording(
        40,
        -28,
        0.18,
        look("Children playing in a garden.", "outdoors, a garden", "summer", stamp="JUL 14 1994"),
    ),
    Recording(40, -40, 0.5, look("A snowy road between trees.", "outdoors, a road", "winter")),
)
BOAT = (
    Recording(
        30, -25, 0.0, look("A white sailing boat at a mooring.", "outdoors, a marina", "summer", ["SOLVIND"])
    ),
    Recording(30, -12, 0.8, look("A kitchen table.", "indoors, a kitchen", "unknown", ["FJORDKIOSK"])),
)


class FakeMedia:
    """ffmpeg's answers for the synthetic tapes, by the cached file's stem (the Drive id)."""

    name = "fake-media"

    def __init__(self, tapes: dict[str, Sequence[Recording]]) -> None:
        self.tapes = tapes
        self.asked: list[tuple[str, str]] = []

    def _starts(self, path: Path) -> list[tuple[float, Recording]]:
        t, found = 0.0, []
        for r in self.tapes[path.stem]:
            found.append((t, r))
            t += r.length
        return found

    def _at(self, path: Path, t: float) -> Recording:
        return next(r for start, r in reversed(self._starts(path)) if start <= t)

    def probe(self, path: Path) -> media.Probe:
        self.asked.append(("probe", path.name))
        return media.Probe(sum(r.length for r in self.tapes[path.stem]), 720, 576, True, True)

    def cuts(self, path: Path, floor: float) -> list[tuple[float, float]]:
        found = [(start, r.cut_in) for start, r in self._starts(path) if start > 0]
        found += [(start + o, s) for start, r in self._starts(path) for o, s in r.inside]
        return sorted((t, s) for t, s in found if s >= floor)

    def levels(self, path: Path, window_s: float) -> list[tuple[float, float]]:
        found, t = [], 0.0
        total = sum(r.length for r in self.tapes[path.stem])
        while t < total:
            found.append((round(t, 2), self._at(path, t).level_db))
            t += window_s
        return found

    def frame(self, path: Path, at_s: float, out: Path) -> None:
        out.write_text(json.dumps({**self._at(path, at_s).look, "at": at_s}), encoding="utf-8")

    def audio(self, path: Path, start_s: float, end_s: float, out: Path) -> None:
        said = [
            (start + a - start_s, start + b - start_s, text)
            for start, r in self._starts(path)
            for a, b, text in r.said
            if start_s <= start + a < end_s
        ]
        out.write_text(json.dumps({"length": end_s - start_s, "said": said}), encoding="utf-8")


class FakeVision:
    """The describe extra's engine shape: answers as a model would, from what the fake media wrote."""

    name = "fake-vision"
    model = "synthetic-vision-2b"

    def __init__(self, ready: bool = True) -> None:
        self._ready = ready
        self.prompts: list[str] = []

    def ready(self) -> bool:
        return self._ready

    def fetch(self) -> None:
        raise AssertionError("videos infer never fetches a model")

    def describe(self, image: Path, prompt: str) -> str:
        self.prompts.append(prompt)
        seen = json.loads(image.read_text(encoding="utf-8"))
        seen.pop("at", None)
        return "```json\n" + json.dumps({**seen, "things": ["a table"]}) + "\n```"


class FakeSpeech:
    """The transcribe extra's engine shape, at ten samples a second: hears what the fake media wrote."""

    name = "fake-whisper"
    model = "synthetic-small"
    RATE = 10

    def __init__(self, ready: bool = True) -> None:
        self._ready = ready
        self._said: list[tuple[float, float, str]] = []

    def ready(self) -> bool:
        return self._ready

    def fetch(self) -> None:
        raise AssertionError("videos infer never fetches a model")

    def load(self, path: Path) -> tuple[list[float], int]:
        heard = json.loads(path.read_text(encoding="utf-8"))
        self._said = [tuple(s) for s in heard["said"]]  # type: ignore[misc]
        return [i / self.RATE for i in range(int(heard["length"] * self.RATE))], self.RATE

    def transcribe(self, samples: Sequence[float], rate: int, language: str | None) -> transcribe.Result:
        if not samples:
            return transcribe.Result([], "nb")
        start, end = samples[0], samples[-1] + 1 / rate
        return transcribe.Result(
            [transcribe.Segment(a - start, b - start, text) for a, b, text in self._said if start <= a < end],
            "nb",
        )


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
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
    return lb


@pytest.fixture
def engines(monkeypatch: pytest.MonkeyPatch, no_network: list[str]) -> Any:
    fake = FakeMedia({HOME_01: TAPE, TAPE_02: BOAT})
    found = (fake, FakeSpeech(), FakeVision())
    monkeypatch.setattr(infer, "detect", lambda _speech, _vision: found)
    yield found
    assert no_network == [], f"videos infer tried to connect: {no_network}"


def _video(lb: Logbook, drive_id: str, title: str) -> dict[str, Any]:
    """A video line as `sync drive --videos` writes it."""
    return lb.append(
        IMPORTED,
        "drive-videos",
        "video",
        2,
        {
            "schema": "video/v1",
            "raw_id": drive_id,
            "library": "google-drive",
            "title": title,
            "file": {"id": drive_id, "name": title, "path": ["Familiens videoer"], "mime_type": "video/mp4"},
            "bytes": 12,
            "duration_s": 170.0,
            "digest": {"md5": "0f343b0931126a20f133d67c2b018a3b"},
            "extra": {"drive_created": "2019-03-02T10:00:00Z", "drive_modified": "2019-03-02T10:41:12Z"},
        },
    )


def _cache(lb: Logbook, drive_id: str) -> Path:
    folder = lb.root / "state" / "videos"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{drive_id}.mp4"
    path.write_bytes(b"synthetic bytes")
    return path


def _run(*args: str) -> int:
    try:
        cli.main(["videos", "infer", *args])
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    return 0


def _new(lb: Logbook, after: int) -> list[dict[str, Any]]:
    return [line for line in Logbook(lb.root).lines() if int(line["seq"]) > after]


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


@pytest.fixture
def inferred(lb: Logbook, engines: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    video = _video(lb, HOME_01, "Home 01")
    _cache(lb, HOME_01)
    seq = int(lb.meta["seq"])
    assert _run() == 0
    return video, _new(lb, seq)


def _drafts(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [line for line in lines if line["kind"] == "draft"]


def test_one_draft_per_scene_where_the_recordings_join(inferred: Any) -> None:
    video, lines = inferred
    found = _drafts(lines)
    assert [d["payload"]["subject"] for d in found] == [
        [f"{video['id']}#t=0.00,40.00"],
        [f"{video['id']}#t=40.00,90.00"],
        [f"{video['id']}#t=90.00,130.00"],
        [f"{video['id']}#t=130.00,170.00"],
    ]
    for d in found:
        assert d["source"] == "model:video-rules/1" and d["payload"]["unit"] == "event"
        assert drafts.validate(d["payload"]) == []


def test_every_sentence_cites_the_video_or_its_transcript(inferred: Any) -> None:
    video, lines = inferred
    (transcript,) = [line for line in lines if line["kind"] == "transcript"]
    allowed = {str(video["id"]), str(transcript["id"])}
    for d in _drafts(lines):
        payload = d["payload"]
        assert payload["read_count"] == 2
        details = payload["extra"]["segments"]
        assert len(details) == len(payload["segments"])
        for segment, detail in zip(payload["segments"], details, strict=True):
            assert set(segment["evidence"]) <= allowed and segment["evidence"], segment
            if detail["part"] in ("where", "when", "season"):
                assert detail.get("frames") or detail.get("speech"), (segment, detail)
            if str(transcript["id"]) in segment["evidence"] and detail["part"] != "proposed":
                assert detail.get("speech") or detail["part"] == "nothing"


def test_the_sign_proposes_its_place_and_no_coordinate(inferred: Any) -> None:
    _video_line, lines = inferred
    pier = _drafts(lines)[1]["payload"]
    assert pier["extra"]["proposal"] == {
        "place": {"type": "place", "id": "Vollen Brygge", "registry": "logbook", "label": "Vollen Brygge"},
        "when": None,
        "confidence": "high",
    }
    texts = [s["text"] for s in pier["segments"]]
    assert any('reads "VOLLEN BRYGGE"' in t for t in texts)
    assert any("Vollen Brygge igjen" in t for t in texts)  # said at 0:50, cited by its range
    for d in _drafts(lines):
        assert not {"lat", "lon", "latitude", "longitude", "coordinates"} & _keys(d["payload"])
        text = json.dumps(d["payload"])
        assert str(VOLLEN["lat"]) not in text and str(VOLLEN["lon"]) not in text


def test_the_stamp_dates_its_scene_to_the_day_and_nothing_else_is_dated(inferred: Any) -> None:
    _video_line, lines = inferred
    proposals = [d["payload"]["extra"]["proposal"] for d in _drafts(lines)]
    assert proposals[2] == {
        "place": None,
        "when": {"from": "1994-07-14", "to": "1994-07-14", "precision": "day"},
        "confidence": "high",
    }
    assert [p["when"] for p in proposals if p is not None and p["when"] is not None] == [proposals[2]["when"]]
    for p in proposals:
        if p is not None and p["when"] is not None:
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", p["when"]["from"])  # a day at most: never a time


def test_a_scene_with_nothing_to_go_on_says_so_and_guesses_nothing(inferred: Any) -> None:
    _video_line, lines = inferred
    birthday, _pier, _garden, snow = _drafts(lines)
    for d in (birthday, snow):
        assert d["payload"]["extra"]["proposal"] is None
        assert any(s["text"] == infer.NOTHING for s in d["payload"]["segments"])
    assert any("show winter" in s["text"] for s in snow["payload"]["segments"])  # said, and dates nothing


def test_one_transcript_for_the_file_with_its_times(inferred: Any, lb: Logbook) -> None:
    video, lines = inferred
    (transcript,) = [line for line in lines if line["kind"] == "transcript"]
    payload = transcript["payload"]
    assert (transcript["at"], transcript["end"], transcript["tier"]) == (IMPORTED, None, 2)
    assert payload["content"]["media_type"] == "text/vtt"
    assert payload["provenance"] == {
        "source": video["id"],
        "engine": "fake-whisper",
        "model": "synthetic-small",
    }
    text = (lb.root / "attachments" / payload["content"]["sha256"]).read_text(encoding="utf-8")
    assert "00:00:05.000 --> 00:00:08.000\nGratulerer med dagen" in text
    assert "00:00:50.000 --> 00:00:53.000\nNå er vi på Vollen Brygge igjen" in text


def test_every_line_is_tier_2_and_the_video_line_is_unchanged(inferred: Any, lb: Logbook) -> None:
    video, lines = inferred
    assert {line["tier"] for line in lines} == {2}
    assert len(lines) == 5  # one transcript, four drafts
    (again,) = [line for line in Logbook(lb.root).lines() if line["id"] == video["id"]]
    assert again == video


def test_the_file_is_deleted_from_the_cache_once_inferred(inferred: Any, lb: Logbook) -> None:
    assert not (lb.root / "state" / "videos" / f"{HOME_01}.mp4").exists()
    assert not list((lb.root / "state" / "videos").glob(".infer-*")), "the scratch of the run is gone"


def test_a_file_inferred_under_the_same_models_and_settings_is_not_inferred_again(
    inferred: Any, lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _cache(lb, HOME_01)
    seq = int(Logbook(lb.root).meta["seq"])
    capsys.readouterr()
    assert _run() == 0
    assert int(Logbook(lb.root).meta["seq"]) == seq
    assert "already inferred" in capsys.readouterr().out
    assert not path.exists()


def test_keep_leaves_the_file_in_the_cache(lb: Logbook, engines: Any) -> None:
    _video(lb, HOME_01, "Home 01")
    path = _cache(lb, HOME_01)
    assert _run("--keep") == 0
    assert path.exists()


def test_the_prompt_never_asks_for_a_name_or_a_place(inferred: Any, engines: Any) -> None:
    _media, _speech, vision = engines
    assert vision.prompts and set(vision.prompts) == {infer.PROMPT}
    assert "Never name or identify a person" in infer.PROMPT
    assert "Never guess where" in infer.PROMPT


def test_a_boats_name_on_its_hull_proposes_the_asset_and_an_unknown_sign_proposes_nothing(
    lb: Logbook, engines: Any
) -> None:
    _video(lb, TAPE_02, "02")
    _cache(lb, TAPE_02)
    seq = int(lb.meta["seq"])
    assert _run() == 0
    boat, kitchen = _drafts(_new(lb, seq))
    assert boat["payload"]["extra"]["proposal"]["place"] == {
        "type": "asset",
        "id": "solvind",
        "registry": "logbook",
        "label": "Solvind",
    }
    assert kitchen["payload"]["extra"]["proposal"] is None
    assert any(
        "FJORDKIOSK" in s["text"] and "names none" in s["text"] for s in kitchen["payload"]["segments"]
    )


def test_limit_infers_at_most_n_files(lb: Logbook, engines: Any) -> None:
    _video(lb, HOME_01, "Home 01")
    _video(lb, TAPE_02, "02")
    first = _cache(lb, HOME_01)
    second = _cache(lb, TAPE_02)
    assert _run("--limit", "1") == 0
    assert (first.exists(), second.exists()) == (True, False)  # the folder's order: "02" before "Home 01"


def test_with_nothing_in_the_cache_it_says_so_and_looks_for_no_engine(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], no_network: list[str]
) -> None:
    monkeypatch.setattr(infer, "detect", lambda *_a: pytest.fail("no engine is needed"))
    _video(lb, HOME_01, "Home 01")
    assert _run() == 0
    assert "nothing to infer" in capsys.readouterr().out


def test_a_dry_run_lists_and_writes_nothing(
    lb: Logbook, engines: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    _video(lb, HOME_01, "Home 01")
    path = _cache(lb, HOME_01)
    seq = int(lb.meta["seq"])
    assert _run("--dry-run") == 0
    assert int(Logbook(lb.root).meta["seq"]) == seq and path.exists()
    assert "1 file in the cache would be inferred" in capsys.readouterr().out


def test_a_model_not_on_this_machine_names_the_one_command_that_fetches_it(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], no_network: list[str]
) -> None:
    found = (FakeMedia({HOME_01: TAPE}), FakeSpeech(ready=False), FakeVision())
    monkeypatch.setattr(infer, "detect", lambda *_a: found)
    _video(lb, HOME_01, "Home 01")
    _cache(lb, HOME_01)
    assert _run() == 2
    assert "videos fetch --models" in capsys.readouterr().err


def test_no_socket_is_opened_during_inference(lb: Logbook, engines: Any, no_network: list[str]) -> None:
    _video(lb, HOME_01, "Home 01")
    _cache(lb, HOME_01)
    assert _run() == 0
    assert no_network == []


# -- the rules, alone ------------------------------------------------------------------------------


def _frame(offset: float, **kw: Any) -> infer.Frame:
    base = {
        "description": "A room.",
        "setting": None,
        "season": None,
        "signs": (),
        "stamp": None,
        "things": (),
    }
    base.update(kw)
    return infer.Frame(offset, **base)


PLACES = [
    infer.places.Place("Vollen Brygge", 59.8, 10.46, 150.0),
    infer.places.Place("Hytta", 61.0, 9.0, 150.0),
    infer.places.Place("Hjem", 59.91, 10.75, 150.0, "home"),
]


def test_two_places_named_as_often_as_each_other_propose_neither() -> None:
    frames = [_frame(1.0, signs=("VOLLEN BRYGGE",)), _frame(2.0, signs=("HYTTA",))]
    found = infer.propose(frames, [], PLACES, [], TODAY)
    assert found.where is None
    assert any("none is proposed" in s.text for s in found.segments)


def test_a_place_heard_in_one_word_is_weak_and_a_short_name_is_never_matched_in_speech() -> None:
    said = [infer.Speech(3.0, 5.0, "vi drar til Hytta i morgen"), infer.Speech(6.0, 7.0, "nå går vi hjem")]
    found = infer.propose([], said, PLACES, [], TODAY)
    assert found.where is not None and found.where.id == "Hytta" and found.confidence == "low"
    assert not any("Hjem" in s.text and s.part == "where" for s in found.segments)


def test_a_year_said_aloud_is_a_year_narrowed_by_the_frames_season_and_low() -> None:
    frames = [_frame(1.0, season="summer"), _frame(4.0, season="summer")]
    found = infer.propose(frames, [infer.Speech(2.0, 4.0, "dette var sommeren 1994")], [], [], TODAY)
    assert found.when == infer.When(date(1994, 6, 1), date(1994, 8, 31), "season")
    assert found.confidence == "low"


def test_stamps_that_disagree_are_their_range() -> None:
    frames = [_frame(1.0, stamp="JUL 14 1994"), _frame(9.0, stamp="JUL 16 1994")]
    found = infer.propose(frames, [], [], [], TODAY)
    assert found.when == infer.When(date(1994, 7, 14), date(1994, 7, 16), "range")
    assert found.confidence == "medium"


def test_a_stamp_the_season_contradicts_is_less_sure() -> None:
    frames = [_frame(1.0, stamp="JUL 14 1994", season="winter")]
    found = infer.propose(frames, [], [], [], TODAY)
    assert found.when is not None and found.confidence == "medium"
    assert any("does not fit" in s.text for s in found.segments)


def test_a_frame_answer_that_is_not_json_is_no_frame() -> None:
    assert infer.parse_frame("I see a boat.", 1.0) is None
    frame = infer.parse_frame(
        '{"description": "A boat.", "season": "fall", "signs": "SOLVIND", "stamp": null}', 2.0
    )
    assert frame is not None and frame.season == "autumn" and frame.signs == ("SOLVIND",)


# -- on a tape ffmpeg generates ---------------------------------------------------------------------------


class OffsetVision(FakeVision):
    """Reads no pixel: says what the generated tape shows at the frame's offset (its file name)."""

    def describe(self, image: Path, prompt: str) -> str:
        offset = float(image.stem.rsplit("-", 1)[1])
        signs, stamp = ([], None)
        if 6.0 <= offset < 12.0:
            signs = ["VOLLEN BRYGGE"]
        if 12.0 <= offset < 18.0:
            stamp = "JUL 14 1994"
        return json.dumps(
            {
                "description": "A test pattern.",
                "setting": "unknown",
                "season": "unknown",
                "signs": signs,
                "stamp": stamp,
            }
        )


class SilentSpeech(FakeSpeech):
    def load(self, path: Path) -> tuple[list[float], int]:
        assert path.read_bytes()[:4] == b"RIFF"  # ffmpeg cut the scene's sound out as WAV
        return [], 16_000


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is not installed")
def test_a_generated_tape_is_inferred_scene_by_scene(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: list[str]
) -> None:
    video = _video(lb, HOME_01, "Home 01")
    tape = make_tape(lb.root / "state" / "videos" / "gen", f"{HOME_01}.mp4")
    shutil.move(str(tape), str(lb.root / "state" / "videos" / f"{HOME_01}.mp4"))
    shutil.rmtree(lb.root / "state" / "videos" / "gen")
    found = (media.detect(), SilentSpeech(), OffsetVision())
    monkeypatch.setattr(infer, "detect", lambda *_a: found)
    seq = int(lb.meta["seq"])
    assert _run() == 0
    lines = _new(lb, seq)
    proposals = [d["payload"]["extra"]["proposal"] for d in _drafts(lines)]
    assert len(proposals) == 4
    assert proposals[1] is not None and proposals[1]["place"]["id"] == "Vollen Brygge"
    assert proposals[2] is not None and proposals[2]["when"] == {
        "from": "1994-07-14",
        "to": "1994-07-14",
        "precision": "day",
    }
    assert proposals[0] is None and proposals[3] is None
    assert all(str(video["id"]) in d["payload"]["subject"][0] for d in _drafts(lines))
    assert no_network == []
