# The crossing

`logbook export crossing --to <member> --since <RFC3339|last> [--until RFC3339] [--tier 1|1,2|1,2,3]
[--kinds a,b] [--unsigned] [--open] [--out DIR] [--force] [--dry-run]` hands one member of your circle the
lines of a window that the tier policy lets cross: a `crossing-package/v1` folder
([RFC 0005](https://github.com/bighydro/logbook/blob/main/rfcs/0005-crossing-package-v1.md)) under the
member's ceiling in `policy/crossing.json` ([ADR 0016](adr/0016-tier-crossing-policy.md)), the lines of
signed days only unless `--unsigned` ([the signed day](signed-day.md)), and one `crossing/v1` line in the
chain that says what left. `--dry-run` counts and writes nothing.

```bash
logbook export crossing --to hermes --since 2026-03-01T00:00:00Z --until 2026-03-02T00:00:00Z --dry-run
logbook export crossing --to hermes --since last --out ~/Handover/hermes
```

## Drafts follow the entry they were written under

A model's draft (`draft/v1`, [the dream](dream.md)) crosses only while the entry it was written under
allows its tier, whatever the member's ceiling: a person's draft (`dream person`) the `relationship`
entry, every other draft (a day's, a journey's, a week's, a call's synthesis) the `dream` entry. Once that
entry's `until` has passed, it is removed, or its `max_tier` is below the draft's tier (and, for the
`relationship` entry, when it has no `until`), the draft stays home and `counts` says how many did,
`held_back_by_entry` (written only when one did); a record with drafts and no `dream` entry ships none of
them. A video scene's draft (`video review`) is written on this machine under no entry and crosses by its
tier like any line. With the entry in force the package is what it was.

## People's mail

Since 21 October 2026 ([RFC 0045](https://github.com/bighydro/logbook/blob/main/rfcs/0045-peoples-mail.md)),
mail crosses only when it is a person's: a mail you received from someone the record names as a person,
or one you sent to one, its sender not let go in Hold ([people's mail](mail-people.md)). Whenever mail is
among the kinds (no `--kinds`, or `--kinds` naming `mail`), the rest stays home, its resolutions and
attachments with it, and `counts` says how many as `mail_held_back`, written whenever the window held a
mail the tiers and signed days let through (`0` when every one was a person's); a package with no mail is
what it was, byte for byte. `--all-mail` crosses every mail the tiers and signed days let through, as
before, and the manifest's `policy` says `"mail": "all"`.

## The package

```
<DIR>/
  manifest.json          what crossed and why, and the list of every other file in the folder
  entries.jsonl          the lines that crossed, verbatim
  resolution.jsonl       the resolution lines their refs resolve through, when any cross
  attachments/<sha256>   the files those lines point at that the store holds
```

A line's refs are the `{kind, value}` refs in its payload (a message's sender, a calendar guest), a mail's
`from`, `to`, `cc` and `bcc` addresses, and a transcript's participants' email, phone and provider id, so
the resolution that names someone on a mail or in a transcript crosses with it.

`manifest.json` lists every other file of the package under `files`, in path order:

```json
"files": [
  {"path": "attachments/<sha256>", "sha256": "<hex sha256>", "bytes": 48213},
  {"path": "entries.jsonl", "sha256": "<hex sha256>", "bytes": 1840}
]
```

`path` is relative to the package, with `/` on every platform. `sha256` and `bytes` are those of the file
as it is in the package: for an attachment resealed to the member, of the sealed file, while its name and
its entry in `blobs` give the plaintext's. The digest of `manifest.json` itself is the `package_sha256`
the crossing line records. A reader checks that the folder holds these files and `manifest.json` and
nothing else, and hashes each one.

## The output directory

Without `--out`, every run writes a folder of its own, `<root>/export/crossing/<member>/<time>`. With
`--out DIR`, the bundle replaces DIR whole, so DIR never holds anything the new selection left out.

The bundle is built from nothing in a hidden folder beside DIR, `.DIR.<random>.staging`, on the same
disk. It is checked against its own manifest, every file in it listed in `files` and every listed file
there at its length, and only then renamed to DIR. Whatever was at DIR is first renamed aside, to
`.DIR.<random>.old`, and removed once the new bundle is in place. At every moment DIR is the earlier
bundle whole, nothing, or the new one whole, never a mix: a tier-1 crossing into the folder of an earlier
`--tier 1,2` one leaves none of its tier-2 lines, resolutions or attachments behind.

What DIR may be:

- **Missing.** It is made, and its parents with it.
- **An empty folder.** It is used.
- **An earlier bundle.** A folder whose `manifest.json` is a `crossing-package/v1` manifest, from a
  crossing or a trip bundle, of this version or an older one. It is replaced, and so is anything you put
  in it since.
- **Anything else.** A file, or a folder that holds anything and no such manifest, is refused (exit 2)
  before anything is written: no crossing line, no watermark, no policy file. `--force` replaces it and
  removes everything in it.
- **The record, or a part of it.** The record's own folder, a folder that holds it, and any path inside it
  that is not under `<root>/export/` (where the default `--out` is) are refused whatever the flags,
  `--force` included, and a path inside it is refused even before it exists, so a second run is never the
  first refused. Folders are told apart by the disk, not by the name, so `~/logbook` on a disk that
  ignores case is the record at `~/Logbook`.

A symbolic link at DIR is followed: the folder it names is replaced, and the link names the new bundle.

An export that fails, for example on a store file that no longer hashes to its name or a full disk,
removes its staging folder and leaves DIR as it was, and appends no line. A crash part of the way can
leave `.DIR.<random>.staging` (a bundle not yet in place) or `.DIR.<random>.old` (the earlier one) beside
DIR, and, between the two renames, DIR itself missing. Nothing reads either folder: delete them, and run
the export again.

Before this, a second export into the same DIR overwrote the files it wrote and left the rest. A folder
that more than one export was written into may hold files its manifest does not name: an
`attachments/<sha256>` that is not in `blobs`, or a `resolution.jsonl` when the manifest has no
`resolution_file`. Look before you hand such a folder over, or export into it once more.

`logbook export trip-bundle` ([shared trips](trips-shared.md)) writes its package the same way, its
`trip.json` among the listed files, and takes `--force` too. `logbook export notion`
([export for Notion](export-notion.md)) writes its folder the same way, its own manifest listing its
files, and replaces only an earlier folder of its own.
