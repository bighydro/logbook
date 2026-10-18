"""The two promises `logbook lab hold census` makes (logbook/labs/hold.py, RFC 0042), held on synthetic
folders and synthetic lines of the Oslo persona, who does not exist:

1. Nothing in a walked folder is moved, renamed, deleted or written, and the walk never leaves the
   folders it was given: a link (to a file or a folder, pointing in, out, nowhere or at its own parent)
   is counted and never followed, a FIFO is never opened, the system's and Claude's folders are not
   entered whatever their case, the record is skipped when it lies inside a walked folder and refused
   as a PATH, a hard link is one file.
2. No file name, sender address or Drive file name leaves the local report: never on stdout or stderr
   (text or `--json`), never in the record (the census appends nothing: every file of the record outside
   `state/hold/` is byte-identical before and after), and the report is mode 0600 in a 0700 folder
   where the system has modes.

What `tests/test_lab_hold.py` counts (types, years, duplicates, the largest) is not repeated here."""

from __future__ import annotations

import builtins
import hashlib
import io
import json
import os
import shutil
import signal
import stat
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.core.store import Logbook
from logbook.labs import hold  # imported before any guard below, so the import's own reads never meet it

POSIX = os.name == "posix"
ROOT_USER = POSIX and os.geteuid() == 0  # root reads what a mode forbids: the permission tests say nothing
WIN = sys.platform == "win32"

# Synthetic names and bytes, distinctive enough that one appearance anywhere is a failure.
TAX = "kari-nordmann-tax-2025.pdf"
PRIVATE = "Ola Nordmann private"
DIARY = "diary-ola-2024.txt"
NOVEL = "ines-reading-novel.epub"
CLAUDE_ONLY = "claude-only-transcript.jsonl"
SENTINEL = "ines-nordmann-passport-scan.jpg"  # lives outside every walked folder, reachable by a link only
SENTINEL_BYTES = b"outside-sentinel-07700-900123-" * 64
SENDER = "ines.nordmann@example.org"
SENDER_NAME = "Ines Nordmann"
OWNER = "kari.nordmann@example.org"
DRIVE_NAME = "Kari Nordmann - tax return 2025"
DEADLINE = 30  # seconds a census on a folder with a FIFO may take before the test calls it blocked


class Touched(AssertionError):
    """A census wrote, moved or removed something outside the record's `state/hold/`."""


# -- the folders, the record, the runs ---------------------------------------------------------------------


@pytest.fixture
def record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "rec"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook.init(root, "Europe/Oslo")


