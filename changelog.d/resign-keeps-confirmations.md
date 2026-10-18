### Fixed
- A day signed again keeps your confirmations: `day sign DAY` and the MCP tool `sign_day`, without
  `--confirm`, keep what the standing signature confirmed, its dispositions and its note, as the Day
  page's *Sign again* and `day reflect --sign` already did; a line added since stays unconfirmed.
  `--confirm all` confirms the whole page (RFC 0034 amendment 4).
- A line superseded twice reads alike everywhere (#321): a superseder that is retracted supersedes
  nothing, and a line stays superseded while any superseder not retracted stands, in the index and so
  in `show`, `review speakers`, the voiceprint registry and every reader that asks it; the MCP door
  marks a transcript heard again as `show` does.
