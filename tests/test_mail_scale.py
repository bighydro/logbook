"""The mail adapter at Takeout scale: a synthetic mbox streamed in constant memory, every message a
line, the attachments never decoded. The 500 MB benchmark asserts a rate and a memory ceiling, so it
is `stress` (LOGBOOK_STRESS=1, never in CI): a shared runner meets neither."""

from __future__ import annotations

import mailbox
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from synthetic_mbox import BLOB_SIZES, write_mbox

from logbook.contrib.adapters import mail

TZ = "Europe/Oslo"
BENCHMARK_BYTES = 500_000_000
MIN_MB_PER_S = 40.0  # the target on a laptop
PEAK_RSS_CEILING_MB = 200  # a 500 MB file read whole would need more than twice this
PROGRESS_EVERY = 10_000

MEASURE = """
import resource, sys, time
from pathlib import Path
from logbook.contrib.adapters import mail
path = Path(sys.argv[1])
reports = []
t = time.perf_counter()
n = 0
for line in mail.run(path, timezone="Europe/Oslo", progress=lambda *a: reports.append(a)):
    n += 1
elapsed = time.perf_counter() - t
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
if sys.platform != "darwin":
    rss *= 1024  # Linux reports kilobytes
print(n, round(elapsed, 2), round(rss / 1e6), len(reports))
"""


def _measure(path: Path) -> tuple[int, float, int, int]:
    """(lines, seconds, peak RSS in MB, progress reports) of a run over `path`, in a process of its own."""
    out = subprocess.run(
        [sys.executable, "-c", MEASURE, str(path)], capture_output=True, encoding="utf-8", check=True
    ).stdout.split()
    return int(out[0]), float(out[1]), int(out[2]), int(out[3])


def test_the_synthetic_mbox_agrees_with_the_standard_library(tmp_path: Path) -> None:
    """Every message the stdlib's mbox reader finds is a line here, with the same subject and sender,
    on a file read in small chunks so separators fall across chunk boundaries."""
    path = tmp_path / "takeout.mbox"
    n = write_mbox(path, 3_000_000, seed=1)
    box = mailbox.mbox(path)
    try:
        oracle = [
            (str(m["Subject"] or ""), str(m["From"] or ""), str(m.get("Message-ID") or "")) for m in box
        ]
    finally:
        box.close()  # Windows: the handle must be gone before the file is read again
    assert len(oracle) == n
    counts: dict[str, int] = {}
    lines = list(mail.run(path, timezone=TZ, counts=counts, chunk_size=4096))
    assert len(lines) == n
    for line, (subject, sender, message_id) in zip(lines, oracle, strict=True):
        p = line["payload"]
        assert p.get("subject") == " ".join(subject.split()) or "=?" in subject
        assert sender.endswith(f"<{p['from']['email']}>")
        if message_id:
            assert p["message_id"] == message_id.strip("<>")
        assert p["size"] > 0 and p["schema"] == "mail/v1"
    assert counts["no_message_id"] == n // 97 and counts["date_from_separator"] == n // 89
    assert not any(key.startswith("skipped_") for key in counts)


def test_attachments_are_named_and_sized_never_decoded_and_the_body_is_capped(tmp_path: Path) -> None:
    path = tmp_path / "takeout.mbox"
    write_mbox(path, 3_000_000, seed=2)
    counts: dict[str, int] = {}
    with_attachments = [
        line["payload"]
        for line in mail.run(path, timezone=TZ, counts=counts)
        if "attachments" in line["payload"]
    ]
    assert with_attachments
    for p in with_attachments:
        for a in p["attachments"]:
            assert set(a) == {"filename", "media_type", "bytes"}  # no digest: the bytes were never read
            assert a["bytes"] in BLOB_SIZES
        assert len(p["body"].encode("utf-8")) <= mail.BODY_CAP
    assert counts["attachments_referenced"] == sum(len(p["attachments"]) for p in with_attachments)


