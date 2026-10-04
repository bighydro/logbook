# The site

`logbook export site <folder> [--tier 1|1,2]` renders the readers as a folder of static HTML: one Year
page per year, every Trip page, a Days index per year, the places and the people, written as plain files
with relative links, one inline stylesheet each, no script, no image, nothing fetched. It is
[`logbook serve`](serve.md) written down — the same renderers, the same text — so the folder reads the
same from a file manager, under any prefix on any web server, or in twenty years. It is an export, not a
reader: it is tier-gated exactly like the vault (tier 1 by default, the shape of the record and no text of
any note or message), and every run appends one `crossing/v1` line to the chain so the record shows it
left. Re-running rewrites only the files whose content changed.

```bash
logbook export site ~/Site                 # every year the record has a line in, tier 1
logbook export site ~/Site --tier 1,2      # notes, transcripts and mail cross too; needs the policy below
open ~/Site/index.html                     # or serve the folder with anything that serves files
```

The demo persona's forty years are published this way, by the docs workflow on every push to `main`:
[bighydro.github.io/logbook/ines/](https://bighydro.github.io/logbook/ines/) is
`logbook demo --years 40 --seed 1` exported at tier 1, so a stranger can browse a life that never happened
without installing anything ([demo.md](demo.md)).

## The folder

```
<folder>/
  index.html                    the root: the years with their days, trips, nights away and people
  years/2026.html               the Year, as `logbook year 2026 --html` writes it, with the site's navigation
  days/2026.html                the Days index: `serve`'s /days table over the year's days the record covers
  trips.html                    every trip of the record, one row each, linked to its page
  trips/trip-2026-06-15-2026-06-17.html   the Trip, as `logbook trip --html` writes it, the map inside
  places.html                   `serve`'s /places table
  people.html                   everyone confirmed present by a line that crosses, by days together
  people/kari-nordmann.html     one per person: the years together, the trips
```

A person's file stem is their name as a slug — lower-case ASCII letters and digits, anything else a dash,
accents dropped (`Zürich café` is `zurich-cafe`, `Bjørn` is `bjorn`) — so it is a URL on any server and a file name on any
platform with nothing to percent-encode; two names that fold to one slug are two pages, the second `-2`.
A trip's is its id with dashes, `trip-<first day>-<last day>`; a year's is the year.

Every link is relative (`../trips/trip-2026-06-15-2026-06-17.html`) and every link resolves to a file in
the folder; the test suite follows each one. There are no Day pages — forty years would be fifteen
thousand of them — so a row of the Days index is an anchor (`days/2026.html#2026-06-13`), not a link, and
the Year's twelve picks render their Days in full as the Year page always has.

## The pages

**The Year** is the page `logbook year --html` writes ([year.md](year.md)): days per country, nights,
the trips (each linked to its page), the flights, the places by nights, the people by days together
(each linked to their page), health and keepers by month, and twelve picks, one day a month, the Day
rendered in full. Above it, the site's navigation: the root, the trips, the places, the people, the
year's Days index, and the years either side.

**The Trip** is the page `logbook trip --html` writes ([trips-shared.md](trips-shared.md) for what it
holds): the route as an inline SVG map, the stays with their nights, the legs, the days from the leaving
day to the return day, the flights in and out, the people confirmed (linked) and proposed, the nights
aboard, the keepers, health and spend. A trip across New Year is one page, found whole from its first
day, though each Year lists its own part of it.

**The Days index** is `serve`'s `/days` table: one row per day the record covers in the year, the night
after, the kilometres moved, the flights, the stays and what attached to them, the people confirmed, the
health line and the usual sources that went quiet. The form and the pager a server offers are not on a
static page; the row's date is its anchor.

**Places** is `serve`'s `/places` table of `places.json`. **People** is a table of everyone a crossing line
confirms present — days, nights, the years, the last contact, the trips — and each person's page lists
the years together with the places shared, and the trips.

## The gate (ADR 0016)

A line is in the site when its tier is in `--tier`, and nowhere otherwise: the readers read the record
through the gate before anything is derived from it (`reading.read(..., tiers)`), so a line the gate holds
back is not a row of a Day, not a night, not a companion, not a count on any page. The default, tier 1,
is the shape of the record: where you were, how you moved, the flights, the calendar entries, the photos
counted, who the calendar confirms present. No text of any note, message, transcript or mail is on a
tier-1 page, and a person a tier-2 note names is on no page until tier 2 crosses. The root page counts
what was held back (`held back: 2,547 lines above tier 1`), and the crossing line records it by tier and
by kind.

The resolution lines — the record's name overlay, a `ref` to an entity — are read whole whatever their
tier, as the vault reads them: the gate is on the line that puts someone somewhere (a calendar entry, a
transcript, a note), never on the line that names them. The MCP server's gate is stricter and holds the
overlay back too; an agent reading a private record and a page the owner publishes are not the same
crossing, and the site follows the export. Health and money are tier 3 and never go to a site;
`--tier 1,2,3` is refused.

How far the gate opens is a setting in the record, not in the code: `policy/crossing.json` maps a
destination to its ceiling, and the site's destination is `site`. A file that does not name it allows
tier 1, so `--tier 1,2` needs one line added:

```json
{"hermes": {"max_tier": 2}, "mcp": {"max_tier": 1}, "site": {"max_tier": 2}}
```

A request above the ceiling is refused naming the file, and nothing is written or appended.

## The record shows it left (RFC 0011)

Every run appends one `crossing/v1` line with the destination `site`, the window as instants (the first
day's local midnight to the midnight after the last), the tiers, the counts (how many lines the record
logged, how many crossed, how many were held back, by tier and by kind), the ceiling in force, the head
before the line, and `package_sha256`: the digest of the folder as written, one line per file —
`<sha256 of its bytes>  <path>` in path order — hashed, as the vault's. Under `extra.site` are the years,
the pages per kind and how many files were written and how many were unchanged. Nothing else is written
to the record, and that one write goes through `Logbook.append`.

## Re-running

Every page is a function of the record's lines and its settings alone: no head (the Year's and the Trip's
footers name none here, since the crossing line a run appends would move it), no timestamp, no counter.
A run compares each page's bytes with what is on disk and writes only the differences; the console says
`92 written, 0 unchanged` the first time and `0 written, 92 unchanged` the next. Nothing is deleted: a
page the record no longer produces stays until you remove it, and a file beside the pages — a `CNAME`, a
`.nojekyll`, your own index — is never touched.

