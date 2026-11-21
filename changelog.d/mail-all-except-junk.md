### Added
- `export crossing --mail people|all|all-except-junk`: a third mail mode, every mail but a received one your
  own rule calls junk, written as `mail_junk` in the destination's entry of `policy/crossing.json`
  (`categories`, `labels`, `never_labels`; RFC 0045, amended). A person of the record, a never-label, an
  invitation platform, an org in a portfolio and a sender Hold keeps spare a mail; a sender let go is always
  held. Refused, with nothing exported, without a `mail_junk` rule. The package counts what was held by
  reason and how many were from a first-time sender, counts only. `--all-mail` stays, the same as
  `--mail all`.
- `logbook day sign` says, per destination with a `mail_junk` rule, how many of the day's mails would be
  held back and how many of those from a first-time sender; the MCP server gains `held_mail(day,
  destination?)`, read through the ceiling like every tool.
