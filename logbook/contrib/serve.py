"""`logbook serve [--port N]`: the record read in a browser, from this machine only.

A reader (ADR 0013) with another output: server-rendered HTML in place of text, one page per
reader the commands already have. `/day/YYYY-MM-DD` is the Day (`day.read`) as a timeline, each
row's attachments and company folded under a toggle; `/days?from=&to=` is a window one row per
day (`days.read`), each row a link to its Day; `/trips?year=` the trips of a year (`trips.trips`
over one `reading.read`); `/places` the named places of `places.json`; `/assets` the registered
assets and the last fix of each (`asset_status.read`); `/gaps` where each source went quiet
(`gaps.report`); `/today` redirects to the Day the owner is in now: the current date in the
record's timezone, the date before until the record's `day_start` (RFC 0036), whose Day then says
where it begins. Every page is built from the index and the readers, so a Day renders in the time
`logbook day` takes whatever the record's length, and nothing is written by a GET: every page is
answered from the record at its head.

Two pages write, on a POST. `/places` carries the review queue of `setup places review`
(`places_review.read`, the same order, `PAGE_SIZE` clusters a page), and its forms post to
`/places/review` (`Site.write`), which names a cluster or rejects it through the engine's own
`accept` and `reject`, so `places.json`, the naming note and `state/places-review.json` are what the
CLI writes. The Day carries the owner's two acts on it, Reflect and Sign (`Site._reflect`,
`Site._sign`): the reflection posts to `/day/YYYY-MM-DD/reflect` and is written through `day
reflect`'s own `reflect.write` (the day's Wispr Flow draft offered prefilled, a recording heard
through `day reflect --audio`'s path when the command wired one in, `Voice`), and the proposals
the rules read in it are checkboxes whose form posts to `/day/YYYY-MM-DD/sign`, which signs the
day through `reflect.close`, the code `day reflect --sign` runs: `signing.sign` with the lines
confirmed, the accepted dispositions and the reflection, a signed day signed again superseding its
signature. The Library's write acts, allowed because the server binds 127.0.0.1 and runs as the
record's own user: a POST is answered only when the connection comes from this machine (the client
address is loopback) and the form was submitted from the server's own pages (the browser's
`Origin`, when it sends one, names 127.0.0.1); anything else is a 403 and nothing is written. Every
write is one at a time (`Site._write_lock`) and through the CLI's own function; the Day's never
waits for another writer. After a write the head has moved, and the next request reads the record
again as after a sync. The policy's `write` list (the MCP door, ADR 0022) is never read: this is
the owner's own page.

The server keeps nothing between requests but the head it last saw. When a sync moves the head
while it runs, the next request brings the index to the new head first (`Site.current`: once,
under a lock, so requests that arrive together wait for one rebuild instead of racing their own on
one file) and every page reads the new lines; no restart. A page that is the record's and nothing
else carries an ETag made from the head and what else it reads (`Site.etag`), sent with
`Cache-Control: no-cache`, so a browser keeps it and asks again each time, and a reload at the same
head is a 304 that renders nothing. `/assets` and `/gaps`, which the clock moves, carry none.

Three rules, each enforced here and tested in `tests/test_serve.py`:

- The server binds 127.0.0.1 and refuses any other host (`HostError`, raised before a socket is
  opened), so the record is readable from this machine and nowhere else. It never resolves a
  name, not even its own.
- A page is one HTML document with one inline stylesheet: no font, no image, no stylesheet link,
  no script fetched, and no reference to any URL but the server's own paths. A script is inline on
  two pages, each named in that page's Content-Security-Policy by its hash and by nothing else: the
  Places page's keys (`PLACES_SCRIPT`: Enter, n and Space) and the Day page's record button
  (`DAY_SCRIPT`, only where the server can hear a recording: it records with the browser's own
  MediaRecorder and sends the recording with the form, never by a fetch); every other page's policy
  allows no script. The header tells the browser what the markup already does, so nothing a
  payload carried could make a page fetch from elsewhere even if the escaping here were wrong.
- Read-only but for the POSTs above. The pages call the readers; the readers never write (not
  even `policy/stays.json`), and a GET writes nothing: a draft is offered, a proposal is a box, and
  nothing is taken until the owner clicks.

The text grammar is the commands' own (`day.span_text`, `days.night_text`, `gaps.runs`, …), so a
row reads here as it prints there.

`logbook export site` writes the same pages as files (`logbook/contrib/site.py`): a `Site` made with `href`
renders every link through it (a relative path to a file, or None for plain text), through the gate
`tiers` (`reading.read`), with its own `nav` and `footer`, and without the forms and pagers a static
page has nothing to submit to. The rendering is this module's either way. The Day says in its footer
that no model touched it (`NO_MODEL`): its rows are computed and a model's draft is headed as one."""

from __future__ import annotations

import base64
import email
import hashlib
import ipaddress
import json
import math
import re
import secrets
import socketserver
import tempfile
import threading
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from email.utils import collapse_rfc2231_value
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PureWindowsPath
from typing import Any, NamedTuple
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from ..core import assets, day_start, drafts, places, reading, share, signing, stays, trips, weather
from ..core import day as day_reader
from ..core import days as days_reader
from ..core.chain import Line
from ..core.export import parse_day
from ..core.flights import Airports
from ..core.store import NOT_WAITING, HeadMoved, Locked, Logbook
from . import asset_status, dream, gaps, places_review, reflect

HOST = "127.0.0.1"  # the one host the server binds; anything else is refused
PORT = 8765
WINDOW_DAYS = 14  # `/days` without a window: the record's last fortnight
HEAD_CHARS = 12
CSP = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'"
DAY_PATH = re.compile(r"^/day/(\d{4}-\d{2}-\d{2})$")
TODAY = "/today"
RECORD_PAGES = frozenset({"/", "/days", "/trips", "/places"})  # and every Day: the record's, not the clock's
REVIEW_PATH = "/places/review"  # the Places page's writes: POST only, from this machine only
DAY_ACT = re.compile(r"^/day/(\d{4}-\d{2}-\d{2})/(reflect|sign)$")  # the Day's two acts: POST only, likewise
REFLECT, HEAR, SIGN = "reflect", "hear", "sign"  # the acts a Day's forms name
CLOSE = "close"  # the Day page's anchor of Reflect and sign, where a write sends the owner back
PAGE_SIZE = 20  # clusters a page of the review queue; "more" is the next page
FORM_BYTES = 64 * 1024  # the most a form may carry: a name, a reflection, the proposals accepted
AUDIO_BYTES = 64 * 1024 * 1024  # the most a recording may carry: half an hour of speech, even as WAV
STATE_FILES = (places_review.STATE_FILE,)  # record-relative bookkeeping the pages read, in the tag
NO_MODEL = "No model touched this page. What a model drafted is marked as a draft."  # the Day's footer
AUDIO_SUFFIXES = {
    "audio/webm": ".webm",
    "video/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/flac": ".flac",
}  # a recording's suffix when its name gives none, so the engine's decoder knows it
PLACES_SCRIPT = """
(function(){
var keys={Enter:"button[value=name]",n:"button[value=reject]",N:"button[value=reject]"," ":"a.skip"};
function current(){var all=document.querySelectorAll(".cluster");
for(var i=0;i<all.length;i++){if(all[i].getBoundingClientRect().bottom>60)return all[i];}return null;}
document.addEventListener("keydown",function(e){
var t=e.target,tag=t&&t.tagName;
if(e.altKey||e.ctrlKey||e.metaKey)return;
if(tag==="INPUT"||tag==="TEXTAREA"){if(e.key==="Escape")t.blur();return;}
if(tag==="BUTTON"||tag==="A"||tag==="SUMMARY")return;
var c=current(),sel=keys[e.key];if(!c||!sel)return;
var el=c.querySelector(sel);if(!el)return;
e.preventDefault();
if(el.tagName==="A")location.assign(el.getAttribute("href"));else el.click();
});
})();
"""
PLACES_SCRIPT_HASH = (
    "sha256-" + base64.b64encode(hashlib.sha256(PLACES_SCRIPT.encode("utf-8")).digest()).decode()
)
PLACES_CSP = CSP.replace("style-src", f"script-src '{PLACES_SCRIPT_HASH}'; style-src")
DAY_SCRIPT = """
(function(){
var form=document.querySelector("form.audio");if(!form)return;
var button=form.querySelector("button.record"),input=form.querySelector("input[type=file]");
var media=navigator.mediaDevices;
if(!button||!input||!window.MediaRecorder||!window.DataTransfer||!media||!media.getUserMedia)return;
button.hidden=false;
var recorder=null;
button.addEventListener("click",function(){
if(recorder){recorder.stop();return;}
media.getUserMedia({audio:true}).then(function(stream){
var parts=[];recorder=new MediaRecorder(stream);
recorder.ondataavailable=function(e){if(e.data&&e.data.size)parts.push(e.data);};
recorder.onstop=function(){
stream.getTracks().forEach(function(t){t.stop();});
var type=(recorder.mimeType||"audio/webm").split(";")[0];
var ext=/mp4|aac/.test(type)?"m4a":(/ogg/.test(type)?"ogg":"webm");
var t=new DataTransfer();t.items.add(new File(parts,"reflection."+ext,{type:type}));
input.files=t.files;recorder=null;button.disabled=true;button.textContent="Hearing it";form.submit();};
recorder.start();button.textContent="Stop, and hear it";
},function(){button.textContent="No microphone here";button.disabled=true;});
});
})();
"""
DAY_SCRIPT_HASH = "sha256-" + base64.b64encode(hashlib.sha256(DAY_SCRIPT.encode("utf-8")).digest()).decode()
DAY_CSP = CSP.replace("style-src", f"script-src '{DAY_SCRIPT_HASH}'; style-src")
YEAR = re.compile(r"^\d{4}$")
EN_DASH, ARROW, DOT = day_reader.EN_DASH, day_reader.ARROW, day_reader.DOT
HTML = "text/html; charset=utf-8"
Cell = str | tuple[str, str]  # a table cell: text, or (text, css class)
Href = Callable[[str], str | None]  # a server path → the link to write, or None for plain text

