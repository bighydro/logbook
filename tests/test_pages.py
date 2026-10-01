"""`logbook show person|asset|place <name>`: the pages, read from the whole record. Synthetic Oslo
persona; nothing is written."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from persona import BOAT, KARI_ID, OLA_ID, persona_record

from logbook import cli


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(["show", *args])
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_run(capsys, *args, "--json"))
    return data


# -- person -------------------------------------------------------------------------------------------------


def test_a_person_page_is_the_arc_of_the_relationship(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    head = lb.meta["head"]
    data = _json(capsys, "person", "Ola Nordmann")
    assert data["page"] == "person" and data["id"] == OLA_ID and data["name"] == "Ola Nordmann"
    assert sorted(r["kind"] for r in data["refs"]) == ["email", "phone"]
    assert data["first_contact"] == "2026-06-11" and data["last_contact"] == "2026-06-16"
    assert data["days_together"] == {"2026": 3}
    assert set(data["places"]) >= {"Office", "aboard solvind"}
    assert data["commitments"] == {"open": [], "note": data["commitments"]["note"]}
    assert "commitment" in data["commitments"]["note"]
    stays = data["shared_stays"]
    assert len(stays) == 3 and stays[0]["start"] > stays[-1]["start"], "the last stays first"
    assert stays[0]["sources"] == ["calendar"] and stays[-1]["sources"] == ["transcript"]
    assert all(len(id_) == 36 for s in stays for id_ in s["lines"])
    assert lb.meta["head"] == head
    text = _run(capsys, "person", "Ola Nordmann")
    assert "Ola Nordmann" in text and "2026-06-11" in text and "2026-06-16" in text
    assert "2026  3 days" in text and "commitments" in text and "Office" in text


def test_a_first_name_resolves_when_it_is_unique_and_an_unknown_name_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch)
    assert _json(capsys, "person", "kari")["id"] == KARI_ID
    assert _json(capsys, "person", OLA_ID)["name"] == "Ola Nordmann"
    with pytest.raises(SystemExit) as e:
        cli.main(["show", "person", "Nordmann"])
    assert e.value.code == 2 and "Nordmann" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        cli.main(["show", "person", "Trude"])
    assert e.value.code == 2


def test_a_person_with_only_proposed_evidence_has_no_contact_yet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch)
    data = _json(capsys, "person", "Kari Nordmann")
    assert data["days_together"] == {"2026": 1} and data["last_contact"] == "2026-06-10"
    assert data["proposed"] == 1 and data["shared_stays"][0]["sources"] == ["calendar", "photo"]


# -- asset --------------------------------------------------------------------------------------------------


def test_an_asset_page_has_its_trips_nights_people_and_track(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch)
    data = _json(capsys, "asset", BOAT)
    assert (
        data["page"] == "asset"
        and data["id"] == BOAT
        and data["name"] == "Solvind"
        and data["kind"] == "yacht"
    )
    assert data["nights"] == 1
    [trip] = data["trips"]
    assert trip["id"] == "trip:2026-06-13:2026-06-13" and trip["asset"] == BOAT
    assert [p["id"] for p in data["people"]] == [OLA_ID]
    track = data["track"]
    assert track["points"] > 1000
    assert (track["stays"], track["moves"]) == (4, 3), "a week at the berth, out, back"
    assert 15_000 < track["distance_m"] < 25_000
    assert track["first"] == "2026-06-07T22:00:00Z" and track["last"].startswith("2026-06-14")
    assert len(track["lines"]) == 2
    text = _run(capsys, "asset", BOAT)
    assert (
        "Solvind" in text
        and "1 night" in text
        and "Ola Nordmann" in text
        and "km" in text
        and "AIS" not in text
    )


def test_an_asset_without_a_track_and_an_unknown_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    cli.main(["assets", "add", "kite", "--kind", "aircraft", "--name", "Kite"])
    capsys.readouterr()
    data = _json(capsys, "asset", "kite")
    assert data["track"] is None and data["trips"] == [] and data["nights"] == 0
    assert "no track" in _run(capsys, "asset", "kite")
    with pytest.raises(SystemExit) as e:
        cli.main(["show", "asset", "nobody"])
    assert e.value.code == 2 and "assets.json" in capsys.readouterr().err
    assert lb.meta["seq"] > 0


# -- place --------------------------------------------------------------------------------------------------


def test_a_place_page_has_visits_people_and_photos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch)
    data = _json(capsys, "place", "Office")
    assert data["page"] == "place" and data["name"] == "Office" and data["kind"] == "other"
    assert data["visits"] == 8 and 60 < data["hours"] < 70
    assert data["first"] == "2026-06-08" and data["last"] == "2026-06-20"
    assert data["by_year"] == {"2026": {"visits": 8, "hours": data["by_year"]["2026"]["hours"]}}
    assert [p["id"] for p in data["people"]] == [OLA_ID]
    assert data["photos"] == 1, "the Art photo was taken at the office"
    assert (
        len(data["last_visits"]) == 8 and data["last_visits"][0]["start"] > data["last_visits"][-1]["start"]
    )
    assert len(data["lines"]) == 16
    text = _run(capsys, "place", "Office")
    assert "Office" in text and "8 visits" in text and "Ola Nordmann" in text and "1 photo" in text
    assert _json(capsys, "place", "home")["photos"] == 0, "names match case aside"
    with pytest.raises(SystemExit) as e:
        cli.main(["show", "place", "Cabin"])
    assert e.value.code == 2 and "places.json" in capsys.readouterr().err


def test_a_day_is_still_the_default_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch)
    text = _run(capsys, "2026-06-10")
    assert text.startswith("2026-06-10") and "Lunch" in text
    with pytest.raises(SystemExit) as e:
        cli.main(["show", "person"])
    assert e.value.code == 2
