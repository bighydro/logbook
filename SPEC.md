# Logbook format — specification v0.3

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
```

A derived locator (`index.sqlite`, ADR 0007) is disposable and not part of conformance; the reference keeps it in the user's cache directory, outside this folder, so a copy of the folder carries no locator (RFC 0029 §8). An implementation MAY keep one inside the folder.

`logbook.json`:

```json
{"format": "logbook/0.3", "owner_id": "<uuid>", "created_at": "<RFC3339 UTC>",
 "timezone": "<IANA tz>", "seq": 4181, "head": "<hex sha256>",
 "recipients": ["age1x5ut7lplvtgkzcnvtjux674z32mu5q72r6ffaxemxtg9g08p7g5qa8ytxl", "age1…"],
 "lineage": [{"from_format": "logbook/0.2", "from_head": "<hex sha256>", "migrated_at": "<RFC3339 UTC>"}]}
```

`recipients` lists the age X25519 recipients (the public halves) that tiers 2–3 are sealed to (§4). It is present in a record that seals, with two entries at least; a record without it, or with an empty list, seals nothing. The private identity is never in this folder (RFC 0029 §6).

`seq` and `head` are those of the last line in chain order (§3). A record with no lines has `seq` 0 and `head` GENESIS. **GENESIS** is the string of 64 ASCII `0` characters, `0000…0000`; it is a named constant, not the digest of anything, and it is also the `prev` of the first line (§3).

`lineage` is present only in a record that was migrated from an earlier format, or that sealed its past (§3.1).

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

**Sealed files.** In a record that seals (§4), a file a tier 2–3 line points at is stored under the same name, the digest of its plaintext, as an age file (RFC 0029 §7): its first 22 bytes are `age-encryption.org/v1\n`. The reference inside the line is unchanged and names the plaintext. A verifier without the key counts such a file as sealed and does not check it; one with the key opens it and requires the plaintext to hash to the name, else it is an error. A plain file may be replaced by its sealed form (the protection raised), never the reverse. A file both a tier-1 and a tier-2 line point at is sealed.

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
| `payload` | object | whatever the source said; MUST contain `schema`, e.g. `"location/v1"`; for a sealed line, the reference `{"schema": "sealed/v1", "of": "<the sealed payload's schema>", "digest": "<hex sha256>"}` |
| `recorded_at` | RFC3339 UTC | when the line was written |
| `prev` | hex sha256 | hash of the previous line; GENESIS (§1) for the first |
| `hash` | hex sha256 | §3 |
| `payload_enc` | string | **sealed lines only** (§4): the sealed content as an age file in standard base64; outside the hash, as `id` is |

Every field in the table but `payload_enc` is present in every line; `payload_enc` is present on a sealed line and on no other. `end` is `null` when the observation has no duration or its end is unknown; it is never omitted. Absent and null are different inputs to the hash: an object without `end` and one with `"end":null` canonicalise to different bytes. Writers MUST emit `null`.

`at`, `end` and `recorded_at` are RFC 3339 date-times in UTC with the literal `Z` designator, as in `2026-03-01T07:30:00Z`; a numeric offset such as `+00:00` MUST NOT be used. Fractional seconds are permitted. The string is hashed verbatim, so `07:30:00Z` and `07:30:00.000Z` are different inputs. They are the same instant: timestamps compare as the instants they denote, never as text (`07:30:00.5Z` is after `07:30:00Z`, though it sorts before it as a string).

`tz`, and `timezone` in `logbook.json`, are IANA zone names. This spec names no edition of the zone database, so a name may be known to one reader and not another (`Europe/Kyiv` and `Europe/Kiev` are the same zone under two editions). `verify` does not interpret `tz`, so no zone name makes a record invalid. A reader that must localise a time and does not know the zone MUST say so; it MUST NOT silently substitute another zone.

Unknown fields MUST be preserved by readers and MUST NOT be added by writers at the top level; extensions go inside `payload`.

**Sealed lines** (RFC 0029). A line whose `payload.schema` is `sealed/v1` is sealed: its `payload` is exactly `{"schema": "sealed/v1", "of": "<schema>", "digest": "<lowercase hex sha256>"}` and it carries `payload_enc`. The sealed bytes are `canonical_json({"payload": <the real payload>, "salt": "<32 lowercase hex, 16 random bytes>"})` in UTF-8; `digest` is their SHA-256; `of` is the real payload's `schema`; `payload_enc` is that text age-sealed (age-encryption.org/v1, X25519 recipients, the binary file, never the armor) to every recipient of `logbook.json`, as standard base64 with padding. A `sealed/v1` payload with other keys, or without a `payload_enc` that is base64 of bytes beginning with the age header, is invalid; so is a `payload_enc` on a line whose payload is not `sealed/v1`. The salt is inside the sealed bytes and inside the digest, so the digest confirms nothing to a reader without the key. Writers seal every tier 2 and 3 line of a record that names recipients, and never a tier-1 line.

## 3. The chain

```
content = canonical_json({at, end, tz, source, kind, tier, payload})
hash    = sha256( prev + "|" + seq + "|" + sha256(content) + "|" + recorded_at )
```

`canonical_json` is RFC 8785 (JSON Canonicalization Scheme): keys sorted by UTF-16 code units, no whitespace, UTF-8, ES6 number serialisation, no NaN/Infinity.

In the pre-image, `prev` and `sha256(content)` are lowercase hex, `seq` is decimal with no padding and no sign, `recorded_at` is the string exactly as written in the line, and `|` is U+007C. Every hex digest in this format, in a pre-image and as written in a file, is lowercase; a verifier compares digests as strings, so an uppercase digest does not verify.

A logbook is **valid** when, taking every line from every file and ordering by `seq` (files partition by the month of `at`, so backfilled history lands in old files; file order is not chain order):

- every line meets §2: `payload.schema` is present, `tier` is 1, 2 or 3, `seq` ≥ 1, and a sealed line meets the sealed-line rule of §2;
- no two lines share a `seq`; when they do, the verifier reports the second occurrence;
- every line's `seq` is the previous plus one, the first being 1;
- every `prev` equals the previous `hash`, the first being GENESIS;
- every `hash` recomputes;
- `logbook.json` `seq`/`head` match the last line, or are 0 and GENESIS when there is none.

A verifier checks the envelope requirements of §2 as well as the chain: a line that chains correctly but has no `payload.schema` or a `tier` outside 1..3 makes the record invalid.

**Sealed lines and the key.** `payload_enc` is outside the hash, so the rules above hold without any key: a verifier without the owner's identity checks the whole chain and the sealed-line rule of §2, reports how many lines it did not open, and exits 0 when the chain holds. It cannot tell a line's sealed bytes from bytes an adversary sealed to the owner's recipients; that is what the key adds. A verifier with the identity MUST open every sealed line, require the SHA-256 of the opened bytes to equal `payload.digest` and the opened payload's `schema` to equal `of`, and treat a mismatch as an error of the record, as a present attachment whose bytes do not match its name is (§1.1). Resealing `payload_enc` to other recipients changes no hash (RFC 0029 §6.4).

**Write order.** A writer appends in this order: the line, or the batch of lines, to its month file, flushed and fsynced; then `logbook.json`, written to a temporary file and renamed into place so it is never half-written; then any index. A crash therefore leaves the files ahead of `logbook.json`, never behind: every line `logbook.json` names is on disk, and any lines past its `seq` are a complete, chained tail. Until `logbook.json` is brought forward, `verify` reports such a record invalid by the last rule above.

**Truncation.** A crash can also cut a month file inside the line being written. Bytes that are not a line — a file that ends inside a line, or a line that is not one JSON object with distinct keys (§2) — make the record invalid, and a verifier MUST report each by file and line number. It MUST still report `seq` and `head`, and they are those of the lines it read: when the whole lines are a chained prefix, as a torn write leaves them, the `seq` and `hash` of the last whole line, so the owner learns which prefix of the chain is intact; 0 and GENESIS only when no whole line remains. A verifier MUST NOT report 0 and GENESIS for a record whose first line is whole. A last line that is whole but for its newline is a line, and a file cut there is valid: the chain covers lines, not bytes (§1.1).

Corrections are new lines. A source that revises an earlier record writes a new line with `payload.supersedes = "<id>"`. Nothing is ever rewritten or removed. A line that should be hidden rather than corrected is retracted: a new line of kind `retraction` whose payload supersedes it (RFC 0003, `retraction/v1`); readers mark it and never drop it.

### 3.1 Format versions

`logbook.json` `format` names the rule the record's hashes were computed with.

| Format | Canonicalisation | Envelope |
|---|---|---|
| `logbook/0.1` | Python's `json.dumps(sort_keys=True, separators=(",", ":"))`. It deviated from RFC 8785 in float layout (`0.0` and `120.0` instead of `0` and `120`; `1e-06` instead of `0.000001`; exponent form from 1e16, not 1e21) and in key order (Unicode code points, not UTF-16 code units). | §2 without `payload_enc` |
| `logbook/0.2` | RFC 8785 exactly, as §3 says. | §2 without `payload_enc`; nothing sealed |
| `logbook/0.3` | RFC 8785 exactly, the same rule. | §2 as written: sealed lines, `recipients` in `logbook.json` |

Canonicalisation is fixed, not versioned (ADR 0014): a conformant implementation carries one rule and MUST refuse to verify or write a `logbook/0.1` record. Such a record MUST be migrated forward. A migration keeps every line's `id`, `seq`, content fields and `recorded_at` unchanged, recomputes `prev` and `hash` in `seq` order under the current rule, sets `format` to the current format, appends `{from_format, from_head, migrated_at}` to `lineage` in `logbook.json`, and then appends one line — `source` `manual`, `kind` `migration`, `tier` 1, payload `{"schema": "migration/v1", "from_format": "logbook/0.1", "from_head": "<old head>"}` — so that the fact of the migration, and the head it replaced, are inside the chain. The old head stays reproducible from the old files with the old rule; nothing else about the record changes.

`logbook/0.2` and `logbook/0.3` hash by the same rule, so a 0.3 implementation MUST read, verify and write a 0.2 record as it is, never migrating it (ADR 0020); a 0.2 record seals nothing, having no recipients, and becomes 0.3 the moment it is given them. A 0.2 implementation that meets a 0.3 record preserves `payload_enc` as an unknown field and verifies the chain correctly, but cannot open anything; the format name tells it that it needs another version of the code.

`migration/v1`, the payload of that one line, is part of this section, not a payload profile of §5: it is frozen with the envelope and listed in no profile table (RFC 0031, question 1).

**Sealing the past** (RFC 0029 §10.2). A record given recipients may seal the tier 2–3 lines written before it had them. That changes those lines' content hashes (the real payload leaves the pre-image and the reference enters it), so it takes the migration road: every line keeps `id`, `seq`, `at`, `end`, `tz`, `source`, `kind`, `tier` and `recorded_at`; a plain tier 2–3 payload becomes the sealed reference with its content in `payload_enc`; `prev` and `hash` are recomputed in `seq` order; every attachment such a line names is sealed under its name; `format` becomes `logbook/0.3`; `lineage` gains an entry; and one `migration/v1` line is appended, with `from_head` the head it replaced and the counts `sealed_lines` and `sealed_attachments`. The plain files are not kept beside the record. The old head stays reproducible, with the identity: open every sealed line, put its payload back, recompute.

### 3.2 Readers

A reader is anything that reads the record for a person and writes nothing to it: `show` and `export`, which list lines, and the derived readers, which compute something from them and never append (ADR 0013, ADR 0019): `derive stays`, `trips`, `day`, `days`, `rollup`, `keepers`, `promises` and `sources --gaps`. Nothing in this subsection touches validity or the hash; it is here so that two implementations print the same day and derive the same stays from the same record. Each derived reader below names its inputs, its rules with their constants, the shape of its JSON output, and what is a reader's own. The text a reader prints is a reader's own throughout: its columns, its wording, its rounding. The JSON form is the contract, and §6.1 says which of them a second implementation is compared on.

Two words recur. A line is **standing** when it is not retracted (RFC 0003) and no later line of the same kind names it in `payload.supersedes`; a derived reader takes the standing lines of a kind, and `show` lists a superseded line with a mark, as it marks a retracted one. The **record's zone** is `timezone` in `logbook.json`: every reader localises every instant in it and assigns every line to a local day by it, never by the line's own `tz` (a `flight/v1` line whose `tz` is the origin's zone is on the local day the record's zone gives its `at`). A reader MAY offer another zone as an option; it is never the default.

#### 3.2.1 Listing a day (`show`)

- A day is listed in the order of the instant `at` denotes, then by `seq`. A line whose `at` does not parse is on no day; a reader skips it.
- A reader listing a day MAY read only the month files that day can touch (§2). Resolutions and retractions apply wherever the line they cover is, so it takes those from every file.
- A retraction line is not listed on its own day (RFC 0003 rule 3). It appears as a mark on the line it hides, on that line's day. Every other kind of line is listed on its day, a `resolution/v1` or a `keeper/v1` line as much as a photo: what a reader derives (a stay, a trip, a Day, a proposal) is never a line and is never listed.
- An alias walk (RFC 0006 rule 6) that ends without reaching an entity line — on its fourth hop, on a cycle, or at a ref with no line standing — names nothing. The `label` an alias line carries is a hint written at resolution time, not a resolution.
- A run of consecutive location points from one source and of one subject (RFC 0001 `subject`; absent is the owner), unbroken by any other row, MAY be collapsed into one row. The row spans from the first point's `at` to the last point's `end` when that is not null, else to its `at`.
- One calendar entry that several sources carry is one row. Two `event/v1` lines are one entry when they come from different sources, their `at` and `end` denote the same instants (both null is the same end), and either their titles name the same flight designator (RFC 0013; `Flight to Zürich (XY 561)` and `Flug XY561`) or their titles are equal with case, whitespace and accents aside (NFKD with the combining marks dropped: `Zürich` and `Zurich` fold, `Tromsø` and `Tromso` do not). A set folds only across sources: one calendar holding an entry twice is two rows, though its repeat folds into a set another calendar already makes. The row is the first line of the set, in the day's order, and stands for every source in it; a retracted line is never folded and folds nothing.
- A `flight/v1` line with no `number` (RFC 0013 rule 1) is listed as its route alone.
- A day's hero photos are its keeper lines standing, `memory` first (3.2.9, RFC 0024 rule 4); a day with none has no hero, and a reader does not pick one.
- A payload whose shape predates its profile (§6) is shown however the reader chooses; reading a string `chat` as the chat's name and a string attendee as an `email` ref is reasonable, not required.
- A sealed line a reader can open is listed as its opened payload; one it cannot open (no identity on this machine) is listed on its day, as its `kind` and `of`, and says it is sealed. A reader never drops it.
- A read command MAY refuse a `logbook/0.1` record, so that every command answers a record it does not carry the same way; §3.1 requires refusal only of verify and write. A reader that does read one says nothing about its hashes.
- What `show` prints for a line, a range of days, a filter by profile and a machine-readable form are a reader's own; the rules above fix which lines are on a day, their order, their marks and their folds, and nothing else. Two implementations that want to print the same text match each other on a fixture, as the reference and logbook-ts do (§6).

#### 3.2.2 What every derived reader shares

**Inputs.** The lines of a window, located however the reader likes (§2: a reader MAY rely on placement; the reference goes through its index); the record's settings in `policy/stays.json` (the table below; an absent file means the defaults, and a reader MUST NOT fail for want of it); its named places in `places.json` (`{"<name>": {"lat", "lon", "radius_m"?, "kind"?, "country"?, "tags"?}}`, `kind` one of `home`, `asset-berth`, `other`, absent is `other`, `radius_m` absent is `radius_m` of the settings); its assets in `assets.json` (`{"assets": [{"id", "kind", "name", …}]}`, `kind` one of `yacht`, `aircraft`, `car`; ADR 0018); the airports table of RFC 0013 rule 5, which also carries each row's municipality and OurAirports type; and, for a country, the zone database's `zone.tab`. A reader writes none of these. The one exception the reference makes is `derive stays`, which writes the defaults into `policy/stays.json` on its first run and never rewrites the file; a reader that does not is conformant.

| Setting | Default | Meaning |
|---|---|---|
| `stay_min_s` | 1200 | a cluster this long (20 min) is a stay by duration alone; and the overlap a night's stay must reach |
| `stop_min_s` | 180 | a cluster shorter than this is travel, not a stop |
| `merge_gap_s` | 600 | out of the radius and back within this: one stay; a silence this long is a gap |
| `radius_m` | 150 | the radius of an unnamed place, and of an aboard match |
| `airport_km` | 8 | a move's end this close to an airport is at it |
| `night` | `["22:00", "08:00"]` | the window the overnight stay is chosen in, local; an end at or before the start is the next morning |
| `modes.walk_max_kmh` | 7 | a move at or under this speed is a walk |
| `modes.car_max_kmh` | 130 | … at or under this a car; above it a train |
| `modes.flight_min_kmh` | 150 | above this a flight |
| `aboard_window_s` | 300 | an asset's position this close in time can match an owner's point |

**The window.** A reader's window is a range of local days `[first, last]` in the record's zone. Its lines are those whose `at` is at or after the first day's local midnight and before the end of the night window of the last day (08:00 the morning after it by default), so the last night is inside; the derivation of stays is also given, per subject, the first location line at or after that end, so a stay that runs past the window ends where the tracker next spoke (3.2.3 rule 4), and that line is not a line of the window. Retractions and resolutions come from the whole record. Where a window defaults, it defaults to the **days the owner's track covers**: the first to the last local day with a `location/v1` line; a window given by the user is clipped to them (`rollup`, `trips`), so a day the record knows nothing about is nothing, not a night in transit.

**Lines.** A derived reader reads standing lines only: a retracted line is out, and so is one a later line of the same kind supersedes. Names come from the resolution lines (RFC 0006) through the alias walk of 3.2.1. The **owner's identities** are `owner_id` in `logbook.json`, the addresses under its `owner_emails`, the `names`, `emails` and `phones` of `policy/owner.json` when it exists, and the closure of those over the resolution lines (a ref that resolves to an owner entity is the owner's; an owner ref's entity is the owner) with every label they resolve to.

**Output.** Instants in JSON are RFC 3339 UTC with `Z` to the second; a `*_local` field is the same instant in the record's zone as an ISO 8601 date-time with its offset. Every number carries, under `lines`, the ids of the lines it came from: for a stay the first and last location line of its run, for a flight the line standing, for a person the lines that put them there, for a night's sleep its stages. A derived id is reproducible from the record (ARCHITECTURE: derived is disposable, ids are stable): a stay or stop is `stay:<subject>:<YYYYMMDDTHHMMZ>@<lat>,<lon>` (`stop:` for a stop; `<subject>` the asset id or `owner`; the start in UTC to the minute; the centroid to four decimals), a move `move:<subject>:<YYYYMMDDTHHMMZ>`, a run aboard an asset `aboard:<asset>:<YYYYMMDDTHHMMZ>`, a trip `trip:<first day>:<last day>`, a proposed promise the digest of 3.2.10. Rounding in JSON is as each reader says; a field with nothing behind it is `null`, never a zero, because a zero is a measurement. Great-circle distances are the haversine on a sphere of radius 6371 km.

#### 3.2.3 Stays, moves and nights (`derive stays`)

**Inputs.** The `location/v1` lines standing of the window, by subject (RFC 0001: `subject` absent is the owner, else an asset id; a line whose `lat` or `lon` is not a finite number is skipped); the owner's evidence lines of the window, the kinds `event`, `transcript`, `note`, `call`, `message` and `photo`; the settings, places, assets and airports of 3.2.2. The window is one day (`--day`, default today) or a range.

**Rules.**

1. Each subject's points are put in time order, by instant then `seq`, and clustered in that order. A point joins the current cluster when it lies within the radius of the cluster's place (the cluster's first point lies in a named place: of the places whose radius holds it, the nearest) or, for a cluster at no named place, within `radius_m` of the cluster's first point (the anchor, never a running centroid, so a slow walk cannot drift a cluster along), however long after the cluster's last point it comes: a tracker is silent while its owner is still. A point outside whose very next point is back inside is GPS noise: it is dropped and counted (`noise_points`). Any other point outside ends the cluster and starts the next.
2. A cluster whose first and last point are less than `stop_min_s` apart is travel and is dropped. Two consecutive clusters at the same place (the same named place; or, both unnamed, centroids within `radius_m`) whose gap is under `merge_gap_s` are one cluster.
3. A cluster's centroid is the mean of its points; its place is its first point's named place, if any; it starts at its first point's `at`.
4. A cluster ends at its last point's `at`, unless the subject's next point comes `merge_gap_s` or more later and lies within `walk_max_kmh` for `merge_gap_s` of the last point (1,167 m by default): then the silence was stillness and the cluster ends at that next point's `at`. A next point farther than that is travel the tracker did not see, and the cluster ends at its last point.
5. A cluster is a **stay** when it lasts `stay_min_s` or longer, or when any of the owner's evidence lines falls inside it (an instant within its span; a line with `end` whose span overlaps it); evidence promotes, duration is the fallback, and a stay by evidence alone is marked `promoted`. Otherwise it is a **stop**. Only the owner's clusters are promoted; `attached` counts the evidence by kind.
6. A **move** lies between two consecutive clusters: it starts where the earlier one ends (rule 4) and ends at the later one's first point. Its distance is the great-circle length of the path from the earlier cluster's last point through every point between (noise left out) to the later one's first; its `points` are those between. Its `airports` are the two IATA codes when its two end points each lie within `airport_km` of an airport. Its mode: when the owner is aboard an asset (rule 7), the asset's kind decides, `yacht` → `boat`, `aircraft` → `flight`, `car` → `car`; an asset's own moves likewise take the mode of its kind; else `null` when the distance is under `radius_m` or the duration is not positive (nothing moved); else from the mean speed — above `flight_min_kmh`, or two airports with no point between, `flight`; at or under `walk_max_kmh` `walk`; at or under `car_max_kmh` `car`; else `train`.
7. The owner is **aboard** an asset during a stay or stop when any of the asset's points inside that span lies within `radius_m` of the centroid; during a move when at least half of the owner's points inside it have an asset point within `aboard_window_s` of them in time and within `radius_m` in distance; and during a move with no points between two stays aboard the same asset. Assets are tried in order of id and the first match is taken. Aboard is the owner's relation to the asset (ADR 0018 rule 3): an asset's own segments never carry it.
8. The **night** of a day is the owner's stay with the longest overlap of that day's night window (3.2.2), when that overlap reaches `stay_min_s`; else the day is **in transit**. The night is **at home** when the stay's place is of kind `home`, or its centroid lies within a home place's radius, or within 400 m of a home place's centre whatever that place's radius: a guest room across the street is not a night away, and a trip never starts or ends with such a night.

**Output.** One object: `window` (`since`, `until`, `days`), `settings` (as the table), `subjects` (`null` for the owner, then the asset ids, sorted), `segments`, `nights`, `noise_points`. A segment carries `id`, `kind` (`stay`, `stop`, `move`), `subject`, `start`, `end`, `start_local`, `end_local`, `duration_s`, `points`, `aboard` and `lines` (`first`, `last`, `points`); a stay or stop also `lat` and `lon` to six decimals, `place`, `attached` (`{<kind>: <count>}`) and `promoted`; a move also `distance_m` (whole metres), `mode` and `airports`. A night carries `day`, `stay` (a segment, or `null`), `in_transit` and `home`. The owner's segments come first, then each asset's, each in time order.

**A reader's own.** The locator; whether the settings file is written; the text.

#### 3.2.4 Flights: the standing set and the inference

**The standing set** is what every reader of flights takes (RFC 0013 rule 4): the `flight/v1` lines not retracted and not named by another flight line's `supersedes`, the last line per key `(date, carrier, number)` (or `(date, "", "<from>><to>")` for a leg with no number), and of two standing lines that are one flight under two numbers (rule 1: the same `date`, the same route, departures within 30 minutes, scheduled against scheduled when both have one, else actual against actual, else whatever each has) only one: the numbered one when the other has none, else the one marked `extra.operating` true when exactly one is, else the first written. One line per flight, its `evidence` the strongest folded in. A reader shows a flight with no number as its route alone.

**The inference** (`infer flights`) is a producer, not a reader: it appends `flight/v1` lines with `source` `flight-inference` and `evidence` `inferred` through the merge of RFC 0013 rule 3, and a re-run appends nothing. Its rules, with the constants RFC 0013 names in prose:

1. A candidate is an `event/v1` line standing (not retracted, not superseded), not `cancelled`, whose title names a flight designator: a carrier code the airlines table knows followed by one to four digits, or any such code when the title also says `flight`, `Flug` or `✈`.
2. Its window of location points runs from 4 hours before the entry's `at` to 8 hours after its `end` (an entry with no `end` is given 6 hours; an all-day entry 4 hours either side). The points are the standing `location/v1` lines of that window in time order. A point is **at an airport** when the nearest airport in the table is within 8 km.
3. A **leg** is the latest point at one airport followed by the first point at a different airport, every point between them at no airport. It counts when it is at least 20 minutes long, the two airports are at least 150 km apart (closer, it was a drive), and, for a timed entry, it overlaps the entry (the arrival point at or after the entry's `at`, the departure point no later than 4 hours after its `end`). Of several legs, the one whose route is the two airport codes the title names wins, else the longest.
4. The leg's two points are `actual_departure` and `actual_arrival`; a timed entry's `at` and `end` are `scheduled_departure` and `scheduled_arrival`; `date` is the local date of the scheduled departure at the origin (of the actual one for an all-day entry); `from` and `to` are the leg's airports.
5. Nothing is written when a `tracked` flight standing on the same route, under another key, covers the leg (the leg lies between 4 hours before that flight's `at` and 8 hours after its `end`): the leg is that flight seen again.
6. The leg carries the entry's designator unless a `tracked` or `declared` flight standing already holds that designator on another route with its `at` inside the window: then the entry named that flight, this leg is another, and it is written with neither `carrier` nor `number`, keyed by date and route.
7. The line's `raw_id` is `<key>@<actual_departure>/<actual_arrival>`; `extra.event` is the entry's id and `extra.gap` the two points' ids.

**Output.** Lines, not a report; the counts a run prints are a producer's own.

#### 3.2.5 Company: who was there ("with")

Who was with the owner at a stay, split into **confirmed**, what the calendar, a recording or the owner's own words say, and **proposed**, a library's guess or an entry that names no hour. The owner is never their own company: evidence carrying one of the owner's identities (3.2.2) is dropped. A move has attachments but no company.

**Inputs.** One stay and the lines of the local days it touches; the resolution lines; the owner's identities; the places.

**Rules.**

1. **Calendar.** An attendee of a timed `event/v1` **held at the stay** is confirmed. An entry is held at the stay when it overlaps the stay and either is located within 1,000 m of the stay's centroid (coordinates under `extra.location.latitude`/`longitude`, or a `location` that is the name of a place in `places.json`, case aside) or has no location at all and overlaps the stay by more than 3,600 s. A located entry the record cannot place places nobody. An all-day entry places nobody unless it is located at the stay, and then its attendees are proposed, since it names no hour. An attendee who `declined` is not listed; one whose `ref` resolves to a person takes that person's label, else their display `name`; a bare address with no name, and a calendar system address (`@calendar.google.com`, `noreply`, `reservations@`, `invite@`), is dropped.
2. **Transcript.** A participant of a `transcript/v1` whose span overlaps the stay (or whose `at` lies in it) is confirmed when the record resolves them to a person: by their `email`, `phone` or `provider_id` ref, else by their `name` matching exactly one person's label (case aside), else exactly one person's label by its first word. A diarizer's `Speaker A`, `me`, `them`, `Unknown` or a name no resolution knows is not company.
3. **Note.** A `note/v1` whose `at` lies inside the stay and whose text says `with <Name>`, the names capitalised and joined by `and`, `og` or `&`, confirms each name the record resolves to a person by rule 2's name match; `with US`, an acronym, a country or a name the record does not know names nobody.
4. **Photo.** A `photo/v1` whose `at` lies inside the stay proposes each id under `people`, as the ref `provider_id` `<library>:<id>`, resolved to a person's label when a resolution line names it, else shown as the ref.
5. **Circle.** Reserved for a page another member of the circle shared (ARCHITECTURE); names nobody until that bundle is defined.

Evidence is merged per person (by entity id, else by name, case aside): the status is confirmed when any evidence confirms, the sources are listed in the order calendar, transcript, note, photo, and confirmed people come before proposed.

**Output.** Wherever a reader lists company: `confirmed` and `proposed`, each a list of `{person, name, status, confidence, sources, reasons, lines}`.

**A reader's own.** `confidence` (the reference writes 0.8 for an attendee who accepted, 0.6 for one who has not answered, 0.9 for a transcript, 1.0 for a note, 0.5 for a face, 0.3 for an all-day entry) and the wording of `reasons`; both are dropped before two implementations are compared (§6.1).

#### 3.2.6 Trips (`trips`)

**Inputs.** The nights of the window (3.2.3 rule 8), the places, the owner's stays, the standing flights (3.2.4) and the company of 3.2.5. The window is `--year`, or `--since`/`--until`, clipped to the days the owner's track covers; without either, those days.

**Rules.**

1. Without a place of kind `home` nothing is away from home: there are no trips, and the reader says so (`warning`).
2. A **trip** is a maximal run of consecutive days of the window whose night is not at home: away or in transit. A run whose every night is in transit is no trip, since nothing places the owner anywhere.
3. `start` is the run's first day, `end` its last, `until` the day after `end` (the return day); `nights` is the number of days in the run and `in_transit` how many of them had no stay.
4. The **route** is one label per night stay in order, two consecutive stays folded into the first when they are at the same named place or, both unnamed, within 200 m of each other, and consecutive equal labels folded. A stay's label is its named place; else, when it is **at an airport** — within 3.5 km of the reference point of an airport with scheduled traffic (OurAirports type `large_airport` or `medium_airport`, whose terminal is often well off the runway midpoint the row marks), within 2 km of any other row — the airport's IATA code and city, `ZRH, Zurich` (the code alone when the row names no municipality); else its coordinates to four decimals, `59.8500,10.6000`, followed by ` near <place>, <x.x> km` for the nearest named place when one is within 5 km, else by ` (<city>)` for the nearest airport within 30 km when its row names a municipality. The city is the municipality's text before any parenthesis or comma. The same label names an unnamed cluster in `rollup places`; `day` and `days` print the coordinates alone where this rule would add `near <place>`.
5. `places` are the named places, home places left out, of the owner's stays overlapping the span from `start`'s local midnight to the end of `until`, each once, in order of first visit; `people` the confirmed company of those stays merged per person, ordered by the number of evidence lines, most first, then name, at most 12; `flights` the standing flights whose `date` lies in `[start, until]`, `flights_in` those dated `start` and `flights_out` those dated `until`.
6. `asset` is set when every night of the trip that has a stay was aboard the same asset.
7. The id is `trip:<start>:<end>`. The captain's name for a trip is a `note/v1` line dated inside it, never a field here (ADR 0019).

**Output.** One object: `window`, `trips` (each `id`, `start`, `end`, `until`, `nights`, `in_transit`, `asset`, `route`, `places`, `people` as `{id, name, confidence, lines}`, `flights_in`, `flights_out`, `flights` as `{date, carrier, number, from, to, evidence, lines}`, `lines`) and `warning` when there is one.

#### 3.2.7 The Day (`day`) and a window of days (`days`)

**Inputs.** For a Day: a window of the day and the day before (the night before is that day's night); the day's lines; the `health-sample/v1` lines of both days; the standing flights. `days` reads a range the same way, a chunk at a time, and asks each day of it; its range defaults to the days the owner's track covers, else to the days with any line.

**Rules.**

1. The **timeline** is the owner's stays, stops and moves that overlap the local day, each keeping its real span and carrying `within_day`, the part of it on the day (a stay that began the evening before starts at 00:00 there); plus the standing flights whose `date` is the day (the local day of `at` when a line has no `date`), as rows of their own. Rows are ordered by their start on the day, a flight after a row that starts at the same instant.
2. A run of two or more consecutive segments aboard one asset is one row of kind `aboard`, with the run under `inside`: the asset's movement never fragments the stay.
3. A move with no points, lasting `merge_gap_s` or more, whose mode is not `flight` and that is not aboard an asset is a **gap**: the tracker did not see it. A gap attaches nothing and has no company.
4. To every other row **attach** the day's lines inside its span (an instant within it; a line with an `end` whose span overlaps it): events named, with their fold (3.2.1) and never an all-day one; transcripts and notes named (a note by the first line of its text, at most 72 characters, a longer one cut to 71 and an ellipsis); mail as threads, by `thread`, else `message_id`, else the line's id, with a message count; calls, with the counterparty's name, else their ref's value, else `withheld`; keepers named; messages and photos counted. Company is the stay's by 3.2.5; a move has attachments and no company; a move also lists the flights whose span overlaps it.
5. **Unplaced** are the day's events (not all-day), transcripts, notes, mail and calls inside no row that is not a gap: what the calendar planned where the track has nothing.
6. The **nights** before and after are the nights of the day before and of the day (3.2.3 rule 8). The **country** is that of the night after's stay, else of the longest stay on the day, else unknown: a place in `places.json` whose radius holds the stay's centroid and carries a `country` decides; else the nearest airport within 300 km and the country its zone is filed under in `zone.tab`; else unknown. It is coarse near borders and far from airports, and says which method it used.
7. **All-day** entries are the day's all-day `event/v1` lines, folded.
8. **Health** is the day's row from the `health-sample/v1` lines standing (RFC 0014 rules 4 and 5; of several lines that supersede the same line the latest stands): `sleep_h`, the asleep stages (`asleep`, `core`, `deep`, `rem`; never `in_bed` or `awake`) of the night that ends on the day, per device the union of their spans, the longest device taken, in hours to one decimal; `steps`, the larger device's count per quarter hour, summed; `resting_hr`, the mean of the day's resting readings in whole bpm, a reading in `count/s` multiplied by 60; `hrv`, the mean of the day's readings in whole ms. A field no line gives is `null`; a day with no health line has no row.
9. **Sources** are every source with a line on the day, with its count and its first and newest instant, most lines first then by name, the folded calendar entries counted.

**Output of `day`.** One object: `day`, `weekday`, `tz`; `nights` (`before`, `after`: `day`, `where`, `home`, `aboard`, `in_transit`, `stay`, `lines`); `country` (`code`, `method` of `place`, `airport` or `null`, `by`, `from` of `night` or `longest stay`); `all_day` (`title`, `line`, `sources`, `lines`); `timeline`, one entry per row: a segment as 3.2.3 gives it plus `within_day` (`start`, `end`, `duration_s`), `where` (a stay's named place, else the airport label of 3.2.6 rule 4, else its coordinates, with ` (<city>)` when no named place is within 5 km; `aboard <asset name>` for an `aboard` row; `null` for a move), `gap`, `attached` (`events`, `transcripts`, `notes`, `mail`, `calls`, `keepers`, and `messages` and `photos` as `{count, lines}`), `with` (3.2.5) and, for a move, `flights`; an `aboard` entry also `asset` (`id`, `name`, `kind`) and `inside`; a flight entry `id`, `kind` `flight`, `start`, `end`, `start_local`, `end_local`, `carrier`, `number`, `from`, `to`, `evidence`, `role`, `aircraft`, `line`; then `flights`, `unplaced` (`kind`, `at`, `end`, `title`, `line`, and for an event `sources` and `lines`), `health` (the row with `lines` and `by`) and `sources`.

**`days`.** One object per day, oldest first, JSON Lines under `--json`, every number the Day's: `day`, `weekday`, `night` (the night after: `where`, `home`, `aboard`, `in_transit`, `stay`), `country` (the code), `moved_m` (the whole metres of every move that started on the day, the passages inside an `aboard` row counted the same way, so a move across midnight counts once), `flights` (`carrier`, `number`, `from`, `to`, `evidence`, `line`), `stays` (`count`, the rows of kind `stay` or `aboard`, never a stop; `attached`, the attachments of every row but a flight; `with_attachments`, the stay rows with any), `people` (`confirmed`, the people confirmed at any row, each once; `names`), `health`, `sources` and `gaps`: every **usual** source with no line on the day, a source being usual when it has a line on at least four in five of the window's days that have any line (retractions aside).

#### 3.2.8 Rollups (`rollup`)

The record summed up per calendar year over a window, from one reading of it; `health` per calendar month or ISO week from the health lines alone. The window is `--year`, or `--since`/`--until`, clipped to the days the record covers: with a location line for `countries`, `nights`, `places` and `people`; with any line for `flights`; with a health line for `health`. Without either, those days. A window the record has no day in is empty.

- **`countries`.** Per year, for each night of the window: in transit when it has no stay; else the country of its stay by 3.2.7 rule 6, counted under its code, or under `unknown`. Each bucket carries `days`, `dates`, `lines` and, per country, `by` (`{place: n, airport: n}`); countries are ordered by days, most first, then code.
- **`flights`.** Per year from the standing flights (3.2.4) dated in it: `count`; `km`, the great-circle distance between the two airports' table coordinates, summed and rounded, a flight whose airport the table does not know counted under `unmeasured` with `km` `null`; `long_haul`, flights over 3,500 km; `by_evidence`; and `flights` (`date`, `carrier`, `number`, `from`, `to`, `km`, `evidence`, `role`, `lines`), by date then `seq`.
- **`nights`.** Per year: `home`, `away` and `in_transit` nights, `aboard` (nights per asset), and `longest_trip`, the longest run of consecutive non-home nights of the year (`start`, `end`, `nights`, `lines`); a `warning` when no place of kind `home` exists, since every night then counts as away.
- **`places`.** Per year, for every named place and every asset (an asset's stays are the owner's stays aboard it): `stays`, `hours` to one decimal, `nights` (the days whose night is there), `first` and `last` (the first stay's start day, the last stay's end day), `people` (the confirmed company of its stays, each with their `stays`, `days` — the distinct local days of the evidence that put them there — and `nights` — the nights there on a day their evidence is dated — and `lines`) and `lines`; then `unnamed`, the owner's stays at no named place grouped within 300 m of each group's first stay, ranked by hours, the top five of the year, each under the id of its first stay with `lat`, `lon` (the hours-weighted centre), `label` (3.2.6 rule 4, with ` aboard <asset>` when most of its hours were aboard one), `aboard`, `nearest` (`name`, `kind`, `metres`) and `city`. `--with` adds, per year, the place × person table under `with`: one row per person per place (`place`, `label`, `kind` of `place`, `asset` or `unnamed`, `id`, `name`, `stays`, `days`, `nights`, `lines`).
- **`people`.** Per year, from the confirmed company only: per person `days` together (the distinct local days of the confirmed evidence), `nights` together (the nights whose stay they were confirmed at on that day), `stays` shared, `last_contact`, `places` (a named place, `aboard <asset>`, else the unnamed label), `confirmed` (the evidence count) and `lines`; ordered by days, most first, then last contact, then name. A confirmed name the record resolves to no person is listed apart under `unresolved`.
- **`health`.** Per period (`YYYY-MM`, or the ISO week `YYYY-Www` in its ISO year) from the day rows of 3.2.7 rule 8: `sleep` (`mean_h` to one decimal, `nights`), `steps` (`mean`, `days`), `resting_hr` (`mean`, `min`, `max`, `days`), `hrv` (`mean_ms`, `days`), each with `lines` and each `null` when no day of the period has a line for it. Every period the window touches is listed, with `first` and `last`, its days inside the window.

Every rollup is one object with `kind`, `window` and `years` (`health`: `by` and `periods`); `countries` also carries `method`, a sentence that is a reader's own.

#### 3.2.9 Keepers (`keepers`)

**Inputs.** The `keeper/v1` lines standing (RFC 0024) whose local day is in the range, and the retractions. **Rules.** One entry per keeper, ordered by day, then `at`, then lane; `--lane` keeps one lane. A day's **hero** photos are its keepers standing, those of lane `memory` first, then the others, each group by `at`; a photo is named by its `file_name`, else its `asset_id`, else the photo line's id. **Output.** `{"keepers": [{line, day, at, lane, source, photo}]}`, `photo` as the line carries it. **A reader's own.** The hero line's text.

#### 3.2.10 Promises (`promises`)

The commitments the record's own words suggest, proposed and never asserted: only the owner closes one, and nothing the reader reads can close another. **Inputs.** The `transcript/v1` lines standing whose text is in the attachment store (read by its media type: WebVTT, SRT, JSON segments, `Speaker: text` prose, plain text; a transcript whose text is not there is counted under `skipped` and passed over) and the `note/v1` lines standing, from `--since` on; the `task/v1` lines; the resolution lines; the owner's identities.

**Rules.**

1. The **extractor** is a reader's own: anything that reads a text and returns the sentences in it that read as a promise, each with the words that made it one (`cue`), a `class` of `future`, `obligation` or `offer`, a `language` and the date phrase in it. The reference's extractor is a set of rules, first-person future, obligation and offer cues in English and German, not negated right after the cue and not a question; a local model is another. A report names its extractor (`name`, `version`).
2. One proposal per sentence. Its **id** is the first sixteen hex characters of the SHA-256 of the origin line's `id`, a newline, and the sentence with whitespace collapsed and case folded: the same sentence in the same line has the same id however often the reader runs and whichever extractor quoted it.
3. The proposal's `day` and `at` are the line's. Its **speaker** is the turn's label resolved: a participant of the line of that name through their `email`, `phone` or `provider_id` ref, else the one person the record labels by that name (3.2.5 rule 2); `me`, `I` and the owner's own names are the owner; a note is the owner's, except for text that carries its own labels (a line beginning `Speaker 2:` or `<a known name>:` is that speaker's); a diarizer's label or a name nobody resolves stays as spoken with no person. `direction` is `owed_by_owner` when the owner said it, `owed_to_owner` when a resolved person did, else `null`.
4. The **due hint** is the date phrase resolved against the day it was said, carried with a question mark because it is a reading of the words: a weekday is the next one strictly after that day; `next week` its Monday; `this week` and `end of the week` the Friday on or after; `next month` the first of it; `tomorrow` and `tonight` as they say; `in N days/weeks/months` counted on; a month and a day the next such date; `the Nth` the next such day of a month. Words that name no day leave it `null`.
5. A proposal is **closed** when the latest standing `task/v1` line whose `extra.promise` is its id has `status` `done` or `cancelled`. `promises done <id>` appends that line and nothing else (`source` `manual`, tier 2, `title` the sentence, `status` `done`, `due` the hint, `completed_at`, `list` `promises`, `raw_id` `promise:<id>@<time>`, and under `extra` the `promise`, its `origin` line, the `speaker` and the `extractor`). A reader never closes a proposal on its own.
6. A **judge**, a second reading of the candidates by a local model, is a reader's own: it never opens a socket, never changes a proposal, its id or what `done` writes, and keeps its verdicts outside the chain.

**Output.** One object: `since`, `open_only`, `judged_only`, `threshold`, `extractor`, `judge`, `unjudged`, `skipped` and `proposals`, each `id`, `status` (`open`, `done`), `closed_by`, `day`, `at`, `line`, `seq`, `kind`, `source`, `title`, `speaker` (`label`, `spoken`, `person`, `owner`), `direction`, `certainty` (always `inferred`), `language`, `cue`, `class`, `quote`, `due` (`phrase`, `date`) and `judgement`; the proposals in order of day, `at`, `seq`.

#### 3.2.11 Where a source went quiet (`sources --gaps`)

**Inputs.** Every line of every source, retracted or not (a retracted line still shows the source was alive), by local day, and the clock. **Rules.** The range is `--since` to today in the record's zone, or, per source, from the day of its first line; a line dated after today is outside it. A source's silences are the stretches between its consecutive lines, the stretch from the range's start to its first line when `--since` names one, and the open stretch from its last line to now; the longest is reported with its ends, `to` `null` when it is still running. Its `missing_days` are the days of the range with no line from it, today among them only once the source has been silent a full day (86,400 s). With `--expect`, only the named sources are reported, one with no line among them, and a source is `flagged` when its longest silence is 86,400 s or more or it has no line at all; the command exits non-zero when any is. **Output.** `since`, `today`, `timezone`, `expect`, `flagged` and `sources`, each `source`, `lines`, `first`, `last`, `silence` (`from`, `to`, `seconds`), `missing_days`, `flagged`. Its output depends on the clock, so it is not among the readers two implementations are compared on.

## 4. Tiers

| Tier | Typical content | At rest |
|---|---|---|
| 1 | location, photo metadata, calendar, public activity | plain |
| 2 | notes, messages, decisions, confirmations, personal mail | sealed with age to the owner's recipients (§2, RFC 0029) |
| 3 | money, health | sealed with age to the owner's recipients (§2, RFC 0029) |

Derived data inherits the highest tier of its evidence. Conformance requires the field. In a record whose `logbook.json` names `recipients` (§1), every tier 2 and 3 line is sealed as §2 says and every file such a line points at is sealed as §1.1 says; a record that names none is written plain, as before, and a verifier reports how many tier 2–3 lines are plain so the owner sees them. The envelope stays plain: `at`, `end`, `tz`, `source`, `kind`, `tier` and `recorded_at` are readable without any key, so a reader lists a day, an index locates a line and `verify` checks the chain without one. What the envelope gives away, and what the key handling is, is RFC 0029.

Each payload profile (§5) names the tier its producers write by default. The table repeats what the RFCs say, and the RFC is authoritative where the two differ:

| Default tier | Profiles (RFC) |
|---|---|
| 1 | `location/v1` (0001), `photo/v1` (0002), `event/v1` (0009; a source MAY set 2 on entries with attendees), `crossing/v1` (0011, MUST), `call/v1` (0012), `flight/v1` (0013), `trip/v1` (0020; 3 when it carries a `price`), `keeper/v1` (0024), `weather/v1` (0026), `migration/v1` (§3.1) |
| 2 | `retraction/v1` (0003), `transcript/v1` (0004), `resolution/v1` (0006; the highest tier of its evidence, 2 in practice), `message/v1` (0008, MUST), `note/v1` (0010, MUST), `mail/v1` (0015), `task/v1` (0016, MUST), `browse/v1` (0017, MUST), `watch/v1` (0018, MUST), `listen/v1` (0019, MUST), `highlight/v1` (0022), `voice-memo/v1` (0023) |
| 3 | `health-sample/v1` (0014), `transaction/v1` (0021, MUST; an import option MUST NOT lower it) |

A default marked MUST is the profile's tier; the others are SHOULD: a producer MAY write a higher tier for a reason it states (the reference `transcript`, `granola` and `wispr-flow` adapters write `transcript/v1` at 3), and an import option (`logbook add --tier`) MAY set another tier for a whole run where the RFC allows it, never per line.

## 5. Payload profiles

The envelope is the standard. Payloads are versioned by `payload.schema` and proposed as RFCs in `rfcs/`; the profiles so far are those of the table in §4, listed with their RFCs in `rfcs/README.md`. A logbook with unknown schemas is still valid, and so is a line whose payload does not have the shape its profile describes: a profile constrains writers, and a reader MUST NOT fail on a payload it cannot interpret.

Every profile is one of three words, said in its RFC's status line and decided by RFC 0031. **Frozen**: the schema is additive-only (a field may be added as MAY; none is removed, renamed or retyped; a change that needs any of these is `name/v2` with its own RFC), the JSON of every reader that reads it keeps every key it has with the same meaning and type under the fields §6.1 compares, and one conformance fixture holds it (§6.1). **Parked**: adapters keep writing it, its RFC says *may change before v1.0*, an amendment with a date may rename, retype or drop a field, a line written before the amendment is read by what it says, it has no fixture and no row in §6.1, and it is not in the v1.0 promise; it becomes frozen by the process RFC 0031 gives. **Deleted**: withdrawn by an RFC, written and read by nothing, its RFC kept as the record of it; `commitment/v1` and `commitment-close/v1` are the two (RFC 0007, withdrawn by RFC 0031).

## 6. Conformance

An implementation is conformant when `verify` on `conformance/sample-logbook` reports valid and prints the head in `conformance/expected.json`; when appending one line to a copy of it yields a logbook that still verifies, with `seq` + 1; and when changing any hashed field of any line of the copy (a content field of §3, `seq`, `prev`, `recorded_at` or `hash`), or deleting any line of it, makes `verify` report invalid; and when cutting the copy's month file inside any line makes `verify` report invalid with the `seq` and `head` of the last whole line (§3, truncation). `id` is outside the hash, and the stored form is not hashed (§2): a change to `id`, or a re-serialisation that leaves the canonical form unchanged, is not detected and is not required to be. `verify` checks the envelope requirements of §2 as well as the chain rules of §3. The sample tests the envelope and the chain, not the profiles: its payloads were written before the RFCs that now define `message/v1` and `event/v1`, and some do not have the shapes those RFCs give (a `chat` that is a string, an attendee that is a string). They are not profile examples; the RFCs are. The sample is a `logbook/0.2` record, which a conformant implementation reads as it is (§3.1). Two independent implementations must agree before v1.0 is frozen.

**Level 2 (sealing).** `conformance/sample-logbook-sealed` is the same week sealed to two recipients, one of them the identity published in `conformance/identity.txt` (it opens the fixture and nothing else). An implementation is Level 2 conformant when, in addition: `verify` on it without the identity reports valid, prints the head in `conformance/expected-sealed.json` and counts its sealed lines; `verify` with the identity reports valid, the same head, and every sealed line opened and matching its digest; changing any byte of a `payload_enc` leaves the keyless `verify` valid and makes the keyed one report invalid; and appending one tier-2 line to a copy seals it, and the other implementation opens it. The fixture's salts are data, so its head is reproducible by anyone who regenerates it; its ciphertext is not, and is not hashed.

*Status:* two independent implementations, [openlogbook](https://github.com/bighydro/logbook) (Python, reference) and [logbook-ts](https://github.com/bighydro/logbook-ts) (TypeScript), reproduce the head in `conformance/expected.json`; they agree on `verify` and `append`, on `verify` of a copy torn inside a line, and on `show` over the fixture records of logbook-ts's cross-implementation test (§6.1). The per-profile fixtures of §6.1 are compared from the day each lands in `conformance/profiles/`.

### 6.1 The readers

Format conformance is §6 above and needs none of the readers: an implementation that verifies and appends is conformant. Two implementations that both carry a reader of §3.2 are compared on the **demo record**, a synthetic month the reference invents from a seed (`logbook demo --days 30 --seed 1 --out <dir>`: thirty days from 2026-06-01, 12,772 lines, a person who does not exist), which the cross-impl job generates with the reference and hands to the other implementation as a folder. The job runs each reader below in both and compares the JSON after dropping the fields §3.2 marks as a reader's own: `confidence` and `reasons` under `with` and under a trip's `people`, the `method` sentence of `rollup countries`, and `warning`.

| Reader | Compared on |
|---|---|
| `derive stays --since 2026-06-01 --until 2026-06-30 --json` | `segments`, `nights` and `noise_points`, every subject |
| `trips --json` | `trips` |
| `day <day> --json`, for every day of the month | the whole object |
| `days --json` | every line |
| `rollup countries\|flights\|nights\|places\|people\|health --json` | `years`, or `periods` |
| `keepers --json` | `keepers` |

**A frozen profile's fixture is part of conformance.** For every frozen profile (§5, RFC 0031) `conformance/profiles/<profile>/` holds one synthetic line as its RFC's example gives it, its canonical form and hash, the `show` row the reference prints for it, and, for a profile a reader of the table above reads, that reader's JSON over a record that holds the line. An implementation passes the parts its readers cover: every implementation the line, its canonical form, its hash and (with `show`) its row; one that carries a reader of the table, that reader's JSON after dropping the fields §3.2 marks as a reader's own. The fixture is the freeze: a change that fails it is a new profile version, not an amendment.

Not compared: `show`, whose text is a reader's own (the reference and logbook-ts diff it on fixture records of logbook-ts's own); `promises`, whose extractor is a reader's own (and the demo record proposes nothing); `sources --gaps`, whose output depends on the clock; and `infer flights`, a producer, whose lines are compared through the standing set that `day`, `trips` and `rollup flights` read.

*Status:* no second implementation of a derived reader exists yet; logbook-ts carries `verify`, `add` and `show`. The cross-impl job compares `verify` and `append` on the conformance sample, and logbook-ts's own cross-implementation test diffs its `show`, `day`, `days`, `stats`, `trips` and `rollup countries|nights` against the reference's on its fixture records, the conformance sample and the seed-1 demo among them. Of the per-profile fixtures, the parts compared today are the line, its canonical form, its hash and its `show` row; the reader JSON binds the reference alone until a second derived reader exists (RFC 0031, question 4). The table is what the next reader is held to.

## 7. What this spec does not say

Nothing about servers, databases, user interfaces, engines, agents, or how two logbooks exchange pages. Those are layers. The spec is finished when it is small enough to implement in an afternoon. §3.2 is not the format: it is the readings the reference ships, written down so that a second implementation can agree with them, and §6.1 says which are compared; the format alone is conformance (§6).
