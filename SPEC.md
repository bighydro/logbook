# Logbook format — specification v0.1

Status: draft. License: CC0. Anyone may implement this without asking.

The key words MUST, MUST NOT, SHOULD and MAY are to be interpreted as described in RFC 2119.

## 1. The folder

```
<root>/
  logbook.json            identity and chain head
  logbook/<YYYY>/<MM>.jsonl   the record
  notes/<YYYY>/<YYYY-MM-DD>.md   free text, optional
  inbox/                  optional; not part of conformance
  index.sqlite            optional; a derived locator, disposable (ADR 0007); not part of conformance
```

`logbook.json`:

```json
{"format": "logbook/0.1", "owner_id": "<uuid>", "created_at": "<RFC3339 UTC>",
 "timezone": "<IANA tz>", "seq": 4181, "head": "<hex sha256>"}
```

## 2. The line (the envelope)

One observation per line, JSON, UTF-8, newline-terminated, in `logbook/<YYYY>/<MM>.jsonl`, where YYYY and MM are taken from `at` in UTC.

| Field | Type | Meaning |
|---|---|---|
| `id` | uuid | UUIDv7 (RFC 9562) recommended; identity of this line; outside the hash so it may be assigned at write time |
| `seq` | integer ≥ 1 | position in the owner's chain; strictly increasing by 1 |
| `at` | RFC3339 UTC | when the thing happened (not when it was recorded) |
| `end` | RFC3339 UTC or null | when it stopped, if it had a duration |
| `tz` | IANA name | the owner's timezone at `at` |
| `source` | string | who reported it: `manual`, `apple-health`, `google-takeout`, … |
| `kind` | string | what it is: `location`, `photo`, `event`, `message`, `sleep`, `note`, … |
| `tier` | 1, 2 or 3 | privacy tier, §4 |
| `payload` | object | whatever the source said; MUST contain `schema`, e.g. `"location/v1"` |
| `recorded_at` | RFC3339 UTC | when the line was written |
| `prev` | hex sha256 | hash of the previous line; 64 zeros for the first |
| `hash` | hex sha256 | §3 |

Unknown fields MUST be preserved by readers and MUST NOT be added by writers at the top level; extensions go inside `payload`.

## 3. The chain

```
content = canonical_json({at, end, tz, source, kind, tier, payload})
hash    = sha256( prev + "|" + seq + "|" + sha256(content) + "|" + recorded_at )
```

`canonical_json` is RFC 8785 (JSON Canonicalization Scheme): keys sorted by UTF-16 code units, no whitespace, UTF-8, ES6 number serialisation, no NaN/Infinity. A logbook is **valid** when, taking every line from every file and ordering by `seq` (files partition by the month of `at`, so backfilled history lands in old files; file order is not chain order), every line's `seq` is the previous plus one, every `prev` equals the previous `hash`, every `hash` recomputes, and `logbook.json` `seq`/`head` match the last line.

Corrections are new lines. A source that revises an earlier record writes a new line with `payload.supersedes = "<id>"`. Nothing is ever rewritten or removed.

## 4. Tiers

| Tier | Typical content | At rest |
|---|---|---|
| 1 | location, photo metadata, calendar, public activity | plain |
| 2 | notes, messages, decisions, confirmations, personal mail | encrypted with the owner's key (v0.2) |
| 3 | money, health | encrypted with the owner's key (v0.2) |

Derived data inherits the highest tier of its evidence. v0.1 conformance requires the field; v0.2 will define the encryption envelope for tiers 2–3 (`payload_enc` replacing `payload`, age/X25519 recipient = the owner's key).

## 5. Payload profiles

The envelope is the standard. Payloads are versioned by `payload.schema` and proposed as RFCs in `rfcs/`. Seed profiles: `location/v1`, `photo/v1`, `event/v1`, `message/v1`, `transaction/v1`, `health-sample/v1`, `note/v1`. A logbook with unknown schemas is still valid.

## 6. Conformance

An implementation is conformant when `verify` on `conformance/sample-logbook` reports valid and prints the head in `conformance/expected.json`, and when appending one line to a copy of it yields a logbook that still verifies. Level 2 conformance (v0.2) adds encryption. Two independent implementations must agree before v1.0 is frozen.

## 7. What this spec does not say

Nothing about servers, databases, user interfaces, engines, agents, or how two logbooks exchange pages. Those are layers. The spec is finished when it is small enough to implement in an afternoon.
