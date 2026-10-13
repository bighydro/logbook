# The record in a browser

`logbook serve` reads the record in a browser, on this machine only.

```bash
logbook serve                     # http://127.0.0.1:8765/
logbook serve --port 8080
logbook serve --install-service   # kept running by launchd or systemd (As a service, below)
```

It is a reader (ADR 0013) with another output: the pages are the commands' own readers rendered as
HTML instead of text, built from the index and nothing else, and nothing is written. Open the
address it prints, read, close it. There is no login because there is no one to log in: the server
answers this machine and no other.

![The Day of 17 June of the demo record, every attachment toggle open](serve.png)

*The demo record (`logbook demo --days 30 --seed 1 --out ~/Demo`), Wednesday 17 June: a week
aboard the yacht Nordlys. Nothing in it is real.*

## The pages

| Page | What it is | The command it renders |
|---|---|---|
| `/day/YYYY-MM-DD` | the Day as a timeline: the nights either side, the country, the all-day entries; one row per stay, stop, move, flight or run aboard an asset, in time order, with the clock, the kind and what it was; each row's attachments (events, transcripts, notes, mail threads, calls, keepers named; messages and photos counted) and company (confirmed, then proposed) under a toggle; what is unplaced; the health line; the sources and when each last spoke | `logbook day` |
| `/days?from=&to=` | one row per day of the window, the day a link to its Day: the night, the kilometres moved, the flights, the stays and what attached, the people confirmed, the health triple, the usual sources with no line that day. Without a window, the record's last fortnight; a form and *earlier* / *later* links move it | `logbook days` |
| `/trips?year=` | the trips of the year: first and last day (a link to those days), nights, route, flights in and out, places, people. Without a year, the record's last; every year the record covers is a link | `logbook trips --year` |
| `/places` | the named places of `places.json`: position, radius, kind, tags, country | `logbook places list` |
| `/assets` | the registered assets and the last fix of each: the time, the position, the nearest named place, the speed, how long ago | `logbook assets status` |
| `/gaps?since=` | where each source went quiet: lines, first and last line, the longest silence, the days with no line folded into runs | `logbook sources --gaps` |

`/` is the front page: how many lines the record holds and the days it covers, and a link to each page.
`/today` redirects to the Day of the current date in the record's timezone (`logbook.json`), the date
before until the record's `day_start` when it sets one (at 05:59 under `06:00`, yesterday's Day), whatever
the clock of the device that asks: the page to bookmark on a phone.
`/day/YYYY-MM-DD?open=1` is the Day with every toggle open, for printing or saving whole; the page's
*expand all* link is that.

Every row reads as the command prints it, because it is the same code: the grammar of a stay, a
move or a night is `logbook/core/day.py`'s and `logbook/core/days.py`'s, a trip's is `logbook/core/trips.py`'s, a
silence's is `logbook/contrib/gaps.py`'s. A number here points at the lines it came from as it does under
`--json`: hover an attachment and its line ids are the tooltip.

## Three rules

Each is enforced in `logbook/contrib/serve.py` and tested in `tests/test_serve.py`.

