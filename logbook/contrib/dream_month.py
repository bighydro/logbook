"""The dream of a month (`logbook dream month [YYYY-MM|DAY]`, and `dream --catch-up` the first mornings
of the next): a model reads one calendar month, once its last day is over, and writes one `draft/v1`
line about it (RFC 0036, unit `month`, the amendment of 2026-10-21): the month told back in a short
paragraph, where it went, the goals with what the month shows for each, one proposal for next month,
never more, and one question for the owner, never more. Every sentence points at the lines it came
from. A proposal, as every draft: the owner reviews a goal (`goal review`) and signs a day; the month
only says back what they signed. The prompt says it plainly: never moralise.

It runs on the dream's engine (`logbook.contrib.dream`) under the same `dream` entry of
`policy/crossing.json` and the same endpoint, and it is held to the same rules as the week
(`logbook.contrib.dream_week`): the month is read through the entry's ceiling (a gated reading,
`reading.read(..., tiers)`), so no line above it is read, named or counted; every sentence cites lines
of the month or is marked unsupported, and more than 30 % unsupported refuses the answer; the draft's
tier is the highest tier among the lines it read, and it records the version of the entry it was
dreamed under.

**Told from the signed days.** The month's paragraph is told from the days the owner signed (a
standing `signed-day/v1` line, RFC 0034), and from nothing else of the record's words: each signed
day's standing draft the entry allows (`drafts.through`), its supported sentences only, given as a
model's words (`drafted`) with the references of the lines they rest on, and the owner's own words
on the day, the reflection notes (`note/v1` labelled `reflection`) and the note they signed it with
(`wrote`). A raw line's text the day drafts did not use is never given. A day not signed is not told:
the month says how many there were (`month.signed` of `month.days`), and a month with no signed day
under the ceiling has nothing to tell and is not sent (`NothingSigned`).

**The numbers are the code's** (`extra.numbers`): the places with their hours and days (`dream.
days_of`, as the week counts them), the nights by class (`home`, `away`, `aboard` and `in_transit`,
as the year's poster classes them: a night with no stay is in transit, a night aboard an asset is
aboard before it is away, a stay in a home region is home; a night with no stay on a day the record
holds no line of is `unknown`, and the month's nights are `no data` when it has no stay at all), and
the canonical people in the order of the time spent together (the days the with module puts them at
the owner's stays, then their contacts, as the week counts them), **names only: no count is
given beside a person** and none is kept; a segment that writes a figure in a sentence naming a
canonical person is marked unsupported (`BESIDE_A_NAME`), as one that writes a figure no item it
cites gives is (`dream.hold_numbers`).

**The goals** open on the month's last day, or reviewed in it, each with what the month shows for it,
computed and never the model's (`extra.numbers.goals`): the owner's reviews dated in the month (`review/
v1`, its `at` the date the verdict is about), its standing disposition on the last day, and the days a
line of the month touched it, as dates and never a count, since a goal's words may name a person: a
contact with a canonical person, or a stay at a named place, that the goal's own words name (its full
name, or a person's first name, whole words). That is the narrow form of RFC 0043 §4.1's *touched*
this module builds and nothing more.

**Once, and again only when it changed.** A month is dreamed once it is over: `dream month` refuses a
month whose last day is today or later (`NotOver`), and with no month named dreams the last one over.
`--catch-up` looks at each month whose last day is among the days it looks at (`months_to_catch_up`),
after the days: the first 06:00 close of a month dreams the month before; the runs after it leave it
alone while it is unchanged, until its last day leaves the window. The re-dream rule is the day's and
the week's (`dream.why_again`): the count of the month's lines and the digest of every id it read.

**The line.** `unit` `month`; `subject` `2026-06`; `extra.parts`; `extra.numbers` (`month`, `places`,
`nights`, `people`, `goals`, each figure with its line ids); `extra.dropped` (a second proposal or a
second question) and `extra.marked`. `read_count` is the month's lines under the ceiling and the
signatures of its days (RFC 0036 rule 5); the day drafts and the goals and reviews dated before the
month count toward the tier and the digest, and how many under `extra.read_beside`. Nothing of the
promises reader, the people who moved or the stale question is read: each walks more of the record
than a month (the week's own docstring)."""

