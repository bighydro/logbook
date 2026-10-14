# RFC 0036 — payload profile `draft/v1`: what a model wrote about a unit of the record

Status: draft · 2026-10-13 · comment period: two weeks · one of the four profiles of [RFC 0036](../docs/rfcs/0036-goals-reviews-drafts-chapters.md) · amendment 1 (the person unit; rule 7 for every unit and through every crossing) 2026-10-13

A model's text about one unit of the record, a day, a journey, an event, a week, a month, a year, a chapter or a person, kept so that the page an orchestrator built can be rebuilt from the record alone, and kept under one rule: every sentence points at the line ids it rests on, or is marked unsupported, and a reader never shows an unsupported sentence as fact. A draft is a proposal. Nothing in it is a fact of the record until the owner confirms it through an act of their own: a signed day (RFC 0034), a note (RFC 0010), a review (`review/v1`) or a star (`keeper/v1`, RFC 0024). The draft is never that confirmation.

`draft/v1` is a new profile, not one of the RFC 0031 freezes: its schema may change while RFC 0036 is a draft. This page fixes the line. `dream day` writes the day's (`docs/dream.md`); the other units have no writer yet (RFC 0036, open question 2).

## Line

`kind` MUST be `draft`. `tier` is the highest tier among the lines the model read (below). `source` MUST be `model:<name>`, the model named as its runner names it (`model:qwen2.5-7b-instruct`); never `manual`, since the owner did not write it, and never an adapter's name. `at` is when the model wrote it; `end` is null.

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"draft/v1"` | MUST | |
| `unit` | string | MUST | one of `day`, `journey`, `event`, `week`, `month`, `year`, `chapter`, `person` (amendment 1) |
| `subject` | string or array of string | MUST | which one: for `day` the local day `YYYY-MM-DD`, for `week` the ISO week `YYYY-Www`, for `month` `YYYY-MM`, for `year` `YYYY`; for `journey`, `event` and `chapter` the ids of the lines the unit is (the `journey/v1` line, the `event/v1` line or lines of the entry, the `chapter/v1` line), as an array; for `person` one canonical person id, as a string (below) |
| `window` | object | MUST for `person` | `{ from, to }`, two local days `YYYY-MM-DD`, both inclusive: the stretch of a person the model read. Absent on every other unit, whose `subject` bounds it |
| `read_head` | hex sha256 | MUST | the record's head (`logbook.json`) when the model read |
| `read_count` | integer | MUST | how many lines of the unit the model read, under the ceiling it read under |
| `language` | string | MUST | the language of the text, a BCP 47 tag (`en`, `nb`) |
| `segments` | array of object | MUST | the text, in order, each `{ text, evidence }` or `{ text, unsupported: true }` (below); at least one |
| `supersedes` | string | MAY | the id of the earlier `draft` line of the same unit this one replaces |
| `proposals` | array of object | MAY | what the model proposes the owner confirm, beside its text (below); absent when it proposes nothing |

Anything else MAY be kept under `extra`: the prompt's name, the model's parameters, how long it took, how many proposals the writer dropped and why (`dropped`, reason → count), and `policy_version`, the version of the crossing entry the writer read under (rule 7).

**A segment** is one object with `text`, a non-empty string, one sentence or a few, and exactly one of:

- `evidence`, a non-empty array of line ids: the lines the text rests on, every one of them a line of the unit the model read; or
- `"unsupported": true`: the text rests on no line. No `evidence` key at all, not an empty one.

A segment with both, with neither, with an empty `evidence`, or with `unsupported` false, makes the line invalid: a writer refuses it, and a reader that meets one anyway treats the segment as unsupported and says the line is malformed.

**A proposal** (amendment of 2026-10-13) is one object, and `kind` says what it proposes; `event` is the only kind so far: an event the model thinks the unit held and the owner may confirm. An event proposal has exactly these keys:

| Key | Type | Meaning |
|---|---|---|
| `kind` | `"event"` | |
| `title` | string | short, non-empty |
| `start`, `end` | RFC3339 UTC with `Z` | the span; `start` before `end`, `start` on the day |
| `place` | string or null | a named place of `places.json` by its name, or an observed place by its id `place:<lat>,<lon>`, as `places review` names a cluster; a place the unit's stays were at |
| `people` | array of string | canonical person ids: entity ids the resolution lines (RFC 0006) name as a person after the alias walk, never the owner; may be empty |
| `evidence` | array of string | the line ids it rests on, non-empty, every one a line of the unit the model read |

A proposal is numbered by its place in the array, from 1. Unlike a segment it has no unsupported form: a writer drops a proposal whose time, place, people or evidence is not of the unit, and MAY count the drops under `extra`. A proposal of another shape makes the line invalid, as a malformed segment does; a reader shows the valid ones and says the line is malformed. A proposal is never a line of its own kind. The owner confirms an event proposal by writing it as an `event/v1` line (RFC 0009), source `owner`, `raw_id` `<draft id>/<number>`, `extra.from` the draft's id; a reader shows a proposal with such a line standing as confirmed, and the event among the day's events. A draft withheld by rule 7 is withheld with its proposals: a reader shows none of them and offers none to confirm; an event the owner confirmed from it before is the owner's line and stays.

## Tier

The highest tier among the lines the model read, by SPEC §4: *derived data inherits the highest tier of its evidence*. The evidence of a draft is every line the model read, not only the lines its segments cite: a model that read a tier-3 line may have written from it in a sentence that cites a tier-1 line, and no reader can tell. So the writer sets `tier` to the highest tier of the `read_count` lines; a draft written through the `mcp` door at a ceiling of 1 is tier 1, and one written on the home machine over a day with a health line is tier 3 and is sealed as tier 3 is (RFC 0029). A writer MAY set a higher tier for a reason it states; it never sets a lower one.

## Rules

1. **The dedupe key is `(source, unit, subject, read_head)`, and the crossing entry it read under when the draft names one (rule 7);** for a person, `(source, unit, subject, window, read_head)` and the entry the same way (amendment 1). The same model on the same unit at the same head under the same entry is one draft: a writer that holds one writes nothing and says so. The record moved, or the entry changed, the model runs again, and that is a new line.
2. **A draft is never edited.** A later draft of the same unit carries `supersedes` naming the earlier one. The **standing draft** of a unit is its latest `draft` line not retracted and not named in a later draft's `supersedes`; a person's is the latest of that subject, whatever its window. The earlier text stays in the record, marked.
3. **Every sentence has evidence or a mark.** The rule of RFC 0036 (*The evidence rule*). A reader prints a supported segment with its evidence reachable and an unsupported one set apart, marked, never run into the prose around it, and never as a fact.
4. **A draft is a proposal.** No reader derives a fact from a draft: not a stay, not a person, not a promise, not a goal, not an event. The owner confirms a sentence by confirming the lines it rests on (a signed day whose `confirmed` names them), by writing a note, by reviewing a goal, or by starring a keeper; an unsupported sentence has no lines to confirm and is confirmed by nothing but the owner writing it down themselves.
5. **A draft reads under a ceiling and says so.** `read_count` is the count under the ceiling the writer read under; a draft written through the door is of the lines the door showed, and the page may hold more. A reader that holds the record MAY compare `read_count` with the unit's lines today and say the draft is of a smaller unit.
6. **Evidence is checked.** A writer refuses a segment whose `evidence` names an id that is not a line of the unit it read (for a person, of the set below). A reader that holds the record and finds an id that is not on the unit shows the segment as unsupported and says why.
7. **A draft follows the policy, not the head** (amended 2026-10-13; ADR 0016, *Derived material follows the policy, not the head*). A writer that reads under a crossing entry SHOULD name the entry's version under `extra.policy_version`: the SHA-256, lowercase hex, of the RFC 8785 JSON of `{"max_tier", "model", "until"}` as the entry writes them (`null` for one it does not set). A reader shows a draft only while that entry, as it counts today, allows the draft's `tier`: lowered, expired or removed, the draft is withheld whatever the head, the reader that holds the record says so and shows nothing of the text, and the line stays in the record. A writer that finds the standing draft above the entry, or under another version of it, MAY write the unit again under the entry as it is, superseding it (rule 2). Amendment 1 adds two things. The rule holds for a draft of every unit, a person's included, and its page says `superseded by policy` where the Day does. And a reader through a crossing holds a draft to that crossing's own ceiling as well, as it counts when the reader serves (its `max_tier` today, 0 past its `until`), never the ceiling the draft was read under: above it, the unit's page through that crossing shows no draft (`draft` is `null`, without the row), the line is counted where the crossing counts what it holds back, and nothing of it crosses, not its id and not its evidence. The owner reading at home crosses nothing, so there the entry alone holds the draft. A draft that names no version, every one written before this rule, is held to the entry by its tier alone.

## Example (synthetic)

A local model drafts Ines Nordmann's Saturday, 13 June 2026 (the day of RFC 0025's shared page), reading under a ceiling of 2: five lines, the morning's steps (tier 3) outside its reading, so the draft is tier 2. The fourth sentence rests on nothing and says so:

```json
{"at":"2026-06-14T06:10:00Z","end":null,"tz":"Europe/Oslo","source":"model:qwen2.5-7b-instruct","kind":"draft","tier":2,
 "payload":{"schema":"draft/v1","unit":"day","subject":"2026-06-13",
 "read_head":"bb97e90d3f946f6cc637e5e223b080ada65e2beb12b07293727e28d2a279b3d8","read_count":5,"language":"en",
 "segments":[
  {"text":"A morning at home, then the afternoon at the boat in Vollen.","evidence":["019cadd3-6bc0-7dcd-9133-0000000000a1","019cadd3-6bc0-7dcd-9133-0000000000a2"]},
  {"text":"One photo from the pontoon, the new mooring lines on.","evidence":["019cadd3-6bc0-7dcd-9133-0000000000a3"]},
  {"text":"You wrote that the engine sounded right for the first time since May.","evidence":["019cadd3-6bc0-7dcd-9133-0000000000a4"]},
  {"text":"Ola came by in the evening.","unsupported":true}]}}
