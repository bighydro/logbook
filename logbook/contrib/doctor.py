"""`logbook doctor`: is this machine set up to keep the record? One line per check — `pass`, `warn` or
`fail` — and exit 1 when anything fails. It reads; it never writes, not even the empty settings
file a reader would create, so running it changes nothing.

The checks, in the order they print:

- `record`: a record is found (`LOGBOOK_HOME`, the working folder, `~/Logbook`) and `verify` is
  green: every hash recomputes, every timestamp is an instant and `logbook.json` names the last line.
  Not found, not intact or hashed by another rule is a fail. The attachments the lines name are looked
  for and the missing ones counted in the pass (SPEC §1.1 allows them); their bytes are `verify`'s.
- `index`: `index.sqlite` was built at the record's head (a stale or missing index is a warn: the
  next reader rebuilds it, `logbook index` shows progress).
- `day-start`: where the owner's day begins, when `logbook.json` sets `day_start` to anything but
  midnight (RFC 0036), as a pass; a warn when `index.sqlite` was built under another boundary (its
  `day_local` puts lines on other days until the next reader rebuilds it); a fail when the value is
  not a clock, which every reader that groups by day refuses. A record whose day begins at midnight,
  with an index that agrees, has no such line.
- `owner`: `policy/owner.json` is there and names at least one alias, so the owner is never listed
  as their own company (`present.owner_of`). Missing or empty is a warn, not JSON is a fail.
- `places`: `places.json` names at least one place of kind `home`, which the night rule needs
  (`trips`, `rollup nights`). None is a warn, not a places file is a fail.
- `assets`: `assets.json` is a registry when it exists (ADR 0018). Absent is fine.
- `dates`: every line's timestamp lies in its source's plausible range (`plausible`: calendar
  entries 1970 to now plus 5 years, mail 1990 to now plus 1 day, the rest 1970 to now plus 1 day,
  each overridable per source in `policy/plausible.json`). Lines outside it are a warn that counts
  them per source with the earliest and the latest; they are never deleted or hidden, and
  `logbook doctor --implausible` lists their ids. Read from the index when it is current, else
  from the month files. A settings file that is not the shape is a fail naming it.
- `extra:<name>`: each optional extra (`ais`, `crypto`, `sealed`, `transcribe`) is installed, with its
  install line when not (a warn).
- `google`: when either variable of the one Google service-account key is set (`LOGBOOK_DRIVE_SA_KEY`,
  `LOGBOOK_DRIVE_USER`), whether the key file is there and is a service-account key, whether the user
  is an address, which of the sources on the key (gmail, gcal, drive, gtasks, meet, gaudit) are
  enabled, a disabled one named as such, and what `people review --from-google` reads on it (contacts,
  other contacts: names for the review, never lines). Read from this machine alone: Google is asked
  nothing, and neither the path nor the address is printed. Something missing or wrong is a warn.
- `sync:<name>`: for each live source the record uses — a `state/<name>.json` watermark, or lines of
  that source when the index is current — the variables its adapter reads are set. Names only,
  never a value: a missing one is a warn naming it, a set one the adapter refuses says to run
  `logbook sync <name>`, a configured one names the variables it reads. A source `policy/import.json`
  disables needs nothing. A source whose first scheduled run was bounded to two weeks and whose
  history no run has read since says so on its line (`first run bounded to 14 days; history not
  read`, with the day it starts and the `--since` that reads the rest), whatever the line's status,
  which it never changes.
- `crossing`: `policy/crossing.json` is the documented shape and every destination's ceiling is listed
  as it counts today (ADR 0016); an entry past its `until` day counts as tier 0 and is a warn naming
  it (ADR 0022). No file is the defaults; a file that is not the shape is a fail naming it.
- `drafts`: a warn naming the days whose standing draft (RFC 0036) is above what the `dream` entry
  allows today, lowered, expired or removed since the day was dreamed: every reader withholds it
  (derived material follows the policy, not the head), and `dream --catch-up` dreams the day again
  under the entry when it is in force. A record with no such day has no line. Read from the index
  when it is current, opened read-only, else from the month files; a sealed draft this machine has
  no identity to open is counted, not named.
- `synthesis`: when the policy has a `dream` entry, how many calls (`transcript/v1` lines) have no
  synthesis: those of the last 7 days and today, which the 06:00 close synthesizes; those before,
  which it leaves, with the `dream --catch-up --since DAY` that reaches the oldest; and those above
  the entry's ceiling, which stay home. A pass; a record whose every call has a synthesis has no line.
  Read as the `drafts` line reads.
- `home`: `state/home.json`, written by `sync --install-schedule` on the record's home (ADR 0022),
  names this machine, or no home is set (a pass either way); another machine is a warn: writers
  belong on the home.
- `last-run`: when the schedule (`sync --install-schedule`) last ran `sync --scheduled`, from
  `state/last-run.json` whichever install wrote it (the user's agents or timers, the system's with
  `--system`, or none on this machine), and whether it was clean: a run older than 26 hours, or one in
  which a source failed or a check failed, is a warn. No file: a pass when no schedule is installed
  here, a warn when one is and has not run yet. Both the user's and the system's installed is a warn
  whatever the run said: each runs every source at the same times.
- `restore-test`: the last `backup --restore-test` (`state/last-restore-test.json`) passed within 35
  days (the schedule runs it on the first Sunday of the month); none, older, or skipped is a warn saying
  what to do; failed is a fail with the reason.
- `serve`: whether this machine keeps the pages served (`serve --install-service`, docs/serve.md): no
  service is a pass saying how to install one; one installed (the user's agent or unit, or the
  system's daemon or unit) passes when a logbook server answers on its port, and is a warn naming
  where its output goes when nothing does; two on one port are a warn. The one request is a HEAD to
  127.0.0.1, made only when a service is installed.
- `disk`: free space on the volume the record is on (under 5 GiB a warn, under 512 MiB a fail).
- `folder`: the record is not under a folder a sync client owns — iCloud Drive, Dropbox, OneDrive,
  Google Drive — by any part of its path, its resolved path, or the `OneDrive` variable Windows
  sets. Such a client evicts files to the cloud and fetches them back on demand, rewrites them
  underneath the writer and puts the record on someone else's server; that is a fail with the
  reason (README, "Where to keep the record")."""

