"""The Library's Journeys and People shelves in `logbook serve`: the journeys of a year and one
journey, the people of a year and one person, every derived row with its evidence folded; the acts
"name this journey", Merge and Not the same person write through the CLI's own functions, byte for
byte what `add --trip`, `people review --accept` and `--reject` write, from this machine only. Phone
first: no page is wider than a 400 px column, read from the page and its stylesheet
(`phone_width.py`). On the four synthetic years (`library_record.py`); nobody here exists."""

from __future__ import annotations

import html
import http.client
import json
import re
import shutil
import subprocess
import sys
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import page_text
import phone_width
import pytest
from four_years import ASTRID, BJORN, FRODE, HANS, INGRID, KRISTIN, OBSERVED
from library_record import ASTRID_ELSEWHERE, BERGEN_WINTER, PROMISE, dream, library_record
from persona import transcript, utc

from logbook import cli
from logbook.contrib import door_people, people_review, serve
from logbook.core.store import Logbook

LOOPBACK = "127.0.0.1"
OCTOBER = datetime(2025, 10, 1, 12, 0, tzinfo=UTC)
BERGEN_PAGE = "/journeys/2022-01-03/2022-03-31"
REFERENCE = re.compile(
    r"""(?:href|src|action|formaction|poster|data|srcset|cite)\s*=\s*["']([^"']*)["']""", re.I
)
PAGES = (
    "/journeys",
    "/journeys?year=2022",
    "/journeys?year=2024",
    BERGEN_PAGE,
    "/journeys/2022-11-03/2023-07-31",
    "/people",
    "/people?year=2022",
    *(f"/people/{p['id']}" for p in (ASTRID, BJORN, FRODE, INGRID, KRISTIN)),
)
UNSTAMPED = ("id", "hash", "prev", "recorded_at")  # what two copies of one write cannot share
GITHUB_HANDLE = "github:bjorn-example"  # a handle a service names: an observed person's key (#281)


def _github_commit(at: str) -> dict[str, Any]:
    """A commit of Bjørn's as `sync github` writes it: an event line whose organizer is his handle
    and whose actor carries the name the commit gave (`logbook.contrib.adapters.github.line`)."""
    return {
        "at": at,
        "end": None,
        "source": "github",
        "kind": "event",
        "tier": 1,
        "payload": {
            "schema": "event/v1",
            "raw_id": "github:commit:example-org/example-repo:0123abcd",
            "title": "Fix the harbour map",
            "calendar": {"id": "github", "name": "GitHub"},
            "all_day": False,
            "modified_at": at,
            "organizer": {"kind": "handle", "value": GITHUB_HANDLE},
            "extra": {
                "action": "commit",
                "repo": "example-org/example-repo",
                "actor": {"login": "bjorn-example", "type": "User", "name": BJORN["name"], "role": "other"},
            },
        },
    }


