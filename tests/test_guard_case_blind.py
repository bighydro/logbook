"""The strong guard, no number beside a person's name (VISION: no metrics near people), reads a name in
any case: `kari 2026`, `KARI 2026` and `2026 kari` are a number beside Kari Nordmann as `Kari 2026` is,
in the shared function (`figures.adjacent`, `figures.beside_a_name`), in every copy of it (the week's,
the people door's) and on the page that echoes what the owner asked (the Ask field's `/search`): the
words stay in the field, and no heading, title or sentence sets the number beside the name. On the
synthetic Oslo persona, who does not exist."""

from __future__ import annotations

import json
import re
from pathlib import Path

import page_text
import pytest

from logbook.contrib import demo, door_people, dream, serve, week_page
from logbook.core import figures, people
from logbook.core.store import Logbook

CASINGS = ("Kari 2026", "kari 2026", "KARI 2026", "2026 kari", "2026 KARI", "kAri: 14:00")
NAMES = ("Kari Nordmann",)


@pytest.mark.parametrize("text", CASINGS)
def test_the_guard_reads_a_name_in_any_case(text: str) -> None:
    assert figures.adjacent(text, "Kari"), text
    assert figures.beside_a_name(text, NAMES), text
    assert week_page.beside(text, ["Kari"]), text
    assert door_people.beside_guard(["Kari"]).search(text) is not None, text


def test_a_name_in_another_case_is_a_name_only_as_a_word() -> None:
    """As written, no boundary is asked (`3Ola`, `Ola Nordmann2`, `3xOla`); in another case the name
    stands as a word, so a word that holds it is no person (`granola 1 line`, `1 person`)."""
    for said in ("3Ola", "Ola Nordmann2", "3xOla", "3 ola", "ola nordmann, 2"):
        assert figures.adjacent(said, "Ola") or figures.adjacent(said, "Ola Nordmann"), said
    for said in ("3xkari", "karix2", "3XKARI", "kari x 2"):  # the `x` of a count is a separator in any case
        assert figures.adjacent(said, "Kari"), said
    assert not figures.adjacent("granola 1 line, last 14:00", "Ola")
    assert not figures.adjacent("read at tier 1 person", "Per")
    assert not week_page.beside("granola 1 line", ["Ola"])


def test_a_name_in_any_case_and_a_figure_anywhere_is_beside_it() -> None:
    """The second half of the guard: a name, then a figure anywhere in the sentence (`3 dinners with
    kari`), in any case, as `3 dinners with Kari` is."""
    for said in ("3 dinners with Kari.", "3 dinners with kari.", "3 dinners with KARI NORDMANN."):
        assert figures.beside_a_name(said, NAMES), said
    assert not figures.beside_a_name("Dinner with kari at 14:00.", NAMES), "a clock is no figure"
    assert not figures.beside_a_name("Karin had 3 dinners.", NAMES), "a letter stuck to the name: not her"


def test_a_dream_sentence_with_a_lower_case_name_is_held() -> None:
    made = dream.Material(
        day="2026-06-08",
        tier=1,
        read_count=0,
        read_head="",
        read_ids_sha256="",
        language="en",
        data={},
        canonical={"p:kari": "Kari Nordmann"},
    )
    assert dream.beside_a_name("kari nordmann · 2026-06-08", made)
    assert dream.beside_a_name("met kari 3 times", made)


