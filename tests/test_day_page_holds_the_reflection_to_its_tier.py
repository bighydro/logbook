"""The Day page holds the reflection and the kept notes to its tier, as every other line of it (the
owner's desk's review of #405): through a gate below a line's tier, a page and a built page never show,
quote, offer or count the reflection (a note, tier 2) or its Wispr Flow draft (a transcript, tier 3),
and never show "kept as #N" for a sentence kept as a note above the gate: the reference to a line above
the page's tiers is itself a leak. Keeping that sentence again through such a page is refused in one
sentence that names no line. The whole record's page shows all of it, as before.

Synthetic throughout: Ines Nordmann of Oslo, who does not exist, and her boat-share log
(`test_keep_and_sign.py`'s record); Ola Nordmann, to whom the reflection delegates."""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

import test_day_page_keep_and_sign as page_keep
import test_day_page_reflect_sign as page_reflect
import test_keep_and_sign as keeping
from persona import utc
from test_day_page_keep_and_sign import (
    DAY,
    REFLECTION,
    _form,
    _hidden,
    _labels,
    _page,
    _post,
    _said,
    _seq,
    _signing,
    _site,
    _text,
)

from logbook.contrib import library_build
from logbook.core import drafts
from logbook.core.store import Logbook

lb = keeping.lb
closing = page_keep.closing

KEPT_WORDS = "The light holds late in October."
SAID = ("A good day for the crew list", "Ola should book the ferry for Sunday")
DICTATED = "Reflect: The crane is booked for Thursday, and Per Hansen will bring the trailer."


def _reflection(lb: Logbook) -> dict[str, Any]:
    return next(x for x in lb.lines() if "reflection" in _labels(x))


def _words(markup: str) -> str:
    """The page's words, its style (colours like #9b9b9b) left out."""
    return _text(re.sub(r"<style.*?</style>", "", markup, flags=re.S))


def _nothing_of_the_reflection(markup: str, note: dict[str, Any]) -> None:
    text = _words(markup)
    for said in (REFLECTION, *SAID):
        assert said not in text and html.escape(said, quote=False) not in markup, said
    assert str(note["id"]) not in markup, "no reference to the line"
    assert not re.search(rf"#{note['seq']}\b", text), "no number of the line"
    assert "reflection #" not in text, "never counted or numbered"
    assert 'name="accept"' not in markup, "none of its proposals offered"


def test_a_tier_1_page_neither_shows_quotes_offers_nor_counts_a_tier_2_reflection(closing: Logbook) -> None:
    note = _reflection(closing)
    assert note["tier"] == 2, "a reflection is a note: tier 2"
    whole = _page(_site(closing))
    assert html.escape(SAID[1], quote=False) in whole and 'name="accept"' in whole, "the whole record's"
    page = _page(_site(closing, tiers=(1,)))
    _nothing_of_the_reflection(page, note)
    assert '<form class="reflect"' not in page, "no field that would hold or replace it"


def test_a_tier_1_page_still_signs_and_writes_nothing_of_the_reflection_it_cannot_show(
    closing: Logbook,
) -> None:
    """Sign through a gate of tier 1 signs the day as before (#405), its form carrying no reference
    to the reflection; the signature confirms the day's lines, the reflection among them, and the
    refusal of a form older than the record names no line either."""
    note = _reflection(closing)
    site = _site(closing, tiers=(1,))
    hidden = _signing(site)
    assert str(note["id"]) not in hidden.values()
    stale = _post(site, {**hidden, "reflection": "older", "act": "sign"})
    assert stale.status == 409 and str(note["id"]) not in stale.body.decode("utf-8")
    assert _post(site, {**hidden, "act": "sign"}).status == 303
    signature = [x for x in Logbook(closing.root).lines() if x["kind"] == "signed-day"][-1]
    assert str(note["id"]) in signature["payload"]["confirmed"]


def test_a_tier_3_dictation_is_not_offered_below_tier_3(closing: Logbook) -> None:
    """The Wispr Flow draft of a reflection is a transcript, tier 3: offered prefilled on the whole
    record's page, never through a gate of 1 or 1, 2; a form that names it anyway writes nothing."""
    dictation = page_reflect._dictation(closing, utc(page_keep.DAY, "19:40"), DICTATED)
    whole = _form(_page(_site(closing)), "reflect")
    assert "Per Hansen" in whole and _hidden(whole)["dictation"] == dictation["id"]
    for tiers in ((1,), (1, 2)):
        site = _site(closing, tiers=tiers)
        page = _page(site)
        assert "Per Hansen" not in page and "crane is booked" not in page, tiers
        assert dictation["id"] not in page and not re.search(rf"#{dictation['seq']}\b", _words(page)), tiers
        seq = _seq(closing)
        named = _post(site, {"text": "Per Hansen", "dictation": dictation["id"], "act": "reflect"}, "reflect")
        assert named.status in (400, 409) and _seq(closing) == seq, (tiers, named.status)


