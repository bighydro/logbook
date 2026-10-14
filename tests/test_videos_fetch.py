"""`logbook videos fetch`: the one command of the videos that touches the network. It downloads one file
at a time into a bounded cache under `state/videos/` (8 GB unless `--cache-gb` says otherwise, kept for
the next run), refuses a file bigger than the cap and says so, verifies each file against the md5 Drive
reported when the line was written, keeps nothing that does not match, and resumes a download a dropped
connection or an earlier run left part way. Nothing it fetches is ever copied into the record.

The synthetic family's folder of `tests/test_drive_videos.py` (Ines Nordmann of Oslo, who does not
exist), each video a few kilobytes of invented bytes, in the in-process fake of `tests/google_fake.py`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from google_fake import FILES_SCOPE, FOLDER_MIME, USER, Fake, md5_of, private_key, write_key

from logbook import cli
from logbook.contrib import videos
from logbook.contrib.adapters import drive_videos, service_account
from logbook.core.store import Logbook

KEY_ENV, USER_ENV, FOLDER_ENV = service_account.KEY_ENV, service_account.USER_ENV, drive_videos.FOLDER_ENV
ROOT = "1FamilyVideosFolderSynthetic01"
A, B, C, BIG = (
    "1TapeASyntheticVideoId0000001",
    "1TapeBSyntheticVideoId0000002",
    "1TapeCSyntheticVideoId0000003",
    "1TapeBigSyntheticVideoId00004",
)
MEDIA = {
    A: b"synthetic tape A, the first recording " * 80,  # 3,040 bytes
    B: b"synthetic tape B " * 235,  # 3,995 bytes
    C: b"synthetic tape C!" * 150,  # 2,550 bytes
}


def _files() -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {
        ROOT: {"id": ROOT, "name": "Familiens videoer", "mimeType": FOLDER_MIME, "parents": ["0AOwnerRoot"]}
    }
    for n, (file_id, data) in enumerate(MEDIA.items(), 1):
        files[file_id] = {
            "id": file_id,
            "name": f"Home 0{n}",
            "mimeType": "video/mp4",
            "parents": [ROOT],
            "size": str(len(data)),
            "md5Checksum": md5_of(data),
            "createdTime": "2019-03-02T10:00:00.000Z",
            "modifiedTime": "2019-03-02T10:00:00.000Z",
        }
    files[B]["resourceKey"] = "0-SyntheticResourceKeyB"
    files[BIG] = {
        **files[A],
        "id": BIG,
        "name": "Home 09",
        "size": "9000000000",  # 9 GB: bigger than the default cap
        "md5Checksum": "00000000000000000000000000000000",
    }
    return files


@pytest.fixture(scope="module")
def key() -> Any:
    return private_key()


@pytest.fixture
def fake(tmp_path: Path, key: Any, monkeypatch: pytest.MonkeyPatch, no_network: list[str]) -> Any:
    server = Fake(key, files=_files(), media=dict(MEDIA))
    server.waits = []  # type: ignore[attr-defined]
    monkeypatch.setattr(service_account, "send", server)
    monkeypatch.setattr(service_account, "open_stream", server.stream)
    monkeypatch.setattr(service_account, "sleep", server.waits.append)  # type: ignore[attr-defined]
    monkeypatch.setattr(videos, "CHUNK", 512)  # small reads, so a cut lands part way
    monkeypatch.setenv(KEY_ENV, str(write_key(tmp_path / "google-sa.json", key)))
    monkeypatch.setenv(USER_ENV, USER)
    monkeypatch.setenv(FOLDER_ENV, ROOT)
    yield server
    assert no_network == [], "the fake is the only way out"


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: Fake) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    assert _run("sync", "drive", "--videos") == 0
    fake.requests.clear()
    fake.assertions.clear()
    return lb


def _run(*args: str) -> int:
    try:
        cli.main(list(args))
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    return 0


def _cache(lb: Logbook) -> Path:
    return lb.root / "state" / "videos"


def _cached(lb: Logbook) -> dict[str, bytes]:
    folder = _cache(lb)
    if not folder.is_dir():
        return {}
    return {p.stem: p.read_bytes() for p in folder.iterdir() if p.is_file() and p.suffix != ".part"}


def _state(lb: Logbook) -> dict[str, Any]:
    return json.loads((lb.root / "state" / "videos.json").read_text(encoding="utf-8"))


def _gb(n: int) -> str:
    return str(n / 1e9)


def test_fetch_downloads_one_file_at_a_time_and_verifies_each(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = int(lb.meta["seq"])
    assert _run("videos", "fetch", "--cache-gb", _gb(20_000)) == 0
    assert _cached(lb) == MEDIA
    assert [s["id"] for s in fake.streamed] == [A, B, C]  # one after another, in the folder's order
    assert not list(_cache(lb).glob("*.part"))
    assert int(Logbook(lb.root).meta["seq"]) == seq, "fetching writes no line"
    stored = list((lb.root / "attachments").glob("*"))
    assert not any(p.stat().st_size >= len(MEDIA[C]) for p in stored), "a video was copied into the record"
    out = capsys.readouterr().out
    assert "md5 verified" in out
    assert set(_state(lb)["fetched"]) == {A, B, C}


def test_the_cap_is_respected_and_the_run_stops_when_the_next_file_would_pass_it(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run("videos", "fetch", "--cache-gb", _gb(8_000)) == 0  # A and B fit, C would pass it
    assert set(_cached(lb)) == {A, B}
    assert C not in [s["id"] for s in fake.streamed]
    out = capsys.readouterr().out
    assert "cache is full" in out and "videos infer" in out
    assert sum(p.stat().st_size for p in _cache(lb).iterdir() if p.is_file()) <= 8_000


def test_a_file_bigger_than_the_cap_is_refused_and_said_so(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run("videos", "fetch") == 0  # the default cap: 8 GB
    out = capsys.readouterr().out
    assert "Home 09" in out and "9.0 GB" in out and "8.0 GB" in out and "--cache-gb" in out
    assert BIG not in [s["id"] for s in fake.streamed]
    assert set(_cached(lb)) == {A, B, C}


def test_the_cap_given_is_kept_for_the_next_run(lb: Logbook, fake: Fake) -> None:
    assert _run("videos", "fetch", "--cache-gb", _gb(3_500), "--limit", "1") == 0
    assert _state(lb)["cap_bytes"] == 3_500
    assert _run("videos", "fetch") == 0  # still 3,500 bytes: B does not fit beside A
    assert set(_cached(lb)) == {A}


def test_limit_fetches_at_most_n_files(lb: Logbook, fake: Fake) -> None:
    assert _run("videos", "fetch", "--limit", "2") == 0
    assert set(_cached(lb)) == {A, B}


def test_a_dropped_connection_is_resumed_from_where_it_stopped(lb: Logbook, fake: Fake) -> None:
    fake.cut_after = 1_000
    assert _run("videos", "fetch", "--limit", "1") == 0
    assert _cached(lb) == {A: MEDIA[A]}
    asked = [s for s in fake.streamed if s["id"] == A]
    assert asked[0]["range"] is None
    assert asked[1]["range"] == "bytes=1000-"


def test_a_part_an_earlier_run_left_is_resumed_and_verified_whole(lb: Logbook, fake: Fake) -> None:
    _cache(lb).mkdir(parents=True, exist_ok=True)
    (_cache(lb) / f"{A}.part").write_bytes(MEDIA[A][:1234])
    assert _run("videos", "fetch", "--limit", "1") == 0
    assert fake.streamed[0] == {"id": A, "range": "bytes=1234-", "keys": None}
    assert _cached(lb) == {A: MEDIA[A]}


def test_a_part_that_is_already_whole_is_verified_and_kept(lb: Logbook, fake: Fake) -> None:
    _cache(lb).mkdir(parents=True, exist_ok=True)
    (_cache(lb) / f"{A}.part").write_bytes(MEDIA[A])
    assert _run("videos", "fetch", "--limit", "1") == 0
    assert _cached(lb) == {A: MEDIA[A]}


def test_bytes_that_do_not_match_the_md5_are_never_kept(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.media[A] = MEDIA[A].replace(b"first", b"fifth")  # the same length, other bytes
    assert _run("videos", "fetch", "--limit", "1") == 1
    assert _cached(lb) == {}
    assert not list(_cache(lb).glob("*.part"))
    assert "md5" in capsys.readouterr().err


def test_the_resource_key_is_sent_for_a_file_that_has_one(lb: Logbook, fake: Fake) -> None:
    assert _run("videos", "fetch", "--limit", "2") == 0
    keys = {s["id"]: s["keys"] for s in fake.streamed}
    assert keys == {A: None, B: f"{B}/0-SyntheticResourceKeyB"}


def test_bytes_are_read_with_the_files_scope_and_nothing_is_listed(lb: Logbook, fake: Fake) -> None:
    assert _run("videos", "fetch", "--limit", "1") == 0
    assert {a["scope"] for a in fake.assertions} == {FILES_SCOPE}
    assert fake.calls("www.googleapis.com/drive/v3/files") == []


def test_without_the_scope_delegated_it_says_where_to_grant_it(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.delegated.discard(FILES_SCOPE)
    assert _run("videos", "fetch", "--limit", "1") == 1
    err = capsys.readouterr().err
    assert "drive.readonly" in err and "Domain-wide delegation" in err
    assert _cached(lb) == {}


def test_a_file_already_inferred_is_not_fetched_again(lb: Logbook, fake: Fake) -> None:
    video = next(line for line in lb.lines() if line["kind"] == "video" and line["payload"]["raw_id"] == A)
    lb.append(
        "2026-10-14T20:00:00Z",
        "model:video-rules/1",
        "draft",
        2,
        {
            "schema": "draft/v1",
            "unit": "event",
            "subject": [videos.scene_ref(str(video["id"]), 0.0, 12.5)],
            "read_head": lb.meta["head"],
            "read_count": 1,
            "language": "en",
            "segments": [{"text": "Nothing places or dates this scene.", "evidence": [str(video["id"])]}],
        },
    )
    assert _run("videos", "fetch", "--limit", "1") == 0
    assert set(_cached(lb)) == {B}


def test_a_fetch_with_nothing_to_do_says_so(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run("videos", "fetch", "--cache-gb", _gb(20_000)) == 0
    capsys.readouterr()
    assert _run("videos", "fetch", "--cache-gb", _gb(20_000)) == 0
    assert "nothing to fetch" in capsys.readouterr().out
