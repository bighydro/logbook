# Governance

**Captain.** A ship has one captain and the captain signs the log. bighydro writes the specification, merges, releases, and writes the letters. bighydro is a pen name and stays one; the project is judged by its documents and its two implementations, not by its author.

**What changes how.**
- The envelope (SPEC §1–3) changes only by major version, with a migration tool, after both implementations pass the new fixture.
- A payload profile changes through an RFC in rfcs/: a pull request with the schema, one synthetic fixture and the readers it affects; two weeks of public comment; a second implementation that emits or reads it; merge. A frozen profile (v1.0) changes only by a new version alongside the old.
- Architecture decisions are ADRs in docs/adr/. Everything else is a pull request with a changelog fragment.

**Two implementations.** No version of the format is final until two independent implementations agree on the conformance fixture for every reader SPEC §6.1 names. Disagreement is a specification bug until proven otherwise.

**Merging.** Signed commits only. Synthetic data only. Readers open no network connection, and CI checks it. A pull request that touches the format needs one review from someone other than its author; today that is often a reviewing agent, and we say so.

**Disagreement.** Decisions are made in public issues. When a contributor and the captain disagree, the captain decides and writes down why in the issue. A decision can be reopened by a new argument, never by repetition.

**Succession.** If the captain is silent for twelve months, the most recent two contributors with merged format changes may jointly tag a release and amend this file. When the project has three officers of the watch, this file is replaced by a charter and the specification moves to a foundation that no one involved controls. That is the intention from the first day, written here so that it can be held against us.
