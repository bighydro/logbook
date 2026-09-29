# Contributing

The easiest and most useful thing to build is an adapter for the export you already have.

1. Copy `adapters/template/`.
2. Put a small, **synthetic** export in `fixture/` — never real data, not even yours.
3. Write `run(input_path, since)` yielding observations with a `payload.schema`.
4. Run the tests; the expected output file is generated on first run and checked in.
5. Open a pull request. Name it `adapter: <source>`.

Rules for every contribution: no network calls unless the adapter is explicitly a live adapter; no writes to any source; nothing that updates or deletes a line in the log — if a change seems to need it, the change is wrong.

## What CI checks

Every pull request, and every push to `main`, runs: ruff and mypy; the test suite on Linux, macOS and Windows with Python 3.12 and 3.13; the conformance rule (`logbook verify` on `conformance/sample-logbook` prints the head in `conformance/expected.json`); the Nix and Docker builds; and `cross-impl`, which builds the independent TypeScript implementation ([bighydro/logbook-ts](https://github.com/bighydro/logbook-ts)) at its `main`, checks that its `verify` prints the same head on the sample, then appends one note to a copy of the sample with the Python CLI and verifies the copy with the TypeScript CLI. The two implementations must agree on a record the other wrote; a change to the spec or the hashing that only one of them follows fails here.

Code is Apache-2.0. Contributions to SPEC.md are CC0.
