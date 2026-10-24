"""What `logbook export notion` writes into a person's page and facts (docs/export-notion.md): the days
together over the person's whole history in the record, whatever the window; only the open promises
said in the 365 days before the read time, in a conversation the person is a direct party to, at most
ten a side; and no talk of money, with a figure or without. The record is `test_export_notion`'s
synthetic one (Ines Nordmann of Oslo, who does not exist), with a few lines added per test."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from persona import OFFICE, attendee, dwell, event
from test_export_notion import (
    DRAWINGS,
    KARI,
    NOW,
    OLA,
    OWNER,
    _all_bytes,
    _at,
    _entry,
    _mail,
    _message,
    _person,
    _read,
    _run,
    build,
)

from logbook.contrib import notion_export
from logbook.core import attachments, policy, signing
from logbook.core.store import Logbook

OLA_CHAT = f"{OLA['phone'][1:]}@s.whatsapp.net"
GROUP_CHAT = "120363000000000001@g.us"
DASH = notion_export.EN_DASH  # a bullet on a person's page
LONG_AGO = "2019-06-14"  # a day together seven years back
LAST_WEEK = "2026-10-08"  # the window of the last week, to the read time on 15 October


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    record = build(tmp_path / "lb")
    monkeypatch.setenv("LOGBOOK_HOME", str(record.root))
    monkeypatch.setattr(notion_export, "now", lambda: NOW)
    monkeypatch.setattr(policy, "today", lambda: date(2026, 10, 15))
    _entry(record)
    return record


def _add(lb: Logbook, *drafts: dict[str, Any]) -> None:
    lb.append_many(list(drafts))  # whole, as the fixture's are: an event keeps its end
    for day in sorted({_day(draft) for draft in drafts}):
        signing.sign(lb, day, at="2026-10-14T08:00:00Z")


def _day(draft: dict[str, Any]) -> str:
    return str(draft["at"])[:10]  # every line here is written in the middle of an Oslo day


def _page(out: Path, entity: str) -> list[str]:
    person = _person(out, entity)
    assert person is not None
    return list(person["page"])


def _said(out: Path, entity: str, side: str) -> list[str]:
    person = _person(out, entity)
    assert person is not None
    return [p["sentence"] for p in person["facts"]["promises"][side]]


def _theirs(day: str, text: str, clock: str = "12:00", chat: str = OLA_CHAT, kind: str = "direct") -> dict:
    found = _message(day, text, chat, ("phone", OLA["phone"]), clock=clock)
    found["payload"]["chat"] = {"id": chat, "type": kind}
    return found


def _mail_with(day: str, body: str, clock: str, **extra: Any) -> dict[str, Any]:
    found = _mail(day, {"name": OLA["name"], "email": OLA["email"]}, "Survey", clock=clock)
    found["payload"]["body"] = body
    if extra:
        found["payload"]["extra"] = extra
    return found


def _call(lb: Logbook, day: str, clock: str, text: str, participants: list[dict[str, str]]) -> dict:
    blob = text.encode("utf-8")
    lb.attach(blob)
    return {
        "at": _at(day, clock), "end": _at(day, "23:00"), "source": "granola", "kind": "transcript", "tier": 2,
        "payload": {"schema": "transcript/v1", "provider": "granola", "raw_id": f"t-{day}-{clock}",
                    "title": "Call", "participants": participants,
                    "content": attachments.reference(blob, "text/markdown")},
    }  # fmt: skip


# -- days together: the whole history ---------------------------------------------------------------------


def test_days_together_are_counted_over_the_whole_record_not_the_window(lb: Logbook, tmp_path: Path):
    """Ola was with Ines at the office in June 2019 and in September 2026; the export's window is the
    last week, in which he wrote once. His page counts both days and names the first and the last."""
    _add(
        lb,
        *dwell(LONG_AGO, "09:00", "12:00", OFFICE),
        event(_at(LONG_AGO, "10:00"), _at(LONG_AGO, "11:30"), "Mast", [attendee(OLA["email"], OLA["name"])]),
        _theirs("2026-10-12", "Hei!"),
    )
    out = tmp_path / "out"
    _run(out, "--since", LAST_WEEK)
    ola = _person(out, OLA["id"])
    assert ola is not None
    facts = ola["facts"]
    assert facts["days_together"] == 2, "2019 and 2026, both before the window"
    assert facts["first_together"] == LONG_AGO and facts["last_together"] == "2026-09-10"
    assert "Tage zusammen: 2 (zuerst 14.06.2019, zuletzt 10.09.2026)" in ola["page"]
    assert not any("seit" in line for line in ola["page"] if line.startswith("Tage zusammen"))
    assert facts["last_contact"] == {"date": "2026-10-12", "kind": "message"}, "the window's, as before"


def test_a_person_with_no_day_together_has_no_line_and_zero_in_the_facts(lb: Logbook, tmp_path: Path):
    _add(lb, _mail("2026-10-12", KARI, "Sommerfest"))
    out = tmp_path / "out"
    _run(out, "--since", LAST_WEEK)
    kari = _person(out, KARI["id"])
    assert kari is not None
    assert kari["facts"]["days_together"] == 0
    assert kari["facts"]["first_together"] is None and kari["facts"]["last_together"] is None
    assert not any(line.startswith("Tage zusammen") for line in kari["page"])


def test_a_day_together_on_an_unsigned_day_does_not_count(lb: Logbook, tmp_path: Path):
    """The whole history is read through the same gate: a day together nobody signed is not one."""
    lb.append_many(
        [
            *dwell(LONG_AGO, "09:00", "12:00", OFFICE),
            event(
                _at(LONG_AGO, "10:00"), _at(LONG_AGO, "11:30"), "Mast", [attendee(OLA["email"], OLA["name"])]
            ),
        ]
    )  # not signed
    _add(lb, _theirs("2026-10-12", "Hei!"))
    out = tmp_path / "out"
    _run(out, "--since", LAST_WEEK)
    ola = _person(out, OLA["id"])
    assert ola is not None
    assert ola["facts"]["days_together"] == 1 and ola["facts"]["first_together"] == "2026-09-10"
    _entry(lb, include_unsigned=True)
    _run(out, "--since", LAST_WEEK, "--include-unsigned")
    ola = _person(out, OLA["id"])
    assert ola is not None
    assert ola["facts"]["days_together"] == 2 and ola["facts"]["first_together"] == LONG_AGO, (
        "the gate lifted"
    )


# -- promises: recent, open, direct ---------------------------------------------------------------------


def test_only_recent_promises_from_a_conversation_the_person_is_party_to(lb: Logbook, tmp_path: Path):
    """The window is the whole record, so only the new rules leave a sentence out: older than 365 days
    before the read time, said in a group chat, quoted in a mail, sent through a mailing list, or said
    in a call the person did not speak in."""
    me = {"name": OWNER["name"], "email": OWNER["email"]}
    ola = {"name": OLA["name"], "email": OLA["email"]}
    kari = {"name": KARI["name"], "email": KARI["email"]}
    _add(
        lb,
        _theirs("2025-10-01", "I'll send you the SENTINEL-OLD sketches by Friday."),
        _theirs("2025-10-20", "I'll send you the SENTINEL-RECENT sketches by Friday."),
        _theirs("2026-10-12", "I'll bring the SENTINEL-GROUP rope on Monday.", chat=GROUP_CHAT, kind="group"),
        _mail_with(
            "2026-10-12",
            "Takk!\n\nAm 11.10.2026 schrieb Ines Nordmann <ines@example.org>:\n"
            "> I will send you the SENTINEL-QUOTED survey tomorrow.\n",
            "09:10",
        ),
        _mail_with("2026-10-12", "> I'll bring the SENTINEL-QUOTED-LINE charts.\nGood.", "09:20"),
        _mail_with("2026-10-12", "I'll send you the SENTINEL-MAIL survey on Monday.", "09:30"),
        _mail_with(
            "2026-10-12",
            "I'll send the SENTINEL-LIST minutes tomorrow.",
            "09:40",
            list={"id": "verft.example.org"},
        ),
        _call(
            lb,
            "2026-10-13",
            "10:00",
            "me: I'll send you the SENTINEL-SPOKE plans tomorrow.\nOla Nordmann: Great, thanks.\n",
            [ola, me],
        ),
        _call(
            lb,
            "2026-10-13",
            "14:00",
            "me: I'll bring the SENTINEL-SILENT charts on Monday.\nKari Nordmann: Fine.\n",
            [ola, kari, me],
        ),
    )
    out = tmp_path / "out"
    _run(out)
    owed_to = _said(out, OLA["id"], "owed_to_owner")
    owed_by = _said(out, OLA["id"], "owed_by_owner")
    assert "I'll send you the SENTINEL-RECENT sketches by Friday." in owed_to, "within 365 days"
    assert "I'll send you the SENTINEL-MAIL survey on Monday." in owed_to, "a mail both are on"
    assert "I'll send you the SENTINEL-SPOKE plans tomorrow." in owed_by, "a call he spoke in"
    whole = _all_bytes(out)
    for left_out in ("SENTINEL-OLD", "SENTINEL-GROUP", "SENTINEL-QUOTED", "SENTINEL-LIST", "SENTINEL-SILENT"):
        assert left_out not in whole, left_out


def test_a_promise_outside_the_window_still_stays_out(lb: Logbook, tmp_path: Path):
    """The 365 days narrow the window, never widen it: the crossing line declares the window."""
    _add(lb, _theirs("2026-09-30", "I'll send you the SENTINEL-BEFORE sketches by Friday."))
    out = tmp_path / "out"
    _run(out, "--since", "2026-10-01")
    assert "SENTINEL-BEFORE" not in _all_bytes(out)


def test_at_most_ten_promises_a_side_newest_first_and_the_rest_counted(lb: Logbook, tmp_path: Path):
    said = [f"I'll send you drawing number {n} tomorrow." for n in range(1, 12)]
    _add(lb, *(_theirs(f"2026-10-{n:02d}", sentence) for n, sentence in enumerate(said, start=1)))
    out = tmp_path / "out"
    _run(out, "--since", "2026-10-01")
    ola = _person(out, OLA["id"])
    assert ola is not None
    facts = ola["facts"]
    listed = [p["sentence"] for p in facts["promises"]["owed_to_owner"]]
    assert listed == said[::-1][:10], "the ten newest, newest first; the first one is the rest"
    assert [p["date"] for p in facts["promises"]["owed_to_owner"]][:2] == ["2026-10-11", "2026-10-10"]
    assert facts["promises_more"] == {"owed_by_owner": 0, "owed_to_owner": 1}
    page = ola["page"]
    start = page.index("Offene Versprechen an mich:")
    assert page[start + 1 : start + 12] == [
        *(
            f"{DASH} {notion_export.quoted(s)} ({n:02d}.10.2026)"
            for n, s in reversed(list(enumerate(said, 1))[1:])
        ),
        "und 1 weitere",
    ]
    assert page.count("und 1 weitere") == 1 and "Offene Versprechen von mir: keine" in page
    assert not any(line.startswith("und ") and "weitere" in line for line in page[:start])


def test_ten_promises_need_no_line_for_the_rest(lb: Logbook, tmp_path: Path):
    _add(
        lb,
        *(_theirs(f"2026-10-{n:02d}", f"I'll send you drawing number {n} tomorrow.") for n in range(1, 11)),
    )
    out = tmp_path / "out"
    _run(out, "--since", "2026-10-01")
    ola = _person(out, OLA["id"])
    assert ola is not None and len(ola["facts"]["promises"]["owed_to_owner"]) == 10
    assert ola["facts"]["promises_more"] == {"owed_by_owner": 0, "owed_to_owner": 0}
    assert not any("weitere" in line for line in ola["page"])


# -- money: with a figure or without -------------------------------------------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        "Ich überweise dir das morgen",
        "send me the invoice",
        "Die Zahlung kommt am Montag.",
        "Ich muss noch zahlen.",
        "Ich bezahle das morgen.",
        "Schick mir die Rechnung.",
        "Kannst du mir die Überweisung bestätigen?",
        "Ich frage nach dem Preis.",
        "I'll make the payment on Monday.",
        "I'll pay you back tomorrow.",
        "Can you transfer it tomorrow?",
        "I'll wire it on Friday.",
        "Send me the price list.",
    ],
)
def test_talk_of_money_without_a_figure_is_caught(sentence: str):
    assert notion_export.talks_money(sentence), sentence


@pytest.mark.parametrize(
    "sentence",
    [
        DRAWINGS,
        "I will call the yard tomorrow.",
        "Kannst du mir die Liste schicken?",
        "Ich schicke dir die Fotos.",
    ],
)
def test_a_promise_without_money_is_kept(sentence: str):
    assert not notion_export.talks_money(sentence), sentence


def test_a_promise_that_talks_of_money_is_left_out_and_counted(lb: Logbook, tmp_path: Path):
    _add(
        lb,
        _theirs("2026-10-12", "Send me the invoice.", clock="12:00"),
        _theirs("2026-10-12", "Kannst du mir die Rechnung schicken?", clock="12:10"),
        _message("2026-10-12", "Ich überweise dir das morgen, versprochen.", OLA_CHAT, clock="12:20"),
        _theirs("2026-10-12", "I'll send you the SENTINEL-KEPT drawings tomorrow.", clock="12:30"),
    )
    out = tmp_path / "out"
    _run(out, "--since", "2026-10-01")
    whole = _all_bytes(out)
    for text in ("invoice", "Rechnung", "überweise"):
        assert text not in whole, text
    assert "SENTINEL-KEPT" in whole, "a promise that does not talk of money still leaves"
    assert _read(out, "manifest.json")["left_out"]["sentences_with_money"] == 3
    assert json.loads((out / "persons.json").read_bytes())["persons"]
