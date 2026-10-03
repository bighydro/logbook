# Shared trips

Two people on one trip keep two records of it. `logbook export trip-bundle` hands one of them to the
other as a folder; `logbook import trip-bundle` takes it in as *received* lines that never mix with
your own; `logbook trip` then shows the trip as both records saw it — who was there according to
each, the places they agree on, and what one of them saw alone. The format is RFC 0025, a crossing
package (RFC 0005) cut to one trip, under the same ceiling as every crossing (ADR 0016).

```bash
# Ola's record: the cabin weekend, for Ines, names included (tier 2)
logbook trips                                              # find the trip's id
logbook export trip-bundle trip:2026-06-12:2026-06-13 --to ines --tier 1,2
logbook export trip-bundle 2026-06-13 --to ines --dry-run  # any day inside the trip; count, write nothing
logbook export trip-bundle trip:2026-06-12:2026-06-13 --to ines --tier 1,2 --attachments --out ~/for-ines

# Ines's record: take it in, then read the trip
logbook import trip-bundle ~/from-ola --dry-run
logbook import trip-bundle ~/from-ola
logbook trip trip:2026-06-12:2026-06-13
logbook trip trip:2026-06-12:2026-06-13 --html ~/cabin.html
```

## What crosses

Only the trip's days, and only what a reader of a trip needs:

- **the lines**: the `photo/v1` lines of those days, with their hashes and never their pixels unless
  you pass `--attachments`, and the trip's standing `flight/v1` lines — verbatim, so each still
  hashes as you wrote it;
- **the rows your readers derive** (`trip.json`): the stays away from home with their nights and
  labels, the moves between them, the flights, and the people confirmed present (the calendar, a
  recording, your own words; never a face alone) with the addresses and numbers that name them;
- **the resolution lines** that give those people their names (RFC 0006).

Nothing of home crosses, and nothing else of the days does: not the location points, not the
calendar entries or notes the company was read from, not the health or money lines.

The destination must be named in `policy/crossing.json` with a `max_tier`, as for any crossing; a
request above it is refused naming the file. `--tier` defaults to 1. The people, your own refs and
the resolution lines are **tier 2** — a name is a resolution's work — so with the default the bundle
carries the places and the photos and says how many names it held back; pass `--tier 1,2` to name
people. Every real export appends one `crossing/v1` line to your chain naming the trip (`show` prints
it as `crossed to ines: 3 lines`); a dry run appends nothing.

## What comes in

The import checks every digest the manifest names and every line's own hash, and refuses a bundle
that does not match, a folder that is not one, and a bundle your own record exported. Then it appends:

- one **received line** per line of the bundle: kind `received`, source `received`, the sender's
  line verbatim under `payload.line`, `extra.from` the sender's owner id. It lands on its day at its
  own tier, and `show` lists it as `from Ola Nordmann: photo immich · …`;
- the **page**, one received line of schema `trip-share/v1`, keyed by the bundle id.

A received line is never one of yours. No derived reader takes the kind, so the sender's photos are
not your photos, their flights are not in your rollup, and their resolutions name nobody in your
registry. A line whose `raw_id` your record already holds — the same shared photo under the same
asset id, the same invite — is skipped and counted as *kept as yours*; a line received before is
skipped and counted too. Nothing is ever rewritten.

```
Ola Nordmann: trip:2026-06-12:2026-06-13 2026-06-12 – 2026-06-13 · bundle 01a0ffdb…
  2 lines received, 3 resolutions, page received
  skipped: 1 kept as yours, 0 received before
```

## The merged page

`logbook trip <id>` finds every received page whose trip touches yours and adds a `shared with`
block per sender:

```
  shared with Ola Nordmann · their trip:2026-06-12:2026-06-13 · 2 nights · received 2026-06-20 · 2 photos
    who            yours                 theirs                             seen only by
    you            owner                 confirmed (calendar)
    Ola Nordmann   confirmed (calendar)  owner
    Kari Nordmann  –                     confirmed (calendar, note, photo)  Ola Nordmann
    where            theirs                             seen only by
    Cabin, 2 nights  Hytta, 2 nights
    –                60.8700,8.5701 near Hytta, 1.5 km  Ola Nordmann
```

- **who**: `you` and your confirmed people on one side, the sender and their confirmed people on the
  other. A person of theirs is yours when one of their refs is one of your own identities (then they
  are `you`) or resolves in your record to someone confirmed here; else when the names match, case
  aside. Ola matched Ines's own `Ola Nordmann` through his address; Kari is in Ola's calendar, note
  and a tagged photo, and in nothing of Ines's.
- **where**: each stay of your route with the sender's stays within 300 m of it beside it — the cabin
  Ines calls *Cabin* is the one Ola calls *Hytta* — and, apart, the stays of theirs that match none of
  yours: the bakery Ola walked to on the Saturday.
- **seen only by**: `you`, the sender's name, or nothing when both records have it.

Under `--json` the same is `shared`, one object per sender with `from`, `bundle_id`, `received_at`,
`logbook_head`, `trip`, `people` (`name`, `person`, `yours`, `theirs`, `seen_only_by`), `places`
(`label`, `nights`, `theirs`, `their_nights`, `seen_only_by`, `lat`, `lon`), `flights` and `photos`.
The HTML page has a *Shared* section with the same two tables.

The page compares; it confirms nobody. A person seen only by the sender stays theirs until you say
otherwise in your own record, and nothing is written when the page is read. What a received page is,
in your chain, is the fact that the sender's record said this at that head, with the package digest
to show for it.

## The fixture

`tests/cabin.py` builds the two records the tests and this page use: Ines's and Ola's weekend at a
cabin, 12 to 14 June 2026, with Ola's bakery walk, Kari in his calendar and his note, one photo shared
between the two libraries under one asset id, and one photo whose bytes are in his store. Every
coordinate, address and id is invented; nobody in it exists.
