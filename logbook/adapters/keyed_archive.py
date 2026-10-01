"""NSKeyedArchiver plists → plain Python, for the blobs Core Data stores keep inside their rows.

An archive is a plist with `$archiver`, `$top` (`root`: a UID) and `$objects`, a flat list every
UID points into. `decode` follows the UIDs once each and returns:

    an NSDictionary / NSMutableDictionary   → dict (keys decoded the same way)
    an NSArray / NSSet / their mutable kin   → list
    an NSString / NSMutableString            → str; an inline string stays a str; "$null" → None
    an NSData / NSMutableData                → bytes
    any other class                          → dict of its fields, plus "$class": the class name
    numbers, booleans, bytes, dates          → themselves

A cycle (an object that points back at itself) comes out as a cycle, not a recursion error. A UID
that points outside `$objects`, a class whose row is missing, a blob that is not a plist or not an
archive: None, never an exception. Nothing here knows what the classes mean; the adapter that reads
a store does.
"""

from __future__ import annotations

import plistlib
from typing import Any

DICTIONARY_CLASSES = frozenset({"NSDictionary", "NSMutableDictionary"})
ARRAY_CLASSES = frozenset(
    {"NSArray", "NSMutableArray", "NSSet", "NSMutableSet", "NSOrderedSet", "NSMutableOrderedSet"}
)
STRING_CLASSES = frozenset({"NSString", "NSMutableString"})
DATA_CLASSES = frozenset({"NSData", "NSMutableData"})


def decode(blob: object) -> Any:
    """The archive's root object as plain Python; None when `blob` is not an archive."""
    if isinstance(blob, memoryview):
        blob = bytes(blob)
    if not isinstance(blob, bytes) or not blob:
        return None
    try:
        data = plistlib.loads(blob)
    except (plistlib.InvalidFileException, ValueError, TypeError, OverflowError):
        return None
    if not isinstance(data, dict):
        return None
    objects = data.get("$objects")
    top = data.get("$top")
    if not isinstance(objects, list) or not isinstance(top, dict):
        return None
    return _Decoder(objects).follow(top.get("root"))


class _Decoder:
    def __init__(self, objects: list[Any]) -> None:
        self.objects = objects
        self.seen: dict[int, Any] = {}

    def follow(self, value: Any) -> Any:
        """`value` with UIDs resolved: an object is decoded once, so a cycle stays a cycle."""
        if not isinstance(value, plistlib.UID):
            return value
        index = value.data
        if index in self.seen:
            return self.seen[index]
        if not 0 <= index < len(self.objects):
            return None
        raw = self.objects[index]
        if raw == "$null":
            return None
        if not isinstance(raw, dict):
            return raw
        return self._object(index, raw)

    def _class_name(self, raw: dict[str, Any]) -> str | None:
        cls = raw.get("$class")
        if isinstance(cls, plistlib.UID) and 0 <= cls.data < len(self.objects):
            row = self.objects[cls.data]
            if isinstance(row, dict):
                name = row.get("$classname")
                return name if isinstance(name, str) else None
        return None

    def _object(self, index: int, raw: dict[str, Any]) -> Any:
        name = self._class_name(raw)
        if name in DICTIONARY_CLASSES:
            out: dict[Any, Any] = {}
            self.seen[index] = out
            keys = raw.get("NS.keys")
            values = raw.get("NS.objects")
            if isinstance(keys, list) and isinstance(values, list):
                for key, value in zip(keys, values, strict=False):
                    out[self.follow(key)] = self.follow(value)
            return out
        if name in ARRAY_CLASSES:
            items: list[Any] = []
            self.seen[index] = items
            values = raw.get("NS.objects")
            if isinstance(values, list):
                items.extend(self.follow(v) for v in values)
            return items
        if name in STRING_CLASSES:
            text = raw.get("NS.string")
            self.seen[index] = text
            return text
        if name in DATA_CLASSES:
            data = raw.get("NS.data")
            self.seen[index] = data
            return data
        fields: dict[str, Any] = {"$class": name}
        self.seen[index] = fields
        for key, value in raw.items():
            if key != "$class":
                fields[key] = self.follow(value)
        return fields
