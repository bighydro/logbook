"""The Library built ahead of time: every door and shelf of `logbook serve` written as files after the
06:00 close and after each act on a page, and served from them (RFC 0047 §8, phase 4 of the Library's
rebuild).

A page is the bytes `serve.Site.respond` renders for its address, kept with the status, the policy
and the location it was answered with, so a built page is the page the server would have rendered at
the moment of the build, byte for byte, with one sentence added to its footer saying when that was.
The server answers a GET from the build when the build holds the address, and renders only what the
build does not hold: today's Day, whose shape moves with the clock (RFC 0043 §5), the redirect of
`/today`, a photo's pixels, and an address no build has written yet, which it renders once and adds
to the build (`Library.keep`), so the next visit is a file. Nothing a page shows is computed while a
browser waits for a door.

Where: the folder `library/` beside the index, in the cache folder (`<cache dir>/logbook/<owner_id>/`,
RFC 0029 §8), never in the record's own folder, so no export, vault, crossing or copy of the record
ever carries it. The folder is 0700 and every file 0600 (on the platforms that have modes): the pages
hold what the Library shows, every tier of it, so only the record's user reads them. A file is named
by the SHA-256 of its address, not by the address, so `/People` and `/people` are never one file on a
filesystem that does not tell case apart, and no address becomes a path. `pages.json` names each:
`{"version", "built": {when, head, seconds, pages, written}, "pages": {address: {file, status, csp,
location, etag, at, head, asked}}}`, written whole and moved into place, so a reader never sees half
of it.

A build is one process's at a time: `building.lock` is created exclusively and holds the pid; a
second build finds it and returns, a lock whose pid is gone is taken over. The build writes only the
files whose bytes changed (`vault.write`'s rule) and removes the pages it no longer names.

What is built (`targets`): the doors and shelves (`DOORS`), the Days of the last fortnight but today,
and the detail pages the doors link to, up to `EACH` of each kind (the people, journeys, orgs, ideas,
goals and promises at the top of their shelves, a year's or a page's variant of a shelf), and every
address the server added on demand (`asked`), the latest `ASKED` of them. A full build renders every
one; `build(only=...)` renders the addresses given, as the server's rebuild after an act does first
for the pages the act changed."""

from __future__ import annotations

import contextlib
import hashlib
import html
import json
import os
import re
import sys
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from ..core import day_start, kept, sealing
from ..core.store import _alive

if TYPE_CHECKING:
    from ..core.store import Logbook
    from .serve import Response, Site

VERSION = 1
FOLDER = "library"
MANIFEST = "pages.json"
LOCK = "building.lock"
# the doors and shelves of the Library today (RFC 0047 §9 maps each to its door)
DOORS = (
    "/",
    "/days",
    "/trips",
    "/journeys",
    "/people",
    "/places",
    "/world",
    "/manifest",
    "/manifest/people",
    "/ideas",
    "/promises",
    "/goals",
    "/agents",
    "/assets",
    "/gaps",
)
EVERYWHERE = ("retraction", "resolution", "entity", "entity-review", "people-review")  # who is who
DAY_PAGE = re.compile(r"^/day/(\d{4}-\d{2}-\d{2})$")
TRIPS_YEAR = re.compile(r"^/trips\?year=(\d{4})$")
TRIPS_SPILL_DAYS = 2  # a year's trips read the night after its last day, and the morning after that
JOURNEY_PAGE = re.compile(r"^/journeys/(\d{4}-\d{2}-\d{2})/(\d{4}-\d{2}-\d{2})$")
RECENT_DAYS = 14  # the Days of the last fortnight are built; today's is always rendered live
EACH = 60  # detail pages of one kind the build follows from the doors
ASKED = 500  # addresses the server added on demand, the latest kept and rebuilt
DETAIL = re.compile(r"^/(people|journeys|org|idea|goals|promises|day)/")
HREF = re.compile(r"""href\s*=\s*["']([^"']*)["']""", re.I)
LIVE_PREFIXES = ("/photo/",)  # pixels from the attachment store: cheap, and not a page
FOOTER = "</footer>"
REPLACE_TRIES = 40  # Windows: a file held open by a reader is replaced again for up to two seconds
SLOWEST = 5  # the pages a build names as its slowest
SAVE_EVERY = 50  # a build names its pages in `pages.json` this many at a time, and at its end