from __future__ import annotations

import contextlib
import importlib.util
import shutil
import sqlite3
import sys
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, TextIO
from zoneinfo import ZoneInfo

from ..core import assets, attachments, day_start, drafts, index, places, plausible, policy, sealing
from ..core.chain import Line, is_sealed
from ..core.store import RETRACTION, FormatError, Logbook, read_line_at, retractions
from . import adapters, first_run, home, last_run, schedule, serve, synthesis
from . import service as serve_service
from .adapters import service_account

Status = Literal["pass", "warn", "fail"]
Usage = Callable[[Path], tuple[int, int, int]]  # (total, used, free) in bytes, as shutil.disk_usage

GIB = 1024**3
DISK_WARN_BYTES = 5 * GIB
DISK_FAIL_BYTES = GIB // 2
PIP = 'pip install "openlogbook[{extra}]"'
#: each extra with the modules that satisfy it, any one of them; `transcribe` has an engine per platform
EXTRAS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ais", ("websockets",)),
    ("crypto", ("cryptography",)),
    ("sealed", ("pyrage",)),
    ("transcribe", ("mlx_whisper", "faster_whisper")),
)
#: a path part that begins with one of these, case-folded, names the service: `Dropbox (Personal)`,
#: `OneDrive - Example Org`, `~/Library/Mobile Documents/com~apple~CloudDocs`
CLOUD_FOLDERS: tuple[tuple[str, str], ...] = (
    ("icloud drive", "iCloud Drive"),
    ("mobile documents", "iCloud Drive"),
    ("com~apple~clouddocs", "iCloud Drive"),
    ("dropbox", "Dropbox"),
    ("onedrive", "OneDrive"),
    ("google drive", "Google Drive"),
    ("googledrive", "Google Drive"),
)
CLOUD_REASON = (
    "a sync client evicts files to the cloud and fetches them back on demand, rewrites month files"
    " and logbook.json underneath the writer, and keeps the record on someone else's server;"
    " move it to a plain local folder and point LOGBOOK_HOME at it"
)
ONEDRIVE_ENV = "OneDrive"  # Windows sets it to the folder OneDrive syncs


@dataclass(frozen=True)
class Check:
    name: str
    status: Status
    detail: str


# -- the checks ------------------------------------------------------------------------------------------


def record_check(lb: Logbook) -> Check:
    """`verify` on the files (never the index): the chain recomputes and `logbook.json` is fresh. The
    files the lines name are looked for, and the missing ones counted in the pass, as `verify` lists
    them without failing (SPEC §1.1); their bytes are `verify`'s to hash, not a check that runs four
    times a day."""
    warnings: list[str] = []
    walk = attachments.Walk(hash_plain=False, open_sealed=False)
    try:
        seq, head, errors = lb.verify(warnings, walk=walk)
    except FormatError as e:
        return Check("record", "fail", f"{lb.root}: {e}")
    except (OSError, ValueError) as e:  # logbook.json unreadable, or not the object SPEC §1 describes
        return Check("record", "fail", f"{lb.meta_path}: {e}")
    if errors:
        more = "" if len(errors) == 1 else f" and {len(errors) - 1} more"
        return Check(
            "record",
            "fail",
            f"{lb.root}: {errors[0]}{more}; run `logbook verify`, and `logbook repair fork` when it"
            " reports two chains",
        )
    missing = len(walk.missing)
    if missing:
        noted = f"; {missing:,} attachment{'s' if missing != 1 else ''} missing (SPEC §1.1 allows it;"
        noted += " `logbook attach status`)"
    else:
        noted = ""
    detail = f"{seq:,} lines, head {head[:12]}…, verified{noted}; {lb.root}"
    if warnings:
        n = len(warnings)
        return Check(
            "record", "warn", f"{detail}; {n} timestamp(s) the next release will reject (logbook verify)"
        )
    return Check("record", "pass", detail)


