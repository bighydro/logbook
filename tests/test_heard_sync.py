"""`sync heard` (RFC 0046): the words of the podcasts and videos the owner played, one `heard/v1` line
per work and text source, the text in the attachment store exactly as it came. A feed's transcript in
each format podcasting 2.0 allows, fetched once under a cap per run and a polite delay, a failed fetch
counted and not retried in a storm; Apple Podcasts' cached TTML matched to its episode through the
Podcasts store; a video's captions from the owner's folder; opt-in through the same settings as every
source, and a first scheduled run bounded to two weeks. No network: `urlopen` is a fake that answers
for example.org and `socket.getaddrinfo` a fake that resolves nothing for real; invented podcasts,
videos and the Oslo persona, who does not exist."""

from __future__ import annotations

import io
import json
import socket
import sqlite3
import urllib.error
from datetime import UTC, date, datetime
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from logbook import cli
from logbook.commands import parser
from logbook.commands import sync as sync_commands
from logbook.contrib import first_run
from logbook.contrib.adapters import heard as step
from logbook.core import heard
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
FEED = "https://havn.example.org/podden"

VTT = (
    b"WEBVTT\nLanguage: nb\n\n"
    b"1\n00:00:00.000 --> 00:00:04.000\n<v Ola Nordmann>Velkommen til Havnepodden.\n\n"
    b"2\n00:00:04.000 --> 00:00:09.500\nI dag snakker vi om \xc3\xb8stkaia.\n"
)
SRT = (
    b"1\n00:00:00,000 --> 00:00:03,000\nThe east berth is full.\n\n"
    b"2\n00:00:03,000 --> 00:00:06,000\nThe tide turns at noon.\n"
)
JSON = json.dumps(
    {
        "version": "1.0.0",
        "segments": [
            {"speaker": "Kari Nordmann", "startTime": 0.5, "endTime": 2.0, "body": "Knots first,"},
            {"speaker": "Kari Nordmann", "startTime": 2.0, "endTime": 4.0, "body": "then the splice."},
        ],
    }
).encode("utf-8")
TEXT = b"Per Hansen reads the harbour notices.\nThe ferry leaves at seven.\n"
HTML = b"<!DOCTYPE html><html><body><p>A transcript page.</p></body></html>"


def _ttml(lang: str, *paragraphs: tuple[str, ...]) -> bytes:
    body = "".join(
        "<p begin='0.0' end='1.0'><span podcasts:unit='sentence'>"
        + "".join(f"<span podcasts:unit='word'>{w}</span>" for w in words)
        + "</span></p>"
        for words in paragraphs
    )
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<tt xmlns='http://www.w3.org/ns/ttml'"
        " xmlns:podcasts='http://podcasts.apple.com/transcript-ttml-internal'"
        f" xml:lang='{lang}'><body><div>{body}</div></body></tt>"
    ).encode()


class FakeWeb:
    """`urlopen` for example.org: each URL answers what `routes` says (bytes and headers, or an HTTP
    status), and every request is recorded with its headers. Anything else is a refused connection."""

    def __init__(self, routes: dict[str, tuple[bytes, dict[str, str]] | int]) -> None:
        self.routes = routes
        self.requests: list[str] = []
        self.headers: list[dict[str, str]] = []

    def __call__(self, request: Any, timeout: float) -> Any:
        url = request.full_url
        self.requests.append(url)
        self.headers.append(dict(request.header_items()))
        answer = self.routes.get(url)
        if answer is None:
            raise urllib.error.URLError("connection refused")
        if isinstance(answer, int):
            raise urllib.error.HTTPError(url, answer, "refused", Message(), io.BytesIO(b""))
        body, headers = answer
        return _Response(body, headers)


class _Response:
    def __init__(self, body: bytes, headers: dict[str, str]) -> None:
        self._body = io.BytesIO(body)
        self.headers = Message()
        for key, value in headers.items():
            self.headers[key] = value

    def read(self, n: int = -1) -> bytes:
        return self._body.read(n)

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


@pytest.fixture
def lb(tmp_path: Path) -> Logbook:
    import os

    return Logbook.init(Path(os.environ["LOGBOOK_HOME"]), TZ)


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr(step, "sleep", slept.append)
    return slept


PUBLIC = "93.184.215.14"  # a public address: Python counts the documentation ranges as private


class FakeResolver:
    """`socket.getaddrinfo` with nothing resolved for real: a host in `answers` gets those addresses,
    a host in `unresolved` is not found, and any other host the one public address. Every host asked
    is recorded."""

    def __init__(self, answers: dict[str, tuple[str, ...]], unresolved: tuple[str, ...]) -> None:
        self.answers = answers
        self.unresolved = unresolved
        self.asked: list[str] = []

    def __call__(self, host: str, port: Any, *args: Any, **kwargs: Any) -> list[tuple[Any, ...]]:
        self.asked.append(host)
        if host in self.unresolved:
            raise socket.gaierror("nodename nor servname provided, or not known")
        found: list[tuple[Any, ...]] = []
        for address in self.answers.get(host, (PUBLIC,)):
            if ":" in address:
                found.append((socket.AF_INET6, socket.SOCK_STREAM, 6, "", (address, port, 0, 0)))
            else:
                found.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port)))
        return found


