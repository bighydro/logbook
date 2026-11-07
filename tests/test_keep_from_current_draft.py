"""Keep and sign takes a sentence only from the day's current draft (RFC 0043 §5, rule 2 of `draft/v1`):
the latest draft not retracted and not named in a later draft's `supersedes`, the whole record read.
A draft dreamed again (the morning's after the evening's, or `dream day` again) supersedes the one
before it, and when the newer one is withheld (the `dream` entry no longer allows its tier, or the Day
page's gate does not read it) the older one is still the draft a reader shows; keeping from it would
let the owner confirm words the model itself has replaced. So keeping from a superseded or a retracted
draft is refused, on the command line and on the Day page, in one sentence that names the current
draft (its number, its id and when it was written) and how to keep from it, and nothing is written. A
keep made before the draft was superseded stays as it was written; `show` says which draft it came from.

Synthetic throughout: Ines Nordmann of Oslo, who does not exist, and her boat-share log
(`test_keep_and_sign.py`'s record and `test_day_page_keep_and_sign.py`'s page)."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import test_day_page_keep_and_sign as page
import test_keep_and_sign as keeping
from persona import utc
from test_keep_and_sign import DAY, KEEP_DECIDED, KEEP_LEARNED, LEARNED, MODEL

from logbook.core import drafts
from logbook.core.store import Logbook

lb = keeping.lb
closing = page.closing

NEWER = "A crew list makes the boat-share log easy."  # the learned sentence of the newer draft


def _draft(lb: Logbook) -> dict[str, Any]:
    """The fixture's one draft of DAY, written at 21:00 at tier 2."""
    return next(line for line in Logbook(lb.root).lines() if line["kind"] == drafts.KIND)


def _again(
    lb: Logbook, tier: int, earlier: dict[str, Any], learned: str = NEWER, at: str = "22:00"
) -> dict[str, Any]:
    """DAY dreamed again: the earlier draft's payload, its learned sentence in other words, `supersedes`
    naming it, at `tier`."""
    payload = dict(earlier["payload"])
    payload["segments"] = [
        {**s, "text": learned} if s.get("text") == LEARNED else dict(s)
        for s in earlier["payload"]["segments"]
    ]
    payload["supersedes"] = str(earlier["id"])
    return Logbook(lb.root).append(utc(DAY, at), MODEL, drafts.KIND, tier, payload)


def _seq(lb: Logbook) -> int:
    return int(Logbook(lb.root).meta["seq"])


def _record(lb: Logbook) -> list[dict[str, Any]]:
    return list(Logbook(lb.root).lines())


def _names_the_current(said: str, current: dict[str, Any]) -> None:
    """The refusal's one sentence names the current draft by its number and its id, and when it was
    written (`recorded_at`, in the record's zone), and says how to keep from it."""
    assert f"#{current['seq']}" in said, said
    assert drafts.short_id(str(current["id"])) in said, said
    written = re.search(r"written (\d{4}-\d{2}-\d{2} \d{2}:\d{2})", said)
    assert written is not None, said
    stamp = datetime.fromisoformat(str(current["recorded_at"]).replace("Z", "+00:00"))
    assert written.group(1) == stamp.astimezone(ZoneInfo("Europe/Oslo")).strftime("%Y-%m-%d %H:%M"), said
    assert f"logbook day sign {DAY} --keep" in said, said
    assert said.count(". ") == 0 and "\n" not in said.strip(), f"one sentence: {said!r}"


# -- the command line --------------------------------------------------------------------------------------


def test_keep_from_the_current_draft_works_as_on_main(lb: Logbook) -> None:
    """Dreamed again at a tier the entry allows: the newer draft is current and shown, and keeping its
    number keeps the newer draft's sentence, `extra.from` the newer draft."""
    newer = _again(lb, 2, _draft(lb))
    seq = _seq(lb)
    code, _out, err = keeping._cli("day", "sign", DAY, "--keep", str(KEEP_LEARNED))
    assert code == 0, err
    kept = [x for x in _record(lb) if int(x["seq"]) > seq and x["kind"] == "note"]
    assert [x["payload"]["text"] for x in kept] == [NEWER]
    assert kept[0]["payload"]["extra"]["from"] == newer["id"]


