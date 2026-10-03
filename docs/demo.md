# A life in a record

`logbook demo` writes a month (`--days`, [try-it.md](try-it.md)). `logbook demo --years N` writes
a life instead: Ines Nordmann, who does not exist, from her birth to 30 June 2026, in phases that
change the shape of the data. The record is invented in code (`logbook/labs/demo_life.py`, on the month's
`logbook/contrib/demo.py`), reads nothing, and is a function of `--years` and `--seed`: the same two
numbers give the same chain head on any machine.

```bash
logbook demo --years 40 --out ~/Demo/Life     # born 1 July 1986; forty years to 30 June 2026
export LOGBOOK_HOME=~/Demo/Life
```

```
demo record: 40 years, 1986-07-01 to 2026-06-30, seed 1; nothing in it is real
wrote 114,786 lines to ~/Demo/Life, head 1d0a9bb43049…
```

She is born the day after the record ends, `N` years earlier, so the record closes on the eve of a
birthday and every year of her life is whole. `--days` and `--years` are one or the other.

You can browse these forty years without installing anything:
[bighydro.github.io/logbook/ines/](https://bighydro.github.io/logbook/ines/) is this record, seed 1,
rendered by `logbook export site` at tier 1 ([site.md](site.md)) — a Year page per year, every trip, a Days
index per year, the places and the people — and published with the docs on every push to `main`.

## The phases

The phases are by age, so a short life is a child's and a long one reaches the boat. Each changes
which sources write, how often, and how dense the phone's track is.

| Age | Phase | Where | What the record holds |
|---|---|---|---|
| 0 to 5 | childhood | Bergen, the family home | Scanned photos (`provenance` `other`, faces tagged), the birthday and Christmas Eve as entries the owner typed in later (`source` `manual`), a summer at the family cabin, and stories told about her: a note a year in the voice of her sister Kari or of Ola, the boy from across the street (`Kari Nordmann: …`), as `promises` reads a speaker. No track, no phone: twenty lines a year. |
| 6 to 13 | school | Bergen | The calendar fills: football practice every Wednesday with Mia and Jens, the class trip, the first day of school; more photos; a diary from 10. Still no track. |
| 14 to 18 | school, with a phone | Bergen | A thin track (a point per stay: where she slept, where she spent the day), texts over iMessage with Mia, Jens and Ola, calls. The family's weeks at the cabin (Easter, July) become trips; a package holiday every other summer, Mallorca, London, Barcelona, brings the first flights, declared from memory (`evidence` `declared`). |
| 19 to 23 | university | Copenhagen, the student flat | Lectures three mornings a week with Hanna and Freja, exams, mail, pages, music, the first transactions. A term in Barcelona at 21, the first long trip (131 nights); a week in London with Hanna at 22; Christmas flights home to Bergen, where the family home is still a home region, so Christmas is not a trip. |
| 24 to 31 | work | Copenhagen, the office | Meetings twice a week with Bjørn, the first boss, and Freja; a transcript the first Thursday of each month; mail three times a week; Zürich for a client twice a year from 26 (Marta and Jonas); a month in Lisbon at 28. Ola comes back at 29, and from then there is a chat with him every other day. The flight tracker from 30: flights are `tracked` from here. |
| 32 on | work, after the move | Oslo: Home, Office, the cabin | The move on 1 October of her thirty-second year, one flight and a note. Per and Liv at the office, Nils at the cabin, six cabin weekends a year with Ola, a Copenhagen visit to Freja each autumn, Zürich twice a year with the tracked flight out and the flight home the record infers from its own points, as in the month. The watch at 34: health starts there, and a run in the park with Tore every other Sunday. The boat at 35: *Nordlys* at the marina, a summer cruise every July with the boat's own AIS track, day sails on Saturdays. Three weeks in Rome at 37. |
| the last month | June 2026 | Oslo | The month `logbook demo` writes on its own, at the phone's full resolution (a point every five minutes, the watch's quarter hours, every profile), when the life is 36 years or longer. A shorter life ends thin. |

People drift in and out, as the `people` reader shows: Jens stops after school (last contact
2005), Mia calls once at 21 and writes once at 24 and is not heard from again, the grandmother
Solveig is in the photos until Ines is 27, Hanna writes once more at 33, Ola is in the childhood
photos from 3, absent through the university years, and back for good at 29.

## The knobs

- `--years N`: the length of the life, 1 or more. A one-year record is a baby's: photos and family
  entries, no track. Fourteen years and more have a phone; thirty-six and more end with the full
  month and have the boat.
- `--seed S`: the same seed gives the same record; another seed is the same life with other noise,
  other step counts, other days for the photos and the cabin weekends. The dates of the phases, the
  journeys and the moves do not depend on the seed.
- The ages are constants at the top of `logbook/labs/demo_life.py` (`PHONE_AGE`, `STUDENT_AGE`,
  `WORK_AGE`, `OLA_BACK_AGE`, `TRACKER_AGE`, `MOVE_AGE`, `WATCH_AGE`, `BOAT_AGE`), and the
  journeys of each year are planned in one place (`_journeys`), so a different life is a small edit.

## Size

Old years are thin, so forty years stay a record a laptop reads at once: about 115,000 lines, of
which 72,000 are location points, most of them in the last six years. Lines per calendar year,
seed 1:

| 1988 | 1995 | 2002 | 2008 | 2015 | 2019 | 2021 | 2025 | 2026 (to June) |
|---|---|---|---|---|---|---|---|---|
| 18 | 63 | 1,671 | 3,162 | 2,831 | 3,149 | 7,890 | 9,781 | 17,134 |

The month alone is 12,800 lines; a year of the month's story (`--days 365`) 155,000.

## What to try

```bash
logbook trips --year 2001          # Easter and July at the family cabin, the first year with a phone
logbook trips --year 2008          # the Barcelona term, 131 nights, and the summer flights home
logbook trips --year 2025          # cabin weekends, Zürich twice, the cruise aboard Nordlys, Copenhagen
logbook rollup flights             # declared until 2016, tracked and inferred after
logbook rollup countries --year 2007   # a Copenhagen year: DK 353 days, NO 12
logbook day 1989-07-01             # a third birthday: one entry, one scanned photo, no track
logbook day 2022-07-23             # a day of the first cruise, aboard, with the night at anchor
logbook stats --health             # from 1 July 2020, the day the watch appears
logbook people --year 1998         # Mia and Jens, every Wednesday
```

```
trips 2001-01-01 – 2001-12-31: 2 trips
  2001-03-28 – 2001-03-31  4 nights · route the family cabin · places the family cabin · trip:2001-03-28:2001-03-31
  2001-07-10 – 2001-07-16  7 nights · route the family cabin · places the family cabin · with Solveig Nordmann, Kari Nordmann, Eva Nordmann · trip:2001-07-10:2001-07-16
```

`people` over the whole life lists everyone with their first and last contact, and shows who is
a decade gone, but the reader asks for the overnight stay of every one of the 14,600 days against
every stay of the window, so on a forty-year record it takes minutes today; `people --year` is
quick. The tests read the same report from the channels alone.

Nothing of the life is real: the people, the boat, the airline XY, the aircraft ZZ-ABC, the
addresses, the numbers (UK `07700 900xxx`, `example.org`), the cities she lived in. The record
pretends the phone always had a track from the day she got one and that the texts of 2000 were
iMessages; the shape of a life is the point, not the era.
