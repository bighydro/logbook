"""`logbook setup`: the guided first run, for someone who has never used a terminal.

One question at a time, in plain words, each with its default in brackets and a line saying why it is
asked. Enter takes the default, `s` skips the step, `q` (or closing the input) stops: what was answered
is kept, and `logbook setup` again continues where it stopped. The steps, in order (`STEPS`):

- `folder`: where the record lives. A folder iCloud Drive, Dropbox, OneDrive or Google Drive syncs is
  refused with the reason (`doctor.cloud_folder`), and so is a code checkout (`Logbook.init`). The record
  is created here, with the zone this machine detects, so the state below has somewhere to live.
- `timezone`: the record's zone (SPEC §3.2, `logbook.json`), validated against this machine's zone
  database and never swapped for another.
- `owner`: the names, emails and phones that are the owner's, into `policy/owner.json`, so the people
  readers never list the owner as their own company (`present.owner_of`). Added to what the file lists.
- `home`: the home place, from coordinates pasted out of a maps app, never an address: one entry of
  kind `home` in `places.json` and the naming as one `note/v1` line, as `logbook places name` does.
- `sources`: what is on this machine — a Google Takeout under `~/Downloads`, an iPhone backup under
  MobileSync, Messages on a Mac — each offered with a dry run first, the counts shown, nothing written
  until the person says so. An iPhone backup is always imported with `--only` the stores found, never
  bare (CLAUDE.md). Then the live sources, by the names of their variables and where the key comes from.
- `doctor`: the checks of `logbook doctor`, so the person sees the record is set up.

State is `<root>/state/setup.json`, `{"steps": {"folder": "done", "owner": "skipped", …}}`, bookkeeping
beside the record like every other file under `state/`, never in the chain. `--step NAME` runs one step
again, `--again` every step, `--yes` takes every default and asks nothing, so tests and scripts can run it.

Nothing here prints a secret or asks for one: an encrypted backup's password stays in
`LOGBOOK_BACKUP_PASSWORD` and is never read by this module; a live source is described by the names of its
variables, never a value. Nothing printed spells the home directory: paths under it print as `~/…`."""

from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
import zoneinfo
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Any

from ..contrib import adapters, doctor, ios_backup
from ..contrib.adapters import imessage_live
from ..core import places, policy
from ..core.store import CodeCheckoutError, Logbook, now_utc

STATE_FILE = PurePath("state") / "setup.json"
STATE_VERSION = 1
STEPS = ("folder", "timezone", "owner", "home", "sources", "doctor")
TITLES = {
    "folder": "where to keep the record",
    "timezone": "your timezone",
    "owner": "who you are",
    "home": "your home place",
    "sources": "what is on this machine",
    "doctor": "a check-up",
}
DONE, SKIPPED = "done", "skipped"
SKIP_WORDS = frozenset({"s", "skip"})
QUIT_WORDS = frozenset({"q", "quit"})
YES_WORDS = frozenset({"y", "yes"})
DEFAULT_FOLDER = ("Logbook",)  # under the home directory, as `logbook init` and `Logbook.find`
DOWNLOADS = ("Downloads",)
TAKEOUT_PREFIX = "takeout"
TAKEOUT_INNER = "Takeout"  # Google's zip unpacks to Takeout/<Product>/
SNIFF_FILE_BUDGET = 500  # files of one Takeout product sniffed before the rest are left to `logbook add`
#: where Finder, iTunes and the Apple Devices app keep iPhone backups, relative to home or to a variable
MOBILESYNC_UNDER_HOME = (
    ("Library", "Application Support", "MobileSync", "Backup"),  # macOS
    ("Apple", "MobileSync", "Backup"),  # Windows, iTunes from the Microsoft Store
)
MOBILESYNC_UNDER_APPDATA = ("Apple Computer", "MobileSync", "Backup")  # Windows, iTunes from Apple
MESSAGES_STORE = imessage_live.DEFAULT_DB  # a Mac's own Messages: Library/Messages/chat.db
PASSWORD_ENV = "LOGBOOK_BACKUP_PASSWORD"  # named, never read here
#: where the key or address of each live source comes from; names only, never a value
KEY_SOURCES = {
    "dawarich": "Dawarich → Settings → Account → API key; the URL is your Dawarich's address",
    "immich": "Immich → Account settings → API keys, with only the asset.read permission; the URL is yours",
    "gcal": "Google Calendar → Settings → the calendar → Integrate calendar → Secret address in iCal format",
    "granola": "Granola → Connectors → API keys (Business and Enterprise plans)",
    "beeper": "Beeper Desktop → Settings → Developers → Approved connections (+); the token reads every chat"
    " and can send as you, so it is a password; the app must be running, Remote Access off",
    "ais": "a free key from aisstream.io, for the vessels registered in assets.json",
    "adsb": "an account at opensky-network.org (optional: anonymous access works, with a lower rate)",
}
COORDINATES = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*$")
HOME_RADIUS_M = 120.0
CLOUD_SERVICES = "iCloud Drive, Dropbox, OneDrive or Google Drive"
RESUME_HINT = "Run `logbook setup` again any time: it continues where you stopped."
WIDTH = 96  # the `Why:` paragraphs are wrapped to this many columns

