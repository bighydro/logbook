# RFC 0035 — payload profile `people-review/v1`: the owner says two are not the same person

Status: draft · 2026-10-10 · comment period: two weeks

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
