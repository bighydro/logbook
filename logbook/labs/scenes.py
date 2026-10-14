"""`logbook videos infer`: the family's videos read on this machine, one scene at a time, and one draft
per scene proposing where and when it was filmed (RFC 0039). A proposal, never a fact: the owner
confirms it with `review videos`, and only that writes where or when.

It works on the files `videos fetch` left in the cache (`logbook.contrib.videos`) and nothing else, and
it never opens a socket: ffmpeg is told to open nothing but files (`logbook.contrib.media`), the speech
and vision models run here with the Hugging Face hub told it is offline (`transcribe.offline`), and the
proposals are made by rules in this module, not by a model behind an endpoint. A model that is not on
this machine stops the run with the one command that fetches it, `videos fetch --models`. Once a file
is inferred it is deleted from the cache, unless `--keep`; a file already inferred under the same
models, prompt and scene settings (`key`) is skipped, so an interrupted run carries on.

**A scene** is one continuous recording. A digitised tape or DVD holds many, one after another, from
different years and places, so where and when are proposed per scene, never per file. The scenes are
found from two signals ffmpeg reads (`media`): the picture's scene score of each frame (0, the same
picture; 1, another picture entirely) and the soundtrack's level in dB over windows of `window_s`
(0.25 s). With the thresholds of `Settings`, the defaults written here, a scene begins at:

- **a cut**: a frame scoring `cut` (0.30) or more;
- **a weak cut with a break in the soundtrack**: a frame scoring `soft_cut` (0.10) or more, when within
  `pair_s` (0.5 s) of it the soundtrack breaks: its mean level over the `side_s` (1 s) after differs
  from the second before by `jump_db` (6 dB) or more, or a window is silent (`quiet_db`, -55 dB or
  less). Two recordings in the same room look alike; their sound seldom does;
- **a gap in the soundtrack**: `gap_s` (1 s) or more of silence (`quiet_db`), the blank between two
  recordings on a tape, at its middle, whatever the picture does.

A camera that pans, a child that runs past the lens, someone who stops talking: none of them is a
boundary on its own. Breaks within `merge_s` (3 s) of the first of a run are one, the strongest kept,
so a glitch of a few frames between two recordings is one boundary, and no run of weak breaks can
swallow a strong one beyond it; no boundary is kept within `merge_s` of the file's start or end. Every
scene is therefore `merge_s` long or longer. The rules lean one way on purpose: a sudden change of
light inside a recording (a camera's flash, a lamp switched on) can split it in two, which costs one
more draft to answer, while a join they missed would mix two recordings' evidence in one proposal. A
fade or a dissolve between two recordings changes the picture too slowly to score a cut and is found
only when the soundtrack breaks with it. These numbers are hypotheses,
as `policy/stays.json`'s are, and the key carries them: other settings infer the file again.

**What is read of a scene.** Its sound, cut out at 16 kHz and heard by the transcribe extra through its
public function (`transcribe.hear`), every segment shifted by the scene's start, so the speech of a
scene is a time range of the file. One `transcript/v1` line per file holds all of it as WebVTT, each cue
with its times (tier 2; `at` the video line's, `end` null: when it was said is not known; source
`video-transcription`, which the synthesis of calls leaves out: a home video's soundtrack is no call). And
`FRAMES` frames of its picture (`frame_times`: at a fifth, a half and four fifths of the scene; one, at
its middle, for a scene under `short_s`, 6 s), each shown to the describe extra's vision model with this
module's own prompt (`PROMPT`): what is visible, the setting, the season, the text on signs, boats and
banners as written, and a date or time the camera burned into the picture, never a person's name and
never a guess at the place. Each frame is deleted as soon as it is read; the descriptions are kept in
the scene's draft (`extra.frames`), the pixels nowhere.

**The rules** (`propose`, `RULES`): a place is proposed only from the owner's own registries: a name of
`places.json`, or an asset's name or registration from `assets.json`, read whole (case and punctuation
aside) on a sign of a frame (confidence `high`), in what was said (`medium` for a name of two words or
more, `low` for one word; a name under five letters is never matched in speech), or in a frame's
description (`low`). Its coordinates are the registry's, never the line's: a draft carries the place's
name, never a latitude. A sign that names nothing of the registries is said, and proposes nothing. Two
places with the same weight propose neither. A date is proposed from the camera's date stamp, to the
precision it shows (a day, a month, a year; a stamp whose day and month could be either way round is
the span from one reading to the other), `high`, or `medium` when the stamps disagree (their range); a
stamp of 1 January at midnight is a camera's clock never set and dates nothing, and 1 January without a
time is `low` and said so; a stamp's time is never read as a year. Else from a year written in a frame
or said aloud (`low`), but never one a shop or a banner has stood since ("SINCE 1952", "etablert
1965"), narrowed to a season when the frames agree on spring, summer or autumn; a season alone dates
nothing. A scene with nothing to go on gets a draft that
says so and proposes nothing. Every sentence cites its evidence: the video line for what the frames
show, the transcript line for what was said, and under `extra.segments` which frames and which time
range.

**The draft** (`draft/v1`, RFC 0036): unit `event`, subject the scene (`<video line id>#t=<start>,<end>`),
source `model:video-rules/1` (the rules wrote the sentences; the two models are named under
`extra.models`), tier 2, the highest of what it read (the video line and the transcript), `read_head`
the head after the transcript was written. Like a dream's draft it is a proposal; unlike it, nothing
crossed to make it (no line left this machine), so no crossing entry governs it and a crossing carries
it by its tier like any line."""

from __future__ import annotations

import bisect
import calendar
import hashlib
import itertools
import json
import re
import shutil
import time
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..contrib import media as media_module
from ..contrib import videos
from ..contrib.adapters import transcript
from ..core import assets as asset_registry
from ..core import attachments, drafts, places
from ..core.chain import Line
from ..core.store import Logbook, now_utc, retractions
from . import describe, transcribe

