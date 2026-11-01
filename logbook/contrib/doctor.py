"""`logbook doctor`: is this machine set up to keep the record? One line per check — `pass`, `warn` or
`fail` — and exit 1 when anything fails. It reads; it never writes, not even the empty settings
file a reader would create, so running it changes nothing.

The checks, in the order they print:

- `record`: a record is found (`LOGBOOK_HOME`, the working folder, `~/Logbook`) and `verify` is
  green: every hash recomputes, every timestamp is an instant and `logbook.json` names the last line.
  Not found, not intact or hashed by another rule is a fail. The attachments the lines name are looked
  for and the missing ones counted in the pass (SPEC §1.1 allows them); their bytes are `verify`'s.
- `index`: `index.sqlite` was built at the record's head (a stale or missing index is a warn: the
  next reader rebuilds it, `logbook repair index` shows progress).
- `day-start`: where the owner's day begins, when `logbook.json` sets `day_start` to anything but
  midnight (RFC 0036), as a pass; a warn when `index.sqlite` was built under another boundary (its
  `day_local` puts lines on other days until the next reader rebuilds it); a fail when the value is
  not a clock, which every reader that groups by day refuses. A record whose day begins at midnight,
  with an index that agrees, has no such line.
- `owner`: `policy/owner.json` is there and names at least one alias, so the owner is never listed
  as their own company (`present.owner_of`). Missing or empty is a warn, not JSON is a fail.
- `agents`: the lines marked machine text (docs/adapters/agents.md), per source: a message an agent
  wrote (`extra.machine`) and a transcript with a machine participant, standing; and how many
  senders `policy/agents.json` names, the owner's own bots the Beeper adapters mark. Only the
  sources that write the mark are read (`AGENT_SOURCES`, every transcript), from the index when it is
  current, else from the month files; a sealed line this machine cannot open is counted, not read. A
  pass; a file that is not the shape is a fail naming it; a record with neither has no line.
- `places`: `places.json` names at least one place of kind `home`, which the night rule needs
  (`trips`, `rollup nights`). None is a warn, not a places file is a fail.
- `assets`: `assets.json` is a registry when it exists (ADR 0018). Absent is fine.
- `voiceprints`: the voiceprint registry, `voiceprints.age` (RFC 0038 §5), said and never shown: that
  the file is there, when it was written, and, opened with this machine's identity, with which
  embedding model and for how many people; a warn when that model is not the configured one (its
  vectors are not comparable: `setup speakers --rebuild`) or when the file will not open. A record
  that names no recipients keeps none, and the line says the review hears what it compares for each
  run. A record with no file and no transcript with voices has no line.
- `dates`: every line's timestamp lies in its source's plausible range (`plausible`: calendar
  entries 1970 to now plus 5 years, mail 1990 to now plus 1 day, the rest 1970 to now plus 1 day,
  each overridable per source in `policy/plausible.json`). Lines outside it are a warn that counts
  them per source with the earliest and the latest; they are never deleted or hidden, and
  `logbook doctor --implausible` lists their ids. Read from the index when it is current, else
  from the month files. A settings file that is not the shape is a fail naming it.
- `extra:<name>`: each optional extra (`ais`, `crypto`, `sealed`, `speakers`, `transcribe`) is installed,
  with its install line when not (a warn): the line adds the extra to this Logbook exactly as it is
  installed (its Python, its venv's options, its source and version, a pipx suffix, uv's companions): this
  venv's pip at the installed version, `pipx inject` into pipx's venv (with `PIPX_HOME` only when the venv
  is not in the home a bare `pipx` uses), `uv tool install --force` with every extra (and the `--python` the
  receipt asked for, if any), or, in a clone, `uv sync --extra <name>`, run in the clone the warn names,
  with an `--extra` for every extra it has too, since `uv sync` keeps only what it is given, and only what
  keeps it this environment: `--python` when uv would ask for another Python than the one running
  (`UV_PYTHON`, the clone's or uv's global `.python-version`), `--no-default-groups` when a default group is
  not installed here. Where doctor proves no such line (Homebrew, whose formula adds no extra, a receipt it
  cannot read, a source that may have changed since, uv's cache) it prints none: the warn says why and
  points to docs/install.md, in one sentence. Nothing is imported to find out: a module's spec is looked
  for, and pyannote.audio (`speakers`) is asked by its installed distribution, as `diarize.installed` asks
  it, since its spec alone would import the `pyannote` package around it.
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
- `export-day`: a folder `export --day` or `--days` writes reads its ceiling from the `folder` entry; with
  none, the line says no entry exists and the default tier 1 applies, as the crossing line the export
  keeps records it (`"entry": null, "default_tier": 1`); `--tier` may lower it, never raise it
  (docs/export.md).
- `phone`: whether the owner's own phone may write through the Library (`logbook setup phone`,
  docs/serve.md): this machine only, as by default, or the origin it may write from and the login,
  the part before @ shortened, never whole. A warn when the setting is not the shape (it lets nothing
  in), or when it names an origin and no `tailscale` is found here (on the PATH doctor is given, or
  where the macOS and Windows apps put it): nothing is run to find out, and without a PATH to look
  on it says nothing of it.
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
- `videos`: when the record names the family's videos (`sync drive --videos`, RFC 0040) or the cache
  under `state/videos/` exists, how many video files the record holds and their size, how many `videos
  fetch` has fetched and `videos infer` has inferred and how many wait in the cache, how many scenes
  the latest inference of each file found, how many it proposed a place or a date for and how many the
  owner confirmed, and the cache's size against its cap. A pass; a cache over its cap, or a
  `state/videos.json` that is not the shape, is a warn naming it. Read from this machine alone, as the
  `drafts` line reads; a record with no video and no cache has no line.
- `schedule`: which machine runs the scheduled syncs, the record's home (ADR 0022): `state/home.json`,
  written by `sync --install-schedule` there, names this machine, or no machine yet (a pass either
  way); another machine is a warn: writers belong on that one.
- `last-run`: when the schedule (`sync --install-schedule`) last ran `sync --scheduled`, from
  `state/last-run.json` whichever install wrote it (the user's agents or timers, the system's with
  `--system`, or none on this machine), and whether it was clean: a run older than 26 hours, or one in
  which a source failed or a check failed, is a warn. No file: a pass when no schedule is installed
  here, a warn when one is and has not run yet. Both the user's and the system's installed is a warn
  whatever the run said: each runs every source at the same times.
- `restore-test`: the last `backup --restore-test` (`state/last-restore-test.json`) passed within 35
  days (the schedule runs it on the first Sunday of the month); none, older, or skipped is a warn saying
  what to do (with no backup recorded yet, `backup DEST` first); failed is a fail with the reason.
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
import importlib.metadata
import importlib.util
import itertools
import json
import os
import re
import shutil
import sqlite3
import sys
import tomllib
import urllib.parse
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, TextIO
from zoneinfo import ZoneInfo

from ..core import (
    assets,
    attachments,
    day_start,
    drafts,
    index,
    machine,
    places,
    plausible,
    policy,
    sealing,
    voiceprints,
)
from ..core.chain import Line, is_sealed
from ..core.store import RETRACTION, FormatError, Logbook, read_line_at, retractions
from . import adapters, first_run, home, last_run, phone, schedule, serve, synthesis, videos
from . import service as serve_service
from .adapters import service_account

Status = Literal["pass", "warn", "fail"]
Usage = Callable[[Path], tuple[int, int, int]]  # (total, used, free) in bytes, as shutil.disk_usage

GIB = 1024**3
DISK_WARN_BYTES = 5 * GIB
DISK_FAIL_BYTES = GIB // 2
#: how this Logbook was installed, each with the one line that adds an extra to it as it is (`install_line`):
#: pip and `pipx inject` add to the environment this Logbook runs in, `uv tool install --force` and a
#: clone's `uv sync` make it again with exactly what they are given, so their line names every extra;
#: Homebrew's formula installs no extra, and where doctor proves no line it prints none
HowInstalled = Literal["pipx", "uv-tool", "checkout", "pip", "homebrew"]
PIPX_RECEIPT = "pipx_metadata.json"  # in the venv pipx made, which is `sys.prefix`
UV_TOOL_RECEIPT = "uv-receipt.toml"  # in the environment `uv tool install` made, likewise
#: each extra with the modules that satisfy it, any one of them; `transcribe` has an engine per platform,
#: and `speakers` (pyannote.audio, which brings torch) is apart from it
EXTRAS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ais", ("websockets",)),
    ("crypto", ("cryptography",)),
    ("sealed", ("pyrage",)),
    ("speakers", ("pyannote.audio",)),
    ("transcribe", ("mlx_whisper", "faster_whisper")),
)
#: the extras doctor has no check for, with the modules that show one is installed; `judge` and
#: `describe` install nothing off Apple silicon, so there only the installer's receipt names them
UNCHECKED_EXTRAS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("describe", ("mlx_vlm",)),
    ("judge", ("mlx_lm",)),
    ("mcp", ("mcp",)),
    ("stream", ("ijson",)),
)
#: every extra the package has: what a pipx receipt's brackets name is read only when it is one of them
KNOWN_EXTRAS = frozenset(extra for extra, _ in (*EXTRAS, *UNCHECKED_EXTRAS))
#: a module asked by its installed distribution, not its spec: finding the spec of `pyannote.audio`
#: imports the `pyannote` package around it, so it is asked as `diarize.installed` asks (labs, which
#: contrib never imports)
DISTRIBUTIONS: Mapping[str, str] = {"pyannote.audio": "pyannote.audio"}
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
#: the message sources that write the machine mark, `beeper-<network>` among them; every transcript is read
AGENT_SOURCES = ("telegram", "beeper")


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
        noted += " `logbook import attachments status`)"
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
        return Check(
            "index", "warn", "no index.sqlite; the next reader builds it, or run `logbook repair index`"
        )
    return Check(
        "index",
        "warn",
        "index.sqlite is behind logbook.json; the next reader rebuilds it, or run `logbook repair index`",
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


def _agent_source(source: object) -> bool:
    return isinstance(source, str) and (source in AGENT_SOURCES or source.startswith("beeper-"))


def _marked(line: Line) -> bool:
    """Whether the line is machine text: a message an agent wrote, a transcript with an agent in it."""
    payload = line.get("payload") or {}
    if line.get("kind") == "transcript":
        parts = payload.get("participants")
        return isinstance(parts, list) and any(machine.is_machine_participant(p) for p in parts)
    return machine.is_machine(payload)


def agent_lines(lb: Logbook, state: str) -> Iterator[Line]:
    """The transcripts and the messages of `AGENT_SOURCES`, one at a time, opened where this machine
    has the identity: from the index when it is `current` (read-only), else from the month files."""
    if state != "current":
        for line in lb.lines_unsorted():
            kind = line.get("kind")
            if kind == "transcript" or (kind == "message" and _agent_source(line.get("source"))):
                yield _opened(lb, line)
        return
    db = sqlite3.connect(f"{lb.index_path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        places = db.execute(
            "SELECT file, offset FROM lines WHERE kind = 'transcript' OR (kind = 'message' AND"
            f" (source IN ({', '.join('?' * len(AGENT_SOURCES))}) OR source LIKE 'beeper-%')) ORDER BY seq",
            AGENT_SOURCES,
        ).fetchall()
    finally:
        db.close()  # before anything could unlink it: Windows refuses to delete an open file
    for file, offset in places:
        with (lb.root / str(file)).open("rb") as fh:
            yield _opened(lb, read_line_at(fh, int(offset)))


def agents_check(lb: Logbook, state: str) -> Check | None:
    """None unless a standing line is marked machine or `policy/agents.json` names a sender."""
    try:
        named = policy.agent_senders(lb.root)
    except policy.PolicyError as e:
        return Check("agents", "fail", str(e))
    retracted = retractions(kind_lines(lb, state, (RETRACTION,)))
    per_source: dict[str, int] = {}
    sealed = 0
    for line in agent_lines(lb, state):
        if str(line.get("id")) in retracted:
            continue
        if is_sealed(line):
            sealed += 1
        elif _marked(line):
            source = str(line.get("source"))
            per_source[source] = per_source.get(source, 0) + 1
    if not per_source and not named:
        return None
    path = policy.AGENTS_FILE.as_posix()
    senders = f"{len(named)} sender{'s' if len(named) != 1 else ''} named in {path}"
    if per_source:
        ranked = sorted(per_source.items(), key=lambda kv: (-kv[1], kv[0]))
        detail = (
            "lines marked machine: " + ", ".join(f"{source} {n:,}" for source, n in ranked) + f"; {senders}"
        )
    else:
        detail = f"no line marked machine yet; {senders}: the next `add beeper` or `sync beeper` marks theirs"
    if sealed:
        detail += f"; {sealed:,} sealed line{'s' if sealed != 1 else ''} not opened here (no identity)"
    return Check("agents", "pass", detail)


def places_check(root: Path) -> Check:
    path = places.path_of(root)
    hint = "`logbook setup places add Home --lat LAT --lon LON --kind home` so nights at home are known"
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


def voiceprints_check(lb: Logbook, state: str) -> Check | None:
    """The voiceprint registry (RFC 0038 §5): that it is there, when, with which model and for how
    many people it was written, never a number of it; which of the two a record without it is in."""
    found = voiceprints.about(lb)
    if found is None:
        if not _has_voices(lb, state):
            return None
        if not lb.recipients:
            return Check(
                "voiceprints",
                "pass",
                "none on disk: the record names no recipients, so the review hears the voices it compares"
                " for each run and keeps nothing",
            )
        if not lb.identities:  # what a write here answers: no file, and none made on this machine
            return Check(
                "voiceprints", "pass", f"none, and none is written here: {voiceprints.NEEDS_IDENTITY}"
            )
        return Check(
            "voiceprints", "pass", f"none yet: `logbook setup speakers --rebuild` makes {voiceprints.FILE}"
        )
    detail = voiceprints.about_text(found, ZoneInfo(str(lb.meta.get("timezone") or "UTC")))
    if found.error is not None:
        if not lb.identities:  # sealed, as it must be: this machine cannot say more, and need not
            return Check("voiceprints", "pass", detail)
        return Check("voiceprints", "warn", f"{detail}; `logbook setup speakers --rebuild` makes it again")
    if found.model != voiceprints.MODEL:
        return Check(
            "voiceprints",
            "warn",
            f"{detail}; written with another model than the configured one, {voiceprints.MODEL}, whose"
            " voices it cannot compare: `logbook setup speakers --rebuild`",
        )
    return Check("voiceprints", "pass", detail)


def _has_voices(lb: Logbook, state: str) -> bool:
    """Whether a transcript of the record carries voices (RFC 0038 §2), as far as this machine can
    open it."""
    return any((line.get("payload") or {}).get("speakers") for line in kind_lines(lb, state, ("transcript",)))


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
    """Whether `module` could be imported, without importing it: an engine loads a model on import.
    A module `DISTRIBUTIONS` names is asked as `diarize.installed` asks: it is here when it is already
    in the process (None there blocks the import, so it is not), else when its distribution is
    installed. Any other module is looked for by its spec."""
    distribution = DISTRIBUTIONS.get(module)
    if distribution is not None:
        if module in sys.modules:
            return sys.modules[module] is not None
        try:
            importlib.metadata.distribution(distribution)
        except importlib.metadata.PackageNotFoundError:
            return False
        return True
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):  # a missing parent package, or a name find_spec refuses
        return False


@dataclass(frozen=True)
class Here:
    """What doctor knows of the process it runs in, all of it read, none of it run: the interpreter
    (`sys.executable`, and `sys._base_executable` behind a venv's), its version, openlogbook's installed
    version and its `direct_url.json` and `INSTALLER`, whether pip is importable here (its spec, never
    the module), the version of another installed distribution (`version_of`), whether the line is
    for PowerShell (what Windows Terminal opens), whether this interpreter is a venv's (`sys.prefix` is
    not `sys.base_prefix`), and the environment's variables, read, never set."""

    executable: str = ""
    base: str = ""
    python: tuple[int, int, int] = (0, 0, 0)
    cpython: bool = True
    version: str = ""
    direct_url: str | None = None
    installer: str = ""
    pip: bool = False
    version_of: Callable[[str], str | None] = field(default=lambda name: None, compare=False)
    windows: bool = False
    venv: bool = False
    env: Mapping[str, str] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class Install:
    """How this Logbook was installed, and what the line that adds an extra keeps: the requirement after
    `openlogbook[extras]` (`==0.7.0`, the installed version, or ` @ git+…@<commit>`, the commit installed),
    or the folder of an editable install or a checkout; the interpreter the line names; pipx's home and
    venv; the options the line carries (pip's index options under pipx, uv's index options and
    companions). `why` set: doctor proves no line, and says why."""

    how: HowInstalled
    extras: frozenset[str] = frozenset()
    requirement: str = ""
    folder: str = ""
    python: str = ""
    home: str = ""
    venv: str = ""
    options: tuple[str, ...] = ()
    uv_pip: bool = False
    windows: bool = False
    why: str = ""


