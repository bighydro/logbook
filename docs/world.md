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
logbook export world --style chart                     # world-chart.html: the record on a period chart
logbook export world --style chart --journey trip:2026-07-10:2026-07-11   # one page of one journey
```

[The chart](#the-chart), below, draws the same record on paper: Mercator's sea chart drawn on the canvas,
or your own scanned chart.

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
and 2, as far as the ceiling goes: where you were and how you moved (tier 1), and the chapters and the
notes that make a stay a stay (tier 2). A journey with a price is tier 3 (RFC 0020) and is in no default page; nor is health or money,
which the page does not draw at any tier.

The ceiling is the `world` entry of `policy/crossing.json`, and 1 when the file does not name it: the
page is one you hand to people, so it fails closed, and without the entry it shows where you were and
nothing more (`logbook doctor` says so on its `world` line). `{"world": {"max_tier": 2}}` adds the
chapters; `--tier 1,2,3` needs the entry raised to 3, and prints the tier-3 warning a crossing prints;
`--tier 1,2` without an entry of 2 is refused, naming the file:

```json
{"hermes": {"max_tier": 2}, "mcp": {"max_tier": 1}, "world": {"max_tier": 3}}
```

You write each entry yourself; a new record names only `mcp`, at 1. An entry may carry an `until` day, as
every entry may (ADR 0022); past it, nothing crosses to the page.

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

## The chart

A logbook is a ship's instrument, and the record drawn on a chart is what a logbook always looked like.
`--style chart` draws the page on paper instead of the globe, beside it in the same folder
(`world-chart.html`), with the same scrubber, the same summaries, the same gate and the same JSON:

```bash
logbook export world --style chart                     # Mercator's chart, drawn: no image in it
logbook export world --chart ~/Charts/oslofjord.png \
  --control-points ~/Charts/oslofjord.json \
  --chart-credit "my scan of a chart in the public domain"   # your own chart as the paper
