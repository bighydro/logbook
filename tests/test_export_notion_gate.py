"""The crossing gate of `logbook export notion`, probed where a fact could rest on a line the gate
refuses: a promise's attribution to a person, a promise outside the window the crossing line
declares, the money filter on the owner's quoted words, and a birthday read off a resolution line.
The record is `test_export_notion`'s synthetic one (Ines Nordmann of Oslo, who does not exist), with
a few lines added per test."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from test_export_notion import (
    KARI,
    LIV,
    NOW,
    OLA,
    OWNER,
    SIGRID,
    _all_bytes,
    _birthday,
    _entry,
    _line,
    _mail,
    _message,
    _person,
    _read,
    _resolution,
    _run,
    build,
)

from logbook import cli
from logbook.contrib import notion_export
from logbook.core import policy, signing
from logbook.core.store import Logbook

OLA_OTHER_PHONE = "+447700900121"  # a second number of Ola's, bound to him by a tier-3 line only
OLA_OTHER_CHAT = f"{OLA_OTHER_PHONE[1:]}@s.whatsapp.net"
SIGNED_DAY = "2026-09-10"
BEFORE_WINDOW = "2026-08-20"
T3_THEIRS = "I'll bring the SENTINEL-T3-THEIRS drawings on Monday."
T3_MINE = "I will send you the SENTINEL-T3-MINE file tomorrow."
EARLY_PROMISE = "I'll send the SENTINEL-EARLY hull drawings by Friday."
MNOK_PROMISE = "I'll wire the 2 MNOK for the SENTINEL-MNOK stand on Monday."
BIRTHDAY = "1911-11-11"  # a sentinel: no other date of the record is this one
CARD_DAY = "2026-09-28"  # the day a contact card was read in: unsigned until a test signs it
OWNER_ID = "019cadd3-6bc0-7dcd-9133-000000000401"  # the entity the record binds Ines's own email to
HEMMELIG = {  # a person the record names by a tier-3 line only, and who writes on a signed day
    "id": "019cadd3-6bc0-7dcd-9133-000000000416",
    "name": "Per Hemmelig",
    "phone": "+447700900131",
}


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    record = build(tmp_path / "lb")
    monkeypatch.setenv("LOGBOOK_HOME", str(record.root))
    monkeypatch.setattr(notion_export, "now", lambda: NOW)
    monkeypatch.setattr(policy, "today", lambda: date(2026, 10, 15))
    _entry(record)
    return record


def _append(lb: Logbook, *drafts: dict[str, Any]) -> list[dict[str, Any]]:
    return [lb.append(**_line(d)) for d in drafts]


def _sign_again(lb: Logbook, day: str) -> None:
    """A standing signature over the day as it is now, the lines just added included."""
    signing.sign(lb, day, at="2026-10-02T08:00:00Z")


def _promises(out: Path, entity: str) -> list[str]:
    person = _person(out, entity)
    assert person is not None
    found = person["facts"]["promises"]
    return [p["sentence"] for side in ("owed_by_owner", "owed_to_owner") for p in found[side]]


# -- a promise's attribution rests on a line the gate refuses ----------------------------------------


def test_a_promise_attributed_through_a_tier_3_resolution_does_not_leave(lb: Logbook, tmp_path: Path):
    """Ola's second number is bound to him by a tier-3 resolution line only. A tier-2 message from it on
    a signed day carries a promise. The sentence may cross on its own line's account, but the fact
    "Ola promised this" rests on the tier-3 line, which names nobody under a ceiling of 2."""
    _append(
        lb,
        _resolution(("phone", OLA_OTHER_PHONE), OLA, tier=3),
        _message(SIGNED_DAY, T3_THEIRS, OLA_OTHER_CHAT, ("phone", OLA_OTHER_PHONE), clock="13:00"),
    )
    _sign_again(lb, SIGNED_DAY)
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01")
    assert T3_THEIRS not in _promises(out, OLA["id"]), "attributed to Ola through a tier-3 line"
    assert "SENTINEL-T3-THEIRS" not in _all_bytes(out)


def test_the_counterpart_of_the_owners_promise_is_not_named_through_a_tier_3_line(
    lb: Logbook, tmp_path: Path
):
    """The owner's own promise in a direct chat whose number a tier-3 line alone gives to Ola: under
    the gate that chat is with nobody the bundle may name, so the sentence is not Ola's to be owed."""
    _append(
        lb,
        _resolution(("phone", OLA_OTHER_PHONE), OLA, tier=3),
        _message(SIGNED_DAY, T3_MINE, OLA_OTHER_CHAT, clock="13:05"),
    )
    _sign_again(lb, SIGNED_DAY)
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01")
    assert T3_MINE not in _promises(out, OLA["id"]), "the counterpart was named through a tier-3 line"
    assert "SENTINEL-T3-MINE" not in _all_bytes(out)


