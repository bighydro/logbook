"""`logbook review receipts` (RFC 0043 §12, the money bridge): receipt mails proposed as payments and
confirmed in review. A synthetic record of Ines Nordmann of Oslo, who does not exist: receipts from
invented merchants at example.org addresses in CHF, EUR, NOK and USD, a newsletter that names a price
and is no receipt, a refund, a receipt a Google Wallet line already holds, and a mail from Kari, whom
the record names. Nothing is written unless told; what is written is tier 3, and a tier-2 reader sees
none of it. Nothing is looked up."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.contrib import receipts
from logbook.core import ledger, reading
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
EX = "example.org"  # every merchant here is invented, at a reserved domain
SINCE = "2026-09-01"
OWNER = {"name": "Ines Nordmann", "email": "ines@example.org"}
KARI = {
    "id": "019cadd3-6bc0-7dcd-9133-000000000112",
    "name": "Kari Nordmann",
    "email": "kari@nordmann.example.org",
}
SAILMAKER = {"id": "019cadd3-6bc0-7dcd-9133-000000000301", "label": "Seilloftet AS",
             "domain": "seilloftet.example.org"}  # fmt: skip

COFFEE_BODY = """Thank you for your order #1042.

2 x Espresso beans, 1 kg      CHF 1'200.00
1 x Hand grinder              CHF 34.50
MwSt 8.1 %                    CHF 92.55
Total                         CHF 1'234.50

Fjordkaffe, an invented roaster"""

BOOK_BODY = """Receipt

Bokhylla order 77-310
1 x Charts of the Oslofjord   € 12,90
Total paid: € 12,90"""

SAIL_BODY = """Ordrebekreftelse 5531

Reparasjon av genua   NOK 1 600
Frakt                 NOK 240
Totalt å betale:      NOK 1 840"""

NEWSLETTER_BODY = """New this autumn: a dark roast from the hills, CHF 14.90 a bag.
Shop now and read our brewing guide."""

REFUND_BODY = """Your refund has been processed.

Charts of the Oslofjord   € 12,90
Refund total: € 12,90"""

KIOSK_BODY = """Kvittering

1 x Sjokolade   NOK 45,00
Sum             NOK 45,00"""


def _at(day: int, hour: int = 10, minute: int = 0, month: int = 9) -> str:
    return f"2026-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:00Z"


def _mail(at: str, email: str, name: str | None, subject: str, body: str | None = None) -> dict[str, Any]:
    sender = {"email": email, **({"name": name} if name else {})}
    payload: dict[str, Any] = {
        "schema": "mail/v1", "raw_id": f"mail:{at}.{email}", "message_id": f"{at}.{email}",
        "thread": f"{at}.{email}", "from": sender, "to": [{"email": OWNER["email"], "name": OWNER["name"]}],
        "subject": subject, "direction": "received", "size": 1200,
    }  # fmt: skip
    if body is not None:
        payload["body"] = body
    return {"at": at, "source": "mail", "kind": "mail", "tier": 2, "payload": payload}


def _resolution(ref: tuple[str, str], kind: str, entity: str, label: str) -> dict[str, Any]:
    return {
        "at": "2026-08-01T08:00:00Z", "source": "manual", "kind": "resolution", "tier": 2,
        "payload": {"schema": "resolution/v1", "ref": {"kind": ref[0], "value": ref[1]},
                    "entity": {"type": kind, "id": entity, "registry": "logbook"}, "label": label,
                    "method": "owner"},
    }  # fmt: skip


def wallet(at: str, amount: float, currency: str, merchant: str, n: int) -> dict[str, Any]:
    """A card payment as Google Wallet's Takeout writes it (`takeout/pay.py`): tier 3."""
    return {
        "at": at, "source": "google-takeout", "kind": "transaction", "tier": 3,
        "payload": {"schema": "transaction/v1", "raw_id": f"pay:{n}", "amount": amount, "currency": currency,
                    "merchant": merchant, "provider": "google-pay", "status": "posted"},
    }  # fmt: skip


