### Fixed
- The shelves listed (`/shelves`, the Library's front page until Today took `/`) answer in a second on a
  record of millions of lines. The page counted the lines and found the first and last stamp in one pass
  over the whole index; it now reads the count from the record's head, as `logbook doctor` prints it, and
  the first and last day two steps down the day index. The page reads as before; a record with a torn
  tail past its head (a crash before `logbook repair tail`) is counted to its head, as `doctor` counts it.
  Today, at `/`, makes no pass over the lines on the request either.