def index_state(lb: Logbook) -> tuple[str, set[str]]:
    """(`current`, `stale` or `missing`, the sources the index holds when current), read-only: the
    file is opened for reading only, so an index another command is building is never discarded."""
    path = lb.index_path
    if not path.exists():
        return "missing", set()
    try:
        db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except (sqlite3.DatabaseError, OSError):
        return "stale", set()
    try:
        stored = dict(db.execute("SELECT key, value FROM meta"))
        stored.pop(index.INDEX_KEY, None)
        stored.pop("opened", None)
        if stored != index.Index._meta_of(lb.meta):
            return "stale", set()
        return "current", {source for (source,) in db.execute("SELECT DISTINCT source FROM lines")}
    except sqlite3.DatabaseError:  # no meta table, or nothing SQLite can read
        return "stale", set()
    finally:
        db.close()  # before anything could unlink it: Windows refuses to delete an open file


def index_day_start(lb: Logbook) -> str | None:
    """The `day_start` `index.sqlite` was built under (`00:00` when its meta names none), read-only;
    None when there is no index or nothing SQLite can read."""
    path = lb.index_path
    if not path.exists():
        return None
    try:
        db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except (sqlite3.DatabaseError, OSError):
        return None
    try:
        found = db.execute("SELECT value FROM meta WHERE key = ?", (day_start.KEY,)).fetchone()
        return day_start.MIDNIGHT if found is None else str(found[0])
    except sqlite3.DatabaseError:  # no meta table, or nothing SQLite can read
        return None
    finally:
        db.close()  # before anything could unlink it: Windows refuses to delete an open file


def day_start_check(lb: Logbook) -> Check | None:
    """`day_start` (RFC 0036): None for a day that begins at midnight with an index that agrees."""
    value = lb.meta.get(day_start.KEY)
    try:
        found = day_start.of(lb.meta)
    except day_start.DayStartError:
        return Check(
            "day-start",
            "fail",
            f"logbook.json day_start {value!r} is not a clock from 00:00 to 23:59 written HH:MM; every reader"
            " that groups by day refuses it: `logbook setup day_start 06:00`, or remove the key for midnight",
        )
    built = index_day_start(lb)
    if built is not None and built != found.text:
        return Check(
            "day-start",
            "warn",
            f"the day begins at {found.text} (logbook.json day_start) but index.sqlite was built with"
            f" {built}, so its days are not yours yet: the next reader rebuilds it, or"
            " `logbook repair index`",
        )
    if found.midnight:
        return None
    return Check(
        "day-start",
        "pass",
        f"the day begins at {found.text}: a line before {found.text} belongs to the day before"
        " (logbook.json day_start)",
    )


def index_check(state: str) -> Check:
    if state == "current":
        return Check("index", "pass", "index.sqlite is current with logbook.json")
    if state == "missing":
        return Check("index", "warn", "no index.sqlite; the next reader builds it, or run `logbook index`")
    return Check(
        "index",
        "warn",
        "index.sqlite is behind logbook.json; the next reader rebuilds it, or run `logbook index`",
    )


def owner_check(root: Path) -> Check:
    path = policy.owner_path(root)
    name = policy.OWNER_FILE.as_posix()
    hint = "add your other names, emails and phones so you are never your own company"
    if not path.exists():
        return Check("owner", "warn", f"{name} is missing; the next reader writes the empty one: {hint}")
    try:
        aliases = policy.owner_aliases(root)  # the file exists, so nothing is written
    except policy.PolicyError as e:
        return Check("owner", "fail", str(e))
    counts = {key: len(values) for key, values in aliases.items() if values}
    if not counts:
        return Check("owner", "warn", f"{name} is empty: {hint}")
    listed = ", ".join(f"{n} {key}" for key, n in counts.items())
    return Check("owner", "pass", f"{name} names {listed}")


def places_check(root: Path) -> Check:
    path = places.path_of(root)
    hint = "`logbook places add Home --lat LAT --lon LON --kind home` so nights at home are known"
    try:
        known = places.read(root)
    except places.PlaceError as e:
        return Check("places", "fail", str(e))
    homes = places.home_places(known)
    if not known:
        return Check("places", "warn", f"no {path.name}: {hint}")
    if not homes:
        return Check("places", "warn", f"{path.name} names {len(known)} place(s) but no home: {hint}")
    names = ", ".join(p.name for p in homes)
    return Check("places", "pass", f"{len(known)} place(s), home: {names}")