#: a command-line value that needs no quotes in any shell doctor's reader has
PLAIN = re.compile(r"[\w.:/\\@%+=,~-]+")
#: what no quoting makes literal in both POSIX shells and PowerShell: a value with one has no line
UNQUOTABLE = re.compile(r"[\"$`!\n\r]")
#: the pip options that name where pip looks, the only ones a pipx receipt's `pip_args` may carry into
#: the line: pip and uv's pip (pipx's uv backend) both take them, and they change nothing but the index
INDEX_OPTIONS = ("--index-url", "-i", "--extra-index-url", "--find-links", "-f")
#: the sources a requirement in uv's receipt names (one at most: none is an index), and every other key
UV_SOURCES = ("specifier", "git", "url", "path", "directory", "editable")
UV_KEYS = frozenset({"name", "extras", "marker", "subdirectory", *UV_SOURCES})
#: the `[tool]` keys a receipt has that one line reproduces; `constraints`, `overrides` and
#: `build-constraint-dependencies` came from files no line names, so a receipt with one has no line
UV_TOOL_KEYS = frozenset({"requirements", "python", "entrypoints", "options"})
#: a Python request in uv's receipt doctor can hold against the running interpreter: `3.12`, `3.12.3`,
#: `cpython3.12`, `cpython@3.12`, `cpython-3.12`, `python3.12`; anything else (a range, `pypy`, `3.13t`)
#: is not guessed at
PYTHON_REQUEST = re.compile(r"^(?:c?python[-@]?)?(\d+)(?:\.(\d+))?(?:\.(\d+))?$", re.IGNORECASE)
HOMEBREW = "Homebrew installed this Logbook and its formula installs the base package only"


