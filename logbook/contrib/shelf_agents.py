"""The Agents shelf of `logbook serve`: `/agents`, the owner's sessions with their own agents by day,
the latest day first (docs/adapters/agents.md). Read-only: no form, no act.

A **session** is one of two things the adapters of #279 and #305 write. A `transcript/v1` line with a
machine participant (a Claude Code session, `source` `claude-code`; a conversation of the Claude
apps, `source` `claude`), standing: not retracted and not superseded by the line a grown session
wrote after it. Or the `message/v1` lines of one conversation with an agent (`extra.counterpart` of
kind `agent`: a Telegram bot) on one local day, both sides. Every line is read through the page's
gate (`tiers`, as `reading.crossing` reads it): a session at a tier the gate does not read is not on
the page, nor counted, and a Telegram day shows only the messages the gate reads.

Each session shows its **source** and agent, its **length** (the minutes from its first line to its
last, the turns or messages of each side, the words of each side and the tool calls, as the source
counted them), **the owner's words** (their turns or messages, read through `core.machine`, the
first `SHOWN` and the rest folded), and **the agent's summary**: the provider's own `summary` of a
transcript (RFC 0004) when it made one, else the title the source derived for it when that is not the
owner's own first line (Claude Code's own summary of a session, the apps' name for a conversation),
and the agent's words folded beside it, marked as machine text, never as anyone's. A summary is
read from the session's own line, so it is at that line's tier, never above. A session **served a
goal** only when a standing `review/v1` line says so, naming the session's line (or one of its
messages) in `extra.lines` (`shelf_goals`): the goal is linked, and otherwise nothing is said; no
goal is guessed from the words.

`?day=YYYY-MM-DD` is one day; `?page=N` the days `PAGE_DAYS` at a time. The page says the highest
tier it read. Nothing is written and no connection is opened."""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import TYPE_CHECKING, Any, NamedTuple

from ..core import day_start, goals, machine, reading
from ..core.chain import Line
from ..core.export import parse_day
from ..core.index import Index
from ..core.store import Logbook, retractions
from ..core.transcripts import Turn, turns_of

if TYPE_CHECKING:  # the Site passes itself; serve imports this module, never the other way at import
    from .serve import Site

TRANSCRIPT, MESSAGE = "transcript", "message"
SOURCES = {"claude-code": "Claude Code", "claude": "Claude", "telegram": "Telegram"}
PAGE_DAYS = 14  # days of sessions a page; "earlier" is the next page
SHOWN = 3  # the owner's turns shown before the rest fold
CHARS = 280  # a turn shown longer than this is cut, and whole in a fold of its own; a folded turn is whole
DOT = goals.DOT
SHELF_STYLE = """
.badge{display:inline-block;font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;padding:0 .35rem;
border:1px solid var(--line);border-radius:3px;color:var(--mute)}
p.facts{margin:.1rem 0;color:var(--mute);overflow-wrap:anywhere}
blockquote.said{margin:.3rem 0;padding-left:.6rem;border-left:3px solid var(--line);overflow-wrap:anywhere;
white-space:pre-wrap}
blockquote.machine{color:var(--mute);font-style:italic}
p.summary{margin:.2rem 0;overflow-wrap:anywhere}
p.pager{display:flex;flex-wrap:wrap;gap:.8rem}
"""  # what the Agents page adds to the one stylesheet; every rule keeps to the column


@dataclass(frozen=True)
class Session:
    """One session with an agent: its anchor line (a transcript's line, a Telegram day's first
    message), every line it is, its day, source and agent, title and summary, its length, the
    owner's words and the agent's, the counts the source kept, the goals a review says it served,
    and the highest tier of its lines."""

    line: str
    lines: tuple[str, ...]
    day: str
    at: str
    end: str | None
    source: str
    agent: str
    title: str | None
    summary: str | None  # the provider's own summary, else its title when not the owner's first line
    owner: tuple[str, ...]
    machine: tuple[str, ...]
    words: Mapping[str, int]
    tool_calls: int | None
    served: tuple[tuple[str, str], ...]  # (standing goal line, its text) a review names it for
    tier: int

    @property
    def minutes(self) -> int | None:
        if self.end is None:
            return None
        try:
            a = datetime.fromisoformat(self.at.replace("Z", "+00:00"))
            b = datetime.fromisoformat(self.end.replace("Z", "+00:00"))
        except ValueError:
            return None
        return max(0, round((b - a).total_seconds() / 60))


