"""Held back on the Day page (RFC 0045, all except junk; RFC 0043 §5, Keep and sign): at the close, beside
Keep and sign, a section for every destination whose policy entry has a `mail_junk` rule, only when that
day held something: first the first-time senders (address and subject, a keep tick each), then the other
senders, one row each by address or domain with how many mails and a keep tick. A tick writes one `keep`
fate (RFC 0042 §4) before the signature, under the one writer lock, so the day's mail from that sender
crosses with the day's bundle and their later mail too. `day sign DAY --keep-sender` writes the same
lines byte for byte. Never a number beside a person's name; nothing fetched; a stale form is a 409.

Synthetic throughout: Ines Nordmann of Oslo, who does not exist, and her boat-share log
(`test_keep_and_sign.py`'s record); Kari and Ola Nordmann, Oslo; a newsletter at news.example.org, a
shop at shop.example.org, an invitation platform's address."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import test_day_page_keep_and_sign as page
import test_keep_and_sign as keeping
import test_no_count_beside_a_name as beside
from persona import utc
from test_keep_and_sign import DAY

from logbook.contrib import held_mail
from logbook.core import crossing, peoples_mail, sender_fates, signing
from logbook.core.store import Logbook

INES = "ines@example.org"
KARI, KARI_ID = "kari@example.org", "019cadd3-6bc0-7dcd-9133-04bb00000002"
OLA, OLA_ID = "ola@example.org", "019cadd3-6bc0-7dcd-9133-04bb00000003"
NEWS_A, NEWS_B = "letters@news.example.org", "offers@news.example.org"
SHOP = "deals@shop.example.org"
NEWCOMER = "hanne.berg@fjord.example.org"  # writes for the first time on DAY
PARTY = "invitations@mail.paperlesspost.com"  # an invitation platform: never junk
RULE = {"categories": ["promotions"]}
DESTINATION = "per-hansen"
NAMES = ("Kari Nordmann", "Ola Nordmann", "Kari", "Ola")

lb = keeping.lb
closing = page.closing


def _resolution(value: str, label: str, entity: str) -> dict[str, Any]:
    return {
        "at": "2026-02-01T09:00:00Z", "source": "ios-contacts", "kind": "resolution", "tier": 2,
        "payload": {"schema": "resolution/v1", "ref": {"kind": "email", "value": value},
                    "entity": {"type": "person", "id": entity, "registry": "logbook"},
                    "label": label, "method": "exact"},
    }  # fmt: skip


def _mail(
    at: str, sender: str, subject: str, category: str | None = "promotions", tier: int = 2
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "mail/v1", "raw_id": f"m-{at}-{sender}", "thread": f"m-{at}-{sender}", "subject": subject,
        "direction": "received", "from": {"email": sender}, "to": [{"email": INES}], "size": 1024,
    }  # fmt: skip
    if category is not None:
        payload["extra"] = {"gmail_category": category}
    return {"at": at, "source": "mail", "kind": "mail", "tier": tier, "payload": payload}


def _junk_policy(lb: Logbook, rule: Any = RULE) -> None:
    path = lb.root / "policy" / "crossing.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    entries[DESTINATION] = {**entries.get(DESTINATION, {}), "max_tier": 2, "mail_junk": rule}
    path.write_text(json.dumps(entries), encoding="utf-8")


@pytest.fixture
def held(closing: Logbook) -> Logbook:
    """DAY with Kari's and Ola's addresses resolved to people, earlier mail from the shop and the
    newsletter, and on DAY: a promotion each from Kari (a person: never junk), the invitation platform
    (never junk), the newcomer (first time), the shop and two addresses of the newsletter; and a
    destination with a junk rule."""
    closing.set_owner_emails([INES])
    closing.append_many(
        [
            _resolution(KARI, "Kari Nordmann", KARI_ID),
            _resolution(OLA, "Ola Nordmann", OLA_ID),
            _mail("2026-10-01T09:00:00Z", SHOP, "September offers"),
            _mail("2026-10-01T09:05:00Z", NEWS_A, "September letter"),
            _mail("2026-10-01T09:10:00Z", NEWS_B, "September offers"),
            _mail(utc(DAY, "08:00"), KARI, "Sails for sale"),
            _mail(utc(DAY, "08:10"), PARTY, "You are invited"),
            _mail(utc(DAY, "08:20"), NEWCOMER, "Kayaks for the harbour"),
            _mail(utc(DAY, "08:30"), SHOP, "Rope, 20% off"),
            _mail(utc(DAY, "08:40"), SHOP, "Last day: rope"),
            _mail(utc(DAY, "08:50"), NEWS_A, "This week at the harbour"),
            _mail(utc(DAY, "09:00"), NEWS_B, "Winter storage"),
        ]
    )
    _junk_policy(closing)
    return Logbook(closing.root)


def _section(markup: str) -> str:
    found = re.search(r'<fieldset class="held-mail">.*?</fieldset>', markup, re.S)
    assert found is not None, "no held-back section"
    return found.group(0)


def _ticks(section: str) -> list[str]:
    return re.findall(r'<input type="checkbox" name="sender" value="([^"]+)">', section)


# -- the reader ----------------------------------------------------------------------------------------------


def test_the_reader_puts_first_time_senders_on_top_and_groups_the_rest(held: Logbook) -> None:
    found = held_mail.read(held, DAY)
    (h,) = found.held
    assert h.destination == DESTINATION
    assert [(f.sender, f.subject) for f in h.first] == [(NEWCOMER, "Kayaks for the harbour")]
    assert [(s.ref, s.mails) for s in h.others] == [
        (("domain", "news.example.org"), 2),
        (("email", SHOP), 2),
    ]
    assert ("email", KARI) not in found.offered and ("email", PARTY) not in found.offered


def test_a_day_that_held_nothing_shows_nothing(held: Logbook) -> None:
    assert not held_mail.read(held, "2026-10-19").shown
    with_no_rule = Logbook(held.root)
    entries = json.loads((held.root / "policy" / "crossing.json").read_text(encoding="utf-8"))
    del entries[DESTINATION]["mail_junk"]
    (held.root / "policy" / "crossing.json").write_text(json.dumps(entries), encoding="utf-8")
    assert not held_mail.read(with_no_rule, DAY).shown


def test_the_reader_holds_to_the_gate(held: Logbook) -> None:
    """A mail above the gate is neither shown nor decides a first time."""
    held.append(**_mail("2026-10-02T09:00:00Z", NEWCOMER, "An earlier word", tier=3))
    assert [f.sender for f in held_mail.read(held, DAY).held[0].first] == []  # every tier: not a first time
    gated = held_mail.read(held, DAY, (1, 2))
    assert [f.sender for f in gated.held[0].first] == [NEWCOMER]
    held.append(**_mail(utc(DAY, "10:00"), "secret@hidden.example.org", "Above the gate", tier=3))
    assert ("email", "secret@hidden.example.org") not in held_mail.read(held, DAY, (1, 2)).offered


def test_a_policy_that_cannot_be_read_fails_closed(held: Logbook) -> None:
    (held.root / "policy" / "owner.json").write_text("{not json", encoding="utf-8")
    found = held_mail.read(held, DAY)
    assert found.problem is not None and found.held == () and found.offered == frozenset()
    _junk_policy(held, {"kategories": ["promotions"]})
    (held.root / "policy" / "owner.json").unlink()
    found = held_mail.read(held, DAY)
    assert found.held[0].problem is not None and found.offered == frozenset()


def test_a_sender_let_go_is_not_offered_again(held: Logbook) -> None:
    sender_fates.write(held, SHOP, sender_fates.LET_GO, "too many offers")
    assert ("email", SHOP) not in held_mail.read(held, DAY).offered


# -- the page ------------------------------------------------------------------------------------------------


def test_the_close_shows_the_section_with_first_time_senders_on_top(held: Logbook) -> None:
    sign = page._form(page._page(page._site(held)), "sign")
    section = _section(sign)
    assert "Held back" in section and DESTINATION in section
    assert section.index(NEWCOMER) < section.index("news.example.org") < section.index(SHOP)
    assert "Kayaks for the harbour" in section
    assert _ticks(section) == [f"email:{NEWCOMER}", "domain:news.example.org", f"email:{SHOP}"]
    assert KARI not in section and PARTY not in section
    assert not re.search(rf"{re.escape(DESTINATION)}\W*\d", page._text(section)), "no count beside a key"
    order = [sign.index('name="accept"'), sign.index('name="sender"'), sign.index('name="act" value="sign"')]
    assert order == sorted(order), "the senders are kept after the delegations, before the signature"
    assert page._hidden(sign)["held"] == held_mail.read(held, DAY).digest


def test_no_number_beside_a_persons_name_and_nothing_fetched(held: Logbook) -> None:
    markup = page._page(page._site(held))
    text = page._text(markup)
    for found in beside.GUARD.finditer(text):
        pytest.fail(f"a number beside a name: {found.group(0)!r}")
    section = _section(markup)
    assert not re.search(r'\b(src|href)="https?:', section), "nothing fetched, nothing linked out"


def test_a_day_with_nothing_held_has_no_section(closing: Logbook) -> None:
    _junk_policy(closing)
    assert 'class="held-mail"' not in page._page(page._site(closing))


def test_a_morning_page_carries_no_section(held: Logbook) -> None:
    assert 'class="held-mail"' not in page._page(page._site(held), "shape=morning")


def test_a_keep_tick_writes_the_fate_before_the_signature_under_one_hold(
    held: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: list[str]
) -> None:
    holds: list[int] = []
    real = Logbook.writer

    def counted(self: Logbook, *args: Any, **kwargs: Any) -> Any:
        from logbook.core import store

        holds.append(store._held.get(self._lock_path(), 0))
        return real(self, *args, **kwargs)

    site = page._site(held)
    fields = {**page._signing(site), "sender": f"email:{SHOP},domain:news.example.org", "act": "sign"}
    seq = page._seq(held)
    monkeypatch.setattr(Logbook, "writer", counted)
    assert page._post(site, fields).status == 303
    assert no_network == []
    written = page._after(held, seq)
    assert [(x["kind"], (x["payload"].get("status"), x["payload"].get("label"))) for x in written] == [
        ("status", ("keep", SHOP)),
        ("status", ("keep", "news.example.org")),
        (signing.KIND, (None, None)),
    ]
    assert holds[0] == 0 and all(depth >= 1 for depth in holds[1:]), "one hold, every write inside it"
    confirmed = set(written[-1]["payload"].get("confirmed") or [])
    assert {str(x["id"]) for x in written[:2]} <= confirmed, "the fates are ink the signature confirms"


def test_a_kept_sender_crosses_with_the_days_bundle(held: Logbook, tmp_path: Path) -> None:
    site = page._site(held)
    assert page._post(site, {**page._signing(site), "sender": f"email:{SHOP}", "act": "sign"}).status == 303
    req = crossing.request(
        Logbook(held.root), DESTINATION, f"{DAY}T00:00:00Z", "2026-10-21T00:00:00Z", (1, 2),
        frozenset({"mail"}), mail="all-except-junk",
    )  # fmt: skip
    sent = {
        line["payload"]["from"]["email"] for line in crossing.select(Logbook(held.root), req).lines
        if line["kind"] == "mail"
    }  # fmt: skip
    assert SHOP in sent and NEWS_A not in sent and KARI in sent


def test_untouched_means_it_stays_home(held: Logbook) -> None:
    site = page._site(held)
    seq = page._seq(held)
    assert page._post(site, {**page._signing(site), "act": "sign"}).status == 303
    assert [x["kind"] for x in page._after(held, seq)] == [signing.KIND]
    assert sender_fates.read(Logbook(held.root)).kept == frozenset()


def test_a_stale_form_is_refused_with_409_and_nothing_written(held: Logbook) -> None:
    site = page._site(held)
    fields = {**page._signing(site), "sender": f"email:{SHOP}", "act": "sign"}
    held.append(**_mail(utc(DAY, "11:00"), "news@another.example.org", "Late news"))  # the day held more
    seq = page._seq(held)
    response = page._post(page._site(held), fields)
    assert response.status == 409 and "nothing was written" in page._said(response)
    assert page._seq(held) == seq


def test_a_sender_the_page_did_not_offer_is_refused_and_nothing_written(held: Logbook) -> None:
    site = page._site(held)
    seq = page._seq(held)
    response = page._post(site, {**page._signing(site), "sender": f"email:{KARI}", "act": "sign"})
    assert response.status == 400 and "held nothing back" in page._said(response)
    assert page._seq(held) == seq


def test_the_other_refusals_of_the_form_still_hold(held: Logbook) -> None:
    site = page._site(held)
    fields = {**page._signing(site), "sender": f"email:{SHOP}", "proposals": "stale", "act": "sign"}
    seq = page._seq(held)
    assert page._post(site, fields).status == 409
    assert page._seq(held) == seq


# -- the command, byte for byte ---------------------------------------------------------------------------


def test_the_page_writes_what_day_sign_keep_sender_writes_byte_for_byte(
    held: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    twin = page._twin(held, tmp_path, "twin")
    page._counting(monkeypatch)
    page._cli(monkeypatch, twin, "day", "sign", DAY, "--keep-sender", f"{NEWCOMER},news.example.org")
    monkeypatch.setenv("LOGBOOK_HOME", str(held.root))
    page._counting(monkeypatch)
    site = page._site(held)
    fields = {**page._signing(site), "sender": f"email:{NEWCOMER},domain:news.example.org", "act": "sign"}
    assert page._post(site, fields).status == 303
    assert page._record(held.root) == page._record(twin), "the command's lines, byte for byte"


def test_day_sign_keep_sender_refuses_what_the_day_did_not_hold(held: Logbook) -> None:
    seq = page._seq(held)
    code, _out, err = keeping._cli("day", "sign", DAY, "--keep-sender", KARI)
    assert code == 2 and "held nothing back" in err
    code, _out, err = keeping._cli("day", "sign", DAY, "--keep-sender", "not a sender")
    assert code == 2
    assert page._seq(held) == seq
    assert peoples_mail.KIND == "mail"


def test_day_sign_says_what_it_kept_and_never_a_count_beside_a_name(held: Logbook) -> None:
    code, out, err = keeping._cli("day", "sign", DAY, "--keep-sender", SHOP)
    assert code == 0, err
    assert f"kept {SHOP}" in out
    for found in beside.GUARD.finditer(out):
        pytest.fail(f"a number beside a name: {found.group(0)!r}")
