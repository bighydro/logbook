# The first hour

You have installed `logbook` and you have a terminal open. Maybe for the first time. This page walks
through the hour that follows: `logbook setup` asks you six things, one at a time, and this is what each
screen looks like, what to type, and what happens to it. Nothing you type is sent anywhere; it stays in
a folder on this computer.

Every example here is the Oslo persona, Ines Nordmann, who does not exist; the addresses are at
`example.org` and the numbers are in a reserved range. Put your own in their place.

## Before you start

Open a terminal: on a Mac, *Terminal* in Applications → Utilities; on Windows, *Terminal* from the
Start menu; on Linux, you know. Type the lines shown after `$` and press Enter. Everything else on the
page is what the computer prints back.

```
$ pipx install openlogbook
$ logbook --version
```

If the second line prints a version, you are ready. If it says the command is not found, close the
terminal, open a new one, and try again: `pipx` tells the shell about new commands on the next start.
If you do not have `pipx`, or you are on a Mac and would rather `brew install bighydro/logbook/logbook`,
[install.md](install.md) takes the install one step at a time, with what each step prints.

## `logbook setup`

```
$ logbook setup
Welcome. This sets up your logbook, one question at a time.
Enter takes the answer in brackets, s skips a step, q stops.
Nothing you type here is sent anywhere; it stays in the record's folder.
```

Three keys do everything: **Enter** takes the answer shown in brackets, **s** skips the step, **q**
stops. Stopping loses nothing: what you answered is kept, and `logbook setup` again continues at the
first question you have not answered. Every question says why it is asked, under *Why:*.

### Step 1: where to keep the record

```
── Step 1 of 6: where to keep the record ────────────────────────────────────
Why: The record is a folder of plain files: that is the whole product. It must be a folder no
     sync service (iCloud Drive, Dropbox, OneDrive or Google Drive) touches: those evict files
     to the cloud, rewrite them underneath the writer and keep your record on someone else's
     server.
Where should the record live? [~/Logbook]:
Created ~/Logbook: the record, its policy/ and inbox/ folders, no lines yet.
```

Press Enter. `~/Logbook` is a folder called *Logbook* in your home folder, where every command looks
for it without being told. The only wrong answer is a folder a sync service owns, and the wizard refuses
it with the reason:

```
Where should the record live? [~/Logbook]: ~/Dropbox/Logbook
Not there: ~/Dropbox/Logbook is under Dropbox; a sync client evicts files to the cloud and fetches them
back on demand, rewrites month files and logbook.json underneath the writer, and keeps the record on
someone else's server; move it to a plain local folder and point LOGBOOK_HOME at it.
Pick a plain local folder, such as ~/Records/Logbook.
Where should the record live? [~/Logbook]:
```

If you do pick a folder other than `~/Logbook`, the last screen tells you the one line to put in your
shell profile so every command finds it. If a record is already in the folder you name, the wizard says
*Found your record at ~/Logbook; keeping it* and carries on with that record's setup.

### Step 2: your timezone

```
── Step 2 of 6: your timezone ───────────────────────────────────────────────
Why: Every time in the record is stored in UTC; your zone is how the days are cut and shown
     (SPEC §3.2). A flight landing at 23:30 your time is on that day, not the next.
Your timezone, as the zone database names it [Europe/Oslo] (Europe/Oslo):
Timezone: Europe/Oslo.
```

The answer in brackets is what this computer thinks its zone is; Enter accepts it. A zone is spelled
as a continent, a slash, and the nearest big city: `Europe/Oslo`, `America/New_York`, `Asia/Tokyo`. A
name this machine does not know is refused and the question asked again, never swapped for a guess:

```
Your timezone, as the zone database names it [Etc/UTC] (Europe/Oslo): Mars/Olympus
'Mars/Olympus' is not a zone this machine knows; Europe/Oslo, America/New_York and
Asia/Tokyo are: a continent, a slash, the nearest big city.
Your timezone, as the zone database names it [Etc/UTC] (Europe/Oslo): Europe/Oslo
Timezone set to Europe/Oslo (was Etc/UTC).
```

### Step 3: who you are

```
── Step 3 of 6: who you are ─────────────────────────────────────────────────
Why: The record meets you under many names: the address a friend writes to, the number a contact
     saved, a nickname. Listing them in policy/owner.json tells every reader which lines are
     you, so you are never your own company when it counts who you spent the day with.
Your names, as contacts and mail know you, separated by commas [skip]: Ines Nordmann, Ines
Your email addresses, separated by commas [skip]: ines.nordmann@example.org
Your phone numbers, separated by commas [skip]: 07700 900123
Wrote ~/Logbook/policy/owner.json: 4 added. Edit it any time; it is yours, never in the chain.
The emails are owner_emails in logbook.json too, so mail and chat imports know your side.
```

