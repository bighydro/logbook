# Places

A place is a name for a spot you return to: home, the office, a cabin, a berth. The record keeps them
in `places.json` in the record folder, a setting beside the chain like `assets.json`: a place is never a
line, and renaming one changes no line. What the chain holds is the naming itself, one `note/v1` line
per place you name ("named 55.6000,4.4000 as Hytta på banken"), so the record says when you gave it.

```json
{"Home": {"lat": 59.9139, "lon": 10.7522, "radius_m": 120, "kind": "home", "tags": ["family"]}}
```

`kind` is `home`, `asset-berth` or `other`; a night is at home when its stay lies in a place of kind
`home`. `radius_m` is how far from the centre a point still counts as there (150 m when left out).
Every reader reads the file each time it runs: the Day, `day`, `serve`, `show days`, the trips, the
rollups. A stay inside a named place prints its name; one outside prints its coordinates, `55.6100,4.4000
near Hytta på banken, 1.1 km`. Name a place and the next page you open says it.

| Command | What it does |
|---|---|
| `logbook setup places list` | one line per place |
| `logbook setup places add NAME --lat --lon [--radius M] [--kind] [--tags]` | add one, by hand; appends nothing |
| `logbook setup places name LAT,LON NAME` | add one and put the naming in the record |
| `logbook setup places propose` | your unnamed stays grouped and ranked by hours, with what is near; `--write` asks for a name for each |
| `logbook setup places review` | the places you return to, each with the name the record already holds for it, to accept, name or reject (below) |
| `logbook setup places import-takeout PATH` | Google Maps' saved and starred places as entries, written only with `--write` |

`logbook places …` still works for each of these, with one line saying the new name.

## Review

You have years of points and a dozen named places, so most of your days print coordinates. `review`
lets you name the places you return to in one sitting, from what the record already knows about each.

```
$ logbook setup places review
12 places observed · 0 named · 12 to review, by nights then hours
   1  55.6000,4.4000 · 6 visits · 6 nights · 91.5 h · 2026-02-02 – 2026-02-14 → Hytta på banken
          google-takeout timeline: "Hytta på banken" (3 visits) · google-takeout timeline: "Home" (3 visits, type) · immich: "Nordsjøen" (1 photo, city)
   2  55.6000,4.4180 · 3 visits · 3 nights · 48.0 h · 2026-02-04 – 2026-02-13 → Verkstedet
          google-takeout timeline: "Verkstedet" (2 visits)
   3  55.6000,4.4360 · 2 visits · 2 nights · 30.5 h · 2026-02-07 – 2026-02-12 → ____
          no source names it
   …
nothing written: `setup places review --accept N[,N]`, `--name N "…"`, or `--reject N[,N]`
```

(A synthetic record at sea; nobody lives at those coordinates.)

### Observed places

