"""The live sources: `sync`, `sources` and `assets`."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from ..contrib import asset_status, gaps, home, schedule
from ..core import assets, places, policy, reading, stays
from ..core import weather as weather_reader
from ..core.export import day_range, parse_day
from ..core.store import Logbook, now_utc
from .common import (
    EN_DASH,
    Subparsers,
    _disabled,
    _is_rfc3339,
    _plural,
    _registry,
    _say_disabled,
    _takes,
    _today,
)
from .skips import _report_skipped

if TYPE_CHECKING:
    from ..contrib import adapters


def _page_progress(
    unit: str,
    status: Mapping[str, Any] | None = None,
    total: int | None = None,
    since: str | None = None,
    walks: bool = False,
) -> Callable[[int, float], None]:
    """One line per page pulled from a live source, dry runs included, counting `unit`. A source
    that listens (`ais`) calls it once a minute and keeps a tally per asset in `status["heard"]`,
    which the line carries in parentheses. A source that `walks` a library says `x of N` against
    the total it asked the server for, `x since <since>` on an incremental pull, and `x so far
    (total unknown)` when the server would not say: never a number that reads as the total."""

    def report(n: int, elapsed: float) -> None:
        heard = status.get("heard") if status is not None else None
        per_asset = f" ({', '.join(f'{k} {v:,}' for k, v in sorted(heard.items()))})" if heard else ""
        if walks and since is not None:
            head, tail = f"{n:,} {unit} since {since}", ""
        elif walks and total is None:
            head, tail = f"{n:,} {unit} so far", " (total unknown)"
        elif walks:
            head, tail = f"{n:,} of {total:,} {unit}", ""
        else:
            head, tail = f"{n:,} {unit}", ""
        print(f"  {head} in {elapsed:,.0f}s{tail}{per_asset}", file=sys.stderr)

    return report


SLOW_LAST = ("immich",)  # a walk over a photo library takes hours: `--all` runs it after the rest


def _all_order(live: Iterable[adapters.LiveAdapter]) -> list[adapters.LiveAdapter]:
    """The order `sync --all` runs the sources in: the quick ones as registered, the slow ones
    (`SLOW_LAST`) after them, so a photo walk never holds up the messages, the calendar, the
    positions or the weather."""
    quick = [a for a in live if a.NAME not in SLOW_LAST]
    slow = [a for a in live if a.NAME in SLOW_LAST]
    return quick + slow


def _window_text(seconds: float) -> str:
    """A window in words: `45 s`, `5 min`, `2 h 12 min`."""
    hours, rest = divmod(round(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    parts = [f"{hours} h"] if hours else []
    if minutes:
        parts.append(f"{minutes} min")
    if secs or not parts:
        parts.append(f"{secs} s")
    return " ".join(parts)


def sync_arguments(sub: Subparsers) -> None:
    """`logbook sync`."""
    s = sub.add_parser(
        "sync",
        help="pull new items from a live source; --all for every configured one",
        description="pull new items from a live source (immich, dawarich, imessage, gcal, granola, ais, adsb,"
        " weather); safe to re-run; --all for every configured source, --install-schedule for twice a day."
        " immich: the first run walks the whole library and says how many assets the server holds before it"
        " starts, then counts `x of N`; a walk interrupted (Ctrl-C, a lost connection, a server error) is"
        " checkpointed in state/immich.json and the next run resumes where it stopped instead of walking"
        " the library again; --restart walks it from the beginning",
    )
    s.add_argument(
        "name",
        nargs="?",
        help="the source: immich, dawarich, imessage (this Mac's Messages), gcal (Google Calendar), granola,"
        " ais (your vessels via aisstream.io), adsb (your aircraft via OpenSky), weather (the places of your"
        " days, one decimal of latitude, from Open-Meteo)",
    )
    s.add_argument(
        "--all",
        action="store_true",
        help="every configured live source in turn (one with its LOGBOOK_* variables set), a failure in one"
        " never stopping the next; one summary line per source; exit 1 when any failed",
    )
    s.add_argument(
        "--install-schedule",
        action="store_true",
        help="run `sync --all` at 07:00 and 19:00 local: a launchd agent (macOS) or a systemd user timer"
        " (Linux), printed before it is written under your LaunchAgents or systemd user directory",
    )
    s.add_argument("--uninstall-schedule", action="store_true", help="remove that agent or timer")
    s.add_argument(
        "--since",
        metavar="RFC3339",
        help="pull from here instead of the stored watermark (weather: a local day, YYYY-MM-DD)",
    )
    s.add_argument(
        "--listen",
        metavar="SECONDS",
        help="ais: listen this long, then write (default: LOGBOOK_AISSTREAM_LISTEN_S, 60 s)",
    )
    s.add_argument(
        "--until",
        metavar="HH:MM",
        help="ais: listen until the record's local clock next shows this time, then write;"
        " weather: the last local day to cover, YYYY-MM-DD (default yesterday)",
    )
    s.add_argument("--dry-run", action="store_true", help="show what would be appended; write nothing")
    s.add_argument(
        "--restart",
        action="store_true",
        help="immich: walk the whole library from the beginning, whatever the watermark and the checkpoint"
        " of an interrupted walk say (the record still refuses what it already holds)",
    )
    s.set_defaults(fn=cmd_sync)


def cmd_sync(a: argparse.Namespace) -> None:
    """`sync <source>`: pull from a live source since its stored watermark (or --since), append,
    advance the watermark. `sync --all`: every configured source in turn (`_sync_all`). `sync
    --install-schedule` / `--uninstall-schedule`: `sync --all` twice a day by the machine's own
    scheduler (`_sync_schedule`, `logbook.contrib.schedule`)."""
    from ..contrib import adapters

    if a.install_schedule or a.uninstall_schedule:
        _sync_schedule(a)
        return
    if a.all:
        _sync_all(a)
        return
    if a.name is None:
        known = ", ".join(x.NAME for x in adapters.live_adapters()) or "none"
        print(f"sync: say a source or --all, e.g. `logbook sync immich` (known: {known})", file=sys.stderr)
        sys.exit(2)
    _sync_source(a)


def _sync_all(a: argparse.Namespace) -> None:
    """Every live source that is configured — at least one of its `ENV` variables set, and its
    `configure` taking the environment — pulled in turn, each from its own watermark; a source the
    owner disabled or one with no variable set is skipped and said so. A failure in one (its exit
    status, or an error its adapter let through) never stops the next: it is said on stderr as a
    single run says it, and the run goes on. At the end one summary line per source — `ok`,
    `failed (status N)`, `skipped (why)` — and exit 1 when any failed. A Ctrl-C while a source
    listens to a stream (ais, status 130) ends the run there: the sources not reached are listed as
    `not run` and the status is 130. `--dry-run` passes through; `--since`, `--listen`, `--until` and
    `--restart` are a single source's and refused. The quick sources run first and the slow ones
    (`SLOW_LAST`: a photo library walk) last, and the first line says the order."""
    from ..contrib import adapters

    if a.name is not None:
        print(
            f"sync: --all takes no source name; run `logbook sync {a.name}` for that one alone",
            file=sys.stderr,
        )
        sys.exit(2)
    for flag, value in (
        ("--since", a.since),
        ("--listen", a.listen),
        ("--until", a.until),
        ("--restart", a.restart or None),
    ):
        if value is not None:
            print(f"sync: --all takes no {flag}: each source starts from its own watermark", file=sys.stderr)
            sys.exit(2)
    lb = Logbook.find()
    disabled = _disabled(lb)
    live = _all_order(adapters.live_adapters())
    print(_all_order_text(live))
    results: list[tuple[str, str]] = []
    interrupted = False
    for adapter in live:
        name = adapter.NAME
        if interrupted:
            results.append((name, "not run"))
            continue
        if name in disabled:
            _say_disabled(lb, name)
            results.append((name, "skipped (disabled)"))
            continue
        reason = _unconfigured(adapter)
        if reason is not None:
            print(f"{name}: {reason}; skipped")
            results.append((name, f"skipped ({reason})"))
            continue
        status = 0
        try:
            _sync_source(argparse.Namespace(**{**vars(a), "name": name, "all": False}))
        except SystemExit as e:
            status = e.code if isinstance(e.code, int) else 1
        except Exception as e:
            print(f"sync: {name}: {type(e).__name__}: {e}", file=sys.stderr)
            status = 1
        if status == 130:  # Ctrl-C while the source listened: the owner wants out, not the next source
            interrupted = True
            results.append((name, "interrupted"))
            continue
        results.append((name, "ok" if status == 0 else f"failed (status {status})"))
    ok = sum(1 for _, r in results if r == "ok")
    failed = sum(1 for _, r in results if r.startswith("failed"))
    skipped = sum(1 for _, r in results if r.startswith("skipped"))
    print(
        f"sync --all: {_plural(len(results), 'source')}: {ok} ok, {failed} failed, {skipped} skipped"
        + (", interrupted" if interrupted else "")
    )
    width = max((len(name) for name, _ in results), default=0)
    for name, result in results:
        print(f"  {name:<{width}}  {result}")
    if interrupted:
        sys.exit(130)
    if failed:
        sys.exit(1)


def _all_order_text(live: list[adapters.LiveAdapter]) -> str:
    """`sync --all`'s first line: the order, and why the slow source comes last."""
    quick = [a.NAME for a in live if a.NAME not in SLOW_LAST]
    slow = [a.NAME for a in live if a.NAME in SLOW_LAST]
    if not slow:
        return f"running {', '.join(quick)}"
    return (
        f"running {', '.join(quick)}, then {', '.join(slow)} last"
        " (a photo library walk can take hours and never holds up the others)"
    )


