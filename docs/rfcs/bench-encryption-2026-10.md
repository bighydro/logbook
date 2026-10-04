# Benchmark — per-line sealing on a 3,000,000-line record

Status: **measured, 2026-10-02** · answers open question 1 of RFC 0029, encryption at rest (`0029-encryption-at-rest.md`) · script: `scripts/bench_seal.py` · no code or spec change.

## Summary

On a 3,000,000-line record with 2,000,000 tier 2–3 lines, per-line age through `pyrage` costs **128 µs a line to seal to one recipient and 214 µs to two** (the age call alone is 88 and 170 µs; the rest is the Option C wrapper, canonical JSON, salt, SHA-256 and base64, in Python), and **145 and 194 µs to open**. A plain line costs about 106 µs end to end on the same machine, so a sealed tier 2–3 line is 2.2 times a plain one at one recipient and 3 times at two. The 20,000 lines a second floor is 50 µs a line; per-line age spends 2.5 to 4 times that on the seal alone, so **the floor cannot hold for tier 2–3 under age and becomes tier-1-only**, with a floor of its own for sealed lines. Keyed `verify` of the record takes 7.7 minutes (one recipient) or 9.7 (two) against 2.6–2.9 keyless, index rebuild with opening 6.4 or 8 minutes against 1.2 plain, all in flat memory (27–35 MB). The record grows from 1.98 GB to 3.37 GB (one recipient) or 3.63 GB (two). The record data key of §9.1 seals in 40 µs and opens in 10 µs a line, verifies keyed in 3 minutes and adds 0.68 GB; it is the recommendation's comparison point, not its recommendation (see the end).

## Method

**The record.** `scripts/bench_seal.py` generates 3,000,000 synthetic lines in chain order, the shape of the stress tests in `tests/test_stress.py`: 1,000,000 tier-1 `location/v1` points (source `sim`), 1,000,000 tier-3 `health-sample/v1` lines of about a hundred bytes of payload (`type`, `value`, `unit`, `device`, a `raw_id`) and 1,000,000 tier-2 `message/v1` lines with about 550 characters of text (a `chat` in the reserved UK range, `from_me`, a `raw_id`). The three kinds are interleaved and `at` is spread evenly over the ten years from 2016-10 to 2026-09, so the record is 120 month files of 25,000 lines each. Everything is synthetic; the Oslo persona does not exist. Generation alone is timed (16.8 s) so the write phases can be read net of it.

**Option C as implemented.** For every tier 2–3 line, exactly as the draft's §4.3 and §5 say:

```
plain       = canonical_json({"payload": <the real payload>, "salt": <16 bytes from os.urandom, 32 lowercase hex>})
digest      = sha256(plain)                                   lowercase hex
payload     = {"schema": "sealed/v1", "digest": digest}      hashed, as any payload
payload_enc = base64(seal(plain))                            standard base64 with padding, outside the hash
```

`canonical_json` is `logbook.chain.canonical_json`, the product's RFC 8785 serialiser; nothing is reimplemented. `seal` is one of three:

