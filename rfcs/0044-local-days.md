# RFC 0044 — Local days: a day is the local calendar day where it began

Status: draft · 2026-10-21 · comment period: two weeks · builds nothing: no code, no line, no SPEC text
and no conformance vector changes with this RFC (§10 says why, and what the code needs) · builds on RFC
0036 (`day_start`), RFC 0034 (the signed day), RFC 0013 (flights and the airports table) and SPEC §3.2 ·
builds RFC 0043 §12, its first bullet, and §14 item 8 · proposes to amend SPEC §3.2 (at document version
0.5, with an ADR, §6) and RFC 0034 (`extra.tz`, `extra.span`, `extra.zones` and `extra.day_start`,
§2.6) · its nine questions decided by the owner on 21 October 2026 (§12)

On `main` every reader puts every line on a day by one clock: the record's zone, `timezone` in
`logbook.json`, under its `day_start` (SPEC §3.2, `logbook/core/day_start.py`). The owner who lives in
Oslo and flies to New York for a week reads that week on Oslo's clock: dinner at 19:00 in Manhattan is
on the next day's page, at 01:00. This RFC proposes the rule the owner lives by instead: **a day is the
local calendar day where the owner was when it began**. A flight west makes a long day, a flight east a
short one, the Day's ribbon marks where the clock changed, and a day the owner has signed keeps the zone
and the span it was signed in and is never re-bucketed later.

It is a reader's rule, behind a setting of `logbook.json`, `"local_days": true`, off by default. No line
is written or rewritten for it, the envelope and the hash are untouched, and a record that never sets it
reads exactly as today. A record with one zone and no travel reads exactly as today even with it set
(§9, with the proof).

## 1. Words

- The **record's zone** is `timezone` in `logbook.json`, as SPEC §3.2 defines it.
- The **owner's zone** at an instant is the IANA zone the owner's clock was on then, as the record's
  evidence says (§2.1); with no evidence, the record's zone.
- A **zone change** is an instant at which the owner's zone becomes another zone. A change is a **change
  of clock** when the two zones' UTC offsets differ at that instant; Oslo to Zurich is a zone change and
  no change of clock.
- The **naive day** of an instant is `day_start.local_day(instant, zone, start)` on `main`: its calendar
  date on the wall clock of `zone`, the date before when that clock reads earlier than `day_start`.
- The **rule day** of an instant is its day under this RFC (§2.2) before signed days are applied.
- A day's **span** is the half-open interval of instants from where it begins to where the next day
  begins (§2.3).
- A signature is **old-style** when its `signed-day/v1` payload has no `extra.span` (every signature on
  `main` today), **new-style** when it has one (§2.6).

## 2. The rule

### 2.1 The owner's zone at an instant

The owner's zone is a step function of time, built from **assertions**: an instant, a zone, and the kind
of evidence. Four kinds of evidence assert a zone, ranked:

1. **The owner's word.** A `note/v1` line standing whose `labels` (RFC 0010, a MAY field) hold `zone`
   and whose `text` begins with an IANA zone name asserts that zone at the note's `at` (a note's `end` is
   null, RFC 0010). It is the highest rank, so it shadows every lower assertion for the 12 hours after it
   (below), and it holds, like any assertion, until a later one: the next flight or still run moves the
   clock on, so a note written to correct one evening does not pin the owner's clock for life. It is the
   correction for everything below: a wrong camera clock, a ferry, a border town. The owner writes it
   through the command line (§12 q4), which appends it through `Logbook.append` under the writer lock;
   no writer sets the label today (`logbook add` writes `schema` and `text`).
2. **A flight's arrival.** Each flight of the standing set (SPEC §3.2.4) asserts the zone of its `to`
   airport in the airports table (RFC 0013 rule 5; every one of the 1,150 rows of
   `logbook/tables/airports.csv` carries an IANA zone) at its arrival: `actual_arrival`, else
   `scheduled_arrival`, else the line's `end`; a flight with none of them, or whose `to` the table does
   not know, asserts nothing. Between departure and arrival the owner is on the departure's clock: the
   clock changes on landing, as a phone's does.
3. **Where the owner is.** The owner's `location/v1` points (subject absent), in time order, each placed
   in a zone: the place's `tz` when a place of `places.json` holds the point and carries one (a new
   optional key beside `country`, §12 q5), else the zone of the nearest airport within 300 km (the
   distance of the country rule, SPEC §3.2.7 rule 6), else no zone. A **still run**, consecutive points
   in one zone that all lie within `radius_m` (150 m) of its first point and that last `stay_min_s`
   (1,200 s) or longer, asserts that zone at its first point: a stay in shape, found on the points alone.
   Points on the move assert nothing, so a car past a border, a boat in mid-sea where the nearest airport
   changes, or one bad fix, never changes the clock. This is the "zone of the place a stay is at" of RFC
   0043 §12, taken from the points rather than the derived stays, because stays are derived from windows
   cut by day (SPEC §3.2.2), and a day that depended on a stay would depend on itself (§5).
4. **A line's own `tz`, where it is the device's.** SPEC §2 says `tz` is "the owner's timezone at `at`",
   but the reference writer fills it with the record's zone whenever an adapter gives none
   (`Logbook._line`), and most adapters give none; a flight carries its origin's zone and a calendar
   entry its organiser's. So `tz` asserts a zone only on `photo/v1` lines whose `tz` differs from the
   record's zone (a camera that stamps its own zone; on `main` the `apple-photos` adapter, which writes
   `ZTIMEZONENAME`, is the one that does), and only when **two photos at least two hours apart, within
   24 hours, name the same zone**: the assertion is at the first. One photo asserts nothing, so a picture
   Per Hansen sent from New York and Ines saved does not move her days. Every other line's `tz` asserts
   nothing. This is the weakest witness; it stays, with the two-photo rule (§12 q3).

With no assertion at or before an instant, the owner's zone is the record's zone.

