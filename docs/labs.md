# The lab

`logbook lab <reader>` runs a reader that is still finding its shape. A lab reader is a reader like
the others (ADR 0013, SPEC §3.2): a pure function of the record at its head, derived every time from
one reading of the window and never written, and it opens no connection. What makes it a lab reader
is that its reading is not settled: its JSON may change between releases, it is not in SPEC §3.2, no
second implementation is held to it and the cross-impl job does not compare it. A lab reader that
proves itself moves out of `logbook/labs/` and into the spec with an ADR; one that does not is
deleted.

```bash
logbook lab introductions              # per person: first day confirmed present with you, and who else was there
logbook lab chapters                   # the record cut into chapters: home changes, gaps in the track, long trips
logbook lab chapters --json            # the same with every number's line ids
```

Both take the window of the rollups: `--year YYYY`, or `--since` and `--until`, clipped to the days
the owner's track covers (the first to the last day with a location line); without either, the whole
record. Both read the record through the index, like `rollup` and `trips`, and print the ids of the
lines behind every number under `--json`.

## Introductions

For every person the record confirms present at a stay with the owner: the first day it does, where,
by which source, and who else was confirmed present that day. The people are the confirmed company of
the with module (SPEC §3.2.5) and nothing else: a timed calendar entry's attendee held at the stay, a
transcript participant the record resolves to a person, a note saying `with <Name>`. Each piece of
evidence is dated by its own line's local day, as `rollup people` dates it.

```
introductions 2026-06-01 – 2026-07-17: 4 people first seen
  2026-06-01  Kari Nordmann  at Office · calendar · nobody else that day · the record had just begun
  2026-07-10  Liv Berg       at Home · note · with Kari Nordmann (known since 2026-06-01, elsewhere that day) · met together: Ola Nordmann (elsewhere that day), Per Hansen (elsewhere that day)
  2026-07-10  Ola Nordmann   at Office · transcript · with Kari Nordmann (known since 2026-06-01) · met together: Per Hansen, Liv Berg (elsewhere that day)
  2026-07-10  Per Hansen     at Office · calendar · with Kari Nordmann (known since 2026-06-01) · met together: Ola Nordmann, Liv Berg (elsewhere that day)
blind spots:
  - …
```

Everyone confirmed on a person's first day is listed with them. Those known from an earlier day are
the **introducers**, the likely ones: the same stay first, then the longest known. Those also first
seen that day are **met together**. `same_stay` says whether the evidence puts the two at the same
stay or only on the same day. Under `--json`:

```json
{"window": {"since": "2026-06-01", "until": "2026-07-17", "days": ["…"]},
 "people": [{"person": "<entity id or null>", "name": "Per Hansen", "first_day": "2026-07-10",
             "stay": "stay:owner:20260710T0610Z@59.9100,10.7600", "where": "Office",
             "sources": ["calendar"], "lines": ["<line id>"], "near_record_start": false,
             "introducers": [{"person": "…", "name": "Kari Nordmann", "known_since": "2026-06-01",
                              "same_stay": true, "lines": ["<line id>"]}],
             "met_together": [{"person": "…", "name": "Ola Nordmann", "known_since": null,
                               "same_stay": true, "lines": ["<line id>"]}]}],
 "blind_spots": ["…"]}
```

The people come first day first, then by name. `near_record_start` is true when the first day falls
in the first 30 days of the owner's track, measured against the record, not the window: a window
that starts later moves first days later and empties the introducers, since inside it nobody was
known before.

### What it cannot see

The reader prints these with the rows and carries them under `blind_spots`, because the numbers
look more certain than they are.

- **The first day is the first confirming line, not the meeting.** Anyone present when the record
  began, or known for years before it, is first seen on some ordinary day. A first day in the record's
  first 30 days is marked `near_record_start`; one later than that can still be an old friend whose
  first calendar entry came late.
- **Only confirmed company counts.** A tagged face is proposed, not confirmed; an all-day entry
  places nobody; a message or a call is contact, not presence. A person met with no confirming line
  is invisible until one exists, and their first day is then the first such line, however late.
- **A person is seen only at the owner's stays.** A day the tracker did not see, or an entry the
  record cannot place at a stay, confirms nobody there.
- **The introducer is a guess from co-presence.** Everyone confirmed that day is listed, the same
  stay first. A large meeting lists everyone in it. Nobody is ever named as the cause; the reader
  says who was there.
- **Identity is the record's.** A person under two refs before `people merge` is two people with two
  first days. A name no resolution line knows is listed by its spelling with `person` null, and
  marked `(unresolved)` in the text.

## Chapters

The record cut into chapters, printed as a table of contents: one row per chapter with its dates,
its nights, its top places and its top people.

```
chapters 2026-03-01 – 2026-05-29: 6 chapters (home history inferred from the nights)
   1  2026-03-01 – 2026-03-28   28 nights  home: Home A               places Office A 136 h, Parents 119 h · with Kari Nordmann 3 d
   2  2026-03-29 – 2026-04-09   12 nights  home: Home B               places Office B 72 h, Home A 9 h · with Ola Nordmann 2 d
   3  2026-04-10 – 2026-04-19     10 days  gap: no track for 10 days  still spoke: mail 10
   4  2026-04-20 – 2026-04-30   11 nights  home: Home B               places Office B 72 h · with Ola Nordmann 2 d
   5  2026-05-01 – 2026-05-25   25 nights  trip: Hotel Zürich         places Hotel Zürich 591 h · with Per Hansen 3 d
   6  2026-05-26 – 2026-05-29    4 nights  home: Home B               places Office B 24 h, Hotel Zürich 10 h
```

A chapter opens where one of three things happens.