def test_people_read_under_the_gate_agrees(lb: Logbook, tmp_path: Path):
    """The people reader, given the same gate, does not count the tier-3-bound number as Ola's: the
    promise path must not know more than the contact path does."""
    _append(
        lb,
        _resolution(("phone", OLA_OTHER_PHONE), OLA, tier=3),
        _message(SIGNED_DAY, T3_THEIRS, OLA_OTHER_CHAT, ("phone", OLA_OTHER_PHONE), clock="13:00"),
    )
    _sign_again(lb, SIGNED_DAY)
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01")
    ola = _person(out, OLA["id"])
    assert ola is not None
    assert {"kind": "phone", "value": OLA_OTHER_PHONE} not in ola["identities"]
    assert ola["facts"]["last_contact"]["date"] == "2026-09-12", "the contact path holds the line"


# -- a promise from outside the window the crossing line declares -----------------------------------


def test_a_promise_before_the_window_is_not_in_a_bundle_of_the_window(lb: Logbook, tmp_path: Path):
    """The crossing line says the lines with `from` <= `at` < `to` were considered (RFC 0011). A signed
    August mail from Ola with an open promise must not feed a bundle whose window opens in September."""
    mail = _mail(BEFORE_WINDOW, OLA, "Hull drawings, early")
    mail["payload"]["body"] = EARLY_PROMISE
    _append(lb, mail)
    _sign_again(lb, BEFORE_WINDOW)
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01")
    assert _read(out, "manifest.json")["window"] == {"since": "2026-09-01", "until": "2026-10-15"}
    assert "SENTINEL-EARLY" not in _all_bytes(out), "a promise from before the window"
    line = lb.line_by_seq(lb.meta["seq"])
    assert line is not None and line["payload"]["window"]["from"] == "2026-08-31T22:00:00Z"


# -- money in the owner's words ----------------------------------------------------------------------


def test_a_promise_naming_money_in_a_prefixed_unit_is_left_out(lb: Logbook, tmp_path: Path):
    """`2 MNOK` is money as the owner writes it; the filter catches `NOK 2` and `2 NOK` and must catch
    this too."""
    _append(lb, _message(SIGNED_DAY, MNOK_PROMISE, f"{OLA['phone'][1:]}@s.whatsapp.net", clock="13:10"))
    _sign_again(lb, SIGNED_DAY)
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01")
    assert "MNOK" not in _all_bytes(out) and "SENTINEL-MNOK" not in _all_bytes(out)


# -- a birthday read off a line the gate refuses -------------------------------------------------------


@pytest.mark.parametrize("ref", [("phone", OLA_OTHER_PHONE), ("email", OLA["email"])])
def test_a_birthday_on_a_tier_3_resolution_line_does_not_leave(
    lb: Logbook, tmp_path: Path, ref: tuple[str, str]
):
    """A tier-3 resolution line on a signed day gives Ola a birthday, through a second number of his or
    by binding his email again. Under a ceiling of 2 the line binds nothing and tells nothing: Ola
    leaves, by the tier-2 lines that bind him, and his birthday stays home."""
    _append(lb, _birthday(ref, OLA, BIRTHDAY, SIGNED_DAY, tier=3))
    _sign_again(lb, SIGNED_DAY)
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01")
    ola = _person(out, OLA["id"])
    assert ola is not None and {"kind": "email", "value": OLA["email"]} in ola["identities"]
    assert ola["facts"]["birthday"] is None, "a birthday read off a tier-3 line"
    assert BIRTHDAY not in _all_bytes(out)


def test_a_birthday_read_on_an_unsigned_day_leaves_only_once_the_gate_lets_it(lb: Logbook, tmp_path: Path):
    """The line that binds Ola's email binds it from any day, as the overlay does; the birthday it
    carries is a fact and binds nothing, so it leaves only from a signed day, or with the gate lifted
    by the entry and the flag both. Held back, it is counted as a line on an unsigned day."""
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01")
    held = _read(out, "manifest.json")["held_back"]["unsigned"]
    _append(lb, _birthday(("email", OLA["email"]), OLA, BIRTHDAY, CARD_DAY))
    _run(out, "--since", "2026-09-01")
    ola = _person(out, OLA["id"])
    assert ola is not None and {"kind": "email", "value": OLA["email"]} in ola["identities"], "it binds"
    assert ola["facts"]["birthday"] is None, "a birthday read on an unsigned day"
    assert BIRTHDAY not in _all_bytes(out)
    assert _read(out, "manifest.json")["held_back"]["unsigned"] == held + 1

    _entry(lb, include_unsigned=True)
    _run(out, "--since", "2026-09-01", "--include-unsigned")
    ola = _person(out, OLA["id"])
    assert ola is not None and ola["facts"]["birthday"] == BIRTHDAY, "the gate lifted"

    _entry(lb)
    _sign_again(lb, CARD_DAY)
    _run(out, "--since", "2026-09-01")
    ola = _person(out, OLA["id"])
    assert ola is not None and ola["facts"]["birthday"] == BIRTHDAY, "the day signed"