@dataclass(frozen=True)
class Shelf:
    """The sessions through one gate, the latest day first, and the highest tier read (0: none)."""

    sessions: list[Session]
    tier: int

    def days(self) -> list[tuple[str, list[Session]]]:
        out: dict[str, list[Session]] = {}
        for s in self.sessions:
            out.setdefault(s.day, []).append(s)
        return sorted(out.items(), key=lambda kv: kv[0], reverse=True)


def is_session(line: Mapping[str, Any]) -> bool:
    """Whether a line is a session's, or one message of one: a transcript with a machine participant,
    or a message of a conversation with an agent."""
    payload = line.get("payload") or {}
    if line.get("kind") == TRANSCRIPT:
        parts = payload.get("participants")
        return isinstance(parts, list) and any(machine.is_machine_participant(p) for p in parts)
    return line.get("kind") == MESSAGE and machine.with_agent(payload)


def _superseded(idx: Index, kind: str) -> set[str]:
    """The lines of `kind` a standing line supersedes (a grown session's earlier line), by the index's
    one rule (#321): a retracted superseder supersedes nothing, so the earlier line stands again."""
    return set(idx.superseded(kind))


def _standing(idx: Index, kind: str, tiers: Sequence[int] | None, retracted: Collection[str]) -> list[Line]:
    """The standing sessions of `kind` the gate reads, in chain order: the kind streamed, so the
    record's messages are read one at a time and only an agent's are kept."""
    superseded = _superseded(idx, kind)
    return [
        line
        for line in idx.stream(kind)
        if reading.crossing([line], tiers)
        and str(line["id"]) not in retracted
        and str(line["id"]) not in superseded
        and is_session(line)
    ]


def sessions_among(
    idx: Index,
    ids: Collection[str],
    tiers: Sequence[int] | None,
    retracted: Collection[str],
    days: day_start.DayStart,
) -> dict[str, str]:
    """Of `ids`, the lines the gate reads that are a session's (or a message of one), standing: id →
    its local day. What a goal's page lists as the sessions that served it."""
    if not ids:
        return {}
    named = [
        line
        for line in reading.crossing(idx.by_ids(ids).values(), tiers)
        if str(line["id"]) not in retracted and is_session(line)
    ]
    superseded = {i for kind in {str(line["kind"]) for line in named} for i in _superseded(idx, kind)}
    return {
        str(line["id"]): days.day_of(str(line["at"])) for line in named if str(line["id"]) not in superseded
    }


class Standing(NamedTuple):
    """The lines the shelf is made of, through the gate: the standing sessions of each kind and the
    goals and reviews that say a session served a goal. What every page of the shelf reads alike (the
    Library keeps it while the record stands); which turns are read depends on the page."""

    transcripts: list[Line]
    messages: list[Line]
    goal_lines: list[Line]
    reviews: list[Line]


def standing(lb: Logbook, tiers: Sequence[int] | None = None) -> Standing:
    with lb.index() as idx:
        retracted = retractions(idx.retractions())
        transcripts = _standing(idx, TRANSCRIPT, tiers, retracted)
        messages = _standing(idx, MESSAGE, tiers, retracted)
        goal_lines = [
            g for g in reading.crossing(idx.by_kind(goals.KIND), tiers) if str(g["id"]) not in retracted
        ]
        reviews = goals.review_lines(reading.crossing(idx.by_kind(goals.REVIEW), tiers), retracted)
    return Standing(transcripts, messages, goal_lines, reviews)


def read(
    lb: Logbook,
    tiers: Sequence[int] | None = None,
    shown: Callable[[list[str]], Collection[str]] | None = None,
    lines: Standing | None = None,
) -> Shelf:
    """Every session through the gate `tiers` (None: every tier), the latest first. `shown`, given
    the days that have a session (the latest first), names the days whose turns are read from the
    attachment store; the other days' sessions are counted, their words left unread. `lines` is
    `standing` of this record and gate, when read already. Writes nothing."""
    days = day_start.of(lb.meta)
    transcripts, messages, goal_lines, reviews = lines or standing(lb, tiers)
    served = _served(goal_lines, reviews)
    every = sorted({days.day_of(str(line["at"])) for line in [*transcripts, *messages]}, reverse=True)
    wanted = set(every) if shown is None else set(shown(every))
    found = [
        _transcript(lb, line, days, served, days.day_of(str(line["at"])) in wanted) for line in transcripts
    ]
    found.extend(_telegram(group, days, served) for group in _conversations(messages, days))
    found.sort(key=lambda s: (s.day, s.at, s.line), reverse=True)
    return Shelf(found, max((s.tier for s in found), default=0))


