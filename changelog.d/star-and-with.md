### Added
- `logbook star LINE [--note TEXT]` marks a line worth keeping, and `logbook unstar LINE` takes the mark
  back. A star is one `star/v1` line (RFC 0041, a draft) at the starred line's own time and tier, so it
  is on its line's day and travels where the line does: `export share day` carries the stars on the lines
  it carries and never a star without its line, and `export trip-bundle` carries the stars on its photos
  and flights. A photo's star is a `memory` keeper (RFC 0024, amended with the star's `note`): the Day's
  hero photo and the photo the press picks for `--print`, the note printed under it as its caption.
  Starred again with another note, the new note supersedes; `unstar` is a retraction at the star's tier
  ([the acts](docs/acts.md)). A model's draft (the dream's draft of a day, a call's synthesis) takes no
  star: it is a proposal, not yours to keep; and no reader shows a star beside a line it does not
  show, so a star never reveals a line above a reader's tiers or a draft the policy withholds.
- `logbook with DAY NAME [NAME…] [--at HH:MM]` says who was there when the record could not see: one
  `note/v1` line per person, `with <name>`, labelled `with`, which the people reader and the Day already
  read as company. A name is what `people NAME` opens; one the record does not place refuses the whole
  statement with the `people review` hint. Without `--at`, noon of a past day, or now today.
- The Day marks a starred line `★` and, on a day you said who was there, lists the day's company in a
  `with` row with your word marked `(you said)`; `day --json` gains `stars` and `stated`, each only on a
  day that has them.
- The Day page of `logbook serve` carries both acts beside Reflect and Sign: a star on every row that is
  a line (events, notes, calls, mail, flights, unplaced items, all-day entries, each photo of a row, now
  named, your goals, reviews and chapters, and a proposed event once you confirmed it; never a draft's
  sentences, a synthesis or a row the policy withholds) and a *with…* field in the header, whose names
  are completed from the people the record names. Both post through the functions the commands run,
  are answered from this machine only, and never wait for another writer: while a command holds the
  record they answer `409` with one sentence and write nothing, as Reflect and Sign do. The Days page
  lists the window's stars under *Starred* ([serve](docs/serve.md#the-day--star-and-with)).

### Changed
- `logbook --help` lists 31 commands on 48 lines: `star`, `unstar` and `with` join the write group.
- `export crossing` carries a star only beside its line, as `export share day` and the trip bundle do;
  and every crossing carries a photo's `memory` keeper (your star on it, or the library's favourite)
  only beside its photo, so a favourite whose photo stays home stays home too.
- A keeper that names an earlier one in `supersedes` replaces it, as SPEC §3.2 defines a standing line.

### Profiles
- `star/v1` (RFC 0041, draft): the owner's star on a line, `line`, `kind`, `note`, `supersedes`, at the
  starred line's `at` and tier. `keeper/v1` gains the MAY field `note` by a dated amendment of RFC 0024;
  RFC 0030's trip bundle carries the stars on its lines by another. No envelope change.
