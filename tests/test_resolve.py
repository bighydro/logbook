"""`logbook.resolve.labels`: (ref.kind, ref.value) → label from the record's own resolution lines
(RFC 0006). Later seq wins, a retracted resolution counts for nothing, `supersedes` drops the
superseded line, and a resolution without a label resolves to no name."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook.resolve import labels, labels_from
from logbook.store import Logbook

PERSON_A = "019cadd3-6bc0-7dcd-9133-043f5aabf2a9"
PERSON_B = "019cadd3-6bc0-7dcd-9133-043f5aabf2aa"


def _resolution(
    kind: str, value: str, label: str | None, entity: str = PERSON_A, supersedes: str | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "resolution/v1",
        "ref": {"kind": kind, "value": value},
        "entity": {"type": "person", "id": entity, "registry": "logbook"},
    }
    if label is not None:
        payload["label"] = label
    if supersedes is not None:
        payload["supersedes"] = supersedes
    return {
        "at": "2026-03-02T09:14:00Z",
        "source": "manual",
        "kind": "resolution",
        "tier": 2,
        "payload": payload,
    }


def _alias(
    kind: str, value: str, target: tuple[str, str], label: str | None = None, supersedes: str | None = None
) -> dict[str, Any]:
    """An alias line (RFC 0006 `alias_of`): this ref and the target ref are the same identity."""
    payload: dict[str, Any] = {
        "schema": "resolution/v1",
        "ref": {"kind": kind, "value": value},
        "alias_of": {"kind": target[0], "value": target[1]},
    }
    if label is not None:
        payload["label"] = label
    if supersedes is not None:
        payload["supersedes"] = supersedes
    return {
        "at": "2026-03-02T09:14:00Z",
        "source": "whatsapp-contacts",
        "kind": "resolution",
        "tier": 2,
        "payload": payload,
    }


def _append(lb: Logbook, draft: dict[str, Any]) -> dict[str, Any]:
    return lb.append(**draft)


def test_labels_maps_every_ref_of_a_person_to_its_label(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    _append(lb, _resolution("email", "ola@example.org", "Ola Nordmann"))
    _append(lb, _resolution("phone", "+4790000001", "Ola Nordmann"))
    assert labels(lb) == {
        ("email", "ola@example.org"): "Ola Nordmann",
        ("phone", "+4790000001"): "Ola Nordmann",
    }


def test_labels_is_empty_for_a_record_without_resolutions(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    lb.append(
        at="2026-03-02T09:14:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "text": "x"},
    )
    assert labels(lb) == {}


def test_labels_later_seq_wins_for_the_same_ref(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    _append(lb, _resolution("email", "kari@example.org", "Kari Older", entity=PERSON_B))
    _append(lb, _resolution("email", "kari@example.org", "Kari Nordmann", entity=PERSON_B))
    assert labels(lb) == {("email", "kari@example.org"): "Kari Nordmann"}


def test_labels_ignores_a_retracted_resolution(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    line = _append(lb, _resolution("phone", "+4790000003", "Mistaken Match"))
    lb.retract(line["seq"], "wrong person")
    assert labels(lb) == {}


def test_labels_retracting_the_later_resolution_reinstates_the_earlier_one(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    _append(lb, _resolution("email", "kari@example.org", "Kari Older", entity=PERSON_B))
    later = _append(lb, _resolution("email", "kari@example.org", "Kari Wrong", entity=PERSON_B))
    lb.retract(later["seq"], "typo")
    assert labels(lb) == {("email", "kari@example.org"): "Kari Older"}


def test_labels_supersedes_drops_the_superseded_line(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    old = _append(lb, _resolution("phone", "+4790000002", "K. Nordmann", entity=PERSON_B))
    _append(lb, _resolution("phone", "+4790000002", "Kari Nordmann", entity=PERSON_B, supersedes=old["id"]))
    assert labels(lb) == {("phone", "+4790000002"): "Kari Nordmann"}


def test_labels_a_superseding_line_that_is_itself_retracted_supersedes_nothing(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    old = _append(lb, _resolution("phone", "+4790000002", "K. Nordmann", entity=PERSON_B))
    new = _append(
        lb, _resolution("phone", "+4790000002", "Kari Wrong", entity=PERSON_B, supersedes=old["id"])
    )
    lb.retract(new["seq"], "wrong")
    assert labels(lb) == {("phone", "+4790000002"): "K. Nordmann"}


def test_labels_a_later_resolution_without_a_label_resolves_to_no_name(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    _append(lb, _resolution("email", "ola@example.org", "Ola Nordmann"))
    _append(lb, _resolution("email", "ola@example.org", None, entity=PERSON_B))
    assert labels(lb) == {}


def test_labels_writes_nothing(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    _append(lb, _resolution("email", "ola@example.org", "Ola Nordmann"))
    before = lb.meta["head"]
    labels(lb)
    assert lb.meta["head"] == before


# -- aliases: a ref that is the same identity as another ref (RFC 0006 `alias_of`) ------------

LID = ("handle", "236000000000001@lid")
PHONE = ("phone", "+4790000001")


def test_labels_alias_takes_the_label_of_the_ref_it_points_at(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    _append(lb, _resolution(*PHONE, "Ola Nordmann"))
    _append(lb, _alias(*LID, PHONE))
    assert labels(lb) == {PHONE: "Ola Nordmann", LID: "Ola Nordmann"}


def test_labels_alias_resolves_in_either_append_order(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    _append(lb, _alias(*LID, PHONE))
    _append(lb, _resolution(*PHONE, "Ola Nordmann"))
    assert labels(lb) == {PHONE: "Ola Nordmann", LID: "Ola Nordmann"}


def test_labels_alias_of_an_unresolved_ref_falls_back_to_its_own_label(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    _append(lb, _alias(*LID, PHONE, label="Ola (WhatsApp)"))
    assert labels(lb) == {LID: "Ola (WhatsApp)"}


def test_labels_alias_of_an_unresolved_ref_without_a_label_resolves_to_nothing(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    _append(lb, _alias(*LID, PHONE))
    assert labels(lb) == {}


def test_labels_target_label_wins_over_the_alias_own_label(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    _append(lb, _resolution(*PHONE, "Ola Nordmann"))
    _append(lb, _alias(*LID, PHONE, label="Ola (WhatsApp)"))
    assert labels(lb)[LID] == "Ola Nordmann"


def test_labels_alias_follows_a_chain_of_aliases(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    _append(lb, _resolution(*PHONE, "Ola Nordmann"))
    _append(lb, _alias("handle", "b", ("handle", "c")))
    _append(lb, _alias("handle", "a", ("handle", "b")))
    _append(lb, _alias("handle", "c", PHONE))
    assert labels(lb)[("handle", "a")] == "Ola Nordmann"


def test_labels_alias_stops_after_four_hops(tmp_path: Path):
    """a → b → c → d → e is four hops and resolves; a → … → f is five and stops at e."""
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    _append(lb, _resolution("handle", "e", "Reached in four"))
    for src, dst in (("a", "b"), ("b", "c"), ("c", "d"), ("d", "e")):
        _append(lb, _alias("handle", src, ("handle", dst)))
    assert labels(lb)[("handle", "a")] == "Reached in four"
    _append(lb, _alias("handle", "e", ("handle", "f"), label="Five is too far"))
    _append(lb, _resolution("handle", "f", "Never reached from a"))
    found = labels(lb)
    assert found[("handle", "a")] == "Five is too far"  # the line the walk stopped on decides
    assert found[("handle", "b")] == "Never reached from a"  # four hops from b


def test_labels_alias_cycle_terminates_and_resolves_to_nothing(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    _append(lb, _alias("handle", "a", ("handle", "b")))
    _append(lb, _alias("handle", "b", ("handle", "a")))
    _append(lb, _alias("handle", "c", ("handle", "c")))
    assert labels(lb) == {}


def test_labels_alias_cycle_stops_on_the_line_that_points_back(tmp_path: Path):
    """a → b → a: from a the walk stops on b's line (unlabelled), from b on a's line (labelled)."""
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    _append(lb, _alias("handle", "a", ("handle", "b"), label="A's own"))
    _append(lb, _alias("handle", "b", ("handle", "a")))
    assert labels(lb) == {("handle", "b"): "A's own"}


def test_labels_a_retracted_alias_does_not_resolve(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    _append(lb, _resolution(*PHONE, "Ola Nordmann"))
    line = _append(lb, _alias(*LID, PHONE, label="Ola (WhatsApp)"))
    lb.retract(line["seq"], "wrong lid")
    assert labels(lb) == {PHONE: "Ola Nordmann"}


def test_labels_a_superseded_alias_gives_way_to_the_later_one(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    _append(lb, _resolution(*PHONE, "Ola Nordmann"))
    _append(lb, _resolution("phone", "+4790000002", "Kari Nordmann", entity=PERSON_B))
    old = _append(lb, _alias(*LID, PHONE))
    _append(lb, _alias(*LID, ("phone", "+4790000002"), supersedes=old["id"]))
    assert labels(lb)[LID] == "Kari Nordmann"


def test_labels_a_later_entity_line_for_the_same_ref_replaces_the_alias(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    _append(lb, _resolution(*PHONE, "Ola Nordmann"))
    _append(lb, _alias(*LID, PHONE))
    _append(lb, _resolution(*LID, "Someone Else", entity=PERSON_B))
    assert labels(lb)[LID] == "Someone Else"


def test_labels_alias_of_that_is_not_a_ref_is_ignored(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    draft = _alias(*LID, PHONE, label="Own")
    draft["payload"]["alias_of"] = {"kind": "phone"}  # no value
    _append(lb, draft)
    assert labels(lb) == {LID: "Own"}


# -- property: labels_from is a pure function of the lines ------------------------------------

REFS = [("email", "a@x"), ("email", "b@x"), ("phone", "+1"), ("phone", "+2")]
LABELS = [None, "A", "B", "C"]


@st.composite
def synthetic_lines(draw: st.DrawFn) -> list[dict[str, Any]]:
    """Resolution lines with unique ids and increasing seq; some retracted, some superseding an
    earlier line, some without a label. Retractions are lines too."""
    n = draw(st.integers(min_value=0, max_value=12))
    lines: list[dict[str, Any]] = []
    for seq in range(1, n + 1):
        kind, value = draw(st.sampled_from(REFS))
        label = draw(st.sampled_from(LABELS))
        draft = _resolution(kind, value, label)
        if draw(st.booleans()):  # an alias instead: any ref, itself included, so cycles happen
            draft = _alias(kind, value, draw(st.sampled_from(REFS)), label)
        resolutions_so_far = [line for line in lines if line["kind"] == "resolution"]
        if resolutions_so_far and draw(st.booleans()):
            draft["payload"]["supersedes"] = draw(st.sampled_from(resolutions_so_far))["id"]
        draft["seq"], draft["id"] = seq, f"id-{seq}"
        lines.append(draft)
        if resolutions_so_far and draw(st.booleans()):
            target = draw(st.sampled_from(resolutions_so_far))
            lines.append(
                {
                    "seq": seq + 100,  # any seq later than every resolution it could name
                    "id": f"id-r{seq}",
                    "at": "2026-03-02T09:14:00Z",
                    "source": "manual",
                    "kind": "retraction",
                    "tier": 2,
                    "payload": {"schema": "retraction/v1", "supersedes": target["id"], "seq": target["seq"]},
                }
            )
    return lines


@settings(max_examples=200, deadline=None)
@given(synthetic_lines(), st.randoms())
def test_labels_from_is_deterministic_and_maps_only_refs_with_an_unretracted_resolution(lines, rnd):
    result = labels_from(lines)
    shuffled = list(lines)
    rnd.shuffle(shuffled)
    assert labels_from(shuffled) == result  # order of input is irrelevant: seq decides
    assert labels_from(lines) == result
    retracted = {line["payload"]["supersedes"] for line in lines if line["kind"] == "retraction"}
    live = [line for line in lines if line["kind"] == "resolution" and line["id"] not in retracted]
    superseded = {line["payload"].get("supersedes") for line in live}
    standing = [line for line in live if line["id"] not in superseded]
    last: dict[tuple[str, str], dict[str, Any]] = {}
    for line in standing:
        ref = (line["payload"]["ref"]["kind"], line["payload"]["ref"]["value"])
        if ref not in last or line["seq"] > last[ref]["seq"]:
            last[ref] = line
    assert set(result) <= set(last)  # only a ref with a standing line is mapped
    for ref, line in last.items():  # follow alias_of at most 4 hops, stop on a cycle or a dead end
        seen = {ref}
        for _ in range(4):
            target = line["payload"].get("alias_of")
            if target is None or (target["kind"], target["value"]) in seen:
                break
            nxt = last.get((target["kind"], target["value"]))
            if nxt is None:
                break
            seen.add((target["kind"], target["value"]))
            line = nxt
        if line["payload"].get("label"):
            assert result[ref] == line["payload"]["label"]
        else:
            assert ref not in result


@settings(max_examples=100, deadline=None)
@given(st.lists(st.tuples(st.sampled_from(REFS), st.sampled_from(REFS), st.sampled_from(LABELS)), max_size=8))
def test_labels_from_terminates_on_any_alias_graph(edges):
    """Every ref an alias of any ref, itself included: cycles, self-loops, long chains. No hang."""
    lines = []
    for seq, ((kind, value), target, label) in enumerate(edges, start=1):
        draft = _alias(kind, value, target, label)
        draft["seq"], draft["id"] = seq, f"id-{seq}"
        lines.append(draft)
    result = labels_from(lines)
    assert set(result) <= {(k, v) for (k, v), _t, _l in edges}
