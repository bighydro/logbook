"""`logbook review speakers` (RFC 0038 §4): the voices not yet named, proposed against the people the
record names, with the evidence, numbered; the owner's say; and the one writer of an attribution.

**The observed voice** (§4.1). A label is the id one recording gives a voice, so a row of the queue is
an *observed voice*, keyed by the strongest identifier the voice carries: the far end of a call (the
voice alone on the `system` channel of a recording that overlaps a `call/v1` line whose counterparty
is an email or a phone) is keyed as people review keys that address or number; else the name the
source displayed, its words folded and sorted; else the label alone, one row per voice. The voice
itself (a voiceprint cluster, §4.1 rule 2) is build 3's, with the registry of §5: until then a voice
is never grouped by how it sounds. An answer to a row is an answer for every voice in it; `N.2`
answers the second recording's voice alone, which is how a row that joined two people is split.

**The score** (§4.3), a plain sum per candidate and voice, a row's the lowest of its voices':

- **the far end of a call**, 40: the voice is alone on `system` and the recording overlaps a call
  whose counterparty resolves to the person;
- **on the entry**, 15: the person attends a timed `event/v1` the recording overlaps, held at the same
  stay (SPEC §3.2.5 rule 1);
- **a participant**, 15: a `participants` entry resolves to the person by email, phone or provider
  id; 5 by a name alone;
- **the source's name**, 10: the voice's `name` is the person's label, or a word of it the record
  gives nobody else;
- **seen that day**, 5: another line of the recording's local day resolves to the person (a message,
  a call, a tagged face, a voice bound in another recording).

`same voice` (up to 70, against a voiceprint) is left out: there is no registry in this build. Context
never stands in for a voice: a candidate without the far end of a call scores 40 at most, so
`--all-above` over 40 never takes a guest named by context alone. Two candidates within 5 points are
both shown and neither is taken. A pair the owner said no to (an `entity-review/v1` or
`people-review/v1` line naming the voice) and a person `policy/speakers.json` says to `forget` are
never proposed. The owner is proposed by nothing until the registry exists (a `from_me` voice is the
owner's without a question); the owner answers `me`.

**The owner's say** (§4.4). Nothing is bound on its own. `answer` is the one writer: every answer of
one command is checked before the first line, then each voice gets one `resolution/v1` line through
`Logbook.append`, `source` `manual`, `method` `owner`, a `speaker` ref, `entity` the person (the owner's
`owner_id`, a person the record names, one minted for a new name, or one minted with no label for
`--unnamed`), `label` the person's (none for the owner and the unnamed), `basis` (`channel` when the
person is the far end of the call the recording overlaps, `voice` when the audio is in the store, else
`text`, which carries `confidence`, the score over 100 capped at `text_confidence_cap`), `consent` when
stated, `evidence` the transcript and the lines the score rested on, `logbook_head`, `supersedes` the
voice's standing line, and under `extra` the row's id, the score and what matched. The same entity,
basis and consent as the standing line write nothing. A no is one `entity-review/v1` line of type
person (RFC 0035 amendment 1, by RFC 0037: `people-review/v1` is read forever and no longer written),
`ref` the row's first voice, `refs` every voice, `entity` the candidate.

**A wrong answer** (§4.5). `read(..., named=True)` lists the voices already named, of one recording or
of a day, numbered as the queue is; an answer to one supersedes its standing line. A wrong no is undone
by retracting its line, a wrong yes by `repair retract SEQ`, which returns the voice to the queue.

Nothing here opens a socket; `play` decodes the audio on this machine and hands a WAV file to a player
on this machine."""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import wave
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..core import attribution, day_start, present, reading, resolve, speakers, stays
from ..core import people as people_reader
from ..core.chain import Line
from ..core.flights import Airports
from ..core.resolve import Identity, Ref
from ..core.store import Logbook, now_utc, retractions, uuid7
from . import entities

SOURCE, METHOD, KIND, SCHEMA = "manual", "owner", "resolution", "resolution/v1"
REGISTRY = "logbook"
TIER = 2
FAR_END, ON_THE_ENTRY, PARTICIPANT, PARTICIPANT_BY_NAME, SOURCE_NAME, SEEN = 40, 15, 15, 5, 10, 5
CONTEXT_CAP = 40  # §4.3: context never stands in for a voice
CLOSE = 5  # §4.3: two candidates this close are both shown and neither is taken
PLAY_S = 20.0  # §4.2: the voice's first twenty seconds alone
QUOTE_CHARS = 60
SETTINGS_FILE = ("policy", "speakers.json")
DEFAULTS: dict[str, Any] = {
    "match": 0.75,
    "floor": 0.5,
    "min_clean_s": 8,
    "text_confidence_cap": 0.6,
    "enrol_unnamed": False,
    "forget": [],
}
ACCEPT, NAME, UNNAMED, REJECT = "accept", "name", "unnamed", "reject"
ME = frozenset({"me", "you", "i", "myself", "jeg", "meg", "ich"})  # the owner's answer for their own voice
NUMBER = re.compile(r"^(\d+)(?:\.(\d+))?$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
NOTHING = (
    'nothing written: `review speakers --accept N[,N]`, `--name N "…"`, `--unnamed N`, `--reject N[,N]`,'
    " `--consent N=yes|no|unknown`, or `--all-above SCORE`"
)


class ReviewError(ValueError):
    """What the record cannot act on: one sentence, nothing written."""


# -- the settings ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Settings:
    """`policy/speakers.json` (§5.5), read each run. This build uses `text_confidence_cap` and
    `forget`; `match`, `floor`, `min_clean_s` and `enrol_unnamed` are the registry's (build 3) and are
    checked, not used."""

    match: float = 0.75
    floor: float = 0.5
    min_clean_s: float = 8.0
    text_confidence_cap: float = 0.6
    enrol_unnamed: bool = False
    forget: frozenset[str] = frozenset()


def settings(root: Path) -> Settings:
    """The settings, the defaults for a key the file does not have or a record with no file;
    ReviewError naming the file for one that is not what it should be."""
    path = Path(root).joinpath(*SETTINGS_FILE)
    if not path.is_file():
        return Settings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise ReviewError(f"{'/'.join(SETTINGS_FILE)} is not JSON: {e}") from e
    if not isinstance(data, dict):
        raise ReviewError(f"{'/'.join(SETTINGS_FILE)} must be one object, as {json.dumps(DEFAULTS)}")
    found = {**DEFAULTS, **data}
    unit = ("match", "floor", "text_confidence_cap")
    for key in unit:
        if not _number(found[key]) or not 0 <= float(found[key]) <= 1:
            raise ReviewError(f"{'/'.join(SETTINGS_FILE)}: {key} must be a number from 0 to 1")
    if not _number(found["min_clean_s"]) or float(found["min_clean_s"]) < 0:
        raise ReviewError(f"{'/'.join(SETTINGS_FILE)}: min_clean_s must be seconds, 0 or more")
    if not isinstance(found["enrol_unnamed"], bool):
        raise ReviewError(f"{'/'.join(SETTINGS_FILE)}: enrol_unnamed must be true or false")
    forget = found["forget"]
    if not isinstance(forget, list) or not all(isinstance(e, str) and e for e in forget):
        raise ReviewError(f"{'/'.join(SETTINGS_FILE)}: forget must be a list of entity ids")
    return Settings(
        float(found["match"]),
        float(found["floor"]),
        float(found["min_clean_s"]),
        float(found["text_confidence_cap"]),
        bool(found["enrol_unnamed"]),
        frozenset(forget),
    )


# -- what the queue holds ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Seen:
    """One person and how the record put them near a voice: the kind of evidence (§4.3's rows), its
    points, the matched words and the lines."""

    entity: str
    kind: str  # far end, entry, participant, name, day
    points: int
    matched: str
    lines: tuple[str, ...]

    @property
    def far_end(self) -> bool:
        return self.kind == "far end"


@dataclass
class Voice:
    """One voice of one standing transcript, as the review reads it."""

    heard: attribution.Heard
    line: Line  # the transcript
    day: str  # the recording's local day
    where: str | None  # the stay it overlaps, named as the Day names it
    first: str | None  # its first segment's words, when the text and the spans file are here
    audio: str | None  # the digest of the audio heard, when the file is in the store
    call: str | None = None  # the call it is the far end of: that line's id
    seen: list[Seen] = field(default_factory=list)  # the evidence, every candidate's
    standing: Line | None = None  # the voice's own standing attribution, when one stands

    @property
    def ref(self) -> str:
        return self.heard.ref

    @property
    def label(self) -> str:
        return self.heard.label

    @property
    def transcript(self) -> str:
        return str(self.line["id"])

    @property
    def tier(self) -> int:
        return int(self.line.get("tier") or TIER)

    def score(self, entity: str) -> tuple[int, list[str], list[str], bool]:
        """(the score of `entity` for this voice, what matched, the lines, whether the far end of
        the call): the plain sum, each kind of evidence once, capped at 40 without the far end."""
        points, matched, lines, far = 0, [], [], False
        kinds: set[str] = set()
        for s in sorted(self.seen, key=lambda s: -s.points):
            if s.entity != entity or s.kind in kinds:
                continue
            kinds.add(s.kind)
            points += s.points
            matched.append(s.matched)
            lines += [line for line in s.lines if line not in lines]
            far = far or s.far_end
        return (points if far else min(points, CONTEXT_CAP)), matched, lines, far


@dataclass(frozen=True)
class Candidate:
    """A person proposed for a row: the owner (`owner`), or a person by their label."""

    entity: str
    name: str | None
    owner: bool
    score: int
    matched: tuple[str, ...]
    lines: tuple[str, ...]

    @property
    def shown(self) -> str:
        return speakers.OWNER if self.owner else self.name or self.entity

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.entity,
            "person": self.entity,
            "name": self.name,
            "owner": self.owner,
            "score": self.score,
            "matched": list(self.matched),
            "evidence": list(self.lines),
        }


