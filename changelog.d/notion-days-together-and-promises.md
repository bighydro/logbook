### Fixed
- `export notion`: a person's "Tage zusammen" names the first and last day that person appears in the
  record (`Tage zusammen: 12 (im Logbuch vom 03.05.2019 bis 14.09.2026)`), no longer the window's first
  day on every page, and is left off the page of someone with no day together instead of saying 0. The
  facts carry it as `appears`, `{first, last}`.
- `export notion`: a person's promises are the ones `promises` reads as yours or theirs (never a request),
  from a message, a mail you wrote, a call or a note, open or kept in the last 365 days; never a line
  quoted in a reply or a chat sent or pasted whole. A page lists the five newest a side, each with its day
  and `offen` or `gehalten am …`, then `… und N weitere`; each fact carries `status` and `kept`. The dry
  run says how many lines the two sections take.
