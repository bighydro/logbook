### Fixed
- A sealed record keeps no reading of its tier 2–3 lines in plain text on this disk: the readings kept
  beside the index, the review pages' tables of observed people, orgs, ideas, assets and places, and the
  Library's built pages stay in the process's memory instead, and what an earlier version left there is
  removed. `logbook serve --built` renders every page live on a sealed record, to its end, and says why;
  `serve --build` refuses in one sentence, and the 06:00 close says the build is off.
  `"plaintext_cache": true` in `logbook.json` keeps them on disk as before, `0600` in the cache folder;
  off by default. The index's own columns stay as RFC 0029 §8 has them ([sealing](docs/sealing.md);
  RFC 0047 §15).
