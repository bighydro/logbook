"""`logbook day reflect DAY`: the owner closes a day by talking, and what they say is taken up.

A reflection is a few sentences at the end of the day, in the owner's words: typed (`--text`), a
recording heard on this machine (`--audio FILE`, the `openlogbook[transcribe]` extra, as `derive
transcripts` hears a voice memo), the microphone on macOS (`--mic SECONDS`, recorded with ffmpeg and
heard the same way), or a Wispr Flow dictation the owner already made (`--from-wispr`). It is written
as one `note/v1` line on the day (RFC 0010: tier 2, whoever writes it), source `reflect`, its kind in
`labels` as `reflection`, through the note path `note_day` writes through (`notes.write`).

**The Wispr Flow convention.** The owner dictates with Wispr Flow all day, and the `wispr-flow` source
keeps every dictation as a `transcript/v1` line (tier 3, the text in the attachment store). A dictation
whose text begins with the word "reflect" is the reflection: the first word, any case, after any
spaces and punctuation ("Reflect: ...", "reflect, ...", "...REFLECT - ..."); "reflection" or
"reflecting" is not the word. The draft is the dictation without that word and the punctuation after
it, offered when `day reflect DAY` is given no input and written only when the owner confirms it (on a
terminal: y, or e to edit it first) or says `--from-wispr`. Of several, the latest; `--from-wispr SEQ`
names one. A dictation a reflection already carries (`extra.dictation`) is not offered again.

**Proposals, rules only.** The sentences of the reflection (`promises.sentences`) are read by rules,
no model, and three kinds of proposal are printed, numbered, each with its evidence:

- a **commitment** the owner made: a sentence the cue tables of `promises` read as the owner's
  promise ("I'll ...", "I need to ...", "ich werde ..."), with the due day its words name. The
  reflection is a note in the owner's words, so `promises` lists it from the reflection itself;
  accepting it writes nothing more.
- a **delegation**, what someone else should do: "ask Ola to ...", "tell Ola to ...", "Ola should
  ...", "Ola must ...", "Ola soll ...", "frag Ola, ob ...", or a request cue of `promises` addressed
  to a name ("Ola, can you ..."), with the counterpart's name as spoken: a capitalised word or two
  that is not a pronoun, a function word or a day, and not after an article ("Die Fähre soll ..." is
  no one). Accepted, it is one `note/v1` line on the day, label `delegation`, `extra.to` the name and
  `extra.reflection` the reflection's id: no profile `promises` reads requests from fits a request the
  owner makes of someone else, and the note is the owner's words.
- a **disposition** of a commitment already on the page: a sentence that says what became of one
  ("went out", "done", "sent" kept; "didn't", "not yet" missed; "drop", "forget it" dropped;
  "tomorrow", "next week" carried; in German too, `disposition_of`), whose words match a commitment
  `promises` reads on the day's page. The match is the Dice overlap of normalised tokens (casefolded
  words of three letters or more, a plural -s dropped, function words, days and the disposition's own
  words left out), at `MATCH` or above, the best match winning. Accepted, it goes into the signature.

A sentence is a delegation or a commitment, never both, and may also be a disposition. Every proposal
is a guess until the owner accepts it (rule 6), with `--accept N,N` or one y/n each on a terminal.

**One path.** `write` puts the reflection on the day and `close` signs it with the proposals accepted;
`day reflect` and the Day page of `logbook serve` (its Reflect and Sign) both call them, and the page
shows the proposals in `proposal_words`, as the command prints them. There is no second
implementation."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..core import notes, sealing, signing
from ..core.chain import Line
from ..core.export import parse_day
from ..core.store import RETRACTION, Logbook, retractions
from . import promises

SOURCE = "reflect"  # the `source` of the lines `day reflect` writes
CUE = "reflect"  # the word a Wispr Flow dictation begins with when it is the reflection
WISPR = "wispr-flow"
TRANSCRIPT = "transcript"
MATCH = 0.5  # the Dice overlap at which a sentence refers to a commitment on the page
COMMITMENT, DELEGATION, DISPOSITION = "commitment", "delegation", "disposition"
TYPED, HEARD, DICTATED, DRAFT, ON_THE_DAY = (
    "typed",
    "heard",
    "dictated",
    "draft",
    "on the day",
)  # `Reflection.how`
FFMPEG = "ffmpeg"
MIC_MAX_S = 1800.0  # half an hour of microphone at most
SHA256 = re.compile(r"[0-9a-f]{64}")


class ReflectError(ValueError):
    """A reflection the command refuses, in one sentence; nothing is written."""


# -- the reflection --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Dictation:
    """A Wispr Flow dictation on the day and its whole text, as it was typed."""

    line: Line
    text: str

    @property
    def id(self) -> str:
        return str(self.line["id"])

    @property
    def seq(self) -> int:
        return int(self.line["seq"])

    @property
    def at(self) -> str:
        return str(self.line["at"])


@dataclass(frozen=True)
class Reflection:
    """The words of the reflection and where they came from: `how` says it (`typed`, `heard`,
    `dictated`, `on the day`); `note` is the reflection's line when it is on the day already;
    `dictation` the Wispr Flow line it was taken from; `at` the moment it was recorded when that is
    known (a dictation's); `extra` what the new note carries under `extra`."""

    text: str
    how: str
    note: Line | None = None
    dictation: Dictation | None = None
    at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def day_lines(lb: Logbook, day: str) -> tuple[list[Line], set[str]]:
    """The lines of `day` in the day's order and the ids retracted, read through the index once."""
    with lb.index() as idx:
        lines = idx.day(day)
        retracted = set(retractions(idx.retractions()))
    lines.sort(key=lambda line: (_instant(str(line["at"])), int(line["seq"])))
    return lines, retracted


def on_page(lines: Sequence[Line], retracted: Collection[str]) -> set[str]:
    """The ids of the page's lines not retracted (RFC 0034: every kind but retraction and signed-day)."""
    return {
        str(line["id"])
        for line in lines
        if line.get("kind") not in (RETRACTION, signing.KIND) and str(line["id"]) not in retracted
    }


def reflections(lines: Sequence[Line], retracted: Collection[str]) -> list[Line]:
    """The reflection notes standing on the day, the latest last."""
    return notes.standing(lines, notes.REFLECTION, retracted)


def same(text: str, standing: Sequence[Line], dictation: Dictation | None = None) -> Line | None:
    """The reflection already on the day that these words are: one with the same text, or, for a
    dictation, the one taken from it; so a reflection run twice is written once."""
    for line in reversed(standing):
        payload = line.get("payload") or {}
        extra = payload.get("extra")
        if dictation is not None and isinstance(extra, dict) and extra.get("dictation") == dictation.id:
            return line
        if payload.get("text") == text:
            return line
    return None


def text_of(line: Line) -> str:
    return str((line.get("payload") or {}).get("text") or "")


def on_the_day(line: Line) -> Reflection:
    """The reflection a note on the day already is."""
    return Reflection(text_of(line), ON_THE_DAY, note=line, at=str(line["at"]))


def draft(d: Dictation) -> Reflection:
    """A dictation that begins with the cue, offered as the reflection's draft: not yet confirmed."""
    return Reflection(without_cue(d.text), DRAFT, dictation=d, at=d.at, extra={"dictation": d.id})


def dictated(d: Dictation, text: str | None = None) -> Reflection:
    """The reflection taken from a dictation, as it is or in the words the owner typed instead: at
    the moment it was spoken, carrying the dictation's id under `extra.dictation`."""
    words = without_cue(d.text) if text is None else text
    return Reflection(words, DICTATED, dictation=d, at=d.at, extra={"dictation": d.id})


def sentences(text: str) -> list[str]:
    """The reflection a sentence a line, as `promises` reads it (`promises.sentences`)."""
    return promises.sentences(text)


def on_or_before(day: str, today: str, tz: str) -> None:
    """A reflection is of today or a day before it: `ReflectError` for a day ahead of `today`."""
    if day > today:
        raise ReflectError(f"{day} is ahead of today in {tz}; a reflection is of today or a day before it")


def write(lb: Logbook, day: str, r: Reflection, at: str | None, today: str) -> Line:
    """The reflection as one note/v1 line on the day (`notes.write`): at `at` when given, else when
    the dictation was spoken, else the note's own default."""
    return notes.write(
        lb,
        day,
        r.text,
        notes.REFLECTION,
        SOURCE,
        at=at if at is not None else r.at,
        today=today,
        extra=r.extra,
    )


def wrote_text(note: Line, zone: ZoneInfo) -> str:
    """What `day reflect` prints when it has written the reflection."""
    clock = _instant(str(note["at"])).astimezone(zone).strftime("%H:%M")
    where = f"(source {SOURCE}, tier {notes.TIER})"
    return f"wrote the reflection as #{note['seq']} {notes.SCHEMA} {where} at {clock}"


def delegate(lb: Logbook, day: str, proposal: Proposal, reflection: Line, today: str) -> Line:
    """An accepted delegation as one note/v1 line on the day (`notes.write`): the sentence as said,
    label `delegation`, `extra.to` the name as spoken and `extra.reflection` the reflection's id, at
    the reflection's moment."""
    return notes.write(
        lb,
        day,
        proposal.quote,
        notes.DELEGATION,
        SOURCE,
        at=str(reflection["at"]),
        today=today,
        extra={"to": proposal.counterpart, "reflection": str(reflection["id"])},
    )


# -- Wispr Flow ----------------------------------------------------------------------------------------

_CUE = re.compile(r"^[\W_]*" + CUE + r"\b[\W_]*", re.IGNORECASE)


def begins_with_cue(text: str) -> bool:
    """Whether a dictation is a reflection: its first word is "reflect", any case, after any spaces
    and punctuation."""
    return _CUE.match(text) is not None


def without_cue(text: str) -> str:
    """The dictation without its first word "reflect" and the punctuation after it: the draft."""
    return _CUE.sub("", text, count=1).strip()


def dictations(lb: Logbook, lines: Sequence[Line], retracted: Collection[str]) -> list[Dictation]:
    """The day's Wispr Flow dictations standing whose text is in the store, in the day's order."""
    found: list[Dictation] = []
    for line in lines:
        payload = line.get("payload") or {}
        if line.get("kind") != TRANSCRIPT or str(line["id"]) in retracted:
            continue
        if line.get("source") != WISPR and payload.get("provider") != WISPR:
            continue
        text = dictation_text(lb, line)
        if text is not None and text.strip():
            found.append(Dictation(line, text))
    return found


def dictation_text(lb: Logbook, line: Line) -> str | None:
    """The whole text of a dictation, as typed: the attachment its `content` names, read as one text
    (never split into speaker turns, so "Reflect: ..." stays the first word); None when the store
    does not have it or it does not open."""
    content = (line.get("payload") or {}).get("content")
    sha256 = content.get("sha256") if isinstance(content, dict) else None
    if not isinstance(sha256, str) or not SHA256.fullmatch(sha256):
        return None
    try:
        return lb.attachment_bytes(sha256).decode("utf-8-sig")
    except (OSError, UnicodeDecodeError, sealing.SealError):
        return None


def drafts(found: Sequence[Dictation], standing: Sequence[Line]) -> list[Dictation]:
    """The dictations that begin with the cue and that no reflection on the day was taken from."""
    taken = {
        extra.get("dictation")
        for line in standing
        if isinstance(extra := (line.get("payload") or {}).get("extra"), dict)
    }
    return [d for d in found if begins_with_cue(d.text) and d.id not in taken]


def pick(found: Sequence[Dictation], entry: str, day: str) -> Dictation:
    """The dictation `--from-wispr SEQ|ID` names among the day's."""
    text = entry.strip()
    for d in found:
        if (text.isdigit() and d.seq == int(text)) or d.id == text:
            return d
    raise ReflectError(
        f"{text!r} is not a Wispr Flow dictation on {day}; `logbook show {day}` lists the day's lines"
    )


# -- the proposals ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Commitment:
    """A commitment on the day's page as `promises` reads it: the line, and the sentence quoted."""

    line: str
    seq: int
    quote: str
    words: frozenset[str]


@dataclass(frozen=True)
class Proposal:
    """One thing the reflection suggests, numbered as printed: its `kind`, the line of the reflection
    it was read in (`sentence`, from 1) and that sentence, the words that made it one (`cue`, as
    said); a delegation's `counterpart` as spoken; a disposition's `value`, the commitment's `line`
    and `seq`, its sentence (`target`) and the overlap (`score`); a due day when the words name one."""

    number: int
    kind: str
    sentence: int
    quote: str
    cue: str
    counterpart: str | None = None
    value: str | None = None
    line: str | None = None
    seq: int | None = None
    target: str | None = None
    score: float | None = None
    due_phrase: str | None = None
    due: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "kind": self.kind,
            "sentence": self.sentence,
            "quote": self.quote,
            "cue": self.cue,
            "counterpart": self.counterpart,
            "disposition": self.value,
            "line": self.line,
            "seq": self.seq,
            "target": self.target,
            "score": None if self.score is None else round(self.score, 2),
            "due": None if self.due_phrase is None else {"phrase": self.due_phrase, "date": self.due},
            "certainty": promises.CERTAINTY,
        }


