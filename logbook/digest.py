"""The digest: one short text per day — `logbook digest [YYYY-MM-DD] [--json | --markdown]`.

The Day (`day.read`) is the whole day read back; the digest is what the owner reads of it in the
evening, in at most `LIMIT` lines, never a list of everything. In order:

1. The day's shape in three lines: **where** (the stays of the timeline in order, a run aboard an
   asset as `aboard <asset>`, and where the night after was spent, home or away or in transit);
   **with** (the people the Day confirms present, never a proposed face or an all-day attendee;
   how many are only proposed); **attached** (how many of each kind attached across the day's rows,
   `day.counts`, and how many lines fell inside no row).
2. The flights of the day, from the Day's `flights` (the `flight/v1` lines standing), the first
   `FLIGHTS_SHOWN` and `+N more`.
3. The open promises due within `DUE_DAYS` of the day, from the promises reader (`promises.extract`,
   its proposals never asserted): the sentence, who said it, the due day and the phrase it came
   from, the first `PROMISES_SHOWN` and `+N more`. A promises reader that judges its proposals
   puts the ids it holds to be promises on its report as `judged`; when the attribute is there,
   only those count (`due_promises`).
4. The usual sources with no line on the day, by the `sources --gaps` rule (`gaps.report` with
   `expect`, the day as `since`): a source is usual when it has a line on `days.USUAL_SHARE` of the
   logged days of the `USUAL_DAYS` ending on the day (`days.usual_sources`), and it is missing when
   the report counts the day among its missing days or holds no line of it at all. One line.
5. Tomorrow's timed calendar entries, from the `event/v1` lines standing on the next local day
   (retracted lines out, the sources folded as the Day folds them, `events.fold`; an all-day entry
   is not timed), with the attendees the record names: the first `TOMORROW_SHOWN` and `+N more`.
6. One closing question the owner can answer in a word, from the record's own bank
   (`logbook/questions.py`, RFC 0027): `policy/questions.json` lists the questions, each with the
   day's facts it asks on (`when`: travelled, aboard, night away, a reunion, no photos, long sleep,
   ...) and a weight; the digest reads the day's facts from the parts it already has (`questions.facts`),
   draws one of the questions whose conditions hold by weight (`questions.pick`), never the same id
   two days running, and remembers what it asked in `state/questions.json`. The first run writes the
   default bank — the nudges this module used to choose in code, as questions — and nothing
   overwrites an edit. The day closes itself (ADR 0005): the question is the one
   nudge, and the digest never sends it — delivery is a later decision.

Everything here is composed from the readers; nothing is derived anew, nothing is written to the
record (the question bank's default and the state of what was asked are files beside it, never
lines; a reader's settings file is never written) and nothing leaves the machine. The text and the
Markdown are the same lines; `fit` holds them to `LIMIT` whatever the day, cutting from the middle
and never the question. ADR 0013: derived is disposable."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from . import day as day_reader
from . import days, events, gaps, promises, questions
from . import flights as flight_lines
from .chain import Line
from .export import parse_day
from .flights import Airports
from .store import Logbook, retractions

LIMIT = 25  # lines, the hard limit of the text and the Markdown
DUE_DAYS = 7  # an open promise due within this many days of the day is in
USUAL_DAYS = 14  # the window ending on the day whose logged days decide which sources are usual
FLIGHTS_SHOWN = 3
PROMISES_SHOWN = 3
TOMORROW_SHOWN = 3
WHERE_SHOWN = 6  # stays named on the where line before `…`
QUOTE_CHARS = 72  # a promise's sentence, in the text and the question
LABEL = 10
ARROW = day_reader.ARROW
EN_DASH = day_reader.EN_DASH
DOT = day_reader.DOT
ELLIPSIS = "…"
QUOTES = ("“", "”")


# -- the reading --------------------------------------------------------------------------------------------


def read(lb: Logbook, day: str, airports: Airports | None = None) -> dict[str, Any]:
    """The digest of `day` as one JSON-ready object. `ValueError` for a day that is not one or has
    not come (after today in the record's zone); `stays.SettingsError` when the record's settings,
    places or assets file is not what it should be. Nothing is written."""
    d = parse_day(day)
    tz = ZoneInfo(str(lb.meta["timezone"]))
    today = gaps.now().astimezone(tz).date()
    if d > today:
        raise ValueError(f"{day} is after today ({today.isoformat()}); a digest closes a day that has come")
    data = day_reader.read(lb, day, airports)
    tomorrow = (d + timedelta(days=1)).isoformat()
    report = promises.extract(lb)
    due = due_promises(report, day)
    missing, usual = _gaps(lb, d)
    entries = _tomorrow(lb, tomorrow, tz)
    shape = _shape(data)
    out = {
        "day": day,
        "weekday": data["weekday"],
        "tz": data["tz"],
        "shape": shape,
        "flights": data["flights"],
        "promises": {
            "within_days": DUE_DAYS,
            "judged": getattr(report, "judged", None) is not None,
            "open": [p.to_json() for p in due],
        },
        "gaps": {"usual": usual, "missing": missing},
        "tomorrow": {"day": tomorrow, "entries": entries},
        "unplaced": data["unplaced"],
        "sources": [s["source"] for s in data["sources"]],
        "question": questions.pick(lb.root, _facts(lb, data, shape, due, missing, entries, day), day),
    }
    out["lines"] = len(list(rows(out)))
    return out


def _shape(data: Mapping[str, Any]) -> dict[str, Any]:
    """The three lines' facts: the stays in order (consecutive repeats folded), the night after,
    the people confirmed and the people only proposed, the attachment counts, the unplaced count."""
    where: list[str] = []
    confirmed: dict[str, str] = {}
    proposed: dict[str, str] = {}
    counts: dict[str, int] = {}
    for e in data["timeline"]:
        if e["kind"] in days.STAYS:
            name = str(e["where"] or f"{e['lat']},{e['lon']}")
            if not where or where[-1] != name:
                where.append(name)
        for c in (e.get("with") or {}).get("confirmed", []):
            confirmed.setdefault(str(c["person"] or c["name"]), str(c["name"]))
        for c in (e.get("with") or {}).get("proposed", []):
            proposed.setdefault(str(c["person"] or c["name"]), str(c["name"]))
        for n, noun in day_reader.counts(e.get("attached")):
            counts[noun] = counts.get(noun, 0) + n
    for key in confirmed:
        proposed.pop(key, None)  # proposed at one stay, confirmed at another: confirmed
    night = data["nights"]["after"]
    return {
        "where": where,
        "night": {k: night[k] for k in ("where", "home", "aboard", "in_transit")},
        "with": {"confirmed": list(confirmed.values()), "proposed": list(proposed.values())},
        "attached": [{"count": n, "noun": noun} for noun, n in counts.items()],
        "unplaced": len(data["unplaced"]),
    }


def due_promises(report: promises.Report, day: str, within: int = DUE_DAYS) -> list[promises.Proposal]:
    """The report's open proposals due on `day` or within `within` days after it, in the report's
    order. A report that carries a `judged` set (the ids its reader holds to be promises) narrows
    them to those; a report without the attribute counts every open proposal."""
    first = parse_day(day)
    last = first + timedelta(days=within)
    judged = getattr(report, "judged", None)
    held: set[str] | None = None if judged is None else {str(i) for i in judged}
    out = []
    for p in report.proposals:
        if p.status != "open" or p.due is None or (held is not None and p.id not in held):
            continue
        try:
            due = date.fromisoformat(p.due)
        except ValueError:
            continue
        if first <= due <= last:
            out.append(p)
    return out


def _gaps(lb: Logbook, d: date) -> tuple[list[str], list[str]]:
    """(the usual sources with no line on the day, the usual sources), by `gaps.report`."""
    first = (d - timedelta(days=USUAL_DAYS - 1)).isoformat()
    usual = days.usual_sources(lb, first, d.isoformat())
    if not usual:
        return [], []
    report = gaps.report(lb, since=d.isoformat(), expect=usual)
    missing = [
        s["source"] for s in report["sources"] if s["lines"] == 0 or d.isoformat() in s["missing_days"]
    ]
    return missing, usual


def _tomorrow(lb: Logbook, day: str, tz: ZoneInfo) -> list[dict[str, Any]]:
    """The timed calendar entries of `day`, standing and folded, in time order: title, start and
    end, the attendees the record names (never a bare address), the sources and the lines."""
    with lb.index() as idx:
        retracted = retractions(idx.retractions())
        found = [line for line in idx.by_kind("event", day, day) if str(line["id"]) not in retracted]
        names = _names(idx.resolutions())
    folded, stands_for = events.fold(found, flight_lines.Airlines.load())
    out = []
    for line in folded:
        payload = line.get("payload") or {}
        if payload.get("all_day") is True:
            continue
        kept = stands_for.get(str(line["id"]))
        out.append(
            {
                "title": str(payload.get("title") or "an event"),
                "start": line["at"],
                "end": line.get("end"),
                "start_local": _local(str(line["at"]), tz),
                "end_local": None if line.get("end") is None else _local(str(line["end"]), tz),
                "with": _attendees(payload, names),
                "sources": [str(line.get("source"))] if kept is None else list(kept.sources),
                "lines": [str(line["id"])] if kept is None else list(kept.lines),
            }
        )
    out.sort(key=lambda e: (str(e["start"]), e["title"]))
    return out


def _names(resolutions: Sequence[Line]) -> dict[tuple[str, str], str]:
    """(ref kind, ref value) → the label the record's resolution lines give it, the last one standing."""
    names: dict[tuple[str, str], str] = {}
    for line in resolutions:
        payload = line.get("payload") or {}
        ref, label = payload.get("ref"), payload.get("label")
        if not (
            isinstance(ref, dict) and isinstance(ref.get("kind"), str) and isinstance(ref.get("value"), str)
        ):
            continue
        if isinstance(label, str) and label:
            names[(ref["kind"], ref["value"])] = label
    return names


def _attendees(payload: Mapping[str, Any], names: Mapping[tuple[str, str], str]) -> list[str]:
    out: list[str] = []
    for a in payload.get("attendees") or []:
        if not isinstance(a, dict):
            continue
        ref = a.get("ref")
        name = None
        if isinstance(ref, dict) and isinstance(ref.get("kind"), str) and isinstance(ref.get("value"), str):
            name = names.get((ref["kind"], ref["value"]))
        name = name or (a.get("name") if isinstance(a.get("name"), str) else None)
        if name and name not in out:
            out.append(name)
    return out


def _local(stamp: str, tz: ZoneInfo) -> str:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(tz).isoformat(timespec="seconds")


# -- the question -------------------------------------------------------------------------------------------


def _facts(
    lb: Logbook,
    data: Mapping[str, Any],
    shape: Mapping[str, Any],
    due: Sequence[promises.Proposal],
    missing: Sequence[str],
    entries: Sequence[Mapping[str, Any]],
    day: str,
) -> questions.Facts:
    """The day's facts for the question bank, from the parts read above; a promise due on the day
    or before is passed quoted, as the text prints it."""
    today = [_quote(p.match.quote) for p in due if p.due is not None and p.due <= day]
    return questions.facts(lb, data, shape, today, missing, len(entries), day)


# -- text ----------------------------------------------------------------------------------------------------


def rows(data: Mapping[str, Any]) -> Iterator[str]:
    """The digest as text, `LIMIT` lines at most: the header, the three lines of the shape, the
    flights, the promises due, the gaps, tomorrow, a blank line and the question."""
    yield from fit(list(_rows(data)))


def markdown(data: Mapping[str, Any]) -> Iterator[str]:
    """The same lines as Markdown: a heading, a bulleted list with the labels in bold, the question
    in bold on its own."""
    lines = fit(list(_rows(data)))
    d = date.fromisoformat(str(data["day"]))
    yield f"## {data['weekday']} {d.day} {d.strftime('%B %Y')}"
    for text in lines[1:-2]:
        if text == ELLIPSIS:
            yield f"- {ELLIPSIS}"
            continue
        label, _, rest = text.strip().partition("  ")
        yield f"- **{label}** {rest.strip()}"
    yield ""
    yield f"**{lines[-1]}**"


def fit(lines: list[str], limit: int = LIMIT) -> list[str]:
    """`lines` held to `limit`: when over, the lines after the header are cut to make room for one
    `…` row, the blank line and the question kept last."""
    if len(lines) <= limit:
        return lines
    head, body, tail = lines[:1], lines[1:-2], lines[-2:]
    room = limit - len(head) - len(tail) - 1
    return [*head, *body[:room], ELLIPSIS, *tail]


def _rows(data: Mapping[str, Any]) -> Iterator[str]:
    tz = ZoneInfo(str(data["tz"]))
    shape = data["shape"]
    yield f"{data['day']}  {data['weekday']}"
    yield _row("where", _where_text(shape, bool(data["sources"])))
    yield _row("with", _with_text(shape["with"]))
    yield _row("attached", _attached_text(shape))
    flights = data["flights"]
    for f in flights[:FLIGHTS_SHOWN]:
        yield _row("flight", _flight_text(f, tz))
    if len(flights) > FLIGHTS_SHOWN:
        yield _row("flight", f"+{len(flights) - FLIGHTS_SHOWN} more flights")
    due = data["promises"]["open"]
    for p in due[:PROMISES_SHOWN]:
        yield _row("due", _due_text(p))
    if len(due) > PROMISES_SHOWN:
        yield _row("due", f"+{len(due) - PROMISES_SHOWN} more due this week")
    if data["gaps"]["missing"]:
        yield _row("gaps", ", ".join(data["gaps"]["missing"]) + ": usual, no line")
    entries = data["tomorrow"]["entries"]
    for e in entries[:TOMORROW_SHOWN]:
        yield _row("tomorrow", _entry_text(e, tz))
    if len(entries) > TOMORROW_SHOWN:
        yield _row("tomorrow", f"+{len(entries) - TOMORROW_SHOWN} more entries")
    yield ""
    yield str(data["question"]["text"])


def _row(label: str, text: str) -> str:
    return f"  {label:<{LABEL}} {text}"


def _where_text(shape: Mapping[str, Any], logged: bool) -> str:
    where = list(shape["where"])
    if not where and not logged:
        return "nothing logged"
    shown = where[:WHERE_SHOWN] + ([ELLIPSIS] if len(where) > WHERE_SHOWN else [])
    route = f" {ARROW} ".join(shown) if shown else "no stay"
    night = shape["night"]
    if night["in_transit"]:
        return f"{route}{DOT}night in transit"
    return f"{route}{DOT}night {'at' if night['home'] else 'away,'} {night['where']}"


def _with_text(with_: Mapping[str, Any]) -> str:
    confirmed, proposed = with_["confirmed"], with_["proposed"]
    text = ", ".join(confirmed) if confirmed else "nobody confirmed"
    if proposed:
        text += f" ({len(proposed)} proposed)"
    return text


def _attached_text(shape: Mapping[str, Any]) -> str:
    parts = [_plural(a["count"], a["noun"]) for a in shape["attached"]]
    if shape["unplaced"]:
        parts.append(f"{shape['unplaced']} unplaced")
    return ", ".join(parts) if parts else "nothing"


def _flight_text(f: Mapping[str, Any], tz: ZoneInfo) -> str:
    name = " ".join(str(part) for part in (f.get("carrier"), f.get("number")) if part) or "a flight"
    route = f"{f.get('from') or '?'}{ARROW}{f.get('to') or '?'}"
    span = _clock(str(f["start"]), tz)
    if f.get("end"):
        span += f"{EN_DASH}{_clock(str(f['end']), tz)}"
    text = f"{name} {route}  {span}"
    if f.get("evidence") and f["evidence"] != "tracked":
        text += f" ({f['evidence']})"
    return text


def _due_text(p: Mapping[str, Any]) -> str:
    speaker = p.get("speaker") or {}
    who = "you" if speaker.get("owner") else (speaker.get("label") or speaker.get("spoken") or "?")
    due = p.get("due") or {}
    tail = f"{who}, {due.get('date')}"
    if due.get("phrase"):
        tail += f" ({due['phrase']})"
    return f"{_quote(str(p['quote']))}  {tail}"


def _entry_text(e: Mapping[str, Any], tz: ZoneInfo) -> str:
    span = _clock(str(e["start"]), tz)
    if e.get("end"):
        span += f"{EN_DASH}{_clock(str(e['end']), tz)}"
    text = f"{span}  {e['title']}"
    if len(e["sources"]) > 1:
        text += f"{DOT}×{len(e['sources'])} sources"
    if e["with"]:
        text += f"{DOT}with {', '.join(e['with'])}"
    return text


def _quote(sentence: str) -> str:
    text = " ".join(sentence.split())
    if len(text) > QUOTE_CHARS:
        text = text[: QUOTE_CHARS - 1].rstrip() + ELLIPSIS
    return f"{QUOTES[0]}{text}{QUOTES[1]}"


def _clock(stamp: str, tz: ZoneInfo) -> str:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(tz).strftime("%H:%M")


def _plural(n: int, noun: str) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {noun}s"