@dataclass
class Row:
    """One observed voice: its key, its voices (one per recording), its candidates, best first."""

    number: int
    key: Ref
    voices: list[Voice]
    candidates: list[Candidate]
    that_day: list[tuple[str, list[str]]] = field(default_factory=list)  # (name, how) of the day's people
    shared: list[str] = field(default_factory=list)  # other voices of the recording the best is as good for

    @property
    def id(self) -> str:
        """The first 16 hex of the SHA-256 of the row's refs, sorted: the same row at any head."""
        return hashlib.sha256("\n".join(sorted(v.ref for v in self.voices)).encode("utf-8")).hexdigest()[:16]

    @property
    def score(self) -> int | None:
        return self.candidates[0].score if self.candidates else None

    @property
    def close(self) -> bool:
        """Two candidates within `CLOSE` points: both shown, neither taken."""
        return len(self.candidates) > 1 and self.candidates[0].score - self.candidates[1].score <= CLOSE

    @property
    def seconds(self) -> float:
        return sum(v.heard.voice.seconds or 0.0 for v in self.voices)

    def to_json(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "id": self.id,
            "key": {"kind": self.key[0], "value": self.key[1]},
            "score": self.score,
            "close": self.close,
            "shared": list(self.shared),
            "voices": [
                {
                    "number": f"{self.number}.{i}",
                    "ref": v.ref,
                    "transcript": v.transcript,
                    "label": v.label,
                    "day": v.day,
                    "at": v.line.get("at"),
                    "title": _title(v.line),
                    "where": v.where,
                    "seconds": v.heard.voice.seconds,
                    "channel": v.heard.voice.channel,
                    "name": v.heard.voice.name,
                    "first": v.first,
                    "audio": v.audio is not None,
                    "standing": None if v.standing is None else str(v.standing["id"]),
                    "bound": v.heard.to_json() if v.heard.bound else None,
                }
                for i, v in enumerate(self.voices, 1)
            ],
            "candidates": [c.to_json() for c in self.candidates],
            "that_day": [{"name": name, "seen": how} for name, how in self.that_day],
        }


@dataclass
class Report:
    """The queue (or, `named`, the voices already named of a recording or a day) at one head."""

    rows: list[Row]
    head: str
    tz: ZoneInfo
    settings: Settings
    owner: present.Owner
    identities: dict[Ref, Identity]
    named_count: int  # the voices of the standing transcripts a line binds
    waiting: int  # the voices not yet named
    recordings: int  # the recordings they are in
    named: bool = False  # the listing of §4.5, not the queue
    people: dict[str, str] = field(default_factory=dict)  # every person a label names, entity → label
    rejected: dict[str, set[str]] = field(default_factory=dict)  # entity → the speaker refs said no to
    tiers: dict[str, int] = field(default_factory=dict)  # line id → tier, of the evidence
    bound: dict[str, set[str]] = field(default_factory=dict)  # transcript id → the people its voices are
    voices_bound: dict[tuple[str, str], list[str]] | None = None  # `answer`'s, kept across a sitting

    @property
    def tier(self) -> int | None:
        return max((v.tier for r in self.rows for v in r.voices), default=None)

    def voices_of_people(self) -> dict[tuple[str, str], list[str]]:
        """(transcript id, person) → the labels a standing line binds to them, for `answer` to say
        when one person becomes a second voice of a recording."""
        found: dict[tuple[str, str], list[str]] = {}
        for ref, who in self.identities.items():
            split = attribution.split(ref[1]) if ref[0] == attribution.SPEAKER else None
            if split is not None and who.entity and not who.unnamed:
                found.setdefault((split[0], who.entity), []).append(split[1])
        return found

    def to_json(self) -> dict[str, Any]:
        return {
            "named_listing": self.named,
            "not_yet_named": self.waiting,
            "recordings": self.recordings,
            "named": self.named_count,
            "tier": self.tier,
            "head": self.head,
            "rows": [r.to_json() for r in self.rows],
        }


# -- reading -----------------------------------------------------------------------------------------------


