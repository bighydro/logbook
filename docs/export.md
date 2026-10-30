# A day to a folder

`logbook export --day DAY --out DIR` writes one day of the record to a folder as a day package
(`day-package/v1`, ADR 0013 §4): `DIR/package.json`, one entry per line of the day — its id, when,
kind, tier and source, never its payload. `--days FROM TO --out DIR` writes one folder per day under
`DIR`, skipping a day with no line of the tiers asked for unless `--empty`. Without `--out` the folder is `<record>/export/DAY`.

```bash
logbook export --day 2026-06-17 --out ~/Handover/june-17
logbook export --day 2026-06-17 --out ~/Handover/june-17 --tier 1     # tier 1 alone, under any entry
logbook export --days 2026-06-15 2026-06-21 --out ~/Handover/the-boat-week
```

## The ceiling is the policy's

Like every other export, a folder holds what `policy/crossing.json` lets cross to it, from its `folder`
entry, as the vault and the site read theirs ([the crossing](crossing.md), ADR 0016):

```json
{"mcp": {"max_tier": 1}, "folder": {"max_tier": 2}}
```

Without the entry it is tier 1, where you were and what happened. With it, the folder holds every tier up
to the entry's `max_tier`: 2 adds what was said, 3 the lines that never leave otherwise. `--tier` may
lower it (`--tier 1`), never raise it: `--tier 3` under an entry at 2 is refused in one sentence that
names the entry to change, and nothing is written.

## The line that says it left

Like every other export, the run leaves one `crossing/v1` line in the record (RFC 0011), after the folder
is written (a run that writes no folder leaves none), so a page leaves only on a command you type, to a place you name, and your record keeps a
line that says it left. A folder, the vault, the site and the world are your own copies, so they take no
signed-day gate and hold a day you have not signed as one you have, while `export crossing` and `export
share day`, which send a day to someone else, hold back every day you have not signed (RFC 0034):

```
2026-06-17: 437 entries → /Users/ines/Handover/june-17
  recorded as #12773 crossing/v1: the folder 'june-17', tier 1, 437 lines
```

Its payload names the destination `folder`, the window of the days asked for, the tiers, the counts
(the lines of those days, the ones that crossed, by tier and by kind, the rest held back), and under
`extra` the folder's last part (`june-17`, never the whole path of this machine), the days written, the
kinds and how many lines. `package_sha256` is the folder's digest as `export vault` hashes one: each
file's sha256 and its path, in path order. `policy` says what set the ceiling: the entry by name and its
ceiling, `{"file": "policy/crossing.json", "entry": "folder", "max_tier": 2}`, or, with no entry, that
there is none and the default applied, `{"file": "policy/crossing.json", "entry": null, "default_tier":
1}`. `logbook doctor`'s `export-day` line says the same ([the doctor](doctor.md)).

The other exports, each with its own page: [the crossing](crossing.md) (a circle member's package),
[the vault](vault.md), [the site](site.md), [the world](world.md), [the letter](letter.md), [Notion](export-notion.md)
and a trip's bundle ([shared trips](trips-shared.md)). `logbook export FILE.jsonl` writes the whole log,
every line as it is, for re-entry: a copy of your own record, not a page that leaves.
