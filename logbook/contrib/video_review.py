"""`logbook review video`: the owner's say over what `videos infer` proposed, one scene at a time, the
sixth queue of RFC 0037's one review sitting (`logbook.commands.videos.VideoQueue`, RFC 0040). It
reads the record and the registries and opens no connection; it writes only through `Logbook.append`,
`source` `manual`, and only what the owner answers.

**The queue** is every scene of the family's videos whose draft (`draft/v1`, unit `event`, subject the
scene) nobody has answered yet, the drafts of each file's latest inference only: a scene with a
proposal first, the surest first (`high`, `medium`, `low`), then the folder's order and the scene's;
then the scenes with nothing to go on, for the owner to name or let go. Each row shows the scene (the
file, its number, its offsets), the proposal and the sentences it rests on with the frames and time
ranges they cite, what the frames showed, and, when the proposal is a single day the rules trust (its
date not `low`), what the record holds for that day (`day_evidence`): where the owner's phone had the
owner (the Day's stays) and where the owner's assets were reported, or the nearest day within
`NEAR_DAYS` that has any.

**The answers**, every number checked before the first line is written:

- `--accept N`: one `attribution/v1` line (RFC 0040): the scene (`ref` `{kind: scene, value: <video line
  id>#t=<start>,<end>}`, and `scene` `{video, start_s, end_s}`) bound to the place and/or the date or
  date range proposed, `method` `owner`, `draft` and `evidence` the draft, the video line and the
  transcript, `logbook_head`, tier 2. The video's line is never touched: the attribution sits beside it,
  as RFC 0038's attributions sit beside a transcript. `--place N NAME` and `--date N WHEN` accept with the
  owner's own place (a name of `places.json`, or an asset of `assets.json` by its id or name) or date
  (`1994`, `1994-07`, `1994-07-14`, `summer 1994`, `1994-06..1994-08`), or `none` to leave that part
  out. A second answer for the same scene supersedes the standing one; the same answer twice writes
  nothing (`raw_id` `<ref>@<12 hex of the answer>`).
- `--reject N`: the review's no, RFC 0037's `entity-review/v1` with `type` `scene`: `verdict`
  `different`, the scene's `ref`, the place or asset proposed as `entity` when there was one, and the
  whole proposal under `extra`. That proposal is never offered for that scene again (a later inference
  that proposes the same is held back); retract the line and it returns. On a scene with nothing
  proposed it says there is nothing to name, and the scene leaves the queue.
- `--ask N`: "ask the family": one open `task/v1` line (RFC 0016), list `videos`, saying which scene, so
  a later shared page can put the scene before the family; the scene leaves the queue until it is
  answered. Accepting it later also writes the task done.

The lock is the review's, one rule for every queue: the sitting reads the queue and asks the owner with
no lock held; `write` appends each answer's lines under the record's writer lock, one hold for a batch,
as places review's no does."""

from __future__ import annotations

import calendar
import hashlib
import json
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from ..core import assets as asset_registry
from ..core import places, sealing
from ..core.chain import Line, canonical_json, is_sealed
from ..core.store import Logbook, now_utc, retractions
from . import videos

CONFIDENCE = ("high", "medium", "low")
NEAR_DAYS = 3  # how far from a proposed day the record is searched for where anyone was
SEASONS = {
    "spring": (3, 5),
    "vår": (3, 5),
    "summer": (6, 8),
    "sommer": (6, 8),
    "autumn": (9, 11),
    "fall": (9, 11),
    "høst": (9, 11),
}
NONE = "none"


class ReviewError(ValueError):
    """An answer the queue cannot take; nothing is written."""


