# RFC 0002 — payload profile `photo/v1`

Status: draft · 2026-09-14 · comment period: two weeks

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

## Provenance rule (reference)

`camera` when make/model and original capture time are present and the file is HEIC/RAW/JPEG from a known device or has a live-photo pair; `screenshot` when PNG at a device screen size with no camera data; `received` when there is no EXIF and the name follows messenger patterns (`IMG-2026…-WA0012`, `image0.jpg`); else `other`. Owners correct with one tap; corrections are `manual` lines.

## Example (synthetic)

```json
{"at":"2026-03-01T09:12:00Z","end":null,"tz":"Europe/Oslo","source":"immich","kind":"photo","tier":1,
 "payload":{"schema":"photo/v1","asset_id":"5d3e…","library":"immich","file_name":"IMG_0001.HEIC","media":"image",
  "lat":59.913,"lon":10.742,"camera":"SimPhone 3","width":4032,"height":3024,"live_photo":true,"provenance":"camera","faces":2,"people":["p_17","p_42"]}}
```