def assets_check(root: Path) -> Check:
    try:
        registry = assets.read(root)
    except assets.AssetError as e:
        return Check("assets", "fail", str(e))
    if not registry:
        return Check("assets", "pass", f"no {assets.ASSETS_FILE}; nothing is tracked as a subject")
    return Check("assets", "pass", f"{len(registry)} asset(s): " + ", ".join(a.id for a in registry))


def implausible(lb: Logbook, state: str, now: datetime) -> list[plausible.Found]:
    """The lines whose timestamp is outside their source's plausible range, in chain order: from the
    index when it is `current` (opened read-only), else from the month files. `PlausibleError` for a
    `policy/plausible.json` that is not the shape."""
    given = plausible.overrides(lb.root)
    rows = (
        plausible.rows_from_index(lb.index_path)
        if state == "current"
        else plausible.rows_from_lines(lb.lines_unsorted())
    )
    return list(plausible.find(rows, now, given))


def dates_check(lb: Logbook, state: str, now: datetime) -> Check:
    name = plausible.PLAUSIBLE_FILE.as_posix()
    try:
        found = implausible(lb, state, now)
    except plausible.PlausibleError as e:
        return Check("dates", "fail", str(e))
    if not found:
        return Check("dates", "pass", f"every line is dated inside its source's plausible range ({name})")
    per = "; ".join(
        f"{c.source} {c.lines} ({c.earliest[:10]} to {c.latest[:10]})" for c in plausible.counts(found)
    )
    return Check(
        "dates",
        "warn",
        f"{len(found)} line(s) dated outside their source's plausible range: {per};"
        f" kept as written, `logbook doctor --implausible` lists them, {name} widens a range",
    )


def module_installed(module: str) -> bool:
    """Whether `module` could be imported, without importing it (an engine loads a model on import)."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):  # a missing parent package, or a name find_spec refuses
        return False


def extras_checks(installed: Callable[[str], bool] = module_installed) -> Iterator[Check]:
    for extra, modules in EXTRAS:
        found = [m for m in modules if installed(m)]
        if found:
            yield Check(f"extra:{extra}", "pass", f"{found[0].replace('_', '-')} is installed")
        else:
            wanted = " or ".join(m.replace("_", "-") for m in modules)
            yield Check(f"extra:{extra}", "warn", f"{wanted} not installed: {PIP.format(extra=extra)}")


def disabled_sources(lb: Logbook) -> set[str]:
    """The sources `policy/import.json` switches off, aliases resolved; none when there is no file
    (`policy.disabled` would write the empty one, and doctor never writes) or it is not the shape."""
    listed: dict[str, str] = {}
    if policy.import_path(lb.root).exists():
        with contextlib.suppress(policy.PolicyError):
            listed = policy.disabled(lb.root)
    return {adapters.ALIASES.get(name, name) for name in listed}


def syncs_used(
    lb: Logbook, sources: set[str], env: Mapping[str, str] | None = None
) -> list[adapters.LiveAdapter]:
    """The live adapters the record uses: a watermark under `state/`, lines of that source, or one
    of its variables set in `env`; never one `policy/import.json` disables (`sync` would not run
    it, so it needs no variables)."""
    disabled = disabled_sources(lb)
    marks = {p.stem for p in (lb.root / "state").glob("*.json")}
    given = env if env is not None else {}
    return [
        a
        for a in adapters.live_adapters()
        if (a.NAME in marks or a.NAME in sources or any(given.get(v, "").strip() for v in a.ENV))
        and a.NAME not in disabled
    ]


def google_check(lb: Logbook, env: Mapping[str, str]) -> Check | None:
    """The one Google key, when either of its variables is set: the key file there and a service-account
    key, the user an address, the sources on the key that are enabled, and what `people review
    --from-google` reads on it. Nothing is sent anywhere and no value is printed; None when neither
    variable is set."""
    raw_key = env.get(service_account.KEY_ENV, "").strip()
    user = env.get(service_account.USER_ENV, "").strip()
    if not raw_key and not user:
        return None
    said: list[str] = []
    if not raw_key:
        said.append(f"{service_account.KEY_ENV} not set")
    else:
        try:
            service_account.read_key(Path(raw_key).expanduser())
        except ValueError as e:
            said.append(str(e))
        else:
            said.append("key present")
    if not user:
        said.append(f"{service_account.USER_ENV} not set")
    elif not service_account.is_address(user):
        said.append(f"{service_account.USER_ENV} is not an address")
    else:
        said.append("user set")
    status: Status = "pass" if said[0] == "key present" and said[1] == "user set" else "warn"
    disabled = disabled_sources(lb)
    on = [name for name in service_account.SOURCES if name not in disabled] or ["none"]
    off = [name for name in service_account.SOURCES if name in disabled]
    sources = ", ".join(on) + (f" ({', '.join(off)} disabled)" if off else "")
    names = ", ".join(service_account.NAMES)
    return Check(
        "google",
        status,
        f"{', '.join(said)}; sources on the key: {sources}; people review --from-google: {names}",
    )


def env_checks(lb: Logbook, env: Mapping[str, str], sources: set[str]) -> Iterator[Check]:
    """Names only, never a value: a missing variable is named; one the adapter refuses is not echoed.
    An adapter with `check` (`beeper`: `GET /v1/info`) is asked, once, whether its app answers; the
    sources on the Google key read it here and ask Google nothing. A source whose first scheduled run
    was bounded to two weeks, and whose history no run has read since, is named as such on its line
    (`first_run.text`), whatever the line's status, which it never changes: the schedule chose not to
    read the history, nothing is broken, and a warn would send the alert at every run."""
    for adapter in syncs_used(lb, sources, env):
        check = _env_check(adapter, env)
        bounded = first_run.read(lb.root, adapter.NAME)
        if bounded is not None:
            said = first_run.text(bounded, adapter.NAME)
            check = Check(check.name, check.status, f"{check.detail}; {said}")
        yield check


def _env_check(adapter: adapters.LiveAdapter, env: Mapping[str, str]) -> Check:
    """One source's `sync:<name>` line, from its variables."""
    name = f"sync:{adapter.NAME}"
    try:
        config = adapter.configure(env)
    except ValueError:
        return Check(name, "warn", f"a variable is set but refused; `logbook sync {adapter.NAME}` says why")
    if config is None:
        return Check(name, "warn", "set " + adapters.needs(adapter, env))
    given = [v for v in adapter.ENV if env.get(v, "").strip()]  # the ones it reads; all when none is set
    detail = "configured (" + ", ".join(given or adapter.ENV) + ")"
    ask = getattr(adapter, "check", None)
    if ask is None:
        return Check(name, "pass", detail)
    try:
        return Check(name, "pass", f"{detail}; {ask(config)}")
    except (OSError, ValueError) as e:
        return Check(name, "warn", f"{detail}; {e}")


