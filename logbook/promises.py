"""`logbook promises`: the commitments the record's own words suggest, proposed and never asserted.

A promise here is a sentence in a `transcript/v1` (RFC 0004) or `note/v1` (RFC 0010) line that reads
like one: first-person future ("I'll send", "we will", "ich schicke", "ich melde mich"), first-person
obligation ("I need to", "ich muss") or an offer ("let me"), in English and German, found by rules
alone. No model runs and no socket opens. Each proposal carries the day, the line it was read in,
the speaker when the transcript resolves one (RFC 0006), the sentence as written and a due hint when
a date phrase is in it ("by Friday", "bis Montag", "next week"), resolved against the day it was
said. Everything here is a draft (ADR 0013.7, RFC 0007 rule 3): the command prints proposals, and
the owner closes one with `promises done <id>`, which appends a `task/v1` line (RFC 0016) marked
done; nothing is ever rewritten.

The extractor is a value, not the command. `extract(lb, since, extractor=RULES)` takes anything
with a `name`, a `version` and `__call__(text) -> list[Match]`; the rules are the first such thing
and a local model can be the next, and the report, the ids and `done` stay the same. A proposal's
id is a digest of the origin line and the sentence it quotes, so two extractors that quote the same
sentence agree on it and a close written against one holds for the other."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import PurePosixPath
from typing import Any, Protocol

from . import policy, present, sealing
from .adapters.transcript import SPEAKER, Turn, parse_text
from .chain import Line
from .index import local_date
from .resolve import Identity, Ref, identities_from
from .store import Logbook, retractions

TRANSCRIPT = "transcript"
NOTE = "note"
TASK = "task"
TASK_SCHEMA = "task/v1"
TASK_TIER = 2
TASK_LIST = "promises"
RAW_PREFIX = "promise:"
CERTAINTY = "inferred"  # RFC 0007: the words were read into a commitment, never stated as one
OWED_BY_OWNER, OWED_TO_OWNER = "owed_by_owner", "owed_to_owner"
FUTURE, OBLIGATION, OFFER = "future", "obligation", "offer"
OWNER_LABELS = frozenset({"me", "i", "ich", "owner", "self"})  # a diarizer's word for the owner
DIARIZER = re.compile(
    r"^(?:speaker|sprecher|spk)\s*[A-Z0-9]{1,2}$", re.IGNORECASE
)  # `Speaker A`, `Speaker 2`
QUOTE_WIDTH = 100
ID_WIDTH = 16
CONTEXT = 2  # sentences either side of a candidate that a judge sees
THRESHOLD = 0.6  # a judged candidate shows when it is a commitment at this confidence or above
OWNER, UNKNOWN = "owner", "unknown"  # a judgement's words for the owner and for nobody it could name


# -- the matches ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Match:
    """One sentence an extractor reads as a promise: the sentence as written, the words that made it
    one, its class (`future`, `obligation`, `offer`), its language, the date phrase in it when there
    is one, and the day the extractor resolved that phrase to when it did so itself (`YYYY-MM-DD`;
    the rules leave it None and `due_of` resolves the phrase against the day it was said)."""

    quote: str
    cue: str
    phrase_class: str
    language: str
    due_phrase: str | None = None
    due: str | None = None


class Extractor(Protocol):
    """What the command needs from an extractor; the rules below are one, a local model is another."""

    name: str
    version: str

    def __call__(self, text: str) -> list[Match]: ...


_NEG_EN = r"(?!\s+(?:not|never)\b)"
_NEG_DE = r"(?!\s+(?:nicht|nie|niemals)\b)"
_CUES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(
            r"\b(?:I|we)(?:['\u2019]ll| will| shall|['\u2019]m going to| am going to|['\u2019]re going to"
            r"| are going to)\b" + _NEG_EN,
            re.IGNORECASE,
        ),
        FUTURE,
        "en",
    ),
    (re.compile(r"\bI promise\b", re.IGNORECASE), FUTURE, "en"),
    (
        re.compile(
            r"\b(?:I|we)(?:['\u2019]ve)? (?:need to|have to|must|got to|ought to)\b" + _NEG_EN, re.IGNORECASE
        ),
        OBLIGATION,
        "en",
    ),
    (re.compile(r"\blet me\b(?!\s+know\b)", re.IGNORECASE), OFFER, "en"),
    (
        re.compile(
            r"\b(?:ich (?:werde|schicke|sende|melde mich|kümmere mich|rufe|bringe|liefere)"
            r"|wir (?:werden|schicken|senden|melden uns|kümmern uns|rufen|bringen|liefern))\b" + _NEG_DE,
            re.IGNORECASE,
        ),
        FUTURE,
        "de",
    ),
    (re.compile(r"\b(?:ich muss|wir müssen)\b" + _NEG_DE, re.IGNORECASE), OBLIGATION, "de"),
)

_SENTENCE_END = re.compile(r"(?<=[^0-9][.!?])\s+")
_DIGEST = re.compile(r"[0-9a-f]{64}")  # an attachment's name (SPEC §1.1)
_SPACE = re.compile(r"\s+")


def sentences(text: str) -> list[str]:
    """The sentences of a turn or a note: split at a full stop, `!` or `?` that does not follow a
    digit (`bis 20. Juni` stays whole) and at every line break, whitespace collapsed."""
    out = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        for piece in _SENTENCE_END.split(raw):
            sentence = _SPACE.sub(" ", piece).strip()
            if sentence:
                out.append(sentence)
    return out


class Rules:
    """The rule extractor: one `Match` per sentence that carries a first-person cue, is not negated
    right after it and is not a question. The first cue in a sentence decides its class."""

    name = "rules"
    version = "1"
    languages = ("en", "de")

    def __call__(self, text: str) -> list[Match]:
        found = []
        for sentence in sentences(text):
            if sentence.endswith("?"):
                continue
            first: tuple[int, re.Match[str], str, str] | None = None
            for pattern, phrase_class, language in _CUES:
                m = pattern.search(sentence)
                if m and (first is None or m.start() < first[0]):
                    first = (m.start(), m, phrase_class, language)
            if first is None:
                continue
            _start, m, phrase_class, language = first
            found.append(Match(sentence, m.group(0), phrase_class, language, due_phrase(sentence)))
        return found


RULES = Rules()


def find(text: str) -> list[Match]:
    """The rules applied to one text."""
    return RULES(text)


# -- the due hints -------------------------------------------------------------------------------------

_WEEKDAYS_EN = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_WEEKDAYS_DE = ("montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag")
_WEEKDAY_INDEX = (
    {name: i for i, name in enumerate(_WEEKDAYS_EN)}
    | {name: i for i, name in enumerate(_WEEKDAYS_DE)}
    | {"sonnabend": 5}
)
_MONTHS = {
    name: i + 1
    for i, names in enumerate(
        (
            ("january", "jan", "januar", "jänner"),
            ("february", "feb", "februar"),
            ("march", "mar", "märz", "maerz", "mär"),
            ("april", "apr"),
            ("may", "mai"),
            ("june", "jun", "juni"),
            ("july", "jul", "juli"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct", "oktober", "okt"),
            ("november", "nov"),
            ("december", "dec", "dezember", "dez"),
        )
    )
    for name in names
}
_NUMBERS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10,
    "ein": 1, "einem": 1, "einer": 1, "eine": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5,
    "fuenf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10,
}  # fmt: skip
_PREP_EN = r"(?:(?:by|before|until|till|on|for) )?"
_PREP_DE = r"(?:(?:bis zum|bis|am|vor|spätestens|spätestens am|spätestens bis) )?"
_WEEKDAY_EN = "|".join(_WEEKDAYS_EN)
_WEEKDAY_DE = "|".join((*_WEEKDAYS_DE, "sonnabend"))
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))
_NUMBER = "|".join((r"\d+", *sorted(_NUMBERS, key=len, reverse=True)))

# (pattern, resolver name); the first that matches the sentence wins, so the specific come first
_DUE: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), name)
    for pattern, name in (
        (r"\b(?:(?:by|before|until|till) )?(?:the )?end of (?:the |this )?week\b", "end_of_week"),
        (r"\b" + _PREP_DE + r"ende der woche\b", "end_of_week"),
        (r"\b(?:(?:by|before|until|till|for) )?next week\b", "next_week"),
        (r"\b(?:(?:bis|für) )?(?:nächste|naechste|kommende) woche\b", "next_week"),
        (r"\bthis week\b", "end_of_week"),
        (r"\bdiese woche\b", "end_of_week"),
        (r"\b(?:(?:by|before|until|till) )?next month\b", "next_month"),
        (r"\b(?:bis )?(?:nächsten|naechsten|kommenden) monat\b", "next_month"),
        (r"\bin (" + _NUMBER + r") (days?|weeks?|months?|tagen?|wochen?|monaten?)\b", "in_units"),
        (r"\b" + _PREP_EN + r"(?:next |this )?(" + _WEEKDAY_EN + r")\b", "weekday"),
        (
            r"\b" + _PREP_DE + r"(?:nächsten |naechsten |kommenden |diesen )?(" + _WEEKDAY_DE + r")\b",
            "weekday",
        ),
        (r"\b(?:by )?(?:tonight|today|eod|end of (?:the )?day|close of business|cob)\b", "same_day"),
        (r"\bheute(?: (?:abend|morgen|nachmittag|mittag|früh))?\b", "same_day"),
        (r"\b(?:by )?(?:the day after tomorrow)\b", "two_days"),
        (r"\bübermorgen\b", "two_days"),
        (r"\b(?:by )?tomorrow\b", "next_day"),
        (r"\b(?:bis )?morgen\b", "next_day"),
        (r"\b" + _PREP_EN + r"(" + _MONTH + r")\.? (\d{1,2})(?:st|nd|rd|th)?\b(?:,? (\d{4}))?", "month_day"),
        (
            r"\b" + _PREP_EN + r"(?:the )?(\d{1,2})(?:st|nd|rd|th)? (?:of )?(" + _MONTH + r")\b"
            r"(?:,? (\d{4}))?",
            "day_month",
        ),
        (r"\b" + _PREP_DE + r"(\d{1,2})\. ?(" + _MONTH + r")\b\.?(?: (\d{4}))?", "day_month"),
        (r"\b" + _PREP_DE + r"(\d{1,2})\.(\d{1,2})\.(?:(\d{4}|\d{2})\b)?", "numeric_dm"),
        (r"\b" + _PREP_EN + r"the (\d{1,2})(?:st|nd|rd|th)\b", "day_of_month"),
        (r"\b(?:am|bis zum|bis|vor dem) (\d{1,2})\.(?!\d)", "day_of_month"),
    )
)  # fmt: skip


def due_phrase(sentence: str) -> str | None:
    """The date phrase in a sentence, as written, or None."""
    found = _due_match(sentence)
    return None if found is None else found[0].group(0).strip()


def _due_match(sentence: str) -> tuple[re.Match[str], str] | None:
    for pattern, name in _DUE:
        m = pattern.search(sentence)
        if m:
            return m, name
    return None


def due_of(phrase: str, day: date) -> date | None:
    """The day a date phrase most plainly names, counted from `day`, the day it was said: a weekday
    is the next one strictly after that day; `next week` its Monday; `this week` and `end of the
    week` the Friday on or after it; `in two weeks` fourteen days on; a month and a
    day the next such date; `the 5th` the next fifth. None when the words name no day."""
    found = _due_match(phrase)
    if found is None:
        return None
    m, name = found
    groups = m.groups()
    try:
        if name == "weekday":
            return _next_weekday(day, _WEEKDAY_INDEX[groups[0].casefold()])
        if name == "next_week":
            return day + timedelta(days=7 - day.weekday())
        if name == "end_of_week":
            return day + timedelta(days=(4 - day.weekday()) % 7)
        if name == "next_month":
            return _add_months(day.replace(day=1), 1)
        if name == "same_day":
            return day
        if name == "next_day":
            return day + timedelta(days=1)
        if name == "two_days":
            return day + timedelta(days=2)
        if name == "in_units":
            count, unit = groups[0].casefold(), groups[1].casefold()
            n = int(count) if count.isdigit() else _NUMBERS[count]
            if unit.startswith(("day", "tag")):
                return day + timedelta(days=n)
            if unit.startswith(("week", "woche")):
                return day + timedelta(days=7 * n)
            return _add_months(day, n)
        if name == "month_day":
            return _month_day(day, _MONTHS[groups[0].casefold()], int(groups[1]), groups[2])
        if name == "day_month":
            return _month_day(day, _MONTHS[groups[1].casefold()], int(groups[0]), groups[2])
        if name == "numeric_dm":
            year = groups[2]
            if year is not None and len(year) == 2:
                year = str(day.year)[:2] + year
            return _month_day(day, int(groups[1]), int(groups[0]), year)
        if name == "day_of_month":
            return _next_day_of_month(day, int(groups[0]))
    except (ValueError, KeyError):  # the 31st of June, month 13: the words name no day
        return None
    return None


def _next_weekday(day: date, weekday: int) -> date:
    ahead = (weekday - day.weekday()) % 7 or 7
    return day + timedelta(days=ahead)


def _add_months(day: date, n: int) -> date:
    month = day.month - 1 + n
    year, month = day.year + month // 12, month % 12 + 1
    last = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(day.day, last))


def _month_day(day: date, month: int, dom: int, year: str | None) -> date:
    if year is not None:
        return date(int(year), month, dom)
    found = date(day.year, month, dom)
    return found if found >= day else date(day.year + 1, month, dom)


def _next_day_of_month(day: date, dom: int) -> date:
    first = day.replace(day=1)
    for months in range(0, 13):
        candidate = _add_months(first, months)
        try:
            found = candidate.replace(day=dom)
        except ValueError:
            continue
        if found > day:
            return found
    raise ValueError(dom)


# -- the proposals -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Speaker:
    """Who said it: the record's name for them and their person id when it resolves the speaker
    (RFC 0006), the label the source wrote, and whether they are the owner."""

    label: str | None
    spoken: str | None
    person: str | None
    owner: bool

    def to_json(self) -> dict[str, Any]:
        return {"label": self.label, "spoken": self.spoken, "person": self.person, "owner": self.owner}

    def display(self) -> str:
        if self.owner:
            return "you"
        return self.label or self.spoken or "?"


@dataclass(frozen=True)
class Said:
    """One sentence of the text around a candidate, with who said it as the report names them
    (`you`, a resolved label, a diarizer's label, `?`)."""

    speaker: str
    text: str


@dataclass(frozen=True)
class Judgement:
    """A local model's reading of one candidate (`logbook.judge`): whether it is a commitment, who
    made it (`owner`, a name, `unknown`), to whom, what in a line, when it is due (`YYYY-MM-DD` or
    None) and how sure the model was (0 to 1); with the engine and model that read it and when, since
    a judgement is never redone and the model may change."""

    is_commitment: bool
    by: str
    to: str
    what: str
    due: str | None
    confidence: float
    model: str
    judged_at: str
    engine: str = ""

    def shows(self, threshold: float = THRESHOLD) -> bool:
        return self.is_commitment and self.confidence >= threshold

    def to_json(self) -> dict[str, Any]:
        return {
            "is_commitment": self.is_commitment,
            "by": self.by,
            "to": self.to,
            "what": self.what,
            "due": self.due,
            "confidence": self.confidence,
            "engine": self.engine,
            "model": self.model,
            "judged_at": self.judged_at,
        }


@dataclass(frozen=True)
class Proposal:
    """One promise as proposed: where it was read, who said it, what, and when it may be due; the
    `CONTEXT` sentences before and after it in the same transcript or note, across turns, and the
    names the record resolves in that line (its speakers and participants, the owner among them)."""

    id: str
    day: str
    at: str
    line: str
    seq: int
    kind: str
    source: str
    title: str | None
    speaker: Speaker | None
    direction: str | None
    match: Match
    due: str | None
    closed_by: str | None = None
    before: tuple[Said, ...] = ()
    after: tuple[Said, ...] = ()
    names: tuple[str, ...] = ()
    judgement: Judgement | None = None

    @property
    def status(self) -> str:
        return "done" if self.closed_by else "open"

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "closed_by": self.closed_by,
            "day": self.day,
            "at": self.at,
            "line": self.line,
            "seq": self.seq,
            "kind": self.kind,
            "source": self.source,
            "title": self.title,
            "speaker": None if self.speaker is None else self.speaker.to_json(),
            "direction": self.direction,
            "certainty": CERTAINTY,
            "language": self.match.language,
            "cue": self.match.cue,
            "class": self.match.phrase_class,
            "quote": self.match.quote,
            "due": None if self.match.due_phrase is None and self.due is None else {
                "phrase": self.match.due_phrase,
                "date": self.due,
            },
            "judgement": None if self.judgement is None else self.judgement.to_json(),
        }  # fmt: skip


