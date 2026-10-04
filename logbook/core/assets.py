"""The asset registry (ADR 0018): `<root>/assets.json` names the boats, aircraft and cars whose
positions the record tracks as their own subjects. A setting of the record, not part of the chain:
edited by `logbook assets add` or by hand, read by `logbook sync ais|adsb` to know which MMSIs and
icao24 addresses to ask for, and by readers that want to name a `subject`. Nothing here touches the
log.

    {"assets": [{"id": "solvind", "kind": "yacht", "name": "Solvind", "mmsi": "999000001"}]}

`id` is the token a location/v1 line carries as `subject` (RFC 0001): lower-case letters, digits and
hyphens. `kind` is `yacht`, `aircraft` or `car`. `mmsi` (nine digits), `icao24` (six hex digits,
stored lower-case) and `registration` (free text: a call sign, a plate) are optional; an asset may
carry any of them, and an identifier belongs to one asset at most. Keys of the file this module
does not know are preserved, as `logbook.json`'s are (SPEC §1)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ASSETS_FILE = "assets.json"
KINDS = ("yacht", "aircraft", "car")
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MMSI_PATTERN = re.compile(r"^[0-9]{9}$")
ICAO24_PATTERN = re.compile(r"^[0-9a-f]{6}$")
IDENTIFIERS = ("mmsi", "icao24", "registration")


class AssetError(ValueError):
    """An entry that is not an asset, a registry that is not one, or an asset already registered."""


@dataclass(frozen=True)
class Asset:
    id: str
    kind: str
    name: str
    mmsi: str | None = None
    icao24: str | None = None
    registration: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.icao24, str):  # the address is hex; the file and the line spell it lower-case
            object.__setattr__(self, "icao24", self.icao24.lower())

    def check(self) -> Asset:
        """Raise AssetError naming the field that is wrong; return self when every field is right."""
        if not isinstance(self.id, str) or not ID_PATTERN.match(self.id):
            raise AssetError(f"id must be lower-case letters, digits and hyphens, not {self.id!r}")
        if self.kind not in KINDS:
            raise AssetError(f"kind must be one of {', '.join(KINDS)}, not {self.kind!r}")
        if not isinstance(self.name, str) or not self.name.strip():
            raise AssetError("name is required")
        if self.mmsi is not None and (not isinstance(self.mmsi, str) or not MMSI_PATTERN.match(self.mmsi)):
            raise AssetError(f"mmsi must be nine digits, not {self.mmsi!r}")
        if self.icao24 is not None and (
            not isinstance(self.icao24, str) or not ICAO24_PATTERN.match(self.icao24)
        ):
            raise AssetError(f"icao24 must be six hex digits, not {self.icao24!r}")
        if self.registration is not None and (
            not isinstance(self.registration, str) or not self.registration.strip()
        ):
            raise AssetError(f"registration must be text, not {self.registration!r}")
        return self

    def to_json(self) -> dict[str, Any]:
        """The entry as the file holds it: identifiers the asset lacks are left out, never null."""
        entry: dict[str, Any] = {"id": self.id, "kind": self.kind, "name": self.name}
        for key in IDENTIFIERS:
            value = getattr(self, key)
            if value is not None:
                entry[key] = value
        return entry

    @classmethod
    def from_json(cls, entry: object) -> Asset:
        """An asset from one entry of the file, checked; an icao24 is lower-cased."""
        if not isinstance(entry, dict):
            raise AssetError(f"an asset is an object with id, kind and name, not {type(entry).__name__}")
        for key in ("id", "kind", "name"):
            if key not in entry:
                raise AssetError(f"an asset needs a {key}")
        return cls(
            id=entry["id"],
            kind=entry["kind"],
            name=entry["name"],
            mmsi=entry.get("mmsi"),
            icao24=entry.get("icao24"),
            registration=entry.get("registration"),
        ).check()


def assets_path(root: Path) -> Path:
    return Path(root) / ASSETS_FILE


def read(root: Path) -> list[Asset]:
    """Every registered asset in file order; none when there is no file. AssetError, naming the
    file, when it is not a registry."""
    return [Asset.from_json(entry) for entry in _document(root)["assets"]]


def _document(root: Path) -> dict[str, Any]:
    path = assets_path(root)
    if not path.exists():
        return {"assets": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise AssetError(f"{path} is not JSON: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("assets"), list):
        raise AssetError(f'{path} must be an object with an "assets" list')
    return data


def write(root: Path, assets: Iterable[Asset]) -> Path:
    """Write the registry, keeping every other key the file already has. Returns the path."""
    document = _document(root)
    document["assets"] = [asset.check().to_json() for asset in assets]
    path = assets_path(root)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def add(root: Path, asset: Asset) -> list[Asset]:
    """Register one asset; refuses an id, mmsi or icao24 another asset already carries. Returns the
    registry after the addition."""
    asset = asset.check()
    registry = read(root)
    for other in registry:
        if other.id == asset.id:
            raise AssetError(f"an asset with id {asset.id!r} is already registered ({other.name})")
        for key in ("mmsi", "icao24"):
            value = getattr(asset, key)
            if value is not None and value == getattr(other, key):
                raise AssetError(f"{key} {value} is already registered to {other.id!r}")
    registry.append(asset)
    write(root, registry)
    return registry


def by_mmsi(assets: Iterable[Asset]) -> dict[str, Asset]:
    return {a.mmsi: a for a in assets if a.mmsi is not None}


def by_icao24(assets: Iterable[Asset]) -> dict[str, Asset]:
    return {a.icao24: a for a in assets if a.icao24 is not None}
