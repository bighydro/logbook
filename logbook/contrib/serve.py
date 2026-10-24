"""`logbook serve [--port N]`: the record read in a browser, from this machine only.

A reader (ADR 0013) with another output: server-rendered HTML in place of text, one page per
reader the commands already have. `/day/YYYY-MM-DD` is the Day (`day.read`) as a timeline, each
row's attachments and company folded under a toggle; `/days?from=&to=` is a window one row per
day (`days.read`), each row a link to its Day; `/trips?year=` the trips of a year (`trips.trips`
over one `reading.read`); `/places` the named places of `places.json`; `/assets` the registered
assets and the last fix of each (`asset_status.read`); `/gaps` where each source went quiet
(`gaps.report`); `/world?from=&to=` the page `logbook export world` writes (`world.py`): the
globe, the places, the assets on their tracks, the stays, the journeys and a time scrubber; `/today`
redirects to the Day the owner is in now: the current date in the record's timezone, the date before
until the record's `day_start` (RFC 0036), whose Day then says where it begins. The Library's
shelves: `/journeys?year=` the journeys that began in a year, the latest first (`journeys.shelf`),
and `/journeys/FIRST/LAST` one journey (`journeys.read`): its days linking their Days, its stays as
dots on a plain canvas drawn here, the promises made on it; `/people?year=` the canonical people of
a year by days together (`person_page.ranked`) and the review queue of `people review`, and
`/people/ID` one person (`person_page.read`); `/manifest?portfolio=` the orgs the owner named under
what they decided about them (`orgs.shelf_of`, RFC 0037 §11), or only those one portfolio holds, and
the review queue of `review org`, `/org/ID` one org (`orgs.page_of`) and `/manifest/people` the
people with more than one org, the money only when asked and the gate reads tier 3, and a portfolio
only when the gate reads tier 3; `/ideas` the ideas the owner named by stage (`ideas.shelf_of`, RFC
0037 §11) and the review queue of `review idea`, `/idea/ID` one idea (`ideas.page_of`). `/line/ID`
is one line as the record holds it, read-only, through the gate (`Site.page_line`): every Day row
that is a line links to it. `/photo/ID` is a photo line's pixels from the record's own attachment
store, the Day's thumbnails (`Site._photo`, `day_photos.stored`), through the gate too. Every
derived row on them carries its evidence folded:
what it rests on, the day, the ids of the lines. Every page is built from the index and the
readers, so a Day renders in the time `logbook day` takes whatever the record's length, and nothing
is written by a GET: every page is answered from the record at its head.

Eight pages write, on a POST. `/places` carries the review queue of `setup places review`
(`places_review.read`, the same order, `PAGE_SIZE` clusters a page), and its forms post to
`/places/review` (`Site.write`), which names a cluster or rejects it through the engine's own
`accept` and `reject`, so `places.json`, the naming note and `state/places-review.json` are what the
CLI writes. A journey's page posts its name to `/journeys/name` (`journeys.name`, what `logbook add
--trip` runs); the People page's queue posts to `/people/review`, Merge through
`people_review.accept` and Not the same person through `people_review.reject` (`people review
--accept`, `--reject`); the Manifest's queue posts to `/manifest/review` (`entity_review.accept` and
`reject`, `review org --accept`, `--name`, `--reject`) and an org's page its status and its
portfolio to `/manifest/status` (`entity_status.write`, `status org … --portfolio`); the Ideas
shelf's queue posts to `/ideas/review` and an idea's page its status to `/ideas/status`, through the
same functions as `review idea` and `status idea`. The Day
carries the owner's two acts on it, Reflect and Sign (`Site._reflect`, `Site._sign`): the reflection posts to
`/day/YYYY-MM-DD/reflect` and is written through `day reflect`'s own `reflect.write` (the day's
Wispr Flow draft offered prefilled, a recording heard through `day reflect --audio`'s path when the
command wired one in, `Voice`), and the proposals the rules read in it are checkboxes whose form
posts to `/day/YYYY-MM-DD/sign`, which signs the day through `reflect.close`, the code `day reflect
--sign` runs: `signing.sign` with the lines confirmed, the accepted dispositions and the reflection,
a signed day signed again superseding its signature. The Day also carries the owner's two acts on
lines already in the record: a star on every row that is a line, posting to `/star` (`Site._star`:
`stars.star` and `stars.unstar`, the lines `logbook star` and `unstar` write; the photo review at the
Day's foot posts there too, its Star a star and its Not a keeper `day_photos.pass_over`, the review's
bookkeeping and no line), and a "with…" field
in the header's `with` row, its names completed from the canonical people by a `datalist`, posting
to `/with` (`Site._with`: `presence.state`, the lines `logbook with` writes). The Library's write
acts, allowed because the server binds 127.0.0.1 and runs as the record's own user: a POST is
answered only when the connection comes from this machine (the client address is loopback) and the
form was submitted from the server's own pages (the browser's `Origin`, when it sends one, names
127.0.0.1); a request that came through a proxy (`phone.proxied`: a Host that is not 127.0.0.1 or
[::1], or a `Tailscale-*` or `X-Forwarded-*` header) is answered only once `logbook setup phone`
names the owner's own phone in `logbook.json` and it is the phone's, through Tailscale Serve
(`phone.allows`: its origin, its Host and its login, all at once); anything else is a 403 and
nothing is written. Every write is one at a time
(`Site._write_lock`) and through the CLI's own function, under the record's writer lock and never
waiting for it: another command writing is one answer for every act, the shelves', the Manifest's
and the Day's alike (`Site._busy`): a 409, one sentence (`BUSY`), the form's input kept in a form
that sends it again, and nothing written. After a write the head has moved, and the next request
reads the record again as after a sync. The policy's `write` list (the MCP door, ADR 0022) is never
read: this is the owner's own page.

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
- A page is one HTML document with one inline stylesheet: no font, no stylesheet link, no script
  fetched, and no reference to any URL but the server's own paths. The one image is a Day's
  thumbnail of a photo, from `/photo/ID`, the record's own attachment store and nothing else: the
  Day's policy allows images from the server alone (`DAY_IMAGES`), every other page's none, an
  `<img>` is written only for pixels the store holds in a type every browser draws, and any other
  photo is counted, never a broken image; a static page draws none. A script is inline on
  three pages, each named in that page's Content-Security-Policy by its hash and by nothing else: the
  Places page's keys (`PLACES_SCRIPT`: Enter, n and Space), the Day page's record button
  (`DAY_SCRIPT`, only where the server can hear a recording: it records with the browser's own
  MediaRecorder and sends the recording with the form, never by a fetch) and the World page's canvas
  (`world.SCRIPT`, its data in two JSON blocks a browser never runs); every other page's policy
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
import contextlib
import contextvars
import email
import faulthandler
import functools
import hashlib
import http.client
import ipaddress
import json
import math
import os
import re
import secrets
import select
import signal
import socket
import socketserver
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from concurrent.futures import CancelledError as FuturesCancelled
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from datetime import UTC, date, datetime, timedelta
from email.utils import collapse_rfc2231_value
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING, Any, NamedTuple, TypeVar
from urllib.parse import parse_qs, quote, unquote, urlsplit
from zoneinfo import ZoneInfo

from ..core import (
    assets,
    cancel,
    chapter,
    day_start,
    drafts,
    goals,
    keepers,
    notes,
    people,
    places,
    policy,
    presence,
    reading,
    share,
    signing,
    stars,
    stays,
    trips,
    weather,
)
from ..core import day as day_reader
from ..core import days as days_reader
from ..core.chain import Line
from ..core.export import day_range, parse_day
from ..core.flights import Airports
from ..core.index import Index
from ..core.store import NOT_WAITING, HeadMoved, Locked, Logbook, now_utc, retractions
from . import (
    asset_status,
    day_photos,
    day_rhythm,
    dream,
    entities,
    entity_review,
    entity_status,
    gaps,
    ideas,
    journeys,
    keep,
    library_build,
    orgs,
    person_page,
    phone,
    places_review,
    reflect,
    search_page,
    shelf_agents,
    shelf_goals,
    shelf_promises,
    trip_page,
    week_page,
    week_paper,
    world,
)
from . import plan as plan_reader

if TYPE_CHECKING:  # the review reads the adapters' phone rules: loaded by the People page, never by `--help`
    from . import people_review

T = TypeVar("T")
HOST = "127.0.0.1"  # the one host the server binds; anything else is refused
PORT = 8765
LIMIT_S = 15.0  # a page read longer than this is stopped and said so (`serve --limit`)
RENDERS = 2  # pages read at once; the rest wait their turn, within their limit
WATCH_S = 0.25  # how often a waiting request looks at its reading and its browser
IDLE_S = 60.0  # a kept-alive connection idle this long is closed
WATCH_EVERY_S = 30.0  # the server asks itself for its icon this often (`Watchdog`)
SILENT_S = 5.0  # an answer slower than this is no answer
STUCK_AFTER = 2  # this many in a row, and the server leaves for its service manager to start again
STUCK_EXIT = 70  # EX_SOFTWARE: a non-zero exit, which launchd's KeepAlive and systemd's on-failure restart
WINDOW_DAYS = 14  # `/days` without a window: the record's last fortnight
HEAD_CHARS = 12
CSP = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'"
SHOWN_MESSAGES, LONG_CONVERSATION = 10, 30  # a conversation of more than 30 shows 10, the rest folded
DAY_PATH = re.compile(r"^/day/(\d{4}-\d{2}-\d{2})$")
TODAY = "/today"
# the record's pages, not the clock's (and every Day, journey, person and org)
RECORD_PAGES = frozenset(
    {"/", "/days", "/trips", "/places", "/world", "/journeys", "/people", "/manifest", "/manifest/people"}
    | {"/ideas"}
    | {"/promises", "/goals", "/agents"}  # the shelves' lists
    | {"/search"}  # the record's words (`search_page`)
)
JOURNEY_PATH = re.compile(r"^/journeys/(\d{4}-\d{2}-\d{2})/(\d{4}-\d{2}-\d{2})$")  # its first and last day
PERSON_PATH = re.compile(r"^/people/([^/]+)$")  # a canonical person, by entity id
ORG_PATH = re.compile(r"^/org/([^/]+)$")  # a named org, by entity id (RFC 0037 §11)
IDEA_PATH = re.compile(r"^/idea/([^/]+)$")  # a named idea, by entity id (RFC 0037 §11)
PROMISE_PATH = re.compile(r"^/promises/([0-9a-f]+)$")  # one promise, by its proposal id (`shelf_promises`)
GOAL_PATH = re.compile(r"^/goals/([^/]+)$")  # one goal, by the id of any line of its chain (`shelf_goals`)
REVIEW_PATH = "/places/review"  # the Places page's writes: POST only, from this machine only
NAME_PATH = "/journeys/name"  # the Journeys page's form: `add --trip`; likewise
PEOPLE_REVIEW_PATH = "/people/review"  # the People page's queue: `people review --accept`, `--reject`
MANIFEST_REVIEW = "/manifest/review"  # the Manifest's queue: `review org --accept`, `--name`, `--reject`
MANIFEST_STATUS = "/manifest/status"  # an org's page: `status org ORG DISPOSITION`
MANIFEST_PATHS = (MANIFEST_REVIEW, MANIFEST_STATUS)  # under the writer lock, never waiting for it: a 409
IDEAS_REVIEW = "/ideas/review"  # the Ideas shelf's queue: `review idea --accept`, `--name`, `--reject`
IDEAS_STATUS = "/ideas/status"  # an idea's page: `status idea IDEA DISPOSITION`
IDEAS_PATHS = (IDEAS_REVIEW, IDEAS_STATUS)  # likewise: a 409 when another command writes
# the Library's forms
WRITE_PATHS = (REVIEW_PATH, NAME_PATH, PEOPLE_REVIEW_PATH, *MANIFEST_PATHS, *IDEAS_PATHS)
DAY_ACT = re.compile(r"^/day/(\d{4}-\d{2}-\d{2})/(reflect|sign)$")  # the Day's two acts: POST only, likewise
REFLECT, HEAR, SIGN = "reflect", "hear", "sign"  # the acts a Day's forms name
DREAM = "dream"  # the evening's *Dream the day so far*, posted to the Day's reflect route (`Site._dream`)
REVISIT, TASK = "revisit-", "task-"  # Keep and sign's fields by number: a decision's day, a task's answer
PENCIL = "pencil"  # the anchor of the evening's pencil, where Dream the day so far sends the owner back
STAR_PATH = "/star"  # the Day page's star on a row (RFC 0041), through `stars.star` and `stars.unstar`
WITH_PATH = "/with"  # the Day page's "with…" field, through `presence.state`
LINE_ACTS = (STAR_PATH, WITH_PATH)  # the Day's acts on its lines: POST only, likewise; a 409 when busy
PASS = "pass"  # the photo review's Not a keeper, posted to STAR_PATH: no line (`day_photos.pass_over`)
PHOTOS = "photos"  # the Day page's anchor of its photo review, where the review's acts send the owner back
WEEK = "week"  # the anchor of a Sunday's week draft (`dream week`), which the other six days link to
LINE_PATH = re.compile(r"^/line/([^/]+)$")  # one line as written, read-only, through the gate
PHOTO_PATH = re.compile(r"^/photo/([^/]+)$")  # a photo line's pixels from the attachment store, likewise
WEEK_PATH = re.compile(r"^/week/(\d{4}-W\d{2})$")  # the week page (RFC 0043 §8, `week_page`), read-only
CLOSE = "close"  # the Day page's anchor of Reflect and sign, where a write sends the owner back
# pages the record's today moves too (this year, anniversaries, drift, the stale orgs and ideas): in the tag
# /goals: a goal goes past; /world: its window ends on today, whatever the calendar holds after it
CLOCK_PAGES = ("/people", "/manifest", "/org/", "/ideas", "/idea/", "/goals", "/world")
TRIP_KINDS: tuple[str, ...] | None = (
    trips.READ_KINDS
)  # the lines a year's trips parse; the rest from the index
SPILL_DAYS = 2  # a reading of days holds the night after the last and the morning after that
ID_SHOWN = 4  # line ids an evidence row prints; the rest are counted
PAGE_SIZE = 20  # clusters a page of the review queue; "more" is the next page
SHOWN = 30  # an org's timeline rows shown before the rest fold
PAGES_KEPT = 64  # pages the server keeps by their tag, the latest asked for last (`Site._keep`)
PAGE_BYTES_KEPT = 64 * 1024 * 1024  # and at most this many bytes of them
SHARED_KEPT = 32  # readings `Site.shared` keeps for the record as it stands, the oldest going first
DAY_KEPT = 48  # readings the Day keeps beside them (`Site._day_reading`): a few each for the days last read
DAY_LATER_KEPT = 12  # the Day's readings beyond the day (`Site._day_later`): today's, and a few before
FORM_BYTES = 64 * 1024  # the most a form may carry: a name, a reflection, the proposals accepted
# another command holds the writer lock: every act's one answer, a 409 (the owner's word of 14 Oct 2026)
BUSY = "Another command is writing to the record; nothing was written. Try again in a moment."
# the fields of the forms the owner types in, shown again in the busy answer's form; the rest kept hidden
TYPED = {
    "text": "your reflection",
    "name": "the name",
    "names": "who was there",
    "reason": "the reason",
    "portfolio": "the portfolio",
    "word": "the day in a word",
}
AUDIO_BYTES = 64 * 1024 * 1024  # the most a recording may carry: half an hour of speech, even as WAV
STATE_FILES = (
    places_review.STATE_FILE,
    day_photos.STATE_FILE,
    *week_page.HOLD_FILES,  # Hold's reports, whose counts the week page reads
)  # record-relative bookkeeping the pages read, in the tag
NO_MODEL = "No model touched this page. What a model drafted is marked as a draft."  # the Day's footer
TIERS_SAID = (  # under the Day's header: what crosses where (SPEC §4), in the Library's words
    "Where you were (tier 1) may travel; what was said (tier 2) stays home unless a policy entry names"
    " where it may go, and money and health (tier 3) never leave without one."
)
NO_DEVICE_WITH = "no device saw this day: say who was there"  # the `with` row of a day with no stay
NONE_CONFIRMED = "nobody confirmed; proposed below"  # the `with` row when only a row's proposals name anyone
TIER_TITLE = (  # a shelf header's tier, on hover; never the words of a tier a gated page does not read
    "The highest tier among the lines this page read (SPEC §4): 1 places, photos and the calendar;"
    " 2 notes, messages and mail; 3 money and health."
)
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
DAY_IMAGES = CSP.replace("default-src 'none';", "default-src 'none'; img-src 'self';")  # a Day's thumbnails
DAY_CSP = DAY_IMAGES.replace("style-src", f"script-src '{DAY_SCRIPT_HASH}'; style-src")
WORLD_CSP = CSP.replace("style-src", f"script-src '{world.SCRIPT_HASH}'; style-src")
YEAR = re.compile(r"^\d{4}$")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
EN_DASH, ARROW, DOT = day_reader.EN_DASH, day_reader.ARROW, day_reader.DOT
HTML = "text/html; charset=utf-8"
Cell = str | tuple[str, str]  # a table cell: text, or (text, css class)
Toggle = Callable[[Sequence[str], bool], str]  # a row's line ids (and: only when starred) → its star
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
ol.timeline,ol.inside,ul.attached,ul.unplaced,ul.plain,ul.proposals{list-style:none;padding:0;margin:0}
li.proposal{padding:.15rem 0}
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
details.synthesis,p.synthesis{margin:.2rem 0 .3rem 1.5rem;font-size:.92rem}
details.synthesis p.segment{margin:.15rem 0}
ul.attached li,ul.unplaced li{padding:.15rem 0}
p.with{margin:.3rem 0 0 1rem;color:var(--mute)}
form.window{display:flex;gap:.6rem;align-items:center;flex-wrap:wrap;margin:0 0 1rem}
input,button{font:inherit;padding:.2rem .4rem;background:var(--bg);color:var(--fg);
border:1px solid var(--line);border-radius:3px}
p.pager,p.mute,.mute{color:var(--mute)}
a.name{font-size:.8rem;margin-left:.5rem}
form.star{display:inline;margin:0 0 0 .3rem}
form.star button{border:0;padding:0 .15rem;background:none;color:var(--mute);cursor:pointer;
font-size:1rem;line-height:1}
form.star button[aria-pressed=true],.star.on{color:#c9a227}
form.with{display:inline-flex;gap:.4rem;align-items:center;flex-wrap:wrap;margin-left:.6rem}
form.with input[type=text]{min-width:12rem}
ul.starred{list-style:none;padding:0;margin:0}
ul.starred li{padding:.2rem 0}
ol.timeline li:target,ul.attached li:target,ul.attached span:target,ul.unplaced li:target,
dt#with:target{background:color-mix(in srgb,var(--accent) 10%,var(--bg))}
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
section.close button,section.close input[type=text],section.close input[type=date]{min-height:44px;
box-sizing:border-box}
section.close details>summary{min-height:44px;display:flex;align-items:center}
section.close code{overflow-wrap:anywhere}
ol.proposals label{min-height:44px;align-items:center}
fieldset.keep{border:0;padding:0;margin:.9rem 0;min-width:0}
fieldset.keep legend{padding:0;font-weight:600;font-size:11px;letter-spacing:.13em;text-transform:uppercase;
color:var(--mute)}
fieldset.keep input[type=text]{width:100%;max-width:20rem}
ol.keep{list-style:none;padding:0;margin:.3rem 0}
ol.keep>li{padding:.3rem 0;border-bottom:1px solid var(--line)}
ol.keep label.pick{display:flex;gap:.6rem;align-items:flex-start;min-height:44px;cursor:pointer;
padding:.3rem 0;box-sizing:border-box}
ol.keep input[type=checkbox],ol.keep input[type=radio],ol.proposals input{flex:none;width:1.25rem;
height:1.25rem;margin:.15rem 0 0}
ol.keep span.head{display:block;font-size:11px;letter-spacing:.08em;text-transform:uppercase;
color:var(--mute)}
ol.keep li.pencil span.words{font-family:var(--serif);color:var(--graphite);background:var(--paper);
border-radius:3px;padding:0 .3rem}
ol.keep li.kept span.words,ol.keep li.task span.words{font-family:var(--serif);color:var(--ink)}
ol.keep label.revisit{display:flex;flex-wrap:wrap;align-items:center;gap:.5rem;min-height:44px;
margin-left:1.85rem;color:var(--mute)}
ol.keep span.answers{display:flex;flex-wrap:wrap;gap:.4rem;margin:.3rem 0 0}
ol.keep span.answers label{display:inline-flex;align-items:center;gap:.4rem;min-height:44px;
padding:0 .8rem;border:1px solid var(--line);border-radius:999px;cursor:pointer;box-sizing:border-box}
ol.keep span.answers input{margin:0}
form.dream{display:flex;flex-wrap:wrap;align-items:center;gap:.2rem .8rem;margin:.6rem 0 1rem}
form.dream p{margin:0;flex:1 1 16rem}
code.sha{overflow-wrap:anywhere}
footer .footnote{display:inline-block;margin-top:.3rem}
@media (max-width:40rem){details{margin-left:1rem}.clock{min-width:0;margin-right:.5rem}
table{display:block;overflow-x:auto}}
ol.shelf{list-style:none;padding:0;margin:0}
ol.shelf>li{padding:.55rem 0;border-bottom:1px solid var(--line);overflow-wrap:anywhere}
ol.shelf>li:target{background:color-mix(in srgb,var(--accent) 10%,var(--bg))}
ol.shelf p{margin:.1rem 0}
p.head{display:flex;flex-wrap:wrap;gap:.1rem .8rem;align-items:baseline}
p.head .mute{font-size:.9rem;font-variant-numeric:tabular-nums}
details.evidence,details.draft{margin:.25rem 0 0}
details.evidence>summary{color:var(--mute);font-size:.85rem}
details.evidence ul.evidence{font-size:.85rem;margin:.2rem 0 0 .8rem}
details.evidence details{margin:0 0 0 .8rem}
span.id{font:.78rem ui-monospace,monospace;color:var(--mute)}
details.draft>summary{font-size:.9rem}
div.draft p.segment{margin:.3rem 0}
p.segment.unsupported{border-left:2px solid var(--line);padding-left:.5rem}
.dates{white-space:nowrap}
svg.stays{display:block;width:100%;max-width:30rem;height:auto;margin:.5rem 0;
border:1px solid var(--line);border-radius:3px}
svg.stays circle{fill:var(--accent);fill-opacity:.85;stroke:var(--bg)}
svg.stays text{font:11px system-ui,sans-serif;fill:var(--fg)}
svg.stays line{stroke:var(--mute)}
li.proposal form{display:flex;flex-wrap:wrap;gap:.5rem;margin:.3rem 0 0}
"""
MANIFEST_STYLE = """
.badge{display:inline-block;font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;padding:0 .35rem;
border:1px solid var(--line);border-radius:3px}
.badge.passed{color:#c0652a}.badge.hold,.badge.add,.badge.sell{color:#2e8b57}
.badge.exited,.badge.let-go{color:var(--mute)}
.stale-flag{color:#c43b3b}
ol.shelf>li.stale{border-left:3px solid #c43b3b;padding-left:.5rem}
p.reason{margin:.2rem 0 0;font-style:italic}
form.act{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center;margin:.4rem 0}
form.act input[type=text]{flex:1 1 10rem;min-width:0}
form.act select,form.act input[type=date]{max-width:100%}
section.acts{border:1px solid var(--line);border-radius:4px;padding:.2rem .6rem;margin:.6rem 0}
s.retracted{color:var(--mute)}
"""  # the Manifest's pages only (an exported site has none): every other page keeps STYLE as it was
TABLES_STYLE = """
@media (max-width:40rem){table{display:block;overflow-x:auto}}
li.cluster svg{max-width:100%}
"""  # the pages of tables, Days, Trips, Places, Assets and Gaps, served or exported (`export site`), on a
# phone: a table scrolls inside its own box (STYLE's phone rule says so too, for every page, the Day's
# Sources among them) and a cluster's canvas keeps to the column
IDEAS_STYLE = MANIFEST_STYLE + "p.refs{overflow-wrap:anywhere}\n"  # the Ideas pages: a Notion id is long
DAY_STYLE = """
p.tiers{color:var(--mute);font-size:.9rem;margin:0 0 1rem}
a.raw{font-size:.75rem;margin-left:.35rem;color:var(--mute);text-decoration:none;font-variant-numeric:tabular-nums}
ul.strip{list-style:none;display:flex;flex-wrap:wrap;gap:.4rem;padding:0;margin:.35rem 0 0 7.5rem}
ul.strip li{display:flex;flex-direction:column;align-items:flex-start;max-width:8rem;font-size:.85rem}
ul.strip img,ul.review img{display:block;max-width:100%;width:8rem;height:auto;border-radius:3px;
border:1px solid var(--line)}
ul.strip li.mute{align-self:center}
ul.strip span.name,ul.review span.name{overflow-wrap:anywhere}
section.review ul.review{list-style:none;display:flex;flex-wrap:wrap;gap:.8rem;padding:0;margin:.5rem 0 1rem}
ul.review li{display:flex;flex-direction:column;gap:.3rem;width:8.5rem;min-width:0}
form.keep{display:block;margin:0}
form.keep button{padding:.2rem .4rem}
svg.track{display:block;width:100%;max-width:30rem;height:auto;margin:.5rem 0;
border:1px solid var(--line);border-radius:3px}
svg.track circle{fill:var(--accent);fill-opacity:.85;stroke:var(--bg)}
svg.track line{stroke:var(--mute);stroke-width:1.5}
svg.track line.gap{stroke-dasharray:4 3}
svg.track text{font:11px system-ui,sans-serif;fill:var(--fg)}
ul.week{color:var(--mute);font-size:.9rem;margin:.3rem 0 1rem}
div.outside ul.strip{margin-left:0}
ul.conversations,ol.messages{list-style:none;padding:0;margin:.2rem 0 0 .8rem}
ol.messages li{padding:.1rem 0;overflow-wrap:anywhere}
ol.messages .clock{min-width:3.2rem}
section.held td{overflow-wrap:anywhere;vertical-align:baseline}
section.held td.at{white-space:nowrap;font-variant-numeric:tabular-nums;color:var(--mute)}
details.conversation,details.all{margin:.2rem 0 0}
section.held details.held{margin:1.5rem 0 0}
section.held h3{font-size:1rem;margin:.8rem 0 .2rem}
span.way{font-size:.78rem;color:var(--mute)}
@media (max-width:40rem){ul.strip{margin-left:1rem}}
"""
LINE_STYLE = """
pre.line{max-width:100%;box-sizing:border-box;overflow-x:auto;white-space:pre-wrap;overflow-wrap:anywhere;
font:.8rem/1.4 ui-monospace,monospace;padding:.6rem;border:1px solid var(--line);border-radius:3px}
dl.header dd{overflow-wrap:anywhere}
@media (max-width:40rem){pre.line{font-size:.75rem}}
"""

NAV = (
    '<a href="/">Logbook</a><a href="/today">today</a><a href="/days">days</a>'
    '<a href="/search">search</a>'
    '<a href="/journeys">journeys</a><a href="/people">people</a><a href="/manifest">manifest</a>'
    '<a href="/ideas">ideas</a><a href="/promises">promises</a><a href="/goals">goals</a>'
    '<a href="/agents">agents</a><a href="/places">places</a><a href="/assets">assets</a>'
    '<a href="/gaps">gaps</a><a href="/world">world</a>'
)


class HostError(ValueError):
    """A host other than 127.0.0.1 was asked for."""


class NotFound(Exception):
    """No page at this path; the message says so, and why when there is a reason."""


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


class DayMarks(NamedTuple):
    """What the Day page reads of a day's lines beside the Day (`Site._day_marks`), through its gate:
    the stars standing by the line each marks, the photos standing (id → name), the lines standing."""

    starred: dict[str, stars.Star]
    photos: dict[str, str]
    lines: dict[str, Line]
    drawn: dict[str, bool]  # photo id → whether the store holds pixels a browser draws, filled as asked


class Rows(NamedTuple):
    """What a Day's rows draw beside the reader's words: `raw`, a row's link to its line as written
    (the first of its ids the page reads); `strip`, a row's photos under it; `lines`, the day's lines
    standing by id, which the Drive folds read (`_drive_folded`)."""

    raw: Callable[[Sequence[str]], str]
    strip: Callable[[Sequence[str]], str]
    lines: Mapping[str, Line]


class Closing(NamedTuple):
    """What the Day page's Reflect and Sign read of a day, at the head: its lines and those retracted,
    the reflection standing (as `day reflect` reads it with no input) and the proposals the rules
    read in it, the Wispr Flow draft not yet taken, the standing signature and what signing again
    would keep from it, and `digest`, the proposals as shown, which the Sign form carries back. For
    Keep and sign: `pencil`, the standing draft as `--keep` reads it (`drafts.for_day` under the `dream`
    entry, its sentences and links numbered and marked kept), and `word`, the day in a word standing."""

    lines: list[Line]
    retracted: set[str]
    reflection: reflect.Reflection | None
    proposals: list[reflect.Proposal]
    draft: reflect.Dictation | None
    earlier: Line | None
    kept: str | None
    digest: str
    pencil: Mapping[str, Any] | None = None
    word: Line | None = None