def _file(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@pytest.fixture
def stuff(tmp_path: Path) -> Path:
    """Ines's folder: a tax return, a private folder, a pair of identical files and a same-sized third,
    an empty file, and the folders the walk must not enter, in odd case."""
    top = tmp_path / "stuff"
    _file(top / "Tax" / TAX, b"%PDF" + b"t" * 5000)
    _file(top / PRIVATE / DIARY, b"dear diary " * 100)
    _file(top / "pair" / "a.bin", b"same" * 500)
    _file(top / "pair" / "b.bin", b"same" * 500)
    _file(top / "pair" / "c.bin", b"else" * 500)  # the same size, other bytes: hashed, no duplicate
    _file(top / "empty.txt", b"")
    _file(top / "books" / "library" / NOVEL, b"once upon " * 50)  # a `library` deeper down is the owner's
    _file(top / ".CLAUDE" / CLAUDE_ONLY, b'{"claude": true}\n')
    _file(top / ".Git" / "HEAD", b"ref: refs/heads/main\n")
    _file(top / "Library" / "Caches" / "cache.db", b"\x00" * 100)
    return top


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    """A folder beside the walked one, holding the sentinel; the walk may never reach it."""
    out = tmp_path / "outside"
    _file(out / SENTINEL, SENTINEL_BYTES)
    return out


def _symlink(target: Path, link: Path, folder: bool = False) -> None:
    try:
        os.symlink(target, link, target_is_directory=folder)
    except (OSError, NotImplementedError) as e:  # Windows without the privilege, a file system without links
        pytest.skip(f"this system makes no symbolic link here: {e}")


def _fifo(path: Path) -> None:
    mkfifo = getattr(os, "mkfifo", None)
    if WIN or mkfifo is None:
        pytest.skip("no FIFO on this system")
    mkfifo(path)


def _main(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    """`logbook lab hold census …` in this process: (exit code, stdout, stderr)."""
    capsys.readouterr()
    code = 0
    try:
        cli.main(["lab", "hold", "census", *args])
    except SystemExit as e:
        code = int(e.code or 0)
    got = capsys.readouterr()
    return code, got.out, got.err


def _reports(lb: Logbook, census: str = "files") -> tuple[str, dict[str, Any]]:
    folder = lb.root / "state" / "hold"
    return (
        (folder / f"{census}.md").read_text(encoding="utf-8"),
        json.loads((folder / f"{census}.json").read_text(encoding="utf-8")),
    )


@contextmanager
def _deadline(seconds: int) -> Iterator[None]:
    """Fail, never hang, when a census blocks (an opened FIFO would): SIGALRM where there is one."""
    if not hasattr(signal, "SIGALRM"):
        yield
        return

    def ring(signum: int, frame: Any) -> None:
        raise TimeoutError(f"the census did not finish in {seconds} s: it blocked")

    before = signal.signal(signal.SIGALRM, ring)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, before)


# -- snapshots: what a folder holds, byte for byte, and what the record holds ------------------------------


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 16):
            sha.update(chunk)
    return sha.hexdigest()


def _snapshot(folder: Path) -> dict[tuple[str, ...], tuple[Any, ...]]:
    """Every path under `folder` (links and FIFOs not followed or opened) as (kind, size, mtime_ns, and
    the content digest of a regular file or the target of a link)."""
    found: dict[tuple[str, ...], tuple[Any, ...]] = {}
    for here, dirs, files in os.walk(folder, followlinks=False):
        for name in [*dirs, *files]:
            path = Path(here) / name
            st = os.lstat(path)
            rel = path.relative_to(folder).parts
            if stat.S_ISLNK(st.st_mode):
                found[rel] = ("link", os.readlink(path))
            elif stat.S_ISREG(st.st_mode):
                found[rel] = ("file", st.st_size, st.st_mtime_ns, _digest(path))
            elif stat.S_ISDIR(st.st_mode):
                found[rel] = ("folder", st.st_mtime_ns)
            else:
                found[rel] = ("special", st.st_mode, st.st_mtime_ns)
    return found


def _record_state(lb: Logbook) -> dict[tuple[str, ...], str]:
    """Every file of the record outside `state/hold/`, by its digest: what a census must leave as it was."""
    reports = lb.root / "state" / "hold"
    return {
        path.relative_to(lb.root).parts: _digest(path)
        for path in lb.root.rglob("*")
        if path.is_file() and reports not in path.parents
    }


def _record_holds(lb: Logbook, text: str) -> bool:
    """Whether any file of the record outside `state/hold/` (the log files, logbook.json, the policies,
    the lock) holds `text`."""
    reports = lb.root / "state" / "hold"
    needle = text.encode("utf-8")
    return any(
        needle in path.read_bytes()
        for path in lb.root.rglob("*")
        if path.is_file() and reports not in path.parents
    )


# -- the guard: every way Python writes, moves or removes a path refuses outside state/hold ----------------

WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


