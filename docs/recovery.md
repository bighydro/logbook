# When verify fails

`logbook verify` reads the files alone and says one of a few things. Each has one answer; none of them
is "edit a month file". The chain is the record, so every repair below moves lines, appends lines or
brings `logbook.json` forward, and never rewrites a line in place. The two commands that give every line
a new hash, `repair migrate` and `key seal --all`, verify the whole record first, every hash under the rule
it was written with and every link, and refuse with the first failing line and its id when it does not, so
a record in this table is put right before it is migrated or sealed and never by being migrated or sealed.

| `verify` says | What happened | What to run |
|---|---|---|
| `logbook.json says seq=N …, files say seq=N+k …` and nothing else | a crash between the files and `logbook.json` (SPEC §3, write order): the files are ahead, every line past `seq` is a chained tail | `logbook repair index` rebuilds the locator; the next append brings `logbook.json` forward. A `logbook.json` behind by one `sync` batch is the normal shape of this |
| `… line n: the file ends inside this line (cut short)` | a crash tore the last line of a month file; the lines before it are whole and verify reports their head | restore that month file from the last backup, or cut the torn line and bring `logbook.json` to the head `verify` printed; `repair fork` does not mend a torn file |
| `seq N expected N+1` and `prev does not match previous hash` on every second line from one seq | two chains fork at one head (#234): a long writer wrote its batch chained from a head another writer had already moved past | `logbook repair fork`, then `logbook repair fork --apply` |
| `created as logbook/0.1 …` | the record was hashed by the rule before the RFC 8785 fix | `logbook repair migrate` |
| `hash does not recompute` on one line | a byte of a line changed on disk, or was changed | restore from backup; the chain says which line |
| `line n: at '…' is not an RFC 3339 instant (SPEC §2)`, or `end`, `recorded_at` | the line carries a timestamp that names no instant (`not-a-dateZ`, `2026-02-30T07:30:00Z`): a line made by hand or by another tool, or one an earlier release appended, which took any stamp ending in `Z`. The index cannot place it either | the stamp is inside the line's hash and no command edits a line: restore the record from the last backup taken before that line, then sync again (`sync` skips what the record already has) and add back by hand what came after |
| `line n: attachments/<sha256> holds bytes that hash to …, not its name (SPEC §1.1)` | the file the line names changed on disk: the line is right, the store is not | restore that one file from a backup; `logbook backup --verify` hashes a snapshot's files the same way |
| `line n: attachments/<sha256> opens to bytes that do not hash to its name (SPEC §1.1)` | a sealed file was replaced by one that opens with your identity and holds other bytes, which anyone with your recipients can make; only the identity tells the two apart | restore that file from a backup, and find what wrote it |
| `line n: attachments/<sha256> does not open with this identity: …` | a sealed file sealed to other recipients, or damaged | restore that file from a backup; `logbook key show` names the recipients the record seals to |

A file the lines name that the store does not hold is not in this table: `verify` lists it and stays valid
([below](#the-files-the-lines-name)).

## Two chains forked at one head

The shape: a `sync` that walked a source for two hours read the head when it started. Meanwhile another
command appended a batch, correctly chained from that head. When the long `sync` wrote its own batch it
chained it from the head it had read, into the month files, before the index refused it (`UNIQUE
constraint failed: lines.seq`). The files now hold two chains from one head; the index, which never
took the second batch, still describes the first; `logbook.json` names the second's head.

```bash
logbook repair fork            # the diagnosis; writes nothing
logbook repair fork --apply    # the repair
```

The diagnosis walks every line of every month file, links the lines into chains by `prev`, and prints
what it found, counts and hashes only, never a line's contents:

```
fork at seq 4803133, head da9813c3cf40…: 2 chains continue from it
  main chain: 4,804,871 lines, seq 1–4804871, head 4dc18fde900da55538fbd134e48652282d044bc2ec8c28ac0573fee15506b599; the index agrees (its head is on it)
  orphan chain: 4,309 lines, seq 4803134–4807442, head e4b3b64c294d1f0a7c3e9b2d8f6a4c1e0b5d7f9a3c2e8d6b4f1a0c9e7d5b3a2f, forked at seq 4803133; sources: immich 4,309; files: logbook/2026/09.jsonl, logbook/2026/10.jsonl
logbook.json says seq=4807442 head=e4b3b64c294d…; the main chain ends at seq=4804871 head=4dc18fde900d…
nothing written — run with --apply to repair
```

Which chain is the record is decided in this order: the chain the index agrees with (the index records
the head it was built at; the chain that head is on); with no index, or one built before the fork, the
longer chain; and when two chains are equally long and the index cannot say, no one: the diagnosis says
`cannot tell which chain is the record` and `--apply` refuses. Every other chain is an orphan. Look at
the orphan's sources and seq range before applying: it should be the batch you know went wrong.

When you know which chain is the record, say so: `--keep-head <head>` takes the full head of the chain
to keep, as the dry run prints it for every chain, or a unique prefix of eight characters at least, and
overrides both rules; a head no chain ends in is refused. Without an index the longer chain is only a
guess, and the dry run says in one sentence that `--keep-head` is the safer choice: in the incident
above the stray batch was the longer chain, and only the index knew better.

```bash
logbook repair fork --keep-head 4dc18fde900da55538fbd134e48652282d044bc2ec8c28ac0573fee15506b599
logbook repair fork --keep-head 4dc18fde900d --apply
```

`--apply` does, in this order:

1. copies every orphan line, in seq order, to `repair/<UTC stamp>-removed.jsonl` inside the record
   folder, and writes `repair/<UTC stamp>-report.json` with everything the diagnosis printed. Nothing is
   deleted; the lines leave the chain and stay in the folder;
2. writes each touched month file again without the orphan lines: every kept line is the bytes it was,
   copied through a temporary file and renamed into place, fsynced. No main-chain line is touched, and
   a file that changed since the diagnosis stops the command before anything is written;
3. sets `logbook.json` to the main chain's last seq and head, rebuilds the index, and runs `verify`.
   Its result is the command's: `valid — …`, or `INVALID` with exit 1, in which case it says so and does
   not try again.

It refuses, and writes nothing, when the record's chain cannot be told, when a line chains from no line
of the record (a break, not a fork), when a month file is cut inside a line, when an orphan line is
sealed and the identity that opens it is not here (what leaves the chain is read first), and when the
record folder is under a sync client's folder (`doctor`'s folder check: iCloud Drive, Dropbox, OneDrive,
Google Drive). The dry run always works.

The orphan lines are observations too; a source that is synced again will bring them back, chained
correctly, and `append_many` skips the ones the record already has by `raw_id`. To put them back by hand,
`logbook add repair/<stamp>-removed.jsonl` appends them as new lines at the head.

## The files the lines name

The chain covers lines, not bytes, but a line names its files by digest ([SPEC §1.1](SPEC.md#11-attachments)),
so after the lines `verify` looks for every file of the attachment store a line names: a reference whose
`path` is `attachments/<sha256>`, or an adapter's pre-attach hash (`extra.media` with a `local_path`, the
file `logbook attach import-backup` fills in), in a sealed line when the identity opens it. A digest alone
names no file of the store and is not looked for: a mail attachment counted and not kept, a body hashed and
never kept, a signed day's page. Each file is looked at once, the first line that names it standing for
the rest, and every line counts, a retracted one too:

- **missing**: listed under `attachments:` with that line, and not an error: `verify` stays valid and exits
  0, as SPEC §1.1 requires. `logbook attach status` counts them by source; a phone source's media is
  missing until `attach import-backup` has run.
- **present and plain**: hashed against its name; bytes that hash to anything else are an error naming the
  line (the table above). `--no-attachment-digests` leaves present plain files unhashed, for a
  store too large to read on every run, and counts them `not hashed`; a missing file is still listed.
- **present and sealed**: with the identity, opened and its plaintext hashed against its name; a mismatch,
  or a file that does not open, is an error (the last two rows). A verifier with the key must make this
  check (SPEC §1.1 and §3), so `--no-attachment-digests` does not skip it. Without the identity, or with
  `--keyless`, a sealed file is counted `sealed and not opened`.

```
valid — 1204 lines, head 4dc18fde900da55538fbd134e48652282d044bc2ec8c28ac0573fee15506b599
  attachments: 3 files named by the lines; 2 present, checked against their name; 1 missing, reported and not an error (SPEC §1.1):
    attachments/9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08 (line 29)
```

Twenty missing files are listed by name, the rest counted. `doctor` looks for the same files and counts the
missing ones in its `record` line, which still passes; it does not hash them, since it runs four times a
day ([The doctor](doctor.md)). `logbook attach verify` is the other walk: every file in the store, named by
a line or not, against its name ([The attachment store](attachments.md)).

## Timestamps

`at`, `end` (when it is not null) and `recorded_at` are RFC 3339 instants ([SPEC §2](SPEC.md#2-the-line-the-envelope)).
`append` refuses a stamp that is not one, whatever it ends in, and keeps one that is exactly as it was
given, since the string is hashed as written: `07:30:00Z` and `07:30:00.000Z` both stand. `verify` reports
a line whose stamp is not one as an error naming the line (the table above); a stamp that is an instant but
is written with an offset, `+01:00`, is a warning this release and an error in the next. A leap second
(`23:59:60Z`) and the year 0000 are refused too: no reader here can place them on a day.

[Backup](backup.md) says how to keep a snapshot so that the first row of the table is the only one you
ever meet.
