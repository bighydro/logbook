# Architecture — five layers

```
5  Agents      any agent with MCP: add, ask, confirm, verify. the UI.
4  Surfaces    day page · timeline · person · books · shared pages
3  Engines     logbook → days, trips, people, places. versioned. recomputable.
2  Adapters    one per source. export in → observations out. pure.
1  Logbook     the folder, the chain, the CLI. the standard.
```

The dependency arrow points down only. An adapter never knows an engine exists. A surface reads derived rows and notes, never the raw log. Agents are operators, not authors: they may run adapters and draft, they may never write a note, a confirmation or a visibility decision — that stays with the human, enforced in layer 1.

| Layer | Contract | Repo |
|---|---|---|
| 1 | the format (SPEC.md); `logbook add/show/verify/export` | this repo |
| 2 | `run(input_path, since) -> iterator[Observation]`; fixture-tested; no network by default | `logbook-adapter-<source>` |
| 3 | `pass(logbook, date_range) -> derived rows` carrying `engine_version`; idempotent; stable derived IDs | `logbook-engine` |
| 4 | reads derived rows + notes; writes only notes and confirmations (as tier-2 lines) | `logbook-web`, `logbook-books` |
| 5 | MCP server exposing `logbook.add`, `logbook.query`, `logbook.ask`, `logbook.confirm`, `logbook.verify` | `logbook-mcp` |

## Derived is disposable

Days, trips, people and places are computed from the log and can be thrown away. Their IDs are derived from (owner, kind, rounded start, place) so a recompute yields the same ID and human notes stay attached. Human input — notes, confirmations, visibility choices — is written to the log as tier-2 lines, so it survives any recompute and any export.

## The circle (layer 4/5, transport to be defined)

A shared page is a signed bundle: one day's lines the owner's policy lets cross, the attachments they point at, the day-package summary, and the owner's Ed25519 signature over the manifest — `shared-page/v1`, RFC 0025 (`docs/rfcs/rfc-0025-shared-page-bundle.md`), written by `logbook share day` and verified by `logbook receive`, which keeps the page beside the record and never in its chain. Transport is undecided (peer-to-peer over a relay vs. a small server); the bundle format came first, so that two implementations can exchange pages by any means, including a USB stick.

## Reference stack

Python 3.12; layer 1 (the folder, the chain, the CLI) is standard library only. The package's one runtime dependency, ijson, belongs to layer 2: the Google Takeout and Dawarich adapters stream their JSON exports through it, so a multi-gigabyte export never has to fit in memory. Engines may use SQLite as an index; PostGIS is a plugin, never a requirement. Web layer: server-rendered HTML. Everything runs on one machine that is always on, or on a laptop that sometimes is.
