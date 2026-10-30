### Security
- `export share day` holds a day to the crossing's rules: only a day you have signed leaves (an unsigned
  one is refused in one sentence naming `logbook day sign`), and a mail crosses only when a person is on
  it; the page's manifest and its crossing line count each, `held_back_unsigned` and `mail_held_back`.
- `export crossing` and `export share day` refuse a name the policy keeps for its own reader or door
  (`mcp`, `hermes`, `dream`, `site`, `vault`, `world`, `folder`, `heard`, `chat`, `phone`, `notion`,
  `letter`, `relationship`, in any case) as a person or destination, in one sentence. A nightly
  `export crossing --to hermes` now stops: give the person's own name and its own entry in
  `policy/crossing.json`.
- docs/export.md says that a folder, the vault, the site and the world are your own copies and take no
  signed-day gate.