**This machine only.** The server binds `127.0.0.1` and refuses any other host before a socket is
opened: `--host 0.0.0.0`, `::`, a LAN address, even `localhost` (a name, and a name may resolve to
anything) exit 2 naming the one host it takes. It never resolves a name, not even its own, and it
never binds anywhere else: not as a service either ([As a service](#as-a-service)), whose file never
carries `--host`. To read the record from another device, see
[reaching it from another device](#reaching-it-from-another-device).

**One document, nothing fetched.** A page is one HTML document with one inline stylesheet. No
script, no font, no image, no stylesheet link, no frame; every link, form and tooltip points at the
server's own paths. The `Content-Security-Policy` header the server sends (`default-src 'none'`)
tells the browser the same, so a payload that carried markup could not make a page fetch from
elsewhere even if the escaping here were wrong (every value is escaped). The test renders every page
and checks each attribute that can hold a URL, the inline style and the headers.

**Read-only.** Every request is a GET answered from the record at its head through the readers, and
the readers never write, not even `policy/stays.json`. The test takes the head and every file before
and after serving every page and finds them the same. The server keeps nothing but the head it last
saw: when a sync moves the head while it runs, the next request brings the index to the new head
first and every page reads the new lines, with no restart. That rebuild happens once, under a lock,
however many requests arrive at that moment; they wait for it rather than each starting their own on
the same file.

## Performance

A Day is one `day.read`: one reading of the day and the day before through `index.sqlite`, the
health lines of the two days by an indexed column, nothing swept. On the demo record a Day answers in
tens of milliseconds, a month of `/days` in under half a second; on a record of millions of lines a
Day still renders in under a second, because the index locates the day's lines and only they are
read ([docs/day.md](day.md), *Performance*). `/days` reads the window in chunks of a month, as the
command does; a year is a dozen readings. The airports table is loaded once, when the server starts.

A reload at the same head costs nothing. Every page that is the record's and nothing else (`/`, a
Day, `/days`, `/trips`, `/places`) carries an `ETag`: the first twelve characters of the head, then a
digest of the request and of what else the page reads (the rest of `logbook.json`, `places.json`,
`assets.json`, `policy/`, the pages received from the circle) and of the server's start. It is sent
with `Cache-Control: no-cache`, so the browser keeps the page and asks every time; when the tag it
sends back is the page's, the answer is a `304` with no body and nothing is read or rendered. A sync
that moves the head, a place renamed or a restart changes the tag, and the next reload is the page
again. `/assets` and `/gaps`, which the clock moves (the age of a fix, a silence that runs to now),
and every error carry no tag and `Cache-Control: no-store`, as before.

The server is the standard library's (`http.server`, one thread per request); it is meant for one
reader on one machine, not for a crowd.

## As a service

```bash
logbook serve --install-service                # as you: a launchd agent, or a systemd user service
logbook serve --install-service --port 8080
logbook serve --install-service --system       # a machine nobody logs in to: prints two sudo commands
logbook serve --status                         # installed? answering? (exit 0, 1, 3)
logbook serve --uninstall-service [--system]
```

`--install-service` keeps `logbook serve` running, so the pages are there in the morning without a
terminal open. The service runs the Python that installed it (`sys.executable -m logbook.cli serve
--port N`, no PATH assumed) on the record this command found (`LOGBOOK_HOME`, and
`LOGBOOK_IDENTITY_FILE` when it is set, so a sealed record's pages open as they do by hand: paths,
never a key). It starts at load, is started again whenever it fails, and its output goes beside the
sync log. As with the schedule ([docs/schedule.md](schedule.md)), the plist or unit is printed
before it is written and nothing is written outside the one directory; the file comes from the same
renderer as the schedule's.

| | macOS | Linux |
|---|---|---|
| without `--system` | a launchd agent, `~/Library/LaunchAgents/org.logbook.serve.plist`, loaded now and at every login | a systemd user service, `~/.config/systemd/user/logbook-serve.service`, enabled and started now; from boot when you linger (`loginctl enable-linger`), else with your session |
| with `--system` | a launchd daemon that runs as you (`UserName`) from boot: `/Library/LaunchDaemons/org.logbook.serve.plist` | a system service that runs as you (`User=`) from boot: `/etc/systemd/system/logbook-serve.service` |
| its output | `~/Library/Logs/logbook-serve.log`, beside `logbook-sync.log` | `journalctl --user -u logbook-serve.service`; with `--system`, `journalctl -u logbook-serve.service` |
| started again | `KeepAlive` when it exits unsuccessfully | `Restart=on-failure`, five seconds later |

**The record's home.** The machine that keeps the record (ADR 0022) is often run by a dedicated user
that never has a login session, and an agent cannot load in a session that never starts. That is
what `--system` is for: run as that user, it writes the daemon to the home directory and prints the
two commands that install it, which you run as an administrator. It never runs `sudo` itself, and it
refuses to run as root (the daemon would run as root, with root's home):

```
$ logbook serve --install-service --system
writing /Users/ines/org.logbook.serve.plist:
…
written: a launchd daemon running `logbook serve --port 8765` as ines from boot, started again when it fails; nothing runs until you install it, as an administrator:
  sudo cp /Users/ines/org.logbook.serve.plist /Library/LaunchDaemons/org.logbook.serve.plist
  sudo launchctl bootstrap system /Library/LaunchDaemons/org.logbook.serve.plist
then http://127.0.0.1:8765/ (/today is today's page); its output: ~/Library/Logs/logbook-serve.log; …
```

Run again over a daemon already installed, it prints `sudo launchctl bootout system/org.logbook.serve`
first; on Linux it prints the copy, `systemctl daemon-reload` and `systemctl restart` in place of the
copy and `systemctl enable --now`. `--uninstall-service --system` removes the copy in the home
directory and prints the two commands that stop the service and remove the system's copy.

**Is it up?** `logbook serve --status` lists the serve services installed here, the user's and the
system's, the port each runs on, and whether a logbook server answers there: exit 0 when every one
answers, 1 when one does not (with where its output goes), 3 when none is installed. The question is
one `HEAD /favicon.ico` to 127.0.0.1, which reads nothing of the record. `logbook doctor` asks the
same in its `serve` line: a pass when no service is installed or when it answers, a warn when it is
installed and silent, or when two share one port.

**After a sync** nothing needs restarting: the next page reads the new head (see *Read-only* above),
and a phone's reload of a page whose head has not moved is a `304`.

### Reaching it from another device

The server binds 127.0.0.1 and nothing else, as a service as by hand; no flag changes that. Reading
the pages from a phone or another machine is your business, done on this machine's terms and by a
tool you choose:

- **an SSH tunnel** from the other device: `ssh -L 8765:127.0.0.1:8765 <this machine>`, then
  http://127.0.0.1:8765/ there;
- **a tailnet's own HTTPS proxy** running on this same machine and forwarding to
  `http://127.0.0.1:8765`, so the pages are reachable over the tailnet only, with its certificate and
  its access rules.

Either way the pages carry every tier the record holds (SPEC §4): the server reads them all because
nothing it serves leaves the machine, so whatever you put in front of it decides who else can read
them. Keep it to your own devices. The server does not know it is there and does not change for it:
same pages, same headers, the same refusal of any other host.

## What it is not

Not an editor: the pages write nothing, and the captain's words — a note, a naming, a confirmation
— go through the CLI as lines in the record, which the next page reads. Not a web application: no
JavaScript, no framework, no build step, no state but the record. Not the circle (ADR 0009): a page
here is for the owner's eyes on the owner's machine; a shared page is a signed bundle, and that is
another layer.
