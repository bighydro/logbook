"""`sync heard`: the words of the podcasts and videos the owner played → heard/v1 (RFC 0046).

A live source of the record's own lines: it reads the `listen/v1` and `watch/v1` lines the other
sources wrote, through the index (`lines`, from the local day before `since` on), and for each work
that has no text yet takes one from each text source the owner turned on (`LOGBOOK_HEARD`, a comma
list), stores it in the attachment store as it came and yields one `heard/v1` line beside it:

    feed      a listen's `extra.transcript_url` (`<podcast:transcript>`), fetched once over HTTPS:
              WebVTT, SRT, podcasting 2.0's JSON or plain text; HTML is skipped and counted
    apple     the TTML transcript Apple Podcasts cached on this Mac, under its group container's
              `Library/Cache/Assets/TTML` (`LOGBOOK_HEARD_TTML_DIR` names another), matched to the
              episode through the Podcasts store's `ZTRANSCRIPTIDENTIFIER` or `ZSTORETRACKID`
              (`LOGBOOK_PODCASTS_DB`, as `sync apple-podcasts` reads it): local files, no network
    captions  a watched video's captions from the owner's folder (`LOGBOOK_HEARD_CAPTIONS_DIR`), a
              file per video named `<video_id>.vtt` or `<video_id>.<language>.vtt`: YouTube
              documents no keyless way to fetch captions, and this never scrapes one

Never twice: the `raw_id` of every text a run could write (`heard.work_key`) is asked of the record
first (`existing`, one SELECT), and a work that has its text is passed by without a request. At most
`LOGBOOK_HEARD_MAX_FETCHES` fetches a run (default 20), `LOGBOOK_HEARD_DELAY_S` seconds apart
(default 2); a run that reaches the cap stops taking works there, so the watermark is the last work
taken and the next run carries on. A failed fetch is one counted skip, its URL noted in the cache
(`state/heard-cache.json`) and not tried again for `RETRY_AFTER_DAYS`, nor ever after
`GIVE_UP_AFTER` failures; a 429 ends the run's fetching. A URL, or a redirect's target, whose host is
this machine, its network or any address that is not global (the tailnet's 100.64.0.0/10 among them),
written out or as any address it resolves to, whose scheme is not http(s) or whose port is not 80 or
443, is never requested, nor one whose host does not resolve, nor an https page's redirect to http;
the connection goes to the address that was checked and no other, on every hop, never through a
proxy; at most `MAX_REDIRECTS` redirects are followed. Without `store` (a dry run) nothing is
fetched and nothing stored: a fetch is counted as `would_fetch`, a local text read and counted.

Not in `pyproject.toml`'s table: `logbook.commands.sync` runs it by name and as the last source of
`sync --all` (RFC 0046 §10)."""

from __future__ import annotations

import ipaddress
import re
import socket
import sqlite3
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from http.client import HTTPConnection, HTTPException
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import (
    HTTPHandler,
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)
from zoneinfo import ZoneInfo

from ... import __version__
from ...core import attachments, policy
from ...core import heard as profile
from . import apple_podcasts

NAME = "heard"
SOURCE = profile.SOURCE
KIND = profile.KIND
TIER = profile.TIER
UNIT = "texts"

SOURCES_ENV = "LOGBOOK_HEARD"
MAX_FETCHES_ENV = "LOGBOOK_HEARD_MAX_FETCHES"
DELAY_ENV = "LOGBOOK_HEARD_DELAY_S"
CAPTIONS_ENV = "LOGBOOK_HEARD_CAPTIONS_DIR"
LANGUAGES_ENV = "LOGBOOK_HEARD_LANGUAGES"
TTML_ENV = "LOGBOOK_HEARD_TTML_DIR"
ENV = (SOURCES_ENV,)  # the switch; the others are optional and read by `configure`
STEP_SOURCES = ("feed", "apple", "captions")  # what this step reads; `local` is reserved (RFC 0046 §6.4)

