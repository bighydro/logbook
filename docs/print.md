# On paper

`logbook year YYYY --html PATH --print` and `logbook trip ID --html PATH --print` write the paper
edition of a Year or a Trip: one HTML document designed for A4 and US Letter, laid out with CSS
paged media, that a browser turns into a PDF or sends to a printer. It is a reader (ADR 0013): a
function of the record at its head, derived every time, never written back.

```bash
logbook year 2026 --html ~/2026.html --print                        # the year: a cover, contents, a spread a month
logbook trip trip:2026-06-15:2026-06-20 --html ~/week.html --print  # one trip: a spread a day; the id as `trips --json` gives it
logbook trip 2026-06-17 --html ~/week.html --print                  # the same trip, named by a day inside it
```

Without `--print`, `--html` writes the screen page the Year and the Trip already had: every table,
the twelve picks, the route with its map. `--print` is the book: fewer facts, set for paper, with
the keepers as hero photos. `--print` needs `--html PATH`; alone it exits 2 and says so.

## What is on the pages

1. **The cover**: the owner's name, the year or the trip's dates, the dates the record covers.
   The name is the first entry of `names` in `policy/owner.json`; without one, the label a
   resolution line gives one of the owner's addresses; without that, the first owner email of
   `logbook.json`. Nothing is guessed from an address.
2. **Contents**: the months of the year with their days, nights away, flights and keepers, and
   the year's trips; or the days of the trip with the night each ended at, its flights, who was
   there and its keepers. A trip then has its **route** on a page of its own: the trip page's map
   (one path per leg, one mark per stay) and the stays under it.
3. **One spread per month** of the year, or **per day** of the trip. The first page of a spread
   is the facts: the nights (home, away, in transit, aboard each asset), the places by nights
   numbered to the map, who was there — the people **confirmed** present by the with module, never
   a proposal from a face or an all-day entry — the flights, the sleep and the steps when the
   record has health lines, the keepers by lane. Beside them the **map**: the track of the span
   drawn as an inline SVG from the location lines themselves, the owner's and, while aboard, the
   asset's, with the places marked and numbered and a scale bar; an equirectangular projection,
   no tiles, nothing fetched. The second page is the **keepers** (RFC 0024) as hero photos sized
   to the page, memory first then art: one photo takes the page, two are stacked, three or four
   are two by two, more are two by three and run on to another page. A month or a day with no
   keepers has its facts page and no photo page, and lays out the same.
4. **The colophon**: the head the record was read at.

Page numbers come from the page counter and sit in the bottom margin; the cover has none.

## Photos are referenced, never copied

A keeper points at a `photo/v1` line, and the document points at that photo's pixels where they
are: at the attachment under the record's `attachments/` folder when the record stores them (a
SPEC §1.1 reference under `content` or `attachment` in the photo line), else at the original path
the library wrote in the line (`path` or `original_path`, at the payload's top or under `extra`,
as the Immich adapter keeps it), as a file URL when that path is absolute. A photo the record
only names gets a frame with its name in the same place, so the page lays out whether or not the
file is there — the synthetic demo record names its photos and stores none, so its fixtures are
all frames.

Two consequences. The document is one file, but the photos are not in it: move it to another
machine and the frames are empty until the record comes too. And a browser shows what it can
decode: Safari renders HEIC, Chromium and Firefox do not, so a library of HEIC originals prints
with its frames empty in Chromium. An adapter that stores a JPEG rendition as the attachment
prints everywhere.

## Making a PDF

The document is plain HTML with one inline stylesheet, no script and nothing loaded from
anywhere, so any browser prints it. The stylesheet sets the page's own margins, so leave the
browser's at their default (or none) and keep background graphics on, else the photo frames and
the map's border are dropped.

**In a browser.** Open the file, print, choose *Save as PDF*, the paper (A4 or Letter — the
layout fits both), and turn headers and footers off: the page numbers are the document's own.
Chromium and Safari lay out `@page` margin boxes; Firefox does not yet, so a PDF from Firefox has
no page numbers.

**Headless Chromium**, for a script or a cron job:

```bash
chromium --headless --no-pdf-header-footer --print-to-pdf=2026.pdf file:///Users/ines/2026.html
```

On a Mac the binary is `/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome`; with
Playwright installed, `playwright` ships one too. The paper is the browser's default (Letter in
the US locale, A4 elsewhere); `--print-to-pdf` has no paper flag, so to pin one set `PAGE_SIZE`
below, or print from the browser and choose it there.

## The paper, and retheming

The layout fits both papers: the text block is set for the narrower width (A4's 210 mm) and the
shorter height (Letter's 279.4 mm), so one document prints on either without a cut or a reflow,
and the sheets differ only in their outer margins. `@page { size: auto }` leaves the paper to the
printer.

Every typographic constant — the margins, the text block, the six-column grid, the type scale (a
major third from 10 pt), the faces (the system's: a document that fetches nothing carries no
webfont), the ink, the map's box, the photo heights per layout — is in one module,
[`logbook/print_layout.py`](https://github.com/bighydro/logbook/blob/main/logbook/print_layout.py),
whose `stylesheet()` builds the one stylesheet from them. A designer retheming the paper edition
changes that file and touches no logic: the renderer (`logbook/print_page.py`) names classes and
never a length.

## The fixtures

`tests/fixtures/demo/print_year_2026.html` and `print_trip_2026-06-15.html` are the documents
the demo record of thirty days with seed 7 gives for 2026 and for its yacht week, pinned byte for
byte by `tests/test_print_page.py`, which also checks every document structurally — every tag
closed in order, one stylesheet, no script, no link, every `src` an `img`'s, every `img` with
`alt`, nothing from the network — and that a day with no photos still lays out. After a change to
the renderer or the layout that is meant, `uv run python scripts/make_print_fixtures.py` writes
them again. Open either fixture in a browser to see the page; nothing in them is real.