from __future__ import annotations

import calendar
import json
import re
from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from string import Template
from typing import Any

from ..core import drafts, goals, notes, people, policy, reading, signing, stays
from ..core.chain import Line
from ..core.day import WEEKDAYS
from ..core.export import day_range, parse_day
from ..core.flights import Airports
from ..core.store import HeadMoved, Logbook, retractions
from . import dream, dream_week
from .dream import DreamError, Material, Outcome
from .model_client import Transport

PROMPT_FILE = Path(__file__).with_name("dream-month-prompt.md")
PROMPT_NAME = "dream-month/1"  # kept under `extra.prompt`, so a draft says which prompt wrote it
UNIT = drafts.UNIT_MONTH
REFS = dream_week.REFS  # the references an item carries, at most
SHOWN = dream_week.SHOWN  # the places and people given, at most
TOLD = 6  # the sentences of one day's draft given, at most
NEXT_MONTH = 1  # the proposals for next month a draft keeps: one
QUESTIONS = 1  # and the questions: one
NO_DATA = "no data"
HOME, AWAY, ABOARD, IN_TRANSIT, UNKNOWN = "home", "away", "aboard", "in_transit", "unknown"
NIGHT_CLASSES = (HOME, AWAY, ABOARD, IN_TRANSIT, UNKNOWN)
MORE_THAN_ONE = "more than one proposal for next month"
MORE_QUESTIONS = "more than one question"
BESIDE_A_NAME = dream.BESIDE_A_NAME  # the key of `extra.marked` for a figure beside a name
REFLECTION, SIGNED = "reflection", "signed"  # what the owner wrote on a signed day, by where


class NotOver(DreamError):
    """The month's last day is today or later: a month is dreamed once it is over."""


class NothingSigned(DreamError):
    """No day of the month is signed under the ceiling: the month is told from its signed days."""


@dataclass
class Read:
    """What the dream read of a month: the material, the goals by their reference, and the ids of the
    lines it read beside the month's own."""

    made: Material
    month: str
    first: str
    last: str
    goals: dict[str, Line] = field(default_factory=dict)  # `G1` -> the standing goal line
    beside: int = 0  # the lines it read beside the month's own: `extra.read_beside`
    numbers: dict[str, Any] = field(default_factory=dict)  # `extra.numbers`: the figures with line ids
    signed: int = 0  # the signed days told


# -- the month --------------------------------------------------------------------------------------------


def bounds(month: str) -> tuple[str, str]:
    """The first and the last local day of `YYYY-MM`; `ValueError` for text that is not a month."""
    if not drafts.ISO_MONTH.match(month):
        raise ValueError(f"not a month (YYYY-MM): {month!r}")
    year, number = int(month[:4]), int(month[5:])
    return f"{month}-01", f"{month}-{calendar.monthrange(year, number)[1]:02d}"


def which(text: str | None, today: date) -> tuple[str, str, str]:
    """The month `text` names, as (`YYYY-MM`, its first day, its last day): a month, any day of one
    (`yesterday` too), or, with no text, the last month that is over. `ValueError` for text that is
    neither; `NotOver` for a month whose last day is today or later."""
    if text is None:
        month = (today.replace(day=1) - timedelta(days=1)).isoformat()[:7]
    elif drafts.ISO_MONTH.match(text):
        month = text
    else:
        try:
            day = (today - timedelta(days=1)) if text == "yesterday" else parse_day(text)
        except ValueError as e:
            raise ValueError(f"not a day or a month (YYYY-MM-DD or YYYY-MM): {text!r}") from e
        month = day.isoformat()[:7]
    first, last = bounds(month)
    if last >= today.isoformat():
        raise NotOver(f"{month} runs to {last}, which is not over; a month is dreamed once its last day is")
    return month, first, last


