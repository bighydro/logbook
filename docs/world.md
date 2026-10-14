# The world

`logbook export world` draws the record as one page: a globe you can scrub. The world's outline, the
places you have named as anchors, your boat and your aircraft as dots moving along their own tracks, your
stays as dots, your journeys as tracks, and at the bottom a time scrubber that moves all of it. It is not
3D and needs no graphics card: a canvas, one script, one file. The [Library](serve.md) serves the same
page at `/world`.

```bash
logbook export world                                   # <root>/export/world/world.html, the whole record
logbook export world --out ~/World                     # ~/World/world.html
logbook export world --from 2026-06-01 --to 2026-08-31  # one summer
logbook export world --tier 1                          # where you were and how you moved, nothing you wrote
open ~/World/world.html                                # any browser, from the disk, offline
```

## What the page shows

- **The outline.** Natural Earth's 1:110m land polygons, drawn on an orthographic globe. Drag to turn it,
  scroll (or `+` and `−`) to zoom down to a marina, *fit* frames what the record holds, *globe* shows the
  whole hemisphere. At the 1:110m scale a fjord is not water; the anchors and the tracks are as precise as
  the record, the coast is not.
- **The anchors.** Every place in `places.json`, a ring the size of its radius and its name.
- **The assets.** Every asset of `assets.json` (ADR 0018), and any other `subject` the record's lines name
  under its own id: a dot where its track puts it at the scrubber's time, the last hours of the track drawn
  behind it, the whole track faint. Between two fixes the dot moves along the line between them; after a
  silence of twelve hours (more on a thinned track) it is drawn hollow at its last fix, "not seen" until
  the next.
- **Your stays.** Every stay of the stays reader, folded as the Day folds them: a run aboard is one stay
  aboard. A stay already over is a solid dot, one still to come a faint one; a night's stay is larger. Your
  own dot is the stay you were in at that minute, between two stays it moves from one to the next, and
  aboard it rides with the boat: the boat's dot is ringed and named "you aboard".
- **Your journeys.** Every standing `journey/v1` (and `trip/v1`) line, RFC 0020: a passage of the deck log
  along its route, a ride or a train from one end to the other, a parking as a square. One still to come is
  dashed, one under way is drawn as far as it has come, one done is a line.
- **The chapters.** When the record holds `chapter/v1` lines (RFC 0036), each standing chapter is a band on
  the scrubber over the days it covers, named, and the line above the globe says which chapter the
  scrubber is in. A chapter named after its stretch began still shows: chapters are read from the whole
  record.

Above the globe: the window, the tiers, the zone, how many lines were held back, and the scrubber's time
as a sentence: `Fri, 10 Jul 2026 19:12 · chapter Sommer på sjøen · aboard Havbris`. The scrubber takes
the arrow keys (an hour; a day with Shift, or Page Up and Page Down); *play* runs the window in forty
seconds. Times are in the record's zone (`logbook.json`); a browser that does not know that zone shows
UTC and says so, and never another zone.

## A place's or an asset's summary

Click an anchor or an asset (or its name in the list on the left) and its summary opens, counted from the
whole window as `logbook show place` and `show asset` count:

| | a place | an asset |
|---|---|---|
| nights | the nights whose stay lay at the place (aboard, the stay the boat lay at) | the nights aboard it |
| journeys | the journeys that start or end there: by the name the line gives, or by a position inside the place's radius | the journeys whose `subject` it is |
| photos | the photos taken during one of your stays at the place | the photos taken while you were aboard, a passage included |
| visits / fixes | the first and the last day of a stay there | the first and the last day of a fix |

An asset's summary also gives its identifiers (`mmsi`, `icao24`, `registration`) and where it is at the
scrubber's time; a place's its position and radius.

## Everything is in the page

The page is one HTML file and fetches nothing. Inside it are three blocks: the record's JSON, the land
table and the script. No URL is in the page: no font, no image, no tile server, no geocoder, no
stylesheet or script from anywhere. The file carries a Content-Security-Policy (`default-src 'none'`,
the one script allowed by its SHA-256) so the browser holds it to that even if a payload carried markup
(every value is escaped, and the page writes text, never markup). The Library sends the same policy as a
header. The test suite reads every attribute that can hold a URL, runs the export with every socket
refused, and passes the page through the synthetic check the published site is held to.

