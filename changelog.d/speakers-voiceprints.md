### Added
- Speakers, build 3 of RFC 0038: the voiceprints. `voiceprints.age`, in the record folder, is one
  file sealed to the record's recipients and written whole: per person the centre of their voice's
  embeddings from clean speech (two seconds alone at least, `min_clean_s` in all), and the voices not
  yet named; no audio, no words, no names. It is a cache made from the record: `derive transcripts`
  and `derive speakers` add what they separate, every answer in `review speakers` updates it without
  the model, a retracted or superseded answer leaves it at the next write, a new model makes it again,
  and `logbook setup speakers --rebuild` makes it from the audio and the answers that stand. Your
  own microphone's voice and every voice you named yourself are your voiceprint, without a line. A
  record without recipients keeps none: the review hears what it compares for the run, in memory.
- `review speakers` scores the same voice, up to 70 points at `match`, none at `floor`, beside the
  context, yours as anyone's, so your row comes first and a guest named once is recognised the next
  time; voices that sound alike are one row of several recordings. `policy/speakers.json` sets
  `match`, `floor`, `min_clean_s`, `text_confidence_cap`, `enrol_unnamed` (off: a person you would
  not name is not recognised either) and `forget` (never kept, never proposed), each refused in one
  sentence when it is not the shape.
- The registry never leaves: no crossing, shared page, trip bundle, vault, site, MCP answer, dream,
  backup or export carries the file or a vector of it, and a test looks in every one. `verify`
  ignores it; `doctor` and `setup speakers` say when, with which model and for how many people it was
  written, never what is in it, and warn when the model is not the configured one.
- `logbook key add-recipient` and `key remove-recipient` seal the registry again with the record, in
  the same hold of the writer lock: before the record's lines when a recipient goes, so a removed
  identity opens no copy of it even when the change stops half way; a registry that cannot be sealed
  again is removed, to be made again.
