"""`logbook export --day DAY --out DIR` is a crossing like every other export (the owner's decision after
the stranger test of 26 October): the README promises that a page leaves "to a place you name, and your
record keeps a line that says it left". The folder holds tier 1 unless `--tier` asks for more, and one
`crossing/v1` line (RFC 0011) names it: destination `folder`, the folder's last part, the tiers, the kinds
and how many lines, the digest of what was written. `--days` is one run and one line. Synthetic lines."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
DAY = "2026-03-02"


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    for at, kind, tier, payload in (
        ("2026-03-02T07:30:00Z", "location", 1, {"schema": "location/v1", "lat": 59.91, "lon": 10.75}),
        ("2026-03-02T08:00:00Z", "event", 1, {"schema": "event/v1", "title": "Standup"}),
        ("2026-03-02T19:00:00Z", "note", 2, {"schema": "note/v1", "text": "a synthetic note"}),
        ("2026-03-02T20:00:00Z", "health", 3, {"schema": "health-sample/v1", "metric": "steps", "value": 9}),
        ("2026-03-03T09:00:00Z", "location", 1, {"schema": "location/v1", "lat": 59.92, "lon": 10.74}),
    ):
        lb.append(at=at, source="manual" if kind == "note" else "sim", kind=kind, tier=tier, payload=payload)
    return lb


def _export(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(["export", *args])
    return capsys.readouterr().out


def _crossings(lb: Logbook) -> list[dict[str, Any]]:
    return [line for line in Logbook(lb.root).lines() if line["kind"] == "crossing"]


def _digest(files: dict[str, bytes]) -> str:
    whole = hashlib.sha256()
    for rel in sorted(files):
        whole.update(f"{hashlib.sha256(files[rel]).hexdigest()}  {rel}\n".encode())
    return whole.hexdigest()


def test_export_day_writes_tier_1_and_records_the_folder(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    head = Logbook(lb.root).meta["head"]
    out = tmp_path / "For Kari"
    said = _export(capsys, "--day", DAY, "--out", str(out))
    package = json.loads((out / "package.json").read_text(encoding="utf-8"))
    assert [e["kind"] for e in package["entries"]] == ["location", "event"], "tier 1 unless --tier"
    [line] = _crossings(lb)
    assert (line["source"], line["tier"], line["at"] == line["recorded_at"]) == ("logbook", 1, True)
    p = line["payload"]
    assert p["schema"] == "crossing/v1" and p["destination"] == "folder"
    assert p["tiers"] == [1] and p["logbook_head"] == head
    assert p["window"] == {"from": "2026-03-01T23:00:00Z", "to": "2026-03-02T23:00:00Z"}
    assert p["counts"]["logged"] == 4 and p["counts"]["crossed"] == 2 and p["counts"]["held_back"] == 2
    assert p["counts"]["by_kind"] == {"event": 1, "location": 1}
    assert p["extra"]["folder"] == "For Kari", "the path's last part, never the whole path"
    assert p["extra"]["kinds"] == ["event", "location"] and p["extra"]["lines"] == 2
    assert str(tmp_path) not in json.dumps(line), "no path of this machine in the chain"
    assert p["package_sha256"] == _digest({"package.json": (out / "package.json").read_bytes()})
    assert "recorded as" in said and "crossing/v1" in said
    assert Logbook(lb.root).verify()[2] == [], "the chain verifies with the line in it"


def _policy(lb: Logbook, entries: dict[str, Any]) -> None:
    path = lb.root / "policy" / "crossing.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries), encoding="utf-8")


def test_no_folder_entry_is_tier_1_only(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The desk (28 October): the ceiling is the policy's, as for every export (ADR 0016), never `--tier`.
    With no `folder` entry it is tier 1, and `--tier 1,2` asks above it: refused, nothing written."""
    with pytest.raises(SystemExit) as e:
        cli.main(["export", "--day", DAY, "--out", str(tmp_path / "x"), "--tier", "1,2"])
    err = capsys.readouterr().err
    assert e.value.code == 2 and "max_tier 1" in err and '"folder"' in err
    assert not (tmp_path / "x").exists() and _crossings(lb) == []


