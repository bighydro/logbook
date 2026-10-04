"""`logbook backup DEST [--keep N] [--verify]`, `backup list DEST` and `backup restore SNAPSHOT TARGET`
on a synthetic record of the Oslo persona, who does not exist. A snapshot is the record's files and
nothing else — never `index.sqlite`, `inbox/` or `state/` — under `DEST/<owner_id>/<timestamp>/`; a
file the previous snapshot already holds unchanged is a hard link to it; the copy is verified and its
head must be the live head. Nothing here touches a real folder: every path is under `tmp_path`."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from logbook import backup, cli
from logbook.core.store import Logbook

PLACES = {"Home": {"lat": 59.9139, "lon": 10.7522, "radius_m": 120, "kind": "home"}}
ASSETS = {"assets": [{"id": "solvind", "kind": "yacht", "name": "Solvind", "mmsi": "970123456"}]}
STAMPS = [
    datetime(2026, 6, 2, 7, 15, tzinfo=UTC),
    datetime(2026, 6, 3, 7, 15, tzinfo=UTC),
    datetime(2026, 6, 4, 7, 15, tzinfo=UTC),
    datetime(2026, 6, 5, 7, 15, tzinfo=UTC),
]


def _note(lb: Logbook, day: str, text: str) -> Path:
    path = lb.root / "notes" / day[:4] / f"{day}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _line(lb: Logbook, at: str, text: str) -> None:
    lb.append(at, "manual", "note", 2, {"schema": "note/v1", "text": text})


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """A record with two months of lines, an attachment, a note, places, assets, a current index,
    an inbox copy and a sync watermark; `LOGBOOK_HOME` points at it."""
    root = tmp_path / "Records" / "Logbook"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    monkeypatch.delenv("OneDrive", raising=False)
    lb = Logbook.init(root, "Europe/Oslo")
    _line(lb, "2026-05-30T10:00:00Z", "the marina, Solvind's sails checked")
    _line(lb, "2026-06-01T07:00:00Z", "coffee with Kari")
    lb.attach(b"a transcript that is not real\n")
    _note(lb, "2026-06-01", "# Monday\n\ncoffee with Kari\n")
    (root / "places.json").write_text(json.dumps(PLACES, indent=2) + "\n", encoding="utf-8")
    (root / "assets.json").write_text(json.dumps(ASSETS, indent=2) + "\n", encoding="utf-8")
    with lb.index():  # built, so the snapshot has something to leave out
        pass
    (root / "inbox" / "takeout.zip").write_bytes(b"PK\x05\x06 not a real archive")
    (root / "state").mkdir()
    (root / "state" / "immich.json").write_text('{"since": "2026-06-01T00:00:00Z"}\n', encoding="utf-8")
    assert (root / "index.sqlite").exists()
    return lb


@pytest.fixture
def dest(tmp_path: Path) -> Path:
    return tmp_path / "Backups"


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[datetime]:
    """`backup.now()` reads the next stamp of this list, so two snapshots never share a name by chance."""
    stamps = list(STAMPS)
    monkeypatch.setattr(backup, "now", lambda: stamps.pop(0))
    return stamps


def _cli(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    try:
        cli.main(["backup", *args])
    except SystemExit as e:
        captured = capsys.readouterr()
        return int(e.code or 0), captured.out, captured.err
    captured = capsys.readouterr()
    return 0, captured.out, captured.err


def _snapshots(dest: Path, owner: str) -> list[Path]:
    return sorted(p for p in (dest / owner).iterdir() if not p.name.startswith("."))


def _files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def _same_file(a: Path, b: Path) -> bool:
    sa, sb = os.stat(a), os.stat(b)
    return (sa.st_dev, sa.st_ino) == (sb.st_dev, sb.st_ino)


def _links_work(folder: Path) -> bool:
    folder.mkdir(parents=True, exist_ok=True)
    a, b = folder / "a", folder / "b"
    a.write_bytes(b"x")
    try:
        os.link(a, b)
    except OSError:
        return False
    return _same_file(a, b)


# -- what a snapshot holds -----------------------------------------------------------------------------------


def test_a_snapshot_is_the_record_and_nothing_else(lb: Logbook, dest: Path, clock: list[datetime]) -> None:
    owner = lb.meta["owner_id"]
    result = backup.snapshot(lb, dest)
    [snap] = _snapshots(dest, owner)
    assert snap.name == "2026-06-02T071500Z"
    assert result.path == snap
    digest = next(p.name for p in (lb.root / "attachments").iterdir())
    assert _files(snap) == {
        "logbook.json",
        "logbook/2026/05.jsonl",
        "logbook/2026/06.jsonl",
        "policy/crossing.json",
        "policy/import.json",
        "policy/owner.json",
        "places.json",
        "assets.json",
        f"attachments/{digest}",
        "notes/2026/2026-06-01.md",
    }
    for rel in _files(snap):
        assert (snap / rel).read_bytes() == (lb.root / rel).read_bytes(), rel
    assert result.head == lb.meta["head"] and result.seq == 2
    assert result.copied == 10 and result.linked == 0
    assert result.bytes == sum((lb.root / rel).stat().st_size for rel in _files(snap))
    assert not list((dest / owner).glob(".*")), "no partial directory is left behind"


def test_the_snapshot_verifies_and_its_head_is_the_live_head(
    lb: Logbook, dest: Path, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    status, out, _err = _cli(capsys, str(dest))
    assert status == 0
    head = lb.meta["head"]
    assert f"head {head}" in out and "2 lines" in out
    assert "2026-06-02T071500Z" in out and "10 copied" in out
    [snap] = _snapshots(dest, lb.meta["owner_id"])
    seq, verified_head, errors = Logbook(snap).verify()
    assert (seq, verified_head, errors) == (2, head, [])


def test_the_snapshot_never_holds_the_index_the_inbox_or_the_watermarks(
    lb: Logbook, dest: Path, clock: list[datetime]
) -> None:
    result = backup.snapshot(lb, dest)
    names = _files(result.path)
    assert not any(n.startswith(("inbox/", "state/", "index")) for n in names)
    assert (lb.root / "index.sqlite").exists(), "the live index is untouched"


# -- the second snapshot: hard links for what did not change -------------------------------------------------


def test_an_unchanged_file_is_a_hard_link_to_the_previous_snapshot(
    lb: Logbook, dest: Path, clock: list[datetime], tmp_path: Path
) -> None:
    if not _links_work(tmp_path / "probe"):
        pytest.skip("no hard links on this filesystem")
    first = backup.snapshot(lb, dest)
    _line(lb, "2026-06-02T07:00:00Z", "a third line, in June")
    second = backup.snapshot(lb, dest)
    assert second.path.name == "2026-06-03T071500Z"
    assert second.linked_to == first.path
    changed = {"logbook.json", "logbook/2026/06.jsonl"}
    for rel in _files(second.path):
        if rel in changed:
            assert not _same_file(first.path / rel, second.path / rel), rel
            assert (second.path / rel).read_bytes() == (lb.root / rel).read_bytes()
        else:
            assert _same_file(first.path / rel, second.path / rel), rel
    assert second.copied == 2 and second.linked == 8
    assert second.copied_bytes == sum((lb.root / rel).stat().st_size for rel in changed)
    assert second.head == lb.meta["head"] and second.seq == 3
    assert (first.path / "logbook.json").read_bytes() != (second.path / "logbook.json").read_bytes()
    assert Logbook(first.path).verify()[:2] == (2, first.head), "the first snapshot is as it was"


def test_a_file_the_previous_snapshot_lacks_is_copied(lb: Logbook, dest: Path, clock: list[datetime]) -> None:
    backup.snapshot(lb, dest)
    _note(lb, "2026-06-02", "# Tuesday\n")
    second = backup.snapshot(lb, dest)
    assert (second.path / "notes" / "2026" / "2026-06-02.md").read_text(encoding="utf-8") == "# Tuesday\n"
    assert second.copied == 1


def test_when_the_filesystem_refuses_links_the_file_is_copied(
    lb: Logbook, dest: Path, clock: list[datetime], monkeypatch: pytest.MonkeyPatch
) -> None:
    backup.snapshot(lb, dest)

    def refuse(src: object, dst: object, **_: object) -> None:
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(backup.os, "link", refuse)
    second = backup.snapshot(lb, dest)
    assert second.copied == 10 and second.linked == 0
    assert _files(second.path) == _files(second.linked_to or second.path)


def test_two_snapshots_in_one_second_get_distinct_names(
    lb: Logbook, dest: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backup, "now", lambda: STAMPS[0])
    first = backup.snapshot(lb, dest)
    second = backup.snapshot(lb, dest)
    assert first.path.name == "2026-06-02T071500Z" and second.path.name == "2026-06-02T071500Z-2"


# -- a copy that does not verify is not kept -----------------------------------------------------------------


def test_a_record_that_does_not_verify_leaves_no_snapshot(
    lb: Logbook, dest: Path, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    month = lb.root / "logbook" / "2026" / "06.jsonl"
    text = month.read_text(encoding="utf-8")
    month.write_text(text.replace("coffee with Kari", "coffee with Ola"), encoding="utf-8")
    status, _out, err = _cli(capsys, str(dest))
    assert status == 1
    assert "hash does not recompute" in err and "nothing kept" in err
    assert not (dest / lb.meta["owner_id"]).exists() or _snapshots(dest, lb.meta["owner_id"]) == []
    assert not list(dest.rglob(".*partial*")), "the partial copy is removed"


def test_a_record_appended_during_the_copy_is_reported_and_not_kept(
    lb: Logbook, dest: Path, clock: list[datetime], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A line appended between the read of logbook.json and the copy of its month file: the files
    say one head, logbook.json another, so the copy does not verify and the owner is told to run again."""
    original = backup.copy_file

    def copy_then_append(src: Path, dst: Path) -> None:
        original(src, dst)
        if src.name == "logbook.json":
            _line(lb, "2026-06-02T08:00:00Z", "appended while the backup ran")

    monkeypatch.setattr(backup, "copy_file", copy_then_append)
    with pytest.raises(backup.BackupError, match=r"changed while|does not verify"):
        backup.snapshot(lb, dest)
    assert _snapshots(dest, lb.meta["owner_id"]) == []


