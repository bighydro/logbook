"""Regenerate the printed fixtures under `tests/fixtures/demo/`: `print_year_2026.html` and
`print_trip_2026-06-15.html`, the documents `logbook year 2026 --html PATH --print` and `logbook
trip trip:2026-06-15:2026-06-20 --html PATH --print` write; `poster_year_2026_A2.html` and
`poster_year_2026_A3.html`, the sheets `logbook year 2026 --poster --sheet A2|A3` writes; and
`paper_week_2026-W25.html`, the paper `logbook digest --paper --week 2026-W25` writes — all for
the demo record of thirty days with seed 7 (`logbook demo --days 30 --seed 7`), whose Oslo persona
does not exist. `tests/test_print_page.py` holds the paper edition to its fixtures byte for byte;
`tests/test_year_poster.py` and `tests/test_week_paper.py` check theirs structurally. A change to
a renderer or to `logbook/print_layout.py` that is meant runs this once and commits the new
fixtures with it:

    uv run python scripts/make_print_fixtures.py

The record is generated in a temporary folder and thrown away; the documents reference no file of
it (the demo's photos are named, not stored), so the fixtures carry no path of this machine."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from logbook import demo, print_page, week_paper, year_poster

DAYS, SEED = 30, 7
YEAR = "2026"
TRIP = "trip:2026-06-15:2026-06-20"
WEEK = "2026-W25"  # the yacht week
FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "demo"


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lb = demo.generate(Path(tmp) / "Demo", DAYS, SEED)
        pages = {
            f"print_year_{YEAR}.html": print_page.html(print_page.read_year(lb, YEAR)),
            f"print_trip_{TRIP.split(':')[1]}.html": print_page.html(print_page.read_trip(lb, TRIP)),
            f"paper_week_{WEEK}.html": week_paper.html(week_paper.read(lb, WEEK)),
        }
        poster = year_poster.read(lb, YEAR)
        for sheet in sorted(year_poster.layout.POSTER_SHEETS):
            pages[f"poster_year_{YEAR}_{sheet}.html"] = year_poster.html(poster, sheet)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name, text in pages.items():
        (FIXTURES / name).write_bytes(text.encode("utf-8"))
        print(f"wrote {FIXTURES / name} ({len(text):,} characters)")


if __name__ == "__main__":
    main()
