# Hold

Hold is the layer that will give everything you own one place: your files, your apps, the senders in
your mailbox, your Drive, later your boxes and the objects in them. Each thing gets a fate (keep it,
shelve it, archive it, let it go), the attention it costs falls, and one number says how much is
left. The whole design is a draft, [RFC 0042](https://github.com/bighydro/logbook/blob/main/rfcs/0042-hold.md).

**Hold v0 only counts.** It is three censuses in the lab, each a report you read. No line is
written; nothing is moved, renamed or deleted, ever.

```bash
logbook lab hold census files ~/Documents ~/Desktop   # what is in these folders
logbook lab hold census senders                      # who writes to you, from the mail the record holds
logbook lab hold census drive                        # your Drive, from the Drive lines the record holds
logbook lab hold census senders --tier 3 --json      # tier-3 mail too; the summary as JSON
```

Each census writes its report, Markdown to read and JSON to keep, in the record folder:

```
<record>/state/hold/files.md      files.json
<record>/state/hold/senders.md    senders.json
<record>/state/hold/drive.md      drive.json
```

A run replaces the census's last report. The folder is the owner's alone (mode 0700, the reports
0600, where the system has modes). The terminal gets a summary: counts and where the report is,
never a file name, a folder inside the ones you named, or an address.

```
hold census files: 18,204 files, 61.3 GB, in 1,912 folders under 2 given; 412 duplicate sets (3.1 GB held more than once); 37 folders untouched for two years
skipped: links 14, system folders 6, system files 210
report (tier 3; names stay in it): /Users/ines/Logbook/state/hold/files.md
  and /Users/ines/Logbook/state/hold/files.json; nothing was moved, renamed or deleted
```

`--json` prints the same summary as one object. The report's JSON is in the lab's terms: its shape may
change between releases.

## Files

`census files PATH…` walks the folders you name and reads them, nothing more.

- **By type**, **by extension** and **by year**: how many files and how many bytes, the type by the
  extension (image, video, audio, document, spreadsheet, presentation, archive, code, mail, other,
  none), the year by the file's modified time in the record's zone.
- **Duplicates**: files with the same bytes, found by SHA-256 of the bytes, read a megabyte at a time.
  Only files whose size another file shares are read at all; an empty file is never a duplicate.
  Each set says how many copies and how much space is held more than once.
- **The 50 largest**, with their modified day.
- **Untouched for two years**: the highest folders under which no file was modified in 730 days, by
  size. A folder inside one listed is not listed again; a folder you named, untouched as a whole, is
  listed as `.`.

What the walk never does:

- **It never writes in your folders.** A file is opened read-only, and only when its size is shared
  with another (to hash it). Nothing is moved, renamed, deleted or created there; the report's
  `changed` block says `0` for each, and the tests hold the folder byte for byte to what it was.
  The one exception is the report itself: when the record lies inside a folder you named (`census
  files ~` with the record at `~/Logbook`), the report is written in the record's `state/hold/`, which
  the walk never enters. A `state/hold` that is a link, or not a folder, is refused: no report.
- **It never makes your computer fetch a file.** A file whose bytes are elsewhere (an iCloud file
  not downloaded to this Mac, a OneDrive or Google Drive file on demand, an offline file) is counted
  from its metadata under `not_local` and never read, so it is never in a duplicate set; such a
  folder is not entered. A folder on another disk than the folder you named (a share or a disk
  mounted inside it, `/proc`) is counted under `other_disk` and not entered.
- **It never leaves the folders you named.** A symbolic link (or a Windows junction) is counted under
  `skipped: links` and never followed, wherever it points, so a link to another disk is not walked.
  A folder you named that is itself a link is followed to its folder once, because you named it.
  A FIFO, a socket or a device is counted (`special`) and never opened. A folder inside another you
  named is walked once.
- **It checks what it reads is what it listed.** A folder is entered only if it is still the folder
  the listing saw (same inode, not a link), and a file is hashed only if it is still the file; one
  swapped in between is counted under `changed_during_census` and left alone.
- **It skips the system's folders and Claude's.** `.git`, `.hg`, `.svn`, `.Trash`, `.Trashes`,
  `$RECYCLE.BIN`, `System Volume Information`, `.Spotlight-V100`, `.fseventsd`,
  `.DocumentRevisions-V100`, `.TemporaryItems`, `.AppleDouble`, `.AppleDB` and `.claude` anywhere;
  `Library` and `AppData` only directly inside a folder you named (the home's are the system's; a
  `Library` of books further down is yours), and so the top folders of a whole disk given as `/` or
  `C:\` (`Windows`, `Program Files`, `Program Files (x86)`, `ProgramData`, `$WinREAgent`, `System`,
  `Volumes`, `private`, `dev`, `proc`, `run`, `sys`); Claude's own folder (`Claude`) under
  `Application Support`, `.config`, `Roaming` or `Local`. Names are compared with case folded.
  `.DS_Store`, `Thumbs.db`, `desktop.ini`, `.localized` and `.claude.json` are not counted as your
  files.
- **It skips the record.** A record inside a folder you named is counted under `skipped: record` and
  not walked; naming the record itself, or a folder inside it, exits 2. An error names the argument
  by its place (`PATH 2 of 3 is not a folder`), never by its path.
- A file reached by two names (a hard link) is one file, never its own duplicate (`hard_links`).
  A folder or a file it cannot read is counted (`unreadable_folders`, `unreadable_files`), and one
  that changed size while it was read is counted (`changed_during_census`) and left out of the
  duplicates.

Reading a file may set its access time on a disk that keeps one; the census reports modified times
only. A name is written into the Markdown as text: every character a viewer reads as markup (`<`,
`[`, `(`, `*`, …) is escaped, so a name shaped like a link or an image fetches nothing when you open
the report in a previewer.

## Senders

`census senders` reads the record's own `mail/v1` lines ([RFC 0015](https://github.com/bighydro/logbook/blob/main/rfcs/0015-mail-v1.md)), from
any road that wrote them (a Takeout, `sync mail`, `sync gmail`). No connection is opened.

- **Every sender** of received mail, by its address lower-cased: messages, bytes, first and last
  seen, threads, the display name it used most.
- **Answered**: yes when you ever wrote to the address (a sent line with it under `to`, `cc` or
  `bcc`) or sent a message in one of its threads (joined on `thread`, never the subject). The report
  keeps both: `written_to` and `threads_answered`.
- **By count**, **by last seen**, **never answered** and **newsletters** are the report's sections.
- **Newsletters** by the `List-Unsubscribe` header, when the line holds it: `extra.list.unsubscribe`,
  which every mail road writes since 20 October 2026 (RFC 0015, amendment of that day), or an older
  producer's key under `extra` or a `headers` object. Lines written before that day hold none, and a
  re-import does not rewrite them, so on a record of older mail the section may say newsletters are
  unknown, not that there are none.
- **Lists and tabs**, per sender: how many of its mails carry `extra.list.unsubscribe`, and how many
  sit in Gmail's Promotions, Social or Updates tab (`extra.gmail_category`, written by a Takeout import
  and `sync gmail`; never by `sync mail`, since IMAP does not say the tab). In the report as a section
  and in the JSON as `list_unsubscribe` and `tabs` on each sender, with the totals under
  `lists_and_tabs`; the summary on the terminal says the totals only, never an address.

## Drive

`census drive` reads the record's own Drive lines (`event/v1` of source `drive`, written by
`logbook sync drive`). No connection is opened, and nothing is asked of Google.

- **Every file** the lines name, by its Drive id: its latest name, type, folder path (when the
  metadata scope was delegated), activities by kind, first and last activity, whether you acted on it.
- **By type**, **by folder**, **by year of the last activity**, **most active**.
- **Untouched**: no activity for two years. **Shared**: a share added and not removed since, by the
  lines; the report names the kind of each share (`user`, `group`, `domain`, `anyone`), never the
  address. **Trashed or deleted**: the last such activity with no restore after it.

The record holds a Drive file only from the activity Drive reported since `sync drive` began: a file
nobody touched since then is not in the census at all. That is the census's largest blind spot.

## Tiers

A report is derived material and takes the highest tier it read (SPEC §4). The senders and Drive
censuses read lines up to `--tier N` (default 2, as `search`), leave the lines above it out, count
them under `left_out: above_tier` and put the highest tier they read under `tier`. A sealed line the
identity on this machine cannot open is counted (`sealed`) and never guessed at. A file has no tier,
and a file name can say anything, so the files report is tier 3.

The reports live under `state/`, which nothing carries anywhere: no line holds them, so no crossing,
export or shared page does; `backup` leaves `state/` out; `doctor --packet` names no file under it.
They are plain files on your disk, though, not sealed, even in a record that seals its lines: delete
`state/hold/` when you no longer need a report, and keep full-disk encryption on.

## What it cannot see

- **Folders you did not name, and links.** The census is as wide as the paths you give it.
- **Duplicates under another encoding.** The same photo saved twice as JPEG is two files with
  different bytes: the census finds identical bytes, never similar content.
- **Who you answer by other roads.** A sender you call or message instead of mailing back is "never
  answered" here.
- **Drive files without activity** since the source began, as above.
- **Your own mail, unless the record knows your addresses.** A mail line is `sent` only when its
  sender is one of `owner_emails` in `logbook.json` (RFC 0015 `direction`). A mailbox imported
  before they were set reads as all received: you are your own top sender and nobody is answered.
  The report and the terminal say so when the record holds no sent mail.
- **Files whose bytes are elsewhere** (`not_local`) are counted, never compared: a duplicate of one
  is not found.