@dataclass(frozen=True)
class Report:
    """What one run proposed: the proposals in day order, what was skipped and by which extractor."""

    proposals: list[Proposal]
    skipped: dict[str, int]
    extractor: dict[str, Any]
    since: str | None
    owner: str | None = None  # the owner's label, as the record resolves it

    @property
    def unjudged(self) -> list[Proposal]:
        return [p for p in self.proposals if p.judgement is None]


def with_judgements(report: Report, judgements: Mapping[str, Judgement]) -> Report:
    """The report with each proposal carrying the judgement kept for its id, when there is one."""
    proposals = [
        replace(p, judgement=judgements[p.id]) if p.id in judgements else p for p in report.proposals
    ]
    return replace(report, proposals=proposals)


def proposal_id(origin: str, quote: str) -> str:
    """The id of a proposal: a digest of the origin line's id and the quoted sentence, case and
    whitespace aside, so the same sentence found twice, by two extractors, is one proposal."""
    normal = _SPACE.sub(" ", quote).strip().casefold()
    return hashlib.sha256(f"{origin}\n{normal}".encode()).hexdigest()[:ID_WIDTH]


def describe(extractor: Extractor) -> dict[str, Any]:
    out: dict[str, Any] = {"name": extractor.name, "version": extractor.version}
    languages = getattr(extractor, "languages", None)
    if isinstance(languages, Sequence) and not isinstance(languages, str):
        out["languages"] = [str(lang) for lang in languages]
    return out


