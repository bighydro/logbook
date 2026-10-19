### Fixed
- The Library (`logbook serve`) on a record of millions of lines: a page asked again at the same head
  is answered from what the server kept (warm, under a second on every page), and the pages that read
  the whole record read it once per head for all of them. A night is found by bisection over the
  owner's stays instead of every stay once a day (the People pages, the World, Trips and Journeys); the
  people review compares only the pairs that share an address, a number or a name word; the Promises
  and Agents shelves stream the messages instead of holding them all. The pages are the same, byte for
  byte. `scripts/bench_library.py` measures every route on a synthetic record of millions of lines.
- `index.sqlite` gains an index on a line's id and one on the lines that supersede another; an index
  built before them is given them when it is next opened.
