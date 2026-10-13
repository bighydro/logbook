# The doctor

`logbook doctor` is the check-up: one line per check, `pass`, `warn` or `fail`, and exit 1 when
anything fails. It reads and never writes. The checks and their rules are listed in the module's
own documentation (`logbook/contrib/doctor.py`); the schedule runs it four times a day
([The schedule](schedule.md)). `logbook doctor sources --gaps` says where each source went quiet.

## Where the day begins

A record whose day does not begin at midnight ([`day_start`](settings.md)) gets a `day-start` line
after `index`: a pass naming the boundary (`pass  day-start  the day begins at 06:00: a line before 06:00
belongs to the day before`); a **warn** when `index.sqlite` was built under another boundary, naming
both (the next reader rebuilds it, or `logbook repair index` does now); a **fail** when the value is not
a clock `HH:MM`, which every reader that groups by day refuses. A record whose day begins at midnight,
with an index that agrees, has no such line.

## Implausible dates

A calendar entry a parser placed in 1948, or a mail a sender's broken clock dated 2612, is not a
day of the owner's life. The `dates` line counts the lines whose timestamp lies outside their
source's plausible range, per source with the earliest and the latest, and warns:
`warn  dates  2 line(s) dated outside their source's plausible range: ics 1 (1948-03-01 to
1948-03-01); mail 1 (2612-03-01 to 2612-03-01); …`. The ranges are: calendar entries (kind
`event`) from 1970-01-01 to now plus 5 years; mail from 1990-01-01 to now plus 1 day; every other
line from 1970-01-01 to now plus 1 day. A record overrides them per source in
`policy/plausible.json`, either field optional — `{"sources": {"ios-calendar": {"earliest":
"1960-01-01", "ahead": "10y"}}}`, `ahead` a count of years or days (`5y`, `1d`); a file that is not
this shape is a fail naming it. Nothing is deleted, hidden or rewritten: the lines stay in the log
and in every reader as they were written. `logbook doctor --implausible` lists them, one row each:
the line id, the source, the kind, the timestamp and the range it missed, then the count.
