### Security
- The Library is one login at a time: tailscaled keeps a connection open for many requests, and a
  request on it that names another login, none, or is this machine's own is now a 403 and the
  connection is closed. Every proxy header (`Forwarded`, `Via`, `X-Real-IP` as well as `Tailscale-*`
  and `X-Forwarded-*`) is a proxy's on a form's POST too, and the docs say so.
- No pencil without evidence: outside the Day's own Draft, a model's sentence (the letter's story, the
  week's proposal under Today and on the week page, the intention it prefills, a goal's proposed verdict,
  a call's decisions, the chapter on Life, what was drafted about a person) is shown with the ids of the
  lines it cites, and only when every one is a line the page reads; one with none, or one that rests on
  a line above the page's tier, is not shown. A letter no longer carries a story sentence that rested on
  a tier-3 line.

### Fixed
- `review receipts` reads a sender's address as the address it is (Unicode NFKC): a fullwidth `＠` or
  fullwidth letters no longer hide a person, or you, behind a lookalike, and an order address written so
  is read.
- The demo record's places are the persona's own coordinates or public landmarks: the museum is the
  Kunsthaus, and no hotel, flat, office or cabin points at a real address.
