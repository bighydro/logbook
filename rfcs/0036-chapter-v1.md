# RFC 0036 — payload profile `chapter/v1`: a named stretch of the record

Status: draft · 2026-10-13 · comment period: two weeks · one of the four profiles of [RFC 0036](../docs/rfcs/0036-goals-reviews-drafts-chapters.md)

A stretch of life the owner names: a sabbatical, a passage, the year after a move. Not a trip (ADR 0019: a trip is derived, never written) and not a goal (a goal is wanted; a chapter is lived). It has a name, a first day, a last day when the owner has closed it, and the chapter's rules in plain text: what counts in this stretch, and what the owner is for in it. A day belongs to the chapter open on that day, and the Day's header says which.

`chapter/v1` is a new profile, not one of the RFC 0031 freezes: its schema may change while RFC 0036 is a draft.

## Line

`kind` MUST be `chapter`. `tier` MUST be 2. `source` MUST be `manual`: the owner named it. `at` is when the owner named it; `end` is null. `from` and `to`, in the payload, are the stretch, and `from` is often before `at`: a chapter is usually named once the owner knows it is one.

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"chapter/v1"` | MUST | |
| `name` | string | MUST | the chapter's name, in the owner's words |
| `from` | `YYYY-MM-DD` | MUST | its first local day |
| `to` | `YYYY-MM-DD` | MAY | its last local day; absent, the chapter is open |
| `rules` | string | MUST | the chapter's rules as plain text: what counts in this stretch, what the owner is for in it. May be empty when the owner has not said |
| `supersedes` | string | MAY | the id of the earlier `chapter` line this one renames, re-bounds or closes (SPEC §3) |

Anything else MAY be kept under `extra`.

## Tier

2, MUST, for the reason [goal/v1](0036-goal-v1.md) gives: a name and a set of rules are the owner's words about their own life, and SPEC §4 puts the owner's words at tier 2 with `note/v1` MUST 2. A chapter named "the divorce" beside one named "the Lofoten summer" is why the writer does not choose.

## Rules

1. **The dedupe key is `(name, from)`.** The same name from the same day is the same chapter: a writer asked for it twice writes nothing and says so. A different name or a different first day is a new chapter, or a new line of the old one with `supersedes`.
2. **Renaming, re-bounding and closing supersede.** A chapter closed (given a `to`), renamed or moved is a new line carrying `supersedes` naming the earlier one and every field again, `rules` included. The **standing chapter** is the latest `chapter` line not retracted and not named in a later chapter's `supersedes`; the earlier line stays in the record, marked.
3. **A day belongs to the chapter open on it.** The chapter of a local day (RFC 0036, `day_start`) is the standing chapter whose `from` is on or before the day and whose `to` is absent or on or after it. A day in none has no chapter.
4. **Chapters do not overlap.** A writer refuses a chapter whose stretch overlaps a standing chapter's, naming it. A reader that meets two standing chapters open on one day anyway (two writers, a retraction that reopened one) shows the later by `from`, then `seq`, and marks the clash. Nested chapters are an open question of RFC 0036.
5. **`rules` is read by people.** A reader prints it and derives nothing from it: it is the owner's statement of what the stretch is for, which a draft of the chapter (`draft/v1`, `unit` `chapter`) may quote as evidence and a review may be written against, by the owner.

## Example (synthetic)

In September, Ines Nordmann names the summer she spent on the boat, which began when she cast off in June and ended when the boat was towed into Bodø:

```json
{"at":"2026-09-06T17:20:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"chapter","tier":2,
 "payload":{"schema":"chapter/v1","name":"The Lofoten summer","from":"2026-06-20","to":"2026-08-09",
 "rules":"Every night at anchor counts. A marina counts against. The engine is not the point; the boat is."}}
```

and the open chapter after it, named the same evening:

```json
{"at":"2026-09-06T17:25:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"chapter","tier":2,
 "payload":{"schema":"chapter/v1","name":"Ashore, fixing things","from":"2026-08-10",
 "rules":"What counts: the engine rebuilt, the mooring sorted, one weekend a month on the water anyway."}}
```

## What a Day page shows

The chapter in the header, after the weekday and the signed state: `2026-07-04  Saturday · signed 2026-07-05 08:15 · chapter The Lofoten summer`. A day in no chapter prints nothing there. The chapter line itself is listed on the day its `at` falls on, as every line is (SPEC §3.2.1): `chapter  The Lofoten summer  2026-06-20 – 2026-08-09`, with the mark `superseded` when a later chapter names it. JSON: `chapter`, `null` or `{ name, line, from, to }`. `days` and the digest are unchanged by this RFC; a chapter's own page, the days it holds and its draft, is a reader of its own and a later RFC.

## Notes

- **Why not a tag on each day.** A day is not a line and cannot carry one (SPEC §3.2.1: what a reader derives is never a line). A stretch with two ends is one line; a mark per day would be hundreds and would still need the two ends to be found.
- **Why the rules are prose.** They are the owner's, for the owner and for a model that drafts the chapter, and no reader interprets them. A field per rule would be a schema for a life, and the record has declined that before (RFC 0010, *Why not `decision/v1`*).
- **Why a trip is not a chapter.** A trip is found in the track and recomputed every time; a chapter is said by the owner and may hold three trips or none.
