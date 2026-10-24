# The week

`logbook serve` has a page for every ISO week, `/week/2026-W25`: the Sunday's week draft
([`dream week`](dream.md#journeys-and-weeks)) grown into a page, beside the seven days it covers. Every
Day links to the week it is in (the pager under its date), and so does the Sunday's week draft. The
week's own pager links the week before and after while they hold a day of the record (or today); past
its first and last week they are named, not linked. At its foot, **Close the week**: one form, no
script, through the writers that exist ([below](#close-the-week); RFC 0043 §8, the second part).

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
   --at SUNDAY` (or `logbook review goal`, the week's sitting), which [Close the week](#close-the-week)
   gives on the page. Under the goals, the two honest moves when a goal stalls: **change the days**
   (the week's one proposal) or **change the sentence** (reword it, `goal add … --supersedes GOAL`, or
   let it go). The page never draws a verdict of its own.
4. **Next week.** The intention you kept on the Sunday, in ink, when you kept one; and the week draft's
   one proposal for next week, in pencil, headed with the model that wrote it, with its lines. A
   proposal only: showing it writes nothing.
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
- **No number beside a person.** A model's sentence, a thread's title, the question or a kept intention
  that would put a digit beside a person's name is withheld, its row saying so and linking the line as
  written; the field of Close the week is left empty rather than hold it.
- **Nothing fetched, nothing written until you press.** One document, one inline stylesheet, no
  script; the Library's [three rules](serve.md#three-rules) hold. Reading the page writes nothing; only
  Close the week does, and only what you chose.

## Close the week

At the foot of the week, on `logbook serve` (a static site carries no form), and only where the page
reads tier 2: the goals and the intention are your own words. One form and one button. Each control
has, beside it, the command that writes the same line, byte for byte:

| On the page | The command beside it |
|---|---|
| each goal open on the Sunday: one choice of five, `advancing`, `stalled`, `done`, `let-go` or `superseded` (or *no verdict*, where it starts), and your words on it | `logbook goal review GOAL VERDICT --period week --at SUNDAY --note "…"` |
| *change the sentence*, when a goal stalls: the goal's page, and the command written out with its id and horizon | `logbook goal add "…" --horizon year --supersedes GOAL` |
| *change the days*, when a goal stalls: next week's intention, the field under the goals, and **Keep these words as next week's intention** | `logbook day reflect SUNDAY --intention "…"` |

```
Close the week
  Goals
    Sail to Lofoten and back this summer.
      (•) no verdict  ( ) advancing  ( ) stalled  ( ) done  ( ) let-go  ( ) superseded
      [your words on it, if any]
      logbook goal review 019c… advancing|stalled|done|let-go|superseded --period week --at 2026-06-21 --note "…"
      When it stalls: change the days, keep next week's intention below; or change the sentence,
      reword it: logbook goal add "…" --horizon year --supersedes 019c…
  Next week's intention
    The week's proposal is in the field, pencil until you keep it; change the words first if they need it.
    [Send Kari Nordmann the harbour map.]
    [ ] Keep these words as next week's intention
    logbook day reflect 2026-06-21 --intention "…"
  [Close the week]
```

- **A verdict** is one `review/v1` line on the goal, for the period `week`, at the Sunday: now when you
  close the week on the Sunday, else the Sunday's last minute ([goals](goals.md)). A goal reviewed
  already on a day of the week (by `review goal`, `goal review`, or here) shows its verdict and no
  choice: the same verdict on the same day again writes nothing, and another is refused.
- **The intention** is one `note/v1` line labelled `intention` on the Sunday, source `reflect`, tier 2,
  your words as one line. Once kept, the words are shown in ink above an empty field (other words
  kept there take their place); before, the field holds the week draft's proposal when it is shown and
  supported (pencil until you keep it), else nothing; it is written only when
  *Keep* is ticked. The same words again write nothing; other words are a new line whose `supersedes`
  names the first, so one intention stands for a week, never two. Next week's mornings show it under
  *For*, in ink, with its Sunday, in place of the pencil ([the Day](day.md#the-morning)); this page shows
  it under *Next week*.
- **One press, all or nothing.** Every verdict and the intention are checked before the first line is
  written, under one writer lock: a sixth word, a goal that is no goal, your words on a goal given no
  verdict, an empty intention, a second verdict for the week, or a sealed record on a machine without
  its identity each refuse the whole press (a 400, its sentence naming what and why), and nothing is
  written. Another command writing the record is the 409 of every act, your words kept in its form.
- **The gate** is every act's ([serve](serve.md)): from this machine, through the server's own pages,
  or from your phone once `logbook setup phone` names it; anything else is a 403 and nothing written.
- **The week closes on its Sunday.** Before its Sunday the part says when it closes and carries no form;
  `day reflect` refuses a day ahead of today, or one that is not a Sunday.

From the command line, the same week closed:

```
$ logbook goal review 019c… stalled --period week --at 2026-06-21 --note "The boat is on land."
$ logbook day reflect 2026-06-21 --intention "Send Kari Nordmann the harbour map."
kept the intention for the week after 2026-W25 as #412 note/v1 (intention, source reflect, tier 2) on 2026-06-21
```

`day reflect SUNDAY --intention` is the command because an intention is a note in your words on a named
day, and `day reflect` is the command that writes those (`notes.write`, source `reflect`). It stands
alone: a reflection, `--sign` or `--at` beside it is refused.

## Later

Time by project (the plan's projects against the lived hours), the sprint's outcomes (done, rolled to
next week, let go: they need the signed day's dispositions in the crossing, RFC 0043 slice C), and the
tasks untouched for 90 days, let go together in one decision.
