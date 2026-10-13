### Added
- EXPERIMENTAL: the relationship reader, slice 0 (`logbook/contrib/relationship/`, its README states the
  boundaries). `people ingest NAME --window FROM TO` reads one canonical person's authorized input set under
  the new `relationship` entry of `policy/crossing.json` (`max_tier` and `until`, both required): the lines
  where they are a counterpart, an attendee or a speaker (RFC 0036 amendment 1), never a line that merely
  mentions them, in the window, not retracted, at or under the ceiling; and writes a disposable store under
  `state/relationship/<person>/`, each line attributed to the peers who spoke it, one peer per canonical
  person and none for an unresolved one, with the line-id map. `people ask NAME QUESTION` answers from the
  store with every cited id resolved against the set read again from the record, or marked unsupported,
  and writes nothing; a store serves only under the head and the entry it was read under, and an expired
  entry refuses. No model is wired yet: `people ask` refuses until a later slice wires one.
