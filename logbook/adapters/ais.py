"""AIS → location/v1 (RFC 0001) with `subject`: the positions of the owner's own vessels (ADR 0018).

Two entrances, one mapping (ADR 0017). The file mode reads a saved aisstream.io stream: one JSON
message per line, as `websocat` or the site's own examples write it. The live mode, `logbook sync
ais`, opens the aisstream.io websocket (`wss://stream.aisstream.io/v0/stream`), subscribes to the
MMSI of every registered asset that has one, listens for a fixed window (`LOGBOOK_AISSTREAM_LISTEN_S`,
default 60 s; a vessel under way reports every few seconds, a moored one every few minutes) and
maps what it heard. Both call `draft(message, asset)`.

A message is `{"MessageType", "MetaData": {"MMSI", "ShipName", "latitude", "longitude", "time_utc"},
"Message": {<MessageType>: {...}}}`. Only `PositionReport` (class A) and `StandardClassBPositionReport`
(class B, what a yacht carries) are positions; the subscription asks for those two and the file mode
skips the rest. The fix time is `MetaData.time_utc` (`2026-03-01 07:30:00.123456789 +0000 UTC`),
truncated to the second; `raw_id` is `aisstream:<mmsi>:<unix seconds>`, so a report saved to a file
and the same report heard live are one line. AIS sentinels for "not available" (latitude 91,
longitude 181, speed 102.3 knots, course 360, heading 511) are left out, never written as numbers;
a report with no position is skipped and counted. Speed comes in knots and is written in m/s
(`speed_mps`), the knots kept under `extra.sog_knots`.

The stream has no history: `since` only filters what was heard, there is no `resume`, and each
asset keeps its own watermark (`GROUP_MARKS`) so `state/ais.json` says when each was last heard.
The key is sent once, inside the subscription message on an encrypted socket; it is never in a URL,
the config's repr, or a message. The websocket client is the `websockets` package, an optional
extra (`openlogbook[ais]`), imported only inside `pull`; network happens only there (ADR 0012).
"""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..assets import Asset, by_mmsi
from ..store import utc

__all__ = [
    "ENV",
    "KIND",
    "NAME",
    "Config",
    "configure",
    "draft",
    "group",
    "pull",
    "run",
    "sniff",
    "watermark",
]

NAME = "ais"
KIND = "location"
TIER = 1
SCHEMA = "location/v1"
TRACKER = "aisstream"
ENV = ("LOGBOOK_AISSTREAM_KEY",)
URL_ENV = "LOGBOOK_AISSTREAM_URL"
DEFAULT_URL = "wss://stream.aisstream.io/v0/stream"
LISTEN_ENV = "LOGBOOK_AISSTREAM_LISTEN_S"
LISTEN_S = 60.0
UNIT = "reports"
GROUP_MARKS = True  # `sync` keeps a watermark per group (per asset) in the state file
TIMEOUT_S = 30
POSITION_TYPES = ("PositionReport", "StandardClassBPositionReport")
KNOT_MPS = 0.514444
NOT_AVAILABLE_SOG = 102.3
NOT_AVAILABLE_COG = 360.0
NOT_AVAILABLE_HEADING = 511
TIME_UTC = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})(?:\.\d+)? \+0000 UTC$")

NOT_A_POSITION = "skipped_not_a_position"
UNKNOWN_SUBJECT = "skipped_unknown_subject"
BAD_COORDINATES = "skipped_bad_coordinates"
NO_TIMESTAMP = "skipped_no_timestamp"


@dataclass(frozen=True)
class Config:
    key: str = field(repr=False)
    url: str = DEFAULT_URL
    listen_s: float = LISTEN_S


def configure(env: Mapping[str, str]) -> Config | None:
    """Config from LOGBOOK_AISSTREAM_KEY (None when absent or empty), LOGBOOK_AISSTREAM_URL and
    LOGBOOK_AISSTREAM_LISTEN_S. Raises ValueError when the window is set but not a number of
    seconds above 0."""
    key = env.get(ENV[0], "").strip()
    if not key:
        return None
    url = env.get(URL_ENV, "").strip().rstrip("/") or DEFAULT_URL
    raw = env.get(LISTEN_ENV, "").strip()
    listen = LISTEN_S
    if raw:
        try:
            listen = float(raw)
        except ValueError:
            listen = -1.0
        if not math.isfinite(listen) or listen <= 0:
            raise ValueError(f"{LISTEN_ENV} must be a number of seconds above 0, not {raw!r}")
    return Config(key=key, url=url, listen_s=listen)