RULES = "video-rules/1"
offline = transcribe.offline  # the hub told it is offline, around the engines' import and every read
SOURCE = videos.DRAFT_SOURCE  # `model:video-rules/1`
PROMPT_NAME = "video-frames/1"
TRANSCRIPT_SOURCE = "video-transcription"  # heard here, as a memo is; no call: synthesis leaves it out
TRANSCRIPT_MEDIA = "text/vtt"
TIER = videos.TIER
LANGUAGE = "en"  # the language the rules write in
FRAMES = (0.2, 0.5, 0.8)  # where in a scene its frames are taken, as fractions of its length
SPEECH_NAME_MIN = 5  # a name shorter than this is never matched in what was said: "Hjem", "Home"
QUOTE_CHARS = 90
DESCRIPTION_CHARS = 160
SEASONS = ("winter", "spring", "summer", "autumn")
SEASON_MONTHS = {"spring": (3, 5), "summer": (6, 8), "autumn": (9, 11)}  # the north; winter crosses a year
CONFIDENCE = ("high", "medium", "low")
EN_DASH = "\u2013"
NOTHING = "Nothing in this scene's frames or speech says where or when it was filmed; nothing is proposed."

PROMPT = (
    "This is one frame of a family's home video, digitised from an old tape. Answer with one JSON object"
    ' and nothing else: {"description": one factual sentence saying what is in the picture, "setting":'
    " indoors or outdoors and the kind of place in a few words (a kitchen, a harbour, a beach, a garden),"
    ' "season": "winter", "spring", "summer", "autumn" or "unknown" from what is visible (snow, bare trees,'
    ' leaves, flowers, clothes), "signs": a list of every piece of text visible in the picture, copied'
    " exactly as written, from signs, shop fronts, banners, boats' hulls, number plates and papers, an empty"
    ' list when there is none, "stamp": the date or time the camera burned into a corner of the picture,'
    ' copied exactly, or null, "things": a short list of the visible things}. Never name or identify a'
    ' person: write "a person", "two children". Never guess where the picture was taken: copy text you'
    " can read, and nothing else. Describe only what is visible."
)


class EngineMissing(Exception):
    """An extra this run needs is not installed, or ffmpeg is not on this machine."""


class ModelMissing(Exception):
    """A model is not on this machine; `videos fetch --models` fetches it."""


# -- the scenes -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Settings:
    """The scene finder's thresholds and the frame sampling (the module's docstring says what each is).
    Every value enters the key: other settings infer a file again."""

    cut: float = 0.30
    soft_cut: float = 0.10
    pair_s: float = 0.5
    side_s: float = 1.0
    jump_db: float = 6.0
    quiet_db: float = -55.0
    gap_s: float = 1.0
    window_s: float = 0.25
    merge_s: float = 3.0
    short_s: float = 6.0
    frames: tuple[float, ...] = FRAMES

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["frames"] = list(self.frames)
        return data


SETTINGS = Settings()


@dataclass(frozen=True)
class Scene:
    """One continuous recording: its number in the file, from 1, its offsets in seconds, and what
    opened it (`start` for the first; `cut`, `cut and sound`, `silence`)."""

    n: int
    start: float
    end: float
    opened_by: str

    @property
    def length(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class _Break:
    at: float
    strength: float
    kind: str


def find_scenes(
    duration: float,
    cuts: Sequence[tuple[float, float]],
    levels: Sequence[tuple[float, float]],
    settings: Settings = SETTINGS,
) -> list[Scene]:
    """The scenes of a file `duration` seconds long, from its picture's cuts (seconds, score) and its
    soundtrack's levels (seconds, dB), by the rules of the module's docstring. At least one scene: the
    whole file, when nothing breaks it."""
    if duration <= 0:
        return []
    sound = _Sound(levels, settings)
    breaks: list[_Break] = []
    for t, score in sorted(cuts):
        if score >= settings.cut:
            breaks.append(_Break(t, score + (0.5 if sound.breaks(t) else 0.0), "cut"))
        elif score >= settings.soft_cut and sound.breaks(t):
            breaks.append(_Break(t, score + 0.5, "cut and sound"))
    breaks.extend(sound.gaps())
    kept = _merge(sorted(breaks, key=lambda b: b.at), settings.merge_s)
    kept = [b for b in kept if settings.merge_s <= b.at <= duration - settings.merge_s]
    edges = [0.0, *(round(b.at, 2) for b in kept), round(duration, 2)]
    kinds = ["start", *(b.kind for b in kept)]
    return [
        Scene(n, edges[n - 1], edges[n], kinds[n - 1])
        for n in range(1, len(edges))
        if edges[n] > edges[n - 1]
    ]


class _Sound:
    """The soundtrack's windows, indexed: a mean over any stretch and the silent windows near a moment
    in logarithmic time, so a three-hour DVD with thousands of weak cuts is read in seconds."""

    def __init__(self, levels: Sequence[tuple[float, float]], settings: Settings) -> None:
        found = sorted(levels)
        self.settings = settings
        self.times = [t for t, _db in found]
        self.levels = [db for _t, db in found]
        self.sums = [0.0, *itertools.accumulate(self.levels)]
        self.quiet = [0, *itertools.accumulate(int(db <= settings.quiet_db) for db in self.levels)]

    def _span(self, start: float, end: float) -> tuple[int, int]:
        return bisect.bisect_left(self.times, start), bisect.bisect_left(self.times, end)

    def mean(self, start: float, end: float) -> float | None:
        """The mean level of the windows that begin in [start, end)."""
        a, b = self._span(start, end)
        return (self.sums[b] - self.sums[a]) / (b - a) if b > a else None

    def breaks(self, at: float) -> bool:
        """Whether the soundtrack breaks near `at`: a silent window within `pair_s`, or its level over
        the `side_s` after differing from the `side_s` before by `jump_db` or more (each window wholly
        on its side of the moment)."""
        if not self.times:
            return False
        s, w = self.settings, self.settings.window_s
        a, b = self._span(at - s.pair_s - w, at + s.pair_s + 1e-9)
        if self.quiet[b] - self.quiet[a] > 0:
            return True
        for shift in (-s.pair_s, 0.0, s.pair_s):
            moment = at + shift
            before = self.mean(moment - s.side_s, moment - w + 1e-9)
            after = self.mean(moment, moment + s.side_s)
            if before is not None and after is not None and abs(after - before) >= s.jump_db:
                return True
        return False

    def gaps(self) -> list[_Break]:
        """A break at the middle of every silence of `gap_s` or more."""
        s = self.settings
        found: list[_Break] = []
        run: list[float] = []
        for t, db in [*zip(self.times, self.levels, strict=True), (float("inf"), 0.0)]:
            if db <= s.quiet_db and (not run or t - run[-1] <= s.window_s * 1.5):
                run.append(t)
                continue
            if run and run[-1] + s.window_s - run[0] >= s.gap_s:
                found.append(_Break((run[0] + run[-1] + s.window_s) / 2, 0.9, "silence"))
            run = [t] if db <= s.quiet_db else []
        return found


def _merge(breaks: Sequence[_Break], merge_s: float) -> list[_Break]:
    """Breaks within `merge_s` of the first of a group are one, the strongest kept; then, of two kept
    breaks closer than `merge_s`, the stronger. Anchored to the first, a long run of weak breaks can
    never swallow a strong one beyond it."""
    groups: list[list[_Break]] = []
    for b in breaks:
        if groups and b.at - groups[-1][0].at < merge_s:
            groups[-1].append(b)
        else:
            groups.append([b])
    kept: list[_Break] = []
    for b in (max(group, key=lambda b: (b.strength, -b.at)) for group in groups):
        if kept and b.at - kept[-1].at < merge_s:
            if b.strength > kept[-1].strength:
                kept[-1] = b
            continue
        kept.append(b)
    return kept


def frame_times(scene: Scene, settings: Settings = SETTINGS) -> list[float]:
    """Where a scene's frames are taken: `settings.frames` of its length, or its middle alone when it
    is shorter than `short_s`."""
    fractions = settings.frames if scene.length >= settings.short_s else (0.5,)
    return [round(scene.start + f * scene.length, 2) for f in fractions]


# -- what a frame shows -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Frame:
    """What the vision model saw in one frame, cleaned; `offset_s` is where in the file it is."""

    offset_s: float
    description: str
    setting: str | None
    season: str | None
    signs: tuple[str, ...]
    stamp: str | None
    things: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "offset_s": self.offset_s,
            "description": self.description,
            "setting": self.setting,
            "season": self.season,
            "signs": list(self.signs),
            "stamp": self.stamp,
            "things": list(self.things),
        }


