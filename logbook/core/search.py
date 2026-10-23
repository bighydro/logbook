"""`logbook search TEXT`: full-text search over the record, through the index.

The words of every line that carries any — a note, a message, a mail, a calendar entry, a
transcript (its text read from the attachment store), a task, a highlight, a voice memo, a page
browsed, something watched or listened to, a trip — sit in one FTS5 table of `index.sqlite`
(`index.SEARCH`), written beside the line's row when the line is appended and rebuilt with it by
`logbook index`; a location point, a photo, a health sample or a call has no words and no row. The
table is a cache like the rest of the index (ADR 0007): the files are the record, and deleting it
loses nothing.

A query is words and phrases. A bare word matches the word itself, case and accents aside
(`zurich` finds `Zürich`), and never a stem of it: `run` does not find `running`, in English or in
German. A run in double quotes is a phrase that must appear in that order. A word ending in `*`
matches by prefix. Every term must match; FTS5's own operators (`AND`, `OR`, `NOT`, `NEAR`, a
colon, a caret) are words here, never syntax (`expression`). The hits are ranked by FTS5's bm25,
and the `LIMIT` best are shown grouped by local day — the latest day first, the lines of a day in
time order — each with the row `show` prints and a snippet of the matching words, `[marked]`.

Tier-aware: tiers 1 and 2 by default; tier 3 (money, health, the transcripts the reference
adapters write at 3) only with `--tier 3`, as `export crossing` and `mcp` have it. A retracted line
is never a hit. A hit a later line of its own kind supersedes (SPEC §3: not standing) is still a hit,
marked with the line that superseded it, in the words `show` marks one with; `--standing` keeps
standing hits only. The mark is asked of the index's `lines_kind_supersedes` index for the hits'
ids, never of the search table. Nothing is written to the record."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from .chain import Line

if TYPE_CHECKING:
    from pathlib import Path

    from .index import Index

LIMIT = 50  # hits shown without --limit
STANDING_MARGIN = 4  # --standing first asks limit + limit // 4 + 1: room for the superseded hits it drops
MAX_TIER = 2  # searched without --tier
SNIPPET_TOKENS = 16  # the words a snippet shows around the match
MARK = ("[", "]")  # around each matching word in a snippet
ELLIPSIS = "…"  # where a snippet cuts the body
FIELD_BREAK = " · "  # between two fields of the body in a snippet (a title and a text)

# The kinds whose lines carry words worth searching: the profile's text fields, as `body_of`
# gathers them. Every other kind (location, photo, health-sample, call, flight, crossing …) is
# numbers, refs and ids and has no row.
KINDS = (
    "note",
    "transcript",
    "message",
    "mail",
    "event",
    "task",
    "highlight",
    "voice-memo",
    "browse",
    "watch",
    "listen",
    "trip",
    "journey",  # RFC 0031: `trip/v1` renamed for new lines; either kind asked for searches both
    "story",
)
# One profile under two kinds (RFC 0031): asking for either searches both.
ALIASES = {"trip": ("trip", "journey"), "journey": ("trip", "journey")}
# Payload keys whose string is an id, a digest, a stamp, a type or a path, never words a person
# searches for: left out of the body so a snippet never shows one and a digest never matches.
SKIP_KEYS = frozenset(
    {
        "schema",
        "raw_id",
        "supersedes",
        "sha256",
        "path",
        "media_type",
        "message_id",
        "thread",
        "reply_to",
        "recurrence",
        "recurrence_of",
        "provider_id",
        "asset_id",
        "modified_at",
        "date",
        "id",
        "kind",
        "type",
        "response",
        "status",
        "direction",
        "language",
        "media_kind",
        "account",
        "source_uri",
    }
)
TERM = re.compile(r'"([^"]*)"?|(\S+)')  # a quoted phrase (the closing quote optional), or a word
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class QueryError(ValueError):
    """A query the command refuses; the message says why."""


@dataclass(frozen=True)
class Query:
    text: str
    expression: str
    since: str | None  # local days, inclusive
    until: str | None
    kinds: tuple[str, ...] | None
    max_tier: int
    limit: int
    standing: bool = False  # standing hits only (`--standing`)

    def to_json(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "expression": self.expression,
            "since": self.since,
            "until": self.until,
            "kinds": None if self.kinds is None else list(self.kinds),
            "max_tier": self.max_tier,
            "limit": self.limit,
            "standing": self.standing,
        }


@dataclass(frozen=True)
class Hit:
    line: Line
    day: str  # the local day
    rank: float  # FTS5's bm25; lower is better
    snippet: str
    superseded_by: tuple[int, str] | None = None  # the (seq, id) of the line of its kind that supersedes it

    @property
    def standing(self) -> bool:
        """Not superseded (a retracted line is never a hit)."""
        return self.superseded_by is None

    def to_json(self, summary: Callable[[Line], str]) -> dict[str, Any]:
        line = self.line
        return {
            "seq": int(line["seq"]),
            "id": str(line["id"]),
            "at": str(line["at"]),
            "kind": str(line["kind"]),
            "source": str(line["source"]),
            "tier": int(line["tier"]),
            "rank": self.rank,
            "snippet": self.snippet,
            "summary": summary(line),
            "standing": self.standing,
            "superseded_by": None if self.superseded_by is None else self.superseded_by[1],
        }


@dataclass(frozen=True)
class Result:
    query: Query
    hits: list[Hit]  # the best first

    def days(self) -> list[tuple[str, list[Hit]]]:
        """The hits grouped by local day, the latest day first, the lines of a day in time order,
        then chain order: the rank decides which hits are kept within the limit, the day where
        they are read."""
        grouped: dict[str, list[Hit]] = {}
        for hit in self.hits:
            grouped.setdefault(hit.day, []).append(hit)
        return [
            (day, sorted(grouped[day], key=lambda h: (str(h.line["at"]), int(h.line["seq"]))))
            for day in sorted(grouped, reverse=True)
        ]

    @property
    def full(self) -> bool:
        """The limit was reached: there may be more."""
        return len(self.hits) >= self.query.limit

    def to_json(self, summary: Callable[[Line], str]) -> dict[str, Any]:
        return {
            "query": self.query.to_json(),
            "hits": len(self.hits),
            "more": self.full,
            "days": [
                {"day": day, "lines": [hit.to_json(summary) for hit in hits]} for day, hits in self.days()
            ],
        }


# -- the query --------------------------------------------------------------------------------------------


def expression(text: str) -> str | None:
    """The FTS5 MATCH expression for a query as a person types it, or None when it holds no word.
    Each bare word becomes one quoted token, so nothing in it is syntax to FTS5; a run in double
    quotes (the closing quote may be missing) becomes a phrase; a term ending in `*` matches by
    prefix (a phrase: its last word). Terms are joined by FTS5's implicit AND. A term with no
    letter or digit in it (`-`, `*`, an em dash) is dropped: the tokenizer would find nothing in
    it."""
    terms = []
    for phrase, word in TERM.findall(text):
        term = phrase if phrase else word
        prefix = term.endswith("*")
        term = term.rstrip("*").replace('"', " ").strip()
        if not any(ch.isalnum() for ch in term):
            continue
        terms.append(f'"{term}" *' if prefix else f'"{term}"')
    return " ".join(terms) if terms else None


def query(
    text: str,
    since: str | None = None,
    until: str | None = None,
    kinds: Sequence[str] | None = None,
    max_tier: int = MAX_TIER,
    limit: int = LIMIT,
    standing: bool = False,
) -> Query:
    """A checked query: the text holds a word, every kind is one the table holds, the window does
    not run backwards, the tier is 1 to 3 and the limit positive; else `QueryError`."""
    built = expression(text)
    if built is None:
        raise QueryError("say a word to search for")
    if kinds is not None:
        unknown = [kind for kind in kinds if kind not in KINDS]
        if unknown:
            raise QueryError(
                f"{', '.join(unknown)}: not a kind with words; the kinds searched are {', '.join(KINDS)}"
            )
    if since is not None and until is not None and until < since:
        raise QueryError(f"the window runs backwards: {since} > {until}")
    if max_tier not in (1, 2, 3):
        raise QueryError("--tier is 1, 2 or 3")
    if limit < 1:
        raise QueryError("--limit is at least 1")
    if kinds is not None:
        kinds = tuple(dict.fromkeys(k for kind in kinds for k in ALIASES.get(kind, (kind,))))
    return Query(
        text, built, since, until, None if kinds is None else tuple(kinds), max_tier, limit, standing
    )


def search(idx: Index, q: Query) -> Result:
    """The hits of `q` through the index's search table: ranked by bm25, the window, the kinds
    and the tier cut in the query, a retracted line left out, each hit's line read from the files
    (`Index.search`), and each marked with the line of its own kind that supersedes it
    (`superseded_by`). With `q.standing` a superseded hit is left out and the next by rank takes
    its place: the query asks for a margin over the limit (`STANDING_MARGIN`), the lines are read
    a limit at a time until the limit stands, and only when the answer runs out first is the query
    asked again for twice as many, the hits already read skipped (the order is total, bm25 then
    the later line first, so a longer answer begins with the shorter one). Each ask ranks every
    match of the words again, so the margin spares the second ask whenever few hits are superseded."""
    hits: list[Hit] = []
    ask = q.limit + q.limit // STANDING_MARGIN + 1 if q.standing else q.limit
    read = 0
    while True:
        found = idx.search(q.expression, q.max_tier, q.since or "", q.until or "9999-12-31", q.kinds, ask)
        while read < len(found) and len(hits) < q.limit:
            batch = found[read : read + q.limit]
            lines = idx.read((file, offset) for _seq, _day, _rank, _snippet, file, offset in batch)
            by = superseded_by(idx, lines)
            for (seq, day, rank, snippet, _file, _offset), line in zip(batch, lines, strict=True):
                hit = Hit(line, day, rank, snippet.replace("\n", FIELD_BREAK), by.get(seq))  # one row
                if hit.standing or not q.standing:
                    hits.append(hit)
            read += len(batch)
        if len(hits) >= q.limit or len(found) < ask:
            return Result(q, hits[: q.limit])
        ask *= 2


def superseded_by(idx: Index, lines: Sequence[Line]) -> dict[int, tuple[int, str]]:
    """seq → the (seq, id) of the line that supersedes it, for those of `lines` one does: the rule
    `Index.superseded` reads by (a line of the same kind naming it in `supersedes`, the last in
    chain order when several do, a retracted one superseding nothing), asked of the
    `lines_kind_supersedes` index for these lines' ids alone, so the cost is the hits, never how
    many lines of their kind were ever corrected. Nothing is read from the files."""
    from .index import RETRACTED  # a function-level import: `index` imports this module

    wanted: dict[str, dict[str, list[int]]] = {}  # kind → id → the seqs of `lines` with it
    for line in lines:
        wanted.setdefault(str(line["kind"]), {}).setdefault(str(line["id"]), []).append(int(line["seq"]))
    found: dict[int, tuple[int, str]] = {}
    for kind, ids in wanted.items():
        named = list(ids)
        for n in range(0, len(named), 500):
            chunk = named[n : n + 500]
            for superseded, seq, line_id in idx.db.execute(
                f"SELECT supersedes, seq, id FROM lines WHERE kind = ? AND supersedes IN"
                f" ({', '.join('?' * len(chunk))}) AND id NOT IN ({RETRACTED}) ORDER BY seq",
                (kind, *chunk),
            ):
                for hit in ids[str(superseded)]:
                    found[hit] = (int(seq), str(line_id))  # in chain order: the last one stays
    return found


# -- the body: the words of one line ----------------------------------------------------------------------


def body_of(line: Mapping[str, Any], root: Path | None) -> str | None:
    """The words of one line, one field per row, or None when its kind carries none or the payload
    holds no string: every string in the payload, at any depth, except under `SKIP_KEYS` (ids,
    digests, stamps, types); for a transcript, then the text of its attachment read from the
    store under `root` as the promises reader reads it (`promises.turns_of`), `Speaker: text` per
    turn — None `root` reads no file. Never the line's own envelope."""
    if line.get("kind") not in KINDS:
        return None
    payload = line.get("payload")
    if not isinstance(payload, dict):
        return None
    parts: list[str] = []
    _gather(payload, parts)
    if line.get("kind") == "transcript" and root is not None:
        parts.extend(_transcript_text(line, root))
    body = "\n".join(part for part in parts if part)
    return body or None