- **age, 1 recipient** and **age, 2 recipients**: `pyrage.encrypt(plain, recipients)`, X25519 recipients, the identities generated fresh for the run. pyrage 1.4.0 (rage underneath). rage adds a random `-> …-grease` stanza to every header, so a ciphertext is about 100 bytes longer than the header arithmetic in the draft's §3 gives: a 171-byte plaintext seals to 466 bytes for one recipient and 564 for two, where §3 predicts 371 and 469. The second recipient costs 98 bytes, as §3 says.
- **data key** (the draft's §9.1 variant): one 32-byte key for the record, each line ChaCha20-Poly1305 under it with a fresh 12-byte nonce (`cryptography` 50 has no XChaCha, so the nonce is 12 bytes, not the 24 the draft names; the cost is the same), `payload_enc = base64(nonce + ciphertext)`.

**Writing.** The plain baseline is `Logbook.append_many`, the product's own path, index included. The sealed records cannot go through `append_many`: it hands each draft to `Logbook._line` as keyword arguments and `_line` knows no `payload_enc`. So the script carries a writer of its own that does what `append_many` does — drafts 10,000 at a time, the chain computed in memory through `Logbook._line`, the sealed line given its `payload_enc` after hashing (it is outside the hash), every batch written in the stored form `store._dumps` writes and fsynced, then `logbook.json`, then the index extended through `Index.add` with `index.row` (so a sealed line's `raw_id` column is NULL, as the draft's §8 says of an index built without the key). The plain record is written through this writer too, as a control: 317 s against `append_many`'s 339 s, 7% apart (the writer skips the dedupe SELECT), so the sealed columns below are comparable with the plain one. The seal step is timed per line inside the writer (two `perf_counter` calls a line, well under a microsecond), so "seal step alone" is canonical JSON + salt + SHA-256 + `seal` + base64, which is what Option C adds to a line; the primitives table isolates `seal` by itself.

**The phases, each in a subprocess of its own so the peak memory is that phase's:**

- *Open every sealed line*: stream the month files (`Logbook.lines_unsorted`), and for each `sealed/v1` line base64-decode, decrypt, compare `sha256(plain)` with `payload.digest` before parsing (§5 rule 6), parse. The decrypt-to-payload step is timed per line; the whole pass is timed too.
- *Keyless verify*: the chain, `chain.verify_lines` over `Logbook.lines()` (the two lines `Logbook.verify` is made of), plus, for every sealed line, that `payload_enc` is base64 of bytes beginning `age-encryption.org/v1\n` (for the data key: at least a nonce and a tag). The record's `logbook.json` must name the head reached. On the plain record it is the product's `Logbook.verify` itself.
- *Keyed verify*: the same chain pass, and every sealed line opened and its digest compared. Nothing is held: one line per month file, as `verify` today.
- *Index rebuild (plain)*: the product's `Logbook.index_rebuild`. *Index rebuild with opening*: the same pass (`located_lines`, `index.row`, one INSERT per 10,000 rows, one transaction) into a second SQLite file, every sealed line opened first so `raw_id`, `supersedes`, `entity` and `media` are filled.
- *Bytes on disk*: the sum of the month files; per line, the average stored length per kind, accumulated by the writer.
- *Memory*: `resource.getrusage(RUSAGE_SELF).ru_maxrss` at the end of each subprocess (kilobytes on Linux, bytes on macOS); `psutil`'s `peak_wset` on Windows when installed.
- *Primitives*: 100,000 health-sized and 100,000 message-sized plaintexts held in memory, sealed and opened each way with nothing else in the loop.

The exact command, on this machine:

```
uv run --with pyrage python scripts/bench_seal.py --out bench-linux.json --markdown
```

`--quick` is the same with 300,000 lines. pyrage is pulled in for the run only; it is not a dependency of the project. The whole run took 6,306 s (1 h 45 min) here.

## Machines

| Machine | Ran | Notes |
|---|---|---|
| **This machine**: a cloud container, Linux 6.18 x86_64 (glibc 2.39), 4 vCPU Intel Xeon at 2.10 GHz, 16.9 GB, Python 3.12.3, pyrage 1.4.0, cryptography 50.0.1 | yes, the full 3,000,000 lines | every number below. A slow core: the stress suite's own 200,000-point `append_many` test runs at 7,300 lines a second here (`LOGBOOK_SLOW=1`, measured the same day), against the 20,000 floor, so absolute rates are low and the ratios between columns are what carries over. |
| GitHub `ubuntu-latest` (4 vCPU, 16 GB) | **not run** | workflow in place, not dispatched; see below |
| GitHub `macos-latest` (arm64, 3–4 vCPU) | **not run** | same |
| GitHub `windows-latest` (4 vCPU, 16 GB) | **not run** | same; memory peaks there need `psutil`, which the workflow adds |

`.github/workflows/bench.yml` runs the same command on the three runners under `workflow_dispatch` only (never on push), with the line count as an input, and uploads each runner's JSON as an artifact. It could not be dispatched from the session that wrote this page: the GitHub connector and `gh` both answered `403 Resource not accessible by integration` on the dispatch endpoint (the session's token has no Actions write permission), so the three runner rows are empty and every number on this page is from the one machine above. The maintainer dispatches it from the repository's Actions tab (`bench`, branch `bench/encryption`; the default is the full 3,000,000 lines, `300000` is a short run of about ten minutes) and reads each runner's JSON from the run's artifacts; `scripts/bench_seal.py --markdown` prints the same tables from any of them.

