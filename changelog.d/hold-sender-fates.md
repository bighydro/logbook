### Added
- `logbook hold sender ADDRESS_OR_DOMAIN --keep` and `--let-go --reason "…"`: keep a sender of mail or
  let one go, one line in the record (RFC 0042 §4, RFC 0037 §10.7). A sender you let go is never a
  person's mail and stays home from a crossing and a shared day, whatever keeps it; a sender you keep
  is never junk under `--mail all-except-junk`; a later fate replaces the earlier one, and nothing is
  deleted.
- `people mail` counts the mail let go in Hold and how many senders you let go, never naming one;
  `--json` carries `fates` in place of the old `let_go` sentence.
- The Day page's Keep and sign carries *Held back* when a destination has a `mail_junk` rule and the
  day held mail under it: first-time senders by address and subject, then the other senders by
  address or domain with a count, each with a *keep* box that keeps the sender before the signature,
  so its mail crosses from then on. `logbook day sign DAY --keep-sender ADDRESS` writes the same.
