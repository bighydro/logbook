# RFC 0001 — payload profile `location/v1`

Status: draft · 2026-09-14 · comment period: two weeks

One observed position of the owner at one instant. Produced by phone trackers (Dawarich, OwnTracks, Overland), Google Timeline exports, GPX tracks, camera EXIF.

## Line

`kind` MUST be `location`. `tier` SHOULD be 1. `at` is the fix time; `end` is null.

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"location/v1"` | MUST | |
| `lat`, `lon` | number | MUST | WGS-84 degrees |
| `accuracy_m` | number | SHOULD | horizontal accuracy radius in metres |
| `alt_m` | number | MAY | altitude in metres |
| `speed_mps` | number | MAY | metres per second |
| `heading_deg` | number | MAY | 0–360 |
| `provider` | string | MAY | `gps`, `wifi`, `cell`, `fused`, `manual` |
| `tracker` | string | MAY | the app or device that produced the fix, e.g. `dawarich`, `garmin`, `iphone` |
| `raw_id` | string | MAY | the source's own id for the point |

Anything else the source reports MAY be kept under `extra`.

## Example (synthetic)

```json
{"at":"2026-03-01T07:30:00Z","end":null,"tz":"Europe/Oslo","source":"dawarich","kind":"location","tier":1,
 "payload":{"schema":"location/v1","lat":59.911,"lon":10.750,"accuracy_m":12,"provider":"fused","tracker":"iphone","raw_id":"184223"}}
```

## Notes

A *visit* or *stay* (a span at one place) is not a location line; it is derived by an engine pass, or, when a source supplies visits itself, recorded as a separate profile (`visit/v1`, to be proposed). Keep raw points raw.
