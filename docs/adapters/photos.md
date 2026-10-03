# Apple Photos: the library, its albums, favourites and faces

One store, three kinds of line. `logbook add photos` (or `import-backup --only apple-photos`) reads
the `Photos.sqlite` an iPhone keeps under `CameraRollDomain` — the library's own record of every
asset — and writes one `photo/v1` line per asset not in the trash (RFC 0002): what the camera wrote,
where the library thinks it was taken, how it arrived, the owner's own albums and marks, and the
faces the library found. The pixels stay where they are; no image is copied. In the same run the
favourites and the Art album become `keeper/v1` lines (RFC 0024). Reading the record back, the names
the library gave its faces are *proposed* company on the stay that holds the photo, never confirmed.

```bash
logbook add photos ~/backup/apple-photos/Photos.sqlite              # one photo/v1 line per asset, then the keepers
logbook add photos ~/backup/apple-photos/Photos.sqlite --dry-run    # count both against the record; write nothing
logbook import-backup ~/Library/Application\ Support/MobileSync/Backup/<udid> --only apple-photos
logbook keepers                                                      # the marked photos, by day and lane
logbook keepers --people                                             # who appears on them, per month, proposed
logbook describe keepers --photos ~/Pictures/Photos\ Library.photoslibrary   # a local vision model's sentence per keeper, from the originals (docs/describe.md)
logbook day 2026-03-01                                               # a face's name under `with … (proposed)`
```

The source is read-only and immutable (`mode=ro`, `immutable=1`): nothing is written beside it, not a
journal. Every table the adapter needs is confirmed by `PRAGMA table_info` first; a column it does not
need may be missing or renamed and the rows still read, and a table that is not there (an old
library with no `ZPERSON`) is a line without that field, never an error. Nothing goes on the network.

## The asset: `photo/v1`