def drafts() -> list[dict[str, Any]]:
    return [
        _resolution(("email", KARI["email"]), "person", KARI["id"], KARI["name"]),
        _resolution(("domain", SAILMAKER["domain"]), "company", SAILMAKER["id"], SAILMAKER["label"]),
        _mail(_at(3), f"orders@fjordkaffe.{EX}", "Fjordkaffe", "Your order #1042 is confirmed", COFFEE_BODY),
        _mail(_at(5), "no-reply@bokhylla.example.org", "Bokhylla", "Receipt for your purchase", BOOK_BODY),
        _mail(_at(8), "ordre@seilloftet.example.org", None, "Ordrebekreftelse 5531", SAIL_BODY),
        _mail(_at(10), "receipts@chartroom.example.org", "Chartroom", "Your receipt from Chartroom: $12.90"),
        _mail(_at(12), f"noreply@fjordkaffe.{EX}", "Fjordkaffe", "Autumn beans are here", NEWSLETTER_BODY),
        _mail(_at(14), f"no-reply@bokhylla.{EX}", "Bokhylla", "Your refund for order 77-310", REFUND_BODY),
        _mail(_at(16, 9), "kvittering@fjordkiosk.example.org", "Fjordkiosk", "Kvittering 2231", KIOSK_BODY),
        wallet(_at(16, 9, 2), -45.0, "NOK", "FJORDKIOSK AS", 1),  # the kiosk's receipt, already in the record
        _mail(_at(18), KARI["email"], KARI["name"], "Receipt for the cabin groceries", "Total NOK 640"),
    ]  # fmt: skip


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    found = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(found.root))
    found.set_owner_emails([OWNER["email"]])
    found.append_many(drafts())
    return found


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(["review", "receipts", "--since", SINCE, *args])
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_run(capsys, *args, "--json"))
    return data


def _refused(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    with pytest.raises(SystemExit) as e:
        cli.main([*args])
    assert e.value.code == 2, args
    return capsys.readouterr().err


def _new_lines(lb: Logbook, seq: int) -> list[dict[str, Any]]:
    return [line for line in Logbook(lb.root).lines() if int(line["seq"]) > seq]


def _number(data: dict[str, Any], merchant: str) -> int:
    return next(int(p["number"]) for p in data["proposals"] if p["merchant"] == merchant)


# -- the rules: amounts, totals, refunds, merchants -------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value", "currency"),
    [
        ("CHF 1'234.50", 1234.50, "CHF"),
        ("CHF 1\u2019234.50", 1234.50, "CHF"),
        ("€ 12,90", 12.90, "EUR"),
        ("12,90 €", 12.90, "EUR"),
        ("$12.90", 12.90, "USD"),
        ("US$ 1,250.00", 1250.00, "USD"),
        ("NOK 1 840", 1840.0, "NOK"),
        ("NOK\u00a01\u00a0840,50", 1840.50, "NOK"),
        ("1.234,50 EUR", 1234.50, "EUR"),
        ("Total: 99.- CHF", 99.0, "CHF"),
        ("GBP 7.5", 7.50, "GBP"),
    ],
)
def test_an_amount_is_read_in_its_common_forms(text: str, value: float, currency: str) -> None:
    (found,) = receipts.amounts(text)
    assert (found.value, found.currency) == (value, currency)


def test_kr_alone_names_no_currency_and_a_bare_number_is_no_amount() -> None:
    """`kr` is the Norwegian, Swedish and Danish crown: without a code it is no currency, as the Google
    Wallet reader rules (`takeout/pay.py`). A number with no currency is no amount."""
    assert receipts.amounts("Sum 45,00 kr") == []
    assert receipts.amounts("Order 1042, 3 items, 12.90") == []


def test_the_total_is_preferred_over_the_line_items_and_a_refund_is_money_in() -> None:
    chosen = receipts.choose("Your order #1042 is confirmed", COFFEE_BODY)
    assert chosen is not None
    assert (chosen.amount.value, chosen.amount.currency, chosen.total, chosen.refund) == (
        1234.50,
        "CHF",
        True,
        False,
    )
    refund = receipts.choose("Your refund for order 77-310", REFUND_BODY)
    assert refund is not None and refund.refund and refund.signed == 12.90
    assert chosen.signed == -1234.50, "a purchase is money out, negative (RFC 0021 rule 2)"


