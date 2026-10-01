# ADR 0019 — Trips are derived, never written

Status: accepted · 2026-10-01

**Context.** The readers now turn the record into stays, nights, countries and company (`derive stays`, `rollup`, the with module), and the next thing a person wants to read back is the trip: the weekend aboard, the week in Zürich, with its route, its nights, who was there and the flights at each end. A trip is the first derived thing that feels like a fact of its own — people name trips, remember them, and would expect one to be *in* the logbook. The tempting design is a line for the derived trip, written by an engine when it finds one, so that `show` and the pages can read it like a flight or an event. That would put a judgement into the chain. A trip exists because of a threshold (what counts as away, what counts as a night), a setting (which places are home), and a derivation that improves with every version of the readers; a line, once written, is what the chain says happened. The record already has a rule for this, ADR 0013 rule 7 and ADR 0018 rule 3: raw and derived never share a line, and aboard is derived, never written.

**Decision.**

1. **A trip is a reader's output.** `logbook trips` computes trips from the nights of a window every time it runs: a run of consecutive days whose overnight stay is outside every home region (`places.json`, kind `home`) or in transit, with its route, nights, places, people and the flights in and out, and `asset` set when every night was aboard one asset. Nothing is appended. Changing the home places, the night window or the readers' rules changes the trips the next run prints and changes no line.
2. **A trip has a derived id, not a line id.** `trip:<first day>:<last day>`, reproducible from the record (ARCHITECTURE: derived ids are stable so that human notes stay attached). It is what a note or a page refers to; it is never the `id` of a line.
3. **The captain's naming is the line.** When the captain names a trip ("Midsummer aboard", "the Zürich week"), that is a `note/v1` line, written through `logbook add` as any note, in the captain's words, dated inside the trip. The name is a fact — the captain said it — and it is the only part of a trip that enters the chain. A reader that shows a trip may show the notes of its days beside it; it does not parse them into fields.
4. **No profile for the derived trip.** This ADR declines one rather than deferring it. RFC 0020's `trip/v1` is a different thing and keeps its name: one *bought* movement or metered stop — a ride, a ticket, a parking session — as the service recorded it, raw evidence like a flight line. A source that supplies journeys of its own (an airline's itinerary, a travel app's export, a rail app's tickets) writes what it has — flights, events, `trip/v1` records — as those profiles; the trip of this ADR is derived over them and is never one of them.

**Consequences.**
- `trips` is cheap to change and safe to be wrong: a bad threshold is a bad printout, not a bad line.
- The pages and the rollups that mention trips (`rollup nights` and its longest trip, the asset page's trips aboard) all derive from the same `trips` function, so they agree.
- A circle page that shares a trip shares derived rows (ARCHITECTURE, the circle), signed by the owner at that head, never a trip line.
- The cost: there is no list of trips to grep in the files, and a reader that wants one runs the derivation over the window it needs. That is the same cost `derive stays` already carries, and the same choice ADR 0007 made for the index: derived is disposable.
