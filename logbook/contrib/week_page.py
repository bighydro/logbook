"""The week page of `logbook serve` (RFC 0043 §8, slice D, part 1): `/week/YYYY-Www`, the Sunday's week
draft (`dream week`, RFC 0036 unit `week`) grown into a page, and closed there (part 2): one form, no
script.

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
   command that gives one, and the two honest moves in words: change the days (the week's one
   proposal) or change the sentence (reword it, `goal add --supersedes`, or let it go).
4. **Next week**: the intention kept on the Sunday (`week_close.kept`), in ink, when one was; and the
   draft's one proposal (`next_week`), in pencil, headed with the model's name, with its lines.
5. **The question**: the draft's one stale question (`extra.question`, code's), asked once.
6. **People who moved**: the people whose contacts in this week's draft differ from the week before's
   draft (`numbers.people` of each, through the same gate), the largest change first, five at most;
   names only, never a count or a direction beside a name.
7. **The plan**: the sprint and the next trip (`plan.read`, the `sync notion` lines, tier 1) as the
   week's last day the clock has reached stood; titles and dates, each linked to its line, never to
   Notion: no URL but the server's own.
8. **Hold**: the senders and Drive censuses as they stand, from the reports `lab hold census` last wrote
   under `state/hold/` (`HOLD_FILES`, which the page's tag digests): counts only, never a file's name or a
   sender, and a report only where the page reads the tiers it read. The census is a lab and runs only
   when the owner runs it: a page never imports it (the import arrow) and never runs it. On the week
   page only.

Then **Close the week** (`close_html`), on `logbook serve` only (a static site carries no form) and only
where the page reads tier 2 (the goals and the intention are the owner's words): one form posting to
`/week/YYYY-Www/close`, which the server answers through `week_close.close` behind the write gate of
every act. Each goal open on the Sunday, begun by it and not reviewed on a day of the week yet, with
the five verdicts as one choice (none chosen: no verdict), your words on it, the command that writes
the same line beside it, and the two honest moves when it stalls, the second the `goal add
--supersedes` command written out for that goal, linked to its page; a goal the week has a verdict on
already says it, with no choice. Then next week's intention: the words kept already, else the
proposal's when it is shown and supported, in the field, written only when Keep is ticked, with the
command beside it. A week whose Sunday is ahead says when it closes and carries no form.

The draft's parts (2, 4, 5, 6 and the proposed verdicts of 3) are behind `with_drafts`: a static site
built without its drafts (`export site`, #364) reads no draft and says so in one line. A model's
sentence, a thread's title or the question that would put a digit beside a person's name (`beside`) is
withheld, its row saying so and naming the line as written.

Left for later, and said on the page: time by project, the sprint's done, rolled and let go (slice C's
dispositions in the crossing) and the pile untouched for 90 days."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from html import escape
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from ..core import day as day_reader
from ..core import day_start, drafts, goals, notes, people
from ..core.export import day_range
from ..core.store import retractions
from . import day_rhythm, plan, shelf_goals, week_close, week_paper

if TYPE_CHECKING:  # the Site passes itself; serve imports this module, never the other way at import
    from .serve import Site

DOT = day_rhythm.DOT
DASH = day_rhythm.DASH
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")  # fmt: skip
HOLD_DIR = PurePosixPath(
    "state/hold"
)  # record-relative: where `lab hold census` writes (`labs.hold.REPORTS`)
HOLD_CENSUSES = ("senders", "drive")  # the censuses of lines the record holds; the files one walks folders
HOLD_FILES = tuple(HOLD_DIR / f"{c}.json" for c in HOLD_CENSUSES)  # what the page reads beside the chain
FIRST_YEAR, LAST_YEAR = 2, 9998  # the weeks a page shows: its neighbours and nights within the calendar
ID_SHOWN = 4  # line ids a figure links; the rest are counted
MOVERS = 5  # the people who moved, at most
VERDICTS = tuple(d.replace(" ", "-") for d in goals.DISPOSITIONS)  # as `goal review` takes them
NO_DRAFT = "The week has no draft yet"
NO_DRAFTS = (
    "This site was built without its drafts: the week's numbers, its proposal, its question and the people"
    " who moved are in the week's draft, left out."
)
WITHHELD_BESIDE = "Withheld here: it sets a number beside a person's name."
LATER = "Later: time by project, the sprint's done, rolled and let go, and the pile untouched for 90 days."
CLOSE = "close"  # the anchor of Close the week, where its form sends the owner back
NO_VERDICT = "no verdict"  # the choice a goal starts at: nothing written for it
BESIDE = "[\\s(:×x#·,]*"  # what may stand between a name and a number and still be beside it
WEEK_STYLE = """
ol.week{list-style:none;padding:0;margin:0}
ol.week>li{padding:4px 0;border-bottom:1px solid var(--line)}ol.week>li:last-child{border-bottom:0}
ol.week p.day{margin:0;font-size:13.5px}
p.line,li.line{overflow-wrap:anywhere}
p.ids{margin:0;font-size:11.5px;color:var(--mute);overflow-wrap:anywhere}div.paper p.ids{line-height:28px}
code.cmd{font-family:var(--mono);font-size:12.5px;overflow-wrap:anywhere;white-space:normal}
ul.plain{list-style:none;padding:0;margin:0 0 6px}ul.plain>li{padding:2px 0;overflow-wrap:anywhere}
p.later{color:var(--mute);font-size:12.5px;margin:18px 0 6px}
fieldset.verdict{border:0;border-top:1px solid var(--line);padding:8px 0 4px;margin:0;min-width:0}
fieldset.verdict legend{padding:0;font-weight:600;overflow-wrap:anywhere;max-width:100%}
p.choices{display:flex;flex-wrap:wrap;gap:0 14px;margin:4px 0}
p.choices label,label.keep{display:inline-flex;align-items:center;gap:6px;min-height:44px}
section.close input[type=text]{width:100%;box-sizing:border-box}
p.ink.kept{margin:4px 0}
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