def parse_frame(text: str, offset_s: float) -> Frame | None:
    """The frame's description in the model's answer (the first JSON object in it), or None when it
    holds none."""
    data = describe.parse(text)
    if data is None or not isinstance(data.get("description"), str):
        return None
    sentence = _words(data["description"], DESCRIPTION_CHARS * 2)
    if not sentence:
        return None
    season = str(data.get("season") or "").strip().casefold()
    season = {"fall": "autumn"}.get(season, season)
    signs = data.get("signs")
    signs_list = [signs] if isinstance(signs, str) else signs if isinstance(signs, list) else []
    stamp = data.get("stamp")
    things = data.get("things")
    return Frame(
        offset_s,
        sentence,
        _words(data.get("setting"), 60) or None,
        season if season in SEASONS else None,
        tuple(dict.fromkeys(w for w in (_words(s, 80) for s in signs_list[:8]) if w)),
        _words(stamp, 40) or None,
        tuple(dict.fromkeys(w.casefold() for w in (_words(t, 40) for t in things[:12]) if w))
        if isinstance(things, list)
        else (),
    )


def _words(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


# -- dates ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class When:
    """A date or a range of local days, both inclusive, and how precise the evidence is: `day`,
    `month`, `season`, `year` or `range`."""

    first: date
    last: date
    precision: str

    def to_json(self) -> dict[str, Any]:
        return {"from": self.first.isoformat(), "to": self.last.isoformat(), "precision": self.precision}

    def text(self) -> str:
        if self.precision == "day":
            return f"{self.first.day} {calendar.month_name[self.first.month]} {self.first.year}"
        if self.precision == "month":
            return f"{calendar.month_name[self.first.month]} {self.first.year}"
        if self.precision == "season":
            return f"{_season_of(self.first.month)} {self.first.year}"
        if self.precision == "year":
            return str(self.first.year)
        return f"{self.first.isoformat()} to {self.last.isoformat()}"


MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "mai": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "okt": 10,
    "nov": 11,
    "dec": 12,
    "des": 12,
}
# a month's name in English or Norwegian, abbreviated or whole: never any other word ("AUTO", "MODE")
_MONTH = rf"(?P<mon>(?:{'|'.join(MONTHS)})[a-zæøå]{{0,6}})\.?"
# a year: four digits, or two after an apostrophe or alone, never the hours of a time (`10:42`, `10.42`)
_YEAR = r"(?P<y>\d{4}|'?\d{2})(?![\d:]|\.\d)"
STAMPS = (  # tried in this order; the first the text holds decides
    ("ymd", re.compile(r"(?<!\d)(?P<y>\d{4})[./-](?P<a>\d{1,2})[./-](?P<b>\d{1,2})(?!\d)")),
    ("mdy", re.compile(rf"(?<![a-z]){_MONTH}\s*(?P<d>\d{{1,2}})(?:st|nd|rd|th)?(?:,\s*|\s+){_YEAR}", re.I)),
    ("dmy", re.compile(rf"(?<!\d)(?P<d>\d{{1,2}})\.?\s*{_MONTH}\s*,?\s*{_YEAR}", re.I)),
    ("abY", re.compile(r"(?<!\d)(?P<a>\d{1,2})[./-](?P<b>\d{1,2})[./-](?P<y>\d{4}|\d{2})(?![\d:]|\.\d)")),
    ("mY", re.compile(rf"(?<![a-z]){_MONTH}\s*,?\s*(?P<y>\d{{4}})(?!\d)", re.I)),
    ("Y", re.compile(r"(?<!\d)(?P<y>19\d\d|20\d\d)(?!\d)")),
)
# the time a camera's clock shows when it was never set, beside 1 January: midnight
MIDNIGHT = re.compile(r"(?<![\d:])(?:0?0[:.]00(?::00)?|12:00(?::00)?\s*AM)(?!\d)", re.I)
NEVER_SET = "1 January is also what a camera's clock shows when it was never set."
# a year that says how long something has stood, not when the picture was taken: a shop's sign, a banner
SINCE_YEAR = re.compile(
    r"(?i)(?:\bsince|\best\.?|\bestablished|\betablert|\bsiden|\bgrunnlagt|\banno|\u00a9)\s*(?:in\s+)?"
    r"(19\d\d|20\d\d)(?!\d)"
)
YEAR_WORD = re.compile(r"(?<!\d)(19[5-9]\d|20[0-9]\d)(?!\d)")
SEASON_WORDS = {
    "winter": "winter",
    "vinter": "winter",
    "spring": "spring",
    "vår": "spring",
    "summer": "summer",
    "sommer": "summer",
    "autumn": "autumn",
    "fall": "autumn",
    "høst": "autumn",
}


