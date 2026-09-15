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

## The circle (layer 4/5, protocol to be defined)

A shared page is a signed bundle: the day's derived rows the owner chose to share, their notes marked shareable, photo references, and the owner's signature. Transport is undecided (peer-to-peer over a relay vs. a small server); the bundle format will be defined before any transport is built, so that the first two implementations can exchange pages by any means, including a USB stick.

## Reference stack

Python 3.12; layer 1 depends only on ijson (streaming JSON, so a multi-gigabyte export never has to fit in memory). Engines may use SQLite as an index; PostGIS is a plugin, never a requirement. Web layer: server-rendered HTML. Everything runs on one machine that is always on, or on a laptop that sometimes is.