@contextmanager
def _guarded(lb: Logbook) -> Iterator[list[Path]]:
    """For the block, `os.open` with a write flag, `open`/`io.open` in a write mode, and every rename,
    replace, move, unlink, mkdir, chmod and utime of `os`, `shutil` and `Path` raise `Touched` (not an
    OSError, which the walk swallows) unless every path they touch is `<record>/state/hold` or under it
    (the report and its `.part`), or `<record>/state` (the parent `mkdir(parents=True)` makes). The
    writes allowed are returned, so a test can see the guard was live."""
    allowed = lb.root / "state" / "hold"
    seen: list[Path] = []

    def check(target: Any, what: str) -> None:
        if isinstance(target, int):  # a descriptor: `os.open` checked it when it was made
            return
        path = Path(os.fspath(target))
        if path == allowed or allowed in path.parents or path == allowed.parent:
            seen.append(path)
            return
        raise Touched(f"{what} touched {path.name!r} outside the record's state/hold")

    def guard(module: Any, name: str, targets: Callable[..., list[Any]]) -> None:
        original = getattr(module, name)

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            for target in targets(*args, **kwargs):
                check(target, f"{module.__name__ if hasattr(module, '__name__') else 'Path'}.{name}")
            return original(*args, **kwargs)

        mp.setattr(module, name, wrapper)

    def first(*args: Any, **kwargs: Any) -> list[Any]:
        return [args[0] if args else kwargs.get("path", kwargs.get("src"))]

    def both(*args: Any, **kwargs: Any) -> list[Any]:
        return list(args[:2]) + [v for k, v in kwargs.items() if k in ("src", "dst")]

    def opened(*args: Any, **kwargs: Any) -> list[Any]:
        file = args[0] if args else kwargs.get("file")
        mode = args[1] if len(args) > 1 else kwargs.get("mode", "r")
        return [file] if any(c in mode for c in "wax+") else []

    def os_open(*args: Any, **kwargs: Any) -> list[Any]:
        flags = args[1] if len(args) > 1 else kwargs.get("flags", 0)
        return [args[0]] if flags & WRITE_FLAGS else []

    with pytest.MonkeyPatch.context() as mp:
        for name in ("remove", "unlink", "rmdir", "mkdir", "makedirs", "truncate", "chmod", "utime"):
            guard(os, name, first)
        for name in ("rename", "replace", "link", "symlink"):
            guard(os, name, both)
        guard(os, "open", os_open)
        guard(builtins, "open", opened)
        guard(io, "open", opened)
        for name in ("move", "copy", "copy2", "copyfile", "copytree", "rmtree"):
            guard(shutil, name, first if name == "rmtree" else both)
        for name in ("unlink", "rmdir", "mkdir", "touch", "write_bytes", "write_text", "chmod"):
            guard(Path, name, first)
        for name in ("rename", "replace"):
            guard(Path, name, both)
        yield seen


# -- property 1: the walk changes nothing and stays inside ---------------------------------------------------


