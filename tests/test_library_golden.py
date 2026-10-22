"""The Library's pages are the same, byte for byte, before and after the work that made them fast on a
record of millions of lines (`docs/serve.md`, *Performance*): every page reachable from the navigation of
seven synthetic records — the persona's fortnight, the demo month, the four years of the People pages, the
orgs of the Manifest, the ideas, the shelves, the places — is rendered and its digest compared with the
one kept in `tests/fixtures/library_golden.json`, written from the pages as they were before.

The records are made deterministic here (`_fixed`): every line id the product would mint (`uuid7`) and
every `recorded_at` stamp it would take from the clock (`now_utc`) comes from a counter, so the same code
gives the same record, the same head and the same pages on any machine. The one page that reads the
wall clock of its own (`/gaps`: the silence that runs to now, `gaps.now`) is read at the record's
instant too; every other page reads the clock only through the Site's `now`.

`LOGBOOK_GOLDEN_WRITE=1 uv run pytest tests/test_library_golden.py` writes the file again from the pages
as the code renders them now: only when a change means to change what a page shows, and it says so.
Nobody here exists: the Oslo persona, addresses at example.org, numbers in 07700 900xxx."""

from __future__ import annotations

import contextlib
import hashlib
import itertools
import json
import os
import re
import sys
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from logbook.contrib import gaps, serve
from logbook.core import store
from logbook.core.store import Logbook

GOLDEN = Path(__file__).parent / "fixtures" / "library_golden.json"
WRITE = os.environ.get("LOGBOOK_GOLDEN_WRITE") == "1"
SEEDS = (
    "/", "/days", "/trips", "/journeys", "/people", "/manifest", "/manifest/people", "/ideas", "/places",
    "/assets", "/gaps", "/world", "/promises", "/goals", "/agents",
)  # fmt: skip
LINK = re.compile(r"""href\s*=\s*["']([^"'#]*)""")
MOST = 500  # pages a record's crawl renders at most; the order is fixed, so the same pages every run
EACH = {
    "day": 60,
    "line": 12,
    "week": 8,
}  # pages of one section a crawl renders at most (the first, in its order)
EACH_OTHER = 30  # the same for every other section: `/days?from=…`, `/people/…`, `/places?page=…`
NOT_PAGES = ("/photo/", "/favicon.ico")


@contextlib.contextmanager
def _fixed() -> Iterator[None]:
    """Every module's `uuid7` and `now_utc` that is the store's own, replaced by counters for the
    block: ids and `recorded_at` stamps that are a function of the order they are asked for in."""
    ids = (f"019cadd3-0000-7000-8000-{n:012d}" for n in itertools.count(1))
    stamps = (f"2026-10-18T{n // 3600 % 24:02d}:{n // 60 % 60:02d}:{n % 60:02d}Z" for n in itertools.count(1))
    originals = {"uuid7": store.uuid7, "now_utc": store.now_utc}
    fakes: dict[str, Callable[[], str]] = {"uuid7": lambda: next(ids), "now_utc": lambda: next(stamps)}
    with pytest.MonkeyPatch.context() as mp:
        for module in list(sys.modules.values()):
            if module is None or not getattr(module, "__name__", "").startswith(
                ("logbook", "persona", "four_years")
            ):
                continue
            for name, original in originals.items():
                if vars(module).get(name) is original:  # never a shim's __getattr__, which warns
                    mp.setattr(module, name, fakes[name])
        yield


def _persona(root: Path, mp: pytest.MonkeyPatch) -> tuple[Logbook, datetime]:
    from persona import persona_record

    return persona_record(root, mp), datetime(2026, 6, 22, 10, 0, tzinfo=UTC)


def _demo(root: Path, mp: pytest.MonkeyPatch) -> tuple[Logbook, datetime]:
    from logbook.contrib import demo

    return demo.generate(root / "Demo", days=30, seed=1), datetime(2026, 7, 1, 10, 0, tzinfo=UTC)


def _library(root: Path, mp: pytest.MonkeyPatch) -> tuple[Logbook, datetime]:
    from library_record import library_record

    return library_record(root / "lb"), datetime(2025, 12, 31, 12, 0, tzinfo=UTC)


def _orgs(root: Path, mp: pytest.MonkeyPatch) -> tuple[Logbook, datetime]:
    import orgs_record

    return orgs_record.settled_record(root, mp), datetime(2026, 10, 12, 20, 0, tzinfo=UTC)


def _ideas(root: Path, mp: pytest.MonkeyPatch) -> tuple[Logbook, datetime]:
    import ideas_record

    lb = ideas_record.record(root, mp, ideas_record.ideas_drafts())
    ideas_record.settle(lb)
    return lb, datetime(2026, 10, 16, 20, 0, tzinfo=UTC)