class Stale(Exception):
    """A Day form older than the record: the reflection, its proposals or the draft it offered are
    not what the page showed; a 409, nothing written."""


_READS: contextvars.ContextVar[Reads | None] = contextvars.ContextVar("reads", default=None)


class Reads(NamedTuple):
    """What a page was made of, when it says (`Site.reads`): the lines of the local days `first` to
    `last`, and of `kinds` the lines of any day; the record's settings and who is who beside them. A
    built page that says it is rendered again only when a line comes for those (`library_build`)."""

    first: str
    last: str
    kinds: tuple[str, ...] = ()


class Response(NamedTuple):
    status: int
    body: bytes
    content_type: str = HTML
    etag: str | None = None  # a page of the record at its head: kept by the browser, asked again
    location: str | None = None  # a redirect's target
    csp: str = CSP  # the Places page names its one inline script; every other page allows none
    reads: Reads | None = None  # what the page was made of, when it says; None: the whole record

    @property
    def headers(self) -> dict[str, str]:
        found = {
            "Content-Type": self.content_type,
            "Content-Security-Policy": self.csp,
            "Cache-Control": "no-store" if self.etag is None else "no-cache",
            "X-Content-Type-Options": "nosniff",
            # no referrer to any other site; to its own, the page's origin, which a form's POST
            # names (under `no-referrer` a browser sends `Origin: null`, and the write gate refuses it)
            "Referrer-Policy": "same-origin",
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
        with_drafts: bool = True,
        library: library_build.Library | None = None,
        on_act: Callable[[], None] | None = None,
        read_later: bool = False,
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
        self.with_drafts = with_drafts  # False: no model's draft (pencil) on the Day (`export site`)
        # the pages built ahead (`library_build`): a GET is answered from them when they hold it, and a
        # page rendered here is added to them; None renders every page (the tests, `export site`)
        self.library = library
        self.on_act = on_act  # told after an act changed the record: the server's rebuild, in the background
        self._lock = threading.Lock()
        # the review queues are read (their tables built once) and acted on under it
        self._review_lock = threading.Lock()
        # one write at a time: the store's writer lock re-enters within a process, so it keeps out
        # another process's writer, never this server's other thread
        self._write_lock = threading.Lock()
        self._head: str | None = None  # the head the index was last brought to by `current`
        self._indexed: str | None = None  # the head `_add_indexes` last tried
        self._started = secrets.token_hex(4)  # in every tag: after a restart (a new version), every page anew
        # what is kept between requests (`_keep`, `shared`), under one lock held only to look and to put
        self._kept_lock = threading.Lock()
        self._kept: dict[str, Response] = {}  # a page by its tag, the latest asked for last
        self._kept_bytes = 0
        self._shared: dict[tuple[Any, ...], Any] = {}  # a reader's result, for `_shared_state`
        self._shared_state: str | None = None
        self._building: dict[tuple[Any, ...], threading.Lock] = {}  # one build of each result at a time
        self._day_kept: dict[tuple[str, ...], Any] = {}  # the Day's readings, a pool of their own
        self._day_state: str | None = None
        self.read_later = read_later  # the Day's whole-record readings on a thread (`logbook serve`)
        self._day_later_kept: dict[tuple[str, ...], Any] = {}  # by the day they are for: None while read
        self._day_later_threads: list[threading.Thread] = []
        self._day_later_queue: list[tuple[tuple[str, ...], Callable[[], Any]]] = []

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

    def quick(self, path: str, query: str = "", if_none_match: str | None = None) -> Response | None:
        """The answer that reads nothing of the record, or None: the icon, a form's address asked with
        a GET, and a page the build holds (`_built`). The server answers these on the request's own
        thread; everything else is a reading, under the limit (`Handler`)."""
        if path == "/favicon.ico":
            return Response(204, b"", "image/x-icon")
        if path in WRITE_PATHS or path in LINE_ACTS:
            return self._error(405, f"{path} takes the forms of the server's own pages (POST), nothing else")
        if DAY_ACT.match(path) is not None:
            return self._error(405, f"{path} takes the Day page's forms (POST), nothing else")
        if self.library is not None and (built := self._built(path, query, if_none_match)) is not None:
            return built  # what the build wrote: no index opened, nothing read
        return None

    def still_reading(self, path: str, query: str, limit_s: float) -> Response:
        """The page a reading over the limit is answered with (503): what happened and when the page
        will be there, in one sentence each, never a spinner. With the build, the page is being
        built in the background; without it (live, the default), the reading was stopped."""
        target = path + (f"?{query}" if query else "")
        again = f'<a href="{escape(target)}">this page again</a>'
        if self.library is not None:
            said = (
                f"This page reads more of the record than the server reads while you wait ({limit_s:g} s)."
                " It is being built now, in the background, and will be here as a page of its own in a"
                f" few minutes; every other door opens as usual. Try {again} then."
            )
        else:
            said = (
                f"This page took longer than {limit_s:g} s to read, so the reading was stopped and this"
                " machine is free for the other pages; `logbook serve` without `--limit` reads every page"
                f" to its end. Try {again}, or the front page."
            )
        body = f'<h1>Still reading</h1>\n<p class="busy">{said}</p>\n<p><a href="/">The front page</a></p>\n'
        return Response(503, self.document("still reading", body).encode("utf-8"))

    def respond(self, path: str, query: str = "", if_none_match: str | None = None) -> Response:
        """The page at `path`. `if_none_match` is the request's header: when it names the page's
        tag, a 304 and nothing rendered. The tag is taken before the page is read, so a head that
        moves in between makes the tag older than the page, never newer: the next reload reads it
        again rather than keeping a stale page."""
        if (found := self.quick(path, query, if_none_match)) is not None:
            return found
        meta = self.current()
        self._add_indexes(str(meta.get("head")))
        if path == TODAY:
            return self._today(meta)
        if (photo := PHOTO_PATH.match(path)) is not None:
            return self._photo(unquote(photo.group(1)), if_none_match)
        etag = self.etag(path, query, meta)
        if etag is not None and if_none_match is not None and _matches(if_none_match, etag):
            return Response(304, b"", etag=etag)
        if etag is not None and (kept := self._kept_page(etag)) is not None:
            return kept  # the tag names the page: what the browser may keep, the server may keep too
        params = {k: v[-1] for k, v in parse_qs(query, keep_blank_values=True).items()}
        csp = PLACES_CSP if path == "/places" else WORLD_CSP if path == "/world" else CSP
        if DAY_PATH.match(path) is not None:
            csp = DAY_CSP if self._records() else DAY_IMAGES
        said = _READS.set(None)
        try:
            rendered = self._page(path, params).encode("utf-8")
            response = Response(200, rendered, etag=etag, csp=csp, reads=_READS.get())
            if etag is not None:
                self._keep(etag, response)
            if self.library is not None:
                self._build_too(path, query, meta, response)
            return response
        except NotFound as e:
            return self._error(404, str(e))
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
        except people.PersonError as e:  # nobody the record names, several, or the owner
            return self._error(404, f"no page at {path}: {e}")
        except orgs.OrgError as e:  # an org the record does not name
            return self._error(404, f"no page at {path}: {e}")
        except ideas.IdeaError as e:  # an idea the record does not name
            return self._error(404, f"no page at {path}: {e}")
        except entities.EntityError as e:  # policy/entities.json not what it should be
            return self._error(500, str(e))
        except ValueError as e:  # a day that is not one, a window that runs backwards, a year that is not
            return self._error(400, str(e))
        finally:
            _READS.reset(said)

    def reads(self, first: str, last: str, kinds: Sequence[str] = ()) -> None:
        """Say that the page being rendered is made of the lines of the local days `first` to `last`, of
        `kinds` those of any day, and the settings and who is who (`Reads`): its response carries it,
        and the build renders it again only when a line comes for those. A page that says nothing is
        made of the whole record."""
        _READS.set(Reads(first, last, tuple(kinds)))

    def _built(self, path: str, query: str, if_none_match: str | None) -> Response | None:
        """The page the build holds at this address, as it was written; None when it holds none, or
        the page is one the server always renders (`library_build.live`: today's Day, `/today`)."""
        assert self.library is not None
        try:
            today = day_start.of(self.lb.meta).today(self.now()).isoformat()
        except (day_start.DayStartError, KeyError, ValueError):
            return None  # the page that says why is rendered
        if library_build.live(path, today):
            return None
        found = self.library.page(library_build.address(path, query))
        if found is None:
            return None
        page, body = found
        if if_none_match is not None and _matches(if_none_match, page.etag):
            return Response(304, b"", etag=page.etag)
        csp = page.csp if page.csp is not None else CSP
        return Response(page.status, body, etag=page.etag, location=page.location, csp=csp)

    def _build_too(self, path: str, query: str, meta: Mapping[str, Any], response: Response) -> None:
        """A page the build did not hold, rendered for this request, added to it (`asked`): the next
        visit is a file. Never today's Day, and never a page the clock alone moves faster than a build."""
        assert self.library is not None
        try:
            today = day_start.of(meta).today(self.now()).isoformat()
        except (day_start.DayStartError, KeyError, ValueError):
            return
        if library_build.live(path, today):
            return
        target, head = library_build.address(path, query), str(meta.get("head") or "")
        with contextlib.suppress(OSError):  # a full disk or a cache folder gone: the page was answered
            self.library.put(target, response, head, asked=True)

    def _after_act(self, path: str, form: Mapping[str, str], response: Response) -> None:
        """An act changed the record: the built pages it changed are dropped at once (the server renders
        them until the build writes them again, so the owner sees what was written), and the rebuild is
        asked for (`on_act`). Which pages: the page the act returns to and the front page; refused
        because the page was older than the record (409), the page the form was on, so the reload is
        the page as it stands (`library_build.touched`)."""
        if self.library is None:
            return
        back = urlsplit(response.location or "").path
        self.library.drop(library_build.touched(self.library.pages(), path, response.status, back, form))
        if self.on_act is not None and response.status < 400:
            self.on_act()

    def write(
        self,
        path: str,
        form: Mapping[str, str],
        client: str,
        origin: str | None,
        upload: Upload | None = None,
        *,
        asked: phone.Asked | None = None,
    ) -> Response:
        """`_write`, and the built pages it changed dropped when it wrote (`_after_act`)."""
        response = self._write(path, form, client, origin, upload, asked=asked)
        with contextlib.suppress(OSError):  # the act is written; a cache that cannot be told is the build's
            self._after_act(path, form, response)
        return response

    def _write(
        self,
        path: str,
        form: Mapping[str, str],
        client: str,
        origin: str | None,
        upload: Upload | None = None,
        *,
        asked: phone.Asked | None = None,
    ) -> Response:
        """A POST: one of the forms of the server's own pages, each through the function the CLI
        runs for the same act. The Library's (`WRITE_PATHS`), under the record's writer lock: the
        Places page's (`_write_place`), the Journeys page's name (`_write_name`), the People page's
        review (`_write_review`), the Manifest's queue and an org's status (`_write_manifest`), the
        Ideas shelf's queue and an idea's status (`_write_ideas`). A Day's: Reflect and Sign
        (`_reflect`, `_sign`), through `day reflect`'s own functions, and the star and the "with…"
        field (`_star`, `_with`), through `logbook star`, `unstar` and `with`'s.
        Another command writing the record is the same answer on every one of them, caught here
        once (`_busy`: a 409, the form kept), and nothing is written. Refused (403, nothing
        written) unless `client`, the connection's address, is loopback and `origin`, the browser's
        Origin header when it sent one, names 127.0.0.1: this machine, the server's own pages. A
        request that came through a proxy (`phone.proxied`: `asked`, its headers, name a Host that is
        not 127.0.0.1 or [::1], or carry a `Tailscale-*` or `X-Forwarded-*` header) is answered only
        when `logbook.json` names the owner's phone (`phone`, off by default) and the headers are the
        phone's (`phone.allows`: the Origin, the Host and the login the setting names, read with each
        POST), and never by the Origin's absence. A
        field sent more than once (the Sign form's boxes) arrives as its values joined with commas,
        as `--accept N,N` takes them; `upload` is the file a form carried, the Day's recording. One
        write at a time (`_write_lock`)."""
        day_act = DAY_ACT.match(path)
        if path not in WRITE_PATHS and path not in LINE_ACTS and day_act is None:
            posts = ", ".join(WRITE_PATHS)
            return self._error(
                404,
                f"nothing to post at {path}; the server's own forms post to {posts}, a Day's to"
                f" /day/YYYY-MM-DD/reflect and /day/YYYY-MM-DD/sign, {STAR_PATH} and {WITH_PATH}",
            )
        # through Tailscale Serve (or any proxy): the phone's checks, or nothing
        proxied = phone.proxied(asked)
        if (
            not _loopback(client)
            or (proxied and not phone.allows(self.lb.meta, origin, asked))
            or (not proxied and origin is not None and not _loopback_origin(origin))
        ):
            where = f"from {client!r}" + (f", origin {origin!r}" if origin is not None else "")
            what = {
                REVIEW_PATH: "a place is named from this machine only, through the server's own pages or"
                " `logbook setup places review`",
                NAME_PATH: "a journey is named from this machine only, through the server's own pages or"
                " `logbook add --trip`",
                PEOPLE_REVIEW_PATH: "a person is merged or told apart from this machine only, through the"
                " server's own pages or `logbook people review`",
                STAR_PATH: "a line is starred from this machine only, through the server's own pages or"
                " `logbook star` and `logbook unstar`",
                WITH_PATH: "company is stated from this machine only, through the server's own pages or"
                " `logbook with`",
                MANIFEST_REVIEW: "an org is named or told apart from this machine only, through the server's"
                " own pages or `logbook review org`",
                MANIFEST_STATUS: "an org's status is set from this machine only, through the server's own"
                " pages or `logbook status org`",
                IDEAS_REVIEW: "an idea is named or told apart from this machine only, through the server's"
                " own pages or `logbook review idea`",
                IDEAS_STATUS: "an idea's status is set from this machine only, through the server's own"
                " pages or `logbook status idea`",
            }.get(
                path,
                "a day is reflected on and signed from this machine only, through the server's own"
                " pages or `logbook day reflect`",
            )
            return self._error(403, f"refused {where}: {what}, {phone.FROM_PHONE}; nothing was written")
        try:
            if day_act is not None:
                day, act = day_act.group(1), day_act.group(2)
                return self._reflect(day, form, upload) if act == REFLECT else self._sign(day, form)
            if path == STAR_PATH:
                return self._star(form)
            if path == WITH_PATH:
                return self._with(form)
            if path in MANIFEST_PATHS:
                return self._write_manifest(path, form)
            if path in IDEAS_PATHS:
                return self._write_ideas(path, form)
            acts = {
                REVIEW_PATH: self._write_place,
                NAME_PATH: self._write_name,
                PEOPLE_REVIEW_PATH: self._write_review,
            }
            with self._write_lock, self._review_lock, self.lb.writer(command="logbook serve", wait=False):
                return acts[path](form)
        except Locked as e:  # every act's one answer, whichever took the lock
            return self._busy(path, form, e, upload)

    def _busy(self, path: str, form: Mapping[str, str], e: Locked, upload: Upload | None) -> Response:
        """Another command holds the record's writer lock: the one answer of every act (the owner's
        word of 14 October 2026), raised before anything is written. A 409; the one sentence (`BUSY`),
        who holds the lock in the store's words, and the form as it was sent, in a form that posts it
        to `path` again: the words the owner typed (`TYPED`) in plain fields (the page's completion
        of names and its language are not carried), the rest hidden. A recording cannot be put back
        by a page: its form asks for the file again."""
        held = escape(str(e).replace(NOT_WAITING, ""))
        out = [
            f'<h1>409</h1>\n<p class="busy">{escape(BUSY)}</p>\n<p class="mute">The lock: {held}.</p>\n'
            f'<form class="again" method="post" action="{escape(path)}"'
            + (' enctype="multipart/form-data"' if upload is not None else "")
            + ">\n"
        ]
        for name, value in form.items():
            if name == "text":
                out.append(
                    f'<textarea name="text" rows="6" aria-label="{TYPED[name]}">{escape(value, quote=False)}'
                    "</textarea>\n"
                )
            elif name in TYPED:
                out.append(
                    f'<input type="text" name="{name}" value="{escape(value)}" aria-label="{TYPED[name]}"'
                    ' autocomplete="off">\n'
                )
            else:
                out.append(f'<input type="hidden" name="{escape(name)}" value="{escape(value)}">\n')
        if upload is not None:
            out.append(
                '<label>the recording, again <input type="file" name="audio" accept="audio/*"></label>\n'
            )
        out.append("<button>Try again</button>\n</form>\n")
        return Response(409, self.document("409", "".join(out)).encode("utf-8"))

    def _write_place(self, form: Mapping[str, str]) -> Response:
        """The Places page's form: `act` `name` (the field `name`, else the name proposed) or
        `reject` on the cluster `id`, through `places_review.accept` and `reject`, the one path the
        CLI's `--name`, `--accept` and `--reject` take. A cluster no longer in the queue (named or
        rejected since the page was read) is a 409; a name the engine refuses a 400. Done, a 303 to
        the page the form came from, at the next cluster."""
        act, cluster = form.get("act", ""), form.get("id", "")
        page = form.get("page", "1")
        page = page if page.isdigit() and int(page) >= 1 else "1"
        if act not in ("name", "reject") or not cluster:
            return self._error(400, "the form names a cluster (id) and an act: name or reject")
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
        if act == DREAM:
            return self._dream(day)
        if act not in (REFLECT, HEAR):
            return self._error(
                400,
                "the form names an act: reflect, with your words, hear, with a recording, or dream, the"
                " day so far",
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
        """Keep and sign (RFC 0043 §5): the day signed through `reflect.close`, the code `day reflect
        --sign` runs, with the reflection standing on the day, the proposals ticked (`accept`, N,N as
        `--accept` takes them; none ticked accepts none) and what the owner keeps (`_keeping`: the
        pencil's sentences and links `keep`, N,N as `--keep` takes them, a kept decision's day
        `revisit-N`, the day in a word `word`, a task's answer `task-N`), all under one hold of the
        writer lock: every item checked and made before the first line (`keep.prepared`), then the
        delegations as notes, the kept lines (`keep.write`), and `signing.sign` with the lines
        confirmed, the accepted dispositions and the reflection, now. A day signed already is signed
        again, the new signature superseding it and keeping what it said. Refused (409, nothing
        written) when the reflection, its proposals, the pencil kept from (`draft`) or the tasks
        answered (`tasks`) are not those the page showed, and when there is no reflection to sign
        with; what Keep and sign refuses is a 400 in its one sentence (`keep.KeepError`)."""
        if form.get("act") != SIGN:
            return self._error(400, "the form names the act: sign")
        try:
            day, today = self._closing_day(day)
            wanted = reflect.numbers(form.get("accept") or reflect.NONE)
            asking = _keeping(form)
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
                    pencil = "" if found.pencil is None else str(found.pencil["line"])
                    if (asking.keep or asking.revisit) and form.get("draft", "") != pencil:
                        raise Stale(
                            f"the pencil changed since this page was read (dreamed again, or no longer"
                            f" shown); /day/{day} is the day as it stands, and nothing was written"
                        )
                    if asking.tasks and form.get("tasks", "") != _tasks_digest(self._plan_now(day)):
                        raise Stale(
                            f"today's tasks changed since this page was read; /day/{day} is the day as it"
                            " stands, and nothing was written"
                        )
                    accepted = reflect.chosen(found.proposals, wanted)
                    reflect.close(self.lb, day, today, r, accepted, keeping=asking)
            except (HeadMoved, Stale) as e:
                return self._error(409, str(e))
            except ValueError as e:  # ReflectError, SignError, NoteError
                return self._error(400, str(e))
        return Response(303, b"", location=f"/day/{day}#{CLOSE}")

    def _plan_now(self, day: str) -> plan_reader.Plan | None:
        """Today's tasks as `keep` will read them when it answers one, read now under the lock: None
        for a mapping that cannot be read (`keep` says why in its own sentence)."""
        try:
            return plan_reader.read(self.lb, day)
        except plan_reader.PlanError:
            return None

    def _dream(self, day: str) -> Response:
        """*Dream the day so far* (RFC 0043 §6 rule 1): `dream day TODAY --evening` through
        `dream.dream`, the function the command runs, under the record's writer lock, the draft it
        writes shown in pencil above the form. Today only, and only under the owner's `dream` entry:
        no entry, an expired one, an endpoint not set, a day with nothing to dream, a 400 in the
        dream's own sentence, and nothing sent; the model's answer failing, a 502, nothing written.
        Done, a 303 to the Day at its pencil."""
        try:
            day, today = self._closing_day(day)
        except ValueError as e:
            return self._error(400, str(e))
        if day != today:
            return self._error(
                400,
                f"Dream the day so far is for today, {today}; `logbook dream day {day}` dreams {day} whole",
            )
        with self._write_lock:
            try:
                with self.lb.writer(command="logbook serve", wait=False):
                    self.current()
                    dream.dream(self.lb, day, airports=self.airports, evening=True)
            except HeadMoved as e:
                return self._error(409, str(e))
            except dream.AnswerError as e:
                return self._error(502, str(e))
            except (dream.DreamError, stays.SettingsError, ValueError) as e:
                return self._error(400, str(e))
        return Response(303, b"", location=f"/day/{day}#{PENCIL}")

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
            pencil, _withheld = drafts.for_day(idx, day, allowed=drafts.allowed(self.lb.root))
        kept = None
        if earlier is not None and r is not None and r.note is not None:
            page = reflect.on_page(lines, retracted)
            kept = reflect.signature(earlier, page, [str(r.note["id"])], []).kept
        shown = json.dumps([p.to_json() for p in proposals], sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(shown.encode("utf-8")).hexdigest()[:16]
        draft = pending[-1] if pending else None
        words = notes.standing(lines, keep.WORD, retracted)
        word = words[0] if words else None
        return Closing(lines, retracted, r, proposals, draft, earlier, kept, digest, pencil, word)

    def _star(self, form: Mapping[str, str]) -> Response:
        """The Day page's star: `act` `star` or `unstar` on the `line` of a row of `day`, through
        `stars.star` and `stars.unstar`, the functions `logbook star` and `logbook unstar` run, so
        the line written is theirs. A star on a line starred already writes nothing; an unstar of a
        line no longer starred (the page was older than the record) is a 409, a line that takes no
        star a 400; another command writing the record the Library's one answer (`_busy`), and
        nothing written. The photo review posts here too (`from` photos): Star as any star, and Not a
        keeper (`act` pass) through `day_photos.pass_over`, which writes no line, only the review's
        bookkeeping, under the same lock; a line that is not a photo of the day standing is a 400.
        Done, a 303 to the Day at the row (`open` keeps an expanded page expanded), or at the review."""
        act, line, day = form.get("act", ""), form.get("line", "").strip(), form.get("day", "")
        if act not in ("star", "unstar", PASS) or not line:
            return self._error(400, "the form names a line and an act: star, unstar or pass")
        try:
            day = parse_day(day).isoformat()
        except ValueError as e:
            return self._error(400, str(e))
        with self._write_lock:
            try:
                with self.lb.writer(command="logbook serve", wait=False):
                    self.current()
                    if act == "star":
                        stars.star(self.lb, line)
                    elif act == "unstar":
                        stars.unstar(self.lb, line)
                    elif line not in self._day_marks(day).photos:
                        return self._error(
                            400,
                            f"{line} is not a photo of {day} standing; Not a keeper is for the day's photos",
                        )
                    else:
                        day_photos.pass_over(self.lb, line, now_utc())
            except stars.NotStarred as e:
                return self._error(409, f"{e}; /day/{day} is the day as it stands")
            except stars.StarError as e:
                return self._error(400, str(e))
            except HeadMoved as e:
                return self._error(409, str(e))
        anchor = PHOTOS if form.get("from") == PHOTOS else _row_id(line)
        back = f"/day/{day}" + ("?open=1" if form.get("open") == "1" else "") + f"#{anchor}"
        return Response(303, b"", location=back)

    def _with(self, form: Mapping[str, str]) -> Response:
        """The Day page's "with…" field: the `names` given (one, or several split at commas) on
        `day`, at `at` (`HH:MM`) when the clock was filled in, through `presence.state`, the function
        `logbook with` runs, so the lines written are its. A name the record does not place is a
        400 with the people-review hint; another command writing the record the Library's one
        answer (`_busy`); nothing is written either way. Done, a 303 to the Day."""
        day, at = form.get("day", ""), form.get("at", "").strip() or None
        names = [name for name in form.get("names", "").split(",") if name.strip()]
        try:
            day = parse_day(day).isoformat()
        except ValueError as e:
            return self._error(400, str(e))
        if not names:
            return self._error(400, "name at least one person in the field")
        with self._write_lock:
            try:
                with self.lb.writer(command="logbook serve", wait=False):
                    self.current()
                    presence.state(self.lb, day, names, at, now=self.now())
            except presence.WithError as e:
                return self._error(400, str(e))
            except HeadMoved as e:
                return self._error(409, str(e))
        return Response(303, b"", location=f"/day/{day}#with")

    def _records(self) -> bool:
        """Whether a Day page carries the recording form and its script: a server that can hear."""
        return not self.static and self.voice is not None and self.voice.hear is not None

    def _write_name(self, form: Mapping[str, str]) -> Response:
        """The Journeys page's form: the field `name` names the journey `id` through
        `journeys.name`, what `logbook add --trip ID "NAME"` runs. A journey that is no longer one
        (the record moved its bounds since the page was read) is a 409; no words a 400. Done, a 303
        to the journey's page, which reads the record again."""
        trip_id = form.get("id", "")
        bounds = trip_id.split(":")
        if len(bounds) != 3 or bounds[0] != "trip" or not all(DAY.fullmatch(b) for b in bounds[1:]):
            return self._error(400, "the form names a journey (id, trip:YYYY-MM-DD:YYYY-MM-DD) and its name")
        self.current()
        try:
            journeys.name(self.lb, trip_id, form.get("name", ""), self.airports)
        except journeys.JourneyError as e:
            return self._error(400, str(e))
        except stays.SettingsError as e:
            return self._error(500, str(e))
        except ValueError as e:
            back = f"/journeys?year={bounds[1][:4]}"
            return self._error(409, f"{trip_id} is not a journey of the record as it stands ({e}); {back}")
        return Response(303, b"", location=f"/journeys/{bounds[1]}/{bounds[2]}")

    def _write_review(self, form: Mapping[str, str]) -> Response:
        """The People page's review queue: `act` `merge` accepts the proposal `id` through
        `people_review.accept` (what `people review --accept N` writes: an alias line per
        identifier seen), `reject` writes through `people_review.reject` (`--reject N`: the two are
        not the same person). A proposal no longer in the queue is a 409; one the engine refuses a
        400. Done, a 303 to the queue on the page the form came from (`year`)."""
        from . import people_review

        act, proposal_id = form.get("act", ""), form.get("id", "")
        year = form.get("year", "")
        if act not in ("merge", "reject") or not proposal_id:
            return self._error(400, "the form names a proposal (id) and an act: merge or reject")
        back = "/people" + (f"?year={year}" if YEAR.fullmatch(year) else "") + "#review"
        self.current()
        report = people_review.read(self.lb)
        found = [p for p in report.proposals if p.id == proposal_id]
        if not found:
            return self._error(
                409,
                f"{proposal_id} is not in the queue: merged or told apart already, or the page was older"
                f" than the record; {back.partition('#')[0]} is the queue as it stands",
            )
        try:
            if act == "merge":
                people_review.accept(self.lb, report, found)
            else:
                people_review.reject(self.lb, report, found)
        except people_review.ReviewError as e:
            return self._error(400, str(e))
        return Response(303, b"", location=back)

    def current(self) -> dict[str, Any]:
        """`logbook.json` as it is now. When its head has moved since the last request (a sync
        appended while the server runs), the index is brought to the new head here, once, under a
        lock, before any page reads it: the requests that arrive together wait for that one rebuild
        instead of each starting its own on the same file. While a writer is between `logbook.json`
        and the index, the index is read as it stands and never rebuilt (`Logbook.index`): the meta
        returned then names the last line the index holds, so a page's tag names what it read."""
        meta = self.lb.meta
        head = str(meta.get("head"))
        if head != self._head:
            with self._lock:
                if head != self._head:
                    with self.lb.index() as idx:
                        seq, indexed = idx.indexed()
                    if indexed != head:  # a writer between logbook.json and the index: what it holds
                        return {**meta, "seq": seq, "head": indexed}
                    self._head = head
                    with self._kept_lock:  # every kept page names the old head in its tag
                        self._kept.clear()
                        self._kept_bytes = 0
        return meta

    def _add_indexes(self, head: str) -> None:
        """An index built before `index.ADDED` is given them here, on a GET, once a head: never by an
        act, which reads `current` under the writer lock, and never while one of this server's own
        acts writes (`_write_lock`, not waited for: the next GET asks again). `Index.add_indexes` takes
        the record's writer lock without waiting; when another process holds it, the next head tries
        again, and when one of this server's readers held the file, the next GET."""
        if head == self._indexed or not self._write_lock.acquire(blocking=False):
            return
        try:
            if head != self._indexed:
                with Index.open(self.lb) as idx:  # never a rebuild here: `current` makes those
                    if idx.add_indexes():
                        self._indexed = head
        finally:
            self._write_lock.release()

    def _kept_page(self, etag: str) -> Response | None:
        with self._kept_lock:
            found = self._kept.pop(etag, None)
            if found is not None:
                self._kept[etag] = found  # the latest asked for last
            return found

    def _keep(self, etag: str, response: Response) -> None:
        """Keep a page by its tag, so the next request for it is answered without reading: the tag
        is the head, the request and everything else the page reads (`etag`), so the same tag is the
        same page, as the browser's `304` already holds. `PAGES_KEPT` pages and `PAGE_BYTES_KEPT`
        bytes at most, the one asked for longest ago going first; a head that moves drops them all."""
        with self._kept_lock:
            if etag in self._kept or len(response.body) > PAGE_BYTES_KEPT:
                return
            self._kept[etag] = response
            self._kept_bytes += len(response.body)
            while len(self._kept) > PAGES_KEPT or self._kept_bytes > PAGE_BYTES_KEPT:
                oldest = next(iter(self._kept))
                self._kept_bytes -= len(self._kept.pop(oldest).body)

    def shared(self, key: tuple[Any, ...], build: Callable[[], T]) -> T:
        """What `build` reads, read once for the record as it stands and handed to every request that
        asks for `key` until it moves: the same head, the same settings beside the chain and the same
        day (`_state`, what a page's tag digests besides the request). Requests that ask together wait
        for one build. A page reads it and never changes it."""
        state = self._state(self.lb.meta)
        with self._kept_lock:
            if state != self._shared_state:
                self._shared.clear()
                self._building.clear()
                self._shared_state = state
            building = self._building.setdefault(key, threading.Lock())
        with building:
            with self._kept_lock:
                if self._shared_state == state and key in self._shared:
                    found: T = self._shared[key]
                    return found
            found = build()
            with self._kept_lock:
                if self._shared_state == state:
                    self._shared[key] = found
                    while len(self._shared) > SHARED_KEPT:  # a `?since=` asked of every day: the oldest go
                        self._shared.pop(next(iter(self._shared)))
            return found

    def _day_reading(self, key: tuple[str, ...], build: Callable[[], T]) -> T:
        """What the Day reads beside the day (`day_rhythm`), kept for the record as it stands as
        `shared` keeps a page's readings, in a pool of its own (`DAY_KEPT`), so paging through days
        never pushes out what `shared` keeps for the other pages."""
        state = self._state(self.lb.meta)
        with self._kept_lock:
            if state != self._day_state:
                self._day_kept.clear()
                self._day_state = state
            if key in self._day_kept:
                kept: T = self._day_kept[key]
                return kept
        found = build()
        with self._kept_lock:
            if self._day_state == state:
                self._day_kept[key] = found
                while len(self._day_kept) > DAY_KEPT:
                    self._day_kept.pop(next(iter(self._day_kept)))
        return found

    def _day_later(self, key: tuple[str, ...], build: Callable[[], T]) -> T | None:
        """A reading the Day shows a part of that reads more than the day (the drift for one reconnect,
        the replies owed, the decisions to revisit), kept by `key`: the part, the day, and for one that a
        sync changes the head. Seconds to minutes on a record of millions of lines. With `read_later`
        (`logbook serve`) it is read off the request, on one thread started once the page is rendered
        (`_day_later_start`), so no page waits for it and none is slowed while it renders: until it has
        arrived, the latest reading of the same part and day stands in (None when there is none), and
        the Day's tag names what has arrived, so the page is read again once it has. Without it (a test,
        a script) it is read on the request. `DAY_LATER_KEPT` at most, the oldest going first."""
        with self._kept_lock:
            if key in self._day_later_kept and self._day_later_kept[key] is not None:
                kept: T = self._day_later_kept[key]
                return kept
            if self.read_later:
                if key not in self._day_later_kept:
                    self._day_later_kept[key] = None
                    self._day_later_queue.append((key, build))
                    self._day_later_trim()
                earlier: T | None = next(
                    (
                        v
                        for k, v in reversed(self._day_later_kept.items())
                        if k[:2] == key[:2] and v is not None
                    ),
                    None,
                )
                return earlier
        now = build()
        with self._kept_lock:
            self._day_later_kept[key] = now
            self._day_later_trim()
        return now

    def _day_later_trim(self) -> None:
        while len(self._day_later_kept) > DAY_LATER_KEPT:  # under `_kept_lock`
            self._day_later_kept.pop(next(iter(self._day_later_kept)))

    def _day_later_start(self) -> None:
        """Read what the page asked to be read later (`_day_later`), one after the other, on one thread:
        no lock held but each reading's own, as every page's (a sync appends beside it, as beside any
        long page). A reading that fails is none for its key, not read again; its error goes to stderr."""
        with self._kept_lock:
            queue, self._day_later_queue = self._day_later_queue, []
            if not queue:
                return
        queue.sort(key=lambda item: item[0][0] == "drift")  # the whole record last: the rest in seconds

        def read() -> None:
            for key, build in queue:
                found: Any = ()
                try:
                    found = build()
                finally:
                    with self._kept_lock:
                        if key in self._day_later_kept:
                            self._day_later_kept[key] = found

        thread = threading.Thread(target=read, name="day-later", daemon=True)
        with self._kept_lock:
            self._day_later_threads = [t for t in self._day_later_threads if t.is_alive()]
            self._day_later_threads.append(thread)
        thread.start()

    def settle(self, timeout: float | None = None) -> None:
        """Wait for the readings the Day started off the request (`_day_later`): for a test, the bench."""
        with self._kept_lock:
            threads = list(self._day_later_threads)
        for thread in threads:
            thread.join(timeout)

    def _day_later_tag(self) -> str:
        with self._kept_lock:
            return ",".join(" ".join(k) for k, v in self._day_later_kept.items() if v is not None)

    def _state(self, meta: Mapping[str, Any]) -> str:
        """The record as the pages read it: `logbook.json`, the record's today, and the settings,
        bookkeeping and pages beside the chain that `etag` digests."""
        try:
            today = day_start.of(meta).today(self.now()).isoformat()
        except day_start.DayStartError:
            today = "-"
        parts = [json.dumps(meta, sort_keys=True), today, *self._beside()]
        return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()

    def etag(self, path: str, query: str, meta: Mapping[str, Any]) -> str | None:
        """The tag of a page that is the record's and nothing else: the head, then a digest of the
        request and what else the pages read — the rest of `logbook.json`, the settings beside the
        chain (`places.json`, `assets.json`, `policy/`), the review's bookkeeping in `state/`, the
        pages received from the circle, this server's start, and for a Day the day the owner is in
        (its forms are there from that day on). One page's tag never stands for
        another's, and a request that is an error is given none. None for a page the clock moves
        (`/assets`, `/gaps`) or a path with no page. The server keeps a page by its tag (`_keep`), so
        anything a page comes to read beside the chain must be digested here (`_beside`): what the tag
        does not name, a kept page never reads again until the head moves."""
        if (
            path not in RECORD_PAGES
            and DAY_PATH.match(path) is None
            and JOURNEY_PATH.match(path) is None
            and PERSON_PATH.match(path) is None
            and ORG_PATH.match(path) is None
            and IDEA_PATH.match(path) is None
            and LINE_PATH.match(path) is None
            and WEEK_PATH.match(path) is None
        ):
            return None
        parts = [self._started, path, query, json.dumps(meta, sort_keys=True)]
        # a week's plan, and its trip's days to go, move with the record's today
        if (
            DAY_PATH.match(path) is not None
            or WEEK_PATH.match(path) is not None
            or path.startswith(CLOCK_PAGES)
        ):
            # a Day's forms are there from the day the owner is in; this year, the coming
            # anniversaries and a silence move with it too
            try:
                parts.append(day_start.of(meta).today(self.now()).isoformat())
            except day_start.DayStartError:
                parts.append("-")
        if (day := DAY_PATH.match(path)) is not None:  # today's shape and its now line move with the clock
            parts.append(day_rhythm.clock_tag(day.group(1), meta, self.now()))
            parts.append(self._day_later_tag())  # a reconnect read off the request has arrived
        parts += self._beside()
        digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
        return f'"{str(meta.get("head") or "")[:HEAD_CHARS]}-{digest[:16]}"'

    def _beside(self) -> list[str]:
        """What the pages read beside the chain, each file as its path and its stat: the places, the
        assets, the policies, the review's bookkeeping and the pages received from the circle."""
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
        parts = []
        for file in read:
            try:
                st = file.stat()
            except OSError:
                parts.append(f"{file.relative_to(root).as_posix()} -")
                continue
            parts.append(f"{file.relative_to(root).as_posix()} {st.st_mtime_ns} {st.st_size} {st.st_ino}")
        return parts

    def _today(self, meta: Mapping[str, Any]) -> Response:
        """A redirect to the Day the owner is in now: the current date in the record's timezone,
        the date before until the record's `day_start` (RFC 0036); never kept, since it moves."""
        try:
            day = day_start.of(meta).today(self.now()).isoformat()
        except day_start.DayStartError as e:
            return self._error(500, str(e))
        body = f'<p><a href="/day/{day}">{day}</a></p>\n'
        return Response(302, self.document("today", body).encode("utf-8"), location=f"/day/{day}")

    def _standing_line(self, line_id: str) -> tuple[Line | None, Line | None]:
        """The line `line_id` through the gate `tiers`, and the retraction that took it back when
        one did; (None, None) for a line the record does not have, one the gate leaves out, one
        whose retraction it leaves out (the line no longer stands, and why is above the gate), and a
        model's draft the `dream` entry withholds (`drafts.allowed`: the Day shows its row, never
        its words): a page never tells these apart."""
        with self.lb.index() as idx:
            found = idx.by_id(line_id)
            if found is None or not reading.crossing([found], self.tiers):
                return None, None
            retraction = retractions(idx.retractions()).get(str(found["id"]))
        if retraction is not None and not reading.crossing([retraction], self.tiers):
            return None, None
        if found.get("kind") == drafts.KIND and not drafts.allowed(self.lb.root).allows(found):
            return None, None
        return found, retraction

    def _photo(self, line_id: str, if_none_match: str | None) -> Response:
        """`/photo/ID`: the pixels of the photo line `ID` from the record's own attachment store
        (`day_photos.stored`), as the Day page's thumbnail shows them: only for a photo line that
        stands and that the gate lets through, in a media type every browser draws; a 404 for
        anything else, a line or not, so a reader learns nothing of a line above its gate. Its tag is
        the file's digest: the same bytes, kept."""
        line, retraction = (None, None) if self.static else self._standing_line(line_id)
        found = day_photos.opened(self.lb, line) if line is not None and retraction is None else None
        if found is None:
            return self._error(404, f"no photo at /photo/{line_id} on this machine")
        stored, data = found
        etag = f'"photo-{stored.sha256[:32]}"'
        if if_none_match is not None and _matches(if_none_match, etag):
            return Response(304, b"", etag=etag)
        return Response(200, data, stored.media_type, etag=etag)

    def page_line(self, line_id: str) -> str:
        """`/line/ID`: one line as the record holds it, read-only: what it is, when, from which
        source and at which tier, the day it is on (a link to that Day), whether it was retracted,
        then the line itself as JSON. Through the gate `tiers`: a line above it is no line here
        (`NotFound`, the words a line the record does not have gets)."""
        line, retraction = self._standing_line(line_id)
        if line is None:
            raise NotFound(f"no line {line_id} on this page")
        tz = ZoneInfo(str(line.get("tz") or self.lb.meta["timezone"]))
        at = stays.instant(line.get("at"))
        day = day_start.of(self.lb.meta).day(at).isoformat() if at is not None else None
        payload = line.get("payload") or {}
        schema = str(payload.get("schema") or line.get("kind")) if isinstance(payload, dict) else "sealed"
        parts = [
            f"<h1>line #{int(line['seq'])} <small>{escape(schema)}</small></h1>\n",
            '<dl class="header">\n',
            _dt("at", _clock(str(line["at"]), tz) if at is not None else str(line.get("at"))),
            *([_dt("end", _clock(str(line["end"]), tz))] if line.get("end") else []),
            _dt("source", str(line.get("source"))),
            _dt("tier", str(line.get("tier"))),
        ]
        if day is not None:
            parts.append(f"<dt>day</dt><dd>{self.link(escape(day), f'/day/{day}')}</dd>\n")
        if retraction is not None:
            reason = (retraction.get("payload") or {}).get("reason")
            said = f"retracted by #{int(retraction['seq'])}" + (f": {reason}" if reason else "")
            parts.append(_dt("standing", said))
        parts.append("</dl>\n")
        parts.append(
            '<p class="mute">The line as the record holds it, read-only: nothing on this page writes,'
            " and the line is never rewritten.</p>\n"
        )
        shown = json.dumps(line, indent=2, ensure_ascii=False)
        parts.append(f'<pre class="line">{escape(shown)}</pre>\n')
        return self.document(f"line #{int(line['seq'])}", "".join(parts), style=LINE_STYLE)

    def _page(self, path: str, params: Mapping[str, str]) -> str:
        if path == "/":
            return self.page_index()
        if (m := DAY_PATH.match(path)) is not None:
            return self.page_day(m.group(1), expanded=params.get("open") == "1", shape=params.get("shape"))
        if (m := LINE_PATH.match(path)) is not None:
            return self.page_line(unquote(m.group(1)))
        if path == "/days":
            return self.page_days(params.get("from") or None, params.get("to") or None)
        if path == "/trips":
            return self.page_trips(params.get("year") or None)
        if path == "/places":
            return self.page_places(params.get("page") or "1", params.get("at") or None)
        if path == "/journeys":
            return self.page_journeys(params.get("year") or None)
        if (m := JOURNEY_PATH.match(path)) is not None:
            return self.page_journey(m.group(1), m.group(2))
        if path == "/people":
            return self.page_people(params.get("year") or None)
        if (m := PERSON_PATH.match(path)) is not None:
            return self.page_person(unquote(m.group(1)))
        if path == "/manifest":
            asked = params.get("portfolio") or ""
            return self.page_manifest(params.get("page") or "1", asked if asked.strip() else None)
        if path == "/manifest/people":
            return self.page_manifest_people()
        if (m := ORG_PATH.match(path)) is not None:
            return self.page_org(unquote(m.group(1)), money=params.get("money") == "1")
        if path == "/ideas":
            return self.page_ideas(params.get("page") or "1")
        if (m := IDEA_PATH.match(path)) is not None:
            return self.page_idea(unquote(m.group(1)))
        if path == "/promises":
            return shelf_promises.page_promises(self, params.get("person") or None)
        if (m := PROMISE_PATH.match(path)) is not None:
            return shelf_promises.page_promise(self, m.group(1))
        if path == "/goals":
            return shelf_goals.page_goals(self)
        if (m := GOAL_PATH.match(path)) is not None:
            return shelf_goals.page_goal(self, unquote(m.group(1)))
        if path == "/agents":
            return shelf_agents.page_agents(self, params.get("page") or "1", params.get("day") or None)
        if path == "/search":
            return search_page.page_search(self, params)
        if path == "/assets":
            return self.page_assets()
        if path == "/gaps":
            return self.page_gaps(params.get("since") or None)
        if path == "/world":
            return self.page_world(params.get("from") or None, params.get("to") or None)
        if (m := WEEK_PATH.match(path)) is not None:
            return week_page.page_week(self, m.group(1), expanded=params.get("open") == "1")
        raise NotFound(f"no page at {path}")

    def _error(self, status: int, message: str) -> Response:
        body = f"<h1>{status}</h1>\n<p>{escape(message)}</p>\n"
        return Response(status, self.document(str(status), body).encode("utf-8"))

    def document(
        self, title: str, body: str, script: str | None = None, footnote: str | None = None, style: str = ""
    ) -> str:
        """One HTML document: the head, the navigation, `body`, the footer and `footnote` under it;
        `script` is the one inline script a page may carry (the Places page's keys, the Day's record
        button), named by hash in that page's policy; `style` what a page adds to the one inline
        stylesheet (the Manifest's, the table pages', so every other page keeps its bytes)."""
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
            f"<style>{STYLE}{style}</style>\n</head>\n<body>\n"
            f"<header><nav>{self.nav}</nav></header>\n<main>\n{body}</main>\n"
            f"<footer>{footer}</footer>\n{'' if script is None else f'<script>{script}</script>' + chr(10)}"
            "</body>\n</html>\n"
        )

    def _whole(self) -> tuple[str, str] | None:
        """The days the owner's track covers, else any line's; None for an empty record."""
        return reading.record_days(self.lb, "location") or reading.record_days(self.lb)

    def tier_small(self, facts: str, tier: int | None) -> str:
        """A shelf header's `<small>`: its facts, then what its tier means in words — `nothing read
        above tier N`, the highest tier among the lines it read, or `no lines` — the scale on hover."""
        words = f"nothing read above tier {tier}" if tier else "no lines"
        return f'<small title="{escape(TIER_TITLE)}">{escape(facts + DOT + words)}</small>'

    def _record_days(self) -> tuple[str, str] | None:
        """`_whole`, read once for the record as it stands (`shared`): `/assets` is never kept."""
        return self.shared(("whole",), self._whole)

    def _nothing_held(self, day: str) -> str:
        """The one sentence of a Day the record holds nothing for (`/today` on a record that ended long
        ago): the record's first and last day, each a link to its Day. Empty when the day holds lines
        the server's tier gate leaves out: the record is not empty there, only this reading."""
        with self.lb.index() as idx:
            held, _per_source = idx.source_days(day, day)
        if held:
            return ""
        whole = self._record_days()
        if whole is None:
            return '<p class="mute">The record has no lines yet.</p>\n'
        first, last = whole
        return (
            f"<p>The record holds nothing for {escape(day)}: its days run from"
            f" {self.link(escape(first), f'/day/{first}')} to"
            f" {self.link(escape(last), f'/day/{last}')}.</p>\n"
        )

    def _last_spoke(self, said: str, last_day: str | None, today: str, runs: str) -> str:
        """The one line of `/gaps` and `/assets` on a record that went quiet before yesterday: `said`
        and when (`last_day`), and that what the page counts (`runs`) still runs to today. Empty
        otherwise."""
        if last_day is None or parse_day(last_day) >= parse_day(today) - timedelta(days=1):
            return ""
        return f'<p class="mute">{escape(said)} {escape(last_day)}; {escape(runs)}.</p>\n'

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
        manifest = (  # the owner's own shelves: never in an exported site, as the navigation has them
            ""
            if self.static
            else f"<li>{self.link('The Manifest', '/manifest')}: the orgs you named, under what you decided"
            " about them; the review of the ones the sources saw.</li>\n"
            f"<li>{self.link('Ideas', '/ideas')}: the ideas you named, by stage, each with its timeline;"
            " the review of the ones the sources saw.</li>\n"
            f"<li>{self.link('Promises', '/promises')}: what was promised in the messages, to whom and by"
            " whom, open first.</li>\n"
            f"<li>{self.link('Goals', '/goals')}: the goals you wrote, by horizon, and the chapter today is"
            " in.</li>\n"
            f"<li>{self.link('Agents', '/agents')}: the sessions with an agent, day by day.</li>\n"
            f"<li>{self.link('Search', '/search')}: the record's words, as logbook search finds them.</li>\n"
        )
        parts.append(
            '<ul class="plain">\n'
            f"<li>{self.link('The last day', f'/day/{whole[1]}')}, {whole[1]}: the Day as a timeline.</li>\n"
            f"<li>{self.link('The last fortnight', f'/days?from={a}&to={b}')}, one row per day.</li>\n"
            f"<li>{self.link(f'Trips of {year}', f'/trips?year={year}')}: runs of nights away.</li>\n"
            f"<li>{self.link('Journeys', '/journeys')}: the trips one at a time, named, with their days,"
            " stays, photos and promises.</li>\n"
            f"<li>{self.link('People', '/people')}: the people the record names, by days together;"
            " the review of who it has not placed.</li>\n"
            f"{manifest}"
            f"<li>{self.link('Places', '/places')}: the named places of the record.</li>\n"
            f"<li>{self.link('Assets', '/assets')}: the assets tracked and the last fix of each.</li>\n"
            f"<li>{self.link('Gaps', '/gaps')}: where each source went quiet.</li>\n"
            f"<li>{self.link('The world', '/world')}: the places of the record on a map of the world.</li>\n"
            "</ul>\n"
        )
        return self.document("Logbook", "".join(parts))

    # -- /day/YYYY-MM-DD ------------------------------------------------------------------------------------

    def page_day(self, day: str, expanded: bool = False, shape: str | None = None) -> str:
        """The Day in its shape (`day_rhythm`): morning, live, evening or signed, computed from the
        clock, the evening hour and the signature on every request, or the one `shape` asks for, shown
        for reading. With `expanded` every toggle is open, so a page prints or saves whole. Each shape
        orders the same parts (`day_rhythm.ORDER`): the header (the eyebrow, the date, where, the
        weather and who, then the night before and after, the signature and the `with` row); what the
        day was for; Yesterday, Today and One person in the morning; the ribbon of the planned beside
        the lived; the owner's words; the pencil; the record, folded (Loose ends, People, the
        timeline under the day's track, each row that is a line linked to it as written, a row's
        photos a strip under it, many edits of one Drive file one row, a row's messages by
        conversation, Looking back, everything the day held, the sources); the photos, the starred
        and the review; every part with nothing named once; then Reflect and sign. A static page
        (`export site`) is the evening's or the signed day's, with no clock, no form and neither fold
        of a row's messages: its rows count the messages, as they did."""
        # the folds from the same reading; a static page (`export site`) keeps to the rows, as before
        data = self._day_reading(
            ("day", day),
            lambda: day_reader.read(self.lb, day, self.airports, self.tiers, held=not self.static),
        )
        tz = ZoneInfo(data["tz"])
        marks = self._day_marks(day)
        star = self._toggle(day, marks.starred, expanded)
        extras = Rows(self._raw(marks), self._strip(day, marks, expanded), marks.lines)
        d = date.fromisoformat(day)
        bounds = day_start.of(self.lb.meta)
        now = self.now().astimezone(tz)
        today = bounds.today(now)
        signed = data.get("signed")
        hour = day_rhythm.evening_hour()  # once a request: the live shape names it too
        if self.static:  # a file has no clock: the day as it closed, or as it was signed
            computed = day_rhythm.SIGNED if signed is not None else day_rhythm.EVENING
            shown = computed
        else:
            computed = day_rhythm.shape_of(
                d,
                now,
                signed=signed is not None,
                first_stay=day_rhythm.first_stay(data, tz),
                evening=hour,
                today=today,
            )
            shown = day_rhythm.asked(shape) or computed
        live = d == today and not self.static  # today's clock, and its now line

        def link(text: str, path: str) -> str:
            return self.link(escape(text), path)

        def person(c: Mapping[str, Any]) -> str:
            name = escape(str(c.get("name") or ""))
            href = self.href(_person_path(str(c["person"]))) if c.get("person") else None
            if href is None:
                return f'<span class="person">{name}</span>'
            return f'<a class="person" href="{escape(href)}">{name}</a>'

        pieces: dict[str, str] = {}
        company = day_reader.company_of_day(data)
        brow = day_rhythm.eyebrow(data["weekday"], shown, now if live else None, signed, day)
        pieces["header"] = (
            self._day_header(day, data, star, extras, expanded, company, shown, computed)
            .replace("<!--eyebrow-->", f'<p class="eyebrow">{escape(brow)}</p>\n')
            .replace("<!--meta-->", day_rhythm.meta_line(data, company, person))
        )
        shelf = self._day_reading(("goals", day), lambda: shelf_goals.read(self.lb, self.tiers, today=day))
        pieces["for"] = day_rhythm.for_html(shelf, day_rhythm.touched(shelf, marks.lines), link)
        pieces["tiers"] = f'<p class="tiers">{escape(TIERS_SAID)}</p>\n'
        near = (  # a static site's days keep to their rows: no promise read for each day exported
            []
            if self.static
            else self._day_reading(
                ("promises", day), lambda: day_rhythm.promises_near(self.lb, day, self.tiers)
            )
        )
        span = bounds.span(d)
        morning = shown == day_rhythm.MORNING
        empty_ahead: list[str] = []  # the morning's parts with nothing, named in Nothing from
        # the morning's plan from the task tool, tier 1 alone as `show plan` reads it: every `sync notion`
        # line, seconds on a record of millions, so beside the page on `logbook serve` (`_day_later`)
        plan = self._day_plan(day) if not self.static and morning else None
        ticks = day_rhythm.task_ticks(plan, tz)
        ribbon = day_rhythm.ribbon(data, marks.lines, span, now if live else None, ticks)
        pieces["the-day"] = ribbon
        pieces["so-far"] = ribbon
        directory = self._day_reading(("directory",), lambda: people.directory(self.lb))
        if morning:
            entries = day_rhythm.planned(data, marks.lines)
            due = day_rhythm.due_on(near, day)
            today_parts = [ribbon + day_rhythm.today_html(entries, due, day, tz, person)]
            if plan is not None:
                said, body = day_rhythm.tasks_html(plan, tz, link)
                if body:
                    today_parts.append(day_rhythm.fold(day_rhythm.TASKS, said, body, True))
                else:
                    empty_ahead.append(day_rhythm.TASKS.lower())
            who = day_rhythm.seeing(entries, marks.lines, directory, self.tiers)
            if who:
                body = '<p class="seeing">' + ", ".join(person(w) for w in who) + "</p>\n"
                said = "from the calendar"  # the names inside, and no count
                today_parts.append(day_rhythm.fold(day_rhythm.SEEING, said, body, True))
            else:
                empty_ahead.append(day_rhythm.SEEING.lower())
            if self.with_drafts:  # a model's proposal (pencil): none on a site built without drafts (#364)
                proposal = self._day_reading(
                    ("proposal", day), lambda: day_rhythm.week_proposal(self.lb, day, self.tiers)
                )
                if proposal is not None:
                    today_parts.append(day_rhythm.proposal_html(proposal, link))
                else:
                    empty_ahead.append(day_rhythm.PROPOSAL)
            pieces["today"] = "".join(today_parts)
            found = self._day_reading(
                ("yesterday", day), lambda: day_rhythm.yesterday(self.lb, day, self.tiers)
            )
            pieces["yesterday"] = day_rhythm.yesterday_html(
                found, link, lambda y: self.link("Sign again", f"/day/{y}#{CLOSE}")
            )
        coming = day_rhythm.birthdays(directory, day, day_rhythm.WEEK, self.tiers)
        this_week = [b for b in coming if (b.on - d).days < day_rhythm.WEEK]
        if this_week:
            said = day_rhythm.birthday_said(this_week[0], day, person)
            pieces["one-person"] = f'<div class="card"><p class="ink">{said}</p></div>\n'
        elif morning and d == today and not self.static:  # one reconnect, the birthday's morning aside
            drifted = self._day_later(("drift", day), lambda: day_rhythm.drifted(self.lb, day, self.airports))
            pick = None if drifted is None else day_rhythm.reconnect(drifted, day, self.tiers)
            if pick is not None:
                said = day_rhythm.reconnect_said(pick, day, person)
                pieces["one-person"] = f'<div class="card"><p class="ink">{said}</p></div>\n'
            elif drifted is not None:
                empty_ahead.append("one person")
        # the morning's replies owed and decisions to revisit, read beyond the day, so beside the page on
        # `logbook serve` (`_day_later`), by the head a sync moves; never a site's (a site has no morning)
        owed: Sequence[Mapping[str, Any]] | None = None
        revisit: Sequence[Mapping[str, Any]] | None = None
        if not self.static and morning:
            head = str(self.lb.meta.get("head"))
            owed = self._day_later(
                ("owed", day, head), lambda: day_rhythm.replies_owed(self.lb, day, directory, self.tiers)
            )
            revisit = self._day_later(
                ("revisit", day, head), lambda: day_rhythm.revisits(self.lb, day, self.tiers)
            )
        if data.get("reflection"):  # the owner's words, in ink
            pieces["words"] = _reflection_html(data["reflection"], tz)
        pencil = ""  # a model's words: none on a site built without its drafts (`with_drafts`, #364)
        if self.with_drafts and data.get("draft"):
            model = escape(day_rhythm.model_of(data["draft"]))
            pencil = (
                f'<div class="paper" id="{PENCIL}">'
                f'<p class="eyebrow">Pencil <span class="sc">{model}</span></p>\n'
                f"{_draft_html(data['draft'], star)}</div>\n"
            )
        if self.with_drafts and data.get("draft_withheld"):  # the policy no longer allows it: the row
            pencil += _withheld_html(data["draft_withheld"], heading=not data.get("draft"))
        folds, empty = self._day_folds(
            day, data, marks, star, extras, expanded, tz, near, shown, link, person, coming, owed, revisit
        )
        empty[:0] = empty_ahead
        proposed = (data.get("draft") or {}).get("proposals") or ()
        confirmed = sum(1 for p in proposed if p.get("confirmed"))
        if pencil and shown in (
            day_rhythm.SIGNED,
            day_rhythm.MORNING,
        ):  # folded: at the foot, or in the record
            said = f"{confirmed} of {len(proposed)} proposals confirmed" if proposed else "the model's draft"
            folds["pencil"] = day_rhythm.fold("Pencil", said, pencil, expanded)
            pieces["pencil"] = folds["pencil"] if shown == day_rhythm.SIGNED else ""
        elif pencil:
            pieces["pencil"] = pencil
        pieces["photos"] = self._photos_html(day, marks, expanded)
        if not pieces["photos"]:
            empty.append("photos")
        elif shown == day_rhythm.MORNING:  # the morning's record holds them, so Add to today follows it
            n = len(marks.photos)
            said = f"{n} photo{'s' if n != 1 else ''}"
            folds["photos"] = day_rhythm.fold("Photos", said, pieces.pop("photos"), expanded)
        week = self._week_html(day, expanded) if self.with_drafts else ""
        pieces["record"] = week + "".join(folds[name] for name in day_rhythm.FOLDS[shown] if folds.get(name))
        pieces["nothing-from"] = day_rhythm.nothing_from(empty)
        asked_at = f" Your question comes at {hour:02d}:00." if hour is not None else ""
        reflect_now = f'<a href="#{CLOSE}">reflect now</a>'
        quiet = not pencil and self.with_drafts and not self.static  # a page that could hold a pencil
        pieces["quiet"] = f'<p class="quiet">No pencil yet.{asked_at} {reflect_now}</p>\n' if quiet else ""
        script = None
        if not self.static:
            closing, records = self._close_html(day, day_rhythm.CLOSE_HEADING[shown], shown)
            pieces["add" if shown in (day_rhythm.MORNING, day_rhythm.LIVE) else "close"] = closing
            script = DAY_SCRIPT if records else None
        pieces["foot"] = f'<p class="foot">{escape(day_rhythm.FOOTER)}</p>\n'
        parts = [
            day_rhythm.part(name, pieces[name], day_rhythm.HEADINGS.get((shown, name)))
            for name in day_rhythm.ORDER[shown]
            if pieces.get(name)
        ]
        self._day_later_start()  # what the page asked to read beside it, once it is rendered
        return self.document(
            f"{day} {data['weekday']}", "".join(parts), script, NO_MODEL, DAY_STYLE + day_rhythm.STYLE
        )

    def _day_header(
        self,
        day: str,
        data: Mapping[str, Any],
        star: Toggle,
        extras: Rows,
        expanded: bool,
        company: Sequence[Mapping[str, Any]],
        shown: str,
        computed: str,
    ) -> str:
        """The Day's header: the eyebrow and the meta line (`<!--eyebrow-->`, `<!--meta-->`, put in
        by `page_day`), the date, the note of a shape shown for reading, the pager, then the night
        before and after, the country, the signature, the day's all-day entries and the `with` row."""
        d = date.fromisoformat(day)
        before, after = (d - timedelta(days=1)).isoformat(), (d + timedelta(days=1)).isoformat()
        a, b = (d - timedelta(days=6)).isoformat(), (d + timedelta(days=7)).isoformat()
        toggle = (  # a static page has no other state to toggle to
            ""
            if self.static
            else (
                self.link("collapse all", f"/day/{day}")
                if expanded
                else self.link("expand all", f"/day/{day}?open=1")
            )
            + DOT
        )
        held = f"{DOT}{chapter.header_text(data['chapter'])}" if data.get("chapter") else ""  # RFC 0036
        close = "" if self.static else f'<a href="/day/{day}#{CLOSE}">reflect and sign</a>{DOT}'
        asked = ""
        if shown != computed:
            own = self.link("its own", f"/day/{day}")
            asked = (
                f'<p class="asked">The {shown} shape, shown for reading; the day is in its {computed} '
                f"now ({own}).</p>\n"
            )
        parts = [
            "<!--eyebrow-->",
            asked,
            f"<h1>{day} <small>{escape(data['weekday'] + held)}</small></h1>\n",
            "<!--meta-->",
            f'<p class="pager">{self.link(f"← {before}", f"/day/{before}")}{DOT}'
            f"{self.link('the fortnight around', f'/days?from={a}&to={b}')}{DOT}"
            f"{week + DOT if (week := week_page.link_html(self, day)) else ''}{toggle}{close}"
            f"{self.link(f'{after} →', f'/day/{after}')}</p>\n",
            "" if self.static or data["sources"] else self._nothing_held(day),
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
            entries = ", ".join(
                escape(a["title"] + day_reader.sources_text(a))
                + star([a["line"], *a["lines"]], False)
                + extras.raw([a["line"]])
                for a in data["all_day"]
            )
            parts.append(f"<dt>all day</dt><dd>{entries}</dd>\n")
        if company or not self.static:  # the "with" row: who was there, and the field to say so
            proposed = any((e.get("with") or {}).get("proposed") for e in data["timeline"])
            nobody = (
                NONE_CONFIRMED
                if proposed  # a row below proposes who: the header says nobody is confirmed, not seen
                else NO_DEVICE_WITH
                if self._unseen(day, data)
                else "nobody the record saw"
            )
            said = (
                escape(day_reader.company_text(company))
                if company
                else f'<span class="mute">{escape(nobody)}</span>'
            )
            field = "" if self.static else self._with_form(day)
            parts.append(f'<dt id="with">with</dt><dd>{said}{field}</dd>\n')
        parts.append("</dl>\n")
        return "".join(parts)

    def _day_folds(
        self,
        day: str,
        data: Mapping[str, Any],
        marks: DayMarks,
        star: Toggle,
        extras: Rows,
        expanded: bool,
        tz: ZoneInfo,
        near: Sequence[Any],
        shown: str,
        link: Callable[[str, str], str],
        person: Callable[[Mapping[str, Any]], str],
        coming: Sequence[day_rhythm.Birthday],
        owed: Sequence[Mapping[str, Any]] | None = None,
        revisit: Sequence[Mapping[str, Any]] | None = None,
    ) -> tuple[dict[str, str], list[str]]:
        """The record's folds by name, each with its summary in counts, and the names of the parts
        with nothing for the day (`day_rhythm.nothing_from`). `owed` and `revisit` are None where the
        page does not read them (a site, a day not today), so not named as empty."""
        folds: dict[str, str] = {}
        empty: list[str] = []
        fold = day_rhythm.fold

        # the call syntheses' decisions are a model's (pencil): none without drafts (`with_drafts`)
        said_by_calls = data if self.with_drafts else {**data, "syntheses": []}
        summary, body = day_rhythm.loose_ends(
            near, said_by_calls, day, tz, person, owed or (), revisit or (), link
        )
        if body:
            folds["loose-ends"] = fold("Loose ends", summary, body, expanded)
        elif not self.static:  # a static day reads no promise: it cannot say there were none
            empty.append("loose ends")
        if owed is not None and not owed:
            empty.append("replies owed")
        if revisit is not None and not revisit:
            empty.append("decisions to revisit")
        who = day_rhythm.people_of_day(data, marks.lines)
        rows = [
            f'<li><span>{person(p)}<span class="sub">'
            + escape(DOT.join([*(f"at {w}" for w in p["where"][:3]), *(["you said"] if p["stated"] else [])]))
            + "</span></span></li>\n"
            for p in who
        ]
        if coming:
            rows.append(
                '<li class="birthdays"><span>Birthdays: '
                + " ".join(day_rhythm.birthday_said(b, day, person) for b in coming)
                + "</span></li>\n"
            )
        if rows:
            said = DOT.join(
                x
                for x in (
                    f"{len(who)} {'person' if len(who) == 1 else 'people'}" if who else "",
                    f"{len(coming)} {'birthday' if len(coming) == 1 else 'birthdays'}" if coming else "",
                )
                if x
            )
            folds["people"] = fold(
                "People", said, '<ul class="rows">\n' + "".join(rows) + "</ul>\n", expanded
            )
        else:
            empty.append("people")
        reviews = _owner_html({**data, "goals": [], "chapters": []}, star, extras.raw)
        if reviews:
            n = len(data.get("reviews") or ())
            folds["reviews"] = fold(
                "Reviews",
                f"{n} review{'s' if n != 1 else ''}",
                reviews.removeprefix("<h2>Reviews</h2>\n"),
                expanded,
            )
        written = _owner_html({**data, "reviews": []}, star, extras.raw)
        if written:
            n = len(data.get("goals") or ()) + len(data.get("chapters") or ())
            folds["goals"] = fold(
                "Goals and chapters",
                f"{n} line{'s' if n != 1 else ''}",
                written.removeprefix("<h2>Goals and chapters</h2>\n"),
                expanded,
            )
        # a call's synthesis, or the policy's row, under the call: none without drafts (`with_drafts`)
        syntheses = day_reader.syntheses_of(data) if self.with_drafts else {}
        if data["timeline"]:
            name_this = None if self.static else self._name_this
            body = _track_svg(data["timeline"]) + '<ol class="timeline">\n'
            body += "".join(
                _entry_html(
                    entry,
                    tz,
                    expanded=expanded,
                    name_this=name_this,
                    syntheses=syntheses,
                    star=star,
                    photos=marks.photos,
                    rows=extras,
                )
                for entry in data["timeline"]
            )
            body += "</ol>\n"
            folds["timeline"] = fold(
                "Timeline", day_rhythm.timeline_summary(data, marks.photos), body, expanded
            )
        else:
            folds["timeline"] = fold(
                "Timeline", "nothing logged", '<p class="mute">nothing logged</p>\n', expanded
            )
        in_rows = [((e.get("attached") or {}).get("photos") or {}).get("lines", ()) for e in data["timeline"]]
        outside = [i for i in marks.photos if not any(i in ids for ids in in_rows)]  # in no row
        if outside:
            folds["outside"] = fold(
                "Photos outside any stay",
                f"{len(outside)} photo{'s' if len(outside) != 1 else ''}",
                f'<div class="outside">{extras.strip(outside)}</div>\n',
                expanded,
            )
        if data["unplaced"]:
            body = '<ul class="unplaced">\n'
            for item in _drive_folded(data["unplaced"], marks.lines, "at"):
                span = day_reader.span_text(item["at"], item["end"], tz)
                blocks = syntheses.get(item["line"], []) if item["kind"] == "transcript" else []
                body += (
                    f'<li id="{_row_id(item["line"])}" title="line {escape(item["line"])}">'
                    f'<span class="clock">{escape(span)}</span> '
                    f'<span class="kind">{escape(item["kind"])}</span> '
                    f"{escape(item['title'] + day_reader.sources_text(item) + day_reader.voices_text(item))}"
                    f"{star([item['line'], *item.get('lines', ())], False)}{extras.raw([item['line']])}"
                    f"{''.join(_synthesis_html(block, expanded) for block in blocks)}</li>\n"
                )
            body += "</ul>\n"
            n = len(data["unplaced"])
            folds["unplaced"] = fold("Unplaced", f"{n} line{'s' if n != 1 else ''}", body, expanded)
        found = (  # a static site's days keep to their rows: no year read again for each day exported
            None
            if self.static
            else self._day_reading(
                ("looking back", day),
                lambda: day_rhythm.looking_back(self.lb, day, self.airports, self.tiers),
            )
        )
        summary, body = day_rhythm.looking_back_html(found or [], link, person, revisit or (), day)
        if body:
            folds["looking-back"] = fold("Looking back", summary, body, expanded)
        elif found is not None:
            empty.append("looking back")
        if data["health"]:
            text = day_reader.health_text(data["health"])
            folds["health"] = fold("Health", text, f"<p>{escape(text)}</p>\n", expanded)
        else:
            empty.append("health")
        if data.get("weather"):
            text = weather.text(data["weather"], data["tz"])
            folds["weather"] = fold(
                "Weather", weather.short_text(data["weather"]), f"<p>{escape(text)}</p>\n", expanded
            )
        else:
            empty.append("weather")
        circle = []
        for page in data.get("received") or []:  # a page someone shared for the day (RFC 0025)
            body = f"<p>{escape(day_reader.received_text(page))}</p>\n"
            if page["named"]:
                body += '<ul class="unplaced">\n'
                for item in page["named"]:
                    line, kind, title = escape(item["line"]), escape(item["kind"]), escape(item["title"])
                    body += f'<li title="line {line}"><span class="kind">{kind}</span> {title}</li>\n'
                body += "</ul>\n"
            n = len(page["named"])
            circle.append(fold(f"From {page['from']}", f"{n} line{'s' if n != 1 else ''}", body, expanded))
        if circle:
            folds["circle"] = "".join(circle)
        else:
            empty.append("the circle")
        held = (
            data
            if self.with_drafts
            else {**data, "held": [r for r in data.get("held") or () if not _drafted(r)]}
        )
        folds["held"] = _held_html(held, tz, extras.raw, expanded)
        sources = [s for s in data["sources"] if self.with_drafts or not _drafted(s)]  # a model's row: #364
        if sources:
            rows_: list[list[Cell]] = [
                [
                    escape(s["source"]),
                    _num(s["lines"]),
                    escape(_clock(s["first"], tz)),
                    escape(_clock(s["newest"], tz)),
                ]
                for s in sources
            ]
            total = sum(int(s["lines"]) for s in sources)
            said = f"{len(sources)} source{'s' if len(sources) != 1 else ''}{DOT}{total:,} lines"
            folds["sources"] = fold(
                "Sources", said, _table(["source", ("lines", "num"), "first", "last"], rows_), expanded
            )
        else:  # the record's spine, as the timeline is: drawn on every day, a day with no line says so
            folds["sources"] = fold("Sources", "none", '<p class="mute">none</p>\n', expanded)
        return folds, empty

    def _photos_html(self, day: str, marks: DayMarks, expanded: bool) -> str:
        """The day's photos: how many and how many starred, the starred ones this machine holds the
        pixels of, then the review of the rest (`_photo_review_html`); nothing on a day with none."""
        if not marks.photos:
            return ""
        starred = [i for i in marks.photos if i in marks.starred]
        shown = [(i, self._thumbnail(i, marks)) for i in starred]
        drawn = [(i, img) for i, img in shown if img]
        n, k = len(marks.photos), len(starred)
        said = f"{n} photo{'s' if n != 1 else ''}" + (f"{DOT}{k} starred" if k else "")
        if len(drawn) < k:
            said += f"{DOT}{k - len(drawn)} starred not on this machine"
        out = [f'<p class="mute">{escape(said)}</p>\n']
        if drawn:
            out.append('<ul class="gallery">\n')
            out.extend(f'<li class="starred">{img}</li>\n' for _i, img in drawn)
            out.append("</ul>\n")
        if not self.static:
            out.append(self._photo_review_html(day, marks))
        return "".join(out)

    def _close_html(
        self, day: str, heading: str = "Reflect and sign", shape: str | None = None
    ) -> tuple[str, bool]:
        """Reflect and sign, at the foot of the Day: the reflection's field (the Wispr Flow draft
        prefilled when one is waiting, else the reflection standing), the recording form when the
        server can hear one, then the standing signature as `day sign` prints it, and the Sign form:
        the proposals as boxes, none ticked. In the evening and signed shapes (`shape`) the form is
        Keep and sign (`_keep_html`), and today's evening opens with *Dream the day so far*, or the
        sentence that says how to allow it (`_dream_html`). Nothing here is written until a button is
        clicked. With it, whether the page carries the recording form (and so its script)."""
        tz = self.tz
        out = [f'<section class="close">\n<h2 id="{CLOSE}">{escape(heading)}</h2>\n']
        try:
            day, today = self._closing_day(day)
        except reflect.ReflectError:
            out.append(
                f'<p class="mute">{day} is ahead of today in {escape(str(tz))}; a day is reflected on and'
                " signed on it or after it</p>\n</section>\n"
            )
            return "".join(out), False
        keeping = shape in (day_rhythm.EVENING, day_rhythm.SIGNED)
        if shape == day_rhythm.EVENING and day == today:
            out.append(self._dream_html(day))
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
        out.append(self._sign_html(day, found, r.note, keeping))
        out.append("</section>\n")
        return "".join(out), records

    def _sign_html(self, day: str, found: Closing, note: Line, keeping: bool = False) -> str:
        """The Sign form: with `keeping`, Keep and sign's controls first (`_keep_html`), then the
        proposals, a box each as `day reflect` numbers them (rules alone, none ticked: a guess until
        the owner accepts it), the reflection a sentence a line folded beside them, what signing
        confirms or keeps, and the button."""
        r = found.reflection
        assert r is not None
        out = [
            f'<form class="sign" method="post" action="/day/{day}/sign">\n'
            f'<input type="hidden" name="reflection" value="{escape(str(note["id"]))}">\n'
            f'<input type="hidden" name="proposals" value="{escape(found.digest)}">\n'
        ]
        if keeping:
            out.append(self._keep_html(day, found))
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
        if keeping:
            out.append(
                '<p class="mute">The same at the command line: <code>logbook day reflect'
                f" {day} --sign --keep N,N --revisit N=YYYY-MM-DD --word WORD --done T,T --tomorrow T,T"
                " --let-go T,T --accept N,N</code>; or <code>logbook day sign"
                f" {day}</code> with the same flags but <code>--accept</code>.</p>\n"
            )
        out.append(f'<button name="act" value="{SIGN}">{button}</button>\n</form>\n')
        return "".join(out)

    def _keep_html(self, day: str, found: Closing) -> str:
        """Keep and sign's controls (RFC 0043 §5), in the order they are written: the pencil's
        keepable sentences and links, a box each numbered as `--keep` takes them (`found.pencil`, read
        as `keep` reads it), the sentence in pencil until kept and in ink once it is, a kept decision's
        revisit day beside its box; the day in a word, one field, or the word standing; then today's
        tasks (`_tasks_html`). The hidden `draft` says which pencil the page showed."""
        pencil = found.pencil
        shown = "" if pencil is None else str(pencil["line"])
        out = [f'<input type="hidden" name="draft" value="{escape(shown)}">\n']
        items: list[str] = []
        if pencil is not None:
            keepable: list[tuple[int, str, Mapping[str, Any]]] = [
                (int(segment["keep"]), str(segment["part"]), segment)
                for segment in pencil["segments"]
                if segment.get("keep") is not None
            ]
            keepable += [(int(link["keep"]), drafts.LINK, link) for link in pencil.get("links") or []]
            for n, part, block in sorted(keepable, key=lambda item: item[0]):
                if block.get("kept") or block.get("supported"):
                    items.append(_keep_item(day, n, part, block))
        out.append('<fieldset class="keep">\n<legend>Keep from the pencil</legend>\n')
        if items:
            out.append('<ol class="keep">\n' + "".join(items) + "</ol>\n")
        else:
            nothing = "nothing in it to keep" if pencil is not None else "no pencil on the day to keep from"
            out.append(f'<p class="mute">{nothing}</p>\n')
        out.append("</fieldset>\n")
        out.append('<fieldset class="keep">\n<legend>The day in a word</legend>\n')
        if found.word is not None:
            said = escape(str((found.word.get("payload") or {}).get("text") or ""))
            out.append(
                f'<p><span class="ink">“{said}”</span> <small class="mute">kept as'
                f" #{found.word['seq']}; a re-sign keeps it</small></p>\n"
            )
        else:
            out.append(
                '<input type="text" name="word" maxlength="60" autocomplete="off" spellcheck="true"'
                ' aria-label="the day in a word" placeholder="one word, or leave it empty">\n'
            )
        out.append("</fieldset>\n")
        out.append(self._tasks_html(day))
        return "".join(out)

    def _day_plan(self, day: str) -> object:
        """The task tool's plan for `day` as `show plan` reads it (tier 1 alone), beside the page on
        `logbook serve` (`_day_later`): a `Plan`, the mapping's error in a sentence, None while it is
        read, or when the page's gate holds no tier 1."""
        if self.tiers is not None and 1 not in self.tiers:
            return None
        return self._day_later(
            ("plan", day, str(self.lb.meta.get("head"))), lambda: day_rhythm.plan_of(self.lb, day)
        )

    def _tasks_html(self, day: str) -> str:
        """Today's tasks answered (RFC 0043 §9): each numbered as `show plan` numbers it, with three
        choices, done, tomorrow and let go, none chosen; a task answered already says how, and offers
        none. Nothing but the hidden `tasks`, the tasks the page showed, when the record maps no
        tasks database."""
        found = self._day_plan(day)
        hidden = f'<input type="hidden" name="tasks" value="{escape(_tasks_digest(found))}">\n'
        if isinstance(found, str):
            body = f'<p class="mute">{escape(found)}</p>\n'
        elif found is None:
            body = (
                '<p class="mute">the tasks of the day are being read beside the page; reload to answer</p>\n'
            )
        elif not isinstance(found, plan_reader.Plan) or not found.mapped or not found.tasks:
            return hidden
        elif not found.tasks["rows"]:
            body = '<p class="mute">no task for the day</p>\n'
        else:
            rows = []
            for row in found.tasks["rows"]:
                title = escape(str(row.get("title") or plan_reader.UNTITLED))
                answered = row.get("answered")
                if answered:
                    said = plan_reader.ANSWERED[answered["outcome"]]
                    rows.append(
                        f'<li class="task kept"><span class="words">{title}</span>'
                        f' <small class="mute">{escape(said)}, #{answered["seq"]}</small></li>\n'
                    )
                    continue
                n = int(row["number"])
                choices = "".join(
                    f'<label><input type="radio" name="{TASK}{n}" value="{outcome}"> {words}</label>'
                    for outcome, words in (
                        (plan_reader.DONE_TODAY, "done"),
                        (plan_reader.TOMORROW, "tomorrow"),
                        (plan_reader.LET_GO, "let go"),
                    )
                )
                rows.append(
                    f'<li class="task"><span class="head">task {n}</span> <span class="words">{title}</span>'
                    f'<span class="answers">{choices}</span></li>\n'
                )
            body = '<ol class="keep">\n' + "".join(rows) + "</ol>\n"
        return f'{hidden}<fieldset class="keep">\n<legend>The tasks of the day</legend>\n{body}</fieldset>\n'

    def _dream_html(self, day: str) -> str:
        """Today's evening, before the close: *Dream the day so far* (`_dream`), only when the owner's
        `dream` entry stands; else the one sentence that says how to allow it, and no button, since
        nothing of the day is sent without the entry."""
        name = policy.POLICY_FILE.as_posix()
        try:
            entry = policy.dream_today(self.lb.root)
        except policy.PolicyError as e:
            return f'<p class="mute dream">{escape(str(e))}</p>\n'
        if entry is None:
            return (
                f'<p class="mute dream">No <code>"dream"</code> entry in <code>{name}</code>, so nothing of'
                " the day is sent to a model: add"
                ' <code>"dream": {"max_tier": 2, "until": "YYYY-MM-DD"}</code>'
                f" to dream the day so far here, as <code>logbook dream day {day} --evening</code>"
                " does.</p>\n"
            )
        if entry.expired:
            until = entry.until.isoformat() if entry.until is not None else "its until"
            return (
                f'<p class="mute dream">The <code>"dream"</code> entry expired on {until}, so nothing of'
                f" the day is sent: give it a new <code>until</code> in <code>{name}</code> to dream the"
                " day so far here.</p>\n"
            )
        to = f"the model {escape(entry.model)}" if entry.model else "the model your endpoint names"
        return (
            f'<form class="dream" method="post" action="/day/{day}/reflect">\n'
            f'<button name="act" value="{DREAM}">Dream the day so far</button>\n'
            f'<p class="mute">Sends today so far, up to tier {entry.max_tier}, to {to}, as <code>logbook'
            f" dream day {day} --evening</code> does; its draft comes back in pencil above, and nothing"
            " of it is kept until you keep it.</p>\n</form>\n"
        )

    def _day_marks(self, day: str) -> DayMarks:
        """What the Day page reads of the day's lines besides the Day, through the gate `tiers`: the
        stars standing on them, a photo's `memory` keeper among them, by the line each marks, each
        beside a line the page reads and never a model's draft (`stars.shown`); the day's photos
        standing, id → name; and the day's lines standing, by id (a row's link to its line, the
        Drive folds, the photos' pixels)."""
        with self.lb.index() as idx:
            lines = reading.crossing(idx.day(day), self.tiers)
            retracted = retractions(idx.retractions())
        marks = [line for line in lines if line.get("kind") in (stars.KIND, keepers.KIND)]
        photos = {
            str(line["id"]): stars.title(line)
            for line in lines
            if line.get("kind") == stars.PHOTO and str(line["id"]) not in retracted
        }
        by_id = {str(line["id"]): line for line in lines}
        standing = {id_: line for id_, line in by_id.items() if id_ not in retracted}
        return DayMarks(stars.shown(stars.standing(marks, retracted), by_id), photos, standing, {})

    def _unseen(self, day: str, data: Mapping[str, Any]) -> bool:
        """Whether the Day says no device saw it (`NO_DEVICE_WITH`): a served day that has begun and
        holds no line at all, under the page's gate: the night the phones were off."""
        if self.static or data["sources"]:
            return False
        try:
            return date.fromisoformat(day) <= day_start.of(self.lb.meta).today(self.now())
        except day_start.DayStartError:
            return False

    def _raw(self, marks: DayMarks) -> Callable[[Sequence[str]], str]:
        """The link of a row that is a line to the line as written (`/line/ID`), `#SEQ`: the first of
        `ids` the page reads. Nothing on a static page, which has no such page. Each link is made once
        a page: a message is linked under its row and again in "Everything this day held"."""
        made: dict[str, str] = {}

        def raw(ids: Sequence[str]) -> str:
            line = next((marks.lines[i] for i in ids if i in marks.lines), None)
            if line is None:
                return ""
            id_ = str(line["id"])
            if id_ in made:
                return made[id_]
            href = self.href(f"/line/{quote(id_, safe='')}")
            seq = int(line["seq"])
            link = (
                ""
                if href is None
                else f' <a class="raw" href="{escape(href)}" title="the line as written">#{seq}</a>'
            )
            made[id_] = link
            return link

        return raw

    def _thumbnail(self, line_id: str, marks: DayMarks) -> str | None:
        """The `<img>` of a photo whose pixels the store holds and a browser draws (`day_photos.stored`),
        from the server's own `/photo/ID`; None for any other, and always on a static page."""
        line = marks.lines.get(line_id)
        if line is None or self.static:
            return None
        if line_id not in marks.drawn:  # once a render: a sealed photo is opened to be judged
            marks.drawn[line_id] = day_photos.stored(self.lb, line) is not None
        if not marks.drawn[line_id]:
            return None
        href = self.href(f"/photo/{quote(line_id, safe='')}")
        if href is None:
            return None
        name = escape(marks.photos.get(line_id) or "a photo")
        return f'<img src="{escape(href)}" alt="{name}" loading="lazy">'

    def _strip(self, day: str, marks: DayMarks, expanded: bool) -> Callable[[Sequence[str]], str]:
        """A row's photos as a strip under it, starred first (RFC 0041): a thumbnail for each the store
        holds, the starred ones it does not by name, and the rest counted, never a broken image. Its
        star on each, and its link to its line. Nothing on a static page, whose rows name the photos."""
        star = self._toggle(day, marks.starred, expanded)
        raw = self._raw(marks)

        def strip(ids: Sequence[str]) -> str:
            ids = day_photos.starred_first([i for i in ids if i in marks.photos], marks.starred)
            if self.static or not ids:
                return ""
            items, missing = [], 0
            for id_ in ids:
                image = self._thumbnail(id_, marks)
                if image is None:
                    missing += 1
                    if id_ not in marks.starred:
                        continue
                    image = f'<span class="name">{escape(marks.photos[id_])}</span>'
                items.append(f'<li id="{_row_id(id_)}-strip">{image}{star([id_], False)}{raw([id_])}</li>')
            if missing:
                items.append(f'<li class="mute">{_plural(missing, "photo")} not on this machine</li>')
            return f'\n<ul class="strip" aria-label="the photos">{"".join(items)}</ul>'

        return strip

    def _photo_review_html(self, day: str, marks: DayMarks) -> str:
        """The photo review at the foot of the Day: the day's photos with no star standing that the
        owner has not passed over (`day_photos.passed`), a thumbnail each when the store holds it,
        else the name; for each, Star (`stars.star`, a `memory` keeper) and Not a keeper (`PASS`,
        `day_photos.pass_over`, no line), both posting to `STAR_PATH`, so another command writing is
        the Library's one answer (`_busy`). Nothing on a day with no photo left to review."""
        passed = day_photos.passed(self.lb.root)
        waiting = [i for i in marks.photos if i not in marks.starred and i not in passed]
        if not waiting:
            return ""
        out = [
            f'<section class="review">\n<h2 id="{PHOTOS}">Photo review</h2>\n'
            f'<p class="mute">{_plural(len(waiting), "photo")} of the day not starred: Star makes one the'
            " day's hero and the press's pick; Not a keeper stops asking, and writes no line.</p>\n"
            '<ul class="review">\n'
        ]
        for id_ in waiting:
            image = self._thumbnail(id_, marks) or f'<span class="name">{escape(marks.photos[id_])}</span>'
            fields = (
                f'<input type="hidden" name="day" value="{day}">'
                f'<input type="hidden" name="line" value="{escape(id_)}">'
                f'<input type="hidden" name="from" value="{PHOTOS}">'
            )
            out.append(
                f"<li>{image}"
                f'<form class="keep" method="post" action="{STAR_PATH}">{fields}'
                '<button name="act" value="star">Star</button></form>'
                f'<form class="keep" method="post" action="{STAR_PATH}">{fields}'
                f'<button name="act" value="{PASS}">Not a keeper</button></form></li>\n'
            )
        out.append("</ul>\n</section>\n")
        return "".join(out)

    def _week_html(self, day: str, expanded: bool) -> str:
        """The week a day is in (`dream week`, RFC 0036 unit `week`): on its Sunday, its last day, the
        standing draft folded under its head, or the row that says the `dream` entry withholds it; on
        the six days before, a line linking to it. Through the gate `tiers`, as every draft on the
        page (`drafts.for_unit`): a draft above it is not there, so neither is the link. Nothing for a
        week with no draft."""
        week, monday, sunday = week_paper.parse_week(week_paper.week_of(day))
        with self.lb.index() as idx:
            retracted = frozenset(retractions(idx.retractions()))
            found = drafts.by_unit(idx.by_kind(drafts.KIND), retracted, drafts.UNIT_WEEK).get(week, [])
            if not found:
                return ""
            on_week = {
                str(line["id"])
                for d in day_range(monday, sunday)
                for line in idx.day(d)
                if str(line["id"]) not in retracted
            }
        draft, withheld = drafts.for_unit(
            found, on_week, self.tiers, drafts.allowed(self.lb.root), drafts.NOT_ON_WEEK
        )
        if draft is None and withheld is None:
            return ""
        if day != sunday:
            href = self.href(f"/day/{sunday}")  # a static site maps the page, not its anchor
            said = escape(f"on its Sunday, {sunday}")
            link = said if href is None else f'<a href="{escape(href)}#{WEEK}">{said}</a>'
            return f'<p class="mute week">The week {escape(week)} has a draft: {link}.</p>\n'
        out = [f'<h2 id="{WEEK}">The week {escape(week)}</h2>\n']
        if page := week_page.link_html(self, day):
            out.append(f'<p class="mute">{page}: its ribbons, goals and proposal</p>\n')
        if draft is not None:
            href = self.href(f"/line/{quote(str(draft['line']), safe='')}")
            if href is not None:
                out.append(f'<p class="mute"><a href="{escape(href)}">the draft as written</a></p>\n')
            folded = _draft_folded(draft)
            out.append(folded.replace("<details", "<details open", 1) if expanded else folded)
            rows = list(drafts.extra_rows(draft, ""))
            if rows:
                out.append(
                    '<ul class="plain week">' + "".join(f"<li>{escape(r)}</li>" for r in rows) + "</ul>\n"
                )
        if withheld is not None:
            out.append(_withheld_html(withheld, heading=False))
        return "".join(out)

    def _toggle(self, day: str, starred: Mapping[str, stars.Star], expanded: bool) -> Toggle:
        """The star of a row whose lines are `ids`: a form that posts to `STAR_PATH`, ★ to unstar
        the line starred among them, else ☆ to star the first; a keeper's row (`only_on`) carries
        one only while it is a star. A static page shows ★ alone, and nothing for a line unstarred."""
        by_mark = {s.star: s for s in starred.values()}

        def toggle(ids: Sequence[str], only_on: bool) -> str:
            ids = [i for i in ids if i]
            on = next((starred.get(i) or by_mark.get(i) for i in ids if i in starred or i in by_mark), None)
            if not ids or (on is None and only_on):
                return ""
            said = f"starred: {on.note}" if on is not None and on.note else "starred"
            if self.static:
                return f' <span class="star on" title="{escape(said)}">{stars.SYMBOL}</span>' if on else ""
            target = on.line if on is not None else ids[0]
            act, symbol = ("unstar", stars.SYMBOL) if on is not None else ("star", "☆")
            title = f"{said}; unstar" if on is not None else "star this line"
            return (
                f'<form class="star" method="post" action="{STAR_PATH}">'
                f'<input type="hidden" name="day" value="{day}">'
                f'<input type="hidden" name="line" value="{escape(target)}">'
                + ('<input type="hidden" name="open" value="1">' if expanded else "")
                + f'<button name="act" value="{act}" aria-pressed="{"true" if on else "false"}"'
                f' title="{escape(title)}">{symbol}</button></form>'
            )

        return toggle

    def _with_form(self, day: str) -> str:
        """The "with…" field: names completed from the canonical people (a `datalist`, no script),
        a clock when the owner knows it, posting to `WITH_PATH`."""
        names = sorted({p.name for p in people.directory(self.lb).known.values()}, key=str.casefold)
        options = "".join(f'<option value="{escape(name)}">' for name in names)
        return (
            f'<form class="with" method="post" action="{WITH_PATH}">'
            f'<input type="hidden" name="day" value="{day}">'
            '<input type="text" name="names" list="people" placeholder="with…" autocomplete="off"'
            ' aria-label="who was there: a name, or several with commas">'
            '<input type="time" name="at" aria-label="the clock, if you know it">'
            f'<button>add</button></form><datalist id="people">{options}</datalist>'
        )

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
            return self.document(
                "days", "<h1>Days</h1>\n<p>no days: the record has no lines</p>\n", style=TABLES_STYLE
            )
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
        body += self._starred(first, last)
        return self.document(f"days {first} {EN_DASH} {last}", body, style=TABLES_STYLE)

    def _starred(self, first: str, last: str) -> str:
        """The window's stars (RFC 0041), a photo's among them, in the order of the lines they mark:
        the day and clock, the kind, what the line is called, linked to its row, and the note."""
        found = stars.listed(self.lb, first, last, self.tiers)
        if not found:
            return ""
        tz = self.tz
        out = ["<h2>Starred</h2>\n", '<ul class="starred">\n']
        for s in found:
            note = f"{DOT}{escape(s['note'])}" if s["note"] else ""
            out.append(
                f'<li><span class="clock">{escape(s["day"])} {_instant(s["at"]).astimezone(tz):%H:%M}</span> '
                f'<span class="kind">{escape(s["kind"])}</span> {stars.SYMBOL} '
                f"{self.link(escape(s['title']), f'/day/{s["day"]}#{_row_id(s["line"])}')}{note}</li>\n"
            )
        out.append("</ul>\n")
        return "".join(out)

    # -- /trips ---------------------------------------------------------------------------------------------

    def page_trips(self, year: str | None) -> str:
        whole = self._whole()
        if whole is None:
            return self.document(
                "trips", "<h1>Trips</h1>\n<p>no trips: the record has no days</p>\n", style=TABLES_STYLE
            )
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
            return self.document(f"trips {year}", "".join(parts), style=TABLES_STYLE)
        rd = self.shared(  # the door and its year's page are one reading
            ("trips", first, last),
            lambda: reading.read(self.lb, first, last, self.airports, self.tiers, TRIP_KINDS),
        )
        self.reads(first, (date.fromisoformat(last) + timedelta(days=SPILL_DAYS)).isoformat())
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
        return self.document(f"trips {year}", "".join(parts), style=TABLES_STYLE)

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
            return self.document("places", body, style=TABLES_STYLE)
        total = len(report.proposals)
        pages = max(1, math.ceil(total / PAGE_SIZE))
        n = min(int(page), pages)
        first = (n - 1) * PAGE_SIZE
        shown = report.proposals[first : first + PAGE_SIZE]
        body += f"<h2>Name this place <small>{escape(places_review.head(report))}</small></h2>\n"
        if not report.observed:
            body += "<p>no places observed: the record has no stays yet</p>\n"
            return self.document("places", body, style=TABLES_STYLE)
        if not shown:
            body += "<p>nothing to review: every place you return to is named</p>\n"
            return self.document("places", body, style=TABLES_STYLE)
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
        return self.document("places", body, PLACES_SCRIPT, style=TABLES_STYLE)

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
            out.append(_folded([escape(line, quote=False) for line in lines]))
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

    # -- /journeys ------------------------------------------------------------------------------------------

    def page_journeys(self, year: str | None) -> str:
        """The journeys that began in the year (default the record's last), the latest first, each
        a row: its name or dates linking its page, the bounds, the nights away, the places, the
        canonical people, the photos, the draft folded, and the evidence folded."""
        located = reading.record_days(self.lb, "location")
        this = year or (located[1][:4] if located is not None else None)  # the door is its year's page
        shelf = self.shared(
            ("journeys", this), lambda: journeys.shelf(self.lb, this, self.airports, self.tiers)
        )
        if shelf.reads is not None:  # its days, and a draft of any day may name one of its journeys
            self.reads(*shelf.reads, kinds=(drafts.KIND,))
        if shelf.year is None:
            return self.document("journeys", f"<h1>Journeys</h1>\n<p>{escape(shelf.warning or '')}</p>\n")
        links = DOT.join(
            f"<b>{y}</b>" if y == shelf.year else self.link(y, f"/journeys?year={y}") for y in shelf.years
        )
        parts = [f"<h1>Journeys <small>{shelf.year}</small></h1>\n", f'<p class="pager">{links}</p>\n']
        if shelf.warning:
            parts.append(f"<p>{escape(shelf.warning)}</p>\n")
        elif not shelf.journeys:
            parts.append(f"<p>no journeys began in {shelf.year}: every night was at home</p>\n")
        else:
            parts.append(
                '<p class="mute">The runs of nights away from home that began in this year, the latest'
                " first: derived from the nights every time, never written; a name is yours, written as"
                " a note on the journey's page or with <code>logbook add --trip</code>.</p>\n"
            )
            parts.append('<ol class="shelf">\n')
            parts.extend(self._journey_row(j) for j in shelf.journeys)
            parts.append("</ol>\n")
        return self.document(f"journeys {shelf.year}", "".join(parts))

    def _journey_row(self, j: journeys.Journey) -> str:
        t = j.trip
        dates = f"{t.start} {EN_DASH} {t.end}"
        title = escape(j.name.text) if j.name else _dates(dates)
        head = self.link(f"<b>{title}</b>", f"/journeys/{t.start}/{t.end}")
        facts = [journeys.nights_text(j.to_json()), f"home {t.until}"]
        if t.route:
            facts.append(f" {ARROW} ".join(trips.route_names(t.route)))
        facts.append(_plural(len(j.photos), "photo"))
        with_ = self._people_links(j.people, j.unplaced)
        out = [
            f'<li id="{escape(t.id.replace(":", "-"))}">\n<p class="head">{head}'
            + (f' <span class="mute">{_dates(dates)}</span>' if j.name else "")
            + "</p>\n",
            f'<p class="facts">{escape(DOT.join(facts))}</p>\n',
        ]
        if t.places:
            out.append(f'<p class="facts">places {escape(", ".join(t.places))}</p>\n')
        if with_:
            out.append(f'<p class="facts">with {with_}</p>\n')
        if j.draft is not None:
            out.append(_draft_folded(j.draft))
        if j.draft_withheld is not None:  # the policy no longer allows it: the row, never the text
            out.append(_withheld_html(j.draft_withheld, heading=False))
        out.append(self._evidence(self._journey_evidence(j)))
        out.append("</li>\n")
        return "".join(out)

    def _journey_evidence(self, j: journeys.Journey) -> list[Evidence]:
        """Where a journey row comes from: each run of nights at one place with the lines of its
        stays, the flights, each person with the lines that put them there, the photos, the name."""
        items: list[Evidence] = []
        runs: list[list[dict[str, Any]]] = []
        for night in j.nights_of:
            if runs and night["where"] == runs[-1][-1]["where"]:
                runs[-1].append(night)
            else:
                runs.append([night])
        for run, where in zip(runs, trips.route_names([r[0]["where"] for r in runs]), strict=True):
            first, last = run[0]["day"], run[-1]["day"]
            span = first if first == last else f"{first} {EN_DASH} {last}"
            lines = list(dict.fromkeys(i for n in run for i in n["lines"]))
            items.append((f"{_plural(len(run), 'night')} {span} {where}", lines, first))
        for f in j.trip.flights:
            name = f"{f['carrier']} {f['number']} " if f.get("number") else ""
            items.append((f"flight {name}{f['from']} {ARROW} {f['to']}", list(f["lines"]), str(f["date"])))
        for p in j.people:
            items.append((f"with {p['name']}", p["lines"], None))
        if j.photos:
            items.append((_plural(len(j.photos), "photo"), j.photos, None))
        if j.name is not None:
            items.append((f"named {j.name.text}", [j.name.line], None))
        return items

    def _people_links(self, found: Sequence[Mapping[str, Any]], unplaced: int = 0) -> str:
        """The canonical people, each a link to their page; the ones no line names counted, a link
        to the review queue."""
        names = [self.link(escape(str(p["name"])), _person_path(str(p["id"]))) for p in found]
        if unplaced:
            names.append(self.link(f"{unplaced} not placed", "/people#review"))
        return ", ".join(names)

    def page_journey(self, start: str, end: str) -> str:
        """One journey: its name (and the form that names it), its draft folded, its stays as dots
        on a plain canvas and one row each, its days one row each linking the Day, the promises
        made on it, its people and photos; every row with its evidence folded."""
        try:
            data = journeys.read(self.lb, f"trip:{start}:{end}", self.airports, self.tiers)
        except stays.SettingsError:
            raise
        except ValueError as e:
            raise NotFound(f"no journey at /journeys/{start}/{end}: {e}") from e
        row = data["journey"]
        named = row["name"]
        dates = f"{data['start']} {EN_DASH} {data['end']}"
        title = f"{escape(named['text'])} <small>{_dates(dates)}</small>" if named else _dates(dates)
        year = data["start"][:4]
        parts = [
            f"<h1>{title}</h1>\n",
            f'<p class="mute">{escape(trip_page.head_text(data))}{DOT}'
            f"{_plural(row['photos']['count'], 'photo')}</p>\n",
            f'<p class="pager">{self.link(f"← journeys of {year}", f"/journeys?year={year}")}{DOT}'
            f"{self.link('its days', f'/days?from={data["start"]}&to={data["until"]}')}</p>\n",
        ]
        if not self.static:
            parts.append(
                f'<form class="name" method="post" action="{NAME_PATH}">'
                f'<input type="hidden" name="id" value="{escape(data["id"])}">'
                f'<input type="text" name="name" value="{escape(named["text"] if named else "")}"'
                ' placeholder="what you call it" aria-label="name this journey" autocomplete="off">'
                "<button>Name this journey</button></form>\n"
            )
        if named:
            parts.append(self._evidence([("named", [named["line"]], None)], "the name"))
        if row["draft"] is not None:
            parts.append(_draft_folded(row["draft"]))
        if row["draft_withheld"] is not None:  # the policy no longer allows it: the row, never the text
            parts.append(_withheld_html(row["draft_withheld"], heading=False))
        parts.append("<h2>Stays</h2>\n")
        parts.append(_stays_svg(data["route"]))
        parts.append('<ol class="shelf">\n')
        for s, name in zip(data["route"], trip_page.route_names(data["route"]), strict=True):
            span = s["first"] if s["first"] == s["last"] else f"{s['first']} {EN_DASH} {s['last']}"
            what = f"{s['n']}. {span}{DOT}{_plural(s['nights'], 'night')}{DOT}{trip_page.stay_text(s, name)}"
            evidence = [(f"stay {s['stay']}", s["lines"], s["first"])] if s["stay"] else []
            parts.append(f"<li><p>{escape(what)}</p>\n{self._evidence(evidence)}</li>\n")
        parts.append("</ol>\n")
        parts.append('<h2>Days</h2>\n<ol class="shelf">\n')
        for r in data["days"]:
            day = str(r["day"])
            parts.append(
                f'<li><p class="head">{self.link(day, f"/day/{day}")} <span class="mute">'
                f"{escape(r['weekday'][:3])}</span> {escape(days_reader.night_text(r))}</p>\n"
                f'<p class="facts">{escape(DOT.join(days_reader.parts(r)))}</p>\n'
                f"{self._evidence(self._day_evidence(r))}</li>\n"
            )
        parts.append("</ol>\n")
        parts.append("<h2>Promises made on it</h2>\n")
        if data["promises"]:
            parts.append('<ol class="shelf">\n')
            parts.extend(self._promise_row(p) for p in data["promises"])
            parts.append("</ol>\n")
        else:
            parts.append('<p class="mute">none: no sentence on its days reads like one</p>\n')
        parts.append("<h2>People</h2>\n")
        confirmed = [p for p in data["people"]["confirmed"] if p["id"]]
        if confirmed:
            parts.append('<ol class="shelf">\n')
            for p in confirmed:
                parts.append(
                    f"<li><p>{self.link(escape(p['name']), _person_path(p['id']))}"
                    f' <span class="mute">{escape(", ".join(p["sources"]))}</span></p>\n'
                    f"{self._evidence([(f'with {p["name"]}', p['lines'], None)])}</li>\n"
                )
            parts.append("</ol>\n")
        else:
            parts.append('<p class="mute">nobody the record names was confirmed on it</p>\n')
        unplaced = row["unplaced"]
        if unplaced:
            parts.append(
                f'<p class="mute">and {self.link(f"{unplaced} not placed", "/people#review")}: seen,'
                " named by no line of the record</p>\n"
            )
        if row["photos"]["count"]:
            parts.append(f"<h2>Photos</h2>\n<p>{_plural(row['photos']['count'], 'photo')} on its days</p>\n")
            parts.append(self._evidence([("photos", row["photos"]["lines"], None)]))
        return self.document(named["text"] if named else f"journey {dates}", "".join(parts))

    def _day_evidence(self, r: Mapping[str, Any]) -> list[Evidence]:
        """Where a day row comes from: the night's stay and its lines, then each source's lines on
        the day, counted; a day with none says so."""
        items: list[Evidence] = []
        night = r["night"]
        if night.get("stay"):
            items.append((f"night: stay {night['stay']}", r.get("night_lines") or [], None))
        for source in r["sources"]:
            items.append((f"{source['source']}: {_plural(int(source['lines']), 'line')}", [], None))
        if not items:
            items.append(("no line on the day: nothing places the night", [], None))
        return items

    def _promise_row(self, p: Mapping[str, Any]) -> str:
        who = {
            "promise": "you",
            "request": f"asked of you{f' by {p["speaker"]}' if p.get('speaker') else ''}",
            "theirs": str(p.get("speaker") or "?"),
        }.get(str(p.get("role")), str(p.get("speaker") or "?"))
        to = f" to {p['counterpart']}" if p.get("counterpart") and p.get("role") == "promise" else ""
        due = f"{DOT}due {p['due']}" if p.get("due") else ""
        status = f"{DOT}{p['status']}" if p.get("status") else ""
        day = str(p["day"])
        return (
            f'<li><p class="head">{self.link(day, f"/day/{day}")} <span class="mute">{escape(who + to)}'
            f"{escape(due + status)}</span></p>\n<p>{escape(str(p['quote']))}</p>\n"
            f"{self._evidence([(f'{p["kind"]} ({p["source"]})', [p['line']], day)])}</li>\n"
        )

    # -- /people -------------------------------------------------------------------------------------------

    def page_people(self, year: str | None) -> str:
        """The canonical people heard in the year (default this year, or the record's last), by days
        together then last real contact, each a link to their page with its evidence folded; then
        the review queue: who the sources saw that the record has not placed, proposed against the
        people it names, with Merge and Not the same person; the observed are listed there only."""
        data = self.shared(("ranked", year), lambda: person_page.ranked(self.lb, year, self.now()))
        if data["year"] is None:
            return self.document("people", "<h1>People</h1>\n<p>no people: the record has no lines</p>\n")
        year = str(data["year"])
        links = DOT.join(
            f"<b>{y}</b>" if y == year else self.link(y, f"/people?year={y}") for y in data["years"]
        )
        parts = [f"<h1>People <small>{year}</small></h1>\n", f'<p class="pager">{links}</p>\n']
        if not data["people"]:
            parts.append(f"<p>nobody the record names was heard in {year}</p>\n")
        else:
            parts.append(
                '<p class="mute">The people the record names, by days together this year, then the last'
                " real contact. Someone the sources saw and the record has not placed is in the review"
                " below, never here.</p>\n"
            )
            parts.append('<ol class="shelf">\n')
            for r in data["people"]:
                parts.append(self._person_row(r))
            parts.append("</ol>\n")
        if not self.static:
            from . import people_review

            with self._review_lock:  # the observed table is built once, as the Places page's queue is
                report = self.shared(("people review",), lambda: people_review.read(self.lb))
            parts.append(self._review_html(report, year))
        return self.document(f"people {year}", "".join(parts))

    def _person_row(self, r: Mapping[str, Any]) -> str:
        days = int(r["days"])
        facts = [f"{_plural(days, 'day')} together" if days else "no day together"]
        if r["nights"]:
            facts.append(f"{_plural(int(r['nights']), 'night')} under one roof")
        contact = r["last_real_contact"]
        facts.append(
            f"last real contact {contact['day']} ({contact['via']})" if contact else "no real contact"
        )
        items: list[Evidence] = [
            (f"together at {d['where']}", d["lines"], str(d["day"])) for d in reversed(r["together"])
        ]
        if contact:
            items.insert(0, (f"last real contact, {contact['via']}", [contact["line"]], str(contact["day"])))
        for name, c in r["channels"].items():
            span = c["first"] if c["first"] == c["last"] else f"{c['first']} {EN_DASH} {c['last']}"
            items.append(
                (f"{name}: {_plural(int(c['lines']), 'line')}, {span}, the last", [c["last_line"]], None)
            )
        return (
            f'<li><p class="head">{self.link(f"<b>{escape(str(r['name']))}</b>", _person_path(str(r["id"])))}'
            f'</p>\n<p class="facts">{escape(DOT.join(facts))}</p>\n{self._evidence(items)}</li>\n'
        )

    def _review_html(self, report: people_review.Report, year: str) -> str:
        """The review queue of `people review`, in its order: each proposal with its evidence and
        the two acts; then the observed people nobody matches, folded."""
        proposed = {p.observed.key for p in report.proposals}
        alone = [o for o in report.unplaced if o.key not in proposed]
        head = f"{_plural(len(report.proposals), 'proposal')}{DOT}{len(report.unplaced)} seen, not placed"
        out = [f'<h2 id="review">Review <small>{escape(head)}</small></h2>\n']
        if not report.proposals and not report.unplaced:
            out.append('<p class="mute">nothing to review: everyone the sources saw is placed</p>\n')
            return "".join(out)
        out.append(
            '<p class="mute">Who the sources saw that the record has not placed, proposed against the'
            " people it names, as <code>people review</code> ranks them. Merge writes what"
            " <code>--accept</code> writes, an alias line for each identifier seen; Not the same person"
            " what <code>--reject</code> writes, so the pair is never proposed again.</p>\n"
        )
        if report.proposals:
            out.append('<ol class="shelf queue">\n')
            for p in report.proposals:
                o = p.observed
                shown = o.key[1] if o.key[0] != "name" else o.name
                seen = ", ".join(f"{kind} {n}" for kind, n in sorted(o.kinds.items()))
                who = f"{shown} ({o.name}; {seen})" if o.name != shown else f"{shown} ({seen})"
                c = p.canonical  # None for a Google contact's name (`--from-google`), a new person
                into = (
                    self.link(escape(c.label), _person_path(c.entity)) if c is not None else escape(p.label)
                )
                items: list[Evidence] = [(why, [], None) for why in p.evidence]
                items.append(
                    (f"seen {o.first} {EN_DASH} {o.last}, {_plural(o.lines, 'line')}", o.samples, None)
                )
                out.append(
                    f'<li class="proposal" id="{escape(p.id)}"><p class="head"><b>{p.number}.</b>'
                    f' {escape(who)} {ARROW} {into} <span class="mute">score {p.score}</span></p>\n'
                    f"{self._evidence(items, open_=True)}"
                    f'<form method="post" action="{PEOPLE_REVIEW_PATH}">'
                    f'<input type="hidden" name="id" value="{escape(p.id)}">'
                    f'<input type="hidden" name="year" value="{escape(year)}">'
                    '<button name="act" value="merge">Merge</button>'
                    '<button name="act" value="reject">Not the same person</button></form>\n</li>\n'
                )
            out.append("</ol>\n")
        if alone:
            out.append(f"<details><summary>{_plural(len(alone), 'more seen')}, nobody matches</summary>\n")
            out.append('<ol class="shelf">\n')
            for o in alone:
                shown = o.key[1] if o.key[0] != "name" else o.name
                seen = ", ".join(f"{kind} {n}" for kind, n in sorted(o.kinds.items()))
                facts = f"{shown} ({seen}){DOT}{_plural(len(o.days), 'day')}{DOT}{o.first} {EN_DASH} {o.last}"
                out.append(
                    f"<li><p>{escape(facts)}</p>\n"
                    f"{self._evidence([(f'seen in {_plural(o.lines, "line")}', o.samples, None)])}</li>\n"
                )
            out.append("</ol>\n</details>\n")
        return "".join(out)

    def page_person(self, name: str) -> str:
        """One person's page: the numbers, the last real contact and what it was, the drift, the
        days together by year, the promises both ways, the anniversaries of the coming month, the
        places; every row with its evidence folded."""
        everyone = self.shared(("everyone",), lambda: person_page.everyone(self.lb, self.airports))
        data = person_page.read(self.lb, name, self.now(), self.airports, everyone)
        refs = ", ".join(str(r["value"]) for r in data["refs"])
        parts = [
            f"<h1>{escape(data['name'])}</h1>\n",
            f'<p class="mute">{escape(refs)}'
            + (f"{DOT}birthday {escape(data['birthday'])}" if data["birthday"] else "")
            + "</p>\n",
            f'<p class="pager">{self.link("← people", "/people")}</p>\n',
            '<ol class="shelf">\n',
        ]
        together = [d for y in data["years"] for d in y["together"]]
        days = f"{_plural(data['days'], 'day')} together" if data["days"] else "no day together"
        if data["nights"]:
            days += f"{DOT}{_plural(data['nights'], 'night')} under one roof"
        parts.append(
            f"<li><p>{escape(days)}</p>\n"
            f"{self._evidence([(f'at {d["where"]}', d['lines'], str(d['day'])) for d in together])}</li>\n"
        )
        contact = data["last_real_contact"]
        if contact is None:
            parts.append("<li><p>no real contact in the record</p></li>\n")
        else:
            parts.append(
                f"<li><p>last real contact {self.link(str(contact['day']), f'/day/{contact["day"]}')}"
                f"{DOT}{escape(str(contact['what']))}</p>\n"
                f"{self._evidence([(str(contact['via']), [contact['line']], str(contact['day']))])}</li>\n"
            )
        drift = data["drift"]
        best = next((y for y in data["years"] if y["year"] == drift["year"]), None)
        drift_items: list[Evidence] = []
        if best is not None:
            drift_items.append((f"{_plural(best['days'], 'day')} together in {best['year']}", [], None))
        if contact is not None:
            drift_items.append(("the last real contact", [contact["line"]], str(contact["day"])))
        parts.append(f"<li><p>{escape(drift['text'])}</p>\n{self._evidence(drift_items)}</li>\n</ol>\n")
        parts.append("<h2>Days together</h2>\n")
        if data["years"]:
            parts.append('<ol class="shelf">\n')
            for y in data["years"]:
                items = [(f"at {d['where']}", d["lines"], str(d["day"])) for d in y["together"]]
                parts.append(
                    f"<li><p><b>{y['year']}</b>{DOT}{_plural(y['days'], 'day')}</p>\n"
                    f"{self._evidence(items, 'the days')}</li>\n"
                )
            parts.append("</ol>\n")
        else:
            parts.append('<p class="mute">none: no stay of yours confirms them there</p>\n')
        parts.append("<h2>Promises</h2>\n")
        for key, label in (("you_owe", "You owe"), ("they_owe", "They owe")):
            found = data["promises"][key]
            parts.append(f"<h3>{label}</h3>\n")
            if not found:
                parts.append('<p class="mute">nothing open</p>\n')
                continue
            parts.append('<ol class="shelf">\n')
            for p in found:
                due = f"{DOT}due {p['due']}" if p["due"] else ""
                day = str(p["day"])
                parts.append(
                    f'<li><p class="head">{self.link(day, f"/day/{day}")}'
                    f'<span class="mute">{escape(due)}</span>'
                    f"</p>\n<p>{escape(str(p['quote']))}</p>\n"
                    f"{self._evidence([(f'{p["kind"]} ({p["source"]})', [p['line']], day)])}</li>\n"
                )
            parts.append("</ol>\n")
        parts.append(f"<h2>Anniversaries <small>{escape(data['today'])} and the month after</small></h2>\n")
        if data["anniversaries"]:
            parts.append('<ol class="shelf">\n')
            for a in data["anniversaries"]:
                ago = _plural(int(a["years"]), "year")
                parts.append(
                    f"<li><p>{escape(str(a['on']))}{DOT}{ago} since "
                    f"{self.link(str(a['day']), f'/day/{a["day"]}')}"
                    f" at {escape(str(a['where']))}</p>\n"
                    f"{self._evidence([('together', a['lines'], str(a['day']))])}</li>\n"
                )
            parts.append("</ol>\n")
        else:
            parts.append('<p class="mute">none in the coming month</p>\n')
        parts.append("<h2>Places</h2>\n")
        if data["places"]:
            parts.append('<ol class="shelf">\n')
            for pl in data["places"]:
                there: list[Evidence] = [
                    ("the days there", pl["lines"], None),
                    *[(d, [], d) for d in pl["on"]],
                ]
                parts.append(
                    f"<li><p>{escape(str(pl['where']))}{DOT}{_plural(int(pl['days']), 'day')}</p>\n"
                    f"{self._evidence(there)}</li>\n"
                )
            parts.append("</ol>\n")
        else:
            parts.append('<p class="mute">none yet</p>\n')
        return self.document(str(data["name"]), "".join(parts))

    # -- the evidence --------------------------------------------------------------------------------------

    def _evidence(self, items: Sequence[Evidence], label: str = "evidence", open_: bool = False) -> str:
        """Where a derived row comes from, folded: a disclosure, closed unless `open_`, whose summary
        counts the lines, and in it one row per piece of evidence, what it is, the day it links and
        the ids of the lines (the whole id on hover), `places_review.SHOWN` rows shown and the rest
        behind "… and N more" (`_folded`, the Places page's own). Nothing when there is none."""
        if not items:
            return ""
        lines = {i for _what, ids, _day in items for i in ids}
        rows = []
        for what, ids, day in items:
            if day and DAY.fullmatch(day):
                text = f"{escape(what)} {self.link(day, f'/day/{day}')}"
            else:
                text = escape(what) + (f" {escape(day)}" if day else "")
            shown = " ".join(
                f'<span class="id" title="line {escape(i)}">{escape(drafts.short_id(i))}</span>'
                for i in ids[:ID_SHOWN]
            )
            more = f" +{len(ids) - ID_SHOWN}" if len(ids) > ID_SHOWN else ""
            rows.append(f"{text}{' ' + shown if shown else ''}{more}")
        count = _plural(len(lines), "line") if lines else _plural(len(items), "row")
        return (
            f'<details class="evidence"{" open" if open_ else ""}>'
            f"<summary>{escape(label)}{DOT}{count}</summary>\n{_folded(rows)}</details>\n"
        )

    # -- /manifest, /org/<id>, /manifest/people (RFC 0037 §7, §11) -----------------------------------------

    def _acts(self) -> bool:
        """Whether the Manifest offers and takes its acts: a page the owner can write from (not an
        exported one) that reads tier 3, since an org's status is tier 3, a no on a merchant may be,
        and the queue's merchants rest on ledger lines. `logbook serve` reads every tier."""
        return not self.static and (self.tiers is None or orgs.MONEY_TIER in self.tiers)

    def _org_record(self, money: bool = False) -> orgs.Record:
        """The orgs as these pages read them: through the site's gate, money only when asked."""
        return self.shared(
            ("orgs", money), lambda: orgs.read(self.lb, orgs.gate(self.tiers, money), self._today_of())
        )

    def _review_of(self, kind: str) -> entity_review.Report:
        """The review queue of `kind` (an org's, an idea's) as the record stands: read once for every
        page that shows it; an act reads it again, under the lock it writes under."""
        return self.shared(("review", kind), lambda: entity_review.read(self.lb, kind))

    def _today_of(self) -> str:
        """The day the owner is in (the record's zone and `day_start`): what the stale flag counts to."""
        return day_start.of(self.lb.meta).today(self.now()).isoformat()

    def page_manifest(self, page: str = "1", portfolio: str | None = None) -> str:
        """The orgs the owner named, under what they decided about them (RFC 0037 §11: holding,
        exited, passed — the anti-portfolio, each reason in full —, let go, no status), the most
        recent touch first, each a link to its page with its evidence folded; a filter by the
        portfolios the record holds, when the page reads tier 3, and with `portfolio` only the orgs
        that one holds; then the review queue of `review org`, its order, `PAGE_SIZE` a page, with
        its acts. One column, no table. Through a gate without tier 3 no filter is offered and one
        asked for lists no org, the same page whichever portfolio is asked."""
        if not page.isdigit() or int(page) < 1:
            raise ValueError(f"page must be a number from 1, not {page!r}")
        with self._review_lock:  # the observed table is built once, as the other queues' are
            shelf = orgs.shelf_of(self.lb, self._org_record(), portfolio=portfolio)
            report = self._review_of(entities.ORG) if self._acts() else None
        filtered = portfolio is not None and shelf.portfolios_read
        count = _plural(len(shelf.rows), "org") + (f" in {portfolio}" if filtered else "")
        parts = [f"<h1>The Manifest {self.tier_small(f'{count}{DOT}{shelf.on}', shelf.tier)}</h1>\n"]
        if shelf.portfolios:
            here = None if portfolio is None else entities.fold(portfolio)
            links = ["<b>every org</b>" if here is None else self.link("every org", "/manifest")]
            for name in shelf.portfolios:
                if entities.fold(name) == here:
                    links.append(f"<b>{escape(name)}</b>")
                else:
                    links.append(self.link(escape(name), f"/manifest?portfolio={quote(name, safe='')}"))
            parts.append(f'<p class="pager">portfolio: {DOT.join(links)}</p>\n')
        if shelf.withheld:
            parts.append(
                f'<p class="mute">{_plural(shelf.withheld, "status line")} not shown: an org\'s status is'
                " tier 3, and this page reads no tier 3.</p>\n"
            )
        if portfolio is not None and not shelf.portfolios_read:
            parts.append(
                '<p class="mute">no org shown by portfolio: a portfolio is tier 3, on an org\'s status'
                " line, and this page reads no tier 3.</p>\n"
            )
        elif portfolio is not None and not shelf.rows:
            parts.append(f"<p>no org is in {escape(portfolio)}; {self.link('every org', '/manifest')}</p>\n")
        elif not shelf.rows:
            parts.append(
                "<p>no orgs named yet: name them below, from what the sources already saw, or with"
                " <code>logbook review org</code></p>\n"
            )
        else:
            parts.append(
                '<p class="mute">The orgs you named, under what you decided about them, the most recent'
                " touch first. A touch is a line that reaches the org through one of its refs: a mail at its"
                " domain, a meeting with its people, its group, its code, its merchant.</p>\n"
            )
        for name, rows in shelf.grouped():
            small = " <small>the anti-portfolio</small>" if name == "passed" else ""
            parts.append(f'<h2>{escape(name)}{small}</h2>\n<ol class="shelf">\n')
            parts.extend(self._org_row(r, [x.org for x in shelf.rows]) for r in rows)
            parts.append("</ol>\n")
        parts.append(
            f"<p>{self.link('People across orgs', '/manifest/people')}: who appears with more than one.</p>\n"
        )
        if report is not None:
            kept = f"&portfolio={quote(portfolio, safe='')}" if filtered and portfolio is not None else ""
            parts.append(self._org_queue_html(report, int(page), kept=kept))
        return self.document("manifest", "".join(parts), style=MANIFEST_STYLE)

    def _org_row(self, r: orgs.Row, among: Sequence[entities.Entity]) -> str:
        cls = ' class="stale"' if r.stale else ""
        link = self.link(f"<b>{escape(orgs.shown_name(r.org, among))}</b>", _org_path(r.org.id))
        head = [link, self._status_html(r.status, r.since)]
        if r.portfolio is not None:
            head.append(f'<span class="mute">portfolio {escape(r.portfolio)}</span>')
        if r.stale:
            head.append(f'<span class="stale-flag">stale: nothing since {escape(r.stale_since or "")}</span>')
        last = "no touch" if r.last is None else f"last touch {r.last.day} {r.last_text or r.last.kind}"
        facts = [last]
        if r.people:
            first = ", ".join(p.name for p in r.people[:2])
            facts.append(f"{orgs.plural(len(r.people), 'person', 'people')} ({first})")
        if r.documents:
            facts.append(_plural(r.documents, "document"))
        out = [
            f'<li id="{escape(r.org.id)}"{cls}><p class="head">{" ".join(head)}</p>\n',
            f'<p class="facts">{escape(DOT.join(facts))}</p>\n',
        ]
        if r.status is not None and r.status.status in orgs.WITH_REASON and r.status.reason:
            out.append(f'<p class="reason">{escape(r.status.reason)}</p>\n')
        items: list[Evidence] = []
        if r.last is not None:
            kind = orgs.THE_LEDGER if r.last_text == orgs.THE_LEDGER else r.last.kind
            items.append((f"last touch, {kind} by its {r.last.via}", [r.last.line], r.last.day))
        if r.status is not None:
            items.append((f"{r.status.status}, the status line", [r.status.line], r.since))
        items.append((f"{_plural(r.touches, 'touch')} in all, tier {r.tier} at most", [], None))
        out.append(f"{self._evidence(items)}</li>\n")
        return "".join(out)

    def _status_html(self, status: entities.Status | None, since: str | None) -> str:
        if status is None:
            return '<span class="mute">no status</span>'
        who = status.proposed_by or "owner"
        return (
            f'<span class="badge {escape(status.status)}">{escape(status.status)}</span>'
            f' <span class="mute">since {escape(since or "")} ({escape(who)})</span>'
        )

    def _org_queue_html(
        self, report: entity_review.Report, page: int, into: str | None = None, kept: str = ""
    ) -> str:
        """The review queue of `review org`, or the part of it that would place something with the org
        `into`: each proposal with its evidence folded and its acts, through the functions `review
        org --accept`, `--name` and `--reject` call. `kept` is the shelf's filter as a query
        (`&portfolio=…`), kept on the pager and on the way back from an act."""
        proposals = [p for p in report.proposals if into is None or (p.canonical and p.canonical.id == into)]
        if into is not None and not proposals:
            return ""
        title = "Proposed for this org" if into is not None else "Name these orgs"
        counts = f"{_plural(len(proposals), 'proposal')}{DOT}{len(report.unplaced)} seen, not placed"
        out = [f'<h2 id="review">{title} <small>{escape(counts)}{DOT}{report.placed} placed</small></h2>\n']
        if not proposals:
            out.append(f'<p class="mute">{escape(_nothing_to_review(len(report.unplaced), "org"))}</p>\n')
            return "".join(out)
        if into is None:
            out.append(
                '<p class="mute">What the sources saw that is no org of yours yet, proposed against the orgs'
                " you named or as a new one, as <code>review org</code> ranks them. Accept writes what"
                " <code>--accept</code> writes, Name what <code>--name</code> writes, No what"
                " <code>--reject</code> writes, so the pair is never proposed again. The hint (company,"
                " community, brand, personal) ranks it and decides nothing.</p>\n"
            )
        size = PAGE_SIZE if into is None else max(1, len(proposals))  # an org's own: one page, all
        pages = max(1, math.ceil(len(proposals) / size))
        n = min(page, pages)
        first = (n - 1) * size
        shown = proposals[first : first + size]
        back = _org_path(into) if into is not None else f"/manifest?page={n}{kept}"
        out.append(f'<ol class="shelf queue" start="{first + 1}">\n')
        out.extend(self._org_proposal(p, back) for p in shown)
        out.append("</ol>\n")
        if pages > 1:
            pager = [f"{first + 1}{EN_DASH}{first + len(shown)} of {len(proposals)}"]
            if n > 1:
                pager.insert(0, f'<a href="/manifest?page={n - 1}{escape(kept)}#review">← earlier</a>')
            if n < pages:
                pager.append(f'<a href="/manifest?page={n + 1}{escape(kept)}#review">more →</a>')
            out.append(f'<p class="pager">{DOT.join(pager)}</p>\n')
        return "".join(out)

    def _org_proposal(self, p: entity_review.Proposal, back: str) -> str:
        o = p.observed
        shown = f'group "{o.key[1]}"' if o.key[0] == "group" else o.key[1]
        into = self.link(escape(p.canonical.label), _org_path(p.canonical.id)) if p.canonical else "a new org"
        score = "new" if p.score is None else f"score {p.score}"
        seen = ", ".join(f"{kind} {count}" for kind, count in sorted(o.kinds.items()))
        items: list[Evidence] = [(why, [], None) for why in p.evidence if why != "new"]
        items.append((f"seen on {seen}, {o.first} {EN_DASH} {o.last}", [i for i, _t in o.samples], None))
        items.extend((f"named {label} ({count})", [], None) for label, count in o.labels.most_common())
        items.append((f"hint {o.hint or '-'}: ranks it, decides nothing", [], None))
        form = [
            f'<form class="act" method="post" action="{MANIFEST_REVIEW}">',
            f'<input type="hidden" name="id" value="{escape(p.id)}">',
            f'<input type="hidden" name="back" value="{escape(back)}">',
        ]
        if p.canonical is None:
            form.append(
                f'<input type="text" name="name" value="{escape(o.name)}" aria-label="the org\'s name"'
                ' autocomplete="off"><button name="act" value="name">Name</button>'
                '<button name="act" value="reject">No, not an org</button>'
            )
        else:
            form.append(
                f'<button name="act" value="accept">Accept: {escape(p.canonical.label)}</button>'
                '<button name="act" value="reject">No, not this org</button>'
            )
        form.append("</form>\n")
        return (
            f'<li class="proposal" id="{escape(p.id)}"><p class="head"><b>{p.number}.</b> {escape(shown)}'
            f' {ARROW} {into} <span class="mute">{escape(score)}{DOT}{escape(o.hint or "-")}</span></p>\n'
            f"{self._evidence(items)}{''.join(form)}</li>\n"
        )

    def page_org(self, org_id: str, money: bool = False) -> str:
        """One org (RFC 0037 §7): its refs, its status and reason (or how many status lines this page may
        not show), the status form, money when asked and the gate reads tier 3, every touch newest
        first (the newest `SHOWN`, the rest folded), its people, who introduced whom, its documents as
        references, every status line, and the proposals that would place something with it."""
        with self._review_lock:
            rec = self._org_record(money and not self.static)
            page = orgs.page_of(self.lb, rec, org_id)
            report = self._review_of(entities.ORG) if self._acts() else None
        org = page.org
        parts = [f"<h1>{escape(org.label)} <small>org{DOT}tier {page.tier}</small></h1>\n"]
        refs = ", ".join(v for _k, v in org.refs)
        if refs:
            parts.append(f'<p class="mute">{escape(refs)}</p>\n')
        if page.status is not None:
            parts.append(f'<p class="head">{self._status_html(page.status, page.since)}</p>\n')
            if page.status.reason:
                parts.append(f'<p class="reason">{escape(page.status.reason)}</p>\n')
            if page.portfolio is not None:
                parts.append(f'<p class="mute">portfolio {escape(page.portfolio)}</p>\n')
        elif page.hidden:
            parts.append(f'<p class="mute">{escape(orgs.HIDDEN)}.</p>\n')
        else:
            parts.append('<p class="mute">no status yet</p>\n')
        if page.stale:
            parts.append(f'<p class="stale-flag">stale: nothing since {escape(page.stale_since or "")}</p>\n')
        if self._acts():
            parts.append(self._org_acts(org, page.status, page.portfolio, orgs.held(rec)))
        if page.money is not None:
            parts.append(
                '<h2>Money <small>tier 3, derived from the ledger now</small></h2>\n<ul class="plain">\n'
            )
            for year, currencies in page.money.items():
                for currency, cell in currencies.items():
                    parts.append(f"<li>{escape(year)} {escape(orgs.money_text(currency, cell))}</li>\n")
            if not page.money:
                parts.append('<li class="mute">no ledger line reaches it</li>\n')
            parts.append("</ul>\n")
        elif rec.gate.reads(orgs.MONEY_TIER) and not self.static:
            parts.append(f'<p class="mute"><a href="{escape(_org_path(org.id))}?money=1">show the money</a>'
                         " (tier 3, the ledger read now)</p>\n")  # fmt: skip
        parts.append(f"<h2>Timeline <small>{_plural(len(page.timeline), 'line')}</small></h2>\n")
        if not page.timeline:
            parts.append('<p class="mute">no line reaches it yet</p>\n')
        else:
            rows = [self._org_item(i) for i in page.timeline]
            parts.append('<ol class="shelf">\n' + "".join(rows[:SHOWN]) + "</ol>\n")
            if rows[SHOWN:]:
                parts.append(
                    f"<details><summary>{EN_DASH} and {len(rows) - SHOWN} earlier</summary>\n"
                    f'<ol class="shelf">\n{"".join(rows[SHOWN:])}</ol>\n</details>\n'
                )
        parts.append("<h2>People</h2>\n")
        if page.people:
            parts.append('<ul class="plain">\n')
            for person in page.people:
                when = f"{_plural(person.days, 'day')}, the last {person.last}"
                parts.append(
                    f"<li>{self.link(escape(person.name), _person_path(person.person))}"
                    f' <span class="mute">{escape(when)}</span></li>\n'
                )
            parts.append("</ul>\n")
        else:
            parts.append('<p class="mute">nobody the record names</p>\n')
        if page.unplaced:
            parts.append(f'<p class="mute">and {page.unplaced} not yet placed</p>\n')
        if page.introductions:
            parts.append('<h2>Introductions</h2>\n<ul class="plain">\n')
            for intro in page.introductions:
                parts.append(
                    f'<li title="line {escape(intro.line)}">{escape(intro.by)} introduced'
                    f" {escape(', '.join(intro.introduced))}"
                    f' <span class="mute">{escape(intro.day)}, “{escape(intro.subject)}”</span></li>\n'
                )
            parts.append("</ul>\n")
        parts.append("<h2>Documents <small>references, never copies</small></h2>\n")
        if page.documents:
            parts.append('<ol class="shelf">\n')
            for d in page.documents:
                parts.append(
                    f'<li title="line {escape(d.line)}"><span class="mute">{escape(d.day)}</span>'
                    f' <span class="badge">{escape(d.kind)}</span> {escape(d.name)}</li>\n'
                )
            parts.append("</ol>\n")
        else:
            parts.append('<p class="mute">none</p>\n')
        parts.append("<h2>Status lines</h2>\n")
        if page.history:
            parts.append('<ol class="shelf">\n')
            for s in page.history:
                text = escape(
                    f"{s.status} ({s.proposed_by or 'owner'})"
                    + (f": {s.reason}" if s.reason else "")
                    + orgs.portfolio_text(s.portfolio)
                )
                if not s.standing:
                    text = f'<s class="retracted">{text}</s> <span class="mute">retracted</span>'
                elif s.current:
                    text += ' <span class="mute">current</span>'
                day = f'<span class="mute">{escape(s.day)}</span>'
                parts.append(f'<li title="line {escape(s.line)}">{day} {text}</li>\n')
            parts.append("</ol>\n")
        else:
            parts.append(
                '<p class="mute">none this page may show</p>\n'
                if page.hidden
                else '<p class="mute">none yet</p>\n'
            )
        if report is not None:
            parts.append(self._org_queue_html(report, 1, into=org.id))
        parts.append(f"<p>{self.link('The Manifest', '/manifest')}</p>\n")
        return self.document(org.label, "".join(parts), style=MANIFEST_STYLE)

    def _org_item(self, item: orgs.Item) -> str:
        day = self.link(escape(item.day), f"/day/{item.day}")
        return (
            f'<li title="line {escape(item.line)}{DOT}{escape(item.source)}{DOT}by its {escape(item.via)}">'
            f'{day} <span class="badge">{escape(item.kind)}</span> {escape(item.what)}</li>\n'
        )

    def _org_acts(
        self,
        org: entities.Entity,
        status: entities.Status | None,
        portfolio: str | None,
        portfolios: Sequence[str],
    ) -> str:
        """The status form: what `logbook status org ORG DISPOSITION [--reason …] [--at DAY]
        [--portfolio …]` writes. The portfolio box shows the portfolio that holds the org, and a
        hidden field the same, so that a box left as it was writes no portfolio at all and an
        emptied one clears it (`_org_status`)."""
        current = None if status is None else status.status
        choices = "".join(
            f'<option value="{s}"{" selected" if s == current else ""}>{s}</option>'
            for s in entities.DISPOSITIONS[entities.ORG]
        )
        known = "".join(f'<option value="{escape(name)}">' for name in portfolios)
        shown = escape(portfolio or "")
        return (
            '<section class="acts">\n'
            f'<form class="act" method="post" action="{MANIFEST_STATUS}">'
            f'<input type="hidden" name="org" value="{escape(org.id)}">'
            f'<input type="hidden" name="back" value="{escape(_org_path(org.id))}">'
            f'<select name="status" aria-label="status">{choices}</select>'
            '<input type="text" name="reason" placeholder="why (passed and let-go need one)"'
            ' aria-label="reason" autocomplete="off">'
            '<input type="date" name="at" aria-label="the day you decided">'
            f'<input type="text" name="portfolio" value="{shown}" placeholder="portfolio (empty: none)"'
            ' aria-label="portfolio" list="portfolios" autocomplete="off">'
            f'<input type="hidden" name="portfolio_was" value="{shown}">'
            f'<datalist id="portfolios">{known}</datalist>'
            '<button name="act" value="status">Set status</button></form>\n'
            '<p class="mute">One <code>status/v1</code> line, tier 3, your reason on it and nowhere'
            " else, and the portfolio when you change it.</p>\n</section>\n"
        )

    def page_manifest_people(self) -> str:
        """The co-investor graph: everyone who appears with more than one org, the most orgs first,
        with the orgs they share and the tier of the lines that say so; then the anti-portfolio."""
        with self._review_lock:
            shelf = orgs.shelf_of(self.lb, self._org_record())
        graph = shelf.graph
        parts = [
            f"<h1>People across orgs <small>{orgs.plural(len(graph), 'person', 'people')}</small></h1>\n"
        ]
        if not graph:
            parts.append("<p>nobody appears with more than one org yet</p>\n")
        else:
            parts.append('<ol class="shelf">\n')
            for shared in graph:
                links = ", ".join(self.link(escape(o.label), _org_path(o.id)) for o in shared.orgs)
                name = self.link(f"<b>{escape(shared.name)}</b>", _person_path(shared.person))
                parts.append(
                    f'<li class="person"><p class="head">{name}'
                    f' <span class="mute">tier {shared.tier}</span></p>\n<p class="facts">{links}</p></li>\n'
                )
            parts.append("</ol>\n")
        passed = shelf.passed
        if passed:
            parts.append('<h2>passed <small>the anti-portfolio</small></h2>\n<ol class="shelf">\n')
            parts.extend(self._org_row(r, [x.org for x in shelf.rows]) for r in passed)
            parts.append("</ol>\n")
        parts.append(f"<p>{self.link('The Manifest', '/manifest')}</p>\n")
        return self.document("people across orgs", "".join(parts), style=MANIFEST_STYLE)

    # -- /ideas, /idea/<id> (RFC 0037 §7, §11) -------------------------------------------------------------

    def _idea_acts(self) -> bool:
        """Whether the Ideas pages offer and take their acts: a page the owner can write from (not an
        exported one) that reads tier 2, an idea's status's tier. `logbook serve` reads every tier."""
        return not self.static and (self.tiers is None or entities.TIER in self.tiers)

    def _idea_record(self) -> ideas.Record:
        """The ideas as these pages read them: through the site's gate, today the owner's day."""
        return self.shared(("ideas",), lambda: ideas.read(self.lb, self.tiers, self._today_of()))

    def page_ideas(self, page: str = "1") -> str:
        """The ideas the owner named, by stage (RFC 0037 §11: build, exploring, spark, built, killed, no
        status), the most recent touch first, each a link to its page with its evidence folded and its
        reason; the people it was discussed with counted, named only on its page. Then the review queue
        of `review idea`, its order, `PAGE_SIZE` a page, with its acts. One column, no table."""
        if not page.isdigit() or int(page) < 1:
            raise ValueError(f"page must be a number from 1, not {page!r}")
        with self._review_lock:  # the observed table is built once, as the other queues' are
            shelf = ideas.shelf_of(self._idea_record())
            report = self._review_of(entities.IDEA) if self._idea_acts() else None
        head = f"{_plural(len(shelf.rows), 'idea')}{DOT}{shelf.on}"
        parts = [f"<h1>Ideas {self.tier_small(head, shelf.tier)}</h1>\n"]
        if not shelf.rows:
            parts.append(
                "<p>no ideas named yet: name them below, from what Notion, the repositories, the calls and"
                " the tasks already hold, or with <code>logbook review idea</code></p>\n"
            )
        else:
            parts.append(
                '<p class="mute">The ideas you named, by stage, the most recent touch first. A touch is a'
                " line that reaches the idea through one of its refs: a Notion page under its root, its"
                " repository, a task or a call of its title; a bot's line never is. Who it was discussed with"
                " is on its own page.</p>\n"
            )
        for name, rows in shelf.grouped():
            parts.append(f'<h2>{escape(name)}</h2>\n<ol class="shelf">\n')
            parts.extend(self._idea_row(r, shelf.year) for r in rows)
            parts.append("</ol>\n")
        if report is not None:
            parts.append(self._idea_queue_html(report, int(page)))
        return self.document("ideas", "".join(parts), style=IDEAS_STYLE)

    def _idea_row(self, r: ideas.Row, year: str) -> str:
        cls = ' class="stale"' if r.stale else ""
        link = self.link(f"<b>{escape(r.idea.label)}</b>", _idea_path(r.idea.id))
        head = [link, self._status_html(r.status, r.since)]
        if r.stale:
            head.append(f'<span class="stale-flag">stale: nothing since {escape(r.stale_since or "")}</span>')
        facts = ["no touch" if r.last is None else f"last touch {r.last.day} {r.last.what}"]
        if r.words:
            facts.append(f"{r.words:+,} words in {year}")
        facts.extend(r.repos)
        if r.people:
            facts.append(ideas.plural(r.people, "person", "people"))
        if r.days is not None:
            facts.append(f"{ideas.plural(r.days, 'day')} since spark")
        if r.titles:
            facts.append("titles " + ", ".join(f"“{t}”" for t in r.titles))
        out = [
            f'<li id="{escape(r.idea.id)}"{cls}><p class="head">{" ".join(head)}</p>\n',
            f'<p class="facts">{escape(DOT.join(facts))}</p>\n',
        ]
        reason = r.reason
        if reason is not None:
            out.append(f'<p class="reason">{escape(self._reason_text(r.status, reason))}</p>\n')
        items: list[Evidence] = []
        if r.last is not None:
            items.append((f"last touch, {r.last.kind} by its {r.last.via}", [r.last.line], r.last.day))
        if r.status is not None:
            items.append((f"{r.status.status}, the status line", [r.status.line], r.since))
        if reason is not None:
            items.append(("the reason's note", [reason.note], reason.day) if reason.note else ("", [], None))
        items.append(
            (f"{ideas.plural(r.touches, 'touch', 'touches')} in all, tier {r.tier} at most", [], None)
        )
        out.append(f"{self._evidence([i for i in items if i[0]])}</li>\n")
        return "".join(out)

    @staticmethod
    def _reason_text(status: entities.Status | None, reason: ideas.Reason) -> str:
        """The owner's words, and when a later status replaced the one they came with, which and when."""
        if status is not None and reason.line == status.line:
            return reason.reason
        return f"{reason.status} {reason.day}: {reason.reason}"

    def _idea_queue_html(self, report: entity_review.Report, page: int, into: str | None = None) -> str:
        """The review queue of `review idea`, or the part of it that would place something with the idea
        `into`: each proposal with its evidence folded and its acts, through the functions `review
        idea --accept`, `--name` and `--reject` call."""
        proposals = [p for p in report.proposals if into is None or (p.canonical and p.canonical.id == into)]
        if into is not None and not proposals:
            return ""
        title = "Proposed for this idea" if into is not None else "Name these ideas"
        counts = f"{_plural(len(proposals), 'proposal')}{DOT}{len(report.unplaced)} seen, not placed"
        out = [f'<h2 id="review">{title} <small>{escape(counts)}{DOT}{report.placed} placed</small></h2>\n']
        if not proposals:
            out.append(f'<p class="mute">{escape(_nothing_to_review(len(report.unplaced), "idea"))}</p>\n')
            return "".join(out)
        if into is None:
            out.append(
                '<p class="mute">What Notion pages, repositories, calls and tasks keep coming back to that is'
                " no idea of yours yet, proposed against the ideas you named or as a new one, as <code>review"
                " idea</code> ranks them. Accept writes what <code>--accept</code> writes, Name what"
                " <code>--name</code> writes, No what <code>--reject</code> writes, so the pair is never"
                " proposed again. A Notion row is proposed only when its <code>Type</code> is"
                " <code>Idea</code>.</p>\n"
            )
        size = PAGE_SIZE if into is None else max(1, len(proposals))  # an idea's own: one page, all
        pages = max(1, math.ceil(len(proposals) / size))
        n = min(page, pages)
        first = (n - 1) * size
        shown = proposals[first : first + size]
        back = _idea_path(into) if into is not None else f"/ideas?page={n}"
        out.append(f'<ol class="shelf queue" start="{first + 1}">\n')
        out.extend(self._idea_proposal(p, back) for p in shown)
        out.append("</ol>\n")
        if pages > 1:
            pager = [f"{first + 1}{EN_DASH}{first + len(shown)} of {len(proposals)}"]
            if n > 1:
                pager.insert(0, f'<a href="/ideas?page={n - 1}#review">← earlier</a>')
            if n < pages:
                pager.append(f'<a href="/ideas?page={n + 1}#review">more →</a>')
            out.append(f'<p class="pager">{DOT.join(pager)}</p>\n')
        return "".join(out)

    def _idea_proposal(self, p: entity_review.Proposal, back: str) -> str:
        o = p.observed
        shown = {"page": f"notion “{o.name}”", "title": f"title “{o.key[1]}”"}.get(o.key[0], o.key[1])
        into = (
            self.link(escape(p.canonical.label), _idea_path(p.canonical.id)) if p.canonical else "a new idea"
        )
        score = "new" if p.score is None else f"score {p.score}"
        seen = ", ".join(f"{kind} {count}" for kind, count in sorted(o.kinds.items()))
        items: list[Evidence] = [(why, [], None) for why in p.evidence if why != "new"]
        if p.call is not None:  # an idea a call's synthesis proposed: its name, and its words to answer
            shown = f"call “{p.call['name']}”"
            items.insert(0, (str(p.call["text"]), [], None))
        items.append((f"seen on {seen}, {o.first} {EN_DASH} {o.last}", [i for i, _t in o.samples], None))
        items.extend((f"named {label} ({count})", [], None) for label, count in o.labels.most_common())
        form = [
            f'<form class="act" method="post" action="{IDEAS_REVIEW}">',
            f'<input type="hidden" name="id" value="{escape(p.id)}">',
            f'<input type="hidden" name="back" value="{escape(back)}">',
        ]
        if p.canonical is None:
            form.append(
                f'<input type="text" name="name" value="{escape(o.name)}" aria-label="the idea\'s name"'
                ' autocomplete="off"><button name="act" value="name">Name</button>'
                '<button name="act" value="reject">No, not an idea</button>'
            )
        else:
            form.append(
                f'<button name="act" value="accept">Accept: {escape(p.canonical.label)}</button>'
                '<button name="act" value="reject">No, not this idea</button>'
            )
        form.append("</form>\n")
        return (
            f'<li class="proposal" id="{escape(p.id)}"><p class="head"><b>{p.number}.</b> {escape(shown)}'
            f' {ARROW} {into} <span class="mute">{escape(score)}</span></p>\n'
            f"{self._evidence(items)}{''.join(form)}</li>\n"
        )

    def page_idea(self, idea_id: str) -> str:
        """One idea (RFC 0037 §7): its refs, its status and reason, the status form, first said, every
        touch newest first (the newest `SHOWN`, the rest folded), the people it was discussed with by
        name, its documents as references, its title thread, the words by month, every status line,
        and the proposals that would place something with it."""
        with self._review_lock:
            page = ideas.page_of(self._idea_record(), idea_id)
            report = self._review_of(entities.IDEA) if self._idea_acts() else None
        idea = page.idea
        parts = [f"<h1>{escape(idea.label)} <small>idea{DOT}tier {page.tier}</small></h1>\n"]
        refs = ", ".join(v for _k, v in idea.refs)
        if refs:
            parts.append(f'<p class="mute refs">{escape(refs)}</p>\n')
        if page.status is not None:
            parts.append(f'<p class="head">{self._status_html(page.status, page.since)}</p>\n')
        else:
            parts.append('<p class="mute">no status yet</p>\n')
        if page.reason is not None:
            parts.append(f'<p class="reason">{escape(self._reason_text(page.status, page.reason))}</p>\n')
        if page.stale:
            parts.append(f'<p class="stale-flag">stale: nothing since {escape(page.stale_since or "")}</p>\n')
        if self._idea_acts():
            parts.append(self._idea_status_form(idea, page.status))
        if page.first is not None:
            since = "" if page.days is None else f"{DOT}{ideas.plural(page.days, 'day')} ago"
            parts.append(
                f'<p class="facts">first said {self.link(escape(page.first.day), f"/day/{page.first.day}")}'
                f" {escape(page.first.what)}{escape(since)}</p>\n"
            )
        parts.append(f"<h2>Timeline <small>{_plural(len(page.timeline), 'line')}</small></h2>\n")
        if not page.timeline:
            parts.append('<p class="mute">no line reaches it yet</p>\n')
        else:
            rows = [self._idea_item(i) for i in page.timeline]
            parts.append('<ol class="shelf">\n' + "".join(rows[:SHOWN]) + "</ol>\n")
            if rows[SHOWN:]:
                parts.append(
                    f"<details><summary>{EN_DASH} and {len(rows) - SHOWN} earlier</summary>\n"
                    f'<ol class="shelf">\n{"".join(rows[SHOWN:])}</ol>\n</details>\n'
                )
        parts.append("<h2>Discussed with</h2>\n")
        if page.people:
            parts.append('<ul class="plain">\n')
            for person in page.people:
                when = f"{_plural(person.days, 'day')}, the last {person.last}"
                parts.append(
                    f"<li>{self.link(escape(person.name), _person_path(person.person))}"
                    f' <span class="mute">{escape(when)}</span></li>\n'
                )
            parts.append("</ul>\n")
        else:
            parts.append('<p class="mute">nobody the record names</p>\n')
        if page.unplaced:
            parts.append(f'<p class="mute">and {page.unplaced} not yet placed</p>\n')
        parts.append("<h2>Documents <small>references, never copies</small></h2>\n")
        if page.documents:
            parts.append('<ol class="shelf">\n')
            for d in page.documents:
                parts.append(
                    f'<li title="{escape(d.ref)}"><span class="mute">{escape(d.last)}</span>'
                    f' <span class="badge">{escape(d.kind)}</span> {escape(ideas.document_text(d))}</li>\n'
                )
            parts.append("</ol>\n")
        else:
            parts.append('<p class="mute">none</p>\n')
        if page.titles:
            parts.append('<h2>Title thread</h2>\n<ul class="plain">\n')
            parts.extend(f"<li>{escape(t)}</li>\n" for t in page.titles)
            parts.append("</ul>\n")
        if page.words:
            parts.append('<h2>Words <small>the Notion deltas, by month</small></h2>\n<ul class="plain">\n')
            parts.extend(f"<li>{escape(month)} {n:+,}</li>\n" for month, n in page.words.items())
            parts.append("</ul>\n")
        parts.append("<h2>Status lines</h2>\n")
        if page.history:
            parts.append('<ol class="shelf">\n')
            for s in page.history:
                text = escape(
                    f"{s.status} ({s.proposed_by or 'owner'})" + (f": {s.reason}" if s.reason else "")
                )
                if not s.standing:
                    text = f'<s class="retracted">{text}</s> <span class="mute">retracted</span>'
                elif s.current:
                    text += ' <span class="mute">current</span>'
                day = f'<span class="mute">{escape(s.day)}</span>'
                parts.append(f'<li title="line {escape(s.line)}">{day} {text}</li>\n')
            parts.append("</ol>\n")
        else:
            parts.append('<p class="mute">none yet</p>\n')
        if report is not None:
            parts.append(self._idea_queue_html(report, 1, into=idea.id))
        parts.append(f"<p>{self.link('Ideas', '/ideas')}</p>\n")
        return self.document(idea.label, "".join(parts), style=IDEAS_STYLE)

    def _idea_item(self, item: ideas.Item) -> str:
        day = self.link(escape(item.day), f"/day/{item.day}")
        return (
            f'<li title="line {escape(item.line)}{DOT}{escape(item.source)}{DOT}by its {escape(item.via)}">'
            f'{day} <span class="badge">{escape(item.kind)}</span> {escape(item.what)}</li>\n'
        )

    def _idea_status_form(self, idea: entities.Entity, status: entities.Status | None) -> str:
        """The status form: what `logbook status idea IDEA DISPOSITION [--reason …] [--at DAY]` writes."""
        current = None if status is None else status.status
        choices = "".join(
            f'<option value="{s}"{" selected" if s == current else ""}>{s}</option>'
            for s in entities.DISPOSITIONS[entities.IDEA]
        )
        return (
            '<section class="acts">\n'
            f'<form class="act" method="post" action="{IDEAS_STATUS}">'
            f'<input type="hidden" name="idea" value="{escape(idea.id)}">'
            f'<input type="hidden" name="back" value="{escape(_idea_path(idea.id))}">'
            f'<select name="status" aria-label="status">{choices}</select>'
            '<input type="text" name="reason" placeholder="why, in your words (killed needs one)"'
            ' aria-label="reason" autocomplete="off">'
            '<input type="date" name="at" aria-label="the day you decided">'
            '<button name="act" value="status">Set status</button></form>\n'
            '<p class="mute">One <code>status/v1</code> line, tier 2; with a reason, first a note in your'
            " words, on the day and in search, as <code>status idea</code> writes them.</p>\n</section>\n"
        )

    def _write_ideas(self, path: str, form: Mapping[str, str]) -> Response:
        """An Ideas form, under the record's writer lock and never waiting for it: another command
        writing is the Library's one answer (`_busy`), and nothing is written (a head that moved under
        the act is a 409 too). The review acts on the proposal `id` (`act` `accept`, `name` with the
        field `name`, `reject`) through `entity_review.accept` and `reject`, what `review idea
        --accept`, `--name` and `--reject` call; an idea's status (`status`,
        `reason`, `at`) through `entity_status.write`, what `status idea IDEA DISPOSITION` calls. A
        proposal no longer in the queue, or an idea the record does not name, is a 409; an answer the
        record refuses a 400. Done, a 303 to `back` when it is one of the Ideas pages."""
        if not self._idea_acts():
            return self._error(
                403,
                "this page reads no tier 2, an idea's status's tier: it writes nothing; `logbook serve`"
                " reads every tier",
            )
        with self._write_lock, self._review_lock:
            try:
                with self.lb.writer(command="logbook serve", wait=False):
                    self.current()
                    if path == IDEAS_REVIEW:
                        return self._idea_review(form)
                    return self._idea_status(form)
            except HeadMoved as e:
                return self._error(409, str(e))
            except (
                entities.EntityError,
                stays.SettingsError,
                policy.PolicyError,
            ) as e:  # a setting, not the form
                return self._error(500, str(e))

    def _idea_review(self, form: Mapping[str, str]) -> Response:
        act, proposal_id = form.get("act", ""), form.get("id", "")
        if act not in ("accept", "name", "reject") or not proposal_id:
            return self._error(400, "the form names a proposal (id) and an act: accept, name or reject")
        report = entity_review.read(self.lb, entities.IDEA)
        found = [p for p in report.proposals if p.id == proposal_id]
        if not found:
            return self._error(
                409,
                f"{proposal_id} is not in the queue: answered already, or the page was older than the"
                " record; /ideas is the queue as it stands",
            )
        p = found[0]
        try:
            if act == "accept":
                entity_review.accept(self.lb, report, [(p, None)])
            elif act == "name":
                entity_review.accept(self.lb, report, [(p, form.get("name", ""))])
            else:
                entity_review.reject(self.lb, report, [p])
        except (entity_review.ReviewError, entities.EntityError) as e:
            return self._error(400, str(e))
        return Response(303, b"", location=_ideas_back(form.get("back"), "/ideas"))

    def _idea_status(self, form: Mapping[str, str]) -> Response:
        idea_id = form.get("idea", "")
        if idea_id not in ideas.named(self.lb):
            return self._error(
                409, "the form names no idea of this record: the page was older than the record"
            )
        reason = form.get("reason", "")
        at = form.get("at", "").strip()
        try:
            entity_status.write(
                self.lb,
                entities.IDEA,
                idea_id,
                form.get("status", ""),
                reason if reason.strip() else None,
                at or None,
            )
        except (entity_status.StatusError, entities.EntityError) as e:
            return self._error(400, str(e))
        return Response(303, b"", location=_ideas_back(form.get("back"), _idea_path(idea_id)))

    def _write_manifest(self, path: str, form: Mapping[str, str]) -> Response:
        """A Manifest form, under the record's writer lock and never waiting for it: another command
        writing is the Library's one answer (`_busy`), and nothing is written (a head that moved
        under the act is a 409 too). The review acts on the proposal `id` (`act` `accept`, `name`
        with the field `name`, `reject`) through `entity_review.accept` and `reject`, what `review
        org --accept`, `--name` and `--reject` call; an org's status (`status`, `reason`, `at`,
        `portfolio`) through `entity_status.write`, what `status org ORG DISPOSITION` calls. A
        proposal no longer in the queue, or an org the record does not name, is a 409; an answer the
        record refuses a 400. Done, a 303 to `back` when it is one of the Manifest's own pages."""
        if not self._acts():
            return self._error(
                403,
                "this page reads no tier 3, and an org's status, a no on a merchant and the queue's"
                " merchants are tier 3: it writes nothing; `logbook serve` reads every tier",
            )
        with self._write_lock, self._review_lock:
            try:
                with self.lb.writer(command="logbook serve", wait=False):
                    self.current()
                    if path == MANIFEST_REVIEW:
                        return self._org_review(form)
                    return self._org_status(form)
            except HeadMoved as e:
                return self._error(409, str(e))
            except (
                entities.EntityError,
                stays.SettingsError,
                policy.PolicyError,
            ) as e:  # a setting, not the form
                return self._error(500, str(e))

    def _org_review(self, form: Mapping[str, str]) -> Response:
        act, proposal_id = form.get("act", ""), form.get("id", "")
        if act not in ("accept", "name", "reject") or not proposal_id:
            return self._error(400, "the form names a proposal (id) and an act: accept, name or reject")
        report = entity_review.read(self.lb, entities.ORG)
        found = [p for p in report.proposals if p.id == proposal_id]
        if not found:
            return self._error(
                409,
                f"{proposal_id} is not in the queue: answered already, or the page was older than the"
                " record; /manifest is the queue as it stands",
            )
        p = found[0]
        try:
            if act == "accept":
                entity_review.accept(self.lb, report, [(p, None)])
            elif act == "name":
                entity_review.accept(self.lb, report, [(p, form.get("name", ""))])
            else:
                entity_review.reject(self.lb, report, [p])
        except (entity_review.ReviewError, entities.EntityError, assets.AssetError) as e:
            return self._error(400, str(e))
        return Response(303, b"", location=_back(form.get("back"), "/manifest"))

    def _org_status(self, form: Mapping[str, str]) -> Response:
        org_id = form.get("org", "")
        if org_id not in orgs.named(self.lb):
            return self._error(
                409, "the form names no org of this record: the page was older than the record"
            )
        reason = form.get("reason", "")
        at = form.get("at", "").strip()
        try:
            entity_status.write(
                self.lb,
                entities.ORG,
                org_id,
                form.get("status", ""),
                reason if reason.strip() else None,
                at or None,
                portfolio=_portfolio_asked(form),
            )
        except (entity_status.StatusError, entities.EntityError) as e:
            return self._error(400, str(e))
        return Response(303, b"", location=_back(form.get("back"), _org_path(org_id)))

    def page_assets(self) -> str:
        registry = assets.read(self.lb.root)
        body = "<h1>Assets</h1>\n"
        if not registry:
            body += f"<p>no assets registered ({escape(assets.ASSETS_FILE)}); `logbook assets add`</p>\n"
            return self.document("assets", body, style=TABLES_STYLE)
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
        whole = self._record_days()  # the days the Day and the front page give the record
        today = day_start.of(self.lb.meta).today(self.now()).isoformat()
        last = None if whole is None else whole[1]
        body += self._last_spoke("The record's last day is", last, today, "each fix's age here runs to now")
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
        return self.document("assets", body, style=TABLES_STYLE)

    def page_world(self, first: str | None, last: str | None) -> str:
        """`logbook export world`'s page, read as the export reads it by default (the `world` ceiling of
        the policy, the record's days or `from` and `to`): the same JSON, the same script, the
        Library's navigation above it and the policy in the header, not in the page."""
        found = world.library_page(self.lb, first, last, self.nav, self.airports, self._today_of())
        if found is None:
            return self.document(
                "world", "<h1>The world</h1>\n<p>the record has no day yet: nothing to draw</p>\n"
            )
        return found

    def _activity(self, first: str, last: str) -> list[dict[str, Any]]:
        """`Index.activity` of the record as it stands, read once per window: the page moves with the
        clock, what it counts only with the head."""

        return self.shared(("activity", first, last), lambda: gaps.activity_of(self.lb, first, last))

    def page_gaps(self, since: str | None) -> str:
        data = gaps.report(self.lb, since=since, activity=self._activity, instant=self.now())
        tz = ZoneInfo(data["timezone"])
        body = (
            "<h1>Gaps <small>where each source went quiet</small></h1>\n"
            f'<form class="window" action="/gaps" method="get">'
            f'<label>since <input type="date" name="since" value="{escape(data["since"] or "")}"></label> '
            "<button>show</button></form>\n"
        )
        if not data["sources"]:
            body += "<p>no lines</p>\n"
            return self.document("gaps", body, style=TABLES_STYLE)
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
        newest = max(s["last"] for s in data["sources"] if s["lines"])
        body += self._last_spoke(
            "The record's last line is from",
            day_start.of(self.lb.meta).day_of(newest),
            data["today"],
            f"every silence and every missing day here runs to today, {data['today']}",
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
        return self.document("gaps", body, style=TABLES_STYLE)


# -- the Day's rows ---------------------------------------------------------------------------------------


def _entry_html(
    entry: Mapping[str, Any],
    tz: ZoneInfo,
    inside: bool = False,
    expanded: bool = False,
    name_this: Callable[[Mapping[str, Any]], str] | None = None,
    syntheses: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    star: Toggle | None = None,
    photos: Mapping[str, str] | None = None,
    rows: Rows | None = None,
) -> str:
    """One timeline row: the clock, the kind, what it was; then an `aboard` entry's inner rows;
    then, behind a toggle, the attachments by name and the company. The grammar is `day.rows`'.
    `name_this` gives a stay printed as coordinates its link to the Places page; `syntheses` (by
    transcript line, `day.syntheses_of`) put a call's synthesis under the call, behind a toggle of its
    own, or the policy's row for one the `dream` entry withholds; `star` gives a row that is a line
    its star (a stay or a move is derived, not a line, and has none; a synthesis is a model's draft
    and has none); `photos` names the photos a row counts, each with its star; `rows` gives a row that
    is a line its link to the line as written and a row's photos their strip under it (`Rows`)."""
    if entry["kind"] == day_reader.FLIGHT:
        route = f"{entry['carrier']} {entry['number']}  {entry['from']} {ARROW} {entry['to']}"
        clock = day_reader.span_text(entry["start"], entry["end"], tz)
        line = str(entry["line"])
        return (
            f'<li class="row flight" id="{_row_id(line)}" title="line {escape(line)}">'
            f'<span class="clock">{escape(clock)}</span> <span class="kind">flight</span> '
            f"{escape(route)}{DOT}{escape(str(entry['evidence']))}"
            f"{star([line], False) if star is not None else ''}{rows.raw([line]) if rows is not None else ''}"
            "</li>\n"
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
                {**s, "attached": None, "with": None},
                tz,
                inside=True,
                expanded=expanded,
                name_this=name_this,
                star=star,
                photos=photos,
                rows=rows,
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
        out.append(_attached_html(entry.get("attached"), tz, syntheses, expanded, star, photos, rows))
        if confirmed or proposed:
            text = ", ".join(day_reader.companion_text(c) for c in confirmed)
            more = ", ".join(day_reader.companion_text(c) for c in proposed)
            if more:
                text = f"{text}{DOT}proposed {more}" if text else f"proposed {more}"
            out.append(f'<p class="with">with {escape(text)}</p>\n')
        out.append("</details>")
    if rows is not None and entry.get("attached"):
        out.append(rows.strip(entry["attached"]["photos"]["lines"]))
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


def _owner_html(
    data: Mapping[str, Any], star: Toggle | None = None, raw: Callable[[Sequence[str]], str] | None = None
) -> str:
    """RFC 0036 on the Day: the reviews made on the day, the goal's current text beside each, and
    `written` when it was written later; then the goal and chapter lines written on the day, marked
    when superseded. Nothing on a day with none. Each is the owner's line and carries its star
    (`star`); a superseded one only while it is starred, since a star names the line that stands; and
    its link to the line as written (`raw`)."""
    parts: list[str] = []
    if data.get("reviews"):
        parts.append('<h2>Reviews</h2>\n<ul class="unplaced">\n')
        for row in data["reviews"]:
            text = goals.review_row_text(row, str(data["day"]), str(data["tz"]))
            line = str(row["line"])
            mark = (star([line], False) if star is not None else "") + (
                raw([line]) if raw is not None else ""
            )
            parts.append(f'<li id="{_row_id(line)}" title="line {escape(line)}">{escape(text)}{mark}</li>\n')
        parts.append("</ul>\n")
    rows = [
        *(("goal", row, goals.goal_text(row)) for row in data.get("goals") or ()),
        *(("chapter", row, chapter.row_text(row)) for row in data.get("chapters") or ()),
    ]
    if rows:
        parts.append('<h2>Goals and chapters</h2>\n<ul class="unplaced">\n')
        for kind, row, text in rows:
            mark = f"{DOT}superseded" if row.get("superseded") else ""
            line = str(row["line"])
            starred = star([line], bool(row.get("superseded"))) if star is not None else ""
            starred += raw([line]) if raw is not None else ""
            parts.append(
                f'<li id="{_row_id(line)}" title="line {escape(line)}"><span class="kind">{kind}</span> '
                f"{escape(text + mark)}{starred}</li>\n"
            )
        parts.append("</ul>\n")
    return "".join(parts)


def _draft_html(draft: Mapping[str, Any], star: Toggle | None = None) -> str:
    """The standing draft of the day (RFC 0036) above the timeline: headed as a draft, one
    paragraph per segment with its evidence ids (the whole id on hover), an unsupported segment a
    muted block marked with the word, never run into the prose around it; then the events it
    proposes, a proposed one greyed and marked, a confirmed one plain with the line it became (the
    event itself is in the timeline, among the day's events). A draft is a model's proposal and
    takes no star (`star`): the confirmed one carries the star of the event line it became."""
    return (
        f'<h2>Draft</h2>\n<p class="mute">{escape(drafts.head_text(draft))}</p>\n<div class="draft">\n'
        f"{_draft_body(draft, star)}</div>\n"
    )


def _draft_folded(draft: Mapping[str, Any]) -> str:
    """The standing draft of a unit other than the day (a journey), folded under its head: a
    proposal until the owner confirms it, never shown open as if it were the record."""
    return (
        f'<details class="draft"><summary>{escape(drafts.head_text(draft))}</summary>\n<div class="draft">\n'
        f"{_draft_body(draft)}</div>\n</details>\n"
    )


def _draft_body(draft: Mapping[str, Any], star: Toggle | None = None) -> str:
    """A draft's segments, one paragraph each with its evidence ids (the whole id on hover); an
    unsupported one a muted block marked with the word and why, never run into the prose; then the
    events it proposes and the earlier drafts."""
    parts: list[str] = []
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
    if draft.get("proposals"):
        parts.append('<ul class="proposals">\n')
        parts.extend(_proposal_html(p, star) for p in draft["proposals"])
        parts.append("</ul>\n")
    if draft.get("earlier"):
        earlier = ", ".join(escape(drafts.short_id(e)) for e in draft["earlier"])
        parts.append(f'<p class="mute">earlier drafts: {earlier}</p>\n')
    return "".join(parts)


def _proposal_html(p: Mapping[str, Any], star: Toggle | None = None) -> str:
    """One proposed event: greyed and marked `proposed` with its evidence ids until the owner accepts
    it (`day sign --accept N`), then plain and marked with the event line it became, and that line's
    star (`star`); muted and marked `unsupported` when its evidence is no longer on the day. A
    proposal is the model's and takes no star until the owner has made it a line."""
    head = f'<span class="kind">event {int(p["number"])}</span> {escape(drafts.proposal_text(p))}'
    confirmed = p.get("confirmed")
    if confirmed:
        line = escape(str(confirmed["line"]))
        mark = star([str(confirmed["line"])], False) if star is not None else ""
        return (
            f'<li class="proposal confirmed" title="line {line}">{head}'
            f" <small>confirmed as #{int(confirmed['seq'])}</small>{mark}</li>\n"
        )
    if not p["supported"]:
        why = f": {escape(str(p['why']))}" if p.get("why") else ""
        return f'<li class="proposal unsupported mute">{head} <small>{drafts.UNSUPPORTED}{why}</small></li>\n'
    ids = ", ".join(
        f'<span class="id" title="line {escape(e)}">{escape(drafts.short_id(e))}</span>'
        for e in p["evidence"]
    )
    return f'<li class="proposal proposed mute">{head} <small>proposed [{ids}]</small></li>\n'


def _withheld_html(row: Mapping[str, Any], heading: bool = True) -> str:
    """A standing draft the `dream` entry no longer allows (`drafts.withheld_json`): one muted line
    that says so and why, and nothing of what the draft says; under the Draft heading of an earlier
    draft the entry does allow, when the Day shows one. A journey's row and page carry it without a
    heading, after the folded draft the entry does allow, when there is one."""
    line = escape(str(row["line"]))
    head = "<h2>Draft</h2>\n" if heading else ""
    return f'{head}<p class="mute" title="line {line}">{escape(drafts.withheld_text(row))}</p>\n'


def _synthesis_html(block: Mapping[str, Any], expanded: bool = False) -> str:
    """A call's synthesis (RFC 0036, `transcript synthesize`) under the call's row, behind a toggle
    closed unless the page is expanded: the summary says what it holds and which model wrote it;
    inside, one paragraph per segment, actions on top, an action with its assignee and due hint, each
    with where in the call it rests (the line on hover), an unsupported one a muted block marked with
    the word, never run into the prose around it. A synthesis the `dream` entry no longer allows
    (`drafts.withheld_json`) is one muted line that says so and why, and nothing of what it says."""
    if drafts.is_withheld(block):
        line = escape(str(block["line"]))
        return f'\n<p class="synthesis mute" title="line {line}">{escape(drafts.withheld_text(block))}</p>'
    parts = [
        f'\n<details class="synthesis"{" open" if expanded else ""}>'
        f"<summary>{escape(drafts.synthesis_summary(block))}</summary>\n"
    ]
    for segment in block["segments"]:
        label = drafts.SYNTHESIS_LABELS.get(str(segment.get("part")), "")
        head = f'<span class="kind">{escape(label)}</span> ' if label else ""
        assigned = drafts.assignment_text(segment)
        who = f" <em>{escape(assigned)}</em>" if assigned else ""
        if segment["supported"]:
            line = escape(str(block["transcript"]))
            where = f' <small title="line {line}">[{escape(drafts.where_text(segment))}]</small>'
            parts.append(f'<p class="segment">{head}{escape(segment["text"])}{who}{where}</p>\n')
        else:
            why = f": {escape(str(segment['why']))}" if segment.get("why") else ""
            parts.append(
                f'<p class="segment unsupported mute">{head}~ {escape(segment["text"])}{who}'
                f" <small>{drafts.UNSUPPORTED}{why}</small></p>\n"
            )
    parts.append("</details>")
    return "".join(parts)


def _attached_html(
    attached: Mapping[str, Any] | None,
    tz: ZoneInfo,
    syntheses: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    expanded: bool = False,
    star: Toggle | None = None,
    photos: Mapping[str, str] | None = None,
    rows: Rows | None = None,
) -> str:
    """A row's attachments, one item each, its star after it (`star`) and its link to its line
    (`rows`), then a call's synthesis under it, which has none; a keeper's row carries a star only
    while it is one, and the photos a row counts are named, each with its own; a Drive file's edits
    are one item (`_drive_folded`)."""
    if not attached:
        return ""
    raw = rows.raw if rows is not None else (lambda ids: "")
    items: list[tuple[str, str, Sequence[str]]] = []  # kind, text, the lines it points at
    for e in _drive_folded(attached["events"], rows.lines if rows is not None else {}, "start"):
        span = day_reader.span_text(e["start"], e["end"], tz)
        items.append(("event", f"{e['title']} {span}{day_reader.sources_text(e)}", e["lines"]))
    for t in attached["transcripts"]:
        items.append(("transcript", t["title"] + day_reader.voices_text(t), [t["line"]]))
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
        blocks = (syntheses or {}).get(lines[0], []) if kind == "transcript" and lines else []
        mark, named = "", ""
        if star is not None and kind not in ("messages", "photos"):
            mark = star(lines, kind == "keeper")
        if kind != "messages":
            mark += raw(lines[:1]) if kind != "photos" else ""
        if star is not None and kind == "photos" and photos:
            named = ": " + ", ".join(
                f'<span id="{_row_id(id_)}">{escape(photos[id_])}{star([id_], False)}{raw([id_])}</span>'
                for id_ in lines
                if id_ in photos
            )
        anchor = f' id="{_row_id(lines[0])}"' if lines and kind not in ("messages", "photos") else ""
        talk = (
            _conversations_html(attached[kind].get("conversations"), tz, raw, expanded)
            if kind == "messages"
            else ""
        )
        out.append(
            f'<li{anchor} title="{escape(_plural(len(lines), "line"))}: {escape(title)}">'
            f'<span class="kind">{escape(kind)}</span> {escape(text)}{named}{mark}{talk}'
            f"{''.join(_synthesis_html(block, expanded) for block in blocks)}</li>\n"
        )
    out.append("</ul>\n")
    return "".join(out)


def _conversations_html(
    found: Sequence[Mapping[str, Any]] | None,
    tz: ZoneInfo,
    raw: Callable[[Sequence[str]], str],
    expanded: bool,
) -> str:
    """A row's messages by conversation (`day.conversations`), each folded under who it was with, the
    network and how many; inside, the messages in time order (`_message_html`). A conversation of
    more than `LONG_CONVERSATION` shows its first `SHOWN_MESSAGES` and folds the rest under "show
    all N". Every fold closed, unless the page is `?open=1`."""
    if not found:
        return ""
    is_open = " open" if expanded else ""
    out = ['\n<ul class="conversations">\n']
    for c in found:
        said = f"{c['counterpart']}{DOT}{c['network']}{DOT}{_plural(int(c['count']), 'message')}"
        items = [_message_html(m, tz, raw) for m in c["messages"]]
        shown, rest = (
            (items[:SHOWN_MESSAGES], items[SHOWN_MESSAGES:])
            if len(items) > LONG_CONVERSATION
            else (items, [])
        )
        out.append(
            f'<li><details class="conversation"{is_open}><summary>{escape(said)}</summary>\n'
            f'<ol class="messages">\n{"".join(shown)}</ol>\n'
        )
        if rest:
            out.append(
                f'<details class="all"{is_open}><summary>show all {int(c["count"]):,}</summary>\n'
                f'<ol class="messages">\n{"".join(rest)}</ol>\n</details>\n'
            )
        out.append("</details></li>\n")
    out.append("</ul>")
    return "".join(out)


def _message_html(m: Mapping[str, Any], tz: ZoneInfo, raw: Callable[[Sequence[str]], str]) -> str:
    """One message: the clock, sent or received, who wrote it in a group, the text as far as
    `day.TEXT_CHARS` (cut with an ellipsis), and the link to its line, where the whole of it is."""
    way = "sent" if m["from_me"] else "received"
    who = f'<span class="who">{escape(str(m["who"]))}</span>: ' if m.get("who") else ""
    return (
        f'<li class="message"><span class="clock">{_hm(str(m["at"]), tz)}</span> '
        f'<span class="way">{way}</span> {who}{escape(str(m["text"]))}{raw([m["line"]])}</li>\n'
    )


def _held_html(
    data: Mapping[str, Any], tz: ZoneInfo, raw: Callable[[Sequence[str]], str], expanded: bool
) -> str:
    """ "Everything this day held", at the foot of the Day: every line of the day (`day.hold`), a table
    per source in the sources row's order, its lines in time order, each the clock, the kind, one
    line of what it was and the link to its line; folded, the counts per source on its summary, as
    the sources row has them. Closed, unless the page is `?open=1`. Nothing on a day with no line."""
    rows = data.get("held") or []
    if not rows:
        return ""
    by: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        by.setdefault(str(row["source"]), []).append(row)
    counts = DOT.join(f"{s['source']} {int(s['lines']):,}" for s in data["sources"])
    out = [
        f'<section class="held">\n<details class="held"{" open" if expanded else ""}>'
        f"<summary>{escape(f'Everything this day held{DOT}{counts}')}</summary>\n"
    ]
    for source in [*(str(s["source"]) for s in data["sources"]), *by]:
        found = by.pop(source, None)
        if not found:
            continue
        out.append(f"<h3>{escape(source)} <small>{escape(_plural(len(found), 'line'))}</small></h3>\n")
        cells: list[list[Cell]] = [
            [
                (_hm(str(row["at"]), tz), "at"),
                f'<span class="kind">{escape(str(row["kind"]))}</span>',
                f"{escape(str(row['what']))}{'' if row.get('withheld') else raw([row['line']])}",
            ]
            for row in found
        ]
        out.append(_table([("at", "at"), "kind", "what"], cells))
    out.append("</details>\n</section>\n")
    return "".join(out)


def _drafted(row: Mapping[str, Any]) -> bool:
    """Whether a sources row or a held row is a model's: its source is `model:<name>`
    (`drafts.SOURCE_PREFIX`)."""
    return str(row.get("source") or "").startswith(drafts.SOURCE_PREFIX)


@functools.lru_cache(maxsize=8192)
def _hm(stamp: str, tz: ZoneInfo) -> str:
    """The local clock of a stamp, escaped, once: a busy day's message is on the page twice, under its
    row and in "Everything this day held"."""
    return escape(day_reader.span_text(stamp, None, tz))


def _row_id(line: str) -> str:
    """The id of the row a line is listed in, the anchor a star's form comes back to."""
    return "l-" + re.sub(r"[^A-Za-z0-9-]", "", line)


DRIVE = "drive"  # the source of `sync drive`'s lines: a file's activities of an hour, one line with a count
DRIVE_NOUNS = {  # `extra.activity` → what the folded row counts
    "edit": "edit",
    "comment": "comment",
    "rename": "rename",
    "move": "move",
    "share": "share",
    "create": "creation",
    "trash": "trashing",
    "delete": "deletion",
    "restore": "restore",
}


def _drive_file(item: Mapping[str, Any], lines: Mapping[str, Line]) -> tuple[str, str] | None:
    """(the file's id, its name) of a Day item whose line is a Drive line (`sync drive`), else None."""
    ids = item.get("lines") or [item.get("line")]
    line = lines.get(str(ids[0])) if ids else None
    if line is None or line.get("source") != DRIVE or line.get("kind") != "event":
        return None
    extra = (line.get("payload") or {}).get("extra")
    file = extra.get("file") if isinstance(extra, dict) else None
    if not isinstance(file, dict) or not isinstance(file.get("id"), str) or not file["id"]:
        return None
    return file["id"], str(file.get("name") or file["id"])


def _drive_folded(
    items: Sequence[Mapping[str, Any]], lines: Mapping[str, Line], start: str
) -> list[Mapping[str, Any]]:
    """A Day's items (a row's events, or the unplaced, whose start is under `start`) with the many
    lines of one Drive file read as one item where the first of them was: `sync drive` writes a line
    per file, hour and activity, so a morning of editing is several; folded, the item is the file's
    name and what was done to it, counted (`Budget 2027 · 5 edits, 2 comments`), from the first
    start to the last end, standing for every line (its star and its link name the first). The fold
    is the page's alone: `logbook day` and the JSON list each line, as Notion's backfill folds in
    the reader (`events.backfilled`) and these do not. An item no other line of its file joins
    stays as it is."""
    groups: dict[str, list[int]] = {}
    for n, item in enumerate(items):
        found = _drive_file(item, lines)
        if found is not None:
            groups.setdefault(found[0], []).append(n)
    out: list[Mapping[str, Any]] = []
    for n, item in enumerate(items):
        found = _drive_file(item, lines)
        if found is None or len(groups[found[0]]) == 1:
            out.append(item)
            continue
        if groups[found[0]][0] != n:
            continue
        members = [items[i] for i in groups[found[0]]]
        ids = [str(i) for m in members for i in (m.get("lines") or [m["line"]])]
        counts: dict[str, int] = {}
        for id_ in ids:
            extra = ((lines.get(id_) or {}).get("payload") or {}).get("extra") or {}
            activity = str(extra.get("activity") or "edit")
            count = extra.get("count")
            counts[activity] = counts.get(activity, 0) + (
                count if isinstance(count, int) and count > 0 else 1
            )
        said = ", ".join(_plural(c, DRIVE_NOUNS.get(a, a)) for a, c in counts.items())
        ends = [str(m.get("end") or m[start]) for m in members]
        out.append(
            {
                **item,
                "title": f"{found[1]}{DOT}{said}",
                start: min(str(m[start]) for m in members),
                "end": max(ends, key=_instant),
                "line": ids[0],
                "lines": ids,
            }
        )
    return out


TRACK_W, TRACK_PAD = 320, 18


def _track_svg(timeline: Sequence[Mapping[str, Any]]) -> str:
    """The day's track on a plain canvas, drawn here from the record's own coordinates: the timeline's
    stays and stops with a position (an `aboard` entry by its own, when it has one) as dots numbered
    in the timeline's order, the stays at one point one dot, and the move between two of them a
    straight line, dashed where the track has a gap, a flight or a stay with no position between;
    an equirectangular projection about their mean latitude and a scale bar. No tile, no image, no
    fetch; nothing on a day with no stay that has a position."""
    located: list[tuple[int, float, float]] = []
    links: list[tuple[int, int, bool]] = []
    broken = False
    for entry in timeline:
        if entry["kind"] == day_reader.FLIGHT or entry.get("gap"):
            broken = True
            continue
        if entry["kind"] == stays.MOVE:
            continue
        if entry.get("lat") is None or entry.get("lon") is None:
            broken = True  # a stay with no position: what lies between is not drawn as one move
            continue
        located.append((len(located) + 1, float(entry["lat"]), float(entry["lon"])))
        if len(located) > 1:
            links.append((len(located) - 2, len(located) - 1, broken))
        broken = False
    if not located:
        return ""
    k = math.cos(math.radians(sum(lat for _, lat, _ in located) / len(located)))
    xs = [lon * k for _, _, lon in located]
    ys = [-lat for _, lat, _ in located]
    inner = TRACK_W - 2 * TRACK_PAD
    scale = inner / max(max(xs) - min(xs), (max(ys) - min(ys)) * 2, 0.005)  # px per degree; 500 m at least
    height = max(120, min(240, round((max(ys) - min(ys)) * scale) + 2 * TRACK_PAD))
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    at = [
        (round((x - cx) * scale + TRACK_W / 2), round((y - cy) * scale + height / 2))
        for x, y in zip(xs, ys, strict=True)
    ]
    out = [f'<svg class="track" viewBox="0 0 {TRACK_W} {height}" role="img" aria-label="the day\'s track">']
    for a, b, gap in links:
        (x1, y1), (x2, y2) = at[a], at[b]
        if (x1, y1) != (x2, y2):
            out.append(f'<line{' class="gap"' if gap else ""} x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>')
    dots: dict[tuple[int, int], list[int]] = {}
    for (n, _, _), point in zip(located, at, strict=True):
        dots.setdefault(point, []).append(n)
    for x, y in dots:
        out.append(f'<circle cx="{x}" cy="{y}" r="5"/>')
    for (x, y), numbers in dots.items():
        anchor, tx = ("end", x - 8) if x > TRACK_W * 0.7 else ("start", x + 8)
        label = ", ".join(str(n) for n in numbers)
        out.append(f'<text x="{tx}" y="{y + 4}" text-anchor="{anchor}">{label}</text>')
    km = 111.2 / scale * (TRACK_W / 4)
    bar_km = max(
        (b for b in (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000) if b <= km), default=0.1
    )
    bar = bar_km / 111.2 * scale
    out.append(f'<line x1="8" y1="{height - 8}" x2="{8 + bar:.1f}" y2="{height - 8}"/>')
    out.append(f'<text x="8" y="{height - 12}">{bar_km:g} km</text>')
    out.append("</svg>\n")
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
        escape(f" {ARROW} ".join(trips.route_names(trip.route)))
        if trip.route
        else '<span class="mute">unknown</span>',
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


STAYS_W, STAYS_PAD = 320, 18


def _stays_svg(route: Sequence[Mapping[str, Any]]) -> str:
    """A journey's stays as dots on a plain canvas, drawn here: an equirectangular projection about
    their mean latitude, one dot per place slept at (its area by the nights there, the stays at one
    point one dot), each with the numbers of the stays at it, and a scale bar. No tile, no fetch."""
    located = [s for s in route if s["lat"] is not None and s["lon"] is not None]
    if not located:
        return '<p class="mute">no stay with a position to draw</p>\n'
    k = math.cos(math.radians(sum(float(s["lat"]) for s in located) / len(located)))
    xs = [float(s["lon"]) * k for s in located]
    ys = [-float(s["lat"]) for s in located]
    span_x, span_y = max(xs) - min(xs), max(ys) - min(ys)
    inner = STAYS_W - 2 * STAYS_PAD
    scale = inner / max(span_x, span_y * 2, 0.02)  # px per degree; a canvas twice as wide as high at most
    height = max(120, min(240, round(span_y * scale) + 2 * STAYS_PAD))
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    dots: dict[tuple[int, int], list[Mapping[str, Any]]] = {}
    for s, x, y in zip(located, xs, ys, strict=True):
        at = (round((x - cx) * scale + STAYS_W / 2), round((y - cy) * scale + height / 2))
        dots.setdefault(at, []).append(s)
    out = [f'<svg class="stays" viewBox="0 0 {STAYS_W} {height}" role="img" aria-label="the stays">']
    for (x, y), found in dots.items():
        r = 3 + math.sqrt(sum(int(s["nights"]) for s in found)) * 1.2
        label = ", ".join(str(s["n"]) for s in found)
        anchor, tx = ("end", x - r - 3) if x > STAYS_W * 0.7 else ("start", x + r + 3)
        out.append(f'<circle cx="{x}" cy="{y}" r="{min(r, 14):.1f}"/>')
        out.append(f'<text x="{tx:.0f}" y="{y + 4}" text-anchor="{anchor}">{escape(label)}</text>')
    km = 111.2 / scale * (STAYS_W / 4)
    bar_km = max(
        (b for b in (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000) if b <= km), default=0.1
    )
    bar = bar_km / 111.2 * scale
    out.append(f'<line x1="8" y1="{height - 8}" x2="{8 + bar:.1f}" y2="{height - 8}"/>')
    out.append(f'<text x="8" y="{height - 12}">{bar_km:g} km</text>')
    out.append("</svg>\n")
    return "".join(out)


def _dates(text: str) -> str:
    """A span of days that never breaks inside a day's hyphens, only at its dash."""
    return f" {EN_DASH} ".join(
        f'<span class="dates">{escape(day)}</span>' for day in text.split(f" {EN_DASH} ")
    )


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


def _keep_item(day: str, n: int, part: str, block: Mapping[str, Any]) -> str:
    """One keepable sentence or link of the pencil in the Keep and sign form. Kept: in ink, with the
    line it became, and no box. Not yet: in pencil, its box numbered as `--keep` takes it, the number
    on the line above the words (never beside a name a sentence opens with), a decision's revisit day
    beside it (a later day than `day`), and what a photo's or a link's keeping writes."""
    label = escape(drafts.PART_LABELS.get(part, part))
    text = escape(str(block.get("text") or ""), quote=False)
    kept = block.get("kept")
    if kept:
        return (
            f'<li class="kept"><span class="head">{label}, kept</span> <span class="words">{text}</span>'
            f' <small class="mute">kept as #{int(kept["seq"])}</small></li>\n'
        )
    what = {drafts.PHOTO: "the photo starred, these words its note", drafts.LINK: "the link"}.get(part)
    sub = f' <small class="mute">{what}</small>' if what else ""
    revisit = ""
    if part == drafts.DECISION:
        after = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
        revisit = (
            f'<label class="revisit">revisit on <input type="date" name="{REVISIT}{n}" min="{after}"></label>'
        )
    return (
        f'<li class="pencil"><label class="pick"><input type="checkbox" name="keep" value="{n}">'
        f'<span><span class="head">keep {n}{DOT}{label}</span> <span class="words">{text}</span>{sub}</span>'
        f"</label>{revisit}</li>\n"
    )


def _keeping(form: Mapping[str, str]) -> keep.Asked:
    """What the Keep and sign form asks to keep, parsed by the function `day sign --keep` parses its
    flags with (`keep.asked`), so a click means what the command's flags mean: `keep` the numbers
    ticked, N,N; `revisit-N` a kept decision's day, a field left empty giving none; `word`, blank
    giving none; `task-N` a task's answer, `done`, `tomorrow` or `let-go` (none chosen, no line).
    `KeepError` names a field the form never sends as it is."""
    revisit = [
        f"{name[len(REVISIT) :]}={value.strip()}"
        for name, value in form.items()
        if name.startswith(REVISIT) and value.strip()
    ]
    answers: dict[str, list[str]] = {outcome: [] for outcome in plan_reader.OUTCOMES}
    for name, value in form.items():
        if not name.startswith(TASK):
            continue
        n = name[len(TASK) :]
        if value not in answers:  # the three choices, as the form words them
            raise keep.KeepError(f"task {n}'s answer is done, tomorrow or let go, not {value!r}")
        answers[value].append(n)
    return keep.asked(
        keep=form.get("keep") or None,
        revisit=revisit,
        word=form.get("word") if (form.get("word") or "").strip() else None,
        **{
            name: ",".join(answers[outcome]) or None
            for name, outcome in (
                ("done", plan_reader.DONE_TODAY),
                ("tomorrow", plan_reader.TOMORROW),
                ("let_go", plan_reader.LET_GO),
            )
        },
    )


def _tasks_digest(found: object) -> str:
    """The tasks the form answers, as the page showed them: their Notion ids in the order `show plan`
    numbers them, digested; "" for no tasks. The form carries it back, so a plan that moved since the
    page was read (a task done in Notion and synced, one added) is refused, never answered by number."""
    if not isinstance(found, plan_reader.Plan) or not found.tasks or not found.tasks["rows"]:
        return ""
    ids = json.dumps([str(row["id"]) for row in found.tasks["rows"]])
    return hashlib.sha256(ids.encode("utf-8")).hexdigest()[:16]


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

Evidence = tuple[str, Sequence[str], str | None]  # what (plain text), the line ids, the day it links


def _folded(rows: Sequence[str]) -> str:
    """The evidence pattern every page shares (the Places page's first): rows already marked up,
    `places_review.SHOWN` of them in a list, the rest behind a toggle that counts them."""
    out = ['<ul class="evidence">\n']
    out.extend(f"<li>{row}</li>\n" for row in rows[: places_review.SHOWN])
    out.append("</ul>\n")
    rest = rows[places_review.SHOWN :]
    if rest:
        out.append(f'<details><summary>… and {len(rest)} more</summary>\n<ul class="evidence">\n')
        out.extend(f"<li>{row}</li>\n" for row in rest)
        out.append("</ul>\n</details>\n")
    return "".join(out)


def _org_path(entity: str) -> str:
    return f"/org/{quote(entity, safe='')}"


def _portfolio_asked(form: Mapping[str, str]) -> str | None:
    """The portfolio a status form asks for, as `status org … --portfolio` takes it: the box as typed
    when it differs from what the page showed (`portfolio_was`), its spaces aside, an emptied box
    asking to clear it and a respelled one asking for the new spelling; None, no portfolio at all,
    when the box is as the page showed it or the form carries none, so a box left alone moves
    nothing, however the record moved since."""
    if "portfolio" not in form:
        return None
    typed = form["portfolio"]
    if typed.split() == form.get("portfolio_was", "").split():
        return None
    return typed


def _back(back: str | None, default: str, prefixes: tuple[str, ...] = ("/manifest", "/org/")) -> str:
    """Where a Manifest form returns: `back` when it is one of the Manifest's own pages (a path from
    `/manifest` or `/org/`, or another form's `prefixes`, with nothing that could make it another
    host's), else `default`."""
    if (
        back
        and back.startswith(prefixes)
        and not back.startswith("//")
        and "\\" not in back
        and ":" not in back.split("#")[0].split("?")[0]
        and all(c.isprintable() and not c.isspace() for c in back)
    ):
        return back
    return default


def _idea_path(entity: str) -> str:
    return f"/idea/{quote(entity, safe='')}"


def _ideas_back(back: str | None, default: str) -> str:
    """Where an Ideas form returns: `back` when it is one of the Ideas pages, else `default` (`_back`)."""
    return _back(back, default, ("/ideas", "/idea/"))


def _person_path(entity: str) -> str:
    return "/people/" + quote(entity, safe="")


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


def _nothing_to_review(unplaced: int, noun: str) -> str:
    """What a review queue with no proposal says under its counts, in agreement with them: with
    nothing seen and not placed, that everything is; else why what was seen is not proposed."""
    if not unplaced:
        return f"nothing to review: every {noun} the sources saw is placed or answered"
    return (
        f"nothing to review: the {unplaced:,} seen, not placed, match no {noun} you named"
        " or are ones you said no to"
    )


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
    timeout = IDLE_S  # a connection that sends nothing for this long is closed: no thread waits on it forever

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
        client, origin = str(self.client_address[0]), self.headers.get("Origin")
        response = site.write(path, form, client, origin, upload, asked=phone.Asked.of(self.headers))
        self._send(response, body=True)

    def _answer(self, body: bool) -> None:
        """A GET: what reads nothing (`Site.quick`: a built page) on this thread at once; a reading in
        the server's pool (`Server.read`), at most `renders` at a time, under the limit. Over it, the
        reading is stopped and the page is the one that says so (`Site.still_reading`), with the page
        built in the background when the server builds; a browser that leaves stops its reading, and
        is sent nothing."""
        assert isinstance(self.server, Server)
        server = self.server
        path, _, query = self.path.partition("?")
        inm = self.headers.get("If-None-Match")
        quick = server.site.quick(path, query, inm)
        if quick is not None:
            self._send(quick, body)
            return
        token = cancel.Token()
        try:
            future = server.pool.submit(server.read, path, query, inm, token)
        except RuntimeError:  # the server is closing: no reading starts
            self.close_connection = True
            return
        deadline = time.monotonic() + server.limit_s
        while True:
            try:
                response = future.result(timeout=WATCH_S)
                break
            except FuturesTimeout:
                pass
            except FuturesCancelled:  # the server closed with the reading still waiting its turn
                self.close_connection = True
                return
            if self._gone():
                token.cancel("the browser left")
                self.close_connection = True
                return
            if time.monotonic() >= deadline:
                token.cancel(f"over the limit of {server.limit_s:g} s")
                if server.rebuilder is not None:
                    server.rebuilder.ask(path + (f"?{query}" if query else ""))
                response = server.site.still_reading(path, query, server.limit_s)
                break
        if response is None:  # stopped before it was read: the limit, answered above, or a closing server
            response = server.site.still_reading(path, query, server.limit_s)
        self._send(response, body)

    def _gone(self) -> bool:
        """Whether the browser closed the connection while its page is read: readable, and nothing to
        read (a request pipelined behind this one is left where it is)."""
        try:
            readable, _, _ = select.select([self.connection], [], [], 0)
            return bool(readable) and self.connection.recv(1, socket.MSG_PEEK) == b""
        except (OSError, ValueError):
            return True

    def _send(self, response: Response, body: bool) -> None:
        """The answer, or nothing when the browser has gone: a broken pipe is the browser's leaving,
        never a traceback in the log."""
        try:
            self.send_response(response.status)
            for name, value in response.headers.items():
                self.send_header(name, value)
            self.end_headers()
            if body and response.status not in (204, 304):
                self.wfile.write(response.body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True


class Server(ThreadingHTTPServer):
    """A loopback-only HTTP server over one `Site`. Never resolves a name: `HTTPServer.server_bind`
    would look up the host's fully qualified name, and this one does not."""

    daemon_threads = True

    def __init__(self, port: int, site: Site, limit_s: float = LIMIT_S, renders: int = RENDERS):
        self.site = site
        self.rebuilder: library_build.Rebuilder | None = None
        self.limit_s = limit_s
        # the readings: at most `renders` at once, however many pages are asked for together, so a
        # whole menu opened at once never holds the record in memory a dozen times over
        self.pool = ThreadPoolExecutor(max_workers=renders, thread_name_prefix="logbook-read")
        super().__init__((HOST, port), Handler)

    def read(self, path: str, query: str, if_none_match: str | None, token: cancel.Token) -> Response | None:
        """One page read in the pool under `token`; None when it was stopped (`cancel.Cancelled`)
        before or while it was read."""
        if token.cancelled:
            return None
        try:
            with cancel.scope(token):
                return self.site.respond(path, query, if_none_match)
        except cancel.Cancelled:
            return None

    def server_close(self) -> None:
        if self.rebuilder is not None:
            self.rebuilder.stop()
        self.pool.shutdown(wait=False, cancel_futures=True)
        super().server_close()

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


def stacks() -> None:
    """Every thread's stack to stderr, the log of a service: `faulthandler`'s, which needs no lock and
    no allocation; `traceback`'s when stderr has no file under it."""
    try:
        faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
    except (AttributeError, ValueError, OSError):
        names = {t.ident: t.name for t in threading.enumerate()}
        for ident, frame in sys._current_frames().items():
            print(f"thread {names.get(ident, ident)}:", file=sys.stderr)
            print("".join(traceback.format_stack(frame)), file=sys.stderr)


class Watchdog:
    """The server asking itself, every `WATCH_EVERY_S`, for `/favicon.ico` (an empty 204 that reads
    nothing of the record), as `serve --status` asks it from outside. `STUCK_AFTER` silences in a row
    (no answer in `SILENT_S`) and it writes every thread's stack to the log, so the next hang says why,
    then `stuck`: by default the process exits (`STUCK_EXIT`), and the service manager that runs it
    starts it again. A process the system paused answers nothing and runs nothing, this thread
    included: the scheduled run restarts that one (`sync --scheduled`)."""

    def __init__(
        self,
        port: int,
        stuck: Callable[[], None] | None = None,
        every_s: float = WATCH_EVERY_S,
        silent_s: float = SILENT_S,
        after: int = STUCK_AFTER,
        say: Callable[[str], None] = lambda text: print(text, file=sys.stderr, flush=True),
    ):
        self.port, self.every_s, self.silent_s, self.after, self.say = port, every_s, silent_s, after, say
        self.stuck = stuck or self._leave
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="logbook-watchdog", daemon=True)
        self.misses = 0

    def start(self) -> Watchdog:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def answers(self) -> bool:
        connection = http.client.HTTPConnection(HOST, self.port, timeout=self.silent_s)
        try:
            connection.request("HEAD", "/favicon.ico")
            return connection.getresponse().status == 204
        except (OSError, http.client.HTTPException):
            return False
        finally:
            connection.close()

    def _run(self) -> None:
        while not self._stop.wait(self.every_s):
            self.misses = 0 if self.answers() else self.misses + 1
            if self.misses >= self.after:
                self.say(
                    f"serve: no answer from itself in {self.silent_s:g} s, {self.misses} times running;"
                    " every thread's stack follows"
                )
                stacks()
                self.stuck()
                return

    def _leave(self) -> None:
        self.say("serve: leaving, for the service manager to start it again")
        sys.stderr.flush()
        os._exit(STUCK_EXIT)


def make_server(
    lb: Logbook,
    host: str = HOST,
    port: int = PORT,
    airports: Airports | None = None,
    voice: Voice | None = None,
    built: bool = False,
    say: Callable[[str], None] | None = None,
    limit_s: float = LIMIT_S,
) -> Server:
    """The server, bound and ready to `serve_forever`. `HostError` for any host but 127.0.0.1,
    before a socket is opened; OSError when the port is taken. `voice`: how a Day hears a recording.
    `built`: answer from the pages built ahead (`library_build`; `logbook serve --built`, labs),
    rebuilt in the background after every act; False, the default, renders every page as it is asked
    for. `limit_s`: a page read longer is stopped and said so; `math.inf` reads every page to its end."""
    if host != HOST:
        raise HostError(
            f"serve binds {HOST} only, never {host!r}: the record is read from this machine, "
            "and nothing here leaves it"
        )
    if not built:
        return Server(port, Site(lb, airports, voice=voice, read_later=True), limit_s)
    library = library_build.Library(lb)
    site = Site(lb, airports, voice=voice, library=library, read_later=True)
    server = Server(port, site, limit_s)
    server.rebuilder = library_build.Rebuilder(lb, site, library, say).start()
    site.on_act = server.rebuilder.kick
    if not library.built():
        server.rebuilder.kick()  # never built on this machine: the first build starts with the server
    return server


def serve(
    lb: Logbook,
    host: str = HOST,
    port: int = PORT,
    airports: Airports | None = None,
    announce: Callable[[str], None] = print,
    voice: Voice | None = None,
    built: bool = False,
    limit_s: float = LIMIT_S,
) -> None:
    """Serve the record until Ctrl-C, every page rendered as it is asked for, or with `built`
    (`--built`, labs) from the pages built ahead; a page read longer than `limit_s` stopped and said so
    (`math.inf`: none). `HostError` and OSError as `make_server`."""
    server = make_server(lb, host, port, airports, voice, built=built, say=announce, limit_s=limit_s)
    if sys.platform != "win32":  # `kill -USR1 <pid>`: every stack to the log, the server running on
        with contextlib.suppress(AttributeError, ValueError, OSError):  # a stderr with no file under it
            faulthandler.register(signal.SIGUSR1, file=sys.stderr, all_threads=True)
    watchdog = Watchdog(int(server.server_address[1])).start()
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
        watchdog.stop()
        server.server_close()


def _shown(root: Path) -> str:
    """The record's folder as `~/Logbook` when it is under the home directory, never the user name."""
    try:
        return "~/" + root.resolve().relative_to(Path.home().resolve()).as_posix()
    except (ValueError, OSError):
        return str(root)
