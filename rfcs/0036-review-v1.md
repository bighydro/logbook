# RFC 0036 — payload profile `review/v1`: the owner's verdict on a goal at a date

Status: draft · 2026-10-13 · comment period: two weeks · one of the four profiles of [RFC 0036](../docs/rfcs/0036-goals-reviews-drafts-chapters.md)

What became of a goal, said by the owner on a date, for a period: advancing, stalled, done, let go, or superseded by a reworded one. The goal line is never edited; the verdict is a line of its own, and a later verdict on the same goal stands over it. A review may be written long after the date it is about: the envelope's `at` is the date, and `recorded_at` says when the owner wrote it.

`review/v1` is a new profile, not one of the RFC 0031 freezes: its schema may change while RFC 0036 is a draft.

## Line

`kind` MUST be `review`. `tier` MUST be 2. `source` MUST be `manual`: the owner judged, not a tool and not a model. `at` is the date the verdict is about, in the record's zone (a review of August written in October has an `at` in August); `end` is null. `recorded_at`, which the envelope carries for every line (SPEC §2), is when it was written, and a reader shows the two apart when they differ.

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"review/v1"` | MUST | |
| `goal` | string | MUST | the id of the `goal/v1` line reviewed. Any goal line of the chain, superseded or not; a reader resolves it to the standing goal by `supersedes` to show the current text |
| `disposition` | string | MUST | one of exactly five strings: `advancing`, `stalled`, `done`, `let go`, `superseded` (below) |
| `period` | string | MUST | the stretch the verdict covers: `day`, `week`, `month`, `quarter` or `year`; the one that holds `at` |
| `note` | string | MAY | the verdict in the owner's words, plain text |

Anything else MAY be kept under `extra`.

The five dispositions:

| Value | Meaning |
|---|---|
| `advancing` | the goal moved in the period; it stays open |
| `stalled` | it did not, and the owner says so; it stays open, and a reader flags it |
| `done` | reached: the goal is closed |
| `let go` | the owner let it go on purpose: the goal is closed, with nothing to flag |
| `superseded` | a reworded goal replaced it: the goal is closed, and the new goal's `supersedes` names it |

## Tier

2, MUST, for the reason [goal/v1](0036-goal-v1.md) gives: a verdict is the owner's words on the owner's goal, and SPEC §4 puts *decisions, confirmations* at tier 2. It is also derived from a tier-2 line, and §4 has derived data inherit the highest tier of its evidence; the two agree. The `note` is free text the owner writes knowing it is tier 2.

## Rules

1. **The dedupe key is `(goal, period, at)`.** One verdict per goal per period per date: a writer asked to review the same goal for the same period on the same date writes nothing and says so. A second opinion on the same date is a retraction of the first (RFC 0003) and a new line.
2. **The standing review of a goal** is its latest `review` line by `at`, then `seq`, not retracted. A goal with none is unreviewed. A review of a superseded goal line counts for the goal it names and the goals that supersede it: the chain of `supersedes` is one goal.
3. **A review closes or keeps open; it never rewrites.** `done`, `let go` and `superseded` close the goal; `advancing` and `stalled` keep it open. A goal closed by a review and then reviewed `advancing` is open again: the later verdict stands, and the record shows the change of mind.
4. **Backfilling is a feature.** `at` MAY be before `recorded_at` by any stretch. A writer refuses an `at` after its own clock by more than five minutes (RFC 0034 amendment 2's rule) and an `at` before the goal's `from`.
5. **`superseded` and the goal's `supersedes` say the same thing twice, on purpose.** The goal's field says which line replaced it; the review says when the owner decided. A reader needs neither to understand the other: a goal named in a later goal's `supersedes` is not standing whatever its reviews say, and a goal reviewed `superseded` is closed whether or not a new goal has been written yet.

## Example (synthetic)

In October, Ines Nordmann writes down that she let the year's sailing goal go in August, when the boat's engine failed in Bodø; the verdict is dated August and written in October:

```json
{"at":"2026-08-31T20:00:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"review","tier":2,
 "payload":{"schema":"review/v1","goal":"019cadd3-6bc0-7dcd-9133-000000000302","disposition":"let go","period":"month",
 "note":"Engine gone in Bodø on the 9th. Towed home. Next summer."}}
```

(`recorded_at`, in the envelope, is `2026-10-11T18:30:00Z`.)

## What a Day page shows

A review is on the day its `at` falls on, the day the verdict is about, not the day it was written. The Day gains a `reviews` row per standing review on the day: the goal's current text (the standing goal by `supersedes`), the disposition, the period and the note, and `written 2026-10-11 20:30` when `recorded_at` is on a later day than `at`, so a backfilled verdict never passes for one made on the day. `show` lists the line as `review  let go · month · <goal text>`. JSON: `reviews`, a list of `{ line, goal, goal_text, disposition, period, note, recorded_at }`; an empty list on a day with none.

## Notes

- **Why `at` is the date and not the writing.** `at` is when the thing happened (SPEC §2), and the thing is a verdict on August. The record already says when every line was written, in `recorded_at`, under the hash; a second date field would repeat it.
- **Why five words.** Advancing and stalled are the two open verdicts; done and let go the two closings, one with and one without an outcome; superseded the one that points at another goal. A sixth word would be a comment, and the note is for that. The words follow RFC 0034 amendment 1's four for a commitment, with `let go` where that has `dropped`, because a goal is not dropped, it is let go.
- **Why `let go` has a space.** It is the owner's phrase and the one a reader prints; a reader compares the string, and a string with a space is as exact as one without.