def read(
    lb: Logbook,
    named: bool = False,
    recording: str | None = None,
    day: str | None = None,
    airports: Any = None,
) -> Report:
    """The queue: every voice of the standing transcripts no line binds (a `from_me` voice is the
    owner's and is not asked), grouped into rows, scored, numbered. With `named`, the voices of one
    recording (`recording`, its id or seq) or of one local day (`day`) that are named already, one row
    each, for an answer that supersedes. Raises ReviewError; writes nothing."""
    if named and (recording is None) == (day is None):
        raise ReviewError("--named takes --recording ID or --day DAY, one of them")
    if not named and (recording is not None or day is not None):
        raise ReviewError("--recording and --day go with --named")
    config = settings(lb.root)
    days = day_start.of(lb.meta)
    with lb.index() as idx:
        marks = idx.retractions()
        resolutions = idx.resolutions()
        retracted = retractions(marks)
        heard_again = idx.superseded("transcript")  # a transcript heard again (§2.8) stands no more
        by = idx.ids(heard_again.values())
        superseded = {old for old, seq in heard_again.items() if by.get(seq) not in retracted}
        transcripts = [
            line
            for line in idx.by_kind("transcript")
            if str(line["id"]) not in retracted and str(line["id"]) not in superseded
        ]
        reviews = [*idx.by_kind(entities.ENTITY_REVIEW), *idx.by_kind(entities.PEOPLE_REVIEW), *marks]
        head = str(lb.meta.get("head") or "")
        identities = resolve.identities_from([*marks, *resolutions])
        standing = resolve.standing([*marks, *resolutions])
        owner = present.owner_of(
            str(lb.meta.get("owner_id") or ""),
            [str(e) for e in lb.meta.get("owner_emails") or [] if isinstance(e, str)],
            _owner_aliases(lb),
            identities,
        )
        voices = attribution.Voices(identities, owner.entities, owner.id)
        all_heard = [(line, h) for line in transcripts for h in voices.of(line)]
        named_count = sum(1 for _line, h in all_heard if h.bound and (attribution.SPEAKER, h.ref) in standing)
        if named:
            wanted = _recording(idx, recording, transcripts) if recording is not None else None
            chosen = [
                (line, h)
                for line, h in all_heard
                if h.bound
                and (wanted is None or str(line["id"]) == wanted)
                and (day is None or days.day_of(str(line["at"])) == day)
            ]
        else:
            chosen = [(line, h) for line, h in all_heard if not h.bound]
        found_days = sorted({days.day_of(str(line["at"])) for line, _h in chosen})
        context = _Context(lb, idx, found_days, identities, owner, retracted) if chosen else None
    waiting = sum(1 for _line, h in all_heard if not h.bound)
    recordings = len({str(line["id"]) for line, h in all_heard if not h.bound})
    people = _people(identities, owner)
    rejected = _rejected(reviews)
    report = Report(
        [],
        head,
        days.zone,
        config,
        owner,
        identities,
        named_count,
        waiting,
        recordings,
        named,
        people,
        rejected,
    )
    if context is None:
        return report
    texts: dict[str, list[Any] | None] = {}
    observed: list[Voice] = []
    for line, h in chosen:
        if str(line["id"]) not in texts:
            texts[str(line["id"])] = attribution.voiced_turns(lb, line)
        voice = Voice(
            h,
            line,
            days.day_of(str(line["at"])),
            context.where(line),
            _first_words(texts[str(line["id"])], h.label),
            _audio(lb, line),
            standing=standing.get((attribution.SPEAKER, h.ref)),
        )
        context.evidence(voice, voices)
        observed.append(voice)
    report.tiers = context.tiers
    for line, h in all_heard:
        if h.state == attribution.PERSON and h.entity:
            report.bound.setdefault(str(line["id"]), set()).add(h.entity)
    report.rows = _rows(observed, report, context) if not named else _named_rows(observed, report)
    return report


def _owner_aliases(lb: Logbook) -> dict[str, list[str]]:
    from ..core import policy

    return policy.owner_aliases(lb.root)


def _recording(idx: Any, wanted: str, transcripts: Sequence[Line]) -> str:
    """The id of the standing transcript `wanted` names, by its id or its seq."""
    ids = {str(line["id"]) for line in transcripts}
    if wanted in ids:
        return wanted
    seq = wanted.lstrip("#")
    if seq.isdigit():
        line = idx.by_seq(int(seq))
        if line is not None and str(line.get("id")) in ids:
            return str(line["id"])
    raise ReviewError(f"--recording {wanted}: no standing transcript has that id or seq")


def _people(identities: Mapping[Ref, Identity], owner: present.Owner) -> dict[str, str]:
    """entity → label of every person a resolution names with a label, never the owner and never a
    person bound unnamed."""
    found: dict[str, str] = {}
    unnamed = {who.entity for who in identities.values() if who.unnamed and who.entity}
    for who in identities.values():
        if not who.entity or not who.label or who.type not in present.PERSON_TYPES:
            continue
        if who.entity in owner.entities or who.entity in unnamed:
            continue
        found.setdefault(who.entity, who.label)
    return found


def _rejected(lines: Iterable[Line]) -> dict[str, set[str]]:
    """entity → the speaker refs a standing no names (`ref` and `refs`), of either profile."""
    found: dict[str, set[str]] = {}
    for review in entities.reviews(lines):
        if review.kind != entities.PERSON or review.entity is None:
            continue
        refs = {review.ref, *review.refs}
        found.setdefault(review.entity, set()).update(v for k, v in refs if k == attribution.SPEAKER)
    return found


def _audio(lb: Logbook, line: Line) -> str | None:
    diarization = (line.get("payload") or {}).get("diarization")
    audio = diarization.get("audio") if isinstance(diarization, dict) else None
    if not speakers.is_digest(audio):
        return None
    return str(audio) if (lb.root / "attachments" / str(audio)).is_file() else None


def _first_words(turns: list[Any] | None, label: str) -> str | None:
    for turn in turns or ():
        if turn.speaker == label and turn.text.strip():
            text = " ".join(turn.text.split("\n")[0].split())
            return text if len(text) <= QUOTE_CHARS else text[: QUOTE_CHARS - 1].rstrip() + "…"
    return None


