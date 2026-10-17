"""What a video file holds, asked of ffmpeg on this machine: its length, where its picture changes, how
loud its soundtrack is, a frame, a stretch of its sound. No model and no network: ffmpeg is told to open
nothing but files (`-protocol_whitelist file,pipe`), so a path that is a URL is refused by ffmpeg itself,
and the commands are given a path in the cache and nothing else.

ffmpeg and ffprobe are programs, not a Python dependency: `detect` finds them on the PATH (`brew install
ffmpeg`, `apt install ffmpeg`, `winget install ffmpeg`) and says so in one sentence when they are not
there. The two signals `videos infer` cuts scenes by (`logbook.labs.scenes`) are read in two passes:

- **the picture**: ffmpeg's scene score of every frame at or above a floor (`select=gte(scene,F)`,
  printed with `metadata=print`), a number from 0 (the same picture) to 1 (another picture entirely).
  A score compares a frame with the one before, so the pass keeps one filter graph for the whole file
  (`-reinit_filter 0`) and brings every frame to the first one's size and pixel format (`scale=W:H`,
  which passes a file whose frames all match it through untouched), as stored (`-noautorotate`: a
  phone's rotation changes no difference between two frames). Without that, ffmpeg builds the
  graph again when a frame's size or pixel format changes, and from 7.1 its colour range or space; the
  graph built again has no frame before, and the join between two clips stitched without re-encoding,
  where exactly such a change falls, would score nothing;
- **the soundtrack**: its RMS level in dB over windows of a fixed length, after resampling to 16 kHz
  (`asetnsamples` then `astats`, `ametadata=print`); digital silence reads as `-inf`, kept as `SILENT_DB`.

Both are parsed from what ffmpeg prints (`parse_cuts`, `parse_levels`), which the tests hold to
captured output so the parsing is checked without the program."""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

FFMPEG, FFPROBE = "ffmpeg", "ffprobe"
QUIET = ("-nostdin", "-hide_banner", "-loglevel", "error")
LOCAL = ("-protocol_whitelist", "file,pipe")  # an input option: nothing but a file is opened
CUTS = "one-graph/1"  # how the picture pass reads a file; `videos infer`'s key carries it
ONE_GRAPH = ("-reinit_filter", "0")  # an input option: the cuts pass never builds its graph again
AS_STORED = ("-noautorotate",)  # an input option: frames as stored, the size ffprobe reads
RATE = 16_000  # the soundtrack is measured, and cut for the speech model, at this rate
SILENT_DB = -120.0  # a window of digital silence (`-inf`)
INSTALL = (
    "install ffmpeg (brew install ffmpeg, apt install ffmpeg, winget install ffmpeg) and put it on the PATH"
)
FRAME = re.compile(r"pts_time:(?P<t>-?\d+(?:\.\d+)?)")
SCORE = re.compile(r"lavfi\.scene_score=(?P<v>-?\d+(?:\.\d+)?(?:e-?\d+)?)")
LEVEL = re.compile(r"lavfi\.astats\.Overall\.RMS_level=(?P<v>-?inf|-?\d+(?:\.\d+)?)")


class MediaMissing(Exception):
    """ffmpeg or ffprobe is not on this machine."""


class MediaError(Exception):
    """ffmpeg could not read the file, or gave no answer that reads."""


@dataclass(frozen=True)
class Probe:
    duration_s: float
    width: int | None
    height: int | None
    video: bool
    audio: bool


class Media(Protocol):
    """A decoder on this machine. `cuts` is (seconds, score) for every frame whose picture changed by
    `floor` or more; `levels` (seconds, dB) per window of `window_s`; `frame` writes one JPEG of the
    picture at `at_s`; `audio` writes `start_s` to `end_s` of the sound as 16 kHz mono WAV."""

    name: str

    def probe(self, path: Path) -> Probe: ...
    def cuts(self, path: Path, floor: float) -> list[tuple[float, float]]: ...
    def levels(self, path: Path, window_s: float) -> list[tuple[float, float]]: ...
    def frame(self, path: Path, at_s: float, out: Path) -> None: ...
    def audio(self, path: Path, start_s: float, end_s: float, out: Path) -> None: ...


Runner = Callable[..., Any]  # subprocess.run's shape


def detect(which: Callable[[str], str | None] = shutil.which, run: Runner = subprocess.run) -> Ffmpeg:
    """ffmpeg and ffprobe from the PATH; MediaMissing saying how to install them."""
    ffmpeg, ffprobe = which(FFMPEG), which(FFPROBE)
    if ffmpeg is None or ffprobe is None:
        raise MediaMissing(f"ffmpeg is not on this machine: {INSTALL}")
    return Ffmpeg(ffmpeg, ffprobe, run)


