# The plan

You keep your tasks, your sprints and your trips in Notion, and `logbook sync notion`
already writes what happens there into the record: one line per page, day and action, with a database
row's status, select, date and checkbox values and the ids of the rows it links to, never its text
([`sync notion`](commands.md#write)). `logbook show plan` reads the plan back from those lines, for one day:

```
logbook show plan                 # today
logbook show plan 2026-10-21
logbook show plan 2026-10-21 --json
logbook show plan --coverage      # how much of each database the record knows
```

```
plan  2026-10-21 · Sprint 24, 2026-10-12 to 2026-10-25  https://www.notion.so/…
  today       1  2026-10-19  Fix the bilge pump · To do · overdue  https://www.notion.so/…
                 2026-10-21  Ask about winter storage · To do · done today  https://www.notion.so/…
              3  2026-10-21  Book the ferry · In progress  https://www.notion.so/…
              4  2026-10-21  Check the life jackets · To do  https://www.notion.so/…
              5  2026-10-21  Clean the cabin · To do  https://www.notion.so/…
             and 3 more in Sprint 24
  next trip  Lofoten · 2026-11-27 to 2026-12-03 · in 37 days  https://www.notion.so/…
```

The plan is **read and never run** ([RFC 0043](https://github.com/bighydro/logbook/blob/main/rfcs/0043-the-day-page.md),
§9). `show plan` fetches nothing: it reads the lines `sync notion` wrote and nothing else, of Notion or
of the record. It is **tier 1 alone**: every `sync notion` line is tier 1, and the plan reads no other
line (never the day's stays, its browsing or its messages) and names none, not even by its id; the one
exception is your own answers at the day's close (*What the record answers*, below), read only to mark
the tasks you answered. It writes nothing, to the record or to Notion, and it never ranks, reschedules or creates a task. Every
row carries its Notion link, `https://www.notion.so/` and the row's id, so the place to change a task
is Notion. No row's text is ever printed: the record never held it.

## The mapping

Which of your databases is which is yours to say, in `policy/notion.json`, under `plan`, each by its id
or by the link Notion copies (*Copy link to view*):

```json
{
  "plan": {
    "tasks": "https://www.notion.so/ines/Tasks-0123456789abcdef0123456789abcdef?pvs=4",
    "sprints": "…",
    "trips": "…",
    "status": "Status",
    "done": ["Done"],
    "date": "Due"
  }
}
```

Every key is optional, and a part whose database is not named is left out. A line keeps a property's value and not its type, so
three keys say how to read a row: `status` is the property that says a task is done (default
`Status`): a status or select whose option is one of `done` (default `Done`, case aside), or a
checkbox, ticked; and `date` the date property of every database, or a list of them tried in order
(default: a task's day is its `Planned` date, else its `Due` date, and a task with neither is not dated;
a sprint's or a trip's is its first date property, by name).

Without a `plan` entry, `show plan` says so in one sentence and prints nothing else; a `plan` entry that
is not this shape is one error naming the file and the key, exit 2. So is a mapping that names `cities`,
`people`, `places` or `queue`: those are for *where you are* and *from the queue* (*What it is not*, at
the end), which this version does not have. It is a separate file from `policy/crossing.json`, whose
`notion` entry says what may *leave* for Notion (`logbook export notion`): the mapping says how to read
what came *from* it, and nothing here writes either.

## The three parts

Each is read for one local day, in your timezone and under your `day_start`
([where your day begins](settings.md)). A row is its latest standing line: a retracted line is not
there, and only tier-1 lines are read (every `sync notion` line is tier 1).

- **The sprint**: the sprints row whose date holds the day, with its dates.
- **Today's tasks**: the open tasks (not done, not archived) whose date holds today (the day, or a range
  from Monday to Friday on its Wednesday), and the overdue ones (past their last day) in the current
  sprint, marked so. Between sprints no task is overdue, and the plan says so in one line under today's
  tasks, *No sprint holds this day, so no overdue tasks are shown.*; with no sprints database mapped,
  every overdue open task is, and nothing is said. In Notion's own date order, then by title; five at
  most, the rest as a count, `and 3 more in Sprint 24` (or `and 5 more, 3 of them in Sprint 24` when
  some are in no sprint). A task in the sprint is one that links to the sprint, or that the sprint links
  to.
- **The next trip**: the trips row whose date starts soonest, today or after, as a countdown: `today`,
  `tomorrow`, `in 37 days`.

Today's tasks are numbered, 1 to 5 as listed: the numbers `day sign --done`, `--tomorrow` and `--let-go`
take (*What the record answers*, below). A task you answered at the day's close is marked instead (`done
today`, `tomorrow`, `let go`) and has no number, so it cannot be answered twice.

`--json` prints the same as one object: `day`, `mapped` (and `said`, the sentence, when nothing is
mapped), `tasks` (`rows`, `more`, `more_in_sprint`, `sprint`, and `said`: that sentence between sprints,
else null), `sprint` and `trip` (with `days`). Every row has its `id`, `title`, `url`, `line` (the `sync
notion` line that holds its state) and, when it has one, `date`; a task its `status`, `overdue`, `number`
(null once answered) and `answered` (`outcome`, `line`, `seq` of the answer, or null).

## Coverage

The record knows a row only from a line `sync notion` wrote of it. A first `sync notion` by hand reads
every page; a source's first *scheduled* run reads only its last 14 days ([the schedule](schedule.md)),
and `LOGBOOK_NOTION_ROOTS` reads only the pages under its roots. A task last edited before then, or
outside the roots, is not in the record, and the plan cannot show it.
`show plan --coverage` says, for each database you mapped, how many rows and lines the record holds and
the day of its first line:

```
plan coverage: the record knows a row from a line `sync notion` wrote of it
  tasks    13 task rows · 15 lines · first line 2026-09-28
  sprints  2 sprint rows · 2 lines · first line 2026-09-27
  trips    no line yet
  …
```

If that is less than your plan holds, one `logbook sync notion --since <an earlier RFC 3339 instant>`
reads every page edited since then, each as it is now. `show plan` never runs it; the decision, and how
far back, are yours.

## What the record answers

At the close of a day you answer its tasks, by the numbers `show plan DAY` prints, when you sign:

```
logbook day sign 2026-10-21 --done 1,3 --tomorrow 4 --let-go 5
logbook day reflect 2026-10-21 --text "..." --sign --done 1
```

Each answer is one `note/v1` line on the day, labelled `task`, written under the same hold of the writer
lock as the signature and before it, and confirmed by it. Its text is the task's title, and its `extra`
has three keys, for the agent that runs your task tool:

- `task`: the Notion row's id (the page id, dashed, as `sync notion` writes it);
- `line`: the id of the row's line `show plan` reported, the line that held the row as you saw it;
- `outcome`: `done` (close the row as done), `tomorrow` (move its `Planned` date to the next day, set on a
  row that had none; its `Due` date is never touched) or `let-go` (close the row with a status of its own,
  *Let go*, beside *Done*; never the task tool's archive or trash).

The agent applies an answer only while the row is as that line saw it: its status, its `Planned` and its
`Due` as the line holds them (RFC 0043 §9); a later change you made in the task tool wins. The record itself writes nothing to Notion, and nothing here runs the agent: the notes are
lines of your day, so they cross with the signed day under the destination's entry in
`policy/crossing.json` (`hermes`, `notion`) at their tier, tier 2, like every note (`logbook export
crossing --dry-run` counts them under `note`). An unsigned day holds them back with the rest of the day.

A task given two answers, a number `show plan` does not list, and a task answered on the day already are
refused in one sentence, and nothing is written. Signing the day again keeps the answers, as it keeps
every line it confirmed, and never writes them twice. They are not the signature's dispositions: those
name lines on the day's page, and a task's line is usually an earlier day's
([the signed day](signed-day.md#keep-and-sign)).

## What it is not

Not a task manager: nothing is ticked, moved or written back. Not *where you are* (the city of the day's
stays and the plan's rows for it) or *from the queue* (a queued note the day's browsing opened): RFC
0043 §9 has both, but they rest on the day's location and browsing lines, which are tier 2, so they wait
for a later slice that holds them to the entry they are shown under. Not the Day page: the plan's place
there, with *done* / *tomorrow* / *let go* beside each task, is the next part of this slice of RFC 0043
(§9), and the week page's *time by project* and the crossing preview before you sign are later ones.