# -- the file mode ---------------------------------------------------------------------------------


def sniff(path: Path) -> bool:
    """A file whose first non-blank line is one aisstream message: a JSON object with `MessageType`
    and `MetaData.MMSI`. Reads one line."""
    path = Path(path)
    if not path.is_file():
        return False
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                if raw.strip():
                    first = json.loads(raw)
                    break
            else:
                return False
    except (OSError, ValueError):
        return False
    return (
        isinstance(first, dict)
        and "MessageType" in first
        and isinstance(first.get("MetaData"), dict)
        and "MMSI" in first["MetaData"]
    )


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    assets: Iterable[Asset] | None = None,
) -> Iterator[dict[str, Any]]:
    """One location/v1 line draft per position report of a registered vessel, in file order. A line
    that is not JSON is skipped silently (a stream dump can end mid-message); a message that is not
    a position, of a vessel not in `assets`, or without a usable fix is skipped and counted."""
    counts = _counts(counts if counts is not None else {})
    vessels = by_mmsi(assets or ())
    cutoff = utc(since) if since else None
    with Path(path).open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            if not raw.strip():
                continue
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            line = _line(message, vessels, counts)
            if line is not None and (cutoff is None or str(line["at"]) >= cutoff):
                yield line


# -- the live mode ---------------------------------------------------------------------------------


def watermark(draft: dict[str, Any]) -> str | None:
    """The report's own time: the stream has no other clock."""
    return str(draft["at"])


def group(draft: dict[str, Any]) -> str:
    """The asset, so `sync` reports seen and new per vessel and keeps a watermark for each."""
    return str(draft["payload"]["subject"])


def pull(
    config: Config,
    since: str | None = None,
    progress: Callable[[int, float], None] | None = None,
    counts: dict[str, int] | None = None,
    assets: Iterable[Asset] | None = None,
) -> Iterator[dict[str, Any]]:
    """Listen to the stream for the configured window and yield one line draft per position report
    of a registered vessel, oldest first (a message can arrive out of order). Everything heard is
    mapped before the first line is yielded, so chain order is time order. `since` drops what is
    older. Skips are tallied in `counts`; `progress(messages_so_far, elapsed_seconds)` is called
    for every message heard. ValueError when no asset has an MMSI; OSError when the stream refuses
    the key, closes early, or the websocket package is not installed."""
    counts = _counts(counts if counts is not None else {})
    vessels = by_mmsi(assets or ())
    if not vessels:
        raise ValueError(
            "no registered asset has an mmsi; register the vessel first: "
            "logbook assets add <id> --kind yacht --name NAME --mmsi <nine digits>"
        )
    cutoff = utc(since) if since else None
    started, heard = time.monotonic(), 0
    lines: list[dict[str, Any]] = []
    for text in _stream(config, sorted(vessels)):
        heard += 1
        try:
            message = json.loads(text)
        except ValueError:
            continue
        if isinstance(message, dict) and "error" in message and "MessageType" not in message:
            raise OSError(f"aisstream refused the subscription: {message['error']}")
        line = _line(message, vessels, counts)
        if line is not None and (cutoff is None or str(line["at"]) >= cutoff):
            lines.append(line)
        if progress is not None:
            progress(heard, time.monotonic() - started)
    lines.sort(key=lambda line: str(line["at"]))  # stable: equal seconds keep the order heard
    yield from lines


def _stream(config: Config, mmsis: list[str]) -> Iterator[str | bytes]:
    """Every message the socket delivers within the window. The only network code in this module."""
    subscription = {
        "APIKey": config.key,
        "BoundingBoxes": [[[-90, -180], [90, 180]]],
        "FiltersShipMMSI": mmsis,
        "FilterMessageTypes": list(POSITION_TYPES),
    }
    deadline = time.monotonic() + config.listen_s
    try:
        socket = _connect(config.url, TIMEOUT_S)
    except ImportError:
        raise OSError(
            "sync ais needs the websockets package: pip install 'openlogbook[ais]' (or uv sync --extra ais)"
        ) from None
    with socket as ws:
        ws.send(json.dumps(subscription))
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                yield ws.recv(timeout=remaining)
            except TimeoutError:
                break
            except Exception as e:  # websockets' ConnectionClosed is not an OSError
                if type(e).__name__.startswith("ConnectionClosed"):
                    raise OSError(f"aisstream closed the connection: {e}") from None
                raise


def _connect(url: str, timeout: float) -> Any:
    """A connected websocket (a context manager with send/recv). Imports `websockets` here, so the
    package is needed only by `logbook sync ais`."""
    from websockets.sync.client import connect

    return connect(url, open_timeout=timeout)


