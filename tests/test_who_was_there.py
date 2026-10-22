"""Who was there (RFC 0043 §11, §12): `with --from D1 --to D2 NAME` (one `with` note per day at its
longest stay, through `presence.state`), `people not-with`, `people lives-with`, `people lives-in`,
the review-with queue (`review with`) and your people in a city (`people city`). On the Oslo persona,
who does not exist: Ines is the owner; Kari Nordmann lives with her; Ola Nordmann is a friend; Per
Hansen lives in Bergen; the crew of the 19th are invented too. Numbers are in the reserved 07700 900xxx
range, addresses at example.org."""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from persona import (
    HOME,
    KARI,
    KARI_ID,
    OFFICE,
    OLA,
    OLA_ID,
    TZ,
    attendee,
    dwell,
    event,
    persona_record,
    photo,
    resolution,
    transcript,
    travel,
    utc,
)

from logbook import cli
from logbook.contrib import review_with, week_paper, who_was_there
from logbook.core import presence, present
from logbook.core.chain import Line
from logbook.core.store import Logbook

PER_ID = "019cadd3-6bc0-7dcd-9133-000000000003"
OLA_FACE, PER_FACE = "p_21", "p_33"
BERGEN = (60.3913, 5.3221)  # the flat in Bergen, invented
CREW = (
    "Astrid Berg",
    "Bjørn Dahl",
    "Cecilie Lund",
    "Didrik Moe",
    "Eli Strand",
    "Frode Vik",
    "Gro Holm",
    "Hans Lie",
    "Ida Bakke",
    "Jon Eide",
    "Kaja Ruud",
    "Lars Foss",
)
WEEK = week_paper.week_of("2026-06-08")  # Monday 8 June to Sunday 14 June
CREW_DAY = "2026-06-19"  # a Friday at the office
TRIP_DAY = "2026-07-02"  # a day of the journey to Bergen
LAST_NIGHT = "2026-07-03"  # its last night away
MEET_DAY = "2026-06-17"  # a day at the hotel in Zürich
NOW = datetime(2026, 10, 21, 10, 0, tzinfo=UTC)


def _crew_id(n: int) -> str:
    return f"019cadd3-6bc0-7dcd-9133-0000000001{n:02d}"


def _drafts() -> list[dict[str, Any]]:
    """What the persona's fortnight lacks for these tests: Per and the crew, Ola's face, the photos,
    and a journey to Bergen, 1 to 4 July."""
    drafts: list[dict[str, Any]] = [
        resolution(("email", "per.hansen@example.org"), PER_ID, "Per Hansen"),
        resolution(("phone", "+447700900123"), PER_ID, "Per Hansen"),
        resolution(("provider_id", f"immich:{PER_FACE}"), PER_ID, "Per Hansen"),
        resolution(("provider_id", f"immich:{OLA_FACE}"), OLA_ID, "Ola Nordmann"),
    ]
    for n, name in enumerate(CREW, start=1):
        drafts.append(resolution(("provider_id", f"immich:c_{n:02d}"), _crew_id(n), name))
    # Kari at home on Tuesday evening, from the owner's own camera
    drafts.append(photo(utc("2026-06-09", "20:00"), HOME, people=[KARI["face"]]))
    # Ola's face on Friday, on photos that were sent, never taken: a chat's, and an AirDrop's
    received = photo(utc("2026-06-12", "10:00"), OFFICE, people=[OLA_FACE])
    received["payload"]["provenance"] = "received"
    received["payload"]["raw_id"] = received["payload"]["asset_id"] = "p-received-1"
    airdrop = photo(utc("2026-06-12", "11:00"), OFFICE, people=[OLA_FACE], library="immich")
    airdrop["payload"]["raw_id"] = airdrop["payload"]["asset_id"] = "p-airdrop-1"
    airdrop["payload"]["extra"] = {"imported_by": 8}
    drafts += [received, airdrop]
    # the crew at the office on the 19th: the n-th of them on n photos
    for n in range(1, len(CREW) + 1):
        for k in range(n):
            at = datetime.fromisoformat(utc(CREW_DAY, "09:00").replace("Z", "+00:00")) + timedelta(
                minutes=n * 13 + k
            )
            shot = photo(at.strftime("%Y-%m-%dT%H:%M:%SZ"), OFFICE, people=[f"c_{n:02d}"])
            shot["payload"]["raw_id"] = shot["payload"]["asset_id"] = f"p-crew-{n:02d}-{k:02d}"
            drafts.append(shot)
    # the journey to Bergen: home on 30 June, three nights away, home on 4 July
    drafts += (
        dwell("2026-06-30", "07:30", "24:00", HOME)
        + dwell("2026-07-01", "00:00", "07:30", HOME)
        + travel("2026-07-01", "07:30", "14:30", HOME, BERGEN, steps=40)
        + dwell("2026-07-01", "14:30", "24:00", BERGEN)
        + dwell("2026-07-02", "00:00", "24:00", BERGEN)
        + dwell("2026-07-03", "00:00", "24:00", BERGEN)
        + dwell("2026-07-04", "00:00", "09:00", BERGEN)
        + travel("2026-07-04", "09:00", "16:00", BERGEN, HOME, steps=40)
        + dwell("2026-07-04", "16:00", "24:00", HOME)
        + dwell("2026-07-05", "00:00", "12:00", HOME)
    )
    drafts.append(photo(utc(TRIP_DAY, "15:00"), BERGEN, people=[PER_FACE]))
    # dinner in Bergen with Ola on the 3rd, which he accepted: the with module confirms him at the stay
    drafts.append(
        event(utc(LAST_NIGHT, "19:00"), utc(LAST_NIGHT, "22:00"), "Dinner", [attendee(OLA["email"])])
    )
    # a Meet call from the hotel in Zürich on the 17th, Ola among its participants
    call = transcript(
        utc(MEET_DAY, "10:00"),
        utc(MEET_DAY, "10:45"),
        "Crew sync",
        [{"name": "Ola Nordmann", "email": OLA["email"]}],
    )
    call["source"] = call["payload"]["provider"] = "meet"
    drafts.append(call)
    return drafts


