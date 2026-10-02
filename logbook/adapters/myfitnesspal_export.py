"""MyFitnessPal's CSV export (`Nutrition-Summary-<from>-to-<to>.csv`) → health-sample/v1 (RFC 0014).

Not an adapter: `myfitnesspal.run` reads the export through here when its path is a CSV, and the
app's `maindb.sqlite` otherwise; both write `source` `myfitnesspal`. The export (*Settings → Export
data*) is one row per meal per day:

    Date, Meal, Calories, Fat (g), Saturated Fat, Polyunsaturated Fat, Monounsaturated Fat, Trans Fat,
    Cholesterol, Sodium (mg), Potassium, Carbohydrates (g), Fiber, Sugar, Protein (g), Vitamin A,
    Vitamin C, Calcium, Iron, Note

`Date`, `Meal` and `Calories` are needed (a file without them is counted `skipped_unreadable_csv`);
every other column may be missing, renamed or new. A row is one `energy_intake` line (rule 10):
`value` the calories as the export summed them; a span over that local day in the record's zone
(`at` midnight, `end` the next) with `extra.all_day` true, since the export keeps the day and never
the clock; the meal under `extra.meal`; every other numeric cell the row has under `extra` keyed by
its header slugged (`Fat (g)` → `fat_g`, `Sodium (mg)` → `sodium_mg`, `Saturated Fat` →
`saturated_fat` as the export leaves it unitless, `Water (ml)` → `water_ml` when the export carries
water); the note under `extra.note`. Nothing about nutrition beyond kilocalories is a type, so the
macros and the water ride on the meal's line, as `extra` is what else the source reports. `raw_id`
is `energy_intake:<date>:<meal slug>`, the same in every later export, so re-adding appends nothing
and a re-logged meal is a correction (`health_export.corrected`). A row without a number in
`Calories` is counted `skipped_no_value`, one whose day will not parse `skipped_bad_date`.
`source_name` is `MyFitnessPal`. Pure: the file opened read-only, once; no network."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from . import health_export as hx

SOURCE = "myfitnesspal"
KIND = "health"
SCHEMA = "health-sample/v1"
SOURCE_NAME = "MyFitnessPal"

NEEDED = ("date", "meal", "calories")
NOTE = ("note", "notes")


def is_export(path: Path) -> bool:
    """A CSV whose header has Date, Meal and Calories. Never raises."""
    path = Path(path)
    try:
        if not path.is_file() or path.suffix.lower() != ".csv":
            return False
        with path.open(encoding="utf-8-sig", errors="replace") as fh:
            header = [cell.strip().lower() for cell in fh.readline().split(",")]
    except OSError:
        return False
    return all(name in header for name in NEEDED)


def lines(path: Path, counts: dict[str, int], timezone: str | None, tier: int) -> list[dict[str, Any]]:
    """Every line of the export at `path`, sorted by `at` then `raw_id`."""
    read = hx.rows(path)
    if read is None:
        hx.count(counts, "skipped_unreadable_csv")
        return []
    header, rows = read
    if not all(name in header for name in NEEDED):
        hx.count(counts, "skipped_unreadable_csv")
        return []
    out = list(_meals(header, rows, hx.zone(timezone), timezone, tier, counts))
    out.sort(key=lambda line: (line["at"], line["payload"]["raw_id"]))
    return out


def _meals(
    header: list[str],
    rows: list[dict[str, str]],
    local: Any,
    tz: str | None,
    tier: int,
    counts: dict[str, int],
) -> Iterator[dict[str, Any]]:
    note = hx.column(header, *NOTE)
    others = [cell for cell in header if cell not in NEEDED and cell != note and cell]
    for row in rows:
        day = _day(row["date"])
        if day is None:
            hx.count(counts, "skipped_bad_date")
            continue
        value = hx.number(row["calories"])
        if value is None:
            hx.count(counts, "skipped_no_value")
            continue
        meal = row["meal"]
        extra: dict[str, Any] = {"meal": meal, "all_day": True}
        for cell in others:
            number = hx.number(row[cell])
            if number is not None:
                extra[hx.slug(cell)] = number
        if note and row[note]:
            extra["note"] = row[note]
        start = datetime.combine(day, time.min, tzinfo=local)
        end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=local)
        yield {
            "at": hx.stamp(start),
            "end": hx.stamp(end),
            "tz": tz,
            "source": SOURCE,
            "kind": KIND,
            "tier": tier,
            "payload": {
                "schema": SCHEMA,
                "raw_id": f"energy_intake:{day.isoformat()}:{hx.slug(meal) or 'meal'}",
                "type": "energy_intake",
                "value": value,
                "unit": "kcal",
                "source_name": SOURCE_NAME,
                "extra": extra,
            },
        }


def _day(text: str) -> date | None:
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        return None
