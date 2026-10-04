"""The labs tier: everything that runs a model, or is still an experiment.

`transcribe` (a voice memo heard by a local Whisper), `describe` (a keeper's photo seen by a local
vision model), `judge` (a promise candidate read by a local instruct model: `promises --judge`) and
`demo_life` (`demo --years`, a synthetic life). Nothing here is imported until its command runs,
so `logbook --help` and every other command load no model code (`logbook/layout.py`)."""
