"""The two sections of a person's page in `logbook export notion` that a dry run read by the receiving
side found wrong: "Tage zusammen" (one start date on every page, a count of 0 on most) and the
promises (every open sentence since the record began, requests and other people's mail among them).

The days together give the first and last day the person appears in the record and the number of
distinct days together, and are left out of a page with none. A promise on a page is one the
promises reader classifies as the owner's or the person's own, from a message, a mail the owner
wrote, a call or a note; open, or kept in the last 365 days; never a quoted line or a whole chat;
dated; at most `PROMISES_SHOWN` a side, then "und N weitere".

The record is `test_export_notion`'s synthetic one: Ines Nordmann of Oslo, who does not exist, with
Ola, Kari and Per Nordmann, and a few lines added per test."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from persona import HOME, OFFICE, attendee, dwell, event, travel
from test_export_notion import (
    KARI,
    NOW,
    OLA,
    OWNER,
    PER,
    _at,
    _entry,
    _line,
    _mail,
    _message,
    build,
)

from logbook.contrib import notion_export
from logbook.contrib import promises as promise_reader
from logbook.core import policy, signing
from logbook.core.store import Logbook

OLA_CHAT = f"{OLA['phone'][1:]}@s.whatsapp.net"
DASH = notion_export.EN_DASH  # a promise's bullet
PROMISE_LINE = re.compile(
    rf"^{DASH} „.+“ \((\d\d\.\d\d\.\d{{4}}), (offen|gehalten am \d\d\.\d\d\.\d{{4}})\)$"
)


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    record = build(tmp_path / "lb")
    monkeypatch.setenv("LOGBOOK_HOME", str(record.root))
    monkeypatch.setattr(notion_export, "now", lambda: NOW)
    monkeypatch.setattr(policy, "today", lambda: date(2026, 10, 15))
    _entry(record, include_unsigned=True)
    return record


def _append(lb: Logbook, *drafts: dict[str, Any]) -> list[dict[str, Any]]:
    return [lb.append(**_line(d), end=d.get("end")) for d in drafts]


def _built(lb: Logbook, since: str | None = None, unsigned: bool = True) -> notion_export.Built:
    return notion_export.build(lb, notion_export.request(lb, since, include_unsigned=unsigned))


def _page(built: notion_export.Built, who: dict[str, str]) -> list[str]:
    found = next((p for p in built.persons if p["id"] == who["id"]), None)
    assert found is not None, who["name"]
    return list(found["page"])


def _facts(built: notion_export.Built, who: dict[str, str]) -> dict[str, Any]:
    return next(p["facts"] for p in built.persons if p["id"] == who["id"])


def _together(page: list[str]) -> list[str]:
    return [line for line in page if line.startswith("Tage zusammen")]


def _met(who: dict[str, str], day: str, clock: str = "10:00") -> list[dict[str, Any]]:
    """A meeting at the office: the owner's day there, from home and back, and an event `who`
    attended, a day together."""
    hour = int(clock[:2])
    return [
        *dwell(day, "07:30", "08:00", HOME),
        *travel(day, "08:00", "08:10", HOME, OFFICE, steps=3),
        *dwell(day, "08:10", "17:50", OFFICE),
        *travel(day, "17:50", "18:00", OFFICE, HOME, steps=3),
        *dwell(day, "18:00", "18:30", HOME),
        event(_at(day, clock), _at(day, f"{hour + 1:02d}:30"), f"Hull review {day} {clock}",
              [attendee(who["email"], who["name"])]),
    ]  # fmt: skip


def _sent_mail(day: str, to: dict[str, str], body: str) -> dict[str, Any]:
    mail = _mail(day, OWNER, f"To {to['name']}", clock="11:00")
    mail["payload"]["to"] = [{"email": to["email"], "name": to["name"]}]
    mail["payload"]["direction"] = "sent"
    mail["payload"]["body"] = body
    return mail


def _done(lb: Logbook, quote: str, day: str, status: str = "done") -> None:
    """The task line `promises done` writes for the proposal quoting `quote`, on `day`."""
    report = promise_reader.extract(lb)
    found = next(p for p in report.proposals if p.match.quote == quote)
    at = _at(day, "18:00")
    payload = promise_reader.draft_done(found, at, report.extractor)
    payload["status"] = status
    lb.append(at=at, source="manual", kind="task", tier=promise_reader.TASK_TIER, payload=payload)


# -- the days together --------------------------------------------------------------------------------


def test_the_days_together_start_on_the_persons_first_day_not_the_records(lb: Logbook):
    """The section said "Tage zusammen seit <the window's first day>" on every page: the record's first
    day, the same for all. It names the first and last day this person appears in the record."""
    built = _built(lb)
    assert built.persons and lb.meta["seq"]
    assert _together(_page(built, OLA)) == ["Tage zusammen: 1 (im Logbuch vom 02.09.2026 bis 25.09.2026)"]
    facts = _facts(built, OLA)
    assert facts["days_together"] == 1
    assert facts["appears"] == {"first": "2026-09-02", "last": "2026-09-25"}
    assert "01.08.2026" not in "\n".join(_page(built, OLA)), "the record's first day is nobody's"


def test_two_people_have_two_starts(lb: Logbook):
    _append(lb, *_met(KARI, "2026-08-25"))
    built = _built(lb)
    assert _together(_page(built, KARI)) == ["Tage zusammen: 1 (im Logbuch vom 20.08.2026 bis 25.08.2026)"]
    assert _together(_page(built, OLA)) == ["Tage zusammen: 1 (im Logbuch vom 02.09.2026 bis 25.09.2026)"]


def test_the_count_is_of_distinct_days(lb: Logbook):
    _append(lb, *_met(OLA, "2026-09-10", "14:00"), *_met(OLA, "2026-09-14"))
    built = _built(lb)
    assert _facts(built, OLA)["days_together"] == 2, "two meetings on the 10th are one day"
    assert _together(_page(built, OLA)) == ["Tage zusammen: 2 (im Logbuch vom 02.09.2026 bis 25.09.2026)"]


def test_a_page_without_a_day_together_has_no_such_section(lb: Logbook):
    """Per and Kari only wrote: no "Tage zusammen: 0" on their pages, no section at all."""
    built = _built(lb)
    for who in (PER, KARI):
        page = _page(built, who)
        assert _together(page) == [], who["name"]
        assert _facts(built, who)["days_together"] == 0
        assert not any("zusammen" in line for line in page)


def test_the_days_together_rest_on_the_gate(lb: Logbook):
    """Signed days only: Ola's last appearance is the 12th, not the unsigned 25th."""
    built = _built(lb, unsigned=False)
    assert _together(_page(built, OLA)) == ["Tage zusammen: 1 (im Logbuch vom 02.09.2026 bis 12.09.2026)"]


