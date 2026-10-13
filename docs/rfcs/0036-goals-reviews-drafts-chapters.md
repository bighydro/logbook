# RFC 0036 — Goals, reviews, drafts and chapters; the day's boundary; the freshness of a signature

Status: draft · 2026-10-13 · comment period: two weeks

Four payload profiles, one record setting and one policy key, so that two implementations agree on how the owner's intentions and a model's words sit in the record. `goal/v1` is a goal in the owner's own words; `review/v1` is the owner's verdict on a goal at a date; `draft/v1` is what a model wrote about a unit of the record, every sentence pointing at the lines it rests on; `chapter/v1` is a named stretch of the record. `day_start` in `logbook.json` is where the owner's day begins, applied by every reader that groups by day and by nothing that writes. `signed_within_days` on a `policy/crossing.json` entry lets only days with a fresh signature cross through it. Nothing in the envelope (SPEC §2–3) changes, nothing is rewritten, and the conformance samples are untouched.

The four profiles are new and not among RFC 0031's freezes: their schemas may change while this RFC is a draft, and each freezes only by RFC 0031's process (a reader, a fixture in both implementations, a schema pass, one dated amendment). Each has a page of its own beside the other profiles, with its field table, its example and the reasoning for its tier: [goal/v1](../../rfcs/0036-goal-v1.md), [review/v1](../../rfcs/0036-review-v1.md), [draft/v1](../../rfcs/0036-draft-v1.md), [chapter/v1](../../rfcs/0036-chapter-v1.md). This document is the one that says why, and how the parts fit.

RFC 0035 is `people-review/v1`, merged on 2026-10-10; this RFC takes the next number.

## Why

The record holds what happened: the sources write the lines, the readers derive the days, the owner signs a day and only signed days cross (RFC 0034). Three things it does not hold yet. What the owner is *for* (a goal, and later the verdict on it) lives in a notes app or nowhere, so a reader that asks "how is the year going" has nothing to read. What a model *said* about a day lives in a chat window, so the Day page an orchestrator builds cannot be rebuilt from the record, and a sentence the model made up looks like a sentence the record supports. And the record has no word for a stretch of life the owner names, a sabbatical, a passage, the year after a move, so a reader groups by calendar alone.

Each of the three is an act, so each is a line (SPEC §3: a correction is a new line; ADR 0004, ADR 0013). A goal reworded is a new goal line carrying `supersedes`; a verdict is a review line on the date it is about; a model's words are a draft line that names the head it read; a chapter renamed or re-bounded is a new chapter line. Nothing is edited, and every reader shows the latest by `supersedes`, as it does for an imported note (RFC 0010 rule 2).

The two mechanisms come from the same week. A day that ends at midnight is the calendar's day, not the owner's: a line at 02:00 belongs to the evening before, and the signed day should cover the day as lived. And the crossing has one gate for *whether* the owner read a day; a destination that should see only what the owner has looked at lately needs one for *how recently*.

## The evidence rule

ADR 0022 says it in one sentence: *orchestrators reach the record only through the crossing: read tools under the ceiling, and the few write tools the owner allows by name.* This RFC adds the sentence for what an orchestrator's model may leave behind when it does write:

**Every sentence of model output stored in the record points at the line ids it rests on, or is marked unsupported; a reader never shows an unsupported sentence as fact.**

A `draft/v1` line is text in segments, each with `evidence`, a non-empty list of line ids, or `"unsupported": true` and no evidence. There is no third shape. A reader prints a supported segment with its evidence reachable (the ids, or links to the lines) and an unsupported one set apart and marked, never as plain prose between two supported ones. The draft as a whole is a proposal: nothing in it is a fact of the record until the owner confirms it through an act of their own, a signed day whose `confirmed` names the lines the segment rests on (RFC 0034), a note (RFC 0010), a review (`review/v1`), or a star (a `keeper/v1` line, RFC 0024). The draft is never that confirmation, whoever ran the model and however many times it agrees with itself. This is RFC 0034's rule, *agents draft; the owner signs*, applied to the agent's text.

## The profiles in one table

| Profile | What it is | `source` | Tier | Dedupe key | Standing |
|---|---|---|---|---|---|
| `goal/v1` | a goal in the owner's own words: `text`, `horizon`, `from`, `until`? | `manual` | 2, MUST | none from a source: one line is one goal | the latest line not retracted and not named in a later goal's `supersedes` |
| `review/v1` | a verdict on a goal at a date: `goal`, `disposition`, `period`, `note`? | `manual` | 2, MUST | `(goal, period, at)` | the latest review of a goal by `at`, then `seq`, not retracted |
| `draft/v1` | a model's text about a unit: `unit`, `subject`, `read_head`, `read_count`, `language`, `segments` | `model:<name>` | the highest tier among the lines it read | `(source, unit, subject, read_head)` | the latest draft of a unit not retracted and not named in a later draft's `supersedes` |
| `chapter/v1` | a named stretch: `name`, `from`, `to`?, `rules` | `manual` | 2, MUST | `(name, from)` | as `goal/v1` |

