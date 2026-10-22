"""The week page of `logbook serve` (RFC 0043 §8, slice D, part 1): `/week/YYYY-Www`, the Sunday's week
draft (`dream week`, RFC 0036 unit `week`) grown into a page. Read-only: no form, no act, no script;
closing the week is part 2.

Each part is one fold with a summary line complete in its counts, every reader through the page's gate
(`tiers`), and a part with nothing in it is no heading: the empty ones share one muted row (`Nothing
from`, as on the Day):

1. **The seven days**: one ribbon a day (`day_rhythm.ribbon`, the planned beside the lived), Monday to
   Sunday, each headed by a link to its Day, read through the Day's own pool (`Site._day_reading`, the
   same key the Day reads it by, so a week read after its days reads nothing again). No now line: the
   week page is the week's, not the hour's.
2. **Where the week went**: the standing week draft's numbers (`extra.numbers`), which the code computed
   from the lines, never the model: the hours by place and the threads, each with the lines it rests on
   (`/line/ID`); sleep and training only on a page that reads tier 3 (a draft that read them is tier 3,
   so through a lower gate it is not read at all). The draft's contacts by person are not shown here:
   a person is never beside a number (VISION, *no metrics near people*), and a thread that is a chat or
   names a person is shown without its count.
3. **Goals**: each goal open on the Sunday or touched in the week (`shelf_goals.read`, as the Day reads
   it on the Sunday; `day_rhythm.touched` for each day), the days the week touched it, your latest
   verdict, the verdict the week's draft proposes (pencil), the five verdicts of `goal review` and the
   command that gives one (no form yet), and the two honest moves in words: change the days (the
   week's one proposal) or change the sentence (reword it, `goal add --supersedes`, or let it go).
4. **Next week**: the draft's one proposal (`next_week`), in pencil, headed with the model's name, with
   its lines.
5. **The question**: the draft's one stale question (`extra.question`, code's), asked once.
6. **People who moved**: the people whose contacts in this week's draft differ from the week before's
   draft (`numbers.people` of each, through the same gate), the largest change first, five at most;
   names only, never a count or a direction beside a name.
7. **The plan**: the sprint and the next trip (`plan.read`, the `sync notion` lines, tier 1) as the
   week's last day the clock has reached stood; titles and dates, each linked to its line, never to
   Notion: no URL but the server's own.
8. **Hold**: the senders and Drive censuses (`labs.hold.census_senders`, `census_drive`) as the record
   stands, through the gate: counts only, never a file's name or a sender. On the week page only.

The draft's parts (2, 4, 5, 6 and the proposed verdicts of 3) are behind `with_drafts`: a static site
built without its drafts (`export site`, #364) reads no draft and says so in one line. A model's
sentence, a thread's title or the question that would put a digit beside a person's name (`beside`) is
withheld, its row saying so and naming the line as written.

Left for later, and said on the page: time by project, the sprint's done, rolled and let go (slice C's
dispositions in the crossing), the pile untouched for 90 days, and closing the week (part 2)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, time, timedelta
from html import escape
from typing import TYPE_CHECKING, Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from ..core import day as day_reader
from ..core import day_start, drafts, goals, people
from ..core.export import day_range
from ..core.store import retractions
from . import day_rhythm, plan, shelf_goals, week_paper

if TYPE_CHECKING:  # the Site passes itself; serve imports this module, never the other way at import
    from .serve import Site

DOT = day_rhythm.DOT
DASH = day_rhythm.DASH
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")  # fmt: skip
ID_SHOWN = 4  # line ids a figure links; the rest are counted
MOVERS = 5  # the people who moved, at most
VERDICTS = tuple(d.replace(" ", "-") for d in goals.DISPOSITIONS)  # as `goal review` takes them
NO_DRAFT = "The week has no draft yet"
NO_DRAFTS = (
    "This site was built without its drafts: the week's numbers, its proposal, its question and the people"
    " who moved are in the week's draft, left out."
)
WITHHELD_BESIDE = "Withheld here: it sets a number beside a person's name."
LATER = (
    "Later: time by project, the sprint's done, rolled and let go, the pile untouched for 90 days, and"
    " closing the week."
)
BESIDE = "[\\s(:×x#·,]*"  # what may stand between a name and a number and still be beside it
WEEK_STYLE = """
ol.week{list-style:none;padding:0;margin:0}
ol.week>li{padding:4px 0;border-bottom:1px solid var(--line)}ol.week>li:last-child{border-bottom:0}
ol.week p.day{margin:0;font-size:13.5px}
p.line,li.line{overflow-wrap:anywhere}
code.cmd{font-family:var(--mono);font-size:12.5px;overflow-wrap:anywhere;white-space:normal}
ul.plain{list-style:none;padding:0;margin:0 0 6px}ul.plain>li{padding:2px 0;overflow-wrap:anywhere}
p.later{color:var(--mute);font-size:12.5px;margin:18px 0 6px}
"""  # what the week page adds to the Day's stylesheet; every rule keeps to the column


def week_path(week: str) -> str:
    return f"/week/{week}"


def _person_path(entity: str) -> str:
    return "/people/" + quote(entity, safe="")


def beside(text: str, names: Iterable[str]) -> bool:
    """Whether a digit stands beside one of `names` in `text` (the guard of `tests/test_day_rhythm.py`)."""
    for name in names:
        n = re.escape(name)
        if name and re.search(rf"(\d{BESIDE}{n})|({n}\??{BESIDE}\d)", text):
            return True
    return False


def span_text(monday: str, sunday: str) -> str:
    """`15-21 June 2026`, `29 June - 5 July 2026`, `28 December 2026 - 3 January 2027`, an en dash
    for each hyphen."""
    a, b = date.fromisoformat(monday), date.fromisoformat(sunday)
    if a.year != b.year:
        return f"{a.day} {MONTHS[a.month - 1]} {a.year} {DASH} {b.day} {MONTHS[b.month - 1]} {b.year}"
    if a.month != b.month:
        return f"{a.day} {MONTHS[a.month - 1]} {DASH} {b.day} {MONTHS[b.month - 1]} {b.year}"
    return f"{a.day}{DASH}{b.day} {MONTHS[a.month - 1]} {a.year}"


def _plural(n: int, noun: str, many: str | None = None) -> str:
    return f"{n} {noun if n == 1 else many or noun + 's'}"


def _reads(tiers: Sequence[int] | None, tier: int) -> bool:
    return tiers is None or tier in tiers


# -- the reading -------------------------------------------------------------------------------------------


def week_draft(site: Site, week: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """The week's standing draft and its withheld row through the page's gate, as the Sunday's Day reads
    it (`drafts.for_unit`, the evidence checked against the week's lines), kept for the record as it
    stands (`Site.shared`)."""

    def build() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        _week, monday, sunday = week_paper.parse_week(week)
        with site.lb.index() as idx:
            retracted = frozenset(retractions(idx.retractions()))
            found = drafts.by_unit(idx.by_kind(drafts.KIND), retracted, drafts.UNIT_WEEK).get(week, [])
            if not found:
                return None, None
            on_week = {
                str(line["id"])
                for d in day_range(monday, sunday)
                for line in idx.day(d)
                if str(line["id"]) not in retracted
            }
        return drafts.for_unit(found, on_week, site.tiers, drafts.allowed(site.lb.root), drafts.NOT_ON_WEEK)

    found: tuple[dict[str, Any] | None, dict[str, Any] | None] = site.shared(("week-draft", week), build)
    return found


def _days(site: Site, monday: str, sunday: str) -> list[tuple[str, Mapping[str, Any], Any]]:
    """Each day of the week as the Day reads it (`day.read` and the page's marks), from the Day's pool."""
    out: list[tuple[str, Mapping[str, Any], Any]] = []
    for day in day_range(monday, sunday):

        def read(day: str = day) -> dict[str, Any]:
            return day_reader.read(site.lb, day, site.airports, site.tiers, held=not site.static)

        out.append((day, site._day_reading(("day", day), read), site._day_marks(day)))
    return out


def _names(site: Site) -> list[str]:
    """Every canonical person's name, for the guard: never shown."""
    directory = site._day_reading(("directory",), lambda: people.directory(site.lb))
    return sorted({p.name for p in directory.known.values() if p.name})


# -- the page ----------------------------------------------------------------------------------------------


def page_week(site: Site, week: str, expanded: bool = False) -> str:
    """`/week/YYYY-Www`: the week's parts, each folded with its summary (the module's docstring).
    `ValueError` for a week the calendar does not have."""
    week, monday, sunday = week_paper.parse_week(week)
    zone = ZoneInfo(str(site.lb.meta["timezone"]))
    bounds = day_start.of(site.lb.meta)
    today = bounds.today(site.now()).isoformat()
    names = _names(site)
    days = _days(site, monday, sunday)
    draft, withheld = week_draft(site, week) if site.with_drafts else (None, None)
    tier = max(
        [int(line.get("tier") or 0) for _d, _data, marks in days for line in marks.lines.values()] or [0]
    )
    if draft is not None:
        tier = max(tier, int(draft.get("tier") or 0))

    folds: list[str] = []
    empty: list[str] = []

    def add(title: str, summary: str, body: str) -> None:
        if body:
            folds.append(day_rhythm.fold(title, summary, body, expanded))
        else:
            empty.append(title.lower() if title != "Hold" else title)

    add("The seven days", *_seven(site, days, bounds, zone))
    if draft is not None:
        add("Where the week went", *_went(site, draft, names))
    else:
        empty.append("where the week went")
    shelf = None
    if _reads(site.tiers, goals.TIER):
        shelf = site._day_reading(
            ("goals", sunday), lambda: shelf_goals.read(site.lb, site.tiers, today=sunday)
        )
        tier = max(tier, shelf.tier)
    add("Goals", *_goals(site, shelf, days, draft, sunday, names))
    if draft is not None:
        add("Next week", *_next_week(site, draft, names))
        add("The question", *_question(draft, names))
        add("People who moved", *_moved(site, week, monday, draft))
    else:
        empty += ["next week", "the question", "people who moved"]
    add("The plan", *_plan(site, monday, sunday, today))
    add("Hold", *_hold(site, today, zone))

    before = week_paper.week_of((date.fromisoformat(monday) - timedelta(days=7)).isoformat())
    after = week_paper.week_of((date.fromisoformat(monday) + timedelta(days=7)).isoformat())
    head = [
        f"<h1>The week {escape(week)} {site.tier_small(span_text(monday, sunday), tier or None)}</h1>\n",
        f'<p class="pager">{site.link(f"← {before}", week_path(before))}{DOT}'
        f"{site.link(escape(f'its Sunday, {sunday}'), f'/day/{sunday}')}{DOT}"
        f"{site.link(f'{after} →', week_path(after))}</p>\n",
    ]
    if not site.with_drafts:
        head.append(f'<p class="mute">{escape(NO_DRAFTS)}</p>\n')
    elif draft is None and withheld is not None:
        head.append(f'<p class="mute">{escape(drafts.withheld_text(withheld))}</p>\n')
    elif draft is None:
        command = f'<code class="cmd">logbook dream week {escape(week)}</code>'
        head.append(
            f'<p class="mute">{escape(NO_DRAFT)}: {command} writes one once its Sunday is over.</p>\n'
        )
    else:
        line = site.href(f"/line/{quote(str(draft['line']), safe='')}")
        model = escape(day_rhythm.model_of(draft))
        written = f'<a href="{escape(line)}">the draft as written</a>' if line is not None else "the draft"
        head.append(
            f'<p class="mute">From {written}, by <span class="sc">{model}</span>: its numbers are the'
            " code's, its sentences pencil.</p>\n"
        )
    body = [
        day_rhythm.part("header", "".join(head)),
        day_rhythm.part("record", "".join(folds)),
        day_rhythm.nothing_from(empty),
        f'<p class="later">{escape(LATER)}</p>\n',
        f'<p class="foot">{escape(day_rhythm.FOOTER)}</p>\n',
    ]
    return site.document(f"week {week}", "".join(body), style=day_rhythm.STYLE + WEEK_STYLE)


# -- the parts ---------------------------------------------------------------------------------------------


def _lines(site: Site, ids: Sequence[str]) -> str:
    """The lines a figure rests on: the first `ID_SHOWN` linked to each as written, the rest counted."""
    shown = []
    for line_id in ids[:ID_SHOWN]:
        href = site.href(f"/line/{quote(str(line_id), safe='')}")
        short = escape(drafts.short_id(str(line_id)))
        shown.append(f'<a href="{escape(href)}">{short}</a>' if href is not None else short)
    rest = len(ids) - ID_SHOWN
    if rest > 0:
        shown.append(f"{rest} more")
    return f' <small class="mute">[{", ".join(shown)}]</small>' if shown else ""


def _seven(
    site: Site, days: Sequence[tuple[str, Mapping[str, Any], Any]], bounds: day_start.DayStart, zone: ZoneInfo
) -> tuple[str, str]:
    rows = []
    legend = ""
    lived = planned = 0
    for day, data, marks in days:
        drawn = day_rhythm.ribbon(data, marks.lines, bounds.span(date.fromisoformat(day)), None)
        svg, _, rest = drawn.partition('<p class="legend">')
        legend = legend or f'<p class="legend">{rest}'
        planned += len(day_rhythm.planned(data, marks.lines))
        lived += 1 if data["sources"] else 0
        when = date.fromisoformat(day)
        label = escape(f"{data['weekday']} {when.day} {MONTHS[when.month - 1]}")
        rows.append(f'<li><p class="day">{site.link(label, f"/day/{day}")}</p>\n{svg}</li>\n')
    summary = f"{_plural(lived, 'day')} with lines{DOT}{_plural(planned, 'entry', 'entries')} planned"
    return summary, f'<ol class="week">\n{"".join(rows)}</ol>\n{legend}'


def _went(site: Site, draft: Mapping[str, Any], names: Sequence[str]) -> tuple[str, str]:
    numbers = draft.get("numbers") or {}
    out: list[str] = []
    counts: list[str] = []
    places = [p for p in numbers.get("places") or [] if isinstance(p, dict)]
    if places:
        rows = "".join(
            f'<li class="line">{escape(str(p.get("place") or ""))}{DOT}{escape(str(p.get("hours")))} h'
            f"{_lines(site, p.get('lines') or [])}</li>\n"
            for p in places
        )
        out.append(f'<h3>Hours by place</h3>\n<ul class="plain">\n{rows}</ul>\n')
        counts.append(_plural(len(places), "place"))
    threads = [t for t in numbers.get("threads") or [] if isinstance(t, dict)]
    shown = []
    for t in threads:
        title = str(t.get("thread") or "")
        if beside(title, names):
            shown.append(
                f'<li class="line mute">{escape(WITHHELD_BESIDE)}{_lines(site, t.get("lines") or [])}</li>\n'
            )
            continue
        bits = [escape(title), escape(str(t.get("kind") or ""))]
        named = t.get("kind") == "chat" or any(n and n in title for n in names)
        if not named:  # a person is never beside a count: a chat is its counterpart, a title may name one
            figure = _plural(int(t.get("count") or 0), "line")
            if t.get("hours"):
                figure += f", {t['hours']} h"
            elif t.get("minutes"):
                figure += f", {t['minutes']} min"
            bits.append(escape(figure))
        shown.append(f'<li class="line">{DOT.join(bits)}{_lines(site, t.get("lines") or [])}</li>\n')
    if shown:
        out.append(f'<h3>Threads</h3>\n<ul class="plain">\n{"".join(shown)}</ul>\n')
        counts.append(_plural(len(shown), "thread"))
    energy = numbers.get("energy")
    if _reads(site.tiers, 3):
        if isinstance(energy, dict) and (energy.get("sleep") or energy.get("training")):
            rows_ = []
            sleep, training = energy.get("sleep"), energy.get("training")
            if isinstance(sleep, dict):
                nights = _plural(int(sleep.get("nights") or 0), "night")
                said = f"{nights}, {sleep.get('hours')} h asleep a night"
                rows_.append(
                    f'<li class="line">{escape(said)}{_lines(site, sleep.get("lines") or [])}</li>\n'
                )
            if isinstance(training, dict):
                said = (
                    f"{_plural(int(training.get('sessions') or 0), 'workout')},"
                    f" {training.get('minutes')} min of training"
                )
                rows_.append(
                    f'<li class="line">{escape(said)}{_lines(site, training.get("lines") or [])}</li>\n'
                )
            out.append(f'<h3>Sleep and training</h3>\n<ul class="plain">\n{"".join(rows_)}</ul>\n')
            counts.append("sleep and training")
        else:
            out.append('<p class="mute">Sleep and training: no data the draft read.</p>\n')
    if not places and not shown and not out:
        return "", ""
    out.append('<p class="mute">Computed from the lines, not by the model; who you spent it with is under'
               " People who moved, by name only.</p>\n")  # fmt: skip
    return DOT.join(counts) or "no figures", "".join(out)


def _goal_days(
    g: shelf_goals.Goal, shelf: shelf_goals.Shelf, days: Sequence[tuple[str, Any, Any]]
) -> list[str]:
    return [day for day, _data, marks in days if g in day_rhythm.touched(shelf, marks.lines)]


def _goals(
    site: Site,
    shelf: shelf_goals.Shelf | None,
    days: Sequence[tuple[str, Mapping[str, Any], Any]],
    draft: Mapping[str, Any] | None,
    sunday: str,
    names: Sequence[str],
) -> tuple[str, str]:
    if shelf is None:
        said = (
            f"Goals and their reviews are your own words, tier {goals.TIER}; this page reads tier"
            f" {', '.join(str(t) for t in sorted(site.tiers or ())) or 'none'} only."
        )
        return "not read here", f'<p class="mute">{escape(said)}</p>\n'
    proposed: dict[str, Mapping[str, Any]] = {}
    segments = list((draft or {}).get("segments") or [])
    for review in ((draft or {}).get("proposed") or {}).get("goals") or []:
        if isinstance(review, dict) and isinstance(review.get("goal"), str):
            proposed[str(shelf.by_line.get(review["goal"]) or review["goal"])] = review
    shown = []
    touched_n = 0
    for g in shelf.goals:
        on = _goal_days(g, shelf, days)
        if g.state != "open" and not on:
            continue
        touched_n += 1 if on else 0
        text = escape(g.text) if not beside(g.text, names) else escape(WITHHELD_BESIDE)
        rows = [f'<p class="line"><b>{site.link(text, shelf_goals.goal_path(g.line))}</b>'
                f' <span class="mute">{escape(g.state)}</span></p>\n']  # fmt: skip
        if on:
            words = ", ".join(day_reader.WEEKDAYS[date.fromisoformat(d).weekday()] for d in on)
            rows.append(f"<p>The week touched it on {escape(words)}.</p>\n")
        else:
            rows.append('<p class="mute">Nothing in the week touched it.</p>\n')
        if g.review is not None:
            day = site.link(escape(g.review.day), f"/day/{g.review.day}")
            rows.append(f"<p>Your latest verdict: {escape(g.review.disposition)}, {day}.</p>\n")
        else:
            rows.append('<p class="mute">Not reviewed yet.</p>\n')
        review = proposed.get(g.line)
        if review is not None and site.with_drafts:
            index = review.get("segment")
            why = ""
            if isinstance(index, int) and 0 <= index < len(segments) and segments[index].get("supported"):
                said = str(segments[index].get("text") or "")
                if not beside(said, names):
                    why = f": {escape(said)}"
            rows.append(
                '<div class="paper"><p>The week\'s draft proposes'
                f" {escape(str(review.get('disposition')))}{why}</p></div>\n"
            )
        command = f"logbook goal review {g.line} {'|'.join(VERDICTS)} --period week --at {sunday}"
        rows.append(
            f'<p>Your verdict, one of five: <code class="cmd">{escape(command)}</code>, or in the week\'s'
            ' sitting, <code class="cmd">logbook review goal</code>.</p>\n'
        )
        shown.append(f'<li id="goal-{escape(g.line)}">{"".join(rows)}</li>\n')
    if not shown:
        return "", ""
    moves = (
        "<h3>When a goal stalls, two honest moves</h3>\n"
        "<p><b>Change the days</b>: the week's one proposal, under Next week.</p>\n"
        "<p><b>Change the sentence</b>: reword it, "
        '<code class="cmd">logbook goal add "…" --horizon H --supersedes GOAL</code>, or let it go, '
        '<code class="cmd">logbook goal review GOAL let-go</code>.</p>\n'
    )
    proposals = sum(1 for g in shelf.goals if g.line in proposed) if site.with_drafts else 0
    summary = [_plural(len(shown), "goal"), f"{touched_n} touched this week"]
    if proposals:
        summary.append(_plural(proposals, "verdict") + " proposed")
    return DOT.join(summary), f'<ol class="week">\n{"".join(shown)}</ol>\n{moves}'


def proposal_html(site: Site, draft: Mapping[str, Any], names: Sequence[str]) -> str:
    """The draft's one proposal for next week, in pencil: headed with the model's name, its sentence and
    its lines; withheld when it sets a number beside a person's name, the line as written named."""
    found = [s for s in draft.get("segments") or [] if s.get("part") == "next_week"]
    if not found:
        return ""
    segment = found[0]
    model = escape(day_rhythm.model_of(draft))
    text = str(segment.get("text") or "")
    href = site.href(f"/line/{quote(str(draft.get('line')), safe='')}")
    if beside(text, names):
        written = f' <a href="{escape(href)}">the draft as written</a>' if href is not None else ""
        said = f'<p class="mute">{escape(WITHHELD_BESIDE)}{written}</p>\n'
    elif segment.get("supported"):
        said = f"<p>{escape(text)}{_lines(site, segment.get('evidence') or [])}</p>\n"
    else:
        why = f": {escape(str(segment['why']))}" if segment.get("why") else ""
        said = (
            f'<p class="segment unsupported">{escape(text)} <span class="mute">unsupported{why}</span></p>\n'
        )
    return f'<div class="paper"><p class="eyebrow">Pencil <span class="sc">{model}</span></p>\n{said}</div>\n'


def _next_week(site: Site, draft: Mapping[str, Any], names: Sequence[str]) -> tuple[str, str]:
    body = proposal_html(site, draft, names)
    if not body:
        return "", ""
    return "one proposal, pencil", body + (
        '<p class="mute">A proposal only: kept, it is yours; ignored, nothing happens.</p>\n'
    )


def _question(draft: Mapping[str, Any], names: Sequence[str]) -> tuple[str, str]:
    asked = (draft.get("proposed") or {}).get("question")
    if not isinstance(asked, dict) or not asked.get("text"):
        return "", ""
    text = str(asked["text"])
    if beside(text, names):
        return "one question", f'<p class="mute">{escape(WITHHELD_BESIDE)}</p>\n'
    kind = str((asked.get("entity") or {}).get("type") or "idea")
    command = f'logbook status {kind} "{asked.get("label") or ""}" STATUS'
    return "one question, asked once", (
        f'<p class="ink">{escape(text)}</p>\n'
        f'<p class="mute">Answer it with <code class="cmd">{escape(command)}</code>, or leave it: it may be'
        " ignored forever.</p>\n"
    )


def _contacts(draft: Mapping[str, Any] | None) -> dict[str, tuple[str, int]]:
    """id → (name, contacts) of the people a week's draft counts (`numbers.people`)."""
    out: dict[str, tuple[str, int]] = {}
    for p in ((draft or {}).get("numbers") or {}).get("people") or []:
        if isinstance(p, dict) and isinstance(p.get("id"), str):
            out[p["id"]] = (str(p.get("name") or ""), int(p.get("contacts") or 0))
    return out


def _moved(site: Site, week: str, monday: str, draft: Mapping[str, Any]) -> tuple[str, str]:
    before = week_paper.week_of((date.fromisoformat(monday) - timedelta(days=7)).isoformat())
    earlier, _withheld = week_draft(site, before)
    if earlier is None:
        return "", ""
    now, was = _contacts(draft), _contacts(earlier)
    moved = []
    for entity in set(now) | set(was):
        a, b = now.get(entity, ("", 0))[1], was.get(entity, ("", 0))[1]
        if a != b:
            name = now.get(entity, was.get(entity, ("", 0)))[0]
            moved.append((-abs(a - b), name.casefold(), name, entity))
    if not moved:
        return "", ""
    rows = "".join(
        "<li>" + site.link(f'<span class="person">{escape(name)}</span>', _person_path(entity)) + "</li>\n"
        for _d, _k, name, entity in sorted(moved)[:MOVERS]
    )
    return "against the week before, names only", (
        f'<ul class="plain">\n{rows}</ul>\n'
        f'<p class="mute">Among the people each week\'s draft counts, against {escape(before)}.</p>\n'
    )


def _plan(site: Site, monday: str, sunday: str, today: str) -> tuple[str, str]:
    if not _reads(site.tiers, 1):
        return "", ""
    day = min(max(today, monday), sunday)  # the week's last day the clock has reached, its first ahead
    try:
        found = site.shared(("plan", day), lambda: plan.read(site.lb, day))
    except plan.PlanError as e:
        return "not read", f'<p class="mute">{escape(str(e))}</p>\n'
    if not found.mapped or (found.sprint is None and found.trip is None):
        return "", ""

    def row(label: str, ref: Mapping[str, Any], after: str = "") -> str:
        line = site.href(f"/line/{quote(str(ref.get('line')), safe='')}") if ref.get("line") else None
        title = escape(str(ref.get("title") or plan.UNTITLED))
        when = plan._date_text(ref.get("date"))
        linked = f'<a href="{escape(line)}">{title}</a>' if line is not None else title
        return f'<li class="line">{escape(label)}: {linked}{DOT}{escape(when)}{escape(after)}</li>\n'

    rows, summary = [], []
    if found.sprint is not None:
        rows.append(row("the sprint", found.sprint))
        summary.append(str(found.sprint.get("title") or plan.UNTITLED))
    if found.trip is not None:
        rows.append(row("the next trip", found.trip, f"{DOT}{plan._days_text(int(found.trip['days']))}"))
        summary.append(f"next trip {plan._days_text(int(found.trip['days']))}")
    note = f'<p class="mute">From the plan as it stood on {escape(day)} (sync notion, tier 1).</p>\n'
    return DOT.join(summary), f'<ul class="plain">\n{"".join(rows)}</ul>\n{note}'


def _hold(site: Site, today: str, zone: ZoneInfo) -> tuple[str, str]:
    """Hold's senders and Drive censuses, counts only, through the gate; nothing of a name."""
    from ..core.search import MAX_TIER
    from ..labs import hold  # a lab: loaded by the week page, never by `--help`

    tiers = site.tiers
    top = max(tiers) if tiers else MAX_TIER
    now = datetime.combine(date.fromisoformat(today), time(), zone)  # the record's day: the tag's
    rows, summary = [], []
    if _reads(tiers, 2):
        senders = site.shared(("hold-senders", top, today), lambda: hold.census_senders(site.lb, top, now))
        t = senders["totals"]
        if t["received"]:
            said = [
                f"{_plural(int(t['senders']), 'sender')} wrote {_plural(int(t['received']), 'mail')}",
                f"{t['never_answered']} never answered",
            ]
            letters = senders["newsletters"]
            if letters.get("held"):
                said.append(_plural(int(letters["senders"]), "newsletter"))
            rows.append(f"<li>Mail: {escape(DOT.join(said))}</li>\n")
            summary.append(_plural(int(t["senders"]), "sender"))
    drive = site.shared(("hold-drive", top, today), lambda: hold.census_drive(site.lb, top, now))
    d = drive["totals"]
    if d["files"]:
        said = [
            _plural(int(d["files"]), "file"),
            f"{d['untouched']} untouched for {drive['settings']['untouched_days']} days",
            f"{d['shared']} shared",
            f"{d['gone']} trashed",
        ]
        rows.append(f"<li>Drive: {escape(DOT.join(said))}</li>\n")
        summary.append(_plural(int(d["files"]), "file"))
    if not rows:
        return "", ""
    return DOT.join(summary), (
        f'<ul class="plain">\n{"".join(rows)}</ul>\n'
        "<p class=\"mute\">Hold's census as the record stands, counts only. Its sweep stays Hold's:"
        ' <code class="cmd">logbook lab hold census</code>.</p>\n'
    )


def link_html(site: Site, day: str) -> str:
    """The week a day is in, as a link to its page; nothing where the page has none (a static site)."""
    week = week_paper.week_of(day)
    return site.link(escape(f"the week {week}"), week_path(week)) if site.href(week_path(week)) else ""