| Field | Where it comes from |
|---|---|
| `raw_id`, `asset_id` | `ZASSET.ZUUID`: the dedupe key, so a second import writes nothing |
| `library` | `apple-photos` |
| `file_name` | the original name the camera or the sender gave the file (`ZORIGINALFILENAME`), else the library's own; with `at`, the merge key a reader folds the Immich line for the same asset on |
| `at`, `tz` | the capture time to the second (`ZDATECREATED`, seconds since 2001 in UTC); the asset's own IANA zone when it has one, else the record's |
| `media`, `width`, `height`, `duration_s`, `live_photo` | the kind, the pixel size, a video's length, a motion half |
| `lat`, `lon` | when the store has them (`-180` is none) |
| `provenance` | from the store's own record of how the asset arrived: `screenshot`; `camera` for a live photo, a camera video kind or an import by either camera; `received` from another app, AirDrop or a share; else `other` |
| `faces` | how many faces the library found |
| `people` | the UUIDs of the people among them the owner has **named** (a merged person under its merge target); ids, never names, as RFC 0002 says |
| `favorite`, `hidden` | the owner's marks, written only when set |
| `albums` | the titles of the owner's own albums (`ZGENERICALBUM.ZKIND` 2, not trashed) the asset is in, sorted; smart albums, memories, shared streams and folders are not albums |
| `extra.faces` | the names of the people under `people`, as the People album shows them (the full name, else the display name; a merged person under its target's name), sorted |
| `extra.uti`, `extra.imported_by`, `extra.imported_by_bundle` | the type identifier, the importing route and app |

Trashed assets and assets with no capture date are skipped and counted. Tier 1 (metadata;
`--tier` overrides). A synthetic line, the Oslo persona's:

```json
{"at":"2026-03-01T09:12:00Z","end":null,"tz":"Europe/Oslo","source":"apple-photos","kind":"photo","tier":1,
 "payload":{"schema":"photo/v1","raw_id":"A0000000-0000-4000-8000-000000000001","asset_id":"A0000000-0000-4000-8000-000000000001",
 "library":"apple-photos","file_name":"IMG_0001.HEIC","media":"image","lat":59.913,"lon":10.742,"width":4032,"height":3024,
 "live_photo":true,"provenance":"camera","faces":2,"people":["C0000000-0000-4000-8000-000000000020"],"favorite":true,
 "albums":["Boats","Oslo weekend"],
 "extra":{"uti":"public.heic","imported_by":1,"imported_by_bundle":"com.apple.camera","faces":["Kari Nordmann"]}}}
```

`extra.faces` is this adapter's extension inside the payload (SPEC §2: extensions go in `payload`),
not a field of the profile: `people` stays the ids, as the RFC requires, and the names ride beside
them because a name is what a reader can act on and a UUID is what it can dedupe on. A name is the
owner's own spelling in their own library; it is written at tier 1 with the rest of the metadata, and
`--tier 2` raises the whole import when that is wanted.

## The marks: `keeper/v1`, written on import

A favourite is a `memory` keeper, a photo in an album named `Art` is an `art` keeper (RFC 0024 rule
2), and the import writes them itself, right after the photo lines: for every marked draft the photo
line's id is looked up by `(source, raw_id)` through the index, the keeper is built from that line,
and `append_many` skips a `(keeper-inference, <photo line id>:<lane>)` the record already holds,
retracted or not. So a second import writes no keeper twice, an unmarked favourite the owner retracted
stays retracted (rule 3), and `logbook infer keepers` run afterwards finds nothing left to write. The
run says what it did:

```
added 6 lines from apple-photos
  skipped 1 without a timestamp, 1 in the trash
  keepers: 1 new from 1 marked photo of 6
```

`--dry-run` counts the keepers the same way — a photo not yet in the record would be a new keeper;
one already there is looked up — and writes nothing: `keepers: 1 would be written, 0 already in the
record (dry run, nothing written)`.

## The faces, read back: proposed, never confirmed

A face is the library's guess at who is in the picture, and `extra.faces` is the owner's label for
that guess. The with module (`present.from_photos`, the `with` of `logbook day`, the pages and
`trips`) lists each name as **proposed** company, confidence 0.5, at the stay that holds the photo,
and it never confirms one: a note that says `with Kari Nordmann`, a transcript she spoke in or a
calendar entry she attended confirms; a face only ever rides along as a further reason. A name is
resolved to a person only when it is exactly the label a resolution line carries, case and spacing
aside: `Kari Nordmann` is Kari Nordmann when a resolution line labels her so; `Kari` alone is not,
since nobody wrote that name at the stay (the loose first-name rule of a note does not apply); `Trude`,
whom no resolution line knows, is listed as written with no person. A face the line names both by id
(`people`, through a `provider_id` resolution `apple-photos:<uuid>`) and by name is one entry, and the
owner's own face is never their own company. `rollup people`, `people` and the days together count
the confirmed set only, so a person the record knows by a face alone is in none of them.

```
  09:12–11:40  stay · 59.9130,10.7420 near Home, 0.6 km · 2 h 28 min · 1 note, 3 photos, 1 keeper
      note         Coffee on the quay with Ola Nordmann
      keeper       IMG_0001.HEIC (memory)
      with         Ola Nordmann (note) · proposed Kari Nordmann (photo)
```

## Who is on the keepers: `logbook keepers --people`

```
2026-03
  Kari Nordmann                   3 keepers  memory 2 · art 1       proposed
  Trude (no person)                1 keeper  memory 1               proposed
```

Per local month, everyone named on the keepers standing — the faces the library named and the people
it tagged by id on each keeper's photo line, resolved as above — with how many keepers they are on,
by lane. `--since`, `--until` and `--lane` cut the keepers first. Every row is `proposed`: this view
writes nothing and asserts nothing, and RFC 0024 rule 1 writes no line for a face. Under `--json`
each row carries `month`, `name`, `person` (the entity id, or null), `status`, `keepers`, `lanes`
and the keeper `lines`.

## The fixture

The tests build a synthetic `Photos.sqlite` with the real table names (`ZASSET`,
`ZADDITIONALASSETATTRIBUTES`, `ZGENERICALBUM`, the `Z_33ASSETS` join found by its shape, `ZPERSON`,
`ZDETECTEDFACE`) around the Oslo persona, who does not exist: eight assets, two user albums and a
trashed one, a smart album and a folder, a named person, an unnamed one, one merged into the named
one, and one named by a display name only. Nobody in it is real.