def _gather(value: object, out: list[str]) -> None:
    if isinstance(value, str):
        if value.strip():
            out.append(" ".join(value.split()))
    elif isinstance(value, dict):
        for key, inner in value.items():
            if key not in SKIP_KEYS:
                _gather(inner, out)
    elif isinstance(value, list):
        for inner in value:
            _gather(inner, out)


def _transcript_text(line: Mapping[str, Any], root: Path) -> Iterable[str]:
    from .store import Logbook
    from .transcripts import turns_of  # a function-level import: `store` imports `index` imports here

    turns = turns_of(Logbook(root), dict(line))
    if not turns:
        return ()
    return (f"{turn.speaker}: {turn.text}" if turn.speaker else turn.text for turn in turns)


# -- the text ---------------------------------------------------------------------------------------------


def rows(result: Result, row: Callable[[Line], str]) -> Iterable[str]:
    """The result as `search` prints it: per day its date and weekday, then per hit the row `show`
    prints (`row`), marked when a line supersedes it (`mark`), and the snippet under it; last, the
    count, with a word when the limit was reached and when tier 3 was not searched."""
    q = result.query
    if not result.hits:
        yield f"nothing matches: {q.text}"
        if q.max_tier < 3:
            yield "tier 3 was not searched; --tier 3 includes it"
        return
    days = result.days()
    for day, hits in days:
        yield f"{day} {weekday(day)}"
        for hit in hits:
            yield row(hit.line) + mark(hit)
            yield f"         {hit.snippet}"
    footer = f"{_plural(len(result.hits), 'hit')} in {_plural(len(days), 'day')}"
    if result.full:
        footer += f"; the first {q.limit} by rank, --limit for more"
    yield footer


def mark(hit: Hit) -> str:
    """What follows a hit's row: nothing when it stands, else the line that superseded it, as `show`
    marks a superseded line whose words it keeps."""
    return "" if hit.superseded_by is None else f"{FIELD_BREAK}superseded by #{hit.superseded_by[0]}"


def weekday(day: str) -> str:
    try:
        return WEEKDAYS[date.fromisoformat(day).weekday()]
    except ValueError:
        return ""


def _plural(n: int, noun: str) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {noun}s"
