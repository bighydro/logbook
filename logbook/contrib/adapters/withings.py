"""The Withings app's stores → health-sample/v1 (RFC 0014).

The app (`AppDomain-com.withings.wiScaleNG`) keeps one set of Core Data stores per profile under
`Library/Application Support/coredata/`, named by the profile's number. Two of them matter:

    <profile>_WTHealth.sqlite   the scale's readings, one row per quantity:
        ZWTOBJECT         (ZTYPEIDENTIFIER `WTQuantityType.weight` …, ZSTARTDATE/ZENDDATE — seconds since
                           2001-01-01 UTC —, ZQUANTITY → ZWTQUANTITY, ZSOURCE → ZWTSOURCE,
                           ZSEARCHABLEMETADATA → ZWTSEARCHABLEMETADATA, ZISREMOVED, ZLOCALIDENTIFIER)
        ZWTQUANTITY       (ZVALUE)
        ZWTSOURCE         (ZBRAND, ZDEVICEMODEL, ZBUNDLEIDENTIFIER: empty or the app's own for the
                           scale; another app's when the row was relayed from Apple Health)
        ZWTSEARCHABLEMETADATA (ZTIMEZONE, an IANA name)
    <profile>_Measure.sqlite    the app's measurement groups, one per standing or reading:
        ZWTMEASUREGROUP   (ZDATE, ZTIMEZONE, ZDEVICEMODEL, ZREMOVED, ZIDENTIFIER)
        ZWTSPECIALIZEDGROUP (Z_ENT names the kind of group through Z_PRIMARYKEY — `WTHeartRateGroup`,
                           `WTHeightGroup`, `WTBloodPressureGroup` —, ZGROUP → the group, ZHEARTRATE →
                           ZWTMEASURE)
        ZWTMEASURE        (ZMANTISSA, ZEXPONENT: the value is mantissa x 10^exponent)

`run` takes either store, or the folder: a `_WTHealth` store brings the `_Measure` store of the same
profile beside it and the other way round; a folder brings every profile in it (`logbook import-backup`
copies the folder's stores out as `withings/` and runs on the folder). Types mapped (rule 8: anything
else is skipped and counted): `weight` kg, `fatMassPercentage` → `body_fat_pct` %, `fatMass`,
`fatFreeMass`, `muscleMass`, `boneMass`, `hydration` → `body_water`, all kg as the store keeps them,
`bmi` kg/m2, `vo2Max` → `vo2_max` mL/kg/min; a heart-rate group → `heart_rate` bpm. Impedance
segments, scores, metabolic age, height and blood pressure are not in the profile and are counted.

A row whose source is another app (`ZBUNDLEIDENTIFIER` set and not the app's own: Apple Health relaying
a watch or another scale) is skipped and counted `skipped_relayed` (rule 11): the record gets it once,
from that app's adapter. Removed rows and groups are skipped (`skipped_deleted`), as are rows without
a value (a correlation row that only groups quantities) or without a date.

`raw_id` is `<type>:<profile>:<local identifier>` (the group's identifier for a heart rate), so two
profiles never collide. `device` is the store's device model number as text; `extra.profile` the
profile's number. `tz` is the row's zone name when it is an IANA name, else the record's. Every line is
tier 3 (SPEC §4; `logbook add --tier` overrides). Pure: stores opened `mode=ro`, `immutable=1`, each
read once; lines of one run are yielded in `at` order; no network.

The same adapter reads the account's data export (`logbook add withings <folder>`, the CSVs of
*Download my data*: weight and body composition, blood pressure, sleep, heart rate, steps, workouts)
through `withings_export`, whose docstring has the files and the mapping; a later export that corrects
a sample supersedes the line already in the record (`health_export.corrected`, through `existing` when
`logbook add` passes it).
"""

from __future__ import annotations

import heapq
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import health_export, withings_export

NAME = "withings"
KIND = "health"
TIER = 3
SCHEMA = "health-sample/v1"

