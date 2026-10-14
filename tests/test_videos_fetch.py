"""`logbook videos fetch`: the one command of the videos that touches the network. It downloads one file
at a time into a bounded cache under `state/videos/` (8 GB unless `--cache-gb` says otherwise, kept for
the next run), refuses a file bigger than the cap and says so, verifies each file against the md5 Drive
reported when the line was written, keeps nothing that does not match, and resumes a download a dropped
connection or an earlier run left part way. Nothing it fetches is ever copied into the record.

The synthetic family's folder of `tests/test_drive_videos.py` (Ines Nordmann of Oslo, who does not
exist), each video a few kilobytes of invented bytes, in the in-process fake of `tests/google_fake.py`."""

from __future__ import annotations

import http.client
import io
import json
from pathlib import Path
from typing import Any

import pytest
from google_fake import FILES_SCOPE, FOLDER_MIME, USER, Fake, md5_of, private_key, write_key

from logbook import cli
from logbook.contrib import videos
from logbook.contrib.adapters import drive_videos, service_account
from logbook.core.store import Logbook

KEY_ENV, USER_ENV, FOLDER_ENV = service_account.KEY_ENV, service_account.USER_ENV, drive_videos.FOLDER_ENV
ROOT = "1FamilyVideosFolderSynthetic01"
A, B, C, BIG = (
    "1TapeASyntheticVideoId0000001",
    "1TapeBSyntheticVideoId0000002",
    "1TapeCSyntheticVideoId0000003",
    "1TapeBigSyntheticVideoId00004",
)
MEDIA = {
    A: b"synthetic tape A, the first recording " * 80,  # 3,040 bytes
    B: b"synthetic tape B " * 235,  # 3,995 bytes
    C: b"synthetic tape C!" * 150,  # 2,550 bytes
}


def _files() -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {
        ROOT: {"id": ROOT, "name": "Familiens videoer", "mimeType": FOLDER_MIME, "parents": ["0AOwnerRoot"]}
    }
    for n, (file_id, data) in enumerate(MEDIA.items(), 1):
        files[file_id] = {
            "id": file_id,
            "name": f"Home 0{n}",
            "mimeType": "video/mp4",
            "parents": [ROOT],
            "size": str(len(data)),
            "md5Checksum": md5_of(data),
            "createdTime": "2019-03-02T10:00:00.000Z",
            "modifiedTime": "2019-03-02T10:00:00.000Z",
        }
    files[B]["resourceKey"] = "0-SyntheticResourceKeyB"
    files[BIG] = {
        **files[A],
        "id": BIG,
        "name": "Home 09",
        "size": "9000000000",  # 9 GB: bigger than the default cap
        "md5Checksum": "00000000000000000000000000000000",
    }
    return files


@pytest.fixture(scope="module")
def key() -> Any:
    return private_key()


@pytest.fixture
def fake(tmp_path: Path, key: Any, monkeypatch: pytest.MonkeyPatch, no_network: list[str]) -> Any:
    server = Fake(key, files=_files(), media=dict(MEDIA))
    server.waits = []  # type: ignore[attr-defined]
    monkeypatch.setattr(service_account, "send", server)
    monkeypatch.setattr(service_account, "open_stream", server.stream)
    monkeypatch.setattr(service_account, "sleep", server.waits.append)  # type: ignore[attr-defined]
    monkeypatch.setattr(videos, "CHUNK", 512)  # small reads, so a cut lands part way
    monkeypatch.setenv(KEY_ENV, str(write_key(tmp_path / "google-sa.json", key)))
    monkeypatch.setenv(USER_ENV, USER)
    monkeypatch.setenv(FOLDER_ENV, ROOT)
    yield server
    assert no_network == [], "the fake is the only way out"


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: Fake) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    assert _run("sync", "drive", "--videos") == 0
    fake.requests.clear()
    fake.assertions.clear()
    return lb


def _run(*args: str) -> int:
    try:
        cli.main(list(args))
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    return 0


