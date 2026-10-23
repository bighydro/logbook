"""The scale harness: the Library timed on a synthetic record the size of a life (phase 3 of the
Library's rebuild, RFC 0047 §8).

    uv run python tests/perf/run.py                        # 2,000,000 lines, 2,000 people, ten years
    uv run python tests/perf/run.py --lines 200000         # a tenth, for a quicker look
    uv run python tests/perf/run.py --routes /people /day/ # some routes only
    uv run python tests/perf/run.py --fresh                # build the record again

It builds `scripts/bench_library.py`'s synthetic ten years with the shape a life has at scale: about
2,000 people (600 with a number in the reserved range 07700 900xxx, the rest reached at example.org),
every fourth flight without its arrival (#344), a chapter, goals with their reviews, 120 days
reflected on and 30 signed. The record is kept in `tests/perf/.record/` (git-ignored, never
committed) and reused while it holds what was asked. Then every route of the Library is timed in a
child process of its own, cold (the first request after the server starts), warm (the second) and
after one line is appended (a sync moved the head); and then every route at once, cold, one thread
each, as a browser opening the whole menu does. It prints the table, and `--out` writes it as JSON.

Everything generated is synthetic: the Oslo persona (Ines Nordmann and the Nordmann family, who do
not exist), addresses at example.org, numbers in 07700 900xxx. Nothing here reads a real record, and
nothing here is ever committed."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE / ".record"
SCRIPT = HERE.parents[1] / "scripts" / "bench_library.py"
LINES = 2_000_000
PEOPLE = 2_000
OPEN_FLIGHTS = 4  # every fourth flight without its arrival
REFLECTIONS = 120  # days of the last year reflected on
TIMEOUT_S = 3600


def bench() -> Any:
    """`scripts/bench_library.py`, loaded as a module: the generator and the timing are its."""
    spec = importlib.util.spec_from_file_location("bench_library", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["bench_library"] = module
    spec.loader.exec_module(module)
    return module


def record(b: Any, root: Path, lines: int, people: int, fresh: bool) -> dict[str, Any]:
    """The record at `root`, built when it is not there or holds something else; what it holds."""
    shape = {
        "asked": lines,
        "seed": b.SEED,
        "people": people,
        "open_flights": OPEN_FLIGHTS,
        "reflections": REFLECTIONS,
    }
    built_file = root / "built.json"
    built = json.loads(built_file.read_text(encoding="utf-8")) if built_file.exists() else None
    if fresh or built is None or any(built.get(k) != v for k, v in shape.items()):
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True)
        say(f"building {lines:,} lines, {people:,} people in {root} …")
        built = {**shape, **b.build(root, lines, b.SEED, people, OPEN_FLIGHTS, REFLECTIONS)}
        built_file.write_bytes((json.dumps(built, indent=2) + "\n").encode("utf-8"))
        say(f"built in {built['build_s']} s")
    return built


def table(results: list[dict[str, Any]], at_once: dict[str, Any]) -> str:
    """The routes as a Markdown table, the slowest cold first, and the menu opened at once."""
    rows = [
        "| route | status | cold s | warm s | after append s | at once s | peak MB |",
        "|---|--:|--:|--:|--:|--:|--:|",
    ]
    each = at_once.get("routes", {})
    for r in sorted(results, key=lambda r: ("error" in r, -float(r.get("cold_s", 0)))):
        together = each.get(r["route"], {}).get("s")
        shown = "" if together is None else f"{together:.3f}"
        if "error" in r:
            rows.append(f"| `{r['route']}` | {r['error']} | | | | {shown} | |")
            continue
        peak = "n/a" if r["peak_mb"] is None else f"{r['peak_mb']:.0f}"
        rows.append(
            f"| `{r['route']}` | {r['status']} | {r['cold_s']:.3f} | {r['warm_s']:.3f}"
            f" | {r['after_append_s']:.3f} | {shown} | {peak} |"
        )
    if "error" in at_once:
        rows.append(f"| every route at once | {at_once['error']} | | | | | |")
    else:
        slowest = max((float(r.get("cold_s", 0)) for r in results if "error" not in r), default=0.0)
        rows.append(
            f"| **every route at once** ({len(each)}) | | {slowest:.3f} (slowest alone) | | |"
            f" {at_once['all_s']:.3f} | {at_once['peak_mb'] or 'n/a'} |"
        )
    return "\n".join(rows)


def say(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def parse(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--lines", type=int, default=LINES, help=f"lines in the record (default {LINES:,})")
    p.add_argument("--people", type=int, default=PEOPLE, help=f"resolved people (default {PEOPLE:,})")
    p.add_argument(
        "--root", type=Path, default=ROOT, help="where the record is kept (default tests/perf/.record)"
    )
    p.add_argument("--routes", nargs="*", help="these routes only, as the bench writes them (/people, /day/)")
    p.add_argument("--fresh", action="store_true", help="build the record again")
    p.add_argument("--timeout", type=int, default=TIMEOUT_S, help="seconds one route may take")
    p.add_argument("--out", type=Path, help="write the results as JSON here")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = parse(argv)
    b = bench()
    built = record(b, args.root, args.lines, args.people, args.fresh)
    say(f"  the index opened in {b.open_index(args.root)} s")
    fill, results = b.time_routes(args.root, built, args.routes, [], args.timeout)
    routes = [r["route"] for r in results if "error" not in r]
    say(f"  every route at once ({len(routes)}) …")
    at_once = b.run_together(args.root, routes, args.timeout)
    out = {
        "record": built,
        "machine": b.machine(),
        "day": fill["day"],
        "routes": results,
        "at_once": at_once,
        "when": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if args.out is not None:
        args.out.write_bytes((json.dumps(out, indent=2) + "\n").encode("utf-8"))
    print(table(results, at_once))
    return out


if __name__ == "__main__":
    main()
