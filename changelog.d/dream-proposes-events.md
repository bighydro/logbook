### Added
- The dream proposes events: beside its segments, `dream day` asks the model for the events the day held
  (`{title, start, end, place, people, evidence}`; the prompt is now `dream-day/2`) and keeps them inside the
  `draft/v1` line under `proposals`, kind `event`, never as event lines. A stay at a restaurant with two
  photos and a recording is a dinner with the people in it. The material gives each stay its `place` (a named
  place's name, or `place:<lat>,<lon>`) and the day's canonical people by id; a proposal with a time, a
  place, a person or evidence not of the day is dropped and counted under `extra.dropped`, an unresolved
  person among them (docs/dream.md, *Proposed events*).
- `day sign` and `day reflect` list the proposed events, numbered; `--accept N` writes one as an `event/v1`
  line, the calendar adapter's own mapping of its fields, source `owner`, tier 1, `extra.from` the draft's id,
  under the writer lock the signature takes and confirmed in it. Nothing is written without `--accept`.
- The Day shows a proposed event greyed (`?` and `proposed` in text) and a confirmed one as an event of the
  day; `day --json` carries them under `draft.proposals`, each with `confirmed`.
- Proposed events follow the policy with their draft: a draft the `dream` entry no longer allows is withheld
  with its proposals, so the Day shows none of them and `day sign`/`day reflect` list none and refuse
  `--accept` for them with the reason; the draft the entry still allows, shown in its place, brings its own.
  An event confirmed before the entry changed stays in the record.
