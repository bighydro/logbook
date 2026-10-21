"""The entry a test's record needs in `policy/crossing.json`, written as the owner writes one: a new
record names no destination above tier 1 (ADR 0016, amended 21 Oct 2026), so a test that crosses to
`hermes` adds the entry itself. The other entries in the file are kept."""

from __future__ import annotations

import json
from pathlib import Path

from logbook.core import policy


def allow(root: Path, destination: str = "hermes", max_tier: int = 2) -> Path:
    """Add `{destination: {"max_tier": max_tier}}` to the record's policy file; returns its path."""
    path = policy.policy_path(root)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data[destination] = {"max_tier": max_tier}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path
