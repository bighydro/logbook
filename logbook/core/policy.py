"""The record's policies: settings the owner keeps in `<root>/policy/`, never constants in the code.

`crossing.json` (ADR 0016) maps a destination to the highest tier that may cross to it. The owner's
circumstances change, so the ceiling is theirs to raise. `logbook init` and the first export write the
default; nothing else writes it. Read-only from here on. An entry may carry an `until` date (ADR 0022:
a ceiling lent to a cloud model or service for a while, `{"max_tier": 2, "until": "2026-12-31"}`); it
holds through that day and from the next counts as `max_tier` 0, so nothing crosses until the owner
writes a new date or removes the line. `doctor` names an expired entry.

`import.json` lists the sources the owner has switched off: `{"disabled": [{"source", "reason"}]}`.
`add`, `sync` and `import-backup` skip a disabled source and say so; `logbook sources` lists every
adapter with its state. An adapter existing is not a decision to run it: demo, sample and placeholder
data never enters the record. `logbook init` writes the default list (`DEFAULT_IMPORT`: the noisy
Takeout products off, everything else on), and so does the first command that reads the file in a
record made before it existed.

`circle.json` (RFC 0025) maps a member of the owner's circle, by the name the owner calls them, to the
public half of their sharing key: `{"ola": {"key": "<64 hex>"}}`. `logbook circle add NAME KEY` adds
one, once; `logbook receive` verifies a page's signature under the key held here and never under a key
the page brought. Nothing else writes it.

`owner.json` lists the owner's own aliases beyond what the record resolves: `{"names": [...], "emails":
[...], "phones": [...]}`. The with module (`present.owner_of`) joins them with `owner_id` and `owner_emails`
from `logbook.json` and every resolution line that names the owner, so the owner is never listed as their
own company. The file lives in the record, never in the repository; `logbook init` writes the empty one,
and so does the first reading of a record made before it existed."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any

POLICY_FILE = PurePosixPath("policy/crossing.json")  # record-relative, as the manifest names it
DEFAULT_DESTINATION = "hermes"
MCP_DESTINATION = "mcp"  # `logbook mcp`: an agent on this machine, reading through the ceiling
MCP_DEFAULT_TIER = 1  # the ceiling for a record whose file does not name the mcp destination
VAULT_DESTINATION = "vault"  # `logbook export vault`: a folder of Markdown on the owner's own disk
VAULT_DEFAULT_TIER = 1  # the ceiling for a record whose file does not name it
SITE_DESTINATION = "site"  # `logbook export site`: a folder of static HTML the owner may publish anywhere
SITE_DEFAULT_TIER = 1  # the ceiling for a record whose file does not name it
DEFAULT_POLICY: dict[str, Any] = {
    DEFAULT_DESTINATION: {"max_tier": 2},
    MCP_DESTINATION: {"max_tier": MCP_DEFAULT_TIER},
}
TIERS = (1, 2, 3)
UNTIL = "until"  # the last day an entry holds, `YYYY-MM-DD`; absent: for good
EXPIRED_TIER = 0  # what an entry past its `until` day counts as: nothing crosses
KEY = re.compile(r"[0-9a-fA-F]{64}")  # an Ed25519 public key as the circle file spells it
IMPORT_FILE = PurePosixPath("policy/import.json")
# Switched off until the owner says otherwise: the two Takeout products that record every sign-in
# and every search or app opened, which few owners want in the record unasked. `logbook init`
# writes them, and so does the first read of a record without the file; the owner removes an entry
# to opt in.
DEFAULT_IMPORT: dict[str, Any] = {
    "disabled": [
        {"source": "google-takeout-access-log", "reason": "every sign-in to every Google service; opt in"},
        {"source": "google-takeout-activity", "reason": "every search and app opened; opt in"},
    ]
}
CIRCLE_FILE = PurePosixPath("policy/circle.json")  # name → the sharing key a received page must verify under
OWNER_FILE = PurePosixPath("policy/owner.json")
OWNER_KEYS = ("names", "emails", "phones")
DEFAULT_OWNER: dict[str, list[str]] = {key: [] for key in OWNER_KEYS}


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


def today() -> date:
    """The calendar day an `until` date is held against: the machine's local date, as the owner
    who wrote the date meant it. Tests replace it."""
    return datetime.now().date()


@dataclass(frozen=True)
class Ceiling:
    """One entry of the policy as it counts today: `max_tier` is 0 when the entry has expired,
    `written` what the file says either way."""

    destination: str
    written: int
    until: date | None
    expired: bool

    @property
    def max_tier(self) -> int:
        return EXPIRED_TIER if self.expired else self.written


def _until(path: Path, destination: str, entry: dict[str, Any]) -> date | None:
    found = entry.get(UNTIL)
    if found is None:
        return None
    try:
        if not isinstance(found, str):
            raise ValueError
        return date.fromisoformat(found)
    except ValueError:
        raise PolicyError(
            f"{path}: {destination!r} has an until that is not a date; "
            "write it as YYYY-MM-DD, the last day the entry holds"
        ) from None


def _entry(path: Path, destination: str, entry: Any, on: date) -> Ceiling:
    """`entry` as a Ceiling held against the day `on`; the shape is the caller's to have checked."""
    until = _until(path, destination, entry)
    return Ceiling(destination, int(entry["max_tier"]), until, until is not None and on > until)


