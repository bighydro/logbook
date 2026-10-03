# The vault

`logbook export vault <folder> [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--tier 1|1,2]` renders the
record as a folder of plain Markdown that Obsidian or Logseq opens as a vault: one page per day, one
per named place, one per person, one per trip, one per year, every page linked to the others with
wikilinks. It is an export, not a reader: it is tier-gated exactly like a crossing (tier 1 by default,
the shape of every day and no text of any note or message), and every run appends one `crossing/v1`
line to the chain so the record shows it left. Re-running rewrites only the files whose content
changed.

```bash
logbook export vault ~/Vault                            # every day the record covers, tier 1
logbook export vault ~/Vault --since 2026-06-01 --until 2026-06-30
logbook export vault ~/Vault --tier 1,2                  # notes, transcripts, mail and calls named; needs the policy below
```

Then open the folder in Obsidian (*Open folder as vault*) or point Logseq at it. Nothing in it needs
a plugin: the links are `[[Name]]`, the front matter is YAML, the files are UTF-8 with `\n` line
endings on every platform.

## The folder

```
<folder>/
  Logbook.md                      the root: years, places, people and trips, each a link
  years/2026.md                   the year: days per country, trips, places by nights, people by days, one line per day
  days/2026/2026-06-13.md         the Day, as `logbook day` reads it
  places/Home.md                  one per place in places.json: its days, the people met there, its trips
  people/Kari Nordmann.md         one per person confirmed present by a line that crosses
  trips/Trip 2026-06-15 to 2026-06-17.md   one per trip, as `logbook trips` derives them
```

A page's file stem is its link text, so the stems are one namespace for the whole vault and every
one is a file name on every platform: whitespace is collapsed, the characters a file system or a
wikilink refuses (`< > : " / \ | ? * [ ] # ^`) become dashes, trailing dots are dropped, and two
names that differ only by case are two pages, the second with ` (2)`. A day is `2026-06-13`, a year
`2026`, a trip `Trip <start> to <end>`; a place and a person keep their names.

## A day

The front matter is what the graph and a search can filter by; the body is the Day:

```markdown
---
date: 2026-06-13
weekday: Saturday
country: "NO"
nights:
  before: "Home"
  after: "aboard Solvind"
places:
  - "Home"
  - "Marina"
people: []
trip: "Trip 2026-06-13 to 2026-06-13"
---
# 2026-06-13

Saturday · night before [[Home]] · night after aboard Solvind · NO · [[2026]] · [[Trip 2026-06-13 to 2026-06-13]]

## Timeline

- 00:00 – 09:00 [[Home]]
- 09:00 – 09:15 walk 1.4 km
- 09:15 – 24:00 aboard Solvind · 1 photo · held back: 1 note
    - 09:15 – 10:00 [[Marina]]
    - 10:00 – 12:00 boat 9.7 km
    - 12:00 – 24:00 59.8500,10.6000

## Sources

dawarich 888, immich 1, manual 1
```

`country` is quoted because a bare `NO` is `false` in YAML. `nights` are the night before and the
night after as the Day names them: a named place, `aboard <asset>`, coordinates with the nearest
place or city, or `in transit`. `places` are the named places stayed at, in order of first stay;
`people` the ones confirmed present — attending a timed calendar entry held at the stay, speaking
in a transcript, named in a note — by a line that crosses (below). A proposed face in a photo is
not on the page: it is a proposal, not a day together ([docs/day.md](day.md)).

The timeline is the Day's rows, each clipped to the day: a stay at a named place is a link, a stay
elsewhere its coordinates with the nearest place or city, a move its mode and kilometres, a stay
aboard an asset one row with the berths, passages and anchorages indented inside it, a flight its
own row. What attached to a row is counted on the row and named under it (`event: Lunch`), who was
there is linked, and what the gate held back is counted: `held back: 1 note`. Then the all-day
entries, the lines the track could not place, the notes in full (only when their tier crosses), and
the sources with their line counts.

## The gate (ADR 0016)

