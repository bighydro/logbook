"""Keep and sign (RFC 0043 §5; slices C and E, part 1): what the owner keeps at the close of a day,
written before the signature, under the hold of the writer lock the signing command takes.

`day sign DAY` and `day reflect DAY --sign` take, beside their own flags:

- `--keep N,N`: the numbered sentences, links and photo of the day's standing draft, as `logbook day
  DAY` numbers them (`drafts.keep_numbers`: a link keeps its proposal number, a sentence of a part one
  keeps is numbered after the last proposal). A sentence learned, decided or about an idea is kept as
  one `note/v1` line through `notes.write`, labelled `learned`, `decision` or `idea`, its `extra` the
  draft's id (`from`), its part and place among the draft's segments (`segment`), the proposal it
  keeps (`proposal`: its part and its words, so a later draft that says the same is shown kept, RFC
  0043 §6 rule 5), an idea's entity (`entity`) and a decision's `revisit`. A link is the `entity/v1`
  line `entity_review.accept` writes for it (`entity_review.drafted`), on the day, `extra.from` and
  `extra.proposal` beside the review's own keys. The photo of the day is a star with its note
  (`stars.star`: a `keeper/v1` of lane `memory`, RFC 0043 §12), never a note label.
- `--mend N="…"`: a kept sentence in the owner's own words; the note (or the star's note) carries
  them, `extra.from` and `extra.proposal` still the draft's.
- `--revisit N=YYYY-MM-DD`: on a kept decision, `extra.revisit`, a local day after the day signed;
  the day Looking back brings the decision back on (RFC 0043 §4.8, §4.12).
- `--word WORD`: the day in a word (§4.14), one word of the owner's own, as a `note/v1` labelled
  `word`; one on a day, so a re-sign keeps the first.
- `--done T,T`, `--tomorrow T,T`, `--let-go T,T`: the plan answered (§9, the owner's decision of 22
  October 2026). T is a task's number as `show plan DAY` lists today's tasks (`plan.read`). Each answer
  is one `note/v1` on the day labelled `task`: the task's title as its text, `extra.task` the Notion
  row's id, `extra.line` the row's line `show plan` reports, `extra.outcome` `done`, `tomorrow` or
  `let-go`. Not a disposition of the signature: those name lines on the day's page, and a task's line
  is usually an earlier day's (RFC 0034 amendment 5 stays for after v1). Nothing is written to Notion:
  the notes cross with the signed day under the destination's entry, at their tier, and the agent
  that runs the task tool applies them (`docs/plan.md`, *What the record answers*).

`prepared` checks every item before the first line is written, and refuses in one sentence
(`KeepError`): a number the draft does not give, an event (`--accept` writes it), a sentence or link
with nothing under it, one kept already, a photo starred already, a mend or a revisit for a sentence
not kept, a revisit that is not a later day, a word that is two or a number, a second word on the day,
a task given two answers, one `show plan` does not list, one answered already. `write` writes them in
order: the sentences (by number), the links, the photo, the word, the answers. A re-sign keeps what an
earlier close kept, since those lines are on the page; it never writes them again. A model writes
none of this: it drafts, the owner keeps. Nothing here opens a socket."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..core import day_start, drafts, notes, stars
from ..core.chain import Line
from ..core.store import Logbook, retractions
from . import entity_review, plan

SOURCE = "reflect"  # the `source` of the notes the close writes, as `reflect.SOURCE` and `plan.ANSWER_SOURCE`
LABELS = {drafts.LEARNED: "learned", drafts.DECISION: "decision", drafts.IDEAS: "idea"}  # part → note label
WORD = "word"  # the day in a word (RFC 0043 §4.14)
FLAGS = ("--keep", "--mend", "--revisit", "--word", "--done", "--tomorrow", "--let-go")
OUTCOME_FLAGS = {plan.DONE_TODAY: "--done", plan.TOMORROW: "--tomorrow", plan.LET_GO: "--let-go"}
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_NUMBER = re.compile(r"[-+]?[\d.,:/'%]*\d[\d.,:/'%]*")  # 42, 3.5, 7/10, 100%: a number, not a word


class KeepError(ValueError):
    """What Keep and sign refuses; the message says why in one sentence and nothing is written."""


@dataclass(frozen=True)
class Asked:
    """What the owner asked to keep, as typed: the numbers kept, the sentences mended and the decisions
    dated by number, the word, and the tasks answered by outcome."""

    keep: tuple[int, ...] = ()
    mend: Mapping[int, str] = field(default_factory=dict)
    revisit: Mapping[int, str] = field(default_factory=dict)
    word: str | None = None
    tasks: Mapping[str, tuple[int, ...]] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.keep or self.mend or self.revisit or self.word is not None or self.tasks)


def numbers(text: str, flag: str) -> tuple[int, ...]:
    """`N,N` as the numbers in order, each once; anything else refused naming the flag."""
    found: list[int] = []
    for word in text.split(","):
        word = word.strip()
        if not word:
            continue
        if not word.isdigit() or int(word) < 1:
            raise KeepError(f"{flag} takes numbers as printed, N,N; not {word!r}")
        if int(word) not in found:
            found.append(int(word))
    if not found:
        raise KeepError(f"{flag} names no number; leave it out to keep nothing")
    return tuple(found)


def pairs(entries: Sequence[str] | None, flag: str, example: str) -> dict[int, str]:
    """`N=VALUE`, given once or more, as number → value; a number given twice is refused."""
    found: dict[int, str] = {}
    for entry in entries or ():
        number, sep, value = entry.partition("=")
        if not sep or not number.strip().isdigit() or int(number) < 1:
            raise KeepError(f"{flag} takes N={example}, the number as printed; not {entry!r}")
        if int(number) in found:
            raise KeepError(f"{flag} names {int(number)} twice; give it once")
        found[int(number)] = value
    return found


def asked(
    keep: str | None = None,
    mend: Sequence[str] | None = None,
    revisit: Sequence[str] | None = None,
    word: str | None = None,
    done: str | None = None,
    tomorrow: str | None = None,
    let_go: str | None = None,
) -> Asked:
    """The flags as typed, parsed; their meaning is checked by `prepared`."""
    answers = {
        outcome: numbers(text, OUTCOME_FLAGS[outcome])
        for outcome, text in ((plan.DONE_TODAY, done), (plan.TOMORROW, tomorrow), (plan.LET_GO, let_go))
        if text is not None
    }
    return Asked(
        keep=() if keep is None else numbers(keep, "--keep"),
        mend=pairs(mend, "--mend", '"your words"'),
        revisit=pairs(revisit, "--revisit", "YYYY-MM-DD"),
        word=word,
        tasks=answers,
    )


def given(a: Any) -> list[str]:
    """The flags of Keep and sign given on a parsed command line, as typed, for a refusal."""
    return [flag for flag in FLAGS if getattr(a, flag[2:].replace("-", "_"), None) is not None]


def from_args(a: Any) -> Asked:
    return asked(a.keep, a.mend, a.revisit, a.word, a.done, a.tomorrow, a.let_go)


@dataclass(frozen=True)
class Item:
    """One line Keep and sign will write, made before the first is written: a note (`text`, `label`,
    `extra`), a link (`link`, the review's report and proposal), or the photo's star (`photo`, the
    photo line's id, and `text` its note); `head` what the command says of it."""

    head: str
    text: str = ""
    label: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)
    link: tuple[entity_review.Report, entity_review.Proposal] | None = None
    photo: str | None = None


def prepared(lb: Logbook, day: str, a: Asked, tiers: Sequence[int] | None = None) -> list[Item]:
    """Every item `a` asks for, checked and made, in the order `write` writes them, before the first is
    written; read under the writer lock the caller holds. The draft kept from is read through the gate
    `tiers` when given (the Day page's, so a page never keeps a sentence it could not show); the command
    reads every tier. `KeepError` names the first refusal."""
    items = _sentences(lb, day, a, tiers) if a.keep or a.mend or a.revisit else []
    if a.word is not None:
        items.append(_word(lb, day, a.word, tiers))
    if a.tasks:
        items += _tasks(lb, day, a.tasks)
    return items


def write(
    lb: Logbook,
    day: str,
    today: str,
    items: Sequence[Item],
    say: Callable[[str], None],
    at: str | None = None,
) -> list[Line]:
    """The items as their lines, in order, each said as it is written: a note through `notes.write`, a
    link through `entity_review.accept`, both at the moment the owner signed (`at`) when it is on the
    day, else at the moment a note on the day takes (`notes.moment`: now on today, else the day's last
    minute); the photo through `stars.star`. The lines written, for the signature to confirm."""
    written: list[Line] = []
    when = moment(lb, day, today, at)
    for item in items:
        if item.link is not None:
            report, proposal = item.link
            line = entity_review.accept(lb, report, [(proposal, None)], at=when)[0].lines[0]
            into = proposal.canonical.label if proposal.canonical is not None else report.kind
            say(f"kept {item.head} as #{line['seq']} entity/v1, binding {proposal.observed.name} to {into}")
        elif item.photo is not None:
            _photo, star = stars.star(lb, item.photo, item.text)
            if star is None:  # checked by `prepared`: a photo with a star standing is refused there
                continue
            line = star
            say(f"kept {item.head} as #{line['seq']} keeper/v1, the photo starred with its note")
        else:
            line = notes.write(lb, day, item.text, str(item.label), SOURCE, when, today, item.extra)
            say(f"kept {item.head} as #{line['seq']} note/v1, labelled {item.label}")
        written.append(line)
    return written


def moment(lb: Logbook, day: str, today: str, at: str | None) -> str:
    """When the close's lines are written: `at`, the moment the owner signed, when it falls on the day
    (a signature given the next morning is not), else what a note on the day takes without one."""
    tz, days = str(lb.meta["timezone"]), day_start.of(lb.meta)
    if at is not None:
        try:
            return notes.moment(day, tz, at, today, days)
        except ValueError:  # after the day: the note's own default, never a note off its day
            pass
    return notes.moment(day, tz, None, today, days)


# -- the draft's sentences, links and photo ----------------------------------------------------------------


def _sentences(lb: Logbook, day: str, a: Asked, tiers: Sequence[int] | None = None) -> list[Item]:
    with lb.index() as idx:
        draft, withheld = drafts.for_day(idx, day, tiers, allowed=drafts.allowed(lb.root))
        above = drafts.kept_on_day(idx, day) if tiers is not None else {}  # kept by a line above the gate
    if draft is None:
        why = f"; the standing draft is {drafts.withheld_text(withheld)}" if withheld is not None else ""
        if tiers is not None:
            gate = ", ".join(str(t) for t in sorted({int(t) for t in tiers}))
            why = f" at the tiers this page reads ({gate})"
        raise KeepError(f"{day} has no draft to keep from{why}; `logbook dream day {day}` dreams one")
    keepable: dict[int, tuple[str, dict[str, Any], int | None]] = {}  # number → (part, block, segment n)
    for i, segment in enumerate(draft["segments"]):
        if segment.get("keep"):
            keepable[int(segment["keep"])] = (str(segment["part"]), segment, i + 1)
    for link in draft.get("links") or []:
        keepable[int(link["keep"])] = (drafts.LINK, link, None)
    events = {int(p["number"]) for p in draft.get("proposals") or []}
    for flag, wanted in (("--mend", a.mend), ("--revisit", a.revisit)):
        for n in wanted:
            if n not in a.keep:
                noun = "a decision" if flag == "--revisit" else "a sentence"
                raise KeepError(f"{flag} {n} names {noun} not kept; give {n} to --keep too")
    items: list[Item] = []
    links: list[Item] = []
    photo: list[Item] = []
    bound: dict[Any, int] = {}
    for n in sorted(a.keep):
        if n not in keepable:
            if n in events:
                raise KeepError(f"proposal {n} is an event; `--accept {n}` writes it into the record")
            numbered = ", ".join(map(str, sorted(keepable))) or "none"
            raise KeepError(
                f"no keepable sentence or link {n} in the draft of {day} ({numbered}); `logbook day {day}`"
                " numbers them"
            )
        part, block, segment_n = keepable[n]
        head = f"{drafts.PART_LABELS.get(part, part)} {n}"
        if block.get("kept"):
            raise KeepError(f"{head} is kept already, as #{block['kept']['seq']}; a re-sign keeps it")
        if _key(part, block) in above:  # said to be kept, never which line keeps it
            raise KeepError(f"{head} is kept already, at a tier this page does not read; a re-sign keeps it")
        if not block.get("supported"):
            raise KeepError(f"{head} rests on no line of the day, so there is nothing to keep")
        mended = a.mend.get(n)
        if mended is not None and part == drafts.LINK:
            raise KeepError(f"--mend {n}: {head} is a link, with no words of its own to mend")
        if mended is not None and not mended.strip():
            raise KeepError(f"--mend {n} is empty; give your words, or leave it out to keep the draft's")
        revisit = a.revisit.get(n)
        if revisit is not None and part != drafts.DECISION:
            raise KeepError(f"--revisit {n}: {head} is not a decision; a revisit day goes with a decision")
        text = " ".join(mended.split()) if mended is not None else str(block["text"])
        if part == drafts.LINK:
            links.append(_link(lb, draft, block, n, head, bound))
        elif part == drafts.PHOTO:
            photo.append(_photo(lb, block, n, head, text))
        else:
            extra: dict[str, Any] = {
                drafts.KEPT_FROM: str(draft["line"]),
                "segment": {"part": part, "n": segment_n},
                drafts.KEPT_PROPOSAL: {"kind": part, "text": str(block["text"])},
            }
            if part == drafts.IDEAS and isinstance(block.get("entity"), str):
                extra["entity"] = block["entity"]
            if revisit is not None:
                extra["revisit"] = _revisit(day, n, revisit)
            items.append(Item(head, text, LABELS[part], extra))
    return [*items, *links, *photo]


def _key(part: str, block: Mapping[str, Any]) -> tuple[Any, ...] | None:
    """The proposal a keepable sentence or link is, as `drafts.kept_keys` keys what was kept."""
    if part == drafts.LINK:
        return drafts.proposal_key(block)
    return drafts.proposal_key({"kind": part, "text": block.get("text")})


def _revisit(day: str, n: int, text: str) -> str:
    value = text.strip()
    try:
        when = date.fromisoformat(value) if _DAY.match(value) else None
    except ValueError:
        when = None
    if when is None:
        raise KeepError(f"--revisit {n}={text!r} is not a day; give it as YYYY-MM-DD")
    if when.isoformat() <= day:
        raise KeepError(f"--revisit {n}={value}: a revisit day comes after {day}, the day you sign")
    return when.isoformat()


def _link(
    lb: Logbook, draft: Mapping[str, Any], link: Mapping[str, Any], n: int, head: str, bound: dict[Any, int]
) -> Item:
    evidence = [str(e) for e in link["evidence"]]
    extra = {
        drafts.KEPT_FROM: str(draft["line"]),
        drafts.KEPT_PROPOSAL: {"kind": drafts.LINK, "entity": str(link["entity"]), "evidence": evidence},
    }
    try:
        report, proposal = entity_review.drafted(lb, str(link["entity"]), evidence, n, extra)
    except entity_review.ReviewError as e:
        raise KeepError(str(e)) from None
    other = bound.setdefault(proposal.observed.key, n)
    if other != n:
        raise KeepError(f"links {other} and {n} bind {proposal.observed.name} twice; keep one of them")
    return Item(head, link=(report, proposal))


def _photo(lb: Logbook, segment: Mapping[str, Any], n: int, head: str, text: str) -> Item:
    evidence = [str(e) for e in segment.get("evidence") or []]
    if len(evidence) != 1:
        raise KeepError(f"{head} names {len(evidence)} lines; the photo of the day is one photo")
    try:
        line, current = stars.checked(lb, evidence[0])
        note = stars.note_of(text)
    except stars.StarError as e:
        raise KeepError(f"{head}: {e}") from None
    if line.get("kind") != stars.PHOTO:
        raise KeepError(f"{head} rests on #{line['seq']}, a {line.get('kind')}, not a photo")
    if current is not None:
        raise KeepError(
            f"{head} is kept already: its photo, #{line['seq']}, has a star standing (yours, or the library's"
            " favourite), and a re-sign keeps it"
        )
    return Item(head, note or "", photo=str(line["id"]))


# -- the word ----------------------------------------------------------------------------------------------


def _word(lb: Logbook, day: str, text: str, tiers: Sequence[int] | None = None) -> Item:
    word = text.strip()
    if not word:
        raise KeepError("--word is empty; give one word, or leave it out")
    if len(word.split()) != 1:
        raise KeepError(f"--word takes one word, not {len(word.split())}: the day in a word")
    if _NUMBER.fullmatch(word):
        raise KeepError(f"--word {word!r}: the day in a word is a word, not a number")
    with lb.index() as idx:
        lines = idx.day(day)
        retracted = retractions(idx.retractions())
    standing = notes.standing(lines, WORD, retracted)
    if standing:
        first = standing[0]
        if tiers is not None and int(first.get("tier") or 0) not in {int(t) for t in tiers}:
            raise KeepError(  # a word above the page's gate: said to stand, never quoted
                f"{day} has its word already, at a tier this page does not read, and a re-sign keeps it;"
                f" `logbook day {day}` shows it"
            )
        said = (first.get("payload") or {}).get("text")
        raise KeepError(
            f"{day} has its word already, “{said}” (#{first['seq']}), and a re-sign keeps it; to change it,"
            f' `logbook repair retract {first["seq"]} "another word"`, then sign again with --word'
        )
    return Item(f"the day in a word, “{word}”,", word, WORD)


# -- the plan answered -------------------------------------------------------------------------------------


def _tasks(lb: Logbook, day: str, answers: Mapping[str, Sequence[int]]) -> list[Item]:
    given_to: dict[int, str] = {}
    for outcome, wanted in answers.items():
        for n in wanted:
            other = given_to.setdefault(n, outcome)
            if other != outcome:
                raise KeepError(
                    f"task {n} is given two answers, {OUTCOME_FLAGS[other]} and {OUTCOME_FLAGS[outcome]};"
                    " a task has one"
                )
    try:
        found = plan.read(lb, day)
    except plan.PlanError as e:
        raise KeepError(str(e)) from None
    first = min(given_to)
    if not found.mapped:
        raise KeepError(f"no task {first}: {plan.NO_MAPPING.rstrip('.')}")
    if found.tasks is None:
        raise KeepError(f"no task {first}: the plan in {plan.PLAN_FILE} names no tasks database")
    rows = found.tasks["rows"]
    items: list[Item] = []
    for n in sorted(given_to):
        if not 1 <= n <= len(rows):
            listed = f"{len(rows)} of them" if rows else "none"
            raise KeepError(f"no task {n}; `logbook show plan {day}` numbers the day's tasks, {listed}")
        row, outcome = rows[n - 1], given_to[n]
        title = str(row.get("title") or plan.UNTITLED)
        if row.get("answered"):
            was = plan.ANSWERED[row["answered"]["outcome"]]
            raise KeepError(
                f"{_task_named(title, n)} is answered on {day} already ({was}); a re-sign keeps it"
            )
        extra = {"task": str(row["id"]), "line": row["line"], "outcome": outcome}
        head = f"the answer to {_task_named(title, n)}, {plan.ANSWERED[outcome]},"
        items.append(Item(head, title, plan.TASK, extra))
    return items


def _task_named(title: str, n: int) -> str:
    """A task in a sentence: its title first, then its number, “Ola: ferry tickets” (task 3), so a
    number never sits beside a name a title opens with."""
    return f"\u201c{title}\u201d (task {n})"
