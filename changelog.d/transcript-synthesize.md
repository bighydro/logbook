### Added
- `transcript synthesize ID|--day DAY [--dry-run] [--show-prompt] [--again]`: a model reads one call through
  the dream's engine, under the same `dream` entry of `policy/crossing.json`, and writes one `draft/v1` line
  (unit `event`, subject the transcript line's id): the actions proposed on top with assignee and due hint,
  the topics consolidated across the whole call, the decisions (settled, not discussed), the open threads and
  a short personal part. The schema and the work-only rule are the prompt's
  (`logbook/contrib/synthesis-prompt.md`, docs/synthesis-prompt.md), never a filter in the code. Utterances
  are not lines, so every segment's evidence is the transcript line and the utterances it rests on, with
  their time into the call, are kept under `extra.segments`; a reference the material did not give makes the
  item unsupported and more than 30 % unsupported refuses the answer. A call above the entry's `max_tier`
  stays home (the granola and transcript adapters write tier 3); one the same model synthesized is unchanged
  and nothing is sent; another model or `--again` supersedes (docs/transcript-synthesis.md).
- `dream --catch-up`, and so the 06:00 close, synthesizes each call of the days it covers that has no
  synthesis yet, and counts the calls the ceiling held back.
- The Day shows a call's synthesis as one collapsed row under the call's own row; `serve` opens it behind a
  toggle, actions on top; `day --json` carries the items under `syntheses`; `--no-dream` leaves them out.
- A call's synthesis follows the policy like any draft: it records the `dream` entry it was made under
  (`extra.policy_version`); one above the entry's `max_tier` today is withheld, the Day saying `superseded by
  policy` under the call (`syntheses_withheld` in JSON) and nothing of it; one made under another version of
  the entry is synthesized again by `transcript synthesize` and `dream --catch-up`.