A line is in the vault when its tier is in `--tier`, and shows only as a count when it is not — the
same rule a crossing applies, line by line. The default, tier 1, is the shape of the record: where
you were, how you moved, the flights, the calendar entries, how many photos and messages and notes,
who the calendar confirms present. No text of any note, message, transcript or mail is in a tier-1
vault, and a person a tier-2 note names is not on the page until tier 2 crosses: the Saturday above
says `held back: 1 note` and names nobody; with `--tier 1,2` the same row reads
`1 note, 1 photo · with [[Ola Nordmann]]`, the note's first line under it and its text under
*Notes*. A message's text is never rendered: a vault is a diary, not a chat archive, and at tier 2
messages stay a count per row. Health and money are tier 3 and never go to a vault; `--tier 1,2,3`
is refused.

How far the gate opens is a setting in the record, not in the code: `policy/crossing.json` maps a
destination to its ceiling, and the vault's destination is `vault`. A file that does not name it
allows tier 1 — the vault is a folder on your own disk, like the `mcp` client — so `--tier 1,2`
needs one line added:

```json
{"hermes": {"max_tier": 2}, "mcp": {"max_tier": 1}, "vault": {"max_tier": 2}}
```

A request above the ceiling is refused naming the file, and nothing is written or appended.

## The record shows it left (RFC 0011)

Every run appends one `crossing/v1` line with the destination `vault`, the window as instants (the
first day's local midnight to the midnight after the last), the tiers, the counts (how many lines
the window logged, how many crossed, how many were held back, by tier and by kind), the ceiling in
force, the head before the line, and `package_sha256`: the digest of the folder as written, one line
per file — `<sha256 of its bytes>  <path>` in path order — hashed, which is what a crossing's
manifest digest is for a bundle that has a manifest. Under `extra.vault` are the pages per kind and
how many files were written and how many were unchanged. `logbook show` lists it as
`crossed to vault: 888 lines (tier 1: 888)`. Nothing else is written to the record, and that
one write goes through `Logbook.append`.

## Re-running

Every page is a function of the record's lines and its settings alone: no head, no timestamp, no
counter is in any file, so a day that did not change is a file that did not change. A run compares
each page's bytes with what is on disk and writes only the differences; the console says
`23 written, 0 unchanged` the first time and `0 written, 23 unchanged` the next. Nothing is deleted:
a page the record no longer produces (a place renamed in `places.json`, a window narrowed with
`--since`) stays until you remove it, and Obsidian's own `.obsidian/` folder and your own notes beside
the pages are never touched. A nightly run is a reasonable thing, and it costs one line in the chain.

## The graph it produces

Obsidian's graph view draws one node per page and one edge per link; the vault is built so that the
picture is the record's shape, without a screenshot:

- **Days** are the most numerous nodes, each with few edges: its year, the places it was spent at,
  the people confirmed present, and its trip when it is in one. A home day links to `Home` and the
  office; a day away links to no named place and hangs off its trip.
- **Places** are hubs. `Home` has an edge to almost every day and is the centre of the graph; the
  office to the weekdays; a marina or a cabin to the weekends. A place with a `country` in
  `places.json` carries it in its front matter, so the graph can be coloured by it.
- **People** sit between the days they were met on and the places they were met at; a person met
  only on trips floats near the trip nodes, a colleague clusters with the office.
- **Trips** are short chains: the trip node with an edge to each of its days, its named places and
  its people, and to its year. A week aboard is one node with seven day spokes.
- **Years** gather everything: one edge to every day, place, person and trip of the year; the root
  page `Logbook` links the years.

Local graph on a day page shows that day's week of places and people one hop out; on a person it
shows the days together, the places shared and the trips. In Logseq the same links are the page
references, and the journals view is empty: the day pages are ordinary pages named by date, not
Logseq journals, so they sit under *All pages* and in the graph.

## What it is not

It is not a reader of the record for other software: the day package (`export --day`) and the
crossing package (`export crossing`) are that, and they carry lines, not prose. It is not a backup:
`logbook backup` is. It renders what the readers derive — a stay, a trip, a companion — and a
derivation is disposable (ADR 0013): rename a place, raise the ceiling, and the next run rewrites
the pages that changed. Your own notes beside the pages are yours; the pages are the record's.
