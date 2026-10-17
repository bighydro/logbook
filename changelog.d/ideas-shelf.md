### Changed
- `review idea` sees a repository in two more places: an act `sync github` wrote (its own link,
  else its repository on github.com: a commit, a README's version), and a task's own `url` beside
  its links.
- A bot's line is nobody's (the owner's decision of 14 October 2026): a line whose actor is a bot
  (`sync notion`'s `bot`, `sync github`'s `Bot`) or whose words an agent wrote (`extra.machine`)
  is never a touch of an idea in `review idea`, never a person seen on one, and adds no words to
  one; an agent among a call's participants is nobody, whatever address it joined under.
- RFC 0037 §4.3, amended 2026-10-16: a database row is its own root. A row of a Notion database
  (its lines carry the row's `database`) is an idea of its own in `review idea`, never folded into
  the page above the database; a page under a row is the row's.
- `review idea` proposes a Notion database row as an idea only when its `Type` select says `Idea`
  (the owner's decision of 14 October 2026), as the row's latest line with `extra.properties` has
  it; a page under a row of another type is not proposed either, and a page that is no row is
  proposed as before. `idea_rows` in `policy/entities.json` names another select and option
  (`{"property": "Kind", "value": "Spark"}`, case aside). `sync notion` already writes the select's
  name and option on the row's line, and nothing else of it.

### Fixed
- `review idea` no longer counts a Notion row's `relations` line (`sync notion --relations-backfill`)
  as one more line of its idea: a relations line links a row to others and touches nothing. The
  observed table is rebuilt once.

### Added
- `logbook show ideas` and `logbook show idea NAME` (RFC 0037 §7, §11): the ideas you named by stage
  (build, exploring, spark, built, killed, no status), the most recent touch first, each with its
  reason (a killed idea that sparked again keeps its old one, said with its day), the words written
  this year (`--year`), its repositories, how many people it was discussed with and never their names,
  the days since its spark, its latest titles and the stale ones said (an `exploring` over two years
  with nothing since); one idea's page with every touch newest first, the people by name, its Notion
  pages and repositories as references (a README's versions), its title thread, the words by month and
  every status line ([ideas read back](docs/entities.md#the-ideas-read-back)). A touch is a line that
  resolves to the idea as `review idea` finds it; a bot's, an agent's and a relations line are none.
- The Ideas shelf under `logbook serve` ([Ideas](docs/serve.md#ideas)): `/ideas`, the ideas you named
  by stage, the most recent touch first, the stale flagged, each with its reason and its evidence
  folded, the people it was discussed with counted and named only on its own page, and below it the
  review queue of `review idea`; `/idea/ID`, one idea with its status form, first said, every touch,
  the people by name, its documents, its title thread and its words by month. Accept, Name and No
  write what `review idea --accept`, `--name` and `--reject` write, the status form what `status
  idea` writes (with a reason, the note first), through the same functions, byte for byte; from this
  machine only, and while another command writes the record an act is a `409` and nothing is written.
  One column, phone first; an exported site has no Ideas.
