### Fixed
- A request counts only when a person wrote it. `promises` proposes "asked of you" from a mail only when
  it is a person's mail (RFC 0045: the sender resolves to a person, is no no-reply address, no agent's)
  and from a message only when its sender resolves to a person, never in a conversation with an agent.
  A newsletter's "please let us know", a notification, a company's mail and a message from a number
  nobody is named by no longer show as asked of you, in `promises`, on the Day page's loose ends, the
  person page, the shelf or the Notion export; resolve the sender to a person and they count again.
  Commitments, transcripts and notes are read as before.