SQLITE_HEADER = b"SQLite format 3\x00"
APPLE_EPOCH_UTC = datetime(2001, 1, 1, tzinfo=UTC)
PLACEHOLDER_BEFORE_YEAR = 1900
HEALTH_SUFFIX = "_WTHealth.sqlite"
MEASURE_SUFFIX = "_Measure.sqlite"
HEALTH_TABLES = ("ZWTOBJECT", "ZWTQUANTITY")
MEASURE_TABLES = ("ZWTMEASURE", "ZWTSPECIALIZEDGROUP", "ZWTMEASUREGROUP")
OWN_BUNDLE_PREFIX = "com.withings"
HEART_RATE_GROUP = "WTHeartRateGroup"

TYPES = {  # ZTYPEIDENTIFIER → (profile type, unit)
    "WTQuantityType.weight": ("weight", "kg"),
    "WTQuantityType.fatMassPercentage": ("body_fat_pct", "%"),
    "WTQuantityType.fatMass": ("fat_mass", "kg"),
    "WTQuantityType.fatFreeMass": ("fat_free_mass", "kg"),
    "WTQuantityType.muscleMass": ("muscle_mass", "kg"),
    "WTQuantityType.boneMass": ("bone_mass", "kg"),
    "WTQuantityType.hydration": ("body_water", "kg"),
    "WTQuantityType.bmi": ("bmi", "kg/m2"),
    "WTQuantityType.vo2Max": ("vo2_max", "mL/kg/min"),
}


def sniff(path: Path) -> bool:
    """A Withings `_WTHealth` or `_Measure` SQLite store, or the data export's folder or one of its
    CSVs. Never raises."""
    path = Path(path)
    if withings_export.is_export(path):
        return True
    try:
        if not path.is_file():
            return False
        with path.open("rb") as fh:
            if fh.read(len(SQLITE_HEADER)) != SQLITE_HEADER:
                return False
        con = _open(path)
    except (OSError, ValueError, sqlite3.Error):
        return False
    try:
        tables = _tables(con)
        return all(t in tables for t in HEALTH_TABLES) or all(t in tables for t in MEASURE_TABLES)
    except sqlite3.Error:
        return False
    finally:
        con.close()


def _open(path: Path) -> sqlite3.Connection:
    """Read-only and immutable: SQLite neither locks the file nor writes a journal beside it."""
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)


def _tables(con: sqlite3.Connection) -> set[str]:
    rows = con.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(name) for (name,) in rows}


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
    tier: int | None = None,
    existing: health_export.Existing | None = None,
) -> Iterator[dict[str, Any]]:
    """One health-sample/v1 line per reading, in `at` order across the stores (or the export's files)
    read.

    `since` is RFC3339 UTC; lines with `at` before it are not yielded. `counts` tallies
    `skipped_relayed`, `skipped_deleted`, `skipped_no_value`, `skipped_no_date`,
    `skipped_placeholder_date` and `skipped_other_type` (the export's own are in `withings_export`).
    `timezone` is the record's zone, used when a row has none; `tier` overrides 3. `existing` is the
    record's standing lines by `(source, raw_id)`, for the corrections (`health_export.corrected`)."""
    path = Path(path)
    counts = counts if counts is not None else {}
    streams = [
        _store_lines(store, counts, timezone, tier or TIER) for store in _stores(path) if store.is_file()
    ]
    if withings_export.is_export(path):
        streams.append(withings_export.lines(path, counts, timezone, tier or TIER))
    merged = heapq.merge(*streams, key=lambda line: (line["at"], line["payload"]["raw_id"]))
    yield from health_export.corrected(
        (line for line in merged if not since or line["at"] >= since), existing, counts
    )


def _stores(path: Path) -> list[Path]:
    """The stores one call reads: every profile's two stores in a folder; a store and its partner
    of the same profile otherwise; none for a file of the export."""
    if path.is_dir():
        return sorted(p for p in path.iterdir() if p.name.endswith((HEALTH_SUFFIX, MEASURE_SUFFIX)))
    if path.suffix.lower() == ".csv":
        return []
    name = path.name
    for suffix, partner in ((HEALTH_SUFFIX, MEASURE_SUFFIX), (MEASURE_SUFFIX, HEALTH_SUFFIX)):
        if name.endswith(suffix):
            return [path, path.with_name(name[: -len(suffix)] + partner)]
    return [path]


