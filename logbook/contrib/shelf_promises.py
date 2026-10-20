"""The Promises shelf of `logbook serve`: `/promises`, the promises the record's words suggest, open
first, then kept, then dropped, and `/promises/ID`, one promise and the line it was read in.
Read-only: no form, no act, and nothing judged here.

Everything on it is the promises reader's (`promises.extract`, `docs/promises.md`), read through the
page's gate: `admit` lets in only the lines whose tier the gate reads (`tiers`, as `reading.crossing`
reads it), so no promise, speaker or counterpart rests on a line above it. What the shelf lists is
what `logbook promises` lists: the owner's promises and what was asked of them (`PROMISE`, `ASKED`),
less what a judgement set aside. **Open** is a proposal still open (a carried one too); **kept** one a
task line marked done closed (`promises done`), or, with no task line, the signed day kept;
**dropped** one a task line marked cancelled closed, or the signed day dropped or missed. Each row:
who it is with, what (the sentence as written), when it was said, the due hint, the verdict of the
local model when one is kept, and the evidence: the line it was read in.

The verdict is shown as the reader gives it (`promises._tail`'s words: the confidence, by whom and to
whom when the judge says, `no` for a judged non-commitment), from the judgements `promises --judge`
kept in `policy/promises-cache.json`, read here as the reader reads them (`read_judgements`, the
cache's shape, an entry that is not a whole judgement left out). Nothing is judged here: the shelf
never runs a model.

`?person=NAME` keeps the promises with one person: the counterpart, or a name the line resolves;
never an agent. A promise's page links its transcript line (the line on its Day, `#l-<id>`), and
shows the sentences around it as the reader read them. The page says the highest tier it read.
Nothing is written and no connection is opened."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from html import escape
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from ..core import signing
from ..core.chain import Line
from ..core.store import Logbook
from . import promises, shelf_agents

if TYPE_CHECKING:  # the Site passes itself; serve imports this module, never the other way at import
    from .serve import Site

CACHE_FILE = PurePosixPath("policy/promises-cache.json")  # `promises --judge`'s cache (labs.judge)
OPEN, KEPT, DROPPED = "open", "kept", "dropped"
SECTIONS = ((OPEN, "Open"), (KEPT, "Kept"), (DROPPED, "Dropped"))
DOT = " · "
JUDGED = re.compile(r"^(?:no )?\d")  # the judgement's part of `promises._tail`: `0.9 to Ola`, `no 0.3`
NOTE_WHO = "(note)"  # a promise in a note names nobody it is to
SHELF_STYLE = """
.badge{display:inline-block;font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;padding:0 .35rem;
border:1px solid var(--line);border-radius:3px;color:var(--mute)}
.badge.open{color:#c0652a}.badge.kept{color:#2e8b57}
p.facts{margin:.1rem 0;color:var(--mute);overflow-wrap:anywhere}
q.said{overflow-wrap:anywhere}
p.people{display:flex;flex-wrap:wrap;gap:.2rem .8rem;overflow-wrap:anywhere}
blockquote.said{margin:.3rem 0;padding-left:.6rem;border-left:3px solid var(--line);overflow-wrap:anywhere}
"""  # what the Promises pages add to the one stylesheet; every rule keeps to the column


class PromiseNotFound(LookupError):
    """No promise the page shows has this id."""


@dataclass(frozen=True)
class Row:
    """One promise as the shelf shows it: the reader's proposal, its section, who it is with."""

    proposal: promises.Proposal
    section: str
    who: str
    tier: int
    agent: bool = False  # read in a session with an agent: `who` is the agent, never a person


@dataclass(frozen=True)
class Shelf:
    """The promises through one gate, in day order; the people they are with; the highest tier read."""

    rows: list[Row]
    people: list[str]
    tier: int

    def section(self, name: str, person: str | None = None) -> list[Row]:
        found = [r for r in self.rows if r.section == name and (person is None or _with(r, person))]
        return list(reversed(found)) if name != OPEN else found  # the open oldest first, the closed newest

    def row(self, pid: str) -> Row:
        found = next((r for r in self.rows if r.proposal.id == pid), None)
        if found is None:
            raise PromiseNotFound(f"no promise {pid}")
        return found


def _with(r: Row, person: str) -> bool:
    if r.agent:
        return False  # an agent is nobody: never one of the people the filter keeps
    folded = person.casefold()
    p = r.proposal
    return r.who.casefold() == folded or any(n.casefold() == folded for n in p.names)


def read_judgements(root: Path) -> dict[str, promises.Judgement]:
    """candidate id → its judgement, from `policy/promises-cache.json` as `promises --judge` keeps it:
    empty when there is no file or it is not the cache's shape; an entry that is not a whole judgement
    left out, never a traceback."""
    path = root.joinpath(*CACHE_FILE.parts)
    try:
        data = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, ValueError):
        return {}
    entries = data.get("judgements") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        return {}
    out: dict[str, promises.Judgement] = {}
    for pid, e in entries.items():
        found = _judgement(e) if isinstance(pid, str) and isinstance(e, dict) else None
        if found is not None:
            out[pid] = found
    return out


