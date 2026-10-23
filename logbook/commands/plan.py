"""The plan: `show plan [DAY] [--json] [--coverage]` (RFC 0043 §9, slice E; `logbook.contrib.plan`)."""

from __future__ import annotations

import argparse
import json
import sys

from ..contrib import gaps
from ..contrib import plan as plan_reader
from ..core import day_start
from ..core.export import parse_day
from ..core.store import Logbook


def cmd_plan(a: argparse.Namespace) -> None:
    """`show plan [DAY] [--json]`: today's tasks, the current sprint and the next trip, from the
    tier-1 lines `sync notion` wrote and no other, each row with its Notion link and never its body;
    `--coverage` how many rows of each mapped database the record knows and when its first line is.
    Read only: nothing is written, to the record or to Notion, and nothing is fetched. Without the
    owner's `plan` entry in `policy/notion.json`, one sentence."""
    lb = Logbook.find()
    try:
        if getattr(a, "coverage", False):
            if a.name is not None:
                print("show plan --coverage: takes no day", file=sys.stderr)
                sys.exit(2)
            found = plan_reader.coverage(lb)
            if a.json:
                print(
                    json.dumps({"mapped": found is not None, "coverage": found}, indent=2, ensure_ascii=False)
                )
                return
            for text in plan_reader.coverage_rows(found):
                print(text)
            return
        days = day_start.of(lb.meta)
        day = days.today(gaps.now()).isoformat() if a.name in (None, "today") else a.name
        try:
            parse_day(day)
        except ValueError:
            print(f"show plan: the day is YYYY-MM-DD or today, not {day!r}", file=sys.stderr)
            sys.exit(2)
        found_plan = plan_reader.read(lb, day)
    except (plan_reader.PlanError, day_start.DayStartError) as e:
        print(f"show plan: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(found_plan.to_json(), indent=2, ensure_ascii=False))
        return
    for text in plan_reader.rows(found_plan):
        print(text)
