### Added
- `logbook export site` writes a Day page for each of the Year's twelve picks, `days/<day>.html`: `serve`'s
  Day page written down with every toggle open, nothing to submit, the site's navigation above it. The
  pick's row in the Days index links its page; any other day stays a row, which a Day page's neighbours
  link. About twelve pages a year, never one per day. The site's pages in `serve`'s stylesheet, the Day
  page among them, need no sideways scroll on a phone: a table wider than the column scrolls inside itself.

### Docs
- The demo site, [bighydro.github.io/logbook/ines/](https://bighydro.github.io/logbook/ines/), is exported
  at tier 2: Ines Nordmann does not exist, so her notes and messages are shown. The docs workflow writes
  the `site` entry into the demo record's `policy/crossing.json` and runs `export site --tier 1,2`; her
  health and money, tier 3, never go to a site. One of her days is the way in, at the same path on every
  build: [days/2025-06-14.html](https://bighydro.github.io/logbook/ines/days/2025-06-14.html), a night at
  the cabin with Ola. `docs/site.md` and `docs/demo.md` say so.
