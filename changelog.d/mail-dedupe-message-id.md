### Fixed
- One email is one line, whichever road brought it: `add mail` (a Takeout mbox), `sync mail` (IMAP) and
  `sync gmail` each skip, before they write, a message the record already holds by its `Message-ID` from
  any of the three, and say so per mailbox (`3,412 already in the record from mail (an import without
  --account)`), dry runs included. A Takeout added without `--account` was keyed `<Message-ID>` and the
  live roads `<account>:<Message-ID>`, so a sync over a period the export covered wrote every message a
  second time. `payload.message_id` is now the id normalised (brackets and surrounding whitespace off, the
  domain part lower-cased, the part before the `@` as written) and a message the record holds under another
  spelling is found among the lines of its days; a copy in another of your mailboxes is still a line of its
  own (RFC 0015 rule 1, amended). Nothing written is touched; a message without a `Message-ID` is keyed by
  its bytes and dedupes on its own road, as before, and `Message-ID: <>` now counts as none instead of
  folding every such message into one line ([Mail](docs/adapters/mail.md#one-email-one-line)).