def _birthday_of(out: Path, entity: str) -> object:
    person = _person(out, entity)
    assert person is not None
    return person["facts"]["birthday"]


def test_a_retracted_birthday_line_tells_nothing(lb: Logbook, tmp_path: Path):
    """A birthday on a signed day, its line retracted: Ola leaves without it."""
    (card,) = _append(lb, _birthday(("email", OLA["email"]), OLA, BIRTHDAY, SIGNED_DAY))
    lb.retract(int(card["seq"]), "the wrong card", at="2026-10-01T09:00:00Z")
    _sign_again(lb, SIGNED_DAY)
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01")
    assert _birthday_of(out, OLA["id"]) is None
    assert BIRTHDAY not in _all_bytes(out)


def test_a_birthday_read_after_the_read_time_stays_home(lb: Logbook, tmp_path: Path):
    """A line stamped after the read time is no fact of this run, the gate lifted or not."""
    late = _birthday(("email", OLA["email"]), OLA, BIRTHDAY, "2026-10-15")
    late["at"] = "2026-10-15T09:00:00Z"  # an hour after NOW
    _append(lb, late)
    _entry(lb, include_unsigned=True)
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01", "--include-unsigned")
    assert _birthday_of(out, OLA["id"]) is None
    assert BIRTHDAY not in _all_bytes(out)


def test_include_unsigned_alone_does_not_lift_the_gate_for_a_birthday(lb: Logbook, tmp_path: Path):
    """The flag without the entry's `include_unsigned` is refused before anything is read, so a
    birthday read on an unsigned day cannot leave by it."""
    _append(lb, _birthday(("email", OLA["email"]), OLA, BIRTHDAY, CARD_DAY))
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as e:
        _run(out, "--since", "2026-09-01", "--include-unsigned")
    assert e.value.code == 2
    assert not out.exists()


def test_a_tier_2_birthday_stays_home_under_a_ceiling_of_1(lb: Logbook, tmp_path: Path):
    """A birthday line is a resolution line, tier 2 as a contacts import writes it: under an entry of
    `max_tier` 1 nothing of it leaves, signed day or not."""
    _append(lb, _birthday(("email", OLA["email"]), OLA, BIRTHDAY, SIGNED_DAY))
    _sign_again(lb, SIGNED_DAY)
    _entry(lb, max_tier=1)
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01")
    assert BIRTHDAY not in _all_bytes(out)
    _entry(lb)
    _run(out, "--since", "2026-09-01")
    assert _birthday_of(out, OLA["id"]) == BIRTHDAY, "the same line, under the owner's ceiling of 2"


def test_the_owners_own_birthday_never_leaves(lb: Logbook, tmp_path: Path):
    """The owner is never a person: a birthday on the line that binds Ines's own email, tier 2 and on a
    signed day, is nowhere in the folder."""
    owner = {"id": OWNER_ID, "name": OWNER["name"]}
    _append(lb, _birthday(("email", OWNER["email"]), owner, BIRTHDAY, SIGNED_DAY))
    _sign_again(lb, SIGNED_DAY)
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01")
    assert _person(out, OWNER_ID) is None
    assert BIRTHDAY not in _all_bytes(out)


