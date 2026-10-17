"""The scenes of a digitised tape (`logbook.labs.scenes.find_scenes`): one continuous recording each,
found from the picture's cuts and the soundtrack's breaks, with cuts closer than a few seconds merged.
First on synthetic signals, so every rule is held without a decoder; then the parsers of what ffmpeg
prints, on captured output; then, where ffmpeg is installed, on tiny videos generated here, each
stitched from four short synthetic recordings with their own picture and soundtrack, one carrying a
synthetic sign and one a burned-in date stamp. Nothing here is real footage, and nothing is committed
as a binary."""

from __future__ import annotations

import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

from logbook.contrib import media
from logbook.labs import scenes as infer
from logbook.labs.scenes import Scene, Settings, When

TODAY = date(2026, 10, 14)
W = infer.SETTINGS.window_s


def _levels(*spans: tuple[float, float, float]) -> list[tuple[float, float]]:
    """A soundtrack: (from, to, dB) spans, one level per window, a little wobble inside each so a
    recording is never flat."""
    found = []
    for start, end, db in spans:
        t = start
        k = 0
        while t < end - 1e-9:
            found.append((round(t, 2), db + (0.8 if k % 3 == 0 else -0.5)))
            t += W
            k += 1
    return found


def _edges(scenes: list[Scene]) -> list[float]:
    return [s.start for s in scenes[1:]]


def test_a_file_with_nothing_breaking_it_is_one_scene() -> None:
    scenes = infer.find_scenes(60.0, [(12.0, 0.12), (30.0, 0.08)], _levels((0, 60, -30)))
    assert scenes == [Scene(1, 0.0, 60.0, "start")]


def test_cuts_with_a_soundtrack_break_split_and_a_pan_does_not() -> None:
    cuts = [
        (20.0, 0.15),  # a pan inside the first recording: weak, the sound goes on
        (40.0, 0.72),  # a hard cut: the next recording
        (90.0, 0.18),  # weak, but the sound jumps 10 dB with it: another recording in the same room
        (130.0, 0.41),  # a hard cut, the sound changing with it
    ]
    levels = _levels((0, 40, -30), (40, 90, -18), (90, 130, -28), (130, 170, -40))
    scenes = infer.find_scenes(170.0, cuts, levels)
    assert _edges(scenes) == [40.0, 90.0, 130.0]
    assert [s.opened_by for s in scenes] == ["start", "cut", "cut and sound", "cut"]


def test_a_level_jump_alone_is_not_a_boundary() -> None:
    scenes = infer.find_scenes(80.0, [], _levels((0, 40, -30), (40, 80, -15)))
    assert len(scenes) == 1  # someone came closer to the microphone: the same recording


def test_a_gap_of_silence_is_a_boundary_at_its_middle() -> None:
    levels = _levels((0, 30, -30), (30, 32, -120), (32, 60, -25))
    scenes = infer.find_scenes(60.0, [], levels)
    assert _edges(scenes) == [31.0]
    assert scenes[1].opened_by == "silence"


def test_breaks_closer_than_merge_s_are_one_boundary_the_strongest() -> None:
    levels = _levels((0, 29.0, -30), (29.0, 30.5, -120), (30.5, 60, -22))
    cuts = [(30.5, 0.5), (31.0, 0.35)]  # the gap, then the new recording's first frames
    scenes = infer.find_scenes(60.0, cuts, levels)
    assert len(scenes) == 2
    assert scenes[1].start == 30.5 and scenes[1].opened_by == "cut"


def test_no_boundary_near_the_start_or_the_end_and_every_scene_is_long_enough() -> None:
    cuts = [(1.0, 0.9), (58.5, 0.9), (25.0, 0.9), (26.5, 0.9)]
    scenes = infer.find_scenes(60.0, cuts, _levels((0, 60, -30)))
    assert _edges(scenes) == [25.0]
    assert all(s.length >= infer.SETTINGS.merge_s for s in scenes)


def test_a_break_at_the_start_takes_no_break_just_inside_with_it() -> None:
    cuts = [(2.0, 0.9), (4.5, 0.35)]  # a glitch as the tape starts, then the first recording's cut
    scenes = infer.find_scenes(60.0, cuts, _levels((0, 60, -30)))
    assert _edges(scenes) == [4.5]
    cuts = [(55.5, 0.35), (58.0, 0.9)]  # and at the end
    scenes = infer.find_scenes(60.0, cuts, _levels((0, 60, -30)))
    assert _edges(scenes) == [55.5]