def ceilings(root: Path) -> list[Ceiling]:
    """Every destination the policy names, in the file's order, each held against today: what the
    file says, its `until` day and whether it has expired. An entry that is not the documented shape
    is refused naming the file, as `ceiling` would refuse it."""
    path = policy_path(root)
    on = today()
    out: list[Ceiling] = []
    for destination, entry in read(root).items():
        if not isinstance(entry, dict) or entry.get("max_tier") not in TIERS:
            raise PolicyError(
                f'{path}: {destination!r} must be {{"max_tier": 1, 2 or 3}}, with an optional "until" date'
            )
        out.append(_entry(path, destination, entry, on))
    return out


def ceiling(root: Path, destination: str) -> int:
    """The highest tier the policy lets cross to `destination`; a destination the file does not
    name is refused, naming the file, so a crossing never goes to an unnamed reader. An entry past
    its `until` day is 0: nothing crosses (ADR 0022)."""
    path = policy_path(root)
    entry = read(root).get(destination)
    if not isinstance(entry, dict) or entry.get("max_tier") not in TIERS:
        raise PolicyError(
            f"{path} names no destination {destination!r} with a max_tier of 1, 2 or 3; "
            f'add {{"{destination}": {{"max_tier": 1}}}} to it to allow a crossing'
        )
    return _entry(path, destination, entry, today()).max_tier


def expired_on(root: Path, destination: str) -> date | None:
    """The `until` day of `destination`'s entry when that day has passed, else None: for a refusal
    that says why the ceiling is 0. A destination the file does not name is None too."""
    entry = read(root).get(destination)
    if not isinstance(entry, dict) or entry.get("max_tier") not in TIERS:
        return None
    found = _entry(policy_path(root), destination, entry, today())
    return found.until if found.expired else None


def expiry_note(root: Path, destination: str) -> str:
    """`; its entry expired on <day> and counts as max_tier 0` when it has, else the empty string."""
    day = expired_on(root, destination)
    return f"; its entry expired on {day.isoformat()} and counts as max_tier 0" if day is not None else ""


def recipient(root: Path, destination: str) -> str | None:
    """The age recipient the policy names for `destination` (RFC 0029 §7), or None: a crossing
    package to it is then shipped opened, and only when the owner types `--open`."""
    entry = read(root).get(destination)
    found = entry.get("recipient") if isinstance(entry, dict) else None
    if found is None:
        return None
    if not isinstance(found, str) or not found.startswith("age1"):
        raise PolicyError(f"{policy_path(root)}: {destination!r} has a recipient that is not an age1… string")
    return found


def mcp_ceiling(root: Path) -> int:
    """The highest tier `logbook mcp` may hand to its client: the `mcp` entry of the policy, or
    tier 1 when the file does not name it — a destination with a default, since the client is an
    agent on the owner's own machine and tier 1 is what crosses on its own (ADR 0016). An entry
    that is there but not a tier of 1, 2 or 3 is refused naming the file, never read as a default."""
    return _ceiling_or_default(root, MCP_DESTINATION, MCP_DEFAULT_TIER)


def vault_ceiling(root: Path) -> int:
    """The highest tier `logbook export vault` may render: the `vault` entry of the policy, or tier 1
    when the file does not name it — the vault is a folder on the owner's own disk, like the `mcp`
    client, and tier 1 is what crosses on its own (ADR 0016). `--tier 1,2` needs the entry."""
    return _ceiling_or_default(root, VAULT_DESTINATION, VAULT_DEFAULT_TIER)


def site_ceiling(root: Path) -> int:
    """The highest tier `logbook export site` may render: the `site` entry of the policy, or tier 1
    when the file does not name it, as the vault. A site is pages the owner may publish anywhere, so
    tier 1 is what crosses on its own (ADR 0016) and `--tier 1,2` needs the entry; tier 3 never."""
    return _ceiling_or_default(root, SITE_DESTINATION, SITE_DEFAULT_TIER)


