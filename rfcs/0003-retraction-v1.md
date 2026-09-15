# RFC 0003 — payload profile `retraction/v1`

Status: draft · 2026-09-15 · comment period: two weeks

One line saying that an earlier line should be hidden. Nothing is rewritten or removed (SPEC §3); the retracted line stays in the chain, and every reader treats it as hidden. Produced by `logbook retract`, by adapters that learn a source has withdrawn something, and by engines that find a line was wrong.

## Line

`kind` MUST be `retraction`. `tier` SHOULD be 2 (the reason is the owner's words). `at` is when the retraction was decided; `end` is null. `source` is whoever decided it: `manual` for the owner, otherwise the adapter or engine name.

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"retraction/v1"` | MUST | |
| `supersedes` | string | MUST | the `id` of the retracted line |
| `seq` | integer | SHOULD | the retracted line's `seq`, for readers without an id index |
| `reason` | string | SHOULD | why, in the owner's words; may be empty |

Anything else MAY be kept under `extra`.

## Rules

1. The retracted line MUST exist earlier in the chain. A retraction of a line that is itself a retraction is not allowed; to undo a retraction, retract the *original* again with a new reason — readers take the retraction written last (rule 4).
2. A retraction hides; it does not correct. A corrected value is a new line of the original's kind whose payload carries `supersedes` (SPEC §3). A retraction says only "not this".
3. Readers (`show`, `export`, engines) MUST keep the retracted line in the record and MUST mark it, not drop it. A day package lists the retracted entry with `retracted_by` set to the retraction's `id`. A retraction is not an event of its own day: it appears where the line it hides was.
4. When one line is retracted more than once, the retraction with the highest `seq` wins.
5. Derived data (engine output) that used a retracted line as evidence MUST be recomputed or itself retracted. Engines record the `logbook_head` they ran against for this reason (ADR 0013).

## Example (synthetic)

```json
{"at":"2026-03-02T21:14:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"retraction","tier":2,
 "payload":{"schema":"retraction/v1","supersedes":"0195d1c2-7e40-7d3a-9b1e-4a2f1c8e0b77","seq":312,"reason":"two file paths pasted as a note by mistake"}}
```

## Notes

The first retraction in a real record was exactly this example: a stray note made of two file paths. It was the moment the record proved it is append-only — the mistake is still there, and so is the line that says it was one.

A source that deletes an item (a photo removed from the library, a track point dropped by the tracker) is a candidate for an adapter-written retraction with `source` set to the adapter; whether adapters do this by default is left to each adapter's RFC, since deletion upstream is not always the owner's intent.
