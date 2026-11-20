### Added
- `logbook hold sender ADDRESS_OR_DOMAIN --keep` and `--let-go --reason "…"`: keep a sender of mail or
  let one go, one line in the record (RFC 0042 §4, RFC 0037 §10.7). A sender you let go is never a
  person's mail and stays home from a crossing and a shared day; an address you keep stands against
  its domain let go; a later fate replaces the earlier one, and nothing is deleted.
- `people mail` counts the mail let go in Hold and how many senders you let go, never naming one;
  `--json` carries `fates` in place of the old `let_go` sentence.