def _resolve(
    monkeypatch: pytest.MonkeyPatch,
    answers: dict[str, tuple[str, ...]] | None = None,
    unresolved: tuple[str, ...] = (),
) -> FakeResolver:
    resolver = FakeResolver(answers or {}, unresolved)
    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    return resolver


def _web(monkeypatch: pytest.MonkeyPatch, routes: dict[str, tuple[bytes, dict[str, str]] | int]) -> FakeWeb:
    web = FakeWeb(routes)
    monkeypatch.setattr(step, "urlopen", web)
    _resolve(monkeypatch)  # every host of the fake web is a public one
    return web


def _listen(lb: Logbook, at: str, uuid: str, title: str, transcript: str | None = None) -> str:
    payload: dict[str, Any] = {
        "schema": "listen/v1",
        "raw_id": f"apple-podcasts:{uuid}@{at}",
        "media": "episode",
        "title": title,
        "show": "Havnepodden",
        "service": "apple-podcasts",
    }
    if transcript is not None:
        payload["extra"] = {"transcript_url": transcript}
    return str(lb.append(at, "apple-podcasts", "listen", 2, payload, tz=TZ)["id"])


def _watch(lb: Logbook, at: str, video: str, title: str) -> str:
    payload = {
        "schema": "watch/v1",
        "raw_id": f"youtube:{at}:{video}",
        "action": "watched",
        "title": title,
        "url": f"https://www.youtube.com/watch?v={video}",
        "video_id": video,
        "channel": {"name": "Knots by Ola"},
        "service": "youtube",
    }
    return str(lb.append(at, "google-takeout", "watch", 2, payload, tz=TZ)["id"])


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    try:
        cli.main(list(args))
    except SystemExit as e:
        status = int(e.code or 0)
    else:
        status = 0
    out = capsys.readouterr()
    return status, out.out, out.err


def _heard(lb: Logbook) -> list[dict[str, Any]]:
    return [dict(line) for line in lb.lines() if line["kind"] == heard.KIND]


def _stored(lb: Logbook, line: dict[str, Any]) -> bytes:
    return (lb.root / "attachments" / line["payload"]["text"]["sha256"]).read_bytes()


# -- feed: a transcript in each format ----------------------------------------------------------------


def test_a_feed_transcript_in_each_format_is_stored_as_it_came_and_named_by_one_line(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], sleeps: list[float]
) -> None:
    ids = {
        "vtt": _listen(lb, "2026-10-14T06:40:00Z", "EP-1", "Episode 12: the east berth", f"{FEED}/12.vtt"),
        "srt": _listen(lb, "2026-10-14T07:40:00Z", "EP-2", "Episode 13: the tide", f"{FEED}/13"),
        "json": _listen(lb, "2026-10-14T08:40:00Z", "EP-3", "Episode 14: knots", f"{FEED}/14.json"),
        "text": _listen(lb, "2026-10-14T09:40:00Z", "EP-4", "Episode 15: notices", f"{FEED}/15.txt"),
    }
    web = _web(
        monkeypatch,
        {
            f"{FEED}/12.vtt": (VTT, {"Content-Type": "text/plain"}),  # a server that says text for WebVTT
            f"{FEED}/13": (SRT, {"Content-Type": "application/srt", "Content-Language": "en"}),
            f"{FEED}/14.json": (JSON, {"Content-Type": "application/json", "Content-Language": "en-GB"}),
            f"{FEED}/15.txt": (TEXT, {}),
        },
    )
    monkeypatch.setenv("LOGBOOK_HEARD", "feed")

    status, out, err = _run(capsys, "sync", "heard")

    assert status == 0, err
    assert "heard: 4 new lines of 4 seen" in out
    lines = {line["payload"]["format"]: line for line in _heard(lb)}
    assert set(lines) == {"vtt", "srt", "json", "text"}
    bodies = {"vtt": VTT, "srt": SRT, "json": JSON, "text": TEXT}
    media = {
        "vtt": "text/vtt",
        "srt": "application/x-subrip",
        "json": "application/json",
        "text": "text/plain",
    }
    language = {"vtt": "nb", "srt": "en", "json": "en-GB", "text": "und"}
    for fmt, line in lines.items():
        p = line["payload"]
        assert line["tier"] == 2 and line["source"] == "heard" and line["kind"] == "heard"
        assert p["schema"] == "heard/v1" and p["of"] == ids[fmt] and p["of_kind"] == "listen"
        assert p["media"] == "episode" and p["by"] == "Havnepodden" and p["text_source"] == "feed"
        assert p["language"] == language[fmt]
        assert p["text"]["media_type"] == media[fmt] and p["text"]["bytes"] == len(bodies[fmt])
        assert _stored(lb, line) == bodies[fmt]  # exactly as fetched
        assert p["url"].startswith(FEED) and p["raw_id"].startswith("heard:feed:")
        assert p["words"] > 0 and p["chars"] > 0
    listens = {str(line["id"]): line for line in lb.lines() if line["kind"] == "listen"}
    assert all(line["at"] == listens[line["payload"]["of"]]["at"] for line in lines.values())
    assert heard.words_of(VTT, "vtt") == "Velkommen til Havnepodden.\nI dag snakker vi om østkaia."
    assert heard.words_of(JSON, "json") == "Knots first,\nthen the splice."
    assert lines["vtt"]["payload"]["words"] == 9
    assert len(web.requests) == 4
    assert all("openlogbook/" in h.get("User-agent", "") for h in web.headers)
    assert not any("Cookie" in h or "Referer" in h or "Authorization" in h for h in web.headers)
    assert sleeps == [2.0, 2.0, 2.0]  # the polite delay, between two fetches, never before the first