STYLE = """
:root{color-scheme:light dark;--fg:#1c1c1c;--bg:#fff;--mute:#6a6a6a;--line:#ddd;--accent:#2f5d7c}
@media (prefers-color-scheme:dark){
:root{--fg:#e8e8e8;--bg:#141414;--mute:#9b9b9b;--line:#333;--accent:#8fb8d6}}
body{margin:0;font:15px/1.45 system-ui,sans-serif;color:var(--fg);background:var(--bg)}
header{border-bottom:1px solid var(--line);padding:.6rem 1rem}
nav{display:flex;flex-wrap:wrap;row-gap:.3rem}
nav a{margin-right:1rem;color:var(--accent);text-decoration:none}
nav a:first-child{font-weight:600}
main{max-width:66rem;margin:0 auto;padding:1rem}
footer{color:var(--mute);font-size:.85rem;padding:1rem;border-top:1px solid var(--line)}
a{color:var(--accent)}
h1{margin:.2rem 0 .6rem}
h1 small{color:var(--mute);font-weight:400;font-size:.6em}
h2{font-size:1.1rem;margin:1.4rem 0 .5rem}
table{border-collapse:collapse;width:100%}
th,td{text-align:left;padding:.3rem .5rem;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mute);font-weight:500}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
td.day{white-space:nowrap}
dl.header{display:grid;grid-template-columns:max-content 1fr;gap:.2rem 1rem;margin:0 0 1rem}
dl.header dt{color:var(--mute)}
dl.header dd{margin:0}
ol.timeline,ol.inside,ul.attached,ul.unplaced,ul.plain{list-style:none;padding:0;margin:0}
.row{padding:.4rem 0;border-bottom:1px solid var(--line)}
.clock{display:inline-block;min-width:7.5rem;font-variant-numeric:tabular-nums;color:var(--mute)}
.kind{display:inline-block;min-width:5.5rem;font-size:.78rem;text-transform:uppercase;letter-spacing:.05em;color:var(--mute)}
.row.stay>.kind{color:#2e8b57}
.row.move>.kind{color:#3a6ec4}
.row.flight>.kind{color:#c0652a}
.row.aboard>.kind{color:#1f7f9a}
.row.gap>.kind{color:#c43b3b}
ol.inside{margin:.3rem 0 0 2rem}
ol.inside .row{border:0;padding:.15rem 0}
details{margin:.3rem 0 0 7.5rem}
summary{cursor:pointer;color:var(--accent)}
ul.attached{margin:.3rem 0 0 1rem}
ul.attached li,ul.unplaced li{padding:.15rem 0}
p.with{margin:.3rem 0 0 1rem;color:var(--mute)}
form.window{display:flex;gap:.6rem;align-items:center;flex-wrap:wrap;margin:0 0 1rem}
input,button{font:inherit;padding:.2rem .4rem;background:var(--bg);color:var(--fg);
border:1px solid var(--line);border-radius:3px}
p.pager,p.mute,.mute{color:var(--mute)}
a.name{font-size:.8rem;margin-left:.5rem}
ol.queue{list-style:none;padding:0;margin:0}
li.cluster{display:grid;grid-template-columns:10rem 1fr;gap:.2rem 1rem;padding:.8rem 0;
border-bottom:1px solid var(--line)}
li.cluster:target{background:color-mix(in srgb,var(--accent) 10%,var(--bg))}
li.cluster svg{grid-row:1/4;width:10rem;height:6.5rem;border:1px solid var(--line);border-radius:3px}
li.cluster svg text{font:11px system-ui,sans-serif;fill:var(--mute)}
li.cluster svg circle.spot{fill:var(--accent)}
li.cluster svg circle.ring,li.cluster svg circle.near{fill:none;stroke:var(--mute);stroke-dasharray:3 2}
li.cluster svg line{stroke:var(--mute)}
li.cluster p.facts{margin:0}
li.cluster p.facts b{font-variant-numeric:tabular-nums}
ul.evidence{list-style:none;padding:0;margin:0;color:var(--mute);font-size:.9rem}
li.cluster details{margin:0;font-size:.9rem}
form.name{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap;margin:.3rem 0 0}
form.name input[type=text]{min-width:16rem;flex:1}
a.skip{display:inline-block;padding:.2rem .4rem;border:1px solid var(--line);border-radius:3px;
text-decoration:none}
@media (max-width:40rem){li.cluster{grid-template-columns:1fr}li.cluster svg{grid-row:auto}}
section.close form{margin:.6rem 0 1rem}
section.close textarea{display:block;width:100%;box-sizing:border-box;min-height:7rem;font:inherit;
padding:.4rem;background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:3px}
section.close button{padding:.35rem .9rem;margin:.4rem .4rem 0 0}
section.close details{margin:.4rem 0}
section.close label{overflow-wrap:anywhere}
section.close input[type=file]{max-width:100%}
ol.proposals,ol.sentences{padding:0;margin:.3rem 0}
ol.proposals{list-style:none}
ol.sentences{padding-left:2rem}
ol.proposals li{padding:.35rem 0;border-bottom:1px solid var(--line)}
ol.proposals label{display:flex;gap:.6rem;align-items:baseline;cursor:pointer}
ol.proposals input{flex:none;width:1.1rem;height:1.1rem}
ul.signed{color:var(--mute);margin:.4rem 0}
code.sha{overflow-wrap:anywhere}
footer .footnote{display:inline-block;margin-top:.3rem}
@media (max-width:40rem){details{margin-left:1rem}.clock{min-width:0;margin-right:.5rem}}
"""

NAV = (
    '<a href="/">Logbook</a><a href="/today">today</a><a href="/days">days</a><a href="/trips">trips</a>'
    '<a href="/places">places</a><a href="/assets">assets</a><a href="/gaps">gaps</a>'
)


class HostError(ValueError):
    """A host other than 127.0.0.1 was asked for."""


class NotFound(Exception):
    """No page at this path."""


class Redirect(Exception):
    """A page that is somewhere else: `/places?at=` landing on a cluster."""

    def __init__(self, location: str):
        super().__init__(location)
        self.location = location


class Voice(NamedTuple):
    """How the Day page hears a recording: `hear`, the path of `day reflect --audio` that the command
    wires in (`commands.day.voice`; contrib never imports labs), or None with `missing`, why this
    machine cannot (the extra, or its model, not here), which the page says in place of the form."""

    hear: Callable[[Path], reflect.Reflection] | None
    missing: str | None = None


class Upload(NamedTuple):
    """A file sent with a form (`multipart/form-data`): the Day page's recording."""

    filename: str
    content_type: str
    data: bytes


class Closing(NamedTuple):
    """What the Day page's Reflect and Sign read of a day, at the head: its lines and those retracted,
    the reflection standing (as `day reflect` reads it with no input) and the proposals the rules
    read in it, the Wispr Flow draft not yet taken, the standing signature and what signing again
    would keep from it, and `digest`, the proposals as shown, which the Sign form carries back."""

    lines: list[Line]
    retracted: set[str]
    reflection: reflect.Reflection | None
    proposals: list[reflect.Proposal]
    draft: reflect.Dictation | None
    earlier: Line | None
    kept: str | None
    digest: str


class Stale(Exception):
    """A Day form older than the record: the reflection, its proposals or the draft it offered are
    not what the page showed; a 409, nothing written."""


class Response(NamedTuple):
    status: int
    body: bytes
    content_type: str = HTML
    etag: str | None = None  # a page of the record at its head: kept by the browser, asked again
    location: str | None = None  # a redirect's target
    csp: str = CSP  # the Places page names its one inline script; every other page allows none

    @property
    def headers(self) -> dict[str, str]:
        found = {
            "Content-Type": self.content_type,
            "Content-Security-Policy": self.csp,
            "Cache-Control": "no-store" if self.etag is None else "no-cache",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        }
        if self.etag is not None:
            found["ETag"] = self.etag
        if self.location is not None:
            found["Location"] = self.location
        if self.status not in (204, 304):
            found["Content-Length"] = str(len(self.body))
        return found


# -- the site --------------------------------------------------------------------------------------------


