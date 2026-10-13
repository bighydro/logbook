### Added
- RFC 0038 (draft), *Speakers: who spoke, and who they are*: anonymous speaker labels on `transcript/v1` from
  diarization in the `transcribe` extra, on this machine (`speakers`, `diarization` and a spans file, additive
  to the frozen profile; a transcript without them stays valid), the model fetched only by
  `setup speakers --fetch-model`; one `resolution/v1` line per voice on a new `speaker` ref, written only by the
  owner through `review speakers` in RFC 0037's shape, the model proposing and never binding, the transcript
  never rewritten; a sealed voiceprint registry beside `places.json`, a cache rebuilt from the audio and the
  attributions, part of no crossing and ignored by `verify`; text-only proposals as `draft/v1` when the audio is
  gone; consent as the owner states it; `exclude_people` and `hold_unattributed` on a crossing-policy entry;
  tiers, dedupe keys and fifteen open questions. Documentation only: no command, line or reader changes yet
  ([rfcs/0038-speakers.md](rfcs/0038-speakers.md)).