logbook export world --style chart --journey trip:2026-07-10:2026-07-11  # one page per journey
```

Two rules hold on it, whatever the paper. **The chart is paper, the track is evidence.** The record's
JSON in a chart page is the globe's, byte for byte (the test suite compares them): every position as
the record has it, every minute as the record has it. The script draws a position where the paper puts
it and nowhere else. An asset's track is the straight segments between its own fixes (on Mercator's
chart that is the rhumb line a navigator lays off between two fixes), never smoothed, broken at a
silence, never displaced to look drawn by hand. An asset is at its last fix, never slid between two (the
globe slides it; the chart does not), and its summary says that fix and when. Between two of your stays
the chart draws no position for you: the record has the stays, not the way between them. A day mark is
a bar across a journey at a recorded position — the first fix of each of the record's days on the
journey's own asset's track (at or after the journey's start), and the journey's two ends where its line
puts them — and its date is the record's day of that fix or that end, as the record's zone and
`day_start` cut it. The export works the dates out from the record's own instants and writes them into
the page: never from the page's minutes, which are rounded (a fix half a minute before midnight is on the
day it was taken), and never from the browser's clock, so a browser that does not know the zone still
writes the record's dates (the clock under the scrubber says UTC then, as the globe's does). A night's
stay is written with its first day on the page. **Nothing is fetched.** The paper is drawn on the canvas or carried in the page
(below); the names and dates are in the system's serif, since a bundled font would have had to be
fetched to be vendored, and nothing is.

### The drawn chart

Mercator's projection (north up, a rhumb line straight), on sepia paper: the coasts of the same land
table as the globe (Natural Earth's 1:110m land, public domain), hachured on the land side, the
graticule engraved at a step the zoom has room for, degrees and minutes in a graduated border (the
latitude cells widen towards the pole, as Mercator's do), and a compass rose with its thirty-two rhumb
lines across the chart. Your stays are pricked positions — the prick and the ring a navigator draws
round a fix, a night's larger and written with its day — your journeys dashed tracks in red ink with
their day marks, your assets' tracks in ink (what each had sailed by the scrubber's time dark, the rest
faint) with the asset's name written along the leg that brought it to its last fix, and your named
places ringed and named. The legend, folded to one line at the foot, names the chart's source. Drag to
move the chart, scroll (or `+` and `−`) to zoom, *fit* frames the record, *chart* shows the world. The
paper is paper: in a dark room it stays light. At 1:110m a fjord is still land; the coast is as coarse
as the globe's, the record as precise as itself.

### Your own chart

`--chart FILE` makes your own chart the paper: a PNG or a JPEG on your disk — a scan of a chart in the
public domain, or one you own — read once, never fetched, never looked up. Three more things go with it:

- **`--control-points FILE`**, a small JSON of three or more pixels of the image tied to positions, the
  pixels counted from the top-left corner of the file as you give it (`x` to the right, `y` down), best
  at crossings of the chart's own graticule, spread over it; a point's `name` (at most 80 characters)
  is how the corner and the console call it:

  ```json
  {"points": [
    {"name": "59°40′ N 10°33′ E", "x": 212.5, "y": 1648.0, "lat": 59.6667, "lon": 10.55},
    {"name": "59°40′ N 10°45′ E", "x": 1530.0, "y": 1702.5, "lat": 59.6667, "lon": 10.75},
    {"name": "59°55′ N 10°45′ E", "x": 1612.0, "y": 252.0, "lat": 59.9167, "lon": 10.75},
    {"name": "59°55′ N 10°33′ E", "x": 296.0, "y": 198.5, "lat": 59.9167, "lon": 10.55}
  ]}
  ```

- **`--chart-credit "…"`**, the chart's source in your words, which the legend writes as you give it.
  Nothing is read from the file to credit it.

**The fit.** The positions are taken to Mercator's plane, as a sea chart is drawn (on a chart of a few
degrees any projection is that close to it), and the transform from the plane to the image's pixels is
the simplest one your points check:

| points | the transform | checked |
|---|---|---|
| 3 | affine, through them exactly | no: three points fit an affine transform whatever they say. The corner and the console say *unchecked* |
| 4 or more | affine by least squares: a scan, turned, scaled, sheared | yes |
| 6 or more, when the affine one does not hold | projective by least squares: a chart photographed at an angle | yes |

Each point's **residual** is how far the fit of the *other* points puts it from the pixel you gave
(leave one out). A fit whose worst residual is more than **1 % of the image's diagonal**
(`chart_fit.RESIDUAL_LIMIT`; 36 px on a 3000 × 2000 scan) is refused, naming the point the others place
worst and listing every residual, and nothing is written or appended. One wrong point raises the
others' residuals too — the point named is not always the wrong one — so check them all. A latitude mistyped by a few hundredths of a degree is caught that way, and so is a
chart drawn in a projection the track cannot honestly be laid on. Refused too, whatever the residuals:
points nearly in a line, points that make a mirror image of the chart (a latitude and a longitude
swapped, or `y` measured up from the bottom edge), and a projective transform whose horizon crosses the
image. A projective transform is never
fitted through four or five points: it has eight parameters, so the fit of the others would pass
through them exactly — a check of nothing — and bend the chart to every error of a click. A thin-plate
spline is not offered for the same reason: it passes through every point whatever the point says and
bends the track towards it, which the track may never be. One transform takes every position of the
record to the image: the track is laid on the chart, the chart is not laid on the track.

**Where the check holds.** The residuals vouch for the fit inside the control points' spread (the
smallest polygon round them). Beyond it a position is placed by extrapolation, which no residual checks:
a chart photographed at an angle, its points bunched in the middle, can pass the check and still put a
position at its far corner well off. Spread the points over the part of the chart the record crosses;
the corner and the console count the positions that lie beyond the spread.

On the page the image is the paper (the globe's coasts are not drawn on it, nor the rose: your chart
has its own), the control points are crosses with their names, and the fit sits in a corner: its kind,
each point's residual in pixels and as a share of the diagonal, the limit, and how many positions lie
beyond the points' spread. The console prints the fit's kind, its worst residual and the limit, how many
positions lie beyond the spread, and how many fall off the chart (they are drawn where the fit puts them,
on no paper; beyond a projective fit's horizon, not at all).

**Only the picture crosses.** An image file carries more than its pixels: a phone's photograph of a
paper chart says where and when it was taken and with what. None of it reaches the page. A PNG keeps the
chunks that draw it (`IHDR`, `PLTE`, `tRNS`, `gAMA`, `cHRM`, `sRGB`, `IDAT`, `IEND`), a JPEG the segments
that decode it (the frame, the tables, the scans, Adobe's colour marker): EXIF and XMP, text chunks,
comments, colour profiles and anything after the image's end (a second picture, a gain map) are left
out, and the console names what was. An image stored turned or mirrored (an EXIF orientation other than
1) is refused: you measured the control points on the picture as a viewer turns it, and without its
EXIF the page would not. Save it upright and measure on that.

**The cap.** The image is carried in the page as base64 in a data block, at most 4 MiB
(`chart_image.IMAGE_BYTES`) and 40 megapixels (`IMAGE_PIXELS`), and the script makes a picture of it with
`createImageBitmap`, so the page's policy stays `default-src 'none'` with its one script by its hash —
no `data:` URL, no `img-src`. A PNG over the cap is **downscaled by the export**: by a whole factor
(2, 3, …, the smallest that fits), each block of pixels averaged, written again as a PNG, lossless. Your
control points stay in the pixels of the file you gave; the page draws each pixel of the smaller picture
as that many of yours, so the fit is unchanged. It takes a while on a large scan: the standard library,
no image library, a row at a time (some ten seconds for a six-megapixel scan where it was measured, more
for one whose rows are filtered by Paeth). An interlaced PNG over the cap is refused: save it without
interlacing. A JPEG is never decoded or re-encoded — the
standard library has no JPEG codec — so a JPEG over the cap is refused, saying about how wide to save
it; measure the points on the smaller file, or give a PNG. A whole chart page is at most 7 MiB
(`world_chart.PAGE_BYTES`): the record's JSON (1,000,000 bytes at most), the land table, the largest
image as base64 and the page around them fit under it with room, and a page that would not is refused.

### One page per journey

`--journey ID` makes the page of one journey, in either style, under its own name so that no page
overwrites another:

- **a trip**, as `logbook show trips` prints it, `trip:FIRST:LAST`, or any day inside it (as `show trip`
  takes it): the page covers its days to the return day and draws every journey line of them. The trip
  is found through the same gate as the page. File: `world-trip-FIRST-LAST.html`
  (`world-trip-FIRST-LAST-chart.html` with `--style chart`).
- **one journey line**, by the id of its `journey/v1` (or `trip/v1`) line — a passage of the deck log, a
  ride: the page covers the local days from its `at` to its `end` and draws that line alone. One above
  the tiers asked for, retracted, superseded or cancelled is refused. File: `world-journey-ID.html`
  (`…-chart.html`).

`--journey` again for another page; every page is built before any is written. `--journey` sets the
page's days, so it does not go with `--from` and `--to`.

**What the line says.** Each page appends its own `crossing/v1` line, as every export does. A chart's or
a journey's line carries under `extra.world` what the globe's does not: `style`, `journey` (the id as
given), and for your own chart `chart` — its credit in your words, the digest, bytes and type of the
image as the page carries it, how far it was downscaled, the fit's kind, its number of points, its worst
residual, and how many positions fell off the chart (`outside`) or beyond the points' spread
(`beyond_spread`). The globe's line of a window is as it was.

The Library's `/world` stays the globe.

## What it is not

It is not a map service: there are no tiles, and the outline is coarse on purpose. The chart is not a
georeferencing tool: it lays the record on your chart, and refuses a chart it cannot lay it on honestly. It is not 3D: the globe
is a projection on a canvas. It is not a reader of the record for other software: the day package and the
crossing package are that. And it is not a place to publish a real record without thinking: a tier-1 page
still says where you slept every night.
