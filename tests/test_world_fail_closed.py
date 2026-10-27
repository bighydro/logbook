"""`export world` and the Library's `/world` fail closed (S9): a record whose policy does not name
`world` gets tier 1 alone, where the owner was, and the chapters (tier 2) stay home until the owner
writes the entry; `doctor` names it. Synthetic: Ines Nordmann of Oslo, who does not exist."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from world_record import CHAPTER, world_record

from logbook import cli
from logbook.contrib import doctor, world
from logbook.core import policy
from logbook.core.store import Logbook


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = world_record(tmp_path, monkeypatch)
    data = policy.read(lb.root)
    data.pop(policy.WORLD_DESTINATION, None)
    policy.policy_path(lb.root).write_text(json.dumps(data), encoding="utf-8")
    return lb


def test_without_a_world_entry_the_page_is_tier_1(lb: Logbook, tmp_path: Path) -> None:
    assert policy.world_ceiling(lb.root) == 1
    out = tmp_path / "World"
    cli.main(["export", "world", "--out", str(out)])
    bundle = world.bundle_of((out / world.FILE_NAME).read_text(encoding="utf-8"))
    assert bundle["tiers"] == [1] and bundle["chapters"] == []
    assert CHAPTER not in (out / world.FILE_NAME).read_text(encoding="utf-8")


def test_without_a_world_entry_tier_2_is_refused_naming_the_entry(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as e:
        cli.main(["export", "world", "--out", str(tmp_path / "x"), "--tier", "1,2"])
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "crossing.json" in err and '"world"' in err and not (tmp_path / "x").exists()


def test_doctor_names_the_world_entry(lb: Logbook) -> None:
    said = doctor.world_check(lb.root).detail
    assert "tier 1" in said and '"world"' in said and "crossing.json" in said, said