DEFAULT_MAX_FETCHES = 20
DEFAULT_DELAY_S = 2.0
MAX_BYTES = 5_000_000  # a transcript larger than this is no transcript: refused and counted
MAX_REDIRECTS = 3  # a feed's transcript that moves more often than this is not followed further
TIMEOUT_S = 30
LOOKBACK_DAYS = 14  # a run starts this far before its watermark: a listen can reach the record late
RETRY_AFTER_DAYS = 7  # a URL that failed is not tried again before this
GIVE_UP_AFTER = 3  # failures after which a URL is never tried again
USER_AGENT = f"openlogbook/{__version__} (+https://github.com/bighydro/logbook)"
ACCEPT = "text/vtt, application/x-subrip, application/srt, application/json, text/plain;q=0.9, */*;q=0.1"
DEFAULT_TTML = (
    "Library",
    "Group Containers",
    "243LU875E5.groups.com.apple.podcasts",
    "Library",
    "Cache",
    "Assets",
    "TTML",
)
CAPTION_SUFFIXES = (".vtt", ".srt")
TRACK_ID = re.compile(r"transcript_(\d+)")
LANGUAGE_TAG = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})*")  # a BCP 47 tag, as far as a file name says
NO_FETCH_ENTRY = "sync heard fetches no transcript without the record's heard entry (policy.heard_fetch)"
FAILED = "failed"  # the cache's key: url → {"count": n, "last": "YYYY-MM-DD"}

sleep = time.sleep  # tests replace it, as they replace `urlopen`
WEB_SCHEMES = ("http", "https")
WEB_PORTS = (80, 443)  # the only ports a fetch connects to, written out or not
VETTED = "logbook_vetted_address"  # the attribute of a Request naming the addresses its host was checked as
HOST_NAME = re.compile(r"[A-Za-z0-9._-]+")  # a host as a name: urllib unquotes a `%` before reading the port


@dataclass(frozen=True)
class Config:
    sources: tuple[str, ...]
    max_fetches: int = DEFAULT_MAX_FETCHES
    delay_s: float = DEFAULT_DELAY_S
    captions_dir: Path | None = None
    languages: tuple[str, ...] = ()
    ttml_dir: Path = field(default_factory=lambda: Path.home().joinpath(*DEFAULT_TTML))
    podcasts_db: Path = field(default_factory=lambda: Path.home().joinpath(*apple_podcasts.DEFAULT_DB))


def configure(env: Mapping[str, str]) -> Config | None:
    """The text sources the owner turned on and the step's settings; None until `LOGBOOK_HEARD`
    is set. A value the step cannot use raises ValueError, one sentence naming the variable."""
    given = env.get(SOURCES_ENV, "").strip()
    if not given:
        return None
    sources = tuple(dict.fromkeys(part.strip().casefold() for part in given.split(",") if part.strip()))
    unknown = [s for s in sources if s not in STEP_SOURCES]
    if unknown:
        hint = " (`local` is reserved, not built)" if "local" in unknown else ""
        raise ValueError(
            f"{SOURCES_ENV} names {', '.join(unknown)}; it takes {', '.join(STEP_SOURCES)}{hint}"
        )
    captions = env.get(CAPTIONS_ENV, "").strip()
    if "captions" in sources and not captions:
        raise ValueError(f"captions are read from your own folder: set {CAPTIONS_ENV}")
    ttml = env.get(TTML_ENV, "").strip()
    return Config(
        sources=sources,
        max_fetches=_whole(env, MAX_FETCHES_ENV, DEFAULT_MAX_FETCHES),
        delay_s=_seconds(env, DELAY_ENV, DEFAULT_DELAY_S),
        captions_dir=Path(captions).expanduser() if captions else None,
        languages=tuple(p.strip() for p in env.get(LANGUAGES_ENV, "").split(",") if p.strip()),
        ttml_dir=Path(ttml).expanduser() if ttml else Path.home().joinpath(*DEFAULT_TTML),
        podcasts_db=apple_podcasts.configure(env).db,
    )


def needs(env: Mapping[str, str]) -> str:
    return f"{SOURCES_ENV} (a comma list of {', '.join(STEP_SOURCES)})"


def _whole(env: Mapping[str, str], name: str, default: int) -> int:
    text = env.get(name, "").strip()
    if not text:
        return default
    if not text.isdigit():
        raise ValueError(f"{name} is a whole number of fetches, not {text!r}")
    return int(text)