@dataclass(frozen=True)
class Row:
    """One scene waiting for the owner: its draft, its video, the proposal and the draft's sentences."""

    draft: Line
    video: videos.Video
    ref: str
    start: float
    end: float
    n: int
    of: int
    proposal: Mapping[str, Any] | None
    transcript: str | None
    standing: Line | None = None  # with `--answered`: the attribution an answer would supersede
    overlaps: tuple[Line, ...] = ()  # standing attributions of another scene of the file it overlaps
    refused: bool = False  # with `--asked`: its proposal was refused, so none is offered

    @property
    def id(self) -> str:
        """Stable at any head that still has the row: the scene and what is proposed."""
        text = json.dumps([self.ref, self.proposal], sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    @property
    def payload(self) -> Mapping[str, Any]:
        found = self.draft.get("payload")
        return found if isinstance(found, dict) else {}

    @property
    def extra(self) -> Mapping[str, Any]:
        found = self.payload.get("extra")
        return found if isinstance(found, dict) else {}

    @property
    def confidence(self) -> str | None:
        return str(self.proposal["confidence"]) if self.proposal and self.proposal.get("confidence") else None

    def rank(self) -> tuple[int, tuple[str, str, int], float]:
        weight = CONFIDENCE.index(self.confidence) if self.confidence in CONFIDENCE else len(CONFIDENCE)
        return (weight, self.video.order(), self.start)


@dataclass
class Queue:
    rows: list[Row]
    head: str
    confirmed: int  # scenes with a standing attribution
    rejected: int
    asked: int
    tier: int
    answered: dict[str, Line] = field(default_factory=dict)  # scene ref -> its standing attribution
    asks: dict[str, Line] = field(default_factory=dict)  # scene ref -> its open ask
    refused: dict[str, list[Any]] = field(default_factory=dict)  # scene ref -> the proposals refused


def _opened(lb: Logbook, lines: Iterable[Line]) -> list[Line]:
    """The lines as a reader shows them, a sealed one opened with this machine's identity. A sealed
    line this machine cannot open is never silently left out of the review: IdentityRequired names
    the identity it needs, and the command says so in one sentence."""
    found = []
    shut = 0
    for line in lines:
        try:
            opened = lb.opened(line)
        except (sealing.SealError, sealing.MissingExtra, OSError, ValueError):
            shut += 1
            continue
        if is_sealed(opened):
            shut += 1
            continue
        found.append(opened)
    if shut:
        raise sealing.IdentityRequired(
            f"{shut} line{'s' if shut != 1 else ''} of the videos {'are' if shut != 1 else 'is'} sealed and"
            f" {'do' if shut != 1 else 'does'} not open on this machine (RFC 0029); none at"
            f" {lb.identity_file}: pass --identity-file or set LOGBOOK_IDENTITY_FILE"
        )
    return found


def _standing(lines: Iterable[Line], gone: set[str]) -> list[Line]:
    """Not retracted, not named in a later line's `supersedes`."""
    kept = [line for line in lines if str(line["id"]) not in gone]
    replaced = {str((line.get("payload") or {}).get("supersedes")) for line in kept}
    return sorted(
        (line for line in kept if str(line["id"]) not in replaced), key=lambda line: int(line["seq"])
    )


MODES = ("open", "asked", "answered")


def read(lb: Logbook, mode: str = "open") -> Queue:
    """The queue at this head: the scenes nobody has answered (`open`); or those kept to ask the
    family (`asked`), or those already confirmed (`answered`), each by the latest draft of its scene,
    so an answer can be given or corrected."""
    with lb.index() as idx:
        head = str(lb.meta["head"])
        gone = set(retractions(idx.retractions()))
        listed = videos.standing_videos(
            _opened(lb, idx.by_kind(videos.KIND)), gone, idx.superseded(videos.KIND)
        )
        scene_drafts = [d for d in _opened(lb, idx.by_kind(videos.DRAFT_KIND)) if videos.is_scene_draft(d)]
        attributions = _opened(lb, idx.by_kind(videos.ATTRIBUTION_KIND))
        noes = _opened(lb, idx.by_kind(videos.NO_KIND))
        tasks = _opened(lb, idx.by_kind(videos.ASK_KIND))
    answered = {
        ref: line
        for line in _standing(attributions, gone)
        if (ref := _ref(line)) is not None
        and (line.get("payload") or {}).get("schema") == videos.ATTRIBUTION_SCHEMA
    }
    refused: dict[str, list[Any]] = {}
    for line in noes:
        payload = line.get("payload") or {}
        ref = _ref(line)
        if str(line["id"]) in gone or payload.get("type") != videos.SCENE or ref is None:
            continue
        extra = payload.get("extra")
        refused.setdefault(ref, []).append(extra.get("proposal") if isinstance(extra, dict) else None)
    asks = open_asks(tasks, gone)
    by_video = {v.id: v for v in listed}
    latest: dict[str, str] = {}  # video id -> the key of its latest inference
    newest: dict[str, Line] = {}  # scene ref -> its latest draft, of any inference
    kept: list[Line] = []
    for line in sorted(scene_drafts, key=lambda line: int(line["seq"])):
        scene = videos.scene_of(line)
        if scene is None or scene[0] not in by_video or str(line["id"]) in gone:
            continue
        extra = (line.get("payload") or {}).get("extra")
        latest[scene[0]] = str(extra.get("inference")) if isinstance(extra, dict) else ""
        newest[str((line.get("payload") or {})["subject"][0])] = line
        kept.append(line)
    rows: list[Row] = []
    tier = 1
    for line in kept:
        scene = videos.scene_of(line)
        assert scene is not None
        payload = line.get("payload") or {}
        extra = _dict(payload.get("extra"))
        ref = str(payload["subject"][0])
        proposal = extra["proposal"] if isinstance(extra.get("proposal"), dict) else None
        if mode == "open":
            if str(extra.get("inference")) != latest.get(scene[0]):
                continue  # an earlier inference of the file: the latest's scenes are the queue
            if ref in answered or ref in asks or proposal in refused.get(ref, []):
                continue
        elif ref not in (asks if mode == "asked" else answered) or line is not newest.get(ref):
            continue
        no = mode == "asked" and proposal is not None and proposal in refused.get(ref, [])
        if no:
            proposal = None  # refused while asked: the family's answer is awaited, the proposal is not
        tier = max(tier, int(line.get("tier") or 1))
        info = _dict(extra.get("scene"))
        evidence = [
            e for s in payload.get("segments") or [] if isinstance(s, dict) for e in s.get("evidence") or []
        ]
        transcript = next((e for e in evidence if e != scene[0]), None)
        rows.append(
            Row(
                line,
                by_video[scene[0]],
                ref,
                scene[1],
                scene[2],
                int(info.get("n") or 0),
                int(info.get("of") or 0),
                proposal,
                transcript,
                answered.get(ref) if mode == "answered" else None,
                _overlapping(answered, ref, scene),
                no,
            )
        )
    rows.sort(key=Row.rank)
    rejected = sum(1 for ref, found in refused.items() if found)
    return Queue(rows, head, len(answered), rejected, len(asks), tier, answered, asks, refused)


def _overlapping(answered: Mapping[str, Line], ref: str, scene: tuple[str, float, float]) -> tuple[Line, ...]:
    """The standing attributions of other scenes of the same file that overlap this one: a file
    inferred again under other settings cuts its scenes elsewhere, and the owner's answer stands."""
    found = []
    for other, line in answered.items():
        bound = videos.parse_scene(other)
        if (
            other != ref
            and bound is not None
            and bound[0] == scene[0]
            and bound[1] < scene[2]
            and scene[1] < bound[2]
        ):
            found.append(line)
    return tuple(found)


def _ref(line: Line) -> str | None:
    ref = (line.get("payload") or {}).get("ref")
    if isinstance(ref, dict) and ref.get("kind") == videos.SCENE and videos.parse_scene(ref.get("value")):
        return str(ref["value"])
    return None


def open_asks(tasks: Iterable[Line], gone: set[str]) -> dict[str, Line]:
    """scene ref -> the open ask for it: the latest snapshot of each ask task (RFC 0016 rule 2) when it
    is open."""
    latest: dict[str, Line] = {}
    for line in sorted(tasks, key=lambda line: int(line["seq"])):
        payload = line.get("payload") or {}
        extra = payload.get("extra")
        if str(line["id"]) in gone or payload.get("list") != videos.ASK_LIST or not isinstance(extra, dict):
            continue
        ref = extra.get(videos.SCENE)
        if isinstance(ref, str) and videos.parse_scene(ref):
            latest[ref] = line
    return {ref: line for ref, line in latest.items() if (line.get("payload") or {}).get("status") == "open"}


# -- what the owner says --------------------------------------------------------------------------------


@dataclass(frozen=True)
class When:
    first: date
    last: date
    precision: str

    def to_json(self) -> dict[str, Any]:
        return {"from": self.first.isoformat(), "to": self.last.isoformat(), "precision": self.precision}


DAY = re.compile(r"(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?\Z")


def parse_when(text: str, today: date) -> When | None:
    """The owner's date: `1994`, `1994-07`, `1994-07-14`, `summer 1994` (or the Norwegian season),
    `A..B` from the first day of A to the last of B; None for `none`. ReviewError for anything else."""
    words = " ".join(text.split()).casefold()
    if words == NONE:
        return None
    if ".." in words:
        first, last = (parse_when(side, today) for side in words.split("..", 1))
        if first is None or last is None or first.first > last.last:
            raise ReviewError(f"{text!r}: a range runs from an earlier date to a later one, A..B")
        return When(first.first, last.last, "range")
    season = re.fullmatch(r"([a-zæøå]+)\s+(\d{4})", words)
    if season is not None and season[1] in SEASONS:
        year = int(season[2])
        a, b = SEASONS[season[1]]
        return _checked(
            When(date(year, a, 1), date(year, b, calendar.monthrange(year, b)[1]), "season"), today
        )
    found = DAY.fullmatch(words)
    if found is None:
        raise ReviewError(f"{text!r} is not a date: 1994, 1994-07, 1994-07-14, summer 1994 or A..B")
    year, month, day = int(found[1]), found[2], found[3]
    try:
        if day is not None:
            when = When(date(year, int(month), int(day)), date(year, int(month), int(day)), "day")
        elif month is not None:
            m = int(month)
            when = When(date(year, m, 1), date(year, m, calendar.monthrange(year, m)[1]), "month")
        else:
            when = When(date(year, 1, 1), date(year, 12, 31), "year")
    except ValueError:
        raise ReviewError(f"{text!r} is not a date of the calendar") from None
    return _checked(when, today)


def _checked(when: When, today: date) -> When:
    if when.first > today:
        raise ReviewError(f"{when.first.isoformat()} is after today")
    return when


def find_place(
    name: str, known: Sequence[places.Place], owned: Sequence[asset_registry.Asset]
) -> dict[str, Any] | None:
    """The owner's place by name: a `places.json` name, else an asset's id or name, case aside; None
    for `none`. ReviewError naming the registries when it is neither."""
    wanted = " ".join(name.split()).casefold()
    if wanted == NONE:
        return None
    for p in known:
        if p.name.casefold() == wanted:
            return {"type": "place", "id": p.name, "registry": "logbook", "label": p.name}
    for a in owned:
        if wanted in (a.id.casefold(), a.name.casefold()):
            return {"type": "asset", "id": a.id, "registry": "logbook", "label": a.name}
    raise ReviewError(
        f"{name!r} is not a place of places.json or an asset of assets.json; add it with `logbook setup"
        " places add` or `logbook setup assets add` first"
    )


@dataclass
class Answer:
    """What the owner said about one row."""

    row: Row
    verb: str  # accept, reject, ask
    place: dict[str, Any] | None = None
    when: dict[str, Any] | None = None


@dataclass
class Written:
    row: Row
    verb: str
    line: Line | None  # None: the same answer already stood, nothing written
    text: str

    def to_json(self) -> dict[str, Any]:
        return {
            "scene": self.row.ref,
            "answer": self.verb,
            "line": None if self.line is None else str(self.line["id"]),
            "text": self.text,
        }


def plan(
    queue: Queue,
    accept: Sequence[int],
    reject: Sequence[int],
    ask: Sequence[int],
    place: Mapping[int, str],
    when: Mapping[int, str],
    known: Sequence[places.Place],
    owned: Sequence[asset_registry.Asset],
    today: date,
) -> list[Answer]:
    """Every answer checked before anything is written: each number one the queue has, no number given
    two verbs, a place of the registries, a date of the calendar, an accepted scene with something to
    bind. ReviewError, and nothing written, otherwise."""
    told: dict[int, str] = {}
    for verb, numbers in (("accept", [*accept, *place, *when]), ("reject", reject), ("ask", ask)):
        for n in numbers:
            if n < 1 or n > len(queue.rows):
                raise ReviewError(f"scene {n} is not in the queue (1 to {len(queue.rows)})")
            if told.get(n, verb) != verb:
                raise ReviewError(f"scene {n} is given --{told[n]} and --{verb}; say one")
            told[n] = verb
    answers = []
    for n, verb in sorted(told.items()):
        row = queue.rows[n - 1]
        if verb == "reject" and row.standing is not None:
            raise ReviewError(
                f"scene {n} is confirmed (#{row.standing['seq']}); a no does not undo it: --place {n} NAME or"
                f" --date {n} WHEN corrects it, `logbook repair retract {row.standing['seq']}` withdraws it"
            )
        answer = Answer(row, verb)
        if verb == "accept":
            given = (row.standing.get("payload") or {}) if row.standing is not None else (row.proposal or {})
            answer.place = given.get("place") if isinstance(given.get("place"), dict) else None
            answer.when = given.get("when") if isinstance(given.get("when"), dict) else None
            if n in place:
                answer.place = find_place(place[n], known, owned)
            if n in when:
                found = parse_when(when[n], today)
                answer.when = found.to_json() if found is not None else None
            if answer.place is None and answer.when is None:
                raise ReviewError(
                    f"scene {n}: nothing to confirm; give --place {n} NAME or --date {n} WHEN,"
                    f" or --reject {n}"
                )
        answers.append(answer)
    return answers


def write(lb: Logbook, queue: Queue, answers: Sequence[Answer]) -> list[Written]:
    """The answers' lines, through `Logbook.append`, under one hold of the writer lock: every answer was
    checked by `plan` before this writes the first."""
    written: list[Written] = []
    with lb.writer():
        for answer in answers:
            written.extend(_write(lb, queue, answer))
    return written


def _write(lb: Logbook, queue: Queue, answer: Answer) -> Iterator[Written]:
    row = answer.row
    head = str(lb.meta["head"])
    evidence = list(dict.fromkeys(e for e in (str(row.draft["id"]), row.video.id, row.transcript) if e))
    tier = max(videos.TIER, int(row.draft.get("tier") or 1), int(row.video.line.get("tier") or 1))
    now = now_utc()
    tz = str(row.video.line.get("tz") or lb.meta["timezone"])
    if answer.verb == "accept":
        payload: dict[str, Any] = {"schema": videos.ATTRIBUTION_SCHEMA}
        bound = {"place": answer.place, "when": answer.when}
        digest = hashlib.sha256(canonical_json(bound).encode("utf-8")).hexdigest()[:12]
        payload["raw_id"] = f"{row.ref}@{digest}"
        payload["ref"] = {"kind": videos.SCENE, "value": row.ref}
        payload["scene"] = {"video": row.video.id, "start_s": row.start, "end_s": row.end}
        if answer.place is not None:
            payload["place"] = answer.place
        if answer.when is not None:
            payload["when"] = answer.when
        payload.update(
            {"method": "owner", "draft": str(row.draft["id"]), "evidence": evidence, "logbook_head": head}
        )
        standing = queue.answered.get(row.ref)
        if standing is not None:
            if (standing.get("payload") or {}).get("raw_id") == payload["raw_id"]:
                yield Written(row, "accept", None, "already confirmed so; nothing written")
                return
            payload["supersedes"] = str(standing["id"])
        proposal = row.proposal or None
        payload["extra"] = {
            "proposal": proposal,
            "changed": proposal is None
            or bound != {"place": proposal.get("place"), "when": proposal.get("when")},
        }
        line = lb.append(now, "manual", videos.ATTRIBUTION_KIND, tier, payload, tz=tz)
        yield Written(row, "accept", line, f"confirmed {_bound_text(answer.place, answer.when)}")
        ask = queue.asks.get(row.ref)
        if ask is not None:
            yield _close_ask(lb, row, ask, now, tz)
    elif answer.verb == "reject":
        proposal = row.proposal
        if row.refused or (proposal is not None and proposal in queue.refused.get(row.ref, [])):
            yield Written(row, "reject", None, "already refused; nothing written")
            return
        payload = {"schema": videos.NO_SCHEMA, "type": videos.SCENE, "verdict": "different"}
        payload["ref"] = {"kind": videos.SCENE, "value": row.ref}
        payload["refs"] = [dict(payload["ref"])]
        place = proposal.get("place") if proposal else None
        if isinstance(place, dict):
            payload["entity"] = {"type": place.get("type"), "id": place.get("id"), "registry": "logbook"}
            payload["label"] = place.get("label")
        payload.update({"method": "owner", "evidence": evidence, "logbook_head": head})
        payload["extra"] = {"draft": str(row.draft["id"]), "proposal": proposal}
        line = lb.append(now, "manual", videos.NO_KIND, tier, payload, tz=tz)
        said = (
            "nothing to name: the scene leaves the queue"
            if proposal is None
            else "not so: never proposed for this scene again"
        )
        yield Written(row, "reject", line, said)
    else:
        if row.ref in queue.asks:
            yield Written(row, "ask", None, "already kept to ask the family; nothing written")
            return
        where = f"{row.video.name}, {videos.span(row.start, row.end)}"
        title = f"Ask the family where and when this was filmed: {where}"
        payload = {
            "schema": videos.ASK_SCHEMA,
            "raw_id": f"videos-ask:{row.ref}@{now}",
            "title": title,
            "status": "open",
            "list": videos.ASK_LIST,
            "modified_at": now,
            "extra": {videos.SCENE: row.ref, "draft": str(row.draft["id"]), "proposal": row.proposal},
        }
        line = lb.append(now, "manual", videos.ASK_KIND, tier, payload, tz=tz)
        yield Written(row, "ask", line, "kept to ask the family: an open task in the list videos")


def _close_ask(lb: Logbook, row: Row, ask: Line, now: str, tz: str) -> Written:
    """The ask's task written again, done: the scene is answered."""
    found = dict(ask.get("payload") or {})
    payload = {
        **found,
        "raw_id": f"videos-ask:{row.ref}@{now}",
        "status": "done",
        "completed_at": now,
        "modified_at": now,
        "supersedes": str(ask["id"]),
    }
    line = lb.append(now, "manual", videos.ASK_KIND, int(ask.get("tier") or videos.TIER), payload, tz=tz)
    return Written(row, "ask", line, "the family's question closed")


# -- what the record holds that day ------------------------------------------------------------------------


def trusted_day(row: Row) -> date | None:
    """The day the proposal names, when it names one day and the rules trust it (the date's own
    confidence not `low`: not 1 January without a time, not a stamp the frames' season contradicts):
    the only case the record's own evidence of where everyone was can be set beside it."""
    proposal = row.proposal or {}
    when = proposal.get("when")
    if proposal.get("when_confidence", proposal.get("confidence")) == "low":
        return None
    if isinstance(when, dict) and when.get("precision") == "day":
        try:
            return date.fromisoformat(str(when.get("from")))
        except ValueError:
            return None
    return None


def day_evidence(lb: Logbook, day: date) -> list[str]:
    """Where the owner and the owner's assets were that day, by the record (the Day's stays, the assets'
    positions), or on the nearest day within `NEAR_DAYS` that has any; empty when the record has none."""
    from ..core import day as day_reader

    owned = {a.id: a.name for a in asset_registry.read(lb.root)}
    for shift in sorted(range(-NEAR_DAYS, NEAR_DAYS + 1), key=abs):
        when = (day + timedelta(days=shift)).isoformat()
        with lb.index() as idx:
            located = [line for line in idx.day(when) if line.get("kind") == "location"]
        if not located:
            continue
        said = []
        try:
            page = day_reader.read(lb, when)
        except ValueError:
            page = {"timeline": []}
        for entry in page.get("timeline") or []:
            if entry.get("kind") in ("stay", "aboard") and entry.get("where"):
                said.append(
                    f"{str(entry['start_local'])[11:16]}{videos.EN_DASH}{str(entry['end_local'])[11:16]}"
                    f" {entry['where']}"
                )
        by_asset: dict[str, int] = {}
        for line in located:
            subject = (line.get("payload") or {}).get("subject")
            if isinstance(subject, str) and subject:
                by_asset[subject] = by_asset.get(subject, 0) + 1
        said += [
            f"{owned.get(a, a)}: {n} position{'s' if n != 1 else ''}" for a, n in sorted(by_asset.items())
        ]
        if not said:
            continue
        head = (
            "that day"
            if shift == 0
            else f"{when}, {_plural(abs(shift), 'day')} {'after' if shift > 0 else 'before'}"
        )
        return [f"{head} in the record: " + " · ".join(said)]
    return []


# -- what is printed ------------------------------------------------------------------------------------


def head_text(queue: Queue) -> str:
    proposed = sum(1 for r in queue.rows if r.proposal)
    blank = len(queue.rows) - proposed
    return (
        f"{_plural(proposed, 'scene')} proposed, {blank} with nothing to go on · {queue.confirmed} confirmed,"
        f" {queue.rejected} refused, {queue.asked} kept to ask the family · tier {queue.tier}"
    )


def _bound_text(place: Mapping[str, Any] | None, when: Mapping[str, Any] | None) -> str:
    parts = []
    if place:
        parts.append(f"{place.get('label') or place.get('id')} ({place.get('type')})")
    if when:
        parts.append(_when_text(when))
    return ", ".join(parts) if parts else "____"


def _when_text(when: Mapping[str, Any]) -> str:
    first, last, precision = str(when.get("from")), str(when.get("to")), when.get("precision")
    if precision == "day" or first == last:
        return first
    if precision == "month":
        return first[:7]
    if precision == "year":
        return first[:4]
    return f"{first}..{last}"


def row_lines(lb: Logbook | None, n: int, row: Row) -> Iterator[str]:
    """One scene as the queue prints it: the head row, the sentences with what they cite, the frames,
    the day's evidence when the proposal is a day."""
    confidence = row.confidence or "—"
    proposal = row.proposal or {}
    target = _bound_text(proposal.get("place"), proposal.get("when")) if row.proposal else "____"
    yield (
        f"{n:4}  [{confidence}]  {row.video.name} · scene {row.n} of {row.of} ·"
        f" {videos.span(row.start, row.end)} → {target}"
    )
    found = row.extra.get("segments")
    details: list[Any] = found if isinstance(found, list) else []
    for i, segment in enumerate(row.payload.get("segments") or []):
        if not isinstance(segment, dict):
            continue
        detail = details[i] if i < len(details) and isinstance(details[i], dict) else {}
        if detail.get("part") in ("setting", "proposed"):
            continue
        cites = []
        if detail.get("frames"):
            cites.append("frames " + ", ".join(videos.clock(float(t)) for t in detail["frames"]))
        if detail.get("speech"):
            cites.append("speech " + ", ".join(videos.span(float(a), float(b)) for a, b in detail["speech"]))
        tail = f"  [{'; '.join(cites)}]" if cites else ""
        yield f"        {segment.get('text')}{tail}"
    for frame in row.extra.get("frames") or []:
        if isinstance(frame, dict):
            signs = f"; text: {', '.join(frame.get('signs') or [])}" if frame.get("signs") else ""
            stamp = f"; stamp: {frame['stamp']}" if frame.get("stamp") else ""
            at = videos.clock(float(frame.get("offset_s") or 0))
            yield f"        frame {at}: {frame.get('description')}{signs}{stamp}"
    for line in row.overlaps:
        payload = line.get("payload") or {}
        bound = videos.parse_scene((payload.get("ref") or {}).get("value"))
        if bound is not None:
            target = _bound_text(payload.get("place"), payload.get("when"))
            yield f"        overlaps a scene you confirmed, {videos.span(bound[1], bound[2])} \u2192 {target}"
    day = trusted_day(row)
    if day is not None and lb is not None:
        evidence = day_evidence(lb, day)
        yield (
            f"        {evidence[0]}"
            if evidence
            else f"        nothing in the record within {NEAR_DAYS} days of {day.isoformat()}"
        )
    yield f"        draft …{str(row.draft['id'])[-8:]}"


def to_json(queue: Queue) -> dict[str, Any]:
    return {
        "head": queue.head,
        "confirmed": queue.confirmed,
        "rejected": queue.rejected,
        "asked": queue.asked,
        "tier": queue.tier,
        "rows": [
            {
                "n": n,
                "id": row.id,
                "scene": row.ref,
                "video": row.video.id,
                "file": row.video.name,
                "start_s": row.start,
                "end_s": row.end,
                "of": [row.n, row.of],
                "proposal": row.proposal,
                "draft": str(row.draft["id"]),
                "segments": row.payload.get("segments"),
                "frames": row.extra.get("frames"),
            }
            for n, row in enumerate(queue.rows, 1)
        ],
    }


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _plural(n: int, noun: str) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {noun}s"
