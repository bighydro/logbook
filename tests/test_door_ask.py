"""Ask v1 (RFC 0047 §4.5): `/ask?q=…`, the field at the top of every page, answered with moments
(`logbook/contrib/door_ask.py`): one row per day, newest first, each with the day (a link to its Day),
where the night was, who was there (names only, each a link to their page) and the words that matched
(the source in pencil, the match marked, a link to the row on the Day); held to the page's tier gate;
superseded hits marked, `?standing=1` leaving them out; the pages as links; the field alone and one
sentence when nothing is asked, one sentence when nothing is found. Nothing written, no script, nothing
fetched, no number beside a person's name, phone width first.

On the Oslo persona's fortnight (Kari and Ola Nordmann, who do not exist), with a few more notes of its
own, on an empty record and on the demo record; every address at example.org; no test opens a
connection."""

from __future__ import annotations

import html
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import beside_a_name
import page_text
import phone_width
import pytest
from dream_fortnight import fortnight, message
from persona import OLA, OLA_ID, note, utc
from test_no_count_beside_a_name import beside

from logbook.contrib import demo, door_ask, doors, library_build, serve
from logbook.core.store import Logbook

NOW = datetime(2026, 6, 22, 9, 0, tzinfo=UTC)  # the Monday after the fortnight
NAMES = ("Kari", "Ola", "Nordmann", "Ines", "Per", "Hansen")  # the persona's people
SAILS = 30  # notes that say "sail" over the summer: two full pages and half a third
NUMBER_BESIDE = r"(\d[\s(:×x#·,]*{name})|({name}\??[\s(:×x#·,]*\d)"


