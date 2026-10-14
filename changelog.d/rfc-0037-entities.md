### Added
- RFC 0037 (draft), *Entities*, with its twelve questions decided by the owner (the body says each,
  and a *Decided* section lists them): one road per kind, a person through `resolution/v1` and an org,
  idea, place or asset through `entity/v1` only, with `company` resolution lines read as orgs and never
  rewritten; `entity-review/v1`, the owner's no for every kind, which `people review` and
  `setup places review` will write (the place nos in `state/places-review.json` become lines once, by
  `--migrate-rejects`, and the file a cache); `status/v1` for orgs, ideas, places (`let-go`) and assets
  (`sold`, `let-go`), a reason kept as a `note/v1` labelled `status`, a `hold` with a reason muting the
  proposal it answered for 365 days, and staleness as a reader's rule; one `observed_entities` table
  with a ranking-only `hint`; how a status differs from RFC 0036's goal review and RFC 0034's
  dispositions. RFC 0035 gains amendment 1 (the no is `entity-review/v1`; `people-review/v1` is read
  forever) and ADR 0018 rule 4 an amendment (registry entries are never deleted; a status line closes
  them with `until`). Documentation only: no command, line or reader changes yet
  ([rfcs/0037-entities.md](rfcs/0037-entities.md)).
