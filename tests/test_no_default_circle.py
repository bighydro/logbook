"""A new record names no one it may send what was said to (the owner's decision, 21 Oct 2026; ADR
0016 amendment): `init` and `demo` write `policy/crossing.json` with the `mcp` door at tier 1 and
nothing else, `policy.read` gives the same for a record without the file, and a crossing to a
destination the file does not name is refused naming the file. A file the owner wrote is never
rewritten, by `init`, `demo` or any export's first write. Every name here is synthetic; the people
live in Oslo and do not exist."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.core import policy
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
SINCE, UNTIL = "2026-06-01T00:00:00Z", "2026-06-03T00:00:00Z"
NEW_RECORD = {"mcp": {"max_tier": 1}}


def _owners_file(*named: str) -> bytes:
    """A policy file as an owner writes it by hand: per-hansen at 2 and each of `named` at 2, on one line
    with no newline at the end, so a rewrite in the program's own layout would show."""
    entries = {"per-hansen": {"max_tier": 2}} | {name: {"max_tier": 2} for name in named}
    return json.dumps(entries, separators=(",", ":")).encode("utf-8")


def _put(root: Path, data: bytes) -> Path:
    path = policy.policy_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _above_tier_1(entries: dict[str, Any]) -> list[str]:
    return [name for name, entry in entries.items() if int(entry.get("max_tier", 0)) > 1]


def _demo(root: Path, capsys: pytest.CaptureFixture[str]) -> Logbook:
    cli.main(["demo", "--days", "2", "--out", str(root)])
    capsys.readouterr()
    return Logbook(root)


# -- what a new record names -------------------------------------------------------------------------------


def test_init_writes_a_policy_that_names_no_destination_above_tier_1(tmp_path: Path) -> None:
    lb = Logbook.init(tmp_path / "Logbook", TZ)
    written = json.loads(policy.policy_path(lb.root).read_text(encoding="utf-8"))
    assert written == NEW_RECORD
    assert _above_tier_1(written) == []


def test_demo_writes_a_policy_that_names_no_destination_above_tier_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = _demo(tmp_path / "Demo", capsys)
    written = json.loads(policy.policy_path(lb.root).read_text(encoding="utf-8"))
    assert written == NEW_RECORD
    assert _above_tier_1(written) == []


def test_read_without_the_file_names_no_destination_above_tier_1(tmp_path: Path) -> None:
    lb = Logbook.init(tmp_path / "Logbook", TZ)
    policy.policy_path(lb.root).unlink()  # a record made before ADR 0016
    found = policy.read(lb.root)
    assert found == NEW_RECORD
    assert _above_tier_1(found) == []
    assert not policy.policy_path(lb.root).exists(), "reading writes nothing"


def test_a_crossing_to_hermes_on_a_new_record_is_refused_naming_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = Logbook.init(tmp_path / "Logbook", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    before = policy.policy_path(lb.root).read_bytes()
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as e:
        cli.main(
            [
                "export",
                "crossing",
                "--to",
                "per-hansen",
                "--tier",
                "1",
                "--since",
                SINCE,
                "--until",
                UNTIL,
                "--out",
                str(out),
            ]
        )
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert str(policy.policy_path(lb.root)) in err and "'per-hansen'" in err
    assert Logbook(lb.root).meta["seq"] == 0, "no line appended"
    assert not out.exists()
    assert policy.policy_path(lb.root).read_bytes() == before


# -- a file the owner wrote is kept ------------------------------------------------------------------------


def test_init_keeps_a_file_that_names_hermes_byte_for_byte(tmp_path: Path) -> None:
    root = tmp_path / "Logbook"
    path = _put(root, _owners_file())
    Logbook.init(root, TZ)
    assert path.read_bytes() == _owners_file()
    assert policy.write_default(root) == path
    assert path.read_bytes() == _owners_file()


def test_demo_keeps_a_file_that_names_hermes_byte_for_byte(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "Demo"
    path = _put(root, _owners_file())
    _demo(root, capsys)
    assert path.read_bytes() == _owners_file()


@pytest.mark.parametrize(
    "args",
    [
        (
            "crossing",
            "--to",
            "per-hansen",
            "--tier",
            "1,2",
            "--since",
            SINCE,
            "--until",
            UNTIL,
            "--unsigned",
            "--out",
            "{out}",
        ),
        ("vault", "{out}"),
        ("site", "{out}"),
        ("world", "--out", "{out}"),
    ],
    ids=["crossing", "vault", "site", "world"],
)
def test_an_exports_first_write_keeps_a_file_that_names_hermes_byte_for_byte(
    args: tuple[str, ...],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lb = _demo(tmp_path / "Demo", capsys)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    path = _put(lb.root, _owners_file())
    seq = lb.meta["seq"]
    out = str(tmp_path / "out")
    cli.main(["export", *(a.replace("{out}", out) for a in args)])
    assert Logbook(lb.root).meta["seq"] == seq + 1, "the export ran and recorded its crossing"
    assert path.read_bytes() == _owners_file()


def test_a_shared_days_first_write_keeps_a_file_that_names_hermes_byte_for_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from shared_day import DAY, both

    ines, _ola = both(tmp_path, monkeypatch)
    path = _put(ines.root, _owners_file("ola"))
    seq = ines.meta["seq"]
    cli.main(["export", "share", "day", DAY, "--to", "ola", "--out", str(tmp_path / "day.zip")])
    capsys.readouterr()
    assert Logbook(ines.root).meta["seq"] == seq + 1
    assert path.read_bytes() == _owners_file("ola")


def test_a_trip_bundles_first_write_keeps_a_file_that_names_hermes_byte_for_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from cabin import TRIP, ola_record

    ola = ola_record(tmp_path)
    monkeypatch.setenv("LOGBOOK_HOME", str(ola.root))
    path = _put(ola.root, _owners_file("ines"))
    seq = ola.meta["seq"]
    cli.main(["export", "trip-bundle", TRIP, "--to", "ines", "--tier", "1,2", "--out", str(tmp_path / "b")])
    capsys.readouterr()
    assert Logbook(ola.root).meta["seq"] == seq + 1
    assert path.read_bytes() == _owners_file("ines")
