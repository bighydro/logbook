# RFC 0026 — payload profile `weather/v1`

Status: frozen for v1.0 · 2026-10-05 (RFC 0031; fixture `conformance/profiles/`) · drafted 2026-10-02 · comment period: two weeks

One statement of the weather of one local day at one place the owner spent it: the lowest and highest temperature, the precipitation, the strongest wind, the WMO weather code, sunrise and sunset. The place is where the owner's own track says they were — the overnight stay, or a stay of three hours or more — rounded to a tenth of a degree, about 10 km, before anyone is asked about it. The values are a weather provider's, not an observation of the owner's: `evidence` is `external`, and a reader shows them as the day's weather, never as a presence or an act. A day the owner spent in two such places has two lines.

## Line

`kind` MUST be `weather`. `tier` SHOULD be 1 (SPEC §4: public data about a 10 km square on a day). `at` is the local day's start — midnight in `tz` — as RFC3339 UTC; `end` is the next day's start, so the line spans the day. `source` is the producer: `weather` for the reference adapter, which reads Open-Meteo (`logbook sync weather`, `docs/adapters/weather.md`); another producer uses its own name.

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"weather/v1"` | MUST | |
| `raw_id` | string | MUST | `<day>@<lat>,<lon>`, the coordinates with one decimal (`2026-06-16@47.4,8.5`); the dedupe key, so a day and place asked twice is one line |
| `day` | `YYYY-MM-DD` | MUST | the local day, in `tz` |
| `lat` | number | MUST | the place, to one decimal (rule 1), −90 to 90 |
| `lon` | number | MUST | the place, to one decimal (rule 1), −180 to 180 |
| `t_min_c` | number or null | MUST | the day's lowest air temperature, °C |
| `t_max_c` | number or null | MUST | the day's highest air temperature, °C |
| `precipitation_mm` | number or null | MUST | the day's precipitation, mm (rain, and snow as water) |
| `wind_max_kmh` | number or null | MUST | the day's strongest wind, km/h |
| `weather_code` | integer or null | MUST | the day's weather as a WMO code (table 4677: 0 clear, 3 overcast, 61 rain, 71 snow, 95 thunderstorm, …) |
| `sunrise` | RFC3339 UTC or null | MUST | |
| `sunset` | RFC3339 UTC or null | MUST | |
| `evidence` | `"external"` | MUST | the values are a provider's (rule 3) |
| `provider` | string | MUST | who was asked: `open-meteo` for the reference adapter |
| `dataset` | string | MAY | the provider's dataset: `archive` (a reanalysis, days ago and older) or `forecast` (the recent days the archive does not have yet) |
| `supersedes` | string | MAY | the id of an earlier weather line for the same day and place this one replaces |

## Rules

1. **One decimal leaves the machine.** A producer MUST round every coordinate to one decimal place before it asks anyone anything, MUST put only the rounded coordinates in a request, and MUST write only the rounded coordinates in the line. A tenth of a degree is about 11 km of latitude and, at Oslo, 6 km of longitude: a valley, not a street. A payload whose `lat` or `lon` carries more precision is not this profile. A coordinate that rounds to zero is written `0.0`, never `-0.0`.
2. **A line is where the owner was.** The places of a day are the owner's overnight stay (the night of the day, as the stays reader derives it: the stay with the longest overlap of the night window) and every stay of three hours or more that overlaps the day — a stay aboard an asset by its anchorages as well as by its centre. One line per `(day, lat, lon)` after rounding: a home and an office 600 m apart are one place. A day with no such stay has no line: nothing is asked about a day the track does not place.
3. **The evidence is external.** The values are what a provider says about a 10 km square on a day. A reader shows them as weather and never derives presence, company or an act from them; nothing in a weather line promotes a stay, places the owner or counts as evidence of anything but the weather. A derived row that uses them inherits tier 1 (SPEC §4).
4. **Null is unknown.** A value the provider does not have is `null`, never `0`. A day the provider has no values at all for gets no line, and a producer asks about it again another time.
5. **Only an explicit command asks.** A producer runs when the owner names it (`logbook sync weather`) or lists it in the configuration of the run that takes every configured source (`sync --all`); nothing a reader does — `day`, `days`, `year`, `trips`, `serve`, `mcp` — fetches anything. The request carries no identifier of the owner: no key, no account, no referrer; the user agent names the software.
6. **The cache is inbox, not record.** A producer MAY keep the provider's answers under `<root>/inbox/weather/`, keyed by the rounded place and the day, so a re-run never asks twice; the cache holds the same rounded coordinates and nothing finer, and it is disposable (SPEC §1: `inbox/` is not part of conformance).
7. **Corrections are new lines.** A better value for a day and place is a new line with `supersedes` (SPEC §3); the earlier line stands in the chain. A `raw_id` already in the record is never written again by a producer.

## Example (synthetic)

```json
{"at":"2026-06-15T22:00:00Z","end":"2026-06-16T22:00:00Z","tz":"Europe/Oslo","source":"weather","kind":"weather","tier":1,
 "payload":{"schema":"weather/v1","raw_id":"2026-06-16@47.4,8.5","day":"2026-06-16","lat":47.4,"lon":8.5,
 "t_min_c":14.1,"t_max_c":26.8,"precipitation_mm":0.3,"wind_max_kmh":18.7,"weather_code":2,
 "sunrise":"2026-06-16T03:30:00Z","sunset":"2026-06-16T19:25:00Z",
 "evidence":"external","provider":"open-meteo","dataset":"archive"}}
```

## Notes

- **Why daily and not hourly.** The question a Day answers is "what was it like that day"; the hourly series would be 24 lines a day of a provider's numbers, and the record is the owner's, not the provider's. A later profile may add an hourly form for a stay; it will be a separate kind.
- **Why the place is rounded in the payload too.** The line is what a reader joins on. If the line carried the stay's centre, a reader could rebuild the exact track from the weather lines alone, and the rounding before the request would have protected nothing. The stays are in the location lines, where they belong; the weather line names the square.
- **Why the record's zone.** A day is a local day of the owner (SPEC §3.2), so a line's `day` is in `tz` even for a place in another zone: the day the owner lived, not the day the place had. The provider is asked in that zone, so its daily values cover the same hours.
- **Why one decimal and not a grid.** A tenth of a degree is the coarsest rounding that still tells a valley from the next; a provider's own grid is finer than that, so the rounding, not the provider, is the boundary.
- **Why not a field on the stay.** The stay is derived and disposable (ADR 0013); the weather is a fetched fact a recompute cannot reproduce without the network. It is a line of its own, joined by day and place.
