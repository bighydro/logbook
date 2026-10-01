# Logbook format — specification v0.2

Status: draft. License: CC0. Anyone may implement this without asking.

The key words MUST, MUST NOT, SHOULD and MAY are to be interpreted as described in RFC 2119.

## 1. The folder

```
<root>/
  logbook.json            identity and chain head
  logbook/<YYYY>/<MM>.jsonl   the record
  notes/<YYYY>/<YYYY-MM-DD>.md   free text, optional
  attachments/<sha256>    optional; content-addressed files a line points at (§1.1)
  inbox/                  optional; not part of conformance
  index.sqlite            optional; a derived locator, disposable (ADR 0007); not part of conformance
```

`logbook.json`:

```json
{"format": "logbook/0.2", "owner_id": "<uuid>", "created_at": "<RFC3339 UTC>",
 "timezone": "<IANA tz>", "seq": 4181, "head": "<hex sha256>",
 "lineage": [{"from_format": "logbook/0.1", "from_head": "<hex sha256>", "migrated_at": "<RFC3339 UTC>"}]}
```

`seq` and `head` are those of the last line in chain order (§3). A record with no lines has `seq` 0 and `head` GENESIS. **GENESIS** is the string of 64 ASCII `0` characters, `0000…0000`; it is a named constant, not the digest of anything, and it is also the `prev` of the first line (§3).

`lineage` is present only in a record that was migrated from an earlier format (§3.1).

Writers MUST preserve keys of `logbook.json` they do not know: read the file, change `seq` and `head`, write everything else back. An implementation that rewrites the file from a fixed set of keys drops `lineage`, and whatever a later version adds, the first time it appends.

### 1.1 Attachments

Some observations refer to a file too large, binary or private to put in a line: a transcript, a photo, a voice message. A line MUST NOT inline such content. The file is stored once, named by its own SHA-256, and the line points at it.

A file lives at `<root>/attachments/<sha256>`, where `<sha256>` is the lowercase hex digest of the file's exact bytes: no extension, no subdirectories.

A payload references it as an object of this shape:

```json
{"sha256": "<hex sha256>", "path": "attachments/<hex sha256>", "bytes": 48213, "media_type": "text/markdown"}
```

`path` is relative to the record root. `bytes` is the length of the file. `media_type` is an IANA media type. A profile MAY name the field as it likes (`content`, `media`, `attachments`) but MUST use this shape.

The store is write-once: a digest is written once and never rewritten. Two lines that point at the same bytes share one file; this is how re-importing a source de-duplicates. Attachments are record, not cache (ADR 0001): they are never pruned.

The chain covers lines, not bytes. The digest is inside the line, so tampering with the file is detectable, but the file is not in the hash chain. `verify` MUST NOT fail because an attachment is missing; it MUST report missing attachments separately and exit 0 when the chain is intact. A verifier MAY check the digests of present files; a file whose bytes do not match its name **is** an error.

A record with no `attachments/` directory is valid. Conformance (§6) does not require the store.

## 2. The line (the envelope)

One observation per line, JSON, UTF-8, newline-terminated, in `logbook/<YYYY>/<MM>.jsonl`, where YYYY and MM are taken from `at` in UTC.

Placement is a writer's obligation, not a validity condition. A writer MUST put a line in the month file of its `at`. A reader takes every line of every `logbook/*/*.jsonl` file and verifies it by §3 wherever it was found; a line in the wrong month file is verified normally. A reader other than `verify` MAY rely on placement: to list a day it MAY read only the month files that day's instants can fall in, and a line it misses because a writer put it in another month file is that writer's bug, not the reader's.

The stored form of a line is any JSON text for the object on one line: UTF-8, no embedded newline (the newline ends the line), any key order, any whitespace. Only the canonical form (§3) is hashed, so re-serialising a line changes nothing. A reader ignores an empty or whitespace-only line. A line whose JSON text gives the same key twice in one object, at any depth, is invalid.

| Field | Type | Meaning |
|---|---|---|
| `id` | uuid | UUIDv7 (RFC 9562) recommended; identity of this line; outside the hash so it may be assigned at write time |
| `seq` | integer ≥ 1 | position in the owner's chain; strictly increasing by 1 |
| `at` | RFC3339 UTC | when the thing happened (not when it was recorded) |
| `end` | RFC3339 UTC or null | when it stopped, if it had a duration; `null` otherwise, never absent |
| `tz` | IANA name | the owner's timezone at `at` |
| `source` | string | who reported it: `manual`, `apple-health`, `google-takeout`, … |
| `kind` | string | what it is: `location`, `photo`, `event`, `message`, `sleep`, `note`, … |
| `tier` | 1, 2 or 3 | privacy tier, §4 |
| `payload` | object | whatever the source said; MUST contain `schema`, e.g. `"location/v1"` |
| `recorded_at` | RFC3339 UTC | when the line was written |
| `prev` | hex sha256 | hash of the previous line; GENESIS (§1) for the first |
| `hash` | hex sha256 | §3 |

