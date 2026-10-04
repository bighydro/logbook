"""`logbook rollup people --drifting [--window N] [--min-contacts N]`: the people whose contact
frequency fell most between the recent window and the same-length window before it. A reader:
nothing is written. The record is synthetic (the Oslo persona and a handful of people who do not
exist; UK reserved phone numbers, example.org addresses)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from circle import ANDERS, EVA, LIV, NILS, OLA, OWNER, PER, call, mail, message
from persona import OFFICE, OLA_ID, PLACES, TZ, attendee, dwell, event, resolution, utc

from logbook import cli
from logbook.core import drifting, people
from logbook.core.store import Logbook

UNTIL = "2026-06-28"  # the recent window is 15 to 28 June; the earlier one 1 to 14 June
WINDOW = 14


def _chat(person: dict[str, Any]) -> tuple[str, str, str]:
    """A direct WhatsApp chat with `person`: the JID is the phone number."""
    return (f"{person['phone'][1:]}@s.whatsapp.net", "direct", person["name"].split()[0])


def drifting_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """Two fortnights. Earlier (1 to 14 June): Ola is everywhere — four direct messages, an answered
    call, a timed meeting at the office the track confirms; Per writes three times; Liv calls
    twice; Eva writes three times and calls once unanswered (and one message of hers is
    retracted); Anders writes three times; Nils sends five mails. Recent (15 to 28 June): Ola writes
    once; Per three times; Anders six times; Liv, Eva and Nils are not heard. The owner is at the
    office on the 3rd (with Ola) and on the 20th (alone)."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    (lb.root / "places.json").write_text(json.dumps(PLACES, indent=2), encoding="utf-8")
    owner_id = str(lb.meta["owner_id"])
    drafts: list[dict[str, Any]] = [
        resolution(("email", OWNER["email"]), owner_id, OWNER["name"]),
        resolution(("phone", OWNER["phone"]), owner_id, OWNER["name"]),
        resolution(("email", OLA["email"]), OLA_ID, OLA["name"]),
        resolution(("phone", OLA["phone"]), OLA_ID, OLA["name"]),
    ]
    for p in (PER, LIV, EVA, ANDERS, NILS):
        drafts.append(resolution(("email", p["email"]), p["id"], p["name"]))
        drafts.append(resolution(("phone", p["phone"]), p["id"], p["name"]))
    drafts += dwell("2026-06-03", "08:10", "17:50", OFFICE) + dwell("2026-06-20", "08:10", "17:50", OFFICE)
    ola, per, eva, anders = _chat(OLA), _chat(PER), _chat(EVA), _chat(ANDERS)
    drafts += [
        # Ola, earlier: four messages, one answered call, one timed meeting the office stay confirms.
        message(utc("2026-06-02", "09:00"), ola, "Lunch this week?"),
        message(utc("2026-06-02", "09:05"), ola, "Wednesday?", OLA),
        message(utc("2026-06-05", "17:00"), ola, "Thanks for today."),
        message(utc("2026-06-08", "08:00"), ola, "Sending the notes.", OLA),
        call(utc("2026-06-04", "19:00"), OLA, True, 15 * 60),
        event(utc("2026-06-03", "10:00"), utc("2026-06-03", "12:00"), "Planning", [attendee(OLA["email"])]),
        # Ola, recent: one message.
        message(utc("2026-06-16", "12:00"), ola, "Back from the cabin.", OLA),
        # Per, steady: three messages in each fortnight.
        message(utc("2026-06-02", "10:00"), per, "Hi", PER),
        message(utc("2026-06-06", "10:00"), per, "Hi again", PER),
        message(utc("2026-06-10", "10:00"), per, "Still here", PER),
        message(utc("2026-06-16", "10:00"), per, "Hi", PER),
        message(utc("2026-06-20", "10:00"), per, "Hi again", PER),
        message(utc("2026-06-24", "10:00"), per, "Still here", PER),
        # Liv, earlier: two answered calls; recent: nothing. Below three contacts.
        call(utc("2026-06-03", "20:00"), LIV, True, 10 * 60),
        call(utc("2026-06-09", "20:00"), LIV, False, 0),
        # Eva, earlier: three messages, one missed call; recent: nothing.
        message(utc("2026-06-01", "11:00"), eva, "Are you around?", EVA),
        message(utc("2026-06-07", "11:00"), eva, "Call me", EVA),
        message(utc("2026-06-12", "11:00"), eva, "Never mind", EVA),
        call(utc("2026-06-13", "21:00"), EVA, True, 0),
        # Anders, rising: three messages earlier, six recent.
        *(message(utc(f"2026-06-{d:02d}", "15:00"), anders, "Regatta?", ANDERS) for d in (2, 6, 10)),
        *(message(utc(f"2026-06-{d:02d}", "15:00"), anders, "Regatta!", ANDERS) for d in range(16, 28, 2)),
        # Nils, mail only: five newsletters earlier, none recent. Mail is never a contact.
        *(mail(utc(f"2026-06-{d:02d}", "07:00"), NILS, OWNER, "Club news") for d in (1, 4, 7, 10, 13)),
    ]
    lb.append_many(drafts)
    stray = lb.append(
        at=utc("2026-06-14", "11:00"),
        source="whatsapp",
        kind="message",
        tier=2,
        payload=message(utc("2026-06-14", "11:00"), eva, "Wrong chat", EVA)["payload"],
    )
    lb.retract(int(stray["seq"]), "not Eva's", at=utc("2026-06-14", "11:30"))
    policy = lb.root / "policy"
    policy.mkdir(exist_ok=True)
    (policy / "owner.json").write_text(
        json.dumps({"names": [OWNER["name"]], "emails": [OWNER["email"]], "phones": [OWNER["phone"]]}),
        encoding="utf-8",
    )
    return lb


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main([*args])
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_run(capsys, *args, "--json"))
    return data


