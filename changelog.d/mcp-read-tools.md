### Added
- `logbook serve mcp` gains three read tools behind the same `mcp` ceiling of `policy/crossing.json` as the
  nine before (`docs/mcp.md`): `day_lines(day?, kinds?)` is `logbook show DAY` as one object per standing
  line, in time order, with the line's id, kind, profile, local time, counterpart and the text part of the
  row `show` prints, `kinds` keeping only the profile families asked for (`mail`, `message`, `transcript`,
  `note`, `location`, `photo`, `calendar`); `line(id)` is one line in full, the row, the payload and the
  text, a transcript's turns read from the attachment store as `promises` reads them; `digest(period?,
  date?)` is the text `logbook digest DATE` prints, or the seven digests of the ISO week that holds the
  date. Lines above the ceiling are left out of `day_lines` and counted in `above_ceiling` with nothing of
  them crossing, not even an id; `line` refuses one naming its tier and nothing else; the digest is read
  through the gate, so at a ceiling of 1 it is the digest of a record that holds only tier 1. An agent on
  this machine could search a day's lines but not read them without a word to search for, read a
  transcript's summary but not its text, and not get the digest; now it can, under the ceiling. The server
  logs one line per call on the `logbook.mcp` logger (stderr): the tool, the day or id, and counts — never
  content. The row `show` prints for a line moved from `logbook/commands/rows.py` to
  `logbook/contrib/rows.py` so a contrib reader can print it (the commands import the same names); nothing
  any command prints changed.
