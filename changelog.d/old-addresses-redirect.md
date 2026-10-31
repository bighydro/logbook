### Changed
- Every Library address from before the doors leads to its door (RFC 0047 §9): `/days?from=&to=` opens
  Life at those days (a whole year of them, Life at that year), `/trips?year=` and `/journeys?year=` Life at
  that year, `/goals` Life, `/world?from=&to=` Places at that year and `/search?q=` Ask with the same words,
  each with a 302 for this release and a 301 from the next. A value the door would refuse is a 404; a form
  still posts where it always did, and every other address answers as before. `docs/serve.md` lists them all.
