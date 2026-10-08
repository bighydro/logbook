# RFC 0034 — The signed day: `signed-day/v1`, and the gate on the crossing

Status: draft · 2026-10-07 · comment period: two weeks

Agents draft; the owner signs; only signed days cross. This RFC adds one payload profile, `signed-day/v1`, the line the owner appends when they have read a day's page and confirm it as the day's facts; one default for the crossing package (RFC 0005, ADR 0016), which now crosses the lines of signed days unless the owner asks for the rest; one header for `show`; and one block in the Day reader, `readiness`, which says per class of source whether the day's lines are in and which usual sources have not delivered. Nothing in the envelope (SPEC §2–3) changes, nothing is rewritten, and no agent can sign.

`signed-day/v1` is a new profile, not one of the nineteen RFC 0031 freezes: its schema may change while this RFC is a draft, and it becomes frozen only by RFC 0031's process, a reader, a fixture in both implementations, a schema pass and one dated amendment to that RFC.

## Why

Adapters and agents fill the record: a tracker writes the points, a mail import the threads, an agent with MCP may run `add` and draft a note the owner then writes (ARCHITECTURE, layer 5: agents are operators, never authors). What crosses to a member of the circle is gated by tier (ADR 0016), which says how private a line is, not whether the owner has looked at it. A day whose photos came in overnight and whose calendar entry was a draft nobody read can cross at tier 1 on a nightly job before the owner has seen the page.

The signed day is the owner's reading of the page, recorded in the chain: *I have seen these lines, on this day, and they are the day's facts.* It is an act, so it is a line (SPEC §3: corrections are new lines; ADR 0004, ADR 0013). It rewrites nothing: a day that was wrong is corrected by new lines and signed again, and the later signature supersedes the earlier. A crossing then has a second gate beside the tier: a line crosses when its day is signed, and the owner opens the gate for the rest by typing so.

## The line

`kind` MUST be `signed-day`. `tier` MUST be 1: the line names a day, line ids, a digest and a count, never what any line said; the one free-text field is a one-line note the owner writes knowing it is tier 1. `source` MUST be `manual`: the owner signed it, not a tool and not an adapter. `at` is when the owner signed, not the day signed (so a signature written the morning after is on the morning after, and the index finds it by `payload.day`); `end` is null.

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"signed-day/v1"` | MUST | |
| `day` | string | MUST | the local day signed, `YYYY-MM-DD`, in the record's zone (SPEC §3.2) |
| `subject` | string | MUST | who signed: the `owner_id` of `logbook.json`. A signature by anyone else is not one, and a reader ignores a line whose subject is not the record's owner |
| `confirmed` | array of string | MUST | the ids of the lines the owner confirmed as the day's facts, in the page's order; a subset of the page's lines (below). Empty is allowed: the owner signs that nothing on the page is a fact of the day, or that an empty day was empty |
| `page` | object | MUST | `{ sha256, lines }`: the digest of the page as shown (below) and how many lines were on it |
| `note` | string | MAY | one line in the owner's words, tier 1; a newline is refused by the writer |
| `supersedes` | string | MAY | the id of the earlier `signed-day` line for the same day this one replaces (SPEC §3) |

Anything else MAY be kept under `extra`.

## The page as shown

A signature says what the owner saw. Text is a reader's own (SPEC §3.2.1), so the digest is not over text: it is over the lines the page listed, bound by their hashes, so that any implementation recomputes it from the record alone and the owner's words cannot be held to a wording.

The **page** of a day is every line SPEC §3.2.1 lists on it: every line whose `at` falls on the local day, of every kind but `retraction` (a mark on another line's day) and `signed-day` (a signature is about the page, never on it), a retracted line included (the page shows it, marked), in the day's order: by the instant of `at`, then `seq`.

```
page_sha256 = sha256( canonical_json({"day": "<YYYY-MM-DD>", "tz": "<the record's zone>",
                                      "lines": ["<hash of the first line>", "<hash of the second>", …]}) )