class NoLine(ValueError):
    """Doctor cannot prove the line: why, as a clause."""


def _names(extras: str | None) -> frozenset[str]:
    return frozenset(e.strip() for e in (extras or "").split(",") if e.strip())


def _arg(value: str) -> str:
    """A value as one word of the line: bare when it can be, else in double quotes; `NoLine` for one
    that no double quotes keep literal (`"`, `$`, a backtick, `!`, and off Windows a backslash, which a
    POSIX shell drops bare and may read as an escape in quotes)."""
    if UNQUOTABLE.search(value) or ("\\" in value and sys.platform != "win32"):
        raise NoLine("a path or address in it has a character no shell keeps literal in quotes")
    return value if PLAIN.fullmatch(value) else f'"{value}"'


def _command(path: str, windows: bool) -> str:
    """An interpreter's path as the first word of a line: bare when it can be, else quoted, and in
    PowerShell (what Windows Terminal opens) a quoted path runs only after `&`."""
    word = _arg(path)
    return f"& {word}" if word.startswith('"') and windows else word


def _strings(value: object) -> Iterator[str]:
    """Every string a parsed receipt holds, at any depth."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _secret(receipt: object) -> bool:
    """Whether a receipt names an address with a password (`https://__token__:…@`) or a name in an
    HTTP address (`https://<token>@github.com`, how a token is often given); `git+ssh://git@…` is no
    secret. Doctor prints no such line: it would land on the screen and in `state/last-run.json`."""
    for value in _strings(receipt):
        for word in value.split():
            if "://" not in word:
                continue
            try:
                parts = urllib.parse.urlsplit(word)
                named = parts.username and parts.scheme.endswith(("http", "https"))
                if parts.password is not None or named:
                    return True
            except ValueError:
                return True  # an address that will not parse is not printed either
    return False


SECRET = "an address it was installed from has a password or token in it, which doctor never prints"


def _source(here: Here) -> tuple[str, str]:
    """What this Logbook was installed from, from its own `direct_url.json` (PEP 610) and version: an
    index (`("==0.7.0", "")`, the version installed now), an editable folder (`("", folder)`) or a git
    commit (`(" @ git+…@<commit>", "")`, the commit installed now, never a branch that may have moved).
    A folder installed whole, a URL and a wheel may have changed since: `NoLine`."""
    if not here.direct_url:
        if not here.version:
            raise NoLine("its installed version cannot be read")
        return (f"=={here.version}", "")
    try:
        origin = json.loads(here.direct_url)
        url = origin["url"]
        if not isinstance(origin, dict) or not isinstance(url, str):
            raise TypeError
    except (ValueError, KeyError, TypeError):
        raise NoLine("its direct_url.json does not read") from None
    if _secret(url):
        raise NoLine(SECRET)
    dir_info, vcs = origin.get("dir_info"), origin.get("vcs_info")
    if isinstance(dir_info, dict) and dir_info.get("editable") is True:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "file" or parts.netloc not in ("", "localhost"):
            raise NoLine("it is editable from somewhere that is not a folder on this machine")
        from urllib.request import url2pathname  # a path, never split as a string; only here

        folder = str(Path(url2pathname(parts.path)))
        _arg(folder)
        return ("", folder)
    if isinstance(vcs, dict) and vcs.get("vcs") == "git" and isinstance(vcs.get("commit_id"), str):
        subdirectory = origin.get("subdirectory")
        fragment = f"#subdirectory={subdirectory}" if isinstance(subdirectory, str) and subdirectory else ""
        requirement = f" @ git+{url}@{vcs['commit_id']}{fragment}"
        _arg(requirement)
        return (requirement, "")
    raise NoLine("it was installed from a folder, a URL or a wheel, which may have changed since")


def _pipx(path: Path, here: Here) -> Install:
    """pipx's venv (`path` is its receipt): the line is `pipx inject` into that venv, which installs into it
    as it is, so its Python and its options (`--system-site-packages`) stay, and writes the extras back to
    the receipt. `PIPX_HOME` names the home the venv is in when a bare `pipx` here would look elsewhere
    (`_pipx_default_home`: `--global`, a home of its own). The venv's name keeps a `--suffix`. Its pip
    may be given the index options the receipt's `pip_args` name (`--pip-args`), and nothing else;
    injected packages are not touched."""
    receipt = json.loads(path.read_text(encoding="utf-8"))
    package = receipt["main_package"]
    spec, args = package["package_or_url"], package.get("pip_args") or []
    if package.get("package", "openlogbook") != "openlogbook":
        raise NoLine(f"its venv is another app's ({package.get('package')}), which pipx installed it beside")
    if not isinstance(spec, str) or not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise NoLine(f"its receipt, {path}, is in a shape doctor does not read")
    if _secret(receipt):
        raise NoLine(
            f"its receipt, {path}, names an address with a password or token, which doctor never prints"
        )
    named = re.findall(r"\[([^\[\]]*)\]", spec)  # the last bracket: a folder is never split on `@` or `~`
    extras = _names(named[-1] if named else "") & KNOWN_EXTRAS
    venv = path.parent
    if venv.parent.name != "venvs":
        raise NoLine(f"its venv, {venv}, is not in a pipx home's venvs folder")
    carried: list[str] = []
    rest = [
        a for a in args if a not in ("-e", "--editable", "--force-reinstall")
    ]  # pipx's own, or the source's
    while rest:
        word = rest.pop(0)
        option, eq, value = word.partition("=")
        if word == "--no-index":
            carried.append(word)
        elif option in INDEX_OPTIONS and eq:
            carried.append(f"{option}={_plain(value)}")
        elif word in INDEX_OPTIONS and rest:
            carried += [word, _plain(rest.pop(0))]
        else:
            raise NoLine(f"its receipt, {path}, gives pip an option doctor does not carry ({word})")
    requirement, folder = _source(here)
    home, name = venv.parent.parent, _arg(venv.name)
    _arg(str(home))
    return Install(
        "pipx",
        extras,
        requirement,
        folder,
        home="" if _pipx_default_home(home, here) else str(home),
        venv=name,
        options=(f"--pip-args={_arg(' '.join(carried))}",) if carried else (),
        windows=here.windows,
    )


def _plain(value: str) -> str:
    """An index option's value as it goes inside `--pip-args="…"`: one word, or `NoLine`."""
    if not PLAIN.fullmatch(value):
        raise NoLine("an index option pipx's receipt gives pip has a character doctor does not quote")
    return value


