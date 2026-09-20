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
    for (kind, value), label in result.items():
        candidates = [
            line
            for line in standing
            if (line["payload"]["ref"]["kind"], line["payload"]["ref"]["value"]) == (kind, value)
        ]
        assert candidates, f"{kind}:{value} has no standing resolution"
        assert max(candidates, key=lambda line: line["seq"])["payload"].get("label") == label
    for line in standing:  # and every standing, labelled ref is mapped when it is the last one
        ref = (line["payload"]["ref"]["kind"], line["payload"]["ref"]["value"])
        last = max(
            (c for c in standing if (c["payload"]["ref"]["kind"], c["payload"]["ref"]["value"]) == ref),
            key=lambda c: c["seq"],
        )
        if last["payload"].get("label"):
            assert result[ref] == last["payload"]["label"]
        else:
            assert ref not in result
