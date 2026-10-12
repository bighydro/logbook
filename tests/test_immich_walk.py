"""`logbook sync immich` against a fake Immich HTTP server on the loopback: the honest total before
the walk starts, progress as `x of N`, every asset counted once although the server serves the ones
sharing a `fileCreatedAt` at a page boundary again, a walk interrupted at page 3 resumed on the next
run from the saved cursor, `--restart`. 2,500 synthetic assets of the Oslo persona (Ines Nordmann,
who does not exist); the only connections are to 127.0.0.1."""

from __future__ import annotations

import base64
import json
import re
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import cycle
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.core.store import Logbook

KEY = "synthetic-read-only-key"
N = 2_500
PAGE = 250
INES = "0000be0b-0000-4000-8000-000000000017"  # Immich's id for a person; the name never reaches a line
# assets per second, cycled: single frames, bursts, a live-photo pair, a scanned batch — the runs of
# equal `fileCreatedAt` a page boundary falls inside
MOMENT_SIZES = (1, 3, 1, 7, 1, 2, 12, 1, 4, 1, 1, 5, 1, 9, 2)


def _stamp(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _asset(i: int, taken: datetime, updated: datetime) -> dict[str, Any]:
    video = i % 50 == 49
    name = f"IMG_{i:04d}.{'MOV' if video else 'HEIC'}"
    return {
        "id": f"0000a5e7-0000-4000-8000-{i:012x}",
        "createdAt": _stamp(updated - timedelta(hours=1)),
        "ownerId": "00000f00-0000-4000-8000-000000000001",
        "type": "VIDEO" if video else "IMAGE",
        "originalPath": f"/data/library/owner-1/{taken:%Y/%Y-%m-%d}/{name}",
        "originalFileName": name,
        "originalMimeType": "video/quicktime" if video else "image/heic",
        "fileCreatedAt": _stamp(taken),
        "fileModifiedAt": _stamp(taken),
        "localDateTime": _stamp(taken),
        "updatedAt": _stamp(updated),
        "isFavorite": i % 97 == 0,
        "isArchived": False,
        "isTrashed": False,
        "visibility": "timeline",
        "duration": 3200 if video else None,
        "exifInfo": {
            "dateTimeOriginal": _stamp(taken),
            "description": "",
            "exifImageWidth": 4032,
            "exifImageHeight": 3024,
            "fileSizeInByte": 2_400_000,
            "latitude": 59.9139,
            "longitude": 10.7522,
            "make": "SimCam",
            "model": "Model 3",
            "city": "Oslo",
            "country": "Norway",
        },
        "livePhotoVideoId": None,
        "people": [{"id": INES, "name": "Ines Nordmann"}] if i % 5 == 0 else [],
        "checksum": base64.b64encode(f"synthetic-checksum-{i:04d}".encode()).decode(),
        "width": 4032,
        "height": 3024,
    }


def synthetic_assets(n: int = N, sizes: tuple[int, ...] = MOMENT_SIZES) -> list[dict[str, Any]]:
    """`n` assets in `fileCreatedAt` order, grouped into moments of `sizes` assets at one second;
    `updatedAt` scattered over 2026 so the walk's watermark is not the last page's."""
    moments = cycle(sizes)
    taken = datetime(2024, 1, 1, 9, 0, tzinfo=UTC)
    assets: list[dict[str, Any]] = []
    while len(assets) < n:
        size = next(moments)
        for _ in range(size):
            if len(assets) == n:
                break
            i = len(assets)
            updated = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=(i * 7919) % n)
            assets.append(_asset(i, taken, updated))
        taken += timedelta(minutes=17 + size)
    return assets


def _encode(stamp: str) -> str:
    return base64.urlsafe_b64encode(stamp.encode("ascii")).decode("ascii")


def _decode(cursor: str) -> str:
    return base64.urlsafe_b64decode(cursor.encode("ascii")).decode("ascii")