class Busy(Exception):
    """Another process is building the Library now."""


def folder_of(lb: Logbook) -> Path:
    """`<cache dir>/logbook/<owner_id>/library/`, beside the index: never inside the record."""
    return sealing.cache_dir(os.environ) / str(lb.meta.get("owner_id")) / FOLDER


def address(path: str, query: str = "") -> str:
    """The address a page is kept under: its path, and its query as asked (`?` and all)."""
    return path + (f"?{query}" if query else "")


def file_name(target: str) -> str:
    return hashlib.sha256(target.encode("utf-8")).hexdigest() + ".html"


def _private_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):  # Windows has no modes to speak of; the folder is the user's
        os.chmod(path, 0o700)


def _write_private(path: Path, data: bytes) -> None:
    """`data` at `path`, 0600 from its first byte: written to a sibling created with that mode, then
    moved into place, so no reader sees half a page and no other user ever could read it. Windows
    refuses to replace a file another thread holds open (the server reading the page it replaces):
    the move is tried again for a moment, and the reader is done by then."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        for attempt in range(REPLACE_TRIES):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if sys.platform != "win32" or attempt == REPLACE_TRIES - 1:
                    raise
                time.sleep(0.05)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _stamp(instant: datetime) -> str:
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamped(body: bytes, when: str) -> bytes:
    """The page with one sentence in its footer saying when it was built: the moment, in the words
    and the zone the footer already uses (`built 06:02`), so a page that is not this minute's says so."""
    marker = FOOTER.encode("utf-8")
    if marker not in body:
        return body
    note = f' · <span class="built">built {html.escape(when)}</span>'.encode()
    head, _, tail = body.rpartition(marker)
    return head + note + marker + tail