```

`canonical_json` is RFC 8785 as SPEC §3 uses it; the digest is lowercase hex. A reader that holds the record recomputes the page and compares: the page matches when the same lines in the same order are still on the day. A line appended later with an `at` on that day changes the page, and the day reads as signed with a page that no longer matches, which is the point: the owner is told the day grew after they signed, and signs again or does not.

## Rules

1. **Only the owner signs.** `logbook day sign` is the one producer. The MCP server (`logbook serve mcp`) exposes no tool that signs, now or later, and an agent that wants a day signed asks the owner (ARCHITECTURE: a confirmation stays with the human, enforced in layer 1). A line whose `subject` is not the record's `owner_id` is not a signature.
2. **A signature appends; nothing is rewritten.** The writer appends one line through `Logbook.append` and touches no other line, no file of the record and no setting. Correcting a day is new lines and a new signature.
3. **Re-signing supersedes.** A day may be signed any number of times. The later line carries `supersedes` with the earlier line's id. The **standing signature** of a day is the latest `signed-day` line (by `seq`) naming that day whose subject is the owner and that is not retracted (RFC 0003); a retracted later signature leaves the earlier standing. A day with no standing signature is **unsigned**.
4. **The confirmed set defaults to the page.** Without `--confirm`, every line of the page not retracted is confirmed. With `--confirm ID,ID,…`, each entry is a line id or a `seq`, resolved against the page; an entry that names a line not on the page, or a retracted line, is refused naming it, and nothing is written.
5. **The crossing crosses signed days.** `logbook export crossing` selects, within its window, tiers and kinds (RFC 0005, ADR 0016), the lines whose local day in the record's zone has a standing signature at the time of the export; a `signed-day` line crosses with the day it signs, wherever its own `at` falls. `--unsigned` lifts the gate and crosses the rest as before. The manifest's `policy` carries `signed_days`, `"only"` or `"any"`; `counts` gains `held_back_unsigned`, the lines the gate held back (counted in `held_back` too); the `crossing/v1` line's `policy` gains `signed_only`, a boolean, beside `file` and `max_tier` (RFC 0011, additive). A trip bundle (RFC 0030), a shared page (RFC 0025), the vault and the site keep their own selections and are not gated by this RFC; `signed_only` is `false` in the line they append.
6. **Readers say so.** `show <day>` prints the state in its header: `<day>  signed <when, local, to the minute>` or `<day>  unsigned`. The Day reader (`logbook day`) prints the same after the weekday and carries it in its JSON under `signed`: `null`, or `{ at, at_local, line, seq, confirmed, lines, page_sha256, page_matches, note, supersedes }` (`page_matches` is whether the page today digests to `page_sha256`; `null` when the reader is gated and cannot see the whole page). A `signed-day` line is listed on its own day by `show` as any line is. `days`, `digest`, `year` and the pages are unchanged.

## Readiness

The second thing the owner wants to know before signing is whether the day is all in. The Day reader gains `readiness`, computed from the record and the policy alone, with no network and nothing written. Six **classes** of source, in this order, each the kinds it covers:

| Class | Kinds |
|---|---|
| `mail` | `mail` |
| `message` | `message` |
| `meeting` | `transcript` |
| `location` | `location` |
| `photo` | `photo` |
| `calendar` | `event` |

For each class: `present` is whether the day has any line of its kinds; `lines` how many; `sources` which sources wrote them. A source is **usual** for a class when, over the window of the 28 local days ending on the day, it has a line of the class's kinds on at least four in five of the window's days that have any line (the rule of SPEC §3.2.7 `days`, per class) and `policy/import.json` has not disabled it. `missing` is the usual sources with no line of the class on the day. The block carries `window` (`since`, `until`, `logged_days`), `classes` (one object each: `name`, `kinds`, `present`, `lines`, `sources`, `usual`, `missing`), `missing` (the names of the classes with a missing source) and `ready` (no class is missing a source). The text form is one row, `readiness`, naming each class as `present`, `none` (nothing in, nothing expected) or `missing <source>` (`present, missing <source>` when the class is in from one source and a usual other is not).

Readiness is advice, never a gate: an owner signs a day with a source missing when they know the tracker was off. Its window and share are the reader's own; the JSON shape above is what a second implementation is held to once the profile freezes.

## Example (synthetic)

```json
{"at":"2026-03-08T19:30:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"signed-day","tier":1,
 "payload":{"schema":"signed-day/v1","day":"2026-03-01","subject":"00000000-0000-4000-8000-000000000001",
 "confirmed":["00000000-0000-4000-8000-000000000001","00000000-0000-4000-8000-000000000002",
 "00000000-0000-4000-8000-000000000003","00000000-0000-4000-8000-000000000004",
 "00000000-0000-4000-8000-000000000031","00000000-0000-4000-8000-000000000005",
 "00000000-0000-4000-8000-000000000006"],
 "page":{"sha256":"<the page digest of the seven lines>","lines":7},
 "note":"A quiet Sunday. Ines came for coffee."}}
```

## Conformance

`conformance/sample-logbook` carries one `signed-day/v1` line, the first day of the week signed on its last evening, as its 32nd line; the sealed sample carries the same, with the page digest the sealed lines give (a sealed line's hash is of its reference, so the two samples' digests differ, as their heads do). An implementation that reproduces the head reproduces the line; one that carries `show` prints `signed` in the first day's header.

## What this changes in SPEC §3.2, when adopted

Nothing in §2–3. In §3.2.1 (`show`), one sentence: the header says whether the day is signed. In §3.2.7, the Day's output gains `signed` and `readiness` as above; `days` is unchanged. The profile joins the tier-1 row of §4 and the draft list of `rfcs/README.md`; it freezes by RFC 0031's process, with a fixture under `conformance/profiles/signed-day/`, once a second reader exists.

## Notes

- **Why the digest is over hashes and not over text.** The owner saw text; two implementations print different text for the same day (SPEC §3.2.1: a reader's own). Hashes name the lines by content and are the same everywhere. What is verified is *which lines, with which content, were on the page*, which is what a signature should bind.
- **Why tier 1.** The crossing must be able to carry the signature with the day, to a member who crosses at tier 1 only; a tier-2 signature would be held back and the member could not tell a signed day from an unsigned one. Hence the line names nothing a line said, and the note is one line the owner writes knowing it crosses.
- **Why `at` is the signing moment.** The line records an act; the act happened when it happened (SPEC §2: `at` is when the thing happened). The day it names is in the payload, where the index and the readers look.
- **Why a gate on the crossing and not a tier.** Tier says how private; signed says whether read. A tier-3 line on a signed day still never crosses without the policy and `--tier 1,2,3`. The two gates are independent and both are the owner's.
- **Why readiness has no network.** Whether a source *should* have delivered is a question about the record's habit, not about the source's server. A source that is reachable and silent and one that is down look the same from the record, and the record is what is signed.
