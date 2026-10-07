# RFC 0005 — bundle format `crossing-package/v1`

Status: draft · 2026-09-16 · comment period: two weeks

## Summary

The file bundle Logbook exports to a member of the owner's circle (ADR 0009) — "the crossing." It carries
the subset of the log that policy lets cross, copies of the content-addressed blobs those lines reference,
and enough provenance to be reproducible. Hermes is the first consumer; the format names no consumer.

## Relation to `day-package/v1`

`crossing-package` does **not** replace `day-package/v1`; they sit side by side with opposite privacy
properties, and both stay:

- **`day-package/v1`** — a *safe index of a day*: identity and shape, and **never a payload** (see
  `logbook/core/export.py` `entry()`). A lightweight overview you can share widely.
- **`crossing-package/v1`** — verbatim log lines **including their payloads**, plus the referenced blobs. A
  selective-disclosure export for a trusted circle member.

Use a day package to show *that* a day happened; a crossing package to hand over *what* was in it.

## Shape

A crossing package is a directory (or a tar of one):

```
<bundle>/
  manifest.json          # this schema
  entries.jsonl          # the crossed log lines, verbatim (the standard envelope)
  attachments/<sha256>   # copies of the content-addressed files referenced by crossed lines (SPEC §1.1 layout)
  resolution.jsonl       # OPTIONAL — derived id resolutions (see Resolution)
```

Files, not an API: a circle member **pulls** the bundle (a private git repo or an rsync target is fine for
v1). The bundle is regenerable from the log at `logbook_head`.

## `manifest.json`

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"crossing-package/v1"` | MUST | |
| `bundle_id` | string | MUST | uuid for this export |
| `generated_at` | RFC3339 UTC | MUST | when the bundle was produced |
| `owner` | string | MUST | the log owner's id |
| `recipient` | string | MUST | the circle member this bundle is for (e.g. `hermes`) — data, not schema |
| `logbook_head` | hex sha256 | MUST | the chain head at generation — the log state this reflects (provenance; see Verification) |
| `covers` | object | MUST | the selection: `{ from, to }` (RFC3339) for a window, or `{ since_head }` for a delta since a prior head |
| `policy` | object | MUST | the crossing policy applied, for audit — see Tier & carve-out |
| `counts` | object | SHOULD | audit totals: `{ logged, crossed, held_back }` |
| `entries_file` | string | MUST | path to the crossed lines (`entries.jsonl`) |
| `blobs` | array | SHOULD | `[{ sha256, path, bytes, media_type }]` for the content-addressed files included — the SPEC §1.1 reference shape, with `path` the record-relative store path (`attachments/<sha256>`), so a crossed line's verbatim `content.path` resolves inside the bundle |
| `resolution_file` | string | MAY | path to `resolution.jsonl`, if a derived resolution overlay is shipped |

## Entries

`entries.jsonl` is the crossed log lines **verbatim** — the same envelope as the log
(`at, end, tz, source, kind, tier, payload, …`), a subset chosen by `policy`. No line is rewritten on
crossing; a held-back line is simply absent. Lines keep their source-native ids — identity is resolved
separately (Resolution). Since RFC 0034 the subset is, by default, the lines of the days the owner has
signed (`policy.signed_days` is `only`; `any` when the owner asked for `--unsigned`), and `counts`
carries `held_back_unsigned`.

## Blobs

Copies of the content-addressed files the crossed lines reference (e.g. a `transcript/v1` `content.sha256`),
laid out under `attachments/<sha256>` — the same record-relative path SPEC §1.1 gives them. Because
`entries.jsonl` crosses **verbatim**, a line's `content.path` is already `attachments/<sha256>`, so it
resolves inside the bundle without any rewrite; a consumer MAY instead resolve by `sha256`, and MUST verify
each file by hashing it. Each appears once. Addressing and store semantics are per SPEC §1.1 — this format
only ships copies of the referenced files, it does not define the store. A held-back line's file does not cross.

## Verification

A crossing package is **not chain-verifiable.** Each line's own hash recomputes, but because the set is a
subset of the chain with gaps, a recipient **cannot** verify it against `logbook_head`. This is inherent to
selective disclosure: provenance here is `logbook_head` + `policy` + each line's own hash, not a chain
replay. A consumer MUST NOT expect the full chain.

## Resolution

Raw lines carry source-native ids (an email, a phone, a provider participant name, a lat/lon). Turning those
into shared ids (a backbone person id, a Wikidata place QID) is a **derived pass**, never part of the raw
line. Placement is a deployment choice:

- **Consumer-side (recommended — and the choice for the first deployment).** The bundle omits
  `resolution.jsonl`; the consumer resolves source ids against its own registry, so the exporter depends on
  nothing outside its own record.
- **Exporter-side.** The exporter runs a resolution pass and ships `resolution.jsonl` — `resolution/v1`
  lines (RFC 0006): each `{ ref: { kind, value, source? }, entity: { type, id, registry }, … }` stating the
  entity a source-native id refers to. A consumer joins an entry to its entity by `ref`.

`resolution_file` is OPTIONAL, so the choice is a deployment decision, not a format change. Either way the
crossed lines stay raw — resolution is a separate overlay (RFC 0006), never written back into a line.

## Tier & carve-out

`policy` records exactly what crossed and why:

```json
{"version":"1","tiers":{"1":"auto","2":"reviewed","3":"never"},"carve_outs":["investment-finance"]}
```

Tier 1 crosses automatically; tier 2 after a batched review — a bundle is reviewed as a whole, never line by
line (cf. ADR 0005, "one evening message"); tier 3 never — except the standing carve-out (investment-finance).
Given `logbook_head` and `policy`, the crossing is reproducible, and the split between "what arrived" (the
log) and "what crossed" (this bundle) is auditable.

## Sealed lines (RFC 0029)

A record that seals tiers 2–3 holds such a line with a `payload` that is a reference (`sealed/v1`: `of`, `digest`)
and the content in `payload_enc`, outside the hash. The line's hashed fields cross **verbatim**, as every line
does; only `payload_enc` is replaced, in one of two ways, named by the manifest's `sealing` field:

- `{"lines": N, "mode": "resealed", "recipient": "age1…"}` — `policy/crossing.json` gives the destination an age
  recipient (`{"hermes": {"max_tier": 2, "recipient": "age1…"}}`), and `payload_enc` is the content resealed to it.
  The member opens each line with its own identity, checks that the SHA-256 of the opened bytes is
  `payload.digest`, and recomputes the line hash from the envelope as before.
- `{"lines": N, "mode": "opened"}` — the destination has no recipient and the owner typed `--open`: `payload_enc`
  is absent and `payload_open` carries the pre-image `{"payload": …, "salt": "…"}` as an object. The member
  canonicalises it (RFC 8785), hashes it, and compares with `payload.digest`.

A sealed attachment crosses under its plaintext digest the same two ways: resealed to the destination, or opened.
Without a recipient and without `--open` the export refuses; so does an exporter without the owner's identity.
A package therefore never carries ciphertext its reader cannot open, and the owner's hashes are never recomputed
for it.

## Notes

- **Delta or window.** `covers.since_head` lets a consumer pull only what is new since it last acknowledged
  a head; `covers.from/to` gives a bounded window (e.g. one day). Whether the consumer then ingests
  per-source or per-day is its own concern, not the bundle's.
- **No consumer name in the format.** `recipient` is data; the standard stays generic and reusable by any
  circle member.
- Consumers MUST ignore unknown manifest fields.