def commitments(lb: Logbook, day: str, exclude: Collection[str] = ()) -> list[Commitment]:
    """The commitments on the day's page: every sentence `promises` reads as owed by the owner (a
    promise of theirs, or a request made of them) in a line of the day, but the lines `exclude`
    names (the reflection itself, the dictation it was taken from), in the day's order."""
    report = promises.extract(lb, since=day, until=day)
    return [
        Commitment(p.line, p.seq, p.match.quote, tokens(p.match.quote))
        for p in report.proposals
        if p.day == day and p.direction == promises.OWED_BY_OWNER and p.line not in exclude
    ]


def propose(text: str, day: str, found: Sequence[Commitment]) -> list[Proposal]:
    """The proposals the reflection `text` suggests on `day`, numbered: the commitments first, then
    the delegations, then the dispositions of `found`, each in the order of the sentences."""
    when = parse_day(day)
    made: list[Proposal] = []
    asked: list[Proposal] = []
    disposed: list[Proposal] = []
    for n, sentence in enumerate(promises.sentences(text), 1):
        phrase = promises.due_phrase(sentence)
        delegated = delegation_of(sentence)
        if delegated is not None:
            name, cue = delegated
            due_phrase, due = _due(phrase, when)
            asked.append(
                Proposal(0, DELEGATION, n, sentence, cue, counterpart=name, due_phrase=due_phrase, due=due)
            )
        else:
            match = promises.RULES.sentence(sentence)
            if match is not None and match.phrase_class in promises.COMMITMENT_CLASSES:
                due_phrase, due = _due(match.due_phrase, when)
                made.append(Proposal(0, COMMITMENT, n, sentence, match.cue, due_phrase=due_phrase, due=due))
        reference = _reference(sentence, found)
        if reference is not None:
            commitment, score, value, cue = reference
            disposed.append(
                Proposal(
                    0,
                    DISPOSITION,
                    n,
                    sentence,
                    cue,
                    value=value,
                    line=commitment.line,
                    seq=commitment.seq,
                    target=commitment.quote,
                    score=score,
                )
            )
    return [replace(p, number=i) for i, p in enumerate([*made, *asked, *disposed], 1)]


