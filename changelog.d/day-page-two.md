### Added
- The Day page of `logbook serve` shows a row's photos as a strip under it, starred first: a thumbnail
  for each photo whose pixels the record's own attachment store holds (`/photo/ID`), the rest
  counted, never a broken image, and nothing fetched from a photo library
  ([In a browser](docs/serve.md#the-day--photos-the-track-the-line-the-week)).
- A photo review at the foot of the Day page: the day's photos with no star, each with *Star* (its
  `memory` keeper) and *Not a keeper*, which stops the review asking and writes no line
  (`state/photo-review.json`); both answer `409` while another command writes, as every act does.
- The Day page draws the day's track from the stays' own coordinates, an inline drawing with no map
  tile; links every row that is a line to `/line/ID`, the line as written, read-only and through
  the page's tier gate; shows the week's draft on its Sunday and links to it from the other six
  days; and says in one sentence under the header what crosses where.
- Many edits of one Drive file read as one row on the Day page, the file's name and what was done to
  it counted (`Budget 2027 · 5 edits, 2 comments`); `logbook day` lists each line as before.
- `logbook with DAY NAME…` and the Day page's *with…* field say who was there on a day no device saw,
  the night the phones were off: the same line from either, and the page says why it saw nobody.

### Fixed
- A portfolio typed in an org's status form comes back typed, in its field, when the form is sent
  again after a busy `409`; it came back hidden.
