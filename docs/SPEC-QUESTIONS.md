# Spec questions, answered from the reference

The TypeScript implementation, [logbook-ts](https://github.com/bighydro/logbook-ts), keeps a numbered list
of questions the spec left open when it met them, `SPEC-QUESTIONS.md`, and the two implementations settle
them one at a time: by a rule in [SPEC.md](SPEC.md) when the answer is the format's, by a note here when it is
an implementation's own choice that the other should know of. The numbers are logbook-ts's. Questions an
earlier release settled are recorded in [CHANGELOG.md](CHANGELOG.md) under that release and are not repeated
here; this file holds the ones answered without a spec change, so that the two sides can be told apart and
aligned in a follow-up.

## 83. A crash between a line and logbook.json: who brings logbook.json forward, and when?

**The question.** SPEC §3 orders a write as the line (fsynced), then `logbook.json`, then the index, so a
process that dies in between leaves the files ahead of `logbook.json`: every line past its `seq` is a
complete, chained tail. The spec says `verify` reports such a record invalid until `logbook.json` is brought
forward, and does not say who brings it forward, or when. Both implementations had the same bug: the next
append chained from the head `logbook.json` named, which the files were already past, and wrote a second
line of the same seq.

**logbook-ts (its pull request #18): validated auto-recovery.** On the next open, the tail past the head is
verified and, when it verifies, `logbook.json` is brought forward to it; the command the owner ran goes on
without asking.

**The reference (this pull request): explicit.** `append` and `append_many` refuse while the files are
ahead, in one sentence naming `logbook repair tail`, and write nothing. `repair tail --dry-run` lists the
tail by seq, file, line and hash; `repair tail` verifies every line past the head as `verify` does and
only then sets `logbook.json` to the last of them, then the index. [When verify fails](recovery.md) has
the procedure.

**Why the reference keeps it explicit.** A `logbook.json` behind the files is the one trace a crash leaves,
and what it says is that a process died mid-write: a kill, a power cut, a disk that went away, a bug. The
auto-forward is safe when the tail verifies, which it does by construction in the crash case, and the
reference's `repair tail` does exactly the same check. The difference is what the owner is left with. An
explicit repair leaves the owner a decision point, the dry run in front of them, and a line in the shell
history saying it was run and when; the refusal that precedes it names the crash the moment the owner next
writes, so a machine that keeps dying mid-write is noticed on the second time, not never. An auto-forward
leaves none of that: the record is mended before anyone looks, and the crash that caused it is not seen.
Both are correct for the format, since neither rewrites a line and both end at the same head; the spec is
not changed by either. Aligning the two is a follow-up on the logbook-ts side (an explicit repair, or the
auto-forward kept behind a switch with a line printed when it runs), and SPEC §3 may then say which is the
rule.

**What both agree on, and the spec already says.** The index is written after `logbook.json`, so a crash
leaves at most the files ahead, never `logbook.json` or the index ahead of the files; a tail that does not
verify (a torn last line, a changed byte) is never adopted by either; and the files behind `logbook.json`
is not a crash's shape and is refused by both.

## A line superseded twice, the later superseder retracted (the reference's issue #321)

**The question.** SPEC §3.2 calls a line **standing** when it is not retracted and no later line of the same
kind names it in `payload.supersedes`. Read to the letter, a retracted superseder still names the line, so
the line it names never stands again; read as the Day read it, a retracted line is out of the record's
reading and supersedes nothing. The reference held both readings at once: `Index.superseded` answered the
*last* superseder of a line and its readers dropped the line only when that last one was not retracted,
while the Day dropped a transcript when *any* superseder of the day stood. They agree on a chain and
disagree when one line is superseded by two. Synthetic: Ines Nordmann records a dinner on 3 October 2026; A
is the transcript, B and C are both heard again with `supersedes: A`, and C is retracted. The Day showed
one dinner, B; `review speakers` and the voiceprint registry read A as standing again, beside B.

**The reference (the owner's v1 choice, 18 October 2026): any superseder that is not retracted.** A line
is superseded while at least one line of its kind that is not retracted supersedes it. A retracted
superseder supersedes nothing, so retracting every superseder of a line stands the line again; a superseder
that is itself superseded still supersedes (A←B←C hides A and B), so a correction of a correction never
brings back the line the first one corrected. `Index.superseded` answers by this rule, the last superseder
that is not retracted, and every reader that asks it (`show`, `review speakers`, the voiceprint registry,
the MCP door, `people`, `promises` and the rest) reads by it with the Day:

| Lines (each a transcript of the same dinner) | Superseded | Standing |
|---|---|---|
| B and C supersede A | A | B, C |
| B and C supersede A; C retracted | A | B |
| B and C supersede A; B and C retracted | none | A |
| A←B←C | A, B | C |
| A←B←C; C retracted | A | B |
| A←B←C; B retracted | none (B's mark on A is void) | A, C |

Retractions are not superseders in this sense and do not change: RFC 0003 forbids retracting a retraction,
and a line retracted more than once is retracted by the one of highest seq (its rule 4). `search` still
finds a superseded line, as `show` still lists it with its mark (`docs/search.md`); it never finds a
retracted one.

**What the spec would say.** SPEC §3.2, the sentence on standing, would read: *A line is **standing** when
it is not retracted (RFC 0003) and no line of the same kind that is itself not retracted names it in
`payload.supersedes`; a superseder superseded in turn still supersedes.* The wording is proposed on the
pull request that settled this here, for the spec's next version; logbook-ts follows the reference or says
why not.
