### Added
- Search in the Library: `/search?q=…` in `logbook serve`, under **search** in the navigation, finds
  the record's words through the function `logbook search` calls and holds every hit to the page's
  tier gate. Each hit shows its day (a link to the Day), its kind, an excerpt with the match marked
  and its line's id (a link to `/line/ID`). The filters by kind and year and the pages of fifty are
  links, never state in the browser. An empty query is the form alone; a query with no hit says so in
  one sentence. A GET form only: nothing written, no script, nothing fetched, phone width first
  ([search](docs/search.md#in-the-library)).