def stamp_when(text: str, today: date) -> When | None:
    """The date a camera's stamp shows, to the precision it shows it, or None when it shows none: the
    first of `STAMPS` the text holds decides, and a date it holds that is not a real day before today
    (a garbled `31.02.1994`, a clock never set) dates nothing, not even its year."""
    for form, pattern in STAMPS:
        found = pattern.search(text)
        if found is not None:
            when = _stamp(form, found, today)
            if when is not None and _new_year(when) and MIDNIGHT.search(text):
                return None  # 1 January at midnight: the clock was never set
            return when
    return None


def _new_year(when: When) -> bool:
    return when.precision == "day" and (when.first.month, when.first.day) == (1, 1)


def _year(text: str, today: date) -> int | None:
    digits = text.lstrip("'")
    if len(digits) == 2:
        yy = int(digits)
        year = 2000 + yy if 2000 + yy <= today.year else 1900 + yy
    else:
        year = int(digits)
    return year if 1950 <= year <= today.year else None


def _month(word: str) -> int | None:
    return MONTHS.get(word.casefold()[:3])


def _day(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _stamp(form: str, found: re.Match[str], today: date) -> When | None:
    year = _year(found["y"], today)
    if year is None:
        return None
    if form == "Y":
        return When(date(year, 1, 1), date(year, 12, 31), "year")
    if form == "mY":
        month = _month(found["mon"])
        if month is None:
            return None
        return When(date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1]), "month")
    if form in ("mdy", "dmy"):
        month = _month(found["mon"])
        day = _day(year, month, int(found["d"])) if month is not None else None
        return When(day, day, "day") if day is not None and day <= today else None
    a, b = int(found["a"]), int(found["b"])
    if form == "ymd":
        day = _day(year, a, b)
        return When(day, day, "day") if day is not None and day <= today else None
    readings = {d for d in (_day(year, b, a), _day(year, a, b)) if d is not None and d <= today}
    if not readings:
        return None
    first, last = min(readings), max(readings)
    return When(first, last, "day" if first == last else "range")


def _season_of(month: int) -> str:
    return next((s for s, (a, b) in SEASON_MONTHS.items() if a <= month <= b), "winter")


def _in_season(year: int, season: str) -> When | None:
    months = SEASON_MONTHS.get(season)
    if months is None:
        return None
    first, last = months
    return When(date(year, first, 1), date(year, last, calendar.monthrange(year, last)[1]), "season")


# -- the proposal ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Speech:
    """One stretch of what was said, its offsets in the file."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Where:
    """A place of the owner's registries: `place` (a `places.json` name, which is the place's id) or
    `asset` (an `assets.json` id)."""

    type: str
    id: str
    label: str

    def to_json(self) -> dict[str, Any]:
        return {"type": self.type, "id": self.id, "registry": "logbook", "label": self.label}


@dataclass(frozen=True)
class Segment:
    """One sentence of the draft: what it rests on (`video`, the frames; `transcript`, what was said;
    or both), which part of the proposal it is about, and which frames and time ranges."""

    text: str
    part: str  # where, when, season, setting, nothing, proposed
    cites: tuple[str, ...]
    frames: tuple[float, ...] = ()
    speech: tuple[tuple[float, float], ...] = ()


@dataclass
class Proposal:
    where: Where | None
    when: When | None
    confidence: str | None
    segments: list[Segment] = field(default_factory=list)

    def to_json(self) -> dict[str, Any] | None:
        if self.where is None and self.when is None:
            return None
        return {
            "place": self.where.to_json() if self.where is not None else None,
            "when": self.when.to_json() if self.when is not None else None,
            "confidence": self.confidence,
        }


def fold(text: str) -> str:
    """Case, accents' composition and punctuation aside: the form names are matched in."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", folded).split())


def _names(text: str, name: str) -> bool:
    needle = fold(name)
    return bool(needle) and re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", fold(text)) is not None


@dataclass
class _Seen:
    where: Where
    weight: int = 0
    signs: list[tuple[float, str]] = field(default_factory=list)
    said: list[Speech] = field(default_factory=list)
    described: list[float] = field(default_factory=list)


def _registry(
    known: Sequence[places.Place], owned: Sequence[asset_registry.Asset]
) -> list[tuple[Where, str]]:
    """Every name the rules look for, with what it names: each place by its name, each asset by its
    name and its registration."""
    found: list[tuple[Where, str]] = [(Where("place", p.name, p.name), p.name) for p in known]
    for a in owned:
        where = Where("asset", a.id, a.name)
        found.append((where, a.name))
        if a.registration:
            found.append((where, a.registration))
    return [(w, n) for w, n in found if len(fold(n)) >= 3]


def propose(
    frames: Sequence[Frame],
    speech: Sequence[Speech],
    known: Sequence[places.Place],
    owned: Sequence[asset_registry.Asset],
    today: date,
) -> Proposal:
    """Where and when one scene was filmed, by the rules of the module's docstring, with a sentence per
    piece of evidence and the frames and time ranges each rests on."""
    segments: list[Segment] = []
    where, where_confidence = _where(frames, speech, known, owned, segments)
    when, when_confidence = _when(frames, speech, today, segments)
    _setting(frames, segments)
    if where is None and when is None:
        segments.append(
            Segment(NOTHING, "nothing", ("video", "transcript") if speech else ("video",), _offsets(frames))
        )
        return Proposal(None, None, None, segments)
    ranks = [CONFIDENCE.index(c) for c in (where_confidence, when_confidence) if c is not None]
    confidence = CONFIDENCE[max(ranks)]
    told = []
    if where is not None:
        told.append(f"where, {where.label} ({where_confidence})")
    if when is not None:
        told.append(f"when, {when.text()} ({when_confidence})")
    cites = tuple(dict.fromkeys(c for s in segments if s.part in ("where", "when") for c in s.cites))
    segments.append(Segment(f"Proposed: {'; '.join(told)}.", "proposed", cites or ("video",)))
    return Proposal(where, when, confidence, segments)