@pytest.fixture(scope="module")
def pristine(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The fortnight; a note that a later note corrects; `SAILS` notes that say "sail", one a day
    from July on; two notes on one day that say "kelp"; Ola's message whose first words are a number,
    which the excerpt would set after his name; and a note whose own words set one beside it."""
    with pytest.MonkeyPatch.context() as mp:
        root = tmp_path_factory.mktemp("door-ask") / "lb"
        mp.setenv("LOGBOOK_HOME", str(root))
        lb = fortnight(root)
        first = lb.append(**note(utc("2026-06-13", "10:00"), "The lighthouse keeper rang about the mooring"))
        corrected = note(
            utc("2026-06-13", "11:00"), "The harbour master rang about the mooring, not the lighthouse"
        )
        corrected["payload"]["supersedes"] = str(first["id"])
        lb.append(**corrected)
        lines: list[dict[str, Any]] = []
        for n in range(SAILS):
            day = f"2026-{7 + n // 28:02d}-{1 + n % 28:02d}"
            lines.append(note(utc(day, "18:00"), f"Went for a sail on the fjord, log {n}"))
        lines.append(note(utc("2026-07-02", "09:00"), "Kelp on the anchor chain"))
        lines.append(note(utc("2026-07-02", "20:00"), "More kelp at dusk"))
        lines.append(message(utc("2026-07-03", "08:00"), "2 dinghies at the pontoon", {**OLA, "name": "Ola"}))
        lines.append(note(utc("2026-07-04", "21:00"), "Ola Nordmann 3 times at the jetty this week"))
        lb.append_many(lines)
        return lb.root


@pytest.fixture
def lb(pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    shutil.copytree(pristine, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook(root)


def _site(lb: Logbook, **kw: Any) -> serve.Site:
    return serve.Site(lb, now=lambda: NOW, **kw)


def _get(site: serve.Site, query: str = "", path: str = "/ask") -> str:
    response = site.respond(path, query)
    assert response.status == 200, response.body.decode("utf-8")[:500]
    return response.body.decode("utf-8")


def _main(page: str) -> str:
    return page.split('<main class="door">')[1].split("</main>")[0]


def _moments(page: str) -> list[str]:
    return re.findall(r'<li class="moment">.*?</ol>\n</li>', page, re.S)


def _days(page: str) -> list[str]:
    return re.findall(r'<a href="/day/(\d{4}-\d{2}-\d{2})" class="when">', page)


def _said(page: str) -> str:
    return page_text.seen(_main(page)).strip()


# -- the field --------------------------------------------------------------------------------------------


def test_the_field_on_every_door_asks_ask(lb: Logbook) -> None:
    assert doors.ASK == door_ask.PATH == "/ask"
    today = _get(_site(lb), path="/")
    assert '<form class="ask" method="get" action="/ask" role="search">' in today
    assert 'name="q"' in today and 'method="post"' not in today.split("</header>")[0]
    # the page of an answer keeps the words in the field; every other page's field is empty
    answer = _get(_site(lb), "q=lunch")
    assert 'name="q" placeholder="Ask: a name, a place, a word" value="lunch"' in answer
    assert "value=" not in today.split("</header>")[0]


def test_an_empty_question_is_the_field_and_one_sentence(lb: Logbook) -> None:
    site = _site(lb)
    for query in ("", "q=", "q=+", "q=-+*"):
        page = _get(site, query)
        assert _said(page).split()[: 1 + len(door_ask.EMPTY.split())] == ["Ask", *door_ask.EMPTY.split()]
        assert door_ask.EMPTY in page and not _moments(page) and "page=" not in page
        # the field beside the sentence, with its button: the header's is far from it on a wide screen
        assert '<form class="asked" method="get" action="/ask" role="search">' in page
        assert "<button>Ask</button>" in page


def test_words_with_no_hit_say_so_in_one_sentence(lb: Logbook) -> None:
    page = _get(_site(lb), "q=zzyzx")
    assert door_ask.NOTHING == "Nothing in the record says that. Try fewer words, or a name."
    assert door_ask.NOTHING in page and not _moments(page)
    assert "“zzyzx”" in page  # the words asked are the page's title


def test_a_moment_is_its_day_its_place_its_people_and_the_words(lb: Logbook) -> None:
    page = _get(_site(lb), "q=lunch")
    (moment,) = _moments(page)
    assert '<a href="/day/2026-06-10" class="when">Wednesday 10 June 2026</a>' in moment
    assert '<a href="/world?from=2026-06-10&amp;to=2026-06-10">Home</a>' in moment  # the night's place
    assert '<span class="source">calendar</span><q>' in moment and "<mark>Lunch</mark>" in moment
    assert " with " not in page_text.seen(moment)  # the Day saw nobody with the owner then: nor does Ask
    with lb.index() as idx:
        (event,) = [line for line in idx.day("2026-06-10") if line["kind"] == "event"]
    assert f'href="/day/2026-06-10#l-{event["id"]}" class="words"' in moment  # its row on the Day
    assert f'id="l-{event["id"]}"' in _get(_site(lb), path="/day/2026-06-10")  # and the Day has the row


def test_the_people_are_the_days_company_names_only(lb: Logbook) -> None:
    page = _get(_site(lb), "q=dinner")  # Tuesday in Zürich: dinner with Ola, by the calendar and a note
    moment = next(m for m in _moments(page) if "/day/2026-06-16" in m)
    assert f'with <a href="/people/{OLA_ID}">Ola Nordmann</a>' in moment
    assert '<a href="/world?from=2026-06-16&amp;to=2026-06-16">near Zurich</a>' in moment  # no coordinates
    assert door_ask.place_words("53.5998,10.0130 (Hamburg)") == "near Hamburg"
    assert door_ask.place_words("59.9100,10.7600 near Office, 1.2 km") == "near Office"
    assert door_ask.place_words("59.9100,10.7600") == door_ask.UNNAMED
    assert door_ask.place_words("ZRH, Zurich") == "ZRH, Zurich" and door_ask.place_words("Home") == "Home"


def test_each_source_is_in_the_owner_s_words(lb: Logbook) -> None:
    page = _get(_site(lb), "q=boat")  # the call with Ola, its title
    assert '<span class="source">call</span>' in page
    assert f'<a href="/people/{OLA_ID}">Ola Nordmann</a>' in page  # he spoke: he was there
    note_page = _get(_site(lb), "q=harbour+map")
    assert (
        '<span class="source">note</span>' in note_page
        and "<mark>harbour</mark> <mark>map</mark>" in note_page
    )


def test_one_row_a_day_newest_first_across_every_page(lb: Logbook) -> None:
    site = _site(lb)
    days = [day for n in (1, 2, 3) for day in _days(_get(site, f"q=sail&page={n}"))]
    assert len(days) == SAILS == len(set(days)), "one row a day, each day once in the whole answer"
    assert days == sorted(days, reverse=True), "newest first, across the pages"
    (kelp,) = _moments(_get(_site(lb), "q=kelp"))
    assert kelp.count('class="words"') == 2  # two notes on one day: one row


def test_the_owner_s_words_lead_their_day(lb: Logbook) -> None:
    lb.append(**note(utc("2026-06-10", "16:00"), "Lunch went long, good to see her"))
    (moment,) = _moments(_get(_site(Logbook(lb.root)), "q=lunch"))
    sources = re.findall(r'<span class="source">([^<]+)</span>', moment)
    assert sources == ["note", "calendar"]  # the note, written after, comes first


def test_an_address_alone_is_left_out_of_the_words(lb: Logbook) -> None:
    page = _get(_site(lb), "q=lunch")
    assert "kari.nordmann@example.org" not in page.split("</header>")[1]
    assert door_ask.readable("[Lunch] · kari.nordmann@example.org") == "[Lunch]"
    assert door_ask.readable("Lunch · [kari].nordmann@example.org") == "Lunch · [kari].nordmann@example.org"


def test_the_pages_are_links(lb: Logbook) -> None:
    site = _site(lb)
    first = _get(site, "q=sail")
    assert len(_moments(first)) == door_ask.DAYS
    assert 'href="/ask?q=sail&amp;page=2"' in first and "page=0" not in first
    second = _get(site, "q=sail&page=2")
    assert 'href="/ask?q=sail"' in second and 'href="/ask?q=sail&amp;page=3"' in second
    third = _get(site, "q=sail&page=3")
    assert len(_moments(third)) == SAILS - 2 * door_ask.DAYS
    assert "page=4" not in third
    assert 'class="pager"' not in _get(site, "q=lunch")  # one page: no pager
    past = _get(site, "q=sail&page=9")
    assert "Page 9 is past the last day of the answer" in past and not _moments(past)
    for bad in ("0", "-1", "two", str(door_ask.MAX_PAGE + 1)):
        assert site.respond("/ask", f"q=sail&page={bad}").status == 400
    assert site.respond("/ask", "q=sail&standing=yes").status == 400


def test_a_superseded_hit_is_marked_and_standing_leaves_it_out(lb: Logbook) -> None:
    site = _site(lb)
    page = _get(site, "q=mooring")
    with lb.index() as idx:
        _first, second = [line for line in idx.day("2026-06-13") if line["kind"] == "note"]
    (moment,) = _moments(page)
    assert moment.count('class="words"') == 2  # both, never silently dropped
    assert f'<p class="superseded"><a href="/line/{second["id"]}">corrected later</a></p>' in moment
    assert 'href="/ask?q=mooring&amp;standing=1"' in page and door_ask.LEAVE_OUT in page
    standing = _get(site, "q=mooring&standing=1")
    (moment,) = _moments(standing)
    assert moment.count('class="words"') == 1 and "harbour master" in moment and "keeper" not in moment
    assert 'class="superseded"' not in standing
    assert 'href="/ask?q=mooring"' in standing and door_ask.TAKE_IN in standing
    # only the superseded line says it: the standing answer is nothing, and says so, with the way back
    only = _get(site, "q=keeper&standing=1")
    assert door_ask.NOTHING in only and 'href="/ask?q=keeper"' in only


def test_a_retracted_line_is_never_a_hit(lb: Logbook) -> None:
    gone = lb.append(**note(utc("2026-06-14", "10:00"), "A word about the quarantine flag"))
    lb.retract(int(gone["seq"]), "wrong day", at=utc("2026-06-14", "11:00"))
    page = _get(_site(Logbook(lb.root)), "q=quarantine")
    assert door_ask.NOTHING in page


# -- the gate ---------------------------------------------------------------------------------------------


def test_a_page_at_tier_1_shows_no_tier_2_line_name_or_count(lb: Logbook) -> None:
    one = _site(lb, tiers=(1,))
    page = _get(one, "q=lunch")  # the calendar entry is tier 1
    (moment,) = _moments(page)
    assert "<mark>Lunch</mark>" in moment and "Home" in moment
    assert "Read at tier 1." in page
    for words in ("boat", "harbour", "sail", "mooring"):  # a call, notes: tier 2
        held = _get(one, f"q={words}")
        assert door_ask.NOTHING in held and not _moments(held), words
        assert "Ola" not in held and "Kari" not in held
    dinner = _get(one, "q=dinner")  # the calendar entry at tier 1; Ola's name rests on tier 2
    assert _moments(dinner) and "Ola" not in dinner and "/people/" not in dinner
    every = _get(_site(lb, tiers=(1, 2)), "q=dinner")
    assert "Ola Nordmann" in every and f"/people/{OLA_ID}" in every


# -- the rules of every door ------------------------------------------------------------------------------


def _number_beside_a_name(page: str) -> list[str]:
    """Every name on the page with a number beside it, over its text (the excerpts, the record's own
    words, stand as one word, so what is around them is read), its titles and its aria-labels."""
    text = page_text.seen(re.sub(r"<q>.*?</q>", "<q>words</q>", page, flags=re.S))
    attrs = " | ".join(re.findall(r'(?:title|aria-label)="([^"]*)"', page))
    found = []
    for name in NAMES:
        pattern = NUMBER_BESIDE.format(name=re.escape(name))
        if re.search(pattern, text) or re.search(pattern, html.unescape(attrs)):
            found.append(name)
    return found


@pytest.mark.parametrize("query", ["q=lunch", "q=boat", "q=dinner", "q=sail", "q=sail&page=2", "q=mooring"])
def test_no_number_beside_a_persons_name(lb: Logbook, query: str) -> None:
    page = _get(_site(lb), query)
    assert _number_beside_a_name(page) == [], query


# every page and state of the door: each query, each page, the filter on and off, past the last page,
# nothing found, nothing asked, the gate at tier 1, a question that itself sets a number beside a name
STATES = (
    "", "q=lunch", "q=boat", "q=dinner", "q=sail", "q=sail&page=2", "q=sail&page=3", "q=sail&page=9",
    "q=mooring", "q=mooring&standing=1", "q=keeper&standing=1", "q=zzyzx", "q=kelp", "q=dinghies",
    "q=jetty", "q=Ola", "q=Kari", "q=Nordmann", "q=Ola+2026", "q=Kari+19:30",
)  # fmt: skip


@pytest.mark.parametrize("tiers", [None, (1,), (1, 2)])
def test_main_s_strong_guards_hold_on_every_page_and_state(
    lb: Logbook, tiers: tuple[int, ...] | None
) -> None:
    """Main's two guards (`test_no_count_beside_a_name.beside`: a number, a date or a clock touching a
    name through separators alone, or stuck to it; `beside_a_name.page`: the same a row at a time, as a
    reader sees the page), over the whole HTML, the record's own words in the excerpts included, the
    title and every attribute: no state of Ask sets a number beside a person's name."""
    site = _site(lb, tiers=tiers)
    for query in STATES:
        page = _get(site, query)
        attrs = "\n".join(html.unescape(a) for a in re.findall(r'(?:title|aria-label|alt)="([^"]*)"', page))
        assert beside(page) == [] and beside(attrs) == [], (query, beside(page) or beside(attrs))
        assert beside_a_name.page(page) == [], (query, beside_a_name.page(page))


