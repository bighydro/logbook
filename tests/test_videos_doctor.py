"""`doctor`'s `videos` line (RFC 0040): how many video files the record holds, how many were fetched
and inferred and wait in the cache, how many scenes were proposed and confirmed, and the cache against
its cap; read from this machine alone. A record with no video has no such line. The synthetic tape of
`tests/test_videos_infer.py` (an invented family of Oslo, who does not exist)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_videos_infer import HOME_01, TAPE, VOLLEN, FakeMedia, FakeSpeech, FakeVision, _cache, _video
from test_videos_infer import _run as _infer

from logbook import cli
from logbook.contrib import doctor
from logbook.core.store import Logbook
from logbook.labs import scenes


def _check(lb: Logbook) -> doctor.Check | None:
    checks = doctor.run(Logbook(lb.root), {}, installed=lambda _m: True)
    return next((c for c in checks if c.name == "videos"), None)


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_network: list[str]) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    (lb.root / "places.json").write_text(json.dumps({"Vollen Brygge": VOLLEN}), encoding="utf-8")
    engines = (FakeMedia({HOME_01: TAPE}), FakeSpeech(), FakeVision())
    monkeypatch.setattr(scenes, "detect", lambda *_a: engines)
    yield lb
    assert no_network == []


def test_a_record_with_no_video_has_no_videos_line(lb: Logbook) -> None:
    assert _check(lb) is None


def test_the_line_counts_files_inference_scenes_and_the_cache(lb: Logbook) -> None:
    _video(lb, HOME_01, "Home 01")
    _video(lb, "1Tape02SyntheticVideoId000002", "02")
    _cache(lb, HOME_01)
    (lb.root / "state" / "videos.json").write_text(
        json.dumps({"cap_bytes": 8_000_000_000, "fetched": {HOME_01: {"bytes": 12}}}), encoding="utf-8"
    )
    assert _infer("--keep") == 0
    cli.main(["review", "videos", "--accept", "1"])
    found = _check(lb)
    assert found is not None and found.status == "pass"
    assert found.detail == (
        "2 video files in the record (24 bytes); 1 fetched, 1 inferred, 1 waiting in the cache;"
        " 4 scenes, 2 proposed, 1 confirmed; cache 15 bytes of 8.0 GB"
    )


def test_a_cache_over_its_cap_is_a_warn(lb: Logbook) -> None:
    _video(lb, HOME_01, "Home 01")
    _cache(lb, HOME_01)
    state = lb.root / "state" / "videos.json"
    state.write_text(json.dumps({"cap_bytes": 10, "fetched": {}}), encoding="utf-8")
    found = _check(lb)
    assert found is not None and found.status == "warn" and "over its cap" in found.detail


def test_a_state_file_that_is_not_the_shape_is_a_warn_naming_it(lb: Logbook) -> None:
    (lb.root / "state").mkdir(exist_ok=True)
    (lb.root / "state" / "videos.json").write_text("[]", encoding="utf-8")
    found = _check(lb)
    assert found is not None and found.status == "warn" and "state/videos.json" in found.detail