# -- the mapping -----------------------------------------------------------------------------------


def _counts(counts: dict[str, int]) -> dict[str, int]:
    for key in (NOT_A_POSITION, UNKNOWN_SUBJECT, BAD_COORDINATES, NO_TIMESTAMP):
        counts.setdefault(key, 0)
    return counts


def _line(message: Any, vessels: Mapping[str, Asset], counts: dict[str, int]) -> dict[str, Any] | None:
    """The line draft for one message, or None (counted) when it is not a position of a registered
    vessel with a usable fix and time."""
    if not isinstance(message, dict) or message.get("MessageType") not in POSITION_TYPES:
        counts[NOT_A_POSITION] += 1
        return None
    asset = vessels.get(_mmsi(message))
    if asset is None:
        counts[UNKNOWN_SUBJECT] += 1
        return None
    report = _report(message)
    lat, lon = _degrees(report.get("Latitude"), 90), _degrees(report.get("Longitude"), 180)
    if lat is None or lon is None:
        counts[BAD_COORDINATES] += 1
        return None
    if _fix_time(message) is None:
        counts[NO_TIMESTAMP] += 1
        return None
    return draft(message, asset)


def draft(message: Mapping[str, Any], asset: Asset) -> dict[str, Any]:
    """One aisstream position report → one location/v1 line draft with `subject` = the asset's id.
    The message must be a PositionReport or StandardClassBPositionReport with a usable position
    and `MetaData.time_utc` (see `_line`)."""
    fix = _fix_time(message)
    assert fix is not None
    report = _report(message)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "lat": report["Latitude"],
        "lon": report["Longitude"],
    }
    extra: dict[str, Any] = {"mmsi": _mmsi(message), "message_type": message["MessageType"]}
    sog = _number(report.get("Sog"))
    if sog is not None and sog != NOT_AVAILABLE_SOG and sog >= 0:
        payload["speed_mps"] = round(sog * KNOT_MPS, 2)
        extra["sog_knots"] = sog
    cog = _number(report.get("Cog"))
    heading = report.get("TrueHeading")
    if cog is not None and 0 <= cog < NOT_AVAILABLE_COG:
        payload["heading_deg"] = cog
        extra["cog_deg"] = cog
    elif isinstance(heading, int) and not isinstance(heading, bool) and 0 <= heading < NOT_AVAILABLE_HEADING:
        payload["heading_deg"] = heading
    if isinstance(heading, int) and not isinstance(heading, bool) and 0 <= heading < NOT_AVAILABLE_HEADING:
        extra["true_heading_deg"] = heading
    for key, name in (("NavigationalStatus", "navigational_status"), ("RateOfTurn", "rate_of_turn")):
        if key in report and report[key] is not None:
            extra[name] = report[key]
    name = message.get("MetaData", {}).get("ShipName")
    if isinstance(name, str) and name.strip():
        extra["ship_name"] = name.strip()
    payload["tracker"] = TRACKER
    payload["raw_id"] = f"{TRACKER}:{extra['mmsi']}:{int(fix.timestamp())}"
    payload["subject"] = asset.id
    payload["extra"] = extra
    return {
        "at": fix.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": None,
        "tz": None,  # the logbook's own
        "source": NAME,
        "kind": KIND,
        "tier": TIER,
        "payload": payload,
    }


def _report(message: Mapping[str, Any]) -> dict[str, Any]:
    body = message.get("Message")
    if isinstance(body, dict):
        report = body.get(str(message.get("MessageType")))
        if isinstance(report, dict):
            return report
    return {}


def _mmsi(message: Mapping[str, Any]) -> str:
    meta = message.get("MetaData")
    value = meta.get("MMSI") if isinstance(meta, dict) else None
    if value is None:
        value = _report(message).get("UserID")
    return str(value) if value is not None else ""


def _fix_time(message: Mapping[str, Any]) -> datetime | None:
    """`MetaData.time_utc` to the second, or None when absent or not in aisstream's layout."""
    meta = message.get("MetaData")
    stamp = meta.get("time_utc") if isinstance(meta, dict) else None
    if not isinstance(stamp, str):
        return None
    m = TIME_UTC.match(stamp.strip())
    if m is None:
        return None
    try:
        return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}").replace(tzinfo=UTC)
    except ValueError:
        return None


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def _degrees(value: object, limit: int) -> float | None:
    """A coordinate as a number strictly within ±limit: AIS reports 91 and 181 for "not available"."""
    number = _number(value)
    return number if number is not None and -limit <= number <= limit else None