def _shelves(root: Path, mp: pytest.MonkeyPatch) -> tuple[Logbook, datetime]:
    import shelves_record

    return shelves_record.record(root, mp), shelves_record.NOW


def _places(root: Path, mp: pytest.MonkeyPatch) -> tuple[Logbook, datetime]:
    import places_record

    return places_record.record(root / "lb"), datetime(2026, 6, 30, 12, 0, tzinfo=UTC)


RECORDS: dict[str, Callable[[Path, pytest.MonkeyPatch], tuple[Logbook, datetime]]] = {
    "persona": _persona,
    "demo": _demo,
    "library": _library,
    "orgs": _orgs,
    "ideas": _ideas,
    "shelves": _shelves,
    "places": _places,
}


def _instant(now: datetime) -> Callable[[], datetime]:
    return lambda: now


def crawl(site: serve.Site) -> dict[str, str]:
    """path → `status sha256` of every page reachable from `SEEDS` through the pages' own links, breadth
    first in sorted order, at most `MOST` of them and at most `EACH` of one section (the path's first
    part), so a month of Days or a pager's every window does not crowd out the shelves."""
    seen: dict[str, str] = {}
    queue = list(SEEDS)
    sections: dict[str, int] = {}
    while queue and len(seen) < MOST:
        target = queue.pop(0)
        if target in seen:
            continue
        path, _, query = target.partition("?")
        response = site.respond(path, query)
        seen[target] = f"{response.status} {hashlib.sha256(response.body).hexdigest()}"
        found: set[str] = set()
        for href in LINK.findall(response.body.decode("utf-8", "replace")):
            parts = urlsplit(unescape(href))
            if (
                parts.scheme
                or parts.netloc
                or not parts.path.startswith("/")
                or parts.path.startswith(NOT_PAGES)
            ):
                continue
            found.add(unquote(parts.path) + (f"?{parts.query}" if parts.query else ""))
        for link in sorted(found):
            if link in seen or link in queue:
                continue
            section = link.split("?")[0].split("/")[1]
            if sections.get(section, 0) >= EACH.get(section, EACH_OTHER):
                continue
            sections[section] = sections.get(section, 0) + 1
            queue.append(link)
    return seen


@pytest.mark.parametrize("name", sorted(RECORDS))
def test_every_page_is_as_it_was(name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with _fixed():
        lb, now = RECORDS[name](tmp_path, monkeypatch)
    monkeypatch.setattr(gaps, "now", lambda: now)  # `/gaps` reads the wall clock, not the Site's: its own
    site = serve.Site(Logbook(lb.root), now=lambda: now)
    pages = crawl(site)
    assert len(pages) > len(SEEDS)
    golden = json.loads(GOLDEN.read_text(encoding="utf-8")) if GOLDEN.exists() else {}
    if WRITE:
        golden[name] = {"head": str(lb.meta["head"]), "pages": pages}
        GOLDEN.write_bytes((json.dumps(golden, indent=1, sort_keys=True) + "\n").encode("utf-8"))
        return
    assert name in golden, f"no golden pages for {name}: LOGBOOK_GOLDEN_WRITE=1 writes them"
    assert str(lb.meta["head"]) == golden[name]["head"], "the record itself changed: not the pages' doing"
    changed = sorted(p for p in golden[name]["pages"] if pages.get(p) != golden[name]["pages"][p])
    assert not changed, f"{len(changed)} pages of {name} are not as they were: {changed[:10]}"
    assert sorted(pages) == sorted(golden[name]["pages"])
    # every page again, the other way round, none of them kept: what the server reads once and hands
    # to every page (`Site.shared`) is the same for each, whichever page read it first
    monkeypatch.setattr(site, "_keep", lambda etag, response: None)
    monkeypatch.setattr(site, "_kept", {})
    again = {}
    for target in reversed(list(pages)):
        path, _, query = target.partition("?")
        response = site.respond(path, query)
        again[target] = f"{response.status} {hashlib.sha256(response.body).hexdigest()}"
    assert again == pages


def test_the_same_record_gives_the_same_pages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The digests are a function of the record: built twice in two folders, the persona's fortnight
    gives the same head and the same page for every path (the folder's name is on no page)."""
    found = []
    for folder in ("a", "b"):
        with _fixed():
            lb, now = _persona(tmp_path / folder, monkeypatch)
        instant = _instant(now)
        monkeypatch.setattr(gaps, "now", instant)
        found.append((str(lb.meta["head"]), crawl(serve.Site(Logbook(lb.root), now=instant))))
    assert found[0] == found[1]
