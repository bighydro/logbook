# The attachment store

`<root>/attachments/<sha256>` is where the record keeps the bytes a line points at: a photo, a voice
message, a transcript (SPEC §1.1, ADR 0015). One file per distinct content, named by the lowercase
hex SHA-256 of its exact bytes, no extension, no subdirectories. The store is write-once and never
pruned; a line that points at a file is the reason the file stays. The chain covers lines, not
bytes: the digest is in the line, so a changed file is detectable, and `verify` of the chain never
fails because a file is missing.

Three commands tend it. None of them appends a line.

```bash
logbook attach import-backup <backup> --only whatsapp,imessage,photos            # fill it from the phone
logbook attach import-backup <backup> --only photos --since 2026-01-01 --dry-run  # what it would store
logbook attach status                                                           # referenced, present, missing
logbook attach verify                                                           # every file against its name
```

## Where the references come from

A phone adapter writes the line first and leaves the bytes on the phone. The line names the file by
digest and by where the phone keeps it, under `extra.media`, the same shape for every source:

| Source | `extra.media.local_path` | The file in the backup |
|---|---|---|
| `whatsapp` | `Media/<jid>/a/b/photo.jpg`, below the app's `Message/` folder | the WhatsApp app group, `Message/<local_path>` |
| `imessage` | `~/Library/SMS/Attachments/ab/12/<guid>/<name>`, or the same under `/var/mobile/` | `MediaDomain`, `Library/SMS/Attachments/<the part after Attachments>`; a message with several files keeps the rest under `extra.more_media` |
| `apple-photos` | `DCIM/100APPLE/IMG_0001.HEIC`, below the library's `Media/` folder (`ZDIRECTORY/ZFILENAME`) | `CameraRollDomain`, `Media/<local_path>`; the digest is also RFC 0002 `content_hash` |

`import-backup` hashes each file as it writes the line — WhatsApp's and Messages' from the copies it
made beside the store, the Photos library's straight from the backup, decrypted on the way when the
backup is and never copied — so the line carries `{local_path, sha256, bytes}`. A file that was not
there is `extra.media_missing` and counted; the line then names no digest, and no pass can fetch
what the backup does not hold. `LOGBOOK_WHATSAPP_HASH_MEDIA=0`, `LOGBOOK_IMESSAGE_HASH_MEDIA=0` and
`LOGBOOK_APPLE_PHOTOS_HASH_MEDIA=0` skip the hashing on a large store; such a line carries the path
alone and is counted as `without a digest` by the pass.

A synthetic line, the Oslo persona's:

```json
{"at":"2026-03-02T17:44:10Z","end":null,"tz":null,"source":"whatsapp","kind":"message","tier":2,
 "payload":{"schema":"message/v1","raw_id":"4790000001@s.whatsapp.net:3EB0A1F5C2D4E6B9","from_me":false,
  "media_kind":"image","extra":{"media":{"local_path":"Media/4790000001@s.whatsapp.net/a/b/photo.jpg",
  "sha256":"5f0c…a41e","bytes":21}}}}
```

## `attach import-backup`

`logbook attach import-backup <backup> --only <sources> [--since YYYY-MM-DD] [--dry-run]` reads, through
the index, every standing line of the sources named — `whatsapp`, `imessage`, `photos` (or
`apple-photos`); not a retracted line; from the local day `--since` on when given — and for every
digest they name:

- a file already under that name in the store is **present**: skipped without being read, which is
  what makes a run resumable — stop it anywhere, run it again, and it carries on with what is left;
- a file the backup's `Manifest.db` lists at the line's path, with its bytes there, is **stored**:
  streamed from the backup a chunk at a time — decrypted on the way when the backup is, with the
  password from `LOGBOOK_BACKUP_PASSWORD` exactly as `import-backup` takes it, never a flag — into a
  temporary file beside the store, hashed as it goes, and renamed into place under the digest only
  when the bytes hash to it. A file is never held whole, and a crash leaves no half file under a
  digest;
- a stream whose bytes hash to another digest is **refused**: nothing lands under the name, one line
  on stderr names the file and both digests, the rest of the run goes on, and the command exits 1
  at the end. A blob the backup damaged, or one that does not decrypt, is treated the same;
- a path the backup does not list, or lists with no bytes, is **not in the backup**: an
  iCloud-optimised library keeps a thumbnail on the phone and the pixels elsewhere, and a message's
  file may have been deleted since.

The same bytes referenced by several lines, or by two sources (a photo forwarded from WhatsApp to
Messages), are one file: the second reference finds it present. `--only` is required, as every run
against a real backup should name what it reads (a source disabled in `policy/import.json` is skipped
and said so). `--dry-run` counts what would be stored and how many bytes, and writes nothing; on an
encrypted backup it decrypts `Manifest.db` into the inbox folder and nothing else. One line per
source closes the run, then the store's size:

```
whatsapp: 1 file referenced by 1 line: 1 stored, 0 present, 0 not in the backup, 0 refused; 1 line without a digest
imessage: 2 files referenced by 2 lines: 1 stored, 1 present, 0 not in the backup, 0 refused
apple-photos: 1 file referenced by 1 line: 1 stored, 0 present, 0 not in the backup, 0 refused
3 files stored (56 bytes); attachments/: 3 files, 56 bytes (56 B)
```

A progress line every 500 files, on stderr, so stdout stays the summary. The backup is only ever read.

## `attach status`

Per source whose standing lines point at an attachment — the one a line points at, as `stats`
counts it: `payload.media`, else `payload.content`, else `extra.media` — the distinct digests
referenced, the lines naming one, how many are present and how many missing; then the store: files
and bytes, the files no standing line references (left by a line since retracted, or by a run that
stopped after the file and before anything pointed at it), and entries under a name that is not a
digest. Read from the index and one listing of the folder, nothing else; `--json` gives the same
as one object.

```
  source        referenced  present  missing  lines
  imessage               2        2        0      2
  whatsapp               1        1        0      1
  apple-photos           1        0        1      1
attachments/: 3 files, 56 bytes (56 B)
```

## `attach verify`

Every file under `attachments/` whose name is a digest is streamed through SHA-256 and compared with
its name. A file whose bytes hash to something else is listed and the command exits 1 (SPEC §1.1: a
present file whose bytes do not match its name is an error); an entry under another name — a
temporary file a run left behind — is counted and ignored. A progress line every 500 files.

```
attachments/: 3 files checked, 56 bytes, every file matches its name
```

## What it never does

No thumbnails, no derived files, no cache beside the store (ADR 0015: the store holds the bytes a
line names and nothing else). No line is appended, rewritten or removed: the pass writes files the
lines already point at. Until it runs, and after a run that stopped, such a line names a file the
store does not hold — a missing attachment, which SPEC §1.1 allows: the chain's `verify` reports it
separately and exits 0, `status` counts it, and the next run fills it in. Nothing is fetched from
anywhere but the backup folder on this machine.