def extract(lb: Logbook, since: str | None = None, extractor: Extractor = RULES) -> Report:
    """Every proposal in the transcript and note lines standing (not retracted, not superseded)
    whose local day is `since` or later, read through the index; closed ones carry the task line
    that closed them. Nothing is written."""
    tz = str(lb.meta["timezone"])
    with lb.index() as idx:
        marks = idx.retractions()
        retracted = retractions(marks)
        identities = identities_from([*marks, *idx.resolutions()])
        superseded = {*idx.superseded(TRANSCRIPT), *idx.superseded(NOTE)}
        lines = [
            line
            for line in [*idx.by_kind(TRANSCRIPT, since, None), *idx.by_kind(NOTE, since, None)]
            if str(line["id"]) not in retracted and str(line["id"]) not in superseded
        ]
        closed = closes(idx.by_kind(TASK), retracted)
    owner = present.owner_of(
        str(lb.meta.get("owner_id") or ""),
        [str(e) for e in lb.meta.get("owner_emails") or [] if isinstance(e, str)],
        policy.owner_aliases(lb.root),
        identities,
    )
    owner_label = _owner_label(owner, identities)
    skipped: dict[str, int] = {}
    proposals: list[Proposal] = []
    seen: set[str] = set()
    for line in lines:
        payload = line.get("payload") or {}
        participants = payload.get("participants")
        participants = participants if isinstance(participants, list) else []
        known = _known(participants, identities, owner)
        if line.get("kind") == TRANSCRIPT:
            turns = turns_of(lb, line)
            if turns is None:
                skipped["transcripts_without_text"] = skipped.get("transcripts_without_text", 0) + 1
                continue
            turns = relabel(turns, known)
            spoken_by = {
                turn.speaker: speaker_of(turn.speaker, participants, identities, owner, owner_label)
                for turn in turns
            }
        else:
            text = payload.get("text")
            turns = relabel([Turn(None, text)] if isinstance(text, str) else [], known)
            spoken_by = {
                turn.speaker: speaker_of(turn.speaker, participants, identities, owner, owner_label)
                for turn in turns
                if turn.speaker is not None
            }
            spoken_by[None] = Speaker(  # a note is the owner's, but for the speakers its text names
                owner_label, None, next(iter(sorted(owner.entities)), None) or None, True
            )
        title = payload.get("title")
        day = local_date(str(line["at"]), tz)
        names = _names(participants, spoken_by, identities, owner, owner_label)
        said = [
            Said(spoken_by[turn.speaker].display(), sentence)
            for turn in turns
            for sentence in sentences(turn.text)
        ]
        at_sentence = 0
        for turn in turns:
            speaker = spoken_by[turn.speaker]
            own = sentences(turn.text)
            for match in extractor(turn.text):
                pid = proposal_id(str(line["id"]), match.quote)
                if pid in seen:
                    continue
                seen.add(pid)
                where = at_sentence + own.index(match.quote) if match.quote in own else None
                before = () if where is None else tuple(said[max(0, where - CONTEXT) : where])
                after = () if where is None else tuple(said[where + 1 : where + 1 + CONTEXT])
                due = match.due
                if due is None and match.due_phrase:
                    resolved = due_of(match.due_phrase, date.fromisoformat(day))
                    due = None if resolved is None else resolved.isoformat()
                proposals.append(
                    Proposal(
                        pid,
                        day,
                        str(line["at"]),
                        str(line["id"]),
                        int(line["seq"]),
                        str(line["kind"]),
                        str(line.get("source") or ""),
                        str(title) if isinstance(title, str) and title else None,
                        speaker,
                        _direction(speaker),
                        match,
                        due,
                        closed.get(pid),
                        before,
                        after,
                        names,
                    )
                )
            at_sentence += len(own)
    proposals.sort(key=lambda p: (p.day, p.at, p.seq))
    return Report(proposals, skipped, describe(extractor), since, owner_label)


