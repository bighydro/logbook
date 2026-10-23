### Added
- People's mail, one rule ([RFC 0045](rfcs/0045-peoples-mail.md), draft): a mail is a person's when
  someone the record names as a person sent it to you or you sent it to one; no-reply addresses, agents
  and companies are not people. `logbook people mail [--since DAY] [--until DAY] [--json]` counts
  people's mail and the rest, never an address or a name in the terminal ([people's mail](docs/mail-people.md)).
- `export crossing` sends people's mail only and counts the rest as `mail_held_back`; `--all-mail` sends
  every mail as before, and the manifest says so ([the crossing](docs/crossing.md#peoples-mail)).
