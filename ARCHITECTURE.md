# Architecture — one package, three tiers

```
logbook/
  core/      the format and what is frozen with it: canonicalisation, the hash chain, the record and its
             index, the attachment store, the privacy tiers and the crossing policy, the day package, and
             the readers whose JSON a second implementation is held to (SPEC §3.2, §6.1): derive stays,
             day, days, trips, year, people, person, the pages, places, the rollups
  contrib/   what reads the world into the record and the record out into the world: the adapters (one
             registry, one module per source), import-backup, sync, setup's stores, the exports (vault,
             the paper edition, trip bundles), serve, the MCP server, the derived readers whose output is
             a reader's own (digest, promises, tasks, gaps, people merge, the trip page), the demo record
  labs/      everything that runs a model, or is still an experiment: transcribe, describe, promises
             --judge, demo --years
  commands/  the CLI, one module per command family; cli.py is the entry point
```

The arrow points down. Core imports core and nothing above it. Contrib imports core and contrib, never
labs. Labs and the commands import anything, and a command imports an adapter or a labs module only
inside the function that runs it, so `logbook --help` loads no adapter and no model code and
`import logbook.cli` imports nothing but the entry point. `logbook/layout.py` declares which module is
in which tier; `tests/test_layout.py` holds the tree to it, the arrow included. Every 0.5 import path
(`logbook.store`, `logbook.adapters.immich`) still imports, the same module object, with a
DeprecationWarning, until 0.7 ([docs/migration-0.6.md](docs/migration-0.6.md)).

## The layers, as the tiers carry them

```
5  Agents      any agent with MCP: add, ask, confirm, verify. the UI.          contrib/mcp_server
4  Surfaces    day page · timeline · person · year · paper · vault · shared    core readers, contrib exports
3  Engines     logbook → days, trips, people, places. versioned. recomputable. core
2  Adapters    one per source. export in → observations out. pure.            contrib/adapters
1  Logbook     the folder, the chain, the CLI. the standard.                   core, commands
```

An adapter never knows an engine exists. A surface reads derived rows and notes, never the raw log.
Agents are operators, not authors: they may run adapters and draft, they may never write a note, a
confirmation or a visibility decision — that stays with the human, enforced in layer 1.

| Layer | Contract | Where |
|---|---|---|
| 1 | the format (SPEC.md); `logbook add/show/verify/export` | `logbook/core/`, `logbook/commands/` |
| 2 | `run(input_path, since) -> iterator[Observation]`; fixture-tested; no network by default | `logbook/contrib/adapters/`, one module per source (ADR 0012); a third-party adapter is a package that registers the `logbook.adapters` entry point |
| 3 | a reader: `read(logbook, window) -> derived rows`, idempotent, stable derived IDs, never a line (ADR 0013, ADR 0019) | `logbook/core/` (frozen by SPEC §3.2), `logbook/contrib/` (a reader's own) |
| 4 | reads derived rows + notes; writes only notes and confirmations (as tier-2 lines) | `logbook serve`, `year --html`, `--print`, `export vault`, the shared page and trip bundle |
| 5 | MCP server exposing the record's readers over stdio | `logbook mcp` (`logbook/contrib/mcp_server.py`) |

Every layer ships in this one package. The second implementation, [logbook-ts](https://github.com/bighydro/logbook-ts), is a separate repository built from SPEC.md alone (CONTRIBUTING, the clean-room rule).

## Derived is disposable

Days, trips, people and places are computed from the log and can be thrown away. Their IDs are derived from (owner, kind, rounded start, place) so a recompute yields the same ID and human notes stay attached. Human input — notes, confirmations, visibility choices — is written to the log as tier-2 lines, so it survives any recompute and any export.

## The circle (layer 4/5, transport to be defined)

A shared page is a signed bundle: one day's lines the owner's policy lets cross, the attachments they point at, the day-package summary, and the owner's Ed25519 signature over the manifest — `shared-page/v1`, RFC 0025 (`docs/rfcs/rfc-0025-shared-page-bundle.md`), written by `logbook share day` and verified by `logbook receive`, which keeps the page beside the record and never in its chain. Transport is undecided (peer-to-peer over a relay vs. a small server); the bundle format came first, so that two implementations can exchange pages by any means, including a USB stick.

## Reference stack

Python 3.12 and the standard library: the format, the chain, the record, the index (SQLite) and every frozen reader need nothing installed beyond `tzdata` on Windows. What else a feature needs is an extra, named where the feature is: `openlogbook[stream]` (ijson, streaming JSON for the five adapters that read a multi-gigabyte export), `[encrypted]` (and its alias `[share]`: cryptography, for an encrypted iOS backup and the signed page), `[ais]`, `[transcribe]`, `[judge]`, `[describe]`, `[mcp]`. PostGIS is a plugin, never a requirement. Web layer: server-rendered HTML. Everything runs on one machine that is always on, or on a laptop that sometimes is: the record's home ([ADR 0022](docs/adr/0022-the-records-home.md)), which holds the only writable copy, runs the sync schedule, the MCP server and the local models, and serves the Day page over the owner's own network. Every other device is a reader, and an orchestrator elsewhere reaches the record only through the crossing.