def _direction(speaker: Speaker) -> str | None:
    if speaker.owner:
        return OWED_BY_OWNER
    if speaker.person is not None:
        return OWED_TO_OWNER
    return None


def _names(
    participants: Sequence[Any],
    spoken_by: Mapping[str | None, Speaker],
    identities: Mapping[Ref, Identity],
    owner: present.Owner,
    owner_label: str | None,
) -> tuple[str, ...]:
    """The names the record resolves in one line: every speaker's and participant's label when a
    person is behind it, the owner's included; sorted, each once."""
    found = {who.label for who in spoken_by.values() if who.label and (who.person or who.owner)}
    for participant in participants:
        name = participant.get("name") if isinstance(participant, dict) else None
        if isinstance(name, str) and name.strip():
            who = speaker_of(name, participants, identities, owner, owner_label)
            if who.label and (who.person or who.owner):
                found.add(who.label)
    return tuple(sorted(found))


def _known(
    participants: Sequence[Any], identities: Mapping[Ref, Identity], owner: present.Owner
) -> Callable[[str], bool]:
    """Whether a label before a colon names someone: a participant of the line, the owner by any of
    their names or a diarizer's word for them, or a person the record resolves by that name."""
    names = {
        present._normal(p["name"])
        for p in participants
        if isinstance(p, dict) and isinstance(p.get("name"), str)
    }

    def known(label: str) -> bool:
        normal = present._normal(label)
        if normal in names or normal in OWNER_LABELS or normal in owner.names:
            return True
        return present._by_name(label, identities)[0] is not None

    return known