def test_an_excerpt_never_sets_its_fields_so_a_number_touches_a_name(lb: Logbook) -> None:
    """Ola's message is his name, his number and his words, `2 dinghies …`: the search's excerpt runs
    them on with ` · `, which would set the words' first figure after his name. The number, a sender's
    reference, is left out like an address, and a field that begins with a digit is a line of its own."""
    page = _get(_site(lb), "q=dinghies")
    (moment,) = _moments(page)
    assert "<mark>dinghies</mark>" in moment and "+4790000001" not in moment
    assert door_ask.parts("Ola · [2] dinghies at the pontoon") == ["Ola", "[2] dinghies at the pontoon"]
    assert door_ask.parts("Lunch · the cafe · 12:00 · Kari") == ["Lunch · the cafe", "12:00", "Kari"]
    assert door_ask.parts("Went for a [sail] · log 4") == ["Went for a [sail] · log 4"]
    assert door_ask.readable("Ola · +4790000001 · 2 [dinghies]") == "Ola · 2 [dinghies]"


def test_an_excerpt_leaves_out_what_is_no_one_s_words() -> None:
    """A type or an app alone (`track`, `shazam`), and a name the excerpt cut at its edge, are no one's
    words: left out when another field holds the match, never when one holds it."""
    music = "track · Fjordsang · [Kari] Nordmann · shazam"
    assert door_ask.readable(music) == "Fjordsang · [Kari] Nordmann"
    cut = "…Nordmann · Mooring for the week · The east [berth] is free from Monday. Fuel dock opens at…"
    assert (
        door_ask.readable(cut)
        == "Mooring for the week · The east [berth] is free from Monday. Fuel dock opens at…"
    )
    assert door_ask.readable("[shazam] · track") == "[shazam]", "a field that holds the match stays"
    assert door_ask.readable("track · shazam") == "track · shazam", "with no match left, the excerpt as it is"
    calendar = "Lunch · [kari].nordmann@example.org · [Kari] Nordmann · the cafe"
    assert door_ask.readable(calendar) == "Lunch · [Kari] Nordmann · the cafe", (
        "an address goes, matched or not"
    )