def _profile(store: Path) -> str | None:
    """The profile number a store's name starts with (`46567466_WTHealth.sqlite`), else None."""
    head, sep, _tail = store.name.partition("_")
    return head if sep and head.isdigit() else None


def _store_lines(
    store: Path, counts: dict[str, int], timezone: str | None, tier: int
) -> list[dict[str, Any]]:
    """Every line of one store, sorted by `at`; a store that is neither kind gives none."""
    try:
        con = _open(store)
    except (OSError, ValueError, sqlite3.Error):
        return []
    try:
        tables = _tables(con)
        profile = _profile(store)
        if all(t in tables for t in HEALTH_TABLES):
            lines = list(_health(con, tables, profile, counts, timezone, tier))
        elif all(t in tables for t in MEASURE_TABLES):
            lines = list(_measures(con, tables, profile, counts, timezone, tier))
        else:
            return []
    except sqlite3.Error:
        return []
    finally:
        con.close()
    lines.sort(key=lambda line: (line["at"], line["payload"]["raw_id"]))
    return lines


def _health(
    con: sqlite3.Connection,
    tables: set[str],
    profile: str | None,
    counts: dict[str, int],
    timezone: str | None,
    tier: int,
) -> Iterator[dict[str, Any]]:
    objects = _columns(con, "ZWTOBJECT")
    select = ["o.Z_PK", "o.ZTYPEIDENTIFIER", "o.ZSTARTDATE", "o.ZENDDATE", "q.ZVALUE"]
    for column in ("ZISREMOVED", "ZLOCALIDENTIFIER"):
        select.append(f"o.{column}" if column in objects else f"NULL AS {column}")
    joins = ["LEFT JOIN ZWTQUANTITY q ON q.Z_PK = o.ZQUANTITY"]
    if "ZWTSOURCE" in tables and "ZSOURCE" in objects:
        sources = _columns(con, "ZWTSOURCE")
        select.append("s.ZBUNDLEIDENTIFIER" if "ZBUNDLEIDENTIFIER" in sources else "NULL")
        select.append("s.ZDEVICEMODEL" if "ZDEVICEMODEL" in sources else "NULL")
        joins.append("LEFT JOIN ZWTSOURCE s ON s.Z_PK = o.ZSOURCE")
    else:
        select += ["NULL", "NULL"]
    if "ZWTSEARCHABLEMETADATA" in tables and "ZSEARCHABLEMETADATA" in objects:
        select.append("m.ZTIMEZONE" if "ZTIMEZONE" in _columns(con, "ZWTSEARCHABLEMETADATA") else "NULL")
        joins.append("LEFT JOIN ZWTSEARCHABLEMETADATA m ON m.Z_PK = o.ZSEARCHABLEMETADATA")
    else:
        select.append("NULL")
    sql = f"SELECT {', '.join(select)} FROM ZWTOBJECT o {' '.join(joins)} ORDER BY o.ZSTARTDATE, o.Z_PK"
    for pk, kind, start, end, value, removed, local_id, bundle, model, zone in con.execute(sql):
        if removed:
            _count(counts, "skipped_deleted")
            continue
        number = _number(value)
        if number is None:
            _count(counts, "skipped_no_value")
            continue
        bundle_id = _text(bundle)
        if bundle_id and not bundle_id.startswith(OWN_BUNDLE_PREFIX):
            _count(counts, "skipped_relayed")
            continue
        mapped = TYPES.get(_text(kind))
        if mapped is None:
            _count(counts, "skipped_other_type")
            continue
        started = _datetime(start)
        if started is None:
            _count(counts, "skipped_no_date")
            continue
        if started.year < PLACEHOLDER_BEFORE_YEAR:
            _count(counts, "skipped_placeholder_date")
            continue
        ended = _datetime(end)
        if ended is not None and ended <= started:
            ended = None
        type_name, unit = mapped
        yield _line(
            type_name,
            unit,
            _round(number),
            started,
            ended,
            _raw_id(type_name, profile, _text(local_id) or f"row{pk}"),
            model,
            _zone(zone) or timezone,
            profile,
            tier,
        )


