### Changed
- `logbook serve` renders every page as it is asked for by default again, with no limit on how long a
  page reads unless `--limit SECONDS` gives one, so the heavy pages (People, a person, the Manifest,
  the World, Promises) answer on a large record instead of *Still reading*. Pages built ahead are a
  lab, `logbook serve --built` (15 s limit, `--limit 0` none); `--live` is still accepted. The 06:00
  close builds the Library only on a machine where `serve --built` or `serve --build` turned it on,
  and otherwise says `library: not built` in one line. docs/serve.md lists what the built pages do
  not do yet.