@dataclass
class Page:
    """One built page as `pages.json` names it."""

    file: str
    status: int
    csp: str | None
    location: str | None
    etag: str
    at: str
    head: str
    asked: bool = False

    def to_json(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


def _page(v: object) -> Page | None:
    """One entry of `pages.json`, or None for one this version did not write."""
    if not isinstance(v, dict) or not isinstance(v.get("file"), str) or not isinstance(v.get("status"), int):
        return None
    csp, location = v.get("csp"), v.get("location")
    return Page(
        file=v["file"],
        status=v["status"],
        csp=csp if isinstance(csp, str) else None,
        location=location if isinstance(location, str) else None,
        etag=str(v.get("etag") or ""),
        at=str(v.get("at") or ""),
        head=str(v.get("head") or ""),
        asked=bool(v.get("asked")),
    )


class Library:
    """The build's folder as the server reads and adds to it. Thread-safe: the manifest is read again
    when its file changes, and every change to it is one write under one lock."""

    def __init__(self, lb: Logbook, folder: Path | None = None, now: Callable[[], datetime] | None = None):
        self.lb = lb
        self.folder = folder if folder is not None else folder_of(lb)
        self.now = now or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()
        self._seen: tuple[int, int] | None = None
        self._pages: dict[str, Page] = {}
        self._built: dict[str, Any] = {}
        self._dirty = False  # pages added (`put(save=False)`) and not yet in `pages.json`

    # -- reading ---------------------------------------------------------------------------------------
    def _load(self) -> None:
        """`pages.json` read again when it changed on disk; never over pages this process added and
        has not saved yet (`_dirty`), which the next `save` writes."""
        if self._dirty:
            return
        manifest = self.folder / MANIFEST
        try:
            st = manifest.stat()
        except OSError:
            self._seen, self._pages, self._built = None, {}, {}
            return
        stamp = (st.st_mtime_ns, st.st_size)
        if stamp == self._seen:
            return
        try:
            data = json.loads(manifest.read_bytes())
        except (OSError, ValueError):
            return  # moved into place whole: a bad file is not ours to read; the next build rewrites it
        if not isinstance(data, dict) or data.get("version") != VERSION:
            self._seen, self._pages, self._built = stamp, {}, {}
            return
        pages = data.get("pages")
        self._pages = {
            str(k): page
            for k, v in (pages.items() if isinstance(pages, dict) else ())
            if (page := _page(v)) is not None
        }
        built = data.get("built")
        self._built = dict(built) if isinstance(built, dict) else {}
        self._seen = stamp

    def pages(self) -> dict[str, Page]:
        with self._lock:
            self._load()
            return dict(self._pages)

    def built(self) -> dict[str, Any]:
        """The last build: `when`, `head`, `seconds`, `pages`, `written`; empty before the first."""
        with self._lock:
            self._load()
            return dict(self._built)

    def page(self, target: str) -> tuple[Page, bytes] | None:
        """The built page at `target` and its bytes; None when the build does not hold it."""
        with self._lock:
            self._load()
            found = self._pages.get(target)
        if found is None:
            return None
        try:
            return found, (self.folder / found.file).read_bytes()
        except OSError:
            return None

    # -- writing ---------------------------------------------------------------------------------------
    def _save(self, pages: Mapping[str, Page], built: Mapping[str, Any]) -> None:
        """`pages.json`, whole, moved into place. Under `_lock`."""
        data = {
            "version": VERSION,
            "built": dict(built),
            "pages": {k: pages[k].to_json() for k in sorted(pages)},
        }
        _private_folder(self.folder)
        _write_private(self.folder / MANIFEST, (json.dumps(data, indent=1) + "\n").encode("utf-8"))
        self._seen = None  # read it back as written, mtime and all
        self._dirty = False

    def put(self, target: str, response: Response, head: str, asked: bool = False, save: bool = True) -> Page:
        """`response` kept at `target`: its bytes with the build's footer note, its file written when
        the bytes changed, the manifest naming it (written now, or with `save` False at the build's
        next `save`, so a build of hundreds of pages writes `pages.json` a few times, not once each)."""
        when = self.now()
        local = self._local(when)
        body = stamped(response.body, local)
        name = file_name(target)
        _private_folder(self.folder)
        path = self.folder / name
        if not (path.is_file() and path.read_bytes() == body):
            _write_private(path, body)
        etag = f'"b-{hashlib.sha256(body).hexdigest()[:20]}"'
        page = Page(name, response.status, response.csp, response.location, etag, _stamp(when), head, asked)
        with self._lock:
            self._load()
            pages = dict(self._pages)
            kept = pages.get(target)
            page.asked = asked or (kept is not None and kept.asked)
            pages[target] = page
            self._pages = pages
            self._dirty = True
            if save:
                self._save(pages, self._built)
        return page

    def save(self) -> None:
        """`pages.json` as this process holds it now: what `put(save=False)` added."""
        with self._lock:
            self._save(self._pages, self._built)

    def drop(self, targets: Iterable[str]) -> list[str]:
        """Forget `targets` (an act changed them): the server renders each until the next build
        writes it again. Their files stay until then; nothing names them. The addresses dropped."""
        gone = []
        with self._lock:
            self._load()
            pages = dict(self._pages)
            for target in targets:
                if pages.pop(target, None) is not None:
                    gone.append(target)
            if gone:
                self._save(pages, self._built)
        return gone

    def _local(self, when: datetime) -> str:
        """`06:02` today, `21 Oct 06:02` on another day, in the record's zone, as the footer shows it."""
        try:
            zone = day_start.of(self.lb.meta).zone
            local, today = when.astimezone(zone), self.now().astimezone(zone)
        except (day_start.DayStartError, KeyError, ValueError):  # the footer names the trouble; UTC here
            local, today = when.astimezone(UTC), self.now().astimezone(UTC)
        clock = local.strftime("%H:%M")
        return clock if local.date() == today.date() else f"{local.day} {local.strftime('%b')} {clock}"

    @contextlib.contextmanager
    def building(self) -> Any:
        """Hold `building.lock` for a build: `Busy` when another live process holds it."""
        _private_folder(self.folder)
        lock = self.folder / LOCK
        for _ in range(2):
            try:
                fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                try:
                    pid = int(json.loads(lock.read_bytes()).get("pid", 0))
                except (OSError, ValueError, AttributeError):
                    pid = 0
                if pid and pid != os.getpid() and _alive(pid):
                    raise Busy(f"the Library is being built by process {pid}") from None
                if pid == os.getpid():
                    raise Busy("the Library is being built by this process") from None
                lock.unlink(missing_ok=True)
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"pid": os.getpid(), "since": _stamp(self.now())}, fh)
            break
        else:
            raise Busy("the Library's build lock could not be taken")
        try:
            yield
        finally:
            lock.unlink(missing_ok=True)