def proposal_words(p: Proposal) -> tuple[str, str]:
    """A proposal as `day reflect` prints it and the Day page shows it: the word (`commitment`,
    `delegation`, or a disposition's own word) and the evidence (the sentence, the cue, a due day; a
    disposition's commitment and the overlap)."""
    due = f" · due {p.due}" if p.due else (f" · {p.due_phrase}" if p.due_phrase else "")
    if p.kind == DISPOSITION:
        return str(p.value), f"#{p.seq} “{p.target}” · {p.cue} · overlap {p.score or 0:.2f}"
    if p.kind == DELEGATION:
        return p.kind, f"to {p.counterpart}: “{p.quote}” · {p.cue}{due}"
    return p.kind, f"“{p.quote}” · {p.cue}{due} · `promises` reads it from the reflection"


def _due(phrase: str | None, when: date) -> tuple[str | None, str | None]:
    """The date phrase and the day it names, counted from the day of the reflection."""
    if phrase is None:
        return None, None
    resolved = promises.due_of(phrase, when)
    return phrase, None if resolved is None else resolved.isoformat()


def _reference(sentence: str, found: Sequence[Commitment]) -> tuple[Commitment, float, str, str] | None:
    """The commitment `sentence` says became something, the overlap, the word and its cue; None when
    the sentence carries no disposition or matches no commitment at `MATCH` or above."""
    disposed = disposition_of(sentence)
    if disposed is None:
        return None
    words = tokens(sentence)
    best: tuple[Commitment, float] | None = None
    for commitment in found:
        score = overlap(words, commitment.words)
        if score >= MATCH and (best is None or score > best[1]):
            best = (commitment, score)
    if best is None:
        return None
    return best[0], best[1], disposed[0], disposed[1]


