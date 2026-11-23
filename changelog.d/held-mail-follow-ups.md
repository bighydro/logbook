### Fixed

- Held mail answers only at its gate: the door's `held_mail` answers only when the `mcp` entry says `"held_mail": true`, a mail above its ceiling is absent (no `above_ceiling`, nothing withheld in the log), and `export crossing --mail all-except-junk` below tier 3 reads no portfolio, no person and no earlier mail above its tiers.
- No count beside a destination's key: `day sign` says `7 mails held back (3 from a first-time sender) by the mail_junk rule for per-hansen`, and `export crossing` names "the destination" with words between its key and every figure.
- A missing, unreadable or malformed `policy/owner.json` fails closed: `--mail all-except-junk` and `--mail all` send people's mail only and say in one sentence what is wrong with the file, `day sign` counts no held mail instead of failing after the signature, and the door's `held_mail` is refused.
