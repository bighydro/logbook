"""NSKeyedArchiver plists → plain Python: what Beeper's store (and other Core Data blobs) hold."""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook.adapters import keyed_archive


def archive(root: object) -> bytes:
    """A binary plist in NSKeyedArchiver's layout: `$objects` holds every object once, UIDs point
    into it, dictionaries and arrays carry their class. Strings and numbers may be inline or
    indirect; both happen in real archives."""
    objects: list[object] = ["$null"]
    classes: dict[str, plistlib.UID] = {}

    def cls(name: str, supers: list[str]) -> plistlib.UID:
        if name not in classes:
            objects.append({"$classname": name, "$classes": [name, *supers]})
            classes[name] = plistlib.UID(len(objects) - 1)
        return classes[name]

    def put(value: object) -> plistlib.UID:
        objects.append(None)
        index = len(objects) - 1
        objects[index] = encode(value)
        return plistlib.UID(index)

    def encode(value: object) -> object:
        if isinstance(value, dict) and value.get("$class") is None:
            return {
                "$class": cls("NSMutableDictionary", ["NSDictionary", "NSObject"]),
                "NS.keys": [put(k) for k in value],
                "NS.objects": [put(v) for v in value.values()],
            }
        if isinstance(value, dict):  # a custom class: fields are keys, `$class` names it
            out: dict[str, object] = {"$class": cls(str(value["$class"]), ["NSObject"])}
            for k, v in value.items():
                if k != "$class":
                    out[k] = put(v) if isinstance(v, dict | list | str) else v
            return out
        if isinstance(value, list):
            return {"$class": cls("NSArray", ["NSObject"]), "NS.objects": [put(v) for v in value]}
        return value

    top = put(root)
    return plistlib.dumps(
        {"$version": 100000, "$archiver": "NSKeyedArchiver", "$top": {"root": top}, "$objects": objects},
        fmt=plistlib.FMT_BINARY,
    )


def _raw(objects: list[object]) -> bytes:
    """An archive whose `$objects` are given as is, root at index 1."""
    return plistlib.dumps(
        {
            "$version": 100000,
            "$archiver": "NSKeyedArchiver",
            "$top": {"root": plistlib.UID(1)},
            "$objects": objects,
        },
        fmt=plistlib.FMT_BINARY,
    )


def test_decodes_dictionaries_arrays_strings_numbers_and_null():
    data = {"body": "hi", "n": 3, "f": 1.5, "flag": True, "none": None, "list": ["a", {"k": "v"}]}
    assert keyed_archive.decode(archive(data)) == data


def test_decodes_a_custom_class_with_its_name():
    event = {
        "$class": "BSEvent",
        "eventId": "$ev1",
        "originServerTs": 1700000000000,
        "content": {"msgtype": "m.text", "body": "hello"},
        "clearEvent": None,
    }
    out = keyed_archive.decode(archive(event))
    assert out == {
        "$class": "BSEvent",
        "eventId": "$ev1",
        "originServerTs": 1700000000000,
        "content": {"msgtype": "m.text", "body": "hello"},
        "clearEvent": None,
    }


def test_decodes_nsdata_nsdate_and_nested_classes():
    objects: list[object] = [
        "$null",
        {"$class": plistlib.UID(2), "NS.data": b"\x01\x02"},
        {"$classname": "NSMutableData", "$classes": ["NSMutableData", "NSData", "NSObject"]},
    ]
    blob = _raw(objects)
    assert keyed_archive.decode(blob) == b"\x01\x02"
    objects = [
        "$null",
        {"$class": plistlib.UID(2), "NS.time": 700000000.5},
        {"$classname": "NSDate", "$classes": ["NSDate", "NSObject"]},
    ]
    blob = _raw(objects)
    assert keyed_archive.decode(blob) == {"$class": "NSDate", "NS.time": 700000000.5}


def test_a_cycle_does_not_recurse_forever():
    objects: list[object] = [
        "$null",
        {"$class": plistlib.UID(2), "NS.keys": [plistlib.UID(3)], "NS.objects": [plistlib.UID(1)]},
        {"$classname": "NSDictionary", "$classes": ["NSDictionary", "NSObject"]},
        "self",
    ]
    blob = _raw(objects)
    out = keyed_archive.decode(blob)
    assert isinstance(out, dict) and out["self"] is out


@pytest.mark.parametrize(
    "blob", [b"", b"not a plist", plistlib.dumps({"no": "archive"}), plistlib.dumps([1, 2])]
)
def test_anything_else_is_none(blob):
    assert keyed_archive.decode(blob) is None


def test_memoryview_and_bad_uid_are_handled():
    objects: list[object] = ["$null", {"$class": plistlib.UID(99), "x": plistlib.UID(42)}]
    blob = _raw(objects)
    assert keyed_archive.decode(memoryview(blob)) == {"$class": None, "x": None}
