"""`logbook repair`: the lines that put a known mistake right, appended; nothing is ever rewritten.

A repair is a migration of what an earlier version wrote: for every line it finds wrong it appends
the corrected line — the same observation with the right value, `payload.supersedes` the old line's
`id` (SPEC §3, RFC 0003 rule 2) and `raw_id` suffixed so the dedupe key of `append_many` does not take
it for the old one — and then a retraction of the old line (`retraction/v1`, source `logbook`). The old
line stays in the chain, hidden; readers see the corrected one. Each repair is idempotent: a second
run finds nothing standing to repair, and a run interrupted midway is finished by the next.

`health_units`: `apple-health` wrote `resting_hr` 60 times and `hrv` 1,000 times too large before the
store's own units were checked (RFC 0014, "Units as the store keeps them").
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .chain import Line
from .store import RETRACTION, Logbook, now_utc

HEALTH_SOURCE = "apple-health"
HEALTH_FACTORS = {"resting_hr": 60, "hrv": 1000}  # type → how many times too large the value was
HEALTH_SUFFIX = ":u2"  # the corrected line's raw_id: `<old raw_id>:u2`
REPAIR_SOURCE = "logbook"  # the retraction's source: the tool decided it, not the owner (RFC 0003)


@dataclass(frozen=True)
class Report:
    found: dict[str, int]  # type → wrong lines standing when the run began
    written: int  # lines appended (corrected lines and retractions); 0 on a dry run
    dry_run: bool

    @property
    def total(self) -> int:
        return sum(self.found.values())


def health_units(lb: Logbook, dry_run: bool = False, at: str | None = None) -> Report:
    """Retract every standing `apple-health` `resting_hr` and `hrv` line whose value the adapter
    rescaled, and re-emit each corrected. `at` is the retractions' instant (now by default)."""
    wrong = _wrong_health_lines(lb)
    found = dict(Counter(str(line["payload"]["type"]) for line in wrong))
    if dry_run or not wrong:
        return Report(found, 0, dry_run)
    written = lb.append_many(_health_drafts(wrong, at or now_utc()))
    return Report(found, written, False)


def _wrong_health_lines(lb: Logbook) -> list[Line]:
    """The lines to repair, in file order: `apple-health`, a type in HEALTH_FACTORS, a numeric value,
    not a corrected line already (the suffix, or `supersedes`), not retracted already."""
    with lb.index() as idx:
        hidden = {(r.get("payload") or {}).get("supersedes") for r in idx.retractions()}
        wrong: list[Line] = []
        for line in idx.of_kind("health"):
            payload = line.get("payload") or {}
            if line.get("source") != HEALTH_SOURCE or payload.get("type") not in HEALTH_FACTORS:
                continue
            if str(payload.get("raw_id", "")).endswith(HEALTH_SUFFIX) or "supersedes" in payload:
                continue
            if line.get("id") in hidden:
                continue
            value = payload.get("value")
            if isinstance(value, bool) or not isinstance(value, int | float):
                continue
            wrong.append(line)
    return wrong


def _health_drafts(wrong: Sequence[Line], at: str) -> Iterator[dict[str, Any]]:
    """Per wrong line, the corrected line first, then the retraction: an interrupted run that wrote
    the correction is finished by the next (the correction is deduped, the retraction written)."""
    for line in wrong:
        payload = deepcopy(line["payload"])
        kind = str(payload["type"])
        factor = HEALTH_FACTORS[kind]
        payload["raw_id"] = f"{payload['raw_id']}{HEALTH_SUFFIX}"
        payload["value"] = _round(float(payload["value"]) / factor)
        payload["supersedes"] = line["id"]
        yield {
            "at": line["at"],
            "end": line.get("end"),
            "tz": line.get("tz"),
            "source": line["source"],
            "kind": line["kind"],
            "tier": line["tier"],
            "payload": payload,
        }
        yield {
            "at": at,
            "source": REPAIR_SOURCE,
            "kind": RETRACTION,
            "tier": 2,
            "payload": {
                "schema": "retraction/v1",
                "supersedes": line["id"],
                "seq": line["seq"],
                "reason": f"apple-health wrote this {kind} {factor:,} times too large (the store's unit was"
                f" taken for another); the corrected line is {payload['raw_id']} (RFC 0014)",
            },
        }


def _round(value: float) -> int | float:
    """Whole numbers as ints, else three decimals, as the adapter writes them."""
    rounded = round(value, 3)
    return int(rounded) if rounded == int(rounded) else rounded


def describe_health_units(report: Report) -> str:
    """One line for the terminal: counts only, never a value."""
    if not report.total:
        return (
            "nothing to repair: no apple-health resting_hr or hrv line written in the wrong unit is standing"
        )
    kinds = " and ".join(f"{n} {kind}" for kind, n in sorted(report.found.items()))
    if report.dry_run:
        return (
            f"dry run: {kinds} apple-health lines to retract and re-emit corrected"
            f" ({report.total * 2} lines would be appended); nothing written"
        )
    return f"retracted and re-emitted {kinds} apple-health lines corrected: {report.written} lines appended"
