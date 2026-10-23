### Added
- `day sign DAY --keep N,N` and `day reflect DAY --sign --keep N,N` keep what you choose of the dream's
  draft before they sign: a sentence learned, decided or about an idea as a note, a proposed link as the
  entity line `review` writes, the photo of the day as a star with its note. `logbook day DAY` numbers
  them after the proposed events. `--mend N="…"` keeps a sentence in your own words, `--revisit
  N=YYYY-MM-DD` gives a kept decision the day it comes back, and `--word WORD` keeps the day in a word,
  one a day. Every item is checked before the first line is written; one refusal writes nothing.
- The plan answered at the close: `day sign DAY --done T,T --tomorrow T --let-go T` writes one note per
  task, labelled `task`, with the Notion row, its line and the answer, for the agent that runs your task
  tool; it crosses with the signed day. `show plan` numbers today's tasks and marks the ones you
  answered, and a task's day is its `Planned` date, else its `Due` date, unless the mapping names one.

### Changed
- A signature never confirms the dream's draft line (RFC 0043 §6 rule 3): `day sign`, `--confirm all`,
  `day reflect --sign`, the Day page's Sign and the door's `sign_day` leave it out of `confirmed`, and
  naming it in `--confirm` or a disposition is refused. The page digest still covers it.