def standing_of(lb: Logbook, month: str) -> Line | None:
    """The month's standing draft, whatever the entry allows (rule 2): the one a new draft supersedes."""
    with lb.index() as idx:
        found = drafts.by_unit(idx.by_kind(drafts.KIND), retractions(idx.retractions()), UNIT)
    return drafts.standing(found.get(month, []))


def owner_of(lb: Logbook) -> str | None:
    """The `subject` a signature of the owner names: the record's `owner_id`; None reads any."""
    return str(lb.meta.get("owner_id") or "") or None


# -- the material -----------------------------------------------------------------------------------------


def material(
    lb: Logbook, month: str, first: str, last: str, found: policy.Ceiling, airports: Airports | None = None
) -> Read:
    """The month's material under the entry's ceiling (the module's docstring). `NothingSigned` is
    not raised here: a caller decides (`run` refuses, `catch_up` counts the month empty)."""
    tiers = dream.tiers_of(found)
    airports = airports or Airports.load()
    rd = reading.read(lb, first, last, airports, tiers, names_at=tiers)
    on = dream.lines_of_days(rd, first, last)
    days = day_range(first, last)
    with lb.index() as idx:
        retracted = frozenset(retractions(idx.retractions()))
        known = dream.names_for(lb, found, idx)
        identities = known.identities
        allowed = drafts.allowed(lb.root)
        every_draft = idx.by_kind(drafts.KIND)
        signatures = {
            day: line
            for day, line in signing.signatures(idx.by_kind(signing.KIND), retracted, owner_of(lb)).items()
            if first <= day <= last and reading.crossing([line], tiers)
        }
        day_drafts = {
            day: drafts.standing(
                drafts.through(drafts.of_day(every_draft, retracted, day), tiers, allowed)[0]
            )
            for day in signatures
        }
        goal_lines = [
            g for g in reading.crossing(idx.by_kind(goals.KIND), tiers) if str(g["id"]) not in retracted
        ]
        review_lines = goals.review_lines(reading.crossing(idx.by_kind(goals.REVIEW), tiers), retracted)
    ids = {str(line["id"]) for line in on} | {str(line["id"]) for line in signatures.values()}
    by_day: dict[str, list[Line]] = {}
    for line in on:
        by_day.setdefault(rd.day_of(line), []).append(line)
    made = Material(
        day=month,
        unit=UNIT,
        tier=1,
        read_count=0,
        read_head=str(lb.meta["head"]),
        read_ids_sha256="",
        language=dream.DEFAULT_LANGUAGE,
        data={},
        ids=ids,
        zone=rd.tz,
        canonical=known.canonical(lb),
        identities=identities,
        withheld=known.withheld,
    )
    read = Read(made, month, first, last, signed=len(signatures))
    beside: dict[str, int] = {}  # what it read beside the month's lines: id -> tier

    told_days = []
    texts: list[str] = []
    for day in sorted(signatures):
        draft = day_drafts[day]
        if draft is not None:
            beside[str(draft["id"])] = int(draft.get("tier") or 1)
        told = _told(draft, ids, made)
        wrote = _wrote(day, signatures[day], by_day.get(day, []), retracted, made)
        texts += [t["drafted"] for t in told] + [w["text"] for w in wrote]
        told_days.append(
            {
                "day": day,
                "weekday": WEEKDAYS[date.fromisoformat(day).weekday()],
                "drafted": told,
                "wrote": wrote,
            }
        )
    made.language = dream.language_of(texts or dream._texts(on))

    _by_day, places = dream.days_of(rd, days, made)
    nights = _nights(rd, days, set(by_day), made)
    report = people.read(lb, first, last, airports)
    persons = _in_order(dream_week._persons(report, ids, made))
    day_of_id = {str(line["id"]): rd.day_of(line) for line in on}
    shown_goals, goal_read, goal_numbers = _goals(goal_lines, review_lines, report, rd, day_of_id, read)
    beside.update(
        {str(line["id"]): int(line.get("tier") or 2) for line in goal_read if str(line["id"]) not in ids}
    )
    numbers_month = {
        "days": len(days),
        "signed": len(signatures),
        "ref": made.refs_of(str(signatures[d]["id"]) for d in sorted(signatures))[:REFS],
    }
    read.numbers = {
        "month": dream_week._lined(numbers_month, made),
        "places": [dream_week._lined(p, made) for p in places[:SHOWN]],
        "nights": NO_DATA if nights is None else [dream_week._lined(n, made) for n in nights],
        "people": [dream_week._lined(p, made) for p in persons[:SHOWN]],  # names and lines, no count
        "goals": goal_numbers,
    }
    made.data = {
        "month": {"month": month, "first": first, "last": last, **numbers_month},
        "max_tier": found.max_tier,
        "days": told_days,
        "where": {
            "places": places[:SHOWN],
            "nights": NO_DATA if nights is None else nights,
            "people": [{"name": p["name"], "ref": p["ref"]} for p in persons[:SHOWN]],
        },
        "goals": shown_goals,
    }
    made.tier = max([int(line.get("tier", 1)) for line in on] + list(beside.values()), default=1)
    made.tier = max([made.tier] + [int(line.get("tier") or 1) for line in signatures.values()])
    made.tier = max(made.tier, known.tier_in([made.data, read.numbers]))  # a name read is read
    made.read_count = len(ids)
    made.read_ids_sha256 = dream.digest(ids | set(beside))
    read.beside = len(set(beside) - ids)
    return read