def _where(
    frames: Sequence[Frame],
    speech: Sequence[Speech],
    known: Sequence[places.Place],
    owned: Sequence[asset_registry.Asset],
    segments: list[Segment],
) -> tuple[Where | None, str | None]:
    seen: dict[Where, _Seen] = {}
    matched_signs: set[str] = set()
    for where, name in _registry(known, owned):
        entry = seen.get(where) or _Seen(where)
        for frame in frames:
            for sign in frame.signs:
                if _names(sign, name):
                    entry.signs.append((frame.offset_s, sign))
                    matched_signs.add(sign)
                    entry.weight += 3
            if _names(frame.description, name):
                entry.described.append(frame.offset_s)
                entry.weight += 1
        if len(fold(name)) >= SPEECH_NAME_MIN:
            for said in speech:
                if _names(said.text, name):
                    entry.said.append(said)
                    entry.weight += 2 if len(fold(name).split()) > 1 else 1
        if entry.weight:
            seen[where] = entry
    for frame in frames:
        for sign in frame.signs:
            if sign not in matched_signs and len(fold(sign)) >= 3 and not YEAR_WORD.fullmatch(fold(sign)):
                segments.append(
                    Segment(
                        f'A sign at {videos.clock(frame.offset_s)} reads "{sign}", which names none of your'
                        " places or assets.",
                        "where",
                        ("video",),
                        (frame.offset_s,),
                    )
                )
    if not seen:
        return None, None
    ranked = sorted(seen.values(), key=lambda e: -e.weight)
    for entry in ranked:
        segments.extend(_where_segments(entry))
    if len(ranked) > 1 and ranked[0].weight == ranked[1].weight:
        names = ", ".join(e.where.label for e in ranked if e.weight == ranked[0].weight)
        segments.append(
            Segment(
                f"Places of yours named as often as each other in this scene ({names}): none is proposed.",
                "where",
                tuple(dict.fromkeys(c for e in ranked for c in _cites(e))),
            )
        )
        return None, None
    best = ranked[0]
    if best.signs:
        confidence = "high"
    elif best.said and (len(fold(best.where.label).split()) > 1 or len(best.said) > 1):
        confidence = "medium"
    else:
        confidence = "low"
    return best.where, confidence


def _cites(entry: _Seen) -> tuple[str, ...]:
    found = []
    if entry.signs or entry.described:
        found.append("video")
    if entry.said:
        found.append("transcript")
    return tuple(found)


def _kind_word(where: Where) -> str:
    return "your places" if where.type == "place" else "your assets"


def _where_segments(entry: _Seen) -> Iterator[Segment]:
    where = entry.where
    for offset, sign in entry.signs:
        yield Segment(
            f'A sign at {videos.clock(offset)} reads "{sign}": {where.label}, of {_kind_word(where)}.',
            "where",
            ("video",),
            (offset,),
        )
    for said in entry.said:
        yield Segment(
            f'At {videos.span(said.start, said.end)} someone says "{_quote(said.text)}": {where.label},'
            f" of {_kind_word(where)}.",
            "where",
            ("transcript",),
            (),
            ((said.start, said.end),),
        )
    if entry.described:
        offsets = tuple(entry.described)
        yield Segment(
            f"The frame{'s' if len(offsets) > 1 else ''} at {_clocks(offsets)}"
            f" {'are' if len(offsets) > 1 else 'is'}"
            f" described with the name {where.label}, of {_kind_word(where)}.",
            "where",
            ("video",),
            offsets,
        )


def _when(
    frames: Sequence[Frame], speech: Sequence[Speech], today: date, segments: list[Segment]
) -> tuple[When | None, str | None]:
    stamped: list[tuple[Frame, When]] = []
    for frame in frames:
        if frame.stamp:
            found = stamp_when(frame.stamp, today)
            if found is not None:
                stamped.append((frame, found))
    seasons = Counter(f.season for f in frames if f.season)
    season_frames = tuple(f.offset_s for f in frames if f.season)
    if seasons:
        season, _ = seasons.most_common(1)[0]
        agree = len(seasons) == 1
        segments.append(
            Segment(
                f"The frame{'s' if len(season_frames) > 1 else ''} at {_clocks(season_frames)} show"
                f"{'' if len(season_frames) > 1 else 's'} "
                + (season if agree else f"different seasons ({', '.join(sorted(seasons))})")
                + ".",
                "season",
                ("video",),
                season_frames,
            )
        )
    if stamped:
        for frame, found in stamped:
            either = (
                f", which reads as {found.first.isoformat()} or {found.last.isoformat()}, one or the other:"
                " proposed as the span from one to the other"
                if found.precision == "range"
                else f": {found.text()}"
            )
            segments.append(
                Segment(
                    f"The camera's date stamp at {videos.clock(frame.offset_s)}"
                    f' reads "{frame.stamp}"{either}.',
                    "when",
                    ("video",),
                    (frame.offset_s,),
                )
            )
        whens = {w for _f, w in stamped}
        if len(whens) == 1:
            when = whens.pop()
            confidence = "high" if when.precision != "range" else "medium"
        else:
            when = When(min(w.first for w in whens), max(w.last for w in whens), "range")
            confidence = "medium"
        if _new_year(when):  # a stamp at midnight was refused already; one without a time is doubtful
            confidence = "low"
            segments.append(Segment(NEVER_SET, "when", ("video",), tuple(f.offset_s for f, _w in stamped)))
        if seasons and len(seasons) == 1 and when.precision in ("day", "month"):
            season = next(iter(seasons))
            if season != _season_of(when.first.month):
                confidence = "medium" if confidence == "high" else "low"
                segments.append(
                    Segment(
                        f"The frames show {season}, which does not fit {when.text()}.",
                        "when",
                        ("video",),
                        season_frames,
                    )
                )
        return when, confidence
    years: dict[int, list[Segment]] = {}
    for frame in frames:
        for sign in frame.signs:
            since = set(SINCE_YEAR.findall(sign))  # how long a shop has stood: no date of the picture
            for y in YEAR_WORD.findall(sign):
                if int(y) <= today.year and y not in since:
                    years.setdefault(int(y), []).append(
                        Segment(
                            f'"{y}" is written in the frame at {videos.clock(frame.offset_s)}.',
                            "when",
                            ("video",),
                            (frame.offset_s,),
                        )
                    )
    for said in speech:
        since = set(SINCE_YEAR.findall(said.text))
        for y in YEAR_WORD.findall(said.text):
            if int(y) <= today.year and y not in since:
                years.setdefault(int(y), []).append(
                    Segment(
                        f'At {videos.span(said.start, said.end)} someone says "{_quote(said.text)}".',
                        "when",
                        ("transcript",),
                        (),
                        ((said.start, said.end),),
                    )
                )
    if not years:
        return None, None
    for said_or_written in years.values():
        segments.extend(said_or_written)
    if len(years) > 1:
        return When(date(min(years), 1, 1), date(max(years), 12, 31), "range"), "low"
    year = next(iter(years))
    if seasons and len(seasons) == 1:
        narrowed = _in_season(year, next(iter(seasons)))
        if narrowed is not None:
            return narrowed, "low"
    return When(date(year, 1, 1), date(year, 12, 31), "year"), "low"