class _Context:
    """What the record holds around the queue's recordings: the owner's stays and the places, the
    calls, the calendar entries, and who else each day resolved (`seen that day`)."""

    def __init__(
        self,
        lb: Logbook,
        idx: Any,
        found_days: Sequence[str],
        identities: Mapping[Ref, Identity],
        owner: present.Owner,
        retracted: Mapping[str, Line],
    ) -> None:
        self.identities = identities
        self.owner = owner
        self.tiers: dict[str, int] = {}
        self.airports: Airports | None = None
        first, last = found_days[0], found_days[-1]
        try:
            track = reading.owner_track(lb, first, last, None)
            self.stays, self.places = track.stays, track.places
        except stays.SettingsError:
            self.stays, self.places = [], []
        self.days = day_start.of(lb.meta)

        def standing(kind: str) -> list[Line]:
            gone = idx.superseded(kind)
            return [
                line
                for line in idx.by_kind(kind, first, last)
                if str(line["id"]) not in retracted and str(line["id"]) not in gone
            ]

        self.calls = standing("call")
        self.events = standing("event")
        self.by_day: dict[
            str, dict[str, list[tuple[str, str, str]]]
        ] = {}  # day → entity → (how, clock, line)
        for kind in ("message", "call", "photo", "event"):
            for line in self.calls if kind == "call" else self.events if kind == "event" else standing(kind):
                self.tiers[str(line["id"])] = int(line.get("tier") or 0)
                for entity in self._names(kind, line):
                    day = self.days.day_of(str(line["at"]))
                    clock = _clock(str(line["at"]), self.days.zone)
                    how = {"photo": "face", "event": "calendar"}.get(kind, kind)
                    self.by_day.setdefault(day, {}).setdefault(entity, []).append(
                        (how, clock, str(line["id"]))
                    )
        for line in standing("transcript"):  # a voice bound in another recording of the day
            self.tiers[str(line["id"])] = int(line.get("tier") or 0)
            for heard in attribution.Voices(identities, owner.entities, owner.id).of(line):
                if heard.state == attribution.PERSON and heard.entity:
                    day = self.days.day_of(str(line["at"]))
                    clock = _clock(str(line["at"]), self.days.zone)
                    self.by_day.setdefault(day, {}).setdefault(heard.entity, []).append(
                        ("voice", clock, str(line["id"]))
                    )

    def _person(self, ref: Ref | None) -> str | None:
        if ref is None:
            return None
        entity, _label = present.resolve_ref(ref, self.identities)
        return None if entity is None or entity in self.owner.entities else entity

    def _names(self, kind: str, line: Line) -> list[str]:
        payload = line.get("payload") or {}
        found: list[str | None] = []
        if kind == "message" and payload.get("from_me") is not True:
            found.append(self._person(_ref(payload.get("sender"))))
        elif kind == "call":
            found.append(self._person(_ref(payload.get("counterparty"))))
        elif kind == "photo":
            library = str(payload.get("library") or line.get("source") or "")
            people = payload.get("people")
            for pid in people if isinstance(people, list) else []:
                if isinstance(pid, str) and pid:
                    found.append(self._person(("provider_id", f"{library}:{pid}")))
        elif kind == "event":
            attendees = payload.get("attendees")
            for attendee in attendees if isinstance(attendees, list) else []:
                if isinstance(attendee, dict) and attendee.get("response") != "declined":
                    found.append(self._person(_ref(attendee.get("ref"))))
        return [e for e in dict.fromkeys(found) if e is not None]

    def stay(self, line: Line) -> stays.Segment | None:
        """The owner's stay the recording overlaps the longest, when one does."""
        start, end = _span(line)
        best, most = None, 0.0
        for stay in self.stays:
            overlap = (min(stay.end, end) - max(stay.start, start)).total_seconds()
            inside = start == end and stay.start <= start <= stay.end  # a recording with no end
            if overlap > most or (best is None and inside):
                best, most = stay, max(overlap, 0.0)
        return best

    def where(self, line: Line) -> str | None:
        """The stay the recording overlaps as the readers of people name it: its named place,
        `aboard <asset>`, else its coordinates with the nearest named place or airport city."""
        stay = self.stay(line)
        if stay is None:
            return None
        if self.airports is None:
            self.airports = Airports.load()
        return people_reader._where(stay, self.places, self.airports)

    def evidence(self, voice: Voice, voices: attribution.Voices) -> None:
        """Every piece of evidence for every candidate of one voice (§4.3, without `same voice`)."""
        line = voice.line
        payload = line.get("payload") or {}
        start, end = _span(line)
        # the far end of a call: alone on `system`, a call overlapping the recording
        if voice.label == speakers.SYSTEM or (
            voice.heard.voice.channel == speakers.SYSTEM and "." not in voice.label
        ):
            for call in self.calls:
                c_start, c_end = _call_span(call)
                if c_start > end or c_end < start:
                    continue
                ref = _ref((call.get("payload") or {}).get("counterparty"))
                if ref is None or ref[0] not in ("email", "phone"):
                    continue
                voice.call = str(call["id"])
                entity = self._person(ref)
                if entity is not None:
                    clock = _clock(str(call["at"]), self.days.zone)
                    voice.seen.append(
                        Seen(
                            entity, "far end", FAR_END, f"the far end of the call {clock}", (str(call["id"]),)
                        )
                    )
                break
        # on the entry: a timed event the recording overlaps, held at the same stay
        stay = self.stay(line)
        if stay is not None:
            for event in self.events:
                e_payload = event.get("payload") or {}
                if e_payload.get("all_day") is True:
                    continue
                e_start, e_end = _span(event)
                if e_start >= end or e_end <= start:
                    continue
                if not present._held_at(stay, event, self.places):
                    continue
                title = str(e_payload.get("title") or "an entry")
                for entity in self._names("event", event):
                    voice.seen.append(
                        Seen(entity, "entry", ON_THE_ENTRY, f'on the entry "{title}"', (str(event["id"]),))
                    )
        # a participant
        participants = payload.get("participants")
        for participant in participants if isinstance(participants, list) else []:
            if not isinstance(participant, dict):
                continue
            entity = None
            for kind in ("email", "phone", "provider_id"):
                value = participant.get(kind)
                if isinstance(value, str) and value:
                    entity = self._person((kind, value))
                    if entity is not None:
                        break
            if entity is not None:
                voice.seen.append(Seen(entity, "participant", PARTICIPANT, "a participant", ()))
                continue
            spoken = participant.get("name")
            if isinstance(spoken, str) and spoken.strip():
                entity, _label = present.by_name(spoken, self.identities)
                if entity is not None and entity not in self.owner.entities:
                    voice.seen.append(
                        Seen(
                            entity, "participant", PARTICIPANT_BY_NAME, f"a participant by name {spoken}", ()
                        )
                    )
        # the source's name
        shown = voice.heard.voice.name
        if shown:
            entity = _by_source_name(shown, self.identities, self.owner)
            if entity is not None:
                voice.seen.append(Seen(entity, "name", SOURCE_NAME, f"the source's name {shown}", ()))
        # seen that day
        for entity, seen in self.by_day.get(voice.day, {}).items():
            scored = {line for s in voice.seen if s.entity == entity for line in s.lines}
            gone = {voice.transcript, voice.call, *scored}  # a line is evidence once
            others = [(how, clock, id_) for how, clock, id_ in seen if id_ not in gone]
            if others:
                how, clock, id_ = others[0]
                voice.seen.append(Seen(entity, "day", SEEN, f"seen that day ({how} {clock})", (id_,)))

    def that_day(self, day: str, people: Mapping[str, str]) -> list[tuple[str, list[str]]]:
        found = []
        for entity, seen in self.by_day.get(day, {}).items():
            if entity in people:
                found.append((people[entity], list(dict.fromkeys(how for how, _c, _i in seen))))
        return sorted(found)


def _by_source_name(name: str, identities: Mapping[Ref, Identity], owner: present.Owner) -> str | None:
    """The person whose label is the name the source displayed (case and spacing aside), else the one
    person a word of whose label is a word of it no other person's label has."""
    entity, _label = present.by_label(name, identities)
    if entity is not None:
        return None if entity in owner.entities else entity
    words = set(_words(name))
    holders: dict[str, set[str]] = {}
    for who in identities.values():
        if who.entity and who.label and who.type in present.PERSON_TYPES and who.entity not in owner.entities:
            for word in _words(who.label):
                holders.setdefault(word, set()).add(who.entity)
    found = {next(iter(holders[w])) for w in words if w in holders and len(holders[w]) == 1}
    return next(iter(found)) if len(found) == 1 else None


def _rows(observed: Sequence[Voice], report: Report, context: _Context) -> list[Row]:
    """The voices grouped by their key (§4.1), each row's candidates scored, the rows numbered: the
    owner's rows first, then by the first recording, within a recording by the seconds spoken."""
    groups: dict[Ref, list[Voice]] = {}
    for voice in observed:
        groups.setdefault(_key(voice, context), []).append(voice)
    rows: list[Row] = []
    for key, members in groups.items():
        members.sort(key=lambda v: (str(v.line["at"]), int(v.line.get("seq") or 0)))
        candidates = _candidates(members, report)
        that_day = context.that_day(members[0].day, report.people) if len(members) == 1 else []
        rows.append(Row(0, key, members, candidates, that_day))
    # context is the recording's, not the voice's: a person proposed as the best for two voices of one
    # recording at the same score is shown for each, and taken by `--all-above` for neither
    best: dict[tuple[str, str, int], list[tuple[Row, str]]] = {}
    for row in rows:
        if row.candidates:
            top = row.candidates[0]
            for voice in row.voices:
                best.setdefault((voice.transcript, top.entity, top.score), []).append((row, voice.label))
    for found in best.values():
        if len(found) > 1:
            for row, _label in found:
                row.shared += [other for r, other in found if r is not row and other not in row.shared]
    rows.sort(
        key=lambda r: (
            not (r.candidates and r.candidates[0].owner),
            str(r.voices[0].line["at"]),
            int(r.voices[0].line.get("seq") or 0),
            -(r.voices[0].heard.voice.seconds or 0.0),
            r.voices[0].label,
        )
    )
    for n, row in enumerate(rows, 1):
        row.number = n
    return rows


def _named_rows(observed: Sequence[Voice], report: Report) -> list[Row]:
    rows = []
    for n, voice in enumerate(
        sorted(observed, key=lambda v: (str(v.line["at"]), -(v.heard.voice.seconds or 0.0), v.label)), 1
    ):
        heard = voice.heard
        bound = Candidate(
            heard.entity or "",
            heard.name,
            heard.state == attribution.OWNER,
            0,
            (),
            (),
        )
        rows.append(Row(n, (attribution.SPEAKER, voice.ref), [voice], [bound]))
    return rows