**The land table** is `logbook/tables/land.json`: Natural Earth's 1:110m land (`ne_110m_land`), which
is in the public domain, every polygon kept and each coordinate rounded to a hundredth of a degree and
delta-encoded, 36 KB. Its cap is 48 KiB (`world.LAND_BYTES`). `scripts/make_land.py` writes it from the
GeoJSON file, read from disk; nothing in the package or its build fetches it.

**The record's JSON** is at most 1,000,000 bytes (`world.CAP_BYTES`), so the whole page stays under about
1.1 MB. A track is drawn at one fix per five minutes at most: a fix is kept when the asset has moved 100 m
since the last one kept, every six hours when it has not, and at both ends of a silence. When the record
does not fit, the tracks are thinned first (a fix per ten minutes, twenty, … one a day), then the stays
shorter than one, three, six and twelve hours are left out, a night's never. The counts are never thinned:
a summary says the same at any thinning. A window that still does not fit is refused, naming `--from` and
`--to`, and nothing is written. The console says how many fixes were drawn and what was thinned.

**Every id it names is in it.** A stay names its place and the asset it was aboard, a journey its asset
and its places, the summaries every place and asset; before the page is written, `world.validate` checks
each one, and a page that refers to anything it does not hold is never written.

**No coordinate is more precise than the record's own.** A place is as `places.json` spells it, a fix and
a journey's route as their line does, to five decimals at most (about a metre). A stay's centre is
computed by the stays reader; it is written to the fewest decimals any of your fixes inside the stay
carries, and to four at most, the precision of the stay's own id. A tracker that writes three decimals
gives stays at three.

## The gate (ADR 0016)

The record is read through the gate, a year at a time (`reading.read(..., tiers)`): a line whose tier is
not asked for is not a stay, not a track, not a journey, not a band, not a count. The default is tiers 1
and 2: where you were and how you moved (tier 1), and the chapters and the notes that make a stay a stay
(tier 2). A journey with a price is tier 3 (RFC 0020) and is in no default page; nor is health or money,
which the page does not draw at any tier.

The ceiling is the `world` entry of `policy/crossing.json`, 2 when the file does not name it. `--tier
1,2,3` needs the entry raised, and prints the tier-3 warning a crossing prints; an entry lowered to 1
makes tier 1 the default and refuses `--tier 1,2`, naming the file:

```json
{"hermes": {"max_tier": 2}, "mcp": {"max_tier": 1}, "world": {"max_tier": 3}}
```

An entry may carry an `until` day, as every entry may (ADR 0022); past it, nothing crosses to the page.

## The record shows it left (RFC 0011)

Every export appends one `crossing/v1` line with the destination `world`: the window as instants, the
tiers, the counts (lines logged, crossed and held back, by tier and by kind), the ceiling in force, the
head before the line, and `package_sha256`, the digest of the folder as a vault's is digested
(`<sha256 of the page>  world.html`, hashed). Under `extra.world`: the page's bytes, the JSON's, how many
places, assets, stays, journeys and chapters it holds, and the thinning. Nothing else is written to the
record, and that one write goes through `Logbook.append`. The Library's `/world` appends nothing: nothing
leaves the machine.

The page is a function of the record's lines and settings alone: no head, no clock. A re-run over an
unchanged record writes the same bytes, and the file is not rewritten (`(unchanged)` in the console).

## In the Library

`logbook serve` answers `/world` with the page `export world` writes by default — the same request, the
same JSON, the same script — under the Library's navigation, with the policy in the header rather than in
the page. `/world?from=2026-07-01&to=2026-07-31` narrows it. Like every page of the record, it carries an
`ETag` and a reload at the same head is a `304`.

## What it is not

It is not a map service: there are no tiles, and the outline is coarse on purpose. It is not 3D: the globe
is a projection on a canvas. It is not a reader of the record for other software: the day package and the
crossing package are that. And it is not a place to publish a real record without thinking: a tier-1 page
still says where you slept every night.
