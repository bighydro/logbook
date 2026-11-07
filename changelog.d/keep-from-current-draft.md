### Fixed
- Keep and sign take a sentence only from the day's current draft. When the day was dreamed again and the
  newer draft is withheld (the `dream` entry no longer allows its tier, or the Day page's gate does not
  read it), the older draft it superseded is still shown, but `logbook day sign DAY --keep N` and the Day
  page now refuse to keep from it, in one sentence that names the current draft (its number, its id and
  when it was written) and how to keep from it; a retracted draft is refused the same way. On the Day page
  a superseded draft's keep boxes are gone and the form says a newer draft exists, with a link to it as
  written (a draft above the page's gate is said to exist and never named). A keep made before its draft
  was superseded stays as it was written, and `logbook show DAY` says which draft it was kept from
  (`kept from draft #8, superseded by #9`).