def _key(voice: Voice, context: _Context) -> Ref:
    """The observed voice's strongest identifier (§4.1): the far end's address or number, else the
    source's name folded, else the label alone."""
    if voice.call is not None:
        call = next((c for c in context.calls if str(c["id"]) == voice.call), None)
        ref = _ref(((call or {}).get("payload") or {}).get("counterparty"))
        if ref is not None:
            return (ref[0], ref[1].strip().casefold() if ref[0] == "email" else ref[1].strip())
    if voice.heard.voice.name:
        words = sorted(_words(voice.heard.voice.name))
        if words:
            return ("name", " ".join(words))
    return (attribution.SPEAKER, voice.ref)


def _candidates(voices: Sequence[Voice], report: Report) -> list[Candidate]:
    """Every person some evidence puts near every voice of the row, the row's score the lowest of its
    voices', a pair said no to and a person to forget left out, best first."""
    entities_seen = list(dict.fromkeys(s.entity for v in voices for s in v.seen))
    out = []
    for entity in entities_seen:
        if entity in report.settings.forget or entity not in report.people:
            continue
        if any(v.ref in report.rejected.get(entity, set()) for v in voices):
            continue
        if any(entity in report.bound.get(v.transcript, ()) for v in voices):
            continue  # one person, one voice of a recording: they are another voice of it already
        scored = [v.score(entity) for v in voices]
        score = min(s[0] for s in scored)
        if score <= 0:
            continue
        matched = tuple(dict.fromkeys(m for s in scored for m in s[1]))
        lines = tuple(dict.fromkeys(line for s in scored for line in s[2]))
        out.append(Candidate(entity, report.people[entity], False, score, matched, lines))
    out.sort(key=lambda c: (-c.score, c.name or "", c.entity))
    return out


# -- numbers -----------------------------------------------------------------------------------------------


def numbers(text: Sequence[str] | None) -> list[str]:
    """`--accept 1,2.1 --accept 4` → ["1", "2.1", "4"]; ReviewError for anything that is not one."""
    found: list[str] = []
    for chunk in text or ():
        for part in str(chunk).split(","):
            part = part.strip()
            if not part:
                continue
            if NUMBER.match(part) is None:
                raise ReviewError(f"{part!r} is not a row number: N, or N.M for one recording of row N")
            found.append(part)
    return found


def pick(report: Report, number: str) -> tuple[Row, list[Voice]]:
    """The row a number names and the voices it answers for: all of them for `N`, one for `N.M`."""
    m = NUMBER.match(number)
    if m is None:
        raise ReviewError(f"{number!r} is not a row number")
    n, sub = int(m.group(1)), m.group(2)
    row = next((r for r in report.rows if r.number == n), None)
    if row is None:
        raise ReviewError(
            f"no row {n}: the {'named voices' if report.named else 'queue'} has {len(report.rows)}"
        )
    if sub is None:
        return row, list(row.voices)
    i = int(sub)
    if not 1 <= i <= len(row.voices):
        raise ReviewError(f"no voice {number}: row {n} has {len(row.voices)}")
    return row, [row.voices[i - 1]]


def above(report: Report, score: str) -> list[Row]:
    """The rows whose one best candidate scores `score` or more; a row with two close candidates,
    and a blank, are never taken."""
    try:
        wanted = int(score)
    except ValueError:
        raise ReviewError(f"--all-above {score!r} is not a score: a whole number") from None
    if report.named:
        raise ReviewError("--all-above goes with the queue, not with --named")
    return [
        r
        for r in report.rows
        if r.candidates and not r.close and not r.shared and r.candidates[0].score >= wanted
    ]


def consents(text: Sequence[str] | None) -> dict[str, str]:
    """`--consent 2=yes --consent 3.1=no` → {"2": "yes", "3.1": "no"}."""
    found: dict[str, str] = {}
    for chunk in text or ():
        for part in str(chunk).split(","):
            number, sep, value = part.strip().partition("=")
            if not sep or NUMBER.match(number) is None or value not in attribution.CONSENTS:
                raise ReviewError(f"--consent {part!r}: say N=yes, N=no or N=unknown")
            if number in found and found[number] != value:
                raise ReviewError(f"--consent {number} is given twice; say one")
            found[number] = value
    return found


def answers_from(
    report: Report,
    accept: Sequence[str] | None = None,
    name: Sequence[Sequence[str]] | None = None,
    unnamed: Sequence[str] | None = None,
    reject: Sequence[str] | None = None,
    all_above: str | None = None,
    consent: Sequence[str] | None = None,
    same_as: str | None = None,
) -> list[Answer]:
    """The answers one command gives, as `--accept`, `--name N "…"`, `--unnamed`, `--same-as`,
    `--reject`, `--all-above` and `--consent` say them; ReviewError for one that cannot be read, a
    `--same-as` without `--unnamed`, or a consent for a row the command does not answer. `answer`
    makes the checks that need the listing."""
    accepted, rejected, nameless = numbers(accept), numbers(reject), numbers(unnamed)
    named: list[tuple[str, str]] = []
    for pair in name or ():
        number, text = (str(pair[0]), str(pair[1])) if len(pair) == 2 else ("", "")
        found = numbers([number]) if number else []
        if len(found) != 1:
            raise ReviewError(f'--name takes one number and a name: --name 3 "Kari Nordmann", not {number!r}')
        named.append((found[0], text))
    if same_as is not None and not nameless:
        raise ReviewError("--same-as goes with --unnamed: `--unnamed 5 --same-as 3`")
    if (
        same_as is not None
        and NUMBER.match(same_as) is None
        and "#" not in same_as
        and not UUID.match(same_as)
    ):
        raise ReviewError(f"--same-as {same_as!r}: a row number, a speaker ref or an unnamed person's id")
    stated = consents(consent)
    told = [*accepted, *(n for n, _ in named), *nameless, *rejected]
    if all_above is not None:
        accepted += [str(r.number) for r in above(report, all_above) if str(r.number) not in told]
    answers = [
        *(Answer(n, ACCEPT, consent=stated.get(n)) for n in accepted),
        *(Answer(n, NAME, name=text, consent=stated.get(n)) for n, text in named),
        *(Answer(n, UNNAMED, same_as=same_as, consent=stated.get(n)) for n in nameless),
        *(Answer(n, REJECT, consent=stated.get(n)) for n in rejected),
    ]
    loose = sorted(set(stated) - {a.number for a in answers})
    if loose:
        raise ReviewError(
            f"--consent {', '.join(loose)}: the command answers no such row; consent goes with an answer"
        )
    return answers


# -- the owner's say: the one writer -----------------------------------------------------------------------


@dataclass(frozen=True)
class Answer:
    """One answer of the owner's: `verdict` accept, name, unnamed or reject, for `number` (`N` or
    `N.M`), with the `name` given, the voice `same_as` names (an unnamed answer), the `consent`
    stated. The terminal, the flags and a later page all say it this way."""

    number: str
    verdict: str
    name: str | None = None
    same_as: str | None = None
    consent: str | None = None


@dataclass
class Written:
    """What one answer wrote: the lines (none when the record held it already, `held`)."""

    answer: Answer
    row: Row
    target: str  # how the answer reads: `you`, a name, `unnamed`, `≠ Kari Nordmann`
    lines: list[Line]
    held: int = 0  # voices whose standing line said this already
    also: list[str] = field(default_factory=list)  # other voices of the recording the person is (§13.1)

    def to_json(self) -> dict[str, Any]:
        return {
            "number": self.answer.number,
            "row": self.row.id,
            "verdict": self.answer.verdict,
            "target": self.target,
            "consent": self.answer.consent,
            "lines": [{"seq": line["seq"], "id": line["id"]} for line in self.lines],
            "held": self.held,
            "also": list(self.also),
        }


@dataclass
class _Plan:
    answer: Answer
    row: Row
    voices: list[Voice]
    entity: str | None  # None for a reject (its candidate is `against`)
    name: str | None
    owner: bool = False
    unnamed: bool = False
    against: Candidate | None = None
    mint: str | None = None  # the name a new person is minted under


