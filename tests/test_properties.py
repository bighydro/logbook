"""Property-based tests: for ANY sequence of appends the chain verifies; ANY single mutation breaks it."""

from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from logbook.chain import verify_lines
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
payload = st.fixed_dictionaries({"schema": st.just("note/v1"), "text": st.text(max_size=80)})
ts = st.datetimes(
    min_value=__import__("datetime").datetime(2000, 1, 1),
    max_value=__import__("datetime").datetime(2040, 1, 1),
).map(lambda d: d.replace(microsecond=0).isoformat() + "Z")
draft = st.fixed_dictionaries(
    {
        "at": ts,
        "source": st.sampled_from(["manual", "sim-a", "sim-b"]),
        "kind": st.sampled_from(["note", "event", "location"]),
        "tier": st.sampled_from([1, 2, 3]),
        "payload": payload,
    }
)


@settings(max_examples=60, deadline=None)
@given(st.lists(draft, min_size=1, max_size=25))
def test_any_append_sequence_verifies(tmp_path_factory, drafts):
    root = tmp_path_factory.mktemp("lb")
    lb = Logbook.init(root, "UTC")
    lb.append_many(drafts)
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == len(drafts)


@settings(max_examples=60, deadline=None)
@given(st.lists(draft, min_size=2, max_size=12), st.data())
def test_any_single_mutation_is_detected(tmp_path_factory, drafts, data):
    root = tmp_path_factory.mktemp("lb")
    lb = Logbook.init(root, "UTC")
    lb.append_many(drafts)
    rows = list(lb.lines())
    i = data.draw(st.integers(0, len(rows) - 1))
    field = data.draw(st.sampled_from(["at", "source", "kind", "tier", "text", "prev", "seq"]))
    row = rows[i]
    if field == "text":
        row["payload"]["text"] += "x"
    elif field == "tier":
        row["tier"] = 1 if row["tier"] != 1 else 2
    elif field == "seq":
        row["seq"] += 1
    elif field == "prev":
        row["prev"] = "f" * 64
    else:
        row[field] = str(row[field]) + "x"
    _, _, errors = verify_lines(rows)
    assert errors, f"mutation of {field} on line {i} went undetected"
