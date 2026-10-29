"""The dream's proposed events, confirmed into the record: `day sign DAY --accept N` and `day reflect
DAY --sign --accept N`.

The dream proposes, inside its `draft/v1` line, the events it thinks the day held (`drafts.PROPOSALS`,
kind `event`: a stay at a restaurant with two photos and a recording is a dinner with the people in
it). Nothing reads a proposal as a fact. `listed` numbers the standing draft's proposals as the
owner's command prints them, from 1 under `day sign` and after the reflection's own proposals under
`day reflect`; only the owner's `--accept` writes one, and then as one `event/v1` line (RFC 0009),
the profile every calendar adapter writes, made by the calendar adapter's own mapping
(`ics.components_lines`, as `gcal` maps the Calendar API) from the VEVENT a calendar named `logbook`
would hold for the proposal's fields (`event_line`): UID `<draft id>/<number>`, DTSTART and DTEND in
the record's zone, SUMMARY the title, LOCATION a named place's name and GEO its coordinates (an
observed place, `place:<lat>,<lon>`, gives GEO alone), one ATTENDEE per person, their label as CN,
accepted, by their email address, each one the record names at tier 1, the event's: a person known only
by tier-2 or tier-3 lines is left out, and a name of theirs in the title reads `someone`. The line is
what the calendar adapter writes for those fields, byte for byte, but for two things: `source` is
`owner` (the owner confirmed it; the model only proposed it) and `extra.from` names the draft. A
person the record knows by no email address is an attendee by the ref it does know, in the shape the
adapter gives an address. The tier is the profile's, 1, as
every calendar entry's: a tier says where a line may travel, never who wrote it.

The proposals are the draft's the Day shows (`listed`, through `drafts.for_day` under the `dream` entry
today, `drafts.allowed`): derived material follows the policy, not the head, so a draft the entry no
longer allows is withheld with its proposals, which are neither listed nor accepted (`held_back` says
why), and the standing draft among the ones the entry allows stands in, with its own. An event the
owner confirmed before the entry changed stays in the record: it is the owner's line, not the model's.

The event lines and the signature are written under one hold of the writer lock, the proposals read
again inside it (`again`): one confirmed meanwhile, one whose evidence left the page, or a day dreamed
again or its draft withheld in between is refused, and nothing is written. Every number and every
flag of the signature is checked before the first line is (`check_signature`). Sending a confirmed
event to an external calendar would be a crossing, and nothing here sends anything."""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from ..core import drafts, places, reading, resolve, signing
from ..core.chain import Line
from ..core.figures import LETTER_AFTER, LETTER_BEFORE
from ..core.store import Logbook, retractions

if TYPE_CHECKING:
    from .adapters import ics

OWNER = drafts.OWNER  # the source of a confirmed event: the owner, not the model and not an adapter
CALENDAR = "logbook"  # the calendar a confirmed event lives in: the record's own (X-WR-CALNAME)
PARTSTAT_ACCEPTED = "ACCEPTED"  # the owner says they were there
TIER = 1  # an event line's, the profile's: the tier its names must be learned at
SOMEONE = "someone"  # a person the title names whom no line at the event's tier names


class EventError(ValueError):
    """A proposed event the command refuses to write, in one sentence; nothing is written."""


@dataclass(frozen=True)
class Proposed:
    """One proposed event as the command prints it: its `number` there; the proposal as the Day
    shows it (`drafts.proposals_json`, whose own `number` is its place in the draft); the draft's
    line id, seq and source."""

    number: int
    item: dict[str, Any]
    draft: str
    seq: int
    source: str

    @property
    def pending(self) -> bool:
        """Not confirmed yet, and every line it rests on still on the page."""
        return self.item["confirmed"] is None and bool(self.item["supported"])


def listed(lb: Logbook, day: str, first: int = 1) -> list[Proposed]:
    """The proposed events of the draft the Day shows for `day`, numbered from `first` in the draft's
    order: the standing draft among the ones the `dream` entry allows today (`drafts.for_day` under
    `drafts.allowed`). None when the day has no draft, when its draft proposes none, or when the entry
    withholds every draft of the day: a withheld draft's proposals are withheld with it. Every tier
    the entry allows: the owner reads their own record."""
    with lb.index() as idx:
        draft, _withheld = drafts.for_day(idx, day, allowed=drafts.allowed(lb.root))
    if draft is None:
        return []
    return [
        Proposed(first + i, item, str(draft["line"]), int(draft["seq"]), str(draft["source"]))
        for i, item in enumerate(draft["proposals"])
    ]