Importer = Callable[[Logbook, adapters.Adapter, Path, bool], int]
BackupImporter = Callable[[Path, tuple[str, ...], bool], None]
Syncer = Callable[[str, bool], None]
Detector = Callable[[], str | None]


class Stopped(Exception):
    """The person typed `q` or closed the input; the run ends here, its state kept."""


class Skipped(Exception):
    """The person typed `s`: the rest of this step is skipped and the next one asked."""


# -- what the person typed -------------------------------------------------------------------------------


def split_list(answer: str) -> list[str]:
    """`a, b,,c ` → `["a", "b", "c"]`: the commas split, the blanks go."""
    return [part.strip() for part in answer.split(",") if part.strip()]


def parse_coordinates(answer: str) -> tuple[float, float] | None:
    """`59.9139, 10.7522` (a comma or a space between) as (lat, lon) within range; None for anything
    else, an address above all."""
    m = COORDINATES.match(answer)
    if m is None:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return lat, lon


def under_home(path: Path) -> str:
    """`~/Logbook` for a path inside the home directory, else the path as given: what is printed
    never spells the user's name."""
    try:
        return str(PurePath("~") / path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def live_variable_names() -> list[str]:
    """Every variable a live adapter reads, so a test can clear the shell's own before it runs."""
    return [name for adapter in adapters.live_adapters() for name in adapter.ENV]


# -- the conversation --------------------------------------------------------------------------------------


class Console:
    """The questions and their answers. `yes` takes every default without asking (`--yes`)."""

    def __init__(self, yes: bool = False) -> None:
        self.yes = yes

    def say(self, text: str = "") -> None:
        print(text)

    def why(self, text: str) -> None:
        print(textwrap.fill(text, width=WIDTH, initial_indent="Why: ", subsequent_indent="     "))

    def ask(self, question: str, default: str | None, *, hint: str = "") -> str | None:
        """One question. Enter is the default (None when there is none: nothing to add); `s` skips the rest
        of the step (`Skipped`); `q` or the end of the input stops (`Stopped`). With `yes`, the default
        is taken and the question only shown."""
        shown = default if default is not None else "skip"
        prompt = f"{question} [{shown}]{hint}: "
        if self.yes:
            print(f"{prompt}{shown}")
            return default
        try:
            answer = input(prompt).strip()
        except EOFError as e:
            print()
            raise Stopped from e
        if answer.casefold() in QUIT_WORDS:
            raise Stopped
        if answer.casefold() in SKIP_WORDS:
            raise Skipped
        return answer or default

    def confirm(self, question: str, default: bool = True) -> bool:
        """A yes or no; Enter is the capital one. `s` and `q` as in `ask`. With `yes`, the default."""
        shown = "Y/n" if default else "y/N"
        if self.yes:
            print(f"{question} [{shown}]: {'yes' if default else 'no'}")
            return default
        answer = self.ask(question, shown)
        if answer is None or answer == shown:
            return default
        return answer.casefold() in YES_WORDS


# -- the state -----------------------------------------------------------------------------------------------


def state_path(root: Path) -> Path:
    return Path(root).joinpath(*STATE_FILE.parts)


def read_state(root: Path) -> dict[str, str]:
    """The steps answered so far, `{step: "done" | "skipped"}`; empty for no file or one that is not ours."""
    path = state_path(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    steps = data.get("steps") if isinstance(data, dict) else None
    if not isinstance(steps, dict):
        return {}
    return {k: v for k, v in steps.items() if k in STEPS and v in (DONE, SKIPPED)}


def write_state(root: Path, steps: Mapping[str, str]) -> Path:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {"version": STATE_VERSION, "steps": dict(steps), "updated_at": now_utc()}
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


# -- what is on this machine --------------------------------------------------------------------------------


@dataclass
class TakeoutJob:
    """One import `logbook add` would do: an adapter on a product folder, or on one file in it."""

    adapter: adapters.Adapter
    path: Path


@dataclass
class Takeout:
    folder: Path
    jobs: list[TakeoutJob] = field(default_factory=list)
    disabled: dict[str, str] = field(default_factory=dict)  # adapter name -> the reason in import.json
    unread: list[str] = field(default_factory=list)  # product folders no adapter claims


@dataclass
class Backup:
    folder: Path
    udid: str
    encrypted: bool
    sources: tuple[str, ...]  # the stores found, as `--only` names them
    plans: list[ios_backup.Plan]


def find_takeouts(home: Path, disabled: Mapping[str, str]) -> tuple[list[Takeout], list[Path]]:
    """The Takeout folders under ~/Downloads (any folder whose name starts with `takeout`, the `Takeout/`
    Google's zip unpacks to looked into) with what the adapters read in each, and the Takeout zips,
    which are named and not read: there is no zip reader yet."""
    downloads = home.joinpath(*DOWNLOADS)
    if not downloads.is_dir():
        return [], []
    takeouts: list[Takeout] = []
    zips: list[Path] = []
    for child in sorted(downloads.iterdir()):
        if not child.name.casefold().startswith(TAKEOUT_PREFIX):
            continue
        if child.is_file() and child.suffix.casefold() == ".zip":
            zips.append(child)
        elif child.is_dir():
            inner = child / TAKEOUT_INNER
            takeouts.append(_takeout(inner if inner.is_dir() else child, disabled))
    return takeouts, zips


def _takeout(folder: Path, disabled: Mapping[str, str]) -> Takeout:
    found = Takeout(folder)
    for product in sorted(folder.iterdir()):
        if product.name.startswith("."):
            continue
        jobs = list(_jobs(product))
        if not jobs:
            found.unread.append(product.name)
        for job in jobs:
            reason = disabled.get(job.adapter.NAME)
            if reason is not None:
                found.disabled[job.adapter.NAME] = reason
            else:
                found.jobs.append(job)
    return found


def _jobs(product: Path) -> Iterator[TakeoutJob]:
    """A product folder one adapter claims whole (`Google Chat/`, `Google Photos/`) is one job; else
    each file in it an adapter recognises is, up to `SNIFF_FILE_BUDGET` files looked at."""
    whole = adapters.find(product)
    if whole is not None:
        yield TakeoutJob(whole, product)
        return
    if product.is_file():
        one = adapters.find(product)
        if one is not None:
            yield TakeoutJob(one, product)
        return
    files = sorted(p for p in product.rglob("*") if p.is_file() and not p.name.startswith("."))
    for looked, file in enumerate(files, start=1):
        if looked > SNIFF_FILE_BUDGET:
            return
        adapter = adapters.find(file)
        if adapter is not None:
            yield TakeoutJob(adapter, file)


def backup_folders(home: Path, env: Mapping[str, str]) -> list[Path]:
    """Every folder iPhone backups are kept in on this machine, existing ones only."""
    roots = [home.joinpath(*parts) for parts in MOBILESYNC_UNDER_HOME]
    appdata = env.get("APPDATA", "").strip()
    if appdata:
        roots.append(Path(appdata).joinpath(*MOBILESYNC_UNDER_APPDATA))
    return [root for root in roots if root.is_dir()]


def find_backups(home: Path, env: Mapping[str, str]) -> list[Backup]:
    """Each backup under those folders, read only: encrypted or not, and for one that can be read, the
    stores the adapters know that are in it (`ios_backup.plan`)."""
    found: list[Backup] = []
    for root in backup_folders(home, env):
        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
            try:
                manifest = ios_backup.Manifest(folder)
            except ios_backup.NotABackup:
                continue
            plans = [] if manifest.encrypted else [p for p in ios_backup.plan(manifest) if p.found]
            sources = tuple(dict.fromkeys(p.source.name for p in plans))
            found.append(Backup(folder, manifest.udid, manifest.encrypted, sources, plans))
    return found


def messages_store(home: Path) -> Path | None:
    """This Mac's own Messages store when there is one (`logbook sync imessage` reads it)."""
    store = home.joinpath(*MESSAGES_STORE)
    return store if store.is_file() else None


# -- the wizard ----------------------------------------------------------------------------------------------


def _default_import(lb: Logbook, adapter: adapters.Adapter, path: Path, dry_run: bool) -> int:
    from ..commands import add  # the command's own code, so what setup imports is what `logbook add` imports

    return add._append_with(lb, adapter, path, None, dry_run=dry_run)


def _default_import_backup(folder: Path, only: tuple[str, ...], dry_run: bool) -> None:
    from ..commands import add

    args = argparse.Namespace(backup=str(folder), only=",".join(only), dry_run=dry_run, attachments=False)
    add.cmd_import_backup(args)


def _default_sync(name: str, dry_run: bool) -> None:
    from ..commands import sync

    args = argparse.Namespace(
        name=name,
        all=False,
        install_schedule=False,
        uninstall_schedule=False,
        since=None,
        listen=None,
        until=None,
        dry_run=dry_run,
    )
    sync.cmd_sync(args)


def _default_detect_timezone() -> str | None:
    from ..commands import record

    return record._detect_timezone()


class Wizard:
    """The steps, run in order from the first not yet answered; `run` returns the exit status."""

    def __init__(
        self,
        console: Console,
        env: Mapping[str, str],
        *,
        importer: Importer = _default_import,
        import_backup: BackupImporter = _default_import_backup,
        sync: Syncer = _default_sync,
        detect_timezone: Detector = _default_detect_timezone,
    ) -> None:
        self.console = console
        self.env = env
        self.importer = importer
        self.import_backup = import_backup
        self.sync = sync
        self.detect_timezone = detect_timezone
        self.lb: Logbook | None = None
        self.steps: dict[str, str] = {}

    # -- running --------------------------------------------------------------------------------------------

    def run(self, only: str | None = None, again: bool = False) -> int:
        say = self.console.say
        try:
            self.lb = Logbook.find()
        except FileNotFoundError:
            self.lb = None
        if self.lb is not None and not again:
            self.steps = read_state(self.lb.root)
        pending = [only] if only is not None else [step for step in STEPS if step not in self.steps]
        if self.lb is None and "folder" not in pending:
            pending.insert(0, "folder")
        if not pending:
            say("Setup is already complete for this record.")
            say("`logbook setup --step owner` (or any step) runs one step again;")
            say("`logbook setup --again` runs them all. The record is kept either way.")
            return 0
        say("Welcome. This sets up your logbook, one question at a time.")
        say("Enter takes the answer in brackets, s skips a step, q stops.")
        say("Nothing you type here is sent anywhere; it stays in the record's folder.")
        for step in pending:
            n = STEPS.index(step) + 1
            say()
            say(f"── Step {n} of {len(STEPS)}: {TITLES[step]} " + "─" * max(0, 60 - len(TITLES[step])))
            try:
                outcome = self._step(step)
            except Stopped:
                say()
                say(f"Stopped. {RESUME_HINT}")
                self._save()
                return 0
            self.steps[step] = outcome
            self._save()
        self._finish()
        return 0

    def _step(self, step: str) -> str:
        """One step to its outcome; `s` skips it, except the folder, which every later step needs."""
        while True:
            try:
                return str(getattr(self, f"step_{step}")())
            except Skipped:
                if step == "folder":
                    self.console.say("The record needs a folder before anything else; the default is fine.")
                    continue
                self.console.say("Skipped.")
                return SKIPPED

    def _save(self) -> None:
        if self.lb is not None:
            write_state(self.lb.root, self.steps)

    def _record(self) -> Logbook:
        assert self.lb is not None, "the folder step runs first"
        return self.lb

    def _finish(self) -> None:
        say = self.console.say
        lb = self._record()
        say()
        say("Setup is complete. Your record is at " + under_home(lb.root) + ".")
        home_default = Path.home().joinpath(*DEFAULT_FOLDER)
        pointed = self.env.get("LOGBOOK_HOME", "").strip()
        if lb.root.resolve() != home_default.resolve() and (
            not pointed or Path(pointed).expanduser().resolve() != lb.root.resolve()
        ):
            say("Every command looks for the record in ~/Logbook; yours is elsewhere, so put this line in")
            say("your shell profile (~/.zshrc on a Mac, ~/.bashrc on Linux) and open a new terminal:")
            say(f"    export LOGBOOK_HOME={under_home(lb.root)}")
        say("Next:")
        say('    logbook add "had lunch with a friend by the lake"    # a line in your words')
        say("    logbook show today                                   # the day read back")
        say("    logbook verify                                       # the chain is intact")
        say("docs/first-hour.md walks through the first hour.")

    # -- the steps ------------------------------------------------------------------------------------------

    def step_folder(self) -> str:
        c = self.console
        if self.lb is not None:
            c.say(f"Found your record at {under_home(self.lb.root)}; keeping it.")
            return DONE
        c.why(
            "The record is a folder of plain files: that is the whole product. It must be a folder no sync"
            f" service ({CLOUD_SERVICES}) touches: those evict files to the cloud, rewrite them underneath"
            " the writer and keep your record on someone else's server."
        )
        pointed = self.env.get("LOGBOOK_HOME", "").strip()
        default = Path(pointed).expanduser() if pointed else Path.home().joinpath(*DEFAULT_FOLDER)
        while True:
            answer = c.ask("Where should the record live?", under_home(default))
            root = Path(answer or under_home(default)).expanduser()
            if (root / "logbook.json").is_file():
                self.lb = Logbook(root)
                self.steps = read_state(root)
                c.say(f"Found your record at {under_home(root)}; continuing its setup.")
                return DONE
            service = doctor.cloud_folder(root, self.env)
            if service is not None:
                c.say(f"Not there: {under_home(root)} is under {service}; {doctor.CLOUD_REASON}.")
                c.say("Pick a plain local folder, such as ~/Records/Logbook.")
                continue
            zone = self.detect_timezone() or "UTC"
            try:
                self.lb = Logbook.init(root, zone)
            except CodeCheckoutError as e:
                c.say(f"Not there: {e}.")
                continue
            except OSError as e:
                c.say(f"Could not create {under_home(root)}: {e.strerror or e}. Try another folder.")
                continue
            c.say(f"Created {under_home(root)}: the record, its policy/ and inbox/ folders, no lines yet.")
            return DONE

    def step_timezone(self) -> str:
        c = self.console
        lb = self._record()
        current = str(lb.meta.get("timezone") or "UTC")
        c.why(
            "Every time in the record is stored in UTC; your zone is how the days are cut and shown"
            " (SPEC §3.2). A flight landing at 23:30 your time is on that day, not the next."
        )
        detected = self.detect_timezone()
        default = detected or current
        while True:
            answer = c.ask("Your timezone, as the zone database names it", default, hint=" (Europe/Oslo)")
            assert answer is not None  # there is always a default
            try:
                zoneinfo.ZoneInfo(answer)
            except (KeyError, ValueError, OSError):
                c.say(f"{answer!r} is not a zone this machine knows; Europe/Oslo, America/New_York and")
                c.say("Asia/Tokyo are: a continent, a slash, the nearest big city.")
                continue
            if answer != current:
                lb.set_timezone(answer)
                c.say(f"Timezone set to {answer} (was {current}).")
            else:
                c.say(f"Timezone: {answer}.")
            return DONE

    def step_owner(self) -> str:
        c = self.console
        lb = self._record()
        c.why(
            "The record meets you under many names: the address a friend writes to, the number a contact"
            " saved, a nickname. Listing them in policy/owner.json tells every reader which lines are you,"
            " so you are never your own company when it counts who you spent the day with."
        )
        try:
            existing = policy.owner_aliases(lb.root)
        except policy.PolicyError as e:
            c.say(f"{e}; fix the file and run `logbook setup --step owner`.")
            return SKIPPED
        questions = {
            "names": "Your names, as contacts and mail know you, separated by commas",
            "emails": "Your email addresses, separated by commas",
            "phones": "Your phone numbers, separated by commas",
        }
        added = 0
        for key, question in questions.items():
            if existing[key]:
                c.say(f"{key}: already listed: {', '.join(existing[key])}")
            answer = c.ask(question, None)
            if answer is None:
                continue
            for value in split_list(answer):
                if value not in existing[key]:
                    existing[key].append(value)
                    added += 1
        if added == 0 and not any(existing.values()):
            c.say("Nothing listed; `logbook doctor` reminds you; `logbook setup --step owner` asks again.")
            return SKIPPED
        path = policy.owner_path(lb.root)
        path.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        c.say(f"Wrote {under_home(path)}: {added} added. Edit it any time; it is yours, never in the chain.")
        if existing["emails"]:
            lb.set_owner_emails(existing["emails"])
            c.say("The emails are owner_emails in logbook.json too, so mail and chat imports know your side.")
        return DONE

    def step_home(self) -> str:
        c = self.console
        lb = self._record()
        c.why(
            "A night is at home when you slept within this circle; trips, nights away and the countries you"
            " were in are counted from it. Coordinates only, never an address: the record keeps what you"
            " paste, so paste the two numbers a maps app shows when you press on your front door."
        )
        try:
            known = places.read(lb.root)
        except places.PlaceError as e:
            c.say(f"{e}; fix the file and run `logbook setup --step home`.")
            return SKIPPED
        homes = places.home_places(known)
        if homes:
            c.say("Home is already named: " + ", ".join(p.name for p in homes))
            return DONE
        while True:
            answer = c.ask("Your home, as latitude, longitude", None, hint=" (e.g. 59.9139, 10.7522)")
            if answer is None:
                c.say("Skipped; `logbook places name Home <lat>,<lon> --kind home` does it later.")
                return SKIPPED
            point = parse_coordinates(answer)
            if point is None:
                c.say(
                    f"{answer!r} is not coordinates. In Google or Apple Maps, press and hold on the spot and"
                    " copy the two numbers it shows, like 59.9139, 10.7522. Never type an address here."
                )
                continue
            break
        lat, lon = point
        name = c.ask("What to call it", "Home") or "Home"
        place = places.Place(name, lat, lon, HOME_RADIUS_M, places.HOME)
        try:
            places.add(lb.root, place)
        except places.PlaceError as e:
            c.say(str(e))
            return SKIPPED
        text = places.naming_text(lat, lon, name)
        line = lb.append(
            at=now_utc(), source="manual", kind="note", tier=2, payload={"schema": "note/v1", "text": text}
        )
        c.say(f"{text} (line #{line['seq']}); a circle of {HOME_RADIUS_M:g} m in places.json.")
        return DONE

    def step_sources(self) -> str:
        c = self.console
        lb = self._record()
        c.why(
            "The record grows from exports you already have. Each one found here is offered with a dry run"
            " first: the adapter reads it and counts, and nothing is written until you say so. An export is"
            " only ever read; your files stay where they are."
        )
        home = Path.home()
        try:
            disabled = policy.disabled(lb.root)
        except policy.PolicyError as e:
            c.say(f"{e}; every source is taken as enabled until the file is fixed.")
            disabled = {}
        found = 0
        found += self._offer_takeouts(lb, home, disabled)
        found += self._offer_backups(lb, home)
        found += self._offer_messages(lb, home, disabled)
        if found == 0:
            c.say("Found nothing to import yet. Where each kind would be:")
            downloads = under_home(home.joinpath(*DOWNLOADS))
            c.say(f"  Google Takeout: the Takeout folder (unzipped) in {downloads}")
            c.say("  iPhone backup: Finder → your iPhone → Back Up Now; it lands under")
            c.say(f"    {under_home(home.joinpath(*MOBILESYNC_UNDER_HOME[0]))}")
            c.say("    (Windows: %APPDATA%\\Apple Computer\\MobileSync\\Backup)")
            store = under_home(home.joinpath(*MESSAGES_STORE))
            c.say(f"  Messages on a Mac: {store} (`logbook sync imessage`)")
            c.say("Any export: `logbook add <file-or-folder>`; the adapters recognise it.")
        self._say_live_sources(disabled)
        return DONE

    def _offer_takeouts(self, lb: Logbook, home: Path, disabled: Mapping[str, str]) -> int:
        c = self.console
        takeouts, zips = find_takeouts(home, disabled)
        for archive in zips:
            c.say(f"Google Takeout archive {under_home(archive)}: unzip it first (double-click it), then run")
            c.say("`logbook setup --step sources` again.")
        for takeout in takeouts:
            c.say(f"Google Takeout at {under_home(takeout.folder)}:")
            for job in takeout.jobs:
                c.say(f"  {job.adapter.NAME}: {under_home(job.path)}")
            for name, reason in takeout.disabled.items():
                c.say(f"  {name}: switched off in policy/import.json ({reason})")
            if takeout.unread:
                c.say("  not read by any adapter yet: " + ", ".join(takeout.unread))
            if not takeout.jobs:
                continue
            if not c.confirm(f"Dry run these {len(takeout.jobs)} import(s)? Nothing is written"):
                c.say("Skipped; `logbook add <folder>` does it later.")
                continue
            for job in takeout.jobs:
                self.importer(lb, job.adapter, job.path, True)
            if not c.confirm("Write these lines to the record?"):
                c.say("Nothing written.")
                continue
            for job in takeout.jobs:
                self.importer(lb, job.adapter, job.path, False)
        return len(takeouts) + len(zips)

    def _offer_backups(self, lb: Logbook, home: Path) -> int:
        c = self.console
        backups = find_backups(home, self.env)
        for backup in backups:
            c.say(f"iPhone backup {backup.udid} at {under_home(backup.folder)}:")
            if backup.encrypted:
                c.say(
                    f"  encrypted: it holds more (Health, calls, Safari) and needs its password in"
                    f" {PASSWORD_ENV}, which setup never asks for. In a terminal, type"
                )
                c.say(f"    read -s {PASSWORD_ENV} && export {PASSWORD_ENV}")
                c.say("  (typed once, never shown), then `logbook import-backup <folder> --only <sources>`.")
                continue
            if not backup.sources:
                c.say("  none of the stores the adapters know is in it.")
                continue
            c.say(f"  stores found: {', '.join(backup.sources)}")
            command = f"logbook import-backup {under_home(backup.folder)} --only {','.join(backup.sources)}"
            c.say(f"  the command: {command}")
            if not c.confirm("Dry run it? Nothing is written"):
                c.say("Skipped; the command above does it later.")
                continue
            self.import_backup(backup.folder, backup.sources, True)
            if not c.confirm("Copy these stores into inbox/ and import them?"):
                c.say("Nothing written.")
                continue
            self.import_backup(backup.folder, backup.sources, False)
        return len(backups)

    def _offer_messages(self, lb: Logbook, home: Path, disabled: Mapping[str, str]) -> int:
        c = self.console
        store = messages_store(home)
        if store is None:
            return 0
        c.say(f"Messages on this Mac: {under_home(store)}")
        if imessage_live.NAME in disabled:
            c.say(f"  switched off in policy/import.json ({disabled[imessage_live.NAME]})")
            return 1
        c.say(
            "  `logbook sync imessage` reads it, new messages each run; the terminal app needs Full Disk"
            " Access (System Settings → Privacy & Security) or macOS refuses the read."
        )
        if not c.confirm("Dry run it? Nothing is written"):
            c.say("Skipped; `logbook sync imessage` does it later.")
            return 1
        self.sync(imessage_live.NAME, True)
        if not c.confirm("Write these messages to the record?"):
            c.say("Nothing written.")
            return 1
        self.sync(imessage_live.NAME, False)
        return 1

    def _say_live_sources(self, disabled: Mapping[str, str]) -> None:
        """Each live source by the names of its variables, set or not, and where the key comes from.
        Names only: no value is ever printed, and none is asked for."""
        c = self.console
        rows: list[str] = []
        for adapter in adapters.live_adapters():
            if adapter.NAME in disabled or adapter.NAME not in KEY_SOURCES:
                continue
            try:
                configured = adapter.configure(self.env) is not None
            except ValueError:
                configured = False
            given = [v for v in adapter.ENV if self.env.get(v, "").strip()]
            missing = [v for v in adapter.ENV if v not in given]
            where = KEY_SOURCES[adapter.NAME]
            if configured and given:
                rows.append(f"  {adapter.NAME}: configured ({', '.join(given)})")
            elif configured:  # every variable optional and none set: it runs as it is
                optional = " and ".join(missing)
                rows.append(f"  {adapter.NAME}: works without a key; optional {optional} — {where}")
            else:
                rows.append(f"  {adapter.NAME}: set {' and '.join(missing)} — {where}")
        if not rows:
            return
        c.say("Live sources pull on their own with `logbook sync <name>`; each needs a variable set:")
        for row in rows:
            c.say(row)
        c.say("A key goes in the variable in your shell profile, never in a file of the record, never here.")

    def step_doctor(self) -> str:
        c = self.console
        lb = self._record()
        c.why("`logbook doctor` is the check-up: one line per check, pass, warn or fail. Run it any time.")
        doctor.report(doctor.run(lb, self.env), sys.stdout)
        return DONE


def run(args: argparse.Namespace, env: Mapping[str, str], **tools: Any) -> int:
    """`logbook setup [--yes] [--step NAME] [--again]`; the exit status."""
    step = getattr(args, "step", None)
    if step is not None and step not in STEPS:
        print(f"setup: no step named {step!r} (the steps: {', '.join(STEPS)})", file=sys.stderr)
        return 2
    wizard = Wizard(Console(yes=bool(getattr(args, "yes", False))), env, **tools)
    return wizard.run(only=step, again=bool(getattr(args, "again", False)))
