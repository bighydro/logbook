# ADR 0005 — One nudge, one channel

Status: accepted · 2026-09-13

**Context.** Several automations could each ask the owner questions in the evening (place confirmations, discoveries, the day's question).

**Decision.** There is one nudge queue and one evening message. Every automation that wants to ask something puts it in that queue; the delivery layer sends at most one message a day and suppresses routine noise. No streaks, no scores.

**Consequences.** A second bot is a bug. The queue is a layer-5 concern; the Logbook itself never sends anything.
