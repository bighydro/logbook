"""The labs tier: everything that runs a model, or is still an experiment.

`transcribe` (a voice memo heard by a local Whisper), `describe` (a keeper's photo seen by a local
vision model), `judge` (a promise candidate read by a local instruct model: `promises --judge`) and
`demo_life` (`demo --years`, a synthetic life). Nothing here is imported until its command runs,
so `logbook --help` and every other command load no model code (`logbook/layout.py`).

The lab: readers that are still finding their shape, run as `logbook lab <reader>`.

A lab reader is a reader (ADR 0013, SPEC §3.2): a pure function of the record at its head, derived
every time from one reading of the window (`reading.read`), never written, and it opens no
connection. What makes it a lab reader is that its reading is not settled: its JSON may change
between releases, it is not in SPEC §3.2, no second implementation is held to it and the cross-impl
job does not compare it. A lab reader that proves itself moves out of `logbook/labs/` and into the
spec with an ADR; one that does not is deleted. `docs/labs.md` says what each one reads, what it
prints, and what it cannot see."""
