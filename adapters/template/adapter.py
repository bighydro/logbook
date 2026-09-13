"""Template adapter. Copy this folder, rename SOURCE, implement run()."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

SOURCE = "example"  # lowercase, dashes only
TIER = 1  # the lowest tier this source's lines may carry


def run(input_path: Path, since: str | None = None) -> Iterator[dict]:
    """Yield observations. `since` is RFC3339 UTC or None (everything)."""
    for row in json.loads(Path(input_path).read_text(encoding="utf-8")):
        if since and row["when"] < since:
            continue
        yield {
            "at": row["when"],
            "end": None,
            "tz": None,  # tz None → the logbook's own timezone
            "source": SOURCE,
            "kind": "event",
            "tier": TIER,
            "payload": {"schema": "event/v1", "title": row["title"], "raw_id": row["id"]},
        }


if __name__ == "__main__":  # python adapter.py fixture/input.json > out.jsonl ; logbook add out.jsonl
    import sys

    for obs in run(Path(sys.argv[1])):
        print(json.dumps(obs, ensure_ascii=False, sort_keys=True))