**The home region changes.** A home region is a place of kind `home` in `places.json`. Two readings
of the file, in this order:

- *Dated homes.* A home entry may carry `since` and `until`, local days as `YYYY-MM-DD`, either one
  open. `logbook places` keeps the keys when it rewrites the file; no other reader uses them yet.
  When any home entry carries one, the dates decide: a chapter opens on each `since`, the home of a
  day is the dated home holding it (the latest `since` when two do), and a stretch no dated home
  holds is named after the home its nights slept at most. `home_history` is `places.json`.

  ```json
  {"Home A": {"lat": 59.9139, "lon": 10.7522, "radius_m": 120, "kind": "home", "until": "2026-03-31"},
   "Home B": {"lat": 59.9500, "lon": 10.6000, "radius_m": 120, "kind": "home", "since": "2026-04-01"}}
  ```

- *Inferred from the nights.* Without dates, the nights decide. Each night at home (SPEC §3.2.3
  rule 8) lies in one home place: the stay's named place when that is a home, else the home whose
  radius holds its centre, else the nearest home within 400 m. A place becomes the home of the time
  when it holds `--min-home-nights` (14) nights at home before the current home holds that many
  again — the counts start over whenever the current home does, so a week at the parents' every month
  never adds up — and the chapter opens on the first of those nights. The first place to reach the
  count is the home from the start; when none ever does, the place with most nights is.
  `home_history` is `inferred`.

**The track goes quiet.** A run of `--min-gap-days` (7) or more local days with no `location/v1` line
of the owner's is a chapter of kind `gap`, and the sources that still spoke in it are counted under
`still_spoke`. The stay reader treats a silent tracker as stillness (a point that comes back inside
the same radius joins the same stay, however long after), so the nights of a gap are usually "at
home": the chapter says the track saw nothing, not that nothing happened.

**A long trip.** A trip (SPEC §3.2.6) of `--min-trip-nights` (21) nights or more is a chapter of kind
`trip`; the home chapter resumes on the return day. A shorter trip stays inside its home chapter,
counted under `nights.away`. A trip cut by the window is as long as the window leaves it.

Every other day belongs to the home chapter of the time. A gap wins over a trip, a trip over the
home. Without a place of kind `home` nothing is home, there are no trips, only the gaps split the
record, every chapter is `home unknown`, and the reader says so under `warning`.

Each chapter carries, under `--json`:

```json
{"window": {"since": "2026-03-01", "until": "2026-05-29", "days": ["…"]},
 "home_history": "inferred",
 "settings": {"min_trip_nights": 21, "min_gap_days": 7, "min_home_nights": 14},
 "chapters": [
   {"n": 2, "kind": "home", "title": "home: Home B", "start": "2026-03-29", "end": "2026-04-09",
    "days": 12, "home": "Home B",
    "nights": {"total": 12, "home": 12, "away": 0, "in_transit": 0}, "located_days": 12,
    "still_spoke": null, "trip": null,
    "places": [{"name": "Office B", "hours": 72.0, "stays": 9, "nights": 0, "lines": ["…"]}],
    "people": [{"person": "…", "name": "Ola Nordmann", "days": 2, "lines": ["…"]}],
    "opened_by": {"kind": "home change", "detail": "Home A → Home B, inferred from the nights",
                  "lines": ["<the first point of the first night at B>"]},
    "lines": ["<first point of the first night's stay>", "<last point of the last night's stay>"]}],
 "warning": "…"}
```

- `kind` is `home`, `trip` or `gap`; `home` is the home region in force, also in a trip or gap
  chapter, so a trip reads "while living at B". `title` is the row's name.
- `nights` counts the chapter's days by their night: at home, away, or in transit (no stay).
  `located_days` is how many of its days have a location line.
- `places` are the named places of the owner's stays inside the chapter, the home of the time left
  out, by hours inside the chapter (clipped at its edges), then nights there, the top five; a visit
  to another home place, and the old home after a move, are places like any other. `people` are the
  confirmed company of those stays by days together inside the chapter, the top five.
- `still_spoke` counts a gap chapter's lines by source; `trip` carries a trip chapter's id, route and
  places (`logbook trip <id>` reads it back). Both are `null` elsewhere.
- `opened_by` says what opened the chapter: `record start`, `home change`, `track gap`,
  `track resumes`, `trip` or `return`, with a sentence and the lines that show it (the first point of
  the first night's stay; for a gap, the last point before it and the first after).
- `lines` are the first point of the chapter's first night with a stay and the last point of its last.

Three thresholds are settings on the command line, echoed under `settings`: `--min-trip-nights`,
`--min-gap-days`, `--min-home-nights`. Each must be at least 1.

### What it cannot see

- **A move the nights do not show.** Two flats in one city 300 m apart are one home region if their
  radii touch; a move between homes the captain never named is no change at all. Name the places,
  or date them.
- **The first chapter's home is a guess at the start.** Without dates, a record that begins with
  three weeks at the parents' calls the parents' house home until the flat has held 14 nights, and
  then calls the flat home from the first day. Date the homes in `places.json` where it matters.
- **A silent tracker looks like stillness.** The gap chapter is drawn from the days with no location
  line; the stays and nights around it come from the stay reader, which joins the points on either
  side into one stay. A gap's nights at home mean the tracker stopped at home, nothing more.
- **Trips are the trips reader's.** A long stay away that the trips reader does not see (no home
  place; every night in transit) opens no chapter. A trip the window cuts short may fall under the
  threshold.
- **People and places are the stays'.** The top people are the confirmed company of the owner's
  stays (the blind spots of `introductions` above apply); the top places are named places only, so
  a chapter spent somewhere unnamed lists nothing under places. `logbook places propose` names the
  unnamed ones.