def _unconfigured(adapter: adapters.LiveAdapter) -> str | None:
    """Why `sync --all` leaves a source out, or None when it is configured: none of its variables
    set (`LOGBOOK_IMMICH_URL, LOGBOOK_IMMICH_KEY not set`), one still missing (`set
    LOGBOOK_IMMICH_KEY`), or a value its `configure` refuses. A source whose variables are all
    optional (`imessage`) joins the run once the owner sets one of them."""
    if not adapter.ENV:
        return "takes no variables; run it by name"
    if not any(os.environ.get(v, "").strip() for v in adapter.ENV):
        return f"{', '.join(adapter.ENV)} not set"
    try:
        config = adapter.configure(os.environ)
    except ValueError as e:
        return str(e)
    if config is None:
        missing = [v for v in adapter.ENV if not os.environ.get(v, "").strip()]
        return f"set {' and '.join(missing)}"
    return None


def _sync_schedule(a: argparse.Namespace) -> None:
    """`sync --install-schedule`: a launchd agent (macOS) or a systemd user timer (Linux) running
    `logbook sync --all` at 07:00 and 19:00 local, the plist or units printed before they are
    written, nothing written outside that one directory, then handed to the scheduler (or, when it
    is not on PATH, the command to run said). `--uninstall-schedule`: the reverse. The record found
    now is the one the agent is pointed at (`LOGBOOK_HOME`). Installing names this machine the
    record's home in `state/home.json` (ADR 0022: the one machine that writes; `doctor` reads it);
    uninstalling leaves that as it is, since home moves by copying the record, not by a flag."""
    if a.install_schedule and a.uninstall_schedule:
        print("sync: --install-schedule or --uninstall-schedule, not both", file=sys.stderr)
        sys.exit(2)
    flag = "--install-schedule" if a.install_schedule else "--uninstall-schedule"
    others = (a.name, a.all or None, a.dry_run or None, a.since, a.listen, a.until, a.restart or None)
    if any(x is not None for x in others):
        print(f"sync: {flag} takes no source and no other option", file=sys.stderr)
        sys.exit(2)
    lb = Logbook.find()
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    try:
        plan = schedule.plan(
            schedule.system(), Path.home(), sys.executable, lb.root, Path(xdg).expanduser() if xdg else None
        )
    except schedule.ScheduleError as e:
        print(f"sync: {flag}: {e}", file=sys.stderr)
        sys.exit(2)
    if a.uninstall_schedule:
        if not any(path.exists() for path in plan.files):
            print(f"no schedule installed ({plan.directory})")
            return
        problem = schedule.run(plan.deactivate, plan.tool, print)
        for path in schedule.uninstall(plan):
            print(f"removed {path}")
        if problem is not None:
            print(f"sync: {flag}: {problem}", file=sys.stderr)
            sys.exit(1)
        return
    schedule.install(plan, print)
    for text in schedule.summary(plan):
        print(text)
    now, before = home.write(lb.root)
    moved = (
        f" (it was {before.host})"
        if before is not None and not home.same_machine(before.host, now.host)
        else ""
    )
    print(f"home: this machine ({now.host}) is the record's home since {now.since}{moved}; state/home.json")
    problem = schedule.run(plan.activate, plan.tool, print)
    if problem is not None:
        print(f"sync: {flag}: {problem}", file=sys.stderr)
        sys.exit(1)


