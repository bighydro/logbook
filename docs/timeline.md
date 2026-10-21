# The timeline

The timeline is the record's moments beside the map, at five zooms: a day, a week, a month, a year and
all years. The [Library](serve.md) serves it at `/timeline`; `logbook show timeline` prints the same
thing, and with `--json` the very object the page is drawn from. It is RFC 0043's timeline (§11) and the
owner's places (§12), slice F: the map itself comes with slice G.

```bash
logbook serve                                   # then http://127.0.0.1:8765/timeline
logbook show timeline                           # today
logbook show timeline --day 2026-06-12          # one day: its moments and the moves between them
logbook show timeline --week 2026-W25 --json    # an ISO week, a line per day
logbook show timeline --month 2026-06           # a calendar of the month's nights
logbook show timeline --year 2026               # twelve months and the journeys
logbook show timeline --life                    # all years, per place and per vessel
logbook setup places class Saltbu family        # the class of a place, the colour of its nights
```

## A moment

A **moment** is a stay of note: one of your stays, as the [Day](day.md) lists them (a stop that holds a
line, a photo or a call is already a stay), or a run aboard an asset (`aboard Solvind`). It says:

- **the place**: the name `places.json` gives it, else the stay's label (an airport, coordinates with
  what is near);
- **the time**: the part of the stay on the day, `19:30–22:40`, and its length;
- **who was there**: the confirmed in one list and the proposed in another, in grey with a `?` and
  the reason in words: *invited* (an attendee of a calendar entry), *spoke* (a recording), *you said*
  (your own note), *face on photos* (a photo library's face, however many photos). Nothing new proposes
  anyone here: these are the Day's own proposals, and a proposal is never shown as confirmed;
- **the photos** taken during it, your own camera's first and the starred first;
- **what passed during it**, placed by time and never by subject: the messages by conversation (who
  and where, `Kari Nordmann · iMessage`), the calls (who and which way, `Ola Nordmann · call in`), the
  sessions with an agent (your words, and the agent's marked as machine text), the mail threads, the
  notes, the calendar's entries. Never how many messages or how long a call: no number stands beside a
  person;
- **paid**, at tier 3 only: the transactions whose time falls inside it, with the merchant. A day no
  payment source covers says *No payment source covers this day*, with the last day one does: a day is
  covered when it lies between the first and the last day of a transaction that stands (a retracted one
  covers nothing).

On the page each moment is folded to one line, `Saltbu · 19:30–22:40 · 6 photos · 2 conversations · with
Ola Nordmann, Kari Nordmann, Per Hansen?`, the people last, so no number stands beside a name, and opens
to the rest. The moves between moments are one line each, `walk · 07:25–07:41 · 460 m`.

## The zooms

| zoom | `/timeline/...` | what it shows |
|---|---|---|
| day | `day/2026-06-12` | the moments and the moves between them; the night after and its class; the day's track |
| week | `week/2026-W25` | a line per day: its night and its moments as chips |
| month | `month/2026-06` | a calendar: each day in its night's colour, its photos, signed or open |
| year | `year/2026` | the twelve months as a strip of their nights by class; the journeys as bands |
| all years | `life` | per place, its visits since the first; per vessel, its nights and passages; who was there, by name |

Every zoom is a link; the page keeps no state and runs no script. `/timeline` alone is the day you are in.
The month and the year count the nights apart: `home 21 · the family's places 4 · aboard 6 · away 3`
(and `in transit` when no stay held a night). All years reads `Saltbu · 23 visits since 2014` and `aboard
Solvind · 41 nights on 9 passages`, with the people who were there by name only: no number ever stands
beside a person.

A **visit** is a run of your stays at the place with no other named place (or vessel) between: a bench on
the walk home does not end one. A **passage** is a run aboard one vessel, from going aboard to coming ashore
(`stays.fold`). A **journey** on the year is a run of nights away from home, the rule of `show trips` (a
night in transit continues it), drawn for the part of it inside the year and linked to its first day.

## The map

On a phone the map's place comes first and the list under it; on a wider screen the list is on the left
and the map on the right. Until slice G draws a map from an offline map file, the place is a box that says
*the map comes with slice G* and holds the day's track as the Day page draws it: the stays as numbered
dots and the moves between them, from the record's own coordinates. Nothing is fetched.

## A place's class

Each night is one of four classes, its colour on the month and the year:

| class | without a `class` key |
|---|---|
| `home` | a place of kind `home`, or a night within reach of one (the Day's 400 m rule) |
| `family` | never: the family's places are yours to name |
| `aboard` | a night aboard an asset |
| `away` | everything else |

`places.json` keeps it under a key of its own, `class`, which only this reader reads; the format
([SPEC §3.2](../SPEC.md)) does not list it and needs it nowhere else:

```json
{"Saltbu": {"lat": 59.66, "lon": 10.63, "radius_m": 150, "kind": "other", "class": "family"}}
```

`logbook setup places class NAME CLASS` writes it: it says what it will write and what the place's class
is now, asks, and writes only on a yes (`--yes` for scripts). Every other key of the file stays as it was,
and nothing is appended to the record.

## Tiers and speed

Every zoom reads through the page's gate, as every page of the Library does, and says the highest tier it
read. A reading without tier 3 has no money slot at all: not an empty one.

The day and the week read the lines of their own days, as the Day does. The month, the year and all years
read your track from the index alone and count photos and signatures from the index's columns, and the
Library reads each once for the record as it stands (the head, the settings beside the chain and the day):
a reload, or another tab, is served from that reading until the record moves.

All years is not rebuilt each time the record moves. The first time it is opened after a move, the Library
starts one build of it and waits up to ten seconds for it, so a record of a few years shows it at once. On
a record of many years the build takes longer (about a minute at five million lines), and meanwhile the
page says, in one line, that all years is being built; a reload shows it once it is done, and it is kept
until the record moves again. `show timeline --life` builds it every time it runs.

## What it is not

Not a summary: every count is a count of lines, and the words are yours or the sources'. Not an editor:
the page writes nothing. Not a map: that is slice G.