def _seconds(env: Mapping[str, str], name: str, default: float) -> float:
    text = env.get(name, "").strip()
    if not text:
        return default
    try:
        value = float(text)
    except ValueError:
        value = -1.0
    if not value >= 0:
        raise ValueError(f"{name} is a number of seconds, not {text!r}")
    return value


def watermark(draft: dict[str, Any]) -> str | None:
    """The `at` of the listen or watch the text belongs to: the record's lines are read by it."""
    return str(draft["at"])


def resume(config: Config, mark: str) -> str:
    """`LOOKBACK_DAYS` before the watermark: a listen or a watch can reach the record days after it
    happened, and the texts already held cost an index lookup, never a fetch."""
    when = datetime.fromisoformat(mark.replace("Z", "+00:00")) - timedelta(days=LOOKBACK_DAYS)
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# -- the pull --------------------------------------------------------------------------------------


@dataclass
class _Work:
    """One text a run may write: the listen or watch line it belongs to, the text source, its key."""

    line: dict[str, Any]
    text_source: str
    key: str


@dataclass
class _Text:
    data: bytes
    fmt: str
    language: str | None
    url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def pull(
    config: Config,
    since: str | None = None,
    progress: Callable[[int, float], None] | None = None,
    counts: dict[str, int] | None = None,
    lines: Callable[[str, str], list[dict[str, Any]]] | None = None,
    existing: Callable[[Iterable[tuple[str, str]]], set[tuple[str, str]]] | None = None,
    store: Callable[..., Path] | None = None,
    cache: dict[str, Any] | None = None,
    timezone: str | None = None,
    notice: Callable[[str], None] | None = None,
    today: date | None = None,
    fetch_entry: policy.Fetch | None = None,
) -> Iterator[dict[str, Any]]:
    """One heard/v1 draft per work that has no text yet, the works in the order of their listen or
    watch (`at`, then `seq`), from `since` on (None: every one). `lines(kind, first_day)` is the
    record's standing lines of a kind from a local day on; `existing` which `(source, raw_id)` keys
    the record holds; `store(data, tier=)` puts a text in the attachment store (None: a dry run,
    nothing fetched, nothing stored); `cache` the step's own bookkeeping between runs; `fetch_entry`
    what the `heard` entry of the policy lets a feed's transcript be fetched for (`policy.heard_fetch`,
    S9), checked before any request or lookup: None, as without the entry, fetches nothing."""
    if lines is None:
        raise OSError("heard reads the record's own listens and watches: run it as `logbook sync heard`")
    counts = counts if counts is not None else {}
    cache = cache if cache is not None else {}
    tz = timezone or "UTC"
    on = today or datetime.now(UTC).date()
    works = _works(config, lines(profile.OF_KINDS[0], _first_day(since, tz)), since, counts)
    works += _works(config, lines(profile.OF_KINDS[1], _first_day(since, tz)), since, counts)
    works.sort(
        key=lambda w: (str(w.line["at"]), int(w.line.get("seq") or 0), STEP_SOURCES.index(w.text_source))
    )
    held = existing((SOURCE, w.key) for w in works) if existing is not None and works else set()
    taken: set[str] = set()
    todo: list[_Work] = []
    for work in works:
        if (SOURCE, work.key) in held or work.key in taken:
            continue  # the record has this text, or an earlier listen of the same work takes it
        taken.add(work.key)
        todo.append(work)
    apple = _AppleTexts(config, counts, notice) if "apple" in config.sources else None
    captions = _Captions(config, counts) if "captions" in config.sources else None
    fetched, written, started = 0, 0, time.monotonic()
    stop_fetching = False
    entry = fetch_entry if fetch_entry is not None else policy.Fetch(0, NO_FETCH_ENTRY)
    told = False
    for n, work in enumerate(todo):
        text: _Text | None = None
        if work.text_source == "feed":
            if int(work.line.get("tier") or profile.TIER) > entry.max_tier:
                _count(counts, "skipped_not_fetched")  # the entry is checked before anything is asked
                if not told and notice is not None:
                    notice(entry.why_not or _under_entry(entry, int(work.line.get("tier") or profile.TIER)))
                told = True
                continue
            if stop_fetching:
                counts["left_for_next_run"] = counts.get("left_for_next_run", 0) + len(todo) - n
                break
            url = str(profile.transcript_url(work.line["payload"]))
            if not _may_try(cache, url, on):
                _count(counts, "skipped_failed_before")
                continue
            if fetched >= config.max_fetches:
                counts["left_for_next_run"] = counts.get("left_for_next_run", 0) + len(todo) - n
                break
            if store is None:
                _count(counts, "would_fetch")
                fetched += 1
                continue
            if fetched and config.delay_s:
                sleep(config.delay_s)
            fetched += 1
            try:
                text = _fetch(url, counts)
            except _RateLimited:  # the host is busy, the URL is not wrong: nothing charged to it
                _count(counts, "skipped_rate_limited")
                stop_fetching = True
                continue
            if text is None:
                _note_failure(cache, url, on)
                continue
            _forget_failure(cache, url)
        elif work.text_source == "apple" and apple is not None:
            text = apple.text(work.line)
        elif work.text_source == "captions" and captions is not None:
            text = captions.text(work.line)
        if text is None:
            continue
        draft = _draft(work, text, tz, counts, store)
        if draft is None:
            continue
        written += 1
        if progress is not None and written % 50 == 0:
            progress(written, time.monotonic() - started)
        yield draft
    if progress is not None:
        progress(written, time.monotonic() - started)


