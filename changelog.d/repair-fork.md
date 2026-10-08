### Added
- `logbook repair fork [--apply]` (`logbook/core/fork.py`, #234): a record whose month files hold two
  chains forked at one head — a long `sync` wrote its batch chained from a head another command had
  moved past, and the index refused it after the files took it — is diagnosed (the fork, each orphan
  chain's count, seq range, sources and files, `logbook.json` against the record's chain; counts and
  hashes only, nothing written) and with `--apply` repaired: every orphan line is copied in order to
  `repair/<stamp>-removed.jsonl` in the record folder with a `repair/<stamp>-report.json`, each touched
  month file is written again without them with every kept line byte for byte, `logbook.json` is set
  to the record's head, the index rebuilt and `verify` run. The record's chain is the one the index
  agrees with, else the longer one, else the command refuses; it also refuses a break that is not a
  fork, a torn month file, a sealed orphan line it cannot open, and a folder under a sync client.
  `doctor`'s record check names it beside `logbook verify`; `docs/recovery.md` is the page.
