### Fixed
- `verify` on a month file cut inside a line (a crash while writing, SPEC §3) reports the lines before the cut and
  their head, naming the cut line by file and line number in one plain sentence; it reported seq 0 and GENESIS
  and forgot every line before the cut. `logbook verify` prints the seq and head of the lines read on its
  `INVALID` line. SPEC §3 (truncation) and §6 now say so; the envelope and the hashes are unchanged.