# -- the promises -------------------------------------------------------------------------------------

OLD_OPEN = "I'll send you the SENTINEL-OLD-OPEN survey next week."
KEPT_RECENT = "I'll bring the SENTINEL-KEPT-RECENT fenders on Saturday."
KEPT_OLD = "I'll return the SENTINEL-KEPT-OLD charts tomorrow."
CANCELLED = "I'll book the SENTINEL-CANCELLED crane for Monday."
REQUEST = "Can you send me the SENTINEL-REQUEST hull numbers?"
THEIR_MAIL = "I will send the SENTINEL-THEIR-MAIL survey on Monday."
MY_MAIL = "I will send the SENTINEL-MY-MAIL drawings on Monday."
QUOTED = "> I will call the SENTINEL-QUOTED yard tomorrow.\nGreat, thanks"
WHOLE_CHAT = (
    "ok so I'll look at the SENTINEL-CHAT hull on monday and then we see what the yard says and if they"
    " agree we go ahead and book the crane and the slip and the paint and everything else that goes with it"
    " and then we talk again about the rest of the season and the mooring and the winter storage too"
)
PASTED = "[12.09.26, 15:10] Ola Nordmann: I'll bring the SENTINEL-PASTED fenders"


def _promises_record(lb: Logbook) -> None:
    received = _mail("2026-09-03", OLA, "Survey", clock="12:00")
    received["payload"]["body"] = THEIR_MAIL
    _append(
        lb,
        _message("2024-11-04", OLD_OPEN, OLA_CHAT),
        _message("2025-03-01", KEPT_OLD, OLA_CHAT),
        _message("2026-09-12", KEPT_RECENT, OLA_CHAT, clock="16:00"),
        _message("2026-09-12", CANCELLED, OLA_CHAT, clock="16:05"),
        _message("2026-09-12", REQUEST, OLA_CHAT, ("phone", OLA["phone"]), clock="16:10"),
        _message("2026-09-12", QUOTED, OLA_CHAT, ("phone", OLA["phone"]), clock="16:15"),
        _message("2026-09-12", WHOLE_CHAT, OLA_CHAT, clock="16:20"),
        _message("2026-09-12", PASTED, OLA_CHAT, clock="16:25"),
        received,
        _sent_mail("2026-09-04", OLA, f"{MY_MAIL}\n\nOn 3 Sep 2026 Ola wrote:\n> {THEIR_MAIL}"),
    )
    _done(lb, KEPT_OLD, "2025-03-05")
    _done(lb, KEPT_RECENT, "2026-09-14")
    _done(lb, CANCELLED, "2026-09-14", status="cancelled")