def _sync_source(a: argparse.Namespace) -> None:
    """One source's pull, under the record's writer lock for the whole of it, the walk included
    (#234): a second writer waits or, with --no-wait, refuses. A dry run appends nothing and takes
    no lock."""
    if a.dry_run:
        _sync_one(a)
        return
    with Logbook.find().writer():
        _sync_one(a)


def _sync_one(a: argparse.Namespace) -> None:
    """Pull from a live source since its stored watermark (or --since), append, advance the watermark.
    The watermark is the source's own clock (adapter.watermark), not the event time, so late uploads of
    old items are still picked up. It lives in <root>/state/<name>.json — bookkeeping, not the record."""
    from ..contrib import adapters
    from ..contrib.adapters import ais
    from ..contrib.adapters import weather as weather_adapter

    adapter = adapters.live(a.name)
    if adapter is None:
        known = ", ".join(x.NAME for x in adapters.live_adapters()) or "none"
        print(f"sync: no live source named {a.name!r} (known: {known})", file=sys.stderr)
        sys.exit(2)
    if adapter.NAME == weather_adapter.NAME:  # a window of local days from the record, not a watermark pull
        _sync_weather(a)
        return
    listens = _takes(adapter, "listen_s", live=True)  # a source that listens to a stream for a window (ais)
    listen_s = _listen_flag(a, listens)
    lb = Logbook.find()
    if _say_disabled(lb, adapter.NAME):  # before the variables: a switched-off source needs none
        return
    try:
        config = adapter.configure(os.environ)
    except ValueError as e:
        print(f"sync: {a.name}: {e}", file=sys.stderr)
        sys.exit(2)
    if config is None:
        missing = [v for v in adapter.ENV if not os.environ.get(v, "").strip()]
        print(f"sync: {a.name}: set {' and '.join(missing)}", file=sys.stderr)
        sys.exit(2)
    if a.since is not None and not _is_rfc3339(a.since):
        print(
            f"sync: --since must be RFC3339 UTC, e.g. 2026-03-01T00:00:00Z, not {a.since!r}", file=sys.stderr
        )
        sys.exit(2)
    state_path = lb.root / "state" / f"{a.name}.json"
    stored = _read_state(state_path).get("since")
    since, resumed_from_record = _start(lb, adapter, config, a.since, stored)
    walks = _takes(adapter, "walk", live=True)
    restart = bool(getattr(a, "restart", False))  # `setup` builds its own namespace without the flag
    if restart and not walks:
        print(f"sync: --restart is for a source that walks a library (immich), not {a.name}", file=sys.stderr)
        sys.exit(2)
    if restart and a.since is not None:
        print("sync: give --restart (the whole library again) or --since, not both", file=sys.stderr)
        sys.exit(2)
    if restart:  # the whole library again, whatever the watermark says; the checkpoint goes too
        since, resumed_from_record = None, None
    seen: dict[str, Any] = {
        "count": 0,
        "first": None,
        "last": None,
        "watermark": None,
        "provenance": Counter(),
        "kinds": Counter(),
    }
    counts: dict[str, int] = {}
    unit = str(getattr(adapter, "UNIT", "assets"))
    item = unit.removesuffix("s")  # one of them: a point, a message, an asset
    options: dict[str, Any] = {}
    total: int | None = None
    walk: WalkState | None = None
    if walks:  # before the walk: how many there are, how many are here, and where it resumes
        total = _total(adapter, config)
        with lb.index() as idx:
            in_record = next((int(s["lines"]) for s in idx.sources() if s["source"] == adapter.NAME), 0)
        on_server = "total unknown" if total is None else f"{total:,} {unit} on the server"
        print(f"{a.name}: {on_server}, {in_record:,} already in the record")
        walk = WalkState(state_path, since, restart=restart)
        options["walk"] = walk
        for text in walk.notices(unit, total):
            print(f"  {text}", file=sys.stderr)
        if walk.checkpoint is not None and walk.checkpoint.get("watermark"):
            seen["watermark"] = str(walk.checkpoint["watermark"])
    if _takes(adapter, "store", live=True) and not a.dry_run:
        options["store"] = lb.attach
    if _takes(adapter, "lookup", live=True):
        options["lookup"] = _lookup(lb)
    if _takes(adapter, "timezone", live=True):
        options["timezone"] = lb.meta["timezone"]
    failed: list[str] = []  # one line per feed the adapter could not read, the others still pulled
    if _takes(adapter, "failed", live=True):
        options["failed"] = failed
    if _takes(adapter, "assets", live=True):
        options["assets"] = _registry(lb, "sync")
    status: dict[str, Any] = {}  # what a listening source reports: messages per asset, reconnects, Ctrl-C
    if listens:
        zone = ZoneInfo(str(lb.meta["timezone"]))
        if a.until is not None:
            try:
                listen_s = ais.seconds_until(a.until, zone, datetime.now(zone))
            except ValueError as e:
                print(f"sync: --until {e}", file=sys.stderr)
                sys.exit(2)
            print(
                f"  listening until {a.until.strip()} {zone.key} ({_window_text(listen_s)})", file=sys.stderr
            )
        else:
            listen_s = listen_s if listen_s is not None else float(getattr(config, "listen_s", 0.0))
            print(f"  listening for {_window_text(listen_s)}", file=sys.stderr)
        options["listen_s"] = listen_s
        options["status"] = status
        options["notice"] = lambda text: print(f"  {text}", file=sys.stderr)
    group: Callable[[dict[str, Any]], str] | None = getattr(adapter, "group", None)
    seen["groups"] = Counter()
    seen["group_marks"] = {}  # the largest watermark per group, kept in the state when GROUP_MARKS
    already_in_group: Counter[str] = Counter()
    progress = _page_progress(unit, status, total=total, since=since, walks=walks)
    drafts = _watch(
        adapter.pull(config, since, progress=progress, counts=counts, **options),
        adapter.watermark,
        seen,
        group,
    )
    try:
        if a.dry_run:
            for _ in drafts:
                pass
        else:
            n = lb.append_many(  # the page lines above are the progress; one stream, not two
                drafts,
                skipped=(lambda d: already_in_group.update([group(d)])) if group else None,
                committed=walk.commit if walk is not None else None,
            )
    except (OSError, ValueError) as e:  # urllib's errors are OSErrors, a malformed page a ValueError;
        print(f"sync: {a.name}: {e}", file=sys.stderr)  # what was pulled before is checkpointed
        sys.exit(1)
    if walk is not None and not a.dry_run:
        walk.finish()  # the walk completed: the checkpoint goes, the watermark below takes over
    for problem in failed:
        print(f"sync: {a.name}: {problem}", file=sys.stderr)
    where = f"since {since}" if since else "from the beginning"
    pending = counts.get("pending", 0)
    skipped = {k: v for k, v in counts.items() if k != "pending"}
    if resumed_from_record is not None:
        print(
            f"  starting from the record's newest {a.name} {item}, {resumed_from_record}, less the lookback"
        )
    if a.dry_run:
        print(f"{a.name}: {seen['count']:,} lines {where} (dry run, nothing written)")
        if seen["count"]:
            print(f"  first {seen['first']}  last {seen['last']}  watermark {seen['watermark'] or '-'}")
            for provenance, count in sorted(seen["provenance"].items()):
                if provenance != "-":
                    print(f"  {provenance}: {count}")
            if len(seen["kinds"]) > 1:
                for kind, count in sorted(seen["kinds"].items()):
                    print(f"  {kind}: {count}")
        for name, count in seen["groups"].items():
            print(f"  {name}: {count} seen")
        _report_skipped(skipped)
        _report_pending(pending)
        _report_listening(status)
        if failed:
            sys.exit(1)
        if status.get("interrupted"):
            sys.exit(130)
        return
    mark = seen["watermark"]
    if walk is not None and mark is not None and mark > walk.started:
        mark = walk.started  # never past the moment the walk began: what changed since is pulled next time
    if failed:  # a feed that was not read may hold changes older than the lookback: try again from here
        kept = f" (kept: {len(failed)} {'feed' if len(failed) == 1 else 'feeds'} failed)"
        mark = stored
    elif mark is not None and (stored is None or mark > stored):  # a watermark never moves backwards
        kept = ""
        _write_state(state_path, _state(state_path, adapter, mark, seen))
    else:
        kept = ""
        mark = stored
    already = seen["count"] - n
    print(
        f"{a.name}: {n:,} new lines of {seen['count']:,} seen {where}"
        + (f" ({already:,} already in the record)" if already else "")
        + f"; watermark {mark or since or '-'}{kept}"
    )
    for name, count in seen["groups"].items():
        print(f"  {name}: {count - already_in_group[name]} new of {count} seen")
    _report_skipped(skipped)
    _report_pending(pending)
    _report_listening(status)
    if failed:
        sys.exit(1)
    if status.get("interrupted"):  # what was heard is written and summed up above; the shell still learns
        sys.exit(130)


