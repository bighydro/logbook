# RFC 0006 — payload profile `resolution/v1`

Status: draft · 2026-09-16 · comment period: two weeks

One statement that a source-native identifier refers to a known entity. Raw lines carry what their source gave — an email address, a phone number, a provider's participant name, a lat/lon. Turning those into an entity ("this is the same person as in that other line") is a *derived* judgement, and it belongs in its own line, never inside the raw one.

## Why this exists

The record must not depend on anything outside itself. An outside registry — a contact list, a company database, an interpreter's people table — changes and may be someone else's. So the raw line stays raw forever, people and companies get their ids in this record (ADR 0013), places reference open keys, and a resolution line records, at a point in time, what some resolver believed. If the resolver was wrong, its line is retracted (RFC 0003) and the raw line is untouched.

## Line

`kind` MUST be `resolution`. `tier` MUST be the highest tier of the evidence it refers to (SPEC §4: derived data inherits the highest tier of its evidence; a resolution over tier-2 lines is tier 2). `at` is when the resolution was made; `end` is null. `source` is the resolver: an engine name, an adapter, or `manual` when the owner said so.

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"resolution/v1"` | MUST | |
| `ref` | object | MUST | the source-native identifier being resolved, as it appears in the raw lines: `{ kind, value, source? }` where `kind` is one of `email`, `phone`, `handle`, `provider_id`, `device_id`, `domain`, or `line`, whose `value` is the `id` of a derived line (a stay) that stands for the thing being resolved |
| `entity` | object | one of | what it refers to: `{ type, id, registry }` where `type` is `person`, `place` or `company`. For `person` and `company`, `registry` MUST be `logbook` and `id` MUST be a UUID minted in this record (see Minting). For `place`, `registry` MUST be `wikidata` or `osm` and `id` is that registry's identifier (ADR 0013.3). A private or interpreter namespace MUST NOT appear as a registry; an interpreter stores a `logbook_ref` on its own side instead (ADR 0013.2) |
| `alias_of` | object | one of | another ref `{ kind, value }`, in the same form as `ref`: this ref and that ref are the same identity. The line names no entity; whatever that ref resolves to, this one does too (see Aliases) |
| `label` | string | SHOULD | a human-readable name at the time of resolution, for reading the log without any registry. MAY accompany either `entity` or `alias_of` |
| `confidence` | number | MAY | 0–1. Absent means asserted, not estimated |
| `method` | string | MAY | how it was decided: `exact`, `heuristic`, `model`, `owner` |
| `evidence` | array | MAY | ids of lines that justify it |
| `supersedes` | string | MAY | the id of an earlier resolution this replaces |
| `logbook_head` | hex sha256 | MAY | the chain head the resolver ran against (ADR 0013). An engine MUST set it (rule 3) |

A line carries exactly one of `entity` and `alias_of`, never both and never neither.

## Minting

An entity exists because a resolution names it. The first resolution for a new person or company mints a UUIDv7 as `entity.id`, with `registry` `logbook`, and carries `label`; later resolutions for other refs — a second email address, a phone number — reuse that id. There is no separate registry file: the log is the registry, and the set of entities is derived by reading every resolution line. Places are not minted; they reference a `wikidata` or `osm` id. A later profile MAY introduce another type along with the rules for minting it.

## Aliases

A source may know a person by an identifier that no contact list carries — a chat app's linked-device id, a second handle — while it also knows which phone number or address that identifier belongs to. An alias line records that pairing without minting anything: the entity comes from whichever line resolves the target ref. A `handle` aliased to a `phone` takes the phone's entity and label the moment the owner's contacts are imported, before or after the alias was written.

## Rules

1. A resolution never modifies the line it resolves. Readers join by `ref`.
2. A `ref` MAY match many lines — that is the point. One resolution covers every past and future line carrying that identifier, unless a later resolution supersedes it.
3. Resolutions are derived data (ADR 0013): an engine that writes them records the `logbook_head` it ran against, and a resolution whose evidence is retracted MUST be recomputed or retracted.
4. There is one id space per record. Conflicting resolutions of the same `ref` are resolved by `supersedes`: the last one wins.
5. Nothing in the format requires resolution. A log with no resolution lines is complete.
6. A reader resolves an alias by following `alias_of` to the target ref and resolving that ref normally — its own last line standing, by rules 3 and 4 — and so on while the line it reaches is itself an alias. It follows at most 4 hops and stops on a cycle (a ref already visited on this walk); it also stops at a ref with no line standing. The line the walk stops on decides: its `entity` and `label`, or none when it has none. Retraction (RFC 0003) and last-wins (rule 4) apply to an alias line exactly as to an entity line: a retracted alias resolves nothing, and a later line for the same ref — alias or entity — replaces it.

## Example (synthetic)

```json
{"at":"2026-03-02T09:14:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"resolution","tier":2,
 "payload":{"schema":"resolution/v1","ref":{"kind":"email","value":"ola@example.org"},
 "entity":{"type":"person","id":"019cadd3-6bc0-7dcd-9133-043f5aabf2a9","registry":"logbook"},"label":"Ola Nordmann","method":"owner"}}
```

An alias (synthetic): a WhatsApp linked-device id paired with the phone number the app knows it by. Once the owner's contacts import resolves `+4790000001` to Ola, every group message from `236000000000001@lid` reads as Ola's. Nothing is minted here.

```json
{"at":"2026-03-02T09:20:00Z","end":null,"tz":"Europe/Oslo","source":"whatsapp-contacts","kind":"resolution","tier":2,
 "payload":{"schema":"resolution/v1","ref":{"kind":"handle","value":"236000000000001@lid"},
 "alias_of":{"kind":"phone","value":"+4790000001"},"label":"Ola Nordmann","method":"exact"}}
```

## Notes

- **Places.** A place is resolved from a derived stay, not from a raw fix: the ref is `{ "kind": "line", "value": "<stay line id>" }`, and the entity is a `wikidata` or `osm` id. A single raw location point is never a ref.
- **Crossing.** In a crossing package (RFC 0005) resolution may be shipped as an overlay or left to the consumer; that is a deployment choice, and this profile is the same in both cases.
- **Privacy.** A resolution line is often more identifying than the raw line it resolves — it is the thing that turns an address into a name. Tier it by its evidence, and expect tier 2 in practice.
