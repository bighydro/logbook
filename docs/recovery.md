# When verify fails

`logbook verify` reads the files alone and says one of a few things. Each has one answer; none of them
is "edit a month file". The chain is the record, so every repair below moves lines, appends lines or
brings `logbook.json` forward, and never rewrites a line in place.

| `verify` says | What happened | What to run |
|---|---|---|
| `logbook.json says seq=N …, files say seq=N+k …` and nothing else | a crash between the files and `logbook.json` (SPEC §3, write order): the files are ahead, every line past `seq` is a chained tail | `logbook repair index` rebuilds the locator; the next append brings `logbook.json` forward. A `logbook.json` behind by one `sync` batch is the normal shape of this |
| `… line n: the file ends inside this line (cut short)` | a crash tore the last line of a month file; the lines before it are whole and verify reports their head | restore that month file from the last backup, or cut the torn line and bring `logbook.json` to the head `verify` printed; `repair fork` does not mend a torn file |
| `seq N expected N+1` and `prev does not match previous hash` on every second line from one seq | two chains fork at one head (#234): a long writer wrote its batch chained from a head another writer had already moved past | `logbook repair fork`, then `logbook repair fork --apply` |
| `created as logbook/0.1 …` | the record was hashed by the rule before the RFC 8785 fix | `logbook repair migrate` |
| `hash does not recompute` on one line | a byte of a line changed on disk, or was changed | restore from backup; the chain says which line |

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
  main chain: 4,804,871 lines, seq 1–4804871, head 4dc18fde900d…; the index agrees (its head is on it)
  orphan chain: 4,309 lines, seq 4803134–4807442, head e4b3b64c294d…, forked at seq 4803133; sources: immich 4,309; files: logbook/2026/09.jsonl, logbook/2026/10.jsonl
logbook.json says seq=4807442 head=e4b3b64c294d…; the main chain ends at seq=4804871 head=4dc18fde900d…
nothing written — run with --apply to repair
```

Which chain is the record is decided in this order: the chain the index agrees with (the index records
the head it was built at; the chain that head is on); with no index, or one built before the fork, the
longer chain; and when two chains are equally long and the index cannot say, no one: the diagnosis says
`cannot tell which chain is the record` and `--apply` refuses. Every other chain is an orphan. Look at
the orphan's sources and seq range before applying: it should be the batch you know went wrong.

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

[Backup](backup.md) says how to keep a snapshot so that the first row of the table is the only one you
ever meet.