def test_a_second_run_fetches_nothing_again_and_a_replayed_episode_has_one_text(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], sleeps: list[float]
) -> None:
    first = _listen(lb, "2026-10-14T06:40:00Z", "EP-1", "Episode 12: the east berth", f"{FEED}/12.vtt")
    _listen(
        lb, "2026-10-16T06:40:00Z", "EP-1", "Episode 12: the east berth", f"{FEED}/12.vtt"
    )  # played again
    web = _web(monkeypatch, {f"{FEED}/12.vtt": (VTT, {"Content-Type": "text/vtt"})})
    monkeypatch.setenv("LOGBOOK_HEARD", "feed")

    assert _run(capsys, "sync", "heard")[0] == 0
    (line,) = _heard(lb)
    assert line["payload"]["of"] == first and len(web.requests) == 1

    _listen(lb, "2026-10-18T06:40:00Z", "EP-1", "Episode 12: the east berth", f"{FEED}/12.vtt")  # and again
    status, out, _ = _run(capsys, "sync", "heard")
    assert status == 0 and "heard: 0 new lines of 0 seen" in out
    status, out, _ = _run(capsys, "sync", "heard", "--since", "2026-01-01T00:00:00Z")  # the whole history
    assert status == 0 and "0 new lines" in out
    assert len(web.requests) == 1  # never fetched again
    assert len(_heard(lb)) == 1


def test_a_failed_fetch_is_a_counted_skip_noted_and_never_a_retry_storm(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], sleeps: list[float]
) -> None:
    _listen(lb, "2026-10-14T06:00:00Z", "EP-1", "Gone", f"{FEED}/gone.vtt")
    _listen(lb, "2026-10-14T07:00:00Z", "EP-2", "A page", f"{FEED}/page.html")
    _listen(lb, "2026-10-14T08:00:00Z", "EP-3", "Fine", f"{FEED}/fine.vtt")
    _listen(lb, "2026-10-14T09:00:00Z", "EP-4", "Nowhere", "https://nowhere.example.org/t.vtt")
    web = _web(
        monkeypatch,
        {
            f"{FEED}/gone.vtt": 404,
            f"{FEED}/page.html": (HTML, {"Content-Type": "text/html; charset=utf-8"}),
            f"{FEED}/fine.vtt": (VTT, {"Content-Type": "text/vtt"}),
        },
    )
    monkeypatch.setenv("LOGBOOK_HEARD", "feed")

    status, out, err = _run(capsys, "sync", "heard")

    assert status == 0, err  # one dead transcript never fails the run
    assert "heard: 1 new lines of 1 seen" in out
    assert "skipped 2 fetch failed, 1 html" in out
    assert len(web.requests) == 4
    cache = json.loads((lb.root / "state" / "heard-cache.json").read_text(encoding="utf-8"))
    assert set(cache["failed"]) == {
        f"{FEED}/gone.vtt",
        f"{FEED}/page.html",
        "https://nowhere.example.org/t.vtt",
    }

    status, out, _ = _run(capsys, "sync", "heard", "--since", "2026-10-01T00:00:00Z")
    assert status == 0 and "skipped 3 failed before" in out
    assert len(web.requests) == 4  # the same day: nothing tried again

    config = step.Config(sources=("feed",))
    lines = sync_commands._lines(lb)
    counts: dict[str, int] = {}
    for day in ("2027-01-01", "2027-01-08"):  # weeks later, then a week on: tried again, still dead
        drafts = list(
            step.pull(
                config,
                None,
                counts=counts,
                lines=lines,
                cache=cache,
                store=lb.attach,
                today=date.fromisoformat(day),
            )
        )
        assert drafts and all(d["payload"]["title"] == "Fine" for d in drafts)
    assert cache["failed"][f"{FEED}/gone.vtt"]["count"] == 3
    before = len(web.requests)
    list(
        step.pull(
            config, None, counts=counts, lines=lines, cache=cache, store=lb.attach, today=date(2027, 6, 1)
        )
    )
    assert f"{FEED}/gone.vtt" not in web.requests[before:]  # three failures: given up, never again


def test_the_cap_per_run_stops_there_and_the_next_run_carries_on(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], sleeps: list[float]
) -> None:
    routes: dict[str, tuple[bytes, dict[str, str]] | int] = {}
    for n in range(5):
        _listen(lb, f"2026-10-1{n}T06:00:00Z", f"EP-{n}", f"Episode {n}", f"{FEED}/{n}.vtt")
        routes[f"{FEED}/{n}.vtt"] = (
            VTT.replace(b"stkaia", f"stkaia {n}".encode()),
            {"Content-Type": "text/vtt"},
        )
    web = _web(monkeypatch, routes)
    monkeypatch.setenv("LOGBOOK_HEARD", "feed")
    monkeypatch.setenv("LOGBOOK_HEARD_MAX_FETCHES", "2")
    monkeypatch.setenv("LOGBOOK_HEARD_DELAY_S", "0.5")

    status, out, _ = _run(capsys, "sync", "heard")
    assert status == 0 and "heard: 2 new lines" in out and "3 left for next run" in out
    assert [line["payload"]["title"] for line in _heard(lb)] == ["Episode 0", "Episode 1"]
    assert len(web.requests) == 2 and sleeps == [0.5]

    status, out, _ = _run(capsys, "sync", "heard")
    assert status == 0 and "heard: 2 new lines" in out
    status, out, _ = _run(capsys, "sync", "heard")
    assert status == 0 and "heard: 1 new lines" in out
    assert [line["payload"]["title"] for line in _heard(lb)] == [f"Episode {n}" for n in range(5)]
    assert len(web.requests) == 5