class Site:
    """The pages of one record. `respond(path, query)` is pure: the same record at the same head
    and the same request give the same page. The airports table is loaded once, here.

    `tiers` reads the record through that gate (`reading.read`); the server reads every tier, since
    nothing leaves the machine. `href` makes the site static (`logbook export site`): every link is
    written as `href(path)` says, a page carries `nav` and `footer` in place of the server's, and no
    form or pager is rendered. `voice` is how the Day page hears a recording (None: it offers none)."""

    def __init__(
        self,
        lb: Logbook,
        airports: Airports | None = None,
        now: Callable[[], datetime] | None = None,
        tiers: Sequence[int] | None = None,
        href: Href | None = None,
        nav: str = NAV,
        footer: str | None = None,
        voice: Voice | None = None,
    ):
        self.lb = lb
        self.airports = airports or Airports.load()
        self.now = now or (lambda: datetime.now(UTC))
        self.tiers = tiers
        self._href = href
        self.static = href is not None
        self.nav = nav
        self.footer = footer
        self.voice = voice
        self._lock = threading.Lock()
        self._review_lock = threading.Lock()  # the queue is read (its table built once) and acted on under it
        # one write at a time: the store's writer lock re-enters within a process, so it keeps out
        # another process's writer, never this server's other thread
        self._write_lock = threading.Lock()
        self._head: str | None = None  # the head the index was last brought to by `current`
        self._started = secrets.token_hex(4)  # in every tag: after a restart (a new version), every page anew

    def href(self, path: str) -> str | None:
        """The link to write for a server path: the path itself, or what `href` makes of it."""
        return path if self._href is None else self._href(path)

    def link(self, text: str, path: str, cls: str = "") -> str:
        """`text` (already escaped) as a link to `path`, or as it is when the path has no page."""
        href = self.href(path)
        if href is None:
            return text
        attrs = f' class="{cls}"' if cls else ""
        return f'<a href="{escape(href)}"{attrs}>{text}</a>'

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(str(self.lb.meta["timezone"]))

    def respond(self, path: str, query: str = "", if_none_match: str | None = None) -> Response:
        """The page at `path`. `if_none_match` is the request's header: when it names the page's
        tag, a 304 and nothing rendered. The tag is taken before the page is read, so a head that
        moves in between makes the tag older than the page, never newer: the next reload reads it
        again rather than keeping a stale page."""
        if path == "/favicon.ico":
            return Response(204, b"", "image/x-icon")
        if path == REVIEW_PATH:
            return self._error(405, f"{REVIEW_PATH} takes the Places page's forms (POST), nothing else")
        if DAY_ACT.match(path) is not None:
            return self._error(405, f"{path} takes the Day page's forms (POST), nothing else")
        meta = self.current()
        if path == TODAY:
            return self._today(meta)
        etag = self.etag(path, query, meta)
        if etag is not None and if_none_match is not None and _matches(if_none_match, etag):
            return Response(304, b"", etag=etag)
        params = {k: v[-1] for k, v in parse_qs(query, keep_blank_values=True).items()}
        csp = PLACES_CSP if path == "/places" else CSP
        if DAY_PATH.match(path) is not None and self._records():
            csp = DAY_CSP
        try:
            return Response(200, self._page(path, params).encode("utf-8"), etag=etag, csp=csp)
        except NotFound:
            return self._error(404, f"no page at {path}")
        except Redirect as r:
            body = f'<p><a href="{escape(r.location)}">{escape(r.location)}</a></p>\n'
            return Response(302, self.document("places", body).encode("utf-8"), location=r.location)
        except (
            stays.SettingsError,
            places.PlaceError,
            assets.AssetError,
            places_review.ReviewError,
            day_start.DayStartError,
        ) as e:
            return self._error(500, str(e))
        except ValueError as e:  # a day that is not one, a window that runs backwards, a year that is not
            return self._error(400, str(e))

    def write(
        self,
        path: str,
        form: Mapping[str, str],
        client: str,
        origin: str | None,
        upload: Upload | None = None,
    ) -> Response:
        """A POST. The Places page's form: `act` `name` (the field `name`, else the name proposed) or
        `reject` on the cluster `id`, through `places_review.accept` and `reject`, the one path the
        CLI's `--name`, `--accept` and `--reject` take. A Day's: Reflect and Sign (`_reflect`,
        `_sign`), through `day reflect`'s own functions. Refused (403, nothing written) unless
        `client`, the connection's address, is loopback and `origin`, the browser's Origin header
        when it sent one, names 127.0.0.1: this machine, the server's own pages. A field sent more
        than once (the Sign form's boxes) arrives as its values joined with commas, as `--accept N,N`
        takes them; `upload` is the file a form carried, the Day's recording.

        On the Places page a cluster no longer in the queue (named or rejected since the page was
        read) is a 409; a name the engine refuses a 400. Done, a 303 to the page the form came from,
        at the next cluster."""
        day_act = DAY_ACT.match(path)
        if path != REVIEW_PATH and day_act is None:
            return self._error(
                404,
                f"nothing to post at {path}; the Places page posts to {REVIEW_PATH}, a Day to"
                " /day/YYYY-MM-DD/reflect and /day/YYYY-MM-DD/sign",
            )
        if not _loopback(client) or (origin is not None and not _loopback_origin(origin)):
            where = f"from {client!r}" + (f", origin {origin!r}" if origin is not None else "")
            what = (
                "a place is named from this machine only, through the server's own pages or"
                " `logbook setup places review`"
                if day_act is None
                else "a day is reflected on and signed from this machine only, through the server's own"
                " pages or `logbook day reflect`"
            )
            return self._error(403, f"refused {where}: {what}; nothing was written")
        if day_act is not None:
            day, act = day_act.group(1), day_act.group(2)
            return self._reflect(day, form, upload) if act == REFLECT else self._sign(day, form)
        act, cluster = form.get("act", ""), form.get("id", "")
        page = form.get("page", "1")
        page = page if page.isdigit() and int(page) >= 1 else "1"
        if act not in ("name", "reject") or not cluster:
            return self._error(400, "the form names a cluster (id) and an act: name or reject")
        with self._write_lock, self._review_lock:
            self.current()
            try:
                report = places_review.read(self.lb)
            except places_review.ReviewError as e:
                return self._error(500, str(e))
            found = [n for n, p in enumerate(report.proposals) if p.id == cluster]
            if not found:
                back = f"/places?page={page}"
                return self._error(
                    409,
                    f"{cluster} is not in the queue: named or rejected already, or the page was older than"
                    f" the record; {back} is the queue as it stands",
                )
            n = found[0]
            proposal = report.proposals[n]
            try:
                if act == "name":
                    given = " ".join(form.get("name", "").split()) or None
                    places_review.accept(self.lb, [(proposal, given)])
                else:
                    places_review.reject(self.lb, [proposal])
            except (places_review.ReviewError, places.PlaceError, stays.SettingsError) as e:
                return self._error(400, str(e))
        following = report.proposals[n + 1 : n + 2]
        location = f"/places?page={page}" + (f"#{following[0].id}" if following else "")
        return Response(303, b"", location=location)

    def _reflect(self, day: str, form: Mapping[str, str], upload: Upload | None) -> Response:
        """Reflect: the words of the field (`act` reflect), written as the day's reflection through
        `reflect.write`, the code `day reflect --text` runs; with `dictation`, the Wispr Flow draft
        the page offered is taken in the words the field holds, as `day reflect`'s y (or e, edited)
        takes it. Or a recording (`act` hear) heard through `Voice.hear`, the path of `day reflect
        --audio`, and written the same way. The same words on the day already are never written
        twice. Done, a 303 to the Day at Reflect and sign, where its proposals are now boxes."""
        act = form.get("act", "")
        if act not in (REFLECT, HEAR):
            return self._error(
                400, "the form names an act: reflect, with your words, or hear, with a recording"
            )
        try:
            day, today = self._closing_day(day)
        except ValueError as e:  # a day ahead, a day that is not one, a day_start that is not a clock
            return self._error(400, str(e))
        heard: reflect.Reflection | None = None
        if act == HEAR:
            if upload is None or not upload.data:
                return self._error(400, "no recording came with the form; choose one, or record one")
            hear = self.voice.hear if self.voice is not None else None
            if hear is None:
                missing = self.voice.missing if self.voice is not None else None
                return self._error(
                    400,
                    missing
                    or f"this server hears no recording; `logbook day reflect {day} --audio FILE` does",
                )
            try:  # heard before the lock is taken: a minute of speech is a while
                with tempfile.TemporaryDirectory(prefix="logbook-reflect-") as folder:
                    recording = Path(folder) / f"reflection{_suffix(upload)}"
                    recording.write_bytes(upload.data)
                    heard = hear(recording)
            except reflect.ReflectError as e:
                return self._error(400, str(e))
        with self._write_lock:
            try:
                with self.lb.writer(command="logbook serve", wait=False):
                    self.current()
                    lines, retracted = reflect.day_lines(self.lb, day)
                    r = heard if heard is not None else self._typed(day, form, lines, retracted)
                    if not r.text.strip():
                        raise reflect.ReflectError("the reflection is empty; say or type a few words")
                    standing = reflect.reflections(lines, retracted)
                    if reflect.same(r.text, standing, r.dictation) is None:  # never written twice
                        reflect.write(self.lb, day, r, None, today)
            except Locked as e:
                return self._error(409, _not_waiting(e))
            except (HeadMoved, Stale) as e:
                return self._error(409, str(e))
            except ValueError as e:  # ReflectError, NoteError, SignError (the note's moment)
                return self._error(400, str(e))
        return Response(303, b"", location=f"/day/{day}#{CLOSE}")

    def _typed(
        self, day: str, form: Mapping[str, str], lines: Sequence[Line], retracted: Collection[str]
    ) -> reflect.Reflection:
        """The reflection the field holds, its line ends plain newlines (a browser sends a field's as
        CRLF): typed, or the Wispr Flow dictation the form names taken in these words; `Stale` when
        that dictation is no longer on the day."""
        text = form.get("text", "").replace("\r\n", "\n").replace("\r", "\n").strip()
        named = form.get("dictation", "").strip()
        if not named:
            return reflect.Reflection(text, reflect.TYPED)
        found = [d for d in reflect.dictations(self.lb, lines, retracted) if d.id == named]
        if not found:
            raise Stale(
                f"the Wispr Flow dictation this page offered is no longer on {day}; /day/{day} is the day"
                " as it stands, and nothing was written"
            )
        return reflect.dictated(found[0], text)

    def _sign(self, day: str, form: Mapping[str, str]) -> Response:
        """Sign: the day signed through `reflect.close`, the code `day reflect --sign` runs, with the
        reflection standing on the day and the proposals ticked (`accept`, N,N as `--accept` takes
        them; none ticked accepts none): the accepted delegations written as notes, then
        `signing.sign` with the lines confirmed, the accepted dispositions and the reflection, now.
        A day signed already is signed again, the new signature superseding it and keeping what it
        said. Refused (409, nothing written) when the reflection or its proposals are not those the
        page showed (`reflection`, `proposals`), and when there is no reflection to sign with."""
        if form.get("act") != SIGN:
            return self._error(400, "the form names the act: sign")
        try:
            day, today = self._closing_day(day)
            wanted = reflect.numbers(form.get("accept") or reflect.NONE)
        except ValueError as e:
            return self._error(400, str(e))
        with self._write_lock:
            try:
                with self.lb.writer(command="logbook serve", wait=False):
                    self.current()
                    found = self._closing(day)
                    r = found.reflection
                    if r is None or r.note is None:
                        raise Stale(
                            f"nothing to sign {day} with: reflect first, and the day is signed with your"
                            f" reflection among the lines it confirms (`logbook day sign {day}` signs it"
                            " without one); nothing was written"
                        )
                    if form.get("reflection") != str(r.note["id"]) or form.get("proposals") != found.digest:
                        raise Stale(
                            f"the reflection or its proposals changed since this page was read; /day/{day}"
                            " is the day as it stands, and nothing was written"
                        )
                    accepted = reflect.chosen(found.proposals, wanted)
                    reflect.close(self.lb, day, today, r, accepted)
            except Locked as e:
                return self._error(409, _not_waiting(e))
            except (HeadMoved, Stale) as e:
                return self._error(409, str(e))
            except ValueError as e:  # ReflectError, SignError, NoteError
                return self._error(400, str(e))
        return Response(303, b"", location=f"/day/{day}#{CLOSE}")

    def _closing_day(self, day: str) -> tuple[str, str]:
        """The day and today as the record defines them (its zone and `day_start`); `ReflectError` for
        a day ahead of today, as `day reflect` refuses one."""
        day = parse_day(day).isoformat()
        today = day_start.of(self.lb.meta).today(self.now()).isoformat()
        reflect.on_or_before(day, today, str(self.lb.meta["timezone"]))
        return day, today

    def _closing(self, day: str) -> Closing:
        """What Reflect and Sign read of `day`, as `day reflect DAY --sign` reads it with no input."""
        lines, retracted = reflect.day_lines(self.lb, day)
        standing = reflect.reflections(lines, retracted)
        pending = reflect.drafts(reflect.dictations(self.lb, lines, retracted), standing)
        r = reflect.on_the_day(standing[-1]) if standing else None
        proposals: list[reflect.Proposal] = []
        if r is not None and r.note is not None:
            mine = str(r.note["id"])
            proposals = reflect.propose(r.text, day, reflect.commitments(self.lb, day, {mine}))
        with self.lb.index() as idx:
            earlier = signing.signature_of(idx, day, str(self.lb.meta["owner_id"]))
        kept = None
        if earlier is not None and r is not None and r.note is not None:
            page = reflect.on_page(lines, retracted)
            kept = reflect.signature(earlier, page, [str(r.note["id"])], []).kept
        shown = json.dumps([p.to_json() for p in proposals], sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(shown.encode("utf-8")).hexdigest()[:16]
        draft = pending[-1] if pending else None
        return Closing(lines, retracted, r, proposals, draft, earlier, kept, digest)

    def _records(self) -> bool:
        """Whether a Day page carries the recording form and its script: a server that can hear."""
        return not self.static and self.voice is not None and self.voice.hear is not None

    def current(self) -> dict[str, Any]:
        """`logbook.json` as it is now. When its head has moved since the last request (a sync
        appended while the server runs), the index is brought to the new head here, once, under a
        lock, before any page reads it: the requests that arrive together wait for that one rebuild
        instead of each starting its own on the same file."""
        meta = self.lb.meta
        head = str(meta.get("head"))
        if head != self._head:
            with self._lock:
                if head != self._head:
                    with self.lb.index():
                        pass
                    self._head = head
        return meta

    def etag(self, path: str, query: str, meta: Mapping[str, Any]) -> str | None:
        """The tag of a page that is the record's and nothing else: the head, then a digest of the
        request and what else the pages read — the rest of `logbook.json`, the settings beside the
        chain (`places.json`, `assets.json`, `policy/`), the review's bookkeeping in `state/`, the
        pages received from the circle, this server's start, and for a Day the day the owner is in
        (its forms are there from that day on). One page's tag never stands for
        another's, and a request that is an error is given none. None for a page the clock moves
        (`/assets`, `/gaps`) or a path with no page."""
        if path not in RECORD_PAGES and DAY_PATH.match(path) is None:
            return None
        root = self.lb.root
        circle = root / share.CIRCLE_DIR
        senders = sorted(p for p in circle.iterdir() if p.is_dir()) if circle.is_dir() else []
        read = [
            root / places.PLACES_FILE,
            root / assets.ASSETS_FILE,
            *sorted((root / "policy").glob("*.json")),
            *(root.joinpath(*f.parts) for f in STATE_FILES),
            circle,
            *senders,
        ]
        parts = [self._started, path, query, json.dumps(meta, sort_keys=True)]
        if DAY_PATH.match(path) is not None:  # its forms are there from the day the owner is in
            try:
                parts.append(day_start.of(meta).today(self.now()).isoformat())
            except day_start.DayStartError:
                parts.append("-")
        for file in read:
            try:
                st = file.stat()
            except OSError:
                parts.append(f"{file.relative_to(root).as_posix()} -")
                continue
            parts.append(f"{file.relative_to(root).as_posix()} {st.st_mtime_ns} {st.st_size} {st.st_ino}")
        digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
        return f'"{str(meta.get("head") or "")[:HEAD_CHARS]}-{digest[:16]}"'

    def _today(self, meta: Mapping[str, Any]) -> Response:
        """A redirect to the Day the owner is in now: the current date in the record's timezone,
        the date before until the record's `day_start` (RFC 0036); never kept, since it moves."""
        try:
            day = day_start.of(meta).today(self.now()).isoformat()
        except day_start.DayStartError as e:
            return self._error(500, str(e))
        body = f'<p><a href="/day/{day}">{day}</a></p>\n'
        return Response(302, self.document("today", body).encode("utf-8"), location=f"/day/{day}")

    def _page(self, path: str, params: Mapping[str, str]) -> str:
        if path == "/":
            return self.page_index()
        if (m := DAY_PATH.match(path)) is not None:
            return self.page_day(m.group(1), expanded=params.get("open") == "1")
        if path == "/days":
            return self.page_days(params.get("from") or None, params.get("to") or None)
        if path == "/trips":
            return self.page_trips(params.get("year") or None)
        if path == "/places":
            return self.page_places(params.get("page") or "1", params.get("at") or None)
        if path == "/assets":
            return self.page_assets()
        if path == "/gaps":
            return self.page_gaps(params.get("since") or None)
        raise NotFound(path)

    def _error(self, status: int, message: str) -> Response:
        body = f"<h1>{status}</h1>\n<p>{escape(message)}</p>\n"
        return Response(status, self.document(str(status), body).encode("utf-8"))

    def document(self, title: str, body: str, script: str | None = None, footnote: str | None = None) -> str:
        """One HTML document: the head, the navigation, `body`, the footer and `footnote` under it;
        `script` is the one inline script a page may carry (the Places page's keys, the Day's record
        button), named by hash in that page's policy."""
        meta = self.lb.meta
        head = str(meta.get("head") or "")[:HEAD_CHARS]
        footer = (
            f"read-only{DOT}head <code>{escape(head)}…</code>{DOT}{escape(str(meta.get('timezone')))}"
            f"{DOT}nothing here leaves this machine"
            if self.footer is None
            else self.footer
        )
        if footnote is not None:
            footer += f'<br><span class="footnote">{escape(footnote)}</span>'
        return (
            "<!doctype html>\n"
            '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{escape(title)} · Logbook</title>\n"
            f"<style>{STYLE}</style>\n</head>\n<body>\n"
            f"<header><nav>{self.nav}</nav></header>\n<main>\n{body}</main>\n"
            f"<footer>{footer}</footer>\n{'' if script is None else f'<script>{script}</script>' + chr(10)}"
            "</body>\n</html>\n"
        )

    def _whole(self) -> tuple[str, str] | None:
        """The days the owner's track covers, else any line's; None for an empty record."""
        return reading.record_days(self.lb, "location") or reading.record_days(self.lb)

    # -- / --------------------------------------------------------------------------------------------------

    def page_index(self) -> str:
        with self.lb.index() as idx:
            total, first, last = idx.totals()
        whole = self._whole()
        parts = ["<h1>Logbook</h1>\n"]
        if whole is None or first is None or last is None:
            parts.append("<p>The record has no lines yet.</p>\n")
            return self.document("Logbook", "".join(parts))
        days = day_start.of(self.lb.meta)
        parts.append(
            f"<p>{total:,} lines, {escape(days.day_of(first))} {EN_DASH} {escape(days.day_of(last))}"
            f" ({escape(str(days.zone))}{'' if days.midnight else f', the day begins at {days.text}'}).</p>\n"
        )
        a, b = _last_window(whole)
        year = whole[1][:4]
        parts.append(
            '<ul class="plain">\n'
            f"<li>{self.link('The last day', f'/day/{whole[1]}')}, {whole[1]}: the Day as a timeline.</li>\n"
            f"<li>{self.link('The last fortnight', f'/days?from={a}&to={b}')}, one row per day.</li>\n"
            f"<li>{self.link(f'Trips of {year}', f'/trips?year={year}')}: runs of nights away.</li>\n"
            f"<li>{self.link('Places', '/places')}: the named places of the record.</li>\n"
            f"<li>{self.link('Assets', '/assets')}: the assets tracked and the last fix of each.</li>\n"
            f"<li>{self.link('Gaps', '/gaps')}: where each source went quiet.</li>\n"
            "</ul>\n"
        )
        return self.document("Logbook", "".join(parts))

    # -- /day/YYYY-MM-DD ------------------------------------------------------------------------------------

    def page_day(self, day: str, expanded: bool = False) -> str:
        """The Day; with `expanded` every toggle is open, so a page prints or saves whole."""
        data = day_reader.read(self.lb, day, self.airports, self.tiers)
        tz = ZoneInfo(data["tz"])
        d = date.fromisoformat(day)
        before, after = (d - timedelta(days=1)).isoformat(), (d + timedelta(days=1)).isoformat()
        a, b = (d - timedelta(days=6)).isoformat(), (d + timedelta(days=7)).isoformat()
        toggle = (
            self.link("collapse all", f"/day/{day}")
            if expanded
            else self.link("expand all", f"/day/{day}?open=1")
        )
        close = "" if self.static else f'<a href="/day/{day}#{CLOSE}">reflect and sign</a>{DOT}'
        parts = [
            f"<h1>{day} <small>{escape(data['weekday'])}</small></h1>\n",
            f'<p class="pager">{self.link(f"← {before}", f"/day/{before}")}{DOT}'
            f"{self.link('the fortnight around', f'/days?from={a}&to={b}')}{DOT}{toggle}{DOT}{close}"
            f"{self.link(f'{after} →', f'/day/{after}')}</p>\n",
            '<dl class="header">\n',
            *(
                [_dt("the day", day_start.span_words(data["day_start"]))]
                if data.get("day_start", day_start.MIDNIGHT) != day_start.MIDNIGHT
                else []
            ),
            _dt("night before", day_reader.night_text(data["nights"]["before"])),
            _dt("night after", day_reader.night_text(data["nights"]["after"])),
            _dt("country", day_reader.country_text(data["country"])),
            _signed_html(data.get("signed")),
        ]
        if data["all_day"]:
            parts.append(
                _dt("all day", ", ".join(a["title"] + day_reader.sources_text(a) for a in data["all_day"]))
            )
        parts.append("</dl>\n")
        if data.get("reflection"):  # the owner's words, above the record (`day reflect`)
            parts.append(_reflection_html(data["reflection"], tz))
        if data.get("draft"):
            parts.append(_draft_html(data["draft"]))
        if data.get("draft_withheld"):  # the policy no longer allows it: the row, never the text
            parts.append(_withheld_html(data["draft_withheld"], heading=not data.get("draft")))
        parts.append("<h2>Timeline</h2>\n")
        if data["timeline"]:
            parts.append('<ol class="timeline">\n')
            name_this = None if self.static else self._name_this
            parts.extend(
                _entry_html(entry, tz, expanded=expanded, name_this=name_this) for entry in data["timeline"]
            )
            parts.append("</ol>\n")
        else:
            parts.append('<p class="mute">nothing logged</p>\n')
        if data["unplaced"]:
            parts.append('<h2>Unplaced</h2>\n<ul class="unplaced">\n')
            for item in data["unplaced"]:
                span = day_reader.span_text(item["at"], item["end"], tz)
                parts.append(
                    f'<li title="line {escape(item["line"])}"><span class="clock">{escape(span)}</span> '
                    f'<span class="kind">{escape(item["kind"])}</span> '
                    f"{escape(item['title'] + day_reader.sources_text(item))}</li>\n"
                )
            parts.append("</ul>\n")
        parts.append(f"<h2>Health</h2>\n<p>{escape(day_reader.health_text(data['health']))}</p>\n")
        if data.get("weather"):
            parts.append(f"<h2>Weather</h2>\n<p>{escape(weather.text(data['weather'], data['tz']))}</p>\n")
        parts.append("<h2>Sources</h2>\n")
        if data["sources"]:
            rows: list[list[Cell]] = [
                [
                    escape(s["source"]),
                    _num(s["lines"]),
                    escape(_clock(s["first"], tz)),
                    escape(_clock(s["newest"], tz)),
                ]
                for s in data["sources"]
            ]
            parts.append(_table(["source", ("lines", "num"), "first", "last"], rows))
        else:
            parts.append('<p class="mute">none</p>\n')
        for page in data.get("received") or []:  # a page someone shared for the day (RFC 0025)
            parts.append(f"<h2>From {escape(str(page['from']))}</h2>\n")
            parts.append(f"<p>{escape(day_reader.received_text(page))}</p>\n")
            if page["named"]:
                parts.append('<ul class="unplaced">\n')
                for item in page["named"]:
                    line, kind, title = escape(item["line"]), escape(item["kind"]), escape(item["title"])
                    parts.append(f'<li title="line {line}"><span class="kind">{kind}</span> {title}</li>\n')
                parts.append("</ul>\n")
        script = None
        if not self.static:
            closing, records = self._close_html(day)
            parts.append(closing)
            script = DAY_SCRIPT if records else None
        return self.document(f"{day} {data['weekday']}", "".join(parts), script, NO_MODEL)

    def _close_html(self, day: str) -> tuple[str, bool]:
        """Reflect and sign, at the foot of the Day: the reflection's field (the Wispr Flow draft
        prefilled when one is waiting, else the reflection standing), the recording form when the
        server can hear one, then the standing signature as `day sign` prints it, and the Sign form:
        the proposals as boxes, none ticked. Nothing here is written until a button is clicked. With
        it, whether the page carries the recording form (and so its script)."""
        tz = self.tz
        out = [f'<section class="close">\n<h2 id="{CLOSE}">Reflect and sign</h2>\n']
        try:
            self._closing_day(day)
        except reflect.ReflectError:
            out.append(
                f'<p class="mute">{day} is ahead of today in {escape(str(tz))}; a day is reflected on and'
                " signed on it or after it</p>\n</section>\n"
            )
            return "".join(out), False
        found = self._closing(day)
        r = found.reflection
        if found.earlier is not None:  # the signature first: what Sign leaves the owner looking at
            out.append('<ul class="plain signed">\n')
            out.extend(f"<li>{escape(text.strip())}</li>\n" for text in signing.summary(found.earlier))
            out.append("</ul>\n")
        out.append(f'<form class="reflect" method="post" action="/day/{day}/reflect">\n')
        if found.draft is not None:
            d = found.draft
            out.append(
                f'<p class="mute">The Wispr Flow dictation #{d.seq} of {escape(_clock(d.at, tz)[11:])} begins'
                f" with \u201c{reflect.CUE}\u201d: its words are below, without that word, a draft until"
                " Reflect takes them (change them first if they need it).</p>\n"
                f'<input type="hidden" name="dictation" value="{escape(d.id)}">\n'
            )
            text = reflect.without_cue(d.text)
        elif r is not None and r.note is not None:
            when = escape(_clock(str(r.note["at"]), tz)[11:])
            out.append(
                f'<p class="mute">Your reflection #{r.note["seq"]} of {when}'
                " is below; Reflect writes changed words as the day's reflection, the same words never"
                " twice.</p>\n"
            )
            text = r.text
        else:
            out.append(
                '<p class="mute">A few sentences about the day, in your words: what went out, what did not,'
                " what you will do, what someone else should. Rules, no model, read them for proposals.</p>\n"
            )
            text = ""
        language = dream.language_of(_texts(found.lines, found.retracted))
        out.append(
            f'<textarea name="text" rows="6" lang="{escape(language)}" aria-label="your reflection"'
            f' spellcheck="true">{escape(text, quote=False)}</textarea>\n'
            '<button name="act" value="reflect">Reflect</button>\n</form>\n'
        )
        records = self._records()
        if records:
            out.append(
                f'<form class="audio" method="post" action="/day/{day}/reflect"'
                ' enctype="multipart/form-data">\n'
                f'<input type="hidden" name="act" value="{HEAR}">\n'
                "<label>or say it: a recording, heard on this machine "
                '<input type="file" name="audio" accept="audio/*" capture></label>\n'
                '<button>Hear it</button> <button type="button" class="record" hidden>Record</button>\n'
                "</form>\n"
            )
        elif self.voice is not None and self.voice.missing:
            out.append(f'<p class="mute">To reflect by voice here: {escape(self.voice.missing)}.</p>\n')
        if r is None or r.note is None:
            out.append(
                '<p class="mute">Reflect first: Sign signs the day with your reflection among the lines it'
                f" confirms, as <code>logbook day reflect {day} --sign</code> does; <code>logbook day sign"
                f" {day}</code> signs it without one.</p>\n</section>\n"
            )
            return "".join(out), records
        out.append(self._sign_html(day, found, r.note))
        out.append("</section>\n")
        return "".join(out), records

    def _sign_html(self, day: str, found: Closing, note: Line) -> str:
        """The Sign form: the proposals, a box each as `day reflect` numbers them (rules alone, none
        ticked: a guess until the owner accepts it), the reflection a sentence a line folded beside
        them, what signing confirms or keeps, and the button."""
        r = found.reflection
        assert r is not None
        out = [
            f'<form class="sign" method="post" action="/day/{day}/sign">\n'
            f'<input type="hidden" name="reflection" value="{escape(str(note["id"]))}">\n'
            f'<input type="hidden" name="proposals" value="{escape(found.digest)}">\n'
        ]
        if found.proposals:
            out.append(
                '<p class="mute">proposals, by rules alone; each is a guess until you accept it:</p>\n'
                '<ol class="proposals">\n'
            )
            for p in found.proposals:
                word, what = reflect.proposal_words(p)
                out.append(
                    f'<li><label><input type="checkbox" name="accept" value="{p.number}">'
                    f' <span><b>{p.number}</b> <span class="kind">{escape(word)}</span> line {p.sentence}'
                    f"{DOT}{escape(what, quote=False)}</span></label></li>\n"
                )
            out.append("</ol>\n")
        else:
            out.append(
                '<p class="mute">no proposals: the rules read no commitment, delegation or disposition in'
                " it</p>\n"
            )
        sentences = "".join(f"<li>{escape(text)}</li>" for text in reflect.sentences(r.text))
        out.append(
            f'<details><summary>the reflection, a sentence a line</summary><ol class="sentences">{sentences}'
            "</ol></details>\n"
        )
        if found.earlier is None:
            said = (
                f"Sign confirms every line on the page, your reflection #{note['seq']} among them, writes"
                " the delegations you tick and puts the dispositions you tick in the signature."
            )
            button = "Sign"
        else:
            kept = found.kept or "keeps nothing from the one it supersedes"
            said = (
                f"Sign again, and the new signature {kept}; your reflection #{note['seq']} is among the"
                " lines it confirms."
            )
            button = "Sign again"
        out.append(f'<p class="mute">{escape(said)}</p>\n')
        out.append(f'<button name="act" value="{SIGN}">{button}</button>\n</form>\n')
        return "".join(out)

    def _name_this(self, entry: Mapping[str, Any]) -> str:
        """The "name this place" link of a stay printed as coordinates: the Places page at its
        cluster (`/places?at=lat,lon`). Nothing for a named stay, a move, or a stay with no fix."""
        if entry["kind"] not in (stays.STAY, stays.STOP) or entry.get("place") or entry.get("lat") is None:
            return ""
        at = f"{entry['lat']:.4f},{entry['lon']:.4f}"
        return f' <a class="name" href="/places?at={at}">name this place</a>'

    # -- /days ----------------------------------------------------------------------------------------------

    def page_days(self, first: str | None, last: str | None) -> str:
        whole = self._whole()
        if whole is None:
            return self.document("days", "<h1>Days</h1>\n<p>no days: the record has no lines</p>\n")
        if last is None:
            last = whole[1] if first is None else _clip(first, WINDOW_DAYS - 1, whole)
        else:
            last = parse_day(last).isoformat()
        first = _clip(last, -(WINDOW_DAYS - 1), whole) if first is None else parse_day(first).isoformat()
        rows: list[list[Cell]] = []
        ids: list[str] = []
        for r in days_reader.read(self.lb, first, last, self.airports, tiers=self.tiers):
            people = ", ".join(r["people"]["names"])
            ids.append(str(r["day"]))
            rows.append(
                [
                    (self.link(str(r["day"]), f"/day/{r['day']}"), "day"),
                    escape(r["weekday"][:3]),
                    escape(days_reader.night_text(r)),
                    (escape(days_reader.km_text(r["moved_m"])), "num"),
                    escape(", ".join(days_reader.flight_text(f) for f in r["flights"])),
                    escape(days_reader.stays_text(r["stays"]) if r["sources"] else "nothing logged"),
                    escape(people),
                    escape(day_reader.health_text(r["health"]) if r["health"] is not None else ""),
                    escape(", ".join(r["gaps"])),
                ]
            )
        span = (date.fromisoformat(last) - date.fromisoformat(first)).days + 1
        earlier = (
            (date.fromisoformat(first) - timedelta(days=span)).isoformat(),
            (date.fromisoformat(first) - timedelta(days=1)).isoformat(),
        )
        later = (
            (date.fromisoformat(last) + timedelta(days=1)).isoformat(),
            (date.fromisoformat(last) + timedelta(days=span)).isoformat(),
        )
        body = f"<h1>Days <small>{first} {EN_DASH} {last}</small></h1>\n"
        if not self.static:
            body += (
                f'<form class="window" action="/days" method="get">'
                f'<label>from <input type="date" name="from" value="{first}"></label> '
                f'<label>to <input type="date" name="to" value="{last}"></label> '
                f"<button>show</button></form>\n"
                f'<p class="pager"><a href="/days?from={earlier[0]}&amp;to={earlier[1]}">← earlier</a>{DOT}'
                f'<a href="/days?from={later[0]}&amp;to={later[1]}">later →</a>{DOT}'
                f"the record runs {whole[0]} {EN_DASH} {whole[1]}</p>\n"
            )
        body += _table(
            ["day", "", "night", ("moved", "num"), "flights", "stays", "with", "health", "gaps"],
            rows,
            ids if self.static else None,
        )
        return self.document(f"days {first} {EN_DASH} {last}", body)

    # -- /trips ---------------------------------------------------------------------------------------------

    def page_trips(self, year: str | None) -> str:
        whole = self._whole()
        if whole is None:
            return self.document("trips", "<h1>Trips</h1>\n<p>no trips: the record has no days</p>\n")
        year = year or whole[1][:4]
        if not YEAR.fullmatch(year):
            raise ValueError(f"not a year (YYYY): {year!r}")
        years = range(int(whole[0][:4]), int(whole[1][:4]) + 1)
        links = DOT.join(
            f"<b>{y}</b>" if str(y) == year else self.link(str(y), f"/trips?year={y}") for y in years
        )
        parts = [f"<h1>Trips <small>{year}</small></h1>\n", f'<p class="pager">{links}</p>\n']
        first, last = max(f"{year}-01-01", whole[0]), min(f"{year}-12-31", whole[1])
        if last < first:
            parts.append(f"<p>no days in {year}: the record runs {whole[0]} {EN_DASH} {whole[1]}</p>\n")
            return self.document(f"trips {year}", "".join(parts))
        rd = reading.read(self.lb, first, last, self.airports, self.tiers)
        found, warning = trips.trips(rd)
        if warning:
            parts.append(f"<p>{escape(warning)}</p>\n")
        elif not found:
            parts.append(f"<p>no trips {first} {EN_DASH} {last}</p>\n")
        else:
            parts.append(
                _table(
                    ["days", "nights", "route", "flights", "places", "with"],
                    [self.trip_row(t, rd) for t in found],
                )
            )
        return self.document(f"trips {year}", "".join(parts))

    def trip_row(self, trip: trips.Trip, rd: reading.Reading) -> list[Cell]:
        """One row of the trips table; the dates link the trip's days (`/days?from=&to=`, which a
        static site maps to the trip's own page)."""
        dates = self.link(f"{trip.start} {EN_DASH} {trip.end}", f"/days?from={trip.start}&to={trip.until}")
        return _trip_row(trip, rd, dates)

    # -- /places, /assets, /gaps ----------------------------------------------------------------------------

    def page_places(self, page: str = "1", at: str | None = None) -> str:
        """The named places first (name, nights, last visit: from the observed places), then
        "Name this place": the review queue in the CLI's order, `PAGE_SIZE` a page, each cluster
        with a dot on a plain canvas, its counts, its evidence folded, and a form. A static site
        gets the named places alone. `at=lat,lon` (the Day's link) is a redirect to the page the
        nearest cluster is on, at that cluster, or this page with a note when there is none."""
        if not page.isdigit() or int(page) < 1:
            raise ValueError(f"page must be a number from 1, not {page!r}")
        with self._review_lock:  # requests that arrive together wait for one build of the table
            report = places_review.read(self.lb)
        tz = report.tz
        note = ""
        if at is not None:
            lat, lon = places.parse_stay_id(at)
            near = [
                (m, p)
                for p in report.proposals
                if (m := places.distance_m(lat, lon, p.lat, p.lon)) <= places_review.MATCH_M
            ]
            if near:
                p = min(near, key=lambda pair: pair[0])[1]
                on = (report.proposals.index(p) // PAGE_SIZE) + 1
                raise Redirect(f"/places?page={on}#{p.id}")
            note = f"no place to name at {lat:.4f},{lon:.4f}: it is named or rejected, or it was never a stay"
        body = "<h1>Places</h1>\n"
        if note:
            body += f'<p class="mute">{escape(note)}</p>\n'
        body += self._named_places(report)
        if self.static:
            return self.document("places", body)
        total = len(report.proposals)
        pages = max(1, math.ceil(total / PAGE_SIZE))
        n = min(int(page), pages)
        first = (n - 1) * PAGE_SIZE
        shown = report.proposals[first : first + PAGE_SIZE]
        body += f"<h2>Name this place <small>{escape(places_review.head(report))}</small></h2>\n"
        if not report.observed:
            body += "<p>no places observed: the record has no stays yet</p>\n"
            return self.document("places", body)
        if not shown:
            body += "<p>nothing to review: every place you return to is named</p>\n"
            return self.document("places", body)
        body += (
            '<p class="mute">The places you return to that have no name yet, by nights then hours, each'
            " with what the record already says about it. Name writes the field into places.json and the"
            " naming into the record, as <code>setup places review</code> does; Not a place keeps the"
            " spot out of the queue; Skip moves on. Keys: Enter names, n is not a place, Space skips.</p>\n"
        )
        body += f'<ol class="queue" start="{first + 1}">\n'
        for k, p in enumerate(shown):
            following = shown[k + 1 : k + 2]
            skip = (
                f"/places?page={n}#{following[0].id}"
                if following
                else (f"/places?page={n + 1}" if n < pages else "")
            )
            body += self._cluster_html(p, tz, n, skip)
        body += "</ol>\n"
        last = first + len(shown)
        pager = [f"{first + 1}{EN_DASH}{last} of {total}"]
        if n > 1:
            pager.insert(0, f'<a href="/places?page={n - 1}">← earlier</a>')
        if n < pages:
            pager.append(f'<a href="/places?page={n + 1}">more →</a>')
        body += f'<p class="pager">{DOT.join(pager)}</p>\n'
        return self.document("places", body, PLACES_SCRIPT)

    def _named_places(self, report: places_review.Report) -> str:
        found = report.places
        if not found:
            return (
                f"<p>no places ({escape(places.PLACES_FILE)}) yet: name one below, or"
                " `logbook setup places add`</p>\n"
            )
        nights: dict[str, int] = {}
        last: dict[str, str] = {}
        for o in report.observed:
            if o.place is None:
                continue
            nights[o.place] = nights.get(o.place, 0) + o.nights
            last[o.place] = max(last.get(o.place, ""), o.last)
        days = day_start.of(self.lb.meta)  # the last visit's day, by the record's own boundary
        rows: list[list[Cell]] = []
        for p in sorted(found, key=lambda p: (-nights.get(p.name, 0), p.name.casefold())):
            rows.append(
                [
                    escape(p.name),
                    _num(nights.get(p.name, 0)),
                    escape(days.day_of(last[p.name])) if p.name in last else "",
                    escape(p.kind),
                    (f"{p.lat:.4f},{p.lon:.4f}", "num"),
                    (escape(_number(p.radius_m)) + " m", "num"),
                    escape(", ".join(p.tags)),
                    escape(p.country or ""),
                ]
            )
        return _table(
            [
                "name",
                ("nights", "num"),
                "last visit",
                "kind",
                ("position", "num"),
                ("radius", "num"),
                "tags",
                "country",
            ],
            rows,
        )

    def _cluster_html(self, p: places_review.Proposal, tz: ZoneInfo, page: int, skip: str) -> str:
        """One cluster of the queue: the canvas, the facts (`places_review.summary`), the evidence
        folded (three lines, the rest behind a toggle), and the form."""
        lines = [places_review.group_text(g) for g in places_review.groups(p.observed.names)]
        out = [
            f'<li class="cluster" id="{escape(p.id)}">\n{_spot_svg(p)}\n',
            f'<p class="facts"><b>{p.number}.</b> {escape(places_review.summary(p, tz), quote=False)}</p>\n',
        ]
        if not lines:
            out.append('<ul class="evidence"><li>no source names it</li></ul>\n')
        else:
            out.append('<ul class="evidence">\n')
            out.extend(f"<li>{escape(line, quote=False)}</li>\n" for line in lines[: places_review.SHOWN])
            out.append("</ul>\n")
            rest = lines[places_review.SHOWN :]
            if rest:
                out.append(f'<details><summary>… and {len(rest)} more</summary>\n<ul class="evidence">\n')
                out.extend(f"<li>{escape(line, quote=False)}</li>\n" for line in rest)
                out.append("</ul>\n</details>\n")
        out.append(
            f'<form class="name" method="post" action="{REVIEW_PATH}">'
            f'<input type="hidden" name="id" value="{escape(p.id)}">'
            f'<input type="hidden" name="page" value="{page}">'
            f'<input type="text" name="name" value="{escape(p.name or "")}" placeholder="what you call it"'
            f' aria-label="name" autocomplete="off">'
            '<button name="act" value="name">Name</button>'
        )
        if skip:
            out.append(f'<a class="skip" href="{escape(skip)}">Skip</a>')
        out.append('<button name="act" value="reject">Not a place</button></form>\n</li>\n')
        return "".join(out)

    def page_assets(self) -> str:
        registry = assets.read(self.lb.root)
        body = "<h1>Assets</h1>\n"
        if not registry:
            body += f"<p>no assets registered ({escape(assets.ASSETS_FILE)}); `logbook assets add`</p>\n"
            return self.document("assets", body)
        named = places.read(self.lb.root)
        statuses = asset_status.read(self.lb, registry, named, self.now())
        tz = self.tz
        rows: list[list[Cell]] = []
        for status in statuses:
            asset, fix = status.asset, status.fix
            ids = ", ".join(f"{k} {v}" for k in assets.IDENTIFIERS if (v := getattr(asset, k)) is not None)
            row: list[Cell] = [escape(asset.id), escape(asset.kind), escape(asset.name), escape(ids)]
            if fix is None:
                row += [("no fix yet", ""), "", "", "", ""]
            else:
                near = "" if fix.near is None else f"near {fix.near[0]}, {_metres(fix.near[1])}"
                row += [
                    escape(_clock(fix.at, tz)),
                    (f"{fix.lat:.4f},{fix.lon:.4f}", "num"),
                    escape(near),
                    ("" if fix.speed_mps is None else f"{fix.speed_mps:.1f} m/s", "num"),
                    escape(asset_status.age_text(fix.age_s)),
                ]
            rows.append(row)
        body += _table(
            [
                "id",
                "kind",
                "name",
                "identifiers",
                "last fix",
                ("position", "num"),
                "near",
                ("speed", "num"),
                "age",
            ],
            rows,
        )
        return self.document("assets", body)

    def page_gaps(self, since: str | None) -> str:
        data = gaps.report(self.lb, since=since)
        tz = ZoneInfo(data["timezone"])
        body = (
            "<h1>Gaps <small>where each source went quiet</small></h1>\n"
            f'<form class="window" action="/gaps" method="get">'
            f'<label>since <input type="date" name="since" value="{escape(data["since"] or "")}"></label> '
            "<button>show</button></form>\n"
        )
        if not data["sources"]:
            body += "<p>no lines</p>\n"
            return self.document("gaps", body)
        rows: list[list[Cell]] = []
        for s in data["sources"]:
            if s["lines"] == 0:
                rows.append([escape(s["source"]), ("0", "num"), "", "", "no lines", ("0", "num"), ""])
                continue
            silence = s["silence"]
            if silence["to"] is None:
                stretch = f"{gaps.duration(silence['seconds'])} since {_clock(silence['from'], tz)}"
            else:
                ends = f"{_clock(silence['from'], tz)} {ARROW} {_clock(silence['to'], tz)}"
                stretch = f"{gaps.duration(silence['seconds'])} {ends}"
            missing = s["missing_days"]
            rows.append(
                [
                    escape(s["source"]),
                    _num(s["lines"]),
                    escape(_clock(s["first"], tz)),
                    escape(_clock(s["last"], tz)),
                    escape(stretch),
                    _num(len(missing)),
                    escape(gaps.runs(missing)),
                ]
            )
        body += _table(
            ["source", ("lines", "num"), "first", "last", "longest silence", ("missing days", "num"), ""],
            rows,
        )
        span = f"since {data['since']}" if data["since"] else "since each source's first line"
        body += (
            f'<p class="mute">{escape(span)}, today {escape(data["today"])} ({escape(data["timezone"])});'
            " counted through the index, every line, retracted or not</p>\n"
        )
        return self.document("gaps", body)


# -- the Day's rows ---------------------------------------------------------------------------------------


def _entry_html(
    entry: Mapping[str, Any],
    tz: ZoneInfo,
    inside: bool = False,
    expanded: bool = False,
    name_this: Callable[[Mapping[str, Any]], str] | None = None,
) -> str:
    """One timeline row: the clock, the kind, what it was; then an `aboard` entry's inner rows;
    then, behind a toggle, the attachments by name and the company. The grammar is `day.rows`'.
    `name_this` gives a stay printed as coordinates its link to the Places page."""
    if entry["kind"] == day_reader.FLIGHT:
        route = f"{entry['carrier']} {entry['number']}  {entry['from']} {ARROW} {entry['to']}"
        clock = day_reader.span_text(entry["start"], entry["end"], tz)
        return (
            f'<li class="row flight" title="line {escape(str(entry["line"]))}">'
            f'<span class="clock">{escape(clock)}</span> <span class="kind">flight</span> '
            f"{escape(route)}{DOT}{escape(str(entry['evidence']))}</li>\n"
        )
    clock = day_reader.span_text(entry["within_day"]["start"], entry["within_day"]["end"], tz, clip=True)
    kind = day_reader.GAP if entry["gap"] else str(entry["kind"])
    parts: list[str] = []
    if entry["kind"] == day_reader.ABOARD:
        asset = entry["asset"]
        head = asset["name"] + (f" ({asset['kind']})" if asset["kind"] else "")
        parts = [head, day_reader.duration_text(entry["within_day"]["duration_s"])]
    elif entry["kind"] == stays.MOVE:
        parts = [day_reader.duration_text(entry["within_day"]["duration_s"])]
        if entry["gap"]:
            parts.append("no points")
            parts.append(day_reader.distance_text(entry["distance_m"] or 0))
        else:
            parts.insert(0, day_reader.distance_text(entry["distance_m"] or 0))
            parts.append(entry["mode"] or "mode unknown")
            if entry["airports"]:
                parts.append(f"{entry['airports'][0]} {ARROW} {entry['airports'][1]}")
            if entry.get("aboard") and not inside:
                parts.append(f"aboard {entry['aboard']}")
    else:
        parts = [str(entry["where"]), day_reader.duration_text(entry["within_day"]["duration_s"])]
        if entry.get("aboard") and not inside:
            parts.append(f"aboard {entry['aboard']}")
    counts = day_reader.counts(entry.get("attached"))
    company = entry.get("with") or {}
    confirmed, proposed = company.get("confirmed") or [], company.get("proposed") or []
    if not counts and not confirmed and not proposed and entry["kind"] == stays.STOP and not inside:
        parts.append("nothing attached")
    out = [
        f'<li class="row {escape(kind)}"><span class="clock">{escape(clock)}</span> '
        f'<span class="kind">{escape(kind)}</span> {escape(DOT.join(parts))}'
        f"{name_this(entry) if name_this is not None else ''}"
    ]
    if entry.get("inside"):
        out.append('\n<ol class="inside">\n')
        out.extend(
            _entry_html(
                {**s, "attached": None, "with": None}, tz, inside=True, expanded=expanded, name_this=name_this
            )
            for s in entry["inside"]
        )
        out.append("</ol>")
    if counts or confirmed or proposed:
        summary = ", ".join(_plural(n, noun) for n, noun in counts)
        if confirmed or proposed:
            n = len(confirmed) + len(proposed)
            summary = f"{summary}{DOT}with {n}" if summary else f"with {n}"
        out.append(f"\n<details{' open' if expanded else ''}><summary>{escape(summary)}</summary>\n")
        out.append(_attached_html(entry.get("attached"), tz))
        if confirmed or proposed:
            text = ", ".join(day_reader.companion_text(c) for c in confirmed)
            more = ", ".join(day_reader.companion_text(c) for c in proposed)
            if more:
                text = f"{text}{DOT}proposed {more}" if text else f"proposed {more}"
            out.append(f'<p class="with">with {escape(text)}</p>\n')
        out.append("</details>")
    out.append("</li>\n")
    return "".join(out)


def _reflection_html(item: Mapping[str, Any], tz: ZoneInfo) -> str:
    """The reflection: when it was recorded and by which source, then the words, a paragraph each."""
    paragraphs = "".join(
        f"<p>{escape(text)}</p>\n" for text in str(item["text"]).splitlines() if text.strip()
    )
    when = f"{_clock(str(item['at']), tz)}{DOT}{item['source']}"
    return (
        f'<h2>Reflection</h2>\n<div class="reflection" title="line {escape(str(item["line"]))}">\n'
        f'<p class="mute">{escape(when)}</p>\n{paragraphs}</div>\n'
    )


def _draft_html(draft: Mapping[str, Any]) -> str:
    """The standing draft of the day (RFC 0036) above the timeline: headed as a draft, one
    paragraph per segment with its evidence ids (the whole id on hover), an unsupported segment a
    muted block marked with the word, never run into the prose around it."""
    parts = [
        "<h2>Draft</h2>\n",
        f'<p class="mute">{escape(drafts.head_text(draft))}</p>\n<div class="draft">\n',
    ]
    for segment in draft["segments"]:
        label = escape(drafts.PART_LABELS.get(str(segment.get("part")), "")) if segment.get("part") else ""
        head = f'<span class="kind">{label}</span> ' if label else ""
        if segment["supported"]:
            ids = ", ".join(
                f'<span class="id" title="line {escape(e)}">{escape(drafts.short_id(e))}</span>'
                for e in segment["evidence"]
            )
            parts.append(f'<p class="segment">{head}{escape(segment["text"])} <small>[{ids}]</small></p>\n')
        else:
            why = f": {escape(str(segment['why']))}" if segment.get("why") else ""
            parts.append(
                f'<p class="segment unsupported mute">{head}~ {escape(segment["text"])}'
                f" <small>{drafts.UNSUPPORTED}{why}</small></p>\n"
            )
    if draft.get("earlier"):
        earlier = ", ".join(escape(drafts.short_id(e)) for e in draft["earlier"])
        parts.append(f'<p class="mute">earlier drafts: {earlier}</p>\n')
    parts.append("</div>\n")
    return "".join(parts)


def _withheld_html(row: Mapping[str, Any], heading: bool = True) -> str:
    """A standing draft the `dream` entry no longer allows (`drafts.withheld_json`): one muted line
    that says so and why, and nothing of what the draft says; under the Draft heading of an earlier
    draft the entry does allow, when the Day shows one."""
    line = escape(str(row["line"]))
    head = "<h2>Draft</h2>\n" if heading else ""
    return f'{head}<p class="mute" title="line {line}">{escape(drafts.withheld_text(row))}</p>\n'


def _attached_html(attached: Mapping[str, Any] | None, tz: ZoneInfo) -> str:
    if not attached:
        return ""
    items: list[tuple[str, str, Sequence[str]]] = []  # kind, text, the lines it points at
    for e in attached["events"]:
        span = day_reader.span_text(e["start"], e["end"], tz)
        items.append(("event", f"{e['title']} {span}{day_reader.sources_text(e)}", e["lines"]))
    for t in attached["transcripts"]:
        items.append(("transcript", t["title"], [t["line"]]))
    for n in attached["notes"]:
        items.append(("note", n["text"], [n["line"]]))
    for m in attached["mail"]:
        items.append(("mail", f"{m['subject']} ({_plural(m['messages'], 'message')})", m["lines"]))
    for c in attached["calls"]:
        items.append(("call", day_reader.call_text(c), [c["line"]]))
    for k in attached["keepers"]:
        items.append(("keeper", f"{k['name']} ({k['lane']})", [k["line"]]))
    for key, noun in (("messages", "message"), ("photos", "photo")):
        if attached[key]["count"]:
            items.append((key, _plural(attached[key]["count"], noun), attached[key]["lines"]))
    if not items:
        return ""
    out = ['<ul class="attached">\n']
    for kind, text, lines in items:
        title = " ".join(lines[:3]) + (" …" if len(lines) > 3 else "")
        out.append(
            f'<li title="{escape(_plural(len(lines), "line"))}: {escape(title)}">'
            f'<span class="kind">{escape(kind)}</span> {escape(text)}</li>\n'
        )
    out.append("</ul>\n")
    return "".join(out)


def _trip_row(trip: trips.Trip, rd: reading.Reading, dates: str) -> list[Cell]:
    nights = _plural(trip.nights, "night")
    if trip.asset:
        asset = rd.assets.get(trip.asset)
        nights += f" aboard {asset.name if asset else trip.asset}"
    if trip.in_transit:
        nights += f" ({trip.in_transit} in transit)"
    flights = []
    for label, found in (("in", trip.flights_in), ("out", trip.flights_out)):
        for f in found:
            name = f"{f['carrier']} {f['number']} " if f["number"] else ""
            flights.append(f"{label} {name}{f['from']} {ARROW} {f['to']}")
    return [
        (dates, "day"),
        escape(nights),
        escape(f" {ARROW} ".join(trip.route)) if trip.route else '<span class="mute">unknown</span>',
        escape(", ".join(flights)),
        escape(", ".join(trip.places)),
        escape(", ".join(c.name for c in trip.people)),
    ]


# -- the spot's canvas ------------------------------------------------------------------------------------

SVG_W, SVG_H = 160, 104


def _spot_svg(p: places_review.Proposal) -> str:
    """A dot on a plain canvas, drawn here: the cluster at the centre with the radius accepting it
    would write, and the nearest named place (within 5 km) as a ring where it lies, or at the edge
    in its direction when it is off the canvas, with its name and distance. No tile, no fetch."""
    cx, cy = SVG_W / 2, SVG_H / 2
    half_m = max(p.radius_m * 2.5, 150.0)
    near = p.nearest if p.nearest is not None and p.nearest[1] <= places_review.NEAR_KM * 1000 else None
    if near is not None and near[1] <= 1500:
        half_m = max(half_m, near[1] * 1.15 + near[0].radius_m)
    scale = (cx - 4) / half_m
    out = [
        f'<svg viewBox="0 0 {SVG_W} {SVG_H}" role="img" aria-label="the spot">',
        f'<circle class="ring" cx="{cx:.1f}" cy="{cy:.1f}" r="{max(p.radius_m * scale, 4):.1f}"/>',
        f'<circle class="spot" cx="{cx:.1f}" cy="{cy:.1f}" r="3.5"/>',
    ]
    if near is not None:
        place, metres = near
        east = (place.lon - p.lon) * math.cos(math.radians(p.lat)) * 111_320
        north = (place.lat - p.lat) * 111_320
        x, y = cx + east * scale, cy - north * scale
        inside = abs(x - cx) <= cx - 6 and abs(y - cy) <= cy - 6
        if not inside:  # at the edge, in its direction
            k = min((cx - 8) / abs(east * scale or 1e-9), (cy - 8) / abs(north * scale or 1e-9))
            x, y = cx + east * scale * k, cy - north * scale * k
            out.append(f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{x:.1f}" y2="{y:.1f}"/>')
        r = min(max(place.radius_m * scale, 3), 60) if inside else 3
        out.append(f'<circle class="near" cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}"/>')
        label = escape(f"{place.name}, {_metres(metres)}")
        if inside:  # under its ring (above it near the foot), clear of the centre, kept on the canvas
            ty = y + r + 12 if y + r + 14 <= SVG_H - 14 else y - r - 4
            half = len(f"{place.name}, {_metres(metres)}") * 2.9 + 2  # about half the text's width
            tx = min(max(x, half), SVG_W - half)
            out.append(f'<text x="{tx:.1f}" y="{ty:.1f}" text-anchor="middle">{label}</text>')
        else:  # the corner, clear of the line
            out.append(f'<text x="4" y="12">{label}</text>')
    out.append(f'<text x="4" y="{SVG_H - 5}">{escape(_metres(p.radius_m))} round</text>')
    out.append("</svg>")
    return "".join(out)


def _loopback(client: str) -> bool:
    """The connection's address is this machine's loopback: 127.0.0.0/8 or ::1 (and ::1 mapped)."""
    try:
        address = ipaddress.ip_address(client.partition("%")[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_loopback


def _loopback_origin(origin: str) -> bool:
    """The browser's Origin names the server as it is reached from this machine: `http://127.0.0.1`
    or `http://[::1]`, any port; a name (`localhost` included: it may resolve to anything), another
    scheme, another host, or `null` (an opaque origin) is not."""
    parts = urlsplit(origin.strip())
    if parts.scheme != "http" or parts.hostname is None:
        return False
    return _loopback(parts.hostname)


def _not_waiting(e: Locked) -> str:
    """Another writer holds the record: the store's sentence, said for a page, which never waits."""
    return str(e).replace(
        NOT_WAITING, "; the page does not wait for another writer, so nothing was written: try again shortly"
    )


def _suffix(upload: Upload) -> str:
    """The recording's suffix, for the engine's decoder: its file name's, else its type's."""
    suffix = PureWindowsPath(upload.filename).suffix.lower()  # a name, perhaps with either separator
    if re.fullmatch(r"\.[a-z0-9]{1,5}", suffix):
        return suffix
    return AUDIO_SUFFIXES.get(upload.content_type.partition(";")[0].strip().lower(), ".audio")


def _multipart(body: bytes, content_type: str) -> tuple[dict[str, str], Upload | None]:
    """A `multipart/form-data` body (RFC 7578): the form's fields, a field sent more than once its
    values joined with commas, and its one file, the recording (None when none was chosen). Each
    part is cut at the boundary the header names and nowhere else, so a recording's bytes are kept
    as they were sent. ValueError for a body that is not one."""
    header = email.message.Message()
    header["content-type"] = content_type
    boundary = header.get_param("boundary")
    if not isinstance(boundary, str) or not boundary:
        raise ValueError("a multipart form names its boundary")
    parts = (b"\r\n" + body).split(b"\r\n--" + boundary.encode("latin-1"))
    if len(parts) < 3 or not parts[-1].startswith(b"--"):
        raise ValueError("the form's body is not what its boundary says")
    fields: dict[str, list[str]] = {}
    upload: Upload | None = None
    for part in parts[1:-1]:
        _padding, _, rest = part.partition(b"\r\n")
        head, found, data = rest.partition(b"\r\n\r\n")
        if not found:
            raise ValueError("a part of the form has no header")
        headers = email.message_from_bytes(head + b"\r\n\r\n")
        name = headers.get_param("name", header="content-disposition")
        if name is None:
            continue
        name = collapse_rfc2231_value(name)
        filename = headers.get_filename()
        if filename is None:
            fields.setdefault(name, []).append(data.decode("utf-8", "replace"))
        elif data:
            upload = Upload(filename, headers.get_content_type(), data)
    return {k: ",".join(v) for k, v in fields.items()}, upload


def _signed_html(signed: Mapping[str, Any] | None) -> str:
    """The Day's signature row: `unsigned`, or when (`signing.state_text`), which line, how many lines
    it confirmed of the page's, and the page digest whole."""
    if signed is None:
        return _dt("signature", signing.state_text(None))
    n, of = signed.get("confirmed"), signed.get("lines")
    text = f"{signing.state_text(dict(signed))}{DOT}#{signed['seq']}{DOT}{n} of {of} lines confirmed"
    digest = signed.get("page_sha256")
    sha = f'{DOT}page sha256 <code class="sha">{escape(str(digest))}</code>' if digest else ""
    return f"<dt>signature</dt><dd>{escape(text)}{sha}</dd>\n"


def _texts(lines: Iterable[Line], retracted: Collection[str]) -> list[str]:
    """The day's own words, for the language they are in: the text, title or subject of each line."""
    found = []
    for line in lines:
        if str(line["id"]) in retracted:
            continue
        payload = line.get("payload") or {}
        for key in ("text", "title", "subject"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                found.append(value)
    return found


# -- fragments --------------------------------------------------------------------------------------------


def _table(head: Sequence[Cell], rows: Iterable[Sequence[Cell]], ids: Sequence[str] | None = None) -> str:
    """A table from cells already escaped (or marked up): a cell is text, or (text, css class).
    `ids`, one per row, are the rows' anchors."""
    out = ["<table>\n<thead><tr>"]
    for cell in head:
        text, cls = cell if isinstance(cell, tuple) else (cell, "")
        out.append(f'<th class="{cls}">{text}</th>' if cls else f"<th>{text}</th>")
    out.append("</tr></thead>\n<tbody>\n")
    for n, row in enumerate(rows):
        out.append(f'<tr id="{escape(ids[n])}">' if ids is not None else "<tr>")
        for cell in row:
            text, cls = cell if isinstance(cell, tuple) else (cell, "")
            out.append(f'<td class="{cls}">{text}</td>' if cls else f"<td>{text}</td>")
        out.append("</tr>\n")
    out.append("</tbody>\n</table>\n")
    return "".join(out)


def _dt(term: str, text: str) -> str:
    return f"<dt>{escape(term)}</dt><dd>{escape(text)}</dd>\n"


def _num(n: int) -> Cell:
    return (f"{n:,}", "num")


def _plural(n: int, noun: str) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {noun}s"


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _metres(m: float) -> str:
    return f"{m:.0f} m" if m < 1000 else f"{m / 1000:.1f} km"


def _matches(header: str, etag: str) -> bool:
    """`If-None-Match` names `etag` among its tags, weak or strong (the weak comparison RFC 9110
    asks of a GET). `*` is not honoured: it would answer 304 for a request that is an error, and a
    browser revalidates with the tag it was given."""
    return etag in {tag.strip().removeprefix("W/") for tag in header.split(",")}


def _instant(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def _clock(stamp: str, tz: ZoneInfo) -> str:
    return _instant(stamp).astimezone(tz).strftime("%Y-%m-%d %H:%M")


def _clip(day: str, days: int, whole: tuple[str, str]) -> str:
    """`day` moved by `days`, kept inside the record's days."""
    moved = (parse_day(day) + timedelta(days=days)).isoformat()
    return min(max(moved, whole[0]), whole[1])


def _last_window(whole: tuple[str, str]) -> tuple[str, str]:
    return _clip(whole[1], -(WINDOW_DAYS - 1), whole), whole[1]


# -- the server -------------------------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = "logbook"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self._answer(body=True)

    def do_HEAD(self) -> None:
        self._answer(body=False)

    def do_POST(self) -> None:
        """A page's form: read in full (a field sent more than once, its values joined with commas;
        a recording as `multipart/form-data`, to a Day only, up to `AUDIO_BYTES`), then `Site.write`
        with the connection's address and the Origin header, which decide whether it is answered at
        all."""
        assert isinstance(self.server, Server)
        site = self.server.site
        path = self.path.partition("?")[0]
        kind = self.headers.get("Content-Type") or ""
        multipart = kind.strip().lower().startswith("multipart/form-data")
        limit = AUDIO_BYTES if multipart and DAY_ACT.match(path) is not None else FORM_BYTES
        length = self.headers.get("Content-Length") or "0"
        size = int(length) if length.isdigit() else 0
        if size > limit:
            self.close_connection = True  # the body is left unread
            self._send(site._error(413, f"a form is at most {limit:,} bytes"), body=True)
            return
        raw = self.rfile.read(size) if size > 0 else b""
        upload: Upload | None = None
        if multipart:
            try:
                form, upload = _multipart(raw, kind)
            except ValueError as e:
                self._send(site._error(400, str(e)), body=True)
                return
        else:
            query = parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True)
            form = {k: ",".join(v) for k, v in query.items()}
        response = site.write(path, form, str(self.client_address[0]), self.headers.get("Origin"), upload)
        self._send(response, body=True)

    def _answer(self, body: bool) -> None:
        assert isinstance(self.server, Server)
        path, _, query = self.path.partition("?")
        response = self.server.site.respond(path, query, self.headers.get("If-None-Match"))
        self._send(response, body)

    def _send(self, response: Response, body: bool) -> None:
        self.send_response(response.status)
        for name, value in response.headers.items():
            self.send_header(name, value)
        self.end_headers()
        if body and response.status not in (204, 304):
            self.wfile.write(response.body)


class Server(ThreadingHTTPServer):
    """A loopback-only HTTP server over one `Site`. Never resolves a name: `HTTPServer.server_bind`
    would look up the host's fully qualified name, and this one does not."""

    daemon_threads = True

    def __init__(self, port: int, site: Site):
        self.site = site
        super().__init__((HOST, port), Handler)

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


def make_server(
    lb: Logbook,
    host: str = HOST,
    port: int = PORT,
    airports: Airports | None = None,
    voice: Voice | None = None,
) -> Server:
    """The server, bound and ready to `serve_forever`. `HostError` for any host but 127.0.0.1,
    before a socket is opened; OSError when the port is taken. `voice`: how a Day hears a recording."""
    if host != HOST:
        raise HostError(
            f"serve binds {HOST} only, never {host!r}: the record is read from this machine, "
            "and nothing here leaves it"
        )
    return Server(port, Site(lb, airports, voice=voice))


def serve(
    lb: Logbook,
    host: str = HOST,
    port: int = PORT,
    airports: Airports | None = None,
    announce: Callable[[str], None] = print,
    voice: Voice | None = None,
) -> None:
    """Serve the record until Ctrl-C. `HostError` and OSError as `make_server`."""
    server = make_server(lb, host, port, airports, voice)
    try:
        bound = server.server_address[1]
        announce(
            f"serving {_shown(lb.root)} at http://{HOST}:{bound}/  (Ctrl-C to stop; nothing is written but"
            " what you name, reflect or sign on a page)"
        )
        server.serve_forever()
    except KeyboardInterrupt:
        announce("stopped")
    finally:
        server.server_close()


def _shown(root: Path) -> str:
    """The record's folder as `~/Logbook` when it is under the home directory, never the user name."""
    try:
        return "~/" + root.resolve().relative_to(Path.home().resolve()).as_posix()
    except (ValueError, OSError):
        return str(root)
