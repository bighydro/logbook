### Added
- An org's portfolio (RFC 0037 §10.2, amended 15 October 2026): `logbook status org ORG
  DISPOSITION --portfolio "Fund I"` names which portfolio holds the company, free text, in the
  `portfolio` field of the org's tier-3 status line; `--portfolio ""` clears it, and a status
  without it leaves it as it stood. Only an org's status takes one: a portfolio for an idea, a
  place or an asset is refused in one sentence and nothing is written. A status equal to the
  standing one is written when it moves the portfolio, and keeps the day the status took effect
  (`since`) unless you give a new reason. `show org NAME`, the org's page and `status list org`
  say it; `show orgs --portfolio TEXT` and the Manifest's filter (`/manifest?portfolio=`) list the
  orgs in one, case and spaces aside; the org page's status form carries it through the same
  writer, byte for byte. It is tier 3: no crossing, shared day or Notion folder carries it, and
  through a gate without tier 3 nothing shows it and a filter lists no org ([the
  profiles](docs/entities.md#statusv1)).