def test_a_429_ends_the_runs_fetching(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], sleeps: list[float]
) -> None:
    for n in range(3):
        _listen(lb, f"2026-10-1{n}T06:00:00Z", f"EP-{n}", f"Episode {n}", f"{FEED}/{n}.vtt")
    web = _web(monkeypatch, {f"{FEED}/0.vtt": 429, f"{FEED}/1.vtt": (VTT, {}), f"{FEED}/2.vtt": (VTT, {})})
    monkeypatch.setenv("LOGBOOK_HEARD", "feed")
    status, out, _ = _run(capsys, "sync", "heard")
    assert status == 0 and "1 rate limited" in out and "2 left for next run" in out
    assert len(web.requests) == 1 and not _heard(lb)


def test_a_dry_run_fetches_nothing_and_writes_nothing(
    lb: Logbook,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    no_network: list[str],
) -> None:
    _listen(lb, "2026-10-14T06:40:00Z", "EP-1", "Episode 12: the east berth", f"{FEED}/12.vtt")
    monkeypatch.setenv("LOGBOOK_HEARD", "feed")
    before = lb.meta["seq"]
    status, out, _ = _run(capsys, "sync", "heard", "--dry-run")
    assert status == 0 and "dry run, nothing written" in out and "1 would fetch" in out
    assert no_network == [] and lb.meta["seq"] == before
    assert not (lb.root / "attachments").exists() or not any((lb.root / "attachments").iterdir())


# -- apple: the TTML Apple Podcasts cached ---------------------------------------------------------------


def _podcasts_store(
    path: Path, rows: list[tuple[str, str | None, int | None]], columns: tuple[str, ...]
) -> Path:
    """A synthetic MTLibrary.sqlite: ZMTEPISODE with the columns the step may read."""
    path.parent.mkdir(parents=True, exist_ok=True)
    types = {"ZTRANSCRIPTIDENTIFIER": "TEXT", "ZSTORETRACKID": "INTEGER"}
    declared = "".join(f", {c} {types[c]}" for c in columns)
    con = sqlite3.connect(path)
    con.execute(
        f"CREATE TABLE ZMTEPISODE (Z_PK INTEGER, ZTITLE TEXT, ZUUID TEXT, ZLASTDATEPLAYED REAL{declared})"
    )
    for n, (uuid, identifier, track) in enumerate(rows):
        values = {"ZTRANSCRIPTIDENTIFIER": identifier, "ZSTORETRACKID": track}
        names = "".join(f", {c}" for c in columns)
        marks = ", ?" * len(columns)
        con.execute(
            f"INSERT INTO ZMTEPISODE (Z_PK, ZTITLE, ZUUID, ZLASTDATEPLAYED{names})"
            f" VALUES (?, ?, ?, ?{marks})",
            (n, f"Episode {n}", uuid, 800_000_000.0, *(values[c] for c in columns)),
        )
    con.commit()
    con.close()
    return path


def test_an_apple_ttml_is_matched_to_its_episode_through_the_store_and_read_where_it_lies(
    lb: Logbook,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    no_network: list[str],
) -> None:
    container = tmp_path / "container"
    ttml = container / "Library" / "Cache" / "Assets" / "TTML"
    by_identifier = ttml / "PodcastContent101" / "v4" / "a1" / "transcript_1000000101.ttml-1000000101.ttml"
    by_track = ttml / "PodcastContent102" / "transcript_1000000102.ttml"
    stray = ttml / "PodcastContent103" / "transcript_1000000999.ttml"
    for path, text in (
        (
            by_identifier,
            _ttml("nb-NO", ("Velkommen", "til", "Havnepodden", "."), ("Ola", "Nordmann", "her", ".")),
        ),
        (by_track, _ttml("en-GB", ("Knots", "and", "splices", "."))),
        (stray, _ttml("en", ("Nobody", "played", "this", "."))),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text)
    store = _podcasts_store(
        tmp_path / "MTLibrary.sqlite",
        [
            ("EP-A", "PodcastContent101/v4/a1/transcript_1000000101.ttml", 1000000101),
            ("EP-B", None, 1000000102),
            ("EP-C", "https://havn.example.org/podden/c.vtt", None),  # a public URL is feed's, not apple's
        ],
        ("ZTRANSCRIPTIDENTIFIER", "ZSTORETRACKID"),
    )
    a = _listen(lb, "2026-10-14T06:40:00Z", "EP-A", "Episode 12: the east berth")
    b = _listen(lb, "2026-10-14T07:40:00Z", "EP-B", "Knots weekly")
    _listen(lb, "2026-10-14T08:40:00Z", "EP-C", "No Apple transcript")
    monkeypatch.setenv("LOGBOOK_HEARD", "apple")
    monkeypatch.setenv("LOGBOOK_HEARD_TTML_DIR", str(ttml))
    monkeypatch.setenv("LOGBOOK_PODCASTS_DB", str(store))

    status, out, err = _run(capsys, "sync", "heard")

    assert status == 0, err
    assert no_network == []
    lines = {line["payload"]["of"]: line for line in _heard(lb)}
    assert set(lines) == {a, b}
    first, second = lines[a]["payload"], lines[b]["payload"]
    assert (
        first["raw_id"] == "heard:apple:EP-A"
        and first["text_source"] == "apple"
        and first["format"] == "ttml"
    )
    assert first["language"] == "nb-NO" and first["text"]["media_type"] == "application/ttml+xml"
    assert second["language"] == "en-GB" and second["extra"]["file"] == "transcript_1000000102.ttml"
    assert "url" not in first and str(tmp_path) not in json.dumps(first)  # no folder of this machine
    assert heard.words_of(_stored(lb, lines[a]), "ttml") == "Velkommen til Havnepodden.\nOla Nordmann her."
    assert "1 no apple transcript" in out