def _under_entry(entry: policy.Fetch, tier: int) -> str:
    return (
        f"sync heard fetches no transcript of a tier-{tier} listen: the {policy.HEARD_DESTINATION!r} entry of"
        f" {policy.POLICY_FILE.as_posix()} allows fetches up to max_tier {entry.max_tier}"
        f' ("{policy.FETCH}": true with a max_tier of {tier} lets them through)'
    )


def _first_day(since: str | None, tz: str) -> str:
    """The local day before `since`'s, so a listen late in that day's evening is read; the
    beginning when there is no `since`."""
    if since is None:
        return "0001-01-01"
    try:
        zone = ZoneInfo(tz)
    except (KeyError, ValueError):
        zone = ZoneInfo("UTC")
    local = datetime.fromisoformat(since.replace("Z", "+00:00")).astimezone(zone)
    return (local - timedelta(days=1)).date().isoformat()


def _works(
    config: Config, found: Iterable[dict[str, Any]], since: str | None, counts: dict[str, int]
) -> list[_Work]:
    """Every (line, text source) pair the owner's sources can give a text for, from `since` on."""
    out: list[_Work] = []
    for line in found:
        if since is not None and str(line.get("at", "")) < since:
            continue
        payload = line.get("payload")
        if not isinstance(payload, dict) or payload.get("schema") == "sealed/v1":
            _count(counts, "skipped_sealed_no_identity")
            continue
        for text_source in STEP_SOURCES:
            if text_source not in config.sources:
                continue
            key = profile.work_key(text_source, line)
            if key is not None:
                out.append(_Work(line, text_source, key))
    return out


def _draft(
    work: _Work, text: _Text, tz: str, counts: dict[str, int], store: Callable[..., Path] | None
) -> dict[str, Any] | None:
    """The heard/v1 line draft for a text, its bytes stored first; None, counted, when the text
    has no words or is not the format it claims."""
    try:
        words = profile.words_of(text.data, text.fmt)
    except profile.Unreadable:
        _count(counts, "skipped_unreadable")
        return None
    chars, n_words = profile.length_of(words)
    if not n_words:
        _count(counts, "skipped_no_words")
        return None
    media_type = profile.MEDIA_TYPES[text.fmt]
    if store is not None:
        store(text.data, tier=TIER)
    line = work.line
    title, by = profile.title_and_by(line)
    payload: dict[str, Any] = {
        "schema": profile.SCHEMA,
        "raw_id": work.key,
        "of": str(line["id"]),
        "of_kind": str(line["kind"]),
        "media": "video" if line["kind"] == "watch" else "episode",
        "title": title,
    }
    if by:
        payload["by"] = by
    payload |= {
        "text_source": work.text_source,
        "language": text.language or profile.UNKNOWN_LANGUAGE,
        "format": text.fmt,
        "chars": chars,
        "words": n_words,
        "text": attachments.reference(text.data, media_type),
    }
    if text.url:
        payload["url"] = text.url
    if text.extra:
        payload["extra"] = dict(text.extra)
    return {
        "at": str(line["at"]),
        "end": line.get("end"),
        "tz": tz,
        "source": SOURCE,
        "kind": KIND,
        "tier": TIER,
        "payload": payload,
    }


