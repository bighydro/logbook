# Five minutes with a demo record

Nothing to import, nothing of yours. `logbook demo` writes a month of a person who does not exist
and every command reads it back. The record is invented in code (`logbook/demo.py`), read from
nowhere, and the same arguments give the same record on any machine.

```bash
pipx install openlogbook                 # or, in a clone: uv sync && uv run logbook …
logbook demo --out ~/Demo/Logbook        # 30 days, seed 1; --days N --seed S to vary it
export LOGBOOK_HOME=~/Demo/Logbook
```

```
demo record: 30 days, 2026-06-01 to 2026-06-30, seed 1; nothing in it is real
wrote 12,772 lines to ~/Demo/Logbook, head 3ee025e7a9fb…
```

## Who

Ines Nordmann lives in Oslo with Ola. She has a sister, Kari; colleagues, Per and Liv; a crew for
the yacht *Nordlys*, Anders and Sigrid; a cabin neighbour, Nils; clients in Zürich, Marta and
Jonas; a friend in Copenhagen, Freja; a mother, Eva; and a running friend, Tore. Twelve people,
each resolved from an `example.org` address and a `07700 900xxx` number, some from a face the
photo library tagged. None of them exists.

Her June: an office week with a weekend at the cabin; Zürich for a client, Monday to Thursday;
a week aboard *Nordlys* down the fjord; and a long weekend in Copenhagen. After 28 days the story
starts again, so `--days 90` is a summer.

## The chain

```bash
logbook verify
```

```
valid — 12772 lines, head 3ee025e7a9fbdbbbf5b91de0ec3bfac7ca27c22d53255aecd615e75fbca0c609
```

Every line is hash-chained to the one before. Change one character of any line and `verify`
says so. The head is the same every time you run `logbook demo` with the same days and seed.

## What is in it

```bash
logbook stats
```

Counts by kind, source and year, never what a line says: ten thousand location points from the
phone and the boat's AIS, two and a half thousand health samples, and a handful of everything
else — events, messages, transcripts, notes, photos and the keepers inferred from them, calls,
mail, tasks, browsing, videos watched, music and podcasts, paid trips, book highlights, voice
memos (metadata and a digest; no audio), transactions, four flights, and the resolution lines
that name the circle.

```bash
logbook stats --health
```