def _measures(
    con: sqlite3.Connection,
    tables: set[str],
    profile: str | None,
    counts: dict[str, int],
    timezone: str | None,
    tier: int,
) -> Iterator[dict[str, Any]]:
    names = _entity_names(con, tables)
    group_columns = _columns(con, "ZWTMEASUREGROUP")
    special = _columns(con, "ZWTSPECIALIZEDGROUP")
    if "ZGROUP" not in special or "ZHEARTRATE" not in special:
        return
    select = ["g.Z_PK", "s.Z_ENT", "g.ZDATE", "m.ZMANTISSA", "m.ZEXPONENT"]
    for column in ("ZREMOVED", "ZIDENTIFIER", "ZTIMEZONE", "ZDEVICEMODEL"):
        select.append(f"g.{column}" if column in group_columns else f"NULL AS {column}")
    sql = (
        f"SELECT {', '.join(select)} FROM ZWTSPECIALIZEDGROUP s"
        " JOIN ZWTMEASUREGROUP g ON g.Z_PK = s.ZGROUP"
        " LEFT JOIN ZWTMEASURE m ON m.Z_PK = s.ZHEARTRATE"
        " ORDER BY g.ZDATE, g.Z_PK"
    )
    for pk, entity, date, mantissa, exponent, removed, identifier, zone, model in con.execute(sql):
        if removed:
            _count(counts, "skipped_deleted")
            continue
        if names.get(entity) != HEART_RATE_GROUP:
            _count(counts, "skipped_other_type")
            continue
        m, e = _number(mantissa), _number(exponent)
        if m is None or e is None:
            _count(counts, "skipped_no_value")
            continue
        taken = _datetime(date)
        if taken is None:
            _count(counts, "skipped_no_date")
            continue
        if taken.year < PLACEHOLDER_BEFORE_YEAR:
            _count(counts, "skipped_placeholder_date")
            continue
        yield _line(
            "heart_rate",
            "bpm",
            _round(m * 10 ** int(e)),
            taken,
            None,
            _raw_id("heart_rate", profile, _text(identifier) or f"group{pk}"),
            model,
            _zone(zone) or timezone,
            profile,
            tier,
        )


def _entity_names(con: sqlite3.Connection, tables: set[str]) -> dict[int, str]:
    if "Z_PRIMARYKEY" not in tables:
        return {}
    return {
        int(ent): str(name)
        for ent, name in con.execute("SELECT Z_ENT, Z_NAME FROM Z_PRIMARYKEY")
        if isinstance(ent, int) and isinstance(name, str)
    }


def _raw_id(type_name: str, profile: str | None, local: str) -> str:
    return f"{type_name}:{profile}:{local}" if profile else f"{type_name}:{local}"


def _line(
    type_name: str,
    unit: str,
    value: int | float,
    start: datetime,
    end: datetime | None,
    raw_id: str,
    model: object,
    tz: str | None,
    profile: str | None,
    tier: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": raw_id,
        "type": type_name,
        "value": value,
        "unit": unit,
    }
    device = _number(model)
    if device is not None:
        payload["device"] = str(int(device))
    if profile:
        payload["extra"] = {"profile": profile}
    return {
        "at": _stamp(start),
        "end": _stamp(end) if end is not None else None,
        "tz": tz,
        "source": NAME,
        "kind": KIND,
        "tier": tier,
        "payload": payload,
    }


def _zone(value: object) -> str | None:
    name = _text(value)
    if not name or " " in name:
        return None
    return name if "/" in name or name in ("UTC", "Etc/UTC") else None


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _text(value: object) -> str:
    if isinstance(value, bytes | bytearray | memoryview):
        try:
            return bytes(value).decode("utf-8").strip()
        except UnicodeDecodeError:
            return ""
    return value.strip() if isinstance(value, str) else ""


def _number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def _round(value: int | float) -> int | float:
    rounded = round(float(value), 3)
    return int(rounded) if rounded == int(rounded) else rounded


def _datetime(seconds_since_2001: object) -> datetime | None:
    """Arithmetic from the epoch, not `fromtimestamp`: Windows refuses instants before 1970."""
    number = _number(seconds_since_2001)
    if number is None:
        return None
    try:
        return APPLE_EPOCH_UTC + timedelta(seconds=int(number))
    except (OverflowError, ValueError):
        return None


def _stamp(when: datetime) -> str:
    return when.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"