def live(path: str, today: str) -> bool:
    """Whether the server renders `path` always, never from the build: today's Day (its shape moves
    with the clock), `/today` (a redirect to it) and a photo's pixels."""
    if path == "/today" or path.startswith(LIVE_PREFIXES):
        return True
    return path == f"/day/{today}"


# the pages a form of the Library is on: a 409 (the page older than the record) drops them, so the
# reload is the page as it stands and not the build's again
FORM_PAGES = {
    "/places/review": ("/places",),
    "/journeys/name": ("/journeys",),
    "/people/review": ("/people",),
    "/manifest/review": ("/manifest", "/org/"),
    "/manifest/status": ("/manifest", "/org/"),
    "/ideas/review": ("/ideas", "/idea/"),
    "/ideas/status": ("/ideas", "/idea/"),
}
DAY_FORM = re.compile(r"^/day/(\d{4}-\d{2}-\d{2})/")


def _under(path: str, prefix: str) -> bool:
    return (
        path.startswith(prefix) if prefix.endswith("/") else path == prefix or path.startswith(prefix + "/")
    )


def touched(pages: Iterable[str], act: str, status: int, back: str, form: Mapping[str, str]) -> list[str]:
    """The built pages an act at `act` changed, which the server drops at once. Written (a 2xx or a
    303): the page it sends the owner back to (`back`, the 303's path, with any query the build holds
    for it) and the front page; every other page it changed is the rebuild's, in the background, so a
    shelf that reads the whole record is never rendered while the owner waits. Refused because the page
    was older than the record (409): the page the form was on, which the reload then renders as it
    stands. Any other refusal changed nothing."""
    if status == 409:
        day = DAY_FORM.match(act)
        on = day.group(1) if day else form.get("day", "") if act in ("/star", "/with") else ""
        prefixes = (f"/day/{on}",) if on else FORM_PAGES.get(act, ())
        return [t for t in pages if any(_under(t.partition("?")[0], p) for p in prefixes)]
    if status >= 400:
        return []
    return [t for t in pages if t == "/" or (back and t.partition("?")[0] == back)]


def _kind(target: str) -> str:
    path, _, query = target.partition("?")
    found = DETAIL.match(path)
    names = sorted({p.partition("=")[0] for p in query.split("&") if p})
    return (found.group(0) if found else path) + ("?" + "&".join(names) if names else "")


def targets(site: Site, today: str, asked: Sequence[str] = ()) -> list[str]:
    """What a full build renders: the doors, the last fortnight's Days but today's, and the detail
    pages and variants the doors link to, `EACH` of a kind, in the order the doors list them; then the
    addresses asked for on demand. Reads the doors as it goes (they are rendered again by the build:
    the second reading is the server's kept page)."""
    out: list[str] = list(DOORS)
    first = date.fromisoformat(today)
    out += [f"/day/{(first - timedelta(days=n)).isoformat()}" for n in range(1, RECENT_DAYS + 1)]
    seen = set(out)
    counts: dict[str, int] = {}
    for door in DOORS:
        path, _, query = door.partition("?")
        response = site.respond(path, query)
        if response.status != 200:
            continue
        for link in HREF.findall(response.body.decode("utf-8", "replace")):
            link = html.unescape(link).partition("#")[0]
            parts = urlsplit(link)
            if not link.startswith("/") or link.startswith("//") or parts.path.startswith(LIVE_PREFIXES):
                continue
            if link in seen or live(parts.path, today):
                continue
            kind = _kind(link)
            if counts.get(kind, 0) >= EACH:
                continue
            counts[kind] = counts.get(kind, 0) + 1
            seen.add(link)
            out.append(link)
    for target in asked:
        if target not in seen:
            seen.add(target)
            out.append(target)
    return out


