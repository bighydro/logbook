"""The shared trip (RFC 0030): `logbook export trip-bundle <trip> --to <member>` writes a
crossing-style package of one trip's days under `policy/crossing.json`; `logbook import trip-bundle
<folder>` writes its lines as `received`, never over the record's own; `logbook trip <id>` then
shows what each record saw. Two synthetic records of one cabin weekend (`tests/cabin.py`); nobody
in them exists."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from cabin import (
    BAKERY,
    CABIN,
    INES,
    KARI,
    OLA,
    PIXELS,
    PIXELS_SHA,
    SHARED_PHOTO,
    TRIP,
    ines_record,
    ola_record,
)

from logbook import cli
from logbook.contrib import trip_bundle
from logbook.core import crossing
from logbook.core.chain import compute_hash
from logbook.core.store import Logbook


@pytest.fixture
def ines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = ines_record(tmp_path)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    return lb


@pytest.fixture
def ola(tmp_path: Path) -> Logbook:
    return ola_record(tmp_path)


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(list(args))
    return capsys.readouterr().out


def _fails(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    with pytest.raises(SystemExit) as e:
        cli.main(list(args))
    assert e.value.code == 2
    return capsys.readouterr().err


def _lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(raw) for raw in path.read_text(encoding="utf-8").splitlines() if raw.strip()]


def _bundle(
    ola: Logbook,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *extra: str,
) -> tuple[Path, str]:
    """Ola's bundle of the weekend for Ines, tiers 1 and 2, under `tmp_path / "bundle"`, and what the
    export printed."""
    out = tmp_path / "bundle"
    monkeypatch.setenv("LOGBOOK_HOME", str(ola.root))
    cli.main(["export", "trip-bundle", TRIP, "--to", "ines", "--tier", "1,2", "--out", str(out), *extra])
    return out, capsys.readouterr().out


# -- export ------------------------------------------------------------------------------------------------


def test_the_bundle_is_a_crossing_package_of_the_trips_days(
    ola: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seq_before = ola.meta["seq"]
    out, text = _bundle(ola, tmp_path, monkeypatch, capsys)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == crossing.SCHEMA
    assert manifest["profile"] == trip_bundle.PROFILE
    assert (manifest["owner"], manifest["recipient"]) == (ola.meta["owner_id"], "ines")
    assert manifest["sender"] == {
        "id": ola.meta["owner_id"],
        "name": OLA["name"],
        "refs": [{"kind": "email", "value": OLA["email"]}, {"kind": "phone", "value": OLA["phone"]}],
    }
    assert manifest["trip"] == {"id": TRIP, "start": "2026-06-12", "end": "2026-06-13", "until": "2026-06-14"}
    assert manifest["tiers"] == [1, 2]
    assert manifest["policy"]["max_tier"] == 2
    assert manifest["attachments_included"] is False
    assert manifest["blobs"] == []
    # the entries: the photo lines of the trip's days and the flights, verbatim, nothing else
    entries = _lines(out / "entries.jsonl")
    assert sorted(line["kind"] for line in entries) == ["photo", "photo", "photo"]
    assert all(compute_hash(line) == line["hash"] for line in entries)
    assert {line["payload"]["raw_id"] for line in entries} >= {SHARED_PHOTO}
    assert hashlib.sha256((out / "entries.jsonl").read_bytes()).hexdigest() == manifest["entries_sha256"]
    # the derived rows: the stays away (never the home stay), the moves, the people with their refs
    share = json.loads((out / "trip.json").read_text(encoding="utf-8"))
    assert share["schema"] == trip_bundle.SCHEMA
    assert share["trip"]["id"] == TRIP
    # the bakery walk cuts the cabin stay in two: one night either side of it
    assert [s["place"] for s in share["stays"]] == ["Hytta", None, "Hytta"]
    hytta, bakery, again = share["stays"]
    assert (hytta["nights"], bakery["nights"], again["nights"]) == (1, 0, 1)
    assert abs(hytta["lat"] - CABIN[0]) < 0.002 and abs(bakery["lat"] - BAKERY[0]) < 0.002
    assert "near Hytta" in bakery["label"]
    assert all(m["kind"] == "move" for m in share["moves"]) and share["moves"]
    assert {p["name"] for p in share["people"]} == {INES["name"], KARI["name"]}
    kari = next(p for p in share["people"] if p["name"] == KARI["name"])
    assert {(r["kind"], r["value"]) for r in kari["refs"]} == {
        ("email", KARI["email"]),
        ("provider_id", f"immich:{KARI['face']}"),
    }
    assert kari["status"] == "confirmed" and kari["sources"] == ["calendar", "note", "photo"]
    assert share["photos"]["count"] == 3 and share["flights"] == []
    assert hashlib.sha256((out / "trip.json").read_bytes()).hexdigest() == manifest["trip_sha256"]
    # the overlay: the resolution lines that name the people, and nothing of the record's other people
    overlay = _lines(out / "resolution.jsonl")
    assert {line["payload"]["ref"]["value"] for line in overlay} == {
        INES["email"],
        KARI["email"],
        f"immich:{KARI['face']}",
    }
    assert not (out / "attachments").exists()
    # the crossing is in the chain (ADR 0016): one crossing/v1 line naming the trip
    assert ola.meta["seq"] == seq_before + 1
    line = ola.line_by_seq(ola.meta["seq"])
    assert line is not None and line["kind"] == "crossing"
    payload = line["payload"]
    assert payload["destination"] == "ines" and payload["extra"] == {
        "trip": TRIP,
        "profile": trip_bundle.PROFILE,
    }
    assert payload["package_sha256"] == hashlib.sha256((out / "manifest.json").read_bytes()).hexdigest()
    assert payload["counts"]["crossed"] == 3 and payload["counts"]["resolutions"] == 3
    assert f"ines: {TRIP}" in text and "3 lines cross" in text and "people: 2" in text


def test_pixels_cross_only_with_attachments(
    ola: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out, _text = _bundle(ola, tmp_path, monkeypatch, capsys, "--attachments")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["attachments_included"] is True
    assert [b["sha256"] for b in manifest["blobs"]] == [PIXELS_SHA]
    assert (out / "attachments" / PIXELS_SHA).read_bytes() == PIXELS


def test_tier_1_alone_holds_back_the_people_and_the_overlay(
    ola: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "bundle"
    monkeypatch.setenv("LOGBOOK_HOME", str(ola.root))
    text = _run(capsys, "export", "trip-bundle", TRIP, "--to", "ines", "--out", str(out))
    share = json.loads((out / "trip.json").read_text(encoding="utf-8"))
    assert share["people"] == [] and share["held_back"]["people"] == 2
    assert [s["place"] for s in share["stays"]] == ["Hytta", None, "Hytta"]
    assert len(_lines(out / "entries.jsonl")) == 3
    assert not (out / "resolution.jsonl").exists()
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["sender"] == {"id": ola.meta["owner_id"], "name": OLA["name"], "refs": []}
    assert "people: 0 (2 held back" in text


def test_the_ceiling_an_unknown_member_and_a_day_at_home_refuse(
    ola: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOGBOOK_HOME", str(ola.root))
    out = str(tmp_path / "bundle")
    err = _fails(capsys, "export", "trip-bundle", TRIP, "--to", "ines", "--tier", "1,2,3", "--out", out)
    assert "policy/crossing.json" in err.replace("\\", "/") and "max_tier 2" in err
    err = _fails(capsys, "export", "trip-bundle", TRIP, "--to", "nobody", "--out", out)
    assert "names no destination 'nobody'" in err
    err = _fails(capsys, "export", "trip-bundle", "2026-06-11", "--to", "ines", "--out", out)
    assert "the night was at home" in err
    err = _fails(capsys, "export", "trip-bundle", TRIP, "--out", out)
    assert "--to" in err
    assert not Path(out).exists()


def test_a_dry_run_writes_nothing(
    ola: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOGBOOK_HOME", str(ola.root))
    seq = ola.meta["seq"]
    out = tmp_path / "bundle"
    text = _run(
        capsys, "export", "trip-bundle", TRIP, "--to", "ines", "--tier", "1,2", "--out", str(out), "--dry-run"
    )
    assert "dry run" in text and "3 lines cross" in text
    assert not out.exists() and ola.meta["seq"] == seq


# -- import ------------------------------------------------------------------------------------------------


def test_import_writes_received_lines_and_never_over_the_records_own(
    ines: Logbook,
    ola: Logbook,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle, _text = _bundle(ola, tmp_path, monkeypatch, capsys)
    monkeypatch.setenv("LOGBOOK_HOME", str(ines.root))
    before = json.loads(_run(capsys, "show", "trips", "--json"))
    seq = ines.meta["seq"]
    text = _run(capsys, "import", "trip-bundle", str(bundle))
    assert "2 lines received" in text and "3 resolutions" in text and "1 kept as yours" in text
    assert ines.meta["seq"] == seq + 2 + 3 + 1  # the lines, the overlay, the page
    received = [line for line in ines.lines() if line["kind"] == trip_bundle.RECEIVED]
    assert len(received) == 6 and all(line["source"] == trip_bundle.RECEIVED for line in received)
    wrapped = [line for line in received if line["payload"]["schema"] == trip_bundle.RECEIVED_SCHEMA]
    assert (
        sorted(line["payload"]["line"]["kind"] for line in wrapped) == ["photo", "photo"] + ["resolution"] * 3
    )
    entries = {line["id"]: line for line in _lines(bundle / "entries.jsonl")}
    for line in wrapped:
        inner = line["payload"]["line"]
        assert line["payload"]["extra"]["from"] == ola.meta["owner_id"]
        assert line["payload"]["extra"]["sender"] == OLA["name"]
        assert (line["at"], line["tier"]) == (inner["at"], inner["tier"])
        assert compute_hash(inner) == inner["hash"]
        if inner["kind"] == "photo":
            assert inner == entries[inner["id"]]
            assert line["payload"]["raw_id"] == inner["payload"]["raw_id"]
    assert SHARED_PHOTO not in {line["payload"]["raw_id"] for line in wrapped}  # Ines's own line stands
    page = next(line for line in received if line["payload"]["schema"] == trip_bundle.SCHEMA)
    assert (
        page["payload"]["raw_id"]
        == f"{trip_bundle.PAGE_RAW_ID}{json.loads((bundle / 'manifest.json').read_text())['bundle_id']}"
    )
    assert page["payload"]["trip"]["id"] == TRIP and page["tier"] == 2
    # a second import of the same bundle writes nothing
    seq = ines.meta["seq"]
    text = _run(capsys, "import", "trip-bundle", str(bundle))
    assert "0 lines received" in text and "received before" in text and ines.meta["seq"] == seq
    # the record's own readers are unmoved: received lines are nobody's photos and nobody's names
    assert json.loads(_run(capsys, "show", "trips", "--json")) == before
    day = _run(capsys, "show", "2026-06-13")
    assert f"from {OLA['name']}" in day and "photo" in day


def test_import_refuses_your_own_bundle_a_tampered_one_and_a_folder_that_is_none(
    ines: Logbook,
    ola: Logbook,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle, _text = _bundle(ola, tmp_path, monkeypatch, capsys)
    seq = ola.meta["seq"]
    err = _fails(capsys, "import", "trip-bundle", str(bundle))
    assert "your own record" in err and ola.meta["seq"] == seq
    monkeypatch.setenv("LOGBOOK_HOME", str(ines.root))
    seq = ines.meta["seq"]
    err = _fails(capsys, "import", "trip-bundle", str(tmp_path))
    assert "manifest.json" in err
    entries = bundle / "entries.jsonl"
    entries.write_bytes(entries.read_bytes().replace(b'"library": "immich"', b'"library": "photos"'))
    err = _fails(capsys, "import", "trip-bundle", str(bundle))
    assert "entries.jsonl" in err and "digest" in err
    assert ines.meta["seq"] == seq


def test_pixels_received_land_in_the_store(
    ines: Logbook,
    ola: Logbook,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle, _text = _bundle(ola, tmp_path, monkeypatch, capsys, "--attachments")
    monkeypatch.setenv("LOGBOOK_HOME", str(ines.root))
    text = _run(capsys, "import", "trip-bundle", str(bundle))
    assert "1 attachment" in text
    assert (ines.root / "attachments" / PIXELS_SHA).read_bytes() == PIXELS


# -- the merged page ---------------------------------------------------------------------------------------


def test_the_trip_page_shows_what_each_record_saw(
    ines: Logbook,
    ola: Logbook,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle, _text = _bundle(ola, tmp_path, monkeypatch, capsys)
    monkeypatch.setenv("LOGBOOK_HOME", str(ines.root))
    assert json.loads(_run(capsys, "show", "trip", TRIP, "--json"))["shared"] == []
    _run(capsys, "import", "trip-bundle", str(bundle))
    data = json.loads(_run(capsys, "show", "trip", TRIP, "--json"))
    (share,) = data["shared"]
    assert share["from"] == {"id": ola.meta["owner_id"], "name": OLA["name"]}
    assert share["trip"]["id"] == TRIP and share["photos"] == 2
    people = {p["name"]: p for p in share["people"]}
    assert people["you"]["yours"] == "owner" and people["you"]["theirs"] == "confirmed (calendar)"
    assert people["you"]["seen_only_by"] is None
    assert people[OLA["name"]]["yours"] == "confirmed (calendar)" and people[OLA["name"]]["theirs"] == "owner"
    assert (
        people[KARI["name"]]["yours"] is None
        and people[KARI["name"]]["theirs"] == "confirmed (calendar, note, photo)"
    )
    assert people[KARI["name"]]["seen_only_by"] == OLA["name"]
    cabin, bakery = share["places"]
    assert (cabin["label"], cabin["theirs"], cabin["seen_only_by"]) == ("Cabin", "Hytta", None)
    assert (cabin["nights"], cabin["their_nights"]) == (2, 2)
    assert (
        bakery["label"] is None and "near Hytta" in bakery["theirs"] and bakery["seen_only_by"] == OLA["name"]
    )
    text = _run(capsys, "show", "trip", TRIP)
    assert f"shared with {OLA['name']}" in text
    assert "seen only by" in text and f"{KARI['name']}" in text and "Hytta" in text
    html = tmp_path / "trip.html"
    _run(capsys, "show", "trip", TRIP, "--html", str(html))
    page = html.read_text(encoding="utf-8")
    assert "<h2>Shared</h2>" in page and KARI["name"] in page and "seen only by" in page


def test_a_page_of_another_trip_is_not_on_this_one(
    ines: Logbook,
    ola: Logbook,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle, _text = _bundle(ola, tmp_path, monkeypatch, capsys)
    share_file = bundle / "trip.json"
    share = json.loads(share_file.read_text(encoding="utf-8"))
    july = {
        "id": "trip:2026-07-03:2026-07-04",
        "start": "2026-07-03",
        "end": "2026-07-04",
        "until": "2026-07-05",
    }
    share["trip"].update(july)
    raw = (json.dumps(share, indent=2, sort_keys=True) + "\n").encode("utf-8")
    share_file.write_bytes(raw)
    manifest_file = bundle / "manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["trip_sha256"] = hashlib.sha256(raw).hexdigest()
    manifest_file.write_bytes((json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    monkeypatch.setenv("LOGBOOK_HOME", str(ines.root))
    _run(capsys, "import", "trip-bundle", str(bundle))
    assert json.loads(_run(capsys, "show", "trip", TRIP, "--json"))["shared"] == []
