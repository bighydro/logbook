# The dream's prompt

`logbook dream` sends a model two messages: the prompt, which is the file
[`logbook/contrib/dream-prompt.md`](https://github.com/bighydro/logbook/blob/main/logbook/contrib/dream-prompt.md)
in the package with the day and the language filled in, and the day's material as JSON. This page
explains the prompt; `logbook dream day DAY --show-prompt` prints both as they go. The prompt's name,
`dream-day/1`, is kept in every draft's `extra.prompt`, so a draft says which wording wrote it; a
change to the prompt that changes what a draft holds bumps the number.

## What it asks for

One JSON object with five keys, each a list of segments, in the order the Day prints them:

| Key | What | How many |
|---|---|---|
| `day` | the day in one paragraph: where the owner was, who was there, what was done | two to five sentences |
| `threads` | the threads the day moved: a conversation continued, a plan made, a trip under way, a promise given or kept | at most four |
| `questions` | questions for the owner's reflection, each resting on something the day holds | exactly two |
| `people` | the people the model thinks were there, one sentence each, with the items that show it | as many as the material names |
| `promises` | the promises it thinks were made or kept that day, in the words the material gives | as many as the material shows |

A segment is `{"text": "...", "evidence": ["L1", "L2"]}` or `{"text": "...", "unsupported": true}`.
The references are the ones the material carries; the record turns them into line ids before the
draft is written and keeps nothing of the prompt ([the dream](dream.md), *the evidence rule*).

## The rules it gives the model

1. **Evidence or a mark.** Every sentence names the items it rests on, or says `unsupported`. Never an
   invented reference, never an item cited for a sentence it does not support. The record checks this
   afterwards and refuses an answer that is mostly unsupported, so the rule is enforced, not only asked.
2. **Only what the material says.** No guessed feelings, no weather the day has no line for, nothing
   where the record is silent; where it is silent the draft is silent or asks.
3. **The names as given.** No nicknames, no titles, no guess at who someone is.
4. **Brief and plain.** No headings, no bullets inside the text, no greeting and no sign-off.

The prompt also says the day (`$day`, `$weekday`, `$tz`) and the language to write in (`$language`,
a BCP 47 tag, and `$language_name`): the language most of the day's own text is in, as the dream
decided it from the notes, messages, titles and subjects of the day.

## The material

The second message is the material as JSON: `day`, `weekday`, `tz`, `max_tier` (the ceiling it was
read under), `night_before` and `night_after` (where, home or away, the references), `country`,
`all_day`, `timeline` (one entry per stay, move, stop or flight as the Day shows it, with its events,
transcripts, mail threads, calls, photos as a count, keepers and who was there, confirmed and proposed,
each with references), `unplaced`, `messages` (by counterpart: the count, the references and the
texts), `notes` (in full), `commitments`, `health` (only when tier 3 is under the ceiling) and `signed`
(when and the note you wrote on signing). Every item carries `ref`, a reference such as `L12`; a
reference stands for one line id of the day, and only lines of the day get one, so the model cannot
cite a line from the night before even though the material describes that night.

## Why a file in the package

So that the words a model is given are versioned with the code that checks its answer, readable
without running anything, and the same on every machine: an orchestrator that rebuilds a Day from the
record and a second implementation that writes drafts can read the same prompt and know what a
`dream-day/1` draft was asked for.
