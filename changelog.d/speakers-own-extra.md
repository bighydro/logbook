### Changed
- The diarizer is its own extra, `openlogbook[speakers]` (RFC 0038, open question 13):
  `openlogbook[transcribe]` brings the Whisper engine and nothing of pyannote.audio, torch's
  diarization stack or CUDA; voices need `openlogbook[transcribe,speakers]`. Without it `derive
  transcripts` transcribes as before and says `speakers: not separated (install openlogbook[speakers],
  then logbook setup speakers --fetch-model)`; `setup speakers` and `derive speakers` exit 2 with that
  sentence. A machine that installed `[transcribe]` from `main` for its voices adds `speakers`.