# What became of a commitment, as the owner says it; the first cue in a sentence decides.
_DISPOSED: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        signing.KEPT,
        re.compile(
            r"\b(?:went out|gone out|is out|are out|done|sent|did it|did that|finished|completed|handled"
            r"|delivered|paid|booked|called|fixed|bought|ordered|kept"
            r"|erledigt|gemacht|geschickt|verschickt|gesendet|ist raus|sind raus|bezahlt|gebucht|angerufen"
            r"|gekauft|bestellt|fertig)\b",
            re.IGNORECASE,
        ),
    ),
    (
        signing.MISSED,
        re.compile(
            r"\b(?:didn['\u2019]?t|did not|haven['\u2019]?t|have not|hasn['\u2019]?t|has not|isn['\u2019]?t"
            r"|is not|wasn['\u2019]?t|was not|weren['\u2019]?t|were not|not yet|not done|not sent|never got"
            r"|forgot|missed|couldn['\u2019]?t|could not|failed to"
            r"|noch nicht|nicht geschafft|nicht gemacht|nicht erledigt|nicht geschickt|vergessen|verpasst"
            r"|versäumt)\b",
            re.IGNORECASE,
        ),
    ),
    (
        signing.DROPPED,
        re.compile(
            r"\b(?:drop(?:ped|ping)?|forget it|forget about it|forget that|forget|let it go|let that go"
            r"|not going to|no longer|scrap(?:ped)?|cancel(?:led|ed)?|skip(?:ped)?|never mind"
            r"|vergiss es|vergiss das|vergiss|lassen wir das|lassen wir es|fällt weg|gestrichen|streichen"
            r"|abgesagt|sein lassen)\b",
            re.IGNORECASE,
        ),
    ),
    (
        signing.CARRIED,
        re.compile(
            r"\b(?:tomorrow|next week|next month|another day|moved? (?:it )?to|push(?:ed)? (?:it )?to"
            r"|carr(?:y|ied) (?:it )?over|postponed?|übermorgen|nächste woche|naechste woche|nächsten monat"
            r"|verschoben|verschieben)\b|(?<!heute )(?<!am )(?<!guten )\bmorgen\b",
            re.IGNORECASE,
        ),
    ),
)