WEATHER_LOOKBACK_DAYS = 7  # a run without --since starts this far before the last day it covered


def _sync_weather(a: argparse.Namespace) -> None:
    """`sync weather [--since DAY] [--until DAY] [--dry-run]`: for every local day of the window, the
    owner's overnight stay and every stay of three hours or more, each place rounded to a tenth of a
    degree (`weather.clusters`), the daily values fetched from Open-Meteo once per cluster and run of
    days and cached under `inbox/weather/` (`adapters.weather.pull`), one `weather/v1` line per
    cluster-day appended; a re-run refetches nothing and appends nothing already there. The window
    defaults to the day after the last day covered (`state/weather.json`, less a week's lookback for
    points that arrive late) — or the record's first located day — up to yesterday. A dry run plans
    and counts and neither fetches nor writes. The variable `LOGBOOK_WEATHER` is `sync --all`'s to
    read: by name the command needs none."""
    from ..contrib.adapters import weather as weather_adapter

    if a.listen is not None:
        print("sync: --listen is for a source that listens to a stream (ais), not weather", file=sys.stderr)
        sys.exit(2)
    if getattr(a, "restart", False):
        print("sync: --restart is for a source that walks a library (immich), not weather", file=sys.stderr)
        sys.exit(2)
    lb = Logbook.find()
    if _say_disabled(lb, weather_adapter.NAME):
        return
    state_path = lb.root / "state" / f"{weather_adapter.NAME}.json"
    stored = _read_state(state_path).get("since")
    try:
        window = _weather_window(lb, a.since, a.until, stored if isinstance(stored, str) else None)
    except ValueError as e:
        print(f"sync: weather: {e}", file=sys.stderr)
        sys.exit(2)
    if window is None:
        print("weather: no days to cover (the record has no location lines, or none before today)")
        return
    first, last = window
    try:
        clusters = weather_reader.clusters(lb, first, last)
    except stays.SettingsError as e:
        print(f"sync: weather: {e}", file=sys.stderr)
        sys.exit(2)
    days = len(day_range(first, last))
    cache = lb.root.joinpath(*weather_adapter.CACHE_DIR.parts)
    tz = str(lb.meta["timezone"])
    today = date.fromisoformat(_today())
    span = f"{first} {EN_DASH} {last}"
    if a.dry_run:
        to_fetch = weather_adapter.outstanding(clusters, cache)
        requests = weather_adapter.plan(to_fetch, today)
        print(
            f"weather: {len(clusters)} cluster-days over {_plural(days, 'day')} {span}, "
            f"{len(clusters) - len(to_fetch)} cached, {len(to_fetch)} to fetch in "
            f"{_plural(len(requests), 'request')} (dry run, nothing written)"
        )
        return
    from_cache = len(clusters) - len(weather_adapter.outstanding(clusters, cache))
    counts: dict[str, int] = {}
    failed: list[str] = []
    seen = 0

    def counted(draft: dict[str, Any]) -> dict[str, Any]:
        nonlocal seen
        seen += 1
        return draft

    fetched: list[int] = [0]

    def progress(n: int, elapsed: float) -> None:
        fetched[0] = n
        _page_progress(weather_adapter.UNIT)(n, elapsed)

    drafts = (
        counted(d)
        for d in weather_adapter.pull(
            weather_adapter.Config(),
            progress=progress,
            counts=counts,
            clusters=clusters,
            cache=cache,
            timezone=tz,
            failed=failed,
            today=today,
        )
    )
    try:
        n = lb.append_many(drafts)
    except (OSError, ValueError) as e:
        print(f"sync: weather: {e}", file=sys.stderr)
        sys.exit(1)
    for problem in failed:
        print(f"sync: weather: {problem}", file=sys.stderr)
    already = seen - n
    print(
        f"weather: {n} new lines of {seen} seen for {_plural(days, 'day')} {span}"
        + (f" ({already} already in the record)" if already else "")
        + f"; {_plural(fetched[0], 'request')}, {from_cache} cluster-days from the cache"
    )
    _report_skipped(counts)
    if failed:
        sys.exit(1)
    if stored is None or last > str(stored):
        _write_state(state_path, {"source": weather_adapter.NAME, "since": last, "updated_at": now_utc()})


