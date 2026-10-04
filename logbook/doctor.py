"""`logbook doctor`: is this machine set up to keep the record? One line per check — `pass`, `warn` or
`fail` — and exit 1 when anything fails. It reads; it never writes, not even the empty settings
file a reader would create, so running it changes nothing.

The checks, in the order they print:

- `record`: a record is found (`LOGBOOK_HOME`, the working folder, `~/Logbook`) and `verify` is
  green: every hash recomputes and `logbook.json` names the last line. Not found, not intact or
  hashed by another rule is a fail.
- `index`: `index.sqlite` was built at the record's head (a stale or missing index is a warn: the
  next reader rebuilds it, `logbook index` shows progress).
- `owner`: `policy/owner.json` is there and names at least one alias, so the owner is never listed
  as their own company (`present.owner_of`). Missing or empty is a warn, not JSON is a fail.
- `places`: `places.json` names at least one place of kind `home`, which the night rule needs
  (`trips`, `rollup nights`). None is a warn, not a places file is a fail.
- `assets`: `assets.json` is a registry when it exists (ADR 0018). Absent is fine.
- `extra:<name>`: each optional extra (`ais`, `crypto`, `sealed`, `transcribe`) is installed, with its
  install line when not (a warn).
- `sync:<name>`: for each live source the record uses — a `state/<name>.json` watermark, or lines of
  that source when the index is current — the variables its adapter reads are set. Names only,
  never a value: a missing one is a warn naming it, a set one the adapter refuses says to run
  `logbook sync <name>`. A source `policy/import.json` disables needs nothing.
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
from pathlib import Path
from typing import Literal, TextIO

from . import adapters, assets, index, places, policy
from .store import FormatError, Logbook

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
    """`verify` on the files (never the index): the chain recomputes and `logbook.json` is fresh."""
    warnings: list[str] = []
    try:
        seq, head, errors = lb.verify(warnings)
    except FormatError as e:
        return Check("record", "fail", f"{lb.root}: {e}")
    except (OSError, ValueError) as e:  # logbook.json unreadable, or not the object SPEC §1 describes
        return Check("record", "fail", f"{lb.meta_path}: {e}")
    if errors:
        more = "" if len(errors) == 1 else f" and {len(errors) - 1} more"
        return Check("record", "fail", f"{lb.root}: {errors[0]}{more}; run `logbook verify`")
    detail = f"{seq:,} lines, head {head[:12]}…, verified; {lb.root}"
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


def syncs_used(lb: Logbook, sources: set[str]) -> list[adapters.LiveAdapter]:
    """The live adapters the record uses: a watermark under `state/`, or lines of that source;
    never one `policy/import.json` disables (`sync` would not run it, so it needs no variables)."""
    listed: dict[str, str] = {}
    if policy.import_path(lb.root).exists():  # `disabled` would write the empty file; doctor never writes
        with contextlib.suppress(policy.PolicyError):
            listed = policy.disabled(lb.root)
    disabled = {adapters.ALIASES.get(name, name) for name in listed}
    marks = {p.stem for p in (lb.root / "state").glob("*.json")}
    return [
        a
        for a in adapters.live_adapters()
        if (a.NAME in marks or a.NAME in sources) and a.NAME not in disabled
    ]


def env_checks(lb: Logbook, env: Mapping[str, str], sources: set[str]) -> Iterator[Check]:
    """Names only, never a value: a missing variable is named; one the adapter refuses is not echoed."""
    for adapter in syncs_used(lb, sources):
        name = f"sync:{adapter.NAME}"
        try:
            config = adapter.configure(env)
        except ValueError:
            yield Check(
                name, "warn", f"a variable is set but refused; `logbook sync {adapter.NAME}` says why"
            )
            continue
        if config is None:
            missing = [v for v in adapter.ENV if not env.get(v, "").strip()]
            yield Check(name, "warn", "set " + " and ".join(missing))
        else:
            yield Check(name, "pass", "configured (" + ", ".join(adapter.ENV) + ")")


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
    checks.append(owner_check(lb.root))
    checks.append(places_check(lb.root))
    checks.append(assets_check(lb.root))
    checks.extend(extras_checks(installed))
    checks.extend(env_checks(lb, env, sources))
    checks.append(disk_check(lb.root, usage))
    checks.append(folder_check(lb.root, env))
    return checks


def report(checks: list[Check], out: TextIO = sys.stdout) -> int:
    """One line per check, a summary, and the exit status: 1 when any check failed."""
    width = max(len(c.name) for c in checks)
    for c in checks:
        out.write(f"{c.status:<4}  {c.name:<{width}}  {c.detail}\n")
    counts = {status: sum(c.status == status for c in checks) for status in ("pass", "warn", "fail")}
    out.write(f"{len(checks)} checks: {counts['pass']} pass, {counts['warn']} warn, {counts['fail']} fail\n")
    return 1 if counts["fail"] else 0