def answer(lb: Logbook, report: Report, answers: Sequence[Answer]) -> list[Written]:
    """Every answer checked, then written: the lines of §4.4 through `Logbook.append`, in the order
    given. ReviewError, nothing written, for a number the listing does not have, a voice answered
    twice, an accept or a reject of a row with no single candidate, a name several people have, a
    consent for the owner's voice or a no, a `--same-as` that names no unnamed person, or a reject in
    the listing of named voices. Rereading is the caller's: the numbers are `report`'s."""
    plans = _plans(report, answers)
    with lb.writer():  # one hold for the command's lines, as every review writes (RFC 0037)
        return _write(lb, report, plans)


def _write(lb: Logbook, report: Report, plans: Sequence[_Plan]) -> list[Written]:
    at = now_utc()
    minted: dict[str, str] = {}  # a new name, folded → the person minted for it in this command
    unnamed_for: dict[str, str] = {}  # a row's number → the unnamed person minted for it
    if report.voices_bound is None:  # kept on the report: a sitting on a terminal answers row by row
        report.voices_bound = report.voices_of_people()
    bound_in = report.voices_bound  # (transcript, person) → the labels bound to them
    written: list[Written] = []
    for plan in plans:
        if plan.answer.verdict == REJECT:
            written.append(_reject(lb, report, plan, at))
            continue
        entity = plan.entity
        if plan.mint is not None:
            entity = minted.setdefault(" ".join(plan.mint.split()).casefold(), uuid7())
            plan.name = report.people.setdefault(entity, plan.mint)  # a later answer finds them by name
        elif plan.unnamed and entity is None:
            root = _root(plan, plans)
            entity = root.entity or unnamed_for.setdefault(root.answer.number, uuid7())
        assert entity is not None  # `_plans` gives every other answer its entity
        lines, held, also = [], 0, []
        for voice in plan.voices:
            payload = _payload(report, plan, voice, entity)
            if payload is None:
                held += 1
                continue
            if not plan.owner and not plan.unnamed:  # two labels may be one person (§13.1): said, not refused
                key = (voice.transcript, entity)
                also += [label for label in bound_in.get(key, []) if label != voice.label]
                bound_in.setdefault(key, []).append(voice.label)
            tier = max([TIER, voice.tier, *(report.tiers.get(e, 0) for e in payload["evidence"])])
            lines.append(lb.append(at=at, source=SOURCE, kind=KIND, tier=tier, payload=payload))
        target = speakers.OWNER if plan.owner else "unnamed" if plan.unnamed else plan.name or entity
        written.append(Written(plan.answer, plan.row, target, lines, held, sorted(set(also))))
    return written


def _plans(report: Report, answers: Sequence[Answer]) -> list[_Plan]:
    """Every answer resolved against the listing, every check made, before anything is written."""
    plans: list[_Plan] = []
    answered: dict[str, Answer] = {}  # voice ref → the answer that answers it
    for a in answers:
        if a.verdict not in (ACCEPT, NAME, UNNAMED, REJECT):
            raise ReviewError(f"{a.verdict!r} is not an answer: accept, name, unnamed or reject")
        if a.consent is not None and a.consent not in attribution.CONSENTS:
            raise ReviewError(f"consent {a.consent!r}: yes, no or unknown")
        row, voices = pick(report, a.number)
        for voice in voices:
            other = answered.get(voice.ref)
            if other is not None:
                if {other.verdict, a.verdict} == {REJECT} or REJECT not in (other.verdict, a.verdict):
                    raise ReviewError(f"{other.number} and {a.number} answer the same voice twice; say one")
                raise ReviewError(f"{a.number} is both accepted and rejected; say one")
            answered[voice.ref] = a
        plan = _Plan(a, row, voices, None, None)
        if a.verdict == REJECT:
            if report.named:
                raise ReviewError(
                    f"{a.number}: a voice already named is corrected by naming it again (`--name"
                    f' {a.number} "…"`, `--unnamed {a.number}`); a wrong yes is undone by'
                    " `repair retract SEQ`, which returns the voice to the queue"
                )
            plan.against = _single(row, a.number, "reject")
            if a.consent is not None:
                raise ReviewError(f"--consent {a.number}: a no states nobody's consent")
        elif a.verdict == ACCEPT:
            chosen = _single(row, a.number, "accept")
            plan.entity, plan.name, plan.owner = chosen.entity, chosen.name, chosen.owner
            if report.named and plan.owner is False and voices[0].heard.state == attribution.UNNAMED:
                plan.unnamed, plan.name = True, None
        elif a.verdict == NAME:
            if not a.name or not a.name.strip():
                raise ReviewError(f"--name {a.number}: say whose voice it is")
            plan.entity, plan.name, plan.owner, plan.mint = _named(report, a.name)
        else:
            plan.unnamed = True
            if a.same_as is not None:
                plan.entity = _same_as(report, a.same_as, answers)
        if a.consent is not None and plan.owner:
            raise ReviewError(f"--consent {a.number}: your own voice is not asked for consent")
        plans.append(plan)
    return plans


def _single(row: Row, number: str, verb: str) -> Candidate:
    if not row.candidates:
        raise ReviewError(
            f'row {row.number} proposes nobody: --name {number} "…", --unnamed {number}, or skip it'
        )
    if row.close:
        first, second = row.candidates[0], row.candidates[1]
        raise ReviewError(
            f"row {row.number} has two candidates within {CLOSE} points ({first.shown} {first.score},"
            f' {second.shown} {second.score}); say which: --name {number} "…"'
        )
    return row.candidates[0]


def _named(report: Report, text: str) -> tuple[str | None, str | None, bool, str | None]:
    """(entity, label, owner, a name to mint) for `--name N "…"`: the owner by `me` or their own names
    or id; a person by their id or a ref the record resolves (`email:…`, `phone:…`, an address, a
    number); the one person the record labels so (case and spacing aside); else a new person, minted
    under that name. A name several people have is refused."""
    raw = " ".join(text.split())
    folded = raw.casefold()
    owner = report.owner
    if folded in ME or folded in owner.names or raw in owner.entities:
        return owner.id or next(iter(sorted(owner.entities)), None), None, True, None
    if raw in report.people:
        return raw, report.people[raw], False, None
    refs = _refs_of(raw)
    for ref in refs:
        if ref in owner.refs:
            return owner.id or next(iter(sorted(owner.entities)), None), None, True, None
        who = report.identities.get(ref)
        if who is not None and who.entity and who.type in present.PERSON_TYPES:
            if who.entity in owner.entities:
                return who.entity, None, True, None
            if who.entity in report.people:
                return who.entity, report.people[who.entity], False, None
    if refs:
        raise ReviewError(f"{raw} is no person the record names: name them by their name to make one")
    matches = sorted(
        entity for entity, label in report.people.items() if " ".join(label.split()).casefold() == folded
    )
    if len(matches) > 1:
        raise ReviewError(
            f"{len(matches)} people are called {raw}: name one by its id ({', '.join(matches)})"
        )
    if matches:
        return matches[0], report.people[matches[0]], False, None
    if UUID.match(raw):
        raise ReviewError(f"{raw} is no person the record names")
    return None, raw, False, raw


def _refs_of(text: str) -> list[Ref]:
    kind, sep, value = text.partition(":")
    if sep and kind in ("email", "phone", "handle", "provider_id") and value:
        return [(kind, value.casefold() if kind == "email" else value)]
    if "@" in text and " " not in text:
        return [("email", text.casefold())]
    if re.fullmatch(r"\+\d{6,15}", text.replace(" ", "")):
        return [("phone", text.replace(" ", ""))]
    return []


