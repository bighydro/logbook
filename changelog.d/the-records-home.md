### Added
- ADR 0022, the record's home (`docs/adr/0022-the-records-home.md`): one machine holds the only
  writable copy, runs the sync schedule, the MCP server and the local models, and serves the Day page
  over the owner's own network; every other device is a reader; an orchestrator elsewhere reaches the
  record only through the crossing; sources come to the home; a collaborator is an OS user on it; and
  every cloud model or service that may see record content has its own entry in `policy/crossing.json`.
  `logbook sync --install-schedule` names this machine the home in `state/home.json` (hostname and
  date; a second install on the same host keeps the date). `doctor` gains a `home` line (pass on the
  home or when none is set, a warn elsewhere: writers belong on the home) and a `crossing` line listing
  every destination's ceiling as it counts today.
- `policy/crossing.json`: an entry may carry `"until": "YYYY-MM-DD"`, the last day it holds; from the
  next day it counts as `max_tier` 0 for `export crossing`, `export vault`, `export site` and the MCP
  server, the refusal says when it expired, and `doctor` names it. An `until` that is not a date is
  refused naming the file.