def _told(line: Line | None, ids: set[str], made: Material) -> list[dict[str, Any]]:
    """A signed day as its standing draft told it: its supported sentences resting on lines of the
    month, a model's words (`drafted`), `TOLD` at most, each with its part and its references; a
    sentence that writes a figure beside a person (`dream.beside_a_name`) is left out, so the material
    never carries one, whatever a day's draft said."""
    if line is None:
        return []
    payload = line.get("payload") or {}
    extra = payload.get("extra")
    parts = extra.get("parts") if isinstance(extra, dict) else None
    segments = payload.get("segments") or []
    told: list[dict[str, Any]] = []
    for i, segment in enumerate(segments):
        shown = drafts.segment_json(segment, ids, drafts.NOT_ON_MONTH)
        if not shown["supported"] or len(told) >= TOLD or dream.beside_a_name(shown["text"], made):
            continue  # a day's sentence with a figure beside a person is never passed on
        if made.withholds(shown["text"]):
            continue  # nor one naming someone the entry's tiers do not name
        ref = made.refs_of(shown["evidence"])
        if ref:
            part = parts[i] if isinstance(parts, list) and len(parts) == len(segments) else None
            told.append({"part": part, "drafted": shown["text"], "ref": ref})
    return told


def _wrote(
    day: str, signature: Line, lines: Sequence[Line], retracted: frozenset[str], made: Material
) -> list[dict[str, Any]]:
    """The owner's own words on a signed day: its reflection notes under the ceiling, then the note
    they signed it with, each with its line's reference."""
    out: list[dict[str, Any]] = []
    for note in notes.standing(lines, notes.REFLECTION, retracted):
        text = dream._clip(str((note.get("payload") or {}).get("text") or ""), dream.NOTE_CHARS)
        if text:
            out.append({"kind": REFLECTION, "text": text, "ref": made.refs_of([str(note["id"])])})
    said = (signature.get("payload") or {}).get("note")
    if isinstance(said, str) and said.strip():
        out.append({"kind": SIGNED, "text": said.strip(), "ref": made.refs_of([str(signature["id"])])})
    return out


def class_of(night: stays.Night) -> str:
    """Which of the four a night is, as the year's poster classes it: in transit with no stay, aboard
    before away, home by the home region, else away."""
    if night.stay is None:
        return IN_TRANSIT
    if night.aboard:
        return ABOARD
    return HOME if night.home else AWAY


