"""Tiers (SPEC §4: every line carries a tier of 1, 2 or 3; each payload profile names the tier its
producers write by default, MUST for some; ADR 0016 and RFC 0005: a crossing carries the lines of a
window whose tier is in the set asked for, under the destination's ceiling). Stated for any record and
any tier t: the export at t is exactly the lines of tier ≤ t; an export at tier 1 carries no payload of
a profile whose default tier is 2 or 3, the list read from SPEC.md; and exporting then importing the
subset gives a record whose head is a function of the subset alone, which a second import leaves."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from logbook.core import crossing, policy
from logbook.core.chain import CONTENT_FIELDS, Line, content_hash
from logbook.core.store import Logbook
from properties.common import CI, drafts, instants, profile_tiers, stamp, text

TZ = "Europe/Oslo"
DESTINATION = "ola"  # a member of the owner's circle, allowed every tier for these tests
SINCE, UNTIL = "2026-03-01T00:00:00Z", "2026-05-01T00:00:00Z"
PROFILES = profile_tiers()
TIER_SETS = {1: (1,), 2: (1, 2), 3: (1, 2, 3)}


def record(root: Path, lines: list[dict[str, Any]]) -> Logbook:
    lb = Logbook.init(root, TZ)
    policy.policy_path(lb.root).write_text(json.dumps({DESTINATION: {"max_tier": 3}}), encoding="utf-8")
    lb.append_many(lines)
    return lb


def exported(lb: Logbook, t: int) -> list[Line]:
    """The lines a crossing to the destination at tier t selects (RFC 0005), the whole window."""
    req = crossing.request(
        lb, DESTINATION, SINCE, UNTIL, TIER_SETS[t], signed_only=False
    )  # tiers, not the gate
    return crossing.select(lb, req).lines


def conformant() -> st.SearchStrategy[list[dict[str, Any]]]:
    """Drafts as conformant producers write them (§4): a profile's default tier, or a higher one
    where the default is a SHOULD — never lower, and never another for a MUST."""

    def one(schema: str) -> st.SearchStrategy[dict[str, Any]]:
        default, must = PROFILES[schema]
        tiers = (default,) if must else tuple(range(default, 4))
        return st.fixed_dictionaries(
            {
                "at": instants(datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 5, 1, tzinfo=UTC)).map(stamp),
                "source": st.just("manual"),
                "kind": st.just(schema.split("/")[0]),
                "tier": st.sampled_from(tiers),
                "payload": st.fixed_dictionaries({"schema": st.just(schema), "text": text}),
            }
        )

    return st.lists(st.sampled_from(sorted(PROFILES)).flatmap(one), max_size=10)


def test_the_tier_table_is_read_from_the_spec() -> None:
    """§4 names a default tier for every profile; the list is read from SPEC.md, never written twice."""
    assert {t for t, _must in PROFILES.values()} == {1, 2, 3}
    assert PROFILES["message/v1"] == (2, True) and PROFILES["transaction/v1"] == (3, True)
    assert PROFILES["health-sample/v1"] == (3, False) and PROFILES["crossing/v1"] == (1, True)


@settings(CI, max_examples=30)
@given(drafts(raw_id=True), st.sampled_from((1, 2, 3)))
def test_the_lines_exported_at_a_tier_are_exactly_those_at_or_below_it(
    tmp_path_factory: pytest.TempPathFactory, lines: list[dict[str, Any]], t: int
) -> None:
    """ADR 0016, RFC 0005: a crossing at tier t carries every line of the window whose tier is in
    1..t, verbatim and in chain order, and no other."""
    lb = record(tmp_path_factory.mktemp("lb"), lines)
    expected = [line for line in lb.lines() if line["tier"] <= t]
    assert exported(lb, t) == expected
    assert all(line["tier"] <= t for line in exported(lb, t))


@settings(CI, max_examples=30)
@given(conformant())
def test_an_export_at_tier_1_carries_no_profile_of_tier_2_or_3(
    tmp_path_factory: pytest.TempPathFactory, lines: list[dict[str, Any]]
) -> None:
    """§4: a crossing at tier 1 carries no payload whose profile defaults to tier 2 or 3 — no note,
    message, mail, transcript, task, health sample or transaction — when the lines were written as §4
    says; a profile of default tier 1 written higher stays home too."""
    lb = record(tmp_path_factory.mktemp("lb"), lines)
    private = {schema for schema, (default, _must) in PROFILES.items() if default >= 2}
    assert private & {"note/v1", "message/v1", "transaction/v1"} == {
        "note/v1",
        "message/v1",
        "transaction/v1",
    }
    schemas = {line["payload"]["schema"] for line in exported(lb, 1)}
    assert schemas & private == set()
    assert schemas <= {schema for schema, (default, _must) in PROFILES.items() if default == 1}


@settings(CI, max_examples=25)
@given(drafts(raw_id=True), st.sampled_from((1, 2, 3)))
def test_exporting_then_importing_at_the_same_tier_is_idempotent_on_the_head(
    tmp_path_factory: pytest.TempPathFactory, lines: list[dict[str, Any]], t: int
) -> None:
    """§3 and RFC 0005: the exported subset, appended to a fresh record with its ids and `recorded_at`
    kept, chains to a head that is a function of the subset alone — a second fresh record reaches the
    same head; importing the subset again appends nothing (dedupe on raw_id) and leaves the head; and
    the new record exports, at the same tier, lines of the same content in the same order."""
    lb = record(tmp_path_factory.mktemp("lb"), lines)
    subset = exported(lb, t)
    as_drafts = [
        {k: v for k, v in line.items() if k in (*CONTENT_FIELDS, "id", "recorded_at")} for line in subset
    ]
    heads = []
    for _ in range(2):
        fresh = record(tmp_path_factory.mktemp("fresh"), [])
        assert fresh.append_many(as_drafts) == len(subset)
        head = fresh.meta["head"]
        again_written = fresh.append_many(as_drafts)
        assert (again_written, fresh.meta["head"]) == (0, head), "a second import changes nothing"
        again = exported(fresh, t)
        assert [content_hash(line) for line in again] == [content_hash(line) for line in subset]
        assert [line["id"] for line in again] == [line["id"] for line in subset]
        assert fresh.verify()[2] == []
        heads.append(head)
    assert heads[0] == heads[1], "the head of the imported subset is the subset's"
