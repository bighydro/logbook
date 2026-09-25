"""Google Takeout → photo/v1: the "Google Photos/" folder, one line per media file, pixels never copied."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters
from logbook.adapters.takeout import location, photos
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "tests" / "fixtures" / "takeout" / "Records.json"
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
PROVENANCES = {"camera", "received", "screenshot", "other"}

# Synthetic: the sample person lives in Oslo and does not exist (CLAUDE.md).
OSLO = {"latitude": 59.913, "longitude": 10.742, "altitude": 14.0}
NO_GEO = {"latitude": 0.0, "longitude": 0.0, "altitude": 0.0}
LONG_NAME = "A_photo_with_a_very_long_file_name_that_google_truncates_2026.JPG"
LONG_SIDECAR = LONG_NAME[:46] + ".json"  # Google keeps the first 46 characters, then ".json"
URL = "https://photos.google.com/photo/AF1QipSyntheticPhotoId0001"


def _seconds(stamp: str) -> str:
    """Takeout writes unix seconds as a string."""
    return str(int(datetime.fromisoformat(stamp).timestamp()))


def _sidecar(
    title: str,
    taken: str | None,
    created: str,
    *,
    geo: dict | None = OSLO,
    origin: dict | str | None = None,
    people: list[str] = (),
    description: str = "",
    url: str | None = None,
    views: str = "0",
) -> dict:
    doc: dict = {
        "title": title,
        "description": description,
        "imageViews": views,
        "creationTime": {"timestamp": _seconds(created), "formatted": created},
        "geoData": dict(geo or NO_GEO),
        "geoDataExif": dict(geo or NO_GEO),
    }
    if taken is not None:
        doc["photoTakenTime"] = {"timestamp": _seconds(taken), "formatted": taken}
    if url is not None:
        doc["url"] = url
    if people:
        doc["people"] = [{"name": name} for name in people]
    if origin is not None:
        doc["googlePhotosOrigin"] = {origin: {}} if isinstance(origin, str) else origin
    return doc


def _write(folder: Path, name: str, content: bytes | dict) -> Path:
    p = folder / name
    if isinstance(content, dict):
        p.write_text(json.dumps(content, indent=2), encoding="utf-8")
    else:
        p.write_bytes(content)
    return p


def build_takeout(root: Path) -> Path:
    """A small Takeout with two albums; returns the Takeout root (the parent of "Google Photos/").

    Album "Photos from 2026": a live-photo pair (HEIC + MOV, each with an old-style `<name>.json`
    sidecar), a JPEG with a `.supplemental-metadata.json` sidecar and zero geo, a long name whose
    sidecar Google truncated, an edited copy with no sidecar, a sidecar with no file, and the album's
    own `metadata.json`, which is not a sidecar.

    Album "Oslo weekend": a photo from a shared album, a video with no photoTakenTime, a duplicate-
    numbered pair `IMG_0006(1).JPG` + `IMG_0006.JPG(1).json`, and a sidecar whose
    `.supplemental-metadata` suffix Google cut short."""
    takeout = root / "Takeout"
    album1 = takeout / "Google Photos" / "Photos from 2026"
    album2 = takeout / "Google Photos" / "Oslo weekend"
    album1.mkdir(parents=True)
    album2.mkdir(parents=True)
    _write(takeout, "archive_browser.html", b"<html></html>")

    _write(album1, "metadata.json", {"title": "Photos from 2026", "access": "protected", "date": {}})
    _write(album1, "IMG_0001.HEIC", b"heic-still-bytes")
    _write(
        album1,
        "IMG_0001.HEIC.json",
        _sidecar(
            "IMG_0001.HEIC",
            "2026-03-01T09:12:00Z",
            "2026-03-01T09:13:00Z",
            origin={"mobileUpload": {"deviceType": "IOS_PHONE"}},
            people=["Kari Nordmann", "Ola Nordmann"],
            url=URL,
            views="3",
        ),
    )
    _write(album1, "IMG_0001.MOV", b"mov-motion-bytes")
    _write(
        album1,
        "IMG_0001.MOV.json",
        _sidecar("IMG_0001.MOV", "2026-03-01T09:12:00Z", "2026-03-01T09:13:00Z", origin="mobileUpload"),
    )
    _write(album1, "IMG_0002.JPG", b"jpeg-bytes-0002")
    _write(
        album1,
        "IMG_0002.JPG.supplemental-metadata.json",
        _sidecar(
            "IMG_0002.JPG",
            "2026-03-01T14:03:30Z",
            "2026-03-01T14:04:00Z",
            geo=None,
            origin="webUpload",
            description="Lunch by the fjord",
        ),
    )
    _write(album1, LONG_NAME, b"jpeg-bytes-long")
    _write(album1, LONG_SIDECAR, _sidecar(LONG_NAME, "2026-03-02T10:00:00Z", "2026-03-02T10:00:00Z"))
    edited = _write(album1, "IMG_0003-edited.JPG", b"jpeg-bytes-edited")
    os.utime(edited, (1772301600, 1772301600))  # 2026-02-28T18:00:00Z
    _write(
        album1, "IMG_0004.JPG.json", _sidecar("IMG_0004.JPG", "2026-03-01T12:00:00Z", "2026-03-01T12:00:00Z")
    )

    _write(album2, "metadata.json", {"title": "Oslo weekend", "access": "protected", "date": {}})
    _write(album2, "IMG_0005.JPG", b"jpeg-bytes-0005")
    _write(
        album2,
        "IMG_0005.JPG.supplemental-metadata.json",
        _sidecar("IMG_0005.JPG", "2026-03-07T11:00:00Z", "2026-03-08T09:00:00Z", origin="fromSharedAlbum"),
    )
    _write(album2, "clip.mp4", b"mp4-bytes")
    _write(
        album2,
        "clip.mp4.supplemental-metadata.json",
        _sidecar("clip.mp4", None, "2026-03-07T16:30:00Z", origin="mobileUpload"),
    )
    _write(album2, "IMG_0006(1).JPG", b"jpeg-bytes-0006-dup")
    _write(
        album2,
        "IMG_0006.JPG(1).json",
        _sidecar("IMG_0006.JPG", "2026-03-07T17:00:00Z", "2026-03-07T17:00:00Z"),
    )
    _write(album2, "IMG_0007.JPG", b"jpeg-bytes-0007")
    _write(
        album2,
        "IMG_0007.JPG.supplemental-met.json",
        _sidecar("IMG_0007.JPG", "2026-03-07T18:00:00Z", "2026-03-07T18:00:00Z", origin="mobileUpload"),
    )
    return takeout


@pytest.fixture
def takeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("LOGBOOK_TAKEOUT_HASH_MEDIA", raising=False)
    return build_takeout(tmp_path)


@pytest.fixture
def google_photos(takeout: Path) -> Path:
    return takeout / "Google Photos"


def _by_name(lines: list[dict]) -> dict[str, dict]:
    return {line["payload"]["file_name"]: line for line in lines}


def _snapshot(folder: Path) -> dict[str, tuple[str, int]]:
    return {
        p.relative_to(folder).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


# -- registry ---------------------------------------------------------------


def test_registry_lists_google_takeout_photos():
    names = [a.NAME for a in adapters.all_adapters()]
    assert "google-takeout-photos" in names and "google-takeout-location" in names


def test_takeout_package_registers_photos_beside_location():
    from logbook.adapters import takeout as package

    assert package.SUB_ADAPTERS == ("location", "photos")
    assert photos.SOURCE == location.SOURCE == "google-takeout"


def test_registry_find_returns_photos_for_the_folder(google_photos):
    found = adapters.find(google_photos)
    assert found is not None and found.NAME == "google-takeout-photos"


def test_registry_find_still_returns_location_for_records():
    found = adapters.find(RECORDS)
    assert found is not None and found.NAME == "google-takeout-location"


# -- sniff ------------------------------------------------------------------


def test_sniff_accepts_the_google_photos_folder(google_photos):
    assert photos.sniff(google_photos) is True


def test_sniff_accepts_a_takeout_root_that_contains_google_photos(takeout):
    assert photos.sniff(takeout) is True


def test_sniff_accepts_one_album_folder(google_photos):
    assert photos.sniff(google_photos / "Oslo weekend") is True


def test_sniff_rejects_files_and_folders_without_sidecars(tmp_path, google_photos):
    assert photos.sniff(RECORDS) is False
    assert photos.sniff(google_photos / "Oslo weekend" / "IMG_0005.JPG") is False
    assert photos.sniff(tmp_path / "nope") is False
    empty = tmp_path / "empty"
    empty.mkdir()
    assert photos.sniff(empty) is False
    other = tmp_path / "other"
    other.mkdir()
    (other / "metadata.json").write_text('{"title": "x"}', encoding="utf-8")
    (other / "notes.json").write_text("not json", encoding="utf-8")
    (other / "a.jpg").write_bytes(b"x")
    assert photos.sniff(other) is False


def test_sniff_never_raises_on_an_unreadable_folder(tmp_path):
    p = tmp_path / "file.json"
    p.write_text('{"photoTakenTime": {"timestamp": "1"}}', encoding="utf-8")
    assert photos.sniff(p) is False  # a file, not a folder
    assert location.sniff(tmp_path) is False  # and the sibling still says no to a folder


# -- run: envelope -----------------------------------------------------------


def test_run_yields_one_photo_line_per_media_file(google_photos):
    lines = list(photos.run(google_photos))
    assert len(lines) == 8
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["end"] is None and line["tz"] is None
        assert line["source"] == "google-takeout"
        assert line["kind"] == "photo" and line["tier"] == 1
        p = line["payload"]
        assert p["schema"] == "photo/v1" and p["library"] == "google-photos"
        assert p["asset_id"] == p["raw_id"]
        json.dumps(line, allow_nan=False)
    assert sorted(_by_name(lines)) == sorted(
        [
            "IMG_0001.HEIC",
            "IMG_0002.JPG",
            LONG_NAME,
            "IMG_0003-edited.JPG",
            "IMG_0005.JPG",
            "clip.mp4",
            "IMG_0006(1).JPG",
            "IMG_0007.JPG",
        ]
    )


def test_run_orders_albums_and_files_by_name(google_photos):
    albums = [line["payload"]["extra"]["album"] for line in photos.run(google_photos)]
    assert albums == ["Oslo weekend"] * 4 + ["Photos from 2026"] * 4


def test_run_from_the_takeout_root_finds_google_photos(takeout, google_photos):
    assert list(photos.run(takeout)) == list(photos.run(google_photos))


def test_run_on_one_album_folder_uses_its_name(google_photos):
    lines = list(photos.run(google_photos / "Oslo weekend"))
    assert len(lines) == 4 and {line["payload"]["extra"]["album"] for line in lines} == {"Oslo weekend"}
    assert lines[0]["payload"]["extra"]["media"]["local_path"] == "IMG_0005.JPG"


def test_run_since_filters_on_at(google_photos):
    lines = list(photos.run(google_photos, since="2026-03-07T00:00:00Z"))
    assert lines and all(line["at"] >= "2026-03-07T00:00:00Z" for line in lines)
    assert len(lines) == 4


# -- run: mapping ---------------------------------------------------------------


def test_sidecar_maps_taken_time_place_people_views_and_url_id(google_photos):
    line = _by_name(list(photos.run(google_photos)))["IMG_0001.HEIC"]
    assert line["at"] == "2026-03-01T09:12:00Z"
    p = line["payload"]
    assert p["raw_id"] == "AF1QipSyntheticPhotoId0001"
    assert p["media"] == "image"
    assert p["lat"] == 59.913 and p["lon"] == 10.742
    assert p["provenance"] == "camera" and p["live_photo"] is True
    assert p["faces"] == 2
    assert "people" not in p  # RFC 0002: ids only there, and Takeout has none
    extra = p["extra"]
    assert extra["album"] == "Photos from 2026"
    assert extra["people"] == [
        {"kind": "name", "value": "Kari Nordmann"},
        {"kind": "name", "value": "Ola Nordmann"},
    ]
    assert extra["origin"] == "mobileUpload"
    assert extra["url"] == URL
    assert extra["image_views"] == 3
    assert extra["altitude"] == 14.0
    assert extra["sidecar"] == "IMG_0001.HEIC.json"
    assert extra["taken_from"] == "photoTakenTime"
    assert "caption" not in extra and "no_sidecar" not in extra


def test_live_photo_pair_is_one_camera_line_with_the_motion_half_under_extra(google_photos):
    counts: dict[str, int] = {}
    lines = _by_name(list(photos.run(google_photos, counts=counts)))
    assert "IMG_0001.MOV" not in lines
    extra = lines["IMG_0001.HEIC"]["payload"]["extra"]
    assert extra["live_video"]["local_path"] == "Photos from 2026/IMG_0001.MOV"
    assert extra["live_video"]["sha256"] == hashlib.sha256(b"mov-motion-bytes").hexdigest()
    assert extra["live_video"]["bytes"] == 16
    assert extra["live_video"]["media_type"] == "video/quicktime"
    assert counts["live_photo_pairs"] == 1


def test_supplemental_metadata_sidecar_zero_geo_and_caption(google_photos):
    line = _by_name(list(photos.run(google_photos)))["IMG_0002.JPG"]
    assert line["at"] == "2026-03-01T14:03:30Z"
    p = line["payload"]
    assert "lat" not in p and "lon" not in p
    assert p["provenance"] == "other" and p["live_photo"] is False
    assert p["faces"] == 0 and "people" not in p["extra"]
    assert p["raw_id"] == "Photos from 2026/IMG_0002.JPG"
    assert p["extra"]["caption"] == "Lunch by the fjord"
    assert p["extra"]["origin"] == "webUpload"
    assert p["extra"]["sidecar"] == "IMG_0002.JPG.supplemental-metadata.json"
    assert "altitude" not in p["extra"] and "url" not in p["extra"]


def test_truncated_sidecar_name_still_matches_its_file(google_photos):
    line = _by_name(list(photos.run(google_photos)))[LONG_NAME]
    assert line["at"] == "2026-03-02T10:00:00Z"
    assert line["payload"]["extra"]["sidecar"] == LONG_SIDECAR


def test_truncated_supplemental_suffix_matches_its_file(google_photos):
    line = _by_name(list(photos.run(google_photos)))["IMG_0007.JPG"]
    assert line["at"] == "2026-03-07T18:00:00Z"
    assert line["payload"]["provenance"] == "camera"
    assert line["payload"]["extra"]["sidecar"] == "IMG_0007.JPG.supplemental-met.json"


def test_truncated_sidecar_without_a_title_matches_by_unique_prefix(tmp_path):
    album = tmp_path / "Album"
    album.mkdir()
    _write(album, LONG_NAME, b"x")
    doc = _sidecar("", "2026-03-02T10:00:00Z", "2026-03-02T10:00:00Z")
    del doc["title"]
    _write(album, LONG_SIDECAR, doc)
    (line,) = photos.run(album)
    assert line["payload"]["extra"]["sidecar"] == LONG_SIDECAR and line["at"] == "2026-03-02T10:00:00Z"


def test_short_sidecar_name_never_matches_by_prefix(tmp_path):
    """`a.json` is not the sidecar of `abc.jpg`: only a name Google cut at 46 characters matches by prefix."""
    album = tmp_path / "Album"
    album.mkdir()
    _write(album, "abc.jpg", b"x")
    _write(album, "a.json", _sidecar("a.jpg", "2026-03-02T10:00:00Z", "2026-03-02T10:00:00Z"))
    counts: dict[str, int] = {}
    (line,) = photos.run(album, counts=counts)
    assert line["payload"]["extra"]["no_sidecar"] is True
    assert counts["skipped_sidecar_without_file"] == 1


def test_a_large_json_file_is_never_read(tmp_path, monkeypatch):
    """The Location History folder holds a multi-gigabyte Records.json; sniff and run must not load it."""
    monkeypatch.setattr(photos, "SIDECAR_MAX_BYTES", 64)
    folder = tmp_path / "Location History (Timeline)"
    folder.mkdir()
    big = _sidecar("IMG_0001.JPG", "2026-03-02T10:00:00Z", "2026-03-02T10:00:00Z")
    _write(folder, "Records.json", big)
    assert (folder / "Records.json").stat().st_size > 64
    assert photos.sniff(folder) is False
    _write(folder, "IMG_0001.JPG", b"x")
    counts: dict[str, int] = {}
    (line,) = photos.run(folder, counts=counts)
    assert line["payload"]["extra"]["no_sidecar"] is True and counts["skipped_unreadable_json"] == 0


def test_duplicate_numbered_sidecar_matches_the_numbered_file(google_photos):
    line = _by_name(list(photos.run(google_photos)))["IMG_0006(1).JPG"]
    assert line["at"] == "2026-03-07T17:00:00Z"
    assert line["payload"]["extra"]["sidecar"] == "IMG_0006.JPG(1).json"
    assert line["payload"]["raw_id"] == "Oslo weekend/IMG_0006(1).JPG"


def test_shared_album_origin_is_received(google_photos):
    p = _by_name(list(photos.run(google_photos)))["IMG_0005.JPG"]["payload"]
    assert p["provenance"] == "received" and p["extra"]["origin"] == "fromSharedAlbum"


def test_video_without_taken_time_falls_back_to_creation_time_and_is_counted(google_photos):
    counts: dict[str, int] = {}
    line = _by_name(list(photos.run(google_photos, counts=counts)))["clip.mp4"]
    assert line["at"] == "2026-03-07T16:30:00Z"
    p = line["payload"]
    assert p["media"] == "video" and p["provenance"] == "camera" and p["live_photo"] is False
    assert p["extra"]["taken_from"] == "creationTime"
    assert p["extra"]["media"]["media_type"] == "video/mp4"
    assert counts["at_from_creation_time"] == 1


def test_file_without_sidecar_is_a_line_at_its_mtime(google_photos):
    counts: dict[str, int] = {}
    line = _by_name(list(photos.run(google_photos, counts=counts)))["IMG_0003-edited.JPG"]
    assert line["at"] == "2026-02-28T18:00:00Z"
    p = line["payload"]
    assert p["raw_id"] == "Photos from 2026/IMG_0003-edited.JPG"
    assert p["provenance"] == "other" and p["faces"] == 0 and p["live_photo"] is False
    assert p["extra"]["no_sidecar"] is True and p["extra"]["taken_from"] == "file_time"
    assert "sidecar" not in p["extra"]
    assert counts["no_sidecar"] == 1


def test_sidecar_without_a_file_is_counted_and_yields_nothing(google_photos):
    counts: dict[str, int] = {}
    names = _by_name(list(photos.run(google_photos, counts=counts)))
    assert "IMG_0004.JPG" not in names
    assert counts["skipped_sidecar_without_file"] == 1


def test_album_metadata_json_is_not_a_sidecar(google_photos):
    counts: dict[str, int] = {}
    lines = list(photos.run(google_photos, counts=counts))
    assert not any(line["payload"]["file_name"] == "metadata.json" for line in lines)
    assert all(line["payload"]["extra"].get("sidecar") != "metadata.json" for line in lines)
    assert {key: n for key, n in counts.items() if n} == {
        "media_hashed": 9,
        "live_photo_pairs": 1,
        "no_sidecar": 1,
        "at_from_creation_time": 1,
        "skipped_sidecar_without_file": 1,
    }


# -- media rule (v1): hash, never copy ----------------------------------------------


def test_media_is_hashed_into_extra_and_payload_media_is_the_kind(google_photos):
    p = _by_name(list(photos.run(google_photos)))["IMG_0002.JPG"]["payload"]
    assert p["media"] == "image"
    assert p["extra"]["media"] == {
        "local_path": "Photos from 2026/IMG_0002.JPG",
        "media_type": "image/jpeg",
        "sha256": hashlib.sha256(b"jpeg-bytes-0002").hexdigest(),
        "bytes": 15,
    }
    assert "media_missing" not in p["extra"]


def test_hash_media_can_be_switched_off(google_photos, monkeypatch):
    monkeypatch.setenv("LOGBOOK_TAKEOUT_HASH_MEDIA", "0")
    counts: dict[str, int] = {}
    lines = list(photos.run(google_photos, counts=counts))
    assert counts["media_hashed"] == 0
    for line in lines:
        media = line["payload"]["extra"]["media"]
        assert "sha256" not in media and "bytes" not in media and "local_path" in media
    live = _by_name(lines)["IMG_0001.HEIC"]["payload"]["extra"]["live_video"]
    assert set(live) == {"local_path", "media_type"}


def test_run_leaves_the_source_folder_byte_identical(takeout):
    before = _snapshot(takeout)
    list(photos.run(takeout))
    list(photos.run(takeout / "Google Photos", since="2026-03-07T00:00:00Z"))
    assert _snapshot(takeout) == before
    assert not any(p.suffix == ".sqlite" or p.name.startswith(".") for p in takeout.rglob("*"))


# -- the log --------------------------------------------------------------------


def test_lines_append_into_a_valid_logbook_and_rerun_appends_nothing(tmp_path, google_photos):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    assert lb.append_many(photos.run(google_photos)) == 8
    assert lb.append_many(photos.run(google_photos)) == 0
    assert lb.append_many(photos.run(google_photos.parent)) == 0  # the same lines from the root
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 8
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
        assert line["tz"] == "Europe/Oslo"


# -- property: every emitted line is a valid photo/v1 observation --------------------


def _rfc_rules(line: dict) -> None:
    assert set(line) == ENVELOPE
    assert line["kind"] == "photo" and line["tier"] == 1 and line["end"] is None
    assert line["source"] == "google-takeout"
    assert line["at"].endswith("Z") and len(line["at"]) == 20
    p = line["payload"]
    assert p["schema"] == "photo/v1"
    assert isinstance(p["asset_id"], str) and p["asset_id"]
    assert p["raw_id"] == p["asset_id"]
    assert p["library"] == "google-photos"
    assert isinstance(p["file_name"], str) and p["file_name"]
    assert p["media"] in {"image", "video"}
    assert ("lat" in p) == ("lon" in p)
    if "lat" in p:
        assert type(p["lat"]) is float and type(p["lon"]) is float
        assert -90 <= p["lat"] <= 90 and -180 <= p["lon"] <= 180
        assert (p["lat"], p["lon"]) != (0.0, 0.0)
    assert p["live_photo"] in (True, False)
    assert p["provenance"] in PROVENANCES
    assert isinstance(p["faces"], int) and p["faces"] >= 0
    assert "people" not in p
    extra = p["extra"]
    assert isinstance(extra["album"], str)
    assert isinstance(extra["media"], dict) and isinstance(extra["media"]["local_path"], str)
    assert set(extra["media"]) <= {"local_path", "media_type", "sha256", "bytes"}
    if "people" in extra:
        assert extra["people"] and all(
            set(ref) == {"kind", "value"} and ref["kind"] == "name" and isinstance(ref["value"], str)
            for ref in extra["people"]
        )
        assert p["faces"] == len(extra["people"])
    if extra.get("no_sidecar"):
        assert extra["taken_from"] == "file_time" and "sidecar" not in extra
    else:
        assert isinstance(extra["sidecar"], str) and extra["taken_from"] in {
            "photoTakenTime",
            "creationTime",
            "file_time",
        }
    json.dumps(line, allow_nan=False)


_unix = st.integers(946_684_800, 2_208_988_800)  # 2000 .. 2040
_stamp = st.one_of(_unix.map(str), _unix, st.text(max_size=6), st.none(), st.floats(allow_nan=False))
_time = st.one_of(st.none(), st.fixed_dictionaries({}, optional={"timestamp": _stamp}), st.text(max_size=3))
_coord = st.one_of(st.floats(-200, 200, allow_nan=False), st.text(max_size=4), st.none())
_geo = st.one_of(
    st.none(),
    st.fixed_dictionaries({}, optional={"latitude": _coord, "longitude": _coord, "altitude": _coord}),
    st.text(max_size=3),
)
_origin = st.one_of(
    st.none(),
    st.sampled_from(
        ["mobileUpload", "webUpload", "fromSharedAlbum", "fromPartnerSharing", "composition"]
    ).map(lambda k: {k: {}}),
    st.text(max_size=5),
    st.dictionaries(st.text(max_size=4), st.text(max_size=2), max_size=2),
)
_people = st.one_of(
    st.none(),
    st.lists(
        st.one_of(st.fixed_dictionaries({"name": st.text(max_size=6)}), st.text(max_size=2), st.none()),
        max_size=3,
    ),
)
_sidecar_doc = st.fixed_dictionaries(
    {},
    optional={
        "title": st.text(max_size=12),
        "description": st.one_of(st.text(max_size=8), st.none(), st.integers()),
        "imageViews": st.one_of(st.integers(0, 99).map(str), st.text(max_size=3), st.integers()),
        "photoTakenTime": _time,
        "creationTime": _time,
        "geoData": _geo,
        "geoDataExif": _geo,
        "people": _people,
        "url": st.one_of(st.none(), st.text(max_size=8), st.just(URL), st.just("https://photos.google.com/")),
        "googlePhotosOrigin": _origin,
    },
)
_item = st.fixed_dictionaries(
    {
        "doc": _sidecar_doc,
        "variant": st.sampled_from(["plain", "supplemental", "truncated", "numbered"]),
        "file_present": st.booleans(),
        "extension": st.sampled_from([".JPG", ".HEIC", ".PNG", ".MP4", ".MOV"]),
        "junk": st.booleans(),
    }
)


def _write_item(album: Path, i: int, item: dict) -> tuple[bool, bool]:
    """Writes one item; returns (a media file exists, a real sidecar exists that names no file)."""
    stem = f"IMG_{i:04d}"
    name = stem + item["extension"]
    if item["file_present"]:
        (album / name).write_bytes(b"bytes-%d" % i)
    variant = item["variant"]
    sidecar_name = {
        "plain": f"{name}.json",
        "supplemental": f"{name}.supplemental-metadata.json",
        "truncated": f"{name}.supplemental-me.json",
        "numbered": f"{name}(1).json",  # its file is IMG_xxxx(1).EXT, which we never write
    }[variant]
    doc = dict(item["doc"])
    if item["junk"]:
        (album / sidecar_name).write_text("{not json", encoding="utf-8")
        return item["file_present"], False
    (album / sidecar_name).write_text(json.dumps(doc, allow_nan=False), encoding="utf-8")
    is_sidecar = isinstance(doc.get("photoTakenTime"), dict) or isinstance(doc.get("creationTime"), dict)
    return item["file_present"], is_sidecar and (variant == "numbered" or not item["file_present"])


@settings(max_examples=40, deadline=None)
@given(st.lists(_item, max_size=6))
def test_any_album_yields_only_valid_lines(tmp_path_factory, items):
    album = tmp_path_factory.mktemp("takeout") / "Google Photos" / "Album"
    album.mkdir(parents=True)
    files = orphans = 0
    for i, item in enumerate(items):
        present, orphan = _write_item(album, i, item)
        files += present
        orphans += orphan
    counts: dict[str, int] = {}
    lines = list(photos.run(album.parent, counts=counts))
    for line in lines:
        _rfc_rules(line)
    assert len(lines) == files  # every media file is a line: distinct stems, so no live pairs
    assert counts.get("skipped_sidecar_without_file", 0) == orphans
    assert len({line["payload"]["raw_id"] for line in lines}) <= len(lines)
    lb = Logbook.init(tmp_path_factory.mktemp("lb"), "UTC")
    assert lb.append_many(lines) == len({line["payload"]["raw_id"] for line in lines})
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)


# -- CLI -------------------------------------------------------------------------


def _cli(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "LOGBOOK_TAKEOUT_HASH_MEDIA"}
    env.update({"LOGBOOK_HOME": str(tmp_path / "lb"), "PYTHONPATH": str(ROOT)})

    def run(*a, check=True):
        return subprocess.run(
            [sys.executable, "-m", "logbook.cli", *a],
            env=env,
            capture_output=True,
            encoding="utf-8",
            check=check,
        )

    return run


def test_cli_add_google_photos_folder_reports_lines_and_counts(tmp_path, google_photos):
    run = _cli(tmp_path)
    run("init", str(tmp_path / "lb"), "--timezone", "Europe/Oslo")
    out = run("add", str(google_photos)).stdout
    assert "added 8 lines from google-takeout-photos" in out
    assert "skipped 1 sidecars without a media file" in out
    assert (
        "also 9 with media hashed, 1 live-photo pairs, 1 without a sidecar, 1 timed by creation time" in out
    )
    assert "no adapter" not in out
    assert "valid — 8 lines" in run("verify").stdout
    assert "added 0 lines from google-takeout-photos" in run("add", str(google_photos)).stdout


def test_cli_add_takeout_root_imports_google_photos(tmp_path, takeout):
    run = _cli(tmp_path)
    run("init", str(tmp_path / "lb"), "--timezone", "Europe/Oslo")
    out = run("add", str(takeout)).stdout
    assert "added 8 lines from google-takeout-photos" in out
    assert "valid — 8 lines" in run("verify").stdout


def test_cli_add_folder_of_location_files_still_walks_its_files(tmp_path):
    run = _cli(tmp_path)
    run("init", str(tmp_path / "lb"), "--timezone", "Europe/Oslo")
    folder = tmp_path / "Location History (Timeline)"
    folder.mkdir()
    (folder / "Records.json").write_bytes(RECORDS.read_bytes())
    assert "added 6 lines from google-takeout-location" in run("add", str(folder)).stdout
