### Added
- Speakers, build 1 of RFC 0038: `derive transcripts` separates the voices of each recording on this
  machine when the diarizer (pyannote.audio, in the `transcribe` extra) and its models are here, and
  the `transcript/v1` line gains `speakers` (anonymous labels `S1`, `S2`…, or `mic` and `system` for a
  call whose source keeps its sides apart, `from_me` on the microphone's one voice) and `diarization`,
  with a spans file in the attachment store; without the models it transcribes as before and says
  `speakers: not separated (logbook setup speakers --fetch-model)`; `--no-speakers` turns it off. The
  two fields are a dated, additive amendment to RFC 0004, `schema/transcript-v1.schema.json`.
- `logbook derive speakers [--since DAY] [--speakers N] [--dry-run]` hears again the transcripts heard
  before, each into a new line that supersedes the old, and says first what that changes (signed
  days, closed promises).
- `logbook setup speakers` says what separates voices here; `--fetch-model` is the one download, with
  `HF_TOKEN` read for those requests only, never written or printed.
- `sync granola` labels the microphone's and the system audio's voices from Granola's own marks.
- `show`, the Day and `serve` name a transcript's voices; `day --json` gives them under `speakers`.