def test_keep_from_a_draft_superseded_by_one_the_entry_withholds_is_refused(lb: Logbook) -> None:
    """The newer draft is tier 3, above the `dream` entry's max_tier 2: the Day still shows the tier-2
    draft it superseded, numbered, and `--keep` of that number is refused in one sentence naming the
    tier-3 draft; nothing is written, not even the signature."""
    older = _draft(lb)
    newer = _again(lb, 3, older)
    code, out, err = keeping._cli("day", DAY, "--no-anniversaries")
    assert code == 0 and f"keep {KEEP_LEARNED}" in out, "the reader shows the older draft"
    seq = _seq(lb)
    for flags in (
        ["--keep", str(KEEP_LEARNED)],
        ["--keep", str(KEEP_DECIDED), "--revisit", f"{KEEP_DECIDED}=2026-11-20"],
    ):
        code, out, err = keeping._cli("day", "sign", DAY, *flags)
        assert code != 0, (flags, out)
        said = err.strip().splitlines()[-1]
        assert f"#{older['seq']}" in said and "superseded" in said, said
        _names_the_current(said, newer)
        assert "dream" in said and "entry" in said, "says why the current draft is not shown"
        assert NEWER not in err, "the withheld draft's words are not quoted"
    assert _seq(lb) == seq, "nothing written"


def test_keep_when_the_only_draft_shown_is_retracted_is_refused_naming_the_current(lb: Logbook) -> None:
    """The tier-2 draft retracted, the tier-3 draft that superseded it withheld by the entry: nothing to
    keep from, and the refusal names the current draft and how to keep from it."""
    older = _draft(lb)
    newer = _again(lb, 3, older)
    Logbook(lb.root).retract(int(older["seq"]), "the model's, not mine")
    seq = _seq(lb)
    code, out, err = keeping._cli("day", "sign", DAY, "--keep", str(KEEP_LEARNED))
    assert code != 0, out
    said = err.strip().splitlines()[-1]
    _names_the_current(said, newer)
    assert _seq(lb) == seq, "nothing written"


def test_a_keep_made_before_the_draft_was_superseded_stays_and_show_names_its_draft(lb: Logbook) -> None:
    """Kept from the current draft, then the day dreamed again: the kept line stays byte for byte (the
    record is append-only; nothing is rewritten), `show` says which draft it was kept from and that
    the draft is superseded, and the newer draft's same sentence reads as kept (RFC 0043 §6 rule 5)."""
    older = _draft(lb)
    code, _out, err = keeping._cli("day", "sign", DAY, "--keep", str(KEEP_LEARNED))
    assert code == 0, err
    kept = next(x for x in _record(lb) if x["kind"] == "note" and "learned" in x["payload"].get("labels", []))
    assert kept["payload"]["extra"]["from"] == older["id"]
    before = list(_record(lb))
    newer = _again(lb, 2, older, learned=LEARNED)
    after = _record(lb)
    assert after[: len(before)] == before, "nothing earlier is rewritten"
    assert [x["id"] for x in after[len(before) :]] == [newer["id"]]
    code, out, err = keeping._cli("show", DAY)
    assert code == 0, err
    row = next(r for r in out.splitlines() if LEARNED in r and " note " in r)
    assert f"kept from draft #{older['seq']}" in row, row
    assert f"superseded by #{newer['seq']}" in row, row
    code, out, err = keeping._cli("day", DAY, "--json", "--no-anniversaries")
    draft = json.loads(out)["draft"]
    assert draft["line"] == newer["id"]
    learned = next(s for s in draft["segments"] if s.get("text") == LEARNED)
    assert learned["kept"] == {"line": kept["id"], "seq": kept["seq"]}


def test_show_names_the_draft_of_a_keep_whose_draft_still_stands(lb: Logbook) -> None:
    older = _draft(lb)
    code, _out, err = keeping._cli("day", "sign", DAY, "--keep", str(KEEP_LEARNED))
    assert code == 0, err
    code, out, err = keeping._cli("show", DAY)
    row = next(r for r in out.splitlines() if LEARNED in r and " note " in r)
    assert row.endswith(f"kept from draft #{older['seq']}"), row


# -- the Day page ------------------------------------------------------------------------------------------