Every field in the table is present in every line. `end` is `null` when the observation has no duration or its end is unknown; it is never omitted. Absent and null are different inputs to the hash: an object without `end` and one with `"end":null` canonicalise to different bytes. Writers MUST emit `null`.

`at`, `end` and `recorded_at` are RFC 3339 date-times in UTC with the literal `Z` designator, as in `2026-03-01T07:30:00Z`; a numeric offset such as `+00:00` MUST NOT be used. Fractional seconds are permitted. The string is hashed verbatim, so `07:30:00Z` and `07:30:00.000Z` are different inputs. They are the same instant: timestamps compare as the instants they denote, never as text (`07:30:00.5Z` is after `07:30:00Z`, though it sorts before it as a string).

`tz`, and `timezone` in `logbook.json`, are IANA zone names. This spec names no edition of the zone database, so a name may be known to one reader and not another (`Europe/Kyiv` and `Europe/Kiev` are the same zone under two editions). `verify` does not interpret `tz`, so no zone name makes a record invalid. A reader that must localise a time and does not know the zone MUST say so; it MUST NOT silently substitute another zone.

Unknown fields MUST be preserved by readers and MUST NOT be added by writers at the top level; extensions go inside `payload`.

## 3. The chain

```
content = canonical_json({at, end, tz, source, kind, tier, payload})
hash    = sha256( prev + "|" + seq + "|" + sha256(content) + "|" + recorded_at )
```

`canonical_json` is RFC 8785 (JSON Canonicalization Scheme): keys sorted by UTF-16 code units, no whitespace, UTF-8, ES6 number serialisation, no NaN/Infinity.

In the pre-image, `prev` and `sha256(content)` are lowercase hex, `seq` is decimal with no padding and no sign, `recorded_at` is the string exactly as written in the line, and `|` is U+007C. Every hex digest in this format, in a pre-image and as written in a file, is lowercase; a verifier compares digests as strings, so an uppercase digest does not verify.

A logbook is **valid** when, taking every line from every file and ordering by `seq` (files partition by the month of `at`, so backfilled history lands in old files; file order is not chain order):

- every line meets §2: `payload.schema` is present, `tier` is 1, 2 or 3, and `seq` ≥ 1;
- no two lines share a `seq`; when they do, the verifier reports the second occurrence;
- every line's `seq` is the previous plus one, the first being 1;
- every `prev` equals the previous `hash`, the first being GENESIS;
- every `hash` recomputes;
- `logbook.json` `seq`/`head` match the last line, or are 0 and GENESIS when there is none.

A verifier checks the envelope requirements of §2 as well as the chain: a line that chains correctly but has no `payload.schema` or a `tier` outside 1..3 makes the record invalid.

**Write order.** A writer appends in this order: the line, or the batch of lines, to its month file, flushed and fsynced; then `logbook.json`, written to a temporary file and renamed into place so it is never half-written; then any index. A crash therefore leaves the files ahead of `logbook.json`, never behind: every line `logbook.json` names is on disk, and any lines past its `seq` are a complete, chained tail. Until `logbook.json` is brought forward, `verify` reports such a record invalid by the last rule above.

Corrections are new lines. A source that revises an earlier record writes a new line with `payload.supersedes = "<id>"`. Nothing is ever rewritten or removed. A line that should be hidden rather than corrected is retracted: a new line of kind `retraction` whose payload supersedes it (RFC 0003, `retraction/v1`); readers mark it and never drop it.

### 3.1 Format versions

`logbook.json` `format` names the rule the record's hashes were computed with.

| Format | Canonicalisation |
|---|---|
| `logbook/0.1` | Python's `json.dumps(sort_keys=True, separators=(",", ":"))`. It deviated from RFC 8785 in float layout (`0.0` and `120.0` instead of `0` and `120`; `1e-06` instead of `0.000001`; exponent form from 1e16, not 1e21) and in key order (Unicode code points, not UTF-16 code units). |
| `logbook/0.2` | RFC 8785 exactly, as §3 says. |

Canonicalisation is fixed, not versioned (ADR 0014): a conformant implementation carries one rule and MUST refuse to verify or write a `logbook/0.1` record. Such a record MUST be migrated forward. A migration keeps every line's `id`, `seq`, content fields and `recorded_at` unchanged, recomputes `prev` and `hash` in `seq` order under the 0.2 rule, sets `format` to `logbook/0.2`, appends `{from_format, from_head, migrated_at}` to `lineage` in `logbook.json`, and then appends one line — `source` `manual`, `kind` `migration`, `tier` 1, payload `{"schema": "migration/v1", "from_format": "logbook/0.1", "from_head": "<old head>"}` — so that the fact of the migration, and the head it replaced, are inside the chain. The old head stays reproducible from the old files with the old rule; nothing else about the record changes.

### 3.2 Readers

A reader here is `show`, `export`, or anything else that lists the record for a person. Nothing in this subsection touches validity or the hash; it is here so that two implementations print the same day.