def _cache(lb: Logbook) -> Path:
    return lb.root / "state" / "videos"


def _cached(lb: Logbook) -> dict[str, bytes]:
    folder = _cache(lb)
    if not folder.is_dir():
        return {}
    return {p.stem: p.read_bytes() for p in folder.iterdir() if p.is_file() and p.suffix != ".part"}


def _state(lb: Logbook) -> dict[str, Any]:
    return json.loads((lb.root / "state" / "videos.json").read_text(encoding="utf-8"))


def _gb(n: int) -> str:
    return str(n / 1e9)


def test_fetch_downloads_one_file_at_a_time_and_verifies_each(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = int(lb.meta["seq"])
    assert _run("videos", "fetch", "--cache-gb", _gb(20_000)) == 0
    assert _cached(lb) == MEDIA
    assert [s["id"] for s in fake.streamed] == [A, B, C]  # one after another, in the folder's order
    assert not list(_cache(lb).glob("*.part"))
    assert int(Logbook(lb.root).meta["seq"]) == seq, "fetching writes no line"
    stored = list((lb.root / "attachments").glob("*"))
    assert not any(p.stat().st_size >= len(MEDIA[C]) for p in stored), "a video was copied into the record"
    out = capsys.readouterr().out
    assert "md5 verified" in out
    assert set(_state(lb)["fetched"]) == {A, B, C}


def test_the_cap_is_respected_and_the_run_stops_when_the_next_file_would_pass_it(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run("videos", "fetch", "--cache-gb", _gb(8_000)) == 0  # A and B fit, C would pass it
    assert set(_cached(lb)) == {A, B}
    assert C not in [s["id"] for s in fake.streamed]
    out = capsys.readouterr().out
    assert "cache is full" in out and "videos infer" in out
    assert sum(p.stat().st_size for p in _cache(lb).iterdir() if p.is_file()) <= 8_000


def test_a_file_bigger_than_the_cap_is_refused_and_said_so(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run("videos", "fetch") == 0  # the default cap: 8 GB
    out = capsys.readouterr().out
    assert "Home 09" in out and "9.0 GB" in out and "8.0 GB" in out and "--cache-gb" in out
    assert BIG not in [s["id"] for s in fake.streamed]
    assert set(_cached(lb)) == {A, B, C}


def test_the_cap_given_is_kept_for_the_next_run(lb: Logbook, fake: Fake) -> None:
    assert _run("videos", "fetch", "--cache-gb", _gb(3_500), "--limit", "1") == 0
    assert _state(lb)["cap_bytes"] == 3_500
    assert _run("videos", "fetch") == 0  # still 3,500 bytes: B does not fit beside A
    assert set(_cached(lb)) == {A}


def test_limit_fetches_at_most_n_files(lb: Logbook, fake: Fake) -> None:
    assert _run("videos", "fetch", "--limit", "2") == 0
    assert set(_cached(lb)) == {A, B}


def test_a_dropped_connection_is_resumed_from_where_it_stopped(lb: Logbook, fake: Fake) -> None:
    fake.cut_after = 1_000
    assert _run("videos", "fetch", "--limit", "1") == 0
    assert _cached(lb) == {A: MEDIA[A]}
    asked = [s for s in fake.streamed if s["id"] == A]
    assert asked[0]["range"] is None
    assert asked[1]["range"] == "bytes=1000-"


def test_a_part_an_earlier_run_left_is_resumed_and_verified_whole(lb: Logbook, fake: Fake) -> None:
    _cache(lb).mkdir(parents=True, exist_ok=True)
    (_cache(lb) / f"{A}.part").write_bytes(MEDIA[A][:1234])
    assert _run("videos", "fetch", "--limit", "1") == 0
    assert fake.streamed[0] == {"id": A, "range": "bytes=1234-", "keys": None}
    assert _cached(lb) == {A: MEDIA[A]}


def test_a_part_that_is_already_whole_is_verified_and_kept(lb: Logbook, fake: Fake) -> None:
    _cache(lb).mkdir(parents=True, exist_ok=True)
    (_cache(lb) / f"{A}.part").write_bytes(MEDIA[A])
    assert _run("videos", "fetch", "--limit", "1") == 0
    assert _cached(lb) == {A: MEDIA[A]}


def test_bytes_that_do_not_match_the_md5_are_never_kept(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.media[A] = MEDIA[A].replace(b"first", b"fifth")  # the same length, other bytes
    assert _run("videos", "fetch", "--limit", "1") == 1
    assert _cached(lb) == {}
    assert not list(_cache(lb).glob("*.part"))
    assert "md5" in capsys.readouterr().err


def test_the_resource_key_is_sent_for_a_file_that_has_one(lb: Logbook, fake: Fake) -> None:
    assert _run("videos", "fetch", "--limit", "2") == 0
    keys = {s["id"]: s["keys"] for s in fake.streamed}
    assert keys == {A: None, B: f"{B}/0-SyntheticResourceKeyB"}


def test_bytes_are_read_with_the_files_scope_and_nothing_is_listed(lb: Logbook, fake: Fake) -> None:
    assert _run("videos", "fetch", "--limit", "1") == 0
    assert {a["scope"] for a in fake.assertions} == {FILES_SCOPE}
    assert fake.calls("www.googleapis.com/drive/v3/files") == []


def test_without_the_scope_delegated_it_says_where_to_grant_it(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.delegated.discard(FILES_SCOPE)
    assert _run("videos", "fetch", "--limit", "1") == 1
    err = capsys.readouterr().err
    assert "drive.readonly" in err and "Domain-wide delegation" in err
    assert _cached(lb) == {}


def test_a_file_already_inferred_is_not_fetched_again(lb: Logbook, fake: Fake) -> None:
    video = next(line for line in lb.lines() if line["kind"] == "video" and line["payload"]["raw_id"] == A)
    lb.append(
        "2026-10-14T20:00:00Z",
        "model:video-rules/1",
        "draft",
        2,
        {
            "schema": "draft/v1",
            "unit": "event",
            "subject": [videos.scene_ref(str(video["id"]), 0.0, 12.5)],
            "read_head": lb.meta["head"],
            "read_count": 1,
            "language": "en",
            "segments": [{"text": "Nothing places or dates this scene.", "evidence": [str(video["id"])]}],
        },
    )
    assert _run("videos", "fetch", "--limit", "1") == 0
    assert set(_cached(lb)) == {B}


def test_a_fetch_with_nothing_to_do_says_so(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run("videos", "fetch", "--cache-gb", _gb(20_000)) == 0
    capsys.readouterr()
    assert _run("videos", "fetch", "--cache-gb", _gb(20_000)) == 0
    assert "nothing to fetch" in capsys.readouterr().out


# -- resuming, and what is never kept (the size-and-quota check's tests) ---------------------------------


def _serve(monkeypatch: pytest.MonkeyPatch, fake: Fake, change: Any) -> None:
    """Every stream answer passed through `change(answer, headers)` before the client reads it."""
    original = fake.stream

    def stream(method: str, url: str, headers: dict[str, str], timeout: float) -> Any:
        return change(original(method, url, headers, timeout), headers)

    monkeypatch.setattr(service_account, "open_stream", stream)


def test_a_server_that_answers_200_to_a_range_restarts_the_file_and_verifies_it(
    lb: Logbook, fake: Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.cut_after = 1_000
    original = fake.stream

    def ignores_range(method: str, url: str, headers: dict[str, str], timeout: float) -> Any:
        return original(method, url, {k: v for k, v in headers.items() if k != "Range"}, timeout)

    monkeypatch.setattr(service_account, "open_stream", ignores_range)
    assert _run("videos", "fetch", "--limit", "1") == 0
    assert _cached(lb) == {A: MEDIA[A]}
    assert not list(_cache(lb).glob("*.part"))


def test_a_body_longer_than_the_line_says_is_not_kept(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.media[A] = MEDIA[A] + b"tail bytes Drive never reported"
    assert _run("videos", "fetch", "--limit", "1") == 1
    assert _cached(lb) == {} and not list(_cache(lb).glob("*.part"))
    assert "Drive sent" in capsys.readouterr().err


def test_a_short_body_with_no_error_is_resumed_from_its_byte(
    lb: Logbook, fake: Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    once = {"done": False}

    def short(answer: Any, _headers: dict[str, str]) -> Any:
        if not once["done"]:  # a clean end 1,500 bytes in, as urllib's read(n) shows a drop
            once["done"] = True
            answer.body = io.BytesIO(answer.body.read(1_500))
        return answer

    _serve(monkeypatch, fake, short)
    assert _run("videos", "fetch", "--limit", "1") == 0
    assert _cached(lb) == {A: MEDIA[A]}
    assert [s["range"] for s in fake.streamed if s["id"] == A] == [None, "bytes=1500-"]


def test_repeated_short_bodies_keep_the_part_for_the_next_run(
    lb: Logbook, fake: Fake, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def short(answer: Any, _headers: dict[str, str]) -> Any:
        answer.body = io.BytesIO(answer.body.read(500))  # every answer ends clean, 500 bytes in
        return answer

    _serve(monkeypatch, fake, short)
    assert _run("videos", "fetch", "--limit", "1") == 1
    assert _cached(lb) == {}
    parts = list(_cache(lb).glob("*.part"))
    assert parts and parts[0].read_bytes() == MEDIA[A][: 500 * (videos.RESUMES + 1)], "the part was deleted"
    assert "resume" in capsys.readouterr().err


def test_repeated_drops_past_the_limit_keep_the_part_and_say_so(
    lb: Logbook, fake: Fake, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def cut(answer: Any, _headers: dict[str, str]) -> Any:
        fake.cut_after = 500  # for the next answer too
        return answer

    fake.cut_after = 500
    _serve(monkeypatch, fake, cut)
    assert _run("videos", "fetch", "--limit", "1") == 1
    parts = list(_cache(lb).glob("*.part"))
    assert parts and parts[0].read_bytes() == MEDIA[A][: 500 * (videos.RESUMES + 1)]
    assert "resume" in capsys.readouterr().err
    assert fake.waits == [1.0, 2.0, 4.0]  # type: ignore[attr-defined]


def test_a_chunked_body_cut_short_is_a_drop_not_a_traceback(
    lb: Logbook, fake: Fake, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Early:
        """Gives 700 bytes, then fails as http.client does on a chunked body cut short."""

        def __init__(self, data: bytes) -> None:
            self._data, self._given = io.BytesIO(data), 0

        def read(self, n: int) -> bytes:
            if self._given >= 700:
                raise http.client.IncompleteRead(b"")
            chunk = self._data.read(min(n, 700 - self._given))
            self._given += len(chunk)
            return chunk

        def close(self) -> None:
            self._data.close()

    def early(answer: Any, _headers: dict[str, str]) -> Any:
        if answer.status in (200, 206):
            answer.body = Early(answer.body.read())
        return answer

    _serve(monkeypatch, fake, early)
    assert _run("videos", "fetch", "--limit", "1") == 1
    err = capsys.readouterr().err
    assert "Traceback" not in err and "resume" in err
    assert list(_cache(lb).glob("*.part"))


def test_a_part_an_earlier_run_left_with_wrong_bytes_fails_the_md5_and_nothing_is_kept(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    _cache(lb).mkdir(parents=True, exist_ok=True)
    (_cache(lb) / f"{A}.part").write_bytes(b"x" * 1234)  # damaged on disk
    assert _run("videos", "fetch", "--limit", "1") == 1
    assert fake.streamed[0]["range"] == "bytes=1234-"
    assert _cached(lb) == {} and not list(_cache(lb).glob("*.part"))
    assert "md5" in capsys.readouterr().err


def test_a_416_when_the_file_in_drive_is_shorter_than_the_part_keeps_nothing(lb: Logbook, fake: Fake) -> None:
    fake.media[A] = MEDIA[A][:2_000]
    _cache(lb).mkdir(parents=True, exist_ok=True)
    (_cache(lb) / f"{A}.part").write_bytes(MEDIA[A][:2_500])
    assert _run("videos", "fetch", "--limit", "1") == 1
    assert _cached(lb) == {} and not list(_cache(lb).glob("*.part"))


def test_a_part_longer_than_the_line_says_is_not_kept(lb: Logbook, fake: Fake) -> None:
    _cache(lb).mkdir(parents=True, exist_ok=True)
    (_cache(lb) / f"{A}.part").write_bytes(MEDIA[A] + b"x")
    assert _run("videos", "fetch", "--limit", "1") == 1
    assert fake.streamed == []  # nothing to ask for
    assert _cached(lb) == {} and not list(_cache(lb).glob("*.part"))


def test_a_part_is_not_counted_twice_against_the_cap(lb: Logbook, fake: Fake) -> None:
    _cache(lb).mkdir(parents=True, exist_ok=True)
    (_cache(lb) / f"{A}.part").write_bytes(MEDIA[A][:1234])
    assert _run("videos", "fetch", "--cache-gb", _gb(len(MEDIA[A])), "--limit", "1") == 0  # exactly A
    assert _cached(lb) == {A: MEDIA[A]}


def test_a_zero_byte_file_does_not_stop_the_run(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    line = next(ln for ln in lb.lines() if ln["kind"] == "video" and ln["payload"]["raw_id"] == A)
    payload = {**line["payload"], "bytes": 0, "digest": {"md5": md5_of(b"")}, "raw_id": f"{A}z"}
    payload["file"] = {**payload["file"], "id": f"{A}z", "name": "Home 00"}
    payload["title"] = "Home 00"  # a failed upload left in the folder, first in its order
    lb.append("2026-10-14T20:00:00Z", "drive-videos", "video", 2, payload)
    fake.media[f"{A}z"] = b""
    code = _run("videos", "fetch", "--limit", "2")
    assert "Traceback" not in capsys.readouterr().err
    assert code == 0 and set(_cached(lb)) == {f"{A}z", A}


def test_a_malformed_state_file_is_one_clear_error_and_no_download(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    (lb.root / "state").mkdir(exist_ok=True)
    (lb.root / "state" / "videos.json").write_text("{", encoding="utf-8")
    assert _run("videos", "fetch") == 2
    err = capsys.readouterr().err
    assert "state/videos.json" in err and "Traceback" not in err
    assert fake.streamed == []


def test_a_quota_answer_on_the_bytes_stops_with_one_line(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.fail(403, reason="dailyLimitExceeded")
    assert _run("videos", "fetch") == 1
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1 and "HTTP 403" in err[0]
    assert _cached(lb) == {}


def test_a_rate_limit_mid_file_keeps_the_part_and_stops_with_one_line(
    lb: Logbook, fake: Fake, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.cut_after = 1_000
    calls = {"n": 0}
    original = fake.stream

    def then_quota(method: str, url: str, headers: dict[str, str], timeout: float) -> Any:
        calls["n"] += 1
        if calls["n"] == 2:  # the resume request: Drive says no, every retry
            for _ in range(service_account.RETRIES + 1):
                fake.fail(429, reason="rateLimitExceeded")
        return original(method, url, headers, timeout)

    monkeypatch.setattr(service_account, "open_stream", then_quota)
    assert _run("videos", "fetch") == 1
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1 and "gave up" in err[0], err
    parts = list(_cache(lb).glob("*.part"))
    assert parts and parts[0].read_bytes() == MEDIA[A][:1_000]


def test_a_file_gone_from_drive_is_said_and_the_next_file_is_still_fetched(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    del fake.media[A]  # deleted from Drive since the line was written: a 404
    assert _run("videos", "fetch", "--limit", "2") == 1
    err = capsys.readouterr().err
    assert "Home 01" in err and "Traceback" not in err
    assert set(_cached(lb)) == {B}