@pytest.fixture(scope="module")
def pristine(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    root = tmp_path_factory.mktemp("library") / "lb"
    library_record(root)
    yield root


@pytest.fixture
def lb(pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    shutil.copytree(pristine, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook(root)


def _site(lb: Logbook) -> serve.Site:
    return serve.Site(lb, now=lambda: OCTOBER)


def _get(site: serve.Site, page: str) -> str:
    path, _, query = page.partition("?")
    response = site.respond(path, query)
    assert response.status == 200, (page, response.body[:300])
    return response.body.decode("utf-8")


def _written(root: Path, seq: int) -> list[dict[str, Any]]:
    return [line for line in Logbook(root).lines() if int(line["seq"]) > seq]


def _same(a: dict[str, Any], b: dict[str, Any], *aside: str) -> bool:
    keep = [k for k in sorted({*a, *b}) if k not in (*UNSTAMPED, *aside)]
    return json.dumps([a.get(k) for k in keep], sort_keys=True) == json.dumps(
        [b.get(k) for k in keep], sort_keys=True
    )


def _cli_on(root: Path, monkeypatch: pytest.MonkeyPatch, *args: str) -> None:
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    cli.main([*args])


def _section(text: str, start: str, end: str | None = None) -> str:
    """From `start` to the next `end` after it (a start that is itself an `<h2>` does not end there)."""
    rest = text[text.index(start) :]
    return rest if end is None else rest[: rest.index(end, len(start))]


# -- the pages render, from the record alone ----------------------------------------------------------


def test_every_page_renders_on_the_four_years_and_points_at_nothing_but_itself(lb: Logbook) -> None:
    site = _site(lb)
    for page in PAGES:
        path, _, query = page.partition("?")
        response = site.respond(path, query)
        assert response.status == 200, page
        text = response.body.decode("utf-8")
        for found in REFERENCE.findall(text):
            target = html.unescape(found)
            assert target.startswith("/") and not target.startswith("//"), (page, target)
            assert ":" not in target.split("?")[0], (page, target)
        assert (
            "<script" not in text.lower() and "script-src" not in response.headers["Content-Security-Policy"]
        )
        assert response.headers["Content-Security-Policy"].startswith("default-src 'none'")
        assert response.etag is not None, f"{page}: the record's, kept by the browser"
        assert '<a href="/people"' in text and ">People</a>" in text, "in the doors' header"
        assert '<a class="gear" href="/shelves"' in text, "the gear: every shelf, the Journeys among them"


def test_serving_the_shelves_writes_nothing(lb: Logbook) -> None:
    site = _site(lb)
    _get(site, "/journeys")
    head = lb.meta["head"]
    files = {str(p.relative_to(lb.root)): p.read_bytes() for p in lb.root.rglob("*") if p.is_file()}
    for page in PAGES:
        _get(site, page)
    after = {str(p.relative_to(lb.root)): p.read_bytes() for p in lb.root.rglob("*") if p.is_file()}
    assert Logbook(lb.root).meta["head"] == head and after == files


def _row(text: str, row_id: str) -> str:
    """One row of a shelf, its evidence and draft included: to the next row or the list's end."""
    rest = text[text.index(f'<li id="{row_id}">') :]
    ends = [i for i in (rest.find('\n<li id="', 1), rest.find("</ol>")) if i > 0]
    return rest[: min(ends)]


def test_the_journeys_of_a_year_most_recent_first_each_row_with_its_evidence(lb: Logbook) -> None:
    text = _get(_site(lb), "/journeys?year=2022")
    rows = re.findall(r'<li id="trip-([^"]+)">', text)
    assert rows == ["2022-11-03-2023-07-31", "2022-01-03-2022-03-31"], "the latest first"
    assert text.count('<details class="evidence">') == len(rows), "every row says where it came from"
    bergen = _row(text, "trip-2022-01-03-2022-03-31")
    assert f'href="{BERGEN_PAGE}"' in bergen and "88 nights away (19 in transit)" in bergen
    assert "home 2022-04-01" in bergen and "2 photos" in bergen and "· Bergen ·" in bergen
    assert f'href="/people/{ASTRID["id"]}">Astrid Bakke</a>' in bergen
    assert OBSERVED["name"] not in bergen and 'href="/people#review">1 not placed</a>' in bergen
    assert '<details class="draft"><summary>draft · model:qwen2.5-7b-instruct' in bergen, "the draft, folded"
    assert '<details class="draft" open' not in text and '<details class="evidence" open' not in text
    evidence = bergen[bergen.index('<details class="evidence">') :]
    dash = serve.EN_DASH
    assert f"69 nights 2022-01-03 {dash} 2022-03-12 Bergen" in evidence and "60.3913" not in bergen
    assert f"19 nights 2022-03-13 {dash} 2022-03-31 in transit" in evidence
    assert 'title="line 019cadd3-6bc0-7dcd-9133-0000000002a1"' in evidence, "the photos' lines"
    assert "<summary>… and 6 more</summary>" in evidence, "three rows shown, the rest behind a toggle"
    last = _get(_site(lb), "/journeys")
    assert "Journeys <small>2025</small>" in last and "no journeys began in 2025" in last, (
        "the record's last year"
    )
    assert _site(lb).respond("/journeys", "year=20x5").status == 400


def test_one_journey_its_days_its_stays_on_a_canvas_and_the_promises_made_on_it(lb: Logbook) -> None:
    text = _get(_site(lb), BERGEN_PAGE)
    days = re.findall(
        r'<p class="head"><a href="/day/(\d{4}-\d{2}-\d{2})">', _section(text, "<h2>Days</h2>", "</ol>")
    )
    assert days[0] == "2022-01-03" and days[-1] == "2022-04-01" and len(days) == 89, "first day to return day"
    canvas = _section(text, '<svg class="stays"', "</svg>")
    assert canvas.count("<circle") == 1 and "km</text>" in canvas, "one place slept at, one dot; a scale"
    assert "<image" not in canvas and "href" not in canvas, "no tile"
    promises = _section(text, "<h2>Promises made on it</h2>", "<h2>People</h2>")
    assert html.escape(PROMISE) in promises and 'href="/day/2022-01-10"' in promises
    assert '<span class="mute">you · due 2022-01-14 · open</span>' in promises, (
        "said on a Monday: that Friday"
    )
    assert f'<form class="name" method="post" action="{serve.NAME_PATH}">' in text
    assert f'name="id" value="{BERGEN_WINTER}"' in text
    assert "unsupported: evidence names a line that is not of the journey" in text
    stays = _section(text, "<h2>Stays</h2>", "<h2>Days</h2>")
    assert stays.count('<details class="evidence">') == 1, (
        "the stay slept at, with its lines; transit has none"
    )
    days_section = _section(text, "<h2>Days</h2>", "<h2>Promises")
    assert days_section.count('<details class="evidence">') == 89, "each day says where it came from"
    missing = _site(lb).respond("/journeys/2025-06-01/2025-06-02", "")
    assert missing.status == 404 and "the night was at home" in missing.body.decode("utf-8")


def test_a_journey_draft_the_dream_entry_no_longer_allows_is_one_row_never_its_text(lb: Logbook) -> None:
    """The Day's rule on both journey pages: a draft above the `dream` entry's max_tier today (#273)
    is one muted row, `superseded by policy` and why, with its line on hover; none of its words."""
    (line,) = [line for line in Logbook(lb.root).lines() if line["kind"] == "draft"]
    dream(lb.root, {"max_tier": 1})
    site = _site(lb)
    for page, text in (
        ("the list", _row(_get(site, "/journeys?year=2022"), "trip-2022-01-03-2022-03-31")),
        ("the journey", _get(site, BERGEN_PAGE)),
    ):
        assert "Two photos of the harbour" not in text and "It rained every day" not in text, page
        assert '<details class="draft"' not in text and "model:qwen2.5-7b-instruct" not in text, page
        row = f'<p class="mute" title="line {line["id"]}">superseded by policy: tier 2, above max_tier 1'
        assert row in text, page
    dream(lb.root, {"max_tier": 2})
    text = _get(_site(lb), BERGEN_PAGE)
    assert "Two photos of the harbour" in text and "superseded by policy" not in text


def test_the_people_of_the_year_canonical_only_then_the_review_queue(lb: Logbook) -> None:
    """The People door (RFC 0047 §4.3): the canonical people by closeness, the closest's thread open
    beside them, each person a link to their thread; under them the shelf as it was, each name a link
    to their page with its evidence folded; then the review queue, as it was."""
    text = _get(_site(lb), "/people")
    listed = _section(text, '<ol class="shelf">', '<h2 id="review">')
    names = re.findall(r'href="/people/[^"]+"><b>([^<]+)</b>', listed)
    assert (
        names[0] == FRODE["name"]
        and OBSERVED["name"] not in listed
        and ASTRID_ELSEWHERE["email"] not in listed
    )
    assert listed.count('<details class="evidence">') == len(names)
    door = _section(text, '<div class="door-people">', '<h2 id="review">')
    drawn = re.findall(r'<a href="/people\?sel=[^"]+"[^>]*aria-label="([^",]+),', door)
    closest = re.findall(r'<h2 class="name" id="thread-name">([^<]+)</h2>', door)
    assert closest == [FRODE["name"]] and FRODE["name"] in drawn
    assert OBSERVED["name"] not in door and ASTRID_ELSEWHERE["email"] not in door
    assert door.count('href="/people?sel=') == len(drawn) == len(set(drawn)), (
        "each once, a link to their thread"
    )
    assert f'href="/people/{FRODE["id"]}"' in door, "the closest's whole thread, a link away"
    review = _section(text, '<h2 id="review">')
    assert "1 proposal · 2 seen, not placed" in review
    assert ASTRID_ELSEWHERE["email"] in review and f'href="/people/{ASTRID["id"]}">Astrid Bakke</a>' in review
    assert "same name Astrid Bakke" in review
    assert OBSERVED["email"] in review, "the observed appear in the review, and only there"
    assert '<button name="act" value="merge">Merge</button>' in review
    assert '<button name="act" value="reject">Not the same person</button>' in review
    past = _get(_site(lb), "/people?year=2022")
    assert re.findall(r'href="/people/[^"]+"><b>([^<]+)</b>', past)[:2] == ["Elin Moe", ASTRID["name"]]
    assert re.findall(r'<h2 class="name" id="thread-name">([^<]+)</h2>', past) == ["Elin Moe"]
    found = door_people.circle(_site(lb), "2022")
    assert found is not None and [n.person.name for n in found.near][:2] == ["Elin Moe", ASTRID["name"]]


def test_a_machine_participant_is_on_no_shelf_no_page_and_in_no_queue(lb: Logbook) -> None:
    """#279: an agent is never a person. A transcript participant marked `machine: true` is not on
    the People shelf, not in the review queue (neither proposed nor among the unplaced), has no
    page, and one named after a person of the record adds nothing to that person's page."""
    bot, named = "Harbour Bot", HANS["name"]
    lb.append_many(
        [
            transcript(
                utc("2025-09-03", "10:00"),
                utc("2025-09-03", "10:30"),
                "A session",
                [{"name": "owner"}, {"name": bot, "machine": True}],
            ),
            transcript(
                utc("2025-09-04", "10:00"),
                utc("2025-09-04", "10:30"),
                "Another",
                [{"name": "owner"}, {"name": named, "machine": True}],
            ),
        ]
    )
    site = _site(lb)
    page = _get(site, "/people")
    assert bot not in page, "nowhere on the People page: not listed, not in the queue"
    listed, review = page.split('<h2 id="review">')
    assert f'href="/people/{HANS["id"]}"' not in listed, (
        "a bot named after a person is not that person's year"
    )
    year = _get(site, "/people?year=2025").split('<h2 id="review">')[0]
    assert f"sel={HANS['id']}" not in year and HANS["name"] not in year, (
        "a bot named after a person is not that person's year"
    )
    assert "1 proposal · 2 seen, not placed" in review and named not in review
    assert site.respond(f"/people/{bot}", "").status == 404, "no page of its own"
    hans = _get(site, f"/people/{HANS['id']}")
    together = _section(hans, "<h2>Days together", "<h2>")  # a row's line id may hold "2025": unseen
    assert page_text.says(together, "2024"), "the section is read: his days together of 2024"
    assert not page_text.says(together, "2025"), "no day together in 2025, by year or by day"
    assert "spoke in Another" not in hans and "transcript" not in hans.split("<h2>")[0]


def test_a_person_s_page(lb: Logbook) -> None:
    """One person's whole thread (RFC 0047 §4.3): the days together counted, by year and as marks over
    the years, one per day; the last real contact and the drift; the promises both ways; an anniversary
    coming; every derived row with its evidence, and every moment a link to its day."""
    site = _site(lb)
    bjorn = _get(site, f"/people/{BJORN['id']}")
    assert "22 days together" in bjorn and "drifting: 22 days together in 2023" in bjorn
    assert (
        "a message from them in a direct chat (whatsapp)" in bjorn
        and "charts</p>" not in bjorn.split("<h2>")[0]
    )
    owed = _section(bjorn, "<h2>Promises</h2>", "<h2>Anniversaries")
    assert "You owe" in owed and "the photos by Friday" in owed and "due 2024-03-15" in owed
    assert "They owe" in owed and "the charts next time" in owed
    assert "You owe them" in owed and "They owe you" in owed
    assert "<b>2023</b> · 22 days" in bjorn
    strip = _section(bjorn, '<ul class="strip">', "</ul>")
    year = _section(strip, '<span class="label">2023</span>', "</li>")
    assert len(re.findall(r'class="mark" href="/day/2023-', year)) == 22, (
        "22 days together in 2023, a mark each"
    )
    kristin = _get(site, f"/people/{KRISTIN['id']}")
    assert '2025-10-14 · 1 year since <a href="/day/2024-10-14">2024-10-14</a>' in kristin
    assert (
        '<span class="date">14 OCT 2025</span><p class="moment"><a href="/day/2024-10-14">A year since'
        in kristin
    )
    ingrid = _get(site, f"/people/{INGRID['id']}")
    assert "Catch-up (Video call)" in ingrid and "not drifting" in ingrid
    for page in (bjorn, kristin, ingrid):
        assert page.count('<details class="evidence">') >= 4, "every derived row has its evidence"
        moments = _section(page, '<ol class="moments">', "</ol>")
        assert moments.count('href="/day/') >= 2, "every moment opens its day"
    assert site.respond(f"/people/{OBSERVED['email']}", "").status == 404, "never an observed person's page"
    assert site.respond("/people/nobody-at-all", "").status == 404


# -- the acts: the CLI's own functions, byte for byte --------------------------------------------------------


def test_naming_a_journey_on_the_page_writes_what_add_trip_writes(
    lb: Logbook, pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = tmp_path / "other"
    shutil.copytree(pristine, other)
    seq = int(lb.meta["seq"])
    _cli_on(other, monkeypatch, "add", "--trip", BERGEN_WINTER, "The Bergen winter")
    site = _site(lb)
    before = site.respond(BERGEN_PAGE, "").etag
    response = site.write(
        serve.NAME_PATH, {"id": BERGEN_WINTER, "name": "  The Bergen   winter "}, LOOPBACK, None
    )
    assert response.status == 303 and response.location == BERGEN_PAGE
    [mine], [theirs] = _written(lb.root, seq), _written(other, seq)
    assert _same(mine, theirs), "the same line, its `at` included: dated inside the journey"
    after = site.respond(BERGEN_PAGE, "", if_none_match=before)
    assert after.status == 200, "the head moved: the page is read again"
    assert "<h1>The Bergen winter <small>" in after.body.decode("utf-8")
    assert "The Bergen winter" in _get(site, "/journeys?year=2022")


def test_merge_and_not_the_same_person_write_what_people_review_writes(
    lb: Logbook, pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proposal = people_review.read(lb).proposals[0]
    seq = int(lb.meta["seq"])
    for act, flag in (("merge", "--accept"), ("reject", "--reject")):
        mine_root, theirs_root = tmp_path / f"{act}-page", tmp_path / f"{act}-cli"
        shutil.copytree(pristine, mine_root)
        shutil.copytree(pristine, theirs_root)
        _cli_on(theirs_root, monkeypatch, "people", "review", flag, "1")
        site = _site(Logbook(mine_root))
        response = site.write(
            serve.PEOPLE_REVIEW_PATH, {"act": act, "id": proposal.id, "year": "2025"}, LOOPBACK, None
        )
        assert response.status == 303 and response.location == "/people?year=2025#review"
        mine, theirs = _written(mine_root, seq), _written(theirs_root, seq)
        assert len(mine) == len(theirs) == 1
        assert all(_same(a, b, "at") for a, b in zip(mine, theirs, strict=True)), "the clock aside"
        kind = "resolution" if act == "merge" else people_review.KIND
        assert mine[0]["kind"] == kind and mine[0]["payload"]["raw_id"].startswith("review:")
        review = _section(_get(site, "/people"), '<h2 id="review">')
        assert f'id="{proposal.id}"' not in review, "out of the queue either way"
        assert (ASTRID_ELSEWHERE["email"] in review) == (act == "reject"), "told apart: still seen, unplaced"
        again = site.write(serve.PEOPLE_REVIEW_PATH, {"act": act, "id": proposal.id}, LOOPBACK, None)
        assert again.status == 409 and "not in the queue" in again.body.decode("utf-8")
    merged = _get(_site(Logbook(tmp_path / "merge-page")), f"/people/{ASTRID['id']}")
    assert ASTRID_ELSEWHERE["email"] in merged, "merged: an address of hers now"


def test_a_github_handle_in_the_queue_renders_and_its_acts_write_what_people_review_writes(
    pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#281: an observed person keyed by a service's handle (`github:<login>`, the organizer of a
    GitHub line) is proposed against the person of that name, shown by the handle with the name
    the commit gave, and Merge and Not the same person write exactly what `people review
    --accept` and `--reject` write for that proposal. The commit is appended once, to one copy both
    roots are then copies of: the alias line cites it by id and the head it was read at."""
    base = tmp_path / "base"
    shutil.copytree(pristine, base)
    lb = Logbook(base)
    lb.append_many([_github_commit(utc("2025-09-10", "09:00"))])
    report = people_review.read(lb)
    [n] = [i for i, p in enumerate(report.proposals, 1) if p.observed.key == ("handle", GITHUB_HANDLE)]
    proposal = report.proposals[n - 1]
    listed, review = _get(_site(lb), "/people").split('<h2 id="review">')
    assert GITHUB_HANDLE not in listed, "the handle is in the queue only, never on the shelf"
    assert f"{GITHUB_HANDLE} ({BJORN['name']}; event 1)" in review
    assert (
        f'href="/people/{BJORN["id"]}">{BJORN["name"]}</a>' in review
        and f"same name {BJORN['name']}" in review
    )
    for act, flag in (("merge", "--accept"), ("reject", "--reject")):
        mine_root, theirs_root = tmp_path / f"{act}-page", tmp_path / f"{act}-cli"
        shutil.copytree(base, mine_root)
        shutil.copytree(base, theirs_root)
        seq = int(lb.meta["seq"])
        _cli_on(theirs_root, monkeypatch, "people", "review", flag, str(n))
        site = _site(Logbook(mine_root))
        response = site.write(
            serve.PEOPLE_REVIEW_PATH, {"act": act, "id": proposal.id, "year": "2025"}, LOOPBACK, None
        )
        assert response.status == 303 and response.location == "/people?year=2025#review"
        mine, theirs = _written(mine_root, seq), _written(theirs_root, seq)
        assert len(mine) == len(theirs) == 1
        assert all(_same(a, b, "at") for a, b in zip(mine, theirs, strict=True)), "the clock aside"
        assert mine[0]["kind"] == ("resolution" if act == "merge" else people_review.KIND)
        if act == "merge":
            assert mine[0]["payload"]["ref"] == {"kind": "handle", "value": GITHUB_HANDLE}
        after = _section(_get(site, "/people"), '<h2 id="review">')
        assert f'id="{proposal.id}"' not in after, "out of the queue either way"
        assert (GITHUB_HANDLE in after) == (act == "reject"), "told apart: still seen, unplaced"
    merged = _get(_site(Logbook(tmp_path / "merge-page")), f"/people/{BJORN['id']}")
    assert GITHUB_HANDLE in merged, "merged: a handle of his now"


def test_a_bad_or_stale_form_writes_nothing(lb: Logbook) -> None:
    site = _site(lb)
    seq = int(lb.meta["seq"])
    for path, form, status in (
        (serve.NAME_PATH, {"id": BERGEN_WINTER, "name": "   "}, 400),
        (serve.NAME_PATH, {"id": "2022-01-03", "name": "Bergen"}, 400),
        (serve.NAME_PATH, {"id": "trip:2022-01-04:2022-03-31", "name": "Bergen"}, 409),
        (serve.NAME_PATH, {"id": "trip:2025-06-01:2025-06-02", "name": "Home"}, 409),
        (serve.PEOPLE_REVIEW_PATH, {"act": "dance", "id": "x"}, 400),
        (serve.PEOPLE_REVIEW_PATH, {"act": "merge"}, 400),
        (serve.PEOPLE_REVIEW_PATH, {"act": "merge", "id": "0000000000000000"}, 409),
        ("/people", {"act": "merge"}, 404),
    ):
        assert site.write(path, form, LOOPBACK, None).status == status, (path, form)
    for path in (serve.NAME_PATH, serve.PEOPLE_REVIEW_PATH):
        assert site.respond(path, "").status == 405
    assert int(Logbook(lb.root).meta["seq"]) == seq


def test_a_post_from_off_this_machine_is_refused(lb: Logbook) -> None:
    site = _site(lb)
    seq = int(lb.meta["seq"])
    proposal = people_review.read(lb).proposals[0]
    forms = (
        (serve.NAME_PATH, {"id": BERGEN_WINTER, "name": "Bergen"}),
        (serve.PEOPLE_REVIEW_PATH, {"act": "merge", "id": proposal.id}),
    )
    for path, form in forms:
        for client in ("192.168.1.20", "10.0.0.5", "203.0.113.9", "::ffff:203.0.113.9", ""):
            response = site.write(path, form, client, None)
            assert response.status == 403 and "this machine" in response.body.decode("utf-8"), (path, client)
        for origin in ("http://example.org", "http://localhost:8765", "null", "https://127.0.0.1"):
            assert site.write(path, form, LOOPBACK, origin).status == 403, (path, origin)
    assert int(Logbook(lb.root).meta["seq"]) == seq
    assert site.write(serve.NAME_PATH, forms[0][1], LOOPBACK, "http://127.0.0.1:8765").status == 303
    assert site.write(serve.PEOPLE_REVIEW_PATH, forms[1][1], "::1", "http://[::1]:8765").status == 303


def test_an_act_while_another_command_writes_is_refused_and_writes_nothing(lb: Logbook) -> None:
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    lock = lb._lock_path()
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        holder = {"pid": other.pid, "command": "sync immich", "since": "2025-10-01T06:00:00Z"}
        lock.write_text(json.dumps(holder), encoding="utf-8")
        seq = int(lb.meta["seq"])
        response = _site(lb).write(serve.NAME_PATH, {"id": BERGEN_WINTER, "name": "Bergen"}, LOOPBACK, None)
        assert response.status == 409 and "sync immich" in response.body.decode("utf-8")
        assert int(Logbook(lb.root).meta["seq"]) == seq
    finally:
        other.kill()
        other.wait()
        lock.unlink(missing_ok=True)


def test_the_name_form_round_trips_over_the_socket(lb: Logbook) -> None:
    server = serve.make_server(lb, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        connection = http.client.HTTPConnection(LOOPBACK, port, timeout=30)
        body = urlencode({"id": BERGEN_WINTER, "name": "The Bergen winter"})
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Origin": "http://example.org"}
        connection.request("POST", serve.NAME_PATH, body=body, headers=headers)
        reply = connection.getresponse()
        assert reply.status == 403 and reply.read()
        headers["Origin"] = f"http://{LOOPBACK}:{port}"
        connection.request("POST", serve.NAME_PATH, body=body, headers=headers)
        reply = connection.getresponse()
        assert reply.status == 303 and reply.read() == b"" and reply.getheader("Location") == BERGEN_PAGE
        connection.request("GET", BERGEN_PAGE)
        reply = connection.getresponse()
        assert reply.status == 200 and "<h1>The Bergen winter" in reply.read().decode("utf-8")
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# -- phone first ---------------------------------------------------------------------------------------------

WIDE_PAGES = ("/journeys?year=2022", BERGEN_PAGE, "/people", f"/people/{BJORN['id']}")


def test_no_shelf_is_wider_than_a_phone(lb: Logbook) -> None:
    """Read as a phone 400 px wide reads them, every disclosure open, from the HTML and the page's
    own stylesheet (`phone_width`, no browser): no element on the Journeys, a journey, the People page
    or a person fixes a width, a min-width or a row of columns that passes the column with the frames
    around it; every image and pre has a max-width that keeps it inside, the journey's canvas of stays
    among them; and the stylesheet has its phone breakpoint."""
    site = _site(lb)
    for page in WIDE_PAGES:
        text = _get(site, page)
        assert phone_width.problems(text) == [], page
        assert phone_width.phone_breakpoints(phone_width.parse(text)[1]), page
    assert phone_width.images(_get(site, BERGEN_PAGE)) == [
        "body > header.doors > a.gear > svg",
        "html > body > main > svg.stays",
    ]