def disposition_of(sentence: str) -> tuple[str, str] | None:
    """(the disposition a sentence suggests, the words that suggest it, as said), or None: of the
    cues of `_DISPOSED` in the sentence, the first decides ("didn't send ... tomorrow" is missed)."""
    first: tuple[int, str, str] | None = None
    for value, pattern in _DISPOSED:
        m = pattern.search(sentence)
        if m and (first is None or m.start() < first[0]):
            first = (m.start(), value, m.group(0))
    return None if first is None else (first[1], first[2])


# -- delegations -----------------------------------------------------------------------------------------

_ASK_EN = re.compile(r"\b(ask|tell|remind|get)\s+(\S+(?:\s+\S+)?)\s+to\b", re.IGNORECASE)
_ASK_DE = re.compile(
    r"\b(frag|frage|bitte|sag|sage|erinnere)\s+(\S+(?:\s+\S+)?)(?=\s*,|\s+(?:dass|ob|an|zu)\b)", re.IGNORECASE
)
_MODAL = re.compile(
    r"\b(should|needs to|has to|must|is to|ought to|soll|sollte|muss|müsste)\b", re.IGNORECASE
)  # a third person's obligation: "Ola should", "Ola soll"
_VOCATIVE = re.compile(r"^[\W_]*(\w[\w'\u2019-]*(?:\s+\w[\w'\u2019-]*)?)\s*,")  # "Ola, can you ..."
_NAME_WORDS = 2  # a name as spoken: a first name, or a first and a family name
_PUNCTUATION = "\"'\u2018\u2019\u201c\u201d.,;:!?()[]"


def delegation_of(sentence: str) -> tuple[str, str] | None:
    """(the counterpart's name as spoken, the cue) when `sentence` asks someone else to do a thing:
    "ask Ola to", "Ola should", "frag Ines, ob", or a request cue of `promises` addressed to a name;
    None when no name is there to ask."""
    for pattern in (_ASK_EN, _ASK_DE):
        m = pattern.search(sentence)
        if m:
            words = [word.strip(_PUNCTUATION) for word in m.group(2).split()]
            if words and all(_is_name(word) for word in words):
                return " ".join(words), m.group(1)
    m = _MODAL.search(sentence)
    if m:
        name = _name_before(sentence[: m.start()])
        if name is not None:
            return name, m.group(1)
    match = promises.RULES.sentence(sentence)
    if match is not None and match.phrase_class == promises.REQUEST:
        m = _VOCATIVE.match(sentence)
        if m:
            words = m.group(1).split()
            if all(_is_name(word) for word in words):
                return " ".join(words), match.cue
    return None


