"""Photos.sqlite → photo/v1 (RFC 0002): one line per asset with the owner's albums, favourites and
the ids of the people they named, keyed by original file name and capture time so a reader can fold
it with the Immich line for the same asset."""

from __future__ import annotations

import sqlite3
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters, cli
from logbook.adapters import apple_photos
from logbook.store import Logbook

TZ = "Europe/Oslo"
APPLE_EPOCH = 978_307_200

# Photos' own layout, as far as the adapter reads it. Entity numbers come from Z_PRIMARYKEY, and the
# album ↔ asset join table is named after them (`Z_33ASSETS` for Album = 33, Asset = 3 on iOS 18).
DDL = """
CREATE TABLE Z_PRIMARYKEY (Z_ENT INTEGER PRIMARY KEY, Z_NAME VARCHAR, Z_SUPER INTEGER, Z_MAX INTEGER);
CREATE TABLE ZASSET (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZFAVORITE INTEGER, ZHIDDEN INTEGER,
    ZKIND INTEGER, ZKINDSUBTYPE INTEGER, ZSAVEDASSETTYPE INTEGER, ZTRASHEDSTATE INTEGER,
    ZWIDTH INTEGER, ZHEIGHT INTEGER, ZADDITIONALATTRIBUTES INTEGER, ZDATECREATED TIMESTAMP,
    ZDURATION FLOAT, ZLATITUDE FLOAT, ZLONGITUDE FLOAT, ZMODIFICATIONDATE TIMESTAMP,
    ZFILENAME VARCHAR, ZUNIFORMTYPEIDENTIFIER VARCHAR, ZUUID VARCHAR);
CREATE TABLE ZADDITIONALASSETATTRIBUTES (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZIMPORTEDBY INTEGER, ZASSET INTEGER,
    ZTIMEZONEOFFSET INTEGER, ZEXIFTIMESTAMPSTRING VARCHAR, ZIMPORTEDBYBUNDLEIDENTIFIER VARCHAR,
    ZORIGINALFILENAME VARCHAR, ZTIMEZONENAME VARCHAR, ZTITLE VARCHAR);
CREATE TABLE ZGENERICALBUM (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZKIND INTEGER, ZTRASHEDSTATE INTEGER,
    ZPARENTFOLDER INTEGER, ZCREATIONDATE TIMESTAMP, ZTITLE VARCHAR, ZUUID VARCHAR);
CREATE TABLE Z_33ASSETS (Z_33ALBUMS INTEGER, Z_3ASSETS INTEGER, Z_FOK_3ASSETS INTEGER,
    PRIMARY KEY (Z_33ALBUMS, Z_3ASSETS));
CREATE TABLE ZPERSON (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZFACECOUNT INTEGER, ZTYPE INTEGER,
    ZVERIFIEDTYPE INTEGER, ZMERGETARGETPERSON INTEGER, ZDISPLAYNAME VARCHAR, ZFULLNAME VARCHAR,
    ZPERSONUUID VARCHAR);
CREATE TABLE ZDETECTEDFACE (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZHIDDEN INTEGER, ZMANUAL INTEGER,
    ZASSETFORFACE INTEGER, ZPERSONFORFACE INTEGER, ZQUALITY FLOAT, ZUUID VARCHAR);
"""
ENTITIES = [
    (3, "Asset", None, 10),
    (32, "GenericAlbum", None, 10),
    (33, "Album", 32, 10),
    (59, "Person", None, 10),
]
IMAGE, VIDEO = 0, 1
LIVE, PANORAMA, SCREENSHOT, SLOMO = 2, 1, 10, 101
BACK_CAMERA, FRONT_CAMERA, THIRD_PARTY, AIRDROP = 1, 2, 3, 8
NO_LOCATION = -180.0


def _apple(stamp: str) -> float:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp() - APPLE_EPOCH


