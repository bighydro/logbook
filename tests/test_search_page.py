"""`/search?q=…` in the Library (`logbook/contrib/search_page.py`): the words of the record found by
the function `logbook search` calls, every hit held to the page's tier gate, each with its day (a link
to its row on the Day), its kind, a short excerpt with the match marked and its line's id; filters by
kind and year and the pages as links; an empty query the form alone; nothing written, no script, no
connection, no number beside a person's name; phone width first. On a synthetic record of the Oslo
persona, who does not exist."""

from __future__ import annotations

import re
from pathlib import Path

import page_text
import phone_width
import pytest

from logbook.contrib import search_page, serve
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
HARBOUR = 120  # notes that say "harbour": two full pages and a third of twenty
NAMES = ("Kari", "Ines", "Ola", "Per", "Hansen", "Nordmann")  # the persona's people


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """A note and a calendar entry that name Kari at tiers 2 and 1, a tier-3 mail that names her too,
    a note with markup in it, a retracted note, and 120 notes that say "harbour" over the summer."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append(
        at="2026-06-10T18:00:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "text": "Dinner with Kari at the cafe, running late"},
    )
    lb.append(
        at="2025-07-01T09:00:00Z",
        source="ics",
        kind="event",
        tier=1,
        payload={"schema": "event/v1", "raw_id": "ev:1", "title": "Sailing Solvind with Kari"},
    )
    lb.append(
        at="2026-06-11T09:00:00Z",
        source="mail",
        kind="mail",
        tier=3,
        payload={
            "schema": "mail/v1",
            "raw_id": "m:1",
            "thread": "m:1",
            "from": {"email": "pharmacy@example.org", "name": "Apotek Example"},
            "to": [{"email": "kari.nordmann@example.org"}],
            "subject": "Receipt for Kari",
            "direction": "received",
            "body": "Your prescription is ready.",
        },
    )
    lb.append(
        at="2026-06-12T10:00:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "text": "Per wrote <b>bold</b> & left the marina"},
    )
    gone = lb.append(
        at="2026-06-13T10:00:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "text": "A retracted line about the lighthouse"},
    )
    lb.retract(int(gone["seq"]), "wrong day", at="2026-06-13T11:00:00Z")
    for n in range(HARBOUR):
        lb.append(
            at=f"2026-{7 + n // 30:02d}-{1 + n % 30:02d}T08:00:00Z",
            source="manual",
            kind="note",
            tier=2,
            payload={"schema": "note/v1", "text": f"Harbour log, entry {n}: Solvind moored"},
        )
    return lb


def _get(site: serve.Site, path: str, query: str = "") -> str:
    r = site.respond(path, query)
    assert r.status == 200, r.body.decode("utf-8")
    return r.body.decode("utf-8")


def _hits(page: str) -> list[str]:
    return re.findall(r'<li class="hit"[^>]*>.*?</li>', page, re.S)


def test_a_hit_at_the_gate_shows_and_one_above_it_is_absent(lb: Logbook) -> None:
    gated = serve.Site(lb, tiers=(1, 2))
    page = _get(gated, "/search", "q=kari")
    assert len(_hits(page)) == 2  # the note at 2 and the calendar entry at 1
    assert "Dinner with" in page and "Sailing Solvind" in page
    assert "Receipt" not in page and "pharmacy" not in page and '<span class="kind">mail</span>' not in page
    assert "nothing read above tier 2" in page
    # the Library reads every tier on this machine, as every other page of `logbook serve` does
    every = _get(serve.Site(lb), "/search", "q=kari")
    assert len(_hits(every)) == 3 and "Receipt for" in every
    # a gate of tier 1 alone: the calendar entry, never the note
    only = _get(serve.Site(lb, tiers=(1,)), "/search", "q=kari")
    assert len(_hits(only)) == 1 and "Sailing Solvind" in only and "Dinner" not in only


def test_each_hit_has_its_day_its_kind_an_excerpt_marked_and_its_line_id(lb: Logbook) -> None:
    site = serve.Site(lb, tiers=(1, 2))
    page = _get(site, "/search", "q=kari")
    with lb.index() as idx:
        note = next(line for line in idx.day("2026-06-10") if line["kind"] == "note")
    line_id = str(note["id"])
    (hit,) = [h for h in _hits(page) if "Dinner" in h]
    assert f'href="/day/2026-06-10#l-{line_id}"' in hit  # its row on its Day
    assert f'id="l-{line_id}"' in _get(site, "/day/2026-06-10")  # and the Day has that row
    assert '<span class="kind">note</span>' in hit
    assert "Dinner with <mark>Kari</mark> at the cafe" in hit
    assert "[Kari]" not in page  # the CLI's brackets are the mark, never text
    assert f'href="/line/{line_id}"' in hit and line_id in page_text.seen(hit)


def test_the_excerpt_is_escaped(lb: Logbook) -> None:
    page = _get(serve.Site(lb), "/search", "q=marina")
    (hit,) = _hits(page)
    assert "<b>" not in hit and "&lt;b&gt;bold&lt;/b&gt; &amp; left the <mark>marina</mark>" in hit


def test_a_retracted_line_is_never_a_hit(lb: Logbook) -> None:
    page = _get(serve.Site(lb), "/search", "q=lighthouse")
    assert _hits(page) == []


def test_paging_is_links_of_fifty(lb: Logbook) -> None:
    site = serve.Site(lb)
    first = _get(site, "/search", "q=harbour")
    assert len(_hits(first)) == search_page.PAGE == 50
    assert "page 1" in page_text.seen(first)
    assert 'href="/search?q=harbour&amp;page=2"' in first and "page=0" not in first
    second = _get(site, "/search", "q=harbour&page=2")
    assert len(_hits(second)) == 50
    assert 'href="/search?q=harbour"' in second and 'href="/search?q=harbour&amp;page=3"' in second
    third = _get(site, "/search", "q=harbour&page=3")
    assert len(_hits(third)) == HARBOUR - 100 and "page=4" not in third
    assert 'class="pager"' not in _get(site, "/search", "q=kari")  # one page: no pager
    ids = [re.findall(r'href="/line/([^"]+)"', p) for p in (first, second, third)]
    assert len({i for page in ids for i in page}) == HARBOUR  # every hit on exactly one page
    for bad in ("0", "-1", "two", str(search_page.MAX_PAGE + 1)):
        assert site.respond("/search", f"q=harbour&page={bad}").status == 400


def test_filters_are_links_of_kind_and_year(lb: Logbook) -> None:
    site = serve.Site(lb)
    page = _get(site, "/search", "q=kari")
    assert 'href="/search?q=kari&amp;kind=note"' in page and 'href="/search?q=kari&amp;kind=mail"' in page
    assert 'href="/search?q=kari&amp;year=2025"' in page and 'href="/search?q=kari&amp;year=2026"' in page
    notes = _get(site, "/search", "q=kari&kind=note")
    assert len(_hits(notes)) == 1 and "Dinner" in notes
    assert 'href="/search?q=kari"' in notes  # the filter taken off is a link too
    year = _get(site, "/search", "q=kari&year=2025")
    assert len(_hits(year)) == 1 and "Sailing Solvind" in year
    both = _get(site, "/search", "q=harbour&kind=note&year=2026&page=2")
    assert (
        len(_hits(both)) == 50 and 'href="/search?q=harbour&amp;kind=note&amp;year=2026&amp;page=3"' in both
    )
    assert site.respond("/search", "q=kari&kind=location").status == 400
    assert site.respond("/search", "q=kari&year=26").status == 400


def test_a_filter_never_says_what_the_gate_holds_back(lb: Logbook) -> None:
    gated = serve.Site(lb, tiers=(1, 2))
    page = _get(gated, "/search", "q=kari")
    assert 'href="/search?q=kari&amp;kind=mail"' in page  # every kind is offered, none counted
    held = _get(gated, "/search", "q=kari&kind=mail")
    assert _hits(held) == [] and "Nothing in the record matches kari as a mail." in page_text.seen(held)
    assert "Receipt" not in held


def test_an_empty_query_is_the_form_alone(lb: Logbook) -> None:
    site = serve.Site(lb)
    for query in ("", "q=", "q=+", "q=-+*"):
        page = _get(site, "/search", query)
        assert '<form class="search" method="get" action="/search">' in page
        assert 'class="hits"' not in page and "matches" not in page and "kind=" not in page
        main = page.split("<main>")[1].split("</main>")[0]
        assert re.sub(r"<form.*?</form>", "", main, flags=re.S).strip() == "<h1>Search</h1>"


def test_a_query_with_no_hit_says_so_in_one_sentence(lb: Logbook) -> None:
    page = _get(serve.Site(lb), "/search", "q=zzyzx")
    main = page.split("</form>")[1].split("</main>")[0]
    assert page_text.seen(main).strip() == "Nothing in the record matches zzyzx."
    assert 'value="zzyzx"' in page  # the form keeps what was asked


def test_no_script_no_write_no_reference_away_and_no_connection(lb: Logbook, no_network: list[str]) -> None:
    site = serve.Site(lb)
    for query in ("", "q=kari", "q=harbour&kind=note&year=2026&page=2", "q=zzyzx"):
        r = site.respond("/search", query)
        text = r.body.decode("utf-8")
        assert r.status == 200 and r.csp == serve.CSP and "script-src" not in r.csp
        assert "<script" not in text.lower() and 'method="post"' not in text.lower()
        assert "http://" not in text and "https://" not in text and "//" not in re.sub(r"https?://", "", text)
        for ref in re.findall(r'(?:href|src|action)="([^"]*)"', text):
            assert ref.startswith("/"), ref
        assert r.etag is not None  # a page of the record at its head, kept and asked again
    assert no_network == []
    assert serve.Site(lb).respond("/search", "q=kari", None).body == site.respond("/search", "q=kari").body


def test_no_number_beside_a_persons_name(lb: Logbook) -> None:
    page = _get(serve.Site(lb), "/search", "q=kari")
    assert "/people/" not in page  # no person facet, no person link
    # the page's own words, the excerpts (the record's words) left out
    chrome = page_text.seen(re.sub(r'<q class="excerpt">.*?</q>', "", page, flags=re.S))
    for name in NAMES:
        assert re.search(rf"{name}\W{{0,3}}\d|\d\W{{0,3}}{name}", chrome) is None, name


def test_phone_width_first_and_touch_targets(lb: Logbook) -> None:
    site = serve.Site(lb)
    for query in ("", "q=kari", "q=harbour&page=2"):
        page = _get(site, "/search", query)
        assert phone_width.problems(page) == [], query
        assert phone_width.phone_breakpoints(phone_width.parse(page)[1]), query
    css = search_page.SEARCH_STYLE
    for selector in ("form.search input", "form.search button", "p.facets a", "p.pager a"):
        assert re.search(rf"{re.escape(selector)}[^{{]*\{{[^}}]*min-height:2\.75rem", css), selector


def test_one_product_the_day_pages_tokens(lb: Logbook) -> None:
    assert search_page.TOKENS in serve.STYLE  # the copy is the Day's own, byte for byte
    assert search_page.SEARCH_STYLE.startswith(search_page.TOKENS)
    assert '<a href="/search">search</a>' in serve.NAV


def test_an_exported_site_has_no_search(lb: Logbook) -> None:
    static = serve.Site(lb, href=lambda path: path)
    text = search_page.page_search(static, {"q": "kari"})
    assert "<form" not in text and "Dinner" not in text


def _notes(lb: Logbook, word: str, n: int, tiers: tuple[int, ...] = (2,)) -> None:
    for i in range(n):
        lb.append(
            at=f"2026-0{1 + i // 28 % 9}-{1 + i % 28:02d}T09:00:00Z",
            source="manual",
            kind="note",
            tier=tiers[i % len(tiers)],
            payload={"schema": "note/v1", "text": f"The {word} at Oslo, number {i}"},
        )


def test_a_gate_of_some_tiers_still_fills_its_pages(lb: Logbook) -> None:
    _notes(lb, "fjord", 120, tiers=(1, 2))  # every other one tier 2, which a gate of 1 and 3 holds back
    site = serve.Site(lb, tiers=(1, 3))
    first = _get(site, "/search", "q=fjord")
    assert len(_hits(first)) == 50 and "page=2" in first
    second = _get(site, "/search", "q=fjord&page=2")
    assert len(_hits(second)) == 10 and "page=3" not in second
    assert '<span class="kind">note</span>' in second and "tier 2" not in page_text.seen(second)


@pytest.mark.parametrize("n", [50, 100])
def test_a_last_full_page_offers_no_next(lb: Logbook, n: int) -> None:
    _notes(lb, "anchorage", n)
    site = serve.Site(lb)
    last = _get(site, "/search", f"q=anchorage&page={n // 50}")
    assert len(_hits(last)) == 50 and f"page={n // 50 + 1}" not in last


def test_every_link_to_a_row_on_the_day_lands_on_it(lb: Logbook) -> None:
    """The Day lists a note, a mail and a calendar entry as rows of their own (`l-ID`); a message is
    under its conversation, a page browsed or a task among the day's lines: a hit of those links to
    the Day itself, never to an anchor the Day does not have."""
    day = "2026-06-20"
    said = {
        "mail": {"raw_id": "m:9", "thread": "m:9", "subject": "Lofoten mooring", "direction": "received",
                 "from": {"email": "marina@example.org"}, "body": "Lofoten is due"},
        "message": {"raw_id": "s:9", "chat": {"id": "c:1", "type": "direct", "name": "Per Hansen"},
                    "from_me": False, "sender": {"kind": "phone", "value": "+447700900123"},
                    "text": "Lofoten is ready"},
        "event": {"raw_id": "ev:9", "title": "Lofoten haul-out"},
        "task": {"raw_id": "t:9", "title": "Varnish Lofoten"},
        "browse": {"raw_id": "b:9", "title": "Lofoten chandlery", "url": "https://example.org/solvind"},
        "highlight": {"raw_id": "h:9", "text": "Lofoten heels well"},
        "watch": {"raw_id": "w:9", "title": "Lofoten documentary"},
        "listen": {"raw_id": "li:9", "title": "Lofoten shanty"},
        "voice-memo": {"raw_id": "v:9", "transcript": "Lofoten needs fuel"},
    }  # fmt: skip
    for hour, (kind, payload) in enumerate(said.items()):
        lb.append(
            at=f"{day}T{8 + hour:02d}:00:00Z",
            source="manual",
            kind=kind,
            tier=2,
            payload={"schema": f"{kind}/v1", **payload},
        )
    site = serve.Site(lb)
    found = _get(site, "/search", "q=lofoten")
    assert len(_hits(found)) == len(said)
    on_day = _get(site, f"/day/{day}")
    anchors = re.findall(rf'href="/day/{day}#(l-[^"]+)"', found)
    assert len(anchors) >= 2  # the mail and the calendar entry at least
    for anchor in anchors:
        assert f'id="{anchor}"' in on_day, anchor
    assert len(re.findall(rf'href="/day/{day}"', found)) >= len(said) - len(anchors)


def test_a_bracket_the_record_holds_is_not_a_mark(lb: Logbook) -> None:
    lb.append(
        at="2026-06-14T10:00:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "text": "Per said [urgent] the boatyard gate in Zürich is broken"},
    )
    site = serve.Site(lb)
    (hit,) = _hits(_get(site, "/search", "q=boatyard"))
    assert "[urgent]" in hit and "<mark>urgent</mark>" not in hit and "<mark>boatyard</mark>" in hit
    (accent,) = _hits(_get(site, "/search", "q=zurich+boatyard"))
    assert "<mark>Zürich</mark>" in accent  # the index folds the accent, and so does the mark
    (prefix,) = _hits(_get(site, "/search", "q=boatya*"))
    assert "<mark>boatyard</mark>" in prefix


def test_what_the_page_refuses(lb: Logbook) -> None:
    site = serve.Site(lb)
    for query in ("q=kari&year=2026%0A", "q=&kind=location", "q=&page=0", "q=kari&year=twenty"):
        assert site.respond("/search", query).status == 400, query


def test_a_filter_that_finds_nothing_says_the_year_first(lb: Logbook) -> None:
    page = _get(serve.Site(lb), "/search", "q=marina&year=2025")
    assert "In 2025, nothing in the record matches marina." in page_text.seen(page)
    assert 'href="/search?q=marina"' in page  # the filter can be taken off