@pytest.fixture(scope="module")
def pristine(tmp_path_factory: pytest.TempPathFactory) -> Path:
    with pytest.MonkeyPatch.context() as mp:
        lb = persona_record(tmp_path_factory.mktemp("who"), mp)
        lb.append_many(_drafts())
        root = lb.root
    (root / "policy").mkdir(exist_ok=True)
    (root / "policy" / "owner.json").write_text(
        json.dumps({"names": ["Ines Nordmann"], "emails": [], "phones": []}), encoding="utf-8"
    )
    return root


@pytest.fixture
def lb(pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    shutil.copytree(pristine, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook(root)


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main([*args])
    return capsys.readouterr().out


def _refused(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    with pytest.raises(SystemExit) as stop:
        cli.main([*args])
    assert stop.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("\n") == 1, captured.err  # one sentence, one line
    assert ". " not in captured.err, captured.err
    return captured.err


def _labelled(lb: Logbook, label: str) -> list[Line]:
    return [
        line
        for line in lb.lines()
        if line["kind"] == "note" and label in (line["payload"].get("labels") or [])
    ]


def _clock(line: Line) -> datetime:
    return datetime.fromisoformat(line["at"].replace("Z", "+00:00")).astimezone(ZoneInfo(TZ))


def _queue(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_run(capsys, "review", "with", *args, "--json"))
    return data


def _asked(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {p["name"]: p for p in data["people"]}


def _number(capsys: pytest.CaptureFixture[str], name: str, *stretch: str) -> str:
    """The number `review with` gives `name` in the queue of `stretch`: their place in its list."""
    names = [p["name"] for p in _queue(capsys, *stretch)["people"]]
    return str(names.index(name) + 1)


# -- with across a stretch -----------------------------------------------------------------------------------


def test_with_across_a_stretch_writes_one_line_per_day_at_the_longest_stay(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = lb.meta["seq"]
    out = _run(capsys, "with", "--from", "2026-06-08", "--to", "2026-06-12", "Ola")
    lines = _labelled(lb, "with")
    assert lb.meta["seq"] == seq + 5 and len(lines) == 5
    for line in lines:
        assert {k: line[k] for k in ("source", "kind", "tier", "tz")} == {
            "source": "manual",
            "kind": "note",
            "tier": 2,
            "tz": TZ,
        }
        assert line["payload"] == {
            "schema": "note/v1",
            "text": "with Ola Nordmann",
            "labels": ["with"],
            "extra": {"person": OLA_ID},
        }
    by_day = {_clock(line).date().isoformat(): _clock(line) for line in lines}
    assert sorted(by_day) == ["2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12"]
    # an office day: the office, 08:10 to 17:50, is the longest stay; its middle is 13:00
    for day in ("2026-06-08", "2026-06-09", "2026-06-11", "2026-06-12"):
        middle = by_day[day].replace(hour=13, minute=0)
        assert abs((by_day[day] - middle).total_seconds()) <= 600, by_day[day]
    # Wednesday the office is split by lunch at the cafe: the night at home, to 08:00, is the longest
    wednesday = by_day["2026-06-10"]
    assert abs((wednesday - wednesday.replace(hour=4, minute=0)).total_seconds()) <= 600, wednesday
    assert len(out.splitlines()) == 5 and all(
        " with Ola Nordmann  2026-06-" in row for row in out.splitlines()
    )
    # the with module reads each as company at the stay it lies in
    rd = review_with.reading.read(lb, "2026-06-08", "2026-06-12")
    stay_of = {
        line["id"]: next(s for s in rd.owner_stays if s.start <= _clock(line) < s.end) for line in lines
    }
    for line in lines:
        found = present.from_notes(stay_of[line["id"]], [line], rd.identities)
        assert [p.person for p in found] == [OLA_ID]
    again = _run(capsys, "with", "--from", "2026-06-08", "--to", "2026-06-12", "Ola")
    assert lb.meta["seq"] == seq + 5 and again.count("stated on") == 5
    assert lb.verify()[2] == []


def test_a_stretch_is_written_by_the_function_with_uses_for_one_day(lb: Logbook) -> None:
    """The same bytes as `presence.state` at the same clock: the stretch adds no writer of its own."""
    [day] = who_was_there.with_stretch(lb, "2026-06-08", "2026-06-08", ["Kari"], now=NOW)
    assert day.at is not None
    [item] = day.stated
    assert item.line is not None
    other = Logbook.init(lb.root.parent / "other", TZ)
    other.append_many([resolution(("email", KARI["email"]), KARI_ID, "Kari Nordmann")])
    [direct] = presence.state(other, "2026-06-08", ["Kari"], day.at, now=NOW)
    assert direct.line is not None
    strip = ("id", "seq", "prev", "hash", "recorded_at")
    assert {k: v for k, v in item.line.items() if k not in strip} == {
        k: v for k, v in direct.line.items() if k not in strip
    }


def test_a_stretch_refuses_too_long_nobody_two_people_and_the_owner_in_one_sentence(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = lb.meta["seq"]
    long = _refused(capsys, "with", "--from", "2026-06-01", "--to", "2026-07-31", "Ola")
    assert "61 days, longer than 60" in long and "nothing was written" in long
    assert "is nobody" in _refused(capsys, "with", "--from", "2026-06-08", "--to", "2026-06-09", "Sven")
    two = _refused(capsys, "with", "--from", "2026-06-08", "--to", "2026-06-09", "Nordmann")
    assert "names several people: Kari Nordmann, Ola Nordmann" in two
    assert "is you" in _refused(capsys, "with", "--from", "2026-06-08", "--to", "2026-06-09", "Ines Nordmann")
    assert "--from and --to go together" in _refused(capsys, "with", "--from", "2026-06-08", "Ola")
    assert "--at goes with one DAY" in _refused(
        capsys, "with", "--from", "2026-06-08", "--to", "2026-06-09", "Ola", "--at", "12:00"
    )
    assert "before --from" in _refused(capsys, "with", "--from", "2026-06-09", "--to", "2026-06-08", "Ola")
    assert lb.meta["seq"] == seq and _labelled(lb, "with") == []


def test_a_stretch_still_to_come_writes_nothing(lb: Logbook) -> None:
    seq = lb.meta["seq"]
    with pytest.raises(who_was_there.CompanyError, match="has not begun"):
        who_was_there.with_stretch(
            lb, "2026-06-20", "2026-06-23", ["Ola"], now=datetime(2026, 6, 21, 12, tzinfo=UTC)
        )
    assert lb.meta["seq"] == seq


def test_with_for_one_day_is_as_before(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    out = _run(capsys, "with", "2026-06-12", "Ola", "--at", "12:00")
    assert out == f"#{lb.meta['seq']} with Ola Nordmann  2026-06-12 12:00\n"
    assert "say the day and at least one person" in _refused(capsys, "with", "2026-06-12")


# -- the queue -----------------------------------------------------------------------------------------------


def test_the_queue_of_a_week_says_the_evidence_in_words_and_the_days(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _queue(capsys, "--week", WEEK)
    assert data["stretch"]["from"] == "2026-06-08" and data["stretch"]["to"] == "2026-06-14"
    asked = _asked(data)
    assert [p["name"] for p in data["people"]] == ["Kari Nordmann", "Ola Nordmann"]
    kari, ola = asked["Kari Nordmann"], asked["Ola Nordmann"]
    assert kari["person"] == KARI_ID and kari["days"] == ["2026-06-09", "2026-06-10"]
    assert kari["evidence"] == "faces on 2 photos across 2 days · invited to 'Lunch'"
    # Thursday's Granola call: its attendees are kept as its participants, read as meeting notes
    assert ola["evidence"] == "in the meeting notes of 'Boat plans'"
    # Saturday's note says "with Ola Nordmann": the owner answered that day; Friday's photos were sent
    assert ola["days"] == ["2026-06-11"]
    text = _run(capsys, "review", "with", "--week", WEEK)
    assert text.splitlines()[:4] == [
        f"who was there, 2026-06-08 \N{EN DASH} 2026-06-14 (week {WEEK})",
        "  Kari Nordmann",
        "      faces on 2 photos across 2 days · invited to 'Lunch'",
        "      on Tue 9 Jun, Wed 10 Jun",
    ]
    assert "--accept N[,N]" in text and "--not NAME" in text


def test_a_photo_received_in_a_chat_never_proposes(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    data = _queue(capsys, "--from", "2026-06-12", "--to", "2026-06-12")
    assert data["people"] == [] and data["unplaced"] == 0
    shots = {line["payload"]["raw_id"]: line for line in lb.lines() if line["kind"] == "photo"}
    assert not who_was_there.own_camera(shots["p-received-1"])
    assert not who_was_there.own_camera(shots["p-airdrop-1"])  # provenance camera, but AirDropped
    assert who_was_there.own_camera(shots[f"p-{utc('2026-06-09', '20:00')}"])
    apple = {
        "kind": "photo",
        "payload": {"schema": "photo/v1", "provenance": "camera", "extra": {"imported_by": 1}},
    }
    assert who_was_there.own_camera(apple)
    for provenance in ("received", "screenshot", "other", None):
        assert not who_was_there.own_camera({"kind": "photo", "payload": {"provenance": provenance}})


def test_the_queue_is_ordered_strongest_first_and_shows_ten(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _queue(capsys, "--from", CREW_DAY, "--to", CREW_DAY)
    names = [p["name"] for p in data["people"]]
    assert names == list(reversed(CREW))[:10] and data["more"] == 2
    assert data["people"][0]["evidence"] == "faces on 12 photos on one day"
    assert data["people"][-1]["evidence"] == "faces on 3 photos on one day"
    text = _run(capsys, "review", "with", "--from", CREW_DAY, "--to", CREW_DAY)
    assert "  and 2 more, on less evidence" in text.splitlines()


def test_no_number_stands_beside_a_name(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    """In the JSON a page would draw, a person's entry carries no number; and in the rows, the line with
    a name has nothing else on it."""
    _run(capsys, "people", "lives-in", "Per", "Bergen")
    outputs = [
        _queue(capsys, "--from", CREW_DAY, "--to", CREW_DAY),
        _queue(capsys, "--week", WEEK),
        json.loads(_run(capsys, "people", "city", "Bergen", "--trip", TRIP_DAY, "--json")),
    ]
    for data in outputs:
        for person in data["people"]:
            assert not any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in person.values())
            assert not re.search(r"\d", person["name"])
    names = {*CREW, "Kari Nordmann", "Ola Nordmann", "Per Hansen"}
    for args in (
        ("review", "with", "--from", CREW_DAY, "--to", CREW_DAY),
        ("review", "with", "--week", WEEK),
        ("people", "city", "Bergen", "--trip", TRIP_DAY),
    ):
        for row in _run(capsys, *args).splitlines():
            if any(name in row for name in names):
                assert not re.search(r"\d", row), row


# -- not with ------------------------------------------------------------------------------------------------


def test_not_with_stops_the_proposals_for_that_stretch(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _run(capsys, "people", "not-with", "Kari", "--from", "2026-06-10", "--to", "2026-06-10")
    [line] = _labelled(lb, "not-with")
    assert out == f"#{line['seq']} note  not-with: Kari Nordmann, 2026-06-10 to 2026-06-10\n"
    assert line["payload"]["extra"] == {"person": KARI_ID, "from": "2026-06-10", "to": "2026-06-10"}
    assert line["tier"] == 2 and line["source"] == "manual"
    kari = _asked(_queue(capsys, "--week", WEEK))["Kari Nordmann"]
    assert kari["days"] == ["2026-06-09"] and kari["evidence"] == "faces on 1 photo on one day"
    _run(capsys, "people", "not-with", "Kari", "--from", "2026-06-08", "--to", "2026-06-14")
    assert "Kari Nordmann" not in _asked(_queue(capsys, "--week", WEEK))
    assert "say the stretch" in _refused(capsys, "people", "not-with", "Kari", "--from", "2026-06-08")


# -- lives with ----------------------------------------------------------------------------------------------


def test_lives_with_at_home_is_not_asked_and_away_is(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    out = _run(capsys, "people", "lives-with", "Kari", "--from", "2026-01-01")
    [line] = _labelled(lb, "lives-with")
    assert out == f"#{line['seq']} note  lives-with: Kari Nordmann, from 2026-01-01\n"
    assert line["payload"]["extra"] == {"person": KARI_ID, "from": "2026-01-01"}
    kari = _asked(_queue(capsys, "--week", WEEK))["Kari Nordmann"]
    assert kari["days"] == [
        "2026-06-10"
    ]  # the cafe: away, so her face proposes; Tuesday at home is not asked
    assert kari["evidence"] == "faces on 1 photo on one day · invited to 'Lunch'"
    _run(capsys, "people", "lives-with", "Kari", "--until", "2026-06-08")  # she moved out on the 8th
    assert _asked(_queue(capsys, "--week", WEEK))["Kari Nordmann"]["days"] == ["2026-06-09", "2026-06-10"]
    relations = who_was_there.relations(lb)
    assert [(s.since, s.until) for s in relations.lives_with[KARI_ID]] == [("2026-01-01", "2026-06-08")]


def test_the_relation_notes_are_never_read_as_company(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(capsys, "people", "lives-with", "Kari", "--from", "2026-01-01")
    _run(capsys, "people", "not-with", "Ola", "--from", "2026-06-08", "--to", "2026-06-09")
    _run(capsys, "people", "lives-in", "Per", "Bergen")
    written = [*_labelled(lb, "lives-with"), *_labelled(lb, "not-with"), *_labelled(lb, "lives-in")]
    assert len(written) == 3
    for line in written:
        assert present.WITH.search(line["payload"]["text"]) is None
        assert presence.stated([line]) == []


# -- lives in, your people in a city -------------------------------------------------------------------------


def test_lives_in_and_a_journey_to_bergen_lists_per_as_not_yet_then_seen(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _run(capsys, "people", "lives-in", "Per", "Bergen", "--from", "2020-05-01")
    [line] = _labelled(lb, "lives-in")
    assert out == f"#{line['seq']} note  lives-in: Per Hansen, Bergen\n"
    assert line["payload"]["extra"] == {"person": PER_ID, "city": "Bergen", "from": "2020-05-01"}
    assert _run(capsys, "people", "city", "bergen").splitlines() == ["your people in bergen", "  Per Hansen"]
    data = json.loads(_run(capsys, "people", "city", "Bergen", "--trip", TRIP_DAY, "--json"))
    assert data["journey"] == "trip:2026-07-01:2026-07-03"
    assert data["people"] == [
        {"person": PER_ID, "name": "Per Hansen", "city": "Bergen", "line": line["id"], "seen": False}
    ]
    assert (
        _run(capsys, "people", "city", "Bergen", "--trip", TRIP_DAY).splitlines()[1]
        == "  Per Hansen  not yet"
    )
    # the journey's queue asks about him: his face, from the owner's camera, in Bergen
    per = _asked(_queue(capsys, "--journey", TRIP_DAY))["Per Hansen"]
    assert per["days"] == [TRIP_DAY] and per["evidence"] == "faces on 1 photo on one day"
    per_n = _number(capsys, "Per Hansen", "--journey", TRIP_DAY)
    _run(capsys, "review", "with", "--journey", TRIP_DAY, "--accept", per_n, "--days", TRIP_DAY)
    assert (
        _run(capsys, "people", "city", "Bergen", "--trip", TRIP_DAY).splitlines()[1] == "  Per Hansen  seen"
    )
    assert "Per Hansen" not in _asked(_queue(capsys, "--journey", TRIP_DAY))
    assert (
        _run(capsys, "people", "city", "Oslo").splitlines()[1].startswith("  nobody the record places there")
    )


# -- the answers ---------------------------------------------------------------------------------------------


def test_the_answers_write_through_the_acts(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    seq = lb.meta["seq"]
    kari = _number(capsys, "Kari Nordmann", "--week", WEEK)
    _run(capsys, "review", "with", "--week", WEEK, "--accept", kari, "--days", "2026-06-10")
    [one] = _labelled(lb, "with")
    assert one["payload"]["extra"] == {"person": KARI_ID} and _clock(one).date().isoformat() == "2026-06-10"
    kari = _number(capsys, "Kari Nordmann", "--week", WEEK)
    _run(capsys, "review", "with", "--week", WEEK, "--accept", kari)  # the whole stretch: the six days left
    assert len(_labelled(lb, "with")) == 7
    # the refusals come while Ola is still in the queue, so he has a number to give
    ola = _number(capsys, "Ola Nordmann", "--week", WEEK)
    both = _refused(capsys, "review", "with", "--week", WEEK, "--accept", ola, "--not", "Ola")
    assert "--accept and --not at once" in both
    assert "is not a day of" in _refused(
        capsys, "review", "with", "--week", WEEK, "--accept", ola, "--days", "2026-06-20"
    )
    _run(capsys, "review", "with", "--week", WEEK, "--not", "Ola")
    [refusal] = _labelled(lb, "not-with")
    assert refusal["payload"]["extra"] == {"person": OLA_ID, "from": "2026-06-08", "to": "2026-06-14"}
    assert _queue(capsys, "--week", WEEK)["people"] == []
    assert lb.meta["seq"] == seq + 8
    assert "--days goes with" in _refused(capsys, "review", "with", "--week", WEEK, "--days", "2026-06-10")
    assert "say one of" in _refused(capsys, "review", "with", "--week", WEEK, "--from", "2026-06-08")
    assert "go with `review with`" in _refused(capsys, "review", "person", "--week", WEEK)
    assert lb.meta["seq"] == seq + 8


def test_the_queue_refuses_a_stretch_longer_than_sixty_days(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    assert "longer than 60" in _refused(
        capsys, "review", "with", "--from", "2026-04-01", "--to", "2026-07-31"
    )


def test_review_alone_lists_the_kinds_and_not_with(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    from logbook.commands import review

    assert "with" not in review.KINDS
    assert "go with `review with`" in _refused(capsys, "review", "--week", WEEK)


# -- what the review found ---------------------------------------------------------------------------------


def test_a_stretch_day_with_no_stay_is_stated_at_noon(lb: Logbook) -> None:
    [day] = who_was_there.with_stretch(lb, "2026-05-20", "2026-05-20", ["Ola"], now=NOW)
    [item] = day.stated
    assert day.at is None and item.line is not None and item.line["at"] == utc("2026-05-20", "12:00")


def test_a_meet_call_is_read_as_meeting_notes_and_an_answered_day_leaves_no_evidence(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    ola = _asked(_queue(capsys, "--from", MEET_DAY, "--to", MEET_DAY))["Ola Nordmann"]
    assert ola["evidence"] == "in the meeting notes of 'Crew sync'" and ola["days"] == [MEET_DAY]
    _run(capsys, "with", MEET_DAY, "Ola")
    assert _queue(capsys, "--from", MEET_DAY, "--to", MEET_DAY)["people"] == []
    # Thursday's meeting notes were Ola's only evidence of the week: answered, he is not asked again
    _run(capsys, "with", "2026-06-11", "Ola")
    assert "Ola Nordmann" not in _asked(_queue(capsys, "--week", WEEK))


def test_seen_on_a_journey_is_the_with_modules_confirmed_company_too(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(capsys, "people", "lives-in", "Ola", "Bergen")
    _run(capsys, "people", "lives-in", "Per", "Bergen")
    rows = _run(capsys, "people", "city", "Bergen", "--trip", TRIP_DAY).splitlines()
    assert rows[1:] == ["  Ola Nordmann  seen", "  Per Hansen  not yet"]  # Ola came to dinner on the 3rd
    _run(capsys, "people", "lives-in", "Ola", "Oslo")  # the latest note is where he lives
    assert _run(capsys, "people", "city", "Bergen").splitlines()[1:] == ["  Per Hansen"]


def test_until_with_nothing_open_is_refused_and_ends_every_open_stretch(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = lb.meta["seq"]
    assert "no standing lives-with to end" in _refused(
        capsys, "people", "lives-with", "Kari", "--until", "2026-06-08"
    )
    assert lb.meta["seq"] == seq
    _run(capsys, "people", "lives-with", "Kari", "--from", "2025-01-01")
    _run(capsys, "people", "lives-with", "Kari", "--from", "2026-01-01")
    _run(capsys, "people", "lives-with", "Kari", "--until", "2026-06-08")
    spans = who_was_there.relations(lb).lives_with[KARI_ID]
    assert [(s.since, s.until) for s in spans] == [("2025-01-01", "2026-06-08"), ("2026-01-01", "2026-06-08")]


def test_a_retracted_relation_stands_no_more(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    _run(capsys, "people", "lives-with", "Kari", "--from", "2026-01-01")
    [line] = _labelled(lb, "lives-with")
    assert KARI_ID in who_was_there.relations_of([line]).lives_with
    assert who_was_there.relations_of([line], [line["id"]]).lives_with == {}
    _run(capsys, "repair", "retract", str(line["seq"]), "she never moved in")
    assert who_was_there.relations(lb).lives_with == {}
    assert _asked(_queue(capsys, "--week", WEEK))["Kari Nordmann"]["days"] == ["2026-06-09", "2026-06-10"]


def test_accept_takes_numbers_by_comma_and_the_other_kinds_options_are_refused(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = lb.meta["seq"]
    assert "--days goes with one --accept" in _refused(
        capsys, "review", "with", "--week", WEEK, "--accept", "1,2", "--days", "2026-06-10"
    )
    assert "--top: not here" in _refused(capsys, "review", "with", "--week", WEEK, "--top", "3")
    assert "--radius: not with `people city`" in _refused(capsys, "people", "city", "Oslo", "--radius", "5")
    assert "not both" in _refused(
        capsys, "with", "2026-06-12", "Ola", "--from", "2026-06-08", "--to", "2026-06-09"
    )
    assert lb.meta["seq"] == seq
    # Kari is proposed on the 10th and Ola on the 11th: a number is for someone the queue asks about
    days = ("--from", "2026-06-10", "--to", "2026-06-11")
    both = f"{_number(capsys, 'Kari Nordmann', *days)},{_number(capsys, 'Ola Nordmann', *days)}"
    _run(capsys, "review", "with", *days, "--accept", both)
    assert sorted(line["payload"]["extra"]["person"] for line in _labelled(lb, "with")) == sorted(
        [KARI_ID, KARI_ID, OLA_ID, OLA_ID]
    )


# -- the owner's answers to #351 -----------------------------------------------------------------------------

# the options `review with` takes; every other option of `review` is refused there
WITH_TAKES = {"-h", "--accept", "--json", "--journey", "--week", "--from", "--to", "--days", "--not"}


def _review_options() -> list[Any]:
    from logbook.commands.parser import build_parser

    root = build_parser()
    commands = next(a for a in root._actions if a.dest == "cmd")
    review = commands.choices["review"]  # type: ignore[union-attr]
    return [action for action in review._actions if action.option_strings]


def _given(action: Any) -> list[str]:
    """The words that give `action` on the command line, a value its type accepts."""
    if action.nargs == 0:
        return [action.option_strings[-1]]
    count = action.nargs if isinstance(action.nargs, int) else 1
    return [action.option_strings[-1], *(["1"] * count)]


def test_review_with_refuses_every_option_it_does_not_take(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = lb.meta["seq"]
    since = _refused(capsys, "review", "with", "--week", WEEK, "--since", "2026-06-01")
    assert "--since: not here" in since
    others = [a for a in _review_options() if not WITH_TAKES & set(a.option_strings)]
    assert {"--since", "--top", "--reject", "--say", "--unnamed", "--place"} <= {
        a.option_strings[-1] for a in others
    }
    for action in others:
        flag = action.option_strings[-1]
        err = _refused(capsys, "review", "with", "--week", WEEK, *_given(action))
        assert f"{flag}: not here" in err, (flag, err)
    # a value that is falsy is still given: `--top 0` is refused, not read as absent
    assert "--top: not here" in _refused(capsys, "review", "with", "--week", WEEK, "--top", "0")
    assert "--all-above: not here" in _refused(capsys, "review", "with", "--week", WEEK, "--all-above", "0")
    assert lb.meta["seq"] == seq


def test_people_city_takes_trip_and_journey_is_its_old_name_for_one_release(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(capsys, "people", "lives-in", "Per", "Bergen")
    new = _run(capsys, "people", "city", "Bergen", "--trip", TRIP_DAY)
    assert new.splitlines() == [
        "your people in Bergen, on journey trip:2026-07-01:2026-07-03",
        "  Per Hansen  not yet",
    ]
    cli.main(["people", "city", "Bergen", "--journey", TRIP_DAY])
    old = capsys.readouterr()
    assert old.out == new
    assert old.err.count("\n") == 1 and ". " not in old.err, old.err
    assert "--trip" in old.err and "--journey" in old.err
    assert "both" in _refused(capsys, "people", "city", "Bergen", "--trip", TRIP_DAY, "--journey", TRIP_DAY)
    # a journey the record does not hold: the refusal alone, one sentence, not the notice as well
    assert "--journey is now --trip" not in _refused(
        capsys, "people", "city", "Bergen", "--journey", "nonsense"
    )
    # --journey stays `people nearby`'s; --trip is `people city`'s alone
    assert "--trip goes with `people city`" in _refused(capsys, "people", "nearby", "--trip", TRIP_DAY)
    assert "--trip goes with `people city`" in _refused(capsys, "people", "mail", "--trip", TRIP_DAY)
    assert "--trip goes with `people city`" in _refused(
        capsys, "people", "lives-in", "Per", "Bergen", "--trip", TRIP_DAY
    )
    assert "--journey goes with `people nearby`" in _refused(
        capsys, "people", "lives-in", "Per", "Bergen", "--journey", TRIP_DAY
    )
    from logbook.commands.parser import build_parser

    commands = next(a for a in build_parser()._actions if a.dest == "cmd")
    people = commands.choices["people"]  # type: ignore[union-attr]
    helps = {a.option_strings[-1]: a.help for a in people._actions if a.option_strings}
    assert "city" not in helps["--journey"] and helps["--trip"].startswith("city: ")


def test_the_longest_stay_counts_waking_hours_only_from_day_start_to_midnight(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """Under a `day_start` of 06:00 the night after a day is the day's (to 06:00 next morning), but its
    hours after midnight are not waking hours: they never make the longest stay, and no line lands in
    them."""
    lb.set_meta(day_start="06:00")
    days = ["2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12"]
    found = who_was_there.with_stretch(lb, days[0], days[-1], ["Ola"], now=NOW)
    assert [d.day for d in found] == days
    for d in found:
        assert d.at is not None and "06:00" <= d.at < "24:00", (d.day, d.at)
    by_day = {_clock(line).date().isoformat(): _clock(line) for line in _labelled(lb, "with")}
    assert sorted(by_day) == days  # each on its own date, none after midnight
    # Wednesday: the evening at home, 18:30 to midnight, outlasts each half of the office split by lunch
    wednesday = by_day["2026-06-10"]
    assert 20 <= wednesday.hour < 22, wednesday  # the middle of the evening, never the night after
    days_of = review_with.reading.day_start.of(lb.meta)
    stays = review_with.reading.owner_track(lb, "2026-06-10", "2026-06-11").stays
    assert who_was_there.longest_stay("2026-06-10", stays, days_of, NOW) == wednesday.strftime("%H:%M")


def test_review_with_accept_takes_the_queues_numbers_and_refuses_a_name(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = lb.meta["seq"]
    rows = _run(capsys, "review", "with", "--week", WEEK).splitlines()
    # each person's number on a line of its own under them, never beside the name
    assert rows[1:9] == [
        "  Kari Nordmann",
        "      faces on 2 photos across 2 days · invited to 'Lunch'",
        "      on Tue 9 Jun, Wed 10 Jun",
        "      --accept 1",
        "  Ola Nordmann",
        "      in the meeting notes of 'Boat plans'",
        "      on Thu 11 Jun",
        "      --accept 2",
    ]
    assert rows[-1] == "  answer: --accept N[,N] (every day of it) · --accept N --days D,D · --not NAME"
    # in the JSON the number is the place in `people`, and no entry carries one
    assert [p["name"] for p in _queue(capsys, "--week", WEEK)["people"]] == ["Kari Nordmann", "Ola Nordmann"]
    name = _refused(capsys, "review", "with", "--week", WEEK, "--accept", "Kari")
    assert "takes the queue's numbers, not a name" in name and "--accept 1,3" in name
    assert "takes the queue's numbers" in _refused(
        capsys, "review", "with", "--week", WEEK, "--accept", "1,Ola"
    )
    assert "no person 3 in the queue" in _refused(capsys, "review", "with", "--week", WEEK, "--accept", "3")
    assert "numbered from 1" in _refused(capsys, "review", "with", "--week", WEEK, "--accept", "0")
    # the crew day shows ten and counts two more: a number past the ten says how to state them
    beyond = _refused(capsys, "review", "with", "--from", CREW_DAY, "--to", CREW_DAY, "--accept", "11")
    assert "shows 10" in beyond and "logbook with --from D1 --to D2 NAME" in beyond
    assert lb.meta["seq"] == seq
    out = _run(capsys, "review", "with", "--week", WEEK, "--accept", "2", "--days", "2026-06-11")
    [line] = _labelled(lb, "with")
    assert line["payload"]["extra"] == {"person": OLA_ID} and out.startswith(
        f"#{line['seq']} with Ola Nordmann"
    )
    # answered, Ola leaves the queue, and the numbers are the queue's as it now stands
    assert [p["name"] for p in _queue(capsys, "--week", WEEK)["people"]] == ["Kari Nordmann"]
    _run(capsys, "review", "with", "--week", WEEK, "--accept", "1", "--accept", "1")
    assert {line["payload"]["extra"]["person"] for line in _labelled(lb, "with")} == {OLA_ID, KARI_ID}
    assert _queue(capsys, "--week", WEEK)["people"] == []
