# RFC 0033 — bundle format `asset-package/v1`: an asset sold with its record

Status: draft · 2026-10-03 · comment period: two weeks · **the consent section is to be read by a non-technical co-author before the comment period opens**; the technical sections may be commented on now.

A boat is sold with her papers: the deck log, the yard's invoices, the survey. A house changes hands with the record of what was done to it. The owner's logbook already holds that record, as the lines whose `subject` is the asset (ADR 0018, RFC 0001 rule 2): her positions, her passages, and, as profiles arrive, what was serviced and when. Those lines are about the hull, not about the owner's day, and when the hull goes, they should be able to go with it. This RFC says which lines travel with an asset and which never do, defines the bundle they travel in, says how the buyer verifies it and imports it under the asset's id, and what the seller's record looks like afterwards.

It does not change the envelope (SPEC §2–3), the hash, or the meaning of any existing line. It adds a bundle format beside `crossing-package/v1` (RFC 0005), two tier-1 lines (one in each record) and a reading of `subject` that every profile already carries or may carry.

## Words

- An **asset** is an entry in the owner's `assets.json`: `{id, kind, name, mmsi?, icao24?, registration?}` (ADR 0018). This RFC uses one more `kind`, `house`, and one more identifier, `identifiers`, a free map of the asset's public identities (`hin`, the hull identification number; `cadastral`, a land registry reference; `vin`) so the bundle can name the thing in the world and not only in one record.
- The **asset's record** is the set of lines in the owner's record whose payload carries `subject` equal to the asset's id, together with the retractions that hide any of them and the attachments they point at. It is a reading of the owner's record, never a second folder: the owner has one record (ADR 0003).
- The **seller** is the owner whose record the lines leave; the **buyer** is the owner whose record they enter. Both are ordinary records with their own chains. Nothing in this RFC gives an asset a chain of its own.

## What travels, and what never does

The rule is one sentence: **a line travels when the asset is its subject, and nothing about a person ever travels.** The table applies it to the profiles that exist and to the two most likely to come.

| Travels with the asset | Never travels |
|---|---|
| `location/v1` lines with `subject` the asset (RFC 0001): her own track, from AIS, ADS-B, a tracker in the car, a positioned deck-log end | every `location/v1` line without `subject`: the owner's track, however often it was aboard |
| `trip/v1` lines with `subject` the asset (RFC 0020, mode `passage`): declared legs, with their `geometry`, `name`, `extra.note` | `trip/v1` lines of the owner's own movement (a taxi to the marina), and any line carrying `price` (tier 3, money) |
| a future `maintenance/v1` or `meter/v1` with `subject` the asset: what was serviced, replaced, read, with the attachments they point at (an invoice photographed, a survey) | `transaction/v1` (RFC 0021): the yard's bill as the bank saw it is the owner's money, tier 3, and MUST NOT travel even when it names the boat |
| `retraction/v1` lines (RFC 0003) whose `supersedes` names a travelling line: a hidden position stays hidden for the buyer (rule 4) | `message/v1`, `mail/v1`, `call/v1`, `transcript/v1`, `note/v1`, `voice-memo/v1`: the owner's words and the words of others, even about the boat |
| the asset's entry from `assets.json`, as `asset.json` in the bundle | `event/v1`, `photo/v1`, `keeper/v1`: a calendar entry has attendees, a photo has faces; a photo *of* the boat is a photo the owner took, and travels only by the owner's hand (open question 2) |
| counts the seller's readers derive from the two tracks together, as numbers and never as lines: nights aboard per year, passages and distance per year, ports called at (rule 5) | the company of any stay (SPEC §3.2.5), the resolution lines (RFC 0006), `crossing/v1`, `custody/v1` (RFC 0032), `health-sample/v1`, `task/v1`, `browse/v1`, `watch/v1`, `listen/v1`, `highlight/v1`, `commitment/v1` and every other line whose subject is a person |
| a place of kind `asset-berth` from `places.json` whose name the seller chooses to send (rule 6) | the owner's `home` and `other` places, `policy/`, `logbook.json`, `notes/`, `state/`, the index |

