# The record's settings

A setting is how you want the record read, not something that happened: it has no `at`, so it is never a
line. The record's own settings live in `logbook.json` beside the chain's head; the readers' settings live
in files beside the log, each yours to edit. `logbook setup` asks about the ones a first run needs, and
`logbook setup <setting>` changes one later.

| setting | where | set with |
| --- | --- | --- |
| your timezone | `logbook.json`, `timezone` | `logbook setup --step timezone` |
| where your day begins | `logbook.json`, `day_start` | `logbook setup day_start 06:00` |
| your own addresses | `logbook.json`, `owner_emails` | `logbook setup --step owner` |
| your other names, addresses, numbers and handles | `policy/owner.json` | `logbook setup --step owner`; `handles` by hand |
| the named places, your home | `places.json` | `logbook setup places` |
| the assets you track | `assets.json` | `logbook setup assets` |
| the digest's questions | `policy/questions.json` | `logbook setup questions` |
| what may leave, and to whom | `policy/crossing.json` | by hand ([the signed day](signed-day.md)) |
| how long a stay is, the night | `policy/stays.json` | by hand |

`policy/owner.json` is `{"names": [...], "emails": [...], "phones": [...], "handles": [...]}`: the
ways the record meets you, so you are never your own company and never a person to review. `handles`
are your logins on a service — `ines-example`, `@ines-example`, or `github:ines-example` for GitHub's
alone, case aside — by which `sync github` and `add github-export` mark your own commits, issues and
comments `owner` ([GitHub](adapters/github.md)). Every key is optional: a file written before `handles`
existed lists none.

Changing a setting rewrites nothing: no line, no hash, no month file. The index is a cache of the
record's days and is rebuilt when a setting it depends on changes (`timezone`, `day_start`).

## Where your day begins: `day_start`

Out of the box a day is the calendar day: from midnight to midnight in your timezone. If you live late, the
concert that ended at 01:30 is the evening's, not the morning's, and the Day of the 13th should not open
with it. `day_start` moves the line:

```bash
logbook setup day_start           # where it begins now: midnight unless you set it
logbook setup day_start 06:00     # a line before 06:00 belongs to the day before
logbook setup day_start 00:00     # back to the calendar day
```

The value is a clock, `HH:MM`, from `00:00` to `23:59`. `logbook init` leaves it out, which is `00:00`.
With `"day_start": "06:00"` in `logbook.json`:

- a line at 01:30 on the 13th is on the **12th**; a line at 06:00 or 07:00 on the 13th is on the 13th; a
  line at 23:30 on the 13th is on the 13th, as it always was;
- the day runs from 06:00 to 06:00 the next morning, and the Day says so in its header (`2026-10-12 Monday
  · unsigned · 06:00 to 06:00 the next day`);
- the comparison is on your wall clock after localising, so the night the clocks change moves no line: at
  06:00 on the last Sunday of October the day begins at 06:00, whatever the offset was at 01:30.

Every reader that puts a line on a day goes by it, from one rule in the code (`logbook/core/day_start.py`):
the index's `day_local`, `show`, `day` and `days`, the nights before and after a day, `trips`, `gaps`
(`doctor sources --gaps`), the digest and its week paper, promises, the rollups, the Year, people, the
signed day's page and the crossing of signed days, the vault, the printed pages, the shared page, the MCP
tools' days, and the pages `logbook serve` keeps, `/today` included (at 05:59 it is still yesterday's
page). Nothing that writes goes by it: `add`, the adapters and the month files keep `at` as it is, in UTC.

**The index.** `logbook setup day_start` rebuilds the index under the new boundary when there is one, with
progress, and says so; on a record without one it says the next reader builds it (or `logbook repair index`
now). The index records the boundary it was built with, and a reader rebuilds it when `logbook.json` says
otherwise, as it does when the head has moved. `logbook doctor` prints a `day-start` line when the day does
not begin at midnight, and warns when the index was built under another boundary.

**Signed days.** The page of a day is the lines on the day so defined, and a signature covers that page.
Moving the boundary moves lines between pages, so a signed day whose page changed reads as `the page has
changed since`, exactly as it does when a line is appended to it; `logbook setup day_start` counts them
(`signed days: 3 of 41 no longer match their page`). Read each again and sign it, or set the boundary back.
Set it once, early.

**The night.** The night window of `policy/stays.json` (22:00 to 08:00) is unchanged: it finds the night's
stay. `day_start` says which night is a day's: the night after a day is the one whose window holds the
day's end, so with `06:00` the night after the 12th is where you were at 06:00 on the 13th, the night of
the 12th, as at midnight. A boundary at or after the night's start (23:00, say) makes a day end inside the
next date's night, and the night after the 12th is then the night of the 13th.

**A value that is not a clock.** `"6am"`, `"24:00"` or `"6:00"` is refused by every reader that groups by
day, naming the key and the value (`logbook.json has day_start '6am', which is not a clock …`), exit 2;
nothing is guessed. `add`, `verify` and the adapters go on as before, since they never group by day, and
`doctor` fails the `day-start` line until it is fixed. A reader that does not implement the rule (RFC 0036)
must refuse in the same way; the conformance samples carry no `day_start`, so it passes as before.
