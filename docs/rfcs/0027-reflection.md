# RFC 0027 — Reflection: the digest's closing question comes from the record

Status: draft · 2026-10-03 · comment period: two weeks

The digest (`logbook digest`, [docs/digest.md](../digest.md)) ends with one question the owner can answer in a word. Until now the question was chosen in code, by the first of seven rules that applied. This RFC moves the choice into the record: the questions live in `policy/questions.json`, a setting the owner edits like every other policy file; each carries the facts of the day it asks on and a weight; the digest reads the day's facts, draws one question whose conditions hold, never the same one two days running, and remembers what it asked. Nothing about the record's lines changes: no new kind, no envelope change, no spec version bump. The mechanism is specified here; the content of the bank is not, and is explicitly left to a future author (the last section).

## Why

The seven rules were data-quality nudges — *was the tracker switched off, was this person with you, did the meeting happen* — and they were right to be there, since the day closes itself on the owner's answer (ADR 0005). But a question is also the one moment the digest speaks to the owner rather than about the day, and what it asks shapes what the owner keeps: gratitude, savouring, people, place, body. Which questions do that well is a research question, with a literature, and not one a coding agent should settle inside a Python module. So the mechanism and the content part ways: the code decides *how* a question is chosen, the record decides *which* questions exist, and a person decides *what they say*.

## The file

`<root>/policy/questions.json` is a JSON object with one key, `questions`, a list of question objects in the order the owner keeps them. `logbook init` does not write it; the first run of `logbook digest` or `logbook questions` writes the defaults, and nothing ever overwrites an edit (the rule every policy file follows). A file that is not this shape stops the digest with the file's path and the key at fault, never a traceback and never a silent default.

| Field | Type | Req | Meaning |
|---|---|---|---|
| `id` | string | MUST | the question's own name, unique in the file; what the state remembers and what `questions disable` takes |
| `text` | string | MUST | the question, in English; may carry placeholders (below) |
| `text_de` | string | MAY | the same question in German; the digest prints `text` today and a reader that knows the owner's language may prefer this |
| `kind` | string | MUST | one of `gratitude`, `savouring`, `people`, `place`, `body`, `open` |
| `when` | list of strings | MUST | the conditions: each a fact name of the table below, or one prefixed `!` for a fact that must not hold; every condition must hold for the question to be a candidate; an empty list is a question that may always be asked |
| `weight` | number > 0 | MUST | the question's share of the draw among the candidates of the day |
| `source` | string | MUST | free text: the research, the book, the person the question comes from; **empty in every default** |
| `enabled` | boolean | MAY | `false` keeps the question in the file and never asks it; absent is `true` |

Absent `kind`, `when`, `weight` and `source` are read as `open`, `[]`, `1` and `""`, so a hand-written entry needs only an id and a text; a present value that is not what it should be is refused.

### Placeholders

A text may hold one of these, in braces, filled from the day: `{person}` (the person seen again after a long while, else the first confirmed present), `{proposed}` (the first person proposed and confirmed nowhere), `{place}` (the first stay of the day that is not home), `{asset}` (the asset the owner was aboard), `{missing}` (the first usual source with no line), `{promise}` (the first open promise due, quoted as the digest prints it), `{event}` (the title of the first calendar entry the track placed nowhere, quoted). A question whose placeholder the day cannot fill is not a candidate that day, whatever its `when` says; a placeholder outside this list is refused when the file is read.

## The day's facts

The digest already reads the Day, its shape, the promises due, the gaps and tomorrow's entries; the facts are read from those parts and nothing is derived anew for them, with one exception, the reunion, read through the `days` reader over the window before the day. Every fact is a yes or no.

| Fact | Holds when |
|---|---|
| `logged` | the day has a line at all |
| `travelled` | a flight on the day, or the night after is not at home |
| `flew` | a `flight/v1` line standing on the day |
| `aboard` | a stay aboard an asset, or the night after aboard one |
| `night_home` | the night after is at home (the 400 m rule of the Day) |
| `night_away` | the night after is at a stay that is not home |
| `night_in_transit` | the night after is at no stay |
| `company` | somebody is confirmed present |
| `alone` | a logged day with nobody confirmed and nobody proposed |
| `proposed` | somebody is proposed and confirmed nowhere (a face, an all-day attendee) |
| `reunion` | somebody confirmed present was confirmed on no day of the ninety before, and the record resolved them before those ninety days (a resolution line older than the window; a person met for the first time is not seen again) |
| `photos` | a photo attached to the day's rows |
| `notes` | a note attached to the day's rows |
| `long_sleep` | the night's sleep is nine hours or more (the Day's health line) |
| `short_sleep` | the night's sleep is under six hours |
| `gap` | a usual source has no line (the `sources --gaps` rule the digest already applies) |
| `promise_due` | an open promise is due on the day or before |
| `event_unplaced` | a calendar entry fell inside no row |
| `tomorrow_busy` | tomorrow has three timed entries or more |
| `weekend` | a Saturday or a Sunday in the record's zone |