def _n(value: object) -> int:
    """A count as the draft or a report keeps it; anything else (a string, a bool, a float) is 0."""
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _ids(value: object) -> list[str]:
    """The line ids a figure keeps (`lines`, `evidence`); anything but a list of strings is none."""
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


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
    `ValueError` for a week the calendar does not have, or one at its edge (the year 1 or 9999, whose
    week before or after, or whose day's night, the calendar cannot hold)."""
    if not FIRST_YEAR <= int(week[:4]) <= LAST_YEAR:
        raise ValueError(f"{week}: the week page shows the years {FIRST_YEAR} to {LAST_YEAR}")
    week, monday, sunday = week_paper.parse_week(week)
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

    add("The seven days", *_seven(site, days, bounds))
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
    intention = None
    if _reads(site.tiers, notes.TIER):
        intention = site._day_reading(
            ("intention", sunday), lambda: week_close.kept(site.lb, sunday, site.tiers)
        )
        if intention is not None:
            tier = max(tier, int(intention.get("tier") or 0))
    if draft is not None or intention is not None:
        add("Next week", *_next_week(site, draft, intention, sunday, names))
    else:
        empty.append("next week")
    if draft is not None:
        add("The question", *_question(draft, names))
        add("People who moved", *_moved(site, week, monday, draft))
    else:
        empty += ["the question", "people who moved"]
    add("The plan", *_plan(site, monday, sunday, today, names))
    held, hold_body, hold_tier = _hold(site)
    add("Hold", held, hold_body)
    tier = max(tier, hold_tier)

    before = week_paper.week_of((date.fromisoformat(monday) - timedelta(days=7)).isoformat())
    after = week_paper.week_of((date.fromisoformat(monday) + timedelta(days=7)).isoformat())
    span = _span(site, today)
    head = [
        f"<h1>The week {escape(week)} {site.tier_small(span_text(monday, sunday), tier or None)}</h1>\n",
        f'<p class="pager">{_week_link(site, f"← {before}", before, span)}{DOT}'
        f"{site.link(escape(f'its Sunday, {sunday}'), f'/day/{sunday}')}{DOT}"
        f"{_week_link(site, f'{after} →', after, span)}</p>\n",
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
    closing = close_html(site, shelf, draft, intention, week, monday, sunday, today, names)
    body = [
        day_rhythm.part("header", "".join(head)),
        day_rhythm.part("record", "".join(folds)),
        day_rhythm.nothing_from(empty),
        *([day_rhythm.part("close", closing)] if closing else []),
        f'<p class="later">{escape(LATER)}</p>\n',
        f'<p class="foot">{escape(day_rhythm.FOOTER)}</p>\n',
    ]
    return site.document(f"week {week}", "".join(body), style=day_rhythm.STYLE + WEEK_STYLE)


# -- the parts ---------------------------------------------------------------------------------------------


def _lines(site: Site, ids: Sequence[str]) -> str:
    """The lines a figure rests on: the first `ID_SHOWN` linked to each as written, the rest counted, as
    a block of their own (`p.ids`): an id may begin with a digit, and a block's end, never a bracket,
    is what stands between it and a name the row above may carry."""
    shown = []
    for line_id in ids[:ID_SHOWN]:
        href = site.href(f"/line/{quote(str(line_id), safe='')}")
        short = escape(drafts.short_id(str(line_id)))
        shown.append(f'<a href="{escape(href)}">{short}</a>' if href is not None else short)
    rest = len(ids) - ID_SHOWN
    if rest > 0:
        shown.append(f"{rest} more")
    return f'<p class="ids">[{", ".join(shown)}]</p>' if shown else ""


def _seven(
    site: Site, days: Sequence[tuple[str, Mapping[str, Any], Any]], bounds: day_start.DayStart
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


def _place(site: Site, p: Mapping[str, Any], names: Sequence[str]) -> str:
    """A place's hours with its lines; a place named as a person is withheld, never beside its hours."""
    lines = _lines(site, _ids(p.get("lines")))
    if beside(f"{p.get('place')} {p.get('hours')}", names):
        return f'<li class="line mute">{escape(WITHHELD_BESIDE)}{lines}</li>\n'
    place, hours = escape(str(p.get("place") or "")), escape(str(p.get("hours")))
    return f'<li class="line">{place}{DOT}{hours} h{lines}</li>\n'


def _went(site: Site, draft: Mapping[str, Any], names: Sequence[str]) -> tuple[str, str]:
    found = draft.get("numbers")
    numbers: Mapping[str, Any] = found if isinstance(found, dict) else {}
    out: list[str] = []
    counts: list[str] = []
    places = [p for p in _list(numbers.get("places")) if isinstance(p, dict)]
    if places:
        rows = "".join(_place(site, p, names) for p in places)
        out.append(f'<h3>Hours by place</h3>\n<ul class="plain">\n{rows}</ul>\n')
        counts.append(_plural(len(places), "place"))
    threads = [t for t in _list(numbers.get("threads")) if isinstance(t, dict)]
    shown = []
    for t in threads:
        title = str(t.get("thread") or "")
        if beside(title, names):
            shown.append(
                f'<li class="line mute">{escape(WITHHELD_BESIDE)}{_lines(site, _ids(t.get("lines")))}</li>\n'
            )
            continue
        bits = [escape(title), *([escape(str(t["kind"]))] if t.get("kind") else [])]
        named = t.get("kind") == "chat" or any(n and n in title for n in names)
        if not named:  # a person is never beside a count: a chat is its counterpart, a title may name one
            figure = _plural(_n(t.get("count")), "line")
            if t.get("hours"):
                figure += f", {t['hours']} h"
            elif t.get("minutes"):
                figure += f", {t['minutes']} min"
            bits.append(escape(figure))
        shown.append(f'<li class="line">{DOT.join(bits)}{_lines(site, _ids(t.get("lines")))}</li>\n')
    if shown:
        out.append(f'<h3>Threads</h3>\n<ul class="plain">\n{"".join(shown)}</ul>\n')
        counts.append(_plural(len(shown), "thread"))
    energy = numbers.get("energy")
    if _reads(site.tiers, 3):
        if isinstance(energy, dict) and (energy.get("sleep") or energy.get("training")):
            rows_ = []
            sleep, training = energy.get("sleep"), energy.get("training")
            if isinstance(sleep, dict):
                nights = _plural(_n(sleep.get("nights")), "night")
                said = f"{nights}, {sleep.get('hours')} h asleep a night"
                rows_.append(
                    f'<li class="line">{escape(said)}{_lines(site, _ids(sleep.get("lines")))}</li>\n'
                )
            if isinstance(training, dict):
                said = (
                    f"{_plural(_n(training.get('sessions')), 'workout')},"
                    f" {training.get('minutes')} min of training"
                )
                rows_.append(
                    f'<li class="line">{escape(said)}{_lines(site, _ids(training.get("lines")))}</li>\n'
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
    by_day = [(day, day_rhythm.touched(shelf, marks.lines)) for day, _data, marks in days]
    shown = []
    touched_n = 0
    for g in shelf.goals:
        on = [day for day, touched in by_day if g in touched]
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
            if (
                isinstance(index, int)
                and not isinstance(index, bool)
                and 0 <= index < len(segments)
                and isinstance(segments[index], dict)
                and segments[index].get("supported")
            ):
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
        said = f"<p>{escape(text)}</p>\n{_lines(site, _ids(segment.get('evidence')))}"
    else:
        why = f": {escape(str(segment['why']))}" if segment.get("why") else ""
        said = (
            f'<p class="segment unsupported">{escape(text)} <span class="mute">unsupported{why}</span></p>\n'
        )
    return f'<div class="paper"><p class="eyebrow">Pencil <span class="sc">{model}</span></p>\n{said}</div>\n'


def kept_html(site: Site, intention: Mapping[str, Any], sunday: str, names: Sequence[str]) -> str:
    """The intention kept on the Sunday, in ink, with its Sunday and its line; withheld when it sets a
    number beside a person's name, the line as written named."""
    text = str((intention.get("payload") or {}).get("text") or "")
    href = site.href(f"/line/{quote(str(intention.get('id')), safe='')}")
    line = f'{DOT}<a href="{escape(href)}">the line</a>' if href is not None else ""
    on = escape(sunday_text(sunday))
    if beside(text, names):
        return f'<p class="mute">Kept on {on}: {escape(WITHHELD_BESIDE)}{line}</p>\n'
    return (
        f'<p class="ink kept">{escape(text)}</p>\n'
        f'<p class="mute">Kept on {on}: next week\'s intention, in your words{line}</p>\n'
    )


def sunday_text(sunday: str) -> str:
    """`Sunday 21 June`."""
    when = date.fromisoformat(sunday)
    return f"Sunday {when.day} {MONTHS[when.month - 1]}"


def close_html(
    site: Site,
    shelf: shelf_goals.Shelf | None,
    draft: Mapping[str, Any] | None,
    intention: Mapping[str, Any] | None,
    week: str,
    monday: str,
    sunday: str,
    today: str,
    names: Sequence[str],
) -> str:
    """Close the week: the one form (the module's docstring), or the sentence that says when the week
    closes; nothing on a static site or a page that does not read tier 2. Every control has the command
    that writes the same line beside it."""
    if site.static or shelf is None or not _reads(site.tiers, notes.TIER):
        return ""
    out = [f'<section class="close">\n<h2 id="{CLOSE}">Close the week</h2>\n']
    if sunday > today:
        out.append(
            f'<p class="mute">The week closes on its Sunday, {escape(sunday)}: its verdicts and next'
            " week's intention are written on it or after it.</p>\n</section>\n"
        )
        return "".join(out)
    out.append(
        '<p class="mute">Your verdicts on the goals and next week\'s intention, each one line in your words'
        f" on {escape(sunday_text(sunday))}. Nothing is written until you press Close the week; every"
        " item is checked before the first line, and one refused writes nothing.</p>\n"
        f'<form class="close-week" method="post" action="{escape(week_path(week))}/close">\n'
    )
    rows = []
    for g in shelf.goals:
        if g.state != "open" or not g.start or g.start > sunday:
            continue
        text = escape(g.text) if not beside(g.text, names) else escape(WITHHELD_BESIDE)
        linked = site.link(text, shelf_goals.goal_path(g.line))
        given = [r for r in g.reviews if monday <= r.day <= sunday]
        if given:
            r = given[0]  # the newest first
            rows.append(
                f'<fieldset class="verdict"><legend>{text}</legend>\n'
                f"<p>Your verdict for the week: {escape(r.disposition)}, {escape(r.day)}"
                f' <span class="mute">({escape(r.period)})</span>.</p>\n</fieldset>\n'
            )
            continue
        field = escape(f"verdict-{g.line}")
        choices = [
            f'<label><input type="radio" name="{field}" value="" checked> {NO_VERDICT}</label>',
            *(f'<label><input type="radio" name="{field}" value="{v}"> {v}</label>' for v in VERDICTS),
        ]
        command = f"logbook goal review {g.line} {'|'.join(VERDICTS)} --period week --at {sunday}"
        reword = f'logbook goal add "…" --horizon {g.horizon} --supersedes {g.line}'
        rows.append(
            f'<fieldset class="verdict"><legend>{linked}</legend>\n'
            f'<p class="choices">{"".join(choices)}</p>\n'
            f'<input type="text" name="{escape(f"note-{g.line}")}" placeholder="your words on it, if any"'
            ' aria-label="your words on the verdict" autocomplete="off">\n'
            f'<p class="ids"><code class="cmd">{escape(command)} --note "…"</code></p>\n'
            "<p>When it stalls: <b>change the days</b>, keep next week's intention below; or <b>change"
            f" the sentence</b>, {site.link('reword it', shelf_goals.goal_path(g.line))}:"
            f' <code class="cmd">{escape(reword)}</code>.</p>\n'
            "</fieldset>\n"
        )
    if rows:
        out.append("<h3>Goals</h3>\n" + "".join(rows))
    out.append("<h3>Next week's intention</h3>\n")
    prefill = ""
    if intention is not None:
        out.append(kept_html(site, intention, sunday, names))
        said = str((intention.get("payload") or {}).get("text") or "")
        prefill = "" if beside(said, names) else said
        what = "These words again keep nothing; other words take the place of the intention kept."
    else:
        segment = next((x for x in (draft or {}).get("segments") or [] if x.get("part") == "next_week"), None)
        said = str((segment or {}).get("text") or "")
        if site.with_drafts and segment is not None and segment.get("supported") and not beside(said, names):
            prefill = said
            what = "The week's proposal is in the field, pencil until you keep it; change the words first if"
            what += " they need it."
        else:
            what = "No proposal to keep: say the week ahead in a sentence of your own."
    command = f'logbook day reflect {sunday} --intention "…"'
    out.append(
        f'<p class="mute">{escape(what)}</p>\n'
        f'<textarea name="intention" rows="3" aria-label="next week\'s intention"'
        f' spellcheck="true">{escape(prefill, quote=False)}</textarea>\n'
        '<label class="keep"><input type="checkbox" name="keep" value="1"> Keep these words as next'
        " week's intention</label>\n"
        f'<p class="ids"><code class="cmd">{escape(command)}</code></p>\n'
        '<button name="act" value="close">Close the week</button>\n</form>\n</section>\n'
    )
    return "".join(out)


def _next_week(
    site: Site,
    draft: Mapping[str, Any] | None,
    intention: Mapping[str, Any] | None,
    sunday: str,
    names: Sequence[str],
) -> tuple[str, str]:
    pencil = proposal_html(site, draft, names) if draft is not None else ""
    summary = []
    body = ""
    if intention is not None:
        body = kept_html(site, intention, sunday, names)
        summary.append("the intention kept")
    if pencil:
        body += pencil
        summary.append("one proposal, pencil")
        if intention is None:
            body += '<p class="mute">A proposal only: kept, it is yours; ignored, nothing happens.</p>\n'
    if not body:
        return "", ""
    return DOT.join(summary), body


def _question(draft: Mapping[str, Any], names: Sequence[str]) -> tuple[str, str]:
    asked = (draft.get("proposed") or {}).get("question")
    if not isinstance(asked, dict) or not asked.get("text"):
        return "", ""
    text = str(asked["text"])
    if beside(text, names):
        return "one question", f'<p class="mute">{escape(WITHHELD_BESIDE)}</p>\n'
    entity = asked.get("entity")
    kind = str(entity.get("type") or "idea") if isinstance(entity, dict) else "idea"
    command = f'logbook status {kind} "{asked.get("label") or ""}" STATUS'
    return "one question, asked once", (
        f'<p class="ink">{escape(text)}</p>\n'
        f'<p class="mute">Answer it with <code class="cmd">{escape(command)}</code>, or leave it: it may be'
        " ignored forever.</p>\n"
    )


def _contacts(draft: Mapping[str, Any] | None) -> dict[str, tuple[str, int]]:
    """id → (name, contacts) of the people a week's draft counts (`numbers.people`)."""
    out: dict[str, tuple[str, int]] = {}
    numbers = (draft or {}).get("numbers")
    for p in _list(numbers.get("people")) if isinstance(numbers, dict) else []:
        if isinstance(p, dict) and isinstance(p.get("id"), str):
            out[p["id"]] = (str(p.get("name") or ""), _n(p.get("contacts")))
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


def _plan(site: Site, monday: str, sunday: str, today: str, names: Sequence[str]) -> tuple[str, str]:
    if not _reads(site.tiers, 1):
        return "", ""
    day = min(max(today, monday), sunday)  # the week's last day the clock has reached, its first ahead
    try:
        found = site.shared(("plan", day), lambda: plan.read(site.lb, day))
    except plan.PlanError as e:
        return "not read", f'<p class="mute">{escape(str(e))}</p>\n'
    if not found.mapped or (found.sprint is None and found.trip is None):
        return "", ""

    def named(ref: Mapping[str, Any]) -> bool:  # a title that names a person stands beside the dates
        return any(n in str(ref.get("title") or "") for n in names if n)

    def row(label: str, ref: Mapping[str, Any], after: str = "") -> str:
        line = site.href(f"/line/{quote(str(ref.get('line')), safe='')}") if ref.get("line") else None
        if named(ref):
            linked = escape(WITHHELD_BESIDE)
            linked = f'<a href="{escape(line)}">{linked}</a>' if line is not None else linked
            return f'<li class="line">{escape(label)}: {linked}</li>\n'
        title = escape(str(ref.get("title") or plan.UNTITLED))
        when = plan._date_text(ref.get("date"))
        linked = f'<a href="{escape(line)}">{title}</a>' if line is not None else title
        return f'<li class="line">{escape(label)}: {linked}{DOT}{escape(when)}{escape(after)}</li>\n'

    rows, summary = [], []
    if found.sprint is not None:
        rows.append(row("the sprint", found.sprint))
        summary.append(
            "the sprint" if named(found.sprint) else str(found.sprint.get("title") or plan.UNTITLED)
        )
    if found.trip is not None:
        rows.append(row("the next trip", found.trip, f"{DOT}{plan._days_text(int(found.trip['days']))}"))
        summary.append(f"next trip {plan._days_text(int(found.trip['days']))}")
    note = f'<p class="mute">From the plan as it stood on {escape(day)} (sync notion, tier 1).</p>\n'
    return DOT.join(summary), f'<ul class="plain">\n{"".join(rows)}</ul>\n{note}'


def hold_report(site: Site, census: str) -> dict[str, Any] | None:
    """Hold's saved report of `census` (`state/hold/<census>.json`, as `lab hold census` last wrote it),
    or None: no report, a folder that is a link or not a folder (never followed), or one that does not
    read. Only its counts are shown; its rows hold names and are never read out."""
    folder = site.lb.root.joinpath(*HOLD_DIR.parts)
    for place in (folder.parent, folder):
        if place.is_symlink() or (place.exists() and not place.is_dir()):
            return None
    path = folder / f"{census}.json"
    try:
        found = json.loads(path.read_bytes()) if path.is_file() and not path.is_symlink() else None
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) and isinstance(found.get("totals"), dict) else None


def _hold(site: Site) -> tuple[str, str, int]:
    """Hold's senders and Drive censuses as they stand, counts only, each only where the page reads
    every tier up to the one the report says it read (a report that names no tier is not read);
    nothing of a name. And the highest tier shown. The census itself is Hold's, a lab: the page reads
    what it wrote and never runs it."""
    rows, summary, left = [], [], []
    shown = 0
    for census in HOLD_CENSUSES:
        report = hold_report(site, census)
        if report is None:
            continue
        tier = _n(report.get("tier"))
        if not 1 <= tier <= 3:
            left.append(f"the {census} report names no tier")
            continue
        if site.tiers is not None and not all(t in site.tiers for t in range(1, tier + 1)):
            left.append(f"the {census} census read tier {tier}")
            continue
        t = report["totals"]
        made = str(report.get("made_at") or "")[:10]
        if census == "senders" and _n(t.get("received")):
            said = [
                f"{_plural(_n(t.get('senders')), 'sender')} wrote {_plural(_n(t.get('received')), 'mail')}",
                f"{_n(t.get('never_answered'))} never answered",
            ]
            letters = report.get("newsletters")
            if isinstance(letters, dict) and letters.get("held") is True:
                said.append(_plural(_n(letters.get("senders")), "newsletter"))
            summary.append(_plural(_n(t.get("senders")), "sender"))
        elif census == "drive" and _n(t.get("files")):
            settings = report.get("settings")
            days = _n(settings.get("untouched_days")) if isinstance(settings, dict) else 0
            said = [
                _plural(_n(t.get("files")), "file"),
                f"{_n(t.get('untouched'))} untouched for {days} days",
                f"{_n(t.get('shared'))} shared",
                f"{_n(t.get('gone'))} trashed",
            ]
            summary.append(_plural(_n(t.get("files")), "file"))
        else:
            continue
        shown = max(shown, tier)
        label = "Mail" if census == "senders" else "Drive"
        rows.append(
            f'<li>{label}: {escape(DOT.join(said))} <span class="mute">on {escape(made)}</span></li>\n'
        )
    if left:
        rows.append(f'<li class="mute">Not read here: {escape(", ".join(left))}.</li>\n')
    if not rows:
        return "", "", 0
    return (
        DOT.join(summary) or "not read here",
        f'<ul class="plain">\n{"".join(rows)}</ul>\n'
        '<p class="mute">Hold\'s census as it stands, counts only, from the reports Hold last wrote.'
        ' Its sweep stays Hold\'s: <code class="cmd">logbook lab hold census senders</code>, then'
        ' <code class="cmd">drive</code>.</p>\n',
        shown,
    )


def _span(site: Site, today: str) -> tuple[str, str] | None:
    """The days the pager may reach: the record's first to its last (`Site._record_days`, the owner's
    track else any line), or today when that is later. None for an empty record: no week is linked."""
    whole = site._record_days()
    return None if whole is None else (whole[0], max(whole[1], today))


def _week_link(site: Site, text: str, week: str, span: tuple[str, str] | None) -> str:
    """`text` as a link to `week`'s page while that week holds a day of `span`, else as plain words: so a
    crawl that follows the pager (the golden crawl, the open-ends walk) ends at the record's edges
    instead of walking every week of the calendar."""
    _week, monday, sunday = week_paper.parse_week(week)
    if span is None or sunday < span[0] or monday > span[1]:
        return escape(text)
    return site.link(escape(text), week_path(week))


def link_html(site: Site, day: str) -> str:
    """The week a day is in, as a link to its page; nothing where the page has none (a static site)."""
    week = week_paper.week_of(day)
    return site.link(escape(f"the week {week}"), week_path(week)) if site.href(week_path(week)) else ""