**Tier.** SPEC §4 puts *notes, decisions, confirmations* at tier 2 and makes `note/v1` MUST 2 (RFC 0010): a note is the owner's words, and the owner's words are tier 2 whatever they say, because a sentence about a goal, a verdict or a stretch of life is as private as a sentence about a day. A goal, a review and a chapter are the owner's words, so each is tier 2 and MUST, as `note/v1` is: a writer never lowers it, and no import option raises or lowers it. A draft is not the owner's words; it is derived from lines, and §4 says *derived data inherits the highest tier of its evidence*. Its evidence is every line the model read, not only the lines it cited, because a model that read a tier-3 line may have written from it without citing it; so a draft's tier is the highest tier among the lines on the unit at the moment it read, under the ceiling it read under. A draft written through the `mcp` door at a ceiling of 1 is tier 1 and crosses as tier 1 does; one written on the home machine over a day with a health line is tier 3 and is sealed as tier 3 is (RFC 0029).

**`at`.** A goal's `at` is when the owner wrote it; `from` is when it starts, and the two differ when a goal is written in January for the year or written down in March for a year that began in January. A review's `at` is the date the verdict is about, and `recorded_at` says when it was written: goals let go in August and reviewed in October carry an `at` in August and a `recorded_at` in October, and the Day of the August date lists them, as it lists every line whose `at` falls on it (SPEC §3.2.1). A draft's `at` is when the model wrote it. A chapter's `at` is when the owner named it, and `from` is where it starts.

## `day_start`

`logbook.json` MAY carry `"day_start": "HH:MM"`, a clock in the 24-hour form; absent, it is `"00:00"`, the calendar day, which is what every record written so far has. The lines do not change: a line's `at` is the instant the thing happened, as always, and the setting is a reader's.

**The rule.** The **local day** of an instant is its calendar date in the record's zone (SPEC §3.2, the record's zone), except that an instant whose local clock is before `day_start` belongs to the date before. With `day_start` `06:00`, a line at `02:00` on the 13th is on the 12th, a line at `06:00` is on the 13th, and a line at `23:30` is on the 13th as it always was. The comparison is on the wall clock after localising, so a change of offset in the night moves no line: the day is what the owner's clock said.

**Who applies it.** Everything that puts a line on a day: `day_local` in the index (ADR 0007; the index is derived and disposable, records the `day_start` it was built with, and is rebuilt when the setting differs, as it is rebuilt when the head does not match), `show` (SPEC §3.2.1), the Day and `days` (§3.2.7), the digest, `promises`, the readiness window of RFC 0034, the page of a signed day (RFC 0034: *every line whose `at` falls on the local day*, which this RFC reads as the local day so defined), the window of a crossing where it is given in days, and the `day` arguments of the MCP tools. The night window of `policy/stays.json` (22:00 to 08:00 by default) is unchanged and independent: it finds the night's stay; `day_start` says which day a line is on. A day's span in a reader is from `day_start` on the date to `day_start` on the next, so the §3.2 window of a reader that reads "the first day's local midnight" reads "the first day's start".

**Who does not.** `verify` and `add`, which never group by day; the month file a line is written to (SPEC §1: by the month of `at`, in UTC, unchanged); `at`, `end`, `recorded_at` and the hash of every line.

**A reader that does not understand it.** A reader that reads `logbook.json`, finds `day_start`, and either does not implement this RFC or cannot parse the value (not `HH:MM`, or outside `00:00`–`23:59`) MUST say so and MUST NOT group by day as if the key were absent: it refuses the command that groups, naming the key and the value, as SPEC §2 has it refuse a zone it does not know rather than substitute one. A reader that does not read `logbook.json` at all cannot meet the key; `verify` is one. The conformance samples (`conformance/`) carry no `day_start`, so a conformant implementation that has not implemented this RFC is unaffected by it and passes as before; a record that sets the key states its own boundary, and a reader of that record has implemented the rule or says it has not.

**The signature.** The page of a day (RFC 0034) is the lines on the day so defined, and the signed day covers the day so defined. Changing `day_start` on a record with signed days moves lines between pages, so every signature whose page changed reads as `page_matches` false, exactly as it does when a line is appended to a signed day; the owner reads again and signs again, or does not. Set it once, early. The `page` digest does not name the boundary; whether it should is an open question below.

## `signed_within_days`