def held_back(lb: Logbook, day: str) -> str | None:
    """`superseded by policy: ...` when the `dream` entry withholds the standing draft of `day`, and
    its proposals with it (the Day's `draft_withheld` row, in words); None otherwise."""
    with lb.index() as idx:
        _draft, row = drafts.for_day(idx, day, allowed=drafts.allowed(lb.root))
    return None if row is None else drafts.withheld_text(row)


def chosen(
    found: Sequence[Proposed], wanted: Sequence[int], day: str, held: str | None = None
) -> list[Proposed]:
    """The proposed events these numbers name, in their order; refused when a number names none (and
    why, `held`, when the policy withholds the standing draft), when one is confirmed already, or
    when one rests on a line no longer on the page."""
    by_number = {p.number: p for p in found}
    missing = [str(n) for n in wanted if n not in by_number]
    if missing:
        have = f"proposed {len(found)} for {day}, numbered above" if found else f"proposed none for {day}"
        if held is not None:
            have += f" that the Day shows: its standing draft is withheld with its proposed events, {held}"
        raise EventError(f"no proposed event {', '.join(missing)}; the dream {have}")
    taken = [by_number[n] for n in sorted(set(wanted))]
    for p in taken:
        confirmed = p.item["confirmed"]
        if confirmed is not None:
            raise EventError(
                f"proposed event {p.number} is confirmed already as #{confirmed['seq']}; nothing was written"
            )
        if not p.item["supported"]:
            raise EventError(
                f"proposed event {p.number} rests on a line that is no longer on the page of {day};"
                " nothing was written"
            )
    return taken


def again(lb: Logbook, day: str, taken: Sequence[Proposed], first: int = 1) -> list[Proposed]:
    """`taken` read again, under the writer lock, just before writing: the same draft still the one
    the Day shows (not dreamed again, not withheld by the policy since), and each proposal still
    pending (`chosen`)."""
    if not taken:
        return []
    fresh = listed(lb, day, first)
    if not fresh or fresh[0].draft != taken[0].draft:
        raise EventError(
            f"{day} was dreamed again, or the policy withheld its draft, while its proposals were read;"
            " nothing was written"
        )
    return chosen(fresh, [p.number for p in taken], day)


def rows(found: Sequence[Proposed]) -> Iterator[str]:
    """The proposed events, numbered, under the line that says whose they are; nothing when none."""
    if not found:
        return
    head = found[0]
    yield f"proposed events, from the dream #{head.seq} ({head.source}); each is a guess until you accept it:"
    for p in found:
        confirmed = p.item["confirmed"]
        if confirmed is not None:
            state = f"{drafts.DOT}confirmed as #{confirmed['seq']}"
        elif not p.item["supported"]:
            state = f"{drafts.DOT}{drafts.UNSUPPORTED}: {p.item['why']}"
        else:
            state = ""
        # the number after the words, never before them: a title may open with a name (the owner)
        yield f"  {drafts.proposal_text(p.item)} ({drafts.EVENT} {p.number}){state}"


def prepared(
    lb: Logbook, day: str, taken: Sequence[Proposed], first: int = 1
) -> list[tuple[Proposed, dict[str, Any]]]:
    """`taken` read again (`again`) and each made into its line (`event_line`), every one of them
    before the first is written, so that a refusal leaves nothing behind. Under the writer lock."""
    return [(p, event_line(lb, p)) for p in again(lb, day, taken, first)]


def write(lb: Logbook, line: dict[str, Any]) -> Line:
    """An event line `event_line` made, appended through `Logbook.append`."""
    return lb.append(
        at=line["at"],
        source=line["source"],
        kind=line["kind"],
        tier=line["tier"],
        payload=line["payload"],
        end=line["end"],
        tz=line["tz"],
    )


def wrote_text(proposal: Proposed, line: Line) -> str:
    """`wrote proposed event 2 as #31 event/v1 (source owner, tier 1)`: what a command says for each
    event it wrote."""
    return (
        f"wrote proposed event {proposal.number} as #{line['seq']} event/v1"
        f" (source {line['source']}, tier {line['tier']})"
    )