def test_a_store_without_the_columns_matches_nothing_and_says_so_once(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ttml = tmp_path / "TTML"
    ttml.mkdir()
    (ttml / "transcript_1.ttml").write_bytes(_ttml("en", ("Hello",)))
    store = _podcasts_store(tmp_path / "MTLibrary.sqlite", [("EP-A", None, None)], ())
    _listen(lb, "2026-10-14T06:40:00Z", "EP-A", "Episode")
    _listen(lb, "2026-10-14T07:40:00Z", "EP-B", "Episode")
    monkeypatch.setenv("LOGBOOK_HEARD", "apple")
    monkeypatch.setenv("LOGBOOK_HEARD_TTML_DIR", str(ttml))
    monkeypatch.setenv("LOGBOOK_PODCASTS_DB", str(store))
    status, _, err = _run(capsys, "sync", "heard")
    assert status == 0 and not _heard(lb)
    assert err.count("neither ZTRANSCRIPTIDENTIFIER nor ZSTORETRACKID") == 1
    assert "Traceback" not in err


# -- captions: the owner's folder --------------------------------------------------------------------------


def test_captions_come_from_the_owners_folder_named_by_video_id_never_fetched(
    lb: Logbook,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    no_network: list[str],
) -> None:
    folder = tmp_path / "Captions"
    folder.mkdir()
    (folder / "aB3dE5fG7hI.en.vtt").write_bytes(
        b"WEBVTT\n\n00:00.000 --> 00:02.000\nToday we splice a rope.\n"
    )
    (folder / "aB3dE5fG7hI.nb.vtt").write_bytes(
        b"WEBVTT\n\n00:00.000 --> 00:02.000\nI dag spleiser vi et tau.\n"
    )
    (folder / "zZ9yY8xX7wV.vtt").write_bytes(b"WEBVTT\nLanguage: en\n\n00:00.000 --> 00:01.000\nA bowline.\n")
    (folder / "notes.txt").write_text("not a caption", encoding="utf-8")
    first = _watch(lb, "2026-10-14T19:05:00Z", "aB3dE5fG7hI", "Splicing a three-strand rope")
    second = _watch(lb, "2026-10-14T20:05:00Z", "zZ9yY8xX7wV", "The bowline")
    _watch(lb, "2026-10-14T21:05:00Z", "qQ1wW2eE3rT", "No captions here")
    monkeypatch.setenv("LOGBOOK_HEARD", "captions")
    monkeypatch.setenv("LOGBOOK_HEARD_CAPTIONS_DIR", str(folder))
    monkeypatch.setenv("LOGBOOK_HEARD_LANGUAGES", "nb,en")

    status, out, err = _run(capsys, "sync", "heard")

    assert status == 0, err
    assert no_network == []
    lines = {line["payload"]["of"]: line["payload"] for line in _heard(lb)}
    assert set(lines) == {first, second}
    assert lines[first]["language"] == "nb" and lines[first]["raw_id"] == "heard:captions:aB3dE5fG7hI"
    assert (
        lines[first]["media"] == "video"
        and lines[first]["of_kind"] == "watch"
        and lines[first]["by"] == "Knots by Ola"
    )
    assert lines[first]["extra"] == {"file": "aB3dE5fG7hI.nb.vtt"}
    assert lines[second]["language"] == "en"  # from the file's own header
    assert "1 captions other language" in out and "1 no captions" in out


def test_captions_need_their_folder(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOGBOOK_HEARD", "captions")
    status, _, err = _run(capsys, "sync", "heard")
    assert status == 2 and "LOGBOOK_HEARD_CAPTIONS_DIR" in err
    monkeypatch.setenv("LOGBOOK_HEARD", "feed,local")
    status, _, err = _run(capsys, "sync", "heard")
    assert status == 2 and "`local` is reserved" in err


# -- the tier, and the settings every source uses -----------------------------------------------------


def test_every_heard_line_is_tier_2_and_meets_the_rfcs_schema(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], sleeps: list[float]
) -> None:
    from jsonschema import Draft202012Validator

    rfc = (Path(__file__).resolve().parents[1] / "rfcs" / "0046-what-you-heard.md").read_text(
        encoding="utf-8"
    )
    schema = json.loads(rfc.split("```json\n", 1)[1].split("```", 1)[0])
    _listen(lb, "2026-10-14T06:40:00Z", "EP-1", "Episode 12", f"{FEED}/12.vtt")
    _web(monkeypatch, {f"{FEED}/12.vtt": (VTT, {"Content-Type": "text/vtt"})})
    monkeypatch.setenv("LOGBOOK_HEARD", "feed")
    assert _run(capsys, "sync", "heard")[0] == 0
    (line,) = _heard(lb)
    assert line["tier"] == heard.TIER == 2
    assert not list(Draft202012Validator(schema).iter_errors(line["payload"]))


def test_unset_it_is_skipped_by_sync_all_and_disabled_it_is_skipped_by_name(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from logbook.contrib import adapters

    monkeypatch.setattr(adapters, "live_adapters", lambda: [step])  # heard alone, the source under test
    status, out, _ = _run(capsys, "sync", "--all")
    assert status == 0 and "heard: LOGBOOK_HEARD not set; skipped" in out
    status, _, err = _run(capsys, "sync", "heard")
    assert status == 2 and "set LOGBOOK_HEARD" in err

    (lb.root / "policy" / "import.json").write_text(
        json.dumps({"disabled": [{"source": "heard", "reason": "not now"}]}), encoding="utf-8"
    )
    monkeypatch.setenv("LOGBOOK_HEARD", "feed")
    status, out, _ = _run(capsys, "sync", "heard")
    assert status == 0 and "heard: disabled (not now); skipped" in out
    status, out, _ = _run(capsys, "sync", "--all")
    assert status == 0 and "heard  skipped (disabled)" in out


def test_its_first_scheduled_run_reads_the_last_two_weeks(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], sleeps: list[float]
) -> None:
    _listen(lb, "2026-09-01T06:00:00Z", "EP-OLD", "Old episode", f"{FEED}/old.vtt")
    _listen(lb, "2026-10-14T06:00:00Z", "EP-NEW", "New episode", f"{FEED}/new.vtt")
    web = _web(monkeypatch, {f"{FEED}/old.vtt": (VTT, {}), f"{FEED}/new.vtt": (VTT, {})})
    monkeypatch.setenv("LOGBOOK_HEARD", "feed")
    a = parser.build_parser().parse_args(["sync", "heard"])
    a.first_run = first_run.window(lb.meta, datetime(2026, 10, 20, 12, 0, tzinfo=UTC))
    sync_commands._sync_source(a)
    out = capsys.readouterr().out
    assert "heard: first scheduled run read from 2026-10-07" in out
    assert web.requests == [f"{FEED}/new.vtt"]
    assert [line["payload"]["title"] for line in _heard(lb)] == ["New episode"]


def test_the_watermark_is_the_listens_time_and_a_run_looks_back_two_weeks() -> None:
    config = step.Config(sources=("feed",))
    assert step.watermark({"at": "2026-10-14T06:40:00Z"}) == "2026-10-14T06:40:00Z"
    assert step.resume(config, "2026-10-14T06:40:00Z") == "2026-09-30T06:40:00Z"


def test_the_pull_refuses_without_the_records_lines() -> None:
    with pytest.raises(OSError, match="sync heard"):
        list(step.pull(step.Config(sources=("feed",))))


# -- what the review found ---------------------------------------------------------------------------


def test_a_response_cut_short_and_a_private_host_are_counted_skips_never_a_traceback(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], sleeps: list[float]
) -> None:
    import http.client

    _listen(lb, "2026-10-14T06:00:00Z", "EP-1", "Cut short", f"{FEED}/short.vtt")
    _listen(lb, "2026-10-14T07:00:00Z", "EP-2", "At home", "http://127.0.0.1:8080/t.vtt")
    _listen(lb, "2026-10-14T08:00:00Z", "EP-3", "Also at home", "http://localhost/t.vtt")
    _listen(lb, "2026-10-14T09:00:00Z", "EP-4", "Fine", f"{FEED}/fine.vtt")
    web = _web(monkeypatch, {f"{FEED}/fine.vtt": (VTT, {})})
    served = web.__call__

    def cut_short(request: Any, timeout: float) -> Any:
        if request.full_url.endswith("short.vtt"):
            web.requests.append(request.full_url)
            raise http.client.IncompleteRead(b"WEBVTT", 100)
        return served(request, timeout)

    monkeypatch.setattr(step, "urlopen", cut_short)
    monkeypatch.setenv("LOGBOOK_HEARD", "feed")
    status, out, err = _run(capsys, "sync", "heard")
    assert status == 0 and "Traceback" not in err, err
    assert "heard: 1 new lines" in out and "1 fetch failed" in out and "2 private host" in out
    assert web.requests == [f"{FEED}/short.vtt", f"{FEED}/fine.vtt"]  # never a request to this machine


