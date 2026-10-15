# Running Logbook on a home server

This page sets up the record's home ([ADR 0022](adr/0022-the-records-home.md)): one small machine at
home, always on, that holds the only writable copy of the record, runs the pages and the schedule as
system daemons, runs a local model for the dream, and is reached from a laptop by `ssh` and from a
phone over your own private network. It is a runbook: do the steps in order, check each one where it
says so, and the whole takes about an hour. Every `logbook` command on it is the CLI as it is, and the
commands shown as printed are what it prints.

The names are synthetic. The server is `server.example`, the laptop `laptop.example`, the record
belongs to Ines Nordmann of Oslo, who does not exist, and the two accounts on the server are `owner`
and `records`.

```
laptop.example ── ssh as records ──▶ server.example ◀── private network ── phone
  development,                         records: the record, serve, the     the pages, read
  a read-only checkout                 schedule; the local model beside
```

**Nothing cloud-synced holds the record.** Not the record folder, not a backup, not a read-only
checkout on the laptop. The phone reaches the pages, never the files.

## Before you start

- **The server**: Linux with systemd, always on, a disk with room for the record and its attachments,
  and a second disk for backups, mounted at `/mnt/backup`. A Mac works too; what differs is at the end
  ([On a Mac](#on-a-mac)).
- **An administrator account** on it, `owner`, that can `sudo` and that you reach by `ssh` from the
  laptop.
- **The laptop**, with an `ssh` key (`~/.ssh/id_ed25519.pub`).
- **A Logbook with the dream and the system daemons**: the release after 0.6.1. `logbook --help`
  lists `dream` under *derive*, and `logbook sync --help` lists `--system`. Until that release is out,
  install from `main` (step 2 says how).

Each block of commands starts with a comment saying who runs it and where; a block without one is
what a command printed.

## 1. Two users, and why (5 minutes)

| account | what it is | what it may do |
|---|---|---|
| `owner` | you, the administrator | `sudo`; runs the commands Logbook prints for the system; holds nothing of the record |
| `records` | the record's own user | holds the record and runs the pages, the schedule and every command that writes; no password, no desktop login, no `sudo`; reached by `ssh` with a key |

Why two:

- The daemons run as the user who installed them, and never as root: `--system` refuses to run as
  root, since the daemon would run as root with root's home. They need an account, and it should be
  one that does nothing else.
- `records`'s home is closed (mode 700), so nothing that runs as `owner` (a browser, a build, a tool
  you are trying) can read the record, and nothing that runs as `records` can become root.
- The commands that install a daemon need an administrator. Logbook never runs `sudo`; it writes the
  file in `records`'s home and prints the commands, and `owner` runs them after reading what they
  copy.
- A collaborator, one day, is a third account on this machine, after sealing at rest
  ([ADR 0022](adr/0022-the-records-home.md), point 5), never a copy of the folder.

```bash
# as owner, on server.example
sudo useradd --create-home --shell /bin/bash records    # no password is set: no console or desktop login
sudo chmod 700 /home/records
```

Let the laptop's key in as `records` (the account has no password, so `ssh-copy-id` cannot do it):

```bash
# on laptop.example
scp ~/.ssh/id_ed25519.pub owner@server.example:laptop.pub
```

```bash
# as owner, on server.example
sudo install -d -m 700 -o records -g records /home/records/.ssh
sudo install -m 600 -o records -g records ~/laptop.pub /home/records/.ssh/authorized_keys
rm ~/laptop.pub
```

**Check:** `ssh records@server.example whoami` on the laptop prints `records`. From here on, "as
records" means that `ssh` session, or `sudo -iu records` from `owner`'s.

Set the server's clock to the record's timezone. The schedule's timers fire at 00:00, 06:00, 12:00
and 18:00 by the system's clock, and the 06:00 run is the one that closes your day:

```bash
# as owner, on server.example
sudo timedatectl set-timezone Europe/Oslo
timedatectl          # Time zone: Europe/Oslo (…)
```

## 2. Install Logbook as records (5 minutes)

```bash
# as records, on server.example
curl -LsSf https://astral.sh/uv/install.sh | sh
exit                 # then log in as records again, so ~/.local/bin is on the path
```

```bash
# as records, on server.example
uv tool install "openlogbook[ais,crypto,sealed,transcribe]"
# until the release after 0.6.1:
# uv tool install "openlogbook[ais,crypto,sealed,transcribe] @ git+https://github.com/bighydro/logbook"
logbook --version
```

The four extras are the ones `doctor` checks (`extra:ais`, `extra:crypto`, `extra:sealed`,
`extra:transcribe`); one missing is a standing warn, which makes no scheduled run clean and, with the
message set up (step 4), is a message every run until it is fixed. On Linux, `transcribe` is
`faster-whisper`; `describe` and `judge` are Apple silicon only and install nothing here
([install](install.md#optional-extras)).

The server runs a released package, installed for `records`, not a checkout of the repository. The
development checkout lives on the laptop and never points at the record: the tests pin `LOGBOOK_HOME`
and the home directory to a temporary folder, and `init` refuses a code checkout as a record folder.

## 3. Where the record lives (5 minutes; a move adds the copy)

The record is `/home/records/Logbook`, which is `records`'s `~/Logbook`: the place `logbook init` makes
by default and `logbook` finds without `LOGBOOK_HOME`. A plain folder on a local disk.

**Never a synced folder.** No file-sync client, peer-to-peer sync tool or network share may hold the
record, its backups or a read-only checkout. A sync client rewrites `logbook.json` and the month files
underneath the writer, evicts files and fetches them back, and keeps the record on someone else's
server; two machines syncing one record are two writers on one chain, which the format has no merge
for. `doctor`'s `folder` line fails a record under iCloud Drive, Dropbox, OneDrive or Google Drive by
name, and `backup` refuses them as a destination; any other sync tool it cannot see, so the rule is
yours to keep.

**A new record:**

```bash
# as records, on server.example
logbook setup        # the guided first run (docs/first-hour.md); or: logbook init --timezone Europe/Oslo
```

**Moving the record from the laptop**, where it lived until now. Home moves by copying the record
once, never by syncing it, and the old copy stops writing. On the laptop, stop its schedule and its
pages first, then take a snapshot:

```bash
# on laptop.example
logbook sync --uninstall-schedule
logbook serve --uninstall-service
logbook backup ~/Transfer          # a verified snapshot, ~/Transfer/<owner_id>/<timestamp>/
scp -r ~/Transfer/<owner_id>/<timestamp> records@server.example:snapshot
```

```bash
# as records, on server.example
logbook backup restore ~/snapshot ~/Logbook     # copied, verified, its head printed
rm -r ~/snapshot
```

A snapshot leaves `state/` out, so every live source is new to the server. A `sync` by hand reads each
from its start, and the record refuses what it already holds, so nothing doubles. The schedule's first
run reads each source's last 14 days ([a source's first scheduled
run](schedule.md#a-sources-first-scheduled-run)): the record already holds what came before the snapshot,
and `doctor` names each source as `first run bounded to 14 days; history not read` until a `logbook sync
<source> --since <date>` from before the snapshot's day reads the days between and clears it (when the
snapshot is from today, there are none, and the record refuses all it reads). If the record seals tiers 2
and 3 (`logbook key show` says so, and where the identity is), the identity file goes to the server too,
by `scp`, to the same place under `records`'s `~/.config/logbook/identities/`, at mode 600. Write nothing
more to the laptop's record folder; once the server's first backup has passed a restore test (step 9),
delete it, and the snapshot in `~/Transfer` with it. A read-only checkout (step 8) takes its place if you
want one there.

**Check:** `logbook verify` as records prints `valid` and the head.

## 4. The env file for secrets (5 minutes)

The schedule reads every key your sources need from `~/.config/logbook/sync.env`, one `KEY=value`
per line, mode 600, `records`'s. Logbook never writes it and never prints a value from it. The system
units name it by its path (`EnvironmentFile=-/home/records/.config/logbook/sync.env`), so nothing
else needs to know where it is.

Write each secret with `read -s`, which takes what you type without showing it; `printf` is a shell
builtin, so the value is never on a command line, in the history or in the process list:

```bash
# as records, on server.example
install -d -m 700 ~/.config/logbook
touch ~/.config/logbook/sync.env && chmod 600 ~/.config/logbook/sync.env
read -rs -p 'LOGBOOK_IMMICH_KEY: ' v && printf 'LOGBOOK_IMMICH_KEY=%s\n' "$v" >> ~/.config/logbook/sync.env; unset v; echo
read -rs -p 'LOGBOOK_DAWARICH_KEY: ' v && printf 'LOGBOOK_DAWARICH_KEY=%s\n' "$v" >> ~/.config/logbook/sync.env; unset v; echo
```

Values that are not secret go in the same way without `-s`, or with an editor:

```bash
# as records, on server.example
printf '%s\n' 'LOGBOOK_IMMICH_URL=http://127.0.0.1:2283' 'LOGBOOK_DAWARICH_URL=http://127.0.0.1:3000' >> ~/.config/logbook/sync.env
```

What goes in it: each live source's variables (`logbook sync --help` names them; `doctor`'s `sync:`
lines say which are missing), `LOGBOOK_IDENTITY_FILE=<path>` for a record that seals (the monthly
restore test needs it, or it is skipped), the dream's two variables (step 7), and, if you want one
message when something is wrong, `LOGBOOK_NOTIFY_TELEGRAM_TOKEN` and `LOGBOOK_NOTIFY_TELEGRAM_CHAT`
([the schedule](schedule.md#what-it-tells-you-and-when)).

**Check**, names only, never values:

```bash
# as records, on server.example
cut -d= -f1 ~/.config/logbook/sync.env          # the names
stat -c '%a %U' ~/.config/logbook/sync.env      # 600 records
```

Never `cat` the file, never paste a key into a command, never put the file in a repository or a synced
folder. The serve daemon does not read it: the pages need no secret.

## 5. Where your day begins (2 minutes)

If your day does not end at midnight, say so before the schedule runs and before you sign a day
([settings](settings.md#where-your-day-begins-day_start)). Moving the boundary later moves lines
between days, and a signed day whose page changed reads as changed.

```bash
# as records, on server.example
logbook setup day_start 06:00
```

```
day_start: 00:00 → 06:00 in logbook.json; a line before 06:00 now belongs to the day before. No line changed
index: rebuilt, 48,213 lines in 1.6s, each on its day under 06:00
```

The schedule's close runs at 06:00 by the server's clock (step 1 set it to the record's timezone). With
`day_start` at 06:00 or earlier, the close finds yesterday ended and the dream catches it up; with a
later `day_start`, the day that has not ended waits for the next morning.

## 6. The pages and the schedule as system daemons (10 minutes)

Both are installed the same way: as `records`, the command writes the unit files into `records`'s
home, prints them, and prints the commands an administrator runs; as `owner`, you read the files and
run those commands. Nothing needs a login session, and no `loginctl enable-linger`: that is what
`--system` is for.

### The pages: `serve --install-service --system`

```bash
# as records, on server.example
logbook serve --install-service --system
```

```
writing /home/records/logbook-serve.service:
[Unit]
Description=logbook serve: the record's pages at http://127.0.0.1:8765/, from this machine only

[Service]
User=records
Environment=LOGBOOK_HOME=/home/records/Logbook
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/records/.local/share/uv/tools/openlogbook/bin/python -m logbook.cli serve --port 8765
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target

written: a systemd system service running `logbook serve --port 8765` as records from boot, started again when it fails; nothing runs until you install it, as an administrator:
  sudo cp /home/records/logbook-serve.service /etc/systemd/system/logbook-serve.service
  sudo systemctl enable --now logbook-serve.service
then http://127.0.0.1:8765/ (/today is today's page); its output: journalctl -u logbook-serve.service; `logbook serve --status` says whether it answers
the server binds 127.0.0.1 and nothing else; reaching it from another device: docs/serve.md
```

```bash
# as owner, on server.example: the two lines it printed
sudo cp /home/records/logbook-serve.service /etc/systemd/system/logbook-serve.service
sudo systemctl enable --now logbook-serve.service
```

The unit carries paths and nothing secret: the Python that installed it, the record, and
`LOGBOOK_IDENTITY_FILE` when it was set in the shell that ran the install. It never carries `--host`;
the server binds 127.0.0.1 and refuses anything else ([serve](serve.md#three-rules)).

### The schedule: `sync --install-schedule --system`

```bash
# as records, on server.example
logbook sync --install-schedule --system
```

It writes four files to `/home/records` and prints each: `logbook-sync.service` and `.timer`
(`sync --scheduled` at 00:00, 12:00 and 18:00) and `logbook-sync-close.service` and `.timer`
(`sync --scheduled --close` at 06:00). Each service is `Type=oneshot`, `User=records`,
`EnvironmentFile=-/home/records/.config/logbook/sync.env` and `LOGBOOK_HOME=/home/records/Logbook`;
each timer is `Persistent=true`, so a run missed while the machine was off happens when it is back.
Then:

```
written: 4 files for the system domain, running as records from boot: `logbook sync --scheduled` (`sync --all`, then `doctor`) runs at 00:00, 12:00 and 18:00 local, and at 06:00 as `sync --scheduled --close`, which then runs the dream's catch-up when this version has it and policy/crossing.json has a dream entry; nothing runs until you install them, as an administrator:
  sudo cp /home/records/logbook-sync.service /home/records/logbook-sync.timer /home/records/logbook-sync-close.service /home/records/logbook-sync-close.timer /etc/systemd/system
  sudo systemctl enable --now logbook-sync.timer logbook-sync-close.timer
to be told when something is wrong, put LOGBOOK_NOTIFY_TELEGRAM_TOKEN and LOGBOOK_NOTIFY_TELEGRAM_CHAT in the same file: one Telegram message when a source fails or doctor warns, and the week's counts on Sunday evening (docs/schedule.md)
the variables your live sources need go in ~/.config/logbook/sync.env, one KEY=value per line, mode 600; a source whose variables are not set is skipped
home: this machine (server) is the record's home since 2026-10-13; state/home.json
```

```bash
# as owner, on server.example: the two lines it printed
sudo cp /home/records/logbook-sync.service /home/records/logbook-sync.timer /home/records/logbook-sync-close.service /home/records/logbook-sync-close.timer /etc/systemd/system
sudo systemctl enable --now logbook-sync.timer logbook-sync-close.timer
```

The last line it printed matters: installing the schedule names this machine the record's home, and
`doctor` on any other machine says writers belong here.

Run either install again later (a new Python, a moved record, a new release that changes the unit) and
it prints the replacing commands instead: the same `sudo cp`, then `sudo systemctl daemon-reload` and
`sudo systemctl restart` of the service or the two timers. `--uninstall-service --system` and
`--uninstall-schedule --system` remove the copies in the home directory and print the commands that
stop the daemons and remove the system's copies.

**Check:**

```bash
# as records, on server.example
logbook serve --status                        # installed: a systemd system service (/etc/systemd/system/logbook-serve.service), port 8765
                                              # answering at http://127.0.0.1:8765/
systemctl list-timers 'logbook-sync*'         # the next 00:00, 06:00, 12:00 or 18:00 of each timer
(set -a; . ~/.config/logbook/sync.env; logbook sync --scheduled)    # one run now, as the timer runs it
```

`--status` exits 0 when the server answers, 1 when it is installed and silent, 3 when none is
installed. The run by hand needs the keys, which the timer reads from the env file and your shell does
not; the parentheses read them in a subshell, so they leave with it. The run is `sync --all`, then
`doctor`, and its last line is `scheduled run: clean; state/last-run.json`.

## 7. The local model, and the dream (10 minutes, and the model's download)

The dream sends a day to a model and writes the draft back as one line ([the dream](dream.md)). Here
the model runs on this machine, as a daemon of its own, beside Logbook and not inside it:

- it takes minutes to load and gigabytes of memory, so it stays up and answers the 06:00 close at once;
- it never needs the record's files, so it runs as no user that can read them;
- it listens on 127.0.0.1 only, so a day never leaves the machine;
- it is replaced by changing two variables, never code.

Any OpenAI-compatible chat completions server will do; `llama-server` from llama.cpp is the one the
dream's docs use. Put the model file where any user can read it (`/srv/models` here), then a unit of
your own, which Logbook neither writes nor reads; the two paths in it are wherever you put the server
and the model:

```ini
# /etc/systemd/system/local-model.service, written by owner
[Unit]
Description=local model for the dream, at http://127.0.0.1:8080/ only
After=network.target

[Service]
DynamicUser=yes
ExecStart=/usr/local/bin/llama-server --model /srv/models/qwen2.5-7b-instruct-q4_k_m.gguf --alias qwen2.5-7b-instruct --host 127.0.0.1 --port 8080
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
# as owner, on server.example
sudo systemctl daemon-reload
sudo systemctl enable --now local-model.service
curl -sS http://127.0.0.1:8080/health          # ok once the model has loaded
```

`DynamicUser=yes` runs it as a throwaway account made for it, which cannot read `/home/records`.
`--alias` is the name the server answers to; the policy and the variable below use the same one.

**The policy entry.** Sending a day to a model is a crossing like any other, so the dream does nothing
until `policy/crossing.json` has a `dream` entry. Add it by hand beside the entries already there:

```json
{
  "hermes": {"max_tier": 2},
  "mcp": {"max_tier": 1},
  "dream": {"max_tier": 2, "until": "2027-03-31", "model": "qwen2.5-7b-instruct"}
}
```

`max_tier` 2 lets the model read notes and messages; 3 would add health and money. `until` is the last
day the entry holds; after it the dream refuses and `doctor` names the entry, so a model you stop
thinking about stops by itself. `model` is the only model the day may go to; a `LOGBOOK_DREAM_MODEL`
that names another is refused.

**The endpoint**, in the env file (step 4). A local server needs no key, so there is no
`LOGBOOK_DREAM_KEY`:

```bash
# as records, on server.example
printf '%s\n' 'LOGBOOK_DREAM_ENDPOINT=http://127.0.0.1:8080' 'LOGBOOK_DREAM_MODEL=qwen2.5-7b-instruct' >> ~/.config/logbook/sync.env
```

**Check**, one day, nothing written:

```bash
# as records, on server.example
LOGBOOK_DREAM_ENDPOINT=http://127.0.0.1:8080 LOGBOOK_DREAM_MODEL=qwen2.5-7b-instruct logbook dream day yesterday --dry-run
```

From now on the 06:00 close runs `dream --catch-up` after the sync and ends with `scheduled run, the
close (dream caught up): clean; state/last-run.json`. A draft is a proposal: a refused day never makes
the run unclean, and the next close tries it again.

**Transcripts and descriptions** are the other local models, and they are not daemons: `derive
transcripts` and `derive descriptions` load their model in the command's own process, offline, and run
when you run them, not on the schedule. Fetch the model once, the only time either uses the network:

```bash
# as records, on server.example
logbook derive transcripts voice-memos --fetch-model    # the first time: download the Whisper model, then transcribe
logbook derive transcripts voice-memos                  # after each import of voice memos
logbook derive descriptions keepers                     # Apple silicon only: elsewhere it names the extra and exits 2
```

([Voice memos](adapters/voice-memos.md), [describing keepers](describe.md).)

## 8. One writer, and read-only checkouts (5 minutes)

The record on the server is the only copy anything writes to. The schedule, the dream, the Places
form and every command you type that appends run there, as `records`, one at a time under the writer
lock (`state/writer.lock`; a second writer waits, saying who holds it). Every other copy is a
**read-only checkout**: a snapshot taken to another machine to read, never written to, replaced whole
and never brought up to date. A write to a copy forks it from the home, and nothing merges it back
([ADR 0022](adr/0022-the-records-home.md)).

**The alias.** On the laptop, run every command on the home over `ssh`:

```bash
# on laptop.example, in ~/.zshrc or ~/.bashrc
alias lb='ssh records@server.example .local/bin/logbook'
```

```bash
# on laptop.example
lb day 2026-10-12
lb digest
lb add "'Rowed out to the island with Ola.'"
```

`ssh` joins the words it is given into one line for the shell at the far end, so a word with a space,
a `*` or a quote in it needs a second pair of quotes, as the note above has. A command that asks you
things (`setup`, `day reflect`) wants a terminal: `ssh -t records@server.example .local/bin/logbook
setup`. A command that needs the sources' keys reads them as the schedule does:

```bash
# on laptop.example
ssh records@server.example 'set -a; . ~/.config/logbook/sync.env; set +a; .local/bin/logbook sync immich'
```

**A read-only checkout** for reading on the laptop away from home: copy a snapshot from the backup
disk, check it, and take its write permission away. Keep it out of `~/Logbook`, so a bare `logbook` on
the laptop finds no record at all.

```bash
# on laptop.example
lb backup list /mnt/backup/Logbook                                  # the newest snapshot is the last
scp -r records@server.example:/mnt/backup/Logbook/<owner_id>/<timestamp> ~/Records/Logbook-copy
logbook verify --root ~/Records/Logbook-copy                        # valid — …
chmod -R a-w ~/Records/Logbook-copy
alias lb-copy='LOGBOOK_HOME="$HOME/Records/Logbook-copy" logbook'
lb-copy day 2026-06-13
```

The readers keep their index in your cache directory, not in the record folder, so `day`, `show`,
`search`, `people`, the rollups, the Year and `doctor` read a checkout without write permission as
they read any record, and a writer started on it by mistake cannot write a line. `digest` is the
exception: it keeps the questions it has asked in the record (`state/questions.json`, and the default
`policy/questions.json` when there is none), so read the digest on the home, `lb digest`. On a record
that seals, the checkout opens tiers 2 and 3 only on a machine that holds the identity; without it the
days list their sealed lines as sealed, which is the right state for a laptop that travels. A snapshot
carries no `state/`, so the checkout names no home and runs no schedule; keep it that way. To bring it
up to date, `chmod -R u+w`, delete it, copy a newer snapshot.

## 9. Backups and the monthly restore test (5 minutes)

A snapshot a night to the backup disk, by a timer of your own, as `records`. This is
[backup](backup.md)'s user timer written as a system unit, since `records` has no session:

```bash
# as owner, on server.example
sudo install -d -m 700 -o records -g records /mnt/backup/Logbook
```

```ini
# /etc/systemd/system/logbook-backup.service, written by owner
[Unit]
Description=logbook backup: one verified snapshot, keep fourteen
ConditionPathIsMountPoint=/mnt/backup

[Service]
Type=oneshot
User=records
Environment=LOGBOOK_HOME=/home/records/Logbook
ExecStart=/home/records/.local/bin/logbook backup /mnt/backup/Logbook --keep 14
```

```ini
# /etc/systemd/system/logbook-backup.timer, written by owner
[Unit]
Description=logbook backup at 03:00 local

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true
Unit=logbook-backup.service

[Install]
WantedBy=timers.target
```

```bash
# as owner, on server.example
sudo systemctl daemon-reload
sudo systemctl enable --now logbook-backup.timer
```

03:00 sits between the schedule's runs, so the schedule appends nothing while the copy runs (a line
appended mid-copy makes the copy fail to verify, and the command says to run it again).
`ConditionPathIsMountPoint` skips a night the disk is not there rather than filling the system disk.
Run the first one by hand, as records, and look at what it printed:

```bash
# as records, on server.example
logbook backup /mnt/backup/Logbook --keep 14     # four lines; the third is `valid — N lines, head …`
logbook backup list /mnt/backup/Logbook
```

**The monthly restore test** is part of the schedule: on the first Sunday of the month the scheduled
run restores the latest snapshot into a temporary folder, verifies it, compares it with what the record
said when the backup was taken, and deletes it; `doctor`'s `restore-test` line passes for 35 days after
a test that passed. By hand, any time: `logbook backup --restore-test`. A record that seals needs
`LOGBOOK_IDENTITY_FILE` in the env file, or the test is skipped and `doctor` warns. A second backup disk
that lives somewhere else, carried home now and then, covers what one disk in one house cannot.

When a test fails, or `verify` says anything but `valid`, [When verify fails](recovery.md) has the one
command for each message.

## 10. The Library on your phone, over a private network (5 minutes, once the network exists)

The pages bind 127.0.0.1 and nothing else, as a service as by hand, and no flag changes that
([serve](serve.md#reaching-it-from-another-device)). The phone reaches them through something you put
in front, on this machine's terms. The pattern, whatever product you use for it:

1. **A private network of your own devices.** The server and the phone are members; nothing else is.
   Traffic between them is encrypted end to end, and no relay in between can read it.
2. **A proxy on the server** that listens on the server's address in that network only (never on all
   interfaces, never on the home network's address, never a port opened on the router), serves HTTPS
   with a certificate for the server's private name, and forwards to `http://127.0.0.1:8765`.
3. **The phone** bookmarks the private name and `/today`: `https://server.example/today`, which is
   today's page by the record's clock and `day_start`, whatever the phone's clock says.

What it means:

- **Every tier is on the pages.** The server reads them all because nothing it serves leaves the
  machine; whoever reaches the proxy reads everything. Keep the private network to your own devices:
  no shared or borrowed ones, and never a cloud machine between the phone and the pages.
- **The Places form is read-only behind the proxy.** A naming is accepted only from 127.0.0.1 with the
  server's own origin, so from the phone the Places page reads and its buttons are refused. To name
  places from the laptop, use a tunnel, through which the form works:

  ```bash
  # on laptop.example
  ssh -N -L 8765:127.0.0.1:8765 records@server.example     # then http://127.0.0.1:8765/places here
  ```

- **A reload is cheap.** A page whose head has not moved is a `304` with no body, so a phone that
  reloads `/today` all day costs the server next to nothing.

## 11. What doctor shows when everything is right

Run it as the schedule does, with the env file read, so the `sync:` lines see the keys:

```bash
# as records, on server.example
(set -a; . ~/.config/logbook/sync.env; logbook doctor)
```

```
pass  record            48,213 lines, head 5b0c9e1d2f3a…, verified; /home/records/Logbook
pass  index             index.sqlite is current with logbook.json
pass  day-start         the day begins at 06:00: a line before 06:00 belongs to the day before (logbook.json day_start)
pass  owner             policy/owner.json names 1 names, 1 emails
pass  places            4 place(s), home: Home
pass  assets            1 asset(s): nordlys
pass  dates             every line is dated inside its source's plausible range (policy/plausible.json)
pass  extra:ais         websockets is installed
pass  extra:crypto      cryptography is installed
pass  extra:sealed      pyrage is installed
pass  extra:transcribe  faster-whisper is installed
pass  sync:immich       configured (LOGBOOK_IMMICH_URL, LOGBOOK_IMMICH_KEY)
pass  sync:dawarich     configured (LOGBOOK_DAWARICH_URL, LOGBOOK_DAWARICH_KEY)
pass  crossing          hermes 2, mcp 1, dream 2 until 2027-03-31 model qwen2.5-7b-instruct
pass  home              this machine (server) is the record's home since 2026-10-13
pass  last-run          2026-10-14 06:00 (2 h ago): immich 12, dawarich 214 lines; doctor 20 pass, 0 warn, 0 fail
pass  restore-test      passed 2026-10-04 (2026-10-03T010000Z, 48,190 lines)
pass  serve             systemd system service (/etc/systemd/system/logbook-serve.service) answering at http://127.0.0.1:8765/
pass  disk              412.6 GiB free on the record's volume
pass  folder            a plain local folder, no sync client
20 checks: 20 pass, 0 warn, 0 fail
```

The lines that say this page worked: `day-start` names your boundary; `crossing` lists the `dream` entry
with its `until`; `home` names this machine; `last-run` is less than 26 hours old and clean; `restore-test`
passed within 35 days; `serve` is the system service, answering; `folder` is a plain local folder. Your
sources, places and counts are your own. The same command without the env file warns on each `sync:`
line for the keys your shell does not have; that is the shell, not a fault.

## Troubleshooting

| You see | What it means | What to do |
|---|---|---|
| `logbook serve --status` exits 1: `nothing answers at http://127.0.0.1:8765/; its output: journalctl -u logbook-serve.service`; `doctor` warns on `serve` | the service is installed and not running: it exits as it starts | `sudo journalctl -u logbook-serve.service -n 50` as owner says why. The record moved, or the Python the unit names is gone (a reinstall with another Python): run `logbook serve --install-service --system` again as records, and as owner the three commands it prints (`sudo cp …`, `sudo systemctl daemon-reload`, `sudo systemctl restart logbook-serve.service`). Another program holds port 8765: install again with `--port 8080`, and tell the proxy |
| `logbook serve --status` exits 3: `no serve service installed` | the system's copy is not in `/etc/systemd/system` | the two `sudo` lines of step 6 were not run, or were run for another file; run `logbook serve --install-service --system` again and run what it prints |
| The schedule ran twice: `doctor` warns `the schedule is installed twice, as systemd user timers and as systemd system timers: every run happens twice`, and the journal shows a run waiting: `another logbook command is writing to this record (…); waiting` | a `sync --install-schedule` without `--system` was run as records too; every source is asked twice. The lock keeps the chain whole; the waste and the double messages are the fault | as records, `logbook sync --uninstall-schedule` removes the user's timers and keeps the system's. Two runs back to back just after boot are the runs missed while the machine was off (`Persistent=true`), not this. A schedule left on the laptop does not run here twice; it keeps writing a second record there: `logbook sync --uninstall-schedule` on the laptop (step 3) |
| `the record's head moved from seq N to seq M while this command ran, so the batch it computed would not chain; the batch was not written` (exit 2), or the dream's `the record's head moved from … to … while the model read the day, …; nothing was written, dream the day again` | something wrote to the record without the writer lock while the command ran: a copy written to and copied back, a version older than the lock, a hand edit. Nothing was written, so the record is whole | find the other writer and stop it; there is one writer, here. Then `logbook verify`: `valid` and the same command again (for the dream, `logbook dream day DAY`, or wait for the next close). Anything else: [When verify fails](recovery.md); two chains from one head is `logbook repair fork`, then `--apply` |
| The 06:00 close ends `scheduled run, the close (dream --catch-up exit 1): clean`, and `sudo journalctl -u logbook-sync-close.service` shows a day `refused` with `the endpoint could not be reached in 2 attempts (HTTP 500 Internal Server Error); nothing was written` | the model's server answered 500 twice, two seconds apart: it ran out of memory, or the day's material is longer than the context it was started with. `TimeoutError` in place of `HTTP 500` is the same with a reply slower than two minutes | `systemctl status local-model.service` and `sudo journalctl -u local-model.service -n 50` say which. Then the diagnostic of [the doctor](doctor.md): `logbook doctor` as records, whose `crossing` line must list `dream` with no `expired`. Then the day by hand, with the two variables as in step 7: `logbook dream day DAY --dry-run --show-prompt` shows what is sent. Start the server with a larger context or a smaller model. Nothing was written; the next close catches the day up |
| `doctor` on the server warns `this machine is not the record's home (…); writers belong on the home` | the server's hostname changed, or the record was copied with its `state/` folder from the machine that was its home (a snapshot leaves `state/` out; a plain copy does not) | as records, `logbook sync --install-schedule --system` again: it names this machine (`(it was …)`) and prints the replacing commands, which change nothing that runs |
| `doctor` warns `last-run … more than 26 h ago: is the schedule still installed?` | the timers have not run: the machine was off, or they are not enabled | `systemctl list-timers 'logbook-sync*'`; when they are not listed, the second `sudo` line of step 6 again |
| `doctor` warns `restore-test  skipped …` | the restore test could not run: no backup recorded yet, or a record that seals without `LOGBOOK_IDENTITY_FILE` in the env file | run `logbook backup /mnt/backup/Logbook` once, or add the identity's path to the env file (step 4); then `logbook backup --restore-test` |

## Keeping it current

```bash
# as records, on server.example
uv tool upgrade openlogbook
logbook --version
```

```bash
# as owner, on server.example
sudo systemctl restart logbook-serve.service
```

The timers run the new version at their next run; the pages need the restart. When the release notes
say a unit changed, run both installs of step 6 again and the replacing commands they print.

## On a Mac

The same steps hold on a Mac mini kept at home, with these differences:

- `--system` writes launchd daemons, not units. The pages: `org.logbook.serve.plist` in the home
  directory, installed with the two lines it prints,
  `sudo cp /Users/records/org.logbook.serve.plist /Library/LaunchDaemons/org.logbook.serve.plist` and
  `sudo launchctl bootstrap system /Library/LaunchDaemons/org.logbook.serve.plist`. The schedule:
  `org.logbook.sync.plist` and `org.logbook.sync.close.plist`, copied to `/Library/LaunchDaemons` and
  bootstrapped the same way. Their output goes to `~/Library/Logs/logbook-serve.log` and
  `logbook-sync.log` in `records`'s home, not the journal.
- `records` is a standard account that no one logs in to at the screen, with Remote Login allowed for
  it; set the clock's timezone in System Settings.
- On Apple silicon, `transcribe` is `mlx-whisper` (it needs `ffmpeg` on the path) and `describe` works:
  install `openlogbook[describe]` too, and run `logbook derive descriptions keepers` with `--photos`
  naming a folder of the photo files that `records` can read.
- The model's daemon is a launchd daemon of your own in `/Library/LaunchDaemons` with the same
  `llama-server` arguments, run as an account that cannot read `records`'s home.
- The backup disk is under `/Volumes`; [backup](backup.md#a-schedule) has the launchd job, which on the
  home becomes a daemon with `UserName` `records`.
