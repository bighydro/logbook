"""The immich live adapter and `logbook sync`: mapping to photo/v1, paging, the watermark, dry-run,
idempotent re-sync, missing environment. No network: the HTTP layer is stubbed with synthetic pages."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters, cli
from logbook.adapters import immich
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "immich"
ENV = {"LOGBOOK_IMMICH_URL": "http://immich.test:2283", "LOGBOOK_IMMICH_KEY": "synthetic-read-only-key"}
CONFIG = immich.Config(url="http://immich.test:2283", key="synthetic-read-only-key")
P17 = "0000be0b-0000-4000-8000-000000000017"
P42 = "0000be0b-0000-4000-8000-000000000042"


def _page(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data


class FakeServer:
    """Answers POST /search/metadata from the fixture pages, keyed by cursor; records every request."""

    def __init__(self, pages: dict[str | None, str]):
        self.pages = pages
        self.requests: list[dict[str, Any]] = []

    def __call__(self, config: immich.Config, body: dict[str, Any]) -> dict[str, Any]:
        assert config == CONFIG
        self.requests.append(body)
        return _page(self.pages[body.get("cursor")])


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> FakeServer:
    fake = FakeServer({None: "page1.json", "cursor-page-2": "page2.json"})
    monkeypatch.setattr(immich, "_post", fake)
    return fake


def _lines(server: FakeServer, since: str | None = None) -> list[dict[str, Any]]:
    return list(immich.pull(CONFIG, since))


def _by_name(lines: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {line["payload"]["file_name"]: line for line in lines}


# -- registry ---------------------------------------------------------------


def test_registry_lists_immich_and_dawarich_as_live_adapters():
    assert [a.NAME for a in adapters.live_adapters()] == ["immich", "dawarich"]
    assert adapters.live("immich") is immich
    assert adapters.live("nope") is None


def test_registry_all_adapters_knows_both_kinds_and_find_only_asks_file_adapters(tmp_path):
    names = [a.NAME for a in adapters.all_adapters()]
    assert "dawarich" in names and "immich" in names
    file_names = [a.NAME for a in adapters.file_adapters()]
    assert file_names == [
        "dawarich",
        "google-takeout-location",
        "ios-contacts",
        "whatsapp",
        "whatsapp-contacts",
        "imessage",
        "ios-notes",
        "ios-calendar",
        "ics",
    ]
    p = tmp_path / "notes.txt"
    p.write_text("just words\n", encoding="utf-8")
    assert adapters.find(p) is None  # immich has no sniff and must not break the lookup


# -- configure ----------------------------------------------------------------


def test_configure_reads_url_and_key_from_the_environment():
    assert immich.configure(ENV) == CONFIG
    assert immich.ENV == ("LOGBOOK_IMMICH_URL", "LOGBOOK_IMMICH_KEY")


@pytest.mark.parametrize("missing", ["LOGBOOK_IMMICH_URL", "LOGBOOK_IMMICH_KEY"])
def test_configure_returns_none_when_a_variable_is_absent_or_empty(missing):
    assert immich.configure({k: v for k, v in ENV.items() if k != missing}) is None
    assert immich.configure({**ENV, missing: ""}) is None


# -- pull: requests and paging ----------------------------------------------------


def test_pull_filters_on_updated_at_and_orders_by_file_time_with_exif_and_people(server):
    _lines(server, since="2026-03-01T00:00:00Z")
    first = server.requests[0]
    assert first["orderBy"] == {"field": "fileCreatedAt", "direction": "asc"}  # updatedAt is not orderable
    assert first["withExif"] is True and first["withPeople"] is True
    assert first["filter"] == {"updatedAt": {"gte": "2026-03-01T00:00:00Z"}}
    assert first["size"] == immich.PAGE_SIZE
    assert "cursor" not in first


def test_pull_without_since_sends_no_filter(server):
    _lines(server)
    assert "filter" not in server.requests[0]


def test_pull_pages_with_the_cursor_until_the_server_returns_none(server):
    lines = _lines(server)
    assert len(lines) == 6
    assert [r.get("cursor") for r in server.requests] == [None, "cursor-page-2"]
    assert [line["payload"]["file_name"] for line in lines][:3] == [
        "IMG_2041.HEIC",
        "Screenshot_20260301-100512.png",
        "IMG-20260301-WA0012.jpg",
    ]


def test_pull_skips_trashed_and_hidden_assets(monkeypatch):
    monkeypatch.setattr(immich, "_post", FakeServer({None: "junk.json"}))
    assert _lines(FakeServer({})) == []


def test_post_sends_the_api_key_header_to_the_search_endpoint(monkeypatch):
    seen: dict[str, Any] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

        def read(self):
            return json.dumps(_page("page2.json")).encode()

    def fake_urlopen(req, timeout):
        seen["url"], seen["headers"], seen["body"], seen["method"] = (
            req.full_url,
            {k.lower(): v for k, v in req.header_items()},
            json.loads(req.data),
            req.get_method(),
        )
        return Response()

    monkeypatch.setattr(immich, "urlopen", fake_urlopen)
    doc = immich._post(immich.Config(url="http://immich.test:2283/", key="k-1"), {"size": 1})
    assert seen["url"] == "http://immich.test:2283/api/search/metadata"
    assert seen["method"] == "POST"
    assert seen["headers"]["x-api-key"] == "k-1"
    assert seen["headers"]["content-type"] == "application/json"
    assert seen["body"] == {"size": 1}
    assert doc["assets"]["count"] == 3


# -- mapping ------------------------------------------------------------------------


def test_every_line_has_the_photo_envelope(server):
    for line in _lines(server):
        assert set(line) == {"at", "end", "tz", "source", "kind", "tier", "payload"}
        assert line["end"] is None and line["tz"] is None
        assert (line["source"], line["kind"], line["tier"]) == ("immich", "photo", 1)
        p = line["payload"]
        assert p["schema"] == "photo/v1" and p["library"] == "immich"
        assert p["raw_id"] == p["asset_id"]
        json.dumps(p)


def test_camera_photo_maps_every_field(server):
    line = _by_name(_lines(server))["IMG_2041.HEIC"]
    assert line["at"] == "2026-03-01T08:12:00Z"  # EXIF 09:12 +01:00 → UTC
    assert line["payload"] == {
        "schema": "photo/v1",
        "asset_id": "0000a5e7-0000-4000-8000-000000000001",
        "library": "immich",
        "file_name": "IMG_2041.HEIC",
        "media": "image",
        "lat": 59.9139,
        "lon": 10.7522,
        "camera": "SimCam Model 3",
        "width": 4032,
        "height": 3024,
        "live_photo": False,
        "provenance": "camera",
        "faces": 2,
        "people": [P17, P42],
        "raw_id": "0000a5e7-0000-4000-8000-000000000001",
        "extra": {
            "checksum": "c3ludGhldGljLWNoZWNrc3VtLTAwMDE=",
            "original_path": "/data/library/owner-1/2026/2026-03-01/IMG_2041.HEIC",
            "updated_at": "2026-03-02T06:10:00Z",
        },
    }


def test_watermark_is_the_assets_updated_at_not_its_capture_time(server):
    line = _by_name(_lines(server))["IMG_2041.HEIC"]
    assert immich.watermark(line) == "2026-03-02T06:10:00Z"
    assert line["at"] == "2026-03-01T08:12:00Z"


def test_people_are_ids_never_names(server):
    for line in _lines(server):
        text = json.dumps(line)
        assert "Person" not in text and "name" not in line["payload"]


def test_screenshot_without_exif_uses_file_time_and_has_no_camera_or_gps(server):
    line = _by_name(_lines(server))["Screenshot_20260301-100512.png"]
    p = line["payload"]
    assert line["at"] == "2026-03-01T09:05:12Z"
    assert p["provenance"] == "screenshot"
    assert (p["width"], p["height"]) == (1170, 2532)
    assert p["faces"] == 0 and p["people"] == []
    for absent in ("lat", "lon", "camera", "duration_s"):
        assert absent not in p


def test_received_image_falls_back_to_asset_dimensions_when_exif_has_none(server):
    p = _by_name(_lines(server))["IMG-20260301-WA0012.jpg"]["payload"]
    assert p["provenance"] == "received"
    assert (p["width"], p["height"]) == (1280, 960)
    assert "camera" not in p


def test_video_maps_media_and_duration_in_seconds(server):
    line = _by_name(_lines(server))["IMG_2042.MOV"]
    p = line["payload"]
    assert line["at"] == "2026-03-01T12:00:00Z"
    assert p["media"] == "video" and p["duration_s"] == 12.345
    assert p["provenance"] == "camera" and p["live_photo"] is False


def test_live_photo_is_flagged_and_description_is_kept_when_non_empty(server):
    p = _by_name(_lines(server))["IMG_2043.HEIC"]["payload"]
    assert p["live_photo"] is True and p["provenance"] == "camera"
    assert p["faces"] == 1 and p["people"] == [P17]
    assert p["extra"]["description"] == "Late lunch by the fjord"


def test_empty_description_is_not_carried(server):
    for line in _lines(server):
        if line["payload"]["file_name"] != "IMG_2043.HEIC":
            assert "description" not in line["payload"]["extra"]


@pytest.mark.parametrize(
    ("file_name", "provenance"),
    [
        ("IMG_2041.HEIC", "camera"),
        ("Screenshot_20260301-100512.png", "screenshot"),
        ("IMG-20260301-WA0012.jpg", "received"),
        ("IMG_2042.MOV", "camera"),
        ("IMG_2043.HEIC", "camera"),
        ("scan_0007.jpg", "other"),
    ],
)
def test_all_four_provenance_outcomes(server, file_name, provenance):
    assert _by_name(_lines(server))[file_name]["payload"]["provenance"] == provenance


@pytest.mark.parametrize(
    ("duration", "seconds"),
    [(None, None), (12345, 12.345), (0, 0.0), ("0:01:02.500", 62.5), ("00:00:03.000000", 3.0)],
)
def test_duration_accepts_milliseconds_and_the_older_clock_string(duration, seconds):
    assert immich._duration_s(duration) == seconds


# -- sync: CLI --------------------------------------------------------------------------


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    return lb


def _sync(*args: str) -> Callable[[], None]:
    return lambda: cli.main(["sync", *args])


def test_sync_appends_every_asset_and_writes_the_watermark(lb, server, capsys):
    _sync("immich")()
    out = capsys.readouterr().out
    assert "immich: 6 new lines" in out
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 6
    state = json.loads((lb.root / "state" / "immich.json").read_text(encoding="utf-8"))
    assert state == {"since": "2026-03-02T06:14:00Z"}  # the latest updatedAt seen, not the last item's
    assert next(lb.lines())["tz"] == "Europe/Oslo"


def test_sync_starts_from_the_stored_watermark(lb, server):
    (lb.root / "state").mkdir()
    (lb.root / "state" / "immich.json").write_text(json.dumps({"since": "2026-02-28T00:00:00Z"}))
    _sync("immich")()
    assert server.requests[0]["filter"] == {"updatedAt": {"gte": "2026-02-28T00:00:00Z"}}


def test_sync_since_overrides_the_stored_watermark(lb, server):
    (lb.root / "state").mkdir()
    (lb.root / "state" / "immich.json").write_text(json.dumps({"since": "2026-02-28T00:00:00Z"}))
    _sync("immich", "--since", "2026-03-01T12:00:00Z")()
    assert server.requests[0]["filter"] == {"updatedAt": {"gte": "2026-03-01T12:00:00Z"}}


def test_sync_re_run_appends_nothing_and_keeps_the_chain_valid(lb, server, capsys):
    _sync("immich")()
    _sync("immich")()
    out = capsys.readouterr().out
    assert "immich: 0 new lines" in out.splitlines()[-1]
    second_run_first_page = server.requests[2]
    assert second_run_first_page["filter"] == {"updatedAt": {"gte": "2026-03-02T06:14:00Z"}}
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 6


def test_sync_picks_up_an_old_photo_uploaded_after_the_last_run(lb, server, monkeypatch, capsys):
    _sync("immich")()
    late = FakeServer({None: "late.json"})
    monkeypatch.setattr(immich, "_post", late)
    _sync("immich")()
    assert late.requests[0]["filter"] == {"updatedAt": {"gte": "2026-03-02T06:14:00Z"}}
    assert "immich: 1 new lines" in capsys.readouterr().out.splitlines()[-1]
    lines = list(lb.lines())
    assert len(lines) == 7
    assert lines[-1]["at"] == "2015-07-14T16:20:00Z"  # `at` stays the capture time
    assert lines[-1]["payload"]["file_name"] == "IMG_0342.JPG"
    state = json.loads((lb.root / "state" / "immich.json").read_text(encoding="utf-8"))
    assert state == {"since": "2026-03-05T20:00:00Z"}


def test_sync_dry_run_prints_a_summary_and_writes_nothing(lb, server, capsys):
    _sync("immich", "--dry-run")()
    out = capsys.readouterr().out
    assert "6 lines" in out
    assert "2026-03-01T08:12:00Z" in out and "2026-03-01T16:00:00Z" in out
    assert "camera: 3" in out and "screenshot: 1" in out and "received: 1" in out and "other: 1" in out
    assert lb.meta["seq"] == 0 and lb.files() == []
    assert not (lb.root / "state").exists()


def test_sync_missing_environment_exits_2_naming_the_variables(lb, server, monkeypatch, capsys):
    monkeypatch.delenv("LOGBOOK_IMMICH_KEY")
    with pytest.raises(SystemExit) as e:
        _sync("immich")()
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "LOGBOOK_IMMICH_KEY" in err and "LOGBOOK_IMMICH_URL" not in err
    assert server.requests == [] and lb.meta["seq"] == 0


def test_sync_unknown_adapter_exits_2(lb, capsys):
    with pytest.raises(SystemExit) as e:
        _sync("nope")()
    assert e.value.code == 2
    assert "nope" in capsys.readouterr().err


def test_sync_bad_since_exits_2(lb, server, capsys):
    with pytest.raises(SystemExit) as e:
        _sync("immich", "--since", "yesterday")()
    assert e.value.code == 2 and server.requests == []


def test_sync_server_error_exits_1_after_keeping_what_was_pulled(lb, monkeypatch, capsys):
    import urllib.error

    calls: list[dict[str, Any]] = []

    def failing(config, body):
        calls.append(body)
        if body.get("cursor") is None:
            return _page("page1.json")
        raise urllib.error.HTTPError("http://immich.test", 500, "boom", None, None)  # type: ignore[arg-type]

    monkeypatch.setattr(immich, "_post", failing)
    with pytest.raises(SystemExit) as e:
        _sync("immich")()
    assert e.value.code == 1
    assert "500" in capsys.readouterr().err
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 3  # page 1 landed at the checkpoint; the watermark did not move
    assert not (lb.root / "state" / "immich.json").exists()


# -- assets the server has not extracted metadata for yet -------------------
# Immich writes the asset row at upload and fills EXIF, dimensions and video duration in a later
# job, which bumps `updatedAt`. Until it runs, `exifInfo` holds only the file size and
# width/height/duration/thumbhash are null. `pull` defers such assets: not yielded, so not in the
# watermark, so the next sync's `updatedAt >= since` window still covers them once processed.
# pending.json: one extracted asset (earliest updatedAt) and three pending ones; extracted.json:
# the same three after the job, with later stamps.

PENDING_NOTE = "3 pending (metadata not extracted yet; will arrive on a later sync)"


@pytest.fixture
def pending(monkeypatch: pytest.MonkeyPatch) -> FakeServer:
    fake = FakeServer({None: "pending.json"})
    monkeypatch.setattr(immich, "_post", fake)
    return fake


def test_live_photo_pair_alone_is_camera_evidence():
    asset = _page("pending.json")["assets"]["items"][1]  # IMG_3101: a pair link and nothing else
    line = immich._line(asset)
    p = line["payload"]
    assert p["live_photo"] is True and p["provenance"] == "camera"
    assert "camera" not in p and "width" not in p and "height" not in p and "lat" not in p
    assert line["at"] == "2021-08-14T13:05:12Z"  # the file time


def test_metadata_is_pending_when_there_are_no_dimensions_and_exif_holds_only_the_file_size():
    assert [immich._metadata_pending(a) for a in _page("pending.json")["assets"]["items"]] == [
        False,
        True,
        True,
        True,
    ]
    assert not any(immich._metadata_pending(a) for a in _page("extracted.json")["assets"]["items"])
    # a file with no EXIF at all but known dimensions has been through the job (screenshots, received)
    assert not immich._metadata_pending({"width": 1170, "height": 2532, "exifInfo": {"fileSizeInByte": 1}})
    assert immich._metadata_pending({"width": None, "height": None, "exifInfo": None})


def test_pull_defers_pending_assets_and_counts_them(pending):
    counts: dict[str, int] = {}
    lines = list(immich.pull(CONFIG, None, counts=counts))
    assert [line["payload"]["file_name"] for line in lines] == ["IMG_3100.HEIC"]
    assert counts == {"pending": 3}


def test_pull_yields_a_deferred_asset_once_a_later_page_has_its_metadata(monkeypatch):
    monkeypatch.setattr(immich, "_post", FakeServer({None: "extracted.json"}))
    counts: dict[str, int] = {}
    outcome = {
        line["payload"]["file_name"]: line["payload"]["provenance"]
        for line in immich.pull(CONFIG, None, counts=counts)
    }
    assert outcome == {
        "IMG_3101.JPG": "camera",
        "IMG_3102.JPG": "other",
        "video-31_singular_display.MOV": "other",
    }
    assert counts == {"pending": 0}


def test_sync_reports_pending_assets_and_keeps_them_out_of_the_watermark(lb, pending, capsys):
    _sync("immich")()
    out = capsys.readouterr().out
    assert "immich: 1 new lines of 1 seen from the beginning" in out
    assert PENDING_NOTE in out
    state = json.loads((lb.root / "state" / "immich.json").read_text(encoding="utf-8"))
    # the extracted asset's stamp; the pending ones are later and must not move it
    assert state == {"since": "2026-09-03T18:39:00Z"}


def test_sync_dry_run_reports_pending_assets_too(lb, pending, capsys):
    _sync("immich", "--dry-run")()
    out = capsys.readouterr().out
    assert "immich: 1 lines from the beginning (dry run, nothing written)" in out
    assert PENDING_NOTE in out
    assert not (lb.root / "state").exists()


def test_sync_picks_up_deferred_assets_once_immich_has_extracted_them(lb, pending, monkeypatch, capsys):
    _sync("immich")()
    later = FakeServer({None: "extracted.json"})
    monkeypatch.setattr(immich, "_post", later)
    _sync("immich")()
    assert later.requests[0]["filter"] == {"updatedAt": {"gte": "2026-09-03T18:39:00Z"}}
    out = capsys.readouterr().out
    assert "immich: 3 new lines of 3 seen" in out.splitlines()[-1] and "pending" not in out.splitlines()[-1]
    lines = list(lb.lines())
    assert [line["payload"]["file_name"] for line in lines] == [
        "IMG_3100.HEIC",
        "IMG_3101.JPG",
        "IMG_3102.JPG",
        "video-31_singular_display.MOV",
    ]
    assert lines[1]["payload"]["provenance"] == "camera" and lines[1]["payload"]["camera"] == "SimPhone 3"
    assert lines[3]["payload"]["duration_s"] == 4.2
    state = json.loads((lb.root / "state" / "immich.json").read_text(encoding="utf-8"))
    assert state == {"since": "2026-09-03T19:12:00Z"}


# -- progress ---------------------------------------------------------------


def test_pull_reports_the_running_asset_count_after_each_page(server):
    ticks: list[tuple[int, float]] = []
    list(immich.pull(CONFIG, None, progress=lambda n, elapsed: ticks.append((n, elapsed))))
    assert [n for n, _ in ticks] == [3, 6]
    assert all(elapsed >= 0 for _, elapsed in ticks)


@pytest.mark.parametrize("dry_run", [False, True])
def test_sync_prints_a_progress_line_per_page_to_stderr(lb, server, capsys, dry_run):
    _sync("immich", *(["--dry-run"] if dry_run else []))()
    err = capsys.readouterr().err.splitlines()
    assert [line for line in err if "assets in" in line] == ["  3 assets in 0s", "  6 assets in 0s"]
