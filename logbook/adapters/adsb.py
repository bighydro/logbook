"""ADS-B → location/v1 (RFC 0001) with `subject`: the positions of the owner's own aircraft (ADR 0018).

Two entrances, one mapping (ADR 0017). The file mode reads a saved OpenSky Network `states/all`
response (`{"time": <unix>, "states": [[...], ...]}`). The live mode, `logbook sync adsb`, asks
`GET /api/states/all?icao24=<a>&icao24=<b>` for the current state of every registered asset that has
an icao24 address, anonymously by default (no key needed for that) or with basic credentials from
`LOGBOOK_OPENSKY_USER` and `LOGBOOK_OPENSKY_PASS` for the higher rate limit. Stdlib urllib. Both
call `draft(state, asset)`.

A state vector is a list in OpenSky's documented order: icao24, callsign, origin_country,
time_position, last_contact, longitude, latitude, baro_altitude, on_ground, velocity, true_track,
vertical_rate, sensors, geo_altitude, squawk, spi, position_source, category. `at` is
`time_position`, the fix time (not `last_contact`); `raw_id` is `opensky:<icao24>:<time_position>`,
so a parked aircraft whose last fix is unchanged is the same line poll after poll, and a response
saved to a file and the same response polled live are one line. A vector with no fix time or no
position is skipped and counted. `alt_m` is the geometric altitude, else the barometric one.

`states/all` is the present, not history: `since` only filters what came back, there is no
`resume`, and each asset keeps its own watermark (`GROUP_MARKS`) so `state/adsb.json` says when
each was last seen. Credentials go only in the Authorization header, never in a URL, the config's
repr, or a message. Network happens only inside `pull` (ADR 0012).
"""

from __future__ import annotations

import base64
import json
import math
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..assets import Asset, by_icao24
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

NAME = "adsb"
KIND = "location"
TIER = 1
SCHEMA = "location/v1"
TRACKER = "opensky"
ENV = ("LOGBOOK_OPENSKY_USER", "LOGBOOK_OPENSKY_PASS")  # both optional: anonymous access needs neither
URL_ENV = "LOGBOOK_OPENSKY_URL"
DEFAULT_URL = "https://opensky-network.org/api"
UNIT = "states"
GROUP_MARKS = True  # `sync` keeps a watermark per group (per asset) in the state file
TIMEOUT_S = 60
# Beyond datetime's range on every platform (Windows refuses negative and far-future stamps).
MAX_UNIX = 32_503_680_000  # 3000-01-01

# the state vector's columns, in OpenSky's documented order
ICAO24, CALLSIGN, ORIGIN_COUNTRY, TIME_POSITION, LAST_CONTACT, LONGITUDE, LATITUDE, BARO_ALTITUDE = range(8)
ON_GROUND, VELOCITY, TRUE_TRACK, VERTICAL_RATE, SENSORS, GEO_ALTITUDE, SQUAWK, SPI, POSITION_SOURCE = range(
    8, 17
)

UNKNOWN_SUBJECT = "skipped_unknown_subject"
BAD_COORDINATES = "skipped_bad_coordinates"
NO_TIMESTAMP = "skipped_no_timestamp"


@dataclass(frozen=True)
class Config:
    url: str = DEFAULT_URL
    user: str | None = None
    password: str | None = field(default=None, repr=False)


def configure(env: Mapping[str, str]) -> Config:
    """Never None: anonymous access needs no variable. Credentials come as a pair; raises ValueError
    when only one of LOGBOOK_OPENSKY_USER and LOGBOOK_OPENSKY_PASS is set."""
    user, password = (env.get(name, "").strip() for name in ENV)
    if bool(user) != bool(password):
        missing = ENV[1] if user else ENV[0]
        raise ValueError(
            f"{ENV[0]} and {ENV[1]} go together; set {missing} too, or neither for anonymous access"
        )
    url = env.get(URL_ENV, "").strip().rstrip("/") or DEFAULT_URL
    return Config(url=url, user=user or None, password=password or None)


# -- the file mode ---------------------------------------------------------------------------------


def sniff(path: Path) -> bool:
    """A JSON object with an integer `time` and a `states` list (or null): a saved states/all response."""
    path = Path(path)
    if not path.is_file() or path.suffix.lower() != ".json":
        return False
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return _is_response(doc)


