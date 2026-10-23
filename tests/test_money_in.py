"""The money slot (RFC 0043 §11, §12): `money_in(lb, start, end)` is the `transaction/v1` lines of a
window with their merchant and amount, tier 3; when no payment source covers the window it says so
from the record's own lines ("No payment source covers this day — the last ends <date>"), never an
empty sum. Synthetic: a card in NOK at made-up merchants, the Oslo persona."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from orgs_record import wire

from logbook.core import money
from logbook.core.store import Logbook

TZ = "Europe/Oslo"


def _record(tmp_path: Path, drafts: list[dict[str, Any]]) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", TZ)
    if drafts:
        lb.append_many(drafts)
    return lb


@pytest.fixture
def card(tmp_path: Path) -> Logbook:
    return _record(
        tmp_path,
        [
            wire("2026-10-01T07:10:00Z", "Bakeri Solvind", -64.0, "card-1"),
            wire("2026-10-05T10:00:00Z", "Fjordkiosk AS", -42.5, "card-2"),
            wire("2026-10-05T15:30:00Z", "Marina Example", -310.0, "card-3"),
            wire("2026-10-05T18:00:00Z", "Per Hansen", 150.0, "card-4"),
            wire("2026-10-06T09:00:00Z", "Bakeri Solvind", -58.0, "card-5"),
        ],
    )


def test_a_covered_day_lists_its_transactions_with_merchant_and_amount(card: Logbook) -> None:
    found = money.money_in(card, "2026-10-05", "2026-10-05")
    assert [(p.merchant, p.amount, p.currency) for p in found.payments] == [
        ("Fjordkiosk AS", -42.5, "NOK"),
        ("Marina Example", -310.0, "NOK"),
        ("Per Hansen", 150.0, "NOK"),
    ]
    assert found.covered and found.said is None
    assert found.totals == {"NOK": {"spent": -352.5, "received": 150.0, "net": -202.5}}
    data = found.to_json()
    assert data["payments"][0]["merchant"] == "Fjordkiosk AS" and data["payments"][0]["line"]
    assert data["tier"] == 3


def test_a_day_past_the_last_payment_line_says_where_the_sources_end_and_sums_nothing(card: Logbook) -> None:
    found = money.money_in(card, "2026-10-12", "2026-10-12")
    assert found.payments == [] and found.totals == {}
    assert not found.covered
    assert found.said == "No payment source covers this day — the last ends 2026-10-06"
    assert found.to_json()["totals"] is None, "never an empty sum"
    week = money.money_in(card, "2026-10-12", "2026-10-18")
    assert week.said == "No payment source covers these days — the last ends 2026-10-06"


def test_a_day_before_the_first_payment_line_says_where_they_begin(card: Logbook) -> None:
    found = money.money_in(card, "2026-09-01", "2026-09-01")
    assert found.said == "No payment source covers this day — the first begins 2026-10-01"


def test_a_covered_day_with_no_transaction_says_no_card_lines_never_a_zero(card: Logbook) -> None:
    found = money.money_in(card, "2026-10-03", "2026-10-03")
    assert found.covered and found.payments == [] and found.totals == {}
    assert found.said == "No card lines for this day"


def test_a_record_with_no_payment_source_says_so(tmp_path: Path) -> None:
    found = money.money_in(_record(tmp_path, []), "2026-10-05", "2026-10-05")
    assert found.said == "No payment source covers this day — the record holds no payment lines"


def test_a_window_running_past_the_last_line_lists_what_it_holds_and_names_the_gap(card: Logbook) -> None:
    found = money.money_in(card, "2026-10-06", "2026-10-08")
    assert [p.merchant for p in found.payments] == ["Bakeri Solvind"]
    assert found.said == "No payment source covers 2026-10-07 to 2026-10-08 — the last ends 2026-10-06"


def test_a_retracted_or_deleted_transaction_is_not_summed(card: Logbook) -> None:
    [line] = [x for x in card.lines() if x["payload"].get("raw_id") == "card-3"]
    card.retract(int(line["seq"]), "a duplicate")
    deleted = wire("2026-10-05T19:00:00Z", "Marina Example", -999.0, "card-6")
    deleted["payload"]["extra"] = {"deleted": True}
    card.append_many([deleted])
    found = money.money_in(card, "2026-10-05", "2026-10-05")
    assert [(p.merchant, p.deleted) for p in found.payments] == [
        ("Fjordkiosk AS", False),
        ("Per Hansen", False),
        ("Marina Example", True),
    ]
    assert found.totals == {"NOK": {"spent": -42.5, "received": 150.0, "net": 107.5}}


@pytest.mark.parametrize("tiers", [(1, 2), (2,), (1,)])
def test_through_a_gate_without_tier_three_nothing_of_the_money_is_shown(
    card: Logbook, tiers: tuple[int, ...]
) -> None:
    for day in ("2026-10-05", "2026-10-12"):
        found = money.money_in(card, day, day, tiers=tiers)
        assert found.payments == [] and found.totals == {} and not found.covered
        assert found.said == money.HIDDEN
        text = str(found.to_json())
        for word in ("Fjordkiosk", "2026-10-06", "2026-10-01", "NOK"):
            assert word not in text, (tiers, word)


def test_a_window_that_runs_backwards_is_refused(card: Logbook) -> None:
    with pytest.raises(ValueError, match="runs backwards"):
        money.money_in(card, "2026-10-06", "2026-10-05")


def test_a_payment_is_on_the_day_the_window_cut_it_by(card: Logbook) -> None:
    """The window is cut on the local day of each line's instant (the index's), and each payment
    reports that day: a `date` that disagrees with the instant (RFC 0021 rule 5 says it never does)
    moves nothing between windows."""
    odd = wire("2026-10-06T20:00:00Z", "Bakeri Solvind", -12.0, "card-odd")
    odd["payload"]["date"] = "2026-10-07"
    card.append_many([odd])
    found = money.money_in(card, "2026-10-06", "2026-10-06")
    assert [(p.day, p.amount) for p in found.payments] == [("2026-10-06", -58.0), ("2026-10-06", -12.0)]
    assert money.money_in(card, "2026-10-07", "2026-10-07").payments == []


def test_a_retracted_line_at_the_edge_does_not_stretch_what_the_sources_cover(card: Logbook) -> None:
    stray = wire("2026-12-20T10:00:00Z", "Bakeri Solvind", -1.0, "card-stray")
    early = wire("2026-08-01T10:00:00Z", "Bakeri Solvind", -1.0, "card-early")
    card.append_many([stray, early])
    for raw_id in ("card-stray", "card-early"):
        [line] = [x for x in card.lines() if x["payload"].get("raw_id") == raw_id]
        card.retract(int(line["seq"]), "a mis-dated import")
    found = money.money_in(card, "2026-10-15", "2026-10-15")
    assert not found.covered
    assert found.said == "No payment source covers this day — the last ends 2026-10-06"
    before = money.money_in(card, "2026-09-01", "2026-09-01")
    assert before.said == "No payment source covers this day — the first begins 2026-10-01"


def test_a_window_past_both_ends_names_both_gaps(card: Logbook) -> None:
    found = money.money_in(card, "2026-09-29", "2026-10-08")
    assert len(found.payments) == 5
    assert found.said == (
        "No payment source covers 2026-09-29 to 2026-09-30 — the first begins 2026-10-01;"
        " nor 2026-10-07 to 2026-10-08 — the last ends 2026-10-06"
    )