def test_the_filter_says_when_it_is_on_and_the_page_when_there_are_pages(lb: Logbook) -> None:
    site = _site(lb)
    off = _get(site, "q=mooring")
    assert door_ask.LEFT_OUT not in off and 'class="on"' not in off
    assert "page 1" not in page_text.seen(_main(off)), "one page: no page number"
    on = _get(site, "q=mooring&standing=1")
    assert door_ask.LEFT_OUT in on and f'<a class="on" href="/ask?q=mooring">{door_ask.TAKE_IN}</a>' in on
    assert "page 1" in page_text.seen(_main(_get(site, "q=sail"))), "several pages: its number"


def test_words_that_set_a_number_beside_a_name_are_on_their_day_only(lb: Logbook) -> None:
    """The owner's own note says `Ola Nordmann 3 times`: Ask shows its day, its source and a link to its
    row on the Day, and none of its words (`HELD`), so no page of the door sets the figure by the name;
    the Day, where the note is the owner's, keeps them."""
    page = _get(_site(lb), "q=jetty")
    (moment,) = _moments(page)
    assert door_ask.HELD in moment and "jetty" not in moment.split('class="source">note</span>')[1]
    assert "/day/2026-07-04#l-" in moment


def test_a_question_that_sets_a_number_beside_a_name_is_kept_in_the_field_only(lb: Logbook) -> None:
    page = _get(_site(lb), "q=Ola+2026")
    assert 'value="Ola 2026"' in page, "the field keeps what was typed"
    assert "<title>Ask · Logbook</title>" in page and f"<h1>{door_ask.ASKED}</h1>" in page
    assert "Ola 2026" not in page.replace('value="Ola 2026"', "")
    asked = _get(_site(lb), "q=Ola")
    assert "<title>Ask: Ola · Logbook</title>" in asked and "<h1>\u201cOla\u201d</h1>" in asked


