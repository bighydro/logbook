### Added
- Ask (`/ask?q=…`, RFC 0047 §4.5, v1): the field at the top of every door now answers with moments, not
  lines. One row a day, each day once and newest first across the pages, with where you spent the night,
  who was with you (names only, each a link to their page) and the words that matched, your own first,
  the match marked and its source (message, mail, call, note …) in pencil, each a link to its row on the
  Day. It searches what `logbook search` searches, held to the page's tier; a hit a later line corrected
  says so, and `?standing=1` leaves it out. `/search` keeps working as it is.
  No number, date or clock touches a person's name anywhere on it, the record's own words in its
  excerpts included.
