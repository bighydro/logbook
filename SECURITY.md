# Security

This software stores a person's whole life. Treat every bug as if it were serious.

## Reporting

Report a vulnerability privately through [GitHub's private vulnerability reporting](https://github.com/bighydro/logbook/security/advisories/new), or to the address in the repository profile. You will get a reply within 48 hours. The fix ships before the report is disclosed, and the advisory names you unless you ask it not to.

## Threat model

**What is protected.** One folder on a machine the owner controls: the record (`logbook/<YYYY>/<MM>.jsonl`), the notes, the attachments, the policy files and the owner's signing key. The record is the whole of a person's whereabouts, company, words, health and money, so a copy of the folder is the asset, and the chain head is the proof that nobody changed it.

**Who the adversary is.** Anyone who obtains the files: a stolen laptop, a backup disk in the wrong hands, a cloud drive the folder was mistakenly placed in, malware on the machine, a member of the owner's circle who was handed one page and wants the rest, and an agent that was given read access and asked for more. The adversary is not assumed to hold the owner's key.

**What is defended today.**

- *Integrity.* Every line carries the hash of the one before (SPEC §3). `verify` finds any edit, removal or reordering, and a broken chain is an error, never repaired silently. Nothing in the code updates or deletes a line; a correction is a new line that retracts an old one.
- *Nothing leaves.* There is no server and no account, and reading never opens a connection. Every reader touches the record and the tables shipped in the package, nothing else. `tests/test_no_network.py` replaces the socket, `urllib`, `http.client` and, where installed, the `httpx`, `requests` and `websockets` request paths with ones that record and refuse every connection, runs every reader against the demo record and every page of `serve` through it, and fails if any of them asked for one, whatever it printed or caught. A socket opens only behind a command that says so: `sync` for the live source it names, `transcribe --fetch-model` and its siblings for a model this machine has not got, `serve` listening on 127.0.0.1 and refusing any other host. A change that needs a reader to fetch anything is wrong; a new reader goes into that test's list.
- *The circle.* A shared page or trip is a bundle signed with the owner's Ed25519 key, holding only the lines the owner's `policy/crossing.json` lets cross to that one named person at their tier ceiling. The receiver verifies the signature and keeps the bundle beside the record, never in its chain. The default ceiling for every destination, including an agent over MCP, is tier 1: the shape of the days and no note, message, name, health or money.
- *Adapters.* An adapter is untrusted code that runs without network by default, never writes to its source, and can only append. An app store is opened read-only after its schema is confirmed with `PRAGMA table_info`; a phone backup is copied into `inbox/` and never modified.
- *Agents.* An agent over MCP may read within its ceiling and run adapters; it cannot write a note, a confirmation or a visibility decision. Tier 3 reaches it only when the policy file allows it and the server was started with `--allow-tier-3`.

**What is not defended yet, and what to do about it.**

- *Confidentiality at rest.* The record is plain text. Tiers 2 and 3 are marked, not encrypted; the encryption envelope is specified for a later version (SPEC §4, with a benchmark in `docs/rfcs/bench-encryption-2026-10.md`). Until then the protection is the one the operating system gives: full-disk encryption on every machine and backup disk that holds the folder, and never a folder a sync client owns (`logbook setup` refuses one).
- *The key.* The sharing key is a file under `~/.config/logbook/share/`, outside the record and readable by the owner alone, so a copy of the folder cannot sign as the owner. Whoever holds that file can. A lost key means a new one, and every member of the circle learns the new public half.
- *Malware with the owner's privileges* can read the files and append to the chain. The chain shows that something was appended and when; it cannot show who typed it.
- *What a page reveals.* A member who receives a page at tier 2 receives the notes on it. The policy file is the owner's decision; an export's `--dry-run` lists what would cross, and an agent's answer says how many lines sat above its ceiling and were left out, so the owner can see what a raise would release.

**Out of scope.** The security of the services the exports come from, the phone's own backup encryption (which `import-backup` decrypts only with the owner's password, locally), and the model files `transcribe`, `promises --judge` and `describe` download on request.

## Housekeeping

Dependencies are pinned in `uv.lock` and raised by Dependabot. Every release wheel carries SLSA provenance and is published to PyPI through trusted publishing; nothing is signed by a human's laptop. `gitleaks` and the PII check run on every commit, so no secret and no real identifier enters the tree.
