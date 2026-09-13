# ADR 0006 — The hash chain is mandatory

Status: accepted · 2026-09-13

**Context.** An optional chain would lower the bar for new implementations; a mandatory one makes every conformant logbook tamper-evident.

**Decision.** The chain (SPEC §3) is required for conformance. It is invisible to the person: `add` computes it, `verify` checks it, nothing else mentions it.

**Consequences.** A file that does not chain is not a logbook. Implementations must pass the conformance fixture. Simplicity is delivered by hiding the chain, never by removing it.
