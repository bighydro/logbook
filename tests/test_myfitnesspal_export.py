"""MyFitnessPal's CSV export (`Nutrition-Summary-<from>-to-<to>.csv`) → health-sample/v1 (RFC 0014):
one `energy_intake` line per meal per day, a span over the local day, the macros, water and note under
`extra`; a later export that corrects a meal supersedes the line already in the record."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters, cli
from logbook.adapters import myfitnesspal
from logbook.core import health
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
RFC = ROOT / "rfcs" / "0014-health-sample-v1.md"
EXPORT = ROOT / "tests" / "fixtures" / "myfitnesspal" / "Nutrition-Summary-2026-06-08-to-2026-06-14.csv"
TZ = "Europe/Oslo"
LINES = 7


def _schema() -> dict[str, Any]:
    text = RFC.read_text(encoding="utf-8")
    block = re.search(r"## JSON Schema\n\n```json\n(.*?)\n```", text, re.S)
    assert block is not None
    return json.loads(block.group(1))  # type: ignore[no-any-return]


def _run(path: Path = EXPORT, **options: Any) -> tuple[list[dict[str, Any]], dict[str, int]]:
    counts: dict[str, int] = {}
    lines = list(myfitnesspal.run(path, counts=counts, timezone=TZ, **options))
    return lines, counts


# -- the reader -------------------------------------------------------------------------------------


def test_sniff_takes_the_nutrition_export_and_nothing_else(tmp_path):
    assert myfitnesspal.sniff(EXPORT)
    assert adapters.find(EXPORT) is myfitnesspal
    other = tmp_path / "other.csv"
    other.write_text("Date,Weight\n2026-06-08,78.4\n", encoding="utf-8")
    assert not myfitnesspal.sniff(other)
    assert not myfitnesspal.sniff(tmp_path)
    assert not myfitnesspal.sniff(tmp_path / "missing.csv")


def test_every_line_is_a_health_sample_with_the_rfc_payload():
    lines, _counts = _run()
    assert len(lines) == LINES
    validator = Draft202012Validator(_schema())
    for line in lines:
        assert (line["source"], line["kind"], line["tier"], line["tz"]) == ("myfitnesspal", "health", 3, TZ)
        validator.validate(line["payload"])
        assert line["payload"]["type"] == "energy_intake"
        assert line["payload"]["unit"] == "kcal"
        assert line["payload"]["source_name"] == "MyFitnessPal"
    assert [line["at"] for line in lines] == sorted(line["at"] for line in lines)
    assert len({line["payload"]["raw_id"] for line in lines}) == LINES


def test_a_meal_is_a_span_over_its_local_day_with_the_macros_water_and_note_beside_it():
    lines, _counts = _run()
    breakfast = lines[0]
    assert (breakfast["at"], breakfast["end"]) == ("2026-06-07T22:00:00Z", "2026-06-08T22:00:00Z")  # CEST
    assert breakfast["payload"]["raw_id"] == "energy_intake:2026-06-08:breakfast"
    assert breakfast["payload"]["value"] == 412
    assert breakfast["payload"]["extra"] == {
        "meal": "Breakfast",
        "all_day": True,
        "fat_g": 14,
        "saturated_fat": 4,
        "polyunsaturated_fat": 2,
        "monounsaturated_fat": 6,
        "trans_fat": 0,
        "cholesterol": 35,
        "sodium_mg": 310,
        "potassium": 420,
        "carbohydrates_g": 52,
        "fiber": 6,
        "sugar": 12,
        "protein_g": 21,
        "vitamin_a": 10,
        "vitamin_c": 25,
        "calcium": 20,
        "iron": 8,
        "water_ml": 500,
        "note": "oats and berries",
    }
    lunch = lines[2]  # one day's meals share an `at` and sort by `raw_id`
    assert lunch["payload"]["extra"]["meal"] == "Lunch"
    assert "water_ml" not in lunch["payload"]["extra"] and "note" not in lunch["payload"]["extra"]
    assert [line["payload"]["raw_id"] for line in lines] == [
        "energy_intake:2026-06-08:breakfast",
        "energy_intake:2026-06-08:dinner",
        "energy_intake:2026-06-08:lunch",
        "energy_intake:2026-06-08:snacks",
        "energy_intake:2026-06-09:breakfast",
        "energy_intake:2026-06-09:dinner",
        "energy_intake:2026-06-10:lunch",
    ]


def test_a_meal_without_calories_and_a_row_without_a_day_are_counted():
    _lines, counts = _run()
    assert counts == {"skipped_no_value": 1, "skipped_bad_date": 1}


def test_since_and_tier():
    lines, _counts = _run(since="2026-06-08T22:00:00Z", tier=2)  # 9 June, local midnight
    assert [line["payload"]["raw_id"] for line in lines] == [
        "energy_intake:2026-06-09:breakfast",
        "energy_intake:2026-06-09:dinner",
        "energy_intake:2026-06-10:lunch",
    ]
    assert all(line["tier"] == 2 for line in lines)


def test_a_column_this_reader_does_not_need_may_be_missing_and_one_it_needs_may_not(tmp_path):
    export = tmp_path / "Nutrition-Summary-2026-06-08-to-2026-06-08.csv"
    export.write_text("Date,Meal,Calories\n2026-06-08,Breakfast,412\n", encoding="utf-8")
    lines, counts = _run(export)
    assert [line["payload"]["value"] for line in lines] == [412]
    assert lines[0]["payload"]["extra"] == {"meal": "Breakfast", "all_day": True}
    assert counts == {}
    export.write_text("Date,Calories\n2026-06-08,412\n", encoding="utf-8")
    assert _run(export) == ([], {"skipped_unreadable_csv": 1})


def test_the_export_is_never_written(tmp_path):
    copy = tmp_path / EXPORT.name
    copy.write_bytes(EXPORT.read_bytes())
    _run(copy)
    assert copy.read_bytes() == EXPORT.read_bytes()


# -- through the CLI --------------------------------------------------------------------------------


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook.init(root, TZ)


def _corrected_export(dst: Path, calories: str) -> Path:
    """The fixture with the 8 June breakfast re-logged, as a later export of the same account."""
    text = EXPORT.read_text(encoding="utf-8")
    dst.write_text(
        text.replace("2026-06-08,Breakfast,412,", f"2026-06-08,Breakfast,{calories},"), encoding="utf-8"
    )
    return dst


def test_add_myfitnesspal_appends_once_and_reports_the_skips(lb, capsys):
    cli.main(["add", "myfitnesspal", str(EXPORT)])
    out = capsys.readouterr().out
    assert f"added {LINES} lines from myfitnesspal" in out
    assert "1 without a value" in out and "1 with an unusable date" in out
    cli.main(["add", str(EXPORT)])  # sniffed, not named
    assert "added 0 lines from myfitnesspal" in capsys.readouterr().out
    seq, _head, errors = lb.verify()
    assert (seq, errors) == (LINES, [])


def test_a_later_export_that_corrects_a_meal_supersedes_the_line(lb, tmp_path, capsys):
    cli.main(["add", "myfitnesspal", str(EXPORT)])
    capsys.readouterr()
    later = _corrected_export(tmp_path / "Nutrition-Summary-2026-06-08-to-2026-06-21.csv", "430")
    cli.main(["add", "myfitnesspal", str(later)])
    out = capsys.readouterr().out
    assert "added 1 lines from myfitnesspal" in out and "1 corrected" in out
    with lb.index() as idx:
        lines = list(idx.of_kind("health"))
    (old,) = (line for line in lines if line["payload"]["raw_id"] == "energy_intake:2026-06-08:breakfast")
    (new,) = (line for line in lines if line["payload"]["raw_id"] == "energy_intake:2026-06-08:breakfast:v2")
    assert new["payload"]["value"] == 430
    assert new["payload"]["supersedes"] == old["id"]
    assert (new["at"], new["end"]) == (old["at"], old["end"])
    standing = {line["payload"]["raw_id"] for line in health.standing(lines)}
    assert "energy_intake:2026-06-08:breakfast:v2" in standing
    assert "energy_intake:2026-06-08:breakfast" not in standing
    cli.main(["add", "myfitnesspal", str(later)])
    assert "added 0 lines" in capsys.readouterr().out
    seq, _head, errors = lb.verify()
    assert (seq, errors) == (LINES + 1, [])


def test_dry_run_counts_and_writes_nothing(lb, capsys):
    cli.main(["add", "myfitnesspal", str(EXPORT), "--dry-run"])
    out = capsys.readouterr().out
    assert (
        f"myfitnesspal: {LINES} lines would be added, 0 already in the record (dry run, nothing written)"
        in out
    )
    assert "1 without a value" in out
    assert lb.verify()[0] == 0
