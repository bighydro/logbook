# RFC 0001 — payload profile `location/v1`

Status: draft · 2026-09-14 · comment period: two weeks · amended 2026-09-30 (`subject`, ADR 0018)

One observed position of one subject at one instant. The subject is the owner unless the line says otherwise: a position of something the owner keeps track of — a boat, an aircraft, a car (ADR 0018) — is the same profile with `subject` set. Produced by phone trackers (Dawarich, OwnTracks, Overland), Google Timeline exports, GPX tracks, camera EXIF; for an asset, by AIS and ADS-B receivers.

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
| `subject` | string | MAY | whose position this is: the id of an asset in the record's `assets.json` (ADR 0018). Absent means the owner |

Anything else the source reports MAY be kept under `extra`.

## Example (synthetic)

The owner's own position:

```json
{"at":"2026-03-01T07:30:00Z","end":null,"tz":"Europe/Oslo","source":"dawarich","kind":"location","tier":1,
 "payload":{"schema":"location/v1","lat":59.911,"lon":10.750,"accuracy_m":12,"provider":"fused","tracker":"iphone","raw_id":"184223"}}
```

The owner's boat, reported over AIS (the MMSI is synthetic; MID 999 is allocated to no country):

```json
{"at":"2026-03-01T07:30:00Z","end":null,"tz":"Europe/Oslo","source":"ais","kind":"location","tier":1,
 "payload":{"schema":"location/v1","lat":59.905,"lon":10.735,"speed_mps":2.6,"heading_deg":184,"tracker":"aisstream",
 "raw_id":"aisstream:999000001:1772350200","subject":"solvind","extra":{"mmsi":"999000001","message_type":"StandardClassBPositionReport"}}}
```

## Rules

1. `subject` absent means the owner. A writer MUST NOT write the owner as a `subject`; there is no id for the owner, and every line of the record is already theirs.
2. A `subject` is an asset id, a token matching `^[a-z0-9][a-z0-9-]*$`, as `assets.json` spells it. A reader that does not know the id keeps the line and shows it as a position of that id; the registry is a setting of the record, not part of the chain, so an id the registry no longer names is still a valid line.
3. An asset's positions are its own track. A reader MUST NOT merge them into the owner's track, collapse them into a run with the owner's points (SPEC §3.2: a run is one source *and one subject*), or take one for the other. Whether the owner was aboard is derived downstream by comparing the two tracks (ADR 0018); it is never written on a location line.
4. The amendment of 2026-09-30 is backward compatible: a line written before it has no `subject` and means what it always meant; a reader from before it ignores the field, as SPEC §5 requires of any payload field it does not know.

## Notes

A *visit* or *stay* (a span at one place) is not a location line; it is derived by an engine pass, or, when a source supplies visits itself, recorded as a separate profile (`visit/v1`, to be proposed). Keep raw points raw.