def test_no_birthday_of_a_person_the_folder_does_not_list(lb: Logbook, tmp_path: Path):
    """Kari is heard only before the window; Liv has no email, phone or handle; Per Hemmelig is named by
    a tier-3 line only, and writes on a signed day. Each has a birthday on a signed day; none of them is
    listed, and none of their birthdays is in the folder."""
    kari, liv, hemmelig = "1911-01-01", "1911-02-02", "1911-03-03"
    _append(
        lb,
        _birthday(("email", KARI["email"]), KARI, kari, SIGNED_DAY),
        _birthday(("provider_id", LIV["provider_id"]), LIV, liv, SIGNED_DAY),
        _birthday(("phone", HEMMELIG["phone"]), HEMMELIG, hemmelig, SIGNED_DAY, tier=3),
        _message(SIGNED_DAY, "Hei", f"{HEMMELIG['phone'][1:]}@s.whatsapp.net", ("phone", HEMMELIG["phone"]),
                 clock="13:30"),
    )  # fmt: skip
    _sign_again(lb, SIGNED_DAY)
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01")
    listed = {p["id"] for p in _read(out, "persons.json")["persons"]}
    assert not listed & {KARI["id"], LIV["id"], HEMMELIG["id"]}
    raw = _all_bytes(out)
    for birthday in (kari, liv, hemmelig):
        assert birthday not in raw
    assert "Hemmelig" not in raw


def test_a_tier_3_birthday_held_back_is_counted_above_the_tier(lb: Logbook, tmp_path: Path):
    """A birthday held back for its tier is a line held back like any other: the manifest's
    `held_back.above_tier` counts it once, run after run."""
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01")
    held = _read(out, "manifest.json")["held_back"]
    _append(lb, _birthday(("email", OLA["email"]), OLA, BIRTHDAY, SIGNED_DAY, tier=3))
    _sign_again(lb, SIGNED_DAY)
    _run(out, "--since", "2026-09-01")
    again = _read(out, "manifest.json")["held_back"]
    assert again == {"above_tier": held["above_tier"] + 1, "unsigned": held["unsigned"]}
    assert _birthday_of(out, OLA["id"]) is None


def test_every_birthday_line_held_back_is_counted_whatever_their_order(lb: Logbook, tmp_path: Path):
    """Ola's birthday on two cards, his email's on a signed day and his phone's on an unsigned one. The
    birthday leaves on the signed line, and the unsigned line is counted as held back all the same: a
    count never depends on which line the reader happened to try first."""
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01")
    held = _read(out, "manifest.json")["held_back"]
    _append(
        lb,
        _birthday(("email", OLA["email"]), OLA, BIRTHDAY, SIGNED_DAY),
        _birthday(("phone", OLA["phone"]), OLA, BIRTHDAY, CARD_DAY),
    )
    _sign_again(lb, SIGNED_DAY)
    _run(out, "--since", "2026-09-01")
    assert _birthday_of(out, OLA["id"]) == BIRTHDAY
    assert _read(out, "manifest.json")["held_back"]["unsigned"] == held["unsigned"] + 1


def test_a_held_back_birthday_is_never_beside_a_name(lb: Logbook, tmp_path: Path, capsys):
    """Held back, a birthday is a number in the totals and nothing else: the manifest's `held_back` has
    no key but the two totals, Ola's facts have the same keys as when no card of his carries a birthday,
    and neither the dry run nor the real run prints a person's name, id or address."""
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01")
    plain = _person(out, OLA["id"])
    assert plain is not None
    _append(
        lb,
        _birthday(("email", OLA["email"]), OLA, BIRTHDAY, CARD_DAY),
        _birthday(("phone", OLA["phone"]), OLA, BIRTHDAY, SIGNED_DAY, tier=3),
    )
    _sign_again(lb, SIGNED_DAY)
    capsys.readouterr()
    _run(out, "--since", "2026-09-01", "--dry-run")
    _run(out, "--since", "2026-09-01")
    printed = capsys.readouterr()
    for said in (printed.out, printed.err):
        for name in (OLA["name"], "Ola", OLA["id"], OLA["email"], OLA["phone"], BIRTHDAY):
            assert name not in said
    manifest = _read(out, "manifest.json")
    assert set(manifest["held_back"]) == {"above_tier", "unsigned"}
    assert BIRTHDAY not in _all_bytes(out)
    held = _person(out, OLA["id"])
    assert held is not None
    assert set(held) == set(plain) and set(held["facts"]) == set(plain["facts"])
    assert held["facts"] == plain["facts"], "nothing of his facts says a birthday was held back"


OTHER_BIRTHDAY = "1922-02-02"  # a second sentinel, on another card of Ola's


