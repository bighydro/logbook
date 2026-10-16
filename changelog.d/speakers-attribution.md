### Added
- Speakers, build 2 of RFC 0038: `logbook review speakers` names the voices of your recordings, and
  only you do. The queue keys a voice by the far end's number or address, the name its source
  displayed, else its label; it scores the far end of a call, the calendar entry, the participants,
  the source's name and who was seen that day (no voiceprint yet: context alone scores 40 at most, and
  two close candidates are both shown and neither taken). `--accept`, `--name N "…"` (`me` for your
  own voice; a new name mints a person), `--unnamed N [--same-as M]`, `--reject`, `--consent
  N=yes|no|unknown`, `--all-above`, `--play N` (the voice alone, here, nothing written); each answer
  is one `resolution/v1` line per voice with a `speaker` ref and its `basis`, a dated additive
  amendment to RFC 0006, `schema/resolution-v1-speaker.schema.json`. `--named --recording ID|--day
  DAY` corrects a wrong answer with a line that supersedes it; `repair retract` returns a voice to the
  queue.
- The readers join who spoke: the Day (`Middag · you 31 min · Kari Nordmann 14 min · 1 unnamed ·
  recorded with consent: unknown`, and `person`, `basis`, `consent` in `day --json`), `with` (a voice
  you named is company where it was recorded; the far end of a call never is; the unnamed are
  counted, `with.unnamed`), `people` (`spoke_s` on the transcripts channel; `and 1 unnamed` and the
  voices not yet named in the head), `rollup people`, `promises` (a sentence's speaker from its voice)
  and the digest.