def disk_check(root: Path, usage: Usage = shutil.disk_usage) -> Check:
    try:
        _total, _used, free = usage(root)
    except OSError as e:
        return Check("disk", "warn", f"could not read the free space under {root}: {e}")
    detail = f"{free / GIB:,.1f} GiB free on the record's volume"
    if free < DISK_FAIL_BYTES:
        return Check("disk", "fail", f"{detail}; the next append may not fit")
    if free < DISK_WARN_BYTES:
        return Check("disk", "warn", f"{detail}; make room before the next import")
    return Check("disk", "pass", detail)


def crossing_check(root: Path) -> Check:
    name = policy.POLICY_FILE.as_posix()
    try:
        found = policy.ceilings(root)
    except policy.PolicyError as e:
        return Check("crossing", "fail", str(e))
    listed = ", ".join(_ceiling_text(c) for c in found)
    if not policy.policy_path(root).exists():
        detail = f"no {name}; the defaults apply until the first export writes it: {listed}"
        return Check("crossing", "pass", detail)
    expired = [c for c in found if c.expired and c.until is not None]
    if expired:
        named = ", ".join(f"{c.destination} expired on {c.until.isoformat()}" for c in expired if c.until)
        return Check(
            "crossing",
            "warn",
            f"{listed}; {named} and counts as tier 0: write a new until in {name} or remove the entry",
        )
    return Check("crossing", "pass", listed)


def draft_lines(lb: Logbook, state: str) -> list[Line]:
    """The record's draft and retraction lines (`kind_lines`)."""
    return kind_lines(lb, state, (drafts.KIND, RETRACTION))


def kind_lines(lb: Logbook, state: str, kinds: tuple[str, ...]) -> list[Line]:
    """The record's lines of these kinds, opened where this machine has the identity: from the index
    when it is `current` (opened read-only, the lines read at the places it names), else from the
    month files."""
    if state == "current":
        db = sqlite3.connect(f"{lb.index_path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            places = db.execute(
                f"SELECT file, offset FROM lines WHERE kind IN ({', '.join('?' * len(kinds))}) ORDER BY seq",
                kinds,
            ).fetchall()
        finally:
            db.close()  # before anything could unlink it: Windows refuses to delete an open file
        found = []
        for file, offset in places:
            with (lb.root / str(file)).open("rb") as fh:
                found.append(read_line_at(fh, int(offset)))
    else:
        found = [line for line in lb.lines_unsorted() if line.get("kind") in kinds]
    return [_opened(lb, line) for line in found]