def _owner_label(owner: present.Owner, identities: Mapping[Ref, Identity]) -> str | None:
    labels = sorted(
        who.label
        for ref, who in identities.items()
        if who.label and (ref in owner.refs or who.entity in owner.entities)
    )
    return labels[0] if labels else None


def speaker_of(
    spoken: str | None,
    participants: Sequence[Any],
    identities: Mapping[Ref, Identity],
    owner: present.Owner,
    owner_label: str | None = None,
) -> Speaker:
    """The speaker behind a source's label: the participant of that name, through the refs the
    source gave for them (email, phone, provider id), else the one person the record labels by that
    name (as the with module reads a transcript); `me` and the owner's own names are the owner;
    `Speaker A` and a name nobody resolves stay as spoken, with no person."""
    if spoken is None:
        return Speaker(None, None, None, False)
    normal = present._normal(spoken)
    if normal in OWNER_LABELS or normal in owner.names:
        return Speaker(owner_label, spoken, next(iter(sorted(owner.entities)), None), True)
    person, label = None, None
    for participant in participants:
        if not isinstance(participant, dict):
            continue
        name = participant.get("name")
        if not isinstance(name, str) or present._normal(name) != normal:
            continue
        for kind, field in (("email", "email"), ("phone", "phone"), ("provider_id", "provider_id")):
            value = participant.get(field)
            if not isinstance(value, str) or not value:
                continue
            ref = (kind, value)
            if ref in owner.refs:
                return Speaker(owner_label, spoken, next(iter(sorted(owner.entities)), None), True)
            person, label = present._resolve(ref, identities)
            if person:
                break
        if person:
            break
    if person is None:
        person, label = present._by_name(spoken, identities)
    if person is not None and person in owner.entities:
        return Speaker(owner_label or label, spoken, person, True)
    return Speaker(label if person else None, spoken, person, False)