# one dict per asset: a live photo from the camera, a screenshot, a WhatsApp image, a slo-mo video, a
# hidden AirDropped image, a trashed one, an undated one, a panorama with no original name
U = "A0000000-0000-4000-8000-00000000000"
ASSETS: list[dict[str, Any]] = [
    dict(pk=1, uuid=U + "1", date="2026-03-01T09:12:00Z", kind=IMAGE, subtype=LIVE, favorite=1, hidden=0,
         trashed=0, w=4032, h=3024, duration=None, lat=59.913, lon=10.742, filename="IMG_0001.HEIC",
         uti="public.heic", original="IMG_0001.HEIC", tz="Europe/Oslo", imported_by=BACK_CAMERA,
         bundle="com.apple.camera"),
    dict(pk=2, uuid=U + "2", date="2026-03-01T10:00:00Z", kind=IMAGE, subtype=SCREENSHOT, favorite=0,
         hidden=0,
         trashed=0, w=1170, h=2532, duration=None, lat=NO_LOCATION, lon=NO_LOCATION, filename="IMG_0002.PNG",
         uti="public.png", original="IMG_0002.PNG", tz="GMT+0100", imported_by=None, bundle=None),
    dict(pk=3, uuid=U + "3", date="2026-03-02T18:30:00Z", kind=IMAGE, subtype=0, favorite=0, hidden=0,
         trashed=0, w=1280, h=960, duration=None, lat=NO_LOCATION, lon=NO_LOCATION, filename="IMG_0003.JPG",
         uti="public.jpeg", original="IMG-20260302-WA0012.jpg", tz="Europe/Oslo", imported_by=THIRD_PARTY,
         bundle="net.whatsapp.WhatsApp"),
    dict(pk=4, uuid=U + "4", date="2026-03-03T12:00:00Z", kind=VIDEO, subtype=SLOMO, favorite=0, hidden=0,
         trashed=0, w=1920, h=1080, duration=12.5, lat=59.95, lon=10.75, filename="IMG_0004.MOV",
         uti="com.apple.quicktime-movie", original="IMG_0004.MOV", tz="Europe/Oslo", imported_by=BACK_CAMERA,
         bundle=None),
    dict(pk=5, uuid=U + "5", date="2026-03-04T12:00:00Z", kind=IMAGE, subtype=0, favorite=0, hidden=1,
         trashed=0, w=3000, h=2000, duration=None, lat=NO_LOCATION, lon=NO_LOCATION, filename="IMG_0005.JPG",
         uti="public.jpeg", original="DSC_0005.JPG", tz=None, imported_by=AIRDROP,
         bundle="com.apple.sharingd"),
    dict(pk=6, uuid=U + "6", date="2026-03-05T12:00:00Z", kind=IMAGE, subtype=0, favorite=0, hidden=0,
         trashed=1, w=100, h=100, duration=None, lat=NO_LOCATION, lon=NO_LOCATION, filename="IMG_0006.JPG",
         uti="public.jpeg", original="IMG_0006.JPG", tz=None, imported_by=BACK_CAMERA, bundle=None),
    dict(pk=7, uuid=U + "7", date=None, kind=IMAGE, subtype=0, favorite=0, hidden=0,
         trashed=0, w=100, h=100, duration=None, lat=NO_LOCATION, lon=NO_LOCATION, filename="IMG_0007.JPG",
         uti="public.jpeg", original="IMG_0007.JPG", tz=None, imported_by=None, bundle=None),
    dict(pk=8, uuid=U + "8", date="2026-03-06T12:00:00Z", kind=IMAGE, subtype=PANORAMA, favorite=0, hidden=0,
         trashed=0, w=9000, h=2000, duration=None, lat=NO_LOCATION, lon=NO_LOCATION, filename="IMG_0008.JPG",
         uti="public.jpeg", original=None, tz="", imported_by=FRONT_CAMERA, bundle=None),
]  # fmt: skip
ALBUMS = [  # (pk, kind, trashed, title, uuid): a user album, another, a trashed one, a smart album, a folder
    (10, 2, 0, "Oslo weekend", "B0000000-0000-4000-8000-000000000010"),
    (11, 2, 0, "Boats", "B0000000-0000-4000-8000-000000000011"),
    (12, 2, 1, "Old album", "B0000000-0000-4000-8000-000000000012"),
    (13, 1510, 0, "Recents", "B0000000-0000-4000-8000-000000000013"),
    (14, 4000, 0, None, "B0000000-0000-4000-8000-000000000014"),
]
MEMBERS = [(10, 1), (11, 1), (12, 1), (13, 1), (10, 4), (13, 2), (14, 2)]  # (album pk, asset pk)
PEOPLE = [  # (pk, face count, merge target, display name, full name, uuid): named, unnamed, merged into named
    (20, 12, None, "K", "Kari Nordmann", "C0000000-0000-4000-8000-000000000020"),
    (21, 3, None, None, None, "C0000000-0000-4000-8000-000000000021"),
    (22, 1, 20, None, None, "C0000000-0000-4000-8000-000000000022"),
    (23, 2, None, "O", None, "C0000000-0000-4000-8000-000000000023"),
]
FACES = [  # (pk, asset pk, person pk)
    (30, 1, 20), (31, 1, 21), (32, 4, 22), (33, 4, 23), (34, 4, None), (35, 6, 20),
]  # fmt: skip
LINES = 6  # eight assets less the trashed one and the undated one