```

## What a Day page shows

The standing draft whose `unit` is `day` and whose `subject` is the day, above the owner's note: before the first `note/v1` line of the day, and before the timeline when the day has none. It is headed as a draft and never as the day:

```
draft · model:qwen2.5-7b-instruct · read at bb97e90d · 5 lines
  A morning at home, then the afternoon at the boat in Vollen.            [a1, a2]
  One photo from the pontoon, the new mooring lines on.                   [a3]
  You wrote that the engine sounded right for the first time since May.   [a4]
  ~ Ola came by in the evening.                                           unsupported
```

The text form prints each segment on its own lines with its evidence after it, the ids shortened as `show` shortens them; an unsupported segment is marked `unsupported` and set apart (a leading `~` in text, a muted block with the word in `serve`), never between two supported segments as if it were one. In `serve` each id is a link to the line. A draft of another unit is for that unit's page (the trip page, the year) and is not on the Day. The draft line is listed on its day among the day's lines too, as every line is (SPEC §3.2.1), with the mark `draft`. After the segments come the proposed events, one row each: a proposal waiting for the owner marked as one (a leading `?` and the word `proposed` in text, greyed in `serve`), one the owner confirmed marked with the line it became, which the Day shows among its events. JSON: `draft`, `null` or `{ line, source, at, read_head, read_count, language, segments, proposals, supersedes }`.

## The person unit (amendment 1)

A draft of one person over a stretch of days answers "what matters to Ola lately?" from what passed between the owner and Ola, and from nothing else. RFC 0036 amendment 1 gives the reasons; the rules are these.

- **`subject`** is one canonical person id: the `entity.id` of `type` `person`, `registry` `logbook` (RFC 0006), that the resolution lines resolve the person to at `read_head`, the primary's after a merge. A writer refuses an id no standing resolution line names, a merged-away id, a place, a company and the owner's `owner_id`.
- **`window`** is the stretch read, two local days, both inclusive. A writer refuses a `from` after `to` and a `to` after the local day of the draft's `at`.
- **The authorized input set** is exactly the lines, not retracted and at or under the ceiling, whose `at` falls on a day of the window and on which the person is a *counterpart* (a `message/v1` they sent, or the owner sent in a direct chat with them; a `call/v1` whose `counterparty` resolves to them; a `mail/v1` from them or addressed to them), an *attendee* (an `event/v1` they attend and did not decline) or a *speaker* (a `transcript/v1` they are a participant of). These are the person page's channels `messages`, `calls`, `mail`, `calendar` and `transcripts` (`docs/people.md`). A line that merely mentions them is never in it: a note naming them, a mail about them, someone else's message in a group they are in, a tagged face, a promise, a stay, a resolution line, a draft.
- **The model reads** the set and the person's label, nothing else of the record; `read_count` is the size of the set. The label's line counts toward the tier and is never evidence.
- **Evidence outside the set is invalid** (rule 6): a writer never writes it, and a reader shows such a segment as unsupported, saying the id is not one of the person's lines in the window.
- **It shows on the person page**, after the numbers and before the shared days, headed `draft · <source> · read at <8 hex> · <read_count> lines · <from> – <to>`; never on the Day, whose draft is of unit `day` alone. It follows rule 7 as the Day's draft does: above the entry it was read under, as that entry counts today, the person page says `superseded by policy` and why (`draft_withheld`) and nothing of its text, a reader through a crossing hides it, and the door holds back its line, as it holds back every `draft` line above the entry, and counts it.

A local model drafts what has passed between Ines Nordmann and Ola Nordmann since the middle of July, under the `dream` entry `{"max_tier": 2, "until": "2026-12-31", "model": "qwen2.5-7b-instruct"}`, whose version it records (rule 7): eleven lines in the set, mail, messages and one call, so the draft is tier 2. The third segment rests on nothing and says so:

```json
{"at":"2026-10-12T06:20:00Z","end":null,"tz":"Europe/Oslo","source":"model:qwen2.5-7b-instruct","kind":"draft","tier":2,
 "payload":{"schema":"draft/v1","unit":"person","subject":"019cadd3-6bc0-7dcd-9133-000000000501",
 "window":{"from":"2026-07-14","to":"2026-10-11"},
 "read_head":"34cb1808a3e7cf1e88351f1dedff1cfbc4ab0a3b1846d04150b8b707cc1d0f2c","read_count":11,
 "language":"en",
 "segments":[
  {"text":"Most of what passed between you since July is the boat: the engine in Bodø, then the tow home.","evidence":["019cadd3-6bc0-7dcd-9133-0000000005a1","019cadd3-6bc0-7dcd-9133-0000000005a2"]},
  {"text":"Ola asked twice in September whether you will keep the berth in Vollen for next summer.","evidence":["019cadd3-6bc0-7dcd-9133-0000000005a3","019cadd3-6bc0-7dcd-9133-0000000005a4"]},
  {"text":"The cost of the rebuild seems to weigh on you both.","unsupported":true}],
 "extra":{"policy_version":"7ec8517a06f1a2c18195832423682f4389056f84cacb94d2922549e4c1009aaf"}}}
