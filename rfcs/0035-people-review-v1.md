# RFC 0035 — payload profile `people-review/v1`: the owner says two are not the same person

Status: draft · 2026-10-10 · comment period: two weeks · amendment 1 (the no is `entity-review/v1`, by RFC 0037) 2026-10-14

One statement by the owner that an observed person — what one source saw, keyed by its strongest identifier — is **not** the canonical person a review proposed. `resolution/v1` (RFC 0006) can say that two refs are one identity (`alias_of`) and that a ref is a person (`entity`); it has no way to say *no*, and a review queue that cannot remember a no asks the same question every time. This profile is that no. It is written by `logbook people review --reject`, read by the same command, and by nothing else: no reader changes a name, a channel or a day because of it.

`people-review/v1` is a new profile, not one of the RFC 0031 freezes: its schema may change while this RFC is a draft.

## Why a line

The record must not depend on anything outside itself, and a decision the owner made is a fact about the record's people (ADR 0013). A side file would be lost with the index, which is disposable; a note would be prose. One line in the chain, retractable like any other (RFC 0003), is the smallest thing that keeps the decision and lets the owner take it back.

## Line

`kind` MUST be `people-review`. `tier` MUST be the highest tier of the evidence it refers to (SPEC §4): the observed lines and the resolution lines that name the canonical person, 2 in practice. `source` MUST be `manual`: the owner said so. `at` is when they said it; `end` is null.

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"people-review/v1"` | MUST | |
| `verdict` | string | MUST | `different`: the observed person and the entity are not the same person. No other verdict is defined; a *same* is a `resolution/v1` alias line (RFC 0006), never this |
| `ref` | object | MUST | the observed person's strongest identifier, `{ kind, value }`: `kind` one of `email` (the address, case aside), `phone` (E.164), or `name` (the display name's words, folded and sorted) |
| `refs` | array of object | SHOULD | the observed person's identifiers as the lines wrote them, each `{ kind, value }` with `kind` one of RFC 0006's ref kinds. A reader matches a later observation against `ref` and every entry here |
| `observed` | array of string | MAY | the display names the observed person was seen under |
| `entity` | object | MUST | the canonical person, `{ type: "person", id, registry: "logbook" }` as RFC 0006 mints them |
| `label` | string | SHOULD | the canonical person's label at the time, for reading the log without any registry |
| `method` | string | MAY | `owner` |
| `evidence` | array of string | MAY | ids of the lines the observed person was seen on |
| `logbook_head` | hex sha256 | MAY | the head the proposal was read against |

## Rules

1. A `people-review` line changes no resolution: the observed identifiers still resolve to nothing (or to whatever other line resolves them), and every reader reads as before. Its one effect is on the review queue.
2. A review reader MUST NOT propose an observed person against an entity when a standing `people-review` line with verdict `different` names that entity and the observed person's strongest identifier, or any identifier it was seen as, is `ref` or in `refs`.
3. Retraction (RFC 0003) applies: a retracted line counts for nothing, and the proposal returns.
4. Nothing requires the line. A record with none is complete, and a queue is as long as its evidence.

## Example (synthetic)

```json
{"at":"2026-10-10T19:02:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"people-review","tier":2,
 "payload":{"schema":"people-review/v1","verdict":"different",
 "ref":{"kind":"email","value":"hanna.foss@example.org"},"refs":[{"kind":"email","value":"hanna.foss@example.org"}],
 "observed":["Hanna Foss"],"entity":{"type":"person","id":"019cadd3-6bc0-7dcd-9133-000000000121","registry":"logbook"},
 "label":"Hanna Foss","method":"owner","evidence":["019cadd3-6bc0-7dcd-9133-0000000000e1"],
 "logbook_head":"8f1c…"}}
```

## Amendment 1 — the no is `entity-review/v1`

Dated 2026-10-14, by [RFC 0037](0037-entities.md) (*Entities*, a draft), whose owner decided that one profile carries the owner's no for every kind of entity, a person's included (RFC 0037 §16, question 2). This section amends the profile above and rewrites nothing in it: every `people-review/v1` line already in a record keeps its meaning and its hash.

1. **From now on the no is written as `entity-review/v1`.** `logbook people review --reject` (and `review person --reject`, RFC 0037 §5) writes one `entity-review/v1` line (RFC 0037 §6) with `type` `person`, and no longer writes `people-review/v1`. The fields are this page's, unchanged in meaning: `verdict` `different`, `ref`, `refs`, `observed`, `entity` (`type` `person`), `label`, `method`, `evidence`, `logbook_head`; the line adds `type` and its `kind` is `entity-review`. `source` `manual` and the tier rule are as above.
2. **Readers accept `people-review/v1` forever.** A standing `people-review/v1` line is read exactly as an `entity-review/v1` line with `type` `person` and the same fields: rule 2 above holds for both profiles, and a no held by either keeps the pair out of the queue. Retraction (RFC 0003) applies to both.
3. **Nothing is migrated.** No `people-review/v1` line is rewritten, superseded or copied into the new profile; a writer that finds the no already held, by a line of either profile, writes nothing and says so (RFC 0037 §9).
4. **The profile stays on this page.** `people-review/v1` is read and no longer written. It is not frozen, and this amendment does not delete it: a record that holds one is read the same by every later reader.

What does not change: rule 1 (a no changes no resolution), rule 4 (nothing requires the line), the person's road, which is `resolution/v1` (RFC 0006) and nothing else, and the queue a record's evidence gives.

### Example (synthetic)

A no as `people review --reject` writes it after this amendment: the review proposed an address that signs as Ola Nordmann against the canonical Ola Nordmann, by the same name, and the owner says it is a namesake:

```json
{"at":"2026-10-14T19:02:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"entity-review","tier":2,
 "payload":{"schema":"entity-review/v1","type":"person","verdict":"different",
 "ref":{"kind":"email","value":"o.nordmann@example.org"},"refs":[{"kind":"email","value":"o.nordmann@example.org"}],
 "observed":["Ola Nordmann"],"entity":{"type":"person","id":"019cadd3-6bc0-7dcd-9133-000000000121","registry":"logbook"},
 "label":"Ola Nordmann","method":"owner","evidence":["019cadd3-6bc0-7dcd-9133-0000000000e1"],
 "logbook_head":"8f1c…"}}
```
