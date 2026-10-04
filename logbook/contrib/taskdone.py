"""`logbook tasks`: the record's tasks (`task/v1`, RFC 0016) read back, and the evidence that an open
one was done, proposed and never asserted.

A task is a snapshot (RFC 0016 rule 2): the same to-do exported again after it was ticked off is a
new line with a newer `raw_id` suffix, and the latest standing line per source id (the `raw_id`
before `@`) is the task's state. `tasks` lists those; `--open` the open ones.

`--propose-done` asks, for every open task, whether the record itself says it was done: within the
fortnight after the task was written, a `mail/v1` subject (RFC 0015) that names the task's key nouns
and confirms something (a booking confirmation for "book flights to Zürich", or a mail the owner
sent), an `event/v1` title (RFC 0009) that names them for a call or a meeting ("Call with Ola" for
"call Ola"), or a `transaction/v1` merchant (RFC 0021) the task names ("Marina Solvind" for "pay the
berth fee at Marina Solvind"). The key nouns are the title's content words in English and German,
compared case, accents, plurals and German compounds aside; found by rules alone, no model runs and
no socket opens. Each proposal carries the evidence line's id, so the owner closes the task with
`tasks done <id> --evidence <line>`, which appends one `task/v1` line marked done (the newest
snapshot of the task, `supersedes` the one before, the evidence under `extra`) and nothing else.
Everything else here is a draft (ADR 0013.7): proposals are printed, never written.

The matcher is a value, not the command. `propose(lb, matcher=RULES)` takes anything with a `name`,
a `version` and `__call__(task, candidate) -> Evidence | None`: the command owns the record, the
tasks, the window and the candidates, and the matcher reads one task against one line and says
whether the line is evidence, how (a `rule`), on which `shared` words, and how sure it is. The rules
are the first such thing; the promises judge's engine (`logbook.labs.judge`), a local instruct model that
answers one JSON object per candidate, can be the next, and the report, the ids and `done` stay the
same."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from ..core.chain import Line
from ..core.index import local_date
from ..core.store import Logbook, retractions

TASK = "task"
TASK_SCHEMA = "task/v1"
TASK_TIER = 2  # RFC 0016: MUST
MAIL, EVENT, TRANSACTION = "mail", "event", "transaction"
KINDS = (MAIL, EVENT, TRANSACTION)
WINDOW = timedelta(days=14)  # evidence counts in the fortnight after the task was written
ID_WIDTH = 16
TEXT_WIDTH = 80
DONE_STATES = ("done", "cancelled")

# -- the words -----------------------------------------------------------------------------------------

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_MIN_WORD = 3  # `to`, `at`, `am`: never a key noun
_MIN_PREFIX = 4  # `flug` in `flugtickets`; never `ola` in `olav`

# the words a title carries that name nothing: articles, prepositions, pronouns, fillers
_STOPWORDS_EN = frozenset(
    (
        "the", "a", "an", "to", "for", "of", "in", "on", "at", "with", "about", "from", "by", "and", "or",
        "my", "our", "your", "his", "her", "their", "this", "that", "these", "those", "it", "its", "is",
        "are", "be", "re", "up", "out", "new", "next", "some", "all", "before", "after", "until", "till",
        "into", "onto", "per", "via", "please", "also", "again", "still", "just", "back", "now", "then",
        "today", "tomorrow", "week", "month", "year"
    )
)  # fmt: skip
_STOPWORDS_DE = frozenset(
    (
        "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem", "einer", "eines", "und",
        "oder", "zu", "zum", "zur", "für", "fuer", "mit", "an", "am", "auf", "in", "im", "von", "vom",
        "bei", "beim", "nach", "über", "ueber", "um", "bis", "aus", "mich", "mir", "meine", "meinen",
        "meinem", "meiner", "mein", "unsere", "unser", "unseren", "noch", "mal", "bitte", "nicht", "wegen",
        "ob", "dann", "heute", "morgen", "woche", "monat", "jahr", "wieder", "auch", "schon", "neu", "neue",
        "neuen"
    )
)  # fmt: skip
# the action of a task: kept apart from its nouns, since the evidence rarely repeats it
_VERBS_EN = frozenset(
    (
        "book", "buy", "call", "pay", "send", "order", "renew", "cancel", "check", "write", "email", "mail",
        "ask", "get", "fix", "finish", "pick", "drop", "return", "schedule", "plan", "confirm", "reply",
        "read", "review", "submit", "sign", "print", "update", "clean", "visit", "meet", "see", "talk",
        "phone", "ring", "text", "transfer", "deposit", "make", "do", "find", "look", "go", "arrange",
        "prepare", "bring", "take", "collect", "fetch", "register", "apply", "file", "hand", "set", "sort"
    )
)  # fmt: skip
_VERBS_DE = frozenset(
    (
        "buchen", "kaufen", "anrufen", "bezahlen", "zahlen", "überweisen", "ueberweisen", "bestellen",
        "schicken", "senden", "schreiben", "mailen", "fragen", "holen", "abholen", "bringen", "erledigen",
        "verlängern", "verlaengern", "kündigen", "kuendigen", "prüfen", "pruefen", "checken", "reservieren",
        "besuchen", "treffen", "planen", "machen", "abgeben", "zurückgeben", "zurueckgeben", "einreichen",
        "unterschreiben", "drucken", "putzen", "lesen", "antworten", "klären", "klaeren", "besorgen",
        "überprüfen", "ueberpruefen", "anmelden", "beantragen", "vereinbaren", "ausmachen"
    )
)  # fmt: skip
# a task that is an appointment: a calendar entry naming its nouns is evidence on its own
_APPOINTMENT_VERBS = frozenset(
    (
        "call", "phone", "ring", "meet", "see", "visit", "talk", "anrufen", "treffen", "besuchen",
        "ausmachen", "vereinbaren"
    )
)  # fmt: skip
_APPOINTMENT_NOUNS = frozenset(
    (
        "appointment", "meeting", "lunch", "dinner", "coffee", "interview", "termin", "besprechung",
        "treffen", "gespräch", "gespraech", "anruf", "mittagessen", "abendessen", "kaffee"
    )
)  # fmt: skip
# what a mail subject says when it confirms something: a prefix of a word (`confirmation`,
# `confirmed`) or a part of a German compound (`Buchungsbestätigung`)
_CUES_EN = (
    "confirm",
    "booking",
    "booked",
    "receipt",
    "ticket",
    "itinerary",
    "reservation",
    "invoice",
    "order",
)
_CUES_DE = (
    "bestätig",
    "bestatig",
    "buchung",
    "gebucht",
    "rechnung",
    "quittung",
    "reservierung",
    "bestellung",
    "beleg",
)
_CUE = re.compile("|".join(sorted((*_CUES_EN, *_CUES_DE), key=len, reverse=True)))


@dataclass(frozen=True)
class Words:
    """A title taken apart: its key nouns (the content words, in order, as written but lower-cased)
    and its verbs (the action words, by the lists above), and whether it reads as an appointment."""

    nouns: tuple[str, ...]
    verbs: tuple[str, ...]

    @property
    def appointment(self) -> bool:
        return any(v in _APPOINTMENT_VERBS for v in self.verbs) or any(
            normal(n) in _APPOINTMENT_NOUNS for n in self.nouns
        )


def tokens(text: str) -> list[str]:
    """The words of a text, lower-cased, letters and digits only."""
    return [m.group(0).casefold() for m in _WORD.finditer(text)]


def words_of(title: str) -> Words:
    """The key nouns and the verbs of a task's title. A noun is a word of three letters or more that
    is neither a stopword nor a verb of the lists, in English or German; a digit run of three or more
    (an invoice number) is a noun too."""
    nouns: list[str] = []
    verbs: list[str] = []
    for word in tokens(title):
        if word in _VERBS_EN or word in _VERBS_DE:
            verbs.append(word)
        elif word in _STOPWORDS_EN or word in _STOPWORDS_DE or len(word) < _MIN_WORD:
            continue
        else:
            nouns.append(word)
    return Words(tuple(nouns), tuple(verbs))


def normal(word: str) -> str:
    """A word with case and accents stripped (`Zürich` and `zurich`, `Tromsø` and `tromso`), for
    comparing."""
    bare = unicodedata.normalize("NFKD", word.casefold())
    bare = "".join(c for c in bare if not unicodedata.combining(c))
    return bare.replace("ø", "o").replace("æ", "ae").replace("ß", "ss").replace("œ", "oe")


def stem(word: str) -> str:
    """`normal`, with an English plural `s` dropped from a word of five letters or more (`flights`
    and `flight`; `fee` and `fees` stay apart, which the prefix rule in `same_word` mends)."""
    bare = normal(word)
    if len(bare) >= 5 and bare.endswith("s") and not bare.endswith("ss"):
        return bare[:-1]
    return bare


def same_word(a: str, b: str) -> bool:
    """Whether two words are one for matching: equal stems, or one the stem of a German compound the
    other begins (`Flug`, `Flugtickets`) when the shorter is four letters or more; so `ola` never
    matches `olav` and `fee` never `feel`."""
    x, y = stem(a), stem(b)
    if x == y:
        return True
    short, long = sorted((x, y), key=len)
    return len(short) >= _MIN_PREFIX and long.startswith(short)


def shared_words(nouns: Sequence[str], text: str) -> tuple[str, ...]:
    """The task's nouns, as the task spells them, that the text carries."""
    had = tokens(text)
    return tuple(n for n in nouns if any(same_word(n, w) for w in had))