Why this matters: when the record counts who you spent a day with, it must know which messages, calls
and photos are *you*. Without this list, the day you texted yourself a shopping list reads as a day with
a very close friend. Three questions, commas between several answers, Enter on a question you have
nothing for. The file is `policy/owner.json` in the record; open it in any text editor later to add
more. If the file already lists something, the screen says *already listed:* and what you type is added.

Nothing here is a password. The wizard never asks for one, anywhere.

### Step 4: your home place

```
── Step 4 of 6: your home place ─────────────────────────────────────────────
Why: A night is at home when you slept within this circle; trips, nights away and the countries
     you were in are counted from it. Coordinates only, never an address: the record keeps what
     you paste, so paste the two numbers a maps app shows when you press on your front door.
Your home, as latitude, longitude [skip] (e.g. 59.9139, 10.7522): 59.9139, 10.7522
What to call it [Home]:
named 59.9139,10.7522 as Home (line #1); a circle of 120 m in places.json.
```

Open Google Maps or Apple Maps on your phone or in a browser, press and hold on your front door, and
two numbers appear, something like `59.9139, 10.7522`. Copy them, paste them here. That is all the
record keeps: a point and a circle of 120 metres, under the name *Home*, in `places.json`. It is also
the first line in your record: *named 59.9139,10.7522 as Home*, the day you gave your home its name.

An address is refused. The record keeps what you type, so it never asks for one:

```
Your home, as latitude, longitude [skip] (e.g. 59.9139, 10.7522): 12 Example Street
'12 Example Street' is not coordinates. In Google or Apple Maps, press and hold on the spot and
copy the two numbers it shows, like 59.9139, 10.7522. Never type an address here.
Your home, as latitude, longitude [skip] (e.g. 59.9139, 10.7522):
```

Not sure yet? Enter skips it; `logbook places name Home 59.9139,10.7522 --kind home` does it later, or
`logbook setup --step home` asks again.

### Step 5: what is on this machine

The wizard looks in three places and tells you what it found. Nothing is read beyond what it takes to
recognise an export, and nothing is written until you say so, twice: once for a dry run that only
counts, once for the import.

```
── Step 5 of 6: what is on this machine ─────────────────────────────────────
Why: The record grows from exports you already have. Each one found here is offered with a dry
     run first: the adapter reads it and counts, and nothing is written until you say so. An
     export is only ever read; your files stay where they are.
```

**A Google Takeout** is a folder called `Takeout` in your Downloads, once the zip Google sent you is
unzipped (double-click it). Each product Google exported that the adapters read is listed, with the
ones your policy has switched off:

```
Google Takeout at ~/Downloads/Takeout:
  google-takeout-chat: ~/Downloads/Takeout/Google Chat
  google-takeout-meet: ~/Downloads/Takeout/Google Meet
  google-takeout-activity: switched off in policy/import.json (every search and app opened; opt in)
Dry run these 2 import(s)? Nothing is written [Y/n]:
google-takeout-chat: 6 lines would be added, 0 already in the record (dry run, nothing written)
  skipped 1 without a timestamp, 0 with unusable coordinates
  skipped 1 without a body
  also 1 with media hashed, 1 without a message id, keyed by time and text
google-takeout-meet: 4 lines would be added, 0 already in the record (dry run, nothing written)
  skipped 1 without a timestamp, 0 with unusable coordinates
  also 1 without a conference id, keyed by start and organizer
Write these lines to the record? [Y/n]:
added 6 lines from google-takeout-chat
  skipped 1 without a timestamp, 0 with unusable coordinates
  skipped 1 without a body
  also 1 with media hashed, 1 without a message id, keyed by time and text
added 4 lines from google-takeout-meet
  skipped 1 without a timestamp, 0 with unusable coordinates
  also 1 without a conference id, keyed by start and organizer
```

The dry run is the real import with the writing left out: the same reader, the same counts, and
*already in the record* tells you what a second run would skip. Answer `n` to either question and
nothing happens; `logbook add ~/Downloads/Takeout/"Google Chat"` does the same later. A Takeout still
zipped is named and left alone: *unzip it first (double-click it), then run `logbook setup --step
sources` again*.

**An iPhone backup** is what Finder (or iTunes, or the Apple Devices app on Windows) makes when you
plug the phone in and press *Back Up Now*. The wizard finds it where those apps keep it, lists the
stores in it that the adapters know, and shows the exact command it is about to run, always with
`--only` the stores found and never the whole backup unasked:

```
iPhone backup 00008030-000A1B2C3D4E5F60 at ~/Library/Application Support/MobileSync/Backup/00008030-000A1B2C3D4E5F60:
  stores found: ios-contacts, imessage, ios-notes
  the command: logbook import-backup ~/Library/Application Support/MobileSync/Backup/00008030-000A1B2C3D4E5F60 --only ios-contacts,imessage,ios-notes
Dry run it? Nothing is written [Y/n]:
ios-contacts: AddressBook.sqlitedb (20,480 bytes) → ~/Logbook/inbox/ios-backup-00008030-000A1B2C3D4E5F60/ios-contacts
imessage: sms.db (61,440 bytes) + sms.db-wal (0 bytes) + 2 media files (50 bytes) under Attachments/ → ~/Logbook/inbox/ios-backup-00008030-000A1B2C3D4E5F60/imessage
ios-notes: NoteStore.sqlite (12,288 bytes) → ~/Logbook/inbox/ios-backup-00008030-000A1B2C3D4E5F60/ios-notes
dry run: 3 of 3 sources found, 94,258 bytes would be copied to ~/Logbook/inbox/ios-backup-00008030-000A1B2C3D4E5F60; nothing written
Copy these stores into inbox/ and import them? [Y/n]:
added 8 lines from ios-contacts
  skipped 1 with a phone or email already seen, 1 without a phone or email
added 13 lines from imessage
  skipped 2 reactions, 1 group system events, 1 with an unusable date, 1 without a chat, 2 without a body
added 4 lines from ios-notes
  skipped 1 password protected, 1 with an unusable date
valid — 25 lines, head cfa62f52b875e25dd949e23cbc4a3006c993660f6a4ca83f448bd7a596f11e0f
```

The backup itself is only read. Each store is copied into the record's `inbox/` folder, checked
against the backup, and read from there; the counts say what each adapter added and what it skipped,
and the last line is `verify`: the chain is intact. (The dry run and import above are from a synthetic
backup the tests build; yours will list more stores and many more lines.)

An **encrypted** backup (*Encrypt local backup* ticked in Finder) holds more: Health, the call log,
Safari. It needs its password, and the wizard will not take it. It names the variable to put it in and
how, and moves on:

```
iPhone backup 00008030-00000000000000BB at ~/Library/Application Support/MobileSync/Backup/00008030-00000000000000BB:
  encrypted: it holds more (Health, calls, Safari) and needs its password in LOGBOOK_BACKUP_PASSWORD, which setup never asks for. In a terminal, type
    read -s LOGBOOK_BACKUP_PASSWORD && export LOGBOOK_BACKUP_PASSWORD
  (typed once, never shown), then `logbook import-backup <folder> --only <sources>`.
```

`read -s` reads what you type without showing it on the screen; the password is held by your terminal
for that session only, never written to a file, never printed, never part of an error.

**Messages on a Mac** is the Mac's own Messages database. It is read live, new messages each time, by
`logbook sync imessage`; the first time, macOS will ask you to give your terminal app *Full Disk
Access* (System Settings → Privacy & Security), or refuse the read:

```
Messages on this Mac: ~/Library/Messages/chat.db
  `logbook sync imessage` reads it, new messages each run; the terminal app needs Full Disk
  Access (System Settings → Privacy & Security) or macOS refuses the read.
Dry run it? Nothing is written [Y/n]:
  13 messages in 0s
imessage: 13 lines since 2026-03-01T18:01:10Z (dry run, nothing written)
  first 2026-03-02T17:42:10Z  last 2026-03-02T18:01:10Z  watermark 2026-03-02T18:01:10Z
Write these messages to the record? [Y/n]:
```

**Nothing found** is the common first answer, and the wizard says where each kind would be:

```
Found nothing to import yet. Where each kind would be:
  Google Takeout: the Takeout folder (unzipped) in ~/Downloads
  iPhone backup: Finder → your iPhone → Back Up Now; it lands under
    ~/Library/Application Support/MobileSync/Backup
    (Windows: %APPDATA%\Apple Computer\MobileSync\Backup)
  Messages on a Mac: ~/Library/Messages/chat.db (`logbook sync imessage`)
Any export: `logbook add <file-or-folder>`; the adapters recognise it.
```

**Live sources** come last. These are services that `logbook sync <name>` pulls from on their own,
each needing a key or an address in a variable of your shell. The wizard prints the variable's *name*
and where the key comes from, and never a value, set or not:

```
Live sources pull on their own with `logbook sync <name>`; each needs a variable set:
  immich: set LOGBOOK_IMMICH_URL and LOGBOOK_IMMICH_KEY — Immich → Account settings → API keys, with only the asset.read permission; the URL is yours
  dawarich: set LOGBOOK_DAWARICH_URL and LOGBOOK_DAWARICH_KEY — Dawarich → Settings → Account → API key; the URL is your Dawarich's address
  granola: set LOGBOOK_GRANOLA_KEY — Granola → Connectors → API keys (Business and Enterprise plans)
  gcal: set LOGBOOK_GCAL_URLS — Google Calendar → Settings → the calendar → Integrate calendar → Secret address in iCal format
  ais: set LOGBOOK_AISSTREAM_KEY — a free key from aisstream.io, for the vessels registered in assets.json
  adsb: works without a key; optional LOGBOOK_OPENSKY_USER and LOGBOOK_OPENSKY_PASS — an account at opensky-network.org (optional: anonymous access works, with a lower rate)
A key goes in the variable in your shell profile, never in a file of the record, never here.
```

One you have set shows as *configured (LOGBOOK_DAWARICH_URL, LOGBOOK_DAWARICH_KEY)*: the names, so
you can see it took; never what they hold. Setting one is a line in your shell profile, such as
`export LOGBOOK_DAWARICH_KEY=...`; the README has each service's section.

### Step 6: a check-up

```
── Step 6 of 6: a check-up ──────────────────────────────────────────────────
Why: `logbook doctor` is the check-up: one line per check, pass, warn or fail. Run it any time.
pass  record            11 lines, head 53c3dffd3261…, verified; /Users/ines/Logbook
pass  index             index.sqlite is current with logbook.json
pass  owner             policy/owner.json names 2 names, 1 emails, 1 phones
pass  places            1 place(s), home: Home
pass  assets            no assets.json; nothing is tracked as a subject
pass  extra:ais         websockets is installed
pass  extra:crypto      cryptography is installed
warn  extra:transcribe  mlx-whisper or faster-whisper not installed: pip install "openlogbook[transcribe]"
pass  disk              29.0 GiB free on the record's volume
pass  folder            a plain local folder, no sync client
10 checks: 9 pass, 1 warn, 0 fail

Setup is complete. Your record is at ~/Logbook.
Next:
    logbook add "had lunch with a friend by the lake"    # a line in your words
    logbook show today                                   # the day read back
    logbook verify                                       # the chain is intact
docs/first-hour.md walks through the first hour.
```

`warn` is advice, not a problem: here, an optional extra for transcribing voice memos is not installed.
`fail` names what to fix. `logbook doctor` runs these checks any time, and changes nothing.

## Stopping, skipping, and coming back

Press `q` at any question, or close the terminal, and this is the whole screen:

```
Your names, as contacts and mail know you, separated by commas [skip]: q

Stopped. Run `logbook setup` again any time: it continues where you stopped.
```

The steps answered are kept in `state/setup.json` inside the record (bookkeeping, not part of the
record itself), and the next `logbook setup` starts at the first one not yet answered. `s` skips a step
and moves to the next; a skipped step is remembered as skipped, not asked again. To revisit one:

```
$ logbook setup --step owner      # one step again: folder, timezone, owner, home, sources, doctor
$ logbook setup --again           # every step again; the record is kept
```

Once every step is answered, `logbook setup` says so and offers those two.

## The rest of the hour

The record is a folder. Open `~/Logbook` in Finder or Explorer: `logbook/` holds the lines, one file a
month, plain text; `policy/` your settings; `inbox/` the copies of what you imported. Nothing in it
needs this program to be read.

```
$ logbook add "coffee with Kari, talked about the summer"
$ logbook show today
$ logbook stats
$ logbook verify
```

`add` with a sentence is a note in your words. `show today` reads the day back: what was imported,
what you wrote. `stats` counts what the record holds, by kind, source and year, and never shows a
line's text. `verify` recomputes every hash and says *valid*; it will say so every time, until a byte
changes.

Then, at your pace: [Try it](try-it.md) runs every command on a demo record of a person who does not
exist; the README's *Sources* lists every export the adapters read, with the command for each; and
`logbook doctor` is there whenever something feels off.

## `--yes`

`logbook setup --yes` takes every default and asks nothing: the record in `~/Logbook` (or where
`LOGBOOK_HOME` points), the detected timezone, the steps with no default skipped, every found export
dry-run and imported, the check-up at the end. It is for tests and scripts; a person should answer the
questions.