A profile written after this RFC that carries `subject` travels under the rule without an amendment here; a profile whose lines are about the owner never carries `subject` (RFC 0001 rule 1: there is no id for the owner) and never travels.

## Shape

An asset package is a directory, or a tar of one:

```
<bundle>/
  manifest.json          # this schema
  asset.json             # the assets.json entry: {id, kind, name, mmsi?, icao24?, registration?, identifiers?}
  entries.jsonl          # the travelling lines, verbatim (the standard envelope), in seq order
  attachments/<sha256>   # the files the travelling lines point at (SPEC §1.1 layout)
  skeleton.jsonl         # OPTIONAL — the proof of place (Verification)
  places.json            # OPTIONAL — the berth(s) the seller sends (rule 6)
```

## `manifest.json`

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"asset-package/v1"` | MUST | |
| `bundle_id` | string | MUST | uuid for this export |
| `generated_at` | RFC3339 UTC | MUST | |
| `owner` | string | MUST | the seller's `owner_id` (a uuid, not a name): provenance, so two bundles of one hull from two owners read as a chain of owners |
| `asset` | object | MUST | `{ id, kind, name, identifiers }` as `asset.json` carries them; `identifiers` SHOULD name at least one identity the world knows (`mmsi`, `hin`, `registration`, `cadastral`), so a buyer can check it is the hull they bought |
| `logbook_head` | hex sha256 | MUST | the seller's chain head at generation, the head before the `crossing/v1` line that records this export |
| `covers` | object | MUST | `{ from, to }`, RFC3339 UTC: the lines of the asset's record with `from` ≤ `at` < `to`. `from` SHOULD be the `at` of the first line with this subject; `to` the generation time |
| `counts` | object | MUST | `{ logged, crossed, held_back, by_kind, by_tier, retractions, attachments: { included, bytes, missing } }`, `held_back` the lines with this subject the seller kept back by rule 3 |
| `entries_file` | string | MUST | `entries.jsonl` |
| `entries_sha256` | hex sha256 | MUST | the digest of that file's bytes |
| `proof` | string | MUST | `lines` or `skeleton` (Verification) |
| `skeleton_file` | string | `skeleton` | `skeleton.jsonl` |
| `skeleton_sha256` | hex sha256 | `skeleton` | its digest |
| `summary` | object | SHOULD | the derived counts of rule 5: `{ nights_aboard: {"<year>": n}, passages: {"<year>": n}, distance_m: {"<year>": n}, ports: ["<label>", …], first, last }`; numbers and labels only, no line ids |
| `blobs` | array | SHOULD | `[{ sha256, path, bytes, media_type }]`, the SPEC §1.1 shape, for every attachment included |
| `places_file` | string | MAY | `places.json` when a berth is sent |

A consumer MUST ignore manifest fields it does not know.

## Rules

1. **Verbatim or not at all.** A travelling line crosses exactly as it is stored in the seller's record: every envelope field, `id`, `seq`, `prev`, `hash` and `recorded_at` among them, and the payload byte for byte in canonical terms. Nothing is rewritten on the way, not even `subject`: a line's content digest is its identity across records (rule 8), and a rewritten line is a different line that proves nothing.
2. **The subject decides.** The exporter selects by `payload.subject` equal to the asset's id and by nothing else; a line about the boat that does not carry `subject` (a note that mentions her, a photo of her, a yard's invoice as a transaction) does not travel, however much it is about her. The owner who wants one of those to travel writes a line with `subject` that says what it says (an `extra.note` on a passage; a `maintenance/v1` when it exists), never a flag on the owner's own line.
3. **The seller may hold a line back, and the count says so.** A position the seller does not want to travel (the week she lay at a place the seller would rather not name) is held back by `at` window or by `id`; `counts.held_back` and `counts.logged` show the buyer that lines with this subject exist that did not come. The exporter never offers to hold back a retraction whose target travels (rule 4).
4. **Hidden stays hidden.** Every `retraction/v1` line whose `supersedes` is a travelling line travels too, verbatim, so the buyer's readers mark the line as the seller's did (RFC 0003 rule 3). The retraction's `reason` is the owner's words, tier 2; it travels because the alternative, a hidden line shown to the buyer as if it stood, is worse. The exporter MUST list the travelling retractions in the `review` the console prints before writing, as tier-2 crossings are reviewed (ADR 0016 rule 3), so the seller reads each reason before it goes.
5. **Numbers travel; the owner's track does not.** How many nights the owner slept aboard in a year is a fact about the boat a buyer reasonably asks for, and it is derived from the owner's track against hers (SPEC §3.2.3 rule 7, `rollup nights` `aboard`). The exporter puts the numbers in `summary`, per calendar year, with no line ids and no dates finer than the year; the owner's `location/v1` lines never leave. The ports in `summary.ports` are the labels of the *asset's own* stays (SPEC §3.2.6 rule 4 applied to her track), which the buyer could derive from `entries.jsonl` anyway. `summary` is a courtesy, not evidence: it is not verifiable from the bundle and a buyer treats it as the seller's word.
6. **A berth is a place, and places are the owner's.** `places.json` is the owner's geography (home among it) and never travels whole. The seller MAY send the entry of kind `asset-berth` where the boat lies, since the buyer will likely take the berth or needs to know where to find her; the entry travels as a one-place `places.json`, and the buyer's import merges it only when the buyer says so.
7. **The export is a crossing.** `logbook export asset <id> --to <buyer>` behaves as `export crossing` does under ADR 0016: the buyer is a `destination` in `policy/crossing.json` with a ceiling, a bundle that would carry a tier above it is refused naming the file, a dry run writes nothing, and every real export appends one `crossing/v1` line (RFC 0011) with `destination` the buyer, `window` `covers`, `counts`, `policy`, `logbook_head` and `package_sha256` the manifest's digest, plus `extra.asset` the asset's id and `extra.schema` `asset-package/v1`, so an audit of crossings (RFC 0011 rule 5) finds the sale. The lines of an asset's record are tier 1 (positions, passages) except the retractions of rule 4 and whatever a future profile says, so the usual ceiling of 2 lets an ordinary sale through and a `maintenance/v1` that carried a price at tier 3 would not.
8. **Import under the asset's id.** The buyer registers the asset in their own `assets.json` under the id the bundle carries (`asset.json`), or, when that id is taken in the buyer's record, under a new id with the bundle's id listed under `was` on the entry, so readers that filter by subject can be told the two tokens are one hull (open question 4). `logbook import asset <bundle>` then appends every line of `entries.jsonl`, through `Logbook.append` and nothing else, as new lines of the buyer's chain: `at`, `end`, `tz`, `source`, `kind`, `tier` and `payload` unchanged, so the content digest of each line equals the one in the seller's chain and the line's provenance can be checked against the bundle for as long as either record exists; `id`, `seq`, `prev`, `hash` and `recorded_at` are the buyer's, because the chain is. The seller's envelope values for each line are not written into the line (`extra` is inside `payload`, and a changed payload is a changed digest); they are kept in the receipt line instead (rule 9). Dedupe is by `(source, raw_id)` as every import is (ADR 0017): a bundle imported twice appends nothing, and a line whose `(source, raw_id)` the buyer's record already has (the buyer tracked the same MMSI by AIS before the sale; the receiver does not know who owns the hull, ADR 0018) is skipped and counted, the buyer's own observation standing.
9. **The receipt.** After the import the buyer's record gets one tier-1 `asset-transfer/v1` line, `source` `logbook`, `kind` `asset-transfer`: `{ schema, asset: { id, was? }, bundle_id, from_owner, logbook_head (the seller's), package_sha256, covers, counts: { imported, skipped, retractions, attachments }, summary (as the manifest's), provenance: [ { id, seq, hash, recorded_at, imported_as } ] }`, the last mapping every seller line to the buyer's line that now carries it. A record that holds a hull's history from two owners holds two receipts, and the chain of owners is read from them. The receipt is the only place the seller's `owner_id` appears in the buyer's record.
10. **The seller afterwards.** The seller's lines stay where they are: nothing is removed (SPEC §3), and a boat the seller owned for nine years is nine years of the seller's own record. What changes is the registry and the instruments: the seller removes the asset from `assets.json` or marks it `until` the sale date, so `sync ais` stops asking the receivers for a hull that is now someone else's position, and `rollup nights` stops counting nights aboard a boat the owner cannot be aboard. The buyer cannot verify that the seller stopped; the consent section says what that means.

## Verification

A bundle is a subset of the seller's chain, so, as RFC 0005 says of a crossing package, the buyer cannot replay it to `logbook_head`. Two levels of proof are offered and `proof` says which the bundle carries:

**`lines`.** Each travelling line's `hash` recomputes from its own fields (SPEC §3), so the buyer knows each line is one the seller's chain once held and that the seller did not change it after writing it. Nothing is known about what lay between the lines. This is RFC 0005's level and the default.

**`skeleton`.** `skeleton.jsonl` holds one small object for *every* line of the seller's chain from the first travelling line to `logbook_head`, in `seq` order: `{ seq, content_sha256, recorded_at }`, with `content_sha256` the digest of the canonical content (the inner digest of SPEC §3, never the content). A travelling line's object is the same three fields and the line itself is in `entries.jsonl`. The buyer replays the chain: starting from the `prev` of the first travelling line, for each object `hash = sha256(prev | seq | content_sha256 | recorded_at)`, and the last hash MUST equal `logbook_head`; for each travelling line, `sha256(canonical content)` MUST equal the skeleton's `content_sha256` at its `seq`. This proves that every travelling line sits where the bundle says it does in a chain that ends at the stated head, and that no line among them was dropped or added. It does not prove that no *asset* line was withheld: a hidden object's content is unknown, and `counts.held_back` is the seller's word for how many of them carry this subject. The price of the proof is what the skeleton reveals: how many lines the seller's record holds over the span and the `recorded_at` of every one, which is when the seller's instruments and the seller were active, to the second. That is a real disclosure and the consent section treats it as one.

A verifier MUST hash every attachment in the bundle against its name (SPEC §1.1), MUST check `entries_sha256` and `skeleton_sha256`, and MUST NOT expect the chain.

## Consent

> **Review wanted from a non-technical co-author.** This section is about what a buyer learns about a seller from a boat's record, what a seller keeps, and what the person who sold the boat to the seller never agreed to. It was written by people who think in hashes; please read it as the seller and as the buyer, and say where it is naive.

**What the buyer learns about the seller.** A boat's track is where the boat was, and for most of a season that is where the seller was. `summary.nights_aboard` says, per year, how many nights the seller slept on her; the asset's track says where she lay each of those nights, so the two together place the seller on a quay on a date, even though no line of the seller's track travels. The RFC keeps the nights to a count per year for that reason, and lets the seller hold positions back (rule 3) with the count showing that they did. A deck log's `extra.note` is the keeper's remark in the keeper's words and travels with the leg; the seller reads the review before the export (rule 4 for retractions; the console SHOULD show notes too, open question 3). The skeleton proof tells the buyer when the seller's record was written to, every line, to the second, over the years the boat was theirs; that is a pattern of a life, and the default is therefore `lines`, with `skeleton` an option the seller chooses knowing what it says.

**What the seller keeps.** Everything. The lines stay in the seller's record, and the seller's own readers will show the boat's passages on the days the seller was aboard for as long as the record exists. A buyer who assumes that selling the boat removed its past from the seller's hands assumes wrong, and should be told so in the words the import prints. What the seller must stop is observing: the hull's position after the sale is the buyer's whereabouts, and a seller who leaves the MMSI in `assets.json` keeps tracking the buyer. Rule 10 asks the seller to stop; the RFC cannot make them, and the buyer cannot check. Whether the format should let a buyer *ask* a receiver to stop reporting a hull to a former owner is beyond a file format and is noted as such.

**The owner before the seller.** A hull bought with a bundle and sold again carries two owners' lines. The first owner agreed to send their lines to the second; they did not agree to the third. The receipt chain (rule 9) makes the provenance visible; it does not make the first owner's consent travel. The default proposed is that imported lines travel on with the asset, because the alternative, that a boat's record thins with each sale, is the thing the papers exist to prevent, and because what travels is the hull's track and not anyone's words. Open question 1 asks whether the first owner should be able to say otherwise at the first sale.

**Houses.** A house does not move, so its record is maintenance, meters and documents, not a track; the people it reveals are the ones who lived in it, and a `maintenance/v1` line that names the plumber names a person. The rule that nothing about a person travels holds; how a maintenance profile keeps the plumber's name out of the subject's line, or marks it so the exporter holds it back, is that profile's problem and should be solved before `house` is used for a sale.

**Cars.** A car's track is its driver's track, and a car driven by one partner, a child or a friend (ADR 0018) carries their whereabouts. A seller who did not drive the car alone sends other people's days. The export SHOULD say how many of the car's days the owner's own track places them in the car, and the rest is the seller's judgement; this RFC proposes no rule beyond that and asks for one.

## Example (synthetic)

The Nordlys of the passages fixture, sold after two seasons. Her MMSI, her owner and her buyer do not exist.

```json
{"schema":"asset-package/v1","bundle_id":"019cadd3-6bc0-7dcd-9133-043f5aabf400","generated_at":"2026-10-01T09:00:00Z",
 "owner":"019cadd3-6bc0-7dcd-9133-000000000010",
 "asset":{"id":"nordlys","kind":"yacht","name":"Nordlys","identifiers":{"mmsi":"970123456","hin":"NO-XYZ00001A626"}},
 "logbook_head":"53d39fda0b4d7a1e3c9f8e2d1a0b6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f0a9b",
 "covers":{"from":"2025-04-02T06:00:00Z","to":"2026-10-01T09:00:00Z"},
 "counts":{"logged":18422,"crossed":18390,"held_back":32,"by_kind":{"location":18311,"trip":76,"retraction":3},"by_tier":{"1":18387,"2":3,"3":0},
 "retractions":3,"attachments":{"included":4,"bytes":2210442,"missing":0}},
 "entries_file":"entries.jsonl","entries_sha256":"9afdd1bd5f7e4c3b2a1908f7e6d5c4b3a291807f6e5d4c3b2a1908f7e6d5c4b3",
 "proof":"lines",
 "summary":{"nights_aboard":{"2025":41,"2026":37},"passages":{"2025":38,"2026":38},"distance_m":{"2025":2104300,"2026":1988750},
 "ports":["Cannes","Genoa Molo Vecchio","Portofino","Bonifacio"],"first":"2025-04-02","last":"2026-09-28"},
 "blobs":[{"sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","path":"attachments/e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","bytes":241088,"media_type":"application/pdf"}],
 "places_file":"places.json"}
