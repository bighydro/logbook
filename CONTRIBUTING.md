# Contributing

Code is Apache-2.0. Contributions to SPEC.md are CC0. Read [SPEC.md](SPEC.md) and [ARCHITECTURE.md](ARCHITECTURE.md) first; the record's rules are there, and a change that needs to break one is wrong.

## Every pull request

- **One issue per PR.** Open or pick an issue first; the PR closes it and nothing else. Unrelated changes go in another PR.
- **Commits are signed and signed off.** Register an SSH signing key on GitHub ([docs](https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification#ssh-commit-signature-verification)), set `gpg.format ssh` and `user.signingkey`, and commit with `git commit -s -S`. `git log -1 --format='%G?'` prints `G` when it worked; the PR shows *Verified*.
- **Tests on synthetic data only, never a real record.** Fixtures, tests, examples and PR text carry no one's personal identifiers — not yours, not a friend's, not a public figure's. The sample person lives in Oslo and does not exist; addresses are at `example.org`; phone numbers come only from reserved fictional ranges (the UK's `07700 900xxx`, or the Oslo persona's numbers already in the fixtures). A pre-commit hook (`scripts/check_pii.py`) greps every added line against a local list of your own identifiers; set it up once and it stops you before CI does.
- **No network calls** in an adapter's default path; **no writes** to any source; **nothing that updates or deletes a line** in the log.
- **CI must be green** before review. A first-time contributor's workflow runs wait until a maintainer approves them; that is GitHub's default for new contributors, not a judgement on the PR.

## Adapters

The easiest and most useful thing to build is an adapter for the export you already have.

1. Copy `adapters/template/`.
2. Put a small, **synthetic** export in `fixture/` — never real data, not even yours.
3. Write `run(input_path, since)` yielding observations with a `payload.schema`.
4. Run the tests; the expected output file is generated on first run and checked in.
5. Open a pull request. Name it `adapter: <source>`.

A source that has both an export and a live API is one adapter with one mapping: backfill and live share it, so the same observation arrives once, with one shape and one `raw_id`, whichever way it came ([ADR 0017](docs/adr/0017-backfill-and-live-share-one-mapping.md)).

## What CI checks

Every pull request, and every push to `main`, runs: ruff and mypy; the test suite on Linux, macOS and Windows with Python 3.12 and 3.13; the conformance rule (`logbook verify` on `conformance/sample-logbook` prints the head in `conformance/expected.json`); the Nix and Docker builds; and `cross-impl`, which builds the independent TypeScript implementation ([bighydro/logbook-ts](https://github.com/bighydro/logbook-ts)) at its `main`, checks that its `verify` prints the same head on the sample, then appends one note to a copy of the sample with the Python CLI and verifies the copy with the TypeScript CLI. The two implementations must agree on a record the other wrote; a change to the spec or the hashing that only one of them follows fails here.