def _weather_window(
    lb: Logbook, since: str | None, until: str | None, stored: str | None
) -> tuple[str, str] | None:
    """The local days `sync weather` covers: `--since` to `--until`, each a day; without `--until`,
    yesterday; without `--since`, a week before the last day covered, or the record's first located
    day. None when nothing is left to cover. ValueError for a day that is not one or a window that
    runs backwards."""
    for text in (since, until):
        if text is not None:
            try:
                parse_day(text)
            except ValueError:
                raise ValueError(f"days are YYYY-MM-DD, not {text!r}") from None
    yesterday = (date.fromisoformat(_today()) - timedelta(days=1)).isoformat()
    last = until if until is not None else yesterday
    if since is not None:
        first = since
    elif stored is not None:
        first = (date.fromisoformat(stored) - timedelta(days=WEATHER_LOOKBACK_DAYS)).isoformat()
    else:
        whole = reading.record_days(lb, "location")
        if whole is None:
            return None
        first = whole[0]
    if last < first:
        if since is not None and until is not None:
            raise ValueError(f"range runs backwards: {since} > {until}")
        return None
    return first, last


def _listen_flag(a: argparse.Namespace, listens: bool) -> float | None:
    """`--listen SECONDS` as a number, None when not given; exits 2 when the source does not listen,
    when both --listen and --until are given, or when the seconds are not a number above 0.
    `--until` is turned into seconds later, once the record's zone is known."""
    from ..contrib.adapters import ais

    if a.listen is None and a.until is None:
        return None
    if not listens:
        print(
            f"sync: --listen and --until are for a source that listens to a stream (ais), not {a.name}",
            file=sys.stderr,
        )
        sys.exit(2)
    if a.listen is not None and a.until is not None:
        print("sync: give --listen or --until, not both", file=sys.stderr)
        sys.exit(2)
    if a.listen is None:
        return None
    try:
        return ais.seconds(a.listen)
    except ValueError as e:
        print(f"sync: --listen {e}", file=sys.stderr)
        sys.exit(2)


