# The week

`logbook serve` has a page for every ISO week, `/week/2026-W25`: the Sunday's week draft
([`dream week`](dream.md#journeys-and-weeks)) grown into a page, beside the seven days it covers. Every
Day links to the week it is in (the pager under its date), and so does the Sunday's week draft. The page is
read-only: nothing on it writes, and it carries no form and no script. Closing the week is the second
part of [RFC 0043](https://github.com/bighydro/logbook/blob/main/rfcs/0043-the-day-page.md) §8 and is not
built yet.

```
The week 2026-W25          15–21 June 2026 · nothing read above tier 2
← 2026-W24 · its Sunday, 2026-06-21 · 2026-W26 →
From the draft as written, by qwen2.5-7b-instruct: its numbers are the code's, its sentences pencil.

▸ The seven days        7 days with lines · 2 entries planned
▸ Where the week went   6 places · 4 threads
▸ Goals                 2 goals · 0 touched this week · 1 verdict proposed
▸ Next week             one proposal, pencil
▸ The question          one question, asked once
▸ People who moved      against the week before, names only
▸ The plan              Sprint 12 · next trip in 12 days
▸ Hold                  1 sender · 1 file
```

Each part is a fold with a summary line complete in its counts, so a closed fold says what it holds. A
part with nothing in it is not drawn: the empty ones are named once, in one muted row, *Nothing from*.
`?open=1` opens every fold, for printing.

## The parts

1. **The seven days.** One ribbon a day, Monday to Sunday, the same ribbon as the Day's
   ([the Day](day.md)): the calendar's timed entries planned above, the stays, moves, time aboard and
   calls lived below, the hours on one scale, so the days read against each other. Each day's name is a
   link to its Day. No *now* line: the page is the week's.
2. **Where the week went.** The week draft's numbers, which the code computed from the lines and never
   the model (`extra.numbers`): the hours by place and the threads (a chat, a mail subject, a calendar
   title, a call), each with the lines it rests on, linked to each line as written. Sleep and training
   only on a page that reads tier 3: health is tier 3, a draft that read it is tier 3, and through a
   lower gate that draft is not read at all. Who you spent the week with is under *People who moved*,
   by name: a chat, or a title that names a person, is shown without its count.
3. **Goals.** Each goal open on the Sunday, or touched in the week: the days the week touched it, your
   latest verdict, the verdict the week's draft proposes (in pencil), and the command that gives one of
   the five verdicts, `logbook goal review GOAL advancing|stalled|done|let-go|superseded --period week
   --at SUNDAY` (or `logbook review goal`, the week's sitting). There is no form yet. Under the goals,
   the two honest moves when a goal stalls: **change the days** (the week's one proposal) or **change
   the sentence** (reword it, `goal add … --supersedes GOAL`, or let it go). The page never draws a
   verdict of its own.
4. **Next week.** The week draft's one proposal for next week, in pencil, headed with the model that
   wrote it, with its lines. A proposal only: showing it writes nothing.
5. **The question.** The week's one stale question about a holding or an idea, asked once
   ([the dream](dream.md#journeys-and-weeks)); answer it with `logbook status`, or leave it.
6. **People who moved.** The people whose contacts in this week's draft differ from the week before's,
   the largest change first, five at most: names only, never a count, a direction or a score beside a
   name. Among the people each week's draft counts; a week whose week before has no draft has none.
7. **The plan.** The sprint and the next trip ([the plan](plan.md)), as the plan stood on the week's
   last day the clock has reached: titles and dates, each linked to its line, never to Notion.
8. **Hold.** [Hold](hold.md)'s senders and Drive censuses as they stand: the counts of the reports
   `logbook lab hold census senders` and `drive` last wrote under `state/hold/`, each with its day, and
   only where the page reads every tier the report read; never a file's name or a sender. The page never
   runs a census: run one again and the page follows. On the week page only.

A week with no draft says so in one line, with the command that writes one once its Sunday is over, and
the parts that rest on the draft (2, 4, 5, 6 and the proposed verdicts) are not drawn: nothing is
invented in their place.

## The rules

- **Through the gate.** Every reader on the page reads through the page's tiers: the days, the draft
  (`drafts.for_unit`, as the Sunday's Day reads it), the goals (tier 2), the plan (tier 1), Hold's
  reports (by the tier each says it read). A
  tier-1 page shows the ribbons, the plan and Drive's counts, and no name, goal or sentence of tier 2.
- **Ink and pencil.** The numbers are the code's; the proposal and the proposed verdicts are the
  model's, in pencil, each with its lines. A site built without its drafts (`logbook export site`
  without `--with-drafts`) reads no draft: the page says so in one line and shows no pencil.
- **No number beside a person.** A model's sentence, a thread's title or the question that would put a
  digit beside a person's name is withheld, its row saying so and linking the draft as written.
- **Nothing fetched, nothing written.** One document, one inline stylesheet, no script; the Library's
  [three rules](serve.md#three-rules) hold.

## Later

Time by project (the plan's projects against the lived hours), the sprint's outcomes (done, rolled to
next week, let go: they need the signed day's dispositions in the crossing, RFC 0043 slice C), the
tasks untouched for 90 days, let go together in one decision, and **close the week**: the verdicts,
the kept proposal as an intention for next week's mornings, through the writers that exist.