class Served(dict[str, list[tuple[str, str]]]):
    """line id → the goals (standing line, text) whose reviews name it in `extra.lines`; `tier`, line
    id → the highest tier of the reviews and goal lines that say so, which a session's row shows."""

    def __init__(self) -> None:
        super().__init__()
        self.tier: dict[str, int] = {}


def _served(goal_lines: Sequence[Line], reviews: Sequence[Line]) -> Served:
    """line id → the goals (standing line, text) whose reviews name it in `extra.lines`."""
    chain = goals.Goals(goal_lines)
    out = Served()
    for review in reviews:
        payload = review.get("payload") or {}
        extra = payload.get("extra")
        named = extra.get("lines") if isinstance(extra, Mapping) else None
        current = chain.current(str(payload.get("goal")))
        if not isinstance(named, list) or current is None:
            continue  # a review of a goal the gate does not read names nothing here
        goal = (str(current["id"]), str((current.get("payload") or {}).get("text") or ""))
        said = max(int(review.get("tier") or 0), int(current.get("tier") or 0))
        for i in named:
            if not isinstance(i, str):
                continue
            if goal not in out.setdefault(i, []):
                out[i].append(goal)
            out.tier[i] = max(out.tier.get(i, 0), said)
    return out


def _served_tier(ids: Iterable[str], served: Served) -> int:
    return max((served.tier.get(i, 0) for i in ids), default=0)


def _goals_of(ids: Iterable[str], served: Mapping[str, list[tuple[str, str]]]) -> tuple[tuple[str, str], ...]:
    found: dict[tuple[str, str], None] = {}
    for i in ids:
        found.update(dict.fromkeys(served.get(i, [])))
    return tuple(found)


def _transcript(
    lb: Logbook, line: Line, days: day_start.DayStart, served: Served, words: bool = True
) -> Session:
    payload = line.get("payload") or {}
    found = payload.get("extra")
    extra: Mapping[str, Any] = found if isinstance(found, Mapping) else {}
    agent = machine.agent_of(payload)
    listed = payload.get("participants")
    parts: list[Any] = listed if isinstance(listed, list) else []
    turns = (turns_of(lb, line) or []) if words else []
    mine = machine.human_turns(turns, parts)
    machines = machine.labels(parts)
    theirs = [
        t for t in turns if t.speaker is not None and " ".join(t.speaker.split()).casefold() in machines
    ]
    title = payload.get("title") if isinstance(payload.get("title"), str) else None
    first = _first_line(mine)
    source = str(line.get("source") or "")
    end = line.get("end")
    own = payload.get("summary")  # RFC 0004: the provider's own summary, when it made one
    return Session(
        str(line["id"]),
        (str(line["id"]),),
        days.day_of(str(line["at"])),
        str(line["at"]),
        end if isinstance(end, str) else None,
        source,
        _agent_name(agent, source),
        title,
        _summary(own, title, first),
        tuple(t.text for t in mine),
        tuple(t.text for t in theirs),
        _words(extra.get("words")),
        extra.get("tool_calls") if isinstance(extra.get("tool_calls"), int) else None,
        _goals_of([str(line["id"])], served),
        max(int(line.get("tier") or 0), _served_tier([str(line["id"])], served)),
    )


def _summary(own: object, title: str | None, first: str | None) -> str | None:
    """The provider's own summary, else the source's title when it is not the owner's first line."""
    if isinstance(own, str) and own.strip():
        return own.strip()
    if not title:
        return None
    cut = title.rstrip("…").rstrip()  # an adapter cuts a long first line and marks it so
    if first is not None and (title == first or (title.endswith("…") and first.startswith(cut))):
        return None  # the owner's own first line, not a summary
    return title


def _first_line(turns: Sequence[Turn]) -> str | None:
    """The first line of the owner's first turn, as an adapter takes it for a title when the source
    has none (`claude_code.first_words`, before it is cut)."""
    for t in turns:
        if t.text.strip():
            return t.text.strip().splitlines()[0].strip()
    return None


def _conversations(messages: Sequence[Line], days: day_start.DayStart) -> list[list[Line]]:
    """The messages with an agent, by the agent's ref and the local day, each in the order written."""
    groups: dict[tuple[str, str], list[Line]] = {}
    for line in sorted(messages, key=lambda m: (str(m["at"]), int(m["seq"]))):
        agent = machine.agent_of(line.get("payload") or {}) or {}
        ref = agent.get("ref")
        chat = (line.get("payload") or {}).get("chat")
        named = agent.get("name") or (chat.get("id") if isinstance(chat, Mapping) else None)
        key = repr(sorted(ref.items())) if isinstance(ref, Mapping) else repr((named, line.get("source")))
        groups.setdefault((key, days.day_of(str(line["at"]))), []).append(line)
    return list(groups.values())


