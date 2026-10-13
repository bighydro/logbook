"""`logbook setup places review --ask-photos`: the place names the owner's photo libraries hold for the
photos already in the record, offered as evidence beside the record's own. On the synthetic fortnight at
sea (`places_record`) with photo lines that carry no place: twelve Immich photos at S3 (and one the server
lost), two at S1, three Photos pictures at S7 (and one the library lost), none at S8. Immich is faked in
process (`immich._get`) under the network guard, and once on the loopback with every connection watched;
the Photos library is a synthetic Photos.sqlite under the test's own home folder."""

from __future__ import annotations

import json
import shutil
import socket
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

import pytest
from photos_library import library
from places_record import (
    AT_S1,
    AT_S3,
    CABIN,
    GONE,
    HARBOUR_TOWN,
    PLATFORM,
    S,
    immich_asset,
    library_assets,
    record_with_photos,
)

from logbook import cli
from logbook.contrib import places_photos, places_review
from logbook.contrib.adapters import immich
from logbook.core import places
from logbook.core.store import Logbook

URL = "http://immich.test:2283"  # .test is reserved: no such host anywhere
KEY = "synthetic-read-only-key"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "places-review"
BLANK = places_review.BLANK
MAC_FOLDER = str(Path("~", "Pictures", "Photos Library.photoslibrary"))  # a Mac's library, under the home
MAC_LIBRARY = str(Path(MAC_FOLDER, "database", "Photos.sqlite"))


