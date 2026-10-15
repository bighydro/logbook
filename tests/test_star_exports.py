"""Stars travel with their lines (RFC 0041): `export share day` carries the stars standing on the
lines it carries, because a star is at its line's day and tier, and never a star whose line stays
home; `export trip-bundle` carries the stars on its photos and flights. The shared Saturday of
`shared_day.py` and the cabin weekend of `cabin.py`; nobody in either exists."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from shared_day import DAY, both

from logbook import cli
from logbook.core.store import Logbook


def _bundle_lines(bundle: Path) -> list[dict[str, Any]]:
    with zipfile.ZipFile(bundle) as zf:
        raw = zf.read("lines.jsonl").decode("utf-8")
    return [json.loads(s) for s in raw.splitlines() if s.strip()]


def _of(lb: Logbook, kind: str) -> list[dict[str, Any]]:
    return [line for line in lb.lines() if line["kind"] == kind]


def test_a_shared_day_carries_the_stars_on_the_lines_it_carries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ines, _ola = both(tmp_path, monkeypatch)
    [photo] = _of(ines, "photo")
    [note] = _of(ines, "note")
    first_fix = _of(ines, "location")[1]
    cli.main(["star", photo["id"], "--note", "late light"])
    cli.main(["star", note["id"]])
    cli.main(["star", first_fix["id"]])
    capsys.readouterr()
    [keeper] = _of(ines, "keeper")
    star_note, star_fix = _of(ines, "star")
    assert (keeper["tier"], star_note["tier"], star_fix["tier"]) == (1, 2, 1)

    tier1 = tmp_path / "tier1.zip"
    cli.main(["export", "share", "day", DAY, "--to", "ola", "--tier", "1", "--out", str(tier1)])
    ids = {line["id"] for line in _bundle_lines(tier1)}
    assert {keeper["id"], star_fix["id"], photo["id"], first_fix["id"]} <= ids
    assert star_note["id"] not in ids and note["id"] not in ids, "a tier-2 line's star stays home with it"

    tier2 = tmp_path / "tier2.zip"
    cli.main(["export", "share", "day", DAY, "--to", "ola", "--tier", "2", "--out", str(tier2)])
    lines = {line["id"]: line for line in _bundle_lines(tier2)}
    assert star_note["id"] in lines and note["id"] in lines
    assert lines[star_note["id"]] == star_note, "verbatim, so the receiver recomputes its hash"


def test_a_star_never_crosses_without_its_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Retract a starred line and its star stays home, whatever the star's own tier says; an
    unstarred line's star stays home too."""
    ines, _ola = both(tmp_path, monkeypatch)
    fixes = _of(ines, "location")
    cli.main(["star", fixes[1]["id"]])
    cli.main(["star", fixes[2]["id"]])
    cli.main(["repair", "retract", str(fixes[1]["seq"]), "a fix in the wrong place"])
    cli.main(["unstar", fixes[2]["id"]])
    capsys.readouterr()
    out = tmp_path / "page.zip"
    cli.main(["export", "share", "day", DAY, "--to", "ola", "--tier", "1", "--out", str(out)])
    kinds = [line["kind"] for line in _bundle_lines(out)]
    assert "star" not in kinds and "retraction" not in kinds


def test_a_trip_bundle_carries_the_stars_on_its_photos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from cabin import TRIP, ola_record

    ola = ola_record(tmp_path)
    monkeypatch.setenv("LOGBOOK_HOME", str(ola.root))
    photos = _of(ola, "photo")
    cli.main(["star", photos[0]["id"], "--note", "the shared one"])
    capsys.readouterr()
    [keeper] = _of(ola, "keeper")
    out = tmp_path / "bundle"
    cli.main(["export", "trip-bundle", TRIP, "--to", "ines", "--tier", "1,2", "--out", str(out)])
    entries = [json.loads(s) for s in (out / "entries.jsonl").read_text(encoding="utf-8").splitlines() if s]
    assert keeper in entries, "the photo's star crosses with it, verbatim"
    assert sorted(line["kind"] for line in entries) == ["keeper", "photo", "photo", "photo"]
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["kinds"] == ["flight", "keeper", "photo", "star"]


def test_export_crossing_carries_a_star_only_with_its_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """RFC 0041 rule 5 for main's generic crossing as well (`export crossing`, its signed-day gate
    lifted with `--unsigned`): a star crosses beside its line; the star of a line retracted since
    stays home, and `--kinds star` alone carries no star, since none has its line beside it."""
    ines, _ola = both(tmp_path, monkeypatch)
    fixes = _of(ines, "location")
    cli.main(["star", fixes[1]["id"]])
    cli.main(["star", fixes[2]["id"]])
    cli.main(["repair", "retract", str(fixes[1]["seq"]), "a fix in the wrong place"])
    capsys.readouterr()
    gone, kept = _of(ines, "star")
    window = ["--since", "2026-06-12T00:00:00Z", "--until", "2026-06-15T00:00:00Z", "--unsigned"]

    out = tmp_path / "crossing"
    cli.main(["export", "crossing", "--to", "ola", *window, "--tier", "1", "--out", str(out)])
    entries = {
        e["id"]: e for e in map(json.loads, (out / "entries.jsonl").read_text(encoding="utf-8").splitlines())
    }
    assert kept["id"] in entries and fixes[2]["id"] in entries
    assert gone["id"] not in entries and fixes[1]["id"] not in entries, (
        "a star never crosses without its line"
    )

    alone = tmp_path / "stars-alone"
    cli.main(
        ["export", "crossing", "--to", "ola", *window, "--tier", "1", "--kinds", "star", "--out", str(alone)]
    )
    assert (alone / "entries.jsonl").read_text(encoding="utf-8").strip() == ""
    capsys.readouterr()