class Ffmpeg:
    """ffmpeg and ffprobe, run as programs with a path in the cache; nothing else is opened."""

    name = "ffmpeg"

    def __init__(self, ffmpeg: str, ffprobe: str, run: Runner = subprocess.run) -> None:
        self.ffmpeg, self.ffprobe, self._run = ffmpeg, ffprobe, run

    def _call(self, args: Sequence[str]) -> str:
        done = self._run(list(args), capture_output=True, encoding="utf-8", errors="replace", check=False)
        if done.returncode != 0:
            last = (done.stderr or "").strip().splitlines()
            raise MediaError(last[-1] if last else f"{Path(args[0]).name} exited {done.returncode}")
        return str(done.stdout or "")

    def probe(self, path: Path) -> Probe:
        text = self._call(
            [
                self.ffprobe,
                "-v",
                "error",
                *LOCAL,
                "-show_entries",
                "format=duration:stream=codec_type,width,height:stream_disposition=attached_pic",
                "-of",
                "json",
                str(path),
            ]
        )
        return parse_probe(text)

    def cuts(self, path: Path, floor: float) -> list[tuple[float, float]]:
        found = self.probe(path)
        text = self._call(
            [
                self.ffmpeg,
                *QUIET,
                *LOCAL,
                *ONE_GRAPH,
                *AS_STORED,
                "-i",
                str(path),
                "-an",
                "-sn",
                "-dn",
                "-vf",
                cut_graph(floor, found.width, found.height),
                "-f",
                "null",
                "-",
            ]
        )
        return parse_cuts(text)

    def levels(self, path: Path, window_s: float) -> list[tuple[float, float]]:
        samples = max(1, round(RATE * window_s))
        graph = (
            f"aresample={RATE},asetnsamples=n={samples}:p=0,astats=metadata=1:reset=1,"
            "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-"
        )
        text = self._call(
            [
                self.ffmpeg,
                *QUIET,
                *LOCAL,
                "-i",
                str(path),
                "-vn",
                "-sn",
                "-dn",
                "-af",
                graph,
                "-f",
                "null",
                "-",
            ]
        )
        return parse_levels(text)

    def frame(self, path: Path, at_s: float, out: Path) -> None:
        self._call(
            [
                self.ffmpeg,
                *QUIET,
                *LOCAL,
                "-ss",
                f"{at_s:.3f}",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-q:v",
                "3",
                "-y",
                str(out),
            ]
        )
        if not out.is_file():
            raise MediaError(f"no frame at {at_s:.2f} s")

    def audio(self, path: Path, start_s: float, end_s: float, out: Path) -> None:
        self._call(
            [
                self.ffmpeg,
                *QUIET,
                *LOCAL,
                "-ss",
                f"{start_s:.3f}",
                "-t",
                f"{max(0.0, end_s - start_s):.3f}",
                "-i",
                str(path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(RATE),
                "-c:a",
                "pcm_s16le",
                "-y",
                str(out),
            ]
        )


def cut_graph(floor: float, width: int | None, height: int | None) -> str:
    """The cuts pass's filters: every frame at the first one's size and pixel format (`width`, `height`,
    the video stream's as ffprobe reads it), then its scene score, printed when it is `floor` or more."""
    same = f"scale={width}:{height}," if width and height else ""
    return f"{same}select='gte(scene,{floor:.3f})',metadata=print:key=lavfi.scene_score:file=-"


def parse_probe(text: str) -> Probe:
    """ffprobe's JSON: the length, the picture's size, and which streams there are. An attached
    picture (a cover) is no video: ffmpeg decodes the recording, not the cover."""
    try:
        data = json.loads(text)
    except ValueError:
        raise MediaError("ffprobe's answer is not JSON") from None
    streams = [s for s in data.get("streams") or [] if isinstance(s, dict)]
    video = next((s for s in streams if s.get("codec_type") == "video" and not _cover(s)), None)
    try:
        duration = float(str((data.get("format") or {}).get("duration")))
    except (TypeError, ValueError):
        raise MediaError("ffprobe gave no length for the file") from None
    width = video.get("width") if video is not None else None
    height = video.get("height") if video is not None else None
    return Probe(
        duration,
        width if isinstance(width, int) else None,
        height if isinstance(height, int) else None,
        video is not None,
        any(s.get("codec_type") == "audio" for s in streams),
    )


def _cover(stream: dict[str, Any]) -> bool:
    disposition = stream.get("disposition")
    return isinstance(disposition, dict) and bool(disposition.get("attached_pic"))


def parse_cuts(text: str) -> list[tuple[float, float]]:
    """(seconds, scene score) per frame `metadata=print` printed, in time order."""
    found: list[tuple[float, float]] = []
    at: float | None = None
    for line in text.splitlines():
        frame = FRAME.search(line)
        if frame is not None:
            at = float(frame["t"])
            continue
        score = SCORE.search(line)
        if score is not None and at is not None:
            value = float(score["v"])
            if math.isfinite(value):
                found.append((at, value))
            at = None
    return sorted(found)


def parse_levels(text: str) -> list[tuple[float, float]]:
    """(seconds, dB) per window `ametadata=print` printed, in time order; silence as `SILENT_DB`."""
    found: list[tuple[float, float]] = []
    at: float | None = None
    for line in text.splitlines():
        frame = FRAME.search(line)
        if frame is not None:
            at = float(frame["t"])
            continue
        level = LEVEL.search(line)
        if level is not None and at is not None:
            value = level["v"]
            db = SILENT_DB if value.endswith("inf") else max(SILENT_DB, float(value))
            found.append((at, db))
            at = None
    return sorted(found)
