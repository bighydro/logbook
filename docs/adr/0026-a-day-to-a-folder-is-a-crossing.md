# ADR 0026 — A day written to a folder is a crossing

Status: accepted · 2026-10-27, amended 2026-10-28 (the ceiling is the policy's) · the owner's decision after the stranger test of 26 October; builds on ADR 0013 §4 (the day package), ADR 0016 (nothing crosses unseen) and RFC 0011 (`crossing/v1`); changes no line, no envelope, no SPEC

**Context.** `logbook export --day DAY --out DIR` wrote one day, every tier, to a folder and appended
nothing. The README promises that a page leaves "only on a command you type, to a place you name, and your
record keeps a line that says it left". Every other export keeps that promise: `export crossing`, the
vault, the site, the world, the letter, Notion, a trip's bundle and a shared day each append one
`crossing/v1` line. The day package did not.

**Decision.**

1. `export --day` and `export --days` read their ceiling from a `folder` entry of `policy/crossing.json`,
   as the vault and the site read theirs (ADR 0016): `{"folder": {"max_tier": 2}}`. Without the entry the
   ceiling is tier 1. A folder holds every tier up to the ceiling; `--tier` (`1`, `1,2`, `1,2,3`, or a
   bare `2` or `3` for every tier up to it) may lower it, never raise it: a tier above the ceiling is
   refused in one sentence naming the entry to write, and nothing is written.
2. A run that writes a folder appends one `crossing/v1` line, after the folder is written, through
   `Logbook.append`. Its destination is `folder`. Its window is the days asked for. It carries the tiers,
   the counts (the lines of those days, the ones that crossed, by tier and by kind) and the folder's
   digest, each file's sha256 and path in path order, as `export vault` hashes a folder. Under `extra` it
   names the folder's last part (never a path of this machine), the days written, the kinds and the line
   count. `policy.max_tier` is the `folder` entry's ceiling, 1 without one. A run that writes no folder
   appends nothing.
3. The package itself is unchanged, `day-package/v1`: entries without payloads. The line says which tiers
   the folder holds.

**Consequences.** SPEC §3.2 describes `export` among the readers that write nothing. That was already
untrue of `export crossing` and the other exports above, and now it is untrue of `--day` too. The
sentence is SPEC's to fix at its next version. A consumer of a folder that needs every tier asks the
owner for a `folder` entry at 3. docs/export.md documents the command.
