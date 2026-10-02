# RFC 0025 — bundle format `shared-page/v1`

Status: draft · 2026-10-02 · comment period: two weeks

## Summary

The page one logbook hands another (ADR 0009: the circle is core): one local day of the owner's
record, chosen for one named person, as a single file they can verify without trusting the
transport. It carries the day's lines verbatim, so the receiver recomputes every hash; the
attachments those lines point at, under their own digests; the `day-package/v1` summary of the
same lines; and a manifest the owner signed with an Ed25519 key that belongs to the record. The
receiver verifies the signature under the key it already holds for the sender, checks every file
against the manifest, and keeps the page beside its own record, never in it. Transport is not
defined (ARCHITECTURE.md, *The circle*): a page travels by mail, by a shared folder, by a USB stick.

`logbook share day`, `logbook receive` and `logbook circle` are the reference implementation
(`logbook/share.py`). The two bundles under `tests/fixtures/share/`, with the two public keys in
`keys.json` beside them, are the fixture a second implementation reads and reproduces.

## Relation to `crossing-package/v1` and `day-package/v1`

A **crossing package** (RFC 0005) is a window of the record for an unattended consumer, pulled
from a folder and not signed. A **day package** (ADR 0013 §4) is the safe index of a day: identity
and shape, never a payload. A **shared page** is for a person: one day, with the payloads, signed,
in one file. It carries the day package of the lines it ships, so a reader that only wants the
index has it, and it uses the crossing package's layout for lines and attachments, so a reader of
one reads the other.

## Shape

A page is a zip file holding exactly these members, and nothing else:

```
manifest.json          this schema; signed
lines.jsonl            the shared lines, verbatim (the standard envelope, SPEC §2)
package.json           the day-package/v1 of those lines (canonical JSON, one line)
attachments/<sha256>   every file the shared lines reference that the sender's store holds
```

Member names are exactly as written: no directory other than `attachments/`, no path with `..`
or a drive, no file the manifest does not name. The receiver refuses a zip that carries anything
else, so nothing a page says can land outside the folder it is kept in.

