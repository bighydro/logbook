# RFC 0002 — payload profile `photo/v1`

Status: frozen for v1.0 · 2026-10-05 (RFC 0031; fixture `conformance/profiles/`) · drafted 2026-09-14 · comment period: two weeks

One image or video asset the owner holds, described by its metadata. The pixels are never in the log; the line points at them.

## Line

`kind` MUST be `photo`. `tier` SHOULD be 1 for metadata. `at` is the capture time (EXIF original) when known, otherwise the file time; `end` is null (video duration goes in the payload).

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"photo/v1"` | MUST | |
| `asset_id` | string | MUST | the library's id (Immich asset id, Photos UUID, file hash) |
| `library` | string | MUST | `immich`, `apple-photos`, `google-photos`, `folder` |
| `file_name` | string | SHOULD | original name |
| `media` | string | SHOULD | `image` or `video` |
| `lat`, `lon` | number | MAY | from EXIF |
| `camera` | string | MAY | make and model |
| `width`, `height` | integer | MAY | |
| `duration_s` | number | MAY | videos |
| `live_photo` | boolean | MAY | |
| `provenance` | string | SHOULD | `camera`, `received`, `screenshot`, `other` — see ADR 0011 |
| `faces` | integer | SHOULD | number of faces the library detected |
| `people` | array of string | MAY | the library's person ids for those faces (ids, never names) |
| `content_hash` | string | MAY | sha256 of the original file, for cross-library dedupe |
| `favorite` | boolean | MAY | the owner marked it a favourite in this library; written only when true |
| `hidden` | boolean | MAY | the owner hid it in this library; written only when true |
| `albums` | array of string | MAY | the titles of the owner's own albums it is in, in this library, sorted; never the library's automatic groupings (smart albums, memories, shared streams) |

## Provenance rule (reference)

`camera` when the asset has a live-photo pair, or when make/model and an original capture time are present on a camera file type (HEIC/RAW/JPEG/video); `screenshot` when PNG at a device screen size with no camera data; `received` when there is no EXIF and the name follows messenger patterns (`IMG-2026…-WA0012`, `image0.jpg`); else `other`. Owners correct with one tap; corrections are `manual` lines.

A library that records how an asset arrived (Photos' `importedBy`: the back or front camera, a third-party app, AirDrop) uses that record instead of the heuristics: `camera` from the camera or a live-photo pair, `screenshot` when the library marks it one, `received` when it came from another app or another device, else `other`.

## Several libraries, one asset (merge rule)

The same photo reaches the record from more than one library: the phone's own Photos store
(`apple-photos`) and the server it is backed up to (`immich`), or a Takeout folder. Each library's line
is written — they are different observations with different `source`, and `(source, raw_id)` dedupes
only within one (SPEC §3: nothing is dropped because another source saw it first). A reader folds them
by this rule and never by guessing:

- Two `photo/v1` lines describe **the same asset** when their `file_name` is equal ignoring case and
  their `at` denote instants at most one second apart. Both fields are what a camera wrote (the
  original file name, the EXIF capture time) and every library keeps them; one second absorbs the
  libraries' rounding (Immich drops sub-seconds, Photos keeps them). Width, height and `content_hash`,
  when both lines have them, MUST agree or the lines are not folded.
- The fold is a **union**: a favourite in either library is a favourite; `albums` is the union of
  both lists; `people` stays per library (person ids are the library's, `p_17` means nothing to another
  library) under the line's own `source`; a `provenance` the libraries disagree on is shown from the
  line with the better evidence (`camera` over `other`), and the owner's `manual` correction wins over
  both.
- The rule is a reader's. No adapter rewrites a line, adds another library's id, or skips an asset
  because another library has it.

## Example (synthetic)

```json
{"at":"2026-03-01T09:12:00Z","end":null,"tz":"Europe/Oslo","source":"immich","kind":"photo","tier":1,
 "payload":{"schema":"photo/v1","asset_id":"5d3e…","library":"immich","file_name":"IMG_0001.HEIC","media":"image",
  "lat":59.913,"lon":10.742,"camera":"SimPhone 3","width":4032,"height":3024,"live_photo":true,"provenance":"camera","faces":2,"people":["p_17","p_42"]}}
```
