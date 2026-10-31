"""Life, the second door of the Library (RFC 0047 §4.2): `/life`, the chapter the owner is in, the
year's goals, one timeline of a life from its first day to a bounded future, and the Volumes at its
foot. Read-only, through the page's gate, every zoom and every move a link (RFC §5).

The record is the persona's fortnight (`persona.py`, 8 to 21 June 2026) with what the owner said about
it, written through the product's own writers: an earlier chapter (*The Copenhagen years*), the chapter
today is in (*Back in Oslo*, from 3 May, with its rules), a year goal and a life goal with reviews (one
of them asking to be looked at again on 1 September), the Zürich trip named *Zürich with Kari*, two
signed days, a reflection on one of them starred, and one chapter line with no first day. Nobody here
exists: the Oslo persona, addresses at example.org."""

from __future__ import annotations

import html
import json
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
from persona import persona_record, utc

from logbook.contrib import door_life, doors, journeys, library_build, serve
from logbook.core import chapter, goals, notes, signing, stars
from logbook.core.store import Logbook

NOW = datetime(2026, 6, 21, 18, 0, tzinfo=UTC)  # Sunday evening, the fortnight's last day
TODAY = "2026-06-21"
EARLIER = "The Copenhagen years"
CHAPTER = "Back in Oslo"
RULES = "the boat, the yard, Sundays at the cabin"
YEAR_GOAL = "Sail to Lofoten with Ola"
LIFE_GOAL = "Learn to read the weather"
TRIP_NAME = "Zürich with Kari"
REFLECTION = "A good weekend on the fjord; the anchor held all night."
UNDATED = "The year at sea"
LIFE = {"from": "1986-07-01", "to": "2035-12-31"}
NAMES = ("Kari Nordmann", "Ola Nordmann", "Kari", "Ola")
STATES = (
    "",
    "zoom=life",
    "zoom=year&at=2025",
    "at=2026-06",
    "at=2026-06-15&zoom=week",
    "zoom=day",
    "zoom=day&from=2025-12-25&to=2026-01-05",
    "trip=2026-06-15/2026-06-17",
)  # every view of the page: the zooms, a year with nothing in it, a window over New Year, a trip
REFERENCE = re.compile(
    r"""(?:href|src|action|formaction|poster|data|srcset|cite)\s*=\s*["']([^"']*)["']""", re.I
)


def _set_life(lb: Logbook, life: dict[str, Any] | None) -> None:
    """`life` in logbook.json, as the owner edits the file (there is no command that writes it)."""
    meta = json.loads(lb.meta_path.read_text(encoding="utf-8"))
    if life is None:
        meta.pop("life", None)
    else:
        meta["life"] = life
    lb.meta_path.write_bytes((json.dumps(meta, indent=2) + "\n").encode("utf-8"))


def life_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, life: bool = True) -> Logbook:
    lb = persona_record(tmp_path, monkeypatch)
    minutes = iter(range(60))
    with pytest.MonkeyPatch.context() as sitting:  # the owner's sitting, on its own clock
        sitting.setattr(goals, "now", lambda: NOW.replace(minute=next(minutes)))
        chapter.open_chapter(lb, EARLIER, start="2019-08-01", to="2026-05-02")
        chapter.open_chapter(lb, CHAPTER, start="2026-05-03", rules=RULES)
        year_goal = goals.add(lb, YEAR_GOAL, "year", start="2026-01-01")
        goals.add(lb, LIFE_GOAL, "life", start="2026-01-01")
        goals.review(lb, str(year_goal["id"]), "advancing", at="2026-06-01T18:00:00+02:00")
    lb.append(
        at="2026-06-20T18:00:00Z",
        source="manual",
        kind="review",
        tier=2,
        payload={
            "schema": "review/v1",
            "goal": str(year_goal["id"]),
            "disposition": "advancing",
            "period": "month",
            "extra": {"revisit": "2026-09-01"},
        },
        recorded_at="2026-06-20T18:00:00Z",
    )
    reflection = notes.write(lb, "2026-06-14", REFLECTION, notes.REFLECTION, "manual", today=TODAY)
    signing.sign(lb, "2026-06-10", at=utc("2026-06-10", "22:00"))
    signing.sign(lb, "2026-06-14", at=utc("2026-06-14", "22:00"))
    stars.star(lb, str(reflection["id"]))
    journeys.name(lb, "2026-06-15", TRIP_NAME, today=TODAY)
    lb.append(  # a chapter the owner has not dated yet
        at="2026-06-20T19:00:00Z",
        source="manual",
        kind="chapter",
        tier=2,
        payload={"schema": "chapter/v1", "name": UNDATED, "rules": ""},
    )
    lb = Logbook(lb.root)
    if life:
        _set_life(lb, LIFE)
    return Logbook(lb.root)