def test_progress_is_reported_every_ten_thousand_messages_with_the_bytes_read(tmp_path: Path) -> None:
    path = tmp_path / "small.mbox"
    data = b"".join(_tiny(i) for i in range(25_000))
    path.write_bytes(data)
    reports: list[tuple[int, int, float]] = []
    n = sum(1 for _ in mail.run(path, timezone=TZ, progress=lambda *a: reports.append(a)))
    assert n == 25_000
    assert [r[0] for r in reports] == [10_000, 20_000]
    assert 0 < reports[0][1] < reports[1][1] <= len(data) and reports[0][2] >= 0


def _tiny(i: int) -> bytes:
    return (
        f"From {i}@xxx Mon Mar 02 10:15:00 +0000 2026\nMessage-ID: <t{i}@mail.example.org>\n"
        "Date: Mon, 2 Mar 2026 11:15:00 +0100\nFrom: Ola Nordmann <ola@example.org>\n"
        f"Subject: tiny {i}\n\nhello {i}\n\n"
    ).encode()


@pytest.mark.stress
@pytest.mark.skipif(
    sys.platform == "win32", reason="peak RSS is read through `resource`, which Windows has not"
)
def test_a_500_mb_mbox_streams_at_40_mb_per_second_in_flat_memory(tmp_path: Path) -> None:
    path = tmp_path / "All mail Including Spam and Trash.mbox"
    started = time.perf_counter()
    n = write_mbox(path, BENCHMARK_BYTES)
    size = path.stat().st_size
    print(f"\nwrote {n:,} messages, {size / 1e6:,.0f} MB in {time.perf_counter() - started:.1f}s")
    lines, seconds, peak_mb, reports = _measure(path)
    rate = size / 1e6 / seconds
    print(f"mail.run: {lines:,} lines in {seconds:.1f}s = {rate:,.1f} MB/s, peak RSS {peak_mb} MB")
    assert lines == n
    assert reports == n // PROGRESS_EVERY
    assert rate >= MIN_MB_PER_S
    assert peak_mb <= PEAK_RSS_CEILING_MB


def test_a_boundary_that_starts_like_another_is_not_taken_for_it(tmp_path: Path) -> None:
    path = tmp_path / "nested.mbox"
    path.write_bytes(
        b"From 1@xxx Mon Mar 02 10:15:00 +0000 2026\n"
        b"Message-ID: <n1@mail.example.org>\nDate: Mon, 2 Mar 2026 11:15:00 +0100\n"
        b"From: Ola Nordmann <ola@example.org>\nSubject: nested\n"
        b'Content-Type: multipart/mixed; boundary="part"\n\n'
        b"--part\n"
        b'Content-Type: multipart/alternative; boundary="part-inner"\n\n'
        b"--part-inner\nContent-Type: text/plain\n\nthe words\n"
        b"--part-inner\nContent-Type: text/html\n\n<p>the words</p>\n"
        b"--part-inner--\n"
        b'--part\nContent-Type: application/pdf; name="plan.pdf"\n'
        b"Content-Transfer-Encoding: base64\n\nJVBERi0xLjQK\n"
        b"--part--\n\n"
    )
    [line] = mail.run(path, timezone=TZ)
    p = line["payload"]
    assert p["body"] == "the words" and "body_from" not in p.get("extra", {})  # the newline is the boundary's
    assert p["attachments"] == [{"filename": "plan.pdf", "media_type": "application/pdf", "bytes": 9}]


def test_text_before_the_first_separator_is_no_message_and_is_let_go(tmp_path: Path) -> None:
    path = tmp_path / "preamble.mbox"
    path.write_bytes(b"x" * 300_000 + b"\n\n" + _tiny(1) + _tiny(2))
    lines = list(mail.run(path, timezone=TZ, chunk_size=4096))
    assert [line["payload"]["subject"] for line in lines] == ["tiny 1", "tiny 2"]
    with path.open("rb") as fh:  # the first separator stands at the start of a chunk, not of the file
        found = list(mail.messages(fh, 4096))
    assert len(found) == 2 and found[0][0].startswith(b"From 1@xxx")
