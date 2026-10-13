### Added
- docs: RFC 0036 amendment 1: a `person` unit for `draft/v1` (one canonical person over a stated
  `window`; the model reads only the lines where they are a counterpart, attendee or speaker, never a line
  that merely mentions them, and evidence outside that set is invalid); the writers of goals, reviews and
  chapters, `goal add`, `goal review` (its `at` may be backfilled), `chapter open` and `chapter close`,
  under the writer lock with the head read again before the append, as `day sign`; a reader hides a draft
  whose tier exceeds the current ceiling of the crossing serving it, and a draft records the policy it was
  read under (`read_policy`); and how `goal/v1` and `review/v1` relate to RFC 0037's `status/v1`. A document
  only: nothing in the code, the envelope or the conformance samples changes.
