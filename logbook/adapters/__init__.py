"""Adapters: one per source, export in → observations out (ARCHITECTURE layer 2, ADR 0012).

Two kinds share one registry. A *file* adapter reads an export you already hold:

    NAME: str                                   # the `source` it writes, e.g. "dawarich"
    sniff(path) -> bool                         # "is this file (or folder) mine?" — cheap, never raises
    run(path, since=None) -> Iterator[dict]     # line drafts: at, end, tz, source, kind, tier, payload

`run` may also take an optional `counts: dict[str, int]`; when it does, `logbook add` passes one and
reports what the adapter skipped (`skipped_no_timestamp`, `skipped_bad_coordinates`, `skipped_no_ref`, ...;
the phrases live in `cli.SKIP_PHRASES`). It may also take an optional `timezone: str`, the record's IANA
zone, for a source whose times are floating (an all-day calendar entry has a day, not an instant), or
`assets: list[Asset]`, the record's asset registry (`assets.json`, ADR 0018), for a source that reports
the positions of the owner's boats and aircraft rather than the owner's own. A source read front to back
from one big file (`mail`) may take `progress(items, bytes_read, elapsed)`, which `add` prints with the
rate, and `cursor`, the inbox manifest's (`logbook.inbox.Cursor`): `cursor.start(file)` is the byte
offset to begin at and `cursor.reached(file, ordinal, offset)` is told, before every draft, how far the
file is read, so an interrupted import resumes at the last draft the record holds; `places: list[Place]`, the
record's named places (`places.json`), for a source that positions a place by its name; or
`report: list[str]`, lines `logbook add` prints after the counts, for what a count cannot say (the
names of the places `passages` could not position).

A *live* adapter pulls from a service you run, and only when `logbook sync <NAME>` asks it to:

    NAME: str
    ENV: tuple[str, ...]                        # the environment variables it reads
    configure(env) -> Config | None             # None when one of them is absent
    pull(config, since=None) -> Iterator[dict]  # the same line drafts, oldest first
    watermark(draft) -> str | None              # the `since` that would pull this draft again

and optionally:

    resume(config, mark) -> str                 # where to start given a watermark; its presence also
                                                # makes a first sync start from the record's newest
                                                # line of this source and KIND
    UNIT: str                                   # what the progress lines count ("assets" if absent)
    group(draft) -> str                         # `sync` then reports seen and new per group (a calendar)
    GROUP_MARKS: bool                           # with `group`: `sync` also keeps a watermark per group
                                                # in the state file (`groups`), one per tracked asset

`pull` may also take `timezone: str` (the record's IANA zone, as a file adapter's `run` may), `assets`
(the registry, as `run` may) and `failed: list[str]`: a source made of several feeds appends one line per
feed it could not read and still yields the others' drafts; `sync` prints each, keeps the watermark and
exits 1.

A source can have both kinds under one NAME (`dawarich` reads an export and pulls live; `imessage`
reads a phone backup's sms.db and the Mac's own chat.db); they write the same lines, so either
dedupes the other. A live source need not be a service: `imessage` reads a file on this machine and
`ENV` names only optional overrides, so its `configure` never returns None. Nor need it share the
NAME: `gcal` pulls Google Calendar's feeds through the `ics` reader and writes `ics` lines, so a
feed and an export of the same calendar dedupe each other.

`since` and the watermark are in the *source's* clock (when it received or last changed the item),
not the event's: `logbook sync` stores the largest watermark of a completed pull and passes it back
as `since`, so an old photo uploaded tomorrow is picked up by tomorrow's sync. A line's `at` is the
event time regardless.

Built-in adapters live in this package. Third-party ones are separate packages that register the
`logbook.adapters` entry point. `all_adapters()` returns both kinds; `find(path)` asks only file
adapters; `named(name)` resolves a file adapter by NAME (or an alias: `flights` is `flighty`) and
`live(name)` a live one. No file adapter makes a network call, and a live adapter makes them only
inside `pull`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from importlib import import_module
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

ENTRY_POINT_GROUP = "logbook.adapters"
BUILT_IN = (
    "dawarich",
    "immich",
    "dawarich_live",
    "takeout.location",
    "takeout.photos",
    "takeout.keep",
    "takeout.tasks",
    "takeout.chrome",
    "takeout.youtube",
    "takeout.pay",
    "takeout.chat",
    "takeout.meet",
    "takeout.access_log",
    "takeout.activity",
    "takeout.contacts",
    "takeout.maps",
    "takeout.home",
    "ios_contacts",
    "whatsapp",
    "whatsapp_contacts",
    "imessage",
    "imessage_live",
    "ios_notes",
    "ios_calendar",
    "ios_calls",
    "ios_wallet",
    "easypark",
    "wispr_flow",
    "flighty",
    "apple_health",
    "ics",
    "transcript",
    "granola",
    "gcal",
    "ais",
    "adsb",
    "mail",
    "safari",
    "shazam",
    "apple_podcasts",
    "pocket",
    "apple_reminders",
    "copilot",
    "splitwise",
    "beeper",
    "line",
    "twitter",
    "apple_books",
    "voice_memos",
    "apple_photos",
    "withings",
    "myfitnesspal",
    "sbb",
    "passages",
    "spotify",
    "apple_music",
    "screentime",
    "weather",
)


@runtime_checkable
class Adapter(Protocol):
    """A file adapter."""

    NAME: str

    def sniff(self, path: Path) -> bool: ...

    def run(self, path: Path, since: str | None = None) -> Iterator[dict[str, Any]]: ...


@runtime_checkable
class LiveAdapter(Protocol):
    NAME: str
    ENV: tuple[str, ...]

    def configure(self, env: Mapping[str, str]) -> object | None: ...

    def pull(
        self,
        config: Any,
        since: str | None = None,
        progress: Callable[[int, float], None] | None = None,
        counts: dict[str, int] | None = None,
    ) -> Iterator[dict[str, Any]]: ...

    def watermark(self, draft: dict[str, Any]) -> str | None: ...


def all_adapters() -> list[Adapter | LiveAdapter]:
    """Built-ins first, then entry points; one file adapter and one live adapter per NAME (the first
    registered of each kind wins), so a source can be both read from an export and pulled live."""
    found: list[Adapter | LiveAdapter] = []
    for name in BUILT_IN:
        found.append(import_module(f"{__name__}.{name}"))
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        module = ep.load()
        if isinstance(module, Adapter | LiveAdapter):
            found.append(module)
    seen: set[tuple[bool, str]] = set()
    unique: list[Adapter | LiveAdapter] = []
    for a in found:
        key = (isinstance(a, LiveAdapter), a.NAME)
        if key not in seen:
            seen.add(key)
            unique.append(a)
    return unique


def file_adapters() -> list[Adapter]:
    return [a for a in all_adapters() if isinstance(a, Adapter)]


def live_adapters() -> list[LiveAdapter]:
    return [a for a in all_adapters() if isinstance(a, LiveAdapter)]


def find(path: Path) -> Adapter | None:
    """The first registered file adapter that recognises `path`, or None."""
    return next((a for a in file_adapters() if a.sniff(Path(path))), None)


TAKEOUT = (
    "location",
    "photos",
    "keep",
    "tasks",
    "chrome",
    "youtube",
    "pay",
    "chat",
    "meet",
    "access-log",
    "activity",
    "contacts",
    "maps",
    "home",
)
ALIASES = {  # `add flights <csv>` (RFC 0013); `add health`, `add calls`, … as `import-backup --only`
    "flights": "flighty",
    "health": "apple-health",
    "calls": "ios-calls",
    "contacts": "ios-contacts",
    "calendar": "ios-calendar",
    "notes": "ios-notes",
    "wallet": "ios-wallet",
    "wispr": "wispr-flow",
    "reminders": "apple-reminders",
    "books": "apple-books",
    "photos": "apple-photos",
    # `add takeout-<product> <folder>`: the Google Takeout sub-adapters by their short names
    **{f"takeout-{short}": f"google-takeout-{short}" for short in TAKEOUT},
    "music": "apple-music",
}


def named(name: str) -> Adapter | None:
    """The file adapter called `name` (or by an alias in `ALIASES`), or None."""
    name = ALIASES.get(name, name)
    return next((a for a in file_adapters() if name == a.NAME), None)


def live(name: str) -> LiveAdapter | None:
    """The live adapter called `name`, or None."""
    return next((a for a in live_adapters() if name == a.NAME), None)