DRIFTING = ("rollup", "people", "--drifting", "--until", UNTIL, "--window", str(WINDOW))


def test_drifting_lists_the_people_whose_contact_frequency_fell_most(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = drifting_record(tmp_path, monkeypatch)
    head = lb.meta["head"]
    data = _json(capsys, *DRIFTING)
    assert data["kind"] == "drifting" and data["min_contacts"] == 3
    assert data["window"]["recent"]["since"] == "2026-06-15" and data["window"]["recent"]["until"] == UNTIL
    assert data["window"]["earlier"] == {
        "since": "2026-06-01",
        "until": "2026-06-14",
        "days": [f"2026-06-{d:02d}" for d in range(1, 15)],
    }
    assert data["window"]["recent"]["days"] == [f"2026-06-{d:02d}" for d in range(15, 29)]
    assert "warning" not in data, "the record begins on the earlier window's first day"
    assert [p["name"] for p in data["people"]] == [EVA["name"], OLA["name"]], "fell most first"
    eva, ola = data["people"]
    assert ola["id"] == OLA_ID
    assert ola["earlier"]["contacts"] == 7 and ola["recent"]["contacts"] == 1
    assert {k: v["count"] for k, v in ola["earlier"].items() if isinstance(v, dict)} == {
        "messages": 4,
        "calls": 1,
        "calendar": 1,
        "together": 1,
    }
    assert {k: v["count"] for k, v in ola["recent"].items() if isinstance(v, dict)} == {
        "messages": 1,
        "calls": 0,
        "calendar": 0,
        "together": 0,
    }
    assert ola["fall"] == 6 and ola["fell_by"] == pytest.approx(6 / 7, abs=0.001)
    assert ola["quiet"] == ["calls", "calendar", "together"]
    assert ola["last_real_contact"] == {
        "day": "2026-06-16",
        "via": "message",
        "line": ola["last_real_contact"]["line"],
    }
    assert ola["days_since_real_contact"] == 12, "from the 16th to the window's last day, the 28th"
    assert ola["last_place"]["where"] == "Office" and ola["last_place"]["day"] == "2026-06-03"
    assert (
        len(ola["last_place"]["lines"]) == 1
        and ola["last_place"]["lines"][0] == ola["earlier"]["calendar"]["lines"][0]
    )
    assert eva["earlier"]["contacts"] == 4 and eva["recent"]["contacts"] == 0, "the retracted message is out"
    assert eva["fall"] == 4 and eva["fell_by"] == 1.0 and eva["quiet"] == ["messages", "calls"]
    assert eva["last_real_contact"]["day"] == "2026-06-12", "a missed call is not a real contact"
    assert eva["days_since_real_contact"] == 16 and eva["last_place"] is None
    assert lb.meta["head"] == head, "nothing is written"


def test_every_number_carries_its_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    drifting_record(tmp_path, monkeypatch)
    data = _json(capsys, *DRIFTING)
    for p in data["people"]:
        for side in ("earlier", "recent"):
            bucket = p[side]
            channels = {k: v for k, v in bucket.items() if isinstance(v, dict)}
            assert set(channels) == {"messages", "calls", "calendar", "together"}
            for name, c in channels.items():
                assert all(len(id_) == 36 for id_ in c["lines"])
                if name == "together":
                    assert bool(c["count"]) == bool(c["lines"]), "a stay together has its evidence"
                else:
                    assert c["count"] == len(c["lines"]), "one line per message, call or entry"
            assert bucket["contacts"] == sum(c["count"] for c in channels.values())
            # the meeting's line is the calendar entry and the stay's evidence: once in the union
            union = {id_ for c in channels.values() for id_ in c["lines"]}
            assert set(bucket["lines"]) == union and len(bucket["lines"]) == len(union)
        if p["last_real_contact"] is not None:
            assert len(p["last_real_contact"]["line"]) == 36


def test_the_table_reads_plainly_and_suggests_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    drifting_record(tmp_path, monkeypatch)
    out = _run(capsys, *DRIFTING)
    lines = out.splitlines()
    assert lines[0] == (
        f"people · drifting · recent 2026-06-15 {drifting.EN_DASH} 2026-06-28 · earlier 2026-06-01 "
        f"{drifting.EN_DASH} 2026-06-14 · at least 3 contacts earlier"
    )
    assert lines[1].split() == [
        "person",
        "earlier",
        "recent",
        "fall",
        "last",
        "real",
        "contact",
        "quiet",
        "last",
        "shared",
        "place",
    ]
    eva, ola = lines[2], lines[3]
    assert eva.startswith(f"        {EVA['name']:<24}") and "4" in eva and "-100%" in eva
    assert "16 days ago" in eva and "messages, calls" in eva and eva.rstrip().endswith(drifting.EM_DASH)
    assert (
        "-86%" in ola
        and "12 days ago" in ola
        and "calls, calendar, together" in ola
        and ola.rstrip().endswith("Office")
    )
    assert len(lines) == 4
    for phrase in ("reach out", "should", "try", "suggest"):
        assert phrase not in out.casefold(), phrase


def test_min_contacts_is_the_floor_on_the_earlier_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    drifting_record(tmp_path, monkeypatch)
    data = _json(capsys, *DRIFTING, "--min-contacts", "2")
    # two people fell to nothing: the larger fall first; Liv's two calls now clear the floor
    assert [p["name"] for p in data["people"]] == [EVA["name"], LIV["name"], OLA["name"]]
    liv = data["people"][1]
    assert liv["earlier"]["contacts"] == 2 and liv["quiet"] == ["calls"] and liv["last_place"] is None
    assert liv["last_real_contact"]["day"] == "2026-06-03", "the answered call; the missed one is not real"
    assert liv["days_since_real_contact"] == 25
    assert data["min_contacts"] == 2
    data = _json(capsys, *DRIFTING, "--min-contacts", "8")
    assert data["people"] == [], "nobody had eight contacts in the earlier fortnight"
    assert (
        _run(capsys, *DRIFTING, "--min-contacts", "8").splitlines()[-1]
        == "        nobody fell below their earlier frequency"
    )


def test_steady_rising_and_mail_only_people_are_not_drifting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    drifting_record(tmp_path, monkeypatch)
    names = {p["name"] for p in _json(capsys, *DRIFTING, "--min-contacts", "1")["people"]}
    assert PER["name"] not in names, "three messages in each fortnight is steady"
    assert ANDERS["name"] not in names, "six after three is rising"
    assert NILS["name"] not in names, "five newsletters are mail, and mail is never a contact"
    assert OWNER["name"] not in names


def test_the_window_defaults_to_the_record_s_last_day_and_a_year(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    drifting_record(tmp_path, monkeypatch)
    data = _json(capsys, "rollup", "people", "--drifting")
    last = date(2026, 6, 26)  # Anders's last message: the last day with a line of any kind
    recent, earlier = data["window"]["recent"], data["window"]["earlier"]
    assert recent["until"] == last.isoformat() and recent["since"] == (last - timedelta(days=364)).isoformat()
    assert earlier["until"] == (last - timedelta(days=365)).isoformat()
    assert earlier["since"] == (last - timedelta(days=729)).isoformat()
    assert len(recent["days"]) == 365 and len(earlier["days"]) == 365
    assert recent["days"][0] == recent["since"] and earlier["days"][-1] == earlier["until"]
    assert data["warning"] == "the record begins 2026-06-01, inside the recent window"
    assert data["people"] == [], "everyone is new: nobody fell"
    out = _run(capsys, "rollup", "people", "--drifting")
    assert out.splitlines()[1] == f"  ({data['warning']})"


def test_an_empty_record_rolls_up_to_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    data = _json(capsys, "rollup", "people", "--drifting")
    assert data == drifting.empty()
    assert data["window"] == {"recent": None, "earlier": None} and data["people"] == []
    assert _run(capsys, "rollup", "people", "--drifting").splitlines()[1] == "  nothing in the window"


def test_the_flags_go_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    drifting_record(tmp_path, monkeypatch)
    for args, text in (
        (("rollup", "places", "--drifting"), "--drifting goes with `rollup people`"),
        (("rollup", "people", "--window", "30"), "--window and --min-contacts go with --drifting"),
        (("rollup", "people", "--min-contacts", "2"), "--window and --min-contacts go with --drifting"),
        (("rollup", "people", "--drifting", "--year", "2026"), "--drifting takes --until and --window"),
        (
            ("rollup", "people", "--drifting", "--since", "2026-06-01"),
            "--drifting takes --until and --window",
        ),
        (("rollup", "people", "--drifting", "--window", "0"), "--window is a number of days, at least 1"),
        (("rollup", "people", "--drifting", "--min-contacts", "-1"), "--min-contacts is a count, at least 0"),
        (("rollup", "people", "--drifting", "--with"), "--with goes with `rollup places`"),
    ):
        with pytest.raises(SystemExit) as e:
            cli.main([*args])
        assert e.value.code == 2
        assert text in capsys.readouterr().err, args


def test_compare_is_pure_and_the_reports_are_the_people_reader_s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The comparison takes two `people.Report`s, so what `logbook people` says of each window is
    what the drift is read from."""
    lb = drifting_record(tmp_path, monkeypatch)
    earlier = people.read(lb, "2026-06-01", "2026-06-14")
    recent = people.read(lb, "2026-06-15", "2026-06-28")
    rows = drifting.compare(earlier, recent, min_contacts=3)
    assert [r["name"] for r in rows] == [EVA["name"], OLA["name"]]
    ola = next(r for r in rows if r["name"] == OLA["name"])
    by_name = {p.name: p for p in earlier.people}
    assert ola["earlier"]["messages"]["lines"] == by_name[OLA["name"]].channels["messages"].ids
    assert ola["earlier"]["together"]["count"] == len(by_name[OLA["name"]].shared)