## `manifest.json`

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"shared-page/v1"` | MUST | |
| `bundle_id` | uuid | MUST | one id per page written; the sender's `crossing/v1` line carries the same |
| `from` | uuid | MUST | the sender's `owner_id` (`logbook.json`) |
| `to` | string | MUST | the receiver, by the name the sender's `policy/crossing.json` gives them |
| `date` | `YYYY-MM-DD` | MUST | the local day the page is of |
| `tz` | IANA name | MUST | the zone that local day is in: the sender's `timezone` |
| `created` | RFC3339 UTC | MUST | when the page was written |
| `max_tier` | 1, 2 or 3 | MUST | the highest tier the page may carry; every line is at or under it |
| `lines` | integer | MUST | how many lines `lines.jsonl` holds |
| `held_back` | integer | MUST | the day's lines that stayed home: above `max_tier` (a retracted line and a retraction are not counted either way) |
| `lines_sha256` | hex sha256 | MUST | the digest of `lines.jsonl`'s bytes |
| `package_sha256` | hex sha256 | MUST | the digest of `package.json`'s bytes |
| `attachments` | array | MUST | one `{sha256, bytes, media_type}` per file under `attachments/`, sorted by digest; empty when none |
| `logbook_head` | hex sha256 | MUST | the sender's chain head when the page was written, before the crossing line that records it |
| `key` | hex, 64 chars | MUST | the public half of the key that signed: what the receiver compares with the key it holds |
| `signature` | hex, 128 chars | MUST | Ed25519 over the pre-image below |

A writer MAY add fields; they are signed with the rest, and a reader ignores what it does not know.
Every digest is lowercase hex, as everywhere in the format.

### The signature

The pre-image is the manifest without its `signature` field, serialised as RFC 8785 canonical JSON
(the chain's own rule, SPEC §3, `chain.canonical_json`) and encoded as UTF-8. The signature is
Ed25519 (RFC 8032) over those bytes, written as 128 lowercase hex characters. Any added field is in
the pre-image too, so a manifest cannot be edited after signing, whichever field is touched.

### The sharing key

Each record has one sharing key, made the first time its owner shares a page. The private half is
a 32-byte seed kept outside the record at `~/.config/logbook/share/<owner_id>.key`, as 64 hex
characters and a newline, readable by the owner alone (mode `0600`). The public half goes into
`logbook.json` as `share_key`, so the record itself says which key signs its pages; writers of
`logbook.json` preserve the field like any other they do not know (SPEC §1). A record whose
`logbook.json` names a key the machine does not hold refuses to share, naming the file: a page is
never signed by a key the record does not name, and a key is never replaced behind the owner's
back. `logbook circle key` prints the public half for handing to a friend.

## `lines.jsonl`

The day's lines, one per line, each the complete envelope of SPEC §2 exactly as the sender's chain
holds it: `id`, `seq`, `prev`, `hash`, `recorded_at` included. The stored form may be re-serialised
(SPEC §2 hashes only the canonical form), and the reference writes sorted keys. The lines are in the
order a reader lists a day (SPEC §3.2): by the instant of `at`, then by `seq`.

Which lines: every line whose local date in `tz` is `date`, at or under `max_tier`, that is not
retracted; a retraction line is not an event of its day (RFC 0003) and is not shipped. The
`held_back` count is the rest of the day's lines above the tier. A line the policy keeps home takes
its attachments with it.

## `package.json`

A `day-package/v1` (ADR 0013 §4, `logbook export --day`) built from the shipped lines alone:
`date`, `tz`, `owner_id`, `generated_at` equal to `created`, `logbook_head`, one `entries` row per
shipped line in the same order (`id`, `seq`, `at`, `end`, `kind`, `tier`, `source`, `raw_id`,
`tags`; never a payload), `derived` empty, and `attachments` equal to the manifest's list. Written
as canonical JSON and a newline, so its digest is reproducible from its content.

## `attachments/`

Every SPEC §1.1 reference the shipped lines carry whose file the sender's store holds, once per
digest, under `attachments/<sha256>`: the record-relative path a line already names, so a line's
`path` resolves inside the page without rewriting. A file the sender's store does not hold stays a
reference and is not listed. The sender hashes each file as it copies it and refuses to ship one
whose bytes are not its name.

## What the sender does

1. Checks the policy first (ADR 0016): `policy/crossing.json` must name the destination, and the
   requested tier may not exceed its ceiling; otherwise the request is refused naming the file and
   nothing is written. Tier 1 is the default; tier 3 crosses only when the file allows it *and* the
   owner typed `--tier 3`, and the console then says so in words nobody can miss.
2. Makes or reads the sharing key; selects the lines; writes the page to a temporary file and
   renames it into place, so a crash leaves no half-written page.
3. Appends one `crossing/v1` line (RFC 0011) to its own chain: destination, the local day's window
   in UTC, the tiers, the counts, the ceiling in force, `logbook_head` and `package_sha256`, the
   digest of `manifest.json`'s bytes; `extra` carries `{"schema": "shared-page/v1", "date"}`. A
   crossing is never invisible: the record shows every page that left it, under which ceiling.

## What the receiver checks

In this order, and all of it before anything is kept:

1. The file is a zip whose members are exactly the ones above, by name: `manifest.json`,
   `lines.jsonl` and `package.json` present, every other member `attachments/<64 hex>`.
2. The manifest parses, is of this schema, and every field has the type and shape the table gives.
3. The sender. With `--from NAME`, the key `policy/circle.json` holds for NAME; without, the circle
   member whose key equals the manifest's `key`. A key nobody in the circle holds is refused with
   the `logbook circle add` line that would add it; the receiver decides whose key that is, never
   the page. The signature MUST verify under the circle's key over the pre-image above. A key the
   page carries is compared, never trusted.
4. `lines.jsonl` hashes to `lines_sha256`; it holds `lines` lines; each parses with no key given
   twice (SPEC §2), has every envelope field, a `tier` of 1, 2 or 3 at or under `max_tier`, a
   `payload.schema`, an `at` whose local date in `tz` is `date`, and a `hash` that recomputes from
   its own `prev`, `seq`, content and `recorded_at` (SPEC §3); no two share an `id`.
5. `package.json` hashes to `package_sha256`, is a `day-package/v1` of this `date` and `owner_id`,
   and its entries' ids are the shipped lines' ids in order.
6. Every attachment the manifest lists is in the zip and every `attachments/` member is listed;
   each is hashed as it is extracted and MUST hash to its name at its stated size.

A page that fails any check is refused with the check named, and nothing of it is kept.

A page is not chain-verifiable: the lines are a subset of the sender's chain with gaps, so
`logbook_head` cannot be replayed (RFC 0005, *Verification*). What the receiver proves is that the
sender signed this manifest, that every file is what the manifest says, and that every line is a
line that hashes as the chain hashes lines, under the sender's `prev` and `seq`. The sender's record
can later be audited against it line by line.

## Where a page is kept

`<root>/circle/<from>/<date>/`, `from` being the circle name the signature was verified under:
the four kinds of file as they were in the zip, plus `received.json`, the receiver's own note (the
sender's name and `owner_id`, the key verified under, when, the zip's name and digest). A page is
read by `logbook day DATE`, which prints a `from <name>` section for each one held: how many lines
by kind, the tier and the day it was shared, and the titles of its events, transcripts, notes, mail
and calls (`received` under `--json`, with line ids).

Receiving the same page again, byte for byte, does nothing. A page newer than the one held
(`created`) replaces it whole, never merged; an older one is refused. The sender's newer view of a
day is the view.

## What the receiver never does

- Never appends to its own chain, and never writes under `logbook/`, `attachments/` or to
  `logbook.json`. A received line is the sender's, with the sender's `seq` and `prev`; it is not,
  and cannot become, a line of the receiver's record. Nothing the receiver does changes its head.
- Never trusts a key the page brought. The key is the circle's, added once by the owner with
  `logbook circle add NAME KEY`; a name already there under another key is refused, so a key is
  never swapped by a typo. The page's `key` field only says which circle member to check.
- Never follows a path from the page. Member names are matched against the fixed set; an
  attachment is named by its digest and placed by the receiver.
- Never raises a ceiling, never reads the sender's policy as its own, never lowers a line's tier.
  A received page's tier is the sender's statement about what they shared, nothing more.
- Never opens, renders or executes an attachment; it hashes bytes.
- Never touches the network. A page is a file.

## Example (synthetic)

`tests/fixtures/share/ines-to-ola/` is Ines Nordmann's Saturday, 2026-06-13, shared with her
brother Ola at tier 2 — two location fixes, a photo with its file, a note; the morning's steps
(tier 3) held back, a message she took back not shipped — and `ola-to-ines/` is Ola's page of the
same day at tier 1, his note and transcript held back. Neither person exists; the keys in
`keys.json` sign nothing but these two pages.

```json
{"schema": "shared-page/v1", "bundle_id": "019cadd3-6bc0-7dcd-9133-00000000a001",
 "from": "c70add25-fcbe-510a-9253-92b542a897e7", "to": "ola", "date": "2026-06-13", "tz": "Europe/Oslo",
 "created": "2026-06-14T18:00:00Z", "max_tier": 2, "lines": 4, "held_back": 1,
 "lines_sha256": "8ccd94815cd6eae339b74c59352de14aefe89699c38c5558e8d7b5d8284888dc",
 "package_sha256": "0f854a6a562eb7b795b5b51cfdd6b52d43db4545d737f402e480152c290bb1a5",
 "attachments": [{"sha256": "b829d2ec5641c7e84d91873c3ae9af0eb49ff5e32620b9da5a8f70433e509d4a", "bytes": 64, "media_type": "image/jpeg"}],
 "logbook_head": "bb97e90d3f946f6cc637e5e223b080ada65e2beb12b07293727e28d2a279b3d8",
 "key": "8965232af604be3294fb964cf0bb9932af098f5f29fe58377578540b4478e9c7",
 "signature": "70f78519c336856f915cdbd0352f932e4dedccda555dda81b84abb534ced8f7967e19cec2460aaba17babfbdc8030cf51135b204143c45a50825239aa96fc40c"}
```

## Notes

- **Why one day.** A page is the unit a person reads, and the unit of the Day (`docs/day.md`): what
  someone hands you about a Saturday sits beside your own Saturday. A window is the crossing
  package's job.
- **Why the lines, not the Day.** A derived Day is disposable (ADR 0013) and would say what the
  sender's engine concluded; the lines say what the sender's sources saw, and the receiver's own
  readers can read them. The day package rides along for a reader that wants only the shape.
- **Why Ed25519 and a key per record.** One signature primitive, small keys, no parameters to get
  wrong, in every language a second implementation would be written in. The key is the record's,
  not the machine's: a record copied to another machine shares under the same key once its key
  file is copied too, and `share_key` in `logbook.json` says which.
- **Encryption** is not here. A page is as private as the channel it travels; tiers 2 and 3 at
  rest are a later version of the format (SPEC §4), and a page of them will follow it.
