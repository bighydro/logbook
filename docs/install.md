# Installing Logbook

Logbook is a command you type in a terminal, the plain text window a computer has had since before
it had windows. This page gets the command onto your Mac, Windows PC or Linux machine, one line
per platform, and tells you what the screen will show at each step so you know it is going right.
Nothing here needs you to have used a terminal before. If you have, the whole page is the three
lines at the top of the README; the rest is for everyone else.

Installing takes a couple of minutes. It puts one command, `logbook`, on your computer. It does not
create your record, read anything of yours or send anything anywhere; that starts only when you run
`logbook setup` afterwards ([The first hour](first-hour.md)), and even then it stays in a folder on
this machine.

## What a terminal looks like

A terminal is a window with dark or white background and a line of text ending in a cursor. That
line is the *prompt*: it is the computer saying it is ready. On a Mac it looks something like

    ines@MacBook ~ %

on Windows like

    PS C:\Users\ines>

and on Linux like

    ines@laptop:~$

with your own name in place of `ines`. You type a line after the prompt and press Enter (Return on
a Mac). The computer does what the line says, prints what it has to say, and shows a new prompt.
While it is working there is no prompt; a command that takes a minute shows nothing new for a
minute, and that is normal. Many commands print nothing at all when they succeed: a new prompt with
no message is good news.

To put a line from this page into the terminal, copy it here and paste it there: **⌘V** on a Mac,
**Ctrl+V** in Windows Terminal, **Ctrl+Shift+V** in most Linux terminals. Lines shown in this page
without a `$` or `%` are exactly what to type; the prompt is already on your screen, so you never
type it. If a line is long, it is still one line: paste it whole and press Enter once.

Two things that look wrong and are not: when a terminal asks for your password, nothing appears as
you type, not even dots; type it and press Enter. And when a terminal prints a paragraph you do not
understand, read the last two lines; that is where it says whether it worked.

## Mac

The one line is

```bash
brew install bighydro/logbook/logbook
```

and it needs **Homebrew**, the installer most Mac software for the terminal comes through. Open the
terminal first: press **⌘ Space**, type `Terminal`, press Return. A window opens with the prompt.

### If you do not have Homebrew yet