class FakeImmich:
    """Immich's `POST /api/search/metadata` as the walk sees it, on 127.0.0.1: pages ordered by
    `fileCreatedAt`, the cursor naming the page's last stamp, the next page every asset from that
    stamp on — so the assets sharing the stamp at a page boundary are served twice, which is what
    the adapter has to see through. `GET /api/assets/statistics` (`statistics="assets"`) or `GET
    /api/server/statistics` (`"server"`) count the assets; `"none"` answers neither. `fail_posts`
    names the search requests (1-based, over the server's life) answered 500."""

    def __init__(
        self, assets: list[dict[str, Any]], statistics: str = "assets", fail_posts: tuple[int, ...] = ()
    ) -> None:
        self.assets = sorted(assets, key=lambda a: (a["fileCreatedAt"], a["id"]))
        self.statistics = statistics
        self.fail_posts = set(fail_posts)
        self.posts: list[dict[str, Any]] = []
        self.gets: list[str] = []
        self.served = 0
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _send(self, status: int, doc: dict[str, Any]) -> None:
                body = json.dumps(doc).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                fake.gets.append(self.path)
                if self.headers.get("x-api-key") != KEY:
                    self._send(401, {"message": "Unauthorized"})
                    return
                images = sum(a["type"] == "IMAGE" for a in fake.assets)
                videos = len(fake.assets) - images
                if self.path == "/api/assets/statistics" and fake.statistics == "assets":
                    self._send(200, {"images": images, "videos": videos, "total": len(fake.assets)})
                elif self.path == "/api/server/statistics" and fake.statistics == "server":
                    self._send(200, {"photos": images, "videos": videos, "usage": 0, "usageByUser": []})
                else:
                    self._send(403, {"message": "Forbidden"})

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                if self.headers.get("x-api-key") != KEY or self.path != "/api/search/metadata":
                    self._send(401, {"message": "Unauthorized"})
                    return
                fake.posts.append(body)
                if len(fake.posts) in fake.fail_posts:
                    self._send(500, {"message": "Internal server error"})
                    return
                self._send(200, fake.page(body))

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def page(self, body: dict[str, Any]) -> dict[str, Any]:
        size = int(body.get("size") or PAGE)
        since = (body.get("filter") or {}).get("updatedAt", {}).get("gte")
        rows = [a for a in self.assets if since is None or a["updatedAt"] >= since]
        cursor = body.get("cursor")
        if cursor is not None:
            stamp = _decode(cursor)
            rows = [a for a in rows if a["fileCreatedAt"] >= stamp]
        items = rows[:size]
        self.served += len(items)
        next_cursor = _encode(items[-1]["fileCreatedAt"]) if len(items) == size else None
        return {
            "assets": {
                "total": len(items),
                "count": len(items),
                "items": items,
                "facets": [],
                "nextPage": None,
                "nextCursor": next_cursor,
            }
        }

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.setenv("LOGBOOK_IMMICH_KEY", KEY)
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")  # a shell's proxy never sees the fake
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    return lb


@pytest.fixture
def serve(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., FakeImmich]]:
    running: list[FakeImmich] = []

    def serve(assets: list[dict[str, Any]] | None = None, **options: Any) -> FakeImmich:
        fake = FakeImmich(synthetic_assets() if assets is None else assets, **options)
        fake.start()
        running.append(fake)
        monkeypatch.setenv("LOGBOOK_IMMICH_URL", fake.url)
        return fake

    yield serve
    for fake in running:
        fake.stop()


def _sync(*args: str) -> int:
    try:
        cli.main(["sync", "immich", *args])
    except SystemExit as e:
        return int(e.code or 0)
    return 0


def _state(lb: Logbook) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((lb.root / "state" / "immich.json").read_text(encoding="utf-8"))
    return data


def _progress(err: str) -> list[str]:
    """The page lines: two spaces, a count, `assets`; never a notice. The seconds elapsed are the
    runner's clock, not the walk's (a loaded Windows runner takes a second over 2,500 assets), so
    they read `0s` whatever they were."""
    return [
        re.sub(r" in \d+s", " in 0s", line)
        for line in err.splitlines()
        if re.match(r"  [\d,]+ (of [\d,]+ )?assets", line)
    ]


def _watermark(assets: list[dict[str, Any]]) -> str:
    return max(a["updatedAt"] for a in assets).replace(".000Z", "Z")


# -- the honest total and progress ------------------------------------------------------------


def test_sync_says_the_servers_total_and_the_records_count_before_the_walk_then_counts_x_of_n(
    lb: Logbook, serve: Callable[..., FakeImmich], capsys: pytest.CaptureFixture[str]
) -> None:
    fake = serve()
    assert _sync() == 0
    out, err = capsys.readouterr()
    assert out.splitlines()[0] == "immich: 2,500 assets on the server, 0 already in the record"
    assert fake.gets == ["/api/assets/statistics"]
    progress = _progress(err)
    assert progress[0] == "  250 of 2,500 assets in 0s"
    assert progress[-1] == "  2,500 of 2,500 assets in 0s"
    counted = [int(line.split()[0].replace(",", "")) for line in progress]
    assert counted == sorted(counted) and max(counted) == N, "never a count above the total"
    assert "immich: 2,500 new lines of 2,500 seen from the beginning" in out
    assert lb.meta["seq"] == N
    assert _state(lb) == {"since": _watermark(fake.assets)}


