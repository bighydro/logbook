### Fixed
- Two Library pages asked for at once no longer fail on Windows when both save the same reading kept
  beside the index: each thread writes a temporary file of its own, and a save that cannot finish
  leaves the reading for the next one to make.
