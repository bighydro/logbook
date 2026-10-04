"""`logbook attach import-backup|status|verify`: the SPEC §1.1 store filled from an iOS backup, counted,
and checked. The backup is the synthetic one `test_import_backup` builds: WhatsApp's one media file,
Messages' two and the Photos library's one, all referenced by digest from the lines `import-backup`
wrote. Two of them hold the same bytes (the fixtures' "not really a jpeg"), so the store ends with
three files for four references. Nobody in it exists."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_imessage import IMAGE_BYTES, VOICE_BYTES
from test_import_backup import WHATSAPP, _backup, _file_id, _snapshot
from test_import_backup_encrypted import PASSWORD, _encrypted_backup

from logbook import attach, cli
from logbook.core import attachments
from logbook.core.store import Logbook

IMAGE = hashlib.sha256(IMAGE_BYTES).hexdigest()  # WhatsApp's photo.jpg and Messages' stern.jpg alike
VOICE = hashlib.sha256(VOICE_BYTES).hexdigest()  # Messages' note.caf
PIXELS = hashlib.sha256(b"pixels").hexdigest()  # the Photos library's IMG_0001.HEIC
THREE = (
    ("whatsapp", "Message/Media/4790000001@s.whatsapp.net/a/b/photo.jpg"),
    ("imessage", "Library/SMS/Attachments/ab/12/AT-100/stern.jpg"),
    ("imessage", "Library/SMS/Attachments/ef/56/AT-103/note.caf"),
    ("apple-photos", "Media/DCIM/100APPLE/IMG_0001.HEIC"),
)
DOMAINS = {"whatsapp": WHATSAPP, "imessage": "MediaDomain", "apple-photos": "CameraRollDomain"}


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    monkeypatch.setenv("LOGBOOK_DIAL_PREFIX", "47")
    for name in (
        "LOGBOOK_WHATSAPP_HASH_MEDIA",
        "LOGBOOK_IMESSAGE_HASH_MEDIA",
        "LOGBOOK_APPLE_PHOTOS_HASH_MEDIA",
    ):
        monkeypatch.delenv(name, raising=False)
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook.init(root, "Europe/Oslo")


@pytest.fixture
def imported(lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    """The fake backup, its three sources imported: the lines are in the record, the store is empty."""
    backup = _backup(tmp_path, sources=("whatsapp", "imessage", "apple-photos"))
    cli.main(["import-backup", str(backup), "--only", "whatsapp,imessage,photos"])
    capsys.readouterr()
    assert not (lb.root / "attachments").exists()
    return backup


def _attach(*args: str) -> None:
    cli.main(["attach", *args])


def _store(lb: Logbook) -> dict[str, bytes]:
    folder = lb.root / "attachments"
    return {p.name: p.read_bytes() for p in folder.iterdir()} if folder.exists() else {}


def _blob(backup: Path, source: str, relative_path: str) -> Path:
    fid = _file_id(DOMAINS[source], relative_path)
    return backup / fid[:2] / fid


# -- import-backup ---------------------------------------------------------------------------------


def test_attach_import_backup_streams_every_referenced_file_into_the_store_once(lb, imported, capsys):
    before = _snapshot(imported)
    _attach("import-backup", str(imported), "--only", "whatsapp,imessage,photos")
    captured = capsys.readouterr()
    assert _snapshot(imported) == before  # the backup is only read
    assert _store(lb) == {IMAGE: IMAGE_BYTES, VOICE: VOICE_BYTES, PIXELS: b"pixels"}
    out = captured.out
    assert "whatsapp: 1 file referenced by 1 line: 1 stored" in out
    assert "imessage: 2 files referenced by 2 lines: 1 stored, 1 present" in out  # stern.jpg = photo.jpg
    assert "apple-photos: 1 file referenced by 1 line: 1 stored" in out
    assert "1 line without a digest" in out  # WhatsApp's clip.mp4 was missing at import
    assert f"attachments/: 3 files, {len(IMAGE_BYTES) + len(VOICE_BYTES) + 6:,} bytes" in out
    assert "refused" not in captured.err
    seq, _head, errors = lb.verify()
    # nothing was appended by attach; the one extra line is the favourite's keeper, written with the photos
    assert errors == [] and seq == 14 + 13 + 6 + 1
    assert sum(1 for line in lb.lines() if line["kind"] == "keeper") == 1


def test_attach_import_backup_resumes_and_never_rewrites_a_present_file(lb, imported, capsys):
    _attach("import-backup", str(imported), "--only", "whatsapp,imessage,photos")
    capsys.readouterr()
    store = lb.root / "attachments"
    (store / VOICE).unlink()  # as a run interrupted before it would have been
    kept = {name: (store / name).stat().st_mtime_ns for name in (IMAGE, PIXELS)}
    _attach("import-backup", str(imported), "--only", "whatsapp,imessage,photos")
    out = capsys.readouterr().out
    assert _store(lb) == {IMAGE: IMAGE_BYTES, VOICE: VOICE_BYTES, PIXELS: b"pixels"}
    assert "whatsapp: 1 file referenced by 1 line: 0 stored, 1 present" in out
    assert "imessage: 2 files referenced by 2 lines: 1 stored" in out
    assert "apple-photos: 1 file referenced by 1 line: 0 stored, 1 present" in out
    assert {name: (store / name).stat().st_mtime_ns for name in kept} == kept


def test_attach_import_backup_refuses_a_file_whose_bytes_are_not_the_lines_digest(lb, imported, capsys):
    """A blob damaged in the backup: the stream hashes to another digest, so it is refused, nothing
    lands under the name, the other files are still stored, and the exit status says so."""
    damaged = _blob(imported, "imessage", "Library/SMS/Attachments/ef/56/AT-103/note.caf")
    damaged.write_bytes(b"caff\x00\x01not the bytes the line names")
    with pytest.raises(SystemExit) as e:
        _attach("import-backup", str(imported), "--only", "whatsapp,imessage,photos")
    assert e.value.code == 1
    captured = capsys.readouterr()
    assert _store(lb) == {IMAGE: IMAGE_BYTES, PIXELS: b"pixels"}
    assert [p.name for p in (lb.root / "attachments").iterdir() if not attachments.is_digest(p.name)] == []
    assert "imessage: 2 files referenced by 2 lines: 0 stored, 1 present, 0 not in the backup, 1 refused" in (
        captured.out
    )
    (refused,) = (line for line in captured.err.splitlines() if "refused" in line)
    assert "Library/SMS/Attachments/ef/56/AT-103/note.caf" in refused and VOICE[:12] in refused
    assert hashlib.sha256(damaged.read_bytes()).hexdigest()[:12] in refused
    assert "1 file refused" in captured.out


def test_attach_import_backup_counts_a_file_the_backup_does_not_hold(lb, imported, capsys):
    _blob(imported, "whatsapp", "Message/Media/4790000001@s.whatsapp.net/a/b/photo.jpg").unlink()
    _attach("import-backup", str(imported), "--only", "whatsapp")
    out = capsys.readouterr().out
    assert "whatsapp: 1 file referenced by 1 line: 0 stored, 0 present, 1 not in the backup, 0 refused" in out
    assert _store(lb) == {}


def test_attach_import_backup_dry_run_says_what_it_would_store_and_writes_nothing(lb, imported, capsys):
    _attach("import-backup", str(imported), "--only", "whatsapp,imessage,photos", "--dry-run")
    out = capsys.readouterr().out
    assert not (lb.root / "attachments").exists()
    assert "whatsapp: 1 file referenced by 1 line: 1 would be stored" in out
    assert "imessage: 2 files referenced by 2 lines: 1 would be stored" in out and "1 present" in out
    assert f"dry run: 3 files ({len(IMAGE_BYTES) + len(VOICE_BYTES) + 6:,} bytes) would be stored" in out
    assert "nothing written" in out


def test_attach_import_backup_since_takes_the_lines_from_that_local_day_on(lb, imported, capsys):
    _attach("import-backup", str(imported), "--only", "whatsapp,imessage,photos", "--since", "2026-03-02")
    out = capsys.readouterr().out
    assert "whatsapp: 1 file referenced by 1 line" in out  # the chat is on 2026-03-02
    assert "apple-photos: 0 files referenced" in out  # IMG_0001 was taken on 2026-03-01
    assert PIXELS not in _store(lb) and IMAGE in _store(lb)
    with pytest.raises(SystemExit) as e:
        _attach("import-backup", str(imported), "--only", "whatsapp", "--since", "yesterday")
    assert e.value.code == 2 and "YYYY-MM-DD" in capsys.readouterr().err


def test_attach_import_backup_leaves_a_retracted_lines_media_alone(lb, imported, capsys):
    photo = next(
        line for line in lb.lines() if line["source"] == "apple-photos" and "content_hash" in line["payload"]
    )
    lb.retract(photo["seq"], "not mine")
    _attach("import-backup", str(imported), "--only", "photos")
    out = capsys.readouterr().out
    assert "apple-photos: 0 files referenced by 0 lines" in out and PIXELS not in _store(lb)


def test_attach_import_backup_needs_only_and_refuses_an_unknown_source(lb, imported, capsys):
    with pytest.raises(SystemExit) as e:
        _attach("import-backup", str(imported))
    assert e.value.code == 2 and "--only" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        _attach("import-backup", str(imported), "--only", "whatsapp,telegram")
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "telegram" in err and "whatsapp, imessage, apple-photos" in err
    with pytest.raises(SystemExit) as e:
        _attach("import-backup", str(imported), "--only", "voice-memos")  # a source with no media pass
    assert e.value.code == 2
    assert not (lb.root / "attachments").exists()


def test_attach_import_backup_skips_a_disabled_source(lb, imported, capsys):
    (lb.root / "policy" / "import.json").write_text(
        json.dumps({"disabled": [{"source": "whatsapp", "reason": "a demo account"}]}), encoding="utf-8"
    )
    _attach("import-backup", str(imported), "--only", "whatsapp,photos")
    out = capsys.readouterr().out
    assert "whatsapp: disabled (a demo account); skipped" in out
    assert _store(lb) == {PIXELS: b"pixels"}


def test_attach_import_backup_refuses_a_folder_that_is_not_a_backup(lb, tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        _attach("import-backup", str(tmp_path), "--only", "whatsapp")
    assert e.value.code == 2 and "Manifest.db" in capsys.readouterr().err


def test_attach_import_backup_prints_a_progress_line_every_so_many_files(lb, imported, monkeypatch, capsys):
    monkeypatch.setattr(attach, "PROGRESS_EVERY", 2)
    _attach("import-backup", str(imported), "--only", "whatsapp,imessage,photos")
    err = capsys.readouterr().err
    progress = [line for line in err.splitlines() if line.startswith("  ") and "files" in line]
    assert [line.split(":")[0] for line in progress] == ["  2 files", "  4 files"]


def test_attach_import_backup_decrypts_an_encrypted_backups_media_on_the_way(
    lb, tmp_path, monkeypatch, capsys
):
    built = _encrypted_backup(tmp_path)
    monkeypatch.setenv("LOGBOOK_BACKUP_PASSWORD", PASSWORD)
    cli.main(["import-backup", str(built.folder), "--only", "imessage"])
    capsys.readouterr()
    before = _snapshot(built.folder)
    _attach("import-backup", str(built.folder), "--only", "imessage")
    captured = capsys.readouterr()
    assert _snapshot(built.folder) == before
    assert PASSWORD not in captured.out and PASSWORD not in captured.err
    assert "imessage: 1 file referenced by 1 line: 1 stored, 0 present, 0 not in the backup" in captured.out
    assert "3 lines without a digest" in captured.out  # note.caf among them: not in this backup at import
    assert _store(lb) == {IMAGE: IMAGE_BYTES}
    monkeypatch.delenv("LOGBOOK_BACKUP_PASSWORD")
    with pytest.raises(SystemExit) as e:
        _attach("import-backup", str(built.folder), "--only", "imessage")
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith("attach import-backup:") and "LOGBOOK_BACKUP_PASSWORD" in err


# -- status -------------------------------------------------------------------------------------


def test_attach_status_counts_referenced_present_and_missing_per_source(lb, imported, capsys):
    _attach("status")
    out = capsys.readouterr().out
    assert "whatsapp" in out and "imessage" in out and "apple-photos" in out
    assert "attachments/: no store yet" in out
    _attach("import-backup", str(imported), "--only", "whatsapp,imessage")
    capsys.readouterr()
    _attach("status", "--json")
    report = json.loads(capsys.readouterr().out)
    by = {s["source"]: s for s in report["sources"]}
    assert by["whatsapp"] == {"source": "whatsapp", "referenced": 1, "lines": 1, "present": 1, "missing": 0}
    assert by["imessage"] == {"source": "imessage", "referenced": 2, "lines": 2, "present": 2, "missing": 0}
    assert by["apple-photos"] == {
        "source": "apple-photos",
        "referenced": 1,
        "lines": 1,
        "present": 0,
        "missing": 1,
    }
    assert report["store"] == {
        "files": 2,
        "bytes": len(IMAGE_BYTES) + len(VOICE_BYTES),
        "other": 0,
        "unreferenced": 0,
    }
    _attach("status")
    out = capsys.readouterr().out
    rows = {line.split()[0]: line.split()[1:] for line in out.splitlines() if line.startswith("  ")}
    assert rows["source"] == ["referenced", "present", "missing", "lines"]
    assert rows["imessage"] == ["2", "2", "0", "2"] and rows["apple-photos"] == ["1", "0", "1", "1"]
    assert f"attachments/: 2 files, {len(IMAGE_BYTES) + len(VOICE_BYTES):,} bytes" in out


def test_attach_status_counts_a_file_no_line_references_and_leaves_a_retracted_line_out(lb, imported, capsys):
    _attach("import-backup", str(imported), "--only", "photos")
    photo = next(
        line for line in lb.lines() if line["source"] == "apple-photos" and "content_hash" in line["payload"]
    )
    lb.retract(photo["seq"], "not mine")
    capsys.readouterr()
    _attach("status", "--json")
    report = json.loads(capsys.readouterr().out)
    assert "apple-photos" not in {s["source"] for s in report["sources"]}
    assert report["store"]["files"] == 1 and report["store"]["unreferenced"] == 1


# -- verify -------------------------------------------------------------------------------------


def test_attach_verify_streams_every_present_file_against_its_name(lb, imported, capsys):
    _attach("verify")
    assert "attachments/: no store yet" in capsys.readouterr().out
    _attach("import-backup", str(imported), "--only", "whatsapp,imessage,photos")
    capsys.readouterr()
    _attach("verify")
    out = capsys.readouterr().out
    total = len(IMAGE_BYTES) + len(VOICE_BYTES) + 6
    assert f"attachments/: 3 files checked, {total:,} bytes, every file matches its name" in out
    store = lb.root / "attachments"
    (store / VOICE).write_bytes(b"tampered")  # nothing else may ever do this
    (store / f".{PIXELS}.999.tmp").write_bytes(b"left by a run that died")
    with pytest.raises(SystemExit) as e:
        _attach("verify")
    assert e.value.code == 1
    out = capsys.readouterr().out
    assert "CORRUPT — 1 of 3 files does not match its name" in out
    assert f"attachments/{VOICE}: hashes to {hashlib.sha256(b'tampered').hexdigest()[:12]}" in out
    assert "1 other entry ignored" in out


def test_attach_verify_prints_a_progress_line_every_so_many_files(lb, imported, monkeypatch, capsys):
    _attach("import-backup", str(imported), "--only", "whatsapp,imessage,photos")
    monkeypatch.setattr(attach, "PROGRESS_EVERY", 2)
    capsys.readouterr()
    _attach("verify")
    err = capsys.readouterr().err
    assert [line.split(":")[0] for line in err.splitlines() if "files" in line] == ["  2 files"]


# -- the module ---------------------------------------------------------------------------------


def test_sources_place_each_lines_path_in_the_backup_and_refuse_one_that_leaves_its_folder():
    whatsapp, imessage, photos = (attach.source(name) for name in ("whatsapp", "imessage", "photos"))
    assert whatsapp is not None and imessage is not None and photos is not None
    assert photos.name == "apple-photos" and attach.source("apple-photos") is photos
    assert attach.source("voice-memos") is None and attach.source("contacts") is None
    assert whatsapp.relative_path("Media/4790000001@s.whatsapp.net/a/b/photo.jpg") == THREE[0][1]
    assert imessage.relative_path("~/Library/SMS/Attachments/ab/12/AT-100/stern.jpg") == THREE[1][1]
    assert imessage.relative_path("/var/mobile/Library/SMS/Attachments/ef/56/AT-103/note.caf") == THREE[2][1]
    assert photos.relative_path("DCIM/100APPLE/IMG_0001.HEIC") == THREE[3][1]
    assert whatsapp.relative_path("../escape.jpg") is None and whatsapp.relative_path("") is None
    assert imessage.relative_path("~/Library/SMS/Attachments/../../secret.txt") is None
    assert imessage.relative_path("~/Library/SMS/elsewhere/a.jpg") is None
    assert photos.relative_path("/DCIM/100APPLE/IMG_0001.HEIC") is None
    assert (whatsapp.domain, imessage.domain, photos.domain) == (WHATSAPP, "MediaDomain", "CameraRollDomain")
    assert [s.name for s in attach.SOURCES] == ["whatsapp", "imessage", "apple-photos"]


def test_references_reads_every_digest_a_line_carries_and_nothing_without_one(lb, imported):
    with lb.index() as idx:
        found = list(attach.references(idx, attach.SOURCES[1], None))
    assert sorted(r.sha256 for r in found) == sorted([IMAGE, VOICE])
    by = {r.sha256: r for r in found}
    assert by[IMAGE].relative_path == THREE[1][1] and by[IMAGE].bytes == len(IMAGE_BYTES)
    assert by[VOICE].local_path.endswith("note.caf") and by[VOICE].source == "imessage"
    assert all(len(r.line_id) == 36 for r in found)


def test_more_media_of_one_message_is_referenced_too(lb, imported):
    """A message with several attachments keeps the rest under `extra.more_media`; every digest
    among them is a reference, and a line whose first file is missing still yields the others."""
    with lb.index() as idx:
        (line,) = (ln for ln in idx.of_kind("message") if ln["payload"].get("extra", {}).get("more_media"))
    assert line["payload"]["extra"]["more_media"][0]["media"]["local_path"].endswith("ola.vcf")
    line["payload"]["extra"]["more_media"].append(
        {"media_kind": "image", "media": {"local_path": "~/Library/SMS/Attachments/x/y/z/a.jpg",
                                          "sha256": "ab" * 32, "bytes": 3}}
    )  # fmt: skip
    refs = list(attach._references_of(line, attach.SOURCES[1]))
    assert [r.sha256 for r in refs] == [VOICE, "ab" * 32]
    assert refs[1].relative_path == "Library/SMS/Attachments/x/y/z/a.jpg"
    line["payload"]["extra"]["media"] = {"local_path": "x", "sha256": "NOT A DIGEST"}
    assert [r.sha256 for r in attach._references_of(line, attach.SOURCES[1])] == ["ab" * 32]


def test_the_store_is_counted_by_digest_names_only(lb):
    store = lb.root / "attachments"
    store.mkdir()
    (store / IMAGE).write_bytes(IMAGE_BYTES)
    (store / "README").write_bytes(b"not a digest")
    (store / f".{VOICE}.1.tmp").write_bytes(b"x")
    assert attach.store_size(lb) == (1, len(IMAGE_BYTES), 2)
    report = attach.verify(lb, lambda n, elapsed: None)
    assert (report.checked, report.bytes, report.other, report.bad) == (1, len(IMAGE_BYTES), 2, [])