def test_the_record_count_in_the_opening_line_is_the_lines_already_there(
    lb: Logbook, serve: Callable[..., FakeImmich], capsys: pytest.CaptureFixture[str]
) -> None:
    serve()
    _sync()
    capsys.readouterr()
    assert _sync("--restart") == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "immich: 2,500 assets on the server, 2,500 already in the record"
    assert "immich: 0 new lines of 2,500 seen" in out


def test_the_total_falls_back_to_the_server_statistics_then_says_total_unknown(
    lb: Logbook, serve: Callable[..., FakeImmich], capsys: pytest.CaptureFixture[str]
) -> None:
    fake = serve(synthetic_assets(600), statistics="server")
    assert _sync("--dry-run") == 0
    out, err = capsys.readouterr()
    assert out.splitlines()[0] == "immich: 600 assets on the server, 0 already in the record"
    assert fake.gets == ["/api/assets/statistics", "/api/server/statistics"]
    assert _progress(err)[-1] == "  600 of 600 assets in 0s"

    fake.statistics = "none"
    assert _sync("--dry-run") == 0
    out, err = capsys.readouterr()
    assert out.splitlines()[0] == "immich: total unknown, 0 already in the record"
    assert _progress(err)[0] == "  250 assets so far in 0s (total unknown)"


def test_an_incremental_sync_counts_what_changed_since_the_watermark_never_against_the_total(
    lb: Logbook, serve: Callable[..., FakeImmich], capsys: pytest.CaptureFixture[str]
) -> None:
    fake = serve(synthetic_assets(600))
    _sync()
    capsys.readouterr()
    since = "2026-01-01T06:00:00Z"
    assert _sync("--since", since) == 0
    out, err = capsys.readouterr()
    assert out.splitlines()[0] == "immich: 600 assets on the server, 600 already in the record"
    changed = sum(a["updatedAt"] >= since for a in fake.assets)
    assert 0 < changed < 600
    assert _progress(err)[-1] == f"  {changed} assets since {since} in 0s"
    assert f"immich: 0 new lines of {changed} seen since {since}" in out


# -- each asset once -----------------------------------------------------------------------------


def test_every_asset_is_counted_once_although_the_server_serves_the_boundary_ties_twice(
    lb: Logbook, serve: Callable[..., FakeImmich], capsys: pytest.CaptureFixture[str]
) -> None:
    fake = serve()
    assert _sync() == 0
    out = capsys.readouterr().out
    assert fake.served > N, "the fake serves the stamp-sharing assets at each page boundary again"
    repeated = fake.served - N
    assert f"  also {repeated} served again by the server at a page boundary, counted once" in out
    assert lb.meta["seq"] == N
    ids = [line["payload"]["asset_id"] for line in lb.lines()]
    assert len(set(ids)) == N
    assert all(line["payload"]["people"] in ([], [INES]) for line in lb.lines())
    assert "Ines" not in "".join(json.dumps(line) for line in lb.lines())


def test_a_run_of_equal_stamps_longer_than_a_page_is_walked_with_a_bigger_page(
    lb: Logbook, serve: Callable[..., FakeImmich], capsys: pytest.CaptureFixture[str]
) -> None:
    fake = serve(synthetic_assets(500, sizes=(100, 300, 100)))
    assert _sync() == 0
    out = capsys.readouterr().out
    assert "immich: 500 new lines of 500 seen" in out
    assert max(int(post["size"]) for post in fake.posts) > PAGE
    assert lb.meta["seq"] == 500


def test_a_run_of_equal_stamps_longer_than_the_biggest_page_is_a_clear_error(
    lb: Logbook, serve: Callable[..., FakeImmich], capsys: pytest.CaptureFixture[str]
) -> None:
    serve(synthetic_assets(1_300, sizes=(100, 1_200)))
    assert _sync() == 1
    err = capsys.readouterr().err
    assert "share fileCreatedAt 2024-01-01T10:57:00.000Z" in err and "1,000" in err


# -- resume ------------------------------------------------------------------------------------