def _report_listening(status: Mapping[str, Any]) -> None:
    """How a listening source's run went, after the counts: the reconnects, if any."""
    n = int(status.get("reconnects", 0))
    if n:
        print(f"  reconnected {'once' if n == 1 else f'{n} times'}")


def sources_arguments(sub: Subparsers) -> None:
    """`logbook doctor sources` (`logbook sources` until 0.6)."""
    s = sub.add_parser(
        "sources",
        help="every adapter, file and live, and whether policy/import.json has disabled it;"
        " --gaps: where each source went quiet",
    )
    s.add_argument(
        "--gaps",
        action="store_true",
        help="per source with lines: its last line's time, the longest silent stretch and the days with"
        " no line, from the index",
    )
    s.add_argument(
        "--since",
        metavar="YYYY-MM-DD",
        help="with --gaps: the range starts here (default: each source's first line)",
    )
    s.add_argument(
        "--expect",
        nargs="+",
        metavar="SOURCE",
        help="with --gaps: only these sources; one silent for a day or more, or with no line, is flagged"
        " and the command exits 1",
    )
    s.add_argument("--json", action="store_true", help="with --gaps: the report as JSON")
    s.set_defaults(fn=cmd_sources)


def cmd_sources(a: argparse.Namespace) -> None:
    """`sources`: every adapter this build has, file and live, with its state under
    `policy/import.json` — `enabled`, or `disabled (<reason>)`; then any disabled name that is no
    adapter, so a typo in the file is seen rather than silently ignored.

    `sources --gaps [--since DAY] [--expect SOURCE...] [--json]`: where each source went quiet, from
    the index alone (`gaps.report`, the rules are there) — per source its lines in the range, its
    last line's time, the longest silent stretch and the days with no line. With `--expect` only
    those sources are shown, a flagged one marked `!`, and the command exits 1 when any is flagged,
    so a cron job can say so. Nothing is written."""
    from ..contrib import adapters

    if not a.gaps and (a.since is not None or a.expect is not None or a.json):
        print("sources: --since, --expect and --json go with --gaps", file=sys.stderr)
        sys.exit(2)
    lb = Logbook.find()
    if a.gaps:
        try:
            data = gaps.report(lb, since=a.since, expect=a.expect)
        except ValueError as e:
            print(f"sources: {e}", file=sys.stderr)
            sys.exit(2)
        if a.json:
            print(json.dumps(data, indent=2))
        else:
            for text in gaps.rows(data):
                print(text)
        if data["flagged"]:
            sys.exit(1)
        return
    disabled = _disabled(lb)
    kinds: dict[str, list[str]] = {}
    for file_adapter in adapters.file_adapters():
        kinds.setdefault(file_adapter.NAME, []).append("file")
    for live_adapter in adapters.live_adapters():
        kinds.setdefault(live_adapter.NAME, []).append("live")
    for name in sorted(kinds):
        reason = disabled.get(name)
        state = "enabled" if reason is None else f"disabled ({reason})"
        print(f"{name:<20} {'+'.join(kinds[name]):<10} {state}")
    for name, reason in disabled.items():
        if name not in kinds:
            print(f"{name:<20} {'-':<10} disabled ({reason}); no adapter by that name in this build")
    n = len(kinds)
    off = sum(name in kinds for name in disabled)
    print(f"{n} adapters, {off} disabled; the list is {policy.import_path(lb.root)}")


def assets_arguments(sub: Subparsers) -> None:
    """`logbook setup assets` (`logbook assets` until 0.6)."""
    s = sub.add_parser("assets", help="the boats, aircraft and cars the record tracks (assets.json)")
    verbs = s.add_subparsers(dest="verb", required=True)
    v = verbs.add_parser("list", help="one line per registered asset")
    v.set_defaults(fn=cmd_assets)
    v = verbs.add_parser(
        "status", help="per asset, its last known position (time, place, speed) and how old that fix is"
    )
    v.add_argument("--json", action="store_true", help="the statuses as JSON")
    v.set_defaults(fn=cmd_assets)
    v = verbs.add_parser("add", help="register one asset")
    v.add_argument("id", help="the subject id its positions carry: lower-case letters, digits, hyphens")
    v.add_argument("--kind", required=True, choices=assets.KINDS)
    v.add_argument("--name", required=True, help="what you call it")
    v.add_argument("--mmsi", help="nine digits; `sync ais` asks aisstream.io for it")
    v.add_argument("--icao24", help="six hex digits; `sync adsb` asks OpenSky for it")
    v.add_argument("--registration", help="call sign or plate, free text")
    v.set_defaults(fn=cmd_assets)