The thresholds (90 days, 9 h, 6 h, 3 entries) are the reader's constants, named in `logbook/contrib/questions.py`; a fact name the file uses that this table does not have is refused when the file is read, so a typo is seen the day it is made and not as a question that never comes. Under `--json` the digest's `question` carries `facts`, the names that held, so the owner writing a `when` can see what a day looked like to the chooser.

## The choice

1. **Candidates.** The enabled questions whose every condition holds on the day's facts and whose placeholders the day fills.
2. **Not two days running.** The ids asked on the other days the state remembers (the last seven) are left out first. When nothing remains, only the ids asked on the day before and the day after are left out, so a question asked within the week may return, but never the one asked yesterday. When nothing remains even then, the digest asks `Anything to add?` — a text that belongs to no id, and is not remembered.
3. **The draw.** One candidate by weight, with a generator seeded by the day, so the same day with the same bank and state draws the same question, and a test can pin it.
4. **Asked once, it stands.** A day whose question the state remembers gets that question again when the day is read again, as long as it is still enabled and still fills; the digest of a day does not change under the owner's feet because a later day was read in between.

The state is `<root>/state/questions.json`, `{"asked": [{"day": "2026-06-10", "id": "gratitude-day"}, ...]}`, the last seven days by day. It is bookkeeping beside the record, like a sync watermark: never a line, never backed up with the record, and losing it only lets a question repeat. A state file that is not JSON or not this shape is read as empty.

## The command

```bash
logbook questions list [--json]          # one line per question: id, kind, weight, when, text; (disabled) when it is
logbook questions add ID --text TEXT --kind KIND [--when FACT]... [--weight N] [--source TEXT] [--de TEXT]
logbook questions disable ID             # kept in the file, never asked
```

`add` refuses an id the file already has, a fact the table above does not know, a kind outside the six, a weight of zero or less and a placeholder the digest cannot fill; nothing is written when it refuses. There is no `enable`: the owner sets `"enabled": true` in the file, which is theirs. There is no `remove`: a question the owner no longer wants is disabled, so its id stays taken and the state's memory of it stays meaningful.

## What does not change

The envelope, the chain, the kinds and the spec version (SPEC §2–3) are untouched: a question is never a line, an answer is never written by the digest. The digest's text and Markdown are the same lines as before, with the question last after a blank line; `--json`'s `question` is now `{"id", "kind", "text", "facts"}` where it was `{"about", "text"}`. The digest still sends nothing and schedules nothing (ADR 0005: one nudge, one channel; delivery is a later layer). It now writes two files beside the record on first use — the default bank and the state — where it wrote none; both are settings and bookkeeping, not record, and the chain head is unchanged by any digest.

## The question bank — to be written

The content of the bank is not this RFC's to decide and is left to a future author, who writes a section here with the questions, their kinds, their conditions and weights, and in `source` the research each one rests on, so that an owner who disables a question knows what they are declining. **Author: to be named by the captain when the work is taken on; until then this section holds the schema and three placeholders and nothing else.** The defaults the code writes today are the seven nudges the digest used to choose in code, each as a question with the condition that chose it, plus the three placeholders below; every `source` is empty, which is the honest state of the research behind them.

The schema, as one entry:

```json
{
  "id": "<name, unique>",
  "text": "<the question, English>",
  "text_de": "<the same, German; optional>",
  "kind": "gratitude | savouring | people | place | body | open",
  "when": ["<fact>", "!<fact>"],
  "weight": 1,
  "source": "<the research behind it; empty until it is written>",
  "enabled": true
}
```

Three placeholder examples, which are placeholders and not the bank:

```json
{"id": "gratitude-day", "text": "What were you glad of today?", "kind": "gratitude", "when": ["logged"], "weight": 1, "source": ""}
```

```json
{"id": "savouring-new", "text": "What did you see today that you had not seen before?", "kind": "savouring", "when": ["travelled"], "weight": 2, "source": ""}
```

```json
{"id": "people-reunion", "text": "How was it, seeing {person} again?", "kind": "people", "when": ["reunion"], "weight": 4, "source": ""}
```

What the future author decides: the questions themselves; whether a kind should be asked more on some days than others (the weights); whether a question should rest a while after it is asked (the no-repeat window, seven days today, is a constant the mechanism can make a setting when the content asks for it); and whether `text_de` or another language should be what the digest prints, which is a setting of the record's owner, not of the bank.