```

## Notes

- **Why segments and not a text with footnotes.** A reader must be able to withhold a sentence. A text with markers in it needs a parser to find the sentence a marker belongs to; a list of segments needs none, and a second implementation prints the same thing.
- **Why `unsupported` is a key and not an empty list.** An empty `evidence` is what a writer produces by mistake; a key the writer must set is a statement. The rule is that there is no third shape, so a reader has two cases and no guess.
- **Why `source` names the model.** `source` is who observed (SPEC §2). A model's text is the model's observation of the lines; the owner's command ran it, but the owner did not say it, and `manual` would say they did.
- **Why the owner's act is the only confirmation.** Two models agreeing is two proposals. The record's facts are observed lines and the owner's words, and a draft is neither (ARCHITECTURE, layer 5: agents are operators, never authors).
- **Why a person's set is contact and not mention (amendment 1).** The lines where a person is on the other end are found by refs and resolution lines, the same way in every implementation; a mention is found by matching text, which no two do alike. And a model that may read every line naming someone has, in practice, read the record.
- **Why hide by today's ceiling (amendment 1).** A ceiling is what the owner lets a destination see now (ADR 0016). A draft that kept the ceiling it was read under would be the one line a lowered ceiling did not reach; hiding it writes nothing, and raising the ceiling shows it again.