@dataclass
class Result:
    pages: int
    written: int
    removed: int
    seconds: float
    failed: dict[str, str]
    slowest: list[tuple[str, float]] = field(default_factory=list)  # the pages that took longest, first


def settled(lb: Logbook, site: Site) -> str:
    """What the pages read besides the lines and the clock: `logbook.json` without its head and seq,
    the settings beside the chain and the code (`kept.stamp`), and the review's bookkeeping and the
    circle's pages (`Site._beside`). A build under another is a full one."""
    return kept.stamp(lb, kept.code_digest(), *site._beside())


def days_touched(lb: Logbook, since: int) -> set[str] | None:
    """The local days the lines appended after `since` landed on, and each one's day before (its night
    runs into the next morning); None when one of them changes who is who everywhere (`EVERYWHERE`),
    which only a full build follows."""
    with lb.index() as idx:
        rows = idx.db.execute("SELECT DISTINCT kind, day_local FROM lines WHERE seq > ?", (since,)).fetchall()
    if any(str(kind) in EVERYWHERE for kind, _day in rows):
        return None
    days = {str(day) for _kind, day in rows}
    return days | {(date.fromisoformat(d) - timedelta(days=1)).isoformat() for d in days}


def _wanted_since(target: str, days: set[str], built: Mapping[str, Page]) -> bool:
    """Whether an incremental build renders `target` again: every door, detail and variant (they read
    the whole record, and the kept readings make that cheap); a Day only when a line landed on it or
    the day after, or when no build has written it; a journey only when it holds such a day; a year's
    trips (`/trips?year=`, which reads that year's days and the morning after) only when a line landed
    on them, or in a year no build has a page of, which every year's pager then names."""
    path = target.partition("?")[0]
    if target not in built:
        return True
    if (trips := TRIPS_YEAR.match(target)) is not None:
        year = trips.group(1)
        after = (date(int(year) + 1, 1, 1) + timedelta(days=TRIPS_SPILL_DAYS)).isoformat()
        return any(f"{year}-01-01" <= d < after or f"/trips?year={d[:4]}" not in built for d in days)
    if (day := DAY_PAGE.match(path)) is not None:
        return day.group(1) in days
    if (journey := JOURNEY_PAGE.match(path)) is not None:
        first, last = journey.group(1), journey.group(2)
        return any(first <= d <= last for d in days)
    return True


