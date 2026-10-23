# The letter

`logbook export letter FROM TO` reads a range of your signed days back as one letter: a single HTML
file to print from the browser or hand to someone, and the same content as Markdown. It is the press's
first object: what you kept of those days, in your words, with the dream's story beside them in pencil.

```bash
logbook export letter 2026-06-08 2026-06-21 --to "Kari Nordmann" --front front.md --dry-run   # count only
logbook export letter 2026-06-08 2026-06-21 --to "Kari Nordmann" --front front.md
logbook export letter 2026-06-08 2026-06-21 --unit week --paper letter
logbook export letter 2026-06-01 2026-06-30 --unit month --card                                # the month card
```

It writes three files into `--out DIR` (default `<root>/export/letter/<FROM>_<TO>_<unit>/`, `_card`
after it for the month card): `letter.html`, `letter.md` and `manifest.json`. The folder is replaced
whole by the next letter written there; a folder that holds anything else is refused unless `--force`.
A range with no day to send (no signed day in it, or no journey) is refused, and nothing is written.

## What is in it

First a front page: the title (`--title`, else the range in words), whom it is for (`--to NAME`) and,
with `--front FILE`, your own words, exactly as the file has them. Then one page per unit of the range,
`--unit day` (the default), `week` (ISO weeks), `month` (calendar months) or `journey` (each trip, a run
of nights away, as `show trips` derives it; days outside a journey are left out and counted). Each page
holds, when the unit has it:

| Part | Where it comes from | How it is set |
|---|---|---|
| the story | the unit's standing draft (`logbook dream`): a day's `story` part (RFC 0043 §4.3) or, from dream-day/3, its `day` part, a week's `time` and `personal`, a journey's `journey`; only the sentences that name their evidence, and only when every day the draft is about goes in (a week with an unsigned day, or one that runs past the range, goes without its story) | pencil, set apart, marked *a model's draft, not the owner's words*, with the model's name |
| your words | each day's reflection (`logbook day reflect` or the Day page, the latest one standing) | ink, a serif; one an agent wrote through the door (`note_day`) is shown with its source, in the record's face, never in ink |
| starred | the lines you starred (`logbook star`), with the star's note; a starred note in full | the record's face |
| photos | the photos you starred, embedded when this machine's attachment store holds a JPEG or a PNG that, stripped of what the camera wrote beside the pixels, is at most **256 KiB (262,144 bytes)**; any other is named, never drawn and never copied | |
| goals | the reviews of your goals standing on the unit's days (`logbook goal review`), the goal's text, the verdict, the period and your note | |
| with | the people confirmed present or whom you said were there (`logbook with`), by name only | never a number beside a name |
| where | the places stayed at, in words (a named place, the asset aboard, `near <place>`, a city), and the flights | flight numbers in mono |

There is no image library among the record's tools, so the letter does not resize: what it embeds is
the stored image with its metadata taken out, every pixel as it was. From a JPEG it drops the APP1 to
APP15 segments (EXIF with the position and the camera, XMP, the maker's notes) and the comments; from a
PNG every chunk but those that draw it (no text, no `eXIf`, no time). The browser scales it to the
page. A photo over the cap once stripped, a GIF or a WebP (which it does not strip), one the store does
not hold (a HEIC, a library's own path, an asset only Immich has) or a sealed one this machine cannot
open is named instead. The stored file is never copied beside the letter.

## The month card

`--unit month --card` makes one page per month and nothing else: the starred photo of each starred day
as a grid (the first the store can draw), how many days of the month you signed, the goals kept (the
goals reviewed `done` in the month), the people, and one sentence of yours chosen by rule: the first
sentence of the longest reflection in your hand on a signed day of the month (the earlier day when two
are as long).
No story, no starred lines, no places.

## What may leave

A letter is a crossing like every export ([the crossing](crossing.md),
[ADR 0016](adr/0016-tier-crossing-policy.md)): it reads the `letter` entry of `policy/crossing.json`,
which you write and the program never does:

```json
{"letter": {"max_tier": 2, "until": "2026-12-31"}}
```

Without the entry the export refuses in one sentence and names the entry to add; an entry past its
`until` day counts as `max_tier` 0 and refuses too. The ceiling holds every line the letter reads: the
day's lines, the drafts, the stars, the goals and the names. A name is the resolution line that gives
it, so under `max_tier 1` your reflections, the dream's drafts and the people's names stay home, and the
dinner you starred goes. Tier 3 never goes by default, whatever the entry says; `--tier 1,2,3` takes it
under an entry of 3 and is refused under a lower one. A draft also follows the `dream` entry it was
written under ([the dream](dream.md)), as on the Day.

Only the days you have signed go in (`logbook day sign`, RFC 0034) unless you type `--unsigned`.

`manifest.json` says what went in and what stayed home, counts only: the units and the days, the
reflections, stories, starred lines, photos embedded and named, the reviews, and what was held back
(lines above the ceiling, unsigned days, drafts above the letter's tier and drafts the `dream` entry
holds, each counted apart, photos over the cap or not on this machine, people without a name under the
ceiling). With `--to` it names the person the letter is for. Then one `crossing/v1` line goes into the
record, destination `letter`, with the window, the tiers, the counts, the entry in force, the
manifest's digest and, with `--to`, the name. A name is tier 2 in your record, so the line is tier 2
when `--to` names someone, and tier 1, as every export's line, when it does not. It is the only thing
the command writes to the record.

`--unit`, `--title`, `--front`, `--paper` and `--card` are the letter's own: any other export refuses
them in one sentence.

## Printing it

Open `letter.html` in a browser and print. The page is set for paper with CSS `@page`: A5 by default,
US letter with `--paper letter`, a page break before every unit. It uses three hands, as the Day page
does: your words in a serif, the record in the system face, numbers in mono, and the model's story
apart in pencil. The fonts are the system's; the file fetches nothing, carries no script and no link,
and its photos are inside it. It reads on a phone too (390 px wide) and has nothing to tap.

## What it costs

The range is read once per 31 days (a journey letter once for the whole range, as the trip reader
needs it whole), located through the index, and each kind the letter quotes is one indexed query of
the range. The drafts, the goals and the names are read whole, as the Day reads them: a line per unit
dreamed, per goal, per name, not per observation. Nothing scans the log: a letter costs what its own
days hold, not the size of the record. A year of a dense tracker is a year's lines read; a month is a
month's.
