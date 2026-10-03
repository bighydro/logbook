# Apple Wallet: boarding passes and tickets

`logbook add wallet` reads the passes in Apple Wallet and writes one `flight/v1` line per air
boarding pass (RFC 0013, evidence `declared`) and one `event/v1` line per event ticket and per
train, boat or bus pass (RFC 0009). A coupon, a store card or a generic pass becomes an event only
when it carries a `relevantDate`; otherwise it is counted and skipped. One file of each pass is
read, `pass.json`; the barcode, the back of the pass, the images and the Passes app's database are
never read, so the booking reference and the passenger's name cannot reach a line.

```bash
logbook import-backup <backup> --only wallet     # the passes of an iPhone backup, copied out and read
logbook add wallet ~/copies/apple-wallet/         # a folder of passes: unpacked .pkpass folders, .pkpass zips, or both
logbook add wallet boarding.pkpass                # one pass, zipped as the airline sent it
logbook add ~/copies/apple-wallet/                # the same, sniffed by content
```

## Where the passes are

An iPhone keeps every pass in Wallet under `Library/Passes/Cards/<id>.pkpass/` in the home domain,
each as a folder holding the pass unpacked: `pass.json`, `manifest.json`, a signature and the
images (`icon.png`, `logo.png`, `strip.png`, …). Beside them the Passes app keeps its own database
(`nav.db`, `passes23.sqlite`): Wallet's cache of the same passes, the order of the cards, the
notifications it showed. `import-backup --only wallet` copies the `pass.json` files alone, below
`inbox/ios-backup-<udid>/apple-wallet/<id>.pkpass/`, with the folder names the phone gave them, and
runs the adapter on that folder. The database is not copied and not read: it holds nothing a pass
does not say.

A `.pkpass` an airline or a venue emailed is the same files as one zip. The adapter reads a zip, an
unpacked folder, a bare `pass.json`, or a folder of any of them, in name order. `pass.json` may be
UTF-8 (with or without a byte-order mark) or UTF-16 with one; a trailing comma is forgiven; a file
that will not parse is counted ("passes that would not parse").

## What is read, and what is never read

Read, from `pass.json` and nothing else:

| Key | Used for |
|---|---|
| `passTypeIdentifier`, `serialNumber` | `raw_id`, hashed together (below); also `calendar.id` on an event |
| `organizationName` | `extra.organization`; the title of a dated coupon or card; `calendar.name` on an event |
| `description` | the title of a ticket when nothing else names it |
| `relevantDate`, or the first of `relevantDates` | the date of a flight when no schedule is known; the start of a ticket or a transit pass; the moment of a dated coupon or card; kept as `extra.relevant_date` |
| `boardingPass`, `eventTicket`, `coupon`, `storeCard`, `generic` | the style, and under `boardingPass` its `transitType` |
| `headerFields`, `primaryFields`, `secondaryFields`, `auxiliaryFields` | each field's `key`, `label` and `value`, matched by role as the next section says |
| `semantics` | these tags only: `airlineCode`, `flightCode`, `flightNumber`, `departureAirportCode`, `destinationAirportCode`, `originalDepartureDate`, `originalArrivalDate`, `departureStationName`, `destinationStationName`, `eventName`, `venueName`, `eventStartDate` (or `eventStartDateInfo.date`), `eventEndDate` |

Deliberately never read:

| Key | Why |
|---|---|
| `barcode`, `barcodes` | an air pass's barcode is an IATA BCBP message carrying the passenger's name and the booking reference; a ticket's carries the ticket's secret. Nothing in it is needed: the pass's front says the same flight |
| `backFields` | terms, contacts, the booking reference, the frequent-flyer number |
| `nfc`, `authenticationToken`, `webServiceURL`, `userInfo`, `beacons` | credentials and Wallet's plumbing |
| `locations`, `expirationDate`, `voided` | where Wallet surfaces the pass and until when: not the plan |
| every other semantic tag | `passengerName`, `confirmationNumber`, `membershipProgramNumber`, `seats`, … |
| any front field whose key or label names a person or a credential | passenger, name, holder, member, guest, booking, order, ticket number, …: never a title, never anything |
| `manifest.json`, the signature, the images | never opened |
| `nav.db`, `passes23.sqlite` | the Passes app's database: not copied, not read |

No field is copied wholesale. A line carries only the values the mapping names; a key the mapping
does not know is simply not there. A test holds the adapter to this on passes whose fields, barcode
and semantic tags all carry the fictional passenger and booking reference.

## An air boarding pass is a flight

A `boardingPass` whose `transitType` is `PKTransitTypeAir` (the default when absent) is one
`flight/v1` line: kind `flight`, tier 1, source `apple-wallet`, evidence `declared`. A boarding
pass is the airline's word for a seat it sold, a plan; a tracker's export (`flighty`) is the record
of a flight that flew, and it wins when both are in the record (RFC 0013 rule 3). Before 0.6.0 the
adapter was `ios-wallet` and decoded the barcode as `tracked`; a record may still hold its lines.