def _name_before(text: str) -> str | None:
    """The name right before a modal, a word or two, each capitalised and none a function word or a
    day; None when there is none, or when an article stands before it ("Die Fähre soll")."""
    words = [word.strip(_PUNCTUATION) for word in text.split()]
    name: list[str] = []
    while words and len(name) < _NAME_WORDS and _is_name(words[-1]):
        name.insert(0, words.pop())
    if not name or (words and words[-1].casefold() in _ARTICLES):
        return None
    return " ".join(name)


def _is_name(word: str) -> bool:
    return (
        bool(word)
        and word[0].isupper()
        and word.casefold() not in _NOT_NAMES
        and word.casefold() not in _STOP
    )


_ARTICLES = frozenset(
    (
        "the", "a", "an", "my", "our", "your", "his", "her", "their", "its", "this", "that", "der", "die",
        "das", "den", "dem", "des", "ein", "eine", "einen", "einem", "einer", "mein", "meine", "unser",
        "unsere", "dein", "deine", "sein", "seine", "ihr", "ihre",
    )
)  # fmt: skip
_NOT_NAMES = frozenset(
    (
        "i", "we", "you", "he", "she", "it", "they", "this", "that", "these", "those", "there", "here",
        "someone", "somebody", "anyone", "anybody", "everyone", "everybody", "nobody", "everything",
        "nothing", "something", "anything", "one", "who", "what", "which", "then", "also", "maybe",
        "perhaps", "so", "and", "but", "all", "both", "each", "ich", "wir", "du", "ihr", "er", "sie", "es",
        "man", "das", "dies", "dieser", "diese", "jemand", "niemand", "jeder", "alle", "wer", "was", "dann",
        "auch", "vielleicht", "und", "aber",
    )
)  # fmt: skip


# -- the overlap -----------------------------------------------------------------------------------------

_WORD = re.compile(r"[^\W\d_]+")
_STOP = frozenset(
    (
        # English function words, modal and auxiliary verbs
        "the", "and", "for", "with", "from", "that", "this", "these", "those", "there", "here", "then",
        "than", "into", "onto", "over", "under", "about", "above", "after", "again", "also", "any", "are",
        "was", "were", "been", "being", "but", "not", "nor", "can", "could", "would", "should", "shall",
        "will", "may", "might", "must", "need", "needs", "needed", "have", "has", "had", "having", "does",
        "did", "doing", "get", "got", "its", "our", "ours", "your", "yours", "their", "theirs", "his",
        "her", "hers", "him", "them", "they", "she", "you", "who", "whom", "what", "which", "when",
        "where", "why", "how", "all", "some", "just", "very", "more", "most", "less", "still", "yet",
        "out", "off", "down", "too", "only", "own", "same", "such", "both", "each", "few", "other",
        "another", "per", "via", "let", "lets", "ill", "ive", "one", "two", "well", "okay", "going",
        "gone", "want", "wants", "really", "maybe",
        # German
        "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem", "einer", "eines", "und",
        "oder", "aber", "wenn", "dann", "als", "wie", "mit", "ohne", "für", "von", "vom", "zum", "zur",
        "bei", "beim", "auf", "aus", "nach", "vor", "über", "unter", "durch", "gegen", "ist", "sind",
        "war", "waren", "sein", "bin", "bist", "hat", "habe", "haben", "hatte", "hatten", "wird", "werde",
        "werden", "würde", "soll", "sollte", "sollen", "muss", "müssen", "kann", "könnte", "können",
        "mich", "mir", "mein", "meine", "meinen", "wir", "uns", "unser", "unsere", "dich", "dir", "dein",
        "deine", "ihn", "ihm", "ihr", "ihre", "sie", "nicht", "kein", "keine", "noch", "schon", "auch",
        "sehr", "mehr", "nur", "doch", "mal", "ganz", "gar", "dass", "damit", "hier", "dort",
        # days and times: when, never what
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "montag", "dienstag",
        "mittwoch", "donnerstag", "freitag", "samstag", "sonntag", "sonnabend", "january", "february",
        "march", "april", "may", "june", "july", "august", "september", "october", "november", "december",
        "januar", "februar", "märz", "mai", "juni", "juli", "oktober", "dezember", "today", "tonight",
        "tomorrow", "yesterday", "morning", "evening", "afternoon", "night", "week", "weeks", "month",
        "months", "year", "day", "days", "weekend", "next", "last", "heute", "morgen", "gestern", "abend",
        "nachmittag", "woche", "wochen", "monat", "monate", "jahr", "tag", "tage", "wochenende", "nächste",
        "nächsten", "kommende",
    )
)  # fmt: skip