def test_an_entry_at_2_and_tier_3_is_refused_in_one_sentence_naming_the_entry(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _policy(lb, {"mcp": {"max_tier": 1}, "folder": {"max_tier": 2}})
    with pytest.raises(SystemExit) as e:
        cli.main(["export", "--day", DAY, "--out", str(tmp_path / "x"), "--tier", "3"])
    err = capsys.readouterr().err.strip()
    assert e.value.code == 2 and err.count("\n") == 0 and err.count(". ") == 0, err
    assert '"folder"' in err and "max_tier 2" in err and "crossing.json" in err, err
    assert not (tmp_path / "x").exists() and _crossings(lb) == []


def test_an_entry_sets_the_ceiling_and_tier_only_lowers_it(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _policy(lb, {"mcp": {"max_tier": 1}, "folder": {"max_tier": 2}})
    _export(capsys, "--day", DAY, "--out", str(tmp_path / "up-to-2"))
    package = json.loads((tmp_path / "up-to-2" / "package.json").read_text(encoding="utf-8"))
    assert [e["tier"] for e in package["entries"]] == [1, 1, 2], "the entry's ceiling, no --tier"
    _export(capsys, "--day", DAY, "--out", str(tmp_path / "lowered"), "--tier", "1")
    package = json.loads((tmp_path / "lowered" / "package.json").read_text(encoding="utf-8"))
    assert [e["tier"] for e in package["entries"]] == [1, 1], "--tier lowers it"
    first, second = _crossings(lb)
    assert first["payload"]["tiers"] == [1, 2] and first["payload"]["policy"]["max_tier"] == 2
    assert second["payload"]["tiers"] == [1] and second["payload"]["policy"]["max_tier"] == 2


def test_export_day_takes_the_tiers_asked_for(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _policy(lb, {"mcp": {"max_tier": 1}, "folder": {"max_tier": 3}})
    out = tmp_path / "all"
    _export(capsys, "--day", DAY, "--out", str(out), "--tier", "1,2,3")
    package = json.loads((out / "package.json").read_text(encoding="utf-8"))
    assert [e["tier"] for e in package["entries"]] == [1, 1, 2, 3]
    [line] = _crossings(lb)
    assert line["payload"]["tiers"] == [1, 2, 3] and line["payload"]["counts"]["by_tier"] == {
        "1": 2,
        "2": 1,
        "3": 1,
    }


def test_export_days_is_one_run_and_one_line(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "week"
    _export(capsys, "--days", "2026-03-01", "2026-03-03", "--out", str(out))
    [line] = _crossings(lb)
    p = line["payload"]
    assert p["extra"]["folder"] == "week" and p["extra"]["days"] == ["2026-03-02", "2026-03-03"]
    assert p["window"] == {"from": "2026-02-28T23:00:00Z", "to": "2026-03-03T23:00:00Z"}
    files = {
        f"{d}/package.json": (out / d / "package.json").read_bytes() for d in ("2026-03-02", "2026-03-03")
    }
    assert p["package_sha256"] == _digest(files) and p["counts"]["crossed"] == 3


def test_an_export_that_writes_no_folder_records_nothing(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The review: `--days` over days with no line wrote no folder and still appended a line."""
    said = _export(capsys, "--days", "2026-01-01", "2026-01-03", "--out", str(tmp_path / "o"))
    assert not (tmp_path / "o").exists() and _crossings(lb) == []
    assert "nothing is recorded" in said


def test_a_bad_tier_writes_nothing(lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as e:
        cli.main(["export", "--day", DAY, "--out", str(tmp_path / "x"), "--tier", "2"])
    assert e.value.code == 2 and "--tier" in capsys.readouterr().err
    assert not (tmp_path / "x").exists() and _crossings(lb) == []