def test_a_dash_between_words_is_no_minus_and_a_minus_on_the_amount_is_a_refund() -> None:
    plain = receipts.choose("Your receipt", "1 x Charts of the Oslofjord - € 12,90\nTotal € 12,90")
    assert plain is not None and not plain.refund and plain.signed == -12.90
    credited = receipts.choose("Your receipt", "Total: -€12,90")
    assert credited is not None and credited.refund and credited.signed == 12.90


def test_with_no_total_line_the_largest_of_several_amounts_is_taken_with_less_confidence() -> None:
    found = receipts.choose("Your order", "Beans CHF 18.00\nGrinder CHF 34.50")
    assert found is not None and found.amount.value == 34.50 and not found.total and not found.only


def test_a_price_without_an_order_or_receipt_marker_is_no_receipt() -> None:
    assert receipts.choose("Autumn beans are here", NEWSLETTER_BODY) is None


def test_the_merchant_is_the_display_name_else_the_domain() -> None:
    assert (
        receipts.merchant_of({"email": "orders@fjordkaffe.example.org", "name": "Fjordkaffe"}) == "Fjordkaffe"
    )
    assert receipts.merchant_of({"email": "ordre@post.seilloftet.example.org"}) == "Seilloftet"
    assert receipts.merchant_of({"email": "no-reply@bokhylla.example.org", "name": "No-Reply"}) == "Bokhylla"


# -- the queue ---------------------------------------------------------------------------------------------


