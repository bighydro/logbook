# ADR 0003 — One log

Status: accepted · 2026-09-13

**Context.** Earlier designs sketched a separate `events.jsonl` event stream for other tools alongside the Logbook, and a future reader ("Aion") consuming it.

**Decision.** There is one log: the Logbook. Any other tool that wants to record an event writes a line here through an adapter or as a `manual` line. Readers read the Logbook. No parallel event stream exists.

**Consequences.** Every derived system is a consumer of the Logbook, never a peer of it. Adapters are the only way in; `Logbook.append` is the only write.