def _setting(frames: Sequence[Frame], segments: list[Segment]) -> None:
    """One sentence of what the frames show, so the owner remembers the scene."""
    if not frames:
        return
    shown = "; ".join(
        f"at {videos.clock(f.offset_s)}, {_quote(f.description, DESCRIPTION_CHARS).rstrip('.')}"
        for f in frames
    )
    segments.append(Segment(f"What the frames show: {shown}.", "setting", ("video",), _offsets(frames)))


def _offsets(frames: Sequence[Frame]) -> tuple[float, ...]:
    return tuple(f.offset_s for f in frames)


def _clocks(offsets: Sequence[float]) -> str:
    texts = [videos.clock(o) for o in offsets]
    return texts[0] if len(texts) == 1 else f"{', '.join(texts[:-1])} and {texts[-1]}"


def _quote(text: str, limit: int = QUOTE_CHARS) -> str:
    words = " ".join(text.split()).replace('"', "'")
    return words if len(words) <= limit else words[: limit - 1].rstrip() + "…"


# -- the run ----------------------------------------------------------------------------------------


def key(speech: transcribe.Engine, vision: describe.Engine, settings: Settings = SETTINGS) -> str:
    """What a file is inferred under: the rules, the prompt, the two models and the scene settings. A
    file whose drafts carry this key is not inferred again."""
    what = {
        "rules": RULES,
        "prompt": PROMPT_NAME,
        "prompt_sha256": hashlib.sha256(PROMPT.encode("utf-8")).hexdigest(),
        "speech": {"engine": speech.name, "model": speech.model},
        "vision": {"engine": vision.name, "model": vision.model},
        "settings": settings.to_json(),
    }
    text = json.dumps(what, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def keys_of(lines: Iterable[Line]) -> dict[str, set[str]]:
    """video line id → the keys its scene drafts were written under."""
    found: dict[str, set[str]] = {}
    for line in lines:
        scene = videos.scene_of(line) if videos.is_scene_draft(line) else None
        extra = (line.get("payload") or {}).get("extra")
        if scene is not None and isinstance(extra, dict) and isinstance(extra.get("inference"), str):
            found.setdefault(scene[0], set()).add(extra["inference"])
    return found


@dataclass(frozen=True)
class Job:
    video: videos.Video
    file: Path


@dataclass
class Done:
    video: videos.Video
    scenes: int
    proposed: int
    transcript: bool
    words: int
    seconds: float
    removed: bool


@dataclass
class Report:
    cached: int  # files in the cache whose video line stands
    already: int  # of those, inferred under this key already
    jobs: list[Job]
    dry_run: bool
    counts: dict[str, int] = field(default_factory=dict)
    done: list[Done] = field(default_factory=list)
    written: int = 0
    key: str | None = None


def pending(
    lb: Logbook, since: str | None, under: str | None, keep: bool, dry_run: bool
) -> tuple[list[Job], int, int]:
    """The cached files to infer, in the folder's order, how many cached files there are, and how many
    were inferred under `under` already (deleted from the cache as they are found, unless `keep` or a
    dry run). `since` keeps the video lines from that local day on."""
    cache = videos.Cache(lb.root)
    zone = ZoneInfo(str(lb.meta["timezone"]))
    with lb.index() as idx:
        gone = retractions(idx.retractions())
        listed = videos.standing_videos(idx.by_kind(videos.KIND), gone, idx.superseded(videos.KIND))
        done = keys_of(idx.by_kind(videos.DRAFT_KIND))
    jobs: list[Job] = []
    cached = already = 0
    for video in listed:
        path = cache.cached(video)
        if path is None:
            continue
        if since is not None and _local_day(str(video.line["at"]), zone) < since:
            continue
        cached += 1
        if under is not None and under in done.get(video.id, set()):
            already += 1
            if not keep and not dry_run:
                path.unlink(missing_ok=True)
            continue
        jobs.append(Job(video, path))
    return jobs, cached, already


def run(
    lb: Logbook,
    media: media_module.Media | None,
    speech: transcribe.Engine | None,
    vision: describe.Engine | None,
    *,
    since: str | None = None,
    limit: int | None = None,
    keep: bool = False,
    dry_run: bool = False,
    settings: Settings = SETTINGS,
    progress: Callable[[str], None] | None = None,
    today: date | None = None,
) -> Report:
    """Infer every cached file not yet inferred under this run's key, oldest in the folder first, at
    most `limit`: its scenes, its transcript line and one draft per scene, written as soon as the file
    is read, so an interrupted run keeps what it did. A dry run lists and needs no engine."""
    under = key(speech, vision, settings) if speech is not None and vision is not None else None
    jobs, cached, already = pending(lb, since, under, keep, dry_run)
    report = Report(cached, already, jobs[: limit if limit is not None else len(jobs)], dry_run, key=under)
    if dry_run or not report.jobs:
        return report
    if media is None or speech is None or vision is None or under is None:
        raise EngineMissing("videos infer needs ffmpeg, the transcribe extra and the describe extra")
    for engine, what in ((speech, "speech"), (vision, "vision")):
        if not engine.ready():
            raise ModelMissing(
                f"the {what} model {engine.model!r} is not on this machine:"
                " run `logbook videos fetch --models`"
                " once (this command never uses the network)"
            )
    known = places.read(lb.root)
    owned = asset_registry.read(lb.root)
    when = today or datetime.now(ZoneInfo(str(lb.meta["timezone"]))).date()
    with transcribe.offline():
        for n, job in enumerate(report.jobs, 1):
            started = time.monotonic()
            if progress is not None:
                progress(f"  {n}/{len(report.jobs)}  {job.video.name}: reading")
            done = _infer(lb, job, media, speech, vision, under, settings, known, owned, when, report)
            done.seconds = time.monotonic() - started
            if not keep:
                job.file.unlink(missing_ok=True)
                done.removed = True
            report.done.append(done)
            if progress is not None:
                progress(
                    f"  {n}/{len(report.jobs)}  {job.video.name}: {_plural(done.scenes, 'scene')},"
                    f" {done.proposed} proposed, {_plural(done.words, 'word')} heard, {done.seconds:.0f}s"
                )
    return report


def _infer(
    lb: Logbook,
    job: Job,
    media: media_module.Media,
    speech: transcribe.Engine,
    vision: describe.Engine,
    under: str,
    settings: Settings,
    known: Sequence[places.Place],
    owned: Sequence[asset_registry.Asset],
    today: date,
    report: Report,
) -> Done:
    probe = media.probe(job.file)
    cuts = media.cuts(job.file, settings.soft_cut) if probe.video else []
    levels = media.levels(job.file, settings.window_s) if probe.audio else []
    scenes = find_scenes(probe.duration_s, cuts, levels, settings)
    scratch = job.file.parent / f".infer-{job.file.stem}"
    scratch.mkdir(parents=True, exist_ok=True)
    read: list[tuple[Scene, list[Frame], list[Speech]]] = []
    languages: Counter[str] = Counter()
    try:
        for scene in scenes:
            frames = _frames(job.file, scene, media, vision, scratch, settings, report)
            said: list[Speech] = []
            if probe.audio:
                said, language = _speech(job.file, scene, media, speech, scratch)
                if language:
                    languages[language] += 1
            read.append((scene, frames, said))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    heard = [s for _scene, _frames, said in read for s in said]
    proposed = 0
    with lb.writer():
        transcript_id = _transcript(lb, job.video, heard, speech, languages, len(scenes)) if heard else None
        head = str(lb.meta["head"])
        earlier = standing_drafts(lb, job.video.id)
        lines = []
        for scene, frames, said in read:
            proposal = propose(frames, said, known, owned, today)
            proposed += proposal.to_json() is not None
            lines.append(
                _draft(
                    job.video,
                    scene,
                    len(scenes),
                    frames,
                    said,
                    proposal,
                    transcript_id,
                    head,
                    under,
                    speech,
                    vision,
                    settings,
                    earlier,
                )
            )
        report.written += lb.append_many(lines)
    return Done(
        job.video,
        len(scenes),
        proposed,
        transcript_id is not None,
        sum(len(s.text.split()) for s in heard),
        0.0,
        False,
    )


def standing_drafts(lb: Logbook, video_id: str) -> dict[str, str]:
    """scene ref → the id of the standing draft of that scene of this video (RFC 0036 rule 2: the
    latest not retracted and not named in a later draft's `supersedes`), so a file inferred again
    supersedes its earlier draft of each scene it cuts the same way."""
    found: dict[str, list[Line]] = {}
    with lb.index() as idx:
        gone = retractions(idx.retractions())
        for line in idx.of_source(videos.DRAFT_KIND, SOURCE, "", "9999-12-31"):
            scene = videos.scene_of(line) if videos.is_scene_draft(line) else None
            if scene is None or scene[0] != video_id or str(line["id"]) in gone:
                continue
            found.setdefault(str(line["payload"]["subject"][0]), []).append(line)
    kept = {ref: drafts.standing(lines) for ref, lines in found.items()}
    return {ref: str(draft["id"]) for ref, draft in kept.items() if draft is not None}


def _frames(
    file: Path,
    scene: Scene,
    media: media_module.Media,
    vision: describe.Engine,
    scratch: Path,
    settings: Settings,
    report: Report,
) -> list[Frame]:
    """The scene's frames, each read by the vision model and deleted at once."""
    found: list[Frame] = []
    for offset in frame_times(scene, settings):
        image = scratch / f"frame-{scene.n}-{offset:.2f}.jpg"
        try:
            media.frame(file, offset, image)
            frame = parse_frame(vision.describe(image, PROMPT), offset)
        except media_module.MediaError:
            _count(report.counts, "frames_unreadable")
            continue
        finally:
            image.unlink(missing_ok=True)
        if frame is None:
            _count(report.counts, "frames_not_described")
            continue
        found.append(frame)
    return found


def _speech(
    file: Path, scene: Scene, media: media_module.Media, speech: transcribe.Engine, scratch: Path
) -> tuple[list[Speech], str]:
    """What was said in the scene, heard by the transcribe extra's public function, its offsets the
    file's; the language it was heard in."""
    sound = scratch / f"sound-{scene.n}.wav"
    try:
        media.audio(file, scene.start, scene.end, sound)
        result = transcribe.hear(speech, sound)
    except media_module.MediaError:
        return [], ""
    finally:
        sound.unlink(missing_ok=True)
    said = [
        Speech(
            round(min(scene.end, scene.start + max(0.0, s.start)), 2),
            round(min(scene.end, scene.start + s.end), 2),
            s.text,
        )
        for s in result.segments
        if s.text.strip()
    ]
    return said, result.language


def vtt(heard: Sequence[Speech]) -> str:
    """The file's speech as WebVTT: one cue per segment, with its times in the file."""
    lines = ["WEBVTT", ""]
    for n, s in enumerate(sorted(heard, key=lambda s: (s.start, s.end)), 1):
        lines += [str(n), f"{_cue_time(s.start)} --> {_cue_time(max(s.end, s.start))}", s.text, ""]
    return "\n".join(lines)


def _cue_time(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, rest = divmod(millis, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def _transcript(
    lb: Logbook,
    video: videos.Video,
    heard: Sequence[Speech],
    speech: transcribe.Engine,
    languages: Counter[str],
    scenes: int,
) -> str:
    """The file's one transcript line, its id: the one already in the record with the same text, or a
    new one, superseding the earlier transcript of the same file when there is one."""
    data = vtt(heard).encode("utf-8")
    raw_id = f"video:{video.drive_id}@{hashlib.sha256(data).hexdigest()[:12]}"
    earlier: Line | None = None
    with lb.index() as idx:
        gone = retractions(idx.retractions())
        for line in idx.of_source("transcript", TRANSCRIPT_SOURCE, "", "9999-12-31"):
            payload = line.get("payload") or {}
            provenance = payload.get("provenance")
            if str(line["id"]) in gone or not isinstance(provenance, dict):
                continue
            if provenance.get("source") != video.id:
                continue
            if payload.get("raw_id") == raw_id:
                return str(line["id"])
            earlier = line
    lb.attach(data)  # tier 2: sealed when the record names recipients
    language = languages.most_common(1)[0][0] if languages else None
    draft = transcript.draft(
        source=TRANSCRIPT_SOURCE,
        at=str(video.line["at"]),
        end=None,
        raw_id=raw_id,
        content=attachments.reference(data, TRANSCRIPT_MEDIA),
        turns=[],
        tier=max(TIER, int(video.line.get("tier") or TIER)),
        title=video.title,
        participants=[],
        language=language,
        extra={
            "video": video.drive_id,
            "scenes": scenes,
            "segments": len(heard),
            "format": "vtt",
            "time_unknown": True,
        },
    )
    payload = draft["payload"]
    payload["provider"] = speech.name
    payload["provenance"] = {"source": video.id, "engine": speech.name, "model": speech.model}
    if earlier is not None:
        payload["supersedes"] = str(earlier["id"])
    line = lb.append(
        draft["at"],
        draft["source"],
        draft["kind"],
        draft["tier"],
        payload,
        end=None,
        tz=str(video.line.get("tz")),
    )
    return str(line["id"])


def _draft(
    video: videos.Video,
    scene: Scene,
    total: int,
    frames: Sequence[Frame],
    said: Sequence[Speech],
    proposal: Proposal,
    transcript_id: str | None,
    head: str,
    under: str,
    speech: transcribe.Engine,
    vision: describe.Engine,
    settings: Settings,
    earlier: dict[str, str] | None = None,
) -> dict[str, Any]:
    """One scene's draft/v1 line: every segment cites the video line (the frames) or the transcript
    line (what was said), the frames and ranges under `extra.segments`; `supersedes` the standing
    draft of the same scene (`earlier`, scene ref → id) when the file was inferred before."""
    ids = {"video": video.id, "transcript": transcript_id}
    segments = []
    details = []
    for s in proposal.segments:
        evidence = [ids[c] for c in s.cites if ids.get(c)] or [video.id]
        segments.append({"text": s.text, "evidence": list(dict.fromkeys(evidence))})
        detail: dict[str, Any] = {"part": s.part}
        if s.frames:
            detail["frames"] = list(s.frames)
        if s.speech:
            detail["speech"] = [list(r) for r in s.speech]
        details.append(detail)
    payload: dict[str, Any] = {
        "schema": drafts.SCHEMA,
        "unit": videos.DRAFT_UNIT,
        "subject": [videos.scene_ref(video.id, scene.start, scene.end)],
        "read_head": head,
        "read_count": 2 if transcript_id else 1,
        "language": LANGUAGE,
        "segments": segments,
        "extra": {
            "scene": {
                "video": video.id,
                "n": scene.n,
                "of": total,
                "start_s": scene.start,
                "end_s": scene.end,
                "opened_by": scene.opened_by,
            },
            "proposal": proposal.to_json(),
            "frames": [f.to_json() for f in frames],
            "speech": [[s.start, s.end] for s in said],
            "segments": details,
            "inference": under,
            "rules": RULES,
            "prompt": PROMPT_NAME,
            "models": {
                "speech": {"engine": speech.name, "model": speech.model},
                "vision": {"engine": vision.name, "model": vision.model},
            },
            "settings": settings.to_json(),
        },
    }
    ref = payload["subject"][0]
    if earlier and ref in earlier:
        payload["supersedes"] = earlier[ref]
    problems = drafts.validate(payload)
    if problems:  # a writer refuses what is not a draft (RFC 0036): a bug here, never written
        raise drafts.DraftError("; ".join(problems))
    return {
        "at": now_utc(),
        "end": None,
        "tz": video.line.get("tz"),
        "source": SOURCE,
        "kind": videos.DRAFT_KIND,
        "tier": max(TIER, int(video.line.get("tier") or TIER)),
        "payload": payload,
    }


def summary(report: Report) -> str:
    """The closing lines of `videos infer`."""
    already = (
        f" ({report.already} already inferred under these models and settings)" if report.already else ""
    )
    if report.dry_run:
        return (
            f"dry run: {_plural(len(report.jobs), 'file')} in the cache would be inferred{already};"
            " nothing written, nothing deleted"
        )
    if not report.cached:
        return "nothing to infer: the cache holds no video; `videos fetch` fills it"
    if not report.done:
        return f"nothing new to infer{already}"
    scenes = sum(d.scenes for d in report.done)
    proposed = sum(d.proposed for d in report.done)
    lines = [
        f"inferred {_plural(len(report.done), 'file')}: {_plural(scenes, 'scene')},"
        f" {proposed} with a proposal,"
        f" {_plural(report.written, 'draft')} written{already}; `review videos` to confirm them"
    ]
    removed = sum(d.removed for d in report.done)
    if removed:
        lines.append(f"  {_plural(removed, 'file')} deleted from the cache")
    skipped = [f"{n:,} {k.replace('_', ' ')}" for k, n in report.counts.items() if n]
    if skipped:
        lines.append(f"  {', '.join(skipped)}")
    return "\n".join(lines)


def _local_day(at: str, zone: ZoneInfo) -> str:
    return datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(zone).date().isoformat()


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _plural(n: int, noun: str) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {noun}s"


def detect(
    speech_model: str, vision_model: str
) -> tuple[media_module.Media, transcribe.Engine, describe.Engine]:
    """ffmpeg, the speech engine and the vision engine this machine has; EngineMissing naming what to
    install."""
    try:
        found = media_module.detect()
        speech = transcribe.detect(speech_model)
        vision = describe.detect(vision_model)
    except (media_module.MediaMissing, transcribe.EngineMissing, describe.EngineMissing) as e:
        raise EngineMissing(str(e)) from None
    return found, speech, vision


__all__ = [
    "PROMPT",
    "SETTINGS",
    "EngineMissing",
    "Frame",
    "ModelMissing",
    "Proposal",
    "Scene",
    "Settings",
    "When",
    "detect",
    "find_scenes",
    "frame_times",
    "key",
    "parse_frame",
    "propose",
    "run",
    "stamp_when",
    "summary",
    "vtt",
]
