# Conformance

`sample-logbook/` is one week of a fictional person (Oslo, March 2026). Nothing in it is real. Its first sixteen lines are the v0.2 sample; the fourteen after them, all on the Sunday, carry one payload of each profile added since (RFCs 0011–0023, and a location with a `subject`), shaped as their RFCs describe, so a verifier meets every schema the reference implementation writes. Two of them reference an attachment by digest without a `path`, so there is nothing for `verify` to report missing.

Your implementation is conformant with format v0.2 when:

1. `verify` on `sample-logbook/` reports **valid** and prints the `seq` and `head` in `expected.json`;
2. appending one line to a copy of it yields a logbook that still verifies, with `seq + 1`;
3. changing any hashed field of any line (a content field of SPEC §3, `seq`, `prev`, `recorded_at` or `hash`), or deleting any line, makes `verify` fail (SPEC §6). `id` is outside the hash, and the stored form is not hashed: a change to `id`, or a re-serialisation that leaves the canonical form unchanged, is not detected.

Heads, as `expected.json` recorded them:

| Release | Lines | Head |
|---|---|---|
| v0.5.0 | 30 | `f50a9f8dd3ef872371396ab9326aa7488ee60b3ccf5afa788ac6927d82e6a890` |
| v0.2 – v0.4.1 | 16 | `53d39fdad121ce8e448221bbdaa9c86396c16347d050bf630035d6f1d37088e6` |

The first sixteen lines did not change between the two, so an implementation that reproduced the v0.2 head reproduces every hash of those lines still; only the tail is new.

Regenerate with `python conformance/make_sample.py` (when the spec changes, or a profile is added; it changes the head, and this table gets a row).
