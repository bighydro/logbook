# RFC 0006 — payload profile `resolution/v1`

Status: draft · 2026-09-16 · comment period: two weeks

One statement that a source-native identifier refers to a known entity. Raw lines carry what their source gave — an email address, a phone number, a provider's participant name, a lat/lon. Turning those into an entity ("this is the same person as in that other line") is a *derived* judgement, and it belongs in its own line, never inside the raw one.

## Why this exists

The record must not depend on anything outside itself. A registry — a contact list, a place gazetteer, a company database — lives outside, changes, and may be someone else's. So the raw line stays raw forever, and a resolution line records, at a point in time, what some resolver believed. If the resolver was wrong, its line is retracted (RFC 0003) and the raw line is untouched.

## Line

`kind` MUST be `resolution`. `tier` SHOULD match the highest tier of the evidence it refers to (a resolution over tier-2 lines is tier 2). `at` is when the resolution was made; `end` is null. `source` is the resolver: an engine name, an adapter, or `manual` when the owner said so.

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"resolution/v1"` | MUST | |
| `ref` | object | MUST | the source-native identifier being resolved, as it appears in the raw lines: `{ kind, value, source? }` where `kind` is one of `email`, `phone`, `handle`, `provider_id`, `device_id`, `coordinate`, `domain` |
| `entity` | object | MUST | what it refers to: `{ type, id, registry }` where `type` is `person`, `place`, `company` or `thing`; `id` is that registry's identifier; `registry` names the registry (e.g. `wikidata`, `celfino-backbone`, `local`) |
| `label` | string | SHOULD | a human-readable name at the time of resolution, for reading the log without the registry |
| `confidence` | number | MAY | 0–1. Absent means asserted, not estimated |
| `method` | string | MAY | how it was decided: `exact`, `heuristic`, `model`, `owner` |
| `evidence` | array | MAY | ids of lines that justify it |
| `supersedes` | string | MAY | the id of an earlier resolution this replaces |

## Rules

1. A resolution never modifies the line it resolves. Readers join by `ref`.
2. A `ref` MAY match many lines — that is the point. One resolution covers every past and future line carrying that identifier, unless a later resolution supersedes it.
3. Resolutions are derived data (ADR 0013): an engine that writes them records the `logbook_head` it ran against, and a resolution whose evidence is retracted MUST be recomputed or retracted.
4. A registry is named, never assumed. Two resolvers may map the same `ref` to different registries; both lines stand.
5. Nothing in the format requires resolution. A log with no resolution lines is complete.

## Example (synthetic)

```json
{"at":"2026-03-02T09:14:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"resolution","tier":2,
 "payload":{"schema":"resolution/v1","ref":{"kind":"email","value":"ola@example.org"},
 "entity":{"type":"person","id":"p_0198","registry":"local"},"label":"Ola Nordmann","method":"owner"}}
```

## Notes

- **Places.** A `coordinate` ref resolves a *cluster*, not a fix: use it with an engine-derived stay, not with a single raw point. The `value` is then the stay line's id rather than a lat/lon pair.
- **Crossing.** In a crossing package (RFC 0005) resolution may be shipped as an overlay or left to the consumer; that is a deployment choice, and this profile is the same in both cases.
- **Privacy.** A resolution line is often more identifying than the raw line it resolves — it is the thing that turns an address into a name. Tier it by its evidence, and expect tier 2 in practice.