## Results

This machine (the only one that ran), 3,000,000 lines, 2,000,000 of them sealed (1,000,000 health-sized, 1,000,000 message-sized). Rates are lines a second of the whole record; "per line" is per sealed line.

| Phase | plain | age, 1 recipient | age, 2 recipients | data key |
|---|---|---|---|---|
| Write the record, end to end (3,000,000 lines) | 339 s · 8,850 lines/s · peak 81 MB | 589 s · 5,093 lines/s · peak 110 MB | 785 s · 3,820 lines/s · peak 115 MB | 420 s · 7,147 lines/s · peak 103 MB |
| Seal step alone, per tier 2–3 line | — | 128 µs · 7,792 lines/s | 214 µs · 4,683 lines/s | 40 µs · 24,916 lines/s |
| Open, per sealed line (decode, decrypt, digest, parse) | — | 145 µs · 6,917 lines/s | 194 µs · 5,143 lines/s | 10 µs · 99,051 lines/s |
| Open every sealed line, whole pass | — | 324 s · peak 27 MB | 427 s · peak 27 MB | 49 s · peak 31 MB |
| Keyless verify | 175 s · 17,175 lines/s · peak 27 MB | 154 s · 19,527 lines/s · peak 27 MB | 160 s · 18,768 lines/s · peak 27 MB | 155 s · 19,391 lines/s · peak 27 MB |
| Keyed verify | — | 460 s · 6,526 lines/s · peak 27 MB | 583 s · 5,144 lines/s · peak 27 MB | 182 s · 16,487 lines/s · peak 31 MB |
| Index rebuild, plain | 69 s · 43,312 lines/s · peak 33 MB | — | — | — |
| Index rebuild with opening | — | 382 s · 7,850 lines/s · peak 35 MB | 481 s · 6,234 lines/s · peak 35 MB | 99 s · 30,351 lines/s · peak 41 MB |
| Month files on disk | 1.98 GB | 3.37 GB (+1.39 GB) | 3.63 GB (+1.65 GB) | 2.66 GB (+0.68 GB) |

The plain column's write is `append_many`; the script's writer wrote the same plain record in 317 s (9,478 lines/s, peak 81 MB). Net of the seal step the three sealed writes took 332, 358 and 340 s: writing a sealed line is otherwise as cheap as a plain one, a little more for the longer line. The writes' peak memory is the 10,000-line batch and its index rows; every reading phase stays at one line per month file, 27–41 MB whatever is being opened. Keyless verify is a little faster on a sealed record than on the plain one because a `sealed/v1` reference canonicalises in fewer bytes than a 600-character message.

### Per line, stored form

Bytes of the stored line (envelope included, which is about 400 bytes of it), and the ratio to the plain line:

| Line | plain | age, 1 recipient | age, 2 recipients | data key |
|---|---|---|---|---|
| health-sized (payload ≈ 110 B) | 513 | 1,127 (2.20×) | 1,258 (2.45×) | 772 (1.50×) |
| message-sized (payload ≈ 600 B) | 1,010 | 1,786 (1.77×) | 1,917 (1.90×) | 1,431 (1.42×) |
| location (tier 1, never sealed) | 460 | 460 | 460 | 460 |

`payload_enc` itself is 622 characters for a health-sized line and 1,284 for a message-sized one at one recipient; the second recipient adds 131 characters a line, 261 MB over the 2,000,000 sealed lines; the data key's is 268 and 928.

### The primitives alone

100,000 plaintexts of each size in memory, the salted canonical text Option C seals, nothing else in the loop (microseconds per operation; ciphertext bytes before base64):

| Plaintext | age, 1 recipient: seal / open | age, 2 recipients: seal / open | data key: seal / open | ciphertext bytes, 1 / 2 / key |
|---|---|---|---|---|
| health-sized, 171 B | 88 / 133 µs | 167 / 179 µs | 2.6 / 1.9 µs | 466 / 564 / 199 |
| message-sized, 667 B | 89 / 134 µs | 172 / 181 µs | 3.1 / 2.3 µs | 962 / 1,060 / 695 |