def test_nothing_in_a_walked_folder_changes_and_only_the_report_is_written(
    record: Logbook, stuff: Path, outside: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    link = stuff / "to-outside"
    _symlink(outside / SENTINEL, link)
    if POSIX and hasattr(os, "mkfifo"):
        os.mkfifo(stuff / "pipe")
    before = _snapshot(stuff)
    with _guarded(record) as writes, _deadline(DEADLINE):
        code, _out, err = _main(capsys, "files", str(stuff))
    assert code == 0, err
    assert _snapshot(stuff) == before
    assert writes, "the guard never saw the report being written: it was not live"
    assert all(path.name.startswith(("files.", "hold", "state")) for path in writes)
    _md, report = _reports(record)
    assert report["changed"] == {"moved": 0, "renamed": 0, "deleted": 0, "written": 0}


def test_a_link_to_a_file_or_folder_in_out_nowhere_or_up_is_counted_and_never_followed(
    record: Logbook, stuff: Path, outside: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _symlink(outside / SENTINEL, stuff / "link-to-file")
    _symlink(outside, stuff / "link-to-folder", folder=True)
    _symlink(stuff / "Tax" / TAX, stuff / "link-inside")  # pointing in: still not a second file
    _symlink(stuff / "nowhere", stuff / "dangling")
    _symlink(Path(".."), stuff / "pair" / "loop", folder=True)  # a loop: its own parent
    code, _out, err = _main(capsys, "files", str(stuff))
    assert code == 0, err
    md, report = _reports(record)
    text = md + json.dumps(report, ensure_ascii=False)
    assert SENTINEL not in text and "outside" not in text.replace(str(stuff), "")
    assert hashlib.sha256(SENTINEL_BYTES).hexdigest() not in text
    assert report["skipped"]["links"] == 5
    regular = sum(1 for v in _snapshot(stuff).values() if v[0] == "file")
    skipped_files = 1 + 1 + 1  # under .CLAUDE, .Git and Library: counted as folders skipped, never as files
    assert report["totals"]["files"] == regular - skipped_files
    assert {f["path"] for d in report["duplicates"]["list"] for f in d["files"]} == {
        "pair/a.bin",
        "pair/b.bin",
    }


def test_a_root_given_as_a_link_is_resolved_once_and_the_walk_goes_no_further(
    record: Logbook, stuff: Path, outside: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _symlink(stuff, tmp_path / "via-link", folder=True)
    _symlink(outside / SENTINEL, stuff / "link-to-file")
    code, out, err = _main(capsys, "files", str(tmp_path / "via-link"), str(stuff), "--json")
    assert code == 0, err
    summary = json.loads(out)
    assert summary["roots"] == 1  # the link and its folder are one root
    md, report = _reports(record)
    assert report["roots"] == [{"n": 1, "path": str(stuff.resolve())}]
    assert report["totals"]["files"] > 0 and report["skipped"]["links"] == 1
    assert SENTINEL not in md + json.dumps(report, ensure_ascii=False)


def test_a_fifo_is_counted_and_never_opened(
    record: Logbook, stuff: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _fifo(stuff / "pipe")  # nobody writes to it: an open for reading without O_NONBLOCK blocks forever
    with _deadline(DEADLINE):
        code, _out, err = _main(capsys, "files", str(stuff))
    assert code == 0, err
    _md, report = _reports(record)
    assert report["skipped"]["special"] == 1
    assert "pipe" not in {f["path"] for d in report["duplicates"]["list"] for f in d["files"]}


def test_a_file_replaced_by_a_fifo_between_the_walk_and_the_hash_does_not_block(
    record: Logbook, stuff: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    if WIN or not hasattr(os, "mkfifo"):
        pytest.skip("no FIFO on this system")
    original, swapped = hold._open, []

    def swap(path: Path) -> int:  # the adversary: between scandir and open, `a.bin` becomes a pipe
        if path.name == "a.bin" and not swapped:
            path.unlink()
            os.mkfifo(path)
            swapped.append(path)
        return original(path)

    monkeypatch.setattr(hold, "_open", swap)
    with _deadline(DEADLINE):
        code, _out, err = _main(capsys, "files", str(stuff))
    assert code == 0, err
    assert swapped, "the hash never reached a.bin"
    _md, report = _reports(record)
    assert report["skipped"]["special"] == 1
    assert report["duplicates"]["sets"] == 0


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="the open cannot refuse a link on this system")
def test_a_file_replaced_by_a_link_between_the_walk_and_the_hash_is_not_read(
    record: Logbook,
    stuff: Path,
    outside: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    twin = _file(outside / "twin.bin", b"same" * 500)  # the size `a.bin` had, so the hash would still run
    _symlink(twin, outside / "probe")  # proves links work here before the race is staged
    original, swapped = hold._open, []

    def swap(path: Path) -> int:
        if path.name == "a.bin" and not swapped:
            path.unlink()
            os.symlink(twin, path)
            swapped.append(path)
        return original(path)

    monkeypatch.setattr(hold, "_open", swap)
    code, _out, err = _main(capsys, "files", str(stuff))
    assert code == 0, err
    assert swapped
    _md, report = _reports(record)
    assert report["skipped"]["unreadable_files"] == 1
    assert report["duplicates"]["sets"] == 0  # b.bin alone; a.bin's bytes were never read through the link


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="the open cannot refuse a link on this system")
def test_a_folder_turned_link_between_the_walk_and_the_hash_is_not_read_through(
    record: Logbook,
    stuff: Path,
    outside: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """O_NOFOLLOW guards the last component only: when a *folder* on the way is replaced by a link after
    the walk listed it, the open reaches a file outside the walked folder. The inode the walk listed
    (`_digest`'s `inode`) is what refuses it: the outside file, of the same size and with a twin of its
    bytes inside, must not make a duplicate set, and its digest must not reach the report."""
    shutil.rmtree(stuff / "pair")
    _file(stuff / "pair" / "a.bin", b"same" * 500)
    _file(stuff / "x.bin", b"same" * 500)
    twin = (SENTINEL_BYTES * 2)[: 4 * 500]  # exactly the size `a.bin` had, so only the inode can tell
    _file(outside / "pair" / "a.bin", twin)
    _file(stuff / "y.bin", twin)  # a twin of the outside bytes inside: the digest would show as a set
    _symlink(outside, stuff / "probe", folder=True)
    original, swapped = hold._open, []

    def swap(path: Path) -> int:
        if path.name == "a.bin" and not swapped:
            shutil.rmtree(path.parent)
            os.symlink(outside / "pair", path.parent, target_is_directory=True)
            swapped.append(path)
        return original(path)

    monkeypatch.setattr(hold, "_open", swap)
    code, _out, err = _main(capsys, "files", str(stuff))
    assert code == 0, err
    assert swapped
    _md, report = _reports(record)
    duplicated = {f["path"] for d in report["duplicates"]["list"] for f in d["files"]}
    assert "pair/a.bin" not in duplicated, (
        "a.bin was read through a folder that had become a link: its bytes came from outside the folder"
    )
    assert report["duplicates"]["sets"] == 0  # x.bin and y.bin are alone
    assert report["skipped"]["changed_during_census"] == 1
    assert hashlib.sha256(twin).hexdigest() not in json.dumps(report)


def test_a_folder_turned_link_between_the_listing_and_the_descent_is_not_entered(
    record: Logbook,
    stuff: Path,
    outside: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _symlink(outside, stuff / "probe", folder=True)
    _file(outside / "deep" / SENTINEL, SENTINEL_BYTES)
    original, swapped = hold._still, []

    def swap(path: Path, inode: int, is_kind: Any) -> bool:  # the adversary, just before the descent
        if path.name == "pair" and not swapped:
            shutil.rmtree(path)
            os.symlink(outside / "deep", path, target_is_directory=True)
            swapped.append(path)
        return original(path, inode, is_kind)

    monkeypatch.setattr(hold, "_still", swap)
    code, _out, err = _main(capsys, "files", str(stuff))
    assert code == 0, err
    assert swapped
    md, report = _reports(record)
    assert SENTINEL not in md + json.dumps(report, ensure_ascii=False)
    assert report["skipped"]["changed_during_census"] == 1
    assert not any(row["path"].startswith("pair/") for row in report["largest"])


def test_system_and_claude_folders_are_not_entered_whatever_their_case(
    record: Logbook, stuff: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _out, err = _main(capsys, "files", str(stuff))
    assert code == 0, err
    md, report = _reports(record)
    text = md + json.dumps(report, ensure_ascii=False)
    assert CLAUDE_ONLY not in text and "HEAD" not in text and "cache.db" not in text
    assert report["skipped"]["system_folders"] == 3  # .CLAUDE, .Git, Library at the top
    assert NOVEL in text  # books/library/, deeper down, is the owner's


def test_the_record_inside_a_walked_folder_is_skipped_and_its_names_stay_out(
    record: Logbook, stuff: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (record.root / "notes" / "ines-note.md").write_text("a note\n", encoding="utf-8")
    code, _out, err = _main(capsys, "files", str(tmp_path))  # the record lies under it
    assert code == 0, err
    md, report = _reports(record)
    text = (md + json.dumps(report, ensure_ascii=False)).replace(str(tmp_path), "")
    assert report["skipped"]["record"] == 1
    assert "logbook.json" not in text and "ines-note" not in text and "files.json" not in text
    assert TAX in text


@pytest.mark.parametrize("inside", ["", "notes", "state/hold"])
def test_a_path_that_is_the_record_or_inside_it_is_refused(
    record: Logbook, inside: str, capsys: pytest.CaptureFixture[str]
) -> None:
    path = record.root.joinpath(*inside.split("/")) if inside else record.root
    path.mkdir(parents=True, exist_ok=True)
    before = _record_state(record)
    with pytest.raises(SystemExit) as raised:
        cli.main(["lab", "hold", "census", "files", str(path)])
    assert raised.value.code == 2
    got = capsys.readouterr()
    assert got.out == ""
    assert "the record" in got.err and got.err.count("\n") == 1
    assert not (record.root / "state" / "hold" / "files.md").exists()
    assert _record_state(record) == before


def test_a_link_to_the_record_is_refused_too(
    record: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _symlink(record.root, tmp_path / "rec-link", folder=True)
    code, out, err = _main(capsys, "files", str(tmp_path / "rec-link"))
    assert code == 2 and out == "" and "the record" in err
    assert not (record.root / "state").exists()


def test_a_path_that_is_a_file_or_missing_is_refused_without_a_report(
    record: Logbook, stuff: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for given in (stuff / "empty.txt", stuff / "nowhere"):
        code, out, err = _main(capsys, "files", str(given))
        assert code == 2 and out == "" and "is not a folder" in err
    assert not (record.root / "state" / "hold").exists()


def test_hard_links_are_one_file_never_a_duplicate(
    record: Logbook, stuff: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    shutil.rmtree(stuff / "pair")
    one = _file(stuff / "linked" / "one.bin", b"hard" * 400)
    try:
        os.link(one, stuff / "linked" / "two.bin")
    except (OSError, NotImplementedError) as e:
        pytest.skip(f"no hard link here: {e}")
    code, _out, err = _main(capsys, "files", str(stuff))
    assert code == 0, err
    _md, report = _reports(record)
    assert report["duplicates"]["sets"] == 0 and report["skipped"]["hard_links"] == 1
    _file(stuff / "linked" / "copy.bin", b"hard" * 400)  # a real second copy is a duplicate of the one file
    code, _out, err = _main(capsys, "files", str(stuff))
    assert code == 0, err
    _md, report = _reports(record)
    assert report["duplicates"]["sets"] == 1 and len(report["duplicates"]["list"][0]["files"]) == 2


@pytest.mark.skipif(not POSIX or ROOT_USER, reason="modes forbid nothing to root or on Windows")
def test_an_unreadable_folder_or_file_is_counted_and_the_census_completes(
    record: Logbook, stuff: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    locked = stuff / "locked"
    _file(locked / SENTINEL, b"behind a mode")
    sealed = _file(stuff / "pair" / "d.bin", b"same" * 500)  # a size twin that cannot be read
    os.chmod(locked, 0)
    os.chmod(sealed, 0)
    try:
        code, _out, err = _main(capsys, "files", str(stuff))
    finally:
        os.chmod(locked, 0o700)
        os.chmod(sealed, 0o600)
    assert code == 0, err
    md, report = _reports(record)
    assert report["skipped"]["unreadable_folders"] == 1 and report["skipped"]["unreadable_files"] == 1
    assert SENTINEL not in md + json.dumps(report, ensure_ascii=False)
    assert report["duplicates"]["sets"] == 1  # a.bin and b.bin still


def test_a_deep_tree_is_walked_whole(
    record: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    depth = 40 if WIN else 300  # Windows paths stop near 260 characters without the long-path switch
    top = tmp_path / "deep"
    bottom = top.joinpath(*(["d"] * depth))
    _file(bottom / "leaf.txt", b"at the bottom")
    code, _out, err = _main(capsys, "files", str(top))
    assert code == 0, err
    _md, report = _reports(record)
    assert report["totals"] == {"files": 1, "bytes": 13, "folders": depth + 1}
    assert report["largest"][0]["path"] == "/".join(["d"] * depth + ["leaf.txt"])


@pytest.mark.skipif(WIN, reason="Windows names are UTF-16 and always decode")
def test_a_file_name_that_is_not_utf8_is_counted_and_kept_escaped_in_the_report(
    record: Logbook, stuff: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A name POSIX allows but UTF-8 does not (one `\\xff` byte, as an old archive leaves) is read with
    surrogate escapes; the report writes it as the escape `\\udcff`, so one odd name never stops the
    census of a whole disk, and it stays off stdout like any other."""
    try:
        with open(os.fsencode(stuff) + b"/odd-\xff.txt", "wb") as fh:
            fh.write(b"odd name")
    except OSError as e:  # a file system that insists on UTF-8 names
        pytest.skip(f"this file system takes no such name: {e}")
    code, out, err = _main(capsys, "files", str(stuff))
    assert code == 0, f"the census stopped: {err}"
    md, report = _reports(record)
    assert "odd-\\udcff.txt" in md
    assert any(row["path"] == "odd-\udcff.txt" for row in report["largest"])
    assert "odd-" not in out


# -- property 2: no name leaves the report -------------------------------------------------------------------


def test_no_file_name_reaches_stdout_stderr_or_the_record_and_all_reach_the_report(
    record: Logbook, stuff: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    names = (TAX, PRIVATE, DIARY, NOVEL, "a.bin", "empty.txt")
    before = _record_state(record)
    code, out, err = _main(capsys, "files", str(stuff))
    assert code == 0 and err == ""
    code, out_json, err_json = _main(capsys, "files", str(stuff), "--json")
    assert code == 0 and err_json == ""
    printed = (out + out_json).replace(str(record.root), "")
    for name in names:
        assert name not in printed, name
    assert "stuff" not in printed  # not even the walked folder's own name: counts and the report's path only
    summary = json.loads(out_json)
    assert set(summary) == {
        "census", "made_at", "tier", "report", "totals", "roots", "duplicates", "untouched_folders",
        "skipped", "changed",
    }  # fmt: skip
    assert summary["roots"] == 1 and summary["tier"] == 3
    assert _record_state(record) == before
    for name in names:
        assert not _record_holds(record, name), name
    md, report = _reports(record)
    text = json.dumps(report, ensure_ascii=False)
    for name in names:
        assert name in md and name in text, name


def test_a_sender_address_reaches_the_report_and_nothing_else(
    record: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    def mail(at: str, sender: str, name: str, to: str, direction: str, n: int) -> None:
        record.append(
            at,
            "mail",
            "mail",
            2,
            {
                "schema": "mail/v1",
                "raw_id": f"{OWNER}:m{n}@mail.example.org",
                "message_id": f"m{n}@mail.example.org",
                "thread": "t1@mail.example.org",
                "from": {"email": sender, "name": name},
                "to": [{"email": to}],
                "subject": "Mooring for the weekend",
                "direction": direction,
                "size": 4821,
            },
        )

    mail("2026-03-02T10:15:00Z", SENDER, SENDER_NAME, OWNER, "received", 1)
    mail("2026-03-03T10:15:00Z", OWNER, "Kari Nordmann", SENDER, "sent", 2)
    before = _record_state(record)
    code, out, err = _main(capsys, "senders")
    assert code == 0 and err == "", err
    code, out_json, err_json = _main(capsys, "senders", "--json")
    assert code == 0 and err_json == ""
    printed = (out + out_json).replace(str(record.root), "")
    for text in (SENDER, SENDER_NAME, OWNER, "example.org", "Mooring", "@"):
        assert text not in printed, text
    assert "1 senders" in out
    assert _record_state(record) == before  # the index lives in the cache folder, not in the record
    md, report = _reports(record, "senders")
    assert SENDER in md and report["senders"][0]["email"] == SENDER and report["senders"][0]["answered"]
    assert report["tier"] == 2


def test_a_drive_file_name_reaches_the_report_and_nothing_else(
    record: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    record.append(
        "2026-09-01T10:00:00Z",
        "drive",
        "event",
        1,
        {
            "schema": "event/v1",
            "raw_id": "f-tax/edit@2026-09-01T10:00:00Z",
            "title": f"edit {DRIVE_NAME}",
            "calendar": {"id": "google-drive", "name": "Google Drive"},
            "all_day": False,
            "modified_at": "2026-09-01T10:00:00Z",
            "extra": {
                "activity": "edit",
                "count": 2,
                "file": {"id": "f-tax", "name": DRIVE_NAME, "mime_type": "application/pdf",
                         "path": ["My Drive", "Nordmann family"]},
                "by_owner": True,
            },
        },
    )  # fmt: skip
    before = _record_state(record)
    code, out, err = _main(capsys, "drive")
    assert code == 0 and err == "", err
    code, out_json, err_json = _main(capsys, "drive", "--json")
    assert code == 0 and err_json == ""
    printed = (out + out_json).replace(str(record.root), "")
    for text in (DRIVE_NAME, "Nordmann", "f-tax", "My Drive"):
        assert text not in printed, text
    assert "1 files" in out
    assert _record_state(record) == before
    md, report = _reports(record, "drive")
    assert DRIVE_NAME in md and report["files"][0]["name"] == DRIVE_NAME
    assert report["files"][0]["folder"] == "My Drive/Nordmann family"


@pytest.mark.skipif(not POSIX, reason="Windows has no mode bits")
def test_the_report_is_readable_by_the_owner_alone(
    record: Logbook, stuff: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for _ in range(2):  # the second run replaces the first report: still 0600
        code, _out, err = _main(capsys, "files", str(stuff))
        assert code == 0, err
        folder = record.root / "state" / "hold"
        assert stat.S_IMODE(folder.stat().st_mode) & 0o077 == 0
        assert stat.S_IMODE(folder.stat().st_mode) & 0o700 == 0o700
        for name in ("files.md", "files.json"):
            mode = stat.S_IMODE((folder / name).stat().st_mode)
            assert mode & 0o077 == 0, f"{name} is {oct(mode)}"
            assert mode & 0o600 == 0o600
        assert sorted(p.name for p in folder.iterdir()) == ["files.json", "files.md"]  # no .part left behind


def test_the_markdown_keeps_an_odd_name_in_its_row_and_the_json_keeps_it_exact(
    record: Logbook, stuff: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    odd = "ola|nordmann\nreceipt.pdf" if not WIN else "ola nordmann receipt.pdf"
    _file(stuff / "Tax" / odd, b"%PDF" + b"r" * 7000)  # the largest: it heads the table
    code, out, err = _main(capsys, "files", str(stuff))
    assert code == 0, err
    md, report = _reports(record)
    assert report["largest"][0]["path"] == f"Tax/{odd}"
    largest = md.split("largest\n", 1)[1].split("\n## ", 1)[0].strip().splitlines()
    assert all(line.startswith("| ") and line.endswith(" |") for line in largest[2:])
    assert len(largest) == 2 + min(hold.LARGEST, report["totals"]["files"])  # the header, the rule, the rows
    assert odd not in out + err