def relabel(turns: Sequence[Turn], known: Callable[[str], bool]) -> list[Turn]:
    """The turns with the speakers their own text names: a line that begins `Speaker 2:` or
    `<a name the record knows>:` starts a turn of that speaker, whatever label the source gave the
    turn (a diarizer's `me` on a mixed segment, or a note, which is the owner's otherwise); a line
    that begins with any other word before a colon (`Plan:`) is text. `known(label)` says whether a
    label is a participant, the owner or a person the record resolves."""
    out: list[Turn] = []
    for turn in turns:
        current: Turn | None = None
        for raw in turn.text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            m = SPEAKER.match(raw)
            label = m.group(1).strip() if m else None
            if label is not None and (DIARIZER.match(label) or known(label)):
                current = Turn(label, m.group(2).strip() if m else "")
                out.append(current)
                continue
            if current is None:
                current = Turn(turn.speaker, raw)
                out.append(current)
            else:
                current = Turn(current.speaker, f"{current.text}\n{raw}")
                out[-1] = current
    return [turn for turn in out if turn.text.strip()]


def turns_of(lb: Logbook, line: Line) -> list[Turn] | None:
    """The speaker turns of a transcript line's text from the attachment store, by its media type:
    WebVTT and SRT cues, Granola's JSON segments, or `Speaker: text` prose and plain text (the file
    adapter's own parsers). None when the line names no text or the file is not in the store."""
    content = (line.get("payload") or {}).get("content")
    if not isinstance(content, dict):
        return None
    sha256 = content.get("sha256")
    rel = PurePosixPath(content["path"]) if isinstance(content.get("path"), str) else None
    if isinstance(sha256, str) and _DIGEST.fullmatch(sha256):
        path = lb.root / "attachments" / sha256
    elif rel is not None and rel.parts and not rel.is_absolute() and ".." not in rel.parts:
        path = lb.root.joinpath(*rel.parts)  # inside the record, never beyond it
    else:
        return None
    if not path.is_file():
        return None
    try:
        in_store = path.parent == lb.root / "attachments"  # opened with the identity when sealed
        data = lb.attachment_bytes(path.name) if in_store else path.read_bytes()
        text = data.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError, sealing.SealError):
        return None
    media = str(content.get("media_type") or "").split(";")[0].strip().casefold()
    if media == "text/vtt":
        return parse_text(text, "vtt").turns
    if media in ("application/x-subrip", "text/srt"):
        return parse_text(text, "srt").turns
    if media == "application/json":
        return _json_turns(text)
    return parse_text(text, "text").turns