@pytest.fixture(scope="module")
def pristine(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("places-photos") / "lb"
    record_with_photos(root)
    return root


@pytest.fixture
def lb(pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    shutil.copytree(pristine, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook(root)


@pytest.fixture
def photos_library() -> Path:
    """The Photos library where a Mac keeps it, under the test's own home folder."""
    return library(Path.home() / "Pictures", library_assets())


class Server:
    """The owner's Immich in process: `GET /api/assets/{id}` answered from `places_record`, a lost
    asset 404, every path asked recorded; with `fail`, every request answers 500."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.asked: list[str] = []

    def __call__(self, config: immich.Config, path: str) -> dict[str, Any]:
        assert config == immich.Config(URL, KEY), "only the configured server, with the configured key"
        self.asked.append(path)
        if self.fail:
            raise HTTPError(URL + path, 500, "Internal Server Error", Message(), None)
        doc = immich_asset(path.removeprefix(immich.ASSET))
        if doc is None:
            raise HTTPError(URL + path, 404, "Not Found", Message(), None)
        return doc

    @property
    def ids(self) -> list[str]:
        return [path.removeprefix(immich.ASSET) for path in self.asked]


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> Server:
    fake = Server()
    monkeypatch.setenv("LOGBOOK_IMMICH_URL", URL)
    monkeypatch.setenv("LOGBOOK_IMMICH_KEY", KEY)
    monkeypatch.setattr(immich, "_get", fake)
    monkeypatch.setattr(immich, "_sleep", lambda seconds: None)  # paced, never slept here
    return fake


def _review(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[str, str]:
    cli.main(["setup", "places", "review", *args])
    out, err = capsys.readouterr()
    return out, err


def _rows(out: str) -> dict[int, tuple[str, str]]:
    """proposal number → (its line, its evidence line)."""
    lines = out.splitlines()
    found = {}
    for n, line in enumerate(lines):
        words = line.split()
        if line.startswith("  ") and words and words[0].isdigit() and "→" in line:
            found[int(words[0])] = (line, lines[n + 1].strip())
    return found


def _spot(lat: float, lon: float) -> int:
    n = min(S, key=lambda i: places.distance_m(lat, lon, *S[i]))
    assert places.distance_m(lat, lon, *S[n]) < 30, (lat, lon, n)
    return n


# -- the names the photos hold ----------------------------------------------------------------------------


def test_an_unnamed_place_gains_the_name_its_photos_hold_counted_by_photo_and_source(
    lb: Logbook,
    server: Server,
    photos_library: Path,
    capsys: pytest.CaptureFixture[str],
    no_network: list[str],
) -> None:
    out, err = _review(capsys, "--ask-photos")
    rows = _rows(out)
    assert rows[3][0].endswith(f"→ {HARBOUR_TOWN}") and rows[3][1] == f"immich ×12: {HARBOUR_TOWN}"
    assert rows[7][0].endswith(f"→ {PLATFORM}") and rows[7][1] == f"photos ×3: {PLATFORM}"
    for n in (8, 9, 10, 11, 12):
        assert rows[n][0].endswith(f"→ {BLANK}") and rows[n][1] == "no source names it", "no photos there"
    assert rows[1][0].endswith(f"→ {CABIN}") and "×" not in rows[1][1], "a named one is not asked"
    assert sorted(server.ids) == sorted([*AT_S3, GONE]), "the photos at the blanks, by asset id alone"
    assert err.splitlines()[:3] == [
        "asking the photos about 7 places: up to 50 photos at each from each library, the nearest its"
        " centre first",
        "  immich: 13 photos; sending 13 asset ids to immich.test:2283, nothing else, at most 10 a second"
        " (about 2 s)",
        f"  photos: 4 photos; reading their places from the library at {MAC_LIBRARY}, on this machine",
    ]
    assert "  immich: 12 named a place, 1 not on the server" in err.splitlines()
    assert "  photos: 3 named a place, 1 not in the library" in err.splitlines()
    assert no_network == [], "the server is faked in process: no socket is ever opened"
    assert not (lb.root / "places.json").exists(), "nothing written"


def test_the_json_carries_the_photo_evidence_and_what_was_asked(
    lb: Logbook, server: Server, photos_library: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out, _err = _review(capsys, "--ask-photos", "--json")
    data = json.loads(out)
    third = data["proposals"][2]
    assert third["name"] == HARBOUR_TOWN
    [said] = third["evidence"]
    assert {k: v for k, v in said.items() if k != "lines"} == {
        "source": "immich",
        "origin": "library",
        "name": HARBOUR_TOWN,
        "grade": "city",
        "count": 12,
        "unit": "photo",
    }
    ids = {line["payload"]["asset_id"]: line["id"] for line in lb.lines() if line["kind"] == "photo"}
    assert said["lines"] == [ids[a] for a in AT_S3[:3]], "the record's photo lines, the nearest first"
    assert data["proposals"][6]["evidence"][0]["source"] == "apple-photos"
    assert data["proposals"][6]["evidence"][0]["grade"] == "name", "an area Photos named weighs as a name"
    assert data["asked_photos"] == [
        {
            "library": "immich",
            "where": "immich.test:2283",
            "photos": 13,
            "cached": 0,
            "asked": 13,
            "named": 12,
            "none": 0,
            "missing": 1,
            "not_asked": 0,
            "failed": None,
        },
        {
            "library": "apple-photos",
            "where": str(places_photos.store_of(None)),
            "photos": 4,
            "cached": 0,
            "asked": 4,
            "named": 3,
            "none": 0,
            "missing": 1,
            "not_asked": 0,
            "failed": None,
        },
    ]


def test_limit_asks_only_the_photos_nearest_each_centre(
    lb: Logbook, server: Server, photos_library: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out, err = _review(capsys, "--ask-photos", "--limit", "5")
    assert server.ids == AT_S3[:5], "the five nearest S3's centre, nearest first"
    assert _rows(out)[3][1] == f"immich ×5: {HARBOUR_TOWN}"
    assert err.splitlines()[0].startswith("asking the photos about 7 places: up to 5 photos at each")
    assert _rows(out)[7][1] == f"photos ×3: {PLATFORM}", "four at S7: under the limit"
    _review(capsys, "--ask-photos", "--limit", "1")
    assert server.ids == AT_S3[:5], "the nearest is answered from the cache"
    with pytest.raises(SystemExit) as e:
        cli.main(["setup", "places", "review", "--ask-photos", "--limit", "-1"])
    assert e.value.code == 2 and "--limit" in capsys.readouterr().err


def test_all_asks_about_the_places_that_have_a_name_too(
    lb: Logbook, server: Server, photos_library: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out, err = _review(capsys, "--ask-photos", "--all")
    assert sorted(server.ids) == sorted([*AT_S1, *AT_S3, GONE])
    line, evidence = _rows(out)[1]
    assert line.endswith(f"→ {CABIN}"), "two photos' city weighs less than three Timeline visits"
    assert f"immich ×2: {HARBOUR_TOWN}" in evidence
    assert err.splitlines()[0].startswith("asking the photos about 12 places:")


def test_near_and_top_ask_only_about_the_places_shown(
    lb: Logbook, server: Server, photos_library: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out, err = _review(capsys, "--ask-photos", "--top", "2")
    assert server.asked == [], "the first two have names; nothing to ask"
    assert "every place shown has a name" in err
    out, err = _review(capsys, "--ask-photos", "--near", "55.61,4.37", "--top", "3")
    assert sorted(_rows(out)) == [1, 2, 3], "the fourth column is more than 5 km east"
    assert sorted(server.ids) == sorted([*AT_S3, GONE]), "only S3 of the three shown is blank"
    assert err.splitlines()[0].startswith("asking the photos about 1 place:")
    assert not any(line.startswith("  photos:") for line in err.splitlines()), "S7 is not shown"


# -- what it costs, and what it keeps ---------------------------------------------------------------------


def test_the_cache_answers_a_second_review_and_a_stale_answer_is_asked_again(
    lb: Logbook, server: Server, photos_library: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first, _err = _review(capsys, "--ask-photos")
    asked = list(server.asked)
    second, err = _review(capsys, "--ask-photos")
    assert server.asked == asked, "every answer, a lost asset's too, came from the cache"
    assert second == first
    assert "  immich: 13 photos, 13 answered from the cache; nothing to ask" in err.splitlines()
    assert "  photos: 4 photos, 4 answered from the cache; nothing to ask" in err.splitlines()
    cache = places_photos.cache_path(lb.root)
    assert cache.parent == lb.root / "state"
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert data["ttl_days"] == places_photos.CACHE_TTL_DAYS == 30
    assert data["answers"]["immich"][AT_S3[0]]["place"] == {"city": HARBOUR_TOWN, "country": "Nordsjøen"}
    assert (
        data["answers"]["immich"][GONE]["place"] is None and data["answers"]["immich"][GONE]["found"] is False
    )
    old = (datetime.now(UTC) - timedelta(days=31)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for answer in data["answers"]["immich"].values():
        answer["at"] = old
    cache.write_text(json.dumps(data), encoding="utf-8")
    third, _err = _review(capsys, "--ask-photos")
    assert len(server.asked) == 2 * len(asked), "older than the TTL: asked again"
    assert third == first


def test_a_failing_immich_is_said_once_and_the_review_goes_on(
    lb: Logbook,
    server: Server,
    photos_library: Path,
    capsys: pytest.CaptureFixture[str],
    no_network: list[str],
) -> None:
    server.fail = True
    out, err = _review(capsys, "--ask-photos")
    failed = [line for line in err.splitlines() if "failed" in line]
    assert failed == [
        "  immich at immich.test:2283 failed: HTTP Error 500: Internal Server Error; 13 photos not asked,"
        " the review goes on without them"
    ]
    assert len(server.asked) == 1, "asked nothing more once it failed"
    rows = _rows(out)
    assert rows[3][0].endswith(f"→ {BLANK}") and rows[7][0].endswith(f"→ {PLATFORM}"), "Photos still asked"
    assert out.splitlines()[-1].startswith("nothing written")
    data = json.loads(places_photos.cache_path(lb.root).read_text(encoding="utf-8"))
    assert data["answers"].get("immich", {}) == {}, "a failure is never cached"
    assert no_network == []


def test_a_server_or_library_that_is_not_there_is_said_and_the_review_goes_on(
    lb: Logbook, capsys: pytest.CaptureFixture[str], no_network: list[str]
) -> None:
    out, err = _review(capsys, "--ask-photos")
    assert "  immich: 13 photos; 13 not asked: set LOGBOOK_IMMICH_URL and LOGBOOK_IMMICH_KEY" in err
    assert (
        f"  photos: 4 photos; 4 not asked: no Photos library at {MAC_FOLDER} (--photos-library PATH)" in err
    )
    assert out.splitlines()[0].startswith("12 places observed")
    assert _rows(out)[3][0].endswith(f"→ {BLANK}")
    assert no_network == []


def test_photos_library_names_another_library_and_a_disabled_immich_is_never_asked(
    lb: Logbook, server: Server, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    elsewhere = library(tmp_path / "elsewhere", library_assets())
    policy = lb.root / "policy" / "import.json"
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text(
        json.dumps({"disabled": [{"source": "immich", "reason": "the server is moving"}]}), encoding="utf-8"
    )
    out, err = _review(capsys, "--ask-photos", "--photos-library", str(elsewhere))
    assert server.asked == []
    assert "13 not asked: immich is disabled in policy/import.json (the server is moving)" in err
    assert _rows(out)[7][0].endswith(f"→ {PLATFORM}")


def test_only_the_configured_immich_host_is_ever_contacted(
    lb: Logbook,
    photos_library: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    loopback: Callable[[], Loopback],
) -> None:
    fake = loopback()
    out, _err = _review(capsys, "--ask-photos")
    assert fake.connections, "the lookups went over a real socket"
    assert set(fake.connections) == {fake.address}, "every connection to the configured host and port"
    assert set(fake.lookups) <= {fake.address[0]}, "no name looked up but the configured host's"
    assert sorted(fake.paths) == sorted(f"/api/assets/{a}" for a in [*AT_S3, GONE])
    assert fake.keys == {KEY}
    assert _rows(out)[3][0].endswith(f"→ {HARBOUR_TOWN}")
    assert not fake.bodies, "a GET: no body, no coordinate"


# -- the owner's say, as before ---------------------------------------------------------------------------


def test_a_name_from_the_photos_is_accepted_as_any_other(
    lb: Logbook, server: Server, photos_library: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = int(lb.meta["seq"])
    with pytest.raises(SystemExit) as e:
        cli.main(["setup", "places", "review", "--accept", "3"])
    assert e.value.code == 2 and "proposal 3 has no name" in capsys.readouterr().err, "unchanged without"
    out, _err = _review(capsys, "--ask-photos", "--accept", "3")
    assert f"accepted 3 → {HARBOUR_TOWN}" in out
    written = json.loads((lb.root / "places.json").read_text(encoding="utf-8"))
    assert (
        set(written) == {HARBOUR_TOWN}
        and _spot(written[HARBOUR_TOWN]["lat"], written[HARBOUR_TOWN]["lon"]) == 3
    )
    assert written[HARBOUR_TOWN]["kind"] == "other"
    assert int(Logbook(lb.root).meta["seq"]) == before + 1, "one naming note, as `places name` writes"
    out, _err = _review(capsys, "--ask-photos", "--reject", "6")
    assert f"rejected 6 ≠ {PLATFORM}" in out, "S7 is the sixth now that S3 is named"
    state = json.loads((lb.root / "state" / "places-review.json").read_text(encoding="utf-8"))
    assert [r["name"] for r in state["rejected"]] == [PLATFORM]
    line, evidence = _rows(_review(capsys, "--ask-photos")[0])[6]
    assert line.endswith(f"→ {BLANK}") and evidence == f"photos ×3: {PLATFORM}", (
        "rejected; the evidence stays"
    )


def test_name_asks_nothing_and_limit_zero_asks_about_no_photo(
    lb: Logbook, server: Server, photos_library: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out, err = _review(capsys, "--ask-photos", "--name", "3", "Base")
    assert "accepted 3 → Base" in out and err == "" and server.asked == [], "the owner's own name"
    with pytest.raises(SystemExit) as e:
        cli.main(["setup", "places", "review", "--ask-photos", "--accept", "1,40"])
    assert e.value.code == 2 and "no proposal 40" in capsys.readouterr().err and server.asked == []
    _out, err = _review(capsys, "--ask-photos", "--limit", "0")
    assert err == "asking the photos about 6 places: --limit 0 asks about no photo\n" and server.asked == []


# -- without the flag -------------------------------------------------------------------------------------


def _lf(text: str) -> str:
    """`text` with every line ending as `\\n`: a Windows checkout gives the fixture CRLF."""
    return text.replace("\r\n", "\n")


def _fixture_text(name: str) -> str:
    return _lf((FIXTURES / name).read_text(encoding="utf-8"))


def test_without_the_flag_the_review_is_byte_for_byte_what_it_was(
    lb: Logbook,
    server: Server,
    photos_library: Path,
    capsys: pytest.CaptureFixture[str],
    no_network: list[str],
) -> None:
    """`tests/fixtures/places-review/` is what #255 printed for this record, before --ask-photos was."""
    out, err = _review(capsys)
    assert _lf(out) == _fixture_text("review.txt") and err == ""
    out, err = _review(capsys, "--near", "55.61,4.335", "--top", "2")
    assert _lf(out) == _fixture_text("review-near-top.txt") and err == ""
    data = json.loads(_review(capsys, "--json")[0])
    data.pop("head")
    for p in data["proposals"]:
        p.pop("lines")
        for e in p["evidence"]:
            e.pop("lines")
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    assert text.encode("utf-8") == (FIXTURES / "review.json").read_bytes()
    assert server.asked == [] and no_network == []
    assert not places_photos.cache_path(lb.root).exists()


def test_the_flags_that_go_with_ask_photos_are_refused_without_it(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    for flags in (["--all"], ["--limit", "5"], ["--photos-library", "Pictures"]):
        with pytest.raises(SystemExit) as e:
            cli.main(["setup", "places", "review", *flags])
        assert e.value.code == 2 and "--ask-photos" in capsys.readouterr().err, flags


# -- the loopback server and the connections it is the only one to see -------------------------------------


class Loopback:
    """`GET /api/assets/{id}` over HTTP on 127.0.0.1, and a guard on the process's sockets: every
    connect and every name lookup recorded; any but this server's refused."""

    def __init__(self) -> None:
        self.paths: list[str] = []
        self.keys: set[str] = set()
        self.bodies: list[bytes] = []
        self.connections: list[tuple[str, int]] = []
        self.lookups: list[str] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def do_GET(self) -> None:
                fake.paths.append(self.path)
                fake.keys.add(str(self.headers.get("x-api-key")))
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    fake.bodies.append(self.rfile.read(length))
                doc = immich_asset(self.path.removeprefix(immich.ASSET))
                body = json.dumps(doc or {"message": "Not found"}).encode("utf-8")
                self.send_response(200 if doc else 404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.address: tuple[str, int] = self.server.server_address[:2]  # type: ignore[assignment]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://{self.address[0]}:{self.address[1]}"


class Refused(RuntimeError):
    """A connection to anything but the loopback Immich."""


@pytest.fixture
def loopback(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[], Loopback]]:
    running: list[Loopback] = []

    def start() -> Loopback:
        fake = Loopback()
        fake.thread.start()
        running.append(fake)
        monkeypatch.setenv("LOGBOOK_IMMICH_URL", fake.url)
        monkeypatch.setenv("LOGBOOK_IMMICH_KEY", KEY)
        monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")  # a shell's proxy never sees the fake
        monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
        monkeypatch.setattr(immich, "_sleep", lambda seconds: None)
        connect, connect_ex, getaddrinfo = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo

        def watched(real: Callable[..., Any]) -> Callable[..., Any]:
            def guard(self: socket.socket, address: Any) -> Any:
                where = (str(address[0]), int(address[1])) if isinstance(address, tuple) else address
                fake.connections.append(where)
                if where != fake.address:
                    raise Refused(f"a connection to {address!r}")
                return real(self, address)

            return guard

        def lookup(host: Any, *args: Any, **kwargs: Any) -> Any:
            fake.lookups.append(str(host))
            if str(host) != fake.address[0]:
                raise Refused(f"a lookup of {host!r}")
            return getaddrinfo(host, *args, **kwargs)

        monkeypatch.setattr(socket.socket, "connect", watched(connect))
        monkeypatch.setattr(socket.socket, "connect_ex", watched(connect_ex))
        monkeypatch.setattr(socket, "getaddrinfo", lookup)
        return fake

    yield start
    for fake in running:
        fake.server.shutdown()
        fake.server.server_close()