def _ceiling_or_default(root: Path, destination: str, default: int) -> int:
    path = policy_path(root)
    entry = read(root).get(destination)
    if entry is None:
        return default
    if not isinstance(entry, dict) or entry.get("max_tier") not in TIERS:
        raise PolicyError(
            f'{path} names {destination!r} without a max_tier of 1, 2 or 3; make it {{"max_tier": {default}}}'
        )
    return _entry(path, destination, entry, today()).max_tier


def import_path(root: Path) -> Path:
    return Path(root).joinpath(*IMPORT_FILE.parts)


def write_default_import(root: Path) -> Path:
    """Write the empty import policy where none exists; never overwrite one. Returns the path."""
    path = import_path(root)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(DEFAULT_IMPORT, indent=2) + "\n", encoding="utf-8")
    return path


def disabled(root: Path) -> dict[str, str]:
    """The disabled sources as `{source: reason}`, as the file spells them (aliases are the
    caller's). A record without the file gets the empty one, so the owner finds it; a file that is
    not the documented shape raises PolicyError naming it, and the caller writes nothing."""
    write_default_import(root)
    return read_disabled(root)


def read_disabled(root: Path) -> dict[str, str]:
    """The disabled sources as `disabled` gives them, without writing the default: a record without
    the file reads as the default (`DEFAULT_IMPORT`), for a reader that writes nothing."""
    path = import_path(root)
    shape = f'{path} must be {{"disabled": [{{"source": "<adapter>", "reason": "<why>"}}, ...]}}'
    if not path.exists():
        data: Any = json.loads(json.dumps(DEFAULT_IMPORT))
    else:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as e:
            raise PolicyError(f"{path} is not JSON: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("disabled"), list):
        raise PolicyError(shape)
    out: dict[str, str] = {}
    for entry in data["disabled"]:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("source"), str)
            or not isinstance(entry.get("reason"), str)
        ):
            raise PolicyError(shape)
        out[entry["source"]] = entry["reason"]
    return out


def owner_path(root: Path) -> Path:
    return Path(root).joinpath(*OWNER_FILE.parts)


def write_default_owner(root: Path) -> Path:
    """Write the empty owner aliases where none exist; never overwrite them. Returns the path."""
    path = owner_path(root)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(DEFAULT_OWNER, indent=2) + "\n", encoding="utf-8")
    return path


def owner_aliases(root: Path) -> dict[str, list[str]]:
    """The owner's extra aliases as `{"names": [...], "emails": [...], "phones": [...]}`, every key
    present (an absent one is empty). A record without the file gets the empty one; a file that is
    not the documented shape raises PolicyError naming it."""
    path = write_default_owner(root)
    shape = f'{path} must be {{"names": [...], "emails": [...], "phones": [...]}}, each a list of strings'
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise PolicyError(f"{path} is not JSON: {e}") from e
    if not isinstance(data, dict):
        raise PolicyError(shape)
    out: dict[str, list[str]] = {}
    for key in OWNER_KEYS:
        values = data.get(key, [])
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise PolicyError(shape)
        out[key] = [v.strip() for v in values if v.strip()]
    return out


def circle_path(root: Path) -> Path:
    return Path(root).joinpath(*CIRCLE_FILE.parts)


def circle(root: Path) -> dict[str, str]:
    """The circle as `{name: key}`, keys lowercase hex; empty when the file is not there. A file
    that is not the documented shape raises PolicyError naming it."""
    path = circle_path(root)
    if not path.exists():
        return {}
    shape = f'{path} must be {{"<name>": {{"key": "<64 hex characters>"}}, ...}}'
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise PolicyError(f"{path} is not JSON: {e}") from e
    if not isinstance(data, dict):
        raise PolicyError(shape)
    out: dict[str, str] = {}
    for name, entry in data.items():
        key = entry.get("key") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not isinstance(key, str) or not KEY.fullmatch(key):
            raise PolicyError(shape)
        out[name] = key.lower()
    return out


def circle_add(root: Path, name: str, key: str) -> bool:
    """Add `name` with `key` to the circle; False when the same pair is there already. A name that
    is there under another key is refused naming the file: a key is never swapped by mistake."""
    path = circle_path(root)
    known = circle(root)
    key = key.lower()
    if known.get(name) == key:
        return False
    if name in known:
        raise PolicyError(f"{path} already names {name!r} with another key; edit the file to change it")
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data[name] = {"key": key}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True