**Which assertion holds.** The owner's zone at an instant is that of the latest assertion at or before
it, except that an assertion is ignored when it comes within 12 hours after an
assertion of a higher rank (a smaller number) in another zone: a camera still on Oslo's clock the
evening a flight landed in New York does not move the day back. Only what comes after is shadowed, so a
ferry's arrival seen in the points is never undone by a flight that leaves the next morning. Assertions
at the same instant are taken in rank order. A note, a photo or a place naming a zone this reader does
not know asserts nothing, and every reader that groups by day names the line in its output (SPEC §2: a
reader that does not know a zone says so; it does not localise in it, and it does not refuse every day
of the record for one typo). The record's own `timezone` unknown is refused, as on `main`.

The timeline is the list of zone changes this leaves, each with its instant, its zone, its evidence kind
and the id of the line that asserted it. It is what the ribbon draws (RFC 0043 §4.2) and what a Day's
JSON carries (§4).

### 2.2 The day of an instant

The rule day of an instant `t` is the latest naive day the owner's clock has shown up to `t`:

    rule_day(t) = max { naive_day(t′, Z(t′), day_start) : t′ ≤ t }

where `Z(t′)` is the owner's zone at `t′`. In words: on one clock, the day of an instant is what that
clock says, as on `main`; and **a day once begun is never left for an earlier date** when the clock
goes back. A flight west that lands at 23:00 on the 20th in New York, having left Oslo after midnight on
the 21st, lands on the 21st, not back on the 20th. The maximum looks back a bounded time: no clock is
more than 26 hours behind another, so nothing older than three days can raise it. A reader computes it,
and every reader reads its evidence, from `first − 4` on (§5), with the zone in force at that start.