# -- the contract --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Task:
    """One task as it stands: the latest standing snapshot of one source id. `id` is a digest of the
    source id (`key`, the `raw_id` before `@`), so it is the same whichever snapshot is newest; `line`
    is that snapshot's line id, `at` and `day` its time."""

    id: str
    key: str
    title: str
    status: str
    due: str | None
    list: str | None
    at: str
    day: str
    seq: int
    line: str
    source: str

    @property
    def open(self) -> bool:
        return self.status not in DONE_STATES

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "key": self.key,
            "title": self.title,
            "status": self.status,
            "due": self.due,
            "list": self.list,
            "at": self.at,
            "day": self.day,
            "seq": self.seq,
            "line": self.line,
            "source": self.source,
        }


@dataclass(frozen=True)
class Candidate:
    """One line that could be evidence, as a matcher sees it: its kind, its one text (a mail's
    subject, an entry's title, a transaction's merchant) and, for a mail, whether the owner sent it."""

    line: str
    seq: int
    kind: str
    source: str
    at: str
    day: str
    tier: int
    text: str
    sent: bool = False


@dataclass(frozen=True)
class Evidence:
    """A matcher's verdict on one candidate: how it is evidence (`rule`: the rules name theirs
    `mail-confirmation`, `mail-sent`, `event`, `transaction`; a model names its own), the task's
    words it found, and how sure it is (0 to 1)."""

    rule: str
    shared: tuple[str, ...]
    confidence: float

    def to_json(self) -> dict[str, Any]:
        return {"rule": self.rule, "shared": list(self.shared), "confidence": self.confidence}