def _nights(
    rd: reading.Reading, days: Sequence[str], lined: Collection[str], made: Material
) -> list[dict[str, Any]] | None:
    """The month's nights by class (`class_of`), each with its count and the references of the stays
    it was spent at; a night with no stay on a day the reading holds no line of (`lined`) is
    `unknown`, not in transit: the record says nothing of it. None when the month holds no stay at all
    (`no data`)."""
    wanted = set(days)
    nights = [n for n in rd.nights if n.day in wanted]
    if not any(n.stay is not None for n in nights):
        return None
    counted: dict[str, list[str]] = {c: [] for c in NIGHT_CLASSES}
    count: Counter[str] = Counter()
    for night in nights:
        found = class_of(night) if night.stay is not None or night.day in lined else UNKNOWN
        count[found] += 1
        if night.stay is not None:
            refs = made.refs_of([night.stay.first_line, night.stay.last_line])
            counted[found] += [r for r in refs if r not in counted[found]]
    return [{"class": c, "nights": count[c], "ref": counted[c][:REFS]} for c in NIGHT_CLASSES if count[c]]


def _in_order(persons: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The people in the order of the time spent together: the days together first, then the
    contacts, then the name; the counts stay here and never reach the material or the line."""
    ranked = sorted(persons, key=lambda p: (-p.get("days_together", 0), -p["contacts"], p["name"]))
    return [{"name": p["name"], "id": p["id"], "ref": p["ref"]} for p in ranked]


def _goals(
    goal_lines: Sequence[Line],
    review_lines: Sequence[Line],
    report: people.Report,
    rd: reading.Reading,
    day_of_id: Mapping[str, str],
    read: Read,
) -> tuple[list[dict[str, Any]], list[Line], list[dict[str, Any]]]:
    """The goals open on the month's last day or reviewed in it, as the lines up to that day left
    them, each with a reference of its own (`G1`, ...) and what the month shows for it, computed:
    the reviews dated in the month, the standing disposition on the last day, and the days a line of
    the month touched it (`_touches`). And the goal and review lines given, which it read, and what
    each goal shows as `extra.numbers.goals` keeps it, with line ids."""
    first, last, made = read.first, read.last, read.made
    day_of = rd.day_start.day_of
    until_last = [r for r in review_lines if day_of(str(r["at"])) <= last]
    found = goals.Goals([g for g in goal_lines if day_of(str(g["at"])) <= last])
    shown: list[dict[str, Any]] = []
    given: list[Line] = []
    kept: list[dict[str, Any]] = []
    for line in found.standing():
        payload = line.get("payload") or {}
        if str(payload.get("from") or "") > last:
            continue
        chain = found.chain(str(line["id"]))
        review = goals.standing_review(until_last, chain)
        in_month = [
            r for r in until_last if str(r["payload"]["goal"]) in chain and first <= day_of(str(r["at"]))
        ]
        if goals.state(line, review, last) != "open" and not in_month:
            continue
        given += [line, *in_month] + ([review] if review is not None and review not in in_month else [])
        ref = f"G{len(read.goals) + 1}"
        read.goals[ref] = line
        text = str(payload.get("text") or "")
        touched = _touches(text, report, rd, day_of_id)
        reviews = [
            {
                "day": day_of(str(r["at"])),
                "disposition": (r.get("payload") or {}).get("disposition"),
                "ref": made.refs_of([str(r["id"])]),
            }
            for r in in_month
        ]
        item: dict[str, Any] = {
            "goal": ref,
            "text": text,
            "horizon": payload.get("horizon"),
            "standing": None if review is None else (review.get("payload") or {}).get("disposition"),
            "reviews": reviews,
            "touched": {
                "days": sorted(touched),  # the days, never a count: a goal's words may name a person
                "ref": made.refs_of(i for d in sorted(touched) for i in touched[d])[:REFS],
            },
        }
        shown.append(item)
        kept.append(
            {
                "goal": str(line["id"]),
                "text": text,
                "standing": item["standing"],
                "reviews": [
                    {"day": r["day"], "disposition": r["disposition"], "line": str(x["id"])}
                    for r, x in zip(reviews, in_month, strict=True)
                ],
                "touched": sorted(touched),
                "lines": sorted({i for d in touched for i in touched[d]}),
            }
        )
    return shown, given, kept


def _touches(
    text: str, report: people.Report, rd: reading.Reading, day_of_id: Mapping[str, str]
) -> dict[str, list[str]]:
    """The days a line of the month touched a goal, day -> the line ids: a contact with a canonical
    person the goal's words name (the full name, or the first name, whole words, as written), or a
    stay at a named place they name (its name, whole words, any case). Only the month's lines under
    the ceiling (`day_of_id`, id -> local day)."""
    out: dict[str, list[str]] = {}
    for p in report.known.values():
        name = p.name.strip()
        first_name = name.split()[0] if name.split() else ""
        if not name or not (_names(text, name) or (len(first_name) >= 3 and _names(text, first_name))):
            continue
        for channel in dream_week.CONTACT_CHANNELS:
            found = p.channels.get(channel)
            for line_id in found.ids if found is not None else []:
                if line_id in day_of_id:
                    out.setdefault(day_of_id[line_id], []).append(line_id)
    for place in rd.places:
        if not place.name or not _names(text.casefold(), place.name.casefold()):
            continue
        for stay in rd.owner_stays:
            if stay.place != place.name:
                continue
            for end in (stay.first_line, stay.last_line):
                if end and end in day_of_id:
                    out.setdefault(day_of_id[end], []).append(end)
    return {day: list(dict.fromkeys(found)) for day, found in out.items()}


def _names(text: str, name: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text) is not None


# -- the prompt and the answer ------------------------------------------------------------------------------


def prompt(read: Read) -> list[dict[str, str]]:
    """The two messages the model gets: the month's prompt with its days and language filled in, and
    the material as JSON."""
    made = read.made
    system = Template(PROMPT_FILE.read_text(encoding="utf-8")).safe_substitute(
        month=read.month,
        first=read.first,
        last=read.last,
        tz=str(made.zone),
        language=made.language,
        language_name=dream.LANGUAGE_NAMES.get(made.language, made.language),
    )
    user = json.dumps(made.data, ensure_ascii=False, indent=1)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def shape(found: Mapping[str, Any], read: Read) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The answer as a draft has it: every part's segments in order (`dream.segments_of`, strictly),
    one proposal for next month and one question at most, the number rule held (`dream.hold_numbers`)
    and no figure beside a person (`dream.hold_names`), and the evidence rule's share checked again; and
    what `extra` keeps of it: `parts`, `numbers`, `dropped`, `marked`."""
    made = read.made
    segments, parts = dream.segments_of(found, made, drafts.MONTH_PARTS, strict=True)
    dropped = keep_one(
        segments, parts, {"next_month": (NEXT_MONTH, MORE_THAN_ONE), "question": (QUESTIONS, MORE_QUESTIONS)}
    )
    marked: dict[str, int] = {}
    unbacked = dream.hold_numbers(segments, made.data, made)
    if unbacked:
        marked[dream.UNBACKED] = unbacked
    beside = dream.hold_names(segments, made)
    if beside:
        marked[BESIDE_A_NAME] = beside
    dream.share_of(segments, made.unit)
    extra: dict[str, Any] = {"parts": parts, "numbers": read.numbers}
    if dropped:
        extra["dropped"] = dropped
    if marked:
        extra["marked"] = marked
    return segments, extra


def keep_one(
    segments: list[dict[str, Any]], parts: list[str], limits: Mapping[str, tuple[int, str]]
) -> dict[str, int]:
    """In place: the segments of each part of `limits` past its count dropped, the later ones; how many
    were dropped, by the reason `limits` names."""
    dropped: Counter[str] = Counter()
    for part, (most, why) in limits.items():
        found = [i for i, p in enumerate(parts) if p == part]
        for i in reversed(found[most:]):
            del segments[i], parts[i]
            dropped[why] += 1
    return dict(dropped)


# -- the dream --------------------------------------------------------------------------------------------


def run(
    lb: Logbook,
    text: str | None = None,
    env: Mapping[str, str] | None = None,
    airports: Airports | None = None,
    dry_run: bool = False,
    transport: Transport | None = None,
    say: Callable[[str], None] | None = None,
    today: date | None = None,
    read: Read | None = None,
) -> dream.Dream:
    """Dream the month `text` names (`which`; the last one over when None): the policy, the endpoint,
    the material (`read` when the caller built it under the lock already), the model's turn, the
    checks, and one `draft/v1` line appended under the writer lock unless `dry_run`. `DreamError`
    says why nothing was written (`NotOver`, `NothingSigned`, the answer); `HeadMoved` when the record
    moved under the reading."""
    found = dream.ceiling(lb)
    ep = dream.endpoint(found, env)
    month, first, last = which(text, today or dream.today())
    with lb.writer():
        read = read or material(lb, month, first, last, found, airports)
        made = read.made
        if not made.ids:
            raise DreamError(f"{month} has no line under max_tier {found.max_tier}; nothing to dream")
        if not read.signed:
            raise NothingSigned(
                f"{month} has no signed day under max_tier {found.max_tier}; a month is told from the days"
                " you signed (`day sign`), so there is nothing to tell"
            )
        latest = standing_of(lb, month)
        source = drafts.SOURCE_PREFIX + ep.model
        version = policy.version(found)
        if not dry_run:
            dream.refuse_same(latest, source, made, version)
        messages = prompt(read)
        if say is not None:
            say(messages[0]["content"])
            say(messages[1]["content"])
        answer, found_answer = dream.ask(ep, messages, transport)
        segments, kept = shape(found_answer, read)
        payload: dict[str, Any] = {
            "schema": drafts.SCHEMA,
            "unit": UNIT,
            "subject": month,
            "read_head": made.read_head,
            "read_count": made.read_count,
            "language": made.language,
            "segments": segments,
            "extra": {
                "prompt": PROMPT_NAME,
                **kept,
                "read_ids_sha256": made.read_ids_sha256,
                "read_beside": read.beside,
                "policy_version": version,
            },
        }
        if latest is not None:
            payload["supersedes"] = str(latest["id"])
        dream.valid(payload)
        if dry_run:
            return dream.Dream(month, None, payload, made.tier, messages, answer)
        line = dream.append(lb, made, source, payload)
    return dream.Dream(month, line, payload, made.tier, messages, answer)


# -- catch-up ---------------------------------------------------------------------------------------------


def changed_since(
    lb: Logbook, month: str, first: str, last: str, found: policy.Ceiling, airports: Airports | None = None
) -> tuple[bool, str, Read]:
    """Whether a month that is over needs dreaming, by the week's rule (`dream.why_again`): no draft
    yet, a standing draft the entry no longer stands behind, or what it would read today is not what
    the standing draft read. The material is returned so a caller that dreams does not read twice."""
    read = material(lb, month, first, last, found, airports)
    latest = standing_of(lb, month)
    if latest is None:
        return True, "its last day is over, no draft yet", read
    why = dream.why_again(latest, found, read.made.read_count, read.made.read_ids_sha256)
    if why is not None:
        return True, why, read
    return False, f"unchanged since #{latest['seq']}", read


def months_to_catch_up(today: date, days: int) -> list[tuple[str, str, str]]:
    """The months whose last day is among the last `days` days before today, oldest first: the first
    close of a month looks at the month before, and the closes after it while its last day is in the
    window (the window of 14 days never holds a whole month, so the week's rule, every day in it,
    would never hold one)."""
    window = dream.days_to_catch_up(today, days)
    out = []
    for day in window:
        month = day[:7]
        first, last = bounds(month)
        if day == last:
            out.append((month, first, last))
    return out


def catch_up_one(
    lb: Logbook,
    month: str,
    first: str,
    last: str,
    found: policy.Ceiling,
    today: date,
    env: Mapping[str, str] | None = None,
    transport: Transport | None = None,
    airports: Airports | None = None,
) -> Outcome:
    """One month's row of a catch-up, under the caller's hold of the writer lock: `empty` for a month
    with no line or no signed day under the ceiling, `unchanged`, `dreamed` or `refused` and why."""
    try:
        needed, why, read = changed_since(lb, month, first, last, found, airports)
        if not read.made.ids:
            return Outcome(month, "empty", "nothing logged")
        if not read.signed:
            return Outcome(month, "empty", "no signed day")
        if not needed:
            return Outcome(month, "unchanged", why)
        dreamed = run(lb, month, env, airports, transport=transport, today=today, read=read)
        return Outcome(month, "dreamed", dream.detail_of(dreamed, why))
    except (DreamError, HeadMoved, ValueError, stays.SettingsError) as e:
        return Outcome(month, "refused", str(e))


# -- the reader -------------------------------------------------------------------------------------------


def for_month(lb: Logbook, month: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """The month's standing draft and its withheld row, as `dream month --json` prints them and a
    page will read them: by the Journeys' rule (`drafts.for_unit`: the `dream` entry today, the
    evidence checked against the month's lines and the signatures of its days)."""
    first, last = bounds(month)
    with lb.index() as idx:
        retracted = frozenset(retractions(idx.retractions()))
        found = drafts.by_unit(idx.by_kind(drafts.KIND), retracted, UNIT).get(month, [])
        if not found:
            return None, None
        on_month = {
            str(line["id"])
            for d in day_range(first, last)
            for line in idx.day(d)
            if str(line["id"]) not in retracted
        }
        on_month |= {
            str(line["id"])
            for day, line in signing.signatures(idx.by_kind(signing.KIND), retracted, owner_of(lb)).items()
            if first <= day <= last
        }
        people = drafts.people_of(idx)
    draft, withheld = drafts.for_unit(
        found, on_month, None, drafts.allowed(lb.root), drafts.NOT_ON_MONTH, people=people
    )
    return draft, withheld


def rows(payload: Mapping[str, Any], indent: str = "  ") -> list[str]:
    """What the month's line keeps beside its segments, in text: the days signed, the hours by place,
    the nights by class, the people in order (names only, never a count), what each goal shows, and
    what was dropped or marked."""
    found = payload.get("extra")
    extra: Mapping[str, Any] = found if isinstance(found, dict) else {}
    found = extra.get("numbers")
    numbers: Mapping[str, Any] = found if isinstance(found, dict) else {}
    out: list[str] = []
    told = numbers.get("month")
    if isinstance(told, dict):
        out.append(f"{indent}  {'signed':<9} {told.get('signed')} of {told.get('days')} days")
    places = numbers.get("places") or []
    if places:
        out.append(
            f"{indent}  {'hours':<9} " + drafts.DOT.join(f"{p['place']} {p['hours']} h" for p in places)
        )
    nights = numbers.get("nights")
    if isinstance(nights, list) and nights:
        out.append(
            f"{indent}  {'nights':<9} "
            + drafts.DOT.join(f"{n['class'].replace('_', ' ')} {n['nights']}" for n in nights)
        )
    elif nights == NO_DATA:
        out.append(f"{indent}  {'nights':<9} {NO_DATA}")
    persons = numbers.get("people") or []
    if persons:
        out.append(f"{indent}  {'with':<9} " + drafts.DOT.join(str(p["name"]) for p in persons))
    for goal in numbers.get("goals") or []:
        said = [f"touched on {', '.join(goal['touched'])}"] if goal.get("touched") else ["not touched"]
        said += [f"reviewed {r['disposition']} on {r['day']}" for r in goal.get("reviews") or []]
        out.append(f"{indent}  {'goal':<9} “{goal['text']}”{drafts.DOT}" + drafts.DOT.join(said))
    for key in ("dropped", "marked"):
        counted = extra.get(key)
        if isinstance(counted, dict) and counted:
            k = sum(int(n) for n in counted.values())
            why = ", ".join(f"{reason} {n}" for reason, n in counted.items())
            out.append(f"{indent}  {k} {'dropped' if key == 'dropped' else 'marked unsupported'}: {why}")
    return out
