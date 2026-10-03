# Open problems

A format earns collaborators by stating what it cannot yet do. These are the problems Logbook has not solved, in the order they block v1.0. Each names what is settled, what is not, and where the discussion lives. Corrections to this list are the most welcome pull request there is.

1. **Canonicalisation across languages.** RFC 8785 fixes the bytes that are hashed, and two implementations agree on the fixture today. Not settled: whether every JSON library's number formatting survives round trips for the values a life produces (coordinates to seven decimals, nanosecond timestamps from Google Fit, durations as floats). A third implementation in a language with different float semantics (Go, Rust, Swift) would tell us. SPEC §3; conformance/.

2. **Resolving people without a directory.** Lines name people by phone, email and handle; resolution lines (RFC 0006) bind them to a person the owner names, with alias hops bounded at three. Not settled: the same person across two records (your Kari and my Kari), merges that later turn out wrong, and a person who asks to be forgotten from someone else's log. There is no global identifier and there must not be one. rfcs/0006; people_merge.

3. **The circle's transport and its trust model.** The shared-page bundle (RFC 0025) is signed and verifiable by file. Not settled: how two records find each other, whether a handed page can be revoked, what the recipient may do with it, and how consent is recorded on both sides. The bundle came first so that transport could come second; transport is the first real protocol question. ADR 0009; rfcs/0025.

4. **Sealing without losing verifiability.** SPEC v0.3 seals tiers 2 and 3 at rest with age while keeping keyless verify, by chaining over a salted digest with the ciphertext beside it. Not settled: key custody for twenty years, the blinded index's actual leakage under a motivated reader of index.sqlite, and recovery from a lost key for the tiers that matter most. PR #143; docs/rfcs/draft-encryption-at-rest.md.

5. **What a day is.** The Day spec (docs/day.md) derives stays, moves, nights and company from location, calendar, photos and transcripts, with named constants. Not settled: a tracker that goes silent indoors, two people with two phones in one car, time zones across a date line, and whether a night aboard a moving vessel is at a place at all. Every constant in policy/stays.json is a hypothesis.

6. **Evidence for company.** "Who was there" is confirmed by a timed calendar entry, a transcript or a note, and proposed by a face. Not settled: the error rates of each, how proposals should decay or be dismissed, and how to say "with" about someone who never agreed to be in anyone's log. Rule 5 is the constraint; the mechanism is open.

7. **Schema evolution without rewriting.** Profiles are versioned (photo/v1) and lines are never edited. Not settled: how a reader of 2046 handles a payload shape from 2026 it has never seen, and whether a profile may ever be deprecated. The answer so far is "readers tolerate, writers never remove"; it has not been tested across a decade.

8. **Custody.** A record that changes hands: a child's until eighteen, an executor's after a death, a vessel's with its sale. Draft RFCs 0029 and 0030 exist. Not settled: almost everything, including whether the law in any jurisdiction recognises a hash chain as a record of custody.

9. **Time.** at, end and recorded_at are UTC; tz is the owner's zone at the time; the record's zone localises everything. Not settled: a line whose zone is unknowable (a photo with no location, imported from a service that stripped the offset), leap seconds in a chain that orders by instant, and the IANA database editions two implementations may disagree on.

10. **The second implementation's independence.** logbook-ts was written from the spec text alone and agrees on verify, append and show. Not settled: whether it stays independent as its author reads the reference to port the readers, and how to keep two implementations honest when one person maintains both. A third implementer who has read neither is the real test.

If you have solved one of these elsewhere, say so in an issue with the reference. If you think one is wrongly stated, that is the most useful issue of all.