def build(
    lb: Logbook,
    site: Site | None = None,
    library: Library | None = None,
    only: Sequence[str] | None = None,
    say: Callable[[str], None] | None = None,
    full: bool = False,
) -> Result:
    """Build the Library: what the lines appended since the last build touched (`days_touched`,
    `_wanted_since`) and every door, or, when the last build was under other settings, when one of
    those lines changes who is who, when there is no build yet, or with `full`, every target
    (`targets`); or `only` those addresses. Each page is `site.respond`'s answer, kept when it is a
    200 or a redirect; a page that fails is named in `failed` and the build goes on. A full build
    removes the pages it no longer names. `Busy` when another process is building."""
    from . import serve

    library = library or Library(lb)
    site = site or serve.Site(lb)
    started = time.monotonic()
    with library.building():
        head = str(lb.meta.get("head") or "")
        with lb.index() as idx:
            seq = idx.indexed()[0]
        today = day_start.of(lb.meta).today(site.now()).isoformat()
        before = library.pages()
        last = library.built()
        stamp = settled(lb, site)
        days = None
        if not full and only is None and last.get("settled") == stamp and isinstance(last.get("seq"), int):
            days = days_touched(lb, int(last["seq"]))
        incremental = days is not None
        asked = sorted((t for t, p in before.items() if p.asked), key=lambda t: before[t].at)[-ASKED:]
        wanted = list(only) if only is not None else targets(site, today, asked)
        if days is not None and only is None:
            wanted = [t for t in wanted if _wanted_since(t, days, before)]
        written = 0
        failed: dict[str, str] = {}
        took: dict[str, float] = {}
        for n, target in enumerate(wanted, 1):
            path, _, query = target.partition("?")
            if live(path, today):
                continue
            began = time.monotonic()
            try:
                response = site.respond(path, query)
            except Exception as e:  # one page's failure is that page's: named, and the rest are built
                failed[target] = f"{type(e).__name__}: {e}"
                continue
            if response.status not in (200, 302):
                failed[target] = f"{response.status}"
                continue
            old = before.get(target)
            page = library.put(target, response, head, asked=target in asked, save=False)
            took[target] = round(time.monotonic() - began, 2)
            if old is None or old.etag != page.etag:
                written += 1
            if n % SAVE_EVERY == 0:
                library.save()  # the server answers from the pages built so far
                if say is not None:
                    say(f"  {n:,} of {len(wanted):,} pages, {time.monotonic() - started:.0f} s")
        library.save()
        removed = 0
        if only is None and not incremental:
            keep = set(wanted)
            gone = [t for t in library.pages() if t not in keep]
            removed = len(library.drop(gone))
            names = {p.file for p in library.pages().values()}
            for f in library.folder.glob("*.html"):
                if f.name not in names:
                    f.unlink(missing_ok=True)
        seconds = round(time.monotonic() - started, 1)
        slowest = sorted(took.items(), key=lambda kv: (-kv[1], kv[0]))[:SLOWEST]
        pages = library.pages()
        with library._lock:
            library._load()
            library._built = {
                "when": _stamp(library.now()),
                "head": head,
                "seq": seq if only is None else last.get("seq"),
                "settled": stamp if only is None else last.get("settled"),
                "seconds": seconds,
                "pages": len(pages),
                "written": written,
                "rendered": len(wanted),
                "full": only is None and not incremental,
                "slowest": [[t, s] for t, s in slowest],
            }
            library._save(library._pages, library._built)
    return Result(len(wanted), written, removed, seconds, failed, slowest)


class Rebuilder:
    """The server's own build, on one thread of its own: asked for after every act (`kick`), it builds
    the Library once for however many acts came in while it built, and waits again; asked for one page
    (`ask`: a reading the server stopped at its limit), it builds the pages asked for, without a limit.
    Another process building (`Busy`, the 06:00 close) is waited out and asked again `RETRY_S` later.
    Never a page's caller: a request never waits for it."""

    RETRY_S = 30.0

    def __init__(self, lb: Logbook, site: Site, library: Library, say: Callable[[str], None] | None = None):
        self.lb, self.site, self.library, self.say = lb, site, library, say
        self._asked = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="library-build", daemon=True)
        self._full = False
        self._wanted: list[str] = []
        self._wanted_lock = threading.Lock()
        self.builds = 0

    def start(self) -> Rebuilder:
        self._thread.start()
        return self

    def kick(self) -> None:
        """A full build: after an act, or when the server finds none."""
        with self._wanted_lock:
            self._full = True
        self._asked.set()

    def ask(self, target: str) -> None:
        """One page: a reading the server stopped at its limit, built here without one."""
        with self._wanted_lock:
            if target not in self._wanted:
                self._wanted.append(target)
        self._asked.set()

    def stop(self) -> None:
        self._stop.set()
        self._asked.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._asked.wait()
            if self._stop.is_set():
                return
            self._asked.clear()
            with self._wanted_lock:
                full, wanted = self._full, self._wanted
                self._full, self._wanted = False, []
            try:
                result = build(self.lb, self.site, self.library, only=None if full else wanted)
            except Busy:
                with self._wanted_lock:
                    self._full = self._full or full
                    self._wanted += [t for t in wanted if t not in self._wanted]
                self._stop.wait(self.RETRY_S)
                self._asked.set()
                continue
            except Exception as e:  # the server goes on answering from the build it has
                if self.say is not None:
                    self.say(f"library: the build failed: {type(e).__name__}: {e}")
                continue
            self.builds += 1
            if self.say is not None:
                self.say(
                    f"library: {result.pages:,} pages, {result.written:,} written, in {result.seconds} s"
                )
