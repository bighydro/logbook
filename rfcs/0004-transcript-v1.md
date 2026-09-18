# RFC 0004 — payload profile `transcript/v1`

Status: draft · 2026-09-16 · comment period: two weeks

## Summary

One transcript of a spoken interaction — a meeting, a call, a voice note — as a single line. Sources:
Granola, Fireflies, Otter, PLAUD, or a manual recorder. The line records **only what the source produced**;
identity resolution and any model-extracted structure are separate, derived layers (see Notes).

## Line

- `kind` MUST be `transcript`.
- `tier` SHOULD be 2 (spoken personal content).
- `at` is the start of the interaction; `end` is its end, or null if the source gives no duration.
- `source` is the adapter that produced the line (e.g. `granola`, `fireflies`, `plaud`, `manual`).

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"transcript/v1"` | MUST | |
| `provider` | string | MUST | the tool that produced the transcript: `granola`, `fireflies`, `otter`, `plaud`, `manual` |
| `raw_id` | string | SHOULD | the provider's own stable id for this transcript — the dedup key |
| `title` | string | SHOULD | the provider's title, verbatim |
| `participants` | array | SHOULD | the people the source names, **source-native — never resolved here** (see Notes). Each: `{ name, email?, phone?, provider_id? }` |
| `summary` | string | MAY | the provider's OWN summary, if it produced one. A model-written summary MUST NOT go here — it is derived (see Notes) |
| `language` | string | MAY | BCP-47 tag of the dominant language |
| `content` | object | SHOULD | the full text, held as an attachment (**never inline**), an attachment reference per SPEC §1.1: `{ sha256, path, bytes, media_type }`, `media_type` one of `text/markdown`, `text/vtt`, `text/plain`, `application/json`. This profile only references the file; where it lives and how `verify` treats a missing one is SPEC §1.1 |
| `source_uri` | string | MAY | a link back to the transcript in the provider |

## Example (synthetic)

```json
{"at":"2026-03-01T13:00:00Z","end":"2026-03-01T13:35:00Z","tz":"Europe/Oslo","source":"granola","kind":"transcript","tier":2,"payload":{"schema":"transcript/v1","provider":"granola","raw_id":"note_7f3a2b","title":"Catch-up with Ines","participants":[{"name":"Ines","email":"ines@example.org"},{"name":"Ola Nordmann"}],"summary":"Ines is moving to Tromsø in May; talked over a northern-lights trip.","language":"en","content":{"sha256":"9f2b1c…","path":"attachments/9f2b1c…","bytes":48213,"media_type":"text/markdown"},"source_uri":"https://granola.example/notes/7f3a2b"}}
```

## Notes

- **Raw, not resolved.** `participants` carry the source's own identifiers (a name, and any email / phone /
  provider id the source gives). Mapping a participant to a shared person id is a derived pass, not this
  profile — proposed separately as `resolution/v1`. A line is complete and portable without it.
- **The provider's words, not a model's.** `summary` is only for a summary the *source* produced. Anything a
  model extracts from the transcript — decisions, action items, entities — is a separate, draft-until-accepted
  layer that *references* this line by `raw_id`; it does not belong in `transcript/v1`.
- **The text is never in the log; the line points at it.** `content` references a file by `sha256` in the
  content-addressed attachment store (SPEC §1.1 — this profile does not introduce it).
  Re-importing the same transcript yields the same `sha256`, so it de-duplicates.
- A voice note with a single speaker is still a `transcript`: `participants` MAY be empty or a single
  self-entry.
- Consumers MUST ignore unknown payload fields and MUST NOT reject a line for an unknown `participants`
  sub-field.