def _json_turns(text: str) -> list[Turn]:
    """Granola's segments (`{speaker: {name|diarization_label|attribution}, text}`), or any JSON
    object carrying such a list under `segments` or `turns`; anything else has no turns."""
    try:
        data = json.loads(text)
    except ValueError:
        return []
    if isinstance(data, dict):
        data = data.get("segments") or data.get("turns") or []
    if not isinstance(data, list):
        return []
    turns = []
    for segment in data:
        if not isinstance(segment, dict):
            continue
        said = segment.get("text")
        if not isinstance(said, str) or not said.strip():
            continue
        turns.append(Turn(_json_label(segment.get("speaker")), said))
    return turns


def _json_label(speaker: object) -> str | None:
    if isinstance(speaker, str):
        return speaker.strip() or None
    if not isinstance(speaker, dict):
        return None
    for key in ("name", "diarization_label", "attribution", "label"):
        value = speaker.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


# -- the close -----------------------------------------------------------------------------------------


def closes(tasks: Iterable[Line], retracted: Mapping[str, Line]) -> dict[str, str]:
    """promise id → the id of the task line that closes it: the latest standing `task/v1` line
    written for that promise (`extra.promise`), when its status is `done` or `cancelled` (RFC 0016
    rule 2: the newest snapshot is the task's state)."""
    latest: dict[str, tuple[int, Line]] = {}
    for line in tasks:
        if str(line["id"]) in retracted:
            continue
        payload = line.get("payload") or {}
        extra = payload.get("extra")
        promise = extra.get("promise") if isinstance(extra, dict) else None
        if not isinstance(promise, str):
            continue
        seq = int(line["seq"])
        if promise not in latest or seq > latest[promise][0]:
            latest[promise] = (seq, line)
    return {
        promise: str(line["id"])
        for promise, (_seq, line) in latest.items()
        if (line.get("payload") or {}).get("status") in ("done", "cancelled")
    }


def draft_done(
    proposal: Proposal, at: str, extractor: Mapping[str, Any], note: str | None = None
) -> dict[str, Any]:
    """The `task/v1` payload that marks a proposal done at `at` (RFC 0016): the sentence as its
    title, status `done`, the due hint as its `due`, `list` `promises`, the owner's note, and under
    `extra` the proposal's id, origin line, speaker and extractor, so `--open` knows it and a reader
    can trace it back."""
    payload: dict[str, Any] = {
        "schema": TASK_SCHEMA,
        "raw_id": f"{RAW_PREFIX}{proposal.id}@{at}",
        "title": proposal.match.quote,
        "status": "done",
    }
    if proposal.due:
        payload["due"] = proposal.due
    payload["completed_at"] = at
    payload["list"] = TASK_LIST
    if note:
        payload["notes"] = note
    extra: dict[str, Any] = {"promise": proposal.id, "origin": proposal.line}
    speaker = proposal.speaker
    if speaker is not None and (speaker.label or speaker.spoken):
        extra["speaker"] = speaker.label or speaker.spoken
    extra["extractor"] = dict(extractor)
    payload["extra"] = extra
    return payload