def test_a_walk_interrupted_at_page_3_resumes_from_the_saved_cursor_and_fetches_only_the_rest(
    lb: Logbook, serve: Callable[..., FakeImmich], capsys: pytest.CaptureFixture[str]
) -> None:
    fake = serve(fail_posts=(4,))
    assert _sync() == 1
    out, err = capsys.readouterr()
    assert "500" in err
    written = int(lb.meta["seq"])
    assert 0 < written <= 3 * PAGE
    state = _state(lb)
    assert "since" not in state, "the watermark waits for the walk to complete"
    walk = state["walk"]
    assert walk["since"] is None and walk["checkpoint"]["fetched"] == written
    saved_cursor = fake.posts[3]["cursor"]  # the page the first run asked for and never got
    assert walk["checkpoint"]["cursor"] == saved_cursor
    assert _progress(err)[-1] == f"  {written:,} of 2,500 assets in 0s"

    posts_before = len(fake.posts)
    assert _sync() == 0
    out, err = capsys.readouterr()
    assert out.splitlines()[0] == f"immich: 2,500 assets on the server, {written:,} already in the record"
    assert (
        f"  resuming where the last run stopped, at {written:,} of 2,500 assets"
        " (state/immich.json; --restart walks from the beginning)" in err
    )
    resumed = fake.posts[posts_before:]
    assert resumed[0]["cursor"] == saved_cursor
    assert all("cursor" in post for post in resumed), "nothing before the saved cursor is asked for"
    ties = len(walk["checkpoint"]["repeats"])  # the stamp-sharing assets the saved cursor serves again
    assert _progress(err)[0] == f"  {written + PAGE - ties:,} of 2,500 assets in 0s"
    assert _progress(err)[-1] == "  2,500 of 2,500 assets in 0s"
    assert f"immich: {N - written:,} new lines of {N - written:,} seen from the beginning" in out
    assert lb.meta["seq"] == N
    assert _state(lb) == {"since": _watermark(fake.assets)}, "the whole walk's watermark, no walk left"
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == N


def test_restart_drops_the_saved_walk_and_begins_again(
    lb: Logbook, serve: Callable[..., FakeImmich], capsys: pytest.CaptureFixture[str]
) -> None:
    fake = serve(fail_posts=(4,))
    _sync()
    written = int(lb.meta["seq"])
    capsys.readouterr()
    posts_before = len(fake.posts)
    assert _sync("--restart") == 0
    out, err = capsys.readouterr()
    assert f"  --restart: the walk interrupted at {written:,} assets is dropped" in err
    assert "cursor" not in fake.posts[posts_before]
    assert f"immich: {N - written:,} new lines of 2,500 seen from the beginning" in out
    assert lb.meta["seq"] == N and "walk" not in _state(lb)


def test_a_saved_walk_is_for_one_since_and_another_since_begins_again(
    lb: Logbook, serve: Callable[..., FakeImmich], capsys: pytest.CaptureFixture[str]
) -> None:
    fake = serve(fail_posts=(4,))
    _sync()
    capsys.readouterr()
    posts_before = len(fake.posts)
    assert _sync("--since", "2026-01-01T00:00:00Z") == 0
    err = capsys.readouterr().err
    assert "was for another --since; starting from the beginning" in err
    assert "cursor" not in fake.posts[posts_before]
    assert fake.posts[posts_before]["filter"] == {"updatedAt": {"gte": "2026-01-01T00:00:00Z"}}


def test_a_dry_run_resumes_too_but_saves_nothing(
    lb: Logbook, serve: Callable[..., FakeImmich], capsys: pytest.CaptureFixture[str]
) -> None:
    serve(fail_posts=(4,))
    _sync()
    before = _state(lb)
    capsys.readouterr()
    assert _sync("--dry-run") == 0
    out, err = capsys.readouterr()
    assert "resuming where the last run stopped" in err
    rest = N - int(before["walk"]["checkpoint"]["fetched"])
    assert f"immich: {rest:,} lines from the beginning (dry run, nothing written)" in out
    assert _state(lb) == before


def test_the_walks_watermark_is_never_later_than_the_moment_the_walk_began(
    lb: Logbook, serve: Callable[..., FakeImmich], capsys: pytest.CaptureFixture[str]
) -> None:
    assets = synthetic_assets(600)
    assets[300]["updatedAt"] = "2099-01-01T00:00:00.000Z"  # a server clock ahead of ours
    serve(assets)
    assert _sync() == 0
    since = _state(lb)["since"]
    assert since < "2099-01-01T00:00:00Z"
    assert datetime.fromisoformat(since.replace("Z", "+00:00")) <= datetime.now(UTC)
