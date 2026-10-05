# RFC 0024 — payload profile `keeper/v1`

Status: frozen for v1.0 · 2026-10-05 (RFC 0031; fixture `conformance/profiles/`) · drafted 2026-10-01 · comment period: two weeks

One statement that the captain marked a photo a keeper: a photo worth coming back to, in one of two lanes — a *memory* (the day's hero photo, the one a Day page shows first) or *art* (a picture kept for itself, not for the day). A `photo/v1` line (RFC 0002) says a photo exists and what the library knows about it; this line says the owner chose it. The choice is an observation of the owner's own act, made in a photo library (a favourite, an album) or at the command line, and it is recorded as such: never inferred from faces, views or any model.

## Line

`kind` MUST be `keeper`. `tier` SHOULD be 1 (SPEC §4: photo metadata). `at` is the photo's capture time, the `at` of the photo line it points at, so a keeper is on the photo's day; `end` is null. `source` is the producer: `keeper-inference` for the step that reads marks out of photo lines (below), `manual` for a mark the owner typed.

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"keeper/v1"` | MUST | |
| `raw_id` | string | MUST | `<photo line id>:<lane>`; the dedupe key, so a mark read twice is one line |
| `photo` | object | MUST | the photo: `{ line, asset_id, library, file_name? }` — the `id` of the `photo/v1` line, and its `asset_id` and `library` as that line carries them, so the keeper reads without the index |
| `at` | RFC3339 UTC | MUST | the photo's capture time, as the line's `at` |
| `lane` | string | MUST | `memory` or `art` |
| `source` | string | MUST | where the mark was made: `ios-photos`, `immich`, `manual`, or another library's name as `photo/v1` spells `library` |
| `marked_at` | RFC3339 UTC | MAY | when the owner made the mark, when the library says |
| `supersedes` | string | MAY | the id of an earlier keeper line for the same photo and lane this one replaces |

## Rules

1. **A keeper is the owner's act.** A line is written only for a mark the owner made: a favourite in a library, membership of an album the owner keeps for the purpose, a word at the command line. No reader proposes keepers; a reader that wants to suggest one writes nothing and shows its suggestion.
2. **Favourites are memories; the `Art` album is art.** The producer `keeper-inference` (`logbook infer keepers`) reads every `photo/v1` line standing and writes a `memory` keeper for each photo its library marked a favourite (`favorite` true, at the payload's top as the `apple-photos` adapter writes it or under `extra` as `immich` keeps `isFavorite`) and an `art` keeper for each photo in an album named `Art` (`albums`, or `album`, at the payload's top or under `extra`, any entry equal to `Art`, case aside). A photo may be in both lanes: two lines. `source` is the photo line's `library`, with `apple-photos` written as `ios-photos`.
3. **Unmarking is a retraction.** A favourite the owner removes is a mark the owner took back; the producer does not delete anything (SPEC §3) and does not write "not a keeper". The owner retracts the keeper line (RFC 0003), and the producer never rewrites a retracted mark: a `(source, raw_id)` already in the record, retracted or not, is skipped.
4. **The Day's hero photos are its keepers.** A reader of a day lists the day's keeper lines standing, `memory` first, as the hero photos; with none, the day has no hero and the reader does not pick one.
5. **A keeper points, it does not copy.** The pixels stay where `photo/v1` left them; the keeper carries the photo line's id and ids, never a path to a file or a thumbnail.

## Example (synthetic)

```json
{"at":"2026-06-10T10:30:00Z","end":null,"tz":"Europe/Oslo","source":"keeper-inference","kind":"keeper","tier":1,
 "payload":{"schema":"keeper/v1","raw_id":"01a0f6a2-068b-7572-94ea-f492e749c3d6:memory",
 "photo":{"line":"01a0f6a2-068b-7572-94ea-f492e749c3d6","asset_id":"p-2026-06-10T10:30:00Z","library":"immich","file_name":"IMG_101030.HEIC"},
 "at":"2026-06-10T10:30:00Z","lane":"memory","source":"immich"}}
```

## Notes

- **Why a line and not a field on the photo.** The photo line is what the library said when the photo was imported; the mark is a later act, and the log is not rewritten. A keeper is to a photo what a resolution (RFC 0006) is to an address: a separate line that readers join by id.
- **Why two lanes and not a rating.** A rating is a reader's scale; the owner's acts in a library are a favourite and an album. Two lanes are what those acts mean. A later profile may add a lane; it will not add stars.
- **Why not `favourite/v1`.** The name says what the owner meant by the mark, not which button they pressed; a library with no favourites but a "Best of" album produces the same line.
