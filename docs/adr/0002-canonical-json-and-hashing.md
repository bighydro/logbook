# ADR 0002 — Canonicalisation and hashing

Status: accepted · 2026-09-13

**Decision.** Content is canonicalised per RFC 8785 (JSON Canonicalization Scheme): sorted keys, no whitespace, UTF-8, ES6 number serialisation. The reference implementation uses Python's `json.dumps(sort_keys=True, separators=(",",":"))`, which agrees with JCS for all fixtures; a JCS conformance vector is tested and a full JCS implementation is a v0.2 task. Hash is SHA-256. Line ids are UUIDv7 (time-ordered) and sit outside the hash so they may be assigned at write time. Signatures (Ed25519 over the month's head) and encryption (HPKE, RFC 9180, or age) are v0.2.