```

The buyer's receipt, after `logbook import asset`:

```json
{"at":"2026-10-02T15:20:00Z","end":null,"tz":"Europe/Oslo","source":"logbook","kind":"asset-transfer","tier":1,
 "payload":{"schema":"asset-transfer/v1","asset":{"id":"nordlys"},"bundle_id":"019cadd3-6bc0-7dcd-9133-043f5aabf400",
 "from_owner":"019cadd3-6bc0-7dcd-9133-000000000010",
 "logbook_head":"53d39fda0b4d7a1e3c9f8e2d1a0b6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f0a9b",
 "package_sha256":"1f0a9b53d39fda0b4d7a1e3c9f8e2d1a0b6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e",
 "covers":{"from":"2025-04-02T06:00:00Z","to":"2026-10-01T09:00:00Z"},
 "counts":{"imported":18102,"skipped":288,"retractions":3,"attachments":4},
 "summary":{"nights_aboard":{"2025":41,"2026":37},"passages":{"2025":38,"2026":38},"distance_m":{"2025":2104300,"2026":1988750},
 "ports":["Cannes","Genoa Molo Vecchio","Portofino","Bonifacio"],"first":"2025-04-02","last":"2026-09-28"},
 "provenance_sha256":"7c1e9b02d5f7e4c3b2a1908f7e6d5c4b3a291807f6e5d4c3b2a1908f7e6d5c4"}}
