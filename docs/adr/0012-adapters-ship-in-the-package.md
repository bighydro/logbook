# ADR 0012 — Adapters built by the project ship inside the package

Status: accepted · 2026-09-14

**Context.** ARCHITECTURE.md places adapters in layer 2 and lists them as separate repositories (`logbook-adapter-<source>`). The first one the captain needs, `dawarich` (ADR 0008, amendment), is small: one file, one fixture, no dependencies. A separate repository, package, release train and version pin for every such adapter is more ceremony than code, and `logbook add <export>` should work out of the box for the sources the project itself maintains.

**Decision.** Adapters built by the project live inside the package, one module each under `logbook/adapters/`. Third-party adapters are separate packages that register the `logbook.adapters` entry point. The CLI discovers both through one registry (`logbook.adapters.all_adapters()`), built-ins first.

Every adapter, built-in or not, is a module exposing three names:

- `NAME: str` — the `source` its lines carry, lowercase, dashes only.
- `sniff(path) -> bool` — "is this file mine?"; cheap, reads only what it must, never raises.
- `run(path, since=None) -> Iterator[dict]` — line drafts with exactly `at, end, tz, source, kind, tier, payload` (SPEC §2 minus the chain fields, which `Logbook.append` adds). `tz` may be `None`, meaning the logbook's own timezone. `since` is RFC3339 UTC.

`logbook add <path>` asks each registered adapter to sniff the file, runs the first that says yes, and appends through `Logbook.append_many`, which skips any draft whose `(source, payload.raw_id)` is already in the log so that re-adding an export appends nothing. `add` also accepts a folder and processes every file in it.

**Rationale.** The contract is what matters, not the packaging. Keeping the project's own adapters in-tree means one test suite, one `uv run pytest`, one release, and a working `add` on day one. The entry point keeps the door open for adapters the project does not want to own: proprietary sources, sources needing heavy dependencies, sources with a different release cadence. Both kinds are found the same way, so moving an adapter in or out of the package is a packaging change, not an API change.

**Consequences.**
- `logbook/adapters/<name>.py` + `tests/fixtures/<name>/` + tests is the whole cost of a built-in adapter. The rules of `adapters/README.md` still apply: synthetic fixtures only, no network on the default path, never write to the source.
- The template in `adapters/template/` gains `NAME` and `sniff` so a copy is registrable as-is.
- The layer-2 row in ARCHITECTURE.md ("Repo: `logbook-adapter-<source>`") now describes third-party adapters; built-ins are in this repo.
- Dedupe on `(source, raw_id)` is a property of `append_many`, not of any adapter; an adapter that wants idempotent re-adds gives every line a stable `raw_id`.
