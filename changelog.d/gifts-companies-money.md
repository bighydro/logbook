### Added
- `logbook add gift DAY NAME WHAT [--received]` writes what you gave someone, or were given: one
  note in your words labelled `gift`, the person under `extra.recipient` or `extra.giver`; a name
  that is nobody, several people or you is refused in one sentence. `logbook people gifts [NAME]
  [--json]` reads them back both ways ([gifts](docs/gifts.md)).
- `logbook lab companies DAY [--json]`: the orgs the Manifest names that a day touched (an update
  mailed from one of their domains, a meeting with someone of theirs, a document in one of their
  repositories), each with its lines and the people of theirs on them, never a bare address;
  grouped by portfolio; status and portfolio only where tier 3 is read ([companies](docs/companies.md)).
- The money slot's reader, `money.money_in`: a window's transactions with merchant and amount (tier
  3), and, when no payment source covers it, `No payment source covers this day — the last ends
  <date>`, never an empty sum.