def _kept_from_a_tier_1_draft(lb: Logbook, monkeypatch: Any) -> dict[str, Any]:
    """A tier-1 draft of DAY standing over the fixture's tier-2 one, and its one sentence kept by the
    command, whole record: a note, tier 2, its `extra.from` the tier-1 draft."""
    upper = next(x for x in lb.lines() if x["kind"] == drafts.KIND)
    photo = next(x for x in lb.lines() if x["kind"] == "photo")
    lower = lb.append(
        utc(DAY, "20:00"),
        keeping.MODEL,
        drafts.KIND,
        1,
        {
            **upper["payload"],
            "supersedes": upper["id"],
            "segments": [
                {"text": "You were out on the water.", "evidence": [photo["id"]]},
                {"text": KEPT_WORDS, "evidence": [photo["id"]]},
            ],
            "proposals": [],
            "extra": {"parts": ["story", "learned"]},
        },
    )
    page_keep._cli(monkeypatch, lb.root, "day", "sign", DAY, "--keep", "1")
    kept = next(
        x for x in Logbook(lb.root).lines() if x["kind"] == "note" and x["payload"]["text"] == KEPT_WORDS
    )
    assert kept["tier"] == 2 and kept["payload"]["extra"]["from"] == lower["id"]
    return kept


def test_a_tier_1_page_shows_no_kept_as_for_a_note_kept_at_tier_2(closing: Logbook, monkeypatch: Any) -> None:
    kept = _kept_from_a_tier_1_draft(closing, monkeypatch)
    whole = _page(_site(closing))
    assert f"kept as #{kept['seq']}" in _text(whole), "the whole record's page says where it went"
    site = _site(closing, tiers=(1,))
    page = _page(site)
    assert KEPT_WORDS in page, "the tier-1 draft's sentence is the page's"
    assert "kept as #" not in _text(page), "no reference to a line above the page's tiers"
    assert str(kept["id"]) not in page and not re.search(rf"#{kept['seq']}\b", _words(page))
    seq = _seq(closing)
    again = _post(site, {**_signing(site), "keep": "1", "act": "sign"})
    assert again.status == 400, again.body[:400]
    said = _said(again)
    assert "kept already" in said and "#" not in said and str(kept["id"]) not in again.body.decode("utf-8")
    assert _seq(closing) == seq, "nothing written"


def test_a_tier_1_built_page_holds_the_reflection_and_the_kept_notes_to_its_tier(
    closing: Logbook, monkeypatch: Any, tmp_path: Path
) -> None:
    """The Library's built Day through a gate of tier 1 (`library_build`, the page as `respond` gives
    it, kept on disk) holds them as the page does."""
    note = _reflection(closing)
    kept = _kept_from_a_tier_1_draft(closing, monkeypatch)
    lb = Logbook(closing.root)
    library = library_build.Library(lb, tmp_path / "library")
    built = library_build.build(lb, _site(lb, tiers=(1,)), library, only=[f"/day/{DAY}"])
    assert not built.failed, built.failed
    texts = {
        str(p.relative_to(tmp_path)): p.read_text(encoding="utf-8")
        for p in sorted((tmp_path / "library").rglob("*"))
        if p.is_file() and p.suffix in {".html", ".json"}
    }
    assert any(KEPT_WORDS in text for text in texts.values()), "the built Day is there, with its pencil"
    for name, text in texts.items():
        _nothing_of_the_reflection(text, note)
        assert "kept as #" not in _text(text), name
        assert str(kept["id"]) not in text, name


def test_a_page_that_reads_no_notes_takes_no_reflection_and_confirms_no_guess(closing: Logbook) -> None:
    """The blind review of this change: Reflect through a gate without tier 2 compared the words typed
    with the hidden reflection, so a guess was confirmed (nothing written) or not (a new one written),
    and a viewer who could not see the reflection replaced it. Such a page offers no Reflect form, and
    a post is refused alike for the right words and the wrong ones, nothing written."""
    site = _site(closing, tiers=(1,))
    page = _page(site)
    assert '<form class="reflect"' not in page and "<textarea" not in page
    seq = _seq(closing)
    right = _post(site, {"text": REFLECTION, "act": "reflect"}, "reflect")
    wrong = _post(site, {"text": "A calm day.", "act": "reflect"}, "reflect")
    assert right.status == wrong.status == 400 and right.body == wrong.body, (right.status, wrong.status)
    assert _seq(closing) == seq, "nothing written"
    assert REFLECTION not in _said(right) and "logbook day reflect" in _said(right)
    assert _post(_site(closing), {"text": "A calm day.", "act": "reflect"}, "reflect").status == 303


def test_a_page_that_reads_no_notes_looks_the_same_with_a_reflection_or_without(
    lb: Logbook, monkeypatch: Any
) -> None:
    """Whether the day has a reflection is itself a line above the gate: through a gate without tier 2
    the section reads the same before the reflection is written and after, its values aside."""

    def section(root: Path) -> str:
        page = _page(_site(Logbook(root), tiers=(1,)))
        found = re.search(r'<section class="close">.*?</section>', page, re.S)
        assert found is not None
        return re.sub(r'value="[0-9a-f]{16}"', 'value="…"', found.group(0))

    before = section(lb.root)
    page_keep._cli(monkeypatch, lb.root, "day", "reflect", DAY, "--text", REFLECTION)
    after = section(lb.root)
    assert before == after
    said = _words(after).casefold()
    assert "reflect first" not in said and "your reflection" not in said, said
