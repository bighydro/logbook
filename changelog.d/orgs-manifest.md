### Changed
- `review org` sees an org in two more places: a transcript participant's address, and an act `sync
  github` wrote (its own link's code-host org, else its repository's on github.com). A calendar's
  rooms and a code host's relay (`resource.calendar.google.com`, `users.noreply.github.com`) name no
  company, and your own code-host account (a `github:` handle in `policy/owner.json`) is yours, never
  an org. A person's own account is hinted `personal`, and a family's domain is one whose names are
  each a given name the address itself spells (`kari@` "Kari Nordmann"), so a newsletter in its own
  name ("Nordmann Nytt", `news@`) is a company. The observed table is rebuilt once.

### Added
- `logbook show orgs` and `logbook show org NAME` (RFC 0037 §7, §11): the orgs you named under their
  current status (holding, exited, passed, let go, no status), the most recent touch first, the stale
  ones said (a `hold` over three years with nothing since, `stale_days` in `policy/entities.json`),
  the passed with their reasons in full, and the people who appear with more than one org; one org's
  page with every touch, its people, who introduced whom, its documents as references and every
  status line. A touch is a line that resolves to the org through one of its refs, a ledger line
  through its merchant among them; its figures only with `--money` (`--year` for the shelf). An org's
  status, its reason and the money are tier 3 and read through the gate of whoever reads
  ([orgs read back](docs/entities.md#the-orgs-read-back)).
- The Manifest under `logbook serve` ([the Manifest](docs/serve.md#the-manifest)): `/manifest`, the
  orgs you named under what you decided about them, the most recent touch first, the stale flagged,
  the passed with their reasons, each row's evidence folded, and below it the review queue of
  `review org`; `/org/ID`, one org with its status form and every touch, the money only when you ask;
  `/manifest/people`, who appears with more than one org. Accept, Name and No write what `review org
  --accept`, `--name` and `--reject` write, the status form what `status org` writes, through the
  same functions, byte for byte; from this machine only, and while another command writes the record
  an act is a `409` and nothing is written. One column, phone first; an exported site has no Manifest.