def test_a_file_with_no_soundtrack_is_cut_by_its_picture_alone() -> None:
    scenes = infer.find_scenes(60.0, [(20.0, 0.6), (40.0, 0.2)], [])
    assert _edges(scenes) == [20.0]  # the weak cut has no sound to confirm it


def test_the_settings_are_the_documented_ones() -> None:
    s = infer.SETTINGS
    assert (s.cut, s.soft_cut, s.jump_db, s.quiet_db, s.gap_s, s.merge_s, s.window_s) == (
        0.30,
        0.10,
        6.0,
        -55.0,
        1.0,
        3.0,
        0.25,
    )
    assert Settings().to_json()["frames"] == [0.2, 0.5, 0.8]


def test_frames_are_sampled_at_a_fifth_a_half_and_four_fifths_or_the_middle_of_a_short_scene() -> None:
    assert infer.frame_times(Scene(2, 40.0, 90.0, "cut")) == [50.0, 65.0, 80.0]
    assert infer.frame_times(Scene(3, 90.0, 94.0, "cut")) == [92.0]


# -- what ffmpeg prints ---------------------------------------------------------------------------

CUTS_OUTPUT = (
    "frame:0    pts:51845   pts_time:5.06299\nlavfi.scene_score=0.723525\n"
    "frame:1    pts:103045  pts_time:10.063\nlavfi.scene_score=0.132315\n"
)
LEVELS_OUTPUT = (
    "frame:0    pts:0       pts_time:0\nlavfi.astats.Overall.RMS_level=-36.473937\n"
    "frame:1    pts:4000    pts_time:0.25\nlavfi.astats.Overall.RMS_level=-inf\n"
    "frame:2    pts:8000    pts_time:0.5\nlavfi.astats.Overall.RMS_level=-35.059497\n"
)
PROBE_OUTPUT = (
    '{"programs": [], "streams": [{"codec_type": "video", "width": 720, "height": 576},'
    ' {"codec_type": "audio"}], "format": {"duration": "4012.480000"}}'
)


def test_the_parsers_read_what_ffmpeg_prints() -> None:
    assert media.parse_cuts(CUTS_OUTPUT) == [(5.06299, 0.723525), (10.063, 0.132315)]
    assert media.parse_levels(LEVELS_OUTPUT) == [
        (0.0, -36.473937),
        (0.25, media.SILENT_DB),
        (0.5, -35.059497),
    ]
    assert media.parse_probe(PROBE_OUTPUT) == media.Probe(4012.48, 720, 576, True, True)
    with pytest.raises(media.MediaError):
        media.parse_probe('{"format": {}}')


def test_a_cover_picture_is_not_the_video_stream() -> None:
    """An attached picture (a cover) is a video stream to ffprobe; ffmpeg decodes the recording, so the
    size the cuts pass scales to is the recording's, and a file with only a cover has no picture."""
    cover = '{"codec_type": "video", "width": 320, "height": 240, "disposition": {"attached_pic": 1}}'
    tape = '{"codec_type": "video", "width": 720, "height": 576, "disposition": {"attached_pic": 0}}'
    sound = '{"codec_type": "audio", "disposition": {"attached_pic": 0}}'
    found = media.parse_probe(f'{{"streams": [{cover}, {tape}, {sound}], "format": {{"duration": "60.0"}}}}')
    assert found == media.Probe(60.0, 720, 576, True, True)
    found = media.parse_probe(f'{{"streams": [{cover}, {sound}], "format": {{"duration": "60.0"}}}}')
    assert found == media.Probe(60.0, None, None, False, True)


def test_ffmpeg_is_asked_to_open_nothing_but_files(tmp_path: Path) -> None:
    asked: list[list[str]] = []

    class Done:
        returncode, stdout, stderr = 0, PROBE_OUTPUT, ""

    def run(args: list[str], **_kw: object) -> Done:
        asked.append(args)
        return Done()

    tool = media.Ffmpeg("ffmpeg", "ffprobe", run)
    tool.probe(tmp_path / "a.mp4")
    tool.cuts(tmp_path / "a.mp4", 0.1)  # its own probe first, for the frame size
    Done.stdout = ""
    tool.levels(tmp_path / "a.mp4", 0.25)
    tool.audio(tmp_path / "a.mp4", 1.0, 2.0, tmp_path / "a.wav")
    for args in asked:
        i = args.index("-protocol_whitelist")
        assert args[i + 1] == "file,pipe"
        assert i < args.index("-i") if "-i" in args else True