def _count(counts: dict[str, int], key: str, n: int = 1) -> None:
    counts[key] = counts.get(key, 0) + n


# -- feed: one fetch -------------------------------------------------------------------------------


class _Refused(Exception):
    """A redirect named a target the step never requests: this machine or its network, a scheme that
    is not http(s), or a host that does not resolve. `count` is the skip it is counted as."""

    def __init__(self, url: str, count: str) -> None:
        super().__init__(url)
        self.count = count


class _Redirects(HTTPRedirectHandler):
    """urllib's redirect handling, with every target checked before it is requested: a target that is
    not http(s), an https page's target that is http, or one `_check` refuses raises `_Refused` and
    nothing is asked of it; the new request carries the address its host was checked as, so the hop
    connects there and nowhere else (`_Pinned`); at most `MAX_REDIRECTS` are followed, and the one
    after is an HTTPError, a counted failed fetch."""

    max_redirections = MAX_REDIRECTS

    def http_error_302(self, req: Any, fp: Any, code: int, msg: str, headers: Any) -> Any:
        target = headers.get("location") or headers.get("uri")
        self._vetted: tuple[str, ...] | None = None
        if target is not None:
            joined = urljoin(req.full_url, target)
            scheme = urlsplit(joined).scheme.casefold()
            refused: str | None
            if scheme not in WEB_SCHEMES:
                refused = "skipped_private_host"
            else:
                refused, self._vetted = _check(joined)
            if refused is None and scheme == "http" and urlsplit(req.full_url).scheme.casefold() == "https":
                refused = "skipped_insecure_redirect"
            if refused is not None:
                fp.close()
                raise _Refused(joined, refused)
        return super().http_error_302(req, fp, code, msg, headers)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            setattr(new, VETTED, getattr(self, "_vetted", None))
        return new


def _pinned(http_class: Any, req: Any) -> Any:
    """`http_class` made to connect to the address `req`'s host was checked as (`VETTED`) and to no
    other, while the name stays the connection's host: the Host header and, for https, the SNI and
    the certificate check carry it. A request no check vetted is refused, never resolved again."""
    addresses = getattr(req, VETTED, None)
    if not isinstance(addresses, tuple) or not addresses:
        raise URLError("the host was not checked before the request; nothing was asked")

    def connection(host: str, **kwargs: Any) -> HTTPConnection:
        made: HTTPConnection = http_class(host, **kwargs)

        def to_vetted(where: tuple[str, int], *args: Any, **options: Any) -> socket.socket:
            failed: OSError | None = None
            for address in addresses:  # each checked address in turn, as `create_connection` tries a name's
                try:
                    return socket.create_connection((address, where[1]), *args, **options)
                except OSError as e:
                    failed = e
            raise failed or OSError("no address to connect to")

        made._create_connection = to_vetted  # type: ignore[attr-defined]
        return made

    return connection


class _PinnedHTTP(HTTPHandler):
    def do_open(self, http_class: Any, req: Any, **kwargs: Any) -> Any:
        return super().do_open(_pinned(http_class, req), req, **kwargs)


class _PinnedHTTPS(HTTPSHandler):
    def do_open(self, http_class: Any, req: Any, **kwargs: Any) -> Any:
        return super().do_open(_pinned(http_class, req), req, **kwargs)


def urlopen(request: Request, timeout: float) -> Any:
    """Every fetch of the step: urllib's opener with no proxy whatever the environment says
    (`ProxyHandler({})`: a proxy would connect where the check never looked), `_Redirects` in place of
    its redirect handler, and the HTTP and HTTPS handlers connecting to the checked address only
    (`_pinned`). Tests replace this function with a fake web, or the HTTP handlers under it."""
    opener = build_opener(ProxyHandler({}), _Redirects(), _PinnedHTTP(), _PinnedHTTPS())
    return opener.open(request, timeout=timeout)


class _RateLimited(Exception):
    """The server said 429: no more fetches this run."""