@pytest.fixture(scope="module")
def record(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    with pytest.MonkeyPatch.context() as mp:
        root = tmp_path_factory.mktemp("guard-case-blind") / "Demo"
        mp.setenv("LOGBOOK_HOME", str(root))
        return demo.generate(Path(root), days=10)


def _names(lb: Logbook) -> list[str]:
    known = [p.name for p in people.directory(lb).known.values() if p.name]
    return sorted({part for name in known for part in (name, name.split()[0])})


def test_ask_holds_the_owners_own_name_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The owner is a person too (`tests/beside_a_name.py` guards their name): with their name in
    `policy/owner.json`, `ines 2026` is not said back in a sentence either, and stays in the field."""
    root = tmp_path / "Demo"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    lb = demo.generate(root, days=3)
    owner = lb.root / "policy" / "owner.json"
    owner.write_bytes(json.dumps({"names": ["Ines Nordmann"]}).encode("utf-8"))
    page = serve.Site(lb).respond("/search", "q=ines+2026").body.decode("utf-8")
    assert 'value="ines 2026"' in page
    main = page[page.index("<main>") : page.index("</main>")]
    body = page_text.seen(re.sub(r'<form class="search".*?</form>', "", main, flags=re.S))
    assert not figures.adjacent(body, "Ines"), body


@pytest.mark.parametrize("asked", CASINGS[:4])
def test_ask_never_sets_the_number_beside_the_name_it_echoes(record: Logbook, asked: str) -> None:
    """`/search?q=kari 2026` (the header's Ask): the words stay in the field as typed; the title, the
    heading and every sentence of the page keep the number and the name apart, in any case."""
    names = _names(record)
    assert "Kari" in names
    r = serve.Site(record).respond("/search", "q=" + asked.replace(" ", "+").replace(":", "%3A"))
    assert r.status == 200
    page = r.body.decode("utf-8")
    field = re.search(r'<form class="search"[^>]*><input [^>]*value="([^"]*)"', page)
    assert field is not None and field.group(1) == asked, "the field keeps what the owner typed"
    title = re.search(r"<title>(.*?)</title>", page, re.S)
    heading = re.search(r"<h1>(.*?)</h1>", page, re.S)
    assert title is not None and heading is not None
    main = page[page.index("<main>") : page.index("</main>")]
    body = page_text.seen(re.sub(r'<form class="search".*?</form>', "", main, flags=re.S))  # the field aside
    for where, text in (("title", title.group(1)), ("heading", heading.group(1)), ("body", body)):
        for name in names:
            assert not figures.adjacent(text, name), (where, name, text)


@pytest.mark.parametrize("asked", CASINGS[:4])
def test_ask_door_keeps_the_number_and_the_name_apart(record: Logbook, asked: str) -> None:
    """`/ask?q=kari 2026`: the header's field keeps the words as typed; the title, the heading and the
    body never set the number beside the name, in any case."""
    names = _names(record)
    r = serve.Site(record).respond("/ask", "q=" + asked.replace(" ", "+"))
    assert r.status == 200
    page = r.body.decode("utf-8")
    field = re.search(r'<form class="ask"[^>]*>.*?<input [^>]*value="([^"]*)"', page, re.S)
    assert field is not None and field.group(1) == asked, "the field keeps what the owner typed"
    title = re.search(r"<title>(.*?)</title>", page, re.S)
    heading = re.search(r"<h1>(.*?)</h1>", page, re.S)
    assert title is not None and heading is not None
    main = page[re.search(r"<main\b[^>]*>", page).end() : page.index("</main>")]  # type: ignore[union-attr]
    body = page_text.seen(re.sub(r"<form\b.*?</form>", "", main, flags=re.S))  # the fields aside
    for where, text in (("title", title.group(1)), ("heading", heading.group(1)), ("body", body)):
        for name in names:
            assert not figures.adjacent(text, name), (where, name, text)


def test_ask_door_holds_the_owners_own_name_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "Demo"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    lb = demo.generate(root, days=3)
    owner = lb.root / "policy" / "owner.json"
    owner.write_bytes(json.dumps({"names": ["Ines Nordmann"]}).encode("utf-8"))
    page = serve.Site(lb).respond("/ask", "q=ines+2026").body.decode("utf-8")
    title = re.search(r"<title>(.*?)</title>", page, re.S)
    heading = re.search(r"<h1>(.*?)</h1>", page, re.S)
    assert title is not None and heading is not None
    for text in (title.group(1), heading.group(1)):
        assert not figures.adjacent(text, "Ines"), text
