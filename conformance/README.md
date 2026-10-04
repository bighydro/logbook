# Conformance

`sample-logbook/` is one week of a fictional person (Oslo, March 2026). Nothing in it is real. Its first sixteen lines are the v0.2 sample; the fifteen after them carry one payload of each profile added since (RFCs 0011–0024, and a location with a `subject`), fourteen on the Sunday and a keeper on the first photo's day, shaped as their RFCs describe, so a verifier meets every schema the reference implementation writes. Two of them reference an attachment by digest without a `path`, so there is nothing for `verify` to report missing.

Your implementation is conformant with format v0.3, Level 1, when (the sample is a `logbook/0.2` record, read as it is):

1. `verify` on `sample-logbook/` reports **valid** and prints the `seq` and `head` in `expected.json`;
2. appending one line to a copy of it yields a logbook that still verifies, with `seq + 1`;
3. changing any hashed field of any line (a content field of SPEC §3, `seq`, `prev`, `recorded_at` or `hash`), or deleting any line, makes `verify` fail (SPEC §6). `id` is outside the hash, and the stored form is not hashed: a change to `id`, or a re-serialisation that leaves the canonical form unchanged, is not detected.

Heads, as `expected.json` recorded them:

| Release | Lines | Head |
|---|---|---|
| v0.5.0 | 31 | `035a74e0027faa6872580c3c7b5f7a0efec92f15bb29cee400a6593814fd345c` |
| v0.2 – v0.4.1 | 16 | `53d39fdad121ce8e448221bbdaa9c86396c16347d050bf630035d6f1d37088e6` |

The first sixteen lines did not change between the two, so an implementation that reproduced the v0.2 head reproduces every hash of those lines still; only the tail is new.

## Level 2: the sealed sample

`sample-logbook-sealed/` is the same week with its tiers 2–3 sealed (SPEC §2 and §4, RFC 0029) to two recipients: the identity published in `identity.txt` (it opens this fixture and nothing else; never use it for a record) and the recipient in `recovery-recipient.txt`, whose identity is published nowhere. Its `logbook.json` is `logbook/0.3` and names both. The salts come from a seeded generator, so the head in `expected-sealed.json` is reproducible by anyone who regenerates the fixture; the ciphertext is not, and is outside the hash, so the files churn on regeneration while the head does not.

Your implementation is Level 2 conformant when, in addition to the three rules above:

4. `verify` on `sample-logbook-sealed/` **without** the identity reports valid, prints the `seq` and `head` in `expected-sealed.json`, and counts its sealed lines;
5. `verify` **with** `identity.txt` reports valid, the same head, and every sealed line opened and matching its digest;
6. changing any byte of a `payload_enc` leaves the keyless `verify` valid and makes the keyed one report invalid;
7. appending one tier-2 line to a copy seals it, and the other implementation opens it.

| Release | Lines | Head (sealed sample) |
|---|---|---|
| v0.6.0 | 31 | `c625fd32d553d6f2f64f04dd50858f63a894575f09d6d0d5063d74680e0b43e3` |

Regenerate with `python conformance/make_sample.py` (when the spec changes, or a profile is added; it changes the head, and this table gets a row).