# -- the text -------------------------------------------------------------------------------------------


def rows(
    report: Report,
    proposals: Sequence[Proposal],
    clock: Any,
    open_only: bool = False,
    judged_only: bool = False,
    judge: Mapping[str, Any] | None = None,
) -> list[str]:
    """`logbook promises` as text: a header that says these are proposals, one row per proposal
    (day, time, who, the sentence, the due hint with a `?`, the judgement when there is one —
    the confidence, whom it is to, `no` for a judged non-commitment — `done` when closed, the id),
    and what was skipped. With `judged_only` the header counts the candidates left unjudged and
    names the flags; `judge` is what a `--judge` run just did. `clock(at)` formats an instant as
    the record's wall clock."""
    since = f" since {report.since}" if report.since else ""
    unjudged = len(report.unjudged)
    out: list[str] = []
    if judge is not None and judge.get("judged"):
        out.append(
            f"judged {_plural(int(judge['judged']), 'candidate')} with {judge['engine']} ({judge['model']})"
        )
    if not proposals:
        if judged_only and report.proposals:
            out.append(
                f"no judged promises{since}; {_plural(len(report.proposals), 'candidate')}"
                + (f", {unjudged} unjudged: run `logbook promises --judge`" if unjudged else "")
                + ", or `logbook promises --all` for every candidate"
            )
        elif open_only and report.proposals:
            out.append(f"no open promises proposed{since}; {_plural(len(report.proposals), 'proposal')} done")
        else:
            out.append(f"no promises proposed{since}")
    else:
        if judged_only:
            head = _plural(len(proposals), "judged promise") + since
            head += f" (a commitment at confidence {THRESHOLD:g} or above"
            if judge is not None and judge.get("engine"):
                head += f", read by {judge['engine']}"
            head += ")"
            if unjudged:
                head += f", {_plural(unjudged, 'candidate')} unjudged (`--judge`)"
            head += "; `--all` shows every candidate; confirm one with `logbook promises done <id>`"
        else:
            head = _plural(len(proposals), "proposed promise") + since
            head += ", read by rules, not facts; confirm one with `logbook promises done <id>`"
        out.append(head)
        who_width = min(24, max(len(p.speaker.display() if p.speaker else "?") for p in proposals))
        for p in proposals:
            who = p.speaker.display() if p.speaker else "?"
            quote = p.match.quote
            if len(quote) > QUOTE_WIDTH:
                quote = quote[: QUOTE_WIDTH - 1].rstrip() + "…"
            out.append(f"  {p.day}  {clock(p.at)}  {who:<{who_width}}  “{quote}”{_tail(p)}  {p.id}")
    missing = report.skipped.get("transcripts_without_text", 0)
    if missing:
        out.append(f"  {_plural(missing, 'transcript')} whose text is not in the attachment store skipped")
    if judge is not None and judge.get("unparsed"):
        out.append(
            f"  {_plural(int(judge['unparsed']), 'candidate')} could not be judged (no verdict in the"
            " model's answer); the next `--judge` tries again"
        )
    return out


def _tail(p: Proposal) -> str:
    """After the quote: the due hint (the judgement's day when it gave one, else the rules' with the
    phrase), the judgement, `done`."""
    tail = ""
    verdict = p.judgement
    if verdict is not None and verdict.due:
        tail += f"  due {verdict.due}?"
    elif p.due:
        tail += f"  due {p.due}?"
        if p.match.due_phrase:
            tail += f" ({p.match.due_phrase})"
    elif p.match.due_phrase:
        tail += f"  due? ({p.match.due_phrase})"
    if verdict is not None:
        if not verdict.is_commitment:
            tail += f"  no {verdict.confidence:g}"
        else:
            tail += f"  {verdict.confidence:g}"
            who = p.speaker.display() if p.speaker else "?"
            by = "you" if verdict.by == OWNER else verdict.by
            if by != UNKNOWN and by != who:
                tail += f" by {by}"
            if verdict.to != UNKNOWN:
                tail += f" to {'you' if verdict.to == OWNER else verdict.to}"
    if p.closed_by:
        tail += "  done"
    return tail


def _plural(n: int, noun: str) -> str:
    return f"{n:,} {noun if n == 1 else noun + 's'}"