def _opened(lb: Logbook, line: Line) -> Line:
    try:
        return lb.opened(line)
    except (sealing.SealError, sealing.MissingExtra, OSError, ValueError):
        return line  # a line that will not open is `record`'s to report; here it stays sealed


def drafts_check(lb: Logbook, state: str) -> Check | None:
    """None unless a day's standing draft is above what the `dream` entry allows today."""
    allowed = drafts.allowed(lb.root)
    if allowed.max_tier >= policy.TIERS[-1]:
        return None  # no draft is above tier 3
    lines = draft_lines(lb, state)
    retracted = retractions(line for line in lines if line.get("kind") == RETRACTION)
    above = drafts.withheld(lines, retracted, allowed)
    sealed = sum(
        1
        for line in lines
        if line.get("kind") == drafts.KIND and is_sealed(line) and not allowed.allows(line)
    )
    if not above and not sealed:
        return None
    named = ", ".join(
        f"{(line.get('payload') or {}).get('subject')} (#{line['seq']}, tier {line['tier']})"
        for line in above
    )
    why = (
        allowed.reason
        if allowed.reason is not None
        else f"the {policy.DREAM_DESTINATION!r} entry allows max_tier {allowed.max_tier} now;"
        " `logbook dream --catch-up` dreams them again under it"
    )
    found = f"{len(above)} day(s) with a draft above what the dream entry allows, which no reader shows"
    if named:
        found += f": {named}"
    if sealed:
        found += f"; {sealed} sealed draft(s) above it that this machine has no identity to open"
    return Check("drafts", "warn", f"{found}; {why}")


def synthesis_check(lb: Logbook, state: str, now: datetime) -> Check | None:
    """The calls with no synthesis (`synthesis.waiting`): in the window the 06:00 close synthesizes,
    before it, and above the `dream` entry's ceiling. None when the policy names no `dream` entry
    (nothing is ever synthesized), when the policy or `day_start` is not readable (`crossing` and
    `day-start` say so), or when every call has a synthesis. A pass: the close leaves the older calls
    by design, and the line says how to reach them."""
    try:
        entry = policy.dream_today(lb.root)
        bounds = day_start.of(lb.meta)
    except (policy.PolicyError, day_start.DayStartError):
        return None
    if entry is None:
        return None
    first, _last = synthesis.window(now.astimezone(bounds.zone).date())
    lines = kind_lines(lb, state, (synthesis.KIND, drafts.KIND, RETRACTION))
    found = synthesis.waiting(lines, bounds.day_of, first, entry.max_tier)
    if not found.total:
        return None
    return Check("synthesis", "pass", synthesis.waiting_text(found))


def _ceiling_text(c: policy.Ceiling) -> str:
    """`hermes 2`, `cloud-model 2 until 2026-12-31`, `mcp 2 write sign_day,note_day`,
    `dream 2 until 2026-12-31 model qwen2.5-7b-instruct`: the ceiling as it counts today, the write
    tools it lets through the door by name (ADR 0022) and the model the entry names (RFC 0036)."""
    when = f" until {c.until.isoformat()}" if c.until is not None and not c.expired else ""
    write = f" write {','.join(c.writes)}" if c.writes else ""
    model = f" model {c.model}" if c.model else ""
    return f"{c.destination} {c.max_tier}{when}{write}{model}"


NO_HOME = (
    "no home set; `logbook sync --install-schedule` on the machine that keeps the record names it (ADR 0022)"
)
NOT_HOME = "this machine is not the record's home ({host}); writers belong on the home"


def home_check(root: Path) -> Check:
    try:
        found = home.read(root)
    except home.HomeError as e:
        return Check("home", "fail", str(e))
    if found is None:
        return Check("home", "pass", NO_HOME)
    if home.same_machine(found.host, home.hostname()):
        return Check("home", "pass", f"this machine ({found.host}) is the record's home since {found.since}")
    return Check("home", "warn", NOT_HOME.format(host=found.host))


RESTORE_TEST_WITHIN = timedelta(days=35)  # the first Sundays of two months are at most five weeks apart
INSTALL = "`logbook sync --install-schedule` runs `sync --all` and `doctor` four times a day and writes it"
RESTORE_TEST = (
    "`logbook backup --restore-test` restores the latest snapshot into a temporary folder and verifies it;"
    " the schedule runs it on the first Sunday of the month"
)


def schedules_installed(env: Mapping[str, str]) -> list[str]:
    """Which installs of the schedule this machine has, in this order: `user`, the agents or timers
    `sync --install-schedule` writes, and `system`, the system's copies of `--system`'s (whichever
    account they run as)."""
    xdg = env.get("XDG_CONFIG_HOME", "").strip()
    config, root = (Path(xdg).expanduser() if xdg else None), serve_service.SYSTEM_ROOT
    try:
        plans = [  # the user's agents or timers, then the system's copies (whichever account they run as)
            schedule.plan(
                schedule.system(), Path.home(), sys.executable, None, config, user=user, system_root=root
            )
            for user in (None, "-")
        ]
    except schedule.ScheduleError:
        return []
    return [which for which, plan in zip(("user", "system"), plans, strict=True) if schedule.installed(plan)]