- A day is listed in the order of the instant `at` denotes, then by `seq`. A line whose `at` does not parse is on no day; a reader skips it.
- A reader listing a day MAY read only the month files that day can touch (§2). Resolutions and retractions apply wherever the line they cover is, so it takes those from every file.
- A retraction line is not listed on its own day (RFC 0003 rule 3). It appears as a mark on the line it hides, on that line's day.
- An alias walk (RFC 0006 rule 6) that ends without reaching an entity line — on its fourth hop, on a cycle, or at a ref with no line standing — names nothing. The `label` an alias line carries is a hint written at resolution time, not a resolution.
- A run of consecutive location points from one source and of one subject (RFC 0001 `subject`; absent is the owner), unbroken by any other row, MAY be collapsed into one row. The row spans from the first point's `at` to the last point's `end` when that is not null, else to its `at`.
- A payload whose shape predates its profile (§6) is shown however the reader chooses; reading a string `chat` as the chat's name and a string attendee as an `email` ref is reasonable, not required.
- A read command MAY refuse a `logbook/0.1` record, so that every command answers a record it does not carry the same way; §3.1 requires refusal only of verify and write. A reader that does read one says nothing about its hashes.

## 4. Tiers

| Tier | Typical content | At rest |
|---|---|---|
| 1 | location, photo metadata, calendar, public activity | plain |
| 2 | notes, messages, decisions, confirmations, personal mail | encrypted with the owner's key (a later version) |
| 3 | money, health | encrypted with the owner's key (a later version) |

Derived data inherits the highest tier of its evidence. Conformance requires the field; a later version will define the encryption envelope for tiers 2–3 (`payload_enc` replacing `payload`, age/X25519 recipient = the owner's key).

Each payload profile (§5) names the tier its producers write by default. The table repeats what the RFCs say, and the RFC is authoritative where the two differ:

| Default tier | Profiles (RFC) |
|---|---|
| 1 | `location/v1` (0001), `photo/v1` (0002), `event/v1` (0009; a source MAY set 2 on entries with attendees), `crossing/v1` (0011, MUST), `call/v1` (0012), `flight/v1` (0013), `trip/v1` (0020; 3 when it carries a `price`), `keeper/v1` (0024), `migration/v1` (§3.1) |
| 2 | `retraction/v1` (0003), `transcript/v1` (0004), `resolution/v1` (0006; the highest tier of its evidence, 2 in practice), `commitment/v1` and `commitment-close/v1` (0007; the highest tier of their evidence, 2 when written by hand), `message/v1` (0008, MUST), `note/v1` (0010, MUST), `mail/v1` (0015), `task/v1` (0016, MUST), `browse/v1` (0017, MUST), `watch/v1` (0018, MUST), `listen/v1` (0019, MUST), `highlight/v1` (0022), `voice-memo/v1` (0023) |
| 3 | `health-sample/v1` (0014), `transaction/v1` (0021, MUST; an import option MUST NOT lower it) |

A default marked MUST is the profile's tier; the others are SHOULD: a producer MAY write a higher tier for a reason it states (the reference `transcript`, `granola` and `wispr-flow` adapters write `transcript/v1` at 3), and an import option (`logbook add --tier`) MAY set another tier for a whole run where the RFC allows it, never per line.

## 5. Payload profiles

The envelope is the standard. Payloads are versioned by `payload.schema` and proposed as RFCs in `rfcs/`; the profiles so far are those of the table in §4, listed with their RFCs in `rfcs/README.md`. A logbook with unknown schemas is still valid, and so is a line whose payload does not have the shape its profile describes: a profile constrains writers, and a reader MUST NOT fail on a payload it cannot interpret.

## 6. Conformance

An implementation is conformant when `verify` on `conformance/sample-logbook` reports valid and prints the head in `conformance/expected.json`; when appending one line to a copy of it yields a logbook that still verifies, with `seq` + 1; and when changing any hashed field of any line of the copy (a content field of §3, `seq`, `prev`, `recorded_at` or `hash`), or deleting any line of it, makes `verify` report invalid. `id` is outside the hash, and the stored form is not hashed (§2): a change to `id`, or a re-serialisation that leaves the canonical form unchanged, is not detected and is not required to be. `verify` checks the envelope requirements of §2 as well as the chain rules of §3. The sample tests the envelope and the chain, not the profiles: its payloads were written before the RFCs that now define `message/v1` and `event/v1`, and some do not have the shapes those RFCs give (a `chat` that is a string, an attendee that is a string). They are not profile examples; the RFCs are. Level 2 conformance (a later version) adds encryption. Two independent implementations must agree before v1.0 is frozen.

*Status:* two independent implementations, [openlogbook](https://github.com/bighydro/logbook) (Python, reference) and [logbook-ts](https://github.com/bighydro/logbook-ts) (TypeScript), reproduce the head in `conformance/expected.json`; they agree on `verify` and `append`.

## 7. What this spec does not say

Nothing about servers, databases, user interfaces, engines, agents, or how two logbooks exchange pages. Those are layers. The spec is finished when it is small enough to implement in an afternoon.