def _judgement(e: Mapping[str, Any]) -> promises.Judgement | None:
    is_commitment, confidence, due = e.get("is_commitment"), e.get("confidence"), e.get("due")
    if not isinstance(is_commitment, bool) or isinstance(confidence, bool):
        return None
    if not isinstance(confidence, int | float) or not 0 <= confidence <= 1:
        return None
    if not all(isinstance(e.get(k), str) for k in ("by", "to", "what")):
        return None
    if due is not None and not isinstance(due, str):
        return None
    return promises.Judgement(
        is_commitment,
        str(e["by"]),
        str(e["to"]),
        str(e["what"]),
        due or None,
        float(confidence),
        str(e.get("model") or ""),
        str(e.get("judged_at") or ""),
        str(e.get("engine") or ""),
    )


def read(lb: Logbook, tiers: Sequence[int] | None = None) -> Shelf:
    """The shelf through the gate `tiers` (None: every tier). Writes nothing."""
    allowed = None if tiers is None else {int(t) for t in tiers}

    def admit(line: Line) -> bool:
        return allowed is None or int(line.get("tier") or 0) in allowed

    report = promises.with_judgements(promises.extract(lb, admit=admit), read_judgements(lb.root))
    named = {p.line for p in report.proposals}
    named |= {p.closed_by for p in report.proposals if p.closed_by}
    named |= {p.disposition.line for p in report.proposals if p.disposition is not None}
    found = _lines(lb, named)
    tier_of = {i: int(line.get("tier") or 0) for i, line in found.items()}
    with lb.index() as idx:  # a name the record resolves rests on the resolution lines read for it
        resolved = max((int(r.get("tier") or 0) for r in idx.resolutions() if admit(r)), default=0)
    rows: list[Row] = []
    for p in report.proposals:
        if not (p.shows and p.role in (promises.PROMISE, promises.ASKED)):
            continue
        # what closed it counts only through the gate: a close above it is not on this page
        if p.closed_by and not _admitted(allowed, tier_of.get(p.closed_by)):
            p = replace(p, closed_by=None)
        if p.disposition is not None and not _admitted(allowed, tier_of.get(p.disposition.line)):
            p = replace(p, disposition=None)
        read_from = [p.line, *([p.closed_by] if p.closed_by else [])]
        read_from += [p.disposition.line] if p.disposition is not None else []
        agent = shelf_agents.is_session(found.get(p.line) or {})
        tier = max(tier_of.get(i, 0) for i in read_from)
        if p.counterpart or p.names or (p.speaker is not None and p.speaker.person):
            tier = max(tier, resolved)  # who it is with may be a resolution's label: its tier counts
        cancelled = bool(p.closed_by) and _status(found.get(p.closed_by or "")) == "cancelled"
        rows.append(Row(p, _section(p, cancelled), _who(p), tier, agent))
    owner = report.owner
    people = {r.who for r in rows if not r.agent and r.who not in ("?", NOTE_WHO, "")}
    people |= {n for r in rows if not r.agent for n in r.proposal.names}
    return Shelf(
        rows, sorted(people - {owner or ""}, key=str.casefold), max((r.tier for r in rows), default=0)
    )


def _admitted(allowed: set[int] | None, tier: int | None) -> bool:
    return tier is not None and (allowed is None or tier in allowed)


def _lines(lb: Logbook, ids: set[str]) -> dict[str, Line]:
    """The lines a promise was read in and the lines that closed one, by id."""
    if not ids:
        return {}
    with lb.index() as idx:
        return idx.by_ids(ids)