def test_a_429_charges_nothing_to_the_url(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], sleeps: list[float]
) -> None:
    _listen(lb, "2026-10-14T06:00:00Z", "EP-1", "Busy", f"{FEED}/busy.vtt")
    _web(monkeypatch, {f"{FEED}/busy.vtt": 429})
    monkeypatch.setenv("LOGBOOK_HEARD", "feed")
    assert _run(capsys, "sync", "heard")[0] == 0
    cache = json.loads((lb.root / "state" / "heard-cache.json").read_text(encoding="utf-8"))
    assert not cache.get("failed")


def test_in_a_record_that_seals_the_text_is_sealed_and_read_with_the_identity_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], sleeps: list[float]
) -> None:
    import os

    from logbook.core import sealing

    pairs = [sealing.generate_identity() for _ in range(2)]
    record = Logbook.init(Path(os.environ["LOGBOOK_HOME"]), TZ)
    meta = record.meta
    meta["recipients"] = [recipient for _, recipient in pairs]
    record._save_meta(meta)
    identity = tmp_path / "keys" / "owner.txt"
    sealing.write_identity_file(identity, pairs[0][0], "test")
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(identity))
    record = Logbook(record.root)
    _listen(record, "2026-10-14T06:40:00Z", "EP-1", "Episode 12: the east berth", f"{FEED}/12.vtt")
    web = _web(monkeypatch, {f"{FEED}/12.vtt": (VTT, {"Content-Type": "text/vtt"})})
    monkeypatch.setenv("LOGBOOK_HEARD", "feed")

    assert _run(capsys, "sync", "heard")[0] == 0
    (line,) = [json.loads(raw) for f in record.files() for raw in f.read_text(encoding="utf-8").splitlines()
               if '"kind":"heard"' in raw.replace(" ", "")]  # fmt: skip
    assert line["tier"] == 2 and line["payload"]["schema"] == "sealed/v1"
    stored = record.root / "attachments" / record.opened(line)["payload"]["text"]["sha256"]
    assert sealing.is_sealed_file(stored)
    status, out, _ = _run(capsys, "show", "heard", "--day", "2026-10-14")
    assert status == 0 and "«Velkommen til Havnepodden. I dag snakker vi om østkaia.»" in out
    assert _run(capsys, "sync", "heard", "--since", "2026-10-01T00:00:00Z")[0] == 0
    assert len(web.requests) == 1  # the blinded raw_id still dedupes: never fetched again

    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(tmp_path / "nowhere.txt"))
    status, out, _ = _run(capsys, "show", "heard", "--day", "2026-10-14")
    assert (
        status == 0
        and "[sealed heard/v1]" in out
        and "(sealed; no identity on this machine to open it)" in out
    )
    assert "Velkommen" not in out