The size of the plaintext does not matter at these lengths; the cost is the key agreement. Opening is slower than sealing in pyrage. The difference between a primitive and the in-record "seal step alone" (40 µs for the data key, against a 3 µs cipher) is the Option C wrapper in Python — `canonical_json` of the payload with its salt, `token_hex`, SHA-256, base64 — about 37 µs a line, paid under every variant.

### Against the draft's §9 estimates

| §9 said | Measured here |
|---|---|
| Seal, Python via pyrage: 100–200 µs | 88 µs (age alone) and 128 µs (with the wrapper) to one recipient; 167 and 214 µs to two. Inside the range for one recipient, at its top for two. |
| Open: 60–120 µs | 133 and 145 µs to one recipient, 179 and 194 µs to two. Above the estimate: in pyrage opening costs more than sealing, not less. |
| Five to ten thousand sealed lines a second per core | 7,800 sealed, 6,900 opened a second to one recipient; 4,700 and 5,100 to two. One recipient is in the range; two is below it. |
| Keyed `verify` on two million sealed lines: three to seven minutes | 5.1 minutes more than keyless to one recipient, 7.1 to two (7.7 and 9.7 minutes in all). In the range; two recipients at its edge. |
| Keyless `verify`: unchanged | 154–160 s against 175 s on the plain record. Unchanged or better. |
| Index rebuild: the same opening pass as keyed verify, once | 382 and 481 s against 69 s plain; the difference is the opening, 313 and 412 s, the same as verify's. |
| Health-sized line about 2.5× its plain size, a 600-byte message about 1.7× | 2.20× and 1.77× at one recipient; 2.45× and 1.90× at two. The ciphertext is about 100 bytes longer than §3's arithmetic (rage's grease stanza) but the plain line is longer than §9 assumed too, so the ratios come out close. |
| Two million sealed health-sized lines add roughly 1 GB | 1,000,000 health-sized and 1,000,000 message-sized added 1.39 GB at one recipient. |
| 131 base64 characters a line per further recipient, 260 MB per two million lines | 131 characters, 261 MB. |
| Memory unchanged | Unchanged: 27–41 MB in every reading phase, as the plain record's 27–33. |
| §9.1 data key: opening a line one or two microseconds | 1.9–2.3 µs for the cipher, 10 µs with decode, digest and parse. |

## Recommendation

**Keep per-line age as the format's construction, make the 20,000 lines a second floor tier-1-only, and give sealed lines a floor of their own; do not adopt the record data key for the hot path now.** The numbers say the floor cannot hold for tier 2–3 under age on any machine: 20,000 lines a second is 50 µs a line and the age call alone is 88 µs to one recipient and 167 to two, before the line is hashed or written, so even a core twice as fast as this one spends the whole budget on the seal. A sealed-line floor of 4,000 lines a second at two recipients (this slow core does 4,683; a laptop core should do two to three times that — an estimate, not measured) states what the owner actually gets: a backfill of 1,000,000 health samples takes 4 to 7 minutes to seal over the 2 minutes it takes to write, once, and the nightly keyed `verify` of a 3,000,000-line record takes 8 to 10 minutes in 27 MB where the draft allowed three to seven. The data key would cut the seal step to 40 µs (three quarters of which is the Option C wrapper, which it shares with age) and keyed verify to 3 minutes, a real gain but a one-time one for backfills and a nightly one for verify, and it is bought with everything §9.1 lists: a long-term key in the record where the draft drew the line at "never"; a line the `age` CLI alone cannot open, so the format gains a construction of its own where it had a file format anyone can check; a writer that needs the identity to seal, losing `sync` from a machine that holds only the recipient (§6.3); and rotation as a reseal of every line instead of every header. None of those is worth four minutes on a backfill. Two things to carry into the spec text: the second recipient costs 85 µs to seal, 50 to open and 131 characters a line, so two recipients is the right default and five is a decision, as §9 said; and `show` of a day opens its sealed lines at 145–194 µs each, so a day of a few thousand sealed lines is a few tenths of a second and the under-a-second floor holds, but a day of 5,000 or more (heart rate by the minute plus steps by the quarter hour) is at the edge — if real health records show such days, the middle road §9.1 declines, the data key for `health-sample/v1` alone, is the thing to measure next, not a reason to adopt the key for everything.