def _same_as(report: Report, text: str, answers: Sequence[Answer]) -> str | None:
    """The unnamed person `--same-as` names: a voice of this listing bound unnamed (`N`, `N.M`), one
    answered `--unnamed` in the same command (None: they share the person minted for it), a `speaker`
    ref bound unnamed, or an unnamed person's id."""
    if NUMBER.match(text):
        if any(a.verdict == UNNAMED and a.number == text for a in answers):
            return None
        _row, voices = pick(report, text)
        heard = voices[0].heard
        if heard.state == attribution.UNNAMED and heard.entity:
            return heard.entity
        raise ReviewError(
            f"--same-as {text}: that voice is not bound unnamed; answer `--unnamed {text}` in the same"
            " command, or name a voice already bound unnamed"
        )
    who = report.identities.get((attribution.SPEAKER, text))
    if who is not None and who.unnamed and who.entity:
        return who.entity
    if any(w.unnamed and w.entity == text for w in report.identities.values()):
        return text
    raise ReviewError(f"--same-as {text}: no voice bound unnamed has that number, ref or id")


def _root(plan: _Plan, plans: Sequence[_Plan]) -> _Plan:
    """The unnamed answer whose person `plan` shares: `--same-as` a number answered `--unnamed` in the
    same command, followed to the first of such a chain (itself when there is none)."""
    current, seen = plan, {plan.answer.number}
    while current.entity is None and current.answer.same_as is not None:
        target = current.answer.same_as
        if target in seen:
            break
        seen.add(target)
        found = next((p for p in plans if p.answer.verdict == UNNAMED and p.answer.number == target), None)
        if found is None:
            break
        current = found
    return current


def _payload(report: Report, plan: _Plan, voice: Voice, entity: str) -> dict[str, Any] | None:
    """The `resolution/v1` payload for one voice, or None when the voice's standing line says the
    same already (the same entity, basis and consent; an unnamed voice answered unnamed again)."""
    owner = plan.owner
    score, matched, lines, far = voice.score(entity) if not owner and not plan.unnamed else (0, [], [], False)
    if far:
        basis = "channel"
    elif voice.audio is not None:
        basis = "voice"
    else:
        basis = "text"
    consent = plan.answer.consent
    standing = voice.standing
    if standing is not None:
        old = standing.get("payload") or {}
        same_entity = isinstance(old.get("entity"), dict) and old["entity"].get("id") == entity
        if same_entity and consent is None and old.get("consent") in attribution.CONSENTS:
            consent = str(old["consent"])  # the same person again: what was stated of them stands
        if plan.unnamed and old.get("unnamed") is True and plan.answer.same_as is None and consent is None:
            return None  # §10: --unnamed on a voice already bound unnamed writes nothing
        stated = consent or attribution.UNKNOWN  # §3.2: absent reads as `unknown`
        if (
            same_entity
            and old.get("basis") == basis
            and (old.get("consent") or attribution.UNKNOWN) == stated
        ):
            return None
    elif voice.heard.voice.from_me and owner and consent is None:
        return None  # the owner's microphone is the owner's without a line (§3.3 rule 4)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "ref": {"kind": attribution.SPEAKER, "value": voice.ref},
        "entity": {"type": "person", "id": entity, "registry": REGISTRY},
    }
    if not owner and not plan.unnamed and plan.name:
        payload["label"] = plan.name
    payload["method"] = METHOD
    payload["basis"] = basis
    if plan.unnamed:
        payload["unnamed"] = True
    if consent is not None and not owner:
        payload["consent"] = consent
    if basis == "text":  # what the record scored them at; your own word alone at the most text may say
        cap = report.settings.text_confidence_cap
        payload["confidence"] = round(min(score / 100, cap) if score > 0 else cap, 2)
    payload["evidence"] = list(dict.fromkeys([voice.transcript, *lines]))
    if report.head:
        payload["logbook_head"] = report.head
    if standing is not None:
        payload["supersedes"] = str(standing["id"])
    payload["extra"] = {"proposal": plan.row.id, "score": score, "matched": matched}
    return payload


def _reject(lb: Logbook, report: Report, plan: _Plan, at: str) -> Written:
    against = plan.against
    assert against is not None
    refs = [(attribution.SPEAKER, v.ref) for v in plan.voices]
    if any(v.ref in report.rejected.get(against.entity, set()) for v in plan.voices):  # §10: (ref, entity)
        return Written(plan.answer, plan.row, f"≠ {against.shown}", [], len(plan.voices))
    evidence = list(dict.fromkeys(v.transcript for v in plan.voices))
    payload = entities.review_payload(
        entities.PERSON,
        refs[0],
        refs,
        [v.heard.voice.name for v in plan.voices if v.heard.voice.name],
        against.entity,
        against.name,
        evidence,
        report.head or None,
        extra={"proposal": plan.row.id, "score": against.score, "matched": list(against.matched)},
    )
    problems = entities.validate_entity_review(payload)
    if problems:  # never: the payload is built to the profile
        raise ReviewError("; ".join(problems))
    tier = entities.review_tier([v.tier for v in plan.voices])
    line = lb.append(at=at, source=SOURCE, kind=entities.ENTITY_REVIEW, tier=tier, payload=payload)
    return Written(plan.answer, plan.row, f"≠ {against.shown}", [line])


# -- playing a voice ---------------------------------------------------------------------------------------


Decoder = Callable[[Path], tuple[Sequence[float], int]]
Player = Callable[[Path], None]


def clips(document: Mapping[str, Any], label: str, limit: float = PLAY_S) -> list[tuple[float, float]]:
    """The voice's first `limit` seconds alone: its turns in the spans file (seconds from the start
    of the recording), less every moment another voice speaks, in order, cut at `limit` in all."""
    turns = document.get("turns")
    mine: list[tuple[float, float]] = []
    others: list[tuple[float, float]] = []
    for t in turns if isinstance(turns, list) else []:
        if not isinstance(t, dict) or not _number(t.get("from")) or not _number(t.get("to")):
            continue
        span = (float(t["from"]), float(t["to"]))
        if span[1] > span[0]:
            (mine if t.get("speaker") == label else others).append(span)
    talking = _merged(others)
    out: list[tuple[float, float]] = []
    left = limit
    for start, end in _merged(mine):
        for a, b in _less(start, end, talking):
            if left <= 0:
                return out
            take = min(b - a, left)
            out.append((round(a, 2), round(a + take, 2)))
            left -= take
    return out


