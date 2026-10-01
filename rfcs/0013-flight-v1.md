# RFC 0013 — payload profile `flight/v1`

Status: draft · 2026-09-30 · comment period: two weeks

One flight the owner was on: a carrier and a number, from one airport to another on one date, with the times that were planned and the times that happened, the aircraft when known, and whether the owner sat in the cabin or at the controls. The same flight reaches the record from up to four places — a flight tracker's export, a boarding pass in the owner's Wallet, the record's own calendar and location lines, the owner's word — and the profile says how they meet.

## Line

`kind` MUST be `flight`. `tier` SHOULD be 1 (SPEC §4: like a calendar entry or a location point, a flight is the owner's own movement). `at` is the actual departure when known, else the scheduled one; `end` the actual arrival when known, else the scheduled one, else null. `tz` is the origin airport's IANA zone when the airports table knows it (SPEC §2: the owner's zone at `at`), else the record's. `source` is the producer: `flighty`, `flight-inference`, `manual`, ….

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"flight/v1"` | MUST | |
| `raw_id` | string | MUST | the producer's own stable id for this observation (rule 6). The `(source, raw_id)` dedupe key: re-running a producer on unchanged input appends nothing |
| `date` | `YYYY-MM-DD` | MUST | the local date of the scheduled departure at the origin (the actual one when nothing was scheduled). Part of the flight key (rule 1) |
| `carrier` | string | MUST* | the airline's IATA designator (`LX`) when the airlines table knows the airline, else the code as the source spelled it, upper-case. Part of the flight key. *An `inferred` line for a leg the record has no number for (rule 1) carries neither `carrier` nor `number`; a `tracked` or `declared` line always has both |
| `carrier_icao` | string | MAY | the ICAO designator (`SWR`) when known |
| `number` | string | MUST* | the flight number without the carrier, leading zeros dropped (`561`, `561A`). Part of the flight key; see `carrier` |
| `from`, `to` | object | MUST | `{ iata?, icao? }`, upper-case; at least one code present. The route as the source gave it; a diversion is `diverted_to` (same shape, MAY) |
| `scheduled_departure`, `scheduled_arrival` | RFC3339 UTC | MAY | gate times as planned |
| `actual_departure`, `actual_arrival` | RFC3339 UTC | MAY | gate times as they happened |
| `scheduled_takeoff`, `actual_takeoff`, `scheduled_landing`, `actual_landing` | RFC3339 UTC | MAY | wheels-off and wheels-on, for sources that keep them |
| `aircraft` | object | MAY | `{ type?, registration? }`, as the source spells them (`A320`, `Airbus A320`, `ZZ-ABC`) |
| `role` | string | MUST | `passenger` or `pilot` |
| `cancelled` | boolean | MAY | true for a flight that did not operate; the plan existed (RFC 0009 rule 3) |
| `evidence` | string | MUST | `tracked`, `inferred` or `declared`: the strongest evidence any observation folded into this line has (rule 3) |
| `observations` | array | MUST | one `{ evidence, source, line? }` per producer observation this line folds in, oldest first; `line` is the id of the earlier line that carried it, absent for this line's own (rule 4) |
| `supersedes` | string | MAY | id of the line this one replaces (rule 4) |

Anything else the source reports MAY be kept under `extra` (a seat, a cabin, a gate, a terminal, the calendar entry and the location points an inference rests on). A booking reference (PNR) is a credential to the booking, not an observation of the day, and MUST NOT be kept anywhere in the line; the owner's own notes about a flight belong in a `note/v1` line, not here.

## Producers

Three producers write this profile. Each is one mapping (ADR 0017), and each names its evidence:

| `evidence` | `source` | What it is |
|---|---|---|
| `tracked` | `flighty` | a flight tracker's export: `logbook add flights <export.csv>` reads Flighty's CSV (`Date, Airline, Flight, From, To, … Gate Departure (Scheduled), Gate Departure (Actual), Take off …, Landing …, Gate Arrival …, Aircraft Type Name, Tail Number, …`). Times in the export are wall-clock at the airport with no offset; the adapter converts them with the airports table's zone (departure fields at `from`, arrival fields at `to`, or at `diverted_to`). A column the export lacks leaves its field absent, never a guess. The same adapter reads Flighty's own store from an iPhone backup (`logbook import-backup`, source `flighty`) through the same mapping, with the same `raw_id`: a flight in both is one observation |
| `tracked` | `ios-wallet` | an air boarding pass in Apple Wallet, read from an iPhone backup (`logbook import-backup`, source `ios-wallet`) or a `.pkpass`: the airline's IATA BCBP barcode gives carrier, number, route, seat and the day of the year, one line per leg; the year comes from `relevantDate`, `expirationDate` or a dated field, never from a guess, so a pass that names none is skipped and counted. Only the pass's semantic tags name a schedule; `relevantDate` (boarding or departure, the airline decides) is kept under `extra.relevant_date` and is the line's `at` when no schedule is known. The PNR, the passenger's name and the barcode are never kept |
| `inferred` | `flight-inference` | the record's own evidence: `logbook infer flights` finds a calendar entry (`event/v1`) whose title names a flight (`LX 561`, `Flight to Zurich (LX 561)`), then a leg in the record's location points around it: the last point near one airport, then the first point near a different one, every point between them (a tracker that keeps logging on the climb, or through the whole flight) near no airport. The leg's two points are the actual departure and arrival; the entry's span is the scheduled one; the airports are the leg's. The two airports are at least 150 km apart; closer, the leg was a drive and is no flight. A leg that a `tracked` flight on the same route already covers (the leg lies within four hours before its departure and eight after its arrival) under another key — a red-eye landing after local midnight, a stale point at the origin — is that flight seen again and produces nothing. The leg carries the entry's designator unless a `tracked` or `declared` flight in the window already holds that designator on another route: then the entry named that flight and this leg is some other one, written with no `carrier` and no `number` — an inferred line never carries a number that did not come from the entry for its own leg, or from a tracked or declared line it merges into. An entry with no such leg is a plan, not a flight, and produces nothing |
| `declared` | `manual` | the owner's word: `logbook add flight "LX 561 NCE ZRH 2026-09-27 pilot"` — designator, origin, destination, date, then optionally the role (default `passenger`), a departure and arrival clock (`07:05-08:20`, local at each airport, recorded as actual), an aircraft type and a registration |

## Rules

1. **One flight, one key.** A flight is identified by `(date, carrier, number)`. Two lines with the same key are the same flight seen twice, whatever their producers; the key never includes the airports, because a diverted or re-routed flight is still that flight. Two lines with different keys are also one flight when they are on the same date and route and their departures are within 30 minutes of each other (scheduled against scheduled when both have one, else actual against actual): a codeshare, the operating carrier's number and a marketing carrier's for one aircraft leaving once. The merged line keeps the operating carrier's designator when a producer marked it (`extra.operating` true on its line), else the designator first seen; the other designator stays on the line it folded in, reachable from `observations`. A reader folds a pair the record holds unmerged the same way. An `inferred` leg the record has no number for (producers, below) has no designator; its key is `(date, "", "<from>><to>")` and it merges by the codeshare rule into a numbered line on its route.
2. **Every observation is a line.** A producer that sees a flight writes a line; nothing is dropped because another producer saw it first (SPEC §3: nothing is rewritten). Only an exact re-run — the same producer, the same input — appends nothing, by `(source, raw_id)`.
3. **The strongest evidence wins, field by field.** When a flight with the same key already stands in the record, the new line supersedes it and carries the merge: `tracked` over `inferred` over `declared`, and between equals the newer observation; for each field the winner's value when it has one, else the next observation's. `role` is the exception: a `declared` observation decides it whenever there is one, because only the owner knows whether they flew the aircraft. `evidence` is the strongest across every observation folded in. `at`, `end` and `tz` are recomputed from the merged fields.
4. **Observations attach, they do not vanish.** The merged line lists every observation in `observations`, the earlier lines by id, and `supersedes` the line it replaces; those lines stay in the record with what they saw. A reader shows the last line standing for a key (the one no other flight line supersedes), as with any `supersedes` chain (SPEC §3), and can walk back to what each producer contributed.
5. **Airports are looked up, never resolved.** `from` and `to` are codes as the source gave them. The airports table (`logbook/tables/airports.csv`: OurAirports' large airports with scheduled service, public domain; IATA, ICAO, name, latitude, longitude, IANA zone) turns a code into a zone and a place, and a place into the nearest airport; a file named by `--airports` or `LOGBOOK_AIRPORTS` (same columns) adds to it or overrides it, for a private field or a strip the table does not have. A code no table knows is kept as given, with no zone: its times cannot be converted and are kept as text under `extra`.
6. **`raw_id` is the observation's, not the flight's.** `flighty`: the export's own flight id, else the key, suffixed with a digest of the mapped row, so an export that later carries the actual times is a new observation of the same flight (rule 3), not a duplicate. `flight-inference`: the key suffixed with the leg's two points, so more location points that move an end make a new observation. `manual`: the key suffixed with a digest of what was declared.
7. **A tracker's times are the tracker's.** The adapter converts a wall-clock time to UTC with the airport's zone and does not "correct" it; a departure that lands before it left (a clock the tracker got wrong, a zone the table got wrong) is kept as given and counted.

## Example (synthetic)

A flight the owner declared, then Flighty tracked. The second line supersedes the first, keeps the declared role, and takes everything else from the tracker:

```json
{"at":"2026-09-27T05:12:00Z","end":"2026-09-27T06:21:00Z","tz":"Europe/Oslo","source":"manual","kind":"flight","tier":1,
 "payload":{"schema":"flight/v1","raw_id":"2026-09-27:XY:561@3f9a1c2b7e4d","date":"2026-09-27","carrier":"XY","number":"561",
 "from":{"iata":"OSL"},"to":{"iata":"ZRH"},"actual_departure":"2026-09-27T05:12:00Z","actual_arrival":"2026-09-27T06:21:00Z",
 "role":"pilot","evidence":"declared","observations":[{"evidence":"declared","source":"manual"}]}}

{"at":"2026-09-27T05:10:00Z","end":"2026-09-27T06:24:00Z","tz":"Europe/Oslo","source":"flighty","kind":"flight","tier":1,
 "payload":{"schema":"flight/v1","raw_id":"fx-0001@8c1d0e5a9b2f","date":"2026-09-27","carrier":"XY","number":"561",
 "from":{"iata":"OSL","icao":"ENGM"},"to":{"iata":"ZRH","icao":"LSZH"},
 "scheduled_departure":"2026-09-27T05:05:00Z","actual_departure":"2026-09-27T05:10:00Z",
 "scheduled_arrival":"2026-09-27T06:20:00Z","actual_arrival":"2026-09-27T06:24:00Z",
 "aircraft":{"type":"Airbus A320","registration":"LN-XYA"},"role":"pilot","evidence":"tracked",
 "observations":[{"evidence":"declared","source":"manual","line":"019a1b2c-0000-7000-8000-000000000001"},{"evidence":"tracked","source":"flighty"}],
 "supersedes":"019a1b2c-0000-7000-8000-000000000001","extra":{"seat":"1A","cabin":"economy"}}}
```

## Notes

- **Why merge instead of skip.** "The tracked one wins" could mean "drop the others". It does not: a declared line carries the role the tracker cannot know, an inferred line carries the two location points that place the owner at the gate, and a record that dropped them would have less evidence than it collected. The winner decides the fields; the others stay attached, and stay in the record.
- **Why the key has no airports.** A calendar entry says `LX 561`; the location points say where. If the key included the route, a diversion would be a second flight. The date is the origin's local date of the scheduled departure, which is how airlines, trackers and calendars all name a flight; a red-eye that lands the next day keeps the date it left on.
- **Why not resolve the airline.** `carrier` is spelled one way — the IATA designator — so that Flighty's `SWR` and a calendar's `LX 561` meet on one key. That is a spelling rule over a small table (`logbook/tables/airlines.csv`), not a resolution (RFC 0006): no entity is minted and no line names a company.
- **Inference is a producer, not an engine.** `logbook infer flights` writes lines with its own `source` and never touches notes, confirmations or visibility (ADR 0013 rule 6). A later pass with better rules writes new observations; the old ones remain what they were.
- **What a flight is not.** A flight is not a `location/v1` point (it has a span and two ends), not an `event/v1` (a plan, which the inference reads but never rewrites), and not a trip (an engine's derivation over several flights).