def _site(lb: Logbook, **kwargs: Any) -> serve.Site:
    return serve.Site(lb, now=lambda: NOW, **kwargs)


def _page(site: serve.Site, query: str = "") -> str:
    response = site.respond("/life", query)
    assert response.status == 200, (query, response.body[:400])
    return response.body.decode("utf-8")


class _Text(HTMLParser):
    """The page as a reader meets it: its text in order, and every title and aria-label on its own."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.labels: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("style", "script"):
            self._skip += 1
        for key, value in attrs:
            if key in ("title", "aria-label") and value:
                self.labels.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("style", "script"):
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def _read(text: str) -> tuple[str, list[str]]:
    parser = _Text()
    parser.feed(text)
    return " ".join(parser.parts), parser.labels


def _section(text: str, cls: str) -> str:
    found = re.search(rf'<section class="[^"]*\b{cls}\b[^"]*".*?</section>', text, re.S)
    assert found is not None, cls
    return found.group(0)


def _links(text: str) -> list[str]:
    return [html.unescape(h) for h in re.findall(r'href="([^"]*)"', text)]


# -- the setting -------------------------------------------------------------------------------------------


def test_the_life_setting_is_two_days_in_logbook_json() -> None:
    meta = {"timezone": "Europe/Oslo"}
    assert door_life.setting(meta) is None
    assert door_life.setting({**meta, "life": LIFE}) == ("1986-07-01", "2035-12-31")
    for wrong in ("1986", {"from": "1986-07-01"}, {"from": "1986-07-01", "to": "1980-01-01"}, {"from": 1986}):
        with pytest.raises(door_life.LifeError, match=r"logbook\.json"):
            door_life.setting({**meta, "life": wrong})


def test_without_the_setting_life_runs_from_the_first_day_to_the_end_of_next_year(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never to the last line the record holds: a calendar entry in 2055 draws no thirty years."""
    lb = life_record(tmp_path, monkeypatch, life=False)
    lb.append(
        at="2055-01-01T09:00:00Z",
        source="calendar",
        kind="event",
        tier=1,
        payload={"schema": "event/v1", "title": "The far appointment"},
    )
    text = _page(_site(Logbook(lb.root)), "zoom=life")
    assert "Your life, 2026 to 2027" in text
    assert "2055" not in _read(text)[0]


def test_the_setting_sets_the_bounds_and_a_wrong_one_is_said_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = life_record(tmp_path, monkeypatch)
    text = _page(_site(lb), "zoom=life")
    assert "Your life, 1986 to 2035" in text
    _set_life(lb, {"from": "July 1986"})
    text = _page(_site(Logbook(lb.root)))
    assert "Your life, 2026 to 2027" in text
    assert "logbook.json" in _read(text)[0], "the page says why it did not read the setting"


# -- the top: the chapter and the goals ---------------------------------------------------------------------


def test_this_chapter_and_its_rules_in_the_owner_s_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = _page(_site(life_record(tmp_path, monkeypatch)))
    found = _section(text, "chapter")
    assert "THIS CHAPTER · SINCE 3 MAY" in _read(found)[0].upper()  # a mono label, set in capitals
    assert CHAPTER in found and RULES in found
    assert 'class="ink' in found


def test_the_goals_of_the_year_and_for_life_with_their_last_look_and_the_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = _page(_site(life_record(tmp_path, monkeypatch)))
    found = _section(text, "goals")
    words, _labels = _read(found)
    assert "GOALS FOR 2026" in words.upper() and "FOR LIFE" in words.upper()  # mono labels, in capitals
    assert words.index(YEAR_GOAL) < words.upper().index("FOR LIFE") < words.index(LIFE_GOAL)
    assert "Reviewed 20 June" in words  # the standing review, in words
    assert "Next look: 1 September" in words
    assert "%" not in words and "score" not in words.lower()