def _merged(spans: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _less(start: float, end: float, others: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    """`[start, end]` less the sorted, disjoint `others`."""
    out: list[tuple[float, float]] = []
    for a, b in others:
        if b <= start or a >= end:
            continue
        if a > start:
            out.append((start, a))
        start = max(start, b)
        if start >= end:
            return out
    if start < end:
        out.append((start, end))
    return out


def play(
    lb: Logbook,
    report: Report,
    number: str,
    decode: Decoder,
    player: Player | None = None,
) -> str:
    """Play the voice `number` names (the first recording of a row), its first twenty seconds alone,
    on this machine: the audio decoded here by `decode` (the transcription engine's own, which the
    command loads), the clips written to a temporary WAV file, a local player started on it, the
    file removed after. Nothing is written to the record. Returns what
    was played; ReviewError when it cannot be (no audio, no spans, no decoder, no player)."""
    _row, voices = pick(report, number)
    voice = voices[0]
    if voice.audio is None:
        raise ReviewError(f"{number}: the recording's audio is not in the store; there is nothing to play")
    diarization = (voice.line.get("payload") or {}).get("diarization") or {}
    spans = diarization.get("spans") if isinstance(diarization, dict) else None
    sha = spans.get("sha256") if isinstance(spans, dict) else None
    if not speakers.is_digest(sha) or not (lb.root / "attachments" / str(sha)).is_file():
        raise ReviewError(f"{number}: the recording has no spans file in the store, so its turns are unknown")
    document = json.loads(lb.attachment_bytes(str(sha)).decode("utf-8"))
    cut = clips(document, voice.label)
    if not cut:
        raise ReviewError(f"{number}: {voice.label} never speaks alone in the recording")
    player = player or _player()
    with lb.attachment(voice.audio) as audio:
        samples, rate = decode(audio)
    pcm = bytearray()
    for start, end in cut:
        for value in samples[int(start * rate) : int(end * rate)]:
            pcm += int(max(-1.0, min(1.0, float(value))) * 32767).to_bytes(2, "little", signed=True)
    with tempfile.TemporaryDirectory(prefix="logbook-voice-") as folder:
        out = Path(folder) / "voice.wav"
        with wave.open(str(out), "wb") as fh:
            fh.setnchannels(1)
            fh.setsampwidth(2)
            fh.setframerate(rate)
            fh.writeframes(bytes(pcm))
        player(out)
    seconds = sum(b - a for a, b in cut)
    return f'played {voice.label} of "{_title(voice.line)}": {seconds:.0f} s alone, in {len(cut)} pieces'


def _player() -> Player:
    """A player on this machine: `afplay` (macOS), `paplay`, `aplay` or `ffplay`, or Windows' own."""
    if sys.platform == "win32":
        import winsound

        return lambda path: winsound.PlaySound(str(path), winsound.SND_FILENAME)
    choices: tuple[tuple[str, list[str]], ...] = (
        ("afplay", []),
        ("paplay", []),
        ("aplay", ["-q"]),
        ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]),
    )
    for name, args in choices:
        found = shutil.which(name)
        if found:
            command = [found, *args]
            return lambda path: _run([*command, str(path)])
    raise ReviewError("--play needs a player on this machine: afplay, paplay, aplay or ffplay")


def _run(command: list[str]) -> None:
    with contextlib.suppress(KeyboardInterrupt):
        subprocess.run(command, check=False)


# -- text --------------------------------------------------------------------------------------------------


def rows(report: Report) -> Iterable[str]:
    """The queue as §4.2 prints it (or the named voices), then what to say."""
    if report.named:
        yield (
            f"{_plural(len(report.rows), 'voice')} named · tier {report.tier}"
            if report.rows
            else "no voice named there"
        )
    elif not report.rows:
        yield f"no voice waits to be named · {report.named_count} named"
        return
    else:
        head = (
            f"{_plural(report.waiting, 'voice')} not yet named in {_plural(report.recordings, 'recording')},"
            f" {_plural(len(report.rows), 'row')} · {report.named_count} named"
        )
        yield head if report.tier is None else f"{head} · tier {report.tier}"
    previous: str | None = None
    for row in report.rows:
        yield from _row_text(row, report, previous)
        previous = row.voices[0].transcript if len(row.voices) == 1 else None
    if report.named:
        yield (
            'nothing written: `review speakers --named … --name N "…"`, `--unnamed N`, or `--accept N'
            " --consent N=yes|no|unknown`; each supersedes the voice's standing line"
        )
    else:
        yield NOTHING


def _row_text(row: Row, report: Report, previous: str | None) -> Iterable[str]:
    score = "—" if row.score is None or report.named else str(row.score)
    lead = f"  {row.number:>2}  [{score}]".ljust(12)
    pad = " " * 12
    if len(row.voices) == 1:
        voice = row.voices[0]
        same = previous == voice.transcript
        yield f"{lead}{_voice_text(voice, report.tz, same)}"
    else:
        minutes = speakers.duration_text(row.seconds)
        yield f"{lead}a voice in {_plural(len(row.voices), 'recording')}, {minutes}{_proposal(row, report)}"
        for i, voice in enumerate(row.voices, 1):
            yield f"      {row.number}.{i}  {_voice_text(voice, report.tz, False)}"
        return
    if report.named:
        voice = row.voices[0]
        stated = voice.heard
        how = [stated.basis or "channel"]
        if stated.state != attribution.OWNER:
            how.append(f"consent {stated.consent or 'unknown'}")
        line = f"line #{voice.standing['seq']}" if voice.standing is not None else "from_me, no line"
        yield f"{pad}= {stated.shown}: {', '.join(how)} · {line}"
        return
    yield f"{pad}{_proposal(row, report).removeprefix(' ')}"
    if row.that_day:
        people = ", ".join(f"{name} ({', '.join(how)})" for name, how in row.that_day)
        yield f"{pad}that day: {people}"


def _proposal(row: Row, report: Report) -> str:
    if not row.candidates:
        return " → ____"
    shown = row.candidates[:2] if row.close else row.candidates[:1]
    parts = [f"{c.shown}: {' · '.join(c.matched)}" if c.matched else c.shown for c in shown]
    text = " → " + " | or ".join(parts)
    if row.close:
        text += " (two close: neither taken)"
    if row.shared:
        text += f" (as good for {', '.join(row.shared)} of the recording: not taken by --all-above)"
    return text


def _voice_text(voice: Voice, tz: ZoneInfo, same: bool) -> str:
    parts = []
    if same:
        parts.append("same recording")
    else:
        at = datetime.fromisoformat(str(voice.line["at"]).replace("Z", "+00:00")).astimezone(tz)
        parts.append(f"{WEEKDAYS[at.weekday()]} {at:%Y-%m-%d %H:%M}")
        if voice.where:
            parts.append(voice.where)
        parts.append(f'"{_title(voice.line)}"')
    parts.append(voice.label if not voice.heard.voice.name else f"{voice.label} ({voice.heard.voice.name})")
    if voice.heard.voice.seconds is not None:
        parts.append(speakers.duration_text(voice.heard.voice.seconds))
    if voice.first:
        parts.append(f'"{voice.first}"')
    return " · ".join(parts)


def written_rows(written: Iterable[Written]) -> Iterable[str]:
    for w in written:
        what = {ACCEPT: "accepted", NAME: "named", UNNAMED: "unnamed", REJECT: "rejected"}[w.answer.verdict]
        voices = _plural(len(w.lines), "line")
        held = f", {w.held} held already" if w.held else ""
        consent = f" · consent {w.answer.consent}" if w.answer.consent else ""
        seqs = ", ".join(f"#{line['seq']}" for line in w.lines)
        also = f"; {w.target} is also {', '.join(w.also)} of the recording" if w.also else ""
        yield (
            f"{what} {w.answer.number} → {w.target}{consent}: {voices}{held}"
            + (f" ({seqs})" if seqs else "")
            + also
        )


# -- helpers -----------------------------------------------------------------------------------------------


def _title(line: Line) -> str:
    title = (line.get("payload") or {}).get("title")
    return str(title) if isinstance(title, str) and title.strip() else "a recording"


def _span(line: Line) -> tuple[datetime, datetime]:
    start = stays.instant(line.get("at"))
    if start is None:
        start = datetime.fromisoformat("1970-01-01T00:00:00+00:00")
    end = stays.instant(line.get("end")) or start
    return start, max(start, end)


def _call_span(line: Line) -> tuple[datetime, datetime]:
    start, end = _span(line)
    seconds = (line.get("payload") or {}).get("duration_s")
    if end == start and isinstance(seconds, int | float) and _number(seconds):
        end = start + timedelta(seconds=float(seconds))
    return start, end


def _clock(stamp: str, tz: ZoneInfo) -> str:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(tz).strftime("%H:%M")


def _ref(value: object) -> Ref | None:
    if not isinstance(value, dict):
        return None
    kind, text = value.get("kind"), value.get("value")
    if not isinstance(kind, str) or not isinstance(text, str) or not text:
        return None
    return (kind, text.strip().casefold() if kind == "email" else text.strip())


def _words(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", text.casefold())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return re.sub(r"[^\w\s]|_", " ", folded).split()


def _number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"