def tokens(text: str) -> frozenset[str]:
    """The words of `text` that say what it is about: casefolded, three letters or more, a plural -s
    dropped, without function words, days and times, and the words of a disposition (`_DISPOSED`)."""
    for _value, pattern in _DISPOSED:
        text = pattern.sub(" ", text)
    found: set[str] = set()
    for word in _WORD.findall(text.casefold()):
        if len(word) < 3 or word in _STOP:
            continue
        if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        found.add(word)
    return frozenset(found)


def overlap(a: Collection[str], b: Collection[str]) -> float:
    """The Dice coefficient of two sets of words: twice the words shared over the words of both."""
    if not a or not b:
        return 0.0
    return 2 * len(set(a) & set(b)) / (len(a) + len(b))


# -- --accept ----------------------------------------------------------------------------------------------

NONE = "none"


def numbers(text: str) -> list[int]:
    """`--accept N,N` as the numbers, in order, each once; `none` as the empty list. A word that is
    not a proposal number is refused."""
    if text.strip().casefold() == NONE:
        return []
    found: list[int] = []
    for word in text.split(","):
        word = word.strip()
        if not word:
            continue
        if not word.isdigit() or int(word) < 1:
            raise ReflectError(
                f"--accept takes the proposals' numbers as printed, N,N, or {NONE}; not {word!r}"
            )
        if int(word) not in found:
            found.append(int(word))
    if not found:
        raise ReflectError(f"--accept names no proposal; --accept {NONE} accepts none of them")
    return found


def chosen(proposals: Sequence[Proposal], wanted: Sequence[int]) -> list[Proposal]:
    """The proposals these numbers name, in their order; refused when a number names none, or when
    two of them give one line of the page two dispositions."""
    by_number = {p.number: p for p in proposals}
    missing = [n for n in wanted if n not in by_number]
    if missing:
        have = f"{len(proposals)} proposal{'s' if len(proposals) != 1 else ''}"
        raise ReflectError(
            f"no proposal {', '.join(map(str, missing))}; the reflection has {have}, numbered above"
        )
    found = [by_number[n] for n in sorted(wanted)]
    given: dict[str, Proposal] = {}
    for p in found:
        if p.kind != DISPOSITION or p.line is None:
            continue
        other = given.get(p.line)
        if other is not None and other.value != p.value:
            raise ReflectError(
                f"#{p.seq} is given {other.value} by proposal {other.number} and {p.value} by proposal"
                f" {p.number}; a line has one disposition, accept one of them"
            )
        given[p.line] = p
    return found


# -- the signature ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Signature:
    """What `signing.sign` is given: the confirmed set (None for the page), the dispositions by word,
    the note; and what was kept from the standing signature, for the owner to read."""

    confirm: list[str] | None
    dispositions: dict[str, list[str]]
    note: str | None
    kept: str | None = None


def signature(
    earlier: Line | None, page: Collection[str], joined: Sequence[str], accepted: Sequence[Proposal]
) -> Signature:
    """The arguments of the signature `day reflect --sign` writes. A day not signed yet: the page
    confirmed (the reflection and the delegations among it) and the accepted dispositions. A day
    signed already is signed again, superseding the standing signature and keeping what it said: its
    confirmed lines still on the page and not retracted, the lines `joined` (the reflection, the
    delegations) added, its dispositions, the accepted ones winning on a line they share, its note."""
    disposed: dict[str, str] = {}
    confirm: list[str] | None = None
    note: str | None = None
    kept: str | None = None
    if earlier is not None:
        p = earlier.get("payload") or {}
        confirmed = p.get("confirmed")
        confirm = [str(id_) for id_ in confirmed if id_ in page] if isinstance(confirmed, list) else []
        confirm += [id_ for id_ in joined if id_ not in confirm]
        disposed = {id_: value for id_, value in signing.dispositions_of(p).items() if id_ in page}
        note = p["note"] if isinstance(p.get("note"), str) and p["note"] else None
        parts = [
            f"{len(confirm) - len(joined)} line{'s' if len(confirm) - len(joined) != 1 else ''} confirmed"
        ]
        counts = signing.counts_text(disposed)
        if counts:
            parts.append(counts)
        if note is not None:
            parts.append("the note")
        kept = f"keeps from the signature it supersedes (#{earlier['seq']}): {', '.join(parts)}"
    for proposal in accepted:
        if proposal.kind == DISPOSITION and proposal.line is not None and proposal.value is not None:
            disposed[proposal.line] = proposal.value
    by_word = {
        value: [id_ for id_, given in disposed.items() if given == value]
        for value in signing.DISPOSITIONS
        if value in disposed.values()
    }
    return Signature(confirm, by_word, note, kept)