def _status(task: Line | None) -> str | None:
    status = ((task or {}).get("payload") or {}).get("status")
    return status if isinstance(status, str) else None


def _section(p: promises.Proposal, cancelled: bool = False) -> str:
    """Open while the reader says so; dropped when the task line that closed it is `cancelled`, or,
    with no task line, when the signed day dropped or missed it; else kept."""
    if p.status == "open":
        return OPEN
    if p.closed_by:
        return DROPPED if cancelled else KEPT
    d = p.disposition
    if d is not None and d.value in (signing.DROPPED, signing.MISSED):
        return DROPPED
    return KEPT


def _who(p: promises.Proposal) -> str:
    if p.counterpart:
        return p.counterpart
    if p.role == promises.ASKED and p.speaker is not None:
        return p.speaker.display()
    return NOTE_WHO if p.kind == promises.NOTE else "?"


def verdict_text(p: promises.Proposal) -> str:
    """The reader's words after a promise's quote (`promises._tail`): the due hint, the judgement, what
    the signed day said, `done`, each part apart; the judgement's part says it is the judge's."""
    parts = [part.strip() for part in promises._tail(p).split("  ") if part.strip()]
    if p.judgement is not None:
        parts = [f"judged {part}" if JUDGED.match(part) else part for part in parts]
    return DOT.join(parts)


# -- the pages ---------------------------------------------------------------------------------------------


def promise_path(pid: str) -> str:
    return f"/promises/{pid}"


def day_line(day: str, line: str) -> str:
    """The line's row on its Day: the anchor the Day gives every row (`serve._row_id`)."""
    return f"/day/{day}#l-" + "".join(c for c in line if c.isalnum() or c == "-")


def page_promises(site: Site, person: str | None = None) -> str:
    """`/promises`: open first (the oldest first), then kept and dropped (the newest first), each row
    who, what, when it was said, the evidence line; `person` keeps one person's."""
    shelf = site.shared(("promises",), lambda: read(site.lb, site.tiers))
    person = person.strip() if person and person.strip() else None
    shown = [r for r in shelf.rows if person is None or _with(r, person)]
    parts = [f"<h1>Promises {site.tier_small(_plural(len(shown), 'promise'), shelf.tier)}</h1>\n"]
    if not shelf.rows:
        if site.tiers is not None:
            parts.append(
                f'<p class="mute">No promise this page reads: it reads tier {_tiers_text(site.tiers)} only,'
                " and a promise is at the tier of the line it was read in (a note, a mail, a message or a"
                " transcript is tier 2).</p>\n"
            )
        else:
            parts.append(
                "<p>No promises proposed yet: the promises reader finds them in what you wrote, your"
                " notes, your mail and messages sent and your turns in a transcript"
                " (<code>logbook promises</code>).</p>\n"
            )
        return site.document("promises", "".join(parts), style=SHELF_STYLE)
    parts.append(
        '<p class="mute">What your words suggest you promised, and what was asked of you: read by rules,'
        " not facts, and a verdict only where the local model already gave one. Close one with"
        " <code>logbook promises done ID</code> or when you sign its day.</p>\n"
    )
    if shelf.people:
        links = [site.link("everyone", "/promises") if person else "<b>everyone</b>"]
        for name in shelf.people:
            text = escape(name)
            links.append(
                f"<b>{text}</b>"
                if person and name.casefold() == person.casefold()
                else site.link(text, f"/promises?person={quote(name)}")
            )
        parts.append(f'<p class="people">{" ".join(links)}</p>\n')
    if person is not None and not shown:
        parts.append('<p class="mute">no promise with anyone of that name on this page</p>\n')
    for name, title in SECTIONS:
        found = shelf.section(name, person)
        parts.append(f"<h2>{title} <small>{len(found):,}</small></h2>\n")
        if not found:
            parts.append('<p class="mute">none</p>\n')
            continue
        parts.append('<ol class="shelf">\n')
        parts.extend(_row_html(site, r) for r in found)
        parts.append("</ol>\n")
    return site.document("promises", "".join(parts), style=SHELF_STYLE)


def _role(r: Row) -> str:
    who = f"the agent {r.who}" if r.agent else r.who
    if r.proposal.role == promises.ASKED:
        return f"asked of you by {who}"
    return "you, in a note" if r.who == NOTE_WHO else f"you, to {who}"


