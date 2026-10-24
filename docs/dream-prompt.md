# The dream's prompt

`logbook dream` sends a model two messages: the prompt, which is the file
[`logbook/contrib/dream-prompt.md`](https://github.com/bighydro/logbook/blob/main/logbook/contrib/dream-prompt.md)
in the package with the day and the language filled in, and the day's material as JSON. This page
explains the prompt; `logbook dream day DAY --show-prompt` prints both as they go. The prompt's name,
`dream-day/4`, is kept in every draft's `extra.prompt`, so a draft says which wording wrote it; a
change to the prompt that changes what a draft holds bumps the number (`dream-day/2` added the proposed
events, so a `dream-day/1` draft has none; `dream-day/3` added rule 5, agents; `dream-day/4` the
goodnight story in the `day` paragraph's place, the lenses, learned, decided, the ideas, the photo of
the day, the links, one question where there were two, rules 6 and 7, and RFC 0043 §7's voice, [the
dream](dream.md#the-dream-learns-dream-day4)).

## What it asks for

One JSON object, every key but the last two a list of segments, in the order the Day prints them, and
the last two the proposed events and links:

| Key | What | How many |
|---|---|---|
| `story` | the goodnight story: second person, past tense, calm, concrete, in the order it happened, ending where the day ended; never a line about tomorrow, which the reader computes | five or six sentences |
| `lens:<id>` | one per lens of the material's `lenses`: the lens's answer from the day; an empty list when the day gives nothing for it, never a sentence saying so | one |
| `threads` | the threads the day moved: a conversation continued, a plan made, a trip under way, a promise given or kept | at most four |
| `learned` | what the day shows was learned | one sentence each |
| `decision` | what the day shows was decided | one sentence each |
| `ideas` | an idea of the material's `named` the day moved, each segment with `entity`, the idea's id | one sentence each |
| `questions` | a question for the owner's reflection, resting on something the day holds | exactly one |
| `people` | the people the model thinks were there, one sentence each, with the items that show it | as many as the material names |
| `promises` | the promises it thinks were made or kept that day, in the words the material gives | as many as the material shows |
| `photo` | the photo of the day from the material's `photos` (own camera first, starred first): a one-line reason, its evidence that photo's one reference | one, or none |
| `events` | the events it thinks the day held that the calendar does not have: `{title, start, end, place, people, evidence}`, the place a stay's `place`, the people ids from the material's `people`, never a name | at most four |
| `links` | lines of the day that belong to an idea or an org of `named`: `{entity, text, evidence, note?}`, `entity` an id the material gave | at most four |

A segment is `{"text": "...", "evidence": ["L1", "L2"]}` or `{"text": "...", "unsupported": true}`.
The references are the ones the material carries; the record turns them into line ids before the
draft is written and keeps nothing of the prompt ([the dream](dream.md), *the evidence rule*). A
proposed event that names a time, a place, a person or a reference the material does not give is
dropped and counted ([the dream](dream.md#proposed-events)).

## The rules it gives the model

1. **Evidence or a mark.** Every sentence names the items it rests on, or says `unsupported`. Never an
   invented reference, never an item cited for a sentence it does not support. The record checks this
   afterwards and refuses an answer that is mostly unsupported, so the rule is enforced, not only asked.
2. **Only what the material says.** No guessed feelings, no weather the day has no line for, nothing
   where the record is silent; where it is silent the draft is silent or asks.
3. **The names as given.** No nicknames, no titles, no guess at who someone is.
4. **Brief and plain.** No headings, no bullets inside the text, no greeting and no sign-off.
5. **Agents are not people.** A counterpart marked `agent` is a program the owner runs (a Telegram
   bot, a coding assistant) and a text marked `machine` is what it wrote ([your own
   agents](adapters/agents.md)): never one of the `people`, and its words never the owner's or anyone's
   promise. The owner's own words to it are the owner's.
6. **Ids from the material.** An idea, an org or a goal by an `id` of `named` or `for.goals`, a person by
   one of `people`, a photo by a reference of `photos`; never a made-up id, never a name in its place.
7. **Intention is not a verdict.** `for`, the chapter and the goals, is what the day was meant for; one is
   named only where a line touches it, and the draft never says the day was good, on track or well
   spent.

Then the voice of RFC 0043 §7, word for word: never moralise and never flatter; every number one the
material gave; an inference says so, in the sentence; at most one proposal of change beside the
proposals to confirm; one question; the day's language; the story calm, concrete, short.

The prompt also says the day (`$day`, `$weekday`, `$tz`) and the language to write in (`$language`,
a BCP 47 tag, and `$language_name`): the language most of the day's own text is in, as the dream
decided it from the notes, messages, titles and subjects of the day.

## The material

The second message is the material as JSON: `day`, `weekday`, `tz`, `max_tier` (the ceiling it was
read under), `night_before` and `night_after` (where, home or away, the references), `country`,
`all_day`, `timeline` (one entry per stay, move, stop or flight as the Day shows it, with its events,
transcripts, mail threads, calls, photos as a count, keepers and who was there, confirmed and proposed,
each with references and, for a canonical person, the `person` id; a stay or stop also its `place`, a
named place's name or `place:<lat>,<lon>`), `unplaced`, `messages` (by counterpart: the count, the
references, the texts and the counterpart's `person` id when the record resolves one; `agent` on a
counterpart that is one of the owner's agents, `machine` on a text it wrote), `notes` (in full),
`commitments`, `photos` (own camera first, then starred, each `ref`, `at`, `provenance`, `starred`),
`people` (every canonical person the material names, `id` and `name`; never the owner), `for`
(`chapter` and `goals`), `named` (the ideas and orgs the owner named, `id`, `kind`, `name`) and `lenses` (`id`, `text`),
`health` (only when tier 3 is under the ceiling) and `signed` (when and the note you wrote on
signing). Every item carries `ref`, a reference such as `L12`; a
reference stands for one line id of the day, and only lines of the day get one, so the model cannot
cite a line from the night before even though the material describes that night.

## Why a file in the package

So that the words a model is given are versioned with the code that checks its answer, readable
without running anything, and the same on every machine: an orchestrator that rebuilds a Day from the
record and a second implementation that writes drafts can read the same prompt and know what a
`dream-day/4` draft was asked for.

## The journey's and the week's

A journey and a week have prompts of their own beside it,
[`dream-journey-prompt.md`](https://github.com/bighydro/logbook/blob/main/logbook/contrib/dream-journey-prompt.md)
(`dream-journey/1`) and
[`dream-week-prompt.md`](https://github.com/bighydro/logbook/blob/main/logbook/contrib/dream-week-prompt.md)
(`dream-week/2`), with the same first rule, evidence or `unsupported`, and one more: numbers are given,
never made. A figure is written only as an item it cites gives it, never added up, rounded or
estimated, and a day's or a call's `drafted` text, a model's words, never lends one; the code marks a
sentence that breaks it. The week's says too that no number stands beside a person (its third rule,
since `dream-week/2`): a sentence that names one and writes a figure is held ([Journeys and weeks](dream.md#journeys-and-weeks)). The journey's asks for
eight lists: `journey`, `days`, `places`, `people`, `decisions`, `promises`, `photos` (the ones to star,
at most six) and `name` (one). The week's asks for six: `time`, `energy` (empty when the material says
`no data`), `people`, `goals` (`{goal, disposition, text, evidence}`, one per goal the week holds
anything for), `next_week` (exactly one) and `personal`, and says, as a rule of its own, never moralise.
`--show-prompt` prints either as it goes.
