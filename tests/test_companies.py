"""The companies a day touched (RFC 0043 §11, §12): `companies_of(lb, day)` over the Manifest's orgs —
an update mailed from an org's domain, a meeting with someone of theirs (a calendar attendee, a
transcript's participant), a document naming it (a repository link) — each row the org, what touched
it and the lines, grouped by the portfolio an org's tier-3 status line carries; statuses and
portfolios only where tier 3 is read. `logbook lab companies DAY [--json]`. Synthetic: the orgs record."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from orgs_record import KIOSK, TIDEVANN, TODAY, VERFT, evidence_record, settle

from logbook import cli
from logbook.contrib import companies, entity_status, orgs
from logbook.core.store import Logbook

BOARD, PACK, PITCH, MERGED, INTRO = "2026-09-15", "2026-10-09", "2026-04-10", "2026-09-20", "2026-05-04"


@pytest.fixture(scope="module")
def settled(tmp_path_factory: pytest.TempPathFactory) -> Path:
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LOGBOOK_DIAL_PREFIX", "44")
        lb = evidence_record(tmp_path_factory.mktemp("companies"))
        settle(lb)
        return lb.root


@pytest.fixture
def lb(settled: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    shutil.copytree(settled, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    monkeypatch.setenv("LOGBOOK_DIAL_PREFIX", "44")
    return Logbook(root)


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    try:
        cli.main(list(argv))
        code = 0
    except SystemExit as e:
        code = int(e.code or 0)
    out = capsys.readouterr()
    return code, out.out, out.err


def _seen(found: companies.Companies) -> list[tuple[str, str | None, list[tuple[str, str, tuple[str, ...]]]]]:
    return [
        (c.name, c.status, [(t.what, t.title, t.people) for t in c.touches])
        for _portfolio, rows in found.groups()
        for c in rows
    ]


def test_an_update_mailed_from_an_org_s_domain_touches_it(lb: Logbook) -> None:
    found = companies.companies_of(lb, PACK)
    assert _seen(found) == [(VERFT, "hold", [("update", "Board pack October", ("Ola Nordmann",))])]
    [row] = found.rows
    [touch] = row.touches
    line = next(x for x in lb.lines() if x["id"] == touch.line)
    assert (line["kind"], line["payload"]["subject"]) == ("mail", "Board pack October")


def test_a_mail_copied_to_someone_of_theirs_touches_it_as_a_mail_not_an_update(lb: Logbook) -> None:
    found = companies.companies_of(lb, INTRO)
    assert _seen(found) == [(TIDEVANN, "add", [("mail", "Intro: Ines <> Liv (Tidevann)", ("Liv Berg",))])]


def test_a_meeting_with_an_attendee_of_theirs_touches_each_org_with_its_own_people(lb: Logbook) -> None:
    found = companies.companies_of(lb, BOARD)
    assert _seen(found) == [
        (TIDEVANN, "add", [("meeting", "Verft board", ("Liv Berg",))]),
        (VERFT, "hold", [("meeting", "Verft board", ("Ola Nordmann",))]),
    ]


def test_a_transcript_s_participant_is_a_meeting_too(lb: Logbook) -> None:
    found = companies.companies_of(lb, PITCH)
    [row] = found.rows
    assert (row.name, row.status) == (KIOSK, "passed")
    assert [(t.what, t.kind, t.people) for t in row.touches] == [
        ("meeting", "event", ("Kari Nordmann",)),
        ("meeting", "transcript", ("Kari Nordmann",)),
    ]


def test_a_document_naming_it_is_a_repository_link(lb: Logbook) -> None:
    found = companies.companies_of(lb, MERGED)
    assert _seen(found) == [(TIDEVANN, "add", [("document", "Merged pull request #12", ())])]


def test_the_rows_group_by_the_portfolio_on_the_org_s_status_line(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    entity_status.write(lb, "org", VERFT, "hold", None, at="2026-10-03", today=TODAY, portfolio="Fund I")
    entity_status.write(lb, "org", TIDEVANN, "add", None, at="2026-10-04", today=TODAY, portfolio="Angel")
    found = companies.companies_of(lb, BOARD)
    assert [(p, [c.name for c in rows]) for p, rows in found.groups()] == [
        ("Angel", [TIDEVANN]),
        ("Fund I", [VERFT]),
    ]
    code, out, err = _run(capsys, "lab", "companies", BOARD)
    assert code == 0, err
    lines = out.splitlines()
    assert lines[0] == f"{BOARD} · 2 companies"
    assert lines.index("Angel") < lines.index(f"  {TIDEVANN}  add") < lines.index("Fund I")
    assert lines.index("Fund I") < lines.index(f"  {VERFT}  hold")
    code, out, err = _run(capsys, "lab", "companies", BOARD, "--json")
    assert code == 0, err
    data = json.loads(out)
    assert data["day"] == BOARD and data["statuses"] is True
    assert [(g["portfolio"], [c["name"] for c in g["companies"]]) for g in data["groups"]] == [
        ("Angel", [TIDEVANN]),
        ("Fund I", [VERFT]),
    ]
    [touch] = data["groups"][1]["companies"][0]["touches"]
    assert touch["what"] == "meeting" and touch["kind"] == "event" and touch["people"] == ["Ola Nordmann"]


def test_through_a_gate_without_tier_three_no_status_and_no_portfolio_is_shown(lb: Logbook) -> None:
    entity_status.write(lb, "org", VERFT, "hold", None, at="2026-10-03", today=TODAY, portfolio="Fund I")
    found = companies.companies_of(lb, BOARD, tiers=(1, 2))
    assert not found.statuses
    assert [(p, [(c.name, c.status, c.portfolio) for c in rows]) for p, rows in found.groups()] == [
        (None, [(TIDEVANN, None, None), (VERFT, None, None)])
    ]
    assert found.to_json()["hidden"] == orgs.HIDDEN
    text = "\n".join(companies.rows(found))
    for word in ("hold", "add", "Fund I", "passed"):
        assert word not in text, word
    assert orgs.HIDDEN in text


def test_a_day_no_org_touched_says_so(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _run(capsys, "lab", "companies", "2026-01-01")
    assert code == 0, err
    assert out.strip() == "2026-01-01 · no org the Manifest names touched this day"
    code, out, err = _run(capsys, "lab", "companies", "not-a-day")
    assert code == 2 and "not-a-day" in err and "Traceback" not in err


def test_a_retracted_mail_touches_nothing(lb: Logbook) -> None:
    [touch] = companies.companies_of(lb, PACK).rows[0].touches
    [line] = [x for x in lb.lines() if x["id"] == touch.line]
    lb.retract(int(line["seq"]), "not mine")
    assert companies.companies_of(lb, PACK).rows == []


def test_someone_of_theirs_the_record_has_not_placed_is_named_as_the_transcript_names_them(
    lb: Logbook,
) -> None:
    from orgs_record import OLA, VERFT_DOMAIN
    from persona import transcript, utc

    call = transcript(
        utc("2026-10-14", "10:00"),
        utc("2026-10-14", "11:00"),
        "Verft yard call",
        [
            {"name": "Siri Verft", "email": f"siri@{VERFT_DOMAIN}"},
            {"name": OLA["name"], "email": OLA["email"]},
            {"name": "me"},
        ],
    )
    lb.append_many([call])
    found = companies.companies_of(lb, "2026-10-14")
    assert _seen(found) == [(VERFT, "hold", [("meeting", "Verft yard call", ("Siri Verft", "Ola Nordmann"))])]


def test_someone_of_theirs_with_no_name_is_someone_at_the_org_never_an_address(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """An attendee with no name and no resolution, and a sender with an empty name, at the org's
    domain: `someone at Nordmann Verft AS`; nothing printed carries an address."""
    from orgs_record import OWNER, VERFT_DOMAIN, mail, meeting

    nameless = {"name": "", "email": f"yard@{VERFT_DOMAIN}"}
    entry = meeting(utc_("2026-10-15", "09:00"), utc_("2026-10-15", "10:00"), "Yard walk", [nameless])
    entry["payload"]["attendees"][0].pop("name", None)
    lb.append_many([entry, mail(utc_("2026-10-15", "12:00"), nameless, [OWNER], "Launch date")])
    found = companies.companies_of(lb, "2026-10-15")
    assert _seen(found) == [
        (
            VERFT,
            "hold",
            [
                ("meeting", "Yard walk", ("someone at Nordmann Verft AS",)),
                ("update", "Launch date", ("someone at Nordmann Verft AS",)),
            ],
        )
    ]
    for argv in (("lab", "companies", "2026-10-15"), ("lab", "companies", "2026-10-15", "--json")):
        code, out, err = _run(capsys, *argv)
        assert code == 0, err
        assert "someone at Nordmann Verft AS" in out
        assert "@" not in out, argv


def utc_(day: str, clock: str) -> str:
    from persona import utc

    return utc(day, clock)


def test_an_attendee_the_record_has_not_placed_is_named_as_the_calendar_names_them(lb: Logbook) -> None:
    from orgs_record import VERFT_DOMAIN, meeting

    entry = meeting(
        utc_("2026-10-16", "09:00"),
        utc_("2026-10-16", "10:00"),
        "Hull survey",
        [{"name": "Siri Verft", "email": f"siri@{VERFT_DOMAIN}"}],
    )
    lb.append_many([entry])
    assert _seen(companies.companies_of(lb, "2026-10-16")) == [
        (VERFT, "hold", [("meeting", "Hull survey", ("Siri Verft",))])
    ]