class Matcher(Protocol):
    """What the command needs from a matcher; the rules below are one, a local model is another."""

    name: str
    version: str

    def __call__(self, task: Task, candidate: Candidate) -> Evidence | None: ...


# -- the rules -----------------------------------------------------------------------------------------


class Rules:
    """The rule matcher. A candidate is evidence when its text carries a key noun of the task and,
    by kind: a mail when its subject also confirms something (`confirmation`, `booking`, `receipt`,
    `Bestätigung`, `Rechnung`, …) or the owner sent it; a calendar entry when the task is an
    appointment (`call`, `meet`, `anrufen`, a `Termin`), or the entry's title repeats the task's
    verb, or it carries two of the task's nouns; a transaction when its merchant carries a noun.
    The confidence is 0.6 and a tenth more per noun shared beyond the first, 0.9 at most; a
    confirmation cue adds a tenth."""

    name = "rules"
    version = "1"
    languages = ("en", "de")

    def __call__(self, task: Task, candidate: Candidate) -> Evidence | None:
        words = words_of(task.title)
        if not words.nouns:
            return None
        shared = shared_words(words.nouns, candidate.text)
        if not shared:
            return None
        confidence = round(min(0.9, 0.6 + 0.1 * (len(shared) - 1)), 2)
        if candidate.kind == MAIL:
            if _CUE.search(normal(candidate.text)):
                return Evidence("mail-confirmation", shared, round(min(0.9, confidence + 0.1), 2))
            if candidate.sent:
                return Evidence("mail-sent", shared, confidence)
            return None
        if candidate.kind == EVENT:
            had = tokens(candidate.text)
            repeats_verb = any(same_word(v, w) for v in words.verbs for w in had)
            if words.appointment or repeats_verb or len(shared) >= 2:
                return Evidence("event", shared, confidence)
            return None
        if candidate.kind == TRANSACTION:
            return Evidence("transaction", shared, confidence)
        return None


