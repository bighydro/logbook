"""Instagram's lines through the Library's doors (RFC 0047): the Day page, Life, People and Ask, over a
record that holds the synthetic export of tests/fixtures/instagram/archive and one person the owner
confirmed (Ola Nordmann, resolved by the display name Instagram shows). No number beside a person's
name, no handle shown as a person, the follows and likes in words, and a page at tier 1 never shows a
tier-2 line. Nobody here exists: Kari Nordmann lives in Oslo and does not."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import beside_a_name
import page_text
import pytest

from logbook.contrib import door_ask, serve
from logbook.contrib.adapters import instagram
from logbook.core import figures
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "tests" / "fixtures" / "instagram" / "archive"
NOW = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
DAY, FOLLOWED = "2026-05-16", "2026-05-06"
OLA = "019cadd3-6bc0-7dcd-9133-043f5aabf2a9"
NAMES = ("Kari Nordmann", "Ola Nordmann", "Ingrid Berg", "Per Hansen", "Kari", "Ola", "Ingrid", "Per")
HANDLES = ("ola.example", "ingrid.example", "per.example", "sailing.example", "spam.example", "noisy.example")
PAGES = (
    f"/day/{DAY}",
    f"/day/{FOLLOWED}",
    "/life",
    f"/life?at={DAY}",
    "/people",
    f"/people?sel={OLA}",
    f"/people/{OLA}",
    "/ask?q=fendere",
    "/ask?q=Ola",
    "/ask?q=sailing",
    "/ask?q=Ingrid",
)


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.delenv(instagram.HASH_MEDIA_ENV, raising=False)
    card = {
        "at": "2026-05-01T09:00:00Z",
        "end": None,
        "tz": "Europe/Oslo",
        "source": "manual",
        "kind": "resolution",
        "tier": 2,
        "payload": {
            "schema": "resolution/v1",
            "ref": {"kind": "provider_id", "value": "instagram:Ola Nordmann"},
            "entity": {"type": "person", "id": OLA, "registry": "logbook"},
            "label": "Ola Nordmann",
            "method": "owner",
        },
    }
    assert lb.append_many([card]) == 1
    assert lb.append_many(instagram.run(EXPORT)) == 27
    return lb


def _get(site: serve.Site, target: str) -> str:
    """The page; a person's page below the tier their name rests on is no page at all (404), and
    says nothing of them."""
    path, _, query = target.partition("?")
    response = site.respond(path, query)
    gated = site.tiers is not None and 2 not in site.tiers and path.startswith("/people/")
    assert response.status == (404 if gated else 200), (target, site.tiers, response.status)
    return response.body.decode("utf-8")


def _main(page: str) -> str:
    return page.split("<main", 1)[1].split("</main>")[0] if "<main" in page else page


def _beside(page: str) -> list[str]:
    return [row for row in beside_a_name.page_rows(page) if any(figures.adjacent(row, n) for n in NAMES)]


@pytest.mark.parametrize("target", PAGES)
def test_no_number_beside_a_name_on_any_door(lb: Logbook, target: str) -> None:
    for tiers in (None, (1,), (1, 2)):
        assert _beside(_get(serve.Site(lb, now=lambda: NOW, tiers=tiers), target)) == [], (target, tiers)


def test_no_handle_is_a_person_on_people(lb: Logbook) -> None:
    site = serve.Site(lb, now=lambda: NOW)
    for target in ("/people", f"/people?sel={OLA}", f"/people/{OLA}"):
        seen = page_text.seen(_main(_get(site, target)))
        assert not [h for h in HANDLES if h in seen], target
        assert "instagram:" not in seen, target
    assert "Ola Nordmann" in page_text.seen(_main(_get(site, "/people")))


def test_ask_never_shows_a_handle_or_a_raw_ref(lb: Logbook) -> None:
    site = serve.Site(lb, now=lambda: NOW)
    for target in ("/ask?q=sailing", "/ask?q=fendere", "/ask?q=Ola", "/ask?q=Ingrid"):
        seen = page_text.seen(_main(_get(site, target)))
        assert not [h for h in HANDLES if h in seen], target
        assert "instagram:" not in seen, target
    shared = page_text.seen(_main(_get(site, "/ask?q=fjorden")))
    assert "Fin tur på fjorden" in shared
    assert (
        door_ask.readable("[Ola] Nordmann · instagram:[Ola] Nordmann · Båten er klar")
        == "[Ola] Nordmann · Båten er klar"
    )


def test_ask_finds_a_group_member_by_what_they_said_not_by_being_there(lb: Logbook) -> None:
    seen = page_text.seen(_main(_get(serve.Site(lb, now=lambda: NOW), "/ask?q=Ingrid")))
    assert "Hvem tar med fendere?" in seen
    assert "Jeg tar med fendere" not in seen  # the owner's message in the group names no Ingrid


def test_the_day_says_the_follows_and_likes_in_words(lb: Logbook) -> None:
    site = serve.Site(lb, now=lambda: NOW)
    day = page_text.seen(_main(_get(site, f"/day/{DAY}")))
    assert "liked a post by @sailing.example" in day
    assert "commented on a post by @ola.example: Så fint! 😍" in day
    assert "liked a story by @ingrid.example" in day
    assert "searched for @per.example" in day
    followed = page_text.seen(_main(_get(site, f"/day/{FOLLOWED}")))
    assert "followed by @ola.example" in followed


def test_a_tier_1_page_shows_no_instagram_line(lb: Logbook) -> None:
    site = serve.Site(lb, now=lambda: NOW, tiers=(1,))
    for target in PAGES:
        seen = page_text.seen(_main(_get(site, target)))
        for words in ("Båten er klar", "Hvem tar med fendere", "Så fint", "@ola.example", "Ola Nordmann"):
            assert words not in seen, (target, words)