def _pipx_default_home(home: Path, here: Here) -> bool:
    """Whether `home` is the pipx home a bare `pipx` in this shell uses: the one `PIPX_HOME` names when it
    is set, else `~/.local/pipx` when that folder exists (every pipx still honours it), else
    `~/.local/share/pipx` (Linux) or `~/Library/Application Support/pipx` (macOS). On Windows, and for
    any other home (`--global`'s among them), the line names it: `PIPX_HOME=… pipx inject`."""
    named = here.env.get("PIPX_HOME")
    if named:
        return _same(home, Path(named))
    if here.windows or sys.platform == "win32":
        return False
    legacy = Path.home() / ".local" / "pipx"
    if legacy.is_dir():
        return _same(home, legacy)
    platform = (
        Path.home() / "Library" / "Application Support" / "pipx"
        if sys.platform == "darwin"
        else Path.home() / ".local" / "share" / "pipx"
    )
    return _same(home, platform)


def _python_agrees(request: object, here: Here) -> bool:
    """Whether uv's receipt's `python` (none, a version request, a path) is the interpreter running."""
    if request is None:
        return True
    if not isinstance(request, str):
        return False
    found = PYTHON_REQUEST.match(request.strip())
    if found:
        wanted = tuple(int(p) for p in found.groups() if p is not None)
        return here.cpython and here.python[: len(wanted)] == wanted
    return any(_same(Path(request), Path(p)) for p in (here.executable, here.base) if p)


def _uv_kind(entry: dict[str, object]) -> str:
    """Which source a requirement in uv's receipt names: `index` (none, or a specifier), `git`,
    `editable`, or `NoLine` for a URL, a wheel, a folder installed whole or a shape doctor does not know."""
    sources = [k for k in UV_SOURCES if k in entry]
    if set(entry) - UV_KEYS or len(sources) > 1 or not all(isinstance(entry[k], str) for k in sources):
        raise NoLine("its receipt names a requirement in a shape doctor does not read")
    if not sources or sources == ["specifier"]:
        return "index"
    if sources[0] in ("git", "editable"):
        return sources[0]
    raise NoLine("it was installed from a folder, a URL or a wheel, which may have changed since")


def _uv_with(entry: dict[str, object], executables: bool, here: Here) -> str:
    """A requirement beside openlogbook's in uv's receipt as the option that put it there, at the
    version installed now: `--with`, or `--with-executables-from` when the tool's executables include
    its own (`executables`). One from anywhere but an index, or with a marker, is `NoLine`."""
    name, extras = entry.get("name"), entry.get("extras") or []
    if _uv_kind(entry) != "index" or "marker" in entry or not isinstance(name, str):
        raise NoLine(f"a package installed beside it ({name}) did not come from an index")
    version = here.version_of(name)
    if not isinstance(extras, list) or version is None:
        raise NoLine(f"the version of a package installed beside it ({name}) cannot be read")
    named = f"{name}[{','.join(str(e) for e in extras)}]" if extras else name
    option = "--with-executables-from" if executables else "--with"
    return f"{option} {_arg(f'{named}=={version}')}"


def _uv_options(options: object) -> tuple[str, ...]:
    """`[tool.options]`, the index options uv was given, as the flags that give them again; an option that
    is not an index's is not guessed at."""
    if not isinstance(options, dict):
        raise NoLine("its receipt's options are in a shape doctor does not read")
    flags: list[str] = []
    for key, value in options.items():
        if key == "no-index" and isinstance(value, bool):
            flags += ["--no-index"] if value else []
        elif key == "index-url" and isinstance(value, str):
            flags += [f"--index-url {_arg(value)}"]
        elif key in ("find-links", "extra-index-url") and isinstance(value, list):
            if not all(isinstance(v, str) for v in value):
                raise NoLine("its receipt's options are in a shape doctor does not read")
            flags += [f"--{key} {_arg(v)}" for v in value]
        else:
            raise NoLine(f"its receipt names an option doctor does not carry ({key})")
    return tuple(flags)


