# Passages: a deck log as declared sea legs

A ship's deck log, kept by hand and transcribed to a CSV, becomes the vessel's own movement in the
record: one `trip/v1` line per leg (RFC 0020, mode `passage`), with the vessel as `subject`
(ADR 0018) and `evidence` `declared`, and a `location/v1` line for the vessel at each end that can
be positioned. Nothing is guessed: the log's words stay the log's words, and a position comes only
from a route the bridge planned, a place the captain named, or a published port position.

```bash
logbook assets add nordlys --kind yacht --name Nordlys --mmsi 970123456     # once
logbook add passages deck-log.csv --asset nordlys --routes ~/ECDIS/routes --dry-run
logbook add passages deck-log.csv --asset nordlys --routes ~/ECDIS/routes
```

## The CSV

| Column | What it holds |
|---|---|
| `dep_local` | when she left: `2026-06-14 08:30` (a `T`, seconds or an offset are fine), or a bare date `2026-06-14` when the clock was not noted |
| `dep_place` | where she left, in the log's words: `Cannes`, `Genoa Molo Vecchio` |
| `arr_local` | when she arrived, the same forms; empty when not noted |
| `arr_place` | where she arrived; empty when the leg is still open |
| `tz` | the IANA zone the clocks are in; empty means the record's zone |
| `note` | the keeper's remark, kept under `extra.note` |
| `check` | anything the transcriber wants a second look at; the row is imported and carries it under `extra.check` |

A row without a departure time or place is skipped and counted. A bare date is the start of that
local day for a departure and its end for an arrival, and the leg says so under `extra.approximate`.

## Positions, in this order

1. **A route file.** `--routes DIR` names a folder of RTZ 1.0 files (the IEC 61174 route exchange
   format Maris MDS and other ECDIS export). A route matches a leg when its name names both places:
   `CANNES TO GENOA` is Cannes → Genoa Molo Vecchio, and Genoa → Cannes with the waypoints reversed.
   Names compare by the words they share, case, accents and punctuation aside, after the words that
   name the kind of place (`port`, `marina`, `cala`, `saint`, …) are set aside. A name with two ends
   (`A TO B`, `A - B`, `A / B`) must name the departure in one and the arrival in the other; a name
   without a separator must name both, the first named being the departure. The leg then takes the
   first and last waypoint as its ends, the whole route as `geometry` (a GeoJSON LineString) and the
   route's great-circle length as `distance_m`.
2. **`places.json`.** A place of the record whose name the log's name contains (`Genoa Molo Vecchio`
   contains `Genoa`); its radius is the position's accuracy.
3. **The bundled gazetteer.** `logbook/tables/ports.csv`: about 250 ports and anchorages of the
   Mediterranean, the US East Coast and the Bahamas, each with aliases (`Genova`, `St Tropez`), a
   published position to about a kilometre, and the country. Nothing in it is invented; a place it
   positions reads `gazetteer` under `extra.positions`.
4. **Nothing.** The place keeps its name and no coordinates, and the run prints `places unresolved:
   Cala Nordlys`. Name it in `places.json` and add the log again: the leg is already in the record
   (same `raw_id`), so the fix is a retraction and a re-import, or simply a better position next time.

## What is written

The leg, for the Nordlys fixture (synthetic; the yacht and her MMSI do not exist):

```json
{"at":"2026-06-14T06:30:00Z","end":"2026-06-14T15:10:00Z","tz":"Europe/Paris","source":"passages","kind":"trip","tier":1,
 "payload":{"schema":"trip/v1","raw_id":"passages:nordlys:2026-06-14T08:30:cannes","mode":"passage","provider":"deck-log",
 "subject":"nordlys","evidence":"declared","name":"Cannes → Genoa Molo Vecchio",
 "from":{"name":"Cannes","latitude":43.548,"longitude":7.015},"to":{"name":"Genoa Molo Vecchio","latitude":44.4075,"longitude":8.926},
 "geometry":{"type":"LineString","coordinates":[[7.015,43.548],[7.13,43.53],[8.05,43.83],[8.926,44.4075]]},"distance_m":185578,
 "extra":{"positions":{"from":"route","to":"route"},"route":{"name":"CANNES TO GENOA","file":"CANNES TO GENOA.rtz"}}}}
```

and her position at each positioned end with a time, `raw_id` the leg's with `:dep` or `:arr`:

```json
{"at":"2026-06-14T06:30:00Z","end":null,"tz":"Europe/Paris","source":"passages","kind":"location","tier":1,
 "payload":{"schema":"location/v1","lat":43.548,"lon":7.015,"accuracy_m":100.0,"provider":"manual","tracker":"deck-log",
 "raw_id":"passages:nordlys:2026-06-14T08:30:cannes:dep","subject":"nordlys",
 "extra":{"evidence":"declared","place":"Cannes","leg":"passages:nordlys:2026-06-14T08:30:cannes","position":"route"}}}
```

An open leg (no arrival) has `end` null, no `to`, `extra.open` true and a departure line only. The
dedupe key is the asset, the departure time and the departure place: the same row again appends
nothing, whatever else changed on it.

The run reports the legs, how many a route positioned, how many are open, and the names it could
not position:

```
added 16 lines from passages
  6 legs: 2 matched to a route, 1 open (no arrival yet)
  places unresolved: Cala Nordlys
```

`--dry-run` prints `passages: N lines would be added, M already in the record (dry run, nothing written)` and writes nothing.

## What the readers make of it

The position lines are the vessel's own track, so every reader that derives an asset's movement
sees the declared legs the way it sees AIS fixes: `assets status` names the last declared position;
`derive stays`, `day`, `days` and `trips` cluster an arrival and the next departure into a stay at
the port and the span between two stays into a move by boat, with its distance. Two things are
beyond the engine's grammar today and wait for the stay-aboard container (the open pull request
that makes a run aboard one stay): a leg whose departure place the log does not also arrive at
earlier — the first row, a row after an unpositioned arrival, the open leg — leaves one fix at its
departure, and a single fix is too short to be a stop, so the engine shows that leg's arrival stay
with no move before it; and the route `geometry` is kept on the leg and not yet drawn by any reader.
Whether the owner was aboard is still derived from the owner's own track (ADR 0018 rule 3), never
from the log.