Field keys differ per airline — one writes `origin` and `destination`, another `from` and `to`, a
third `f1` and `f2` with the labels `DEP` and `ARR` — so every value is found by its field's key
*or* label, split into words (`departureDate` → `departure date`) and matched case-insensitively:

| Field | Found by | Value |
|---|---|---|
| `from`, `to` | the semantic airport codes; else a field saying origin, from, dep, departure, outbound (the origin) and one saying destination, to, arr, arrival, inbound (the destination): of the three-letter upper-case tokens in the value (`OSL`, `Oslo (OSL)`, `NEW YORK JFK`), else in the label, the one the airports table knows, else the last; else the first two codes among the other plain fields | spelled through the airports table, `{iata, icao}` |
| `carrier`, `number` | the semantic `airlineCode` + `flightNumber` or `flightCode`; else a field saying flight: `XY 561`, `YZ0562`, `XY-561`, or a bare `561` with the carrier from a field saying airline, carrier or operator | the carrier through the airlines table; leading zeros dropped |
| `date` | the local date at the origin of the scheduled departure when the pass names one; else `relevantDate`'s own date; else a field saying date or day whose value carries a year (`2026-03-14`, `14.03.2026`, `14 Mar 2026`, `14MAR26`) | a pass with none is counted ("without a date"), never placed by a file time |
| `scheduled_departure`, `scheduled_arrival` | the semantic `originalDepartureDate` and `originalArrivalDate`; else a field saying departure or arrival whose value is a timestamp | RFC 3339 UTC |
| `extra.seat` | a field saying seat | as written |
| `extra.class` | a field saying class, cabin, compartment or fare | as written |
| `extra.organization` | `organizationName` | the airline's name |
| `extra.relevant_date` | `relevantDate` | as written, with its offset |

`relevantDate` is the instant Wallet shows the pass: boarding for one airline, departure for
another. It is kept as it is, and it is the line's `at` when the pass names no schedule, but it is
never written as a scheduled time. `at` and `end` follow RFC 0013: the scheduled departure and
arrival when known, else `relevantDate`, else the date's local midnight at the origin; `tz` is the
origin airport's zone, else the record's. A pass with no readable route or flight number is counted
("boarding passes without a readable flight").

A synthetic example, the Oslo persona's pass for XY 561:

```json
{"at":"2026-03-14T06:05:00Z","end":null,"tz":"Europe/Oslo","source":"apple-wallet","kind":"flight","tier":1,
 "payload":{"schema":"flight/v1","raw_id":"wallet:8c1d0e5a9b2f3a4b@3f9a1c2b7e4d","date":"2026-03-14","carrier":"XY","number":"561",
 "from":{"iata":"OSL","icao":"ENGM"},"to":{"iata":"ZRH","icao":"LSZH"},"role":"passenger","evidence":"declared",
 "observations":[{"evidence":"declared","source":"apple-wallet"}],
 "extra":{"organization":"Nordic Example Air","seat":"12A","class":"Economy","relevant_date":"2026-03-14T07:05:00+01:00"}}}
```

## A ticket is an event

An `eventTicket` is one `event/v1` line, tier 1: `title` from the semantic `eventName`, else a
field saying event, title or show, else the first primary field that names no person; `location`
from `venueName` or a field saying venue, location, where or place; `at` from `relevantDate`, else
`eventStartDate`, else a field saying start, doors, time or date — a day with no clock makes an
all-day line in the record's zone; `end` from `eventEndDate` or a field saying end. `calendar` is
`{id: the pass type, name: the issuer}`; `extra` holds `pass_style`, `organization` and
`relevant_date`. A ticket with no date is counted.

A `boardingPass` for a train (`PKTransitTypeTrain`), a boat, a bus or a generic transit is an event
titled `origin → destination`, from the semantic station names or the fields saying origin and
destination as text, with `extra.transit_type` (`train`, `boat`, `bus`, `generic`), `at` from
`relevantDate` or the departure field, `end` from the arrival field, and its seat and class under
`extra` as a flight keeps them.

A `coupon`, a `storeCard` or a `generic` pass is counted ("coupons", "store and loyalty cards",
"generic passes") unless it carries a `relevantDate`: then it is one event titled with the
issuer's name, `extra.pass_style` saying which kind it was. A loyalty card without a date says
nothing about any day; a coupon for one morning says where the owner meant to be.

## Re-imports and updates

`raw_id` is `wallet:<16 hex of sha256(passTypeIdentifier, serialNumber)>@<digest of the mapped
line>`. The pass type and serial identify a pass across every device it was on; the serial is
often the booking reference, so the pair is hashed and never carried. Importing the same Wallet
again appends nothing. A pass the airline updated — a delay pushed as a new `relevantDate`, a new
seat — has the same serial and a different mapped line, so it is a new observation of the same
flight: `flights.reconcile` folds it into the line that stands for the flight's key and supersedes
it (RFC 0013 rules 3 and 6), and a Flighty export of the flight later supersedes both, carrying the
seat along. A pass rescheduled to another day is, by the key, another flight.
