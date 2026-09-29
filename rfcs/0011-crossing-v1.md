# RFC 0011 — payload profile `crossing/v1`

Status: draft · 2026-09-29 · comment period: two weeks

One line saying that a crossing package (RFC 0005) left the record: for whom, which window, how much of each tier, under what policy, and the digest of what was written. Produced by `logbook export crossing` after every real export, never after a dry run. The package is a view and can be thrown away; the fact that it crossed stays in the chain (ADR 0016: a crossing is never invisible).

## Line

`kind` MUST be `crossing`. `tier` MUST be 1: the line names counts, a destination and digests, never what any line said. `at` is when the package was generated; `end` is null. `source` is `logbook`: the tool wrote it, not the owner and not an adapter.

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"crossing/v1"` | MUST | |
| `destination` | string | MUST | the circle member the package is for, as the manifest's `recipient` |
| `bundle_id` | string | MUST | the manifest's `bundle_id` |
| `window` | object | MUST | `{ from, to }`, RFC3339 UTC: the lines with `from` ≤ `at` < `to` were considered |
| `tiers` | array of integer | MUST | the tiers the owner asked to cross: `[1]`, `[1, 2]` or `[1, 2, 3]` |
| `counts` | object | MUST | the manifest's `counts`: `logged`, `crossed`, `held_back`, `by_tier`, `by_kind`, the resolution and attachment counts |
| `policy` | object | MUST | the ceiling in force: `{ file, max_tier }`, `file` the record-relative policy path (`policy/crossing.json`) |
| `logbook_head` | hex sha256 | MUST | the chain head the package reflects — the head before this line |
| `package_sha256` | hex sha256 | MUST | the digest of the package's `manifest.json` bytes; the manifest names the digest of every other file in the package (`entries_sha256`, `resolution_sha256`, `blobs[].sha256`), so this one digest covers the whole bundle |

Anything else MAY be kept under `extra`.

## Rules

1. A crossing line is appended after the package is completely written and its manifest hashed, and before the watermark moves. A crash between the two leaves a package no line names; the next export covers the window again.
2. A dry run appends nothing.
3. `logbook_head` is the head *before* this line. The package cannot contain the line that records it; the next window does.
4. A crossing line is tier 1 and crosses like any other line. A reader that finds one in a package learns that the record crossed to someone at that time, and nothing else.
5. Readers that count what left the record (a `stats` of crossings, an audit) join `destination` and `window` across every crossing line; the watermark file is bookkeeping and may be lost.

## Example (synthetic)

```json
{"at":"2026-03-02T02:00:00Z","end":null,"tz":"Europe/Oslo","source":"logbook","kind":"crossing","tier":1,
 "payload":{"schema":"crossing/v1","destination":"hermes","bundle_id":"019cadd3-6bc0-7dcd-9133-043f5aabf2b0",
 "window":{"from":"2026-03-01T00:00:00Z","to":"2026-03-02T00:00:00Z"},"tiers":[1,2],
 "counts":{"logged":7,"crossed":6,"held_back":1,"by_tier":{"1":2,"2":4,"3":0},"by_kind":{"location":2,"message":3,"note":1},
 "resolutions":2,"resolutions_held_back":0,"attachments":{"included":1,"bytes":48213,"missing":1}},
 "policy":{"file":"policy/crossing.json","max_tier":2},
 "logbook_head":"53d39fda0b4d7a1e3c9f8e2d1a0b6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f0a9b",
 "package_sha256":"9afdd1bd5f7e4c3b2a1908f7e6d5c4b3a291807f6e5d4c3b2a1908f7e6d5c4b3"}}
```

## Notes

The first consumer pulls nightly and unattended; the reason this line exists is that the owner, reading the record a month later, finds the crossing on the day it happened, with its counts and ceiling, and that `verify` covers the fact.