def event_line(lb: Logbook, proposal: Proposed) -> dict[str, Any]:
    """The line `--accept` writes for `proposal`: the calendar adapter's for the VEVENT of its fields
    (the module's docstring), source `owner`, `extra.from` the draft. Nothing is written."""
    from .adapters import ics  # here, not at the top: `--help` imports no adapter (tests/test_cli_lazy.py)

    tz = str(lb.meta["timezone"])
    zone = ZoneInfo(tz)
    item = proposal.item
    vevent = ics.Component("VEVENT")
    add = vevent.properties.append
    add(ics.Property("UID", {}, _escape(f"{proposal.draft}/{item['number']}")))
    add(_time("DTSTART", str(item["start"]), zone))
    add(_time("DTEND", str(item["end"]), zone))
    attendees, hidden = _attendees(lb, proposal)
    add(ics.Property("SUMMARY", {}, _escape(_unnamed(str(item["title"]), hidden))))
    place = item.get("place")
    if isinstance(place, str) and place:
        at = drafts.cluster_coordinates(place)
        if at is None:
            add(ics.Property("LOCATION", {}, _escape(place)))
            named = places.by_name(places.read(lb.root)).get(place)
            at = None if named is None else (named.lat, named.lon)
        if at is not None:
            add(ics.Property("GEO", {}, f"{at[0]};{at[1]}"))
    for (kind, value), label in attendees:
        if kind == "email":
            params = {"CN": [label], "PARTSTAT": [PARTSTAT_ACCEPTED]}
            add(ics.Property("ATTENDEE", params, f"{ics.MAILTO}{value}"))
    root = ics.Component("VCALENDAR", [ics.Property("X-WR-CALNAME", {}, CALENDAR)], [vevent])
    (line,) = ics.components_lines([root], CALENDAR, {}, tz)
    line["source"] = OWNER
    payload = line["payload"]
    if any(kind != "email" for (kind, _value), _label in attendees):
        mapped = iter(payload.get("attendees") or [])
        payload["attendees"] = [
            next(mapped) if kind == "email" else _attendee((kind, value), label)
            for (kind, value), label in attendees
        ]
    payload.setdefault("extra", {})["from"] = proposal.draft
    return line


def _attendees(lb: Logbook, proposal: Proposed) -> tuple[list[tuple[resolve.Ref, str]], list[str]]:
    """Each person of the proposal the record names at the event's tier (`TIER`), as (the ref the line
    names them by, their label): their email address, else their phone, else the first ref a tier-1
    resolution gives them. A person known only by lines above it is left out: a tier-1 line never
    carries a name or an address learned from a tier-2 or tier-3 one (the owner's rule). Beside them,
    the words of the names learned only above the tier, which the title must not carry (`_held_words`,
    `_unnamed`). Refused when
    the record no longer resolves a person at all (merged into another since the dream, say)."""
    people = proposal.item.get("people") or []  # none or several: the title is held to the tier either way
    with lb.index() as idx:
        retracted, resolutions = list(idx.retractions()), list(idx.resolutions())
    everyone = resolve.identities_from([*retracted, *resolutions])
    at_tier = resolve.identities_from([*retracted, *reading.crossing(resolutions, range(1, TIER + 1))])
    names, named = drafts.person_names(everyone), drafts.person_names(at_tier)
    out: list[tuple[resolve.Ref, str]] = []
    for person in people:
        entity = str(person["id"])
        if entity not in names or not any(who.entity == entity for who in everyone.values()):
            raise EventError(
                f"proposed event {proposal.number} names {entity}, whom the record no longer resolves to a"
                " person; dream the day again"
            )
        refs = sorted(ref for ref, who in at_tier.items() if who.entity == entity)
        if entity not in named or not refs:
            continue  # known only above the event's tier: left out, never named
        ref = next((r for r in refs if r[0] == "email"), None) or next(
            (r for r in refs if r[0] == "phone"), refs[0]
        )
        out.append((ref, named[entity]))
    shown = {who.label for who in at_tier.values() if who.label}
    hidden = {who.label for who in everyone.values() if who.label and who.label not in shown}
    return out, _held_words(hidden, shown)


def _held_words(hidden: Iterable[str], shown: Iterable[str]) -> list[str]:
    """The words a title must not carry: each name learned only above the event's tier, whole, then
    each of its words of more than three letters no name shown at the tier also has (a first name, a
    surname), the longest first."""
    kept = {w.casefold() for label in shown for w in label.split()}
    found: set[str] = set()
    for label in hidden:
        if label.strip():
            found.add(" ".join(label.split()))
            found |= {w for w in label.split() if len(w) > 3 and w.casefold() not in kept}
    return sorted(found, key=lambda w: (-len(w), w))