def test_the_cuts_pass_keeps_one_graph_and_compares_every_frame_at_the_first_ones_size(
    tmp_path: Path,
) -> None:
    asked: list[list[str]] = []

    class Done:
        returncode, stdout, stderr = 0, PROBE_OUTPUT, ""

    def run(args: list[str], **_kw: object) -> Done:
        asked.append(args)
        return Done()

    media.Ffmpeg("ffmpeg", "ffprobe", run).cuts(tmp_path / "a.mp4", 0.1)
    args = asked[-1]
    assert args[0] == "ffmpeg" and args.index("-reinit_filter") < args.index("-i")
    assert args[args.index("-reinit_filter") + 1] == "0"
    assert args.index("-noautorotate") < args.index("-i")  # a phone's rotation changes no difference
    assert args[args.index("-vf") + 1].startswith("scale=720:576,select='gte(scene,0.100)'")


def test_the_key_names_how_the_picture_was_cut(monkeypatch: pytest.MonkeyPatch) -> None:
    """A file cut into scenes by an earlier cuts pass is inferred again (`videos fetch --again`, then
    `videos infer`): one whose recordings change size, pixel format or colour tags at a join may hold
    two recordings in one scene."""
    from types import SimpleNamespace

    speech = SimpleNamespace(name="speech-engine", model="speech-model")
    vision = SimpleNamespace(name="vision-engine", model="vision-model")
    now = infer.key(speech, vision)  # type: ignore[arg-type]
    assert media.CUTS == "one-graph/1"
    monkeypatch.setattr(media, "CUTS", "earlier/0")
    assert infer.key(speech, vision) != now  # type: ignore[arg-type]


def test_without_ffmpeg_it_says_how_to_install_it() -> None:
    with pytest.raises(media.MediaMissing, match="install ffmpeg"):
        media.detect(which=lambda _name: None)


# -- the camera's date stamp ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stamp", "first", "last", "precision"),
    [
        ("JUL 14 1994", "1994-07-14", "1994-07-14", "day"),
        ("JUL. 14, 94", "1994-07-14", "1994-07-14", "day"),
        ("14 JUL 1994", "1994-07-14", "1994-07-14", "day"),
        ("14. JULI 1994  10:42", "1994-07-14", "1994-07-14", "day"),
        ("1994.07.14", "1994-07-14", "1994-07-14", "day"),
        ("14.7.94", "1994-07-14", "1994-07-14", "day"),
        ("7/14/1994", "1994-07-14", "1994-07-14", "day"),
        ("07.08.94", "1994-07-08", "1994-08-07", "range"),  # either way round: the range between
        ("AUG 1997", "1997-08-01", "1997-08-31", "month"),
        ("1989", "1989-01-01", "1989-12-31", "year"),
    ],
)
def test_a_stamp_is_read_to_the_precision_it_shows(stamp: str, first: str, last: str, precision: str) -> None:
    assert infer.stamp_when(stamp, TODAY) == When(
        date.fromisoformat(first), date.fromisoformat(last), precision
    )


@pytest.mark.parametrize("stamp", ["12:00 AM", "31.02.1994", "JUL 14 2031", "MODE 3", "REC", ""])
def test_a_stamp_that_shows_no_real_date_dates_nothing(stamp: str) -> None:
    assert infer.stamp_when(stamp, TODAY) is None


# -- on a generated video, where ffmpeg is installed --------------------------------------------------

FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
JOINS = (6.0, 12.0, 18.0)
RECORDINGS = (  # picture, the text drawn on it, the sound's source and its filter: six seconds each
    ("testsrc2=size=160x120:rate=10", None, "sine=frequency=220:sample_rate=16000", "volume=0.05"),
    ("smptebars=size=160x120:rate=10", "VOLLEN BRYGGE", "sine=frequency=440:sample_rate=16000", "volume=0.6"),
    (
        "color=c=0x3a6020:size=160x120:rate=10",
        "JUL 14 1994",
        "anoisesrc=color=pink:amplitude=0.02:r=16000",
        "anull",
    ),
    ("rgbtestsrc=size=160x120:rate=10", None, "sine=frequency=880:sample_rate=16000", "volume=0.25"),
)
RESHAPED = (  # three recordings whose streams differ at the joins, as clips stitched without re-encoding do
    ("testsrc2=size=160x120:rate=10", None, "sine=frequency=220:sample_rate=16000", "volume=0.05"),
    (
        "smptebars=size=176x144:rate=10",
        None,
        "sine=frequency=440:sample_rate=16000",
        "volume=0.6",
    ),  # its size
    (  # its pixel format
        "rgbtestsrc=size=176x144:rate=10",
        None,
        "sine=frequency=880:sample_rate=16000",
        "volume=0.25",
        "yuv444p",
    ),
)


