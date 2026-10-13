### Added
- `logbook day reflect YYYY-MM-DD`: close the day in your words. The reflection is typed (`--text`), heard on
  this machine (`--audio FILE`, the `openlogbook[transcribe]` extra, refused with the install hint without it),
  recorded from the microphone on macOS (`--mic SECONDS`, with ffmpeg), or the day's Wispr Flow dictation that
  begins with the word "reflect" (offered as a draft and written only when you confirm it, or with
  `--from-wispr [SEQ]`). It is one `note/v1` line on the day, tier 2, source `reflect`, `reflection` in its
  `labels`, printed back a sentence a line. Rules only, no model, read it with the cue tables of `promises`:
  your commitments, delegations to a named counterpart ("ask Ola to ...", "Ola should ...", "Ola soll ..."),
  and what became of the commitments on the day's page (kept, missed, dropped, carried; matched by token
  overlap at 0.5), all printed as numbered proposals and none written until you accept it. `--sign` with
  `--accept N,N` (or one y/n each on a terminal) writes the accepted delegations as `note/v1` lines labelled
  `delegation` and signs the day through `signing.sign`, the reflection among the lines confirmed, the
  accepted dispositions in the signature and `--at` the moment you spoke; a day signed before is signed
  again, keeping what its signature said. `--dry-run` writes nothing.
- `day` and the Day page of `serve` show the latest reflection in a section of its own, below the header and
  above the timeline; `day --json` carries it under `reflection`, a key present only on a day that has one.

### Changed
- The MCP tool `note_day` writes through the same note path as `day reflect` (`logbook/core/notes.py`); what
  it writes is unchanged.
