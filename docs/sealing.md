# A sealed record on this disk

A record is **sealed** when `logbook.json` names its recipients (`"recipients": [...]`, two or more;
[RFC 0029](../rfcs/0029-encryption-at-rest.md)): every tier 2 and 3 line is written as ciphertext, and
only a machine that holds the identity opens it. This page is about what a sealed record leaves on this
machine's disk in plain text besides its own folder, and the one setting that changes it.

## What stays off the disk

On a sealed record, nothing read from its tier 2 and 3 lines is kept on this disk in plain text by
default. The readings the Library and the commands keep between one head and the next stay in the
process's memory for its life, and go when it stops:

- **The kept readings** beside the index (the whole record's people, the promises, each person's last
  real contact, the orgs, ideas, places, gaps, agents' sessions and the World's years:
  `<cache dir>/logbook/<owner_id>/*.json` on a record that seals nothing). Every such file left there
  from before, whatever reading kept it, and any a crash left half written, is removed by the first
  reading of the record in each process.
- **The review pages' tables** of observed people, orgs, ideas, assets and places, which a record that
  seals nothing keeps in `index.sqlite`. Rows left there from before are removed by the next reading.
- **The Library's built pages** ([built ahead](serve.md#built-ahead)): `logbook serve --built` renders
  every page as it is asked for, to its end as live does, and says so when it starts; `logbook serve
  --build` refuses in one sentence, and the 06:00 close says the build is off. A build left from
  before is removed. No page is built, not even one of tier 1: it still names who is who from the
  resolutions, which are tier 2.

The cost is time, not correctness: a server reads the whole record once after it starts, where a record
that seals nothing would bring a kept reading forward, and every page is rendered as it is asked for.
Each page is the same either way.

## `plaintext_cache`: keeping them on the disk

To keep those readings and pages on this disk anyway, set `plaintext_cache` in `logbook.json`:

```json
{
  "...": "the keys already there, unchanged",
  "plaintext_cache": true
}
```

Off by default; absent, `false` or anything but `true` is off. With it on, a sealed record keeps its
readings, tables and built pages on this disk as a record that seals nothing does: in the cache folder
beside the index, never in the record's folder, each file `0600` and the folders `0700`, so only this
machine's user reads them, and a copy of the record never carries them. They then hold, in plain text,
what the Library shows of the sealed lines. No command writes this setting yet: edit `logbook.json` by
hand, keep it valid JSON, and leave `seq` and `head` as they are. Turning it off again removes the
readings and pages the next time each would be kept.

This was decided for v1 in [RFC 0047](../rfcs/0047-the-librarys-doors.md) §15 (question 11); the owner
may revisit it.

## What is on the disk regardless

- **The index**, `index.sqlite`, in the cache folder. For every line, sealed or not, it holds the
  envelope (its seq, id, time, local day, kind, source, tier, `end`) and where the line is in its file.
  For a sealed line opened with the identity it also holds, in plain text, a few fields of the opened
  payload that readers look lines up by: the id it `supersedes`, the entity a resolution mints, the
  digest of its attachment, the `subject` of a point, and a point's `lat` and `lon`. Its `raw_id` is
  blinded (RFC 0029 §8). These columns are the index's own, decided in RFC 0029 §8, and this setting
  does not change them.
- **Rows removed from `index.sqlite`** can stay in the file's free pages until it is written again whole.
  To be sure none of them is left after you turn `plaintext_cache` off, delete `index.sqlite` (it is a
  cache: the next command builds it again, [ADR 0007](adr/0007-sqlite-default-index.md)).
- **The browser's own cache** of the pages you opened, as for any site.
- **What you export or hand on yourself**: a vault, a site, a crossing, a relationship store, a dream's
  input. Each is a command you run, and each says where it writes.
