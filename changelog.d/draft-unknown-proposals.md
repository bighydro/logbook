### Changed
- A draft's proposals of a kind this reader does not know are counted, not malformed: the Day shows
  the proposals of the kinds it knows, counts the others as `proposals_unknown` in its JSON, and says
  `malformed` only for a known kind of the wrong shape or a proposal with no kind; every writer still
  writes only the kinds it knows and refuses any other (`draft/v1`, forward compatibility, 19 Oct 2026).
