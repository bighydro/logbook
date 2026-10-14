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