def test_no_script_no_write_nothing_fetched(lb: Logbook, no_network: list[str]) -> None:
    site = _site(lb)
    for query in ("", "q=lunch", "q=sail&page=2", "q=mooring&standing=1", "q=zzyzx"):
        r = site.respond("/ask", query)
        text = r.body.decode("utf-8")
        assert r.status == 200 and r.csp == doors.CSP and "script-src" not in (r.csp or "")
        assert "<script" not in text.lower() and 'method="post"' not in text.lower()
        assert "http://" not in text and "https://" not in text
        for ref in re.findall(r'(?:href|src|action)="([^"]*)"', text):
            assert ref.startswith("/") and not ref.startswith("//"), ref
        assert r.etag is not None  # a page of the record at its head, kept and asked again
    assert no_network == []


def test_phone_width_first_and_touch_targets(lb: Logbook) -> None:
    site = _site(lb)
    for query in ("", "q=lunch", "q=sail&page=2", "q=zzyzx"):
        page = _get(site, query)
        assert phone_width.problems(page) == [], query
    css = door_ask.STYLE
    for selector in (".door-ask a.when", ".door-ask a.words", ".door-ask p.where a", ".door-ask p.pager a"):
        assert re.search(rf"{re.escape(selector)}[^{{]*\{{[^}}]*min-height:4[4-6]px", css), selector
    assert ":root" not in css  # the tokens are the frame's; a door only reads them
    assert all(
        rule.strip().startswith((".door-ask", "@media", "}"))
        for rule in re.findall(r"(?:^|\})([^{}]+)\{", css)
    )


def test_search_keeps_working_as_it_is(lb: Logbook) -> None:
    page = _get(_site(lb), "q=lunch", path="/search")
    assert '<form class="search" method="get" action="/search">' in page and "<mark>Lunch</mark>" in page


def test_ask_is_built_with_the_doors(lb: Logbook) -> None:
    assert door_ask.PATH in library_build.DOORS


def test_an_exported_site_has_no_server_to_ask(lb: Logbook) -> None:
    static = serve.Site(lb, now=lambda: NOW, href=lambda path: path)
    text = door_ask.page_ask(static, {"q": "lunch"})
    assert door_ask.NO_SERVER in text and "<form" not in text and "Lunch" not in text


# -- other records ----------------------------------------------------------------------------------------


def test_an_empty_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    site = _site(lb)
    assert door_ask.EMPTY in _get(site)
    assert door_ask.NOTHING in _get(site, "q=anything")


def test_the_demo_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "Demo"))
    lb = demo.generate(tmp_path / "Demo", days=30, seed=1)
    site = serve.Site(lb, now=lambda: datetime(2026, 7, 1, 10, 0, tzinfo=UTC))
    for words in ("Zürich", "berth", "Copenhagen"):
        page = _get(site, f"q={words}")
        assert _moments(page), words
        assert _number_beside_a_name(page) == [], words
        assert phone_width.problems(page) == [], words
