### Fixed
- `logbook serve --built` (labs): the rebuild after an act renders every page on a site of its own, so
  it no longer keeps a built page's old bytes again with a second `built hh:mm` in its footer, nor marks
  pages as asked for. A built page older than the record's head (a CLI act, a sync) is still served,
  its footer saying when it was built, and starts one rebuild for that head, however many pages are
  asked for meanwhile.
- The built pages' `pages.json` is written only under `building.lock`, whole and moved into place: the
  server no longer loses the 06:00 close's writes, nor the close the server's; a page an act dropped
  stays dropped until a page that read past the act is written, even when a build begun before the act
  writes the old one back.
- Every built page records the tiers it was built at, and is served only to a request read through
  that same gate; a build through another gate renders every page again.
- A sealed record without `plaintext_cache` keeps no built page through any write of the lab, and a
  record sealed while a build runs keeps nothing that build wrote.
