### Added
- `review goal`: each open goal is asked once a week in the review sitting and answered with
  `--say N advancing|stalled|done|let-go|superseded [--note N TEXT]`, the line `goal review … --period
  week` writes, byte for byte (RFC 0036 amendment 1).
- `dream week` asks one stale question a week about the stalest holding or idea (RFC 0037 §10.6), kept
  in the week's draft as `extra.question`: never a line of its own, never a status, never above the
  draft's tier.
- The call synthesis proposes up to three ideas the call put forward, new or refining one you named;
  they wait in `review idea`, marked `[call]`, and reach the Ideas shelf only when you accept one.
- With the Telegram notifier set, the schedule sends "Your Day page for <date> is ready" after the 06:00
  close (`LOGBOOK_NOTIFY_LINK_HOST` adds the link) and the evening question at
  `LOGBOOK_NOTIFY_EVENING_HOUR`: one message each a day, nothing of the day beyond the date, the count
  and the question.