Type `brew --version` and press Return. If it prints `Homebrew 4.` and a number, skip to the next
heading. If it says `zsh: command not found: brew`, install it with the line from
[brew.sh](https://brew.sh), which is

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

It prints what it is going to do, under *This script will install:*, and waits with
*Press RETURN/ENTER to continue or any other key to abort*. Press Return. It asks for your Mac
password (nothing shows as you type; press Return when done). Then it works for a few minutes,
printing a lot; on a Mac that has never built anything it first installs Apple's *Command Line
Tools*, which can add ten minutes and may show a separate dialog asking you to agree. The end is

    ==> Installation successful!

followed by **Next steps**. Do what the next steps say: on a recent Mac they are two or three lines
starting with `echo` and `eval` that you copy from your own screen and paste back, so the terminal
can find `brew` from now on. After that, `brew --version` prints a version. (If it still says
*command not found*, close the terminal window, open a new one, and try again; a terminal learns
about new commands when it starts.)

### Install Logbook

```bash
brew install bighydro/logbook/logbook
```

The first time, Homebrew fetches the *tap* (the small repository that holds the recipe) and prints

    ==> Tapping bighydro/logbook
    Cloning into '/opt/homebrew/Library/Taps/bighydro/homebrew-logbook'...
    Tapped 1 formula

then

    ==> Fetching bighydro/logbook/logbook
    ==> Downloading https://files.pythonhosted.org/packages/.../openlogbook-0.5.0.tar.gz
    ==> Installing logbook from bighydro/logbook

and a minute or two of lines about Python and a package called `ijson`, which it builds for your
machine. The last line is the beer glass:

    🍺  /opt/homebrew/Cellar/logbook/0.5.0: 180 files, 2.1MB, built in 45 seconds

The numbers differ; the glass is what matters. Jump to [Did it work?](#did-it-work).

### Mac, without Homebrew

If you already have `pipx` or `uv` (see Linux below for what they are), either of

```bash
pipx install openlogbook
uv tool install openlogbook
```

does the same thing, and is the way to install an [extra](#optional-extras).

## Windows

The one line is

```powershell
pipx install openlogbook
```

and it needs **Python** and **pipx**, which Windows does not come with. Three short steps get them.
Open the terminal first: press the **Windows key**, type `Terminal`, press Enter. (On Windows 10
without Windows Terminal, type `PowerShell` instead; the window is blue and works the same way.)

### 1. Python

Type `python --version` and press Enter.

- If it prints `Python 3.12.` or `Python 3.13.` or higher, you have it; go to step 2.
- If the Microsoft Store opens on a page for Python, that is Windows offering to install it. Press
  **Get**, wait for it to finish, close the Store, and run `python --version` again in the terminal.
- If it prints `Python 3.11.` or lower, or *'python' is not recognized*, install it:

  ```powershell
  winget install Python.Python.3.13
  ```

  `winget` asks you to agree to the source terms the first time (type `Y`, Enter), shows a progress
  bar, and ends with *Successfully installed*. Then close the terminal, open a new one, and
  `python --version` prints `Python 3.13.` and a number.

### 2. pipx

`pipx` installs Python command-line tools, each in its own compartment, so Logbook never
interferes with anything else on the computer. Two lines:

```powershell
python -m pip install --user pipx
python -m pipx ensurepath
```

The first prints *Collecting pipx*, a few *Downloading* lines, and *Successfully installed pipx-*
and a number. (A yellow *WARNING: The script pipx.exe is installed in ... which is not on PATH* is
expected; the second line fixes exactly that.) The second prints

    Success! Added C:\Users\ines\.local\bin to the PATH environment variable.
    Consider adding shell completions for pipx. Run 'pipx completions' for instructions.

    You will need to open a new terminal or re-login for the PATH changes to take effect.

Do as it says: close the terminal window and open a new one.

### 3. Logbook

```powershell
pipx install openlogbook
```

It takes half a minute and prints

      installed package openlogbook 0.5.0, installed using Python 3.13.2
      These apps are now globally available
        - logbook.exe
    done! ✨ 🌟 ✨

Jump to [Did it work?](#did-it-work).

### Windows, with uv instead

If you would rather have one tool that also brings its own Python, `uv` does both steps in one:

```powershell
winget install astral-sh.uv
```

then close the terminal, open a new one, and

```powershell
uv tool install openlogbook
```

prints *Resolved*, *Installed* and finally `Installed 1 executable: logbook.exe`. If it adds a
yellow warning that a folder is *not on your PATH*, run `uv tool update-shell`, then close and
reopen the terminal.

## Linux

The one line is

```bash
pipx install openlogbook
```

with `pipx` from your distribution: `sudo apt install pipx` on Debian and Ubuntu, `sudo dnf install
pipx` on Fedora, `sudo pacman -S python-pipx` on Arch. Then `pipx ensurepath` once, a new terminal,
and the line above, which ends with

      installed package openlogbook 0.5.0, installed using Python 3.12.3
      These apps are now globally available
        - logbook
    done! ✨ 🌟 ✨

Logbook needs Python 3.12 or newer. On a distribution whose Python is older (Debian 12, Ubuntu
22.04), `pipx install` stops with a line about `Requires-Python >=3.12`; use `uv` instead, which
fetches a Python of its own:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

then a new terminal, and

```bash
uv tool install openlogbook
```

which prints *Resolved*, *Installed* and `Installed 1 executable: logbook`. Both `pipx` and `uv`
put the command in `~/.local/bin`; if the terminal cannot find `logbook` afterwards, that folder is
not on your path and `pipx ensurepath` or `uv tool update-shell` adds it, from the next terminal on.

Nix and Docker users: [the tour](tour.md) has the `nix run` and `docker run` lines.

## Did it work?

In a terminal, type

```bash
logbook --version
```

and press Enter. It prints one short line, the version:

    0.5.0

That is the whole check. From here, [The first hour](first-hour.md) sets up your own record one
question at a time, and [Try it](try-it.md) gives you a month of someone who does not exist to
look around in first.

If instead it says `command not found: logbook` (Mac, Linux) or *'logbook' is not recognized as
the name of a cmdlet* (Windows): close the terminal window, open a new one, and try again. Every
installer above tells the terminal where the new command lives, but a terminal only reads that when
it opens. If a fresh terminal still does not find it, the installer printed how to fix it, in the
lines about PATH: on Mac and Linux `pipx ensurepath` or `uv tool update-shell`, on Windows
`python -m pipx ensurepath` or `uv tool update-shell`, then another new terminal.

## Keeping it current

Logbook changes often. The update is the same tool that installed it:

| installed with | update                        | remove                         |
| -------------- | ----------------------------- | ------------------------------ |
| Homebrew       | `brew upgrade logbook`        | `brew uninstall logbook`       |
| pipx           | `pipx upgrade openlogbook`    | `pipx uninstall openlogbook`   |
| uv             | `uv tool upgrade openlogbook` | `uv tool uninstall openlogbook`|

Removing the command never touches your record. The folder `logbook setup` made (`~/Logbook`
unless you chose otherwise) stays where it is, readable as plain files, and a later install finds
it again.

## Optional extras

Some features need an extra library: reading an encrypted iPhone backup (`encrypted`), sharing a
signed page (`share`), serving the record to an AI assistant (`mcp`), listening to ships (`ais`),
transcribing voice memos (`transcribe`), and the two local models on Apple silicon (`judge`,
`describe`). Logbook tells you when a command needs one; `logbook doctor` lists them with a
`pass` or `warn` each. You add one by installing the package with the extra's name in brackets:

```bash
pipx install --force "openlogbook[encrypted]"
uv tool install "openlogbook[encrypted]"
```

Several at once are a comma-separated list: `"openlogbook[encrypted,share]"`. The quotes matter;
the brackets mean something else to the terminal without them. The Homebrew formula installs the
base package only: a Mac that needs an extra uses `pipx` or `uv` for Logbook instead, which is a
`brew uninstall logbook` followed by one of the two lines above. Your record is untouched either way.

## If something goes wrong

- **The terminal asks *Are you sure you want to continue connecting* or *Allow this app to make
  changes*.** That is Homebrew, winget or your distribution's installer asking before it installs
  a tool; say yes to those. Logbook itself never asks for anything.
- **A wall of red text.** Read the last two lines. *No matching distribution* or *Requires-Python*
  means the Python on this machine is too old; use `uv`, above. *Permission denied* means the line
  was run somewhere it should not write; none of the lines on this page need `sudo` except the
  `apt`, `dnf` and `pacman` ones.
- **It worked yesterday and not today.** Something updated the Python underneath `pipx`. The fix is
  `pipx reinstall-all`, or `uv tool upgrade --all`.
- **Anything else.** Open an issue at <https://github.com/bighydro/logbook/issues> with the exact
  lines you typed and the last ten lines the terminal printed. Nothing in them is personal; the
  record does not exist yet.