@dataclass(frozen=True)
class Closed:
    """What `close` wrote: the signature, the reflection it confirmed (`written` when it was written
    by this close, not on the day already), the accepted delegations as their notes, and what the
    signature kept from the one it supersedes."""

    signature: Line
    reflection: Line
    written: bool
    delegations: tuple[Line, ...]
    kept: str | None


def _quiet(_text: str) -> None:
    return None


def close(
    lb: Logbook,
    day: str,
    today: str,
    r: Reflection,
    accepted: Sequence[Proposal],
    at: str | None = None,
    say: Callable[[str], None] = _quiet,
) -> Closed:
    """The day closed: `day reflect --sign`, and the Sign of the Day page. Under one hold of the
    writer lock: the page read again (a disposition's line retracted since the proposals were read
    is refused, nothing written), the reflection written when it is new (`write`), the accepted
    delegations written as notes (`delegate`), then the signature through `signing.sign` with what
    `signature` says, at `at` or now. `say` hears what the command prints as it goes. HeadMoved and
    another writer are the store's own errors; nothing is retried."""
    zone = ZoneInfo(str(lb.meta["timezone"]))
    with lb.writer():
        lines, retracted = day_lines(lb, day)
        page = on_page(lines, retracted)
        gone = [p for p in accepted if p.kind == DISPOSITION and p.line not in page]
        if gone:
            raise ReflectError(f"#{gone[0].seq} is no longer on the page of {day}; nothing was written")
        with lb.index() as idx:
            earlier = signing.signature_of(idx, day, str(lb.meta["owner_id"]))
        note = r.note
        if note is None:
            note = write(lb, day, r, at, today)
            say(wrote_text(note, zone))
        joined = [str(note["id"])]
        delegations: list[Line] = []
        for p in accepted:
            if p.kind == COMMITMENT:
                say(f"commitment {p.number}: nothing to write; `promises` lists it from the reflection")
            elif p.kind == DELEGATION:
                line = delegate(lb, day, p, note, today)
                joined.append(str(line["id"]))
                delegations.append(line)
                say(f"wrote delegation {p.number} to {p.counterpart} as #{line['seq']} {notes.SCHEMA}")
        args = signature(earlier, page | set(joined), joined, accepted)
        if args.kept is not None:
            say(f"  {args.kept}")
        line = signing.sign(
            lb, day, confirm=args.confirm, note=args.note, at=at, dispositions=args.dispositions
        )
    return Closed(line, note, r.note is None, tuple(delegations), args.kept)


# -- the microphone ----------------------------------------------------------------------------------------


def _platform() -> str:
    return sys.platform


def record(seconds: float, folder: Path) -> Path:
    """`seconds` of the default microphone recorded into `folder`, on macOS, with ffmpeg's
    AVFoundation input: mono, 16 kHz, a WAV the engines read. Refused plainly off macOS, without
    ffmpeg on the PATH, and when no microphone answers. Nothing leaves the machine."""
    if _platform() != "darwin":
        raise ReflectError("--mic records on macOS only; give --audio FILE with a recording, or --text")
    if not 1 <= seconds <= MIC_MAX_S:
        raise ReflectError(f"--mic takes seconds from 1 to {MIC_MAX_S:g}, not {seconds:g}")
    ffmpeg = shutil.which(FFMPEG)
    if ffmpeg is None:
        raise ReflectError(
            "--mic records with ffmpeg, which is not on the PATH (`brew install ffmpeg`);"
            " or give --audio FILE"
        )
    out = folder / "reflection.wav"
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-f", "avfoundation", "-i", ":0",
        "-t", f"{seconds:g}", "-ac", "1", "-ar", "16000", "-y", str(out),
    ]  # fmt: skip
    try:
        done = subprocess.run(command, capture_output=True, timeout=seconds + 30, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ReflectError(f"no microphone answered: {e}") from e
    if done.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        raise ReflectError(
            "no microphone was available to record from: ffmpeg could not open the default input (macOS asks"
            " once to let the terminal use the microphone, under Privacy & Security)"
        )
    return out


def _instant(stamp: str) -> datetime:
    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