def schedule_installed(env: Mapping[str, str]) -> bool:
    """Whether this machine has the agents or timers `sync --install-schedule` writes, the user's or,
    with `--system`, the system's copies."""
    return bool(schedules_installed(env))


def _twice(system: str) -> str:
    """The warning for a machine with both installs: each runs every source at the same four times."""
    user, system_wide = (
        ("launchd agents", "launchd daemons")
        if system == "darwin"
        else ("systemd user timers", "systemd system timers")
    )
    return (
        f"the schedule is installed twice, as {user} and as {system_wide}: every run happens twice; keep one"
        " (`logbook sync --uninstall-schedule` removes the user's, `--uninstall-schedule --system` says how"
        " to remove the system's)"
    )


def last_run_check(lb: Logbook, env: Mapping[str, str]) -> Check:
    """`state/last-run.json`: the last scheduled run, when, and whether it was clean, whichever install
    of the schedule wrote it; a warn besides when both the user's and the system's are installed."""
    try:
        state = last_run.read(lb.root)
    except last_run.LastRunError as e:
        return Check("last-run", "warn", str(e))
    installs = schedules_installed(env)
    twice = f"; {_twice(schedule.system())}" if len(installs) > 1 else ""
    if state is None:
        if installs:
            return Check(
                "last-run",
                "warn",
                "the schedule is installed but has not run yet; wait for 00:00, 06:00, 12:00 or 18:00"
                + twice,
            )
        return Check("last-run", "pass", f"no schedule on this machine; {INSTALL}")
    run = state.run
    now = last_run.now()
    zone = ZoneInfo(str(lb.meta["timezone"]))
    age = now - run.at
    when = f"{run.at.astimezone(zone):%Y-%m-%d %H:%M} ({last_run.age_text(age)})"
    detail = f"{when}: {last_run.sources_text(run)}; {last_run.doctor_text(run.doctor)}"
    if age > last_run.STALE_AFTER:
        hours = round(last_run.STALE_AFTER.total_seconds() / 3600)
        return Check(
            "last-run", "warn", f"{detail}; more than {hours} h ago: is the schedule still installed?{twice}"
        )
    if run.doctor is None and age > timedelta(hours=3):
        return Check("last-run", "warn", f"{detail}; the run did not finish{twice}")
    if run.failed:
        return Check("last-run", "warn", f"{detail}; first failing line: {run.first_failing}{twice}")
    return Check("last-run", "warn" if twice else "pass", detail + twice)


def restore_test_check(lb: Logbook) -> Check:
    """`state/last-restore-test.json`: the last restore test passed, within 35 days."""
    from . import backup  # here, not at the top: backup imports this module

    try:
        test = backup.read_restore_test(lb.root)
    except ValueError as e:
        return Check("restore-test", "warn", str(e))
    if test is None:
        return Check("restore-test", "warn", f"no restore test yet: {RESTORE_TEST}")
    when = f"{test.at:%Y-%m-%d}"
    name = test.snapshot.name if test.snapshot is not None else "no snapshot"
    if test.status == "failed":
        return Check("restore-test", "fail", f"failed {when} ({name}): {test.reason}")
    if test.status == "skipped":
        return Check("restore-test", "warn", f"skipped {when}: {test.reason}")
    age = last_run.now() - test.at
    if age > RESTORE_TEST_WITHIN:
        return Check(
            "restore-test",
            "warn",
            f"last passed {when} ({name}), {last_run.age_text(age)}, more than"
            f" {RESTORE_TEST_WITHIN.days} days; {RESTORE_TEST}",
        )
    return Check("restore-test", "pass", f"passed {when} ({name}, {test.seq or 0:,} lines)")


SERVE_INSTALL = (
    f"`logbook serve --install-service` keeps the pages at http://{serve.HOST}:{serve.PORT}/ from load"
    " (docs/serve.md)"
)


def serve_check(env: Mapping[str, str]) -> Check:
    """The serve services this machine has (`service.find`) and whether a logbook server answers on
    the port of each; nothing is asked when none is installed."""
    xdg = env.get("XDG_CONFIG_HOME", "").strip()
    home_dir = Path.home()
    found = serve_service.find(serve_service.system(), home_dir, Path(xdg).expanduser() if xdg else None)
    if not found:
        return Check("serve", "pass", f"no serve service on this machine; {SERVE_INSTALL}")
    status: Status = "pass"
    parts: list[str] = []
    for item in found:
        named = f"{item.kind} ({serve_service.shown(item.path, home_dir)})"
        address = f"http://{serve.HOST}:{item.port}/"
        if serve_service.answering(item.port):
            parts.append(f"{named} answering at {address}")
        else:
            status = "warn"
            parts.append(f"{named} installed, but nothing answers at {address}; its output: {item.log}")
    ports = [item.port for item in found]
    if len(set(ports)) < len(ports):
        status = "warn"
        parts.append("two services on one port: remove one (`logbook serve --uninstall-service [--system]`)")
    return Check("serve", status, "; ".join(parts))