def _telegram(group: Sequence[Line], days: day_start.DayStart, served: Served) -> Session:
    first = group[0]
    agent = machine.agent_of(first.get("payload") or {})
    source = str(first.get("source") or "")
    owner: list[str] = []
    theirs: list[str] = []
    for line in group:
        payload = line.get("payload") or {}
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        if machine.is_machine(payload):
            theirs.append(text)
        elif payload.get("from_me") is True and not _forwarded(payload):
            owner.append(text)  # a forward is someone else's words, never the owner's
    ids = tuple(str(line["id"]) for line in group)
    return Session(
        ids[0],
        ids,
        days.day_of(str(first["at"])),
        str(first["at"]),
        str(group[-1]["at"]) if len(group) > 1 else None,
        source,
        _agent_name(agent, source),
        None,
        None,
        tuple(owner),
        tuple(theirs),
        {"owner": sum(len(t.split()) for t in owner), "machine": sum(len(t.split()) for t in theirs)},
        None,
        _goals_of(ids, served),
        max([*(int(line.get("tier") or 0) for line in group), _served_tier(ids, served)]),
    )


def _forwarded(payload: Mapping[str, Any]) -> bool:
    extra = payload.get("extra")
    return isinstance(extra, Mapping) and bool(extra.get("forwarded"))


def _agent_name(agent: Mapping[str, Any] | None, source: str) -> str:
    if agent is not None:
        for key in ("name", "username"):
            if isinstance(agent.get(key), str) and agent[key].strip():
                return str(agent[key]).strip()
    return SOURCES.get(source, source or "an agent")


