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

## Drafts the policy no longer allows

A draft follows the `dream` entry of `policy/crossing.json`, not the head ([the dream](dream.md), *When
the entry changes*). When a day's standing draft is above what the entry allows today (the ceiling
lowered, the `until` passed, the entry removed), no reader shows it, and a `drafts` line after
`crossing` names the days: ``warn  drafts  1 day(s) with a draft above what the dream entry allows, which
no reader shows: 2026-06-10 (#5440, tier 3); the 'dream' entry allows max_tier 2 now; `logbook dream
--catch-up` dreams them again under it``. A record with no such day has no line.

## The Google key

When either variable of the Google service-account key is set (`LOGBOOK_DRIVE_SA_KEY`,
`LOGBOOK_DRIVE_USER`), one `google` line comes before the `sync:` lines of the sources it covers: the key
file present and a service-account key, the user an address, and which of `gmail`, `gcal`, `drive` and
`gtasks` are on it, a source switched off in `policy/import.json` named as disabled —
`pass  google  key present, user set; sources on the key: gmail, gcal, drive, gtasks`. A key not set,
not readable or not a service-account key, or a user that is not an address, is a warn naming the
variable. The line reads the key on this machine and asks Google nothing, and never prints the path or
the address ([the tour, *Google, on one key*](tour.md#google-on-one-key)).

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