RULES = Rules()


def describe(matcher: Matcher) -> dict[str, Any]:
    out: dict[str, Any] = {"name": matcher.name, "version": matcher.version}
    languages = getattr(matcher, "languages", None)
    if isinstance(languages, Sequence) and not isinstance(languages, str):
        out["languages"] = [str(lang) for lang in languages]
    return out


# -- the tasks -----------------------------------------------------------------------------------------


def task_id(key: str) -> str:
    """The id of a task: a digest of its source id, sixteen hex characters, the same for every
    snapshot of the task."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:ID_WIDTH]


def key_of(payload: Mapping[str, Any]) -> tuple[str, str] | None:
    """A task's source id and the snapshot's suffix (RFC 0016 rule 2): `raw_id` split at its last
    `@`; a `raw_id` with no `@` is the key whole and the suffix is its `modified_at`, else empty."""
    raw_id = payload.get("raw_id")
    if not isinstance(raw_id, str) or not raw_id:
        return None
    key, sep, suffix = raw_id.rpartition("@")
    if not sep:
        modified = payload.get("modified_at")
        return raw_id, modified if isinstance(modified, str) else ""
    return key, suffix


def tasks_of(lines: Iterable[Line], retracted: Mapping[str, Line], tz: str) -> list[Task]:
    """The tasks the `task/v1` lines describe, one per source id, each as its latest standing
    snapshot (the newest suffix; the later line when two share it), a retracted line out and a line
    with no `raw_id` or no title skipped; in day order."""
    latest: dict[str, tuple[str, int, Line]] = {}
    for line in lines:
        if str(line.get("id")) in retracted:
            continue
        payload = line.get("payload") or {}
        if payload.get("schema") != TASK_SCHEMA or not isinstance(payload.get("title"), str):
            continue
        found = key_of(payload)
        if found is None:
            continue
        key, suffix = found
        seq = int(line["seq"])
        kept = latest.get(key)
        if kept is None or (suffix, seq) > (kept[0], kept[1]):
            latest[key] = (suffix, seq, line)
    tasks: list[Task] = []
    for key, (_suffix, seq, line) in latest.items():
        payload = line["payload"]
        at = str(line["at"])
        tasks.append(
            Task(
                task_id(key),
                key,
                str(payload["title"]),
                str(payload.get("status") or "open"),
                _text(payload.get("due")),
                _text(payload.get("list")),
                at,
                local_date(at, tz),
                seq,
                str(line["id"]),
                str(line.get("source") or ""),
            )
        )
    tasks.sort(key=lambda t: (t.day, t.at, t.seq))
    return tasks


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


# -- the candidates ------------------------------------------------------------------------------------


def candidate_of(line: Line, tz: str) -> Candidate | None:
    """A standing mail, event or transaction line as a candidate, or None when it has no text to
    read (a mail with no subject, an entry with no title, a transaction with no merchant)."""
    kind = str(line.get("kind") or "")
    payload = line.get("payload") or {}
    if kind == MAIL:
        text, sent = payload.get("subject"), payload.get("direction") == "sent"
    elif kind == EVENT:
        text, sent = payload.get("title"), False
    elif kind == TRANSACTION:
        text, sent = payload.get("merchant"), False
    else:
        return None
    if not isinstance(text, str) or not text.strip():
        return None
    at = str(line["at"])
    return Candidate(
        str(line["id"]),
        int(line["seq"]),
        kind,
        str(line.get("source") or ""),
        at,
        local_date(at, tz),
        int(line.get("tier") or 1),
        " ".join(text.split()),
        sent,
    )


def instant(at: str) -> datetime:
    return datetime.fromisoformat(at.replace("Z", "+00:00"))


def in_window(task: Task, at: str, window: timedelta = WINDOW) -> bool:
    """Whether an instant falls in the evidence window of a task: from the task's `at` to `window`
    after it, both ends included."""
    start = instant(task.at)
    return start <= instant(at) <= start + window


# -- the proposals -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Proposal:
    """Evidence that one open task was done: the task, the evidence line (`line`; `lines` every
    line of the same entry when two calendars carry it, its own first, and `sources` theirs), what
    it says, and the matcher's verdict."""

    task: Task
    line: str
    kind: str
    source: str
    at: str
    day: str
    tier: int
    text: str
    evidence: Evidence
    lines: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "task": self.task.id,
            "line": self.line,
            "lines": list(self.lines),
            "kind": self.kind,
            "source": self.source,
            "sources": list(self.sources),
            "at": self.at,
            "day": self.day,
            "tier": self.tier,
            "text": self.text,
            "evidence": self.evidence.to_json(),
        }


