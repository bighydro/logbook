"""keeper/v1 (RFC 0024): `logbook infer keepers` turns favourites and the Art album into keeper
lines, `logbook keepers` lists them, and a day's hero photos are its keepers. Synthetic persona."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from persona import persona_record

from logbook import cli, keepers
from logbook.adapters import immich
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main([*args])
    return capsys.readouterr().out


def _keepers(lb: Logbook) -> list[dict[str, Any]]:
    return [line for line in lb.lines() if line["kind"] == "keeper"]


def test_infer_keepers_writes_a_memory_per_favourite_and_an_art_per_album_photo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    seq = lb.meta["seq"]
    out = _run(capsys, "infer", "keepers", "--dry-run")
    assert "4 keepers" in out and "nothing written" in out and lb.meta["seq"] == seq
    out = _run(capsys, "infer", "keepers")
    assert "4 new keepers" in out
    found = _keepers(lb)
    assert len(found) == 4 and lb.meta["seq"] == seq + 4
    by_lane: dict[str, list[dict[str, Any]]] = {}
    for line in found:
        by_lane.setdefault(line["payload"]["lane"], []).append(line)
    assert len(by_lane["memory"]) == 3 and len(by_lane["art"]) == 1
    art = by_lane["art"][0]
    photos = {line["id"]: line for line in lb.lines() if line["kind"] == "photo"}
    photo = photos[art["payload"]["photo"]["line"]]
    assert photo["payload"]["extra"]["album"] == "Art"
    assert (art["source"], art["kind"], art["tier"], art["at"], art["end"]) == (
        "keeper-inference",
        "keeper",
        1,
        photo["at"],
        None,
    )
    assert art["payload"] == {
        "schema": "keeper/v1",
        "raw_id": f"{photo['id']}:art",
        "photo": {
            "line": photo["id"],
            "asset_id": photo["payload"]["asset_id"],
            "library": "immich",
            "file_name": photo["payload"]["file_name"],
        },
        "at": photo["at"],
        "lane": "art",
        "source": "immich",
    }
    assert all(line["payload"]["source"] == "immich" for line in found)
    out = _run(capsys, "infer", "keepers")
    assert "0 new keepers" in out and "4 already" in out, "a re-run appends nothing"
    assert lb.meta["seq"] == seq + 4
    assert lb.verify()[2] == []


def test_apple_photos_marks_read_as_ios_photos_and_albums_may_be_a_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from persona import photo

    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    both = photo("2026-06-01T10:00:00Z", library="apple-photos")
    both["payload"]["favorite"] = True  # apple-photos writes the marks at the payload's top
    both["payload"]["albums"] = ["Holiday", "art"]
    neither = photo("2026-06-01T11:00:00Z", library="apple-photos")
    neither["payload"]["albums"] = ["Holiday"]
    lb.append_many([both, neither])
    _run(capsys, "infer", "keepers")
    found = _keepers(lb)
    assert sorted(line["payload"]["lane"] for line in found) == ["art", "memory"]
    assert {line["payload"]["source"] for line in found} == {"ios-photos"}
    assert {line["payload"]["photo"]["line"] for line in found} == {next(lb.lines())["id"]}


def test_a_retracted_keeper_is_never_written_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    _run(capsys, "infer", "keepers")
    art = next(line for line in _keepers(lb) if line["payload"]["lane"] == "art")
    lb.retract(art["seq"], "not art after all")
    seq = lb.meta["seq"]
    out = _run(capsys, "infer", "keepers")
    assert "0 new keepers" in out and lb.meta["seq"] == seq
    data = json.loads(_run(capsys, "keepers", "--json"))
    assert len(data["keepers"]) == 3 and all(k["lane"] == "memory" for k in data["keepers"])


def test_keepers_lists_them_by_day_and_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    assert "no keepers" in _run(capsys, "keepers")
    _run(capsys, "infer", "keepers")
    text = _run(capsys, "keepers")
    assert text.count("memory") == 3 and text.count("art") == 1 and "IMG_" in text
    assert "2026-06-10" in text and "2026-06-16" in text
    data = json.loads(_run(capsys, "keepers", "--since", "2026-06-13", "--json"))
    assert [k["day"] for k in data["keepers"]] == ["2026-06-13", "2026-06-16"]
    assert data["keepers"][0]["lane"] == "memory" and data["keepers"][0]["photo"]["file_name"].startswith(
        "IMG_"
    )
    assert len(data["keepers"][0]["line"]) == 36 and len(data["keepers"][0]["photo"]["line"]) == 36
    data = json.loads(_run(capsys, "keepers", "--lane", "art", "--json"))
    assert [k["day"] for k in data["keepers"]] == ["2026-06-11"]
    data = json.loads(_run(capsys, "keepers", "--until", "2026-06-10", "--json"))
    assert [k["day"] for k in data["keepers"]] == ["2026-06-10"]
    with pytest.raises(SystemExit):
        cli.main(["keepers", "--lane", "stars"])
    assert lb.meta["head"] == lb.meta["head"]


def test_a_days_hero_photos_are_its_keepers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch)
    text = _run(capsys, "show", "2026-06-10")
    assert "hero" not in text
    _run(capsys, "infer", "keepers")
    lines = _run(capsys, "show", "2026-06-10").splitlines()
    assert lines[0] == "2026-06-10"
    assert lines[1].strip().startswith("hero") and "IMG_101030.HEIC" in lines[1]
    assert any("keeper" in line and "memory" in line and "IMG_101030.HEIC" in line for line in lines[2:])
    lines = _run(capsys, "show", "2026-06-11").splitlines()
    assert "art" in lines[1] and "hero" in lines[1]


def test_the_immich_adapter_keeps_the_favourite_flag_under_extra() -> None:
    asset = {
        "id": "a1",
        "originalFileName": "IMG_1.HEIC",
        "type": "IMAGE",
        "isFavorite": True,
        "people": [],
        "checksum": "c",
        "originalPath": "/p",
    }
    assert immich._payload(asset, {})["extra"]["favorite"] is True
    assert (
        "favorite" not in immich._payload({k: v for k, v in asset.items() if k != "isFavorite"}, {})["extra"]
    )


def test_the_profile_is_written_down() -> None:
    rfc = (ROOT / "rfcs" / "0024-keeper-v1.md").read_text(encoding="utf-8")
    assert "keeper/v1" in rfc and "memory" in rfc and "art" in rfc
    assert "0024" in (ROOT / "rfcs" / "README.md").read_text(encoding="utf-8")
    assert keepers.SCHEMA == "keeper/v1" and keepers.LANES == ("memory", "art")