def _row_html(site: Site, r: Row) -> str:
    p = r.proposal
    head = [
        f'<span class="badge {r.section}">{escape(r.section)}</span>',
        site.link(f'<q class="said">{escape(p.match.quote)}</q>', promise_path(p.id)),
    ]
    facts = [_role(r), f"said {p.day}", f"{p.kind} {p.source}".strip()]
    verdict = verdict_text(p)
    if verdict:
        facts.append(verdict)
    evidence = site.link(f"the line {escape(p.line[:8])}…", day_line(p.day, p.line))
    return (
        f'<li id="{escape(p.id)}"><p class="head">{" ".join(head)}</p>\n'
        f'<p class="facts">{escape(DOT.join(facts))}{DOT}{evidence}</p></li>\n'
    )


def page_promise(site: Site, pid: str) -> str:
    """`/promises/ID`: one promise: what, who, when, its state and verdict, the sentences around it, and
    the line it was read in, linked on its Day."""
    shelf = site.shared(("promises",), lambda: read(site.lb, site.tiers))
    try:
        r = shelf.row(pid)
    except PromiseNotFound as e:
        from .serve import NotFound  # serve is loaded by now: it is what called this page

        raise NotFound(f"no page at {promise_path(pid)}: {e}, or none this page reads") from None
    p = r.proposal
    parts = [
        f'<h1><q class="said">{escape(p.match.quote)}</q> <small>promise{DOT}tier {r.tier}</small></h1>\n',
        f'<p class="head"><span class="badge {r.section}">{escape(r.section)}</span>'
        f' <span class="mute">{escape(_role(r))}</span></p>\n',
    ]
    facts = [f"said {p.day}", f"{p.kind} from {p.source}" if p.source else p.kind]
    if p.title:
        facts.append(f"“{p.title}”")
    if p.due:
        facts.append(f"due {p.due}?")
    parts.append(f'<p class="facts">{escape(DOT.join(facts))}</p>\n')
    verdict = verdict_text(p)
    if verdict:
        parts.append(f'<p class="facts">the reader says: {escape(verdict)}</p>\n')
    if p.judgement is not None:
        j = p.judgement
        parts.append(
            f'<p class="facts">judged by {escape(j.model or "a local model")}'
            f" on {escape(j.judged_at[:10] or '?')}: {escape(j.what)}</p>\n"
        )
    if p.before or p.after:
        parts.append("<h2>Around it</h2>\n")
        for said in p.before:
            parts.append(
                f'<blockquote class="said mute">{escape(said.speaker)}: {escape(said.text)}</blockquote>\n'
            )
        speaker = p.speaker.display() if p.speaker is not None else "?"
        parts.append(
            f'<blockquote class="said"><b>{escape(speaker)}: {escape(p.match.quote)}</b></blockquote>\n'
        )
        for said in p.after:
            parts.append(
                f'<blockquote class="said mute">{escape(said.speaker)}: {escape(said.text)}</blockquote>\n'
            )
    parts.append('<h2>Evidence</h2>\n<ul class="plain">\n')
    word = "transcript line" if p.kind == promises.TRANSCRIPT else f"{p.kind} line"
    parts.append(
        f"<li>{site.link(f'the {word} it was read in, on {escape(p.day)}', day_line(p.day, p.line))}"
        f' <span class="mute" title="line {escape(p.line)}">{escape(p.line[:8])}…</span></li>\n'
    )
    if p.closed_by:
        task = escape(p.closed_by)
        parts.append(
            f'<li>closed by the task line <span class="mute" title="line {task}">{task[:8]}…</span></li>\n'
        )
    if p.disposition is not None:
        d = p.disposition
        parts.append(
            f"<li>{site.link(f'{escape(d.value)} on the signed day {escape(d.day)}', f'/day/{d.day}')}"
            f' <span class="mute" title="line {escape(d.line)}">{escape(d.line[:8])}…</span></li>\n'
        )
    parts.append("</ul>\n")
    parts.append(f'<p class="mute">proposal {escape(p.id)}</p>\n')
    parts.append(f"<p>{site.link('Promises', '/promises')}</p>\n")
    return site.document(p.match.quote, "".join(parts), style=SHELF_STYLE)


def _tiers_text(tiers: Sequence[int]) -> str:
    return ", ".join(str(t) for t in sorted({int(t) for t in tiers})) or "none"


def _plural(n: int, noun: str) -> str:
    return f"{n:,} {noun if n == 1 else noun + 's'}"
