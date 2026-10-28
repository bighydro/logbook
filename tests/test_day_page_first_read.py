"""The Day page as a stranger first reads it (the dry run of 26 October): the `with` row's words and its
field do not run together, the footer says which forms write to the record instead of `read-only`, and a
past day is headed by its weekday alone, the shape (`morning`, `live`, `evening`) being today's.
Synthetic Oslo persona, who does not exist."""

from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from persona import TZ, persona_record

from logbook.contrib import serve
from logbook.core.store import Logbook

DAY = "2026-06-10"  # a Wednesday of the persona's fortnight
WRITES = "Reflect and Sign, the with field and the stars write to your record; nothing else here does"


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    return persona_record(tmp_path, monkeypatch)


def _page(lb: Logbook, day: str, now: str) -> str:
    at = datetime.fromisoformat(now).replace(tzinfo=ZoneInfo(TZ))
    response = serve.Site(lb, now=lambda: at).respond(f"/day/{day}", "")
    assert response.status == 200
    return response.body.decode("utf-8")


def _text(fragment: str) -> str:
    """What a reader without styles reads: the tags gone, a field and a button by their words."""
    return html.unescape(re.sub(r"<[^>]+>", "", fragment))


def test_the_with_row_and_its_field_do_not_run_together(lb: Logbook) -> None:
    page = _page(lb, "2026-06-12", "2026-07-20T10:00")
    row = re.search(r'<dt id="with">with</dt><dd>(.*?)</dd>', page, re.S)
    assert row is not None
    said = _text(row.group(1).split("<datalist")[0])
    assert re.search(r"[a-z]add\b", said) is None, said
    assert said.endswith(" · add"), said


def test_the_footer_says_which_forms_write(lb: Logbook) -> None:
    page = _page(lb, DAY, "2026-07-20T10:00")
    footer = re.search(r"<footer>(.*?)</footer>", page, re.S)
    assert footer is not None
    assert WRITES in footer.group(1) and "read-only" not in footer.group(1)
    assert "nothing here leaves this machine" in footer.group(1)
    for form in re.findall(r'<form class="([a-z]+)" method="post"', page):
        assert form in ("reflect", "star", "keep", "with"), f"a form the footer does not name: {form}"


def test_a_past_day_is_headed_by_its_weekday_alone(lb: Logbook) -> None:
    brow = re.search(r'<p class="eyebrow">(.*?)</p>', _page(lb, DAY, "2026-07-20T10:00"))
    assert brow is not None and brow.group(1) == "Wednesday", "read weeks later: no `evening`"
    today = re.search(r'<p class="eyebrow">(.*?)</p>', _page(lb, DAY, f"{DAY}T21:00"))
    assert today is not None and today.group(1).startswith("Wednesday · "), "today keeps its shape"
