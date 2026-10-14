### Added
- docs: RFC 0036 amendment 1: a `person` unit for `draft/v1` (one canonical person over a stated
  `window`; the model reads only the lines where they are a counterpart, attendee or speaker, never a line
  that merely mentions them, and evidence outside that set is invalid); the writers of goals, reviews and
  chapters, `goal add`, `goal review` (its `at` may be backfilled), `chapter open` and `chapter close`,
  under the writer lock with the head read again before the append, as `day sign`; `draft/v1` rule 7, a
  draft follows the policy, not the head (the entry's version under `extra.policy_version`, `superseded by
  policy` where the page would show it), held for a draft of every unit, a person's included, and through a
  crossing to that crossing's current ceiling as well; and how `goal/v1` and `review/v1` relate to RFC
  0037's `status/v1`. A document only: nothing in the code, the envelope or the conformance samples
  changes.