```

`skipped` 288: the buyer had been receiving the hull's AIS reports for a fortnight before the sale (the receiver does not know who owns her), and those `(source, raw_id)` pairs were already in the buyer's record. The `provenance` list of rule 9 is 18,102 entries long, so the example carries its digest in place of the list; whether the list belongs in the line or in an attachment the line points at is open question 5.

## Notes

- **Why not give the asset a chain of its own.** A boat with her own `logbook.json` would be a second record for one person to keep, which ADR 0003 refused, and a chain nobody is the subject of. The asset's record is a reading of the owner's, and a sale moves lines from one person's chain to another's, which is what every import already does.
- **Why the lines are not rewritten on import.** A buyer who could prove, years later, that a passage in their record is byte for byte the one the seller's chain held on the day of sale has the boat's papers. A buyer whose import changed `subject` to a new id has a copy with the seller's word for it. The id travels so the proof does.
- **Why the seller's `owner_id` is in the bundle.** Provenance needs a name for the previous keeper of the lines, and a uuid is the least a name can be. It is not a resolution to a person; the buyer's record never learns who the seller was unless the buyer writes it.

## Open questions

1. **The first owner's consent at a second sale.** Should a line imported from a bundle carry, in the receipt, a flag from the first seller (`onward`: `true`/`false`) that the exporter honours at the next sale, so a seller can say "to this buyer and no further"? That is a right the format can state and no format can enforce.
2. **Photos of the asset.** A `photo/v1` line has no `subject`, and a photo of the boat often has the owner's family in it. Should the owner be able to mark a photo as the asset's (a `keeper/v1` lane `asset`? a `subject` on `photo/v1`, amending RFC 0002?) so it travels, and should the exporter show the photo before it goes?
3. **Reviewing words that travel.** Rule 4 makes the retraction reasons reviewed. A passage's `extra.note` and `extra.check` are also words; should every travelling line with any free-text field be in the review, or every line (a bundle of 18,000 positions is not reviewable line by line, ADR 0005)?
4. **Two tokens, one hull.** When the buyer's record already uses the id, rule 8 proposes `was` on the `assets.json` entry so readers can treat two subject tokens as one asset. That makes the registry, a setting, decide what a reader joins, which ADR 0018 rule 4 avoided. The alternative is to require the bundle's id and refuse the import on a clash.
5. **Where the provenance list lives.** A receipt that maps every imported line to its seller line is as long as the import. In the payload it makes one very large line; as an attachment it is outside the chain and the line carries its digest. Which?
6. **A house is not a subject that moves.** ADR 0018 says assets are subjects because they move. A house has no track and may equally be a `places.json` entry with documents. Is `kind` `house` an asset, a place with a record, or both; and does the answer change what a `maintenance/v1` line's `subject` is?
7. **A sale while a crossing is standing.** The buyer's hull positions after the sale are, to the seller's circle, noise about someone else. Should the seller's `crossing/v1` to the buyer be the last line about the asset the seller's unattended consumers (ADR 0016) see, and how would a consumer know?
8. **The summary's evidence.** `summary` is unverifiable by design (rule 5). Should the bundle be allowed to carry, for each counted night, the asset's own stay id (`stay:nordlys:…`, derivable from the travelling track) and no more, so the buyer can check the count against the track without the owner's lines?
