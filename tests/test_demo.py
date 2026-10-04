"""`logbook demo --days N --seed S --out DIR`: a complete synthetic record of the Oslo persona,
invented in code, deterministic from the seed, that every reader of the record runs on."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.contrib import demo
from logbook.core.index import local_date
from logbook.core.store import Logbook

PHONE = re.compile(r"\+447700900\d{3}$")  # the UK reserved range, nothing else


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(list(args))
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> Any:
    return json.loads(_run(capsys, *args, "--json"))


def _generate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, days: int = 30, seed: int = 7) -> Logbook:
    root = tmp_path / "Demo"
    cli.main(["demo", "--days", str(days), "--seed", str(seed), "--out", str(root)])
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook(root)


@pytest.fixture(scope="module")
def record(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    """Thirty days, generated once for the readers' tests of this module."""
    root = tmp_path_factory.mktemp("demo") / "Demo"
    cli.main(["demo", "--days", "30", "--seed", "7", "--out", str(root)])
    return Logbook(root)


@pytest.fixture
def lb(record: Logbook, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    monkeypatch.setenv("LOGBOOK_HOME", str(record.root))
    return record


# -- the record ------------------------------------------------------------------------------------------


def test_the_record_verifies_and_holds_every_profile(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    out = _run(capsys, "verify")
    assert out.startswith("valid")
    stats = _json(capsys, "show", "stats")
    kinds = {k["kind"] for k in stats["kinds"]}
    assert kinds >= demo.KINDS, demo.KINDS - kinds
    schemas = {line["payload"]["schema"] for line in lb.lines()}
    assert schemas >= demo.SCHEMAS, demo.SCHEMAS - schemas
    assert stats["first"].startswith("2026-05-31"), "the resolutions, written the day before the first day"
    assert stats["last"].startswith("2026-06-30")
    assert stats["resolutions"]["entities"] >= 12
    assert stats["attachments"]["present"] >= 1, "a transcript's text is in the store"
    assert (lb.root / "places.json").is_file() and (lb.root / "assets.json").is_file()


def test_nothing_in_it_is_real(lb: Logbook) -> None:
    text = "\n".join(p.read_text(encoding="utf-8") for p in lb.files())
    for phone in re.findall(r"\+\d{8,}", text):
        assert PHONE.match(phone), phone
    for email in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text):  # a chat id is source-native
        assert email.endswith(("example.org", "@s.whatsapp.net", "@g.us")), email
    for mmsi in re.findall(r'"mmsi":\s*"(\d+)"', text):
        assert mmsi.startswith("970"), mmsi
    for registration in re.findall(r'"registration":\s*"([^"]+)"', text):
        assert registration.startswith("ZZ-"), registration
    for carrier in re.findall(r'"carrier":\s*"([^"]+)"', text):
        assert carrier == "XY", carrier


def test_the_same_seed_gives_the_same_head(tmp_path: Path) -> None:
    a = demo.generate(tmp_path / "a", days=3, seed=1)
    b = demo.generate(tmp_path / "b", days=3, seed=1)
    c = demo.generate(tmp_path / "c", days=3, seed=2)
    assert a.meta["head"] == b.meta["head"] and a.meta["seq"] == b.meta["seq"]
    assert a.meta["owner_id"] == b.meta["owner_id"]
    assert c.meta["head"] != a.meta["head"]
    for f in a.files():
        assert f.read_bytes() == (b.root / f.relative_to(a.root)).read_bytes()


def test_a_short_record_is_still_sensible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lb = _generate(tmp_path, monkeypatch, days=2, seed=3)
    seq, _head, errors = lb.verify()
    assert not errors and seq > 0
    days = {local_date(line["at"], demo.TZ) for line in lb.lines() if line["kind"] == "location"}
    assert days == {"2026-06-01", "2026-06-02"}


def test_refuses_an_existing_record(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    demo.generate(tmp_path / "Demo", days=1, seed=1)
    with pytest.raises(SystemExit) as e:
        cli.main(["demo", "--days", "1", "--out", str(tmp_path / "Demo")])
    assert e.value.code == 2
    assert "already a logbook" in capsys.readouterr().err


# -- the readers -----------------------------------------------------------------------------------------


def test_stats_health_has_a_row_per_day(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    days = _json(capsys, "show", "stats", "--health")["days"]
    assert len(days) >= 30
    for d in days[1:30]:
        assert d["sleep_h"] is not None and 5.5 <= d["sleep_h"] <= 9.5, d
        assert d["steps"] is not None and 2000 <= d["steps"] <= 20000, d
        assert d["resting_hr"] is not None and 45 <= d["resting_hr"] <= 70, d


def test_derive_stays_finds_the_nights(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    data = _json(capsys, "derive", "stays", "--since", "2026-06-01", "--until", "2026-06-30")
    nights = {n["day"]: n for n in data["nights"]}
    assert len(nights) == 30
    assert nights["2026-06-01"]["home"] and nights["2026-06-01"]["stay"]["place"] == "Home"
    assert nights["2026-06-06"]["stay"]["place"] == "Cabin" and not nights["2026-06-06"]["home"]
    assert nights["2026-06-09"]["stay"]["place"] is None and not nights["2026-06-09"]["in_transit"]
    assert nights["2026-06-17"]["stay"]["aboard"] == demo.BOAT
    assert sum(1 for n in nights.values() if n["in_transit"]) == 0
    assert demo.BOAT in data["subjects"]
    text = _run(capsys, "derive", "stays", "--day", "2026-06-03")
    assert "Office" in text and "Home" in text


def test_infer_flights_finds_the_calendar_flights(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    out = _run(capsys, "derive", "flights", "--dry-run")
    assert "from 4 calendar entries" in out and "1 already in the record" in out, out
    assert "3 flights" in out


def test_trips_are_the_cabin_zurich_the_boat_and_copenhagen(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _json(capsys, "show", "trips", "--year", "2026")
    cabin, zurich, boat, copenhagen = data["trips"]
    assert (cabin["id"], cabin["nights"], cabin["route"]) == ("trip:2026-06-06:2026-06-06", 1, ["Cabin"])
    assert (zurich["start"], zurich["until"], zurich["nights"]) == ("2026-06-08", "2026-06-11", 3)
    assert zurich["route"] == ["47.3769,8.5417 (Zurich)"], "a hotel 9 km from the airport, no place near"
    assert [f["number"] for f in zurich["flights_in"]] == ["561"]
    assert [f["number"] for f in zurich["flights_out"]] == ["562"]
    assert [p["name"] for p in zurich["people"]], "someone was met in Zürich"
    assert (boat["start"], boat["end"], boat["nights"], boat["asset"]) == (
        "2026-06-15",
        "2026-06-20",
        6,
        demo.BOAT,
    )
    assert (copenhagen["start"], copenhagen["until"], copenhagen["nights"]) == ("2026-06-25", "2026-06-27", 2)
    assert [f["number"] for f in copenhagen["flights_in"]] == ["571"]
    assert [f["number"] for f in copenhagen["flights_out"]] == ["572"]
    text = _run(capsys, "show", "trips")
    assert "Cabin" in text and "route 47.3769,8.5417 (Zurich)" in text


def test_rollup_countries_and_flights(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    countries = _json(capsys, "rollup", "countries")
    (year,) = countries["years"]
    by_code = {c["country"]: c["days"] for c in year["countries"]}
    assert by_code["NO"] >= 20 and by_code["CH"] == 3 and by_code["DK"] == 2, by_code
    assert year["in_transit"]["days"] == 0 and year["unknown"]["days"] == 0
    flights = _json(capsys, "rollup", "flights")
    (year,) = flights["years"]
    assert year["count"] == 4
    assert year["by_evidence"] == {"tracked": 2, "inferred": 1, "declared": 1}
    text = _run(capsys, "rollup", "flights")
    assert "OSL" in text and "ZRH" in text and "CPH" in text


def test_places_propose_ranks_the_unnamed_stays(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    data = _json(capsys, "setup", "places", "propose")
    proposals = data["proposals"]
    assert len(proposals) >= 3
    assert proposals[0]["hours"] >= proposals[-1]["hours"]
    assert any(p["aboard"] == demo.BOAT for p in proposals), "the anchorages are aboard"
    text = _run(capsys, "setup", "places", "propose", "--top", "3")
    assert "unnamed place" in text


def test_places_propose_reads_the_same_from_the_index_as_it_did_from_the_files(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """The before/after pin: `places propose` is served from the index's own columns (the owner's
    points, the evidence, the retractions) and clusters from there; its output on the demo record is
    byte for byte what the reading of every line of the window gave. The fixtures were written by
    the earlier code on this same record (thirty days, seed 7)."""
    fixtures = Path(__file__).parent / "fixtures" / "demo"
    expected = json.loads((fixtures / "places_propose.json").read_text(encoding="utf-8"))
    assert _json(capsys, "setup", "places", "propose") == expected
    text = (fixtures / "places_propose.txt").read_text(encoding="utf-8")
    assert _run(capsys, "setup", "places", "propose").splitlines() == text.splitlines()


def test_show_prints_a_day_and_the_keepers(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    text = _run(capsys, "show", "2026-06-08")
    assert "XY 561" in text or "561" in text
    keepers = _json(capsys, "show", "keepers")
    assert len(keepers["keepers"]) >= 3
    assert {k["lane"] for k in keepers["keepers"]} == {"memory", "art"}