@dataclass(frozen=True)
class Report:
    """What one run read: every task as it stands, the proposals in task order then evidence order,
    which matcher read them and over what window."""

    tasks: list[Task]
    proposals: list[Proposal]
    matcher: dict[str, Any]
    window_days: int

    @property
    def open(self) -> list[Task]:
        return [t for t in self.tasks if t.open]


def read(lb: Logbook) -> Report:
    """Every task as it stands, through the index, with no evidence read: `tasks` and `tasks done`."""
    with lb.index() as idx:
        tasks = tasks_of(idx.by_kind(TASK), retractions(idx.retractions()), str(lb.meta["timezone"]))
    return Report(tasks, [], {}, WINDOW.days)


def propose(lb: Logbook, matcher: Matcher = RULES, window: timedelta = WINDOW) -> Report:
    """Every task as it stands, and for each open one the standing mail, event and transaction lines
    of the `window` after it that `matcher` reads as evidence; read through the index, nothing
    written. A calendar entry several sources carry (the same instants and the same text) is one
    proposal naming every line."""
    tz = str(lb.meta["timezone"])
    with lb.index() as idx:
        retracted = retractions(idx.retractions())
        tasks = tasks_of(idx.by_kind(TASK), retracted, tz)
        open_tasks = [t for t in tasks if t.open]
        candidates: list[Candidate] = []
        if open_tasks:
            first = min(t.day for t in open_tasks)
            last = local_date(
                (max(instant(t.at) for t in open_tasks) + window + timedelta(days=1)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                tz,
            )
            for kind in KINDS:
                superseded = idx.superseded(kind)
                for line in idx.by_kind(kind, first, last):
                    if str(line["id"]) in retracted or str(line["id"]) in superseded:
                        continue
                    found = candidate_of(line, tz)
                    if found is not None:
                        candidates.append(found)
    candidates.sort(key=lambda c: (instant(c.at), c.seq))
    proposals: list[Proposal] = []
    for task in open_tasks:
        folded: dict[tuple[str, str, str], Proposal] = {}
        for c in candidates:
            if not in_window(task, c.at, window):
                continue
            verdict = matcher(task, c)
            if verdict is None:
                continue
            key = (c.kind, c.at, normal(c.text))
            kept = folded.get(key)
            if kept is None:
                folded[key] = Proposal(
                    task,
                    c.line,
                    c.kind,
                    c.source,
                    c.at,
                    c.day,
                    c.tier,
                    c.text,
                    verdict,
                    (c.line,),
                    (c.source,),
                )
            elif c.source not in kept.sources:
                folded[key] = Proposal(
                    task,
                    kept.line,
                    kept.kind,
                    kept.source,
                    kept.at,
                    kept.day,
                    max(kept.tier, c.tier),
                    kept.text,
                    kept.evidence,
                    (*kept.lines, c.line),
                    (*kept.sources, c.source),
                )
        proposals.extend(folded.values())
    return Report(tasks, proposals, describe(matcher), window.days)


# -- the close -----------------------------------------------------------------------------------------


def draft_done(task: Task, at: str, evidence: str | None = None) -> dict[str, Any]:
    """The `task/v1` payload that marks a task done at `at` (RFC 0016): the newest snapshot of the
    task, `raw_id` `<key>@<at>`, the title, `due` and `list` carried over, `status` `done`,
    `completed_at` and `modified_at` `at`, `supersedes` the snapshot it replaces, and the evidence
    line's id under `extra.evidence` when the owner named one."""
    payload: dict[str, Any] = {
        "schema": TASK_SCHEMA,
        "raw_id": f"{task.key}@{at}",
        "title": task.title,
        "status": "done",
    }
    if task.due:
        payload["due"] = task.due
    payload["completed_at"] = at
    if task.list:
        payload["list"] = task.list
    payload["modified_at"] = at
    payload["supersedes"] = task.line
    if evidence:
        payload["extra"] = {"evidence": evidence}
    return payload


# -- the text ------------------------------------------------------------------------------------------


def rows(report: Report, tasks: Sequence[Task], clock: Any, open_only: bool = False) -> list[str]:
    """`logbook tasks` as text: a header with the counts, one row per task (day, time, status, the
    due day, the list, the title, the id). `clock(at)` formats an instant as the record's wall clock."""
    if not report.tasks:
        return ["no tasks in the record (task/v1, RFC 0016)"]
    open_count = len(report.open)
    if open_only:
        if not tasks:
            return [f"no open tasks; {_plural(len(report.tasks), 'task')} done"]
        head = f"{_plural(open_count, 'open task')} of {len(report.tasks)}"
    else:
        head = f"{_plural(len(report.tasks), 'task')}, {open_count} open"
    out = [head + " (the latest snapshot of each task is its state, RFC 0016)"]
    status_width = max(len(t.status) for t in tasks) if tasks else 4
    for t in tasks:
        due = f"due {t.due}" if t.due else ""
        where = f"[{t.list}]" if t.list else ""
        out.append(
            f"  {t.day}  {clock(t.at)}  {t.status:<{status_width}}  {due:<14}  “{_cut(t.title)}”"
            + (f"  {where}" if where else "")
            + f"  {t.id}"
        )
    return out


def proposal_rows(report: Report, clock: Any) -> list[str]:
    """`logbook tasks --propose-done` as text: a header that says these are proposals, then for each
    open task with evidence its title, day and id, and under it one row per evidence line (day, time,
    kind, the text, the words shared, `×N sources`, the line id); last, how many open tasks had none."""
    if not report.tasks:
        return ["no tasks in the record (task/v1, RFC 0016)"]
    if not report.open:
        return [f"no open tasks; {_plural(len(report.tasks), 'task')} done"]
    by_task: dict[str, list[Proposal]] = {}
    for p in report.proposals:
        by_task.setdefault(p.task.id, []).append(p)
    without = len(report.open) - len(by_task)
    out: list[str] = []
    if not by_task:
        out.append(
            f"no evidence found for {_plural(len(report.open), 'open task')} in the {report.window_days} days"
            f" after each, read by {report.matcher['name']}"
        )
        return out
    out.append(
        f"{_plural(len(by_task), 'open task')} with evidence of being done, read by {report.matcher['name']},"
        " not facts; close one with `logbook tasks done <id> --evidence <line>`"
    )
    for task in report.open:
        found = by_task.get(task.id)
        if not found:
            continue
        out.append(f"  “{_cut(task.title)}”  ({task.day}, {task.id})")
        for p in found:
            tail = f"  ×{len(p.sources)} sources" if len(p.sources) > 1 else ""
            out.append(
                f"    {p.day}  {clock(p.at)}  {p.kind:<11}  “{_cut(p.text)}”  {' '.join(p.evidence.shared)}"
                f"{tail}  {p.line}"
            )
    if without:
        out.append(f"  {_plural(without, 'open task')} with no evidence found")
    return out


def _cut(text: str) -> str:
    return text if len(text) <= TEXT_WIDTH else text[: TEXT_WIDTH - 1].rstrip() + "…"


def _plural(n: int, noun: str) -> str:
    return f"{n:,} {noun if n == 1 else noun + 's'}"