An **observed place** is a cluster of your stays: the same spot within **75 m** (`--radius M` to
change it). Your stays are taken from the longest down; each joins the nearest cluster whose first,
longest stay lies within the radius, or starts a cluster of its own. Each observed place has its
visits (the stays), its nights (the nights whose overnight stay, as the Day picks it, was there), its
first and last visit, its total hours, its centre (the stays' centres weighted by hours), and the names
the record holds for the spot. The queue ranks them by **nights, then hours**: where you sleep comes
first.

The observed places are derived, never stored in the record: a table in the index (`observed_places` in
`index.sqlite`, in your cache directory), built from the lines and kept until the record, `places.json`,
`assets.json` or `policy/stays.json` changes, then built again. Building it reads your track from the
index alone, as `propose` does, and opens only the lines that can carry a name: the Timeline visits,
the photos, the calendar entries, and the first and last point of each stay.

### Where the names come from

Only from lines already in the record. Each name is shown under the source that said it, with how
often:

| Source | What names a spot | Weight a line |
|---|---|---|
| Google Timeline | a place visit of the archive's **Semantic Location History** names the place and its address (`placeVisit.location.name`, else `address`), by its coordinates | 3 |
| | any Timeline visit whose type is home or work (`TYPE_HOME`, `INFERRED_WORK`, `Home`) says `Home` or `Work` | 1 |
| Calendar | the location of a timed entry held during one of the cluster's stays (overlapping it for half its length or more), its first line as you typed it; not an online meeting (a link, Zoom, Teams, Meet, Webex, Skype, FaceTime), not one whose own coordinates are more than 1 km away, not an all-day entry, not a cancelled one | 3 |
| Photos | the place the photo's library named: Photos' area name or address (`extra.place`, written by `apple-photos`), by the photo's coordinates or, without them, its time | 2 |
| | Immich's city (`exifInfo.city`, written by `immich` as `extra.place.city`) | 1 |
| Dawarich | the place Dawarich's own reverse geocoder wrote on the first and last point of a stay (`name`, else street and number), once per stay | 2 |

A name with coordinates names the observed place nearest them within 150 m, one you were at that hour
first. The proposal's name is the one with the most weight; a name already in `places.json`, or one you
rejected for that spot, is passed over for the next. Where no source names a spot, the proposal is a
blank (`____`) for you to fill.

The phones' own Timeline exports (Android's `Timeline.json`, the iPhone's `location-history.json`)
carry Google's place id and a type for each visit, never a name: they give `Home` and `Work` at most.
The names are in the Semantic Location History of a Takeout archive downloaded before Google moved
Timeline onto the phone ([the export steps](adapters/takeout.md#location-history-and-the-timeline)).
A location shared in iMessage or WhatsApp would name a spot too, but neither adapter keeps a shared
location's coordinates yet, so none is read.

### Nothing is looked up

**No coordinate leaves your machine, and no geocoder is ever asked — not an online one, not an offline
one.** `review` reads the record and writes `places.json`; it opens no connection, and the tests hold it
to that with the network guard on. A spot has a name here only when a source already wrote one into a
line: Google's when you exported your Timeline, your calendar's when you typed it, your photo library's
when it named the picture on your phone or your Immich server, Dawarich's when your own server
geocoded the point. Everything else is a blank, and the name is yours to give.

### Your say

Nothing is accepted on its own.

```bash
logbook setup places review --accept 1,2           # the names proposed, as they are
logbook setup places review --name 3 "Base"         # your own name for proposal 3
logbook setup places review --reject 4              # never propose that name for that spot again
logbook setup places review --near Home --top 10    # the ten first within 5 km of Home (or of lat,lon)
logbook setup places review --json                  # the queue, with the evidence and its line ids
```

- **Accept** writes the place into `places.json`: the observed place's centre, a fitted radius (below),
  kind `other` — change it with an editor or `setup places add` if it is a home or a berth — and puts the
  naming in the record as `setup places name` does, one `note/v1` line.
- **Name** is accept with your own words.
- **Reject** records the pair — the spot and the name proposed, or the blank — in
  `state/places-review.json` beside the record, never as a line. That name is not proposed for that
  spot again; reject a blank and the spot stays out of the queue until a source names it. The file is
  bookkeeping, as the rest of `state/` is: a backup leaves it out, and deleting it brings every rejected
  pair back.

The numbers are the queue's as `review` prints it, also with `--near` and `--top`; every number in one
command is checked before anything is written, and after a write the queue is numbered again. On a
terminal, `review` asks for each proposal shown: `y` accepts the name, `n` rejects it, anything else is
the name to give it, Enter skips, `q` stops. Each answer is written at once.

### The fitted radius

The radius an accepted place gets is the distance from its centre within which 95% of its hours were
spent, plus 75 m for the scatter of one stay's own fixes, rounded up to 5 m, between 75 and 300 m. When
that circle would reach into a place you have named already, it is drawn back to that place's edge,
never below 50 m; a spot whose centre lies inside a named place is that place already, and is not
proposed. `--json` shows the radius each proposal would get.
