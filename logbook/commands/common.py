"""Helpers every command family shares: the record's own words for a count, a path, a span, a
clock; the airports table; the import policy's disabled sources; the argparse hook a family's
`<command>_arguments` functions take. Nothing here is a command."""

from __future__ import annotations

import argparse
import inspect
import os
import sys
from datetime import date, datetime
from pathlib import Path, PurePath
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from .. import assets, flights, policy
from ..store import Logbook

if TYPE_CHECKING:
    from .. import adapters


type Subparsers = argparse._SubParsersAction[argparse.ArgumentParser]  # what `add_subparsers` returns


def _under_home(path: Path) -> str:
    """`~/Logbook` for a path inside the home directory, else the path as given: what is printed
    (and recorded in a demo) never spells the user's name."""
    try:
        return str(PurePath("~") / path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def _registry(lb: Logbook, command: str) -> list[assets.Asset]:
    """The record's asset registry for an adapter that takes `assets`; a broken file exits 2."""
    try:
        return assets.read(lb.root)
    except assets.AssetError as e:
        print(f"{command}: {e}", file=sys.stderr)
        sys.exit(2)


def _disabled(lb: Logbook) -> dict[str, str]:
    """The disabled sources of `policy/import.json` by adapter NAME (`books` stands for `apple-books`,
    `health` for `apple-health`, as in `adapters.ALIASES`); a malformed file exits 2 naming it."""
    from .. import adapters

    try:
        listed = policy.disabled(lb.root)
    except policy.PolicyError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)
    return {adapters.ALIASES.get(name, name): reason for name, reason in listed.items()}


def _say_disabled(lb: Logbook, name: str) -> bool:
    """True, having said so, when the owner disabled the source `name` in `policy/import.json`."""
    from .. import adapters

    reason = _disabled(lb).get(adapters.ALIASES.get(name, name))
    if reason is None:
        return False
    print(f"{name}: disabled ({reason}); skipped — {policy.import_path(lb.root)}")
    return True


def _takes(adapter: adapters.Adapter | adapters.LiveAdapter, option: str, live: bool = False) -> bool:
    """Whether the adapter's `run` (or, for `sync`, its `pull`: `live`) accepts the optional keyword:
    `counts` (a dict to tally what it skipped), `timezone` (the record's zone, for a source whose
    times are floating), `store` (puts bytes in the attachment store), `store_file` (puts a file
    there, streamed), `lookup` (the id of a line by
    source and raw_id), `resolved` (the refs the record resolves, `{(kind, value): entity id}`), `failed`
    (a live adapter's list for the feeds it could not read), `progress` (a file adapter's own
    reporter, every 10,000 items with the bytes read), `cursor` (the inbox manifest's, so a long
    import resumes), or one of
    `assets` (the asset registry, ADR 0018), `places` (the record's named places), `report` (lines
    `add` prints after the counts), `listen_s`, `notice` and `status` (a source that listens
    to a stream, `ais`), or one of `add`'s own options. A module can be both a file and a live
    adapter (`ais`), so `sync` asks about `pull`, never `run`."""
    from .. import adapters

    if live and isinstance(adapter, adapters.LiveAdapter):
        return option in inspect.signature(adapter.pull).parameters
    if isinstance(adapter, adapters.Adapter):
        return option in inspect.signature(adapter.run).parameters
    pulls: adapters.LiveAdapter = adapter
    return option in inspect.signature(pulls.pull).parameters


def _progress(n: int, elapsed: float) -> None:
    print(f"  {n:,} lines in {elapsed:,.0f}s", file=sys.stderr)


EN_DASH = "\u2013"  # between the two clocks of a time span


EM_DASH = "\u2014"  # heads an asset's section of `derive stays`


def _csv(value: str | None) -> list[str] | None:
    """A comma-separated flag as a list, None when the flag was not given."""
    if value is None:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def _airports(given: str | None) -> flights.Airports:
    """The airports table with the override `--airports` names, else `LOGBOOK_AIRPORTS`, else none;
    a file that will not read exits 2 naming the line."""
    path = given or os.environ.get(flights.AIRPORTS_ENV, "").strip() or None
    try:
        return flights.Airports.load(Path(path).expanduser() if path else None)
    except (OSError, ValueError) as e:
        print(f"add: --airports: {e}", file=sys.stderr)
        sys.exit(2)


def _is_rfc3339(value: str) -> bool:
    try:
        return datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False


def _today() -> str:
    """The local day, as one function so a test can pin it."""
    return date.today().isoformat()


def _print_target(a: argparse.Namespace, command: str) -> Path:
    """`--print` writes the paper edition of a Year or a Trip (one HTML document for A4 and US
    Letter) to `--html PATH`: the path, its folder made; exit 2 without `--html`, before anything
    is read."""
    if not a.html:
        print(
            f"{command}: --print writes the paper edition where --html PATH says; give both", file=sys.stderr
        )
        sys.exit(2)
    out = Path(a.html)
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


ARROW = "\u2192"  # →


def _clock(at: str, tz: ZoneInfo) -> str:
    return datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(tz).strftime("%H:%M")


def _plural(n: int, noun: str, plural: str | None = None) -> str:
    return f"{n:,} {noun if n == 1 else plural or noun + 's'}"


def _duration_text(seconds: int) -> str:
    minutes = round(seconds / 60)
    if minutes < 1:
        return "< 1 min"
    hours, minutes = divmod(minutes, 60)
    if not hours:
        return f"{minutes} min"
    return f"{hours} h" if not minutes else f"{hours} h {minutes} min"


def _distance_text(metres: float) -> str:
    if metres < 1000:
        return f"{round(metres)} m"
    km = metres / 1000
    return f"{km:.1f} km" if km < 100 else f"{round(km)} km"