def _uv_tool(path: Path, here: Here) -> Install:
    """uv's tool environment (`path` is its receipt): `uv tool install --force` makes it again with
    exactly what the line names, so the line names the interpreter running now (`--python`), the
    receipt's index options, each companion at its installed version, every extra, and openlogbook
    as installed now (`_source`). A receipt whose Python is not the one running, whose source is not
    the one installed, or that names what one line cannot give again (constraints, a companion from a
    URL), is `NoLine`."""
    tool = tomllib.loads(path.read_text(encoding="utf-8"))["tool"]
    if _secret(tool):
        raise NoLine(
            f"its receipt, {path}, names an address with a password or token, which doctor never prints"
        )
    requirements, entrypoints = tool["requirements"], tool.get("entrypoints") or []
    if not all(isinstance(r, dict) for r in (*requirements, *entrypoints)) or set(tool) - UV_TOOL_KEYS:
        raise NoLine(f"its receipt, {path}, is in a shape doctor does not read")
    ours = requirements[0]  # the tool's own package; openlogbook beside another tool is that tool's
    if ours.get("name") != "openlogbook" or any(r.get("name") == "openlogbook" for r in requirements[1:]):
        raise NoLine(f"its receipt, {path}, makes another tool, with openlogbook beside it")
    named = ours.get("extras") or []
    if not isinstance(named, list) or not all(isinstance(e, str) for e in named):
        raise NoLine(f"its receipt, {path}, is in a shape doctor does not read")
    extras = frozenset(named)
    kind = _uv_kind(ours)
    if "marker" in ours or "subdirectory" in ours:
        raise NoLine(f"its receipt, {path}, is in a shape doctor does not read")
    if not here.executable:
        raise NoLine("the interpreter it runs in cannot be named")
    if not _python_agrees(tool.get("python"), here):
        raise NoLine("uv's receipt names another Python than the one it runs on")
    requirement, folder = _source(here)
    installed = "editable" if folder else ("git" if requirement.startswith(" @") else "index")
    if installed != kind:
        raise NoLine("uv's receipt names another source than the one installed")
    sources = {e.get("from") for e in entrypoints} - {"openlogbook"}
    others = [r for r in requirements if r is not ours]
    if not sources <= {r.get("name") for r in others}:
        raise NoLine(f"its receipt, {path}, is in a shape doctor does not read")
    options = _uv_options(tool.get("options", {}))
    withs = tuple(_uv_with(r, r.get("name") in sources, here) for r in others)
    request = tool.get("python")
    if not isinstance(request, str) or _inside(Path(request), path.parent):
        request = ""  # none asked; or this environment's own interpreter, which `--force` makes again
    if request:
        _arg(request)
    return Install("uv-tool", extras, requirement, folder, request, options=options + withs)


def _inside(path: Path, folder: Path) -> bool:
    """`path` names a file in `folder`, by their parts (macOS and Windows ignore case)."""
    try:
        parts = [p.casefold() for p in path.absolute().parts]
        within = [p.casefold() for p in folder.absolute().parts]
    except (OSError, ValueError):
        return False
    return parts[: len(within)] == within


def _homebrew(prefix: Path) -> bool:
    """`prefix` is a Homebrew keg's (`…/Cellar/logbook/0.7.0/libexec`, where the formula's
    `virtualenv_install_with_resources` puts it), told by its path's parts alone."""
    parts = [p.casefold() for p in prefix.parts]
    return any(a == "cellar" and b in ("logbook", "openlogbook") for a, b in itertools.pairwise(parts))


def _same(a: Path, b: Path) -> bool:
    """One file or folder, as the filesystem tells (macOS and Windows ignore case); a missing one is
    no match."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def install_of(prefix: Path, here: Here | None = None) -> Install:
    """How the Logbook in `prefix` (`sys.prefix`) was installed, from the files its installer left and
    what `here` knows: pipx's and uv's receipts in the prefix, a Homebrew keg by its path, a checkout
    when the package is editable from a folder whose `.venv` is `prefix` (`uv sync`), else pip. Each
    is held to what one line can keep (`install_line`); what it cannot is an `Install` with `why` set,
    never a traceback. Reads files only, never runs a command."""
    here = here or Here()
    pipx, uv = prefix / PIPX_RECEIPT, prefix / UV_TOOL_RECEIPT
    how: HowInstalled = "pipx" if pipx.is_file() else "uv-tool" if uv.is_file() else "pip"
    try:
        if how == "pipx":
            return _pipx(pipx, here)
        if how == "uv-tool":
            return _uv_tool(uv, here)
        if _homebrew(prefix):
            return Install("homebrew", why=HOMEBREW)
        return _pip(prefix, here)
    except NoLine as e:
        return Install(how, why=str(e))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
        receipt = pipx if how == "pipx" else uv if how == "uv-tool" else None
        why = f"its receipt, {receipt}, is in a shape doctor does not read" if receipt else ""
        return Install(how, why=why or "what it was installed from does not read")


def _pip(prefix: Path, here: Here) -> Install:
    """A checkout (`uv sync`), or pip: this interpreter's pip, or uv's pip aimed at it in an environment
    uv made (its `INSTALLER`), with openlogbook at the version installed now from an index. Never an
    environment in uv's cache (`uvx`, `uv run --with`), which keeps nothing it is given, and never a
    Python that is not a venv's, whose pip would install beside (`--user`) or refuse (PEP 668)."""
    parts = {p.casefold() for p in prefix.parts}
    config = prefix / "pyvenv.cfg"
    relocatable = config.is_file() and re.search(
        r"^\s*relocatable\s*=\s*true\s*$", config.read_text(encoding="utf-8"), re.MULTILINE | re.IGNORECASE
    )
    if parts & {"archive-v0", "builds-v0"} or relocatable:
        raise NoLine("it runs from uv's cache (`uvx`, `uv run --with`), which keeps nothing added to it")
    requirement, folder = _source(here)
    if folder and _same(prefix, Path(folder) / ".venv") and (Path(folder) / "pyproject.toml").is_file():
        try:
            if here.env.get("UV_PROJECT_ENVIRONMENT"):
                raise NoLine("UV_PROJECT_ENVIRONMENT is set, so `uv sync` would sync another environment")
            if not here.executable:
                raise NoLine("the interpreter it runs in cannot be named")
            _arg(here.executable)
            options = _sync_options(Path(folder), here)
            return Install("checkout", folder=folder, python=here.executable, options=options)
        except NoLine as e:
            return Install("checkout", why=str(e))
    if not requirement or folder or requirement.startswith(" @"):
        raise NoLine("pip installed it from a folder, a repository, a URL or a wheel, not an index")
    if not here.executable:
        raise NoLine("the interpreter it runs in cannot be named")
    if not here.venv:
        raise NoLine("the Python it runs in is not a venv's, so pip would install beside it or refuse")
    _arg(here.executable)
    uv_pip = not here.pip and here.installer.strip() == "uv"
    if not here.pip and not uv_pip:
        raise NoLine("the interpreter it runs in has no pip")
    return Install(
        "pip", requirement=requirement, python=here.executable, uv_pip=uv_pip, windows=here.windows
    )


def _sync_options(folder: Path, here: Here) -> tuple[str, ...]:
    """What `uv sync` run in the clone `folder` needs, beside its extras, to sync the environment this
    process runs in as it is (the desk, after the tag): `--python` and this interpreter (its base) when
    uv would ask for another (`UV_PYTHON`, else the clone's `.python-version`, else uv's global pin),
    since uv would make the venv again on that one; `--no-default-groups` when a default group of the
    clone's `pyproject.toml` is not installed here, since uv would add it. Nothing when neither: the
    short line. `NoLine` when the `pyproject.toml` does not read, or when `UV_NO_DEV` or
    `UV_NO_DEFAULT_GROUPS` would have `uv sync` remove the groups installed."""
    options: list[str] = []
    if not _python_kept(folder, here):
        options += ["--python", _arg(here.base or here.executable)]
    if not _groups_installed(folder, here):
        options.append("--no-default-groups")
    elif any(here.env.get(v) for v in ("UV_NO_DEV", "UV_NO_DEFAULT_GROUPS")):
        raise NoLine("UV_NO_DEV or UV_NO_DEFAULT_GROUPS is set, so `uv sync` would remove the dev group")
    return tuple(options)


def _python_kept(folder: Path, here: Here) -> bool:
    """Whether what uv asks for in `folder` is this interpreter (`_python_agrees`): no request at all
    (the venv met `requires-python` when uv made it), a version it starts with (`3.12` of 3.12.3), or
    its path; a request doctor does not hold it to (another implementation, a range) is not."""
    request = here.env.get("UV_PYTHON") or ""
    for pinned in (folder / ".python-version", _global_pin(here)):  # uv reads none above the project
        if request:
            break
        if pinned is not None and pinned.is_file():
            lines = pinned.read_text(encoding="utf-8").splitlines()
            request = next((x.strip() for x in lines if x.strip() and not x.startswith("#")), "")
    return _python_agrees(request or None, here)