def test_the_queue_proposes_each_receipt_with_its_merchant_amount_currency_time_mail_and_confidence(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _json(capsys)
    assert data["kind"] == "receipts" and data["tier"] == 3
    found = [(p["merchant"], p["amount"], p["currency"], p["refund"], p["at"]) for p in data["proposals"]]
    assert found == [
        ("Fjordkaffe", -1234.50, "CHF", False, _at(3)),
        ("Bokhylla", -12.90, "EUR", False, _at(5)),
        ("Seilloftet AS", -1840.0, "NOK", False, _at(8)),  # the Manifest's name for the org on the domain
        ("Chartroom", -12.90, "USD", False, _at(10)),  # no body kept: the subject carries it
        ("Bokhylla", 12.90, "EUR", True, _at(14)),  # a refund: money in
    ]
    refunds = [p for p in data["proposals"] if p["refund"]]
    assert [(p["merchant"], p["amount"], p["currency"]) for p in refunds] == [("Bokhylla", 12.90, "EUR")]
    assert [p["number"] for p in data["proposals"]] == [1, 2, 3, 4, 5], "numbered from 1 in time order"
    mails = {str(line["id"]): line for line in Logbook(lb.root).lines() if line["kind"] == "mail"}
    for p in data["proposals"]:
        assert mails[p["mail"]]["at"] == p["at"], "the mail line's id and the time of the mail"
        assert 0 < p["confidence"] < 1
    by_merchant = {p["merchant"]: p for p in data["proposals"] if not p["refund"]}
    assert by_merchant["Seilloftet AS"]["confidence"] > by_merchant["Chartroom"]["confidence"], (
        "an org in the Manifest on the sender's domain is a plus"
    )
    assert "org in the Manifest" in by_merchant["Seilloftet AS"]["why"]
    subjects = {p["mail"] for p in data["proposals"]}
    newsletter = next(i for i, line in mails.items() if line["payload"]["subject"] == "Autumn beans are here")
    kari = next(i for i, line in mails.items() if line["payload"]["from"]["email"] == KARI["email"])
    assert newsletter not in subjects, "a price is not a receipt"
    assert kari not in subjects, "a person the record names is no merchant"


def test_nothing_is_written_without_the_owner_s_accept(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = int(lb.meta["seq"])
    out = _run(capsys)
    _json(capsys)
    cli.main(["review"])
    capsys.readouterr()
    assert int(Logbook(lb.root).meta["seq"]) == seq
    assert out.splitlines()[0].startswith("5 receipts proposed · 1 already in the record")
    assert "--accept N,N" in out


def test_accept_writes_one_tier_3_transaction_line_with_the_mail_s_id(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _json(capsys)
    coffee, sail = _number(data, "Fjordkaffe"), _number(data, "Seilloftet AS")
    proposals = {p["number"]: p for p in data["proposals"]}
    seq = int(lb.meta["seq"])
    written = _json(capsys, "--accept", f"{coffee},{sail}")
    new = _new_lines(lb, seq)
    assert len(new) == 2 == len(written["written"])
    for line, number in zip(new, (coffee, sail), strict=True):
        p = proposals[number]
        assert (line["kind"], line["tier"], line["source"], line["at"]) == (
            "transaction",
            3,
            "receipts",
            p["at"],
        )
        payload = line["payload"]
        assert payload["schema"] == "transaction/v1"
        assert (payload["amount"], payload["currency"], payload["merchant"]) == (
            p["amount"],
            p["currency"],
            p["merchant"],
        )
        assert payload["provider"] == "receipts"
        assert payload["extra"]["from"] == p["mail"]
    after = _json(capsys)
    assert {p["merchant"] for p in after["proposals"]} == {"Bokhylla", "Chartroom"}, (
        "accepted, never proposed again"
    )
    assert after["accepted"] == 2
    standing = ledger.ledger(reading.read(Logbook(lb.root), "2026-09-01", "2026-09-30"))
    assert sorted((e.amount, e.currency) for e in standing.entries if e.source == "receipts") == [
        (-1840.0, "NOK"),
        (-1234.50, "CHF"),
    ], "the ledger reads the accepted receipts as payments"


def test_reject_is_remembered_as_a_tier_3_not_a_payment_line(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """The owner's answer: a no is tier 3, like the payments. A `note/v1` is tier 2 by RFC 0010, so the
    no is a line of its own, `receipt-review/v1`, as a scene's no is (RFC 0040 §5)."""
    data = _json(capsys)
    chart = next(p for p in data["proposals"] if p["merchant"] == "Chartroom")
    seq = int(lb.meta["seq"])
    out = _run(capsys, "--reject", str(chart["number"]))
    (note,) = _new_lines(lb, seq)
    assert (note["kind"], note["source"], note["tier"]) == ("receipt-review", "receipts", 3)
    assert note["payload"]["schema"] == "receipt-review/v1"
    assert note["payload"]["text"] == "not a payment"
    assert note["payload"]["labels"] == ["not-a-payment"]
    assert note["payload"]["extra"] == {"from": chart["mail"]}
    assert "12.90" not in json.dumps(note) and "USD" not in json.dumps(note), "the no names no amount"
    assert "not a payment" in out
    again = _json(capsys)
    assert chart["mail"] not in {p["mail"] for p in again["proposals"]}, "never proposed again"
    assert again["rejected"] == 1
    assert int(Logbook(lb.root).meta["seq"]) == seq + 1


def test_a_receipt_the_record_holds_from_another_source_is_shown_and_never_written(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _json(capsys)
    (held,) = data["already"]
    assert (held["merchant"], held["amount"], held["currency"]) == ("Fjordkiosk", -45.0, "NOK")
    assert held["number"] is None
    assert held["held_by"]["source"] == "google-takeout"
    assert "Fjordkiosk" not in {p["merchant"] for p in data["proposals"]}
    out = _run(capsys)
    assert any("already in the record" in line and "Fjordkiosk" in line for line in out.splitlines())
    seq = int(lb.meta["seq"])
    err = _refused(capsys, "review", "receipts", "--since", SINCE, "--accept", "6")
    assert "no proposal 6" in err
    assert int(Logbook(lb.root).meta["seq"]) == seq


def test_a_receipt_written_before_the_ledger_delivered_it_is_listed_as_covered(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """The ledger's line wins: once a payment source holds the payment a receipt's line holds, the
    queue lists the pair, and the receipt's line is the one to take back (`repair retract`)."""
    data = _json(capsys)
    _run(capsys, "--accept", str(_number(data, "Fjordkaffe")))
    receipt = next(line for line in Logbook(lb.root).lines() if line["source"] == "receipts")
    lb.append_many([wallet(_at(4, 7), -1234.50, "CHF", "FJORDKAFFE ZUERICH", 2)])
    after = _json(capsys)
    (covered,) = after["covered"]
    assert covered["line"] == receipt["id"] and covered["seq"] == receipt["seq"]
    assert covered["held_by"]["source"] == "google-takeout"
    out = _run(capsys)
    assert f"logbook repair retract {receipt['seq']}" in out
    assert "Fjordkaffe" not in {p["merchant"] for p in after["proposals"]}


def test_a_tier_2_reader_sees_none_of_it(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    data = _json(capsys)
    _run(capsys, "--accept", str(_number(data, "Fjordkaffe")))
    _run(capsys, "--reject", str(_number(data, "Chartroom")))
    every = reading.read(Logbook(lb.root), "2026-09-01", "2026-10-31")
    assert any(line["source"] == "receipts" and line["kind"] == "transaction" for line in every.lines)
    assert any(
        line["source"] == "receipts" and line["kind"] == "receipt-review" and line["tier"] == 3
        for line in every.lines
    ), "the no is in the record, at tier 3"
    gated = reading.read(Logbook(lb.root), "2026-09-01", "2026-10-31", tiers=(1, 2))
    assert not [line for line in gated.lines if line["kind"] == "transaction"]
    assert not [line for line in gated.lines if line["source"] == "receipts"], "neither a payment nor a no"
    for line in gated.lines:
        text = json.dumps(line)
        assert "receipt-review" not in text and "not-a-payment" not in text
    withheld = receipts.read(Logbook(lb.root), SINCE, tiers=(1, 2))
    assert withheld.withheld and not withheld.proposals and not withheld.already and not withheld.covered
    assert withheld.to_json()["proposals"] == []


def test_the_queue_refuses_what_it_cannot_do_and_writes_nothing(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = int(lb.meta["seq"])
    for args, words in (
        (("review", "receipts", "--name", "1", "Fjordkaffe"), "--name"),
        (("review", "receipts", "--all-above", "1"), "--all-above"),
        (("review", "receipts", "--since", "last week"), "--since takes a day"),
        (
            ("review", "receipts", "--since", SINCE, "--accept", "1", "--reject", "1"),
            "both accepted and rejected",
        ),
        (("review", "receipts", "--since", SINCE, "--accept", "1,9"), "no proposal 9"),
        (("review", "org", "--since", SINCE), "--since goes with `review receipts`"),
    ):
        err = _refused(capsys, *args)
        assert words in err, (args, err)
    assert int(Logbook(lb.root).meta["seq"]) == seq, "every number checked before the first line"


# -- what the independent review broke ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("subject", "body", "value", "currency", "refund"),
    [
        ("Your ticket receipt", "Ferry\nTotal NOK 320,00\nNon-refundable.", 320.0, "NOK", False),
        ("Receipt", "Total EUR 40.00\nRefund policy: see our terms", 40.0, "EUR", False),
        ("Ordrebekreftelse 5531 NOK 1 840", None, 1840.0, "NOK", False),
        ("Invoice 2026-09 EUR 12.90", None, 12.90, "EUR", False),
        ("Your order", "Flight XY 1234 USD 300.00\nTotal USD 300.00", 300.0, "USD", False),
        ("Your receipt", "Total EUR 12.90 (approx. NOK 150.00)", 12.90, "EUR", False),
        ("Your receipt", "Total incl. VAT CHF 12.00\nVAT CHF 0.90", 12.0, "CHF", False),
        ("Kvittering", "Sum inkl. mva NOK 45,00", 45.0, "NOK", False),
        ("Your order", "Beans CHF 66.48 Total CHF 66.48 Free shipping over CHF 100", 66.48, "CHF", False),
        ("Your refund", "Charts € 12,90\nRefund total € 12,90", 12.90, "EUR", True),
    ],
)  # fmt: skip
def test_a_footer_a_date_an_order_number_and_a_second_currency_do_not_fool_the_rules(
    subject: str, body: str | None, value: float, currency: str, refund: bool
) -> None:
    found = receipts.choose(subject, body)
    assert found is not None
    assert (found.amount.value, found.amount.currency, found.refund) == (value, currency, refund)


def test_a_word_inside_another_is_no_marker() -> None:
    """`reçu` is a receipt; `recurring` is not."""
    assert receipts.choose("Set up a recurring delivery", "Beans from € 12,90 a bag") is None


def test_a_long_body_is_read_in_linear_time() -> None:
    import time

    started = time.monotonic()
    receipts.choose("Your order", "1" + " 123" * 16000)
    receipts.choose("Your order", "EUR 1'" * 10000)
    receipts.choose("Your order", ("Total CHF 12.90 " * 4000)[:65536])
    assert time.monotonic() - started < 2.0


def test_an_order_address_is_known_in_its_common_spellings() -> None:
    for email in ("no_reply@a.example.org", "auto-confirm@a.example.org", "orders.eu@a.example.org"):
        assert receipts.role(email), email
    assert not receipts.role("ola@nordmann.example.org")


def test_a_short_or_generic_merchant_name_matches_nothing() -> None:
    assert not receipts.same_merchant(("seilloftetas",), "AS")
    assert not receipts.same_merchant(("shop",), "WEBSHOP NORGE")
    assert receipts.same_merchant(("fjordkiosk",), "FJORDKIOSK AS")


def _seq_of(lb: Logbook) -> int:
    return int(Logbook(lb.root).meta["seq"])


def test_a_person_the_record_names_at_an_order_address_is_no_merchant_and_a_sent_mail_no_receipt(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    per = "orders@hansen.example.org"
    sent = _mail(_at(20), "orders@fjordkaffe.example.org", "Fjordkaffe", "Re: your order #1042", COFFEE_BODY)
    sent["payload"]["direction"] = "sent"
    lb.append_many(
        [
            _resolution(("email", per), "person", "019cadd3-6bc0-7dcd-9133-000000000113", "Per Hansen"),
            _mail(_at(19), per, "Per Hansen", "Your order: the sail, NOK 900", "Total NOK 900"),
            sent,
        ]
    )
    data = _json(capsys)
    assert {p["domain"] for p in data["proposals"]}.isdisjoint({"hansen.example.org"}), "a person"
    assert _at(19) not in {p["at"] for p in [*data["proposals"], *data["already"]]}, (
        "a person the record names"
    )
    assert [p["at"] for p in data["proposals"]].count(_at(20)) == 0, "a sent mail is no receipt"


def test_a_retracted_no_proposes_the_mail_again_and_a_retracted_accept_can_be_accepted_again(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _json(capsys)
    chart, coffee = data["proposals"][3], data["proposals"][0]
    _run(capsys, "--reject", str(chart["number"]), "--accept", str(coffee["number"]))
    written = [line for line in Logbook(lb.root).lines() if line["source"] == "receipts"]
    for line in written:
        Logbook(lb.root).retract(int(line["seq"]), "a test of the queue")
    again = _json(capsys)
    assert {chart["mail"], coffee["mail"]} <= {p["mail"] for p in again["proposals"]}
    seq = _seq_of(lb)
    number = next(p["number"] for p in again["proposals"] if p["mail"] == coffee["mail"])
    out = _json(capsys, "--accept", str(number))
    assert len(out["written"]) == 1 and _seq_of(lb) == seq + 1


def test_two_mails_for_one_order_are_one_payment(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    """A shipping notice repeats the order's total a day later: once the first is accepted, the second
    is already in the record, held by the receipt's own line."""
    lb.append_many(
        [
            _mail(
                _at(4),
                "orders@fjordkaffe.example.org",
                "Fjordkaffe",
                "Your order #1042 has shipped",
                COFFEE_BODY,
            )
        ]
    )
    data = _json(capsys)
    first = next(p for p in data["proposals"] if p["at"] == _at(3))
    _run(capsys, "--accept", str(first["number"]))
    after = _json(capsys)
    held = [p for p in after["already"] if p["at"] == _at(4)]
    assert held and held[0]["held_by"]["source"] == "receipts"


def test_the_two_day_window_is_the_edge(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    lb.append_many(
        [
            _mail(_at(22, 12), "orders@ankerbua.example.org", "Ankerbua", "Your order #7", "Total NOK 99,00"),
            _mail(_at(25, 12), "orders@tauverk.example.org", "Tauverk", "Your order #8", "Total NOK 77,00"),
            wallet(_at(24, 12), -99.0, "NOK", "ANKERBUA", 3),  # two days after: held
            wallet(_at(28, 12, 1), -77.0, "NOK", "TAUVERK", 4),  # three days and a minute after: not
        ]
    )
    data = _json(capsys)
    assert "Ankerbua" in {p["merchant"] for p in data["already"]}
    assert "Tauverk" in {p["merchant"] for p in data["proposals"]}


def test_the_queue_never_shows_a_sender_s_address_and_names_the_merchant_by_its_domain(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """Not in the rows, not in the JSON, not in what is written back: a display name that is itself
    an address is no name either."""
    lb.append_many(
        [
            _mail(
                _at(21),
                "orders@tauverk.example.org",
                "orders@tauverk.example.org",
                "Your order #9",
                "Total NOK 77,00",
            )
        ]
    )
    out = _run(capsys)
    data = _json(capsys)
    cli.main(["review"])  # and as `review` with no kind lists it
    alone = capsys.readouterr().out
    assert "@" not in out and "@" not in json.dumps(data)
    assert "@" not in alone[alone.index("receipts") :]
    for domain in ("fjordkaffe.example.org", "bokhylla.example.org", "seilloftet.example.org"):
        assert domain in out, domain
    assert {p["domain"] for p in data["proposals"]} >= {"fjordkaffe.example.org", "chartroom.example.org"}
    tauverk = next(p for p in data["proposals"] if p["domain"] == "tauverk.example.org")
    assert tauverk["merchant"] == "Tauverk", "an address is no display name"
    written = _run(capsys, "--accept", str(tauverk["number"]))
    assert "@" not in written


def test_a_duplicate_in_one_batch_is_refused_counted_and_never_written_twice(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """Two mails of one payment on one day (the order and its confirmation), accepted together: the
    first is written, the second refused and counted; a different payment in the batch is written."""
    lb.append_many(
        [
            _mail(
                _at(3, 15),
                f"orders@fjordkaffe.{EX}",
                "Fjordkaffe",
                "Order #1042: payment confirmed",
                COFFEE_BODY,
            )
        ]
    )
    data = _json(capsys)
    coffee = [p["number"] for p in data["proposals"] if p["merchant"] == "Fjordkaffe"]
    assert len(coffee) == 2, "both mails are proposed: neither is in the record yet"
    sail = _number(data, "Seilloftet AS")
    seq = _seq_of(lb)
    out = _json(capsys, "--accept", ",".join(map(str, [*coffee, sail])))
    new = _new_lines(lb, seq)
    assert len(new) == 2, "the coffee once, the sail once"
    assert sorted(line["payload"]["merchant"] for line in new) == ["Fjordkaffe", "Seilloftet AS"]
    verdicts = [w["verdict"] for w in out["written"]]
    assert verdicts.count("accepted") == 2 and verdicts.count("duplicate") == 1
    (dup,) = [w for w in out["written"] if w["verdict"] == "duplicate"]
    assert dup["number"] == coffee[1] and dup["same_as"] == coffee[0] and dup["line"] is None
    after = _json(capsys)
    assert "Fjordkaffe" not in {p["merchant"] for p in after["proposals"]}, "the second is now in the record"
    assert "Fjordkaffe" in {p["merchant"] for p in after["already"]}


def test_a_duplicate_in_one_batch_is_said_in_words(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    lb.append_many(
        [
            _mail(
                _at(3, 15),
                f"orders@fjordkaffe.{EX}",
                "Fjordkaffe",
                "Order #1042: payment confirmed",
                COFFEE_BODY,
            )
        ]
    )
    data = _json(capsys)
    first, second = [p["number"] for p in data["proposals"] if p["merchant"] == "Fjordkaffe"]
    seq = _seq_of(lb)
    out = _run(capsys, "--accept", f"{first},{second}")
    assert _seq_of(lb) == seq + 1
    assert f"{second}  Fjordkaffe" in out and f"the same payment as {first}" in out and "not written" in out
    assert "1 duplicate refused" in out
