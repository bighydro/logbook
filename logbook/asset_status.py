"""`logbook assets status`: where each registered asset (ADR 0018) last was, read from the record.

A reader (ADR 0013). For every asset of `assets.json` the last known position is its standing
location/v1 line (RFC 0001) with the latest `at` whose `subject` is the asset's id, found through
the index (`Index.last_fix`): the time, the coordinates, the nearest named place of `places.json`
when one is within NEAR_M, the speed when the line carries one, and how old the fix is. An asset
with no such line has no fix yet. Nothing is written."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, NamedTuple

from .assets import Asset
from .places import Place, nearest

if TYPE_CHECKING:
    from .store import Logbook

NEAR_M = 5000.0  # a named place this close is where the asset is


class Fix(NamedTuple):
    """One asset's last known position."""

    at: str  # RFC3339 UTC, the line's own
    lat: float
    lon: float
    speed_mps: float | None
    near: tuple[str, float] | None  # the nearest named place within NEAR_M and the metres to it
    age_s: int  # seconds from the fix to `now`, never negative
    line_id: str

    def to_json(self) -> dict[str, Any]:
        return {
            "at": self.at,
            "lat": self.lat,
            "lon": self.lon,
            "speed_mps": self.speed_mps,
            "near": None if self.near is None else {"name": self.near[0], "m": round(self.near[1])},
            "age_s": self.age_s,
            "line": self.line_id,
        }


class Status(NamedTuple):
    asset: Asset
    fix: Fix | None  # None: no fix yet

    def to_json(self) -> dict[str, Any]:
        return {**self.asset.to_json(), "fix": None if self.fix is None else self.fix.to_json()}


def read(lb: Logbook, registry: Iterable[Asset], places: Sequence[Place], now: datetime) -> list[Status]:
    """One Status per asset, in registry order. One index lookup per asset; one line read each."""
    now = now.astimezone(UTC)
    out: list[Status] = []
    with lb.index() as idx:
        for asset in registry:
            line = idx.last_fix(asset.id)
            out.append(Status(asset, None if line is None else _fix(line, places, now)))
    return out


def _fix(line: dict[str, Any], places: Sequence[Place], now: datetime) -> Fix:
    payload = line.get("payload") or {}
    lat, lon = float(payload["lat"]), float(payload["lon"])
    speed = payload.get("speed_mps")
    at = str(line["at"])  # RFC3339 UTC with a literal Z (SPEC §2)
    instant = datetime.fromisoformat(at.replace("Z", "+00:00"))
    found = nearest(lat, lon, places)
    near = (found[0].name, found[1]) if found is not None and found[1] <= NEAR_M else None
    return Fix(
        at=at,
        lat=lat,
        lon=lon,
        speed_mps=float(speed) if isinstance(speed, int | float) and not isinstance(speed, bool) else None,
        near=near,
        age_s=max(0, int((now - instant).total_seconds())),
        line_id=str(line["id"]),
    )


def age_text(seconds: int) -> str:
    """How long ago, as people say it: `just now` under a minute, then minutes, hours and minutes,
    days and hours."""
    if seconds < 60:
        return "just now"
    minutes, hours, days = (seconds // 60) % 60, (seconds // 3600) % 24, seconds // 86400
    if days:
        parts = [f"{days} day" if days == 1 else f"{days} days"]
        if hours:
            parts.append(f"{hours} h")
    elif hours:
        parts = [f"{hours} h"]
        if minutes:
            parts.append(f"{minutes} min")
    else:
        parts = [f"{minutes} min"]
    return " ".join(parts) + " ago"