def cmd_assets(a: argparse.Namespace) -> None:
    """`assets list`: one line per registered asset. `assets add`: register one (ADR 0018). The
    registry is <root>/assets.json, a setting of the record, outside the chain. `assets status`:
    per asset, its last known position (its latest standing location line, through the index,
    `logbook/contrib/asset_status.py`) and the age of that fix; a table in local time, or JSON."""
    lb = Logbook.find()
    try:
        if a.verb == "add":
            asset = assets.Asset(
                id=a.id, kind=a.kind, name=a.name, mmsi=a.mmsi, icao24=a.icao24, registration=a.registration
            )
            assets.add(lb.root, asset)
            print(_asset_row(asset))
            return
        registry = assets.read(lb.root)
        named = places.read(lb.root) if a.verb == "status" else []
    except (assets.AssetError, places.PlaceError) as e:
        print(f"assets: {e}", file=sys.stderr)
        sys.exit(2)
    if not registry:
        print(
            "no assets registered; register one with: logbook assets add <id> --kind "
            f"{'|'.join(assets.KINDS)} --name NAME [--mmsi N] [--icao24 HEX] [--registration REG]"
        )
        return
    if a.verb == "status":
        statuses = asset_status.read(lb, registry, named, datetime.now(UTC))
        if a.json:
            print(json.dumps({"assets": [s.to_json() for s in statuses]}, indent=2))
            return
        zone = ZoneInfo(str(lb.meta["timezone"]))
        for status in statuses:
            print(_status_row(status, zone))
        return
    for asset in registry:
        print(_asset_row(asset))


def _status_row(status: asset_status.Status, zone: ZoneInfo) -> str:
    """`<id> <kind> <name>  <local time>  <lat>,<lon>  near <place>, x km  <speed> m/s  <age> ago`,
    or `no fix yet`. The distance to the place is in metres under a kilometre."""
    head = f"{status.asset.id:<16} {status.asset.kind:<9} {status.asset.name:<24}"
    fix = status.fix
    if fix is None:
        return f"{head} no fix yet"
    when = datetime.fromisoformat(fix.at.replace("Z", "+00:00")).astimezone(zone).strftime("%Y-%m-%d %H:%M")
    parts = [when, f"{fix.lat:.4f},{fix.lon:.4f}"]
    if fix.near is not None:
        name, m = fix.near
        parts.append(f"near {name}, {m:.0f} m" if m < 1000 else f"near {name}, {m / 1000:.1f} km")
    if fix.speed_mps is not None:
        parts.append(f"{fix.speed_mps:.1f} m/s")
    parts.append(asset_status.age_text(fix.age_s))
    return f"{head} {'  '.join(parts)}"


def _asset_row(asset: assets.Asset) -> str:
    ids = [f"{key} {value}" for key in ("mmsi", "icao24") if (value := getattr(asset, key)) is not None]
    if asset.registration is not None:
        ids.append(asset.registration)
    return f"{asset.id:<16} {asset.kind:<9} {asset.name}" + (f"  ({', '.join(ids)})" if ids else "")


def _state(path: Path, adapter: adapters.LiveAdapter, mark: str, seen: dict[str, Any]) -> dict[str, Any]:
    """The state to store: the watermark and, for an adapter with GROUP_MARKS, one per group (per
    tracked asset), each merged with the stored one and never moved backwards."""
    state: dict[str, Any] = {"since": mark}
    if getattr(adapter, "GROUP_MARKS", False):
        groups: dict[str, str] = dict(_read_state(path).get("groups") or {})
        for name, group_mark in seen["group_marks"].items():
            if name not in groups or group_mark > groups[name]:
                groups[name] = group_mark
        state["groups"] = dict(sorted(groups.items()))
    return state


def _lookup(lb: Logbook) -> Callable[[str, str], str | None]:
    """For a live adapter whose `pull` takes `lookup`: the id of the line with (source, raw_id), or
    None, read through the index, so a derived line can point at one already in the record."""

    def lookup(source: str, raw_id: str) -> str | None:
        with lb.index() as idx:
            return idx.line_id(source, raw_id)

    return lookup


def _start(
    lb: Logbook, adapter: adapters.LiveAdapter, config: object, given: str | None, stored: str | None
) -> tuple[str | None, str | None]:
    """Where a pull starts, and the record's newest line when that is what it started from.

    `--since` is used as given. Otherwise the stored watermark; an adapter with `resume` turns it
    into a start (a lookback before it, for a source whose items can arrive late) and, with no
    watermark yet, resumes from the record's newest line of its source and KIND, so a record seeded
    from an export carries on where the export ended."""
    if given is not None:
        return given, None
    resume = getattr(adapter, "resume", None)
    if resume is None:
        return stored, None
    if stored is not None:
        return str(resume(config, stored)), None
    with lb.index() as idx:
        newest = idx.newest(adapter.NAME, str(getattr(adapter, "KIND", "")))
    if newest is None:
        return None, None
    return str(resume(config, newest)), newest


def _report_pending(pending: int) -> None:
    """Assets the source has not finished processing; the adapter left them for a later sync."""
    if pending:
        print(f"  {pending:,} pending (metadata not extracted yet; will arrive on a later sync)")


