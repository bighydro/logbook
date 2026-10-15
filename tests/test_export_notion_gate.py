"""The crossing gate of `logbook export notion`, probed where a fact could rest on a line the gate
refuses: a promise's attribution to a person, a promise outside the window the crossing line
declares, and the money filter on the owner's quoted words. The record is `test_export_notion`'s
synthetic one (Ines Nordmann of Oslo, who does not exist), with a few lines added per test."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from test_export_notion import (
    NOW,
    OLA,
    SIGRID,
    _all_bytes,
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
