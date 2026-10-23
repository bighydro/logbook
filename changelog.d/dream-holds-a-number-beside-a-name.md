### Fixed
- A dream's sentence that puts a number beside a person's name is dropped, not only marked: the draft
  keeps its slot as `held: a number beside a name`, unsupported, with the evidence it cited under
  `extra.held` (a day's), so `day`, the Day page and `export site --with-drafts` never print its words.
  A sentence the number rule had already marked is held too. A day's, a month's and a chapter's dream
  (RFC 0043; [the dream](docs/dream.md)).
- `dream day` drops a proposed event whose title, or a proposed link whose text or note, puts a number
  beside a person's name, counted as `a number beside a person`.