# -- redirects: every target checked before it is requested ---------------------------------------------


class FakeTransport:
    """The HTTP and HTTPS handlers' own `open`, so the step's real opener and its redirect handler
    run: each URL answers a status and headers from `routes` (a redirect is a 302 with `Location`),
    every request is recorded, and a URL not in `routes` was never meant to be asked for."""

    def __init__(self, routes: dict[str, tuple[int, dict[str, str], bytes]]) -> None:
        self.routes = routes
        self.requests: list[str] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import urllib.request

        transport = self

        def fake_open(handler: Any, request: Any) -> Any:
            return transport.answer(request)

        monkeypatch.setattr(urllib.request.HTTPHandler, "http_open", fake_open)
        monkeypatch.setattr(urllib.request.HTTPSHandler, "https_open", fake_open)
        _resolve(monkeypatch)  # every host of the fake web is a public one

    def answer(self, request: Any) -> Any:
        import urllib.response

        url = request.full_url
        self.requests.append(url)
        if url not in self.routes:
            raise AssertionError(f"{url} was requested")
        code, headers, body = self.routes[url]
        message = Message()
        for key, value in headers.items():
            message[key] = value
        response = urllib.response.addinfourl(io.BytesIO(body), message, url, code)
        response.msg = "OK" if code == 200 else "Found"  # type: ignore[attr-defined]
        return response


def test_a_redirect_to_this_machine_is_refused_and_never_requested(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], sleeps: list[float]
) -> None:
    _listen(lb, "2026-10-14T06:00:00Z", "EP-1", "Moved", f"{FEED}/moved.vtt")
    transport = FakeTransport({f"{FEED}/moved.vtt": (302, {"Location": "http://127.0.0.1:8080/t.vtt"}, b"")})
    transport.install(monkeypatch)
    monkeypatch.setenv("LOGBOOK_HEARD", "feed")

    status, out, err = _run(capsys, "sync", "heard")

    assert status == 0 and "Traceback" not in err, err
    assert transport.requests == [f"{FEED}/moved.vtt"]  # no second request: the target was refused
    assert "1 private host" in out and not _heard(lb)


def test_a_redirect_is_followed_to_a_public_host_and_never_to_another_scheme(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], sleeps: list[float]
) -> None:
    _listen(lb, "2026-10-14T06:00:00Z", "EP-1", "Moved once", f"{FEED}/a.vtt")
    _listen(lb, "2026-10-14T07:00:00Z", "EP-2", "To a file", f"{FEED}/b.vtt")
    _listen(lb, "2026-10-14T08:00:00Z", "EP-3", "To the LAN", f"{FEED}/c.vtt")
    transport = FakeTransport(
        {
            f"{FEED}/a.vtt": (302, {"Location": "https://cdn.example.org/a.vtt"}, b""),
            "https://cdn.example.org/a.vtt": (200, {"Content-Type": "text/vtt"}, VTT),
            f"{FEED}/b.vtt": (302, {"Location": "file:///etc/hosts"}, b""),
            f"{FEED}/c.vtt": (301, {"Location": "http://192.168.1.20/c.vtt"}, b""),
        }
    )
    transport.install(monkeypatch)
    monkeypatch.setenv("LOGBOOK_HEARD", "feed")

    status, out, err = _run(capsys, "sync", "heard")

    assert status == 0, err
    assert transport.requests == [
        f"{FEED}/a.vtt",
        "https://cdn.example.org/a.vtt",
        f"{FEED}/b.vtt",
        f"{FEED}/c.vtt",
    ]
    (line,) = _heard(lb)
    assert line["payload"]["title"] == "Moved once"
    assert "2 private host" in out


