"""A synthetic Apple Photos library for the tests: the reverse-location archive Photos keeps for a
picture (`ZREVERSELOCATIONDATA`) and a small `Photos.sqlite` holding nothing but the columns a
reader of places needs. Every name, address and coordinate is invented."""

from __future__ import annotations

import plistlib
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path
from typing import Any

APPLE_EPOCH = 978_307_200  # 2001-01-01T00:00:00Z as a Unix time


def reverse_location(address: str, city: str, names: list[str]) -> bytes:
    """A `PLRevGeoLocationInfo` as Photos archives it in ZREVERSELOCATIONDATA (NSKeyedArchiver):
    `addressString`, a `postalAddress` (`CNPostalAddress`, `_city`) and a `mapItem` whose
    `sortedPlaceInfos` carry the names of the areas the point lies in. Invented, every word."""
    uid = plistlib.UID
    objects: list[Any] = ["$null"]

    def put(value: Any) -> plistlib.UID:
        objects.append(value)
        return uid(len(objects) - 1)

    def cls(name: str) -> plistlib.UID:
        return put({"$classname": name, "$classes": [name, "NSObject"]})

    infos = [
        put({"$class": cls("PLRevGeoMapItemAdditionalPlaceInfo"), "name": put(n), "placeType": 4})
        for n in names
    ]
    array = put({"$class": cls("NSArray"), "NS.objects": infos})
    map_item = put({"$class": cls("PLRevGeoMapItem"), "sortedPlaceInfos": array})
    postal = put(
        {"$class": cls("CNPostalAddress"), "_city": put(city), "_street": put(address.split(",")[0])}
    )
    root = put(
        {
            "$class": cls("PLRevGeoLocationInfo"),
            "addressString": put(address),
            "postalAddress": postal,
            "mapItem": map_item,
            "isHome": False,
        }
    )
    archive = {
        "$archiver": "NSKeyedArchiver",
        "$version": 100000,
        "$top": {"root": root},
        "$objects": objects,
    }
    return plistlib.dumps(archive, fmt=plistlib.FMT_BINARY)


def library(folder: Path, assets: Iterable[tuple[str, bytes | None, int | None]]) -> Path:
    """`<folder>/Photos Library.photoslibrary/database/Photos.sqlite` holding one asset per
    `(uuid, reverse-location blob or None, the row's valid flag)`; the library folder is returned."""
    root = folder / "Photos Library.photoslibrary"
    (root / "database").mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(root / "database" / "Photos.sqlite")) as con:
        con.executescript(
            "CREATE TABLE ZASSET (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, ZUUID VARCHAR,"
            " ZDATECREATED TIMESTAMP, ZTRASHEDSTATE INTEGER);"
            "CREATE TABLE ZADDITIONALASSETATTRIBUTES (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER,"
            " ZASSET INTEGER, ZREVERSELOCATIONDATA BLOB, ZREVERSELOCATIONDATAISVALID INTEGER);"
        )
        for pk, (uuid, blob, valid) in enumerate(assets, start=1):
            con.execute("INSERT INTO ZASSET VALUES (?, 3, ?, 800000000, 0)", (pk, uuid))
            con.execute(
                "INSERT INTO ZADDITIONALASSETATTRIBUTES VALUES (?, 5, ?, ?, ?)", (pk, pk, blob, valid)
            )
        con.commit()
    return root
