"""`logbook sync drive --videos`: one `video/v1` line per video file in the family's Drive folder and its
subfolders, from Drive's metadata alone. No byte of a video is asked for; the photos and lists beside
them are never listed; Drive's created and modified times are the upload's and are kept as such, never
as when anything was filmed; the run pages, stops on a quota answer with one line and its watermark
kept, and writes each Drive id once.

The folder is the synthetic family's of Ines Nordmann of Oslo (who does not exist), in the in-process
fake of `tests/google_fake.py`: digitised tapes and a DVD, a subfolder of photos, a list."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from google_fake import FOLDER_MIME, USER, Fake, private_key, write_key

from logbook import cli
from logbook.contrib.adapters import drive_videos, service_account
from logbook.core.store import Logbook

KEY_ENV, USER_ENV = service_account.KEY_ENV, service_account.USER_ENV
FOLDER_ENV = "LOGBOOK_DRIVE_VIDEOS_FOLDER"
NOW = "2026-10-14T19:30:00Z"  # when the sync runs: the line's `at`
ROOT = "1FamilyVideosFolderSynthetic01"
DVD = "1DvdSubfolderSynthetic0000001"
PHOTOS = "1PhotoSubfolderSynthetic00001"
PHOTOS_1994 = "1PhotoSubfolder1994Synthetic1"
HOME_01 = "1HomeTape01SyntheticVideoId01"
TAPE_14 = "1Tape14SyntheticVideoId000014"
DVD_03 = "1Dvd03SyntheticVideoId0000003"
UPLOADED = "2019-03-02T10:00:00.000Z"  # when the tapes were digitised and put in Drive: never the filming

FILES: dict[str, dict[str, Any]] = {
    ROOT: {"id": ROOT, "name": "Familiens videoer", "mimeType": FOLDER_MIME, "parents": ["0AOwnerRoot"]},
    HOME_01: {
        "id": HOME_01,
        "name": "Home 01",
        "mimeType": "video/mp4",
        "parents": [ROOT],
        "size": "3221225472",
        "md5Checksum": "0f343b0931126a20f133d67c2b018a3b",
        "createdTime": UPLOADED,
        "modifiedTime": "2019-03-02T10:41:12.000Z",
        "videoMediaMetadata": {"width": 720, "height": 576, "durationMillis": "4012480"},
    },
    TAPE_14: {
        "id": TAPE_14,
        "name": "14",
        "mimeType": "video/mp4",
        "parents": [ROOT],
        "size": "2147483648",
        "md5Checksum": "5eb63bbbe01eeed093cb22bb8f5acdc3",
        "createdTime": "2018-11-20T08:15:00.000Z",
        "modifiedTime": "2018-11-20T08:15:00.000Z",
        "description": "kassett fra hytta",
        "resourceKey": "0-SyntheticResourceKey14",
        "videoMediaMetadata": {"width": 720, "height": 576, "durationMillis": "3600000"},
    },
    DVD: {"id": DVD, "name": "DVD", "mimeType": FOLDER_MIME, "parents": [ROOT]},
    DVD_03: {
        "id": DVD_03,
        "name": "DVD 03",
        "mimeType": "video/mp4",
        "parents": [DVD],
        "size": "4000000000",
        "md5Checksum": "e4d909c290d0fb1ca068ffaddf22cbd0",
        "createdTime": "2020-01-05T12:00:00.000Z",
        "modifiedTime": "2020-01-05T12:00:00.000Z",
    },
    PHOTOS: {"id": PHOTOS, "name": "Bilder", "mimeType": FOLDER_MIME, "parents": [ROOT]},
    PHOTOS_1994: {"id": PHOTOS_1994, "name": "1994", "mimeType": FOLDER_MIME, "parents": [PHOTOS]},
    "1PhotoJpegSynthetic000000001": {
        "id": "1PhotoJpegSynthetic000000001",
        "name": "hytta.jpg",
        "mimeType": "image/jpeg",
        "parents": [PHOTOS],
        "createdTime": UPLOADED,
        "modifiedTime": UPLOADED,
    },
    "1PhotoJpegSynthetic000000002": {
        "id": "1PhotoJpegSynthetic000000002",
        "name": "jul.jpg",
        "mimeType": "image/jpeg",
        "parents": [PHOTOS_1994],
        "createdTime": UPLOADED,
        "modifiedTime": UPLOADED,
    },
    "1ListDocSynthetic00000000001": {
        "id": "1ListDocSynthetic00000000001",
        "name": "Hva er på kassettene",
        "mimeType": "application/vnd.google-apps.document",
        "parents": [ROOT],
        "createdTime": UPLOADED,
        "modifiedTime": UPLOADED,
    },
    "1TrashedVideoSynthetic000001": {
        "id": "1TrashedVideoSynthetic000001",
        "name": "Home 01 (kopi)",
        "mimeType": "video/mp4",
        "parents": [ROOT],
        "trashed": True,
        "createdTime": UPLOADED,
        "modifiedTime": UPLOADED,
    },
}
VIDEOS = {HOME_01, TAPE_14, DVD_03}


@pytest.fixture(scope="module")
def key() -> Any:
    return private_key()


@pytest.fixture
def fake(tmp_path: Path, key: Any, monkeypatch: pytest.MonkeyPatch, no_network: list[str]) -> Any:
    server = Fake(key, files=json.loads(json.dumps(FILES)))
    server.waits = []  # type: ignore[attr-defined]
    monkeypatch.setattr(service_account, "send", server)
    monkeypatch.setattr(service_account, "open_stream", server.stream)
    monkeypatch.setattr(service_account, "sleep", server.waits.append)  # type: ignore[attr-defined]
    monkeypatch.setattr(drive_videos, "_now", lambda: drive_videos._instant(NOW))
    monkeypatch.setenv(KEY_ENV, str(write_key(tmp_path / "google-sa.json", key)))
    monkeypatch.setenv(USER_ENV, USER)
    monkeypatch.setenv(FOLDER_ENV, ROOT)
    yield server
    assert no_network == [], "the fake is the only way out"


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    return lb


def _sync(*args: str) -> int:
    try:
        cli.main(["sync", *args])
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    return 0


def _videos(lb: Logbook) -> dict[str, dict[str, Any]]:
    return {
        line["payload"]["raw_id"]: line
        for line in lb.lines()
        if line["source"] == drive_videos.NAME and line["kind"] == drive_videos.KIND
    }


def _state(lb: Logbook) -> dict[str, Any]:
    return json.loads((lb.root / "state" / f"{drive_videos.NAME}.json").read_text(encoding="utf-8"))


def test_one_line_per_video_file_in_the_folder_and_its_subfolders(fake: Fake, lb: Logbook) -> None:
    assert _sync("drive", "--videos") == 0
    found = _videos(lb)
    assert set(found) == VIDEOS
    home = found[HOME_01]
    assert {k: home[k] for k in ("at", "end", "tz", "source", "kind", "tier")} == {
        "at": NOW,
        "end": None,
        "tz": "Europe/Oslo",
        "source": "drive-videos",
        "kind": "video",
        "tier": 2,
    }
    assert home["payload"] == {
        "schema": "video/v1",
        "raw_id": HOME_01,
        "library": "google-drive",
        "title": "Home 01",
        "file": {
            "id": HOME_01,
            "name": "Home 01",
            "path": ["Familiens videoer"],
            "mime_type": "video/mp4",
            "url": f"https://drive.google.com/file/d/{HOME_01}/view",
        },
        "bytes": 3221225472,
        "duration_s": 4012.48,
        "width": 720,
        "height": 576,
        "digest": {"md5": "0f343b0931126a20f133d67c2b018a3b"},
        "extra": {"drive_created": "2019-03-02T10:00:00Z", "drive_modified": "2019-03-02T10:41:12Z"},
    }
    assert found[DVD_03]["payload"]["file"]["path"] == ["Familiens videoer", "DVD"]
    assert "description" not in home["payload"]
    assert found[TAPE_14]["payload"]["description"] == "kassett fra hytta"


def test_no_byte_is_downloaded_and_only_the_metadata_scope_is_asked(fake: Fake, lb: Logbook) -> None:
    assert _sync("drive", "--videos") == 0
    assert fake.streamed == [], "sync drive --videos asked for a file's bytes"
    assert fake.methods() == {("GET", "www.googleapis.com"), ("POST", "oauth2.googleapis.com")}
    assert {a["scope"] for a in fake.assertions} == {service_account.SCOPES["drive paths"]}
    for _method, _path, params in fake.requests:
        assert params.get("alt") != "media"


def test_the_photos_and_the_lists_beside_the_videos_are_never_listed(fake: Fake, lb: Logbook) -> None:
    assert _sync("drive", "--videos") == 0
    assert set(_videos(lb)) == VIDEOS
    photos_and_lists = {i for i, f in FILES.items() if f["mimeType"] not in (FOLDER_MIME, "video/mp4")}
    assert not photos_and_lists & set(fake.listed), "a photo or a list was listed"
    assert "1TrashedVideoSynthetic000001" not in fake.listed
    assert PHOTOS in fake.listed and PHOTOS_1994 in fake.listed  # walked, and nothing in it written


def test_drives_times_are_the_upload_never_the_filming(fake: Fake, lb: Logbook) -> None:
    assert _sync("drive", "--videos") == 0
    for line in _videos(lb).values():
        extra = line["payload"]["extra"]
        assert line["at"] == NOW
        assert line["at"] not in (extra["drive_created"], extra["drive_modified"])
        assert line["end"] is None
        assert set(extra) == {"drive_created", "drive_modified"}
    assert _videos(lb)[TAPE_14]["payload"]["extra"]["drive_created"] == "2018-11-20T08:15:00Z"


def test_a_file_with_a_resource_key_is_written_and_nothing_fails_on_it(fake: Fake, lb: Logbook) -> None:
    assert _sync("drive", "--videos") == 0
    assert _videos(lb)[TAPE_14]["payload"]["file"]["resource_key"] == "0-SyntheticResourceKey14"


def test_it_pages(fake: Fake, lb: Logbook) -> None:
    fake.page = 1
    assert _sync("drive", "--videos") == 0
    assert set(_videos(lb)) == VIDEOS
    tokens = [p.get("pageToken") for p in fake.calls("www.googleapis.com/drive/v3/files")]
    assert len([t for t in tokens if t]) == 3  # the root lists four children, one a page


def test_a_second_run_writes_nothing_twice(
    fake: Fake, lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _sync("drive", "--videos") == 0
    seq = int(lb.meta["seq"])
    capsys.readouterr()
    assert _sync("drive", "--videos") == 0
    assert int(Logbook(lb.root).meta["seq"]) == seq
    assert "0 new lines of 3 seen" in capsys.readouterr().out


def test_a_quota_answer_stops_with_one_line_and_keeps_the_watermark(
    fake: Fake, lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _sync("drive", "--videos") == 0
    mark = _state(lb)["since"]
    assert mark == "2020-01-05T12:00:00Z"  # the newest modified time a line holds
    fake.files["1NewTapeSyntheticVideoId0015"] = {
        **FILES[HOME_01],
        "id": "1NewTapeSyntheticVideoId0015",
        "name": "15",
        "modifiedTime": "2026-10-01T09:00:00.000Z",
        "md5Checksum": "9e107d9d372bb6826bd81d3542a419d6",
    }
    capsys.readouterr()
    fake.fail(403, reason="dailyLimitExceeded")
    assert _sync("drive", "--videos") == 1
    err = capsys.readouterr().err.strip().splitlines()
    quota = [line for line in err if "quota" in line]
    assert len(quota) == 1, err
    assert "LOGBOOK" not in quota[0] and "Traceback" not in "\n".join(err)
    assert _state(lb)["since"] == mark
    assert "1NewTapeSyntheticVideoId0015" not in _videos(lb)


def test_a_quota_answer_part_way_keeps_what_was_listed_and_the_watermark(
    fake: Fake, lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.page = 2
    original = fake._list
    asked = {"n": 0}

    def listing(scope: str, params: dict[str, Any]) -> Any:
        asked["n"] += 1
        if asked["n"] == 3:  # the root's two pages, then Drive says no more today
            fake.fail(429, reason="rateLimitExceeded")
            for _ in range(service_account.RETRIES):
                fake.fail(429, reason="rateLimitExceeded")
        return original(scope, params)

    fake._list = listing  # type: ignore[method-assign]
    assert _sync("drive", "--videos") == 1
    err = capsys.readouterr().err
    assert sum("quota" in line for line in err.splitlines()) == 1, err
    written = set(_videos(lb))
    assert written and written < VIDEOS
    assert not (lb.root / "state" / f"{drive_videos.NAME}.json").exists()  # no watermark written yet


def test_without_the_folder_it_says_which_variable_to_set(
    fake: Fake, lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(FOLDER_ENV)
    assert _sync("drive", "--videos") == 2
    assert FOLDER_ENV in capsys.readouterr().err
    assert fake.requests == []


def test_a_folder_id_that_is_not_one_is_refused_before_anything_is_asked(
    fake: Fake, lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(FOLDER_ENV, "https://drive.google.com/drive/folders/../x")
    assert _sync("drive", "--videos") == 2
    assert FOLDER_ENV in capsys.readouterr().err
    assert fake.requests == []


def test_videos_is_drives_flag_alone(fake: Fake, lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    assert _sync("gmail", "--videos") == 2
    assert "sync drive --videos" in capsys.readouterr().err
    assert _sync("--all", "--videos") == 2


def test_plain_sync_drive_is_unchanged_and_writes_no_video_line(fake: Fake, lb: Logbook) -> None:
    assert _sync("drive") == 0
    assert _videos(lb) == {}


def test_the_config_never_prints_the_folder_or_the_key(fake: Fake, lb: Logbook) -> None:
    import os

    config = drive_videos.configure(os.environ)
    assert config is not None
    assert ROOT not in repr(config) and USER not in repr(config)


# -- Drive's clock and the line's, with a later run (the size-and-dates check's tests) -----------------

LATER = "2026-11-02T08:00:00Z"
NEW = "1NewTapeSyntheticVideoId0015"


def test_since_is_not_a_filter_and_never_a_lines_at(fake: Fake, lb: Logbook) -> None:
    assert _sync("drive", "--videos", "--since", "2030-01-01T00:00:00Z") == 0
    found = _videos(lb)
    assert set(found) == VIDEOS
    assert {line["at"] for line in found.values()} == {NOW}


def test_a_dry_run_writes_nothing_and_streams_nothing(fake: Fake, lb: Logbook) -> None:
    assert _sync("drive", "--videos", "--dry-run") == 0
    assert _videos(lb) == {} and fake.streamed == []
    assert not (lb.root / "state" / f"{drive_videos.NAME}.json").exists()


def test_a_later_run_moves_the_watermark_and_no_lines_at(
    fake: Fake, lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _sync("drive", "--videos") == 0
    before = {k: (v["at"], v["hash"]) for k, v in _videos(lb).items()}
    fake.files[NEW] = {
        **FILES[HOME_01],
        "id": NEW,
        "name": "15",
        "createdTime": "2026-10-01T09:00:00.000Z",
        "modifiedTime": "2026-10-01T09:00:00.000Z",
        "md5Checksum": "9e107d9d372bb6826bd81d3542a419d6",
    }
    monkeypatch.setattr(drive_videos, "_now", lambda: drive_videos._instant(LATER))
    assert _sync("drive", "--videos") == 0
    after = _videos(lb)
    assert {k: (v["at"], v["hash"]) for k, v in after.items() if k != NEW} == before
    assert after[NEW]["at"] == LATER  # when the record learned of it, not Drive's 2026-10-01
    assert after[NEW]["payload"]["extra"]["drive_modified"] == "2026-10-01T09:00:00Z"
    assert _state(lb)["since"] == "2026-10-01T09:00:00Z"  # the watermark is Drive's clock; no line's at is


def test_a_rate_limit_on_the_very_first_call_is_one_line_and_the_watermark_kept(
    fake: Fake, lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _sync("drive", "--videos") == 0
    mark = _state(lb)["since"]
    capsys.readouterr()
    for _ in range(service_account.RETRIES + 1):
        fake.fail(429, reason="rateLimitExceeded")
    assert _sync("drive", "--videos") == 1
    err = capsys.readouterr().err
    assert sum("quota" in line for line in err.splitlines()) == 1, err
    assert "Traceback" not in err
    assert _state(lb)["since"] == mark


def test_no_field_of_the_line_but_extra_carries_drives_clock(fake: Fake, lb: Logbook) -> None:
    assert _sync("drive", "--videos") == 0
    for line in _videos(lb).values():
        payload = dict(line["payload"])
        extra = payload.pop("extra")
        text = str(line["at"]) + str(line["end"]) + str(line["recorded_at"]) + repr(payload)
        for stamp in extra.values():
            assert stamp[:10] not in text, (stamp, line)
