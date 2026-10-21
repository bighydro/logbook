"""The timeline's reader (`logbook.core.moments`, RFC 0043 §11-12) on the demo record: every zoom, a
moment's *during* window, proposed company never confirmed, the tiers held (no money slot through a
gate without tier 3), and the place classes counted apart."""

from __future__ import annotations

import contextlib
import io
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.core import moments, places
from logbook.core.store import Logbook

DAYS, SEED = 30, 7
OFFICE_DAY = "2026-06-12"  # a calendar entry, a mail thread, a message and a payment at the office
ABOARD_DAY = "2026-06-20"  # a whole day aboard Nordlys, Ola proposed by a face
COPENHAGEN_DAY = "2026-06-26"  # lunch with Freja: an attendee, a face, a note
ALL = (0, 1, 2, 3)
NO_MONEY = (0, 1, 2)  # a gate a tier-2 entry reads through


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    root = tmp_path_factory.mktemp("timeline") / "Demo"
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LOGBOOK_HOME", str(root))
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["demo", "--days", str(DAYS), "--seed", str(SEED), "--out", str(root)])
    return Logbook(root)


def _at(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def _moments(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [i for i in data["items"] if i["kind"] == "moment"]


def test_a_day_is_its_moments_and_the_moves_between_them(demo: Logbook) -> None:
    data = moments.read(demo, "day", OFFICE_DAY)
    assert data["zoom"] == "day" and data["week"] == "2026-W24"
    assert [i["kind"] for i in data["items"]][:3] == ["moment", "move", "move"]
    office = next(m for m in _moments(data) if m["place"] == "Office")
    assert office["span"] == "07:50\u201317:25" and office["named"] and office["class"] == "away"
    assert data["night"] == {"class": "home", "where": "Home"}
    assert [p["name"] for p in office["people"]["confirmed"]] == ["Per Hansen", "Liv Berg"]
    assert office["people"]["confirmed"][0]["because"] == ["invited"]
    assert [m["subject"] for m in office["during"]["mail"]] == ["Mooring for the week"]
    assert office["during"]["messages"][0] | {"lines": []} == {
        "with": "Ola Nordmann",
        "network": "whatsapp",
        "group": False,
        "agent": False,
        "sent": 0,
        "received": 1,
        "lines": [],
    }
    assert [t["merchant"] for t in office["money"]["paid"]] == ["Havnekiosken"]
    rows = list(moments.rows(data))
    assert any(r.strip().startswith("Office · 07:50\u201317:25 · Per Hansen, Liv Berg") for r in rows), rows


def test_what_passed_during_a_moment_lies_inside_its_window(demo: Logbook) -> None:
    """Placed by time: every line a moment lists as during it is inside the part of the stay on the
    day, and a line of the day outside every moment is in none of them."""
    data = moments.read(demo, "day", OFFICE_DAY)
    with demo.index() as idx:
        for m in _moments(data):
            start, end = _at(m["within_day"]["start"]), _at(m["within_day"]["end"])
            during = m["during"]
            ids = [i for c in during["messages"] for i in c["lines"]]
            ids += [i for t in during["mail"] for i in t["lines"]]
            ids += [
                x["line"]
                for kind in ("calls", "notes", "events", "agents", "recordings")
                for x in during[kind]
            ]
            for line_id in ids:
                line = idx.by_id(line_id)
                assert line is not None
                at = _at(str(line["at"]))
                until = _at(str(line["end"])) if line.get("end") else at
                assert at < end and until >= start, (m["place"], line_id)
    walked = next(m for m in _moments(data) if m["place"] == "59.9136,10.7527 near Home, 0.0 km")
    assert all(
        not walked["during"][kind] for kind in walked["during"]
    )  # the message on the walk is the move's


def test_a_proposed_person_is_never_confirmed_and_says_why(demo: Logbook) -> None:
    (aboard,) = _moments(moments.read(demo, "day", ABOARD_DAY))
    assert (
        aboard["place"] == "aboard Nordlys" and aboard["class"] == "aboard" and aboard["aboard"] == "nordlys"
    )
    assert aboard["people"]["confirmed"] == []
    assert [(p["name"], p["because"]) for p in aboard["people"]["proposed"]] == [
        ("Ola Nordmann", ["face on 1 photo"])
    ]
    assert "Ola Nordmann?" in moments.item_text(aboard)


def test_the_reasons_read_in_words() -> None:
    assert moments.because(
        ["attendee of Lunch", "face in A.HEIC", "face Ola in B.HEIC", "spoke in Call", "note says with Ola"]
    ) == ["invited", "spoke", "you said", "face on 2 photos"]
    assert moments.because(["attendee of Sail (all day)"]) == ["invited"]


def test_a_gate_without_tier_three_has_no_money_slot(demo: Logbook) -> None:
    held = moments.read(demo, "day", OFFICE_DAY, tiers=NO_MONEY)
    assert "money" not in held
    assert all("money" not in m for m in _moments(held))
    assert "Havnekiosken" not in "\n".join(moments.rows(held))
    whole = moments.read(demo, "day", OFFICE_DAY, tiers=ALL)
    assert "money" in whole and all("money" in m for m in _moments(whole))


def test_a_day_no_payment_source_covers_says_so_with_the_last_day_one_does(demo: Logbook) -> None:
    data = moments.read(demo, "day", "2026-07-15")
    assert data["money"]["covered"] is False
    assert data["money"]["said"] == "No payment source covers this day"
    with demo.index() as idx:
        span = idx.span("transaction")
    assert span is not None and data["money"]["last_covered"] == span[1]
    assert "No payment source covers this day; the last day one covers is" in "\n".join(moments.rows(data))
    assert moments.read(demo, "day", "2026-06-20")["money"]["covered"] is True


def test_a_week_is_a_line_per_day_with_its_night_and_moments(demo: Logbook) -> None:
    data = moments.read(demo, "week", "2026-W25")
    assert [d["day"] for d in data["days"]] == [f"2026-06-{n}" for n in range(15, 22)]
    assert [d["night"]["class"] for d in data["days"]][:6] == ["aboard"] * 6
    assert all(d["moments"] for d in data["days"])
    with pytest.raises(ValueError, match="week"):
        moments.read(demo, "week", "2026-W54")


def test_a_month_counts_its_nights_by_class_and_says_signed_or_open(demo: Logbook) -> None:
    data = moments.read(demo, "month", "2026-06")
    assert len(data["days"]) == 30 and data["signed"] == 0
    assert data["nights"] == {"home": 18, "aboard": 6, "away": 6}
    assert moments.counts_text(data["nights"]) == "home 18 · aboard 6 · away 6"
    assert sum(d["photos"] for d in data["days"]) == data["photos"] > 0
    assert {d["night"]["class"] for d in data["days"]} == {"home", "aboard", "away"}


def test_a_place_s_class_counts_apart(demo: Logbook, tmp_path: Path) -> None:
    """The Cabin given the class `family`: its night counts as the family's places, not away."""
    copy = tmp_path / "copy"
    import shutil

    shutil.copytree(demo.root, copy)
    lb = Logbook(copy)
    places.set_class(lb.root, "Cabin", "family")
    data = moments.read(lb, "month", "2026-06")
    assert data["nights"] == {"home": 18, "family": 1, "aboard": 6, "away": 5}
    assert moments.counts_text(data["nights"]) == "home 18 · the family's places 1 · aboard 6 · away 5"


def test_a_year_is_twelve_months_and_its_journeys_as_bands(demo: Logbook) -> None:
    data = moments.read(demo, "year", "2026")
    assert [m["month"] for m in data["months"]] == [f"2026-{n:02d}" for n in range(1, 13)]
    assert [(j["first"], j["last"]) for j in data["journeys"]] == [
        ("2026-06-06", "2026-06-06"),
        ("2026-06-08", "2026-06-10"),
        ("2026-06-15", "2026-06-20"),
        ("2026-06-25", "2026-06-26"),
    ]
    assert data["journeys"][2]["where"] == "aboard Nordlys"


def test_all_years_per_place_and_per_vessel_names_only(demo: Logbook) -> None:
    data = moments.read(demo, "life")
    by_place = {p["place"]: p for p in data["places"]}
    assert by_place["Office"]["people"] == ["Per Hansen", "Liv Berg"]
    assert moments.place_text(by_place["Cabin"]) == "Cabin · 1 visit since 2026"
    (vessel,) = data["vessels"]
    assert moments.vessel_text(vessel) == "aboard Nordlys · 6 nights on 3 passages"
    for row in [*data["places"], *data["vessels"]]:
        assert all(isinstance(n, str) and not re.search(r"\d", n) for n in row["people"])


def test_a_key_that_is_not_one_is_refused(demo: Logbook) -> None:
    for zoom, key in (("day", "2026-6-1"), ("month", "2026-13"), ("year", "26"), ("hour", "1")):
        with pytest.raises(ValueError):
            moments.read(demo, zoom, key)


@pytest.fixture(scope="module")
def sessions(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    """The shelves' record (sessions with Claude Code, the Claude apps and a Telegram bot, early March
    2026) with a synthetic track: the owner still at one spot from the evening of 28 February on."""
    import shelves_record

    with pytest.MonkeyPatch.context() as mp:
        lb = shelves_record.record(tmp_path_factory.mktemp("sessions"), mp)
    at = datetime(2026, 2, 28, 22, 0, tzinfo=UTC)
    while at < datetime(2026, 3, 4, tzinfo=UTC):
        stamp = at.strftime("%Y-%m-%dT%H:%M:%SZ")
        point = {"schema": "location/v1", "lat": 59.9139, "lon": 10.7522, "accuracy_m": 10}
        lb.append(stamp, "dawarich", "location", 1, {**point, "raw_id": f"dawarich:{stamp}"})
        at += timedelta(minutes=15)
    return lb


def test_a_session_with_an_agent_during_a_moment_keeps_the_machine_s_words_apart(sessions: Logbook) -> None:
    (moment,) = _moments(moments.read(sessions, "day", "2026-03-01"))
    (session,) = moment["during"]["agents"]
    assert (session["agent"], session["title"]) == ("Claude Code", "Passage planner for Solvind")
    assert session["owner"][0] == "Write a passage planner for Solvind. I'll test it on Saturday."
    assert session["machine"][0] == "I'll start with the tide tables. Can you send me the harbour list?"
    assert not set(session["owner"]) & set(session["machine"])
    bots = moment["during"]["messages"]
    assert bots and all(c["agent"] for c in bots)  # the Telegram bot's chats, marked as an agent's
    assert f"{len(bots) + 1} conversations" in moments.item_text(moment)  # the chats and the session