def cloud_folder(root: Path, env: Mapping[str, str]) -> str | None:
    """The sync service whose folder holds `root`, by a part of its path (as given and resolved,
    so a symlink into the folder is seen) or the OneDrive variable; None for a plain folder."""
    candidates = [root]
    with contextlib.suppress(OSError):
        candidates.append(root.resolve())
    for path in candidates:
        for part in path.parts:
            service = _cloud_part(part)
            if service is not None:
                return service
    onedrive = env.get(ONEDRIVE_ENV, "").strip()
    if onedrive and any(_under(path, Path(onedrive)) for path in candidates):
        return "OneDrive"
    return None


def _cloud_part(part: str) -> str | None:
    key = part.casefold()
    for prefix, service in CLOUD_FOLDERS:
        if key == prefix or (key.startswith(prefix) and key[len(prefix)] in " -(_."):
            return service
    return None


def _under(path: Path, folder: Path) -> bool:
    try:
        folder = folder.resolve()
    except OSError:
        return False
    return path == folder or folder in path.parents


def folder_check(root: Path, env: Mapping[str, str]) -> Check:
    service = cloud_folder(root, env)
    if service is None:
        return Check("folder", "pass", "a plain local folder, no sync client")
    return Check("folder", "fail", f"{root} is under {service}: {CLOUD_REASON}")


# -- the command -----------------------------------------------------------------------------------------


def run(
    lb: Logbook | None,
    env: Mapping[str, str],
    *,
    installed: Callable[[str], bool] = module_installed,
    usage: Usage = shutil.disk_usage,
    now: datetime | None = None,
) -> list[Check]:
    """Every check in print order. Without a record only the record failure and the extras."""
    checks: list[Check] = []
    if lb is None:
        checks.append(Check("record", "fail", "no logbook found; run `logbook init`, or set LOGBOOK_HOME"))
        checks.extend(extras_checks(installed))
        return checks
    checks.append(record_check(lb))
    state, sources = index_state(lb)
    checks.append(index_check(state))
    boundary = day_start_check(lb)
    if boundary is not None:
        checks.append(boundary)
    checks.append(owner_check(lb.root))
    checks.append(places_check(lb.root))
    checks.append(assets_check(lb.root))
    checks.append(dates_check(lb, state, now or last_run.now()))
    checks.extend(extras_checks(installed))
    google = google_check(lb, env)
    if google is not None:
        checks.append(google)
    checks.extend(env_checks(lb, env, sources))
    checks.append(crossing_check(lb.root))
    withheld = drafts_check(lb, state)
    if withheld is not None:
        checks.append(withheld)
    calls = synthesis_check(lb, state, now or last_run.now())
    if calls is not None:
        checks.append(calls)
    checks.append(home_check(lb.root))
    checks.append(last_run_check(lb, env))
    checks.append(restore_test_check(lb))
    checks.append(serve_check(env))
    checks.append(disk_check(lb.root, usage))
    checks.append(folder_check(lb.root, env))
    return checks


def report_implausible(lb: Logbook, out: TextIO = sys.stdout, now: datetime | None = None) -> int:
    """`logbook doctor --implausible`: one row per line dated outside its source's plausible range,
    id, source, kind and timestamp, then the count; exit 1 only when the settings file is broken."""
    when = now or last_run.now()
    try:
        given = plausible.overrides(lb.root)
        found = implausible(lb, index_state(lb)[0], when)
    except plausible.PlausibleError as e:
        out.write(f"{e}\n")
        return 1
    for f in found:
        window = plausible.window(f.kind, f.source, given)
        out.write(f"{f.id}  {f.source}  {f.kind}  {f.at}  (plausible {window.text(when)})\n")
    out.write(f"{len(found)} line(s) outside their source's plausible range; none was changed\n")
    return 0


def report(checks: list[Check], out: TextIO = sys.stdout) -> int:
    """One line per check, a summary, and the exit status: 1 when any check failed."""
    width = max(len(c.name) for c in checks)
    for c in checks:
        out.write(f"{c.status:<4}  {c.name:<{width}}  {c.detail}\n")
    counts = {status: sum(c.status == status for c in checks) for status in ("pass", "warn", "fail")}
    out.write(f"{len(checks)} checks: {counts['pass']} pass, {counts['warn']} warn, {counts['fail']} fail\n")
    return 1 if counts["fail"] else 0
