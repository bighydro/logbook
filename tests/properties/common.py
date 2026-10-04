"""What the property modules share: the Hypothesis settings they inherit, the strategies for a line
and the synthetic persona's identifiers, and the SPEC §4 table read from SPEC.md itself.

Every string a strategy draws is synthetic: phone numbers are in the UK reserved range 07700 900xxx
and the +47 9000 000x range the RFC examples use, addresses are at example.org, and the persona
(Ines, Kari and Ola Nordmann of Oslo) does not exist."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hypothesis import settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "SPEC.md"

# Deterministic, no deadline, replayable: `tests/properties/conftest.py` registers the same as a profile.
CI = settings(derandomize=True, deadline=None, print_blob=True)

# -- lines ------------------------------------------------------------------------------------------------

SOURCES = ("manual", "dawarich", "ios-calendar", "whatsapp")
KINDS = ("note", "event", "location", "message")
SCHEMAS = ("note/v1", "event/v1", "location/v1", "message/v1")
EPOCH = datetime(2026, 3, 1, tzinfo=UTC)


def stamp(instant: datetime) -> str:
    """An aware instant as SPEC §2 writes it: RFC 3339 UTC to the second with a literal Z."""
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def instants(start: datetime, end: datetime) -> st.SearchStrategy[datetime]:
    """Aware UTC instants, to the second, in [start, end)."""
    return st.integers(0, int((end - start).total_seconds()) - 1).map(
        lambda s: datetime.fromtimestamp(start.timestamp() + s, UTC)
    )


# Text as a payload carries it: any Unicode but the surrogates, which UTF-8 cannot encode (RFC 8785 §3.2.2.2).
text = st.text(max_size=40)
tier = st.sampled_from((1, 2, 3))


def payloads(raw_id: bool = False) -> st.SearchStrategy[dict[str, Any]]:
    """A payload with its `schema`, a text, a number, and a `raw_id` when the caller dedupes on it."""
    fields: dict[str, st.SearchStrategy[Any]] = {
        "schema": st.sampled_from(SCHEMAS),
        "text": text,
        "n": st.integers(-1000, 1000) | st.floats(allow_nan=False, allow_infinity=False, width=32),
    }
    if raw_id:
        fields["raw_id"] = st.uuids(version=4).map(str)
    return st.fixed_dictionaries(fields)


def drafts(
    start: datetime = EPOCH,
    end: datetime = datetime(2026, 5, 1, tzinfo=UTC),
    raw_id: bool = False,
    min_size: int = 0,
    max_size: int = 10,
) -> st.SearchStrategy[list[dict[str, Any]]]:
    """Drafts for `Logbook.append_many`, with `at` in [start, end) and, when `raw_id`, a distinct
    raw_id per draft. `end` is a span after `at`, or None (SPEC §2: never absent)."""
    one = st.fixed_dictionaries(
        {
            "at": instants(start, end).map(stamp),
            "end": st.none(),
            "tz": st.sampled_from(("Europe/Oslo", "UTC", "Pacific/Chatham")),
            "source": st.sampled_from(SOURCES),
            "kind": st.sampled_from(KINDS),
            "tier": tier,
            "payload": payloads(raw_id),
        }
    )
    return st.lists(one, min_size=min_size, max_size=max_size)


# -- SPEC §4, read from the spec --------------------------------------------------------------------------

PROFILE = re.compile(r"`([a-z0-9-]+/v\d+)`([^`]*)")


def profile_tiers() -> dict[str, tuple[int, bool]]:
    """`{schema: (default tier, MUST)}` from the table of SPEC §4 — the second table of the section,
    one row per default tier, the profiles in backticks, a MUST in the parenthesis after a profile
    whose default is its only tier. Read from SPEC.md so the list is never written twice."""
    section = SPEC.read_text(encoding="utf-8").split("\n## 4. Tiers", 1)[1].split("\n## 5.", 1)[0]
    found: dict[str, tuple[int, bool]] = {}
    for row in section.splitlines():
        m = re.match(r"\|\s*([123])\s*\|(.*)\|\s*$", row)
        if m is None or "/v" not in row:
            continue
        default = int(m.group(1))
        for schema, tail in PROFILE.findall(m.group(2)):
            found[schema] = (default, "MUST" in tail.split(")")[0] if "(" in tail else False)
    assert found.get("location/v1") == (1, False) and found.get("note/v1") == (2, True), found
    return found
