### Added
- `logbook doctor --packet [--out FILE]`: a plain-text diagnostic to hand a collaborator when something
  fails, with no line's content, no name, no path under the home directory and no value of a variable in
  it (docs/doctor.md, "Sending a diagnostic"). It holds the OS and its version, the architecture, the RAM,
  Python, openlogbook and the extras installed; the record's line count and head; each source's last-run
  result and watermark date; the schedule, the last scheduled run and the serve service; the dream
  endpoint's host and port and model with one probe, the fixed prompt `Reply with the single word
  ready.` sent once, and the reply's HTTP status and body as they came; the names of the variables set;
  and the last 40 lines of the sync and service logs. What it quotes is scrubbed: the home directory
  becomes `~`, the record's folder `[record]`, the owner's names, handles, addresses and numbers from
  `policy/owner.json` (a number however it is spaced) and the login name `[owner]`, the machine's name
  `[host]`, places and assets `[place]` and `[asset]`, a variable's value its name in brackets. The
  probe is the packet's one network call, made only when `LOGBOOK_DREAM_ENDPOINT` is set and a model is
  named.