def _is_response(doc: object) -> bool:
    return (
        isinstance(doc, dict)
        and isinstance(doc.get("time"), int)
        and "states" in doc
        and (doc["states"] is None or isinstance(doc["states"], list))
    )


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    assets: Iterable[Asset] | None = None,
) -> Iterator[dict[str, Any]]:
    """One location/v1 line draft per state vector of a registered aircraft, in response order. A
    vector of an aircraft not in `assets`, without a fix time or without a position is skipped and
    counted."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not _is_response(doc):
        raise ValueError(f"{path} is not an OpenSky states/all response")
    yield from _lines(doc["states"] or [], since, _counts(counts if counts is not None else {}), assets)


def _lines(
    states: Sequence[Any], since: str | None, counts: dict[str, int], assets: Iterable[Asset] | None
) -> Iterator[dict[str, Any]]:
    aircraft = by_icao24(assets or ())
    cutoff = utc(since) if since else None
    for state in states:
        line = _line(state, aircraft, counts)
        if line is not None and (cutoff is None or str(line["at"]) >= cutoff):
            yield line


# -- the live mode ---------------------------------------------------------------------------------


def watermark(draft: dict[str, Any]) -> str | None:
    """The fix time: the API has no other clock for a state."""
    return str(draft["at"])


def group(draft: dict[str, Any]) -> str:
    """The asset, so `sync` reports seen and new per aircraft and keeps a watermark for each."""
    return str(draft["payload"]["subject"])


def pull(
    config: Config,
    since: str | None = None,
    progress: Callable[[int, float], None] | None = None,
    counts: dict[str, int] | None = None,
    assets: Iterable[Asset] | None = None,
) -> Iterator[dict[str, Any]]:
    """One GET states/all for every registered icao24; one line draft per aircraft with a fix, oldest
    first. `since` drops older fixes. ValueError when no asset has an icao24 or the body is not a
    states response; OSError, without the password, for an HTTP or network failure."""
    counts = _counts(counts if counts is not None else {})
    registry = list(assets or ())
    addresses = sorted(by_icao24(registry))
    if not addresses:
        raise ValueError(
            "no registered asset has an icao24; register the aircraft first: "
            "logbook assets add <id> --kind aircraft --name NAME --icao24 <six hex digits>"
        )
    doc = _get(config, addresses)
    lines = sorted(_lines(doc["states"] or [], since, counts, registry), key=lambda line: str(line["at"]))
    if progress is not None:
        progress(len(doc["states"] or []), 0.0)
    yield from lines


def _get(config: Config, addresses: list[str]) -> dict[str, Any]:
    """One GET /states/all. The only network call in this module."""
    headers = {"Accept": "application/json"}
    if config.user is not None and config.password is not None:
        token = base64.b64encode(f"{config.user}:{config.password}".encode()).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    req = Request(f"{config.url}/states/all?{urlencode([('icao24', a) for a in addresses])}", headers=headers)
    try:
        with urlopen(req, timeout=TIMEOUT_S) as response:
            body = response.read()
    except HTTPError as e:
        if e.code == 401:
            raise OSError("OpenSky refused the credentials (401); check LOGBOOK_OPENSKY_USER/PASS") from None
        if e.code == 429:
            raise OSError("OpenSky rate limit reached (429); try again later or set credentials") from None
        raise OSError(f"OpenSky answered {e.code} {e.reason}") from None
    except URLError as e:
        raise OSError(f"OpenSky unreachable: {e.reason}") from None
    return _decode(body)


def _decode(body: bytes) -> dict[str, Any]:
    try:
        doc = json.loads(body.decode("utf-8"), parse_constant=lambda _name: None)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("expected a states/all response, got something that is not JSON") from None
    if not _is_response(doc):
        raise ValueError(f"expected a states/all response, got a JSON {type(doc).__name__}")
    response: dict[str, Any] = doc
    return response


# -- the mapping -----------------------------------------------------------------------------------


def _counts(counts: dict[str, int]) -> dict[str, int]:
    for key in (UNKNOWN_SUBJECT, NO_TIMESTAMP, BAD_COORDINATES):
        counts.setdefault(key, 0)
    return counts


def _line(state: Any, aircraft: Mapping[str, Asset], counts: dict[str, int]) -> dict[str, Any] | None:
    """The line draft for one state vector, or None (counted) when it is not a registered aircraft
    with a fix time and a position."""
    if not isinstance(state, list) or len(state) <= POSITION_SOURCE or not isinstance(state[ICAO24], str):
        counts[UNKNOWN_SUBJECT] += 1
        return None
    asset = aircraft.get(state[ICAO24].strip().lower())
    if asset is None:
        counts[UNKNOWN_SUBJECT] += 1
        return None
    stamp = state[TIME_POSITION]
    if isinstance(stamp, bool) or not isinstance(stamp, int | float) or not 0 <= stamp < MAX_UNIX:
        counts[NO_TIMESTAMP] += 1
        return None
    if _degrees(state[LATITUDE], 90) is None or _degrees(state[LONGITUDE], 180) is None:
        counts[BAD_COORDINATES] += 1
        return None
    return draft(state, asset)


def draft(state: Sequence[Any], asset: Asset) -> dict[str, Any]:
    """One OpenSky state vector → one location/v1 line draft with `subject` = the asset's id. The
    vector must carry `time_position`, `latitude` and `longitude` (see `_line`)."""
    payload: dict[str, Any] = {"schema": SCHEMA, "lat": state[LATITUDE], "lon": state[LONGITUDE]}
    alt = _number(state[GEO_ALTITUDE])
    if alt is None:
        alt = _number(state[BARO_ALTITUDE])
    if alt is not None:
        payload["alt_m"] = alt
    speed = _number(state[VELOCITY])
    if speed is not None and speed >= 0:
        payload["speed_mps"] = speed
    track = _number(state[TRUE_TRACK])
    if track is not None and 0 <= track <= 360:
        payload["heading_deg"] = track
    icao24 = str(state[ICAO24]).strip().lower()
    payload["tracker"] = TRACKER
    payload["raw_id"] = f"{TRACKER}:{icao24}:{int(state[TIME_POSITION])}"
    payload["subject"] = asset.id
    extra: dict[str, Any] = {"icao24": icao24}
    callsign = state[CALLSIGN]
    if isinstance(callsign, str) and callsign.strip():
        extra["callsign"] = callsign.strip()
    extra["on_ground"] = bool(state[ON_GROUND])
    for index, name in (
        (BARO_ALTITUDE, "baro_alt_m"),
        (VERTICAL_RATE, "vertical_rate_mps"),
        (SQUAWK, "squawk"),
        (LAST_CONTACT, "last_contact"),
        (POSITION_SOURCE, "position_source"),
    ):
        if state[index] is not None:
            extra[name] = state[index]
    payload["extra"] = extra
    return {
        "at": datetime.fromtimestamp(int(state[TIME_POSITION]), UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": None,
        "tz": None,  # the logbook's own
        "source": NAME,
        "kind": KIND,
        "tier": TIER,
        "payload": payload,
    }


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def _degrees(value: object, limit: int) -> float | None:
    number = _number(value)
    return number if number is not None and -limit <= number <= limit else None