def test_the_page_offers_no_keep_from_a_superseded_draft_and_links_the_newer(closing: Logbook) -> None:
    """The whole record's page shows the tier-2 draft the withheld tier-3 one superseded: its keep
    boxes are gone, the form says a newer draft exists with a link to it as written, and a POST that
    keeps its number anyway is refused in the sentence; nothing is written."""
    older = _draft(closing)
    newer = _again(closing, 3, older)
    site = page._site(closing)
    sign = page._form(page._page(site), "sign")
    assert 'name="keep"' not in sign and 'name="revisit-' not in sign, "no keep boxes"
    assert page._hidden(sign)["draft"] == older["id"]
    text = page._text(sign)
    assert "newer draft" in text, text
    links = re.findall(r'<p class="mute newer">.*?</p>', sign, re.S)
    assert len(links) == 1, sign
    hrefs = re.findall(r'href="([^"]+)"', links[0])
    assert hrefs, "a link to the newer draft"
    for href in hrefs:  # the link goes somewhere: the entry withholds the draft, so never its line's page
        parts = urlsplit(href)
        assert site.respond(parts.path, parts.query).status == 200, href
    assert NEWER not in sign, "the withheld draft's words are not quoted"
    seq = _seq(closing)
    response = page._post(site, {**page._signing(site), "keep": str(KEEP_LEARNED), "act": "sign"})
    assert response.status == 400, response.body[:400]
    said = page._said(response)
    assert f"#{older['seq']}" in said and "superseded" in said, said
    _names_the_current(said, newer)
    assert _seq(closing) == seq, "nothing written"
    assert page._post(site, {**page._signing(site), "word": "calm", "act": "sign"}).status == 303, (
        "signing without keeping from the pencil still signs"
    )


def test_a_page_read_before_the_day_was_dreamed_again_is_refused_naming_the_newer(closing: Logbook) -> None:
    """The page was read with the tier-2 draft; the day was dreamed again since, at tier 2: a POST
    that keeps from the draft the page showed is refused in the sentence naming the newer draft."""
    older = _draft(closing)
    site = page._site(closing)
    fields = page._signing(site)
    assert fields["draft"] == older["id"]
    newer = _again(closing, 2, older)
    seq = _seq(closing)
    response = page._post(site, {**fields, "keep": str(KEEP_LEARNED), "act": "sign"})
    assert response.status == 409, response.body[:400]
    said = page._said(response)
    assert f"#{older['seq']}" in said and "superseded" in said, said
    _names_the_current(said, newer)
    assert _seq(closing) == seq, "nothing written"


def test_a_page_whose_draft_was_retracted_since_is_refused_naming_the_current(closing: Logbook) -> None:
    """The page was read with the newer draft; it was retracted since, so the earlier one is current
    again (rule 2): a POST that keeps from the retracted draft is refused in the sentence naming it."""
    older = _draft(closing)
    newer = _again(closing, 2, older)
    site = page._site(closing)
    fields = page._signing(site)
    assert fields["draft"] == newer["id"]
    Logbook(closing.root).retract(int(newer["seq"]), "not what the day was")
    seq = _seq(closing)
    response = page._post(site, {**fields, "keep": str(KEEP_LEARNED), "act": "sign"})
    assert response.status == 409, response.body[:400]
    said = page._said(response)
    assert f"#{newer['seq']}" in said and "retracted" in said, said
    _names_the_current(said, older)
    assert _seq(closing) == seq, "nothing written"


def test_a_page_whose_only_draft_was_retracted_says_there_is_none(closing: Logbook) -> None:
    older = _draft(closing)
    site = page._site(closing)
    fields = page._signing(site)
    Logbook(closing.root).retract(int(older["seq"]), "not what the day was")
    seq = _seq(closing)
    response = page._post(site, {**fields, "keep": str(KEEP_LEARNED), "act": "sign"})
    assert response.status == 409, response.body[:400]
    said = page._said(response)
    assert f"#{older['seq']}" in said and "retracted" in said and f"logbook dream day {DAY}" in said, said
    assert _seq(closing) == seq, "nothing written"


def test_a_gated_page_never_names_a_newer_draft_above_its_gate(closing: Logbook) -> None:
    """Through a gate of tier 2 the tier-3 draft is not there: the page says a newer draft exists at a
    tier it does not read, links nothing of it, and a POST that keeps from the older one is refused
    without naming the newer draft's number or id."""
    older = _draft(closing)
    newer = _again(closing, 3, older)
    site = page._site(closing, tiers=(1, 2))
    sign = page._form(page._page(site), "sign")
    assert 'name="keep"' not in sign
    assert "newer draft" in page._text(sign) and "tier this page does not read" in page._text(sign)
    body = page._page(site)
    assert str(newer["id"]) not in body and drafts.short_id(str(newer["id"])) not in body
    seq = _seq(closing)
    response = page._post(site, {**page._signing(site), "keep": str(KEEP_LEARNED), "act": "sign"})
    assert response.status == 400, response.body[:400]
    said = page._said(response)
    assert "superseded" in said and "tier this page does not read" in said, said
    assert f"#{newer['seq']}" not in said and str(newer["id"]) not in response.body.decode("utf-8")
    assert f"logbook day sign {DAY} --keep" in said, said
    assert _seq(closing) == seq, "nothing written"