def test_at_most_three_redirects_are_followed(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], sleeps: list[float]
) -> None:
    _listen(lb, "2026-10-14T06:00:00Z", "EP-1", "Far away", f"{FEED}/0.vtt")
    hops = [f"{FEED}/{n}.vtt" for n in range(5)]
    routes: dict[str, tuple[int, dict[str, str], bytes]] = {
        hops[n]: (302, {"Location": hops[n + 1]}, b"") for n in range(4)
    }
    routes[hops[4]] = (200, {"Content-Type": "text/vtt"}, VTT)
    transport = FakeTransport(routes)
    transport.install(monkeypatch)
    monkeypatch.setenv("LOGBOOK_HEARD", "feed")

    status, out, err = _run(capsys, "sync", "heard")

    assert status == 0, err
    assert transport.requests == hops[:4]  # the first request and three redirects; the fourth is refused
    assert "1 fetch failed" in out and not _heard(lb)


# -- a name, or a number that is not written out, resolved and every address checked ---------------

LOOPBACK = ("127.0.0.1",)
AT_HOME = {  # what the resolver says of each: this machine, however the URL writes it
    "http://127.1/t.vtt": LOOPBACK,
    "http://2130706433/t.vtt": LOOPBACK,
    "http://0x7f000001/t.vtt": LOOPBACK,
    "https://rebind.example.org/t.vtt": LOOPBACK,
}
RESOLVES_HOME = {str(urlsplit(url).hostname): addresses for url, addresses in AT_HOME.items()}


@pytest.mark.parametrize("url", list(AT_HOME))
def test_a_host_that_resolves_to_this_machine_is_never_requested(
    url: str,
    lb: Logbook,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    sleeps: list[float],
) -> None:
    _listen(lb, "2026-10-14T06:00:00Z", "EP-1", "At home in disguise", url)
    transport = FakeTransport({})
    transport.install(monkeypatch)
    resolver = _resolve(monkeypatch, RESOLVES_HOME)
    monkeypatch.setenv("LOGBOOK_HEARD", "feed")

    status, out, err = _run(capsys, "sync", "heard")

    assert status == 0 and "Traceback" not in err, err
    assert transport.requests == []  # no request at all
    assert resolver.asked == [urlsplit(url).hostname]
    assert "1 private host" in out and not _heard(lb)


@pytest.mark.parametrize("url", list(AT_HOME))
def test_a_redirect_to_a_host_that_resolves_to_this_machine_is_refused_and_never_requested(
    url: str,
    lb: Logbook,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    sleeps: list[float],
) -> None:
    _listen(lb, "2026-10-14T06:00:00Z", "EP-1", "Moved home", f"{FEED}/moved.vtt")
    transport = FakeTransport({f"{FEED}/moved.vtt": (302, {"Location": url}, b"")})
    transport.install(monkeypatch)
    resolver = _resolve(monkeypatch, RESOLVES_HOME)
    monkeypatch.setenv("LOGBOOK_HEARD", "feed")

    status, out, err = _run(capsys, "sync", "heard")

    assert status == 0 and "Traceback" not in err, err
    assert transport.requests == [f"{FEED}/moved.vtt"]  # no second request: the target was refused
    assert resolver.asked == ["havn.example.org", urlsplit(url).hostname]
    assert "1 private host" in out and not _heard(lb)


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.7",
        "169.254.169.254",
        "240.0.0.1",
        "224.0.0.251",
        "0.0.0.0",
        "::1",
        "::ffff:127.0.0.1",
        "fe80::1",
    ],
)
def test_one_address_of_this_machine_or_its_network_among_public_ones_refuses_the_host(
    address: str,
    lb: Logbook,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    sleeps: list[float],
) -> None:
    _listen(lb, "2026-10-14T06:00:00Z", "EP-1", "Half at home", "https://mixed.example.org/t.vtt")
    transport = FakeTransport({})
    transport.install(monkeypatch)
    _resolve(monkeypatch, {"mixed.example.org": (PUBLIC, address)})
    monkeypatch.setenv("LOGBOOK_HEARD", "feed")

    status, out, err = _run(capsys, "sync", "heard")

    assert status == 0 and "Traceback" not in err, err
    assert transport.requests == [] and "1 private host" in out


def test_a_host_that_does_not_resolve_is_a_failed_fetch_never_a_request(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], sleeps: list[float]
) -> None:
    _listen(lb, "2026-10-14T06:00:00Z", "EP-1", "Nowhere", "https://gone.example.org/t.vtt")
    _listen(lb, "2026-10-14T07:00:00Z", "EP-2", "Moved nowhere", f"{FEED}/moved.vtt")
    transport = FakeTransport(
        {f"{FEED}/moved.vtt": (302, {"Location": "https://gone.example.org/m.vtt"}, b"")}
    )
    transport.install(monkeypatch)
    _resolve(monkeypatch, unresolved=("gone.example.org",))
    monkeypatch.setenv("LOGBOOK_HEARD", "feed")

    status, out, err = _run(capsys, "sync", "heard")

    assert status == 0 and "Traceback" not in err, err
    assert transport.requests == [f"{FEED}/moved.vtt"]
    assert "2 fetch failed" in out and "private host" not in out and not _heard(lb)
