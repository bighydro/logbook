# Contributing

The easiest and most useful thing to build is an adapter for the export you already have.

1. Copy `adapters/template/`.
2. Put a small, **synthetic** export in `fixture/` — never real data, not even yours.
3. Write `run(input_path, since)` yielding observations with a `payload.schema`.
4. Run the tests; the expected output file is generated on first run and checked in.
5. Open a pull request. Name it `adapter: <source>`.

Rules for every contribution: no network calls unless the adapter is explicitly a live adapter; no writes to any source; nothing that updates or deletes a line in the log — if a change seems to need it, the change is wrong.

Code is Apache-2.0. Contributions to SPEC.md are CC0.