@pytest.mark.parametrize("unsigned_ref", ["email", "phone"])
def test_a_birthday_leaves_on_its_signed_card_whichever_ref_was_bound_first(
    lb: Logbook, tmp_path: Path, unsigned_ref: str
):
    """Two cards of Ola's carry two birthdays, one on a signed day and one on an unsigned day. The
    signed one leaves and the unsigned one is counted as held back, whichever of his refs the record
    bound first: neither the fact nor the count depends on the order of his refs."""
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01")
    held = _read(out, "manifest.json")["held_back"]["unsigned"]
    signed_ref = "phone" if unsigned_ref == "email" else "email"
    _append(
        lb,
        _birthday((unsigned_ref, OLA[unsigned_ref]), OLA, BIRTHDAY, CARD_DAY),
        _birthday((signed_ref, OLA[signed_ref]), OLA, OTHER_BIRTHDAY, SIGNED_DAY),
    )
    _sign_again(lb, SIGNED_DAY)
    _run(out, "--since", "2026-09-01")
    assert _birthday_of(out, OLA["id"]) == OTHER_BIRTHDAY
    assert BIRTHDAY not in _all_bytes(out)
    assert _read(out, "manifest.json")["held_back"]["unsigned"] == held + 1


def test_a_malformed_card_does_not_hide_a_good_one(lb: Logbook, tmp_path: Path):
    """Ola's email's card carries a birthday with a trailing newline, his phone's a whole one, both on a
    signed day: the whole one leaves and nothing of the other."""
    _append(
        lb,
        _birthday(("email", OLA["email"]), OLA, BIRTHDAY + "\n", SIGNED_DAY),
        _birthday(("phone", OLA["phone"]), OLA, OTHER_BIRTHDAY, SIGNED_DAY),
    )
    _sign_again(lb, SIGNED_DAY)
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01")
    assert _birthday_of(out, OLA["id"]) == OTHER_BIRTHDAY
    assert BIRTHDAY not in _all_bytes(out)


def test_two_birthdays_that_both_pass_give_none(lb: Logbook, tmp_path: Path):
    """Two cards of Ola's, both on a signed day, disagree: the record does not know his birthday, and
    neither leaves."""
    _append(
        lb,
        _birthday(("email", OLA["email"]), OLA, BIRTHDAY, SIGNED_DAY),
        _birthday(("phone", OLA["phone"]), OLA, OTHER_BIRTHDAY, SIGNED_DAY),
    )
    _sign_again(lb, SIGNED_DAY)
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01")
    assert _birthday_of(out, OLA["id"]) is None
    raw = _all_bytes(out)
    assert BIRTHDAY not in raw and OTHER_BIRTHDAY not in raw


def test_the_dry_run_counts_the_birthdays_and_writes_nothing(lb: Logbook, tmp_path: Path, capsys):
    """`--dry-run` says how many birthdays would leave, as a total beside the persons, and writes
    nothing: no folder, no line. The real run's manifest counts the same."""
    _append(lb, _birthday(("email", OLA["email"]), OLA, BIRTHDAY, SIGNED_DAY))
    _sign_again(lb, SIGNED_DAY)
    seq = lb.meta["seq"]
    out = tmp_path / "out"
    capsys.readouterr()
    cli.main(["export", "notion", str(out), "--since", "2026-09-01", "--dry-run"])
    text = capsys.readouterr().out
    assert "persons: 1 (1 birthday)" in text
    assert not out.exists() and lb.meta["seq"] == seq
    _run(out, "--since", "2026-09-01")
    assert _read(out, "manifest.json")["counts"]["birthdays"] == 1


# -- the record itself is never the target ----------------------------------------------------------


@pytest.mark.parametrize("inside", [(), ("logbook",), ("policy",), ("export", "..", "logbook")])
def test_the_record_is_never_replaced(lb: Logbook, inside: tuple[str, ...], capsys):
    """`--force` or not: the record, its log and its policy are no target, nor a path that walks
    back into them from `export/`; nothing is written and no line appended."""
    out = lb.root.joinpath(*inside)
    seq = lb.meta["seq"]
    with pytest.raises(SystemExit) as e:
        _run(out, "--since", "2026-09-01", "--force")
    assert e.value.code == 2
    assert lb.meta["seq"] == seq
    assert (lb.root / "policy" / "crossing.json").exists()
    assert json.loads((lb.root / "policy" / "crossing.json").read_text(encoding="utf-8"))["notion"]
    capsys.readouterr()


def test_sigrid_stays_out_whatever_the_promise(lb: Logbook, tmp_path: Path):
    """A control: a person bound by a tier-3 line only is not in the bundle, and neither is a promise
    of hers, since she is not among the people heard."""
    _append(
        lb,
        _message(SIGNED_DAY, "I'll bring the SENTINEL-SIGRID cake.", f"{SIGRID['phone'][1:]}@s.whatsapp.net",
                 ("phone", SIGRID["phone"]), clock="13:20"),
    )  # fmt: skip
    _sign_again(lb, SIGNED_DAY)
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01")
    assert _person(out, SIGRID["id"]) is None
    assert "SENTINEL-SIGRID" not in _all_bytes(out)