def _words(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    return {k: int(v) for k, v in value.items() if k in ("owner", "machine") and isinstance(v, int)}


# -- the page ----------------------------------------------------------------------------------------------


def session_path(line: str, day: str) -> str:
    """The Agents page of `day`, at the session whose line is `line` (or one of its messages)."""
    return f"/agents?day={day}#{anchor(line)}"


def anchor(line: str) -> str:
    return "s-" + "".join(c for c in line if c.isalnum() or c == "-")


def page_agents(site: Site, page: str = "1", day: str | None = None) -> str:
    """`/agents`: the sessions by day, the latest first, `PAGE_DAYS` days a page, or one `day`."""
    if not page.isdigit() or int(page) < 1:
        raise ValueError(f"page must be a number from 1, not {page!r}")
    if day is not None:
        day = parse_day(day).isoformat()
    n = int(page)

    def chosen(days: list[str]) -> list[str]:
        return [d for d in days if d == day] if day is not None else days[(n - 1) * PAGE_DAYS : n * PAGE_DAYS]

    lines = site.shared(("agents",), lambda: standing(site.lb, site.tiers))
    shelf = read(site.lb, site.tiers, chosen, lines)  # the turns of the days shown, and no others
    every = shelf.days()
    wanted = set(chosen([d for d, _s in every]))
    shown = [(d, s) for d, s in every if d in wanted]
    count = sum(len(s) for _d, s in shown)
    parts = [f"<h1>Agents {site.tier_small(_plural(len(shelf.sessions), 'session'), shelf.tier)}</h1>\n"]
    if not shelf.sessions:
        if site.tiers is not None:
            gate = ", ".join(str(t) for t in sorted({int(t) for t in site.tiers})) or "none"
            parts.append(
                f'<p class="mute">No session this page reads: it reads tier {escape(gate)} only, and a'
                " session is at its lines' tier (a session or a bot chat is tier 2 unless imported at"
                " another).</p>\n"
            )
        else:
            parts.append(
                "<p>No sessions with an agent yet. Add yours with <code>logbook add claude-sessions"
                " ~/.claude/projects</code>, <code>logbook add claude-export</code> (the Claude apps'"
                " export) or <code>logbook add telegram-export</code> (your bot chats).</p>\n"
            )
        return site.document("agents", "".join(parts), style=SHELF_STYLE)
    parts.append(
        '<p class="mute">Your sessions with your own agents, by day. Your words are yours; the agent\'s are'
        " machine text, shown apart. A session served a goal only where a review of the goal says so.</p>\n"
    )
    if day is not None:
        parts.append(f'<p class="mute">{escape(day)}{DOT}{_plural(count, "session")}</p>\n')
        if not shown:
            parts.append('<p class="mute">none this day</p>\n')
    elif not shown:
        parts.append(f'<p class="mute">no sessions on page {n}: {site.link("the latest", "/agents")}</p>\n')
    for d, sessions in shown:
        count_of = _plural(len(sessions), "session")
        parts.append(f"<h2>{site.link(escape(d), f'/day/{d}')} <small>{count_of}</small></h2>\n")
        parts.append('<ol class="shelf">\n')
        parts.extend(_session_html(site, s) for s in sessions)
        parts.append("</ol>\n")
    if day is None:
        pager = []
        if n > 1:
            pager.append(site.link("← later", f"/agents?page={n - 1}"))
        if n * PAGE_DAYS < len(every):
            pager.append(site.link("earlier →", f"/agents?page={n + 1}"))
        if pager:
            parts.append(f'<p class="pager">{"".join(pager)}</p>\n')
    else:
        parts.append(f"<p>{site.link('Agents', '/agents')}</p>\n")
    return site.document("agents", "".join(parts), style=SHELF_STYLE)


def _session_html(site: Site, s: Session) -> str:
    source = SOURCES.get(s.source, s.source)
    head = [f'<span class="badge">{escape(source)}</span>', f"<b>{escape(s.title or s.agent)}</b>"]
    if s.title and s.agent != source:
        head.append(f'<span class="mute">with {escape(s.agent)}</span>')
    out = [f'<li id="{anchor(s.line)}" title="line {escape(s.line)}"><p class="head">{" ".join(head)}</p>\n']
    # a Telegram day's other messages: a review may name any of them, and its link lands here
    out.extend(f'<span id="{anchor(i)}"></span>' for i in s.lines[1:])
    out.append(f'<p class="facts">{escape(DOT.join(_length(s)))}</p>\n')
    if s.served:
        links = ", ".join(site.link(escape(text), f"/goals/{goal}") for goal, text in s.served)
        out.append(f'<p class="facts">served {links}, as your review says</p>\n')
    if s.summary:
        out.append(
            f'<p class="summary"><span class="mute">the agent\'s summary:</span> {escape(s.summary)}</p>\n'
        )
    out.append(_said(s.owner, "your words", "said"))
    out.append(_said(s.machine, "the agent's words, machine text", "said machine", folded=True))
    out.append("</li>\n")
    return "".join(out)


def _length(s: Session) -> list[str]:
    facts = []
    if s.minutes is not None:
        facts.append(f"{s.minutes:,} min")
    if len(s.lines) > 1:
        facts.append(_plural(len(s.lines), "message"))
    facts.append(f"{_plural(len(s.owner), 'turn')} of yours, {len(s.machine):,} of the agent's")
    if s.words:
        facts.append(f"{s.words.get('owner', 0):,} words yours, {s.words.get('machine', 0):,} the agent's")
    if s.tool_calls:
        facts.append(_plural(s.tool_calls, "tool call"))
    facts.append(f"tier {s.tier}")
    return facts


def _said(texts: Sequence[str], label: str, cls: str, folded: bool = False) -> str:
    """Turns as quotes: the first `SHOWN` (each cut at `CHARS`, whole in its own fold) and the rest
    folded whole, or all of them folded whole."""
    if not texts:
        return ""
    whole = [f'<blockquote class="{cls}">{escape(t.strip())}</blockquote>\n' for t in texts]
    if folded:
        return f"<details><summary>{escape(label)}{DOT}{len(texts):,}</summary>\n{''.join(whole)}</details>\n"
    out = f'<p class="facts">{escape(label)}</p>\n' + "".join(_shown(t, cls) for t in texts[:SHOWN])
    if whole[SHOWN:]:
        rest = "".join(whole[SHOWN:])
        out += f"<details><summary>and {len(whole) - SHOWN:,} more</summary>\n{rest}</details>\n"
    return out


def _shown(text: str, cls: str) -> str:
    """A turn on the page: whole when short, else cut with the whole of it in a fold."""
    text = text.strip()
    if len(text) <= CHARS:
        return f'<blockquote class="{cls}">{escape(text)}</blockquote>\n'
    cut = text[: CHARS - 1].rstrip() + "…"
    return (
        f'<blockquote class="{cls}">{escape(cut)}\n<details><summary>the whole turn</summary>'
        f"{escape(text)}</details></blockquote>\n"
    )


def _plural(n: int, noun: str) -> str:
    return f"{n:,} {noun if n == 1 else noun + 's'}"