def test_a_promise_on_a_page_is_one_of_the_owners_or_the_persons_own(lb: Logbook):
    _promises_record(lb)
    built = _built(lb)
    page = "\n".join(_page(built, OLA))
    facts = _facts(built, OLA)["promises"]
    mine = [p["sentence"] for p in facts["owed_by_owner"]]
    theirs = [p["sentence"] for p in facts["owed_to_owner"]]
    assert "SENTINEL-REQUEST" not in page and REQUEST not in mine, "a request is no promise"
    assert "SENTINEL-THEIR-MAIL" not in page, "a mail the owner did not write, nor the reply quoting it"
    assert MY_MAIL in mine, "a mail the owner wrote"
    assert "SENTINEL-QUOTED" not in page, "a quoted line inside a reply"
    assert "SENTINEL-CHAT" not in page and "SENTINEL-PASTED" not in page, "a whole chat is no sentence"
    assert "I'll send you the drawings by Friday." in theirs and "I will call the yard tomorrow." in mine


def test_open_promises_and_those_kept_in_the_last_year(lb: Logbook):
    _promises_record(lb)
    built = _built(lb)
    page = _page(built, OLA)
    text = "\n".join(page)
    assert f"{DASH} „{OLD_OPEN}“ (04.11.2024, offen)" in page, "open, however old"
    assert f"{DASH} „{KEPT_RECENT}“ (12.09.2026, gehalten am 14.09.2026)" in page
    assert "SENTINEL-KEPT-OLD" not in text, "kept more than 365 days ago"
    assert "SENTINEL-CANCELLED" not in text, "let go, not kept"
    mine = {p["sentence"]: p for p in _facts(built, OLA)["promises"]["owed_by_owner"]}
    assert mine[OLD_OPEN]["status"] == "open" and mine[OLD_OPEN]["kept"] is None
    assert mine[KEPT_RECENT]["status"] == "kept" and mine[KEPT_RECENT]["kept"] == "2026-09-14"
    assert KEPT_OLD not in mine and CANCELLED not in mine


def test_every_rendered_promise_keeps_its_date_and_the_section_is_capped(lb: Logbook):
    _promises_record(lb)
    _append(
        lb,
        *(
            _message("2026-09-20", f"I'll send drawing number {n} tomorrow.", OLA_CHAT, clock=f"12:{n:02d}")
            for n in range(1, 9)
        ),
    )
    built = _built(lb)
    page = _page(built, OLA)
    start = page.index("Versprechen von mir:")
    end = page.index("Versprechen an mich:")
    listed = page[start + 1 : end]
    mine = _facts(built, OLA)["promises"]["owed_by_owner"]
    shown = notion_export.PROMISES_SHOWN
    assert len(listed) == shown + 1
    assert all(PROMISE_LINE.match(line) for line in listed[:shown]), listed
    assert listed[-1] == f"… und {len(mine) - shown} weitere"
    dates = [PROMISE_LINE.match(line).group(1) for line in listed[:shown]]  # type: ignore[union-attr]
    assert dates == ["20.09.2026"] * shown, "the newest first"
    for line in page:
        if line.startswith(f"{DASH} "):
            assert PROMISE_LINE.match(line), line


def test_a_side_with_none_says_so(lb: Logbook):
    built = _built(lb, since="2026-09-01", unsigned=False)
    assert "Versprechen an mich:" in _page(built, OLA)
    _append(lb, _message("2026-09-12", "Hei", f"{PER['phone'][1:]}@s.whatsapp.net", ("phone", PER["phone"])))
    signing.sign(lb, "2026-09-12", at="2026-10-02T08:00:00Z")
    built = _built(lb, since="2026-09-01", unsigned=False)
    page = _page(built, PER)
    assert "Versprechen von mir: keine" in page and "Versprechen an mich: keine" in page


def test_the_dry_run_says_how_wide_the_sections_are(lb: Logbook, tmp_path: Path, capsys):
    from logbook import cli

    _promises_record(lb)
    cli.main(["export", "notion", str(tmp_path / "out"), "--dry-run", "--include-unsigned"])
    text = capsys.readouterr().out
    built = _built(lb)
    sizes = built.sections()
    assert sizes["together"] == 1, "Ola's page alone has a day together"
    assert "days together: 1 line on 1 page" in text
    assert (
        f"promises: {sizes['promise_lines']} lines ({sizes['listed']} listed, {sizes['more']} more not"
        in text
    )