def test_a_trip_bundle_exported_again_carries_the_star_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Main's crossing builds a bundle fresh and puts it in place of the folder (`--force` for one
    that is not a bundle): a star given a new note between two exports is in the second once, the
    standing one, and the bundle carries nothing of the first."""
    from cabin import TRIP, ola_record

    ola = ola_record(tmp_path)
    monkeypatch.setenv("LOGBOOK_HOME", str(ola.root))
    photo = _of(ola, "photo")[0]
    out = tmp_path / "bundle"
    cli.main(["star", photo["id"], "--note", "the shared one"])
    cli.main(["export", "trip-bundle", TRIP, "--to", "ines", "--tier", "1,2", "--out", str(out)])
    cli.main(["star", photo["id"], "--note", "the one for the wall"])
    cli.main(["export", "trip-bundle", TRIP, "--to", "ines", "--tier", "1,2", "--out", str(out), "--force"])
    capsys.readouterr()
    first, second = _of(ola, "keeper")
    assert second["payload"]["supersedes"] == first["id"]
    entries = [json.loads(s) for s in (out / "entries.jsonl").read_text(encoding="utf-8").splitlines() if s]
    assert [e["id"] for e in entries if e["kind"] == "keeper"] == [second["id"]]


def test_a_photo_s_star_never_crosses_without_its_photo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A photo's star is its `memory` keeper (rule 2), so rule 5 holds for it too: retract the photo
    and its keeper stays home from a shared day and from a crossing alike."""
    ines, _ola = both(tmp_path, monkeypatch)
    [photo] = _of(ines, "photo")
    cli.main(["star", photo["id"], "--note", "late light"])
    cli.main(["repair", "retract", str(photo["seq"]), "not this one"])
    capsys.readouterr()
    [keeper] = _of(ines, "keeper")
    page = tmp_path / "page.zip"
    cli.main(["export", "share", "day", DAY, "--to", "ola", "--tier", "1", "--out", str(page)])
    assert keeper["id"] not in {line["id"] for line in _bundle_lines(page)}
    out = tmp_path / "crossing"
    window = ["--since", "2026-06-12T00:00:00Z", "--until", "2026-06-15T00:00:00Z", "--unsigned"]
    cli.main(["export", "crossing", "--to", "ola", *window, "--tier", "1", "--out", str(out)])
    lines = (out / "entries.jsonl").read_text(encoding="utf-8").splitlines()
    assert keeper["id"] not in {json.loads(s)["id"] for s in lines if s}
    capsys.readouterr()


def test_a_trip_bundle_carries_the_star_of_a_photo_before_the_record_s_day_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Under a `day_start` of 06:00 (RFC 0036) a photo at 01:00 on the trip's first date is in the
    bundle's window, though its local day, and its star's, is the day before: the star crosses with it."""
    from cabin import TRIP, ola_record
    from persona import photo as photo_draft

    ola = ola_record(tmp_path)
    monkeypatch.setenv("LOGBOOK_HOME", str(ola.root))
    early = ola.append(**photo_draft("2026-06-11T23:00:00Z", (59.9139, 10.7522)))  # 01:00 in Oslo
    ola.set_meta(day_start="06:00")
    cli.main(["star", early["id"], "--note", "the night ferry"])
    capsys.readouterr()
    keeper = next(k for k in _of(ola, "keeper") if k["payload"]["photo"]["line"] == early["id"])
    out = tmp_path / "bundle"
    cli.main(["export", "trip-bundle", TRIP, "--to", "ines", "--tier", "1,2", "--out", str(out)])
    entries = [json.loads(s) for s in (out / "entries.jsonl").read_text(encoding="utf-8").splitlines() if s]
    ids = {e["id"] for e in entries}
    assert early["id"] in ids and keeper["id"] in ids


def test_a_trip_bundle_carries_the_star_on_a_flight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """RFC 0030's amendment: a flight of the trip crosses with its `star/v1` line, verbatim, and the
    manifest names the kind; a flight's star at a tier not asked for stays home with the flight."""
    from cabin import TRIP, ola_record
    from persona import flight

    ola = ola_record(tmp_path)
    monkeypatch.setenv("LOGBOOK_HOME", str(ola.root))
    hop = ola.append(
        **flight("2026-06-12", "123", "OSL", "BGO", "2026-06-12T06:00:00Z", "2026-06-12T06:55:00Z")
    )
    cli.main(["star", hop["id"], "--note", "the window seat"])
    capsys.readouterr()
    [star] = _of(ola, "star")
    assert star["tier"] == hop["tier"] == 1
    out = tmp_path / "bundle"
    cli.main(["export", "trip-bundle", TRIP, "--to", "ines", "--tier", "1", "--out", str(out)])
    entries = [json.loads(s) for s in (out / "entries.jsonl").read_text(encoding="utf-8").splitlines() if s]
    assert hop in entries and star in entries, "the flight and its star, verbatim"