def make_tape(
    folder: Path, name: str = "tape.mp4", recordings: tuple[tuple[str | None, ...], ...] = RECORDINGS
) -> Path:
    """A tiny synthetic tape: the four recordings, stitched without re-encoding. A sign and a date stamp
    are drawn when this ffmpeg can draw text, and left out when it cannot: the scenes do not depend on
    them. A recording's fifth value, when it has one, is its pixel format (yuv420p otherwise)."""
    folder.mkdir(parents=True, exist_ok=True)
    parts = []
    for n, (picture, text, sound, level, *rest) in enumerate(recordings, 1):
        pixels = rest[0] if rest else "yuv420p"
        part = folder / f"rec{n}.mp4"
        for overlay in ([text] if text else []) + [None]:
            draw = f"drawtext=text='{overlay}':fontsize=16:fontcolor=white:x=8:y=8" if overlay else "null"
            args = [
                "ffmpeg", *media.QUIET, "-y",
                "-f", "lavfi", "-i", f"{picture}:duration=6",
                "-f", "lavfi", "-i", f"{sound}:duration=6",
                "-filter_complex", f"[0:v]{draw}[v];[1:a]{level}[a]",
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", str(pixels),
                "-c:a", "aac", "-shortest", str(part),
            ]  # fmt: skip
            if subprocess.run(args, capture_output=True, check=False).returncode == 0:
                break
        else:
            pytest.skip("this ffmpeg cannot make the synthetic recordings")
        parts.append(part)
    listing = folder / "list.txt"
    listing.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    tape = folder / name
    done = subprocess.run(
        [
            "ffmpeg",
            *media.QUIET,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            "-c",
            "copy",
            str(tape),
        ],
        capture_output=True,
        check=False,
        cwd=folder,
    )
    if done.returncode != 0:
        pytest.skip("this ffmpeg cannot stitch the synthetic recordings")
    for p in [*parts, listing]:
        p.unlink()
    return tape


def read_out(scenes: object, cuts: list[tuple[float, float]], levels: list[tuple[float, float]]) -> str:
    """What this ffmpeg read of the generated tape, for a failure's message: its version, every scene
    score it printed and the soundtrack's levels a second either side of each join."""
    version = subprocess.run(["ffmpeg", "-version"], capture_output=True, encoding="utf-8", check=False)
    near = {join: [(t, round(db, 1)) for t, db in levels if abs(t - join) <= 1.0] for join in JOINS}
    first = (version.stdout or "").splitlines()[:1]
    return f"{first} scenes={scenes} cuts={cuts} levels near the joins={near}"


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is not installed")
def test_on_a_generated_tape_the_scenes_are_found_where_the_recordings_join(tmp_path: Path) -> None:
    tape = make_tape(tmp_path / "gen")
    tool = media.detect()
    probe = tool.probe(tape)
    assert probe.video and probe.audio and 23.5 < probe.duration_s < 24.6
    cuts = tool.cuts(tape, infer.SETTINGS.soft_cut)
    levels = tool.levels(tape, infer.SETTINGS.window_s)
    scenes = infer.find_scenes(probe.duration_s, cuts, levels)
    assert len(scenes) == 4, read_out(scenes, cuts, levels)
    for found, join in zip(_edges(scenes), JOINS, strict=True):
        assert abs(found - join) <= 0.6, (found, join)
    frame = tmp_path / "frame.jpg"
    tool.frame(tape, 9.0, frame)
    assert frame.read_bytes()[:2] == b"\xff\xd8"  # a JPEG
    sound = tmp_path / "sound.wav"
    tool.audio(tape, 6.0, 12.0, sound)
    assert sound.read_bytes()[:4] == b"RIFF" and 180_000 < sound.stat().st_size < 200_000  # 6 s, 16 kHz


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is not installed")
def test_a_join_where_the_streams_size_or_pixel_format_changes_is_found(tmp_path: Path) -> None:
    """ffmpeg builds its filter graph again when a frame's size or pixel format changes (and, from 7.1,
    its colour range or space), and a graph built again has no frame before to compare with: the first
    frame of the next recording would score nothing, and the join between two clips stitched without
    re-encoding would be missed. The cuts pass keeps its one graph and brings every frame to the first
    one's size and format, so each join is a cut, on every ffmpeg."""
    tape = make_tape(tmp_path / "gen", recordings=RESHAPED)
    tool = media.detect()
    probe = tool.probe(tape)
    assert probe.video and 17.5 < probe.duration_s < 18.6
    cuts = tool.cuts(tape, infer.SETTINGS.soft_cut)
    levels = tool.levels(tape, infer.SETTINGS.window_s)
    scenes = infer.find_scenes(probe.duration_s, cuts, levels)
    assert len(scenes) == 3, read_out(scenes, cuts, levels)
    for found, join in zip(_edges(scenes), JOINS[:2], strict=True):
        assert abs(found - join) <= 0.6, (found, join)
    assert all(scene.opened_by.startswith("cut") for scene in scenes[1:]), scenes


