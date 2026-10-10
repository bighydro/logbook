### Added
- `logbook people review` (`logbook/contrib/people_review.py`, `docs/people.md`): the record's people in two
  layers. An **observed** person is what one source saw, keyed by its strongest identifier — the email
  address, else the phone number in E.164 (a WhatsApp JID read as the number it spells), else the folded
  name — never by a per-observation id, so an address seen under three display names is one person; they
  are a derived table in the index, `observed_people`, built from the standing mail, message, transcript
  and event lines, stamped with the head and rebuilt when the record grows, nothing stored in the record. A
  **canonical** person is one the resolution lines name, as `people` lists them. The command proposes each
  observed person not yet placed against the canonical people, ranked by the evidence (same email 60, same
  phone 50, same name 20 and +5 per further source, together on the same days 2 per day) and numbered;
  `--accept N[,N]` writes the alias line `people merge` writes, one per identifier as the lines wrote it;
  `--reject N[,N]` writes one `people-review/v1` line (RFC 0035, draft) saying the two are not the same
  person, so the pair never comes back; `--all-above SCORE` accepts at or above. Nothing is promoted on its
  own; every number is checked before the first line is written; `--json` carries the queue, the unplaced
  and a stable id per pair.
- `logbook people --priority [--year YYYY]` ranks the canonical people heard in the last year by a plain
  sum printed beside each name: 3 per day together, 1 per message exchanged (the smaller direction, up to
  50), 2 per meeting, 10 when the last real contact is within 30 days and 5 within 90. No model.
