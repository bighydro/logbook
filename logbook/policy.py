"""The crossing policy (ADR 0016): `<root>/policy/crossing.json` maps a destination to the highest
tier that may cross to it. A setting in the record, not a constant: the owner's circumstances
change, so the ceiling is theirs to raise. `logbook init` and the first export write the default;
nothing else writes it. Read-only from here on."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

POLICY_FILE = PurePosixPath("policy/crossing.json")  # record-relative, as the manifest names it
DEFAULT_DESTINATION = "hermes"
DEFAULT_POLICY: dict[str, Any] = {DEFAULT_DESTINATION: {"max_tier": 2}}
TIERS = (1, 2, 3)


class PolicyError(ValueError):
    """The policy file refuses the request, or is not a policy; the message names the file."""


def policy_path(root: Path) -> Path:
    return Path(root).joinpath(*POLICY_FILE.parts)


def write_default(root: Path) -> Path:
    """Write the default policy where none exists; never overwrite one. Returns the path."""
    path = policy_path(root)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(DEFAULT_POLICY, indent=2) + "\n", encoding="utf-8")
    return path


def read(root: Path) -> dict[str, Any]:
    """The policy as written, or the default when the file does not exist yet."""
    path = policy_path(root)
    if not path.exists():
        default: dict[str, Any] = json.loads(json.dumps(DEFAULT_POLICY))
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise PolicyError(f"{path} is not JSON: {e}") from e
    if not isinstance(data, dict):
        raise PolicyError(f'{path} must map destination to {{"max_tier": N}}')
    return data


def ceiling(root: Path, destination: str) -> int:
    """The highest tier the policy lets cross to `destination`; a destination the file does not
    name is refused, naming the file, so a crossing never goes to an unnamed reader."""
    path = policy_path(root)
    entry = read(root).get(destination)
    if not isinstance(entry, dict) or entry.get("max_tier") not in TIERS:
        raise PolicyError(
            f"{path} names no destination {destination!r} with a max_tier of 1, 2 or 3; "
            f'add {{"{destination}": {{"max_tier": 1}}}} to it to allow a crossing'
        )
    return int(entry["max_tier"])