def _entry(lb: Logbook, max_tier: int) -> None:
    from logbook.core import policy

    path = policy.policy_path(lb.root)
    held = json.loads(path.read_text(encoding="utf-8"))
    held[policy.DREAM_DESTINATION]["max_tier"] = max_tier
    path.write_text(json.dumps(held), encoding="utf-8")


def test_a_page_with_no_pencil_says_so_and_never_speaks_of_a_newer_draft(closing: Logbook) -> None:
    """No pencil at all is not a superseded one: a tier-1 page on a day whose only draft is tier 2, and
    the whole record's page when the entry withholds the only draft, say there is no pencil to keep
    from, as on main, and never that a newer draft exists."""
    for site in (page._site(closing, tiers=(1,)), None):
        if site is None:
            _entry(closing, 1)
            site = page._site(closing)
        text = page._text(page._form(page._page(site), "sign"))
        assert "no pencil on the day to keep from" in text, text
        assert "newer draft" not in text, text
    gated = page._site(closing, tiers=(1,))
    response = page._post(gated, {**page._signing(gated), "keep": str(KEEP_LEARNED), "act": "sign"})
    said = page._said(response)
    assert response.status in (400, 409) and "current draft" not in said, said


def test_a_draft_withheld_since_the_page_was_read_is_not_called_superseded(closing: Logbook) -> None:
    """The page was read with the current draft; the entry was lowered since, so the draft is withheld,
    not superseded: the refusal never says it is superseded by itself."""
    site = page._site(closing)
    fields = page._signing(site)
    _entry(closing, 1)
    seq = _seq(closing)
    response = page._post(site, {**fields, "keep": str(KEEP_LEARNED), "act": "sign"})
    assert response.status == 409, response.body[:400]
    said = page._said(response)
    assert "superseded" not in said and "nothing was written" in said, said
    assert _seq(closing) == seq


def test_a_gated_page_keeps_from_its_current_draft_over_an_older_one_above_the_gate(closing: Logbook) -> None:
    """The tier-2 draft superseded by a tier-1 one: the tier-1 draft is current and in the gate, so a
    tier-1 page offers it and keeps from it."""
    older = _draft(closing)
    photo = next(x for x in _record(closing) if x["kind"] == "photo")
    payload = {
        **older["payload"],
        "segments": [
            {"text": "You were out on the water.", "evidence": [photo["id"]]},
            {"text": "The light holds late in October.", "evidence": [photo["id"]]},
        ],
        "proposals": [],
        "extra": {"parts": ["story", "learned"]},
        "supersedes": older["id"],
    }
    lower = Logbook(closing.root).append(utc(DAY, "22:00"), MODEL, drafts.KIND, 1, payload)
    site = page._site(closing, tiers=(1,))
    sign = page._form(page._page(site), "sign")
    assert re.findall(r'<input type="checkbox" name="keep" value="(\d+)">', sign) == ["1"]
    seq = _seq(closing)
    assert page._post(site, {**page._signing(site), "keep": "1", "act": "sign"}).status == 303
    kept = [x for x in _record(closing) if int(x["seq"]) > seq and x["kind"] == "note"]
    assert [x["payload"]["text"] for x in kept] == ["The light holds late in October."]
    assert kept[0]["payload"]["extra"]["from"] == lower["id"]


def test_the_morning_draft_since_you_signed_is_current_and_kept_from(lb: Logbook) -> None:
    """Signed with a keep, then dreamed again (the morning's draft, since you signed): the earlier keep
    stands and a re-sign keeps a new sentence of the morning draft."""
    older = _draft(lb)
    code, _out, err = keeping._cli("day", "sign", DAY, "--keep", str(KEEP_LEARNED))
    assert code == 0, err
    morning = _again(lb, 2, older, learned=LEARNED, at="23:30")
    seq = _seq(lb)
    code, _out, err = keeping._cli("day", "sign", DAY, "--keep", str(KEEP_DECIDED))
    assert code == 0, err
    kept = [x for x in _record(lb) if int(x["seq"]) > seq and x["kind"] == "note"]
    assert [x["payload"]["extra"]["from"] for x in kept] == [morning["id"]]
