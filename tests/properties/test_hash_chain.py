"""The hash chain (SPEC §1: GENESIS; §3: content hash, line hash, what makes a record valid, write
order; §6: conformance — changing any hashed field of any line or deleting any line makes `verify`
report invalid, while `id` and the stored form are outside the hash). Stated for any sequence of
lines, any single byte of any line, and any point of truncation. The record is a real one on disk
(`Logbook.init`, `append_many`), in two month files, so chain order and file order differ (§3)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from hypothesis import Phase, given, settings
from hypothesis import strategies as st

from logbook.core.chain import GENESIS, compute_hash, content_hash, parse_line, verify_lines
from logbook.core.store import Logbook
from properties.common import CI, drafts

Stored = tuple[int, Path, int, int, bytes]  # (seq, file, line number in the file, offset, the bytes)


def record(root: Path, lines: list[dict[str, Any]]) -> Logbook:
    lb = Logbook.init(root, "Europe/Oslo")
    lb.append_many(lines)
    return lb


def stored(lb: Logbook) -> list[Stored]:
    """Every stored line of the record with where it is: the bytes between newlines."""
    found: list[Stored] = []
    for file in lb.files():
        offset = 0
        for n, raw in enumerate(file.read_bytes().splitlines(keepends=True), 1):
            found.append((int(parse_line(raw)["seq"]), file, n, offset, raw))
            offset += len(raw)
    return found


def names(errors: list[str], lb: Logbook, position: int, file: Path, n: int) -> bool:
    """Whether an error names the line: by its position in the verifier's reading order (`line N`,
    SPEC §3 orders by seq) or, for a line that is not JSON, by its file and line number."""
    wanted = (f"line {position}:", f"{file.relative_to(lb.root).as_posix()} line {n}:")
    return any(e.startswith(w) or f" {w}" in e for e in errors for w in wanted)


def test_genesis_is_the_head_of_the_empty_record(tmp_path: Path) -> None:
    """SPEC §1: a record with no lines has seq 0 and head GENESIS, the 64 ASCII zeros, a named
    constant and not the digest of anything; it is also the `prev` of the first line (§3)."""
    assert GENESIS == "0" * 64
    assert verify_lines([]) == (0, GENESIS, [])
    lb = Logbook.init(tmp_path / "lb", "UTC")
    assert (lb.meta["seq"], lb.meta["head"]) == (0, GENESIS)
    assert lb.verify() == (0, GENESIS, [])
    line = lb.append(
        at="2026-03-01T07:30:00Z", source="manual", kind="note", tier=2, payload={"schema": "note/v1"}
    )
    assert line["prev"] == GENESIS and line["seq"] == 1


@settings(CI, max_examples=40)
@given(drafts(min_size=1))
def test_any_sequence_of_lines_verifies(
    tmp_path_factory: pytest.TempPathFactory, lines: list[dict[str, Any]]
) -> None:
    """SPEC §3: for any sequence of appends the record is valid — seq counts from 1 by one, every
    `prev` is the previous `hash` (GENESIS first), every hash recomputes from the content hash,
    `logbook.json` names the last line — whatever order the month files hold the lines in."""
    lb = record(tmp_path_factory.mktemp("lb"), lines)
    seq, head, errors = lb.verify()
    assert errors == [] and seq == len(lines)
    prev = GENESIS
    for n, line in enumerate(lb.lines(), 1):
        assert line["seq"] == n and line["prev"] == prev
        assert line["hash"] == compute_hash(line) and len(content_hash(line)) == 64
        prev = line["hash"]
    assert head == prev == lb.meta["head"] and lb.meta["seq"] == len(lines)


@settings(CI, max_examples=40)
@given(drafts(), drafts(min_size=1, max_size=1))
def test_appending_one_line_changes_only_the_head(
    tmp_path_factory: pytest.TempPathFactory, lines: list[dict[str, Any]], one: list[dict[str, Any]]
) -> None:
    """SPEC §3: a line is appended to the month file of its `at` and `logbook.json` moves its seq and
    head; no stored byte of any earlier line changes, no other file changes, and nothing else in
    `logbook.json` changes (§1: unknown keys are preserved)."""
    lb = record(tmp_path_factory.mktemp("lb"), lines)
    before = {f: f.read_bytes() for f in lb.files()}
    meta_before = lb.meta
    line = lb.append(**one[0])
    after = {f: f.read_bytes() for f in lb.files()}
    grown = [f for f in after if after[f] != before.get(f, b"")]
    assert len(grown) == 1, "exactly one month file grew"
    assert (
        after[grown[0]]
        == before.get(grown[0], b"") + (json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n").encode()
    )
    assert all(after[f] == before[f] for f in before if f != grown[0])
    meta = lb.meta
    assert (meta["seq"], meta["head"]) == (meta_before["seq"] + 1, line["hash"])
    assert line["prev"] == meta_before["head"] and line["seq"] == len(lines) + 1
    assert {k: v for k, v in meta.items() if k not in ("seq", "head")} == {
        k: v for k, v in meta_before.items() if k not in ("seq", "head")
    }
    assert lb.verify()[2] == []


@settings(CI, max_examples=120)
@given(drafts(min_size=1), st.data())
def test_flipping_any_byte_of_any_line_is_rejected_naming_the_line(
    tmp_path_factory: pytest.TempPathFactory, lines: list[dict[str, Any]], data: st.DataObject
) -> None:
    """SPEC §6: changing any hashed field of any line makes `verify` report invalid, naming the line.
    A byte flip the hash cannot see — one that leaves the parsed line equal in every field but `id`
    (§2: `id` is outside the hash; §6: a re-serialisation that leaves the canonical form unchanged
    is not detected and is not required to be) — is the one exemption, and then `verify` still
    accepts; every other flip is rejected, and an error names the line: by its position in the
    verifier's reading order (by the seq it now claims, §3), or by file and line number when the
    bytes are no longer a line."""
    lb = record(tmp_path_factory.mktemp("lb"), lines)
    original = {int(line["seq"]): line for line in lb.lines()}
    seq, file, n, offset, raw = data.draw(st.sampled_from(stored(lb)))
    i = data.draw(st.integers(0, len(raw) - 1))
    byte = data.draw(st.integers(0, 255).filter(lambda b: b != raw[i]))
    flipped = raw[:i] + bytes([byte]) + raw[i + 1 :]
    content = file.read_bytes()
    file.write_bytes(content[:offset] + flipped + content[offset + len(raw) :])
    _seq, _head, errors = lb.verify()
    parsed = parsed_line(flipped)
    unseen = (
        parsed is not None
        and "id" in parsed
        and {k: v for k, v in parsed.items() if k != "id"}
        == {k: v for k, v in original[seq].items() if k != "id"}
    )
    merged = raw.endswith(b"\n") and not flipped.endswith(b"\n") and offset + len(raw) < len(content)
    if unseen and not merged:
        assert errors == [], "a flip the hash does not cover (SPEC §2, §6) is not an error"
        return
    assert errors, f"a flipped byte at {i} of line {seq} went undetected"
    order = sorted(stored_raw(lb), key=lambda row: (claimed_seq(row[2]), lb.files().index(row[0]), row[1]))
    position = 1 + order.index((file, n, flipped))
    assert names(errors, lb, position, file, n), (errors, position)


def parsed_line(raw: bytes) -> dict[str, Any] | None:
    """The line the reader makes of these bytes, or None when they are not one."""
    try:
        line = parse_line(raw.rstrip(b"\n"))
    except ValueError:
        return None
    return line if isinstance(line, dict) else None


def claimed_seq(raw: bytes) -> int:
    """The seq a stored line claims, as the reader orders it: a line that is not one, or has no
    integer seq, sorts first (`store._seq_of`)."""
    line = parsed_line(raw)
    seq = line.get("seq") if line is not None else None
    return seq if isinstance(seq, int) and not isinstance(seq, bool) else 0


def stored_raw(lb: Logbook) -> list[tuple[Path, int, bytes]]:
    """Every stored line, parseable or not: (file, line number in the file, the bytes)."""
    return [
        (file, n, raw)
        for file in lb.files()
        for n, raw in enumerate(file.read_bytes().splitlines(keepends=True), 1)
    ]


ONE_MONTH = drafts(min_size=1, end=datetime(2026, 4, 1, tzinfo=UTC))  # one month file: the record is one file


def truncated(lb: Logbook, cut: int) -> tuple[int, str, list[str], list[Stored]]:
    """The one month file cut at byte `cut`; what `verify` then reports, and the lines left whole
    (a line is whole without its newline: the reader takes it)."""
    (file,) = lb.files()
    raw = file.read_bytes()
    rows = stored(lb)
    file.write_bytes(raw[:cut])
    whole = [row for row in rows if row[3] + len(row[4].rstrip(b"\n")) <= cut]
    seq, head, errors = lb.verify()
    return seq, head, errors, whole


@settings(CI, max_examples=40)
@given(ONE_MONTH, st.data())
def test_truncating_the_record_at_a_line_boundary_reports_the_last_good_head(
    tmp_path_factory: pytest.TempPathFactory, lines: list[dict[str, Any]], data: st.DataObject
) -> None:
    """SPEC §3, write order: a crash leaves at worst a truncated month file. Cut the month file at the
    end of any line (or before the first): the lines before the cut are a valid prefix of the chain,
    and `verify` reports their count and head (the last good head; GENESIS when none survives) and
    one error, that the record is not the one `logbook.json` names. A cut that takes only the final
    newline leaves every line whole, and the record valid."""
    lb = record(tmp_path_factory.mktemp("lb"), lines)
    rows = stored(lb)
    boundaries = [0, *(row[3] + len(row[4]) for row in rows), rows[-1][3] + len(rows[-1][4].rstrip(b"\n"))]
    cut = data.draw(st.sampled_from(boundaries))
    seq, head, errors, whole = truncated(lb, cut)
    assert seq == len(whole)
    assert head == (original_hash(whole[-1]) if whole else GENESIS)
    if len(whole) == len(lines):
        assert errors == []
    else:
        assert len(errors) == 1 and "logbook.json" in errors[0]


# No shrinking: the shrunk counterexample (two lines, the file cut one byte into the second, once
# reported seq 0 and GENESIS) is the first example below, and shrinking a record on disk costs twenty
# seconds a run; the first counterexample found is reported instead.
@settings(CI, max_examples=15, phases=(Phase.explicit, Phase.reuse, Phase.generate))
@given(drafts(min_size=1, max_size=3, end=datetime(2026, 4, 1, tzinfo=UTC)), st.data())
def test_truncating_the_record_inside_a_line_reports_the_last_good_head(
    tmp_path_factory: pytest.TempPathFactory, lines: list[dict[str, Any]], data: st.DataObject
) -> None:
    """SPEC §3, write order, continued: cut the month file inside any line. The lines before the cut
    are still a valid prefix, so `verify` reports their count and head (the last good head; GENESIS
    when none survives), and an error naming the cut line by its file and line number."""
    lb = record(tmp_path_factory.mktemp("lb"), lines)
    rows = stored(lb)
    row = data.draw(st.sampled_from(rows))
    cut = row[3] + data.draw(st.integers(1, len(row[4].rstrip(b"\n")) - 1))
    seq, head, errors, whole = truncated(lb, cut)
    assert errors, "the cut line is not a line"
    assert seq == len(whole)
    assert head == (original_hash(whole[-1]) if whole else GENESIS)
    assert names(errors, lb, 0, row[1], row[2]), (errors, row[2])


def original_hash(row: Stored) -> str:
    """The hash a line had, from the bytes the cut left whole (the file is not read again: after a
    cut inside a line it holds bytes that are not one)."""
    return str(parse_line(row[4])["hash"])


@settings(CI, max_examples=40)
@given(drafts(min_size=1), st.data())
def test_dropping_the_tail_of_the_chain_reports_the_last_good_head(
    tmp_path_factory: pytest.TempPathFactory, lines: list[dict[str, Any]], data: st.DataObject
) -> None:
    """The same for a record of several month files, truncated in chain order: keep the first k lines
    wherever they are and drop the rest; `verify` reports k and the k-th hash, and that `logbook.json`
    names a later head."""
    lb = record(tmp_path_factory.mktemp("lb"), lines)
    rows = stored(lb)
    k = data.draw(st.integers(0, len(lines) - 1))
    kept = {row[0]: row for row in rows if row[0] <= k}
    for file in lb.files():
        file.write_bytes(
            b"".join(row[4] for row in sorted(kept.values(), key=lambda r: r[3]) if row[1] == file)
        )
    seq, head, errors = lb.verify()
    assert seq == k
    assert head == (str(parse_line(kept[k][4])["hash"]) if k else GENESIS)
    assert len(errors) == 1 and "logbook.json" in errors[0]
