# ADR 0013 — Downstream interpreters

Status: accepted · 2026-09-14

**Context.** Other systems will read the Logbook and turn it into understanding and action: a personal wiki, a task database, a calendar, an agent. One such system proposed an interoperability contract. Most of it fits; four points would have moved decisions upstream that belong to the record.

**Decision.** A downstream interpreter relates to the Logbook as follows.

1. **Everything enters; the interpreter receives a curated view.** The Logbook ingests every item its adapters can reach, classified but not filtered (ADR 0011). What an interpreter receives is a *derived export* chosen by later, versioned passes. The interpreter never defines what enters the log.
2. **The Logbook mints identity.** People and places get their ids here. An interpreter stores a `logbook_ref` and never a parallel id space. An interpreter's existing registry of people or places may be imported once, through an adapter, to seed names and aliases.
3. **Open keys for the world.** Places reference OSM / Wikidata ids, never a private namespace. Person ids are Logbook UUIDs.
4. **The day package is the hand-off unit.** `logbook export --day <date>` writes a `day-package/v1` directory: a manifest with the day's lines (ids, kinds, tiers, tags), derived entities when they exist, attachments by content hash, and `logbook_head` — the chain head at generation time — so the consumer can prove which state of the record it read. The package is a view; it never replaces the log.
5. **Tags and lifting are downstream and confirmed.** A personal taxonomy (life areas) is applied as tags by a classification pass, in the owner's private layer, never by the public spec. Lifting a tier-2/3 line into an interpreter's cloud store is a per-line visibility choice recorded in the log (ADR 0004); a tag may *propose* it, a human confirms it.
6. **Writes back are proposals.** An interpreter may return suggestions (a trip, a person, a task) and, on acceptance, a reference to what it created; the acceptance and the reference are recorded as manual lines. An interpreter may append *observations* through the agent path with its own `source`; it never writes notes, confirmations or visibility.
7. **Raw and derived never share a line.** A source's own fields (a provider's summary, participants, ids) are the raw line. Anything a model extracted (decisions, action items, entities) is a separate extraction, a draft until accepted.

**Consequences.** The interpreter can be replaced, or run alongside a second one, without touching the record. Every question of the form "should X enter the Logbook?" is answered "yes, classified"; every question "should X go to the interpreter?" is answered by an export rule the owner can change and re-run.
