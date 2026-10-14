# RFC 0036 — payload profile `draft/v1`: what a model wrote about a unit of the record

Status: draft · 2026-10-13 · comment period: two weeks · one of the four profiles of [RFC 0036](../docs/rfcs/0036-goals-reviews-drafts-chapters.md)

A model's text about one unit of the record, a day, a journey, an event, a week, a month, a year or a chapter, kept so that the page an orchestrator built can be rebuilt from the record alone, and kept under one rule: every sentence points at the line ids it rests on, or is marked unsupported, and a reader never shows an unsupported sentence as fact. A draft is a proposal. Nothing in it is a fact of the record until the owner confirms it through an act of their own: a signed day (RFC 0034), a note (RFC 0010), a review (`review/v1`) or a star (`keeper/v1`, RFC 0024). The draft is never that confirmation.

`draft/v1` is a new profile, not one of the RFC 0031 freezes: its schema may change while RFC 0036 is a draft. What writes it is not fixed here (RFC 0036, open question 2); this page fixes the line.

## Line

`kind` MUST be `draft`. `tier` is the highest tier among the lines the model read (below). `source` MUST be `model:<name>`, the model named as its runner names it (`model:qwen2.5-7b-instruct`); never `manual`, since the owner did not write it, and never an adapter's name. `at` is when the model wrote it; `end` is null.

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"draft/v1"` | MUST | |
| `unit` | string | MUST | one of `day`, `journey`, `event`, `week`, `month`, `year`, `chapter` |
| `subject` | string or array of string | MUST | which one: for `day` the local day `YYYY-MM-DD`, for `week` the ISO week `YYYY-Www`, for `month` `YYYY-MM`, for `year` `YYYY`; for `journey`, `event` and `chapter` the ids of the lines the unit is (the `journey/v1` line, the `event/v1` line or lines of the entry, the `chapter/v1` line), as an array |
| `read_head` | hex sha256 | MUST | the record's head (`logbook.json`) when the model read |
| `read_count` | integer | MUST | how many lines of the unit the model read, under the ceiling it read under |
| `language` | string | MUST | the language of the text, a BCP 47 tag (`en`, `nb`) |
| `segments` | array of object | MUST | the text, in order, each `{ text, evidence }` or `{ text, unsupported: true }` (below); at least one |
| `supersedes` | string | MAY | the id of the earlier `draft` line of the same unit this one replaces |
| `proposals` | array of object | MAY | what the model proposes the owner confirm, beside its text (below); absent when it proposes nothing |

Anything else MAY be kept under `extra`: the prompt's name, the model's parameters, how long it took, how many proposals the writer dropped and why (`dropped`, reason → count).

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

1. **The dedupe key is `(source, unit, subject, read_head)`, and the crossing entry it read under when the draft names one (rule 7).** The same model on the same unit at the same head under the same entry is one draft: a writer that holds one writes nothing and says so. The record moved, or the entry changed, the model runs again, and that is a new line.
2. **A draft is never edited.** A later draft of the same unit carries `supersedes` naming the earlier one. The **standing draft** of a unit is its latest `draft` line not retracted and not named in a later draft's `supersedes`. The earlier text stays in the record, marked.
3. **Every sentence has evidence or a mark.** The rule of RFC 0036 (*The evidence rule*). A reader prints a supported segment with its evidence reachable and an unsupported one set apart, marked, never run into the prose around it, and never as a fact.
4. **A draft is a proposal.** No reader derives a fact from a draft: not a stay, not a person, not a promise, not a goal, not an event. The owner confirms a sentence by confirming the lines it rests on (a signed day whose `confirmed` names them), by writing a note, by reviewing a goal, or by starring a keeper; an unsupported sentence has no lines to confirm and is confirmed by nothing but the owner writing it down themselves.
5. **A draft reads under a ceiling and says so.** `read_count` is the count under the ceiling the writer read under; a draft written through the door is of the lines the door showed, and the page may hold more. A reader that holds the record MAY compare `read_count` with the unit's lines today and say the draft is of a smaller unit.
6. **Evidence is checked.** A writer refuses a segment whose `evidence` names an id that is not a line of the unit it read. A reader that holds the record and finds an id that is not on the unit shows the segment as unsupported and says why.
7. **A draft follows the policy, not the head** (amended 2026-10-13; ADR 0016, *Derived material follows the policy, not the head*). A writer that reads under a crossing entry SHOULD name the entry's version under `extra.policy_version`: the SHA-256, lowercase hex, of the RFC 8785 JSON of `{"max_tier", "model", "until"}` as the entry writes them (`null` for one it does not set). A reader shows a draft only while that entry, as it counts today, allows the draft's `tier`: lowered, expired or removed, the draft is withheld whatever the head, the reader that holds the record says so and shows nothing of the text, and the line stays in the record. A writer that finds the standing draft above the entry, or under another version of it, MAY write the unit again under the entry as it is, superseding it (rule 2).

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

## Notes

- **Why segments and not a text with footnotes.** A reader must be able to withhold a sentence. A text with markers in it needs a parser to find the sentence a marker belongs to; a list of segments needs none, and a second implementation prints the same thing.
- **Why `unsupported` is a key and not an empty list.** An empty `evidence` is what a writer produces by mistake; a key the writer must set is a statement. The rule is that there is no third shape, so a reader has two cases and no guess.
- **Why `source` names the model.** `source` is who observed (SPEC §2). A model's text is the model's observation of the lines; the owner's command ran it, but the owner did not say it, and `manual` would say they did.
- **Why the owner's act is the only confirmation.** Two models agreeing is two proposals. The record's facts are observed lines and the owner's words, and a draft is neither (ARCHITECTURE, layer 5: agents are operators, never authors).