def test_an_empty_record_says_what_fills_each_part(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    for query in ("", "zoom=life", "zoom=month", "zoom=week", "zoom=day"):
        text = _page(_site(lb), query)
        words = _read(text)[0]
        assert "No chapter yet." in words and "logbook chapter open" in words
        assert "logbook goal add" in words
    assert "Nothing on the line yet" in _read(_page(_site(lb)))[0]


def test_the_demo_record_opens_its_life(tmp_path: Path) -> None:
    from logbook.contrib import demo

    lb = demo.generate(tmp_path / "Demo", days=30, seed=1)
    site = serve.Site(lb, now=lambda: datetime(2026, 7, 1, 10, 0, tzinfo=UTC))
    text = _page(site)
    assert "Your life, 2026 to 2027" in text
    assert 'class="span trip' in text, "the month's trips on the year"
    for query in ("zoom=life", "zoom=month&at=2026-06", "zoom=week&at=2026-06-15", "zoom=day"):
        _page(site, query)


# -- the timeline --------------------------------------------------------------------------------------------


def test_the_year_opens_with_today_in_view(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    text = _page(_site(life_record(tmp_path, monkeypatch)))
    line = _section(text, "timeline")
    assert 'aria-current="page">Year<' in line
    assert line.count('class="month') == 12
    assert TRIP_NAME in line and CHAPTER in line and "First signed day" in line
    assert "NOW" in line and "AHEAD" in line
    assert line.count('class="dot signed') == 2
    assert (
        'href="/journeys/2026-06-15/2026-06-17"' in line or 'href="/life?trip=2026-06-15/2026-06-17"' in line
    )


def test_the_life_zoom_draws_the_whole_life_and_at_most_a_dozen_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = _page(_site(life_record(tmp_path, monkeypatch)), "zoom=life")
    line = _section(text, "timeline")
    for year in ("1990", "1995", "2000", "2025", "2030", "2035"):
        assert f">{year}<" in line, year
    assert "NOW" in line and "AHEAD" in line
    assert 'class="band chapter' in line and EARLIER in line and CHAPTER in line
    assert TRIP_NAME in line, "a trip the owner named"
    assert 'class="tick reflection' in line, "the starred reflection of a signed day"
    assert re.search(r'class="[^"]*\bbefore\b', line), "before the record began, drawn as such"
    assert len(re.findall(r'class="label\b', line)) <= 12


def test_silences_are_drawn_as_silence_never_as_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = life_record(tmp_path, monkeypatch)
    lb.append(
        at="2026-02-01T09:00:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "text": "A winter note."},
    )
    text = _page(_site(Logbook(lb.root)), "zoom=year&at=2026")
    line = _section(text, "timeline")
    assert re.search(r'class="[^"]*\bsilence\b', line)
    assert "error" not in _read(line)[0].lower()


def test_every_address_of_the_door_answers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    site = _site(life_record(tmp_path, monkeypatch))
    for query in (
        "",
        "zoom=life",
        "zoom=year",
        "zoom=year&at=2026",
        "at=2026",
        "year=2026",
        "at=2026-06",
        "zoom=month&at=2026-06",
        "at=2026-06-15",
        "at=2026-06-15&zoom=week",
        "zoom=day",
        "zoom=day&at=2026-06-15",
        "zoom=day&from=2026-06-08&to=2026-06-21",
        "trip=2026-06-15/2026-06-17",
        "at=1975-01-01",  # before the bounds: shown at their first day
    ):
        text = _page(site, query)
        for link in _links(text):
            path, _, rest = link.partition("?")
            if path == "/life":
                assert site.respond(path, rest).status == 200, (query, link)
    for wrong in ("at=2026-13", "at=June", "zoom=decade", "trip=2026-06-17/2026-06-15", "zoom=day&from=x"):
        assert site.respond("/life", wrong).status == 400, wrong


def test_the_zoom_tabs_and_earlier_and_later_carry_the_moment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = _page(_site(life_record(tmp_path, monkeypatch)), "at=2026-06-15&zoom=week")
    links = _links(_section(text, "timeline"))
    assert "/life?zoom=life" in links
    assert "/life?zoom=year&at=2026" in links
    assert "/life?zoom=month&at=2026-06" in links
    assert "/life?zoom=day&at=2026-06-15" in links
    assert "/life?zoom=week&at=2026-06-08" in links and "/life?zoom=week&at=2026-06-22" in links
    assert "/week/2026-W25" in links, "the week page (#376) is on main"
    assert all(f"/day/2026-06-{d}" in links for d in range(15, 22))


def test_the_month_is_its_weeks_each_a_link_to_its_week(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = _page(_site(life_record(tmp_path, monkeypatch)), "at=2026-06")
    links = _links(_section(text, "timeline"))
    assert [w for w in ("/week/2026-W23", "/week/2026-W24", "/week/2026-W25", "/week/2026-W26") if w in links]
    assert len([w for w in links if w.startswith("/week/")]) == 5
    assert "/day/2026-06-01" in links and "/day/2026-06-30" in links


def test_a_trip_is_its_days(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    text = _page(_site(life_record(tmp_path, monkeypatch)), "trip=2026-06-15/2026-06-17")
    line = _section(text, "timeline")
    assert TRIP_NAME in line
    assert "/journeys/2026-06-15/2026-06-17" in _links(line)
    assert all(f"/day/2026-06-{d}" in _links(line) for d in (15, 16, 17, 18))


def test_a_chapter_with_no_day_is_not_yet_placed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    text = _page(_site(life_record(tmp_path, monkeypatch)))
    found = _section(text, "unplaced")
    assert "Not yet placed" in found and UNDATED in found and "logbook chapter open" in found


def test_the_volumes_are_the_years_bound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    text = _page(_site(life_record(tmp_path, monkeypatch)))
    found = _section(text, "volumes")
    words = _read(found)[0]
    assert "A year of your life, bound. Signed days in ink, the rest left honest." in words
    assert "2026, being written" in words
    assert "/days?from=2026-01-01&to=2026-12-31" in _links(found)


# -- the rules ----------------------------------------------------------------------------------------------


def test_a_page_at_tier_one_shows_nothing_of_tier_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = life_record(tmp_path, monkeypatch)
    site = _site(lb, tiers=(1,))
    for query in (
        "",
        "zoom=life",
        "at=2026-06",
        "at=2026-06-15&zoom=week",
        "zoom=day",
        "trip=2026-06-15/2026-06-17",
    ):
        words, labels = _read(_page(site, query))
        seen = " ".join([words, *labels])
        for secret in (CHAPTER, EARLIER, RULES, YEAR_GOAL, LIFE_GOAL, TRIP_NAME, REFLECTION, UNDATED):
            assert secret not in seen, (query, secret)
        assert "starred" not in seen.lower(), query
    words = _read(_page(site))[0]
    assert "tier 2" in words, "the page says why the chapter and the goals are not here"


def test_no_number_beside_a_person_s_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    site = _site(life_record(tmp_path, monkeypatch))
    for query in (
        "",
        "zoom=life",
        "at=2026-06",
        "at=2026-06-15&zoom=week",
        "zoom=day",
        "trip=2026-06-15/2026-06-17",
    ):
        words, labels = _read(_page(site, query))
        assert "Kari" in " ".join([words, *labels]), "the guard has a name to look at"
        for name in NAMES:
            n = re.escape(name)
            word = rf"(?<![^\W\d_xX]){n}(?![^\W\d_xX])"  # in another case: a word, or by an `x`
            beside = re.compile(
                rf"(\d[\s(:×x#·,]*{n})|({n}\??[\s(:×x#·,]*\d)|(?i:\d[\s(:×x#·,]*{word}|{word}\??[\s(:×x#·,]*\d)"
            )
            for text in (words, *labels):
                assert not beside.search(text), (query, name, text[:200])


def test_no_script_and_nothing_outside_the_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The doors' policy on every state of the page (frame-ancestors 'none' among it), no script, every
    reference the server's own, one form (the header's Ask, a GET to the search), and a stylesheet that
    fetches nothing but the server's own faces; Life's rules read the shell's tokens and define none."""
    site = _site(life_record(tmp_path, monkeypatch))
    for query in STATES:
        response = site.respond("/life", query)
        text = response.body.decode("utf-8")
        low = text.lower()
        assert (
            response.csp == doors.CSP
            and "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
        )
        assert "<script" not in low and "script-src" not in response.csp
        for found in REFERENCE.findall(text):
            target = html.unescape(found)
            assert target.startswith("/") and not target.startswith("//"), (query, target)
            assert ":" not in target.split("?")[0], (query, target)
        for tag in ("<link", "<iframe", "<frame", "<object", "<embed", "<base", "<meta http-equiv"):
            assert tag not in low, (query, tag)
        forms = re.findall(r"<form\b[^>]*>", low)
        assert forms == [f'<form class="ask" method="get" action="{doors.ASK}" role="search">'], forms
        style = "".join(re.findall(r"<style>(.*?)</style>", text, re.S))
        assert set(re.findall(r"url\(([^)]*)\)", style)) <= {f"/font/{name}" for name in doors.FACES}
        assert "@import" not in style and "http" not in style
        door = style[style.index(".door-life") :]
        assert ":root" not in door, "the door never defines :root: the shell's tokens are its"
        assert "var(--ink, #16181D)" in door


def test_the_page_is_kept_by_its_tag_and_moves_with_today(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = life_record(tmp_path, monkeypatch)
    first = _site(lb).respond("/life")
    assert first.etag is not None
    assert _site(lb).respond("/life", if_none_match=first.etag).status in (200, 304)
    later = serve.Site(lb, now=lambda: datetime(2026, 6, 23, 18, 0, tzinfo=UTC)).respond("/life")
    assert later.etag != first.etag


def test_the_build_writes_the_door(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert "/life" in library_build.DOORS
    lb = life_record(tmp_path, monkeypatch)
    library = library_build.Library(lb, tmp_path / "library", now=lambda: NOW)
    library_build.build(lb, _site(lb), library, only=["/life"])
    found = library.page("/life")
    assert found is not None and found[0].status == 200
    assert CHAPTER.encode("utf-8") in found[1]


def test_a_static_site_writes_the_links_it_has_and_no_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = life_record(tmp_path, monkeypatch)
    site = _site(lb, href=lambda path: None, nav="")
    text = site.respond("/life").body.decode("utf-8")
    assert "<a href" not in text
    assert CHAPTER in text


# -- ideas, a band on the timeline (the owner's answer of 25 October 2026 to RFC 0047 §14, question 6) ------

IDEAS_NOW = datetime(2026, 10, 16, 20, 0, tzinfo=UTC)  # the ideas record's sitting
IDEAS = ("the fjord kiosk", "the tide clock", "the harbour sauna")


def _ideas_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    import ideas_record

    lb = ideas_record.record(tmp_path, monkeypatch, ideas_record.ideas_drafts())
    ideas_record.settle(lb)
    return Logbook(lb.root)


def test_ideas_are_a_band_on_the_life_and_the_year(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each named idea is a span from its spark to its last touch (or to the day it was built or killed),
    its name and stage on hover, a link to its page; never the people it was discussed with."""
    site = serve.Site(_ideas_record(tmp_path, monkeypatch), now=lambda: IDEAS_NOW)
    life = _section(_page(site, "zoom=life"), "timeline")
    assert life.count('class="span idea') == len(IDEAS)
    words, labels = _read(life)
    for name in IDEAS:
        assert name in " ".join([words, *labels]), name
    assert sum(1 for link in _links(life) if link.startswith("/idea/")) >= len(IDEAS)
    assert "exploring" in " ".join(labels) and "killed" not in words  # a stage on hover, not on the line
    year = _section(_page(site, "zoom=year&at=2026"), "timeline")
    assert 'class="span idea' in year and "the fjord kiosk" in year
    assert "Ola" not in _read(year)[0] and "Ola" not in _read(life)[0]


def test_a_page_at_tier_one_draws_no_idea(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    site = serve.Site(_ideas_record(tmp_path, monkeypatch), now=lambda: IDEAS_NOW, tiers=(1,))
    for query in ("zoom=life", "zoom=year&at=2026"):
        text = _page(site, query)
        seen = " ".join([_read(text)[0], *_read(text)[1]])
        assert 'class="span idea' not in text
        for name in IDEAS:
            assert name not in seen, (query, name)


# -- the rules main holds every page to (v1.0): main's own guard, the tier gate, pencil --------------------

HOSTILE = {  # the owner's words, each starting with a name and ending in a number
    "earlier": "Per Hansen and the yard, 2019",
    "chapter": "Ola Nordmann's summer, 2026",
    "rules": "Kari Nordmann first, then the boat in 2026",
    "year": "Kari Nordmann's birthday sail, 2026",
    "life": "Per Hansen's boat, 2030",
    "note": "Ola Nordmann said yes in 2026",
    "trip": "Kari Nordmann in Zürich, 2026",
    "reflection": "Ola Nordmann came aboard; the anchor held until 2",
    "undated": "Ola Nordmann's year at sea, then 2027",
}


def hostile_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """The persona's fortnight with what the owner said about it, every text of the owner's starting with a
    person's name and ending in a number (none with a number beside a name inside it)."""
    lb = persona_record(tmp_path, monkeypatch)
    minutes = iter(range(60))
    with pytest.MonkeyPatch.context() as sitting:
        sitting.setattr(goals, "now", lambda: NOW.replace(minute=next(minutes)))
        chapter.open_chapter(lb, HOSTILE["earlier"], start="2019-08-01", to="2026-05-02")
        chapter.open_chapter(lb, HOSTILE["chapter"], start="2026-05-03", rules=HOSTILE["rules"])
        year_goal = goals.add(lb, HOSTILE["year"], "year", start="2026-01-01")
        goals.add(lb, HOSTILE["life"], "life", start="2026-01-01")
        goals.review(
            lb, str(year_goal["id"]), "advancing", note=HOSTILE["note"], at="2026-06-01T18:00:00+02:00"
        )
    reflection = notes.write(lb, "2026-06-14", HOSTILE["reflection"], notes.REFLECTION, "manual", today=TODAY)
    signing.sign(lb, "2026-06-10", at=utc("2026-06-10", "22:00"))
    signing.sign(lb, "2026-06-14", at=utc("2026-06-14", "22:00"))
    stars.star(lb, str(reflection["id"]))
    journeys.name(lb, "2026-06-15", HOSTILE["trip"], today=TODAY)
    lb.append(
        at="2026-06-20T19:00:00Z",
        source="manual",
        kind="chapter",
        tier=2,
        payload={"schema": "chapter/v1", "name": HOSTILE["undated"], "rules": ""},
    )
    _set_life(Logbook(lb.root), LIFE)
    return Logbook(lb.root)


def _held_apart(site: serve.Site, queries: tuple[str, ...] = STATES) -> list[tuple[str, list[str]]]:
    """Main's guard (`tests/test_no_count_beside_a_name.py`: a number, a date or a clock beside a name with
    only separators between) over every state of the page: its text, then each title and aria-label."""
    import test_no_count_beside_a_name as guard

    found = []
    for query in queries:
        text = _page(site, query)
        _words, labels = _read(text)
        caught = guard.beside(text) + guard.beside(labels)
        if caught:
            found.append((query, caught))
    return found


def test_main_s_guard_holds_on_every_state_of_every_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No number, date or clock time touches a person's name, in the text, a title or an aria-label, on
    every view of the page, through every gate, on the persona's record, a record whose owner's words
    start with a name and end in a number, the demo, the ideas and an empty record."""
    from logbook.contrib import demo

    sites = {
        "persona": _site(life_record(tmp_path / "persona", monkeypatch)),
        "hostile": _site(hostile_record(tmp_path / "hostile", monkeypatch)),
        "demo": serve.Site(
            demo.generate(tmp_path / "demo" / "Demo", days=30, seed=1),
            now=lambda: datetime(2026, 7, 1, 10, 0, tzinfo=UTC),
        ),
        "ideas": serve.Site(_ideas_record(tmp_path / "ideas", monkeypatch), now=lambda: IDEAS_NOW),
    }
    empty = Logbook.init(tmp_path / "empty" / "lb", "Europe/Oslo")
    for name in ("persona", "hostile"):
        sites[f"{name} at tier 1"] = serve.Site(sites[name].lb, now=lambda: NOW, tiers=(1,))
    sites["empty"] = _site(empty)
    shown = []
    for query in ("", "zoom=life", "at=2026-06", "zoom=day&at=2026-06-15"):
        words, labels = _read(_page(sites["hostile"], query))
        shown += [words, *labels]
    for words in HOSTILE.values():
        assert any(words in text or words[:30] in text for text in shown), words  # the guard has them to read
    for name, site in sites.items():
        assert _held_apart(site) == [], name
    # and as the page is seen: with the words said to a screen reader alone taken out, no date stands beside
    # a name either (a day's row and a week's day show the kind of what follows their date)
    import test_no_count_beside_a_name as guard

    for query in STATES:
        seen = re.sub(r'<span class="hidden">[^<]*</span>', "", _page(sites["hostile"], query))
        assert guard.beside(seen) == [], query


def test_at_tier_one_no_person_idea_chapter_or_date_of_tier_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A page read at tier 1 names nobody (Life names people only in the owner's own words, all tier 2), and
    shows no idea, no chapter band, no review's day and no reflection's day a tier-2 line alone gives."""
    import test_no_count_beside_a_name as guard

    site = serve.Site(hostile_record(tmp_path, monkeypatch), now=lambda: NOW, tiers=(1,))
    for query in STATES:
        text = _page(site, query)
        words, labels = _read(text)
        seen = " ".join([words, *labels])
        for name in guard.NAMES:
            assert name not in seen, (query, name)
        assert "/idea/" not in text and 'class="band chapter' not in text and 'class="span idea' not in text
        assert "Reviewed" not in seen and "Next look" not in seen and "reflection you starred" not in seen
        assert 'class="tick reflection' not in text and 'class="dot reflection' not in text, query


DRAFTED = "A summer on the water, the yard before the office."


def _drafted(lb: Logbook, entry: dict[str, Any] | None) -> Logbook:
    """The chapter today is in, drafted by a model (`draft/v1` unit `chapter`, as `dream chapter` writes
    it), under the `dream` entry `entry` (None: no entry)."""
    import dream_fortnight

    dream_fortnight.set_dream_entry(lb.root, entry)
    with lb.index() as idx:
        standing = chapter.standing(chapter.chapter_lines(idx.by_kind(chapter.KIND)))
    current = next(c for c in standing if (c.get("payload") or {}).get("name") == CHAPTER)
    lb.append(
        at="2026-06-20T06:05:00Z",
        source="model:synthetic-model",
        kind="draft",
        tier=2,
        payload={
            "schema": "draft/v1",
            "unit": "chapter",
            "subject": [str(current["id"])],
            "read_head": "c" * 64,
            "read_count": 1,
            "language": "en",
            "segments": [{"text": DRAFTED, "evidence": [str(current["id"])]}],
            "extra": {"prompt": "dream-chapter/1"},
        },
    )
    return Logbook(lb.root)


def test_a_model_s_draft_of_the_chapter_is_pencil_and_never_ink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = _drafted(life_record(tmp_path, monkeypatch), {"max_tier": 2, "until": "2026-12-31"})
    found = _section(_page(_site(lb)), "chapter")
    pencil = re.search(r'<p class="pencil" title="([^"]*)">(.*?)</p>', found, re.S)
    assert pencil is not None and DRAFTED in pencil.group(2)
    assert "synthetic-model" in pencil.group(1) and "not your words" in pencil.group(1)
    for ink in re.findall(r'<[a-z0-9]+ class="[^"]*\bink\b[^"]*">(.*?)</', found, re.S):
        assert DRAFTED not in ink, "pencil never set as ink"
    assert DRAFTED not in _page(_site(lb, with_drafts=False)), "a site built without drafts shows none"
    withheld = _drafted(
        life_record(tmp_path / "withheld", monkeypatch), {"max_tier": 1, "until": "2026-12-31"}
    )
    assert DRAFTED not in _page(_site(withheld)), "a draft above the entry's tier is not shown"


def test_every_target_on_every_view_is_44_px(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A thumb's target on a phone (main's helpers, `tests/test_phone_targets.py`, read through the page's
    own stylesheet): every link and every zoom tab on every view is 44 px tall at least, and every link
    whose width the sheet sets (the marks on a canvas, a day's and a row's links, the month's cells and
    week links) is 44 px wide at least. A label or a bar on a canvas is as wide as its words or its days,
    and its box is 44 px tall."""
    import test_phone_targets as phone

    site = _site(life_record(tmp_path, monkeypatch))
    door = phone._tag("div", "door-life")
    sized = (
        phone._tag("a", "dot"),
        phone._tag("a", "tick"),
        phone._tag("a", "cell"),
        phone._tag("a", "wk"),
        phone._within(phone._tag("a"), phone._tag("ul", "marks")),
        phone._within(phone._tag("a"), phone._tag("span", "marks")),
        phone._within(phone._tag("a"), phone._tag("ul", "this")),
        phone._within(phone._tag("a"), phone._tag("div", "zoom")),
    )
    for query in STATES:
        page = _page(site, query)
        assert phone._tall(page, phone._within(phone._tag("a"), door)) == [], query
        for wanted in sized:
            if list(phone._styled(page, wanted)):
                assert phone._wide(page, wanted) == [], query