# -- --keep --------------------------------------------------------------------------------------------------


def test_keep_prunes_the_oldest_snapshots_after_the_new_one_is_verified(
    lb: Logbook, dest: Path, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    owner = lb.meta["owner_id"]
    for _ in range(3):
        assert _cli(capsys, str(dest))[0] == 0
    assert [p.name for p in _snapshots(dest, owner)] == [
        "2026-06-02T071500Z",
        "2026-06-03T071500Z",
        "2026-06-04T071500Z",
    ]
    status, out, _err = _cli(capsys, str(dest), "--keep", "2")
    assert status == 0
    assert [p.name for p in _snapshots(dest, owner)] == ["2026-06-04T071500Z", "2026-06-05T071500Z"]
    assert "pruned 2026-06-02T071500Z, 2026-06-03T071500Z" in out and "kept 2" in out
    for snap in _snapshots(dest, owner):
        assert Logbook(snap).verify()[2] == [], "a pruned link leaves the survivors whole"


def test_keep_never_prunes_another_owners_snapshots(
    lb: Logbook, dest: Path, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    other = dest / "019cadd3-6bc0-7dcd-9133-000000000099" / "2026-01-01T000000Z"
    other.mkdir(parents=True)
    (other / "logbook.json").write_text("{}", encoding="utf-8")
    assert _cli(capsys, str(dest), "--keep", "1")[0] == 0
    assert (other / "logbook.json").exists()


def test_keep_takes_a_positive_number(
    lb: Logbook, dest: Path, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    status, _out, err = _cli(capsys, str(dest), "--keep", "0")
    assert status == 2 and "--keep" in err
    assert not dest.exists()


# -- --verify: the attachments too ---------------------------------------------------------------------------


def test_verify_checks_every_attachment_in_the_copy_against_its_name(
    lb: Logbook, dest: Path, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    status, out, _err = _cli(capsys, str(dest), "--verify")
    assert status == 0 and "1 attachment" in out and "match" in out
    [stored] = list((lb.root / "attachments").iterdir())
    stored.write_bytes(b"not the bytes the name says\n")
    status, out, err = _cli(capsys, str(dest), "--verify")
    assert status == 1
    assert f"attachments/{stored.name}" in err and "nothing kept" in err
    assert len(_snapshots(dest, lb.meta["owner_id"])) == 1
    status, _out, _err = _cli(capsys, str(dest))
    assert status == 0, "without --verify the chain is what is checked; the chain is intact"


# -- refusals ------------------------------------------------------------------------------------------------


def test_a_destination_inside_the_record_is_refused(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    for inside in (lb.root, lb.root / "backups", lb.root / "inbox" / "b"):
        status, _out, err = _cli(capsys, str(inside))
        assert status == 2, inside
        assert "inside the record" in err
        assert not (lb.root / "backups").exists()


def test_a_destination_under_a_sync_client_folder_is_refused(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for parts, service in (
        (("Dropbox", "Backups"), "Dropbox"),
        (("Library", "Mobile Documents", "com~apple~CloudDocs", "Backups"), "iCloud Drive"),
        (("OneDrive - Example Org", "Backups"), "OneDrive"),
        (("Google Drive", "My Drive", "Backups"), "Google Drive"),
    ):
        folder = tmp_path.joinpath(*parts)
        status, _out, err = _cli(capsys, str(folder))
        assert status == 2, parts
        assert service in err and "sync client" in err
        assert not folder.exists()


def test_a_destination_the_onedrive_variable_names_is_refused(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cloud = tmp_path / "Cloud"
    cloud.mkdir()
    monkeypatch.setenv("OneDrive", str(cloud))
    status, _out, err = _cli(capsys, str(cloud / "Backups"))
    assert status == 2 and "OneDrive" in err


def test_a_destination_that_is_a_file_is_refused(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = tmp_path / "backups.txt"
    file.write_text("x", encoding="utf-8")
    status, _out, err = _cli(capsys, str(file))
    assert status == 2 and "not a directory" in err


def test_a_logbook_of_another_format_is_refused_naming_migrate(
    lb: Logbook, dest: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    meta = lb.meta
    meta["format"] = "logbook/0.1"
    lb._save_meta(meta)
    status, _out, err = _cli(capsys, str(dest))
    assert status == 2 and "logbook migrate" in err
    assert not dest.exists()


# -- backup list ---------------------------------------------------------------------------------------------


def test_list_shows_each_snapshot_with_its_lines_head_and_size(
    lb: Logbook, dest: Path, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    first = backup.snapshot(lb, dest)
    _line(lb, "2026-06-02T07:00:00Z", "a third line")
    second = backup.snapshot(lb, dest)
    (dest / lb.meta["owner_id"] / ".2026-06-09T071500Z.partial").mkdir()  # a crash mid-copy
    status, out, _err = _cli(capsys, "list", str(dest))
    assert status == 0
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert lines[0] == lb.meta["owner_id"]
    assert len(lines) == 3, out
    assert lines[1].split()[0] == "2026-06-02T071500Z" and f"head {first.head[:12]}" in lines[1]
    assert "2 lines" in lines[1]
    assert lines[2].split()[0] == "2026-06-03T071500Z" and f"head {second.head[:12]}" in lines[2]
    assert "3 lines" in lines[2]
    assert "partial" not in out
    first_size, second_size = (backup.human(s.bytes) for s in (first, second))
    assert first_size in lines[1] and second_size in lines[2]
    new = f"{backup.human(second.copied_bytes)} new"
    assert new in lines[2], "the bytes not shared, by a hard link, with an earlier snapshot"


def test_list_of_an_empty_or_missing_destination_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status, out, _err = _cli(capsys, "list", str(tmp_path / "nowhere"))
    assert status == 0 and "no snapshots" in out
    (tmp_path / "empty").mkdir()
    status, out, _err = _cli(capsys, "list", str(tmp_path / "empty"))
    assert status == 0 and "no snapshots" in out


def test_list_needs_no_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "none"))
    status, out, _err = _cli(capsys, "list", str(tmp_path / "Backups"))
    assert status == 0 and "no snapshots" in out


def test_list_reads_the_snapshots_as_data_when_one_is_broken(
    lb: Logbook, dest: Path, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    backup.snapshot(lb, dest)
    broken = dest / lb.meta["owner_id"] / "2026-06-03T071500Z"
    broken.mkdir()
    (broken / "logbook.json").write_text("not json", encoding="utf-8")
    status, out, _err = _cli(capsys, "list", str(dest))
    assert status == 0
    assert "2026-06-03T071500Z" in out and "logbook.json" in out and "not" in out


# -- backup restore ------------------------------------------------------------------------------------------


def test_restore_copies_a_snapshot_back_and_verifies_it(
    lb: Logbook, dest: Path, clock: list[datetime], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snap = backup.snapshot(lb, dest)
    target = tmp_path / "Restored" / "Logbook"
    status, out, _err = _cli(capsys, "restore", str(snap.path), str(target))
    assert status == 0
    assert f"head {snap.head}" in out and "2 lines" in out and str(target) in out
    assert _files(target) == _files(snap.path)
    for rel in _files(target):
        assert (target / rel).read_bytes() == (snap.path / rel).read_bytes()
        assert not _same_file(target / rel, snap.path / rel), f"{rel}: a copy, never a link into the backup"
    assert Logbook(target).verify() == (2, snap.head, [])
    assert not (target / "index.sqlite").exists(), "the next reader builds it"


def test_restore_never_writes_into_a_folder_that_holds_anything(
    lb: Logbook, dest: Path, clock: list[datetime], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snap = backup.snapshot(lb, dest)
    status, _out, err = _cli(capsys, "restore", str(snap.path), str(lb.root))
    assert status == 2 and "not empty" in err
    assert Logbook(lb.root).verify()[2] == []
    occupied = tmp_path / "Occupied"
    occupied.mkdir()
    (occupied / "keep.txt").write_text("mine", encoding="utf-8")
    status, _out, err = _cli(capsys, "restore", str(snap.path), str(occupied))
    assert status == 2 and "not empty" in err
    assert _files(occupied) == {"keep.txt"}
    empty = tmp_path / "Empty"
    empty.mkdir()
    assert _cli(capsys, "restore", str(snap.path), str(empty))[0] == 0, "an empty folder is fine"


def test_restore_refuses_a_target_under_a_sync_client_and_a_code_checkout(
    lb: Logbook, dest: Path, clock: list[datetime], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snap = backup.snapshot(lb, dest)
    status, _out, err = _cli(capsys, "restore", str(snap.path), str(tmp_path / "Dropbox" / "Logbook"))
    assert status == 2 and "Dropbox" in err
    checkout = tmp_path / "logbook"
    checkout.mkdir()
    (checkout / "pyproject.toml").write_text("", encoding="utf-8")
    status, _out, err = _cli(capsys, "restore", str(snap.path), str(checkout))
    assert status == 2 and "not empty" in err, "a checkout is never empty"
    assert _files(checkout) == {"pyproject.toml"}


def test_restore_refuses_what_is_not_a_snapshot(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status, _out, err = _cli(capsys, "restore", str(tmp_path / "nowhere"), str(tmp_path / "T"))
    assert status == 2 and "not a snapshot" in err
    assert not (tmp_path / "T").exists()


def test_restore_of_a_snapshot_that_does_not_verify_says_so_and_keeps_nothing(
    lb: Logbook, dest: Path, clock: list[datetime], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snap = backup.snapshot(lb, dest)
    month = snap.path / "logbook" / "2026" / "06.jsonl"
    month.write_text(month.read_text(encoding="utf-8").replace("Kari", "Ola"), encoding="utf-8")
    target = tmp_path / "Restored"
    status, _out, err = _cli(capsys, "restore", str(snap.path), str(target))
    assert status == 1 and "hash does not recompute" in err and "nothing kept" in err
    assert not target.exists()


# -- the command's shape -------------------------------------------------------------------------------------


def test_the_verbs_take_their_paths_and_nothing_else(
    lb: Logbook, dest: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for args in (
        ["list"],
        ["list", str(dest), "--keep", "2"],
        ["restore", str(dest)],
        ["restore", str(dest), str(dest), "--verify"],
        [str(dest), str(dest)],
    ):
        status, _out, err = _cli(capsys, *args)
        assert status == 2, args
        assert "backup" in err
    assert not dest.exists()


def test_the_destination_is_made_and_a_tilde_is_expanded(
    lb: Logbook, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    status, out, _err = _cli(capsys, "~/Backups")
    assert status == 0
    home = Path.home()  # conftest points it at a temporary folder
    assert _snapshots(home / "Backups", lb.meta["owner_id"])
    assert str(home / "Backups") in out


def test_human_sizes() -> None:
    assert backup.human(0) == "0 B"
    assert backup.human(999) == "999 B"
    assert backup.human(4_100) == "4.0 KiB"
    assert backup.human(1_258_291) == "1.2 MiB"
    assert backup.human(5 * 1024**3) == "5.0 GiB"
