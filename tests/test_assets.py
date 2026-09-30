"""The asset registry (ADR 0018): `<root>/assets.json`, read and written by `logbook.assets`, and
`logbook assets list|add`. Every identifier here is synthetic: MMSI under MID 999 (allocated to no
country), icao24 in the unallocated 000000 block, registrations under the unassigned `ZZ` prefix."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import assets, cli
from logbook.assets import Asset, AssetError
from logbook.store import Logbook

YACHT = Asset(id="solvind", kind="yacht", name="Solvind", mmsi="999000001", registration="ZZ-LOG1")
PLANE = Asset(id="ln-zz1", kind="aircraft", name="the club's Cub", icao24="000a01", registration="ZZ-ZZ1")
CAR = Asset(id="volvo", kind="car", name="the old Volvo", registration="ZZ 00001")


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    return lb


# -- the file ------------------------------------------------------------------------------------


def test_a_record_without_the_file_has_no_assets(lb):
    assert assets.read(lb.root) == []
    assert not assets.assets_path(lb.root).exists()


def test_add_writes_assets_json_at_the_root_as_an_object_with_an_assets_list(lb):
    assets.add(lb.root, YACHT)
    path = lb.root / "assets.json"
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "assets": [
            {
                "id": "solvind",
                "kind": "yacht",
                "name": "Solvind",
                "mmsi": "999000001",
                "registration": "ZZ-LOG1",
            }
        ]
    }


def test_absent_identifiers_are_left_out_of_the_file_not_written_as_null(lb):
    assets.add(lb.root, CAR)
    (entry,) = json.loads(assets.assets_path(lb.root).read_text(encoding="utf-8"))["assets"]
    assert entry == {"id": "volvo", "kind": "car", "name": "the old Volvo", "registration": "ZZ 00001"}


def test_read_round_trips_every_asset_in_the_order_added(lb):
    for asset in (YACHT, PLANE, CAR):
        assets.add(lb.root, asset)
    assert assets.read(lb.root) == [YACHT, PLANE, CAR]


def test_add_keeps_keys_of_the_file_it_does_not_know(lb):
    assets.assets_path(lb.root).write_text(json.dumps({"assets": [], "note": "kept"}), encoding="utf-8")
    assets.add(lb.root, CAR)
    assert json.loads(assets.assets_path(lb.root).read_text(encoding="utf-8"))["note"] == "kept"


def test_add_refuses_a_second_asset_with_the_same_id(lb):
    assets.add(lb.root, YACHT)
    with pytest.raises(AssetError, match="solvind"):
        assets.add(lb.root, Asset(id="solvind", kind="car", name="another"))
    assert assets.read(lb.root) == [YACHT]


def test_add_refuses_a_second_asset_with_the_same_mmsi_or_icao24(lb):
    assets.add(lb.root, YACHT)
    assets.add(lb.root, PLANE)
    with pytest.raises(AssetError, match="999000001"):
        assets.add(lb.root, Asset(id="other", kind="yacht", name="Other", mmsi="999000001"))
    with pytest.raises(AssetError, match="000a01"):
        assets.add(lb.root, Asset(id="other", kind="aircraft", name="Other", icao24="000A01"))


@pytest.mark.parametrize("bad", ["", "Solvind", "sol vind", "-solvind", "sol/vind", "sølvind"])
def test_an_id_is_a_lower_case_token(bad):
    with pytest.raises(AssetError, match="id"):
        Asset(id=bad, kind="yacht", name="x").check()


@pytest.mark.parametrize("bad", ["boat", "Yacht", "", "plane"])
def test_kind_is_yacht_aircraft_or_car(bad):
    with pytest.raises(AssetError, match="kind"):
        Asset(id="x", kind=bad, name="x").check()


def test_name_is_required():
    with pytest.raises(AssetError, match="name"):
        Asset(id="x", kind="car", name="").check()


@pytest.mark.parametrize("bad", ["99900001", "9990000012", "99900000a", "999 000 001"])
def test_an_mmsi_is_nine_digits(bad):
    with pytest.raises(AssetError, match="mmsi"):
        Asset(id="x", kind="yacht", name="x", mmsi=bad).check()


@pytest.mark.parametrize("bad", ["00a01", "000a012", "000g01", "00-a01"])
def test_an_icao24_is_six_hex_digits(bad):
    with pytest.raises(AssetError, match="icao24"):
        Asset(id="x", kind="aircraft", name="x", icao24=bad).check()


def test_an_icao24_is_stored_in_lower_case():
    entry = {"id": "x", "kind": "aircraft", "name": "x", "icao24": "000A01"}
    assert Asset.from_json(entry).icao24 == "000a01"
    assert Asset(id="x", kind="aircraft", name="x", icao24="000A01").icao24 == "000a01"


def test_from_json_refuses_an_entry_that_is_not_an_object_or_lacks_a_field():
    with pytest.raises(AssetError):
        Asset.from_json(["solvind"])
    with pytest.raises(AssetError, match="kind"):
        Asset.from_json({"id": "solvind", "name": "Solvind"})
    with pytest.raises(AssetError, match="mmsi"):
        Asset.from_json({"id": "solvind", "kind": "yacht", "name": "Solvind", "mmsi": 999000001})


def test_a_file_that_is_not_a_registry_is_refused_naming_the_file(lb):
    path = assets.assets_path(lb.root)
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(AssetError, match=r"assets\.json"):
        assets.read(lb.root)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(AssetError, match=r"assets\.json"):
        assets.read(lb.root)


def test_by_mmsi_and_by_icao24_index_the_assets_that_carry_one():
    registry = [YACHT, PLANE, CAR]
    assert assets.by_mmsi(registry) == {"999000001": YACHT}
    assert assets.by_icao24(registry) == {"000a01": PLANE}


# -- the CLI -------------------------------------------------------------------------------------


def _assets(*args: str) -> None:
    cli.main(["assets", *args])


def test_assets_add_registers_an_asset_and_says_so(lb, capsys):
    _assets("add", "solvind", "--kind", "yacht", "--name", "Solvind", "--mmsi", "999000001")
    out = capsys.readouterr().out
    assert "solvind" in out and "yacht" in out and "999000001" in out
    assert assets.read(lb.root) == [Asset(id="solvind", kind="yacht", name="Solvind", mmsi="999000001")]


def test_assets_add_takes_every_identifier(lb):
    _assets(
        "add", "ln-zz1", "--kind", "aircraft", "--name", "the club's Cub",
        "--icao24", "000A01", "--registration", "ZZ-ZZ1",
    )  # fmt: skip
    assert assets.read(lb.root) == [PLANE]


def test_assets_list_prints_one_line_per_asset_in_the_order_registered(lb, capsys):
    for asset in (YACHT, PLANE, CAR):
        assets.add(lb.root, asset)
    _assets("list")
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3
    assert lines[0].startswith("solvind") and "yacht" in lines[0] and "mmsi 999000001" in lines[0]
    assert lines[1].startswith("ln-zz1") and "icao24 000a01" in lines[1] and "ZZ-ZZ1" in lines[1]
    assert lines[2].startswith("volvo") and "car" in lines[2] and "ZZ 00001" in lines[2]


def test_assets_list_with_nothing_registered_says_how_to_add_one(lb, capsys):
    _assets("list")
    out = capsys.readouterr().out
    assert "no assets" in out and "logbook assets add" in out


def test_assets_add_refuses_a_bad_asset_on_one_line_and_exits_2(lb, capsys):
    with pytest.raises(SystemExit) as e:
        _assets("add", "Solvind", "--kind", "yacht", "--name", "Solvind")
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith("assets: ") and "id" in err and len(err.splitlines()) == 1
    assert assets.read(lb.root) == []


def test_assets_add_refuses_a_duplicate_id_and_exits_2(lb, capsys):
    assets.add(lb.root, YACHT)
    with pytest.raises(SystemExit) as e:
        _assets("add", "solvind", "--kind", "car", "--name", "x")
    assert e.value.code == 2
    assert "solvind" in capsys.readouterr().err


def test_the_registry_is_outside_the_chain(lb):
    assets.add(lb.root, YACHT)
    seq, _head, errors = lb.verify()
    assert (seq, errors) == (0, [])
    assert not (lb.root / "logbook" / "assets.json").exists()