## Publishing it

The folder is static: copy it anywhere that serves files. The project publishes the demo persona under
its own docs site, and the way it does so is the template:

- `.github/workflows/docs.yml` runs on every push to `main`: `logbook demo --years 40 --seed 1`, then
  `logbook export site docs/ines`, then the docs build, which copies the folder as it is to `/ines/` on
  GitHub Pages. No new infrastructure: the same `gh-pages` branch, the same deploy.
- Before the build, `scripts/check_synthetic.py docs/ines` fails the workflow if any page carries an
  identifier outside CONTRIBUTING.md's synthetic allowlist — an email at a domain other than
  `example.org`, a phone number outside `07700 900xxx` and `+47 9000 000x`, a nine-digit number in an
  assigned MMSI range, a URL of any kind — or, when the owner's `~/.config/logbook/pii-patterns` exists,
  anything it names: the scrub rule CONTRIBUTING describes, applied to the rendering rather than the
  diff. It prints `file:line` and a count, never the text.
- The demo only. A real record's site is tier-gated like any export, but publishing it is a decision the
  gate does not make for you: a tier-1 site still says where you slept every night.

## What it is not

It is not `serve`: nothing listens, nothing is read on request, and the pages are as old as the last run.
It is not a reader of the record for other software: the day package (`export --day`) and the crossing
package (`export crossing`) are that, and they carry lines, not prose. It is not a backup: `logbook
backup` is. It renders what the readers derive — a stay, a trip, a companion — and a derivation is
disposable (ADR 0013): rename a place, raise the ceiling, and the next run rewrites the pages that changed.
