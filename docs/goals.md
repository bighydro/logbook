# Goals, reviews and chapters

The record holds what happened. These three hold what you are for, what became of it, and what you
call a stretch of your life. Each is one line in your own words, and nothing else in the record is
derived from it ([RFC 0036](rfcs/0036-goals-reviews-drafts-chapters.md)): a **goal** (`goal/v1`), a
**review**, your verdict on a goal at a date (`review/v1`), and a **chapter**, a named stretch
(`chapter/v1`). The profiles each have a page:
[goal/v1](https://github.com/bighydro/logbook/blob/main/rfcs/0036-goal-v1.md),
[review/v1](https://github.com/bighydro/logbook/blob/main/rfcs/0036-review-v1.md),
[chapter/v1](https://github.com/bighydro/logbook/blob/main/rfcs/0036-chapter-v1.md).

```
logbook goal add "Sail to Lofoten and back between June and August." --horizon year --from 2026-01-01
logbook goal review 12 let-go --period month --at 2026-08-31 --note "Engine gone in Bodø. Next summer."
logbook goal list
logbook goal import goals.txt --horizon year --review let-go --at 2026-08-31
logbook chapter open "The Lofoten summer" --from 2026-06-20 --rules "Every night at anchor counts."
logbook chapter close --to 2026-08-09
logbook chapter list
```

All three are tier 2, always: they are your words, as private as a note (SPEC §4, `note/v1`). A
tier is where a line may travel, not who wrote it, so no option sets another one, and a reader
under a ceiling of 1 (the MCP door at its default, a crossing at tier 1) never sees a goal, a
review or a chapter, nor the chapter name in a Day's header. Every line is `source` `manual`: you
wrote it, not a tool and not a model. A model that proposes a goal writes a draft or a note
labelled `proposal`; the goal is yours to write.

## Goals

`goal add TEXT --horizon life|year|quarter` writes one goal. `--from` is the first day it holds for
(today by default, in your day: under a `day_start` of 06:00, 05:30 is still yesterday), `--until`
the last, when it has one. The line's `at` is now, when you wrote it; `from` is the stretch, which
is often earlier (the year's goal, written in its first week).

One line is one goal. Asked for the same words twice, it writes two goals, and you retract one
(`repair retract SEQ REASON`). A goal said better or bounded differently is a new goal that names
the old one: `--supersedes GOAL`, by id or by seq as `goal list` prints it. The earlier words stay in
the record, marked superseded where they are shown; the chain of `supersedes` is one goal. A goal
that is superseded already cannot be superseded again: reword the standing one.

`goal list` prints every standing goal with its latest review, and how many are open; `--open` only
the open ones, `--json` the same with line ids. A goal is open until a review says `done`, `let go`
or `superseded`, or its `until` has passed.

```
2 goals · 1 open
  #2     year     from 2026-01-01 until 2026-12-31   Sail to Lofoten and back between June and August.
         let go 2026-08-31 · month · Engine gone in Bodø on the 9th. Towed home. Next summer.
  #5     quarter  from 2026-10-01                    Learn to splice a rope.
         unreviewed
```

## Reviews

`goal review GOAL DISPOSITION` is your verdict on a goal, one of five: `advancing` and `stalled` keep
it open, `done`, `let-go` and `superseded` close it. The line stores `let go` with a space, the
profile's word; the command line takes `let-go` so it needs no quotes. A later review stands over an
earlier one: a goal closed and then reviewed `advancing` is open again, and the record shows the
change of mind.

`--period day|week|month|quarter|year` is the stretch the verdict covers (default: the goal's
horizon, a year for a life goal). `--note` is the verdict in your words.

`--at` is the day the verdict is about, and a review is often written long after it: let go in August,
written down in October, the line's `at` is in August and its `recorded_at` in October, and the
review is on the August Day. A day, `YYYY-MM-DD`, is that day's last minute (23:59, or 05:59 the next
morning when your day begins at 06:00), or now when it is today; a moment with an offset or `Z`
(`2026-08-31T22:00:00+02:00`) is itself. A verdict more than five minutes in the future is refused, and
so is one before the goal's `from`.

One verdict per goal, per period, per day: asked to review the same goal (any line of its chain) for
the same period on the same day again, the command writes nothing and says which review is there. A
second opinion on the same day is a retraction of the first and a new review.

## The first backfill

`goal import FILE` reads a plain text file, one goal per line, with two optional columns:

```
# the year so far
Sail to Lofoten and back. | year | 2026-01-01
Rebuild the engine. | quarter | 2026-07-01
Read one book a month.
Keep the boat. | | 2026-03-01
```

A line without a horizon takes `--horizon`, one without a first day takes `--from` (today by
default); blank lines and lines starting with `#` are skipped. `--review DISPOSITION` writes one
review of every goal imported, with `--at`, `--period` (each goal's horizon's by default) and `--note`
as `goal review` takes them: the year's goals written down in October and let go at the end of August
are one command. Every line is checked before any is written, and they are all written in one batch:
a line that does not read, or a review before a goal's first day, names the line and writes nothing.
`--dry-run` prints what would be written. A file saved on Windows (a byte order mark, CRLF) reads as
any other.

## Chapters

`chapter open NAME` names a stretch from `--from` (today by default) with its `--rules`, what counts
in it and what you are for in it, as plain text no reader interprets. A chapter is usually named once
you know it is one: `--to` gives its last day when it is already over. `chapter close` closes the open
chapter on `--to` (today by default): the chapter written again with its last day and every other
field, its rules included, superseding the open line. `chapter list` prints every standing chapter,
its rules under it, and `· today` beside the one today is in.

Chapters do not overlap: a stretch that shares a day with a standing chapter is refused, naming it (and,
when that one is open, saying to close it first). The same name from the same day is the same chapter:
asked for it twice, the command writes nothing and says so. This is not `lab chapters`, which reads a
table of contents out of the track and writes nothing.

## On the Day

`day`, `show` and the Day page of `serve` show these lines on the days they are about
(`docs/day.md`):

```
2026-07-04  Saturday · signed 2026-07-05 08:15 · chapter The Lofoten summer
```

- **The chapter, in the header**, after the weekday and the signed state: the standing chapter whose
  stretch holds the day. Should two standing chapters hold one day (two writers, or a retraction that
  reopened one), the later by `from` is shown and the header says `, clashes with <the other>`.
- **The reviews**, one row per review on the day the verdict is about, with the goal's current text (a
  review of the earlier line of a reworded goal shows the reworded words), and `written <when>` when it
  was written on a later day, so a backfilled verdict never passes for one made on the day. Of two
  reviews of one goal for one period on a day, the later is shown; a retracted one is not.

  ```
    reviews       let go · month · Sail to Lofoten and back between June and August. · Engine gone in Bodø on the 9th. Towed home. Next summer. · written 2026-10-11 20:30
  ```

- **The goal and chapter lines**, on the day you wrote them, as every line is: `goal <text> (year, from
  2026-01-01)`, `chapter The Lofoten summer 2026-06-20 – 2026-08-09`, each `· superseded` when a later
  line replaced it. `show` lists a review as `let go · month · <goal text>`.

Under `--json` the Day carries `chapter` (`name`, `line`, `from`, `to`, and `clash` when there is one),
`reviews` (`line`, `goal`, `goal_text`, `disposition`, `period`, `note`, `recorded_at`), `goals` and
`chapters` (the lines written on the day, each with `superseded`, the id of the line that replaced it).
Each key is there only on a day that has one, as `draft` and `reflection` are, so the Day's object is
otherwise what it was and the conformance fixtures do not move: a day in no chapter has no `chapter`
key, where RFC 0036 writes `null`, and a day with no review no `reviews` key, where it writes an empty
list. `days`, `digest`, `year` and the printed pages are unchanged.

A goal, a review and a chapter whose `at` is on a day are on its page, so writing one on a signed day
makes its signature read as the page having changed since, as any line does (RFC 0034); sign again.

## One writer at a time

Every one of these commands is a writer: it holds the record's writer lock for its whole run, from the
first read of the record to the append, and with `--no-wait` it refuses with exit 2 while another
command writes. Before it appends it reads the head again; when another writer moved it in between (one
that did not take the lock), it writes nothing and says the head moved, exit 2.
