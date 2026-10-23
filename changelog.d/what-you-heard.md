### Added
- What you heard (RFC 0046, draft): `sync heard` stores the words of the podcasts and videos you
  played, one `heard/v1` line beside each listen or watch, the text kept as it came in the
  attachment store: a feed's own transcript fetched once (WebVTT, SRT, JSON or plain text; at most
  `LOGBOOK_HEARD_MAX_FETCHES` a run, two seconds apart, a failed fetch counted and not retried for a
  week), the transcripts Apple Podcasts cached on this Mac, and a video's captions from your own
  folder (YouTube documents no keyless way to fetch them). Opt in with `LOGBOOK_HEARD`.
- `logbook show heard [--day D | --since D --until D] [--json]` lists the texts with a one-line excerpt
  and their length; `logbook search` finds words inside them. A crossing or a shared page leaves
  every text at home unless the destination's entry in `policy/crossing.json` says `"heard": true`.