An entry of `policy/crossing.json` MAY carry `"signed_within_days": N`, N a positive integer. Absent, there is no restriction: the entry crosses what RFC 0034 lets cross today (signed days by default, every day under `--unsigned`). Present, only the lines of days whose **standing signature** (RFC 0034 rule 3) was written on one of the local days from N days before today through today cross through that entry, today being the day of the export or the tool call in the record's zone. A day that is unsigned, or whose standing signature is older, crosses nothing but its header: the day, and whether and when it was signed, which is what `show` prints above a day's lines and what RFC 0034 rule 6 puts in the Day's header. Re-signing a day refreshes it: the owner read the page again, and the new signature is today's.

```json
{"hermes": {"max_tier": 2},
 "mcp": {"max_tier": 1, "write": ["sign_day", "note_day"], "write_window_days": 60},
 "cloud-model": {"max_tier": 2, "until": "2026-12-31", "signed_within_days": 14}}
```

**How it composes.** The three keys are three gates on one entry, each independent and each the owner's (ADR 0016), and a line crosses when it passes all of them:

- `max_tier` is on the line: a line above the ceiling never crosses, whatever its day's signature says, and a request above the ceiling is refused naming the file (ADR 0016 rule 2).
- `until` is on the entry: past that day the entry counts as `max_tier` 0 (ADR 0022 rule 6) and nothing crosses, the header included; `signed_within_days` on an expired entry has nothing left to gate.
- `signed_within_days` is on the day: it decides which days' lines may cross at all, and `max_tier` then decides which of those lines. It never lets a line cross that `max_tier` holds back, and `max_tier` never lets a day cross that it holds back.

The rule is the entry's, not the command's, so every crossing that reads the entry obeys it: the crossing package (RFC 0005), the shared page (RFC 0025; a page of a day the entry does not allow is refused naming the key), the trip bundle (RFC 0030), the vault, the site and the MCP read tools (`docs/mcp.md`), including the ones RFC 0034 rule 5 leaves ungated by default. `--unsigned` lifts RFC 0034's default, which is the command's; it does not lift the entry's rule, and a day the entry holds back stays home under it, counted and said. The MCP door's write tools (`write`) are not crossings out of the record and are not gated by it: `sign_day` must reach an unsigned day to sign it, and `write_window_days` is the window on writes.

**What a reader says.** The crossing package's manifest `policy` carries `signed_within_days` beside `signed_days` when the entry sets it, and `counts.held_back_unsigned` counts the lines held back by either gate; the `crossing/v1` line's `policy` carries the same key (RFC 0011, additive). `doctor` prints it on the entry's crossing line, as it prints `write`. An MCP answer's `gate` carries it beside `max_tier`.

## What a Day page shows

The Day (`logbook day`, `/day/YYYY-MM-DD` in `serve`, `show`) gains four things, each from the standing lines of the record and nothing else, in this order:

1. **The chapter, in the header.** After the weekday and the signed state: `· chapter <name>`, the standing chapter whose `from` is on or before the day and whose `to` is absent or on or after it. A day in no chapter prints nothing. JSON: `chapter`, `null` or `{ name, line, from, to }`.
2. **The draft, above the owner's note, marked as a draft.** Before the first `note/v1` line of the day (and before the timeline when the day has no note): the standing `draft/v1` line whose `unit` is `day` and whose `subject` is this day, headed `draft · <source> · read at <read_head, 8 hex> · <read_count> lines`, then its segments in order. A supported segment prints with its evidence reachable: the line ids in text, links to the lines in `serve`. An unsupported segment prints set apart and marked `unsupported`, and is never run into the prose around it. A draft is listed as a line on its day too, as every line is (SPEC §3.2.1), with the mark `draft`. A draft of another unit (a week, a journey, a chapter) is for that unit's page and is not on the Day. JSON: `draft`, `null` or the payload's fields with `line` and `source`.
3. **Goal reviews, on the day they were made.** A `reviews` row per standing review whose `at` falls on the day: the goal's text (from the goal line, the standing one by `supersedes`), the disposition, the period, the note, and `written <recorded_at, local>` when `recorded_at` is on a later day than `at`, so a backfilled verdict says it was. JSON: `reviews`, a list of `{ line, goal, goal_text, disposition, period, note, recorded_at }`.
4. **Goals and chapters as lines.** A `goal/v1` or `chapter/v1` line is listed on the day its `at` falls on, as any line is, with its text; nothing else is derived from it on the Day. Where goals are read as a whole (open goals, the year's verdicts) is a reader of its own and a later RFC.

The signature is unchanged by all four: the page digest is over the hashes of the page's lines (RFC 0034), and a draft, a review, a goal or a chapter whose `at` is on the day is one of them. `days`, `digest`, `year` and the printed pages are unchanged by this RFC.

## What this changes in SPEC, when adopted

Nothing in §2–3. In §1, `logbook.json` gains `day_start` as an optional key, with the rule above. In §3.2, the sentence on the record's zone gains the day's boundary, and §3.2.1 and §3.2.7 gain the four items above. The four profiles join the §4 table (tier 2, MUST, for three; *the highest tier of its evidence* for `draft/v1`) and the draft list of `rfcs/README.md`. ADR 0016's file gains the key `signed_within_days`, and RFC 0034 rule 5 gains the sentence that the entry's rule applies where the command's default does not. Each profile freezes by RFC 0031's process, with a fixture under `conformance/profiles/`, once a second reader exists.

## Notes

- **Why one line per goal and a new line to reword.** The log is not edited (SPEC §3), and a goal reworded is a decision in itself: the owner wanted something else, or wanted to say it better, and the record keeps both. `supersedes` is the mechanism every edited thing in the record already uses (RFC 0010 rule 2, RFC 0034 rule 3).
- **Why a review is on the date it is about.** `at` is when the thing happened (SPEC §2), and the thing is the verdict on a stretch that ended then. The record's own `recorded_at` says when it was written; a second field would say the same twice.
- **Why a draft names the head and the count it read.** A draft is a reading of the record at a moment. The head says which record it read; the count says how much of the unit, so a reader can tell a draft written from four lines from one written from forty, and a draft written under a ceiling of 1 from one written on the home machine. When the unit grows, the standing draft is of a smaller unit than the page now shows, and a reader can say so.
- **Why every segment has evidence or a mark.** A model's sentence with no line behind it is the one kind of content the record has never held: not observed, not the owner's. It is allowed in, because the owner wants to read it, on the one condition that it never looks like the rest.
- **Why the draft's tier is what it read, not what it cited.** A tier is what a line may give away. A model that read a tier-3 line may have been shaped by it in a sentence that cites a tier-1 line, and no reader can tell. The ceiling the model read under is the only bound that holds.
- **Why `day_start` is a setting and not a line.** It is the owner's habit, not an event; it has no `at`. It belongs with `timezone`, which is the same kind of thing: how the owner's clock maps onto the record's instants. And `logbook.json` already requires writers to preserve keys they do not know (SPEC §1), so a record that sets it is read by an old writer without losing it.
- **Why refuse rather than guess.** A reader that groups by calendar day on a record whose owner set `06:00` would sign, cross and digest the wrong days, silently. SPEC §2 made the same choice for an unknown zone.
- **Why the window is on the signature's day and not the day signed.** The point is how recently the owner looked. A rule on the gap between a day and its signature would make a day whose page grew after N days uncrossable for good, since no later signature could close the gap; a rule on the signature's recency is refreshed by signing again, which is what RFC 0034 asks the owner to do when a page changes.
- **Why `--unsigned` does not lift it.** `--unsigned` is the owner at the console lifting the command's default for one run. A policy key is a ceiling (ADR 0016): the command cannot exceed it, which is what makes an unattended destination safe to give a fixed command line.

## Open questions

1. **Should the signed day's `page` name the boundary?** RFC 0034's page digest is over `day`, `tz` and the line hashes. A record that changes `day_start` makes every signature read as not matching, which is correct and loud, but a reader cannot tell a page that changed because a line was appended from one that changed because the boundary moved. Adding `day_start` to the pre-image is one field; it is also a change to a profile that is already in the conformance sample. Left for RFC 0034's own amendment.
2. **What writes a draft.** This RFC fixes the line and not the writer. `note_day` through the door writes a `note/v1` with `labels: ["proposal"]` today (`docs/mcp.md`); whether a `draft_day` tool joins `write`, or a command on the home machine runs the model, is the agent layer's to decide, under ADR 0022.
3. **A star on a draft.** "A star" here is a `keeper/v1` line, the one mark the owner makes today, and it marks a photo. A mark on a draft segment, "this sentence is right", does not exist and is not invented here; the owner confirms a segment by confirming the lines it rests on, in a signed day.
4. **Overlapping chapters.** The rule on the chapter page is that chapters do not overlap and a writer refuses one that would; a reader that meets two standing chapters open on one day shows the later by `from`, then `seq`, and marks the clash. Whether an owner wants nested stretches (a passage inside a sabbatical) is not decided.
5. **A review of nothing.** A review names a goal. A verdict on a period with no goal behind it, "the quarter went badly", is a note today, and stays one.
6. **`period` and `at`.** The period is the stretch that ends on, or holds, the review's `at`; which of the two is left to the writer and the owner's habit (a week reviewed on its Sunday, a month on its last day or its first). A reader shows the period as written and derives nothing from it.