def _fetch(url: str, counts: dict[str, int]) -> _Text | None:
    """The transcript at `url`, or None having counted why not: the server refused, the body is
    over `MAX_BYTES`, it is HTML or a format nobody reads. A 429 raises `_RateLimited`."""
    refused, address = _check(url)
    if refused is not None:
        _count(counts, refused)
        return None
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": ACCEPT})
    setattr(request, VETTED, address)  # the addresses the connection goes to, and no second answer
    try:
        with urlopen(request, timeout=TIMEOUT_S) as response:
            data = response.read(MAX_BYTES + 1)
            content_type = response.headers.get("Content-Type")
            content_language = response.headers.get("Content-Language")
    except _Refused as e:  # a redirect to this machine, its network, another scheme, port or nowhere
        _count(counts, e.count)
        return None
    except HTTPError as e:
        if e.code == 429:
            raise _RateLimited from None
        _count(counts, "skipped_fetch_failed")
        return None
    except (OSError, ValueError, HTTPException):  # refused, timed out, cut short, unresolved, a bad URL
        _count(counts, "skipped_fetch_failed")
        return None
    if len(data) > MAX_BYTES:
        _count(counts, "skipped_too_large")
        return None
    fmt = profile.format_of(content_type, _url_name(url), data)
    if fmt == "html":
        _count(counts, "skipped_html")
        return None
    if fmt is None or fmt == "ttml":  # a feed's TTML is not one podcasting 2.0 names
        _count(counts, "skipped_unknown_format")
        return None
    language = profile.language_of(data, fmt) or _first_language(content_language)
    extra = {"content_type": content_type} if content_type else {}
    return _Text(data, fmt, language, url=url, extra=extra)


def _refusal(url: str) -> str | None:
    """Why the step never requests `url`, as the skip it is counted as, or None when it may (`_check`)."""
    return _check(url)[0]


def _is_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _check(url: str) -> tuple[str | None, tuple[str, ...] | None]:
    """Why the step never requests `url`, as the skip it is counted as, and else the one address the
    request connects to: `skipped_private_host` when the scheme is not http(s), when `_private_host`
    refuses it as written, or when any address its host resolves to (`socket.getaddrinfo`, asked once)
    is one `_at_home` names, so `127.1`, `2130706433` or a name that resolves to 127.0.0.1 or into the
    tailnet are refused like `127.0.0.1`; `skipped_port` for a port other than 80 and 443;
    `skipped_fetch_failed` when the host does not resolve. The check is before every request, the
    first and each redirect's, and the addresses it returns are the ones it checked: the connection
    goes to them in turn (`_pinned`), never to a second answer of the resolver. A host that is neither
    a name nor an address (an escape in it) is refused before any lookup."""
    parts = urlsplit(url)
    if parts.scheme.casefold() not in WEB_SCHEMES or _private_host(url):
        return "skipped_private_host", None
    try:
        port = parts.port or (443 if parts.scheme.casefold() == "https" else 80)
    except ValueError:  # a port that is not a number in range
        return "skipped_port", None
    if port not in WEB_PORTS:
        return "skipped_port", None
    host = str(parts.hostname)
    if not HOST_NAME.fullmatch(host) and not _is_address(host):
        return "skipped_private_host", None  # `a.example%3A22` would connect to port 22
    try:
        found = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, ValueError):  # not found, no answer, a name the resolver cannot encode
        return "skipped_fetch_failed", None
    if not found:
        return "skipped_fetch_failed", None
    addresses: list[str] = []
    for *_, sockaddr in found:
        try:
            address = ipaddress.ip_address(sockaddr[0])
        except ValueError:  # an address the step cannot read is one it cannot vouch for
            return "skipped_private_host", None
        if _at_home(address):
            return "skipped_private_host", None
        addresses.append(str(address))
    return None, tuple(dict.fromkeys(addresses))


def _private_host(url: str) -> bool:
    """A URL a feed names that points into this machine or its network as written: no host,
    `localhost`, or an address written out that `_at_home` names. A feed is someone else's data, and
    the step never lets it aim a request at the owner's own services. A name, and a number not written
    out in full (`127.1`), is resolved and every address checked by `_refusal`."""
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return True
    if not host:
        return True
    if host.casefold() == "localhost" or host.casefold().endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return _at_home(address)