def _store(folder: Path, *, name: str = "Photos.sqlite") -> Path:
    """A synthetic Photos.sqlite. Nobody in it exists; the person is the Oslo persona."""
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    with closing(sqlite3.connect(p)) as con:
        con.executescript(DDL)
        con.executemany("INSERT INTO Z_PRIMARYKEY VALUES (?,?,?,?)", ENTITIES)
        for a in ASSETS:
            con.execute(
                "INSERT INTO ZASSET VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (a["pk"], 3, 1, a["favorite"], a["hidden"], a["kind"], a["subtype"], 3, a["trashed"], a["w"],
                 a["h"], a["pk"], _apple(a["date"]) if a["date"] else None, a["duration"], a["lat"], a["lon"],
                 None, a["filename"], a["uti"], a["uuid"]),
            )  # fmt: skip
            con.execute(
                "INSERT INTO ZADDITIONALASSETATTRIBUTES VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    a["pk"],
                    5,
                    1,
                    a["imported_by"],
                    a["pk"],
                    None,
                    None,
                    a["bundle"],
                    a["original"],
                    a["tz"],
                    None,
                ),
            )
        for pk, kind, trashed, title, uuid in ALBUMS:
            con.execute(
                "INSERT INTO ZGENERICALBUM VALUES (?,?,?,?,?,?,?,?,?)",
                (pk, 33, 1, kind, trashed, None, 0, title, uuid),
            )
        con.executemany("INSERT INTO Z_33ASSETS VALUES (?,?,0)", MEMBERS)
        for pk, faces, target, display, full, uuid in PEOPLE:
            con.execute(
                "INSERT INTO ZPERSON VALUES (?,?,?,?,?,?,?,?,?,?)",
                (pk, 59, 1, faces, 0, 1, target, display, full, uuid),
            )
        for pk, asset, person in FACES:
            con.execute(
                "INSERT INTO ZDETECTEDFACE VALUES (?,?,?,?,?,?,?,?,?)",
                (pk, 23, 1, 0, 0, asset, person, 0.9, f"F{pk}"),
            )
        con.commit()
    return p


def _lines(tmp_path: Path, **kw: Any) -> list[dict[str, Any]]:
    return list(apple_photos.run(_store(tmp_path / "photos"), **kw))


