### Fixed
- A week draft's people are printed by name only, the most time together first, never with a count
  beside a name (`with  Kari Nordmann · Ola Nordmann`, was `contacts  Kari Nordmann 12`): in `dream
  week`, `logbook day` and `day --json` on its Sunday, the Day page, `export site --with-drafts`, and
  for a week dreamed before as well. A chat among the week's threads is named without its count, and
  a title is quoted beside its count. The line keeps each person's name, id, lines and contacts (the
  week page compares the contacts to name who moved, and prints none), no longer the counts by
  channel or the days together; and the week's own sentences are held as the day's, month's and
  chapter's are: one that names a person and writes a figure is dropped, `held: a number beside a
  name` (`dream-week/2`; RFC 0043 §2.5).
- The readers of a day, a week, an org and an idea set no number beside a person's name either: a
  call on the Day (`logbook day`, the Day page) reads `19 min ← Ola Nordmann` (was `← Ola Nordmann,
  19 min`); a recording's voices are named in the order of who spoke most, without their minutes,
  `you · Kari Nordmann and 1 unnamed`; the digest's `with` reads `Kari Nordmann and 1 proposed`; an
  org's and an idea's people (`show org`, `show idea`, the Library) read `Kari Nordmann, last
  2026-06-12`; the week's paper, the vault's People lists and the lab's chapters name the people, the
  most days first, without the days.