# -- the independent check of scenes and dates ------------------------------------------------------


def test_a_chain_of_weak_breaks_never_swallows_a_join() -> None:
    cuts = [(100.0, 0.9), (120.0, 0.9)] + [(float(t), 0.15) for t in range(102, 120, 2)]
    spans = [(0.0, 100.0, -30.0)] + [
        (float(t), float(t + 2), -20.0 if (t // 2) % 2 == 0 else -30.0) for t in range(100, 120, 2)
    ]
    scenes = infer.find_scenes(160.0, cuts, _levels(*spans, (120.0, 160.0, -40.0)))
    assert 100.0 in _edges(scenes) and 120.0 in _edges(scenes), _edges(scenes)


def test_a_glitch_of_a_few_frames_between_two_recordings_in_the_same_room_is_one_boundary() -> None:
    levels = _levels((0, 120, -30))
    assert _edges(infer.find_scenes(120.0, [(60.0, 0.95)], levels)) == [60.0]
    assert _edges(infer.find_scenes(120.0, [(60.0, 0.95), (60.08, 0.7), (60.12, 0.9)], levels)) == [60.0]


@pytest.mark.parametrize("stamp", ["JUL 14 10:42", "14 JUL 10:42", "JUL 14 10.42", "AUTO 14 1994"])
def test_a_stamp_with_a_time_and_no_year_dates_nothing_more_than_it_shows(stamp: str) -> None:
    found = infer.stamp_when(stamp, TODAY)
    assert found is None or found.precision == "year"  # AUTO is no month: at most the year it shows


def test_a_day_and_a_year_with_a_comma_and_no_space_is_the_day() -> None:
    assert infer.stamp_when("JUL 14,1994", TODAY) == When(date(1994, 7, 14), date(1994, 7, 14), "day")


@pytest.mark.parametrize("stamp", ["JAN 1 2000 12:00 AM", "1.1.2000 0:00", "01/01/2000 00:00", "JAN 1 2000"])
def test_a_camcorder_clock_never_set_is_not_a_sure_day(stamp: str) -> None:
    found = infer.propose([infer.Frame(1.0, "A garden.", None, None, (), stamp, ())], [], [], [], TODAY)
    assert found.confidence != "high"
    if ":" in stamp:
        assert found.when is None
    else:
        assert found.confidence == "low" and any("never set" in s.text for s in found.segments)
        assert (found.to_json() or {})["when_confidence"] == "low"


def test_the_proposal_keeps_the_dates_own_confidence_beside_the_weaker_of_the_two() -> None:
    frames = [infer.Frame(1.0, "A garden.", None, None, (), "JUL 14 1994", ())]
    said = [infer.Speech(2.0, 4.0, "Her i Vollen er det fint")]  # one word said: a `low` place
    known = [infer.places.Place("Vollen", 59.8, 10.48, 300.0)]
    found = infer.propose(frames, said, known, [], TODAY).to_json()
    assert found is not None
    assert (found["confidence"], found["when_confidence"]) == ("low", "high")
    assert infer.propose(frames, [], [], [], TODAY).to_json() == {
        "place": None,
        "when": {"from": "1994-07-14", "to": "1994-07-14", "precision": "day"},
        "confidence": "high",
        "when_confidence": "high",
    }


def test_a_year_a_shop_has_stood_since_dates_no_scene() -> None:
    frames = [infer.Frame(1.0, "A shop front.", None, None, ("SINCE 1952", "ETABLERT 1965"), None, ())]
    assert infer.propose(frames, [], [], [], TODAY).when is None


def test_frame_is_asked_to_open_nothing_but_files(tmp_path: Path) -> None:
    asked: list[list[str]] = []

    class Done:
        returncode, stdout, stderr = 0, "", ""

    def run(args: list[str], **_kw: object) -> Done:
        asked.append(args)
        (tmp_path / "f.jpg").write_bytes(b"\xff\xd8")
        return Done()

    media.Ffmpeg("ffmpeg", "ffprobe", run).frame(tmp_path / "a.mp4", 9.0, tmp_path / "f.jpg")
    (args,) = asked
    i = args.index("-protocol_whitelist")
    assert args[i + 1] == "file,pipe" and i < args.index("-ss") < args.index("-i")