def _by_name(lines: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {line["payload"]["file_name"]: line for line in lines}


# -- registry and sniff ----------------------------------------------------------------------------


def test_registry_lists_apple_photos_and_photos_is_an_alias():
    assert apple_photos in adapters.file_adapters()
    assert adapters.named("apple-photos") is apple_photos
    assert adapters.named("photos") is apple_photos


def test_sniff_takes_a_photos_store_and_nothing_else(tmp_path):
    assert apple_photos.sniff(_store(tmp_path / "photos"))
    other = tmp_path / "other.sqlite"
    with closing(sqlite3.connect(other)) as con:
        con.execute("CREATE TABLE ZASSET (x)")
    assert not apple_photos.sniff(other)  # ZASSET alone is not Photos
    assert not apple_photos.sniff(tmp_path / "missing.sqlite")


# -- the lines -------------------------------------------------------------------------------------


def test_every_asset_is_a_photo_line_in_capture_order(tmp_path):
    lines = _lines(tmp_path, timezone=TZ)
    assert len(lines) == LINES
    for line in lines:
        assert set(line) == {"at", "end", "tz", "source", "kind", "tier", "payload"}
        assert (line["source"], line["kind"], line["tier"], line["end"]) == ("apple-photos", "photo", 1, None)
        p = line["payload"]
        assert p["schema"] == "photo/v1" and p["library"] == "apple-photos"
        assert p["raw_id"] == p["asset_id"] and len(p["asset_id"]) == 36
    assert [line["at"] for line in lines] == sorted(line["at"] for line in lines)


def test_a_live_photo_from_the_camera_with_its_albums_favourite_and_named_people(tmp_path):
    line = _by_name(_lines(tmp_path, timezone=TZ))["IMG_0001.HEIC"]
    assert (line["at"], line["tz"]) == ("2026-03-01T09:12:00Z", "Europe/Oslo")
    assert line["payload"] == {
        "schema": "photo/v1",
        "raw_id": "A0000000-0000-4000-8000-000000000001",
        "asset_id": "A0000000-0000-4000-8000-000000000001",
        "library": "apple-photos",
        "file_name": "IMG_0001.HEIC",
        "media": "image",
        "lat": 59.913,
        "lon": 10.742,
        "width": 4032,
        "height": 3024,
        "live_photo": True,
        "provenance": "camera",
        "faces": 2,
        "people": ["C0000000-0000-4000-8000-000000000020"],
        "favorite": True,
        "albums": ["Boats", "Oslo weekend"],
        "extra": {"uti": "public.heic", "imported_by": 1, "imported_by_bundle": "com.apple.camera"},
    }


def test_a_screenshot_has_no_location_and_a_non_iana_zone_falls_back_to_the_record(tmp_path):
    line = _by_name(_lines(tmp_path, timezone=TZ))["IMG_0002.PNG"]
    p = line["payload"]
    assert line["tz"] == TZ and "lat" not in p and "lon" not in p
    assert p["provenance"] == "screenshot" and p["faces"] == 0 and "people" not in p
    assert "favorite" not in p and "albums" not in p and "live_photo" not in p  # smart albums are not albums


def test_a_messenger_image_is_received_and_keeps_the_original_name(tmp_path):
    p = _by_name(_lines(tmp_path))["IMG-20260302-WA0012.jpg"]["payload"]
    assert p["provenance"] == "received" and p["extra"]["imported_by_bundle"] == "net.whatsapp.WhatsApp"


def test_a_video_has_its_duration_and_a_merged_person_counts_under_its_target(tmp_path):
    p = _by_name(_lines(tmp_path))["IMG_0004.MOV"]["payload"]
    assert p["media"] == "video" and p["duration_s"] == 12.5 and p["provenance"] == "camera"
    assert p["faces"] == 3  # one unnamed face is still a face
    assert p["people"] == ["C0000000-0000-4000-8000-000000000020", "C0000000-0000-4000-8000-000000000023"]
    assert p["albums"] == ["Oslo weekend"]


def test_hidden_airdropped_and_front_camera_assets(tmp_path):
    by = _by_name(_lines(tmp_path))
    hidden = by["DSC_0005.JPG"]["payload"]
    assert hidden["hidden"] is True and hidden["provenance"] == "received"
    panorama = by["IMG_0008.JPG"]["payload"]  # no original name: the library's file name stands in
    assert panorama["provenance"] == "camera" and "tz" not in panorama


def test_trashed_and_undated_assets_are_skipped_and_counted(tmp_path):
    counts: dict[str, int] = {}
    lines = _lines(tmp_path, counts=counts)
    assert len(lines) == LINES
    assert counts == {"skipped_trashed": 1, "skipped_no_timestamp": 1}
    assert "IMG_0006.JPG" not in _by_name(lines)


def test_since_and_tier(tmp_path):
    lines = _lines(tmp_path, since="2026-03-03T00:00:00Z", tier=2)
    assert [line["payload"]["file_name"] for line in lines] == [
        "IMG_0004.MOV",
        "DSC_0005.JPG",
        "IMG_0008.JPG",
    ]
    assert {line["tier"] for line in lines} == {2}


def test_the_store_is_never_written(tmp_path):
    store = _store(tmp_path / "photos")
    before = store.read_bytes()
    list(apple_photos.run(store))
    assert store.read_bytes() == before and [p.name for p in store.parent.iterdir()] == ["Photos.sqlite"]


def test_the_merge_key_matches_an_immich_line_for_the_same_asset(tmp_path):
    """RFC 0002: same original file name (ignoring case), capture times within a second."""
    ours = _by_name(_lines(tmp_path))["IMG_0001.HEIC"]
    theirs = {"at": "2026-03-01T09:12:00Z", "payload": {"file_name": "img_0001.heic", "library": "immich"}}
    assert ours["payload"]["file_name"].lower() == theirs["payload"]["file_name"].lower()
    assert ours["at"] == theirs["at"]


# -- through the CLI --------------------------------------------------------------------------------


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook.init(root, TZ)


def test_add_photos_appends_once(lb, tmp_path, capsys):
    store = _store(tmp_path / "photos")
    cli.main(["add", "photos", str(store)])
    out = capsys.readouterr().out
    assert f"added {LINES} lines from apple-photos" in out and "skipped 1 without a timestamp" in out
    assert "1 in the trash" in out
    cli.main(["add", "photos", str(store)])
    assert "added 0 lines" in capsys.readouterr().out
    seq, _head, errors = lb.verify()
    assert (seq, errors) == (LINES, [])