def _unnamed(title: str, words: Sequence[str]) -> str:
    """`title` with each of `words` (`_held_words`), no letter stuck to either end (a digit may be,
    `Kari2`), a genitive's `s` with it, as
    `SOMEONE` (`someone's` for a genitive): `Dinner with Kari Nordmann` is `Dinner with someone` and
    `Karis bursdag` is `someone's bursdag` when no tier-1 line names Kari."""
    for said in words:
        title = re.sub(
            rf"{LETTER_BEFORE}{re.escape(said)}(['\u2019]s|s)?{LETTER_AFTER}",
            lambda m: SOMEONE + ("'s" if m.group(1) else ""),
            title,
        )
    return title


def _attendee(ref: resolve.Ref, label: str) -> dict[str, Any]:
    """An attendee by a ref that is not an address, in the shape the adapter gives an address."""
    return {"ref": {"kind": ref[0], "value": ref[1]}, "name": label, "response": "accepted"}


def _time(name: str, stamp: str, zone: ZoneInfo) -> ics.Property:
    """A start or end as a calendar spells it: the wall clock in the record's zone with its TZID; in
    UTC with a `Z` when that wall clock reads back as another instant (the hour the clocks go back)."""
    from .adapters import ics

    when = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(UTC)
    local = when.astimezone(zone)
    wall = datetime(local.year, local.month, local.day, local.hour, local.minute, local.second, tzinfo=zone)
    if wall.astimezone(UTC) == when:
        return ics.Property(name, {"TZID": [zone.key]}, local.strftime("%Y%m%dT%H%M%S"))
    return ics.Property(name, {}, when.strftime("%Y%m%dT%H%M%SZ"))


def _escape(text: str) -> str:
    """A TEXT value escaped as RFC 5545 has it, so the adapter reads back exactly `text`."""
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


# -- the signature beside them ---------------------------------------------------------------------------


def check_signature(
    lb: Logbook,
    day: str,
    confirm: Sequence[str] | None,
    dispositions: Mapping[str, Sequence[str]],
    at: str | None,
    note: str | None,
) -> None:
    """What `signing.sign` would refuse in the flags of `day sign`, checked before an accepted event
    is written, so that a signature refused leaves nothing behind: `--at` (`signing.moment`), a note
    of more than one line, an empty confirmation beside an accepted event, and every entry of
    `--confirm` and of the four disposition flags a line on the page, not retracted, and given one
    disposition at most."""
    if at is not None:
        signing.moment(at, day, str(lb.meta["timezone"]))
    if note is not None and ("\n" in note or "\r" in note):
        raise signing.SignError("a note is one line; put the rest in a note/v1 line on the day")
    if confirm is not None and len(confirm) == 0:
        raise signing.SignError(
            f"--confirm {signing.NOTHING} confirms nothing, and an event you --accept is confirmed by"
            " accepting it; give one or the other"
        )
    with lb.index() as idx:
        lines = signing.page(idx, day)
        retracted = retractions(idx.retractions())
    for entry in confirm or []:
        _on_page(day, lines, retracted, entry)
    given: dict[str, str] = {}
    for value, entries in dispositions.items():
        for entry in entries:
            line = _on_page(day, lines, retracted, entry)
            if line is None:
                continue
            id_ = str(line["id"])
            if id_ in given and given[id_] != value:
                raise signing.SignError(
                    f"#{line['seq']} is given twice ({given[id_]} and {value}); a line has one disposition"
                )
            given[id_] = value


def _on_page(day: str, lines: Sequence[Line], retracted: Collection[str], entry: str) -> Line | None:
    """The line of the page an entry names by seq or id, as `signing.sign` reads one; None for a blank."""
    text = entry.strip()
    if not text:
        return None
    if text.isdigit():
        line = next((line for line in lines if int(line["seq"]) == int(text)), None)
    else:
        line = next((line for line in lines if str(line["id"]) == text), None)
    if line is None:
        raise signing.SignError(
            f"{text!r} is not a line on the page of {day}; `logbook show {day}` lists them"
        )
    if str(line["id"]) in retracted:
        raise signing.SignError(f"#{line['seq']} is retracted; a retracted line is not a fact of the day")
    return line