def _watch(
    drafts: Iterable[dict[str, Any]],
    watermark: Callable[[dict[str, Any]], str | None],
    seen: dict[str, Any],
    group: Callable[[dict[str, Any]], str] | None = None,
) -> Iterator[dict[str, Any]]:
    """Pass drafts through, noting count, earliest/latest `at`, the largest watermark, per-provenance
    counts and, given `group`, the count per group (per calendar, for `gcal`)."""
    for d in drafts:
        if group is not None:
            seen["groups"][group(d)] += 1
        seen["count"] += 1
        at = d["at"]
        if seen["first"] is None or at < seen["first"]:
            seen["first"] = at
        if seen["last"] is None or at > seen["last"]:
            seen["last"] = at
        mark = watermark(d)
        if mark is not None and (seen["watermark"] is None or mark > seen["watermark"]):
            seen["watermark"] = mark
        if mark is not None and group is not None:
            name = group(d)
            if name not in seen["group_marks"] or mark > seen["group_marks"][name]:
                seen["group_marks"][name] = mark
        seen["provenance"][d["payload"].get("provenance", "-")] += 1
        seen["kinds"][d["kind"]] += 1
        yield d


def _read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _write_state(path: Path, state: dict[str, Any]) -> None:
    """The state file, whole, never half-written: a temporary beside it, then one rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _total(adapter: adapters.LiveAdapter, config: object) -> int | None:
    """What the source says it holds, or None when it cannot say (the adapter's `total` raised, or
    there is none): `sync` then says `total unknown` rather than a number that is not the total."""
    ask = getattr(adapter, "total", None)
    if ask is None:
        return None
    try:
        n = ask(config)
    except (OSError, ValueError):
        return None
    return int(n) if isinstance(n, int) and not isinstance(n, bool) else None


class WalkState:
    """A live source's walk through its whole library, checkpointed under `walk` in
    `state/<name>.json`, so a run interrupted after hours (Ctrl-C, a lost connection, a server
    error) carries on where it stopped instead of walking the library again (`immich`). The
    adapter's half (`adapters.Walk`): `start()` is the checkpoint it saved last time, a JSON object
    of its own (`cursor`, `fetched`, ...), or None; `reached(ordinal, checkpoint)` after a page
    says: once draft `ordinal` is in the record, `checkpoint` is where to resume. The consumer's
    half: `commit(taken)`, `append_many`'s `committed`, writes the latest checkpoint reached by
    then, so a checkpoint never runs ahead of the lines on disk; `finish()` removes it once the
    walk completed. A saved walk is for one `since`: a run with another, or `--restart`, drops it
    and begins again. `started` is when the walk began (the first run's clock), the latest the
    walk's watermark may be. Bookkeeping, not the record: nothing here is in the chain."""

    def __init__(self, path: Path, since: str | None, restart: bool = False) -> None:
        self.path = path
        self.since = since
        self.started = now_utc()
        self.pending: list[tuple[int, dict[str, Any]]] = []
        self.checkpoint: dict[str, Any] | None = None
        self.dropped: tuple[str, dict[str, Any]] | None = None  # (why, the walk) when one is left behind
        saved = _read_state(path).get("walk")
        if isinstance(saved, dict) and isinstance(saved.get("checkpoint"), dict):
            if restart:
                self.dropped = ("--restart", saved)
            elif saved.get("since") != since:
                self.dropped = ("since", saved)
            else:
                self.checkpoint = dict(saved["checkpoint"])
                self.started = str(saved.get("started") or self.started)

    def notices(self, unit: str, total: int | None) -> list[str]:
        """What to say before the walk: that it resumes, or that a saved walk is dropped and why."""
        if self.checkpoint is not None:
            fetched = int(self.checkpoint.get("fetched") or 0)
            of = f"{fetched:,} {unit}" if total is None else f"{fetched:,} of {total:,} {unit}"
            return [
                f"resuming where the last run stopped, at {of} ({self.path.parent.name}/{self.path.name};"
                " --restart walks from the beginning)"
            ]
        if self.dropped is not None:
            why, walk = self.dropped
            fetched = int((walk.get("checkpoint") or {}).get("fetched") or 0)
            left = f"the walk interrupted at {fetched:,} {unit}"
            if why == "--restart":
                return [f"--restart: {left} is dropped; starting from the beginning"]
            return [f"{left} was for another --since; starting from the beginning"]
        return []

    # -- the adapter's half ----------------------------------------------------

    def start(self) -> dict[str, Any] | None:
        return dict(self.checkpoint) if self.checkpoint is not None else None

    def reached(self, ordinal: int, checkpoint: dict[str, Any]) -> None:
        self.pending.append((ordinal, dict(checkpoint)))

    # -- the consumer's half ---------------------------------------------------

    def commit(self, taken: int) -> None:
        """Every draft up to `taken` is in the record: the latest checkpoint reached by then is
        written; the ones after it wait for the next commit."""
        reached = [checkpoint for ordinal, checkpoint in self.pending if ordinal <= taken]
        self.pending = [(ordinal, checkpoint) for ordinal, checkpoint in self.pending if ordinal > taken]
        if not reached:
            return
        state = _read_state(self.path)
        state["walk"] = {
            "since": self.since,
            "started": self.started,
            "saved": now_utc(),
            "checkpoint": reached[-1],
        }
        _write_state(self.path, state)

    def finish(self) -> None:
        """The walk completed: no checkpoint to resume from."""
        self.pending = []
        state = _read_state(self.path)
        if "walk" in state:
            del state["walk"]
            _write_state(self.path, state)