def _at_home(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """An address of this machine or its network, or none a fetch should go to: any address that is
    not global (the tailnet's 100.64.0.0/10 and Tailscale's 100.100.100.100 among them, which
    `is_private` lets through), and private, loopback, link-local, reserved, multicast or unspecified
    ones, an IPv4 address inside IPv6 judged as itself."""
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return (
        not address.is_global
        or address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def _url_name(url: str) -> str | None:
    """The last part of a URL's path, for its extension; never a filesystem path."""
    path = urlsplit(url).path
    return path.rsplit("/", 1)[-1] or None


def _first_language(header: str | None) -> str | None:
    if not header:
        return None
    first = header.split(",")[0].strip()
    return first if LANGUAGE_TAG.fullmatch(first) else None


def _may_try(cache: dict[str, Any], url: str, on: date) -> bool:
    """A URL that failed is tried again only `RETRY_AFTER_DAYS` after its last failure, and never
    after `GIVE_UP_AFTER` failures."""
    failed = cache.get(FAILED)
    noted = failed.get(url) if isinstance(failed, dict) else None
    if not isinstance(noted, dict):
        return True
    count = noted.get("count")
    if isinstance(count, int) and count >= GIVE_UP_AFTER:
        return False
    try:
        last = date.fromisoformat(str(noted.get("last")))
    except ValueError:
        return True
    return (on - last).days >= RETRY_AFTER_DAYS


def _note_failure(cache: dict[str, Any], url: str, on: date) -> None:
    failed = cache.setdefault(FAILED, {})
    noted = failed.get(url)
    count = noted.get("count") if isinstance(noted, dict) else None
    failed[url] = {"count": (count if isinstance(count, int) else 0) + 1, "last": on.isoformat()}


def _forget_failure(cache: dict[str, Any], url: str) -> None:
    failed = cache.get(FAILED)
    if isinstance(failed, dict):
        failed.pop(url, None)


# -- apple: the TTML files Apple Podcasts cached ---------------------------------------------------


class _AppleTexts:
    """The TTML files under the container, by name, and the Podcasts store's columns that name an
    episode's file: read once, on the first episode asked for."""

    def __init__(self, config: Config, counts: dict[str, int], notice: Callable[[str], None] | None) -> None:
        self.config, self.counts, self.notice = config, counts, notice
        self._by_uuid: dict[str, Path] | None = None

    def text(self, line: Mapping[str, Any]) -> _Text | None:
        uuid = profile.episode_uuid(line["payload"])
        path = self._files().get(str(uuid))
        if path is None:
            _count(self.counts, "skipped_no_apple_transcript")
            return None
        try:
            data = path.read_bytes()
        except OSError:
            _count(self.counts, "skipped_unreadable")
            return None
        return _Text(data, "ttml", profile.language_of(data, "ttml"), extra={"file": path.name})

    def _files(self) -> dict[str, Path]:
        if self._by_uuid is None:
            self._by_uuid = self._match()
        return self._by_uuid

    def _match(self) -> dict[str, Path]:
        folder = self.config.ttml_dir
        if not folder.is_dir():
            self._say(f"apple: no transcript folder at {folder}; nothing read from it")
            return {}
        files = sorted(p for p in folder.rglob("*") if p.suffix.casefold() == ".ttml" and p.is_file())
        by_name = {p.name.casefold(): p for p in files}
        by_track: dict[str, Path] = {}
        for p in files:
            found = TRACK_ID.search(p.name)
            if found:
                by_track.setdefault(found.group(1), p)
        out: dict[str, Path] = {}
        for uuid, identifier, track in self._episodes():
            path = None
            if identifier:
                name = _last_part(identifier).casefold()
                path = by_name.get(name) or next(
                    (p for n, p in by_name.items() if name and n.startswith(name)), None
                )
            if path is None and track:
                path = by_track.get(track)
            if path is not None:
                out[uuid] = path
        return out

    def _episodes(self) -> Iterator[tuple[str, str | None, str | None]]:
        """(uuid, transcript identifier, store track id) of every episode the store names, the
        columns confirmed with `PRAGMA table_info` first; nothing, said once, when the store or both
        columns are missing."""
        try:
            con = apple_podcasts.open_live(self.config.podcasts_db)
        except OSError as e:
            self._say(f"apple: {e}; no transcript matched")
            return
        try:
            have = {str(row[1]) for row in con.execute(f"PRAGMA table_info({apple_podcasts.EPISODES})")}
            wanted = [c for c in ("ZTRANSCRIPTIDENTIFIER", "ZSTORETRACKID") if c in have]
            if not wanted:
                self._say(
                    f"apple: {self.config.podcasts_db} has neither ZTRANSCRIPTIDENTIFIER nor ZSTORETRACKID;"
                    " no transcript matched"
                )
                return
            columns = [
                "ZUUID",
                *(c if c in have else "NULL" for c in ("ZTRANSCRIPTIDENTIFIER", "ZSTORETRACKID")),
            ]
            query = f"SELECT {', '.join(columns)} FROM {apple_podcasts.EPISODES} WHERE ZUUID IS NOT NULL"
            for uuid, identifier, track in con.execute(query):
                ident = identifier if isinstance(identifier, str) and identifier.strip() else None
                if ident is not None and ident.startswith(apple_podcasts.URL_SCHEMES):
                    ident = None  # a public URL is the feed's transcript, `feed`'s to fetch
                track_id = _track_id(track)
                yield str(uuid), ident, track_id
        except sqlite3.Error as e:
            self._say(f"apple: cannot read {self.config.podcasts_db} ({e}); no transcript matched")
        finally:
            con.close()

    def _say(self, text: str) -> None:
        if self.notice is not None:
            self.notice(text)


def _track_id(value: object) -> str | None:
    """The store's catalogue id of an episode, an integer column that drift may make text."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float) and value > 0:
        return str(int(value))
    if isinstance(value, str) and value.strip().isdigit():
        return value.strip()
    return None


def _last_part(identifier: str) -> str:
    """The last part of the store's identifier, a path relative to the TTML folder as Apple spells it
    (`/`-separated whatever the machine): never a path on this machine, so it is split here once."""
    from pathlib import PurePosixPath

    return PurePosixPath(identifier.strip()).name


# -- captions: the owner's folder ------------------------------------------------------------------


class _Captions:
    """The owner's caption files by video id: `<id>.vtt`, `<id>.<language>.vtt` (or `.srt`)."""

    def __init__(self, config: Config, counts: dict[str, int]) -> None:
        self.config, self.counts = config, counts
        self._by_id: dict[str, list[tuple[str | None, Path]]] | None = None

    def text(self, line: Mapping[str, Any]) -> _Text | None:
        video = profile.video_id(line["payload"])
        found = self._files().get(str(video))
        if not found:
            _count(self.counts, "skipped_no_captions")
            return None
        language, path = self._choose(found)
        if len(found) > 1:
            _count(self.counts, "skipped_captions_other_language", len(found) - 1)
        try:
            data = path.read_bytes()
        except OSError:
            _count(self.counts, "skipped_unreadable")
            return None
        fmt = "srt" if path.suffix.casefold() == ".srt" else "vtt"
        said = language or profile.language_of(data, fmt)
        return _Text(data, fmt, said, extra={"file": path.name})

    def _choose(self, found: list[tuple[str | None, Path]]) -> tuple[str | None, Path]:
        """The first of the owner's languages present, else the file without a language, else the
        first by name."""
        for wanted in self.config.languages:
            for language, path in found:
                if language is not None and language.casefold() == wanted.casefold():
                    return language, path
        bare = [item for item in found if item[0] is None]
        return (bare or sorted(found, key=lambda item: item[1].name))[0]

    def _files(self) -> dict[str, list[tuple[str | None, Path]]]:
        if self._by_id is None:
            self._by_id = {}
            folder = self.config.captions_dir
            if folder is not None and folder.is_dir():
                for path in sorted(folder.iterdir()):
                    if path.suffix.casefold() not in CAPTION_SUFFIXES or not path.is_file():
                        continue
                    stem = Path(path.stem)  # `<id>` or `<id>.<language>`
                    language = stem.suffix.removeprefix(".") or None
                    video = stem.stem if language else stem.name
                    if language is not None and not LANGUAGE_TAG.fullmatch(language):
                        language, video = None, stem.name
                    self._by_id.setdefault(video, []).append((language, path))
        return self._by_id