def _global_pin(here: Here) -> Path | None:
    """The file `uv python pin --global` writes, which uv reads when the project pins nothing:
    `%APPDATA%\\uv` on Windows, else `$XDG_CONFIG_HOME/uv` or `~/.config/uv`."""
    if here.windows:
        appdata = here.env.get("APPDATA")
        return Path(appdata) / "uv" / ".python-version" if appdata else None
    config = here.env.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(config) / "uv" / ".python-version"


def _groups_installed(folder: Path, here: Here) -> bool:
    """Whether every requirement of the clone's default groups (`tool.uv.default-groups`, else `dev`)
    is installed here (`here.version_of`): the clone's own package and a requirement with a marker,
    which doctor does not read, aside. `NoLine` when the `pyproject.toml` does not read."""
    try:
        project = tomllib.loads((folder / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        raise NoLine("the clone's pyproject.toml does not read") from None
    groups = project.get("dependency-groups") or {}
    chosen = ((project.get("tool") or {}).get("uv") or {}).get("default-groups", ["dev"])
    names = list(groups) if chosen == "all" else [str(g) for g in chosen if isinstance(g, str)]
    own = re.sub(r"[-_.]+", "-", str((project.get("project") or {}).get("name") or "")).lower()
    seen: set[str] = set()
    while names:
        group = names.pop()
        if group in seen:
            continue
        seen.add(group)
        for requirement in groups.get(group) or []:
            if isinstance(requirement, dict):  # `{include-group = "…"}`
                names.extend(str(v) for k, v in requirement.items() if k == "include-group")
                continue
            text = str(requirement)
            name = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", text.strip())
            if name is None or ";" in text or re.sub(r"[-_.]+", "-", name.group(0)).lower() == own:
                continue
            if here.version_of(name.group(0)) is None:
                return False
    return True


def here_now() -> Here:
    """`Here` of this process."""
    direct_url: str | None
    try:
        found = importlib.metadata.distribution("openlogbook")
        version = found.version
    except (importlib.metadata.PackageNotFoundError, OSError, ValueError):
        found, version = None, ""
    try:
        direct_url = found.read_text("direct_url.json") if found else None
    except (OSError, ValueError):
        direct_url = "unreadable"  # not JSON: `_source` says it does not read, never "from an index"
    try:
        installer = (found.read_text("INSTALLER") if found else None) or ""
    except (OSError, ValueError):
        installer = ""
    try:
        pip = importlib.util.find_spec("pip") is not None  # its spec: pip is never imported
    except (ImportError, ValueError):
        pip = False

    def version_of(name: str) -> str | None:
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            return None

    return Here(
        sys.executable or "",
        getattr(sys, "_base_executable", "") or "",
        (sys.version_info.major, sys.version_info.minor, sys.version_info.micro),
        sys.implementation.name == "cpython",
        version or "",
        direct_url,
        installer,
        pip,
        version_of,
        sys.platform == "win32",
        sys.prefix != sys.base_prefix,
        os.environ,
    )


def detect_install() -> Install:
    """`install_of` this process: `sys.prefix` and `here_now`."""
    return install_of(Path(sys.prefix), here_now())


def install_line(install: Install, extras: set[str] | frozenset[str]) -> str | None:
    """The line that adds `extras`, all of them, to this Logbook as it is installed, keeping its Python,
    its venv's options, its source and version, its suffix and its companions; None when doctor proves
    no such line (`install.why`)."""
    needs = {"pipx": (install.venv,), "checkout": (install.folder,), "uv-tool": ()}.get(
        install.how, (install.python,)
    )
    if install.why or install.how == "homebrew" or not all(needs):
        return None
    names = ",".join(sorted(extras))
    try:
        if install.how == "checkout":  # run in the clone (`extras_checks` names it), the short line
            options = "".join(f" {o}" for o in install.options)  # what keeps it this venv (`_sync_options`)
            return "uv sync" + options + "".join(f" --extra {e}" for e in sorted(extras))
        if install.folder:
            requirement = f"--editable {_arg(f'{install.folder}[{names}]')}"
        else:
            requirement = _arg(f"openlogbook[{names}]{install.requirement}")
        options = "".join(f"{o} " for o in install.options)
        if install.how == "pipx":
            set_home = ""
            if install.home:  # PowerShell's right side is an expression: a path there is quoted
                home = _arg(install.home)
                set_home = f'$env:PIPX_HOME = "{install.home}"; ' if install.windows else f"PIPX_HOME={home} "
            return f"{set_home}pipx inject {options}{install.venv} {requirement}"
        if install.how == "uv-tool":
            python = f"--python {_arg(install.python)} " if install.python else ""
            return f"uv tool install --force {python}{options}{requirement}"
        if install.uv_pip:
            return f"uv pip install --python {_arg(install.python)} {requirement}"
        return f"{_command(install.python, install.windows)} -m pip install {requirement}"
    except NoLine:
        return None


def no_line(install: Install, extra: str) -> str:
    """Why there is no line for `extra`, and where to read how to add it, in one sentence."""
    if install.how == "homebrew":
        why = HOMEBREW
    else:
        why = f"doctor prints no line, since {install.why or 'it cannot prove one'}"
    return f'{why}; docs/install.md, "Optional extras", says how to add {extra}'


def extras_checks(
    installed: Callable[[str], bool] = module_installed, install: Install | None = None
) -> Iterator[Check]:
    how = install or detect_install()
    present = _present(installed, how)
    missing = [extra for extra, modules in EXTRAS if not any(installed(m) for m in modules)]
    for extra, modules in EXTRAS:
        found = [m for m in modules if installed(m)]
        if found:
            yield Check(f"extra:{extra}", "pass", f"{found[0].replace('_', '-')} is installed")
            continue
        wanted = " or ".join(m.replace("_", "-") for m in modules)
        yield Check(
            f"extra:{extra}", "warn", f"{wanted} not installed{_remedy(how, extra, present, missing)}"
        )


def _present(installed: Callable[[str], bool], how: Install) -> set[str]:
    """The extras this Logbook has: what its installer's receipt names, and each whose package is here."""
    return set(how.extras) | {
        extra for extra, modules in (*EXTRAS, *UNCHECKED_EXTRAS) if any(installed(m) for m in modules)
    }


def _remedy(how: Install, extra: str, present: set[str], missing: Sequence[str]) -> str:
    """What follows `<package> not installed` for `extra`: `: <line>`, with what the reader must know said
    before it (`; in the clone, <folder>: <line>`), so the line is the last thing and copies whole; or
    `: <why doctor proves none>`."""
    # pip and `pipx inject` add and remove nothing else, so they name the extra (and what pipx's receipt
    # names, which pipx writes back); `uv tool install --force` and a clone's `uv sync` keep only what they
    # are given, so they name every extra this Logbook has
    exact = how.how in ("uv-tool", "checkout")
    line = install_line(how, (present if exact else set(how.extras)) | {extra})
    if line is None:
        return f": {no_line(how, extra)}"
    notes = ""
    if exact and len(missing) > 1:
        notes += "; the line installs exactly the extras it names, so add any other one wanted to it"
    if how.how == "checkout":
        notes += f"; in the clone, {how.folder}"
    return f"{notes}: {line}"


def how_to_add(
    extra: str, installed: Callable[[str], bool] = module_installed, install: Install | None = None
) -> str:
    """How to add `extra` to this Logbook as it is installed, as a clause a message ends with: doctor's
    line for it (`pipx inject openlogbook "openlogbook[transcribe]==0.7.1"`, `in the clone, <folder>: uv
    sync --extra transcribe`), or why doctor proves none and where to read. What the Day page
    and Today say in place of the recording form, the same line as `doctor`'s `extra:` row."""
    how = install or detect_install()
    present = _present(installed, how)
    missing = [e for e, modules in EXTRAS if not any(installed(m) for m in modules)]
    return _remedy(how, extra, present, missing).removeprefix("; ").removeprefix(": ")


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
    fetches = policy.heard_fetch(root).max_tier > 0
    listed = ", ".join(_ceiling_text(c, fetches) for c in found) + _heard_text(root)
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


def export_day_check(root: Path) -> Check:
    """What `export --day` and `--days` may put in a folder (ADR 0026): the `folder` entry's ceiling, or,
    when the file names none, that no entry exists and the default tier 1 applies, and the entry that
    would raise it; a warn when the entry has expired, which counts as tier 0 (ADR 0022)."""
    try:
        named = policy.FOLDER_DESTINATION in policy.read(root)
        tier = policy.folder_ceiling(root)
    except policy.PolicyError as e:
        return Check("export-day", "fail", str(e))
    expired = policy.expired_on(root, policy.FOLDER_DESTINATION)
    if expired is not None:
        return Check(
            "export-day",
            "warn",
            f"the folder entry expired on {expired.isoformat()} and counts as tier 0, so export --day writes"
            f" no folder: write a new until in {policy.POLICY_FILE.as_posix()} or remove the entry",
        )
    if named:
        return Check(
            "export-day",
            "pass",
            f"export --day puts tiers up to {tier} in a folder, as the folder entry says",
        )
    return Check(
        "export-day",
        "pass",
        f"export --day puts tier {tier} alone in a folder: {policy.POLICY_FILE.as_posix()} names no folder"
        f' entry, so the default tier {tier} applies; {{"{policy.FOLDER_DESTINATION}": {{"max_tier": 2}}}}'
        " would let tier 2 go",
    )


def world_check(root: Path) -> Check:
    """What `export world` and the Library's `/world` may show (S9): the `world` entry's ceiling, or
    the default of tier 1 and the entry that would raise it when the file does not name it."""
    try:
        named = policy.WORLD_DESTINATION in policy.read(root)
        tier = policy.world_ceiling(root)
    except policy.PolicyError as e:
        return Check("world", "fail", str(e))
    if named:
        return Check("world", "pass", f"export world shows tiers up to {tier}, as the world entry says")
    return Check(
        "world",
        "pass",
        f"export world shows tier {tier} alone: {policy.POLICY_FILE.as_posix()} names no world entry;"
        f' {{"{policy.WORLD_DESTINATION}": {{"max_tier": 2}}}} would add the chapters',
    )


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
    """None unless a standing draft is above what the entry it was written under allows today: a
    day's the `dream` entry, a person's the `relationship` entry (`drafts.Allowed.of`)."""
    allowed = drafts.allowed(lb.root)
    people = allowed.of(drafts.UNIT_PERSON)
    if allowed.max_tier >= policy.TIERS[-1] and people.max_tier >= policy.TIERS[-1]:
        return None  # no draft is above tier 3
    lines = draft_lines(lb, state)
    retracted = retractions(line for line in lines if line.get("kind") == RETRACTION)
    above = drafts.withheld(lines, retracted, allowed)
    persons = drafts.withheld_people(lines, retracted, allowed)
    sealed = sum(
        1
        for line in lines
        if line.get("kind") == drafts.KIND
        and line.get("source") != videos.DRAFT_SOURCE  # a scene's draft: no crossing entry governs it
        and is_sealed(line)
        and not allowed.allows(line)
    )
    if not above and not sealed and not persons:
        return None
    found = ""
    if above or sealed:
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
        found += f"; {why}"
    if persons:
        named = ", ".join(
            f"{(line.get('payload') or {}).get('subject')} (#{line['seq']}, tier {line['tier']})"
            for line in persons
        )
        why = (
            people.reason
            if people.reason is not None
            else f"the {drafts.PERSON_ENTRY!r} entry allows max_tier {people.max_tier} now;"
            " `logbook dream person NAME` dreams them again under it"
        )
        said = (
            f"{len(persons)} person(s) with a draft above what the {drafts.PERSON_ENTRY} entry allows,"
            f" which no reader shows: {named}; {why}"
        )
        found = f"{found} · {said}" if found else said
    return Check("drafts", "warn", found)


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


def videos_check(lb: Logbook, state: str) -> Check | None:
    """The family's videos (RFC 0040): the files, what was fetched and inferred, the scenes proposed
    and confirmed, the cache against its cap. None when the record names no video and there is no
    cache; a warn when the cache is over its cap or its state file is not the shape."""
    lines = kind_lines(lb, state, (videos.KIND, videos.DRAFT_KIND, videos.ATTRIBUTION_KIND, RETRACTION))
    cache = videos.Cache(lb.root)
    known = any(line.get("kind") == videos.KIND for line in lines)
    if not known and not cache.dir.is_dir() and not lb.root.joinpath(*videos.STATE_FILE.parts).is_file():
        return None
    try:
        found = videos.counts(lb, lines)
    except videos.StateError as e:
        return Check("videos", "warn", f"{e}; delete it and `logbook videos fetch` writes it again")
    text = videos.counts_text(found)
    if found.used > found.cap:
        return Check("videos", "warn", f"{text}: over its cap; `logbook videos infer` empties it as it goes")
    return Check("videos", "pass", text)


def _heard_text(root: Path) -> str:
    """What `sync heard`'s fetches need, when `LOGBOOK_HEARD` names the feed and the policy lets
    none through (S9): the entry to write, named."""
    sources = {part.strip().casefold() for part in os.environ.get("LOGBOOK_HEARD", "").split(",")}
    found = policy.heard_fetch(root)
    if "feed" not in sources or found.max_tier:
        return ""
    return (
        f"; sync heard fetches no feed transcript until {policy.POLICY_FILE.as_posix()} has"
        f' {{"{policy.HEARD_DESTINATION}": {{"max_tier": 2, "{policy.FETCH}": true}}}}'
    )


def _ceiling_text(c: policy.Ceiling, fetches: bool = False) -> str:
    """`hermes 2`, `cloud-model 2 until 2026-12-31`, `mcp 2 write sign_day,note_day`,
    `dream 2 until 2026-12-31 model qwen2.5-7b-instruct`: the ceiling as it counts today, the write
    tools it lets through the door by name (ADR 0022) and the model the entry names (RFC 0036)."""
    when = f" until {c.until.isoformat()}" if c.until is not None and not c.expired else ""
    write = f" write {','.join(c.writes)}" if c.writes else ""
    model = f" model {c.model}" if c.model else ""
    fetch = f" {policy.FETCH}" if c.destination == policy.HEARD_DESTINATION and fetches else ""
    return f"{c.destination} {c.max_tier}{when}{write}{model}{fetch}"


#: the record's home (ADR 0022) is the machine that runs the scheduled syncs; the row says so in those
#: words, since `home` beside the Home place `setup` names read as that place (the stranger test)
NO_HOME = (
    "no machine runs the scheduled syncs yet: `logbook sync --install-schedule` on the one that keeps the"
    " record makes it that machine (ADR 0022)"
)
NOT_HOME = "the scheduled syncs run on {host}, not on this machine; writers belong on that one"


def home_check(root: Path) -> Check:
    """The `schedule` row: which machine runs the scheduled syncs (`state/home.json`, the record's home)."""
    try:
        found = home.read(root)
    except home.HomeError as e:
        return Check("schedule", "fail", str(e))
    if found is None:
        return Check("schedule", "pass", NO_HOME)
    if home.same_machine(found.host, home.hostname()):
        return Check(
            "schedule", "pass", f"this machine ({found.host}) runs the scheduled syncs, since {found.since}"
        )
    return Check("schedule", "warn", NOT_HOME.format(host=found.host))


#: before any record exists: what to do next, in a sentence (the exit code stays 1)
NO_RECORD = (
    "No record yet: run `logbook demo --out ~/Demo/Logbook` to try one, or `logbook setup` to start yours."
)
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
    if test is None:  # with no backup yet, `--restore-test` alone answers that there is no snapshot
        if backup.last_backup(lb.root):
            return Check("restore-test", "warn", f"no restore test yet: {RESTORE_TEST}")
        then = RESTORE_TEST.replace("` restores", "`, which restores", 1)
        return Check(
            "restore-test", "warn", f"no restore test yet: run `logbook backup DEST` once, then {then}"
        )
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


#: where the Tailscale apps put the command when it is not on the PATH: macOS's app, Windows' installer
TAILSCALE_APPS = (
    Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale"),
    Path("C:/Program Files/Tailscale/tailscale.exe"),
)
Finder = Callable[[str, str], str | None]  # (command, PATH) -> its path, as shutil.which


def _tailscale(command: str, path: str) -> str | None:
    """`tailscale` on `path`, or where an app put it; read from the disk, never run."""
    found = shutil.which(command, path=path)
    if found is not None:
        return found
    return next((str(app) for app in TAILSCALE_APPS if app.is_file()), None)


def phone_check(lb: Logbook, env: Mapping[str, str], found: Finder = _tailscale) -> Check:
    """`phone` in logbook.json: whether the owner's phone may write through the Library, and from
    which origin; the login shortened (`phone.shown`). A warn when it is not the shape, or when it
    names an origin and `found` finds no `tailscale` on the PATH; no PATH, nothing said of it."""
    meta = lb.meta
    problem = phone.problem(meta)
    if problem is not None:
        return Check(
            "phone", "warn", f"logbook.json phone lets nothing in: {problem}; `logbook setup phone` writes it"
        )
    setting = phone.of(meta)
    if setting is None:
        return Check(
            "phone",
            "pass",
            "the Library is written from this machine only; `logbook setup phone` lets your phone write too",
        )
    detail = f"your phone may write through the Library from {setting.origin} as {phone.shown(setting.login)}"
    path = env.get("PATH")
    if path and found("tailscale", path) is None:
        return Check(
            "phone",
            "warn",
            f"{detail}, but no tailscale is found on this machine, and Tailscale Serve is what carries it"
            " here",
        )
    return Check("phone", "pass", detail)


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
    install: Install | None = None,
) -> list[Check]:
    """Every check in print order. Without a record only the record failure and the extras. `install` is
    how this Logbook was installed, which the extras' lines follow (`detect_install` when None)."""
    checks: list[Check] = []
    if lb is None:
        checks.append(Check("record", "fail", NO_RECORD))
        checks.extend(extras_checks(installed, install))
        return checks
    checks.append(record_check(lb))
    state, sources = index_state(lb)
    checks.append(index_check(state))
    boundary = day_start_check(lb)
    if boundary is not None:
        checks.append(boundary)
    checks.append(owner_check(lb.root))
    agents = agents_check(lb, state)
    if agents is not None:
        checks.append(agents)
    checks.append(places_check(lb.root))
    checks.append(assets_check(lb.root))
    prints = voiceprints_check(lb, state)
    if prints is not None:
        checks.append(prints)
    checks.append(dates_check(lb, state, now or last_run.now()))
    checks.extend(extras_checks(installed, install))
    google = google_check(lb, env)
    if google is not None:
        checks.append(google)
    checks.extend(env_checks(lb, env, sources))
    checks.append(crossing_check(lb.root))
    checks.append(world_check(lb.root))
    checks.append(export_day_check(lb.root))
    checks.append(phone_check(lb, env))
    withheld = drafts_check(lb, state)
    if withheld is not None:
        checks.append(withheld)
    calls = synthesis_check(lb, state, now or last_run.now())
    if calls is not None:
        checks.append(calls)
    family = videos_check(lb, state)
    if family is not None:
        checks.append(family)
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


@dataclass(frozen=True)
class Missing:
    """A standing line whose attachment the store lacks: the line, and the digest it names."""

    id: str
    source: str
    kind: str
    at: str
    sha256: str


def missing_attachments(lb: Logbook, state: str) -> list[Missing]:
    """The standing lines whose attachment (`index.media_of`: the one `import attachments status`
    counts) is not under `attachments/`, in chain order: from the index when it is `current`, opened
    read-only, else from the month files; a sealed line this machine cannot open names no digest."""
    folder = lb.root / attachments.DIR
    found: list[Missing] = []
    if state == "current":
        db = sqlite3.connect(f"{lb.index_path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            rows = db.execute(
                "SELECT id, source, kind, at, media FROM lines WHERE media IS NOT NULL"
                f" AND id NOT IN ({index.RETRACTED}) ORDER BY seq"
            ).fetchall()
        finally:
            db.close()  # before anything could unlink it: Windows refuses to delete an open file
        named = [
            Missing(str(i), str(source), str(kind), str(at), str(media))
            for i, source, kind, at, media in rows
        ]
    else:
        retracted = retractions(line for line in lb.lines_unsorted() if line.get("kind") == RETRACTION)
        named = []
        for line in lb.lines_unsorted():
            if str(line.get("id")) in retracted:
                continue
            payload = _opened(lb, line).get("payload")
            media = index.media_of(payload) if isinstance(payload, dict) else None
            if media is not None:
                named.append(
                    Missing(str(line["id"]), str(line["source"]), str(line["kind"]), str(line["at"]), media)
                )
    for m in named:
        if attachments.is_digest(m.sha256) and not (folder / m.sha256).is_file():
            found.append(m)
    return found


def report_attachments(lb: Logbook, out: TextIO = sys.stdout) -> int:
    """`logbook doctor --attachments`: per source, the most first, the lines whose attachment the
    store lacks (id, kind, time, the digest's first twelve characters), then the count by source.
    Exit 0: a missing attachment is reported, never an error (SPEC §1.1)."""
    found = missing_attachments(lb, index_state(lb)[0])
    if not found:
        out.write(f"every file the lines name is in the store ({attachments.DIR}/)\n")
        return 0
    by_source: dict[str, list[Missing]] = {}
    for m in found:
        by_source.setdefault(m.source, []).append(m)
    ranked = sorted(by_source.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    for source, missing in ranked:
        out.write(
            f"{source}: {len(missing):,} line{'s' if len(missing) != 1 else ''} whose file the store lacks\n"
        )
        for m in missing:
            out.write(f"  {m.id}  {m.kind}  {m.at}  {m.sha256[:12]}…\n")
    listed = ", ".join(f"{source} {len(missing):,}" for source, missing in ranked)
    out.write(
        f"{len(found):,} line{'s' if len(found) != 1 else ''} name a file the store lacks: {listed}."
        " Adding the export that holds them again stores them (`logbook add transcript FOLDER`;"
        " `logbook import attachments import-backup` for a phone's); nothing was changed\n"
    )
    return 0


def report(checks: list[Check], out: TextIO = sys.stdout) -> int:
    """One line per check, a summary, and the exit status: 1 when any check failed."""
    width = max(len(c.name) for c in checks)
    for c in checks:
        out.write(f"{c.status:<4}  {c.name:<{width}}  {c.detail}\n")
    counts = {status: sum(c.status == status for c in checks) for status in ("pass", "warn", "fail")}
    out.write(f"{len(checks)} checks: {counts['pass']} pass, {counts['warn']} warn, {counts['fail']} fail\n")
    return 1 if counts["fail"] else 0