One row per day: hours asleep (the union of the night's stages, never in bed or awake), steps
(the larger device per quarter hour, summed), resting heart rate.

## A day

```bash
logbook day 2026-06-17
```

```
2026-06-17  Wednesday
  night before  aboard Nordlys · 59.4300,10.4800 · away
  night after   aboard Nordlys · 59.0500,10.0300 · away
  country       NO (nearest airport TRF)

  00:00–24:00  aboard Nordlys (yacht) · 24 h · 1 note, 1 message, 1 photo
      00:00–08:55  stay   59.4300,10.4800 (Sandefjord) · 8 h 55 min
      08:55–14:00  move   49.4 km · 5 h 5 min · boat
      14:00–24:00  stay   59.0500,10.0300 (Sandefjord) · 10 h
      note         Anchored by nine. Grilled.
      with         proposed Anders Vik (photo)

  health        sleep 6.7 h · 6,602 steps · resting 56 bpm
  sources       dawarich 263 lines, last 23:55 · ais 173 lines, last 23:50 · apple-health 84 lines, last 22:29 · …
```

One day read back: the nights around it, the country, the stays and moves with what was attached
to them and who was there, the flights, the health line, and every source's newest line, so a
tracker's silence is seen. A day aboard the boat is one stay `aboard Nordlys`, with the anchorage,
the passage and the next anchorage inside it; the night names the boat and where she lay. Then
every line of the day as the sources wrote it:

```bash
logbook show 2026-06-08             # the morning flight to Zürich
logbook show 2026-06-17 --raw       # refs as the sources spelled them, never a name
```

## Where she was

```bash
logbook derive stays --day 2026-06-17
```

```
2026-06-17
  00:00–08:00+1  stay  aboard nordlys · 32 h · 1 note, 1 message, 1 photo
      00:00–08:55    stay  59.4300,10.4800 · 8 h 55 min · 1 message
      08:55–14:00    move  49.4 km · 5 h 5 min · boat
      14:00–08:00+1  stay  59.0500,10.0300 · 18 h · 1 note, 1 photo
  night          aboard nordlys · 59.0500,10.0300 · 00:00–08:00+1
— nordlys (Nordlys, yacht)
2026-06-17
  00:00–09:05    stay  59.4300,10.4800 · 9 h 5 min
  09:05–14:00    move  49.4 km · 4 h 55 min · boat
  14:00–08:00+1  stay  59.0500,10.0300 · 18 h
```

Stays, moves and the overnight stay, derived from the points and never written (ADR 0013). The
owner's track first, then each asset's; when the boat's track lies within the radius of the
owner's points for twenty minutes or longer the owner is *aboard*, and the run of stays and
moves aboard is one stay with the run under it ([day.md](day.md), *Aboard an asset*). A
range: `--since 2026-06-15 --until 2026-06-21`; one subject: `--subject nordlys`; `--json` for
the numbers.

```bash
logbook places propose --top 4
```

```
2026-06-01 – 2026-06-30: 14 unnamed places, by hours
  1.   58.5 h · 47.3769,8.5417 · 3 stays · 1400 km from Marina   stay:owner:20260608T0830Z@47.3769,8.5417
  2.   40.7 h · 59.0500,10.0300 · 2 stays · aboard nordlys · 103 km from Marina   …
  3.   40.0 h · 59.8500,10.6000 · 2 stays · aboard nordlys · 9.7 km from Marina   …
  4.   33.1 h · 55.6850,12.5500 · 2 stays · 481 km from Marina   …
```

`places.json` names Home, Office, Marina and Cabin; the hotels, the anchorages, the cafe and the
airports are yours to name. `logbook places name <stay id> "Hotel by the river"` adds one and puts the naming in the
record as a note; `--write` asks for each in turn.

## Trips, flights, countries

```bash
logbook trips
```

```
trips 2026-06-01 – 2026-06-30: 4 trips
  2026-06-06 – 2026-06-06  1 night · route Cabin · places Cabin · with Ola Nordmann
  2026-06-08 – 2026-06-10  3 nights · route Zürich · in XY 561 OSL → ZRH · out XY 562 ZRH → OSL · with Marta Keller, Jonas Weber
  2026-06-15 – 2026-06-20  6 nights aboard nordlys · route near Marina → Sandefjord → near Marina → Marina · places Marina · with Ola Nordmann, Anders Vik, Sigrid Moen
  2026-06-25 – 2026-06-26  2 nights · route Copenhagen Kastrup · in XY 571 OSL → CPH · out XY 572 CPH → OSL · places Office · with Freja Lund, Liv Berg, Per Hansen
```

A trip is a run of nights away from every place of kind `home`, with the flights in and out and
the people the calendar, a transcript, a note or a tagged face put there. Derived, never written
(ADR 0019).

```bash
logbook rollup flights
```

```
flights 2026-05-31 – 2026-06-30
  2026  4 flights · 3,886 km · 0 long-haul · declared 1, inferred 1, tracked 2
        2026-06-08  XY 561  OSL → ZRH · 1,426 km · tracked
        2026-06-11  XY 562  ZRH → OSL · 1,426 km · inferred
        2026-06-25  XY 571  OSL → CPH · 517 km · tracked
        2026-06-27  XY 572  CPH → OSL · 517 km · declared
```

Three producers of one profile (RFC 0013): a flight tracker's export (`tracked`), the record's own
calendar entry and location points (`inferred`), the owner's word (`declared`). Let the record
infer the rest:

```bash
logbook infer flights
```

```
inferred 3 new flights from 4 calendar entries (1 already in the record)
  also 3 merged into a flight already in the record
```

Four calendar entries name a flight (`Flight to Zürich (XY 561)`) and the location points leave
one airport and reach another around each. The flight home from Zürich was already in the record
as an inference; the other three merge into the lines that stand, each new line superseding the
last and listing every observation. Run `rollup flights` again and XY 572 reads `inferred`: the
record's own evidence outranks the owner's word, and the declared line stays in the record.

```bash
logbook rollup countries
logbook rollup nights
logbook rollup places
logbook rollup people
```

```
countries 2026-06-01 – 2026-06-30
  2026  NO 25 days · CH 3 days · DK 2 days · in transit 0
```

```
nights 2026-06-01 – 2026-06-30
  2026  18 home · 12 away · 0 in transit · 6 nights aboard nordlys · longest trip 2026-06-15 – 2026-06-20 (6 nights)
```

`--json` on any of them carries the ids of the lines every number came from.

The whole year on one page — the rollups, the trips in order, the places by nights, the people by
days together, health and keepers by month, and one day a month read back with the day reader,
the day with the most evidence ([docs/year.md](year.md)):

```bash
logbook year 2026                        # as text
logbook year 2026 --html ~/Demo/2026.html  # one self-contained page that prints
```

## Keepers and pages

```bash
logbook keepers                     # the photos she marked favourites, and the one in the Art album
logbook show person "Ola Nordmann"  # a page: when they were together, by the evidence
logbook show asset nordlys          # the boat's page
logbook show place Cabin
```

## Out and back in

```bash
logbook export --day 2026-06-17 --out ~/Demo/pages    # one day as a package: 528 entries
```

A window for someone in the circle is a crossing (RFC 0005): name them in `policy/crossing.json`
with the highest tier they may see, then `logbook export crossing --to <name> --since … --until …`.

## Make it yours

The month is a function of two numbers. `--seed 2` is the same story with other noise, other
step counts, other times for the messages; `--days 90` is a summer; `--days 365` a year of 150,000
lines, enough to feel what the index is for. When you are done:

```bash
rm -r ~/Demo/Logbook
unset LOGBOOK_HOME
logbook init                         # your own, in ~/Logbook
```

Nothing of the demo is real: the people, the boat, the airline XY, the aircraft ZZ-ABC, the
addresses, the numbers. The persona lives in Oslo and does not exist.
