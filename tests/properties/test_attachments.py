"""The attachment store (SPEC §1.1): a file lives at `<root>/attachments/<sha256>`, the lowercase hex
SHA-256 of its exact bytes, no extension, no subdirectory; the store is write-once and two lines that
point at the same bytes share one file; a line carries `{sha256, path, bytes, media_type}`. Stated for
any bytes, any media type, and any way of handing the bytes over (whole, as a file, as a stream of
chunks)."""

from __future__ import annotations

import hashlib
from itertools import pairwise
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from logbook.store import Logbook

from logbook import attachments
from properties.common import CI

data = st.binary(max_size=3000)
media_types = st.sampled_from(("text/markdown", "image/jpeg", "audio/mp4", "application/octet-stream"))


def chunked(blob: bytes, cuts: list[int]) -> list[bytes]:
    """`blob` split at the given offsets, in order; empty chunks allowed."""
    if not blob:
        return [b""]
    bounds = sorted({0, len(blob), *(c % (len(blob) + 1) for c in cuts)})
    return [blob[a:b] for a, b in pairwise(bounds)]


@settings(CI, max_examples=100)
@given(data, media_types)
def test_store_then_load_returns_the_same_bytes_under_their_digest(
    tmp_path_factory: pytest.TempPathFactory, blob: bytes, media_type: str
) -> None:
    """§1.1: the file is stored once, named by its own SHA-256 — the lowercase hex digest of its exact
    bytes, which this test computes on its own — and read back it is byte for byte what was stored;
    the reference a line carries names that path and length."""
    lb = Logbook.init(tmp_path_factory.mktemp("lb") / "lb", "Europe/Oslo")
    sha256 = hashlib.sha256(blob).hexdigest()
    path = lb.attach(blob)
    assert path == lb.root / "attachments" / sha256 and path.parent == lb.root / "attachments"
    assert path.read_bytes() == blob
    assert attachments.is_digest(path.name) and path.suffix == ""
    assert attachments.reference(blob, media_type) == {
        "sha256": sha256,
        "path": f"attachments/{sha256}",
        "bytes": len(blob),
        "media_type": media_type,
    }


@settings(CI, max_examples=60)
@given(data, st.integers(2, 4), st.lists(st.integers(0, 3000), max_size=4))
def test_storing_twice_does_not_duplicate(
    tmp_path_factory: pytest.TempPathFactory, blob: bytes, times: int, cuts: list[int]
) -> None:
    """§1.1: the store is write-once; storing the same bytes again, whole, from a file or as a stream
    of chunks, leaves one file under one name, its bytes unchanged, and no temporary file behind."""
    root = tmp_path_factory.mktemp("lb") / "lb"
    lb = Logbook.init(root, "Europe/Oslo")
    first = lb.attach(blob)
    source = root.parent / "source.bin"
    source.write_bytes(blob)
    for _ in range(times):
        assert lb.attach(blob) == first
        assert lb.attach_file(source) == first
        target, size = attachments.write_chunks(root, iter(chunked(blob, cuts)), first.name)
        assert target == first and size == len(blob)
    assert [p.name for p in (root / "attachments").iterdir()] == [first.name]
    assert first.read_bytes() == blob


@settings(CI, max_examples=60)
@given(data, media_types, st.lists(st.integers(0, 3000), max_size=4))
def test_every_way_of_handing_over_the_bytes_names_the_same_file(
    tmp_path_factory: pytest.TempPathFactory, blob: bytes, media_type: str, cuts: list[int]
) -> None:
    """§1.1: the content address is a function of the bytes alone — the same whether they came whole,
    from a file on disk or in chunks, and the same reference either way."""
    root = tmp_path_factory.mktemp("lb")
    source = root / "source.bin"
    source.write_bytes(blob)
    sha256 = hashlib.sha256(blob).hexdigest()
    assert attachments.digest(blob) == sha256 and attachments.digest_path(source) == (sha256, len(blob))
    assert attachments.reference_path(source, media_type) == attachments.reference(blob, media_type)
    whole, streamed, chunks = root / "a", root / "b", root / "c"
    assert attachments.write(whole, blob).name == sha256
    assert attachments.write_path(streamed, source).name == sha256
    assert attachments.write_chunks(chunks, iter(chunked(blob, cuts)), sha256)[0].name == sha256
    assert (
        (whole / "attachments" / sha256).read_bytes()
        == (streamed / "attachments" / sha256).read_bytes()
        == blob
    )
    assert (chunks / "attachments" / sha256).read_bytes() == blob
    assert [p.name for p in (chunks / "attachments").iterdir()] == [sha256], "no temporary file is left"


@settings(CI, max_examples=60)
@given(data, data)
def test_different_bytes_never_share_a_file(
    tmp_path_factory: pytest.TempPathFactory, a: bytes, b: bytes
) -> None:
    """§1.1: a digest names exactly one content; two different byte strings get two files, and a file
    whose bytes do not match its name is an error, never overwritten."""
    root = tmp_path_factory.mktemp("lb") / "lb"
    lb = Logbook.init(root, "Europe/Oslo")
    pa, pb = lb.attach(a), lb.attach(b)
    assert (pa == pb) == (a == b)
    assert pa.read_bytes() == a and pb.read_bytes() == b
    if a != b:
        pb.write_bytes(a)  # a file under b's name that holds a's bytes
        with pytest.raises(ValueError, match="do not match"):
            lb.attach(b)
        assert pb.read_bytes() == a, "never overwritten"


def test_the_store_is_optional(tmp_path: Path) -> None:
    """§1.1: a record with no `attachments/` directory is valid; the directory appears with the first file."""
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    assert not (lb.root / "attachments").exists() and lb.verify()[2] == []
    lb.attach(b"")
    assert (lb.root / "attachments" / hashlib.sha256(b"").hexdigest()).is_file() and lb.verify()[2] == []