A zone change between two zones on the same clock (Oslo and Zurich, Oslo and Copenhagen, Kristiansand
and Gothenburg) moves nothing, since the naive day depends on the zone only through the offset. On one
clock the maximum differs from `main`'s `local_day` in one case only: a `day_start` inside the hour a
fall-back night repeats (on Central European time, Oslo's, Zurich's and Copenhagen's, a `day_start` from
02:00 to 02:59 on the last Sunday of October; on London's, Dublin's and Lisbon's, 01:00 to 01:59).
`main` puts the second pass of that hour, before `day_start`, back on the day before, after the day had
begun; the maximum keeps it on the day, so that every day is one interval (§9 says what this costs).

### 2.3 A day's span: long days and short days

Day `D` begins at the first instant whose rule day is `D` or later and ends where `D + 1` begins. Its
rule span is `[begin(D), begin(D + 1))`. The rule day is non-decreasing (a maximum), so the rule spans of
consecutive days abut: every instant is on exactly one day, and no line is on two (§2.7). On one clock,
`begin(D)` is the first instant at which that clock reads `day_start` on the date `D` or later. (On a
spring-forward night with a `day_start` inside the skipped hour, that is the instant of the change;
`DayStart.span` on `main` returns the instant an hour later there, while `local_day` already puts the
lines of that hour on the day: a small disagreement of `main`'s own that this rule does not inherit.)
A day's **span**, as a reader reports it, is the extent of the instants §2.6 puts on it, which is its
rule span unless a signed neighbour moves an edge.

- **West.** Leaving Oslo on the 10th at 10:00 and landing in New York at 12:30 local, the 10th began at
  midnight in Oslo and ends at midnight in New York: 30 hours. The 11th is New York's.
- **East.** Leaving Los Angeles on the 15th at 19:00 and landing in Oslo at 15:00 on the 16th, the 16th
  began at midnight on the clock the owner was on, Los Angeles's, while in the air, and ends at midnight
  in Oslo: 15 hours.
- **Across the date line.** Leaving Honolulu at 23:00 on 25 June and landing in Auckland at 06:00 on the
  27th (New Zealand's winter time, UTC+12; in December, UTC+13, the day is 7 hours), the 26th began at
  midnight in Honolulu, in the air, and ended on landing: 8 hours, all of them aboard. A day can be
  shorter still, and empty, only where a single change of clock is more than 24 hours (Pago Pago, UTC−11,
  to Kiritimati, UTC+14): then that day has a span of zero and holds no line, and it is listed,
  marked as skipped (§12 q8): `days` prints it with `hours` 0 and `skipped` true, and `day` names it as
  crossed in the air. (UTC−10 to UTC+14 is exactly 24 hours: the wall clock reads the same time and the
  date moves by one.)

The worked journey of Ines Nordmann, record zone `Europe/Oslo`, June 2026 (synthetic; flights of the
airline XY; computed by the rule above):

| Day | Begins (UTC) | Ends (UTC) | Hours | Began in | Why |
|---|---|---|---|---|---|
| 06-09 | 06-08 22:00 | 06-09 22:00 | 24 | Europe/Oslo | |
| 06-10 | 06-09 22:00 | 06-11 04:00 | 30 | Europe/Oslo | XY 101 OSL→JFK lands 16:30Z, 12:30 in New York |
| 06-11 | 06-11 04:00 | 06-12 04:00 | 24 | America/New_York | |
| 06-12 | 06-12 04:00 | 06-13 04:00 | 24 | America/New_York | |
| 06-13 | 06-13 04:00 | 06-14 07:00 | 27 | America/New_York | XY 203 JFK→LAX lands 19:00Z, 12:00 in Los Angeles |
| 06-14 | 06-14 07:00 | 06-15 07:00 | 24 | America/Los_Angeles | |
| 06-15 | 06-15 07:00 | 06-16 07:00 | 24 | America/Los_Angeles | XY 305 LAX→OSL leaves 06-16 02:00Z, 19:00 on the 15th |
| 06-16 | 06-16 07:00 | 06-16 22:00 | 15 | America/Los_Angeles | it lands 13:00Z, 15:00 in Oslo |
| 06-17 | 06-16 22:00 | 06-17 22:00 | 24 | Europe/Oslo | |

On `main` the same record puts 06-10 18:00 to 24:00 in New York on the 11th, and every evening in New
York and Los Angeles on the next day; and the first five hours of XY 305 (02:00Z to 07:00Z on the 16th)
on the 16th, where this rule keeps them on the 15th, the evening the owner left Los Angeles.

**The night flight across midnight.** XY 107 leaves Oslo at 21:00 on the 20th (19:00Z) and lands in New
York at 23:00 on the 20th (03:00Z on the 21st). The 21st began at midnight in Oslo, 22:00Z, in the air.
On landing New York's clock reads the 20th, and the maximum keeps the owner on the 21st: the 21st runs
from 22:00Z on the 20th to midnight on the 22nd in New York (04:00Z), 30 hours, and the hour in New York
between landing and midnight is on the 21st. A rule without the maximum (the owner-local date of every
instant) would put that hour back on the 20th, a day already ended and perhaps already signed: the 20th
would be begun twice.

### 2.4 Stays, moves and nights across a change

Stays are unchanged. Stays, stops and moves are clustered on instants (SPEC §3.2.3) and never on days; a
segment keeps its real span, and a day's timeline cuts it at the day's span as it cuts a stay across
midnight today (`within_day`, SPEC §3.2.7 rule 1). What changes is only where the cuts fall.

A change asserted by where the owner is (§2.1, kind 3) falls on the first point of a still run in the
new zone, so it falls at or after the start of the stay it is in: at the start for most stays, a
little after it for a stay that began inside a named place's wider radius, across a short silence, or
past a dropped noise point (SPEC §3.2.3 rules 1 and 2). A change can fall well inside a stay when the
owner's word or a flight puts it there (a note "from now I am on Lisbon's
clock" in a hotel; a flight whose arrival time is wrong). Then the stay keeps its one span and place; the
day boundary inside it is where the rule puts it; and its `start_local` and `end_local` are each on the
clock of that instant.

**The night** of a day keeps its definition (SPEC §3.2.3 rule 8): the owner's stay with the longest
overlap of the day's night window. The window is read on the owner's clock: it begins at the first
instant at which the owner's wall clock, on the day `D`, reads the night's start (22:00 by default), and
ends at the first instant after that at which it reads the night's end (08:00 the next morning). On one
clock that is `stays.night_window` today. A night flight is in transit, as it is today.

The passage of the yacht Solvind from Kristiansand to Aberdeen is a move aboard (SPEC §3.2.3 rule 7); the
boat asserts nothing while it moves, though the nearest airport changes from Kristiansand's to Aberdeen's
in mid-sea; its first still run, berthed in Aberdeen at 09:00Z, asserts `Europe/London`. The day of
arrival, 2026-07-02, began at midnight in Kristiansand and ends at midnight in Aberdeen: 25 hours. The
night of the 2nd is read from 22:00 to 08:00 in Aberdeen.

### 2.5 `day_start`

`day_start` applies on every clock: a day begins at `day_start` on the owner's clock, wherever the owner
is. Under `"06:00"` the 10th of the journey begins at 06:00 in Oslo and ends at 06:00 in New York. The
maximum and the spans are computed with the naive day under `day_start`, so nothing in §2.2 or §2.3 is
special to midnight.

### 2.6 A signed day keeps its zone and its span

A signed day is the owner's reading of one page (RFC 0034). If a later import, a flight or a note moved
the day's edges, the page the owner signed would silently become another page, and the signature would
cover lines the owner never saw, or lose lines they confirmed. So **a signed day is never re-bucketed**:
a reader puts a signed day's lines where its standing signature says, and applies the rule only to the
instants no signature claims. That holds in full for a new-style signature, whose span is written in it.
An old-style one names no span and claims by the record's zone and `day_start` of the moment, so it
moves when the owner changes `timezone` (`Logbook.set_timezone`) or `day_start`, as it does on `main`
today. From the release that carries this RFC, every signature records the `day_start` it was signed
under (`extra.day_start`, §12 q7), with the setting on or off, so a signature written from then on no
longer moves when `day_start` changes; a change of `timezone` still moves an old-style one, as on
`main`.

**What a signature says.** A new-style signature, written while `local_days` is set, carries under
`extra` (RFC 0034: "Anything else MAY be kept under `extra`"):

```json
"extra": {"tz": "Europe/Oslo", "span": {"start": "2026-06-09T22:00:00Z", "end": "2026-06-11T04:00:00Z"},
          "zones": [{"at": "2026-06-10T16:30:00Z", "tz": "America/New_York", "by": "flight", "line": "<id>"}],
          "day_start": "00:00"}
```

`tz` is the owner's zone when the day began, `span` its span in UTC with `Z`, as every instant of the
record is written, `zones` the changes inside the span, in order (empty for a day on one clock), and
`day_start` the record's `day_start` when it was signed, `HH:MM` (`"00:00"` when the key is absent). A
signature written with the setting off carries `extra.day_start` alone. The
page digest is unchanged: its pre-image is still `{"day", "tz", "lines"}` with `tz` the record's zone
(RFC 0034, *The page as shown*), so the digest of every signature on `main` stays valid and a reader
that does not know this RFC still checks it; `extra.tz` and `extra.span` name the clock and the span
beside it (§12 q2). RFC 0034's payload table says `day` is "the local day signed … in the record's
zone", and its rule 5 gates the crossing by the record-zone day; the amendment redefines both: `day` is
the day signed under SPEC §3.2 as the record reads it (this RFC's rule when the setting is on), and the
crossing's gate asks each line's day as §2.6 gives it.

An old-style signature carries no span. It was signed under `main`'s rule, so it says: the lines whose
naive day in the **record's zone**, under the `day_start` it was signed under (its `extra.day_start`,
else, for a signature written before this RFC, the record's `day_start` now), is its day. That is what
it claims.

**The day of an instant**, with the setting on:

1. An instant claimed by a standing signature is on that signature's day. An old-style signature
   claims the instants whose naive day in the record's zone, under its `day_start` (above), is its day; a new-style one the instants of
   its span. A span is honoured when it is well formed: both ends RFC 3339 UTC with `Z`, `start` at or
   before `end`, no longer than 72 hours, and inside `[D − 2, D + 3)` at midnight UTC for its day `D`
   (wide enough for any `day_start` and any zone); else the signature claims as an old-style one does,
   and the reader says the span was not honoured. An empty span (`start` equal to `end`, the day crossed
   in the air) claims nothing. When two standing signatures claim one instant, the later signature (by
   `seq`) has it: the owner's latest reading wins, whatever its style.
2. Else its rule day `R`, when `R` has no standing signature.
3. Else `R` is signed and does not claim the instant. When the instant comes before every instant `R`
   claims, it is on `R − 1`; when after every one, on `R + 1`; when between two (only an old-style
   signature on the fall-back night of §2.2), on its naive day in the record's zone, which is `main`'s.
   That day's page then shows the line; when that day is signed too, its page no longer digests to what
   was signed and the reader says so ("the page has changed since", as for a backfilled line on `main`).

Every step is defined for every instant and gives one date, so every line is on exactly one day (§2.7).
A signed day's date never changes and the instants it claims never leave it while its signature
stands; the days beside it lose or gain the hours the rule and the signature disagree on.

**Signing with the setting on.** `day sign D` computes `D`'s span with the other days' standing
signatures in place: `begin(D)` is pinned to the end of a signed `D − 1` and `begin(D + 1)` to the
beginning of a signed `D + 1`, so a writer never writes two spans that overlap or leave a gap. The page
is the lines of that span (every kind but `retraction` and `signed-day`, by instant then `seq`, as
today), and the signature writes `extra` as above. Re-signing a day recomputes its span the same way: the
owner's new reading is a new page.

**Switching the setting off** is refused while a new-style signature stands: an old-style signature
written after it, pinned to nothing, could overlap it, and rule 1 would then give the later one the
overlap, so the earlier day's page would change with nothing appended. The owner who wants record-zone
days back retracts or re-signs those days first; `logbook setup local_days off` lists them. A reader
that knows this RFC honours a new-style span whatever the setting says (a hand-edited `logbook.json`
cannot move a signed day), since the span is the signature's and not the setting's. Only records that
once had the setting on have new-style signatures, so on every record of `main` this changes nothing.

The worked case. Ines signs 06-10 with the setting off: an old-style signature, Oslo's midnight to
midnight. She then sets `local_days`. The 10th keeps 06-09 22:00Z to 06-10 22:00Z (rule 1); the rule
would end it at 06-11 04:00Z, so the six New York hours from 18:00 to midnight are unclaimed and lie
after the signed day: they are on the 11th (rule 3), and the 11th's span runs from 06-10 22:00Z to
06-12 04:00Z. If she re-signs the 10th while the 11th is unsigned, the new signature takes the 30-hour
span and the six hours come back to the 10th; when the 11th is signed, the writer pins the 10th's end to
the 11th's start and they stay where she signed them.

### 2.7 No line vanishes, no line is on two days

The day of an instant is a function (§2.6, rules 1 to 3): each rule yields one date, and the last rule
leaves nothing undefined. A line whose `at` does not parse is on no day, as SPEC §3.2.1 says today; no
other line can be on none. The danger is not the rule but a reader that fetches too few lines to apply
it: §5 gives the bound a reader widens its index cut by, and a reader that cuts narrower loses lines.

## 3. The setting

`logbook.json` MAY carry `"local_days": true`. It is off by default, for every record, new ones
included, until the owner has lived with it on; whether a new record sets it is decided after that
(§12 q9). Absent, or `false`, every unsigned day groups as on `main` (a standing new-style signature
keeps its span, §2.6, and exists only on a record that once had the setting on). Any other value is
refused, naming the key and the value, by the reader that groups by day, as RFC 0036
refuses a `day_start` it cannot parse; a refusal is never "as if absent". `logbook setup local_days on`
and `off` write it, under the writer lock, preserving every other key (SPEC §1). `doctor` names it. The
index does not record it (§5).

A reader that does not implement this RFC and meets `"local_days": true`, or a standing `signed-day` line
with `extra.span`, MUST refuse to group by day rather than group by the record's zone silently, from the
release of SPEC that carries §6 on (a reader already shipped cannot be bound): two readers of one record
would otherwise print different days with no word said. `verify`, `add` and `show --raw` do not group by
day and are not affected.

## 4. The readers

Every reader that puts a line on a day, a stay on a night or a count in a day, a month or a year changes
with the setting and with nothing else. There are two roads to a day on `main`, and every reader takes
one or both:

- **Road A**, the rule: `day_start.of(meta)` returns a `DayStart`, asked `day(instant)`, `day_of(stamp)`,
  `today(now)` or `span(day)` (`logbook/core/day_start.py:106` onwards). Under this RFC `DayStart` must
  know the owner's zone at an instant, so `of` must read the evidence (§2.1), which `meta` alone does not
  hold: it becomes `of(meta, idx)`, or a `LocalDays` built once per command from the index.
- **Road B**, the index: the column `day_local`, derived per line by `index.local_date`
  (`logbook/core/index.py:233`) and cut by `Index.day` (:633), `between` (:640), `by_kind` (:727),
  `stream` (:738), `locations` (:763), `evidence` (:779), `of_source` (:805), `of_kind` (:837),
  `source_days` and `kind_source_days` (:912, :932), `span`, `kinds`, `years` and `activity` (:902 to
  :1048) and `search` (:1065). Under this RFC `day_local` stays the record-zone day and becomes a locator
  only (§5): a reader widens its cut and applies the rule to the lines it read.

The readers, by module (core first; the line is where the day is taken):

| Reader | Where | Road | What changes with the setting |
|---|---|---|---|
| `show` (a day) | `logbook/commands/day.py:301` | B | the day's lines by the rule; header names the zone(s) |
| `day` | `logbook/core/day.py:169` (`read`), `:310` (`day_lines`) | A, B | the window, the page, `tz` (the zone it began in), `*_local` on the clock of each instant, a new `zones` list |
| `days` | `logbook/core/days.py:94` (`_by_day`) | A | lines by the rule; `moved_m` per day as before |
| the shared reading | `logbook/core/reading.py:175` (`read`), `:249` (`owner_track`), `:307` (`_window`) | A, B | the window's first and last instants from the spans; the night windows on the owner's clock |
| `derive stays`, nights | `logbook/core/stays.py:949` (`night_window`), `:970` (`Nights`) | A | the night window on the owner's clock (§2.4) |
| `trips` | `logbook/core/trips.py`, through `Nights` | A | runs of nights over the new days |
| `rollup` | `logbook/core/rollup.py:371`, `:736` | A, B | stays and lines per day by the rule |
| health | `logbook/core/health.py:94` to `:190` | B (`local_date`) | sleep, steps, resting and HRV per rule day |
| `keepers` | `logbook/core/keepers.py:172` | B | a keeper's day and month by the rule |
| `export` | `logbook/core/export.py:63`, `:86` | B | a range of days by the rule |
| the crossing's gate | `logbook/core/crossing.py:257` to `:262` | A | a line crosses with the day the rule (and §2.6) puts it on |
| the signed day | `logbook/core/signing.py:84` (`page`), `:95` (`page_digest`), `:191` (`_sign`), `:273` (`moment`), `:459` (`signed_json`) | A, B | §2.6: the page by span, `extra`, the moment checked against the span |
| readiness | `logbook/core/readiness.py:49` | B | the page of a day by the rule |
| the year, pages | `logbook/core/year.py:276`, `:291`; `logbook/core/pages.py:218`, `:222` | A | days by the rule |
| drafts, presence, stars, people, ledger | `logbook/core/drafts.py:526`; `presence.py:171`; `stars.py:137`, `:230`; `people.py:433`, `:627`, `:634`; `ledger.py:231` | A | a line's day by the rule |
| goals, chapters, notes | `logbook/core/goals.py`, `chapter.py`, `notes.py` | A (`today`) | today is the rule day of now |
| share | `logbook/core/share.py:272`, `:633` | A | a shared page's day |
| commands | `logbook/commands/record.py:381`, `keepers.py:41`, `rollup.py:122` to `:128`, `derive.py:667`, `trips.py:88`, `transcript.py:85` | A, B | as their readers |
| the door (MCP) | `logbook/contrib/mcp_server.py:290` to `:299` (its gated index overrides `day`, `between`, `window`), `:320` to `:460` (its own `day_local` SQL), `:532`, `:803` | B | widen and filter, as the index's own callers |
| the Library | `logbook/contrib/serve.py` (the Day page, `/today`, the week) | A, B | as `day`; after #344 and #345 land |
| `doctor` | `logbook/contrib/doctor.py:262`, `:683` to `:688` | A | names the setting; after #338 lands |
| the contrib readers | `digest.py:82`, `dream.py:298`, `dream_week.py:375`, `:902`, `notify.py:255`, `reflect.py:130`, `synthesis.py`, `world.py`, `trip_page.py:223`, `print_page.py:191`, `week_paper.py:89`, `:123`, `people_nearby.py:185`, `:228`, `taskdone.py`, `vault.py:956`, `site.py`, `entity_review.py:301`, `:837`, `relationship/reader.py:254`, `:372`, `notion_export.py`, `gaps.py:54` to `:110`, `journeys.py:266`, `people_review.py:447`, `people_drift.py:106`, `video_review.py:663`, `first_run.py:69`; `logbook/labs/transcribe.py:673`, `introductions.py:113` | A, B | a line's day by the rule; the ones that only count lines per record-zone day (`stats`, `years`, `kinds`) MAY keep the record's zone and say so |

`sources --gaps` (SPEC §3.2.11) counts missing days; it takes the rule days like the rest. `promises`
dates a proposal by its line's day, and `verify`, `add`, `infer flights` and the adapters group nothing.

**The JSON.** With the setting off no field changes. With it on, a day **on the record's clock** (no
change of clock inside it, and begun on a zone with the record's zone's offset) prints exactly as on
`main`: `tz` the record's zone, no new key, `*_local` in the record's zone. Only a day off the record's
clock changes: `day --json` gains `zones` (the changes of clock inside the day: `at`, `tz`, `by`, `line`)
and `span` (`start`, `end`, `hours`); its `tz` is the zone the day began in; a `*_local` field is the
instant on the owner's clock at that instant, with its offset (SPEC §3.2.2 says "in the record's zone"
today). `days --json` gains `tz` and `hours` on such a day, and `skipped` (true) on an empty one (§2.3).
A change between zones of one offset (the demo's photos from Zurich) is no change of clock and shows
nowhere in the JSON. Every other reader's JSON keeps its keys.

**What it costs on a record of five million lines.** The evidence is read once per command, from the
index and never from a scan of the files:

- flights: the standing set is a few hundred lines (`idx.by_kind("flight")`), read already by `day` and
  `trips`; milliseconds;
- where the owner is: the owner's location points from four days before the window to its end, from the
  index's own columns (`idx.locations`, no file read), each placed by `Airports.nearest`; a day reads a
  few thousand points. A reader over the whole record (`days`, `rollup`) reads every point, two to three
  million on a five-million-line record, which `derive stays` already reads for the same command; placing
  each needs a cache by 0.1° cell (a few thousand cells for a lifetime), else `nearest` with a 300 km
  radius scans all 1,150 airports per point, minutes instead of seconds;
- the zone carried into the window: the latest assertion before `first − 4`, one indexed query per kind
  (the last flight arriving before it; the last still run before it, `idx.last_fix`-like; the last
  `zone` note);
- notes labelled `zone`: tier 2 and sealed on a record that seals (SPEC §4), so a reader needs the
  identity to read them, and without it a note asserts nothing and the reader says how many it could
  not open. Reading every note of the record per command is too slow at tens of thousands; the labels
  must come from a derived table (§5) or from `places.json`-like local state.

So a day costs what it costs today plus a few thousand index rows; a whole-record reader costs one more
pass over the points `derive stays` reads anyway, provided the cell cache exists.

## 5. The index

`day_local` does not learn the setting. It stays the record-zone day (`index.local_date`, unchanged),
the locator a reader cuts a window by, and `SCHEMA_VERSION` does not move: every index row is byte for
byte what `main` writes, with the setting on or off. Two reasons:

1. **It cannot.** The index is built in one pass and extended inside `append` (`_index_if_current`),
   one row per line. The day of a line under this rule depends on other lines (a flight imported today
   moves the edges of a day two years ago), so a row would have to be re-bucketed whenever a flight, a
   note or a point lands: a rebuild trigger on every import, and a digest of the zone timeline in the
   index's `meta`.
2. **It need not.** Every instant a reader puts on day `D` has a record-zone date, the `day_local`
   the index holds, in `[D − 4, D + 4]`, and every instant of `D`'s rule span one in `[D − 2, D + 2]`.
   Proof. Write every instant shifted back by `day_start`, so that a naive day is the calendar date of
   the shifted instant plus the zone's offset, for the owner's clock and the record's alike. `D` begins
   at an instant where the owner's clock reads `D`, or at a change that passes it; no zone is ahead of
   UTC by more than 14 hours, so the shifted `begin(D)` is at or after `D − 1` 10:00 UTC. `D + 1` begins
   at the latest when the owner's clock reads `D + 1`, and no zone is behind UTC by more than 12 hours,
   so the shifted `begin(D + 1)` is at or before `D + 1` 12:00 UTC. The maximum holds only a date some
   clock has already shown, so it moves neither edge past these. The record's zone is itself between
   UTC−12 and UTC+14, so a shifted instant from `D − 1` 10:00 to `D + 1` 12:00 UTC has a record-zone
   date from `D − 2` to `D + 2`. For the signed days of §2.6: an old-style claim is the record-zone day
   itself; an instant rule 3 moves to `R ± 1` lies in `R`'s rule span, so within `[R − 2, R + 2]`; and a
   new-style span is honoured only inside `[D − 2, D + 3)` at midnight UTC (§2.6), whose instants have
   record-zone dates from `D − 4` (midnight UTC less twelve hours and a `day_start` of 23:59) to `D + 3`.
   ∎ For any two zones less than 24 hours apart one date either side would bound the rule span; pairs
   more than 24 hours apart exist across the date line (Pago Pago and Kiritimati, 25 hours), so the RFC
   asks for two, and for two more to honour a span signed under another `day_start`.

   So a reader asking for the days `[first, last]` cuts `day_local` over `[first − 4, last + 4]`, keeps
   the rows whose `at` (an index column; no file is read for it) can lie on those days, reads the
   standing signatures (one line per signed day; `standing` reads them all by kind already) and the
   zone timeline from `first − 4` on, and applies the rule to what it read. A day costs nine record-days
   of index rows, not one, and the same lines read from the files as today.

What the index MAY gain later, in a pull request of its own with its own `SCHEMA_VERSION`: a derived
table of zone assertions (the still runs and the `zone` notes, with the line ids), rebuilt with the
rest, so that a reader never places points or opens notes per command. It is a cache, not the rule.

## 6. SPEC

When adopted, SPEC §3.2's second paragraph gains, after "it is never the default":

> A record whose `logbook.json` sets `"local_days": true` (RFC 0044) is read by the owner's clock
> instead: a reader puts each line on the local day the owner was in when it began, as RFC 0044 §2
> gives it, with the zone at an instant asserted by the owner's `zone` notes, the standing flights'
> arrivals, the owner's still location runs and two photos' agreeing `tz`, in that order, and the record's
> zone where nothing asserts one; a signed day keeps the span its signature names. A reader that does
> not implement RFC 0044 MUST refuse to group such a record by day.

and §3.2.2 *Output* says that, on such a record, a `*_local` field is on the owner's clock at that
instant. §3.2.3 rule 8 reads its night window on the owner's clock. That is a reader's rule, as SPEC
0.4's was: the document becomes 0.5, the format stays `logbook/0.3` (§1 to §3.1, the envelope and the
hash are untouched), and an ADR records the decision. CLAUDE.md's rule for "the envelope (SPEC §2–3)"
asks the same three things of an envelope change; this is not one, but it is taken the same way, as 0.4
was with ADR 0023. SPEC §2's sentence on `tz`, "the owner's timezone at `at`", stays: it is what a writer
SHOULD put there, and §2.1 kind 4 says why a reader cannot rely on it.

Until it is adopted, the amendment is a proposed section of SPEC, marked as not yet normative, placed
after §7 so that §2 and §3 are untouched, in the pull request that builds the readers (§10).

## 7. Conformance

**No existing vector changes.** The setting is off unless a record sets it, and no fixture sets it:
`conformance/expected.json` and `expected-sealed.json` (the heads), every `conformance/profiles/*`
fixture (its line, canonical form, hash, `show.txt`, `day.json`, `days.json`) and the demo record of SPEC
§6.1 are untouched. They would not move with it set either: every line of the conformance samples and of
every profile record has `tz` `Europe/Oslo`, the samples' two flights are between OSL and CPH, whose zone
has Oslo's offset all year; and the seed-1 demo's 9,936 location lines, placed by the nearest airport,
its four flights and its lines whose `tz` is `Europe/Zurich` (1,220) or `Europe/Copenhagen` (690) fall in
`Europe/Oslo`, `Europe/Zurich` and `Europe/Copenhagen`, none at another offset than Oslo's on any of its
days (checked for this RFC). By §9 no line moves, and by §4 every day is on the record's clock, so no
JSON changes.

**New vectors**, for the setting on, in `conformance/local-days/`, each a record with `"local_days":
true` and an `expected.json` that maps every line id to its day and every day to its span, `tz` and
`zones`, with `day.json` and `days.json` as the profile fixtures carry them:

1. the journey of §2.3, Oslo → New York → Los Angeles → Oslo (a long day, a 27-hour day, a short day);
2. the westward night flight across Oslo's midnight (the maximum);
3. Honolulu → Auckland across the date line (an 8-hour day);
4. the Solvind passage Kristiansand → Aberdeen (a change asserted by a still run, a stay after it, the
   night on Aberdeen's clock);
5. Oslo → Zurich → Oslo (zone changes, no change of clock: identical to the record with the setting off);
6. a note labelled `zone` that overrides two photos' `tz` and a flight in the 12 hours after it, and a
   flight the next day that moves the clock on;
7. a day signed old-style, then the setting set (§2.6's worked case), and the same day re-signed;
8. a day signed new-style, then a flight imported that moves the rule's edge (the signed day keeps its
   span; the day beside it takes the difference);
9. the profile fixtures and the seed-1 demo with the setting on: each `day.json` and `days.json` byte for
   byte what the setting off prints (every day of them is on the record's clock, §4).

A reader that implements this RFC passes them; one that does not must refuse each record (§3).

## 8. logbook-ts

logbook-ts carries `verify`, `add` and `show`, and its cross-implementation test diffs `show`, `day`,
`days`, `stats`, `trips` and `rollup countries|nights` against the reference (SPEC §6.1, *Status*). It
must, before the reference ships the setting: refuse to group by day a record that sets `local_days`
(§3), until it implements the rule; then implement §2 (the evidence, the maximum, the spans, the signed
claims), the widened cut where it has an index, and pass the vectors of §7. Its `verify` and `add` need
nothing. Nothing in this RFC is changed in that repository by this pull request.

## 9. Migration, and the proof that a record with one zone and no travel sees nothing

Nothing is migrated. No line is written, the index is not rebuilt, and a record without the setting
reads as before. Setting `local_days` writes one key of `logbook.json`.

**Claim.** On a record where every zone of the owner's timeline (§2.1) has the record's zone's UTC
offset at every instant of its stretch, and every standing signature is old-style (with no
`extra.day_start` other than the record's `day_start`), every instant is on
the same day with the setting on as on `main`, under any `day_start`, with one exception: a `day_start`
inside the hour a fall-back night of the record's zone repeats. A record with no evidence of travel is
the case of one stretch, the record's zone.

**Proof.** The naive day depends on the zone only through the UTC offset at the instant (the wall clock
is the instant plus the offset), so at every instant `naive_day(t, Z(t), day_start) = naive_day(t,
record's zone, day_start)`, which is `main`'s `local_day(t)`. On one clock `local_day` is
non-decreasing in `t`: the wall clock only goes back on a fall-back night, by the repeated hour, and
the date it shows goes back only when `day_start` lies inside that hour. Outside that case the maximum
of a non-decreasing function up to `t` is its value at `t`, so `rule_day(t) = local_day(t)`. With only
old-style signatures, rule 1 of §2.6 claims exactly the instants `main` puts on each signed day; every
other instant has a rule day that is `main`'s day and is not signed (a signed one would claim it), so
rule 2 gives `main`'s day and rule 3 never applies. Every reader of §4 takes its days from this
function, so every day holds the lines it holds on `main`. ∎

**The exception.** With, say, `"day_start": "02:30"` in `Europe/Oslo`, on 2026-10-25 `main` puts the
instants from 01:00Z to 01:30Z (02:00 to 02:30 CET, the second pass) on the 24th, after the 25th began at
00:30Z; this rule puts them on the 25th. With the 24th signed old-style they stay on the 24th (rule 1);
with the 25th signed old-style and the 24th not, rule 3 gives them `main`'s day, the 24th. So only lines
of that half hour, on a night neither day is signed, move, and only on a record whose `day_start` is set
inside the repeated hour. At midnight, the default, it would need a zone whose clocks go back across
midnight, and none does: no zone of the zone database shows its local date going back at any instant from
2020 to 2030 (checked for this RFC). `logbook setup local_days on` names such lines before it writes the
key. Keeping `main`'s half hour instead, at the cost of a day that is two intervals, was weighed and
not taken (§12 q1).

The hypothesis holds of every fixture of §7: Oslo, Zurich and Copenhagen kept the same UTC offset
through every day of 2026, the year every fixture is in, and no fixture sets `day_start`.

The fixture checks of §7 (vector 5, vector 9, and the demo record diffed with the setting on and off)
are the same proof run on data.

Where the hypothesis fails, the record has travel, and the days of that travel move: which is the point.
The owner sees it before it happens: `logbook setup local_days on` prints the days whose span changes
(the first and last ten, and a count), and the signed days among them that keep their span.

## 10. What the code needs (why this pull request builds nothing)

The brief for this pull request allowed changes in `logbook/core/day_start.py`, in
`logbook/core/index.py` only if `day_local` had to learn the setting, and in `logbook/core/signing.py`
only for `extra.tz` and the span, and asked for the RFC alone if anything more were needed in
`store.py`, `signing.py` or `index.py`. More is needed, so this pull request carries the RFC alone:

1. **`signing.py`, beyond the fields.** Writing `extra.tz` and `extra.span` without honouring them would
   be the opposite of "never re-bucketed": a span no reader obeys. Honouring them changes `page` (:84;
   the page by span, through `idx.window` or a widened `idx.between`, instead of `idx.day`), `_sign`
   (:191; the span pinned against the neighbours' signatures, §2.6), `moment` (:273; `--at` checked
   against the span, not against `DayStart.day`), `signed_json` (:459; the `page_matches` of a day signed
   on another clock), `signatures` and `standing` (:105, :123; the claims of §2.6 as data for every
   reader), and the crossing's gate that reads them (`crossing.py:257`).
2. **`day_start.py`'s interface.** `of(meta)` takes `logbook.json` alone; the rule needs the evidence,
   which lives in the index. Every one of the roughly sixty callers of §4 changes to pass it, or to take
   a `LocalDays` built once per command.
3. **Every Road-B caller** widens its cut to `[first − 4, last + 4]` and filters (§5), including the
   door's own SQL in `mcp_server.py`, and the Library's Day page in `serve.py`, which is being changed by
   #344 and #345 and must wait for them.
4. **The command line**: `logbook setup local_days`, the owner's command that writes a `zone` note
   (§12 q4), `extra.day_start` on every signature `day sign` writes, with the setting on or off (§12 q7;
   with the setting off that changes the line written, not what any reader prints), and `places.json`'s
   `tz` read by `places` (§12 q5); `doctor` and the command line are being changed by #338; and
   `docs/settings.md`, `docs/day.md` and `docs/signed-day.md`.
5. **Optionally the index's derived table** of zone assertions (§5), with its own `SCHEMA_VERSION`.

None of it needs a change to `store.py`, to an existing line, to the envelope, or to an existing
conformance vector. The order proposed: the pure rule in `day_start.py` with the vectors of §7 as unit
tests (no reader calls it); then `signing.py` and the readers of `logbook/core/` in one pull request with
the SPEC section marked proposed; then the door, the Library and the command line after their open pull
requests land; then adoption, SPEC 0.5 and the ADR.

## 11. Where this RFC differs from its brief and from RFC 0043

- The brief cites "RFC 0043 §6f.1 and decision 15". RFC 0043 has no §6f.1: its §6 is the rules of the
  evening dream, its item 15 (§14) is a place's class, and its slices (§15) are A to E. The text this RFC
  builds is RFC 0043 §12's first bullet and §14 item 8.
- RFC 0043 §12 says "`extra.tz` on the signature is not needed, since the page digest names the zone".
  The digest names the record's zone (RFC 0034, *The page as shown*), not the zone the day began in, and
  it cannot name a span. This RFC keeps the digest as it is and adds `extra.tz`, `extra.span` and
  `extra.zones` (§2.6).
- "Midnight to midnight in the zone where the owner was when it began", read literally, gives each day 24
  hours in one zone and leaves the evening of a westward flight on no day, or on two. §2.3 reads it as
  the owner's clock: a day begins at midnight on the clock the owner is on and ends at the next midnight
  on the clock the owner is on then, which is what makes a westward day long.
- "The zone of the place a stay is at from `zone.tab`": `zone.tab` maps a zone to its country, not a
  point to its zone. The point's zone comes from the airports table (every row carries one) or a place's
  own `tz`, the road SPEC §3.2.7 rule 6 already takes for a country.
- "A line's own `tz`" is weak evidence on `main`: the writer fills it with the record's zone when an
  adapter gives none, a flight carries its origin's zone, a calendar entry its organiser's. §2.1 takes it
  from photos only.
- The brief asks for a SPEC section in this pull request and a version bump in none; §6 places the
  section with the code that implements it, so that SPEC never proposes what no reader does.

## 12. Decided

The nine questions this RFC asked, as the owner answered them on 21 October 2026. The text above is
written to these answers.

1. **The running maximum.** A day once begun is never left for an earlier date (§2.2), so every day is
   one interval. Weighed and not taken: the owner-local date of every instant with no maximum, which
   begins the day before again after a westward night flight; and a maximum applied only where the clock
   changes zone, which keeps `main`'s half hour on the fall-back night of §9 but makes that day two
   intervals.
2. **The page digest keeps the record's zone.** Its pre-image stays as RFC 0034 has it, so every digest
   on `main` stays valid and a reader that does not know this RFC still checks it; the day's clock and
   span are under `extra` (§2.6).
3. **The 12-hour shadow stays, and photos assert a zone only when two agree** (§2.1): a lower-ranked
   assertion in another zone within 12 hours after a higher-ranked one is ignored, and one photo's `tz`
   asserts nothing.
4. **The owner's word is a `zone` note in the record**, a `note/v1` labelled `zone`, written by the owner
   through the command line (§2.1, kind 1; §10 item 4). It is in the chain, tier 2 and sealed on a
   record that seals; a reader without the identity counts the notes it could not open (§4). A local
   `policy/zones.json` was weighed and not taken.
5. **`places.json` gets an optional `tz`** beside `country` (§2.1, kind 3): an IANA zone name that places
   a point inside the place's radius before the nearest airport is asked.
6. **Switching off is refused while a new-style signature stands** (§2.6): the owner retracts or
   re-signs those days first, and `logbook setup local_days off` lists them.
7. **Signatures record `extra.day_start` from now on** (§2.6), with the setting on or off, and an
   old-style signature that carries one claims by it, so a day signed from then on no longer moves when
   `day_start` changes. Signatures written before keep claiming by the record's `day_start` of the
   moment, as on `main`, and a change of `timezone` still moves an old-style signature.
8. **The empty day across the date line is listed, marked as skipped** (§2.3): `days` prints it with
   `hours` 0 and `skipped` true, and `day` names it as crossed in the air.
9. **Off by default until the owner has lived with it on** (§3). Whether a new record sets it is decided
   after that, in its own change.

## Example (synthetic)

The signature Ines writes for the 10th of the journey with the setting on, as `day sign 2026-06-10`
appends it (tier 1; the ids and digest made up; its envelope `tz` is the record's zone, as
`Logbook.append` fills it when the writer names none, and this RFC does not change that):

```json
{"at":"2026-06-11T03:40:00Z","end":null,"tz":"Europe/Oslo","source":"manual","kind":"signed-day",
 "tier":1,"payload":{"schema":"signed-day/v1","day":"2026-06-10",
 "subject":"00000000-0000-4000-8000-000000000001",
 "confirmed":["00000000-0000-4000-8000-0000000000a1","00000000-0000-4000-8000-0000000000a2"],
 "page":{"sha256":"7ed527057371e8656f8754fe8e7492c4bc2355234ec458c19d22f4f6ba060354","lines":2},
 "extra":{"tz":"Europe/Oslo",
          "span":{"start":"2026-06-09T22:00:00Z","end":"2026-06-11T04:00:00Z"},
          "zones":[{"at":"2026-06-10T16:30:00Z","tz":"America/New_York","by":"flight",
                    "line":"00000000-0000-4000-8000-0000000000f1"}],
          "day_start":"00:00"}}}
```

Her two lines: the flight XY 101 at 08:00Z and a note at 23:10 in New York (03:10Z on the 11th), "Dinner
with Per Hansen near the hotel". On `main` the note is on the 11th; with the setting, and under this
signature, it is on the 10th, where she wrote it.
